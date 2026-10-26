# 07. 운영 Iceberg 데이터를 테스트 환경으로 반입하기

> ⚠️ 이 챕터는 **운영 데이터를 다룹니다.** 원본에 대한 쓰기 권한을 절대 부여하지 마십시오.
> 🔴 가장 흔한 실패: "`mc mirror`로 복사했는데 테이블이 안 열린다" — 원인은 [05장 §2.2](../05-iceberg-on-s3/)의 절대경로 문제입니다.

## 1. 반입 전 결정 사항

| 결정 | 선택지 | 권장 | 근거 |
|---|---|---|---|
| 데이터 범위 | 전체 / 일부 파티션 / 샘플링 | **일부 파티션** | 스캐너 사이클(02장 §5)이 규모에 비례 |
| 반입 방식 | CTAS / mirror+register / rewrite_table_path | **CTAS** | 경로 문제 원천 차단 |
| 버킷명 | 원본과 동일 / 다르게 | 상황에 따라 (§3) | 동일하면 mirror가 쉬워짐 |
| 마스킹 | 필요 / 불필요 | 사내 정책 따름 | §2 |
| 원본 접근 | 직접 / 사본 경유 | **사본 경유 권장** | 운영 영향 차단 |
| 테이블 수 | 1개 / 여러 개 | 처음엔 1개 | 원인 분리 |

## 2. 거버넌스 체크포인트 (관리적 통제)

기술 작업 전에 확인해야 할 항목입니다. 미완료 시 진행하지 마십시오.

| # | 항목 | 확인 주체 | 완료 | 비고 |
|---|---|---|---|---|
| GV-1 | 운영 데이터 테스트 사용 승인 | 데이터 오너 | ☐ | 승인 근거 문서화 |
| GV-2 | 개인정보 포함 여부 판단 | 개인정보 담당 | ☐ | 포함 시 GV-3 필수 |
| GV-3 | 마스킹/비식별 처리 방안 | 데이터팀 | ☐ | §4.3 |
| GV-4 | 반입 데이터 보존기간·폐기 계획 | 데이터팀 | ☐ | 테스트 종료 후 폐기 |
| GV-5 | 접근 권한 최소화 (읽기 전용 계정) | 보안팀 | ☐ | 작업 후 계정 폐기 |
| GV-6 | 원본 클러스터 부하 영향 평가 | 스토리지팀 | ☐ | 대량 읽기 발생 |
| GV-7 | 반입 작업 시간대 합의 | 운영팀 | ☐ | 업무시간 외 권장 |
| GV-8 | 감사 로그 보관 | 보안팀 | ☐ | 누가 무엇을 반입했는지 |

### ⚠️ 원본 클러스터 영향

전체 테이블 CTAS는 원본에 대해 **전량 읽기**를 발생시킵니다.

| 완화책 | 방법 |
|---|---|
| 파티션 한정 | `WHERE dt >= ...` 로 범위 축소 |
| 병렬도 제한 | executor 수/코어 축소, `spark.sql.files.maxPartitionBytes` 조정 |
| 시간대 분리 | 야간/주말 |
| 읽기 전용 복제본 사용 | 있는 경우 |
| 속도 제한 | `mc mirror --limit-download` 🔍 |

## 3. 🔴 왜 단순 복사로는 안 되는가

### 3.1 문제 구조

```
원본:  s3://prod-warehouse/db.db/tbl/metadata/00042-uuid.metadata.json
       ↑ 이 안에:  "manifest-list": "s3://prod-warehouse/db.db/tbl/metadata/snap-....avro"
                   manifest 안:     "file_path": "s3://prod-warehouse/db.db/tbl/data/....parquet"

mc mirror 로 복사 →

대상:  s3://warehouse/db.db/tbl/metadata/00042-uuid.metadata.json
       ↑ 내용은 그대로:  "s3://prod-warehouse/..." 를 계속 가리킴 🔴
                          → 테스트 클러스터에 없는 경로 → 조회 실패
                          → 또는 더 나쁜 경우: 운영 클러스터를 읽으러 감 ⚠️
```

