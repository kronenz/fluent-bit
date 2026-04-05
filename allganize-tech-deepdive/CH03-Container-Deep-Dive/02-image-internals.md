# 컨테이너 이미지 내부 구조 (Image Internals)

> **TL;DR**
> - 컨테이너 이미지는 **읽기 전용 레이어**의 스택이며, OverlayFS가 이를 하나의 파일시스템으로 합쳐 보여준다.
> - **멀티스테이지 빌드**로 빌드 도구 제외 → 이미지 크기를 1/10 이하로 줄일 수 있다.
> - 레이어 캐싱, .dockerignore, distroless 베이스 등 **최적화 기법**이 CI/CD 속도와 보안에 직결된다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### 1. 이미지 = 레이어의 스택

Dockerfile의 각 명령어(FROM, RUN, COPY, ADD)가 하나의 **읽기 전용 레이어**를 생성한다. 컨테이너 실행 시 최상단에 **쓰기 가능한 레이어(Container Layer)**가 추가된다.

```dockerfile
FROM ubuntu:22.04           # Layer 1: 베이스 이미지 (~77MB)
RUN apt-get update && \
    apt-get install -y curl # Layer 2: 패키지 설치 (~25MB)
COPY requirements.txt .     # Layer 3: 의존성 파일 (~1KB)
RUN pip install -r requirements.txt  # Layer 4: 패키지 (~50MB)
COPY app/ /app/             # Layer 5: 애플리케이션 코드 (~500KB)
CMD ["python3", "/app/main.py"]     # 메타데이터 (레이어 아님)
```

```
┌──────────────────────────────┐
│  Container Layer (R/W)       │  ← 실행 중 변경사항만 기록
├──────────────────────────────┤
│  Layer 5: COPY app/         │  ← Read-Only (자주 변경)
├──────────────────────────────┤
│  Layer 4: pip install       │  ← Read-Only
├──────────────────────────────┤
│  Layer 3: COPY requirements │  ← Read-Only
├──────────────────────────────┤
│  Layer 2: apt-get install   │  ← Read-Only
├──────────────────────────────┤
│  Layer 1: ubuntu:22.04      │  ← Read-Only (공유 가능)
└──────────────────────────────┘
```

**레이어가 중요한 이유:**
- **공유**: 같은 베이스 이미지를 쓰는 100개 컨테이너도 Layer 1은 디스크에 1번만 저장
- **캐싱**: 변경되지 않은 레이어는 빌드 시 재사용 (빌드 시간 단축)
- **전송 최적화**: Pull 시 이미 존재하는 레이어는 다운로드 생략

### 2. Union FS (OverlayFS)

Linux의 **OverlayFS**가 여러 레이어를 하나의 파일시스템으로 합쳐 보여준다.

```
┌─────────────────────────────────────────────────┐
│                   merged (보이는 뷰)              │
│     /bin  /etc  /usr  /app  /tmp                │
├─────────────────────────────────────────────────┤
│  upperdir (R/W)                                 │
│  ← 컨테이너의 쓰기 레이어                         │
│  ← 새 파일, 수정된 파일이 여기에 저장              │
├─────────────────────────────────────────────────┤
│  lowerdir (R/O)                                 │
│  ← 이미지 레이어들 (Layer 1 + 2 + ... + N)       │
│  ← 불변(immutable), 여러 컨테이너가 공유          │
├─────────────────────────────────────────────────┤
│  workdir                                        │
│  ← OverlayFS 내부 작업용 디렉토리                 │
└─────────────────────────────────────────────────┘
```

### 3. Copy-on-Write (CoW)

컨테이너가 읽기 전용 레이어의 파일을 수정하면, **해당 파일만 upperdir로 복사**한 뒤 수정한다.

