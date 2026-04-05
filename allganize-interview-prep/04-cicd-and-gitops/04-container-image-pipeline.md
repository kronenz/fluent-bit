# 컨테이너 이미지 파이프라인 (Container Image Pipeline)

> **TL;DR**
> - Dockerfile 최적화(멀티스테이지, 레이어 캐싱)로 빌드 시간과 이미지 크기를 줄인다
> - Trivy 등으로 이미지 취약점을 스캔하고, Cosign으로 서명하여 공급망(Supply Chain) 보안을 확보한다
> - 폐쇄망에서는 Harbor를 Private Registry로 사용하고, 오프라인 취약점 DB와 미러 관리가 핵심이다

---

## 1. Dockerfile 최적화

### 멀티스테이지 빌드 (Multi-stage Build)

빌드 도구와 런타임을 분리하여 최종 이미지 크기를 최소화한다.

```dockerfile
# ===== Stage 1: Build =====
FROM golang:1.22-alpine AS builder

WORKDIR /app

# 의존성 캐시 최적화: go.mod/go.sum을 먼저 복사
COPY go.mod go.sum ./
RUN go mod download

# 소스 코드 복사 및 빌드
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o /app/server ./cmd/server

# ===== Stage 2: Runtime =====
FROM alpine:3.19

# 보안: 비루트(non-root) 사용자
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# 필수 CA 인증서만 복사
RUN apk --no-cache add ca-certificates

WORKDIR /app
COPY --from=builder /app/server .

# 비루트 사용자로 전환
USER appuser

EXPOSE 8080
ENTRYPOINT ["./server"]
```

**결과 비교:**

```
golang:1.22 기반 단일 스테이지  → ~1.2GB
alpine + 멀티스테이지           → ~15MB
distroless 기반                → ~10MB
scratch 기반                   → ~7MB
```

### 레이어 캐싱 최적화

Docker는 각 명령어(Instruction)를 레이어(Layer)로 캐싱한다.
변경이 적은 레이어를 위에, 자주 변경되는 레이어를 아래에 배치한다.

```dockerfile
# Bad: 소스 변경 시 의존성도 다시 설치
COPY . .
RUN npm install
RUN npm run build

# Good: 의존성 캐시 활용
COPY package.json package-lock.json ./    # 변경 적음 (캐시 히트)
RUN npm ci --production                    # 캐시 히트 시 스킵
COPY . .                                   # 소스만 변경
RUN npm run build
```

### Node.js 멀티스테이지 예시

```dockerfile
# Stage 1: Dependencies
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Stage 2: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# Stage 3: Runtime
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
RUN addgroup -S nodejs && adduser -S nextjs -G nodejs

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

USER nextjs
EXPOSE 3000
CMD ["node", "dist/index.js"]
```

### Python 멀티스테이지 예시

```dockerfile
# Stage 1: Build
FROM python:3.12-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock ./
RUN poetry export -f requirements.txt --output requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim
WORKDIR /app

RUN groupadd -r appgroup && useradd -r -g appgroup appuser

COPY --from=builder /install /usr/local
COPY . .

USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Dockerfile 보안 베스트 프랙티스

```dockerfile
# 1. 특정 버전 태그 사용 (latest 금지)
FROM python:3.12.2-slim    # Good
# FROM python:latest        # Bad

# 2. 비루트 사용자
USER 1001

# 3. COPY 범위 최소화 (.dockerignore 활용)
COPY src/ ./src/

# 4. 빌드 인자(ARG)로 민감 정보 전달하지 않기
# ARG DB_PASSWORD    # Bad: 레이어에 남음

# 5. HEALTHCHECK 포함
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost:8080/healthz || exit 1

# 6. 읽기 전용 파일시스템
# docker run --read-only myapp
```

### .dockerignore

```
.git
.github
.env
*.md
node_modules
__pycache__
*.pyc
.pytest_cache
coverage/
dist/
.idea
.vscode
docker-compose*.yml
Makefile
```

---

## 2. 이미지 취약점 스캔 (Image Scanning)

### Trivy

Aqua Security에서 개발한 오픈소스 취약점 스캐너이다.
컨테이너 이미지, 파일시스템, Git 저장소, IaC 파일을 스캔한다.

```bash
# 이미지 스캔
trivy image harbor.internal.corp/myapp/backend:v1.0.0

