## P-1 전이 진행 (기존 객체)

| 지점 | 시각 (UTC) | 규칙 적용 후 | 전이/전체 |
|---|---|---|---|
| 규칙 적용 | 2026-10-26T01:46:13Z | 0 s | - |
| 1% | 2026-10-26T01:46:23Z | 10 s | 2667/4000 |
| 50% | 2026-10-26T01:46:23Z | 10 s | 2667/4000 |
| 90% | 2026-10-26T01:46:38Z | 25 s | 4000/4000 |
| 100% | 2026-10-26T01:46:38Z | 25 s | 4000/4000 |

처리율(1%→100%): 266.7 객체/s · 대상 4000 객체

| 메트릭 (규칙 적용 후 증가분) | 값 |
|---|---|
| `minio_node_ilm_action_count_transition_action{server="127.0.0.1:9000"}` | 1298 |
| `minio_node_ilm_transition_missed_immediate_tasks{server="127.0.0.1:9000"}` | 0 |
| `minio_node_scanner_bucket_scans_finished{server="127.0.0.1:9000"}` | 101 |
| `minio_node_scanner_objects_scanned{server="127.0.0.1:9000"}` | 34955 |
| `minio_node_tier_requests_failure{server="127.0.0.1:9000",tier="WARM-TIER"}` | 0 |
| `minio_node_tier_requests_success{server="127.0.0.1:9000",tier="WARM-TIER"}` | 0 |
| 전이 대기 작업 최대 | 0 |
| 전이 진행 작업 최대 | 0 |

| 구간 | Hot CPU 평균 (코어, MinIO 메트릭) |
|---|---|
| baseline | 0.074 |
| post | 0.109 |

## P-2 / P-3 쓰기·읽기 지연 (구간별, ms)

| 구간 | 회 | 오류 | write p50/p95 | 고정 파티션 읽기 p50/p95 | 메타데이터 조회 p50 | 전체 스캔 p50 | 정합성 |
|---|---|---|---|---|---|---|---|

## P-4 Pod 자원 (kubectl top, 구간별 평균/최대)

| 구간 | Pod | CPU 평균/최대 (m) | 메모리 최대 (Mi) |
|---|---|---|---|
| baseline | minio-hot-0 | 91/994 | 603 |
| baseline | minio-warm-0 | 35/605 | 483 |
| transition | minio-hot-0 | 181/260 | 546 |
| transition | minio-warm-0 | 162/320 | 963 |
| post | minio-hot-0 | 21/321 | 665 |
| post | minio-warm-0 | 13/380 | 991 |

## 영향도 (I-*)

