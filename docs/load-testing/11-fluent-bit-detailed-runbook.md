# 11. Fluent-bit 상세 부하 테스트 runbook

`02-fluent-bit-load-test.md`의 FB-01~07 시나리오를 **명령 단위로 분해한 절차서**입니다. 자동화 스크립트 없이 운영자가 한 줄씩 실행하며 매 단계 검증할 수 있도록 구성했습니다.

## 공통 사전 준비

```bash
# 0.1 환경 변수 (운영자가 수정)
export CTX=minikube-remote                              # 운영: prod-cluster-1
export PROM=http://192.168.101.197:9090                 # 운영: https://prometheus.intranet
export OS=http://opensearch-lt-node.monitoring.svc:9200 # 운영: https://opensearch.intranet:9200
export TEST_ID=LT-$(date +%Y%m%d)-FB                    # 결과 기록용 ID

# 0.2 클러스터 health 확인
kubectl --context=$CTX get nodes
kubectl --context=$CTX -n monitoring get pods | grep -E "fluent-bit|opensearch"

# 0.3 ServiceMonitor 픽업 검증
kubectl --context=$CTX -n monitoring get servicemonitor fluent-bit-lt -o yaml | grep -A2 endpoints

# 0.4 베이스라인 — 부하 없이 5분 캡처 (Grafana 시간 범위 기록)
echo "Baseline start: $(date +%H:%M:%S)"
sleep 300
echo "Baseline end:   $(date +%H:%M:%S)"

# 0.5 알람 silence (운영 시 필수)
# amtool --alertmanager.url=$AM silence add matchers='alertname=~"FluentBit.*"' duration=2h
```

✅ **체크포인트 0**: ServiceMonitor 적용됨, baseline 시간 범위 기록함, 알람 silence 적용됨.

---

## FB-01 — 단일 Pod throughput ceiling

**목표**: per-pod 처리량 ≥ 50,000 lines/s, drop = 0 검증.

### 단계 1. flog 단일 Pod 배포

```bash
# 1.1 flog 1개로 시작 (점진 증가용 baseline)
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=1
kubectl --context=$CTX -n load-test get pods -l app=flog-loader -w   # Ctrl+C로 빠져나옴

# 1.2 flog가 로그 생성 중인지 확인
POD=$(kubectl --context=$CTX -n load-test get pod -l app=flog-loader -o jsonpath='{.items[0].metadata.name}')
kubectl --context=$CTX -n load-test logs $POD --tail=3
```

✅ **체크포인트 1**: flog Pod Running, JSON 로그 출력 확인.

### 단계 2. Fluent-bit input rate 확인 (5분 후)

```bash
# 2.1 입력 속도 (per-pod)
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(fluentbit_input_records_total[1m])' | jq '.data.result[] | {pod: .metric.pod, rate: .value[1]}'

# 2.2 출력 속도
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(fluentbit_output_proc_records_total[1m])' | jq '.data.result[] | {pod: .metric.pod, rate: .value[1]}'

# 2.3 drop 여부
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(fluentbit_output_dropped_records_total[1m])' | jq '.data.result[]'
```

✅ **체크포인트 2**: input rate 측정값 기록 (예: 5,000 lines/s), output rate ≈ input rate, drop = 0.

### 단계 3. flog 부하 단계적 증가 (×2 → ×5 → ×10)

```bash
# 3.1 ×2 부하 (replicas 2)
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=2
sleep 180   # 3분 sustain
RATE2=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(rate(fluentbit_input_records_total[1m]))' | jq -r '.data.result[0].value[1]')
echo "T=replicas2: $RATE2 lines/s"

# 3.2 ×5 부하
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=5
sleep 180
RATE5=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(rate(fluentbit_input_records_total[1m]))' | jq -r '.data.result[0].value[1]')
echo "T=replicas5: $RATE5 lines/s"

# 3.3 ×10 부하 (FB ceiling 탐색)
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=10
sleep 300   # 5분 sustain (한계 도달)
RATE10=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(rate(fluentbit_input_records_total[1m]))' | jq -r '.data.result[0].value[1]')
echo "T=replicas10: $RATE10 lines/s"
```

