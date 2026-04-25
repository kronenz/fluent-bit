#!/usr/bin/env bash
# Tear down everything provisioned under deploy/load-testing/.
# Use with care — this deletes the monitoring/load-test namespaces and PVCs.
set -euo pipefail

CTX="${CTX:-minikube-remote}"

read -p "This will delete monitoring + load-test namespaces and PVCs on context '$CTX'. Continue? [y/N] " ans
[[ "$ans" =~ ^[yY]$ ]] || { echo "aborted"; exit 1; }

cd "$(dirname "$0")"

echo "[1/4] Removing test jobs..."
kubectl --context="$CTX" delete -f 04-test-jobs/ --ignore-not-found || true

echo "[2/4] Removing load generators..."
kubectl --context="$CTX" delete -f 03-load-generators/ --ignore-not-found || true

echo "[3/4] Uninstalling helm releases..."
helm --kube-context="$CTX" -n monitoring uninstall fluent-bit-lt 2>/dev/null || true
helm --kube-context="$CTX" -n monitoring uninstall opensearch-lt 2>/dev/null || true
helm --kube-context="$CTX" -n monitoring uninstall kps 2>/dev/null || true

echo "[4/4] Deleting namespaces (and their PVCs)..."
kubectl --context="$CTX" delete ns load-test --ignore-not-found
kubectl --context="$CTX" delete ns monitoring --ignore-not-found
kubectl --context="$CTX" delete ns kburner --ignore-not-found 2>/dev/null || true

echo "Done."
