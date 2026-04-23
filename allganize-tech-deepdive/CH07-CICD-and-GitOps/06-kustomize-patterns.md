# Kustomize 패턴 (Kustomize Patterns)

> **TL;DR**
> - Kustomize는 base/overlay 패턴으로 환경별 K8s 매니페스트를 템플릿 없이 순수 YAML 오버레이 방식으로 관리한다
> - Strategic Merge Patch와 JSON Patch로 기존 리소스를 부분 수정하고, ConfigMap/Secret Generator로 변경 시 자동 롤링 업데이트를 지원한다
> - Helm은 패키지 배포용, Kustomize는 환경별 설정 관리용으로 상호 보완적이며, ArgoCD에서 둘 다 네이티브로 지원한다

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 20min

---

## 핵심 개념

### Kustomize란?

Kustomize는 K8s 네이티브 설정 관리 도구이다. Helm처럼 템플릿 엔진을 사용하지 않고, 순수 YAML 파일을 오버레이(Overlay) 방식으로 합성(Compose)하여 환경별 매니페스트를 생성한다. kubectl에 내장되어 있어 별도 설치가 필요 없다.

```
Kustomize의 핵심 철학:

┌──────────────────────────────────────────────────────────┐
│  "Template-free configuration customization"              │
│                                                          │
│  Helm:     values.yaml  → {{ .Values.xxx }}  → 최종 YAML│
│            (변수 치환)    (Go Template)                   │
│                                                          │
│  Kustomize: base YAML   → patch / overlay  → 최종 YAML  │
│            (순수 YAML)    (YAML 합성)                     │
│                                                          │
│  장점:                                                    │
│  ● base 파일이 유효한 K8s YAML (그대로 kubectl apply 가능)│
│  ● 템플릿 문법 학습 불필요                                 │
│  ● kubectl에 내장 (kubectl apply -k)                      │
│  ● Git diff로 변경 내용을 직관적으로 확인 가능             │
└──────────────────────────────────────────────────────────┘
```

### base/overlay 패턴

```
alli-api/
├── base/                          # 환경 공통 (기본 리소스)
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── ingress.yaml
│
└── overlays/                      # 환경별 오버라이드
    ├── dev/
    │   ├── kustomization.yaml
    │   ├── patch-replicas.yaml    # replicas: 1
    │   └── patch-resources.yaml   # 작은 리소스
    │
    ├── staging/
    │   ├── kustomization.yaml
    │   ├── patch-replicas.yaml    # replicas: 2
    │   └── configmap-env.yaml     # 스테이징 환경 변수
    │
    └── production/
        ├── kustomization.yaml
        ├── patch-replicas.yaml    # replicas: 4
        ├── patch-resources.yaml   # 큰 리소스
        ├── patch-hpa.yaml         # HPA 추가
        └── ingress-patch.yaml     # 프로덕션 도메인
```

### base 파일 예시

```yaml
# base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml

commonLabels:
  app.kubernetes.io/name: alli-api
  app.kubernetes.io/part-of: alli-platform
```

```yaml
# base/deployment.yaml (순수 K8s YAML)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api
spec:
  replicas: 2
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
        image: ghcr.io/allganize/alli-api:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
        env:
        - name: LOG_LEVEL
          value: "info"
        - name: DB_HOST
          valueFrom:
            configMapKeyRef:
              name: alli-api-config
              key: db-host
```

```yaml
# base/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: alli-api
spec:
  selector:
    app: alli-api
  ports:
  - port: 80
    targetPort: 8080
```

```yaml
# base/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alli-api-config
data:
  db-host: "mongodb.default.svc"
  cache-ttl: "300"
  log-format: "json"
```

### overlay 파일 예시 (production)

