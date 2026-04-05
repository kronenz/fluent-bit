# 03. 인증서 체인과 CA — X.509, CA 체인, Self-Signed CA, cert-manager

> **TL;DR**
> - X.509 인증서는 **공개키 + 소유자 정보 + CA 서명**으로 구성되며, Root CA → Intermediate CA → End-Entity 인증서의 **체인 구조**로 신뢰를 전파한다.
> - 브라우저/OS에 내장된 **Root CA 목록**(Trust Store)이 신뢰의 출발점이며, Intermediate CA가 실제 서명을 담당하여 Root CA를 보호한다.
> - Kubernetes 환경에서는 **cert-manager**가 인증서 생명주기를 자동화하고, 폐쇄망에서는 **Self-Signed CA**를 구축하여 내부 PKI를 운영한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### X.509 인증서 구조

```
┌──────────────────────────────────────────┐
│            X.509 v3 인증서                │
├──────────────────────────────────────────┤
│ Version: v3                               │
│ Serial Number: 0x3A7B...                  │
│ Signature Algorithm: sha256WithRSAEnc     │
│                                           │
│ Issuer: CN=Intermediate CA, O=CA Corp     │  ← 발급자 (CA)
│ Validity:                                 │
│   Not Before: 2024-01-01                  │
│   Not After:  2025-01-01                  │
│                                           │
│ Subject: CN=api.allganize.ai              │  ← 소유자
│ Subject Public Key Info:                  │
│   Algorithm: RSA (2048 bit)               │
│   Public Key: 30 82 01 0A 02 82...        │  ← 공개키
│                                           │
│ Extensions:                               │
│   Subject Alternative Name (SAN):         │
│     DNS: api.allganize.ai                 │
│     DNS: *.allganize.ai                   │
│   Key Usage: Digital Signature            │
│   Extended Key Usage: TLS Web Server Auth │
│   Authority Key Identifier: AB:CD:EF...   │
│   CRL Distribution Points: http://...     │
│   Authority Info Access:                  │
│     OCSP: http://ocsp.ca.com              │
│     CA Issuers: http://ca.com/inter.crt   │
├──────────────────────────────────────────┤
│ Signature: 4A 8B C3 ...                   │  ← CA의 개인키로 서명
└──────────────────────────────────────────┘
```

**핵심 필드 설명:**
- **Subject**: 인증서 소유자 (CN=Common Name은 레거시, SAN이 실제 도메인 매칭에 사용)
- **Issuer**: 인증서를 서명한 CA
- **SAN (Subject Alternative Name)**: 실제 도메인 매칭에 사용되는 필드 (와일드카드 지원)
- **Key Usage / Extended Key Usage**: 인증서 용도 제한
- **CRL / OCSP**: 인증서 폐기 확인 메커니즘

### 인증서 체인 (Chain of Trust)

```
┌─────────────────────────────┐
│      Root CA 인증서          │  ← OS/브라우저 Trust Store에 내장
│  (자기 서명, Issuer=Subject) │     보통 20년+ 유효기간
│  개인키: 오프라인 보관 (HSM)  │     전 세계 약 150개
└──────────┬──────────────────┘
           │ 서명
┌──────────▼──────────────────┐
│   Intermediate CA 인증서     │  ← 실제 인증서 발급 담당
│  (Root CA가 서명)            │     보통 5~10년 유효기간
│  개인키: 온라인, 보안 강화    │     Root CA 침해 위험 분산
└──────────┬──────────────────┘
           │ 서명
┌──────────▼──────────────────┐
│   End-Entity 인증서          │  ← 실제 서버에 설치
│  (Intermediate CA가 서명)    │     보통 90일~1년 유효기간
│  CN=api.allganize.ai         │     Let's Encrypt: 90일
└─────────────────────────────┘

검증 과정 (클라이언트):
1. 서버가 End-Entity + Intermediate 인증서를 전송
2. Intermediate의 서명을 Root CA 공개키로 검증
3. End-Entity의 서명을 Intermediate 공개키로 검증
4. 체인이 Trust Store의 Root CA까지 연결되면 신뢰
```

