# 08. 테스트 시나리오

> 각 시나리오는 **목적 / 사전조건 / 절차 / 판정 기준(✅) / 실패 시 참조**로 구성됩니다.
> 결과는 §9 결과 기록표에 누적하십시오.

## 1. 테스트 전체 맵

| 그룹 | ID | 시나리오 | 소요 | 선행 |
|---|---|---|---|---|
| **A. 기본 동작** | T-01 | Iceberg 테이블 생성·쓰기·조회 | 30분 | 06장 완료 |
| | T-02 | 파티션 추가 및 증분 적재 | 30분 | T-01 |
| | T-03 | 시간여행 조회 | 20분 | T-02 |
| | T-04 | 스키마 진화 | 20분 | T-01 |
| **B. ILM 전이** | T-05 | 데이터 파일 전이 발생 확인 | 1~3일 (또는 즉시*) | 04장 |
| | T-06 | 전이 후 쿼리 결과 동일성 | 30분 | T-05 |
| | T-07 | metadata 프리픽스 제외 확인 | 20분 | T-05 |
| | T-08 | 전이 객체 재작성(compaction) 동작 | 1시간 | T-05 |
| | T-09 | noncurrent 전이/만료 동작 | 1~7일 | T-05 |
| **C. 복제** | T-10 | 객체 복제 정합성 | 1시간 | 03장 |
| | T-11 | 복제 지연 측정 | 2시간 | T-10 |
| | T-12 | **전이 객체의 복제 동작** 🔍 | 1일 | T-05, T-10 |
| | T-13 | 삭제 전파 동작 | 1시간 | T-10 |
| | T-14 | 복제 중단·재개(resync) | 2시간 | T-10 |
| **D. 유지보수** | T-15 | `rewrite_data_files` (compaction) | 1시간 | T-02 |
| | T-16 | `expire_snapshots` | 1시간 | T-15 |
| | T-17 | `rewrite_manifests` | 30분 | T-15 |
| | T-18 | delete file 생성·병합 (MERGE/DELETE) | 1시간 | T-01 |
| | T-19 | ⚠️ `remove_orphan_files` (제한적) | 2시간 | 11장 F-06 숙지 |
| **E. 장애/복구** | T-20 | warm 클러스터 중단 시 영향 범위 | 2시간 | T-05 |
| | T-21 | 복제 대상 중단 시 backlog 거동 | 2시간 | T-10 |
| | T-22 | HMS 중단 시 영향 | 1시간 | T-01 |
| | T-23 | tier 자격증명 오류 시 거동 | 1시간 | T-05 |
| | T-24 | 동시 커밋 충돌 | 1시간 | T-01 |

\* 07장 §6 방법 B(과거 날짜 전이 규칙) 사용 시 즉시

## 2. 테스트 진행 원칙

| 원칙 | 이유 |
|---|---|
| 소규모 → 대규모 순서 | 원인 분리 가능 |
| 한 번에 하나씩 변경 | 무엇이 원인인지 알 수 있음 |
| 매 시나리오 전후 상태 스냅샷 기록 | 재현·비교 가능 |
| 실패해도 즉시 조치하지 말고 **상태를 먼저 채증** | 원인 분석 자료 확보 |
| 정상 케이스도 반드시 기록 | 기준선 확보 |

### 매 시나리오 전후 채증 스크립트

```bash
#!/usr/bin/env bash
# snapshot-state.sh <label>
L=${1:-state}; T=$(date +%Y%m%d-%H%M%S); D="./evidence/$T-$L"; mkdir -p "$D"
BKT=${BKT:-HOT/warehouse}; TBLP=${TBLP:-ilm_test.db/orders}

mc ls --recursive          "$BKT/$TBLP/"          > "$D/objects.txt"          2>&1
mc ls --versions --recursive "$BKT/$TBLP/"        > "$D/objects-versions.txt" 2>&1
mc du                      "$BKT/$TBLP/"          > "$D/du.txt"               2>&1
mc ilm rule ls             "$BKT"                 > "$D/ilm-rules.txt"        2>&1
mc replicate status        "$BKT"                 > "$D/repl-status.txt"      2>&1
mc ilm tier info           HOT WARM-TIER          > "$D/tier-info.txt"        2>&1
mc admin prometheus metrics HOT node    2>/dev/null | grep -Ei 'scanner|ilm' > "$D/metrics-node.txt"
mc admin prometheus metrics HOT cluster 2>/dev/null | grep -Ei 'replication|ilm|tier' > "$D/metrics-cluster.txt"
mc ls --recursive WARM/warm-tier/  2>/dev/null | wc -l > "$D/warmtier-count.txt"
mc ls --recursive WARM/warehouse/"$TBLP"/ 2>/dev/null | wc -l > "$D/warmrepl-count.txt"
echo "채증: $D"
```

