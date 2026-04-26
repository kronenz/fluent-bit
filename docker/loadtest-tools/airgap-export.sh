#!/usr/bin/env bash
# Bundle every artifact required to deploy load-testing in an air-gapped
# environment: the loadtest-tools image, all third-party container images we
# reference, and pinned helm charts. Output is a single tar.gz that can be
# scp'd into the air-gap.
set -euo pipefail

OUT_DIR="${OUT_DIR:-./airgap-bundle}"
TAG="${TAG:-0.1.1}"
IMAGE="${IMAGE:-loadtest-tools}"

cd "$(dirname "$0")"
mkdir -p "$OUT_DIR/images" "$OUT_DIR/charts"

# ---- 1. Built loadtest-tools image ----
echo "[1/3] Saving $IMAGE:$TAG ..."
docker save "$IMAGE:$TAG" | gzip > "$OUT_DIR/images/${IMAGE}_${TAG}.tar.gz"

# ---- 2. Third-party images (long-running pods + observability stack) ----
THIRD_PARTY_IMAGES=(
    # Cluster runtime targets — pulled by helm charts
    "opensearchproject/opensearch:2.19.1"
    "opensearchproject/opensearch:2.19.1-jvm"
    "fluent/fluent-bit:4.2.3"
    # kube-prometheus-stack 76.5.1 (app v0.84.1) bundled images
    "quay.io/prometheus/prometheus:v3.6.0"
    "quay.io/prometheus/alertmanager:v0.28.1"
    "quay.io/prometheus-operator/prometheus-operator:v0.84.1"
    "quay.io/prometheus-operator/prometheus-config-reloader:v0.84.1"
    "registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.16.0"
    "quay.io/prometheus/node-exporter:v1.9.1"
    "grafana/grafana:12.1.0"
    "registry.k8s.io/ingress-nginx/controller:v1.14.3"
    "registry.k8s.io/ingress-nginx/kube-webhook-certgen:v1.6.7"
    "registry.k8s.io/metrics-server/metrics-server:v0.8.1"
    "registry.k8s.io/pause:3.10"             # used by kube-burner object template
    "docker.io/library/busybox:1.37.0"
    "curlimages/curl:latest"                 # used by ad-hoc curl Pods (k6 verifications, smoke tests)
)
for img in "${THIRD_PARTY_IMAGES[@]}"; do
    safe=$(echo "$img" | tr '/:' '__')
    if [[ -f "$OUT_DIR/images/${safe}.tar.gz" ]]; then
        echo "  · skip (cached): $img"
        continue
    fi
    echo "  · pulling $img"
    docker pull "$img" >/dev/null
    docker save "$img" | gzip > "$OUT_DIR/images/${safe}.tar.gz"
done

# ---- 3. Helm charts (pinned versions) ----
echo "[2/3] Pulling helm charts ..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add opensearch https://opensearch-project.github.io/helm-charts/ >/dev/null 2>&1 || true
helm repo add fluent https://fluent.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null

helm pull prometheus-community/kube-prometheus-stack --version 76.5.1 -d "$OUT_DIR/charts"
helm pull opensearch/opensearch                       --version 2.32.0 -d "$OUT_DIR/charts"
helm pull fluent/fluent-bit                           --version 0.55.0 -d "$OUT_DIR/charts"

# ---- 4. Manifests + scripts ----
echo "[3/3] Bundling manifests + scripts ..."
cp -r ../../deploy/load-testing "$OUT_DIR/manifests"

BUNDLE="loadtest-airgap-${TAG}-$(date +%Y%m%d).tar.gz"
tar -C "$(dirname "$OUT_DIR")" -czf "$BUNDLE" "$(basename "$OUT_DIR")"
echo
echo "Done."
ls -la "$BUNDLE"
echo
cat <<EOF
Transfer to air-gap host (one file):
    scp $BUNDLE bsh@<airgap-host>:/tmp/

On air-gap host:
    tar -xzf /tmp/$BUNDLE -C /tmp
    bash /tmp/airgap-bundle/manifests/.../airgap-import.sh REGISTRY=nexus.intranet/loadtest
EOF
