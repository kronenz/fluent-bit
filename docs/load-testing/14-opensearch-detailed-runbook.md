# 14. OpenSearch 상세 부하 테스트 runbook

`01-opensearch-load-test.md`의 OS-01~07 + 신규 OS-08/09/12/14/16을 명령 단위 + 결과 확인 절차로 분해.

워크로드 가정: 200대 cluster (Spark/Trino/Airflow) 로그 ingest 주, 검색은 6팀 간헐적.

## 공통 사전 준비

```bash
export CTX=minikube-remote
export PROM=http://192.168.101.197:9090
export OS=http://opensearch-lt-node.monitoring.svc:9200
export TEST_ID=LT-$(date +%Y%m%d)-OS

# 0.1 OpenSearch health
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/_cluster/health" | jq

# 0.2 elasticsearch_exporter sidecar 정상
kubectl --context=$CTX -n monitoring get deploy opensearch-exporter
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=up{job="opensearch-exporter"}' | jq -r '.data.result[0].value[1]'

# 0.3 베이스라인 정보 기록 (이후 비교용)
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/_cat/indices?v" | tee /tmp/$TEST_ID-indices-before.txt
```

✅ **체크포인트 0**: cluster health 확인, exporter up=1, 인덱스 현황 기록.

---

## OS-01 — Bulk Indexing Baseline (`--test-mode`, 오프라인 workloads)

**목표**: opensearch-benchmark 도구가 운영망에서 오프라인 동작하는지 확인 + indexing TPS baseline.

### 단계 1. Job 적용

```bash
# 1.1 매니페스트 검증
kubectl --context=$CTX -n load-test get configmap lt-config -o jsonpath='{.data.OSB_WORKLOAD}'; echo
kubectl --context=$CTX -n load-test get configmap lt-config -o jsonpath='{.data.OPENSEARCH_URL}'; echo

# 1.2 기존 Job 정리 후 시작
kubectl --context=$CTX -n load-test delete job opensearch-benchmark --ignore-not-found
kubectl --context=$CTX apply -f deploy/load-testing/04-test-jobs/opensearch-benchmark.yaml
echo "T0: $(date +%H:%M:%S)"
```

### 단계 2. Pod 시작 + 워크로드 적재 검증

```bash
# 2.1 Pod 진행 상황
kubectl --context=$CTX -n load-test get pod -l app=opensearch-benchmark -w &
WATCHER=$!
sleep 30; kill $WATCHER 2>/dev/null

# 2.2 워크로드 경로가 image 안에 박혀있는지 (인터넷 의존성 0 확인)
POD=$(kubectl --context=$CTX -n load-test get pod -l app=opensearch-benchmark -o jsonpath='{.items[0].metadata.name}')
kubectl --context=$CTX -n load-test exec $POD -- bash -c 'ls /opt/osb-workloads/$OSB_WORKLOAD | head -5'
# index.json, files.txt 등 보여야 함
```

✅ **체크포인트 1**: Pod Running, 워크로드 정의가 image 안에 있음.

### 단계 3. 진행 모니터링 (--test-mode = 1k docs, 보통 30초~수분)

```bash
# 3.1 실시간 로그
kubectl --context=$CTX -n load-test logs job/opensearch-benchmark -f --tail=20 &
LOG_PID=$!

# 3.2 indexing rate 측정 (별도 터미널 또는 sleep 후)
sleep 30
curl -sG "$PROM/api/v1/query" --data-urlencode \
  'query=sum(rate(elasticsearch_indices_indexing_index_total[1m]))' | jq -r '.data.result[0].value[1]'

# 3.3 완료 대기
kubectl --context=$CTX -n load-test wait --for=condition=complete \
  job/opensearch-benchmark --timeout=10m
kill $LOG_PID 2>/dev/null
```

### 단계 4. 결과 확인

