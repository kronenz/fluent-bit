# 13. kube-state-metrics 상세 부하 테스트 runbook

`05-kube-state-metrics-load-test.md`의 KSM-01~07 시나리오를 명령 단위 + 결과 확인 절차로 분해.

## 공통 사전 준비

```bash
export CTX=minikube-remote
export PROM=http://192.168.101.197:9090
export TEST_ID=LT-$(date +%Y%m%d)-KSM

kubectl --context=$CTX -n monitoring get pods -l app.kubernetes.io/name=kube-state-metrics
kubectl --context=$CTX -n monitoring get servicemonitor kps-kube-state-metrics

# kube-burner ServiceAccount + ClusterRole 적용 확인
kubectl --context=$CTX -n load-test get sa kube-burner
kubectl --context=$CTX get clusterrolebinding kube-burner-load-test
```

✅ **체크포인트 0**: KSM Pod Running, ServiceMonitor 활성, kube-burner RBAC 정상.

---

## KSM-01 — Baseline (현행 상태)

**목표**: 현재 클러스터의 오브젝트 수 / KSM RSS / 응답 시간 베이스라인 캡처.

### 단계 1. 5분간 부하 없이 sampling

```bash
# 1.1 Grafana 시간 범위 시작 기록
echo "Baseline start: $(date +%H:%M:%S)"
sleep 300
echo "Baseline end: $(date +%H:%M:%S)"
```

### 단계 2. 결과 확인 — 현황 메트릭

```bash
# 2.1 클러스터 오브젝트 수
echo "=== object counts ==="
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_pod_info)' | jq -r '"pods: \(.data.result[0].value[1])"'
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_deployment_labels)' | jq -r '"deploys: \(.data.result[0].value[1])"'
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_configmap_info)' | jq -r '"configmaps: \(.data.result[0].value[1])"'
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_namespace_status_phase)' | jq -r '"namespaces: \(.data.result[0].value[1])"'

# 2.2 KSM 자체 자원 (cgroup)
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"}' | \
  jq -r '"KSM RSS: \(.data.result[0].value[1] | tonumber / 1024 / 1024) MiB"'
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"}[5m])' | \
  jq -r '"KSM CPU: \(.data.result[0].value[1]) cores"'

# 2.3 1회 scrape에서 나오는 시리즈 수
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=avg_over_time(scrape_samples_scraped{job="kube-state-metrics"}[5m])' | \
  jq -r '"samples/scrape: \(.data.result[0].value[1])"'
```

### 단계 3. 결과 확인 — Grafana

| 대시보드 | 패널 (row "KSM-01") | 정상 패턴 |
|---|---|---|
| `Load Test • kube-state-metrics` | "Pods total" stat | testbed 기준 ~30, 운영 수천 |
| 동 | "KSM /metrics duration p95" | empty (KSM telemetry port 미스크레이프) — 운영에선 `--telemetry-port=8081` 추가 시 활성화 |
| 동 | "KSM RSS" | 평탄선 |

### 단계 4. 합격 + 결과 기록

| 지표 | 기준 | 실측 | 판정 |
|---|---|---|---|
| KSM RSS | ≤ pod limit 70% | (단계 2.2) | |
| samples/scrape | (현황 기준값) | (단계 2.3) | |

```bash
cat > /tmp/$TEST_ID-KSM01-baseline.json <<EOF
{
  "test_id": "$TEST_ID-KSM01",
  "scenario": "Baseline",
  "pods_count": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_pod_info)' | jq -r '.data.result[0].value[1]'),
  "configmaps_count": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_configmap_info)' | jq -r '.data.result[0].value[1]'),
  "ksm_rss_bytes": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"}' | jq -r '.data.result[0].value[1]'),
  "samples_per_scrape": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(scrape_samples_scraped{job="kube-state-metrics"}[5m])' | jq -r '.data.result[0].value[1]')
}
EOF
cat /tmp/$TEST_ID-KSM01-baseline.json
```

---

## KSM-02 — Pod 대량 생성 (kube-burner 100 → 운영 10000)

**목표**: 오브젝트 ↑ 시 KSM /metrics 응답 시간 / RSS 증가 측정.

### 단계 1. 매니페스트 검증 + Job 시작

