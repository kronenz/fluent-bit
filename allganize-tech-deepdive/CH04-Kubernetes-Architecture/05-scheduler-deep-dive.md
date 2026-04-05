# Scheduler Deep Dive

> **TL;DR**: kube-scheduler는 Filtering(조건 불충족 노드 제거)과 Scoring(점수 기반 순위 매기기) 2단계로 Pod를 최적 노드에 배치한다.
> nodeSelector, nodeAffinity, podAffinity/Anti-Affinity, Taints/Tolerations는 스케줄링을 제어하는 핵심 메커니즘이다.
> GPU 워크로드, 멀티 AZ 분산, 특정 노드 그룹 지정 등 실전 시나리오에서 적절한 조합이 필요하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### 스케줄링 알고리즘 전체 흐름

```
새 Pod 생성 (nodeName 비어있음)
        │
        ▼
┌──────────────────────────────────┐
│  1. Scheduling Queue             │
│     (Priority 기반 정렬)          │
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│  2. Filtering (Predicates)       │
│     조건을 만족하지 않는 노드 제거  │
│                                  │
│  ┌─ PodFitsResources            │
│  ├─ PodFitsHostPorts            │
│  ├─ NodeSelector 매칭            │
│  ├─ NodeAffinity 매칭            │
│  ├─ TaintToleration             │
│  ├─ PodTopologySpread           │
│  └─ VolumeZone (EBS AZ 매칭)    │
│                                  │
│  전체 N개 노드 → 필터 후 M개 노드  │
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│  3. Scoring (Priorities)         │
│     남은 노드에 0-100 점수 부여   │
│                                  │
│  ┌─ LeastRequestedPriority      │
│  ├─ BalancedResourceAllocation   │
│  ├─ NodeAffinityPriority        │
│  ├─ PodAffinityPriority         │
│  ├─ TaintTolerationPriority     │
│  └─ ImageLocalityPriority       │
│                                  │
│  점수 합산 → 최고 점수 노드 선택   │
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────────┐
│  4. Binding                      │
│     Pod.spec.nodeName 설정       │
│     → apiserver에 Binding 요청   │
└──────────────────────────────────┘
```

### nodeSelector (가장 단순한 노드 선택)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-pod
spec:
  nodeSelector:
    accelerator: nvidia-a100     # 정확히 일치하는 라벨의 노드에만 배치
    disk-type: ssd
  containers:
  - name: ml-training
    image: my-ml-image:latest
```

```bash
# 노드에 라벨 추가
kubectl label nodes node-1 accelerator=nvidia-a100
kubectl label nodes node-1 disk-type=ssd

# 노드 라벨 확인
kubectl get nodes --show-labels
kubectl get nodes -l accelerator=nvidia-a100
```

### Node Affinity (유연한 노드 선택)

nodeSelector의 확장판으로, **필수(required)** / **선호(preferred)** 구분과 연산자 지원.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: llm-serving
spec:
  affinity:
    nodeAffinity:
      # 필수: 이 조건을 만족하는 노드에만 배치 (Filtering)
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: node-role
            operator: In
            values: ["gpu", "ml"]
          - key: topology.kubernetes.io/zone
            operator: In
            values: ["ap-northeast-2a", "ap-northeast-2c"]
      # 선호: 가능하면 이 조건의 노드에 배치 (Scoring)
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 80               # 1-100, 높을수록 강한 선호
        preference:
          matchExpressions:
          - key: instance-type
            operator: In
            values: ["p3.2xlarge"]
      - weight: 20
        preference:
          matchExpressions:
          - key: instance-type
            operator: In
            values: ["g4dn.xlarge"]
  containers:
  - name: llm-server
    image: allganize/alli-llm:latest
```

**연산자(Operator):**

| Operator | 설명 | 예시 |
|---|---|---|
| In | 값 목록 중 하나와 일치 | `values: ["a", "b"]` |
| NotIn | 값 목록에 없어야 함 | `values: ["c"]` |
| Exists | 키가 존재하면 됨 (값 무관) | key만 지정 |
| DoesNotExist | 키가 없어야 함 | key만 지정 |
| Gt | 숫자 비교 (초과) | `values: ["3"]` |
| Lt | 숫자 비교 (미만) | `values: ["7"]` |

### Pod Affinity / Anti-Affinity

**다른 Pod와의 관계**를 기반으로 배치. topologyKey로 범위를 지정.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-web
spec:
  replicas: 3
  template:
    spec:
      affinity:
        # Pod Affinity: 캐시 서버와 같은 노드에 배치
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values: ["redis-cache"]
            topologyKey: kubernetes.io/hostname
        # Pod Anti-Affinity: 같은 앱의 다른 Pod와 다른 AZ에 분산
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values: ["alli-web"]
              topologyKey: topology.kubernetes.io/zone
      containers:
      - name: alli-web
        image: allganize/alli-web:latest
