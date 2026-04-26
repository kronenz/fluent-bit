#!/usr/bin/env bash
# Idempotent minikube setup for load testing on Ubuntu 24.04
# Reads sudo password from $SUDOPASS env var
set -euo pipefail

if [[ -z "${SUDOPASS:-}" ]]; then
    echo "ERROR: SUDOPASS env var not set" >&2
    exit 1
fi

# Wrapper: feed password to stdin for every sudo call. Avoids any pipe collisions.
s() { echo "$SUDOPASS" | sudo -S -p '' "$@"; }

log() { echo -e "\n\033[1;36m=== $* ===\033[0m"; }

MINIKUBE_VERSION="${MINIKUBE_VERSION:-latest}"
MINIKUBE_CPUS="${MINIKUBE_CPUS:-8}"
MINIKUBE_MEMORY="${MINIKUBE_MEMORY:-16384}"
MINIKUBE_DISK="${MINIKUBE_DISK:-50g}"
MINIKUBE_DRIVER="${MINIKUBE_DRIVER:-docker}"

WORK=/tmp/minikube-setup-work
mkdir -p "$WORK"

log "1. apt update + base packages"
s apt-get update -qq
s DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    ca-certificates curl gnupg lsb-release conntrack socat ethtool

log "2. Install Docker (if missing)"
if ! command -v docker >/dev/null; then
    s install -m 0755 -d /etc/apt/keyrings
    # Download GPG key to temp file (no sudo in pipe)
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$WORK/docker.gpg.asc"
    gpg --dearmor < "$WORK/docker.gpg.asc" > "$WORK/docker.gpg"
    s install -m 0644 "$WORK/docker.gpg" /etc/apt/keyrings/docker.gpg
    # Build sources.list line then sudo-write it
    SRC_LINE="deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable"
    echo "$SRC_LINE" > "$WORK/docker.list"
    s install -m 0644 "$WORK/docker.list" /etc/apt/sources.list.d/docker.list
    s apt-get update -qq
    s DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-ce docker-ce-cli containerd.io
else
    echo "docker already installed: $(docker --version)"
fi

log "3. Add $USER to docker group"
if ! id -nG "$USER" | grep -qw docker; then
    s usermod -aG docker "$USER"
    echo "Added $USER to docker group (effective via sg below)"
fi

log "4. Enable + start docker service"
s systemctl enable --now docker
s systemctl is-active docker

log "5. Install minikube (if missing)"
if ! command -v minikube >/dev/null; then
    if [[ "$MINIKUBE_VERSION" == "latest" ]]; then
        URL="https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64"
    else
        URL="https://storage.googleapis.com/minikube/releases/${MINIKUBE_VERSION}/minikube-linux-amd64"
    fi
    curl -L -o "$WORK/minikube" "$URL"
    s install -o root -g root -m 0755 "$WORK/minikube" /usr/local/bin/minikube
fi
echo "minikube version: $(minikube version --short 2>/dev/null || minikube version | head -1)"

log "6. Start minikube cluster (${MINIKUBE_CPUS} CPU / ${MINIKUBE_MEMORY}MB / ${MINIKUBE_DISK})"
if ! sg docker -c "minikube status -p minikube" >/dev/null 2>&1; then
    sg docker -c "minikube start \
        --driver=$MINIKUBE_DRIVER \
        --cpus=$MINIKUBE_CPUS \
        --memory=$MINIKUBE_MEMORY \
        --disk-size=$MINIKUBE_DISK \
        --kubernetes-version=stable \
        --addons=metrics-server,ingress"
else
    echo "minikube already running"
    sg docker -c "minikube status"
fi

log "7. Configure kubectl alias in ~/.bashrc"
BASHRC="$HOME/.bashrc"
MARK="# >>> minikube kubectl alias >>>"
END_MARK="# <<< minikube kubectl alias <<<"
if ! grep -qF "$MARK" "$BASHRC"; then
    cat >> "$BASHRC" <<EOF

$MARK
alias kubectl='minikube kubectl --'
alias mk='minikube'
if command -v minikube >/dev/null; then
    source <(minikube kubectl -- completion bash 2>/dev/null) 2>/dev/null || true
    complete -F __start_kubectl kubectl 2>/dev/null || true
fi
$END_MARK
EOF
    echo "Added alias block to $BASHRC"
else
    echo "alias block already present"
fi

log "8. Verify cluster"
sg docker -c "minikube kubectl -- get nodes -o wide"
sg docker -c "minikube kubectl -- get pods -A"
sg docker -c "minikube addons list" | head -25

log "9. Cleanup work dir"
rm -rf "$WORK"

log "DONE - Cluster ready for load testing"
cat <<EOF

Quick reference (after re-login or 'newgrp docker'):
  source ~/.bashrc        # load alias
  kubectl get nodes       # via alias (-> minikube kubectl --)
  minikube dashboard      # web UI
  minikube tunnel         # expose LoadBalancer services
  minikube ip             # cluster IP
  minikube stop / start   # lifecycle

Resources:
  driver:  $MINIKUBE_DRIVER
  cpus:    $MINIKUBE_CPUS
  memory:  ${MINIKUBE_MEMORY}MB
  disk:    $MINIKUBE_DISK
  addons:  metrics-server, ingress

EOF
