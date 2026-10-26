# 10. 성능 — 측정, 해석, 튜닝

## 1. 이 환경의 성능 모델

```
쿼리 총 소요 = 플래닝 + 실행
             = (metadata 읽기 시간) + (data 읽기 시간 + 계산 시간)

전이(warm)가 개입하면:
  metadata 전이 → 플래닝 시간 × (warm RTT 배수)        ← 모든 쿼리에 상수 부과 🔴
  data 전이     → 실행 시간의 I/O 부분 × (warm RTT 배수) ← 스캔량에 비례 🟡
```

### 1.1 핵심 변수

| 변수 | 기호 | 영향 | 측정 방법 |
|---|---|---|---|
| hot 로컬 GET 지연 | L_hot | 기준 | §2.1 |
| warm 경유 GET 지연 | L_warm | 전이 비용 | §2.1 |
| 지연 배수 | **M = L_warm / L_hot** | **가장 중요한 수치** | §2.1 |
| 스캔 파일 수 | F | 요청 수 결정 | `tbl.files` |
| 파일당 요청 수 | R (≈ 2~3 + 컬럼수) | 증폭 계수 | Parquet 구조 |
| 병렬도 | P (executor 코어 총합) | 지연 은닉 | Spark 설정 |

```
전이 데이터 읽기 시간 ≈ (F × R × L_warm) / P
비전이 읽기 시간     ≈ (F × R × L_hot)  / P
증가분              ≈ (F × R × (L_warm - L_hot)) / P
```

> **이 식이 말하는 것: 파일 수(F)와 병렬도(P)가 전이 성능을 지배합니다.** 파일이 작고 많을수록(F↑) 나쁘고, 병렬도가 높을수록(P↑) 지연이 은닉됩니다.

### 1.2 왜 "작은 파일"이 전이 환경에서 치명적인가

| 시나리오 | 파일 수 | 파일당 요청 | 총 요청 | L_warm=50ms, P=32 기준 소요 |
|---|---|---|---|---|
| 512MB 파일 × 20개 (10GB) | 20 | 5 | 100 | 100×50ms/32 ≈ **0.16초** |
| 8MB 파일 × 1,280개 (10GB) | 1,280 | 5 | 6,400 | 6400×50ms/32 ≈ **10초** |
| 1MB 파일 × 10,240개 (10GB) | 10,240 | 5 | 51,200 | 51200×50ms/32 ≈ **80초** |

**같은 10GB인데 500배 차이**가 납니다. hot 로컬(L=2ms)에서는 이 차이가 훨씬 작아 문제가 드러나지 않다가, **전이 후에 갑자기 터집니다.**

> ✅ 그래서 [05장 §5](../05-iceberg-on-s3/)의 파일 크기 튜닝이 이 환경의 최우선 과제입니다.

## 2. 기준선 측정

### 2.1 객체 스토리지 계층 지연 측정

```bash
#!/usr/bin/env bash
# measure-object-latency.sh — hot 로컬 vs 전이 객체 GET 지연
BKT=HOT/warehouse/ilm_test.db/orders/data

pick_local() {  # 전이 안 된 객체
  mc ls --recursive "$BKT/" | awk '{print $NF}' | while read -r o; do
    mc stat "$BKT/$o" 2>/dev/null | grep -qi 'WARM-TIER' || { echo "$o"; return; }
  done | head -1
}
pick_tiered() { # 전이된 객체
  mc ls --recursive "$BKT/" | awk '{print $NF}' | while read -r o; do
    mc stat "$BKT/$o" 2>/dev/null | grep -qi 'WARM-TIER' && { echo "$o"; return; }
  done | head -1
}

bench() {  # $1=label $2=object
  local n=10 total=0
  for i in $(seq 1 $n); do
    s=$(date +%s%N)
    mc cat "$BKT/$2" > /dev/null 2>&1
    e=$(date +%s%N)
    ms=$(( (e-s)/1000000 )); total=$((total+ms)); echo "  $1 #$i: ${ms}ms"
  done
  echo "$1 평균: $((total/n))ms"
}

L=$(pick_local);  echo "로컬 객체: $L";  [ -n "$L" ] && bench "LOCAL " "$L"
T=$(pick_tiered); echo "전이 객체: $T";  [ -n "$T" ] && bench "TIERED" "$T"
```

