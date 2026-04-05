# Helm 심화 (Helm Deep Dive)

> **TL;DR**
> - Helm은 K8s 패키지 매니저로, Chart(패키지) 단위로 복잡한 K8s 리소스를 템플릿화하여 재사용한다
> - values.yaml 오버라이드와 Go Template 함수로 환경별 설정을 유연하게 관리하고, Hook으로 배포 전후 작업을 자동화한다
> - OCI Registry(ECR, Harbor 등)에 Chart를 저장하여 이미지와 동일한 방식으로 관리하는 것이 현대적 방식이다

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Helm이란?

Helm은 K8s의 패키지 매니저이다. apt(Debian), yum(RHEL)처럼 복잡한 K8s 리소스를 하나의 패키지(Chart)로 묶어 설치, 업그레이드, 롤백을 관리한다.

```
Helm의 3가지 핵심 개념:

┌──────────────────────────────────────────────┐
│  Chart (차트)                                 │
│  → K8s 리소스의 패키지 (템플릿 + 기본값)       │
│  → 예: nginx-ingress, prometheus, argocd     │
│                                              │
│  Release (릴리스)                              │
│  → Chart의 설치 인스턴스                       │
│  → 같은 Chart를 여러 번 설치 가능              │
│  → 예: my-nginx (release name)               │
│                                              │
│  Repository (저장소)                           │
│  → Chart를 저장하고 공유하는 장소               │
│  → 예: https://charts.helm.sh/stable         │
│  → OCI Registry도 지원 (oci://...)            │
└──────────────────────────────────────────────┘
```

### Chart 디렉토리 구조

```
alli-api/                          # Chart 이름
├── Chart.yaml                     # 메타데이터 (이름, 버전, 의존성)
├── Chart.lock                     # 의존성 Lock 파일
├── values.yaml                    # 기본 설정값
├── values-dev.yaml                # 환경별 오버라이드 (선택)
├── values-production.yaml         # 환경별 오버라이드 (선택)
├── .helmignore                    # 패키징 시 제외 파일
├── templates/                     # K8s 매니페스트 템플릿
│   ├── NOTES.txt                  # 설치 후 안내 메시지
│   ├── _helpers.tpl               # 공통 템플릿 헬퍼 함수
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   ├── serviceaccount.yaml
│   └── tests/                     # Chart 테스트
│       └── test-connection.yaml
├── charts/                        # 의존 서브차트
│   └── redis/                     # (helm dependency update로 관리)
└── crds/                          # CRD 정의 (있는 경우)
```

### Chart.yaml 상세

```yaml
apiVersion: v2                     # Helm 3 (v1은 Helm 2)
name: alli-api
description: Allganize Alli API Service Helm Chart
type: application                  # application 또는 library

version: 1.2.3                     # Chart 버전 (SemVer 필수)
appVersion: "2.1.0"                # 앱 버전 (정보 표시용)

# 의존성 (서브차트)
dependencies:
  - name: redis
    version: "18.x.x"             # 버전 범위 (SemVer)
    repository: https://charts.bitnami.com/bitnami
    condition: redis.enabled       # values.yaml의 redis.enabled로 on/off

  - name: postgresql
    version: "13.x.x"
    repository: https://charts.bitnami.com/bitnami
    condition: postgresql.enabled

# 키워드 (검색용)
keywords:
  - api
  - allganize
  - alli

maintainers:
  - name: Platform Team
    email: platform@allganize.ai

# Helm 버전 제약
kubeVersion: ">=1.25.0-0"
```

### values.yaml과 오버라이드 체계

```yaml
# values.yaml (기본값)
replicaCount: 2

image:
  repository: ghcr.io/allganize/alli-api
  tag: "latest"                    # Chart.yaml의 appVersion을 주로 사용
  pullPolicy: IfNotPresent

imagePullSecrets:
  - name: ghcr-secret

serviceAccount:
  create: true
  annotations: {}
  name: ""                         # 비어있으면 릴리스명 기반 자동 생성

service:
  type: ClusterIP
  port: 80
  targetPort: 8080

ingress:
  enabled: false
  className: nginx
  annotations: {}
  hosts:
    - host: api.allganize.ai
      paths:
        - path: /
          pathType: Prefix
  tls: []

resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi

autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 80

# 환경변수
env:
  - name: LOG_LEVEL
    value: "info"
  - name: DB_HOST
    value: "mongodb.default.svc"

# 프로브
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5

# 서브차트 설정
redis:
  enabled: true
  architecture: standalone
  auth:
    enabled: true
    existingSecret: redis-secret

postgresql:
  enabled: false
```