### 3.2 버킷명이 같으면 되는가?

| 조건 | 결과 |
|---|---|
| 버킷명 동일 + 엔드포인트만 다름 | ✅ **동작함** (경로 문자열이 `s3://warehouse/...` 로 동일) |
| 버킷명 다름 | ❌ 경로 재작성 필요 |
| 스킴 다름 (`s3a` vs `s3`) | ❌ 설정에 따라 실패 |
| DB/테이블명 다름 | ❌ (디렉터리 경로가 달라짐) |

> ✅ **가장 쉬운 길: 테스트 클러스터의 버킷명·DB명·테이블명을 원본과 동일하게 만드는 것.**
> 그러면 mirror + HMS 등록만으로 동작합니다. 다만 **운영 엔드포인트로 잘못 접속할 위험**이 커지므로 §3.3 안전장치를 반드시 두십시오.

### 3.3 ⚠️ 동일 버킷명 사용 시 안전장치

| 위험 | 안전장치 |
|---|---|
| Spark가 실수로 운영 엔드포인트 접속 | 테스트 K8s 네임스페이스에서 운영 S3로 **NetworkPolicy 차단** |
| 자격증명 혼동 | 테스트 계정은 운영에 권한 없음 (별도 계정) |
| HMS 혼동 | **테스트 전용 HMS** 사용 (운영 HMS 공유 금지) 🔴 |
| 사람의 alias 혼동 | mc alias 이름을 `PROD-RO`, `HOT`, `WARM`으로 명확히 |

🔴 **운영 HMS를 테스트에서 공유하면 절대 안 됩니다.** 테스트 커밋이 운영 테이블의 `metadata_location`을 바꿔버릴 수 있습니다. 이것이 이 챕터에서 가장 위험한 실수입니다.

## 4. 반입 방법 3가지

### 방법 1: Spark CTAS (권장) ✅

원본을 읽어 테스트 카탈로그에 **새 테이블로 다시 씀**. 모든 경로가 새로 생성되므로 경로 문제가 원천적으로 없습니다.

```python
# ingest-ctas.py
from pyspark.sql import SparkSession

spark = (SparkSession.builder
         .appName("ingest-prod-to-test")
         # 원본 카탈로그 (읽기 전용)
         .config("spark.sql.catalog.prod", "org.apache.iceberg.spark.SparkCatalog")
         .config("spark.sql.catalog.prod.type", "hive")
         .config("spark.sql.catalog.prod.uri", "thrift://prod-hms:9083")
         .config("spark.sql.catalog.prod.warehouse", "s3://prod-warehouse/")
         .config("spark.sql.catalog.prod.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
         .config("spark.sql.catalog.prod.s3.endpoint", "https://prod-s3.example.internal")
         .config("spark.sql.catalog.prod.s3.path-style-access", "true")
         .config("spark.sql.catalog.prod.s3.access-key-id", "<PROD_RO_KEY>")
         .config("spark.sql.catalog.prod.s3.secret-access-key", "<PROD_RO_SECRET>")
         # 대상 카탈로그 (테스트 hot)
         .config("spark.sql.catalog.hive_prod", "org.apache.iceberg.spark.SparkCatalog")
         .config("spark.sql.catalog.hive_prod.type", "hive")
         .config("spark.sql.catalog.hive_prod.uri", "thrift://hms.data.svc:9083")
         .config("spark.sql.catalog.hive_prod.warehouse", "s3://warehouse/")
         .config("spark.sql.catalog.hive_prod.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
         .config("spark.sql.catalog.hive_prod.s3.endpoint", "https://hot-s3.example.internal")
         .config("spark.sql.catalog.hive_prod.s3.path-style-access", "true")
         .getOrCreate())

SRC = "prod.db.orders"
DST = "hive_prod.ilm_test.orders"

spark.sql("CREATE DATABASE IF NOT EXISTS hive_prod.ilm_test")

# 1) 원본 규모 파악
spark.sql(f"SELECT count(*) AS files, sum(file_size_in_bytes)/1e9 AS gb FROM {SRC}.files").show()

# 2) 파티션 범위를 한정해 반입 (전체 반입 지양)
spark.sql(f"""
  CREATE TABLE {DST}
  USING iceberg
  PARTITIONED BY (days(order_ts))
  TBLPROPERTIES (
    'write.target-file-size-bytes'='536870912',
    'write.metadata.delete-after-commit.enabled'='true',
    'write.metadata.previous-versions-max'='20',
    'commit.manifest-merge.enabled'='true',
    'format-version'='2'
  )
  AS SELECT * FROM {SRC}
     WHERE order_ts >= timestamp'2026-08-01' AND order_ts < timestamp'2026-08-15'
""")

# 3) 검증
spark.sql(f"SELECT count(*) FROM {DST}").show()
spark.sql(f"SELECT count(*) AS files, sum(file_size_in_bytes)/1e9 AS gb, avg(file_size_in_bytes)/1e6 AS avg_mb FROM {DST}.files").show()
spark.sql(f"SELECT file_path FROM {DST}.files LIMIT 3").show(truncate=False)   # 경로가 테스트 버킷인지 확인 ★
spark.stop()
```

