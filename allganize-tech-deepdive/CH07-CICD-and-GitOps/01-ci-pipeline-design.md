# CI 파이프라인 설계 (CI Pipeline Design)

> **TL;DR**
> - GitHub Actions는 SaaS 기반 빠른 셋업, Jenkins는 폐쇄망/복잡 파이프라인, GitLab CI는 올인원 DevOps 플랫폼에 최적이다
> - 파이프라인 스테이지는 Lint → Build → Test → Scan → Package 순으로 Fast Feedback 원칙을 따른다
> - Allganize처럼 GitHub 기반 SaaS 환경에서는 GitHub Actions + Reusable Workflow가 가장 효율적이다

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### CI (Continuous Integration)란?

개발자가 코드를 공유 브랜치에 자주 병합(Merge)하고, 병합할 때마다 자동으로 빌드와 테스트를 수행하는 소프트웨어 엔지니어링 프랙티스(Practice)이다. 핵심 목표는 "내 코드가 다른 사람의 코드와 합쳐져도 문제없는가?"를 빠르게 검증하는 것이다.

```
개발자 Push
    │
    ▼
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│  Lint   │───→│  Build  │───→│  Test   │───→│  Scan   │───→│ Package │
│ (10초)  │    │ (1~2분) │    │ (1~3분) │    │ (2~5분) │    │ (1~3분) │
└─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘
     ↑                                                            │
     └──── Fail Fast: 비용 낮은 단계에서 먼저 실패 ────────────────┘
```

### 3대 CI 도구 비교

```
┌────────────────────────────────────────────────────────────────┐
│                    CI 도구 포지셔닝 맵                          │
│                                                                │
│   복잡도 높음                                                   │
│       ▲                                                        │
│       │    ┌──────────┐                                        │
│       │    │ Jenkins  │  1800+ 플러그인, Groovy Pipeline       │
│       │    │          │  Self-hosted, 폐쇄망 최적              │
│       │    └──────────┘                                        │
│       │                   ┌────────────┐                       │
│       │                   │ GitLab CI  │  올인원 DevOps        │
│       │                   │            │  내장 Registry/SAST   │
│       │                   └────────────┘                       │
│       │                                ┌───────────────┐      │
│       │                                │ GitHub Actions │      │
│       │                                │                │      │
│       │                                │ SaaS, YAML기반 │      │
│       │                                └───────────────┘      │
│       └──────────────────────────────────────────────→        │
│                                              설정 용이성       │
└────────────────────────────────────────────────────────────────┘
```

| 비교 항목 | Jenkins | GitHub Actions | GitLab CI |
|-----------|---------|---------------|-----------|
| **설정 파일** | Jenkinsfile (Groovy) | .github/workflows/*.yaml | .gitlab-ci.yml |
| **실행 환경** | Self-hosted Agent | GitHub-hosted / Self-hosted Runner | Shared / Self-hosted Runner |
| **트리거** | Webhook, Cron, 수동 | push, PR, schedule, workflow_dispatch | push, MR, schedule, trigger |
| **시크릿 관리** | Credentials Plugin | Encrypted Secrets + OIDC | CI/CD Variables + Vault 연동 |
| **캐싱** | 플러그인 (stash/unstash) | actions/cache | cache: 키워드 내장 |
| **병렬 실행** | parallel 스텝 | matrix strategy | parallel: N |
| **Artifact** | archiveArtifacts | upload-artifact/download-artifact | artifacts: 키워드 |
| **비용** | 서버 비용만 | 2,000분/월 무료 (private) | 400분/월 무료 |
| **K8s 연동** | K8s Plugin (Pod Agent) | Self-hosted Runner on K8s | K8s Agent (GitLab Agent) |
| **폐쇄망** | **최적** (완전 Self-hosted) | Runner만 Self-hosted 가능 | Self-managed 가능 |

### GitHub Actions 심화

```yaml
# .github/workflows/ci.yaml
name: CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

# 동시 실행 제어: 같은 PR의 이전 빌드를 취소
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Lint
        run: |
          pip install ruff
          ruff check .
          ruff format --check .

  build-and-test:
    needs: lint
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']  # Matrix 빌드
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      # 의존성 캐싱
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: pip-${{ runner.os }}-${{ hashFiles('**/requirements*.txt') }}
          restore-keys: pip-${{ runner.os }}-

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Test with coverage
        run: pytest --cov=src --cov-report=xml --junitxml=report.xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml

  scan:
    needs: build-and-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: SAST - Bandit
        run: |
          pip install bandit
          bandit -r src/ -f json -o bandit-report.json || true
      - name: Dependency check
        run: |
          pip install safety
          safety check -r requirements.txt

  image-build:
    needs: [build-and-test, scan]
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Trivy scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
          severity: HIGH,CRITICAL
          exit-code: '1'
