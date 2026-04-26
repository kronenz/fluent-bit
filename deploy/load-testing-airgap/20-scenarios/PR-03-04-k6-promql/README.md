# PR-03 / PR-04 — k6 PromQL 쿼리 부하

운영 Grafana 에서 보는 7가지 PromQL 패턴을 라운드 로빈으로 실행해
Prometheus 의 query path 를 부하.

| ID | 이름 | 차이점 |
|----|------|-------|
| PR-03 | concurrent queries | 동시성 기준선 (20 VU × 5m) |
| PR-04 | wide range + heavy agg | 위 7개 쿼리 중 3번 (`topk`, `sum by`, `histogram_quantile`) 가 heavy 케이스 |

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| Prometheus 도달 | `kubectl -n load-test run --rm -it tmp --image=nexus.intranet:8082/loadtest/loadtest-tools:0.1.1 -- curl -fsS ${PROMETHEUS_URL}/-/ready` | `Prometheus is Ready` |
| 충분한 series | (avalanche 또는 운영 metric 가 1k+ series 노출 중) | — |

## 실행

```bash
# 권장: avalanche 와 함께 가동 (실제 query 부하)
kubectl apply -f deploy/load-testing-airgap/10-load-generators/avalanche.yaml
sleep 60   # avalanche scrape 정착 대기

kubectl apply -f deploy/load-testing-airgap/20-scenarios/PR-03-04-k6-promql/
kubectl -n load-test logs -f job/k6-promql
```

## 부하 패턴

| Stage | 시간 | VU |
|-------|------|----|
| Sustained | 5m | 20 |

총 요청 ≈ 20 VU × (1/0.1s) × 300s = **60,000 req**.

## 기대 결과

| 지표 | 임계 | 의미 |
|------|------|------|
| `http_req_duration p95` | < 2,000 ms | 95% 쿼리 2초 내 |
| `http_req_failed`        | < 1%       | 거의 모든 쿼리 성공 |
| Prometheus CPU 사용     | < 80% req  | thread saturation 없음 |
| `prometheus_engine_query_duration_seconds` | p99 < 5s | engine eval p99 |

## 결과 확인

```bash
kubectl -n load-test logs job/k6-promql | tail -30
```

대시보드: `http://<grafana>/d/lt-prometheus` → "PR-03/04 Query Load" 패널

```bash
# Prometheus 자체 query rate
curl -s "${PROMETHEUS_URL}/api/v1/query?query=rate(prometheus_http_requests_total{handler='/api/v1/query'}[1m])" | jq
```

## 실패 신호

| 증상 | 원인 | 해결 |
|------|------|------|
| `p(95) > 2000ms` | Prometheus CPU/heap 부족 | resources 증설 또는 query timeout 조정 |
| 5xx 빈발 | engine eval timeout | `--query.timeout` 상향, query 간소화 |
| OOMKilled (Prom) | heavy query × series 폭증 | `--query.max-samples` 낮춤 |

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/PR-03-04-k6-promql/
```
