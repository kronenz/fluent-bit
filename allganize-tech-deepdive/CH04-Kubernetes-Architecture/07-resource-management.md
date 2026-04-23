# Resource Management

> **TL;DR**: requests는 스케줄링 기준(보장량), limits는 최대 사용량이며, 이 설정에 따라 QoS 클래스(Guaranteed, Burstable, BestEffort)가 결정된다.
> LimitRange는 네임스페이스 내 개별 Pod/Container의 기본값과 범위를, ResourceQuota는 네임스페이스 전체의 총량을 제한한다.
> 적절한 리소스 설정은 안정성과 비용 효율의 핵심이며, OOM Kill과 CPU Throttling을 방지하는 열쇠이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Requests vs Limits

```
┌────────────────────────────────────────────────────┐
│              Node (Allocatable: 4 CPU, 8Gi)        │
│                                                    │
│  ┌──────────────────────┐                          │
│  │  Pod A               │                          │
│  │  requests:           │ ← 스케줄러가 확인         │
│  │    cpu: 500m         │   (이만큼의 공간이 있는    │
│  │    memory: 1Gi       │    노드에만 배치)          │
│  │  limits:             │ ← kubelet/커널이 강제     │
│  │    cpu: 1000m        │   (이 이상 사용 불가)      │
│  │    memory: 2Gi       │                          │
│  └──────────────────────┘                          │
│                                                    │
│  requests 합계 ≤ Allocatable  (스케줄링 조건)        │
│  실제 사용량 ≤ limits          (런타임 제한)          │
│  실제 사용량은 requests와 limits 사이에서 변동        │
└────────────────────────────────────────────────────┘
```

**CPU vs Memory 초과 동작:**

| 리소스 | 초과 시 동작 | 이유 |
|--------|------------|------|
| CPU | **Throttling** (느려짐) | CPU는 압축 가능(compressible) 리소스 |
| Memory | **OOM Kill** (프로세스 종료) | Memory는 압축 불가(incompressible) 리소스 |

**CPU 단위:**
```
1 CPU = 1000m (millicores)
500m = 0.5 CPU = 1 vCPU의 절반
100m = 0.1 CPU
```

**Memory 단위:**
```
1Gi = 1024Mi = 1,073,741,824 bytes (2진수)
1G  = 1000M  = 1,000,000,000 bytes (10진수)
→ 항상 Gi/Mi 사용 권장 (혼동 방지)
```

### QoS Classes (Quality of Service)

QoS 클래스는 **리소스 설정에 의해 자동으로 결정**되며, 노드 리소스 압박 시 **eviction 우선순위**를 결정한다.

```
┌─────────────────────────────────────────────────────────┐
│                    QoS Classes                           │
│                                                         │
│  ┌───────────────┐  가장 높은 보호. 마지막에 evict       │
│  │  Guaranteed   │  조건: 모든 컨테이너의                 │
│  │               │       requests == limits              │
│  │  (보장)       │       (CPU, Memory 모두 설정)          │
│  └───────────────┘                                      │
│                                                         │
│  ┌───────────────┐  중간 보호                            │
│  │  Burstable    │  조건: requests 또는 limits 중        │
│  │               │       하나 이상 설정, but              │
│  │  (변동)       │       Guaranteed 조건 불충족           │
│  └───────────────┘                                      │
│                                                         │
│  ┌───────────────┐  가장 먼저 evict                      │
│  │  BestEffort   │  조건: requests, limits               │
│  │               │       모두 미설정                      │
│  │  (최선 노력)   │                                      │
│  └───────────────┘                                      │
│                                                         │
│  Eviction 순서: BestEffort → Burstable → Guaranteed     │
└─────────────────────────────────────────────────────────┘
```

**각 QoS 클래스 예시:**

```yaml
# Guaranteed: requests == limits
containers:
- name: app
  resources:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "1"
      memory: "2Gi"

# Burstable: requests < limits 또는 일부만 설정
containers:
- name: app
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "2"
      memory: "4Gi"

# BestEffort: 아무것도 설정 안 함
containers:
- name: app
  image: my-app:latest
  # resources 섹션 없음
```

