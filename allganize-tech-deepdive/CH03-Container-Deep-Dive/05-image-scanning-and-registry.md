# 이미지 스캐닝과 레지스트리 (Image Scanning & Registry)

> **TL;DR**
> - **Trivy**는 오픈소스 취약점 스캐너로, 오프라인 지원이 가능하여 폐쇄망에서도 사용할 수 있다.
> - **Harbor**는 Self-hosted 레지스트리의 사실상 표준이며, 취약점 스캔/이미지 서명/복제를 내장한다.
> - **Cosign**으로 이미지에 서명하고, Admission Controller로 서명 검증을 강제하여 공급망 보안을 확보한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### 1. 이미지 취약점 스캐닝의 필요성

컨테이너 이미지에는 OS 패키지, 언어별 라이브러리, 설정 파일이 포함된다. 이 중 하나라도 알려진 취약점(CVE)이 있으면 공격 경로가 된다.

```
[이미지 구성 요소와 스캐닝 대상]

┌──────────────────────────────────┐
│  Application Code                │ ← SAST/DAST 영역
├──────────────────────────────────┤
│  Language Dependencies           │ ← Trivy 스캔
│  (npm, pip, go.mod, maven)      │    (CVE 데이터베이스 대조)
├──────────────────────────────────┤
│  OS Packages                     │ ← Trivy 스캔
│  (apt, apk, rpm)                │    (CVE 데이터베이스 대조)
├──────────────────────────────────┤
│  Base Image                      │ ← Trivy 스캔
│  (ubuntu, alpine, distroless)   │
└──────────────────────────────────┘
```

### 2. 취약점 심각도 (CVSS)

| 심각도 | CVSS 점수 | 대응 |
|--------|----------|------|
| **CRITICAL** | 9.0 - 10.0 | 즉시 패치, 배포 차단 |
| **HIGH** | 7.0 - 8.9 | 24시간 내 패치 |
| **MEDIUM** | 4.0 - 6.9 | 다음 릴리스에 포함 |
| **LOW** | 0.1 - 3.9 | 모니터링 |

### 3. 이미지 서명과 공급망 보안

**소프트웨어 공급망 공격**(SolarWinds, CodeCov 등)이 증가하면서, 이미지가 신뢰할 수 있는 파이프라인에서 빌드되었는지 **암호학적으로 검증**하는 것이 필수가 되었다.

```
[공급망 보안 체인]

Code → Build → Scan → Sign → Push → Verify → Deploy

  소스 코드    CI 빌드   취약점   Cosign    레지스트리  Admission   K8s
  (Git)       (BuildKit) 스캔    서명      (Harbor)   Controller  클러스터
                        (Trivy)  (개인키)             (공개키 검증)
```

### 4. Trivy 아키텍처

```
┌──────────────────────────────────────────────┐
│                    Trivy                      │
├──────────────┬───────────────────────────────┤
│   Scanner    │  Vulnerability DB             │
│              │  ┌─────────────────────┐      │
│  - OS Pkg    │  │ NVD (NIST)          │      │
│  - Language  │  │ GitHub Advisory     │      │
│  - IaC       │  │ Red Hat OVAL        │      │
│  - K8s       │  │ Alpine SecDB        │      │
│  - License   │  │ Debian Security     │      │
│              │  └─────────────────────┘      │
├──────────────┤                               │
│   Reporter   │  출력: Table, JSON, SARIF,    │
│              │  JUnit, CycloneDX, SPDX       │
└──────────────┴───────────────────────────────┘
```

### 5. 레지스트리 비교

| 항목 | Harbor | ECR (AWS) | ACR (Azure) | Docker Hub |
|------|--------|-----------|-------------|------------|
| **호스팅** | Self-hosted | AWS 관리형 | Azure 관리형 | SaaS |
| **취약점 스캔** | Trivy 내장 | Inspector 연동 | Defender 연동 | 유료 |
| **이미지 서명** | Cosign/Notary | 지원 | Notation | 미지원 |
| **복제** | Push/Pull 복제 | Cross-Region | Geo-Replication | 미지원 |
| **RBAC** | 프로젝트 기반 | IAM 정책 | AAD + RBAC | Organization |
| **Garbage Collection** | 수동/정책 기반 | 라이프사이클 정책 | 보존 정책 | 무료 제한 |
| **폐쇄망** | 최적 | N/A | N/A | N/A |
| **비용** | 인프라 비용만 | Pull 무료, 스토리지 과금 | 티어별 | 무료/유료 |

### 6. Cosign -- 이미지 서명/검증

