# Kubernetes 성능 튜닝

> **TL;DR**: HPA/VPA로 Pod 리소스를 자동 조절하고, Cluster Autoscaler로 노드를 확장한다.
> PDB(Pod Disruption Budget)로 가용성을 보장하고, Priority Class로 중요 워크로드를 보호한다.
> AI 워크로드는 GPU 노드의 스케일링 시간이 길어 proactive 확장 전략이 필요하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 1. HPA (Horizontal Pod Autoscaler)

HPA는 메트릭 기반으로 Pod replica 수를 자동 조절한다.

```
                    ┌─────────────┐
                    │ Metrics API │
                    │ (metrics-   │
                    │  server /   │
                    │  custom)    │
                    └──────┬──────┘
                           │ 메트릭 수집
                    ┌──────▼──────┐
                    │     HPA     │
                    │ Controller  │
                    │             │
                    │ 목표: CPU   │
                    │   70% 유지  │
                    └──────┬──────┘
                           │ replicas 조정
                    ┌──────▼──────┐
                    │ Deployment  │
                    │ replicas: ? │
                    └──────┬──────┘
                     ┌─────┼─────┐
                    Pod   Pod   Pod
```

**스케일링 공식**:
```
desiredReplicas = ceil(currentReplicas × (currentMetric / desiredMetric))

예: 현재 3개 Pod, CPU 평균 90%, 목표 70%
   = ceil(3 × (90/70)) = ceil(3.86) = 4개
```

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: alli-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: alli-api
  minReplicas: 3
  maxReplicas: 50
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30    # 빠른 스케일업
      policies:
      - type: Percent
        value: 100                       # 한번에 2배까지
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300   # 느린 스케일다운 (5분)
      policies:
      - type: Percent
        value: 10                        # 한번에 10%만
        periodSeconds: 60
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  # Custom Metric 기반 스케일링 (AI 서비스용)
  - type: Pods
    pods:
      metric:
        name: inference_queue_depth
      target:
        type: AverageValue
        averageValue: "5"               # Pod당 큐 깊이 5 이하 유지
```

### 2. VPA (Vertical Pod Autoscaler)

VPA는 Pod의 CPU/Memory requests/limits를 자동 조정한다.

```
VPA 동작 모드

┌─────────────────────────────────────────────┐
│ Mode: "Off"       → 추천값만 제공            │
│ Mode: "Initial"   → Pod 생성 시에만 적용     │
│ Mode: "Auto"      → Pod 재시작하며 적용 ⚠️   │
│ Mode: "Recreate"  → Auto와 동일 (deprecated) │
└─────────────────────────────────────────────┘
```

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: alli-worker-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: alli-worker
  updatePolicy:
    updateMode: "Off"          # 추천값만 보고 수동 반영 (운영 안전)
  resourcePolicy:
    containerPolicies:
    - containerName: worker
      minAllowed:
        cpu: 500m
        memory: 512Mi
      maxAllowed:
        cpu: 4
        memory: 8Gi
      controlledResources: ["cpu", "memory"]
```

**HPA vs VPA 사용 가이드**:

| 기준 | HPA | VPA |
|------|-----|-----|
| 스케일 방향 | 수평 (Pod 수) | 수직 (Pod 리소스) |
| 적합 워크로드 | stateless API 서버 | 단일 인스턴스, 배치 작업 |
| 동시 사용 | CPU/Memory 기반 시 충돌 | Custom Metric HPA + VPA는 가능 |
| 중단 여부 | 무중단 (새 Pod 추가) | Pod 재시작 필요 (Auto 모드) |

> **중요**: HPA(CPU 기반)와 VPA를 같은 Deployment에 동시 사용하면 충돌한다. HPA는 custom metric, VPA는 resource로 분리해야 한다.

### 3. Cluster Autoscaler (CA)

```
Pod Pending ──→ CA가 감지 ──→ Cloud API로 노드 추가 요청
                                    │
                          ┌─────────▼─────────┐
                          │ 노드 프로비저닝     │
                          │ (2~5분 소요)       │
                          │ GPU 노드: 5~10분   │
                          └─────────┬─────────┘
                                    │
                          Node Ready ──→ Pod 스케줄링
```

