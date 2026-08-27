# 09. 운영 절차 및 모니터링

## 1. 운영 점검 주기

| 주기 | 항목 | 소요 | 담당 | 절 |
|---|---|---|---|---|
| **일 1회** | 복제 backlog / 실패, 전이 적체, 용량 추세, 잡 실패 | 15분 | 데이터팀 | §2 |
| **주 1회** | 스캐너 사이클, 파일 수 추세, 유지보수 실행, ILM 규칙 검증 | 1시간 | 데이터팀 | §5 |
| **월 1회** | 용량 예측, 성능 추세, tier 통계, 정합성 샘플 검증 | 2시간 | 데이터팀+스토리지팀 | §6 |
| **분기 1회** | 규칙 감사, 자격증명 수명, DR 훈련, 리스크 재평가 | 반나절 | 전체 | §7 |
| **수시** | 장애 대응 | - | 온콜 | [11장](../11-failure-and-risk/) |

## 2. 일일 점검 절차

### 2.1 자동 점검 스크립트

```bash
#!/usr/bin/env bash
# daily-check.sh — 일일 점검. 이상 시 exit 1
set -u
HOT=${HOT:-HOT}; WARM=${WARM:-WARM}; BUCKET=${BUCKET:-warehouse}
TS=$(date +%F' '%T); WARN=0; CRIT=0
say(){ printf '%-10s %s\n' "$1" "$2"; }
crit(){ say "[CRIT]" "$1"; CRIT=$((CRIT+1)); }
warn(){ say "[WARN]" "$1"; WARN=$((WARN+1)); }
ok(){   say "[OK]"   "$1"; }

echo "===== 일일 점검 $TS ====="

# 1. 클러스터 상태
mc admin info "$HOT"  >/dev/null 2>&1 && ok "hot 접속"  || crit "hot 접속 실패"
mc admin info "$WARM" >/dev/null 2>&1 && ok "warm 접속" || crit "warm 접속 실패"

# 2. ILM 규칙 위험 검증 (04장 verify-ilm.sh 재사용)
if ./verify-ilm.sh "$HOT/$BUCKET" >/tmp/ilm-check.txt 2>&1; then
  ok "ILM 규칙 안전"
else
  crit "ILM 규칙 위험: $(head -3 /tmp/ilm-check.txt)"
fi

# 3. warm tier 버킷에 규칙 없음 (🔴 최우선)
if mc ilm rule ls "$WARM/warm-tier" 2>/dev/null | grep -qiE 'expir|transition'; then
  crit "warm-tier 버킷에 ILM 규칙 존재 — 전이 데이터 소실 위험"
else
  ok "warm-tier 규칙 없음"
fi

# 4. 복제 상태
R=$(mc replicate status "$HOT/$BUCKET" 2>&1)
echo "$R" | grep -qiE 'failed|error' && crit "복제 실패 감지" || ok "복제 정상"

# 5. 전이 적체
P=$(mc admin prometheus metrics "$HOT" node 2>/dev/null \
    | awk '/minio_node_ilm_transition_pending_tasks/{s+=$2} END{print s+0}')
echo "     전이 대기 작업: $P"
[ "${P%.*}" -gt 100000 ] 2>/dev/null && warn "전이 적체 과다 ($P)" || ok "전이 적체 정상"

# 6. 용량
mc du "$HOT/$BUCKET"  2>/dev/null | tail -1
mc du "$WARM/warm-tier" 2>/dev/null | tail -1
mc admin info "$HOT" | grep -iE 'used|free|capacity'

# 7. 스캐너 진행
mc admin prometheus metrics "$HOT" node 2>/dev/null | grep -E 'scanner_bucket_scans_(started|finished)'

echo "===== WARN=$WARN CRIT=$CRIT ====="
[ "$CRIT" -gt 0 ] && exit 1 || exit 0
```

### 2.2 일일 점검표

| # | 항목 | 정상 기준 | 이상 시 참조 |
|---|---|---|---|
| D-01 | hot/warm 접속 | 둘 다 Online | 11장 F-01/F-05 |
| D-02 | ILM 규칙 위험 검증 | CRITICAL 0 | 04장 §3.5 |
| D-03 | **warm-tier 버킷 규칙 없음** | 규칙 0개 | 🔴 즉시 조치 |
| D-04 | 복제 FAILED | 0건 | 11장 F-12 |
| D-05 | 복제 backlog | 목표치 이내 | §4 |
| D-06 | 전이 pending | 추세 안정 | 11장 F-09 |
| D-07 | hot 용량 | 임계 이하 | §6 |
| D-08 | warm 용량 | 임계 이하 | §6 |
| D-09 | Spark 잡 실패 | 0건 또는 원인 파악 | 06장 §5 |
| D-10 | 스캐너 진행 | 카운터 증가 중 | §3 |

