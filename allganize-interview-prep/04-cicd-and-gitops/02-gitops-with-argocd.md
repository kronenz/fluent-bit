# GitOps와 ArgoCD (GitOps with ArgoCD)

> **TL;DR**
> - GitOps는 Git 저장소를 Single Source of Truth로 삼아 인프라와 애플리케이션을 선언적으로 관리하는 운영 모델이다
> - ArgoCD는 K8s 네이티브(Native) GitOps 도구로, Git 매니페스트와 클러스터 상태를 자동으로 동기화(Sync)한다
> - 폐쇄망에서도 Pull 기반 배포로 보안 우위를 가지며, App of Apps 패턴으로 대규모 환경을 관리한다

---

## 1. GitOps 핵심 개념

### GitOps란?

Git 저장소에 시스템의 원하는 상태(Desired State)를 선언적(Declarative)으로 정의하고,
자동화된 프로세스가 실제 상태(Actual State)를 원하는 상태에 맞추는 운영 방식이다.

### GitOps 4대 원칙 (CNCF 정의)

```
1. 선언적 (Declarative)
   → 시스템의 원하는 상태를 선언적으로 기술한다
   → K8s YAML, Helm Chart, Kustomize

2. 버전 관리 (Versioned and Immutable)
   → 원하는 상태는 Git에 저장되어 버전 관리된다
   → Git 히스토리 = 변경 이력 = 감사 로그(Audit Log)

3. 자동 적용 (Pulled Automatically)
   → 승인된 변경은 자동으로 시스템에 적용된다
   → Pull 기반: Agent가 Git을 감시하고 변경을 감지

4. 지속적 조정 (Continuously Reconciled)
   → Agent가 실제 상태와 원하는 상태의 차이를 감지하고 자동 복구한다
   → Drift Detection + Self-healing
```

### Push vs Pull 배포 모델

```
[Push 기반 - 전통적 CI/CD]
CI Server ──(kubectl apply)──→ K8s Cluster
           네트워크 밖에서 안으로
           → CI에 클러스터 인증 정보 필요
           → 보안 위험

[Pull 기반 - GitOps]
Git Repo ←──(watch)── ArgoCD (클러스터 내부)
                         │
                         ├── 변경 감지
                         └── 클러스터에 적용
           → 클러스터 인증 정보가 외부에 노출되지 않음
           → 폐쇄망에서 보안 우위
```

---

## 2. ArgoCD 아키텍처

### 핵심 컴포넌트

```
┌─────────────────────────────────────────────┐
│                ArgoCD                        │
│                                              │
│  ┌──────────────┐  ┌─────────────────────┐  │
│  │  API Server   │  │ Application          │  │
│  │               │  │ Controller           │  │
│  │ - Web UI      │  │                      │  │
│  │ - gRPC/REST   │  │ - Git 폴링(Polling)  │  │
│  │ - RBAC        │  │ - 상태 비교           │  │
│  │ - SSO 연동    │  │ - Sync 실행          │  │
│  └──────┬───────┘  │ - Health Check       │  │
│         │          └──────────┬────────────┘  │
│         │                     │               │
│  ┌──────┴───────┐             │               │
│  │ Repo Server   │             │               │
│  │               │             │               │
│  │ - Git Clone   │◄────────────┘               │
│  │ - Helm 렌더링 │                              │
│  │ - Kustomize   │                              │
│  │ - Jsonnet     │                              │
│  └──────────────┘                              │
│                                                │
│  ┌──────────────┐  ┌──────────────┐           │
│  │ Redis         │  │ Dex (SSO)    │           │
│  │ (캐시)        │  │ (인증)       │           │
│  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────┘
```

**API Server:**
- Web UI와 CLI(argocd)의 백엔드
- RBAC(Role-Based Access Control) 정책 적용
- SSO(Single Sign-On) 연동 (OIDC, LDAP, SAML)

