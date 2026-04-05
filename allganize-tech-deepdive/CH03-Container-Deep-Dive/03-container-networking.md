# 컨테이너 네트워킹 (Container Networking)

> **TL;DR**
> - 컨테이너 네트워킹의 핵심은 **veth pair + bridge + NAT**이다. 각 컨테이너는 자체 네트워크 네임스페이스를 가진다.
> - Docker는 **bridge, host, none, overlay** 네트워크 드라이버를 제공하며, K8s에서는 **CNI 플러그인**이 이를 대체한다.
> - 컨테이너 간 통신은 bridge를 통해, 외부 통신은 **iptables NAT(MASQUERADE)**를 통해 이루어진다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### 1. Network Namespace

각 컨테이너는 독립된 **네트워크 네임스페이스**를 가진다. 이 안에서 고유한 네트워크 인터페이스, 라우팅 테이블, iptables 규칙, 소켓을 가진다.

```
┌─── Host Network Namespace ──────────────────────────┐
│  eth0: 192.168.1.100                                │
│  docker0 (bridge): 172.17.0.1                       │
│                                                      │
│  ┌── Container A NS ──┐  ┌── Container B NS ──┐     │
│  │  eth0: 172.17.0.2  │  │  eth0: 172.17.0.3  │     │
│  │  lo: 127.0.0.1     │  │  lo: 127.0.0.1     │     │
│  │  routing table     │  │  routing table     │     │
│  │  iptables rules    │  │  iptables rules    │     │
│  └────────────────────┘  └────────────────────┘     │
└──────────────────────────────────────────────────────┘
```

### 2. veth pair (Virtual Ethernet Pair)

veth pair는 **가상 이더넷 케이블**이다. 한쪽 끝은 컨테이너 네임스페이스의 eth0, 다른 쪽은 호스트의 bridge에 연결된다.

```
Container A                              Host
┌──────────────┐                    ┌──────────────────┐
│  eth0        │ ←── veth pair ──→ │  vethXXX         │
│  172.17.0.2  │                    │  (docker0에 연결) │
└──────────────┘                    └──────────────────┘

Container B                              Host
┌──────────────┐                    ┌──────────────────┐
│  eth0        │ ←── veth pair ──→ │  vethYYY         │
│  172.17.0.3  │                    │  (docker0에 연결) │
└──────────────┘                    └──────────────────┘
```

### 3. Bridge 네트워크

docker0은 **가상 L2 스위치(bridge)**이다. 같은 bridge에 연결된 컨테이너끼리 직접 통신할 수 있다.

```
                     ┌──────────────────────┐
                     │     docker0 bridge   │
                     │     172.17.0.1/16    │
                     └──┬──────────┬────────┘
                        │          │
                   vethXXX     vethYYY
                        │          │
                  ┌─────┴─┐  ┌─────┴─┐
                  │ eth0  │  │ eth0  │
                  │.0.2   │  │.0.3   │
                  │ Cnt A │  │ Cnt B │
                  └───────┘  └───────┘

Container A → Container B (같은 bridge):
  172.17.0.2 → docker0 bridge → 172.17.0.3
  (L2 스위칭, MAC 주소 기반)
```

### 4. NAT와 외부 통신

컨테이너에서 외부로 나가는 트래픽은 **iptables MASQUERADE**(SNAT)를 통해 호스트 IP로 변환된다.

```
[컨테이너 → 외부]
Container (172.17.0.2:54321)
    → docker0 bridge (172.17.0.1)
    → iptables NAT (MASQUERADE)
    → eth0 (192.168.1.100:random_port)  ← 소스 IP 변환
    → 인터넷

[외부 → 컨테이너] (Port Mapping: -p 8080:80)
외부 (any) → eth0:8080
    → iptables DNAT (192.168.1.100:8080 → 172.17.0.2:80)
    → docker0 bridge
    → Container (172.17.0.2:80)
```

**iptables 규칙 (Docker가 자동 생성):**

```
# SNAT: 컨테이너 → 외부
-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE

# DNAT: 외부 → 컨테이너 (포트 매핑)
-A DOCKER -p tcp --dport 8080 -j DNAT --to-destination 172.17.0.2:80

# 컨테이너 간 통신 허용
-A FORWARD -i docker0 -o docker0 -j ACCEPT
```

### 5. Docker 네트워크 드라이버

