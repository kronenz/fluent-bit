# 04. ILM 정책 설계 (hot 1d → warm 1d)

> 🔴 이 챕터의 설계 원칙 하나만 기억한다면: **Iceberg 데이터 경로에 `expiration`을 걸지 않는다.**
> 나머지는 전부 최적화이고, 이것만 성능·비용 문제이며, 이것을 어기면 데이터 유실입니다.

## 1. 설계 원칙

| # | 원칙 | 이유 | 위반 시 |
|---|---|---|---|
| P-1 | Iceberg 데이터 파일에 **age 기반 expiration 금지** | 객체 나이 ≠ Iceberg 참조 여부 | 🔴 테이블 손상 |
| P-2 | `metadata/` 프리픽스는 **transition에서도 제외** | 매 쿼리마다 읽는 경로 | 🟠 전 쿼리 지연 급증 |
| P-3 | 프리픽스로 대상을 **명시적으로 한정** (버킷 전체 규칙 금지) | 규칙이 의도치 않은 경로에 적용됨 | 🔴/🟠 |
| P-4 | **noncurrent expiration은 반드시 설정** | 버저닝 용량 무한 증가 + 스캐너 사이클 악화 | 🟠 |
| P-5 | 삭제(정리)는 **Iceberg 프로시저**가, 계층 이동은 **ILM**이 담당 | 책임 분리. Iceberg만 참조 유효성을 안다 | 🔴 |
| P-6 | warm의 tier 버킷에는 **어떤 ILM 규칙도 두지 않는다** | 전이 데이터 실체가 여기 있음 | 🔴 |
| P-7 | 규칙 변경은 백업 → 적용 → 검증 순서 | 되돌릴 수 없는 만료가 존재 | - |

### P-1을 그림으로

```
객체 나이:        ──────────────────────────────────► 오래됨
Iceberg 참조:     ████░░░░████████░░░░████░░░████████
                  (참조중)(고아)(참조중)  (고아)(참조중)

ILM expiration(age 1d):  1일 넘은 것 전부 삭제 ✂️
                         → 참조중인 파일까지 삭제됨 🔴

Iceberg expire_snapshots / remove_orphan_files:
                         → 고아(░)만 삭제 ✅
```

**"오래된 것"과 "안 쓰는 것"은 다릅니다.** ILM은 전자만 알고, Iceberg만 후자를 압니다.

## 2. 테이블 레이아웃 전제

Iceberg + HMS 카탈로그의 기본 레이아웃:

```
s3://warehouse/
  └── <db>.db/
      └── <table>/
          ├── metadata/                    ← 🚫 전이·만료 모두 제외
          │   ├── 00001-<uuid>.metadata.json
          │   ├── snap-<snapshot-id>-1-<uuid>.avro     (manifest list)
          │   └── <uuid>-m0.avro                        (manifest)
          └── data/                        ← ✅ 전이 대상 (만료는 금지)
              └── dt=2026-08-26/
                  └── 00000-0-<uuid>.parquet
```

⚠️ **레이아웃을 먼저 확인하십시오.** 테이블 생성 방식/버전에 따라 `data/` 하위가 아니라 파티션 디렉터리가 테이블 루트 바로 아래에 오는 경우도 있습니다.

```sql
-- 실제 경로 확인
SELECT file_path FROM hive_prod.db.tbl.files LIMIT 5;
SELECT * FROM hive_prod.db.tbl.metadata_log_entries ORDER BY timestamp DESC LIMIT 5;
```

```bash
# 객체 스토리지에서 직접 확인
mc ls --recursive HOT/warehouse/db.db/tbl/ | awk '{print $NF}' | sed 's|/[^/]*$||' | sort -u | head -20
```

### ⚠️ ObjectStoreLocationProvider 를 쓰는 경우

`write.object-storage.enabled=true` 인 테이블은 데이터 파일 경로 앞에 **해시 프리픽스**가 붙습니다.

```
s3://warehouse/db.db/tbl/data/a1b2/c3d4/dt=2026-08-26/00000-0-<uuid>.parquet
                              ^^^^^^^^^ 랜덤 해시
```

| 영향 | 내용 |
|---|---|
| 프리픽스 기반 ILM 규칙 | `data/` 로 시작하면 여전히 매칭됨 ✅ (해시는 `data/` 뒤에 옴) |
| 단, 설정에 따라 해시가 **테이블 루트 앞**에 올 수도 있음 🔍 | 이 경우 프리픽스 규칙이 깨짐 🔴 |
| 조치 | 위 SQL로 실제 `file_path` 를 반드시 확인 후 규칙 프리픽스 결정 |