---

## 그룹 A — 기본 동작

### T-01: 테이블 생성·쓰기·조회

**목적** 기준선 확보. 이후 모든 비교의 출발점.

```sql
CREATE DATABASE IF NOT EXISTS hive_prod.ilm_test;

CREATE TABLE hive_prod.ilm_test.orders (
  order_id BIGINT, customer_id STRING, order_ts TIMESTAMP,
  amount DECIMAL(18,2), region STRING
) USING iceberg
PARTITIONED BY (days(order_ts))
TBLPROPERTIES (
  'format-version'='2',
  'write.target-file-size-bytes'='536870912',
  'write.metadata.delete-after-commit.enabled'='true',
  'write.metadata.previous-versions-max'='20'
);

INSERT INTO hive_prod.ilm_test.orders SELECT * FROM prod.db.orders WHERE order_ts >= timestamp'2026-08-01' AND order_ts < timestamp'2026-08-02';

SELECT count(*) FROM hive_prod.ilm_test.orders;
SELECT count(*) AS files, sum(file_size_in_bytes)/1e9 AS gb, avg(file_size_in_bytes)/1e6 AS avg_mb
FROM hive_prod.ilm_test.orders.files;
```

| ✅ 판정 | 기준 |
|---|---|
| 커밋 성공 | 예외 없음 |
| 행 수 | 원본 대비 일치 |
| 파일 경로 | `s3://warehouse/ilm_test.db/orders/...` |
| 평균 파일 크기 | 05장 §8 "안전" 범위 |

**기준선 기록** (이후 비교용)

| 항목 | 값 |
|---|---|
| 행 수 | |
| 데이터 파일 수 | |
| 총 크기(GB) | |
| 평균 파일 크기(MB) | |
| 스냅샷 수 | |
| `SELECT count(*)` 소요(초) | |
| 단일 파티션 조회 소요(초) | |

실패 시 → [06장 §5](../06-spark-setup/)

### T-02: 증분 적재

```python
for i in range(1, 15):
    spark.sql(f"""INSERT INTO hive_prod.ilm_test.orders
                  SELECT * FROM prod.db.orders
                  WHERE order_ts >= timestamp'2026-08-{i:02d}' AND order_ts < timestamp'2026-08-{i+1:02d}'""")
spark.sql("SELECT snapshot_id, committed_at, operation, summary FROM hive_prod.ilm_test.orders.snapshots").show(50, False)
```

| ✅ 판정 | 기준 |
|---|---|
| 스냅샷 수 | 14개 이상 |
| 각 커밋 성공 | 예외 없음 |
| 파티션 수 | 14개 |

### T-03: 시간여행

```sql
SELECT snapshot_id, committed_at FROM hive_prod.ilm_test.orders.snapshots ORDER BY committed_at;
SELECT count(*) FROM hive_prod.ilm_test.orders VERSION AS OF <초기_snapshot_id>;
SELECT count(*) FROM hive_prod.ilm_test.orders TIMESTAMP AS OF '2026-08-05 00:00:00';
```

| ✅ 판정 | 기준 |
|---|---|
| 과거 스냅샷 조회 성공 | 예외 없음 |
| 행 수 | 해당 시점 누적값과 일치 |

### T-04: 스키마 진화

```sql
ALTER TABLE hive_prod.ilm_test.orders ADD COLUMN channel STRING;
ALTER TABLE hive_prod.ilm_test.orders RENAME COLUMN region TO region_code;
INSERT INTO hive_prod.ilm_test.orders VALUES (999, 'c', current_timestamp(), 100.00, 'KR', 'web');
SELECT * FROM hive_prod.ilm_test.orders WHERE order_id = 999;
SELECT count(*) FROM hive_prod.ilm_test.orders;   -- 구 파일도 정상 조회
```

| ✅ 판정 | 기준 |
|---|---|
| 구 파일 조회 시 새 컬럼 = NULL | 정상 |
| 전체 행 수 유지 | 정상 |

---

## 그룹 B — ILM 전이

### T-05: 데이터 파일 전이 발생 ★