```bash
# 4.1 stdout summary 추출
kubectl --context=$CTX -n load-test logs job/opensearch-benchmark | tee /tmp/$TEST_ID-OS01-bench.log
grep -E "SUCCESS|FAILURE|took|Test Execution" /tmp/$TEST_ID-OS01-bench.log

# 4.2 result.json (Pod 살아있을 때만)
POD=$(kubectl --context=$CTX -n load-test get pod -l app=opensearch-benchmark -o jsonpath='{.items[0].metadata.name}')
kubectl --context=$CTX -n load-test exec $POD -- cat /tmp/result.json 2>/dev/null > /tmp/$TEST_ID-OS01-result.json
jq '.results.op_metrics[] | {op: .operation, throughput: .throughput, latency: .latency}' /tmp/$TEST_ID-OS01-result.json | head -30

# 4.3 인덱스 docs 추가 확인
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/_cat/indices/geonames?v"
```

### 단계 5. 결과 확인 — Grafana

| 대시보드 | 패널 (row) | 정상 패턴 |
|---|---|---|
| `Load Test • OpenSearch` row "OS-01 Indexing" | "Indexing Rate (docs/s)" | Job 진행 중 곡선 step-up, 종료 시 0 |
| 동 | "Bulk Reject Rate" | 0 유지 |
| 동 | "Indexing Latency avg" | < 50 ms |

### 단계 6. 합격 판정

| 지표 | 기준 | 실측 | 판정 |
|---|---|---|---|
| Job 완료 | SUCCESS | (단계 4.1) | |
| 인터넷 의존성 | 0 | (워크로드 image 안) | ✓ |
| Bulk reject | 0 | (단계 5) | |
| Indexing TPS | (testbed 기준값 기록) | (단계 4) | |

### 단계 7. 정리

```bash
kubectl --context=$CTX -n load-test delete job opensearch-benchmark --ignore-not-found
# 인덱스는 보관 (이후 비교용). 정리 시:
# kubectl exec ... -- curl -X DELETE "$OS/geonames"
```

---

## OS-08 — Sustained High Ingest (200대 모사)

**목표**: 운영 200대 cluster의 sustainable ingest TPS 정량화.

### 단계 1. flog scale-up 단계적 (5 → 20 → 50 → 100 → 200)

```bash
# 1.1 평균값 출발 (FLOG_DELAY=100us 가정)
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=5
echo "T0: $(date +%H:%M:%S)  replicas=5"
sleep 600   # 10분 sustain

# 1.2 5분마다 단계적 증가 (각 단계 sustain 5분)
for R in 20 50 100 200; do
  kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=$R
  echo "T+: $(date +%H:%M:%S) replicas=$R, 10분 sustain"
  sleep 600
  
  # 단계별 sample
  TPS=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(sum(rate(elasticsearch_indices_indexing_index_total[1m]))[5m:30s])' | jq -r '.data.result[0].value[1]')
  HEAP=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=max_over_time((elasticsearch_jvm_memory_used_bytes{area="heap"}/elasticsearch_jvm_memory_max_bytes{area="heap"}*100)[5m:30s])' | jq -r '.data.result[0].value[1]')
  REJ=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=increase(elasticsearch_thread_pool_rejected_count{type="write"}[5m])' | jq -r '.data.result[0].value[1]')
  echo "  replicas=$R: avg TPS=$TPS, peak heap=$HEAP%, rejects (5m)=$REJ"
done
```

✅ **체크포인트 1**: 단계별 TPS / heap / reject 기록. heap > 75% 또는 reject > 0 시점이 sustainable 한계.

### 단계 2. 진행 중 4축 결과 확인

```bash
# 2.1 PromQL — 1분마다 핵심 지표
PROM=http://192.168.101.197:9090
for q in \
  "indexing TPS|sum(rate(elasticsearch_indices_indexing_index_total[1m]))" \
  "bulk reject|rate(elasticsearch_thread_pool_rejected_count{type=\"write\"}[1m])" \
  "heap %|elasticsearch_jvm_memory_used_bytes{area=\"heap\"}/elasticsearch_jvm_memory_max_bytes{area=\"heap\"}*100" \
  "segment count|elasticsearch_indices_segments_count" \
  "FB output rate|sum(rate(fluentbit_output_proc_records_total[1m]))" \
  "FB backlog|sum(fluentbit_input_storage_chunks_busy_bytes)" \
  "FB output errors|sum(rate(fluentbit_output_errors_total[1m]))"; do
  name="${q%|*}"; expr="${q#*|}"
  val=$(curl -sG "$PROM/api/v1/query" --data-urlencode "query=$expr" | jq -r '.data.result[0].value[1] // "NONE"')
  printf "  %-25s %s\n" "$name" "$val"
done

# 2.2 OpenSearch 측 Cat API로 실시간 점검
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- bash -c "
  echo === pending ===
  curl -s '$OS/_cluster/pending_tasks' | jq '.tasks | length'
  echo === thread_pool write ===
  curl -s '$OS/_cat/thread_pool/write?v'
  echo === segments ===
  curl -s '$OS/_cat/segments/logs-fb-*?v&h=index,segment,size,docs.count' | head -5
"
```