```
[읽기 요청]  /etc/config.yml
  → lowerdir에서 읽기 (레이어 복사 없음, 빠름)

[쓰기 요청]  /etc/config.yml 수정
  1. lowerdir에서 upperdir로 파일 복사 (Copy-Up)
  2. upperdir의 복사본을 수정
  3. 이후 읽기도 upperdir에서 수행
  → 원본 lowerdir는 변경 없음

[삭제 요청]  /etc/config.yml 삭제
  → upperdir에 whiteout 파일 생성 (character device 0,0)
  → merged 뷰에서 해당 파일이 사라짐
```

### 4. 이미지 매니페스트 구조

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
      "digest": "sha256:layer1...",
      "size": 28000000
    },
    {
      "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
      "digest": "sha256:layer2...",
      "size": 15000000
    }
  ]
}
```

**Multi-Architecture Image (Fat Manifest):**

```
Image Index (Fat Manifest)
  ├── Manifest (linux/amd64) → config + layers
  ├── Manifest (linux/arm64) → config + layers
  └── Manifest (linux/s390x) → config + layers
```

M1/M2 Mac에서 빌드한 arm64 이미지가 amd64 K8s 노드에서 실행 실패하는 문제를 방지하려면, `docker buildx`로 멀티 아키텍처 이미지를 빌드해야 한다.

---

## 실전 예시

### 레이어 분석

```bash
# 이미지 레이어 히스토리 확인
docker history nginx:latest --no-trunc

# 이미지 inspect (레이어 다이제스트 확인)
docker inspect nginx:latest | jq '.[0].RootFS.Layers'

# 컨테이너의 OverlayFS 마운트 정보 확인
docker inspect <container-id> | jq '.[0].GraphDriver.Data'
# {
#   "LowerDir": "/var/lib/docker/overlay2/.../diff:...",
#   "MergedDir": "/var/lib/docker/overlay2/.../merged",
#   "UpperDir": "/var/lib/docker/overlay2/.../diff",
#   "WorkDir": "/var/lib/docker/overlay2/.../work"
# }

# 호스트에서 OverlayFS 마운트 확인
mount | grep overlay

# dive로 레이어별 파일 변경사항 시각화
dive nginx:latest
```

### 멀티스테이지 빌드 -- Go 예시

```dockerfile
# ===== Stage 1: Build =====
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download          # 의존성 캐시 레이어
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o server ./cmd/server

# ===== Stage 2: Runtime =====
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
USER nonroot:nonroot
ENTRYPOINT ["/server"]
```

```
빌드 결과 비교:
  golang:1.22 단일 스테이지   → ~1.2 GB
  alpine + 멀티스테이지       → ~15 MB
  distroless + 멀티스테이지   → ~7 MB
  scratch + 멀티스테이지      → ~5 MB
```

### 멀티스테이지 빌드 -- Python 예시

```dockerfile
# Stage 1: 의존성 빌드 (wheel 생성)
FROM python:3.12-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Stage 2: 런타임
FROM python:3.12-slim
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels
COPY src/ ./src/
USER app
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 레이어 캐싱 최적화

```dockerfile
# Bad: 소스 변경 시 의존성도 다시 설치
COPY . .
RUN npm install && npm run build

# Good: 의존성 파일을 먼저 복사하여 캐시 활용
COPY package.json package-lock.json ./    # 변경 적음 → 캐시 히트
RUN npm ci --production                    # 캐시 히트 시 스킵
COPY . .                                   # 소스만 변경 시 여기부터 재빌드
RUN npm run build
```

**캐시 규칙**: 어떤 레이어가 변경되면, 그 **이후의 모든 레이어**가 무효화된다. 따라서 변경이 적은 레이어를 위에, 자주 변경되는 레이어를 아래에 배치한다.

### 이미지 크기 최적화 체크리스트