| 장점 | 단점 |
|---|---|
| 경로 문제 없음 ✅ | 원본 전량 읽기 부하 |
| 파일 크기·파티셔닝 재설계 가능 ✅ | 스냅샷 이력이 사라짐 (스냅샷 1개로 시작) |
| 마스킹을 SELECT에 넣을 수 있음 ✅ | 시간이 오래 걸림 |
| 스키마 정리 가능 | |

⚠️ CTAS 결과는 **스냅샷이 1개**입니다. 시간여행·`expire_snapshots` 테스트를 하려면 §5에서 스냅샷을 인위적으로 여러 개 만들어야 합니다.

### 방법 2: mc mirror + register_table

객체를 그대로 복사하고 HMS에만 등록. **버킷/DB/테이블 경로가 완전히 동일할 때만** 유효합니다.

```bash
# 1) 객체 복사 (읽기 전용 원본 alias 사용)
mc mirror --preserve --overwrite \
  PROD-RO/warehouse/db.db/orders/ \
  HOT/warehouse/db.db/orders/

# 2) 복사 검증
mc ls --recursive PROD-RO/warehouse/db.db/orders/ | wc -l
mc ls --recursive HOT/warehouse/db.db/orders/     | wc -l   # 같아야 함

# 3) 최신 metadata.json 경로 확인
mc ls HOT/warehouse/db.db/orders/metadata/ | grep metadata.json | sort | tail -3
```

```sql
-- 4) HMS에 등록 (Iceberg register_table 프로시저)
CALL hive_prod.system.register_table(
  table => 'ilm_test.orders',
  metadata_file => 's3://warehouse/db.db/orders/metadata/00042-uuid.metadata.json'
);

-- 5) 검증
SELECT count(*) FROM hive_prod.ilm_test.orders;
SELECT file_path FROM hive_prod.ilm_test.orders.files LIMIT 3;   -- 경로 확인 ★
```

| 장점 | 단점 |
|---|---|
| 빠름 (재작성 없음) | 🔴 버킷명이 다르면 동작 안 함 |
| 스냅샷 이력 보존 ✅ | 운영과 동일 경로 사용에 따른 혼동 위험 |
| 원본 부하가 상대적으로 낮음 | 마스킹 불가 |
| 파일 구성 그대로 재현 ✅ | 원본의 소파일 문제도 그대로 옴 |

> ✅ **스냅샷 이력이 있는 상태에서 ILM을 테스트하려면 이 방법이 유리합니다.** 다양한 나이의 객체가 이미 존재하기 때문입니다.