```bash
# 1.1 ConfigMap의 jobIterations 확인
kubectl --context=$CTX -n load-test get configmap kube-burner-config -o jsonpath='{.data.config\.yaml}' | grep -A2 jobIterations
# testbed: 100, 운영: 10000으로 사전 변경 필요

# 1.2 부하 시작
kubectl --context=$CTX apply -f deploy/load-testing/04-test-jobs/kube-burner-pod-density.yaml
echo "T0: $(date +%H:%M:%S)"

# 1.3 kube-burner Pod 진행 상황
kubectl --context=$CTX -n load-test logs job/kube-burner-pod-density -f --tail=20 &
LOG_PID=$!
```

✅ **체크포인트 1**: kube-burner Pod Running, "Pre-load: Sleeping for 1m0s" 후 진짜 작업 시작.

### 단계 2. 진행 모니터링 (Pod 생성 진행률)

```bash
# 2.1 1분마다 kburner-* namespace 수 + 그 안 Pod 수
for i in 1 2 3 4 5; do
  echo "=== T+$((i*60))s ==="
  KBN=$(kubectl --context=$CTX get ns -o name 2>/dev/null | grep -c '^namespace/kburner-')
  KBP=$(kubectl --context=$CTX get pods -A --no-headers 2>/dev/null | grep -c '^kburner-')
  KBR=$(kubectl --context=$CTX get pods -A --field-selector=status.phase=Running --no-headers 2>/dev/null | grep -c '^kburner-')
  echo "namespaces=$KBN pods_total=$KBP pods_running=$KBR"
  sleep 60
done
```

### 단계 3. 진행 중 KSM 부담 측정

```bash
# 3.1 KSM /metrics 응답 시간 (외부 측정)
KSM_SVC="http://kps-kube-state-metrics.monitoring.svc:8080/metrics"
kubectl --context=$CTX -n monitoring run -i --rm curl-test --image=curlimages/curl:latest \
  --restart=Never --quiet --command -- sh -c "
    for i in 1 2 3; do
      time curl -s -o /dev/null $KSM_SVC
    done
  " 2>&1 | grep real

# 3.2 KSM RSS 추세
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"}' | \
  jq -r '.data.result[0].value[1] | tonumber / 1024 / 1024'

# 3.3 API 서버 verb별 부담
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum by (verb) (rate(apiserver_request_total[1m]))' | \
  jq '.data.result[] | {verb: .metric.verb, rps: .value[1]}'

# 3.4 kube-pod-info 시리즈 수 (KSM 처리량 증가 가시화)
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_pod_info)' | jq -r '.data.result[0].value[1]'
```

### 단계 4. kube-burner 완료 대기 + 결과

```bash
# 4.1 완료 대기 (testbed 100 iter ≈ 5~10분, 운영 10000 ≈ 1~2시간)
kubectl --context=$CTX -n load-test wait --for=condition=complete \
  job/kube-burner-pod-density --timeout=2h

# 4.2 kube-burner stdout 분석
kubectl --context=$CTX -n load-test logs job/kube-burner-pod-density | tail -50 | tee /tmp/$TEST_ID-KSM02-burner.log
grep -E "ELAPSED|Job pod-density" /tmp/$TEST_ID-KSM02-burner.log
# - "Job pod-density: 100 iterations completed" 형태로 결과 출력

# 4.3 KSM 최종 메트릭
echo "=== Final KSM state ==="
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"}' | \
  jq -r '"RSS: \(.data.result[0].value[1] | tonumber / 1024 / 1024) MiB"'
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(kube_pod_info)' | jq -r '"pods: \(.data.result[0].value[1])"'
```

### 단계 5. 결과 확인 — Grafana

| 대시보드 | 패널 | 정상 / 이상 |
|---|---|---|
| `Load Test • kube-state-metrics` row "KSM-02" | "Total Pods vs kburner Pods" | kburner 곡선이 0 → 100 (or 10000) ramp |
| 동 | "KSM RSS" | 단조 증가 후 cleanup으로 감소 |
| 동 | "API Server Request Rate by verb" | CREATE 폭증 후 정상 회복 |

### 단계 6. 합격 판정

| 지표 | 기준 | 실측 | 판정 |
|---|---|---|---|
| Pods 100개 생성 (testbed) | 완료 | (단계 4.1) | |
| KSM RSS 증가율 | ≤ pod limit 70% | (단계 4.3) | |
| API 서버 LIST 실패율 | ≈ 0% | (단계 3.3) | |
| kube-burner 자체 실패 Pod | 0 | (단계 4.2) | |

### 단계 7. 정리

