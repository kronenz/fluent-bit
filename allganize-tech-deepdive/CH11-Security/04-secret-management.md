# Secret Management: Vault, External Secrets, SOPS

> **TL;DR**: Kubernetes Secrets는 base64 인코딩일 뿐 암호화가 아니므로, 프로덕션에서는 외부 Secret Store(HashiCorp Vault, AWS Secrets Manager)와 연동이 필수다.
> External Secrets Operator(ESO)가 외부 Secret Store를 K8s Secret으로 동기화하고, SOPS는 GitOps 환경에서 시크릿을 암호화하여 Git에 안전하게 저장한다.
> etcd Encryption at Rest를 활성화하지 않으면 etcd 백업에서 Secret이 평문으로 노출된다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Kubernetes Secrets의 한계

```
  ┌──────────────────────────────────────────────┐
  │  K8s Secret의 치명적 한계                      │
  │                                               │
  │  1. base64 인코딩 ≠ 암호화                     │
  │     echo "cGFzc3dvcmQ=" | base64 -d            │
  │     → password  (누구나 디코딩 가능)            │
  │                                               │
  │  2. etcd에 평문 저장 (기본 설정)                │
  │     etcd 백업 탈취 → 모든 Secret 노출          │
  │                                               │
  │  3. RBAC으로만 접근 제어                        │
  │     Secret 조회 권한이 있으면 모든 값 확인 가능  │
  │                                               │
  │  4. Git에 Secret YAML 커밋 → 영구 노출          │
  │     git history에서 삭제 불가능                 │
  │                                               │
  │  5. 자동 로테이션 기능 없음                     │
  │     수동으로 Secret 업데이트 + Pod 재시작 필요   │
  └──────────────────────────────────────────────┘
```

### etcd Encryption at Rest

```yaml
# /etc/kubernetes/enc/encryption-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
    - secrets
    providers:
    - aescbc:                    # AES-CBC 암호화 (권장: aesgcm)
        keys:
        - name: key1
          secret: <base64-encoded-32-byte-key>
    - identity: {}               # fallback: 암호화 안 함 (기존 데이터 읽기용)

# apiserver 플래그 추가
# --encryption-provider-config=/etc/kubernetes/enc/encryption-config.yaml
```

```
  Secret 저장 흐름:

  kubectl create secret
       │
       ▼
  kube-apiserver
       │
       ▼ (EncryptionConfiguration 적용)
  ┌─────────────────┐
  │ AES-CBC 암호화   │
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │   etcd 저장      │  ← 암호화된 상태
  └─────────────────┘
```

### HashiCorp Vault 아키텍처

```
  ┌──────────────────────────────────────────────────┐
  │                 HashiCorp Vault                    │
  │                                                   │
  │  ┌─────────────┐  ┌──────────────┐               │
  │  │ Secret Engine│  │  Auth Method │               │
  │  │ ├ KV v2     │  │ ├ Kubernetes │◄── SA Token   │
  │  │ ├ Database  │  │ ├ AWS IAM    │               │
  │  │ ├ PKI      │  │ ├ OIDC       │               │
  │  │ └ Transit  │  │ └ AppRole    │               │
  │  └─────────────┘  └──────────────┘               │
  │                                                   │
  │  ┌─────────────┐  ┌──────────────┐               │
  │  │   Policy     │  │ Audit Log    │               │
  │  │ path "secret/│  │ 모든 접근     │               │
  │  │   data/ai/*" │  │ 기록 (감사)  │               │
  │  │ { read }     │  │              │               │
  │  └─────────────┘  └──────────────┘               │
  │                                                   │
  │  Storage Backend: Consul / Raft(내장) / S3        │
  └──────────────────────────────────────────────────┘
```

**Vault + Kubernetes 인증 흐름**:

```
  Pod (ServiceAccount)
       │
       │ 1. SA Token으로 Vault 인증
       ▼
  ┌──────────────┐
  │   Vault       │
  │   ├ K8s Auth  │ ── 2. K8s API로 SA Token 검증
  │   ├ Policy    │ ── 3. 정책에 따라 Secret 접근 허용
  │   └ Secret    │ ── 4. Dynamic/Static Secret 반환
  └──────┬───────┘
         │ 5. Secret 값 반환
         ▼
  Pod에서 사용 (환경변수 / 파일)
```

**Vault 주요 기능**:
- **Dynamic Secrets**: DB 접속 시마다 임시 credential 발급 → TTL 후 자동 폐기
- **Secret Rotation**: 자동 로테이션 + lease 관리
- **Encryption as a Service (Transit)**: 애플리케이션이 직접 암호화하지 않고 Vault API로 위임
- **PKI Engine**: 내부 CA로 TLS 인증서 자동 발급/갱신

### External Secrets Operator (ESO)

```
  ┌──────────────────────────────────────────────┐
  │  External Secrets Operator                    │
  │                                               │
  │  SecretStore            ExternalSecret         │
  │  (인증 정보)            (동기화 규칙)           │
  │       │                      │                 │
  │       ▼                      ▼                 │
  │  ┌──────────┐          ┌───────────┐          │
  │  │  AWS SM   │◄─────────│ ESO       │          │
  │  │  Vault    │  polling │ Controller│          │
  │  │  Azure KV │  (주기적)│           │          │
  │  └──────────┘          └─────┬─────┘          │
  │                              │                 │
  │                              ▼                 │
  │                     ┌──────────────┐          │
  │                     │ K8s Secret    │          │
  │                     │ (자동 생성)   │          │
  │                     └──────────────┘          │
  └──────────────────────────────────────────────┘
```

```yaml
# 1. SecretStore: 외부 Secret Store 연결 설정
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: aws-secrets-manager
  namespace: ai-serving
spec:
  provider:
    aws:
      service: SecretsManager
      region: ap-northeast-2
      auth:
        jwt:
          serviceAccountRef:
            name: eso-sa   # IRSA로 AWS 인증

---
# 2. ExternalSecret: 동기화 규칙 정의
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ai-model-secrets
  namespace: ai-serving
spec:
  refreshInterval: 1h              # 동기화 주기
  secretStoreRef:
    name: aws-secrets-manager
    kind: SecretStore
  target:
    name: ai-model-secrets         # 생성될 K8s Secret 이름
    creationPolicy: Owner
  data:
  - secretKey: db-password          # K8s Secret의 key
    remoteRef:
      key: prod/ai-serving/db      # AWS SM의 Secret 이름
      property: password            # JSON 내 필드
  - secretKey: api-key
    remoteRef:
      key: prod/ai-serving/llm-api
      property: api_key
```

### SOPS (Secrets OPerationS)

```
  GitOps 환경에서의 Secret 관리:

  개발자
    │
    │ 1. SOPS로 Secret YAML 암호화
    ▼
  ┌────────────────────────────┐
  │  sops --encrypt            │
  │  --kms arn:aws:kms:...     │
  │  secret.yaml               │
  │         │                  │
  │         ▼                  │
  │  암호화된 secret.enc.yaml  │
  └────────────┬───────────────┘
               │ 2. Git에 커밋 (안전)
               ▼
  ┌────────────────────────────┐
  │  Git Repository            │
  │  (암호화된 Secret만 저장)  │
  └────────────┬───────────────┘
               │ 3. ArgoCD/Flux 감지
               ▼
  ┌────────────────────────────┐
  │  ArgoCD + KSOPS plugin     │
  │  또는 Flux SOPS controller │
  │         │                  │
  │         ▼ 4. KMS로 복호화  │
  │  K8s Secret 생성           │
  └────────────────────────────┘
```

