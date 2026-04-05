# 프로세스와 스레드 (Process & Thread)

> **TL;DR**
> 1. Linux 프로세스는 **fork/exec** 2단계 모델로 생성되며, Copy-on-Write로 효율적으로 메모리를 관리한다.
> 2. 좀비(zombie)와 고아(orphan) 프로세스는 장기 운영 시스템에서 PID 고갈과 리소스 누수의 원인이 된다.
> 3. 시그널(signal)은 프로세스 간 비동기 통신 메커니즘이며, 컨테이너 환경에서 graceful shutdown의 핵심이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 프로세스 vs 스레드

Linux 커널은 프로세스와 스레드를 모두 `task_struct`로 관리한다. 스레드는 `clone()` 시스템 콜에 `CLONE_VM | CLONE_FILES | CLONE_FS` 플래그를 사용해 주소 공간을 공유하는 경량 프로세스(LWP)다.

```
프로세스 A (PID 100)              프로세스 B (PID 200)
┌──────────────────┐             ┌──────────────────┐
│  Code  │  Data   │             │  Code  │  Data   │
│  Stack │  Heap   │  ← 독립    │  Stack │  Heap   │
│  FD Table        │             │  FD Table        │
└──────────────────┘             └──────────────────┘

프로세스 C (PID 300) - 멀티스레드
┌──────────────────────────────────┐
│  Code (공유)  │  Data (공유)     │
│  Heap (공유)  │  FD Table (공유) │
├──────────┬──────────┬───────────┤
│ Thread 1 │ Thread 2 │ Thread 3  │
│ Stack    │ Stack    │ Stack     │ ← 스택만 독립
│ TID 300  │ TID 301  │ TID 302  │
└──────────┴──────────┴───────────┘
```

| 구분 | 프로세스 (Process) | 스레드 (Thread) |
|------|-------------------|-----------------|
| 메모리 공간 | **독립적** (가상 주소 공간 분리) | **공유** (힙, 코드, 데이터 공유) |
| 생성 비용 | 높음 (`fork` → 페이지 테이블 복사) | 낮음 (`clone` → 주소 공간 공유) |
| 통신 | IPC 필요 (pipe, socket, shm) | 직접 메모리 접근 (동기화 필요) |
| 안정성 | 하나 죽어도 다른 프로세스 무관 | 하나 죽으면 전체 프로세스 종료 |
| 컨텍스트 스위칭 | 비용 높음 (TLB flush) | 비용 낮음 (같은 주소 공간) |

### fork/exec 모델

```
 bash (PID 1000)
   │
   ├─ fork() ────→ bash 복사본 (PID 1001)   [COW: 페이지 테이블만 복사]
   │                    │
   │                    └─ exec("/bin/ls") ──→ ls (PID 1001)  [메모리 교체]
   │                                              │
   │                                              └─ exit(0)
   │                                                   │
   └─ wait(&status) ←─────────────────────────────────┘  [종료 코드 수거]
```

- **fork()**: 부모 프로세스를 복제. COW(Copy-on-Write)로 실제 메모리 복사는 쓰기 시점까지 지연
- **vfork()**: exec 직전에 사용하는 최적화 버전. 부모를 블록하고 자식이 주소 공간을 빌려 씀
- **exec()**: 현재 프로세스의 메모리를 새 프로그램으로 교체. PID는 유지
- **clone()**: fork의 일반화 버전. 플래그로 공유할 리소스를 세밀하게 제어

### 프로세스 상태 머신

```
                    fork()
  [Created] ──────────────→ [Ready / Runnable (R)]
                                  │       ↑
                      스케줄러 ↓       │ preempt / wake
                             [Running (R)]
                              │    │    │
                    I/O wait ↓    │    ↓ exit()
              [Sleeping (S/D)]    │  [Zombie (Z)]
                                  │       │
                          SIGSTOP ↓       │ parent wait()
                          [Stopped (T)]   [Removed]
```

| 상태 | 코드 | 설명 | kill -9 가능? |
|------|------|------|--------------|
| Running/Runnable | R | CPU 실행 중 또는 run queue 대기 | O |
| Interruptible Sleep | S | 이벤트 대기, 시그널 수신 가능 | O |
| Uninterruptible Sleep | D | 커널 I/O 대기, 시그널 무시 | **X** |
| Zombie | Z | 종료됨, 부모의 wait() 대기 | X (이미 죽음) |
| Stopped | T | SIGSTOP/SIGTSTP로 정지 | O |
| Dead | X | 최종 상태, 곧 제거 | - |

### 좀비(Zombie) 프로세스

