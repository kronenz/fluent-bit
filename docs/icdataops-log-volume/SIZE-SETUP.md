# `_size` 활성화 & 정확 용량 검증 런북 (icdataops-dev-log)

로그 **바이트 적재량**을 namespace/app/pod/멀티라인별로 정확히 집계하려면 `_size` 메타필드가 필요하다.
라인수(count)는 문서당 크기 차이(실측 12B~1,455B, 약 120배)를 못 담고, **멀티라인은 라인수로 구분 불가**
(조인 시 1라인으로 숨음). 그래서 `sum(_size)`가 정답이다.

> `_size` = 색인 시점 **원본 `_source` 바이트**(비압축 JSON) → "얼마나 들어오나(ingest 볼륨)"의 정확한 척도.
> `_cat/indices`의 `store.size` = **디스크(압축+색인 후)**. 둘은 다르다: 유입량 판단엔 `_size`, 실디스크는 `store.size`.

---

## 0. ⚠️ 가장 중요한 주의 — 소급 안 됨
`_size`는 **색인 시점에 계산·저장**된다. 활성화해도 **기존 문서엔 안 생기고, 활성화 이후 새로 들어오는 문서부터** 값이 붙는다.
→ 과거 데이터의 정확 용량은 산출 불가(아래 §6 과도기 추정으로 근사). 하루 롤오버 기준 **다음 날 인덱스부터** 온전히 집계된다.

## 1. 전제: mapper-size 플러그인 확인
```
GET _cat/plugins?v&h=name,component,version    # 'mapper-size' 있는지
```
- 없으면 설치(전 노드) 후 **롤링 재시작**:
  - 수동: 각 노드에서 `bin/opensearch-plugin install mapper-size` → 재시작.
  - Helm/오퍼레이터 배포면 values의 `plugins.install`(또는 initContainer)에 `mapper-size` 추가 후 롤아웃.
- 설치는 클러스터 변경이므로 운영 창구/담당과 협의(재시작 수반).

## 2. 현재 인덱스 관리 주체 확인 (충돌 방지)
```
GET _index_template/*?filter_path=index_templates.name,index_templates.index_template.index_patterns,index_templates.index_template.priority
GET _template/*                      # 레거시 템플릿도 확인
GET _cat/aliases/icdataops-dev-log*  # alias→backing 인덱스 실제 이름 패턴 확인 (롤오버? 날짜?)
```
`icdataops-dev-log*`를 만드는 템플릿이 이미 있으면 **그 템플릿에 `_size`만 추가**가 안전. 없으면 §3의 새 템플릿.

## 3. `_size` 활성 — 인덱스 템플릿에 매핑 추가
**A) 기존 템플릿이 있으면** 그 템플릿 mappings에 아래를 병합:
```json
"mappings": { "_size": { "enabled": true } }
```

**B) 새 composable 템플릿**(기존과 패턴 안 겹치게, 겹치면 priority를 기존보다 높게):
```json
PUT _index_template/icdataops-dev-log-size
{
  "index_patterns": ["icdataops-dev-log*"],
  "priority": 500,
  "template": { "mappings": { "_size": { "enabled": true } } }
}
```
> 이미 다른 템플릿이 같은 패턴을 priority 동일하게 잡고 있으면 에러 → priority를 그보다 크게. (A안이 더 깔끔)

## 4. 즉시 적용 (다음 인덱스부터)
템플릿은 **새로 생성되는 인덱스**에만 적용된다. 빨리 확인하려면:
- **롤오버 방식**: `POST icdataops-dev-log/_rollover` (write alias면) → 새 backing 인덱스 생성.
- **날짜 인덱스 방식**: 다음 날(또는 Fluent Bit가 새 인덱스 만들 때) 자동 적용.
- (선택) 현재 write 인덱스에 즉시: `PUT <현재인덱스>/_mapping {"_size":{"enabled":true}}` — **이 인덱스의 새 문서부터** 붙음(기존 문서는 여전히 없음).

## 5. 검증 쿼리 (활성 후)
```json
// (1) 매핑에 _size 켜졌나
GET <새인덱스>/_mapping/field/_size

// (2) 새 문서에 _size 값이 붙나 (docvalue)
GET icdataops-dev-log*/_search
{ "size": 1, "_source": false, "docvalue_fields": ["_size"],
  "sort": [{ "@timestamp": "desc" }] }

// (3) 네임스페이스별 바이트 용량 (핵심 — 대시보드가 쓰는 것)
GET icdataops-dev-log*/_search
{ "size": 0, "query": { "bool": { "filter": [
    { "range": { "@timestamp": { "gte": "now-1h" } } },
    { "exists": { "field": "_size" } } ] } },
  "aggs": { "by_ns": { "terms": {
    "field": "kubernetes.namespace_name.keyword", "size": 30, "order": { "bytes": "desc" } },
    "aggs": { "bytes": { "sum": { "field": "_size" } },
              "avg_line": { "avg": { "field": "_size" } },
              "lines": { "value_count": { "field": "@timestamp" } } } } } }
```
- `by_ns` 버킷을 **`bytes` 내림차순**으로 정렬 → 용량 상위 = 필터 1순위.
- 같은 결과에서 **`bytes` 순위  vs `lines`(doc_count) 순위가 어긋나는 네임스페이스** = "라인은 적은데 뚱뚱한(멀티라인/대형)" 로그 → 라인수로는 놓쳤을 후보.
- 교차확인: `sum(_size)` 합 ≈ 유입 바이트(비압축). 디스크는 `GET _cat/indices/icdataops-dev-log*?v&h=index,docs.count,store.size`로 별도 확인(압축 후라 더 작음).

## 6. 과도기(설정 전) 근사 — 소급이 필요할 때
`_size` 없이 대략의 네임스페이스별 바이트를 추정: 최근 문서를 표본 추출해 `_source.log` 바이트 길이 평균을 구하고 라인수와 곱한다.
```
GET icdataops-dev-log*/_search?size=2000&_source=log,MESSAGE,kubernetes.namespace_name,log_source&q=@timestamp:[now-30m TO now]
```
→ (클라이언트에서) 네임스페이스별 평균 바이트 × 해당 네임스페이스 라인수 ≈ 유입량. **상대 순위 참고용**(정확치 아님).

## 7. 대시보드 전환
- 대시보드(`logvol-dashboard.json`)는 이미 `sum(_size)`·`avg(_size)` 패널을 포함 → **`_size`만 켜지면 자동으로 용량 기준으로 표시**된다(데이터소스·재import 불필요).
- 표의 용량 컬럼이 비면 = 플러그인 미설치이거나 컬럼명 불일치(`renameByName` 키를 실제 반환명에 맞춤, README §_size 참조).
- 멀티라인 명시 판별이 더 필요하면: `logtag=P`(비조인) 또는 파이프라인 `multiline` 마커, 그리고 **`avg(_size)` 상위 네임스페이스**(뚱뚱한 로그)로 판단.
