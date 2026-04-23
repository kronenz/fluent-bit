# 04. mTLS와 제로 트러스트 — mTLS 동작 원리, Service Mesh(Istio/Linkerd) mTLS 자동화

> **TL;DR**
> - **mTLS(mutual TLS)**는 서버뿐 아니라 **클라이언트도 인증서를 제시**하여 양방향 인증을 수행한다. 일반 TLS와 달리 "누가 요청했는지"를 인프라 레벨에서 검증한다.
> - **제로 트러스트(Zero Trust)**는 "네트워크 위치를 신뢰하지 않는다"는 원칙으로, mTLS는 이를 구현하는 핵심 메커니즘이다.
> - **Istio/Linkerd** 같은 Service Mesh는 사이드카 프록시를 통해 **애플리케이션 수정 없이** mTLS를 자동 적용하고 인증서를 자동 로테이션한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### TLS vs mTLS

```
일반 TLS (단방향 인증):
클라이언트                              서버
    │── ClientHello ─────────────────→│
    │←── ServerHello + Certificate ──│  ← 서버만 인증서 제시
    │   (서버 신원 확인)               │
    │── Key Exchange ────────────────→│
    │═══ 암호화 통신 ════════════════│

    * 클라이언트 신원은 확인 불가
    * 인증은 Application Layer (JWT, API Key 등)에서 처리

mTLS (양방향 인증):
클라이언트                              서버
    │── ClientHello ─────────────────→│
    │←── ServerHello + Certificate ──│  ← 서버 인증서 제시
    │←── CertificateRequest ─────────│  ← 서버가 클라이언트 인증서 요청!
    │── Certificate ─────────────────→│  ← 클라이언트도 인증서 제시!
    │── CertificateVerify ───────────→│  ← 개인키 소유 증명
    │── Key Exchange ────────────────→│
    │═══ 암호화 통신 ════════════════│

    * 양측 모두 인증서로 신원 확인
    * 네트워크 레벨에서 "누구인지" 보장
```

### 왜 mTLS가 필요한가?

```
전통적 보안 모델 (Castle-and-Moat):
┌─────────────────────────────────────────┐
│              신뢰할 수 있는 내부 네트워크  │
│                                         │
│  Service A ──(평문)──→ Service B        │
│       │                    │            │
│       └──(평문)──→ Service C            │
│                                         │
│  "내부이므로 안전하다" ← 잘못된 가정!     │
│                                         │
│  * 내부자 위협                           │
│  * 컨테이너 탈출 (Container Escape)      │
│  * 동일 네트워크의 침해된 Pod             │
│  * 수평 이동 (Lateral Movement)          │
└─────────────────────────────────────────┘

제로 트러스트 모델:
┌─────────────────────────────────────────┐
│              어떤 네트워크도 신뢰하지 않음  │
│                                         │
│  Service A ══(mTLS)══> Service B        │
│       ║                    ║            │
│       ╚══(mTLS)══> Service C            │
│                                         │
│  * 모든 통신 암호화                      │
│  * 모든 서비스 상호 인증                  │
│  * 최소 권한 원칙 (네트워크 정책)          │
│  * 지속적 검증 (인증서 만료/폐기)          │
└─────────────────────────────────────────┘
```

### 제로 트러스트 핵심 원칙

| 원칙 | 설명 | mTLS 기여 |
|------|------|-----------|
| Never Trust, Always Verify | 네트워크 위치와 무관하게 항상 인증 | 모든 연결에서 양측 인증서 검증 |
| Least Privilege | 최소 권한만 부여 | 인증서 기반 서비스 ID로 세밀한 접근 제어 |
| Assume Breach | 침해를 전제하고 설계 | 침해된 서비스가 다른 서비스를 위장 불가 |
| Micro-Segmentation | 세밀한 네트워크 분리 | 서비스 단위 인증 + AuthorizationPolicy |

### Service Mesh mTLS 자동화