```yaml
# values-production.yaml (운영 환경 오버라이드)
replicaCount: 4

image:
  tag: "v2.1.0"

resources:
  requests:
    cpu: 1000m
    memory: 1Gi
  limits:
    cpu: 2000m
    memory: 2Gi

autoscaling:
  enabled: true
  minReplicas: 4
  maxReplicas: 20
  targetCPUUtilizationPercentage: 70

ingress:
  enabled: true
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: api.allganize.ai
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: alli-api-tls
      hosts:
        - api.allganize.ai

env:
  - name: LOG_LEVEL
    value: "warn"
  - name: DB_HOST
    value: "mongodb-prod.default.svc"
```

### values 오버라이드 우선순위

```
우선순위 (낮음 → 높음):

1. Chart 내 values.yaml            (기본값)
2. 부모 Chart의 values.yaml         (서브차트 오버라이드)
3. -f / --values 파일               (helm install -f values-prod.yaml)
4. --set 파라미터                   (helm install --set image.tag=v2)
5. --set-string                     (문자열 강제)
6. --set-json                       (JSON 구조체)

예시:
helm upgrade alli-api ./alli-api \
  -f values.yaml \
  -f values-production.yaml \           # values.yaml 위에 오버라이드
  --set image.tag=abc1234 \             # 가장 높은 우선순위
  --namespace alli-api
```

### Go Template 핵심 문법

```yaml
# templates/deployment.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "alli-api.fullname" . }}
  labels:
    {{- include "alli-api.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "alli-api.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      annotations:
        # ConfigMap 변경 시 Pod 재시작을 위한 checksum
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
      labels:
        {{- include "alli-api.selectorLabels" . | nindent 8 }}
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      serviceAccountName: {{ include "alli-api.serviceAccountName" . }}
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.service.targetPort }}
              protocol: TCP
          {{- if .Values.env }}
          env:
            {{- toYaml .Values.env | nindent 12 }}
          {{- end }}
          {{- with .Values.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.livenessProbe }}
          livenessProbe:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with .Values.readinessProbe }}
          readinessProbe:
            {{- toYaml . | nindent 12 }}
          {{- end }}
```

### _helpers.tpl (공통 헬퍼)

```yaml
# templates/_helpers.tpl

{{/*
Chart 전체 이름 (릴리스명-차트명, 63자 제한)
*/}}
{{- define "alli-api.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
공통 라벨
*/}}
{{- define "alli-api.labels" -}}
helm.sh/chart: {{ include "alli-api.chart" . }}
{{ include "alli-api.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector 라벨
*/}}
{{- define "alli-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "alli-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount 이름
*/}}
{{- define "alli-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "alli-api.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
```

### Helm Hooks

배포 전후에 자동으로 실행되는 작업을 정의한다.

```yaml
# templates/pre-upgrade-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "alli-api.fullname" . }}-db-migrate
  annotations:
    "helm.sh/hook": pre-upgrade,pre-install
    "helm.sh/hook-weight": "-5"           # 낮은 숫자가 먼저 실행
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        command: ["python", "manage.py", "migrate", "--no-input"]
        env:
          - name: DATABASE_URL
            valueFrom:
              secretKeyRef:
                name: db-credentials
                key: url
      restartPolicy: Never
  backoffLimit: 3
---
# templates/post-upgrade-test.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "alli-api.fullname" . }}-smoke-test
  annotations:
    "helm.sh/hook": post-upgrade,post-install
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
      - name: smoke-test
        image: curlimages/curl:latest
        command:
        - sh
        - -c
        - |
          echo "Waiting for service..."
          sleep 10
          curl -sf http://{{ include "alli-api.fullname" . }}:{{ .Values.service.port }}/healthz
          echo "Smoke test passed!"
      restartPolicy: Never
  backoffLimit: 1
```

