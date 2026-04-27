# OpenSearch 부하·장애 시나리오 6종 — 수행 가이드

## 0. 공통 사전 정보

### 0.1 메트릭 prefix
운영 cluster 의 OS 모니터링은 `prometheus-community/elasticsearch-exporter`
사용. 메트릭 prefix 는 **`elasticsearch_*`** (OpenSearch 도 동일 — exporter 가
호환). 본 가이드의 PromQL 은 모두 이 prefix 기준.

| metric | 의미 | 비고 |
|--------|------|------|
| `elasticsearch_cluster_health_status{color="green/yellow/red"}` | 클러스터 상태 (0/1 값) | 현재 상태인 color 만 1, 나머지 0 |
| `elasticsearch_cluster_health_unassigned_shards` | 미할당 shard | 회복 진행도 측정 |
| `elasticsearch_cluster_health_initializing_shards` | 초기화 중 shard | 회복 시 일시 증가 |
| `elasticsearch_cluster_health_relocating_shards` | 재배치 중 shard | replica 재구성 |
| `elasticsearch_cluster_health_number_of_nodes` | 살아있는 노드 수 | 노드 장애 즉시 감소 |
| `elasticsearch_indices_indexing_index_total` | 누적 색인 건수 (per node) | `sum(rate(...))` 으로 cluster RPS |
| `elasticsearch_indices_indexing_index_time_seconds_total` | 누적 색인 시간 | `rate / rate` 로 평균 latency |
| `elasticsearch_indices_search_query_total` | 누적 검색 건수 | 동시 부하 시나리오 핵심 |
| `elasticsearch_thread_pool_queue_count{type="write|search|get"}` | 큐 깊이 | 포화 지표 |
| `elasticsearch_thread_pool_rejected_count` | 거부된 요청 누적 | RPS 초과 감지 |
| `elasticsearch_breakers_tripped` | circuit breaker trip 누적 | 메모리 압력 |
| `elasticsearch_jvm_memory_used_bytes{area="heap"}` | heap 사용량 | %heap = used/max |
| `elasticsearch_filesystem_data_available_bytes` | 데이터 노드 가용 디스크 | 부하/장애 양쪽 핵심 |

### 0.2 부하 도구

`loadtest-tools:0.1.2` (=Nexus mirror) 한 이미지에 모두 포함:

| 도구 | 용도 | 본 가이드 시나리오 |
|------|------|-------------------|
| opensearch-benchmark (OSB) | 표준 워크로드 (geonames, http_logs 등 14개) | §1, §2 |
| k6 | HTTP 시나리오 / 함수 / wave | §2, §3 |
| hey | 단순 RPS burst | §1 빠른 가산 |
| flog | 가짜 로그 생성 (fluent-bit → OS) | §4 |
| kubectl + curl | 직접 OS API (인덱스 생성, force-merge, _cluster/health) | 전 시나리오 |

### 0.3 관찰 대시보드

`/Ingest Pipeline/OpenSearch/` 폴더 (5조직 모두 동일 — gitops 로 배포됨):

| dashboard UID | 매핑 시나리오 |
|---------------|---------------|
| loadtest-os-cluster-overview     | 공통 (모든 시나리오) |
| loadtest-os-bulk-throughput      | §1 |
| loadtest-os-mixed-load           | §2 |
| loadtest-os-batch-wave           | §3 |
| loadtest-os-sustained-190        | §4 |
| loadtest-os-chaos-node           | §5 |
| loadtest-os-chaos-pv             | §6 |

### 0.4 testbed 한계 안내

