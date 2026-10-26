# 03. 클러스터 구성 및 검증 절차

> ⚠️ 이 챕터의 명령은 **운영 클러스터에 정책을 변경**합니다. §7 현행 진단을 먼저 수행하고, 변경 전 §8 백업을 반드시 실행하십시오.
> 🔍 표시 명령은 버전에 따라 플래그가 다릅니다. `--help`로 먼저 확인하십시오.

## 1. 작업 순서 개요

| 단계 | 작업 | 소요(예상) | 되돌릴 수 있는가 | 절 |
|---|---|---|---|---|
| 0 | 현행 구성 진단 | 30분 | - | §7 |
| 0.5 | 기존 설정 백업(export) | 10분 | - | §8 |
| 1 | mc alias 등록 | 5분 | ✅ | §2 |
| 2 | 서비스 계정/정책 생성 | 20분 | ✅ | §3 |
| 3 | 버킷 생성 + Versioning | 10분 | ⚠️ Versioning은 Suspend만 가능, OFF 불가 | §4 |
| 4 | Remote Tier 등록 | 15분 | ⚠️ 사용 중이면 삭제 불가 | §5 |
| 5 | Replication 설정 | 20분 | ✅ | §6 |
| 6 | ILM 규칙 설정 | 30분 | ✅ (단 이미 실행된 만료는 복구 불가) | [04장](../04-ilm-policy-design/) |
| 7 | 구성 검증 | 30분 | - | §9 |

## 2. mc alias 등록

```bash
# hot 클러스터 (관리자 자격)
mc alias set HOT  https://hot-s3.example.internal  <ACCESS_KEY> <SECRET_KEY> --api S3v4

# warm 클러스터 (관리자 자격)
mc alias set WARM https://warm-s3.example.internal <ACCESS_KEY> <SECRET_KEY> --api S3v4

# 확인
mc alias list
mc admin info HOT
mc admin info WARM
```

### 확인 결과 기록표

| 항목 | HOT | WARM |
|---|---|---|
| 버전 | | |
| 노드 수 | | |
| 드라이브 수 | | |
| 총 용량 / 사용량 | | |
| 상태(online) | | |

⚠️ 자격증명을 셸 히스토리에 남기지 않으려면 `MC_HOST_HOT` 환경변수 방식을 사용하십시오.

```bash
export MC_HOST_HOT='https://ACCESS:SECRET@hot-s3.example.internal'
mc ls HOT/
```

## 3. 서비스 계정 및 정책

### 3.1 계정 설계

| 계정 | 사용처 | 대상 | 권한 범위 | 자격증명 저장 위치 |
|---|---|---|---|---|
| `svc-spark` | Spark 읽기/쓰기 | hot | `warehouse` 버킷 RW | K8s Secret |
| `svc-tier` | ILM transition | warm | `warm-tier` 버킷 RW | hot의 tier 설정 내부 |
| `svc-repl` | Replication | warm | `warehouse` 버킷 RW + 복제 | hot의 복제 설정 내부 |
| `svc-monitor` | 모니터링 | hot/warm | 읽기 전용 + 메트릭 | Prometheus Secret |
| `svc-migrate` | 운영데이터 반입 | 운영 S3 | **읽기 전용** ⚠️ | 임시, 작업 후 폐기 |

### 3.2 Spark용 정책 예시

```bash
cat > /tmp/policy-spark.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:ListBucketVersions",
        "s3:GetBucketLocation",
        "s3:ListBucketMultipartUploads"
      ],
      "Resource": ["arn:aws:s3:::warehouse"]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": ["arn:aws:s3:::warehouse/*"]
    }
  ]
}
EOF

mc admin policy create HOT spark-rw /tmp/policy-spark.json
mc admin user  add     HOT svc-spark '<SECRET>'
mc admin policy attach HOT spark-rw --user svc-spark
```

> ⚠️ `s3:DeleteObjectVersion`은 기본적으로 부여하지 마십시오. 부여하면 Spark 작업 실수로 **영구 삭제**가 가능해집니다. 유지보수 시에만 별도 계정으로 수행하십시오.

### 3.3 tier / replication 계정 (warm)

```bash
# tier 전용
mc admin user add WARM svc-tier '<SECRET>'
mc mb WARM/warm-tier --ignore-existing
# warm-tier 버킷 RW 정책 생성 후 attach (위와 동일 패턴)

# replication 전용
mc admin user add WARM svc-repl '<SECRET>'
mc mb WARM/warehouse --ignore-existing
mc version enable WARM/warehouse
```