⚠️ `--preserve` 는 원본의 타임스탬프를 보존하려 하지만, **S3 객체의 LastModified는 PUT 시각으로 새로 찍힙니다** 🔍. 즉 **복사된 객체는 전부 "오늘 생성"으로 간주**되어 ILM 1일 규칙이 즉시 걸리지 않습니다. 이 문제의 해법은 §6에 있습니다.

### 방법 3: rewrite_table_path (Iceberg 1.7+) 🔍

버킷/경로가 다른 곳으로 옮길 때 **메타데이터 내부 경로를 일괄 재작성**해 주는 프로시저입니다.

```sql
-- 🔍 Iceberg 버전에 따라 시그니처가 다를 수 있음. 먼저 지원 여부 확인
CALL hive_prod.system.rewrite_table_path(
  table => 'ilm_test.orders',
  source_prefix => 's3://prod-warehouse/db.db/orders',
  target_prefix => 's3://warehouse/ilm_test.db/orders'
);
```

| 장점 | 단점 |
|---|---|
| 스냅샷 이력 보존 + 경로 변경 동시 달성 ✅ | 버전 의존 🔍 (미지원 시 사용 불가) |
| 데이터 재작성 불필요 (빠름) | 절차가 복잡 (메타 재작성 후 파일 복사 순서 주의) |
| | 프로시저 결과물을 대상에 복사하는 후속 단계 필요 |

> 지원되지 않는 버전이면 방법 1 또는 2를 쓰십시오.

### 방법 선택 결정표

```
버킷/DB/테이블 경로를 원본과 동일하게 할 수 있는가?
├─ YES → 스냅샷 이력이 필요한가?
│         ├─ YES → 방법 2 (mirror + register_table)  ← 권장
│         └─ NO  → 방법 1 (CTAS)
└─ NO  → 마스킹이 필요한가?
          ├─ YES → 방법 1 (CTAS, SELECT에서 마스킹)   ← 권장
          └─ NO  → rewrite_table_path 지원되는가?
                    ├─ YES → 방법 3
                    └─ NO  → 방법 1 (CTAS)
```

### 4.3 마스킹 예시 (방법 1과 결합)

```sql
CREATE TABLE hive_prod.ilm_test.orders USING iceberg
PARTITIONED BY (days(order_ts))
AS SELECT
     order_id,
     sha2(customer_id, 256)                     AS customer_id,   -- 해시
     regexp_replace(email, '(^.).*(@.*$)', '$1***$2') AS email,   -- 부분 마스킹
     CAST(NULL AS STRING)                       AS phone,          -- 제거
     order_ts, amount, region                                       -- 원본 유지
   FROM prod.db.orders
   WHERE order_ts >= timestamp'2026-08-01';
```

| 기법 | 용도 | 주의 |
|---|---|---|
| 해시 | 조인 키 유지하며 식별성 제거 | 카디널리티 유지 → 파일 크기 유사 ✅ |
| 부분 마스킹 | 형식 유지 | 압축률 변화 가능 |
| NULL 치환 | 완전 제거 | **압축률이 크게 달라져 파일 크기 특성이 변함** ⚠️ |
| 샘플링 | 규모 축소 | 파티션 분포가 달라짐 |

⚠️ 마스킹이 **파일 크기 분포를 바꾸면 ILM/성능 테스트의 대표성이 떨어집니다.** 성능 측정이 목적이면 카디널리티·길이를 보존하는 마스킹(해시, 랜덤 대체)을 쓰십시오.

## 5. 테스트에 필요한 데이터 상태 만들기

ILM/복제 테스트에는 단순 데이터 외에 **특정 상태**가 필요합니다.

