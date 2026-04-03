# 06. RBAC과 보안 (RBAC and Security)

> **TL;DR**
> - K8s 보안은 **인증(Authentication) → 인가(Authorization, RBAC) → 어드미션 컨트롤(Admission Control)** 3단계다.
> - **RBAC**은 Role/ClusterRole로 권한을 정의하고, RoleBinding/ClusterRoleBinding으로 사용자/SA에 연결한다.
> - **PodSecurityStandard**, **OPA/Gatekeeper**, **Kyverno**로 워크로드 보안 정책을 강제한다.

---

## 1. K8s 보안 아키텍처

```
사용자/서비스 요청
     │
     ▼
┌─── Authentication (인증) ───┐
│ "누구인가?" (X.509, Token,   │
│  OIDC, ServiceAccount)      │
└─────────────┬───────────────┘
              ▼
┌─── Authorization (인가) ────┐
│ "무엇을 할 수 있는가?"       │
│ RBAC, ABAC, Webhook         │
└─────────────┬───────────────┘
              ▼
┌─── Admission Control ──────┐
│ "정책에 맞는가?"             │
│ Mutating → Validating       │
│ (OPA, Kyverno, PSA)         │
└─────────────┬───────────────┘
              ▼
        etcd에 저장
```

---

## 2. RBAC (Role-Based Access Control)

### 2-1. 핵심 구조

```
┌─── 권한 정의 ───┐          ┌─── 권한 부여 ───┐
│                 │          │                 │
│  Role           │ ←────── │ RoleBinding     │ ──→ User/Group/SA
│  (namespace 범위)│          │ (namespace 범위) │
│                 │          │                 │
│  ClusterRole    │ ←────── │ ClusterRoleBinding│ ──→ User/Group/SA
│  (클러스터 범위) │          │ (클러스터 범위)   │
└─────────────────┘          └─────────────────┘
```

### 2-2. Role과 ClusterRole

```yaml
# Namespace 범위 Role: 특정 namespace의 Pod 읽기
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: development
rules:
- apiGroups: [""]              # core API group
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/exec"]
  verbs: ["create"]            # kubectl exec 허용
---
# Cluster 범위 ClusterRole: 모든 namespace의 Deployment 관리
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: deployment-manager
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["services"]
  verbs: ["get", "list", "watch", "create", "update"]
```

### RBAC Verbs 정리

| Verb | 설명 | kubectl 명령어 |
|------|------|---------------|
| **get** | 단일 리소스 조회 | `kubectl get pod <name>` |
| **list** | 리소스 목록 조회 | `kubectl get pods` |
| **watch** | 변경 감시 | `kubectl get pods -w` |
| **create** | 생성 | `kubectl create`, `kubectl apply` |
| **update** | 전체 수정 | `kubectl replace` |
| **patch** | 부분 수정 | `kubectl patch` |
| **delete** | 삭제 | `kubectl delete` |

### 2-3. RoleBinding과 ClusterRoleBinding

```yaml
# RoleBinding: 사용자에게 Role 연결
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dev-pod-reader
  namespace: development
subjects:
- kind: User
  name: "dev-kim"
  apiGroup: rbac.authorization.k8s.io
- kind: Group
  name: "developers"
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
---
# ClusterRoleBinding: ServiceAccount에 ClusterRole 연결
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: monitoring-view
subjects:
- kind: ServiceAccount
  name: prometheus
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: view                   # K8s 기본 제공 ClusterRole
  apiGroup: rbac.authorization.k8s.io
```

### K8s 기본 제공 ClusterRole

| ClusterRole | 권한 |
|-------------|------|
| **cluster-admin** | 모든 리소스 모든 권한 |
| **admin** | namespace 내 대부분 권한 (RBAC 수정 불가) |
| **edit** | namespace 내 리소스 CRUD (Role/RoleBinding 불가) |
| **view** | namespace 내 읽기 전용 |

```bash
# 현재 사용자 권한 확인
kubectl auth can-i create deployments --namespace production
kubectl auth can-i '*' '*'    # 모든 권한 확인

# 특정 사용자 권한 확인 (관리자)
kubectl auth can-i create pods --as dev-kim --namespace development

# 모든 권한 나열
kubectl auth can-i --list --namespace development

# RBAC 리소스 조회
kubectl get roles,rolebindings -n development
kubectl get clusterroles,clusterrolebindings
```

---

## 3. ServiceAccount

**Pod 내부에서 K8s API에 접근**할 때 사용하는 ID다.

```yaml
# ServiceAccount 생성
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: production
automountServiceAccountToken: false    # 불필요하면 비활성화
---
# Pod에서 ServiceAccount 사용
apiVersion: v1
kind: Pod
metadata:
  name: app
  namespace: production
spec:
  serviceAccountName: app-sa
  automountServiceAccountToken: true   # API 접근 필요 시
  containers:
  - name: app
    image: myapp:1.0
```

