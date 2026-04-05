# 배포 전략 심화 (Deployment Strategies Deep Dive)

> **TL;DR**
> - Rolling Update는 K8s 기본 전략으로 리소스 효율적이지만 두 버전이 공존하고, Blue-Green은 즉시 전환/롤백이 가능하지만 리소스 2배, Canary는 정밀 검증이 가능하지만 구현이 복잡하다
> - Argo Rollouts는 K8s Deployment를 대체하는 CRD로, Canary/Blue-Green을 선언적으로 구현하고 AnalysisTemplate으로 메트릭 기반 자동 롤백을 지원한다
> - 배포 전략 선택은 다운타임 허용도, 리소스 여유, 검증 수준, DB 스키마 변경 유무로 결정한다

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### 배포 전략이 중요한 이유

Google SRE 보고서에 따르면 장애의 70%가 배포와 관련이 있다. 안전한 배포 전략은 사용자 영향을 최소화하면서 새 버전을 출시하는 핵심 수단이다.

### 3대 배포 전략 시각화

```
[Rolling Update] ── K8s 기본, Pod를 순차적으로 교체
Time →
t0: v1 ●●●●          (4 replicas, 100% v1)
t1: v1 ●●●  v2 ○     (maxSurge=1, 새 Pod 생성)
t2: v1 ●●   v2 ○○    (v1 하나 종료, v2 하나 추가)
t3: v1 ●    v2 ○○○
t4:          v2 ○○○○  (100% v2, 완료)

[Blue-Green] ── 두 환경을 준비하고 트래픽을 한 번에 전환
t0: Blue(v1) ●●●● ← Traffic     Green(v2) ○○○○ (대기)
t1: Blue(v1) ●●●●               Green(v2) ○○○○ ← Traffic 전환
    즉시 롤백: Blue로 다시 전환

[Canary] ── 소수 트래픽으로 검증 후 점진적 확대
t0: Stable(v1) ●●●●●●●●●● (100%)
t1: Stable(v1) ●●●●●●●●●  (90%)  Canary(v2) ○ (10%)
t2: Stable(v1) ●●●●●●●    (70%)  Canary(v2) ○○○ (30%)
t3: Stable(v1) ●●●●       (40%)  Canary(v2) ○○○○○○ (60%)
t4: Canary(v2) → Stable    ○○○○○○○○○○ (100%)
```

### Rolling Update 심화

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api
spec:
  replicas: 6
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 2          # 최대 2개 추가 (총 8개까지)
      maxUnavailable: 1     # 최대 1개 불가용 (최소 5개 유지)
  # minReadySeconds: 30    # Pod Ready 후 30초 대기 (안정성 확보)
  # progressDeadlineSeconds: 600  # 10분 내 완료 안 되면 실패
  template:
    spec:
      containers:
      - name: alli-api
        image: ghcr.io/allganize/alli-api:v2.0.0
        ports:
        - containerPort: 8080
        # Readiness Probe: Rolling Update의 핵심!
        # 이것이 없으면 트래픽이 준비 안 된 Pod로 갈 수 있다
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
```

```
maxSurge / maxUnavailable 조합 전략:

┌─────────────────────┬─────────────────┬───────────────────────┐
│ 시나리오             │ maxSurge        │ maxUnavailable        │
├─────────────────────┼─────────────────┼───────────────────────┤
│ 안전 우선 (느림)     │ 1               │ 0                     │
│ → 항상 N개 이상 유지  │                 │ → 추가 Pod Ready 후   │
│                     │                 │   기존 Pod 종료        │
├─────────────────────┼─────────────────┼───────────────────────┤
│ 속도 우선 (빠름)     │ 50%             │ 50%                   │
│ → 절반씩 교체        │                 │                       │
├─────────────────────┼─────────────────┼───────────────────────┤
│ 리소스 절약          │ 0               │ 1                     │
│ → 추가 Pod 없이      │                 │ → 기존 종료 후         │
│   교체               │                 │   새 Pod 생성          │
├─────────────────────┼─────────────────┼───────────────────────┤
│ 균형 (권장)          │ 25%             │ 25%                   │
│ → K8s 기본값         │                 │                       │
└─────────────────────┴─────────────────┴───────────────────────┘
```

### Blue-Green 구현 패턴

**패턴 1: Service selector 전환**

```yaml
# Blue Deployment (현재)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api-blue
spec:
  replicas: 4
  selector:
    matchLabels:
      app: alli-api
      version: blue
  template:
    metadata:
      labels:
        app: alli-api
        version: blue
    spec:
      containers:
      - name: alli-api
        image: ghcr.io/allganize/alli-api:v1.0.0
