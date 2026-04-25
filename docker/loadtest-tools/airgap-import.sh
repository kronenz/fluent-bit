#!/usr/bin/env bash
# Run on the air-gap host that has the bundle extracted at $BUNDLE_DIR.
# Loads every saved image into the local docker daemon, retags into the
# internal registry, and pushes. Helm charts are left in place; deploy with:
#   helm install kps charts/kube-prometheus-stack-76.5.1.tgz -f kps-values.yaml
set -euo pipefail

BUNDLE_DIR="${BUNDLE_DIR:-./airgap-bundle}"
REGISTRY="${REGISTRY:?set REGISTRY (e.g. nexus.intranet:8082/loadtest)}"

cd "$BUNDLE_DIR"
[[ -d images ]] || { echo "no images/ dir under $BUNDLE_DIR" >&2; exit 1; }

echo "[1/2] Loading + retagging + pushing images..."
for f in images/*.tar.gz; do
    echo "  · loading $f"
    SRC=$(gunzip -c "$f" | docker load | awk '/Loaded image:/ {print $NF}' | head -1)
    [[ -z "$SRC" ]] && { echo "    WARN: nothing loaded from $f"; continue; }

    # Strip original registry prefix and prepend internal registry
    NAME=$(echo "$SRC" | sed -E 's@^[^/]+/@@; s@^[^/]+/@@' )  # strip up to 2 path components
    DEST="${REGISTRY}/${NAME}"
    echo "    $SRC  →  $DEST"
    docker tag  "$SRC"  "$DEST"
    docker push "$DEST"
done

echo "[2/2] Helm charts on disk:"
ls -la charts/

cat <<EOF

Next:
  cd manifests/load-testing
  # adjust install scripts: replace upstream image refs with \$REGISTRY/...
  REGISTRY=$REGISTRY \\
    bash 01-monitoring-core/install.sh
EOF
