# CNI 플러그인 비교 (CNI Plugins)

> **TL;DR**: CNI(Container Network Interface)는 Kubernetes Pod에 네트워크를 할당하는 표준 인터페이스다. Calico(BGP/eBPF), Cilium(eBPF 네이티브), Flannel(간단한 overlay), Weave(멀티캐스트 지원) 등이 있으며, 프로덕션 환경에서는 NetworkPolicy 지원, 성능, 운영 복잡도를 기준으로 선택한다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 20min

---

## 핵심 개념

### CNI란?

CNI(Container Network Interface)는 CNCF 프로젝트로, 컨테이너 런타임이 네트워크 플러그인을 호출하는 표준 인터페이스를 정의한다.

```
kubelet
  │
  ▼ CRI (containerd/CRI-O)
  │
  ▼ 컨테이너 생성 → network namespace 생성
  │
  ▼ CNI 호출: /opt/cni/bin/<plugin> ADD
  │
  ▼ CNI 플러그인이 수행하는 작업:
     1) veth pair 생성 (Pod ns ↔ Host ns)
     2) Pod에 IP 할당 (IPAM)
     3) 라우팅 규칙 추가
     4) (선택) overlay 터널 설정
```

**CNI 설정 파일 위치**: `/etc/cni/net.d/`
**CNI 바이너리 위치**: `/opt/cni/bin/`

```json
// /etc/cni/net.d/10-calico.conflist 예시
{
  "name": "k8s-pod-network",
  "cniVersion": "0.3.1",
  "plugins": [
    {
      "type": "calico",
      "datastore_type": "kubernetes",
      "ipam": {
        "type": "calico-ipam"
      }
    },
    {
      "type": "bandwidth",
      "capabilities": {"bandwidth": true}
    }
  ]
}
```

### CNI 플러그인 상세 비교

#### 1. Calico

```
┌─────────────────────────────────────────────┐
│  Calico Architecture                         │
│                                              │
│  ┌────────┐  ┌────────┐  ┌──────────────┐  │
│  │ Felix  │  │ BIRD   │  │ Typha        │  │
│  │(Agent) │  │(BGP)   │  │(Fan-out      │  │
│  │iptables│  │route   │  │ proxy)       │  │
│  │/eBPF   │  │exchange│  │              │  │
│  └────┬───┘  └───┬────┘  └──────────────┘  │
│       │          │                           │
│  ─────┴──────────┴───── Node ──────          │
│                                              │
│  Datastore: Kubernetes API (etcd) 또는       │
│             dedicated etcd                   │
└─────────────────────────────────────────────┘
```

- **네트워킹 모드**: BGP (기본), VXLAN, IP-in-IP, eBPF (v3.13+)
- **NetworkPolicy**: 완전 지원 + Calico 확장 정책 (GlobalNetworkPolicy)
- **IPAM**: Calico IPAM (IP 풀 관리, BGP 경로 광고)
- **장점**: 검증된 안정성, 풍부한 기능, 대규모 클러스터 실적
- **단점**: BGP 모드는 네트워크 인프라 이해 필요, 컴포넌트가 많아 복잡

#### 2. Cilium

```
┌─────────────────────────────────────────────┐
│  Cilium Architecture                         │
│                                              │
│  ┌──────────────────────┐  ┌─────────────┐  │
│  │ Cilium Agent         │  │ Hubble      │  │
│  │  ┌──────────────┐   │  │ (Network    │  │
│  │  │ eBPF Programs │   │  │  Observ.)   │  │
│  │  │ - XDP        │   │  │             │  │
│  │  │ - TC         │   │  └─────────────┘  │
│  │  │ - Socket LB  │   │                    │
│  │  └──────────────┘   │                    │
│  └──────────────────────┘                    │
│                                              │
│  Datastore: Kubernetes CRD 또는 etcd         │
└─────────────────────────────────────────────┘
```

- **네트워킹 모드**: eBPF direct routing, VXLAN, GENEVE
- **NetworkPolicy**: K8s 표준 + Cilium 확장 (L7, FQDN, Identity)
- **IPAM**: Cilium IPAM, Cluster-scope, AWS ENI, Azure IPAM
- **장점**: 최고 성능(eBPF), kube-proxy 대체, L7 가시성(Hubble), 활발한 개발
- **단점**: 커널 4.19+ 필요, 러닝커브, 비교적 최근 프로젝트