```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# base 참조
resources:
  - ../../base

# 네임스페이스 지정
namespace: alli-api-prod

# 이름 접두사/접미사
namePrefix: prod-

# 공통 라벨 추가
commonLabels:
  env: production
  team: backend

# 공통 어노테이션
commonAnnotations:
  managed-by: argocd

# 이미지 태그 오버라이드 (가장 많이 사용)
images:
  - name: ghcr.io/allganize/alli-api
    newTag: v2.1.0
    # newName: 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/alli-api  # 레지스트리 변경

# ConfigMap/Secret Generator
configMapGenerator:
  - name: alli-api-config
    behavior: merge                # base의 ConfigMap과 병합
    literals:
      - db-host=mongodb-prod.alli-api-prod.svc
      - cache-ttl=600
      - log-format=json

# Secret Generator
secretGenerator:
  - name: alli-api-secret
    literals:
      - api-key=ENCRYPTED_VALUE
    type: Opaque

# 패치 적용
patches:
  # Strategic Merge Patch (파일)
  - path: patch-replicas.yaml
  - path: patch-resources.yaml
  - path: patch-hpa.yaml

  # Inline Strategic Merge Patch
  - patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: alli-api
      spec:
        template:
          spec:
            containers:
            - name: alli-api
              env:
              - name: LOG_LEVEL
                value: "warn"

  # JSON Patch (특정 필드만 정밀 수정)
  - target:
      group: apps
      version: v1
      kind: Deployment
      name: alli-api
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/resources/requests/cpu
        value: "1000m"
      - op: replace
        path: /spec/template/spec/containers/0/resources/limits/cpu
        value: "2000m"
```

```yaml
# overlays/production/patch-replicas.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api
spec:
  replicas: 4
```

```yaml
# overlays/production/patch-resources.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api
spec:
  template:
    spec:
      containers:
      - name: alli-api
        resources:
          requests:
            cpu: 1000m
            memory: 1Gi
          limits:
            cpu: 2000m
            memory: 2Gi
```

```yaml
# overlays/production/patch-hpa.yaml
# 새 리소스 추가 (base에 없는 리소스)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: alli-api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: alli-api
  minReplicas: 4
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### Strategic Merge Patch vs JSON Patch

```
┌──────────────────────────────────────────────────────────────┐
│          패치 방식 비교                                        │
│                                                              │
│  Strategic Merge Patch (기본)                                 │
│  ● K8s 리소스 구조를 이해하고 "똑똑하게" 머지                  │
│  ● 배열은 키 필드(name 등)로 매칭하여 머지                     │
│  ● 직관적이고 읽기 쉬움                                       │
│  ● 대부분의 경우에 적합                                       │
│                                                              │
│  예시: containers의 name으로 매칭                              │
│  patch:                                                      │
│    spec:                                                     │
│      template:                                               │
│        spec:                                                 │
│          containers:                                         │
│          - name: alli-api        # name으로 기존 컨테이너 매칭│
│            resources:                                        │
│              requests:                                       │
│                cpu: 1000m        # 이 값만 변경               │
│                                                              │
│  JSON Patch (RFC 6902)                                       │
│  ● 경로(path)와 연산(op)으로 정밀 수정                        │
│  ● 배열 인덱스로 직접 접근 가능                                │
│  ● 추가(add), 삭제(remove), 교체(replace) 연산                │
│  ● Strategic Merge로 안 되는 경우에 사용                      │
│                                                              │
│  예시:                                                       │
│  - op: replace                                               │
│    path: /spec/template/spec/containers/0/resources/limits/cpu│
│    value: "2000m"                                            │
│  - op: add                                                   │
│    path: /spec/template/spec/containers/0/env/-              │
│    value:                                                    │
│      name: NEW_VAR                                           │
│      value: "new-value"                                      │
│  - op: remove                                                │
│    path: /spec/template/spec/containers/0/env/2              │
└──────────────────────────────────────────────────────────────┘
```

### ConfigMap/Secret Generator

Kustomize의 Generator는 ConfigMap/Secret 생성 시 이름에 해시 접미사(suffix)를 추가한다. 내용이 변경되면 이름이 변경되고, 이를 참조하는 Deployment가 자동으로 롤링 업데이트된다.

```yaml
# kustomization.yaml
configMapGenerator:
  # 리터럴 값
  - name: alli-api-config
    literals:
      - db-host=mongodb-prod.svc
      - cache-ttl=600

  # 파일에서 생성
  - name: alli-api-nginx-conf
    files:
      - nginx.conf                 # 파일 이름이 key, 내용이 value
      - custom-key=my-config.txt   # key 이름 지정

  # 환경 파일에서 생성
  - name: alli-api-env
    envs:
      - .env.production            # KEY=VALUE 형식 파일

