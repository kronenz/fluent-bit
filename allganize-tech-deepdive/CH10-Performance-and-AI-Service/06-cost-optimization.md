# 클라우드 비용 최적화

> **TL;DR**: Reserved/Spot/On-demand를 워크로드 특성에 맞게 조합하여 40~70% 비용을 절감한다.
> Kubecost로 K8s 비용을 네임스페이스/워크로드 단위로 분석하고, FinOps 프레임워크로 조직적 비용 관리를 수행한다.
> GPU 워크로드는 비용이 10~100배이므로 활용률 최적화가 가장 큰 절감 레버이다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 20min

---

## 핵심 개념

### 1. 클라우드 비용 분석 프레임워크

```
비용 최적화 4단계 프레임워크

┌──────────────────────────────────────────────────┐
│  1. 가시성 (Visibility)                           │
│     "어디서 얼마를 쓰고 있는가?"                    │
│     → 태그 정책, 비용 할당, 대시보드               │
├──────────────────────────────────────────────────┤
│  2. 최적화 (Optimization)                         │
│     "같은 일을 더 싸게 할 수 있는가?"               │
│     → 인스턴스 right-sizing, Spot, Reserved       │
├──────────────────────────────────────────────────┤
│  3. 거버넌스 (Governance)                         │
│     "예산 초과를 어떻게 방지하는가?"                │
│     → 예산 알림, 승인 프로세스, 정책               │
├──────────────────────────────────────────────────┤
│  4. 자동화 (Automation)                           │
│     "비용 최적화를 자동으로 수행할 수 있는가?"       │
│     → Autoscaling, Scheduled scaling, Cleanup    │
└──────────────────────────────────────────────────┘
```

### 2. Reserved / Spot / On-demand 전략

```
가격 비교 (us-east-1, p4d.24xlarge 기준 - A100 8장)

On-demand:  $32.77/hr   ████████████████████  (100%)
1yr RI:     $21.30/hr   █████████████         (65%)  ← 35% 절감
3yr RI:     $13.11/hr   ████████              (40%)  ← 60% 절감
Spot:       $9.83/hr    ██████                (30%)  ← 70% 절감 ⚠️ 회수 위험

Savings Plan (1yr):
  Compute SP: ~30% 절감 (모든 인스턴스 유연)
  EC2 SP:     ~35% 절감 (인스턴스 패밀리 고정)
```

**워크로드별 인스턴스 전략**:

```
┌─────────────────────────────────────────────────────┐
│           워크로드 유형별 인스턴스 전략                 │
│                                                      │
│  ┌──────────────────┐                                │
│  │ Production       │  Reserved Instance / Savings Plan│
│  │ LLM Inference    │  ← 항상 가동, 예측 가능          │
│  │ (Alli API)       │  ← 안정성 최우선                 │
│  └──────────────────┘                                │
│                                                      │
│  ┌──────────────────┐                                │
│  │ Baseline +       │  RI(기본) + On-demand(버스트)    │
│  │ Burst Traffic    │  ← HPA와 연계                   │
│  │ (API Workers)    │  ← 피크 시간만 On-demand         │
│  └──────────────────┘                                │
│                                                      │
│  ┌──────────────────┐                                │
│  │ Batch / Training │  Spot Instance                  │
│  │ (Model Training, │  ← 중단 허용, 체크포인트 활용    │
│  │  Data Pipeline)  │  ← 70% 절감 가능                │
│  └──────────────────┘                                │
│                                                      │
│  ┌──────────────────┐                                │
│  │ Dev / Staging    │  Spot + Scheduled Shutdown      │
│  │                  │  ← 업무 시간 외 중지             │
│  │                  │  ← 80~90% 절감 가능             │
│  └──────────────────┘                                │
└─────────────────────────────────────────────────────┘
```

### 3. Spot 인스턴스 운영 전략