**사전조건** 04장 규칙 적용 완료. 가속이 필요하면 07장 §6 방법 B.

```bash
./snapshot-state.sh before-transition

# 대상 객체 목록 확보
mc ls --recursive HOT/warehouse/ilm_test.db/orders/data/ | awk '{print $NF}' > /tmp/data-objs.txt
wc -l /tmp/data-objs.txt

# 전이 전 상태 (샘플 5개)
head -5 /tmp/data-objs.txt | while read -r o; do
  echo "--- $o"; mc stat "HOT/warehouse/ilm_test.db/orders/data/$o" | grep -Ei 'name|size|tier'
done

# 진행 관찰 (주기적)
watch -n 300 'mc admin prometheus metrics HOT node | grep -E "ilm_transition|scanner_bucket_scans_finished"'
```

전이 후:

```bash
./snapshot-state.sh after-transition

# 전이된 객체 수 집계
TOTAL=0; TIERED=0
while read -r o; do
  TOTAL=$((TOTAL+1))
  if mc stat "HOT/warehouse/ilm_test.db/orders/data/$o" 2>/dev/null | grep -qi 'WARM-TIER'; then
    TIERED=$((TIERED+1))
  fi
done < /tmp/data-objs.txt
echo "전이: $TIERED / $TOTAL"

mc ilm tier info HOT WARM-TIER
mc du HOT/warehouse/ilm_test.db/orders/     # 사용량 감소 (스캐너 집계 지연 있음)
mc ls --recursive WARM/warm-tier/ | wc -l
```

| ✅ 판정 | 기준 |
|---|---|
| 전이 비율 | 대상 객체의 상당수가 `Tier: WARM-TIER` |
| `mc ls` 결과 | **변화 없음** (객체는 그대로 보임) — 02장 §1 |
| warm-tier 객체 수 | 증가 |
| tier info 통계 | 객체 수·용량 증가 |

**⚠️ 전이가 0건인 경우 진단 순서**

| # | 확인 | 명령 |
|---|---|---|
| 1 | 규칙이 실제 등록됐는가 | `mc ilm rule ls HOT/warehouse` |
| 2 | 프리픽스가 실제 경로와 일치하는가 | `mc ls --recursive` 결과와 대조 ★ 가장 흔한 원인 |
| 3 | 객체 나이가 충분한가 | `mc ls --recursive` 의 날짜 |
| 4 | 스캐너가 도는가 | `scanner_bucket_scans_finished` 증가 여부 |
| 5 | 전이 작업이 적체됐는가 | `ilm_transition_pending_tasks` |
| 6 | tier 접근이 되는가 | `mc ilm tier info HOT WARM-TIER` |
| 7 | 에러 로그 | `mc admin logs HOT --last 200` 🔍 |

실패 시 → [09장 §3](../09-operations/), [11장 F-09](../11-failure-and-risk/)

### T-06: 전이 후 쿼리 결과 동일성 ★

```sql
-- T-01에서 기록한 값과 비교
SELECT count(*) FROM hive_prod.ilm_test.orders;
SELECT region_code, count(*), sum(amount) FROM hive_prod.ilm_test.orders GROUP BY region_code ORDER BY region_code;
SELECT count(*) FROM hive_prod.ilm_test.orders WHERE order_ts >= timestamp'2026-08-01' AND order_ts < timestamp'2026-08-02';
```

```python
import time
def timed(sql, n=3):
    ts=[]
    for _ in range(n):
        t=time.time(); spark.sql(sql).collect(); ts.append(time.time()-t)
    return min(ts), sum(ts)/len(ts), max(ts)

for q in ["SELECT count(*) FROM hive_prod.ilm_test.orders",
          "SELECT region_code, sum(amount) FROM hive_prod.ilm_test.orders GROUP BY region_code",
          "SELECT * FROM hive_prod.ilm_test.orders WHERE order_ts >= timestamp'2026-08-01' AND order_ts < timestamp'2026-08-02' LIMIT 1000"]:
    print(timed(q), q[:60])
```

| ✅ 판정 | 기준 |
|---|---|
| 결과 정확성 | T-01 기준선과 **완전 일치** (필수) |
| 예외 발생 | 없음 |
| 지연 | 증가함 (정상). 증가율은 10장에서 평가 |

⚠️ **결과가 다르면 즉시 중단하고 채증**하십시오. 데이터 유실 또는 delete file 소실 가능성 → [11장 F-02/F-08](../11-failure-and-risk/)

### T-07: metadata 제외 확인 ★

