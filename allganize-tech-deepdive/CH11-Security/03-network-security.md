# Network Security: NetworkPolicy, Zero Trust, Service Mesh

> **TL;DR**: Kubernetes NetworkPolicy는 Pod 간 트래픽을 L3/L4에서 제어하며, 기본적으로 모든 트래픽이 허용(allow-all)되므로 명시적 정책 적용이 필수다.
> Zero Trust 모델은 "절대 신뢰하지 않고 항상 검증"하는 원칙으로, Service Mesh(Istio/Linkerd)의 mTLS와 authorization policy로 구현한다.
> WAF(Web Application Firewall)는 L7에서 OWASP Top 10 공격을 방어하며, Ingress 앞단에 배치한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Kubernetes 기본 네트워크 모델

```
  ┌─────────────────────────────────────────┐
  │         Kubernetes Cluster               │
  │                                          │
  │  기본 상태: ALL TRAFFIC ALLOWED           │
  │                                          │
  │  Pod A ◄────────► Pod B                  │
  │    │                 │                    │
  │    │    모든 Pod 간   │                    │
  │    │    통신 허용     │                    │
  │    ▼                 ▼                    │
  │  Pod C ◄────────► Pod D                  │
  │                                          │
  │  NetworkPolicy 적용 후:                   │
  │  명시적으로 허용된 트래픽만 통과             │
  └─────────────────────────────────────────┘
```

**중요**: NetworkPolicy는 CNI 플러그인이 지원해야 동작한다.

| CNI | NetworkPolicy 지원 |
|-----|-------------------|
| Calico | O (L3/L4 + L7 일부) |
| Cilium | O (L3/L4 + L7, eBPF 기반) |
| AWS VPC CNI + Calico | O |
| Flannel | **X** (정책 무시됨) |
| WeaveNet | O |

### NetworkPolicy 구조

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ai-serving-policy
  namespace: ai-serving
spec:
  # 정책 대상 Pod 선택
  podSelector:
    matchLabels:
      app: ai-model

  # 적용할 트래픽 방향
  policyTypes:
  - Ingress    # 들어오는 트래픽 제어
  - Egress     # 나가는 트래픽 제어

  # Ingress 규칙: 허용할 인바운드 트래픽
  ingress:
  - from:
    - namespaceSelector:        # 특정 NS에서만
        matchLabels:
          purpose: api-gateway
    - podSelector:              # 또는 특정 Pod에서만
        matchLabels:
          app: api-gateway
    ports:
    - protocol: TCP
      port: 8080

  # Egress 규칙: 허용할 아웃바운드 트래픽
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          purpose: database
    ports:
    - protocol: TCP
      port: 5432
  - to:                         # DNS 허용 (필수!)
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### NetworkPolicy 동작 원리

```
  NetworkPolicy 선택 로직:

  1. podSelector가 비어있으면 → 해당 NS의 모든 Pod에 적용
  2. policyTypes에 Ingress가 있으면 → ingress 규칙에 매칭되는 트래픽만 허용
  3. policyTypes에 Egress가 있으면 → egress 규칙에 매칭되는 트래픽만 허용
  4. ingress/egress 블록이 비어있으면 → 해당 방향 모든 트래픽 차단

  ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
  │ Default Deny │────►│ Allow Rules  │────►│ Final State │
  │ (implicit)   │     │ (explicit)   │     │             │
  └─────────────┘     └──────────────┘     └─────────────┘
```

### Default Deny 정책 (필수 기본)

```yaml
# 1. 모든 인바운드 트래픽 차단 (Namespace 단위)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: ai-serving
spec:
  podSelector: {}          # 모든 Pod
  policyTypes:
  - Ingress                # ingress 규칙 없음 = 모두 차단

---
# 2. 모든 아웃바운드 트래픽 차단
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: ai-serving
spec:
  podSelector: {}
  policyTypes:
  - Egress

---
# 3. DNS만 허용 (egress deny 후 필수)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: ai-serving
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Zero Trust 네트워크 모델

```
  전통적 모델 (Castle & Moat)        Zero Trust 모델
  ┌─────────────────────┐           ┌─────────────────────┐
  │  ┌───────────────┐  │           │                     │
  │  │ 내부 = 신뢰   │  │           │  모든 통신을 검증    │
  │  │  자유 통신    │  │           │                     │
  │  └───────────────┘  │           │  Pod A ──mTLS──► B  │
  │         ▲           │           │    │  인증+인가+암호화│
  │    방화벽(경계보안)  │           │    ▼                 │
  │         │           │           │  Pod C ──mTLS──► D  │
  │  외부 = 비신뢰      │           │                     │
  └─────────────────────┘           └─────────────────────┘
