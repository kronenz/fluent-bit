# 02. 메모리와 스토리지 (Memory & Storage)

> **TL;DR**
> 1. Linux는 **가상 메모리(Virtual Memory)**와 **페이지 테이블(Page Table)**로 프로세스별 독립 주소 공간을 제공하며, 물리 메모리가 부족하면 **swap**과 **OOM Killer**가 동작한다.
> 2. 파일시스템은 용도에 따라 **ext4**(범용), **XFS**(대용량), **OverlayFS**(컨테이너)를 선택하고, I/O 스케줄러는 워크로드에 맞게 튜닝한다.
> 3. 폐쇄망 온프레미스에서 물리 디스크와 메모리를 직접 관리한 경험은 성능 문제의 근본 원인을 찾는 핵심 역량이다.

---

## 1. 가상 메모리 (Virtual Memory)

### 핵심 개념

**가상 메모리**는 각 프로세스에 독립된 연속적인 주소 공간을 제공하는 추상화 기법이다. 실제 물리 메모리(RAM)와 디스크(swap)를 조합하여, 프로세스는 자기만의 거대한 메모리 공간을 가진 것처럼 동작한다.

```
┌─────────────────────────────────────────┐
│        프로세스 가상 주소 공간             │
│                                          │
│  ┌──────────┐ 0xFFFFFFFF (높은 주소)     │
│  │  Kernel   │  ← 사용자 접근 불가        │
│  ├──────────┤                            │
│  │  Stack    │  ← 지역변수, 함수 호출     │
│  │  ↓        │    (위에서 아래로 성장)     │
│  ├──────────┤                            │
│  │  (빈공간) │                            │
│  ├──────────┤                            │
│  │  ↑        │                            │
│  │  Heap     │  ← malloc, new            │
│  ├──────────┤    (아래에서 위로 성장)      │
│  │  BSS      │  ← 초기화되지 않은 전역변수 │
│  ├──────────┤                            │
│  │  Data     │  ← 초기화된 전역변수       │
│  ├──────────┤                            │
│  │  Text     │  ← 실행 코드 (읽기전용)    │
│  └──────────┘ 0x00000000 (낮은 주소)     │
└─────────────────────────────────────────┘
```

### 페이지 테이블 (Page Table)

가상 주소를 물리 주소로 변환하는 매핑 테이블이다. **MMU(Memory Management Unit)**가 하드웨어 수준에서 변환을 수행한다.

- **페이지(Page)** : 가상 메모리의 기본 단위 (기본 4KB)
- **프레임(Frame)** : 물리 메모리의 기본 단위 (페이지와 같은 크기)
- **TLB(Translation Lookaside Buffer)** : 페이지 테이블의 캐시. 히트율이 성능에 큰 영향

```bash
# 시스템 페이지 크기 확인
getconf PAGE_SIZE
# → 4096 (4KB)

# Huge Pages 설정 확인 (2MB 단위)
cat /proc/meminfo | grep -i huge

# THP (Transparent Huge Pages) 상태 확인
cat /sys/kernel/mm/transparent_hugepage/enabled

# 프로세스별 메모리 맵 확인
cat /proc/<PID>/maps

# 프로세스의 상세 메모리 정보
cat /proc/<PID>/smaps_rollup
```

### Swap

물리 메모리가 부족할 때 **덜 사용되는 페이지를 디스크로 이동**시키는 기법이다.

```bash
# swap 상태 확인
swapon --show
free -h

# swappiness 값 확인 (0~100, 높을수록 적극적으로 swap 사용)
cat /proc/sys/vm/swappiness

# 쿠버네티스 노드에서는 swap을 비활성화하는 것이 기본
swapoff -a
# /etc/fstab에서 swap 라인 주석 처리

# swap 사용량이 높은 프로세스 찾기
for pid in /proc/[0-9]*; do
  name=$(cat $pid/comm 2>/dev/null)
  swap=$(grep VmSwap $pid/status 2>/dev/null | awk '{print $2}')
  [ -n "$swap" ] && [ "$swap" -gt 0 ] && echo "$swap kB - $name (PID: $(basename $pid))"
done | sort -rn | head -20
```

