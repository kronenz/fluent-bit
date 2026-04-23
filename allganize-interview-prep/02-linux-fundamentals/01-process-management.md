# 01. 프로세스 관리 (Process Management)

> **TL;DR**
> 1. 프로세스(Process)는 실행 중인 프로그램이며, **fork/exec** 모델로 생성되고, 좀비(zombie)/고아(orphan) 상태를 이해해야 한다.
> 2. **cgroup**은 리소스 제한, **namespace**는 격리를 담당하며, 이 둘이 합쳐져 컨테이너가 된다.
> 3. 폐쇄망/온프레미스 환경에서 직접 리소스를 관리한 경험은 클라우드 네이티브 이해의 강력한 기반이 된다.

---

## 1. 프로세스와 스레드 (Process & Thread)

### 핵심 개념

**프로세스(Process)**는 커널이 관리하는 실행 단위다. 각 프로세스는 고유한 **PID**, 독립된 메모리 공간(가상 주소 공간), 파일 디스크립터 테이블을 가진다.

**스레드(Thread)**는 프로세스 내에서 실행 흐름을 공유하는 경량 단위다. Linux에서는 **clone()** 시스템 콜로 생성되며, 프로세스와 동일한 `task_struct`로 관리된다. 이것이 Linux에서 "lightweight process"라 불리는 이유다.

| 구분 | 프로세스 (Process) | 스레드 (Thread) |
|------|-------------------|-----------------|
| 메모리 공간 | **독립적** | **공유** |
| 생성 비용 | 높음 (fork) | 낮음 (clone) |
| 통신 | IPC 필요 | 직접 메모리 접근 |
| 안정성 | 하나가 죽어도 다른 프로세스 영향 없음 | 하나가 죽으면 전체 프로세스 종료 |

### 실전 명령어

```bash
# 현재 시스템의 모든 프로세스 트리 확인
ps auxf

# 특정 프로세스의 스레드 확인
ps -T -p <PID>

# /proc 파일시스템으로 프로세스 상세 정보 확인
ls -la /proc/<PID>/
cat /proc/<PID>/status | grep -E "Pid|Threads|VmSize|VmRSS"

# 스레드 수 확인
ls /proc/<PID>/task/ | wc -l
```

---

## 2. 프로세스 라이프사이클 (Process Lifecycle)

### fork/exec 모델

Linux의 프로세스 생성은 **2단계**로 이루어진다.

1. **fork()** : 부모 프로세스를 복제하여 자식 프로세스를 생성한다. 이때 **Copy-on-Write(COW)** 기법으로 실제 메모리 복사는 쓰기가 발생할 때까지 지연된다.
2. **exec()** : 자식 프로세스의 메모리 공간을 새로운 프로그램으로 교체한다.

```
부모 프로세스 (bash)
    │
    ├── fork() → 자식 프로세스 (bash 복사본)
    │                │
    │                └── exec("/usr/bin/ls") → ls 프로세스로 변환
    │
    └── wait() → 자식 종료 대기
```

### 프로세스 상태 (Process States)

```
   ┌─────────┐    fork()    ┌──────────┐
   │ Created │ ──────────→ │ Ready(R) │
   └─────────┘             └──────────┘
                               │  ↑
                    스케줄링 ↓  │ 선점(preempt)
                           ┌──────────┐
                           │Running(R)│
                           └──────────┘
                             │      │
                  I/O 대기 ↓      │ exit()
                  ┌──────────┐  ┌──────────┐
                  │Sleeping  │  │Zombie (Z)│
                  │(S or D)  │  └──────────┘
                  └──────────┘       │
                                     │ wait()
                                ┌──────────┐
                                │ Removed  │
                                └──────────┘
```

