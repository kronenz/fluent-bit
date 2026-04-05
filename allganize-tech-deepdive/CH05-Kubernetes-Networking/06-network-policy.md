# NetworkPolicy 작성과 운영 (Network Policy)

> **TL;DR**: Kubernetes NetworkPolicy는 Pod 간 트래픽을 제어하는 방화벽 규칙이다. Namespace/Pod selector와 CIDR 기반으로 Ingress/Egress를 허용하며, "default deny + explicit allow" 패턴이 보안 모범 사례다. Cilium 확장 정책은 L7(HTTP, DNS) 수준 제어와 FQDN 기반 Egress를 추가 지원한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### NetworkPolicy 기본 구조

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: alli-prod
spec:
  podSelector:              # 이 정책이 적용될 Pod
    matchLabels:
      app: alli-backend
  policyTypes:
    - Ingress               # 들어오는 트래픽 제어
    - Egress                # 나가는 트래픽 제어
  ingress:                  # 허용할 인바운드 규칙
    - from:
        - podSelector:
            matchLabels:
              app: alli-frontend
        - namespaceSelector:
            matchLabels:
              env: production
      ports:
        - protocol: TCP
          port: 8080
  egress:                   # 허용할 아웃바운드 규칙
    - to:
        - podSelector:
            matchLabels:
              app: alli-db
      ports:
        - protocol: TCP
          port: 27017
```

### 핵심 동작 원리

```
NetworkPolicy가 없는 상태:
  모든 Pod ←→ 모든 Pod 통신 가능 (default allow)

podSelector에 매칭되는 Pod에 NetworkPolicy가 1개라도 적용되면:
  해당 policyType(Ingress/Egress)에 대해 default deny
  → 명시적으로 허용된 트래픽만 통과

중요: NetworkPolicy는 "허용(allow)" 규칙만 정의
  → "거부(deny)" 규칙은 없음
  → 여러 정책은 OR(합집합)로 결합
```

```
┌─────────────────────────────────────────────────┐
│  NetworkPolicy 적용 흐름                          │
│                                                   │
│  1. Pod에 매칭되는 NetworkPolicy 확인              │
│     │                                             │
│     ├─ 없음 → 모든 트래픽 허용 (default allow)    │
│     │                                             │
│     └─ 있음 → policyType 확인                     │
│          │                                        │
│          ├─ Ingress 정책 있음 → ingress default deny │
│          │   └─ 규칙에 매칭 → 허용                │
│          │   └─ 매칭 안 됨  → 차단                │
│          │                                        │
│          └─ Egress 정책 있음 → egress default deny│
│              └─ 규칙에 매칭 → 허용                │
│              └─ 매칭 안 됨  → 차단                │
└─────────────────────────────────────────────────┘
```

### from/to 셀렉터의 AND/OR 규칙

이 부분은 면접에서 자주 혼동되는 포인트이다.

```yaml
# 케이스 1: OR 조건 (배열의 각 항목)
ingress:
  - from:
      - podSelector:          # 조건 A
          matchLabels:
            app: frontend
      - namespaceSelector:    # 조건 B
          matchLabels:
            env: staging
# → "frontend Pod" 또는 "staging namespace의 모든 Pod" (OR)

# 케이스 2: AND 조건 (같은 항목 내 두 selector)
ingress:
  - from:
      - podSelector:          # 조건 A
          matchLabels:
            app: frontend
        namespaceSelector:    # AND 조건 B
          matchLabels:
            env: staging
# → "staging namespace에 있는 frontend Pod" (AND)
```

```
OR (두 개의 - 항목):           AND (한 개의 - 항목 내):
  - podSelector: A             - podSelector: A
  - namespaceSelector: B         namespaceSelector: B

  A 또는 B 매칭 → 허용          A 그리고 B 모두 매칭 → 허용
```

### 보안 모범 사례: Default Deny + Explicit Allow

```yaml
# Step 1: Default Deny All (Namespace 수준)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: alli-prod
spec:
  podSelector: {}           # 모든 Pod에 적용
  policyTypes:
    - Ingress
    - Egress
# → 이 Namespace의 모든 Pod는 모든 inbound/outbound 차단

---
# Step 2: DNS 허용 (거의 모든 Pod에 필요)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: alli-prod
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53

---
# Step 3: 서비스별 허용 규칙
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-api
  namespace: alli-prod
spec:
  podSelector:
    matchLabels:
      app: alli-api
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: alli-frontend
      ports:
        - protocol: TCP
          port: 8080