```
Service Mesh 아키텍처 (Istio 예시):

┌─────── Pod A ──────────┐     mTLS      ┌─────── Pod B ──────────┐
│ ┌─────────────────────┐│               │┌─────────────────────┐ │
│ │   Application       ││               ││   Application       │ │
│ │   (HTTP 평문)        ││               ││   (HTTP 평문)        │ │
│ └────────┬────────────┘│               │└────────▲────────────┘ │
│          │ localhost    │               │         │ localhost    │
│ ┌────────▼────────────┐│    TLS 1.3    │┌────────┴────────────┐ │
│ │   Envoy Sidecar     ││══════════════>││   Envoy Sidecar     │ │
│ │   (프록시)           ││  양방향 인증   ││   (프록시)           │ │
│ │   - 인증서 자동 발급  ││               ││   - 인증서 자동 발급  │ │
│ │   - 자동 갱신         ││               ││   - 자동 검증         │ │
│ └─────────────────────┘│               │└─────────────────────┘ │
└────────────────────────┘               └────────────────────────┘

         ▲ 인증서 발급/갱신                        ▲
         │                                         │
    ┌────┴──────────────────────────────────────────┴────┐
    │               Istiod (Control Plane)               │
    │                                                    │
    │   * 각 Pod에 SPIFFE ID 기반 인증서 발급              │
    │   * 인증서 자동 로테이션 (기본 24시간)                │
    │   * Root CA 관리                                    │
    │   * 인증서 서명 요청(CSR) 처리                       │
    └────────────────────────────────────────────────────┘
```

**애플리케이션은 mTLS를 전혀 인식하지 못함:**
- 앱은 `http://service-b:8080`으로 평문 요청
- Envoy 사이드카가 자동으로 TLS 암호화 + 인증서 제시
- 수신 측 Envoy가 TLS 복호화 + 인증서 검증
- 앱에는 평문 HTTP로 전달

### SPIFFE/SPIRE — 서비스 ID 표준

```
SPIFFE ID 형식:
  spiffe://trust-domain/path

예시:
  spiffe://allganize.ai/ns/production/sa/alli-api
         │              │              │
         │              │              └─ ServiceAccount
         │              └──────────────── Namespace
         └─────────────────────────────── Trust Domain

SVID (SPIFFE Verifiable Identity Document):
  = X.509 인증서의 SAN에 SPIFFE ID를 포함

Istio에서의 적용:
  * Istiod가 SPIFFE 호환 X.509 인증서를 각 Pod에 발급
  * 인증서의 SAN: spiffe://cluster.local/ns/prod/sa/alli-api
  * AuthorizationPolicy에서 SPIFFE ID 기반으로 접근 제어
```

### Istio vs Linkerd mTLS 비교

| 항목 | Istio | Linkerd |
|------|-------|---------|
| 사이드카 프록시 | Envoy | linkerd2-proxy (Rust) |
| mTLS 기본 활성화 | PERMISSIVE 모드 (선택적) | 기본 활성화 |
| 인증서 관리 | Istiod 내장 CA / 외부 CA | 자체 CA / cert-manager 연동 |
| 인증서 로테이션 | 기본 24시간 | 기본 24시간 |
| 리소스 사용량 | 높음 (Envoy 무거움) | 낮음 (Rust 기반 경량) |
| ID 체계 | SPIFFE | SPIFFE 호환 |
| 접근 제어 | AuthorizationPolicy (풍부) | Server/ServerAuthorization |
| 학습 곡선 | 높음 | 낮음 |
| 적합한 환경 | 대규모, 복잡한 정책 | 중소규모, 빠른 도입 |

---

## 실전 예시

### Istio mTLS 설정