- **R (Running/Runnable)** : CPU에서 실행 중이거나 실행 대기
- **S (Interruptible Sleep)** : 이벤트 대기 중, 시그널로 깨울 수 있음
- **D (Uninterruptible Sleep)** : I/O 대기 중, 시그널로 깨울 수 없음 (kill -9도 안 됨)
- **Z (Zombie)** : 종료되었지만 부모가 아직 wait()를 호출하지 않은 상태
- **T (Stopped)** : SIGSTOP이나 디버거에 의해 정지된 상태

### 좀비 프로세스 (Zombie Process)와 고아 프로세스 (Orphan Process)

**좀비 프로세스**는 자식이 종료되었지만 부모가 `wait()`를 호출하지 않아 프로세스 테이블에 남아 있는 상태다. 메모리는 해제되지만 **PID 슬롯을 차지**한다.

**고아 프로세스**는 부모가 먼저 종료되어 **init(PID 1) 또는 systemd가 입양**하는 프로세스다.

```bash
# 좀비 프로세스 찾기
ps aux | awk '$8 ~ /Z/ {print $2, $11}'

# 좀비 프로세스의 부모 찾기
ps -o ppid= -p <ZOMBIE_PID>

# 좀비 프로세스 정리: 부모 프로세스에 SIGCHLD 보내기
kill -SIGCHLD <PARENT_PID>

# 그래도 안 되면 부모 프로세스 종료
kill -9 <PARENT_PID>
```

> **폐쇄망 경험 연결**: 온프레미스 환경에서 장기 운영되는 서버에서 좀비 프로세스가 쌓이면 PID 고갈이 발생할 수 있다. `pid_max` 값을 확인하고 주기적으로 모니터링하는 것이 중요하다.

```bash
# 시스템 최대 PID 확인
cat /proc/sys/kernel/pid_max

# 현재 사용 중인 프로세스 수
ls -d /proc/[0-9]* | wc -l
```

---

## 3. cgroup (Control Groups)

### 핵심 개념

**cgroup**은 프로세스 그룹에 대해 **리소스 사용량을 제한, 우선순위 지정, 감시, 제어**하는 Linux 커널 기능이다.

### cgroup v1 vs cgroup v2

| 구분 | cgroup v1 | cgroup v2 |
|------|-----------|-----------|
| 구조 | 컨트롤러별 **개별 계층** (hierarchy) | **단일 통합 계층** |
| 마운트 | `/sys/fs/cgroup/<controller>/` | `/sys/fs/cgroup/` |
| 위임 | 복잡하고 보안 문제 | 안전한 위임 지원 |
| PSI | 미지원 | **Pressure Stall Information** 지원 |
| 쿠버네티스 | 기본값 (구버전) | 1.25+ 정식 지원 |

```bash
# 현재 시스템의 cgroup 버전 확인
stat -fc %T /sys/fs/cgroup/
# "cgroup2fs" → v2, "tmpfs" → v1

# cgroup v2 마운트 확인
mount | grep cgroup

# 현재 프로세스의 cgroup 확인
cat /proc/self/cgroup
```

### CPU 리소스 제한

```bash
# cgroup v2에서 CPU 제한 설정
mkdir -p /sys/fs/cgroup/my-app

# CPU를 50%로 제한 (100ms 주기 중 50ms 사용)
echo "50000 100000" > /sys/fs/cgroup/my-app/cpu.max

# 프로세스를 cgroup에 추가
echo <PID> > /sys/fs/cgroup/my-app/cgroup.procs

# CPU 사용량 통계 확인
cat /sys/fs/cgroup/my-app/cpu.stat
```

### Memory 리소스 제한

```bash
# 메모리 제한 설정 (512MB)
echo $((512 * 1024 * 1024)) > /sys/fs/cgroup/my-app/memory.max

# soft limit 설정 (256MB)
echo $((256 * 1024 * 1024)) > /sys/fs/cgroup/my-app/memory.high

# 메모리 사용량 확인
cat /sys/fs/cgroup/my-app/memory.current
cat /sys/fs/cgroup/my-app/memory.stat
```

