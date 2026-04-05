# 커널 튜닝 (Kernel Tuning)

> **TL;DR**
> 1. **sysctl**은 런타임에 커널 파라미터를 조정하는 도구이며, `/etc/sysctl.d/`에 영구 설정한다.
> 2. 네트워크(net.core, net.ipv4), 메모리(vm.*), 파일 디스크립터(fs.*) 튜닝이 서비스 성능과 안정성에 직접 영향을 미친다.
> 3. Kubernetes 노드에서는 kubelet의 `--allowed-unsafe-sysctls`와 Pod의 `securityContext.sysctls`로 Pod별 커널 파라미터를 설정할 수 있다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 25min

---

## 핵심 개념

### sysctl 구조

```
/proc/sys/                          sysctl 파라미터 매핑
├── net/                            net.*
│   ├── core/                       net.core.*
│   │   ├── somaxconn               → 리슨 큐 최대 크기
│   │   ├── netdev_max_backlog      → NIC 수신 큐 크기
│   │   └── rmem_max / wmem_max     → 소켓 버퍼 최대값
│   ├── ipv4/                       net.ipv4.*
│   │   ├── tcp_max_syn_backlog     → SYN 큐 크기
│   │   ├── ip_local_port_range     → 임시 포트 범위
│   │   ├── tcp_tw_reuse            → TIME_WAIT 재사용
│   │   ├── tcp_keepalive_*         → keepalive 설정
│   │   └── tcp_fin_timeout         → FIN_WAIT2 타임아웃
│   └── ipv6/                       net.ipv6.*
├── vm/                             vm.*
│   ├── swappiness                  → swap 경향
│   ├── overcommit_memory           → 메모리 오버커밋
│   ├── dirty_ratio                 → dirty page 비율
│   └── panic_on_oom                → OOM 시 패닉 여부
├── fs/                             fs.*
│   ├── file-max                    → 시스템 전체 FD 한도
│   ├── nr_open                     → 프로세스당 FD 한도
│   └── inotify/                    → 파일 감시 한도
│       └── max_user_watches
└── kernel/                         kernel.*
    ├── pid_max                     → 최대 PID
    ├── threads-max                 → 최대 스레드
    └── panic                       → 패닉 후 재부팅 대기 시간
```

### 네트워크 커널 파라미터 (핵심)

**TCP 연결 수립 과정과 관련 파라미터**:

```
클라이언트                     서버
    │                          │
    │──── SYN ────────────────→│  tcp_max_syn_backlog (SYN 큐)
    │                          │
    │←─── SYN-ACK ────────────│
    │                          │
    │──── ACK ────────────────→│  somaxconn (Accept 큐 = listen backlog)
    │                          │
    │    [ESTABLISHED]         │  accept() → 앱으로 전달
    │                          │
```

| 파라미터 | 기본값 | 권장값 (고부하) | 설명 |
|----------|--------|----------------|------|
| **net.core.somaxconn** | 4096 | **65535** | listen() 백로그 최대값. 높은 동시 접속에 필수 |
| **net.core.netdev_max_backlog** | 1000 | **5000** | NIC → 커널 수신 큐. 패킷 드롭 방지 |
| **net.core.rmem_max** | 212992 | **16777216** | 소켓 수신 버퍼 최대 (16MB) |
| **net.core.wmem_max** | 212992 | **16777216** | 소켓 송신 버퍼 최대 (16MB) |
| **net.ipv4.tcp_max_syn_backlog** | 256 | **65535** | SYN 큐 크기. SYN flood 방어 |
| **net.ipv4.ip_local_port_range** | 32768 60999 | **1024 65535** | 임시 포트 범위 확장 |
| **net.ipv4.tcp_tw_reuse** | 0/2 | **1** | TIME_WAIT 소켓 재사용 (outgoing) |
| **net.ipv4.tcp_fin_timeout** | 60 | **15** | FIN_WAIT2 타임아웃 단축 |
| **net.ipv4.tcp_keepalive_time** | 7200 | **600** | keepalive 첫 probe까지 시간(초) |
| **net.ipv4.tcp_keepalive_intvl** | 75 | **30** | probe 간격(초) |
| **net.ipv4.tcp_keepalive_probes** | 9 | **3** | 최대 probe 횟수 |
| **net.ipv4.tcp_syncookies** | 1 | **1** | SYN flood 방어 (유지) |

### 메모리 커널 파라미터