Cosign은 Sigstore 프로젝트의 일부로, **컨테이너 이미지의 디지털 서명**을 생성하고 검증한다.

```
[Cosign 서명 흐름]

1. 키 생성
   cosign generate-key-pair → cosign.key(개인키) + cosign.pub(공개키)

2. 서명
   cosign sign --key cosign.key image:tag
   → OCI Artifact로 서명을 레지스트리에 저장
   → image:sha256-<digest>.sig

3. 검증
   cosign verify --key cosign.pub image:tag
   → 서명 다운로드 → 공개키로 검증 → 성공/실패

[Keyless 서명 (Sigstore Fulcio + Rekor)]
   cosign sign image:tag  (키 없이)
   → OIDC 토큰 (GitHub Actions 등)으로 인증
   → Fulcio가 단기 인증서 발급
   → Rekor 투명성 로그에 기록
   → 퍼블릭 환경에서 키 관리 부담 제거
```

---

## 실전 예시

### Trivy 기본 사용

```bash
# 이미지 스캔 (기본)
trivy image nginx:1.25

# 심각도 필터링
trivy image --severity HIGH,CRITICAL nginx:1.25

# CI/CD에서 사용: CRITICAL 발견 시 실패
trivy image --exit-code 1 --severity CRITICAL \
  harbor.internal.corp/myapp/backend:v1.0.0

# JSON 출력 (파이프라인 연동)
trivy image --format json --output result.json nginx:1.25

# SBOM 생성 (CycloneDX 형식)
trivy image --format cyclonedx --output sbom.json nginx:1.25

# Dockerfile 스캔 (설정 오류)
trivy config --severity HIGH,CRITICAL ./Dockerfile

# 파일시스템 스캔 (소스 코드 의존성)
trivy fs --scanners vuln,secret .

# Kubernetes 클러스터 스캔
trivy k8s --report summary cluster
```

### Trivy 오프라인 사용 (폐쇄망)

```bash
# === 외부망에서 ===

# 취약점 DB 다운로드
trivy image --download-db-only
# DB 위치: ~/.cache/trivy/db/trivy.db

# DB를 OCI Artifact로 Harbor에 Push (권장)
oras push harbor.external.com/trivy-db:latest \
  --artifact-type application/vnd.aquasecurity.trivy.db.layer.v1.tar+gzip \
  ~/.cache/trivy/db/db.tar.gz

# === 폐쇄망에서 ===

# Harbor 복제로 trivy-db 이미지 동기화 (또는 USB 반입)

# 오프라인 스캔
export TRIVY_DB_REPOSITORY=harbor.internal.corp/security/trivy-db
trivy image --skip-db-update \
  harbor.internal.corp/myapp/backend:v1.0.0

# 또는 로컬 캐시 직접 사용
trivy image --skip-db-update \
  --cache-dir /opt/trivy-cache \
  harbor.internal.corp/myapp/backend:v1.0.0
```

### Harbor 구축 및 운영

```bash
# Harbor Helm 설치
helm repo add harbor https://helm.goharbor.io
helm install harbor harbor/harbor \
  --namespace harbor --create-namespace \
  --set expose.type=ingress \
  --set expose.ingress.hosts.core=harbor.internal.corp \
  --set expose.tls.certSource=secret \
  --set expose.tls.secret.secretName=harbor-tls \
  --set persistence.persistentVolumeClaim.registry.size=500Gi \
  --set trivy.enabled=true

# 프로젝트 생성
curl -X POST "https://harbor.internal.corp/api/v2.0/projects" \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{"project_name": "myapp", "public": false}'

# Robot Account 생성 (CI/CD용)
curl -X POST "https://harbor.internal.corp/api/v2.0/robots" \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{
    "name": "ci-push",
    "duration": -1,
    "level": "project",
    "permissions": [{
      "namespace": "myapp",
      "kind": "project",
      "access": [
        {"resource": "repository", "action": "push"},
        {"resource": "repository", "action": "pull"}
      ]
    }]
  }'
```

### ECR / ACR 운영

```bash
# === AWS ECR ===

# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
  docker login --username AWS --password-stdin \
  123456789.dkr.ecr.ap-northeast-2.amazonaws.com

# 리포지토리 생성
aws ecr create-repository \
  --repository-name myapp/backend \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=AES256

# 라이프사이클 정책 (오래된 이미지 자동 삭제)
aws ecr put-lifecycle-policy \
  --repository-name myapp/backend \
  --lifecycle-policy-text '{
    "rules": [{
      "rulePriority": 1,
      "description": "Keep last 10 images",
      "selection": {
        "tagStatus": "any",
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": {"type": "expire"}
    }]
  }'

# === Azure ACR ===

# ACR 로그인
az acr login --name myregistry

# 이미지 Push
docker tag myapp:v1.0.0 myregistry.azurecr.io/myapp:v1.0.0
docker push myregistry.azurecr.io/myapp:v1.0.0

# Geo-Replication 설정 (Premium 티어)
az acr replication create \
  --registry myregistry \
  --location koreacentral
```

