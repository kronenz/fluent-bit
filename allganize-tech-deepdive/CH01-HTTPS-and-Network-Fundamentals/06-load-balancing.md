# 06. 로드 밸런싱 — L4 vs L7, ALB/NLB, Kubernetes Service 유형

> **TL;DR**
> - **L4 로드 밸런싱**은 TCP/UDP 레벨(IP+포트)에서 동작하여 빠르고 프로토콜 무관하며, **L7 로드 밸런싱**은 HTTP 헤더/경로/쿠키 기반으로 세밀한 라우팅이 가능하다.
> - AWS에서 **ALB**는 L7(HTTP/HTTPS), **NLB**는 L4(TCP/UDP)이며, 용도에 따라 선택한다.
> - Kubernetes에서는 **ClusterIP, NodePort, LoadBalancer, ExternalName** 4가지 Service 유형과 **Ingress**로 트래픽을 관리한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### L4 vs L7 로드 밸런싱

```
OSI 7계층 모델에서의 위치:

Layer 7 (Application)  ← L7 LB: HTTP 헤더, URL 경로, 쿠키 분석
Layer 6 (Presentation)
Layer 5 (Session)
Layer 4 (Transport)    ← L4 LB: TCP/UDP 포트, IP 주소 기반
Layer 3 (Network)
Layer 2 (Data Link)
Layer 1 (Physical)
```

```
L4 로드 밸런싱:
┌──────────────┐      TCP SYN      ┌──────────────┐
│   Client     │──────────────────→│  L4 LB       │
│              │                   │              │
│              │                   │ IP + Port만  │
│              │                   │ 확인하여 분배 │
│              │                   │              │
│              │                   │ 패킷 내용을   │
│              │                   │ 읽지 않음     │
└──────────────┘                   └──────┬───────┘
                                     │    │    │
                               ┌─────┘    │    └─────┐
                               ▼          ▼          ▼
                          Backend A   Backend B  Backend C

특징:
- TCP/UDP 연결을 통째로 하나의 백엔드에 전달
- 패킷 내용(HTTP 헤더 등)을 파싱하지 않음 → 매우 빠름
- TLS 종단(termination) 하지 않음 → 백엔드까지 암호화 유지
- DSR(Direct Server Return) 지원 가능


L7 로드 밸런싱:
┌──────────────┐    HTTPS         ┌──────────────────────────┐
│   Client     │─────────────────→│  L7 LB (TLS Termination) │
│              │                  │                          │
│              │                  │  URL: /api/v1/chat       │
│              │                  │  Host: api.allganize.ai  │
│              │                  │  Cookie: session=abc     │
│              │                  │                          │
│              │                  │  → 내용 분석 후 라우팅    │
└──────────────┘                  └─────────┬────────────────┘
                                       │    │    │
                            ┌──────────┘    │    └──────────┐
                            ▼               ▼               ▼
                      /api/* → API      /ws/* → WS     /static/* →
                      Backend           Backend         CDN/Static

특징:
- HTTP 헤더, URL, 쿠키 등을 파싱하여 지능적 라우팅
- TLS 종단 가능 → 인증서 관리 집중화
- HTTP/2 → HTTP/1.1 변환, 압축, 캐싱 가능
- 요청 단위 로드 밸런싱 (연결이 아닌 요청)
- WebSocket, gRPC 인지 가능
```

### L4 vs L7 비교 표

| 항목 | L4 로드 밸런싱 | L7 로드 밸런싱 |
|------|---------------|---------------|
| 동작 계층 | Transport (TCP/UDP) | Application (HTTP/HTTPS) |
| 분배 기준 | IP + Port | URL, Host, Header, Cookie |
| TLS 종단 | 불가 (패스스루) | 가능 |
| 프로토콜 인식 | 없음 | HTTP, gRPC, WebSocket |
| 성능 | 매우 높음 | 상대적으로 낮음 |
| 세션 유지 | Source IP 기반 | Cookie 기반 (정확) |
| Health Check | TCP/ICMP | HTTP 상태 코드 |
| 대표 서비스 | AWS NLB, HAProxy L4 | AWS ALB, nginx, Envoy |
| 적합한 경우 | 고성능, 비HTTP, DB | HTTP API, 마이크로서비스 |

### 로드 밸런싱 알고리즘

