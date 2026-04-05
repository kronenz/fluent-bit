# 메모리 관리 (Memory Management)

> **TL;DR**
> 1. Linux는 **가상 메모리(Virtual Memory)** 체계로 프로세스마다 독립된 주소 공간을 제공하며, **페이지 폴트(page fault)** 를 통해 물리 메모리를 지연 할당한다.
> 2. **OOM Killer**는 메모리 부족 시 oom_score가 가장 높은 프로세스를 강제 종료하며, 컨테이너 환경에서는 cgroup memory.max 초과 시 발동된다.
> 3. **swap**, **hugepages**, **NUMA** 설정은 AI/LLM 서비스의 성능에 직접적인 영향을 미친다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 가상 메모리 (Virtual Memory)

각 프로세스는 독립된 가상 주소 공간을 가진다. MMU(Memory Management Unit)와 페이지 테이블이 가상 주소를 물리 주소로 변환한다.

```
프로세스 A (가상 주소)          물리 메모리 (RAM)         프로세스 B (가상 주소)
┌──────────────┐              ┌──────────────┐          ┌──────────────┐
│ 0xFFFF..FFFF │              │              │          │ 0xFFFF..FFFF │
│   Kernel     │──────┐      │  Frame 0     │   ┌──────│   Kernel     │
│   Space      │      │      │  Frame 1  ←──┼───┘      │   Space      │
├──────────────┤      │      │  Frame 2  ←──┼───┐      ├──────────────┤
│   Stack  ↓   │      └─────→│  Frame 3     │   │      │   Stack  ↓   │
│              │      ┌─────→│  Frame 4     │   │      │              │
│   Heap   ↑   │──────┘      │  Frame 5  ←──┼───┘      │   Heap   ↑   │
│   BSS        │             │  ...         │          │   BSS        │
│   Data       │──────┐      │  Frame N     │          │   Data       │
│   Text       │      └─────→│  (공유 lib)  │←─────────│   Text       │
│ 0x0000..0000 │              └──────────────┘          │ 0x0000..0000 │
└──────────────┘                                        └──────────────┘
        │                 MMU + Page Table                      │
        └─────────── 가상→물리 주소 변환 ──────────────────────┘
```

### 프로세스 메모리 레이아웃

```
High Address
┌──────────────────┐
│   Kernel Space   │  사용자 접근 불가
├──────────────────┤  0xC000_0000 (32bit) / 0x7FFF...(64bit)
│   Stack      ↓   │  지역 변수, 함수 호출 프레임 (자동 확장)
│                   │
│   (빈 공간)       │  ← Stack과 Heap 사이 가드
│                   │
│   mmap region     │  공유 라이브러리, 파일 매핑
│                   │
│   Heap       ↑   │  동적 할당 (malloc/brk)
├──────────────────┤
│   BSS            │  초기화되지 않은 전역/정적 변수 (0으로 초기화)
│   Data           │  초기화된 전역/정적 변수
│   Text (Code)    │  실행 코드 (읽기 전용)
├──────────────────┤
│   (Reserved)     │  NULL 포인터 트랩 영역
└──────────────────┘
Low Address (0x0)
```

### 페이지 폴트 (Page Fault)

프로세스가 접근하려는 가상 주소의 페이지가 물리 메모리에 없을 때 발생.

| 유형 | 원인 | 처리 | 비용 |
|------|------|------|------|
| **Minor** (soft) | 페이지가 메모리에 있지만 페이지 테이블 미매핑 | 페이지 테이블 업데이트만 | 낮음 (~1us) |
| **Major** (hard) | 페이지가 디스크(swap)에 있음 | 디스크에서 읽어와야 함 | **높음 (~10ms)** |
| **Invalid** | 잘못된 주소 접근 (segfault) | SIGSEGV 시그널 → 프로세스 종료 | 프로세스 종료 |

```
프로세스가 가상 주소 X 접근
         │
    ┌────▼────┐
    │  MMU    │──→ 페이지 테이블 조회
    └────┬────┘
         │
    ┌────▼────┐     YES     ┌───────────────┐
    │ 매핑    │────────────→│ 물리 주소 반환  │ (정상)
    │ 존재?   │             └───────────────┘
    └────┬────┘
         │ NO
    ┌────▼────┐
    │Page Fault│
    │ Handler  │
    └────┬────┘
         │
    ┌────▼──────┐   YES   ┌─────────────────┐
    │ 유효한     │───────→│ Minor: 프레임 할당│
    │ 가상주소?  │        │ Major: 디스크 I/O │
    └────┬──────┘        └─────────────────┘
         │ NO
    ┌────▼────┐
    │ SIGSEGV │ → 프로세스 종료
    └─────────┘
```