| 시나리오 | testbed (single-node) | 의도 |
|----------|----------------------|------|
| §1 Bulk | OSB --test-mode 1k docs OK / 운영급 N/A | smoke 검증만 |
| §2 Mixed | OSB + k6 동시 OK | RPS 절반 (운영의 ~1/10) |
| §3 Wave | k6 wave script OK | peak 의도된 throttle |
| §4 190-node | flog replicas=30 max (단일노드 한계) | 운영급은 멀티노드 필요 |
| §5 Node failure | replica=0 이라 의도된 RED 발생 | 운영(replica≥1) 의 회복 흐름 시뮬 |
| §6 PV failure | hostpath PV 삭제 가능 | 운영 PVC 회복 절차 검증 |

---

## §1. Bulk Indexing 처리량 / 지연

| 항목 | 값 |
|------|-----|
| 시나리오 ID | OS-BULK-01 |
| 주제 | bulk insert 만으로 OS 가 받을 수 있는 최대 처리량과 그 시점의 latency |
| 가설 / SLO | 단일 노드: ≥ 1k docs/s, 평균 latency ≤ 50ms / 운영 멀티노드: ≥ 50k docs/s, p95 ≤ 200ms |
| 조작 변수 | bulk size, 동시 client 수 |
| 통제 변수 | doc 크기, target index, replica=0 (testbed) |

### 1.1 사전 조건
- OS 클러스터 status=green (또는 testbed 의 yellow)
- 인덱스 prefix `loadtest-bulk-` 사용 — 운영 인덱스 침범 방지
- replica=0 으로 강제 (testbed): `kubectl exec -n monitoring opensearch-lt-node-0 -- curl -X PUT -u admin:admin "http://localhost:9200/_template/loadtest-bulk-tpl" -H 'Content-Type: application/json' -d '{"index_patterns":["loadtest-bulk-*"],"settings":{"number_of_replicas":0}}'`

### 1.2 수행 절차

```bash
CTX=minikube-remote
DIR=deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest

# (testbed 한정) image swap
SWAP='sed -e s|nexus.intranet:8082/loadtest/loadtest-tools:0.1.2|loadtest-tools:0.1.2|g'

# 1. lt-config 의 OSB_WORKLOAD 를 'http_logs' 로 (대용량 doc)
kubectl --context=$CTX -n load-test patch configmap lt-config \
  --type=merge -p '{"data":{"OSB_WORKLOAD":"http_logs","OSB_TEST_PROCEDURE":"append-no-conflicts"}}'

# 2. job 적용
kubectl --context=$CTX -n load-test delete job opensearch-benchmark --ignore-not-found
cat $DIR/job.yaml | $SWAP | kubectl --context=$CTX apply -f -

# 3. 진행 모니터링 (Grafana 'OpenSearch Bulk — Throughput & Latency' 대시보드)
kubectl --context=$CTX -n load-test logs -f job/opensearch-benchmark
```

운영급 부하는 lt-config 에서 `OSB_TEST_MODE=false` + PVC 에 full corpus 사전 적재.

### 1.3 측정 지표 + 기록 양식

| 항목 | 측정 방법 | 기록 |
|------|-----------|------|
| 누적 doc 수 | OSB final report `doc count` | _____ |
| 평균 throughput | OSB report `Mean throughput` | _____ docs/s |
| Median latency | OSB report `50th percentile` | _____ ms |
| p95 latency | OSB report `95th percentile` | _____ ms |
| Write queue 최대 | dashboard panel "Write queue depth" max | _____ |
| Bulk rejected | `increase(elasticsearch_thread_pool_rejected_count{type="write"}[총소요])` | _____ |
| 종료 후 segment 수 | dashboard "Segments after run" | _____ |

### 1.4 합격 / 실패 판정
- ✅ p95 ≤ SLO + rejected = 0 + status remained green/yellow
- ⚠ rejected > 0 → bulk size 또는 client 수 줄이거나 노드 추가
- ❌ status=red 발생 시 즉시 조사

### 1.5 트러블슈팅
- bulk hang: single-node + replica=1 → replica=0 강제 또는 노드 추가
- 모든 doc count=0: workload corpus 누락 → 0.1.2 air-gap bundle 사용 확인
- "fielddata circuit breaker": refresh_interval 길게 + heap 증설