```

**Zero Trust 핵심 원칙**:
1. **Never Trust, Always Verify**: 네트워크 위치와 무관하게 항상 인증/인가
2. **Least Privilege Access**: 필요한 최소한의 접근만 허용
3. **Assume Breach**: 침입은 이미 발생했다고 가정, blast radius 최소화
4. **Micro-Segmentation**: Pod/Service 단위의 세밀한 네트워크 분리

### Service Mesh Security (Istio 예시)

```
  ┌──────────────────────────────────────────┐
  │  Service Mesh (Istio)                     │
  │                                           │
  │  Pod A                    Pod B           │
  │  ┌─────────────────┐    ┌─────────────┐  │
  │  │ App Container   │    │ App Container│  │
  │  │    (plaintext)  │    │  (plaintext) │  │
  │  ├─────────────────┤    ├─────────────┤  │
  │  │ Envoy Sidecar   │───►│Envoy Sidecar│  │
  │  │  ├ mTLS 암호화  │    │ ├ mTLS 복호화│  │
  │  │  ├ 인증 (SPIFFE)│    │ ├ 인증 검증  │  │
  │  │  └ 인가 (AuthZ) │    │ └ 인가 검증  │  │
  │  └─────────────────┘    └─────────────┘  │
  │          │                                │
  │          ▼                                │
  │  ┌─────────────────┐                      │
  │  │   istiod         │                      │
  │  │  ├ CA (인증서)   │                      │
  │  │  ├ Config (xDS)  │                      │
  │  │  └ Service Disc. │                      │
  │  └─────────────────┘                      │
  └──────────────────────────────────────────┘
```

**mTLS (Mutual TLS)**:
```yaml
# PeerAuthentication: mTLS 모드 설정
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: ai-serving
spec:
  mtls:
    mode: STRICT       # mTLS 강제 (plaintext 거부)
    # PERMISSIVE: mTLS + plaintext 모두 허용 (마이그레이션 중)
    # DISABLE: mTLS 비활성화
```

**Authorization Policy**:
```yaml
# L7 수준의 접근 제어
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: ai-model-authz
  namespace: ai-serving
spec:
  selector:
    matchLabels:
      app: ai-model
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/api-gateway/sa/gateway-sa"]
    to:
    - operation:
        methods: ["POST"]
        paths: ["/v1/predict", "/v1/chat"]
    when:
    - key: request.headers[x-api-key]
      notValues: [""]
```

### WAF (Web Application Firewall)

```
  Internet
     │
     ▼
  ┌──────────────┐
  │  Cloud WAF    │  AWS WAF / Azure WAF / Cloudflare
  │  (L7 필터링)  │
  │  ├ SQL Injection    차단 │
  │  ├ XSS              차단 │
  │  ├ Path Traversal   차단 │
  │  ├ Rate Limiting    적용 │
  │  └ Bot Detection    탐지 │
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ Load Balancer │  ALB / NLB
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ Ingress       │  NGINX / Istio Gateway
  │ Controller    │
  └──────┬───────┘
         ▼
  ┌──────────────┐
  │ K8s Service   │
  └──────────────┘
```

**AWS WAF 규칙 예시**:
```json
{
  "Rules": [
    {
      "Name": "AWSManagedRulesCommonRuleSet",
      "Priority": 1,
      "Statement": {
        "ManagedRuleGroupStatement": {
          "VendorName": "AWS",
          "Name": "AWSManagedRulesCommonRuleSet"
        }
      },
      "Action": { "Block": {} }
    },
    {
      "Name": "RateLimit-API",
      "Priority": 2,
      "Statement": {
        "RateBasedStatement": {
          "Limit": 1000,
          "AggregateKeyType": "IP"
        }
      },
      "Action": { "Block": {} }
    }
  ]
}
```

---

## 실전 예시

### AI 서비스 네트워크 정책 설계

```yaml
# API Gateway → AI Model 서빙만 허용
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-gateway-to-model
  namespace: ai-serving
