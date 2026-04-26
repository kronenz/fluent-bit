# 4일 테스트 계획서 — Step-by-Step 핸즈온

`20-scenario-spec.md` 의 15개 시나리오를 4일에 걸쳐 수행하는 step-by-step
계획서. 각 step 은 ① 명령 / ② 예상 출력 / ③ 확인 포인트 / ④ 결과 기록 위치
를 포함하므로 직접 핸즈온 가능.

---

## 0. 전체 일정 한눈에

| Day | 시간 | 시나리오 | 누적 |
|-----|------|----------|------|
| **Day 1** | 8h | 환경 셋업 + OS-01 / OS-08 / OS-09 / OS-16 | 1일 |
| **Day 2** | 8h | CHAOS-OS-07 / OS-PV / FB-OOM / FB-PROD | 2일 |
| **Day 3** | 8h | FB-BURST / PR-HA / PR-SCRAPE / PR-QUERY | 3일 |
| **Day 4** | 8h | NE-COST / NE-FREQ / KSM-OOM + 결과서 작성 | 4일 |

---

## Day 0 — 사전 준비 (전날 1~2시간 권장)

### Step 0.1 — Cluster 사양 / 가정 확정

```bash
export CTX=minikube-remote                      # 폐쇄망: airgap-prod
export NS=load-test
export NS_MON=monitoring

kubectl --context=$CTX get nodes -o wide
kubectl --context=$CTX top node 2>/dev/null || echo "metrics-server 가 필요할 수 있음"
```

**기록**: 노드 수, 노드별 CPU/MEM, 사용 가능 리소스.

### Step 0.2 — 사전 객체 적용

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/00-prerequisites/
kubectl --context=$CTX apply -f deploy/load-testing-airgap/10-load-generators/
```

**확인**: `kubectl -n $NS get pods,deploy,cm,secret`

### Step 0.3 — node-exporter limit 사전 검증 (Critical)

```bash
kubectl --context=$CTX -n $NS_MON describe ds kps-prometheus-node-exporter | grep -A2 -i 'limits'
```

`memory: 32Mi` 이면 즉시 패치:
```bash
kubectl --context=$CTX -n $NS_MON patch ds kps-prometheus-node-exporter --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"256Mi"}
]'
```

**기록**: 패치 전/후 값. 운영 배포 시 helm values 에 영구 반영 필요.

### Step 0.4 — Grafana 접속 확인

```
http://<grafana-host>/d/lt-overview
http://<grafana-host>/d/lt-opensearch
http://<grafana-host>/d/lt-fluent-bit
http://<grafana-host>/d/lt-prometheus
http://<grafana-host>/d/lt-node-exporter
http://<grafana-host>/d/lt-ksm
```

각 대시보드가 데이터를 띄우는지 확인. 안 띄우면 ServiceMonitor / opensearch-creds Secret 미적용 가능성.

---

## Day 1 — OpenSearch 부하 테스트 (8시간)

### 09:00 - 09:30 — Day 1 환경 점검

```bash
# OS 가동 확인
kubectl --context=$CTX -n $NS_MON get pod -l app.kubernetes.io/name=opensearch

# replica=0 적용 (single-node 한정)
kubectl --context=$CTX -n $NS_MON exec opensearch-lt-node-0 -- \
  curl -s -u admin:admin -X PUT "http://localhost:9200/*/_settings" \
  -H 'Content-Type: application/json' -d '{"index":{"number_of_replicas":0}}'

# 인덱스 사전 채움 (flog 30분 가동)
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=10
```

30분 대기.

### 09:30 - 10:30 — Step 1: OS-01 Bulk Indexing

#### 1.1 적용
```bash
cat deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/job.yaml \
  | sed -e 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
  | kubectl --context=$CTX apply -f -
```

#### 1.2 모니터링
```bash
kubectl --context=$CTX -n $NS logs -f job/opensearch-benchmark
```

#### 1.3 예상 출력 (test-mode)
```
============== OSB SUCCESS ==============
{ "throughput": 850 docs/s, "latency_p95_ms": 32, ... }
```

#### 1.4 확인 포인트
- ✅ Job complete (1/1)
- ✅ throughput ≥ 200 docs/s (test-mode 기준)
- ✅ p95 < 50ms

#### 1.5 결과 기록
[22-test-result-form.md](22-test-result-form.md) 의 OS-01 양식에 throughput / p95 / fail 비율 기록.

#### 1.6 정리
```bash
kubectl --context=$CTX -n $NS delete job opensearch-benchmark
```

### 10:30 - 12:00 — Step 2: OS-08 Sustained High Ingest (1시간)

#### 2.1 적용
```bash
# flog 운영급으로 scale
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=30

