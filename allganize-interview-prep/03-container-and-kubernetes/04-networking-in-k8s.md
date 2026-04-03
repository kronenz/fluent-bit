# 04. 쿠버네티스 네트워킹 (Networking in Kubernetes)

> **TL;DR**
> - K8s 네트워킹의 핵심 원칙: **모든 Pod는 NAT 없이 서로 통신**할 수 있어야 한다.
> - **Service**는 Pod 그룹에 안정적인 엔드포인트를 제공하고, **Ingress**는 외부 HTTP(S) 트래픽을 라우팅한다.
> - **CNI 플러그인**(Calico, Cilium)이 실제 네트워크를 구현하고, **NetworkPolicy**로 트래픽을 제어한다.

---

## 1. K8s 네트워킹 기본 원칙

K8s는 네트워킹에 대해 **세 가지 기본 규칙**을 요구한다.

1. **Pod-to-Pod:** 모든 Pod는 NAT 없이 다른 Pod와 통신 가능
2. **Node-to-Pod:** 모든 노드는 NAT 없이 모든 Pod와 통신 가능
3. **Pod 자기 인식:** Pod가 보는 자신의 IP = 다른 Pod가 보는 해당 Pod의 IP

```
┌────── Node 1 (10.0.1.1) ──────┐    ┌────── Node 2 (10.0.1.2) ──────┐
│ Pod A: 10.244.1.10             │    │ Pod C: 10.244.2.10             │
│ Pod B: 10.244.1.11             │    │ Pod D: 10.244.2.11             │
│                                │    │                                │
│ Pod A → Pod C : 직접 통신 가능  │←→ │                                │
└────────────────────────────────┘    └────────────────────────────────┘
```

---

## 2. Service 유형

Pod는 생성/삭제될 때마다 **IP가 바뀐다**. Service는 Pod 그룹에 **안정적인 접근점**을 제공한다.

### 2-1. ClusterIP (기본값)

**클러스터 내부 전용** 가상 IP를 할당한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend-svc
spec:
  type: ClusterIP              # 기본값, 생략 가능
  selector:
    app: backend
  ports:
  - port: 80                   # Service 포트
    targetPort: 8080            # Pod 포트
    protocol: TCP
```

```bash
# 클러스터 내부에서 접근
curl http://backend-svc.default.svc.cluster.local:80

# 짧은 형식 (같은 namespace)
curl http://backend-svc:80
```

### 2-2. NodePort

**모든 노드의 특정 포트**를 열어 외부에서 접근 가능하게 한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-nodeport
spec:
  type: NodePort
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080            # 30000-32767 범위
```

```bash
# 외부에서 접근
curl http://<node-ip>:30080
```

### 2-3. LoadBalancer

**클라우드 로드밸런서**를 자동 프로비저닝한다. 온프레미스에서는 **MetalLB**를 사용한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-lb
spec:
  type: LoadBalancer
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
```

**온프레미스에서 MetalLB 설정:**

```yaml
# MetalLB L2 모드 설정
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.200-192.168.1.250    # 사용할 IP 대역
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: default
  namespace: metallb-system
spec:
  ipAddressPools:
  - default-pool
```

### 2-4. 서비스 유형 비교

| 유형 | 접근 범위 | 사용 시나리오 |
|------|----------|--------------|
| **ClusterIP** | 클러스터 내부 | 마이크로서비스 간 통신 |
| **NodePort** | 노드 IP + 포트 | 테스트, 간단한 외부 노출 |
| **LoadBalancer** | 외부 LB IP | 프로덕션 외부 서비스 |
| **ExternalName** | DNS CNAME | 외부 서비스 참조 |

---

## 3. Ingress

**HTTP(S) 레벨**에서 외부 트래픽을 여러 Service로 라우팅한다.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-tls-secret
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: backend-svc
            port:
              number: 80
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend-svc
            port:
              number: 80
```

```bash
# TLS Secret 생성 (폐쇄망에서 자체 CA 인증서)
kubectl create secret tls app-tls-secret \
  --cert=tls.crt \
  --key=tls.key

# Ingress Controller 설치 (Nginx)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/baremetal/deploy.yaml

# 폐쇄망: 미리 다운로드한 매니페스트 적용
kubectl apply -f /manifests/ingress-nginx-baremetal.yaml
```

**Ingress Controller 비교:**

| 컨트롤러 | 특징 |
|----------|------|
| **Nginx Ingress** | 가장 보편적, 풍부한 어노테이션 |
| **HAProxy Ingress** | 고성능, TCP/UDP 지원 |
| **Traefik** | 자동 TLS, 동적 설정 |
| **Istio Gateway** | 서비스 메시 통합 |

