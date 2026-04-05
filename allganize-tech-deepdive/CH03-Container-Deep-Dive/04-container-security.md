# 컨테이너 보안 (Container Security)

> **TL;DR**
> - 컨테이너 보안은 **rootless 실행, Linux capabilities 제한, seccomp, AppArmor/SELinux** 네 계층으로 구성된다.
> - **root 컨테이너는 커널 취약점 하나로 호스트 탈출**이 가능하므로, 비루트(non-root) 실행이 최소 요건이다.
> - Kubernetes의 **Pod Security Standards(PSS)**와 **SecurityContext**로 클러스터 수준 보안 정책을 강제한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### 1. 컨테이너 보안 계층 모델

컨테이너 보안은 여러 계층에서 방어하는 **Defense-in-Depth** 전략이다.

```
┌─────────────────────────────────────────────────┐
│  Layer 5: Admission Control (OPA/Kyverno)       │
│  → 정책 위반 Pod 배포 차단                        │
├─────────────────────────────────────────────────┤
│  Layer 4: Network Policy (Calico/Cilium)        │
│  → Pod 간 트래픽 제어                             │
├─────────────────────────────────────────────────┤
│  Layer 3: seccomp / AppArmor / SELinux          │
│  → 시스템콜/파일 접근 제한                        │
├─────────────────────────────────────────────────┤
│  Layer 2: Linux Capabilities                    │
│  → root 권한 세분화, 불필요 권한 제거             │
├─────────────────────────────────────────────────┤
│  Layer 1: Non-root User + Read-only FS          │
│  → 기본 실행 권한 최소화                          │
└─────────────────────────────────────────────────┘
```

### 2. Rootless 컨테이너

root(UID 0)로 컨테이너를 실행하면, 커널 취약점(예: CVE-2024-21626 runc 탈출)을 통해 **호스트 root 권한**을 획득할 수 있다. Rootless 실행은 이 위험을 원천 차단한다.

```
[Root 컨테이너 위험]
Container (root, UID 0)
    → 커널 취약점 악용
    → namespace 탈출
    → Host (root, UID 0)  ← 전체 시스템 장악

[Rootless 컨테이너]
Container (appuser, UID 1000)
    → 커널 취약점 악용 시도
    → namespace 탈출하더라도
    → Host (UID 1000)  ← 제한된 권한, 피해 최소화
```

**Dockerfile에서의 비루트 설정:**

```dockerfile
# 사용자 생성 및 전환
RUN groupadd -r app && useradd -r -g app -s /sbin/nologin app
# 필요한 디렉토리 권한 설정
RUN chown -R app:app /app
USER app

# 또는 숫자 UID 사용 (이미지에 사용자 없어도 동작)
USER 1000:1000
```

### 3. Linux Capabilities

전통적인 Unix 권한은 "root(전능) vs 일반 사용자(제한)" 이분법이다. Linux Capabilities는 root 권한을 **37개 이상의 세부 권한**으로 분리한다.

```
전통적 root 권한:
  ALL PRIVILEGES (위험!)

Capabilities로 세분화:
  CAP_NET_BIND_SERVICE  → 1024 미만 포트 바인딩
  CAP_NET_RAW           → raw socket 사용
  CAP_SYS_ADMIN         → mount, namespace 등 (거의 root)
  CAP_SYS_PTRACE        → 다른 프로세스 디버깅
  CAP_CHOWN             → 파일 소유자 변경
  CAP_DAC_OVERRIDE      → 파일 권한 무시
  CAP_SETUID/SETGID     → UID/GID 변경
  ...
```

**Docker 기본 Capabilities (허용):**

| Capability | 설명 |
|-----------|------|
| CAP_CHOWN | 파일 소유자 변경 |
| CAP_DAC_OVERRIDE | 파일 접근 권한 무시 |
| CAP_FSETID | setuid/setgid 비트 유지 |
| CAP_FOWNER | 파일 소유자 검사 무시 |
| CAP_MKNOD | 특수 파일 생성 |
| CAP_NET_RAW | raw socket |
| CAP_SETGID | GID 변경 |
| CAP_SETUID | UID 변경 |
| CAP_SETFCAP | 파일 capability 설정 |
| CAP_SETPCAP | 프로세스 capability 변경 |
| CAP_NET_BIND_SERVICE | 1024 미만 포트 바인딩 |
| CAP_SYS_CHROOT | chroot |
| CAP_KILL | 시그널 전송 |
| CAP_AUDIT_WRITE | 감사 로그 기록 |

**보안 강화: 모든 capability를 제거하고 필요한 것만 추가:**

```yaml
securityContext:
  capabilities:
    drop:
      - ALL           # 모든 capability 제거
    add:
      - NET_BIND_SERVICE  # 80/443 포트 필요 시만 추가
```