```yaml
# 1. PeerAuthentication — 네임스페이스 전체 STRICT mTLS
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: production
spec:
  mtls:
    mode: STRICT                # STRICT: mTLS 필수
                                # PERMISSIVE: mTLS와 평문 모두 허용
                                # DISABLE: mTLS 비활성화
---
# 2. 특정 서비스만 예외 (레거시 서비스 등)
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: legacy-exception
  namespace: production
spec:
  selector:
    matchLabels:
      app: legacy-service
  mtls:
    mode: PERMISSIVE            # 이 서비스만 평문도 허용
---
# 3. AuthorizationPolicy — 서비스 간 접근 제어
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: alli-api-policy
  namespace: production
spec:
  selector:
    matchLabels:
      app: alli-api
  action: ALLOW
  rules:
  - from:
    - source:
        principals:
        - "cluster.local/ns/production/sa/alli-gateway"
        - "cluster.local/ns/production/sa/alli-worker"
    to:
    - operation:
        methods: ["GET", "POST"]
        paths: ["/api/*"]
---
# 4. 기본 거부 정책 (Zero Trust 기본)
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: deny-all
  namespace: production
spec:
  {}                            # 빈 spec = 모든 트래픽 거부
```

### Linkerd mTLS 설정

```bash
# Linkerd 설치
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -

# 네임스페이스에 자동 주입 활성화
kubectl annotate namespace production linkerd.io/inject=enabled

# 기존 Deployment에 Linkerd 사이드카 주입
kubectl rollout restart deployment/alli-api -n production

# mTLS 상태 확인
linkerd viz stat deploy -n production
# NAME       MESHED   SUCCESS   RPS   LATENCY_P50   LATENCY_P99
# alli-api   2/2      100.00%   25    2ms           15ms

# 특정 서비스 간 mTLS 연결 확인
linkerd viz edges deploy -n production
# SRC          DST          SRC_NS      DST_NS       SECURED
# alli-gw      alli-api     production  production   √
# alli-api     alli-worker  production  production   √
```

### Linkerd ServerAuthorization

```yaml
# Server 리소스 — 포트별 정책 정의
apiVersion: policy.linkerd.io/v1beta1
kind: Server
metadata:
  name: alli-api-server
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: alli-api
  port: 8080
  proxyProtocol: HTTP/2
---
# ServerAuthorization — 접근 제어
apiVersion: policy.linkerd.io/v1beta1
kind: ServerAuthorization
metadata:
  name: alli-api-auth
  namespace: production
spec:
  server:
    name: alli-api-server
  client:
    meshTLS:
      serviceAccounts:
      - name: alli-gateway
        namespace: production
      - name: alli-worker
        namespace: production
```

### mTLS 디버깅

```bash
# Istio: 서비스 간 mTLS 상태 확인
istioctl x describe pod <pod-name> -n production

# Istio: Envoy 프록시 설정 확인
istioctl proxy-config cluster <pod-name> -n production
istioctl proxy-config secret <pod-name> -n production

# 인증서 상세 확인 (Istio sidecar에서)
kubectl exec -it <pod-name> -c istio-proxy -n production -- \
  openssl x509 -in /var/run/secrets/istio/cert-chain.pem -noout -text

# Linkerd: 트래픽 암호화 상태 확인
linkerd viz tap deploy/alli-api -n production --to deploy/alli-worker
# 출력에서 tls=true 확인

# tcpdump로 mTLS 트래픽 확인 (암호화 여부)
kubectl exec -it <pod-name> -c istio-proxy -- \
  tcpdump -i eth0 -A port 8080 -c 10
# 암호화된 바이너리 데이터만 보여야 정상
```

---

## 면접 Q&A

### Q: mTLS란 무엇이고, 일반 TLS와 어떻게 다른가요?

**30초 답변**:
일반 TLS는 **서버만** 인증서를 제시하여 클라이언트가 서버를 검증합니다. mTLS는 **클라이언트도 인증서를 제시**하여 서버가 클라이언트를 검증합니다. 이를 통해 "누가 요청했는지"를 네트워크 레벨에서 보장하며, 제로 트러스트 아키텍처의 핵심 구성 요소입니다.

**2분 답변**:
일반 TLS에서 클라이언트는 서버의 인증서를 검증하여 "내가 올바른 서버에 접속했는지" 확인할 수 있습니다. 하지만 서버 입장에서는 "누가 요청했는지" 알 수 없고, 이를 위해 JWT, API Key 같은 Application Layer 인증을 별도로 구현해야 합니다.

