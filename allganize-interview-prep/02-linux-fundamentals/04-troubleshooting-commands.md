# 리눅스 트러블슈팅 실전 명령어 (Linux Troubleshooting Commands)

## TL;DR
1. 장애 대응의 기본 순서: CPU → 메모리 → 디스크 → 네트워크 → 프로세스 순으로 체계적으로 점검한다 (USE Method)
2. 각 명령어의 출력을 '읽을 수 있는 능력'이 핵심이며, 숫자 하나하나의 의미를 정확히 설명할 수 있어야 한다
3. 10년간 폐쇄망/온프렘에서 직접 트러블슈팅한 경험은 클라우드 환경에서도 매니지드 서비스 뒤의 본질을 이해하는 힘이 된다

---

## 1. CPU 분석 (CPU Analysis)

### uptime - 시스템 부하 확인의 첫 번째 명령어

```bash
$ uptime
 14:23:15 up 45 days, 3:12, 2 users, load average: 2.35, 1.87, 0.92
```

**출력 해석**:
- `load average: 2.35, 1.87, 0.92` → 1분, 5분, 15분 평균 부하
- CPU 코어 수 대비 해석: 4코어 시스템에서 2.35 → 약 59% 활용 (정상)
- **패턴 분석**: 1분 > 5분 > 15분 → 부하가 증가하는 추세 (주시 필요)
- **패턴 분석**: 1분 < 5분 < 15분 → 부하가 감소하는 추세 (안정화 중)
- 코어 수 확인: `nproc` 또는 `cat /proc/cpuinfo | grep processor | wc -l`

### top / htop - 실시간 프로세스 모니터링

```bash
$ top -bn1 | head -20
```

**핵심 지표 해석**:
- `%us` (user): 사용자 프로세스의 CPU 사용률
- `%sy` (system): 커널 프로세스의 CPU 사용률 → 높으면 I/O 또는 컨텍스트 스위칭 문제 의심
- `%wa` (iowait): I/O 대기 시간 → 높으면 디스크 병목 (Bottleneck)
- `%si` (softirq): 소프트 인터럽트 → 높으면 네트워크 패킷 처리 과부하 의심
- `%st` (steal): 가상화 환경에서 하이퍼바이저가 빼앗은 시간 → 높으면 VM 리소스 부족

### mpstat - CPU 코어별 상세 분석

```bash
$ mpstat -P ALL 1 3
```

**활용 시나리오**:
- 특정 코어에만 부하 집중 → CPU 어피니티 (Affinity) 문제 또는 단일 스레드 애플리케이션
- 모든 코어 균등 부하 → 정상적인 멀티스레드 워크로드
- IRQ 불균형 확인: 네트워크 인터럽트가 특정 코어에 집중되는 경우

---

## 2. 메모리 분석 (Memory Analysis)

### free -h - 메모리 사용 현황

```bash
$ free -h
              total        used        free      shared  buff/cache   available
Mem:           31Gi        12Gi       2.1Gi       256Mi        17Gi        18Gi
Swap:         4.0Gi       512Mi       3.5Gi
```

**출력 해석**:
- `available`이 실제 사용 가능한 메모리 (free + 회수 가능한 buff/cache)
- `free`가 낮아도 `available`이 충분하면 정상 → 리눅스는 여유 메모리를 캐시로 활용
- **Swap 사용 확인**: Swap 사용이 지속적으로 증가하면 물리 메모리 부족 신호
- Swap 사용 중이지만 `si/so`가 0이면 과거에 스왑아웃된 데이터가 아직 회수 안 된 것 (즉시 문제 아님)

### vmstat - 가상 메모리 통계

```bash
$ vmstat 1 5
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 3  0  52480 215644 189340 1782004    0    0    12    45  892 1543 15  3 80  2  0
```