```dockerfile
# 1. 경량 베이스 이미지 사용
FROM alpine:3.19        # ~5MB (vs ubuntu:22.04 ~77MB)
FROM distroless/static  # ~2MB (쉘 없음, 보안 강화)

# 2. RUN 명령어 합치기 (레이어 수 줄이기)
# Bad: 3개 레이어
RUN apt-get update
RUN apt-get install -y curl
RUN rm -rf /var/lib/apt/lists/*

# Good: 1개 레이어 + 캐시 정리
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# 3. .dockerignore 활용
# .git, node_modules, __pycache__, .env 등 제외

# 4. 멀티 아키텍처 빌드
docker buildx build --platform linux/amd64,linux/arm64 \
    -t harbor.internal.corp/myapp:v1.0.0 --push .
```

### 폐쇄망 이미지 관리

```bash
# 이미지를 tar로 내보내기/불러오기
docker save nginx:1.25 -o nginx-1.25.tar
# USB 또는 망간 전송 후
docker load -i nginx-1.25.tar

# skopeo로 레지스트리 간 복사 (OCI 호환)
skopeo copy \
  docker://docker.io/library/nginx:1.25 \
  docker://harbor.internal.corp/base/nginx:1.25

# crane으로 레이어 단위 조작
crane pull harbor.internal.corp/myapp:v1.0.0 myapp.tar
crane manifest harbor.internal.corp/myapp:v1.0.0 | jq .
```

---

## 면접 Q&A

### Q1: "컨테이너 이미지의 레이어 구조를 설명해주세요."

**30초 답변**:
"컨테이너 이미지는 Dockerfile의 각 명령어가 생성한 읽기 전용 레이어의 스택입니다. OverlayFS가 이 레이어들을 하나의 파일시스템으로 합쳐 보여주고, 컨테이너 실행 시 최상단에 쓰기 가능 레이어가 추가됩니다. Copy-on-Write로 원본 레이어는 변경되지 않습니다."

**2분 답변**:
"이미지는 OCI Image Spec에 따라 매니페스트, 설정, 레이어 tar 파일로 구성됩니다. 각 레이어는 이전 레이어와의 차이(diff)만 저장하므로 공간 효율적입니다. 예를 들어 ubuntu:22.04 베이스 위에 curl을 설치하면, curl 바이너리와 관련 파일만 새 레이어에 기록됩니다. OverlayFS는 lowerdir(이미지 레이어)와 upperdir(컨테이너 쓰기 레이어)를 merged 뷰로 합칩니다. 파일 수정 시 Copy-on-Write가 발생하여 해당 파일만 upperdir로 복사됩니다. 파일 삭제는 whiteout 파일로 처리됩니다. 이 구조 덕분에 같은 베이스 이미지를 사용하는 수십 개 컨테이너가 디스크에서 베이스 레이어를 공유할 수 있고, Pull 시에도 이미 존재하는 레이어는 생략됩니다."

**경험 연결**:
"폐쇄망에서 대역폭이 제한된 환경에서, 공통 베이스 이미지를 표준화하여 내부 레지스트리에 미리 배포해두면 애플리케이션 업데이트 시 변경된 코드 레이어만 전송하여 배포 시간을 크게 단축했습니다."

**주의**:
RUN 명령어에서 파일을 생성하고 다음 RUN에서 삭제해도, 이전 레이어에 파일이 남아 이미지 크기가 줄지 않는다. 반드시 같은 RUN에서 생성과 정리를 해야 한다.

### Q2: "멀티스테이지 빌드를 왜 사용하나요?"

**30초 답변**:
"빌드 도구(컴파일러, SDK)와 런타임을 분리하여 최종 이미지에 실행 바이너리만 포함합니다. Go 애플리케이션의 경우 1.2GB에서 7MB로 줄일 수 있고, 공격 표면도 줄어들어 보안이 강화됩니다."

