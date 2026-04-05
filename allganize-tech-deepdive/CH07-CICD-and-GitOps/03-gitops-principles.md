# GitOps 원칙 (GitOps Principles)

> **TL;DR**
> - GitOps는 Git을 Single Source of Truth로 삼아 인프라와 애플리케이션을 선언적으로 관리하는 운영 모델이다
> - Push 모델(전통적 CI/CD)은 CI 서버가 클러스터에 직접 배포하고, Pull 모델(GitOps)은 클러스터 내 Agent가 Git을 감시한다
> - Pull 모델은 클러스터 인증 정보를 외부에 노출하지 않아 보안에 유리하며, Drift Detection과 Self-healing이 자연스럽게 구현된다

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### GitOps란?

2017년 Weaveworks의 Alexis Richardson이 제안한 운영 모델로, Git 저장소에 시스템의 원하는 상태(Desired State)를 선언적(Declarative)으로 정의하고, 자동화된 프로세스가 실제 상태(Actual State)를 원하는 상태와 일치시키는 방식이다.

### CNCF GitOps 4대 원칙

```
┌────────────────────────────────────────────────────────────────┐
│                  CNCF GitOps Principles (2021)                 │
│                                                                │
│  1. Declarative (선언적)                                       │
│     "원하는 상태를 선언적으로 기술한다"                           │
│     → K8s YAML, Helm Chart, Kustomize, Terraform HCL          │
│     → "어떻게(How)" 가 아니라 "무엇(What)"을 정의              │
│                                                                │
│  2. Versioned and Immutable (버전 관리 + 불변)                  │
│     "원하는 상태는 불변 저장소에 버전 관리된다"                   │
│     → Git commit = 변경 이력 = 감사 로그(Audit Log)            │
│     → git revert = 즉시 롤백                                   │
│     → PR/MR = 변경 승인 프로세스                                │
│                                                                │
│  3. Pulled Automatically (자동 Pull)                            │
│     "승인된 변경은 자동으로 시스템에 적용된다"                    │
│     → Pull 기반: Agent가 Git을 감시하고 변경을 적용             │
│     → Webhook 또는 Polling으로 변경 감지                        │
│                                                                │
│  4. Continuously Reconciled (지속적 조정)                       │
│     "Agent가 지속적으로 Desired vs Actual 상태를 비교한다"       │
│     → Drift Detection: 수동 변경을 감지                         │
│     → Self-healing: 자동으로 원하는 상태로 복구                  │
│     → Reconciliation Loop: 감시 → 비교 → 조정 → 반복           │
└────────────────────────────────────────────────────────────────┘
```

### Push vs Pull 배포 모델

```
[Push 모델 - 전통적 CI/CD]

 Developer                CI Server              K8s Cluster
    │                        │                       │
    │── git push ──────────→ │                       │
    │                        │── build ──→ Image     │
    │                        │── test               │
    │                        │── kubectl apply ────→ │
    │                        │   (직접 배포)          │
    │                        │                       │
    │   CI 서버가 Cluster 인증 정보(kubeconfig)를     │
    │   보유해야 한다 → 보안 위험                      │

[Pull 모델 - GitOps]

 Developer       Git Repo        GitOps Agent        K8s Cluster
    │                │            (ArgoCD/Flux)           │
    │── git push ──→ │                │                   │
    │                │ ←── poll/watch │                   │
    │                │                │── 변경 감지        │
    │                │                │── Desired vs Live  │
    │                │                │── kubectl apply ──→│
    │                │                │   (클러스터 내부)    │
    │                │                │                    │
    │   Agent가 클러스터 내부에서 동작하므로               │
    │   외부에 인증 정보를 노출하지 않는다                  │
```

### Push vs Pull 상세 비교

| 비교 항목 | Push 모델 | Pull 모델 (GitOps) |
|-----------|-----------|-------------------|
| **배포 주체** | CI 서버 (외부) | GitOps Agent (클러스터 내부) |
| **인증 정보** | CI에 kubeconfig 필요 | Agent는 in-cluster 인증 |
| **보안** | 외부에서 내부 접근 필요 | 내부에서 외부(Git)만 접근 |
| **Drift Detection** | 없음 (배포 후 모름) | 지속적 감시 |
| **Self-healing** | 없음 | 자동 복구 |
| **감사(Audit)** | CI 로그 확인 필요 | Git 히스토리 = 감사 로그 |
| **롤백** | CI 재실행 또는 kubectl | git revert → 자동 적용 |
| **상태 가시성** | CI 대시보드 | GitOps UI (ArgoCD 등) |
| **방화벽** | CI → Cluster 인바운드 필요 | Agent → Git 아웃바운드만 필요 |