---
# Green Deployment (새 버전)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api-green
spec:
  replicas: 4
  selector:
    matchLabels:
      app: alli-api
      version: green
  template:
    metadata:
      labels:
        app: alli-api
        version: green
    spec:
      containers:
      - name: alli-api
        image: ghcr.io/allganize/alli-api:v2.0.0
---
# Service: selector 전환으로 트래픽 이동
apiVersion: v1
kind: Service
metadata:
  name: alli-api
spec:
  selector:
    app: alli-api
    version: blue    # → 'green'으로 변경하면 즉시 전환
  ports:
  - port: 80
    targetPort: 8080
```

**패턴 2: Ingress 기반 전환 (더 안전)**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-api
  annotations:
    # Nginx Ingress Controller 기반
    nginx.ingress.kubernetes.io/canary: "false"
spec:
  rules:
  - host: api.allganize.ai
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: alli-api-blue    # → green으로 변경
            port:
              number: 80
```

### Canary 구현 패턴

**패턴 1: Replica 비율 (기본)**

```
Service (selector: app=alli-api)
    │
    ├── Deployment: alli-api-stable (replicas: 9)
    │   labels: app=alli-api, track=stable
    │
    └── Deployment: alli-api-canary (replicas: 1)
        labels: app=alli-api, track=canary

→ Service는 app=alli-api로 선택하므로 10개 Pod에 균등 분배
→ 약 90:10 비율 (정밀하지 않음)
```

**패턴 2: Istio VirtualService (정밀 트래픽 제어)**

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: alli-api
spec:
  hosts:
  - alli-api
  http:
  - route:
    - destination:
        host: alli-api
        subset: stable
      weight: 90
    - destination:
        host: alli-api
        subset: canary
      weight: 10
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: alli-api
spec:
  host: alli-api
  subsets:
  - name: stable
    labels:
      version: v1
  - name: canary
    labels:
      version: v2
```

**패턴 3: Nginx Ingress Canary**

```yaml
# Stable Ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-api-stable
spec:
  rules:
  - host: api.allganize.ai
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: alli-api-stable
            port:
              number: 80
---
# Canary Ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-api-canary
  annotations:
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "10"
    # 헤더 기반: 특정 사용자만 Canary로
    # nginx.ingress.kubernetes.io/canary-by-header: "X-Canary"
    # nginx.ingress.kubernetes.io/canary-by-header-value: "true"
spec:
  rules:
  - host: api.allganize.ai
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: alli-api-canary
            port:
              number: 80
```

### 전략 선택 의사결정 트리

```
                    배포 전략 선택
                         │
                ┌────────┤
                │        │
          리소스 여유 없음?
                │
          ┌─Yes─┤──No──┐
          │            │
    Rolling Update   즉시 롤백 필요?
                       │
                 ┌─Yes─┤──No──┐
                 │            │
            Blue-Green   정밀 트래픽 제어 필요?
                              │
                        ┌─Yes─┤──No──┐
                        │            │
                     Canary    Rolling Update
                    (Argo Rollouts)

  추가 고려사항:
  ● DB 스키마 변경 있음 → Blue-Green (Expand-Contract)
  ● AI 모델 교체 → Canary (정확도 메트릭 검증)
  ● 프론트엔드 → Blue-Green (UX 일관성)
  ● API 서비스 → Canary (점진적 검증)
```

### Argo Rollouts 심화

Argo Rollouts는 K8s Deployment를 대체하는 CRD로, Progressive Delivery를 선언적으로 구현한다.

```
Deployment vs Rollout:

┌──────────────┐          ┌──────────────────────────┐
│  Deployment  │          │  Rollout                  │
│              │          │                           │
│  strategy:   │          │  strategy:                │
│    type:     │          │    canary:                │
│    Rolling   │          │      steps:               │
│    Update    │          │      - setWeight: 10      │
│              │          │      - pause: {duration:5m}│
│              │          │      - setWeight: 30      │
│              │          │      - pause: {}          │
│              │          │      analysis:             │
│              │          │        templates:          │
│              │          │        - successRate       │
│  (기본 전략만)│          │  (Canary + 자동 분석)      │
└──────────────┘          └──────────────────────────┘
```

### Argo Rollouts - Canary with Analysis

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: alli-api
spec:
  replicas: 10
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: alli-api
  template:
    metadata:
      labels:
        app: alli-api
    spec:
      containers:
      - name: alli-api
        image: ghcr.io/allganize/alli-api:v2.0.0
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
  strategy:
    canary:
      # ── 트래픽 라우팅 ──
      canaryService: alli-api-canary       # Canary Pod용 Service
      stableService: alli-api-stable       # Stable Pod용 Service
      trafficRouting:
        nginx:
          stableIngress: alli-api-ingress  # 기존 Ingress
          additionalIngressAnnotations:
            canary-by-header: X-Canary     # 헤더 기반 라우팅도 지원

      # ── 단계별 배포 ──
      steps:
      - setWeight: 5                       # 5% 트래픽
      - pause: { duration: 2m }            # 2분 대기 (메트릭 수집)

      - setWeight: 10                      # 10%
      - pause: { duration: 5m }

      - setWeight: 30                      # 30%
      - pause: { duration: 5m }

      - setWeight: 60                      # 60%
      - pause: { duration: 5m }

      # 마지막 단계 후 자동으로 100% 전환

      # ── 메트릭 기반 자동 분석 ──
      analysis:
        templates:
        - templateName: alli-api-analysis
        startingStep: 1                    # 5% 단계부터 분석 시작
        args:
        - name: service-name
          value: alli-api-canary

      # ── 롤백 조건 ──
      abortScaleDownDelaySeconds: 30       # abort 후 30초 뒤 축소
      dynamicStableScale: true             # Canary 증가 시 Stable 축소
```

### AnalysisTemplate - 자동 롤백 판단

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: alli-api-analysis
spec:
  args:
  - name: service-name
  metrics:
  # ── 메트릭 1: HTTP 성공률 ──
  - name: success-rate
    successCondition: result[0] >= 0.95   # 95% 이상이면 성공
    failureLimit: 3                        # 3회 연속 실패 시 롤백
    interval: 60s                          # 1분마다 체크
    provider:
      prometheus:
        address: http://prometheus.monitoring:9090
        query: |
          sum(rate(
            http_requests_total{
              service="{{args.service-name}}",
              status=~"2.."
            }[5m]
          )) /
          sum(rate(
            http_requests_total{
              service="{{args.service-name}}"
            }[5m]
          ))

  # ── 메트릭 2: 응답 시간 P99 ──
  - name: latency-p99
    successCondition: result[0] < 500      # 500ms 미만
    failureLimit: 3
    interval: 60s
    provider:
      prometheus:
        address: http://prometheus.monitoring:9090
        query: |
          histogram_quantile(0.99,
            sum(rate(
              http_request_duration_seconds_bucket{
                service="{{args.service-name}}"
              }[5m]
            )) by (le)
          ) * 1000

  # ── 메트릭 3: 에러 로그 수 ──
  - name: error-count
    successCondition: result[0] < 10       # 5분간 에러 10건 미만
    failureLimit: 2
    interval: 300s
    provider:
      prometheus:
        address: http://prometheus.monitoring:9090
        query: |
          sum(increase(
            log_messages_total{
              service="{{args.service-name}}",
              level="error"
            }[5m]
          ))
```

### Argo Rollouts - Blue-Green

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: alli-web
spec:
  replicas: 4
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: alli-web
  template:
    metadata:
      labels:
        app: alli-web
    spec:
      containers:
      - name: alli-web
        image: ghcr.io/allganize/alli-web:v2.0.0
        ports:
        - containerPort: 3000
  strategy:
    blueGreen:
      activeService: alli-web-active         # 현재 트래픽 서비스
      previewService: alli-web-preview       # 미리보기 서비스

      autoPromotionEnabled: false            # 수동 승인 필요
      # autoPromotionSeconds: 300            # 5분 후 자동 승인

      scaleDownDelaySeconds: 300             # 전환 후 5분간 이전 버전 유지

      # ── 전환 전 검증 ──
      prePromotionAnalysis:
        templates:
        - templateName: smoke-test
        args:
        - name: preview-url
          value: http://alli-web-preview.default.svc:3000

      # ── 전환 후 검증 ──
      postPromotionAnalysis:
        templates:
        - templateName: alli-api-analysis
```

