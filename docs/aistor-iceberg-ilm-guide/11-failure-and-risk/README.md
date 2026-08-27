# 11. 장애 시나리오 및 리스크 관리 ★

> 이 챕터는 **사고가 났을 때 펴는 문서**입니다. §1 요약표에서 증상을 찾아 해당 F-번호로 이동하십시오.

## 1. 증상별 빠른 진입

| 증상 | 가능성 높은 원인 | 이동 |
|---|---|---|
| 쿼리가 `NotFoundException: ...parquet` | ILM 만료로 데이터 파일 삭제 | **F-02** 🔴 |
| 쿼리가 `NotFoundException: ...metadata.json` / `.avro` | 메타데이터 삭제 | **F-03** 🔴 |
| 구 파티션만 조회 실패, 최신은 정상 | warm 다운 또는 tier 접근 실패 | **F-05 / F-04** |
| 전 테이블 조회 실패, S3는 정상 | HMS 장애 | **F-07** |
| 삭제한 데이터가 다시 조회됨 | delete file 소실 | **F-08** 🔴 |
| 전이가 안 일어남 | 스캐너 대기 또는 규칙 오류 | **F-09** |
| 용량이 줄지 않음 | noncurrent 버전 미정리 | **F-11** |
| warm에 사본이 없음 | 복제 실패/전이 객체 미복제 | **F-12** |
| warm에서 데이터가 사라짐 | 삭제 전파 | **F-13** |
| hot에 만든 규칙이 warm에도 생김 | 사이트 복제로 규칙 전파 | **F-14** |
| 커밋이 계속 실패 | 동시 커밋 충돌 | **F-15** |
| 쿼리가 타임아웃 | 전이 지연 + 짧은 타임아웃 | **F-16** |
| 테이블이 통째로 사라짐 | DROP PURGE 또는 광범위 만료 | **F-17** 🔴 |
| 전이 객체 전체 조회 불가 | tier 삭제/자격증명 | **F-04 / F-18** 🔴 |

## 2. 장애 대응 공통 원칙

| # | 원칙 | 이유 |
|---|---|---|
| 1 | **먼저 채증, 그 다음 조치** | 원인 분석 자료가 사라짐 |
| 2 | **추가 삭제를 유발하는 명령 금지** | `remove_orphan_files`, `expire_snapshots`, `DROP PURGE` |
| 3 | **위험 ILM 규칙을 먼저 비활성화** | 피해 확산 중단 |
| 4 | 쓰기 작업 중지 | 상태 고정 |
| 5 | 버전 목록 확보 | 복구 가능성 판단 근거 |
| 6 | 복구 시도 전 현 상태 스냅샷 | 복구 실패 시 원복 |

### 채증 명령 (사고 발생 즉시 실행)

```bash
#!/usr/bin/env bash
# incident-capture.sh — 사고 즉시 실행
D=./incident-$(date +%Y%m%d-%H%M%S); mkdir -p "$D"
BKT=${BKT:-HOT/warehouse}; TBLP=${TBLP:-ilm_test.db/orders}

mc ilm rule export     "$BKT"           > "$D/ilm-rules.json"      2>&1
mc replicate export    "$BKT"           > "$D/repl-rules.json"     2>&1
mc replicate status    "$BKT"           > "$D/repl-status.txt"     2>&1
mc ilm tier ls HOT --json               > "$D/tiers.json"          2>&1
mc ilm tier info HOT WARM-TIER          > "$D/tier-info.txt"       2>&1
mc ls --versions --recursive "$BKT/$TBLP/" > "$D/objects-versions.txt" 2>&1
mc ls --recursive WARM/warm-tier/       > "$D/warmtier.txt"        2>&1
mc ls --recursive WARM/warehouse/"$TBLP"/ > "$D/warmrepl.txt"      2>&1
mc admin info HOT                       > "$D/hot-info.txt"        2>&1
mc admin info WARM                      > "$D/warm-info.txt"       2>&1
mc admin logs HOT --last 500 2>/dev/null > "$D/hot-logs.txt"
mc admin config get HOT scanner         > "$D/scanner.txt"         2>&1
mc admin prometheus metrics HOT cluster > "$D/metrics-cluster.txt" 2>&1
mc admin prometheus metrics HOT node    > "$D/metrics-node.txt"    2>&1
echo "채증 완료: $D"
```

```sql
-- Iceberg 측 채증
SELECT * FROM hive_prod.ilm_test.orders.snapshots ORDER BY committed_at DESC;
SELECT * FROM hive_prod.ilm_test.orders.metadata_log_entries ORDER BY timestamp DESC;
SELECT file_path FROM hive_prod.ilm_test.orders.all_data_files;   -- 전 스냅샷 참조 파일
SELECT file_path FROM hive_prod.ilm_test.orders.all_manifests;
```

---

## 3. 장애 시나리오 상세

### F-01: hot 클러스터 장애 🔴

| 항목 | 내용 |
|---|---|
| 증상 | 모든 S3 접근 실패, 전체 쿼리·쓰기 중단 |
| 영향 | **전면 중단** (단일 진입점) |
| 데이터 유실 | 없음 (일시 중단) |
| RTO | 클러스터 복구 시간 |
| 탐지 | health 체크, P1 알람 |

**대응**

1. AIStor 클러스터 복구 (스토리지팀)
2. 복구 후 Spark 잡 재실행
3. 진행 중이던 커밋의 잔여 파일 확인 (고아 파일 발생 가능 — 정리는 신중히, F-06 참조)

**대비**