### 보안 이점 상세

```
┌────────────────────────────────────────────────────────────────┐
│              GitOps Security Benefits                           │
│                                                                │
│  1. 최소 노출 원칙 (Least Exposure)                             │
│     ● 클러스터 인증 정보가 CI 서버에 없음                        │
│     ● Agent는 Git에 대한 읽기 권한만 필요                        │
│     ● 네트워크는 아웃바운드(Agent→Git)만 필요                    │
│                                                                │
│  2. 감사 추적 (Audit Trail)                                     │
│     ● 모든 변경 = Git 커밋 (누가, 언제, 무엇을)                 │
│     ● PR 리뷰 = 변경 승인 기록                                  │
│     ● git blame = 변경 책임자 추적                               │
│     ● 규제 산업(금융, 공공) 컴플라이언스 충족                     │
│                                                                │
│  3. 변경 통제 (Change Control)                                   │
│     ● PR + Code Review = 4-eyes 원칙                            │
│     ● Branch Protection = 직접 push 차단                        │
│     ● CODEOWNERS = 팀별 리뷰어 지정                             │
│     ● kubectl 직접 변경 → Self-heal로 차단                      │
│                                                                │
│  4. 재현 가능성 (Reproducibility)                                │
│     ● 특정 시점의 시스템 상태 = 해당 Git 커밋                    │
│     ● 재해 복구(DR) 시 Git에서 전체 시스템 재구축 가능            │
│     ● "이 환경을 그대로 복제해줘" = git checkout + ArgoCD Sync   │
└────────────────────────────────────────────────────────────────┘
```

### Git 저장소 전략

```
[단일 저장소 (Monorepo)]

k8s-manifests/
├── apps/
│   ├── alli-api/
│   │   ├── base/
│   │   └── overlays/
│   │       ├── dev/
│   │       ├── staging/
│   │       └── production/
│   ├── alli-web/
│   └── alli-worker/
├── platform/
│   ├── monitoring/
│   ├── logging/
│   └── ingress/
└── README.md

장점: 전체 시스템 상태를 한 눈에 파악, 크로스 서비스 변경이 하나의 커밋
단점: 권한 분리 어려움, 규모가 커지면 관리 복잡

[멀티 저장소 (Polyrepo)]

github.com/allganize/alli-api-manifests
github.com/allganize/alli-web-manifests
github.com/allganize/platform-manifests

장점: 팀별 독립적 관리, 세밀한 접근 제어
단점: 크로스 서비스 변경 시 여러 저장소 수정 필요
```

```
[앱 코드 vs 매니페스트 저장소 분리]

┌─────────────────┐      ┌──────────────────────┐
│  App Source Repo │      │  K8s Manifests Repo  │
│  (application    │      │  (deployment config) │
│   code + CI)     │      │                      │
│                  │      │  apps/               │
│  src/            │      │   alli-api/          │
│  tests/          │      │     deployment.yaml  │
│  Dockerfile      │      │     service.yaml     │
│  .github/        │      │     values.yaml      │
│    workflows/    │      │                      │
│      ci.yaml     │      │  ArgoCD가 감시       │
└────────┬─────────┘      └──────────┬───────────┘
         │                           │
         │  CI: 이미지 빌드 후        │
         │  매니페스트 저장소의        │
         │  이미지 태그를 업데이트     │
         └───────────────────────────┘

이유:
● 앱 코드 변경과 배포 설정 변경의 라이프사이클이 다르다
● CI 트리거(코드 Push)와 CD 트리거(매니페스트 변경)를 분리
● 매니페스트 저장소에 대한 PR 리뷰 = 배포 승인 프로세스
```

### Reconciliation Loop

GitOps Agent의 핵심 동작 원리이다.