**핵심 컬럼 해석**:
- `r` (run queue): 실행 대기 프로세스 수 → CPU 코어 수 초과 시 CPU 병목
- `b` (blocked): I/O 대기 프로세스 수 → 0이 아니면 디스크 병목 의심
- `si/so` (swap in/out): 0이 아니면 메모리 부족으로 스와핑 발생 중
- `cs` (context switch): 초당 컨텍스트 스위칭 횟수 → 급격한 증가는 문제 신호

### /proc/meminfo - 상세 메모리 정보

```bash
$ cat /proc/meminfo | grep -E "MemTotal|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|Slab"
```

### slabtop - 커널 슬랩 캐시 분석

```bash
$ sudo slabtop -o | head -20
```

**활용 시나리오**: dentry 캐시나 inode 캐시가 비정상적으로 큰 경우 → 파일 시스템 관련 메모리 누수 의심

---

## 3. 디스크 분석 (Disk Analysis)

### df / du - 디스크 공간 확인

```bash
# 파일 시스템별 사용량
$ df -h

# 특정 디렉토리의 상위 사용량
$ du -sh /var/* | sort -rh | head -10

# inode 사용량 (파일 수 제한)
$ df -i
```

**주의**: 디스크 용량은 충분한데 inode가 부족한 경우 → 소규모 파일이 대량 생성된 상황 (로그, 임시파일, 세션 파일 등)

### iostat - 디스크 I/O 성능 분석

```bash
$ iostat -xz 1 3
Device  r/s   w/s   rkB/s   wkB/s  rrqm/s  wrqm/s  %rrqm  %wrqm  r_await  w_await  aqu-sz  rareq-sz  wareq-sz  svctm  %util
sda    12.00 45.00  96.00  360.00   0.00    8.00   0.00  15.09    1.25    3.50   0.18     8.00     8.00   2.10  11.97
nvme0  85.00 120.00 2720.00 3840.00  0.00   15.00   0.00  11.11    0.15    0.08   0.02    32.00    32.00   0.05   1.03
```

**핵심 지표 해석**:
- `%util`: 디바이스 활용률 → 100%에 가까우면 I/O 병목 (SSD는 100%여도 큐잉으로 처리 가능)
- `r_await / w_await`: 읽기/쓰기 요청의 평균 대기 시간 (ms) → 높으면 디스크 느림
- `aqu-sz` (average queue size): 평균 요청 큐 길이 → 길수록 대기 중인 I/O 많음

### iotop - 프로세스별 I/O 사용량

```bash
$ sudo iotop -oP
```

**활용**: 어떤 프로세스가 디스크 I/O를 가장 많이 쓰는지 실시간 확인

### lsblk - 블록 디바이스 구조 확인

```bash
$ lsblk -f
```

**활용**: 디스크 파티션, 파일 시스템 타입, 마운트 포인트, UUID 확인

---

## 4. 네트워크 분석 (Network Analysis)

### ss - 소켓 통계 (netstat의 현대적 대체)

```bash
# 모든 TCP 연결 상태
$ ss -tnap

# 상태별 연결 수 요약
$ ss -s

# 특정 포트 리스닝 확인
$ ss -tlnp | grep :8080

# TIME_WAIT 연결 수 확인
$ ss -tan state time-wait | wc -l
```

**출력 해석**:
- `ESTAB`: 정상 연결 → 수가 비정상적으로 많으면 연결 풀 (Connection Pool) 문제
- `TIME_WAIT`: 연결 종료 후 대기 → 많으면 짧은 연결이 빈번한 상황
- `CLOSE_WAIT`: 상대방이 FIN을 보냈으나 애플리케이션이 close하지 않음 → 애플리케이션 버그 의심

### tcpdump - 패킷 캡처

```bash
# 특정 호스트와의 HTTP 트래픽
$ sudo tcpdump -i eth0 host 10.0.1.50 and port 80 -nn -c 100

# DNS 쿼리 캡처
$ sudo tcpdump -i any port 53 -nn

# 파일로 저장 후 Wireshark에서 분석
$ sudo tcpdump -i eth0 -w /tmp/capture.pcap -c 1000
```

