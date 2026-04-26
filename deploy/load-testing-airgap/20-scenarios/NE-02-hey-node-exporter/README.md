# NE-02 — hey HTTP 부하 → node-exporter

외부 모니터링 시스템이 모든 노드를 동시에 5초 간격으로 scrape 하는 운영 사고를
시뮬레이션. node-exporter /metrics endpoint 에 직접 RPS 부하.

총 RPS = `HEY_CONCURRENCY × HEY_RPS_PER_WORKER` = 50 × 50 = **2,500 RPS** (2분).

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| node-exporter 가동 | `kubectl -n monitoring get ds kps-prometheus-node-exporter` | DESIRED=NODES |
| Service 도달 | `kubectl -n load-test run --rm -it tmp --image=nexus.intranet:8082/loadtest/loadtest-tools:0.1.1 -- curl -fsS ${NODE_EXPORTER_SVC}/metrics \| head` | metric output |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/NE-02-hey-node-exporter/
kubectl -n load-test logs -f job/hey-node-exporter
```

## 기대 결과 (정상 클러스터)

| 지표 | 기대 |
|------|------|
| Total requests | ~ 2,500 × 120s = 300,000 |
| 99% latency | < 50 ms |
| Status code distribution | 100% 2xx |
| node-exporter CPU spike | < 30% (per node) |
| `process_resident_memory_bytes` | flat (memory leak 없음) |

## 결과 확인

```bash
kubectl -n load-test logs job/hey-node-exporter | tail -40
```

hey 의 출력 형식:
```
Summary:
  Total:        120.0123 secs
  Slowest:      0.0890 secs
  Fastest:      0.0012 secs
  Average:      0.0156 secs
  Requests/sec: 2498.2

  Total data:   1.2 GB
  Size/request: 4.0 KB

Status code distribution:
  [200] 299784 responses
```

대시보드: `http://<grafana>/d/lt-node-exporter` → "NE-02 hey RPS" 패널

## 실패 신호

| 증상 | 원인 | 해결 |
|------|------|------|
| `Average > 100ms` | node CPU saturation | NE-04 (eviction) 시나리오 연계 검토 |
| 5xx 발생 | scrape budget 초과 | RPS 낮추거나 node-exporter `--web.max-requests` 상향 |
| latency 점진 증가 | 메모리 누수 | `process_resident_memory_bytes` 추세 확인 |

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/NE-02-hey-node-exporter/
```
