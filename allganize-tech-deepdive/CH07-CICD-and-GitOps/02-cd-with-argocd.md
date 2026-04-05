# ArgoCD를 활용한 CD (Continuous Delivery with ArgoCD)

> **TL;DR**
> - ArgoCD는 K8s 네이티브 GitOps CD 도구로, Git 매니페스트와 클러스터 상태를 자동으로 동기화(Reconcile)한다
> - Application CRD가 핵심이며, Sync Policy(Auto/Manual, Prune, Self-heal)로 배포 동작을 세밀하게 제어한다
> - Health Check + Sync Wave + App of Apps 패턴으로 대규모 마이크로서비스 환경을 선언적으로 관리한다

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### ArgoCD 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│                        ArgoCD System                             │
│                                                                  │
│  ┌────────────────┐   ┌──────────────────────┐                  │
│  │   API Server   │   │ Application Controller│                  │
│  │                │   │                       │                  │
│  │ ● Web UI       │   │ ● Git Polling (3min)  │                  │
│  │ ● gRPC/REST    │   │ ● Desired vs Live     │                  │
│  │ ● RBAC         │   │   State Diff          │                  │
│  │ ● SSO (Dex)    │   │ ● Sync Execution      │                  │
│  │ ● Webhook      │   │ ● Health Assessment   │                  │
│  └───────┬────────┘   └───────────┬───────────┘                  │
│          │                        │                              │
│  ┌───────┴────────────────────────┴───────────┐                  │
│  │              Repo Server                    │                  │
│  │                                             │                  │
│  │  ● Git Clone & Cache                        │                  │
│  │  ● Helm Template Rendering                  │                  │
│  │  ● Kustomize Build                          │                  │
│  │  ● Jsonnet / Plain YAML                     │                  │
│  └─────────────────────────────────────────────┘                  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐         │
│  │    Redis     │  │     Dex      │  │ Notification   │         │
│  │   (Cache)    │  │   (SSO)      │  │  Controller    │         │
│  └──────────────┘  └──────────────┘  └────────────────┘         │
└──────────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────┐           ┌─────────────────────┐
│   Git Repos     │           │   K8s Clusters      │
│  (Source of     │           │  (in-cluster +      │
│   Truth)        │           │   remote clusters)  │
└─────────────────┘           └─────────────────────┘
```

**컴포넌트별 역할 상세:**

| 컴포넌트 | 역할 | 핵심 설정 |
|----------|------|----------|
| **API Server** | Web UI, CLI, CI 연동의 진입점. RBAC/SSO 처리 | `argocd-rbac-cm`, `argocd-cm` |
| **Application Controller** | 핵심 엔진. Git과 Cluster 상태를 주기적으로 비교하고 Sync 실행 | `timeout.reconciliation` (기본 3분) |
| **Repo Server** | Git 클론, Helm/Kustomize 렌더링. 결과를 Controller에 전달 | `reposerver.parallelism.limit` |
| **Redis** | 매니페스트 캐시, 앱 상태 캐시 | 메모리 설정 |
| **Dex** | OIDC/LDAP/SAML 기반 SSO 인증 | `argocd-cm` 의 `dex.config` |
| **Notification Controller** | Slack, Teams, Webhook으로 Sync 이벤트 알림 | `argocd-notifications-cm` |

### Application CRD 완전 분석

Application CRD는 ArgoCD의 핵심 리소스로, "무엇을(Source) 어디에(Destination) 어떻게(SyncPolicy) 배포할 것인가"를 정의한다.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: alli-api                       # 앱 이름 (ArgoCD UI에 표시)
  namespace: argocd                    # Application CRD는 반드시 argocd NS
  labels:
    team: backend
    env: production
    tier: api
  annotations:
    # Notification 설정
    notifications.argoproj.io/subscribe.on-sync-succeeded.slack: ci-cd-alerts
    notifications.argoproj.io/subscribe.on-health-degraded.slack: ci-cd-alerts
  finalizers:
    - resources-finalizer.argocd.argoproj.io  # 삭제 시 K8s 리소스도 함께 정리
spec:
  # ── 프로젝트 ──
  project: alli-platform               # AppProject로 RBAC 범위 지정

  # ── 소스 (Git 저장소) ──
  source:
    repoURL: https://github.com/allganize/k8s-manifests.git
    targetRevision: main               # 브랜치, 태그, 커밋 SHA 모두 가능
    path: apps/alli-api/overlays/production

    # Helm 사용 시
    # helm:
    #   releaseName: alli-api
    #   valueFiles:
    #     - values.yaml
    #     - values-production.yaml
    #   parameters:
    #     - name: image.tag
    #       value: "abc1234"

    # Kustomize 사용 시
    # kustomize:
    #   namePrefix: prod-
    #   commonLabels:
    #     env: production

  # ── 다중 소스 (v2.6+) ──
  # sources:
  #   - repoURL: https://charts.example.com
  #     chart: alli-api
  #     targetRevision: 1.2.3
  #     helm:
  #       valueFiles:
  #         - $values/apps/alli-api/values-prod.yaml
  #   - repoURL: https://github.com/allganize/k8s-values.git
  #     targetRevision: main
  #     ref: values

  # ── 대상 (K8s 클러스터) ──
  destination:
    server: https://kubernetes.default.svc  # in-cluster
    # server: https://eks-prod.ap-northeast-2.eks.amazonaws.com  # 원격 클러스터
    namespace: alli-api

  # ── 동기화 정책 ──
  syncPolicy:
    automated:
      prune: true                      # Git에서 삭제된 리소스 → 클러스터에서도 삭제
      selfHeal: true                   # 수동 kubectl 변경 → Git 상태로 자동 복원
      allowEmpty: false                # 빈 매니페스트 방지 (안전장치)
    syncOptions:
      - CreateNamespace=true           # 네임스페이스 자동 생성
      - PrunePropagationPolicy=foreground  # Cascade 삭제
      - PruneLast=true                 # Sync 후 마지막에 Prune (순서 보장)
      - ServerSideApply=true           # SSA 사용 (대규모 리소스 시 권장)
      - RespectIgnoreDifferences=true  # ignoreDifferences 존중
      - ApplyOutOfSyncOnly=true        # 변경된 리소스만 적용 (성능 최적화)
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m

  # ── Diff 무시 ──
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas              # HPA가 관리하는 replicas는 무시
    - group: ""
      kind: Service
      jqPathExpressions:
        - .spec.clusterIP             # 자동 할당되는 ClusterIP 무시

  # ── 리소스별 Health Check 커스텀 ──
  # (argocd-cm ConfigMap에서 글로벌 설정도 가능)
```