| 대비책 | 효과 |
|---|---|
| hot 클러스터 HA/이중화 | 근본 대책 |
| warm으로의 수동 전환 절차 (§8) | RTO 단축 |
| Spark 잡 재시도/체크포인트 | 부분 복구 |

### F-02: ILM expiration으로 데이터 파일 삭제 🔴 치명

| 항목 | 내용 |
|---|---|
| 증상 | `NotFoundException: s3://.../data/xxx.parquet` |
| 원인 | Iceberg 데이터 프리픽스에 age 기반 expiration 적용 |
| 영향 | **테이블 손상**. 해당 파일을 참조하는 모든 스냅샷 조회 불가 |
| 데이터 유실 | **가능 (영구)** |
| 탐지 | 쿼리 실패, P1 알람 |

**즉시 조치 (순서 엄수)**

```bash
# 1) 원인 규칙 즉시 비활성화 — 피해 확산 중단 (최우선)
mc ilm rule export HOT/warehouse > /tmp/ilm-incident-backup.json
mc ilm rule rm HOT/warehouse --id <BAD_RULE_ID>
mc ilm rule ls HOT/warehouse

# 2) 채증
./incident-capture.sh

# 3) 삭제된 파일의 버전이 남아있는지 확인 ★ 복구 가능성 판단
mc ls --versions "HOT/warehouse/ilm_test.db/orders/data/dt=2026-08-01/xxx.parquet"
```

**복구 경로 (가능성 높은 순)**

| # | 경로 | 조건 | 절차 |
|---|---|---|---|
| 1 | **noncurrent 버전 복원** | Versioning ON + noncurrent 미만료 | 아래 §3.F-02.복원 |
| 2 | **warm 복제본에서 복원** | 방식 B 복제 + 삭제 미전파 | `mc cp WARM/... HOT/...` |
| 3 | **이전 스냅샷으로 롤백** | 삭제된 파일을 참조하지 않는 스냅샷 존재 | `rollback_to_snapshot` |
| 4 | **원본 재적재** | 원천 데이터 존재 | 해당 파티션 재생성 |
| 5 | 복구 불가 | 위 전부 불가 | 데이터 유실 확정 |

**복원 절차 (경로 1: 버전 복원)**

```bash
# 삭제 마커 확인
mc ls --versions "HOT/warehouse/ilm_test.db/orders/data/dt=2026-08-01/" | head -20

# delete marker를 제거해 이전 버전을 current로 복원 🔍
mc rm --versions --version-id <DELETE_MARKER_VERSION_ID> \
   "HOT/warehouse/ilm_test.db/orders/data/dt=2026-08-01/xxx.parquet"

# 복원 확인
mc stat "HOT/warehouse/ilm_test.db/orders/data/dt=2026-08-01/xxx.parquet"
```

⚠️ ILM expiration이 **버전을 영구 삭제**했다면(`ExpiredObjectAllVersions`) 이 경로는 불가합니다.

**복원 절차 (경로 3: 스냅샷 롤백)**

```sql
-- 손상되지 않은 스냅샷 찾기
SELECT snapshot_id, committed_at FROM hive_prod.ilm_test.orders.snapshots ORDER BY committed_at DESC;

-- 해당 스냅샷이 삭제된 파일을 참조하는지 확인
SELECT file_path FROM hive_prod.ilm_test.orders.files FOR VERSION AS OF <snapshot_id>;

CALL hive_prod.system.rollback_to_snapshot(table => 'ilm_test.orders', snapshot_id => <ID>);
```

⚠️ 롤백은 그 이후의 커밋을 되돌립니다. 손실되는 데이터 범위를 먼저 확인하십시오.

**예방 (핵심)**

| 통제 | 구현 |
|---|---|
| expiration 규칙 원천 금지 | 04장 §3.4 안티패턴 |
| 자동 규칙 검증 | `verify-ilm.sh` (04장 §3.5) 일일 실행 |
| 규칙 변경 2인 승인 | 09장 §10 |
| 규칙 형상관리 (Git) | 04장 §8 |
| noncurrent 보존 충분히 | 안전망 확보 |

### F-03: 메타데이터 파일 삭제 🔴 치명

| 항목 | 내용 |
|---|---|
| 증상 | `NotFoundException: ...metadata.json` 또는 `snap-*.avro` / `*-m0.avro` |
| 영향 | **테이블 전체 접근 불가** (데이터는 남아 있어도 못 읽음) |
| 데이터 유실 | 메타 유실 (데이터는 복구 가능성 있음) |

**복구 경로**

```sql
-- 1) 이전 metadata.json 목록 확인
SELECT * FROM hive_prod.ilm_test.orders.metadata_log_entries ORDER BY timestamp DESC;
```

```bash
# 2) S3에 남아있는 metadata.json 확인 (버전 포함)
mc ls --versions HOT/warehouse/ilm_test.db/orders/metadata/ | grep metadata.json

# 3) warm 복제본 확인
mc ls WARM/warehouse/ilm_test.db/orders/metadata/ | grep metadata.json
```

```sql
-- 4) 살아있는 metadata.json 으로 테이블 재등록
DROP TABLE hive_prod.ilm_test.orders;    -- ⚠️ PURGE 없이! 파일은 남김
CALL hive_prod.system.register_table(
  table => 'ilm_test.orders',
  metadata_file => 's3://warehouse/ilm_test.db/orders/metadata/00041-<uuid>.metadata.json'
);
SELECT count(*) FROM hive_prod.ilm_test.orders;
```

🔴 `DROP TABLE ... PURGE` 를 절대 쓰지 마십시오. 남은 데이터 파일까지 삭제됩니다.

