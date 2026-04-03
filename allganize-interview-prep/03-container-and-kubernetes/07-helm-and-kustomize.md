# 07. Helm과 Kustomize (Helm and Kustomize)

> **TL;DR**
> - **Helm**은 K8s의 패키지 매니저로, 템플릿 + values.yaml로 복잡한 앱을 한 번에 배포한다.
> - **Kustomize**는 원본 YAML 수정 없이 **overlay 패턴**으로 환경별 설정을 관리한다.
> - Helm은 **제3자 앱 배포**, Kustomize는 **자체 앱의 환경별 설정**에 각각 강점이 있다.

---

## 1. 왜 패키지 관리가 필요한가?

하나의 마이크로서비스를 배포하려면 **여러 K8s 리소스**가 필요하다.

```
하나의 서비스 배포에 필요한 리소스:
  Deployment + Service + Ingress + ConfigMap + Secret +
  HPA + PDB + NetworkPolicy + ServiceAccount + ...
```

이걸 환경(dev/staging/prod)마다 수동 관리하면 **실수와 불일치**가 발생한다.

---

## 2. Helm

### 2-1. Helm Chart 구조

```
mychart/
├── Chart.yaml              # 차트 메타데이터 (이름, 버전)
├── values.yaml             # 기본 설정값
├── charts/                 # 의존 차트 (서브차트)
├── templates/              # K8s 매니페스트 템플릿
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── hpa.yaml
│   ├── _helpers.tpl        # 재사용 템플릿 함수
│   ├── NOTES.txt           # 설치 후 안내 메시지
│   └── tests/
│       └── test-connection.yaml
└── .helmignore
```

### Chart.yaml

```yaml
apiVersion: v2
name: web-api
description: Web API 서비스
type: application
version: 1.2.0               # 차트 버전
appVersion: "2.1.0"           # 앱 버전
dependencies:
- name: redis
  version: "17.x.x"
  repository: "https://charts.bitnami.com/bitnami"
  condition: redis.enabled
```

### 2-2. values.yaml

```yaml
# values.yaml: 기본 설정값
replicaCount: 2

image:
  repository: web-api
  tag: "2.1.0"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 80

ingress:
  enabled: true
  className: nginx
  hosts:
  - host: api.example.com
    paths:
    - path: /
      pathType: Prefix
  tls:
  - secretName: api-tls
    hosts:
    - api.example.com

resources:
  requests:
    cpu: "250m"
    memory: "256Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70

# 환경별 오버라이드
env:
  DATABASE_HOST: "postgres-svc"
  LOG_LEVEL: "info"

# 폐쇄망용: 내부 레지스트리 설정
imageRegistry: "registry.internal.local"
```

