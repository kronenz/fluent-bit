# icdataops-dev — 로그 적재량 · 스토리지 필터링 분석 대시보드

**목적**: OpenSearch `icdataops-dev-log*`에 쌓이는 k8s 컨테이너 로그 + systemd 로그(kubelet·containerd·etcd 등)의
**유입량을 namespace / app label / pod / 소스 / 멀티라인별로 실측**해서, **수집(Fluent Bit) 단계에서 무엇을 drop(필터)할지**
판단하기 위한 대시보드다. "용량 상위 기여자 = 1순위 필터 후보".

- 생성기: [`gen-logvol.py`](./gen-logvol.py) → 산출물 [`logvol-dashboard.json`](./logvol-dashboard.json) (18패널). **수정은 생성기 고쳐 재생성**(손편집 금지).
- 대상 플러그인: `grafana-opensearch-datasource` (lab Grafana 11.x에서 스키마 import 검증 완료).

## 무엇을 보여주나 (패널)
1. **개요** — 전체/컨테이너/systemd 라인수, 네임스페이스 수, 전체 용량(bytes).
2. **소스별** — 컨테이너 vs systemd 유입 추이·비중.
3. **Top 네임스페이스** — 라인수 막대(필터 1순위 후보) + 요약표(라인·파드수·용량).
4. **Top 앱라벨 / Top 파드** — 과다 로깅 앱·파드 식별.
5. **systemd 유닛별** — kubelet·containerd·etcd… 유입량·추이.
6. **멀티라인 분석** — `logtag`(F 완결 : P 분할) 비중·추이.
7. **네임스페이스별 평균 문서 크기** — 뚱뚱한 로그(=멀티라인/대형) 후보.

## 도입 절차
1. Grafana에서 **OpenSearch 데이터소스** 생성:
   - URL = icdataops-dev OpenSearch 엔드포인트, **Index name = `icdataops-dev-log*`**, **Time field = `@timestamp`**.
   - Version은 OpenSearch **서버** 버전에 맞춤(플러그인 버전과 별개 — 프로젝트 룰 참조).
2. `logvol-dashboard.json`을 **Import** → 변수 `데이터소스`에서 위 데이터소스 선택.
3. 상단 시간범위/`키워드(lucene)`로 스코프 조정.

## ⚠️ 도입 전 필드 검증 (룰: 추측 금지 — 프레임 실측)
필드명은 이 팀의 Fluent Bit(CRI tail + systemd) → OpenSearch 파이프라인 **실측 기준**이다.
`icdataops-dev`에서 아래 한 방으로 확인하고, 다르면 생성기 상수만 고쳐 재생성:

```json
// OpenSearch Dashboards → Dev Tools
GET icdataops-dev-log*/_search?size=1
// 확인: kubernetes.namespace_name / pod_name / labels.* / logtag / stream / log_source
//       systemd 문서의 SYSTEMD_UNIT / SYSLOG_IDENTIFIER
GET icdataops-dev-log*/_mapping/field/_size    // ← _size(용량) 사용 가능 여부
```

- **앱 라벨**: 기본 `kubernetes.labels.app_kubernetes_io/name.keyword`. 앱이 `app` 라벨을 쓰면
  `gen-logvol.py`의 `APP_LABEL`을 `kubernetes.labels.app.keyword`로 바꿔 재생성.
- **바이트 용량(`sum _size`)**: `_size`는 **mapper-size 플러그인 + 매핑 활성** 시에만 존재. 없으면 용량 패널은 비고 라인수로 판단.
  활성화(신규 인덱스부터 적용):
  ```json
  PUT _index_template/icdataops-dev-log
  { "index_patterns": ["icdataops-dev-log*"], "template": { "mappings": { "_size": { "enabled": true } } } }
  ```
  활성 후, 표의 용량 컬럼명이 플러그인 버전에 따라 `Sum _size`가 아니면 `renameByName` 키만 맞추면 됨(빈 컬럼 = 키 불일치, 룰 §1).

## 🧵 멀티라인 판별 정확도
- 대시보드 기본은 **CRI `logtag`**(P=분할/부분, F=완결)로 근사한다 — 바로 동작.
- 파이프라인이 멀티라인을 **조인**하면(스택트레이스를 한 문서로 합침) 조인 결과는 `logtag=F`가 되어 P로 안 잡힌다.
  이 경우 정확한 "앱 멀티라인" 판별은 두 방법:
  - **파이프라인 마커 추가(권장)** — Fluent Bit lua/record_modifier로 조인된 레코드에 `multiline: true` 부여 후 그 필드로 집계.
  - **수동 즉시 확인** — 개행 포함 문서 비율(Dev Tools):
    ```json
    GET icdataops-dev-log*/_count
    { "query": { "regexp": { "log.keyword": "(.|\n)*\n(.|\n)*" } } }   // log.keyword ignore_above로 장문 누락 가능 → 근사
    ```
  - 평균 문서 크기 패널(`avg _size`)이 큰 네임스페이스 = 멀티라인/대형 로그 유력 → 실질적 필터 판단엔 이게 가장 유용.

## 필터링 판단 가이드 (스토리지 절감)
대시보드에서 **값 크고 가치 낮은** 항목부터 Fluent Bit에서 drop/샘플링:
- **접근/헬스체크 로그** (nginx/ingress access, `/healthz`·`/readyz` 폴링) — 대량·저가치.
- **debug/verbose** 레벨 — 특정 앱이 debug로 폭주.
- **systemd containerd/kubelet의 반복 이벤트** — 노이즈성 반복 메시지.
- **멀티라인/대형 스택트레이스** 남발 앱 — 평균 문서 크기 상위 네임스페이스.
- 구현: Fluent Bit `[FILTER] grep`(Exclude)·`nest`·`throttle`, 또는 namespace/app 단위 라우팅 분리.

> 검증 한계: 대상 OpenSearch(icdataops-dev)에 직접 접근 불가라 필드는 동일 파이프라인(lab)로 실측·JSON 스키마는 lab Grafana import로 검증했다. 실데이터 쿼리 검증은 위 Dev Tools로 도입 시 확인할 것.
