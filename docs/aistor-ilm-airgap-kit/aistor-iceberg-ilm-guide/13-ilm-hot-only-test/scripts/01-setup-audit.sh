#!/usr/bin/env bash
# 01-setup-audit.sh — Hot/Warm audit log 를 Fluent Bit http input 으로 전송
# 사용: source config.env && ./01-setup-audit.sh
# 🔍 audit_webhook 키 이름·재시작 필요 여부는 AIStor 버전에서 확인 (mc admin config get <alias> audit_webhook)
set -euo pipefail
: "${HOT_ALIAS:?config.env 를 source 하세요}"
mkdir -p backup

for pair in "${HOT_ALIAS}:minio-hot" "${WARM_ALIAS}:minio-warm"; do
  alias=${pair%%:*}; tag=${pair##*:}
  echo "== $alias → ${AUDIT_ENDPOINT}/${tag}"
  mc admin config get "$alias" audit_webhook > "backup/audit-${alias}-$(date +%Y%m%dT%H%M%S).txt" 2>/dev/null || true
  # URI path 가 Fluent Bit 태그가 된다 (minio-hot / minio-warm)
  mc admin config set "$alias" audit_webhook:ilmtest \
    enable=on endpoint="${AUDIT_ENDPOINT}/${tag}" auth_token="Bearer ${AUDIT_TOKEN}"
done

echo "설정 반영에 재시작이 필요하면: mc admin service restart <alias>  ⚠️ 운영 영향 확인 후"