### dig / curl - DNS 및 HTTP 테스트

```bash
# DNS 조회 (응답 시간 포함)
$ dig allganize.ai +stats

# HTTP 응답 시간 상세 분석
$ curl -o /dev/null -s -w "DNS: %{time_namelookup}s\nConnect: %{time_connect}s\nTLS: %{time_appconnect}s\nTTFB: %{time_starttransfer}s\nTotal: %{time_total}s\n" https://example.com
```

### ping / traceroute - 연결성 및 경로 확인

```bash
$ ping -c 5 10.0.1.50
$ traceroute -n 10.0.1.50
# MTR (결합 도구): 지속적인 경로 분석
$ mtr -n --report 10.0.1.50
```

---

## 5. 프로세스 분석 (Process Analysis)

### ps - 프로세스 상태 확인

```bash
# CPU/메모리 상위 프로세스
$ ps aux --sort=-%cpu | head -10
$ ps aux --sort=-%mem | head -10

# 프로세스 트리
$ ps auxf

# 특정 프로세스의 스레드 확인
$ ps -eLf | grep java
```

### strace - 시스템 콜 추적

```bash
# 실행 중인 프로세스에 attach
$ sudo strace -p <PID> -f -tt -T -e trace=network

# 시스템 콜 통계 (어디서 시간을 소비하는지)
$ sudo strace -c -p <PID> -f
```

**활용 시나리오**:
- 프로세스가 행 (Hang)된 경우 → 어떤 시스템 콜에서 블록되었는지 확인
- 파일을 못 찾는 경우 → `open()` 호출에서 어떤 경로를 시도하는지 확인
- 네트워크 타임아웃 → `connect()`, `read()` 에서의 대기 시간 확인

### lsof - 열린 파일/소켓 확인

```bash
# 특정 프로세스가 연 파일
$ lsof -p <PID>

# 특정 포트를 사용하는 프로세스
$ lsof -i :8080

# 삭제되었지만 아직 열려있는 파일 (디스크 공간 미회수)
$ lsof +L1
```

**핵심 팁**: `df`로 디스크가 가득 찬 것으로 보이는데 `du`의 합산이 작다면 → `lsof +L1`로 삭제된 파일을 아직 참조하는 프로세스를 확인

---

## 6. 종합 도구 (Comprehensive Tools)

### sar - 시스템 활동 리포터 (System Activity Reporter)

```bash
# 과거 CPU 사용 이력 (기본 10분 간격 수집)
$ sar -u -f /var/log/sa/sa03

# 과거 메모리 사용 이력
$ sar -r -f /var/log/sa/sa03

# 과거 네트워크 트래픽
$ sar -n DEV -f /var/log/sa/sa03

# 과거 디스크 I/O
$ sar -d -f /var/log/sa/sa03
```

**핵심 가치**: 장애 발생 시점의 시스템 상태를 과거 데이터로 소급 분석 가능 → sysstat 패키지 설치 필수

### dstat / nmon - 실시간 통합 모니터링

```bash
# CPU, 메모리, 디스크, 네트워크 동시 모니터링
$ dstat -cdnm 1

# nmon: 인터랙티브 모니터링 (녹화 가능)
$ nmon -f -s 10 -c 360  # 10초 간격, 1시간 녹화
```

---

## 7. 실전 트러블슈팅 시나리오 (Practical Scenarios)

### 시나리오 1: "서버 응답이 느립니다" (Slow Server Response)

**체계적 접근법 (USE Method: Utilization, Saturation, Errors)**:

```
Step 1: 전체 상황 파악 (30초)
$ uptime                    # load average 확인
$ dmesg -T | tail -20       # 커널 에러 메시지 확인

Step 2: CPU 확인 (30초)
$ top -bn1 | head -20       # CPU 사용률, iowait 확인
$ mpstat -P ALL 1 3         # 코어별 불균형 확인

Step 3: 메모리 확인 (30초)
$ free -h                   # available 메모리, swap 사용 확인
$ vmstat 1 5                # si/so (스와핑 발생 여부)

Step 4: 디스크 확인 (30초)
$ iostat -xz 1 3            # %util, await 확인
$ iotop -oP                 # I/O 과다 프로세스 식별

Step 5: 네트워크 확인 (30초)
$ ss -s                     # 연결 상태 요약
$ ss -tnap | grep CLOSE_WAIT # 비정상 연결 확인

Step 6: 프로세스 확인 (30초)
$ ps aux --sort=-%cpu | head -5   # CPU 과다 프로세스
$ strace -c -p <PID> -f           # 시스템 콜 병목 확인
```

> **면접에서 이렇게 물어보면 →** "서버 응답이 느리다는 보고를 받았을 때 어떻게 대응하나요?"
>
> **이렇게 대답한다:** "USE Method를 기반으로 체계적으로 접근합니다. 먼저 uptime으로 load average를 확인하여 전체적인 부하 수준을 파악합니다. 그 다음 top으로 CPU와 iowait를 보고, free로 메모리 상태를 봅니다. iowait가 높으면 iostat로 디스크 병목을 확인하고, 메모리가 부족하면 vmstat로 스와핑 여부를 봅니다. 이 과정을 2-3분 안에 완료하여 병목 지점을 특정하고, 그에 맞는 조치를 취합니다. 폐쇄망 환경에서 클라우드 서포트 없이 이런 분석을 수년간 해왔기 때문에 체계가 몸에 배어 있습니다."

### 시나리오 2: "디스크가 100%입니다" (Disk Full)

```
Step 1: 어느 파일 시스템이 가득 찼는지 확인
$ df -h

Step 2: 큰 디렉토리 추적
$ du -sh /* 2>/dev/null | sort -rh | head -10
$ du -sh /var/* | sort -rh | head -10
$ du -sh /var/log/* | sort -rh | head -10

Step 3: 최근 생성/수정된 큰 파일 찾기
$ find /var -type f -size +100M -mtime -1 -exec ls -lh {} \;

Step 4: 삭제되었지만 공간을 차지하는 파일 확인
$ lsof +L1

Step 5: inode 부족 여부 확인
$ df -i

Step 6: 로그 로테이션 상태 확인
$ ls -la /etc/logrotate.d/
$ cat /var/lib/logrotate/status
```

**자주 발생하는 원인**:
- 로그 로테이션 (Log Rotation) 미설정 → `/var/log` 폭증
- 삭제된 파일을 프로세스가 계속 참조 → `lsof +L1`로 확인 후 프로세스 재시작
- 컨테이너 오버레이 (Overlay) 파일 시스템 → `/var/lib/docker` 정리
- inode 부족 → 소규모 파일 대량 생성 (세션, 캐시 파일)

> **면접에서 이렇게 물어보면 →** "디스크 100% 알림이 왔습니다. 어떻게 하나요?"
>
> **이렇게 대답한다:** "먼저 df -h로 어떤 파일 시스템이 가득 찼는지 확인하고, du로 큰 디렉토리를 추적합니다. 다만 df와 du의 결과가 다를 수 있는데, 이 경우 lsof +L1으로 삭제되었지만 아직 프로세스가 참조 중인 파일을 확인합니다. 이것은 실제로 제가 온프렘 환경에서 자주 겪은 상황입니다. 로그 파일을 rm으로 삭제해도 해당 프로세스를 재시작하기 전까지 공간이 회수되지 않는 것을 경험으로 알고 있습니다. 또한 df -i로 inode 부족 여부도 반드시 확인합니다."