### Cosign 서명 및 검증

```bash
# 키 쌍 생성
cosign generate-key-pair
# → cosign.key (개인키, 암호화됨)
# → cosign.pub (공개키)

# 이미지 서명
cosign sign --key cosign.key \
  harbor.internal.corp/myapp/backend:v1.0.0

# 메타데이터 포함 서명
cosign sign --key cosign.key \
  -a "build-id=${BUILD_NUMBER}" \
  -a "git-sha=$(git rev-parse --short HEAD)" \
  -a "scanner=trivy" \
  -a "scan-result=pass" \
  harbor.internal.corp/myapp/backend:v1.0.0

# 서명 검증
cosign verify --key cosign.pub \
  harbor.internal.corp/myapp/backend:v1.0.0

# 특정 어노테이션 검증
cosign verify --key cosign.pub \
  -a "scan-result=pass" \
  harbor.internal.corp/myapp/backend:v1.0.0

# SBOM 서명 첨부
cosign attest --key cosign.key \
  --predicate sbom.json --type cyclonedx \
  harbor.internal.corp/myapp/backend:v1.0.0
```

### CI/CD 파이프라인 통합

```yaml
# GitHub Actions 예시
name: Image Pipeline
on:
  push:
    branches: [main]

jobs:
  build-scan-sign:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Build image
      run: |
        docker build -t $IMAGE:${{ github.sha }} .

    - name: Trivy scan
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: ${{ env.IMAGE }}:${{ github.sha }}
        format: 'sarif'
        output: 'trivy-results.sarif'
        severity: 'HIGH,CRITICAL'
        exit-code: '1'

    - name: Upload scan results
      uses: github/codeql-action/upload-sarif@v3
      if: always()
      with:
        sarif_file: 'trivy-results.sarif'

    - name: Push image
      run: docker push $IMAGE:${{ github.sha }}

    - name: Sign image (Cosign)
      uses: sigstore/cosign-installer@main
    - run: |
        cosign sign --key env://COSIGN_KEY \
          -a "git-sha=${{ github.sha }}" \
          -a "workflow=${{ github.workflow }}" \
          $IMAGE:${{ github.sha }}
      env:
        COSIGN_KEY: ${{ secrets.COSIGN_KEY }}
        COSIGN_PASSWORD: ${{ secrets.COSIGN_PASSWORD }}
```

```groovy
// Jenkins Pipeline 예시
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh "docker build -t ${IMAGE}:${BUILD_NUMBER} ."
            }
        }
        stage('Scan') {
            steps {
                sh """
                    trivy image --exit-code 1 \
                        --severity HIGH,CRITICAL \
                        --format template \
                        --template '@/usr/local/share/trivy/templates/junit.tpl' \
                        --output trivy-report.xml \
                        ${IMAGE}:${BUILD_NUMBER}
                """
                junit 'trivy-report.xml'
            }
        }
        stage('Push & Sign') {
            steps {
                sh "docker push ${IMAGE}:${BUILD_NUMBER}"
                withCredentials([file(credentialsId: 'cosign-key', variable: 'KEY')]) {
                    sh """
                        cosign sign --key ${KEY} \
                            -a "build-id=${BUILD_NUMBER}" \
                            ${IMAGE}:${BUILD_NUMBER}
                    """
                }
            }
        }
    }
}
```

### Kubernetes Admission Control (서명 검증)

```yaml
# Kyverno로 서명되지 않은 이미지 배포 차단
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  background: false
  rules:
  - name: verify-cosign
    match:
      any:
      - resources:
          kinds: ["Pod"]
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
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
---
# OPA Gatekeeper 대안
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: allowedregistries
spec:
  crd:
    spec:
      names:
        kind: AllowedRegistries
      validation:
        openAPIV3Schema:
          type: object
          properties:
            registries:
              type: array
              items:
                type: string
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package allowedregistries
      violation[{"msg": msg}] {
        container := input.review.object.spec.containers[_]
        not startswith(container.image, input.parameters.registries[_])
        msg := sprintf("Image %v is not from an allowed registry", [container.image])
      }
```

---

## 면접 Q&A

