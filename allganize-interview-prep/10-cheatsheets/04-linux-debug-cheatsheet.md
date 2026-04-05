# 리눅스 트러블슈팅 치트시트 (Cheatsheet)

> **TL;DR**
> 1. CPU -> 메모리 -> 디스크 -> 네트워크 순서로 체계적으로 확인하라
> 2. 각 영역의 핵심 원라이너(One-liner)를 외워두면 면접에서 강력하다
> 3. `top`, `free`, `df`, `ss` 네 가지면 대부분의 초기 진단이 가능하다

---

## 1. CPU 디버깅

```bash
# 전체 CPU 사용률 확인
top -bn1 | head -20

# CPU별 사용률
mpstat -P ALL 1 5

# CPU 많이 쓰는 프로세스 Top 10
ps aux --sort=-%cpu | head -11

# Load Average 확인
uptime
cat /proc/loadavg

# 특정 프로세스 CPU 추적
pidstat -u -p <PID> 1 5

# perf로 CPU 프로파일링
perf top                           # 실시간 핫스팟
perf record -g -p <PID> -- sleep 10
perf report

# CPU 코어 수 확인
nproc
lscpu | grep "^CPU(s):"
```

| 지표 | 정상 범위 | 확인 명령 |
|---|---|---|
| Load Average | < CPU 코어 수 | `uptime` |
| %usr + %sys | < 80% | `mpstat` |
| %iowait | < 10% | `mpstat` |

---

## 2. 메모리 디버깅

```bash
# 메모리 요약 (가장 먼저)
free -h

# 상세 메모리 정보
cat /proc/meminfo | head -20

# 메모리 추이 (1초 간격, 5회)
vmstat 1 5

# 메모리 많이 쓰는 프로세스 Top 10
ps aux --sort=-%mem | head -11

# 특정 프로세스 메모리 상세
pmap -x <PID> | tail -1
cat /proc/<PID>/status | grep -i vm

# OOM Killer 로그 확인
dmesg | grep -i "oom\|killed"
journalctl -k | grep -i "oom\|killed"

# 캐시/버퍼 수동 해제 (긴급 시)
sync && echo 3 > /proc/sys/vm/drop_caches

# Swap 사용량
swapon --show
```

| 지표 | 확인 포인트 | 명령 |
|---|---|---|
| available | 실제 사용 가능 메모리 | `free -h` |
| buff/cache | 필요 시 회수 가능 | `free -h` |
| si/so | Swap In/Out (0이 정상) | `vmstat 1` |
| OOM Kill | 메모리 부족 강제 종료 | `dmesg \| grep oom` |

---

## 3. 디스크 디버깅

```bash
# 파일시스템 사용량
df -h
df -ih                             # inode 사용량

# 디렉토리별 크기 (상위 10개)
du -sh /* 2>/dev/null | sort -rh | head -10
du -sh /var/log/* | sort -rh | head -10

# 디스크 I/O 통계
iostat -xz 1 5

# 디스크 I/O가 높은 프로세스
iotop -oP

# 삭제됐지만 열려있는 파일 (공간 미회수)
lsof +L1

# 큰 파일 찾기
find / -type f -size +100M -exec ls -lh {} \; 2>/dev/null

# 특정 파일을 열고 있는 프로세스
lsof /var/log/syslog
fuser -v /var/log/syslog

# 실시간 파일시스템 이벤트
inotifywait -mr /var/log/
```

| 지표 | 위험 수준 | 확인 명령 |
|---|---|---|
| 디스크 사용률 | > 90% | `df -h` |
| inode 사용률 | > 90% | `df -ih` |
| %util | > 80% | `iostat -xz 1` |
| await(ms) | > 20ms | `iostat -xz 1` |

---

## 4. 네트워크 디버깅

```bash
# 열린 포트 / 연결 확인
ss -tlnp                          # TCP LISTEN 포트
ss -tnp                           # 현재 TCP 연결
ss -s                             # 연결 상태 요약

# netstat (구버전)
netstat -tlnp
netstat -an | awk '/^tcp/ {print $6}' | sort | uniq -c | sort -rn

# 연결 상태별 카운트
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn

# DNS 확인
dig example.com
dig +short example.com
nslookup example.com

# HTTP 디버깅
curl -v https://example.com
curl -o /dev/null -s -w "%{http_code} %{time_total}s\n" https://example.com
curl -I https://example.com       # 헤더만

# TCP 연결 테스트
nc -zv example.com 443
timeout 3 bash -c "echo > /dev/tcp/example.com/443" && echo "OK"

# 패킷 캡처 (tcpdump)
tcpdump -i eth0 port 80 -nn
tcpdump -i any host 10.0.0.1 -w capture.pcap
tcpdump -i eth0 'tcp[tcpflags] & tcp-syn != 0' -nn

# 라우팅 확인
ip route
traceroute example.com
mtr example.com                    # 실시간 traceroute

# 인터페이스 정보
ip addr show
ip link show
```

