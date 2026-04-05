# Supply Chain Security: Image Signing, SBOM, Vulnerability Scanning

> **TL;DR**: 소프트웨어 공급망 보안(Supply Chain Security)은 코드 작성부터 프로덕션 배포까지 전 과정의 무결성과 신뢰성을 보장하는 것이다.
> cosign/Notary로 컨테이너 이미지에 서명하고, SBOM(Software Bill of Materials)으로 구성 요소를 투명하게 관리하며, Trivy/Grype 등으로 취약점을 CI/CD 파이프라인에서 자동 스캔한다.
> Admission Controller(Kyverno/OPA)로 서명되지 않은 이미지의 배포를 차단하여 신뢰 체인을 완성한다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 15min

---

## 핵심 개념

### 소프트웨어 공급망 공격 벡터

```
  ┌──────────────────────────────────────────────────┐
  │  소프트웨어 공급망 (Software Supply Chain)         │
  │                                                   │
  │  Source Code ──► Build ──► Registry ──► Deploy     │
  │       │            │          │           │        │
  │       ▼            ▼          ▼           ▼        │
  │  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌────────┐  │
  │  │악성 코드 │ │빌드 변조 │ │이미지  │ │미서명  │  │
  │  │주입      │ │CI 파이프 │ │교체/   │ │이미지  │  │
  │  │(의존성   │ │라인 침해 │ │변조    │ │배포    │  │
  │  │ 오염)    │ │          │ │        │ │        │  │
  │  └─────────┘ └──────────┘ └────────┘ └────────┘  │
  │                                                   │
  │  대표 사례:                                        │
  │  • SolarWinds (2020) - 빌드 파이프라인 침해         │
  │  • Log4Shell (2021) - 의존성 취약점                 │
  │  • Codecov (2021) - CI 스크립트 변조                │
  └──────────────────────────────────────────────────┘
```

### SLSA (Supply-chain Levels for Software Artifacts)

```
  SLSA Levels (공급망 보안 성숙도 프레임워크)

  Level 0: 보호 없음
  Level 1: 빌드 프로세스 문서화, 서명
  Level 2: 호스팅된 빌드 서비스 사용 (GitHub Actions 등)
  Level 3: 빌드 플랫폼의 소스/빌드 무결성 검증
  Level 4: 2인 리뷰 + 재현 가능한 빌드 (Hermetic Build)

  ┌──────────┬──────────┬──────────┬──────────┐
  │ Level 1  │ Level 2  │ Level 3  │ Level 4  │
  │ 빌드     │ 호스팅   │ 소스     │ 2인 리뷰 │
  │ 문서화   │ 빌드     │ 무결성   │ 재현빌드 │
  │ + 서명   │ 서비스   │ 검증     │          │
  └──────────┴──────────┴──────────┴──────────┘
       ▲ 보안 성숙도 증가
```

### 이미지 서명 (cosign / Sigstore)

```
  ┌──────────────────────────────────────────────┐
  │  cosign 서명 흐름 (Keyless / Fulcio)          │
  │                                               │
  │  개발자/CI                                     │
  │    │                                           │
  │    │ 1. OIDC 인증 (GitHub Actions OIDC 등)     │
  │    ▼                                           │
  │  ┌──────────┐                                  │
  │  │  Fulcio   │ ── 2. 단기 서명 인증서 발급      │
  │  │  (CA)     │                                  │
  │  └────┬─────┘                                  │
  │       │ 3. 인증서로 이미지 서명                  │
  │       ▼                                        │
  │  ┌──────────┐     ┌──────────┐                 │
  │  │ Container │     │  Rekor   │                 │
  │  │ Registry  │     │(투명성   │                 │
  │  │ (서명저장)│     │ 로그)    │ ── 4. 서명 기록 │
  │  └──────────┘     └──────────┘                 │
  │                                               │
  │  검증 시:                                      │
  │  cosign verify → Rekor에서 서명 확인           │
  │                → 인증서 체인 검증               │
  │                → 이미지 다이제스트 매칭          │
  └──────────────────────────────────────────────┘
```