**최후 수단: 데이터 파일에서 테이블 재구성**

```sql
-- 데이터 파일이 남아있고 스키마를 안다면
CREATE TABLE hive_prod.ilm_test.orders_recovered (...) USING iceberg PARTITIONED BY (...);
-- Parquet 을 직접 읽어 재적재
INSERT INTO hive_prod.ilm_test.orders_recovered
SELECT * FROM parquet.`s3://warehouse/ilm_test.db/orders/data/`;
```

⚠️ 이 방법은 **delete file이 반영되지 않아 삭제된 행이 되살아납니다.** 규정 준수 이슈가 될 수 있습니다.

### F-04: tier 접근 불가 (자격증명/삭제/엔드포인트) 🔴

| 항목 | 내용 |
|---|---|
| 증상 | 전이된 객체만 조회 실패. 미전이 객체는 정상 |
| 원인 | tier 자격증명 만료/변경, tier 정의 삭제, warm 엔드포인트/인증서 변경 |
| 영향 | 전이된 전체 데이터 조회 불가 |
| 데이터 유실 | 대개 없음 (접근 문제) — 단 tier 대상 버킷이 삭제됐다면 유실 |

**진단**

```bash
mc ilm tier ls   HOT
mc ilm tier info HOT WARM-TIER          # 접근 실패 시 오류 표시
mc admin logs HOT --last 200 | grep -i tier

# warm 직접 접근 테스트
mc ls WARM/warm-tier/ | head
curl -v https://warm-s3.example.internal/minio/health/live
```

**조치**

| 원인 | 조치 |
|---|---|
| 자격증명 만료/오류 | `mc ilm tier update HOT WARM-TIER --access-key ... --secret-key ...` |
| 계정 삭제됨 | warm에 계정 재생성 후 update |
| 정책 변경 | warm 계정 정책 복원 |
| 엔드포인트/DNS | DNS·인증서 복구 |
| tier 정의 삭제됨 | **동일 이름·동일 대상으로 재등록** 🔍 |
| 대상 버킷 삭제됨 | 🔴 복구 불가 — F-02 복구 경로 검토 |

**예방**

- tier 계정 자격증명 만료일 관리 (09장 Q-03)
- tier 계정에 대한 변경 알람
- warm 엔드포인트 인증서 만료 모니터링
- `mc ilm tier rm` 사용 금지 (운영 절차에서 배제)

### F-05: warm 클러스터 다운

| 항목 | 내용 |
|---|---|
| 증상 | 구 파티션 조회 실패, 최신 파티션 정상. 복제 backlog 증가 |
| 영향 범위 | 전이된 데이터를 읽는 쿼리 전부 |
| 데이터 유실 | 없음 |
| RTO | warm 복구 시간 |

**영향 매트릭스** (T-20에서 실측한 값으로 갱신)

| 작업 | warm 다운 시 |
|---|---|
| 최신(미전이) 파티션 조회 | ✅ 정상 |
| 전이 파티션 조회 | ❌ 실패 |
| 전체 스캔 | ❌ 실패 |
| 신규 쓰기 | ✅ 정상 |
| 메타데이터 조회 | ✅ 정상 (metadata 미전이 시) |
| compaction (구 파티션) | ❌ 실패 |
| 복제 | ⏸ backlog 축적 |
| 신규 전이 | ⏸ 대기 (데이터는 hot에 안전) |

**대응**

1. warm 복구 (스토리지팀)
2. 복구 중에는 **최신 파티션만 조회**하도록 잡/쿼리 임시 제한
3. 복구 후 복제 backlog 해소 확인
4. 실패한 잡 재실행

**대비**

| 대비책 | 효과 | 비용 |
|---|---|---|
| warm HA 구성 | 근본 | 높음 |
| hot 보존 기간 확대 | 영향 범위 축소 | hot 용량 |
| 중요 파티션 전이 제외 규칙 | 핵심 데이터 보호 | 용량 |
| 쿼리 레벨 fallback 없음 | — | Iceberg는 자동 fallback 미제공 |

### F-06: remove_orphan_files 오작동 🔴 치명

| 항목 | 내용 |
|---|---|
| 증상 | 실행 직후 또는 이후 쿼리에서 `NotFoundException` 대량 발생 |
| 원인 | 동시 커밋 중 실행, 메타데이터 읽기 실패, 시계 오차, `older_than` 과소 |
| 영향 | **live 데이터 파일 삭제** |
| 데이터 유실 | **가능 (영구)** |

**이 환경의 기본 방침: 실행 금지**

부득이하게 실행해야 한다면:

```
사전 조건 (전부 충족해야 함)
☐ 해당 테이블에 대한 모든 쓰기 작업 중지 (스트리밍 포함)
☐ 실행 중인 compaction/expire 작업 없음
☐ 복제 backlog 0
☐ 전이 작업 pending 0
☐ older_than 이 현재보다 최소 7일 이전
☐ dry_run 결과를 사람이 검토
☐ dry_run 결과를 tbl.all_data_files / all_manifests 와 대조
☐ 실행 전 버킷 버전 목록 백업
☐ 담당자 2인 입회
```

```sql
-- 1) dry-run
CALL hive_prod.system.remove_orphan_files(
  table => 'ilm_test.orders',
  older_than => TIMESTAMP '2026-08-01 00:00:00',
  dry_run => true
);
```

```python
# 2) dry-run 결과를 live 파일 목록과 대조 (필수)
orphans = {r[0] for r in spark.sql(
    "CALL hive_prod.system.remove_orphan_files(table=>'ilm_test.orders', older_than=>TIMESTAMP '2026-08-01 00:00:00', dry_run=>true)").collect()}