### 단계 3. 결과 확인 — Grafana

| 대시보드 | 패널 (row "OS-08") | 정상 / 이상 |
|---|---|---|
| `Load Test • OpenSearch` | "Sustained Indexing TPS" | 각 단계에서 평탄선, 한계 도달 시 점진 하락 |
| 동 | "Bulk Reject (sustained)" | 0 유지가 정상; 비제로 시점 = 한계 |
| 동 | "Heap % (long range)" | 75% 도달 시 GC 영향 |
| 동 | "FB Output vs OS Indexing Rate" | 두 곡선 동기화. divergence = drop 위험 |
| 동 | "Segment Count (merge keep up?)" | 단조 증가는 merge 못 따라옴 |

### 단계 4. 합격 판정

| 지표 | 기준 | 실측 | 판정 |
|---|---|---|---|
| 1h reject 누적 | 0 | (단계 1 또는 PromQL `increase[1h]`) | |
| FB output_errors | 0 | (단계 2.1) | |
| OS heap max | ≤ 75% | (단계 1) | |
| Sustainable TPS | (운영 30k+) | (단계 1 곡선의 무리 없는 최대값) | |

### 단계 5. 정리

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
sleep 60   # backlog drain
```

---

## OS-09 — Spark Job Startup Burst (×30)

**목표**: spike 흡수, drop 0, OS green 유지.

### 단계 1. 평균 부하 5분

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=3
echo "Baseline T0: $(date +%H:%M:%S)"
sleep 300

# 송신 카운트 기준점
SENT_PRE=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(fluentbit_output_proc_records_total)' | jq -r '.data.result[0].value[1]')
RECV_PRE=$(kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- curl -s "$OS/logs-fb-*/_count" | jq -r '.count')
echo "Pre-burst: sent=$SENT_PRE indexed=$RECV_PRE"
```

### 단계 2. Burst 시작 (4분 ×30)

```bash
echo "Burst start: $(date +%H:%M:%S)"
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=90    # 운영 ×30
# testbed 한계: replicas=20 정도

# Burst 동안 1분마다 sample
for i in 1 2 3 4; do
  echo "=== T+${i}min ==="
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(fluentbit_input_records_total[1m]))' | jq -r '"input rate: " + .data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(fluentbit_output_proc_records_total[1m]))' | jq -r '"output rate: " + .data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '"backlog bytes: " + .data.result[0].value[1]'
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=increase(elasticsearch_thread_pool_rejected_count{type="write"}[1m])' | jq -r '"OS rejects/min: " + .data.result[0].value[1]'
  sleep 60
done | tee /tmp/$TEST_ID-OS09-burst.log
```

### 단계 3. Burst 종료 + 복구 측정

```bash
echo "Burst end: $(date +%H:%M:%S)"
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=3

# Backlog 0 도달까지 시간 측정
START=$(date +%s)
while true; do
  BACKLOG=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(fluentbit_input_storage_chunks_busy_bytes)' | jq -r '.data.result[0].value[1]')
  ELAPSED=$(($(date +%s) - START))
  echo "T+${ELAPSED}s: backlog=$BACKLOG bytes"
  [[ $(echo "$BACKLOG < 1048576" | bc) -eq 1 ]] && break
  sleep 10
  [[ $ELAPSED -gt 600 ]] && { echo "Recovery > 10min, ABORT"; break; }
done
echo "Recovery time: ${ELAPSED}s"
```

### 단계 4. 손실률 검증