```

### GitHub Actions - Reusable Workflow

조직 내 여러 저장소에서 공통 파이프라인을 재사용하는 패턴이다.

```yaml
# .github/workflows/reusable-python-ci.yaml (공통 워크플로우)
name: Reusable Python CI

on:
  workflow_call:
    inputs:
      python-version:
        required: false
        type: string
        default: '3.12'
      run-scan:
        required: false
        type: boolean
        default: true
    secrets:
      SONAR_TOKEN:
        required: false

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ inputs.python-version }}
      - run: pip install -r requirements.txt && pytest --cov
      - if: inputs.run-scan
        run: bandit -r src/
```

```yaml
# 호출하는 쪽 (.github/workflows/ci.yaml)
name: CI
on: [push, pull_request]
jobs:
  call-shared-ci:
    uses: org/shared-workflows/.github/workflows/reusable-python-ci.yaml@main
    with:
      python-version: '3.12'
      run-scan: true
    secrets:
      SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

### Jenkins Pipeline 심화

```groovy
// Jenkinsfile (Declarative Pipeline)
pipeline {
    agent {
        kubernetes {
            yaml '''
            spec:
              containers:
              - name: python
                image: python:3.12-slim
                command: ['sleep', 'infinity']
              - name: docker
                image: docker:24-dind
                securityContext:
                  privileged: true
              - name: trivy
                image: aquasec/trivy:latest
                command: ['sleep', 'infinity']
            '''
        }
    }

    environment {
        REGISTRY = 'harbor.internal.corp'
        IMAGE    = "${REGISTRY}/alli/backend"
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    stages {
        stage('Lint') {
            steps {
                container('python') {
                    sh 'pip install ruff && ruff check .'
                }
            }
        }

        stage('Build & Test') {
            steps {
                container('python') {
                    sh '''
                        pip install -r requirements.txt -r requirements-dev.txt
                        pytest --cov=src --cov-report=xml --junitxml=report.xml
                    '''
                    junit 'report.xml'
                    cobertura coberturaReportFile: 'coverage.xml'
                }
            }
        }

        stage('Image Build') {
            steps {
                container('docker') {
                    sh "docker build -t ${IMAGE}:${BUILD_NUMBER}-${GIT_COMMIT[0..6]} ."
                    sh "docker push ${IMAGE}:${BUILD_NUMBER}-${GIT_COMMIT[0..6]}"
                }
            }
        }

        stage('Image Scan') {
            steps {
                container('trivy') {
                    sh """
                        trivy image --exit-code 1 \
                            --severity HIGH,CRITICAL \
                            --skip-db-update \
                            --cache-dir /opt/trivy-cache \
                            ${IMAGE}:${BUILD_NUMBER}-${GIT_COMMIT[0..6]}
                    """
                }
            }
        }
    }

    post {
        failure {
            slackSend channel: '#ci-alerts',
                      color: 'danger',
                      message: "CI FAILED: ${env.JOB_NAME} #${env.BUILD_NUMBER}\n${env.BUILD_URL}"
        }
        success {
            slackSend channel: '#ci-alerts',
                      color: 'good',
                      message: "CI PASSED: ${env.JOB_NAME} #${env.BUILD_NUMBER}"
        }
    }
}
```