# 심각도 필터링
trivy image --severity HIGH,CRITICAL \
  harbor.internal.corp/myapp/backend:v1.0.0

# CI/CD에서 사용: HIGH/CRITICAL 발견 시 실패(exit code 1)
trivy image --exit-code 1 --severity HIGH,CRITICAL \
  harbor.internal.corp/myapp/backend:v1.0.0

# JSON 포맷 출력 (파이프라인 연동)
trivy image --format json --output result.json \
  harbor.internal.corp/myapp/backend:v1.0.0

# SBOM(Software Bill of Materials) 생성
trivy image --format spdx-json --output sbom.json \
  harbor.internal.corp/myapp/backend:v1.0.0
```

### 폐쇄망에서 Trivy 오프라인 사용

```bash
# 외부망에서 취약점 DB 다운로드
trivy image --download-db-only
# DB 위치: ~/.cache/trivy/db/trivy.db

# 폐쇄망으로 DB 파일 전송 후
trivy image --skip-db-update \
  --cache-dir /opt/trivy-cache \
  harbor.internal.corp/myapp/backend:v1.0.0

# OCI 형식으로 DB를 Harbor에 저장 (권장)
# 외부망에서
oras push harbor.internal.corp/trivy-db:latest \
  --artifact-type application/vnd.aquasecurity.trivy.db.layer.v1.tar+gzip \
  db.tar.gz

# 폐쇄망 Trivy 설정
# TRIVY_DB_REPOSITORY=harbor.internal.corp/trivy-db
```

### CI 파이프라인 통합 (Jenkins)

```groovy
stage('Image Scan') {
    steps {
        sh """
            trivy image \
                --exit-code 1 \
                --severity HIGH,CRITICAL \
                --format template \
                --template '@/usr/local/share/trivy/templates/junit.tpl' \
                --output trivy-report.xml \
                ${IMAGE}:${BUILD_NUMBER}
        """
        junit 'trivy-report.xml'
    }
}
```

### CI 파이프라인 통합 (GitHub Actions)

```yaml
- name: Trivy vulnerability scan
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: ghcr.io/${{ github.repository }}:${{ github.sha }}
    format: 'sarif'
    output: 'trivy-results.sarif'
    severity: 'HIGH,CRITICAL'
    exit-code: '1'

- name: Upload scan results
  uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: 'trivy-results.sarif'
```

### Trivy vs Snyk 비교

| 항목 | Trivy | Snyk |
|------|-------|------|
| 라이선스 | 오픈소스 (Apache 2.0) | Freemium (무료 제한) |
| 스캔 대상 | 이미지, FS, IaC, K8s | 이미지, 코드, IaC |
| 오프라인 지원 | 가능 (DB 사전 다운로드) | 제한적 |
| CI 통합 | CLI 기반 (범용) | 전용 플러그인 |
| 수정 제안 | 취약 버전 정보 제공 | 자동 PR 생성 (Fix PR) |
| **폐쇄망** | **최적 (완전 오프라인)** | 클라우드 의존 |

---

## 3. Registry 관리

### Registry 비교

| 항목 | Harbor | ECR | ACR | Docker Hub |
|------|--------|-----|-----|------------|
| 호스팅 | Self-hosted | AWS | Azure | SaaS |
| 취약점 스캔 | 내장 (Trivy) | 내장 | Defender | 유료 |
| 이미지 서명 | Cosign/Notary | 지원 | Notation | 미지원 |
| 복제(Replication) | Pull/Push 복제 | Cross-Region | Geo-Replication | 미지원 |
| RBAC | 프로젝트 기반 | IAM | AAD | Organization |
| **폐쇄망** | **최적** | N/A | N/A | N/A |

### Harbor 구축 및 운영

```bash
# Harbor 설치 (Helm)
helm repo add harbor https://helm.goharbor.io
helm install harbor harbor/harbor \
  --namespace harbor --create-namespace \
  --set expose.type=ingress \
  --set expose.ingress.hosts.core=harbor.internal.corp \
  --set expose.tls.certSource=secret \
  --set expose.tls.secret.secretName=harbor-tls \
  --set persistence.persistentVolumeClaim.registry.size=500Gi \
  --set persistence.persistentVolumeClaim.database.size=10Gi \
  --set trivy.enabled=true \
  --set notary.enabled=true