**왜 Intermediate CA를 사용하는가?**
- Root CA 개인키는 **오프라인 HSM(Hardware Security Module)**에 보관
- Intermediate CA가 침해되면 해당 Intermediate만 폐기하면 됨
- Root CA를 직접 사용하면 침해 시 전체 PKI 붕괴

### 인증서 유효성 검증 방법

```
CRL (Certificate Revocation List):
┌──────────────────────────────────────┐
│ CA가 주기적으로 폐기 인증서 목록 게시  │
│ 클라이언트가 목록 다운로드 후 확인      │
│                                      │
│ 단점: 목록이 커짐, 실시간성 부족       │
└──────────────────────────────────────┘

OCSP (Online Certificate Status Protocol):
┌──────────────────────────────────────┐
│ 클라이언트가 CA의 OCSP 서버에 개별 조회│
│ 실시간 폐기 상태 확인                  │
│                                      │
│ 단점: CA 서버 의존, 개인정보 우려      │
└──────────────────────────────────────┘

OCSP Stapling (권장):
┌──────────────────────────────────────┐
│ 웹 서버가 미리 OCSP 응답을 받아와서   │
│ TLS 핸드셰이크 시 클라이언트에게 전달  │
│                                      │
│ 장점: CA 서버 의존 제거, 개인정보 보호 │
└──────────────────────────────────────┘
```

### Self-Signed CA (내부 PKI)

```
폐쇄망 / 내부 서비스 간 통신:

┌──────────────────────────┐
│    Internal Root CA       │  ← 직접 생성, 자기 서명
│    (자체 구축)             │     모든 노드의 Trust Store에 등록
└──────────┬───────────────┘
           │
┌──────────▼───────────────┐
│  Internal Intermediate CA │  ← Root CA로 서명
│                           │     실제 인증서 발급
└──────────┬───────────────┘
           │
    ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
    │ Service A    │  │ Service B    │  │ Service C    │
    │ cert         │  │ cert         │  │ cert         │
    └─────────────┘  └─────────────┘  └─────────────┘
```

---

## 실전 예시

### 인증서 체인 확인

```bash
# 서버 인증서 체인 전체 확인
openssl s_client -connect api.allganize.ai:443 -showcerts 2>/dev/null

# 인증서 상세 정보 확인
echo | openssl s_client -connect api.allganize.ai:443 2>/dev/null | \
  openssl x509 -noout -text

# 인증서 만료일만 확인
echo | openssl s_client -connect api.allganize.ai:443 2>/dev/null | \
  openssl x509 -noout -dates -subject -issuer

# SAN (Subject Alternative Name) 확인
echo | openssl s_client -connect api.allganize.ai:443 2>/dev/null | \
  openssl x509 -noout -ext subjectAltName

# 인증서 체인 검증
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt \
  -untrusted intermediate.crt server.crt
```

### Self-Signed CA 구축 (실습용)

```bash
# 1. Root CA 생성
openssl genrsa -aes256 -out rootCA.key 4096
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 3650 \
  -out rootCA.crt \
  -subj "/C=KR/O=Allganize/CN=Allganize Internal Root CA"

# 2. Intermediate CA 생성
openssl genrsa -out intermediateCA.key 4096
openssl req -new -key intermediateCA.key \
  -out intermediateCA.csr \
  -subj "/C=KR/O=Allganize/CN=Allganize Internal Intermediate CA"

# Intermediate CA 인증서 서명 (Root CA로)
cat > intermediate_ext.cnf << 'EOF'
[v3_intermediate_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, digitalSignature, cRLSign, keyCertSign
EOF

openssl x509 -req -in intermediateCA.csr -CA rootCA.crt -CAkey rootCA.key \
  -CAcreateserial -out intermediateCA.crt -days 1825 -sha256 \
  -extfile intermediate_ext.cnf -extensions v3_intermediate_ca

# 3. 서버 인증서 생성
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
  -subj "/C=KR/O=Allganize/CN=api.internal.allganize.ai"

cat > server_ext.cnf << 'EOF'
[v3_server]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = api.internal.allganize.ai
DNS.2 = *.internal.allganize.ai
EOF

openssl x509 -req -in server.csr -CA intermediateCA.crt -CAkey intermediateCA.key \
  -CAcreateserial -out server.crt -days 365 -sha256 \
  -extfile server_ext.cnf -extensions v3_server

# 4. 체인 파일 생성 (서버 배포용)
cat server.crt intermediateCA.crt > fullchain.crt

# 5. 검증
openssl verify -CAfile rootCA.crt -untrusted intermediateCA.crt server.crt
# server.crt: OK
```