### OOM Kill 메커니즘

```
Memory 사용량이 limits를 초과
        │
        ▼
Linux OOM Killer 작동
        │
        ├─ oom_score_adj 기반 프로세스 선택
        │   Guaranteed: -997 (거의 죽지 않음)
        │   Burstable:  2~999 (사용량에 따라)
        │   BestEffort: 1000 (가장 먼저)
        │
        ▼
컨테이너 프로세스 SIGKILL
        │
        ▼
Pod의 restartPolicy에 따라 재시작
        │
        ▼
kubectl get pod → OOMKilled (Reason)
```

### CPU Throttling

```
CPU limits = 1000m (1 CPU)인 컨테이너가
실제로 1.5 CPU를 사용하려고 할 때:

CFS(Completely Fair Scheduler) 기반 조절:
- cfs_period_us = 100ms (기본)
- cfs_quota_us  = 100ms (limits=1000m일 때)

100ms 주기에서 100ms 사용 후 → 나머지 시간 대기 (throttled)

│████████████████████░░░░░░░│████████████████████░░░░░░░│
│  100ms 실행    대기        │  100ms 실행    대기        │
│◄──── 1 period (100ms) ───►│◄──── 1 period (100ms) ───►│

→ kubectl top pod에서 CPU가 limits에 가까우면 throttling 발생 가능
→ container_cpu_cfs_throttled_periods_total 메트릭으로 확인
```

### LimitRange

**네임스페이스 내 개별 Pod/Container에 대한 기본값과 범위를 설정.**

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
  # Container 레벨 제한
  - type: Container
    default:              # limits 기본값 (미설정 시 적용)
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:       # requests 기본값 (미설정 시 적용)
      cpu: "200m"
      memory: "256Mi"
    max:                  # 최대 limits
      cpu: "4"
      memory: "8Gi"
    min:                  # 최소 requests
      cpu: "50m"
      memory: "64Mi"
    maxLimitRequestRatio: # limits/requests 최대 비율
      cpu: "4"            # limits는 requests의 최대 4배
      memory: "4"

  # Pod 레벨 제한 (모든 컨테이너 합산)
  - type: Pod
    max:
      cpu: "8"
      memory: "16Gi"

  # PVC 크기 제한
  - type: PersistentVolumeClaim
    max:
      storage: "100Gi"
    min:
      storage: "1Gi"
```

**LimitRange 동작:**
```
Pod 생성 요청 (resources 미설정)
        │
        ▼
Admission Controller: LimitRanger
        │
        ├─ requests 미설정 → defaultRequest 적용
        ├─ limits 미설정  → default 적용
        ├─ requests < min → 거부
        ├─ limits > max   → 거부
        └─ limits/requests > maxLimitRequestRatio → 거부
        │
        ▼
Pod 생성 (기본값 적용됨)
```

### ResourceQuota

**네임스페이스 전체의 리소스 총량을 제한.**

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-ai-quota
  namespace: team-ai
spec:
  hard:
    # 컴퓨트 리소스
    requests.cpu: "20"
    requests.memory: "40Gi"
    limits.cpu: "40"
    limits.memory: "80Gi"
    requests.nvidia.com/gpu: "4"     # GPU 쿼타

    # 오브젝트 수
    pods: "50"
    services: "20"
    services.loadbalancers: "2"
    persistentvolumeclaims: "10"
    secrets: "50"
    configmaps: "50"

    # 스토리지
    requests.storage: "500Gi"

  # Scope로 특정 QoS 클래스만 제한 가능
  # scopeSelector:
  #   matchExpressions:
  #   - scopeName: PriorityClass
  #     operator: In
  #     values: ["high"]
```

**ResourceQuota 동작:**
```
Pod 생성 요청
    │
    ▼
Admission Controller: ResourceQuota
    │
    ├─ 현재 사용량 + 새 Pod 리소스 > hard limit?
    │   YES → 거부 ("exceeded quota")
    │   NO  → 허용
    │
    ▼
※ ResourceQuota가 설정된 NS에서는 모든 Pod에
   requests/limits가 반드시 있어야 함
   (LimitRange의 default로 자동 설정 가능)
```