### Sync Policy 상세 비교

```
┌─────────────────────────────────────────────────────────┐
│              Sync Policy Decision Matrix                 │
│                                                         │
│  ┌───────────┬──────────┬──────────┬───────────┐       │
│  │           │ Dev/Test │ Staging  │Production │       │
│  ├───────────┼──────────┼──────────┼───────────┤       │
│  │ Auto Sync │    ✅    │    ✅    │    ❌     │       │
│  │ Prune     │    ✅    │    ✅    │  ⚠️ 신중  │       │
│  │ Self-heal │    ✅    │    ✅    │    ✅     │       │
│  │ Retry     │   3회    │   3회    │   5회     │       │
│  └───────────┴──────────┴──────────┴───────────┘       │
│                                                         │
│  Production: Manual Sync + Self-heal 조합이 일반적      │
│  → Git Push로 변경하되, Sync는 의도한 시점에 실행       │
│  → 누군가 kubectl edit하면 자동 복구                     │
└─────────────────────────────────────────────────────────┘
```

### Sync Wave와 Sync Hook

리소스 간 배포 순서를 제어하는 메커니즘이다.

```yaml
# Wave: 숫자가 낮은 것부터 순서대로 Sync
# Namespace (wave -1) → ConfigMap (wave 0) → Deployment (wave 1) → Ingress (wave 2)

# 1) Namespace 먼저 생성
apiVersion: v1
kind: Namespace
metadata:
  name: alli-api
  annotations:
    argocd.argoproj.io/sync-wave: "-1"

---
# 2) ConfigMap/Secret
apiVersion: v1
kind: ConfigMap
metadata:
  name: alli-api-config
  annotations:
    argocd.argoproj.io/sync-wave: "0"

---
# 3) Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api
  annotations:
    argocd.argoproj.io/sync-wave: "1"

---
# 4) Post-sync Job (DB Migration 등)
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: harbor.internal.corp/alli/migrate:v1.2.3
        command: ["python", "manage.py", "migrate"]
      restartPolicy: Never
```