```
Round Robin (라운드 로빈):
  요청 1 → Backend A
  요청 2 → Backend B
  요청 3 → Backend C
  요청 4 → Backend A  (순환)
  * 가장 단순, 백엔드 성능이 동일할 때 적합

Weighted Round Robin (가중 라운드 로빈):
  Backend A (weight=5) ████████████████████
  Backend B (weight=3) ████████████
  Backend C (weight=2) ████████
  * 서버 스펙이 다를 때 적합

Least Connections (최소 연결):
  Backend A: 현재 연결 15개  ←── 다음 요청은 여기로
  Backend B: 현재 연결 23개
  Backend C: 현재 연결 18개
  * 요청 처리 시간이 다양할 때 적합

IP Hash (소스 IP 해싱):
  hash(client_ip) % backend_count → 항상 같은 백엔드
  * 세션 고정(Sticky Session) 필요 시

Least Response Time (최소 응답 시간):
  Backend A: 평균 응답 15ms  ←── 다음 요청은 여기로
  Backend B: 평균 응답 45ms
  Backend C: 평균 응답 30ms
  * 성능 기반 동적 분배
```

### AWS ALB vs NLB

```
ALB (Application Load Balancer) — L7:
┌──────────────────────────────────────────────┐
│                    ALB                        │
│                                              │
│  Listener: HTTPS:443                         │
│    ├── Rule: Host=api.allganize.ai           │
│    │   └── Target Group: alli-api (HTTP:8080)│
│    ├── Rule: Host=dash.allganize.ai          │
│    │   └── Target Group: dashboard (HTTP:3000)│
│    └── Default: Fixed Response 404           │
│                                              │
│  기능: 경로 기반 라우팅, Host 기반 라우팅,    │
│        가중치 기반 라우팅, WAF 통합,          │
│        인증(Cognito/OIDC), HTTP/2 지원       │
└──────────────────────────────────────────────┘

NLB (Network Load Balancer) — L4:
┌──────────────────────────────────────────────┐
│                    NLB                        │
│                                              │
│  Listener: TCP:443                           │
│    └── Target Group: alli-api (TCP:8080)     │
│                                              │
│  Listener: TCP:6379                          │
│    └── Target Group: redis (TCP:6379)        │
│                                              │
│  기능: 고정 IP/Elastic IP, 초당 수백만 요청,  │
│        TLS 패스스루, TCP/UDP 지원,            │
│        소스 IP 보존, PrivateLink 지원         │
└──────────────────────────────────────────────┘
```

| 항목 | ALB | NLB |
|------|-----|-----|
| 계층 | L7 (HTTP/HTTPS) | L4 (TCP/UDP/TLS) |
| 라우팅 | URL, Host, Header, Query | Port |
| 고정 IP | 불가 (DNS 이름만) | **지원** (Elastic IP 가능) |
| TLS 종단 | ALB에서 종단 | 패스스루 또는 NLB에서 종단 |
| 성능 | 수만 RPS | **수백만 RPS**, 극저지연 |
| 소스 IP | X-Forwarded-For 헤더 | **원본 소스 IP 보존** |
| WebSocket | 지원 | 지원 (TCP) |
| gRPC | 지원 (HTTP/2) | 지원 (TCP 패스스루) |
| 비용 | LCU 기반 | NLCU 기반 (보통 더 저렴) |
| 적합한 경우 | HTTP API, 웹서비스 | 고성능, 비HTTP, 게임 서버 |

### Kubernetes Service 유형