```

### Cilium 확장 NetworkPolicy

Kubernetes 표준 NetworkPolicy의 한계를 Cilium이 확장한다.

| 기능 | K8s 표준 | Cilium 확장 |
|------|---------|------------|
| L3/L4 (IP, Port) | 지원 | 지원 |
| L7 (HTTP method/path) | 미지원 | CiliumNetworkPolicy |
| FQDN 기반 Egress | 미지원 | toFQDNs |
| DNS 기반 정책 | 미지원 | DNS-aware policy |
| Node 기반 정책 | 미지원 | CiliumClusterwideNetworkPolicy |
| Identity 기반 | 미지원 | Cilium Identity |
| Deny 규칙 | 미지원 | CiliumClusterwideNetworkPolicy (deny) |

```yaml
# Cilium L7 HTTP 정책 예시
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: alli-api-l7
  namespace: alli-prod
spec:
  endpointSelector:
    matchLabels:
      app: alli-api
  ingress:
    - fromEndpoints:
        - matchLabels:
            app: alli-frontend
      toPorts:
        - ports:
            - port: "8080"
              protocol: TCP
          rules:
            http:
              - method: "GET"
                path: "/api/v1/health"
              - method: "POST"
                path: "/api/v1/chat/completions"
              # PUT, DELETE 등은 차단됨
```

```yaml
# Cilium FQDN 기반 Egress 정책
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: alli-engine-egress
  namespace: alli-prod
spec:
  endpointSelector:
    matchLabels:
      app: alli-engine
  egress:
    - toFQDNs:
        - matchPattern: "*.openai.com"
        - matchName: "api.anthropic.com"
        - matchPattern: "*.amazonaws.com"
      toPorts:
        - ports:
            - port: "443"
    # DNS 조회 허용 (FQDN 정책의 전제 조건)
    - toEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: kube-system
            k8s-app: kube-dns
      toPorts:
        - ports:
            - port: "53"
              protocol: UDP
          rules:
            dns:
              - matchPattern: "*"
```

### 실제 마이크로서비스 네트워크 정책 설계

```
┌──────────────────────────────────────────────────────┐
│  Alli Service Architecture (예상)                      │
│                                                        │
│  Internet                                              │
│     │                                                  │
│     ▼                                                  │
│  ┌──────────┐  allow:443  ┌──────────┐               │
│  │ Ingress  │────────────►│ alli-api │               │
│  │Controller│             │ (API GW) │               │
│  └──────────┘             └────┬─────┘               │
│                                │                      │
│                    ┌───────────┼───────────┐          │
│                    ▼           ▼           ▼          │
│              ┌──────────┐ ┌──────────┐ ┌────────┐    │
│              │ alli-chat│ │alli-embed│ │alli-rag│    │
│              │ (추론)   │ │(임베딩)  │ │(RAG)   │    │
│              └────┬─────┘ └────┬─────┘ └───┬────┘    │
│                   │            │           │          │
│              ┌────▼────┐  ┌───▼────┐  ┌───▼────┐    │
│              │ Redis   │  │Vector  │  │MongoDB │    │
│              │ (캐시)  │  │DB      │  │        │    │
│              └─────────┘  └────────┘  └────────┘    │
│                                                        │
│  Egress: *.openai.com, *.amazonaws.com만 허용          │
└──────────────────────────────────────────────────────┘
```

---

## 실전 예시

### NetworkPolicy 테스트

```bash
# 테스트용 Pod 생성
kubectl run client --image=nicolaka/netshoot --rm -it -n alli-prod -- bash

# 내부에서 연결 테스트
curl -m 5 http://alli-api:8080/health     # 허용된 경우 200
curl -m 5 http://alli-db:27017            # 차단된 경우 timeout

# nc로 포트 연결 테스트
nc -zv alli-api 8080   # 성공
nc -zv alli-db 27017   # 차단 시 timeout

# 정책 확인
kubectl get networkpolicy -n alli-prod
kubectl describe networkpolicy allow-frontend-to-api -n alli-prod

# Cilium에서 정책 verdict 확인
hubble observe --namespace alli-prod --verdict DROPPED
hubble observe --namespace alli-prod --verdict FORWARDED
```

### NetworkPolicy 디버깅

```bash
# 1. 정책이 올바른 Pod에 적용되는지 확인
kubectl get pods -n alli-prod --show-labels
kubectl get networkpolicy -n alli-prod -o yaml | grep -A5 podSelector