**Application Controller:**
- Git 저장소를 주기적으로 폴링(기본 3분)
- 원하는 상태(Git)와 실제 상태(Cluster)를 비교
- Sync 작업 실행, Health Check 수행

**Repo Server:**
- Git 저장소 클론(Clone) 및 캐싱
- Helm Template, Kustomize Build 등 매니페스트 렌더링
- 렌더링 결과를 Application Controller에 전달

---

## 3. ArgoCD 설치 및 기본 설정

### 설치

```bash
# Namespace 생성 및 ArgoCD 설치
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 폐쇄망: 매니페스트를 사전 다운로드하여 적용
# kubectl apply -n argocd -f ./argocd-install.yaml

# CLI 설치
curl -sSL -o argocd \
  https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x argocd && sudo mv argocd /usr/local/bin/

# 초기 비밀번호 확인
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d

# 로그인
argocd login argocd.example.com --grpc-web
```

### Git 저장소 등록

```bash
# HTTPS (폐쇄망 내부 Git)
argocd repo add https://git.internal.corp/team/k8s-manifests.git \
  --username deploy \
  --password ${GIT_TOKEN} \
  --insecure-skip-server-verification    # 내부 CA 사용 시

# SSH
argocd repo add git@git.internal.corp:team/k8s-manifests.git \
  --ssh-private-key-path ~/.ssh/id_rsa
```

---

## 4. Application CRD와 Sync 전략

### Application CRD 기본 구조

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: backend-app
  namespace: argocd
  # Finalizer: Application 삭제 시 K8s 리소스도 함께 삭제
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default

  # Source: Git 저장소 정보
  source:
    repoURL: https://git.internal.corp/team/k8s-manifests.git
    targetRevision: main
    path: apps/backend          # 매니페스트 경로

  # Destination: 배포 대상 클러스터
  destination:
    server: https://kubernetes.default.svc    # in-cluster
    namespace: backend

  # Sync Policy: 동기화 전략
  syncPolicy:
    automated:
      prune: true           # Git에서 삭제된 리소스를 클러스터에서도 삭제
      selfHeal: true         # 수동 변경(Drift)을 자동 복구
      allowEmpty: false      # 빈 매니페스트 방지
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true       # 다른 리소스 Sync 후 마지막에 Prune
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

### Sync 전략 상세

| 전략 | 설명 | 사용 시점 |
|------|------|----------|
| Manual Sync | 수동으로 Sync 실행 | 운영 환경, 신중한 배포 필요 시 |
| Auto Sync | Git 변경 감지 시 자동 Sync | 개발/스테이징 환경 |
| Prune | Git에서 삭제된 리소스 제거 | 리소스 정리가 필요할 때 |
| Self-heal | 수동 변경 자동 복구 | Drift 방지가 중요할 때 |

### Helm 기반 Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring-stack
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.internal.corp/team/helm-charts.git
    targetRevision: main
    path: charts/monitoring
    helm:
      releaseName: monitoring
      valueFiles:
        - values.yaml
        - values-production.yaml    # 환경별 오버라이드
      parameters:
        - name: grafana.replicas
          value: "2"
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
```

### Kustomize 기반 Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: frontend-production
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.internal.corp/team/k8s-manifests.git
    targetRevision: main
    path: apps/frontend/overlays/production    # Kustomize overlay 경로
  destination:
    server: https://kubernetes.default.svc
    namespace: frontend
```

---

## 5. App of Apps 패턴

### 개념

하나의 "루트(Root) Application"이 여러 Application을 관리하는 패턴이다.
대규모 환경에서 수십 개의 서비스를 일괄 관리할 때 사용한다.

```
Root App (apps-of-apps)
  ├── backend-app
  ├── frontend-app
  ├── monitoring-app
  ├── logging-app
  └── ingress-app
```

### 디렉토리 구조

