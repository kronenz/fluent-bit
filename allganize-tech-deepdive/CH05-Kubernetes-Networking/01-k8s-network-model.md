# Kubernetes 네트워크 모델 (Network Model)

> **TL;DR**: Kubernetes는 모든 Pod에 고유 IP를 부여하고, NAT 없이 Pod 간 직접 통신을 보장하는 flat network 모델을 사용한다. Pod-to-Pod, Pod-to-Service, External-to-Service 세 가지 통신 경로가 핵심이며, 이 모델을 구현하는 것이 CNI 플러그인의 역할이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### Kubernetes 네트워크의 4가지 근본 요구사항

Kubernetes 공식 문서에서 정의하는 네트워크 모델의 필수 조건:

1. **모든 Pod는 NAT 없이 다른 모든 Pod와 통신**할 수 있어야 한다
2. **모든 Node의 에이전트(kubelet 등)는 해당 Node의 모든 Pod와 통신**할 수 있어야 한다
3. **Host network를 사용하는 Pod는 NAT 없이 다른 모든 Pod와 통신**할 수 있어야 한다
4. **각 Pod는 자신의 IP를 다른 Pod가 보는 IP와 동일하게 인식**한다 (no source NAT for intra-cluster)

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌──────────── Node A ────────────┐  ┌──── Node B ────────┐│
│  │  ┌─────────┐   ┌─────────┐    │  │  ┌─────────┐       ││
│  │  │ Pod A-1 │   │ Pod A-2 │    │  │  │ Pod B-1 │       ││
│  │  │10.244.1 │   │10.244.1 │    │  │  │10.244.2 │       ││
│  │  │   .10   │   │   .11   │    │  │  │   .20   │       ││
│  │  └────┬────┘   └────┬────┘    │  │  └────┬────┘       ││
│  │       │              │         │  │       │             ││
│  │  ─────┴──────────────┴─────    │  │  ─────┴──────────  ││
│  │       veth pairs → cbr0       │  │     cbr0            ││
│  │           10.244.1.0/24        │  │   10.244.2.0/24     ││
│  └────────────┬───────────────────┘  └───────┬─────────────┘│
│               │      Overlay / Routing       │              │
│               └──────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### 통신 경로 1: Pod-to-Pod (같은 Node)

같은 Node의 Pod끼리는 Linux bridge(cbr0)를 통해 직접 L2 통신한다.

```
Pod A-1 (10.244.1.10)
  │
  └─ veth pair ─→ cbr0 (bridge) ─→ veth pair ─┐
                                                │
                                    Pod A-2 (10.244.1.11)
```

- Pod의 네트워크 namespace에 `eth0`가 생성되고, Node namespace의 `vethXXX`와 pair
- `cbr0`(또는 `cni0`)에 veth가 연결되어 같은 서브넷 내 ARP 기반 통신

### 통신 경로 2: Pod-to-Pod (다른 Node)

다른 Node의 Pod 간 통신은 CNI 플러그인의 구현에 따라 다르다:

| 방식 | 예시 CNI | 메커니즘 |
|------|---------|---------|
| **Overlay (VXLAN)** | Flannel, Calico(VXLAN mode) | L2 frame을 UDP로 캡슐화하여 Node 간 전달 |
| **BGP Routing** | Calico(BGP mode) | 각 Node가 BGP peer로 Pod CIDR 경로 광고 |
| **eBPF Direct** | Cilium | eBPF 프로그램이 커널 수준에서 패킷 라우팅 |
| **AWS VPC CNI** | aws-vpc-cni | Pod에 VPC ENI의 실제 IP 할당 (native routing) |

```
Pod A-1 (Node A)                                    Pod B-1 (Node B)
  │                                                      ▲
  ▼                                                      │
eth0 → veth → cbr0 → Node A routing table               │
                         │                               │
                    ┌────▼────┐                    ┌─────┴────┐
                    │ VXLAN   │  ══UDP tunnel══►   │  VXLAN   │
                    │ (vtep)  │   Port 4789        │  (vtep)  │
                    └─────────┘                    └──────────┘
                                                         │
                                              cbr0 → veth → eth0
```