# 2. Cilium endpoint에서 정책 상태 확인
cilium endpoint list -n alli-prod
cilium policy get

# 3. 실시간 트래픽 모니터링
hubble observe --pod alli-api-xxxxx --type drop
hubble observe --pod alli-api-xxxxx --type trace

# 4. DNS가 차단되어 있지 않은지 확인 (가장 흔한 실수)
kubectl exec -it client -n alli-prod -- nslookup alli-api
# 실패 시 → allow-dns 정책 누락

# 5. 특정 정책 테스트 (dry-run)
kubectl apply -f policy.yaml --dry-run=server
```

---

## 면접 Q&A

### Q: NetworkPolicy의 기본 동작과 "default deny"를 설명해주세요.
**30초 답변**:
NetworkPolicy가 없으면 모든 Pod 간 통신이 허용됩니다. 특정 Pod에 NetworkPolicy가 적용되면 해당 policyType(Ingress/Egress)에 대해 자동으로 default deny가 되고, 명시적으로 허용된 트래픽만 통과합니다. 보안 모범 사례는 Namespace에 "default deny all" 정책을 먼저 적용한 후, 필요한 통신만 개별 정책으로 허용하는 것입니다.

**2분 답변**:
Kubernetes NetworkPolicy는 additive(추가적)하게 동작합니다. deny 규칙은 없고 allow 규칙만 존재하며, 여러 정책이 OR(합집합)로 결합됩니다.

기본 동작 흐름은 이렇습니다. Pod에 매칭되는 NetworkPolicy가 없으면 모든 트래픽이 허용됩니다. NetworkPolicy가 하나라도 적용되면 해당 policyType에 대해 암묵적으로 deny가 됩니다. 예를 들어 Ingress 정책만 적용하면 Ingress는 정책에 따라 제어되고, Egress는 여전히 모두 허용입니다.

"default deny all" 패턴은 빈 podSelector({})와 빈 ingress/egress 규칙으로 구현합니다. 이렇게 하면 Namespace의 모든 Pod에 대해 모든 Ingress/Egress가 차단됩니다. 그 후 서비스 간 필요한 통신만 개별 NetworkPolicy로 허용합니다.

반드시 DNS(kube-dns, port 53) Egress를 허용해야 합니다. 이를 빠뜨리면 Service 이름 해석이 안 되어 모든 Service 간 통신이 실패합니다.

**경험 연결**:
폐쇄망 환경에서 방화벽을 "default deny + whitelist" 방식으로 운영한 경험이 있습니다. NetworkPolicy도 동일한 원칙이며, 다만 Pod label 기반이라 IP를 몰라도 된다는 점이 더 유연합니다.

**주의**:
NetworkPolicy는 CNI 플러그인이 구현한다. Flannel은 NetworkPolicy를 지원하지 않으므로 정책을 작성해도 적용되지 않는다. Calico, Cilium, Weave가 지원한다.

### Q: NetworkPolicy에서 from의 AND/OR 조건을 설명해주세요.
**30초 답변**:
from 배열에서 각 항목(-)은 OR 조건이고, 같은 항목 내의 podSelector와 namespaceSelector는 AND 조건입니다. 즉 `- podSelector: A`와 `- namespaceSelector: B`는 "A 또는 B"이고, `- podSelector: A`에 `namespaceSelector: B`를 같이 쓰면 "A 그리고 B"입니다.

**2분 답변**:
이 구분은 YAML의 들여쓰기 차이로 결정되며, 실수하기 쉬운 부분입니다.

OR 조건 예시: from 아래에 두 개의 대시(-) 항목으로 작성합니다.
```
from:
  - podSelector: {matchLabels: {app: frontend}}
  - namespaceSelector: {matchLabels: {env: staging}}
```
이는 "frontend Pod" 또는 "staging namespace의 모든 Pod"에서 오는 트래픽을 허용합니다.

AND 조건 예시: 하나의 대시(-) 항목 안에 두 selector를 함께 작성합니다.
```
from:
  - podSelector: {matchLabels: {app: frontend}}
    namespaceSelector: {matchLabels: {env: staging}}