## 3. ★ 스캐너 상태 진단 절차

> "ILM이 안 도는 것 같다"를 판별하는 표준 절차입니다.

### 3.1 판별 흐름

```
전이가 안 일어난다
├─ 1. 규칙이 등록되어 있는가?           mc ilm rule ls
│     └─ NO → 규칙 등록 (04장)
├─ 2. 프리픽스가 실제 경로와 맞는가?     mc ls --recursive 와 대조   ★ 최다 원인
│     └─ NO → 프리픽스 수정
├─ 3. 객체 나이가 충분한가?             mc ls 의 날짜 + S3 days 해석(02장 §3.2)
│     └─ NO → 대기 또는 Date 기준 규칙(07장 §6)
├─ 4. 스캐너 카운터가 증가하는가?        scanner_objects_scanned
│     └─ NO → 스캐너 정지/과부하 → 로그 확인, 속도 설정 확인
├─ 5. 사이클이 아직 안 돌았는가?         bucket_scans_finished 증분
│     └─ YES → 정상. 대기 (§3.2로 사이클 시간 추정)
├─ 6. 전이 작업이 적체됐는가?            ilm_transition_pending_tasks
│     └─ YES → tier 대역폭/가용성 확인
└─ 7. 전이 작업이 실패하는가?            로그, tier 접근성
      └─ YES → 11장 F-04
```

### 3.2 사이클 소요 시간 측정

```bash
#!/usr/bin/env bash
# measure-scanner-cycle.sh — 24시간 관찰로 사이클 추정
OUT=scanner-cycle-$(date +%F).csv
echo "ts,objects_scanned,versions_scanned,scans_started,scans_finished,ilm_pending" > "$OUT"
for i in $(seq 1 288); do            # 5분 간격 × 288 = 24시간
  M=$(mc admin prometheus metrics HOT node 2>/dev/null)
  o=$(echo "$M" | awk '/minio_node_scanner_objects_scanned/{s+=$2} END{print s+0}')
  v=$(echo "$M" | awk '/minio_node_scanner_versions_scanned/{s+=$2} END{print s+0}')
  a=$(echo "$M" | awk '/minio_node_scanner_bucket_scans_started/{s+=$2} END{print s+0}')
  b=$(echo "$M" | awk '/minio_node_scanner_bucket_scans_finished/{s+=$2} END{print s+0}')
  p=$(echo "$M" | awk '/minio_node_ilm_transition_pending_tasks/{s+=$2} END{print s+0}')
  echo "$(date -Is),$o,$v,$a,$b,$p" >> "$OUT"
  sleep 300
done
```

**해석**

| 관측 | 해석 |
|---|---|
| `scans_finished` 가 24시간에 N 증가 | 버킷 스캔 N회 완료 |
| `objects_scanned` 증가율 × 시간 ≈ 총 객체 수 | 1사이클 소요 추정 |
| `started - finished` 가 계속 증가 | 스캔이 완료되지 못함 ⚠️ |
| `objects_scanned` 정체 | 스캐너 정지 🔴 |
| `ilm_pending` 계속 증가 | 전이 처리량 부족 (tier 대역폭) |

```
1사이클 추정 시간 ≈ 총 객체 수 / (objects_scanned 증가율 per hour)
```

### 3.3 사이클 단축 조치 우선순위

| 순위 | 조치 | 효과 | 부작용 |
|---|---|---|---|
| 1 | **noncurrent 버전 정리** (규칙 추가) | 큼 | 없음 ✅ |
| 2 | **파일 크기 확대** (compaction) | 큼 | 유지보수 부하 |
| 3 | 불필요 버킷/프리픽스 정리 | 중~큼 | 없음 |
| 4 | 스캐너 속도 상향 | 중 | I/O 영향 |
| 5 | 노드/드라이브 증설 | 큼 | 비용 |

## 4. 복제 상태 모니터링

### 4.1 상태 확인 명령