### 4. seccomp (Secure Computing Mode)

seccomp는 컨테이너가 호출할 수 있는 **시스템콜을 제한**한다. Linux 커널에는 300개 이상의 시스템콜이 있지만, 대부분의 애플리케이션은 40-70개만 사용한다.

```
[seccomp 없이]
Container → 모든 시스템콜 허용
  → mount(), ptrace(), reboot(), kexec_load() ...
  → 커널 공격 표면 넓음

[seccomp 적용]
Container → 허용 목록의 시스템콜만 가능
  → read(), write(), open(), close(), mmap() ...
  → 차단된 시스템콜 호출 시 → EPERM 또는 SIGKILL
```

**Docker 기본 seccomp 프로파일:**
약 44개의 위험 시스템콜을 차단한다 (mount, kexec_load, reboot, ptrace 등).

### 5. AppArmor / SELinux

| 항목 | AppArmor | SELinux |
|------|----------|---------|
| **방식** | 경로(path) 기반 접근 제어 | 레이블(label) 기반 접근 제어 |
| **복잡도** | 비교적 간단 | 복잡하지만 강력 |
| **기본 배포판** | Ubuntu, Debian, SUSE | RHEL, CentOS, Fedora |
| **컨테이너 지원** | Docker/K8s 기본 지원 | CRI-O/OpenShift 기본 |

```
[AppArmor 동작]
프로파일: "컨테이너는 /app/** 읽기만, /etc/passwd 접근 금지"
  → 컨테이너가 /etc/shadow 읽기 시도 → DENIED

[SELinux 동작]
레이블: container_t (컨테이너 프로세스)
  → container_t는 container_file_t 타입 파일만 접근 가능
  → 호스트의 sshd_exec_t 파일 접근 → DENIED
```

### 6. Kubernetes SecurityContext와 Pod Security Standards

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  securityContext:            # Pod 수준
    runAsNonRoot: true        # root 실행 금지
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault    # 기본 seccomp 프로파일
  containers:
  - name: app
    image: harbor.internal.corp/myapp:v1.0.0
    securityContext:          # 컨테이너 수준
      allowPrivilegeEscalation: false  # 권한 상승 금지
      readOnlyRootFilesystem: true     # 루트 FS 읽기 전용
      capabilities:
        drop: ["ALL"]         # 모든 capability 제거
    volumeMounts:
    - name: tmp
      mountPath: /tmp         # 쓰기 필요 시 emptyDir 마운트
  volumes:
  - name: tmp
    emptyDir: {}
```

**Pod Security Standards (PSS) -- 3단계:**

| 레벨 | 설명 | 제한 사항 |
|------|------|----------|
| **Privileged** | 제한 없음 | 시스템 컴포넌트용 |
| **Baseline** | 기본 보안 | hostNetwork, privileged, hostPID 금지 |
| **Restricted** | 강화 보안 | non-root 필수, capability drop ALL, readOnlyRootFS |

```bash
# 네임스페이스에 PSS 적용
kubectl label namespace production \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted
```

---

## 실전 예시

### Rootless Docker 설정

```bash
# Rootless Docker 설치 (Docker 20.10+)
dockerd-rootless-setuptool.sh install

# 확인
docker info | grep -i rootless
# rootless: true

# Rootless 모드에서는 Docker 데몬이 일반 사용자로 실행
# /var/run/docker.sock 대신 $XDG_RUNTIME_DIR/docker.sock 사용
```

### Capabilities 확인 및 테스트

```bash
# 컨테이너의 현재 capabilities 확인
docker run --rm alpine cat /proc/1/status | grep Cap
# CapPrm: 00000000a80425fb  (허용된 capability 비트마스크)

# 비트마스크 해석
docker run --rm alpine sh -c "apk add -q libcap && capsh --decode=00000000a80425fb"

# 모든 capability 제거 후 실행
docker run --rm --cap-drop=ALL alpine ping -c1 8.8.8.8
# ping: permission denied (CAP_NET_RAW 없음)

# 필요한 것만 추가
docker run --rm --cap-drop=ALL --cap-add=NET_RAW alpine ping -c1 8.8.8.8
# PING 8.8.8.8: 56 data bytes ...

# 1024 미만 포트 바인딩 테스트
docker run --rm --cap-drop=ALL --cap-add=NET_BIND_SERVICE -p 80:80 nginx
```

### seccomp 프로파일 적용

```bash
# Docker 기본 seccomp 프로파일 확인
docker info --format '{{.SecurityOptions}}'

