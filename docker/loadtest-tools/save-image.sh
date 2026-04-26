#!/usr/bin/env bash
# Save the built loadtest-tools image to a single gzipped tar that can be
# transferred into the air-gap network. Run on the build host (where the
# image was built with build.sh).
set -euo pipefail

IMAGE="${IMAGE:-loadtest-tools}"
TAG="${TAG:-0.1.1}"
OUT_DIR="${OUT_DIR:-./out}"

mkdir -p "$OUT_DIR"
OUT="${OUT_DIR}/${IMAGE}-${TAG}.tar.gz"

echo "[1/3] Saving ${IMAGE}:${TAG} → ${OUT}"
docker save "${IMAGE}:${TAG}" | gzip > "$OUT"

echo "[2/3] Computing SHA256"
SHA=$(sha256sum "$OUT" | awk '{print $1}')
echo "$SHA  $(basename "$OUT")" > "${OUT}.sha256"

echo "[3/3] Result"
ls -lh "$OUT" "${OUT}.sha256"
echo "SHA256: $SHA"

cat <<EOF

Transfer to air-gap host:
  scp ${OUT} ${OUT}.sha256 <airgap-host>:/tmp/

Then run on the air-gap host:
  REGISTRY=nexus.intranet:8082/loadtest \\
    bash docker/loadtest-tools/push-to-nexus.sh /tmp/$(basename "$OUT")
EOF
