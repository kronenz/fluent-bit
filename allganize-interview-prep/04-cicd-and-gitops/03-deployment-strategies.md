# 배포 전략 (Deployment Strategies)

> **TL;DR**
> - Rolling Update는 기본이고, Blue-Green은 즉시 전환/롤백, Canary는 점진적 검증에 적합하다
> - 배포 전략 선택은 다운타임 허용, 리소스 여유, 검증 수준에 따라 결정한다
> - Argo Rollouts를 사용하면 K8s에서 Canary/Blue-Green을 선언적(Declarative)으로 구현할 수 있다

---

## 1. 배포 전략 개요

### 왜 배포 전략이 중요한가?

배포는 장애의 주요 원인이다. Google SRE 보고서에 따르면 장애의 70%가 배포와 관련이 있다.
안전한 배포 전략은 사용자 영향을 최소화하면서 새 버전을 출시하는 핵심 수단이다.

### 전략 비교 요약

```
[Rolling Update]
v1 ●●●●  →  v1 ●●○  →  v1 ●○○  →  v2 ○○○
             v2 ○      v2 ○○      v2 ●●●
순차적으로 교체

[Blue-Green]
Blue(v1)  ●●●●  ← 트래픽
Green(v2) ○○○○

Blue(v1)  ●●●●
Green(v2) ○○○○  ← 트래픽 전환 (한 번에)

[Canary]
v1 ●●●●●●●●●  (90% 트래픽)
v2 ○            (10% 트래픽) → 점진적 증가
```

---

## 2. Rolling Update

### 개념

기존 Pod를 하나씩(또는 설정된 수만큼) 새 버전으로 교체하는 방식이다.
K8s Deployment의 기본(Default) 배포 전략이다.

### K8s 구현

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
spec:
  replicas: 4
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # 최대 1개 추가 Pod 허용 (총 5개까지)
      maxUnavailable: 1     # 최대 1개 Pod 불가용 허용 (최소 3개 유지)
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: backend
        image: harbor.internal.corp/myapp/backend:v2.0.0
        ports:
        - containerPort: 8080
        readinessProbe:          # Readiness Probe 필수!
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
```

### 배포 과정 상세

```
시점 1: maxSurge=1로 새 Pod 생성
  v1 [Ready] [Ready] [Ready] [Ready]
  v2 [Creating...]

시점 2: v2 Pod Ready, v1 Pod 하나 종료
  v1 [Ready] [Ready] [Ready] [Terminating]
  v2 [Ready]

시점 3: 반복
  v1 [Ready] [Ready] [Terminating]
  v2 [Ready] [Ready]

시점 4: 완료
  v2 [Ready] [Ready] [Ready] [Ready]
```

### 롤백

```bash
# 배포 상태 확인
kubectl rollout status deployment/backend

# 롤백 (이전 버전으로)
kubectl rollout undo deployment/backend

# 특정 리비전으로 롤백
kubectl rollout history deployment/backend
kubectl rollout undo deployment/backend --to-revision=3
```

### 장단점

| 장점 | 단점 |
|------|------|
| K8s 기본 내장, 추가 설정 불필요 | 배포 중 두 버전이 공존 |
| 리소스 효율적 (약간의 여유만 필요) | DB 스키마 변경 시 주의 필요 |
| 점진적이라 위험 분산 | 롤백 시간이 오래 걸릴 수 있음 |
| Zero-downtime 지원 | 정밀한 트래픽 제어 불가 |

---

## 3. Blue-Green Deployment

### 개념

두 개의 동일한 환경(Blue=현재, Green=새 버전)을 준비하고,
트래픽을 한 번에 전환(Switch)하는 방식이다.

### K8s 구현 (Service 기반)

```yaml
# Blue Deployment (현재 운영 중)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-blue
  labels:
    app: backend
    version: blue
spec:
  replicas: 4
  selector:
    matchLabels:
      app: backend
      version: blue
  template:
    metadata:
      labels:
        app: backend
        version: blue
    spec:
      containers:
      - name: backend
        image: harbor.internal.corp/myapp/backend:v1.0.0

---
# Green Deployment (새 버전, 대기 중)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-green
  labels:
    app: backend
    version: green
