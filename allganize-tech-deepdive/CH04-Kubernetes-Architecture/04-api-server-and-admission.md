# API Server and Admission Control

> **TL;DR**: kube-apiserver는 모든 K8s 요청의 관문으로, Authentication(누구인가) → Authorization(무엇을 할 수 있는가, RBAC) → Admission Control(정책 적용, Mutating/Validating Webhook) 순서로 처리한다.
> RBAC의 4가지 리소스(Role, ClusterRole, RoleBinding, ClusterRoleBinding)와 Admission Webhook의 동작 원리를 이해해야 한다.
> 보안과 거버넌스의 핵심 지점이며, OPA/Gatekeeper, Kyverno 같은 정책 엔진과 연동된다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### API 요청 처리 전체 흐름

```
Client (kubectl, SDK, kubelet, controller)
  │
  │  HTTPS (TLS)
  ▼
┌──────────────────────────────────────────────────────┐
│                  kube-apiserver                       │
│                                                      │
│  1. ┌──────────────────┐                             │
│     │  Authentication   │  ← "누구인가?"              │
│     │  (인증)           │     X.509, Bearer Token,   │
│     │                   │     OIDC, ServiceAccount   │
│     └────────┬─────────┘                             │
│              ▼                                       │
│  2. ┌──────────────────┐                             │
│     │  Authorization    │  ← "무엇을 할 수 있는가?"   │
│     │  (인가)           │     RBAC, ABAC, Webhook,   │
│     │                   │     Node Authorization     │
│     └────────┬─────────┘                             │
│              ▼                                       │
│  3. ┌──────────────────┐                             │
│     │  Mutating         │  ← 리소스 수정 가능         │
│     │  Admission        │     (sidecar 주입,         │
│     │                   │      default 값 설정 등)    │
│     └────────┬─────────┘                             │
│              ▼                                       │
│  4. ┌──────────────────┐                             │
│     │  Schema           │  ← OpenAPI 스키마 검증      │
│     │  Validation       │                            │
│     └────────┬─────────┘                             │
│              ▼                                       │
│  5. ┌──────────────────┐                             │
│     │  Validating       │  ← 정책 검증 (거부만 가능)  │
│     │  Admission        │     (리소스 제한,           │
│     │                   │      이미지 정책 등)        │
│     └────────┬─────────┘                             │
│              ▼                                       │
│  6. ┌──────────────────┐                             │
│     │  etcd Write       │  ← 최종 저장               │
│     └──────────────────┘                             │
└──────────────────────────────────────────────────────┘
```

### 1. Authentication (인증)

요청자의 **신원을 확인**하는 단계. 여러 인증 방식을 동시에 활성화할 수 있으며, 하나라도 성공하면 통과.

**인증 방식:**

| 방식 | 대상 | 토큰/인증서 위치 |
|------|------|----------------|
| X.509 Client Cert | 사용자, 컴포넌트 | `--client-certificate`, `--client-key` |
| Bearer Token | ServiceAccount | `Authorization: Bearer <token>` 헤더 |
| OIDC | 사용자 (SSO) | ID Token (Google, Azure AD 등) |
| Webhook Token | 외부 시스템 | 외부 인증 서버에 위임 |
| Bootstrap Token | 노드 조인 | `kubeadm join` 시 사용 |

**ServiceAccount 토큰 (Projected Volume):**
```yaml
# K8s 1.22+: Bound ServiceAccount Token (시간 제한, 대상 제한)
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  serviceAccountName: my-sa
  automountServiceAccountToken: true
  # 자동으로 /var/run/secrets/kubernetes.io/serviceaccount/token 마운트
  # → JWT 토큰, 1시간 만료, 자동 갱신
```

### 2. Authorization (인가) - RBAC

인증된 사용자가 **어떤 리소스에 어떤 작업**을 할 수 있는지 결정.