복제 대상 계정에는 복제 수신에 필요한 권한이 포함되어야 합니다 🔍.

```json
{
  "Effect": "Allow",
  "Action": [
    "s3:GetBucketVersioning", "s3:PutBucketVersioning",
    "s3:ListBucket", "s3:ListBucketVersions",
    "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectVersionTagging",
    "s3:PutObject", "s3:DeleteObject",
    "s3:ReplicateObject", "s3:ReplicateDelete", "s3:ReplicateTags"
  ],
  "Resource": ["arn:aws:s3:::warehouse", "arn:aws:s3:::warehouse/*"]
}
```

## 4. 버킷 및 Versioning

```bash
# hot
mc mb HOT/warehouse --ignore-existing
mc version enable HOT/warehouse
mc version info   HOT/warehouse      # → Enabled 확인

# warm (복제 대상)
mc mb WARM/warehouse --ignore-existing
mc version enable WARM/warehouse
mc version info   WARM/warehouse

# warm (tier 대상) — Versioning 불필요 🔍
mc mb WARM/warm-tier --ignore-existing
```

| 확인 항목 | 기대값 | ✅ |
|---|---|---|
| `mc version info HOT/warehouse` | Enabled | |
| `mc version info WARM/warehouse` | Enabled | |
| 두 버킷 이름 동일 여부 | 동일 권장 (경로 혼선 방지) | |

⚠️ **Versioning은 한 번 켜면 완전히 끌 수 없습니다** (Suspended만 가능, 기존 버전은 잔존). 테스트 버킷과 운영 버킷을 분리하십시오.

## 5. Remote Tier 등록 (방식 A)

### 5.1 등록

```bash
mc ilm tier add minio HOT WARM-TIER \
  --endpoint   https://warm-s3.example.internal \
  --access-key svc-tier \
  --secret-key '<SECRET>' \
  --bucket     warm-tier \
  --prefix     iceberg/ \
  --region     us-east-1
```

| 옵션 | 의미 | 권고 |
|---|---|---|
| `minio` | tier 타입 (다른 AIStor/MinIO 대상) | 본 구성 |
| `HOT` | tier를 등록할 클러스터 (전이의 **출발지**) | |
| `WARM-TIER` | tier 이름. 대문자 관례. **나중에 변경 불가** 🔍 | 신중히 명명 |
| `--prefix` | 전이 데이터가 저장될 하위 경로 | ✅ 지정 권장 (버킷 재사용 시 구분) |
| `--storage-class` | S3 타입 tier에서만 의미 | minio 타입엔 불필요 |

### 5.2 확인

```bash
mc ilm tier ls   HOT
mc ilm tier info HOT WARM-TIER      # 🔍 전이 객체 수/용량 통계 제공
```

| 확인 항목 | 기대값 | ✅ |
|---|---|---|
| tier 목록에 `WARM-TIER` 존재 | Y | |
| 상태 | 정상/Online | |
| 통계 (초기) | 0 objects | |

### 5.3 tier 관련 주의

| 항목 | 내용 | 위험 |
|---|---|---|
| tier 삭제 | 전이된 객체가 있으면 삭제 불가(또는 삭제 시 참조 깨짐) | 🔴 치명 |
| 자격증명 변경 | `mc ilm tier update` 로 갱신 🔍. 만료 시 **모든 전이 객체 조회 불가** | 🔴 치명 |
| 대상 버킷 삭제 | 전이 데이터 전부 소실 | 🔴 치명 |
| 대상 버킷에 ILM 만료 규칙 | 전이 데이터 소실 | 🔴 치명 |
| 엔드포인트 변경(DNS/인증서) | 전이 객체 조회 실패 | 🟠 |

```bash
# 자격증명 갱신 (예시) 🔍
mc ilm tier update HOT WARM-TIER --access-key svc-tier --secret-key '<NEW_SECRET>'
```

> ✅ **운영 체크리스트에 넣을 것**: tier 계정의 자격증명 만료일, warm-tier 버킷의 ILM 규칙 없음 확인 (분기 1회).

## 6. Replication 설정 (방식 B / DR)

### 6.1 버킷 복제 규칙 추가

```bash
mc replicate add HOT/warehouse \
  --remote-bucket "https://svc-repl:<SECRET>@warm-s3.example.internal/warehouse" \
  --replicate "existing-objects,delete-marker,delete" \
  --priority 1 \
  --storage-class "" \
  --tags "" \
  --path off
```

