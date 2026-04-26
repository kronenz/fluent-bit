# 08. 시나리오 카탈로그 — 실행 명령 + 대시보드 링크

`docs/load-testing/01-05`에 정의된 35개 시나리오(7개씩 × 5개 컴포넌트) 각각의 **실행 명령, 변수, 합격 기준, Grafana 대시보드 링크**를 한 곳에 모은 카탈로그입니다.

---

## 변수 표기 규칙

본 문서의 명령과 URL은 다음 변수를 가정합니다. **본인 환경에 맞게 search-replace**하거나 셸 변수로 정의 후 `envsubst`를 통과시키세요.

| 변수 | 예시 (테스트베드) | 예시 (운영) |
|------|----------------|------------|
| `${KUBECONTEXT}` | `minikube-remote` | `prod-cluster-1` |
| `${GRAFANA_BASE_URL}` | `http://192.168.101.197:3000` | `https://grafana.intranet` |
| `${PROMETHEUS_URL}` | `http://192.168.101.197:9090` | `https://prometheus.intranet` |
| `${OPENSEARCH_URL}` | `http://opensearch-lt-node.monitoring.svc:9200` | `https://opensearch.intranet:9200` |
| `${REGISTRY}` | (없음) | `nexus.intranet:8082/loadtest` |

`lt-config` ConfigMap의 변수는 `$(VAR_NAME)` (Pod 내부) 또는 직접 값으로 표기됩니다.

대시보드 링크는 모두 다음 형식:
```
${GRAFANA_BASE_URL}/d/<UID>?orgId=1&refresh=30s
```

---

## 대시보드 인덱스

