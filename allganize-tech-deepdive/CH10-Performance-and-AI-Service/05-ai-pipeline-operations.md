# AI 파이프라인 운영

> **TL;DR**: 모델 배포 파이프라인은 학습 → 평가 → 레지스트리 → 서빙의 단계를 자동화한다.
> A/B Testing과 Shadow Deployment로 새 모델을 안전하게 검증하고, 모델 버전 관리로 롤백을 보장한다.
> DevOps 엔지니어는 CI/CD의 ML 확장인 MLOps 파이프라인을 구축하고 운영한다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 20min

---

## 핵심 개념

### 1. ML/AI 배포 파이프라인 전체 흐름

```
┌────────────────────────────────────────────────────────────────┐
│                    AI Model Deployment Pipeline                 │
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐  │
│  │  Model   │   │  Model   │   │  Model   │   │  Model     │  │
│  │ Training │──▶│ Evaluate │──▶│ Registry │──▶│  Serving   │  │
│  │          │   │ /Validate│   │          │   │            │  │
│  └──────────┘   └──────────┘   └──────────┘   └────────────┘  │
│       │              │              │               │          │
│  GPU Cluster    메트릭 비교     버전 관리        A/B Test     │
│  Fine-tuning    Gate 통과 시    Artifact 저장    Shadow Deploy │
│  학습 데이터    자동 승격       메타데이터 관리   Canary Release│
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Monitoring & Feedback                  │  │
│  │  모델 성능 모니터링 → Drift 감지 → 재학습 트리거          │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### 2. 모델 배포 전략

```
전략 1: Rolling Update (기본)
──────────────────────────────────────────
  v1 [████] [████] [████]
       ↓
  v1 [████] [████] → v2 [████]          Pod 순차 교체
       ↓
  v1 [████] → v2 [████] [████]
       ↓
  v2 [████] [████] [████]              완료

주의: 모델 로딩 시간이 길면 교체 중 capacity 감소


전략 2: Blue-Green Deployment
──────────────────────────────────────────
  Blue (v1):  [████] [████] [████]  ← 현재 트래픽 100%
  Green (v2): [████] [████] [████]  ← 준비 완료, 트래픽 0%

  검증 후 트래픽 전환:
  Blue (v1):  [████] [████] [████]  ← 트래픽 0% (대기)
  Green (v2): [████] [████] [████]  ← 트래픽 100%

장점: 즉시 롤백 가능 (Blue로 복귀)
단점: 2배의 리소스 필요 (GPU 비용 높음)


전략 3: Canary Deployment
──────────────────────────────────────────
  v1: [████] [████] [████] [████]  ← 95% 트래픽
  v2: [████]                        ← 5% 트래픽 (카나리)

  메트릭 확인 후 점진 증가:
  v1: [████] [████] [████]          ← 70% → 50% → 0%
  v2: [████] [████]                  ← 30% → 50% → 100%


전략 4: Shadow Deployment
──────────────────────────────────────────
  사용자 요청 ──┬──→ v1 (Production) ──→ 응답 반환
                │
                └──→ v2 (Shadow)     ──→ 결과 기록만 (반환 X)
                                          │
                                     비교 분석 대시보드

장점: 사용자 영향 제로, 실제 트래픽으로 검증
단점: 2배 GPU 리소스, 응답 비교 로직 필요
```

### 3. A/B Testing for AI Models

```
A/B Testing 아키텍처

                    ┌──────────────┐
                    │  API Gateway │
                    │  / Istio VS  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Traffic Split│
                    │              │
                    │ user_id hash │
                    │ → 일관된     │
                    │   라우팅     │
                    └──┬────────┬──┘
                       │        │
              ┌────────▼──┐  ┌──▼────────┐
              │ Model A   │  │ Model B   │
              │ (Control) │  │ (Variant) │
              │ 50%       │  │ 50%       │
              └─────┬─────┘  └─────┬─────┘
                    │              │
              ┌─────▼──────────────▼─────┐
              │   Experiment Tracker      │
              │   - Response quality     │
              │   - Latency comparison   │
              │   - User satisfaction    │
              │   - Token usage / cost   │
              └──────────────────────────┘
```

```yaml
# Istio VirtualService로 A/B 트래픽 분할
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: alli-llm-ab
  namespace: alli-inference
spec:
  hosts:
  - alli-llm-svc
  http:
  - match:
    - headers:
        x-experiment-group:
          exact: "variant-b"
    route:
    - destination:
        host: alli-llm-svc
        subset: model-b
      weight: 100
  - route:
    - destination:
        host: alli-llm-svc
        subset: model-a
      weight: 80
    - destination:
        host: alli-llm-svc
        subset: model-b
      weight: 20

---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: alli-llm-dr
spec:
  host: alli-llm-svc
  subsets:
  - name: model-a
    labels:
      model-version: "v1.0"
  - name: model-b
    labels:
      model-version: "v1.1"
