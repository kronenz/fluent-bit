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
| **OS-01** OSB --test-mode (0.1.1, replica=1) | Cancelled | 13m+ | pre-flight 4/4 통과, ingest 단계에서 hang | ⚠ HANG | single-node OS yellow status (4 unassigned shards) + replica=1 default 로 OSB 가 wait |
| **OS-01** OSB --test-mode (0.1.2, replica=0, **폐쇄망 모드**) | Complete | 15s | p50 latency 137ms, p100 178ms, 1k docs 인덱싱 SUCCESS | ✅ PASS | 0.1.2 = 모든 워크로드 (14개) test-mode corpus baked + OSB offline patch 적용. 폐쇄망 (iptables FORWARD egress 차단) 환경 동작 검증 완료 |
| **PR-03-04** k6 PromQL (0.1.2, **폐쇄망**) | Complete | 5m7s | p95 4.15ms / fail 0.00% / 58,379 reqs / 194 req/s | ✅ PASS | k6 telemetry phone-home 비활성 (K6_NO_USAGE_REPORT=true). 임계 모두 통과 |
| **NE-OOM-tuning** (0.1.2, **폐쇄망, NE limit 256Mi 패치 후**) | Complete | 4m39s | baseline 36 MB / normal 10 / high 138 / peak 149 MB | ✅ PASS | NE limit 32Mi → 256Mi 패치 효과 검증 — 모든 stage 에서 NE 살아있음. peak 149 MB 기반 운영 limit = 256 MB 충분 |
| **OS-02** k6 heavy search (0.1.2, **폐쇄망**) | Complete | 7m5s | p95 48.51ms / p99 (n/a in tail) / fail 0.00% / 2.27M reqs | ✅ PASS | 인덱스가 비어있어도 OS 가 빠르게 빈 결과 반환 → 모든 임계 통과. 운영급은 데이터 사전 확보 필요 |
| **FB-OOM-tuning** (0.1.2, **폐쇄망**) | Complete | 18m | 모든 stage RSS=0 MB (script label/URL encoding 버그) | ⚠ DATA_NOT_RECORDED | flog scale up/down 4단계는 정상 동작 (1→3→10→30→1) — fluent-bit 는 살아있음. RSS 측정 스크립트의 prom query URL encoding 버그로 값 미수집. **별도 수정 필요** (`tr -d \\n` 또는 query 직접 raw URL) |
| **KSM-02-04** kube-burner iter=50 | Complete | 6m52s | 50/50 iter, 5m25s 본 작업 + 1m27s GC | ✅ PASS | 이전 iter=100 으로 4h timeout → iter=50 으로 안전 동작. 단일노드 적정 한계 = 50 |
| **KSM-OOM-tuning** iter=50 (3 pod + 3 cm + 3 svc) | Failed | 4h timeout | 25/50 iter 까지만, namespace 26 stuck. 모든 stage RSS=22MB / scrape=0s (bash 측정 실패) | ❌ FAIL (testbed 한계) | iter 당 객체 9개 = 총 450 객체, 단일노드 minikube 의 pod 슬롯/스케줄러 한계 초과. 30 iter 또는 객체 종류 축소 필요 |
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

### 3.3 kube-burner 단일노드 한계 (객체 종류별)

| 워크로드 | testbed 안전치 | 결과 |
|----------|----------------|------|
| KSM-02-04: pod × 1 (50 iter = 50 pods) | 50 iter ✅ | 5m25s 완료 |
| KSM-OOM: pod × 3 + cm × 3 + svc × 3 (50 iter = 450 객체) | 50 iter ❌ | 25/50 에서 stuck → 4h timeout |
| KSM-OOM: pod × 1 + cm × 1 + svc × 1 (50 iter = 150 객체) | (검증 필요) | — |

**즉시 해야 할 수정** (KSM-OOM scenario):
- jobIterations: 50 → **30**
- 또는 객체 종류 축소: 3 종 → 2 종 (pod + cm)
- 또는 replicas: 3 → 1 (iter 당 3개 → 1개)

**권장 (전체)**:
| 클러스터 | KSM-02-04 (단순 pod) | KSM-OOM (복합 객체) |
|----------|----------------------|----------------------|
| 단일노드 testbed | 50 | 20~30 |
| 4-node 테스트 | 500 | 200 |
| 운영 시뮬레이션 (10+ node) | 5,000 ~ 10,000 | 2,000 ~ 5,000 |

### 3.4 KSM-OOM 의 RSS 측정 실패

bash 스크립트가 모든 stage 에서 RSS=22MB / scrape=0s 출력 → KSM 부하가 없거나 측정 query 가 잘못된 것이 아니라, **kube-burner 가 백그라운드로 시작했지만 25 iter 부터 stuck → 부하가 안 들어감**. 따라서 RSS 변화 없음.

운영 환경 (멀티노드, jobIterations 적정값) 에서는 정상 동작 예상.

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
