# OS-14 — high-cardinality 로그 인덱싱

Spark/Airflow 운영 1순위 사고 패턴 — UUID/task_attempt_id 같은 unbounded
keyword field 를 dynamic mapping 에 인덱싱 → cluster_state 비대화 →
master OOM. 이 시나리오는 그 임계점을 미리 찾는 것이 목적입니다.

## 매니페스트

이 시나리오는 별도의 Job 이 없습니다 — 부하 발생기 `loggen-spark` 자체가
OS-14 의 본체입니다. fluent-bit DaemonSet 이 stdout 을 읽어 OpenSearch 로
보내는 구조이며, 시간이 흐름에 따라 distinct keyword value 가 누적됩니다.

## 사전 조건

| 항목 | 명령 | 정상값 |
|------|------|--------|
| fluent-bit DaemonSet 가동 | `kubectl -n kube-system get ds fluent-bit` | DESIRED=NODES |
| OS index template 의 dynamic mapping | `curl ${OPENSEARCH_URL}/_index_template/logs-fb` | `dynamic: true` (또는 미설정 = default true) |
| logs-fb-* 인덱스 생성 가능 | flog 와 같은 다른 stdout 출처가 한 번이라도 흘렀어야 | exists |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/10-load-generators/loggen-spark.yaml
# 30분 ~ 2시간 동안 가동 (시간이 길수록 cardinality 누적)
```

## 측정 포인트

```bash
# 1) 인덱스 mapping field count
curl -s "${OPENSEARCH_URL}/logs-fb-*/_mapping" | jq '[.. | objects | .properties? // empty | keys] | flatten | length'
# 1000 미만이면 아직 여유. 10,000 넘으면 mapping explosion 임박.

# 2) cluster state 크기
curl -s "${OPENSEARCH_URL}/_cluster/state?human" | wc -c
# 정상 < 5 MB. 50 MB 이상이면 master OOM 위험.

# 3) heap 사용률 (per node)
curl -s "${OPENSEARCH_URL}/_nodes/stats/jvm" | jq '.nodes[] | {name, heap: .jvm.mem.heap_used_percent}'
```

## 기대 결과 (정상 == "임계점 발견")

| 지표 | 1시간 후 (관측) | 임계 (즉시 중지) |
|------|-----------------|-------------------|
| logs-fb-* doc count | > 10M | — |
| logs-fb-* mapping field 수 | 50 ~ 200 | > 10,000 |
| cluster_state size | < 5 MB | > 50 MB |
| master node heap | < 70% | > 90% |
| `pending_tasks` | 0 | > 100 (mapping update queue 적체) |

## 결과 해석

본 시나리오의 "성공 = OS 가 깨지지 않으면서 운영 임계 한도를 알아냈다".

**대응 액션 (테스트 후 운영 적용):**
1. Index template 에 `mapping.total_fields.limit: 1000` (기본 1000 유지) 강제
2. 문제 필드 (task_attempt_id 등) 를 `dynamic: false` 또는 `runtime field` 로 변경
3. fluent-bit 의 `[FILTER] modify` 로 UUID 필드 hash 처리 → cardinality 압축

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/10-load-generators/loggen-spark.yaml

# 누적된 인덱스도 삭제 (다른 시나리오 영향 방지)
kubectl -n monitoring exec opensearch-lt-node-0 -- \
  curl -X DELETE "http://localhost:9200/logs-fb-*"
```