---

## §2. 인덱싱 + 검색 동시 부하

| 항목 | 값 |
|------|-----|
| 시나리오 ID | OS-MIX-01 |
| 주제 | 색인이 진행 중인 상태에서 검색을 동시 수행 — 운영 실 워크로드 시뮬 |
| 가설 / SLO | 검색 latency p95 ≤ 500 ms (mixed 시 단독 검색 대비 < 2x 증가), 색인 throughput ≥ 단독 색인의 70% |
| 조작 변수 | 검색 동시성 (k6 vus), 색인 RPS |
| 통제 변수 | doc 크기, query 종류 (fixed term query) |

### 2.1 사전 조건
- §1 의 OSB ingest 가 진행 중이거나, 인덱스에 ≥ 1M docs 사전 적재
- k6 search job 매니페스트 (OS-02-k6-heavy-search) 준비됨

### 2.2 수행 절차

```bash
# 두 job 을 시간차 ≤ 30s 로 동시 시작
TS=$(date +%s)
cat deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/job.yaml | $SWAP \
  | sed "s|name: opensearch-benchmark|name: opensearch-benchmark-mix-${TS}|" \
  | kubectl --context=$CTX apply -f -

cat deploy/load-testing-airgap/20-scenarios/OS-02-k6-heavy-search/job.yaml | $SWAP \
  | sed "s|name: k6-heavy-search|name: k6-heavy-search-mix-${TS}|" \
  | kubectl --context=$CTX apply -f -

# 둘 다 완료까지 대기
kubectl --context=$CTX -n load-test wait --for=condition=complete \
  job/opensearch-benchmark-mix-${TS} job/k6-heavy-search-mix-${TS} --timeout=20m
```

### 2.3 측정 지표 + 기록

| 항목 | metric / 도구 | 기록 |
|------|---------------|------|
| 단독 색인 throughput (baseline) | §1 결과 재사용 | _____ docs/s |
| Mixed 색인 throughput | sum(rate(elasticsearch_indices_indexing_index_total[5m])) — mixed 구간 평균 | _____ docs/s |
| 단독 검색 p95 (baseline) | OS-02 단독 실행 결과 | _____ ms |
| Mixed 검색 p95 | k6 stdout `http_req_duration p(95)` | _____ ms |
| Search queue 최대 | dashboard "Mixed Workload" panel | _____ |
| Search rejected | `increase(elasticsearch_thread_pool_rejected_count{type="search"})` | _____ |

### 2.4 합격 / 실패
- ✅ 색인 ≥ 0.7 × baseline AND 검색 p95 ≤ 2 × baseline
- ⚠ 색인 < 0.5 × baseline → write queue 포화 → bulk size↓ 또는 thread_pool.write 증설
- ❌ 검색 p95 > 5 × baseline → cache miss / GC 지옥 → heap 증설 + JVM 튜닝

---

## §3. Spark / Airflow 동시 동작 wave

| 항목 | 값 |
|------|-----|
| 시나리오 ID | OS-WAVE-01 |
| 주제 | 평소 = baseline 부하, 정각마다 Spark/Airflow batch ingest = 5x peak (10~15분 wave) |
| 가설 / SLO | wave peak 시 status=green 유지 + circuit breaker trip = 0 + GC pause < 1s |
| 조작 변수 | wave 진폭 (peak/baseline 비), 주기 (15min/30min/1h) |
| 통제 변수 | doc 크기, target index, refresh_interval=30s |

### 3.1 부하 패턴

```
RPS  ┐
5K   │      ████      ████      ████       ← peak (Spark wave)
1K   │ ▒▒▒▒    ▒▒▒▒▒▒    ▒▒▒▒▒▒    ▒▒▒▒    ← baseline
0    └─────────────────────────────────→ time
       0  10 15  25 30  40 45  55 60
```

### 3.2 수행 절차 (k6 wave 스크립트)