### Q1: "이미지 취약점 스캐닝을 CI/CD에 어떻게 통합하나요?"

**30초 답변**:
"Trivy를 CI 파이프라인의 Scan 스테이지에 넣고, HIGH/CRITICAL 취약점 발견 시 exit-code 1로 빌드를 실패시킵니다. 결과는 SARIF나 JUnit 형식으로 출력하여 리포트를 확인합니다."

**2분 답변**:
"이미지 파이프라인은 Build → Scan → Push → Sign 순서로 구성합니다. Trivy를 Scan 스테이지에 통합하는데, 세 가지 포인트가 중요합니다. 첫째, --exit-code 1 --severity HIGH,CRITICAL로 심각한 취약점 발견 시 파이프라인을 중단합니다. 둘째, 결과를 SARIF(GitHub CodeQL 연동) 또는 JUnit(Jenkins 연동) 형식으로 출력하여 대시보드에서 추적합니다. 셋째, SBOM(Software Bill of Materials)을 CycloneDX 형식으로 생성하여 자산 관리에 활용합니다. 폐쇄망에서는 Trivy 취약점 DB를 주기적으로 외부에서 다운로드하여 내부 Harbor에 OCI Artifact로 저장합니다. Harbor 자체에도 Trivy가 내장되어 Push 시 자동 스캔이 가능합니다."

**경험 연결**:
"폐쇄망 환경에서 Trivy DB 업데이트를 주 1회 자동화하고, 취약점 리포트를 보안팀에 자동 전달하는 프로세스를 구축한 경험이 있습니다. 오프라인 DB로도 충분히 효과적이었습니다."

**주의**:
취약점 스캔 결과에 fix가 없는(unfixed) CVE도 포함될 수 있다. 무조건 차단하면 배포가 막히므로, unfixed는 별도 트래킹하고 fixable 취약점만 차단하는 정책이 현실적이다.

### Q2: "Harbor를 선택한 이유와 운영 경험을 말씀해주세요."

**30초 답변**:
"Harbor는 CNCF graduated 프로젝트로 Self-hosted 레지스트리의 사실상 표준입니다. Trivy 내장 스캔, Cosign/Notary 서명, Pull/Push 복제, RBAC을 제공하며, 폐쇄망에서 완전 오프라인 운영이 가능합니다."

**2분 답변**:
"Harbor를 선택한 이유는 세 가지입니다. 첫째, 보안 기능이 통합되어 있습니다. Trivy 내장으로 Push 시 자동 취약점 스캔, Cosign/Notary로 이미지 서명 검증, 프로젝트 기반 RBAC으로 접근 제어가 가능합니다. 둘째, 복제(Replication) 기능으로 외부 레지스트리에서 내부로, 또는 멀티 사이트 간 이미지를 동기화할 수 있습니다. 셋째, 운영 편의성이 좋습니다. Helm으로 설치가 간단하고, 웹 UI로 관리가 직관적입니다. 운영 시 핵심은 스토리지 관리입니다. Garbage Collection과 태그 보존 정책(Immutable Tag + Retention Policy)으로 오래된 이미지를 자동 정리합니다. PV로 500GB 이상을 할당하고, 모니터링으로 디스크 사용률을 추적합니다."

**경험 연결**:
"폐쇄망에서 Harbor를 운영하면서, 외부 베이스 이미지(alpine, ubuntu, python)를 주기적으로 반입하는 프로세스와, 프로젝트별 로봇 계정으로 CI/CD 파이프라인 연동을 구성한 경험이 있습니다."

**주의**:
Harbor의 Garbage Collection은 UI에서 수동 실행하거나 cron으로 스케줄링해야 한다. GC 실행 중에는 Registry가 잠시 읽기 전용이 되므로, 사용량이 적은 시간에 실행해야 한다.

### Q3: "Cosign 이미지 서명이 왜 필요하고, 어떻게 동작하나요?"

**30초 답변**:
"Cosign은 이미지가 신뢰할 수 있는 파이프라인에서 빌드되었는지 암호학적으로 검증합니다. 개인키로 서명하고, K8s Admission Controller에서 공개키로 검증하여 서명되지 않은 이미지의 배포를 차단합니다."