live = {r["file_path"] for r in spark.sql("SELECT file_path FROM hive_prod.ilm_test.orders.all_data_files").collect()} \
     | {r["path"]      for r in spark.sql("SELECT path FROM hive_prod.ilm_test.orders.all_manifests").collect()}
overlap = orphans & live
assert not overlap, f"🔴 live 파일이 고아로 분류됨 {len(overlap)}건 — 실행 중단"
print(f"고아 후보 {len(orphans)}건, live 겹침 없음")
```

**사고 발생 시 복구**: F-02와 동일 경로 (버전 복원 → 복제본 → 스냅샷 롤백 → 재적재)

### F-07: HMS 장애

| 항목 | 내용 |
|---|---|
| 증상 | 모든 Iceberg 테이블 접근 실패. S3는 정상 (`mc ls` 동작) |
| 영향 | 전체 읽기·쓰기 중단 |
| 데이터 유실 | 없음 (메타 DB가 살아있는 경우) |

**진단**

```bash
kubectl -n data get pods -l app=hms
kubectl -n data logs deploy/hms --tail=200
nc -zv hms.data.svc.cluster.local 9083
# 백엔드 DB
psql -h <db> -U hive -c "SELECT count(*) FROM TBLS;"
```

**복구**

1. HMS Pod 재기동
2. 백엔드 DB 연결 확인
3. 백엔드 DB 손상 시 → 백업 복원
4. 최악: `register_table` 로 테이블 재등록 (S3의 metadata.json 경로 필요)

```sql
-- HMS DB 유실 시 테이블 복구
CREATE DATABASE IF NOT EXISTS hive_prod.ilm_test;
CALL hive_prod.system.register_table(
  table => 'ilm_test.orders',
  metadata_file => 's3://warehouse/ilm_test.db/orders/metadata/<최신>.metadata.json'
);
```

```bash
# 최신 metadata.json 찾기
mc ls HOT/warehouse/ilm_test.db/orders/metadata/ | grep metadata.json | sort | tail -3
```

**대비**

| 대비책 | 우선순위 |
|---|---|
| HMS 다중 인스턴스 | 높음 |
| 백엔드 DB HA + 정기 백업 | **최고** |
| `metadata_location` 정기 export | 높음 (복구 시 결정적) |

```bash
# metadata_location 정기 백업 (일 1회 권장)
psql -h <db> -U hive -t -A -F',' -c \
  "SELECT d.NAME, t.TBL_NAME, p.PARAM_VALUE
   FROM TBLS t JOIN DBS d ON t.DB_ID=d.DB_ID
   JOIN TABLE_PARAMS p ON t.TBL_ID=p.TBL_ID
   WHERE p.PARAM_KEY='metadata_location'" > metadata-locations-$(date +%F).csv
```

> ✅ 이 CSV 하나가 HMS 전체 유실 시 **복구 가능/불가능을 가릅니다.** 반드시 정기 백업하십시오.

### F-08: delete file 소실로 삭제 데이터 부활 🔴

| 항목 | 내용 |
|---|---|
| 증상 | **에러 없음.** 삭제했던 행이 조회 결과에 다시 나타남 |
| 원인 | delete file(작은 파일)이 ILM 만료로 삭제됨 |
| 영향 | **잘못된 결과**. 규정 준수(삭제 요청 이행) 위반 가능 |
| 탐지 난이도 | **매우 높음** (에러가 없음) |

**탐지 방법**

```sql
-- delete file 수 추세 감시 (급감 시 의심)
SELECT count(*) FROM hive_prod.ilm_test.orders.delete_files;

-- 알고 있는 삭제 대상이 조회되는지 정기 검증
SELECT count(*) FROM hive_prod.ilm_test.orders WHERE order_id IN (<삭제했던 ID들>);
-- 0이어야 정상
```

```bash
# delete file 이 전이/만료 대상인지 확인
mc ls --recursive HOT/warehouse/ilm_test.db/orders/data/ | grep -i delete | head
mc stat "HOT/warehouse/ilm_test.db/orders/data/<delete-file>" | grep -i tier
```

**예방 (핵심)**

| 통제 | 내용 |
|---|---|
| 데이터 프리픽스에 expiration 금지 | F-02와 동일 통제 |
| delete file 위치 파악 | `data/` 하위에 섞여 있음 — 별도 제외 불가 |
| 크기 필터 병용 | `ObjectSizeGreaterThan` 로 소파일 전이 제외 (05장 §6.3) |
| 삭제 검증 테스트 정기 실행 | 위 SQL을 주간 배치에 편성 |
| copy-on-write 모드 검토 | delete file 자체를 만들지 않음 |

```sql
-- copy-on-write 로 전환 (delete file 미생성, 대신 재작성 비용)
ALTER TABLE hive_prod.ilm_test.orders SET TBLPROPERTIES (
  'write.delete.mode'='copy-on-write',
  'write.update.mode'='copy-on-write',
  'write.merge.mode'='copy-on-write'
);
```

| 모드 | delete file | 쓰기 비용 | 읽기 비용 | 전이 환경 적합성 |
|---|---|---|---|---|
| merge-on-read (기본) | 생성됨 | 낮음 | 높음 (소파일 다수) | 🟠 |
| copy-on-write | 없음 | 높음 (파일 재작성) | 낮음 | ✅ |

### F-09: 전이가 일어나지 않음

| 항목 | 내용 |
|---|---|
| 증상 | 규칙을 걸었는데 며칠이 지나도 전이 안 됨 |
| 영향 | hot 용량 절감 미달. 데이터는 안전 |
| 심각도 | 🟡 (데이터 안전) |

**원인 순위와 판별** — [09장 §3.1](../09-operations/) 흐름도 참조

| 순위 | 원인 | 판별 | 조치 |
|---|---|---|---|
| 1 | **프리픽스 불일치** | `mc ls --recursive` 실제 경로와 대조 | 규칙 프리픽스 수정 |
| 2 | 스캐너 사이클 대기 | `bucket_scans_finished` 증분 | 대기 또는 가속 |
| 3 | 객체 나이 부족 | `mc ls` 날짜 + S3 days 해석 | 대기 또는 Date 규칙 |
| 4 | 규칙 미등록/비활성 | `mc ilm rule ls` | 등록/활성화 |
| 5 | 전이 작업 적체 | `ilm_transition_pending_tasks` | tier 대역폭 확인 |
| 6 | tier 접근 실패 | `mc ilm tier info` | F-04 |
| 7 | 스캐너 정지 | `objects_scanned` 정체 | 서비스 점검 |

### F-10: 전이가 과도하게 발생 (metadata 포함)

| 항목 | 내용 |
|---|---|
| 증상 | 모든 쿼리가 급격히 느려짐. 플래닝 시간 급증 |
| 원인 | 프리픽스를 넓게 잡아 metadata까지 전이됨 |
| 영향 | 전체 성능 저하 |

**조치**

```bash
# 1) 규칙 즉시 수정 (프리픽스 한정)
mc ilm rule rm HOT/warehouse --id <BAD_RULE>
mc ilm rule add HOT/warehouse --prefix "ilm_test.db/orders/data/" --transition-days 1 --transition-tier WARM-TIER