**결과 기록**

| 항목 | 값 | 비고 |
|---|---|---|
| 객체 크기 | | 동일 크기로 비교할 것 |
| L_hot (평균) | ms | |
| L_warm (평균) | ms | |
| **M (배수)** | × | **가장 중요** |
| hot↔warm 네트워크 RTT | ms | `ping` |

⚠️ `mc cat`은 전체 객체를 받으므로 **크기가 큰 파일은 대역폭 측정**이 되고, 작은 파일은 **지연 측정**이 됩니다. 소파일과 대파일 둘 다 측정하십시오.

```bash
# range GET 지연 측정 (Parquet footer 읽기 패턴 모사)
curl -s -o /dev/null -w "%{time_total}\n" \
  -r -8 -H "..." "https://hot-s3.example.internal/warehouse/.../file.parquet"
```

### 2.2 쿼리 계층 기준선

```python
# bench-queries.py
import time, json
from pyspark.sql import SparkSession
spark = SparkSession.builder.appName("bench").getOrCreate()
T = "hive_prod.ilm_test.orders"

QUERIES = {
  "q1_count_all":        f"SELECT count(*) FROM {T}",
  "q2_recent_partition": f"SELECT count(*) FROM {T} WHERE order_ts >= current_date() - 1",
  "q3_old_partition":    f"SELECT count(*) FROM {T} WHERE order_ts < timestamp'2026-08-05'",
  "q4_full_scan_agg":    f"SELECT region_code, count(*), sum(amount) FROM {T} GROUP BY region_code",
  "q5_point_lookup":     f"SELECT * FROM {T} WHERE order_id = 12345",
  "q6_planning_only":    f"SELECT count(*) FROM {T}.files",
  "q7_wide_scan":        f"SELECT * FROM {T} WHERE amount > 1000 LIMIT 100000",
}

def run(sql, warmup=1, n=3):
    for _ in range(warmup): spark.sql(sql).collect()
    ts=[]
    for _ in range(n):
        t=time.time(); spark.sql(sql).collect(); ts.append(time.time()-t)
    return {"min":round(min(ts),3), "avg":round(sum(ts)/len(ts),3), "max":round(max(ts),3)}

res = {k: run(v) for k,v in QUERIES.items()}
print(json.dumps(res, indent=2))
with open(f"bench-{int(time.time())}.json","w") as f: json.dump(res,f,indent=2)
```

⚠️ **`warmup` 유무를 명확히 하십시오.** 카탈로그 캐시(`cache-enabled`)가 켜져 있으면 2회차부터 플래닝이 빨라집니다. 전이 영향을 보려면 **warmup=0**으로도 측정해 비교하십시오.

### 2.3 기준선 기록표

| 쿼리 | 전이 전 (avg s) | 전이 후 (avg s) | 배수 | 판정 |
|---|---|---|---|---|
| q1 count(*) | | | | metadata만 읽음 → 배수 ≈1 이어야 정상 ★ |
| q2 최근 파티션 | | | | 전이 안 됨 → 배수 ≈1 |
| q3 구 파티션 | | | | 전이됨 → 배수 = M 근처 |
| q4 전체 집계 | | | | 전이 비율에 비례 |
| q5 포인트 조회 | | | | |
| q6 플래닝만 | | | | **배수 >1.5면 metadata 전이 의심** 🔴 |
| q7 넓은 스캔 | | | | |

> ✅ **q1과 q6의 배수가 1에 가까워야 정상입니다.** 이 둘이 느려졌다면 metadata가 전이된 것입니다 → [04장 §3](../04-ilm-policy-design/) 규칙 확인.