```
Sync Hook 종류:
  PreSync   → Sync 시작 전 (DB 백업 등)
  Sync      → 메인 Sync와 함께
  PostSync  → Sync 성공 후 (DB 마이그레이션, 스모크 테스트)
  SyncFail  → Sync 실패 시 (알림, 정리)
  Skip      → Sync에서 제외

Hook Delete Policy:
  HookSucceeded      → 훅 성공 시 리소스 삭제
  HookFailed         → 훅 실패 시 리소스 삭제
  BeforeHookCreation → 새 훅 생성 전 이전 리소스 삭제
```

### Health Check 체계

ArgoCD는 리소스별로 Health 상태를 자동 판단한다.

```
Health Status:
  Healthy      → 정상 동작 중
  Progressing  → 변경 진행 중 (Deployment rollout 등)
  Degraded     → 일부 문제 (Pod CrashLoopBackOff 등)
  Suspended    → 일시 중지 (Rollout pause 등)
  Missing      → 리소스 없음
  Unknown      → 상태 판단 불가

리소스별 Health 판단 기준:
  Deployment  → .status.conditions의 Available 및 Progressing
  StatefulSet → .status.readyReplicas == .spec.replicas
  Pod         → .status.phase == Running && 모든 Container Ready
  Service     → 항상 Healthy (LoadBalancer는 IP 할당 여부)
  Ingress     → .status.loadBalancer.ingress 존재 여부
  Job         → .status.succeeded > 0
  PVC         → .status.phase == Bound
```

커스텀 리소스에 대한 Health Check:

```yaml
# argocd-cm ConfigMap
data:
  # Argo Rollouts의 Rollout 리소스 Health Check
  resource.customizations.health.argoproj.io_Rollout: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.phase == "Healthy" then
        hs.status = "Healthy"
        hs.message = obj.status.message
      elseif obj.status.phase == "Paused" then
        hs.status = "Suspended"
        hs.message = obj.status.message
      elseif obj.status.phase == "Degraded" then
        hs.status = "Degraded"
        hs.message = obj.status.message
      else
        hs.status = "Progressing"
        hs.message = obj.status.message
      end
    end
    return hs

  # CRD에 대한 무시 설정
  resource.customizations.ignoreDifferences.admissionregistration.k8s.io_MutatingWebhookConfiguration: |
    jqPathExpressions:
      - '.webhooks[]?.clientConfig.caBundle'
```

### App of Apps 패턴

```
┌────────────────────────────────────────────────────────────┐
│                   App of Apps Architecture                  │
│                                                            │
│  Root Application (apps-of-apps)                           │
│  source: k8s-manifests/apps-of-apps/                       │
│       │                                                    │
│       ├── alli-api.yaml ──────→ Application: alli-api      │
│       │                         path: apps/alli-api/       │
│       │                         overlays/production        │
│       │                                                    │
│       ├── alli-web.yaml ──────→ Application: alli-web      │
│       │                         path: apps/alli-web/       │
│       │                         overlays/production        │
│       │                                                    │
│       ├── alli-worker.yaml ───→ Application: alli-worker   │
│       │                                                    │
│       └── platform/                                        │
│           ├── monitoring.yaml → Application: monitoring    │
│           ├── logging.yaml ──→ Application: logging        │
│           └── ingress.yaml ──→ Application: ingress        │
│                                                            │
│  새 서비스 추가 = YAML 파일 1개를 Git에 Push               │
│  ArgoCD가 자동으로 Application CRD 생성                    │
└────────────────────────────────────────────────────────────┘
```

### ApplicationSet Controller

App of Apps보다 동적인 Application 생성이 가능한 컨트롤러이다.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: alli-services
  namespace: argocd