✅ **체크포인트 3**: 단계별 rate 기록. ×10에서 FB CPU throttling 발생 여부 다음 단계에서 확인.

### 단계 4. FB 자원 포화 확인

```bash
# 4.1 FB Pod CPU 사용률
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}[1m])' | \
  jq '.data.result[] | {pod: .metric.pod, cpu: .value[1]}'

# 4.2 FB throttling 발생 여부
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(container_cpu_cfs_throttled_seconds_total{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}[1m])' | \
  jq '.data.result[] | {pod: .metric.pod, throttled: .value[1]}'

# 4.3 FB RSS
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=container_memory_working_set_bytes{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}' | \
  jq '.data.result[] | {pod: .metric.pod, rss_mb: (.value[1] | tonumber / 1024 / 1024)}'

# 4.4 송신 vs 수신 일치 확인 (drop 검증)
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(rate(fluentbit_input_records_total[1m])) - sum(rate(fluentbit_output_proc_records_total[1m]))' | \
  jq -r '.data.result[0].value[1] // "0"'   # 0 근접이 정상
```

✅ **체크포인트 4**: CPU < limit 70%, throttling = 0, RSS 안정, 입출력 차이 ≈ 0.

### 단계 5. FB-01 합격 판정

| 지표 | 기준 | 실측 | 판정 |
|------|------|------|------|
| per-pod throughput | ≥ 50,000 lines/s | (단계 3 측정값/replicas 수) | |
| drop | 0 | (단계 4.4) | |
| CPU throttling | 0 | (단계 4.2) | |
| RSS | ≤ limit 70% | (단계 4.3) | |

### 단계 6. 정리

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
sleep 30   # buffer drain 대기
# 상태 확인 — backlog 0 회복?
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '.data.result[0].value[1]'
```

✅ **FB-01 종료**.

---

## FB-02 — 정상 운영 부하 (1시간)

**목표**: 평균 부하 1시간 유지 시 buffer 누적 없음, CPU/RSS ≤ limit 70%.

### 단계 1. 운영 평균값 재현

```bash
# 1.1 flog 평균 부하 (운영 200 노드 모사)
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=3
kubectl --context=$CTX -n load-test edit configmap lt-config
# FLOG_DELAY: "500us"  ← 부하 낮춤 (testbed)
kubectl --context=$CTX -n load-test rollout restart deploy flog-loader

# 1.2 1시간 sustain
echo "T0: $(date +%H:%M:%S)"
```

✅ **체크포인트 1**: flog 3 replicas Running, 부하 시작.

### 단계 2. 5분마다 6회 sample 수집 (총 30분)

```bash
# 2.1 sampling loop (직접 실행, 결과 텍스트로 저장)
for i in 1 2 3 4 5 6; do
  echo "=== Sample $i at $(date +%H:%M:%S) ==="
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=sum(rate(fluentbit_input_records_total[5m]))' | jq -r '.data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=sum(rate(fluentbit_output_proc_records_total[5m]))' | jq -r '.data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '.data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=container_memory_working_set_bytes{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}' | jq -r '.data.result[0].value[1]'
  sleep 300
done > /tmp/$TEST_ID-fb02-samples.txt
```

✅ **체크포인트 2**: 6개 샘플 모두 input ≈ output, backlog 0 근처, RSS 안정.

### 단계 3. 1시간 후 합격 판정

| 지표 | 기준 | 명령 |
|---|---|---|
| 1h drop 누적 | 0 | `curl -sG "$PROM/api/v1/query" --data-urlencode 'query=increase(fluentbit_output_dropped_records_total[1h])'` |
| 1h backlog 평균 | < 50 MB | `curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(sum(fluentbit_input_storage_chunks_busy_bytes)[1h:1m])'` |
| CPU peak | ≤ limit 70% | Grafana 1h 시간 범위 |
| RSS drift | < 10% | sample 첫 번째 vs 마지막 비교 |