### cert-manager 전체 설정

```yaml
# 1. cert-manager 설치 (Helm)
# helm repo add jetstack https://charts.jetstack.io
# helm install cert-manager jetstack/cert-manager \
#   --namespace cert-manager --create-namespace \
#   --set installCRDs=true

# 2. ClusterIssuer — Let's Encrypt (프로덕션)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: devops@allganize.ai
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - dns01:                              # 와일드카드 인증서용
        route53:
          region: ap-northeast-2
          hostedZoneID: Z1234567890
      selector:
        dnsZones:
        - "allganize.ai"
    - http01:                             # 일반 인증서용
        ingress:
          class: nginx
---
# 3. ClusterIssuer — 내부 Self-Signed CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca
spec:
  ca:
    secretName: internal-ca-keypair       # Root CA 키페어
---
# 4. Certificate 리소스
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: alli-api-cert
  namespace: production
spec:
  secretName: alli-api-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: api.allganize.ai
  dnsNames:
  - api.allganize.ai
  - "*.api.allganize.ai"
  duration: 2160h                         # 90일
  renewBefore: 360h                       # 만료 15일 전 갱신
  privateKey:
    algorithm: ECDSA
    size: 256
---
# 5. Ingress에서 자동 인증서 연결
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-api
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
  - hosts:
    - api.allganize.ai
    secretName: alli-api-tls              # cert-manager가 자동 생성
  rules:
  - host: api.allganize.ai
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: alli-api
            port:
              number: 8080
```

### 인증서 만료 모니터링

```bash
# 모든 cert-manager 인증서 상태 확인
kubectl get certificates -A

# 특정 인증서 상세 확인
kubectl describe certificate alli-api-cert -n production

# 인증서 만료일 프로메테우스 메트릭
# cert-manager는 자동으로 아래 메트릭 노출:
# certmanager_certificate_expiration_timestamp_seconds
# certmanager_certificate_ready_status

# Grafana 알림 규칙 예시
# ALERT: certmanager_certificate_expiration_timestamp_seconds - time() < 7*24*3600
```

---

## 면접 Q&A

### Q: 인증서 체인이 왜 필요하고, 어떻게 검증되나요?

**30초 답변**:
Root CA 인증서는 OS/브라우저에 내장되어 신뢰의 출발점이 됩니다. Root CA는 보안을 위해 오프라인으로 보관하고, **Intermediate CA**가 실제 인증서를 발급합니다. 클라이언트는 End-Entity → Intermediate → Root CA 순으로 서명을 검증하여 **체인이 Trust Store까지 연결되는지** 확인합니다.

**2분 답변**:
인증서 체인은 신뢰의 위임(Delegation of Trust) 구조입니다.

Root CA는 전 세계에 약 150개로, 각 OS/브라우저에 하드코딩되어 있습니다. Root CA 개인키가 침해되면 그 아래 모든 인증서가 무효화되므로, 개인키는 **HSM(Hardware Security Module)**에 오프라인 보관합니다. 따라서 Root CA가 직접 서버 인증서를 서명하는 것은 비현실적입니다.

