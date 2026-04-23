# Worker Node Components

> **TL;DR**: Worker Node는 실제 워크로드가 실행되는 곳으로, kubelet이 Pod 생명주기를 관리하고, kube-proxy가 서비스 네트워킹을 처리하며, Container Runtime(containerd)이 컨테이너를 실행한다.
> CNI 플러그인은 Pod 간 네트워크 통신을 담당하며, 각 Pod에 고유 IP를 할당한다.
> kubelet은 Control Plane의 "손과 발"로, apiserver와 지속적으로 통신하며 노드 상태를 보고한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Worker Node 전체 구조

```
┌──────────────────────────────────────────────────┐
│                  Worker Node                      │
│                                                  │
│  ┌─────────┐   ┌───────────┐   ┌──────────────┐ │
│  │ kubelet  │   │kube-proxy │   │  Container   │ │
│  │          │   │           │   │  Runtime     │ │
│  │ (agent)  │   │(iptables/ │   │ (containerd) │ │
│  │          │   │ ipvs)     │   │              │ │
│  └────┬─────┘   └─────┬─────┘   └──────┬───────┘ │
│       │               │                │         │
│       │         ┌─────┴─────┐          │         │
│       │         │ CNI Plugin│          │         │
│       │         │(Calico/   │          │         │
│       │         │ Cilium)   │          │         │
│       │         └───────────┘          │         │
│       │                                │         │
│  ┌────┴────────────────────────────────┴───┐     │
│  │              Linux Kernel                │     │
│  │  (cgroups, namespaces, netfilter)        │     │
│  └──────────────────────────────────────────┘     │
└──────────────────────────────────────────────────┘
         │
         │  gRPC (CRI)
         ▼
   Control Plane (apiserver)
```

### 1. kubelet

Worker Node에서 실행되는 **에이전트 프로세스**. Control Plane과 Worker Node의 연결 고리.

**핵심 역할:**
- apiserver에서 PodSpec을 수신하고 해당 Pod가 실행되도록 보장
- Container Runtime에 CRI(Container Runtime Interface)를 통해 컨테이너 생성/삭제 지시
- Probe(liveness, readiness, startup) 실행 및 결과 보고
- 노드 상태(Node Status)를 주기적으로 apiserver에 보고
- cAdvisor 통합으로 리소스 사용량 메트릭 수집
- Static Pod 관리 (`/etc/kubernetes/manifests/`)

**kubelet의 작동 방식:**
```
apiserver ──watch──► kubelet
                        │
                        ├─► PodSpec 수신
                        │
                        ├─► CRI 호출 ──► containerd ──► runc ──► Container
                        │
                        ├─► Probe 실행 (HTTP/TCP/Exec)
                        │
                        ├─► CSI 호출 ──► Volume Mount
                        │
                        └─► Node Status 보고 (10s 주기)
                             - CPU/Memory 용량 및 사용량
                             - 실행 중인 Pod 목록
                             - Node Conditions (Ready, DiskPressure 등)
```

**Static Pod:**
```
/etc/kubernetes/manifests/
├── kube-apiserver.yaml        ← kubeadm이 여기에 배치
├── kube-controller-manager.yaml
├── kube-scheduler.yaml
└── etcd.yaml
```
kubelet이 이 디렉토리를 감시하며, 파일이 있으면 자동으로 Pod를 생성한다. apiserver 없이도 동작 가능.

### 2. kube-proxy

**Service 추상화의 네트워크 구현체**. ClusterIP, NodePort, LoadBalancer 서비스의 트래픽 라우팅을 담당.

**동작 모드:**

| 모드 | 메커니즘 | 성능 | 특징 |
|------|---------|------|------|
| iptables (기본) | netfilter rules | 중간 | 규칙 수에 비례해 성능 저하 |
| ipvs | Linux IPVS | 높음 | 해시 테이블 기반, 대규모에 유리 |
| nftables (1.29+) | nftables rules | 높음 | iptables 후속, 최신 커널 필요 |

**iptables 모드 동작:**
```
Client Pod ──► ClusterIP (10.96.0.10)
                    │
            iptables DNAT rules
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
       Pod-1     Pod-2     Pod-3
    (10.244.1.5)(10.244.2.3)(10.244.3.7)

    → 랜덤 확률 기반 로드밸런싱
    → Service 당 O(n) 규칙 생성
```