### Jenkins Shared Library

```
shared-library/
├── vars/
│   ├── pythonPipeline.groovy    # 파이프라인 함수
│   └── notifySlack.groovy       # 공통 알림
├── src/
│   └── org/company/Utils.groovy # 유틸리티 클래스
└── resources/
    └── templates/               # 설정 템플릿
```

```groovy
// vars/pythonPipeline.groovy
def call(Map config = [:]) {
    pipeline {
        agent { kubernetes { yaml pythonAgentYaml() } }
        stages {
            stage('Lint')  { steps { container('python') { sh 'ruff check .' } } }
            stage('Test')  { steps { container('python') { sh 'pytest --cov' } } }
            stage('Build') { steps { container('docker') {
                sh "docker build -t ${config.image}:${BUILD_NUMBER} ."
            }}}
        }
    }
}
```

### GitLab CI 심화

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - build
  - scan
  - deploy

variables:
  IMAGE: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

# 캐시 설정
cache:
  key:
    files:
      - requirements.txt
  paths:
    - .cache/pip
    - .venv/

lint:
  stage: lint
  image: python:3.12-slim
  script:
    - pip install ruff
    - ruff check .
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"

test:
  stage: test
  image: python:3.12-slim
  script:
    - pip install -r requirements.txt -r requirements-dev.txt
    - pytest --cov=src --junitxml=report.xml
  artifacts:
    reports:
      junit: report.xml
    when: always

build:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $IMAGE .
    - docker push $IMAGE
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

# GitLab 내장 SAST
sast:
  stage: scan
include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Container-Scanning.gitlab-ci.yml

deploy-staging:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl set image deployment/backend backend=$IMAGE -n staging
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy-production:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl set image deployment/backend backend=$IMAGE -n production
  environment:
    name: production
    url: https://app.example.com
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### 파이프라인 설계 5대 원칙

```
1. Fast Feedback (빠른 피드백)
   → 비용이 적은 검사(Lint)를 먼저, 느린 검사(E2E)를 나중에
   → 개발자가 10분 내에 결과를 확인할 수 있어야 한다

2. Fail Fast (빠른 실패)
   → 문법 오류를 빌드 전에, 단위 테스트를 통합 테스트 전에 실행
   → 실패 원인을 빠르게 특정할 수 있어야 한다

3. Idempotency (멱등성)
   → 같은 커밋이면 같은 결과가 나와야 한다
   → latest 태그 대신 Git SHA 기반 태깅

4. Artifact Promotion (아티팩트 프로모션)
   → 한 번 빌드한 이미지를 Dev → STG → PRD로 프로모션
   → 환경마다 다시 빌드하지 않는다

5. Pipeline as Code
   → 파이프라인 정의 자체를 Git에서 버전 관리
   → PR 리뷰를 통해 파이프라인 변경도 검증
```

---

## 실전 예시

### GitHub Actions - OIDC로 AWS 인증 (시크릿 없이)

```yaml
permissions:
  id-token: write
  contents: read

steps:
  - name: Configure AWS Credentials
    uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: arn:aws:iam::123456789012:role/GitHubActions
      aws-region: ap-northeast-2

  - name: Login to ECR
    uses: aws-actions/amazon-ecr-login@v2

  - name: Push to ECR
    run: |
      docker build -t $ECR_REGISTRY/$ECR_REPO:${{ github.sha }} .
      docker push $ECR_REGISTRY/$ECR_REPO:${{ github.sha }}
```

### 빌드 캐시 최적화 비교

```
GitHub Actions:
  cache-from: type=gha          → GitHub Cache API 활용
  BuildKit inline cache         → 레이어 단위 캐싱

Jenkins:
  stash/unstash                 → 스테이지 간 파일 전달
  docker build --cache-from     → 레지스트리 캐시

GitLab CI:
  cache: key: files:            → Lock 파일 기반 캐시 키
  services: docker:dind         → DinD 레이어 캐시
```

