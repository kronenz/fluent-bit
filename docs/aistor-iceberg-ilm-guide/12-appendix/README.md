# 12. 부록 — 명령어 레퍼런스 · FAQ · 템플릿

## 1. mc 명령어 레퍼런스

### 1.1 기본

| 목적 | 명령 |
|---|---|
| alias 등록 | `mc alias set HOT https://ep KEY SECRET --api S3v4` |
| alias 목록 | `mc alias list` |
| 클러스터 정보 | `mc admin info HOT` |
| 버킷 목록 | `mc ls HOT` |
| 객체 목록(재귀) | `mc ls --recursive HOT/bucket/prefix/` |
| **버전 포함 목록** | `mc ls --versions --recursive HOT/bucket/prefix/` |
| 객체 상세(전이 여부) | `mc stat HOT/bucket/key` |
| 객체 상세 JSON | `mc stat --json HOT/bucket/key` |
| 사용량 | `mc du HOT/bucket/prefix/` |
| 미완료 멀티파트 | `mc ls --incomplete HOT/bucket/` 🔍 |
| 로그 | `mc admin logs HOT --last 200` 🔍 |
| 요청 추적 | `mc admin trace HOT` |

### 1.2 Versioning

| 목적 | 명령 |
|---|---|
| 활성화 | `mc version enable HOT/bucket` |
| 상태 | `mc version info HOT/bucket` |
| 일시중지 | `mc version suspend HOT/bucket` |
| 특정 버전 조회 | `mc cat --version-id <VID> HOT/bucket/key` |
| 특정 버전 삭제 ⚠️ | `mc rm --version-id <VID> HOT/bucket/key` |

### 1.3 ILM

| 목적 | 명령 |
|---|---|
| 규칙 목록 | `mc ilm rule ls HOT/bucket` |
| 규칙 JSON export | `mc ilm rule export HOT/bucket` |
| 규칙 JSON import ⚠️ 전체 대체 | `mc ilm rule import HOT/bucket < f.json` |
| 전이 규칙 추가 | `mc ilm rule add HOT/bucket --prefix p/ --transition-days 1 --transition-tier WARM-TIER` |
| noncurrent 만료 | `mc ilm rule add HOT/bucket --prefix p/ --noncurrent-expire-days 7` |
| 규칙 삭제 | `mc ilm rule rm HOT/bucket --id <ID>` |
| 플래그 확인 🔍 | `mc ilm rule add --help` |

### 1.4 Tier

| 목적 | 명령 |
|---|---|
| tier 목록 | `mc ilm tier ls HOT` |
| tier 상세/통계 | `mc ilm tier info HOT WARM-TIER` |
| tier 추가 | `mc ilm tier add minio HOT WARM-TIER --endpoint https://... --access-key K --secret-key S --bucket b --prefix p/` |
| 자격증명 갱신 | `mc ilm tier update HOT WARM-TIER --access-key K --secret-key S` 🔍 |
| tier 삭제 🔴 | `mc ilm tier rm HOT WARM-TIER` — **전이 객체 있으면 금지** |

### 1.5 Replication

| 목적 | 명령 |
|---|---|
| 규칙 목록 | `mc replicate ls HOT/bucket` |
| 상태 | `mc replicate status HOT/bucket` |
| 규칙 추가 | `mc replicate add HOT/bucket --remote-bucket "https://K:S@ep/bucket" --replicate "existing-objects,delete-marker"` |
| 규칙 변경 | `mc replicate update HOT/bucket --id <ID> --state enable\|disable` |
| 규칙 삭제 | `mc replicate rm HOT/bucket --id <ID>` |
| export/import | `mc replicate export/import HOT/bucket` |
| 재동기화 | `mc replicate resync start HOT/bucket --remote-bucket <ARN>` |
| 재동기화 상태 | `mc replicate resync status HOT/bucket --remote-bucket <ARN>` |
| 사이트 복제 확인 | `mc admin replicate info HOT` |

### 1.6 Scanner / 설정 / 메트릭

| 목적 | 명령 |
|---|---|
| 스캐너 설정 조회 | `mc admin config get HOT scanner` |
| 스캐너 속도 설정 | `mc admin config set HOT scanner speed=fast` 🔍 |
| API 설정 | `mc admin config get HOT api` |
| 클러스터 메트릭 | `mc admin prometheus metrics HOT cluster` |
| 노드 메트릭 | `mc admin prometheus metrics HOT node` |
| 버킷 메트릭 | `mc admin prometheus metrics HOT bucket` 🔍 |
| 성능 측정 | `mc support perf drive\|net\|object HOT` 🔍 |

