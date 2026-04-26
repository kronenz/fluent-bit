# 12. node-exporter 상세 부하 테스트 runbook

`04-node-exporter-load-test.md`의 NE-01~07 시나리오를 명령 단위로 분해 + **결과 확인 절차**를 단계마다 명시.

## 공통 사전 준비

```bash
export CTX=minikube-remote
export PROM=http://192.168.101.197:9090
export GRAFANA=http://192.168.101.197:3000     # 대시보드 스냅샷용
export TEST_ID=LT-$(date +%Y%m%d)-NE

# health
kubectl --context=$CTX -n monitoring get ds kps-prometheus-node-exporter
kubectl --context=$CTX -n monitoring get servicemonitor kps-prometheus-node-exporter

# 이 runbook 동안 cluster의 다른 부하기를 모두 끄기 권장
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
kubectl --context=$CTX -n load-test scale deploy avalanche --replicas=0
kubectl --context=$CTX -n load-test scale deploy loggen-spark --replicas=0
```

✅ **체크포인트 0**: node-exporter DaemonSet 1대 이상 Running, 다른 부하기 0.

---

## NE-01 — 기본 collector scrape 비용 (Baseline)

**목표**: 부하 없는 상태의 scrape duration / 시리즈 수 / CPU·RSS 기준값 캡처.

### 단계 1. 5분간 부하 없이 메트릭 sampling

```bash
# 1.1 Grafana 시간 범위 기록 시작
echo "Baseline start: $(date +%H:%M:%S)"

# 1.2 5분 sustain (다른 변경 없음)
sleep 300
echo "Baseline end: $(date +%H:%M:%S)"
```

### 단계 2. 결과 확인 — PromQL

```bash
# 2.1 Scrape duration p95
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=avg_over_time(scrape_duration_seconds{job="node-exporter"}[5m])' | \
  jq '.data.result[] | {instance: .metric.instance, duration_s: .value[1]}'

# 2.2 1회 scrape의 sample 수
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=avg_over_time(scrape_samples_scraped{job="node-exporter"}[5m])' | \
  jq '.data.result[] | {instance: .metric.instance, samples: .value[1]}'

# 2.3 collector별 소요시간 분포
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=node_scrape_collector_duration_seconds' | \
  jq '.data.result[] | {collector: .metric.collector, duration_s: .value[1]}' | \
  sort -t: -k3 -nr | head -10

# 2.4 RSS / CPU
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=process_resident_memory_bytes{job="node-exporter"}' | \
  jq -r '.data.result[] | "\(.metric.instance)\t\(.value[1] | tonumber / 1024 / 1024) MiB"'

curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(process_cpu_seconds_total{job="node-exporter"}[5m])' | \
  jq -r '.data.result[] | "\(.metric.instance)\t\(.value[1])"'
```

### 단계 3. 결과 확인 — Grafana 시각

| 대시보드 | 패널 (row "NE-01") | 정상 패턴 |
|---|---|---|
| `Load Test • node-exporter` | "Scrape Duration" | 평탄선, < 0.3 s |
| 동 | "Samples Scraped per Scrape" | 평탄선, ≤ 2,000 |
| 동 | "Per-collector Duration" | filesystem/diskstats가 상위, 모두 < 0.1 s |

스냅샷:
```bash
# Grafana 대시보드 → 우상단 "Share" → "Snapshot" → external/local 저장
# 또는 panel-level CSV export: panel 우측 ⋯ → "Inspect" → "Data" → "Download CSV"
```

### 단계 4. 합격 판정 + 결과 기록

| 지표 | 기준 | 실측 | 판정 |
|------|------|------|------|
| `/metrics` p95 (server-side) | ≤ 300 ms | (단계 2.1) | |
| samples/scrape | ≤ 2,000 | (단계 2.2) | |
| CPU | ≤ 100m (idle) | (단계 2.4) | |
| RSS | ≤ 50 MiB | (단계 2.4) | |