```bash
# cosign으로 이미지 서명 (Key Pair 방식)
cosign generate-key-pair

# 이미지 서명 (반드시 digest 기반)
cosign sign --key cosign.key \
  company-registry.io/ai-model@sha256:abc123...

# Keyless 서명 (CI/CD에서 권장)
# GitHub Actions OIDC → Fulcio → 단기 인증서 자동 발급
cosign sign --yes \
  company-registry.io/ai-model@sha256:abc123...

# 서명 검증
cosign verify --key cosign.pub \
  company-registry.io/ai-model@sha256:abc123...

# Keyless 검증 (OIDC issuer + subject 확인)
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp "github.com/company/ai-model" \
  company-registry.io/ai-model@sha256:abc123...
```

### Notary v2 (OCI 표준)

```bash
# Notation (Notary v2 CLI)으로 서명
notation sign \
  --key my-signing-key \
  company-registry.io/ai-model@sha256:abc123...

# 검증
notation verify \
  company-registry.io/ai-model@sha256:abc123...

# Trust Policy 설정 (~/.config/notation/trustpolicy.json)
{
  "version": "1.0",
  "trustPolicies": [{
    "name": "company-images",
    "registryScopes": ["company-registry.io/*"],
    "signatureVerification": { "level": "strict" },
    "trustStores": ["ca:company-ca"],
    "trustedIdentities": ["x509.subject: CN=company-signer"]
  }]
}
```

### SBOM (Software Bill of Materials)

```
  ┌──────────────────────────────────────────┐
  │  SBOM = 소프트웨어 "부품 목록"             │
  │                                           │
  │  ai-model:v1.2.3                          │
  │  ├── python:3.11-slim (base image)        │
  │  │   ├── libc 2.36-9                      │
  │  │   ├── openssl 3.0.11                   │
  │  │   └── ...                              │
  │  ├── torch 2.1.0 (pip)                    │
  │  │   └── nvidia-cuda-runtime 12.1         │
  │  ├── transformers 4.35.0 (pip)            │
  │  ├── fastapi 0.104.0 (pip)               │
  │  └── ...                                  │
  │                                           │
  │  형식: SPDX / CycloneDX                    │
  └──────────────────────────────────────────┘
```

```bash
# Syft로 SBOM 생성
syft company-registry.io/ai-model:v1 -o spdx-json > sbom.spdx.json
syft company-registry.io/ai-model:v1 -o cyclonedx-json > sbom.cdx.json

# SBOM을 OCI 아티팩트로 레지스트리에 첨부
cosign attach sbom --sbom sbom.spdx.json \
  company-registry.io/ai-model@sha256:abc123...

# SBOM 기반 취약점 스캔
grype sbom:sbom.spdx.json
```

### 취약점 스캔 파이프라인

```
  ┌──────────────────────────────────────────────────┐
  │  CI/CD 취약점 스캔 파이프라인                      │
  │                                                   │
  │  1. 코드 단계 (Shift Left)                        │
  │     ├── 의존성 스캔: Dependabot, Snyk             │
  │     ├── 코드 분석: Semgrep, CodeQL                │
  │     └── Secret 스캔: Gitleaks, TruffleHog         │
  │                                                   │
  │  2. 빌드 단계                                     │
  │     ├── 이미지 스캔: Trivy, Grype                 │
  │     ├── SBOM 생성: Syft                           │
  │     ├── 이미지 서명: cosign                       │
  │     └── 정적 분석: Dockerfile lint (Hadolint)     │
  │                                                   │
  │  3. 배포 단계 (Admission)                         │
  │     ├── 서명 검증: Kyverno / OPA                  │
  │     ├── 취약점 등급 게이트: Critical/High 차단     │
  │     └── 이미지 출처 제한: 허용된 레지스트리만      │
  │                                                   │
  │  4. 런타임 단계                                   │
  │     ├── 지속적 스캔: Trivy Operator               │
  │     └── 새 CVE 발견 시 알림                       │
  └──────────────────────────────────────────────────┘
```