| 드라이버 | 격리 수준 | 사용 사례 |
|----------|----------|----------|
| **bridge** (기본) | 컨테이너별 NS | 단일 호스트, 개발 환경 |
| **host** | NS 공유 (호스트와 동일) | 성능 최우선 (네트워크 오버헤드 제거) |
| **none** | 네트워크 없음 | 배치 작업, 보안 격리 |
| **overlay** | 멀티호스트 VXLAN | Docker Swarm, 멀티 노드 |
| **macvlan** | 물리 NIC에 직접 연결 | 레거시 시스템 통합, VLAN 필요 시 |

### 6. CNI (Container Network Interface)

Kubernetes에서는 Docker 네트워크 대신 **CNI 플러그인**을 사용한다. CNI는 컨테이너 네트워크 설정/해제의 표준 인터페이스이다.

```
kubelet → CRI (containerd) → CNI Plugin → 네트워크 설정

CNI 플러그인 호출 흐름:
  1. Pod 생성 요청
  2. containerd가 pause 컨테이너 (sandbox) 생성
  3. CNI 플러그인 실행: ADD 명령
     → veth pair 생성
     → IP 할당 (IPAM)
     → 라우팅 규칙 설정
  4. 애플리케이션 컨테이너가 sandbox NS에 합류
```

| CNI 플러그인 | 특징 | 사용 환경 |
|-------------|------|----------|
| **Calico** | BGP 기반 L3, NetworkPolicy 강력 | 온프레미스, 대규모 클러스터 |
| **Cilium** | eBPF 기반, L7 정책, iptables-free | 최신 K8s, 고성능 요구 |
| **AWS VPC CNI** | Pod에 VPC IP 직접 할당 | EKS |
| **Azure CNI** | Pod에 VNet IP 직접 할당 | AKS |
| **Flannel** | 간단한 VXLAN overlay | 소규모, 학습용 |

---

## 실전 예시

### 네트워크 네임스페이스 직접 확인

```bash
# 컨테이너 실행
docker run -d --name web nginx:latest

# 컨테이너의 PID 확인
PID=$(docker inspect --format '{{.State.Pid}}' web)

# 컨테이너의 네트워크 네임스페이스에서 명령 실행
sudo nsenter -t $PID -n ip addr show
sudo nsenter -t $PID -n ip route show
sudo nsenter -t $PID -n ss -tlnp

# 호스트에서 veth pair 확인
ip link show type veth
bridge link show docker0
```

### Bridge 네트워크 구성 분석

```bash
# Docker bridge 네트워크 상세 정보
docker network inspect bridge | jq '.[0].IPAM'
# {
#   "Config": [{ "Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1" }]
# }

# 사용자 정의 bridge 네트워크 생성
docker network create --subnet=10.10.0.0/24 --gateway=10.10.0.1 mynet

# 사용자 정의 네트워크에 컨테이너 연결
docker run -d --name app --network mynet nginx
docker run -d --name db --network mynet postgres:16

# 사용자 정의 네트워크에서는 DNS(컨테이너 이름)으로 통신 가능
docker exec app ping db   # 기본 bridge에서는 불가
```

### iptables NAT 규칙 확인

```bash
# Docker가 생성한 NAT 규칙 확인
sudo iptables -t nat -L -n -v

# MASQUERADE (SNAT) 규칙
sudo iptables -t nat -L POSTROUTING -n -v
# MASQUERADE  all  --  172.17.0.0/16  0.0.0.0/0

# DNAT (포트 매핑) 규칙
docker run -d -p 8080:80 --name web nginx
sudo iptables -t nat -L DOCKER -n -v
# DNAT  tcp  --  0.0.0.0/0  0.0.0.0/0  tcp dpt:8080 to:172.17.0.2:80

# FORWARD 규칙
sudo iptables -L FORWARD -n -v
```

### 네트워크 트러블슈팅

```bash
# 컨테이너에서 DNS 확인
docker exec web cat /etc/resolv.conf
docker exec web nslookup google.com

# 컨테이너 간 연결 테스트
docker exec app curl -s http://db:5432 2>&1 || echo "연결 확인"

# 패킷 캡처 (호스트에서 veth 인터페이스)
sudo tcpdump -i vethXXX -nn -c 20

# 컨테이너 네트워크 네임스페이스에서 패킷 캡처
PID=$(docker inspect --format '{{.State.Pid}}' web)
sudo nsenter -t $PID -n tcpdump -i eth0 -nn -c 20

# docker0 bridge 트래픽 모니터링
sudo tcpdump -i docker0 -nn port 80
```

### host 네트워크 모드 비교

