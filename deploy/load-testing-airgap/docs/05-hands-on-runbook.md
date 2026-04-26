# 핸즈온 런북 — testbed 시나리오 검증

concept.md 의 요구사항 ("현재 테스트베드 환경에서 테스트를 수행하고 제대로
동작하는지 시나리오별로 핸즈온 해본다음 폐쇄망으로 옮겨 구성") 에 대응.
각 시나리오를 testbed (minikube-remote) 에서 단계별로 검증하는 절차.

## 0. testbed 사양 / 가정

| 항목 | 값 |
|------|-----|
| context | `minikube-remote` |
| 노드 | 단일 노드 (32 CPU, 64 GB) |
| OpenSearch | `opensearch-lt-node-0` 단일 instance (replica=0) |
| fluent-bit | DaemonSet 1 pod |
| Prometheus | `kps-prometheus` 단일 instance |
| KSM | `kps-kube-state-metrics` 단일 instance |
| node-exporter | DaemonSet 1 pod |

⚠ 단일노드 한계:
- KSM-02-04 / KSM-OOM 의 jobIterations 는 50 이하 (이상 시 timeout)
- CHAOS-OS-07 은 의도된 실패로 동작 (replica=0 → green 회복 불가)
- OS replica scaling 시나리오 (OS-04) 는 의미 없음

## 1. 사전 정리 + apply (모든 시나리오 공통)

```bash
CTX=minikube-remote

# 이전 Job 잔재 정리
kubectl --context=$CTX -n load-test delete jobs --all --wait=false
kubectl --context=$CTX get ns -o name | grep -E '^namespace/(kburner|ksm-oom)-' | xargs -r kubectl --context=$CTX delete --wait=false

# 사전 객체 적용
kubectl --context=$CTX apply -f deploy/load-testing-airgap/00-prerequisites/

# 부하 발생기 가동
kubectl --context=$CTX apply -f deploy/load-testing-airgap/10-load-generators/
```

## 2. 시나리오 핸즈온 순서 (testbed 기준)

권장 순서 — 가벼운 것부터 → 무거운 것 → 장애:

| # | 시나리오 | 예상 시간 | 비고 |
|---|----------|-----------|------|
| 1 | NE-02 hey RPS | 2m | 가장 빠름. 도구 동작 확인 |
| 2 | OS-01 OSB --test-mode | 1~2m | 1k docs 빠른 sanity |
| 3 | KSM-02-04 kube-burner | 5~15m | testbed iter=50 으로 안전 |
| 4 | PR-03-04 k6 PromQL | 5m | avalanche 가동 후 |
| 5 | OS-02 k6 heavy search | 7m | 인덱스 사전 채움 필요 |
| 6 | OS-16 k6 light search | 30m | 핵심 SLO. flog 동시 |
| 7 | NE-OOM-tuning | 4m | RPS ramp |
| 8 | KSM-OOM-tuning | 5m | 객체 ramp |
| 9 | FB-OOM-tuning | 18m | flog scale ramp (자동) |
| 10 | CHAOS-FB-restart | 3m | offset DB 검증 |
| 11 | CHAOS-OS-07 | 10m | (testbed 의도된 FAIL) |

## 3. 시나리오별 명령 + 결과 확인

### 3.1 NE-02 (hey RPS)

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/NE-02-hey-node-exporter/
sleep 130
kubectl --context=$CTX -n load-test logs job/hey-node-exporter | tail -30
```

**합격**: `[200] N responses` 가 100% (2xx 만 있음), Average < 50ms.

### 3.2 OS-01 OSB

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/
kubectl --context=$CTX -n load-test logs -f job/opensearch-benchmark
```

**합격**: 마지막 줄 `OSB SUCCESS`, exit code 0.

### 3.3 KSM-02-04 (testbed iter=50)

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/KSM-02-04-kube-burner/
kubectl --context=$CTX -n load-test logs -f job/kube-burner-pod-density
```

**합격**: `Total elapsed time: ...` 출력, exit code 0. 50/50 iter 완료.

### 3.4 PR-03-04 (k6 PromQL)

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/PR-03-04-k6-promql/
kubectl --context=$CTX -n load-test logs -f job/k6-promql
```

**합격**: thresholds `✓` (p95<2000, fail<1%).

### 3.5 OS-02 (k6 heavy search)

```bash
# 인덱스 사전 채움 — flog 가 이미 가동 중이면 5~10분 대기로 충분
kubectl --context=$CTX -n monitoring exec opensearch-lt-node-0 -- \
  curl -u admin:admin -s 'http://localhost:9200/_cat/indices/logs-fb-*?v'
# logs-fb-* 인덱스의 doc count ≥ 100k 인지 확인

kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/OS-02-k6-heavy-search/
kubectl --context=$CTX -n load-test logs -f job/k6-opensearch-search
```

**합격**: thresholds `✓` (p95<500, p99<1500, fail<0.5%).

### 3.6 OS-16 (k6 light search) — 핵심 SLO

```bash
# 사전: flog + loggen-spark 동시 가동 (이미 10-load-generators apply 했으면 OK)
kubectl --context=$CTX get deploy -n load-test -l role=load-generator

kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/OS-16-k6-light-search/
# 30분 대기 — 다른 시나리오 병행 가능
kubectl --context=$CTX -n load-test logs -f job/k6-opensearch-light-search
```

**합격**: thresholds `✓` (★ p95 < 5,000, p99 < 10,000, fail < 1%).

### 3.7 NE-OOM-tuning

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/NE-OOM-tuning/
kubectl --context=$CTX -n load-test logs -f job/ne-oom-tuning
```

**기록**: 각 stage RSS 값 표로 정리.

### 3.8 KSM-OOM-tuning

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/KSM-OOM-tuning/
kubectl --context=$CTX -n load-test logs -f job/ksm-oom-tuning

# 잔재 정리
kubectl --context=$CTX get ns -o name | grep '^namespace/ksm-oom-' | xargs -r kubectl --context=$CTX delete --wait=false
```

**기록**: KSM RSS + scrape duration vs ramp 단계.

### 3.9 FB-OOM-tuning

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/FB-OOM-tuning/
kubectl --context=$CTX -n load-test logs -f job/fb-oom-tuning
# 18분 자동 ramp
```

**기록**: 각 stage fluent-bit RSS. peak 단계에서 OOM 여부.

### 3.10 CHAOS-FB-restart

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/CHAOS-FB-restart/
kubectl --context=$CTX -n load-test logs -f job/chaos-fb-restart
```

**합격**: `[PASS] ingest 끊김 없음` 출력.

### 3.11 CHAOS-OS-07 (testbed 한정 의도된 FAIL)

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/20-scenarios/CHAOS-OS-07-node-failure/
kubectl --context=$CTX -n load-test logs -f job/chaos-os-07-node-failure
```

**testbed 결과 (정상)**: `[FAIL] green 회복 실패 — replica ≥ 1 필요` — 이는 단일노드 환경의 의도된 실패. 멀티노드에서는 PASS 확인.

## 4. 결과 보고 양식

각 시나리오 종료 시 아래 양식으로 기록:

```
시나리오     : NE-02
실행 일시    : 2026-04-26 12:00
조작변수     : HEY_CONCURRENCY=50, HEY_DURATION=2m, HEY_RPS_PER_WORKER=50
통제변수     : 단일노드 minikube, helm chart 기본 limit
측정값       : Total 300,000 reqs, p99 38ms, 100% 2xx
판정         : ✅ PASS
비고         : node-exporter restart 0 (이전 17회 OOM 이후 안정)
```

## 5. 종합 확인

11개 시나리오 모두 진행 후:

```bash
# 모든 Job 상태
kubectl --context=$CTX -n load-test get jobs -o wide

# Grafana 대시보드 (모든 패널 데이터 채워짐 확인)
# http://<grafana>/d/lt-overview
# http://<grafana>/d/lt-opensearch
# http://<grafana>/d/lt-fluent-bit
# http://<grafana>/d/lt-prometheus
# http://<grafana>/d/lt-node-exporter
# http://<grafana>/d/lt-ksm

# OOMKilled 발생 횟수 (모든 컴포넌트)
for ns in monitoring load-test; do
  kubectl --context=$CTX -n $ns get pod \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].restartCount}{"\n"}{end}' \
    | awk '$2 > 0'
