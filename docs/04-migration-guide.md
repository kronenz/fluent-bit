# 운영 → 테스트 데이터 이전 작업 가이드 (1일치 Iceberg 테이블)

> **작업 PC 에서 수행하는 기준**으로 쓴 절차서. 모든 명령·출력은 2026-09-04 에 실제로 실행한 것이다.
> 검증 원문: [`../results/MIGRATION-VERIFICATION.md`](../results/MIGRATION-VERIFICATION.md)

---

## 0. 무엇을 하는 작업인가

운영 레이크하우스에서 **하루치 데이터만** 떼어 테스트 환경으로 옮기고, 테스트 쪽에서
조회가 되는지 확인한다. 옮기는 것은 세 가지다:

1. **데이터 파일** (Parquet) — S3 → S3
2. **Iceberg 메타데이터** (metadata.json / manifest / manifest-list) — S3 → S3
3. **메타스토어 등록** (HMS 의 PostgreSQL 행) — `register_table` 로 생성

### 이번에 사용한 환경

| | 운영 (source) | 테스트 (target) |
|---|---|---|
| S3 | `minio.dataops.svc:9000`<br>(외부 `s3.obs.k8s.miribit.lab`) | `10.10.103.116:9000` (VM) |
| 버킷 | `lakehouse` | **`lakehouse`** (같은 이름 — §3 참조) |
| HMS | `hive-metastore.dataops.svc:9083` | `hive-metastore.ilm-lakehouse.svc:9083` |
| 메타스토어 DB | PostgreSQL (`hms-postgres`, dataops) | PostgreSQL (`postgres`, ilm-lakehouse) |
| 조회 엔진 | Trino 카탈로그 `lake` | Trino 카탈로그 `laketest` |

**S3·HMS·PostgreSQL 이 전부 별개**다. 실제 운영↔테스트 분리와 같은 형상이다.

---

## 1. 작업 PC 준비

### 필요한 도구