```

**topologyKey 이해:**
```
topologyKey: kubernetes.io/hostname
→ 같은 노드 / 다른 노드 기준

topologyKey: topology.kubernetes.io/zone
→ 같은 AZ / 다른 AZ 기준

topologyKey: topology.kubernetes.io/region
→ 같은 리전 / 다른 리전 기준
```

### Taints and Tolerations

**노드가 특정 Pod를 거부**하는 메커니즘 (노드 관점). Pod는 Toleration으로 Taint를 "용인"할 수 있다.

```
  Taint가 있는 노드
  ┌─────────────────┐
  │  Node (GPU)      │
  │                  │
  │  Taint:          │
  │  gpu=true:       │
  │  NoSchedule      │
  │                  │
  │  ┌────────┐     │   ← Toleration이 있는 Pod만 배치
  │  │GPU Pod │     │
  │  └────────┘     │
  │                  │
  │  ✗ 일반 Pod      │   ← Toleration 없으면 거부
  └─────────────────┘
```

**Taint Effect 종류:**

| Effect | 동작 |
|---|---|
| NoSchedule | 새 Pod 스케줄링 거부 (기존 Pod 유지) |
| PreferNoSchedule | 가능하면 스케줄링 안 함 (soft) |
| NoExecute | 새 Pod 거부 + 기존 Pod도 퇴출 |

```bash
# Taint 추가
kubectl taint nodes gpu-node-1 gpu=true:NoSchedule
kubectl taint nodes gpu-node-1 dedicated=ml:NoExecute

# Taint 제거 (끝에 - 붙임)
kubectl taint nodes gpu-node-1 gpu=true:NoSchedule-

# 노드의 Taint 확인
kubectl describe node gpu-node-1 | grep -A5 Taints
```

**Toleration 설정:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ml-training
spec:
  tolerations:
  # 정확한 매칭
  - key: "gpu"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"
  # 키만 매칭 (값 무관)
  - key: "dedicated"
    operator: "Exists"
    effect: "NoExecute"
    tolerationSeconds: 3600     # 1시간 후 퇴출 (NoExecute만 해당)
  # 모든 Taint 허용 (주의해서 사용)
  # - operator: "Exists"
  containers:
  - name: ml-training
    image: my-ml:latest
```

### Pod Topology Spread Constraints

Pod를 **토폴로지 도메인(AZ, 노드 등) 간 균등하게 분산**하는 기능. Anti-Affinity보다 세밀한 제어 가능.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api
spec:
  replicas: 6
  template:
    spec:
      topologySpreadConstraints:
      # AZ 간 최대 1개 차이로 분산
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule    # 조건 불충족 시 대기
        labelSelector:
          matchLabels:
            app: alli-api
      # 노드 간 최대 1개 차이로 분산
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway   # 조건 불충족 시 최선 노력
        labelSelector:
          matchLabels:
            app: alli-api
      containers:
      - name: alli-api
        image: allganize/alli-api:latest
```

**분산 결과 예시 (replicas=6, 3 AZ):**
```
AZ-a: Pod Pod     (2개)
AZ-b: Pod Pod     (2개)  → maxSkew=1 만족: |2-2| ≤ 1
AZ-c: Pod Pod     (2개)
```

---

## 실전 예시

### 스케줄링 실패 디버깅

```bash
# Pod가 Pending인 이유 확인
kubectl describe pod <pending-pod>
# → Events 섹션에서:
#   "0/10 nodes are available: 3 Insufficient cpu,
#    4 node(s) didn't match Pod's node affinity/selector,
#    3 node(s) had taint {gpu=true:NoSchedule}"

# 노드별 할당 가능 리소스 확인
kubectl describe nodes | grep -A5 "Allocated resources"

# 특정 노드의 상세 리소스 확인
kubectl describe node <node-name>
# → Capacity / Allocatable / Allocated 비교
```

### GPU 노드 전용 스케줄링 구성

```bash
# 1. GPU 노드에 Taint 추가 (일반 Pod 거부)
kubectl taint nodes gpu-node-{1,2,3} nvidia.com/gpu=present:NoSchedule

# 2. GPU 노드에 라벨 추가
kubectl label nodes gpu-node-{1,2,3} accelerator=nvidia-a100
```

```yaml
# 3. GPU Pod 설정
apiVersion: v1
kind: Pod
metadata:
  name: llm-inference
spec:
  nodeSelector:
    accelerator: nvidia-a100
  tolerations:
  - key: "nvidia.com/gpu"
    operator: "Equal"
    value: "present"
    effect: "NoSchedule"
  containers:
  - name: llm
    image: allganize/alli-llm:latest
    resources:
      limits:
        nvidia.com/gpu: 1          # GPU 1장 요청