## 3. Parquet 읽기 패턴과 전이 비용

### 3.1 파일 1개를 읽을 때 실제 요청

```
1. GET range [-8]              → footer 길이 + 매직넘버
2. GET range [size-8-N, size]  → footer (스키마, row group 메타)
3. GET range [offset, len] × C → 필요한 컬럼 청크 (C = 읽는 컬럼 수 × row group 수)
```

| 상황 | 요청 수 |
|---|---|
| count(*) (메타만) | 2 (footer만) — 실제로는 Iceberg 통계로 생략 가능 |
| 컬럼 1개 조회 | 2 + row group 수 |
| 컬럼 10개 조회 | 2 + 10 × row group 수 |
| SELECT * | 2 + 전체 컬럼 × row group 수 |

### 3.2 튜닝 포인트

| 설정 | 효과 | 권장 |
|---|---|---|
| `write.parquet.row-group-size-bytes` ↑ | row group 수 ↓ → 요청 수 ↓ | 128~256MB |
| `write.target-file-size-bytes` ↑ | 파일 수 ↓ | 512MB~1GB |
| 컬럼 프루닝 (SELECT 명시) | 읽는 컬럼 ↓ | `SELECT *` 지양 |
| 파티션 프루닝 | 파일 수 ↓ | 파티션 조건 필수 |
| `spark.sql.iceberg.vectorization.enabled` | CPU 효율 | true |
| `fs.s3a.experimental.input.fadvise=random` (S3A) | 불필요 읽기 방지 | random |
| `read.split.target-size` ↑ | 태스크당 파일 수 ↑, 태스크 수 ↓ | 256MB |

> ⚠️ `SELECT *` 는 전이 환경에서 비용이 특히 큽니다. 컬럼 수만큼 warm 왕복이 늘어납니다.

### 3.3 병렬도로 지연 은닉하기

전이 지연은 **레이턴시** 문제이므로 병렬도로 상당 부분 상쇄됩니다.

| 조치 | 효과 | 부작용 |
|---|---|---|
| executor 수 ↑ | 동시 요청 수 ↑ | hot 클러스터 부하 ↑ |
| executor 코어 ↑ | 동상 | 메모리 필요 |
| `http-client.apache.max-connections` ↑ | 커넥션 대기 제거 | hot 커넥션 수 ↑ |
| `read.split.target-size` ↓ | 태스크 수 ↑ (병렬↑) | 오버헤드 ↑ |

⚠️ **hot이 프록시 역할을 하므로, 병렬도를 올리면 hot의 부하가 그대로 증가**합니다. hot의 CPU/네트워크를 모니터링하며 올리십시오.

```
최적 병렬도 ≈ min(
    필요 처리량 / 파일당 처리량,
    hot이 감당 가능한 동시 요청 수,
    warm이 감당 가능한 동시 요청 수
)
```

## 4. 성능 목표 설정

측정 결과를 바탕으로 목표를 정하십시오. **절대값이 아니라 배수로 정하는 것**이 현실적입니다.

| 지표 | 목표 설정 방법 | 예시 |
|---|---|---|
| 플래닝 시간 배수 | 전이 전 대비 | ≤ 1.2× (metadata 미전이 확인) |
| 최근 파티션 쿼리 | 전이 전 대비 | ≤ 1.1× (전이 대상 아님) |
| 구 파티션 쿼리 | 전이 전 대비 | ≤ M × 1.2 (M은 §2.1 측정값) |
| 전체 스캔 | 전이 비율 가중 | 계산식으로 예측 후 검증 |
| 쓰기 처리량 | 전이 전 대비 | ≈ 1.0× (쓰기는 hot 로컬) |
| 복제 지연 p95 | RPO에서 역산 | RPO의 1/3 이하 |

### 4.1 hot 보존 기간 결정 (핵심 의사결정)

전이 후 성능이 얼마나 나빠지는지를 알면, **hot 보존 기간**을 데이터로 정할 수 있습니다.