| 파라미터 | 기본값 | 권장값 | 설명 |
|----------|--------|--------|------|
| **vm.swappiness** | 60 | **0~10** (서버) | anonymous page swap 경향 |
| **vm.overcommit_memory** | 0 | 상황별 | 0: 휴리스틱, 1: 항상 허용, **2: 제한** |
| **vm.overcommit_ratio** | 50 | 80~90 | mode=2일 때 commit limit = swap + RAM*ratio% |
| **vm.dirty_ratio** | 20 | **10** | dirty page 비율 (쓰기 블록 임계) |
| **vm.dirty_background_ratio** | 10 | **5** | 백그라운드 플러시 시작 비율 |
| **vm.panic_on_oom** | 0 | 0 | 1이면 OOM 시 커널 패닉 |
| **vm.min_free_kbytes** | 동적 | **131072** | 커널 예약 메모리 (128MB) |

**overcommit_memory 동작**:

```
mode 0 (heuristic):   malloc 요청을 휴리스틱으로 판단 (일부 거절)
mode 1 (always):      항상 허용 → 실제 사용 시 OOM Kill 가능
mode 2 (strict):      commit limit = swap + RAM * (overcommit_ratio/100)
                       초과 시 malloc 실패 (-ENOMEM)
```

### 파일 디스크립터 한도

```
┌─────────────────────────────────────────────┐
│              FD 한도 계층 구조                │
│                                              │
│  시스템 전체:  fs.file-max (커널 한도)        │
│       │                                      │
│  프로세스당:  fs.nr_open (hard ceiling)       │
│       │                                      │
│  사용자별:   /etc/security/limits.conf       │
│       │      nofile hard/soft                │
│       │                                      │
│  셸 세션:    ulimit -n (현재 세션)           │
│                                              │
│  systemd:   LimitNOFILE= (Unit 파일)        │
└─────────────────────────────────────────────┘
```

| 설정 | 기본값 | 권장값 | 설명 |
|------|--------|--------|------|
| **fs.file-max** | ~100만 | **2097152** | 시스템 전체 최대 FD |
| **fs.nr_open** | 1048576 | **1048576** | 프로세스당 최대 FD (ulimit 상한) |
| **fs.inotify.max_user_watches** | 8192 | **524288** | inotify 감시 수 (IDE, kubectl 등) |
| **fs.inotify.max_user_instances** | 128 | **1024** | inotify 인스턴스 수 |

### Kubernetes Pod별 sysctl

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sysctl-example
spec:
  securityContext:
    sysctls:
    # safe sysctls (기본 허용, namespace 격리)
    - name: net.ipv4.ip_local_port_range
      value: "1024 65535"
    - name: net.ipv4.tcp_syncookies
      value: "1"
    # unsafe sysctls (kubelet에서 명시적 허용 필요)
    # --allowed-unsafe-sysctls=net.core.somaxconn
    - name: net.core.somaxconn
      value: "65535"
  containers:
  - name: app
    image: nginx
```

**Safe vs Unsafe sysctl**:

| 구분 | 조건 | 예시 |
|------|------|------|
| **Safe** | namespace 격리됨, 다른 Pod에 영향 없음 | net.ipv4.* (일부) |
| **Unsafe** | 노드 전체에 영향 가능 | net.core.*, vm.*, kernel.* |

---

## 실전 예시

```bash
# === sysctl 기본 사용 ===
sysctl -a                             # 모든 파라미터 출력
sysctl net.core.somaxconn             # 특정 값 조회
sysctl -w net.core.somaxconn=65535    # 임시 변경 (재부팅 시 초기화)

# 영구 설정
cat > /etc/sysctl.d/99-custom.conf << 'EOF'
# === Network ===
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 5000
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# === Memory ===
vm.swappiness = 10
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.min_free_kbytes = 131072
vm.overcommit_memory = 0

# === File Descriptors ===
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 1024
EOF

sysctl --system                        # 모든 설정 파일 로드

# === 파일 디스크립터 설정 ===
# 현재 세션
ulimit -n                              # soft limit
ulimit -Hn                             # hard limit

# 영구 설정 (/etc/security/limits.conf)
cat >> /etc/security/limits.conf << 'EOF'
*       soft    nofile  65535
*       hard    nofile  131072
root    soft    nofile  65535
root    hard    nofile  131072
EOF

# systemd 서비스에서
# [Service]
# LimitNOFILE=131072

# === 네트워크 상태 확인 ===
# TIME_WAIT 소켓 수
ss -s                                  # 소켓 요약 통계
ss -tan state time-wait | wc -l        # TIME_WAIT 수

# SYN 큐 상태
ss -tan state syn-recv | wc -l         # SYN 큐 사용량

# Listen 큐 오버플로 확인
ss -tlnp                               # 리슨 소켓과 큐 상태
# Recv-Q: 현재 큐에 쌓인 연결
# Send-Q: 최대 큐 크기 (backlog)
nstat -az TcpExtListenOverflows        # Accept 큐 오버플로 카운터
nstat -az TcpExtListenDrops            # 드롭된 연결 수