```bash
# bridge 모드 (기본): 네트워크 격리, NAT 오버헤드
docker run -d --name bridge-nginx -p 80:80 nginx
# 호스트:80 → NAT → 컨테이너:80

# host 모드: 격리 없음, NAT 없음, 최고 성능
docker run -d --name host-nginx --network host nginx
# 컨테이너가 호스트의 80 포트를 직접 사용

# 성능 차이: host 모드가 ~5-10% 낮은 레이턴시
# 단, 포트 충돌 주의 필요
```

---

## 면접 Q&A

### Q1: "컨테이너 네트워킹이 어떻게 작동하는지 설명해주세요."

**30초 답변**:
"각 컨테이너는 독립된 네트워크 네임스페이스를 가지고, veth pair로 호스트의 bridge(docker0)에 연결됩니다. 같은 bridge의 컨테이너끼리는 L2 스위칭으로 통신하고, 외부 통신은 iptables NAT(MASQUERADE)를 통해 호스트 IP로 변환됩니다."

**2분 답변**:
"컨테이너 네트워킹은 세 가지 Linux 커널 기술의 조합입니다. 첫째, 네트워크 네임스페이스로 컨테이너마다 독립된 네트워크 스택(인터페이스, 라우팅, iptables)을 부여합니다. 둘째, veth pair는 가상 이더넷 케이블로, 한쪽은 컨테이너의 eth0, 다른 쪽은 호스트의 bridge에 연결됩니다. 셋째, iptables로 NAT 규칙을 설정합니다. 외부 → 컨테이너는 DNAT(포트 매핑), 컨테이너 → 외부는 MASQUERADE(SNAT)를 사용합니다. Kubernetes 환경에서는 Docker 네트워크 대신 CNI 플러그인이 이 역할을 합니다. AWS EKS에서는 VPC CNI가 Pod에 VPC IP를 직접 할당하여 NAT 없이 VPC 내 직접 통신이 가능합니다."

**경험 연결**:
"온프레미스 환경에서 컨테이너 네트워크 문제를 디버깅할 때, nsenter로 컨테이너 네임스페이스에 들어가 tcpdump와 ip route를 확인하는 것이 가장 효과적이었습니다. iptables NAT 규칙 확인도 필수적인 트러블슈팅 스킬입니다."

**주의**:
Docker의 기본 bridge 네트워크에서는 컨테이너 이름으로 DNS 해석이 안 된다. 사용자 정의 bridge 네트워크를 만들어야 내장 DNS가 동작한다.

### Q2: "veth pair가 무엇이고, 왜 필요한가요?"

**30초 답변**:
"veth pair는 두 네트워크 네임스페이스를 연결하는 가상 이더넷 케이블입니다. 한쪽 끝에서 패킷을 보내면 다른 쪽 끝에서 받습니다. 컨테이너(격리된 NS)와 호스트(bridge)를 연결하는 유일한 통로입니다."

**2분 답변**:
"네트워크 네임스페이스는 완전히 격리된 네트워크 스택이므로, 외부와 통신하려면 연결 통로가 필요합니다. veth pair는 항상 쌍으로 생성되며, 한쪽을 컨테이너 NS에 넣고(eth0으로 이름 변경) 다른 쪽을 호스트의 bridge에 연결합니다. 패킷 흐름은 이렇습니다: 컨테이너 eth0 → veth pair → 호스트 vethXXX → docker0 bridge → 목적지(다른 컨테이너의 veth 또는 iptables NAT → 외부). Kubernetes의 Pod도 동일한 원리입니다. pause 컨테이너가 네트워크 NS를 만들고, CNI 플러그인이 veth pair를 생성하여 노드의 bridge(또는 직접 라우팅)에 연결합니다."

**경험 연결**:
"네트워크 문제 시 `ip link show type veth`로 호스트의 veth 인터페이스를 확인하고, `bridge link`로 어떤 bridge에 연결되어 있는지 추적하는 방법으로 장애를 해결한 경험이 있습니다."

**주의**:
veth pair는 양방향이지만, 한쪽이 삭제되면 다른 쪽도 자동 삭제된다. 컨테이너 종료 시 해당 NS의 veth가 삭제되면서 호스트 측 veth도 정리된다.

### Q3: "Docker bridge 네트워크와 host 네트워크의 차이와 선택 기준은?"

**30초 답변**:
"bridge는 컨테이너마다 독립된 네트워크 NS와 IP를 부여하고 NAT로 통신합니다. host는 호스트의 네트워크 NS를 공유하여 NAT 오버헤드가 없지만 격리가 없습니다. 성능이 중요한 경우 host를, 격리가 필요한 경우 bridge를 선택합니다."