```sql
-- 확인 (해시가 어디에 붙는지)
SELECT file_path FROM hive_prod.db.tbl.files LIMIT 3;
```

## 3. 권장 규칙 세트

### 3.1 규칙 목록

| ID | 이름 | 프리픽스 | 동작 | 값 | 목적 |
|---|---|---|---|---|---|
| R-1 | data-transition | `<table-prefix>/data/` | Transition → WARM-TIER | 1일 (테스트) | hot 용량 절감 |
| R-2 | data-noncurrent-transition | 동일 | Noncurrent transition | 1일 | 구버전도 내려보냄 (선택) |
| R-3 | data-noncurrent-expire | 동일 | Noncurrent expiration | 7일 (테스트) | 용량 회수 ✅ |
| R-4 | metadata-keep | `<table-prefix>/metadata/` | **규칙 없음** | - | 명시적 제외 |
| R-5 | mpu-cleanup | 버킷 전체 | AbortIncompleteMultipartUpload | 3일 | 숨은 용량 누수 제거 |
| R-6 | delete-marker-cleanup | `<table-prefix>/` | Expire delete markers | - | 고아 마커 정리 |

> 🚫 **의도적으로 넣지 않은 것**: `Expiration (current version)`. Iceberg 데이터에는 절대 넣지 않습니다.

### 3.2 적용 명령

```bash
BUCKET=HOT/warehouse
TBL=db.db/tbl                      # 실제 테이블 프리픽스로 치환

# R-1: 데이터 파일 전이 (1일)
mc ilm rule add "$BUCKET" \
  --prefix "$TBL/data/" \
  --transition-days 1 \
  --transition-tier WARM-TIER

# R-2: noncurrent 버전 전이 (선택)
mc ilm rule add "$BUCKET" \
  --prefix "$TBL/data/" \
  --noncurrent-transition-days 1 \
  --noncurrent-transition-tier WARM-TIER

# R-3: noncurrent 버전 만료 (필수) — current 버전은 건드리지 않음
mc ilm rule add "$BUCKET" \
  --prefix "$TBL/data/" \
  --noncurrent-expire-days 7

# R-5: 미완료 멀티파트 정리 🔍 (플래그명 버전 확인)
mc ilm rule add "$BUCKET" --prefix "" --expire-delete-marker   # 예시, --help 확인

# 확인
mc ilm rule ls "$BUCKET"
mc ilm rule export "$BUCKET" | python3 -m json.tool
```

🔍 `mc ilm rule add --help` 로 플래그명을 먼저 확인하십시오. 계열에 따라 `--expiry-days` / `--expire-days`, `--noncurrentversion-expiration-days` / `--noncurrent-expire-days` 등으로 다릅니다.

### 3.3 JSON으로 직접 관리 (권장)

규칙이 여러 개가 되면 CLI 플래그보다 JSON 관리가 안전합니다. **Git으로 버전 관리하십시오.**

```bash
cat > ilm-warehouse.json <<'EOF'
{
  "Rules": [
    {
      "ID": "data-transition-1d",
      "Status": "Enabled",
      "Filter": { "Prefix": "db.db/tbl/data/" },
      "Transition": { "Days": 1, "StorageClass": "WARM-TIER" }
    },
    {
      "ID": "data-noncurrent-transition-1d",
      "Status": "Enabled",
      "Filter": { "Prefix": "db.db/tbl/data/" },
      "NoncurrentVersionTransition": { "NoncurrentDays": 1, "StorageClass": "WARM-TIER" }
    },
    {
      "ID": "data-noncurrent-expire-7d",
      "Status": "Enabled",
      "Filter": { "Prefix": "db.db/tbl/data/" },
      "NoncurrentVersionExpiration": { "NoncurrentDays": 7 }
    },
    {
      "ID": "abort-mpu-3d",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 3 }
    },
    {
      "ID": "expire-delete-markers",
      "Status": "Enabled",
      "Filter": { "Prefix": "db.db/tbl/" },
      "Expiration": { "ExpiredObjectDeleteMarker": true }
    }
  ]
}
EOF

mc ilm rule import HOT/warehouse < ilm-warehouse.json
mc ilm rule ls     HOT/warehouse
```