자식이 `exit()`했지만 부모가 `wait()`를 호출하지 않아 프로세스 테이블 엔트리가 남아있는 상태다. 메모리는 해제되었지만 **PID 슬롯**을 차지한다.

```
부모 (PID 500, wait() 안 함)
  │
  └── 자식 (PID 501) ──→ exit() ──→ [Z] 좀비 상태
                                      │
                            부모가 wait() 호출 시 → 완전 제거
                            부모가 죽으면 → init(PID 1)이 입양 후 수거
```

### 고아(Orphan) 프로세스

부모가 먼저 종료되면 자식은 **init(PID 1)** 또는 **systemd**에 재입양(reparent)된다. `prctl(PR_SET_CHILD_SUBREAPER)`로 subreaper를 지정하면 init 대신 특정 프로세스가 입양한다 (컨테이너 런타임이 이 방식 사용).

### 시그널(Signal) 체계

```
┌─────────────────────────────────────────────────────┐
│                    시그널 전달 흐름                    │
│                                                      │
│  kill(pid, sig) ──→ 커널 ──→ 대상 프로세스            │
│                      │                               │
│                      ├─ 기본 동작 (default action)    │
│                      ├─ 사용자 핸들러 (signal handler) │
│                      └─ 무시 (SIG_IGN)               │
│                                                      │
│  ※ SIGKILL(9), SIGSTOP(19)는 핸들링/무시 불가         │
└─────────────────────────────────────────────────────┘
```

| 시그널 | 번호 | 기본 동작 | 용도 |
|--------|------|----------|------|
| SIGHUP | 1 | 종료 | 데몬 설정 리로드 (nginx -s reload) |
| SIGINT | 2 | 종료 | Ctrl+C |
| SIGQUIT | 3 | 코어 덤프 | Ctrl+\\ |
| SIGKILL | 9 | **강제 종료** | 핸들링 불가, 최후 수단 |
| SIGTERM | 15 | 종료 | **graceful shutdown 기본 시그널** |
| SIGCHLD | 17 | 무시 | 자식 종료/정지 알림 |
| SIGSTOP | 19 | 정지 | 핸들링 불가 정지 |
| SIGUSR1/2 | 10/12 | 종료 | 사용자 정의 |

**컨테이너에서 시그널이 중요한 이유**: `docker stop`은 SIGTERM을 보내고 grace period(기본 10초) 후 SIGKILL을 보낸다. PID 1 프로세스가 시그널을 제대로 처리하지 않으면 항상 10초 대기 후 강제 종료된다.

---

## 실전 예시

```bash
# 프로세스 트리 확인 (부모-자식 관계)
ps auxf
pstree -p

# 특정 프로세스의 스레드 목록
ps -T -p <PID>
ls /proc/<PID>/task/

# /proc로 프로세스 상세 정보
cat /proc/<PID>/status | grep -E "^(Name|State|Pid|PPid|Threads|VmSize|VmRSS)"
cat /proc/<PID>/cmdline | tr '\0' ' '

# 좀비 프로세스 찾기
ps aux | awk '$8 ~ /^Z/ { print $2, $11 }'

# 좀비의 부모 찾기 및 처리
ps -o ppid= -p <ZOMBIE_PID>
kill -SIGCHLD <PARENT_PID>     # 부모에게 자식 수거 요청
kill -9 <PARENT_PID>            # 최후 수단: 부모 강제 종료

# 시그널 보내기
kill -SIGTERM <PID>             # graceful shutdown
kill -SIGHUP <PID>              # 설정 리로드
kill -0 <PID>                   # 프로세스 존재 여부만 확인 (시그널 안 보냄)

# PID 고갈 모니터링
cat /proc/sys/kernel/pid_max
ls -d /proc/[0-9]* | wc -l

# fork bomb 방지 (ulimit)
ulimit -u                       # 현재 사용자 최대 프로세스 수
cat /etc/security/limits.conf   # 영구 설정

# strace로 fork/exec 추적
strace -f -e trace=clone,execve bash -c "ls"

# D 상태 프로세스 확인 (I/O 블록)
ps aux | awk '$8 == "D" { print }'
cat /proc/<PID>/wchan           # 어떤 커널 함수에서 대기 중인지
```

### Copy-on-Write 동작 확인

```bash
# 부모/자식 메모리 공유 확인
python3 -c "
import os
data = bytearray(100 * 1024 * 1024)  # 100MB 할당
pid = os.fork()
if pid == 0:
    # 자식: 쓰기 전에는 물리 메모리 공유 (COW)
    import time; time.sleep(10)
    data[0] = 1   # 쓰기 발생 → 페이지 복사
    time.sleep(10)
else:
    os.wait()
"
# 별도 터미널에서: watch -n1 'ps -o pid,rss,vsz -p <PARENT_PID>,<CHILD_PID>'
```