```bash
# metadata 객체가 전이되지 않았는지 확인
mc ls --recursive HOT/warehouse/ilm_test.db/orders/metadata/ | awk '{print $NF}' | while read -r o; do
  if mc stat "HOT/warehouse/ilm_test.db/orders/metadata/$o" | grep -qi 'tier'; then
    echo "🔴 전이됨: $o"
  fi
done
echo "검사 완료"
```

| ✅ 판정 | 기준 |
|---|---|
| metadata 객체 전이 | **0건** (필수) |
| 플래닝 시간 | T-01 대비 큰 증가 없음 |

실패 시 → [04장 §3](../04-ilm-policy-design/) 규칙 프리픽스 수정

### T-08: 전이 상태에서 compaction

```sql
CALL hive_prod.system.rewrite_data_files(
  table => 'ilm_test.orders',
  options => map('min-input-files','5','target-file-size-bytes','536870912')
);
SELECT count(*) FROM hive_prod.ilm_test.orders;
```

| ✅ 판정 | 기준 |
|---|---|
| compaction 성공 | 예외 없음 |
| 행 수 | 변화 없음 |
| 소요 시간 | 비전이 대비 증가 (전이 파일을 warm에서 읽어야 함) |
| 신규 파일 | hot 로컬에 생성 (전이 대상 아님, 나이 리셋) |

⚠️ compaction은 **전이된 파일을 다시 hot으로 끌어올려 읽습니다.** 대량 실행 시 hot↔warm 트래픽이 폭증합니다. 야간 실행 권장.

### T-09: noncurrent 전이/만료

```bash
mc ls --versions --recursive HOT/warehouse/ilm_test.db/orders/data/ | wc -l    # 전체 버전 수
mc ls --versions --recursive HOT/warehouse/ilm_test.db/orders/data/ | grep -c "DELETEMARKER"  # 🔍 표기 확인
mc du HOT/warehouse/ilm_test.db/orders/
```

노후화 대기 후 재측정.

| ✅ 판정 | 기준 |
|---|---|
| noncurrent 버전 수 | 만료 기간 경과 후 **감소** |
| 사용량 | 감소 |
| current 버전 | **변화 없음** (필수) 🔴 |
| 테이블 조회 | 정상 |

⚠️ current 버전이 줄었다면 규칙 오설정입니다. 즉시 중단 → [04장 §3.4](../04-ilm-policy-design/)

---

## 그룹 C — 복제

### T-10: 복제 정합성

```bash
# 객체 수 비교
H=$(mc ls --recursive HOT/warehouse/ilm_test.db/orders/  | wc -l)
W=$(mc ls --recursive WARM/warehouse/ilm_test.db/orders/ | wc -l)
echo "hot=$H warm=$W"

# 목록 차집합
mc ls --recursive HOT/warehouse/ilm_test.db/orders/  | awk '{print $NF}' | sort > /tmp/h.txt
mc ls --recursive WARM/warehouse/ilm_test.db/orders/ | awk '{print $NF}' | sort > /tmp/w.txt
comm -23 /tmp/h.txt /tmp/w.txt | head -20    # hot에만 있는 것 (미복제)
comm -13 /tmp/h.txt /tmp/w.txt | head -20    # warm에만 있는 것 (잔여/고아)

# ETag 비교 (샘플)
for o in $(head -10 /tmp/h.txt); do
  eh=$(mc stat --json "HOT/warehouse/ilm_test.db/orders/$o"  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("etag"))')
  ew=$(mc stat --json "WARM/warehouse/ilm_test.db/orders/$o" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("etag"))' 2>/dev/null)
  [ "$eh" = "$ew" ] && echo "OK  $o" || echo "DIFF $o ($eh vs $ew)"
done

# 복제 상태
mc replicate status HOT/warehouse
```

| ✅ 판정 | 기준 |
|---|---|
| 객체 수 | 지연 감안 후 일치 |
| 미복제 목록 | 안정 상태에서 0건 |
| ETag | 샘플 전부 일치 |
| 복제 상태 | FAILED 0건 |

### T-11: 복제 지연 측정