```bash
# SOPS로 Secret 암호화
sops --encrypt \
  --kms "arn:aws:kms:ap-northeast-2:123456789:key/mrk-xxx" \
  --encrypted-regex '^(data|stringData)$' \
  secret.yaml > secret.enc.yaml

# 암호화된 파일 내용 (data 값만 암호화됨)
# apiVersion: v1
# kind: Secret
# metadata:
#   name: db-secret
# data:
#   password: ENC[AES256_GCM,data:xxx,iv:xxx,tag:xxx,type:str]
```

### 솔루션 비교

```
  ┌─────────────┬──────────────┬──────────────┬──────────────┐
  │             │ K8s Secret   │ Vault + ESO  │ SOPS         │
  │             │ (기본)       │              │              │
  ├─────────────┼──────────────┼──────────────┼──────────────┤
  │ 암호화      │ base64만     │ Vault 자체   │ KMS/PGP      │
  │ 로테이션    │ 수동         │ 자동         │ 수동+GitOps  │
  │ 감사 추적   │ K8s Audit    │ Vault Audit  │ Git History  │
  │ 동적 Secret │ 불가능       │ 가능         │ 불가능       │
  │ GitOps 호환 │ 위험(평문)   │ ESO 연동     │ 네이티브     │
  │ 운영 복잡도 │ 낮음         │ 높음         │ 중간         │
  │ 비용        │ 무료         │ Enterprise$$ │ 무료         │
  └─────────────┴──────────────┴──────────────┴──────────────┘
```

---

## 실전 예시

### Vault Kubernetes Auth 설정

```bash
# Vault에서 Kubernetes Auth 활성화
vault auth enable kubernetes

vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc:443" \
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

# Policy 생성
vault policy write ai-model-policy - <<EOF
path "secret/data/ai-serving/*" {
  capabilities = ["read"]
}
path "database/creds/ai-model-db" {
  capabilities = ["read"]
}
EOF

# Role 생성 (K8s SA ↔ Vault Policy 매핑)
vault write auth/kubernetes/role/ai-model \
  bound_service_account_names=ai-model-sa \
  bound_service_account_namespaces=ai-serving \
  policies=ai-model-policy \
  ttl=1h
```

### Dynamic Database Credentials (Vault)

```bash
# Database Secret Engine 설정
vault secrets enable database

vault write database/config/ai-postgres \
  plugin_name=postgresql-database-plugin \
  allowed_roles="ai-model-db" \
  connection_url="postgresql://{{username}}:{{password}}@postgres:5432/aidb" \
  username="vault-admin" \
  password="admin-password"

vault write database/roles/ai-model-db \
  db_name=ai-postgres \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
  default_ttl="1h" \
  max_ttl="24h"

# Pod에서 사용: 매번 임시 DB credential 발급
vault read database/creds/ai-model-db
# username: v-k8s-ai-model-xxxxx
# password: A1b2C3d4...
# ttl: 1h (만료 후 자동 삭제)
```

### Secret Rotation 자동화

```yaml
# ExternalSecret + refreshInterval로 자동 동기화
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rotating-db-secret
spec:
  refreshInterval: 30m      # 30분마다 외부 Secret Store와 동기화
  secretStoreRef:
    name: aws-secrets-manager
  target:
    name: db-credentials
  data:
  - secretKey: password
    remoteRef:
      key: prod/db-password  # AWS SM에서 자동 로테이션 설정된 Secret

---
# Stakater Reloader: Secret 변경 시 Pod 자동 재시작
apiVersion: apps/v1
kind: Deployment
metadata:
  annotations:
    reloader.stakater.com/auto: "true"   # Secret 변경 감지 → Rolling Update
spec:
  template:
    spec:
      containers:
      - name: app
        envFrom:
        - secretRef:
            name: db-credentials
```

---

## 면접 Q&A