# OSB sustained mode (test-mode false)
cat deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/job.yaml \
  | sed -e 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
        -e 's|name: opensearch-benchmark|name: osb-sustained|g' \
        -e 's|name: OSB_TEST_MODE, value: "true"|name: OSB_TEST_MODE, value: "false"|g' \
  | kubectl --context=$CTX apply -f -
```

#### 2.2 모니터링 (1시간)
- Grafana `lt-opensearch` 패널 → indexing rate, heap, segment count
- 매 15분마다 metric 스냅샷:
  ```bash
  curl -s "${PROMETHEUS_URL}/api/v1/query?query=rate(elasticsearch_indices_indexing_index_total[5m])" | jq
  curl -s "${PROMETHEUS_URL}/api/v1/query?query=elasticsearch_jvm_memory_used_bytes/elasticsearch_jvm_memory_max_bytes" | jq
  ```

#### 2.3 확인 포인트 (1시간 후)
- ✅ indexing rate sustained 30k docs/s 이상
- ✅ heap < 75% (drift ≤ 10%)
- ✅ segment count 마지막 10분 변화율 < 5%

#### 2.4 결과 기록
OS-08 양식에 sustained rate / heap drift / segment count 기록.

#### 2.5 정리
```bash
kubectl --context=$CTX -n $NS delete job osb-sustained
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=10
```

### 13:00 - 14:00 — Step 3: OS-09 Spark/Airflow Wave (Spike)

#### 3.1 baseline 안정화
```bash
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=5
sleep 300
```

#### 3.2 Burst 적용
```bash
T0=$(date +%s)
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=30
echo "burst started at $(date)"
```

#### 3.3 모니터링 (15분)
Grafana `lt-fluent-bit` 패널 → input rate spike, filesystem buffer 사용률, drop rate
```bash
# OS reject 측정
curl -s "${PROMETHEUS_URL}/api/v1/query?query=rate(elasticsearch_threadpool_rejected_count{name=\"write\"}[1m])" | jq

# fluent-bit buffer 사용
curl -s "${PROMETHEUS_URL}/api/v1/query?query=fluentbit_storage_chunks_total" | jq
```

#### 3.4 burst 종료 + 회복 시간 측정
```bash
sleep 900   # 15분 burst
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=5
T1=$(date +%s)
echo "burst ended at $(date), duration=$((T1-T0))s"

# 회복 측정 — input rate 가 baseline 으로 돌아오는 시간
sleep 300
```

#### 3.5 확인 포인트
- ✅ filesystem buffer 사용 < 80%
- ✅ OS reject < 1%
- ✅ ingest 정상화 시간 < 5분

#### 3.6 결과 기록
OS-09 양식에 burst peak rate / buffer max / reject rate / 회복 시간 기록.

### 14:00 - 14:30 — Step 4: OS-16 인덱싱+검색 동시 (★ 핵심 SLO)

#### 4.1 사전 (heavy ingest 가동 확인)
```bash
kubectl --context=$CTX -n $NS get deploy -l role=load-generator
# flog-loader 5 replica, loggen-spark 3, avalanche 2 모두 running 이어야 함
```

#### 4.2 적용
```bash
cat deploy/load-testing-airgap/20-scenarios/OS-16-k6-light-search/scenario.yaml \
  | sed -e 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
  | kubectl --context=$CTX apply -f -
```

#### 4.3 모니터링 (30분)
```bash
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=2400s job/k6-opensearch-light-search
kubectl --context=$CTX -n $NS logs job/k6-opensearch-light-search | tail -30
```

#### 4.4 예상 출력 (★ 합격)
```
✓ http_req_duration..............: avg=824ms p(95)=3,212ms p(99)=7,891ms
✓ http_req_failed................: 0.4%