spec:
  podSelector:
    matchLabels:
      app: ai-model
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          purpose: api-gateway
      podSelector:
        matchLabels:
          app: gateway
    ports:
    - protocol: TCP
      port: 8080

---
# AI Model → 외부 LLM API 호출 허용 (Azure OpenAI 등)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-model-to-external-llm
  namespace: ai-serving
spec:
  podSelector:
    matchLabels:
      app: ai-model
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 443
  - to:                    # DNS
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
```

### Cilium L7 NetworkPolicy (확장)

```yaml
# HTTP 경로 수준 제어 (Cilium 전용)
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: l7-ai-model-policy
  namespace: ai-serving
spec:
  endpointSelector:
    matchLabels:
      app: ai-model
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: gateway
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
      rules:
        http:
        - method: "POST"
          path: "/v1/predict"
        - method: "POST"
          path: "/v1/chat/completions"
        - method: "GET"
          path: "/healthz"
```

---

## 면접 Q&A

### Q: Kubernetes NetworkPolicy의 동작 원리와 Default Deny 전략을 설명해주세요.
**30초 답변**:
NetworkPolicy는 podSelector로 대상 Pod를 선택하고, ingress/egress 규칙으로 허용할 트래픽을 정의합니다. 기본적으로 모든 트래픽이 허용되므로, Default Deny 정책을 먼저 적용하고 필요한 통신만 명시적으로 허용하는 것이 보안 모범 사례입니다.

**2분 답변**:
Kubernetes 기본 네트워크 모델은 모든 Pod 간 통신이 허용됩니다. NetworkPolicy를 적용하면 대상 Pod에 대해 "명시적으로 허용된 트래픽만 통과"하는 화이트리스트 모델로 전환됩니다. 핵심 동작 원리는 additive(합산)입니다. 여러 NetworkPolicy가 같은 Pod를 선택하면 각 정책의 허용 규칙이 합산됩니다. 차단 규칙은 없으며, 허용되지 않은 트래픽은 묵시적으로 차단됩니다. Default Deny 전략은 3단계입니다. 첫째, `podSelector: {}`와 빈 ingress 규칙으로 모든 인바운드를 차단합니다. 둘째, 동일하게 egress도 차단합니다. 셋째, DNS(UDP/TCP 53)를 egress에서 명시적으로 허용합니다. DNS를 허용하지 않으면 서비스 디스커버리가 전혀 동작하지 않는 실수를 주의해야 합니다. CNI에 따라 지원 수준이 다르며, Flannel은 NetworkPolicy를 지원하지 않으므로 Calico나 Cilium을 사용해야 합니다.

**💡 경험 연결**:
폐쇄망 환경에서 방화벽 정책 관리 경험이 있어 화이트리스트 기반 네트워크 정책 설계에 익숙합니다. Kubernetes NetworkPolicy도 동일한 원칙으로 접근하되, Pod Label 기반이라 IP 기반보다 동적 환경에 적합합니다.

**⚠️ 주의**:
NetworkPolicy의 `namespaceSelector`와 `podSelector`를 같은 `from` 항목에 넣으면 AND 조건, 별도 항목으로 분리하면 OR 조건이 된다. 이 차이를 정확히 이해해야 한다.

### Q: Zero Trust 네트워크 모델을 Kubernetes에서 어떻게 구현하나요?
**30초 답변**:
NetworkPolicy로 기본 마이크로세그멘테이션을 구현하고, Service Mesh(Istio/Linkerd)의 mTLS로 모든 Pod 간 통신을 암호화하며, Authorization Policy로 서비스 Identity 기반 L7 접근 제어를 적용합니다.

**2분 답변**:
Zero Trust의 "Never Trust, Always Verify" 원칙을 Kubernetes에서 구현하려면 4가지 계층이 필요합니다. 첫째, NetworkPolicy로 L3/L4 마이크로세그멘테이션을 적용합니다. Default Deny 후 필요한 통신만 허용합니다. 둘째, Service Mesh의 mTLS로 모든 Pod 간 트래픽을 암호화합니다. Istio의 PeerAuthentication을 STRICT 모드로 설정하면 평문 통신이 차단됩니다. 셋째, Service Mesh의 AuthorizationPolicy로 SPIFFE Identity 기반의 L7 접근 제어를 적용합니다. HTTP method, path, header 수준에서 제어할 수 있습니다. 넷째, 외부 진입점에 WAF를 배치하여 OWASP Top 10 공격을 방어합니다. 추가로 Cilium의 eBPF 기반 L7 정책을 사용하면 Sidecar 없이도 HTTP 경로 수준 제어가 가능합니다. 이 계층적 방어(Defense in Depth)가 Zero Trust의 실질적 구현입니다.

**💡 경험 연결**:
폐쇄망에서도 내부 네트워크 세그멘테이션은 필수였습니다. VLAN과 방화벽으로 구현하던 것을 Kubernetes에서는 NetworkPolicy와 Service Mesh로 더 유연하게 구현할 수 있어, 기존 네트워크 보안 경험이 직접 활용됩니다.

**⚠️ 주의**:
mTLS는 통신 암호화와 상호 인증을 제공하지만, **인가(Authorization)**는 별도로 구현해야 한다. mTLS만으로는 "누가 어떤 API를 호출할 수 있는가"를 제어할 수 없다.

### Q: Service Mesh의 mTLS와 NetworkPolicy의 차이점은 무엇인가요?
**30초 답변**:
NetworkPolicy는 L3/L4에서 IP/Port 기반으로 트래픽을 허용/차단하고, Service Mesh mTLS는 L7에서 서비스 Identity 기반 인증과 트래픽 암호화를 제공합니다. 둘은 대체 관계가 아니라 보완 관계입니다.

**2분 답변**:
NetworkPolicy는 커널 수준(iptables/eBPF)에서 동작하며 IP, Port, Protocol 기반으로 트래픽을 제어합니다. 장점은 오버헤드가 거의 없고 CNI만 지원하면 추가 인프라가 불필요합니다. 단점은 트래픽 암호화가 없고, HTTP 경로나 헤더 수준 제어가 불가능합니다. Service Mesh mTLS는 Sidecar Proxy(Envoy)에서 동작하며, X.509 인증서 기반 상호 인증과 TLS 암호화를 제공합니다. SPIFFE Identity로 서비스를 식별하므로 IP가 변해도 정책이 유효합니다. AuthorizationPolicy로 HTTP method, path, header 수준의 세밀한 제어가 가능합니다. 단점은 Sidecar로 인한 리소스 오버헤드(CPU/메모리)와 latency 증가(~1ms)입니다. 운영 환경에서는 둘 다 적용하는 것이 모범 사례입니다. NetworkPolicy로 네트워크 수준 격리를 하고, Service Mesh로 서비스 수준 인증/인가/암호화를 추가하는 계층적 방어(Defense in Depth)를 구현합니다.

**💡 경험 연결**:
방화벽(L3/L4)과 WAF(L7)를 함께 운영한 경험과 동일한 계층적 방어 개념입니다. Kubernetes에서는 NetworkPolicy가 방화벽, Service Mesh가 L7 보안 역할을 담당합니다.

**⚠️ 주의**:
Service Mesh 도입 시 기존 NetworkPolicy가 Sidecar 트래픽(15001, 15006 포트)을 차단할 수 있다. Mesh 도입 전 NetworkPolicy와의 호환성을 반드시 검증해야 한다.

---

## Allganize 맥락

- **AI API 보호**: Allganize의 Alli API는 외부 고객이 호출하므로, WAF로 injection 공격을 차단하고, Rate Limiting으로 API 남용을 방지해야 한다.
- **LLM 파이프라인 격리**: 모델 학습, 서빙, 데이터 전처리 각 단계를 NetworkPolicy로 격리하여 한 컴포넌트의 침해가 전체로 확산되지 않도록 한다(blast radius 최소화).
- **멀티테넌시 네트워크 격리**: 고객별 Namespace에 Default Deny를 적용하고, 공유 서비스(모니터링, 로깅)만 선택적으로 허용하는 구조.
- **폐쇄망 경험 활용**: 방화벽 정책 관리, VLAN 세그멘테이션, 네트워크 ACL 경험이 Kubernetes 네트워크 보안 설계에 직접 대응됨.
- **JD 연관**: "인프라 취약점 관리"에서 네트워크 보안은 핵심 영역. NetworkPolicy 미적용이 가장 흔한 K8s 보안 취약점 중 하나.

---
**핵심 키워드**: `NetworkPolicy` `Default-Deny` `Zero-Trust` `mTLS` `Service-Mesh` `Istio` `Cilium` `WAF` `Micro-Segmentation` `Defense-in-Depth`