```bash
mc replicate status HOT/warehouse
mc replicate ls     HOT/warehouse
mc admin prometheus metrics HOT cluster | grep -i replication
mc admin prometheus metrics HOT bucket  | grep -i replication   # 🔍

# 특정 객체의 복제 상태
mc stat --json HOT/warehouse/path/to/obj | python3 -m json.tool | grep -i -A3 replic
```

### 4.2 주요 메트릭

| 메트릭 (예시 🔍) | 의미 | 알람 기준(예) |
|---|---|---|
| `minio_bucket_replication_latency_ms` | 복제 지연 | p95 > 목표 RPO |
| `minio_bucket_replication_failed_bytes` | 실패 바이트 | > 0 지속 |
| `minio_bucket_replication_failed_count` | 실패 건수 | > 0 지속 |
| `minio_bucket_replication_sent_bytes` | 송신량 | 급감 시 이상 |
| `minio_bucket_replication_received_bytes` | 수신량 (대상 측) | |
| `minio_cluster_replication_last_hour_failed_bytes` | 최근 1시간 실패 | > 0 |
| `minio_bucket_replication_proxied_get_requests_total` | 프록시 조회 | 급증 시 로컬 부재 다수 |

### 4.3 복제 정합성 정기 검증

```bash
#!/usr/bin/env bash
# verify-replication.sh — 주 1회
BKT=ilm_test.db/orders
mc ls --recursive HOT/warehouse/$BKT/  | awk '{print $NF, $(NF-2)}' | sort > /tmp/hot.lst
mc ls --recursive WARM/warehouse/$BKT/ | awk '{print $NF, $(NF-2)}' | sort > /tmp/warm.lst

echo "hot  객체 수: $(wc -l < /tmp/hot.lst)"
echo "warm 객체 수: $(wc -l < /tmp/warm.lst)"
echo "--- hot 에만 존재 (미복제) ---"; comm -23 /tmp/hot.lst /tmp/warm.lst | head -20
echo "--- warm 에만 존재 (잔여) ---"; comm -13 /tmp/hot.lst /tmp/warm.lst | head -20

# ETag 샘플 대조 (100개)
shuf -n 100 /tmp/hot.lst | awk '{print $1}' | while read -r o; do
  a=$(mc stat --json "HOT/warehouse/$BKT/$o"  2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("etag",""))')
  b=$(mc stat --json "WARM/warehouse/$BKT/$o" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("etag",""))')
  [ "$a" = "$b" ] || echo "MISMATCH $o"
done
echo "ETag 대조 완료"
```

⚠️ 전이된 객체는 hot에서 실제 데이터를 다시 읽어야 체크섬 비교가 가능하므로, **전체 대조는 비용이 큽니다.** 샘플링으로 하십시오.

## 5. 주간 점검

| # | 항목 | 명령/쿼리 | 판단 |
|---|---|---|---|
| W-01 | 스캐너 사이클 추세 | §3.2 | 증가 추세면 §3.3 조치 |
| W-02 | 테이블별 파일 수 | `SELECT count(*) FROM tbl.files` | 05장 §8 기준표 |
| W-03 | 평균 파일 크기 | 동상 | < 32MB면 compaction |
| W-04 | manifest 수 | `SELECT count(*) FROM tbl.manifests` | > 1000이면 rewrite |
| W-05 | 스냅샷 수 | `SELECT count(*) FROM tbl.snapshots` | > 500이면 expire |
| W-06 | delete file 수 | `SELECT count(*) FROM tbl.delete_files` | > 10000이면 병합 |
| W-07 | noncurrent 버전 수 | `mc ls --versions \| wc -l` | 급증 시 규칙 확인 |
| W-08 | 복제 정합성 | §4.3 | 불일치 조사 |
| W-09 | ILM 규칙 diff | `mc ilm rule export` vs Git | 드리프트 감지 |
| W-10 | 미완료 멀티파트 | `mc ls --incomplete` 🔍 | 정리 |

### 주간 유지보수 배치 (예시)