#### 3. Flannel

```
┌─────────────────────────────────────────────┐
│  Flannel Architecture                        │
│                                              │
│  ┌────────────────┐                          │
│  │ flanneld       │  ← 각 Node에서 실행      │
│  │                │                          │
│  │ Backend:       │                          │
│  │  - VXLAN (기본)│                          │
│  │  - host-gw     │                          │
│  │  - UDP (레거시)│                          │
│  └────────────────┘                          │
│                                              │
│  Datastore: Kubernetes API (subnet lease)    │
└─────────────────────────────────────────────┘
```

- **네트워킹 모드**: VXLAN (기본), host-gw (같은 L2 네트워크)
- **NetworkPolicy**: **미지원** (별도 Calico 추가 필요 = Canal)
- **장점**: 가장 간단한 설치/운영, 학습 용도에 적합
- **단점**: NetworkPolicy 미지원, 기능이 제한적, overlay 성능 오버헤드

#### 4. Weave Net

```
┌─────────────────────────────────────────────┐
│  Weave Net Architecture                      │
│                                              │
│  ┌────────────────┐                          │
│  │ weave router   │  ← mesh overlay          │
│  │                │                          │
│  │ - Fast DP      │  (VXLAN or sleeve)       │
│  │ - Encryption   │  (IPsec 지원)            │
│  │ - DNS (WeaveDNS)│                         │
│  └────────────────┘                          │
│                                              │
│  Datastore: 자체 분산 (gossip protocol)       │
└─────────────────────────────────────────────┘
```

- **네트워킹 모드**: VXLAN (Fast Datapath), sleeve (fallback)
- **NetworkPolicy**: 지원
- **장점**: 설치 간단, 멀티캐스트 지원, 내장 암호화
- **단점**: 성능이 다른 CNI 대비 낮음, 개발 활동 감소 추세

### 종합 비교표

| 기준 | Calico | Cilium | Flannel | Weave |
|------|--------|--------|---------|-------|
| **NetworkPolicy** | 완전 지원 + 확장 | 완전 지원 + L7 확장 | 미지원 | 지원 |
| **성능** | 높음 (BGP/eBPF) | 최고 (eBPF) | 중간 (VXLAN) | 낮음-중간 |
| **운영 복잡도** | 중-높 | 중 | 낮 | 낮 |
| **kube-proxy 대체** | 가능 (eBPF 모드) | 가능 | 불가 | 불가 |
| **Observability** | 기본 | Hubble (우수) | 없음 | 기본 |
| **최소 커널** | 3.10 | 4.19 (5.4+ 권장) | 3.10 | 3.8 |
| **Datastore** | K8s API/etcd | K8s CRD/etcd | K8s API | 자체 gossip |
| **클라우드 통합** | AWS/Azure/GCP | AWS ENI/Azure | 없음 | 없음 |
| **CNCF 상태** | Graduated | Graduated | Sandbox | 없음 |
| **프로덕션 사례** | 대규모 검증 | 급속 성장 | 소규모/학습 | 감소 추세 |

### 클라우드 매니지드 K8s의 기본 CNI

| 클라우드 | 기본 CNI | 특징 |
|---------|---------|------|
| **AWS EKS** | VPC CNI (aws-vpc-cni) | Pod에 VPC IP 직접 할당, Security Group for Pods |
| **Azure AKS** | Azure CNI (기본) / kubenet | VNET IP 할당 또는 overlay |
| **GCP GKE** | GKE CNI (Dataplane V2 = Cilium) | Cilium 기반 eBPF |
| **온프레미스** | 직접 선택 (Calico/Cilium 주로) | BGP 또는 overlay |

---

## 실전 예시

### CNI 확인 및 진단

```bash
# 현재 사용 중인 CNI 확인
ls /etc/cni/net.d/
cat /etc/cni/net.d/10-calico.conflist

# CNI 바이너리 확인
ls /opt/cni/bin/

# CNI Pod 상태 확인
kubectl get pods -n kube-system -l k8s-app=calico-node
kubectl get pods -n kube-system -l k8s-app=cilium

# Calico 상태 확인
kubectl exec -n kube-system calico-node-xxxxx -- calico-node -bird-ready
calicoctl node status

# Cilium 상태 확인
cilium status
cilium connectivity test

# Node 라우팅 테이블 확인
ip route | grep -E "calico|cilium|cni|flannel"
```