### 1.7 데이터 이동

| 목적 | 명령 |
|---|---|
| 복사 | `mc cp src dst` |
| 미러 | `mc mirror --preserve --overwrite src/ dst/` |
| 차이 비교 | `mc diff HOT/bucket/p/ WARM/bucket/p/` |
| 삭제 ⚠️ | `mc rm --recursive --force HOT/bucket/p/` |
| 대역 제한 | `mc mirror --limit-download 100MB src dst` 🔍 |

## 2. Iceberg / Spark SQL 레퍼런스

### 2.1 시스템 테이블

| 테이블 | 용도 |
|---|---|
| `tbl.snapshots` | 스냅샷 목록·시각·연산 |
| `tbl.files` | **현재 스냅샷** 데이터 파일 |
| `tbl.all_data_files` | **모든 스냅샷** 데이터 파일 (고아 판정용) |
| `tbl.delete_files` | v2 delete 파일 |
| `tbl.manifests` | 현재 manifest |
| `tbl.all_manifests` | 모든 manifest |
| `tbl.partitions` | 파티션별 파일 수·크기 |
| `tbl.history` | 스냅샷 이력 |
| `tbl.metadata_log_entries` | metadata.json 이력 |
| `tbl.refs` | 브랜치/태그 |

### 2.2 유지보수 프로시저

| 프로시저 | 용도 | 위험 |
|---|---|---|
| `rewrite_data_files` | 소파일 병합 | 낮음 (I/O 큼) |
| `rewrite_manifests` | manifest 병합 | 낮음 |
| `rewrite_position_delete_files` | delete file 병합 | 낮음 |
| `expire_snapshots` | 스냅샷 만료 | 중 (시간여행 축소) |
| `remove_orphan_files` | 고아 파일 삭제 | 🔴 **높음** |
| `rollback_to_snapshot` | 스냅샷 롤백 | 중 |
| `set_current_snapshot` | 현재 스냅샷 지정 | 중 |
| `register_table` | 기존 metadata.json으로 등록 | 낮음 |
| `migrate` | Hive 테이블 → Iceberg | 중 |
| `snapshot` | Hive 테이블 스냅샷 생성 | 낮음 |
| `rewrite_table_path` | 경로 재작성 🔍 | 중 |

```sql
-- 자주 쓰는 형태
CALL hive_prod.system.rewrite_data_files(
  table => 'db.tbl',
  where => 'dt >= current_date() - interval 7 days',
  options => map('min-input-files','5','target-file-size-bytes','536870912','partial-progress.enabled','true'));

CALL hive_prod.system.expire_snapshots(
  table => 'db.tbl', older_than => current_timestamp() - interval 7 days, retain_last => 10);

CALL hive_prod.system.rollback_to_snapshot(table => 'db.tbl', snapshot_id => 1234567890);

CALL hive_prod.system.register_table(
  table => 'db.tbl', metadata_file => 's3://warehouse/db.db/tbl/metadata/00042-x.metadata.json');
```

### 2.3 주요 테이블 속성

| 속성 | 기본 | 이 환경 권장 |
|---|---|---|
| `format-version` | 2 | 2 |
| `write.target-file-size-bytes` | 536870912 | 536870912~1073741824 |
| `write.parquet.row-group-size-bytes` | 134217728 | 134217728 |
| `write.parquet.compression-codec` | zstd/gzip | zstd |
| `write.metadata.delete-after-commit.enabled` | false | **true** |
| `write.metadata.previous-versions-max` | 100 | 20~50 |
| `commit.manifest.target-size-bytes` | 8388608 | 16777216 |
| `commit.manifest-merge.enabled` | true | true |
| `commit.retry.num-retries` | 4 | 10 |
| `history.expire.max-snapshot-age-ms` | 432000000 | 604800000 |
| `history.expire.min-snapshots-to-keep` | 1 | 10 |
| `write.delete.mode` | merge-on-read | 검토 (F-08) |
| `write.distribution-mode` | hash | hash 또는 range |

```sql
ALTER TABLE hive_prod.db.tbl SET TBLPROPERTIES ('key'='value');
ALTER TABLE hive_prod.db.tbl UNSET TBLPROPERTIES ('key');
DESCRIBE EXTENDED hive_prod.db.tbl;
```