mTLS는 TLS 핸드셰이크에서 서버가 `CertificateRequest`를 보내 클라이언트에게도 인증서를 요구합니다. 클라이언트가 인증서와 `CertificateVerify`(개인키 소유 증명)를 보내면, 서버는 클라이언트의 신원을 암호학적으로 검증할 수 있습니다.

이것이 중요한 이유는 **제로 트러스트** 원칙 때문입니다. 마이크로서비스 환경에서 "같은 VPC 안이니까 안전하다"는 가정은 위험합니다. 침해된 Pod가 다른 서비스를 호출하거나, 네트워크를 도청할 수 있기 때문입니다.

mTLS를 적용하면:
1. 인증서 없는 서비스는 통신 자체가 불가능 → 위장 방지
2. 모든 트래픽이 암호화 → 도청 방지
3. 인증서의 SPIFFE ID로 세밀한 접근 제어 가능

Service Mesh(Istio/Linkerd)를 사용하면 애플리케이션 코드 수정 없이 사이드카 프록시가 mTLS를 자동 처리합니다.

**경험 연결**:
"폐쇄망 환경에서 내부 서비스 간 통신이 평문이라 보안 감사에서 지적을 받은 경험이 있습니다. 당시에는 각 서비스에 직접 TLS를 구현해야 했는데, Service Mesh의 mTLS 자동화가 이 문제를 인프라 레벨에서 해결한다는 점이 큰 장점입니다."

**주의**:
- mTLS는 "암호화"뿐 아니라 "인증"이 핵심. 단순히 트래픽을 암호화하는 것과 다름
- PERMISSIVE 모드는 마이그레이션용이며, 최종적으로 STRICT로 전환해야 제로 트러스트

### Q: Service Mesh 없이 mTLS를 구현할 수 있나요?

**30초 답변**:
가능합니다. 각 서비스에서 직접 TLS 라이브러리를 사용하여 인증서를 로드하고 검증 로직을 구현할 수 있습니다. 하지만 인증서 발급/갱신/로테이션을 각 서비스가 개별 처리해야 하므로 **운영 부담이 매우 큽니다**. Service Mesh는 이를 인프라 레벨에서 자동화합니다.

**2분 답변**:
Service Mesh 없이 mTLS를 구현하는 방법은 여러 가지입니다.

첫째, **애플리케이션 레벨**: Go의 `crypto/tls`, Python의 `ssl` 모듈 등으로 직접 구현. 하지만 모든 서비스 코드를 수정해야 하고, 언어/프레임워크마다 구현이 다릅니다.

둘째, **SPIRE 직접 사용**: SPIFFE/SPIRE 에이전트를 각 노드에 배포하고, Envoy SDS(Secret Discovery Service)와 연동하여 인증서를 자동 발급.

셋째, **cert-manager + 수동 마운트**: cert-manager로 인증서를 발급하고 Volume으로 마운트. 하지만 갱신 시 서비스 재시작이 필요할 수 있음.

Service Mesh가 우월한 이유:
- 인증서 발급/갱신/폐기를 **완전 자동화** (기본 24시간 로테이션)
- 애플리케이션 **코드 수정 불필요** (사이드카가 투명하게 처리)
- SPIFFE ID 기반 **접근 제어** 정책을 선언적으로 관리
- **관측 가능성** — mTLS 성공/실패, 지연 시간 등 자동 메트릭 수집

단, Service Mesh는 사이드카로 인한 **리소스 오버헤드**와 **복잡성**이 단점입니다. 소규모 환경에서는 cert-manager + 수동 구현이 더 적합할 수 있습니다.

**경험 연결**:
"온프레미스 환경에서 Service Mesh 도입 이전에 각 서비스에 직접 TLS를 설정한 경험이 있는데, 인증서 갱신 시 서비스 재시작이 필요하여 다운타임이 발생했습니다. Service Mesh의 사이드카 기반 자동 로테이션이 이 문제를 해결합니다."

