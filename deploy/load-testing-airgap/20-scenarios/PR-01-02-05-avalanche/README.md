# PR-01 / PR-02 / PR-05 — Prometheus ingest 부하 (avalanche)

avalanche 가 노출하는 합성 /metrics 를 ServiceMonitor 가 등록 → kps-prometheus
가 자동 scrape. 이 시나리오는 *부하 발생기 가동만으로* 측정이 진행되며 별도
Job 이 없습니다.

| ID | 이름 | 측정 포인트 |
|----|------|-------------|
| PR-01 | active series 적재 | prometheus_tsdb_head_series, ingest rate |
| PR-02 | scrape budget       | scrape_duration_seconds, scrape_samples_scraped |
| PR-05 | cardinality bomb    | head series 폭증 → WAL replay → OOM 재현 |

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| Prometheus 가동 | `kubectl -n monitoring get pod -l app.kubernetes.io/name=prometheus` | Running |
| ServiceMonitor selector | `kubectl -n monitoring get prometheus -o yaml \| grep namespaceSelector` | `any: true` |
| Prometheus heap | `kubectl -n monitoring describe pod kps-prometheus-* \| grep -i memory` | limit ≥ 4Gi |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/10-load-generators/avalanche.yaml
```

5분 후 prometheus 가 본격 scrape 시작 (scrape interval 15s).

## 부하 강도 조절

| 조절값 | 위치 | 효과 |
|--------|------|------|
| replicas | `kubectl scale deploy/avalanche` | active series 선형 증가 |
| --gauge-metric-count | args | metric name 수 |
| --series-count       | args | metric 당 series 수 |
| --label-count        | args | series 당 label 수 (cardinality 폭증 강도) |

PR-05 (cardinality bomb) 재현:
```bash
kubectl -n load-test patch deployment avalanche --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args","value":[
    "--gauge-metric-count=2000",
    "--series-count=2000",
    "--label-count=20",
    "--port=9001"
  ]}]'
# per-pod 4M series → prometheus heap 폭증 관찰
```

## 결과 확인

```bash
# active series
curl -s "${PROMETHEUS_URL}/api/v1/query?query=prometheus_tsdb_head_series" | jq

# scrape duration p95
curl -s "${PROMETHEUS_URL}/api/v1/query?query=histogram_quantile(0.95,sum(rate(prometheus_target_scrape_duration_seconds_bucket[5m]))%20by%20(le))"
```

대시보드: `http://<grafana>/d/lt-prometheus` → "PR-01 / PR-02 / PR-05" 패널

## 기대 결과

| 지표 | 기본 (200×200×2) | 운영 (500×500×20) |
|------|--------------------|---------------------|
| active series | ~ 80,000 | ~ 5,000,000 |
| Prometheus heap | < 1 GB | 5 ~ 8 GB |
| scrape p95 | < 0.5 s | < 2 s |
| WAL replay 시간 (재시작) | < 30 s | 5 ~ 15 분 |

PR-05 임계 도달 시 prometheus pod 가 OOMKilled 되며, 이때 WAL 복구 시간을
측정하는 것이 시나리오의 진짜 목적입니다.

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/10-load-generators/avalanche.yaml

# active series 정리는 prometheus retention (기본 24h) 기다리거나 즉시:
kubectl -n monitoring delete pod -l app.kubernetes.io/name=prometheus  # WAL 만 보존
```