**ipvs 모드 동작:**
```
Client Pod ──► Virtual IP (kube-ipvs0 인터페이스)
                    │
              IPVS 해시 테이블
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
       Pod-1     Pod-2     Pod-3

    → rr, lc, sh 등 다양한 알고리즘
    → O(1) 룩업 성능
    → 1000+ 서비스 환경에서 유리
```

### 3. Container Runtime

kubelet이 **CRI(Container Runtime Interface)**를 통해 통신하는 컨테이너 실행 환경.

**런타임 스택:**
```
kubelet
  │
  │  CRI (gRPC)
  ▼
containerd          ◄── 고수준 런타임 (이미지 관리, 스냅샷)
  │
  │  OCI Runtime Spec
  ▼
runc                ◄── 저수준 런타임 (실제 컨테이너 생성)
  │
  │  syscalls
  ▼
Linux Kernel        ◄── namespaces, cgroups, seccomp
```

**주요 Container Runtime 비교:**

| Runtime | 특징 | 사용 사례 |
|---------|------|----------|
| containerd | Docker에서 분리, 업계 표준 | EKS, AKS, GKE 기본값 |
| CRI-O | Red Hat 주도, OCI 전용 | OpenShift |
| kata-containers | VM 기반 격리 | 멀티테넌트, 보안 중시 |
| gVisor (runsc) | 유저스페이스 커널 | 신뢰할 수 없는 워크로드 |

> Docker(dockershim)는 K8s 1.24에서 제거되었다. containerd가 사실상 표준.

### 4. CNI (Container Network Interface) Plugin

Pod에 **네트워크 인터페이스를 할당**하고, Pod 간 통신을 가능하게 하는 플러그인.

**Kubernetes 네트워크 모델 원칙:**
1. 모든 Pod는 고유한 IP를 가진다
2. 모든 Pod는 NAT 없이 다른 Pod와 통신할 수 있다
3. Node의 에이전트(kubelet 등)는 해당 Node의 모든 Pod와 통신할 수 있다

**주요 CNI 플러그인:**

| Plugin | 방식 | 특징 |
|--------|------|------|
| Calico | BGP / VXLAN / eBPF | NetworkPolicy 지원, 대규모 환경 |
| Cilium | eBPF | L7 정책, 관찰성, Service Mesh |
| AWS VPC CNI | ENI 직접 할당 | EKS 기본, VPC IP 사용 |
| Azure CNI | VNET IP 할당 | AKS 기본, 서브넷 IP 사용 |
| Flannel | VXLAN overlay | 간단, 소규모 환경 |

**AWS VPC CNI 동작 (EKS):**
```
┌─────────────────────────────────────┐
│          EC2 Instance (Node)         │
│                                     │
│  eth0 (Primary ENI)                 │
│  ├── 10.0.1.10 (Node IP)           │
│  │                                  │
│  eth1 (Secondary ENI)              │
│  ├── 10.0.1.20 ──► Pod-A           │
│  ├── 10.0.1.21 ──► Pod-B           │
│  ├── 10.0.1.22 ──► Pod-C           │
│  │                                  │
│  → VPC 내 라우팅으로 직접 통신       │
│  → ENI 당 할당 가능 IP 수 = 인스턴스  │
│    타입에 따라 제한                   │
└─────────────────────────────────────┘
```

---

## 실전 예시

### kubelet 상태 확인 및 디버깅

```bash
# kubelet 상태 확인
systemctl status kubelet
journalctl -u kubelet -f --no-pager | tail -50

# 노드 상태 상세 확인
kubectl describe node <node-name>
# → Conditions: Ready, MemoryPressure, DiskPressure, PIDPressure
# → Capacity vs Allocatable
# → Non-terminated Pods

# kubelet 설정 확인
kubectl get --raw "/api/v1/nodes/<node-name>/proxy/configz" | jq .
```

### kube-proxy 모드 확인 및 변경