### OOM Killer

시스템 메모리(또는 cgroup memory.max)가 고갈되면 커널의 OOM Killer가 프로세스를 선택하여 강제 종료한다.

**oom_score 계산 요소**:
- 프로세스의 RSS(Resident Set Size)가 클수록 높은 점수
- `oom_score_adj` 값 (-1000 ~ 1000)으로 조정 가능
- -1000 = OOM Kill 면제, 1000 = 최우선 Kill 대상

```
OOM 발생 시 선택 알고리즘:

  모든 프로세스의 oom_score 계산
         │
  ┌──────▼──────┐
  │ oom_score =  │
  │ RSS 비율     │  + oom_score_adj 보정
  │ (0~1000)    │
  └──────┬──────┘
         │
  가장 높은 oom_score의 프로세스에 SIGKILL
```

**Kubernetes QoS와 OOM**:

| K8s QoS 클래스 | oom_score_adj | OOM Kill 우선순위 |
|----------------|---------------|------------------|
| BestEffort | 1000 | **가장 먼저** Kill |
| Burstable | 2~999 | 중간 |
| Guaranteed | **-997** | **가장 나중에** Kill |

### Swap

물리 메모리가 부족할 때 덜 사용되는 페이지를 디스크로 내보내는 메커니즘.

| 설정 | 값 | 의미 |
|------|-----|------|
| vm.swappiness | 0 | swap 최소화 (커널 3.5+: anonymous page swap 하지 않음, file cache만 회수) |
| | 60 | 기본값 |
| | 100 | 적극적으로 swap |
| swapoff -a | - | swap 완전 비활성화 |

**Kubernetes와 swap**: 전통적으로 K8s는 swap off를 요구했으나, 1.28부터 swap을 제한적으로 지원(NodeSwap feature gate).

### HugePages

기본 페이지 크기(4KB) 대신 2MB 또는 1GB 페이지를 사용하여 TLB miss를 줄이고 성능을 향상.

```
일반 페이지 (4KB)                    HugePages (2MB)
┌──┬──┬──┬──┬──┬──┐                 ┌──────────────────┐
│4K│4K│4K│4K│4K│4K│  512개 = 2MB    │       2MB        │  1개 = 2MB
└──┴──┴──┴──┴──┴──┘                 └──────────────────┘
  TLB 엔트리 512개 필요               TLB 엔트리 1개로 충분
  TLB miss 빈번                      TLB miss 대폭 감소
```

---

## 실전 예시

```bash
# === 메모리 상태 확인 ===
free -h                              # 전체 메모리 사용량
cat /proc/meminfo                    # 상세 메모리 정보

# 프로세스별 메모리 확인
# VSZ: 가상 메모리, RSS: 실제 물리 메모리
ps aux --sort=-rss | head -20

# 프로세스 상세 메모리 맵
cat /proc/<PID>/status | grep -E "^(VmSize|VmRSS|VmSwap|RssAnon|RssFile)"
pmap -x <PID> | tail -1              # 요약

# smaps로 정밀 분석 (PSS = 공유 메모리를 공유자 수로 나눈 값)
cat /proc/<PID>/smaps_rollup

# === 페이지 폴트 확인 ===
# minflt: minor fault, majflt: major fault
ps -o pid,minflt,majflt,cmd -p <PID>
# 또는
cat /proc/<PID>/stat | awk '{print "minflt="$10, "majflt="$12}'

# perf로 페이지 폴트 추적
perf stat -e page-faults,minor-faults,major-faults -p <PID> -- sleep 10

# === OOM 확인 및 설정 ===
# OOM Kill 로그 확인
dmesg | grep -i "oom\|out of memory\|killed process"
journalctl -k | grep -i oom

# 프로세스의 oom_score 확인
cat /proc/<PID>/oom_score
cat /proc/<PID>/oom_score_adj

# OOM Kill 면제 설정 (중요 프로세스 보호)
echo -1000 > /proc/<PID>/oom_score_adj

# cgroup OOM 이벤트 모니터링 (cgroup v2)
cat /sys/fs/cgroup/<path>/memory.events
# oom: OOM 발생 횟수, oom_kill: 실제 Kill 횟수

# === Swap 설정 ===
swapon --show                        # 현재 swap 상태
cat /proc/sys/vm/swappiness          # 현재 swappiness
sysctl vm.swappiness=10              # 임시 변경

# 프로세스별 swap 사용량
for pid in /proc/[0-9]*/status; do
  awk '/^(Name|VmSwap)/{printf "%s ", $2}' "$pid" 2>/dev/null
  echo
done | sort -k2 -rn | head -10

# === HugePages 설정 ===
cat /proc/meminfo | grep -i huge
# 2MB hugepages 128개 할당 (= 256MB)
echo 128 > /proc/sys/vm/nr_hugepages
# 또는 부팅 파라미터: hugepages=128

# Transparent HugePages (THP) 상태 확인
cat /sys/kernel/mm/transparent_hugepage/enabled
# [always] madvise never

# === 메모리 누수 탐지 ===
# RSS가 지속적으로 증가하는 프로세스 찾기
watch -n 5 'ps aux --sort=-rss | head -10'

# valgrind (개발 환경)
valgrind --leak-check=full ./my-app
```