### Monorepo CI 패턴 (path filter)

```yaml
# GitHub Actions: Monorepo에서 변경된 서비스만 빌드
on:
  push:
    paths:
      - 'services/alli-api/**'
      - 'libs/shared/**'

# 또는 dorny/paths-filter 활용
jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      api: ${{ steps.filter.outputs.api }}
      web: ${{ steps.filter.outputs.web }}
    steps:
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            api:
              - 'services/alli-api/**'
            web:
              - 'services/alli-web/**'

  build-api:
    needs: detect-changes
    if: needs.detect-changes.outputs.api == 'true'
    runs-on: ubuntu-latest
    steps:
      - run: echo "Building API..."
```

---

## 면접 Q&A

### Q: "GitHub Actions, Jenkins, GitLab CI 중 어떤 것을 선택하시겠습니까?"

**30초 답변**:
환경에 따라 다릅니다. GitHub을 이미 사용 중인 SaaS 환경이라면 GitHub Actions가 통합성과 설정 간편함에서 최적입니다. 폐쇄망이나 복잡한 파이프라인이 필요하면 Jenkins, Git부터 CI/CD까지 올인원 플랫폼이 필요하면 GitLab CI를 선택합니다.

**2분 답변**:
세 도구의 핵심 차이는 호스팅 모델과 확장성입니다. GitHub Actions는 YAML 기반으로 학습 곡선이 낮고, Marketplace에 수만 개의 Action이 있어 빠르게 파이프라인을 구축할 수 있습니다. OIDC를 지원하여 AWS/Azure 인증 시 시크릿을 저장하지 않아도 되는 보안 이점이 있습니다. Reusable Workflow로 조직 내 파이프라인을 표준화할 수도 있습니다. Jenkins는 1800개 이상의 플러그인과 Groovy 기반 Scripted Pipeline으로 가장 유연합니다. K8s Plugin으로 빌드 에이전트를 Pod로 동적 생성하면 리소스 효율성이 높습니다. Shared Library로 조직 공통 로직을 재사용할 수 있고, 완전 Self-hosted이므로 폐쇄망에서 유일한 선택지입니다. GitLab CI는 소스 코드 관리부터 CI/CD, Registry, SAST까지 하나의 플랫폼에서 제공하여 도구 파편화를 줄입니다. 다만 GitHub 생태계에 비해 서드파티 통합이 적습니다. Allganize가 GitHub 기반이라면 GitHub Actions + ArgoCD 조합을 제안하겠습니다.

**💡 경험 연결**:
폐쇄망 프로젝트에서 Jenkins를 운영했습니다. 오프라인 플러그인 번들 관리, K8s Pod Agent로 동적 빌드 환경 구성, Shared Library로 10개 이상 프로젝트의 파이프라인을 표준화한 경험이 있습니다. 클라우드 전환 시 GitHub Actions로 마이그레이션한다면 핵심 파이프라인 로직을 Reusable Workflow로 재설계하겠습니다.

**⚠️ 주의**:
"무조건 A가 좋다"라고 단정하지 말 것. 항상 "환경/요구사항에 따라" 전제를 깔고, 구체적 기준(호스팅 모델, 보안 요구, 팀 규모)으로 비교할 것.

---

### Q: "CI 파이프라인의 스테이지를 어떻게 설계하시겠습니까?"

**30초 답변**:
Fast Feedback 원칙에 따라 Lint(10초) → Build(1-2분) → Unit Test(1-3분) → SAST/Image Scan(2-5분) → Package(1-3분) 순으로 설계합니다. 비용이 적은 검사를 먼저 실행하여 빠르게 실패하고, 개발자가 10분 내에 결과를 확인할 수 있도록 합니다.

