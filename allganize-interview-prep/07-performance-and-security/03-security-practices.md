# 보안 실무 (Security Practices) - Allganize 면접 준비

---

> **TL;DR**
> 1. **Zero Trust**는 "아무도 신뢰하지 않는다"는 원칙으로, 모든 접근을 검증한다
> 2. K8s 보안은 **NetworkPolicy + RBAC + Secret 관리 + 이미지 스캐닝** 4층 방어다
> 3. 폐쇄망 경험이 강점 -- 네트워크 격리, 물리 보안, 내부 위협 대응에 능숙하다

---

## 1. Zero Trust 아키텍처 개념

### 전통적 보안 vs Zero Trust

```
[전통적 보안 - Castle & Moat]
  외부 ←── 방화벽 ──→ 내부 (신뢰 영역)
  "내부 네트워크는 안전하다" (X)

[Zero Trust]
  모든 접근 = 비신뢰 (Never Trust, Always Verify)
  "내부라도 검증하고, 최소 권한만 부여한다" (O)
```

### Zero Trust 5대 원칙

| 원칙 | 설명 | K8s 적용 |
|------|------|----------|
| **Verify Explicitly** | 모든 요청을 인증/인가 | ServiceAccount + RBAC |
| **Least Privilege** | 최소 권한만 부여 | RBAC ClusterRole 최소화 |
| **Assume Breach** | 침해를 가정하고 설계 | NetworkPolicy로 마이크로세그먼테이션 |
| **Micro-segmentation** | 네트워크를 세밀하게 분리 | Namespace별 NetworkPolicy |
| **Continuous Validation** | 지속적 모니터링/검증 | Falco, OPA Gatekeeper |

### 폐쇄망에서의 Zero Trust

```
폐쇄망 (Air-gapped) 환경에서도 Zero Trust는 필수:
- 내부 직원에 의한 위협 (Insider Threat)
- 서비스 간 무분별한 통신
- 권한 확대 (Privilege Escalation)

폐쇄망 = 외부 차단 ≠ 내부 안전
```

---

## 2. Kubernetes NetworkPolicy 설계

### NetworkPolicy 기본 구조

```yaml
# deny-all.yaml - 기본 차단 정책 (Zero Trust 시작점)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: ai-serving
spec:
  podSelector: {}          # 모든 Pod에 적용
  policyTypes:
    - Ingress
    - Egress
```

### 계층별 NetworkPolicy 설계

#### Layer 1: Namespace 간 격리

```yaml
# ns-isolation.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-same-namespace
  namespace: ai-serving
spec:
  podSelector: {}
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector: {}   # 같은 Namespace 내에서만 허용
```

#### Layer 2: 서비스 간 허용 규칙

```yaml
# allow-api-to-model.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-to-model
  namespace: ai-serving
spec:
  podSelector:
    matchLabels:
      app: vllm-server         # 대상: 모델 서버
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: api-gateway  # 출발: API Gateway만 허용
      ports:
        - protocol: TCP
          port: 8000
```

#### Layer 3: 외부 통신 제한

```yaml
# restrict-egress.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restrict-egress
  namespace: ai-serving
spec:
  podSelector:
    matchLabels:
      app: vllm-server
  policyTypes:
    - Egress
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: mongodb     # MongoDB만 접근 허용
      ports:
        - protocol: TCP
          port: 27017
    - to:                       # DNS 허용 (필수)
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
```

### 실전 팁: NetworkPolicy 디버깅

```bash
# Calico 기준 - 정책 적용 확인
kubectl get networkpolicy -n ai-serving

# Pod 간 연결 테스트
kubectl exec -n ai-serving api-gateway-xxx -- \
  curl -s -o /dev/null -w "%{http_code}" \
  http://vllm-server:8000/health

# Calico 로그로 차단된 트래픽 확인
kubectl logs -n calico-system -l k8s-app=calico-node | grep -i deny
```

---

## 3. 시크릿 관리

### 왜 K8s Secret만으로는 부족한가

```
K8s Secret 문제점:
1. Base64 인코딩일 뿐, 암호화가 아님
2. etcd에 평문 저장 (EncryptionConfiguration 미설정 시)
3. 버전 관리 / 자동 로테이션 불가
4. 감사(Audit) 추적 어려움
```

### 솔루션 비교

| 도구 | 유형 | 장점 | 적합 환경 |
|------|------|------|----------|
| **HashiCorp Vault** | Self-hosted | 동적 시크릿, 자동 로테이션, 폐쇄망 | On-premises, Air-gapped |
| **AWS Secrets Manager** | Managed | AWS 통합, 자동 로테이션 | AWS 클라우드 |
| **External Secrets Operator** | K8s Operator | 외부 저장소 -> K8s Secret 동기화 | 모든 환경 |

### HashiCorp Vault + K8s 통합

