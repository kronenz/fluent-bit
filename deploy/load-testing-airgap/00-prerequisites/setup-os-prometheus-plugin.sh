#!/usr/bin/env bash
# OpenSearch prometheus-exporter plugin 자동 설치.
#
# 흐름:
#   1. plugin .zip 다운로드 (인터넷 zone) — 폐쇄망 host 는 Nexus 에서 받기
#   2. monitoring ns 에 ConfigMap 생성
#   3. helm upgrade (extraInitContainers 추가)
#   4. ServiceMonitor 적용
#   5. 검증
#
# 사용:
#   bash deploy/load-testing-airgap/00-prerequisites/setup-os-prometheus-plugin.sh
#
# 폐쇄망 swap:
#   PLUGIN_URL=https://nexus.intranet:8082/repository/opensearch-plugins/prometheus-exporter-2.19.1.0.zip
#
set -euo pipefail

CTX=${CTX:-$(kubectl config current-context)}
NS=${NS:-monitoring}
RELEASE=${RELEASE:-opensearch-lt}
PLUGIN_VER=${PLUGIN_VER:-2.19.1.0}
PLUGIN_URL=${PLUGIN_URL:-https://github.com/aiven/prometheus-exporter-plugin-for-opensearch/releases/download/${PLUGIN_VER}/prometheus-exporter-${PLUGIN_VER}.zip}
TMP=${TMP:-/tmp/prometheus-exporter-${PLUGIN_VER}.zip}

echo "[1/5] downloading plugin → $TMP"
if [ ! -f "$TMP" ]; then
  curl -fsSL --max-time 60 "$PLUGIN_URL" -o "$TMP"
fi
ls -la "$TMP"

echo "[2/5] ConfigMap 생성"
kubectl --context="$CTX" -n "$NS" create configmap opensearch-prometheus-plugin \
  --from-file=prometheus-exporter-${PLUGIN_VER}.zip="$TMP" \
  --dry-run=client -o yaml | kubectl --context="$CTX" apply -f -

echo "[3/5] helm upgrade (extraInitContainers 추가)"
helm --kube-context="$CTX" upgrade "$RELEASE" opensearch/opensearch \
  --version 2.32.0 -n "$NS" --reuse-values \
  -f "$(dirname "$0")/opensearch-helm-values.yaml"

echo "[4/5] ServiceMonitor 적용"
kubectl --context="$CTX" apply -f "$(dirname "$0")/opensearch-servicemonitor.yaml"

echo "[5/5] OS pod 재시작 + plugin endpoint 검증"
kubectl --context="$CTX" -n "$NS" rollout status sts/opensearch-lt-node --timeout=300s
sleep 5
kubectl --context="$CTX" -n "$NS" exec opensearch-lt-node-0 -- \
  curl -s localhost:9200/_prometheus/metrics | head -10

echo ""
echo "================ 설치 완료 ================"
echo "Prometheus 가 30s 안에 새 metric 을 scrape 함 (kps-prometheus)."
echo "확인: kubectl -n monitoring port-forward svc/kps-prometheus 19090:9090"
echo "      → http://localhost:19090 → 'opensearch_cluster_status' 검색"
