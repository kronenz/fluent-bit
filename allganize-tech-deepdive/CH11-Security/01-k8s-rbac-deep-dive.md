# Kubernetes RBAC Deep Dive

> **TL;DR**: RBAC(Role-Based Access Control)은 Kubernetes에서 "누가(Subject) 무엇을(Resource) 어떻게(Verb) 할 수 있는가"를 제어하는 인가 메커니즘이다.
> Role/ClusterRole로 권한을 정의하고, RoleBinding/ClusterRoleBinding으로 Subject에 연결하며, ServiceAccount는 Pod 내 워크로드의 Identity를 담당한다.
> OIDC 연동을 통해 외부 IdP(Azure AD, Keycloak 등)와 통합하면 사용자 인증을 중앙화할 수 있다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### RBAC 아키텍처 전체 흐름

```
  Client (kubectl / Pod)
       │
       ▼
  ┌──────────────────────────────────────────┐
  │            kube-apiserver                  │
  │                                           │
  │  1. Authentication (인증)                  │
  │     ├── X.509 Client Cert                 │
  │     ├── Bearer Token (ServiceAccount)     │
  │     ├── OIDC Token (Azure AD, Keycloak)   │
  │     └── Webhook Token Review              │
  │                                           │
  │  2. Authorization (인가) ◄── RBAC HERE     │
  │     ├── Role / ClusterRole                │
  │     └── RoleBinding / ClusterRoleBinding  │
  │                                           │
  │  3. Admission Control (정책)               │
  └──────────────────────────────────────────┘
```

### Role vs ClusterRole

| 구분 | Role | ClusterRole |
|------|------|-------------|
| 범위 | 특정 Namespace 내 | 클러스터 전체 |
| 리소스 | Namespace 리소스 (Pod, Service 등) | Namespace + Cluster 리소스 (Node, PV, Namespace 등) |
| 사용 시나리오 | 팀별 권한 분리 | 관리자, 노드 관리, CRD 접근 |

```yaml
# Role: 특정 namespace의 Pod 읽기 권한
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: ai-serving
  name: pod-reader
rules:
- apiGroups: [""]          # core API group
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/log"]   # subresource
  verbs: ["get"]
```

```yaml
# ClusterRole: 클러스터 전체 노드 조회 + CRD 관리
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-viewer
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apiextensions.k8s.io"]
  resources: ["customresourcedefinitions"]
  verbs: ["get", "list"]
```

### RoleBinding vs ClusterRoleBinding

```
  Subject (User / Group / ServiceAccount)
       │
       │  binds to
       ▼
  ┌─────────────┐       ┌────────────┐
  │ RoleBinding  │──────►│   Role     │   ← Namespace 범위
  └─────────────┘       └────────────┘

  ┌──────────────────┐  ┌─────────────┐
  │ClusterRoleBinding │─►│ ClusterRole │   ← 클러스터 범위
  └──────────────────┘  └─────────────┘

  ┌─────────────┐       ┌─────────────┐
  │ RoleBinding  │──────►│ ClusterRole │   ← ClusterRole를 특정 NS에 한정
  └─────────────┘       └─────────────┘
```

**핵심 패턴**: ClusterRole을 RoleBinding으로 연결하면 재사용 가능한 권한 템플릿을 Namespace별로 적용할 수 있다.

```yaml
# RoleBinding: ClusterRole 'pod-reader'를 특정 NS에 바인딩
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dev-team-pod-reader
  namespace: ai-serving
subjects:
- kind: Group
  name: "dev-team"           # OIDC group claim
  apiGroup: rbac.authorization.k8s.io
- kind: ServiceAccount
  name: ai-model-sa
  namespace: ai-serving
roleRef:
  kind: ClusterRole          # ClusterRole을 NS 범위로 제한
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

### ServiceAccount (SA)

Pod 내부 워크로드의 **Identity**. 모든 Pod는 반드시 하나의 ServiceAccount로 실행된다.

```
  Pod 생성 시
       │
       ▼
  ┌─────────────────────────────────┐
  │ ServiceAccount Token Mount      │
  │                                 │
  │  /var/run/secrets/              │
  │    kubernetes.io/serviceaccount/│
  │      ├── token    (JWT)         │  ◄── Projected Volume (1.21+)
  │      ├── ca.crt   (CA cert)    │      시간 제한 + 대상 제한
  │      └── namespace             │
  └─────────────────────────────────┘