### Q: Kubernetes Secret이 왜 안전하지 않고, 어떤 대안이 있나요?
**30초 답변**:
K8s Secret은 base64 인코딩일 뿐 암호화가 아니며, etcd에 기본적으로 평문 저장됩니다. etcd Encryption at Rest를 활성화하고, 프로덕션에서는 HashiCorp Vault나 AWS Secrets Manager 같은 외부 Secret Store를 External Secrets Operator로 연동하는 것이 모범 사례입니다.

**2분 답변**:
K8s Secret의 핵심 한계는 5가지입니다. 첫째, base64 인코딩은 누구나 디코딩 가능합니다. 둘째, etcd에 기본 평문 저장되어 etcd 백업 탈취 시 모든 Secret이 노출됩니다. 셋째, Secret YAML을 Git에 커밋하면 history에서 영구 노출됩니다. 넷째, 자동 로테이션 기능이 없어 수동 관리 부담이 큽니다. 다섯째, RBAC 외 세밀한 접근 제어(필드 단위 등)가 불가능합니다. 대안은 3가지 계층입니다. 기본으로 etcd Encryption at Rest(EncryptionConfiguration)를 활성화합니다. 그 위에 External Secrets Operator로 AWS Secrets Manager, Vault 등 외부 Store를 K8s Secret으로 동기화합니다. GitOps 환경에서는 SOPS로 Secret을 암호화하여 Git에 안전하게 저장합니다. 가장 강력한 방법은 Vault의 Dynamic Secrets로, DB 접속 시마다 임시 credential을 발급받아 TTL 후 자동 폐기하는 것입니다.

**💡 경험 연결**:
폐쇄망 환경에서 Secret을 ConfigMap처럼 평문 YAML로 관리하던 것을 발견하고, etcd Encryption at Rest를 활성화하고 RBAC으로 Secret 접근을 제한한 경험이 있습니다. 클라우드 환경에서는 ESO + AWS Secrets Manager 조합이 운영 부담 대비 보안 효과가 가장 좋다고 판단합니다.

**⚠️ 주의**:
etcd Encryption at Rest를 활성화해도 **기존에 저장된 Secret은 평문 상태**로 남아있다. `kubectl get secrets --all-namespaces -o json | kubectl replace -f -`로 모든 Secret을 재저장(re-encrypt)해야 한다.

### Q: External Secrets Operator의 동작 원리와 장점을 설명해주세요.
**30초 답변**:
ESO는 SecretStore(외부 Store 연결 정보)와 ExternalSecret(동기화 규칙) CRD를 사용합니다. Controller가 주기적으로 외부 Store를 polling하여 K8s Secret을 자동 생성/갱신하므로, 애플리케이션 코드 변경 없이 외부 Secret Store를 사용할 수 있습니다.

**2분 답변**:
ESO의 아키텍처는 CRD 기반입니다. SecretStore(또는 ClusterSecretStore)에 외부 Store의 인증 정보를 설정합니다. AWS SM이면 IRSA, Vault면 K8s Auth를 사용합니다. ExternalSecret에 "어떤 외부 Secret의 어떤 필드를 K8s Secret의 어떤 key로 동기화할지" 매핑 규칙을 정의합니다. ESO Controller가 refreshInterval 주기로 외부 Store를 polling하여 K8s Secret을 생성하거나 업데이트합니다. 장점은 세 가지입니다. 첫째, 기존 워크로드가 K8s Secret을 그대로 사용하므로 애플리케이션 코드 변경이 불필요합니다. 둘째, Secret의 Single Source of Truth가 외부 Store이므로 중앙 관리가 가능합니다. 셋째, Stakater Reloader와 조합하면 Secret 변경 시 Pod 자동 재시작까지 자동화됩니다. ClusterSecretStore를 사용하면 여러 Namespace에서 하나의 Store 연결을 공유할 수 있어 관리 포인트가 줄어듭니다.