```sql
-- 매주 토요일 02:00 (업무 영향 최소 시간대)
-- 1) 매니페스트 정리 (가벼움, 먼저)
CALL hive_prod.system.rewrite_manifests(table => 'ilm_test.orders');

-- 2) 소파일 병합 (무거움) ⚠️ 전이 파일 읽기 발생 → 야간 필수
CALL hive_prod.system.rewrite_data_files(
  table => 'ilm_test.orders',
  where => 'order_ts >= current_date() - interval 7 days',   -- 최근만 (전이 안 된 구간)
  options => map('min-input-files','5','target-file-size-bytes','536870912',
                 'max-concurrent-file-group-rewrites','4','partial-progress.enabled','true')
);

-- 3) delete file 병합
CALL hive_prod.system.rewrite_position_delete_files(table => 'ilm_test.orders');

-- 4) 스냅샷 만료 (마지막)
CALL hive_prod.system.expire_snapshots(
  table => 'ilm_test.orders',
  older_than => current_timestamp() - interval 7 days,
  retain_last => 10
);

-- 🚫 remove_orphan_files 는 배치에 넣지 않는다 (11장 F-06)
```

> ✅ **`where` 절로 최근 파티션만 compaction 하십시오.** 전이된 구 파티션까지 재작성하면 warm에서 전량 다시 읽어와 트래픽·시간이 폭증하고, 재작성된 파일은 나이가 리셋되어 다시 hot에 쌓입니다.

## 6. 월간 점검 — 용량 및 성능 추세

### 6.1 용량 산정표 (매월 갱신)

| 항목 | 전월 | 당월 | 증가율 | 3개월 예측 | 임계 |
|---|---|---|---|---|---|
| hot 논리 사용량 | | | | | |
| hot 물리 사용량 (EC 포함) | | | | | |
| hot noncurrent 비중 | | | | | |
| warm-tier 사용량 | | | | | |
| warm 복제본 사용량 | | | | | |
| 총 객체 수 | | | | | |
| 총 버전 수 | | | | | |
| 스캐너 1사이클 시간 | | | | | |

### 6.2 실효 용량 배수

```
총 물리 사용량 ≈ 논리 데이터량 × EC오버헤드 × (1 + noncurrent비율) × 복사본수

복사본 수:
  방식 A만    → hot(stub) + warm-tier(1)          ≈ 1.0×
  방식 B만    → hot(1) + warm복제(1)              ≈ 2.0×  (만료 전)
  A + B 동시  → hot(stub) + warm-tier + warm복제  ≈ 2.0×  ⚠️
```

| 구성 요소 | 배수 |
|---|---|
| Erasure Coding (예: EC:4 on 16드라이브) | ×1.33 (환경별 상이) |
| noncurrent 버전 (정리 전) | ×1.2 ~ ×3.0 |
| 복사본 | ×1.0 ~ ×2.0 |
| **합계 (최악)** | **×8.0 가능** |

⚠️ 이 계산을 하지 않아 용량 산정이 크게 빗나가는 것이 흔한 사례입니다. noncurrent 정리 정책이 배수를 좌우합니다.

### 6.3 성능 추세

10장의 벤치마크 쿼리를 매월 동일 조건으로 실행해 기록하십시오.

| 쿼리 | 기준선 | 전월 | 당월 | 변화 | 원인 |
|---|---|---|---|---|---|
| 전체 count | | | | | |
| 최근 파티션 조회 | | | | | |
| 전이 파티션 조회 | | | | | |
| 플래닝 시간 | | | | | |

## 7. 분기 점검 — 감사

| # | 항목 | 확인 | 조치 |
|---|---|---|---|
| Q-01 | hot/warm 전 버킷 ILM 규칙 전수 검토 | `mc ilm rule ls` (모든 버킷) | 불필요 규칙 제거 |
| Q-02 | **warm tier 버킷 규칙 없음 재확인** | 동상 | 🔴 |
| Q-03 | tier 자격증명 만료일 | 계정 정책 | 갱신 계획 |
| Q-04 | 복제 자격증명 만료일 | 동상 | 갱신 계획 |
| Q-05 | Spark 계정 권한 최소성 | `mc admin policy info` | 축소 |
| Q-06 | DR 훈련 (warm으로 복구 시나리오) | 11장 §8 | 절차 갱신 |
| Q-07 | 리스크 레지스터 재평가 | 11장 §9 | 등급 조정 |
| Q-08 | 문서 갱신 | 본 문서 | 실측값 반영 |
| Q-09 | 스캐너 속도 설정 원복 여부 | `mc admin config get` | 원복 |
| Q-10 | 미사용 tier/규칙 정리 | | 정리 |

## 8. 알람 설계

### 8.1 알람 목록