# 프로젝트 생성
curl -X POST "https://harbor.internal.corp/api/v2.0/projects" \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{
    "project_name": "myapp",
    "public": false,
    "storage_limit": 107374182400
  }'
```

### Harbor 이미지 복제 (Replication)

```
[외부 Harbor]                    [내부 Harbor (폐쇄망)]
harbor.external.com    ──Push──→  harbor.internal.corp
                      Replication
                       Policy

사용 사례:
- 외부 베이스 이미지를 내부로 복제
- 멀티 사이트 간 이미지 동기화
```

### 이미지 정리 (Garbage Collection)

```bash
# Harbor UI 또는 API로 Garbage Collection 실행
# 태그 보존 정책 설정
curl -X POST "https://harbor.internal.corp/api/v2.0/projects/myapp/immutabletagrules" \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{
    "tag_selectors": [{"kind": "doublestar", "decoration": "matches", "pattern": "v*"}],
    "scope_selectors": {"repository": [{"kind": "doublestar", "decoration": "repoMatches", "pattern": "**"}]}
  }'
```

### 이미지 Pull 설정 (K8s)

```yaml
# ImagePullSecret 생성
kubectl create secret docker-registry harbor-cred \
  --docker-server=harbor.internal.corp \
  --docker-username=robot-deploy \
  --docker-password=${ROBOT_TOKEN} \
  -n backend

# Pod에서 사용
apiVersion: v1
kind: Pod
spec:
  imagePullSecrets:
  - name: harbor-cred
  containers:
  - name: backend
    image: harbor.internal.corp/myapp/backend:v1.0.0

# ServiceAccount에 기본 설정 (권장)
kubectl patch serviceaccount default -n backend \
  -p '{"imagePullSecrets": [{"name": "harbor-cred"}]}'
```

---

## 4. 이미지 태깅 전략 (Image Tagging Strategy)

### 안티패턴: latest 태그

```bash
# Bad: 재현 불가능, 어떤 버전인지 알 수 없음
docker build -t myapp:latest .
docker push myapp:latest
```

### 권장 태깅 전략

```bash
# 1. Git Commit SHA (가장 정확한 추적)
IMAGE_TAG=$(git rev-parse --short HEAD)    # e.g., a1b2c3d
docker build -t myapp:${IMAGE_TAG} .

# 2. Semantic Versioning (릴리스용)
docker build -t myapp:v1.2.3 .
docker tag myapp:v1.2.3 myapp:v1.2    # 마이너 버전 태그
docker tag myapp:v1.2.3 myapp:v1      # 메이저 버전 태그

# 3. Git SHA + 빌드 번호 (CI 환경)
docker build -t myapp:${BUILD_NUMBER}-${GIT_SHA} .
# e.g., myapp:142-a1b2c3d

# 4. 날짜 + Git SHA (시간 기반 추적)
IMAGE_TAG=$(date +%Y%m%d)-${GIT_SHA}
docker build -t myapp:${IMAGE_TAG} .
# e.g., myapp:20240315-a1b2c3d
```

### Immutable Tag 정책

```yaml
# Harbor에서 Immutable Tag 설정
# 한 번 Push된 태그는 덮어쓸 수 없음

# Kubernetes에서 항상 Pull 강제
spec:
  containers:
  - name: backend
    image: harbor.internal.corp/myapp/backend:v1.0.0
    imagePullPolicy: Always    # 태그가 같아도 항상 Pull
```

---

## 5. 이미지 서명 (Image Signing) - Cosign

### Cosign이란?

Sigstore 프로젝트의 컨테이너 이미지 서명/검증 도구이다.
이미지가 신뢰할 수 있는 소스에서 빌드되었는지 검증한다.

### 서명 및 검증

```bash
# 키 쌍 생성
cosign generate-key-pair
# cosign.key (개인키), cosign.pub (공개키) 생성