```yaml
# Trivy를 CI/CD에 통합 (GitHub Actions 예시)
name: Container Security
on: push

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
    - name: Build image
      run: docker build -t ai-model:${{ github.sha }} .

    - name: Run Trivy vulnerability scanner
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: ai-model:${{ github.sha }}
        format: table
        exit-code: 1                    # 취약점 발견 시 빌드 실패
        severity: CRITICAL,HIGH         # Critical/High만 차단
        ignore-unfixed: true            # 패치 없는 취약점 무시

    - name: Generate SBOM
      run: syft ai-model:${{ github.sha }} -o spdx-json > sbom.json

    - name: Sign image
      run: cosign sign --yes company-registry.io/ai-model@${{ steps.push.outputs.digest }}
```

### Admission Controller로 서명 강제

```yaml
# Kyverno: 서명된 이미지만 배포 허용
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  background: false
  rules:
  - name: verify-cosign-signature
    match:
      any:
      - resources:
          kinds: ["Pod"]
    verifyImages:
    - imageReferences:
      - "company-registry.io/*"
      attestors:
      - count: 1
        entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
    - imageReferences:
      - "*"
      required: false    # 외부 이미지는 선택적 검증

---
# OPA/Gatekeeper: 허용된 레지스트리만 사용
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sAllowedRepos
metadata:
  name: allowed-repos
spec:
  match:
    kinds:
    - apiGroups: [""]
      kinds: ["Pod"]
  parameters:
    repos:
    - "company-registry.io/"
    - "public.ecr.aws/company/"
```

---

## 실전 예시

### 완전한 CI/CD 보안 파이프라인

```bash
#!/bin/bash
# build-and-secure.sh

IMAGE="company-registry.io/ai-model"
TAG="${GIT_SHA}"
FULL="${IMAGE}:${TAG}"

# 1. Dockerfile 린트
hadolint Dockerfile --failure-threshold error

# 2. Secret 스캔 (소스코드에 하드코딩된 시크릿 탐지)
gitleaks detect --source . --verbose

# 3. 이미지 빌드
docker build -t "${FULL}" .

# 4. 취약점 스캔 (Critical/High 발견 시 실패)
trivy image --exit-code 1 --severity CRITICAL,HIGH \
  --ignore-unfixed "${FULL}"

# 5. SBOM 생성
syft "${FULL}" -o spdx-json > sbom.spdx.json

# 6. Push
docker push "${FULL}"
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${FULL}")

# 7. 이미지 서명 (digest 기반)
cosign sign --key cosign.key "${DIGEST}"

# 8. SBOM 첨부
cosign attach sbom --sbom sbom.spdx.json "${DIGEST}"

# 9. SBOM 서명
cosign sign --key cosign.key --attachment sbom "${DIGEST}"

echo "Signed image: ${DIGEST}"
```

### Trivy Operator (런타임 지속 스캔)

```yaml
# Trivy Operator 설치 후 자동 생성되는 VulnerabilityReport
apiVersion: aquasecurity.github.io/v1alpha1
kind: VulnerabilityReport
metadata:
  name: deployment-ai-model-ai-model
  namespace: ai-serving
report:
  scanner:
    name: Trivy
    version: 0.48.0
  summary:
    criticalCount: 0
    highCount: 2
    mediumCount: 15
    lowCount: 42
  vulnerabilities:
  - vulnerabilityID: CVE-2024-xxxx
    severity: HIGH
    resource: libssl3
    installedVersion: 3.0.11
    fixedVersion: 3.0.13
    title: "OpenSSL: Buffer overflow in..."
```

---

## 면접 Q&A

