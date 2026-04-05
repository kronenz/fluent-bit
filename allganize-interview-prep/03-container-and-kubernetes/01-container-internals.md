# 01. 컨테이너 내부 구조 (Container Internals)

> **TL;DR**
> - 컨테이너는 VM이 아니라 **Linux 커널의 namespace + cgroup**으로 격리된 프로세스다.
> - **OCI 표준** 덕분에 Docker, containerd, CRI-O 등 런타임이 서로 호환된다.
> - 이미지는 **레이어(layer)** 단위로 쌓이며, Union FS가 이를 하나로 합쳐 보여준다.

---

## 1. 컨테이너가 실제로 하는 일

컨테이너는 가상머신이 아니다.
**Linux 커널**이 제공하는 두 가지 기능으로 프로세스를 격리할 뿐이다.

| 기술 | 역할 |
|------|------|
| **Namespace** | PID, Network, Mount, UTS, IPC, User 등을 분리 |
| **cgroup (Control Group)** | CPU, Memory, I/O 등 자원 사용량 제한 |

```bash
# 현재 프로세스의 namespace 확인
ls -la /proc/self/ns/

# cgroup으로 메모리 제한 확인
cat /sys/fs/cgroup/memory/memory.limit_in_bytes
```

**폐쇄망(air-gapped) 경험과의 연결:**
보안등급이 높은 환경에서 VM 대신 컨테이너를 도입하면, **커널을 공유**하므로 오버헤드가 줄어든다. 다만 커널 공유가 보안 이슈가 될 수 있어 **gVisor**, **Kata Containers** 같은 샌드박스 런타임을 병행하기도 한다.

---

## 2. 컨테이너 런타임 계층 구조

컨테이너 런타임은 **두 계층**으로 나뉜다.

```
┌─────────────────────────────────┐
│  High-Level Runtime             │
│  (containerd, CRI-O)            │
│  - 이미지 관리, 네트워크 설정    │
│  - Kubernetes CRI 인터페이스     │
├─────────────────────────────────┤
│  Low-Level Runtime              │
│  (runc, crun, kata-runtime)     │
│  - 실제 namespace/cgroup 생성    │
│  - OCI Runtime Spec 구현         │
└─────────────────────────────────┘
```

### Docker vs containerd vs CRI-O

| 항목 | Docker | containerd | CRI-O |
|------|--------|-----------|-------|
| **포지셔닝** | 개발자 도구 (빌드+실행) | 산업 표준 런타임 | K8s 전용 경량 런타임 |
| **CRI 지원** | dockershim (K8s 1.24 제거) | CRI 플러그인 내장 | 네이티브 CRI |
| **이미지 빌드** | `docker build` 지원 | 별도 도구 필요 (BuildKit) | 별도 도구 필요 |
| **사용처** | 개발 환경 | K8s 기본 런타임 | OpenShift 기본 런타임 |
| **Low-level** | runc | runc | runc |

> **핵심 포인트:** Kubernetes 1.24부터 **dockershim이 제거**되어 Docker를 직접 CRI로 쓸 수 없다. containerd나 CRI-O를 써야 한다.

```bash
# containerd 상태 확인
sudo systemctl status containerd

# crictl로 컨테이너 목록 확인 (CRI 호환 CLI)
sudo crictl --runtime-endpoint unix:///run/containerd/containerd.sock ps

# CRI-O 소켓 확인
sudo crictl --runtime-endpoint unix:///var/run/crio/crio.sock info
```

---

## 3. OCI (Open Container Initiative) 스펙

OCI는 컨테이너 생태계의 **표준 규격**이다.

### 3-1. OCI Image Spec

이미지를 **어떻게 패키징하고 배포하는가**를 정의한다.

```json
{
  "schemaVersion": 2,
  "mediaType": "application/vnd.oci.image.manifest.v1+json",
  "config": {
    "mediaType": "application/vnd.oci.image.config.v1+json",
    "digest": "sha256:abc123...",
    "size": 1234
  },
  "layers": [
    {
      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
      "digest": "sha256:def456...",
      "size": 56789
    }
  ]
}
```

### 3-2. OCI Runtime Spec

컨테이너를 **어떻게 실행하는가**를 정의한다 (`config.json`).

```json
{
  "ociVersion": "1.0.2",
  "process": {
    "terminal": false,
    "user": { "uid": 0, "gid": 0 },
    "args": ["/bin/sh", "-c", "echo hello"],
    "env": ["PATH=/usr/bin:/bin"],
    "cwd": "/"
  },
  "root": {
    "path": "rootfs",
    "readonly": true
  },
  "linux": {
    "namespaces": [
      { "type": "pid" },
      { "type": "network" },
      { "type": "mount" }
    ],
    "resources": {
      "memory": { "limit": 536870912 }
    }
  }
}
```

```bash
# runc으로 OCI 번들 직접 실행 (디버깅 용도)
mkdir -p mycontainer/rootfs
cd mycontainer
runc spec                     # config.json 생성
runc create mycontainer       # 컨테이너 생성
runc start mycontainer        # 실행
runc list                     # 목록 확인
```

---

## 4. 이미지 레이어와 Union FS

### 4-1. 레이어 구조

**Dockerfile의 각 명령어**가 하나의 레이어를 생성한다.