> **폐쇄망 경험 연결**: 온프레미스 환경에서 swap이 과도하게 사용되면 성능이 급격히 저하된다. 클라우드와 달리 메모리를 즉시 추가할 수 없으므로, `swappiness` 튜닝과 메모리 사용량 사전 모니터링이 필수적이다.

---

## 2. OOM Killer (Out of Memory Killer)

### 동작 원리

Linux 커널은 메모리가 완전히 고갈되면 **OOM Killer**를 호출하여 프로세스를 강제 종료(SIGKILL)한다.

**OOM Score** 계산 기준:
- 메모리 사용량이 **많을수록** 점수 높음
- 실행 시간이 **짧을수록** 점수 높음
- root 프로세스는 점수 **감소**
- `oom_score_adj` 값으로 수동 조정 가능 (-1000 ~ 1000)

```bash
# 프로세스의 OOM 점수 확인
cat /proc/<PID>/oom_score

# OOM 점수 조정 (-1000이면 절대 죽이지 않음)
echo -1000 > /proc/<PID>/oom_score_adj

# 중요 서비스 보호 (systemd)
# /etc/systemd/system/myapp.service
# [Service]
# OOMScoreAdjust=-900

# OOM Kill 로그 확인
dmesg | grep -i "oom\|killed process"
journalctl -k | grep -i oom

# cgroup 레벨 OOM 이벤트 모니터링 (cgroup v2)
cat /sys/fs/cgroup/<path>/memory.events
# oom         ← OOM 발생 횟수
# oom_kill    ← OOM Kill 발생 횟수
```

### 쿠버네티스와의 연결

쿠버네티스에서 **memory limits**를 설정하면 cgroup의 `memory.max`에 매핑된다. Pod가 이 한계를 초과하면 cgroup 레벨 OOM Killer가 동작하여 컨테이너가 **OOMKilled** 상태가 된다.

```bash
# Pod OOMKilled 확인
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState}'

# 노드의 메모리 pressure 확인 (cgroup v2 PSI)
cat /proc/pressure/memory
# some avg10=0.50 avg60=0.30 avg300=0.10
# full avg10=0.10 avg60=0.05 avg300=0.02
```

---

## 3. 파일시스템 (Filesystem)

### ext4 vs XFS vs OverlayFS

| 구분 | ext4 | XFS | OverlayFS |
|------|------|-----|-----------|
| **용도** | 범용 | 대용량 파일/디스크 | 컨테이너 레이어 |
| **최대 파일 크기** | 16TB | 8EB | N/A |
| **최대 볼륨 크기** | 1EB | 8EB | N/A |
| **저널링** | 지원 | 지원 (메타데이터) | N/A |
| **축소(shrink)** | 가능 | **불가능** | N/A |
| **할당 방식** | extent | extent + B+tree | union mount |
| **주 사용처** | 루트 파티션, 일반 스토리지 | DB, 대용량 스토리지 | Docker, containerd |

```bash
# 파일시스템 타입 확인
df -Th
lsblk -f

# ext4 파일시스템 생성 및 튜닝
mkfs.ext4 -L mydata /dev/sdb1
tune2fs -l /dev/sdb1

# XFS 파일시스템 생성 및 정보 확인
mkfs.xfs -L bigdata /dev/sdc1
xfs_info /dev/sdc1

# inode 사용량 확인 (inode 고갈은 디스크 여유가 있어도 파일 생성 불가)
df -ih
```

### OverlayFS (컨테이너 파일시스템)

```
┌──────────────┐
│  Container   │  ← merged (통합 뷰)
│   View       │
├──────────────┤
│  Upper Layer │  ← 쓰기 가능 (컨테이너 변경사항)
├──────────────┤
│  Lower Layer │  ← 읽기 전용 (이미지 레이어)
│  Lower Layer │
│  Lower Layer │
└──────────────┘
```