---

## 면접 Q&A

### Q: fork()와 exec()의 차이를 설명하고, 왜 2단계로 나뉘어 있나요?

**30초 답변**:
fork()는 현재 프로세스를 복제하여 자식을 만들고, exec()는 프로세스의 메모리를 새 프로그램으로 교체합니다. 2단계로 나뉜 이유는 fork와 exec 사이에 파일 디스크립터 조작, 환경변수 설정 등 준비 작업을 할 수 있기 때문입니다.

**2분 답변**:
Unix 철학의 핵심 설계입니다. fork()는 부모 프로세스의 주소 공간, 파일 디스크립터, 환경변수를 모두 복제한 자식을 만듭니다. 이때 COW(Copy-on-Write)를 사용해 실제 메모리 복사는 쓰기가 발생할 때까지 지연합니다. exec()는 현재 프로세스의 메모리를 새 프로그램으로 완전히 교체하되 PID와 열린 파일 디스크립터(close-on-exec 제외)는 유지합니다. 이 두 단계 사이에서 shell은 파이프(`dup2`), 리다이렉션(`open` + `dup2`), 환경변수 설정 등을 수행합니다. 예를 들어 `ls | grep foo`에서 shell은 fork 후 exec 전에 pipe의 read/write end를 적절히 연결합니다. Windows의 `CreateProcess()`는 이를 하나로 합쳤지만, Unix 방식이 더 유연합니다.

**경험 연결**:
폐쇄망 환경에서 장기 운영 서버의 데몬 프로세스를 관리할 때, fork/exec 모델을 이해하고 있어야 프로세스가 왜 특정 파일 디스크립터를 물고 있는지, 왜 환경변수가 상속되는지 파악할 수 있었습니다. 특히 로그 파일 rotation 시 서비스가 옛 파일 디스크립터를 물고 있는 문제를 진단한 경험이 있습니다.

**주의**:
면접에서 "fork는 프로세스 생성, exec는 프로그램 실행"으로만 답하면 피상적입니다. COW, 파일 디스크립터 상속, 2단계 분리의 설계 이유를 함께 설명해야 합니다.

### Q: 좀비 프로세스와 고아 프로세스의 차이, 그리고 컨테이너 환경에서의 영향은?

**30초 답변**:
좀비는 자식이 종료됐지만 부모가 wait()를 안 해서 프로세스 테이블에 남아있는 상태이고, 고아는 부모가 먼저 죽어서 init에 입양된 프로세스입니다. 컨테이너에서는 PID 1이 시그널 핸들링과 좀비 수거를 제대로 해야 합니다.

**2분 답변**:
좀비 프로세스는 메모리는 해제되었지만 PID 슬롯과 종료 상태 정보가 프로세스 테이블에 남아 있습니다. 대량 발생 시 `/proc/sys/kernel/pid_max`에 도달하여 새 프로세스 생성이 불가능해집니다. 고아 프로세스는 init(PID 1)에 재입양되어 init이 wait()를 호출하므로 자동 수거됩니다. 컨테이너에서는 애플리케이션이 PID 1로 실행되는데, 일반 애플리케이션은 SIGCHLD 핸들링이나 wait()를 구현하지 않아 좀비가 쌓일 수 있습니다. 이를 해결하기 위해 `tini`나 `dumb-init` 같은 경량 init 프로세스를 ENTRYPOINT로 사용하거나, Docker의 `--init` 플래그를 사용합니다. Kubernetes에서는 `shareProcessNamespace: true`를 설정하면 pause 컨테이너가 PID 1 역할을 합니다.

**경험 연결**:
온프레미스 환경에서 수개월간 재부팅 없이 운영되는 서버에서 좀비 프로세스가 수백 개 쌓인 경험이 있습니다. 모니터링 스크립트로 좀비 프로세스 수를 추적하고, 원인이 되는 부모 프로세스의 시그널 핸들링을 수정했습니다.

**주의**:
"좀비는 kill -9로 죽이면 됩니다"라고 답하면 감점입니다. 좀비는 이미 죽은 상태이므로 시그널이 무의미하며, 부모에게 SIGCHLD를 보내거나 부모를 종료시켜야 합니다.

### Q: D 상태(Uninterruptible Sleep) 프로세스를 어떻게 처리하나요?

**30초 답변**:
D 상태는 커널 I/O 작업 완료를 기다리는 상태로, 시그널을 받지 않으므로 kill -9도 불가능합니다. 근본 원인인 I/O 문제(NFS 타임아웃, 디스크 장애 등)를 해결해야 합니다.