```bash
sleep 60   # FB 잔여 buffer drain
SENT_POST=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(fluentbit_output_proc_records_total)' | jq -r '.data.result[0].value[1]')
RECV_POST=$(kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- curl -s "$OS/logs-fb-*/_count" | jq -r '.count')
DSENT=$(echo "$SENT_POST - $SENT_PRE" | bc)
DRECV=$(echo "$RECV_POST - $RECV_PRE" | bc)
echo "FB sent: $DSENT, OS indexed: $DRECV, loss: $(echo "$DSENT - $DRECV" | bc)"
```

### 단계 5. Grafana 확인

| 패널 | 정상 패턴 |
|---|---|
| row "OS-09" — "Indexing TPS (spike profile)" | 3-line: FB input ↑ 즉시, FB output ↑ OS 한계까지, OS indexing ↑ 평탄 |
| 동 — "FB Storage Backlog (spike + drain)" | spike 중 누적, 종료 후 단조 감소 |
| 동 — "Cluster Status (must stay green)" | 1 유지 |

### 단계 6. 합격 판정

| 지표 | 기준 | 실측 | 판정 |
|---|---|---|---|
| Drop (loss) | 0 | (단계 4) | |
| Backlog 소진 시간 | < 1분 | (단계 3 ELAPSED) | |
| Cluster green | 유지 | (단계 5) | |

### 단계 7. 정리

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
```

---

## OS-12 — Refresh Interval 튜닝 (1s vs 30s vs 60s)

**목표**: refresh_interval 변경 시 indexing TPS / segment count 영향.

### 단계 1. 동일 부하 시작 (replicas 고정)

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=20
sleep 300   # 5분 안정화
```

### 단계 2. 3구간 비교 (각 30분 sustain)

```bash
for INTERVAL in 1s 30s 60s; do
  T_START=$(date +%H:%M:%S)
  echo "=== refresh_interval=${INTERVAL} start at $T_START ==="
  
  # 2.1 설정 적용
  kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
    curl -sX PUT "$OS/logs-fb-*/_settings" \
    -H 'Content-Type: application/json' \
    -d "{\"index\": {\"refresh_interval\": \"${INTERVAL}\"}}"
  
  # 2.2 1800초 sustain
  sleep 1800
  
  # 2.3 결과 sample
  TPS=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(sum(rate(elasticsearch_indices_indexing_index_total[1m]))[30m:1m])' | jq -r '.data.result[0].value[1]')
  REFRESH_OPS=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(rate(elasticsearch_indices_refresh_total[2m])[30m:1m])' | jq -r '.data.result[0].value[1]')
  REFRESH_TIME=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(rate(elasticsearch_indices_refresh_time_seconds_total[2m])[30m:1m])' | jq -r '.data.result[0].value[1]')
  SEG=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=avg_over_time(elasticsearch_indices_segments_count[30m:1m])' | jq -r '.data.result[0].value[1]')
  echo "  ${INTERVAL}: TPS=$TPS, refresh_ops/s=$REFRESH_OPS, refresh_time/s=$REFRESH_TIME, segments=$SEG"
done | tee /tmp/$TEST_ID-OS12-tuning.log
```

### 단계 3. 비교 분석

```bash
# 3.1 결과 정리
cat /tmp/$TEST_ID-OS12-tuning.log

# 3.2 Grafana — 시간 범위로 3구간 시각 비교
# UI: 우상단 시간 선택기 → 각 구간 30분 범위로 zoom → 패널별 평균값 비교
```

### 단계 4. 합격 판정

| 지표 | 1s (default) | 30s | 60s |
|---|---|---|---|
| TPS | (baseline) | ≥ baseline ×1.3 | ≥ baseline ×1.4 |
| refresh ops/s | ~1 | ~0.03 | ~0.017 |
| refresh time/s | (높음) | 70% 감소 | 90% 감소 |
| segments (count) | (많음) | 적음 | 가장 적음 |

### 단계 5. 정리 — 운영 적용 결정

```bash
# 검색 가시성 SLO 협상 후 운영 인덱스 template에 적용:
# kubectl exec opensearch-... -- curl -X PUT "$OS/_index_template/logs-fb-template" \
#   -H 'Content-Type: application/json' -d '{
#     "index_patterns": ["logs-fb-*"],
#     "template": { "settings": { "index.refresh_interval": "30s" } }
#   }'

# 부하 종료
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
```

---

## OS-14 — High-Cardinality Field 폭증

