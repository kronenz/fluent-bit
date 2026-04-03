# 03. 네트워킹 기초 (Networking Basics)

> **TL;DR**
> 1. **TCP/IP 스택**의 3-way handshake, TIME_WAIT 동작을 이해해야 서비스 장애를 진단할 수 있다.
> 2. **iptables/netfilter**는 리눅스 방화벽이자 쿠버네티스 서비스 네트워킹의 핵심 기반이다.
> 3. 폐쇄망에서 네트워크를 직접 설계하고 방화벽을 관리한 경험은 쿠버네티스 네트워킹 트러블슈팅의 결정적 강점이다.

---

## 1. TCP/IP 스택 (TCP/IP Stack)

### 계층 구조

```
┌──────────────────────────────────────┐
│  Application Layer (L7)              │
│  HTTP, DNS, SSH, gRPC                │
├──────────────────────────────────────┤
│  Transport Layer (L4)                │
│  TCP, UDP                            │
├──────────────────────────────────────┤
│  Network Layer (L3)                  │
│  IP, ICMP, ARP                       │
├──────────────────────────────────────┤
│  Data Link Layer (L2)                │
│  Ethernet, VLAN                      │
├──────────────────────────────────────┤
│  Physical Layer (L1)                 │
│  전기 신호, 광케이블                   │
└──────────────────────────────────────┘
```

### TCP 3-way Handshake

```
Client                          Server
  │                                │
  │──── SYN (seq=x) ────────────→ │
  │                                │
  │←─── SYN-ACK (seq=y, ack=x+1) ─│
  │                                │
  │──── ACK (ack=y+1) ───────────→ │
  │                                │
  │         연결 수립 (ESTABLISHED)  │
```

```bash
# TCP 연결 상태 확인
ss -tnap

# 상태별 TCP 연결 수 집계
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn

# 특정 포트의 연결 상태 확인
ss -tnap | grep :8080

# SYN 백로그 크기 확인
cat /proc/sys/net/ipv4/tcp_max_syn_backlog

# 연결 수립 대기 큐 크기
cat /proc/sys/net/core/somaxconn
```

### TCP 연결 종료와 TIME_WAIT

```
Client (능동 종료)              Server (수동 종료)
  │                                │
  │──── FIN ─────────────────────→ │  ← CLOSE_WAIT
  │                                │
  │←─── ACK ──────────────────── │
  │                                │
  │←─── FIN ──────────────────── │
  │                                │
  │──── ACK ─────────────────────→ │  ← CLOSED
  │                                │
  │  TIME_WAIT (2*MSL = 60초)      │
  │  → CLOSED                      │
```

**TIME_WAIT**는 능동적으로 연결을 종료한 쪽에서 발생한다. 목적은:
1. 지연된 패킷이 새 연결에 혼입되는 것을 방지
2. 마지막 ACK 유실 시 재전송 대응

```bash
# TIME_WAIT 연결 수 확인
ss -tan state time-wait | wc -l

# TIME_WAIT 과다 시 커널 파라미터 튜닝
# tcp_tw_reuse: TIME_WAIT 소켓 재사용 허용
cat /proc/sys/net/ipv4/tcp_tw_reuse
echo 1 > /proc/sys/net/ipv4/tcp_tw_reuse

# 로컬 포트 범위 확인 및 확장
cat /proc/sys/net/ipv4/ip_local_port_range
echo "1024 65535" > /proc/sys/net/ipv4/ip_local_port_range

# 영구 설정 (/etc/sysctl.conf)
cat >> /etc/sysctl.conf << 'SYSCTL'
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
SYSCTL
sysctl -p
```

> **폐쇄망 경험 연결**: 폐쇄망에서 고부하 서비스를 운영하면 TIME_WAIT 폭증으로 포트 고갈이 발생할 수 있다. 클라우드의 로드밸런서가 이를 대신 처리해주는 것과 달리, 온프레미스에서는 직접 커널 파라미터를 튜닝해야 하므로 TCP 상태 전이를 깊이 이해해야 한다.

---

## 2. DNS (Domain Name System)

### DNS 동작 원리