**2분 답변**:
"bridge 모드에서 컨테이너는 172.17.x.x 대역의 IP를 받고, 외부 통신 시 iptables NAT를 거칩니다. 포트 매핑(-p)으로 외부 노출하며, 각 컨테이너가 같은 포트(예: 80)를 사용해도 충돌하지 않습니다. host 모드에서 컨테이너는 호스트의 네트워크 스택을 그대로 사용합니다. NAT가 없어 레이턴시가 5-10% 낮고 throughput이 높지만, 포트 충돌이 발생할 수 있고 네트워크 격리가 없습니다. 실무에서 host 모드를 사용하는 경우는 고성능 네트워크 처리(모니터링 에이전트, 로드밸런서, 네트워크 프록시)이며, 일반 애플리케이션은 bridge(또는 K8s의 CNI)를 사용합니다."

**경험 연결**:
"온프레미스 환경에서 Prometheus node-exporter를 host 네트워크로 실행하여 호스트 메트릭을 수집했고, 일반 서비스는 bridge/CNI로 격리하여 운영했습니다."

**주의**:
K8s에서 hostNetwork: true로 Pod를 실행하면 호스트 포트를 직접 사용한다. kube-proxy, CNI daemonset 등 시스템 컴포넌트 외에는 사용을 지양한다.

### Q4: "Kubernetes에서 CNI의 역할과 선택 기준은?"

**30초 답변**:
"CNI는 Pod 생성 시 네트워크 인터페이스 설정, IP 할당, 라우팅 규칙을 담당하는 표준 인터페이스입니다. 클라우드 환경에서는 해당 클라우드의 CNI(AWS VPC CNI, Azure CNI)를, 온프레미스에서는 Calico나 Cilium을 사용합니다."

**2분 답변**:
"CNI 플러그인은 Pod sandbox 생성 시 호출되어 veth pair 생성, IP 할당(IPAM), 라우팅을 설정합니다. 선택 기준은 환경에 따라 다릅니다. AWS EKS에서는 VPC CNI가 Pod에 VPC 서브넷 IP를 직접 할당하여 VPC 내 직접 통신이 가능하고, 보안 그룹을 Pod 단위로 적용할 수 있습니다. Azure AKS에서는 Azure CNI가 유사한 역할을 합니다. 온프레미스에서는 Calico(BGP 라우팅, 강력한 NetworkPolicy)나 Cilium(eBPF 기반, 높은 성능, L7 정책)을 선택합니다. NetworkPolicy 지원 여부도 중요한데, Flannel은 NetworkPolicy를 지원하지 않아 프로덕션에는 부적합합니다."

**경험 연결**:
"온프레미스 K8s에서 Calico를 사용하여 네트워크 정책으로 네임스페이스 간 트래픽을 제어했습니다. BGP 모드로 물리 네트워크와 직접 피어링하여 overlay 오버헤드를 제거한 경험이 있습니다."

**주의**:
AWS VPC CNI는 ENI(Elastic Network Interface)당 IP 수에 제한이 있어, 노드당 Pod 수가 인스턴스 타입에 따라 제한된다. 대규모 배포 시 prefix delegation 설정이 필요하다.

---

## Allganize 맥락

- **EKS의 VPC CNI**: Allganize의 AWS 환경에서 EKS는 VPC CNI를 기본 사용한다. Pod가 VPC IP를 직접 받으므로 RDS, ElastiCache 등 AWS 서비스와 NAT 없이 직접 통신한다.
- **AKS의 Azure CNI**: Azure 환경에서는 Azure CNI로 Pod에 VNet IP를 할당받는다. Azure Private Link와 결합하여 Azure OpenAI Service 등과 프라이빗 통신이 가능하다.
- **NetworkPolicy**: LLM 추론 서비스, 백엔드 API, 데이터베이스 간 네트워크 정책을 적용하여 최소 권한 원칙을 구현한다. Calico 또는 Cilium의 NetworkPolicy로 네임스페이스/레이블 기반 트래픽 제어를 한다.
- **서비스 메시**: 마이크로서비스 간 mTLS, 트래픽 관리가 필요하면 Istio/Linkerd를 CNI 위에 추가 배포한다.

---
**핵심 키워드**: `veth pair` `bridge` `NAT` `iptables` `Network Namespace` `CNI` `VPC CNI`