```
1. 파티션별 쿼리 빈도 조사 (최근 30일)
2. 전이 시 각 파티션 쿼리의 지연 증가량 계산 (§1.1 식)
3. 지연 증가 × 빈도 = 총 사용자 영향
4. 영향이 허용치를 넘지 않는 최소 hot 보존일 선택
```

| hot 보존 | hot 용량 | 영향받는 쿼리 비율 | 총 지연 증가 |
|---|---|---|---|
| 1일 (테스트) | 최소 | 대부분 | 큼 |
| 7일 | 소 | | |
| 30일 | 중 | | |
| 90일 | 대 | 소수 | 작음 |

> ✅ 이 표를 실측으로 채우는 것이 이 환경 테스트의 **가장 실무적인 산출물**입니다.

```sql
-- 파티션별 쿼리 빈도 조사 (Spark 이벤트 로그 또는 쿼리 로그 기반)
-- 대안: 테이블의 파티션별 최근 접근 추정
SELECT partition, file_count, total_data_file_size_in_bytes
FROM hive_prod.ilm_test.orders.partitions
ORDER BY partition DESC;
```

## 5. 성능 문제 진단 흐름

```
쿼리가 느리다
├─ 1. 플래닝인가 실행인가?
│     Spark UI: "Scan iceberg" 이전 시간 vs 이후
│     ├─ 플래닝 → 2번
│     └─ 실행   → 5번
├─ 2. metadata가 전이됐는가?
│     mc stat 로 metadata/ 객체 확인
│     └─ YES → 🔴 ILM 규칙 수정 (04장 §3)
├─ 3. manifest가 너무 많은가?
│     SELECT count(*) FROM tbl.manifests
│     └─ YES → rewrite_manifests
├─ 4. 스냅샷이 너무 많은가?
│     └─ YES → expire_snapshots
├─ 5. 파일 수가 많은가?
│     SELECT count(*) FROM tbl.files
│     └─ YES → rewrite_data_files (05장 §5)
├─ 6. 전이 파일 비율이 높은가?
│     전이 객체 수 / 전체
│     └─ YES → 정상 비용. hot 보존 기간 재검토 (§4.1)
├─ 7. 커넥션 풀이 부족한가?
│     로그: "Timeout waiting for connection from pool"
│     └─ YES → max-connections ↑
├─ 8. 병렬도가 낮은가?
│     Spark UI 태스크 수 vs 코어 수
│     └─ YES → executor/split 조정
├─ 9. delete file이 많은가?
│     SELECT count(*) FROM tbl.delete_files
│     └─ YES → rewrite_position_delete_files
└─ 10. hot/warm 네트워크가 포화됐는가?
      hot 노드 네트워크 사용률
      └─ YES → 대역폭 증설 또는 유지보수 시간 분리
```

### 5.1 Spark UI에서 봐야 할 것

| 위치 | 지표 | 정상 | 이상 시 |
|---|---|---|---|
| SQL 탭 → 쿼리 상세 | Scan 노드의 `number of files read` | 파티션 프루닝 반영 | 프루닝 실패 |
| SQL 탭 | 쿼리 시작 ~ 첫 Job 시작 | 짧음 | 플래닝 병목 |
| Stage 탭 | Task duration 분포 | 균등 | 스큐 또는 일부 파일이 warm |
| Stage 탭 | `Shuffle Read/Write` | | 스큐 |
| Executor 탭 | Task Time / GC Time | GC < 10% | 메모리 부족 |
| Stage 탭 | Task 재시도 | 0 | 타임아웃 (전이 지연) |

> ✅ **Task duration 분포가 이중봉(bimodal)이면 전이 파일과 로컬 파일이 섞인 것**입니다. 이 패턴이 보이면 전이가 성능에 영향을 주고 있다는 직접 증거입니다.

### 5.2 채증 명령