```
┌────────────┐   1. 쿼리     ┌────────────────┐
│ Application│ ───────────→ │ Local Resolver  │
│            │              │ (/etc/resolv.conf│
└────────────┘              │  에 설정된 DNS)  │
                            └───────┬─────────┘
                                    │ 2. 캐시 미스
                            ┌───────▼─────────┐
                            │  Root DNS (.)    │
                            └───────┬─────────┘
                                    │ 3. .com 위임
                            ┌───────▼─────────┐
                            │  TLD DNS (.com)  │
                            └───────┬─────────┘
                                    │ 4. example.com 위임
                            ┌───────▼──────────────┐
                            │  Authoritative DNS   │
                            │  (example.com)       │
                            └──────────────────────┘
```

### /etc/resolv.conf와 /etc/hosts

```bash
# DNS 서버 설정 확인
cat /etc/resolv.conf
# nameserver 8.8.8.8
# nameserver 8.8.4.4
# search example.com   ← 도메인 검색 접미사

# 이름 해석 순서 확인
cat /etc/nsswitch.conf | grep hosts
# hosts: files dns   ← /etc/hosts 먼저, 그 다음 DNS

# DNS 쿼리 테스트
dig example.com +trace       # 전체 해석 경로 추적
dig example.com @8.8.8.8     # 특정 DNS 서버로 쿼리
nslookup example.com
host example.com

# DNS 캐시 확인 (systemd-resolved)
resolvectl statistics
resolvectl query example.com
```

### 쿠버네티스 DNS (CoreDNS)

```bash
# Pod 내부의 DNS 설정 확인
kubectl exec <pod> -- cat /etc/resolv.conf
# nameserver 10.96.0.10      ← CoreDNS ClusterIP
# search default.svc.cluster.local svc.cluster.local cluster.local
# ndots:5                     ← 점이 5개 미만이면 search 도메인 추가 시도

# CoreDNS 로그 확인
kubectl logs -n kube-system -l k8s-app=kube-dns

# DNS 해석 테스트 (Pod 내부)
kubectl exec <pod> -- nslookup kubernetes.default.svc.cluster.local
```

> **ndots:5 주의점**: `example.com`을 조회하면 점이 1개이므로 search 도메인을 모두 붙여 5번 쿼리 후 마지막에 원래 도메인을 조회한다. 외부 도메인 조회가 느리다면 **ndots를 낮추거나 FQDN 끝에 `.`을 붙이는 것**이 해결책이다.

---

## 3. 라우팅 (Routing)

```bash
# 라우팅 테이블 확인
ip route show
# default via 192.168.1.1 dev eth0 proto dhcp metric 100
# 192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.10
# 10.244.0.0/16 via 10.244.0.1 dev cni0   ← Pod 네트워크 라우트

# 특정 목적지까지의 경로 확인
ip route get 8.8.8.8
traceroute 8.8.8.8

# 정적 라우트 추가
ip route add 10.0.0.0/8 via 192.168.1.254 dev eth0

# Policy-based routing (다중 인터페이스)
ip rule show
ip rule add from 192.168.2.0/24 table 100
ip route add default via 192.168.2.1 table 100

# ARP 테이블 확인
ip neigh show
```

---

## 4. iptables / netfilter

### netfilter 구조

**netfilter**는 Linux 커널의 네트워크 패킷 처리 프레임워크이고, **iptables**는 그 사용자 공간(userspace) 인터페이스다.

```
                    ┌─────────────────────────────────────────┐
    패킷 도착 →     │              PREROUTING                  │
                    │  (raw → mangle → nat)                    │
                    └───────────┬───────────────┬──────────────┘
                                │               │
                     라우팅 결정 ↓               │ 로컬 목적지
                    ┌───────────┐      ┌────────▼──────────┐
                    │ FORWARD   │      │ INPUT              │
                    │(mangle →  │      │(mangle → filter)   │
                    │ filter)   │      └────────┬──────────┘
                    └─────┬─────┘               │
                          │              ┌──────▼──────┐
                          │              │ 로컬 프로세스│
                          │              └──────┬──────┘
                    ┌─────▼─────────────────────▼──────┐
                    │           POSTROUTING              │
                    │     (mangle → nat)                 │
                    └───────────┬───────────────────────┘
                                │
                         패킷 출발 →
```

### 5개의 체인 (Chain)