> ⚠️ `import`는 **기존 규칙 전체를 대체**합니다. 반드시 export 백업 후 실행하십시오.

### 3.4 ⚠️ 절대 만들면 안 되는 규칙 (안티패턴)

```json
// 🔴 금지 1: 버킷 전체 만료 — 모든 Iceberg 파일 삭제
{ "ID": "bad", "Status": "Enabled",
  "Filter": {"Prefix": ""}, "Expiration": {"Days": 1} }

// 🔴 금지 2: 데이터 경로 current 버전 만료 — live 스냅샷 파일 삭제
{ "ID": "bad", "Status": "Enabled",
  "Filter": {"Prefix": "db.db/tbl/data/"}, "Expiration": {"Days": 1} }

// 🔴 금지 3: 메타데이터 만료 — 테이블 즉시 손상
{ "ID": "bad", "Status": "Enabled",
  "Filter": {"Prefix": "db.db/tbl/metadata/"}, "Expiration": {"Days": 1} }

// 🟠 비권장 4: 메타데이터 전이 — 모든 쿼리 플래닝 지연
{ "ID": "meh", "Status": "Enabled",
  "Filter": {"Prefix": "db.db/tbl/metadata/"}, "Transition": {"Days": 1, "StorageClass": "WARM-TIER"} }

// 🔴 금지 5: 모든 버전 삭제 옵션 사용 (버전 안전망 무력화)
{ "Expiration": {"Days": 1, "ExpiredObjectAllVersions": true} }
```

### 3.5 규칙 검증 스크립트

적용 후 반드시 자동 검증하십시오.

```bash
#!/usr/bin/env bash
# verify-ilm.sh — 위험 규칙 탐지
set -u
BUCKET=${1:-HOT/warehouse}
J=$(mc ilm rule export "$BUCKET")
FAIL=0

echo "$J" | python3 - "$BUCKET" <<'PY'
import json,sys
b=sys.argv[1]; d=json.load(sys.stdin); bad=[]
for r in d.get("Rules",[]):
    rid=r.get("ID","?"); pre=(r.get("Filter") or {}).get("Prefix","")
    exp=r.get("Expiration") or {}
    tr =r.get("Transition")  or {}
    if exp.get("Days") and "metadata/" in pre:      bad.append((rid,"CRITICAL","metadata 만료 규칙"))
    if exp.get("Days") and "data/"     in pre:      bad.append((rid,"CRITICAL","data current 버전 만료 규칙"))
    if exp.get("Days") and pre=="":                 bad.append((rid,"CRITICAL","버킷 전체 만료 규칙"))
    if exp.get("ExpiredObjectAllVersions"):         bad.append((rid,"CRITICAL","전 버전 삭제 옵션"))
    if tr.get("Days") and "metadata/" in pre:       bad.append((rid,"WARN","metadata 전이 규칙(성능)"))
    if pre=="" and (tr.get("Days")):                bad.append((rid,"WARN","버킷 전체 전이 규칙"))
has_nc = any((r.get("NoncurrentVersionExpiration") or {}).get("NoncurrentDays") for r in d.get("Rules",[]))
if not has_nc: bad.append(("-","WARN","noncurrent 만료 규칙 없음(용량 증가)"))
for rid,sev,msg in bad: print(f"[{sev}] rule={rid}: {msg}")
print("OK: 위험 규칙 없음" if not bad else f"총 {len(bad)}건")
sys.exit(1 if any(s=="CRITICAL" for _,s,_ in bad) else 0)
PY
```

> ✅ 이 스크립트를 CI 또는 일일 점검(09장)에 넣으십시오. 사람의 리뷰만으로는 반복 실수를 막지 못합니다.

## 4. hot 1일 / warm 1일의 의미 정리

"hot 1d, warm 1d"는 구성 방식에 따라 다르게 해석됩니다.

| 구성 | hot 1d 의 의미 | warm 1d 의 의미 | 안전한가 |
|---|---|---|---|
| 방식 A (tier) | 1일 후 warm으로 **전이** | warm tier 버킷의 규칙 — **있으면 안 됨** 🔴 | 하단 참조 |
| 방식 B (복제+만료) | 1일 후 hot에서 **삭제** | warm 사본을 1일 후 삭제 | 🔴 Iceberg엔 부적합 |
| 계층 3단 구성 | 1일 후 warm | warm에서 1일 후 cold(별도 tier) | 별도 tier 등록 필요 |

