# 파일시스템과 I/O (Filesystem & I/O)

> **TL;DR**
> 1. **ext4**는 범용 안정성, **XFS**는 대용량 파일/병렬 I/O에 강하며, **OverlayFS**는 컨테이너 이미지의 레이어 시스템을 구현한다.
> 2. Linux I/O 스택은 VFS → 파일시스템 → Block Layer(I/O Scheduler) → Device Driver 순으로 처리되며, 각 계층에서 성능 병목이 발생할 수 있다.
> 3. 디스크 성능 측정은 `fio`, `iostat`, `iotop`으로 수행하며, IOPS/throughput/latency를 구분하여 분석해야 한다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Linux I/O 스택

```
 사용자 프로세스 (read/write 시스템 콜)
        │
 ┌──────▼──────┐
 │     VFS     │  Virtual File System (추상화 계층)
 │ (dentry     │  모든 파일시스템의 공통 인터페이스
 │  + inode    │
 │  + page     │
 │    cache)   │
 └──────┬──────┘
        │
 ┌──────▼──────────────────────────────────┐
 │          파일시스템 드라이버               │
 │  ext4 │ XFS │ OverlayFS │ NFS │ tmpfs  │
 └──────┬──────────────────────────────────┘
        │
 ┌──────▼──────┐
 │ Page Cache  │  메모리에 데이터 캐싱 (읽기/쓰기 버퍼)
 └──────┬──────┘
        │
 ┌──────▼──────┐
 │ Block Layer │  I/O 스케줄러 (mq-deadline, bfq, kyber, none)
 │ (bio 요청)  │  I/O 병합, 정렬, 우선순위
 └──────┬──────┘
        │
 ┌──────▼──────┐
 │Device Driver│  SCSI, NVMe, virtio-blk
 └──────┬──────┘
        │
 ┌──────▼──────┐
 │  물리 디스크  │  HDD / SSD / NVMe
 └─────────────┘
```

### 주요 파일시스템 비교

| 특성 | ext4 | XFS | OverlayFS |
|------|------|-----|-----------|
| 최대 파일 크기 | 16TB | 8EB | 하위 FS 의존 |
| 최대 볼륨 크기 | 1EB | 8EB | - |
| 저널링 | O (ordered) | O (metadata) | - |
| 온라인 축소 | O | **X** (확장만 가능) | - |
| 온라인 확장 | O | O | - |
| 대용량 파일 | 보통 | **우수** (extent 기반) | - |
| 병렬 I/O | 보통 | **우수** (Allocation Group) | - |
| 삭제 성능 | 느림 (대량 파일) | **빠름** | - |
| 주요 용도 | 범용, 부트 파티션 | DB, 대용량 스토리지 | **컨테이너 이미지** |
| K8s 기본 | - | RHEL 기본 | Docker/containerd 기본 |

### OverlayFS (컨테이너 핵심)

OverlayFS는 여러 디렉토리를 계층적으로 합쳐 하나의 통합 뷰를 제공한다. 컨테이너 이미지 레이어의 핵심.

```
Container Filesystem View (merged)
┌─────────────────────────────────┐
│  /bin  /etc  /var  /app         │  ← 사용자가 보는 통합 뷰
└─────────┬───────────────────────┘
          │
    OverlayFS (union mount)
          │
┌─────────▼───────────────────────┐
│  Upper Layer (R/W)              │  ← 컨테이너 실행 중 변경사항
│  /var/lib/docker/overlay2/      │
│  └── <container-id>/diff/       │     수정/생성된 파일만 저장
│      └── app/config.yaml (수정) │     (Copy-on-Write)
├─────────────────────────────────┤
│  Lower Layer 3 (R/O)           │  ← 앱 레이어 (COPY, RUN)
│  └── app/main.py               │
├─────────────────────────────────┤
│  Lower Layer 2 (R/O)           │  ← pip install 레이어
│  └── usr/lib/python3/...       │
├─────────────────────────────────┤
│  Lower Layer 1 (R/O)           │  ← 베이스 이미지 (ubuntu:22.04)
│  └── bin/ etc/ lib/ usr/       │
└─────────────────────────────────┘
```

**Copy-on-Write 동작**:
1. **읽기**: 위에서부터 아래로 탐색, 처음 발견된 파일 반환
2. **수정**: lower layer 파일을 upper layer로 복사 후 수정 (copy_up)
3. **삭제**: upper layer에 whiteout 파일 생성 (`.wh.<filename>`)
4. **생성**: upper layer에 직접 생성

### I/O 스케줄러

Linux 5.0+ 에서는 Multi-Queue(blk-mq) 기반 스케줄러를 사용한다.

| 스케줄러 | 특성 | 권장 용도 |
|----------|------|----------|
| **none** (noop) | 스케줄링 없음, FIFO | NVMe SSD (자체 스케줄링) |
| **mq-deadline** | 읽기/쓰기 deadline 보장 | 범용 SSD, HDD |
| **bfq** | 대역폭 공정 분배, 저지연 | 데스크탑, 저속 디스크 |
| **kyber** | 경량, 읽기/쓰기 latency 타겟 | 고성능 SSD |

