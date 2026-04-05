# Ingress & Gateway API

> **TL;DR**: Ingress는 HTTP/HTTPS 트래픽을 호스트/경로 기반으로 내부 Service에 라우팅하는 L7 리소스이다. Nginx Ingress Controller가 가장 널리 사용되며, TLS termination과 path-based routing이 핵심 기능이다. Gateway API는 Ingress의 한계를 극복한 차세대 표준으로, 역할 분리와 확장성이 크게 개선되었다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Ingress란?

Ingress는 클러스터 외부의 HTTP(S) 트래픽을 내부 Service로 라우팅하는 규칙을 정의하는 API 리소스이다. Ingress 자체는 규칙일 뿐이고, 실제 트래픽 처리는 **Ingress Controller**가 담당한다.

```
Internet
    │
    ▼
┌─────────────────────────┐
│  Cloud Load Balancer     │  ← Service type: LoadBalancer (1개)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────────────────────────┐
│         Ingress Controller (Nginx Pod)       │
│                                              │
│  ┌─ Ingress Rules ─────────────────────┐    │
│  │ api.alli.ai    → alli-api-svc:80    │    │
│  │ app.alli.ai    → alli-web-svc:80    │    │
│  │ api.alli.ai/v2 → alli-api-v2:80     │    │
│  └─────────────────────────────────────┘    │
└──────┬──────────┬──────────┬────────────────┘
       │          │          │
       ▼          ▼          ▼
  alli-api    alli-web    alli-api-v2
   Service     Service     Service
```

### Ingress 리소스 정의

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"    # LLM 요청 payload 크기
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"  # AI 추론 긴 응답 대기
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.alli.ai
        - app.alli.ai
      secretName: alli-tls-secret
  rules:
    - host: api.alli.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: alli-api-svc
                port:
                  number: 80
          - path: /v2
            pathType: Prefix
            backend:
              service:
                name: alli-api-v2-svc
                port:
                  number: 80
    - host: app.alli.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: alli-web-svc
                port:
                  number: 80
```

### pathType 종류

| pathType | 매칭 방식 | 예시 |
|----------|----------|------|
| **Exact** | 정확한 경로만 매칭 | `/api` → `/api` (O), `/api/users` (X) |
| **Prefix** | 경로 접두사 매칭 (/ 구분) | `/api` → `/api` (O), `/api/users` (O), `/apiv2` (X) |
| **ImplementationSpecific** | Controller 구현에 따라 다름 | Nginx regex 등 |

### 주요 Ingress Controller 비교

| 항목 | Nginx Ingress | Traefik | AWS ALB Ingress | Istio Gateway |
|------|--------------|---------|-----------------|---------------|
| **레이어** | L7 | L7 | L7 (AWS native) | L4/L7 |
| **설정 방식** | annotations | CRD (IngressRoute) | annotations | VirtualService CRD |
| **자동 TLS** | cert-manager 연동 | 내장 Let's Encrypt | ACM 인증서 | cert-manager 연동 |
| **성능** | 높음 (C기반 nginx) | 중간 (Go) | 높음 (AWS managed) | 높음 (Envoy) |
| **장점** | 검증된 안정성, 풍부한 커뮤니티 | 동적 설정, 미들웨어 | AWS 네이티브 통합 | 풀 서비스 메시 |
| **단점** | reload 필요 시 순간 끊김 | 대규모에서 메모리 | AWS 전용 | 복잡한 러닝커브 |

### TLS Termination

```
Client ──HTTPS──► Ingress Controller ──HTTP──► Backend Pod
                  (TLS 종료 지점)

또는

Client ──HTTPS──► Ingress Controller ──HTTPS──► Backend Pod
                  (TLS passthrough)
```

**cert-manager를 이용한 자동 인증서 관리**:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v2.api.letsencrypt.org/directory
    email: devops@allganize.ai
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: nginx
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
    - hosts:
        - api.alli.ai
      secretName: alli-tls-auto    # cert-manager가 자동 생성/갱신
```

### Gateway API (차세대 표준)

Gateway API는 Ingress의 한계를 극복하기 위해 SIG-Network에서 개발한 새로운 표준이다.

```
Ingress의 한계:
- annotation 기반 Controller별 설정 → 이식성 없음
- 역할 분리 불가 (인프라팀 vs 앱팀)
- TCP/UDP 지원 불가 (HTTP만)
- Header 기반 라우팅 등 고급 기능 부족

Gateway API의 개선:
- 역할 기반 리소스 분리
- typed 설정 (annotation이 아닌 구조화된 API)
- HTTP, TCP, UDP, gRPC, TLS 지원
- 확장 가능한 Policy Attachment
```

**Gateway API 리소스 계층**:

```
┌──────────────────────────────────────────────┐
│  GatewayClass (인프라 관리자)                   │
│  └─ 어떤 Controller가 처리할지 정의              │
│     예: Nginx, Cilium, Istio                   │
├──────────────────────────────────────────────┤
│  Gateway (클러스터 운영자)                      │
│  └─ 리스너(포트, 프로토콜, TLS) 정의            │
│     예: HTTPS :443, HTTP :80                  │
├──────────────────────────────────────────────┤
│  HTTPRoute / TCPRoute / GRPCRoute (앱 개발자)  │
│  └─ 라우팅 규칙 정의                            │
│     예: host=api.alli.ai → alli-api-svc       │
└──────────────────────────────────────────────┘
```

```yaml
# 1. GatewayClass - 인프라팀이 관리
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: cilium
spec:
  controllerName: io.cilium/gateway-controller
---
# 2. Gateway - 플랫폼팀이 관리
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: alli-gateway
  namespace: infra
spec:
  gatewayClassName: cilium
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - name: alli-tls-secret
      allowedRoutes:
        namespaces:
          from: Selector
          selector:
            matchLabels:
              gateway-access: "true"
---
# 3. HTTPRoute - 앱팀이 관리
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: alli-api-route
  namespace: alli-prod
spec:
  parentRefs:
    - name: alli-gateway
      namespace: infra
  hostnames:
    - api.alli.ai
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /v2
          headers:
            - name: X-API-Version
              value: "2"
      backendRefs:
        - name: alli-api-v2-svc
          port: 80
          weight: 90
        - name: alli-api-v3-svc
          port: 80
          weight: 10     # 카나리 배포: 10% 트래픽
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: alli-api-svc
          port: 80
```

---

## 실전 예시

### Nginx Ingress Controller 설치 및 확인

```bash
# Helm으로 Nginx Ingress Controller 설치
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=LoadBalancer \
  --set controller.metrics.enabled=true

# 설치 확인
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx

# Ingress 리소스 확인
kubectl get ingress -A
kubectl describe ingress alli-ingress

# TLS 인증서 확인
kubectl get secret alli-tls-secret -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout

# Nginx 설정 확인 (디버깅)
kubectl exec -it -n ingress-nginx deploy/ingress-nginx-controller -- cat /etc/nginx/nginx.conf | grep "server_name"

# 접근 테스트
curl -H "Host: api.alli.ai" https://<LB-IP>/ -v
```

### Gateway API 설치 및 사용

```bash
# Gateway API CRD 설치
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml

# GatewayClass 확인
kubectl get gatewayclass

# Gateway 상태 확인
kubectl get gateway -A
kubectl describe gateway alli-gateway -n infra

# HTTPRoute 확인
kubectl get httproute -A
```

---

## 면접 Q&A

### Q: Ingress Controller는 어떻게 동작하나요?
**30초 답변**:
Ingress Controller는 Ingress 리소스의 변경을 watch하여, 라우팅 규칙을 reverse proxy(Nginx, Envoy 등) 설정으로 변환합니다. 자체적으로 LoadBalancer Service를 통해 외부 트래픽을 수신하고, host/path 기반으로 적절한 backend Service로 L7 라우팅합니다.

**2분 답변**:
Ingress Controller의 동작 과정은 다음과 같습니다. 먼저 Kubernetes API Server를 watch하여 Ingress, Service, Endpoints, Secret(TLS 인증서) 리소스의 변경을 감지합니다. 변경이 발생하면 Ingress 규칙을 파싱하여 reverse proxy의 설정 파일을 생성합니다. Nginx의 경우 `nginx.conf`를 갱신하고 reload합니다.

Ingress Controller 자체는 Deployment로 배포된 Pod이며, LoadBalancer 타입 Service를 통해 외부 트래픽을 수신합니다. 즉, 외부 LB 1개로 여러 서비스를 host/path 기반으로 라우팅할 수 있어 비용 효율적입니다.

주요 기능으로는 TLS termination, path-based routing, host-based routing, rate limiting, authentication, CORS 설정 등이 있습니다. 이러한 설정은 Ingress annotations이나 ConfigMap으로 제어합니다.

**경험 연결**:
온프레미스에서 Nginx를 reverse proxy로 운영하며 vhost 설정을 수동으로 관리한 경험이 있습니다. Ingress Controller는 이 과정을 Kubernetes 리소스로 선언적 관리할 수 있게 해주어, GitOps와 결합하면 설정 변경이 자동화됩니다.

**주의**:
Nginx Ingress Controller에는 두 가지 구현이 있다. kubernetes/ingress-nginx(커뮤니티)와 nginxinc/kubernetes-ingress(NGINX Inc). 설정 방식과 annotation이 다르므로 주의해야 한다.

### Q: Gateway API가 Ingress를 대체하는 이유는?
**30초 답변**:
Ingress는 annotation 기반의 Controller별 설정이 이식성이 없고, HTTP만 지원하며, 역할 분리가 불가능합니다. Gateway API는 GatewayClass/Gateway/Route로 리소스를 분리하여 인프라팀과 앱팀의 역할을 명확히 하고, HTTP/TCP/gRPC를 표준으로 지원하며, weight 기반 트래픽 분할 등 고급 기능을 제공합니다.