### 🔴 "warm 1d"가 warm tier 버킷의 만료 규칙이라면 즉시 중단

방식 A에서 warm-tier 버킷은 **hot 객체의 실데이터 저장소**입니다. 여기에 1일 만료 규칙이 있으면:

```
T+24h  hot의 data/x.parquet → warm-tier로 전이 (hot은 stub)
T+48h  warm-tier의 실데이터가 만료 규칙으로 삭제됨 ⚠️
       → hot의 stub은 남아 있음 → mc ls 하면 파일이 "보임"
       → 그러나 GET 하면 실패 → Iceberg 쿼리 실패, 복구 불가
```

**증상이 지연되어 나타나기 때문에** 가장 발견이 늦고 피해가 큰 유형입니다. 03장 D-2 확인 항목이 이것입니다.

### warm에서의 3단 계층이 목적이라면

warm 클러스터에서 다시 cold로 내리려면, **warm 클러스터에 별도의 tier를 등록**하고 warm의 *일반 버킷*에 규칙을 겁니다. warm-tier 버킷(hot의 전이 대상)에는 여전히 규칙을 두지 않습니다.

| 계층 | 클러스터 | 버킷 | 규칙 |
|---|---|---|---|
| hot | hot | warehouse | transition 1d → WARM-TIER |
| warm | warm | warm-tier | **규칙 없음** (hot이 관리) |
| cold | (별도) | - | hot에 COLD tier를 추가 등록하고 hot 규칙으로 제어 🔍 |

> 즉, **다단 계층도 hot의 규칙에서 제어**하는 것이 안전합니다. 대상만 다른 tier로 지정합니다.

## 5. Noncurrent 버전 정책 (필수)

### 5.1 왜 필수인가

| 시점 | 이벤트 | noncurrent 증가 |
|---|---|---|
| 매일 | Spark write (신규 파일) | 0 (덮어쓰기 아님) |
| 주 1회 | `expire_snapshots` | 수천~수만 개 delete marker + noncurrent |
| 주 1회 | `rewrite_data_files` | compaction된 구 파일이 noncurrent화 |
| 커밋마다 | 구 metadata.json 정리 | 수십 개 |

규칙이 없으면 이 전부가 **영구 잔존**합니다.

### 5.2 보존 기간 산정

```
noncurrent 보존일 ≥ max(
    Iceberg 스냅샷 보존 기간,          -- 실수 복구 여지
    유지보수 주기 × 2,                 -- 롤백 여유
    DR 복제 지연 최대치 × 3            -- 복제 완료 보장
)
```

| 환경 | 권장 |
|---|---|
| 테스트 (본 구성) | 3~7일 |
| 운영 초기 | 14~30일 |
| 운영 안정화 후 | 7~14일 |

⚠️ noncurrent 보존을 너무 짧게 잡으면, **복제가 끝나기 전에 원본 버전이 사라져** 복제 실패가 누적될 수 있습니다.

### 5.3 delete marker 정리

```json
{ "ID": "expire-delete-markers", "Status": "Enabled",
  "Filter": {"Prefix": "db.db/tbl/"},
  "Expiration": {"ExpiredObjectDeleteMarker": true} }
```

`ExpiredObjectDeleteMarker: true` 는 **하위 버전이 모두 사라진 고아 delete marker만** 제거합니다. `Days`와 함께 쓰면 안 됩니다(그러면 일반 만료가 됨).

| 옵션 | 동작 | 안전성 |
|---|---|---|
| `ExpiredObjectDeleteMarker: true` (단독) | 고아 마커만 정리 | ✅ 안전 |
| `Expiration.Days: N` | current 버전 삭제 | 🔴 Iceberg에 금지 |
| `ExpiredObjectAllVersions: true` | 전 버전 삭제 | 🔴 금지 |

## 6. 테스트 기간 스캐너 튜닝

```bash
# 1) 현재값 백업
mc admin config get HOT scanner > scanner-backup.txt

# 2) 테스트용 가속
mc admin config set HOT scanner speed=fast     # 🔍 키 확인 필수

# 3) 사이클 관찰 (09장 §3 절차)
watch -n 60 'mc admin prometheus metrics HOT node | grep scanner_bucket_scans_finished'

# 4) 테스트 종료 후 반드시 원복 ⚠️
mc admin config set HOT scanner speed=default
```