## 3. 트러블슈팅 FAQ

### Q1. `mc ls` 에는 파일이 보이는데 Spark에서 `NotFoundException` 이 납니다.

가능성 순서:

| # | 원인 | 확인 | 조치 |
|---|---|---|---|
| 1 | 전이 대상(warm) 접근 실패 | `mc stat` 로 Tier 확인 → `mc cat` 시도 | F-04 |
| 2 | ILM 만료로 실제 삭제 (stub만 남음 아님) | `mc ls --versions` | F-02 |
| 3 | warm tier 버킷에서 데이터 삭제됨 | `mc ls WARM/warm-tier` | F-04 |
| 4 | 경로 스킴 불일치 (`s3` vs `s3a`) | HMS의 metadata_location | 06장 §1.2 |
| 5 | Spark 자격증명이 다른 버킷 권한 | 정책 확인 | 03장 §3 |

> ⚠️ **`mc ls`에 보인다고 데이터가 있는 것이 아닙니다** — 전이 stub도 그대로 보입니다 (02장 §1).

### Q2. 전이가 며칠째 안 됩니다.

[09장 §3.1](../09-operations/) 판별 흐름을 따르십시오. 가장 흔한 원인은 **프리픽스 불일치**입니다.

```bash
mc ilm rule ls HOT/warehouse                                   # 규칙의 프리픽스
mc ls --recursive HOT/warehouse/ | head -5                     # 실제 경로
```

두 값을 눈으로 대조하십시오. 예: 규칙이 `data/` 인데 실제는 `ilm_test.db/orders/data/` 인 경우가 많습니다.

### Q3. `expire_snapshots` 를 했는데 용량이 그대로입니다.

정상입니다. Versioning ON에서 DELETE는 논리 삭제입니다. noncurrent 만료 규칙이 있어야 회수됩니다. → [F-11](../11-failure-and-risk/), [04장 §5](../04-ilm-policy-design/)

### Q4. compaction 후 오히려 S3 객체 수가 늘었습니다.

정상입니다. 새 파일이 생기고 구 파일은 noncurrent로 남습니다. 논리 파일 수(`tbl.files`)는 줄었는지 확인하십시오.

### Q5. 삭제한 행이 다시 조회됩니다.

🔴 **즉시 조사하십시오.** delete file이 소실됐을 가능성이 큽니다. → [F-08](../11-failure-and-risk/)

### Q6. 최근 파티션은 빠른데 구 파티션만 느립니다.

정상적인 전이 비용입니다. 배수가 예상보다 크면 소파일 문제입니다. → [10장 §1.2](../10-performance/)

### Q7. `SELECT count(*)` 도 느려졌습니다.

🔴 metadata가 전이됐을 가능성이 큽니다. `count(*)`는 대개 메타데이터만 읽습니다. → [F-10](../11-failure-and-risk/), [08장 T-07](../08-test-scenarios/)

```bash
mc stat HOT/warehouse/db.db/tbl/metadata/<최신>.metadata.json | grep -i tier
```

### Q8. `UnknownHostException: bucket.hot-s3...`

`path-style-access=true` 누락입니다. → [06장 §2](../06-spark-setup/)

### Q9. `SSLHandshakeException: PKIX path building failed`

사설 CA가 **Java truststore**에 없습니다. OS 신뢰만으론 부족합니다. → [06장 §3.4](../06-spark-setup/)

### Q10. 복제 상태가 계속 PENDING 입니다.

| 확인 | 조치 |
|---|---|
| 대상 버킷 Versioning | `mc version enable WARM/bucket` |
| 대상 계정 권한 | 03장 §3.3 |
| 대상 접근성 | `mc ls WARM/bucket` |
| 대역폭 | 전이 작업과 시간 분리 |

→ [F-12](../11-failure-and-risk/)

### Q11. tier 를 삭제해도 되나요?

🔴 **전이된 객체가 하나라도 있으면 안 됩니다.** 먼저 확인하십시오.

```bash
mc ilm tier info HOT WARM-TIER    # 객체 수 0인지
```

### Q12. warm 클러스터에 직접 접속해서 데이터를 확인해도 되나요?

**읽기(ls, stat)는 가능하지만 쓰기/삭제는 절대 금지**입니다. 또한 tier 버킷의 객체는 내부 포맷이라 사람이 해석할 수 없습니다. → [01장 §3](../01-architecture/)