```
Spot 인스턴스 아키텍처 (K8s)

┌──────────────────────────────────────────────┐
│  EKS Cluster                                  │
│                                               │
│  ┌────────────────────┐                      │
│  │ On-demand Node Pool │ ← 시스템 + 핵심 서비스│
│  │ (system, inference) │                      │
│  └────────────────────┘                      │
│                                               │
│  ┌────────────────────┐                      │
│  │ Spot Node Pool      │ ← 배치, 비핵심 워크로드│
│  │ (batch, dev, test)  │                      │
│  │                     │                      │
│  │ 회수 대응:           │                      │
│  │ ├─ 2분 경고 감지     │                      │
│  │ ├─ Pod graceful     │                      │
│  │ │  shutdown         │                      │
│  │ ├─ 다른 Spot 노드로  │                      │
│  │ │  재스케줄링        │                      │
│  │ └─ On-demand        │                      │
│  │    fallback         │                      │
│  └────────────────────┘                      │
└──────────────────────────────────────────────┘
```

```yaml
# Karpenter Spot + On-demand 혼합 전략
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: batch-workers
spec:
  template:
    spec:
      requirements:
      - key: karpenter.sh/capacity-type
        operator: In
        values: ["spot", "on-demand"]        # Spot 우선, fallback으로 On-demand
      - key: node.kubernetes.io/instance-type
        operator: In
        values:                               # 다양한 타입으로 Spot 가용성 확보
        - m5.2xlarge
        - m5a.2xlarge
        - m6i.2xlarge
        - m6a.2xlarge
        - c5.2xlarge
        - c6i.2xlarge
  limits:
    cpu: "200"
  disruption:
    consolidationPolicy: WhenUnderutilized
    expireAfter: 720h

---
# AWS Node Termination Handler (Spot 회수 대응)
# kube-system에 DaemonSet으로 배포
# Spot 회수 2분 전 경고 감지 → cordon + drain → Pod 재스케줄링
```

### 4. Kubecost

```
Kubecost 아키텍처

┌─────────────────────────────────────────────────┐
│                   Kubecost                       │
│                                                   │
│  ┌─────────────┐   ┌──────────────────────────┐  │
│  │ Cost Model  │   │   Kubecost Frontend      │  │
│  │             │   │   (Dashboard)             │  │
│  │ K8s 리소스  │   │                           │  │
│  │ × 클라우드  │   │   네임스페이스별 비용      │  │
│  │   단가      │   │   워크로드별 비용          │  │
│  │ = 실제 비용 │   │   비용 추이 그래프         │  │
│  └──────┬──────┘   │   효율성 리포트           │  │
│         │          └──────────────────────────┘  │
│  ┌──────▼──────┐                                 │
│  │ Data Source │                                 │
│  │             │                                 │
│  │ Prometheus  │  ← node_exporter, kube-state    │
│  │ Cloud Bill  │  ← AWS CUR, Azure Cost Mgmt    │
│  │ K8s API     │  ← Pod, Node, PV 정보           │
│  └─────────────┘                                 │
└─────────────────────────────────────────────────┘
```

```bash
# Kubecost 설치
helm repo add kubecost https://kubecost.github.io/cost-analyzer/
helm install kubecost kubecost/cost-analyzer \
  --namespace kubecost \
  --create-namespace \
  --set kubecostToken="<token>" \
  --set prometheus.server.global.scrape_interval=60s
```

**Kubecost 핵심 기능**:

| 기능 | 설명 |
|------|------|
| Namespace Cost | 네임스페이스별 일/월 비용 |
| Workload Cost | Deployment/StatefulSet별 비용 |
| Efficiency | CPU/Memory request vs 실사용 비교 |
| Savings | Right-sizing 추천, 유휴 리소스 알림 |
| Alerts | 예산 초과 알림, 비용 급증 알림 |
| Allocation | 팀/프로젝트별 비용 할당 (showback/chargeback) |