### Vertical Pod Autoscaler (VPA)와 리소스 최적화

```
┌──────────────────────────────────────┐
│  VPA (Vertical Pod Autoscaler)       │
│                                      │
│  Recommender                         │
│  ├─ 실제 리소스 사용량 수집           │
│  ├─ 히스토그램 기반 분석              │
│  └─ 권장 requests/limits 계산        │
│                                      │
│  Updater                             │
│  └─ Pod를 재생성하여 권장값 적용      │
│                                      │
│  Admission Controller                │
│  └─ 새 Pod 생성 시 권장값 주입        │
└──────────────────────────────────────┘
```

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: alli-api-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: alli-api
  updatePolicy:
    updateMode: "Off"         # Off: 권장만 / Auto: 자동 적용
  resourcePolicy:
    containerPolicies:
    - containerName: alli-api
      minAllowed:
        cpu: "100m"
        memory: "128Mi"
      maxAllowed:
        cpu: "4"
        memory: "8Gi"
      controlledResources: ["cpu", "memory"]
```

---

## 실전 예시

### 리소스 사용량 확인

```bash
# Pod 리소스 사용량 (metrics-server 필요)
kubectl top pods -n production
kubectl top pods --sort-by=cpu
kubectl top pods --sort-by=memory

# 노드 리소스 사용량
kubectl top nodes

# 노드의 리소스 할당 상세
kubectl describe node <node-name>
# → Capacity:      cpu=4, memory=16Gi
# → Allocatable:   cpu=3500m, memory=14Gi  (systemReserved + kubeReserved 제외)
# → Allocated:     cpu=2800m, memory=10Gi   (requests 합산)
# → Available:     cpu=700m, memory=4Gi     (여유분)

# Pod의 QoS 클래스 확인
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'

# OOM Kill 이력 확인
kubectl get events --field-selector reason=OOMKilling -n production
kubectl describe pod <pod-name> | grep -A5 "Last State"
```

### LimitRange + ResourceQuota 실전 설정

```bash
# Namespace 생성 + LimitRange + ResourceQuota 한 번에 적용

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: team-ai
  labels:
    team: ai
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: team-ai
spec:
  limits:
  - type: Container
    default:
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:
      cpu: "200m"
      memory: "256Mi"
    max:
      cpu: "4"
      memory: "8Gi"
    min:
      cpu: "50m"
      memory: "64Mi"
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-ai-quota
  namespace: team-ai
spec:
  hard:
    requests.cpu: "20"
    requests.memory: "40Gi"
    limits.cpu: "40"
    limits.memory: "80Gi"
    pods: "50"
    persistentvolumeclaims: "10"
EOF

# 현재 쿼타 사용량 확인
kubectl describe resourcequota team-ai-quota -n team-ai
# → Used / Hard 비교
```

### CPU Throttling 진단

```bash
# 노드에서 cgroup 확인
# cgroup v2 기준
cat /sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<uid>.slice/cri-containerd-<id>.scope/cpu.max
# 출력: 100000 100000  → limits=1CPU (quota/period = 100ms/100ms)

# Prometheus 메트릭으로 throttling 확인
# container_cpu_cfs_throttled_seconds_total
# container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total
# → 비율이 25% 이상이면 limits 증가 고려
```

### 리소스 최적화 워크플로

```bash
# 1. 현재 requests/limits 확인
kubectl get pods -n production -o custom-columns=\
NAME:.metadata.name,\
CPU_REQ:.spec.containers[0].resources.requests.cpu,\
CPU_LIM:.spec.containers[0].resources.limits.cpu,\
MEM_REQ:.spec.containers[0].resources.requests.memory,\
MEM_LIM:.spec.containers[0].resources.limits.memory

# 2. VPA 권장값 확인 (VPA 설치 후)
kubectl get vpa -n production -o yaml