### Q: 컨테이너 이미지 서명(cosign)의 필요성과 동작 원리를 설명해주세요.
**30초 답변**:
이미지 서명은 "이 이미지가 신뢰할 수 있는 빌드 파이프라인에서 생성되었고 변조되지 않았음"을 보증합니다. cosign은 이미지 다이제스트에 서명하고, Admission Controller에서 검증하여 미서명 이미지의 배포를 차단합니다.

**2분 답변**:
SolarWinds 사태 이후 공급망 보안이 핵심 화두가 되었습니다. 이미지 서명의 핵심은 무결성(Integrity)과 출처 증명(Provenance)입니다. cosign은 Sigstore 프로젝트의 일부로, Key Pair 방식과 Keyless 방식을 지원합니다. Key Pair 방식은 전통적인 공개키 암호화로 서명합니다. Keyless 방식은 CI/CD 환경에서 OIDC 토큰으로 Fulcio CA에서 단기 인증서를 발급받아 서명하고, Rekor 투명성 로그에 서명 기록을 남깁니다. 서명은 반드시 이미지 다이제스트(sha256) 기반이어야 합니다. 태그(latest, v1 등)는 가변적이므로 서명이 무의미해집니다. Kubernetes에서는 Kyverno나 OPA Gatekeeper의 verifyImages 규칙으로 서명되지 않은 이미지의 배포를 Admission 단계에서 차단합니다. 이것이 "빌드에서 배포까지의 신뢰 체인(Chain of Trust)"을 완성합니다.

**💡 경험 연결**:
폐쇄망 환경에서 내부 레지스트리의 이미지 무결성을 관리한 경험이 있습니다. 당시에는 이미지 다이제스트를 수동으로 기록하고 배포 시 검증했는데, cosign과 Admission Controller를 도입하면 이 과정을 자동화할 수 있습니다.

**⚠️ 주의**:
이미지 태그(`:v1`, `:latest`)로 서명하면 안 된다. 태그는 다른 이미지를 가리킬 수 있으므로 반드시 **다이제스트**(`@sha256:...`)로 서명해야 한다.

### Q: SBOM(Software Bill of Materials)이 왜 중요하고, 어떻게 활용하나요?
**30초 답변**:
SBOM은 소프트웨어에 포함된 모든 구성 요소(라이브러리, 버전)의 목록입니다. Log4Shell 같은 취약점 발생 시 "우리 시스템에 해당 컴포넌트가 있는가"를 즉시 파악할 수 있어 보안 사고 대응 시간을 크게 단축합니다.

**2분 답변**:
SBOM은 소프트웨어의 "성분표"입니다. SPDX와 CycloneDX 두 가지 표준 형식이 있으며, Syft, Trivy 등으로 생성합니다. 활용 시나리오는 세 가지입니다. 첫째, 제로데이 취약점 대응입니다. Log4Shell이 공개되었을 때, SBOM이 있는 조직은 몇 분 만에 영향받는 서비스를 식별했지만, 없는 조직은 수일이 걸렸습니다. 둘째, 라이선스 컴플라이언스입니다. GPL, AGPL 등 라이선스 위반 여부를 자동 검증할 수 있습니다. 셋째, 규제 대응입니다. 미국 Executive Order 14028 이후 정부 납품 소프트웨어에 SBOM 제출이 의무화되었습니다. CI/CD 파이프라인에서 SBOM을 자동 생성하고, cosign으로 서명하여 OCI 아티팩트로 레지스트리에 첨부하면, 이미지와 SBOM의 연관성이 보장됩니다. Grype로 SBOM을 지속적으로 스캔하면 새로운 CVE가 발견될 때 기존 배포된 이미지도 검사할 수 있습니다.

**💡 경험 연결**:
Log4Shell 사태 때 Java 기반 서비스에서 Log4j 사용 여부를 수동으로 확인하느라 많은 시간이 소요된 경험이 있습니다. 이후 SBOM 자동 생성 파이프라인을 구축하여 동일한 상황에 신속 대응할 수 있는 체계를 마련했습니다.

