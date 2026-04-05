# cgroup과 namespace (컨테이너의 기반 기술)

> **TL;DR**
> 1. **cgroup**은 프로세스 그룹의 리소스 사용량(CPU, memory, I/O)을 **제한**하고, **namespace**는 시스템 리소스의 **가시성을 격리**한다.
> 2. cgroup v2는 단일 통합 계층과 PSI(Pressure Stall Information)를 지원하며, Kubernetes 1.25+에서 정식 지원된다.
> 3. **컨테이너 = namespace(격리) + cgroup(제한) + layered filesystem(이미지)** 이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### cgroup (Control Groups)

cgroup은 프로세스 그룹에 대해 리소스 사용량을 **제한(limit), 우선순위(priority), 감시(accounting), 제어(control)** 하는 커널 기능이다.

```
┌─────────────────────────────────────────────────┐
│                   cgroup 계층                     │
│                                                   │
│   root (/)                                        │
│    ├── system.slice/       ← systemd 서비스       │
│    │    ├── docker.service                        │
│    │    └── sshd.service                          │
│    ├── user.slice/         ← 사용자 세션          │
│    │    └── user-1000.slice                       │
│    └── kubepods.slice/     ← K8s Pod             │
│         ├── kubepods-burstable.slice              │
│         │    └── pod-xxxx.slice/                  │
│         │         ├── container-aaa (cpu, mem)    │
│         │         └── container-bbb (cpu, mem)    │
│         └── kubepods-besteffort.slice             │
└─────────────────────────────────────────────────┘
```

### cgroup v1 vs cgroup v2

| 구분 | cgroup v1 | cgroup v2 |
|------|-----------|-----------|
| 구조 | 컨트롤러별 **개별 계층** | **단일 통합 계층** |
| 마운트 포인트 | `/sys/fs/cgroup/<controller>/` | `/sys/fs/cgroup/` |
| 프로세스 소속 | 컨트롤러마다 다른 그룹 가능 | 하나의 그룹에만 소속 |
| PSI 지원 | X | **O** (Pressure Stall Information) |
| 위임(delegation) | 복잡, 보안 문제 | 안전한 위임 지원 |
| MemoryQoS | X | **O** (memory.low/high/max/min) |
| I/O 제어 | blkio (제한적) | io.weight, io.max (통합) |
| K8s 지원 | 기본값 (구버전) | **1.25+ 정식** (GA) |
| 주요 배포판 | RHEL 7/8, Ubuntu 20.04 | **RHEL 9, Ubuntu 22.04** 기본값 |

```
cgroup v1 구조 (컨트롤러별 분리)     cgroup v2 구조 (단일 통합)
┌──────┐ ┌──────┐ ┌──────┐          ┌──────────────────────┐
│ cpu  │ │memory│ │blkio │          │   unified hierarchy   │
│  /   │ │  /   │ │  /   │          │   /                   │
│ ├─A  │ │ ├─A  │ │ ├─B  │  ←비일관  │   ├─A (cpu+mem+io)   │
│ └─B  │ │ └─C  │ │ └─A  │          │   ├─B (cpu+mem+io)   │
└──────┘ └──────┘ └──────┘          │   └─C (cpu+mem+io)   │
  A: cpu에만, B: cpu+blkio          └──────────────────────┘
  C: memory에만 → 혼란                모든 컨트롤러 일관된 계층
```

### cgroup v2 주요 컨트롤러

| 컨트롤러 | 파일 | 설명 |
|----------|------|------|
| **cpu** | `cpu.max` (quota period) | `"50000 100000"` → 100ms 중 50ms 사용 (50%) |
| | `cpu.weight` (1-10000) | 상대적 가중치 (기본 100) |
| **memory** | `memory.max` | hard limit (초과 시 OOM Kill) |
| | `memory.high` | soft limit (초과 시 throttle) |
| | `memory.min` | 보장 최소량 (reclaim 보호) |
| | `memory.low` | 최선 노력 보장 (압박 시 reclaim 가능) |
| **io** | `io.max` | 디바이스별 IOPS/BPS 제한 |
| | `io.weight` | 디바이스별 I/O 가중치 |
| **pids** | `pids.max` | 최대 프로세스(스레드) 수 |

### PSI (Pressure Stall Information)

cgroup v2에서만 지원되는 리소스 압박 모니터링. `/proc/pressure/` 또는 cgroup 내 `*.pressure` 파일로 확인.