# 2) 이미 전이된 metadata 를 hot으로 되돌리기 🔍
#    ⚠️ 전이 취소 명령이 없을 수 있음. 그 경우 아래 우회
```

**전이 취소 우회 (복사 재작성)**

```bash
# 객체를 자기 자신으로 복사하면 새 버전이 hot에 생성됨 (전이 상태 해제)
mc cp "HOT/warehouse/ilm_test.db/orders/metadata/00042-x.metadata.json" \
      "HOT/warehouse/ilm_test.db/orders/metadata/00042-x.metadata.json"
mc stat "HOT/warehouse/ilm_test.db/orders/metadata/00042-x.metadata.json"   # Tier 표기 사라졌는지 확인
```

⚠️ 이 방법은 **새 버전을 만들고 noncurrent를 남깁니다.** 대량 실행 시 버전 수가 늘어납니다. 🔍 실제 동작을 소량으로 먼저 확인하십시오.

### F-11: 용량이 줄지 않음 (noncurrent 축적)

| 항목 | 내용 |
|---|---|
| 증상 | `expire_snapshots` 를 해도 사용량이 그대로 |
| 원인 | Versioning ON + noncurrent 만료 규칙 없음 |
| 영향 | 용량 폭증 → 스캐너 사이클 악화 → ILM 지연 (악순환) |

**진단**

```bash
# 논리 객체 수 vs 총 버전 수
A=$(mc ls --recursive          HOT/warehouse/ilm_test.db/orders/ | wc -l)
B=$(mc ls --versions --recursive HOT/warehouse/ilm_test.db/orders/ | wc -l)
echo "current=$A total_versions=$B ratio=$(echo "scale=2;$B/$A" | bc)"
```

| ratio | 판정 |
|---|---|
| ~1.0 | 정상 |
| 1.0~2.0 | 주의 |
| > 2.0 | 🟠 noncurrent 정책 필요 |
| > 5.0 | 🔴 심각 |

**조치**: [04장 §5](../04-ilm-policy-design/) noncurrent expiration 규칙 적용

### F-12: 복제 실패 누적

| 항목 | 내용 |
|---|---|
| 증상 | `X-Amz-Replication-Status: FAILED`, backlog 증가 |
| 원인 | 대상 접근 불가, 권한 부족, 대상 버저닝 비활성, 대역폭 부족, 원본 버전 만료 |
| 영향 | RPO 손실. 평상시 조회에는 무영향 |

**진단·조치**

```bash
mc replicate status HOT/warehouse
mc admin logs HOT --last 300 | grep -i replicat

# 대상 접근
mc ls WARM/warehouse/ | head
mc version info WARM/warehouse      # Enabled 필수

# 대상 계정 권한
mc admin policy info WARM <policy-name>