```bash
# kube-burner는 cleanup: true이므로 namespace 자동 삭제. 추가 검증:
kubectl --context=$CTX get ns | grep kburner | head -5   # 없어야 함

# 만약 잔존하면 강제 삭제
kubectl --context=$CTX get ns -o name | grep kburner | xargs -I{} kubectl --context=$CTX delete {} --grace-period=0 --force --wait=false
kubectl --context=$CTX -n load-test delete job kube-burner-pod-density --ignore-not-found
```

---

## KSM-03 — ConfigMap 5만 개

**목표**: ConfigMap 대량 생성 시 KSM 메모리 / etcd 압박.

### 단계 1. kube-burner config 변경 (Pod → ConfigMap)

```bash
# 임시 config 작성
cat > /tmp/$TEST_ID-KSM03-config.yaml <<'EOF'
metricsEndpoints: []
global: { gc: true, gcMetrics: false }
jobs:
  - name: configmap-density
    jobType: create
    jobIterations: 5000   # testbed 한계, 운영 50000
    namespace: kburner-cm
    namespacedIterations: false
    cleanup: true
    qps: 30
    burst: 50
    objects:
      - objectTemplate: cm.yaml
        replicas: 1
EOF

cat > /tmp/$TEST_ID-KSM03-cm.yaml <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: burner-cm-{{.Iteration}}
  labels: { app: kube-burner-cm }
data:
  payload: "test-data-{{.Iteration}}"
EOF

# kube-burner를 Pod로 직접 실행 (config + template을 ConfigMap으로 마운트)
kubectl --context=$CTX -n load-test create configmap kube-burner-cm-config \
  --from-file=config.yaml=/tmp/$TEST_ID-KSM03-config.yaml \
  --from-file=cm.yaml=/tmp/$TEST_ID-KSM03-cm.yaml \
  --dry-run=client -o yaml | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n load-test run kube-burner-cm \
  --image=loadtest-tools:0.1.1 --restart=Never \
  --serviceaccount=kube-burner \
  --overrides='{"spec":{"containers":[{"name":"kube-burner-cm","image":"loadtest-tools:0.1.1","workingDir":"/work","command":["kube-burner","init","-c","/config/config.yaml","--uuid","cm-test"],"volumeMounts":[{"name":"config","mountPath":"/config"}]}],"volumes":[{"name":"config","configMap":{"name":"kube-burner-cm-config"}}]}}'
```

### 단계 2. 진행 + 결과 확인

```bash
kubectl --context=$CTX -n load-test logs -f kube-burner-cm

# 별도 터미널에서:
watch -n 30 'curl -sG "$PROM/api/v1/query" --data-urlencode "query=count(kube_configmap_info)" | jq -r .data.result[0].value[1]'
watch -n 30 'curl -sG "$PROM/api/v1/query" --data-urlencode "query=container_memory_working_set_bytes{namespace=\"monitoring\",pod=~\".*kube-state-metrics.*\"}" | jq -r ".data.result[0].value[1] | tonumber / 1024 / 1024"'
```

### 단계 3. 정리

```bash
kubectl --context=$CTX delete ns kburner-cm --ignore-not-found --wait=false
kubectl --context=$CTX -n load-test delete pod kube-burner-cm --ignore-not-found
```

---

## KSM-04 — Namespace churn

**목표**: namespace 생성/삭제 반복 → API 서버 LIST/WATCH 부담.

### 단계 1. 반복 churn 명령

```bash
# 5분 동안 namespace 생성 → 30초 → 삭제 반복
for i in $(seq 1 10); do
  echo "=== iteration $i ==="
  kubectl --context=$CTX create ns ksm04-$i
  sleep 30
  kubectl --context=$CTX delete ns ksm04-$i --wait=false
  sleep 30
done
```

### 단계 2. 진행 중 측정

```bash
# 별도 터미널 — 1분마다 API verb별 rate
for i in 1 2 3 4 5 6 7 8 9 10; do
  ts=$(date +%H:%M:%S)
  list=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(apiserver_request_total{verb="LIST"}[1m]))' | jq -r '.data.result[0].value[1]')
  watch_=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(apiserver_request_total{verb="WATCH"}[1m]))' | jq -r '.data.result[0].value[1]')
  echo -e "$ts\tLIST=$list\tWATCH=$watch_"
  sleep 60
done | tee /tmp/$TEST_ID-KSM04-api.tsv
```

### 단계 3. 합격

