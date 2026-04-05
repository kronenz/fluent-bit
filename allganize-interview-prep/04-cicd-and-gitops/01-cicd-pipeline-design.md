# CI/CD 파이프라인 설계 (CI/CD Pipeline Design)

> **TL;DR**
> - CI(Continuous Integration)는 코드 통합 자동화, CD(Continuous Delivery/Deployment)는 배포 자동화이다
> - 파이프라인은 Build - Test - Scan - Deploy 스테이지로 구성하며, 브랜치 전략에 따라 흐름이 달라진다
> - 폐쇄망(Air-gapped) 환경에서는 Jenkins가 여전히 강력하며, 미러 레지스트리와 오프라인 플러그인 관리가 핵심이다

---

## 1. CI/CD 핵심 개념

### CI (Continuous Integration)

개발자가 코드를 공유 저장소에 자주 병합(Merge)하고,
병합할 때마다 자동으로 빌드와 테스트를 수행하는 프랙티스(Practice)이다.

**목표:** "내 코드가 다른 사람 코드와 합쳐져도 문제없는가?"를 빠르게 검증

```
개발자 Push → 트리거(Trigger) → 빌드(Build) → 단위 테스트(Unit Test) → 결과 알림
```

### CD - Continuous Delivery vs Continuous Deployment

| 구분 | Continuous Delivery | Continuous Deployment |
|------|--------------------|-----------------------|
| 정의 | 운영 배포 직전까지 자동화 | 운영 배포까지 완전 자동화 |
| 승인 | 수동 승인(Manual Approval) 필요 | 승인 없이 자동 배포 |
| 적합 환경 | 규제 산업, 금융, 공공 | SaaS, 스타트업 |
| **폐쇄망 관점** | **더 적합** (변경 관리 절차 필수) | 제한적 적용 |

### CI와 CD의 경계

```
[CI 영역]                    [CD 영역]
Code → Build → Test → Scan → Staging Deploy → 승인 → Production Deploy
```

---

## 2. 브랜치 전략 (Branching Strategy)

### GitFlow

```
main ──────────────────────────────────────────── (운영)
  └── develop ─────────────────────────────────── (개발 통합)
        ├── feature/login ──── (기능 개발)
        ├── feature/payment ── (기능 개발)
        └── release/1.2.0 ──── (릴리스 준비)
              └── hotfix/critical-bug ──── (긴급 수정)
```

**장점:**
- 릴리스 주기가 명확한 프로젝트에 적합
- 버전 관리가 체계적

**단점:**
- 브랜치가 많아 복잡도 증가
- 장기 브랜치(Long-lived Branch)로 Merge Conflict 빈발

### Trunk-based Development

```
main ──●──●──●──●──●──●──●──●──●── (모든 개발자가 직접 커밋)
       │     │        │
       └─ feature flag로 기능 제어 ─┘
```

**장점:**
- CI/CD와 가장 잘 맞는 전략
- 짧은 피드백 루프(Feedback Loop)
- Feature Flag로 배포와 릴리스 분리

**단점:**
- 높은 테스트 커버리지 필요
- Feature Flag 관리 복잡도

### 선택 기준

| 기준 | GitFlow | Trunk-based |
|------|---------|-------------|
| 릴리스 주기 | 2주-1개월 | 매일-매주 |
| 팀 규모 | 대규모 (10+) | 소규모-중규모 |
| 테스트 성숙도 | 낮아도 가능 | 높아야 함 |
| **폐쇄망** | **적합 (릴리스 관리)** | 점진적 도입 가능 |

---

## 3. CI/CD 도구 비교

### Jenkins

```groovy
// Jenkinsfile (Declarative Pipeline)
pipeline {
    agent {
        kubernetes {
            yaml '''
            spec:
              containers:
              - name: maven
                image: maven:3.9-eclipse-temurin-17
                command: ['sleep', 'infinity']
              - name: docker
                image: docker:24-dind
                securityContext:
                  privileged: true
            '''
        }
    }

    environment {
        REGISTRY = 'harbor.internal.corp'
        IMAGE = "${REGISTRY}/myapp/backend"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build & Test') {
            steps {
                container('maven') {
                    sh 'mvn clean package -DskipTests=false'
                    junit 'target/surefire-reports/*.xml'
                }
            }
        }

        stage('Image Build & Push') {
            steps {
                container('docker') {
                    sh """
                        docker build -t ${IMAGE}:${BUILD_NUMBER} .
                        docker push ${IMAGE}:${BUILD_NUMBER}
                    """
                }
            }
        }

        stage('Deploy to Staging') {
            steps {
                sh "kubectl set image deployment/backend backend=${IMAGE}:${BUILD_NUMBER} -n staging"
            }
        }

        stage('Approval') {
            steps {
                input message: '운영 배포를 승인하시겠습니까?'
            }
        }

        stage('Deploy to Production') {
            steps {
                sh "kubectl set image deployment/backend backend=${IMAGE}:${BUILD_NUMBER} -n production"
            }
        }
    }

    post {
        failure {
            slackSend channel: '#deploy', message: "빌드 실패: ${env.JOB_NAME} #${env.BUILD_NUMBER}"
        }
    }
}
```