### Q13. 테스트를 위해 1일을 기다리지 않으려면?

과거 날짜 기준 transition 규칙을 쓰십시오 (Expiration에는 절대 금지). → [07장 §6](../07-test-data/)

### Q14. 스캐너를 즉시 돌릴 수 있나요?

일반적으로 강제 트리거는 없습니다. 속도 프리셋 상향 또는 데이터셋 축소가 현실적입니다. → [02장 §5.5](../02-aistor-internals/)

### Q15. hot 보존 기간을 며칠로 해야 하나요?

파티션별 쿼리 빈도 × 전이 시 지연 증가로 산정하십시오. → [10장 §4.1](../10-performance/)

### Q16. 운영 데이터를 mirror 했는데 테이블이 안 열립니다.

metadata 내부가 원본 경로를 가리키고 있습니다. 버킷/DB/테이블 경로를 원본과 동일하게 하거나 CTAS로 재작성하십시오. → [07장 §3](../07-test-data/)

### Q17. `Timeout waiting for connection from pool`

커넥션 풀 부족입니다. `http-client.apache.max-connections` 를 executor 총 코어 × 2 이상으로 올리십시오.

### Q18. 전이 객체를 다시 hot으로 되돌릴 수 있나요?

전이 취소 명령은 없을 수 있습니다 🔍. 우회로 자기 자신 복사가 있으나 noncurrent 버전을 남깁니다. → [F-10](../11-failure-and-risk/)

## 4. 설정 템플릿

### 4.1 ILM 규칙 (안전 기본형)

```json
{
  "Rules": [
    { "ID": "data-transition-1d", "Status": "Enabled",
      "Filter": { "Prefix": "REPLACE_DB.db/REPLACE_TBL/data/" },
      "Transition": { "Days": 1, "StorageClass": "WARM-TIER" } },
    { "ID": "data-noncurrent-expire-7d", "Status": "Enabled",
      "Filter": { "Prefix": "REPLACE_DB.db/REPLACE_TBL/data/" },
      "NoncurrentVersionExpiration": { "NoncurrentDays": 7 } },
    { "ID": "expire-delete-markers", "Status": "Enabled",
      "Filter": { "Prefix": "REPLACE_DB.db/REPLACE_TBL/" },
      "Expiration": { "ExpiredObjectDeleteMarker": true } },
    { "ID": "abort-mpu-3d", "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 3 } }
  ]
}
```

### 4.2 Spark 설정 (S3FileIO)

```properties
spark.sql.extensions                                            org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions
spark.sql.catalog.hive_prod                                     org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.hive_prod.type                                hive
spark.sql.catalog.hive_prod.uri                                 thrift://hms.data.svc.cluster.local:9083
spark.sql.catalog.hive_prod.warehouse                           s3://warehouse/
spark.sql.catalog.hive_prod.io-impl                             org.apache.iceberg.aws.s3.S3FileIO
spark.sql.catalog.hive_prod.s3.endpoint                         https://hot-s3.example.internal
spark.sql.catalog.hive_prod.s3.path-style-access                true
spark.sql.catalog.hive_prod.client.region                       us-east-1
spark.sql.catalog.hive_prod.http-client.type                    apache
spark.sql.catalog.hive_prod.http-client.apache.max-connections  200
spark.sql.catalog.hive_prod.http-client.apache.socket-timeout-ms 180000
spark.sql.catalog.hive_prod.commit.retry.num-retries            10
spark.sql.catalog.hive_prod.cache-enabled                       true
spark.sql.iceberg.vectorization.enabled                         true
spark.sql.adaptive.enabled                                      true
spark.sql.adaptive.coalescePartitions.enabled                   true
```

### 4.3 테이블 생성

```sql
CREATE TABLE hive_prod.<db>.<tbl> (
  -- 컬럼 정의
) USING iceberg
PARTITIONED BY (days(<ts_col>))
TBLPROPERTIES (
  'format-version'='2',
  'write.target-file-size-bytes'='536870912',
  'write.parquet.row-group-size-bytes'='134217728',
  'write.parquet.compression-codec'='zstd',
  'write.metadata.delete-after-commit.enabled'='true',
  'write.metadata.previous-versions-max'='20',
  'commit.manifest-merge.enabled'='true',
  'commit.manifest.target-size-bytes'='16777216',
  'commit.retry.num-retries'='10',
  'history.expire.max-snapshot-age-ms'='604800000',
  'history.expire.min-snapshots-to-keep'='10'
);
```