**⚠️ 주의**:
SBOM 생성 도구마다 탐지 범위가 다르다. 예를 들어 Alpine apk 패키지는 잘 탐지하지만, 소스에서 직접 컴파일한 바이너리는 놓칠 수 있다. 여러 도구를 조합하는 것이 좋다.

### Q: CI/CD 파이프라인에서 취약점 스캔을 어떻게 구현하나요?
**30초 답변**:
Shift Left 원칙으로 가능한 초기 단계에서 스캔합니다. 코드 단계에서 의존성/시크릿을 스캔하고, 빌드 단계에서 이미지를 Trivy로 스캔하며, 배포 단계에서 Admission Controller로 취약 이미지를 차단하고, 런타임에서 Trivy Operator로 지속 스캔합니다.

**2분 답변**:
효과적인 취약점 스캔 파이프라인은 4단계입니다. 첫째, 코드 단계에서 Dependabot/Renovate로 의존성 취약점을 감지하고, Gitleaks로 하드코딩된 시크릿을 탐지합니다. 둘째, 빌드 단계에서 Hadolint로 Dockerfile 모범 사례를 검증하고, Trivy로 이미지를 스캔합니다. `--exit-code 1 --severity CRITICAL,HIGH`로 임계값 이상의 취약점이 발견되면 빌드를 실패시킵니다. `--ignore-unfixed`로 패치가 아직 없는 취약점은 제외하여 불필요한 빌드 실패를 방지합니다. 셋째, 배포 단계에서 Kyverno의 verifyImages로 서명을 검증하고, 허용된 레지스트리만 사용 가능하도록 제한합니다. 넷째, 런타임에서 Trivy Operator가 클러스터 내 모든 이미지를 주기적으로 재스캔하여 새 CVE에 대응합니다. 핵심은 "개발자의 워크플로를 방해하지 않으면서 보안 게이트를 자동화"하는 것입니다.

**💡 경험 연결**:
온프레미스 폐쇄망에서는 취약점 DB를 오프라인으로 동기화해야 했습니다. Trivy의 `--offline-scan`과 DB 미러링을 활용하여 인터넷 없는 환경에서도 취약점 스캔 파이프라인을 구축한 경험이 있습니다.

**⚠️ 주의**:
취약점 스캔 결과의 **오탐(False Positive)**에 주의해야 한다. 실제로 해당 코드 경로를 사용하지 않는 취약점까지 모두 차단하면 개발 생산성이 크게 떨어진다. `.trivyignore` 파일로 합리적인 예외 처리가 필요하다.

---

## Allganize 맥락

- **AI 모델 이미지 보안**: LLM 모델 이미지는 대용량(수 GB)이며 고가의 학습 결과물이므로, 서명과 무결성 검증이 특히 중요하다. 모델 가중치가 변조되면 AI 서비스의 신뢰성이 훼손된다.
- **Python 의존성 관리**: AI/ML 워크로드는 PyTorch, Transformers 등 대규모 Python 생태계에 의존하므로, SBOM과 취약점 스캔이 필수. GPU 드라이버/CUDA 런타임의 취약점도 포함해야 한다.
- **Private Registry 관리**: Allganize는 자체 모델 이미지를 Private Registry(ECR, ACR)에서 관리하므로, Admission Controller로 허용된 레지스트리만 사용 가능하도록 제한해야 한다.
- **SaaS 컴플라이언스**: 기업 고객에게 AI SaaS를 제공할 때, SBOM 제출이 요구될 수 있으며, 공급망 보안 체계는 고객 신뢰 확보에 중요한 요소.
- **JD 연관**: "인프라 취약점 관리"에 직접 대응. CI/CD 파이프라인에서의 자동화된 취약점 스캔 경험은 핵심 역량.

---
**핵심 키워드**: `Supply-Chain-Security` `cosign` `Sigstore` `Notary` `SBOM` `SPDX` `CycloneDX` `Trivy` `Grype` `Admission-Controller` `SLSA` `Shift-Left`