**RBAC 4가지 리소스:**
```
┌─────────────────────────────────────────────────┐
│                 Namespace Scope                  │
│                                                 │
│  ┌────────┐         ┌─────────────┐             │
│  │  Role  │◄────────│ RoleBinding  │──► User/    │
│  │(권한)  │  참조    │  (연결)      │   Group/   │
│  └────────┘         └─────────────┘   SA        │
│                                                 │
├─────────────────────────────────────────────────┤
│                 Cluster Scope                    │
│                                                 │
│  ┌────────────┐     ┌──────────────────┐        │
│  │ClusterRole │◄────│ClusterRoleBinding │──► User│
│  │(권한)      │ 참조 │  (연결)           │  /SA  │
│  └────────────┘     └──────────────────┘        │
│                                                 │
│  ※ ClusterRole + RoleBinding = 특정 NS에만 적용  │
└─────────────────────────────────────────────────┘
```

**Role/ClusterRole 구조:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: production
  name: pod-reader
rules:
- apiGroups: [""]              # core API group
  resources: ["pods"]
  verbs: ["get", "watch", "list"]
- apiGroups: [""]
  resources: ["pods/log"]       # 서브리소스
  verbs: ["get"]
```

**RoleBinding 구조:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: production
subjects:
- kind: User
  name: jane
  apiGroup: rbac.authorization.k8s.io
- kind: ServiceAccount
  name: my-app-sa
  namespace: production
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

**RBAC 동사(Verbs) 매핑:**

| HTTP Method | RBAC Verb | 설명 |
|---|---|---|
| GET (단건) | get | 리소스 조회 |
| GET (목록) | list | 리소스 목록 |
| GET (watch) | watch | 변경 감시 |
| POST | create | 리소스 생성 |
| PUT | update | 리소스 전체 수정 |
| PATCH | patch | 리소스 부분 수정 |
| DELETE | delete | 리소스 삭제 |
| DELETE (목록) | deletecollection | 리소스 일괄 삭제 |

### 3. Admission Control

인증/인가를 통과한 요청에 대해 **추가 정책을 적용**하는 단계. **Mutating**(수정)과 **Validating**(검증) 두 단계로 구분.

**내장 Admission Controller (주요):**

| Controller | 유형 | 역할 |
|---|---|---|
| NamespaceLifecycle | Validating | 삭제 중인 NS에 리소스 생성 방지 |
| LimitRanger | Mutating | LimitRange에 따라 기본 리소스 설정 |
| ServiceAccount | Mutating | 기본 SA 토큰 자동 마운트 |
| DefaultStorageClass | Mutating | StorageClass 미지정 PVC에 기본값 |
| ResourceQuota | Validating | NS의 리소스 사용량 제한 |
| PodSecurity | Validating | Pod Security Standards 적용 (1.25+) |

**Webhook Admission Controller:**
```
apiserver ──► Mutating Webhooks ──► Validating Webhooks
                    │                      │
                    ▼                      ▼
              ┌──────────┐          ┌──────────┐
              │ Webhook   │          │ Webhook   │
              │ Server    │          │ Server    │
              │ (Pod)     │          │ (Pod)     │
              │           │          │           │
              │ 예: Istio  │          │ 예: OPA   │
              │ sidecar   │          │ Gatekeeper│
              │ 주입       │          │ 정책 검증  │
              └──────────┘          └──────────┘
```

**MutatingWebhookConfiguration 예시:**
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: sidecar-injector
webhooks:
- name: sidecar.example.com
  clientConfig:
    service:
      name: sidecar-injector
      namespace: istio-system
      path: "/inject"
    caBundle: <base64-encoded-ca>
  rules:
  - operations: ["CREATE"]
    apiGroups: [""]
    apiVersions: ["v1"]
    resources: ["pods"]
  namespaceSelector:
    matchLabels:
      sidecar-injection: enabled
  failurePolicy: Ignore        # Fail 또는 Ignore
  sideEffects: None
  admissionReviewVersions: ["v1"]
```

**ValidatingWebhookConfiguration 예시 (OPA Gatekeeper):**
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: gatekeeper-validating-webhook
webhooks:
- name: validation.gatekeeper.sh
  clientConfig:
    service:
      name: gatekeeper-webhook-service
      namespace: gatekeeper-system
      path: "/v1/admit"
  rules:
  - operations: ["CREATE", "UPDATE"]
    apiGroups: ["*"]
    apiVersions: ["*"]
    resources: ["*"]
  failurePolicy: Ignore     # 프로덕션에서는 Ignore로 시작, 안정화 후 Fail
  timeoutSeconds: 5          # Webhook 응답 타임아웃
