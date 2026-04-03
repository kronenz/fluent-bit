# 컨테이너 이미지 파이프라인 (Container Image Pipeline)

> **TL;DR**
> - Dockerfile 멀티스테이지 빌드와 경량 베이스 이미지(distroless, Alpine)로 이미지 크기를 최소화하고 공격 표면을 줄인다
> - Trivy/Grype 등 보안 스캔을 CI 파이프라인에 필수 게이트로 넣고, Cosign으로 이미지 서명까지 자동화한다
> - 폐쇄망 환경에서는 Harbor를 내부 Registry로 운영하고, 이미지 미러링과 오프라인 취약점 DB 업데이트가 핵심이다

---

## 1. Dockerfile 최적화

### 멀티스테이지 빌드 (Multi-stage Build)

빌드 도구와 런타임을 분리하여 최종 이미지에는 실행에 필요한 바이너리만 포함한다.
빌드 의존성(컴파일러, 패키지 매니저)이 최종 이미지에 들어가지 않으므로 크기와 보안 모두 개선된다.

```dockerfile
# ---- Stage 1: Build ----
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download          # 의존성 캐싱 레이어
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /app/server ./cmd/server

# ---- Stage 2: Runtime ----
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /app/server /server
EXPOSE 8080
ENTRYPOINT ["/server"]
```

### 레이어 캐싱 전략 (Layer Caching)

Docker는 각 명령어(RUN, COPY 등)를 레이어로 만들고, 변경이 없으면 캐시를 재사용한다.
**자주 변경되는 명령어를 아래쪽에 배치**하는 것이 핵심이다.

```
좋은 예:                          나쁜 예:
COPY go.mod go.sum ./             COPY . .              ← 소스 변경 시
RUN go mod download               RUN go mod download      캐시 전부 무효화
COPY . .                          RUN go build
RUN go build
```

### .dockerignore

빌드 컨텍스트에서 불필요한 파일을 제외하여 빌드 속도를 높이고 민감 정보 유출을 방지한다.

```
.git
.github
node_modules
*.md
.env
.env.*
docker-compose*.yml
**/*_test.go
```

---

## 2. 이미지 크기 최소화

### 베이스 이미지 비교

| 베이스 이미지 | 크기 (대략) | 쉘 포함 | 패키지 매니저 | 적합한 경우 |
|---------------|-------------|---------|--------------|-------------|
| `ubuntu:24.04` | ~80MB | O | apt | 디버깅, 개발용 |
| `alpine:3.20` | ~7MB | O (ash) | apk | 경량화 + 디버깅 필요 시 |
| `distroless` | ~2-20MB | X | X | 프로덕션 (Go, Java, Python) |
| `scratch` | 0MB | X | X | 정적 바이너리 전용 |

### 실무 선택 가이드

```
정적 바이너리 (Go, Rust)?
  → scratch 또는 distroless/static

JVM 기반 (Java, Kotlin)?
  → distroless/java (JRE만 포함)

Python / Node.js?
  → distroless 또는 alpine + 필요 패키지만 설치

디버깅이 자주 필요한 환경?
  → alpine (쉘 있음, 경량)

폐쇄망에서 패키지 설치 어려움?
  → 빌드 서버에서 모든 의존성 포함 후 distroless로 복사
```

### 크기 최소화 팁

```dockerfile
# 1. 불필요한 캐시 제거
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# 2. 단일 RUN으로 레이어 최소화
RUN apk add --no-cache python3 py3-pip \
    && pip install --no-cache-dir -r requirements.txt

# 3. 실행 권한만 부여 (보안)
COPY --chmod=0755 --from=builder /app/server /server
USER nonroot:nonroot
```

---

## 3. 이미지 보안 스캔

### 도구 비교