| 지표 | 기준 | 실측 |
|---|---|---|
| API 서버 LIST 에러율 | < 0.1% | `rate(apiserver_request_total{code!~"2..", verb="LIST"}[5m])` |
| KSM /metrics 응답 안정 | ✓ | row "KSM-04" 패널 |

---

## KSM-05 — Shard 구성 (`--total-shards=N`)

**목표**: KSM 수평 분할 시 각 shard 부담 분산.

### 단계 1. KSM Deployment를 StatefulSet으로 변경 (운영) — testbed에선 helm values 수정

```bash
# helm values.yaml에 다음 추가:
# kube-state-metrics:
#   statefulset:
#     replicas: 3
#     args:
#       - --pod=$(POD_NAME)
#       - --pod-namespace=$(POD_NAMESPACE)
#       - --total-shards=3
#       - --shard=$(POD_NAME 마지막 숫자 추출)

# 변경 후 helm upgrade
# bash deploy/load-testing/01-monitoring-core/install.sh
```

### 단계 2. shard별 RSS / 응답 시간

```bash
# 2.1 각 shard pod의 RSS
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum by (pod) (container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"})' | \
  jq '.data.result[]'

# 2.2 부담 분배 (kube_pod_info를 어느 shard가 처리하는지)
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=count by (instance) (kube_pod_info)' | jq
# 균등하게 분포되어야 함
```

---

## KSM-06 — Soak 24h

```bash
# 매시간 RSS / goroutine 기록
while true; do
  ts=$(date +"%Y-%m-%d %H:%M:%S")
  rss=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*"})' | jq -r '.data.result[0].value[1]')
  cpu=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~".*kube-state-metrics.*"}[5m]))' | jq -r '.data.result[0].value[1]')
  echo -e "$ts\t$rss\t$cpu"
  sleep 3600
done | tee /tmp/$TEST_ID-KSM06-soak.tsv
```

합격: 24h drift < 10%.

---

## KSM-07 — Allowlist / Denylist 튜닝

**목표**: 고-카디널리티 메트릭 제거 → 시리즈 수 감소.

### 단계 1. 변경 전 시리즈 수 기록

```bash
BEFORE=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=avg_over_time(scrape_samples_scraped{job="kube-state-metrics"}[5m])' | jq -r '.data.result[0].value[1]')
echo "BEFORE: $BEFORE samples/scrape"
```

### 단계 2. helm values에 denylist 추가

```yaml
# 01-monitoring-core/values.yaml
kube-state-metrics:
  metricLabelsAllowlist:
    - "pods=[*]"          # 또는 specific labels
  metricsDenylist:
    - "kube_pod_init_container.*"
    - "kube_replicaset_owner"
```

```bash
helm --kube-context=$CTX -n monitoring upgrade kps prometheus-community/kube-prometheus-stack \
  --version 76.5.1 -f deploy/load-testing/01-monitoring-core/values.yaml --reuse-values --wait
sleep 120   # 새 KSM scrape
```

### 단계 3. 변경 후 비교

```bash
AFTER=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=avg_over_time(scrape_samples_scraped{job="kube-state-metrics"}[5m])' | jq -r '.data.result[0].value[1]')
echo "AFTER: $AFTER samples/scrape"
echo "Reduction: $(echo "scale=1; ($BEFORE - $AFTER) / $BEFORE * 100" | bc)%"
```

합격: 시리즈 30% 이상 감소 (denylist 적중률에 따라).

---

## 결과 확인 공통 패턴

각 시나리오:
1. **kubectl 명령** — Pod state, events, logs
2. **PromQL** — 정량 측정값 (본 runbook의 명령들)
3. **Grafana** — `Load Test • kube-state-metrics` row "KSM-XX" + `Load Test • Overview`
4. **kube-burner stdout** — Job 완료 시 자동 요약 출력 (`ELAPSED`, `iterations completed`)

```bash
# 모든 결과를 단일 디렉토리에 보관
mkdir -p /tmp/$TEST_ID
cp /tmp/$TEST_ID-KSM*.* /tmp/$TEST_ID/

# Grafana JSON export (대시보드 + 데이터)
curl -s -u admin:admin \
  "http://192.168.101.197:3000/api/dashboards/uid/lt-ksm" \
  -o /tmp/$TEST_ID/dash-ksm.json
```

운영 결과는 `10-test-plan-and-results.md` §10 템플릿에 따라 별도 LT-YYYYMMDD-KSM-## 형식으로 기록.