**2분 답변**:
D(Uninterruptible Sleep) 상태는 디스크 I/O나 NFS 같은 커널 코드 경로에서 데이터 일관성을 보장하기 위해 시그널 전달을 차단하는 상태입니다. 이 상태의 프로세스는 어떤 시그널도 받지 않으므로 강제 종료가 불가능합니다. Linux 2.6.25부터 `TASK_KILLABLE` 상태가 추가되어 일부 경우에 SIGKILL은 수신할 수 있게 되었습니다. 진단 방법은 `/proc/<PID>/wchan`으로 대기 중인 커널 함수를 확인하고, `dmesg`에서 I/O 에러를 확인합니다. 일반적 원인은 NFS 서버 무응답(`nfs_wait_bit_killable`), SAN/iSCSI 경로 장애, 물리 디스크 불량 섹터 등입니다. 해결은 I/O 계층의 근본 원인을 해결하는 것이며, 최악의 경우 재부팅이 필요합니다. NFS의 경우 마운트 옵션에 `soft,timeo=30`을 사용하면 타임아웃 후 에러를 반환하도록 설정할 수 있습니다.

**경험 연결**:
폐쇄망 환경에서 NFS 스토리지 장애 시 D 상태 프로세스가 수십 개 발생한 경험이 있습니다. kill이 안 되어 당황했지만, NFS 서버의 네트워크 문제를 해결하자 모든 프로세스가 정상 복귀했습니다. 이후 NFS 마운트를 soft 옵션으로 변경하여 재발을 방지했습니다.

**주의**:
"재부팅하면 됩니다"만 답하지 말고, 근본 원인 분석 과정(wchan 확인, dmesg, I/O 계층 추적)을 설명하세요.

### Q: 컨테이너 환경에서 PID 1의 특수성은 무엇인가요?

**30초 답변**:
PID 1은 init 프로세스로서 좀비 수거(wait)와 시그널 전달의 책임을 집니다. 컨테이너에서 일반 앱이 PID 1로 실행되면 SIGTERM을 기본 무시하고, 좀비가 쌓이는 문제가 발생합니다.

**2분 답변**:
Linux에서 PID 1은 두 가지 특수성이 있습니다. 첫째, 등록하지 않은 시그널은 기본 동작이 무시(ignore)됩니다. 일반 프로세스의 SIGTERM 기본 동작은 종료지만, PID 1에서는 명시적으로 핸들러를 등록해야 합니다. 둘째, 고아 프로세스의 부모가 되어 wait()로 좀비를 수거해야 합니다. 컨테이너에서 이 문제를 해결하는 방법: (1) `tini`를 ENTRYPOINT로 사용 (`ENTRYPOINT ["/tini", "--", "app"]`), (2) Docker `--init` 플래그, (3) Dockerfile에서 `exec` 형식 사용하여 shell wrapping 방지 (`CMD ["app"]` vs `CMD app`), (4) 앱 자체에서 시그널 핸들링 구현. Kubernetes에서는 `terminationGracePeriodSeconds`와 함께 preStop hook을 활용합니다.

**경험 연결**:
온프레미스에서 shell script로 감싼 Java 애플리케이션이 SIGTERM을 받지 못해 항상 강제 종료되는 문제를 경험했습니다. shell이 PID 1이 되면서 exec를 사용하지 않아 시그널이 자식 Java 프로세스로 전달되지 않았고, exec를 추가하여 해결했습니다.

**주의**:
Dockerfile에서 `CMD app.sh`(shell 형식)와 `CMD ["app.sh"]`(exec 형식)의 차이를 혼동하지 마세요. shell 형식은 `/bin/sh -c app.sh`로 실행되어 sh가 PID 1이 됩니다.

---

## Allganize 맥락

- **AI/LLM 서비스 Pod**: LLM 추론 프로세스는 GPU를 사용하며 멀티스레드로 동작. 프로세스 모니터링과 graceful shutdown이 모델 로딩 시간(수분)을 고려할 때 매우 중요
- **Kubernetes terminationGracePeriodSeconds**: LLM 모델 언로드 시간을 고려한 충분한 grace period 설정 필요
- **tini/dumb-init**: Allganize의 컨테이너 이미지에서 PID 1 문제를 방지하기 위한 init 프로세스 사용 권장
- **좀비 프로세스 모니터링**: 장기 운영 Pod에서 좀비 누적 방지를 위한 모니터링 메트릭 설정

---
**핵심 키워드**: `fork/exec` `COW` `zombie/orphan` `signal` `PID-1` `tini` `SIGTERM` `graceful-shutdown`