### 단계 4. 정리

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
```

---

## FB-03 — Output 장애 주입 (Chaos)

**목표**: OpenSearch 다운 시 FB filesystem buffer 적재, 복구 시 자동 backlog 소진, 데이터 손실 0.

### 단계 1. 부하 시작 + 베이스라인 30분

```bash
# 1.1 평균 부하 (FB-02와 동일)
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=3
echo "T0: $(date +%H:%M:%S) — 30분 sustain 후 chaos 트리거"

# 1.2 30분 후 송신 카운트 기록 (장애 전 기준)
SENT_BEFORE=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(fluentbit_output_proc_records_total)' | jq -r '.data.result[0].value[1]')
echo "Before chaos: sent=$SENT_BEFORE"

# 1.3 OS 인덱스 docs.count 기록
RECV_BEFORE=$(kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/logs-fb-*/_count" | jq -r '.count')
echo "Before chaos: indexed=$RECV_BEFORE"
```

✅ **체크포인트 1**: 송수신 카운트 기록 (이후 손실 검증의 기준).

### 단계 2. OpenSearch 다운 트리거

```bash
# 2.1 OpenSearch helm release 일시 삭제 (PVC는 유지)
helm --kube-context=$CTX -n monitoring uninstall opensearch-lt --keep-history
kubectl --context=$CTX -n monitoring get pods | grep opensearch  # Terminating 확인

# 2.2 다운타임 동안 FB 거동 모니터링
echo "Chaos start: $(date +%H:%M:%S)"
for i in 1 2 3 4 5 6; do   # 5분 × 6회
  echo "=== T+$((i*5))min ==="
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=rate(fluentbit_output_errors_total[1m])' | jq -r '.data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=rate(fluentbit_output_retries_total[1m])' | jq -r '.data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '.data.result[0].value[1]'
  sleep 300
done > /tmp/$TEST_ID-fb03-chaos.txt
```

✅ **체크포인트 2**: output_errors > 0 (OS 응답 불가 신호), backlog 단조 증가.

### 단계 3. OpenSearch 복구

```bash
# 3.1 OS 재배포
bash deploy/load-testing/02-logging/install.sh
kubectl --context=$CTX -n monitoring wait --for=condition=ready pod opensearch-lt-node-0 --timeout=300s

echo "Recovery start: $(date +%H:%M:%S)"

# 3.2 backlog 소진 모니터링
for i in 1 2 3 4 5; do
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '.data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=rate(fluentbit_output_proc_records_total[1m])' | jq -r '.data.result[0].value[1]'
  sleep 60
done
```

✅ **체크포인트 3**: backlog 단조 감소 → 0 근접 도달.

### 단계 4. 손실률 검증

```bash
# 4.1 부하 중단
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
sleep 60   # 잔여 buffer drain

# 4.2 카운트 비교
SENT_AFTER=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(fluentbit_output_proc_records_total)' | jq -r '.data.result[0].value[1]')
RECV_AFTER=$(kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/logs-fb-*/_count" | jq -r '.count')

DELTA_SENT=$(echo "$SENT_AFTER - $SENT_BEFORE" | bc)
DELTA_RECV=$(echo "$RECV_AFTER - $RECV_BEFORE" | bc)
LOSS=$(echo "$DELTA_SENT - $DELTA_RECV" | bc)
echo "FB sent=$DELTA_SENT  OS indexed=$DELTA_RECV  loss=$LOSS"
```

✅ **체크포인트 4**: loss = 0 (또는 < 0.001%) 합격.

---

## FB-04 — 멀티라인 스택트레이스

**목표**: 멀티라인 비율 ↑ 시 parser 지연 ≤ 평소 ×1.5.

### 단계 1. loggen-spark Deployment 활용 (UUID + multiline 흉내)

```bash
# 1.1 loggen-spark 배포 (Java 스택트레이스 generator로 변형해도 동일)
kubectl --context=$CTX apply -f deploy/load-testing/03-load-generators/loggen-spark.yaml
sleep 120

# 1.2 FB CPU 비교 (FB-02 baseline 대비)
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}[5m])' | \
  jq '.data.result[]'