spec:
  replicas: 4
  selector:
    matchLabels:
      app: backend
      version: green
  template:
    metadata:
      labels:
        app: backend
        version: green
    spec:
      containers:
      - name: backend
        image: harbor.internal.corp/myapp/backend:v2.0.0

---
# Service: selector로 트래픽 전환
apiVersion: v1
kind: Service
metadata:
  name: backend
spec:
  selector:
    app: backend
    version: blue    # ← 'green'으로 변경하면 트래픽 전환
  ports:
  - port: 80
    targetPort: 8080
```

### 전환 스크립트

```bash
#!/bin/bash
# blue-green-switch.sh

CURRENT=$(kubectl get svc backend -o jsonpath='{.spec.selector.version}')
if [ "$CURRENT" = "blue" ]; then
    NEW="green"
else
    NEW="blue"
fi

echo "현재: ${CURRENT} → 전환: ${NEW}"

# Green 환경 Health Check
echo "새 버전 상태 확인 중..."
kubectl rollout status deployment/backend-${NEW} --timeout=120s
if [ $? -ne 0 ]; then
    echo "새 버전이 준비되지 않았습니다. 전환 취소."
    exit 1
fi

# 트래픽 전환
kubectl patch svc backend -p "{\"spec\":{\"selector\":{\"version\":\"${NEW}\"}}}"
echo "트래픽이 ${NEW}으로 전환되었습니다."

# 롤백이 필요하면
# kubectl patch svc backend -p '{"spec":{"selector":{"version":"'${CURRENT}'"}}}'
```

### 장단점

| 장점 | 단점 |
|------|------|
| 즉시 전환/롤백 (수 초) | 리소스 2배 필요 |
| 배포 전 충분한 검증 가능 | DB 마이그레이션 복잡 |
| 두 버전 공존 시간 없음 | 상태(State) 있는 서비스에 어려움 |
| 단순하고 이해하기 쉬움 | 비용 증가 |

---

## 4. Canary Deployment

### 개념

새 버전을 소수의 사용자에게 먼저 배포하고,
모니터링 결과를 보며 점진적으로 트래픽을 증가시키는 방식이다.

### K8s 기본 구현 (Replica 비율)

```yaml
# v1: 9 replicas (90% 트래픽)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-stable
spec:
  replicas: 9
  selector:
    matchLabels:
      app: backend
      track: stable
  template:
    metadata:
      labels:
        app: backend
        track: stable
    spec:
      containers:
      - name: backend
        image: harbor.internal.corp/myapp/backend:v1.0.0

---
# v2: 1 replica (10% 트래픽) - Canary
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-canary
spec:
  replicas: 1
  selector:
    matchLabels:
      app: backend
      track: canary
  template:
    metadata:
      labels:
        app: backend
        track: canary
    spec:
      containers:
      - name: backend
        image: harbor.internal.corp/myapp/backend:v2.0.0

---
# Service: 두 Deployment의 Pod를 모두 포함
apiVersion: v1
kind: Service
metadata:
  name: backend
spec:
  selector:
    app: backend    # track 라벨 없이 -> stable + canary 모두 포함
  ports:
  - port: 80
    targetPort: 8080
```

### Istio를 활용한 정밀 Canary

```yaml
# VirtualService로 가중치(Weight) 기반 트래픽 분배
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: backend
spec:
  hosts:
  - backend
  http:
  - route:
    - destination:
        host: backend
        subset: stable
      weight: 90
    - destination:
        host: backend
        subset: canary
      weight: 10

---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: backend
spec:
  host: backend
  subsets:
  - name: stable
    labels:
      version: v1
  - name: canary
    labels:
      version: v2
```

### 장단점

| 장점 | 단점 |
|------|------|
| 위험 최소화 (소수만 영향) | 구현 복잡도 높음 |
| 실제 트래픽으로 검증 | 모니터링 인프라 필수 |
| 메트릭 기반 자동화 가능 | 배포 시간이 김 |
| A/B 테스트에도 활용 가능 | Service Mesh 필요할 수 있음 |

---

## 5. 전략 선택 기준

| 기준 | Rolling | Blue-Green | Canary |
|------|---------|------------|--------|
| 다운타임 | Zero | Zero | Zero |
| 리소스 오버헤드 | 낮음 | 높음 (2배) | 중간 |
| 롤백 속도 | 느림 (분) | 즉시 (초) | 빠름 (초-분) |
| 구현 복잡도 | 낮음 | 중간 | 높음 |
| 버전 공존 | 있음 | 없음 | 있음 |
| 트래픽 제어 | 불가 | 전체 전환 | 정밀 제어 |
| **폐쇄망 적합도** | **최적** | **적합** | 인프라 필요 |

```
결정 트리:

리소스 여유 없음? → Rolling Update
즉시 롤백 필요? → Blue-Green
정밀 검증 필요? → Canary
DB 스키마 변경? → Blue-Green (+ DB 마이그레이션 전략)
```

---

## 6. Argo Rollouts - Progressive Delivery

### Argo Rollouts란?

K8s Deployment를 대체하는 CRD(Custom Resource Definition)로,
Blue-Green과 Canary 배포를 선언적으로 구현한다.

### 설치

```bash
# Argo Rollouts 설치
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts \
  -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

# kubectl 플러그인 설치
curl -LO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
chmod +x kubectl-argo-rollouts-linux-amd64
sudo mv kubectl-argo-rollouts-linux-amd64 /usr/local/bin/kubectl-argo-rollouts

# 배포 상태 실시간 확인
kubectl argo rollouts dashboard
```

### Canary Rollout

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: backend
spec:
  replicas: 10
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: backend
        image: harbor.internal.corp/myapp/backend:v2.0.0
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 200m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
  strategy:
    canary:
      # 단계별 트래픽 증가
      steps:
      - setWeight: 10         # 10% 트래픽을 Canary로
      - pause:
          duration: 5m        # 5분 대기 (메트릭 관찰)
      - setWeight: 30         # 30%로 증가
      - pause:
          duration: 5m
      - setWeight: 60         # 60%로 증가
      - pause:
          duration: 5m
      # 마지막 단계 후 100%로 자동 전환

      # 자동 롤백 조건 (Analysis 기반)
      analysis:
        templates:
        - templateName: success-rate
        startingStep: 1       # 두 번째 단계부터 분석 시작
        args:
        - name: service-name
          value: backend

      # 트래픽 관리 (Nginx Ingress 연동)
      canaryService: backend-canary
      stableService: backend-stable
      trafficRouting:
        nginx:
          stableIngress: backend-ingress
          additionalIngressAnnotations:
            canary-by-header: X-Canary
```

### Analysis Template (자동 롤백 조건)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
spec:
  args:
  - name: service-name
  metrics:
  - name: success-rate
    # Prometheus 쿼리로 성공률 측정
    successCondition: result[0] >= 0.95    # 95% 이상이면 성공
    failureLimit: 3                         # 3회 실패 시 롤백
    interval: 60s                           # 1분마다 체크
    provider:
      prometheus:
        address: http://prometheus.monitoring:9090
        query: |
          sum(rate(http_requests_total{
            service="{{args.service-name}}",
            status=~"2.."
          }[5m])) /
          sum(rate(http_requests_total{
            service="{{args.service-name}}"
          }[5m]))
```

### Blue-Green Rollout

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: frontend
spec:
  replicas: 4
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
      - name: frontend
        image: harbor.internal.corp/myapp/frontend:v2.0.0
        ports:
        - containerPort: 3000
  strategy:
    blueGreen:
      activeService: frontend-active       # 현재 트래픽을 받는 Service
      previewService: frontend-preview     # 미리보기 Service (테스트용)
      autoPromotionEnabled: false          # 수동 승인 필요
      scaleDownDelaySeconds: 300           # 이전 버전 5분 후 축소

      # 전환 전 자동 테스트
      prePromotionAnalysis:
        templates:
        - templateName: smoke-test
        args:
        - name: preview-url
          value: http://frontend-preview.default.svc

      # 전환 후 검증
      postPromotionAnalysis:
        templates:
        - templateName: success-rate
```

### Rollout 운영 명령어

```bash
# 배포 상태 실시간 확인
kubectl argo rollouts get rollout backend --watch

# 수동 승인 (promote)
kubectl argo rollouts promote backend

# 롤백 (abort)
kubectl argo rollouts abort backend

# 재시도
kubectl argo rollouts retry rollout backend

# 특정 이미지로 업데이트
kubectl argo rollouts set image backend backend=myapp:v3.0.0

# 대시보드로 시각적 확인
kubectl argo rollouts dashboard
# 브라우저에서 http://localhost:3100 접속
```