```bash
# Vault 설치 (Helm)
helm install vault hashicorp/vault \
  --namespace vault \
  --set server.ha.enabled=true \
  --set server.ha.replicas=3

# K8s Auth 활성화
vault auth enable kubernetes
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc:443"

# 시크릿 엔진 설정
vault secrets enable -path=ai-serving kv-v2
vault kv put ai-serving/mongodb \
  username="admin" \
  password="SecureP@ss123"

# 정책 생성
vault policy write ai-serving-policy - <<EOF
path "ai-serving/data/mongodb" {
  capabilities = ["read"]
}
EOF
```

### External Secrets Operator 예시

```yaml
# secret-store.yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: ai-serving
spec:
  provider:
    vault:
      server: "http://vault.vault:8200"
      path: "ai-serving"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "ai-serving-role"
---
# external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: mongodb-credentials
  namespace: ai-serving
spec:
  refreshInterval: 1h              # 1시간마다 동기화
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: mongodb-secret            # 생성될 K8s Secret 이름
    creationPolicy: Owner
  data:
    - secretKey: username
      remoteRef:
        key: mongodb
        property: username
    - secretKey: password
      remoteRef:
        key: mongodb
        property: password
```

---

## 4. 이미지 보안

### 컨테이너 이미지 보안 파이프라인

```
[이미지 빌드] -> [스캐닝 (Trivy)] -> [서명 (Cosign)] -> [런타임 보안 (Falco)]
                      |                    |                      |
                  CVE 검출            무결성 보장           이상 행위 탐지
```

### Trivy: 이미지 취약점 스캐닝

```bash
# 이미지 스캔
trivy image vllm/vllm-openai:latest

# 심각도 필터링 (CRITICAL, HIGH만)
trivy image --severity CRITICAL,HIGH vllm/vllm-openai:latest

# CI/CD 통합 (취약점 발견 시 빌드 실패)
trivy image --exit-code 1 --severity CRITICAL myregistry/ai-app:v1.0

# K8s 클러스터 전체 스캔
trivy k8s --report summary cluster

# SBOM (Software Bill of Materials) 생성
trivy image --format spdx-json --output sbom.json myregistry/ai-app:v1.0
```

#### CI 파이프라인 통합 예시

```yaml
# .github/workflows/security-scan.yaml (또는 GitLab CI에서 유사하게)
security-scan:
  stage: test
  script:
    - trivy image --exit-code 1 --severity CRITICAL,HIGH
        --ignore-unfixed ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
    - trivy config --exit-code 1 ./k8s/    # IaC 설정도 스캔
```

### Falco: 런타임 보안 모니터링

```yaml
# falco-rules.yaml - 커스텀 규칙
- rule: Unexpected Process in AI Container
  desc: AI 서빙 컨테이너에서 예상치 못한 프로세스 실행 감지
  condition: >
    spawned_process and
    container.name = "vllm" and
    not proc.name in (python3, vllm, nvidia-smi, tritonserver)
  output: >
    Unexpected process in AI container
    (user=%user.name command=%proc.cmdline container=%container.name)
  priority: WARNING

- rule: Sensitive File Access
  desc: 시크릿 파일 접근 감지
  condition: >
    open_read and
    fd.name startswith /var/run/secrets/ and
    not proc.name in (python3, node, java)
  output: >
    Sensitive file accessed (file=%fd.name proc=%proc.name container=%container.name)
  priority: CRITICAL
```

```bash
# Falco 설치 (Helm)
helm install falco falcosecurity/falco \
  --namespace falco \
  --set falcosidekick.enabled=true \
  --set falcosidekick.config.slack.webhookurl="https://hooks.slack.com/..."

# 이벤트 확인
kubectl logs -n falco -l app.kubernetes.io/name=falco -f
```

---

## 5. RBAC 최소 권한 원칙 (Principle of Least Privilege)

### RBAC 핵심 구조

```
User/ServiceAccount
      |
  RoleBinding / ClusterRoleBinding
      |
  Role / ClusterRole
      |
  Rules (apiGroups, resources, verbs)
```

### 실전 RBAC 설계

#### AI 서비스용 최소 권한 ServiceAccount

```yaml
# ai-serving-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ai-serving-sa
  namespace: ai-serving
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ai-serving-role
  namespace: ai-serving
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list"]          # 읽기만 허용
    resourceNames: ["model-config"] # 특정 리소스만 허용
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
    resourceNames: ["mongodb-secret", "es-secret"]  # 필요한 시크릿만
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]          # Pod 상태 확인만
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ai-serving-binding
  namespace: ai-serving
subjects:
  - kind: ServiceAccount
    name: ai-serving-sa
    namespace: ai-serving
roleRef:
  kind: Role
  name: ai-serving-role
  apiGroup: rbac.authorization.k8s.io
```

#### 위험한 권한 감지

```bash
# cluster-admin 바인딩 확인
kubectl get clusterrolebindings -o json | \
  jq '.items[] | select(.roleRef.name=="cluster-admin") |
      {name: .metadata.name, subjects: .subjects}'

# 와일드카드(*) 권한 확인
kubectl get clusterroles -o json | \
  jq '.items[] | select(.rules[]?.verbs[]? == "*") |
      {name: .metadata.name}'

# 특정 ServiceAccount의 권한 확인
kubectl auth can-i --list --as=system:serviceaccount:ai-serving:ai-serving-sa
```