✓ p(95)<5000
✓ p(99)<10000
✓ rate<0.01
```

#### 4.5 확인 포인트
- ★ p95 < 5,000 ms ← **운영 SLO 핵심**
- ✅ p99 < 10,000 ms
- ✅ fail < 1%

#### 4.6 결과 기록
OS-16 양식에 p95/p99/fail rate + 동시 ingest 강도 기록. 본 시나리오가 운영 적용 가능 여부 1차 판단.

#### 4.7 정리
```bash
kubectl --context=$CTX -n $NS delete job k6-opensearch-light-search
```

### 15:00 - 17:00 — Day 1 정리 / Grafana 스크린샷 / 결과서 작성

```bash
# Day 1 결과 종합 확인
kubectl --context=$CTX -n $NS get jobs --no-headers
```

각 시나리오 logs 추출:
```bash
mkdir -p ~/loadtest-results/day1
for j in opensearch-benchmark osb-sustained k6-opensearch-light-search; do
  kubectl --context=$CTX -n $NS logs $j > ~/loadtest-results/day1/$j.log 2>/dev/null || true
done
```

Grafana 스크린샷:
- `lt-opensearch` 대시보드 — Day 1 시간 범위 (예: 9:00 ~ 17:00)
- 핵심 패널 캡쳐 (OS-01 / OS-08 / OS-09 / OS-16)

**Day 1 종합 판정**: 4개 시나리오 ✅ 비율 기록.

---

## Day 2 — OS Chaos + Fluent-bit (8시간)

### 09:00 - 10:00 — Step 5: CHAOS-OS-07 Node Failure

#### 5.1 사전
```bash
# 멀티노드 클러스터 + replica ≥ 1 필수
kubectl --context=$CTX -n $NS_MON exec opensearch-lt-node-0 -- \
  curl -u admin:admin -s 'http://localhost:9200/_cat/indices?v' | head
# rep 컬럼 ≥ 1 확인. 0 이면 시나리오 무의미

# OS-08 baseline 가동 (50% TPS)
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=15
```

#### 5.2 적용
```bash
cat deploy/load-testing-airgap/20-scenarios/CHAOS-OS-07-node-failure/scenario.yaml \
  | sed 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
  | kubectl --context=$CTX apply -f -
```

#### 5.3 모니터링
```bash
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=900s job/chaos-os-07-node-failure || true
kubectl --context=$CTX -n $NS logs job/chaos-os-07-node-failure
```

#### 5.4 예상 출력 (멀티노드 정상)
```
RED 진입       : 5 s
YELLOW 진입    : 15 s
GREEN 회복     : 180 s
[PASS] green 회복 180s
```

#### 5.5 확인 포인트
- ✅ RED 진입 < 30s
- ✅ YELLOW → GREEN < 10분
- ✅ 데이터 손실 = 0 (인덱스 doc count 보존)

testbed (single-node) = 의도된 FAIL.

#### 5.6 정리
```bash
kubectl --context=$CTX -n $NS delete job chaos-os-07-node-failure
```

### 10:00 - 11:00 — Step 6: OS-PV PV 장애

⚠ 본 시나리오는 storage class / CSI driver 에 따라 절차가 다름. 아래는 hostPath PV 기준.

#### 6.1 PV 정보 확인
```bash
kubectl --context=$CTX -n $NS_MON get pvc -l app.kubernetes.io/name=opensearch
kubectl --context=$CTX get pv | grep opensearch
```

#### 6.2 baseline 가동
```bash
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=10
```

#### 6.3 PV detach / readonly 시뮬레이션 (CSI driver 별도)

CSI driver 가 EBS / GCEPD 등이면 console 에서 detach. hostPath/local 이면:
```bash
# OS pod 강제 종료 + PV finalizer 임시 제거
PV=$(kubectl --context=$CTX get pv -o jsonpath='{.items[?(@.spec.claimRef.name=="data-opensearch-lt-node-0")].metadata.name}')
kubectl --context=$CTX delete pod -n $NS_MON opensearch-lt-node-0 --grace-period=0 --force