### GitHub Actions

```yaml
# .github/workflows/ci-cd.yaml
name: CI/CD Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Go
        uses: actions/setup-go@v5
        with:
          go-version: '1.22'

      - name: Build
        run: go build -v ./...

      - name: Test
        run: go test -v -coverprofile=coverage.out ./...

      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage
          path: coverage.out

  image-build:
    needs: build-and-test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: |
            ghcr.io/${{ github.repository }}:${{ github.sha }}
            ghcr.io/${{ github.repository }}:latest

  deploy:
    needs: image-build
    runs-on: ubuntu-latest
    environment: production    # 수동 승인(Manual Approval) 설정
    steps:
      - name: Update manifest
        run: |
          # GitOps 방식: 매니페스트 저장소의 이미지 태그 업데이트
          git clone https://github.com/org/k8s-manifests.git
          cd k8s-manifests
          sed -i "s|image:.*|image: ghcr.io/${{ github.repository }}:${{ github.sha }}|" \
            apps/backend/deployment.yaml
          git commit -am "chore: update backend image to ${{ github.sha }}"
          git push
```

### GitLab CI

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - scan
  - deploy

variables:
  IMAGE: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}

build:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker build -t ${IMAGE} .
    - docker push ${IMAGE}

test:
  stage: test
  image: golang:1.22
  script:
    - go test -race -coverprofile=coverage.out ./...
  coverage: '/total:\s+\(statements\)\s+(\d+.\d+)%/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.out

scan:
  stage: scan
  image: aquasec/trivy:latest
  script:
    - trivy image --exit-code 1 --severity HIGH,CRITICAL ${IMAGE}

deploy-staging:
  stage: deploy
  script:
    - kubectl apply -f k8s/ -n staging
  environment:
    name: staging

deploy-production:
  stage: deploy
  script:
    - kubectl apply -f k8s/ -n production
  environment:
    name: production
  when: manual    # 수동 승인
  only:
    - main
```

### 도구 비교표

| 항목 | Jenkins | GitHub Actions | GitLab CI |
|------|---------|---------------|-----------|
| 호스팅 | Self-hosted | SaaS / Self-hosted Runner | SaaS / Self-hosted |
| 설정 파일 | Jenkinsfile | .github/workflows/*.yaml | .gitlab-ci.yml |
| 플러그인 생태계 | 1800+ 플러그인 | Marketplace Actions | 내장 기능 풍부 |
| **폐쇄망 적합성** | **최적** (완전 Self-hosted) | Runner만 Self-hosted 가능 | Self-managed 가능 |
| 학습 곡선 | 높음 (Groovy) | 낮음 (YAML) | 중간 (YAML) |
| K8s 연동 | 플러그인 필요 | Action 활용 | 내장 K8s Agent |

---

## 4. 파이프라인 스테이지 설계

### 표준 파이프라인 스테이지

```
[1. Source]     코드 체크아웃, 의존성 캐시 복원
    ↓
[2. Build]      컴파일, 아티팩트 생성
    ↓
[3. Test]       단위 테스트, 통합 테스트, 커버리지
    ↓
[4. Scan]       SAST(정적 분석), 이미지 취약점 스캔
    ↓
[5. Package]    컨테이너 이미지 빌드, 레지스트리 Push
    ↓
[6. Deploy-STG] 스테이징 환경 배포, E2E 테스트
    ↓
[7. Approval]   수동 승인 게이트
    ↓
[8. Deploy-PRD] 운영 환경 배포
    ↓
[9. Verify]     스모크 테스트(Smoke Test), 모니터링 확인
```

### 파이프라인 설계 원칙

**1) Fast Feedback (빠른 피드백)**

```
# 빠른 테스트를 먼저, 느린 테스트를 나중에
stages:
  - lint          # 10초
  - unit-test     # 30초
  - build         # 2분
  - integration   # 5분
  - e2e           # 10분
```

**2) Fail Fast (빠른 실패)**

```yaml
# 비용이 적은 단계에서 먼저 실패하도록 구성
lint:
  stage: lint
  script:
    - golangci-lint run ./...    # 코드 품질 문제를 빌드 전에 잡는다
```

**3) Idempotent (멱등성)**

```bash
# 같은 입력이면 같은 결과가 나와야 한다
# Bad: latest 태그 사용
docker build -t myapp:latest .

# Good: 커밋 SHA 기반 태그
docker build -t myapp:${GIT_SHA} .
```

**4) Artifact Promotion (아티팩트 프로모션)**

```
# 한 번 빌드하고, 환경별로 같은 아티팩트를 프로모션
Build → [artifact v1.2.3]
           ├── Deploy to Dev    (동일 이미지)
           ├── Deploy to STG    (동일 이미지)
           └── Deploy to PRD    (동일 이미지)