```

**Projected ServiceAccount Token (1.21+)**:
- 기존: 만료 없는 static token (Secret에 저장)
- 현재: 시간 제한(expirationSeconds), 대상 제한(audience) 적용된 **Bound Token**
- `automountServiceAccountToken: false`로 불필요한 토큰 마운트 방지

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ai-model-sa
  namespace: ai-serving
  annotations:
    # AWS IRSA (IAM Roles for ServiceAccounts)
    eks.amazonaws.com/role-arn: "arn:aws:iam::123456789:role/ai-model-s3-access"
automountServiceAccountToken: false   # 명시적으로 필요한 Pod에서만 마운트
```

### OIDC Integration

```
  사용자 (브라우저)
       │
       │ 1. 로그인
       ▼
  ┌──────────────┐
  │   IdP         │  Azure AD / Keycloak / Okta
  │   (OIDC)      │
  └──────┬───────┘
         │ 2. id_token (JWT) 발급
         ▼
  ┌──────────────┐
  │   kubectl     │  --token=<id_token>
  │   kubelogin   │  또는 OIDC plugin
  └──────┬───────┘
         │ 3. API 요청 + Bearer Token
         ▼
  ┌──────────────────────────────┐
  │   kube-apiserver              │
  │   --oidc-issuer-url           │
  │   --oidc-client-id            │
  │   --oidc-username-claim=email │
  │   --oidc-groups-claim=groups  │
  └──────────────────────────────┘
         │ 4. JWT 검증 → username/groups 추출
         │ 5. RBAC 평가
         ▼
      Allow / Deny
```

**EKS 환경**: `aws-auth` ConfigMap 또는 EKS Access Entry로 IAM → K8s RBAC 매핑

```yaml
# aws-auth ConfigMap (EKS)
apiVersion: v1
kind: ConfigMap
metadata:
  name: aws-auth
  namespace: kube-system
data:
  mapRoles: |
    - rolearn: arn:aws:iam::123456789:role/devops-role
      username: devops-admin
      groups:
        - system:masters
    - rolearn: arn:aws:iam::123456789:role/dev-role
      username: developer
      groups:
        - dev-team
```

### Aggregated ClusterRoles

```yaml
# Label 기반으로 ClusterRole을 자동 집계
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-aggregate
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.example.com/aggregate-to-monitoring: "true"
rules: []  # 자동으로 채워짐
```

---

## 실전 예시

### RBAC 권한 확인 (Troubleshooting)

```bash
# 현재 사용자의 권한 확인
kubectl auth can-i create deployments --namespace ai-serving
# yes / no

# 특정 ServiceAccount의 권한 확인
kubectl auth can-i list pods \
  --namespace ai-serving \
  --as system:serviceaccount:ai-serving:ai-model-sa

# 전체 권한 목록 확인
kubectl auth can-i --list --namespace ai-serving

# 특정 사용자의 전체 권한 (impersonation)
kubectl auth can-i --list \
  --as developer@company.com \
  --namespace ai-serving
```

### Least Privilege 원칙 적용

```yaml
# BAD: 과도한 권한
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["*"]

# GOOD: 최소 권한
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch"]
  resourceNames: ["ai-model-v1", "ai-model-v2"]  # 특정 리소스만
```

### IRSA (IAM Roles for ServiceAccounts) - EKS

```yaml
# 1. ServiceAccount에 IAM Role 연결
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ai-model-sa
  namespace: ai-serving
  annotations:
    eks.amazonaws.com/role-arn: "arn:aws:iam::123456789:role/s3-reader"

# 2. Pod에서 SA 사용
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-model
spec:
  template:
    spec:
      serviceAccountName: ai-model-sa
      containers:
      - name: model
        image: company/ai-model:v1
        # AWS SDK가 자동으로 IRSA 토큰 사용
```

---

## 면접 Q&A

### Q: RBAC에서 Role과 ClusterRole의 차이점과 사용 시나리오를 설명해주세요.
**30초 답변**:
Role은 특정 Namespace 내 리소스에 대한 권한을 정의하고, ClusterRole은 클러스터 전체 범위의 권한을 정의합니다. ClusterRole을 RoleBinding으로 연결하면 동일한 권한 템플릿을 여러 Namespace에 재사용할 수 있어 관리 효율이 높습니다.

**2분 답변**:
Role은 특정 Namespace에 한정되며 Pod, Service, Deployment 같은 Namespace 리소스에 대한 접근 권한을 정의합니다. ClusterRole은 Node, PersistentVolume, Namespace 같은 Cluster-scoped 리소스와 비리소스 URL(`/healthz` 등)에 대한 권한까지 포괄합니다. 실무에서 가장 유용한 패턴은 ClusterRole을 공통 권한 템플릿으로 정의하고, 각 Namespace에 RoleBinding으로 연결하는 것입니다. 예를 들어 `pod-reader` ClusterRole 하나를 만들고, 팀별 Namespace에 RoleBinding을 생성하면 권한 정의의 일관성을 유지하면서 Namespace 격리도 보장됩니다. 또한 Aggregated ClusterRole을 사용하면 Label 기반으로 여러 ClusterRole을 자동 합산할 수 있어, Operator나 CRD 추가 시 기존 Role을 수정하지 않고 권한을 확장할 수 있습니다.