# 이미지 서명
cosign sign --key cosign.key \
  harbor.internal.corp/myapp/backend:v1.0.0

# 메타데이터 추가 서명
cosign sign --key cosign.key \
  -a "build-id=142" \
  -a "git-sha=a1b2c3d" \
  -a "pipeline=jenkins" \
  harbor.internal.corp/myapp/backend:v1.0.0

# 서명 검증
cosign verify --key cosign.pub \
  harbor.internal.corp/myapp/backend:v1.0.0

# 특정 어노테이션 포함 여부 검증
cosign verify --key cosign.pub \
  -a "pipeline=jenkins" \
  harbor.internal.corp/myapp/backend:v1.0.0
```

### CI 파이프라인에 서명 통합

```groovy
// Jenkinsfile
stage('Sign Image') {
    steps {
        withCredentials([file(credentialsId: 'cosign-key', variable: 'COSIGN_KEY')]) {
            sh """
                cosign sign --key ${COSIGN_KEY} \
                    -a "build-id=${BUILD_NUMBER}" \
                    -a "git-sha=${GIT_COMMIT}" \
                    ${IMAGE}:${BUILD_NUMBER}
            """
        }
    }
}
```

### K8s에서 서명 검증 (Policy Controller)

```yaml
# Kyverno를 사용한 서명 검증 정책
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
  - name: verify-cosign-signature
    match:
      any:
      - resources:
          kinds:
          - Pod
    verifyImages:
    - imageReferences:
      - "harbor.internal.corp/myapp/*"
      attestors:
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
```

```
[이미지 서명 흐름]

CI Pipeline
  │
  ├── Build Image
  ├── Scan (Trivy)
  ├── Sign (Cosign) ──── cosign.key (개인키)
  └── Push to Harbor
                           │
                           ▼
K8s Cluster ← Admission Controller (Kyverno)
                    │
                    ├── cosign.pub (공개키)로 서명 검증
                    ├── 검증 성공 → Pod 생성 허용
                    └── 검증 실패 → Pod 생성 거부
```

---

## 6. 전체 이미지 파이프라인 (End-to-End)

```
[전체 파이프라인 흐름]

1. Code Push
   └── Git Repository

2. CI Trigger
   └── Jenkins / GitHub Actions

3. Build
   ├── Dockerfile Lint (hadolint)
   ├── Multi-stage Build
   └── 레이어 캐시 활용

4. Test
   ├── Unit Test
   └── Integration Test

5. Scan
   ├── SAST (SonarQube)
   ├── Image Scan (Trivy)
   └── License Check

6. Sign
   └── Cosign 서명

7. Push
   └── Harbor Registry

8. Deploy
   ├── ArgoCD Sync
   └── Argo Rollouts (Canary/Blue-Green)

9. Verify
   ├── Smoke Test
   └── Monitoring Check
```

### 자동화 스크립트 (통합 예시)

```bash
#!/bin/bash
# build-scan-sign-push.sh
set -euo pipefail

IMAGE="harbor.internal.corp/myapp/backend"
GIT_SHA=$(git rev-parse --short HEAD)
TAG="${BUILD_NUMBER:-local}-${GIT_SHA}"
FULL_IMAGE="${IMAGE}:${TAG}"

echo "=== [1/5] Dockerfile Lint ==="
hadolint Dockerfile --failure-threshold error

echo "=== [2/5] Build ==="
docker build \
    --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
    --build-arg GIT_SHA=${GIT_SHA} \
    --label "org.opencontainers.image.revision=${GIT_SHA}" \
    -t ${FULL_IMAGE} .

echo "=== [3/5] Scan ==="
trivy image --exit-code 1 --severity HIGH,CRITICAL ${FULL_IMAGE}

echo "=== [4/5] Push ==="
docker push ${FULL_IMAGE}

echo "=== [5/5] Sign ==="
cosign sign --key ${COSIGN_KEY_PATH} \
    -a "build-id=${BUILD_NUMBER}" \
    -a "git-sha=${GIT_SHA}" \
    ${FULL_IMAGE}