```bash
# 결과 기록 (JSON 형태로 보관)
cat > /tmp/$TEST_ID-NE01-baseline.json <<EOF
{
  "test_id": "$TEST_ID-NE01",
  "scenario": "Baseline",
  "duration_s": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(scrape_duration_seconds{job="node-exporter"}[5m])' | jq -r '.data.result[0].value[1]'),
  "samples": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(scrape_samples_scraped{job="node-exporter"}[5m])' | jq -r '.data.result[0].value[1]'),
  "rss_bytes": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=process_resident_memory_bytes{job="node-exporter"}' | jq -r '.data.result[0].value[1]'),
  "cpu_cores": $(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=rate(process_cpu_seconds_total{job="node-exporter"}[5m])' | jq -r '.data.result[0].value[1]')
}
EOF
cat /tmp/$TEST_ID-NE01-baseline.json
```

✅ **NE-01 종료** — 이 baseline은 NE-02 ~ NE-07 비교 기준.

---

## NE-02 — 고빈도 scrape (hey 50c × 50qps × 2분)

**목표**: 외부 HTTP 부하로 `/metrics` 응답 분포 측정. p95 ≤ 300 ms.

### 단계 1. hey Job 적용

```bash
# 1.1 매니페스트 검증 (이미지 0.1.1 사용 확인)
kubectl --context=$CTX -n load-test get configmap lt-config -o jsonpath='{.data.NODE_EXPORTER_SVC}'; echo
kubectl --context=$CTX -n load-test get configmap lt-config -o jsonpath='{.data.HEY_DURATION}'; echo

# 1.2 Job 시작
kubectl --context=$CTX apply -f deploy/load-testing/04-test-jobs/hey-node-exporter.yaml
kubectl --context=$CTX -n load-test get pods -l app=hey-node-exporter
```

✅ **체크포인트 1**: hey Pod Running, 환경 변수 정상 주입.

### 단계 2. 진행 모니터링 (2분)

```bash
# 2.1 hey는 stdout으로 progress 출력 안 함 → 중간 메트릭으로 확인
for i in 1 2; do
  echo "=== T+$((i*60))s ==="
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=scrape_duration_seconds{job="node-exporter"}' | jq -r '.data.result[] | "\(.metric.instance)\t\(.value[1]) s"'
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=rate(process_cpu_seconds_total{job="node-exporter"}[1m])' | jq -r '.data.result[] | "\(.metric.instance)\t\(.value[1])"'
  sleep 60
done

# 2.2 Job 완료 대기
kubectl --context=$CTX -n load-test wait --for=condition=complete job/hey-node-exporter --timeout=5m
```

### 단계 3. 결과 확인 — hey stdout summary

```bash
# 3.1 hey 결과 분석 (p50/p95/p99 + 응답 코드 분포)
kubectl --context=$CTX -n load-test logs job/hey-node-exporter | tee /tmp/$TEST_ID-NE02-hey.txt

# 3.2 핵심 수치 추출
grep -E "Total:|Average:|Requests/sec:|9[0-9]%" /tmp/$TEST_ID-NE02-hey.txt
grep -A20 "Status code distribution" /tmp/$TEST_ID-NE02-hey.txt
```

해석:
- `[200]` 응답 비율 → 정상 (≥ 99%)
- `[503]` / `connection refused` → node-exporter `--web.max-requests` 한계 도달
- p95/p99 → SLO 평가

### 단계 4. 결과 확인 — Prometheus 측 영향

```bash
# 4.1 부하 중 scrape duration 변화
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=max_over_time(scrape_duration_seconds{job="node-exporter"}[5m])' | jq

# 4.2 scrape timeout 발생 여부 (up=0 시점)
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=count_over_time(up{job="node-exporter"}[5m])' | jq
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=count_over_time((up{job="node-exporter"}==0)[5m])' | jq
```

### 단계 5. 결과 확인 — Grafana