```
┌────────────────────────────────────────────────────┐
│              Reconciliation Loop                    │
│                                                    │
│         ┌──────────┐                               │
│         │  Observe  │ ◄─── Git Repo (Desired)      │
│         │  (관찰)   │ ◄─── K8s API (Actual)        │
│         └─────┬─────┘                              │
│               │                                    │
│               ▼                                    │
│         ┌──────────┐                               │
│         │  Compare  │                              │
│         │  (비교)   │ Desired == Actual ?           │
│         └─────┬─────┘                              │
│               │                                    │
│          ┌────┴────┐                               │
│          │         │                               │
│       동일      다름(Drift)                         │
│          │         │                               │
│          ▼         ▼                               │
│    ┌─────────┐  ┌──────────┐                      │
│    │  Wait   │  │  Act     │                      │
│    │ (대기)  │  │  (조정)  │ → kubectl apply       │
│    └────┬────┘  └────┬─────┘                      │
│         │            │                             │
│         └────────────┘                             │
│               │                                    │
│               ▼                                    │
│         다시 Observe (무한 반복)                     │
└────────────────────────────────────────────────────┘

주기: ArgoCD 기본 3분 / Flux 기본 1분
Webhook으로 즉시 트리거도 가능
```

### Drift Detection과 Self-healing

```
[Drift 시나리오]

1. 운영자가 긴급 패치로 kubectl edit deployment/alli-api
   → replicas: 3 → 5로 변경

2. ArgoCD가 다음 Reconciliation에서 Drift 감지
   → Desired(Git): replicas: 3
   → Actual(Cluster): replicas: 5
   → Status: OutOfSync

3-A. Self-heal OFF:
   → ArgoCD UI에 OutOfSync 표시 (경고만)
   → 수동 Sync 필요

3-B. Self-heal ON:
   → ArgoCD가 자동으로 replicas를 3으로 복구
   → Notification으로 "Drift 복구됨" 알림 발송

[올바른 긴급 변경 프로세스]
   → Git에 PR 생성 → 긴급 승인 → Merge → ArgoCD Auto Sync
   → 또는 ArgoCD CLI로 수동 Sync
```

### GitOps와 IaC의 관계

```
┌─────────────────────────────────────────────────┐
│          GitOps는 IaC의 상위 집합이 아니다        │
│          GitOps는 IaC의 "운영 모델"이다            │
│                                                 │
│  IaC (Infrastructure as Code)                    │
│  → 인프라를 코드로 정의한다                        │
│  → Terraform, Pulumi, CloudFormation             │
│  → "무엇을 선언할 것인가"                          │
│                                                 │
│  GitOps                                          │
│  → IaC 코드를 Git에서 관리하고 자동 적용한다       │
│  → ArgoCD, Flux, Terraform Cloud                 │
│  → "어떻게 운영할 것인가"                          │
│                                                 │
│  IaC + GitOps = 선언적 코드 + 자동화된 운영        │
└─────────────────────────────────────────────────┘
```

---

## 실전 예시

### GitOps 기반 배포 워크플로우 (전체 흐름)

```
[1] 개발자가 앱 코드 수정 후 PR 생성
    └── github.com/allganize/alli-api (앱 저장소)

[2] CI 파이프라인 실행 (GitHub Actions)
    ├── Lint → Build → Test → Scan
    ├── 이미지 빌드: ghcr.io/allganize/alli-api:abc1234
    └── 이미지 Push to Registry

[3] CI가 매니페스트 저장소 업데이트 (자동화)
    └── github.com/allganize/k8s-manifests
        └── apps/alli-api/overlays/production/kustomization.yaml
            └── images.newTag: abc1234 (이전: def5678)

[4] ArgoCD가 매니페스트 저장소 변경 감지
    └── OutOfSync 감지

[5] Sync 실행 (Auto 또는 Manual)
    └── K8s Cluster에 새 이미지로 Deployment 업데이트

[6] Health Check 통과 확인
    └── Healthy → 배포 완료
    └── Degraded → Notification 알림 + 자동 롤백 또는 수동 대응
```

### CI에서 매니페스트 저장소 업데이트 자동화

```yaml
# .github/workflows/cd-trigger.yaml (앱 저장소의 CI)
update-manifest:
  needs: image-build
  runs-on: ubuntu-latest
  steps:
    - name: Checkout manifest repo
      uses: actions/checkout@v4
      with:
        repository: allganize/k8s-manifests
        token: ${{ secrets.MANIFEST_REPO_TOKEN }}
        path: manifests

    - name: Update image tag
      run: |
        cd manifests/apps/alli-api/overlays/production
        kustomize edit set image \
          ghcr.io/allganize/alli-api=ghcr.io/allganize/alli-api:${{ github.sha }}

    - name: Commit and push
      run: |
        cd manifests
        git config user.name "github-actions[bot]"
        git config user.email "github-actions[bot]@users.noreply.github.com"
        git add .
        git commit -m "chore(alli-api): update image to ${{ github.sha }}"
        git push
```

### ArgoCD Image Updater (자동 이미지 업데이트)

