#!/usr/bin/env bash
# 02-deploy.sh — ns · ConfigMap 생성 후 CronJob/trace collector/audit 수신기 배포
# 사전: Secret ilmtest-s3 (README §8) 와 공유 볼륨 ilmtest-shared(testbed/00-shared.yaml)를 먼저 만든다.
#       OpenSearch 로 보낼 때만 Secret ilmtest-os 와 FLUENT_BIT_CONF=fluent-bit/audit-receiver.yaml.
# 사용: source config.env && ./02-deploy.sh
set -euo pipefail
: "${HOT_ALIAS:?config.env 를 source 하세요}"
cd "$(dirname "$0")"
source ./lib.sh   # IMAGE_REGISTRY (폐쇄망 레지스트리) 지원

kubectl get ns "$K8S_NS" >/dev/null 2>&1 || kubectl create ns "$K8S_NS"
kubectl -n "$K8S_NS" get secret ilmtest-s3 >/dev/null || { echo "Secret ilmtest-s3 가 없습니다 (README §8)"; exit 1; }

# 공통 설정 — 자격증명 제외 값만
kubectl -n "$K8S_NS" create configmap ilmtest-config --dry-run=client -o yaml \
  --from-literal=HOT_ALIAS=HOT \
  --from-literal=BUCKET="$BUCKET" \
  --from-literal=TIER_NAME="$TIER_NAME" \
  --from-literal=TIER_ACCESS_KEY="$TIER_ACCESS_KEY" \
  --from-literal=TRANSITION_DAYS="$TRANSITION_DAYS" \
  --from-literal=SCANNER_GRACE_HOURS="${SCANNER_GRACE_HOURS:-24}" \
  --from-literal=HMS_URI="$HMS_URI" \
  --from-literal=CATALOG="$CATALOG" \
  --from-literal=DB="$DB" \
  --from-literal=TABLE="$TABLE" \
  --from-literal=LEDGER_TABLE="$LEDGER_TABLE" \
  --from-literal=TABLE_PREFIX="$TABLE_PREFIX" \
  --from-literal=ROWS_PER_BATCH="$ROWS_PER_BATCH" \
  --from-literal=EVIDENCE_DIR="${EVIDENCE_DIR:-/shared/evidence}" \
  --from-literal=SPARK_JARS="${SPARK_JARS:-}" \
  --from-literal=HOT_METRICS_URLS="${HOT_METRICS_URLS:-}" \
  | kubectl apply -f -

sync_jobs "$K8S_NS"   # spark/*.py · run-spark.sh · state_snapshot.py

kubectl -n "$K8S_NS" create configmap ilmtest-fluent-bit --dry-run=client -o yaml \
  --from-file=fluent-bit.yaml="${FLUENT_BIT_CONF:-fluent-bit/audit-receiver-file.yaml}" \
  | kubectl apply -f -

kapply "$K8S_NS" k8s/*.yaml
# 설정이 바뀌면 상시 수집기도 새 EVIDENCE_DIR 등을 읽도록 재시작
kubectl -n "$K8S_NS" rollout restart deploy/fluent-bit-audit deploy/ilmtest-trace >/dev/null
# 스모크 등 수동 실행 구간: CRON_SUSPEND=1 이면 주기 실행을 멈춘다 (해제: CRON_SUSPEND=0 으로 재실행)
for cj in ilmtest-writer ilmtest-verifier ilmtest-state; do
  kubectl -n "$K8S_NS" patch cronjob "$cj" --type merge -p "{\"spec\":{\"suspend\":$([[ "${CRON_SUSPEND:-0}" == 1 ]] && echo true || echo false)}}" >/dev/null
done
kubectl -n "$K8S_NS" get cronjob,deploy,svc