> **폐쇄망 경험 연결**: 에어갭 환경에서는 클라우드의 오토스케일링이 불가능하므로, cgroup을 통한 **정밀한 리소스 제어**가 더욱 중요하다. 물리 서버의 리소스를 직접 분배해본 경험은 쿠버네티스의 requests/limits 설정을 이해하는 데 큰 도움이 된다.

---

## 4. namespace (네임스페이스)

### 핵심 개념

**namespace**는 프로세스가 볼 수 있는 시스템 리소스의 **범위를 격리**하는 커널 기능이다. 프로세스마다 "자기만의 시스템"처럼 보이게 만든다.

### 8가지 namespace 종류

| namespace | 격리 대상 | 플래그 | 컨테이너에서의 역할 |
|-----------|----------|--------|---------------------|
| **pid** | 프로세스 ID | `CLONE_NEWPID` | 컨테이너 내부 PID 1 |
| **net** | 네트워크 스택 | `CLONE_NEWNET` | 독립 IP, 포트 |
| **mnt** | 마운트 포인트 | `CLONE_NEWNS` | 독립 파일시스템 뷰 |
| **uts** | 호스트명, 도메인명 | `CLONE_NEWUTS` | 컨테이너 호스트명 |
| **ipc** | IPC 리소스 | `CLONE_NEWIPC` | 독립 공유메모리, 세마포어 |
| **user** | UID/GID | `CLONE_NEWUSER` | rootless 컨테이너 |
| **cgroup** | cgroup 루트 디렉토리 | `CLONE_NEWCGROUP` | cgroup 뷰 격리 |
| **time** | 시스템 시간 (5.6+) | `CLONE_NEWTIME` | 독립 시간 설정 |

### 실전 명령어

```bash
# 현재 프로세스의 namespace 확인
ls -la /proc/self/ns/

# 특정 프로세스의 namespace 확인
lsns -p <PID>

# 전체 namespace 목록
lsns

# 새 namespace로 프로세스 실행 (pid + net + mnt 격리)
unshare --pid --net --mount --fork /bin/bash

# 특정 namespace에 진입
nsenter -t <PID> -p -n -m /bin/bash

# Docker 컨테이너의 namespace 확인
CONTAINER_PID=$(docker inspect --format '{{.State.Pid}}' <container_name>)
ls -la /proc/$CONTAINER_PID/ns/
```

### namespace로 간이 컨테이너 만들기

```bash
# 1) 격리된 환경 생성
unshare --pid --fork --mount-proc /bin/bash

# 2) 격리 확인: PID 1이 bash
ps aux
# PID 1 = bash (호스트에서는 다른 PID)

# 3) 호스트명 격리
unshare --uts /bin/bash
hostname my-container
hostname  # → my-container (호스트에는 영향 없음)
```

---

## 5. 컨테이너와의 연결점

**컨테이너 = namespace + cgroup + layered filesystem**

```
┌───────────────────────────────────────┐
│            컨테이너 런타임              │
│  (Docker, containerd, CRI-O)          │
├───────────────────────────────────────┤
│  namespace (격리)  │  cgroup (리소스)   │
│  - pid namespace   │  - cpu.max        │
│  - net namespace   │  - memory.max     │
│  - mnt namespace   │  - io.max         │
│  - uts namespace   │  - pids.max       │
│  - ipc namespace   │                   │
│  - user namespace  │                   │
├───────────────────────────────────────┤
│  OverlayFS (파일시스템 레이어)          │
├───────────────────────────────────────┤
│           Linux Kernel                 │
└───────────────────────────────────────┘
```

```bash
# Docker 컨테이너의 cgroup 확인
docker run -d --name test --cpus="0.5" --memory="256m" nginx
CONTAINER_ID=$(docker inspect --format '{{.Id}}' test)

# cgroup v2 경로 확인
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/cpu.max
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/memory.max

# 쿠버네티스 Pod의 cgroup 확인 (노드에서)
cat /sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<UID>.slice/memory.max
```