### 통신 경로 3: Pod-to-Service

Service는 kube-proxy가 iptables/IPVS 규칙으로 구현하는 가상 IP(ClusterIP)이다.

```
Pod A-1 → dst: 10.96.0.100:80 (Service ClusterIP)
    │
    ▼ iptables DNAT (kube-proxy가 설정)
    │
    dst 변환: 10.244.2.20:8080 (Backend Pod IP)
    │
    ▼ Pod-to-Pod 라우팅 (위의 경로 사용)
    │
Pod B-1 (실제 백엔드)
```

**kube-proxy 모드 비교**:

| 모드 | 작동 방식 | 장단점 |
|------|----------|--------|
| **iptables** (기본) | iptables 규칙으로 DNAT | 안정적이나 규칙 수 증가 시 성능 저하 (O(n)) |
| **IPVS** | Linux IPVS(L4 LB)로 분산 | 해시 테이블 기반 O(1) 조회, 다양한 LB 알고리즘 |
| **eBPF (kube-proxy 대체)** | Cilium이 eBPF로 직접 처리 | 가장 높은 성능, iptables 체인 완전 제거 |

### 통신 경로 4: External-to-Service

외부 트래픽이 클러스터 내부 Pod에 도달하는 경로:

```
Internet Client
    │
    ▼
┌─────────────────────┐
│   Cloud Load Balancer│  ← Service type: LoadBalancer
│   (AWS ALB/NLB)     │
└─────────┬───────────┘
          │
          ▼
    NodePort (30000-32767)
          │
          ▼ kube-proxy (iptables/IPVS)
          │
    ClusterIP → Pod (실제 백엔드)
```

### IP 주소 할당 체계

```
Cluster CIDR:     10.244.0.0/16    ← --cluster-cidr (kube-controller-manager)
  Node A subnet:  10.244.1.0/24    ← --node-cidr-mask-size (기본 /24)
  Node B subnet:  10.244.2.0/24
  Node C subnet:  10.244.3.0/24

Service CIDR:     10.96.0.0/12     ← --service-cluster-ip-range (kube-apiserver)
  kubernetes:     10.96.0.1
  kube-dns:       10.96.0.10
```

---

## 실전 예시

### Pod 네트워크 확인

```bash
# Pod IP 확인
kubectl get pods -o wide

# Pod 내부에서 네트워크 인터페이스 확인
kubectl exec -it debug-pod -- ip addr show
kubectl exec -it debug-pod -- ip route

# Node에서 veth pair 확인
ip link show type veth

# cbr0/cni0 브리지 확인
brctl show
# 또는
ip link show type bridge

# iptables 규칙 확인 (Service DNAT 규칙)
iptables -t nat -L KUBE-SERVICES -n | head -20

# IPVS 모드일 때 확인
ipvsadm -Ln
```

### Pod 간 통신 테스트

```bash
# 디버그 Pod 생성
kubectl run nettest --image=nicolaka/netshoot --rm -it -- bash

# 다른 Pod로 ping
ping 10.244.2.20

# DNS 해석 + HTTP 테스트
curl http://my-service.default.svc.cluster.local:80

# traceroute로 경로 확인 (overlay vs direct routing 구분)
traceroute 10.244.2.20

# tcpdump으로 패킷 캡처 (Node에서)
tcpdump -i any -nn port 4789   # VXLAN encap 확인
tcpdump -i cbr0 -nn icmp       # bridge 통과 ICMP 확인
```

### CIDR 할당 확인

```bash
# 클러스터 전체 CIDR 확인
kubectl cluster-info dump | grep -m 1 cluster-cidr

# 각 Node에 할당된 Pod CIDR 확인
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.podCIDR}{"\n"}{end}'

# Service CIDR 확인
kubectl get svc kubernetes -o jsonpath='{.spec.clusterIP}'
```

---

## 면접 Q&A