# (옵션) PV finalizer 제거 — 운영 적용 신중
# kubectl --context=$CTX patch pv $PV -p '{"metadata":{"finalizers":null}}'
```

#### 6.4 회복 측정
```bash
# OS pod 재시작 + green 회복까지의 시간
T0=$(date +%s)
until kubectl --context=$CTX -n $NS_MON exec opensearch-lt-node-0 -- \
       curl -s -u admin:admin http://localhost:9200/_cluster/health 2>/dev/null \
       | grep -q '"status":"green"'; do
  sleep 10
done
T1=$(date +%s)
echo "green 회복 시간: $((T1-T0))s"
```

#### 6.5 확인 포인트
- ✅ green 회복 (시간 기록)
- ✅ 데이터 정합성 — 인덱스 doc count 손실 없음 (replica 보존)

#### 6.6 결과 기록
OS-PV 양식에 회복 시간 / 손실 doc 수 / 사용된 PV 종류 기록.

### 11:00 - 12:00 — Step 7: FB-OOM 단일 Pod Ceiling (자동 ramp 18분)

#### 7.1 적용
```bash
cat deploy/load-testing-airgap/20-scenarios/FB-OOM-tuning/scenario.yaml \
  | sed 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
  | kubectl --context=$CTX apply -f -
```

#### 7.2 모니터링 (병렬)
```bash
# 다른 터미널에서 fluent-bit 메모리 watch
watch -n 1 'kubectl -n monitoring top pod -l app.kubernetes.io/name=fluent-bit'
```

#### 7.3 결과 (자동 ramp 18분)
```bash
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=1500s job/fb-oom-tuning
kubectl --context=$CTX -n $NS logs job/fb-oom-tuning | grep 'RSS peak'
```

#### 7.4 예상 출력
```
[stage=baseline]  fluent-bit RSS peak = 60 MB
[stage=normal]    fluent-bit RSS peak = 150 MB
[stage=high]      fluent-bit RSS peak = 400 MB
[stage=peak]      fluent-bit RSS peak = 800 MB
```

#### 7.5 확인 포인트
- ✅ peak stage 까지 OOMKilled 없음
- ✅ RSS 곡선이 단계 별로 합리적 증가

#### 7.6 결과 기록
FB-OOM 양식에 stage 별 RSS + 운영 limit 권장값 기록.

```
운영 limit = max(high RSS × 1.5, peak RSS × 1.2)
        예) max(600, 1440) = 1440 MB → 1.5GB
```

### 13:00 - 14:00 — Step 8: FB-PROD 190대 운영 성능 (1시간 sustained)

#### 8.1 적용
```bash
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=10
T0=$(date +%s)
echo "FB-PROD started at $(date)"
```

#### 8.2 모니터링 (1시간)
- Grafana `lt-fluent-bit` 대시보드 watch
- 매 15분 metric 스냅샷:
  ```bash
  curl -s "${PROMETHEUS_URL}/api/v1/query?query=sum(rate(fluentbit_input_records_total[1m]))" | jq
  curl -s "${PROMETHEUS_URL}/api/v1/query?query=sum(rate(fluentbit_output_proc_records_total[1m]))" | jq
  curl -s "${PROMETHEUS_URL}/api/v1/query?query=sum(rate(fluentbit_output_proc_dropped_records_total[1m]))" | jq
  ```

#### 8.3 종료
```bash
sleep 3600
T1=$(date +%s)
echo "FB-PROD ended at $(date), duration=$((T1-T0))s"
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=5
```

#### 8.4 확인 포인트
- ✅ input rate ≈ output rate (drop = 0)
- ✅ buffer 사용 안정 (1시간 동안 일정)
- ✅ DaemonSet OOMKilled = 0

#### 8.5 결과 기록
FB-PROD 양식에 input/output rate / drop count / buffer 안정성 기록.

### 14:00 - 17:00 — Day 2 정리 + 결과서 보고

(Day 1 정리와 동일 패턴)

---

## Day 3 — Fluent-bit Burst + Prometheus (8시간)

### 09:00 - 10:00 — Step 9: FB-BURST Spike

#### 9.1 baseline 안정화
```bash
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=5
sleep 300
```

#### 9.2 Burst (30초)
```bash
T0=$(date +%s)
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=30
sleep 30
kubectl --context=$CTX -n $NS scale deploy/flog-loader --replicas=5
T1=$(date +%s)
echo "burst $((T1-T0))s"
```

#### 9.3 회복 측정
```bash
# 5분 동안 buffer / drop 모니터링
sleep 300
curl -s "${PROMETHEUS_URL}/api/v1/query?query=fluentbit_storage_chunks_total" | jq
curl -s "${PROMETHEUS_URL}/api/v1/query?query=fluentbit_output_proc_dropped_records_total" | jq
```

#### 9.4 확인 포인트
- ✅ filesystem buffer 사용 < 80% (burst 중)
- ✅ drop = 0 또는 < 0.01% (burst 중)
- ✅ buffer 정상화 시간 < 2분 (burst 후)

### 10:00 - 11:00 — Step 10: PR-HA

#### 10.1 replica=2 적용
```bash
kubectl --context=$CTX -n $NS_MON patch prometheus kps-prometheus -p '{"spec":{"replicas":2}}' --type=merge
kubectl --context=$CTX -n $NS_MON wait --for=condition=ready pod -l app.kubernetes.io/name=prometheus --timeout=300s
```

#### 10.2 baseline 알람 정착 (5분)
```bash
sleep 300
curl -s "${ALERTMANAGER_URL}/api/v2/alerts" | jq '. | length'
```

#### 10.3 1개 replica 강제 종료
```bash
T0=$(date +%s)
kubectl --context=$CTX -n $NS_MON delete pod prometheus-kps-prometheus-0 --grace-period=0 --force
```

#### 10.4 alerting 끊김 측정
```bash
# 1분 동안 alertmanager 가 alert 받는지 확인
for i in 1 2 3 4 5 6; do
  COUNT=$(curl -s "${ALERTMANAGER_URL}/api/v2/alerts" | jq '. | length')
  echo "$(date +%H:%M:%S) alerts=${COUNT}"
  sleep 10