`deploy/load-testing-airgap/20-scenarios/OS-WAVE-01-spark-airflow/script.js` 가 없으면
인라인 ConfigMap 으로 추가:

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: k6-wave-script, namespace: load-test }
data:
  wave.js: |
    import http from 'k6/http';
    import { sleep } from 'k6';

    // 30분 = 1 cycle (10분 baseline → 5분 ramp → 10분 peak → 5분 cooldown)
    export const options = {
      stages: [
        { duration: '10m', target: 50  },   // baseline 50 RPS
        { duration: '5m',  target: 250 },   // ramp 5x
        { duration: '10m', target: 250 },   // peak 250 RPS
        { duration: '5m',  target: 50  },   // back to baseline
        // 반복: stages 를 3 cycle 만큼 늘려도 됨
      ],
    };

    const URL = __ENV.OPENSEARCH_URL + '/loadtest-wave-' + __VU + '/_doc';
    const AUTH = { headers: { Authorization: 'Basic ' + encoding.b64encode('admin:admin') }};

    export default function () {
      const payload = JSON.stringify({
        '@timestamp': new Date().toISOString(),
        vu: __VU, iter: __ITER, msg: 'spark-batch-row-' + __ITER,
      });
      http.post(URL, payload, { headers: { 'Content-Type': 'application/json' }, ...AUTH });
      sleep(0.05);
    }
```

```bash
kubectl --context=$CTX apply -f - << 'EOF'
apiVersion: batch/v1
kind: Job
metadata: { name: k6-spark-wave, namespace: load-test }
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: k6
          image: loadtest-tools:0.1.2
          command: [k6, run, /scripts/wave.js]
          envFrom: [ { configMapRef: { name: lt-config } }, { secretRef: { name: opensearch-creds } } ]
          volumeMounts: [ { name: scripts, mountPath: /scripts } ]
      volumes: [ { name: scripts, configMap: { name: k6-wave-script } } ]
EOF
```

### 3.3 측정 지표 + 기록

| 항목 | metric | 기록 |
|------|--------|------|
| baseline RPS (실측) | sum(rate(elasticsearch_indices_indexing_index_total[5m])) (10~15min 구간) | _____ |
| peak RPS (실측) | sum(rate(elasticsearch_indices_indexing_index_total[1m])) max | _____ |
| GC time / sec (peak) | rate(elasticsearch_jvm_gc_collection_seconds_sum[1m]) (peak 구간) | _____ s/s |
| Circuit breaker trips | increase(elasticsearch_breakers_tripped[총소요]) | _____ |
| Segment count growth | delta(elasticsearch_indices_segments_count[총소요]) | _____ |
| Cluster status during peak | min(elasticsearch_cluster_health_status{color="green"}) | _____ (1=green 유지) |

### 3.4 합격 / 실패
- ✅ peak 구간에 trip=0 + status green + GC<10% (=0.1 s/s)
- ⚠ trip>0 → indexing.bulk 메모리 한계 → bulk size↓ 또는 heap↑
- ❌ status=yellow 진입 시 5분 내 복귀 안 되면 fail

---

## §4. 190대 클러스터 지속 부하 (flog replica 다수)

| 항목 | 값 |
|------|-----|
| 시나리오 ID | OS-SUSTAIN-01 |
| 주제 | 운영 동등 노드 수 (190) × 노드당 평균 로그 RPS 를 24~72시간 지속 |
| 가설 / SLO | 24h 동안 status green 유지, 디스크 사용률 < 80%, p95 latency 증가 < 50% |
| 조작 변수 | flog replicas (testbed: 30 / 운영: 190), 지속 시간 |
| 통제 변수 | 로그 포맷, 노드당 RPS = 200 lines/s 고정 |

### 4.1 사전 조건
- fluent-bit DaemonSet 동작 중
- OS index lifecycle (ILM) 구성: hot → warm 7일, delete 30일 (운영)
- testbed: 단일 노드 디스크 ≥ 100GB 여유

### 4.2 수행 절차

```bash
# flog replicas scale up
# testbed: 단일노드 한계 = ~30 (CPU 32, mem 64GB)
# 운영 zone: 190
REPLICAS=30
kubectl --context=$CTX -n load-test scale deployment flog-loader --replicas=${REPLICAS}