**2분 답변**:
Ingress의 핵심 한계는 세 가지입니다. 첫째, Controller별 annotation이 달라 이식성이 없습니다. Nginx의 `nginx.ingress.kubernetes.io/rewrite-target`은 Traefik에서 작동하지 않습니다. 둘째, 인프라 관리자와 앱 개발자의 관심사가 하나의 리소스에 혼재됩니다. 셋째, HTTP만 지원하여 gRPC, TCP, UDP 트래픽은 별도 CRD가 필요합니다.

Gateway API는 이를 세 계층으로 분리합니다. GatewayClass는 인프라 관리자가 Controller 종류를 정의하고, Gateway는 클러스터 운영자가 리스너(포트, TLS)를 설정하며, HTTPRoute/GRPCRoute/TCPRoute는 앱 개발자가 라우팅 규칙을 정의합니다.

추가로 weight 기반 트래픽 분할(카나리 배포), 헤더 기반 라우팅, 요청 미러링 등이 표준 API로 제공되어 annotation 없이 구현 가능합니다. Cilium, Istio, Nginx 모두 Gateway API를 지원하기 시작했습니다.

**경험 연결**:
여러 팀이 하나의 Nginx 설정 파일을 동시에 수정하며 충돌이 발생한 경험이 있습니다. Gateway API의 역할 분리 모델은 이 문제를 구조적으로 해결하여, DevOps 팀이 Gateway를 관리하고 앱 팀이 Route만 관리하는 명확한 책임 경계를 제공합니다.

**주의**:
Gateway API는 아직 모든 Controller에서 완전히 구현되지 않은 실험적(Experimental) 기능이 있다. 프로덕션 도입 전 사용할 Controller의 지원 범위를 확인해야 한다.

### Q: TLS termination을 Ingress에서 하는 것과 Pod에서 하는 것의 차이는?
**30초 답변**:
Ingress에서 TLS termination하면 인증서를 중앙 관리하고 backend Pod는 HTTP로 통신하여 운영이 단순합니다. Pod에서 하면(TLS passthrough) end-to-end 암호화가 보장되지만 인증서 관리가 분산되고, Ingress의 L7 라우팅 기능을 사용할 수 없습니다.

**2분 답변**:
Ingress TLS termination은 Ingress Controller에서 TLS를 복호화하고, backend Pod에는 평문 HTTP로 전달합니다. 장점은 인증서를 Secret 하나로 중앙 관리할 수 있고, cert-manager로 자동 갱신이 가능하며, Ingress에서 host/path 기반 L7 라우팅이 가능하다는 것입니다. 대부분의 웹 서비스에 적합합니다.

TLS passthrough는 Ingress Controller가 TLS를 복호화하지 않고 TCP 수준에서 SNI(Server Name Indication)만 보고 라우팅합니다. backend Pod가 직접 TLS를 처리하므로 end-to-end 암호화가 보장됩니다. 금융, 의료 등 규제 환경에서 요구될 수 있습니다. 단점은 Ingress가 평문 HTTP 헤더를 볼 수 없으므로 path 기반 라우팅이 불가능합니다.

하이브리드 방식으로 Ingress에서 TLS를 종료하고, Ingress와 backend 사이를 mTLS(mutual TLS)로 재암호화하는 방법도 있습니다. Service Mesh(Istio)가 이 패턴을 자동으로 처리합니다.

**경험 연결**:
폐쇄망 환경에서 내부 인증서를 직접 관리하며 각 서버에 배포했는데, cert-manager + Ingress 조합으로 인증서 생명주기가 완전 자동화되어 운영 부담이 크게 줄어듭니다.

**주의**:
TLS termination 시 Ingress Controller와 backend 사이 통신이 평문이므로, 클러스터 내부 네트워크가 신뢰할 수 없는 환경이면 backend re-encryption 또는 mTLS를 고려해야 한다.

---

## Allganize 맥락

- **Nginx Ingress + NLB**: Allganize의 프로덕션 환경에서는 AWS NLB → Nginx Ingress Controller 조합이 유력. NLB에서 TLS termination하거나 Ingress에서 cert-manager로 관리
- **AI API의 긴 응답 시간**: LLM 추론은 수초~수십초가 걸리므로 `proxy-read-timeout`, `proxy-send-timeout`을 충분히 늘려야 한다. Streaming 응답의 경우 `proxy-buffering: "off"` 설정 필요
- **대용량 payload**: 문서 업로드, 임베딩 요청 등은 수 MB~수십 MB 가능. `proxy-body-size` 조정 필수
- **Gateway API 도입 가능성**: Cilium을 CNI로 사용한다면 Cilium Gateway API Controller를 활용하여 Ingress Controller 없이 Gateway API를 직접 구현 가능. 인프라 단순화 효과
- **멀티테넌트 라우팅**: 고객별 서브도메인(`customer-a.alli.ai`) 또는 path(`/tenant/customer-a`) 기반 라우팅으로 멀티테넌시 구현

---
**핵심 키워드**: `Ingress` `IngressController` `Nginx` `Traefik` `GatewayAPI` `HTTPRoute` `TLS-termination` `cert-manager` `pathType`