```yaml
# Application에 annotation으로 설정
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: alli-api
  annotations:
    # Image Updater가 레지스트리를 감시하고 새 태그를 자동 반영
    argocd-image-updater.argoproj.io/image-list: >
      alli-api=ghcr.io/allganize/alli-api
    argocd-image-updater.argoproj.io/alli-api.update-strategy: semver
    argocd-image-updater.argoproj.io/alli-api.allow-tags: regexp:^v[0-9]+\.[0-9]+\.[0-9]+$
    argocd-image-updater.argoproj.io/write-back-method: git
    argocd-image-updater.argoproj.io/write-back-target: kustomization
```

### 재해 복구(DR) 시나리오

```bash
# 시나리오: 프로덕션 클러스터가 완전히 손실

# 1. 새 K8s 클러스터 프로비저닝
terraform apply -var="cluster_name=eks-prod-recovered"

# 2. ArgoCD 설치
helm install argocd argo/argo-cd --namespace argocd --create-namespace \
  -f argocd-values.yaml

# 3. Git 저장소 등록
argocd repo add https://github.com/allganize/k8s-manifests.git \
  --username deploy --password ${GIT_TOKEN}

# 4. Root Application 적용 (App of Apps)
kubectl apply -f root-application.yaml

# 5. ArgoCD가 Git에서 모든 Application을 자동 복구
#    → 전체 시스템이 Git에 정의된 상태로 재구축

# Git이 Single Source of Truth이므로
# 별도의 백업/복원 없이 시스템 전체를 재현할 수 있다
# (단, Persistent Volume의 데이터는 별도 백업 필요)
```

---

## 면접 Q&A

### Q: "GitOps란 무엇이고, 왜 중요한가요?"

**30초 답변**:
GitOps는 Git을 Single Source of Truth로 삼아 인프라와 앱을 선언적으로 관리하는 운영 모델입니다. CNCF가 정의한 4대 원칙은 선언적 정의, 버전 관리, 자동 적용, 지속적 조정입니다. 핵심 가치는 감사 추적(Git 히스토리), 보안(Pull 기반), 재현 가능성(Git에서 전체 시스템 복구)입니다.

**2분 답변**:
GitOps는 2017년 Weaveworks가 제안한 운영 모델로, Git 저장소에 시스템의 Desired State를 선언적으로 정의하고, 자동화된 Agent가 실제 상태를 맞추는 방식입니다. 중요한 이유는 네 가지입니다. 첫째, 감사 추적입니다. 모든 변경이 Git 커밋으로 기록되므로 "누가, 언제, 무엇을, 왜 변경했는가"를 완벽하게 추적할 수 있습니다. 규제 산업(금융, 공공)의 컴플라이언스 요구사항을 자연스럽게 충족합니다. 둘째, 보안입니다. Pull 모델에서는 클러스터 내부의 Agent가 Git을 감시하므로, CI 서버에 클러스터 인증 정보를 저장하지 않습니다. 네트워크도 아웃바운드(Agent→Git)만 필요하여 방화벽 설정이 간단합니다. 셋째, 재현 가능성입니다. 특정 시점의 시스템 상태가 Git 커밋으로 기록되므로, 재해 복구 시 새 클러스터에 ArgoCD를 설치하고 Git 저장소를 연결하면 전체 시스템을 재구축할 수 있습니다. 넷째, Drift Detection입니다. 누군가 kubectl로 수동 변경해도 Agent가 이를 감지하고, Self-heal이 설정되어 있으면 Git 상태로 자동 복구합니다. "환경 간 설정이 달라서 문제가 발생하는" Configuration Drift를 근본적으로 방지합니다.

**💡 경험 연결**:
폐쇄망에서 수동 배포(kubectl apply)를 하다가 운영 환경의 설정이 개발 환경과 달라진 것을 뒤늦게 발견한 경험이 있습니다. GitOps로 전환하면서 모든 변경이 Git을 거치도록 강제했고, Drift 발생 시 알림을 받아 즉시 대응할 수 있게 되었습니다.

**⚠️ 주의**:
"GitOps는 ArgoCD를 쓰는 것입니다"라고 축소하지 말 것. GitOps는 원칙/패러다임이고, ArgoCD는 그 구현체 중 하나라는 점을 명확히 할 것.

---

### Q: "Push 모델과 Pull 모델의 차이를 설명해주세요"