# 실행 시간 (testbed: 1h smoke / 운영: 24~72h)
DURATION=1h
echo "Started: $(date)"
sleep ${DURATION}

# 결과 수집 후 정리
kubectl --context=$CTX -n load-test scale deployment flog-loader --replicas=0
echo "Ended: $(date)"
```

장기 실행 (24h+) 은 다음을 매 시간 자동 수집 권장 (bash + cron):
- `_cluster/health` 의 status / unassigned_shards
- `_cat/indices?h=index,docs.count,store.size&s=store.size:desc` 상위 10개
- node-exporter 의 disk used%

### 4.3 측정 지표 + 기록

| 항목 | metric | 기록 (1h smoke / 24h full) |
|------|--------|----------------------------|
| Aggregate ingestion RPS | sum(rate(elasticsearch_indices_indexing_index_total[5m])) avg | _____ / _____ docs/s |
| 누적 색인 doc 수 | delta(...total[1h]) 또는 [24h] | _____ / _____ M docs |
| 디스크 사용률 max (data node) | max((1 - elasticsearch_filesystem_data_available_bytes / elasticsearch_filesystem_data_size_bytes) * 100) | _____ % |
| Translog flush 빈도 | rate(elasticsearch_indices_translog_flush_total[5m]) avg | _____ |
| Status changes | changes(elasticsearch_cluster_health_status{color="green"}[총소요]) | _____ (목표 0) |
| Restart count | sum(kube_pod_container_status_restarts_total{namespace="monitoring", pod=~"opensearch.*"}) | _____ |

### 4.4 합격 / 실패
- ✅ status changes=0, 디스크 ≤ 80%, restart=0
- ⚠ 디스크 > 80% → ILM rollover 더 공격적으로 (1d → 6h)
- ❌ status≠green 누적 5분 이상 → fail

---

## §5. 노드 장애 회복 (red → yellow → green time)

| 항목 | 값 |
|------|-----|
| 시나리오 ID | CHAOS-OS-NODE-01 |
| 주제 | 데이터 노드 1개 강제 down → cluster 가 자동 회복하는 시간 측정 |
| 가설 / SLO | yellow 진입 ≤ 30s, green 회복 ≤ 5분 (replica 1, 1GB shards × 10) |
| 조작 변수 | down 시키는 노드 종류 (data / master / coord), 직전 indexing rate |
| 통제 변수 | replica ≥ 1, shard 크기, heap 동일 |

### 5.1 사전 조건 (★ 중요)
- replica ≥ 1 — testbed 는 의도된 RED 발생 (replica=0 이라 미할당 = unrecoverable)
- 부하 X (정상 상태에서 시작), 또는 §1 의 baseline 부하만 진행 중
- 측정 시점 직전 timestamp 기록

### 5.2 수행 절차

```bash
# 0. baseline 부하 (선택)
# 1. 측정 시작 timestamp
T0=$(date +%s)
echo "T0 (failure injection): $T0"

# 2. 데이터 노드 1개 강제 종료
NODE=$(kubectl --context=$CTX -n monitoring get pod -l app=opensearch \
       -o jsonpath='{.items[0].metadata.name}')
kubectl --context=$CTX -n monitoring delete pod $NODE --grace-period=0 --force

# 3. status=red / yellow / green 천이 시점 기록 (Grafana 'Chaos — Node Recovery' 대시보드)
#    각 천이를 자동 기록하는 prometheus alert 도 가능:
#    - alert: ClusterStatusRed   expr: max(elasticsearch_cluster_health_status{color="red"}) == 1
#    - alert: ClusterStatusYellow ...