| 컴포넌트 | UID | 링크 |
|----------|-----|------|
| 종합 | `lt-overview` | [`${GRAFANA_BASE_URL}/d/lt-overview`](#) |
| OpenSearch | `lt-opensearch` | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) |
| Fluent-bit | `lt-fluent-bit` | [`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) |
| Prometheus | `lt-prometheus` | [`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) |
| node-exporter | `lt-node-exporter` | [`${GRAFANA_BASE_URL}/d/lt-node-exporter`](#) |
| kube-state-metrics | `lt-ksm` | [`${GRAFANA_BASE_URL}/d/lt-ksm`](#) |

---

# OpenSearch (OS-01 ~ OS-07)

## OS-01 — Bulk Indexing

| 항목 | 내용 |
|------|------|
| **목적** | OpenSearch 클러스터의 인덱싱 처리량 한계 측정 |
| **도구** | opensearch-benchmark (`geonames` 워크로드) |
| **매니페스트** | `04-test-jobs/opensearch-benchmark.yaml` |
| **주요 변수** | `OSB_WORKLOAD`, `OSB_TEST_PROCEDURE`, `OPENSEARCH_URL` |
| **합격 기준** | TPS ≥ 30,000 docs/s, reject < 0.1%, heap ≤ 75% |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-01" |

```bash
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/04-test-jobs/opensearch-benchmark.yaml
kubectl --context=${KUBECONTEXT} -n load-test wait --for=condition=complete job/opensearch-benchmark --timeout=45m
kubectl --context=${KUBECONTEXT} -n load-test logs job/opensearch-benchmark --tail=200
```

## OS-02 — Mixed Read/Write

| 항목 | 내용 |
|------|------|
| **목적** | 인덱싱 진행 중 검색 부하 동시 가하여 응답 거동 확인 |
| **도구** | k6 (`/_search` POST), 7분 부하 |
| **매니페스트** | `04-test-jobs/k6-opensearch-search.yaml` |
| **주요 변수** | `K6_SEARCH_VU_TARGET`, `K6_SEARCH_DURATION`, `OS_INDEX_PATTERN` |
| **합격 기준** | http_req_duration p95 ≤ 500 ms, p99 ≤ 1500 ms, error rate < 0.5% |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-02" |

```bash
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/04-test-jobs/k6-opensearch-search.yaml
kubectl --context=${KUBECONTEXT} -n load-test wait --for=condition=complete job/k6-opensearch-search --timeout=15m
kubectl --context=${KUBECONTEXT} -n load-test logs job/k6-opensearch-search | tail -30   # k6 summary
```

## OS-03 — Heavy Aggregation

| 항목 | 내용 |
|------|------|
| **목적** | 대용량 집계(`terms`, `histogram`)에서 메모리·연산 부하 측정 |
| **도구** | k6 (집계 쿼리 반복) — `04-test-jobs/k6-opensearch-search.yaml`의 query body 변경 |
| **합격 기준** | heap ≤ 75%, breaker tripped 0, GC count 안정 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-03" |

```javascript
// k6-opensearch-search.yaml 의 body를 다음으로 교체:
const body = JSON.stringify({
  size: 0,
  aggs: { by_status: { terms: { field: "status", size: 100 } } }
});
```

## OS-04 — Shard / Replica Scaling

| 항목 | 내용 |
|------|------|
| **목적** | 인덱스 동적 설정 변경 시 shard relocation·처리량 영향 측정 |
| **도구** | `kubectl exec` + curl (REST PUT) |
| **합격 기준** | relocating_shards 일시 증가 후 0 복귀, recovery time < 10분 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-04" |

```bash
# 인덱싱 부하 진행 중 다음 실행
kubectl --context=${KUBECONTEXT} -n monitoring exec opensearch-lt-node-0 -- curl -s -X PUT \
  -H 'Content-Type: application/json' \
  ${OPENSEARCH_URL}/logs-fb-*/_settings \
  -d '{"index": {"number_of_replicas": 2}}'
```

## OS-05 — Soak 24h

| 항목 | 내용 |
|------|------|
| **목적** | OS-01 부하를 24시간 유지, 메모리 누수·GC drift 검증 |
| **합격 기준** | heap monotonic 상승 없음, FD/threads 안정 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-05" |
| **시간 범위** | 대시보드 우상단 → "Last 24 hours" 선택 |

```bash
# k8s CronJob으로 hourly trigger or 단일 Job duration ↑
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/04-test-jobs/opensearch-benchmark.yaml
# OSB_WORKLOAD=geonames + 24h cycle
```

## OS-06 — Spike Ingest ×5

| 항목 | 내용 |
|------|------|
| **목적** | 평균 부하 대비 ×5 spike → backpressure·reject 거동 |
| **도구** | flog 또는 benchmark의 `--load-worker-coordinator-target-throughput` |
| **합격 기준** | reject burst 후 1분 내 0 복귀, status green |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-06" |

```bash
# 평균 부하 → 5분 후 spike: FLOG_REPLICAS×5 또는 benchmark target throughput ↑
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=15
sleep 300
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=3
```

## OS-07 — Node Failure (Chaos)

| 항목 | 내용 |
|------|------|
| **목적** | data node 1대 강제 종료 시 회복 시간·데이터 손실 측정 |
| **도구** | `kubectl delete pod` |
| **합격 기준** | green 회복 < 20분, 손실 0, 인덱싱 중단 < 1분 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-07" (Cluster Status timeline) |

```bash
kubectl --context=${KUBECONTEXT} -n monitoring delete pod opensearch-lt-node-1   # multi-node 환경
# 또는 single-node에선 OS-04로 대체
```

---

> 아래 OS-08/09/12/14/16은 **운영 워크로드(200대 cluster log ingest)** 맞춤 신규 시나리오입니다.

## OS-08 — Sustained High Ingest (200대 모사)

| 항목 | 내용 |
|------|------|
| **목적** | 200대 cluster의 Spark/Trino/Airflow 로그 ingest를 흡수할 수 있는 sustainable TPS 정량화 |
| **도구** | flog Deployment (`replicas` 단계적 증가) → Fluent-bit DS → OpenSearch |
| **매니페스트** | `03-load-generators/flog.yaml` + `lt-config.yaml` (`FLOG_REPLICAS`) |
| **주요 변수** | `FLOG_REPLICAS` (5→20→50→100→200), `FLOG_DELAY` |
| **합격 기준** | 1시간 reject 0, FB output_errors 0, OS heap ≤ 75%, segment count 안정 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-08" |

```bash
# 운영: lt-config의 FLOG_REPLICAS=200 으로 ramp
kubectl --context=${KUBECONTEXT} edit configmap -n load-test lt-config
# FLOG_REPLICAS: "200"
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/03-load-generators/flog.yaml
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=200
# 1시간 sustain 후 metric 확인
```

## OS-09 — Spark Job Startup Burst (×30)

| 항목 | 내용 |
|------|------|
| **목적** | Spark/Airflow 작업 일제 시작 시 평소 대비 ×30 spike → backpressure·복구 검증 |
| **도구** | `kubectl scale`로 flog replicas 단기간 ×30 |
| **합격 기준** | spike 동안 drop 0 (FB filesystem buffer 사용), spike 종료 후 1분 내 backlog 소진, OS green 유지 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-09" |

```bash
# 평소 부하 (replicas=3) → 4분간 ×30 spike → 평소 복귀
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=90
sleep 240
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=3
# 대시보드에서 spike 곡선 + filesystem buffer 누적/소진 확인
```

## OS-12 — Refresh Interval 튜닝 비교

| 항목 | 내용 |
|------|------|
| **목적** | `refresh_interval`을 1s/30s/60s로 바꾸며 동일 부하에서 throughput·검색 가시성 trade-off |
| **도구** | curl로 `_settings` 변경 + flog 부하 |
| **합격 기준** | 30s/60s에서 indexing TPS ≥ 1s 대비 +30%, 검색 lag ≤ 60s |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-12" (refresh ops, segment count) |

```bash
# 1) 동일 부하 시작 (예: flog replicas=50)
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=50

# 2) refresh_interval 변경 (각 설정 30분씩 sustain)
for INTERVAL in 1s 30s 60s; do
  kubectl --context=${KUBECONTEXT} -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
    curl -sX PUT "${OPENSEARCH_URL}/logs-fb-*/_settings" \
    -H 'Content-Type: application/json' \
    -d "{\"index\": {\"refresh_interval\": \"${INTERVAL}\"}}"
  echo "interval=$INTERVAL applied at $(date +%H:%M:%S) — sleep 30m"
  sleep 1800
done
# 3) Grafana 대시보드에서 시간 범위로 3구간 비교
```

## OS-14 — High-Cardinality Field 폭증

| 항목 | 내용 |
|------|------|
| **목적** | Spark `task_attempt_id`, Airflow `dag_run_id` 같은 고유값 keyword가 매핑·cluster state에 미치는 압박 측정 |
| **도구** | `loggen-spark` Pod (Python 스크립트가 ConfigMap, UUID 주입) |
| **매니페스트** | `03-load-generators/loggen-spark.yaml` |
| **주요 변수** | `LOGGEN_DELAY`(생성 속도), replicas |
| **합격 기준** | 매핑 필드 수 < 1000, master heap ≤ 70%, cluster state size 안정 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-14" |

```bash
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/03-load-generators/loggen-spark.yaml
# 30분 후
kubectl --context=${KUBECONTEXT} -n monitoring exec opensearch-lt-node-0 -c opensearch -- \
  curl -s "${OPENSEARCH_URL}/_cluster/state?filter_path=metadata.indices.*.mappings.properties" | jq 'keys | length'
# 매핑 필드 수 추적; 종료 시 cleanup
kubectl --context=${KUBECONTEXT} delete -f deploy/load-testing/03-load-generators/loggen-spark.yaml
```

## OS-16 — Heavy Ingest + Light Search (운영 통합)

| 항목 | 내용 |
|------|------|
| **목적** | 가장 운영 현실적인 시나리오 — 200대 ingest 부하 중 6팀 간헐적 검색이 SLO 만족하는지 검증 |
| **도구** | flog (sustained ingest) + k6 6 VU `last 1h` range query |
| **매니페스트** | `04-test-jobs/k6-opensearch-light-search.yaml` |
| **주요 변수** | `LIGHT_SEARCH_VUS`(=6), `LIGHT_SEARCH_DURATION`, `OS_INDEX_PATTERN` |
| **합격 기준** | indexing TPS ≥ OS-08 단독 대비 95%, 검색 p95 ≤ 5s, error rate < 1% |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-opensearch`](#) → row "OS-16" |

```bash
# 1) Heavy ingest 시작
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=50

# 2) 동시에 6 VU light search Job
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/04-test-jobs/k6-opensearch-light-search.yaml
kubectl --context=${KUBECONTEXT} -n load-test wait --for=condition=complete \
  job/k6-opensearch-light-search --timeout=45m

# 3) k6 stdout summary에서 p95/p99 확인
kubectl --context=${KUBECONTEXT} -n load-test logs job/k6-opensearch-light-search | tail -30
```

---

# Fluent-bit (FB-01 ~ FB-07)

## FB-01 — 단일 Pod throughput ceiling

| 항목 | 내용 |
|------|------|
| **목적** | 단일 Fluent-bit Pod의 최대 lines/s 측정 |
| **도구** | flog (`-d 100us` 무한 루프) |
| **매니페스트** | `03-load-generators/flog.yaml` |
| **주요 변수** | `FLOG_REPLICAS`, `FLOG_DELAY` |
| **합격 기준** | per-pod ≥ 50,000 lines/s, drop=0 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) → row "FB-01" |

```bash
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/03-load-generators/flog.yaml
# 30분 후
kubectl --context=${KUBECONTEXT} delete -f deploy/load-testing/03-load-generators/flog.yaml
```

## FB-02 — 정상 운영 부하 (1h)

| 항목 | 내용 |
|------|------|
| **목적** | 평균 운영 부하 1시간 유지 시 buffer·자원 안정성 |
| **도구** | flog (`-d 500us`, `FLOG_REPLICAS=3`) |
| **합격 기준** | CPU/RSS ≤ limit 70%, buffer 누적 없음 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) → row "FB-02" |

```bash
# lt-config의 FLOG_DELAY를 500us로 변경 후 적용
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/03-load-generators/flog.yaml
```

## FB-03 — Output 장애 주입

| 항목 | 내용 |
|------|------|
| **목적** | OpenSearch 다운 시 Fluent-bit retry / filesystem buffer 적재 / 자동 복구 검증 |
| **도구** | `helm uninstall opensearch-lt` 후 다시 install |
| **합격 기준** | 데이터 손실 0, 복구 후 backlog 자동 소진 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) → row "FB-03" |

```bash
# 부하 진행 중
helm --kube-context=${KUBECONTEXT} -n monitoring uninstall opensearch-lt
sleep 300   # 5분 다운타임
bash deploy/load-testing/02-logging/install.sh   # 복구
```

## FB-04 — 멀티라인 스택트레이스

| 항목 | 내용 |
|------|------|
| **목적** | 멀티라인 로그 비율 ↑ 시 parser 지연·CPU 영향 |
| **도구** | 자바 스택트레이스 generator (custom) |
| **합격 기준** | parse 지연 ≤ 평소 ×1.5 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) → row "FB-04" |

## FB-05 — 로그 버스트 spike

| 항목 | 내용 |
|------|------|
| **목적** | ×30~×40 spike 시 backpressure·drop 거동 |
| **합격 기준** | drop=0 (filesystem buffer), 회복 후 backlog 소진 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) → row "FB-05" |

```bash
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=30
sleep 240
kubectl --context=${KUBECONTEXT} -n load-test scale deploy flog-loader --replicas=3
```

## FB-06 — Soak 24h

[`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) → row "FB-06". 평소 부하 24h 유지하며 RSS drift / FD / retry 누적 관찰.

## FB-07 — 대용량 로그 (1 line = 16 KB)

[`${GRAFANA_BASE_URL}/d/lt-fluent-bit`](#) → row "FB-07". flog `-b 16K` 또는 custom generator.

---

# Prometheus (PR-01 ~ PR-07)

## PR-01 — 수집 타깃 수 증가

| 항목 | 내용 |
|------|------|
| **목적** | 합성 endpoint 수 ↑ → scrape duration 측정 |
| **도구** | avalanche replicas 증가 |
| **매니페스트** | `03-load-generators/avalanche.yaml` |
| **주요 변수** | `AVALANCHE_REPLICAS` |
| **합격 기준** | scrape duration p95 ≤ 1s |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) → row "PR-01" |

```bash
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/03-load-generators/avalanche.yaml
kubectl --context=${KUBECONTEXT} -n load-test scale deploy avalanche --replicas=20   # 점진 증가
```

## PR-02 — Active Series 1M → 5M

| 항목 | 내용 |
|------|------|
| **도구** | avalanche `--gauge-metric-count`, `--series-count` |
| **합격 기준** | RSS ≤ pod limit 80%, compactions_failed 0 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) → row "PR-02" |

