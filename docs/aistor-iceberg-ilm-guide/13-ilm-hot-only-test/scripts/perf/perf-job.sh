#!/usr/bin/env bash
# perf-job.sh <name> <job.py> [KEY=VALUE ...] — 성능·영향도 검증용 Spark Job 1회 실행 (CronJob 과 같은 이미지·설정)
# ilmtest-config 를 그대로 쓰고 KEY=VALUE 로 덮어쓴다 (예: DB=ilmperf EVIDENCE_DIR=/shared/evidence/perf-...).
# 실행 중인 1d 연속 테스트의 ConfigMap 은 건드리지 않는다.
set -euo pipefail
NAME=${1:?name}; JOB=${2:?job.py}; shift 2
NS=${K8S_NS:-ilm-test}
source "$(dirname "$0")/../lib.sh"
ENV_YAML='{ name: TZ, value: UTC }, { name: AWS_REGION, value: us-east-1 }'
for kv in "$@"; do ENV_YAML+=", { name: ${kv%%=*}, value: \"${kv#*=}\" }"; done

kubectl -n "$NS" delete job "$NAME" --ignore-not-found >/dev/null
render <<YAML | kubectl -n "$NS" apply -f - 2>&1 | grep -v '^Warning'
apiVersion: batch/v1
kind: Job
metadata:
  name: $NAME
  labels: { app.kubernetes.io/part-of: ilmtest, app.kubernetes.io/name: perf }
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels: { app.kubernetes.io/part-of: ilmtest, app.kubernetes.io/name: perf }
    spec:
      restartPolicy: Never
      containers:
        - name: spark
          image: apache/spark:3.5.3-python3
          command: ["/bin/bash", "/jobs/run-spark.sh", "$JOB"]
          env: [ $ENV_YAML ]
          envFrom: [{ configMapRef: { name: ilmtest-config } }, { secretRef: { name: ilmtest-s3 } }]
          resources: { requests: { cpu: "${PERF_CPU:-2}", memory: 4Gi }, limits: { memory: 4Gi } }
          volumeMounts: [{ name: jobs, mountPath: /jobs }, { name: shared, mountPath: /shared }]
      volumes:
        - { name: jobs, configMap: { name: ilmtest-jobs } }
        - { name: shared, persistentVolumeClaim: { claimName: ilmtest-shared } }
YAML
