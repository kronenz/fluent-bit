# ILM 테스트 모니터링 쿼리

> 🔍 메트릭 이름은 AIStor 버전·메트릭 경로(v2/v3)에 따라 다르다. 대시보드를 만들기 전에
> `curl -s -H "Authorization: Bearer $TOKEN" https://hot/minio/v2/metrics/node | grep -E 'ilm|scanner'` 로 실제 이름을 먼저 확인할 것.

## 1. 메트릭 (PromQL / MetricsQL)

| 판정 | 패널 | 쿼리 | 기대 |
|---|---|---|---|
| J-1 | 누적 전이 객체 | `sum by (tier) (minio_cluster_ilm_transitioned_objects{deployment="hot"})` | 단조 증가 (`tier="WARM-TIER"`) |
| J-1 | 누적 전이 바이트 | `sum by (tier) (minio_cluster_ilm_transitioned_bytes{deployment="hot"})` | 단조 증가 |
| J-1 | 전이 대기 | `sum(minio_node_ilm_transition_pending_tasks{deployment="hot"})` | 사이클마다 증가 후 0 으로 복귀 |
| J-1 | 전이 진행 | `sum(minio_node_ilm_transition_active_tasks{deployment="hot"})` | 전이 시점에 0 이상 |
| J-8 | 즉시 전이 누락 | `sum(increase(minio_node_ilm_transition_missed_immediate_tasks{deployment="hot"}[1h]))` | 0 |
| — | Scanner 사이클 | `increase(minio_node_scanner_bucket_scans_finished{deployment="hot"}[1h])` | 0 이 길게 이어지면 Scanner 정체 |
| — | Scanner 처리량 | `rate(minio_node_scanner_objects_scanned{deployment="hot"}[5m])` | 0 이 아님 |
| — | Hot 용량 | `minio_bucket_usage_total_bytes{deployment="hot", bucket="warehouse"}` | 논리 크기라 전이 후에도 줄지 않을 수 있다 → 디스크 메트릭으로 확인 |
| — | Warm tier 용량 | `minio_bucket_usage_total_bytes{deployment="warm", bucket="warm-tier"}` | 전이에 따라 증가 |
| — | 디스크 실사용 | `sum by (deployment) (minio_node_drive_used_bytes)` | Hot 증가 둔화, Warm 증가 |
| — | 버전·DM | `minio_cluster_usage_version_total`, `minio_cluster_usage_deletemarker_total` | expire 후 증가 → R-3 이후 감소 |

## 2. 로그 (OpenSearch)

| 판정 | 인덱스 | 쿼리 (DQL) | 기대 |
|---|---|---|---|
| J-1 | `ilmtest-app` | `event:"ilmtest.state" and data.overdue > 0` | 기한 경과 후 0건 |
| J-2 | `ilmtest-app` | `event:"ilmtest.state" and metadata.transitioned > 0` | 0건 |
| J-3 | `ilmtest-app` | `event:"ilmtest.verify" and not status:"ok"` | 0건 |
| J-4 | `ilmtest-app` | `event:"ilmtest.verify" and old_read.ok:false` | 0건 |
| J-5 | `ilmtest-app` | `event:"ilmtest.write" and status:"fail"` | 0건 |
| J-6 | `ilmtest-app` | `event:"ilmtest.maintenance"` | 모두 `status:"ok"` |
| J-7 | `ilmtest-alert` | `*` | 0건 (tier 계정 외 Warm 접근) |
| J-7 | `ilmtest-audit` | `api.bucket:"warm-tier"` → `accessKey` 집계 | tier 계정 1개 🔍(audit 필드명 확인) |
| J-8 | `ilmtest-app` | `kubernetes.labels.app_kubernetes_io/name:"trace" and error:*` | 0건 |
| 참고 | `ilmtest-audit` | `api.name:"PutObject" and api.bucket:"warm-tier"` | 전이 시각과 일치 (Hot → Warm 이동 흔적) |