**30초 답변**:
Push 모델은 CI 서버가 kubectl apply로 클러스터에 직접 배포합니다. CI에 kubeconfig가 필요하므로 보안 위험이 있고, 배포 후 Drift를 감지하지 못합니다. Pull 모델은 클러스터 내부의 Agent(ArgoCD)가 Git을 감시하고 변경을 자동 적용합니다. 인증 정보가 외부에 노출되지 않고, 지속적으로 상태를 조정합니다.

**2분 답변**:
Push 모델은 전통적 CI/CD 방식으로 Jenkins나 GitHub Actions가 빌드 후 kubectl apply나 helm upgrade로 클러스터에 직접 배포합니다. 이 방식의 근본적 문제는 CI 서버가 클러스터의 인증 정보(kubeconfig, Service Account Token)를 보유해야 한다는 점입니다. CI 서버가 해킹되면 클러스터도 위험해집니다. 또한 배포 후 누군가 kubectl로 수동 변경해도 CI 서버는 이를 알 수 없어 Configuration Drift가 발생합니다. Pull 모델에서는 ArgoCD나 Flux 같은 Agent가 클러스터 내부에서 동작합니다. Agent는 Git 저장소에 대한 읽기 권한만 필요하고, 클러스터 인증은 in-cluster ServiceAccount로 자동 처리됩니다. 네트워크 관점에서도 Agent가 Git으로 나가는 아웃바운드만 필요하여, 폐쇄망 환경에서 방화벽 규칙이 훨씬 간단합니다. Reconciliation Loop로 지속적으로 Desired와 Actual 상태를 비교하므로, 수동 변경(Drift)을 즉시 감지하고 복구합니다. 다만 Pull 모델도 단점이 있습니다. Git 저장소 가용성에 의존하므로 Git 서버 장애 시 새로운 배포가 불가능합니다. 또한 긴급 변경 시 "Git → PR → Merge → Sync"의 단계가 느릴 수 있어 Break Glass 절차(긴급 시 직접 배포 허용)를 별도로 마련해야 합니다.

**💡 경험 연결**:
Pull 모델 도입 전에는 Jenkins 서버에 모든 클러스터의 kubeconfig가 있었습니다. 보안 감사에서 지적을 받아 ArgoCD로 전환했고, CI는 이미지 빌드까지만, 배포는 ArgoCD가 담당하도록 분리한 경험이 있습니다.

**⚠️ 주의**:
Pull 모델의 장점만 나열하지 말 것. Git 서버 의존성, 긴급 배포의 느린 속도 등 단점도 언급하면 균형잡힌 시각을 보여줄 수 있다.

---

### Q: "GitOps에서 앱 코드 저장소와 매니페스트 저장소를 분리하는 이유는?"

**30초 답변**:
두 가지 이유입니다. 첫째, 라이프사이클이 다릅니다. 앱 코드 변경은 빌드와 테스트를 거치지만, 매니페스트 변경(replicas 조정, 환경변수 변경)은 빌드 없이 배포만 필요합니다. 둘째, 관심사 분리입니다. 개발자는 앱 코드에, 운영자는 배포 설정에 집중할 수 있고, 각각 다른 PR 리뷰/승인 프로세스를 적용할 수 있습니다.

**2분 답변**:
앱 저장소와 매니페스트 저장소의 분리는 GitOps 모범 사례입니다. 가장 큰 이유는 변경 주기와 관심사가 다르기 때문입니다. 앱 코드 변경은 CI 파이프라인(빌드, 테스트, 스캔)을 거쳐야 하지만, 배포 설정 변경(replicas 조정, 리소스 변경, 환경변수 추가)은 CI 없이 바로 배포될 수 있습니다. 이 둘을 같은 저장소에 두면 코드 변경 없이 설정만 바꿔도 전체 CI가 실행되거나, 반대로 CI 실패가 설정 변경 배포까지 막을 수 있습니다. 두 번째 이유는 접근 제어입니다. 매니페스트 저장소에는 운영팀과 SRE만 쓰기 권한을 가지고, 앱 저장소에는 개발팀이 쓰기 권한을 가집니다. CODEOWNERS 파일로 리뷰어를 분리하고, Branch Protection으로 승인 프로세스를 다르게 적용합니다. 세 번째는 보안입니다. 매니페스트 저장소에는 환경별 설정, 리소스 정의, 네트워크 정책 등 운영 민감 정보가 포함될 수 있습니다. 앱 개발자가 이를 직접 수정하는 것보다 PR을 통해 운영팀 리뷰를 받는 것이 안전합니다. 연결 방법은 CI 파이프라인이 이미지를 빌드한 후 매니페스트 저장소의 이미지 태그를 업데이트하는 커밋을 자동으로 생성합니다. 또는 ArgoCD Image Updater가 레지스트리를 감시하고 매니페스트 저장소를 자동 업데이트할 수도 있습니다.