**2분 답변**:
"공급망 공격(SolarWinds, Log4Shell)으로 이미지 신뢰성 검증이 필수가 되었습니다. Cosign의 동작은 세 단계입니다. 첫째, cosign generate-key-pair로 키 쌍을 생성합니다. 개인키는 CI 시크릿에 보관합니다. 둘째, CI 파이프라인에서 빌드 + 스캔 통과 후 cosign sign으로 서명합니다. 빌드 번호, Git SHA 같은 메타데이터를 어노테이션으로 함께 서명할 수 있습니다. 서명은 OCI Artifact로 레지스트리에 저장됩니다. 셋째, K8s에서 Kyverno 또는 Sigstore Policy Controller가 Pod 생성 시 이미지 서명을 검증합니다. 서명이 없거나 검증 실패 시 Pod 생성을 거부합니다. 퍼블릭 환경에서는 Keyless 서명(Fulcio + Rekor)으로 키 관리 부담을 줄일 수 있지만, 폐쇄망에서는 로컬 키 쌍을 사용합니다."

**경험 연결**:
"폐쇄망 환경에서 이미지 서명 체계를 도입할 때, Cosign의 로컬 키 모드가 외부 인프라(Fulcio, Rekor) 없이 동작하여 적합했습니다. Jenkins Credential에 개인키를 보관하고, K8s Admission Webhook으로 검증을 강제했습니다."

**주의**:
Cosign 서명은 이미지 다이제스트(sha256)에 대해 이루어진다. 태그가 아니라 다이제스트를 기준으로 서명하므로, 태그를 덮어써도 서명이 무효화되지 않는다. 하지만 태그와 다이제스트가 불일치하면 검증이 실패한다.

### Q4: "ECR과 ACR의 주요 기능과 차이점은?"

**30초 답변**:
"ECR은 AWS IAM과 통합되고 ECR Enhanced Scanning(Inspector)으로 취약점을 스캔합니다. ACR은 Azure AD와 통합되고 Defender for Containers로 보안을 강화합니다. 둘 다 해당 클라우드 K8s(EKS/AKS)와 네이티브 연동됩니다."

**2분 답변**:
"ECR은 IAM 정책으로 리포지토리별 접근 제어를 하고, 라이프사이클 정책으로 오래된 이미지를 자동 삭제합니다. Cross-Region Replication으로 다른 리전에 이미지를 복제할 수 있습니다. EKS 노드의 IAM Role로 인증하므로 imagePullSecret이 필요 없습니다. ACR은 Azure AD/RBAC으로 접근 제어하고, Premium 티어에서 Geo-Replication을 지원합니다. AKS의 Managed Identity로 인증하며, ACR Tasks로 레지스트리 내에서 이미지 빌드도 가능합니다. Allganize처럼 AWS와 Azure를 모두 사용하는 환경에서는, 각 클라우드의 네이티브 레지스트리를 사용하고 CI에서 양쪽에 Push하거나, Harbor를 중앙 레지스트리로 두고 ECR/ACR로 복제하는 전략을 택합니다."

**경험 연결**:
"온프레미스 Harbor에서 관리하던 이미지를 클라우드 환경으로 마이그레이션할 때, skopeo로 이미지를 일괄 복사하고 ECR 라이프사이클 정책을 설정한 경험이 있습니다."

**주의**:
ECR 로그인 토큰은 12시간 후 만료된다. CI/CD에서 매번 `aws ecr get-login-password`로 갱신하거나, credential helper를 설정해야 한다.

---

## Allganize 맥락

- **멀티 클라우드 레지스트리**: Allganize는 AWS와 Azure를 사용하므로, ECR과 ACR을 각각 운영하거나 Harbor를 중앙 레지스트리로 사용할 수 있다. CI 파이프라인에서 빌드 후 양쪽에 Push하는 것이 일반적이다.
- **LLM 이미지 보안**: AI 모델 서빙 이미지는 고가치 자산이므로, Cosign 서명과 SBOM 관리가 필수적이다. 모델 파일 자체는 이미지에 포함하지 않고 S3/Blob에서 마운트하되, 런타임 이미지의 보안을 Trivy로 지속 검증한다.
- **자동화**: Trivy 스캔 → 취약점 발견 → Slack/Teams 알림 → Jira 티켓 자동 생성 워크플로로 취약점 대응을 자동화한다.
- **규정 준수**: SOC2, ISO 27001 등 컴플라이언스 요구사항으로 이미지 서명, SBOM, 취약점 스캔 이력 보관이 필요할 수 있다. Harbor의 감사 로그와 Trivy 리포트를 중앙 보관한다.
- **공급망 보안**: SLSA(Supply-chain Levels for Software Artifacts) 프레임워크를 적용하여 빌드 출처를 증명하는 attestation을 이미지에 첨부할 수 있다.

---
**핵심 키워드**: `Trivy` `Harbor` `ECR` `ACR` `Cosign` `SBOM` `이미지서명` `공급망보안`