```
# /proc/pressure/cpu 출력 예시
some avg10=4.67 avg60=2.33 avg300=1.18 total=123456789
full avg10=0.00 avg60=0.00 avg300=0.00 total=0

# some: 하나 이상의 태스크가 대기한 시간 비율
# full: 모든 태스크가 대기한 시간 비율 (CPU에는 없음)
```

---

### namespace (네임스페이스)

namespace는 프로세스가 볼 수 있는 시스템 리소스의 **범위를 격리**한다. 프로세스마다 "자기만의 시스템"처럼 보이게 만든다.

```
호스트 커널
┌─────────────────────────────────────────────┐
│                                              │
│  Container A                Container B      │
│  ┌────────────────┐       ┌────────────────┐│
│  │ PID NS: 1,2,3  │       │ PID NS: 1,2    ││
│  │ NET NS: eth0   │       │ NET NS: eth0   ││
│  │  172.17.0.2    │       │  172.17.0.3    ││
│  │ MNT NS: /      │       │ MNT NS: /      ││
│  │ UTS: app-a     │       │ UTS: app-b     ││
│  │ USER: root(0)  │       │ USER: root(0)  ││
│  └────────────────┘       └────────────────┘│
│                                              │
│  호스트에서 보면:                              │
│  PID 4521 (=Container A의 PID 1)            │
│  PID 4600 (=Container B의 PID 1)            │
└─────────────────────────────────────────────┘
```

### 8가지 namespace

| namespace | 격리 대상 | clone 플래그 | 컨테이너에서의 역할 |
|-----------|----------|-------------|---------------------|
| **pid** | 프로세스 ID 공간 | `CLONE_NEWPID` | 컨테이너 내부 PID 1 |
| **net** | 네트워크 스택(인터페이스, IP, 라우팅) | `CLONE_NEWNET` | 독립 IP, 포트 바인딩 |
| **mnt** | 마운트 포인트 | `CLONE_NEWNS` | 독립 파일시스템 뷰 |
| **uts** | 호스트명, 도메인명 | `CLONE_NEWUTS` | 컨테이너 호스트명 |
| **ipc** | System V IPC, POSIX MQ | `CLONE_NEWIPC` | 격리된 공유메모리 |
| **user** | UID/GID 매핑 | `CLONE_NEWUSER` | rootless 컨테이너 |
| **cgroup** | cgroup 루트 디렉토리 | `CLONE_NEWCGROUP` | cgroup 뷰 격리 |
| **time** | 시스템 부팅 시간, 모노토닉 시계 (5.6+) | `CLONE_NEWTIME` | 독립 시간 오프셋 |

### namespace + cgroup = 컨테이너

```
docker run --cpus=0.5 --memory=256m -p 8080:80 nginx

                            ┌─ namespace ──────────────────┐
                            │ PID NS: nginx = PID 1        │
"docker run" ───→ runc ───→ │ NET NS: veth pair + bridge   │
                            │ MNT NS: overlayfs mount      │
                            │ UTS NS: hostname = container  │
                            └──────────────────────────────┘
                            ┌─ cgroup ─────────────────────┐
                            │ cpu.max = "50000 100000"     │
                            │ memory.max = 268435456       │
                            │ pids.max = max               │
                            └──────────────────────────────┘
```

---

## 실전 예시