```bash
# Docker의 OverlayFS 확인
docker inspect <container> --format '{{.GraphDriver.Data}}'

# OverlayFS 수동 마운트 예시
mkdir -p /tmp/{lower,upper,work,merged}
echo "base file" > /tmp/lower/file.txt
mount -t overlay overlay \
  -o lowerdir=/tmp/lower,upperdir=/tmp/upper,workdir=/tmp/work \
  /tmp/merged

# 확인: lower의 파일이 merged에 보임
cat /tmp/merged/file.txt
# merged에서 수정하면 upper에 기록됨 (Copy-on-Write)
```

> **폐쇄망 경험 연결**: 에어갭 환경에서는 이미지 레지스트리를 내부에 구축하고, 이미지 레이어를 효율적으로 관리해야 한다. OverlayFS의 레이어 구조를 이해하면 이미지 크기 최적화와 빌드 캐시 전략을 수립할 수 있다.

---

## 4. I/O 스케줄러와 디스크 성능

### I/O 스케줄러 종류

| 스케줄러 | 특징 | 적합한 워크로드 |
|----------|------|----------------|
| **none (noop)** | 스케줄링 없음 | NVMe SSD, 가상머신 |
| **mq-deadline** | 요청별 데드라인 보장 | DB, 지연 민감 워크로드 |
| **bfq** | 공정 대역폭 분배 | 데스크톱, 혼합 워크로드 |
| **kyber** | 저지연 최적화 | 고성능 SSD |

```bash
# 현재 I/O 스케줄러 확인
cat /sys/block/sda/queue/scheduler
# [mq-deadline] kyber bfq none

# I/O 스케줄러 변경
echo "mq-deadline" > /sys/block/sda/queue/scheduler

# 디스크 read-ahead 값 확인 및 조정
cat /sys/block/sda/queue/read_ahead_kb
echo 256 > /sys/block/sda/queue/read_ahead_kb
```

### 디스크 성능 측정

```bash
# 순차 읽기 성능 (간이 측정)
dd if=/dev/sda of=/dev/null bs=1M count=1024 iflag=direct 2>&1 | tail -1

# 순차 쓰기 성능
dd if=/dev/zero of=/tmp/testfile bs=1M count=1024 oflag=direct 2>&1 | tail -1

# fio를 이용한 정밀 측정 (랜덤 4K 읽기, iodepth 32)
fio --name=rand_read \
    --ioengine=libaio \
    --iodepth=32 \
    --rw=randread \
    --bs=4k \
    --size=1G \
    --numjobs=4 \
    --runtime=60 \
    --group_reporting

# iostat으로 실시간 I/O 모니터링
iostat -xz 1
# 주요 지표: %util, await, r_await, w_await, avgqu-sz
```

### 주요 I/O 지표 해석

| 지표 | 의미 | 주의 기준 |
|------|------|----------|
| **%util** | 디스크 사용률 | 90% 이상 포화 |
| **await** | 평균 I/O 대기 시간 (ms) | SSD: 1ms 이하, HDD: 10ms 이하 |
| **avgqu-sz** | 평균 큐 길이 | 높으면 I/O 병목 |
| **r/s, w/s** | 초당 읽기/쓰기 IOPS | 디스크 스펙과 비교 |
| **rMB/s, wMB/s** | 초당 처리량 | 대역폭 확인 |

---

## 5. 메모리 관련 핵심 명령어

```bash
# 전체 메모리 상태 (free 명령어 해석)
free -h
#               total     used     free   shared  buff/cache  available
# Mem:          31Gi     8.2Gi    2.1Gi    512Mi      21Gi      22Gi
# → "free"가 낮아도 "available"이 높으면 정상 (buff/cache는 필요 시 회수 가능)

# /proc/meminfo 상세 정보
cat /proc/meminfo | head -20

# 페이지 캐시 강제 해제 (운영 환경 주의!)
# 1=pagecache, 2=dentries+inodes, 3=all
echo 3 > /proc/sys/vm/drop_caches

# 메모리를 많이 사용하는 프로세스 Top 10
ps aux --sort=-%mem | head -11

# NUMA 아키텍처에서 메모리 분포 확인
numactl --hardware
numastat
```