```
k8s-manifests/
├── apps-of-apps/           # 루트 Application
│   ├── backend.yaml        # 각 서비스의 Application CRD
│   ├── frontend.yaml
│   ├── monitoring.yaml
│   └── logging.yaml
├── apps/
│   ├── backend/
│   │   ├── base/
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   └── kustomization.yaml
│   │   └── overlays/
│   │       ├── dev/
│   │       ├── staging/
│   │       └── production/
│   └── frontend/
│       ├── base/
│       └── overlays/
└── platform/
    ├── monitoring/
    └── logging/
```

### 루트 Application

```yaml
# root-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: apps-of-apps
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.internal.corp/team/k8s-manifests.git
    targetRevision: main
    path: apps-of-apps    # 하위 Application CRD가 있는 디렉토리
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd      # Application CRD는 argocd 네임스페이스에 생성
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 하위 Application 예시

```yaml
# apps-of-apps/backend.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: backend
  namespace: argocd
  labels:
    team: backend
    env: production
spec:
  project: default
  source:
    repoURL: https://git.internal.corp/team/k8s-manifests.git
    targetRevision: main
    path: apps/backend/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: backend
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

---

## 6. ArgoCD 운영 팁

### RBAC 설정

```yaml
# argocd-rbac-cm ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.csv: |
    # 역할 정의
    p, role:dev-team, applications, get, default/*, allow
    p, role:dev-team, applications, sync, default/*, allow
    p, role:ops-team, applications, *, */*, allow
    p, role:ops-team, clusters, get, *, allow

    # 그룹 매핑 (SSO 그룹)
    g, dev-team-group, role:dev-team
    g, ops-team-group, role:ops-team
  policy.default: role:readonly
```

### Notification 설정

```yaml
# argocd-notifications-cm
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
      send: [app-sync-succeeded]
  template.app-sync-succeeded: |
    message: |
      Application {{.app.metadata.name}} 동기화 완료
      Revision: {{.app.status.sync.revision}}
      Environment: {{.app.spec.destination.namespace}}
```

### Health Check 커스터마이징

```yaml
# argocd-cm ConfigMap에 추가
data:
  resource.customizations.health.argoproj.io_Rollout: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.currentPodHash ~= nil then
        hs.status = "Healthy"
        hs.message = "Rollout is healthy"
      else
        hs.status = "Progressing"
        hs.message = "Waiting for rollout"
      end
    end
    return hs
```

---

## 7. ArgoCD vs Flux 비교

| 항목 | ArgoCD | Flux v2 |
|------|--------|---------|
| Web UI | 내장 (강력) | 별도 설치 (Weave GitOps) |
| 멀티 클러스터 | 중앙 집중 관리 | 각 클러스터에 설치 |
| SSO/RBAC | 내장 (Dex) | K8s RBAC 활용 |
| Helm 지원 | Template 렌더링 | Helm Controller |
| 이미지 자동 업데이트 | ArgoCD Image Updater | 내장 (Image Reflector) |
| 아키텍처 | 단일 배포 | 마이크로서비스 (Toolkit) |
| 학습 곡선 | 중간 | 높음 |
| **추천 환경** | **UI 필요, 멀티 클러스터** | **경량, 자동화 중심** |

---

## 8. 폐쇄망에서 ArgoCD 운영

```
[폐쇄망 ArgoCD 구성]

내부 Git (GitLab/Gitea)
    │
    ├── manifests repo ◄──── ArgoCD Repo Server (폴링)
    │                              │
    │                              ▼
    │                     Application Controller
    │                              │
    │                              ▼
    └──────────────────── K8s Cluster에 배포

[핵심 포인트]
1. ArgoCD 이미지를 내부 Harbor에 사전 반입
2. 내부 Git 서버 인증서를 ArgoCD에 등록
3. Helm Chart 저장소도 내부에 구축 (ChartMuseum)
4. Webhook 대신 폴링(Polling) 방식 활용
```