# 재동기화
mc replicate resync start  HOT/warehouse --remote-bucket <ARN>
mc replicate resync status HOT/warehouse --remote-bucket <ARN>
```

| 원인 | 조치 |
|---|---|
| 대상 버저닝 비활성 | `mc version enable WARM/warehouse` |
| 권한 부족 | 03장 §3.3 정책 적용 |
| 대상 다운 | 복구 후 자동 재시도 |
| 대역폭 부족 | 전이 작업과 시간대 분리 |
| **원본 noncurrent가 먼저 만료** | noncurrent 보존 기간 확대 ⚠️ |
| 전이 객체 미복제 | T-12 결과에 따라 대응 (구성 재검토) |

### F-13: 삭제 전파로 warm 사본 소실

| 항목 | 내용 |
|---|---|
| 증상 | hot에서 실수로 삭제한 데이터가 warm에서도 사라짐 |
| 원인 | 복제 `delete` / `delete-marker` 전파 ON |
| 영향 | **DR 사본 소실** — 복구 수단 없음 |

**이 환경 특유의 위험**: Iceberg 유지보수(`expire_snapshots`, `rewrite_data_files`)가 **정상 동작으로 대량 삭제를 발생**시킵니다. 전파가 켜져 있으면 그 삭제가 그대로 warm까지 갑니다.

| 대비책 | 장점 | 단점 |
|---|---|---|
| 삭제 전파 OFF | warm이 사실상 백업 | warm 용량 증가, 상태 불일치 |
| warm에 별도 보존 정책 | 유예 기간 확보 | 관리 복잡 |
| warm에 Object Lock / 보존 잠금 🔍 | 강력 | 운영 제약 |
| 삭제 전 승인 절차 | 인적 통제 | 자동화 저해 |

> ✅ **권고: 이 환경에서는 삭제 전파를 OFF로 두고, warm에는 별도의 장기 보존 정책을 두는 편이 안전합니다.** 다만 용량 산정에 반영해야 합니다 (10장 §6).

### F-14: 사이트 복제로 ILM 규칙이 warm에 전파됨 🔴

| 항목 | 내용 |
|---|---|
| 증상 | hot에 만든 규칙이 warm 버킷에도 생김. warm 데이터가 사라짐 |
| 원인 | 사이트 복제(`mc admin replicate`)는 버킷 설정(ILM 포함)을 동기화 🔍 |
| 영향 | warm의 전이/복제 데이터 소실 |

**진단**

```bash
mc admin replicate info HOT           # 사이트 복제 사용 여부
mc ilm rule ls WARM/warehouse
mc ilm rule ls WARM/warm-tier         # 🔴 여기 규칙 있으면 즉시 조치
```

**조치**

1. warm의 위험 규칙 즉시 제거
2. 사이트 복제 사용 여부 재검토 — 버킷 복제로 전환 검토
3. warm-tier 버킷을 사이트 복제 범위에서 제외 🔍
4. 일일 점검(09장 D-03)에 항목 추가

### F-15: 동시 커밋 충돌

| 항목 | 내용 |
|---|---|
| 증상 | `CommitFailedException: metadata location has changed` |
| 원인 | 여러 잡이 같은 테이블에 동시 커밋 |
| 영향 | 잡 실패 (데이터 유실은 없음) |

**조치**

| 조치 | 방법 |
|---|---|
| 재시도 설정 상향 | 06장 §5 |
| 잡 스케줄 분리 | 같은 테이블 동시 실행 회피 |
| 파티션 단위 분리 | 서로 다른 파티션이어도 커밋은 경합함 |
| 배치 크기 확대 | 커밋 횟수 감소 |

### F-16: 쿼리 타임아웃

| 항목 | 내용 |
|---|---|
| 증상 | `SocketTimeoutException`, 태스크 재시도 후 실패. 구 파티션에서만 발생 |
| 원인 | 전이 객체 읽기 지연 > 클라이언트 타임아웃 |

**조치**

```properties
spark.sql.catalog.hive_prod.http-client.apache.socket-timeout-ms      180000
spark.sql.catalog.hive_prod.http-client.apache.connection-timeout-ms   20000
spark.sql.catalog.hive_prod.s3.retry.num-retries                           8
spark.task.maxFailures                                                     8
```

근본 조치: 파일 크기 확대(10장 §1.2), hot 보존 기간 확대, warm 네트워크 개선.

### F-17: 테이블 전체 소실 🔴

| 원인 | 특징 |
|---|---|
| `DROP TABLE ... PURGE` 오실행 | 즉시, 전량 |
| 버킷 전체 만료 규칙 | 점진적, 광범위 |
| 버킷 삭제 | 즉시 |

**복구**

1. 버전 목록 확인 → 대량 복원 시도

```bash
# delete marker 일괄 제거 시도 🔍 (대상 범위를 반드시 좁힐 것)
mc ls --versions --recursive HOT/warehouse/ilm_test.db/orders/ | grep -i delete | head -50
```

2. warm 복제본에서 복원

```bash
mc mirror --preserve WARM/warehouse/ilm_test.db/orders/ HOT/warehouse/ilm_test.db/orders/
```

3. metadata.json 으로 재등록 (F-03 절차)
4. 원천에서 재적재

**예방**

| 통제 | 구현 |
|---|---|
| `DeleteObjectVersion` 권한 미부여 | 03장 §3.2 |
| `DROP PURGE` 사용 금지 절차 | 운영 규정 |
| 버킷 전체 규칙 금지 | 04장 §3.4 |
| Object Lock / 보존 잠금 검토 🔍 | 중요 테이블 |
| 정기 백업 (metadata_location) | F-07 |

### F-18: tier 정의 삭제 🔴

| 항목 | 내용 |
|---|---|
| 증상 | 전이된 전 객체 조회 불가 |
| 원인 | `mc ilm tier rm` 실행 |
| 복구 | **동일 이름·동일 대상으로 재등록** 시 복구 가능성 있음 🔍. 원격 데이터가 삭제됐으면 불가 |

**예방**: 운영 절차에서 `mc ilm tier rm` 배제. 사용 전 `mc ilm tier info`로 전이 객체 수 확인 필수.

---

## 4. 데이터 유실 가능성 판정표

사고 발생 시 "복구 가능한가"를 빠르게 판단하는 표입니다.

| 조건 | 복구 가능성 |
|---|---|
| Versioning ON + noncurrent 미만료 + delete marker만 생성 | ✅ 높음 (버전 복원) |
| Versioning ON + noncurrent 만료됨 | 🟠 warm 복제본 여부에 달림 |
| warm 복제본 존재 + 삭제 미전파 | ✅ 높음 (복제본 복원) |
| warm 복제본 존재 + 삭제 전파됨 | ❌ 낮음 |
| 방식 A만 (전이) + tier 데이터 삭제 | ❌ **불가** (사본 1개뿐) |
| `ExpiredObjectAllVersions` 로 삭제 | ❌ **불가** |
| 원천 데이터 보유 | ✅ 재적재 가능 (시간 소요) |
| 위 전부 해당 없음 | ❌ 유실 확정 |

> 🔴 **방식 A(전이)는 백업이 아닙니다.** 실데이터가 warm에 한 벌만 있습니다. 백업이 필요하면 복제를 별도로 두어야 합니다.

## 5. 복구 절차 요약 (Runbook)

| 상황 | 1단계 | 2단계 | 3단계 | 4단계 |
|---|---|---|---|---|
| 데이터 파일 소실 | 원인 규칙 비활성화 | 채증 | 버전 복원 | 복제본/롤백/재적재 |
| 메타데이터 소실 | 쓰기 중지 | 채증 | 이전 metadata.json 확인 | `register_table` |
| tier 접근 불가 | 채증 | 자격증명/정의 확인 | tier update/재등록 | 검증 |
| warm 다운 | 영향 범위 확인 | 쿼리 제한 안내 | warm 복구 | backlog 해소 확인 |
| HMS 소실 | 쓰기 중지 | DB 복구 시도 | `register_table` 일괄 | 검증 |
| 복제 실패 | 원인 진단 | 조치 | resync | 정합성 검증 |

## 6. 사고 대응 절차 (프로세스)

| 단계 | 활동 | 담당 | 산출물 |
|---|---|---|---|
| 1. 탐지 | 알람/사용자 신고 | 온콜 | 사고 티켓 |
| 2. 초동 | **채증 스크립트 실행**, 확산 차단(규칙 비활성화) | 온콜 | 증적 디렉터리 |
| 3. 영향 평가 | 영향 테이블·파티션·기간 산정 | 데이터팀 | 영향 범위표 |
| 4. 복구 판단 | §4 판정표로 복구 가능성 결정 | 데이터팀+스토리지팀 | 복구 계획 |
| 5. 복구 실행 | §5 Runbook | 담당팀 | 복구 로그 |
| 6. 검증 | 행 수·체크섬·쿼리 정상성 | 데이터팀 | 검증 결과 |
| 7. 사후 | 원인 분석, 재발 방지 | 전체 | 사후 보고서 |
| 8. 통제 반영 | 규칙/알람/절차 개선 | 전체 | 개정된 문서 |

## 7. 영향 범위 산정 템플릿

| 항목 | 값 |
|---|---|
| 발생 시각 | |
| 탐지 시각 | |
| 영향 테이블 | |
| 영향 파티션/기간 | |
| 영향 파일 수 / 용량 | |
| 영향 행 수(추정) | |
| 영향 다운스트림 | |
| 복구 가능성 (§4) | |
| 예상 RTO | |
| 실제 유실 여부 | |

## 8. DR — warm으로의 전환 검토

> ⚠️ 이 환경은 **"저장·액세스는 hot을 통해서만"** 이 전제이므로, warm은 즉시 서비스 가능한 상태가 아닙니다. 전환에는 준비가 필요합니다.

### 8.1 전환 가능성 판단

| 조건 | warm 단독 서비스 가능? |
|---|---|
| 방식 A만 (전이) | ❌ **불가** — warm은 hot의 tier일 뿐, 독립 네임스페이스 아님 |
| 방식 B만 (복제) + 전량 복제 | 🟡 조건부 가능 (아래 절차 필요) |
| A + B, 복제가 전량 커버 | 🟡 조건부 가능 |
| A + B, 전이 객체 미복제 (T-12 결과 c) | ❌ 부분 유실 |

> ✅ **T-12(08장)의 결과가 DR 가능 여부를 결정합니다.** 반드시 실측하십시오.

### 8.2 전환 절차 (방식 B 기준)

```bash
# 1) warm 데이터 완전성 확인
mc ls --recursive WARM/warehouse/ilm_test.db/orders/ | wc -l
mc replicate status HOT/warehouse       # 마지막 복제 시점 = RPO