| 대시보드 | 패널 | 정상 / 이상 패턴 |
|---|---|---|
| `Load Test • node-exporter` row "NE-02" | "node-exporter CPU" | 부하 시작 시 CPU 곡선 step-up, 종료 시 step-down |
| 동 | "Scrape Duration (high-freq)" | NE-01 baseline 대비 ≤ 1.5× |
| `Load Test • Overview` | "Targets DOWN" | 0 유지 (timeout 없음) |

### 단계 6. 합격 판정

| 지표 | 기준 | 실측 | 판정 |
|------|------|------|------|
| http_req p95 (hey) | ≤ 300 ms | (단계 3.2) | |
| 200 응답 비율 | ≥ 99% | (단계 3.2) | |
| node-exporter CPU 증가 | ≤ baseline ×3 | (단계 4) | |
| scrape timeout | 0건 | (단계 4.2) | |

### 단계 7. 정리

```bash
kubectl --context=$CTX -n load-test delete job hey-node-exporter
```

---

## NE-03 — textfile 메트릭 1만 개

**목표**: textfile collector를 통해 1만 개 시리즈 추가 시 scrape duration 변화.

### 단계 1. 노드에 textfile 디렉토리 마운트 확인

```bash
# 1.1 node-exporter args에 --collector.textfile.directory 있는지 확인
kubectl --context=$CTX -n monitoring get ds kps-prometheus-node-exporter -o yaml | \
  grep -A2 textfile
# 없으면 helm values에 추가 후 upgrade 필요

# 1.2 hostPath 또는 ConfigMap으로 1만 라인 .prom 파일 주입
NE_POD=$(kubectl --context=$CTX -n monitoring get pod -l app.kubernetes.io/name=prometheus-node-exporter -o jsonpath='{.items[0].metadata.name}')
kubectl --context=$CTX -n monitoring exec $NE_POD -- sh -c '
  mkdir -p /var/lib/node_exporter
  for i in $(seq 1 10000); do
    echo "bench_metric{idx=\"$i\"} $i"
  done > /var/lib/node_exporter/bench.prom
  ls -lh /var/lib/node_exporter/bench.prom
'
```

✅ **체크포인트 1**: bench.prom 생성됨, 약 200KB.

### 단계 2. Prometheus가 새 메트릭 보는지 확인 (1~2 scrape 후)

```bash
sleep 60   # 다음 scrape 대기
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=count(bench_metric)' | jq -r '.data.result[0].value[1]'
# 1만 도달이 정상
```

### 단계 3. Scrape duration 변화 확인

```bash
# 3.1 baseline 대비 비교
NE01_BASELINE=$(jq -r '.duration_s' /tmp/$TEST_ID-NE01-baseline.json 2>/dev/null || echo "0.05")
NE03_NOW=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=avg_over_time(scrape_duration_seconds{job="node-exporter"}[2m])' | jq -r '.data.result[0].value[1]')
echo "Baseline: $NE01_BASELINE s, NE-03: $NE03_NOW s"

# 3.2 textfile collector 단독 비용
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=node_scrape_collector_duration_seconds{collector="textfile"}' | jq
```

### 단계 4. 합격 판정

| 지표 | 기준 | 실측 | 판정 |
|------|------|------|------|
| Samples per scrape | NE-01 + ~10,000 | (PromQL `count(bench_metric)`) | |
| Scrape duration | ≤ NE-01 × 2 | (단계 3.1) | |
| textfile collector duration | ≤ 0.5 s | (단계 3.2) | |

### 단계 5. 정리

```bash
kubectl --context=$CTX -n monitoring exec $NE_POD -- rm -f /var/lib/node_exporter/bench.prom
sleep 60
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=count(bench_metric)' | jq -r '.data.result[0].value[1]'  # 0 또는 NONE
```

---

## NE-04 — 마운트 포인트 50+

**목표**: filesystem collector 처리해야 할 마운트 수 증가 시 영향.

