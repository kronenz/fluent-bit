#!/usr/bin/env bash
# Packet Drop 묶음 검증 게이트 (plan §6 / AC §2):
#   1) 구조: nodename 변수 단일(multi=false,includeAll=false), L0만 cross-node(nodename 변수 없음)
#   2) 링크 무결성: 모든 dashboard/data link의 /d/<uid> 타겟이 묶음 안에 실재
#   3) 스키마: 각 JSON을 Grafana API로 POST(status:success) 후 DELETE
# 사용: ops/dashboards/packet-drop/validate.sh  (GRAFANA_USER/GRAFANA_PASS env 선택)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
GHOST="${GRAFANA_HOST:-nic-grafana.miribit.lab}"
GIP="${GRAFANA_IP:-192.168.50.21}"
GUSER="${GRAFANA_USER:-admin}"; GPASS="${GRAFANA_PASS:-nicdrop-2026}"
CURL=(curl -k -s --resolve "${GHOST}:443:${GIP}" -u "${GUSER}:${GPASS}")
fail=0

echo "== 1) 구조 + 2) 링크 무결성 =="
python3 - "$DIR" <<'PY'
import json,sys,glob,os,re
d=sys.argv[1]; files=sorted(glob.glob(f"{d}/*.json"))
uids=set(); per={}
for f in files:
    j=json.load(open(f)); uids.add(j["uid"]); per[f]=j
ok=True
for f,j in per.items():
    name=os.path.basename(f); is_l0 = j["uid"].endswith("l0-fleet")
    nn=[v for v in j["templating"]["list"] if v.get("name")=="nodename"]
    if is_l0:
        if nn: print(f"  ✗ {name}: L0인데 nodename 변수 있음(cross-node 오염)"); ok=False
    else:
        if not nn: print(f"  ✗ {name}: nodename 변수 없음"); ok=False
        else:
            v=nn[0]
            if v.get("multi") or v.get("includeAll"):
                print(f"  ✗ {name}: nodename multi/All 허용됨(single 위반)"); ok=False
    # 링크 타겟 수집
    targets=set(re.findall(r"/d/([a-z0-9-]+)", json.dumps(j)))
    ext=[t for t in targets if t not in uids]
    if ext: print(f"  ✗ {name}: 미존재 링크 타겟 {ext}"); ok=False
print("  uids:", sorted(uids))
print("  STRUCT+LINKS:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
PY
[ $? -ne 0 ] && fail=1

echo "== 3) Grafana 스키마 import 검증 =="
for f in "$DIR"/*.json; do
  payload=$(python3 -c "import json,sys;d=json.load(open('$f'));d['id']=None;print(json.dumps({'dashboard':d,'overwrite':True}))")
  st=$(printf '%s' "$payload" | "${CURL[@]}" -H 'Content-Type: application/json' -X POST "https://${GHOST}/api/dashboards/db" -d @- | python3 -c "import sys,json;print(json.load(sys.stdin).get('status','ERR'))" 2>/dev/null)
  uid=$(python3 -c "import json;print(json.load(open('$f'))['uid'])")
  printf "  %-18s => %s\n" "$(basename "$f")" "$st"
  [ "$st" != "success" ] && fail=1
  "${CURL[@]}" -X DELETE "https://${GHOST}/api/dashboards/uid/${uid}" >/dev/null
done

echo
[ $fail -eq 0 ] && echo "✅ ALL PASS" || echo "❌ FAIL"
exit $fail