Intermediate CA가 이 문제를 해결합니다. Root CA가 Intermediate CA를 서명하고, Intermediate CA가 End-Entity 인증서를 서명합니다. Intermediate CA가 침해되면 해당 CA만 폐기하면 됩니다.

검증 과정은 역순입니다. 클라이언트가 서버로부터 End-Entity + Intermediate 인증서를 받으면:
1. End-Entity 인증서의 Issuer를 확인하고 Intermediate 인증서를 찾음
2. Intermediate 공개키로 End-Entity 서명 검증
3. Intermediate의 Issuer를 확인하고 Trust Store에서 Root CA를 찾음
4. Root CA 공개키로 Intermediate 서명 검증
5. 체인 완성 → 신뢰

서버는 반드시 Intermediate 인증서를 함께 보내야 합니다(fullchain). 누락하면 일부 클라이언트에서 "인증서를 신뢰할 수 없음" 오류가 발생합니다.

**경험 연결**:
"폐쇄망 환경에서 자체 Root CA를 구축하고 모든 서버/클라이언트에 Trust Store를 배포한 경험이 있습니다. 초기에 Intermediate CA 없이 Root CA로 직접 서명했다가, 키 관리 리스크를 인지하고 2-tier PKI로 전환했습니다. Ansible로 Root CA 인증서를 전 노드에 자동 배포하는 파이프라인도 구축했습니다."

**주의**:
- fullchain.crt에 Root CA를 포함하면 안 됨 (클라이언트 Trust Store에 이미 있음, 불필요한 전송)
- SAN 필드가 CN보다 우선. 최신 브라우저는 SAN만 확인하며 CN을 무시할 수 있음

### Q: cert-manager의 동작 원리를 설명해주세요.