| 체인 | 시점 | 주요 용도 |
|------|------|----------|
| **PREROUTING** | 패킷 도착 직후, 라우팅 전 | DNAT (포트포워딩) |
| **INPUT** | 로컬 프로세스로 전달될 때 | 방화벽 (접근 제어) |
| **FORWARD** | 다른 인터페이스로 전달될 때 | 라우터/브리지 필터링 |
| **OUTPUT** | 로컬에서 생성된 패킷 출발 시 | 아웃바운드 제어 |
| **POSTROUTING** | 패킷이 인터페이스를 떠나기 직전 | SNAT/MASQUERADE |

### 4개의 테이블 (Table)

| 테이블 | 용도 | 주요 사용 체인 |
|--------|------|---------------|
| **filter** | 패킷 허용/차단 (기본) | INPUT, FORWARD, OUTPUT |
| **nat** | 주소 변환 | PREROUTING, POSTROUTING |
| **mangle** | 패킷 헤더 수정 | 모든 체인 |
| **raw** | 연결 추적 예외 | PREROUTING, OUTPUT |

### 실전 명령어

```bash
# 현재 규칙 확인
iptables -L -n -v --line-numbers
iptables -t nat -L -n -v --line-numbers

# 특정 포트 허용
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# 특정 IP 차단
iptables -A INPUT -s 10.0.0.100 -j DROP

# DNAT (외부 8080 → 내부 80으로 포트포워딩)
iptables -t nat -A PREROUTING -p tcp --dport 8080 -j DNAT --to-destination 192.168.1.10:80

# SNAT/MASQUERADE (내부 네트워크 → 외부 인터넷)
iptables -t nat -A POSTROUTING -s 10.0.0.0/8 -o eth0 -j MASQUERADE

# 규칙 저장 및 복원
iptables-save > /etc/iptables/rules.v4
iptables-restore < /etc/iptables/rules.v4

# 연결 추적 테이블 확인
conntrack -L
conntrack -C    # 현재 추적 중인 연결 수
cat /proc/sys/net/netfilter/nf_conntrack_max   # 최대 추적 수
```

### nftables (iptables 후속)

```bash
# nftables 규칙 확인 (RHEL 8+, Ubuntu 20.04+)
nft list ruleset

# iptables가 실제로 nftables 백엔드를 사용하는지 확인
iptables --version
# iptables v1.8.7 (nf_tables) ← nftables 백엔드
```

---

## 5. 쿠버네티스 네트워킹과의 연결점

### kube-proxy와 iptables

쿠버네티스의 **kube-proxy**는 Service의 ClusterIP를 Pod IP로 변환하기 위해 iptables(또는 IPVS) 규칙을 생성한다.

```bash
# kube-proxy가 생성한 iptables 규칙 확인 (노드에서)
iptables -t nat -L KUBE-SERVICES -n | head -20
iptables -t nat -L KUBE-SVC-XXXX -n    # 특정 서비스의 규칙

# IPVS 모드 확인
ipvsadm -L -n

# kube-proxy 모드 확인
kubectl get cm kube-proxy -n kube-system -o yaml | grep mode
```

### Service 네트워킹 흐름

```
┌──────────┐     ┌──────────────────────────────────────┐
│  Client  │────→│  ClusterIP (10.96.0.100:80)          │
│  Pod     │     │      │                                │
└──────────┘     │  iptables DNAT                        │
                 │      │                                │
                 │  ┌───▼──────────┐  ┌───────────────┐ │
                 │  │ Pod1 10.244. │  │ Pod2 10.244.  │ │
                 │  │    1.5:8080  │  │    2.3:8080   │ │
                 │  └──────────────┘  └───────────────┘ │
                 └──────────────────────────────────────┘
```

### CNI (Container Network Interface)

```bash
# CNI 플러그인 설정 확인
ls /etc/cni/net.d/
cat /etc/cni/net.d/10-flannel.conflist

# Pod 네트워크 인터페이스 확인
kubectl exec <pod> -- ip addr show
kubectl exec <pod> -- ip route show

# 노드 간 Pod 통신 확인
kubectl exec <pod-on-node1> -- ping <pod-ip-on-node2>
```

