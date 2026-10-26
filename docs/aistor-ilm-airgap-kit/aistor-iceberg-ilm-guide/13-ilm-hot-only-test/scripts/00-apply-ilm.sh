#!/usr/bin/env bash
# 00-apply-ilm.sh — Hot 버킷 ILM 규칙 백업 → 적용 → 위험 규칙 검사
# 사용: source config.env && ./00-apply-ilm.sh [--dry-run]
#   MERGE=1          : 기존 규칙을 지우지 않고 추가한다 (같은 ID 만 교체). `mc ilm rule import` 는 버킷 규칙 전체를 대체한다
#   RULE_ID_PREFIX=x : 규칙 ID 앞에 붙인다 — 한 버킷에 테이블별 규칙을 여러 벌 둘 때 (예: perf-)
#   EXPIRE_DAYS=n    : data/ current Expiration(R-4) 추가 — Iceberg 테이블에는 금지(파일 유실). 기한 삭제 시험용이며
#                      ALLOW_CURRENT_EXPIRATION=1 이 없으면 위험 규칙 검사에서 실패한다
set -euo pipefail

: "${HOT_ALIAS:?config.env 를 source 하세요}"
DRY_RUN=0; [[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1
TARGET="${HOT_ALIAS}/${BUCKET}"
TS=$(date +%Y%m%dT%H%M%S)
mkdir -p backup

echo "== 0) 사전 확인"
{ mc ilm tier ls "$HOT_ALIAS" 2>/dev/null || mc admin tier ls "$HOT_ALIAS"; } | grep -q "$TIER_NAME" \
  || { echo "tier '$TIER_NAME' 가 $HOT_ALIAS 에 없습니다 (mc ilm tier add 먼저)"; exit 1; }
mc version info "$TARGET"

echo "== 1) 기존 규칙 백업 → backup/ilm-${BUCKET}-${TS}.json"
mc ilm rule export "$TARGET" > "backup/ilm-${BUCKET}-${TS}.json" 2>/dev/null || echo '{}' > "backup/ilm-${BUCKET}-${TS}.json"

echo "== 2) 규칙 생성"
RULES_FILE="backup/ilm-${BUCKET}-${TS}.new.json"
python3 - "$RULES_FILE" "backup/ilm-${BUCKET}-${TS}.json" <<'PY'
import json, os, sys
p = os.environ["TABLE_PREFIX"].rstrip("/")
rid = os.environ.get("RULE_ID_PREFIX", "")
rules = [{
    "ID": rid + "r1-data-transition",
    "Status": "Enabled",
    "Filter": {"Prefix": f"{p}/data/"},
    "Transition": {"Days": int(os.environ["TRANSITION_DAYS"]), "StorageClass": os.environ["TIER_NAME"]},
}]
if os.environ.get("VERSIONING", "on") == "on":
    rules += [
        {"ID": rid + "r3-data-noncurrent-expire", "Status": "Enabled",
         "Filter": {"Prefix": f"{p}/data/"},
         "NoncurrentVersionExpiration": {"NoncurrentDays": max(1, int(os.environ["NONCURRENT_EXPIRE_DAYS"]))}},
        {"ID": rid + "r6-expired-delete-marker", "Status": "Enabled",
         "Filter": {"Prefix": f"{p}/"},
         "Expiration": {"ExpiredObjectDeleteMarker": True}},
    ]
if os.environ.get("EXPIRE_DAYS"):
    rules[0]["Expiration"] = {"Days": int(os.environ["EXPIRE_DAYS"])}   # 같은 규칙에 Transition + Expiration
# R-2(metadata/) 는 의도적으로 규칙 없음
if os.environ.get("MERGE") == "1":
    try:
        old = json.load(open(sys.argv[2])).get("Rules", [])
    except ValueError:
        old = []
    ids = {r["ID"] for r in rules}
    rules = [r for r in old if r.get("ID") not in ids] + rules
json.dump({"Rules": rules}, open(sys.argv[1], "w"), indent=2)
PY
cat "$RULES_FILE"; echo

# 위험 규칙 검사 — 적용 전(생성한 규칙 = 병합 결과)과 적용 후(실제 버킷) 두 번 한다
check_rules() {
python3 - "$1" <<'PY'
import json, os, sys
p = os.environ["TABLE_PREFIX"].rstrip("/")
rules = json.load(open(sys.argv[1])).get("Rules", [])
bad = []
for r in rules:
    pre = (r.get("Filter") or {}).get("Prefix", r.get("Prefix", ""))
    exp = r.get("Expiration") or {}
    if exp.get("Days") or exp.get("Date"):
        bad.append(f"{r['ID']}: current Expiration (prefix='{pre}') — Iceberg 데이터 유실 위험")
    if exp.get("ExpiredObjectAllVersions"):
        bad.append(f"{r['ID']}: ExpiredObjectAllVersions — 버전 안전망 무력화")
    if pre in ("", "/") and (r.get("Transition") or exp.get("Days")):
        bad.append(f"{r['ID']}: 버킷 전체 대상 Transition/Expiration")
    if pre.startswith(f"{p}/metadata"):
        bad.append(f"{r['ID']}: metadata/ 대상 규칙")
print("\n".join(bad) if bad else "OK — 위험 규칙 없음")
if bad and os.environ.get("ALLOW_CURRENT_EXPIRATION") == "1" and all("current Expiration" in b for b in bad):
    print("⚠️  ALLOW_CURRENT_EXPIRATION=1 — 시험용으로 허용 (Iceberg 운영 테이블에는 쓰지 말 것)")
    sys.exit(0)
sys.exit(1 if bad else 0)
PY
}

echo "== 3) 위험 규칙 검사 (적용 전 — 병합 결과 전체)"
check_rules "$RULES_FILE" || { echo "적용하지 않았습니다. 위 규칙을 정리한 뒤 다시 실행하세요."; exit 1; }

if [[ $DRY_RUN -eq 0 ]]; then
  echo "== 4) 적용 ($([[ "${MERGE:-0}" == 1 ]] && echo "기존 규칙 유지 + 추가" || echo "기존 규칙을 대체합니다"))"
  mc ilm rule import "$TARGET" < "$RULES_FILE"
  mc ilm rule export "$TARGET" > "backup/ilm-${BUCKET}-${TS}.applied.json"
  echo "   적용 후 재검사"; check_rules "backup/ilm-${BUCKET}-${TS}.applied.json"
fi

echo "== 5) Warm tier 버킷 규칙 없음 확인"
WARM_RULES=$(mc ilm rule ls "${WARM_ALIAS}/${WARM_TIER_BUCKET}" 2>&1 || true)   # 규칙이 없으면 mc 가 에러로 종료한다
if grep -qiE "no lifecycle|not found|does not exist" <<<"$WARM_RULES"; then
  echo "OK — ${WARM_ALIAS}/${WARM_TIER_BUCKET} 규칙 없음"
else
  echo "$WARM_RULES"
  echo "확인 필요: Warm tier 버킷에 규칙이 보이면 즉시 제거하세요 (stub 만 남고 실데이터 소실)"
fi

echo "== 6) 현재 규칙"
mc ilm rule ls "$TARGET"