done
```

#### 10.5 확인 포인트
- ✅ 다른 replica (kps-prometheus-1) 가 정상 동작
- ✅ alerts 가 끊기지 않고 도착 (60s 내 회복)
- ✅ 죽은 replica 자동 재시작

### 11:00 - 12:00 — Step 11: PR-SCRAPE Active Series 적재

#### 11.1 avalanche 운영급 scale
```bash
kubectl --context=$CTX -n $NS scale deploy/avalanche --replicas=20
```

⚠ testbed memory 검토 — 20 replicas × 256Mi = 5 GB 필요.

#### 11.2 정착 + 측정 (30분)
```bash
sleep 1800
curl -s "${PROMETHEUS_URL}/api/v1/query?query=prometheus_tsdb_head_series" | jq
curl -s "${PROMETHEUS_URL}/api/v1/query?query=histogram_quantile(0.95,sum(rate(prometheus_target_scrape_duration_seconds_bucket[5m]))%20by%20(le))" | jq
```

#### 11.3 확인 포인트
- ✅ active series ~ 5M (gauge_count × series_count × replicas)
- ✅ scrape p95 < 0.5s
- ✅ Prometheus heap < 80%

#### 11.4 정리
```bash
kubectl --context=$CTX -n $NS scale deploy/avalanche --replicas=2
```

### 13:00 - 14:00 — Step 12: PR-QUERY (k6 PromQL 부하)

#### 12.1 적용
```bash
cat deploy/load-testing-airgap/20-scenarios/PR-03-04-k6-promql/scenario.yaml \
  | sed 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
  | kubectl --context=$CTX apply -f -
```

#### 12.2 결과 (5분)
```bash
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=420s job/k6-promql
kubectl --context=$CTX -n $NS logs job/k6-promql | tail -30
```

#### 12.3 확인 포인트
- ✅ k6 thresholds 통과 (p95 < 2s, fail < 1%)

#### 12.4 정리
```bash
kubectl --context=$CTX -n $NS delete job k6-promql
```

### 14:00 - 17:00 — Day 3 정리 + 결과서

---

## Day 4 — Node-exporter + KSM + 종합 결과서 (8시간)

### 09:00 - 09:30 — Step 13: NE-COST 정상 Scrape 비용

#### 13.1 적용 (NE-02 그대로 사용)
```bash
cat deploy/load-testing-airgap/20-scenarios/NE-02-hey-node-exporter/job.yaml \
  | sed 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
  | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=180s job/hey-node-exporter