```bash
# 현재 kube-proxy 모드 확인
kubectl get configmap kube-proxy -n kube-system -o yaml | grep mode

# iptables 규칙 확인 (노드에서)
iptables -t nat -L KUBE-SERVICES -n | head -20

# ipvs 규칙 확인 (ipvs 모드 시)
ipvsadm -ln

# kube-proxy를 ipvs 모드로 변경
kubectl edit configmap kube-proxy -n kube-system
# mode: "ipvs" 로 변경 후
kubectl rollout restart daemonset kube-proxy -n kube-system
```

### Container Runtime 관리

```bash
# containerd 상태 확인
systemctl status containerd

# crictl로 컨테이너 조회 (CRI 직접 접근)
crictl --runtime-endpoint unix:///run/containerd/containerd.sock ps
crictl pods
crictl images

# 특정 컨테이너 로그 확인
crictl logs <container-id>

# 이미지 정리
crictl rmi --prune
```

### CNI 디버깅

```bash
# Pod IP 할당 확인
kubectl get pods -o wide

# CNI 설정 확인 (노드에서)
ls /etc/cni/net.d/
cat /etc/cni/net.d/10-calico.conflist

# CNI 바이너리 위치
ls /opt/cni/bin/

# Pod 네트워크 네임스페이스 확인
crictl inspect <container-id> | jq '.info.runtimeSpec.linux.namespaces'

# AWS VPC CNI: 노드당 할당된 IP 확인
kubectl get node <node-name> -o jsonpath='{.status.addresses}'
```

### kubelet 리소스 할당 확인

```yaml
# kubelet config (/var/lib/kubelet/config.yaml)
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
evictionHard:
  memory.available: "100Mi"       # 이 이하면 Pod eviction
  nodefs.available: "10%"
  imagefs.available: "15%"
systemReserved:
  cpu: "500m"                     # 시스템용 예약
  memory: "1Gi"
kubeReserved:
  cpu: "500m"                     # K8s 컴포넌트용 예약
  memory: "1Gi"
# Allocatable = Capacity - systemReserved - kubeReserved - evictionHard
```

---

## 면접 Q&A

### Q: kubelet의 역할과 동작 방식을 설명해주세요.
**30초 답변**:
kubelet은 각 Worker Node에서 실행되는 에이전트로, apiserver로부터 PodSpec을 받아 Container Runtime(containerd)에 CRI를 통해 컨테이너 실행을 지시하고, Probe를 수행하며, 노드 상태를 주기적으로 보고합니다.

**2분 답변**:
kubelet은 Worker Node의 핵심 에이전트로 여러 중요한 역할을 수행합니다. 첫째, apiserver의 watch를 통해 해당 노드에 스케줄링된 Pod의 PodSpec을 수신합니다. 둘째, CRI(Container Runtime Interface)를 통해 containerd에 컨테이너 생성/삭제를 지시합니다. 이때 이미지 풀, 볼륨 마운트(CSI), 네트워크 설정(CNI)을 오케스트레이션합니다. 셋째, liveness/readiness/startup Probe를 실행하여 컨테이너 헬스를 모니터링하고, 필요시 재시작합니다. 넷째, 10초 간격으로 Node Status를 apiserver에 보고하는데, CPU/메모리 용량, allocatable 리소스, Node Conditions(Ready, DiskPressure 등)를 포함합니다. 또한 Static Pod 기능으로 `/etc/kubernetes/manifests/` 디렉토리의 매니페스트를 자동 실행하는데, kubeadm 기반 클러스터에서는 apiserver 자체도 이 방식으로 실행됩니다. eviction 매니저가 리소스 압박 시 우선순위 낮은 Pod를 퇴출하는 역할도 합니다.

**경험 연결**:
온프레미스 환경에서 kubelet이 "PLEG is not healthy" 오류를 보이며 노드가 NotReady 상태가 된 경험이 있습니다. 원인은 Container Runtime(당시 Docker)의 응답 지연이었으며, containerd로 전환 후 해결되었습니다. 이 경험을 통해 kubelet과 CRI의 관계를 깊이 이해하게 되었습니다.

**주의**:
kubelet은 Control Plane 컴포넌트가 아니라 Worker Node 컴포넌트다. 또한 kubelet은 Pod가 아닌 systemd 서비스로 실행되므로, `kubectl`로 직접 관리할 수 없다.