```

### 단계 2. 정리

```bash
kubectl --context=$CTX delete -f deploy/load-testing/03-load-generators/loggen-spark.yaml
```

> 멀티라인 전용 generator가 필요하면 loggen-spark.py에 `\n` 포함 메시지 추가 후 재빌드.

---

## FB-05 — 로그 버스트 (Spike)

**목표**: ×30 spike 시 drop 0, backlog 자동 소진.

### 단계 1. 평균 부하 5분

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=3
echo "T0: $(date +%H:%M:%S) baseline 5분 시작"
sleep 300
```

### 단계 2. Spike (×10 testbed, ×30 운영)

```bash
echo "T+5min: spike trigger flog 3→30"
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=30

# Spike 동안 backlog 추적
for i in 1 2 3 4; do
  echo "=== T+$((5+i))min ==="
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(fluentbit_input_records_total[1m]))' | jq -r '.data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '.data.result[0].value[1]'
  sleep 60
done
```

### 단계 3. Spike 종료 + 복구 모니터링

```bash
echo "T+9min: spike end"
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=3

# Backlog 0 복귀 시간 측정
START=$(date +%s)
while [[ $(curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '.data.result[0].value[1]') -gt 1048576 ]]; do
  sleep 10
  echo "T+$(($(date +%s) - START))s: still draining"
done
echo "T+$(($(date +%s) - START))s: backlog drained"
```

✅ **체크포인트 5**: 복구 시간 < 1분 (운영), drop = 0.

### 단계 4. 정리

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
```

---

## FB-06 — Soak 24h

**목표**: 24h 유지 시 RSS drift 없음, FD/threads 안정.

### 단계 1. 평균 부하 시작

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=3
echo "Soak start: $(date)"
```

### 단계 2. 매시간 sample (24h × 1회)

```bash
# 별도 터미널에서 cron 또는 watch로:
while true; do
  ts=$(date +"%Y-%m-%d %H:%M:%S")
  rss=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=sum(container_memory_working_set_bytes{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"})' | jq -r '.data.result[0].value[1]')
  echo "$ts $rss"
  sleep 3600
done | tee /tmp/$TEST_ID-fb06-soak.tsv
```

### 단계 3. 24h 후 평가

```bash
# RSS drift = (last - first) / first
head -1 /tmp/$TEST_ID-fb06-soak.tsv
tail -1 /tmp/$TEST_ID-fb06-soak.tsv
```

합격: drift < 10%, retry 누적 안정.

### 단계 4. 정리

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
```

---

## FB-07 — 대용량 라인 (1 line = 16 KB)

**목표**: bytes/s throughput 측정, CPU ≤ limit 70%.

### 단계 1. 큰 라인 generator

```bash
# flog는 -b 옵션으로 byte size 가능 (또는 loggen-spark.py 변형)
# 임시: flog Deployment env에 더 큰 메시지 주입
kubectl --context=$CTX -n load-test edit deploy flog-loader
# args: ["-f","json","-b","16000","-l"]   ← byte size = 16KB

sleep 300
```

### 단계 2. Bytes throughput

```bash
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(rate(fluentbit_output_proc_bytes_total[1m]))' | jq -r '.data.result[0].value[1]'

curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(rate(fluentbit_input_bytes_total[1m]))/clamp_min(sum(rate(fluentbit_input_records_total[1m])),1)' | jq -r '.data.result[0].value[1]'
# 평균 byte/line ≈ 16000?
```

### 단계 3. 정리

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
```

---

## 결과 확인 공통 패턴

각 시나리오 진행 시 다음 4가지를 함께 보면 누수·이상을 빠르게 감지할 수 있습니다.

### 1. kubectl 명령 (Pod 거동)

```bash
# Pod 상태 + 최근 events
kubectl --context=$CTX -n load-test get pods,events --sort-by=.lastTimestamp | tail -20
kubectl --context=$CTX -n monitoring get pods -l app.kubernetes.io/name=fluent-bit
# 실시간 로그 (최근 100줄, 따라가기)
kubectl --context=$CTX -n monitoring logs -l app.kubernetes.io/name=fluent-bit --tail=100 -f
# 자원 사용량
kubectl --context=$CTX -n monitoring top pod -l app.kubernetes.io/name=fluent-bit
```