```
1. ClusterIP (기본값) — 내부 전용
┌────── Cluster ──────────────────────────┐
│                                          │
│  Pod A ──→ alli-api:80 ──→ Pod B (8080) │
│            (ClusterIP)       Pod C (8080)│
│            10.96.x.x                     │
│                                          │
│  * 클러스터 내부에서만 접근 가능           │
│  * kube-proxy가 iptables/IPVS로 분배     │
└──────────────────────────────────────────┘

2. NodePort — 노드 포트 개방
┌────── Cluster ──────────────────────────┐
│  Node1:30080 ─┐                          │
│  Node2:30080 ─┼→ alli-api ─→ Pod B/C    │
│  Node3:30080 ─┘  ClusterIP               │
│                                          │
│  * 모든 노드의 30000~32767 포트 개방      │
│  * 외부에서 <NodeIP>:<NodePort>로 접근    │
│  * 프로덕션에서는 직접 사용하지 않음       │
└──────────────────────────────────────────┘

3. LoadBalancer — 클라우드 LB 연동
┌────────────────────────────────────────────────┐
│  Client ──→ Cloud LB ──→ NodePort ──→ Service  │
│             (ALB/NLB)     (자동생성)    ──→ Pod │
│                                                │
│  * 클라우드 프로바이더의 LB를 자동 생성          │
│  * AWS: aws-load-balancer-controller 사용       │
│  * 서비스당 하나의 LB → 비용 이슈               │
└────────────────────────────────────────────────┘

4. ExternalName — CNAME 매핑
┌────── Cluster ──────────────────────────┐
│                                          │
│  Pod A ──→ ext-db.default.svc ──→ CNAME │
│            (ExternalName)                │
│            ──→ mydb.xxx.rds.amazonaws.com│
│                                          │
│  * 외부 서비스를 클러스터 DNS로 매핑      │
│  * 프록시 없이 CNAME만 반환               │
└──────────────────────────────────────────┘
```

### Ingress — L7 라우팅 통합

```
┌────────────────────────────────────────────────────────┐
│                     Ingress Controller                  │
│                  (nginx / ALB / Traefik)                │
│                                                        │
│  Rule 1: host=api.allganize.ai, path=/v1/*             │
│          → Service: alli-api-v1:8080                   │
│                                                        │
│  Rule 2: host=api.allganize.ai, path=/v2/*             │
│          → Service: alli-api-v2:8080                   │
│                                                        │
│  Rule 3: host=dashboard.allganize.ai                   │
│          → Service: dashboard:3000                     │
│                                                        │
│  Default: 404                                          │
│                                                        │
│  * 여러 서비스를 하나의 LB 뒤에서 라우팅               │
│  * TLS 종단, 리다이렉트, Rate Limiting 등              │
└────────────────────────────────────────────────────────┘
```

---

## 실전 예시

### AWS ALB Ingress 설정

```yaml
# AWS Load Balancer Controller + ALB Ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-ingress
  namespace: production
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip          # Pod IP 직접 (성능 향상)
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:...
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
    alb.ingress.kubernetes.io/healthcheck-path: /health
    alb.ingress.kubernetes.io/healthcheck-interval-seconds: "15"
    alb.ingress.kubernetes.io/actions.ssl-redirect: |
      {"Type": "redirect", "RedirectConfig": {"Protocol": "HTTPS", "Port": "443", "StatusCode": "HTTP_301"}}
spec:
  rules:
  - host: api.allganize.ai
    http:
      paths:
      - path: /api/v1
        pathType: Prefix
        backend:
          service:
            name: alli-api-v1
            port:
              number: 8080
      - path: /api/v2
        pathType: Prefix
        backend:
          service:
            name: alli-api-v2
            port:
              number: 8080
  - host: dashboard.allganize.ai
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: dashboard
            port:
              number: 3000
```

### NLB Service 설정 (gRPC/고성능)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alli-grpc
  namespace: production
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: external
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
    service.beta.kubernetes.io/aws-load-balancer-scheme: internal
    # TLS를 NLB에서 종단하지 않고 패스스루
    service.beta.kubernetes.io/aws-load-balancer-backend-protocol: tcp
spec:
  type: LoadBalancer
  selector:
    app: alli-grpc-server
  ports:
  - port: 443
    targetPort: 8443
    protocol: TCP
```

### nginx Ingress Controller 고급 설정

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-api
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"       # LLM 추론 대기
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"          # 스트리밍 응답
    nginx.ingress.kubernetes.io/upstream-hash-by: "$request_uri" # 일관된 해싱
    nginx.ingress.kubernetes.io/limit-rps: "100"                 # Rate Limiting
    nginx.ingress.kubernetes.io/enable-cors: "true"
    # 카나리 배포
    # nginx.ingress.kubernetes.io/canary: "true"
    # nginx.ingress.kubernetes.io/canary-weight: "10"
spec:
  tls:
  - hosts:
    - api.allganize.ai
    secretName: alli-tls
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

### kube-proxy 모드 확인 및 IPVS

```bash
# kube-proxy 모드 확인
kubectl get configmap kube-proxy -n kube-system -o yaml | grep mode

# iptables 규칙 확인 (iptables 모드)
sudo iptables -t nat -L KUBE-SERVICES | head -20