**2분 답변**:
파이프라인 설계의 핵심은 5가지 원칙입니다. Fast Feedback, Fail Fast, Idempotency, Artifact Promotion, Pipeline as Code입니다. 구체적으로 첫 번째 스테이지는 Lint(코드 스타일, 정적 분석)인데, 10초 내에 기본적인 코드 품질 문제를 잡습니다. 빌드조차 하지 않고 걸러낼 수 있는 것들입니다. 두 번째는 Build로 컴파일과 의존성 해결을 수행합니다. 여기서 캐싱이 중요한데, GitHub Actions의 cache action이나 Docker BuildKit 캐시로 빌드 시간을 절반 이상 줄일 수 있습니다. 세 번째는 Test로 단위 테스트와 커버리지를 측정합니다. 네 번째는 Scan으로 SAST(Bandit, SonarQube), 의존성 취약점 점검(Safety, Snyk), 이미지 취약점 스캔(Trivy)을 수행합니다. 마지막으로 Package에서 컨테이너 이미지를 빌드하고 레지스트리에 Push합니다. 태그는 Git SHA 기반으로 멱등성을 보장합니다. Monorepo 환경이라면 path filter로 변경된 서비스만 빌드하여 불필요한 빌드를 방지합니다. 전체 파이프라인은 10분 이내를 목표로 하고, 15분을 초과하면 병렬화나 캐싱을 개선합니다.

**💡 경험 연결**:
이전 프로젝트에서 파이프라인이 30분 이상 걸려 개발자들이 결과를 기다리지 않고 다른 작업을 하는 문제가 있었습니다. Lint를 빌드 전으로 이동하고, Docker 레이어 캐싱을 최적화하고, 테스트를 병렬 실행하여 12분으로 단축한 경험이 있습니다.

**⚠️ 주의**:
파이프라인 속도와 품질 검증의 균형이 중요하다. "빠른 것"만 강조하면 품질이, "꼼꼼한 것"만 강조하면 생산성이 떨어진다. 균형점을 제시할 것.

---

### Q: "Reusable Workflow와 Jenkins Shared Library의 차이는?"

**30초 답변**:
둘 다 조직 내 파이프라인 로직을 재사용하는 패턴입니다. GitHub Actions Reusable Workflow는 YAML 기반으로 workflow_call 트리거를 통해 호출하고, Jenkins Shared Library는 Groovy 코드로 vars/ 디렉토리에 함수를 정의하여 호출합니다. Reusable Workflow는 선언적이고 간결하며, Shared Library는 프로그래밍적이고 유연합니다.

**2분 답변**:
GitHub Actions Reusable Workflow는 하나의 워크플로우 YAML을 다른 워크플로우에서 `uses`로 호출하는 방식입니다. `inputs`와 `secrets`를 명시적으로 정의하므로 인터페이스가 명확하고, YAML이라 비개발자도 이해하기 쉽습니다. 다만 조건부 로직이나 복잡한 분기 처리는 제한적입니다. Composite Action으로 스텝 레벨 재사용도 가능합니다. Jenkins Shared Library는 Groovy 클래스와 함수로 구성됩니다. `vars/` 디렉토리의 전역 함수는 `pythonPipeline(image: 'myapp')`처럼 호출하고, `src/` 디렉토리에는 유틸리티 클래스를 둡니다. 프로그래밍 언어이므로 조건부 로직, 루프, 에러 핸들링이 자유롭습니다. 하지만 Groovy 학습 곡선이 높고, 디버깅이 어렵습니다. 핵심 차이는 선언적 vs 명령적입니다. 10개 이하 마이크로서비스라면 Reusable Workflow가 유지보수하기 쉽고, 50개 이상이고 복잡한 분기가 필요하면 Shared Library가 적합합니다.

**💡 경험 연결**:
Jenkins 환경에서 Shared Library로 Python, Go, Java 프로젝트별 표준 파이프라인을 만들어 10개 팀이 공유한 경험이 있습니다. 버전 태깅으로 Library 변경이 기존 파이프라인에 영향을 주지 않도록 관리했습니다.