**목표**: Spark `task_attempt_id` 등 고유값 keyword가 매핑·heap에 미치는 압박.

### 단계 1. loggen-spark Deployment 적용

```bash
# 1.1 변경 전 매핑 필드 수 기록
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/logs-fb-*/_mapping" | jq '[.. | objects | select(has("type"))] | length' \
  > /tmp/$TEST_ID-OS14-fields-before.txt
echo "Fields before: $(cat /tmp/$TEST_ID-OS14-fields-before.txt)"

# 1.2 loggen-spark 배포 (3 replicas, UUID 주입)
kubectl --context=$CTX apply -f deploy/load-testing/03-load-generators/loggen-spark.yaml
kubectl --context=$CTX -n load-test get pods -l app=loggen-spark
```

### 단계 2. 30분 진행 + 5분마다 매핑 모니터링

```bash
for i in 1 2 3 4 5 6; do
  ts=$(date +%H:%M:%S)
  fields=$(kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
    curl -s "$OS/logs-fb-*/_mapping" | jq '[.. | objects | select(has("type"))] | length')
  pending=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=elasticsearch_cluster_health_number_of_pending_tasks' | jq -r '.data.result[0].value[1]')
  heap=$(curl -sG "$PROM/api/v1/query" --data-urlencode \
    'query=elasticsearch_jvm_memory_used_bytes{area="heap"}/elasticsearch_jvm_memory_max_bytes{area="heap"}*100' | jq -r '.data.result[0].value[1]')
  echo "$ts  fields=$fields  pending_tasks=$pending  heap=${heap}%"
  sleep 300
done | tee /tmp/$TEST_ID-OS14-progression.log
```

### 단계 3. 결과 확인 — cluster state size

```bash
# 3.1 cluster state 크기
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/_cluster/state?filter_path=metadata.indices.*.mappings" -o /dev/null -w "%{size_download}\n"

# 3.2 indices stats — segment / fielddata memory
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "$OS/_stats/segments,fielddata" | \
  jq '._all.total | {segments_memory: .segments.memory_in_bytes, fielddata_memory: .fielddata.memory_size_in_bytes}'
```

### 단계 4. 결과 확인 — Grafana

| 대시보드 | 패널 (row "OS-14") | 정상 / 이상 |
|---|---|---|
| `Load Test • OpenSearch` | "Indices Memory Usage" | 점진 증가 (UUID 누적) |
| 동 | "Pending Cluster Tasks" | 0 ~ 일시 1~2 (정상), 누적은 master 부담 |
| 동 | "OS Heap %" | 75% 미만 유지 |

### 단계 5. 합격 판정

| 지표 | 기준 | 실측 |
|---|---|---|
| 매핑 필드 수 | < 1000 | (단계 2) |
| Pending tasks | 0 또는 일시적 | (단계 2) |
| Heap | ≤ 75% | (단계 2) |
| Cluster state size | 안정 | (단계 3.1) |

### 단계 6. 정리

```bash
kubectl --context=$CTX delete -f deploy/load-testing/03-load-generators/loggen-spark.yaml
# 운영: 다음 ILM rollover로 매핑 reset
```

---

## OS-16 — Heavy Ingest + Light Search

**목표**: 운영 통합 — 200대 ingest 부하 중 6팀 검색이 SLO (p95 ≤ 5s) 만족.

### 단계 1. Heavy ingest 시작 (OS-08과 동일)

```bash
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=50
echo "Ingest baseline T0: $(date +%H:%M:%S)"
sleep 300   # 5분 안정화
```

### 단계 2. Light search Job (6 VU, 30분)

```bash
# 2.1 lt-config 변수 확인
kubectl --context=$CTX -n load-test get configmap lt-config -o jsonpath='{.data.OS_INDEX_PATTERN}'; echo

# 2.2 Job 시작
kubectl --context=$CTX apply -f deploy/load-testing/04-test-jobs/k6-opensearch-light-search.yaml

# 2.3 k6 진행 모니터링 (별도 터미널)
kubectl --context=$CTX -n load-test logs job/k6-opensearch-light-search -f --tail=10 &
LOG_PID=$!
```

### 단계 3. 진행 중 양방향 영향 측정