> **폐쇄망 경험 연결**: 온프레미스에서 물리 서버를 직접 관리하며 프로세스, 리소스, 네트워크를 다뤄본 경험은 컨테이너의 내부 동작을 이해하는 데 **결정적인 강점**이다. 클라우드에서 추상화된 레이어를 경험한 사람은 "왜 이렇게 동작하는지" 설명하기 어렵지만, 바닥부터 올라온 사람은 근본 원인을 설명할 수 있다.

---

## 면접 Q&A

### Q1. "프로세스와 스레드의 차이를 설명해주세요."

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "프로세스는 독립된 메모리 공간을 가지는 실행 단위이고, 스레드는 같은 프로세스 내에서 메모리를 공유하는 실행 흐름입니다. Linux에서는 둘 다 `task_struct`로 관리되며, 스레드는 `clone()` 시스템 콜에 `CLONE_VM` 플래그를 사용해 메모리 공간을 공유하는 방식으로 구현됩니다. 그래서 Linux에서 스레드를 lightweight process라고 부릅니다."

### Q2. "좀비 프로세스가 무엇이고, 왜 문제가 되며, 어떻게 해결하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "좀비 프로세스는 자식 프로세스가 종료되었지만 부모가 `wait()`를 호출하지 않아 프로세스 테이블에 항목이 남아있는 상태입니다. 메모리는 이미 해제되었지만 PID 슬롯을 차지하므로, 대량 발생 시 PID 고갈로 새 프로세스를 생성할 수 없게 됩니다. 해결 방법은 부모 프로세스에 SIGCHLD를 보내거나, 부모를 종료시켜 init이 입양하게 하는 것입니다. 실무에서는 폐쇄망 장기 운영 서버에서 이 문제를 경험했고, 모니터링 스크립트를 만들어 사전에 감지했습니다."

### Q3. "cgroup과 namespace의 차이를 설명하고, 컨테이너와 어떻게 연결되나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "cgroup은 리소스를 **얼마나** 사용할 수 있는지 제한하고, namespace는 **무엇을** 볼 수 있는지 격리합니다. 컨테이너는 이 두 기술의 조합입니다. 예를 들어, Docker에서 `--cpus=0.5 --memory=256m`은 cgroup의 `cpu.max`와 `memory.max`에 매핑되고, 컨테이너 내부에서 PID 1로 보이는 것은 pid namespace 덕분입니다. 온프레미스에서 물리 서버의 리소스를 직접 분배했던 경험이 쿠버네티스의 requests/limits를 이해하는 데 큰 도움이 되었습니다."

### Q4. "cgroup v1과 v2의 차이를 아시나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "가장 큰 차이는 구조입니다. v1은 CPU, memory 등 각 컨트롤러가 **개별 계층**을 가지고, v2는 **단일 통합 계층**으로 관리됩니다. v2는 PSI(Pressure Stall Information)를 지원하여 리소스 압박 상황을 더 정밀하게 모니터링할 수 있고, 안전한 위임(delegation)을 지원합니다. 쿠버네티스 1.25부터 cgroup v2를 정식 지원하며, 최신 배포판(Ubuntu 22.04, RHEL 9)은 기본값이 v2입니다."

### Q5. "D 상태(Uninterruptible Sleep) 프로세스를 kill할 수 없는 이유는?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "D 상태는 디스크 I/O 등 커널 영역의 작업이 완료될 때까지 시그널을 받지 않도록 설계된 상태입니다. `kill -9`도 시그널이므로 전달되지 않습니다. 보통 NFS 마운트가 응답하지 않거나, 디스크 장애 상황에서 발생합니다. 폐쇄망 환경에서 NFS 스토리지 장애 시 이 상태의 프로세스가 대량 발생하는 것을 경험했고, 근본 원인인 스토리지 문제를 해결해야 했습니다."

---

**Tags**: `#프로세스_라이프사이클` `#cgroup_v2` `#namespace` `#fork_exec` `#컨테이너_내부구조`