```bash
#!/usr/bin/env bash
# measure-repl-lag.sh
for i in $(seq 1 20); do
  F=/tmp/lag-$i.bin
  head -c $((10*1024*1024)) /dev/urandom > "$F"     # 10MB
  T0=$(date +%s.%N)
  mc cp "$F" HOT/warehouse/_lagtest/obj-$i.bin >/dev/null 2>&1
  while true; do
    if mc stat WARM/warehouse/_lagtest/obj-$i.bin >/dev/null 2>&1; then
      T1=$(date +%s.%N); echo "$i $(echo "$T1-$T0" | bc)"; break
    fi
    sleep 1
    NOW=$(date +%s.%N)
    if (( $(echo "$NOW-$T0 > 600" | bc) )); then echo "$i TIMEOUT"; break; fi
  done
  rm -f "$F"
done
mc rm --recursive --force HOT/warehouse/_lagtest/
```

| ✅ 판정 | 기준 (환경별 설정) |
|---|---|
| p50 지연 | 목표치 이내 |
| p95 지연 | 목표치 이내 |
| 타임아웃 | 0건 |

측정값을 RPO 목표 근거로 기록하십시오. → [09장 §4](../09-operations/)

### T-12: 전이 객체의 복제 동작 🔍 ★

**이 항목은 문서로 답할 수 없고 반드시 실측해야 합니다.** 버전/구현 의존입니다.

```bash
# 1) 전이된 객체 하나 선택
OBJ=$(mc ls --recursive HOT/warehouse/ilm_test.db/orders/data/ | awk '{print $NF}' | while read -r o; do
        mc stat "HOT/warehouse/ilm_test.db/orders/data/$o" | grep -qi WARM-TIER && { echo "$o"; break; }
      done)
echo "대상: $OBJ"

# 2) 복제 상태 확인
mc stat --json "HOT/warehouse/ilm_test.db/orders/data/$OBJ" | python3 -m json.tool

# 3) warm 복제 버킷에 존재하는가
mc stat "WARM/warehouse/ilm_test.db/orders/data/$OBJ" || echo "복제본 없음"

# 4) warm 복제본이 실데이터인가 stub인가
mc stat "WARM/warehouse/ilm_test.db/orders/data/$OBJ" | grep -i tier

# 5) warm-tier 쪽 용량
mc ls --recursive WARM/warm-tier/ | wc -l
mc du WARM/warm-tier/
mc du WARM/warehouse/
```

**기록해야 할 결과 (4가지 중 어느 쪽인가)**

| 관측 결과 | 의미 | 함의 |
|---|---|---|
| (a) 전이 전에 복제 완료됨 | 복제가 먼저 → 정상 | warm에 사본 2벌 (복제+tier) → 용량 2× |
| (b) 전이 후 복제가 hot의 fetch를 통해 진행 | 복제 시 warm→hot→warm 왕복 | 트래픽 증폭 ⚠️ |
| (c) 전이 객체는 복제되지 않음 | DR 사본 없음 | 🔴 **RPO 갭** — 반드시 문서화 |
| (d) 복제 상태가 PENDING으로 정체 | 복제 실패 누적 | 🔴 조치 필요 |

| ✅ 판정 | 기준 |
|---|---|
| 결과가 (a)~(d) 중 무엇인지 명확히 기록 | 필수 |
| (c)/(d)이면 리스크 등록 | 11장 리스크 레지스터 반영 |

### T-13: 삭제 전파

```bash
mc cp /tmp/del-test.txt HOT/warehouse/_deltest/x.txt
sleep 60
mc ls WARM/warehouse/_deltest/           # 존재 확인

mc rm HOT/warehouse/_deltest/x.txt       # delete marker 생성
sleep 60

mc ls --versions HOT/warehouse/_deltest/
mc ls --versions WARM/warehouse/_deltest/    # 전파 여부 확인
```

| 설정 | 기대 결과 |
|---|---|
| `delete-marker` 전파 ON | warm에도 delete marker |
| 전파 OFF | warm에는 객체가 그대로 남음 |

| ✅ 판정 | 기준 |
|---|---|
| 실제 동작이 설정과 일치 | 필수 |
| 결과를 DR 절차에 반영 | [11장 F-13](../11-failure-and-risk/) |

### T-14: 복제 중단·재개

```bash
# 1) 복제 일시 중지 🔍 (명령은 버전 확인)
mc replicate update HOT/warehouse --id <RULE_ID> --state disable

# 2) 데이터 적재 (backlog 축적)
#    Spark INSERT 실행

# 3) backlog 관측
mc replicate status HOT/warehouse
mc admin prometheus metrics HOT cluster | grep -i replication

# 4) 재개
mc replicate update HOT/warehouse --id <RULE_ID> --state enable

# 5) 해소 시간 측정
watch -n 30 'mc replicate status HOT/warehouse'

# 6) 필요 시 resync
mc replicate resync start  HOT/warehouse --remote-bucket <ARN>
mc replicate resync status HOT/warehouse --remote-bucket <ARN>
```