```yaml
# Kubecost 비용 알림 설정
apiVersion: v1
kind: ConfigMap
metadata:
  name: kubecost-alerts
data:
  alerts.json: |
    {
      "alerts": [
        {
          "type": "budget",
          "threshold": 10000,
          "window": "monthly",
          "aggregation": "namespace",
          "filter": "alli-prod",
          "slackWebhookUrl": "https://hooks.slack.com/..."
        },
        {
          "type": "efficiency",
          "threshold": 0.3,
          "window": "48h",
          "aggregation": "deployment",
          "slackWebhookUrl": "https://hooks.slack.com/..."
        }
      ]
    }
```

### 5. GPU 비용 최적화

```
GPU 비용 최적화 전략

┌──────────────────────────────────────────────────┐
│  1. GPU 활용률 최적화                              │
│     ├── dcgm-exporter로 GPU util 모니터링         │
│     ├── GPU util < 30%인 Pod → 리소스 재조정       │
│     ├── MIG/Time-Slicing으로 GPU 공유             │
│     └── Batch 요청 모아서 처리 (높은 batch size)   │
├──────────────────────────────────────────────────┤
│  2. 인스턴스 전략                                  │
│     ├── Production inference → RI/SP (1yr+)       │
│     ├── Training/Fine-tuning → Spot (체크포인트)  │
│     ├── Dev/Test → Spot + 자동 종료               │
│     └── 멀티 리전 Spot 풀 (가용성 확보)            │
├──────────────────────────────────────────────────┤
│  3. 모델 최적화                                    │
│     ├── 양자화 (FP16 → INT8 → INT4)              │
│     │   메모리 50~75% 절감, 적은 GPU 필요          │
│     ├── 모델 증류 (Distillation)                  │
│     │   소형 모델로 대체                           │
│     └── TensorRT 최적화                           │
│         추론 속도 2~4x 향상                        │
├──────────────────────────────────────────────────┤
│  4. 스케줄링 최적화                                │
│     ├── 업무 시간 외 스케일다운                     │
│     ├── 배치 작업은 야간/주말에 실행               │
│     └── GPU 노드 자동 종료 (CronJob)              │
└──────────────────────────────────────────────────┘
```

### 6. FinOps 프레임워크

```
FinOps 라이프사이클

            ┌────────────┐
    ┌──────▶│  Inform    │──────┐
    │       │ (가시성)    │      │
    │       │            │      ▼
    │       └────────────┘  ┌────────────┐
    │                       │  Optimize  │
    │                       │  (최적화)   │
    │                       │            │
    │       ┌────────────┐  └─────┬──────┘
    │       │  Operate   │◀───────┘
    └───────│  (운영)    │
            │            │
            └────────────┘

Inform:   태그 정책, 비용 대시보드, 팀별 할당
Optimize: Right-sizing, RI/SP 구매, Spot 활용
Operate:  예산 관리, 정책 자동화, 문화 구축
```

**FinOps 핵심 원칙**:

| 원칙 | 설명 | 실행 방법 |
|------|------|---------|
| Teams need to collaborate | 엔지니어+재무+경영 협업 | 월간 비용 리뷰 미팅 |
| Everyone takes ownership | 각 팀이 비용 책임 | 네임스페이스별 비용 할당 |
| FinOps data should be accessible | 비용 데이터 투명 공개 | Kubecost 대시보드 공유 |
| A centralized team drives FinOps | 전담 팀/담당자 필요 | FinOps 엔지니어 역할 |
| Take advantage of variable cost | 가변 비용 모델 활용 | Spot, Autoscaling |
| Reports should be timely | 실시간에 가까운 리포팅 | 일간 비용 알림 |

### 7. AWS/Azure 비용 도구

