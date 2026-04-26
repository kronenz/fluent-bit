# 통합 부하 테스트 계획서

폐쇄망 환경에서 시나리오를 선택적으로 실행하기 위한 운영 절차서.

## 0. 적용 범위

- **대상 클러스터**: 사내 폐쇄망 Kubernetes (200 노드 규모 운영 시뮬레이션)
- **테스트 대상**: OpenSearch / Fluent-bit / Prometheus / Node-exporter / kube-state-metrics
- **부하 도구**: opensearch-benchmark, k6, hey, kube-burner, flog, avalanche, loggen-spark
- **이미지**: `nexus.intranet:8082/loadtest/loadtest-tools:0.1.1`
- **기간**: 시나리오별 2분 ~ 30분

---

## 1. 사전 준비 체크리스트

| # | 항목 | 명령 | 정상 |
|---|------|------|------|
| 1 | Nexus 도달 가능 | `docker pull nexus.intranet:8082/loadtest/loadtest-tools:0.1.1` | OK |
| 2 | imagePullSecret (인증 필요 시) | `kubectl -n load-test get secret nexus-cred` | exists |
| 3 | kube-prometheus-stack 가동 | `kubectl -n monitoring get pod -l release=kps` | 모두 Running |
| 4 | OpenSearch 가동 | `kubectl -n monitoring get sts -l app.kubernetes.io/name=opensearch` | READY 일치 |
| 5 | fluent-bit DaemonSet 가동 | `kubectl -n kube-system get ds fluent-bit` | DESIRED=NODES |
| 6 | namespace + lt-config | `kubectl apply -f deploy/load-testing-airgap/00-prerequisites/` | created |
| 7 | OpenSearch Secret (admin/admin) | `kubectl -n load-test get secret opensearch-creds` | exists |
| 8 | Grafana 접속 | `http://<grafana-host>:3000/d/lt-overview` | login OK |

---

## 2. 시나리오 카탈로그 (실행 절차 + 기대 결과)

### 2.1 OpenSearch 시나리오

| ID | 이름 | 사전 부하 | 실행 명령 | 소요 | 핵심 SLO | 결과 확인 |
|----|------|----------|-----------|------|----------|----------|
| OS-01 | OSB bulk-ingest | — | `kubectl apply -f .../OS-01-osb-bulk-ingest/` | 30s ~ 15m | exit code 0 | `kubectl logs job/opensearch-benchmark` |
| OS-02 | k6 heavy search | flog 10분+ 가동 | `kubectl apply -f .../OS-02-k6-heavy-search/` | 7m | p95 < 500ms, p99 < 1.5s, fail < 0.5% | `kubectl logs job/k6-opensearch-search` |
| OS-14 | high-cardinality | — | `kubectl apply -f 10-load-generators/loggen-spark.yaml` | 30m+ | mapping field < 10,000 | `_cluster/state` size 추세 |
| OS-16 | k6 light search | flog + loggen-spark + (선택) OSB 동시 가동 | `kubectl apply -f .../OS-16-k6-light-search/` | 30m | **p95 < 5,000ms**, fail < 1% | `kubectl logs job/k6-opensearch-light-search` |

### 2.2 Fluent-bit 시나리오

| ID | 이름 | 사전 부하 | 실행 명령 | 소요 | 핵심 SLO | 결과 확인 |
|----|------|----------|-----------|------|----------|----------|
| FB-01~07 | ingest pipeline | — | `kubectl apply -f 10-load-generators/flog-loader.yaml` | 지속 | drop rate = 0 | Grafana `lt-fluent-bit` |

### 2.3 Prometheus 시나리오

| ID | 이름 | 사전 부하 | 실행 명령 | 소요 | 핵심 SLO | 결과 확인 |
|----|------|----------|-----------|------|----------|----------|
| PR-01/02/05 | active series | — | `kubectl apply -f 10-load-generators/avalanche.yaml` | 지속 | scrape p95 < 0.5s | Grafana `lt-prometheus` |
| PR-03 | concurrent queries | avalanche 권장 | `kubectl apply -f .../PR-03-04-k6-promql/` | 5m | p95 < 2,000ms, fail < 1% | `kubectl logs job/k6-promql` |
| PR-04 | wide range agg | (위와 동일 — 쿼리에 heavy case 포함) | (PR-03 과 동일 Job) | 5m | p99 engine < 5s | `prometheus_engine_query_duration_seconds` |

### 2.4 Node-exporter 시나리오