| 옵션 | 설명 | 이 환경 권고 |
|---|---|---|
| `--replicate existing-objects` | 기존 객체 포함 | ✅ 초기 1회 필요 |
| `--replicate delete` | 버전 삭제 전파 | 결정 필요 → [02장 §4.2](../02-aistor-internals/) |
| `--replicate delete-marker` | delete marker 전파 | 결정 필요 |
| `--replicate replica-metadata-sync` | 양방향 시 메타 동기화 | active-active 시 ✅ |
| `--priority` | 규칙 우선순위 | 규칙 1개면 1 |
| `--path off/on` | path-style 강제 | 엔드포인트 형태에 맞춤 |

### 6.2 프리픽스 한정 복제(선택)

Iceberg 메타데이터만 우선 복제하고 싶은 경우 등:

```bash
mc replicate add HOT/warehouse \
  --remote-bucket "https://svc-repl:<SECRET>@warm-s3.example.internal/warehouse" \
  --prefix "metadata/" --priority 1 --replicate "existing-objects"
```

⚠️ **Iceberg에서 메타데이터만 복제하는 것은 무의미하거나 위험합니다.** metadata가 참조하는 data 파일이 없으면 DR 사본으로 쓸 수 없고, "복제됐다"는 착시만 줍니다. 부분 복제를 할 거라면 **테이블 단위(테이블 프리픽스 전체)** 로 나누십시오.

### 6.3 확인

```bash
mc replicate ls     HOT/warehouse
mc replicate status HOT/warehouse
mc replicate export HOT/warehouse          # JSON 백업
```

| 확인 항목 | 기대값 | ✅ |
|---|---|---|
| 규칙 상태 | Enabled / Active | |
| 대상 ARN | warm 엔드포인트/버킷 정확 | |
| 대상 버킷 Versioning | Enabled | |
| 복제 지연 | 초기 0 | |

## 7. ★ 현행 구성 진단 절차

> "지금 우리 환경이 방식 A인가 B인가 A+B인가"를 30분 안에 확정하는 절차입니다.
> 결과에 따라 04·08·11장에서 볼 내용이 갈립니다.

### 7.1 진단 스크립트

```bash
#!/usr/bin/env bash
# diag-aistor.sh — 현행 hot/warm 구성 진단
set -u
HOT=${HOT:-HOT}; WARM=${WARM:-WARM}; BUCKET=${BUCKET:-warehouse}
OUT=./diag-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"

echo "== [1] 클러스터 정보 =="
mc admin info  "$HOT"                       | tee "$OUT/01-hot-info.txt"
mc admin info  "$WARM"                      | tee "$OUT/02-warm-info.txt"
mc --version                                | tee "$OUT/03-mc-version.txt"

echo "== [2] 버킷/버저닝 =="
mc ls          "$HOT"                       | tee "$OUT/10-hot-buckets.txt"
mc ls          "$WARM"                      | tee "$OUT/11-warm-buckets.txt"
mc version info "$HOT/$BUCKET"              | tee "$OUT/12-hot-versioning.txt"
mc version info "$WARM/$BUCKET" 2>/dev/null | tee "$OUT/13-warm-versioning.txt"

echo "== [3] Tier (방식 A 여부) =="
mc ilm tier ls "$HOT"                       | tee "$OUT/20-hot-tiers.txt"
for t in $(mc ilm tier ls "$HOT" --json 2>/dev/null | grep -o '"name":"[^"]*"' | cut -d'"' -f4); do
  mc ilm tier info "$HOT" "$t"              | tee "$OUT/21-tier-$t.txt"
done

echo "== [4] ILM 규칙 =="
mc ilm rule ls     "$HOT/$BUCKET"           | tee "$OUT/30-hot-ilm.txt"
mc ilm rule export "$HOT/$BUCKET"           | tee "$OUT/31-hot-ilm.json"
mc ilm rule ls     "$WARM/$BUCKET" 2>/dev/null | tee "$OUT/32-warm-ilm.txt"
mc ilm rule ls     "$WARM/warm-tier" 2>/dev/null | tee "$OUT/33-warmtier-ilm.txt"   # ⚠️ 여기 규칙 있으면 즉시 조사

echo "== [5] Replication (방식 B 여부) =="
mc replicate ls     "$HOT/$BUCKET"          | tee "$OUT/40-hot-repl.txt"
mc replicate status "$HOT/$BUCKET"          | tee "$OUT/41-hot-repl-status.txt"
mc replicate export "$HOT/$BUCKET"          | tee "$OUT/42-hot-repl.json"
mc admin replicate info "$HOT" 2>/dev/null  | tee "$OUT/43-site-repl.txt"   # 사이트 복제 여부

echo "== [6] Scanner 설정 =="
mc admin config get "$HOT" scanner          | tee "$OUT/50-scanner.txt"
mc admin config get "$HOT" api 2>/dev/null  | tee "$OUT/51-api.txt"

echo "== [7] ILM/스캐너 메트릭 =="
mc admin prometheus metrics "$HOT" cluster 2>/dev/null | grep -Ei 'ilm|tier|replication' | tee "$OUT/60-metrics-cluster.txt"
mc admin prometheus metrics "$HOT" node    2>/dev/null | grep -Ei 'scanner|ilm'          | tee "$OUT/61-metrics-node.txt"

echo "결과: $OUT"
```

