#!/usr/bin/env bash
# Install kube-prometheus-stack into the `monitoring` namespace.
# Idempotent: re-run to upgrade values.
set -euo pipefail

CTX="${CTX:-minikube-remote}"
NS="${NS:-monitoring}"
RELEASE="${RELEASE:-kps}"
CHART_VERSION="${CHART_VERSION:-76.5.1}"   # 2025 early-Q3 stable, app v0.84.1

cd "$(dirname "$0")"

echo "[1/4] Ensuring helm repo prometheus-community is added..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update prometheus-community >/dev/null

echo "[2/4] Ensuring namespace '$NS' exists..."
kubectl --context="$CTX" get ns "$NS" >/dev/null 2>&1 \
  || kubectl --context="$CTX" create ns "$NS"

echo "[3/4] helm upgrade --install $RELEASE..."
VERSION_ARG=()
[[ -n "$CHART_VERSION" ]] && VERSION_ARG=(--version "$CHART_VERSION")
helm --kube-context="$CTX" upgrade --install "$RELEASE" \
    prometheus-community/kube-prometheus-stack \
    -n "$NS" \
    -f values.yaml \
    --wait --timeout=10m \
    "${VERSION_ARG[@]}"

echo "[4/4] Verifying..."
kubectl --context="$CTX" -n "$NS" get pods
kubectl --context="$CTX" -n "$NS" get svc | grep -E 'NodePort|grafana|prometheus|alertmanager' || true

cat <<EOF

Done. Quick access:
  Grafana:      http://192.168.101.197:30030  (admin / admin)
  Prometheus:   http://192.168.101.197:30090
  Ingress host: add 'grafana.local 192.168.101.197' to /etc/hosts (then http://grafana.local)

Validate ServiceMonitor pickup:
  kubectl --context=$CTX -n $NS get servicemonitors

Uninstall:
  helm --kube-context=$CTX -n $NS uninstall $RELEASE

EOF