# 4. green 회복 시 timestamp T_recover = $(date +%s)
# 5. 회복 시간 = T_recover - T0
```

### 5.3 회복 시간 자동 측정 (PromQL)

```promql
# red 상태 지속 시간 (초)
sum_over_time(elasticsearch_cluster_health_status{color="red"}[1h]) * 30

# yellow 지속 시간
sum_over_time(elasticsearch_cluster_health_status{color="yellow"}[1h]) * 30

# 마지막 red→green 시점
last_over_time((elasticsearch_cluster_health_status{color="green"} == 1)[1h:30s])
```
(`* 30` 은 scrape interval 30s 가정 — 실제 interval 대입)

### 5.4 측정 지표 + 기록

| 항목 | 측정 방법 | 기록 |
|------|-----------|------|
| T0 (kill 시각) | 위 명령 출력 | _____ |
| T_yellow (yellow 진입) | dashboard timeseries 의 첫 yellow 값 | _____ s after T0 |
| T_green (green 복귀) | dashboard 첫 green 값 | _____ s after T0 |
| 미할당 shard peak | max_over_time(elasticsearch_cluster_health_unassigned_shards[10m]) | _____ |
| Initializing shard peak | max_over_time(elasticsearch_cluster_health_initializing_shards[10m]) | _____ |
| 회복 throughput | rate(elasticsearch_indices_translog_size_in_bytes[1m]) | _____ MB/s |

### 5.5 합격 / 실패
- ✅ T_yellow ≤ 30s AND T_green ≤ 5min AND 데이터 손실 0
- ⚠ T_green 5~15min → replica 재구성 IO 부족 → cluster.routing 튜닝
- ❌ red 영구 (10min+) → replica=0 의심 / corrupted shards

---

## §6. 스토리지 장애 회복 (PV 유실 시 green 복구 시간)

| 항목 | 값 |
|------|-----|
| 시나리오 ID | CHAOS-OS-PV-01 |
| 주제 | 데이터 노드 PVC 강제 삭제 → cluster 가 reroute 로 자동 회복 (replica 자동 재생성) 시간 |
| 가설 / SLO | replica=1 + 데이터 1GB 기준 green 복구 ≤ 10분 |
| 조작 변수 | 삭제 PV 개수 (1/2 동시), 데이터 양 |
| 통제 변수 | replica=1 (절대), 노드 수 ≥ 3 (운영 환경 가정) |

### 6.1 사전 조건 (★ 운영급)
- replica = 1 (testbed: 단일노드라 시뮬 한계 — 운영 zone 에서만 실제 검증)
- StatefulSet 또는 Deployment 가 PVC volumeClaimTemplate 사용
- 데이터 ≥ 1GB (회복 시간 측정 의미 있게)

### 6.2 수행 절차 (운영 zone)

```bash
# 0. baseline + 데이터 사전 적재 (§1 의 1k docs 가 아닌 대용량)
# 1. T0 timestamp
T0=$(date +%s); echo "T0=$T0"

# 2. 데이터 노드 1대의 PVC 삭제 (PV 도 자동 release)
PVC=$(kubectl --context=$CTX -n monitoring get pvc \
      -l app=opensearch -o jsonpath='{.items[0].metadata.name}')
kubectl --context=$CTX -n monitoring delete pvc $PVC --wait=false

# 3. 해당 pod 재시작 강제 (StatefulSet 이 새 PVC binding)
POD=$(kubectl --context=$CTX -n monitoring get pod \
      -l app=opensearch -o jsonpath='{.items[0].metadata.name}')
kubectl --context=$CTX -n monitoring delete pod $POD --grace-period=0 --force