| 도구 | 용도 | 설치 |
|---|---|---|
| **`kubectl`** | 클러스터 조작, port-forward, Secret 조회 | 배포판 패키지 또는 [공식 바이너리](https://kubernetes.io/docs/tasks/tools/) |
| **`mc`** (MinIO Client) | S3 간 복사, 버킷·정책 관리 | `curl -O https://dl.min.io/client/mc/release/linux-amd64/mc && chmod +x mc` |
| **`python3`** | Trino 쿼리 실행기(`scripts/trino_query.py`), 매니페스트 템플릿 | 시스템 기본 |
| `psql` *(선택)* | 메타스토어 DB 직접 확인 | `kubectl exec` 로 대체 가능 — 별도 설치 불필요 |
| `trino` CLI *(선택)* | 대화형 쿼리 | `pip install trino` 또는 REST API 직접 호출 |

> Spark 는 **작업 PC 에 설치하지 않는다.** `SparkApplication` CR 을 `kubectl apply` 로 제출해
> 클러스터에서 실행한다. 작업 PC 는 조작·복사·검증만 한다.

### 사전 확인 (3개 다 통과해야 시작)

```bash
export KUBECONFIG=~/path/to/obs.kubeconfig

# ① 클러스터 도달
kubectl -n dataops get pods | head

# ② 운영 S3 도달 (VPN 필요)
curl -s -o /dev/null -w "%{http_code}\n" http://s3.obs.k8s.miribit.lab/minio/health/live   # 200

# ③ 테스트 S3 도달
curl -s -o /dev/null -w "%{http_code}\n" http://10.10.103.116:9000/minio/health/live       # 200
```

### mc 별칭 등록 — **읽기 전용 키로 운영에 붙는다**

```bash
# 운영: svc-trino 는 lakehouse 에 읽기 전용 → 이전 작업의 최소 권한
PA=$(kubectl -n dataops get secret s3-svc-trino -o jsonpath='{.data.access_key}' | base64 -d)
PS=$(kubectl -n dataops get secret s3-svc-trino -o jsonpath='{.data.secret_key}' | base64 -d)
mc alias set prod http://s3.obs.k8s.miribit.lab "$PA" "$PS"

# 테스트: 쓰기 필요
TA=$(kubectl -n ilm-lakehouse get secret ilm-minio -o jsonpath='{.data.access_key}' | base64 -d)
TS=$(kubectl -n ilm-lakehouse get secret ilm-minio -o jsonpath='{.data.secret_key}' | base64 -d)
mc alias set test http://10.10.103.116:9000 "$TA" "$TS"
```

> 키를 명령행 문자열로 직접 타이핑하지 말 것. 위처럼 **Secret 에서 변수로 받아** 쓴다
> (셸 히스토리에 남지 않게 하려면 `set +o history` 를 함께 쓴다).

---

## 2. 전체 흐름

```
[운영]                                    작업 PC                        [테스트]
lakehouse.events (3일치)
      │
      │ ① Spark: 하루치를 자기완결 테이블로 추출
      ▼
lakehouse/warehouse/events_20260902/
  ├─ data/ts_day=2026-09-02/*.parquet
  └─ metadata/{metadata.json, *.avro}
      │                                  ② mc mirror
      └──────────────────────────────────────────────────────────▶ lakehouse/warehouse/events_20260902/
                                                                          │
                                         ③ Spark: register_table          │
                                            (테스트 HMS 에 포인터 등록)  ◀─┘
                                                                          ▼
                                         ④ 조회 검증 + 운영과 대조   laketest.restored.events_20260902
```

---

## 3. ★ 시작 전에 반드시 이해할 것 — 버킷 이름

**Iceberg 메타데이터는 `s3://버킷/...` 절대경로를 담는다.** 실제 파일 내용:

```
$ mc cat test/lakehouse/warehouse/events_20260902/metadata/00000-....metadata.json | jq
  location      : s3://lakehouse/warehouse/events_20260902
  manifest-list : s3://lakehouse/warehouse/events_20260902/metadata/snap-6080887....avro
```

그래서 **대상 버킷 이름을 운영과 같게** 두면 복사한 메타데이터가 그대로 유효하다.

### 이름이 다르면 어떻게 되는가 — 실측한 결과

같은 데이터를 `lakehouse-alt` 라는 다른 이름 버킷에 복사하고, 그 경로의 metadata.json 으로
등록한 뒤 조회했다:

```
[alt] 조회 성공: 691200 rows
[alt] 실제 읽은 파일: s3://lakehouse/warehouse/events_20260902/data/...
                      ^^^^^^^^^ 복사해 둔 lakehouse-alt 가 아니라 원본 버킷
```

> ⚠ **에러가 나지 않는다.** 조회가 성공하고 행 수도 맞다. 그런데 실제로는 **복사본을 완전히
> 무시하고 원본 버킷을 읽고 있다.** "이전했고 조회도 된다"고 확인해 놓고 실은 운영 데이터를
> 보고 있는 상태가 된다. 원본 버킷이 없는 환경(진짜 분리된 테스트)으로 가면 그제서야 깨진다.
>
> **대책 (택1)**
> 1. **대상 버킷 이름을 운영과 동일하게 한다** ← 이번에 택한 방법. 가장 단순하고 안전.
> 2. 이름을 바꿔야 하면 메타데이터 경로를 다시 써야 한다 —
>    Iceberg 의 `rewrite_table_path` 프로시저(1.7+) 또는 대상에서 **CTAS 로 재작성**.
> 3. 검증할 때 **반드시 `"<table>$files"` 의 `file_path` 를 눈으로 확인**해 대상 버킷을
>    가리키는지 본다. 행 수만 보면 이 함정을 못 잡는다.

---

## 4. 단계별 절차

### ① 하루치를 자기완결 테이블로 추출 (운영)

**파티션 디렉터리만 복사하면 안 된다.** 원본 테이블의 metadata/manifest 는 **전체 테이블의
파일 목록**을 담고 있어, 대상에서 나머지 날짜 파일을 찾다가 깨진다.
새 테이블로 뽑으면 그 테이블의 메타데이터가 **자기 파일만** 가리켜 통째로 옮길 수 있다.

```bash
scripts/run-spark.sh extract_day
```

내부적으로 수행되는 SQL:

```sql
CREATE TABLE lake.lakehouse.events_20260902
USING iceberg
PARTITIONED BY (days(ts))
LOCATION 's3://lakehouse/warehouse/events_20260902' AS
SELECT * FROM lake.lakehouse.events
WHERE ts >= TIMESTAMP '2026-09-02 00:00:00'
  AND ts <  TIMESTAMP '2026-09-02 00:00:00' + INTERVAL 1 DAY;
```

실제 출력:

```
[extract] lake.lakehouse.events_20260902: 691200 rows, 데이터파일 1개
[extract] metadata.json = s3://lakehouse/warehouse/events_20260902/metadata/00000-ebae4d1d-f999-4395-a16c-68f95a51d053.metadata.json
  buy    count=  230400 sum=16401516.57
  click  count=  230400 sum=16401645.71
  view   count=  230400 sum=16401774.86
```

> **이 집계값을 적어둔다.** 마지막에 테스트 쪽 결과와 대조할 기준이다.
> **`metadata.json` 경로도 적어둔다.** ③단계에서 그대로 쓴다.

### ② 대상 버킷 준비 + 복사 (작업 PC)

```bash
mc mb --ignore-existing test/lakehouse          # ★ 운영과 같은 이름

mc du prod/lakehouse/warehouse/events_20260902/
# 3.3MiB  4 objects

time mc mirror --overwrite \
  prod/lakehouse/warehouse/events_20260902/ \
  test/lakehouse/warehouse/events_20260902/
# Total 3.29 MiB / Transferred 3.29 MiB / 00m00s / 11.60 MiB/s
# real 0m0.362s
```

옮겨진 것 (자기완결 세트):

```bash
mc ls -r test/lakehouse/warehouse/events_20260902/
# data/ts_day=2026-09-02/00000-1-....parquet          3.3MiB   ← 데이터
# metadata/00000-ebae4d1d-....metadata.json           2.5KiB   ← 테이블 정의·스냅샷 목록
# metadata/72636609-....-m0.avro                      7.0KiB   ← manifest (파일 목록)
# metadata/snap-6080887....avro                       4.4KiB   ← manifest-list
```

> **`mc mirror` 는 작업 PC 를 거쳐 흐른다.** 두 S3 간 서버-투-서버 전송이 아니다.
> 대용량이면 작업 PC 의 대역폭·시간이 병목이 된다 — 큰 이전은 클러스터 안에서
> 잡으로 돌리거나 MinIO 의 배치 리플리케이션을 검토한다.

### ③ 테스트 HMS 에 등록 (register_table)

```bash
META="s3://lakehouse/warehouse/events_20260902/metadata/00000-ebae4d1d-f999-4395-a16c-68f95a51d053.metadata.json"
scripts/run-migrate.sh register "$META"
```

내부 SQL:

```sql
CREATE NAMESPACE IF NOT EXISTS laketest.restored LOCATION 's3://lakehouse/warehouse';
CALL laketest.system.register_table(
  table => 'restored.events_20260902',
  metadata_file => 's3://lakehouse/warehouse/events_20260902/metadata/00000-....metadata.json'
);
```

출력:

```
[register] laketest.restored.events_20260902 등록 완료 — 691200 rows
```

> **`register_table` 은 데이터를 다시 쓰지 않는다.** metadata.json 을 가리키는 포인터만
> 메타스토어에 만든다. 그래서 즉시 끝나고 원본 파일을 손대지 않는다.

#### 메타스토어 DB 에 실제로 들어간 것

```bash
kubectl -n ilm-lakehouse exec deploy/postgres -- psql -U hive -d metastore -c \
 "SELECT d.\"NAME\", t.\"TBL_NAME\", t.\"TBL_TYPE\", s.\"LOCATION\"
  FROM \"TBLS\" t JOIN \"DBS\" d ON t.\"DB_ID\"=d.\"DB_ID\"
  JOIN \"SDS\" s ON t.\"SD_ID\"=s.\"SD_ID\" WHERE t.\"TBL_NAME\" LIKE 'events%';"
```

```
   NAME   |    TBL_NAME     |    TBL_TYPE    |                 LOCATION
 restored | events_20260902 | EXTERNAL_TABLE | s3://lakehouse/warehouse/events_20260902

metadata_location = s3://lakehouse/warehouse/events_20260902/metadata/00000-....metadata.json
table_type        = ICEBERG
```

> **메타스토어 DB 는 포인터만 갖는다.** 스키마·스냅샷·파일 목록은 전부 S3 의 metadata.json 안에 있다.
> 그래서 **PostgreSQL 덤프/복원 없이** `register_table` 한 번으로 끝난다(§6 에 덤프 방식도 정리).

### ④ 조회 검증 + 운영과 대조

**Spark 로:**

```bash
scripts/run-migrate.sh verify
```

```
[verify] laketest.restored.events_20260902: 691200 rows, 데이터파일 1개
  buy    count=  230400 sum=16401516.57
  click  count=  230400 sum=16401645.71
  view   count=  230400 sum=16401774.86
  날짜 2026-09-02: 691200
```

**Trino 로 (작업 PC 에서, 한 쿼리로 양쪽 대조):**

```bash
TRINO_URL=http://trino.obs.k8s.miribit.lab python3 scripts/trino_query.py \
"SELECT 'prod' AS src, count(*) c, round(sum(amount),2) s FROM lake.lakehouse.events_20260902
 UNION ALL
 SELECT 'test', count(*), round(sum(amount),2) FROM laketest.restored.events_20260902"
```

```
src	c	s
test	691200	49204937.14
prod	691200	49204937.14        ← 완전 일치
```

> 하나의 Trino 가 **서로 다른 두 S3·두 HMS·두 PostgreSQL** 을 동시에 읽어 대조한 것이다.
> 이전 검증으로는 이보다 강한 형태가 드물다.

**★ 반드시 함께 확인할 것 — 실제로 읽은 파일 경로:**

```sql
SELECT file_path FROM laketest.restored."events_20260902$files";
-- s3://lakehouse/warehouse/events_20260902/data/ts_day=2026-09-02/00000-1-....parquet
```

§3 의 함정 때문에, **행 수가 맞는다고 대상을 읽고 있다는 뜻이 아니다.**

### ⑤ 정리

```bash
# 테스트 등록만 해제 (S3 데이터는 보존)
scripts/run-migrate.sh cleanup

# 운영의 추출 테이블도 필요 없으면 (★ PURGE 는 파일까지 지운다 — 신중히)
# Spark: DROP TABLE lake.lakehouse.events_20260902
```

---

## 5. 체크리스트

작업 전:

- [ ] 운영 접근이 **읽기 전용 키**인가 (`svc-trino`)
- [ ] 대상 버킷 이름이 **운영과 동일**한가
- [ ] 대상 S3 여유 용량 확인 (`mc du` 로 옮길 크기 확인)
- [ ] 테스트 HMS 가 대상 S3 를 볼 수 있는가 (HMS 자격증명이 그 버킷을 포괄하는가)

작업 후:

- [ ] 행 수가 일치하는가
- [ ] **집계 합계**가 일치하는가 (행 수만으로는 부족)
- [ ] 날짜 분포가 **옮기기로 한 하루만** 있는가
- [ ] **`$files` 의 `file_path` 가 대상 버킷을 가리키는가** ← 가장 중요
- [ ] 메타스토어 DB 에 `table_type=ICEBERG`, `metadata_location` 이 있는가

---

## 6. 대안 — 메타스토어 PostgreSQL 을 통째로 옮기는 방법

테이블 몇 개가 아니라 **메타스토어 전체**를 복제해야 할 때만 쓴다.

```bash
# 덤프 (운영)
kubectl -n dataops exec deploy/hms-postgres -- \
  pg_dump -U hive -d metastore -Fc > metastore.dump

# 복원 (테스트) — 기존 스키마를 지우고 덮어쓴다
kubectl -n ilm-lakehouse exec -i deploy/postgres -- \
  pg_restore -U hive -d metastore --clean --if-exists < metastore.dump
```

**이 방식의 문제점**

- 옮기고 싶지 않은 테이블까지 전부 따라온다.
- `SDS.LOCATION` / `TABLE_PARAMS.metadata_location` 이 **운영 S3 경로 그대로**다.
  버킷 이름이 다르면 전 테이블을 UPDATE 로 고쳐야 한다.
- HMS 스키마 버전이 양쪽에서 같아야 한다.
- 복원 중 테스트 HMS 를 내려야 한다.

> **테이블 단위 이전에는 `register_table` 이 압도적으로 낫다.** 덤프는 환경 복제용이다.

---

## 7. 함정 모음 (이번 작업에서 실제로 겪은 것)

| # | 함정 | 증상 | 대응 |
|---|---|---|---|
| 1 | ★ **메타데이터의 절대경로** | 다른 이름 버킷으로 옮겨도 **에러 없이 조회 성공**하는데 실제로는 원본 버킷을 읽는다 | 버킷 이름 동일하게. 검증 시 `$files` 경로 확인 |
| 2 | 파티션 디렉터리만 복사 | 대상에서 나머지 날짜 파일을 못 찾아 깨짐 | **자기완결 테이블로 추출**한 뒤 통째 복사 |
| 3 | HMS 가 대상 버킷 권한 없음 | `HIVE_METASTORE_ERROR ... AccessDenied 403` | HMS 키가 **모든 대상 버킷**을 포괄해야 함 |
| 4 | `mc mirror` 가 작업 PC 를 경유 | 대용량에서 PC 대역폭이 병목 | 큰 이전은 클러스터 안 잡으로 |
| 5 | 셸 치환에 `s3://` 포함 | `sed: unknown option to 's'` | 구분자 충돌 — 파이썬 등으로 치환 |
| 6 | Trino 정적 카탈로그 | 새 카탈로그(`laketest`)가 안 보임 | 코디네이터·워커 재기동 필요 |
| 7 | 행 수만 검증 | 위 #1 을 못 잡는다 | 집계 합계 + 파일 경로까지 확인 |

---

## 8. 되돌리기

| 되돌릴 것 | 방법 |
|---|---|
| 테스트 테이블 등록 | `DROP TABLE laketest.restored.<table>` (PURGE 없이 — 파일 보존) |
| 테스트 S3 데이터 | `mc rm --recursive --force test/lakehouse/warehouse/<table>/` |
| 테스트 버킷 | `mc rb --force test/lakehouse` |
| 운영 추출 테이블 | Spark `DROP TABLE lake.lakehouse.<table>` (**PURGE 는 파일까지 삭제**) |
| Trino 카탈로그 | `backup/cm-trino-catalog.yaml` 로 되돌린 뒤 재기동 |

운영 쪽은 **읽기만** 했으므로 되돌릴 것이 없다(추출 테이블 생성은 예외).