**💡 경험 연결**:
Secret 관리가 팀마다 다른 방식으로 이루어져 일관성이 없었던 문제를 ESO 도입으로 해결한 사례가 있습니다. ExternalSecret manifest만 관리하면 되므로 GitOps와도 잘 통합됩니다.

**⚠️ 주의**:
ESO의 refreshInterval이 너무 짧으면 외부 Store API 호출 비용이 증가하고, 너무 길면 Secret 변경 반영이 지연된다. 프로덕션에서는 1h 정도가 적당하며, 긴급 변경 시에는 수동으로 ExternalSecret을 trigger할 수 있다.

### Q: Vault의 Dynamic Secrets가 Static Secrets보다 안전한 이유는?
**30초 답변**:
Dynamic Secrets는 요청할 때마다 새로운 임시 credential을 발급하고 TTL 후 자동 폐기합니다. credential이 탈취되어도 짧은 시간 후 자동 만료되므로 피해 범위(blast radius)가 제한됩니다.

**2분 답변**:
Static Secret의 핵심 위험은 유출 시 영구적으로 유효하다는 점입니다. DB 비밀번호가 유출되면 수동으로 변경할 때까지 공격자가 접근 가능합니다. Vault Dynamic Secrets는 이를 근본적으로 해결합니다. Database Secret Engine을 예로 들면, Pod가 DB 접근이 필요할 때 Vault에 요청하면 임시 DB 사용자/비밀번호를 발급합니다. TTL(예: 1시간) 후 Vault가 해당 사용자를 DB에서 자동 삭제합니다. 이로써 credential 탈취 시 피해 시간이 최대 TTL로 제한됩니다. 또한 각 Pod가 고유한 credential을 받으므로, 감사 시 "어떤 Pod가 어떤 작업을 했는지" 추적이 가능합니다. 공유 credential에서는 불가능한 세밀한 감사입니다. 추가로 Vault의 Transit Engine을 사용하면 애플리케이션이 직접 암호화 키를 갖지 않고 Vault API로 암/복호화를 위임할 수 있어, 키 관리 부담을 제거합니다.

**💡 경험 연결**:
DB 비밀번호를 공유 credential로 사용하다가, 퇴사자의 접근을 차단하기 위해 비밀번호를 변경해야 하는 상황을 여러 번 겪었습니다. Dynamic Secrets를 사용하면 이런 문제가 구조적으로 해결됩니다.

**⚠️ 주의**:
Dynamic Secrets 사용 시 Vault 자체의 가용성이 핵심이 된다. Vault가 다운되면 새 credential을 발급받지 못하므로, Vault HA 구성과 적절한 TTL 설정이 중요하다.

---

## Allganize 맥락

- **LLM API Key 관리**: OpenAI, Azure OpenAI, Anthropic 등 외부 LLM API Key는 Vault 또는 AWS Secrets Manager로 중앙 관리하고, ESO로 K8s Secret에 동기화해야 한다.
- **멀티테넌트 Secret 격리**: 고객별 API Key, DB credential을 Namespace별로 격리하고, ClusterSecretStore + ExternalSecret으로 자동 프로비저닝.
- **DB 접근 보안**: AI 서비스의 PostgreSQL/Vector DB 접근 시 Vault Dynamic Secrets로 임시 credential을 사용하면 보안과 감사 추적이 동시에 가능.
- **GitOps 호환**: ArgoCD로 배포한다면 SOPS + KSOPS 또는 ESO로 Secret을 관리하여, Git에 평문 Secret이 커밋되는 사고를 방지.
- **JD 연관**: "보안 정책 수립"에서 Secret Management는 가장 기본이면서도 자주 미흡한 영역. 외부 Secret Store 연동 경험은 강력한 어필 포인트.

---
**핵심 키워드**: `K8s-Secrets` `base64` `etcd-encryption` `Vault` `Dynamic-Secrets` `External-Secrets-Operator` `SOPS` `Secret-Rotation` `IRSA` `Transit-Engine`