> **폐쇄망 경험 연결**: 에어갭 환경에서 네트워크 세그먼트를 직접 설계하고 방화벽 규칙을 관리한 경험은 쿠버네티스의 NetworkPolicy, Service 네트워킹, CNI 구성을 이해하는 데 강력한 기반이 된다. 특히 iptables를 직접 다뤄본 경험은 kube-proxy 트러블슈팅에서 큰 차이를 만든다.

---

## 면접 Q&A

### Q1. "TCP 3-way handshake를 설명하고, 왜 3-way인가요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "클라이언트가 SYN을 보내고, 서버가 SYN-ACK로 응답하며, 클라이언트가 ACK를 보내 연결을 수립합니다. 3-way인 이유는 **양방향 통신 채널의 신뢰성을 확보**하기 위함입니다. 클라이언트→서버 채널(SYN/SYN-ACK)과 서버→클라이언트 채널(SYN-ACK/ACK)을 각각 확인하며, SYN과 ACK를 합쳐 3번으로 최적화한 것입니다. 2-way로는 서버가 클라이언트의 수신 능력을 확인할 수 없고, 4-way는 불필요한 중복입니다."

### Q2. "TIME_WAIT가 왜 존재하고, 너무 많으면 어떻게 대응하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "TIME_WAIT는 능동 종료 측에서 2*MSL(보통 60초) 동안 유지됩니다. 두 가지 목적이 있습니다. 첫째, 지연된 패킷이 새 연결에 혼입되는 것을 방지합니다. 둘째, 마지막 ACK가 유실됐을 때 상대방의 FIN 재전송에 응답하기 위함입니다. 과다 발생 시 `tcp_tw_reuse=1`로 재사용을 허용하고, `ip_local_port_range`를 확장합니다. 근본적으로는 Connection Pooling이나 Keep-Alive를 활용하여 연결 재사용을 늘리는 것이 해결책입니다."

### Q3. "iptables의 테이블과 체인의 관계를 설명해주세요."

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "iptables는 4개의 테이블(filter, nat, mangle, raw)과 5개의 체인(PREROUTING, INPUT, FORWARD, OUTPUT, POSTROUTING)으로 구성됩니다. 패킷은 방향에 따라 체인을 통과하고, 각 체인에서 테이블의 규칙이 순서대로 적용됩니다. 예를 들어, 외부에서 로컬로 오는 패킷은 PREROUTING(nat에서 DNAT) → INPUT(filter에서 허용/차단) 순서로 처리됩니다. 쿠버네티스에서는 kube-proxy가 nat 테이블의 PREROUTING에 DNAT 규칙을 추가하여 Service ClusterIP를 Pod IP로 변환합니다."

### Q4. "쿠버네티스에서 ndots:5 설정이 성능 문제를 일으킬 수 있는 이유는?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "ndots:5는 도메인에 점이 5개 미만이면 search 도메인을 순서대로 붙여 먼저 시도합니다. `api.example.com`을 조회하면 점이 2개이므로 `api.example.com.default.svc.cluster.local`, `.svc.cluster.local`, `.cluster.local` 등을 먼저 시도한 후 마지막에 원래 도메인을 조회합니다. 외부 도메인 조회마다 불필요한 DNS 쿼리가 4~5배 발생하여 CoreDNS에 부하를 줍니다. 해결 방법은 FQDN 끝에 `.`을 붙이거나, Pod spec에서 `dnsConfig.options`로 ndots를 낮추는 것입니다."

### Q5. "폐쇄망에서 DNS를 어떻게 구성하셨나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "에어갭 환경에서는 내부 DNS 서버를 구축하여 사용했습니다. BIND나 dnsmasq로 내부 도메인 존(zone)을 관리하고, 외부 도메인이 필요한 경우 수동으로 A 레코드를 등록하거나 /etc/hosts를 배포했습니다. 쿠버네티스 환경에서는 CoreDNS의 forward 플러그인을 내부 DNS로 설정하고, 외부 접근이 필요한 서비스는 ExternalName이나 Endpoints를 수동 생성하여 해결했습니다. 이런 경험이 DNS 동작 원리를 깊이 이해하는 계기가 되었습니다."

---

**Tags**: `#TCP_3way_handshake` `#TIME_WAIT` `#iptables_netfilter` `#DNS_resolv.conf` `#쿠버네티스_네트워킹`