```

### API Server Aggregation Layer

```
kubectl get --raw /apis
    │
    ▼
kube-apiserver
    │
    ├── /api/v1                    ← 내장 Core API
    ├── /apis/apps/v1              ← 내장 API Group
    ├── /apis/metrics.k8s.io/v1    ← Aggregated API (metrics-server)
    └── /apis/custom.io/v1         ← Aggregated API (custom)
         │
         ▼
    APIService → 외부 API Server로 프록시
```

---

## 실전 예시

### 인증 디버깅

```bash
# 현재 사용자 확인
kubectl auth whoami   # K8s 1.27+

# kubeconfig의 인증 정보 확인
kubectl config view --minify

# ServiceAccount 토큰 수동 생성
kubectl create token my-sa -n production --duration=24h

# 토큰 디코딩
kubectl get secret <sa-secret> -o jsonpath='{.data.token}' | base64 -d | \
  python3 -c "import sys,json; t=sys.stdin.read().split('.')[1]; \
  import base64; print(json.loads(base64.urlsafe_b64decode(t+'==')))"
```

### RBAC 확인 및 디버깅

```bash
# 특정 사용자의 권한 확인
kubectl auth can-i create pods --as jane -n production
kubectl auth can-i '*' '*' --as system:serviceaccount:default:my-sa

# 모든 권한 나열
kubectl auth can-i --list --as jane -n production

# 특정 Role/ClusterRole의 규칙 확인
kubectl describe role pod-reader -n production
kubectl describe clusterrole admin

# RBAC 문제 디버깅: apiserver 감사 로그에서 403 확인
# audit.log에서 "Forbidden" 검색
```

### RBAC 실전 설정: 개발팀용 Namespace 접근 제어

```yaml
# 1. Namespace 생성
apiVersion: v1
kind: Namespace
metadata:
  name: team-ai
  labels:
    team: ai
---
# 2. 개발자 Role (Pod/Deployment 관리, Secret 읽기만)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: team-ai
  name: developer
rules:
- apiGroups: ["", "apps"]
  resources: ["pods", "deployments", "services", "configmaps"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]           # Secret은 읽기만
- apiGroups: [""]
  resources: ["pods/log", "pods/exec"]
  verbs: ["get", "create"]         # 로그 확인, exec 허용
---
# 3. RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: developer-binding
  namespace: team-ai
subjects:
- kind: Group
  name: ai-developers              # OIDC 그룹과 매핑
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: developer
  apiGroup: rbac.authorization.k8s.io
```

### Admission Webhook 디버깅

```bash
# Webhook 설정 확인
kubectl get mutatingwebhookconfigurations
kubectl get validatingwebhookconfigurations

# Webhook 서버 로그 확인
kubectl logs -n gatekeeper-system deploy/gatekeeper-controller-manager

# Webhook 우회 (긴급 시)
kubectl label namespace kube-system admission.gatekeeper.sh/ignore=true

# 특정 리소스에 대한 Admission 결과 확인 (dry-run)
kubectl apply -f pod.yaml --dry-run=server -v=6
# → Webhook 호출 포함한 전체 파이프라인 테스트
```

### OPA Gatekeeper 정책 예시: 신뢰할 수 있는 레지스트리만 허용

```yaml
# ConstraintTemplate 정의
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sallowedrepos
spec:
  crd:
    spec:
      names:
        kind: K8sAllowedRepos
      validation:
        openAPIV3Schema:
          type: object
          properties:
            repos:
              type: array
              items:
                type: string
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8sallowedrepos
      violation[{"msg": msg}] {
        container := input.review.object.spec.containers[_]
        satisfied := [good | repo = input.parameters.repos[_]; good = startswith(container.image, repo)]
        not any(satisfied)
        msg := sprintf("container <%v> has an invalid image repo <%v>", [container.name, container.image])
      }
---
# Constraint 적용
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sAllowedRepos
metadata:
  name: allowed-repos
spec:
  match:
    kinds:
    - apiGroups: [""]
      kinds: ["Pod"]
    namespaces: ["production"]
  parameters:
    repos:
    - "123456789.dkr.ecr.ap-northeast-2.amazonaws.com/"
    - "ghcr.io/allganize/"