```bash
# 3.1 5분마다 양 측면 sample
for i in 1 2 3 4 5 6; do
  echo "=== T+${i}*5min ==="
  # Indexing 측면
  TPS=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(elasticsearch_indices_indexing_index_total[1m]))' | jq -r '.data.result[0].value[1]')
  echo "  indexing TPS: $TPS"
  # Search 측면
  QPS=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=sum(rate(elasticsearch_indices_search_query_total[1m]))' | jq -r '.data.result[0].value[1]')
  AVG_LAT=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=rate(elasticsearch_indices_search_query_time_seconds_total[1m])/clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)' | jq -r '.data.result[0].value[1]')
  echo "  search QPS: $QPS, avg latency: ${AVG_LAT}s"
  # Resource
  HEAP=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=elasticsearch_jvm_memory_used_bytes{area="heap"}/elasticsearch_jvm_memory_max_bytes{area="heap"}*100' | jq -r '.data.result[0].value[1]')
  echo "  heap: ${HEAP}%"
  sleep 300
done | tee /tmp/$TEST_ID-OS16-progression.log
```

### 단계 4. Job 완료 + k6 stdout 분석

```bash
kubectl --context=$CTX -n load-test wait --for=condition=complete \
  job/k6-opensearch-light-search --timeout=45m
kill $LOG_PID 2>/dev/null

# 4.1 k6 핵심 지표
kubectl --context=$CTX -n load-test logs job/k6-opensearch-light-search > /tmp/$TEST_ID-OS16-k6.log
grep -E "checks|http_req_duration|http_req_failed|http_reqs" /tmp/$TEST_ID-OS16-k6.log
```

### 단계 5. 결과 확인 — Grafana

| 대시보드 | 패널 (row "OS-16") | 정상 패턴 |
|---|---|---|
| `Load Test • OpenSearch` | "Indexing TPS (during light search)" | OS-08 단독 대비 평탄, drop ≤ 5% |
| 동 | "Light Search Rate" | 6 VU 평균 (~6 qps) |
| 동 | "Search Latency avg" | < 1s (서버 평균) |
| 동 | "Active Search/Write Threads" | 두 thread pool 모두 활성 |

### 단계 6. 합격 판정

| 지표 | 기준 | 실측 |
|---|---|---|
| Indexing TPS | ≥ OS-08 단독 95% | (단계 3.1) |
| http_req_duration p95 | ≤ 5s | (단계 4.1, k6 stdout) |
| http_req_failed rate | < 1% | (단계 4.1) |

### 단계 7. 정리

```bash
kubectl --context=$CTX -n load-test delete job k6-opensearch-light-search
kubectl --context=$CTX -n load-test scale deploy flog-loader --replicas=0
```

---

## OS-03 — Heavy Aggregation

```bash
# 단계 1. k6-search 매니페스트의 query body를 aggregation으로 변경
# {"size":0, "aggs":{"by_status":{"terms":{"field":"status","size":100}}}}

# 단계 2. 30분 진행 + breaker tripped / heap 모니터링
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=elasticsearch_breakers_tripped' | jq
curl -sG "$PROM/api/v1/query" --data-urlencode 'query=elasticsearch_jvm_gc_collection_seconds_count{gc="old"}' | jq

# 합격: breaker tripped 0, old GC count 안정
```

---

## OS-04 — Shard / Replica Scaling

```bash
# 단계 1. 인덱싱 진행 중 동적 settings 변경
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -sX PUT "$OS/logs-fb-*/_settings" -H 'Content-Type: application/json' \
  -d '{"index": {"number_of_replicas": 2}}'

# 단계 2. relocating shards 모니터링
for i in 1 2 3 4 5; do
  curl -sG "$PROM/api/v1/query" --data-urlencode 'query=elasticsearch_cluster_health_relocating_shards' | jq -r '.data.result[0].value[1]'
  sleep 60
done

# 합격: relocating 일시 증가 후 0, recovery time < 10분
```

---

## OS-05 — Soak 24h