```

### 4. Shadow Deployment 구현

```yaml
# Istio VirtualService Mirror (Shadow)
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: alli-llm-shadow
spec:
  hosts:
  - alli-llm-svc
  http:
  - route:
    - destination:
        host: alli-llm-svc
        subset: production
      weight: 100
    mirror:
      host: alli-llm-svc
      subset: shadow
    mirrorPercentage:
      value: 100.0                    # 100% 미러링
```

### 5. 모델 버전 관리 (Model Versioning)

```
모델 레지스트리 구조

model-registry/
├── alli-chat-v1.0/
│   ├── model.safetensors          # 모델 가중치
│   ├── tokenizer.json             # 토크나이저
│   ├── config.json                # 모델 설정
│   └── metadata.json              # 메타데이터
│       {
│         "version": "1.0",
│         "framework": "vllm",
│         "gpu_memory_required": "40GB",
│         "eval_metrics": {
│           "accuracy": 0.89,
│           "latency_p95_ms": 450,
│           "ttft_p95_ms": 320
│         },
│         "training_date": "2025-12-01",
│         "approved_by": "ml-team",
│         "rollback_to": "v0.9"
│       }
├── alli-chat-v1.1/
│   └── ...
└── alli-embedding-v2.0/
    └── ...
```

```yaml
# 모델 저장소 (S3 + PVC 조합)
# S3에 모델 아카이브 보관, PVC로 서빙 노드에 캐시

apiVersion: batch/v1
kind: Job
metadata:
  name: model-sync-v1.1
spec:
  template:
    spec:
      containers:
      - name: sync
        image: amazon/aws-cli:latest
        command:
        - /bin/sh
        - -c
        - |
          aws s3 sync s3://alli-models/alli-chat-v1.1/ /models/alli-chat-v1.1/ \
            --exclude "*.tmp"
          # 무결성 검증
          sha256sum -c /models/alli-chat-v1.1/checksums.sha256
          # 준비 완료 마커
          touch /models/alli-chat-v1.1/.ready
        volumeMounts:
        - name: model-storage
          mountPath: /models
      volumes:
      - name: model-storage
        persistentVolumeClaim:
          claimName: model-cache-pvc
      restartPolicy: OnFailure
```

### 6. 모델 모니터링 및 Drift 감지

```
Model Monitoring 구성

┌─────────────────────────────────────────────────┐
│              Production Model (v1.0)             │
│                                                   │
│  Input ──→ Inference ──→ Output                  │
│    │                        │                    │
│    ▼                        ▼                    │
│  Input Logger           Output Logger            │
│    │                        │                    │
│    ▼                        ▼                    │
│  ┌─────────────────────────────────────────┐    │
│  │         Monitoring Dashboard            │    │
│  │                                          │    │
│  │  - Input Distribution Drift             │    │
│  │  - Output Quality Score                 │    │
│  │  - Latency Percentiles (TTFT, TPS)     │    │
│  │  - Error Rate                           │    │
│  │  - Token Usage & Cost                   │    │
│  └─────────────────────────────────────────┘    │
│                     │                            │
│              Drift 감지 시                        │
│                     ▼                            │
│         재학습/재배포 파이프라인 트리거             │
└─────────────────────────────────────────────────┘
```

**주요 모니터링 지표**:

| 카테고리 | 지표 | 설명 |
|---------|------|------|
| 품질 | Response Quality Score | 사용자 피드백, 자동 평가 |
| 품질 | Hallucination Rate | 환각 발생 비율 |
| 성능 | TTFT p95 | 첫 토큰 지연 |
| 성능 | TPS | 토큰 생성 속도 |
| 안정성 | Error Rate | 추론 실패율 |
| 비용 | Token Usage | 입출력 토큰 사용량 |
| Drift | Input Distribution | 입력 분포 변화 |

---

## 실전 예시

### ArgoCD + Kustomize 기반 모델 배포 파이프라인

```yaml
# GitOps 구조
# git repo: alli-model-deployments/
# ├── base/
# │   ├── deployment.yaml
# │   ├── service.yaml
# │   └── kustomization.yaml
# ├── overlays/
# │   ├── staging/
# │   │   ├── kustomization.yaml    # model-version: v1.1-rc1
# │   │   └── hpa.yaml
# │   └── production/
# │       ├── kustomization.yaml    # model-version: v1.0 (안정)
# │       └── hpa.yaml
# └── experiments/
#     └── ab-test-v1.1/
#         ├── virtual-service.yaml   # 20% 트래픽 분할
#         └── kustomization.yaml

# base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-llm
  labels:
    app: alli-llm