### Q: kube-proxy의 iptables 모드와 ipvs 모드 차이를 설명해주세요.
**30초 답변**:
iptables 모드는 netfilter 규칙으로 서비스 라우팅을 구현하며 규칙 수에 비례해 성능이 저하됩니다. ipvs 모드는 Linux IPVS의 해시 테이블을 사용하여 O(1) 룩업 성능을 제공하며, 다양한 로드밸런싱 알고리즘을 지원합니다.

**2분 답변**:
iptables 모드는 Kubernetes 기본값으로, 각 Service에 대해 DNAT 규칙을 생성합니다. ClusterIP로 들어온 트래픽을 확률 기반으로 백엔드 Pod에 분배합니다. 규칙이 선형적으로 증가하여 1000개 이상 서비스에서 성능 병목이 발생합니다. 규칙 업데이트 시 전체 iptables를 교체해야 하므로 latency spike가 생길 수 있습니다. ipvs 모드는 Linux 커널의 IPVS(IP Virtual Server)를 활용하며, 해시 테이블 기반으로 O(1) 성능을 제공합니다. round-robin, least-connection, source-hash 등 다양한 알고리즘을 지원합니다. kube-ipvs0 더미 인터페이스에 Virtual IP를 바인딩하고 IPVS 규칙으로 라우팅합니다. 대규모 클러스터(수천 서비스)에서는 ipvs 모드가 사실상 필수입니다. 최근에는 Cilium 같은 eBPF 기반 솔루션이 kube-proxy를 완전히 대체하는 추세도 있습니다.

**경험 연결**:
서비스 수가 500개를 넘어가면서 iptables 규칙 업데이트에 수 초가 걸려 간헐적 통신 실패가 발생한 경험이 있습니다. ipvs 모드로 전환 후 문제가 해결되었으며, `ipvsadm -ln`으로 룰을 직관적으로 확인할 수 있어 트러블슈팅도 용이해졌습니다.

**주의**:
ipvs 모드를 사용하려면 노드에 `ipvs` 커널 모듈이 로드되어 있어야 한다 (`ip_vs`, `ip_vs_rr`, `ip_vs_wrr`, `ip_vs_sh`, `nf_conntrack`).

### Q: Docker 대신 containerd를 사용하는 이유는 무엇인가요?
**30초 답변**:
Kubernetes 1.24에서 dockershim이 제거되면서 Docker를 직접 CRI로 사용할 수 없게 되었습니다. containerd는 Docker에서 분리된 컨테이너 런타임으로, CRI를 네이티브 지원하며, 중간 레이어가 없어 더 가볍고 빠릅니다.

**2분 답변**:
Docker는 원래 이미지 빌드, 런타임, CLI 등을 모두 포함한 모놀리식 도구였습니다. Kubernetes에서 Docker를 사용하면 kubelet → dockershim → dockerd → containerd → runc 경로를 거쳐야 했습니다. containerd를 직접 사용하면 kubelet → containerd → runc로 단축되어 레이어가 줄고, 리소스 오버헤드가 감소합니다. Docker의 이미지 빌드 기능은 Kubernetes 런타임에 불필요한데, containerd는 런타임 기능만 제공하여 공격 표면도 줄어듭니다. 실무에서 Docker로 빌드한 이미지는 OCI 표준을 따르므로 containerd에서 그대로 실행됩니다. CI/CD에서는 여전히 Docker나 buildah로 이미지를 빌드하고, 런타임만 containerd를 사용하는 것이 일반적입니다. EKS, AKS, GKE 모두 containerd가 기본 런타임입니다.

**경험 연결**:
Docker에서 containerd로의 마이그레이션을 수행한 경험이 있습니다. 기존에 `docker exec`으로 디버깅하던 습관을 `crictl exec`으로 전환해야 했고, 이미지 캐시가 호환되지 않아 마이그레이션 시 이미지를 다시 pull해야 했습니다. 하지만 노드당 메모리 사용량이 약 200MB 감소하는 효과가 있었습니다.