### CNI 성능 테스트

```bash
# iperf3으로 Pod 간 대역폭 측정
kubectl run iperf-server --image=networkstatic/iperf3 -- -s
kubectl run iperf-client --image=networkstatic/iperf3 --rm -it -- -c <server-pod-ip> -t 30

# 같은 Node vs 다른 Node 비교
# Overlay(VXLAN) vs Direct routing 성능 차이 확인

# netperf로 latency 측정
kubectl run netperf-server --image=networkstatic/netperf -- netserver
kubectl run netperf-client --image=networkstatic/netperf --rm -it -- \
  netperf -H <server-pod-ip> -t TCP_RR -l 30
```

---

## 면접 Q&A

### Q: CNI 플러그인을 선택하는 기준은 무엇인가요?
**30초 답변**:
세 가지 기준으로 선택합니다. 첫째, NetworkPolicy 지원 여부(보안 필수), 둘째 성능 요구사항(eBPF 기반 Cilium이 최고), 셋째 운영 복잡도와 팀 역량입니다. 프로덕션 환경에서는 Calico 또는 Cilium이 권장되고, 학습/테스트에는 Flannel이 적합합니다.

**2분 답변**:
CNI 선택 시 고려할 핵심 기준은 다섯 가지입니다.

첫째, NetworkPolicy 지원입니다. 멀티테넌트 환경에서 네트워크 격리는 필수이므로 Flannel처럼 미지원하는 CNI는 프로덕션에서 부적합합니다.

둘째, 성능입니다. AI 추론 서비스처럼 대용량 데이터를 처리하는 경우 eBPF 기반 CNI(Cilium, Calico eBPF)가 최고 성능을 제공합니다. VXLAN overlay는 약 50바이트 오버헤드와 캡슐화/역캡슐화 CPU 비용이 있습니다.

셋째, 클라우드 통합입니다. AWS EKS에서는 VPC CNI가 기본이고 Pod에 VPC IP를 직접 할당하여 Security Group 등 AWS 네이티브 기능을 활용할 수 있습니다.

넷째, 관측가능성입니다. Cilium의 Hubble은 eBPF 기반으로 네트워크 플로우를 실시간 시각화하여 디버깅에 매우 유용합니다.

다섯째, 커뮤니티와 성숙도입니다. Calico와 Cilium 모두 CNCF Graduated 프로젝트로 장기 지원이 보장됩니다.

**경험 연결**:
온프레미스 폐쇄망에서는 VLAN과 정적 라우팅으로 네트워크를 구성했는데, Calico BGP 모드가 이 경험과 가장 유사합니다. 물리 라우터와 BGP peering을 맺어 Pod CIDR을 광고하면 overlay 없이 native 성능을 얻을 수 있습니다.

**주의**:
CNI를 변경하는 것은 클러스터 전체 네트워크를 재구성하는 것이므로 운영 중 변경이 매우 어렵다. 초기 설계 시 신중하게 선택해야 한다.

### Q: Calico와 Cilium의 가장 큰 차이점은?
**30초 답변**:
가장 큰 차이는 데이터플레인입니다. Calico는 전통적으로 iptables 기반이고(eBPF 모드 추가), Cilium은 처음부터 eBPF 네이티브로 설계되었습니다. Cilium은 kube-proxy 완전 대체, L7 정책, Hubble 관측성에서 우위이고, Calico는 BGP 네이티브 라우팅과 대규모 운영 실적에서 우위입니다.

**2분 답변**:
Calico는 2015년부터 시작된 성숙한 프로젝트로, Felix(에이전트)와 BIRD(BGP 데몬)가 핵심입니다. iptables 기반 데이터플레인이 기본이지만 v3.13부터 eBPF 모드를 지원합니다. BGP 네이티브 라우팅이 가장 큰 강점으로, 온프레미스에서 물리 네트워크와 통합할 때 이상적입니다.

Cilium은 2017년부터 eBPF를 핵심 기술로 탄생했습니다. iptables를 전혀 사용하지 않고 eBPF 프로그램으로 모든 네트워킹을 처리합니다. kube-proxy를 완전히 대체할 수 있고, L7 프로토콜(HTTP, gRPC, Kafka)을 인식하는 네트워크 정책이 가능합니다. Hubble을 통한 네트워크 관측성이 뛰어나며, Service Mesh 기능까지 통합되고 있습니다.