**2분 답변**:
"단일 스테이지로 빌드하면 컴파일러, 빌드 도구, 소스 코드가 모두 최종 이미지에 포함됩니다. 멀티스테이지 빌드에서는 첫 번째 스테이지에서 빌드를 수행하고, 두 번째 스테이지에서 결과물만 COPY --from=builder로 가져옵니다. 이렇게 하면 세 가지 이점이 있습니다. 첫째, 이미지 크기가 대폭 줄어듭니다. 둘째, 빌드 도구의 취약점이 런타임 이미지에 포함되지 않습니다. 셋째, distroless나 scratch 같은 최소 베이스 이미지를 사용할 수 있어 쉘조차 없는 이미지가 가능합니다. Python의 경우 wheel을 먼저 빌드하고 런타임 스테이지에서 설치하는 패턴을 사용합니다."

**경험 연결**:
"폐쇄망에서 이미지 크기가 곧 배포 속도에 직결되었습니다. 멀티스테이지 도입 후 이미지 크기를 80% 이상 줄여 배포 시간을 단축하고, 스토리지 비용도 절감했습니다."

**주의**:
distroless/scratch 이미지에는 쉘이 없어 exec으로 디버깅이 불가하다. kubectl debug로 ephemeral container를 붙이거나, debug 스테이지를 별도로 유지하는 전략이 필요하다.

### Q3: "Docker 이미지 빌드 시 캐시가 무효화되는 조건은?"

**30초 답변**:
"어떤 레이어가 변경되면 해당 레이어부터 이후의 모든 레이어 캐시가 무효화됩니다. 따라서 변경이 적은 의존성 설치를 위에, 자주 변경되는 소스 코드를 아래에 배치하여 캐시 히트율을 높여야 합니다."

**2분 답변**:
"Docker 빌드 캐시는 레이어 단위로 작동합니다. RUN 명령어는 명령어 문자열이 동일하면 캐시를 사용하고, COPY/ADD는 소스 파일의 체크섬을 비교합니다. 핵심은 어떤 레이어의 캐시가 무효화되면 그 이후 모든 레이어가 재빌드된다는 것입니다. 그래서 package.json을 먼저 COPY하고 npm install을 실행한 뒤, 소스 코드를 COPY하는 패턴이 중요합니다. BuildKit을 사용하면 --mount=type=cache로 패키지 매니저 캐시를 빌드 간에 재사용할 수 있고, --mount=type=secret으로 시크릿을 레이어에 남기지 않고 전달할 수 있습니다."

**경험 연결**:
"CI 파이프라인에서 빌드 캐시가 없어 매번 전체 빌드가 수행되는 문제가 있었습니다. BuildKit의 캐시 마운트와 레지스트리 기반 캐시(--cache-to, --cache-from)를 적용하여 빌드 시간을 70% 단축했습니다."

**주의**:
`RUN apt-get update`만 단독 레이어로 만들면, 캐시된 상태에서 오래된 패키지 인덱스를 사용하게 된다. 반드시 `apt-get update && apt-get install`을 하나의 RUN으로 합쳐야 한다.

---

## Allganize 맥락

- **LLM 모델 이미지 최적화**: Alli AI의 LLM 모델 파일은 수 GB에 달할 수 있다. 모델 파일을 이미지에 포함하면 레이어가 거대해지므로, 모델은 PV/S3에서 마운트하고 이미지에는 런타임만 포함하는 것이 표준 패턴이다.
- **멀티 아키텍처**: AWS Graviton(ARM) 인스턴스를 비용 절감 목적으로 사용할 경우, `docker buildx`로 amd64/arm64 멀티 아키텍처 이미지를 빌드해야 한다.
- **CI/CD 빌드 캐시**: GitHub Actions에서 BuildKit의 레지스트리 캐시(`--cache-to type=registry`)를 활용하면 PR 빌드 시간을 대폭 단축할 수 있다.
- **베이스 이미지 표준화**: 팀 내에서 Python/Node.js/Go 베이스 이미지를 표준화하고 내부 레지스트리에서 관리하면, 보안 패치를 베이스 이미지 한 곳에서 적용하여 전체 서비스에 전파할 수 있다.

---
**핵심 키워드**: `OverlayFS` `Copy-on-Write` `Multi-stage Build` `레이어캐싱` `distroless` `BuildKit`
