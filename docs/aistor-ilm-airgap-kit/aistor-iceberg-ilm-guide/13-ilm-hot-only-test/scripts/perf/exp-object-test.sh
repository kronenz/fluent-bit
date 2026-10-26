#!/usr/bin/env bash
# exp-object-test.sh setup|newver|expire|verify|status — Hot 1d → Warm → 기한 삭제를 객체 단위로 즉시 재현 (E-1 · E-2)
# toolbox 에서 실행 (MC_HOST_HOT · MC_HOST_WARM 관리자, s3_backdate.py 같은 디렉터리).
#
# 실제 일정:  0일 PUT ─(1일)→ Warm 전이 ─(EXPIRE_DAYS)→ current 만료 ─(NONCURRENT_EXPIRE_DAYS)→ Warm 실데이터 삭제
# 재현 방법: 객체 mtime 을 과거로 써서(s3_backdate.py) 일수 경과를 만들고, 규칙을 두 단계로 건다.
#   setup  : Transition 1d 만 → Scanner 가 age ≥ 1 객체를 Warm 으로 (실제로 1일째 일어나는 일)
#   expire : Transition 1d + Expiration EXPIRE_DAYS + Noncurrent 1d (+ 고아 DM 정리) → 만료 일어나는 일
#   (처음부터 두 규칙을 같이 걸면 age 6 객체는 전이 없이 바로 만료된다 — 실제 시간 흐름과 다르다)
# Warm 쪽은 전용 tier WARM-EXP (warm-tier 버킷 exp/ prefix) 로 분리해 정확히 센다.
set -euo pipefail
cd "$(dirname "$0")"
VB=${VB:-ilm-age-test}     # Versioning ON (운영과 같은 설정)
NB=${NB:-ilm-age-nv}       # Versioning OFF (비교)
TIER=${EXP_TIER:-WARM-EXP}
EXPIRE_DAYS=${EXPIRE_DAYS:-5}
EV=${EVIDENCE_DIR:-/shared/evidence/exp}
mkdir -p "$EV"

rules() {   # rules <bucket> <phase>
  python3 - "$1" "$2" "$TIER" "$EXPIRE_DAYS" <<'PY'
import json, sys
bucket, phase, tier, exp = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
r1 = {"ID": "e1-transition", "Status": "Enabled", "Filter": {"Prefix": "obj/"},
      "Transition": {"Days": 1, "StorageClass": tier}}
rules = [r1]
if phase == "expire":
    r1["Expiration"] = {"Days": exp}
    rules += [{"ID": "e3-noncurrent", "Status": "Enabled", "Filter": {"Prefix": "obj/"},
               "NoncurrentVersionExpiration": {"NoncurrentDays": 1}},
              {"ID": "e6-dm", "Status": "Enabled", "Filter": {"Prefix": "obj/"},
               "Expiration": {"ExpiredObjectDeleteMarker": True}}]
print(json.dumps({"Rules": rules}))
PY
}

status() {  # 한 줄 JSON — 버킷별 키·버전·storageClass, Warm exp/ 객체 수
  python3 - "$VB" "$NB" "${1:-status}" <<'PY'
import datetime, json, subprocess, sys
def ls(target, versions):
    a = ["mc", "ls", "--recursive", "--json"] + (["--versions"] if versions else []) + [target]
    out = subprocess.run(a, stdout=subprocess.PIPE, universal_newlines=True).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip().startswith("{")]
rec = {"event": "ilmtest.expobj", "phase": sys.argv[3],
       "ts": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z", "buckets": {}}
for b in sys.argv[1:3]:
    vs = ls("HOT/{}/obj/".format(b), True)
    keys = {}
    for v in vs:
        k = v["key"]
        keys.setdefault(k, []).append({"ord": v.get("versionOrdinal"), "dm": bool(v.get("isDeleteMarker")),
                                      "sc": v.get("storageClass") or "STANDARD", "mtime": v.get("lastModified", "")[:19]})
    for k in keys:
        keys[k].sort(key=lambda x: -(x["ord"] or 0))
    rec["buckets"][b] = keys
rec["warm_exp_objects"] = len([o for o in ls("WARM/warm-tier/exp/", False) if o.get("type") == "file"])
# Iceberg 시험 테이블 (E-3/E-4): prefix 별 버전 분포 · Warm expi/ 객체 수
import os
rec["iceberg"] = {}
for p in os.environ.get("EXP_ICEBERG_PREFIXES", "warehouse/ilmexp.db/events/data/ warehouse/ilmexp2.db/events/data/").split():
    c = {}
    for v in ls("HOT/" + p, True):
        part = v["key"].split("/")[0]
        kind = "DM" if v.get("isDeleteMarker") else (v.get("storageClass") or "STANDARD")
        c.setdefault(part, {}).setdefault(kind, 0)
        c[part][kind] += 1
    rec["iceberg"][p] = c
rec["warm_expi_objects"] = len([o for o in ls("WARM/warm-tier/expi/", False) if o.get("type") == "file"])
print(json.dumps(rec, ensure_ascii=False))
PY
}

