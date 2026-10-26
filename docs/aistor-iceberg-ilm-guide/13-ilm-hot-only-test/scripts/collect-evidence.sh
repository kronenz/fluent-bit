#!/usr/bin/env bash
# collect-evidence.sh <out_dir> — 테스트 증적을 한 디렉터리로 모은다
#   1) OpenSearch 의 ilmtest-* 인덱스 → JSONL (Fluent Bit 이 적재한 앱·audit 로그)
#   2) 남아 있는 Pod 로그 → JSONL (OpenSearch 미사용·유실 대비)
#   3) ILM 규칙 · tier · 버킷 현황 스냅샷
# 사용: source config.env && OS_URL=https://opensearch:9200 OS_AUTH=user:pass ./collect-evidence.sh evidence/20261026
set -euo pipefail
: "${HOT_ALIAS:?config.env 를 source 하세요}"
OUT=${1:?out_dir}; mkdir -p "$OUT"

if [[ -n "${OS_URL:-}" ]]; then
  for idx in ilmtest-app ilmtest-audit ilmtest-alert; do
    echo "== OpenSearch $idx"
    python3 - "$OS_URL" "${OS_AUTH:-}" "$idx" > "$OUT/os-${idx}.jsonl" <<'PY'
import base64, json, ssl, sys, urllib.request
url, auth, idx = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
ctx = ssl._create_unverified_context()   # 테스트 환경 자체서명 인증서 허용
def req(path, body):
    r = urllib.request.Request(url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    if auth:
        r.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    return json.load(urllib.request.urlopen(r, context=ctx))
res = req("/{}/_search?scroll=5m".format(idx), {"size": 5000, "sort": ["_doc"]})
while res["hits"]["hits"]:
    for h in res["hits"]["hits"]:
        print(json.dumps(h["_source"], ensure_ascii=False))
    res = req("/_search/scroll", {"scroll": "5m", "scroll_id": res["_scroll_id"]})
PY
    wc -l "$OUT/os-${idx}.jsonl"
  done
fi

echo "== Pod 로그 (ns=$K8S_NS)"
for pod in $(kubectl -n "$K8S_NS" get pods -l app.kubernetes.io/part-of=ilmtest -o name); do
  kubectl -n "$K8S_NS" logs "$pod" --all-containers 2>/dev/null | grep '^{"event"' || true
done > "$OUT/pods.jsonl"
wc -l "$OUT/pods.jsonl"

echo "== S3 현황"
mc ilm rule export "${HOT_ALIAS}/${BUCKET}"        > "$OUT/ilm-rules.json"   || true
mc ilm rule ls "${HOT_ALIAS}/${BUCKET}"            > "$OUT/ilm-rules.txt"    || true
mc ilm tier ls "$HOT_ALIAS"                         > "$OUT/tier-ls.txt"      || true
mc admin info "$HOT_ALIAS"                          > "$OUT/hot-info.txt"     || true
mc du --versions "${HOT_ALIAS}/${BUCKET}/${TABLE_PREFIX}/" > "$OUT/hot-du.txt" || true
mc ilm rule ls "${WARM_ALIAS}/${WARM_TIER_BUCKET}" > "$OUT/warm-tier-rules.txt" 2>&1 || true
python3 state_snapshot.py                            > "$OUT/state-final.jsonl" || true

echo "== 완료: $OUT  →  python3 judge.py $OUT"