---

## 면접 Q&A

### Q: OOM Killer가 동작하는 원리와 Kubernetes에서의 영향을 설명해주세요.

**30초 답변**:
OOM Killer는 메모리 고갈 시 oom_score가 가장 높은 프로세스를 SIGKILL합니다. Kubernetes에서는 QoS 클래스에 따라 oom_score_adj가 설정되어, BestEffort Pod가 먼저 종료되고 Guaranteed Pod가 가장 나중에 종료됩니다.

**2분 답변**:
두 가지 수준의 OOM이 있습니다. 첫째, **시스템 레벨 OOM**: 전체 노드 메모리가 고갈되면 커널 OOM Killer가 동작합니다. 각 프로세스의 RSS 비율에 `oom_score_adj`를 반영한 `oom_score`가 계산되고, 최고 점수 프로세스가 종료됩니다. 둘째, **cgroup 레벨 OOM**: 컨테이너의 memory.max(K8s limits.memory에 매핑)를 초과하면 해당 cgroup 내 프로세스만 종료됩니다. Kubernetes는 QoS 클래스에 따라 oom_score_adj를 설정합니다: Guaranteed(-997), Burstable(2~999), BestEffort(1000). 따라서 노드 OOM 시 BestEffort Pod가 먼저 희생됩니다. 실무에서는 kubelet의 eviction threshold(`--eviction-hard=memory.available<100Mi`)가 OOM Killer보다 먼저 Pod을 퇴거(evict)시켜 노드를 보호합니다. `dmesg | grep oom`과 `kubectl describe pod`의 `OOMKilled` 상태로 진단합니다.

**경험 연결**:
온프레미스 서버에서 Java 애플리케이션의 힙 설정 오류로 OOM Kill이 반복 발생한 경험이 있습니다. `/proc/<PID>/oom_score_adj`를 조정하여 중요 서비스를 보호하고, 문제 프로세스의 메모리 제한을 cgroup으로 설정했습니다.

**주의**:
"메모리가 부족하면 프로세스가 종료됩니다" 수준의 답변은 부족합니다. cgroup OOM vs 시스템 OOM, K8s QoS 연결, kubelet eviction과의 관계까지 설명하세요.

### Q: vm.swappiness는 무엇이고, 컨테이너/K8s 환경에서 어떻게 설정하나요?

**30초 답변**:
vm.swappiness는 커널이 anonymous page를 swap out하는 경향을 제어하는 파라미터입니다. 0이면 swap을 최소화하고, 100이면 적극적으로 swap합니다. Kubernetes는 전통적으로 swap off를 요구했지만, 1.28부터 제한적 지원이 시작되었습니다.