secretGenerator:
  - name: alli-api-secret
    literals:
      - db-password=s3cr3t
    type: Opaque

# 해시 접미사 비활성화 (ArgoCD에서 필요한 경우)
generatorOptions:
  disableNameSuffixHash: true      # 해시 접미사 제거
  labels:
    generated-by: kustomize
  annotations:
    note: "auto-generated"
```

```
해시 접미사 동작 원리:

1. configMapGenerator로 ConfigMap 생성
   → alli-api-config-g5hft2m7c8  (해시 접미사 자동 추가)

2. Deployment가 이 ConfigMap을 참조
   → envFrom.configMapRef.name: alli-api-config-g5hft2m7c8

3. ConfigMap 내용 변경 시
   → 새 이름: alli-api-config-k8t2d4m9h5
   → Deployment의 참조도 변경 → Pod 재생성 (Rolling Update)

장점: ConfigMap 변경 시 별도 작업 없이 Pod가 재시작된다
문제: ArgoCD에서 매번 새 ConfigMap이 생성되므로 Prune 설정 필요
```

### Components (재사용 가능한 설정 조각)

Kustomize v3.7+에서 도입된 Components는 여러 overlay에서 공통으로 사용하는 설정을 모듈화한다.

```
alli-api/
├── base/
│   └── kustomization.yaml
├── components/                    # 재사용 가능한 설정 조각
│   ├── monitoring/                # 프로메테우스 annotation 추가
│   │   └── kustomization.yaml
│   ├── istio-sidecar/             # Istio sidecar 설정
│   │   └── kustomization.yaml
│   └── resource-limits-large/     # 대규모 리소스 설정
│       └── kustomization.yaml
└── overlays/
    ├── dev/
    │   └── kustomization.yaml     # base + monitoring
    ├── staging/
    │   └── kustomization.yaml     # base + monitoring + istio
    └── production/
        └── kustomization.yaml     # base + monitoring + istio + large
```

```yaml
# components/monitoring/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component

patches:
  - patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: alli-api
      spec:
        template:
          metadata:
            annotations:
              prometheus.io/scrape: "true"
              prometheus.io/port: "8080"
              prometheus.io/path: "/metrics"
```

```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

components:
  - ../../components/monitoring
  - ../../components/istio-sidecar
  - ../../components/resource-limits-large

namespace: alli-api-prod
images:
  - name: ghcr.io/allganize/alli-api
    newTag: v2.1.0