```

### 스케줄러 프로파일링 (Scheduling Framework)

```yaml
# kube-scheduler 설정 (KubeSchedulerConfiguration)
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
- schedulerName: default-scheduler
  plugins:
    score:
      enabled:
      - name: NodeResourcesFit
        weight: 1
      - name: InterPodAffinity
        weight: 2
      - name: NodeAffinity
        weight: 2
      disabled:
      - name: ImageLocality      # 이미지 로컬리티 비활성화
  pluginConfig:
  - name: NodeResourcesFit
    args:
      scoringStrategy:
        type: MostAllocated       # 빈 패킹 전략 (노드 수 최소화)
        # type: LeastAllocated    # 부하 분산 전략 (기본값)
```

### 다중 스케줄러

```yaml
# 커스텀 스케줄러를 사용하는 Pod
apiVersion: v1
kind: Pod
metadata:
  name: custom-scheduled-pod
spec:
  schedulerName: my-custom-scheduler    # 기본값: default-scheduler
  containers:
  - name: app
    image: my-app:latest
```

---

## 면접 Q&A

### Q: Kubernetes 스케줄링의 Filtering과 Scoring 단계를 설명해주세요.
**30초 답변**:
Filtering은 리소스 부족, Taint, Affinity 위반 등 조건을 만족하지 않는 노드를 제거하는 단계이고, Scoring은 남은 노드에 리소스 균형, Affinity 선호도 등 기준으로 0-100 점수를 매겨 최고 점수 노드를 선택하는 단계입니다.

**2분 답변**:
스케줄링은 두 단계로 나뉩니다. Filtering(Predicates) 단계에서는 모든 노드를 대상으로 필수 조건을 검사합니다. PodFitsResources로 CPU/메모리 여유를 확인하고, NodeSelector와 NodeAffinity의 required 조건을 검사하며, TaintToleration으로 Taint가 있는 노드에 Toleration이 있는지 확인합니다. PodTopologySpread과 VolumeZone(PVC와 같은 AZ인지) 등도 이 단계에서 검사합니다. 이 단계에서 모든 노드가 필터링되면 Pod는 Pending 상태가 됩니다. Scoring(Priorities) 단계에서는 필터링을 통과한 노드에 0-100 점수를 부여합니다. LeastRequestedPriority는 리소스 여유가 많은 노드에 높은 점수를, BalancedResourceAllocation은 CPU/메모리 비율이 균형잡힌 노드에 높은 점수를 줍니다. NodeAffinityPriority와 PodAffinityPriority는 preferred 조건에 맞는 노드에 가중치를 부여합니다. 모든 점수를 합산하여 최고 점수 노드에 Pod를 바인딩합니다. Scheduling Framework를 통해 플러그인을 추가/제거하거나 가중치를 조정할 수 있습니다.

**경험 연결**:
노드 리소스에 여유가 있는데도 Pod가 Pending인 상황을 경험한 적 있습니다. `kubectl describe pod`에서 "didn't match Pod's node affinity"를 확인하고, 노드 라벨이 누락된 것을 발견했습니다. 이후 스케줄링 실패 시 `describe pod`의 Events를 먼저 확인하는 것을 표준 절차로 만들었습니다.

**주의**:
"IgnoredDuringExecution"의 의미를 오해하지 않도록. 이는 이미 실행 중인 Pod에는 Affinity 변경이 적용되지 않는다는 뜻이지, 스케줄링 시 무시한다는 뜻이 아니다.

### Q: Taints/Tolerations와 NodeAffinity의 차이와 사용 시나리오를 설명해주세요.
**30초 답변**:
Taints/Tolerations는 노드 관점에서 "특정 Pod만 받겠다"는 거부 메커니즘이고, NodeAffinity는 Pod 관점에서 "특정 노드에 가고 싶다"는 요청 메커니즘입니다. 보통 함께 사용하여 GPU 노드처럼 전용 노드를 구성합니다.

**2분 답변**:
Taints/Tolerations는 노드가 주도하는 메커니즘입니다. GPU 노드에 `gpu=true:NoSchedule` Taint를 추가하면, Toleration이 없는 일반 Pod는 해당 노드에 스케줄링되지 않습니다. 하지만 Toleration이 있다고 해서 반드시 해당 노드에 배치되는 것은 아닙니다. 즉, "이 노드에 올 수 있는 자격"을 주는 것입니다. NodeAffinity는 Pod가 주도하는 메커니즘입니다. "나는 gpu 라벨이 있는 노드에 가고 싶다"를 표현합니다. required는 필수 조건, preferred는 선호 조건입니다. 실전에서는 둘을 조합합니다: Taint로 일반 Pod를 거부하고, NodeAffinity로 GPU Pod가 해당 노드를 선택하도록 합니다. 또한 NoExecute 효과는 이미 실행 중인 Pod도 퇴출할 수 있어, 노드 유지보수 시 유용합니다. `kubectl drain`이 내부적으로 NoExecute Taint를 사용합니다. PodAffinity/Anti-Affinity는 Pod 간 관계를 정의하는 것으로, 같은 AZ에 두거나 다른 노드에 분산하는 데 사용합니다.

**경험 연결**:
GPU 노드에 Taint만 설정하고 NodeAffinity를 설정하지 않아, GPU Pod가 일반 노드에 배치된 경험이 있습니다. Taint는 "거부"만 하지 "유도"는 하지 않으므로, NodeSelector나 NodeAffinity를 반드시 함께 사용해야 합니다.

**주의**:
Toleration만으로는 해당 노드에 배치를 보장하지 않는다. Taint + Toleration은 "이 노드에 올 수 있는 자격"을 주고, NodeAffinity/nodeSelector가 "이 노드에 가겠다"를 지정하는 것이다. 둘을 함께 사용해야 전용 노드 구성이 완성된다.

### Q: Pod Topology Spread Constraints는 언제 사용하나요?
**30초 답변**:
Pod를 AZ나 노드 간에 균등하게 분산할 때 사용합니다. Anti-Affinity는 "같은 곳에 두지 마라"만 표현할 수 있지만, TopologySpread는 maxSkew로 "최대 N개 차이까지 허용"이라는 세밀한 균등 분산을 표현할 수 있습니다.

**2분 답변**:
PodAnti-Affinity는 "동일 도메인에 해당 Pod가 없어야 한다"는 이진적 조건인 반면, TopologySpread Constraints는 maxSkew를 통해 도메인 간 Pod 수의 최대 차이를 지정할 수 있습니다. 예를 들어 3개 AZ에 6개 replicas를 배포할 때, Anti-Affinity required를 쓰면 AZ당 1개만 배치되고 나머지 3개는 Pending이 됩니다. TopologySpread에서 maxSkew=1을 쓰면 2-2-2로 균등 분배됩니다. whenUnsatisfiable 옵션으로 DoNotSchedule(조건 불충족 시 대기)과 ScheduleAnyway(최선 노력)를 선택할 수 있습니다. 여러 topologyKey를 조합하면 AZ 간 분산과 노드 간 분산을 동시에 적용할 수 있습니다. 실제로 AWS EKS에서 Multi-AZ 배포 시 AZ 장애에 대비한 균등 분산이 중요하며, TopologySpread가 이 요구를 정확히 충족합니다. 클러스터 수준 기본 TopologySpread를 설정할 수도 있어, 모든 Deployment에 일관된 분산 정책을 적용할 수 있습니다.

**경험 연결**:
3개 AZ 환경에서 Deployment가 특정 AZ에 편중되어, 해당 AZ 장애 시 서비스 가용성이 크게 떨어진 경험이 있습니다. TopologySpread Constraints를 적용하여 AZ 간 균등 분산을 보장한 후, 단일 AZ 장애 시에도 2/3 용량이 유지되도록 개선했습니다.

**주의**:
TopologySpread에서 labelSelector가 Deployment 자체의 Pod를 정확히 선택하도록 해야 한다. 다른 Deployment의 Pod까지 포함하면 의도하지 않은 분산이 될 수 있다.

---

## Allganize 맥락

- **GPU 노드 스케줄링**: Allganize의 LLM 서빙에는 GPU 인스턴스가 필수이다. Taint + NodeAffinity 조합으로 GPU 노드를 전용화하고, NVIDIA Device Plugin이 `nvidia.com/gpu` extended resource를 관리한다. 인스턴스 타입별(A100 vs T4) 노드 그룹을 분리하고 NodeAffinity로 워크로드를 매칭하는 전략이 필요하다.
- **Multi-AZ 분산**: AWS EKS에서 서비스 가용성을 위해 TopologySpread Constraints로 AZ 간 균등 분산을 적용해야 한다. 특히 AI 추론 서비스는 latency-sensitive하므로, AZ 장애 시에도 충분한 용량이 남아야 한다.
- **Spot Instance 활용**: ML 학습 워크로드는 Spot Instance를 활용하여 비용을 절감할 수 있다. Spot 노드에 적절한 Taint를 설정하고, 학습 Pod에 Toleration을 부여하는 패턴이다.
- **Karpenter**: EKS 환경에서 Karpenter를 사용하면 스케줄링 실패 시 자동으로 적절한 인스턴스를 프로비저닝한다. NodePool과 EC2NodeClass로 인스턴스 타입, AZ, 용량 타입(On-Demand/Spot)을 제어한다.

---
**핵심 키워드**: `kube-scheduler` `Filtering` `Scoring` `nodeSelector` `nodeAffinity` `podAffinity` `podAntiAffinity` `Taints` `Tolerations` `TopologySpreadConstraints` `GPU-scheduling`