### 7.2 판정표

진단 결과를 아래 표로 해석합니다.

| 관찰 | 방식 A (tier) | 방식 B (복제+만료) | A+B |
|---|---|---|---|
| `mc ilm tier ls HOT` 결과 | tier 존재 | 없음 | 존재 |
| hot ILM 규칙에 `Transition` | 있음 | 없음 | 있음 |
| hot ILM 규칙에 `Expiration` | 없어야 정상 | 있음 | 있음 ⚠️ |
| `mc replicate ls HOT/BUCKET` | 있을 수도(DR 목적) | 있음 | 있음 |
| 임의 구객체 `mc stat` | `Tier: WARM-TIER` 표기 | 표기 없음 | 표기 |
| warm 버킷 목록 | tier용 버킷 존재 | warehouse만 | 둘 다 |

### 7.3 즉시 확인해야 할 위험 항목

진단 직후 아래를 **먼저** 확인하십시오. 하나라도 해당되면 04장 진행 전에 조치합니다.

| # | 확인 | 명령 | 위험 시 조치 |
|---|---|---|---|
| D-1 | hot ILM에 Iceberg 데이터 경로 대상 **Expiration** 규칙이 있는가 | `mc ilm rule ls HOT/warehouse` | 🔴 즉시 규칙 제거/프리픽스 한정 |
| D-2 | **warm tier 버킷**에 ILM 규칙이 있는가 | `mc ilm rule ls WARM/warm-tier` | 🔴 즉시 제거 (전이 데이터 소실 위험) |
| D-3 | noncurrent expiration 규칙이 **없는가** | 동상 | 🟠 용량 폭증 예정 → 04장 §5 |
| D-4 | `metadata/` 프리픽스가 transition 대상에 포함되는가 | 동상 | 🟠 성능 저하 → 04장 §3 |
| D-5 | 사이트 복제(`mc admin replicate info`)가 켜져 있는가 | 동상 | 🟠 ILM 규칙이 warm으로 전파될 수 있음 → 11 F-14 |
| D-6 | Spark 계정에 `DeleteObjectVersion` 권한이 있는가 | `mc admin policy info` | 🟠 권한 축소 |
| D-7 | 스캐너 속도가 `fastest`로 방치되어 있는가 | `mc admin config get HOT scanner` | 🟡 원복 |
| D-8 | 미완료 멀티파트 정리 규칙이 있는가 | `mc ilm rule ls` | 🟡 숨은 용량 누수 |

### 7.4 전이 여부 실물 확인

```bash
# 임의 구(old) 객체 하나 골라 상세 확인
OBJ=$(mc ls --recursive HOT/warehouse/data/ | head -1 | awk '{print $NF}')
mc stat "HOT/warehouse/data/$OBJ"

# 기대 출력 예 (전이된 경우)
#   Name      : part-00000-....parquet
#   Size      : 128 MiB
#   Tier      : WARM-TIER          ← 이 줄이 전이 증거
#   ...
```

```bash
# 버전까지 포함해서 보기
mc ls --versions --recursive HOT/warehouse/data/ | head -20

# 특정 객체의 복제 상태 헤더 확인
mc stat --json "HOT/warehouse/data/$OBJ" | python3 -m json.tool | grep -i -A2 replic
```

## 8. 변경 전 백업 (필수)

```bash
BK=./backup-$(date +%Y%m%d)
mkdir -p "$BK"

mc ilm rule export  HOT/warehouse   > "$BK/hot-ilm.json"
mc replicate export HOT/warehouse   > "$BK/hot-replication.json"
mc ilm tier ls HOT --json           > "$BK/hot-tiers.json"
mc admin config get HOT scanner     > "$BK/hot-scanner.txt"
mc admin policy info HOT spark-rw   > "$BK/policy-spark.json" 2>/dev/null

# 복원 예
# mc ilm rule import HOT/warehouse < "$BK/hot-ilm.json"
# mc replicate import HOT/warehouse < "$BK/hot-replication.json"
```