| 필요한 상태 | 만드는 방법 | 검증 |
|---|---|---|
| 여러 스냅샷 | 여러 번 나눠서 INSERT | `SELECT count(*) FROM tbl.snapshots` |
| 다양한 파일 나이 | 며칠에 걸쳐 나눠 적재 또는 §6 기법 | `mc ls --recursive` 의 날짜 |
| noncurrent 버전 | `rewrite_data_files` 후 `expire_snapshots` | `mc ls --versions` |
| delete marker | `DELETE FROM` 후 `expire_snapshots` | `mc ls --versions \| grep DELETEMARKER` |
| 소파일 다수 | 작은 배치로 다수 INSERT | `tbl.files` 의 avg 크기 |
| v2 delete file | `DELETE`/`UPDATE`/`MERGE` 실행 | `SELECT count(*) FROM tbl.delete_files` |
| 대용량 파티션 | 한 파티션에 집중 적재 | `tbl.partitions` |

### 5.1 스냅샷 여러 개 만들기

```python
from datetime import datetime, timedelta

DST = "hive_prod.ilm_test.orders"
base = datetime(2026, 8, 1)
for i in range(14):                       # 14개 스냅샷
    d0 = base + timedelta(days=i)
    d1 = d0 + timedelta(days=1)
    spark.sql(f"""
      INSERT INTO {DST}
      SELECT * FROM prod.db.orders
      WHERE order_ts >= timestamp'{d0:%Y-%m-%d}' AND order_ts < timestamp'{d1:%Y-%m-%d}'
    """)
    print(f"snapshot {i+1} committed for {d0:%Y-%m-%d}")

spark.sql(f"SELECT snapshot_id, committed_at, operation FROM {DST}.snapshots ORDER BY committed_at").show(50, False)
```

### 5.2 noncurrent 버전 / delete marker 만들기

```sql
-- 1) 소파일을 만든 뒤 compaction → 구 파일이 삭제되어 noncurrent 발생
CALL hive_prod.system.rewrite_data_files(
  table => 'ilm_test.orders',
  options => map('min-input-files','2','target-file-size-bytes','536870912')
);

-- 2) 스냅샷 만료 → 실제 S3 DELETE 발생 → delete marker + noncurrent
CALL hive_prod.system.expire_snapshots(
  table => 'ilm_test.orders',
  older_than => TIMESTAMP '2026-08-20 00:00:00',
  retain_last => 3
);
```

```bash
# 확인: 버전과 delete marker
mc ls --versions --recursive HOT/warehouse/ilm_test.db/orders/data/ | head -30
mc ls --versions --recursive HOT/warehouse/ilm_test.db/orders/data/ | grep -ci "DELETE"   # 마커 수
```

## 6. ★ 객체 나이 문제 — "1일 대기"를 어떻게 할 것인가

복사된 객체는 전부 "방금 생성"입니다. 1일 규칙 테스트를 하려면 최소 하루를 기다려야 하고, 스캐너 사이클까지 더하면 최대 3일입니다.

### 해결책 비교

| 방법 | 소요 | 정확도 | 위험 | 권장 |
|---|---|---|---|---|
| A. 그냥 기다린다 | 1~3일 | 최고 (실제 동작) | 없음 | ✅ 최종 검증용 |
| B. **Transition을 날짜(Date) 기준으로 지정** | 즉시 | 높음 | 규칙 오적용 주의 | ✅ **1차 검증용** |
| C. `days=0` 규칙 🔍 | 즉시~ | 중 (지원 여부 확인) | 전체 즉시 전이 | 🟡 |
| D. 스캐너 가속만 적용 | 여전히 1일+ | 높음 | I/O 부하 | 보조 |
| E. 객체 시각 조작 | - | - | **불가/위험** | ✖ |

### 방법 B: 과거 날짜 기준 전이 규칙

S3 Lifecycle은 `Days` 대신 `Date`를 지정할 수 있습니다. **과거 날짜를 지정하면 모든 대상 객체가 즉시 전이 대상**이 됩니다.