**💡 경험 연결**:
폐쇄망 환경에서 팀별로 Namespace를 분리하고, 각 팀에 최소 권한 RBAC를 적용한 경험이 있습니다. 초기에는 팀마다 개별 Role을 만들었는데, 권한 변경 시 N개의 Role을 모두 수정해야 하는 문제가 발생했습니다. ClusterRole + RoleBinding 패턴으로 전환한 후 관리 포인트가 크게 줄었습니다.

**⚠️ 주의**:
`system:masters` 그룹에 바인딩하는 ClusterRoleBinding은 apiserver 수준에서 하드코딩된 슈퍼유저 권한이므로, Admission Controller로도 제한할 수 없다. 운영 환경에서는 절대 일반 사용자에게 부여하면 안 된다.

### Q: ServiceAccount와 IRSA(IAM Roles for ServiceAccounts)의 동작 원리를 설명해주세요.
**30초 답변**:
ServiceAccount는 Pod의 Identity를 담당하며, IRSA는 EKS에서 Kubernetes SA와 AWS IAM Role을 OIDC Federation으로 연결하여 Pod가 AWS 리소스에 안전하게 접근하도록 합니다. Node 전체에 IAM Role을 부여하는 것보다 훨씬 세밀한 권한 제어가 가능합니다.

**2분 답변**:
ServiceAccount는 Pod 내 프로세스의 Identity입니다. Kubernetes 1.21부터 Projected Volume 기반의 Bound ServiceAccount Token이 기본이며, 시간 제한과 대상(audience) 제한이 적용됩니다. IRSA의 동작 원리는 다음과 같습니다. EKS가 OIDC Provider를 노출하고, AWS IAM에 이 OIDC Provider를 신뢰하는 IAM Role을 생성합니다. Pod가 시작되면 Projected SA Token(JWT)이 마운트되고, AWS SDK는 `sts:AssumeRoleWithWebIdentity` API를 호출하여 이 JWT로 임시 자격 증명을 받습니다. 이렇게 하면 Node의 Instance Profile에 과도한 권한을 부여하지 않고도, Pod 단위로 S3, SQS 등 AWS 리소스에 접근할 수 있습니다. Allganize에서 AI 모델이 S3의 학습 데이터에 접근하거나, SQS 큐를 읽어야 한다면 IRSA로 Pod 단위 권한을 부여하는 것이 보안 모범 사례입니다.

**💡 경험 연결**:
온프레미스에서는 ServiceAccount 토큰이 만료 없이 Secret에 저장되는 레거시 방식이었는데, Bound Token으로 전환하면서 토큰 탈취 위험을 크게 줄인 경험이 있습니다. 클라우드로 전환한다면 IRSA/Pod Identity 같은 클라우드 네이티브 인증을 적극 활용할 것입니다.

**⚠️ 주의**:
IRSA 설정 시 Trust Policy의 Condition에 `sub` 필드(system:serviceaccount:NAMESPACE:SA_NAME)를 반드시 명시해야 한다. 와일드카드를 쓰면 다른 Namespace의 SA도 해당 IAM Role을 assume할 수 있다.

### Q: Kubernetes OIDC 연동을 통한 사용자 인증 구조를 설명해주세요.
**30초 답변**:
apiserver의 OIDC 플래그를 설정하면 외부 IdP(Azure AD, Keycloak 등)가 발급한 JWT를 검증하여 사용자를 인증합니다. JWT의 claim에서 username과 groups를 추출하고, 이를 RBAC Subject와 매핑하여 인가를 수행합니다.

**2분 답변**:
Kubernetes apiserver는 자체적으로 사용자 DB를 갖지 않으므로, 외부 IdP에 인증을 위임합니다. OIDC 연동 시 apiserver에 `--oidc-issuer-url`, `--oidc-client-id`, `--oidc-username-claim`, `--oidc-groups-claim`을 설정합니다. 사용자가 kubectl로 API를 호출하면, kubelogin 같은 credential plugin이 OIDC Authorization Code Flow로 IdP에서 id_token을 받아 Bearer Token으로 전송합니다. apiserver는 IdP의 JWKS로 토큰 서명을 검증하고, claim에서 사용자 이름과 그룹을 추출합니다. 이 그룹 정보를 RBAC의 Group Subject와 매핑하면, IdP에서 그룹 멤버십을 변경하는 것만으로 Kubernetes 권한을 제어할 수 있습니다. EKS에서는 aws-auth ConfigMap이나 EKS Access Entry를 통해 IAM 주체를 K8s 사용자/그룹으로 매핑합니다. Azure AKS에서는 Azure AD 통합이 기본 지원되어 `az aks` 명령으로 OIDC를 쉽게 활성화할 수 있습니다.