| 백업 대상 | 복원 가능 | 비고 |
|---|---|---|
| ILM 규칙 | ✅ | import로 복원 |
| Replication 규칙 | ✅ | import로 복원 |
| Tier 정의 | ⚠️ 수동 재등록 | 시크릿은 export되지 않음 |
| Scanner 설정 | ✅ | 수동 재설정 |
| **삭제된 객체** | ❌ | 백업으로 복구 불가 — 그래서 만료 규칙이 위험 |

## 9. 구성 검증 체크리스트

| # | 항목 | 명령 | 기대 | ✅ |
|---|---|---|---|---|
| V-1 | hot/warm 접속 | `mc admin info HOT/WARM` | Online | |
| V-2 | 버킷 존재 | `mc ls HOT; mc ls WARM` | 대상 버킷 존재 | |
| V-3 | Versioning | `mc version info` | Enabled (hot, warm/warehouse) | |
| V-4 | Tier 등록 | `mc ilm tier ls HOT` | WARM-TIER 존재 | |
| V-5 | Tier 접근 | 테스트 객체 전이 후 `mc cat` | 정상 읽힘 | |
| V-6 | Replication 규칙 | `mc replicate ls HOT/warehouse` | Enabled | |
| V-7 | Replication 실동작 | 테스트 객체 PUT → warm에서 확인 | 수분 내 존재 | |
| V-8 | ILM 규칙 | `mc ilm rule ls HOT/warehouse` | 04장 설계대로 | |
| V-9 | warm-tier 규칙 없음 | `mc ilm rule ls WARM/warm-tier` | 규칙 없음 ⚠️ | |
| V-10 | Spark 계정 접근 | Spark에서 read/write | 성공 | |
| V-11 | 스캐너 설정 | `mc admin config get HOT scanner` | 의도한 값 | |
| V-12 | 메트릭 수집 | Prometheus target | UP | |

### V-7 복제 실동작 스모크 테스트

```bash
echo "replication-smoke-$(date +%s)" > /tmp/smoke.txt
mc cp /tmp/smoke.txt HOT/warehouse/_smoke/smoke.txt

# 즉시 상태 확인 (PENDING 기대)
mc stat --json HOT/warehouse/_smoke/smoke.txt | grep -i replic

# 수십 초~수 분 후
mc stat --json HOT/warehouse/_smoke/smoke.txt | grep -i replic   # COMPLETED 기대
mc ls WARM/warehouse/_smoke/                                     # 존재 기대
mc cat WARM/warehouse/_smoke/smoke.txt                           # 내용 일치

# 정리
mc rm HOT/warehouse/_smoke/smoke.txt
```

| 결과 | 해석 |
|---|---|
| 수 분 내 COMPLETED + warm 존재 | ✅ 정상 |
| 계속 PENDING | 대상 접근 실패/큐 적체 → 09장 §4 |
| FAILED | 자격증명/권한/버저닝 문제 → 12장 FAQ |
| warm에 없는데 COMPLETED | 대상 버킷 오지정 확인 |

## 10. 롤백 절차

| 되돌릴 것 | 명령 | 주의 |
|---|---|---|
| ILM 규칙 | `mc ilm rule rm HOT/warehouse --id <RULE_ID>` 또는 `mc ilm rule import` | 이미 만료된 객체는 복구 불가 ⚠️ |
| Replication 규칙 | `mc replicate rm HOT/warehouse --id <ARN/ID>` 🔍 | 이미 복제된 객체는 warm에 잔존 |
| Tier | `mc ilm tier rm HOT WARM-TIER` 🔍 | ⚠️ 전이 객체가 있으면 **절대 실행 금지** |
| Scanner 속도 | `mc admin config set HOT scanner speed=default` | 테스트 종료 시 필수 |
| Versioning | `mc version suspend HOT/warehouse` | 기존 버전은 남음. 완전 OFF 불가 |

### ⚠️ 전이 객체가 있는 상태에서 tier를 지우면

hot의 stub이 참조할 대상을 잃어 **해당 객체 전부 조회 불가**가 됩니다. 복구하려면 동일 이름·동일 대상으로 tier를 재등록해야 하며, 원격 데이터가 이미 정리되었다면 복구 불가입니다.

전이 객체 수 확인 후 판단하십시오.

```bash
mc ilm tier info HOT WARM-TIER      # 전이된 객체 수/용량 🔍
```

→ 다음: [04. ILM 정책 설계](../04-ilm-policy-design/)
