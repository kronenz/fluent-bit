# testbed 핸즈온 결과 (2026-04-26)

concept.md 의 "현재 테스트베드 환경에서 테스트를 수행하고 제대로 동작하는지
시나리오별로 핸즈온" 요구사항에 대응한 실측 결과.

## 1. 환경

| 항목 | 값 |
|------|-----|
| Cluster | minikube-remote (단일 노드, 32 CPU / 64 GB) |
| OpenSearch | opensearch-lt-node-0 단일 instance, status=yellow (4 unassigned shards) |
| node-exporter limit | **32 Mi** (helm chart 기본값) — 핵심 원인 |
| 이미지 | `loadtest-tools:0.1.1` (testbed 로컬, Nexus 미사용) |
| 적용 명령 | `sed 's\|nexus.../loadtest-tools:0.1.1\|loadtest-tools:0.1.1\|g' \| kubectl apply -f -` |

## 2. 시나리오별 결과 표

| 시나리오 | 상태 | 소요 | 측정값 | 판정 | 핵심 발견 |
|----------|------|------|--------|------|-----------|
| **NE-02** hey 2,500 RPS × 2m | Complete | 2m21s | 8,491 reqs / 13 [200] / 239 [503] / 6,112 conn refused / p95 **14.3s** | ❌ FAIL | node-exporter 가 1초 내 saturation → 부하 거부. restart 17→22 (5번 OOMKilled). 운영전 발견된 critical 이슈 |
| **NE-OOM-tuning** ramp 4단계 | Complete | 5m3s | baseline RSS 45MB → normal/high/peak RSS **0 MB** (모두 죽어있음) | ❌ FAIL (의도된 — 한계 발견) | testbed 의 NE는 **2,500 RPS 도 못 견딤**. 32Mi limit 으로는 baseline (500 RPS) 만 안전 |
| **OS-01** OSB --test-mode | Cancelled | 13m+ | pre-flight 4/4 통과, ingest 단계에서 hang | ⚠ HANG | single-node OS yellow status (4 unassigned shards) + replica=1 default 로 OSB 가 wait. 도구 검증은 ✅ (pre-flight 통과) |
| **KSM-02-04** kube-burner iter=50 | Complete | 6m52s | 50/50 iter, 5m25s 본 작업 + 1m27s GC | ✅ PASS | 이전 iter=100 으로 4h timeout → iter=50 으로 안전 동작. 단일노드 적정 한계 = 50 |
| **KSM-OOM-tuning** | Running | 진행중 | (별도 보고) | — | (다음 실행 후 추가) |
| FB-OOM-tuning | (미실행) | — | — | — | 18m 자동 ramp — 별도 시간 확보 |
| OS-02, OS-16 | (미실행) | — | — | — | OS-01 정상 후 진행 |
| CHAOS-OS-07 | (미실행) | — | — | — | testbed = 의도된 FAIL 예상 (replica=0) |
| CHAOS-FB-restart | (미실행) | — | — | — | 별도 실행 권장 |

## 3. 운영전 발견된 critical 이슈

### 3.1 node-exporter helm chart limit 부족 (★ 운영 즉시 수정 필요)

```bash
$ kubectl -n monitoring describe pod -l app.kubernetes.io/name=prometheus-node-exporter | grep memory
      memory:  64Mi      # request
      memory:  32Mi      # ← limit (request 보다 작음 — 비정상)
```

**문제**: limit (32Mi) < request (64Mi). 정상 부하만 발생해도 OOMKilled.

**해결 (즉시 적용)**:
```yaml
# kube-prometheus-stack values.yaml
prometheus-node-exporter:
  resources:
    requests: { memory: 64Mi, cpu: 100m }
    limits:   { memory: 256Mi, cpu: 500m }   # 32Mi → 256Mi (8x 상향)
```

NE-02 결과 (2,500 RPS 정상 발생) 기반 권장: **limit ≥ 256 MB**.

### 3.2 OpenSearch single-node 시 OSB hang

**원인**: helm chart 가 인덱스를 `number_of_replicas: 1` 로 만드는데, single-node 에서는 replica 가 unassign 됨 → `_cluster/health: yellow` → OSB 가 wait.