```bash
# === cgroup 관련 ===

# 현재 시스템의 cgroup 버전 확인
stat -fc %T /sys/fs/cgroup/
# "cgroup2fs" → v2,  "tmpfs" → v1

# 현재 프로세스의 cgroup 소속 확인
cat /proc/self/cgroup
# v2: "0::/user.slice/user-1000.slice/..."
# v1: "12:memory:/user.slice/..." (여러 줄)

# cgroup v2에서 리소스 제한 설정 (root 권한)
mkdir -p /sys/fs/cgroup/my-test
echo "50000 100000" > /sys/fs/cgroup/my-test/cpu.max        # CPU 50%
echo $((256*1024*1024)) > /sys/fs/cgroup/my-test/memory.max # 메모리 256MB
echo 100 > /sys/fs/cgroup/my-test/pids.max                  # 최대 100개 프로세스
echo $$ > /sys/fs/cgroup/my-test/cgroup.procs               # 현재 셸 추가

# 현재 사용량 확인
cat /sys/fs/cgroup/my-test/cpu.stat
cat /sys/fs/cgroup/my-test/memory.current
cat /sys/fs/cgroup/my-test/memory.stat

# PSI 확인 (cgroup v2)
cat /proc/pressure/cpu
cat /proc/pressure/memory
cat /proc/pressure/io

# Docker 컨테이너의 cgroup 경로 확인
docker run -d --name test --cpus=0.5 --memory=256m nginx
CID=$(docker inspect --format '{{.Id}}' test)
cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/cpu.max
cat /sys/fs/cgroup/system.slice/docker-${CID}.scope/memory.max

# K8s Pod의 cgroup 확인 (노드에서)
# QoS별 경로: kubepods-guaranteed / kubepods-burstable / kubepods-besteffort
cat /sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<UID>.slice/memory.max

# === namespace 관련 ===

# 현재 프로세스의 namespace 확인
ls -la /proc/self/ns/

# 시스템 전체 namespace 목록
lsns

# 새 namespace로 격리된 셸 실행
unshare --pid --fork --mount-proc /bin/bash
# → ps aux 하면 PID 1이 bash

# 네트워크 namespace 생성 및 사용
ip netns add test-ns
ip netns exec test-ns ip addr                  # lo만 보임
ip netns exec test-ns ip link set lo up
ip netns del test-ns

# Docker 컨테이너의 namespace에 진입
CPID=$(docker inspect --format '{{.State.Pid}}' test)
nsenter -t $CPID -p -n -m /bin/bash            # PID, NET, MNT namespace 진입
ls -la /proc/$CPID/ns/                          # namespace inode 비교

# 두 컨테이너가 같은 namespace를 공유하는지 확인
readlink /proc/<PID1>/ns/net
readlink /proc/<PID2>/ns/net
# 같은 inode → 같은 network namespace (K8s Pod 내 컨테이너들)
```

---

## 면접 Q&A

### Q: cgroup과 namespace의 차이를 설명하고, 컨테이너와 어떻게 연결되나요?

**30초 답변**:
cgroup은 리소스를 **얼마나** 사용할 수 있는지 제한하고, namespace는 **무엇을** 볼 수 있는지 격리합니다. 컨테이너는 이 두 기술 위에 layered filesystem을 결합한 것입니다.

**2분 답변**:
cgroup은 CPU, 메모리, I/O, PID 수 등의 리소스 사용량을 그룹 단위로 제한합니다. Docker의 `--cpus=0.5`는 cgroup의 `cpu.max`에 매핑되고, `--memory=256m`은 `memory.max`에 매핑됩니다. namespace는 PID, 네트워크, 마운트, 호스트명 등 시스템 리소스의 가시성을 격리합니다. 컨테이너 내부에서 PID 1로 보이는 것은 PID namespace 덕분이고, 독립 IP를 가지는 것은 network namespace 덕분입니다. 컨테이너 런타임(runc)은 `clone()` 시스템 콜로 namespace를 생성하고, cgroup 디렉토리를 만들어 리소스를 제한합니다. Kubernetes에서 같은 Pod 내 컨테이너들은 network namespace를 공유하여 localhost로 통신하고, 각자의 PID namespace는 분리됩니다(shareProcessNamespace 설정으로 변경 가능).

**경험 연결**:
온프레미스에서 물리 서버의 CPU affinity와 메모리 제한을 직접 설정하며 프로세스별 리소스를 관리한 경험이 있습니다. 이 경험이 cgroup의 동작 원리를 이해하는 기반이 되었고, Kubernetes의 requests/limits가 결국 cgroup 파일에 값을 쓰는 것임을 자연스럽게 이해할 수 있었습니다.

**주의**:
"컨테이너는 경량 VM"이라고 답하면 감점. 컨테이너는 VM이 아니라 **커널을 공유하는 프로세스 격리 기술**입니다.

### Q: cgroup v1과 v2의 차이, v2로 전환해야 하는 이유는?

**30초 답변**:
v1은 컨트롤러마다 별도 계층이라 프로세스가 분산 배치되어 관리가 복잡하고, v2는 단일 통합 계층으로 일관된 관리가 가능합니다. PSI, MemoryQoS, 안전한 위임 등 v2 전용 기능이 있어 전환이 권장됩니다.