spec:
  template:
    metadata:
      labels:
        app: alli-llm
        model-version: MODEL_VERSION      # kustomize로 치환
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:v0.4.0
        args:
        - --model=/models/MODEL_PATH      # kustomize로 치환
        - --tensor-parallel-size=2

# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- ../../base
patches:
- target:
    kind: Deployment
    name: alli-llm
  patch: |
    - op: replace
      path: /spec/template/metadata/labels/model-version
      value: "v1.0"
    - op: replace
      path: /spec/template/spec/containers/0/args/0
      value: "--model=/models/alli-chat-v1.0"
```

### Argo Rollouts를 활용한 Canary 배포

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: alli-llm-rollout
spec:
  replicas: 4
  strategy:
    canary:
      canaryService: alli-llm-canary
      stableService: alli-llm-stable
      analysis:
        templates:
        - templateName: llm-quality-check
        startingStep: 1
        args:
        - name: service-name
          value: alli-llm-canary
      steps:
      - setWeight: 10                      # 10% 트래픽
      - pause: {duration: 30m}             # 30분 관찰
      - setWeight: 30
      - pause: {duration: 30m}
      - setWeight: 50
      - pause: {duration: 1h}              # 1시간 관찰
      - setWeight: 100

---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: llm-quality-check
spec:
  metrics:
  - name: ttft-p95
    interval: 5m
    successCondition: result[0] < 1.0      # TTFT p95 < 1초
    provider:
      prometheus:
        address: http://prometheus:9090
        query: |
          histogram_quantile(0.95,
            sum(rate(vllm_request_ttft_seconds_bucket{service="{{args.service-name}}"}[5m]))
            by (le))
  - name: error-rate
    interval: 5m
    successCondition: result[0] < 0.01     # 에러율 1% 미만
    provider:
      prometheus:
        address: http://prometheus:9090
        query: |
          sum(rate(vllm_request_errors_total{service="{{args.service-name}}"}[5m]))
          / sum(rate(vllm_requests_total{service="{{args.service-name}}"}[5m]))
```

---

## 면접 Q&A

### Q1: AI 모델 배포에서 Canary Deployment와 Shadow Deployment의 차이점과 사용 시나리오는?

**30초 답변**:
Canary는 실제 사용자의 일부(예: 10%)에게 새 모델 응답을 제공하여 점진적으로 검증합니다. Shadow는 모든 요청을 새 모델에도 보내되 응답은 기존 모델만 반환하고, 새 모델의 결과는 비교 분석만 합니다. Canary는 빠른 검증, Shadow는 무위험 검증에 적합합니다.

**2분 답변**:

| 특성 | Canary | Shadow |
|------|--------|--------|
| 사용자 영향 | 일부 사용자가 새 모델 응답 수신 | 없음 (기존 모델만 응답) |
| 리소스 비용 | 추가 비용 적음 (일부 Pod만) | 2배 GPU 비용 |
| 검증 속도 | 빠름 (실시간 사용자 피드백) | 느림 (오프라인 비교 분석) |
| 위험도 | 일부 사용자에게 품질 저하 가능 | 위험 제로 |
| 적합 시나리오 | 성능 개선, 마이너 모델 업데이트 | 모델 아키텍처 변경, 메이저 업데이트 |

AI 모델 배포의 특수성:
- 일반 소프트웨어와 달리 "정답"이 없어 품질 측정이 어려움
- LLM 응답 품질은 자동 평가(LLM-as-Judge) + 사용자 피드백 조합으로 판단
- A/B Testing은 통계적 유의성을 위해 충분한 샘플이 필요 (수일~수주)

Allganize 추천 전략:
1. Shadow로 먼저 새 모델의 응답 품질을 오프라인 비교
2. 품질 확인 후 Canary 10% → 30% → 100% 점진 배포
3. Argo Rollouts의 AnalysisTemplate으로 TTFT/에러율 자동 게이트

**💡 경험 연결**:
"서비스 배포 시 카나리 배포의 개념은 잘 알고 있으며, AI 모델 배포에서는 추가로 응답 품질이라는 비기능적 지표까지 검증해야 한다는 점이 차별점입니다."

**⚠️ 주의**: Shadow Deployment는 GPU 비용이 2배이므로 장기간 운영은 비현실적. 검증 기간을 명확히 정하고 완료 후 즉시 정리해야 한다.

---

### Q2: 모델 버전 관리는 어떻게 하며, 문제 발생 시 롤백 절차는?

**30초 답변**:
모델 아티팩트(가중치, 토크나이저, config)를 S3/GCS에 버전별로 저장하고, 메타데이터(평가 메트릭, 학습 날짜, 승인자)를 함께 관리합니다. GitOps로 Deployment의 model-version 레이블을 변경하여 배포하고, 롤백은 Git revert 또는 ArgoCD의 이전 리비전으로 복원합니다.