| ✅ 판정 | 기준 |
|---|---|
| 재개 후 backlog 해소 | 전부 복제됨 |
| 해소 소요 시간 | 기록 (RTO 산정 근거) |
| resync 동작 확인 | 정상 |
| 데이터 누락 | 0건 (T-10 재실행으로 확인) |

---

## 그룹 D — 유지보수

### T-15: rewrite_data_files (compaction)

```sql
-- 전
SELECT count(*) files, avg(file_size_in_bytes)/1e6 avg_mb FROM hive_prod.ilm_test.orders.files;

CALL hive_prod.system.rewrite_data_files(
  table => 'ilm_test.orders',
  strategy => 'binpack',
  options => map('min-input-files','5','target-file-size-bytes','536870912','max-concurrent-file-group-rewrites','4')
);

-- 후
SELECT count(*) files, avg(file_size_in_bytes)/1e6 avg_mb FROM hive_prod.ilm_test.orders.files;
SELECT count(*) FROM hive_prod.ilm_test.orders;
```

```bash
# S3 객체 수는 오히려 늘어남 (noncurrent 때문) — 확인
mc ls --recursive          HOT/warehouse/ilm_test.db/orders/data/ | wc -l
mc ls --versions --recursive HOT/warehouse/ilm_test.db/orders/data/ | wc -l
```

| ✅ 판정 | 기준 |
|---|---|
| 논리 파일 수 | 감소 |
| 평균 파일 크기 | 증가 |
| 행 수 | 불변 |
| **S3 총 버전 수** | 증가 (예상된 동작) — 02장 §2.2 |

### T-16: expire_snapshots

```sql
SELECT count(*) FROM hive_prod.ilm_test.orders.snapshots;

CALL hive_prod.system.expire_snapshots(
  table => 'ilm_test.orders',
  older_than => TIMESTAMP '2026-08-20 00:00:00',
  retain_last => 5
);

SELECT count(*) FROM hive_prod.ilm_test.orders.snapshots;
SELECT count(*) FROM hive_prod.ilm_test.orders;
```

| ✅ 판정 | 기준 |
|---|---|
| 스냅샷 수 | 감소 |
| 행 수 | 불변 |
| 만료된 스냅샷 시간여행 | 실패 (정상) |
| S3 사용량 | **즉시 감소하지 않음** (버저닝) — 정상 |
| noncurrent 만료 후 | 감소 |

### T-17: rewrite_manifests

```sql
SELECT count(*) FROM hive_prod.ilm_test.orders.manifests;
CALL hive_prod.system.rewrite_manifests(table => 'ilm_test.orders');
SELECT count(*) FROM hive_prod.ilm_test.orders.manifests;
```

| ✅ 판정 | 기준 |
|---|---|
| manifest 수 | 감소 |
| 플래닝 시간 | 개선 |

### T-18: delete file

```sql
DELETE FROM hive_prod.ilm_test.orders WHERE order_id % 1000 = 0;
SELECT count(*) FROM hive_prod.ilm_test.orders.delete_files;
SELECT count(*) FROM hive_prod.ilm_test.orders;

CALL hive_prod.system.rewrite_position_delete_files(table => 'ilm_test.orders');
SELECT count(*) FROM hive_prod.ilm_test.orders.delete_files;
```

```bash
# delete file 크기 확인 — 소파일 다수 여부
mc ls --recursive HOT/warehouse/ilm_test.db/orders/data/ | awk '$4 ~ /delete/ {print}' | head
```

| ✅ 판정 | 기준 |
|---|---|
| 삭제 반영 | 행 수 감소 |
| delete file 생성 | 확인 |
| 병합 후 감소 | 확인 |
| 🔴 **delete file이 ILM 대상인지 확인** | 만료 대상이면 즉시 규칙 수정 |

### T-19: ⚠️ remove_orphan_files (제한적)

> 🔴 **[11장 F-06](../11-failure-and-risk/)을 먼저 읽으십시오.** 이 시나리오는 기본적으로 **실행하지 않는 것이 정답**입니다. 테스트 환경에서 거동만 확인합니다.