**2분 답변**:
vm.swappiness(0~200, 기본 60)는 메모리 회수 시 anonymous page(힙, 스택)와 file-backed page(페이지 캐시)의 회수 비율을 결정합니다. 값이 낮으면 file cache를 우선 회수하고, 높으면 anonymous page도 적극 swap합니다. 0으로 설정하면 커널 3.5+에서 file cache로 충분히 회수 가능한 한 anonymous page를 swap하지 않습니다. AI/LLM 서비스에서 swap은 치명적입니다. 모델 추론 시 메모리 접근 패턴이 랜덤에 가까워 swap되면 major page fault가 폭증하여 latency가 수천 배 증가합니다. 따라서 GPU 서버에서는 `swapoff -a`와 `vm.swappiness=0`을 설정하고, K8s에서는 Guaranteed QoS로 memory requests=limits를 설정하여 OOM Kill은 되더라도 swap으로 느려지는 것을 방지합니다. K8s 1.28의 NodeSwap은 Burstable Pod에 한해 swap을 허용하지만, 프로덕션 GPU 워크로드에는 권장되지 않습니다.

**경험 연결**:
폐쇄망 환경에서 메모리가 부족한 서버에서 swap을 활용하여 서비스를 유지한 경험이 있지만, latency-sensitive한 서비스에서는 swap이 오히려 장애를 유발했습니다. 이 경험을 통해 swap의 트레이드오프를 체감적으로 이해하고 있습니다.

**주의**:
"swap은 무조건 끄는 게 좋다"는 지나친 단순화입니다. 워크로드 특성에 따라 판단해야 하며, 배치 처리 시스템에서는 swap이 유용할 수 있습니다.

### Q: HugePages는 언제, 왜 사용하나요?

**30초 답변**:
HugePages는 기본 4KB 대신 2MB/1GB 페이지를 사용하여 TLB miss를 줄이고 메모리 접근 성능을 향상시킵니다. 대용량 메모리를 사용하는 데이터베이스나 AI 모델 추론에서 효과적입니다.

**2분 답변**:
CPU의 TLB(Translation Lookaside Buffer)는 가상→물리 주소 변환을 캐싱하는 하드웨어로, 크기가 제한적(수백~수천 엔트리)입니다. 4KB 페이지로 10GB 메모리를 매핑하면 약 260만 개의 페이지 테이블 엔트리가 필요하지만, 2MB 페이지를 사용하면 5,120개로 줄어듭니다. TLB miss 감소는 메모리 집약적 워크로드의 성능을 5-10% 향상시킬 수 있습니다. Static HugePages는 부팅 시 예약하여 `hugetlbfs`로 마운트하고, 애플리케이션이 `mmap`으로 사용합니다. Transparent HugePages(THP)는 커널이 자동으로 4KB 페이지를 2MB로 합치지만, compaction 오버헤드와 latency spike를 유발할 수 있어 데이터베이스(MongoDB, Redis)에서는 비활성화를 권장합니다. Kubernetes에서는 `spec.containers[].resources.limits["hugepages-2Mi"]`로 Pod에 hugepages를 할당할 수 있습니다.

**경험 연결**:
온프레미스 데이터베이스 서버에서 THP로 인한 간헐적 latency spike를 경험하고, THP를 비활성화한 후 안정화된 경험이 있습니다. 이 경험은 메모리 관리의 미세 조정이 실제 성능에 미치는 영향을 이해하는 계기가 되었습니다.

**주의**:
Static HugePages와 Transparent HugePages를 혼동하지 마세요. THP는 편리하지만 부작용이 있고, Static HugePages는 명시적 설정이 필요하지만 예측 가능합니다.

---

## Allganize 맥락

- **LLM 모델 메모리**: LLM 모델은 수 GB~수십 GB의 메모리를 사용하므로 OOM 방지를 위한 정밀한 memory limits 설정이 핵심
- **GPU 서버 swap off**: AI 추론 서버에서 swap은 latency를 수천 배 증가시키므로 반드시 비활성화
- **HugePages for AI**: 대규모 모델 로딩 시 HugePages로 TLB miss를 줄여 성능 향상 가능
- **OOM 모니터링**: Prometheus `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` 메트릭으로 OOM 이벤트 추적
- **kubelet eviction**: 노드 메모리 보호를 위한 eviction threshold 설정으로 노드 전체 장애 방지

---
**핵심 키워드**: `virtual-memory` `page-fault` `OOM-Killer` `oom_score_adj` `vm.swappiness` `hugepages` `THP` `RSS` `cgroup-memory`
