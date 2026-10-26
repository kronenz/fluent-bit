## P-1 전이 진행 (기존 객체)

| 지점 | 시각 (UTC) | 규칙 적용 후 | 전이/전체 |
|---|---|---|---|
| 규칙 적용 | 2026-10-26T01:02:08Z | 0 s | - |
| 1% | 2026-10-26T01:02:21Z | 13 s | 101/4016 |
| 50% | 2026-10-26T01:09:21Z | 433 s | 2022/4023 |
| 90% | 2026-10-26T01:15:22Z | 794 s | 3729/4029 |
| 100% | 2026-10-26T01:17:22Z | 914 s | 4031/4031 |

처리율(1%→100%): 4.5 객체/s · 대상 4049 객체

| 메트릭 (규칙 적용 후 증가분) | 값 |
|---|---|
| `minio_node_ilm_action_count_transition_action{server="127.0.0.1:9000"}` | 3948 |
| `minio_node_ilm_transition_missed_immediate_tasks{server="127.0.0.1:9000"}` | 0 |
| `minio_node_scanner_bucket_scans_finished{server="127.0.0.1:9000"}` | 35 |
| `minio_node_scanner_objects_scanned{server="127.0.0.1:9000"}` | 10386 |
| `minio_node_tier_requests_failure{server="127.0.0.1:9000",tier="WARM-TIER"}` | 0 |
| `minio_node_tier_requests_success{server="127.0.0.1:9000",tier="WARM-TIER"}` | 145182 |
| 전이 대기 작업 최대 | 0 |
| 전이 진행 작업 최대 | 0 |

| 구간 | Hot CPU 평균 (코어, MinIO 메트릭) |
|---|---|
| baseline | 0.083 |
| transition | 0.101 |
| post | 0.086 |

## P-2 / P-3 쓰기·읽기 지연 (구간별, ms)

| 구간 | 회 | 오류 | write p50/p95 | 고정 파티션 읽기 p50/p95 | 메타데이터 조회 p50 | 전체 스캔 p50 | 정합성 |
|---|---|---|---|---|---|---|---|
| baseline | 15 | 0 | 482/649 | 755/827 | 216 | 17972 | 3/3 일치 |
| transition | 19 | 0 | 488/673 | 920/1086 | 241 | 23202 | 4/4 일치 |
| post | 15 | 0 | 456/552 | 951/1145 | 278 | 25189 | 3/3 일치 |

## P-4 Pod 자원 (kubectl top, 구간별 평균/최대)

| 구간 | Pod | CPU 평균/최대 (m) | 메모리 최대 (Mi) |
|---|---|---|---|
| baseline | minio-hot-0 | 87/994 | 469 |
| baseline | minio-warm-0 | 1/6 | 129 |
| transition | minio-hot-0 | 96/816 | 470 |
| transition | minio-warm-0 | 45/504 | 483 |
| post | minio-hot-0 | 64/769 | 665 |
| post | minio-warm-0 | 35/605 | 991 |

## 영향도 (I-*)

| Iceberg (Spark) | pre-rule | post-transition | post-evolve | 동일 |
|---|---|---|---|---|
| `schema_sha` | "d1123fe33a176894" | "d1123fe33a176894" | "d1123fe33a176894" | ✅ |
| `partitioning` | ["hours(event_ts)"] | ["hours(event_ts)"] | ["hours(event_ts)"] | ✅ |
| `location` | "s3://warehouse/ilmperf.db/events" | "s3://warehouse/ilmperf.db/events" | "s3://warehouse/ilmperf.db/events" | ✅ |
| `props_sha` | "3002e319e4dff85e" | "3002e319e4dff85e" | "3002e319e4dff85e" | ✅ |
| `pinned_files` | 4000 | 4000 | 4000 | ✅ |
| `pinned_files_sha` | "e0bc212b82d68109" | "e0bc212b82d68109" | "e0bc212b82d68109" | ✅ |

스키마 변경 시험: {"add_column_ms": 416, "old_read": {"ok": true, "rows": 600000, "non_null": 0, "ms": 1511}, "new_write_read": {"ok": true, "rows": 1000}, "restored": true, "ok": true}

| HMS | pre-rule | post-transition | post-evolve | 동일 |
|---|---|---|---|---|
| `tbl_type` | "EXTERNAL_TABLE" | "EXTERNAL_TABLE" | "EXTERNAL_TABLE" | ✅ |
| `location` | "s3://warehouse/ilmperf.db/events" | "s3://warehouse/ilmperf.db/events" | "s3://warehouse/ilmperf.db/events" | ✅ |
| `columns` | ["batch_id:string", "id:bigint", "event_ts:timestamp", "payl | ["batch_id:string", "id:bigint", "event_ts:timestamp", "payl | ["batch_id:string", "id:bigint", "event_ts:timestamp", "payl | ✅ |
| `formats` | ["org.apache.hadoop.mapred.FileInputFormat / org.apache.hado | ["org.apache.hadoop.mapred.FileInputFormat / org.apache.hado | ["org.apache.hadoop.mapred.FileInputFormat / org.apache.hado | ✅ |
| `params_sha` | "b45b1a213fbeb7c0" | "b45b1a213fbeb7c0" | "b45b1a213fbeb7c0" | ✅ |
| `metadata_location_prefix` | "s3://warehouse/ilmperf.db/events/metadata/" | "s3://warehouse/ilmperf.db/events/metadata/" | "s3://warehouse/ilmperf.db/events/metadata/" | ✅ |