### Q: Kubernetes 네트워크 모델의 핵심 원칙을 설명해주세요.
**30초 답변**:
Kubernetes는 모든 Pod에 고유 IP를 부여하고, NAT 없이 Pod 간 직접 통신을 보장하는 flat network 모델을 채택합니다. 이 모델은 CNI 플러그인이 overlay(VXLAN), BGP routing, 또는 eBPF 등의 방식으로 구현하며, kube-proxy가 Service IP를 실제 Pod IP로 변환하는 역할을 담당합니다.

**2분 답변**:
Kubernetes 네트워크 모델은 4가지 기본 요구사항을 정의합니다. 첫째, 모든 Pod는 NAT 없이 다른 모든 Pod와 통신 가능해야 합니다. 둘째, Node의 에이전트도 해당 Node의 모든 Pod와 통신 가능해야 합니다. 셋째, hostNetwork Pod도 다른 Pod와 NAT 없이 통신해야 합니다. 넷째, Pod는 자신이 인식하는 IP가 다른 Pod가 보는 IP와 동일해야 합니다.

실제 구현에서 같은 Node의 Pod 간 통신은 Linux bridge(cbr0)를 통한 L2 통신으로 이루어지고, 다른 Node 간은 CNI 플러그인에 따라 VXLAN overlay, BGP routing, 또는 eBPF direct routing 등으로 구현됩니다. Service 통신은 kube-proxy가 iptables 또는 IPVS 규칙으로 ClusterIP를 실제 Pod IP로 DNAT하는 방식입니다.

클러스터 전체에는 Pod CIDR(예: 10.244.0.0/16)이 할당되고, 각 Node에 서브넷(예: /24)이 분배됩니다. Service에는 별도의 CIDR(예: 10.96.0.0/12)이 사용됩니다.

**경험 연결**:
폐쇄망 환경에서 VLAN 세그멘테이션과 라우팅을 직접 설계한 경험이 있는데, Kubernetes의 flat network 모델은 물리 네트워크의 L2/L3 개념을 가상화한 것이라 이해하기 쉬웠습니다. 온프레미스에서 BGP로 Pod CIDR을 물리 라우터에 광고하는 Calico BGP 설정도 기존 네트워크 경험을 그대로 활용할 수 있었습니다.

**주의**:
"Pod IP는 ephemeral하므로 Service IP를 사용해야 한다"는 점을 반드시 언급할 것. Pod가 재시작되면 IP가 변경되므로 직접 IP를 하드코딩하면 안 된다.

### Q: kube-proxy의 iptables 모드와 IPVS 모드의 차이점은?
**30초 답변**:
iptables 모드는 각 Service/Endpoint마다 iptables 규칙을 생성하여 DNAT로 트래픽을 분산합니다. IPVS 모드는 Linux 커널의 L4 로드밸런서를 사용하여 해시 테이블 기반으로 O(1) 조회가 가능하고, round-robin, least-connection 등 다양한 분산 알고리즘을 지원합니다.

**2분 답변**:
iptables 모드는 Kubernetes의 기본 kube-proxy 모드로, 각 Service에 대해 KUBE-SERVICES 체인에 규칙을 추가하고, Endpoint마다 KUBE-SEP 체인으로 DNAT합니다. 규칙은 probability 기반으로 분산되어 random 방식의 로드밸런싱이 됩니다. 문제는 Service가 수천 개가 되면 iptables 규칙이 수만 개로 늘어나 규칙 순차 매칭으로 인한 레이턴시가 발생한다는 점입니다.

IPVS 모드는 Linux 커널의 netfilter 위에 구축된 L4 로드밸런서입니다. 해시 테이블 기반이므로 Service 수에 관계없이 O(1) 성능을 보이며, rr(round-robin), lc(least-connection), sh(source-hash) 등 다양한 알고리즘을 선택할 수 있습니다. 대규모 클러스터(1000+ Service)에서는 IPVS 모드가 권장됩니다.

추가로 Cilium의 eBPF 기반 kube-proxy 대체도 있는데, 이는 iptables/IPVS를 완전히 제거하고 eBPF 프로그램이 커널 수준에서 직접 패킷을 조작하여 가장 높은 성능을 제공합니다.

