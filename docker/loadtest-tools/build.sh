#!/usr/bin/env bash
# Build the loadtest-tools image. Run from this directory.
# REGISTRY/IMAGE/TAG can be overridden via env. The default tag is built from
# the date so iterations during development don't clobber each other.
set -euo pipefail

REGISTRY="${REGISTRY:-}"
IMAGE="${IMAGE:-loadtest-tools}"
TAG="${TAG:-0.1.0}"

cd "$(dirname "$0")"

FULL="${IMAGE}:${TAG}"
[[ -n "$REGISTRY" ]] && FULL="${REGISTRY}/${FULL}"

echo "Building $FULL ..."
docker build -t "$FULL" .

# Also tag a shorter alias so manifests can use 'loadtest-tools:latest' on the
# test bed without depending on the registry.
docker tag "$FULL" "${IMAGE}:latest"

echo
echo "Built:"
docker images | awk -v i="$IMAGE" '$1==i {print $1":"$2"  "$NF}'
echo
echo "Push to internal registry (run inside the air-gap):"
echo "  docker push $FULL"