### Smoke Test AnalysisTemplate

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: smoke-test
spec:
  args:
  - name: preview-url
  metrics:
  - name: smoke-test
    count: 1                              # 1회만 실행
    provider:
      job:
        spec:
          backoffLimit: 0
          template:
            spec:
              containers:
              - name: smoke-test
                image: curlimages/curl:latest
                command:
                - sh
                - -c
                - |
                  # 핵심 엔드포인트 검증
                  echo "Testing {{args.preview-url}}/healthz..."
                  curl -sf {{args.preview-url}}/healthz || exit 1

                  echo "Testing {{args.preview-url}}/api/v1/status..."
                  curl -sf {{args.preview-url}}/api/v1/status || exit 1

                  echo "All smoke tests passed!"
              restartPolicy: Never
```

### 자동 롤백 흐름

```
┌──────────────────────────────────────────────────────────┐
│            Argo Rollouts 자동 롤백 흐름                    │
│                                                          │
│  1. 이미지 태그 변경 (Git Push)                            │
│     │                                                    │
│  2. ArgoCD Sync → Rollout 업데이트 감지                   │
│     │                                                    │
│  3. Canary Pod 생성 (5% 트래픽)                           │
│     │                                                    │
│  4. AnalysisRun 시작                                      │
│     │  ├── 성공률 체크: 98% ✅ (≥95%)                     │
│     │  ├── P99 지연시간: 320ms ✅ (<500ms)                │
│     │  └── 에러 수: 2 ✅ (<10)                           │
│     │                                                    │
│  5. 다음 단계 (10% → 30% → 60%)                          │
│     │  ├── 성공률 체크: 91% ❌ (<95%)  ← 3회 연속 실패    │
│     │  │                                                 │
│  6. AnalysisRun Failed → Rollout Abort                   │
│     │                                                    │
│  7. Canary Pod 제거, 100% Stable(v1)로 복구               │
│     │                                                    │
│  8. Notification: "alli-api 롤백 완료 (사유: 성공률 저하)" │
└──────────────────────────────────────────────────────────┘
```

### DB 스키마 변경 시 배포 전략

```
[Expand-Contract 패턴]

Phase 1: Expand (확장)
  ● 새 컬럼 추가 (기존 컬럼 유지)
  ● v1 코드가 새 컬럼을 무시하므로 안전
  ● DB Migration Job (ArgoCD Sync Wave: PreSync)

Phase 2: Migrate (전환)
  ● v2 코드 배포 (새 컬럼 사용)
  ● Dual Write: 이전 + 새 컬럼 모두 쓰기
  ● Canary 또는 Blue-Green으로 배포

Phase 3: Contract (축소)
  ● v2가 안정화된 후
  ● 이전 컬럼 제거 (별도 Migration)
  ● v1으로 롤백 불가능한 시점

예시:
  users 테이블의 name → first_name + last_name 분리

  Phase 1: first_name, last_name 컬럼 추가
  Phase 2: v2가 first_name, last_name 사용 + name도 유지
  Phase 3: name 컬럼 삭제 (v2 안정화 확인 후)
```

---

## 실전 예시

### Argo Rollouts 운영 명령어

```bash
# 설치
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts \
  -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

# kubectl 플러그인 설치
curl -LO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
chmod +x kubectl-argo-rollouts-linux-amd64
sudo mv kubectl-argo-rollouts-linux-amd64 /usr/local/bin/kubectl-argo-rollouts

# 실시간 상태 확인 (가장 유용한 명령어)
kubectl argo rollouts get rollout alli-api --watch

# 수동 승인 (Canary 다음 단계로)
kubectl argo rollouts promote alli-api

# 즉시 전체 전환 (모든 단계 스킵)
kubectl argo rollouts promote alli-api --full

# 롤백 (abort)
kubectl argo rollouts abort alli-api

# 재시도 (abort 후)
kubectl argo rollouts retry rollout alli-api

# 이미지 직접 변경 (테스트 시 유용)
kubectl argo rollouts set image alli-api alli-api=ghcr.io/allganize/alli-api:v3.0.0