| 설정 | 예상 사이클 (상대) | 사용자 I/O 영향 | 권고 |
|---|---|---|---|
| `default` | 1.0× | 없음 | 운영 |
| `fast` | 0.3~0.5× | 소 | 테스트 ✅ |
| `fastest` | 0.1~0.2× | 중~대 ⚠️ | 짧은 검증 구간만 |

### 사이클을 줄이는 더 좋은 방법: 데이터셋 축소

스캐너 튜닝보다 효과적이고 안전합니다.

| 방법 | 사이클 단축 효과 | 위험 |
|---|---|---|
| 전용 소규모 테스트 버킷 사용 | **매우 큼** (객체 수에 비례) | 없음 ✅ |
| 스캐너 속도 상향 | 중 | I/O 영향 |
| noncurrent 정리로 버전 수 감소 | 중~큼 | 없음 ✅ |
| 파일 크기 키워 파일 수 감소 | 큼 | 쓰기 패턴 변경 필요 |

> ✅ **권장 테스트 전략**: 1단계 — 객체 1,000개 규모 전용 버킷에서 정책 로직 검증(수 시간). 2단계 — 실 데이터 규모에서 성능/사이클 검증(수 일). 이 순서를 지키면 원인 분리가 가능합니다.

## 7. 규칙 적용 후 검증 절차

| 단계 | 확인 | 명령 | 기대 |
|---|---|---|---|
| 1 | 규칙 등록 | `mc ilm rule ls HOT/warehouse` | 의도한 규칙만 존재 |
| 2 | 위험 규칙 없음 | `verify-ilm.sh` | OK |
| 3 | 대상 프리픽스 정확 | `mc ls --recursive HOT/warehouse/db.db/tbl/data/ \| head` | 실제 경로와 일치 |
| 4 | metadata 제외 확인 | 규칙 프리픽스에 metadata 없음 | ✅ |
| 5 | 전이 시작 관찰 | `mc admin prometheus metrics HOT node \| grep ilm_transition` | pending/active 증가 |
| 6 | 실물 전이 확인 | `mc stat HOT/warehouse/.../*.parquet` | `Tier: WARM-TIER` |
| 7 | 전이 후 조회 | Spark 쿼리 | 결과 동일 ✅ |
| 8 | metadata 미전이 확인 | `mc stat HOT/warehouse/.../metadata/*.json` | Tier 표기 **없음** ✅ |
| 9 | warm 용량 증가 | `mc du WARM/warm-tier` | 증가 |
| 10 | hot 용량 감소 | `mc du HOT/warehouse` 🔍 | 감소 (통계 갱신 지연 있음) |

⚠️ 10번의 `mc du`는 스캐너가 집계하므로 **즉시 반영되지 않습니다.** 사이클 1회 이후에 보십시오.

## 8. 규칙 변경 관리 (관리적 통제)

| 통제 | 내용 | 담당 |
|---|---|---|
| 형상관리 | `ilm-*.json` 을 Git에 보관, 변경은 PR로 | 데이터팀 |
| 리뷰 | expiration 계열 추가 시 2인 승인 필수 | 데이터팀 + 스토리지팀 |
| 자동 검증 | `verify-ilm.sh` 를 CI/일일 배치에 편성 | 플랫폼팀 |
| 변경 기록 | 아래 표를 문서에 누적 | 변경 담당 |
| 정기 감사 | 분기 1회 hot/warm 전 버킷 규칙 점검 | 스토리지팀 |

### 변경 이력표 (템플릿)

| 일자 | 버킷 | 규칙 ID | 변경 | 사유 | 승인 | 롤백 방법 |
|---|---|---|---|---|---|---|
| | | | | | | |

## 9. 이 챕터 요약

- Iceberg 데이터에는 **transition만, expiration은 절대 금지**.
- `metadata/`는 전이·만료 모두 제외 (성능 + 안전).
- **noncurrent expiration은 반드시 설정** — 안 하면 용량과 스캐너가 동시에 망가진다.
- warm tier 버킷에는 어떤 규칙도 두지 않는다. 다단 계층도 hot에서 제어한다.
- 규칙은 JSON + Git + 자동 검증으로 관리한다.
- 테스트 가속은 스캐너 속도보다 **데이터셋 축소**가 안전하고 효과적이다.

→ 다음: [05. Iceberg on S3 — 구조와 충돌 지점](../05-iceberg-on-s3/)