```

### Helm vs Kustomize 비교

```
┌──────────────────┬────────────────────┬────────────────────┐
│                  │ Helm               │ Kustomize          │
├──────────────────┼────────────────────┼────────────────────┤
│ 방식             │ Template (Go Tmpl) │ Overlay (YAML 합성)│
│ 학습 곡선        │ 중간 (템플릿 문법)  │ 낮음 (순수 YAML)   │
│ 패키지 관리      │ ✅ Chart Repository│ ❌ 없음            │
│ 의존성 관리      │ ✅ dependencies    │ ❌ 없음            │
│ 릴리스 관리      │ ✅ helm history    │ ❌ 없음            │
│ 롤백             │ ✅ helm rollback   │ git revert         │
│ 환경별 설정      │ values 파일        │ overlay 디렉토리   │
│ kubectl 내장     │ ❌ 별도 설치       │ ✅ kubectl -k      │
│ base 파일 유효성 │ ❌ 템플릿 문법     │ ✅ 유효한 K8s YAML │
│ Hook             │ ✅ 내장           │ ❌ 없음            │
│ 테스트           │ ✅ helm test      │ ❌ 없음            │
│ 커뮤니티 Chart   │ ✅ 풍부           │ ❌ 없음            │
│ ArgoCD 지원      │ ✅ 네이티브       │ ✅ 네이티브        │
├──────────────────┼────────────────────┼────────────────────┤
│ 적합한 용도      │ 서드파티 앱 설치    │ 자체 앱 환경별 관리│
│                  │ 패키지 배포        │ 환경 간 차이 관리  │
│                  │ 복잡한 조건부 로직  │ 간단한 오버라이드  │
└──────────────────┴────────────────────┴────────────────────┘

실무 조합 패턴:
● Helm으로 서드파티 앱 설치 (Prometheus, ArgoCD, Nginx Ingress)
● Kustomize로 자체 앱의 환경별 설정 관리
● ArgoCD에서 둘 다 네이티브로 지원하므로 혼용 가능
```

---

## 실전 예시

### Kustomize 명령어

```bash
# ── 빌드 (렌더링) ──
kustomize build overlays/production            # 최종 YAML 출력
kustomize build overlays/production | kubectl apply -f -

# kubectl 내장 명령어 (동일 기능)
kubectl apply -k overlays/production           # 직접 적용
kubectl diff -k overlays/production            # 차이 확인 (적용 전)
kubectl delete -k overlays/production          # 삭제
kubectl get -k overlays/production             # 리소스 조회

# ── 빌드 결과를 파일로 저장 ──
kustomize build overlays/production > rendered.yaml

# ── 이미지 태그 변경 (CI에서 사용) ──
cd overlays/production
kustomize edit set image ghcr.io/allganize/alli-api=ghcr.io/allganize/alli-api:abc1234

# ── 네임스페이스 변경 ──
kustomize edit set namespace alli-api-prod

# ── 라벨 추가 ──
kustomize edit add label env:production

# ── 리소스 추가 ──
kustomize edit add resource ../hpa.yaml
```

### CI에서 이미지 태그 업데이트 (GitOps 연계)

```yaml
# GitHub Actions에서 Kustomize 이미지 태그 업데이트
- name: Update image tag in manifest repo
  run: |
    git clone https://github.com/allganize/k8s-manifests.git
    cd k8s-manifests/apps/alli-api/overlays/production

    # kustomize edit으로 이미지 태그 변경
    kustomize edit set image \
      ghcr.io/allganize/alli-api=ghcr.io/allganize/alli-api:${{ github.sha }}

    # 변경 커밋
    git add kustomization.yaml
    git commit -m "chore(alli-api): update image to ${{ github.sha }}"
    git push
```

### ArgoCD에서 Kustomize 사용

```yaml
# ArgoCD Application (Kustomize 기반)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: alli-api-production
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/allganize/k8s-manifests.git
    targetRevision: main
    path: apps/alli-api/overlays/production    # overlay 경로
    # kustomize 추가 설정 (선택)
    kustomize:
      namePrefix: prod-
      commonLabels:
        managed-by: argocd
      images:
        - ghcr.io/allganize/alli-api:v2.1.0   # Application CRD에서 직접 이미지 지정
  destination:
    server: https://kubernetes.default.svc
    namespace: alli-api-prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 대규모 멀티 서비스 구조