done
```

## 6. testbed → 폐쇄망 이전 체크리스트

| # | 항목 | 확인 |
|---|------|------|
| 1 | loadtest-tools 이미지 Nexus 존재 | `docker pull nexus.intranet:8082/loadtest/loadtest-tools:0.1.1` |
| 2 | pause:3.10 Nexus 존재 | `docker pull nexus.intranet:8082/loadtest/pause:3.10` |
| 3 | helm 차트 이미지 Nexus mirror | (별도 list) |
| 4 | imagePullSecret (인증 필요 시) | `kubectl create secret docker-registry nexus-cred ...` |
| 5 | OpenSearch security plugin → admin/admin Secret | `00-prerequisites/opensearch-creds.yaml` 적용 |
| 6 | sed 로 Nexus 주소 일괄 변경 (다른 host인 경우) | (`README.md` §"Nexus 주소 변경" 참조) |
| 7 | OS 노드 ≥ 3 (CHAOS-OS-07 의미 회복) | helm values 의 replicaCount |
| 8 | 인덱스 replica ≥ 1 (CHAOS 데이터 손실 방지) | OS index template |
| 9 | KSM-02-04 / KSM-OOM iter 운영급으로 상향 | `kustomize edit` 또는 sed |
| 10 | testbed 에서 11개 시나리오 모두 ✅ PASS | (위 §3 결과) |