```bash
# OS-08과 동일 부하를 24h 유지하면서 매시간 sample
while true; do
  ts=$(date +"%Y-%m-%d %H:%M:%S")
  heap=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=elasticsearch_jvm_memory_used_bytes{area="heap"}/elasticsearch_jvm_memory_max_bytes{area="heap"}*100' | jq -r '.data.result[0].value[1]')
  gc=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=rate(elasticsearch_jvm_gc_collection_seconds_sum[5m])' | jq -r '.data.result[0].value[1]')
  threads=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=elasticsearch_jvm_threads_count' | jq -r '.data.result[0].value[1]')
  echo -e "$ts\t$heap\t$gc\t$threads"
  sleep 3600
done | tee /tmp/$TEST_ID-OS05-soak.tsv

# 합격: heap monotonic 상승 없음, GC count 안정, threads 안정
```

---

## OS-07 — Node Failure (Chaos)

```bash
# 단계 1. 부하 진행 중 data node 1대 강제 종료 (multi-node 환경)
kubectl --context=$CTX -n monitoring delete pod opensearch-lt-node-1

# 단계 2. cluster status timeline 추적
for i in 1 2 3 4 5 6 7 8 9 10; do
  STATE=$(kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- curl -s "$OS/_cluster/health" | jq -r '.status')
  UNASSIGNED=$(curl -sG "$PROM/api/v1/query" --data-urlencode 'query=elasticsearch_cluster_health_unassigned_shards' | jq -r '.data.result[0].value[1]')
  echo "T+${i}min: $STATE  unassigned=$UNASSIGNED"
  sleep 60
done

# 합격: green 회복 < 20분, 손실 0, 인덱싱 중단 < 1분
```

---

## 결과 확인 공통 패턴

각 시나리오에서 4축 동시 관찰:

```bash
# 1. kubectl
kubectl --context=$CTX -n monitoring get pods -l app.kubernetes.io/name=opensearch
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- curl -s "$OS/_cluster/health" | jq

# 2. PromQL — 핵심 8개 한 번에
PROM=http://192.168.101.197:9090
for q in \
  "indexing TPS|sum(rate(elasticsearch_indices_indexing_index_total[1m]))" \
  "search QPS|sum(rate(elasticsearch_indices_search_query_total[1m]))" \
  "search latency|rate(elasticsearch_indices_search_query_time_seconds_total[1m])/clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)" \
  "bulk reject|rate(elasticsearch_thread_pool_rejected_count{type=\"write\"}[1m])" \
  "heap %|elasticsearch_jvm_memory_used_bytes{area=\"heap\"}/elasticsearch_jvm_memory_max_bytes{area=\"heap\"}*100" \
  "old GC count|elasticsearch_jvm_gc_collection_seconds_count{gc=\"old\"}" \
  "segments|elasticsearch_indices_segments_count" \
  "breaker tripped|elasticsearch_breakers_tripped"; do
  name="${q%|*}"; expr="${q#*|}"
  val=$(curl -sG "$PROM/api/v1/query" --data-urlencode "query=$expr" | jq -r '.data.result[0].value[1] // "NONE"')
  printf "  %-25s %s\n" "$name" "$val"
done

# 3. Grafana
# UI: http://192.168.101.197:3000/d/lt-opensearch
# 시나리오 ID로 row 이동, 시간 범위 조정 후 스냅샷

# 4. OpenSearch _cat API (top-down 진단)
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -c opensearch -- bash -c "
  echo === health ===
  curl -s '$OS/_cluster/health?pretty'
  echo === thread_pool write ===
  curl -s '$OS/_cat/thread_pool/write?v'
  echo === pending tasks ===
  curl -s '$OS/_cluster/pending_tasks?pretty' | head -20
  echo === indices summary ===
  curl -s '$OS/_cat/indices?v&s=docs.count:desc' | head -10
"
```

결과 보관:
```bash
mkdir -p /tmp/$TEST_ID
cp /tmp/$TEST_ID-OS*.* /tmp/$TEST_ID/
# Grafana JSON
curl -s -u admin:admin "http://192.168.101.197:3000/api/dashboards/uid/lt-opensearch" \
  -o /tmp/$TEST_ID/dash-opensearch.json
# Tar
tar -czf /tmp/$TEST_ID-results.tar.gz -C /tmp $TEST_ID/
```

각 결과는 `10-test-plan-and-results.md` §10 템플릿에 따라 `LT-YYYYMMDD-OS-##` 형식으로 기록.