```
k8s-manifests/
├── apps/
│   ├── alli-api/
│   │   ├── base/
│   │   │   ├── kustomization.yaml
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   └── configmap.yaml
│   │   └── overlays/
│   │       ├── dev/
│   │       │   └── kustomization.yaml
│   │       ├── staging/
│   │       │   └── kustomization.yaml
│   │       └── production/
│   │           └── kustomization.yaml
│   │
│   ├── alli-web/
│   │   ├── base/
│   │   └── overlays/
│   │       ├── dev/
│   │       ├── staging/
│   │       └── production/
│   │
│   └── alli-worker/
│       ├── base/
│       └── overlays/
│
├── platform/
│   ├── monitoring/
│   │   ├── base/                  # Prometheus, Grafana
│   │   └── overlays/
│   └── logging/
│       ├── base/                  # Fluentd, Elasticsearch
│       └── overlays/
│
├── components/                    # 재사용 가능한 설정 조각
│   ├── monitoring-annotations/
│   ├── istio-sidecar/
│   └── resource-profiles/
│       ├── small/
│       ├── medium/
│       └── large/
│
└── cluster/
    ├── dev/
    │   └── kustomization.yaml     # dev 환경 전체 앱 모음
    ├── staging/
    │   └── kustomization.yaml
    └── production/
        └── kustomization.yaml
```

```yaml
# cluster/production/kustomization.yaml
# 프로덕션 환경의 모든 앱을 한 번에 관리
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../apps/alli-api/overlays/production
  - ../../apps/alli-web/overlays/production
  - ../../apps/alli-worker/overlays/production
  - ../../platform/monitoring/overlays/production
  - ../../platform/logging/overlays/production
```

### Kustomize + Helm 조합 (Post Rendering)

```bash
# Helm 렌더링 결과를 Kustomize로 후처리
helm template my-release prometheus-community/kube-prometheus-stack \
  -f values.yaml | \
  kustomize build --stdin

# 또는 Helm의 --post-renderer 옵션
helm install my-release prometheus-community/kube-prometheus-stack \
  --post-renderer ./kustomize-post-renderer.sh
```

```bash
#!/bin/bash
# kustomize-post-renderer.sh
# Helm이 렌더링한 YAML을 stdin으로 받아 Kustomize로 가공

cat > /tmp/helm-output.yaml
cat > /tmp/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - helm-output.yaml
commonLabels:
  managed-by: helm+kustomize
patches:
  - patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: prometheus-server
      spec:
        template:
          metadata:
            annotations:
              cluster-autoscaler.kubernetes.io/safe-to-evict: "true"
EOF

cd /tmp && kustomize build .
```

---

## 면접 Q&A

### Q: "Kustomize의 base/overlay 패턴을 설명해주세요"

**30초 답변**:
base 디렉토리에 환경 공통 K8s 매니페스트(Deployment, Service 등)를 정의하고, overlays 디렉토리에 환경별(dev, staging, production) 차이점만 패치로 정의합니다. kustomize build로 base와 overlay를 합성하여 최종 YAML을 생성합니다. base 파일은 유효한 K8s YAML이므로 그대로 kubectl apply할 수도 있습니다.

**2분 답변**:
base/overlay 패턴은 Kustomize의 핵심 설계입니다. base 디렉토리에는 모든 환경에서 공통으로 사용하는 K8s 리소스를 정의합니다. Deployment, Service, ConfigMap 등 순수 YAML 파일과 이들을 참조하는 kustomization.yaml을 둡니다. Helm과 달리 base 파일 자체가 유효한 K8s 매니페스트이므로, 별도 렌더링 없이 kubectl apply로 바로 적용할 수 있습니다. overlay 디렉토리에는 환경별 차이만 정의합니다. kustomization.yaml에서 `resources: [../../base]`로 base를 참조하고, patches로 변경할 부분만 기술합니다. 예를 들어 production overlay에서는 replicas를 4로, 리소스를 2배로, HPA를 추가하는 패치를 적용합니다. images 필드로 이미지 태그를 변경하고, namespace 필드로 네임스페이스를 지정합니다. 패치 방식은 두 가지입니다. Strategic Merge Patch는 K8s 리소스 구조를 이해하고 필드를 머지합니다. containers 배열에서 name 필드로 기존 컨테이너를 찾아 특정 필드만 변경할 수 있습니다. JSON Patch는 경로와 연산으로 정밀하게 수정합니다. 배열의 특정 인덱스에 접근하거나, 필드를 삭제(remove)할 때 사용합니다. 이 패턴의 장점은 환경 간 차이를 최소화하면서 명시적으로 관리한다는 점입니다. Git diff로 dev와 production의 차이가 무엇인지 한눈에 파악할 수 있습니다.