---

## 4. CNI 플러그인

**CNI (Container Network Interface)**는 Pod 네트워크를 실제로 구현하는 플러그인이다.

### 4-1. Calico

```yaml
# Calico 설치 (온프레미스)
# calico.yaml 다운로드 후 CIDR 수정
# CALICO_IPV4POOL_CIDR을 클러스터 Pod CIDR과 일치시킴

apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  calicoNetwork:
    ipPools:
    - cidr: 10.244.0.0/16
      encapsulation: VXLAN          # 또는 IPIP
      natOutgoing: Enabled
      nodeSelector: all()
```

| 특징 | 설명 |
|------|------|
| **라우팅 모드** | BGP, VXLAN, IPIP |
| **NetworkPolicy** | K8s 표준 + Calico 확장 정책 |
| **성능** | eBPF 모드 지원 |
| **적합 환경** | 온프레미스, BGP 라우터 있는 환경 |

### 4-2. Cilium

```yaml
# Cilium 설치 (Helm)
# helm repo add cilium https://helm.cilium.io/
apiVersion: v1
kind: ConfigMap
metadata:
  name: cilium-config
  namespace: kube-system
data:
  enable-bpf-masquerade: "true"
  kube-proxy-replacement: "true"    # kube-proxy 대체
  enable-hubble: "true"             # 네트워크 관찰성
```

| 특징 | 설명 |
|------|------|
| **기반 기술** | eBPF (커널 레벨 프로그래밍) |
| **kube-proxy 대체** | eBPF로 직접 패킷 처리 |
| **관찰성** | Hubble UI로 트래픽 시각화 |
| **적합 환경** | 대규모 클러스터, L7 정책 필요 시 |

### CNI 선택 가이드

```
온프레미스 + BGP 라우터 있음 → Calico (BGP 모드)
온프레미스 + 심플 구성      → Calico (VXLAN 모드)
대규모 + 고성능 필요        → Cilium (eBPF)
서비스 메시 통합 필요       → Cilium
폐쇄망 + 안정성 우선        → Calico (검증 기간 길고 안정적)
```

---

## 5. kube-proxy 모드

kube-proxy는 **Service의 ClusterIP를 실제 Pod IP로 변환**하는 규칙을 관리한다.

### 5-1. iptables 모드 (기본)

```bash
# iptables 규칙 확인
sudo iptables -t nat -L KUBE-SERVICES -n | head -20

# 특정 서비스의 규칙 추적
sudo iptables -t nat -L KUBE-SVC-XXXXXXX -n
```

- **장점:** 안정적, 대부분의 환경에서 동작
- **단점:** Service 수 증가 시 규칙이 선형 증가 → **O(n) 탐색**, 수천 개 서비스에서 지연 발생

### 5-2. IPVS 모드

```bash
# IPVS 모드로 변경 (kube-proxy ConfigMap)
kubectl edit configmap kube-proxy -n kube-system
# mode: "ipvs"

# IPVS 규칙 확인
sudo ipvsadm -Ln
```

- **장점:** 해시 테이블 기반 **O(1) 탐색**, 로드밸런싱 알고리즘 다양 (rr, lc, sh 등)
- **단점:** ipvsadm, ip_vs 커널 모듈 필요

### 비교

| 항목 | iptables | IPVS |
|------|----------|------|
| **조회 성능** | O(n) | O(1) |
| **서비스 1,000개** | 적합 | 적합 |
| **서비스 10,000개+** | 성능 저하 | 적합 |
| **LB 알고리즘** | 랜덤 | rr, lc, dh, sh 등 |
| **커널 요구** | 기본 | ip_vs 모듈 필요 |

---

## 6. CoreDNS

클러스터 내부 **DNS 서비스**로, Service 이름을 IP로 변환한다.

```
Service DNS 형식:
  <service-name>.<namespace>.svc.cluster.local

Pod DNS 형식 (Headless Service):
  <pod-name>.<service-name>.<namespace>.svc.cluster.local
```

```bash
# DNS 확인 (디버깅 Pod 사용)
kubectl run dnsutils --image=busybox:1.36 --restart=Never -- sleep 3600
kubectl exec dnsutils -- nslookup backend-svc.default.svc.cluster.local
kubectl exec dnsutils -- nslookup kubernetes.default.svc.cluster.local

# CoreDNS 설정 확인
kubectl get configmap coredns -n kube-system -o yaml
```