```
Helm Hook 종류:
  pre-install      → install 전
  post-install     → install 후
  pre-delete       → delete 전
  post-delete      → delete 후
  pre-upgrade      → upgrade 전
  post-upgrade     → upgrade 후
  pre-rollback     → rollback 전
  post-rollback    → rollback 후
  test             → helm test 시

Hook Delete Policy:
  before-hook-creation → 새 hook 생성 전 이전 리소스 삭제
  hook-succeeded       → hook 성공 시 삭제
  hook-failed          → hook 실패 시 삭제
```

### Chart 테스트

```yaml
# templates/tests/test-connection.yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "alli-api.fullname" . }}-test-connection"
  labels:
    {{- include "alli-api.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  containers:
    - name: wget
      image: busybox
      command: ['wget']
      args: ['{{ include "alli-api.fullname" . }}:{{ .Values.service.port }}/healthz']
  restartPolicy: Never
```

```bash
# 테스트 실행
helm test alli-api -n alli-api

# 테스트 로그 확인
helm test alli-api -n alli-api --logs
```

### OCI Registry로 Chart 관리

Helm 3.8+ 부터 OCI (Open Container Initiative) Registry에 Chart를 저장할 수 있다. 컨테이너 이미지와 동일한 레지스트리(ECR, ACR, Harbor, GHCR)를 사용한다.

```bash
# ── Chart 패키징 ──
helm package ./alli-api
# → alli-api-1.2.3.tgz

# ── OCI Registry 로그인 ──
# ECR
aws ecr get-login-password --region ap-northeast-2 | \
  helm registry login --username AWS --password-stdin \
  123456789012.dkr.ecr.ap-northeast-2.amazonaws.com

# GHCR
echo $GITHUB_TOKEN | helm registry login ghcr.io --username $GITHUB_USER --password-stdin

# Harbor
helm registry login harbor.internal.corp --username admin --password $HARBOR_PASS

# ── Chart Push ──
helm push alli-api-1.2.3.tgz oci://ghcr.io/allganize/charts

# ── Chart Pull ──
helm pull oci://ghcr.io/allganize/charts/alli-api --version 1.2.3

# ── Chart Install (OCI에서 직접) ──
helm install alli-api oci://ghcr.io/allganize/charts/alli-api \
  --version 1.2.3 \
  -f values-production.yaml \
  -n alli-api

# ── Chart 정보 확인 ──
helm show chart oci://ghcr.io/allganize/charts/alli-api --version 1.2.3
helm show values oci://ghcr.io/allganize/charts/alli-api --version 1.2.3
```

```
OCI Registry vs ChartMuseum 비교:

┌────────────────┬─────────────────────┬──────────────────┐
│                │ OCI Registry        │ ChartMuseum       │
├────────────────┼─────────────────────┼──────────────────┤
│ 인프라         │ 기존 레지스트리 재사용│ 별도 서버 필요    │
│ 인증           │ Docker 인증과 통합   │ 별도 인증         │
│ 버전 관리      │ 이미지와 동일 방식   │ index.yaml 기반  │
│ 이미지+차트    │ 같은 레지스트리      │ 분리 관리         │
│ CI/CD 통합     │ docker login 재사용  │ helm repo add    │
│ 표준           │ OCI 표준 (CNCF)     │ Helm 전용        │
│ 권장도         │ ★★★ (현대적)        │ ★★☆ (레거시)     │
└────────────────┴─────────────────────┴──────────────────┘
```

### Library Chart

재사용 가능한 템플릿 로직을 공유하는 Chart 유형이다. 직접 설치되지 않고 다른 Chart에서 의존성으로 사용한다.

```yaml
# library-chart/Chart.yaml
apiVersion: v2
name: allganize-common
type: library                       # application이 아님
version: 1.0.0

# library-chart/templates/_deployment.tpl
{{- define "allganize-common.deployment" -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "allganize-common.fullname" . }}
  labels:
    {{- include "allganize-common.labels" . | nindent 4 }}
spec:
  # ... 공통 Deployment 템플릿
{{- end -}}
```

```yaml
# alli-api/Chart.yaml (사용하는 쪽)
dependencies:
  - name: allganize-common
    version: "1.0.0"
    repository: "oci://ghcr.io/allganize/charts"

# alli-api/templates/deployment.yaml
{{ include "allganize-common.deployment" . }}
```

---

## 실전 예시

### Helm 운영 명령어