**💡 경험 연결**:
기존에 환경별로 YAML 파일을 복사하여 관리하다가, 공통 변경 시 모든 환경 파일을 수동으로 수정해야 하는 문제가 있었습니다. Kustomize의 base/overlay로 전환하면서 공통 변경은 base만, 환경별 차이는 overlay만 수정하면 되어 실수가 크게 줄었습니다.

**⚠️ 주의**:
"Kustomize는 Helm보다 좋다"라고 비교 우위를 단정하지 말 것. 용도가 다르며 상호 보완적이라는 점을 강조할 것.

---

### Q: "Helm과 Kustomize를 각각 언제 사용하나요?"

**30초 답변**:
Helm은 서드파티 앱 설치(Prometheus, ArgoCD, Nginx Ingress)와 패키지 배포에 적합합니다. Chart Repository, 의존성 관리, Hook, 롤백 기능이 필요할 때 사용합니다. Kustomize는 자체 개발 앱의 환경별 설정 관리에 적합합니다. 순수 YAML로 base/overlay를 관리하며, kubectl에 내장되어 있어 별도 도구가 필요 없습니다.

**2분 답변**:
두 도구의 설계 철학이 다릅니다. Helm은 "패키지 매니저"입니다. Chart로 복잡한 앱을 패키징하고, values로 설정을 주입하고, 릴리스 단위로 설치/업그레이드/롤백합니다. 서드파티 앱은 커뮤니티 Chart를 사용하면 복잡한 K8s 리소스를 직접 작성할 필요 없이 values.yaml 하나로 커스터마이징할 수 있습니다. 또한 Hook으로 DB Migration 같은 배포 전후 작업을 자동화하고, chart test로 설치 후 검증도 가능합니다. Kustomize는 "설정 커스터마이저"입니다. 이미 작성된 YAML을 환경별로 오버라이드하는 데 특화되어 있습니다. 템플릿 문법이 없으므로 base 파일이 유효한 K8s YAML이고, 개발자가 직접 kubectl apply로 테스트할 수 있습니다. Git diff로 변경 내용을 직관적으로 확인할 수 있어 코드 리뷰에 유리합니다. 실무에서는 조합하여 사용합니다. Prometheus 설치는 `helm install`로, 자체 마이크로서비스의 dev/staging/production 매니페스트는 Kustomize base/overlay로 관리합니다. ArgoCD에서는 Application CRD에서 source.path에 Kustomize overlay를 지정하거나, source.helm으로 Helm Chart를 지정할 수 있어 혼용이 자연스럽습니다. Helm의 렌더링 결과를 Kustomize로 후처리(post-renderer)하는 패턴도 있습니다.

**💡 경험 연결**:
사내 앱은 Kustomize로 환경별 설정을 관리하고, 인프라 컴포넌트(Prometheus, Grafana, Nginx Ingress)는 Helm Chart로 설치하는 이중 전략을 사용했습니다. ArgoCD에서 두 방식 모두 Application CRD로 관리하여 통합 대시보드에서 전체 상태를 확인할 수 있었습니다.

**⚠️ 주의**:
"Kustomize만 쓰면 됩니다" 또는 "Helm만 쓰면 됩니다"라고 하면 실무 경험이 부족해 보인다. 각각의 강점과 조합 전략을 제시할 것.