```json
{
  "Rules": [{
    "ID": "test-transition-by-date",
    "Status": "Enabled",
    "Filter": { "Prefix": "ilm_test.db/orders/data/" },
    "Transition": { "Date": "2020-01-01T00:00:00Z", "StorageClass": "WARM-TIER" }
  }]
}
```

```bash
mc ilm rule export HOT/warehouse > ilm-backup.json     # 백업 필수
mc ilm rule import HOT/warehouse < ilm-test-by-date.json
```

| 항목 | 내용 |
|---|---|
| 효과 | 스캐너가 방문하는 즉시 전이 (나이 대기 없음) |
| 남는 대기 | 스캐너 사이클만 (04장 §6으로 단축) |
| ⚠️ 위험 | 프리픽스를 잘못 쓰면 **전 객체가 즉시 전이**됨. 반드시 프리픽스 한정 |
| 🔴 금지 | 같은 기법을 **Expiration에 사용 금지** — 즉시 전량 삭제됨 |
| 사후 | 테스트 후 반드시 Days 기준 규칙으로 원복 |

> ✅ **권장 테스트 순서**: (1) 방법 B로 전이 로직·조회 정상성·성능을 빠르게 검증 → (2) 방법 A로 실제 `Days: 1` 규칙의 타이밍을 최종 확인.

### 🔴 방법 B 사용 시 안전 규칙

| 규칙 | 이유 |
|---|---|
| 반드시 **전용 테스트 프리픽스**에만 적용 | 오적용 시 전 데이터 전이 |
| `Expiration`에는 절대 사용 금지 | 즉시 전량 삭제 → 복구 불가 🔴 |
| 적용 전 `mc ilm rule export` 백업 | 원복 경로 확보 |
| 적용 후 `verify-ilm.sh`(04장 §3.5) 실행 | 위험 규칙 자동 탐지 |
| 테스트 종료 시 규칙 제거 확인 | 방치 시 운영 데이터에 영향 |

## 7. 반입 검증 체크리스트

| # | 항목 | 명령/쿼리 | 기대 | ✅ |
|---|---|---|---|---|
| I-1 | 테이블 조회 가능 | `SELECT count(*) FROM hive_prod.ilm_test.orders` | 성공 | |
| I-2 | 행 수 일치 | 원본 대비 (범위 한정 감안) | 일치 | |
| I-3 | **파일 경로가 테스트 버킷** | `SELECT file_path FROM ....files LIMIT 3` | `s3://warehouse/...` ★ | |
| I-4 | 원본 경로 잔존 없음 | 위 결과에 `prod-` 없음 | 없음 🔴 | |
| I-5 | 스키마 일치 | `DESCRIBE` 비교 | 일치 | |
| I-6 | 파티션 구조 정상 | `SELECT * FROM ....partitions` | 예상대로 | |
| I-7 | 파일 크기 분포 | `avg(file_size_in_bytes)` | 05장 §8 기준표 | |
| I-8 | 스냅샷 수 | `SELECT count(*) FROM ....snapshots` | 테스트에 충분 | |
| I-9 | 복제 진행 | `mc replicate status HOT/warehouse` | 진행/완료 | |
| I-10 | warm 객체 수 | `mc ls --recursive WARM/warehouse/... \| wc -l` | hot과 일치(지연 후) | |
| I-11 | 마스킹 적용 확인 | 샘플 조회 | 원본값 없음 | |
| I-12 | 운영 HMS 미변경 | 운영 테이블 `metadata_location` 비교 | 변경 없음 🔴 | |

### I-3/I-4 자동 검증

```python
bad = [r["file_path"] for r in spark.sql(
        "SELECT file_path FROM hive_prod.ilm_test.orders.files").collect()
       if not r["file_path"].startswith("s3://warehouse/")]
assert not bad, f"테스트 버킷 밖을 가리키는 파일 {len(bad)}건: {bad[:5]}"
print("경로 검증 통과")
```

## 8. 데이터 규모 산정

반입 규모를 정할 때 아래 표로 영향을 추정하십시오.