**⚠️ 주의**:
Reusable Workflow는 GitHub Actions에서만, Shared Library는 Jenkins에서만 동작한다. 도구 종속성(Vendor Lock-in)을 언급하면 깊이가 더해진다.

---

### Q: "CI에서 보안은 어떻게 확보하나요?"

**30초 답변**:
세 가지 레이어로 확보합니다. 첫째 시크릿 관리로, GitHub Actions OIDC나 Vault를 사용하여 정적 시크릿을 최소화합니다. 둘째 파이프라인 내 보안 스캔으로, SAST(정적 분석), 의존성 취약점 점검, 이미지 스캔을 통합합니다. 셋째 파이프라인 자체 보안으로, 최소 권한 원칙을 적용하고 승인 게이트를 설정합니다.

**2분 답변**:
CI 보안은 크게 세 영역입니다. 첫째, 시크릿 관리입니다. GitHub Actions에서는 OIDC를 통해 AWS/Azure에 시크릿 없이 인증할 수 있습니다. IAM Role을 GitHub 저장소에 매핑하면 Access Key를 저장할 필요가 없습니다. Jenkins에서는 Credentials Plugin과 Vault Plugin을 사용합니다. 둘째, 파이프라인 내 보안 검증입니다. SAST(Bandit, SonarQube)로 코드 수준의 취약점을 점검하고, Safety나 Snyk으로 서드파티 의존성의 알려진 취약점(CVE)을 확인합니다. 이미지 빌드 후에는 Trivy로 OS 패키지와 애플리케이션 라이브러리의 취약점을 스캔합니다. HIGH/CRITICAL 발견 시 파이프라인을 실패시킵니다. 셋째, 파이프라인 자체의 보안입니다. GitHub Actions의 permissions를 최소 권한으로 설정하고, 서드파티 Action은 SHA 고정(pinning)으로 공급망 공격을 방지합니다. Branch Protection Rule로 CI 통과를 PR 머지 조건으로 설정합니다. Cosign으로 이미지에 서명하고 K8s Admission Controller에서 검증하면 엔드투엔드 공급망 보안이 완성됩니다.

**💡 경험 연결**:
폐쇄망에서 Trivy 오프라인 DB를 주기적으로 반입하여 이미지 스캔을 구현한 경험이 있습니다. 외부 네트워크 없이도 보안 스캔을 자동화할 수 있었고, 이를 통해 보안 감사(Audit) 요구사항을 충족했습니다.

**⚠️ 주의**:
보안을 "Trivy 쓰면 됩니다" 한 줄로 끝내지 말 것. 시크릿 관리, 코드 스캔, 이미지 스캔, 파이프라인 자체 보안으로 계층적으로 설명할 것.

---

## Allganize 맥락

- **Alli AI 서비스**: LLM 기반 서비스의 CI에서는 모델 파일 크기가 크므로 빌드 캐싱과 레이어 최적화가 특히 중요하다
- **GitHub 기반 환경**: GitHub Actions + Reusable Workflow로 마이크로서비스별 표준 CI 파이프라인을 구축하면 효율적이다
- **AWS/Azure 멀티클라우드**: OIDC를 통한 클라우드 인증으로 시크릿 관리 부담을 줄이고, ECR/ACR에 동시 Push하는 파이프라인을 설계할 수 있다
- **K8s 환경**: CI 결과물(이미지)을 ArgoCD가 감시하는 Git 저장소에 반영하는 GitOps 연계가 핵심이다
- **면접 포인트**: "CI 도구 선택"보다 "파이프라인 설계 원칙"과 "보안"에 대한 깊이 있는 답변이 차별화 요소

---
**핵심 키워드**: `GitHub Actions` `Jenkins` `GitLab CI` `Reusable Workflow` `Fast Feedback` `OIDC` `Pipeline as Code`