**2분 답변**:
cgroup v1의 근본 문제는 CPU, memory, blkio 등 각 컨트롤러가 독립된 계층(hierarchy)을 가져서 프로세스 A가 cpu 계층에서는 그룹 X에, memory 계층에서는 그룹 Y에 속할 수 있다는 것입니다. 이로 인해 리소스 관리가 비일관적이었습니다. v2는 단일 통합 계층에서 모든 컨트롤러를 관리하여 이 문제를 해결했습니다. v2 전용 기능으로는 PSI(Pressure Stall Information)로 리소스 압박 정도를 수치화하여 모니터링할 수 있고, memory.low/min으로 세밀한 메모리 QoS를 지원하며, 안전한 위임(delegation)으로 비특권 사용자에게 하위 트리를 위임할 수 있습니다. Kubernetes 1.25에서 cgroup v2가 GA되었고, MemoryQoS 기능이 memory.min으로 guaranteed 클래스의 메모리를 보호합니다. RHEL 9과 Ubuntu 22.04가 기본 v2이므로 신규 클러스터는 자연스럽게 v2를 사용합니다.

**경험 연결**:
인프라 운영 시 RHEL 7/8에서는 cgroup v1이 기본이었고, OS 업그레이드와 함께 v2로 전환하는 과정을 경험했습니다. 전환 시 Docker 버전 호환성과 systemd 설정 변경이 필요했습니다.

**주의**:
실제 면접에서는 "현재 운영 중인 시스템이 v1인지 v2인지 확인하는 방법"도 물어볼 수 있으므로, `stat -fc %T /sys/fs/cgroup/` 명령을 기억하세요.

### Q: Kubernetes Pod 내 컨테이너들은 어떤 namespace를 공유하나요?

**30초 답변**:
같은 Pod의 컨테이너들은 network namespace와 IPC namespace를 공유합니다. 따라서 localhost로 통신 가능하고, 포트 충돌에 주의해야 합니다. PID namespace는 기본적으로 분리되지만 `shareProcessNamespace`로 공유할 수 있습니다.

**2분 답변**:
Kubernetes Pod는 pause 컨테이너(infra container)가 먼저 생성되어 namespace를 만들고, 이후 앱 컨테이너들이 해당 namespace에 합류합니다. 공유되는 namespace: (1) **network** - 같은 IP, 같은 포트 공간, localhost 통신 가능, (2) **IPC** - 공유 메모리(shm)와 세마포어 공유, (3) **UTS** - 같은 호스트명. 분리되는 namespace: (1) **PID** - 기본 분리, `shareProcessNamespace: true`로 공유 가능, (2) **mount** - 각 컨테이너 독립 파일시스템 (volume mount로 공유 가능), (3) **user** - 각 컨테이너 독립 UID/GID. 사이드카 패턴(로그 수집, 프록시)이 가능한 이유가 바로 이 namespace 공유 때문입니다. Envoy 사이드카가 같은 network namespace에서 트래픽을 가로채는 것이 대표적 예입니다.

**경험 연결**:
온프레미스에서 하나의 서버에서 여러 서비스를 포트로 구분하여 운영한 경험이 있는데, Pod의 네트워크 공유가 이와 유사한 개념입니다. 다만 namespace 격리 덕분에 서로의 파일시스템은 볼 수 없어 보안이 더 강합니다.

**주의**:
"Pod은 하나의 컨테이너"라고 혼동하지 마세요. Pod은 namespace를 공유하는 컨테이너 **그룹**이며, pause 컨테이너가 namespace의 생명주기를 관리합니다.

---

## Allganize 맥락

- **K8s cgroup v2 + MemoryQoS**: LLM 추론 Pod에 guaranteed QoS를 설정하여 GPU 서버의 메모리를 보호하는 것이 중요
- **PSI 모니터링**: cgroup v2의 PSI 메트릭을 Prometheus로 수집하여 리소스 압박을 사전에 감지
- **사이드카 패턴**: Alli 서비스에서 Envoy 프록시, 로그 수집기(Fluent Bit) 등 사이드카와의 네트워크 namespace 공유 활용
- **namespace 보안**: user namespace를 활용한 rootless 컨테이너로 AI 모델 서빙의 보안 강화

---
**핵심 키워드**: `cgroup-v2` `namespace` `PSI` `memory.max` `cpu.max` `PID-namespace` `network-namespace` `pause-container`