**💡 경험 연결**:
초기에는 앱 코드와 K8s 매니페스트를 같은 저장소에 두었는데, 개발자가 Dockerfile만 수정해도 불필요한 ArgoCD Sync가 트리거되는 문제가 있었습니다. 저장소를 분리하면서 CI와 CD의 트리거가 명확하게 분리되었고, 불필요한 배포가 제거되었습니다.

**⚠️ 주의**:
분리의 장점만 강조하면 "항상 분리해야 한다"로 들릴 수 있다. 소규모 팀이나 초기 프로젝트에서는 Monorepo가 더 간단할 수 있다는 점도 언급하면 현실적이다.

---

### Q: "GitOps의 한계점은 무엇인가요?"

**30초 답변**:
세 가지 한계가 있습니다. Git 서버 의존성(Git 장애 시 새 배포 불가), 긴급 변경의 느린 속도(Git PR 프로세스를 거쳐야 함), Secret 관리의 복잡성(Git에 평문 Secret 저장 불가)입니다. 각각 Git HA 구성, Break Glass 절차, Sealed Secrets/ESO로 대응합니다.

**2분 답변**:
GitOps는 강력하지만 만능이 아닙니다. 첫째, Git 서버 가용성에 대한 의존입니다. Git 서버가 다운되면 새로운 배포가 불가능합니다. 이미 배포된 서비스는 영향이 없지만, 긴급 패치가 필요한 상황에서는 치명적일 수 있습니다. Git 서버의 HA(High Availability) 구성이 필수적입니다. 둘째, 긴급 변경 대응입니다. 모든 변경이 "코드 수정 → PR → 리뷰 → 머지 → Sync"를 거쳐야 하므로, 장애 상황에서 즉시 대응하기 어려울 수 있습니다. 이를 위해 Break Glass 절차를 마련합니다. 긴급 시 ArgoCD Auto Sync를 일시 중지하고 kubectl로 직접 패치한 후, 사후에 Git에 반영하는 프로세스입니다. 셋째, Secret 관리입니다. Git에 평문 Secret을 저장할 수 없으므로 Sealed Secrets, External Secrets Operator, SOPS 같은 별도 도구가 필요합니다. 넷째, 학습 곡선입니다. 기존 kubectl 기반 배포에 익숙한 팀에게 "Git을 통해서만 변경하라"는 문화 변화를 요구합니다. 다섯째, Stateful 리소스입니다. 데이터베이스 스키마 마이그레이션, PV 데이터 등은 GitOps만으로 관리하기 어렵고 별도 전략이 필요합니다.

**💡 경험 연결**:
GitOps 도입 초기에 운영자들이 "급한데 왜 PR을 써야 하냐"는 반발이 있었습니다. Break Glass 절차를 문서화하고, 긴급 변경 시에는 사후 Git 반영을 의무화하는 타협안으로 팀을 설득한 경험이 있습니다.

**⚠️ 주의**:
"GitOps는 완벽합니다"라고 하면 실무 경험이 없어 보인다. 한계를 인정하면서 각각의 대응 방안을 함께 제시하면 성숙한 엔지니어의 답변이 된다.

---

## Allganize 맥락

- **SaaS 환경**: 클라우드 기반이므로 Pull 모델(GitOps)의 보안 이점이 극대화된다. CI 서버에 EKS/AKS kubeconfig를 저장하지 않아도 된다
- **멀티클라우드 (AWS/Azure)**: Git을 Single Source of Truth로 두면 양쪽 클라우드에 동일한 설정을 일관되게 적용할 수 있다
- **AI/LLM 서비스**: 모델 버전과 서빙 설정을 Git으로 관리하면 "어떤 모델 버전이 언제 프로덕션에 배포되었는가"를 완벽히 추적할 수 있다
- **컴플라이언스**: AI 서비스의 규제 요구사항(모델 감사, 변경 이력)을 Git 히스토리로 충족할 수 있다
- **면접 포인트**: "Push vs Pull 모델의 차이"와 "GitOps의 보안 이점"을 구체적으로 설명하면 기본기가 탄탄한 인상을 준다

---
**핵심 키워드**: `GitOps` `Push vs Pull` `Single Source of Truth` `Reconciliation` `Drift Detection` `Self-healing` `Audit Trail`
