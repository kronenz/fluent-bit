## P-1 전이 진행 (기존 객체)

| 지점 | 시각 (UTC) | 규칙 적용 후 | 전이/전체 |
|---|---|---|---|
| 규칙 적용 | 2026-10-26T02:16:46Z | 0 s | - |
| 1% | 2026-10-26T02:17:32Z | 46 s | 2/106 |
| 50% | 2026-10-26T02:21:32Z | 286 s | 114/114 |
| 90% | 2026-10-26T02:21:32Z | 286 s | 114/114 |
| 100% | 2026-10-26T02:21:32Z | 286 s | 114/114 |

처리율(1%→100%): 0.5 객체/s · 대상 119 객체

| 메트릭 (규칙 적용 후 증가분) | 값 |
|---|---|
| `minio_node_ilm_action_count_transition_action{server="127.0.0.1:9000"}` | 119 |
| `minio_node_ilm_transition_missed_immediate_tasks{server="127.0.0.1:9000"}` | 0 |
| `minio_node_scanner_bucket_scans_finished{server="127.0.0.1:9000"}` | 56 |
| `minio_node_scanner_objects_scanned{server="127.0.0.1:9000"}` | 5146 |
| `minio_node_tier_requests_failure{server="127.0.0.1:9000",tier="WARM-EXP"}` | 0 |
| `minio_node_tier_requests_failure{server="127.0.0.1:9000",tier="WARM-EXPI"}` | 0 |
| `minio_node_tier_requests_failure{server="127.0.0.1:9000",tier="WARM-TIER"}` | 0 |
| `minio_node_tier_requests_success{server="127.0.0.1:9000",tier="WARM-EXP"}` | 0 |
| `minio_node_tier_requests_success{server="127.0.0.1:9000",tier="WARM-EXPI"}` | 0 |
| `minio_node_tier_requests_success{server="127.0.0.1:9000",tier="WARM-TIER"}` | 2982 |
| 전이 대기 작업 최대 | 0 |
| 전이 진행 작업 최대 | 0 |

| 구간 | Hot CPU 평균 (코어, MinIO 메트릭) |
|---|---|
| baseline | 0.020 |
| transition | 0.023 |
| post | 0.027 |

## P-2 / P-3 쓰기·읽기 지연 (구간별, ms)

| 구간 | 회 | 오류 | write p50/p95 | 고정 파티션 읽기 p50/p95 | 메타데이터 조회 p50 | 전체 스캔 p50 | 정합성 |
|---|---|---|---|---|---|---|---|
| baseline | 4 | 0 | 541/4029 | 405/1107 | 188 | 782 | 2/2 일치 |
| transition | 10 | 0 | 482/4432 | 315/1240 | 166 | 842 | 5/5 일치 |
| post | 4 | 0 | 616/3937 | 498/1235 | 253 | 1197 | 2/2 일치 |

## P-4 Pod 자원 (kubectl top, 구간별 평균/최대)

| 구간 | Pod | CPU 평균/최대 (m) | 메모리 최대 (Mi) |
|---|---|---|---|
| baseline | minio-hot-0 | 18/49 | 549 |
| baseline | minio-warm-0 | 6/36 | 526 |
| transition | minio-hot-0 | 20/46 | 531 |
| transition | minio-warm-0 | 5/21 | 526 |
| post | minio-hot-0 | 24/101 | 527 |
| post | minio-warm-0 | 11/45 | 767 |

## 영향도 (I-*)

| Iceberg (Spark) | pre-rule | post-transition | post-evolve | 동일 |
|---|---|---|---|---|
| `schema_sha` | "d1123fe33a176894" | "d1123fe33a176894" | "d1123fe33a176894" | ✅ |
| `partitioning` | ["hours(event_ts)"] | ["hours(event_ts)"] | ["hours(event_ts)"] | ✅ |
| `location` | "s3://warehouse/ilmperfv2.db/events" | "s3://warehouse/ilmperfv2.db/events" | "s3://warehouse/ilmperfv2.db/events" | ✅ |
| `props_sha` | "3002e319e4dff85e" | "3002e319e4dff85e" | "3002e319e4dff85e" | ✅ |
| `pinned_files` | 100 | 100 | 100 | ✅ |
| `pinned_files_sha` | "aea34c6b401fd141" | "aea34c6b401fd141" | "aea34c6b401fd141" | ✅ |

스키마 변경 시험: {"add_column_ms": 364, "old_read": {"ok": true, "rows": 50000, "non_null": 0, "ms": 554}, "new_write_read": {"ok": true, "rows": 1000}, "restored": true, "ok": true}

| HMS | pre-rule | post-transition | post-evolve | 동일 |
|---|---|---|---|---|
| `tbl_type` | "EXTERNAL_TABLE" | "EXTERNAL_TABLE" | "EXTERNAL_TABLE" | ✅ |
| `location` | "s3://warehouse/ilmperfv2.db/events" | "s3://warehouse/ilmperfv2.db/events" | "s3://warehouse/ilmperfv2.db/events" | ✅ |
| `columns` | ["batch_id:string", "id:bigint", "event_ts:timestamp", "payl | ["batch_id:string", "id:bigint", "event_ts:timestamp", "payl | ["batch_id:string", "id:bigint", "event_ts:timestamp", "payl | ✅ |
| `formats` | ["org.apache.hadoop.mapred.FileInputFormat / org.apache.hado | ["org.apache.hadoop.mapred.FileInputFormat / org.apache.hado | ["org.apache.hadoop.mapred.FileInputFormat / org.apache.hado | ✅ |
| `params_sha` | "5cc997aa6f56a3b5" | "5cc997aa6f56a3b5" | "5cc997aa6f56a3b5" | ✅ |
| `metadata_location_prefix` | "s3://warehouse/ilmperfv2.db/events/metadata/" | "s3://warehouse/ilmperfv2.db/events/metadata/" | "s3://warehouse/ilmperfv2.db/events/metadata/" | ✅ |