**경험 연결**:
온프레미스에서 L4 로드밸런서(F5, HAProxy)를 운영한 경험이 있는데, IPVS의 LB 알고리즘 개념이 동일합니다. 특히 least-connection 알고리즘은 AI 추론 서비스처럼 요청 처리 시간이 불균일한 워크로드에 적합한 선택입니다.

**주의**:
IPVS 모드를 사용하려면 Node에 `ipvsadm`, `ip_vs`, `ip_vs_rr` 등의 커널 모듈이 로드되어 있어야 한다. 클라우드 매니지드 K8s에서는 기본값이 iptables인 경우가 많으므로 확인이 필요하다.

### Q: Pod에서 외부 인터넷으로 나가는 트래픽(Egress)은 어떻게 처리되나요?
**30초 답변**:
Pod의 outbound 트래픽은 Node의 네트워크 namespace를 통해 나가며, 이때 SNAT(Source NAT)이 적용되어 Pod IP가 Node IP로 변환됩니다. 클라우드 환경에서는 Node의 ENI/NIC를 통해 VPC 라우팅을 거쳐 Internet Gateway로 나갑니다.

**2분 답변**:
Pod의 Egress 트래픽 경로는 다음과 같습니다. Pod(10.244.1.10) -> veth -> cbr0 -> Node routing table -> iptables POSTROUTING SNAT -> Node eth0(192.168.1.100) -> 외부 네트워크. iptables의 MASQUERADE 규칙이 Pod IP를 Node IP로 변환하는데, 이는 외부에서 Pod CIDR을 알 수 없기 때문입니다.

AWS EKS의 경우 VPC CNI를 사용하면 Pod에 VPC 서브넷의 실제 IP가 할당되므로 SNAT 없이도 외부 통신이 가능합니다. 하지만 보안 관점에서 NAT Gateway를 통해 Egress IP를 고정하는 것이 일반적입니다. Azure AKS에서도 유사하게 VNET 통합과 NAT Gateway를 조합합니다.

Egress 제어가 필요한 경우 NetworkPolicy로 특정 CIDR만 허용하거나, Istio/Cilium의 Egress Gateway를 사용하여 외부 트래픽을 중앙 집중 관리할 수 있습니다.

**경험 연결**:
폐쇄망 환경에서는 Egress가 엄격히 제한되었기 때문에 proxy 서버를 통한 외부 접근만 허용했습니다. Kubernetes에서도 NetworkPolicy와 Egress Gateway를 조합하면 유사한 수준의 제어가 가능하며, AI 서비스에서 외부 API(OpenAI 등) 호출 시 Egress IP를 고정하는 것이 허용 목록(whitelist) 관리에 유리합니다.

**주의**:
AWS VPC CNI 사용 시 Pod IP가 VPC IP를 소모하므로 서브넷 크기를 충분히 확보해야 한다. /24 서브넷(254개 IP)은 Pod 수가 많은 Node에서 빠르게 소진될 수 있다.

---

## Allganize 맥락

- **AWS EKS + VPC CNI**: Allganize의 Alli 서비스는 EKS에서 운영되며, VPC CNI를 사용할 가능성이 높다. Pod에 VPC IP가 직접 할당되므로 Security Group을 Pod 단위로 적용 가능 (Security Group for Pods)
- **Azure AKS + Azure CNI**: Azure 환경에서도 유사하게 VNET 통합으로 Pod가 실제 Azure IP를 받을 수 있다
- **AI 추론 서비스 네트워크**: LLM 추론 서비스는 대용량 payload(수 MB)를 주고받으므로 MTU 설정과 네트워크 성능이 중요. VXLAN overlay는 50바이트의 오버헤드를 추가하므로 MTU를 1450으로 조정하거나, native routing을 사용하는 것이 유리
- **멀티테넌시 격리**: 고객별 AI 워크로드를 네트워크 수준에서 격리해야 하므로 NetworkPolicy가 필수. Namespace별 default-deny 정책 + 필요한 통신만 허용하는 whitelist 방식 권장

---
**핵심 키워드**: `flat-network` `CNI` `kube-proxy` `iptables` `IPVS` `Pod-CIDR` `Service-CIDR` `VXLAN` `SNAT`