# 환경마다 다시 빌드하지 않는다!
```

### 폐쇄망 파이프라인 설계 포인트

```
[외부망]                          [폐쇄망]
                    ┌──────────┐
소스 코드 ─────────→│ 전송 게이트 │──────→ 내부 Git (Gitea/GitLab)
의존성 패키지 ──────→│ (망간자료) │──────→ 내부 Nexus/Artifactory
베이스 이미지 ──────→│  전송체계  │──────→ 내부 Harbor Registry
                    └──────────┘
                                         Jenkins (내부)
                                           ├── Build (오프라인 의존성)
                                           ├── Test
                                           ├── Scan (오프라인 DB)
                                           └── Deploy
```

**핵심 고려사항:**
- 의존성 미러(Mirror) 구축: Maven Central, npm, PyPI 미러
- 오프라인 취약점 DB: Trivy 오프라인 DB 주기적 반입
- 플러그인 사전 설치: Jenkins 플러그인 오프라인 번들
- 인증서 관리: 내부 CA(Certificate Authority) 배포

---

## 5. 면접 Q&A

### Q1. "CI와 CD의 차이를 설명해주세요"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "CI는 개발자가 코드를 자주 통합하고 자동으로 빌드와 테스트를 수행하는 것이고,
> CD는 그 결과물을 스테이징이나 운영 환경에 자동으로 배포하는 것입니다.
> CD는 Continuous Delivery와 Continuous Deployment로 나뉘는데,
> Delivery는 운영 배포 전 수동 승인이 있고, Deployment는 완전 자동입니다.
> 폐쇄망 환경에서는 변경 관리 절차가 있어서 Continuous Delivery가 더 현실적이었고,
> 수동 승인 게이트를 Jenkins Pipeline의 input 스텝으로 구현했습니다."

### Q2. "GitFlow와 Trunk-based Development 중 어떤 걸 선호하시나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "팀의 상황에 따라 다릅니다. 릴리스 주기가 길고 QA 프로세스가 별도로 있는 환경에서는
> GitFlow가 적합하고, 빠른 배포가 필요한 환경에서는 Trunk-based가 좋습니다.
> 이전 폐쇄망 프로젝트에서는 월 1회 릴리스 주기였기 때문에 GitFlow를 사용했는데,
> release 브랜치에서 통합 테스트를 거친 후 운영에 반영하는 방식이었습니다.
> 다만 최근에는 Trunk-based + Feature Flag 조합이 CI/CD와 가장 잘 맞는
> 모던 프랙티스라고 생각합니다."

### Q3. "파이프라인에서 가장 중요하게 생각하는 것은?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "세 가지를 강조합니다. 첫째, 멱등성(Idempotency)입니다. 같은 커밋이면 같은 결과가
> 나와야 합니다. 둘째, 아티팩트 프로모션입니다. 한 번 빌드한 이미지를 환경별로 재사용하면
> '스테이징에서 됐는데 운영에서 안 되는' 문제를 줄일 수 있습니다.
> 셋째, Fast Feedback입니다. Lint를 먼저 실행하고, 느린 E2E 테스트를 마지막에 두어
> 개발자가 빠르게 피드백을 받을 수 있도록 합니다."

### Q4. "폐쇄망에서 CI/CD를 어떻게 구축하셨나요?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "가장 큰 과제는 외부 의존성 관리였습니다. Nexus Repository로 Maven, npm, PyPI 미러를
> 구축하고, 주기적으로 망간자료전송 절차를 통해 업데이트했습니다.
> 컨테이너 이미지는 Harbor에서 관리했고, 베이스 이미지도 사전에 반입하여
> Dockerfile에서 내부 레지스트리를 참조하도록 했습니다.
> Jenkins는 오프라인 플러그인 번들로 설치했고, 에이전트는 K8s Pod로 동적 생성하여
> 리소스 효율성을 높였습니다."

### Q5. "Jenkins와 GitHub Actions 중 무엇을 선택하시겠습니까?"

> **면접에서 이렇게 물어보면 → 이렇게 대답한다**
>
> "환경에 따라 다릅니다. 클라우드 SaaS 환경이고 GitHub을 쓴다면 GitHub Actions가
> 설정이 간편하고 Marketplace 생태계가 풍부합니다.
> 하지만 폐쇄망이나 복잡한 파이프라인이 필요한 환경에서는 Jenkins가 더 유연합니다.
> Shared Library로 조직 공통 파이프라인을 재사용할 수 있고,
> 플러그인으로 거의 모든 도구와 연동할 수 있기 때문입니다.
> Allganize의 환경이 클라우드 기반이라면 GitHub Actions나 GitLab CI를 추천하겠지만,
> 하이브리드 환경이라면 Jenkins + ArgoCD 조합도 고려할 만합니다."

---

## 키워드 (Keywords)

`CI/CD Pipeline` `Branching Strategy` `Jenkins` `Artifact Promotion` `Fast Feedback`