**2분 답변**:
모델 버전 관리 체계:
1. **아티팩트 저장**: S3에 `s3://models/{model-name}/{version}/` 구조로 저장
2. **메타데이터**: 평가 메트릭, GPU 메모리 요구량, 호환 서빙 프레임워크 버전
3. **체크섬**: SHA256으로 무결성 검증 (배포 시 자동 확인)
4. **GitOps 연동**: model-version을 Git 레포에서 관리 → ArgoCD가 동기화

롤백 절차:
```
1. 이상 감지 (TTFT 급증, 에러율 증가, 품질 저하)
2. ArgoCD에서 이전 리비전으로 Rollback 실행
3. 또는 Git revert → ArgoCD 자동 동기화
4. 서빙 Pod가 이전 모델 버전으로 교체
5. 모델 로딩 시간(3~5분) 후 서비스 복구
6. Post-mortem: 품질 저하 원인 분석
```

주의사항:
- 모델 파일이 수십 GB이므로 PVC 캐시를 유지하여 롤백 시 재다운로드 방지
- 이전 버전의 모델이 항상 로컬에 남아있도록 캐시 정책 설계
- 롤백 중에도 PDB를 존중하여 서비스 중단 최소화

**💡 경험 연결**:
"인프라 변경 관리에서 롤백 계획을 항상 먼저 수립하는 습관이 있습니다. AI 모델 배포도 동일하게, 배포 전에 롤백 경로와 소요 시간을 미리 확인하는 것이 중요합니다."

**⚠️ 주의**: 모델 롤백 시 모델 로딩 시간이 길다는 점을 반드시 언급. 일반 앱 롤백(초 단위)과 달리 분 단위 소요.

---

### Q3: MLOps와 전통적 DevOps의 차이점은 무엇입니까?

**30초 답변**:
전통 DevOps는 코드가 입력이고 바이너리가 출력입니다. MLOps는 코드 + 데이터가 입력이고 모델이 출력입니다. 추가로 데이터 버전 관리, 실험 추적, 모델 레지스트리, 모델 모니터링(drift 감지)이 필요하며, 배포 후에도 모델 품질을 지속적으로 평가해야 합니다.

**2분 답변**:

| 관점 | DevOps | MLOps |
|------|--------|-------|
| 입력 | 코드 | 코드 + 데이터 + 하이퍼파라미터 |
| 출력 | 바이너리/컨테이너 이미지 | 모델 아티팩트 |
| 버전 관리 | Git (코드) | Git (코드) + DVC (데이터) + Model Registry |
| 테스트 | 유닛/통합/E2E | + 모델 평가 (정확도, 편향, 공정성) |
| 배포 검증 | 기능 정상 동작 | + 모델 품질, A/B 통계적 유의성 |
| 운영 모니터링 | 가용성, 성능 | + 모델 drift, 데이터 drift |
| 인프라 | CPU 중심 | GPU 중심 (비용 10~100x) |
| 재현성 | Dockerfile로 보장 | 데이터 + 코드 + 환경 + 시드 모두 필요 |

DevOps 엔지니어가 MLOps에서 담당하는 영역:
- 학습/서빙 인프라 구축 (GPU 클러스터, K8s)
- 모델 배포 파이프라인 (CI/CD 확장)
- 서빙 인프라 운영 (vLLM, Triton)
- 모니터링/알림 (dcgm-exporter, 서빙 메트릭)
- 비용 최적화 (GPU 효율화, Spot 활용)

**💡 경험 연결**:
"DevOps 경험을 기반으로 MLOps로의 확장은 자연스럽습니다. CI/CD, 모니터링, IaC의 기본 원리가 동일하고, 여기에 데이터와 모델이라는 새로운 축이 추가되는 것입니다."

**⚠️ 주의**: MLOps 전체를 DevOps 엔지니어가 담당하는 것이 아님을 인지. ML 엔지니어와의 협업 포인트를 구분해서 설명해야 한다.

---

## Allganize 맥락

- **Alli 모델 배포**: Allganize의 LLM "Alli"는 지속적으로 개선되므로, 안전한 배포 파이프라인이 핵심
- **A/B Testing**: 고객사별 커스텀 모델의 성능을 비교하여 최적 모델 선택
- **Shadow Deployment**: 새 LLM 버전 출시 전 실제 트래픽으로 품질 검증
- **GitOps**: ArgoCD 기반으로 모델 버전을 선언적으로 관리
- **멀티 클라우드**: AWS/Azure 모두에서 동일한 모델 배포 파이프라인 운영
- **JD 연결**: "CI/CD 파이프라인 구축"이 모델 배포까지 확장되는 것

---

**핵심 키워드**: `Canary-Deployment` `Shadow-Deployment` `A/B-Testing` `Model-Registry` `Model-Versioning` `Argo-Rollouts` `MLOps` `GitOps` `Drift-Detection` `Blue-Green`