```sql
-- 반드시 dry-run 먼저 🔍 (파라미터 지원 여부 확인)
CALL hive_prod.system.remove_orphan_files(
  table => 'ilm_test.orders',
  older_than => TIMESTAMP '2026-08-01 00:00:00',   -- 충분히 과거로
  dry_run => true
);
```

| 사전 필수 조건 | 확인 |
|---|---|
| 해당 테이블에 대한 **모든 쓰기 작업 중지** | ☐ |
| 복제 backlog 0 | ☐ |
| dry_run 결과 목록을 사람이 검토 | ☐ |
| `older_than` 이 현재보다 최소 7일 이전 | ☐ |
| 테스트 테이블임 (운영 아님) | ☐ |

| ✅ 판정 | 기준 |
|---|---|
| dry_run 목록에 live 파일 없음 | `tbl.all_data_files`와 대조 |
| 실행 후 테이블 정상 | 조회 성공 |

---

## 그룹 E — 장애/복구

### T-20: warm 클러스터 중단 ★

⚠️ 테스트 환경에서만. 운영에서는 절대 금지.

```bash
# 중단 전 채증
./snapshot-state.sh before-warm-down

# warm 중단 (방화벽 차단 또는 서비스 정지)
# 예: hot 노드에서 warm 엔드포인트 차단
```

```sql
-- 1) 전이되지 않은 최신 파티션 조회
SELECT count(*) FROM hive_prod.ilm_test.orders WHERE order_ts >= current_date() - 1;

-- 2) 전이된 구 파티션 조회
SELECT count(*) FROM hive_prod.ilm_test.orders WHERE order_ts < timestamp'2026-08-05';

-- 3) 전체 스캔
SELECT count(*) FROM hive_prod.ilm_test.orders;

-- 4) 신규 쓰기
INSERT INTO hive_prod.ilm_test.orders VALUES (777, 'x', current_timestamp(), 1.00, 'KR', 'web');

-- 5) 메타데이터 조회
SELECT * FROM hive_prod.ilm_test.orders.snapshots;
```

**결과 기록표** (이것이 이 테스트의 산출물)

| 작업 | 예상 | 실측 | 오류 메시지 |
|---|---|---|---|
| 1) 미전이 파티션 조회 | ✅ 성공 | | |
| 2) 전이 파티션 조회 | ❌ 실패 | | |
| 3) 전체 스캔 | ❌ 실패 | | |
| 4) 신규 쓰기 | ✅ 성공 | | |
| 5) 메타데이터 조회 | ✅ 성공 (metadata 제외 시) | | |
| 6) 복제 | 지연/실패 | | |

```bash
# 복구 후
./snapshot-state.sh after-warm-recovery
mc replicate status HOT/warehouse
```

| ✅ 판정 | 기준 |
|---|---|
| 실패 범위가 예상과 일치 | 필수 |
| 복구 후 자동 정상화 | 재시도로 해소 |
| 데이터 유실 | 0건 |
| 오류 메시지 문서화 | 12장 FAQ에 반영 |

### T-21: 복제 대상 중단 시 backlog

```bash
# warm 차단 상태에서 지속 쓰기
# 관측
watch -n 60 'mc replicate status HOT/warehouse; mc admin prometheus metrics HOT cluster | grep -i replication_'
```

| ✅ 판정 | 기준 |
|---|---|
| hot 쓰기 계속 성공 | 비동기이므로 정상 |
| backlog 증가 관측 | 메트릭 확인 |
| 복구 후 자동 해소 | 시간 기록 |
| 큐 한계 도달 시 거동 | 🔍 기록 |

### T-22: HMS 중단

```bash
kubectl -n data scale deploy hms --replicas=0
```

| 작업 | 예상 | 실측 |
|---|---|---|
| 테이블 조회 | ❌ 실패 | |
| 신규 쓰기 | ❌ 실패 | |
| 이미 실행 중인 잡 | 부분 성공 가능 | |
| `mc ls` (S3 직접) | ✅ 성공 | |

```bash
kubectl -n data scale deploy hms --replicas=1
```

| ✅ 판정 | 기준 |
|---|---|
| 복구 후 정상 | 즉시 |
| 데이터 유실 | 0건 |
| HMS SPOF 확인 | HA 필요성 근거로 기록 |

### T-23: tier 자격증명 오류

```bash
mc ilm tier update HOT WARM-TIER --access-key wrong --secret-key wrong    # 🔍
```

| 작업 | 예상 | 실측 |
|---|---|---|
| 전이 객체 조회 | ❌ 실패 | |
| 미전이 객체 조회 | ✅ 성공 | |
| 신규 전이 | ❌ 실패 (데이터는 안전) | |