```bash
# 내부 CA 인증서 등록
kubectl -n argocd create configmap argocd-tls-certs-cm \
  --from-file=git.internal.corp=/path/to/internal-ca.crt

# 폴링 주기 조정 (기본 3분 → 1분)
kubectl -n argocd edit configmap argocd-cm
# data:
#   timeout.reconciliation: 60s
```

---

## 9. 면접 Q&A

### Q1. "GitOps가 무엇이고, 왜 중요한가요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "GitOps는 Git을 Single Source of Truth로 삼아 인프라와 애플리케이션의 원하는 상태를
> 선언적으로 관리하는 운영 모델입니다. 핵심은 4가지인데, 선언적 정의, 버전 관리,
> 자동 적용, 지속적 조정입니다.
> 가장 큰 장점은 감사 추적(Audit Trail)입니다. 누가, 언제, 무엇을 변경했는지
> Git 커밋 히스토리에 모두 남습니다. 폐쇄망에서 보안 감사 요구사항을 충족할 때
> 이 점이 특히 유용했습니다.
> 또한 Pull 기반이라 클러스터 인증 정보를 외부에 노출하지 않아 보안에 유리합니다."

### Q2. "ArgoCD의 아키텍처를 설명해주세요"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "ArgoCD는 크게 3개 컴포넌트로 구성됩니다.
> API Server는 Web UI와 CLI의 백엔드로, RBAC과 SSO를 담당합니다.
> Repo Server는 Git 저장소를 클론하고 Helm이나 Kustomize로 매니페스트를 렌더링합니다.
> Application Controller가 핵심인데, Git의 원하는 상태와 클러스터의 실제 상태를
> 주기적으로 비교하고, 차이가 있으면 Sync를 실행합니다.
> Self-heal을 활성화하면 누군가 kubectl로 직접 수정해도 Git 상태로 자동 복구됩니다."

### Q3. "Auto Sync와 Manual Sync는 언제 각각 사용하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "개발/스테이징 환경에서는 Auto Sync를 켜서 Git Push만 하면 바로 반영되게 하고,
> 운영 환경에서는 Manual Sync로 설정하여 의도한 시점에 배포합니다.
> Auto Sync에서 Prune 옵션은 Git에서 삭제된 리소스를 클러스터에서도 제거하는 것이고,
> Self-heal은 Drift를 자동 복구하는 것입니다.
> 운영 환경에서도 Self-heal은 켜두는 것을 권장하는데,
> kubectl edit로 긴급 수정한 것이 다음 배포 때 덮어씌워지는 것을 방지하기 위해서입니다."

### Q4. "App of Apps 패턴은 왜 사용하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "마이크로서비스가 20-30개 이상인 환경에서 Application CRD를 하나씩 수동으로
> 만들면 관리가 어렵습니다. App of Apps 패턴은 루트 Application이 하위 Application을
> 자동으로 생성하고 관리하므로, 새 서비스를 추가할 때 YAML 파일 하나만 Git에
> Push하면 ArgoCD가 자동으로 Application을 생성합니다.
> 폐쇄망에서 수십 개 서비스를 운영할 때 이 패턴으로 배포 관리를 크게 단순화했습니다."

### Q5. "GitOps에서 Secret은 어떻게 관리하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "Git에 평문 Secret을 저장하면 안 되므로, 몇 가지 방법이 있습니다.
> 첫째, Sealed Secrets를 사용하면 암호화된 형태로 Git에 저장하고
> 클러스터의 Controller가 복호화합니다.
> 둘째, External Secrets Operator로 Vault나 AWS Secrets Manager에서
> 런타임에 Secret을 가져올 수 있습니다.
> 셋째, SOPS(Secrets OPerationS)로 파일 레벨 암호화도 가능합니다.
> 폐쇄망에서는 Sealed Secrets이 외부 의존성이 없어서 가장 적합했습니다."

---

## 키워드 (Keywords)

`GitOps` `ArgoCD` `Declarative` `App of Apps` `Self-heal`