| ID | 이름 | 사전 부하 | 실행 명령 | 소요 | 핵심 SLO | 결과 확인 |
|----|------|----------|-----------|------|----------|----------|
| NE-02 | hey RPS | — | `kubectl apply -f .../NE-02-hey-node-exporter/` | 2m | p99 < 50ms, 100% 2xx | `kubectl logs job/hey-node-exporter` |

### 2.5 kube-state-metrics 시나리오

| ID | 이름 | 사전 부하 | 실행 명령 | 소요 | 핵심 SLO | 결과 확인 |
|----|------|----------|-----------|------|----------|----------|
| KSM-02 | scrape time | — | `kubectl apply -f .../KSM-02-04-kube-burner/` | 5~15m | scrape p95 < 1s | `kube_state_metrics_scrape_duration_seconds` |
| KSM-03 | ingest backlog | (위와 동일 Job) | (위와 동일) | (위와 동일) | head_chunks 안정 | Grafana `lt-ksm` |
| KSM-04 | watch event burst | (위와 동일 Job) | (위와 동일) | (위와 동일) | watch latency < 100ms | apiserver_watch_events_total |

---

## 3. 추천 실행 시퀀스

### 3.1 빠른 smoke test (15분)

| 순서 | 작업 | 시간 |
|------|------|------|
| 1 | `kubectl apply -f 00-prerequisites/` | 1m |
| 2 | `kubectl apply -f 20-scenarios/OS-01-osb-bulk-ingest/` (test-mode) | 1~2m |
| 3 | OS-01 종료 후 `kubectl apply -f 20-scenarios/NE-02-hey-node-exporter/` | 2m |
| 4 | NE-02 종료 후 Grafana 패널 확인 | 5m |
| 5 | `kubectl delete -f 20-scenarios/OS-01-... 20-scenarios/NE-02-...` | — |

### 3.2 운영 시뮬레이션 (60분)

| 시점 | 작업 | 동작 |
|------|------|------|
| t=0   | 모든 부하 발생기 가동 (`kubectl apply -f 10-load-generators/`) | 백그라운드 ingest 시작 |
| t=10m | OS-01 OSB 실행 (1차) | 인덱스 채우기 |
| t=15m | OS-16 k6 light-search Job 시작 (30분) | search SLO 검증 |
| t=20m | KSM-02/03/04 시작 | 컨트롤플레인 부하 |
| t=30m | OS-02 k6 heavy-search 시작 (선택) | stress 케이스 |
| t=45m | 부하 발생기 정지 (`kubectl scale --replicas=0`) | wind-down |
| t=60m | 모든 Job/Deployment 정리, 결과 수집 | — |

### 3.3 단일 시나리오 회귀 테스트 (사전 의존만 가동)

```bash
# 예) OS-16 만 검증
kubectl apply -f deploy/load-testing-airgap/10-load-generators/flog-loader.yaml
kubectl apply -f deploy/load-testing-airgap/10-load-generators/loggen-spark.yaml
sleep 600   # 인덱스 채움
kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-16-k6-light-search/
kubectl -n load-test logs -f job/k6-opensearch-light-search
```

---

## 4. 결과 판정 기준

각 시나리오 README 의 "기대 결과" 표 vs 실제값 비교. 종합 판정:

| 종합 판정 | 기준 |
|-----------|------|
| ✅ PASS  | 모든 시나리오의 SLO 충족 + Job exit code 0 |
| ⚠ WARN  | 1~2개 시나리오의 SLO p95/p99 임계 근접 (90~100%) — 운영 적용 가능하나 모니터링 필요 |
| ❌ FAIL | OOMKilled / 인덱스 손상 / SLO 30%+ 초과 — 운영 적용 보류 |

---

## 5. 자동화/스케줄링 (선택)

야간 회귀: CronJob 으로 `00-prerequisites/` + `20-scenarios/OS-01/` 만 실행, 결과를
OS 인덱스 `loadtest-results-YYYY.MM.DD` 에 적재. (현재 미구현 — 향후 작업)

---

## 6. 관련 문서

- [README.md](../README.md) — 폴더 구조 / 빠른 시작
- [02-troubleshooting.md](02-troubleshooting.md) — 흔한 실패 + 해결법
- [03-result-verification.md](03-result-verification.md) — Grafana / kubectl / API
- [../../../docs/load-testing/08-scenario-catalog.md](../../../docs/load-testing/08-scenario-catalog.md) — 전체 시나리오 카탈로그 (35+)