```bash
# ServiceAccount 토큰 확인 (K8s 1.24+ 바운드 토큰)
kubectl create token app-sa -n production --duration=1h

# Pod 내부에서 API 호출 (토큰 자동 마운트 시)
# TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
# curl -H "Authorization: Bearer $TOKEN" \
#   https://kubernetes.default.svc/api/v1/namespaces/production/pods
```

**보안 베스트 프랙티스:**
- **default ServiceAccount 사용 금지** → 전용 SA 생성
- 불필요하면 **automountServiceAccountToken: false** 설정
- **최소 권한 원칙(Least Privilege)** 적용

---

## 4. Pod Security Standards (PSS)

K8s 1.25+에서 PodSecurityPolicy(PSP)를 대체하는 **Pod 보안 정책**이다.

### 세 가지 보안 수준

| 수준 | 설명 | 허용 범위 |
|------|------|----------|
| **Privileged** | 제한 없음 | 모든 설정 허용 |
| **Baseline** | 기본 보안 | 알려진 위험 설정 차단 |
| **Restricted** | 강화 보안 | 최소 권한 강제 |

```yaml
# Namespace에 PSA(Pod Security Admission) 적용
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted    # 위반 시 거부
    pod-security.kubernetes.io/audit: restricted      # 감사 로그
    pod-security.kubernetes.io/warn: restricted       # 경고 표시
```

```yaml
# Restricted 수준을 만족하는 Pod 예시
apiVersion: v1
kind: Pod
metadata:
  name: secure-pod
  namespace: production
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: myapp:1.0
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsUser: 1000
      runAsGroup: 1000
      capabilities:
        drop:
        - ALL
    volumeMounts:
    - name: tmp
      mountPath: /tmp
  volumes:
  - name: tmp
    emptyDir: {}                 # readOnlyRootFilesystem이므로 쓰기용 tmpfs
```

---

## 5. OPA/Gatekeeper

**Open Policy Agent (OPA)**와 **Gatekeeper**로 K8s에 커스텀 정책을 강제한다.

```yaml
# ConstraintTemplate: 정책 로직 정의
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8srequiredlabels
spec:
  crd:
    spec:
      names:
        kind: K8sRequiredLabels
      validation:
        openAPIV3Schema:
          type: object
          properties:
            labels:
              type: array
              items:
                type: string
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8srequiredlabels
      violation[{"msg": msg}] {
        provided := {label | input.review.object.metadata.labels[label]}
        required := {label | label := input.parameters.labels[_]}
        missing := required - provided
        count(missing) > 0
        msg := sprintf("필수 라벨 누락: %v", [missing])
      }
---
# Constraint: 정책 적용
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: require-team-label
spec:
  match:
    kinds:
    - apiGroups: ["apps"]
      kinds: ["Deployment"]
    namespaces: ["production"]
  parameters:
    labels:
    - "team"
    - "env"
```

---

## 6. Kyverno

OPA/Gatekeeper보다 **K8s 네이티브**하고 학습 곡선이 낮은 정책 엔진이다.
Rego 대신 **YAML로 정책을 작성**한다.

```yaml
# 정책 1: 리소스 요청/제한 필수
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
spec:
  validationFailureAction: Enforce     # Enforce 또는 Audit
  rules:
  - name: check-resource-limits
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "CPU와 메모리 limits가 필수입니다."
      pattern:
        spec:
          containers:
          - resources:
              limits:
                cpu: "?*"
                memory: "?*"
---
# 정책 2: latest 태그 금지
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationFailureAction: Enforce
  rules:
  - name: validate-image-tag
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "latest 태그 사용이 금지됩니다. 구체적인 버전을 지정하세요."
      pattern:
        spec:
          containers:
          - image: "!*:latest"
---
# 정책 3: 자동으로 라벨 추가 (Mutate)
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-default-labels
spec:
  rules:
  - name: add-env-label
    match:
      any:
      - resources:
          kinds:
          - Deployment
          namespaces:
          - production
    mutate:
      patchStrategicMerge:
        metadata:
          labels:
            env: production
            managed-by: kyverno
```

### OPA/Gatekeeper vs Kyverno

| 항목 | OPA/Gatekeeper | Kyverno |
|------|---------------|---------|
| **정책 언어** | Rego (전용 언어) | YAML (K8s 네이티브) |
| **학습 곡선** | 높음 | 낮음 |
| **Mutate 지원** | 제한적 | 기본 지원 |
| **Generate 지원** | 미지원 | 리소스 자동 생성 가능 |
| **커뮤니티** | 넓음 (CNCF Graduated) | 성장 중 (CNCF Incubating) |
| **적합 환경** | 복잡한 정책, 멀티 시스템 | K8s 전용, 빠른 도입 |

---

## 7. 네트워크 보안

### 7-1. mTLS (Mutual TLS)

서비스 간 통신을 **암호화하고 상호 인증**한다.

```yaml
# Istio PeerAuthentication으로 mTLS 강제
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata:
  name: default
  namespace: production
spec:
  mtls:
    mode: STRICT                # 모든 통신에 mTLS 강제
```