```
AWS 비용 관리 도구
├── AWS Cost Explorer         → 비용 분석/시각화
├── AWS Budgets               → 예산 설정/알림
├── AWS Cost & Usage Report   → 상세 사용량 데이터 (S3)
├── Savings Plans             → 유연한 약정 할인
├── Reserved Instances        → 인스턴스별 약정 할인
├── Spot Instances            → 여유 용량 할인
└── Compute Optimizer         → Right-sizing 추천

Azure 비용 관리 도구
├── Azure Cost Management     → 비용 분석/예산
├── Azure Advisor             → 최적화 권장사항
├── Azure Reservations        → 약정 할인
├── Azure Spot VMs            → 여유 용량 할인
└── Azure Hybrid Benefit      → 기존 라이선스 활용
```

---

## 실전 예시

### 월간 비용 분석 대시보드 구성

```
Kubecost + Grafana 통합 대시보드

┌─────────────────────────────────────────────────┐
│  Monthly Cost Overview                           │
│                                                   │
│  Total: $45,230  |  Budget: $50,000  |  91%      │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Namespace Breakdown                          │ │
│  │ alli-prod:     $28,500 (63%) ██████████████ │ │
│  │ alli-staging:  $5,200  (11%) ████           │ │
│  │ ml-training:   $6,800  (15%) █████          │ │
│  │ monitoring:    $2,100  (5%)  ██             │ │
│  │ others:        $2,630  (6%)  ██             │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Top Cost Drivers                             │ │
│  │ 1. GPU instances (p4d.24xlarge): $22,400    │ │
│  │ 2. EBS volumes (gp3):           $3,200     │ │
│  │ 3. Data transfer:               $2,100     │ │
│  │ 4. ELB:                         $1,800     │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Savings Recommendations                      │ │
│  │ ✓ 3 pods over-provisioned → save $450/mo   │ │
│  │ ✓ Dev env on weekends → save $1,200/mo     │ │
│  │ ✓ Switch 2 nodes to Spot → save $800/mo    │ │
│  └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### Right-sizing 자동화

```yaml
# VPA 추천값 기반 Right-sizing 리포트 생성
# CronJob으로 주간 실행

apiVersion: batch/v1
kind: CronJob
metadata:
  name: rightsizing-report