# 2) warm에 대한 애플리케이션 접근 허용 (네트워크/계정)
mc admin user add WARM svc-spark '<SECRET>'
# 정책 attach

# 3) HMS의 경로가 warm에서도 유효한지 확인 ★
#    버킷명이 같으면 엔드포인트만 바꾸면 됨
```

```properties
# 4) Spark 엔드포인트 전환
spark.sql.catalog.hive_prod.s3.endpoint  https://warm-s3.example.internal
```

```sql
-- 5) 검증
SELECT count(*) FROM hive_prod.ilm_test.orders;
SELECT max(order_ts) FROM hive_prod.ilm_test.orders;   -- RPO 확인
```

| 전제 조건 | 확인 |
|---|---|
| warm 버킷명이 hot과 동일 | ☐ (다르면 경로 재작성 필요 — 07장 §4) |
| HMS가 살아있고 접근 가능 | ☐ |
| warm에 전량 복제 완료 | ☐ |
| warm 접근 계정/권한 준비 | ☐ |
| 네트워크 경로 확보 | ☐ |

### 8.3 RPO/RTO 목표

| 지표 | 측정 방법 | 현재값 | 목표 |
|---|---|---|---|
| RPO | 복제 지연 p95 (08장 T-11) | | |
| RTO (warm 전환) | 위 절차 소요 시간 | | |
| RTO (hot 복구) | 클러스터 복구 시간 | | |
| 전환 후 정상성 | 검증 쿼리 통과 | | |

### 8.4 DR 훈련 체크리스트 (분기 1회)

| # | 항목 | ✅ |
|---|---|---|
| 1 | warm 데이터 완전성 확인 | |
| 2 | 엔드포인트 전환 절차 수행 | |
| 3 | 검증 쿼리 통과 | |
| 4 | RPO 실측 | |
| 5 | RTO 실측 | |
| 6 | 원복 절차 수행 | |
| 7 | 절차서 갱신 | |

## 9. ★ 리스크 레지스터

| ID | 리스크 | 발생가능성 | 영향도 | 등급 | 통제 | 잔여위험 | 담당 | 관련 |
|---|---|---|---|---|---|---|---|---|
| R-01 | Iceberg 데이터에 ILM expiration 적용 | 중 | 치명 | 🔴 | 규칙 금지, 자동검증, 2인 승인 | 낮음 | 데이터팀 | F-02 |
| R-02 | warm tier 버킷에 ILM 규칙 존재 | 중 | 치명 | 🔴 | 일일 점검 D-03, 분기 감사 | 낮음 | 스토리지팀 | F-04 |
| R-03 | `remove_orphan_files` 오작동 | 낮 | 치명 | 🔴 | 실행 금지 원칙, 절차 통제 | 낮음 | 데이터팀 | F-06 |
| R-04 | delete file 소실로 삭제 데이터 부활 | 중 | 높음 | 🔴 | 프리픽스/크기 필터, 정기 검증 | 중 | 데이터팀 | F-08 |
| R-05 | metadata 전이로 성능 저하 | 높 | 중 | 🟠 | 프리픽스 분리, 성능 모니터링 | 낮음 | 데이터팀 | F-10 |
| R-06 | noncurrent 축적으로 용량 폭증 | 높 | 높음 | 🟠 | noncurrent 만료 규칙, 월간 점검 | 낮음 | 스토리지팀 | F-11 |
| R-07 | warm 장애 시 전이 데이터 조회 불가 | 중 | 높음 | 🟠 | warm HA, hot 보존 확대 | 중 | 스토리지팀 | F-05 |
| R-08 | tier 자격증명 만료 | 중 | 높음 | 🟠 | 만료일 관리, 알람 | 낮음 | 보안팀 | F-04 |
| R-09 | HMS 단일 장애점 | 중 | 높음 | 🟠 | HA, DB 백업, location export | 중 | 데이터팀 | F-07 |
| R-10 | 복제 backlog 누적 (RPO 미달) | 중 | 중 | 🟡 | backlog 알람, 대역폭 관리 | 중 | 스토리지팀 | F-12 |
| R-11 | 삭제 전파로 DR 사본 소실 | 낮 | 높음 | 🟠 | 전파 정책 결정, warm 보존 | 중 | 스토리지팀 | F-13 |
| R-12 | 사이트 복제로 규칙 전파 | 낮 | 치명 | 🟠 | 구성 확인, 일일 점검 | 낮음 | 스토리지팀 | F-14 |
| R-13 | 스캐너 지연으로 정책 예측 불가 | 높 | 낮 | 🟡 | 사이클 모니터링, 데이터셋 관리 | 중 | 스토리지팀 | F-09 |
| R-14 | 전이 객체 미복제로 RPO 갭 | 중 | 높음 | 🟠 | **T-12 실측 후 확정** | **미정** | 스토리지팀 | T-12 |
| R-15 | 운영 데이터 반입 중 원본 오염 | 낮 | 치명 | 🟠 | 읽기 전용 계정, HMS 분리 | 낮음 | 데이터팀 | 07장 §3.3 |
| R-16 | 소파일 다수로 전이 후 성능 붕괴 | 중 | 높음 | 🟠 | 파일 크기 튜닝, compaction | 중 | 데이터팀 | 10장 §1.2 |
| R-17 | 스캐너 가속 설정 방치 | 중 | 중 | 🟡 | 분기 점검 Q-09 | 낮음 | 스토리지팀 | 04장 §6 |
| R-18 | warm 용량 2배 산정 누락 | 중 | 중 | 🟡 | 용량 산정에 반영 | 낮음 | 스토리지팀 | 10장 §6.2 |

### 등급 기준

| 영향도 \ 가능성 | 낮 | 중 | 높 |
|---|---|---|---|
| **치명** (복구 불가 유실) | 🟠 | 🔴 | 🔴 |
| **높음** (서비스 중단/부분 유실) | 🟡 | 🟠 | 🔴 |
| **중** (성능/용량) | 🟡 | 🟡 | 🟠 |
| **낮** (운영 불편) | 🟢 | 🟡 | 🟡 |

### 미해결 항목 (테스트로 확정해야 할 것)

| ID | 미확정 사항 | 확정 방법 | 기한 |
|---|---|---|---|
| R-14 | 전이 객체의 복제 동작 | 08장 T-12 | |
| - | `days=1` 실제 적용 지연 | 08장 T-05 | |
| - | 스캐너 1사이클 실제 소요 | 09장 §3.2 | |
| - | 전이 지연 배수 M | 10장 §2.1 | |
| - | 권장 hot 보존 기간 | 10장 §4.1 | |
| - | warm 다운 시 정확한 실패 범위 | 08장 T-20 | |
| - | 삭제 전파 실제 설정 | 08장 T-13 | |

> ✅ 이 표가 비어 있는 동안은 **리스크 평가가 완료된 것이 아닙니다.** 테스트의 목적이 이 표를 채우는 것입니다.

→ 다음: [12. 부록](../12-appendix/)