```bash
# hot 노드 자원
mc admin info HOT
mc support perf drive HOT    2>/dev/null    # 🔍
mc support perf net   HOT    2>/dev/null    # 🔍
mc support perf object HOT   2>/dev/null    # 🔍

# 요청 추적 (짧게)
timeout 30 mc admin trace --verbose HOT | head -100
timeout 30 mc admin trace --call s3.GetObject HOT | head -50   # 🔍

# API 지연 메트릭
mc admin prometheus metrics HOT cluster | grep -E 'request|ttfb|latency'
```

## 6. 용량 및 비용

### 6.1 실효 사용량 계산

```
논리 데이터량            D
Erasure Coding 오버헤드   ×E   (예: EC:4/16 → ×1.33)
noncurrent 버전 비율      ×(1+N)
복사본 수                 ×C

hot 물리 사용량   = D_hot  × E_hot  × (1+N_hot)
warm 물리 사용량  = D_warm × E_warm × (1+N_warm) × C_warm
```

### 6.2 시나리오별 총 사용량 (D=100TB 가정)

| 구성 | hot | warm | 합계 | 비고 |
|---|---|---|---|---|
| 전이 없음, 복제 없음 | 133TB | 0 | 133TB | 기준 |
| 방식 A (전이만) | ~1TB (stub) | 133TB | 134TB | hot 용량 대폭 절감 ✅ |
| 방식 B (복제만) | 133TB | 133TB | 266TB | DR 확보 |
| A + B 동시 | ~1TB | **266TB** ⚠️ | 267TB | warm에 사본 2벌 |
| A + B + noncurrent 40% | ~1TB | 372TB | 373TB | 정리 안 할 경우 |

> ⚠️ **A+B 동시 구성 시 warm 용량이 예상의 2배**가 될 수 있습니다. [08장 T-12](../08-test-scenarios/)에서 실측 확인이 필요한 이유입니다.

### 6.3 용량 절감 조치 우선순위

| 순위 | 조치 | 절감 효과 | 리스크 |
|---|---|---|---|
| 1 | noncurrent 만료 규칙 적용 | 20~50% | 낮음 (보존기간 적정 시) |
| 2 | 미완료 멀티파트 정리 | 0~10% (숨은 누수) | 없음 |
| 3 | `expire_snapshots` 정기 실행 | 10~30% | 시간여행 범위 축소 |
| 4 | compaction (소파일 병합) | 5~15% | 유지보수 부하 |
| 5 | 전이 대상 확대 (hot 보존 단축) | hot 대폭 | 성능 영향 (§4.1) |
| 6 | 복제 범위 축소 | warm 절감 | **DR 범위 축소** ⚠️ |
| 7 | 압축 코덱 변경 (zstd) | 10~30% | 재작성 필요 |

```sql
ALTER TABLE hive_prod.ilm_test.orders SET TBLPROPERTIES (
  'write.parquet.compression-codec' = 'zstd',
  'write.parquet.compression-level' = '3'
);
```

## 7. 성능 측정 보고 템플릿

### 7.1 측정 조건

| 항목 | 값 |
|---|---|
| 측정 일시 | |
| 데이터 규모 (논리) | |
| 파일 수 / 평균 크기 | |
| 전이 비율 | % |
| Spark executor (수 × 코어 × 메모리) | |
| hot 클러스터 (노드 × 드라이브) | |
| hot↔warm RTT | ms |
| 동시 실행 잡 | |

### 7.2 결과

| 쿼리 | 전이 전 | 전이 후 | 배수 | 목표 | 판정 |
|---|---|---|---|---|---|
| | | | | | ☐P ☐F |

### 7.3 결론 및 권고

| 항목 | 결론 | 근거 |
|---|---|---|
| 권장 hot 보존 기간 | 일 | §4.1 |
| 권장 파일 크기 | MB | §1.2 |
| 권장 executor 병렬도 | | §3.3 |
| 필요 hot↔warm 대역폭 | Gbps | §1.1 |
| warm 용량 소요 | TB | §6.2 |
| 미해결 이슈 | | |

→ 다음: [11. 장애 및 리스크](../11-failure-and-risk/)