| 도구 | 특징 | 오프라인 지원 | CI 통합 |
|------|------|--------------|---------|
| **Trivy** | Aqua Security, 빠른 속도, SBOM 지원 | O (DB 다운로드) | 우수 |
| **Grype** | Anchore, 경량, SBOM 기반 | O (DB 다운로드) | 우수 |
| **Snyk** | SaaS 기반, 수정 가이드 제공 | 제한적 | 우수 |

### Trivy 활용

```bash
# 이미지 스캔 (HIGH, CRITICAL만)
trivy image --severity HIGH,CRITICAL harbor.internal.corp/myapp/backend:v2.0.0

# SBOM 생성 (Software Bill of Materials)
trivy image --format spdx-json -o sbom.json myapp:latest

# 폐쇄망: 오프라인 DB 업데이트
# 인터넷 환경에서 DB 다운로드
trivy image --download-db-only
cp ~/.cache/trivy/db/trivy.db /media/usb/

# 폐쇄망 서버에서 DB 지정
trivy image --skip-db-update --cache-dir /opt/trivy-db/ myapp:latest
```

### CI 게이트로 보안 스캔 적용

스캔 결과에 CRITICAL 취약점이 있으면 파이프라인을 중단한다.
이것이 **Shift-Left Security**의 핵심이다.

```yaml
# GitHub Actions 예시
- name: Trivy 보안 스캔
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: ${{ env.IMAGE_TAG }}
    format: 'table'
    exit-code: '1'              # CRITICAL 발견 시 빌드 실패
    severity: 'CRITICAL,HIGH'
    ignore-unfixed: true        # 수정 불가 취약점은 무시
```

---

## 4. Registry 관리

### 주요 Registry 비교

| Registry | 환경 | 이미지 스캔 | 접근 제어 | 복제(Replication) |
|----------|------|------------|----------|-------------------|
| **ECR** (AWS) | 클라우드 | O (내장) | IAM | 리전 간 복제 |
| **ACR** (Azure) | 클라우드 | O (Defender) | Azure AD | 지역 복제 |
| **Harbor** | 온프레미스/폐쇄망 | O (Trivy 내장) | LDAP/OIDC | 원격 복제 |
| **Docker Hub** | 퍼블릭 | 제한적 | 토큰 | X |

### Harbor: 폐쇄망 필수 Registry

Harbor는 CNCF Graduated 프로젝트로, 폐쇄망 온프레미스 환경의 사실상(de facto) 표준 Registry이다.

```
[Harbor 핵심 기능]

1. 프로젝트 기반 접근 제어
   └─ LDAP/AD 연동으로 기존 인프라 인증 체계 활용

2. 이미지 스캔 내장
   └─ Trivy 스캐너 내장, 스캔 정책 자동 적용

3. 이미지 서명 (Cosign/Notary)
   └─ 서명되지 않은 이미지 배포 차단 정책

4. 복제 (Replication)
   └─ 외부 Registry → Harbor 미러링 (에어갭 환경 이미지 반입)
   └─ Harbor 간 복제 (멀티 클러스터 운영)

5. 가비지 컬렉션 (GC)
   └─ 미사용 이미지 레이어 자동 정리 → 디스크 절약
```

### 폐쇄망 이미지 반입 워크플로우

```
[인터넷 환경]                      [폐쇄망]
docker pull nginx:1.27        →    물리 매체 (USB, DVD)
docker save -o nginx.tar         또는 단방향 전송 장비
                                      ↓
                               docker load -i nginx.tar
                               docker tag nginx:1.27 \
                                 harbor.internal.corp/library/nginx:1.27
                               docker push harbor.internal.corp/library/nginx:1.27
```

---

## 5. 이미지 태깅 전략

### 태깅 방식 비교

| 전략 | 예시 | 장점 | 단점 |
|------|------|------|------|
| **SemVer** | `v1.2.3` | 의미 명확, 롤백 쉬움 | 수동 버전 관리 필요 |
| **Git SHA** | `abc1234` | 코드와 1:1 매핑 | 사람이 읽기 어려움 |
| **날짜 기반** | `20260403-1` | 빌드 시점 파악 쉬움 | 같은 날 여러 빌드 시 혼란 |
| **복합** | `v1.2.3-abc1234` | 의미 + 추적 가능 | 태그가 길어짐 |

