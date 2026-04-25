# Load Testing Deployment

`docs/load-testing/` 가이드의 도구를 검증하기 위한 Kubernetes 매니페스트와 Helm values 모음입니다. 운영 규모 부하 테스트는 별도 에어갭 환경에서 수행하며, 본 디렉토리는 **도구·매니페스트의 동작 검증** 용입니다.

## 디렉토리 구조

```
deploy/load-testing/
├── 00-namespaces.yaml              # monitoring, load-test ns
├── 01-monitoring-core/             # Tier 1: kube-prometheus-stack
├── 02-logging/                     # Tier 2: OpenSearch + Fluent-bit
├── 03-load-generators/             # Tier 3: 상시 부하 타깃
│   ├── flog.yaml                   # FB-01/02/04/05 로그 생성기
│   └── avalanche.yaml              # PR-01/02/05 합성 메트릭 + ServiceMonitor
├── 04-test-jobs/                   # Tier 3: 일회성 Job
│   ├── opensearch-benchmark.yaml   # OS-01 인덱싱 벤치
│   ├── k6-promql.yaml              # PR-03/04 PromQL 부하
│   ├── k6-opensearch-search.yaml   # OS-02 검색 부하
│   ├── kube-burner-pod-density.yaml # KSM-02 Pod 1만 (single-node는 100으로 축소)
│   └── hey-node-exporter.yaml      # NE-02 /metrics HTTP 부하
└── 99-cleanup.sh                   # 전체 제거
```

각 ID(`OS-01`, `FB-01`, …)는 `docs/load-testing/0[1-5]-*.md` 의 시나리오 매트릭스를 참조합니다.

## 사전 준비

- 로컬 `kubectl` v1.36+ + context `minikube-remote` (원격 minikube 클러스터)
- 로컬 `helm` v3
- 원격 클러스터: 8 CPU / 16 GiB / 50 GiB (single-node minikube, kubernetes v1.35.x)

## 적용 순서

```bash
# 0. 네임스페이스
kubectl --context=minikube-remote apply -f 00-namespaces.yaml

# 1. monitoring core (Tier 1, ~3 GiB)
bash 01-monitoring-core/install.sh

# 2. logging stack (Tier 2, ~5 GiB) — 메모리 여유 시
bash 02-logging/install.sh

# 3. 시나리오별 적용
kubectl --context=minikube-remote apply -f 03-load-generators/avalanche.yaml
kubectl --context=minikube-remote apply -f 04-test-jobs/k6-promql.yaml
# 결과 확인 후
kubectl --context=minikube-remote -n load-test logs -l app=k6-promql --tail=-1
kubectl --context=minikube-remote delete -f 04-test-jobs/k6-promql.yaml
```

## Grafana / Prometheus 접근

minikube docker driver는 NodePort를 호스트에 자동 publish하지 않습니다. 다음 중 하나 사용:

```bash
# A. kubectl port-forward (가장 단순)
kubectl --context=minikube-remote -n monitoring port-forward svc/kps-grafana    3000:80
kubectl --context=minikube-remote -n monitoring port-forward svc/kps-prometheus 9090:9090

# B. SSH 터널 (호스트 NodePort 그대로 사용)
ssh -L 30030:127.0.0.1:30030 minikube-host  # Grafana
# minikube-01 안에서 minikube ssh 후 curl 192.168.49.2:30030 으로 검증 가능

# C. minikube tunnel (호스트에서, ingress 라우팅용 — 별도 daemon)
ssh minikube-host 'sudo minikube tunnel'
# 후 /etc/hosts에 'grafana.local 192.168.101.197' 추가 → http://grafana.local
```

## 현재 검증 상태

- [x] Tier 1 (kube-prometheus-stack) 배포 — Prometheus, Grafana, Alertmanager, node-exporter, kube-state-metrics 모두 Running
- [x] 크로스-namespace ServiceMonitor 픽업 검증 (avalanche → `up{job="avalanche"}=1`)
- [ ] Tier 2 (OpenSearch + Fluent-bit) — 미배포 (수동 트리거)
- [ ] Test jobs 실행 확인 — 각 Job별로 시나리오 적용 후 로그 확인 필요

## 주의

- 단일 노드라 `docs/load-testing/`의 SLO(예: OS 30k TPS, Prom 5M series, KSM 10k pod) 도달은 **목표 아님**. 본 매니페스트는 실행 가능성/도구 동작 확인용.
- OpenSearch + 부하 생성기 동시 실행 시 OOM 주의. Tier 2를 띄울 땐 `flog/avalanche` replicas 축소.
- 테스트 후 Job/Deployment 정리 필수 (`99-cleanup.sh` 또는 개별 `kubectl delete`).
- `kube-burner-pod-density.yaml`의 `jobIterations`는 single-node 기준 100으로 축소해 둠. 운영 환경에서는 10000으로 상향.