---

### Q: "Kustomize에서 ConfigMap 변경 시 Pod가 자동 재시작되는 원리는?"

**30초 답변**:
configMapGenerator로 ConfigMap을 생성하면 이름에 해시 접미사가 붙습니다. 예를 들어 `alli-api-config-g5hft2m7c8`입니다. 내용이 변경되면 해시가 바뀌어 새 이름이 생성되고, Deployment가 참조하는 ConfigMap 이름도 변경되므로 Pod가 자동으로 롤링 업데이트됩니다.

**2분 답변**:
K8s의 기본 동작에서는 ConfigMap 내용이 변경되어도 해당 ConfigMap을 참조하는 Pod가 자동으로 재시작되지 않습니다. 환경변수로 주입된 값은 Pod가 재생성될 때만 반영되므로, 설정 변경이 실시간으로 적용되지 않는 문제가 있습니다. Kustomize의 configMapGenerator는 이 문제를 해시 접미사로 해결합니다. ConfigMap을 생성할 때 내용의 해시를 이름에 추가합니다. 예를 들어 `alli-api-config-g5hft2m7c8`입니다. Deployment 템플릿에서 이 ConfigMap을 참조하면 Kustomize가 자동으로 해시 접미사가 포함된 이름으로 치환합니다. ConfigMap 내용을 변경하면 새로운 해시가 생성되어 이름이 바뀝니다. Deployment가 참조하는 이름도 변경되므로 K8s는 이를 Deployment 스펙 변경으로 인식하고 롤링 업데이트를 시작합니다. 주의할 점이 두 가지 있습니다. 첫째, 이전 ConfigMap은 orphan 리소스가 되므로 ArgoCD의 Prune 옵션이나 수동 정리가 필요합니다. 둘째, ArgoCD에서 해시 접미사 때문에 매번 OutOfSync로 감지되는 문제가 있을 수 있는데, 이 경우 `generatorOptions.disableNameSuffixHash: true`로 비활성화하고 Helm의 checksum/config 패턴으로 대체할 수 있습니다.

**💡 경험 연결**:
운영 환경에서 ConfigMap을 변경했는데 Pod에 반영이 안 되어 원인을 찾느라 시간을 소비한 경험이 있습니다. configMapGenerator의 해시 접미사 패턴을 도입한 후에는 설정 변경이 확실하게 Pod에 반영되어 이런 문제가 사라졌습니다.

**⚠️ 주의**:
해시 접미사의 장단점을 모두 언급할 것. "자동 롤링 업데이트"는 장점이지만, "orphan 리소스 정리 필요"와 "ArgoCD와의 호환 이슈"는 단점으로 인지하고 있어야 한다.

---

## Allganize 맥락

- **마이크로서비스 환경별 관리**: alli-api, alli-web, alli-worker 등 자체 서비스의 dev/staging/production 설정을 Kustomize base/overlay로 깔끔하게 분리할 수 있다
- **ArgoCD 통합**: Application CRD의 path에 overlay 경로를 지정하면 환경별 ArgoCD Application이 자동으로 올바른 설정을 사용한다
- **멀티클라우드 오버레이**: AWS 전용 overlay와 Azure 전용 overlay를 만들어 클라우드별 차이(StorageClass, Annotation, Ingress Controller)를 관리할 수 있다
- **Components 활용**: 모니터링 annotation, Istio sidecar 설정 등을 Component로 모듈화하면 서비스별 선택적 적용이 가능하다
- **면접 포인트**: base/overlay 패턴과 Strategic Merge Patch를 정확히 설명하고, Helm과의 역할 분담을 명확히 하면 실무적 판단력을 보여줄 수 있다

---
**핵심 키워드**: `Kustomize` `base/overlay` `Strategic Merge Patch` `JSON Patch` `configMapGenerator` `Components` `kubectl -k`