```bash
# 단계 1. 노드 호스트에 bind mount 50개 추가 (운영 클러스터 또는 minikube ssh)
ssh minikube-host 'sudo mkdir -p /tmp/mounts && \
  for i in $(seq 1 50); do sudo mkdir -p /tmp/mounts/m$i; sudo mount --bind /tmp /tmp/mounts/m$i; done'

# 단계 2. filesystem collector duration 측정
sleep 60
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=node_scrape_collector_duration_seconds{collector="filesystem"}' | jq

# 단계 3. 정리 (역순)
ssh minikube-host 'for i in $(seq 1 50); do sudo umount /tmp/mounts/m$i 2>/dev/null; done; sudo rm -rf /tmp/mounts'
```

합격: filesystem duration ≤ 0.5 s, scrape timeout 0.

---

## NE-05 / NE-06 — 노드 자원 포화 (CPU / Disk)

**목표**: 노드 자체 CPU 90% / 디스크 IO 포화 시 node-exporter 거동.

### NE-05 CPU 포화

```bash
# 1. stress-ng로 CPU 90% 4코어
kubectl --context=$CTX -n load-test run stress --image=alexeiled/stress-ng --restart=Never -- \
  --cpu 4 --cpu-load 90 --timeout 5m

# 2. 부하 중 node-exporter 측정
sleep 60
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=scrape_duration_seconds{job="node-exporter"}' | jq

# 3. 노드 CPU 확인 (부하 진입 검증)
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m]))' | jq -r '.data.result[0].value[1]'
# 0.9 근접

# 4. 정리
kubectl --context=$CTX -n load-test delete pod stress
```

### NE-06 Disk IO 포화

```bash
# 1. fio
kubectl --context=$CTX -n load-test run fio --image=lpabon/fio --restart=Never -- \
  --name=randwrite --rw=randwrite --bs=4k --size=1G --runtime=300 --time_based

# 2. diskstats collector duration
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=node_scrape_collector_duration_seconds{collector="diskstats"}' | jq

# 3. 정리
kubectl --context=$CTX -n load-test delete pod fio
```

합격: 어느 경우든 scrape timeout 0, duration ≤ baseline ×2.

---

## NE-07 — Soak 24h

```bash
# Goroutine / FD / RSS 24h 추적
while true; do
  ts=$(date +"%Y-%m-%d %H:%M:%S")
  goroutines=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=go_goroutines{job="node-exporter"}' | jq -r '.data.result[0].value[1]')
  fds=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=process_open_fds{job="node-exporter"}' | jq -r '.data.result[0].value[1]')
  rss=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=process_resident_memory_bytes{job="node-exporter"}' | jq -r '.data.result[0].value[1]')
  echo -e "$ts\t$goroutines\t$fds\t$rss"
  sleep 3600
done | tee /tmp/$TEST_ID-NE07-soak.tsv
```

합격: goroutines / FD monotonic 증가 없음.

---

## 결과 확인 공통 패턴

각 시나리오 진행 시 다음 4가지를 함께 보면 누수·이상을 빠르게 감지:

| 관측 | 도구 | 명령 / 위치 |
|---|---|---|
| Pod 상태 | kubectl | `kubectl get pods,events --sort-by=.lastTimestamp` |
| 도구 stdout | kubectl logs | `kubectl logs job/<name>` |
| 메트릭 (정량) | curl + Prom API | 본 문서 PromQL |
| 시각화 (정성) | Grafana | dashboard `lt-node-exporter` row "NE-XX" |

결과 보관:
```bash
mkdir -p /tmp/$TEST_ID
cp /tmp/$TEST_ID-NE*.* /tmp/$TEST_ID/
# Grafana 대시보드 → "Share" → "Export" → "Save as JSON" → /tmp/$TEST_ID/*.json
# Grafana 패널 → "Inspect" → "Panel JSON" → "Data" → "Download CSV"
```
