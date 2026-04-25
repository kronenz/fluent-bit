#!/usr/bin/env bash
# Install OpenSearch (single-node) + Fluent-bit DaemonSet into `monitoring` namespace.
# Tier 2 — apply only after Tier 1 (monitoring core) is healthy.
set -euo pipefail

CTX="${CTX:-minikube-remote}"
NS="${NS:-monitoring}"

# Pinned to early 2025 helm artifact repository versions.
OS_CHART_VERSION="${OS_CHART_VERSION:-2.32.0}"   # → OpenSearch 2.19.1
FB_CHART_VERSION="${FB_CHART_VERSION:-0.55.0}"   # → Fluent-bit 4.2.3

cd "$(dirname "$0")"

echo "[1/4] Adding helm repos..."
helm repo add opensearch https://opensearch-project.github.io/helm-charts/ >/dev/null 2>&1 || true
helm repo add fluent https://fluent.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update opensearch fluent >/dev/null

echo "[2/4] Installing OpenSearch (single-node) chart=$OS_CHART_VERSION ..."
helm --kube-context="$CTX" upgrade --install opensearch-lt \
    opensearch/opensearch \
    --version "$OS_CHART_VERSION" \
    -n "$NS" \
    -f opensearch-values.yaml \
    --wait --timeout=10m

echo "[3/4] Installing Fluent-bit DaemonSet chart=$FB_CHART_VERSION ..."
helm --kube-context="$CTX" upgrade --install fluent-bit-lt \
    fluent/fluent-bit \
    --version "$FB_CHART_VERSION" \
    -n "$NS" \
    -f fluent-bit-values.yaml \
    --wait --timeout=5m

echo "[4/5] Deploying OpenSearch metrics exporter..."
kubectl --context="$CTX" apply -f opensearch-exporter.yaml
kubectl --context="$CTX" -n "$NS" rollout status deploy/opensearch-exporter --timeout=2m

echo "[5/5] Verifying..."
kubectl --context="$CTX" -n "$NS" get pods -l 'app.kubernetes.io/name in (opensearch,fluent-bit)'
sleep 5
echo "--- OpenSearch cluster health ---"
kubectl --context="$CTX" -n "$NS" exec -ti svc/opensearch-lt-node -- curl -s http://localhost:9200/_cluster/health | head -1 || true
echo "--- Fluent-bit metrics endpoint check ---"
kubectl --context="$CTX" -n "$NS" exec -ti ds/fluent-bit-lt -- curl -s http://localhost:2020/api/v2/metrics/prometheus | head -5 || true

cat <<EOF

Done.

Test log flow:
  kubectl --context=$CTX -n load-test apply -f ../03-load-generators/flog.yaml
  # wait 30s
  kubectl --context=$CTX -n monitoring exec svc/opensearch-lt-node -- \\
    curl -s 'http://localhost:9200/logs-fb-*/_count' | jq

Uninstall:
  helm --kube-context=$CTX -n $NS uninstall fluent-bit-lt opensearch-lt

EOF