선택 기준으로, 온프레미스 BGP 환경이나 iptables 호환이 필요하면 Calico, 최신 eBPF 기능과 관측성이 중요하면 Cilium이 적합합니다. 최근 추세는 Cilium으로의 이동이 뚜렷합니다(GKE Dataplane V2가 Cilium 기반).

**경험 연결**:
물리 네트워크 장비를 관리한 경험이 있어 BGP 개념에 익숙합니다. Calico의 BGP 모드가 직관적으로 이해되었고, Cilium은 eBPF라는 새로운 기술이지만 kube-proxy 제거로 인한 성능 개선이 AI 서비스에 매력적입니다.

**주의**:
Cilium은 Linux 커널 4.19 이상, 권장 5.4 이상이 필요하다. 오래된 OS를 사용하는 환경에서는 커널 업그레이드가 선행되어야 한다.

### Q: AWS EKS의 VPC CNI는 다른 CNI와 어떻게 다른가요?
**30초 답변**:
VPC CNI는 Pod에 VPC 서브넷의 실제 IP를 할당합니다. overlay가 없으므로 VPC 라우팅을 직접 사용하여 성능이 좋고, AWS Security Group을 Pod 단위로 적용할 수 있습니다. 단, Pod IP가 VPC IP를 소모하므로 IP 주소 관리가 중요합니다.

**2분 답변**:
일반 CNI(Calico, Cilium)는 Pod에 클러스터 내부 CIDR(예: 10.244.0.0/16)의 가상 IP를 할당하고 overlay로 통신합니다. AWS VPC CNI는 완전히 다른 접근으로, 각 Node의 ENI(Elastic Network Interface)에 secondary IP를 추가하고 이를 Pod에 직접 할당합니다.

장점으로는 VPC 네이티브 라우팅으로 overlay 오버헤드가 없고, Pod에 Security Group을 직접 적용 가능하며, VPC Flow Log로 Pod 트래픽을 추적할 수 있습니다.

단점으로는 ENI당 IP 수가 인스턴스 타입에 따라 제한되어 Node당 최대 Pod 수가 제한됩니다. 예를 들어 m5.large는 ENI 3개 x IP 10개 = 29개 Pod가 최대입니다. 이를 완화하기 위해 prefix delegation 모드(/28 prefix 할당)를 사용하면 Pod 수를 크게 늘릴 수 있습니다.

대규모 클러스터에서는 VPC 서브넷의 IP 소진이 문제가 될 수 있으므로 서브넷 크기를 /18 이상으로 충분히 확보하거나, secondary CIDR을 추가해야 합니다.

**경험 연결**:
온프레미스에서 서버마다 IP를 수동 할당하고 DHCP로 관리한 경험이 있습니다. VPC CNI의 IP 관리도 유사한 개념이며, 서브넷 설계와 IP 용량 계획이 중요하다는 점에서 기존 네트워크 설계 경험이 직접 적용됩니다.

**주의**:
VPC CNI와 Calico/Cilium은 동시에 사용할 수 있다. VPC CNI로 네트워킹을 담당하고, Calico/Cilium은 NetworkPolicy만 담당하는 하이브리드 구성이 EKS에서 일반적이다.

---

## Allganize 맥락

- **EKS 환경**: VPC CNI가 기본이며, NetworkPolicy를 위해 Calico 또는 Cilium을 추가 설치할 가능성이 높다. EKS는 Calico NetworkPolicy 엔진을 공식 지원
- **Cilium 도입 가능성**: GKE가 Cilium 기반 Dataplane V2를 채택한 것처럼, Allganize도 Cilium으로 kube-proxy 제거 + Hubble 관측성을 확보하는 것이 AI 서비스 운영에 유리
- **AI 추론 성능**: LLM 추론 서비스는 모델 가중치 다운로드(수 GB), 추론 요청/응답(수 KB~수 MB)이 혼재. native routing(VPC CNI 또는 BGP)이 overlay보다 유리
- **IP 관리**: 대규모 AI 워크로드에서 GPU Node의 Pod 수가 많으면 VPC CNI의 IP 소진 문제가 발생할 수 있음. prefix delegation 또는 secondary CIDR 활용 필요

---
**핵심 키워드**: `CNI` `Calico` `Cilium` `Flannel` `Weave` `VPC-CNI` `BGP` `VXLAN` `eBPF` `NetworkPolicy`