spec:
  generators:
    # Git 디렉토리 기반 자동 생성
    - git:
        repoURL: https://github.com/allganize/k8s-manifests.git
        revision: main
        directories:
          - path: apps/*              # apps/ 아래 각 디렉토리마다 Application 생성
          - path: apps/excluded-app   # 제외
            exclude: true

    # 멀티 클러스터 배포
    # - clusters:
    #     selector:
    #       matchLabels:
    #         env: production

    # Matrix: 클러스터 x 서비스 조합
    # - matrix:
    #     generators:
    #       - clusters:
    #           selector:
    #             matchLabels:
    #               env: production
    #       - git:
    #           repoURL: ...
    #           directories:
    #             - path: apps/*

  template:
    metadata:
      name: '{{path.basename}}'        # 디렉토리 이름이 앱 이름
      namespace: argocd
      labels:
        app.kubernetes.io/managed-by: applicationset
    spec:
      project: default
      source:
        repoURL: https://github.com/allganize/k8s-manifests.git
        targetRevision: main
        path: '{{path}}/overlays/production'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{path.basename}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

### 멀티 클러스터 관리

```bash
# 원격 클러스터 등록
argocd cluster add eks-prod-cluster \
  --kubeconfig ~/.kube/config \
  --name production-eks

# 등록된 클러스터 확인
argocd cluster list

# 클러스터별 Application 배포
# destination.server에 원격 클러스터 URL 지정
```

```
┌──────────────────────────────────────────────────┐
│            Multi-Cluster Architecture             │
│                                                  │
│  ┌─────────────┐                                 │
│  │  ArgoCD     │                                 │
│  │  (관리 클러스터) │                              │
│  └──────┬──────┘                                 │
│         │                                        │
│    ┌────┼─────────────┐                          │
│    │    │             │                          │
│    ▼    ▼             ▼                          │
│  ┌────┐ ┌────┐    ┌────┐                        │
│  │EKS │ │AKS │    │EKS │                        │
│  │Prod│ │Prod│    │Dev │                        │
│  │ AP │ │ KR │    │ AP │                        │
│  └────┘ └────┘    └────┘                        │
│                                                  │
│  ArgoCD는 관리 클러스터에만 설치하고              │
│  원격 클러스터에는 Agent 없이 API로 배포          │
└──────────────────────────────────────────────────┘
```

---

## 실전 예시

### ArgoCD 설치 (Production-grade)

```bash
# Helm으로 설치 (운영 환경 권장)
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

helm install argocd argo/argo-cd \
  --namespace argocd --create-namespace \
  --set server.ingress.enabled=true \
  --set server.ingress.hosts[0]=argocd.allganize.internal \
  --set server.ingress.tls[0].secretName=argocd-tls \
  --set server.ingress.tls[0].hosts[0]=argocd.allganize.internal \
  --set controller.metrics.enabled=true \
  --set server.metrics.enabled=true \
  --set repoServer.replicas=2 \
  --set controller.replicas=1 \
  --set server.replicas=2 \
  --set redis-ha.enabled=true \
  --values argocd-values.yaml

# 초기 admin 비밀번호 확인
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
```

### RBAC 설정 (팀별 권한 분리)

```yaml
# argocd-rbac-cm ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.csv: |
    # Backend 팀: 자기 앱만 Sync 가능
    p, role:backend-team, applications, get, alli-platform/alli-api*, allow
    p, role:backend-team, applications, sync, alli-platform/alli-api*, allow
    p, role:backend-team, applications, action/*, alli-platform/alli-api*, allow

    # Platform 팀: 모든 앱 관리 가능
    p, role:platform-team, applications, *, */*, allow
    p, role:platform-team, clusters, get, *, allow
    p, role:platform-team, repositories, *, *, allow
    p, role:platform-team, projects, *, *, allow

    # 읽기 전용 (모니터링 용도)
    p, role:viewer, applications, get, */*, allow

    # SSO 그룹 매핑
    g, backend-engineers, role:backend-team
    g, platform-engineers, role:platform-team
    g, managers, role:viewer

  policy.default: role:''             # 기본 권한 없음
  scopes: '[groups, email]'
```

### Notification 설정 (Slack)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  service.slack: |
    token: $slack-token

  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
      send: [sync-succeeded]

  trigger.on-health-degraded: |
    - when: app.status.health.status == 'Degraded'
      send: [health-degraded]

  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Error', 'Failed']
      send: [sync-failed]

  template.sync-succeeded: |
    slack:
      attachments: |
        [{
          "color": "#18be52",
          "title": "{{.app.metadata.name}} Sync 성공",
          "fields": [
            {"title": "Revision", "value": "{{.app.status.sync.revision | trunc 7}}", "short": true},
            {"title": "Namespace", "value": "{{.app.spec.destination.namespace}}", "short": true}
          ]
        }]

  template.health-degraded: |
    slack:
      attachments: |
        [{
          "color": "#f4c030",
          "title": "{{.app.metadata.name}} Health Degraded",
          "text": "앱 상태가 비정상입니다. 확인이 필요합니다."
        }]

  template.sync-failed: |
    slack:
      attachments: |
        [{
          "color": "#E96D76",
          "title": "{{.app.metadata.name}} Sync 실패",
          "text": "{{.app.status.operationState.message}}"
        }]
```

### ArgoCD CLI 운영 명령어

```bash
# 로그인
argocd login argocd.allganize.internal --grpc-web --sso

# 앱 목록
argocd app list

# 앱 상세 (Diff 확인)
argocd app get alli-api
argocd app diff alli-api

# 수동 Sync
argocd app sync alli-api
argocd app sync alli-api --prune --force  # 강제 Sync

# 롤백 (이전 Git revision으로)
argocd app rollback alli-api

# 히스토리 확인
argocd app history alli-api

# 앱 삭제 (K8s 리소스도 함께 = cascade)
argocd app delete alli-api --cascade

# 하드 리프레시 (캐시 무시하고 Git 재조회)
argocd app get alli-api --hard-refresh
```

---

## 면접 Q&A

### Q: "ArgoCD의 아키텍처를 설명해주세요"

**30초 답변**:
ArgoCD는 세 가지 핵심 컴포넌트로 구성됩니다. API Server는 Web UI와 CLI의 백엔드로 RBAC과 SSO를 처리합니다. Repo Server는 Git 저장소를 클론하고 Helm/Kustomize로 매니페스트를 렌더링합니다. Application Controller가 핵심 엔진으로, Git의 Desired State와 Cluster의 Live State를 주기적으로 비교하고 차이가 있으면 Sync를 실행합니다.

**2분 답변**:
ArgoCD의 아키텍처는 관심사 분리(Separation of Concerns) 원칙을 따릅니다. API Server는 gRPC/REST 기반으로 Web UI, CLI(argocd), CI 시스템의 진입점입니다. Dex와 연동하여 OIDC/LDAP/SAML 기반 SSO 인증을 처리하고, RBAC 정책을 적용하여 팀별 접근 제어가 가능합니다. Repo Server는 Git 저장소를 클론하고 캐싱합니다. Helm Template, Kustomize Build, Jsonnet 등으로 최종 K8s 매니페스트를 렌더링하는 역할입니다. 렌더링 결과를 Redis에 캐시하여 반복 요청의 성능을 높입니다. Application Controller가 가장 중요한 컴포넌트입니다. 기본 3분 주기로 Git 저장소를 폴링(Polling)하여 Desired State를 확인하고, K8s API를 통해 Live State를 조회합니다. 두 상태를 비교하여 차이(Diff)가 있으면 OutOfSync로 표시하고, Auto Sync가 설정되어 있으면 자동으로 Sync를 실행합니다. Health Check도 Controller가 담당하여 Deployment의 Available Condition, Pod의 Ready 상태 등을 종합적으로 판단합니다. 이 외에 Redis(캐시), Dex(SSO), Notification Controller(Slack/Teams 알림)가 보조 역할을 합니다. 멀티 클러스터 환경에서는 ArgoCD를 관리 클러스터에만 설치하고, 원격 클러스터에는 K8s API를 통해 배포합니다.

**💡 경험 연결**:
폐쇄망 환경에서 ArgoCD를 운영할 때 Repo Server의 Git 인증이 핵심 과제였습니다. 내부 CA 인증서를 argocd-tls-certs-cm ConfigMap에 등록하고, 폴링 주기를 1분으로 조정하여 배포 반영 속도를 높인 경험이 있습니다.

**⚠️ 주의**:
컴포넌트를 단순 나열하지 말고, 데이터 흐름(Git → Repo Server → Controller → Cluster)을 중심으로 설명할 것. "Controller가 핵심"이라는 점을 강조.

---

### Q: "Application CRD의 Sync Policy를 설명해주세요"

**30초 답변**:
Sync Policy는 Auto Sync, Prune, Self-heal 세 가지가 핵심입니다. Auto Sync는 Git 변경 감지 시 자동 배포, Prune은 Git에서 삭제된 리소스를 클러스터에서도 제거, Self-heal은 kubectl edit 같은 수동 변경을 Git 상태로 자동 복구합니다. 운영 환경에서는 Manual Sync + Self-heal 조합이 일반적입니다.

**2분 답변**:
Sync Policy는 배포 동작의 자동화 수준을 결정합니다. Auto Sync를 켜면 Git 변경이 감지될 때 자동으로 Sync가 실행됩니다. Dev/Staging 환경에서 적합하고, 운영 환경에서는 의도하지 않은 배포를 방지하기 위해 Manual Sync를 사용합니다. Prune은 Git에서 매니페스트를 삭제했을 때 해당 K8s 리소스도 함께 삭제하는 기능입니다. PruneLast 옵션을 함께 설정하면 다른 리소스가 먼저 Sync된 후 마지막에 정리되어 순서 문제를 방지합니다. Self-heal은 Drift Detection의 핵심입니다. 누군가 kubectl로 직접 Deployment의 replicas를 변경하거나 ConfigMap을 수정하면 ArgoCD가 이를 감지하고 Git에 정의된 상태로 자동 복구합니다. 운영 환경에서도 Self-heal은 켜두는 것을 권장하는데, 긴급 수동 변경이 다음 Sync 때 덮어씌워지는 것보다 즉시 복구되는 것이 운영 일관성에 유리하기 때문입니다. ignoreDifferences를 활용하면 HPA가 관리하는 replicas처럼 자동 변경되는 필드는 Diff에서 제외할 수 있습니다. syncOptions에서는 CreateNamespace, ServerSideApply, ApplyOutOfSyncOnly 등 세부 동작을 제어합니다.

**💡 경험 연결**:
운영 환경에서 Self-heal 없이 ArgoCD를 운영했더니 누군가 kubectl edit로 환경변수를 변경한 것을 다음 Sync 때까지 발견하지 못한 적이 있습니다. 이후 Self-heal을 활성화하고 Notification으로 "자동 복구 발생" 알림을 설정하여 비인가 변경을 즉시 감지하도록 개선했습니다.

**⚠️ 주의**:
"전부 Auto로 설정하면 됩니다"라고 하면 운영 경험이 없어 보인다. 환경별 차등 적용과 ignoreDifferences의 필요성(HPA 충돌 방지)을 언급하면 깊이가 더해진다.

---

### Q: "ArgoCD에서 Secret은 어떻게 관리하나요?"

**30초 답변**:
Git에 평문 Secret을 저장하면 안 되므로 세 가지 접근법이 있습니다. Sealed Secrets는 클러스터 내 Controller가 복호화하므로 외부 의존성이 없습니다. External Secrets Operator는 AWS Secrets Manager나 Vault에서 런타임에 Secret을 가져옵니다. SOPS는 파일 레벨 암호화로 KMS 키를 사용합니다.

**2분 답변**:
GitOps에서 Secret 관리는 "Git에 Secret을 어떻게 안전하게 저장하거나, Git 외부에서 어떻게 주입할 것인가"의 문제입니다. 첫째, Sealed Secrets는 kubeseal CLI로 Secret을 암호화하여 SealedSecret CRD로 Git에 저장합니다. 클러스터의 Sealed Secrets Controller만 복호화할 수 있으므로 Git 저장소가 유출되어도 안전합니다. 폐쇄망에서 외부 의존성 없이 사용할 수 있는 장점이 있습니다. 둘째, External Secrets Operator(ESO)는 AWS Secrets Manager, HashiCorp Vault, Azure Key Vault 같은 외부 시크릿 저장소와 연동합니다. ExternalSecret CRD를 Git에 저장하면 ESO가 외부 저장소에서 값을 가져와 K8s Secret을 자동 생성합니다. 시크릿 로테이션도 자동화할 수 있습니다. 셋째, SOPS(Secrets OPerationS)는 YAML 파일의 values만 암호화합니다. ArgoCD의 Helm Secrets 플러그인이나 KSOPS(Kustomize 플러그인)로 복호화를 자동화합니다. AWS KMS, GCP KMS, PGP 키를 사용합니다. Allganize처럼 AWS/Azure 멀티클라우드 환경이라면 ESO가 가장 적합합니다. 각 클라우드의 네이티브 시크릿 서비스를 통합 관리할 수 있기 때문입니다.

**💡 경험 연결**:
폐쇄망 환경에서는 외부 시크릿 서비스가 없었으므로 Sealed Secrets를 사용했습니다. 클러스터 재구축 시 Sealing Key를 백업/복원하는 프로세스를 만들어 운영한 경험이 있습니다.

**⚠️ 주의**:
"Vault 쓰면 됩니다" 한 줄로 끝내지 말 것. Sealed Secrets, ESO, SOPS의 차이와 각각의 적합한 환경을 설명해야 한다. 특히 ESO는 최근 표준으로 자리잡고 있음을 언급.

---

### Q: "App of Apps와 ApplicationSet의 차이는?"

**30초 답변**:
App of Apps는 루트 Application이 하위 Application YAML 파일을 관리하는 정적 패턴입니다. ApplicationSet은 Generator(Git Directory, Cluster Label, Matrix)를 사용하여 Application을 동적으로 생성하는 컨트롤러입니다. 서비스가 자주 추가/삭제되면 ApplicationSet이, 명시적 관리가 필요하면 App of Apps가 적합합니다.

**2분 답변**:
App of Apps 패턴은 ArgoCD 초기부터 사용된 방식으로, 하나의 루트 Application이 apps-of-apps/ 디렉토리의 Application YAML을 관리합니다. 새 서비스를 추가하려면 YAML 파일을 직접 작성하고 Git에 Push합니다. 명시적이고 직관적이지만, 서비스가 50개 이상이면 YAML 파일 관리가 번거롭습니다. ApplicationSet은 Generator 기반으로 Application을 자동 생성합니다. Git Directory Generator는 특정 디렉토리 구조에서 각 하위 디렉토리마다 Application을 생성합니다. Cluster Generator는 라벨로 선택된 클러스터들에 동일한 앱을 배포합니다. Matrix Generator는 클러스터와 서비스의 조합을 만듭니다. 예를 들어 3개 클러스터 x 10개 서비스 = 30개 Application을 하나의 ApplicationSet으로 관리할 수 있습니다. 실무에서는 두 패턴을 혼합합니다. 플랫폼 컴포넌트(Monitoring, Logging, Ingress)는 명시적으로 App of Apps로 관리하고, 비즈니스 서비스는 ApplicationSet으로 동적 관리합니다.

**💡 경험 연결**:
마이크로서비스 20개 이상인 환경에서 App of Apps를 사용하다가 ApplicationSet의 Git Directory Generator로 전환한 경험이 있습니다. 새 서비스를 추가할 때 Application YAML을 별도로 작성할 필요 없이 디렉토리만 추가하면 되어 온보딩이 크게 간소화되었습니다.

**⚠️ 주의**:
ApplicationSet은 ArgoCD v2.3+ 부터 내장된 기능이다. "ApplicationSet Controller를 별도 설치해야 한다"고 하면 버전 정보가 오래된 것이므로 주의.

---

## Allganize 맥락

- **Alli AI 마이크로서비스**: App of Apps 또는 ApplicationSet으로 API, Web, Worker, ML Pipeline 등 다수의 서비스를 일괄 관리할 수 있다
- **AWS EKS + Azure AKS**: ArgoCD 멀티 클러스터 관리 기능으로 단일 ArgoCD에서 양쪽 클라우드의 K8s 클러스터를 통합 배포 가능
- **GitOps 보안**: RBAC으로 팀별 앱 접근을 제어하고, External Secrets Operator로 AWS Secrets Manager/Azure Key Vault 연동
- **배포 안정성**: Sync Wave로 DB Migration → Backend → Frontend 순서를 보장하고, Health Check로 배포 후 자동 검증
- **면접 포인트**: Application CRD의 세부 필드(syncPolicy, ignoreDifferences, syncOptions)를 구체적으로 설명할 수 있으면 실무 경험이 느껴진다

---
**핵심 키워드**: `ArgoCD` `Application CRD` `Sync Policy` `Self-heal` `App of Apps` `ApplicationSet` `Health Check`