**주의**:
"Docker가 더 이상 사용 불가"라고 답하면 오해를 줄 수 있다. Docker로 빌드한 이미지는 여전히 사용 가능하며, Kubernetes 런타임에서만 Docker(dockershim)가 제거된 것이다.

### Q: CNI 플러그인의 역할과 AWS VPC CNI의 특징을 설명해주세요.
**30초 답변**:
CNI 플러그인은 Pod에 네트워크 인터페이스를 할당하고 Pod 간 통신을 구현합니다. AWS VPC CNI는 EC2의 ENI(Elastic Network Interface)에서 직접 IP를 할당하여 Pod가 VPC의 실제 IP를 사용하므로, overlay 없이 네이티브 성능을 제공합니다.

**2분 답변**:
CNI(Container Network Interface)는 kubelet이 Pod를 생성할 때 호출하는 플러그인 인터페이스로, ADD(네트워크 연결), DEL(네트워크 해제), CHECK(상태 확인) 명령을 구현합니다. 일반적인 CNI(Calico, Flannel)는 overlay 네트워크(VXLAN)를 사용하여 Pod IP를 캡슐화합니다. 반면 AWS VPC CNI는 EC2 인스턴스에 Secondary ENI를 추가하고, 각 ENI의 Secondary IP를 Pod에 직접 할당합니다. 이 방식의 장점은 VPC 내에서 Pod IP로 직접 라우팅이 가능하여 overlay 오버헤드가 없고, Security Group을 Pod 레벨에 적용할 수 있으며, VPC Flow Logs로 Pod 트래픽을 추적할 수 있습니다. 단점으로는 인스턴스 타입별 ENI 수와 IP 수가 제한되어 노드당 Pod 수에 한계가 있고, 서브넷 IP가 빠르게 소모될 수 있습니다. Prefix Delegation 모드를 활성화하면 /28 prefix를 할당하여 노드당 Pod 수를 크게 늘릴 수 있습니다.

**경험 연결**:
온프레미스에서는 Calico BGP 모드를 사용하여 물리 네트워크와 Pod 네트워크를 통합한 경험이 있습니다. AWS 환경에서는 VPC CNI를 사용하면 유사하게 VPC 라우팅으로 직접 통신이 가능하여, 온프레미스에서의 네트워크 설계 경험이 직접적으로 도움이 됩니다.

**주의**:
VPC CNI의 IP 제한은 인스턴스 타입에 따라 다르다. 예를 들어 m5.large는 최대 29개 Pod IP, m5.xlarge는 최대 58개이다. 이 제한을 모르면 Pod가 Pending 상태로 남을 수 있다.

---

## Allganize 맥락

- **EKS Worker Node 최적화**: Allganize의 AI/LLM 워크로드는 GPU 인스턴스(p3, g4, g5)를 사용하므로, NVIDIA Device Plugin이 kubelet과 연동하여 GPU를 Pod에 할당한다. GPU 노드의 kubelet 설정에서 `systemReserved`와 `kubeReserved`를 적절히 설정해야 OOM을 방지할 수 있다.
- **VPC CNI IP 관리**: LLM 서빙 Pod가 많아지면 VPC 서브넷 IP가 소모될 수 있다. Prefix Delegation 모드 또는 Custom Networking으로 별도 서브넷을 Pod에 할당하는 전략이 필요하다.
- **kube-proxy vs Cilium**: 대규모 마이크로서비스 환경에서는 Cilium으로 kube-proxy를 대체하여 eBPF 기반의 고성능 네트워킹과 L7 관찰성을 확보할 수 있다. Allganize의 서비스 간 통신 최적화에 유리하다.
- **containerd 런타임**: EKS/AKS 모두 containerd가 기본이므로, `crictl` 사용법과 containerd 설정(/etc/containerd/config.toml)에 익숙해야 노드 레벨 트러블슈팅이 가능하다.
- **폐쇄망 경험 활용**: 온프레미스에서 kubelet, kube-proxy를 직접 설치하고 설정한 경험은 managed K8s에서도 노드 이슈 디버깅 시 강력한 이점이 된다.

---
**핵심 키워드**: `kubelet` `kube-proxy` `containerd` `CRI` `CNI` `VPC-CNI` `iptables` `ipvs` `Static-Pod` `crictl`