# 3. 실제 사용량 vs requests 비교 (Prometheus)
# avg(container_memory_working_set_bytes) / avg(kube_pod_container_resource_requests{resource="memory"})
# → 30% 미만이면 over-provisioned
# → 80% 이상이면 under-provisioned

# 4. Goldilocks (VPA 기반 대시보드)
# https://github.com/FairwindsOps/goldilocks
```

### GPU 리소스 관리

```yaml
# NVIDIA GPU 요청
apiVersion: v1
kind: Pod
metadata:
  name: llm-inference
spec:
  containers:
  - name: llm
    image: allganize/alli-llm:latest
    resources:
      limits:
        nvidia.com/gpu: 1          # GPU는 limits만 설정 (requests 자동 동일)
        # nvidia.com/gpu는 정수만 가능 (분할 불가)
      requests:
        cpu: "4"
        memory: "16Gi"
      limits:
        cpu: "8"
        memory: "32Gi"
        nvidia.com/gpu: 1

# GPU 공유 (MIG - Multi-Instance GPU, A100)
# nvidia.com/mig-1g.5gb: 1   ← A100을 7개 인스턴스로 분할
# nvidia.com/mig-2g.10gb: 1  ← 2개 SM + 10GB 메모리
```

---

## 면접 Q&A

### Q: requests와 limits의 차이를 설명해주세요.
**30초 답변**:
requests는 스케줄러가 노드 배치 시 확인하는 보장량이고, limits는 컨테이너가 사용할 수 있는 최대량입니다. CPU limits 초과 시 throttling, Memory limits 초과 시 OOM Kill이 발생합니다.

**2분 답변**:
requests와 limits는 Kubernetes 리소스 관리의 핵심입니다. requests는 스케줄러가 Pod를 노드에 배치할 때 사용하는 기준으로, 노드의 Allocatable 리소스에서 기존 Pod들의 requests 합을 빼고 남은 양이 새 Pod의 requests보다 커야 배치됩니다. 실제 사용량과는 무관하게 "예약"하는 개념입니다. limits는 컨테이너가 실제로 사용할 수 있는 상한선으로, Linux cgroup으로 강제됩니다. CPU와 Memory의 초과 동작이 다릅니다. CPU는 compressible resource라서 limits를 초과하면 CFS throttling이 발생하여 프로세스가 느려지지만 죽지 않습니다. Memory는 incompressible resource라서 limits를 초과하면 Linux OOM Killer가 컨테이너 프로세스를 SIGKILL로 종료합니다. 실무에서 requests는 평균 사용량의 p50~p80, limits는 p95~p99 피크를 기준으로 설정합니다. requests를 너무 높게 잡으면 노드 활용률이 떨어지고, limits를 너무 낮게 잡으면 throttling과 OOM이 자주 발생합니다.

**경험 연결**:
Memory requests를 실제 사용량보다 훨씬 높게 설정하여 노드 활용률이 30%에 그쳤던 경험이 있습니다. VPA의 권장값을 참고하여 requests를 적절히 낮추고, limits는 피크 사용량 기준으로 설정하여 활용률을 70%까지 끌어올렸습니다.

**주의**:
Memory limits를 설정하지 않으면 컨테이너가 노드 전체 메모리를 사용할 수 있어, 다른 Pod에 영향을 줄 수 있다. 프로덕션에서는 반드시 Memory limits를 설정해야 한다.

### Q: QoS 클래스의 종류와 각각의 의미를 설명해주세요.
**30초 답변**:
Guaranteed(requests=limits)는 가장 높은 보호를 받고, Burstable(requests!=limits)은 중간, BestEffort(미설정)는 가장 먼저 eviction됩니다. 노드 리소스 압박 시 BestEffort → Burstable → Guaranteed 순서로 Pod가 퇴출됩니다.

**2분 답변**:
QoS 클래스는 Pod의 리소스 설정에 의해 자동으로 결정되며, kubelet의 eviction 우선순위를 결정합니다. Guaranteed는 모든 컨테이너에서 CPU와 Memory의 requests와 limits가 동일하게 설정된 경우입니다. oom_score_adj가 -997로 설정되어 OOM Kill 대상에서 거의 제외됩니다. 노드 eviction 시에도 가장 마지막에 퇴출됩니다. 중요한 프로덕션 워크로드에 적합합니다. Burstable은 requests와 limits가 다르거나 일부만 설정된 경우입니다. 실제 사용량에 비례하여 oom_score_adj가 계산되어, 많이 사용하는 Pod부터 퇴출됩니다. 대부분의 일반 워크로드에 적합합니다. BestEffort는 requests와 limits를 전혀 설정하지 않은 경우입니다. oom_score_adj가 1000으로 가장 먼저 OOM Kill 대상이 됩니다. 개발/테스트 환경이나 비핵심 배치 작업에만 사용해야 합니다. 실무 전략으로는 핵심 서비스는 Guaranteed, 일반 서비스는 Burstable, 비핵심 작업은 BestEffort로 구분합니다.

**경험 연결**:
노드 메모리 압박으로 중요 서비스 Pod가 eviction된 경험이 있습니다. 해당 Pod가 Burstable이었고, 같은 노드의 덜 중요한 Pod도 Burstable이어서 사용량 기반으로 퇴출 대상이 결정되었습니다. 이후 핵심 서비스를 Guaranteed로 변경하여 문제를 방지했습니다.

**주의**:
Guaranteed라고 절대 eviction되지 않는 것은 아니다. 노드의 시스템 리소스(systemReserved)까지 부족하면 Guaranteed Pod도 퇴출될 수 있다. 또한 QoS는 개별 컨테이너가 아닌 Pod 전체의 설정으로 결정된다.

### Q: LimitRange와 ResourceQuota의 차이를 설명해주세요.
**30초 답변**:
LimitRange는 네임스페이스 내 개별 Pod/Container의 리소스 기본값과 허용 범위를 설정하고, ResourceQuota는 네임스페이스 전체의 리소스 총량과 오브젝트 수를 제한합니다. LimitRange는 Mutating Admission, ResourceQuota는 Validating Admission으로 동작합니다.

**2분 답변**:
LimitRange와 ResourceQuota는 보완적 관계입니다. LimitRange는 개별 리소스에 대한 규칙입니다. Container나 Pod 단위의 min/max를 설정하고, requests/limits를 지정하지 않은 컨테이너에 default 값을 자동 주입합니다. Mutating Admission Controller로 동작하므로 리소스를 수정할 수 있습니다. 예를 들어 "어떤 컨테이너든 CPU는 50m~4 사이여야 하고, 미설정 시 기본 200m"을 정할 수 있습니다. ResourceQuota는 네임스페이스 전체에 대한 총량 제한입니다. Validating Admission Controller로 동작하므로, 새 Pod 생성 시 현재 사용량 + 새 요청량이 quota를 초과하면 거부합니다. CPU/Memory 총량뿐 아니라 Pod 수, Service 수, PVC 수 등 오브젝트 카운트도 제한할 수 있습니다. 멀티 팀 환경에서는 두 가지를 함께 사용합니다: LimitRange로 개별 Pod가 과도한 리소스를 요청하지 못하게 하고, ResourceQuota로 팀 전체가 할당된 리소스 내에서 운영하도록 합니다. 특히 ResourceQuota가 설정된 Namespace에서는 모든 Pod에 requests가 필수이므로, LimitRange로 기본값을 설정하지 않으면 기존 매니페스트가 실패할 수 있습니다.

**경험 연결**:
멀티 팀 클러스터에서 한 팀이 리소스를 과점하여 다른 팀의 Pod가 Pending 상태가 된 경험이 있습니다. ResourceQuota로 팀별 총량을 제한하고, LimitRange로 개별 Pod의 최대 크기를 제한하여 공정한 리소스 분배를 구현했습니다.

**주의**:
ResourceQuota를 설정하면 해당 Namespace의 모든 Pod에 requests/limits가 필요하다. LimitRange를 함께 설정하여 기본값을 제공하지 않으면, 기존에 리소스 미설정이었던 Pod 생성이 실패하게 된다.

### Q: CPU Throttling은 왜 발생하고 어떻게 해결하나요?
**30초 답변**:
CPU limits를 설정하면 CFS(Completely Fair Scheduler)가 100ms 주기 내에서 할당된 quota만큼만 CPU를 사용하도록 제한합니다. 실제 사용량이 limits에 근접하면 throttling이 발생하여 응답이 느려집니다. limits를 높이거나 제거하여 해결합니다.

**2분 답변**:
CPU throttling은 Linux CFS bandwidth control 메커니즘으로 발생합니다. CPU limits를 1000m(1 CPU)으로 설정하면, cfs_quota_us=100000, cfs_period_us=100000으로 설정되어 100ms 주기에서 최대 100ms만 CPU를 사용할 수 있습니다. 짧은 burst에서도 100ms를 초과하면 나머지 시간 동안 CPU가 차단(throttled)됩니다. 특히 멀티 스레드 애플리케이션에서 심각한데, Go 런타임이 GOMAXPROCS를 CPU limits가 아닌 노드 전체 CPU로 설정하면 스레드가 동시에 실행되면서 quota를 빠르게 소진합니다. 해결 방법은: (1) CPU limits를 높이거나 제거합니다 (Google의 권장). (2) 애플리케이션의 스레드 수를 limits에 맞춥니다. (3) GOMAXPROCS를 uber-go/automaxprocs 라이브러리로 자동 설정합니다. (4) `container_cpu_cfs_throttled_periods_total` 메트릭을 모니터링합니다. 최근에는 CPU limits를 아예 설정하지 않고 requests만 설정하는 전략도 널리 사용됩니다. requests가 스케줄링과 CPU 시간 가중치를 보장하므로, limits 없이도 공정한 분배가 가능합니다.

**경험 연결**:
Java 애플리케이션에서 CPU limits를 2로 설정했는데, GC(Garbage Collection) 시 throttling이 심하게 발생하여 응답 지연이 발생했습니다. JVM의 -XX:ActiveProcessorCount를 limits에 맞추고, GC 스레드 수를 줄여 해결했습니다.

**주의**:
CPU limits를 제거하면 noisy neighbor 문제가 발생할 수 있다. requests로 보장은 되지만, burst 시 다른 Pod의 CPU를 빼앗을 수 있으므로, 노드 활용률 모니터링이 필수이다.

---

## Allganize 맥락

- **LLM 서빙 리소스 설계**: LLM 추론은 GPU뿐 아니라 CPU와 Memory도 많이 사용한다. 모델 크기에 따라 Memory requests를 정확히 설정해야 OOM을 방지한다. 예: 7B 모델은 약 14GB, 13B 모델은 약 26GB의 GPU 메모리가 필요하며, CPU 메모리도 모델 로딩 + 추론 버퍼를 고려해야 한다.
- **GPU 리소스 관리**: `nvidia.com/gpu`는 정수 단위로만 요청 가능하며, 하나의 GPU를 여러 Pod이 공유할 수 없다 (MIG 제외). GPU 활용률을 높이려면 MIG(A100) 또는 GPU time-slicing을 활용해야 한다.
- **팀별 ResourceQuota**: Allganize에서 여러 팀이 하나의 클러스터를 공유한다면, ResourceQuota로 GPU, CPU, Memory 할당량을 관리하여 공정성을 보장한다.
- **비용 최적화**: VPA로 over-provisioned 리소스를 식별하고 requests를 최적화하면 노드 활용률이 높아져 비용을 절감할 수 있다. Goldilocks 대시보드로 시각화하면 팀별 최적화 포인트를 쉽게 찾을 수 있다.
- **Spot Instance와 QoS**: ML 학습 워크로드를 Spot Instance에서 실행할 때, BestEffort나 Burstable로 설정하고 checkpoint 기반 복구를 구현하면 비용을 크게 절감할 수 있다.

---
**핵심 키워드**: `requests` `limits` `QoS-class` `Guaranteed` `Burstable` `BestEffort` `OOM-Kill` `CPU-Throttling` `LimitRange` `ResourceQuota` `VPA`