### Pod Security Standards (PSS)

```yaml
# namespace-security.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ai-serving
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
# 보안 강화된 Pod 설정
apiVersion: v1
kind: Pod
metadata:
  name: secure-ai-pod
  namespace: ai-serving
spec:
  serviceAccountName: ai-serving-sa
  automountServiceAccountToken: false   # 불필요 시 토큰 마운트 방지
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: myregistry/ai-app:v1.0
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      volumeMounts:
        - name: tmp
          mountPath: /tmp
  volumes:
    - name: tmp
      emptyDir: {}
```

---

## 면접 Q&A

### Q1. "Zero Trust 아키텍처를 설명하고, K8s에서 어떻게 구현하나요?"

> **이렇게 대답한다:**
> "Zero Trust는 '내부든 외부든 아무도 신뢰하지 않는다'는 원칙입니다. K8s에서는 네 가지로 구현합니다. 첫째, NetworkPolicy로 default-deny를 적용한 뒤 필요한 통신만 화이트리스트로 허용합니다. 둘째, RBAC으로 ServiceAccount별 최소 권한만 부여합니다. 셋째, mTLS(Istio/Linkerd)로 서비스 간 암호화 통신을 보장합니다. 넷째, Falco로 런타임 이상 행위를 실시간 감지합니다. 폐쇄망 운영 경험에서 내부 위협의 심각성을 체감했기 때문에, Zero Trust가 폐쇄망에서도 반드시 필요하다고 확신합니다."

### Q2. "K8s Secret 관리의 문제점과 대안은?"

> **이렇게 대답한다:**
> "K8s Secret은 Base64 인코딩일 뿐 암호화가 아니고, etcd에 평문 저장될 수 있으며, 자동 로테이션도 불가합니다. 대안으로 HashiCorp Vault + External Secrets Operator 조합을 사용합니다. Vault가 시크릿의 단일 진실 소스(Single Source of Truth)가 되고, ESO가 Vault의 시크릿을 K8s Secret으로 자동 동기화합니다. 폐쇄망에서는 Vault를 Self-hosted로 운영해야 하므로, HA 구성과 Auto-Unseal 설정이 중요합니다."

### Q3. "컨테이너 이미지 보안은 어떻게 관리하나요?"

> **이렇게 대답한다:**
> "빌드 타임과 런타임 두 단계로 나눕니다. 빌드 타임에는 Trivy로 이미지의 CVE 취약점을 스캔하고, CRITICAL/HIGH 취약점이 있으면 CI 파이프라인을 실패시킵니다. 또한 Cosign으로 이미지에 서명하여 무결성을 보장합니다. 런타임에는 Falco로 컨테이너 내부의 이상 행위(예상치 못한 프로세스 실행, 시크릿 파일 접근 등)를 실시간 감지합니다. 폐쇄망에서는 외부 레지스트리 접근이 불가하므로, 내부 Harbor 레지스트리에 Trivy를 통합하여 이미지 푸시 시 자동 스캔되도록 구성합니다."

### Q4. "RBAC 최소 권한 원칙을 실무에서 어떻게 적용하나요?"

> **이렇게 대답한다:**
> "먼저 cluster-admin과 와일드카드(*) 권한을 가진 바인딩을 감사합니다. 그 다음 서비스별로 실제 필요한 API 리소스와 동작(verbs)만 열거한 Role을 작성합니다. resourceNames로 특정 리소스까지 제한하면 더 안전합니다. Pod Security Standards를 restricted 레벨로 설정하고, automountServiceAccountToken을 false로 설정하여 불필요한 토큰 노출을 방지합니다. 정기적으로 kubectl auth can-i --list로 각 ServiceAccount의 실제 권한을 점검합니다."

### Q5. "폐쇄망 환경에서의 보안 경험을 Allganize에 어떻게 적용할 수 있나요?"

> **이렇게 대답한다:**
> "폐쇄망 10년 운영 경험에서 얻은 핵심은 '외부 차단이 보안의 전부가 아니다'입니다. 내부 네트워크 세그먼테이션, 접근 제어, 감사 로그가 더 중요합니다. Allganize에서 고객사에 온프레미스/폐쇄망 배포를 지원할 때, 이 경험이 직접적으로 도움이 됩니다. 내부 레지스트리 구축, 오프라인 취약점 DB 관리, 네트워크 격리 설계 등 폐쇄망 특유의 보안 과제를 이미 해결한 경험이 있기 때문입니다."

---

## 핵심 키워드 5선

`Zero Trust Architecture` `K8s NetworkPolicy (default-deny)` `External Secrets Operator + Vault` `Trivy + Falco (빌드/런타임 보안)` `RBAC 최소 권한 원칙`