# 4. dashboard 'Chaos — PV Recovery' 모니터링
# 5. green 복구 timestamp T_recover
```

### 6.3 측정 지표 + 기록

| 항목 | 측정 | 기록 |
|------|------|------|
| T0 (PVC delete 시각) | 명령 출력 | _____ |
| 새 PVC bound 시각 | kubectl get pvc -w 의 'Bound' 천이 | _____ s after T0 |
| 노드 join 시각 | elasticsearch_cluster_health_number_of_nodes 회복 | _____ s after T0 |
| Replica 재생성 진행 (peak) | max(elasticsearch_cluster_health_initializing_shards) | _____ |
| 회복 throughput | sum(rate(elasticsearch_indices_translog_operations_total[1m])) | _____ ops/s |
| T_green | dashboard 첫 green | _____ s after T0 |

### 6.4 합격 / 실패
- ✅ T_green ≤ 10분 AND 데이터 손실 0
- ⚠ replica 가 다른 노드에서 살아있는데도 회복 지연 → cluster.routing.allocation.node_initial_primaries_recoveries 튜닝
- ❌ 데이터 손실 발생 (replica=0 이거나 unique primary 보유 시)

### 6.5 testbed 제약
- 단일 노드 minikube 에서는 의미 있는 검증 불가 (replica=0)
- testbed 에서는 PVC delete → pod CrashLoop 만 확인 (PV 재생성 흐름)
- 진짜 검증은 운영 zone (≥ 3 데이터 노드, replica=1) 에서 실행

---

## 7. 결과 기록 양식 (모든 시나리오 공통)

복사해서 시나리오별 결과 파일에 사용:

```yaml
# YYYY-MM-DD_OS-XXX-N1_run01.yaml
scenario_id: OS-BULK-01
run_at: 2026-04-XX HH:MM
operator: <name>
cluster:
  context: minikube-remote   # 또는 prod-cluster
  os_version: 2.x.x
  nodes_total: 1             # data nodes
  replica_factor: 0
input_variables:
  bulk_size: 1000
  client_count: 4
  duration: 5m
results:
  status_during_test: green
  throughput_avg: 8500       # docs/s
  latency_p50_ms: 35
  latency_p95_ms: 89
  latency_p99_ms: 145
  rejected_count: 0
  notes: |
    - peak heap = 60% (정상)
    - segment count grew 50→1200, force-merge 후 30
verdict: PASS    # PASS / FAIL / WARN
follow_up: []    # 후속 액션 (있으면 list)
```

---

## 8. 운영 시 자동화

### 8.1 정기 회귀 (CronJob)
- §1 + §2 → 매주 1회 야간 (smoke)
- §4 → 분기 1회 24h
- §5 + §6 → 신규 cluster 또는 helm upgrade 직후

### 8.2 알람 (kube-prometheus-stack PrometheusRule)
```yaml
- alert: OSStatusNotGreen
  expr: max(elasticsearch_cluster_health_status{color="green"}) < 1
  for: 5m
- alert: OSWriteRejection
  expr: rate(elasticsearch_thread_pool_rejected_count{type="write"}[5m]) > 0
- alert: OSDiskHigh
  expr: (1 - elasticsearch_filesystem_data_available_bytes / elasticsearch_filesystem_data_size_bytes) * 100 > 80
- alert: OSCircuitBreakerTripped
  expr: increase(elasticsearch_breakers_tripped[5m]) > 0
```

### 8.3 GitOps drift sync
신규 시나리오/대시보드는 `deploy/load-testing-airgap/30-grafana-gitops/` repo
에 commit → CronJob (10분 주기) 가 자동 sync.

---

## 9. 참고

- 기존 시나리오 매니페스트: `deploy/load-testing-airgap/20-scenarios/OS-*`
- OSB workload 명세: `loadtest-tools` 이미지 의 `/opt/osb-workloads/<name>/workload.json`
- 테스트 결과 모음: `deploy/load-testing-airgap/docs/06-testbed-handson-results.md`
- 운영 zone 이전 가이드: `deploy/load-testing-airgap/30-grafana-gitops/AIRGAP-GUIDE.md`