### latest 안티패턴

```
[문제 상황]
이미지: myapp:latest

개발자 A: "최신 버전 배포했어요" (v2.0)
개발자 B: "저도 배포했는데요" (v2.1 덮어씀)
개발자 A: "롤백하고 싶은데 latest가 이미 v2.1이네요..."

→ latest는 어떤 버전인지 추적 불가
→ imagePullPolicy: Always가 아니면 캐시된 이전 이미지 사용
→ 프로덕션에서 latest 사용은 절대 금지
```

### 권장 태깅 전략

```yaml
# CI 파이프라인에서 생성하는 태그 예시
IMAGE_TAG="${SEMVER}-${GIT_SHA:0:7}"
# 예: v1.2.3-abc1234

# K8s 매니페스트에서 항상 고정 태그 사용
containers:
  - name: backend
    image: harbor.internal.corp/myapp/backend:v1.2.3-abc1234
    imagePullPolicy: IfNotPresent    # 고정 태그이므로 안전
```

---

## 6. 이미지 서명 (Image Signing)

### 왜 필요한가?

이미지 서명은 **"이 이미지가 신뢰할 수 있는 CI 파이프라인에서 빌드되었음"**을 증명한다.
서명되지 않은 이미지의 배포를 차단하면 공급망 공격(Supply Chain Attack)을 방어할 수 있다.

### Cosign (Sigstore)

```bash
# 키 생성
cosign generate-key-pair

# 이미지 서명
cosign sign --key cosign.key harbor.internal.corp/myapp/backend:v1.2.3

# 서명 검증
cosign verify --key cosign.pub harbor.internal.corp/myapp/backend:v1.2.3

# Keyless 서명 (OIDC 기반, 인터넷 환경)
cosign sign --identity-token=$(gcloud auth print-identity-token) \
  harbor.internal.corp/myapp/backend:v1.2.3
```

### K8s에서 서명 검증 강제 (Policy Controller)

```yaml
# Kyverno 정책: 서명된 이미지만 배포 허용
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-cosign-signature
    match:
      any:
      - resources:
          kinds:
          - Pod
    verifyImages:
    - imageReferences:
      - "harbor.internal.corp/*"
      attestors:
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
```

### 폐쇄망에서의 이미지 서명

```
[폐쇄망 서명 전략]

1. Cosign 키 페어를 내부 PKI(사내 인증 체계)로 관리
2. CI 서버에 서명 키를 안전하게 보관 (Vault, HSM)
3. 빌드 파이프라인에서 자동 서명
4. Harbor + Cosign 연동으로 서명 상태 확인
5. Kyverno/OPA Gatekeeper로 미서명 이미지 배포 차단
```

---

## 7. CI에서의 이미지 빌드 파이프라인 (GitHub Actions 예시)

### 전체 파이프라인 흐름

```
[코드 Push] → [Lint/Test] → [Docker Build] → [보안 스캔] → [이미지 서명] → [Registry Push] → [매니페스트 업데이트]
                                  ↓                ↓
                            멀티스테이지       CRITICAL 발견 시
                            빌드 최적화        파이프라인 중단
```

### GitHub Actions Workflow

