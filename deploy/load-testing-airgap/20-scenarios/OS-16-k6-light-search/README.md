# OS-16 — k6 light search (heavy ingest 동시)

운영 패턴 그대로 — 6 서비스 팀이 각자 Grafana 를 열어 "최근 1시간 ERROR
로그" 같은 range query 를 5~15초 간격으로 실행. 동시에 ingest 는 풀스로틀.

## 핵심 검증 SLO

★ heavy ingest 와 light search 가 *동시* 에 흘러도 search p95 < 5,000 ms

## 사전 조건 (반드시 동시 가동)

| 부하 | 명령 |
|------|------|
| flog (FB ingest)        | `kubectl apply -f deploy/load-testing-airgap/10-load-generators/flog-loader.yaml` |
| loggen-spark (OS-14 부하) | `kubectl apply -f deploy/load-testing-airgap/10-load-generators/loggen-spark.yaml` |
| (선택) opensearch-benchmark | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/` |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-16-k6-light-search/
kubectl -n load-test logs -f job/k6-opensearch-light-search
```

총 30분 동안 6 VU 가 각각 5-15초 간격으로 search.

## 기대 결과

| 지표 | 임계 | 의미 |
|------|------|------|
| `http_req_duration p95` | < 5,000 ms | 운영 SLO |
| `http_req_duration p99` | < 10,000 ms | tail latency |
| `http_req_failed`       | < 1% | 검색 실패 |
| `http_reqs` total       | ~ 720 ~ 2,160 | (6 VU × 1800s) / (5~15s) |

## 실패 시 의미

p95 > 5,000ms 가 발생하면 **운영 환경에서 6개 팀이 동시에 대시보드를 열면
검색이 5초 이상 걸린다**는 뜻 → search/indexing thread pool 분리, replica
증설, query cache 튜닝 필요.

## 결과 확인

```bash
kubectl -n load-test logs job/k6-opensearch-light-search | tail -40
```

대시보드: `http://<grafana>/d/lt-opensearch` → "OS-16 Light Search" 패널
(p95 / p99 lines + ingest rate overlay)

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/OS-16-k6-light-search/
# 부하 발생기는 다른 시나리오에서도 쓰이므로 그대로 둘 수 있음.
```