```yaml
# Cluster Autoscaler 핵심 설정
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
spec:
  template:
    spec:
      containers:
      - name: cluster-autoscaler
        command:
        - ./cluster-autoscaler
        - --cloud-provider=aws
        - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled
        - --balance-similar-node-groups     # AZ 간 균형
        - --skip-nodes-with-local-storage=false
        - --expander=least-waste            # 낭비 최소화 전략
        - --scale-down-delay-after-add=10m  # 노드 추가 후 10분간 축소 금지
        - --scale-down-unneeded-time=10m    # 10분간 유휴 시 축소
        - --max-node-provision-time=15m     # GPU 노드는 넉넉히
```

**Expander 전략**:

| 전략 | 설명 | 적합 상황 |
|------|------|---------|
| `random` | 무작위 선택 | 노드 그룹이 동일할 때 |
| `least-waste` | 리소스 낭비 최소화 | 비용 최적화 |
| `most-pods` | 가장 많은 Pod 수용 | 빠른 스케줄링 |
| `priority` | 우선순위 기반 | GPU vs CPU 노드 분리 시 |

### 4. Karpenter (차세대 노드 오토스케일링)

```yaml
# Karpenter NodePool (CA 대체, AWS 환경)
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: gpu-inference
spec:
  template:
    spec:
      requirements:
      - key: node.kubernetes.io/instance-type
        operator: In
        values: ["g5.xlarge", "g5.2xlarge", "p4d.24xlarge"]
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["on-demand", "spot"]       # Spot 인스턴스 혼합
      - key: topology.kubernetes.io/zone
        operator: In
        values: ["ap-northeast-2a", "ap-northeast-2c"]
  limits:
    cpu: "1000"
    memory: 4000Gi
    nvidia.com/gpu: "32"                    # GPU 상한
  disruption:
    consolidationPolicy: WhenUnderutilized
    expireAfter: 720h                        # 30일 후 교체
```

### 5. Pod Disruption Budget (PDB)

```yaml
# 최소 가용 Pod 보장
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: alli-api-pdb
spec:
  minAvailable: "70%"          # 항상 70% 이상 유지
  # 또는 maxUnavailable: 1     # 한번에 1개만 중단 가능
  selector:
    matchLabels:
      app: alli-api
```

```
PDB 동작 시나리오 (5 Pod, minAvailable: 3)

정상 상태:    [Pod1] [Pod2] [Pod3] [Pod4] [Pod5]  ← 5/5 Running
노드 drain:   [Pod1] [Pod2] [Pod3] [----] [Pod5]  ← 4/5 OK (≥3)
추가 drain:   [Pod1] [Pod2] [Pod3] [----] [----]  ← 3/5 OK (=3)
drain 차단:   [Pod1] [Pod2] [Pod3]  ← PDB가 추가 eviction 차단!
```

**PDB가 중요한 상황**:
- 노드 업그레이드 (kubectl drain)
- Cluster Autoscaler 노드 축소
- Spot 인스턴스 회수
- Karpenter 노드 통합(consolidation)

### 6. Priority Class

```yaml
# System Critical (최고 우선순위)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: system-critical
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "코어 시스템 컴포넌트용"

---
# AI Inference (높은 우선순위)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: ai-inference
value: 100000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "LLM 추론 서비스용"

---
# Batch Processing (낮은 우선순위)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-low
value: 1000
globalDefault: false
preemptionPolicy: Never              # 다른 Pod를 선점하지 않음
description: "배치 작업, 학습 파이프라인"

---
# Deployment에서 사용
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-inference
spec:
  template:
    spec:
      priorityClassName: ai-inference   # GPU 리소스 부족 시 batch를 선점
      containers:
      - name: inference
        resources:
          requests:
            nvidia.com/gpu: 1
```

```
Preemption 시나리오

GPU Node (4 GPU):
Before: [batch-1] [batch-2] [batch-3] [batch-4]  ← 모두 batch-low

inference Pod 스케줄 요청 (ai-inference priority)
  → batch-4가 preempt됨

After:  [batch-1] [batch-2] [batch-3] [INFERENCE]  ← inference가 선점
```

---

## 실전 예시

### 종합 오토스케일링 설계 (Alli 서비스 예시)