```bash
# lt-config 변경 후 avalanche 재배포
kubectl --context=${KUBECONTEXT} edit configmap -n load-test lt-config
# AVALANCHE_GAUGE_METRIC_COUNT: "500"
# AVALANCHE_SERIES_COUNT:       "500"
kubectl --context=${KUBECONTEXT} -n load-test rollout restart deploy avalanche
```

## PR-03 — PromQL 동시성

| 항목 | 내용 |
|------|------|
| **도구** | k6 PromQL queries |
| **매니페스트** | `04-test-jobs/k6-promql.yaml` |
| **주요 변수** | `K6_PROMQL_VUS`, `K6_PROMQL_DURATION` |
| **합격 기준** | http_req_duration p95 ≤ 2s |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) → row "PR-03" |

```bash
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/04-test-jobs/k6-promql.yaml
kubectl --context=${KUBECONTEXT} -n load-test wait --for=condition=complete job/k6-promql --timeout=15m
kubectl --context=${KUBECONTEXT} -n load-test logs job/k6-promql | tail -30
```

## PR-04 — 장기 Range Query (30d)

[`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) → row "PR-04". k6 스크립트의 query를 `query_range?start=...&end=...&step=30d`로 교체.

## PR-05 — Cardinality Spike

[`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) → row "PR-05". `AVALANCHE_LABEL_COUNT` ↑ + `AVALANCHE_SERIES_INTERVAL` ↓.