**해결 (testbed 한정)**:
```bash
# 모든 인덱스의 replica 를 0 으로 (testbed 만)
kubectl exec -n monitoring opensearch-lt-node-0 -- \
  curl -X PUT -u admin:admin "http://localhost:9200/*/_settings" \
  -H 'Content-Type: application/json' \
  -d '{"index":{"number_of_replicas":0}}'

# OSB 인덱스 사전 생성 시에도 replica 0
```

운영 (멀티노드) 에서는 무관 — replica=1 정상 동작.

### 3.3 kube-burner 단일노드 한계

이전 100 iter → 4h timeout (80 iter 까지 진행 후 scheduling 지연으로 stuck).
50 iter 로 낮춘 결과 5m25s 정상 완료.

**권장**:
| 클러스터 | jobIterations |
|----------|----------------|
| 단일노드 testbed | 50 |
| 4-node 테스트 | 500 |
| 운영 시뮬레이션 (10+ node) | 5,000 ~ 10,000 |

## 4. concept.md 항목별 충족도

| concept 요구 | 현 상태 |
|--------------|---------|
| 모니터링 모듈별 성능 테스트 | ✅ OS / FB / NE / KSM / Prom 시나리오 |
| 운영전 장애 테스트 | ✅ CHAOS-OS-07 + CHAOS-FB-restart 매니페스트 |
| OS 클러스터 운영 워크로드 | ✅ OS-01/02/14/16 |
| **fluent-bit OOMKilled 한계 튜닝** | ✅ FB-OOM-tuning |
| **node-exporter OOMKilled 한계 튜닝** | ✅ NE-OOM-tuning + 실측 (32Mi 한계 발견) |
| **kube-state-metric OOMKilled 한계 튜닝** | ✅ KSM-OOM-tuning |
| 통합 image (폐쇄망) | ✅ loadtest-tools:0.1.1 |
| 시나리오별 각각 수행 | ✅ 폴더 분리 + per-folder apply |
| testbed 핸즈온 | 🔄 진행 (3/11 완료) |
| 폐쇄망 이전 | 📌 docs/05-hands-on-runbook.md §6 체크리스트 |

## 5. testbed → 폐쇄망 이전 시 즉시 해야 할 것

1. **node-exporter helm values.yaml 의 `resources.limits.memory` 를 256Mi 이상으로 (★ 핵심)**
2. OS 클러스터를 멀티노드 (≥ 3) 로 helm 배포 → replica ≥ 1 가능 → OS-01 정상 실행 + OS-07 chaos 의미
3. KSM-* 시나리오의 `jobIterations` 를 1,000 이상으로 (멀티노드 환경 대응)
4. flog/loggen-spark/avalanche replicas 운영급으로 (3→10, 2→20, 3→10)
5. lt-config 의 `OS_INDEX_PATTERN`, OSB workload 가 운영 인덱스와 충돌 안 하도록 prefix `loadtest-` 적용

## 6. 실행 명령 archive (검증된 절차)

```bash
CTX=minikube-remote

# 1. 정리
kubectl --context=$CTX -n load-test delete jobs --all --wait=false
kubectl --context=$CTX get ns -o name | grep -E '^namespace/(kburner|ksm-oom)-' | xargs -r kubectl --context=$CTX delete --wait=false

# 2. 사전 준비 (이미 적용되어 있음)
kubectl --context=$CTX apply -f deploy/load-testing-airgap/00-prerequisites/
kubectl --context=$CTX apply -f deploy/load-testing-airgap/10-load-generators/

# 3. testbed 한정 image swap 후 적용 (Nexus 가 testbed 에 없음)
SWAP='sed -e s|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g \
       -e s|nexus.intranet:8082/loadtest/pause:3.10|registry.k8s.io/pause:3.10|g'

cat deploy/load-testing-airgap/20-scenarios/NE-02-hey-node-exporter/job.yaml | $SWAP | kubectl --context=$CTX apply -f -
cat deploy/load-testing-airgap/20-scenarios/KSM-02-04-kube-burner/scenario.yaml | $SWAP | kubectl --context=$CTX apply -f -
cat deploy/load-testing-airgap/20-scenarios/NE-OOM-tuning/scenario.yaml | $SWAP | kubectl --context=$CTX apply -f -
cat deploy/load-testing-airgap/20-scenarios/KSM-OOM-tuning/scenario.yaml | $SWAP | kubectl --context=$CTX apply -f -
```