```
                    ┌─────────────────────────┐
                    │   Alli API Gateway      │
                    │   HPA: custom metric    │
                    │   (request_rate)        │
                    │   min:3 / max:50        │
                    └───────────┬─────────────┘
                          ┌─────┴─────┐
                    ┌─────▼────┐ ┌────▼─────┐
                    │ RAG Svc  │ │ LLM Svc  │
                    │ HPA:CPU  │ │ HPA:GPU  │
                    │ min:2    │ │ queue_dep │
                    │ max:20   │ │ min:2    │
                    └──────────┘ │ max:16   │
                                 └──────────┘
                                      │
                              GPU Node Pool
                              Karpenter/CA
                              PDB: minAvail 70%
                              Priority: ai-inference
```

### Resource Quota + LimitRange 조합

```yaml
# Namespace 전체 리소스 제한
apiVersion: v1
kind: ResourceQuota
metadata:
  name: alli-prod-quota
  namespace: alli-prod
spec:
  hard:
    requests.cpu: "100"
    requests.memory: 200Gi
    limits.cpu: "200"
    limits.memory: 400Gi
    requests.nvidia.com/gpu: "16"
    pods: "200"

---
# Pod 기본값 강제
apiVersion: v1
kind: LimitRange
metadata:
  name: alli-prod-limits
  namespace: alli-prod
spec:
  limits:
  - type: Container
    default:
      cpu: "1"
      memory: 1Gi
    defaultRequest:
      cpu: 250m
      memory: 256Mi
    max:
      cpu: "8"
      memory: 16Gi
      nvidia.com/gpu: "4"
```

---

## 면접 Q&A

### Q1: HPA와 VPA를 동시에 사용할 수 있나요? 어떤 상황에서 각각을 선택합니까?

**30초 답변**:
CPU/Memory 기반 HPA와 VPA를 동시에 사용하면 충돌합니다. HPA가 CPU 사용률로 Pod 수를 늘리는데, VPA가 CPU request를 변경하면 HPA 계산이 깨집니다. 동시 사용하려면 HPA는 custom metric(QPS, queue depth), VPA는 resource request 관리로 역할을 분리해야 합니다.

**2분 답변**:
사용 시나리오별 가이드:
- **Stateless API 서버**: HPA(CPU 또는 custom metric) 단독. 수평 확장이 자연스럽고 무중단.
- **Stateful/Single 인스턴스**: VPA가 적합. DB, 캐시 등 replica 추가가 어려운 워크로드.
- **AI Inference 서버**: HPA(inference queue depth) + VPA(Off 모드로 추천값만 참고). 모델 로딩 시간이 길어 Pod 재시작 최소화 필요.
- **Batch Worker**: VPA(Auto)가 효과적. 작업 특성에 따라 리소스 요구량이 변동.

실무 팁:
1. VPA는 우선 "Off" 모드로 배포하여 추천값을 관찰
2. 추천값이 안정되면 request/limit을 수동 반영
3. HPA의 behavior 설정으로 scaleDown을 보수적으로 (stabilizationWindow 활용)
4. KEDA(Kubernetes Event-Driven Autoscaling)를 사용하면 0→N 스케일링도 가능

**💡 경험 연결**:
"서버 리소스 산정 시 초기에는 보수적으로 잡고 모니터링 후 조정하는 패턴을 써왔습니다. VPA의 Off 모드가 이 접근과 동일한 철학이어서, 먼저 추천값을 관찰하고 반영하는 프로세스를 선호합니다."

**⚠️ 주의**: HPA minReplicas를 1로 설정하면 스케일다운 시 단일 장애점이 된다. 프로덕션에서는 최소 2~3을 권장.

---

### Q2: Cluster Autoscaler와 Karpenter의 차이점은 무엇입니까?

**30초 답변**:
CA는 ASG(Auto Scaling Group) 단위로 노드를 추가/제거하며 미리 정의된 노드 그룹에서만 선택합니다. Karpenter는 Pod 요구사항을 보고 최적의 인스턴스 타입을 직접 선택하여 프로비저닝하므로 더 빠르고 비용 효율적입니다. Karpenter는 AWS 전용이지만, 노드 통합(consolidation) 기능으로 비용 최적화가 뛰어납니다.

**2분 답변**:

| 특성 | Cluster Autoscaler | Karpenter |
|------|-------------------|-----------|
| 노드 그룹 | ASG 기반, 사전 정의 필수 | NodePool로 유연하게 정의 |
| 인스턴스 선택 | ASG 내 고정 타입 | Pod spec 기반 최적 타입 자동 선택 |
| 프로비저닝 속도 | ASG → EC2 (느림) | 직접 EC2 API 호출 (빠름) |
| 노드 통합 | 지원 안함 | Consolidation 자동 (빈 노드 통합) |
| 클라우드 | AWS, GCP, Azure 등 | AWS 전용 (Azure 베타) |
| Spot 관리 | ASG 혼합 정책 | 네이티브 Spot 지원 + 자동 대체 |

Allganize 환경 추천:
- AWS EKS → Karpenter 우선 고려 (비용 30~40% 절감 사례)
- Azure AKS → CA 사용 (Karpenter 미지원)
- GPU 노드 → 별도 NodePool로 분리, on-demand 위주

**💡 경험 연결**:
"온프레미스 환경에서는 물리 서버 추가에 수주가 걸렸지만, 클라우드에서는 분 단위로 노드가 추가됩니다. 다만 GPU 노드는 가용성이 제한적이어서 예약 인스턴스를 사전 확보하는 전략이 필요하다는 점을 AI 데이터센터 프로젝트에서 체감했습니다."

**⚠️ 주의**: Karpenter를 설명할 때 AWS 전용이라는 점을 반드시 언급. Allganize가 Azure도 사용하므로 멀티클라우드 전략을 함께 말해야 한다.

---

### Q3: PDB를 설정하지 않으면 어떤 문제가 발생할 수 있나요?

**30초 답변**:
노드 업그레이드나 Spot 회수 시 여러 Pod가 동시에 종료되어 서비스 중단이 발생합니다. 예를 들어 3개 Pod가 2개 노드에 있을 때, 한 노드가 drain되면 2개가 동시 종료되어 가용 Pod가 1개로 급감합니다. PDB가 있으면 minAvailable을 보장하여 순차적으로만 eviction을 허용합니다.

**2분 답변**:
PDB 미설정 시 위험 시나리오:
1. **Rolling Update 중 노드 drain**: Deployment의 maxUnavailable과 별개로, drain은 해당 노드의 모든 Pod를 제거. PDB 없으면 서비스 Pod 대부분이 한 노드에 있을 때 전부 중단.
2. **Cluster Autoscaler 축소**: CA가 underutilized 노드를 제거할 때, PDB 없으면 해당 노드의 Pod를 모두 한번에 evict.
3. **Spot 인스턴스 회수**: 2분 경고 후 강제 종료. PDB가 있으면 다른 노드의 Pod는 보호됨.

설정 시 주의사항:
- `minAvailable`을 너무 높게 잡으면 drain이 영원히 진행 안 됨 (deadlock)
- 단일 Pod Deployment에 `minAvailable: 1`을 설정하면 노드 drain 불가
- PDB는 자발적 중단(voluntary disruption)만 제어, 노드 장애(involuntary)는 제어 불가

**💡 경험 연결**:
"서버 유지보수 시 한 대씩 순차적으로 작업하는 것이 운영의 기본입니다. PDB는 이 원칙을 K8s에서 자동화한 것으로, 인프라 운영 경험에서 자연스럽게 이해되는 개념입니다."

**⚠️ 주의**: PDB는 voluntary disruption만 제어한다는 점을 명확히. 노드 장애(involuntary)는 PDB로 막을 수 없다.

---

## Allganize 맥락

- **Alli API 서비스**: HPA + custom metric(inference queue depth)으로 LLM 추론 부하에 따라 자동 확장
- **GPU 노드 관리**: GPU 노드는 프로비저닝이 느려 Karpenter의 proactive 확장 또는 buffer 노드 전략 필요
- **AWS EKS + Azure AKS**: AWS는 Karpenter, Azure는 CA로 이원화 전략
- **PDB 필수**: Alli 서비스는 고가용성이 필요하므로 모든 프로덕션 Deployment에 PDB 설정
- **Priority Class**: LLM inference > RAG retrieval > batch processing 순으로 우선순위 설정
- **비용 관리**: 오토스케일링과 비용의 균형을 위해 scaleDown을 보수적으로 설정

---

**핵심 키워드**: `HPA` `VPA` `Cluster-Autoscaler` `Karpenter` `PDB` `PriorityClass` `custom-metrics` `KEDA` `scaleDown-stabilization` `preemption`