# 대시보드
kubectl argo rollouts dashboard
# http://localhost:3100 에서 시각적 확인
```

### ArgoCD + Argo Rollouts 통합 워크플로우

```
┌────────────────────────────────────────────────────────┐
│  Git Push (image tag)                                  │
│       │                                                │
│       ▼                                                │
│  ArgoCD: OutOfSync 감지 → Sync                         │
│       │                                                │
│       ▼                                                │
│  Argo Rollouts: Canary 시작 (5%)                       │
│       │                                                │
│       ▼                                                │
│  AnalysisRun: Prometheus 메트릭 검증                    │
│       │                                                │
│  ┌────┴────┐                                           │
│  │         │                                           │
│  Pass     Fail                                         │
│  │         │                                           │
│  ▼         ▼                                           │
│  다음 단계  자동 롤백                                    │
│  (10%→30%) (100% v1)                                   │
│  │                                                     │
│  ▼                                                     │
│  100% v2: 배포 완료                                     │
│       │                                                │
│       ▼                                                │
│  ArgoCD: Healthy 확인                                   │
│  Notification: Slack 알림                               │
└────────────────────────────────────────────────────────┘
```

---

## 면접 Q&A

### Q: "Rolling Update, Blue-Green, Canary의 차이를 설명해주세요"

**30초 답변**:
Rolling Update는 K8s 기본 전략으로 Pod를 순차적으로 교체합니다. 리소스 효율적이지만 배포 중 두 버전이 공존합니다. Blue-Green은 두 환경을 준비하고 트래픽을 한 번에 전환하므로 즉시 롤백이 가능하지만 리소스가 2배 필요합니다. Canary는 소수 트래픽으로 새 버전을 검증하며 점진적으로 확대하는데, 메트릭 기반 자동 롤백이 가능하지만 구현이 복잡합니다.

**2분 답변**:
세 전략은 위험 수용 수준과 리소스 가용성에 따라 선택합니다. Rolling Update는 K8s Deployment의 기본 전략으로, maxSurge와 maxUnavailable 파라미터로 교체 속도를 제어합니다. 가장 큰 장점은 추가 설정 없이 사용 가능하고 리소스 효율적이라는 점입니다. 단점은 배포 중 v1과 v2가 동시에 트래픽을 처리하므로, API 호환성이 보장되어야 합니다. 또한 롤백 시 다시 Rolling Update를 실행해야 하므로 수 분이 걸립니다. Blue-Green은 동일한 환경 두 개를 운영하고 Service selector나 Ingress 변경으로 트래픽을 즉시 전환합니다. 가장 큰 장점은 롤백이 수 초 내에 가능하다는 점이고, 두 버전이 공존하지 않습니다. 단점은 리소스가 2배 필요하고, DB 스키마 변경이 있으면 양쪽 환경이 같은 DB를 사용하므로 마이그레이션 전략이 복잡합니다. Canary는 가장 정교한 전략으로, 실제 사용자 트래픽으로 새 버전을 검증합니다. Argo Rollouts를 사용하면 AnalysisTemplate으로 Prometheus 메트릭(성공률, 지연시간)을 자동 검증하고, 기준을 만족하지 못하면 자동 롤백합니다. AI 서비스처럼 모델 교체 시 정확도 검증이 필요한 경우에 특히 유용합니다. 실무에서는 서비스 특성에 따라 혼합합니다. 내부 API는 Rolling Update, 사용자 대면 서비스는 Canary, 프론트엔드는 Blue-Green이 일반적입니다.

**💡 경험 연결**:
온프레미스 환경에서 리소스 제약이 있어 대부분 Rolling Update를 사용했습니다. 다만 결제 시스템 같은 핵심 서비스는 Blue-Green으로 배포했고, 전환 전 QA팀이 Green 환경에서 수동 검증을 완료한 후에만 전환을 승인하는 프로세스를 운영했습니다.

**⚠️ 주의**:
"Canary가 최고"라고 단정하지 말 것. 각 전략의 트레이드오프를 명확히 하고, 서비스 특성에 따라 선택한다는 점을 강조.

---

### Q: "Canary 배포에서 자동 롤백은 어떻게 구현하나요?"

**30초 답변**:
Argo Rollouts의 AnalysisTemplate을 사용합니다. Prometheus에서 HTTP 성공률, P99 지연시간, 에러 수 같은 메트릭을 주기적으로 조회하고, 성공 조건(예: 성공률 95% 이상)을 만족하지 못하면 자동으로 Canary를 abort하고 Stable 버전으로 롤백합니다.

**2분 답변**:
Argo Rollouts는 AnalysisTemplate이라는 CRD로 자동 롤백 조건을 선언적으로 정의합니다. Rollout의 canary.analysis 필드에 AnalysisTemplate을 지정하면, 각 Canary 단계에서 AnalysisRun이 생성되어 메트릭을 검증합니다. AnalysisTemplate에는 여러 메트릭을 정의할 수 있습니다. 가장 기본적인 것은 HTTP 성공률로, Prometheus에서 status 2xx 요청 비율을 쿼리합니다. successCondition에 "result >= 0.95"를 설정하면 95% 미만일 때 실패로 판정합니다. failureLimit으로 연속 실패 허용 횟수를 지정하고, interval로 체크 주기를 설정합니다. 성공률 외에도 P99 응답 시간(500ms 미만), 에러 로그 수(5분간 10건 미만) 등 복합 조건을 설정할 수 있습니다. 모든 메트릭이 성공해야 다음 단계로 진행하고, 하나라도 failureLimit을 초과하면 전체 Rollout이 abort됩니다. Provider로는 Prometheus 외에도 Datadog, New Relic, CloudWatch, 심지어 Kubernetes Job(커스텀 테스트 스크립트)도 사용할 수 있습니다. Blue-Green에서는 prePromotionAnalysis로 전환 전 검증, postPromotionAnalysis로 전환 후 검증을 분리할 수 있습니다. 핵심은 "사람이 대시보드를 보고 판단"하는 것이 아니라 "메트릭 기준을 사전에 정의하고 자동으로 판단"하는 것입니다.

**💡 경험 연결**:
수동 Canary 배포를 하다가 담당자가 퇴근한 사이에 에러율이 올라간 사고가 있었습니다. 이후 AnalysisTemplate으로 자동 롤백을 구현하여 업무 시간 외에도 안전한 배포가 가능해졌습니다.

**⚠️ 주의**:
AnalysisTemplate의 메트릭 기준값(threshold)을 어떻게 정하는지도 준비할 것. "정상 상태의 baseline을 측정하고, 그 기준에서 허용 범위를 정한다"가 정답.

---

### Q: "DB 스키마 변경이 있을 때 배포 전략은?"

**30초 답변**:
Expand-Contract 패턴을 사용합니다. Phase 1에서 새 컬럼을 추가하되 기존 컬럼은 유지합니다. Phase 2에서 새 버전 코드를 배포하고 Dual Write로 양쪽 컬럼에 기록합니다. Phase 3에서 새 버전이 안정화된 후 이전 컬럼을 삭제합니다. 이렇게 하면 어느 단계에서든 롤백이 가능합니다.

**2분 답변**:
DB 스키마 변경을 포함한 배포는 가장 위험한 시나리오 중 하나입니다. 핵심 원칙은 Backward Compatible Migration, 즉 하위 호환성을 유지하는 것입니다. 컬럼 추가는 안전하지만, 컬럼 삭제나 이름 변경은 Expand-Contract 패턴이 필요합니다. 구체적으로 Phase 1(Expand)에서 새 컬럼을 추가합니다. 이 시점에서 v1 코드는 새 컬럼을 모르지만, 새 컬럼에 DEFAULT 값이 있으면 문제가 없습니다. ArgoCD Sync Wave의 PreSync Hook으로 Migration Job을 실행합니다. Phase 2(Migrate)에서 v2 코드를 배포합니다. v2는 새 컬럼을 사용하면서 이전 컬럼에도 쓰기(Dual Write)를 합니다. 이 단계에서 롤백하면 v1이 이전 컬럼에서 데이터를 읽을 수 있으므로 안전합니다. Canary나 Blue-Green으로 배포하면 v1과 v2가 공존할 때도 데이터 정합성이 유지됩니다. Phase 3(Contract)에서 v2가 충분히 안정화된 후(보통 1-2주) 이전 컬럼을 삭제합니다. 이 시점부터는 v1으로의 롤백이 불가능하므로 신중하게 결정합니다. 배포 전략은 Blue-Green이 가장 안전합니다. Green 환경에서 Migration을 실행하고 검증한 후 트래픽을 전환하면, 문제 발생 시 Blue(이전 버전+이전 스키마)로 즉시 롤백할 수 있습니다.

**💡 경험 연결**:
테이블 컬럼 이름을 변경하는 배포에서 한 번에 삭제+추가를 했다가 롤백 시 데이터 손실이 발생한 경험이 있습니다. 이후 Expand-Contract 패턴을 도입하여 모든 스키마 변경을 3단계로 분리했습니다.

**⚠️ 주의**:
"Canary로 배포하면 됩니다"라고 단순화하지 말 것. DB 스키마 변경은 배포 전략만의 문제가 아니라 데이터 마이그레이션 전략의 문제라는 점을 강조.

---

### Q: "Argo Rollouts를 ArgoCD와 함께 사용하는 이유는?"

**30초 답변**:
ArgoCD는 Git과 클러스터 상태를 동기화하는 GitOps 도구이고, Argo Rollouts는 배포 과정 자체를 제어하는 Progressive Delivery 도구입니다. ArgoCD가 Git 변경을 감지하여 Sync하면, Argo Rollouts가 Canary/Blue-Green 방식으로 안전하게 배포하고, AnalysisTemplate으로 메트릭 기반 자동 롤백까지 처리합니다.

**2분 답변**:
ArgoCD와 Argo Rollouts는 보완적 관계입니다. ArgoCD는 "무엇을 배포할 것인가"(Git의 Desired State)를 관리하고, Argo Rollouts는 "어떻게 안전하게 배포할 것인가"(Progressive Delivery)를 관리합니다. 이 둘이 없으면 CI에서 kubectl apply로 직접 배포하는 Push 모델이 됩니다. ArgoCD만 사용하면 GitOps의 이점(Drift Detection, Self-heal, Audit)은 얻지만, 배포 자체는 K8s 기본 Rolling Update만 사용하게 됩니다. Argo Rollouts를 추가하면 Canary의 단계별 트래픽 제어와 메트릭 기반 자동 판단이 가능해집니다. 통합 워크플로우는 이렇습니다. 개발자가 이미지 태그를 매니페스트 저장소에 Push하면, ArgoCD가 변경을 감지하여 Sync합니다. Sync 대상이 Rollout CRD이므로 Argo Rollouts Controller가 Canary 배포를 시작합니다. 각 단계에서 AnalysisRun이 Prometheus 메트릭을 검증하고, 통과하면 다음 단계로, 실패하면 자동 롤백합니다. ArgoCD UI에서 Rollout의 Canary 진행 상태와 Health를 한눈에 확인할 수 있습니다. 이렇게 하면 Git Push부터 안전한 프로덕션 배포까지 완전 자동화된 파이프라인이 완성됩니다.

**💡 경험 연결**:
ArgoCD만 사용하던 환경에서 프로덕션 배포 후 에러율이 급등하여 수동으로 롤백한 경험이 있습니다. Argo Rollouts를 도입하여 5%→10%→30%→60%→100%의 Canary 단계를 적용했고, 10% 단계에서 문제가 감지되면 자동으로 롤백되도록 개선했습니다.

**⚠️ 주의**:
"ArgoCD에 Canary 기능이 있나요?"라는 후속 질문에 대비할 것. ArgoCD 자체에는 Canary 기능이 없고, Argo Rollouts가 별도 프로젝트라는 점을 명확히.

---

## Allganize 맥락

- **Alli AI 모델 배포**: LLM 모델 교체 시 Canary로 정확도/응답시간 메트릭을 검증하며 점진적으로 전환하면 안전하다
- **마이크로서비스**: API, Web, Worker 서비스별로 다른 배포 전략을 적용할 수 있다. API는 Canary, Web은 Blue-Green이 적합하다
- **AWS/Azure 멀티클라우드**: Argo Rollouts는 Nginx Ingress, AWS ALB, Istio 등 다양한 트래픽 라우터를 지원하여 클라우드별 최적 선택 가능
- **메트릭 기반 자동화**: Prometheus + AnalysisTemplate으로 "사람이 대시보드를 보고 판단"하는 것에서 "자동으로 판단하고 롤백"하는 것으로 진화
- **면접 포인트**: 전략별 트레이드오프를 명확히 하고, Argo Rollouts의 AnalysisTemplate까지 설명하면 실무 수준의 깊이를 보여줄 수 있다

---
**핵심 키워드**: `Rolling Update` `Blue-Green` `Canary` `Argo Rollouts` `AnalysisTemplate` `Progressive Delivery` `Expand-Contract`