```

#### 13.2 결과
```bash
kubectl --context=$CTX -n $NS logs job/hey-node-exporter | tail -25
```

#### 13.3 확인 포인트
- ✅ 100% 2xx
- ✅ Average < 50ms
- ✅ p99 < 100ms

(testbed 에서 limit=32Mi 면 FAIL — STEP 0.3 수정 필요)

### 09:30 - 10:00 — Step 14: NE-FREQ 고빈도 Scrape Ramp

#### 14.1 적용
```bash
cat deploy/load-testing-airgap/20-scenarios/NE-OOM-tuning/scenario.yaml \
  | sed 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
  | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=600s job/ne-oom-tuning
```

#### 14.2 결과 추출
```bash
kubectl --context=$CTX -n $NS logs job/ne-oom-tuning | grep 'RSS peak'
```

#### 14.3 확인 포인트
- ✅ 모든 stage RSS > 0 (NE 가 부하 흡수)
- 운영 limit = peak RSS × 1.5

### 10:00 - 11:00 — Step 15: KSM-OOM (보강)

#### 15.1 적용 (testbed iter=50)
```bash
cat deploy/load-testing-airgap/20-scenarios/KSM-OOM-tuning/scenario.yaml \
  | sed -e 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
        -e 's|nexus.intranet:8082/loadtest/pause:3.10|registry.k8s.io/pause:3.10|g' \
  | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=600s job/ksm-oom-tuning
```

#### 15.2 결과
```bash
kubectl --context=$CTX -n $NS logs job/ksm-oom-tuning | grep -E 'stage=|DONE'
```

#### 15.3 확인 포인트
- ✅ KSM scrape duration < 5s (모든 stage)
- ✅ KSM RSS 안정

### 11:00 - 17:00 — 종합 결과서 작성

#### 1. 시나리오별 결과 표 작성
[22-test-result-form.md](22-test-result-form.md) 참조 → 각 시나리오 결과 입력.

#### 2. SLO 매트릭스
| 컴포넌트 | SLO 목표 | 실측값 | 판정 |
|----------|----------|--------|------|
| OS indexing TPS | ≥ 30k docs/s | (Day 1 OS-08 결과) | ? |
| OS search p95 | < 5,000 ms | (Day 1 OS-16 결과) | ? |
| OS green 회복 | < 10분 | (Day 2 CHAOS-OS-07) | ? |
| FB drop rate | 0 | (Day 2 FB-PROD) | ? |
| FB buffer 안정 | < 80% | (Day 3 FB-BURST) | ? |
| PR scrape p95 | < 0.5s | (Day 3 PR-SCRAPE) | ? |
| PR query p95 | < 2s | (Day 3 PR-QUERY) | ? |
| NE 200 응답 | 100% | (Day 4 NE-COST) | ? |
| KSM scrape duration | < 5s | (Day 4 KSM-OOM) | ? |

#### 3. 발견된 운영 이슈 (운영 적용 필요)
- node-exporter helm limit (32Mi → 256Mi 이상)
- (기타 발견된 이슈)

#### 4. 폐쇄망 이전 체크리스트
[deploy/load-testing-airgap/docs/05-hands-on-runbook.md](../../deploy/load-testing-airgap/docs/05-hands-on-runbook.md) §6 참조.

---

## 종합 — 4일 일정 시간표

| Day | 시작 | 종료 | 시나리오 / 작업 |
|-----|------|------|------------------|
| Day 0 | (전날) | — | 사전 준비 (1~2h) |
| Day 1 | 09:00 | 17:00 | OS-01, OS-08, OS-09, OS-16 |
| Day 2 | 09:00 | 17:00 | CHAOS-OS-07, OS-PV, FB-OOM, FB-PROD |
| Day 3 | 09:00 | 17:00 | FB-BURST, PR-HA, PR-SCRAPE, PR-QUERY |
| Day 4 | 09:00 | 17:00 | NE-COST, NE-FREQ, KSM-OOM, **결과서 작성** |

**버퍼**: 시나리오 실패 / 디버깅 시 다음 시나리오 시간 단축. 시간 부족 시 우선순위 Medium (OS-PV, KSM-OOM, PR-QUERY) skip 가능.