# 임시 포트 고갈 확인
ss -tan | awk '{print $4}' | cut -d: -f2 | sort -n | uniq -c | sort -rn | head

# === 메모리 튜닝 확인 ===
cat /proc/sys/vm/swappiness
cat /proc/sys/vm/overcommit_memory
cat /proc/sys/vm/overcommit_ratio

# overcommit 상태
grep -E "CommitLimit|Committed_AS" /proc/meminfo
# Committed_AS > CommitLimit 이면 overcommit 상태

# dirty page 상태
grep -E "Dirty|Writeback" /proc/meminfo

# === FD 사용량 모니터링 ===
cat /proc/sys/fs/file-nr
# 출력: 할당된_FD  사용가능_FD  최대_FD

# 프로세스별 FD 사용량 (상위 10)
for pid in /proc/[0-9]*/fd; do
  echo "$(ls "$pid" 2>/dev/null | wc -l) $(cat "${pid%/fd}/cmdline" 2>/dev/null | tr '\0' ' ')"
done | sort -rn | head -10

# lsof로 확인
lsof -p <PID> | wc -l
lsof | awk '{print $1}' | sort | uniq -c | sort -rn | head

# === K8s 노드 튜닝 (DaemonSet으로) ===
# initContainer에서 sysctl 설정
# apiVersion: apps/v1
# kind: DaemonSet
# spec:
#   template:
#     spec:
#       initContainers:
#       - name: sysctl
#         image: busybox
#         command: ["sh", "-c", "sysctl -w net.core.somaxconn=65535"]
#         securityContext:
#           privileged: true
```

---

## 면접 Q&A

### Q: 대량의 동시 접속을 처리하기 위한 커널 튜닝 항목을 설명해주세요.

**30초 답변**:
`net.core.somaxconn`(listen 큐)과 `net.ipv4.tcp_max_syn_backlog`(SYN 큐)를 늘리고, `ip_local_port_range`를 확장하며, `tcp_tw_reuse`로 TIME_WAIT 소켓을 재활용합니다. `fs.file-max`와 `ulimit -n`으로 파일 디스크립터 한도도 늘려야 합니다.

**2분 답변**:
TCP 연결 수립 과정을 따라가며 병목을 제거합니다. 1) SYN 수신: `tcp_max_syn_backlog`(65535)으로 SYN 큐 확장, `tcp_syncookies=1`로 SYN flood 방어. 2) Accept 큐: `somaxconn`(65535)과 앱의 listen backlog를 함께 늘려야 합니다(min 적용). `ss -tlnp`의 Recv-Q/Send-Q로 큐 상태를 확인합니다. 3) 연결 수립 후: 동시에 수만 개 연결을 유지하려면 `file-max`와 프로세스별 FD 한도(`ulimit -n` 또는 systemd `LimitNOFILE`)를 충분히 설정합니다. 4) 연결 종료: `tcp_tw_reuse=1`로 outgoing 연결의 TIME_WAIT 재사용, `tcp_fin_timeout=15`로 FIN_WAIT2 단축. 5) 소켓 버퍼: `rmem_max`/`wmem_max`를 16MB로 확대하여 대용량 전송 성능 확보. `nstat -az TcpExtListenOverflows`로 Accept 큐 오버플로를 모니터링하고, Prometheus node_exporter로 이 메트릭을 수집합니다.

**경험 연결**:
폐쇄망의 내부 API 서버에서 동시 접속 증가 시 `connection refused` 에러가 발생한 경험이 있습니다. `somaxconn`이 기본값 128이었던 것이 원인이었고, 커널 파라미터 튜닝과 애플리케이션 backlog 값을 함께 조정하여 해결했습니다. 이때 `ss -tlnp`로 큐 상태를 모니터링하는 방법을 배웠습니다.

**주의**:
`somaxconn`만 늘리고 앱의 listen backlog를 안 늘리면 소용없습니다. 실제 적용되는 값은 `min(somaxconn, app_backlog)`입니다. nginx의 경우 `listen 80 backlog=65535;`를 함께 설정해야 합니다.

### Q: vm.overcommit_memory의 세 가지 모드를 설명하고, AI 서비스에 적합한 설정은?

**30초 답변**:
mode 0(휴리스틱)은 커널이 판단하여 일부 malloc을 거절하고, mode 1(항상 허용)은 무조건 허용 후 OOM Kill로 처리하며, mode 2(strict)는 commit limit을 초과하면 malloc이 실패합니다. AI 서비스에서는 예측 가능한 동작을 위해 mode 0(기본) + 충분한 메모리 확보가 일반적입니다.

**2분 답변**:
mode 0(heuristic): 커널이 현재 가용 메모리, 캐시, swap 등을 종합적으로 판단하여 "명백히 과도한" 요청만 거절합니다. 대부분의 서비스에 적합합니다. mode 1(always): malloc이 항상 성공하므로 프로그램이 ENOMEM을 처리할 필요가 없지만, 실제 사용 시 OOM Kill이 발생할 수 있습니다. Redis는 fork를 사용한 RDB 저장 시 COW로 인한 overcommit이 필요하여 mode 1을 권장합니다. mode 2(strict): `CommitLimit = swap + RAM * overcommit_ratio / 100`을 초과하면 malloc이 -ENOMEM을 반환합니다. 금융 시스템 등 OOM Kill을 절대 허용할 수 없는 환경에서 사용합니다. AI 서비스(LLM 추론)는 모델 로딩 시 대량의 메모리를 한꺼번에 할당하므로, mode 0에서 충분한 메모리를 확보하고 K8s의 Guaranteed QoS(requests=limits)로 cgroup 수준에서 보호하는 것이 좋습니다. mode 2는 모델 로딩 실패를 유발할 수 있어 주의가 필요합니다.

**경험 연결**:
온프레미스에서 Redis 서버가 RDB 저장 시 overcommit 관련 경고를 출력하여, `vm.overcommit_memory=1`로 변경한 경험이 있습니다. 이때 overcommit 정책의 트레이드오프를 학습했습니다.

**주의**:
mode 1을 "메모리가 무한"이라고 오해하지 마세요. 실제 사용량이 물리 메모리를 초과하면 OOM Kill이 발생합니다. 커밋과 실제 사용의 차이를 이해해야 합니다.

### Q: Kubernetes 노드의 커널 튜닝을 어떻게 관리하나요?

**30초 답변**:
노드 레벨 sysctl은 DaemonSet의 privileged initContainer 또는 노드 프로비저닝 도구(Ansible, cloud-init)로 설정합니다. Pod 레벨은 securityContext.sysctls로 safe sysctl을 설정하고, unsafe sysctl은 kubelet의 `--allowed-unsafe-sysctls`로 허용해야 합니다.

**2분 답변**:
세 가지 수준으로 관리합니다. 1) **노드 프로비저닝**: Terraform + cloud-init 또는 Ansible로 노드 생성 시 `/etc/sysctl.d/` 파일을 배포합니다. EKS/AKS의 경우 Launch Template의 userdata에 포함합니다. 2) **DaemonSet**: 클러스터 운영 중 변경이 필요하면 privileged initContainer가 있는 DaemonSet을 배포하여 `sysctl -w`를 실행합니다. node affinity로 특정 노드 풀(GPU 노드 등)에만 적용할 수 있습니다. 3) **Pod securityContext**: namespace 격리가 가능한 safe sysctl(net.ipv4.* 일부)은 Pod spec에서 직접 설정합니다. unsafe sysctl은 kubelet 설정에서 명시적으로 허용해야 하며, PodSecurityPolicy(deprecated) 또는 PodSecurityAdmission으로 통제합니다. 실무에서는 GPU 노드에 `vm.swappiness=0`, `net.core.somaxconn=65535`, `fs.inotify.max_user_watches=524288` 등을 기본 적용합니다. node_exporter + Prometheus로 실제 적용 여부를 모니터링합니다.

**경험 연결**:
온프레미스에서 Ansible로 수백 대 서버의 커널 파라미터를 일괄 관리한 경험이 있습니다. 이 방법론이 K8s 노드 관리에서 DaemonSet + 노드 프로비저닝 방식으로 자연스럽게 확장됩니다.

**주의**:
unsafe sysctl을 무분별하게 허용하면 Pod이 노드 전체에 영향을 줄 수 있습니다. 특히 `vm.*`이나 `kernel.*`은 노드 레벨에서만 설정하고, Pod에는 허용하지 않는 것이 안전합니다.

---

## Allganize 맥락

- **AI 서비스 네트워크 튜닝**: LLM API 서버의 높은 동시 접속을 처리하기 위한 somaxconn, backlog, port range 확장
- **GPU 노드 메모리 튜닝**: `vm.swappiness=0`, 충분한 `vm.min_free_kbytes`로 AI 추론의 메모리 성능 보장
- **파일 디스크립터**: 모델 파일 로딩, 다수의 API 연결을 처리하기 위한 FD 한도 확대
- **노드 프로비저닝 자동화**: Terraform + cloud-init으로 AWS/Azure 노드 생성 시 커널 파라미터 자동 적용
- **모니터링**: node_exporter의 `node_nf_conntrack_entries`, `node_sockstat_*` 메트릭으로 커널 수준 병목 감지

---
**핵심 키워드**: `sysctl` `somaxconn` `tcp_tw_reuse` `vm.swappiness` `overcommit_memory` `file-max` `ulimit` `inotify` `safe-sysctl`