case "${1:-status}" in
  setup)
    mc mb -p "HOT/$VB" "HOT/$NB" >/dev/null
    mc version enable "HOT/$VB" >/dev/null
    for b in "$VB" "$NB"; do
      for a in 0.5 2 4.5 6; do python3 -W ignore s3_backdate.py put "$b" "obj/age-$a" "$a" >/dev/null; done
    done
    python3 -W ignore s3_backdate.py put "$VB" obj/nc 6 >/dev/null          # v1: 6일 전 — Warm 으로 전이될 버전
    python3 -W ignore s3_backdate.py put "$VB" obj/ow 3 >/dev/null          # 비교: 일반 덮어쓰기로 비현행이 되는 전이 버전
    rules "$VB" setup | mc ilm rule import "HOT/$VB" >/dev/null
    rules "$NB" setup | mc ilm rule import "HOT/$NB" >/dev/null
    status setup | tee -a "$EV/ilmtest.expobj.jsonl" ;;
  newver)
    # nc 의 새 버전(3일 전) → v1 은 '3일 전부터 비현행' 이 된다 → Noncurrent 1d 만료 대상
    python3 -W ignore s3_backdate.py put "$VB" obj/nc 3 >/dev/null
    python3 -W ignore s3_backdate.py put "$VB" obj/ow 0 >/dev/null          # 지금 시각 새 버전 → v1 은 방금 비현행 (만료 아님). mc pipe 는 버퍼가 커서 toolbox OOM
    status newver | tee -a "$EV/ilmtest.expobj.jsonl" ;;
  expire)
    rules "$VB" expire | mc ilm rule import "HOT/$VB" >/dev/null
    rules "$NB" expire | mc ilm rule import "HOT/$NB" >/dev/null
    mc ilm rule ls "HOT/$VB"
    status expire-applied | tee -a "$EV/ilmtest.expobj.jsonl" ;;
  verify)
    # 전이된 비현행 버전이 실제로 읽히는가 — ILM 만료로 생긴 비현행(age-6) vs 일반 덮어쓰기 비현행(ow)
    python3 - "$VB" <<'PY' | tee -a "$EV/ilmtest.expread.jsonl"
import datetime, json, subprocess, sys
vb = sys.argv[1]
out = {"event": "ilmtest.expread", "ts": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z", "cases": {}}
for key, why in (("obj/age-6", "ILM current Expiration 으로 비현행이 된 전이 버전"), ("obj/ow", "일반 덮어쓰기로 비현행이 된 전이 버전")):
    vs = [json.loads(l) for l in subprocess.run(["mc", "ls", "--versions", "--json", "HOT/{}/{}".format(vb, key)],
          stdout=subprocess.PIPE, universal_newlines=True).stdout.splitlines() if l.strip()]
    if not vs:
        out["cases"][key] = {"why": why, "versions": 0}
        continue
    top = max(x.get("versionOrdinal", 0) for x in vs)
    for v in [v for v in vs if not v.get("isDeleteMarker") and v.get("versionOrdinal") != top]:
        r = subprocess.run(["mc", "cat", "--version-id", v["versionId"], "HOT/{}/{}".format(vb, key)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out["cases"][key] = {"why": why, "storageClass": v.get("storageClass"), "readable": r.returncode == 0,
                             "error": r.stderr.strip()[-160:] if r.returncode else None}
print(json.dumps(out, ensure_ascii=False))
PY
    ;;
  status)
    status "${2:-status}" | tee -a "$EV/ilmtest.expobj.jsonl" ;;
esac