```yaml
name: Container Image Pipeline
on:
  push:
    branches: [main]
    tags: ['v*']

env:
  REGISTRY: harbor.internal.corp
  IMAGE_NAME: myapp/backend

jobs:
  build-and-push:
    runs-on: self-hosted    # 폐쇄망: Self-hosted Runner 사용
    permissions:
      contents: read
      packages: write

    steps:
    # 1. 코드 체크아웃
    - name: 소스 코드 체크아웃
      uses: actions/checkout@v4

    # 2. 이미지 메타데이터 생성 (태그, 라벨)
    - name: 이미지 메타데이터 설정
      id: meta
      uses: docker/metadata-action@v5
      with:
        images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
        tags: |
          type=semver,pattern={{version}}
          type=semver,pattern={{major}}.{{minor}}
          type=sha,prefix=,format=short

    # 3. BuildKit 설정 (캐싱 지원)
    - name: Docker Buildx 설정
      uses: docker/setup-buildx-action@v3

    # 4. Registry 로그인
    - name: Harbor 로그인
      uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ secrets.HARBOR_USER }}
        password: ${{ secrets.HARBOR_PASSWORD }}

    # 5. 이미지 빌드 및 푸시
    - name: 이미지 빌드 & 푸시
      uses: docker/build-push-action@v5
      with:
        context: .
        push: true
        tags: ${{ steps.meta.outputs.tags }}
        labels: ${{ steps.meta.outputs.labels }}
        cache-from: type=registry,ref=${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:buildcache
        cache-to: type=registry,ref=${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:buildcache,mode=max

    # 6. 보안 스캔 (게이트)
    - name: Trivy 보안 스캔
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ steps.meta.outputs.version }}
        format: 'table'
        exit-code: '1'
        severity: 'CRITICAL,HIGH'
        ignore-unfixed: true

    # 7. 이미지 서명
    - name: Cosign 서명
      uses: sigstore/cosign-installer@v3
    - run: |
        cosign sign --key env://COSIGN_PRIVATE_KEY \
          ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ steps.meta.outputs.version }}
      env:
        COSIGN_PRIVATE_KEY: ${{ secrets.COSIGN_PRIVATE_KEY }}
        COSIGN_PASSWORD: ${{ secrets.COSIGN_PASSWORD }}

    # 8. GitOps 매니페스트 업데이트
    - name: K8s 매니페스트 이미지 태그 업데이트
      run: |
        git clone https://git.internal.corp/team/k8s-manifests.git
        cd k8s-manifests
        sed -i "s|image: .*backend:.*|image: ${REGISTRY}/${IMAGE_NAME}:${{ steps.meta.outputs.version }}|" \
          apps/backend/deployment.yaml
        git add . && git commit -m "chore: update backend image to ${{ steps.meta.outputs.version }}"
        git push
```

### 폐쇄망 CI 환경 구성 포인트

```
[폐쇄망 CI 체크리스트]

1. Self-hosted Runner
   └─ GitHub Actions Runner를 내부 서버에 설치
   └─ 또는 Jenkins, GitLab CI 등 온프레미스 CI 도구 사용

2. 빌드 캐시
   └─ Registry 기반 캐시 (Harbor에 buildcache 태그로 저장)
   └─ 로컬 디스크 캐시 (Runner 서버에 Docker 레이어 캐시 유지)

3. 의존성 미러
   └─ Go: GOPROXY 내부 미러 (Athens)
   └─ npm: Verdaccio 내부 Registry
   └─ pip: devpi 내부 미러
   └─ Docker: Harbor 프록시 캐시 프로젝트

4. 보안 스캔 DB
   └─ Trivy DB를 주기적으로 외부에서 다운로드 후 내부 반입
   └─ 스케줄링된 Job으로 DB 업데이트 자동화
```

---

## 8. 면접 Q&A

### Q1. "Dockerfile 최적화 방법을 설명해주세요"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "크게 세 가지입니다. 첫째, 멀티스테이지 빌드로 빌드 도구와 런타임을 분리합니다.
> Go나 Java처럼 컴파일 언어는 빌드 스테이지에서 바이너리를 만들고,
> distroless 같은 최소 이미지에 복사만 합니다. 둘째, 레이어 캐싱을 활용합니다.
> 의존성 파일(go.mod, package.json)을 먼저 복사하고 설치한 뒤에 소스 코드를 복사하면,
> 소스만 바뀌었을 때 의존성 레이어를 재사용할 수 있습니다.
> 셋째, .dockerignore로 불필요한 파일을 빌드 컨텍스트에서 제외합니다.
> 폐쇄망에서 근무할 때 이미지 크기가 네트워크 전송과 저장 공간에 직접 영향을 줬기 때문에
> 이런 최적화를 철저히 적용했습니다."