> **폐쇄망 경험 연결**: 온프레미스 환경에서 `free` 명령어의 **buff/cache**와 **available**의 차이를 정확히 이해하는 것이 중요하다. "메모리가 부족하다"는 보고를 받았을 때, 실제로 available이 충분한 경우가 많으며, 이를 정확히 판단할 수 있는 역량이 실무에서 필요하다.

---

## 면접 Q&A

### Q1. "free 명령어에서 free가 거의 0인데 문제가 있는 건가요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "아닙니다. Linux는 유휴 메모리를 **페이지 캐시(buff/cache)**로 활용합니다. 중요한 것은 `free` 값이 아니라 `available` 값입니다. available은 새 프로세스에 할당 가능한 메모리 추정치로, 페이지 캐시에서 회수 가능한 양을 포함합니다. available이 충분하면 정상이며, available이 지속적으로 감소하면 실제 메모리 부족을 의심해야 합니다."

### Q2. "OOM Killer가 어떤 기준으로 프로세스를 죽이나요? 중요한 프로세스를 보호하려면?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "OOM Killer는 `oom_score`가 가장 높은 프로세스를 종료합니다. 점수는 메모리 사용량에 비례하고, `oom_score_adj` 값으로 조정됩니다. 중요 프로세스를 보호하려면 `oom_score_adj`를 `-1000`으로 설정합니다. systemd 서비스에서는 `OOMScoreAdjust=-900`으로 설정할 수 있습니다. 쿠버네티스에서는 QoS 클래스가 Guaranteed인 Pod의 oom_score_adj가 `-997`로 설정되어 가장 마지막에 죽습니다."

### Q3. "ext4와 XFS 중 어떤 것을 선택해야 하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "범용 목적이면 ext4가 안정적이고, 대용량 파일과 디스크를 다루는 환경(빅데이터, 미디어 서버)에서는 XFS가 유리합니다. 핵심 차이는 XFS는 **볼륨 축소가 불가능**하다는 점과, 병렬 I/O 성능에서 우수하다는 점입니다. RHEL/CentOS 7부터 XFS가 기본 파일시스템이고, Ubuntu는 ext4가 기본입니다. 실무에서는 워크로드 특성에 맞게 선택하되, 컨테이너 환경에서는 OverlayFS의 백엔드로 사용되므로 호환성도 고려합니다."

### Q4. "swap을 쓰면 안 되는 경우는 언제인가요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "대표적으로 **쿠버네티스 노드**에서는 swap을 비활성화하는 것이 권장됩니다. 스케줄러가 메모리 requests/limits를 기반으로 Pod를 배치하는데, swap이 있으면 실제 물리 메모리 상태를 정확히 판단할 수 없기 때문입니다. 또한 **저지연이 중요한 DB 서버**(Redis, 실시간 처리)에서도 swap은 성능 저하를 유발합니다. 다만 쿠버네티스 1.28부터 swap 지원이 베타로 도입되어 점차 활용 가능해지고 있습니다."

### Q5. "D 상태(Uninterruptible Sleep) 프로세스가 많아지면 어떻게 대응하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "D 상태는 주로 디스크 I/O 또는 NFS 응답 대기에서 발생합니다. 먼저 `iostat -xz 1`으로 디스크 병목을 확인하고, `dmesg`에서 스토리지 관련 오류를 확인합니다. NFS 마운트 문제라면 `mount` 옵션에 `soft,timeo=10`을 적용하여 타임아웃을 설정합니다. 폐쇄망 환경에서 공유 스토리지 장애 시 이런 상황이 자주 발생했고, 근본 원인인 스토리지 경로와 네트워크를 점검하는 것이 해결의 핵심이었습니다."

---

**Tags**: `#가상메모리` `#OOM_Killer` `#파일시스템_ext4_xfs` `#I/O_스케줄러` `#swap_관리`