```

---

## 면접 Q&A

### Q: API 요청의 처리 흐름을 설명해주세요.
**30초 답변**:
API 요청은 Authentication(인증) → Authorization(인가, RBAC) → Mutating Admission → Schema Validation → Validating Admission → etcd 저장 순서로 처리됩니다. 각 단계에서 거부되면 요청이 즉시 실패합니다.

**2분 답변**:
kube-apiserver로 들어온 요청은 6단계를 거칩니다. 첫째, Authentication에서 X.509 인증서, Bearer Token, OIDC 등으로 요청자의 신원을 확인합니다. 여러 인증 방식이 체인으로 동작하며 하나만 성공하면 됩니다. 둘째, Authorization에서 RBAC 규칙에 따라 해당 사용자가 요청한 리소스에 대한 동사(verb) 권한이 있는지 확인합니다. 셋째, Mutating Admission에서 Webhook을 통해 리소스를 수정할 수 있습니다. 대표적으로 Istio의 sidecar 자동 주입이 이 단계에서 동작합니다. 넷째, Schema Validation에서 OpenAPI 스키마에 따라 리소스 형식을 검증합니다. 다섯째, Validating Admission에서 정책 위반 여부를 검증합니다. OPA Gatekeeper나 Kyverno가 이 단계에서 이미지 레지스트리 제한, 리소스 제한 등을 적용합니다. 마지막으로 모든 단계를 통과한 요청만 etcd에 저장됩니다. Mutating이 Validating 전에 실행되는 이유는, 수정된 최종 상태를 검증해야 하기 때문입니다.

**경험 연결**:
Webhook 서버가 응답 지연되면서 전체 Pod 생성이 막혔던 경험이 있습니다. failurePolicy를 Fail로 설정했기 때문인데, 이후 Ignore로 변경하고 Webhook 서버의 가용성을 별도로 모니터링하는 방식으로 개선했습니다.

**주의**:
Mutating Admission과 Validating Admission의 순서를 혼동하지 않도록 주의. "Mutating → Validation → Validating" 순서이며, Mutating에서 수정한 결과를 Validating이 최종 검증한다.

### Q: RBAC에서 Role과 ClusterRole의 차이를 설명해주세요.
**30초 답변**:
Role은 특정 Namespace 내에서만 유효한 권한을 정의하고, ClusterRole은 클러스터 전체 또는 비 Namespace 리소스(Node, PV 등)에 대한 권한을 정의합니다. ClusterRole을 RoleBinding으로 연결하면 특정 Namespace에만 적용할 수도 있습니다.

**2분 답변**:
Role은 Namespace 범위의 권한을 정의합니다. 예를 들어 "production 네임스페이스에서 Pod를 get/list/watch할 수 있다"를 Role로 정의하고 RoleBinding으로 사용자에게 부여합니다. ClusterRole은 두 가지 용도가 있습니다. 첫째, Node, PersistentVolume, Namespace 같은 비 Namespace 리소스에 대한 권한을 정의합니다. 이들은 ClusterRoleBinding으로만 부여할 수 있습니다. 둘째, 여러 Namespace에서 재사용할 공통 권한을 정의합니다. ClusterRole을 RoleBinding으로 연결하면 해당 Namespace에서만 유효하게 됩니다. 이 패턴은 "개발자" 같은 공통 역할을 ClusterRole로 한 번 정의하고, 각 팀의 Namespace에 RoleBinding으로 적용할 때 유용합니다. 기본 제공되는 ClusterRole로는 admin, edit, view가 있으며, 이들을 기반으로 확장하는 것이 권장됩니다. aggregated ClusterRole을 사용하면 label 기반으로 규칙을 자동 병합할 수도 있습니다.

**경험 연결**:
팀별로 Namespace를 분리하고 개발자에게 최소 권한을 부여하는 RBAC 설계를 수행한 경험이 있습니다. ClusterRole "developer"를 정의하고, 각 팀 Namespace에 RoleBinding으로 적용하여 관리 오버헤드를 줄였습니다.

**주의**:
cluster-admin ClusterRole은 모든 리소스에 대한 모든 권한을 가지므로 매우 신중하게 부여해야 한다. 운영 환경에서는 break-glass 절차로만 사용하는 것이 권장된다.

### Q: Admission Webhook의 failurePolicy를 Fail과 Ignore 중 어떻게 선택하나요?
**30초 답변**:
Fail은 Webhook이 응답하지 않으면 요청을 거부하여 보안은 강하지만 가용성이 낮습니다. Ignore는 Webhook 장애 시 요청을 허용하여 가용성은 높지만 정책을 우회할 수 있습니다. 보안 정책에는 Fail, 부가 기능(sidecar 주입 등)에는 Ignore가 적절합니다.

**2분 답변**:
failurePolicy 선택은 보안과 가용성의 트레이드오프입니다. Fail 모드에서는 Webhook 서버가 다운되면 해당 리소스의 모든 생성/수정이 차단됩니다. 컨테이너 이미지 정책처럼 보안이 절대적인 경우에 적합하지만, Webhook 서버 자체의 가용성(replicas, PDB, 우선순위)을 보장해야 합니다. Ignore 모드에서는 Webhook 장애 시 정책이 적용되지 않은 채 요청이 통과합니다. Istio sidecar 주입처럼 부가 기능에 적합하며, 주입이 안 되면 서비스가 동작은 하되 mesh에 포함되지 않는 정도의 영향입니다. 실무에서의 전략은: 도입 초기에는 Ignore로 시작하여 안정성을 검증하고, Webhook 서버의 SLA가 보장되면 Fail로 전환합니다. 또한 timeoutSeconds를 짧게(3-5초) 설정하여 Webhook 지연이 API 응답을 블로킹하지 않도록 합니다. namespaceSelector로 kube-system 같은 핵심 Namespace는 Webhook에서 제외하는 것이 안전합니다.

**경험 연결**:
OPA Gatekeeper를 도입할 때 처음에는 dryrun 모드로 위반 사항만 로깅하고, 3주간 안정화 후 deny 모드로 전환했습니다. failurePolicy도 Ignore에서 시작하여 Webhook 서버의 uptime이 99.9%를 달성한 후 Fail로 변경했습니다.

**주의**:
failurePolicy: Fail 설정 시, Webhook 서버가 속한 Namespace의 Pod 생성도 차단될 수 있다 (circular dependency). objectSelector나 namespaceSelector로 Webhook 서버 자체는 제외해야 한다.

---

## Allganize 맥락

- **OIDC 기반 인증**: Allganize에서 AWS EKS를 사용한다면, AWS IAM + OIDC로 개발자 인증을 구성할 가능성이 높다. `aws-iam-authenticator`나 EKS의 `aws-auth` ConfigMap을 이해해야 한다.
- **이미지 정책**: AI 모델 이미지는 신뢰할 수 있는 레지스트리(ECR)에서만 Pull하도록 Validating Webhook으로 강제할 수 있다. 공급망 보안(Supply Chain Security)의 첫 단계이다.
- **멀티테넌시 RBAC**: 여러 고객사의 AI 서비스를 하나의 클러스터에서 운영한다면, Namespace 기반 격리와 RBAC으로 접근 제어를 구현해야 한다. NetworkPolicy와 함께 적용하면 더 강력하다.
- **Admission Webhook 활용**: Allganize의 AI Pod에 GPU 리소스 요청이 없으면 거부하거나, 특정 label이 없으면 모니터링 sidecar를 자동 주입하는 등의 정책을 Webhook으로 구현할 수 있다.
- **폐쇄망 경험 활용**: 폐쇄망에서 인증서 기반 인증을 직접 구성한 경험은 K8s의 X.509 인증 이해에 직접적으로 연결된다. TLS 인증서의 CN(Common Name)이 K8s 사용자 이름으로 매핑되고, O(Organization)가 그룹으로 매핑되는 구조를 이해하고 있으면 강점이 된다.

---
**핵심 키워드**: `Authentication` `Authorization` `RBAC` `Role` `ClusterRole` `RoleBinding` `Admission-Control` `Mutating-Webhook` `Validating-Webhook` `OPA-Gatekeeper` `failurePolicy`