```bash
mc ilm tier update HOT WARM-TIER --access-key svc-tier --secret-key '<SECRET>'    # 원복
```

| ✅ 판정 | 기준 |
|---|---|
| 복구 후 즉시 정상 | 필수 |
| 데이터 유실 | 0건 |
| 자격증명 만료 알람 필요성 확인 | 09장 반영 |

### T-24: 동시 커밋 충돌

```python
from concurrent.futures import ThreadPoolExecutor
def w(i):
    try:
        spark.sql(f"INSERT INTO hive_prod.ilm_test.orders VALUES ({9000+i}, 'c{i}', current_timestamp(), {i}.00, 'KR', 'web')")
        return f"{i}: OK"
    except Exception as e:
        return f"{i}: FAIL {type(e).__name__}"
with ThreadPoolExecutor(8) as ex:
    for r in ex.map(w, range(8)): print(r)
spark.sql("SELECT count(*) FROM hive_prod.ilm_test.orders WHERE order_id >= 9000").show()
```

| ✅ 판정 | 기준 |
|---|---|
| 재시도로 전부 성공 | 커밋 재시도 설정 적정 |
| 최종 행 수 | 8건 (유실·중복 없음) |
| 실패 발생 시 | 재시도 설정 상향 → 06장 §5 |

---

## 9. 테스트 결과 기록표

| ID | 시나리오 | 실행일 | 담당 | 결과 | 소요 | 비고/증적 경로 |
|---|---|---|---|---|---|---|
| T-01 | 테이블 생성·쓰기·조회 | | | ☐P ☐F | | |
| T-02 | 증분 적재 | | | ☐P ☐F | | |
| T-03 | 시간여행 | | | ☐P ☐F | | |
| T-04 | 스키마 진화 | | | ☐P ☐F | | |
| T-05 | 전이 발생 | | | ☐P ☐F | | |
| T-06 | 전이 후 결과 동일성 | | | ☐P ☐F | | |
| T-07 | metadata 제외 | | | ☐P ☐F | | |
| T-08 | 전이 상태 compaction | | | ☐P ☐F | | |
| T-09 | noncurrent 정책 | | | ☐P ☐F | | |
| T-10 | 복제 정합성 | | | ☐P ☐F | | |
| T-11 | 복제 지연 | | | ☐P ☐F | | |
| T-12 | 전이 객체 복제 🔍 | | | ☐P ☐F | | 결과 (a)/(b)/(c)/(d): |
| T-13 | 삭제 전파 | | | ☐P ☐F | | |
| T-14 | 복제 중단·재개 | | | ☐P ☐F | | |
| T-15 | compaction | | | ☐P ☐F | | |
| T-16 | expire_snapshots | | | ☐P ☐F | | |
| T-17 | rewrite_manifests | | | ☐P ☐F | | |
| T-18 | delete file | | | ☐P ☐F | | |
| T-19 | remove_orphan_files | | | ☐P ☐F ☐N/A | | |
| T-20 | warm 중단 | | | ☐P ☐F | | |
| T-21 | 복제 대상 중단 | | | ☐P ☐F | | |
| T-22 | HMS 중단 | | | ☐P ☐F | | |
| T-23 | tier 자격증명 오류 | | | ☐P ☐F | | |
| T-24 | 동시 커밋 | | | ☐P ☐F | | |

## 10. 테스트 일정 (예시)

| 주차 | 작업 | 산출물 |
|---|---|---|
| 1주차 | 03장 구성 진단·백업, 06장 Spark 검증, 07장 소규모 반입 | 진단 보고서, 연결 검증 통과 |
| 2주차 | T-01~T-04 (기본), 04장 규칙 적용, T-05 가속 검증 | 기준선 기록 |
| 3주차 | T-05~T-09 (전이, 실제 1일 대기 포함) | 전이 검증 결과 |
| 4주차 | T-10~T-14 (복제) | 복제 지연 수치, T-12 결론 |
| 5주차 | T-15~T-19 (유지보수) | 유지보수 안전성 확인 |
| 6주차 | T-20~T-24 (장애), 10장 성능 측정 | 장애 영향 매트릭스, 성능 보고서 |
| 7주차 | 실 규모 확장 검증, 11장 리스크 확정 | 최종 보고서, 운영 이행안 |

→ 다음: [09. 운영 절차](../09-operations/)