---

## 실전 예시

```bash
# === 파일시스템 확인 ===
df -Th                                # 마운트된 FS 타입과 사용량
lsblk -f                             # 블록 디바이스별 FS 타입
mount | column -t                     # 마운트 옵션 확인

# 파일시스템 상세 정보
dumpe2fs /dev/sda1 | head -50         # ext4
xfs_info /dev/sda2                    # XFS

# OverlayFS 확인 (Docker)
docker inspect <container> --format '{{.GraphDriver.Data}}'
mount | grep overlay

# === I/O 스케줄러 ===
cat /sys/block/sda/queue/scheduler    # 현재 스케줄러
echo mq-deadline > /sys/block/sda/queue/scheduler  # 변경

# NVMe의 경우
cat /sys/block/nvme0n1/queue/scheduler

# === 디스크 성능 측정 ===

# iostat: 실시간 I/O 통계
iostat -xz 1                          # 1초 간격
# 주요 지표: r/s, w/s (IOPS), rkB/s, wkB/s (처리량),
#           await (평균 대기시간), %util (디스크 사용률)

# iotop: 프로세스별 I/O 사용량 (실시간)
iotop -oP                             # I/O 발생 프로세스만

# fio: 벤치마크 도구
# 순차 읽기 테스트
fio --name=seq-read --ioengine=libaio --direct=1 \
    --rw=read --bs=1M --size=1G --numjobs=1 --runtime=30

# 랜덤 읽기 테스트 (IOPS 측정)
fio --name=rand-read --ioengine=libaio --direct=1 \
    --rw=randread --bs=4k --size=1G --numjobs=4 --runtime=30 \
    --iodepth=32 --group_reporting

# 랜덤 쓰기 테스트
fio --name=rand-write --ioengine=libaio --direct=1 \
    --rw=randwrite --bs=4k --size=1G --numjobs=4 --runtime=30 \
    --iodepth=32 --group_reporting

# === Page Cache 관련 ===
# 페이지 캐시 사용량
cat /proc/meminfo | grep -E "^(Cached|Buffers|Dirty|Writeback)"

# 페이지 캐시 강제 비우기 (테스트 용도)
sync                                  # dirty 페이지 플러시
echo 3 > /proc/sys/vm/drop_caches    # 모든 캐시 드롭

# 파일이 캐시에 있는지 확인
vmtouch <file>                        # 캐시 상태 확인
vmtouch -t <file>                     # 캐시에 로드

# === D 상태 프로세스 (I/O 블록) ===
ps aux | awk '$8 == "D"'             # I/O 대기 프로세스
cat /proc/<PID>/wchan                # 대기 중인 커널 함수

# === 파일 디스크립터 ===
ls -la /proc/<PID>/fd | wc -l        # 프로세스의 열린 FD 수
cat /proc/sys/fs/file-nr             # 시스템 전체 FD 사용량
# 출력: 할당된FD  미사용FD  최대FD
```

---

## 면접 Q&A

### Q: ext4와 XFS의 차이, 언제 어떤 것을 선택하나요?

**30초 답변**:
ext4는 범용적이고 온라인 축소가 가능한 안정적 파일시스템이고, XFS는 대용량 파일과 병렬 I/O에 강하지만 축소가 불가능합니다. 데이터베이스나 대용량 스토리지에는 XFS, 범용 서버에는 ext4를 선택합니다.

**2분 답변**:
ext4는 ext 시리즈의 진화형으로, 저널링, 지연 할당(delayed allocation), 온라인 축소/확장을 지원하는 범용 파일시스템입니다. XFS는 SGI가 개발한 고성능 파일시스템으로, Allocation Group 단위의 병렬 I/O 처리가 강점입니다. 대용량 파일 생성/삭제가 빠르고, extent 기반 할당으로 단편화가 적습니다. 단, 온라인 축소가 불가능합니다. RHEL 7부터 XFS가 기본 파일시스템이고, Kubernetes PV에서도 XFS를 많이 사용합니다. Docker의 overlay2 storage driver는 ext4, XFS 모두 지원하지만, XFS 사용 시 `d_type=true`(ftype=1) 옵션이 필수입니다. 실무 선택 기준: 부트 파티션이나 자주 리사이즈하는 볼륨은 ext4, DB 데이터 디렉토리나 대용량 로그 저장소는 XFS를 사용합니다.

**경험 연결**:
온프레미스 환경에서 ext4로 구성된 서버에서 대량의 로그 파일 삭제 시 I/O 급증으로 서비스에 영향을 준 경험이 있습니다. XFS로 마이그레이션 후 삭제 성능이 크게 개선되었습니다.