| 항목 | 산정식 | 예시 (1TB, 평균 256MB 파일) |
|---|---|---|
| 데이터 파일 수 | 총량 / 평균 파일크기 | 1TB / 256MB ≈ 4,096개 |
| S3 객체 수 (초기) | 데이터 파일 + metadata | ≈ 4,200개 |
| S3 객체 수 (유지보수 후) | × (1 + noncurrent 배수) | ≈ 8,000~12,000개 |
| hot 사용량 | 데이터 총량 (EC 오버헤드 별도) | 1TB |
| **warm 사용량** | (전이분) + (복제분) | 최대 2TB ⚠️ |
| 전이 전송량 | 전이 대상 총량 | 1TB |
| 복제 전송량 | 전체 총량 | 1TB |
| 스캐너 사이클 영향 | 객체 수 × 버전 수에 비례 | - |

### ⚠️ 방식 A+B 동시 사용 시 warm 용량 2배

전이본(warm-tier 버킷)과 복제본(warehouse 버킷)이 **별개로 존재**할 수 있습니다.

```
hot:  data/x.parquet  → (복제) → warm/warehouse/data/x.parquet   [사본 1]
                      → (전이) → warm/warm-tier/<uuid>            [사본 2]
```

| 구성 | warm 실효 사용량 |
|---|---|
| 방식 A만 | 1× |
| 방식 B만 | 1× |
| A + B 동시 | **최대 2×** ⚠️ |

용량 산정 시 반드시 반영하십시오. → [10장 §6](../10-performance/)

### 권장 테스트 규모 단계

| 단계 | 규모 | 목적 | 예상 소요 |
|---|---|---|---|
| 1 | 객체 ~1,000개 / ~10GB | 정책 로직 검증 (전이/조회/제외) | 반나절 |
| 2 | 객체 ~10,000개 / ~200GB | 스캐너 사이클·복제 지연 관측 | 2~3일 |
| 3 | 실 운영 규모 부분 (~1TB) | 성능·용량·장애 시나리오 | 1~2주 |

> ✅ 1단계를 건너뛰고 3단계부터 하면, 문제가 생겼을 때 **정책 오류인지 규모 문제인지 구분할 수 없습니다.**

## 9. 테스트 종료 후 정리

```bash
# 1) 테스트 ILM 규칙 제거 및 원복
mc ilm rule import HOT/warehouse < ilm-backup.json
mc ilm rule ls HOT/warehouse

# 2) 스캐너 원복
mc admin config set HOT scanner speed=default

# 3) 테스트 테이블 삭제 (PURGE = 파일까지 삭제)
#    ⚠️ 전이된 객체도 정리되는지 확인 필요
```

```sql
DROP TABLE hive_prod.ilm_test.orders PURGE;
```

```bash
# 4) 잔여 객체 확인 (버전 포함)
mc ls --versions --recursive HOT/warehouse/ilm_test.db/ | wc -l
mc ls --recursive WARM/warm-tier/ | wc -l

# 5) 임시 계정 폐기
mc admin user remove PROD-RO svc-migrate    # 원본 읽기 전용 계정

# 6) 반입 데이터 폐기 기록 (GV-4)
```

| 정리 항목 | 확인 | ✅ |
|---|---|---|
| 테스트 ILM 규칙 제거 | `mc ilm rule ls` | |
| 스캐너 속도 원복 | `mc admin config get HOT scanner` | |
| 테스트 테이블 삭제 | HMS + S3 | |
| noncurrent 버전 정리 | `mc ls --versions` | |
| warm tier 잔여 정리 | `mc ilm tier info` | |
| 복제본 정리 | `mc ls WARM/warehouse/ilm_test.db/` | |
| 임시 계정 폐기 | `mc admin user list` | |
| 폐기 기록 문서화 | 거버넌스 | |

→ 다음: [08. 테스트 시나리오](../08-test-scenarios/)