# IPVS 규칙 확인 (IPVS 모드)
sudo ipvsadm -Ln

# IPVS가 iptables보다 좋은 이유:
# - O(1) 복잡도 (iptables는 O(n))
# - 대규모 Service에서 성능 우위
# - 더 많은 LB 알고리즘 지원 (rr, lc, dh, sh, sed, nq)
```

---

## 면접 Q&A

### Q: L4와 L7 로드 밸런싱의 차이를 설명해주세요.

**30초 답변**:
**L4**는 TCP/UDP의 IP+포트만 보고 라우팅하여 빠르고 프로토콜 무관합니다. **L7**은 HTTP 헤더, URL 경로, 쿠키 등을 분석하여 세밀한 라우팅이 가능하지만 상대적으로 느립니다. AWS에서는 NLB(L4)와 ALB(L7)가 대표적입니다.

**2분 답변**:
L4 로드 밸런싱은 전송 계층에서 동작합니다. TCP SYN 패킷의 소스/목적지 IP와 포트만 확인하여 백엔드를 선택합니다. 패킷 페이로드를 전혀 파싱하지 않으므로 **극히 빠르고**, HTTP뿐 아니라 데이터베이스, 게임 서버 등 **모든 TCP/UDP 프로토콜**에 사용할 수 있습니다. NLB의 경우 초당 수백만 요청을 처리하며, 고정 IP와 소스 IP 보존이 가능합니다.

L7 로드 밸런싱은 애플리케이션 계층에서 동작합니다. HTTP 요청을 **완전히 파싱**하여 URL 경로(/api/v1 → 서비스 A, /api/v2 → 서비스 B), Host 헤더(api.allganize.ai → 서비스 A, dashboard.allganize.ai → 서비스 B), 쿠키, 헤더 등을 기반으로 라우팅합니다. TLS 종단, HTTP/2 변환, 응답 압축, WAF 통합 같은 부가 기능도 제공합니다.

선택 기준:
- **HTTP API, 웹서비스**: L7 (ALB) — 경로/호스트 기반 라우팅, TLS 종단
- **gRPC end-to-end**: L4 (NLB) 패스스루 또는 L7 (ALB HTTP/2)
- **데이터베이스, 비HTTP**: L4 (NLB)
- **극저지연, 초고성능**: L4 (NLB)

**경험 연결**:
"온프레미스 환경에서 HAProxy를 L4와 L7 모드 모두 운영한 경험이 있습니다. 내부 DB 클러스터에는 L4 모드로 TCP 프록시를 구성하고, 웹 서비스에는 L7 모드로 URL 기반 라우팅을 적용했습니다."

**주의**:
- ALB는 고정 IP가 없어 방화벽 화이트리스트가 필요한 경우 NLB 앞에 ALB를 두거나 Global Accelerator 사용
- NLB는 소스 IP를 보존하지만, ALB는 X-Forwarded-For 헤더로 전달 → 애플리케이션에서 처리 필요

### Q: Kubernetes Service 유형별 차이와 사용 시나리오를 설명해주세요.

**30초 답변**:
**ClusterIP**는 내부 전용, **NodePort**는 노드 포트를 열어 외부 접근, **LoadBalancer**는 클라우드 LB를 자동 생성, **ExternalName**은 외부 서비스를 CNAME으로 매핑합니다. 프로덕션에서는 보통 LoadBalancer + Ingress 조합을 사용합니다.

**2분 답변**:
Kubernetes Service 유형은 4가지입니다.

**ClusterIP**(기본값): 클러스터 내부 가상 IP를 할당합니다. 마이크로서비스 간 통신에 사용하며, 외부에서는 접근 불가합니다. kube-proxy가 iptables 또는 IPVS 규칙으로 Pod에 트래픽을 분배합니다.

**NodePort**: ClusterIP에 추가로 모든 노드의 특정 포트(30000~32767)를 개방합니다. 테스트용으로는 쓸 수 있지만, 프로덕션에서는 보안과 포트 관리 문제로 직접 사용하지 않습니다.

**LoadBalancer**: 클라우드 프로바이더의 로드 밸런서를 자동으로 프로비저닝합니다. AWS에서는 aws-load-balancer-controller가 ALB/NLB를 생성합니다. 단점은 Service마다 LB가 생성되어 비용이 증가하는 것입니다.

**Ingress**: Service 유형은 아니지만, 여러 Service를 하나의 LB 뒤에서 L7 라우팅하여 비용을 절약합니다. 호스트/경로 기반 라우팅, TLS 종단, 카나리 배포 등을 지원합니다.

프로덕션 아키텍처: Ingress(ALB) → Service(ClusterIP) → Pod

**경험 연결**:
"온프레미스에서는 LoadBalancer 유형을 사용할 수 없어 MetalLB를 도입하거나, NodePort + 외부 HAProxy 조합을 사용한 경험이 있습니다. 클라우드 환경에서는 ALB Ingress Controller가 이를 자동화해줍니다."

**주의**:
- Service type LoadBalancer를 남용하면 LB 비용이 급증 → Ingress로 통합
- IPVS 모드의 kube-proxy는 대규모 클러스터에서 iptables보다 성능이 우수 (O(1) vs O(n))

### Q: ALB의 target-type ip와 instance의 차이는 무엇인가요?

**30초 답변**:
**instance 모드**는 ALB가 NodePort를 통해 노드에 트래픽을 보내고, kube-proxy가 Pod로 전달합니다. **ip 모드**는 ALB가 **Pod IP에 직접** 트래픽을 전달하여 한 단계를 건너뜁니다. ip 모드가 latency가 낮고 소스 IP 보존도 쉽습니다.

**2분 답변**:
instance 모드(기본값)의 트래픽 경로:
Client → ALB → Node(NodePort) → kube-proxy → Pod

이 경우 ALB는 EC2 인스턴스의 NodePort로 트래픽을 보내고, kube-proxy가 iptables 규칙에 따라 적절한 Pod로 전달합니다. 이때 트래픽이 다른 노드의 Pod로 전달될 수도 있어(SNAT 발생) **추가 홉과 latency**가 발생합니다.

ip 모드의 트래픽 경로:
Client → ALB → Pod (직접)

ALB가 VPC CNI를 통해 Pod의 IP를 직접 Target으로 등록합니다. kube-proxy를 거치지 않으므로 **홉이 줄어들고 latency가 감소**합니다. 또한 ALB에서 직접 Pod의 health check를 수행할 수 있습니다.

ip 모드의 전제조건:
- AWS VPC CNI 사용 (Pod가 VPC 서브넷의 IP를 받아야 함)
- aws-load-balancer-controller v2 이상

**경험 연결**:
"Kubernetes 클러스터에서 ALB를 instance 모드로 사용할 때 간헐적인 5xx 에러가 발생했는데, 원인이 NodePort를 통한 추가 홉에서 타임아웃이었습니다. ip 모드로 전환 후 해결되었습니다."

**주의**:
- ip 모드에서는 Pod IP가 직접 노출되므로 **Security Group을 Pod 레벨**에서 관리 가능
- Fargate 환경에서는 ip 모드만 지원

---

## Allganize 맥락

### Alli 서비스와의 연결

- **API 라우팅**: ALB Ingress로 api.allganize.ai의 경로별 라우팅 (/v1, /v2, /health 등)
- **LLM 추론 서비스**: LLM 추론은 응답이 느릴 수 있으므로 proxy-read-timeout을 충분히 설정
- **스트리밍 응답**: SSE/WebSocket 기반 토큰 스트리밍 시 proxy-buffering off 필수
- **멀티클라우드 LB**: AWS ALB + Azure Application Gateway 조합, 각각의 Ingress Controller 운영
- **비용 최적화**: 서비스마다 LoadBalancer 생성 대신 Ingress로 통합하여 LB 비용 절감
- **gRPC 통신**: 내부 마이크로서비스 간 gRPC 사용 시 NLB 패스스루 또는 ALB HTTP/2 선택

### JD 연결 포인트

```
JD: "안정적 서비스 운영"   → LB 설정 최적화, Health Check 설정
JD: "AWS/Azure"          → ALB/NLB, Azure App GW 운영
JD: "Kubernetes"         → Service/Ingress 설계, kube-proxy 모드
JD: "성능 분석"           → L4/L7 선택, target-type 최적화
```

---

**핵심 키워드**: `L4-LB` `L7-LB` `ALB` `NLB` `ClusterIP` `NodePort` `LoadBalancer` `Ingress` `kube-proxy` `IPVS`
