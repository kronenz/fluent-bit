#!/usr/bin/env bash
# Re-pull kubeconfig from remote minikube and update local context "minikube-remote".
# Run after the remote minikube cluster is restarted (the published API port changes).
set -euo pipefail

SSH_HOST="${SSH_HOST:-minikube-host}"
REMOTE_IP="${REMOTE_IP:-192.168.101.197}"
CTX_NAME="${CTX_NAME:-minikube-remote}"
LOCAL_KUBECFG="${LOCAL_KUBECFG:-$HOME/.kube/config}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[1/5] Resolving API port on remote..."
PORT=$(ssh "$SSH_HOST" 'sg docker -c "docker port minikube 8443"' | head -1 | awk -F: '{print $NF}')
[[ -z "$PORT" ]] && { echo "could not resolve port — is minikube running?" >&2; exit 1; }
SERVER="https://${REMOTE_IP}:${PORT}"
echo "    server URL: $SERVER"

echo "[2/5] Pulling flattened kubeconfig from remote..."
ssh "$SSH_HOST" 'sg docker -c "minikube kubectl -- config view --flatten --raw --minify"' > "$WORK/kc.yaml"

echo "[3/5] Renaming entries to '$CTX_NAME' and updating server URL..."
KUBECONFIG="$WORK/kc.yaml" kubectl config rename-context minikube "$CTX_NAME" >/dev/null
KUBECONFIG="$WORK/kc.yaml" kubectl config set-cluster minikube --server="$SERVER" --tls-server-name=minikube >/dev/null
sed -i \
  -e "s/^  name: minikube\$/  name: $CTX_NAME/" \
  -e "s/^- name: minikube\$/- name: $CTX_NAME/" \
  -e "s/cluster: minikube\$/cluster: $CTX_NAME/" \
  -e "s/user: minikube\$/user: $CTX_NAME/" \
  "$WORK/kc.yaml"

echo "[4/5] Backing up local kubeconfig and merging..."
cp "$LOCAL_KUBECFG" "/tmp/kube-config.bak.$(date +%s)"
# Drop any pre-existing entries with this name first
KUBECONFIG="$LOCAL_KUBECFG" kubectl config delete-context "$CTX_NAME" 2>/dev/null || true
KUBECONFIG="$LOCAL_KUBECFG" kubectl config delete-cluster "$CTX_NAME" 2>/dev/null || true
KUBECONFIG="$LOCAL_KUBECFG" kubectl config delete-user "$CTX_NAME" 2>/dev/null || true
KUBECONFIG="$LOCAL_KUBECFG:$WORK/kc.yaml" kubectl config view --flatten --raw > "$WORK/merged.yaml"
cp "$WORK/merged.yaml" "$LOCAL_KUBECFG"
chmod 600 "$LOCAL_KUBECFG"

echo "[5/5] Verifying..."
kubectl --context="$CTX_NAME" get nodes
echo "OK — context '$CTX_NAME' updated."