# 커스텀 seccomp 프로파일 작성
cat <<'EOF' > custom-seccomp.json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": [
        "read", "write", "open", "close", "stat", "fstat",
        "mmap", "mprotect", "munmap", "brk", "ioctl",
        "access", "pipe", "select", "clone", "execve",
        "exit_group", "arch_prctl", "futex", "epoll_wait",
        "accept", "bind", "listen", "socket", "connect",
        "sendto", "recvfrom", "getpid", "getuid"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
EOF

# 커스텀 프로파일로 실행
docker run --rm --security-opt seccomp=custom-seccomp.json alpine sh

# seccomp 없이 실행 (위험 -- 디버깅 용도만)
docker run --rm --security-opt seccomp=unconfined alpine sh
```

### AppArmor 프로파일

```bash
# 현재 AppArmor 상태 확인
sudo aa-status

# 커스텀 AppArmor 프로파일 작성
cat <<'EOF' | sudo tee /etc/apparmor.d/docker-myapp
#include <tunables/global>

profile docker-myapp flags=(attach_disconnected) {
  #include <abstractions/base>

  # 네트워크 접근 허용
  network inet tcp,
  network inet udp,

  # 파일 접근 제어
  /app/** r,           # /app 읽기 전용
  /tmp/** rw,          # /tmp 읽기/쓰기
  /proc/*/status r,    # 프로세스 상태 읽기

  # 금지 항목
  deny /etc/shadow r,  # 패스워드 파일 접근 금지
  deny /root/** rw,    # root 홈 접근 금지
}
EOF

# 프로파일 로드
sudo apparmor_parser -r /etc/apparmor.d/docker-myapp

# 프로파일 적용하여 실행
docker run --rm --security-opt apparmor=docker-myapp myapp:latest
```

### Kubernetes에서 보안 설정 종합 예시

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-backend
  namespace: production
spec:
  replicas: 3
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      automountServiceAccountToken: false  # SA 토큰 자동 마운트 금지
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: backend
        image: harbor.internal.corp/myapp/backend:v1.0.0
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop: ["ALL"]
        resources:
          limits:
            cpu: "1"
            memory: "512Mi"
          requests:
            cpu: "200m"
            memory: "256Mi"
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: cache
          mountPath: /app/.cache
      volumes:
      - name: tmp
        emptyDir:
          sizeLimit: 100Mi
      - name: cache
        emptyDir:
          sizeLimit: 200Mi
```

---

## 면접 Q&A

### Q1: "컨테이너를 root로 실행하면 왜 위험한가요?"

**30초 답변**:
"컨테이너 내 root(UID 0)는 호스트의 root와 같은 UID입니다. 커널 취약점으로 namespace를 탈출하면 호스트 root 권한을 획득합니다. 비루트 실행, capabilities drop ALL, seccomp로 다중 방어해야 합니다."

**2분 답변**:
"컨테이너는 커널을 공유하므로, 커널 취약점이 곧 탈출 경로입니다. 2024년 runc CVE-2024-21626은 /proc/self/fd 누출로 컨테이너 탈출이 가능했습니다. root 컨테이너에서 탈출하면 호스트 root가 됩니다. 방어는 다중 계층으로 합니다. 첫째, Dockerfile에서 USER 1000으로 비루트 실행합니다. 둘째, K8s SecurityContext에서 runAsNonRoot: true, allowPrivilegeEscalation: false를 설정합니다. 셋째, capabilities를 drop ALL하고 필요한 것만 추가합니다. 넷째, seccomp RuntimeDefault로 위험 시스템콜을 차단합니다. 다섯째, readOnlyRootFilesystem으로 파일시스템 변조를 방지합니다. Pod Security Standards의 restricted 레벨을 네임스페이스에 적용하면 이 모든 것을 강제할 수 있습니다."

**경험 연결**:
"보안등급이 높은 온프레미스 환경에서 보안 심사 시 컨테이너의 root 실행이 주요 이슈였습니다. Dockerfile 검증 자동화와 Admission Controller를 통해 root 컨테이너 배포를 차단하는 정책을 적용한 경험이 있습니다."

**주의**:
User Namespace Remapping(userns-remap)을 사용하면 컨테이너 내 root가 호스트에서는 일반 사용자(예: UID 100000)로 매핑되어 탈출 시 피해를 줄일 수 있다. 하지만 모든 환경에서 지원되지 않으므로 비루트 실행이 우선이다.

### Q2: "seccomp과 AppArmor의 차이를 설명해주세요."

**30초 답변**:
"seccomp는 시스템콜을 필터링하고, AppArmor는 파일 경로/네트워크 접근을 제어합니다. seccomp이 커널 인터페이스를 제한하고, AppArmor가 리소스 접근을 제한하는 상호 보완적 관계입니다."

**2분 답변**:
"seccomp는 커널의 시스템콜 필터입니다. BPF 프로그램으로 허용할 시스템콜 목록을 정의하고, 목록 외 시스템콜 호출 시 EPERM을 반환하거나 프로세스를 종료합니다. Docker 기본 프로파일은 mount, reboot, kexec_load 등 44개 위험 시스템콜을 차단합니다. AppArmor는 LSM(Linux Security Module)으로 파일 경로 기반 접근 제어를 합니다. '/app/** r'처럼 특정 경로의 읽기/쓰기/실행을 제어하고, 네트워크 접근도 제어합니다. 둘은 보완적입니다. seccomp으로 커널 공격 표면을 줄이고, AppArmor로 파일/네트워크 리소스 접근을 세밀하게 통제합니다. RHEL/OpenShift 환경에서는 AppArmor 대신 SELinux를 사용하며, 레이블 기반으로 더 강력한 정책을 적용할 수 있습니다."

**경험 연결**:
"폐쇄망 환경에서 SELinux enforcing 모드를 유지한 채 컨테이너를 운영해야 했습니다. container_t 레이블 정책을 이해하고 커스텀 SELinux 모듈을 작성하여 필요한 접근만 허용한 경험이 있습니다."

**주의**:
seccomp 프로파일이 너무 제한적이면 애플리케이션이 동작하지 않는다. strace로 필요한 시스템콜을 확인한 후 프로파일을 작성해야 한다. RuntimeDefault 프로파일로 시작하는 것을 권장한다.

### Q3: "Linux capabilities란 무엇이고, 컨테이너 보안에서 왜 중요한가요?"

**30초 답변**:
"Capabilities는 root 권한을 37개 이상의 세부 권한으로 분리한 것입니다. 컨테이너에서 drop ALL로 모든 권한을 제거하고, 필요한 것(예: NET_BIND_SERVICE)만 추가하면 공격 시 악용 가능한 권한이 최소화됩니다."

**2분 답변**:
"전통적 Unix는 root(UID 0)에게 모든 권한을 부여합니다. Capabilities는 이를 NET_BIND_SERVICE(1024 미만 포트), SYS_ADMIN(마운트, 네임스페이스), NET_RAW(raw socket) 등으로 세분화합니다. Docker는 기본적으로 14개의 capability를 허용하는데, 이 중에도 불필요한 것이 많습니다. 예를 들어 NET_RAW는 ARP spoofing에 악용될 수 있고, SYS_CHROOT는 탈출에 활용될 수 있습니다. 보안 모범 사례는 drop ALL로 시작하여 애플리케이션에 필요한 것만 add하는 것입니다. 웹 서버가 80포트를 사용해야 하면 NET_BIND_SERVICE만 추가합니다. 또는 비루트 사용자로 8080 같은 고포트를 사용하면 어떤 capability도 필요 없습니다."

**경험 연결**:
"온프레미스 환경에서 컨테이너 보안 가이드를 수립할 때, CIS Docker Benchmark를 기준으로 불필요한 capabilities를 제거하는 정책을 적용했습니다. 특히 NET_RAW, SYS_ADMIN 제거를 기본으로 했습니다."

**주의**:
SYS_ADMIN capability는 '거의 root'와 동일하다. mount, bpf, namespace 생성 등이 가능해지므로, 이 capability를 추가하라는 요구가 있으면 근본 원인을 파악하여 다른 방법을 찾아야 한다.

---

## Allganize 맥락

- **Pod Security Standards**: Allganize의 프로덕션 네임스페이스에는 PSS restricted 레벨을 적용하여 비루트 실행, readOnlyRootFS, capability drop ALL을 강제한다.
- **LLM 워크로드 보안**: GPU를 사용하는 LLM 추론 Pod는 NVIDIA 디바이스 접근이 필요하여 일부 privileged 설정이 필요할 수 있다. RuntimeClass나 Security Profile Operator로 최소 권한을 부여한다.
- **멀티테넌트 격리**: SaaS 환경에서 고객별 데이터 격리가 중요하다. 네임스페이스 분리 + NetworkPolicy + seccomp + 서비스 계정 분리로 다중 방어한다.
- **Admission Controller**: OPA Gatekeeper나 Kyverno로 보안 정책을 코드로 관리(Policy-as-Code)하고, 정책 위반 Pod의 배포를 사전 차단한다.
- **이미지 보안**: distroless 베이스 이미지를 사용하여 쉘 없는 프로덕션 이미지를 만들고, Trivy 스캔 + Cosign 서명으로 공급망 보안을 확보한다.

---
**핵심 키워드**: `rootless` `seccomp` `AppArmor` `capabilities` `Pod Security Standards` `SecurityContext` `Defense-in-Depth`