**30초 답변**:
cert-manager는 Kubernetes에서 인증서 생명주기를 자동화하는 컨트롤러입니다. **Certificate 리소스**를 생성하면, Issuer를 통해 CA(Let's Encrypt 등)에 인증서를 요청하고, 발급된 인증서를 **Secret으로 저장**합니다. 만료 전에 자동 갱신하며, Ingress 어노테이션만으로도 자동 발급이 가능합니다.

**2분 답변**:
cert-manager는 Kubernetes CRD 기반의 인증서 관리 컨트롤러입니다.

핵심 리소스는 세 가지입니다:
- **Issuer/ClusterIssuer**: 인증서 발급 주체 설정 (Let's Encrypt ACME, 내부 CA, Vault 등)
- **Certificate**: 원하는 인증서 스펙 정의 (도메인, 유효기간, 갱신 시점)
- **CertificateRequest**: 실제 발급 요청 (Certificate 컨트롤러가 자동 생성)

Let's Encrypt 사용 시 동작 흐름은:
1. Certificate 리소스 생성
2. cert-manager가 ACME 프로토콜로 Let's Encrypt에 도메인 소유권 증명 (HTTP-01 또는 DNS-01 챌린지)
3. 인증서 발급 완료 → Kubernetes Secret에 tls.crt, tls.key 저장
4. Ingress가 해당 Secret을 참조하여 TLS 종단
5. renewBefore 시점에 자동 갱신

DNS-01 챌린지는 와일드카드 인증서에 필수이며, Route53/Cloud DNS 등과 연동합니다. HTTP-01은 간단하지만 와일드카드를 지원하지 않습니다.

**경험 연결**:
"온프레미스 환경에서는 인증서 만료 감지가 수동이라 장애가 발생한 적이 있습니다. cert-manager를 도입하면서 인증서 만료로 인한 장애를 완전히 제거할 수 있었고, Prometheus 메트릭으로 만료 예정 인증서를 모니터링하는 대시보드도 구축했습니다."

**주의**:
- HTTP-01 챌린지는 포트 80이 열려있어야 함 (방화벽 확인)
- DNS-01 챌린지에서 DNS 전파 지연(TTL)으로 실패할 수 있음 → propagationTimeout 설정

### Q: Self-Signed CA는 언제 사용하고, 주의사항은 무엇인가요?

**30초 답변**:
**폐쇄망**, **개발/테스트 환경**, **내부 마이크로서비스 간 mTLS**에서 사용합니다. 주의사항은 Root CA 인증서를 모든 클라이언트의 **Trust Store에 등록**해야 한다는 것과, 키 관리(특히 Root CA 개인키 보호)를 철저히 해야 한다는 점입니다.

**2분 답변**:
Self-Signed CA는 세 가지 시나리오에서 사용합니다.

첫째, **폐쇄망/에어갭 환경** — 외부 CA에 접근할 수 없으므로 내부 PKI를 구축해야 합니다.
둘째, **내부 서비스 간 mTLS** — 마이크로서비스 간 상호 인증에 공개 CA 인증서를 사용하면 비용과 관리 부담이 큽니다.
셋째, **개발/테스트 환경** — 빠른 인증서 발급이 필요한 경우.

주의사항:
1. **Trust Store 배포**: 모든 클라이언트/서버에 Root CA 인증서를 신뢰하도록 설정해야 합니다. 누락하면 TLS 오류 발생
2. **키 관리**: Root CA 개인키는 반드시 안전한 곳에 보관. 유출되면 내부 PKI 전체가 무효화
3. **인증서 폐기**: CRL/OCSP 인프라를 자체 구축하지 않으면 폐기된 인증서가 계속 사용될 수 있음
4. **유효기간 관리**: 자동 갱신 메커니즘 없으면 수동 관리 부담

Kubernetes 환경에서는 cert-manager의 CA Issuer로 Self-Signed CA를 등록하면, 내부 인증서 발급/갱신을 자동화할 수 있습니다.

**경험 연결**:
"폐쇄망 프로젝트에서 2-tier Self-Signed PKI를 구축하고, Ansible로 Root CA 인증서를 전 노드에 배포한 경험이 있습니다. 인증서 만료 관리를 위해 crontab + 스크립트로 만료 30일 전 알림을 구현했는데, cert-manager를 사용하면 이 과정이 훨씬 자동화됩니다."

**주의**:
- Self-Signed CA 인증서를 브라우저에서 수동으로 "예외 추가"하는 것은 보안 습관으로 위험 → 반드시 Trust Store에 정상 등록
- 테스트용으로 만든 Self-Signed 인증서를 프로덕션에 사용하지 않도록 관리 체계 필요

---

## Allganize 맥락

### Alli 서비스와의 연결

- **cert-manager 필수**: 멀티 도메인(api.allganize.ai, dashboard.allganize.ai 등) 인증서를 수동 관리하는 것은 불가능 → cert-manager + Let's Encrypt 자동화
- **와일드카드 인증서**: `*.allganize.ai`로 서브도메인 추가 시 인증서 재발급 불필요 (DNS-01 챌린지 사용)
- **내부 mTLS**: 마이크로서비스 간 통신에 Self-Signed CA 기반 mTLS 적용 (Service Mesh와 연계)
- **멀티클라우드 인증서**: AWS ACM, Azure Key Vault에서도 인증서를 관리하되, cert-manager로 통합 관리 가능
- **인증서 모니터링**: Prometheus + certmanager_certificate_expiration_timestamp_seconds 메트릭으로 만료 예정 인증서 알림

### JD 연결 포인트

```
JD: "보안 정책"       → PKI 구축, 인증서 관리, TLS 적용
JD: "자동화"          → cert-manager 인증서 생명주기 자동화
JD: "AWS/Azure"      → ACM/Key Vault 인증서 + cert-manager 통합
JD: "모니터링"        → 인증서 만료 모니터링 대시보드
```

---

**핵심 키워드**: `X.509` `인증서-체인` `Root-CA` `Intermediate-CA` `cert-manager` `ACME` `OCSP-Stapling` `Self-Signed-CA` `SAN`