### 2-3. 템플릿 문법

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "web-api.fullname" . }}
  labels:
    {{- include "web-api.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "web-api.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "web-api.selectorLabels" . | nindent 8 }}
    spec:
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.imageRegistry | default "" }}{{ if .Values.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        ports:
        - containerPort: 8080
        resources:
          {{- toYaml .Values.resources | nindent 10 }}
        env:
        {{- range $key, $value := .Values.env }}
        - name: {{ $key }}
          value: {{ $value | quote }}
        {{- end }}
```

```yaml
# templates/_helpers.tpl
{{- define "web-api.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "web-api.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "web-api.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

### 2-4. Helm 명령어

```bash
# 차트 생성
helm create mychart

# 템플릿 렌더링 확인 (실제 배포 전 확인 필수)
helm template my-release ./mychart -f values-prod.yaml

# 설치
helm install my-release ./mychart \
  -f values-prod.yaml \
  -n production --create-namespace

# 환경별 values 파일로 오버라이드
helm install my-release ./mychart \
  -f values.yaml \
  -f values-prod.yaml \
  --set image.tag="2.2.0"

# 업그레이드
helm upgrade my-release ./mychart \
  -f values-prod.yaml \
  --set image.tag="2.2.0"

# 릴리즈 히스토리
helm history my-release -n production

# 롤백
helm rollback my-release 1 -n production

# 릴리즈 목록
helm list -n production

# 삭제
helm uninstall my-release -n production

# Dry-run (실제 적용하지 않고 확인)
helm install my-release ./mychart --dry-run --debug
```

### 2-5. 폐쇄망에서 Helm 사용

```bash
# 1. 차트를 tar로 패키징
helm package ./mychart
# mychart-1.2.0.tgz 생성

# 2. 내부 Helm 레포지토리 구성 (ChartMuseum 또는 Harbor)
helm repo add internal https://charts.internal.local
helm push mychart-1.2.0.tgz internal

# 3. 의존성 차트 미리 다운로드
helm dependency update ./mychart
# charts/ 디렉토리에 서브차트 다운로드됨

# 4. 오프라인 설치
helm install my-release ./mychart-1.2.0.tgz \
  -f values-airgapped.yaml \
  --set imageRegistry=registry.internal.local
```

---

## 3. Kustomize

### 3-1. 디렉토리 구조

```
app/
├── base/                        # 공통 리소스 (원본)
│   ├── kustomization.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
├── overlays/                    # 환경별 오버라이드
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   ├── replica-patch.yaml
│   │   └── configmap-patch.yaml
│   ├── staging/
│   │   ├── kustomization.yaml
│   │   └── replica-patch.yaml
│   └── prod/
│       ├── kustomization.yaml
│       ├── replica-patch.yaml
│       ├── hpa.yaml
│       └── resource-patch.yaml
```

### 3-2. Base

```yaml
# base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- deployment.yaml
- service.yaml
- configmap.yaml

commonLabels:
  app: web-api

configMapGenerator:
- name: app-config
  literals:
  - LOG_LEVEL=info
  - APP_MODE=default
```

```yaml
# base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: web-api
  template:
    metadata:
      labels:
        app: web-api
    spec:
      containers:
      - name: api
        image: web-api:latest
        ports:
        - containerPort: 8080
        envFrom:
        - configMapRef:
            name: app-config
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
```

### 3-3. Overlay (환경별 오버라이드)

```yaml
# overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../../base
- hpa.yaml                      # prod 전용 리소스 추가

namespace: production            # 모든 리소스에 namespace 지정

namePrefix: prod-                # 리소스 이름에 접두사

commonLabels:
  env: production

images:
- name: web-api
  newName: registry.internal.local/web-api   # 이미지 경로 변경
  newTag: "2.1.0"                             # 태그 변경

patches:
- path: replica-patch.yaml
- path: resource-patch.yaml

configMapGenerator:
- name: app-config
  behavior: merge                # base 설정에 병합
  literals:
  - LOG_LEVEL=warn
  - APP_MODE=production
  - DATABASE_HOST=postgres-prod.svc
```

```yaml
# overlays/prod/replica-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-api
spec:
  replicas: 5
```

```yaml
# overlays/prod/resource-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-api
spec:
  template:
    spec:
      containers:
      - name: api
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "1000m"
            memory: "1Gi"
```

```yaml
# overlays/prod/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-api
  minReplicas: 5
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### 3-4. Kustomize 명령어

```bash
# 렌더링 결과 확인 (적용 전 확인)
kubectl kustomize overlays/prod

# 직접 적용
kubectl apply -k overlays/prod

# diff 확인
kubectl diff -k overlays/prod

# 삭제
kubectl delete -k overlays/prod

# kustomize CLI (독립 실행)
kustomize build overlays/prod | kubectl apply -f -
```

---

## 4. Helm vs Kustomize 비교

| 항목 | Helm | Kustomize |
|------|------|-----------|
| **접근 방식** | 템플릿 엔진 (Go template) | Overlay 패치 |
| **패키지 관리** | Chart 패키지, 버전 관리 | 없음 (파일 기반) |
| **릴리즈 관리** | 릴리즈 이력, 롤백 기본 지원 | 없음 (kubectl 기반) |
| **학습 곡선** | Go 템플릿 문법 학습 | YAML만 알면 됨 |
| **3rd party 앱** | Helm repo에서 설치 | 직접 YAML 관리 |
| **kubectl 통합** | 별도 CLI (helm) | `kubectl -k` 내장 |
| **GitOps 호환** | Helm Controller 필요 | 네이티브 호환 |
| **디버깅** | `helm template`로 렌더링 | `kubectl kustomize`로 확인 |

### 언제 무엇을 쓰는가?

```
Helm을 쓸 때:
  - 제3자 앱 설치 (Prometheus, Nginx Ingress, Cert-Manager 등)
  - 복잡한 조건부 로직이 필요할 때
  - 릴리즈 버전 관리/롤백이 중요할 때
  - 내부 공통 라이브러리 차트 배포

Kustomize를 쓸 때:
  - 자체 앱의 환경별(dev/staging/prod) 설정 관리
  - 원본 YAML을 수정하지 않고 패치만 적용할 때
  - 단순한 이미지 태그/replica 변경
  - GitOps 파이프라인과 통합할 때

둘을 함께 쓸 때 (권장 패턴):
  - Helm으로 차트 렌더링 → Kustomize로 환경별 패치
  - helm template | kustomize edit
```

---

## 5. 실전 패턴: Helm + Kustomize 조합

```bash
# Helm으로 렌더링 → Kustomize base로 사용
helm template my-release bitnami/redis \
  --version 17.0.0 \
  -f redis-values.yaml \
  > base/redis-all.yaml
```

```yaml
# base/kustomization.yaml
resources:
- redis-all.yaml          # Helm 렌더링 결과

# overlays/prod/kustomization.yaml
resources:
- ../../base
patches:
- target:
    kind: StatefulSet
    name: my-release-redis-master
  patch: |
    - op: replace
      path: /spec/replicas
      value: 3
```

### ArgoCD에서의 활용

```yaml
# ArgoCD Application에서 Helm
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: web-api
spec:
  source:
    repoURL: https://git.internal.local/team/web-api.git
    path: helm-chart
    helm:
      valueFiles:
      - values-prod.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: production
---
# ArgoCD Application에서 Kustomize
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: web-api-kustomize
spec:
  source:
    repoURL: https://git.internal.local/team/web-api.git
    path: kustomize/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: production
```

---

## 6. 폐쇄망에서의 패키지 관리 전략

```
┌─── 외부망 (개발자 PC) ───────────────┐
│                                       │
│  helm pull bitnami/redis --untar     │
│  helm dependency update              │
│  → 차트 + 이미지 tar 패키징          │
│                                       │
└──────────┬────────────────────────────┘
           │ USB / 내부 전송
           ▼
┌─── 내부망 (폐쇄망) ─────────────────┐
│                                       │
│  Harbor: Helm 차트 + 컨테이너 이미지  │
│  Git:    Kustomize overlay 관리       │
│  ArgoCD: GitOps 자동 배포             │
│                                       │
└───────────────────────────────────────┘
```

```bash
# 차트 + 이미지 일괄 패키징 스크립트
#!/bin/bash
CHART_DIR="./charts"
IMAGE_DIR="./images"
mkdir -p $CHART_DIR $IMAGE_DIR

# Helm 차트 다운로드
helm pull prometheus-community/kube-prometheus-stack \
  --version 45.0.0 -d $CHART_DIR

# 차트에서 사용하는 이미지 목록 추출
helm template test $CHART_DIR/kube-prometheus-stack-45.0.0.tgz \
  | grep "image:" | sort -u | awk '{print $2}' | tr -d '"' \
  > image-list.txt

# 이미지 다운로드
while read img; do
  filename=$(echo $img | tr '/:' '_')
  docker pull $img
  docker save $img -o "$IMAGE_DIR/${filename}.tar"
done < image-list.txt

# 내부망에서 로드
for f in $IMAGE_DIR/*.tar; do
  docker load -i $f
  # 내부 레지스트리에 push
done
```

---

## 면접 Q&A

### Q1. "Helm과 Kustomize의 차이점과 각각 언제 사용하나요?"

> **이렇게 대답한다:**
> "**Helm**은 Go 템플릿 기반 패키지 매니저로, values.yaml로 파라미터를 주입하고 릴리즈 버전 관리/롤백을 지원합니다. **Kustomize**는 원본 YAML을 수정하지 않고 overlay 패치로 환경별 설정을 관리합니다. 실무에서는 Prometheus, Nginx Ingress 같은 **제3자 앱은 Helm**으로 설치하고, 자체 서비스의 **dev/staging/prod 환경 분리는 Kustomize**로 관리합니다. ArgoCD와 함께 GitOps를 구성할 때 두 도구를 조합하여 사용합니다."

### Q2. "Helm Chart를 직접 만들어본 적 있나요?"

> **이렇게 대답한다:**
> "네, `helm create`로 스캐폴딩 후 **values.yaml에 환경별 변수**(이미지, 리소스, 레플리카 등)를 정의하고, 조건부 렌더링으로 HPA나 Ingress를 선택적 활성화했습니다. `_helpers.tpl`에 공통 라벨과 이름 규칙을 정의하여 일관성을 유지했습니다. 폐쇄망에서는 **imageRegistry 변수**를 추가하여 내부 레지스트리를 기본값으로 사용하도록 설계했습니다."

### Q3. "폐쇄망에서 Helm Chart는 어떻게 관리하나요?"

> **이렇게 대답한다:**
> "외부에서 `helm pull`로 차트를 다운로드하고, 의존성 차트도 `helm dependency update`로 함께 받습니다. 차트가 사용하는 **컨테이너 이미지도 함께 패키징**하여 내부망으로 전달합니다. 내부에는 **Harbor**를 설치하여 Helm 차트 저장소와 컨테이너 레지스트리를 함께 운영합니다. values.yaml에서 이미지 경로를 내부 레지스트리로 오버라이드하여 배포합니다."

### Q4. "Kustomize의 overlay 패턴을 설명해주세요."

> **이렇게 대답한다:**
> "**base 디렉토리**에 공통 YAML을 두고, **overlays 디렉토리**에 환경별(dev/staging/prod) 패치를 정의합니다. overlay에서는 이미지 태그 변경, 레플리카 수 조정, 리소스 한도 변경, 환경 변수 추가 등을 **원본을 수정하지 않고** 패치합니다. `kubectl apply -k overlays/prod` 한 줄로 적용되므로 GitOps에 자연스럽게 통합되고, git diff로 환경 간 **차이점을 명확히 확인**할 수 있는 것이 큰 장점입니다."

---

`#Helm` `#Kustomize` `#Chart` `#Overlay패턴` `#패키지관리`