spec:
  schedule: "0 9 * * 1"                    # 매주 월요일 09:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: reporter
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              echo "=== Right-sizing Report ==="
              echo "Date: $(date)"
              echo ""
              for vpa in $(kubectl get vpa -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'); do
                NS=$(echo $vpa | cut -d/ -f1)
                NAME=$(echo $vpa | cut -d/ -f2)
                echo "--- $NS/$NAME ---"
                kubectl get vpa $NAME -n $NS -o jsonpath='{.status.recommendation.containerRecommendations[*]}' | jq .
              done | curl -X POST -d @- $SLACK_WEBHOOK_URL
          restartPolicy: OnFailure
```

### 비업무 시간 자동 스케일다운

```yaml
# KEDA CronScaler - 야간/주말 스케일다운
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: alli-staging-cron
  namespace: alli-staging
spec:
  scaleTargetRef:
    name: alli-api-staging
  minReplicaCount: 0
  maxReplicaCount: 10
  triggers:
  # 업무 시간 (월~금 09:00~21:00 KST)
  - type: cron
    metadata:
      timezone: Asia/Seoul
      start: 0 9 * * 1-5
      end: 0 21 * * 1-5
      desiredReplicas: "3"
  # 비업무 시간 → 0으로 스케일다운
  - type: cron
    metadata:
      timezone: Asia/Seoul
      start: 0 21 * * 1-5
      end: 0 9 * * 2-6
      desiredReplicas: "0"
```

---

## 면접 Q&A

### Q1: 클라우드 비용을 40% 절감해야 한다면 어떤 순서로 접근하시겠습니까?

**30초 답변**:
먼저 Kubecost/Cost Explorer로 비용 현황을 가시화하고 Top Cost Driver를 식별합니다. 가장 큰 절감 효과는 GPU 인스턴스에서 나오므로, 활용률이 낮은 GPU를 정리하고 RI/SP를 구매합니다. 그 다음 Spot 활용, Dev/Staging 비업무시간 중지, right-sizing 순으로 적용합니다.

**2분 답변**:
단계별 접근:

1단계 - 가시화 (1주):
- 모든 리소스에 태그 정책 적용 (team, env, service)
- Kubecost 설치, Cost Explorer 대시보드 구성
- Top 10 비용 항목 식별

2단계 - Quick Win (2주):
- 유휴 리소스 정리: 미사용 EBS, Elastic IP, 중지된 인스턴스
- Dev/Staging 비업무시간 자동 종료 → 60~70% 절감 (해당 환경)
- 이전 세대 인스턴스 → 최신 세대 (m5→m6i: 10% 저렴 + 성능 향상)

3단계 - 구조적 최적화 (1개월):
- Reserved Instance / Savings Plan 구매 (안정적 워크로드)
- Spot Instance 도입 (batch, training, dev)
- GPU right-sizing (VPA 추천값 기반)
- 모델 양자화 (FP16→INT8: GPU 수 50% 절감 가능)

4단계 - 지속적 관리:
- 월간 비용 리뷰 프로세스 수립
- 예산 알림 자동화
- Kubecost Efficiency 리포트 주간 배포

예상 절감:
- RI/SP: 30~40% (compute 비용의)
- Spot: 60~70% (배치 워크로드)
- 비업무시간 중지: 60% (dev/staging)
- Right-sizing: 20~30% (과할당 해소)

**💡 경험 연결**:
"인프라 비용 최적화는 항상 '측정 → 분석 → 개선 → 검증' 사이클로 접근합니다. 온프레미스에서도 서버 활용률을 분석하여 통합/가상화하던 경험이 클라우드 비용 최적화에 직접 적용됩니다."

**⚠️ 주의**: 비용 절감을 위해 안정성을 희생하면 안 된다. Production 서비스는 반드시 On-demand/RI를 사용하고, Spot은 내결함성이 있는 워크로드에만 적용.

---

### Q2: Kubecost를 사용하여 K8s 비용을 관리하는 방법을 설명해주세요.

**30초 답변**:
Kubecost는 K8s 리소스 사용량과 클라우드 단가를 조합하여 네임스페이스/워크로드 단위의 실제 비용을 계산합니다. CPU, Memory, GPU, Storage, Network 비용을 분리하여 보여주고, over-provisioned 워크로드를 식별하여 right-sizing을 추천합니다.

**2분 답변**:
Kubecost 활용 방법:

1. **비용 할당 (Allocation)**:
   - 네임스페이스별: alli-prod $28K, alli-staging $5K 등
   - 워크로드별: alli-inference Deployment가 전체의 50% 등
   - 레이블별: team=ml, team=platform으로 팀별 할당

2. **효율성 분석 (Efficiency)**:
   - CPU request vs 실사용량 비교
   - Memory request vs 실사용량 비교
   - 효율성 30% 미만인 워크로드 알림

3. **Savings 추천**:
   - "이 Deployment의 CPU request를 2→0.5로 줄이면 월 $200 절감"
   - "이 namespace에 유휴 PVC 3개 → 삭제 시 월 $50 절감"

4. **예산 관리**:
   - 네임스페이스별 월간 예산 설정
   - 80%, 90%, 100% 도달 시 Slack 알림
   - 일일 비용 추이 리포트

5. **GPU 비용 추적**:
   - nvidia.com/gpu 리소스를 비용으로 환산
   - GPU 활용률 vs 비용 효율 대시보드

**💡 경험 연결**:
"인프라 자원 사용량을 추적하고 최적화하는 것은 온프레미스에서도 해왔던 핵심 업무입니다. Kubecost는 이를 K8s 환경에서 자동화해주는 도구로, 도입과 운영이 자연스럽습니다."

**⚠️ 주의**: Kubecost Free 버전은 15일 데이터만 보존. 장기 분석이 필요하면 Enterprise 또는 OpenCost(오픈소스 대안)를 고려.

---

### Q3: GPU 워크로드의 비용 최적화 전략을 구체적으로 설명해주세요.

**30초 답변**:
GPU 비용 최적화는 세 가지 축입니다. 첫째, GPU 활용률을 높이는 것(MIG/Time-Slicing, batch size 최적화). 둘째, 인스턴스 비용을 낮추는 것(RI/SP, Spot). 셋째, 필요 GPU 수를 줄이는 것(모델 양자화, 증류, TensorRT 최적화). 이 세 축을 조합하면 50~70% 절감이 가능합니다.

**2분 답변**:

**축 1: 활용률 최적화 (같은 GPU로 더 많이)**
- dcgm-exporter로 GPU util 추적. 30% 미만이면 과할당.
- MIG로 A100을 분할: 1대로 3~7개 서비스 운영 가능.
- Continuous Batching (vLLM): batch size를 동적으로 조절하여 GPU 유휴 시간 최소화.
- 요청이 적은 시간에 추론 서버 수를 줄이는 HPA.

**축 2: 인스턴스 비용 절감 (같은 GPU를 더 싸게)**
- Production inference → 1~3년 RI/SP (35~60% 절감)
- Training/Fine-tuning → Spot (70% 절감, 체크포인트 필수)
- Dev/Test → Spot + 비업무시간 자동 종료

**축 3: GPU 수량 감소 (더 적은 GPU로 같은 일)**
- 양자화: FP32→FP16→INT8→INT4로 메모리 절감
  - INT8 양자화: 모델 크기 절반, GPU 수 절반, 품질 손실 미미
- 모델 증류: 70B 모델을 7B로 증류 (특정 태스크에서 유사 성능)
- TensorRT-LLM: NVIDIA 최적화 엔진으로 2~4x 처리량 향상

구체적 절감 시나리오:
```
Before: A100 x 8대 (On-demand) → $32.77/hr x 8 = $262/hr
After:
  - INT8 양자화 → 4대로 축소
  - 1yr RI 구매 → $21.30/hr x 4 = $85/hr
  - 절감: $262 → $85 = 67% 절감
```

**💡 경험 연결**:
"서버 리소스 최적화는 '측정 → 분석 → 최적화' 사이클입니다. GPU도 동일한 접근을 적용하되, 비용 단위가 10~100배 크므로 작은 개선도 큰 절감으로 이어집니다."

**⚠️ 주의**: 양자화 시 모델 품질 평가를 반드시 수행해야 한다. 비용 절감을 위해 서비스 품질을 희생하면 안 된다.

---

## Allganize 맥락

- **GPU 중심 비용 구조**: Alli 서비스의 비용 대부분이 GPU 인스턴스. 활용률 최적화가 가장 큰 레버.
- **AWS + Azure 멀티 클라우드**: 클라우드별 RI/SP 전략을 각각 수립. 교차 활용 불가.
- **FinOps 문화**: 스타트업으로서 비용 효율이 중요. 팀별 비용 가시화 → 책임 부여.
- **Kubecost**: K8s 기반 운영이므로 Kubecost가 가장 적합한 비용 분석 도구.
- **모델 양자화**: Alli의 LLM을 양자화하여 GPU 비용 절감. ML 팀과 협업 필요.
- **JD 연결**: "클라우드 인프라 운영"에서 비용 관리는 핵심 역량. FinOps 경험이 차별화 요소.

---

**핵심 키워드**: `FinOps` `Kubecost` `Reserved-Instance` `Savings-Plan` `Spot-Instance` `Right-sizing` `GPU-cost-optimization` `Quantization` `Cost-Explorer` `Showback-Chargeback`