## PR-06 — WAL Replay 복구

```bash
# 부하 진행 중 Prometheus restart
kubectl --context=${KUBECONTEXT} -n monitoring delete pod prometheus-kps-prometheus-0
# 재시작 후 process_start_time_seconds 변화로 식별
```
[`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) → row "PR-06".

## PR-07 — Soak 24h

[`${GRAFANA_BASE_URL}/d/lt-prometheus`](#) → row "PR-07". 24h "Last 24 hours" 시간 범위로 RSS / 디스크 / churn 추세 확인.

---

# node-exporter (NE-01 ~ NE-07)

## NE-01 — Baseline collector scrape

| 항목 | 내용 |
|------|------|
| **목적** | 부하 없는 상태 baseline 캡처 |
| **합격 기준** | CPU ≤ 100m, RSS ≤ 50 MiB, samples ≤ 2,000 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-node-exporter`](#) → row "NE-01" |

```bash
# 부하 적용 없음, 5분간 dashboard 스냅샷
```

## NE-02 — 고빈도 scrape (5s)

| 항목 | 내용 |
|------|------|
| **도구** | hey (`/metrics` HTTP 부하) |
| **매니페스트** | `04-test-jobs/hey-node-exporter.yaml` |
| **주요 변수** | `HEY_CONCURRENCY`, `HEY_DURATION`, `HEY_RPS_PER_WORKER`, `NODE_EXPORTER_SVC` |
| **합격 기준** | p95 ≤ 300 ms, scrape timeout 0 |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-node-exporter`](#) → row "NE-02" |

```bash
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/04-test-jobs/hey-node-exporter.yaml
kubectl --context=${KUBECONTEXT} -n load-test wait --for=condition=complete job/hey-node-exporter --timeout=5m
kubectl --context=${KUBECONTEXT} -n load-test logs job/hey-node-exporter   # hey summary
```

## NE-03 — textfile 메트릭 1만 개

[`${GRAFANA_BASE_URL}/d/lt-node-exporter`](#) → row "NE-03". hostPath에 1만 라인 .prom 파일 생성.

```bash
kubectl --context=${KUBECONTEXT} -n monitoring exec ds/kps-prometheus-node-exporter -- \
  sh -c 'for i in $(seq 1 10000); do echo "bench_metric{idx=\"$i\"} $i"; done > /var/lib/node_exporter/bench.prom'
```

## NE-04 — 마운트 포인트 50+

[`${GRAFANA_BASE_URL}/d/lt-node-exporter`](#) → row "NE-04". 노드에 bind mount 50+ 추가 후 filesystem collector 영향 측정.

## NE-05 / NE-06 — CPU / Disk 포화

```bash
# stress-ng로 노드 CPU 90%
kubectl --context=${KUBECONTEXT} run stress --rm -it --image=alexeiled/stress-ng --restart=Never -- \
  --cpu 4 --cpu-load 90 --timeout 30m
# fio로 디스크 IO 포화
kubectl --context=${KUBECONTEXT} run fio --rm -it --image=lpabon/fio --restart=Never -- \
  --name=randwrite --rw=randwrite --bs=4k --size=1G --runtime=600 --time_based
```

## NE-07 — Soak 24h

[`${GRAFANA_BASE_URL}/d/lt-node-exporter`](#) → row "NE-07". goroutine / FD / RSS 누수 감지.

---

# kube-state-metrics (KSM-01 ~ KSM-07)

## KSM-01 — Baseline

[`${GRAFANA_BASE_URL}/d/lt-ksm`](#) → row "KSM-01". 현행 오브젝트 수와 KSM RSS 베이스라인.

## KSM-02 — Pod 대량 생성

| 항목 | 내용 |
|------|------|
| **도구** | kube-burner (`pod-density`) |
| **매니페스트** | `04-test-jobs/kube-burner-pod-density.yaml` |
| **주요 변수** | `KSM_BURNER_ITERATIONS`, `KSM_BURNER_QPS`, `KSM_BURNER_BURST` |
| **합격 기준** | /metrics p95 ≤ 2s, RSS ≤ pod limit 70% |
| **대시보드** | [`${GRAFANA_BASE_URL}/d/lt-ksm`](#) → row "KSM-02" |

```bash
# 운영 환경에서는 매니페스트의 jobIterations를 10000으로 변경
kubectl --context=${KUBECONTEXT} apply -f deploy/load-testing/04-test-jobs/kube-burner-pod-density.yaml
kubectl --context=${KUBECONTEXT} -n load-test wait --for=condition=complete job/kube-burner-pod-density --timeout=2h
```

## KSM-03 — ConfigMap 5만 개

[`${GRAFANA_BASE_URL}/d/lt-ksm`](#) → row "KSM-03". kube-burner config의 `objects.kind: ConfigMap`로 변경.

## KSM-04 — Namespace churn

[`${GRAFANA_BASE_URL}/d/lt-ksm`](#) → row "KSM-04". `jobType: delete + create`로 반복.

## KSM-05 — Shard 구성

```bash
# kps-kube-state-metrics를 StatefulSet로 변경 + --total-shards
kubectl --context=${KUBECONTEXT} -n monitoring edit deploy kps-kube-state-metrics
# args 추가: --pod=$(POD_NAME) --total-shards=3 --shard=$(SHARD_INDEX)
```
[`${GRAFANA_BASE_URL}/d/lt-ksm`](#) → row "KSM-05".

## KSM-06 — Soak 24h

[`${GRAFANA_BASE_URL}/d/lt-ksm`](#) → row "KSM-06". RSS / goroutine 안정성 확인.

## KSM-07 — allowlist/denylist 튜닝

```bash
# kps values.yaml: kube-state-metrics.metricLabelsAllowlist 또는 metricsDenylist 적용
helm --kube-context=${KUBECONTEXT} -n monitoring upgrade kps prometheus-community/kube-prometheus-stack \
    --version 76.5.1 -f deploy/load-testing/01-monitoring-core/values.yaml --reuse-values
```
[`${GRAFANA_BASE_URL}/d/lt-ksm`](#) → row "KSM-07".

---

## 부록 A — 결과 비교 템플릿

각 시나리오 실행 후 다음 표를 채우세요:

```markdown
| 시나리오 | 일시 | 변수 | 실측 | SLO | 판정 | 대시보드 스냅샷 |
|----------|------|------|------|-----|------|----------------|
| OS-01    | 2026-XX-XX | OSB_WORKLOAD=geonames | 13.8k docs/s | ≥ 30k | FAIL | <Grafana PNG export> |
```

대시보드 스냅샷: 각 row 상단의 "Share" 버튼 → "Snapshot" → 이미지 export.

## 부록 B — 시나리오 의존성

| 시나리오 | 사전 조건 |
|----------|----------|
| FB-01/02/03 | logging stack 배포됨 (Tier 2) |
| OS-02 | flog 5분 이상 동작 (인덱스에 데이터) |
| FB-03 | OpenSearch 정상 동작 후 의도적 다운 |
| KSM-02/03/04 | RBAC: cluster-admin (kube-burner SA) |
| OS-07 | OpenSearch multi-node (single-node에선 의미 없음) |
| PR-06 | Prometheus PVC 충분, retention ≥ 6h |