**💡 경험 연결**:
폐쇄망 환경에서 내부 LDAP을 Dex(OIDC proxy)와 연동하여 Kubernetes 인증을 구현한 경험이 있습니다. LDAP 그룹을 K8s RBAC 그룹에 매핑하여, Active Directory 그룹 멤버십 변경만으로 클러스터 접근 권한을 관리했습니다.

**⚠️ 주의**:
OIDC 토큰은 apiserver가 직접 IdP에 revocation 여부를 확인하지 않으므로, 토큰 만료 시간을 짧게 설정(15분 이내)해야 한다. 사용자 퇴사 시 즉시 접근 차단이 필요하면 Webhook Token Authentication을 함께 사용하는 것이 좋다.

### Q: RBAC 설정 시 흔히 하는 실수와 Least Privilege 원칙 적용 방법은?
**30초 답변**:
가장 흔한 실수는 `*` 와일드카드로 모든 권한을 부여하는 것과, default ServiceAccount를 그대로 사용하는 것입니다. Least Privilege는 필요한 API 그룹, 리소스, Verb만 명시하고, resourceNames로 특정 리소스까지 제한하는 것입니다.

**2분 답변**:
첫째, `apiGroups: ["*"], resources: ["*"], verbs: ["*"]`는 클러스터 관리자에게조차 위험합니다. 실수로 etcd를 삭제하거나 RBAC 자체를 변경할 수 있기 때문입니다. 둘째, default ServiceAccount는 Namespace마다 자동 생성되며, 여러 Pod가 공유하므로 권한 격리가 불가능합니다. Pod마다 전용 SA를 생성하고 `automountServiceAccountToken: false`를 기본으로 설정해야 합니다. 셋째, `escalate`와 `bind` verb에 대한 이해가 부족하면 권한 상승 공격에 취약해집니다. 사용자가 자신보다 높은 권한의 Role을 생성하거나 바인딩할 수 없도록 이 verb를 제한해야 합니다. 실무적으로는 OPA/Gatekeeper나 Kyverno 같은 Policy Engine으로 RBAC 규칙 자체를 검증하는 정책을 추가하는 것이 좋습니다.

**💡 경험 연결**:
보안 감사에서 default ServiceAccount에 cluster-admin이 바인딩된 것을 발견한 경험이 있습니다. 이후 모든 Namespace에 default SA의 automountServiceAccountToken을 false로 설정하고, Pod별 전용 SA를 의무화하는 정책을 Kyverno로 적용했습니다.

**⚠️ 주의**:
`kubectl auth can-i`는 RBAC만 확인하며, Admission Controller(OPA, Kyverno)의 추가 제한은 반영하지 않는다. 실제 허용 여부는 Admission 단계까지 포함해야 정확하다.

---

## Allganize 맥락

- **멀티테넌시 격리**: Allganize SaaS에서 고객별 Namespace를 분리할 때, ClusterRole + RoleBinding 패턴으로 일관된 권한 템플릿을 적용하면 고객 간 데이터 격리를 보장할 수 있다.
- **AI 모델 서빙 Pod의 AWS 접근**: LLM 모델이 S3에서 모델 가중치를 로드하거나, Bedrock API를 호출할 때 IRSA로 Pod 단위 IAM 권한을 부여하는 것이 필수다.
- **CI/CD 파이프라인 권한**: ArgoCD, Flux 같은 GitOps 도구의 ServiceAccount에는 배포에 필요한 최소 권한만 부여하고, 클러스터 관리 권한은 분리해야 한다.
- **폐쇄망 경험 활용**: 온프레미스에서의 RBAC 설계 경험(팀별 격리, 감사 추적)은 클라우드 환경에서도 직접 활용 가능하며, "보안 원칙은 환경이 달라도 동일하다"는 관점을 면접에서 보여줄 수 있다.
- **JD 연관**: "보안 정책 수립/운영"에 직접 대응하는 주제. RBAC 설계 역량은 DevOps 엔지니어의 핵심 보안 역량이다.

---
**핵심 키워드**: `RBAC` `Role` `ClusterRole` `RoleBinding` `ServiceAccount` `OIDC` `IRSA` `Least-Privilege` `Bound-Token`