| 상황 | 확인 명령 |
|---|---|
| 포트가 열려 있는지 | `ss -tlnp \| grep <port>` |
| DNS 해석 문제 | `dig +short <domain>` |
| 연결 타임아웃 | `curl -m 5 -v <url>` |
| 패킷 유실 | `ping -c 10 <host>` |
| TIME_WAIT 과다 | `ss -tan \| grep TIME-WAIT \| wc -l` |

---

## 5. 프로세스 디버깅

```bash
# 프로세스 목록
ps aux
ps -ef --forest                    # 트리 형태

# 특정 프로세스 찾기
ps aux | grep <name>
pgrep -la <name>

# 프로세스가 여는 파일
lsof -p <PID>
ls -la /proc/<PID>/fd/

# 시스템 콜 추적 (strace)
strace -p <PID>                    # 실행 중 프로세스
strace -p <PID> -e trace=network   # 네트워크 콜만
strace -c -p <PID>                 # 시스템 콜 통계
strace -f -e trace=open,read,write <command>

# 시그널 보내기
kill -l                            # 시그널 목록
kill -15 <PID>                     # SIGTERM (graceful)
kill -9 <PID>                      # SIGKILL (강제)

# 좀비 프로세스 찾기
ps aux | awk '$8=="Z" {print}'

# 프로세스 리소스 제한
cat /proc/<PID>/limits
ulimit -a
```

---

## 6. 실전 시나리오별 원라이너

### 서버가 느릴 때 (종합 점검)

```bash
# 1단계: 전체 상황 파악
uptime && free -h && df -h

# 2단계: CPU/메모리 상위 프로세스
ps aux --sort=-%cpu | head -6
ps aux --sort=-%mem | head -6
```

### 디스크 100% 찼을 때

```bash
# 큰 디렉토리 찾기
du -sh /* 2>/dev/null | sort -rh | head
# 큰 파일 찾기
find /var -type f -size +50M -exec ls -lh {} \;
# 삭제했는데 공간 안 늘어날 때
lsof +L1 | grep deleted
```

### 특정 포트에 연결이 안 될 때

```bash
# 포트 리슨 확인
ss -tlnp | grep <port>
# 방화벽 확인
iptables -L -n | grep <port>
# 외부에서 연결 테스트
curl -v telnet://host:<port>
```

### OOM Kill 발생 시

```bash
# OOM 로그 확인
dmesg -T | grep -A5 "Out of memory"
# 메모리 많이 쓰는 프로세스
ps aux --sort=-%rss | head -10
# cgroup 메모리 제한 확인
cat /sys/fs/cgroup/memory/memory.limit_in_bytes
```

### 높은 Load Average, 낮은 CPU 사용률

```bash
# I/O Wait 확인 (디스크 병목)
iostat -xz 1 3
# D 상태(Uninterruptible Sleep) 프로세스
ps aux | awk '$8~/D/ {print}'
# 어떤 프로세스가 I/O 유발
iotop -oP
```

### 네트워크 지연 분석

```bash
# 구간별 지연 확인
mtr --report <host>
# TCP 연결 시간 측정
curl -o /dev/null -s -w "DNS: %{time_namelookup}s\nConnect: %{time_connect}s\nTTFB: %{time_starttransfer}s\nTotal: %{time_total}s\n" https://example.com
```

---

## 7. 유용한 도구 설치

```bash
# 한 줄 설치 (Ubuntu/Debian)
apt install -y sysstat net-tools \
  iotop htop strace tcpdump \
  dnsutils curl mtr-tiny lsof

# CentOS/RHEL
yum install -y sysstat net-tools \
  iotop htop strace tcpdump \
  bind-utils curl mtr lsof
```

---

**핵심 키워드**: `top/free/df/ss`, `strace`, `iostat`, `tcpdump`, `OOM Killer`