echo "Image pipeline completed: ${FULL_IMAGE}"
```

---

## 7. 면접 Q&A

### Q1. "Dockerfile 최적화 경험을 설명해주세요"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "세 가지 방법을 주로 사용합니다.
> 첫째, 멀티스테이지 빌드로 빌드 도구와 런타임을 분리합니다.
> Go 애플리케이션의 경우 1.2GB에서 15MB로 줄였습니다.
> 둘째, 레이어 캐싱을 활용합니다. 의존성 파일(go.mod, package.json)을
> 소스 코드보다 먼저 COPY하면 의존성이 변경되지 않았을 때 캐시를 재사용합니다.
> 셋째, .dockerignore로 불필요한 파일(테스트, 문서, .git)을 빌드 컨텍스트에서 제외합니다.
> 폐쇄망에서는 빌드 시간이 곧 배포 시간이므로 이런 최적화가 특히 중요했습니다."

### Q2. "이미지 취약점 스캔을 CI/CD에 어떻게 통합하나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "Trivy를 CI 파이프라인의 Scan 스테이지에 통합합니다.
> HIGH/CRITICAL 취약점이 발견되면 exit-code 1을 반환하도록 설정하여
> 파이프라인이 실패하도록 합니다. 결과는 JUnit이나 SARIF 형식으로 출력하여
> Jenkins나 GitHub에서 리포트를 확인할 수 있게 합니다.
> 폐쇄망에서는 Trivy의 취약점 DB를 주기적으로 외부에서 다운로드하여
> 내부로 반입하는 프로세스를 만들었습니다.
> Harbor에 내장된 Trivy를 활용하면 Push 시 자동 스캔도 가능합니다."

### Q3. "latest 태그를 사용하면 안 되는 이유는?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "세 가지 이유가 있습니다.
> 첫째, 재현 불가능(Non-reproducible)합니다. 어떤 커밋으로 빌드된 이미지인지 알 수 없습니다.
> 둘째, 롤백이 불가능합니다. latest가 덮어씌워지면 이전 버전을 복구할 수 없습니다.
> 셋째, K8s에서 imagePullPolicy가 기본적으로 Always가 아니면 캐시된 이미지를 사용하여
> 업데이트가 반영되지 않을 수 있습니다.
> 대신 Git Commit SHA나 Semantic Versioning을 사용하고,
> Immutable Tag 정책을 적용하는 것을 권장합니다."

### Q4. "폐쇄망에서 컨테이너 레지스트리를 어떻게 관리하셨나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "Harbor를 Private Registry로 사용했습니다. 핵심 운영 포인트가 세 가지 있었습니다.
> 첫째, 베이스 이미지 관리입니다. alpine, ubuntu 같은 공식 이미지를
> 주기적으로 외부에서 Pull하여 내부 Harbor로 Push하는 프로세스를 만들었습니다.
> 둘째, 취약점 스캔입니다. Harbor 내장 Trivy를 활용했고,
> 오프라인 DB를 주 1회 업데이트했습니다.
> 셋째, 스토리지 관리입니다. Garbage Collection과 태그 보존 정책으로
> 오래된 이미지를 자동 정리하여 디스크 공간을 관리했습니다."

### Q5. "이미지 서명(Cosign)은 왜 필요한가요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "소프트웨어 공급망 보안(Supply Chain Security) 때문입니다.
> SolarWinds 사건처럼 빌드 과정에서 악성 코드가 삽입될 수 있습니다.
> Cosign으로 이미지에 서명하고, K8s의 Admission Controller(Kyverno 등)에서
> 서명을 검증하면 신뢰할 수 있는 파이프라인에서 빌드된 이미지만 배포할 수 있습니다.
> 폐쇄망에서는 외부 키 서버 없이 로컬 키 쌍으로 운영했고,
> 서명 키는 Jenkins Credential에 안전하게 보관했습니다.
> SBOM(Software Bill of Materials)과 함께 사용하면 더욱 완벽한 보안 체계가 됩니다."

---

## 키워드 (Keywords)

`Multi-stage Build` `Trivy` `Harbor` `Image Tagging` `Cosign`