---

## 7. ArgoCD + Argo Rollouts 통합

```yaml
# ArgoCD Application에서 Rollout 사용
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: backend
  namespace: argocd
spec:
  source:
    repoURL: https://git.internal.corp/team/k8s-manifests.git
    path: apps/backend
  destination:
    server: https://kubernetes.default.svc
    namespace: backend
  syncPolicy:
    automated:
      selfHeal: true
```

```
[워크플로우]

1. 개발자가 이미지 태그를 Git에 Push
2. ArgoCD가 변경 감지 → Sync
3. Argo Rollouts가 Canary 배포 시작
4. AnalysisTemplate이 Prometheus 메트릭 검증
5. 성공 → 자동 Promote / 실패 → 자동 Rollback
6. ArgoCD UI에서 전체 상태 확인 가능
```

---

## 8. 면접 Q&A

### Q1. "Rolling Update, Blue-Green, Canary의 차이를 설명해주세요"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "Rolling Update는 K8s 기본 전략으로 Pod를 순차적으로 교체합니다.
> 리소스 효율적이지만 배포 중 두 버전이 공존합니다.
> Blue-Green은 두 환경을 준비하고 트래픽을 한 번에 전환하므로 즉시 롤백이 가능하지만
> 리소스가 2배 필요합니다.
> Canary는 새 버전에 소수 트래픽을 보내며 점진적으로 늘리는 방식으로,
> 실제 사용자 트래픽으로 검증할 수 있지만 구현이 복잡합니다.
> 폐쇄망 온프레미스 환경에서는 리소스 제약이 있어 Rolling Update를 기본으로 쓰고,
> 중요 서비스에만 Blue-Green을 적용했습니다."

### Q2. "Canary 배포에서 자동 롤백은 어떻게 구현하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "Argo Rollouts의 AnalysisTemplate을 사용합니다.
> Prometheus에서 HTTP 성공률이나 응답 시간(Latency) 같은 메트릭을 주기적으로 조회하고,
> 성공 조건(예: 성공률 95% 이상)을 만족하지 못하면 자동으로 롤백합니다.
> 예를 들어 Canary가 10%에서 시작하고, 5분마다 메트릭을 체크한 뒤
> 문제가 없으면 30%, 60%, 100%로 단계적으로 올립니다.
> 어느 단계에서든 메트릭이 기준을 벗어나면 즉시 0%로 롤백됩니다."

### Q3. "DB 스키마 변경이 있을 때 배포 전략은?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "DB 변경이 있으면 Blue-Green이 가장 안전합니다.
> 핵심은 하위 호환(Backward Compatible) 마이그레이션입니다.
> 컬럼 추가는 괜찮지만, 컬럼 삭제나 이름 변경은 Expand-Contract 패턴을 씁니다.
> 1단계에서 새 컬럼을 추가하고 양쪽에 쓰기(Dual Write),
> 2단계에서 새 버전으로 전환,
> 3단계에서 확인 후 이전 컬럼을 삭제합니다.
> 이렇게 하면 롤백이 필요해도 이전 버전이 여전히 동작합니다."

### Q4. "Argo Rollouts를 ArgoCD와 함께 사용하는 이유는?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "ArgoCD는 Git과 클러스터의 상태를 동기화하는 GitOps 도구이고,
> Argo Rollouts는 배포 과정 자체를 제어하는 Progressive Delivery 도구입니다.
> 둘을 함께 쓰면, ArgoCD가 Git 변경을 감지하여 Sync하고,
> Argo Rollouts가 Canary나 Blue-Green 방식으로 안전하게 배포합니다.
> 메트릭 기반 자동 롤백까지 포함하면 완전 자동화된 안전한 배포 파이프라인이 됩니다.
> 폐쇄망 환경에서도 Prometheus를 내부에 구축하면 동일하게 적용 가능합니다."

---

## 키워드 (Keywords)

`Rolling Update` `Blue-Green` `Canary` `Argo Rollouts` `Progressive Delivery`