**주의**:
- Service Mesh의 사이드카는 요청당 1~3ms 정도의 latency를 추가 → LLM 추론처럼 이미 수백ms인 서비스에서는 무시 가능하지만, 초저지연 서비스에서는 고려 필요

### Q: Istio의 PeerAuthentication과 AuthorizationPolicy의 차이는?

**30초 답변**:
**PeerAuthentication**은 mTLS **활성화 여부**(STRICT/PERMISSIVE)를 제어합니다. **AuthorizationPolicy**는 mTLS로 인증된 서비스에 대해 **어떤 요청을 허용/거부할지** 결정합니다. PeerAuthentication이 "문을 잠글지", AuthorizationPolicy가 "누구를 들여보낼지"를 결정합니다.

**2분 답변**:
PeerAuthentication은 **전송 계층** 보안 정책입니다. mTLS 모드를 STRICT(mTLS 필수), PERMISSIVE(mTLS와 평문 모두 허용), DISABLE(mTLS 비활성화)로 설정합니다. 네임스페이스 단위 또는 워크로드 단위로 적용할 수 있습니다.

AuthorizationPolicy는 **애플리케이션 계층** 접근 제어 정책입니다. mTLS로 확인된 서비스 ID(SPIFFE principal)를 기반으로, 어떤 source에서 어떤 HTTP method/path로의 요청을 허용할지 정의합니다.

예를 들어:
1. PeerAuthentication: production 네임스페이스에서 STRICT mTLS 적용
2. AuthorizationPolicy: alli-api에는 alli-gateway와 alli-worker만 접근 허용

제로 트러스트를 구현하려면:
1. 먼저 모든 네임스페이스에 deny-all AuthorizationPolicy를 적용
2. 필요한 서비스 간 통신만 명시적으로 ALLOW
3. PeerAuthentication은 STRICT로 설정

**경험 연결**:
"방화벽 정책 관리 경험과 유사합니다. 네트워크 방화벽에서 기본 DENY + 필요 포트만 ALLOW하는 것처럼, Istio에서도 기본 거부 + 명시적 허용 정책을 적용하는 것이 베스트 프랙티스입니다."

**주의**:
- AuthorizationPolicy의 빈 spec `{}`은 **모든 트래픽 거부**를 의미
- PERMISSIVE → STRICT 전환 시 mTLS가 아닌 트래픽이 차단되므로 사전 검증 필수

---

## Allganize 맥락

### Alli 서비스와의 연결

- **마이크로서비스 보안**: Alli의 API Gateway → LLM Engine → Vector DB 간 통신에 mTLS 적용으로 서비스 간 인증 보장
- **고객 데이터 보호**: AI 서비스가 처리하는 고객 데이터의 전송 중 암호화(Encryption in Transit) 요건 충족
- **멀티클라우드 제로 트러스트**: AWS와 Azure에 분산된 서비스 간에도 mTLS로 일관된 보안 적용
- **Service Mesh 선택**: Alli 서비스 규모와 복잡도에 따라 Istio(대규모, 세밀한 정책) 또는 Linkerd(경량, 빠른 도입) 선택
- **SPIFFE ID 기반 RBAC**: "이 서비스만 LLM 엔진에 접근 가능" 같은 정책을 인증서 기반으로 강제

### JD 연결 포인트

```
JD: "보안 정책"         → mTLS, 제로 트러스트 아키텍처
JD: "Kubernetes"       → Service Mesh (Istio/Linkerd) 운영
JD: "안정적 서비스 운영" → 인증서 자동 로테이션, 접근 제어 자동화
JD: "복원력"           → mTLS 기반 서비스 격리, 침해 확산 방지
```

---

**핵심 키워드**: `mTLS` `제로-트러스트` `SPIFFE` `Istio` `Linkerd` `PeerAuthentication` `AuthorizationPolicy` `사이드카-프록시` `서비스-메시`