### Q2. "이미지 보안 스캔을 CI에 어떻게 통합하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "이미지 빌드 직후 Trivy 같은 도구로 스캔하고, CRITICAL 취약점이 발견되면
> 파이프라인을 실패시키는 게이트를 설정합니다. 이것이 Shift-Left Security입니다.
> 추가로 SBOM(Software Bill of Materials)을 생성해서 이미지에 포함된
> 모든 패키지와 버전을 추적합니다.
> 폐쇄망에서는 Trivy 취약점 DB를 인터넷 환경에서 주기적으로 다운로드한 뒤
> 물리 매체나 단방향 전송 장비로 반입하여 업데이트했습니다.
> DB가 최신이 아니면 새로운 CVE를 탐지하지 못하므로,
> 주 1~2회 업데이트 주기를 정해 운영했습니다."

### Q3. "latest 태그를 프로덕션에서 쓰면 안 되는 이유는?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "latest는 Mutable(가변) 태그이기 때문입니다.
> 누군가 새 이미지를 빌드하면 latest가 덮어씌워지는데,
> 이러면 현재 운영 중인 이미지가 정확히 어떤 코드 기반인지 추적할 수 없습니다.
> 롤백도 불가능합니다. 대신 SemVer와 Git SHA를 조합한 Immutable(불변) 태그를 사용합니다.
> 예를 들어 v1.2.3-abc1234 형태로 태깅하면 버전 의미도 명확하고
> 코드 커밋도 바로 찾을 수 있습니다.
> K8s에서 imagePullPolicy를 IfNotPresent로 설정해도 항상 올바른 이미지가 보장됩니다."

### Q4. "폐쇄망에서 컨테이너 이미지 관리는 어떻게 하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "Harbor를 내부 Registry로 운영합니다.
> 외부 이미지가 필요하면 인터넷 연결된 환경에서 docker save로 tar 파일을 만들고,
> 보안 검증 후 물리 매체로 반입하여 docker load 후 Harbor에 push합니다.
> 이 과정을 자동화하기 위해 이미지 반입 승인 워크플로우를 만들고,
> 반입 시 Trivy 스캔을 필수로 수행했습니다.
> Harbor의 프록시 캐시 기능을 활용하면 허용된 외부 접근이 있는 경우
> Docker Hub 미러링도 가능합니다.
> 가비지 컬렉션으로 미사용 레이어를 정리하여 스토리지도 관리했습니다."

### Q5. "이미지 서명은 왜 필요하고 어떻게 구현하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "이미지 서명은 공급망 보안(Supply Chain Security)의 핵심입니다.
> CI 파이프라인에서 빌드한 이미지만 프로덕션에 배포되도록 보장합니다.
> Cosign으로 빌드 시점에 서명하고, 클러스터에는 Kyverno 같은 Policy Engine으로
> 서명 검증을 강제하는 정책을 적용합니다.
> 서명되지 않은 이미지로 Pod를 생성하려 하면 Admission Webhook이 차단합니다.
> 폐쇄망에서는 Keyless(OIDC) 방식 대신 키 페어를 사내 PKI나 Vault에서 관리하고,
> CI 서버에서만 서명 키에 접근할 수 있도록 권한을 제한했습니다.
> 이렇게 하면 내부 개발자가 임의로 빌드한 이미지가 운영 환경에 배포되는 것을 원천 차단합니다."

---

## 키워드 (Keywords)

`Multi-stage Build` `Trivy` `Harbor` `Cosign` `Image Tagging Strategy`