```
이는 "staging namespace에 있으면서 app=frontend인 Pod"만 허용합니다.

프로덕션에서 이 차이를 잘못 이해하면 의도치 않게 전체 namespace의 트래픽을 허용하는 보안 사고가 발생할 수 있습니다. 항상 정책 적용 후 실제 테스트를 수행해야 합니다.

**경험 연결**:
방화벽 ACL을 작성할 때도 AND/OR 조건의 혼동으로 잘못된 규칙이 배포된 경험이 있습니다. NetworkPolicy도 동일한 주의가 필요하며, CI/CD 파이프라인에서 정책을 검증하는 도구(Kyverno, OPA)를 사용하는 것이 좋습니다.

**주의**:
namespaceSelector를 빈 값({})으로 설정하면 모든 Namespace가 매칭된다. 이를 podSelector와 OR로 조합하면 클러스터 전체의 모든 Pod에서 접근 가능해지므로 주의해야 한다.

### Q: Cilium의 L7 NetworkPolicy는 어떤 상황에서 사용하나요?
**30초 답변**:
Kubernetes 표준 NetworkPolicy는 L3/L4(IP, Port)만 제어합니다. Cilium의 L7 정책은 HTTP method/path, gRPC method, DNS query까지 제어하여 "POST /api/chat만 허용, DELETE는 차단" 같은 세밀한 정책이 가능합니다. API Gateway가 없는 환경이나 Zero Trust 네트워크에서 특히 유용합니다.

**2분 답변**:
L7 NetworkPolicy가 필요한 세 가지 시나리오가 있습니다.

첫째, 세밀한 API 접근 제어입니다. "frontend에서 backend의 GET /api/v1/users와 POST /api/v1/chat만 허용하고, DELETE /api/v1/users는 차단"하는 정책을 네트워크 수준에서 강제합니다. 애플리케이션 코드의 인증/인가와 별개로 네트워크 계층의 방어선을 추가합니다.

둘째, FQDN 기반 Egress 제어입니다. AI 엔진이 외부 API(OpenAI, Anthropic)를 호출할 때 `*.openai.com`만 허용하는 정책을 DNS 수준에서 적용합니다. IP 기반 정책은 CDN/SaaS의 동적 IP에 대응할 수 없지만 FQDN 정책은 DNS 조회 결과를 실시간으로 반영합니다.

셋째, Kafka topic 수준 정책입니다. 특정 서비스가 특정 Kafka topic만 produce/consume할 수 있도록 L7 정책으로 제어합니다.

Cilium은 eBPF로 패킷을 파싱하여 L7 프로토콜을 인식하므로, 사이드카 프록시(Envoy) 없이도 L7 정책을 적용할 수 있습니다. 다만 L7 파싱은 L3/L4보다 CPU 비용이 높으므로 필요한 서비스에만 선택적으로 적용해야 합니다.

**경험 연결**:
웹 방화벽(WAF)에서 HTTP 메서드/경로 기반 규칙을 설정한 경험이 있습니다. Cilium L7 정책은 WAF의 기능을 Kubernetes 네이티브로 제공하여 별도 WAF 인프라 없이도 API 수준의 접근 제어가 가능합니다.

**주의**:
L7 정책 사용 시 Cilium이 Envoy proxy를 투명하게 주입할 수 있다. 이 경우 추가적인 latency와 리소스 소모가 발생하므로 성능 테스트가 필요하다.

---

## Allganize 맥락

- **멀티테넌시 격리**: 고객별 Namespace를 분리하고 default-deny 정책 적용. 고객 A의 Pod가 고객 B의 데이터에 접근 불가하도록 NetworkPolicy로 강제
- **AI 엔진 Egress 제어**: 추론 엔진이 외부 LLM API만 호출하도록 Cilium FQDN 정책 적용. 데이터 유출 방지(DLP) 효과
- **PCI-DSS/SOC2 컴플라이언스**: NetworkPolicy로 네트워크 세그멘테이션을 증명. 감사 시 정책 YAML과 Hubble 로그를 증거로 제출
- **마이크로서비스 간 최소 권한**: API → 추론엔진 → 벡터DB → MongoDB 각 경로에 필요한 포트만 허용. 횡방향 이동(lateral movement) 방지
- **CI/CD 정책 검증**: GitOps로 NetworkPolicy를 관리하고, OPA/Kyverno로 배포 전 정책 검증. "모든 Namespace에 default-deny가 있는가" 같은 가드레일 설정

---
**핵심 키워드**: `NetworkPolicy` `default-deny` `Ingress-rule` `Egress-rule` `podSelector` `namespaceSelector` `CiliumNetworkPolicy` `L7-policy` `FQDN` `Zero-Trust`