```dockerfile
FROM ubuntu:22.04           # Layer 1: 베이스 이미지
RUN apt-get update          # Layer 2: 패키지 인덱스
RUN apt-get install -y curl # Layer 3: curl 설치
COPY app.py /app/           # Layer 4: 애플리케이션 코드
CMD ["python3", "/app/app.py"]  # 메타데이터 (레이어 아님)
```

```
┌──────────────────────┐  ← Container Layer (R/W, 임시)
├──────────────────────┤
│ Layer 4: COPY app.py │  ← Read-Only
├──────────────────────┤
│ Layer 3: curl 설치    │  ← Read-Only
├──────────────────────┤
│ Layer 2: apt update   │  ← Read-Only
├──────────────────────┤
│ Layer 1: ubuntu:22.04 │  ← Read-Only
└──────────────────────┘
```

### 4-2. Union FS (OverlayFS)

**OverlayFS**는 여러 레이어를 하나의 파일시스템처럼 합쳐서 보여준다.

```
upperdir (R/W)  ←  컨테이너가 쓰기하는 곳
     ↕ merged
lowerdir (R/O)  ←  이미지 레이어들 (불변)
```

```bash
# OverlayFS 마운트 정보 확인
mount | grep overlay

# 특정 컨테이너의 레이어 확인
docker inspect --format='{{.GraphDriver.Data}}' <container_id>

# 이미지 레이어 히스토리
docker history nginx:latest
```

### 4-3. Copy-on-Write (CoW)

컨테이너가 읽기 전용 레이어의 파일을 수정하면, **해당 파일만 upperdir로 복사**한 뒤 수정한다. 원본 레이어는 그대로 유지된다.

**폐쇄망 환경에서의 레이어 활용:**

```bash
# 프라이빗 레지스트리에서 이미지 저장/로드 (air-gapped)
docker save nginx:latest -o nginx.tar
# USB 또는 내부망 전송
docker load -i nginx.tar

# skopeo로 레지스트리 간 이미지 복사 (OCI 호환)
skopeo copy \
  docker://public-registry.io/nginx:latest \
  docker://internal-registry.local/nginx:latest

# 이미지 레이어를 미리 캐시하면 배포 시간 대폭 단축
# 공통 베이스 이미지를 내부 레지스트리에 미리 적재하는 전략
```

---

## 5. 멀티 스테이지 빌드 (Multi-stage Build)

프로덕션 이미지 크기를 줄이는 핵심 기법이다.

```dockerfile
# Stage 1: 빌드
FROM golang:1.21 AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o myapp .

# Stage 2: 실행 (최소 이미지)
FROM gcr.io/distroless/static:nonroot
COPY --from=builder /app/myapp /myapp
USER nonroot:nonroot
ENTRYPOINT ["/myapp"]
```

**결과:** 빌드 도구 없이 바이너리만 포함 → 이미지 크기 수백 MB → 수 MB로 감소.

---

## 면접 Q&A

### Q1. "컨테이너와 VM의 차이를 설명해주세요."

> **이렇게 대답한다:**
> "VM은 하이퍼바이저 위에 **게스트 OS 전체**를 실행하지만, 컨테이너는 **호스트 커널을 공유**하면서 namespace와 cgroup으로 프로세스를 격리합니다. 그래서 컨테이너는 시작 시간이 수초 이내이고, 메모리 오버헤드가 훨씬 적습니다. 다만 커널을 공유하기 때문에 **커널 취약점이 곧 컨테이너 탈출**로 이어질 수 있어, 보안이 중요한 환경에서는 gVisor나 Kata Containers 같은 샌드박스 런타임을 고려합니다."

### Q2. "Kubernetes가 Docker를 더 이상 지원하지 않는다는 게 무슨 뜻인가요?"

> **이렇게 대답한다:**
> "정확히는 **dockershim이 K8s 1.24에서 제거**된 것입니다. Docker 내부적으로 containerd를 쓰기 때문에, containerd를 CRI 런타임으로 직접 연결하면 됩니다. Docker로 빌드한 이미지는 **OCI 표준**을 따르므로 어떤 런타임에서든 그대로 실행됩니다. 실무에서는 containerd로 전환하는 것이 일반적이고, OpenShift 환경이라면 CRI-O를 사용합니다."

### Q3. "이미지 레이어가 왜 중요한가요?"

> **이렇게 대답한다:**
> "레이어 구조 덕분에 **공통 베이스 이미지를 여러 컨테이너가 공유**할 수 있어 디스크와 네트워크 사용량이 줄어듭니다. 특히 폐쇄망 환경에서는 내부 레지스트리에 베이스 이미지를 미리 적재하고, 애플리케이션 코드 레이어만 업데이트하면 **배포 시간을 대폭 단축**할 수 있습니다. Dockerfile 작성 시 자주 바뀌는 레이어를 아래쪽에 배치하면 캐시 히트율이 높아집니다."

### Q4. "폐쇄망에서 컨테이너 이미지를 어떻게 관리하셨나요?"

> **이렇게 대답한다:**
> "`docker save/load`나 **skopeo**를 활용해 이미지를 오프라인으로 전달했습니다. 내부에 **Harbor** 같은 프라이빗 레지스트리를 구축하고, 이미지 서명과 취약점 스캔을 거쳐 승인된 이미지만 배포 가능하도록 관리했습니다. OCI 표준 덕분에 레지스트리 간 이미지 이동이 수월했습니다."

---

`#컨테이너런타임` `#OCI` `#containerd` `#이미지레이어` `#UnionFS`