```bash
# ── 설치 / 업그레이드 ──
helm install alli-api ./alli-api -n alli-api --create-namespace \
  -f values.yaml -f values-production.yaml

# install + upgrade 통합 (멱등)
helm upgrade --install alli-api ./alli-api -n alli-api --create-namespace \
  -f values-production.yaml \
  --set image.tag=abc1234 \
  --wait --timeout 5m                  # 배포 완료까지 대기

# ── 상태 확인 ──
helm list -n alli-api                  # 설치된 릴리스 목록
helm status alli-api -n alli-api       # 릴리스 상태
helm history alli-api -n alli-api      # 릴리스 히스토리

# ── 롤백 ──
helm rollback alli-api 3 -n alli-api   # revision 3으로 롤백
helm rollback alli-api 0 -n alli-api   # 이전 리비전으로

# ── 디버깅 ──
helm template alli-api ./alli-api -f values-production.yaml  # 렌더링 확인
helm template alli-api ./alli-api -f values-production.yaml --debug  # 디버그 모드
helm lint ./alli-api                   # Chart 문법 검사
helm diff upgrade alli-api ./alli-api -f values-production.yaml  # diff 플러그인

# ── 삭제 ──
helm uninstall alli-api -n alli-api    # 릴리스 삭제

# ── 의존성 관리 ──
helm dependency update ./alli-api      # Chart.lock 기반 서브차트 다운로드
helm dependency build ./alli-api       # 의존성 빌드
```

### ArgoCD에서 Helm Chart 사용

```yaml
# ArgoCD Application (Helm 기반)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: alli-api
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/allganize/k8s-manifests.git
    targetRevision: main
    path: charts/alli-api
    helm:
      releaseName: alli-api
      valueFiles:
        - values.yaml
        - values-production.yaml
      parameters:
        - name: image.tag
          value: "abc1234"
      # values 파일을 inline으로도 지정 가능
      # values: |
      #   replicaCount: 4
  destination:
    server: https://kubernetes.default.svc
    namespace: alli-api
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

```yaml
# ArgoCD Application (OCI Registry에서 직접)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: alli-api
  namespace: argocd
spec:
  source:
    chart: alli-api                          # Chart 이름
    repoURL: ghcr.io/allganize/charts        # OCI Registry
    targetRevision: 1.2.3                    # Chart 버전
    helm:
      valueFiles:
        - $values/apps/alli-api/values-prod.yaml
  # Multi-source로 values 파일을 별도 Git 저장소에서 관리
  sources:
    - repoURL: ghcr.io/allganize/charts
      chart: alli-api
      targetRevision: 1.2.3
      helm:
        valueFiles:
          - $values/production/alli-api.yaml
    - repoURL: https://github.com/allganize/k8s-values.git
      targetRevision: main
      ref: values
```

### Helm Chart CI/CD 파이프라인

```yaml
# .github/workflows/chart-ci.yaml
name: Helm Chart CI

on:
  push:
    paths:
      - 'charts/**'

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Helm
        uses: azure/setup-helm@v3

      - name: Helm lint
        run: helm lint charts/alli-api

      - name: Helm template (렌더링 검증)
        run: |
          helm template alli-api charts/alli-api \
            -f charts/alli-api/values.yaml \
            -f charts/alli-api/values-production.yaml

      - name: Kubeconform (스키마 검증)
        run: |
          helm template alli-api charts/alli-api | \
            kubeconform -strict -kubernetes-version 1.28.0

  package-and-push:
    needs: lint-and-test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Helm
        uses: azure/setup-helm@v3

      - name: Login to GHCR
        run: |
          echo ${{ secrets.GITHUB_TOKEN }} | \
            helm registry login ghcr.io --username ${{ github.actor }} --password-stdin

      - name: Package and push
        run: |
          helm package charts/alli-api
          helm push alli-api-*.tgz oci://ghcr.io/${{ github.repository_owner }}/charts