| 우선순위 | 알람 | 조건 | 대응 |
|---|---|---|---|
| P1 | hot 클러스터 다운 | health 실패 | 즉시 |
| P1 | warm-tier 버킷에 ILM 규칙 감지 | 규칙 존재 | 즉시 제거 |
| P1 | ILM 위험 규칙 감지 | `verify-ilm.sh` CRITICAL | 즉시 제거 |
| P1 | Iceberg 쿼리 `NotFoundException` | 로그 패턴 | 11장 F-02 |
| P2 | warm 클러스터 다운 | health 실패 | 전이 데이터 조회 영향 |
| P2 | 복제 실패 지속 | failed_bytes > 0 (1h) | 11장 F-12 |
| P2 | 복제 지연 초과 | latency p95 > RPO | 대역폭 점검 |
| P2 | hot 용량 임계 | > 80% | 전이/정리 |
| P3 | 전이 적체 증가 | pending 지속 증가 | tier 대역폭 |
| P3 | 스캐너 정지 | objects_scanned 정체 (2h) | 서비스 점검 |
| P3 | 파일 수 급증 | 주간 대비 +50% | compaction |
| P3 | noncurrent 비중 초과 | > 40% | 규칙 점검 |

### 8.2 Prometheus 알람 규칙 (예시)

```yaml
groups:
  - name: aistor-iceberg
    rules:
      - alert: AistorReplicationFailing
        expr: increase(minio_cluster_replication_total_failed_bytes[1h]) > 0
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "AIStor 복제 실패 발생"
          runbook: "docs/aistor-iceberg-ilm-guide/11-failure-and-risk/#f-12"

      - alert: AistorTransitionBacklog
        expr: sum(minio_node_ilm_transition_pending_tasks) > 100000
        for: 2h
        labels: { severity: warning }
        annotations:
          summary: "ILM 전이 적체"
          runbook: "docs/aistor-iceberg-ilm-guide/09-operations/#3"

      - alert: AistorScannerStalled
        expr: increase(minio_node_scanner_objects_scanned[2h]) == 0
        for: 30m
        labels: { severity: warning }
        annotations:
          summary: "스캐너 정지 의심 — ILM 미적용 상태"

      - alert: AistorHotCapacityHigh
        expr: minio_cluster_capacity_usable_free_bytes / minio_cluster_capacity_usable_total_bytes < 0.2
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "hot 클러스터 가용 용량 20% 미만"
```

🔍 메트릭 이름은 반드시 실환경에서 확인 후 적용하십시오.

```bash
mc admin prometheus metrics HOT cluster | grep -oE '^[a-z_]+' | sort -u | head -60
```

## 9. 운영 R&R

| 작업 | 데이터팀 | 스토리지팀 | 플랫폼팀 | 보안팀 |
|---|---|---|---|---|
| Iceberg 테이블 설계·유지보수 | **R** | C | I | I |
| ILM 규칙 설계 | **R** | C | I | I |
| ILM 규칙 적용 | C | **R** | I | I |
| tier/복제 구성 | C | **R** | I | I |
| Spark 잡 운영 | **R** | I | C | I |
| 모니터링/알람 | C | C | **R** | I |
| 용량 계획 | C | **R** | I | I |
| 장애 대응 (1차) | **R** | **R** | C | I |
| 자격증명 관리 | C | C | I | **R** |
| 운영데이터 반입 승인 | C | I | I | **R** |

R=책임, C=협의, I=통보

## 10. 변경 관리

| 변경 유형 | 승인 | 사전 검증 | 롤백 계획 | 공지 |
|---|---|---|---|---|
| ILM 규칙 추가/변경 | 2인 | `verify-ilm.sh` | export 백업 | 필수 |
| ILM **expiration** 추가 | **관리자 승인** 🔴 | 필수 + 리뷰 | 백업 | 필수 |
| tier 변경/삭제 | 관리자 승인 | 전이 객체 수 확인 | 재등록 절차 | 필수 |
| 복제 규칙 변경 | 2인 | 스모크 테스트 | export 백업 | 필수 |
| 스캐너 설정 | 1인 | - | 원복값 기록 | 권장 |
| Spark 설정 | 1인 | 검증 잡 | 이전 conf | 권장 |
| 테이블 속성 | 1인 | - | ALTER 원복 | 권장 |

→ 다음: [10. 성능](../10-performance/)