## 5. 체크리스트 모음

### 5.1 착수 전

| # | 항목 | ✅ |
|---|---|---|
| 1 | 현행 구성 진단 완료 (방식 A/B/A+B 확정) — 03장 §7 | |
| 2 | 위험 항목 D-1~D-8 확인 및 조치 | |
| 3 | 설정 백업 (ILM/복제/tier/scanner) | |
| 4 | Spark 연결 검증 통과 — 06장 §4 | |
| 5 | 테스트 전용 버킷/DB 준비 | |
| 6 | 거버넌스 승인 (GV-1~GV-8) — 07장 §2 | |
| 7 | 모니터링/알람 구성 — 09장 §8 | |
| 8 | 롤백 절차 숙지 — 03장 §10 | |

### 5.2 ILM 규칙 적용 전 (매번)

| # | 항목 | ✅ |
|---|---|---|
| 1 | `mc ilm rule export` 백업 | |
| 2 | 프리픽스를 실제 경로와 대조 | |
| 3 | `metadata/` 미포함 확인 | |
| 4 | Expiration 규칙 없음 확인 (noncurrent 제외) | |
| 5 | `verify-ilm.sh` 통과 | |
| 6 | 2인 리뷰 (expiration 계열은 필수) | |
| 7 | 적용 후 `mc ilm rule ls` 재확인 | |
| 8 | 변경 이력표 기록 | |

### 5.3 테스트 종료 후

| # | 항목 | ✅ |
|---|---|---|
| 1 | 테스트 ILM 규칙 제거/원복 | |
| 2 | 스캐너 속도 원복 | |
| 3 | 테스트 테이블/데이터 폐기 | |
| 4 | noncurrent/warm 잔여 정리 | |
| 5 | 임시 계정 폐기 | |
| 6 | 결과 기록표 완성 — 08장 §9 | |
| 7 | 리스크 레지스터 미해결 항목 확정 — 11장 §9 | |
| 8 | 운영 이행 권고안 작성 | |

## 6. 참조 문서

| 주제 | 참조 |
|---|---|
| S3 Lifecycle 규격 | AWS S3 Lifecycle 공식 문서 (필터/Days/Date 해석) |
| MinIO/AIStor ILM·Tiering | 제품 공식 문서 (버전에 맞는 것) |
| MinIO/AIStor Replication | 제품 공식 문서 |
| Apache Iceberg 스펙 | Iceberg Table Spec (v2) |
| Iceberg Spark 프로시저 | Iceberg Spark Procedures 문서 |
| Iceberg AWS 연동 | Iceberg AWS Integration 문서 |
| Spark on K8s | Spark 공식 문서 / Spark Operator |

⚠️ 본 문서의 🔍 표시 항목은 위 공식 문서에서 **사용 중인 버전 기준으로 확인**하십시오. 버전 간 차이가 큽니다.

## 7. 문서 내 스크립트 목록

| 스크립트 | 위치 | 용도 |
|---|---|---|
| `diag-aistor.sh` | 03장 §7.1 | 현행 구성 진단 |
| `verify-ilm.sh` | 04장 §3.5 | ILM 위험 규칙 탐지 |
| `verify-spark-iceberg.py` | 06장 §4.2 | Spark 연결 검증 |
| `ingest-ctas.py` | 07장 §4 | 운영 데이터 반입 |
| `snapshot-state.sh` | 08장 §2 | 시나리오 전후 채증 |
| `measure-repl-lag.sh` | 08장 T-11 | 복제 지연 측정 |
| `daily-check.sh` | 09장 §2.1 | 일일 점검 |
| `measure-scanner-cycle.sh` | 09장 §3.2 | 스캐너 사이클 측정 |
| `verify-replication.sh` | 09장 §4.3 | 복제 정합성 검증 |
| `measure-object-latency.sh` | 10장 §2.1 | 전이 지연 배수 M 측정 |
| `bench-queries.py` | 10장 §2.2 | 쿼리 벤치마크 |
| `incident-capture.sh` | 11장 §2 | 사고 채증 |

> ✅ 이 스크립트들을 `scripts/` 하위에 모아 Git으로 관리하고, 일일/주간 점검은 배치로 편성하십시오.

← [문서 인덱스로 돌아가기](../README.md)
