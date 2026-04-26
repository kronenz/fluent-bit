#!/usr/bin/env bash
# Load a saved loadtest-tools image (tar.gz) on the air-gap host, retag to
# the internal Nexus registry, and push.
#
# Required env vars:
#   REGISTRY      e.g. nexus.intranet:8082/loadtest
# Optional env vars:
#   IMAGE         default: loadtest-tools
#   TAG           default: 0.1.0
#   NEXUS_USER    if set with NEXUS_PASS, performs `docker login` first
#   NEXUS_PASS    pass via env or stdin (avoid history)
#
# Usage:
#   REGISTRY=nexus.intranet:8082/loadtest bash push-to-nexus.sh /tmp/loadtest-tools-0.1.0.tar.gz
set -euo pipefail

TARBALL="${1:-}"
[[ -z "$TARBALL" || ! -f "$TARBALL" ]] && {
    echo "usage: $0 <path-to-image.tar.gz>" >&2; exit 2;
}

: "${REGISTRY:?set REGISTRY (e.g. nexus.intranet:8082/loadtest)}"
IMAGE="${IMAGE:-loadtest-tools}"
TAG="${TAG:-0.1.0}"
SRC="${IMAGE}:${TAG}"
DEST="${REGISTRY}/${IMAGE}:${TAG}"

# 1. Verify checksum if .sha256 sidecar present
if [[ -f "${TARBALL}.sha256" ]]; then
    echo "[1/5] Verifying SHA256..."
    (cd "$(dirname "$TARBALL")" && sha256sum -c "$(basename "${TARBALL}.sha256")")
else
    echo "[1/5] No SHA256 sidecar — skipping integrity check"
fi

# 2. docker load
echo "[2/5] docker load < $TARBALL"
LOADED=$(gunzip -c "$TARBALL" | docker load | awk '/Loaded image:/ {print $NF}' | head -1)
[[ -z "$LOADED" ]] && { echo "ERROR: nothing loaded" >&2; exit 1; }
echo "    loaded: $LOADED"
[[ "$LOADED" != "$SRC" ]] && {
    echo "    NOTE: loaded tag ($LOADED) ≠ expected ($SRC). Using loaded tag."
    SRC="$LOADED"
}

# 3. docker tag
echo "[3/5] docker tag $SRC → $DEST"
docker tag "$SRC" "$DEST"

# 4. docker login (if creds provided)
NEXUS_HOST="${REGISTRY%%/*}"
if [[ -n "${NEXUS_USER:-}" ]]; then
    echo "[4/5] docker login $NEXUS_HOST as $NEXUS_USER"
    if [[ -n "${NEXUS_PASS:-}" ]]; then
        echo "$NEXUS_PASS" | docker login "$NEXUS_HOST" -u "$NEXUS_USER" --password-stdin
    else
        echo "  (NEXUS_PASS not set, prompting interactively)"
        docker login "$NEXUS_HOST" -u "$NEXUS_USER"
    fi
else
    echo "[4/5] No NEXUS_USER — assuming previous login is still valid"
fi

# 5. docker push
echo "[5/5] docker push $DEST"
docker push "$DEST"

cat <<EOF

✅ Push complete: $DEST

Verify on Nexus UI:
  https://${NEXUS_HOST}/#browse/browse:docker

Or via API:
  curl -u \$NEXUS_USER:\$NEXUS_PASS \\
    https://${NEXUS_HOST}/v2/${IMAGE}/manifests/${TAG} | head

Pull from a cluster node to confirm:
  docker pull $DEST
  docker run --rm $DEST k6 version

K8s manifest update (kustomize):
  cd deploy/load-testing
  kustomize edit set image loadtest-tools=$DEST
  kubectl apply -k .

EOF