### 7-2. Secret 관리

```yaml
# Secret 생성
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: production
type: Opaque
data:
  username: YWRtaW4=            # base64 인코딩 (암호화 아님!)
  password: cGFzc3dvcmQxMjM=
```

```bash
# Secret 생성 (CLI)
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password=password123 \
  -n production

# etcd에서 Secret 암호화 설정 (EncryptionConfiguration)
# /etc/kubernetes/pki/encryption-config.yaml
```

```yaml
# etcd Secret 암호화 설정
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
- resources:
  - secrets
  providers:
  - aescbc:
      keys:
      - name: key1
        secret: <base64-encoded-32-byte-key>
  - identity: {}               # 폴백: 암호화 없이 저장
```

**보안 베스트 프랙티스:**
- Secret은 **base64 인코딩일 뿐, 암호화가 아니다**
- **etcd 암호화(EncryptionConfiguration)** 필수
- 프로덕션에서는 **HashiCorp Vault**, **Sealed Secrets** 사용 권장
- GitOps에서 Secret을 **git에 절대 커밋하지 않는다**

```yaml
# Sealed Secrets 예시 (git에 안전하게 커밋 가능)
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: db-credentials
  namespace: production
spec:
  encryptedData:
    username: AgBy3i4OJSWK+PiTySYZZA9rO...   # 암호화됨
    password: AgCtr5DJnSREMT+qlJhN4Q2aJ...
```

---

## 8. 보안 체크리스트 (온프레미스/폐쇄망)

```
[ ] RBAC: 최소 권한 원칙, default SA 사용 금지
[ ] PSA: production namespace에 restricted 수준 적용
[ ] NetworkPolicy: 기본 deny-all, 필요한 통신만 허용
[ ] Secret: etcd 암호화, Vault 또는 Sealed Secrets 사용
[ ] 이미지: 내부 레지스트리만 허용, 이미지 서명/스캔
[ ] 런타임: non-root 실행, readOnlyRootFilesystem
[ ] 감사: audit log 활성화, 주기적 검토
[ ] 인증서: 내부 CA로 TLS 인증서 관리, 자동 갱신
```

---

## 면접 Q&A

### Q1. "RBAC의 구성요소를 설명해주세요."

> **이렇게 대답한다:**
> "RBAC은 네 가지 리소스로 구성됩니다. **Role**은 namespace 범위에서 '무엇을 할 수 있는가'를 정의하고, **ClusterRole**은 클러스터 범위에서 정의합니다. **RoleBinding**은 Role을 사용자, 그룹, 또는 ServiceAccount에 연결하며, **ClusterRoleBinding**은 ClusterRole을 연결합니다. 핵심은 **최소 권한 원칙**으로, 필요한 리소스에 필요한 verb만 부여합니다."

### Q2. "PodSecurityPolicy가 deprecated된 이유와 대안은?"

> **이렇게 대답한다:**
> "PSP는 설정이 복잡하고, **어떤 정책이 어떤 Pod에 적용되는지 파악하기 어려운** 문제가 있었습니다. K8s 1.25에서 제거되었고, 대안으로 **Pod Security Admission(PSA)**이 내장되었습니다. PSA는 Privileged/Baseline/Restricted 세 수준으로 단순화되어 namespace 라벨만으로 적용할 수 있습니다. 더 세밀한 정책이 필요하면 **Kyverno나 OPA/Gatekeeper**를 함께 사용합니다."

### Q3. "K8s Secret은 안전한가요?"

> **이렇게 대답한다:**
> "기본적으로 Secret은 **base64 인코딩**일 뿐 암호화가 아니므로 안전하지 않습니다. 보안을 강화하려면 **etcd EncryptionConfiguration**으로 저장 시 암호화를 적용하고, RBAC으로 Secret 접근 권한을 제한합니다. 프로덕션에서는 **HashiCorp Vault**로 외부 시크릿 관리를 하거나, GitOps에서는 **Sealed Secrets**로 암호화된 형태로 git에 저장합니다. 폐쇄망에서는 Vault를 내부에 설치하여 운영합니다."

### Q4. "폐쇄망에서 보안 정책을 어떻게 관리하셨나요?"

> **이렇게 대답한다:**
> "폐쇄망은 외부 접근이 차단되어 있지만, **내부 위협(lateral movement)**에 대비해야 합니다. **NetworkPolicy**로 Pod 간 통신을 제한하고, **PSA restricted** 수준을 기본 적용했습니다. **Kyverno**로 승인된 내부 레지스트리 이미지만 사용 가능하도록 정책을 강제하고, 이미지 취약점 스캔은 **Trivy**를 오프라인 DB와 함께 운영했습니다. RBAC은 팀별로 namespace를 분리하고 최소 권한을 부여했습니다."

---

`#RBAC` `#ServiceAccount` `#PodSecurityStandard` `#Kyverno` `#Secret관리`