### 시나리오 3: "네트워크가 안 됩니다" (Network Unreachable)

```
Step 1: 기본 연결성 확인
$ ip addr show                       # IP 할당 상태
$ ip route show                      # 라우팅 테이블
$ ping -c 3 <게이트웨이 IP>            # 게이트웨이 연결

Step 2: DNS 확인
$ cat /etc/resolv.conf               # DNS 설정
$ dig google.com                      # DNS 해석 가능 여부
$ dig @8.8.8.8 google.com            # 외부 DNS로 직접 테스트

Step 3: 경로 추적
$ traceroute -n <목적지 IP>           # 어느 홉에서 끊기는지
$ mtr -n --report <목적지 IP>         # 패킷 손실률 확인

Step 4: 포트 연결 확인
$ curl -v telnet://<IP>:<PORT>       # TCP 연결 테스트
$ ss -tlnp                           # 로컬 리스닝 포트 확인

Step 5: 방화벽 확인
$ sudo iptables -L -n -v             # iptables 규칙
$ sudo nft list ruleset              # nftables 규칙

Step 6: 패킷 캡처 (위 단계로 해결 안 될 때)
$ sudo tcpdump -i eth0 host <목적지 IP> -nn -c 50
```

**레이어별 점검 순서 (OSI Layer)**:
1. L1/L2: 물리적 연결, 링크 상태 (`ethtool eth0`, `ip link`)
2. L3: IP, 라우팅 (`ip addr`, `ip route`, `ping`)
3. L4: TCP/UDP 포트 (`ss`, `curl telnet://`)
4. L7: 애플리케이션 (`curl -v`, `dig`)

> **면접에서 이렇게 물어보면 →** "특정 서비스에 연결이 안 된다는 보고를 받았을 때 어떻게 진단하나요?"
>
> **이렇게 대답한다:** "네트워크 문제는 OSI 레이어 순서로 아래에서 위로 점검합니다. 먼저 ip addr과 ip route로 기본 네트워크 설정을 확인하고, ping으로 게이트웨이 연결을 테스트합니다. 그 다음 DNS 해석이 되는지 dig로 확인하고, 특정 포트 연결은 curl이나 ss로 테스트합니다. 그래도 원인을 모르겠으면 tcpdump로 패킷을 캡처하여 SYN이 나가는지, SYN-ACK가 오는지, RST가 오는지를 직접 확인합니다. 폐쇄망 환경에서는 방화벽 규칙이 복잡하게 얽혀 있어서, iptables 규칙을 추적하며 패킷 흐름을 분석하는 것이 일상이었습니다."

---

## 8. 명령어 출력 해석 치트시트 (Quick Reference)

| 상황 | 확인 명령어 | 정상 기준 | 이상 신호 |
|------|-----------|----------|----------|
| CPU 부하 | `uptime` | load avg < CPU 코어 수 | load avg > 코어 수 x 2 |
| I/O 대기 | `top` (%wa) | < 5% | > 20% |
| 메모리 | `free -h` (available) | > 전체의 20% | < 전체의 10% |
| 스와핑 | `vmstat` (si/so) | 0 | > 0 지속 |
| 디스크 | `iostat` (%util) | < 70% | > 90% 지속 |
| 디스크 응답 | `iostat` (await) | < 10ms (SSD) | > 50ms |
| 네트워크 | `ss -s` | CLOSE_WAIT 0 | CLOSE_WAIT 다수 |
| 컨텍스트 스위칭 | `vmstat` (cs) | 안정적 | 급격한 증가 |
| 파일 디스크립터 | `lsof -p <PID> \| wc -l` | < ulimit 값 | ulimit 근접 |

---

## 핵심 키워드 (Keywords)
`USE Method (Utilization/Saturation/Errors)` · `System Call Tracing (strace)` · `Packet Capture (tcpdump)` · `Performance Metrics Interpretation` · `OSI Layer Troubleshooting`