### 2. PromQL (정량 측정 — 핵심 8개)

```bash
# 핵심 지표 한꺼번에 sample
PROM=http://192.168.101.197:9090
for q in \
  "input rate|sum(rate(fluentbit_input_records_total[1m]))" \
  "output rate|sum(rate(fluentbit_output_proc_records_total[1m]))" \
  "drop rate|sum(rate(fluentbit_output_dropped_records_total[1m]))" \
  "errors|sum(rate(fluentbit_output_errors_total[1m]))" \
  "retries|sum(rate(fluentbit_output_retries_total[1m]))" \
  "retries-failed|sum(rate(fluentbit_output_retries_failed_total[1m]))" \
  "backlog bytes|sum(fluentbit_input_storage_chunks_busy_bytes)" \
  "rss bytes|sum(container_memory_working_set_bytes{namespace=\"monitoring\",pod=~\"fluent-bit.*\",container=\"fluent-bit\"})"; do
  name="${q%|*}"; expr="${q#*|}"
  val=$(curl -sG "$PROM/api/v1/query" --data-urlencode "query=$expr" | jq -r '.data.result[0].value[1] // "NONE"')
  printf "  %-20s %s\n" "$name" "$val"
done
```

### 3. Grafana (정성 시각화)

| 시나리오 | 대시보드 | 패널 (row) | 정상 패턴 |
|---|---|---|---|
| FB-01 | `Load Test • Fluent-bit` | row "Throughput (FB-01)" | input/output 곡선 동기 |
| FB-02 | 동 | row "Buffer / Resource (FB-02)" | RSS 평탄 |
| FB-03 | 동 | row "Reliability (FB-03/05)" | errors/retries spike → 0 복귀 |
| FB-04 | 동 | row "Throughput" + CPU panel | CPU 일시 상승 |
| FB-05 | 동 | row "Reliability" | input·output rate divergence + backlog 급증→소진 |
| FB-06 | 동 | row "Buffer / Resource" | RSS 24h 평탄 |
| FB-07 | 동 | row "Buffer / Resource" — Output Throughput (Bps) | bytes/s 그래프가 핵심 |

스냅샷 저장:
```bash
# Grafana UI: 대시보드 → 우상단 "Share" → "Snapshot" 또는 "Export" → "Save as JSON"
# 패널별 CSV: 패널 우측 ⋯ → "Inspect" → "Data" → "Download CSV"
# API로 dashboard JSON 일괄 export
curl -s -u admin:admin \
  "http://192.168.101.197:3000/api/dashboards/uid/lt-fluent-bit" \
  > /tmp/$TEST_ID-fb-dashboard.json
```

### 4. 송수신 카운트 대조 (FB-03 손실 검증의 핵심)

```bash
# OS 인덱스의 docs.count vs FB output_records_total
SENT=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(fluentbit_output_proc_records_total)' | jq -r '.data.result[0].value[1]')
RECV=$(kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/logs-fb-*/_count" | jq -r '.count')
echo "FB sent total: $SENT"
echo "OS indexed total: $RECV"
echo "Loss: $(echo "$SENT - $RECV" | bc) records"
```

## 결과 기록

각 시나리오 종료 후 `10-test-plan-and-results.md` §10 템플릿에 결과 기록:
- `LT-YYYYMMDD-FB01`, `LT-YYYYMMDD-FB02`, ...
- 측정값, 합격/실패 판정, Grafana 스냅샷, 튜닝 적용 diff

```bash
# 모든 결과를 단일 디렉토리에 보관
mkdir -p /tmp/$TEST_ID
cp /tmp/$TEST_ID-fb*.* /tmp/$TEST_ID/
# tar로 묶어서 결과 리포지토리 또는 공유 드라이브에 보관
tar -czf /tmp/$TEST_ID-results.tar.gz -C /tmp $TEST_ID/
ls -lh /tmp/$TEST_ID-results.tar.gz
```