**주의**:
"XFS는 축소가 안 되므로 나쁘다"는 잘못된 결론입니다. 클라우드 환경에서 볼륨 축소는 거의 발생하지 않으며, XFS의 성능 이점이 더 큽니다.

### Q: 컨테이너에서 OverlayFS가 어떻게 동작하나요?

**30초 답변**:
OverlayFS는 읽기 전용 lower layer(이미지 레이어)와 읽기/쓰기 upper layer(컨테이너 레이어)를 합쳐 하나의 파일시스템 뷰를 만듭니다. 파일 수정 시 Copy-on-Write로 upper layer에 복사 후 수정합니다.

**2분 답변**:
Docker/containerd의 기본 storage driver인 overlay2는 OverlayFS를 사용합니다. 이미지의 각 레이어가 별도 디렉토리로 저장되고, 컨테이너 실행 시 모든 레이어를 순서대로 쌓아 union mount합니다. 읽기 동작은 upper layer부터 하향 탐색하여 처음 발견된 파일을 반환합니다. 쓰기 동작은 lower layer의 파일을 upper layer로 copy_up한 후 수정합니다. 삭제는 whiteout 파일(character device 0,0 또는 `.wh.` prefix)을 upper layer에 생성합니다. 성능 고려사항: copy_up은 첫 쓰기 시 전체 파일을 복사하므로, 대용량 파일을 자주 수정하는 워크로드(DB data file)에는 volume mount를 사용해야 합니다. `docker diff <container>`로 upper layer 변경사항을 확인할 수 있고, `docker system df`로 레이어별 디스크 사용량을 볼 수 있습니다.

**경험 연결**:
온프레미스에서 NFS 마운트로 공유 라이브러리를 여러 서버에 배포한 경험이 있는데, OverlayFS의 lower layer 공유 개념과 유사합니다. 읽기 전용 공유 + 각 서버별 로컬 변경사항이라는 패턴입니다.

**주의**:
"OverlayFS = AUFS"라고 혼동하지 마세요. AUFS는 out-of-tree 드라이버로 현재 deprecated되었고, OverlayFS는 커널 mainline에 포함된 공식 union filesystem입니다.

### Q: 디스크 I/O 성능 문제를 어떻게 진단하나요?

**30초 답변**:
`iostat -xz 1`로 디바이스별 IOPS, throughput, await(대기시간), %util(사용률)을 확인하고, `iotop`으로 I/O를 많이 사용하는 프로세스를 식별합니다. `fio`로 디스크 자체 성능을 벤치마크합니다.

**2분 답변**:
단계적으로 접근합니다. 1단계: `iostat -xz 1`로 전체 상황 파악. `%util`이 100% 근접하면 디스크가 포화 상태, `await`가 높으면 요청 대기 시간이 길다는 의미입니다. `r_await`와 `w_await`를 분리하여 읽기/쓰기 중 어디가 병목인지 확인합니다. 2단계: `iotop -oP`로 I/O를 유발하는 프로세스를 식별합니다. 3단계: `strace -e trace=read,write,fsync -p <PID>`로 해당 프로세스의 I/O 패턴을 분석합니다. fsync 빈도가 높으면 불필요한 동기 쓰기가 병목일 수 있습니다. 4단계: 디스크 자체 성능을 `fio`로 측정하여 하드웨어 한계인지 소프트웨어 문제인지 구분합니다. 추가로 페이지 캐시 히트율(`/proc/meminfo`의 Cached), I/O 스케줄러 설정, NVMe의 경우 queue depth도 확인합니다.

**경험 연결**:
폐쇄망 서버에서 야간 백업과 서비스 I/O가 충돌하여 성능 저하가 발생한 경험이 있습니다. `iostat`으로 병목 구간을 식별하고, I/O 스케줄러를 deadline으로 변경하고 백업 시간을 조정하여 해결했습니다.

**주의**:
SSD/NVMe에서 `%util` 100%가 반드시 포화를 의미하지 않습니다. NVMe는 병렬 처리가 가능하므로 `%util`보다 `await` 증가를 더 중요하게 봐야 합니다.

---

## Allganize 맥락

- **OverlayFS + 컨테이너 이미지**: AI 모델 이미지가 수 GB에 달하므로, 레이어 최적화로 빌드/배포 시간 단축이 중요
- **XFS for PV**: LLM 학습/추론 데이터를 저장하는 Kubernetes PV에 XFS 사용 권장
- **NVMe I/O 스케줄러**: GPU 서버의 NVMe에 `none` 스케줄러 설정으로 최대 성능 확보
- **fio 벤치마크**: AWS EBS/Azure Disk의 실제 성능을 fio로 측정하여 SLA 검증
- **Page Cache 최적화**: AI 모델 파일을 page cache에 preload하여 첫 추론 latency 감소

---
**핵심 키워드**: `ext4` `XFS` `OverlayFS` `I/O-scheduler` `iostat` `fio` `page-cache` `copy-on-write` `whiteout`