```yaml
# CoreDNS Corefile 예시 (내부 DNS 포워딩 추가)
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        errors
        health
        ready
        kubernetes cluster.local in-addr.arpa ip6.arpa {
            pods insecure
            fallthrough in-addr.arpa ip6.arpa
        }
        forward . /etc/resolv.conf
        cache 30
        loop
        reload
        loadbalance
    }
    # 폐쇄망 내부 도메인 포워딩
    internal.company.com:53 {
        forward . 10.0.0.53
        cache 60
    }
```

---

## 7. NetworkPolicy

**Pod 간 트래픽을 제어**하는 방화벽 규칙이다. CNI 플러그인이 지원해야 동작한다.

```yaml
# 기본: 모든 인바운드 차단 (Zero Trust)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-ingress
  namespace: production
spec:
  podSelector: {}              # 모든 Pod에 적용
  policyTypes:
  - Ingress
  # ingress 규칙 없음 = 모든 인바운드 차단
---
# 특정 트래픽만 허용
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend                # 대상: backend Pod
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend           # 출발: frontend Pod만
    - namespaceSelector:
        matchLabels:
          env: production         # 같은 환경의 namespace만
    ports:
    - protocol: TCP
      port: 8080
---
# Egress 제어: 외부 나가는 트래픽 제한
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restrict-egress
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: database
    ports:
    - protocol: TCP
      port: 5432
  - to:                          # DNS 허용 (필수)
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
```

**폐쇄망 보안 강화:**
NetworkPolicy로 **마이크로 세그멘테이션(Micro-segmentation)**을 구현하면, 네트워크가 분리된 환경에서도 Pod 레벨의 추가 격리를 제공한다.

---

## 면접 Q&A

### Q1. "ClusterIP, NodePort, LoadBalancer의 차이를 설명해주세요."

> **이렇게 대답한다:**
> "**ClusterIP**는 클러스터 내부에서만 접근 가능한 가상 IP입니다. **NodePort**는 ClusterIP + 모든 노드의 특정 포트(30000-32767)를 열어 외부 접근을 허용합니다. **LoadBalancer**는 NodePort + 클라우드 LB를 자동 프로비저닝합니다. 온프레미스에서는 **MetalLB**로 LoadBalancer 타입을 구현할 수 있습니다. 실무에서는 보통 ClusterIP + Ingress 조합으로 HTTP 서비스를 노출합니다."

### Q2. "kube-proxy의 iptables 모드와 IPVS 모드의 차이는?"

> **이렇게 대답한다:**
> "**iptables 모드**는 Service마다 iptables 규칙을 생성하여 **체인을 순차 탐색(O(n))**합니다. 서비스 수천 개까지는 문제없지만 만 개 이상이면 성능이 저하됩니다. **IPVS 모드**는 해시 테이블 기반으로 **O(1) 조회**가 가능하고 round-robin, least-connection 등 다양한 로드밸런싱 알고리즘을 지원합니다. 대규모 트래픽 환경에서는 IPVS가 적합하며, 더 나아가 Cilium의 **eBPF 기반 kube-proxy 대체**도 고려할 수 있습니다."

### Q3. "NetworkPolicy를 사용해본 경험이 있나요?"

> **이렇게 대답한다:**
> "보안이 중요한 온프레미스 환경에서 **Zero Trust 원칙**으로 기본 모든 트래픽을 차단한 후, 필요한 통신만 명시적으로 허용하는 NetworkPolicy를 적용했습니다. 예를 들어 프론트엔드에서 백엔드로, 백엔드에서 DB로의 통신만 허용하고, **DNS(UDP 53) egress는 반드시 열어야** 한다는 점을 주의했습니다. Calico를 CNI로 사용하면 K8s 기본 NetworkPolicy보다 **더 세밀한 L7 정책**도 적용 가능합니다."

### Q4. "온프레미스에서 LoadBalancer 타입 서비스를 어떻게 구현하나요?"

> **이렇게 대답한다:**
> "클라우드가 아닌 환경에서는 **MetalLB**를 사용합니다. L2 모드는 ARP로 IP를 광고하므로 설정이 간단하고, BGP 모드는 라우터와 BGP 피어링하여 더 안정적입니다. 폐쇄망이라면 L2 모드로 내부 IP 대역을 할당하고, 필요 시 앞단에 **HAProxy나 F5** 같은 하드웨어 로드밸런서를 배치하는 구성도 활용했습니다."

---

`#Service` `#Ingress` `#CNI` `#NetworkPolicy` `#CoreDNS`