```

---

## 면접 Q&A

### Q: "Helm Chart의 구조와 주요 파일을 설명해주세요"

**30초 답변**:
Chart.yaml은 메타데이터(이름, 버전, 의존성)를 정의하고, values.yaml은 템플릿의 기본 설정값입니다. templates/ 디렉토리에 Go Template 기반의 K8s 매니페스트가 있고, _helpers.tpl은 공통 헬퍼 함수를 정의합니다. charts/ 디렉토리에는 서브차트(의존 Chart)가 위치합니다.

**2분 답변**:
Helm Chart는 K8s 리소스의 패키지입니다. 핵심 파일은 네 가지입니다. Chart.yaml은 Chart의 메타데이터로, name, version(Chart 자체 버전, SemVer 필수), appVersion(애플리케이션 버전), dependencies(서브차트)를 정의합니다. version과 appVersion을 분리하는 이유는 Chart 구조 변경과 앱 버전 업데이트의 라이프사이클이 다르기 때문입니다. values.yaml은 템플릿 변수의 기본값입니다. 환경별로 values-dev.yaml, values-production.yaml을 만들어 오버라이드합니다. `-f` 플래그로 여러 파일을 지정하면 나중에 지정한 파일이 이전 값을 덮어씁니다. `--set`은 가장 높은 우선순위를 가집니다. templates/ 디렉토리에는 Go Template 문법으로 작성된 K8s 매니페스트가 있습니다. `{{ .Values.replicaCount }}` 같은 변수 참조, `{{ if }}`, `{{ range }}` 같은 제어 구조를 사용합니다. _helpers.tpl은 `define`으로 재사용 가능한 템플릿 블록을 정의하고, `include`로 호출합니다. 라벨 생성, 이름 생성 같은 공통 로직을 여기에 둡니다. tests/ 디렉토리에는 `helm test` 명령으로 실행되는 검증 Pod를 정의합니다. 설치 후 서비스 연결이 정상인지 확인하는 데 사용합니다.

**💡 경험 연결**:
사내 공통 Chart를 Library Chart로 만들어 Deployment, Service, Ingress의 표준 템플릿을 제공하고, 각 팀은 values.yaml만 작성하면 되도록 표준화한 경험이 있습니다. 이를 통해 신규 서비스 온보딩 시간을 크게 단축했습니다.

**⚠️ 주의**:
Helm 2와 Helm 3의 차이(Tiller 제거)를 물어볼 수 있다. Helm 3에서는 Tiller가 없어져 보안이 개선되었고, K8s RBAC을 직접 사용한다는 점을 알아둘 것.

---

### Q: "Helm의 values 오버라이드 우선순위를 설명해주세요"

**30초 답변**:
기본 values.yaml이 가장 낮은 우선순위이고, `-f`로 지정한 파일이 그 위에, `--set`이 가장 높은 우선순위입니다. 여러 `-f` 파일을 지정하면 나중에 지정한 파일이 이전 파일을 덮어씁니다. 이를 활용하여 values.yaml(공통) → values-production.yaml(환경별) → `--set image.tag`(CI에서 동적)으로 계층적 설정을 관리합니다.

**2분 답변**:
Helm의 값 오버라이드는 계층적 머지(Merge) 방식입니다. Chart 내 values.yaml이 기본값이고, `-f` 또는 `--values` 플래그로 지정한 파일이 그 위에 덮어씌워집니다. 여러 `-f`를 지정하면 순서대로 머지되어 나중 파일이 우선합니다. `--set`은 가장 높은 우선순위로, CLI에서 개별 값을 직접 지정합니다. 실무에서는 이 계층을 활용하여 설정을 분리합니다. 첫 번째 레이어는 values.yaml로 모든 환경의 공통 기본값(이미지, 포트, 프로브 설정)을 정의합니다. 두 번째는 values-production.yaml처럼 환경별 파일로 replicas, 리소스, 인그레스 등을 오버라이드합니다. 세 번째는 `--set image.tag=$GIT_SHA`처럼 CI/CD에서 동적으로 변경되는 값을 주입합니다. ArgoCD에서는 Application CRD의 `helm.valueFiles`와 `helm.parameters`로 동일한 계층화를 구현합니다. Multi-source 기능을 사용하면 values 파일을 별도 Git 저장소에서 관리하여 Chart와 설정의 라이프사이클을 완전히 분리할 수도 있습니다. 주의할 점은 `--set`으로 복잡한 구조(배열, 중첩 객체)를 지정하면 가독성이 떨어지고 실수하기 쉽습니다. 복잡한 값은 반드시 파일로 관리하고, `--set`은 단순 값(image.tag, replicaCount)에만 사용하는 것이 좋습니다.

**💡 경험 연결**:
초기에 `--set`으로 10개 이상의 값을 지정하다가 릴리스 간 차이를 추적하기 어려웠습니다. values 파일로 전환하고 Git에서 관리하면서 변경 이력 추적이 가능해졌습니다. `helm diff` 플러그인으로 업그레이드 전 차이를 확인하는 습관도 도움이 되었습니다.

**⚠️ 주의**:
"--set이 편리해서 자주 씁니다"라고 하면 GitOps와 충돌하는 인상을 줄 수 있다. "--set은 디버깅이나 일회성 테스트에만 사용하고, 프로덕션은 반드시 values 파일로 관리한다"고 답할 것.

---

### Q: "Helm Chart를 OCI Registry에 저장하는 이유는?"

**30초 답변**:
OCI Registry를 사용하면 컨테이너 이미지와 Helm Chart를 같은 레지스트리(ECR, GHCR, Harbor)에서 관리할 수 있습니다. 별도의 ChartMuseum 서버가 필요 없고, 기존 Docker 인증 체계를 그대로 사용합니다. CNCF 표준이므로 장기적으로 권장되는 방식입니다.

**2분 답변**:
전통적으로 Helm Chart는 ChartMuseum이나 GitHub Pages 같은 HTTP 기반 Chart Repository에 저장했습니다. 하지만 이 방식은 별도 서버 운영, 별도 인증 체계, index.yaml 관리 등의 부담이 있습니다. OCI Registry 지원이 Helm 3.8에서 GA(Generally Available)가 되면서, 기존 컨테이너 레지스트리에 Chart를 함께 저장할 수 있게 되었습니다. 장점은 세 가지입니다. 첫째, 인프라 통합입니다. ECR, ACR, GHCR, Harbor 같은 기존 레지스트리를 그대로 사용하므로 별도 서버가 필요 없습니다. 둘째, 인증 통합입니다. `docker login`과 동일한 인증을 `helm registry login`에서 사용합니다. AWS의 경우 ECR에 이미지와 Chart를 모두 저장하고, IAM으로 통합 접근 제어가 가능합니다. 셋째, 표준화입니다. OCI는 CNCF 산하 표준으로, 컨테이너 이미지, Helm Chart, WASM 모듈 등을 동일한 분배(Distribution) 규격으로 관리합니다. ArgoCD도 OCI 기반 Helm Chart를 네이티브로 지원합니다. Application CRD에서 `repoURL: ghcr.io/allganize/charts`처럼 OCI 주소를 직접 지정할 수 있습니다. CI/CD 파이프라인에서는 이미지 Push 직후 Chart를 같은 레지스트리에 Push하는 것이 자연스러운 워크플로우가 됩니다.

**💡 경험 연결**:
폐쇄망에서 ChartMuseum을 별도 운영하다가 Harbor의 OCI Chart 저장 기능으로 전환했습니다. 레지스트리 하나로 이미지와 Chart를 모두 관리하게 되면서 운영 부담이 줄었습니다.

**⚠️ 주의**:
OCI 지원이 Helm 3.8+ GA라는 버전 정보를 알아둘 것. Helm 3.7 이하에서는 실험적 기능(experimental)이었다.

---

## Allganize 맥락

- **마이크로서비스 표준화**: Library Chart로 Deployment, Service, Ingress의 조직 표준 템플릿을 만들면 서비스별 values.yaml만 작성하면 되어 온보딩이 빨라진다
- **AWS/Azure 멀티클라우드**: OCI Registry에 Chart를 저장하면 ECR(AWS)과 ACR(Azure)에서 동일한 Chart를 관리할 수 있다
- **ArgoCD 통합**: Application CRD에서 Helm valueFiles와 parameters로 환경별 배포를 자동화하고, Multi-source로 Chart와 values를 분리 관리한다
- **AI 모델 서빙**: 모델 버전을 values의 image.tag로 관리하면, 모델 교체가 values 파일 한 줄 변경으로 가능하다
- **면접 포인트**: Chart 구조와 values 오버라이드를 정확히 설명하고, OCI Registry와 ArgoCD 연동까지 언급하면 최신 기술 동향을 파악하고 있다는 인상을 준다

---
**핵심 키워드**: `Helm Chart` `values override` `Go Template` `Helm Hook` `OCI Registry` `Library Chart` `helm diff`
