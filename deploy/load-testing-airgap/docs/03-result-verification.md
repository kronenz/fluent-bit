# 결과 확인 가이드

부하 테스트 후 결과를 확인하는 4가지 경로.

## 1. Grafana 대시보드 (1차 결과)

| 대시보드 | URL 끝 | 시나리오 매핑 |
|----------|--------|---------------|
| Overview     | `/d/lt-overview`     | 전체 통합 — Health 5종 + 시나리오 progress |
| OpenSearch   | `/d/lt-opensearch`   | OS-01, OS-02, OS-14, OS-16 |
| Fluent-bit   | `/d/lt-fluent-bit`   | FB-01 ~ FB-07 |
| Prometheus   | `/d/lt-prometheus`   | PR-01, PR-02, PR-03, PR-04, PR-05 |
| Node-exporter| `/d/lt-node-exporter`| NE-01 ~ NE-04 |
| KSM          | `/d/lt-ksm`          | KSM-01 ~ KSM-04 |

각 패널에 "왜 측정?" 설명이 포함되어 있어 SLO 위반 시 의미 해석 가능.

대시보드는 별도로 적용:
```bash
kubectl apply -f deploy/load-testing/05-dashboards/dashboards.yaml
```

## 2. kubectl logs (Job 결과)

| Job | 명령 | 끝부분 의미 |
|-----|------|-------------|
| opensearch-benchmark | `kubectl -n load-test logs job/opensearch-benchmark` | result.json (JSON) — throughput, latency_p95, error_rate |
| k6-opensearch-search | `kubectl -n load-test logs job/k6-opensearch-search \| tail -50` | k6 summary — http_req_duration / http_req_failed |
| k6-opensearch-light-search | `kubectl -n load-test logs job/k6-opensearch-light-search \| tail -50` | (위와 동일 형식, 30분 결과) |
| k6-promql | `kubectl -n load-test logs job/k6-promql \| tail -30` | (위와 동일) |
| hey-node-exporter | `kubectl -n load-test logs job/hey-node-exporter` | hey summary — Total / Slowest / Average / Status code dist |
| kube-burner-pod-density | `kubectl -n load-test logs job/kube-burner-pod-density` | "Total elapsed time", per-iteration stats |

## 3. Prometheus 직접 쿼리 (정량 검증)

```bash
PROM=http://kps-prometheus.monitoring.svc:9090

# OS 시나리오: 인덱싱 throughput
curl -s "$PROM/api/v1/query?query=rate(elasticsearch_indices_indexing_index_total[1m])" | jq

# Fluent-bit: input vs output rate (drop 이 있으면 둘 차이 발생)
curl -s "$PROM/api/v1/query?query=sum(rate(fluentbit_input_records_total[1m]))" | jq
curl -s "$PROM/api/v1/query?query=sum(rate(fluentbit_output_proc_records_total[1m]))" | jq

# Prometheus: active series
curl -s "$PROM/api/v1/query?query=prometheus_tsdb_head_series" | jq

# Node-exporter: scrape duration p95
curl -s "$PROM/api/v1/query?query=histogram_quantile(0.95,rate(prometheus_target_scrape_duration_seconds_bucket{job=\"node-exporter\"}[5m]))" | jq

# KSM: scrape duration
curl -s "$PROM/api/v1/query?query=kube_state_metrics_scrape_duration_seconds" | jq
```

## 4. OpenSearch 직접 쿼리

```bash
# admin:admin (security plugin)
OS_AUTH="-u admin:admin"
OS=http://opensearch-lt-node.monitoring.svc:9200

# 인덱스 doc count
curl -s $OS_AUTH "$OS/_cat/indices/logs-fb-*?v"

# cluster health
curl -s $OS_AUTH "$OS/_cluster/health?pretty"

# search latency stats
curl -s $OS_AUTH "$OS/_nodes/stats/indices/search" | jq '.nodes[].indices.search'

# segment / merge / refresh stats (FB 시나리오)
curl -s $OS_AUTH "$OS/_nodes/stats/indices/segments,merges,refresh" | jq '.nodes[].indices'
```

---

## 5. SLO 매트릭스 (시나리오 ↔ 측정값 ↔ 임계)

| 시나리오 | 측정값 | 정상값 | 측정 방법 |
|----------|--------|--------|-----------|
| OS-01 | OSB throughput | TEST_MODE: 200~1k docs/s; 운영: 5k~50k | `kubectl logs job/opensearch-benchmark` |
| OS-01 | OSB p95 latency | < 50ms (test) / < 500ms (운영) | (위와 동일) |
| OS-02 | k6 search p95 | < 500 ms | `kubectl logs job/k6-opensearch-search` |
| OS-02 | k6 search p99 | < 1,500 ms | (위와 동일) |
| OS-14 | mapping field 수 | < 10,000 | `curl $OS/_mapping` |
| OS-14 | cluster_state size | < 50 MB | `curl $OS/_cluster/state` |
| OS-16 | k6 search p95 | **< 5,000 ms** ★핵심 | `kubectl logs job/k6-opensearch-light-search` |
| FB    | drop rate | 0 | Grafana FB 패널 |
| FB    | input vs output rate | 일치 | Prometheus query |
| PR-01 | active series | < 5M (운영) | `prometheus_tsdb_head_series` |
| PR-02 | scrape p95 | < 0.5s | `histogram_quantile(0.95, ...)` |
| PR-03 | k6 query p95 | < 2,000 ms | `kubectl logs job/k6-promql` |
| PR-05 | OOMKilled 후 WAL replay | < 15분 (운영) | `kubectl describe pod prometheus-*` |
| NE-02 | hey p99 | < 50 ms | `kubectl logs job/hey-node-exporter` |
| NE-02 | 2xx 비율 | 100% | (위와 동일) |
| KSM-02 | KSM scrape p95 | < 1s | `kube_state_metrics_scrape_duration_seconds` |
| KSM-04 | apiserver watch latency | < 100ms | `apiserver_watch_events_total` rate |

---

## 6. 결과 보고 양식 (운영 보고용)

```
## 통합 부하 테스트 결과 (YYYY-MM-DD)

| 시나리오 | 결과 | 측정값 | 임계 | 판정 |
|----------|------|--------|------|------|
| OS-01    | exit 0 | throughput 850 docs/s, p95 32ms | 200~1000 docs/s | ✅ |
| OS-02    | exit 0 | p95 387ms, p99 974ms, fail 0.2% | p95<500, p99<1500, fail<0.5% | ✅ |
| OS-16    | exit 0 | p95 3,212ms, p99 7,891ms, fail 0.4% | p95<5000, p99<10000, fail<1% | ✅ |
| FB-*     | drop 0 | input 30k/s, output 30k/s | drop=0 | ✅ |
| PR-03    | exit 0 | p95 1,124ms, fail 0.1% | p95<2000, fail<1% | ✅ |
| NE-02    | exit 0 | p99 38ms, 2xx 100% | p99<50, 2xx=100% | ✅ |
| KSM-02   | exit 0 | scrape p95 0.8s | p95<1s | ✅ |

종합 판정: ✅ PASS
```

자동 생성을 원하면 `kubectl get jobs -n load-test -o json | jq` 와 위 SLO 매트릭스를
조합한 스크립트 작성 가능 (현재 미구현).
