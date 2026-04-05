# Terraform CI/CD 통합

> **TL;DR**: Terraform을 CI/CD에 통합하면 PR 생성 시 자동 Plan, 승인 후 자동 Apply로 인프라 변경의 안전성과 속도를 모두 확보한다.
> Atlantis, Spacelift 등 전용 도구나 GitHub Actions로 파이프라인을 구축하며, Plan 결과를 PR 코멘트로 공유하여 코드 리뷰 문화를 정착시킨다.
> "인프라 변경 = PR 머지"라는 GitOps 원칙이 핵심이다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Terraform CI/CD 워크플로

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Developer│     │   CI/CD  │     │ Reviewer │     │   CI/CD  │
│          │     │ (Plan)   │     │          │     │ (Apply)  │
│ .tf 수정 │────▶│          │────▶│ Plan 결과│────▶│          │
│ PR 생성  │     │ tf plan  │     │ 검토     │     │ tf apply │
│          │     │ 결과를   │     │ Approve  │     │ 실행     │
│          │     │ PR 코멘트│     │          │     │          │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
     │                │                │                │
     ▼                ▼                ▼                ▼
  feature branch   Plan output      PR Approved      main branch
  생성             PR에 표시        merge 승인       merge & apply
```

### GitHub Actions 기반 파이프라인

```yaml
# .github/workflows/terraform.yml
name: Terraform CI/CD

on:
  pull_request:
    paths:
      - 'infrastructure/**'
  push:
    branches:
      - main
    paths:
      - 'infrastructure/**'

permissions:
  contents: read
  pull-requests: write
  id-token: write          # OIDC 인증용

env:
  TF_VERSION: "1.7.0"
  AWS_REGION: "ap-northeast-2"

jobs:
  # ─── PR 생성/업데이트 시: Plan ───
  plan:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    strategy:
      matrix:
        environment: [dev, staging, prod]
    defaults:
      run:
        working-directory: infrastructure/environments/${{ matrix.environment }}

    steps:
      - uses: actions/checkout@v4

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TF_VERSION }}
          terraform_wrapper: true    # stdout 캡처 활성화

      # AWS OIDC 인증 (시크릿 키 불필요)
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/github-terraform
          aws-region: ${{ env.AWS_REGION }}

      - name: Terraform Init
        run: terraform init -no-color

      - name: Terraform Validate
        run: terraform validate -no-color

      - name: Terraform Plan
        id: plan
        run: terraform plan -no-color -out=tfplan
        continue-on-error: true

      # Plan 결과를 PR 코멘트로 게시
      - name: Comment Plan on PR
        uses: actions/github-script@v7
        with:
          script: |
            const output = `### Terraform Plan - \`${{ matrix.environment }}\`

            #### Init: \`Success\`
            #### Validate: \`Success\`
            #### Plan: \`${{ steps.plan.outcome }}\`

            <details><summary>Plan Output (click to expand)</summary>

            \`\`\`hcl
            ${{ steps.plan.outputs.stdout }}
            \`\`\`

            </details>

            *Pushed by: @${{ github.actor }}, Action: \`${{ github.event_name }}\`*`;

            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: output
            })

      - name: Plan Status Check
        if: steps.plan.outcome == 'failure'
        run: exit 1

  # ─── main 머지 시: Apply ───
  apply:
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    strategy:
      max-parallel: 1          # 순차 실행 (환경 순서 보장)
      matrix:
        environment: [dev, staging, prod]
    environment: ${{ matrix.environment }}   # GitHub Environment (승인 게이트)
    defaults:
      run:
        working-directory: infrastructure/environments/${{ matrix.environment }}

    steps:
      - uses: actions/checkout@v4

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TF_VERSION }}

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/github-terraform-${{ matrix.environment }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Terraform Init
        run: terraform init -no-color

      - name: Terraform Apply
        run: terraform apply -auto-approve -no-color
```

### Atlantis 패턴

Atlantis는 Terraform 전용 PR Automation 서버이다.

```
┌───────────────────────────────────────────────────┐
│                  Atlantis 서버                      │
│                                                   │
│  Webhook 수신 ─▶ Plan 자동 실행 ─▶ PR 코멘트      │
│                                                   │
│  PR 코멘트 명령어:                                 │
│    atlantis plan         → Plan 실행              │
│    atlantis plan -d vpc  → 특정 디렉토리만 Plan    │
│    atlantis apply        → Apply 실행 (승인 후)    │
│    atlantis unlock       → State Lock 해제        │
└───────────────────────────────────────────────────┘
```

**atlantis.yaml** (서버 사이드 설정):
```yaml
# atlantis.yaml (리포지토리 루트)
version: 3
automerge: false
parallel_plan: true
parallel_apply: false     # Apply는 순차 실행

projects:
  - name: prod-vpc
    dir: infrastructure/environments/prod/vpc
    workspace: default
    terraform_version: v1.7.0
    autoplan:
      when_modified:
        - "*.tf"
        - "*.tfvars"
        - "../../../modules/vpc/**"    # 모듈 변경도 감지
      enabled: true
    apply_requirements:
      - approved            # PR 승인 필수
      - mergeable           # CI 통과 필수

  - name: prod-eks
    dir: infrastructure/environments/prod/eks
    workspace: default
    terraform_version: v1.7.0
    autoplan:
      when_modified:
        - "*.tf"
        - "../../../modules/eks/**"
      enabled: true
    apply_requirements:
      - approved
      - mergeable

  - name: dev-vpc
    dir: infrastructure/environments/dev/vpc
    workspace: default
    autoplan:
      enabled: true
    apply_requirements: []   # dev는 승인 없이 Apply 가능
```

### Spacelift 패턴

```
┌─────────────────────────────────────────────────────┐
│                    Spacelift                         │
│                                                     │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Stack   │  │ Policy   │  │ Drift Detection  │  │
│  │ (환경별) │  │ (OPA)    │  │ (자동 감지)       │  │
│  │         │  │          │  │                  │  │
│  │ Plan    │  │ 비용 한도 │  │ cron: 매 1시간   │  │
│  │ Apply   │  │ 리소스    │  │ plan 실행        │  │
│  │ Destroy │  │ 제한     │  │ drift 알림       │  │
│  └─────────┘  └──────────┘  └──────────────────┘  │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │ Stack Dependencies (DAG)                     │   │
│  │                                             │   │
│  │ vpc-stack ──▶ eks-stack ──▶ app-stack       │   │
│  │     │                                       │   │
│  │     └──▶ rds-stack                          │   │
│  │                                             │   │
│  │ VPC 변경 시 → EKS, RDS 자동 re-plan         │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**Spacelift vs Atlantis 비교**:

```
┌─────────────────┬──────────────────┬──────────────────┐
│ 항목             │ Atlantis         │ Spacelift        │
├─────────────────┼──────────────────┼──────────────────┤
│ 호스팅           │ 자체 서버 운영    │ SaaS (관리형)    │
│ 비용             │ 무료 (오픈소스)   │ 유료 (팀 규모별) │
│ Policy Engine   │ Conftest (OPA)   │ 내장 OPA         │
│ Drift Detection │ 수동 설정        │ 내장 자동 감지    │
│ Stack 의존성    │ 없음             │ DAG 기반 자동     │
│ 비용 추정       │ Infracost 연동   │ 내장              │
│ 적합 대상       │ 소규모~중규모 팀  │ 중규모~대규모 팀  │
└─────────────────┴──────────────────┴──────────────────┘
```

### 보안: OIDC 인증

```
기존 방식 (Secret Key):
  GitHub Secrets에 AWS_ACCESS_KEY_ID 저장
  → 키 유출 위험, 키 로테이션 필요

OIDC 방식 (추천):
  GitHub → AWS STS → 임시 토큰 발급
  → 장기 키 없음, IAM Role 기반

┌──────────┐    OIDC Token    ┌──────────┐
│ GitHub   │─────────────────▶│ AWS STS  │
│ Actions  │                  │          │
│          │◀─────────────────│ 임시 토큰│
│          │  AssumeRole      │ (15분)   │
└──────────┘                  └──────────┘
```

```hcl
# OIDC Provider 설정 (한 번만)
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# GitHub Actions용 IAM Role
resource "aws_iam_role" "github_terraform" {
  name = "github-terraform"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:allganize/infrastructure:*"
        }
      }
    }]
  })
}
```

## 실전 예시

### Infracost 비용 추정 통합

```yaml
# .github/workflows/infracost.yml
- name: Infracost Breakdown
  run: |
    infracost breakdown \
      --path=infrastructure/environments/prod \
      --format=json \
      --out-file=/tmp/infracost.json

- name: Infracost Comment
  run: |
    infracost comment github \
      --path=/tmp/infracost.json \
      --repo=$GITHUB_REPOSITORY \
      --pull-request=${{ github.event.pull_request.number }} \
      --github-token=${{ github.token }} \
      --behavior=update

# PR 코멘트 예시:
# ┌────────────────────────────────────────────┐
# │ Monthly cost will increase by $142 (+12%)  │
# │                                            │
# │ aws_instance.web    $85/mo → $127/mo       │
# │ aws_rds_instance.db $200/mo → $300/mo      │
# │                                            │
# │ Total: $1,180/mo → $1,322/mo               │
# └────────────────────────────────────────────┘
```

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.86.0
    hooks:
      - id: terraform_fmt          # 코드 포맷팅
      - id: terraform_validate     # 문법 검증
      - id: terraform_tflint       # Linting
        args:
          - --args=--config=__GIT_WORKING_DIR__/.tflint.hcl
      - id: terraform_docs         # README 자동 생성
        args:
          - --hook-config=--path-to-file=README.md
          - --hook-config=--add-to-existing-file=true
      - id: terraform_checkov      # 보안 스캔
        args:
          - --args=--quiet
          - --args=--skip-check CKV_AWS_79
      - id: infracost_breakdown    # 비용 추정
        args:
          - --args=--path=.
          - --hook-config=--currency=USD
```

### 환경별 Apply 게이트

```yaml
# GitHub Environments 설정
#
# dev:      자동 Apply (승인 불필요)
# staging:  1명 승인 필요
# prod:     2명 승인 + 배포 시간 제한 (평일 10:00-17:00)
#
# GitHub Repository Settings > Environments에서 설정:
#
# prod 환경:
#   Required reviewers: devops-lead, platform-lead
#   Wait timer: 5 minutes
#   Deployment branches: main only
#   Environment secrets: (환경별 시크릿)
```

## 면접 Q&A

### Q: Terraform CI/CD 파이프라인을 어떻게 구성하나요?

**30초 답변**:
PR 생성 시 자동으로 `terraform plan`을 실행하고 결과를 PR 코멘트로 게시합니다. 리뷰어가 Plan 결과를 확인하고 Approve하면, main 브랜치 머지 시 `terraform apply`가 자동 실행됩니다. OIDC 인증으로 장기 시크릿 키 없이 안전하게 클라우드에 접근합니다.

**2분 답변**:
파이프라인은 크게 세 단계로 구성합니다.

첫째, PR 단계(Plan)입니다. PR 생성/업데이트 시 변경된 디렉토리를 감지하여 해당 환경의 `terraform plan`을 실행합니다. Plan 결과를 PR 코멘트로 게시하여 리뷰어가 "어떤 리소스가 추가/변경/삭제되는지"를 코드 리뷰처럼 확인합니다. Infracost를 연동하면 비용 변동도 함께 표시됩니다.

둘째, 머지 단계(Apply)입니다. PR이 승인되고 main에 머지되면 `terraform apply`가 실행됩니다. GitHub Environments를 활용하여 prod는 추가 승인 게이트를 설정합니다. Apply는 환경별로 순차 실행하여 dev → staging → prod 순서를 보장합니다.

셋째, 보안입니다. AWS OIDC 인증을 사용하여 GitHub Actions에서 임시 토큰으로 인증하므로 장기 Access Key가 불필요합니다. 환경별 IAM Role을 분리하여 최소 권한 원칙을 적용합니다.

도구 선택은 팀 규모에 따라 다릅니다. 소규모는 GitHub Actions, 중규모는 Atlantis, 대규모는 Spacelift이 적합합니다.

**💡 경험 연결**:
온프레미스에서 변경관리(RFC) 프로세스가 "요청 → 검토 → 승인 → 실행"이었는데, Terraform CI/CD는 이를 "PR → Plan Review → Approve → Apply"로 자동화한 것입니다. 수동 프로세스의 엄격함을 유지하면서 실행 속도를 높인 것이 핵심입니다.

**⚠️ 주의**:
`-auto-approve`는 CI/CD의 Apply 단계에서만, GitHub Environments 승인 게이트와 함께 사용해야 합니다. 승인 없이 `-auto-approve`를 사용하면 거버넌스가 무력화됩니다.

---

### Q: Atlantis와 GitHub Actions 중 어떤 것을 선택하나요?

**30초 답변**:
GitHub Actions는 범용적이고 추가 인프라가 불필요하지만, Terraform 특화 기능이 부족합니다. Atlantis는 Terraform 전용으로 PR 코멘트 기반 워크플로(`atlantis plan`, `atlantis apply`)가 편리하지만 자체 서버 운영이 필요합니다. 팀 규모와 운영 역량에 따라 선택합니다.

**2분 답변**:
GitHub Actions는 이미 사용 중인 CI/CD 플랫폼에 Terraform을 추가하는 방식이라 도입 장벽이 낮습니다. 하지만 변경된 디렉토리 감지, Plan 결과 파싱, State Lock 관리 등을 직접 구현해야 합니다.

Atlantis는 Terraform에 특화되어 있어 설정이 간단합니다. PR에 `atlantis plan` 코멘트만 달면 해당 디렉토리의 Plan이 실행되고, 결과가 코멘트로 돌아옵니다. `autoplan`으로 .tf 파일 변경 시 자동 Plan도 가능합니다. 하지만 Atlantis 서버를 직접 운영해야 하므로 K8s 위에 배포하고 고가용성을 확보해야 합니다.

Spacelift은 SaaS형으로 인프라 관리가 불필요하고, OPA 정책, Drift Detection, Stack 의존성 관리 등 엔터프라이즈 기능이 내장되어 있습니다. 다만 비용이 발생하고 외부 SaaS 의존성이 생깁니다.

추천 기준은 5명 이하 팀은 GitHub Actions, 5-20명은 Atlantis, 20명 이상이거나 거버넌스가 중요한 조직은 Spacelift입니다.

**💡 경험 연결**:
도구 선택은 팀 규모와 운영 성숙도에 맞춰야 합니다. 처음에는 GitHub Actions로 시작하고, 팀이 성장하면 Atlantis로 전환하는 점진적 접근이 현실적입니다.

**⚠️ 주의**:
Atlantis 서버에는 클라우드 자격 증명이 있으므로 보안이 매우 중요합니다. 네트워크 접근 제한, Webhook 시크릿, RBAC를 반드시 설정해야 합니다.

---

### Q: Terraform Plan에서 예상치 못한 destroy가 나타나면 어떻게 하나요?

**30초 답변**:
먼저 Plan을 주의 깊게 읽어 어떤 리소스가 왜 삭제되는지 파악합니다. 리소스 이름 변경으로 인한 것이면 `moved` 블록을 사용하고, ForceNew 속성 변경이면 `lifecycle { create_before_destroy = true }`를 검토합니다. 절대 Plan을 확인하지 않고 Apply하면 안 됩니다.

**2분 답변**:
예상치 못한 destroy는 여러 원인이 있습니다.

첫째, 리소스 이름(주소) 변경입니다. `aws_vpc.main`을 `aws_vpc.primary`로 변경하면 Terraform은 main을 삭제하고 primary를 새로 생성합니다. `moved` 블록이나 `terraform state mv`로 해결합니다.

둘째, ForceNew 속성 변경입니다. AMI ID, 인스턴스 타입 등 일부 속성은 in-place 변경이 불가하여 삭제 후 재생성됩니다. `lifecycle { create_before_destroy = true }`로 새 리소스를 먼저 만들고 구 리소스를 삭제하도록 순서를 바꿀 수 있습니다.

셋째, 모듈 소스 변경입니다. 모듈 source를 변경하면 내부 리소스가 모두 재생성될 수 있습니다.

넷째, Provider 업그레이드입니다. 리소스 스키마 변경으로 재생성이 필요할 수 있습니다.

대응 방법은 `-target`으로 안전한 리소스만 먼저 Apply하거나, `lifecycle { prevent_destroy = true }`로 중요 리소스의 삭제를 차단하는 것입니다.

**💡 경험 연결**:
인프라 변경의 "영향도 분석"은 온프레미스에서도 필수였습니다. Terraform Plan은 이 분석을 자동화해주지만, 결과를 사람이 반드시 검토해야 한다는 원칙은 동일합니다.

**⚠️ 주의**:
`prevent_destroy = true`는 `terraform destroy` 실행을 차단하지만, .tf 코드에서 리소스를 삭제하고 apply하면 에러가 발생합니다. 코드 삭제 전에 lifecycle을 먼저 제거해야 합니다.

## Allganize 맥락

- **PR 기반 인프라 변경 문화**: Allganize에서 인프라 변경을 PR → Plan Review → Approve → Apply 파이프라인으로 운영하면, 모든 변경이 Git 히스토리에 남고 누가 언제 무엇을 변경했는지 추적 가능하다.
- **멀티클라우드 Plan**: AWS와 Azure 인프라의 Plan을 각각 PR 코멘트로 표시하면, 한 번의 코드 리뷰로 양쪽 클라우드 변경을 동시에 검토할 수 있다.
- **비용 거버넌스**: Infracost를 연동하여 PR 단계에서 비용 변동을 확인하면, AI 모델 서빙에 필요한 GPU 인스턴스 추가 등 고비용 변경을 사전에 검토할 수 있다.
- **JD 연결 — "CI/CD 파이프라인 경험"**: Terraform CI/CD 구축 경험은 IaC 자동화 역량의 핵심 증거이다. "PR에서 Plan 결과를 공유하고, 승인 후 Apply하는 파이프라인을 어떻게 구축했는가"를 구체적으로 설명할 수 있어야 한다.

---
**핵심 키워드**: `GitHub Actions` `Atlantis` `Spacelift` `OIDC` `auto plan` `PR comment` `apply approval` `Infracost` `pre-commit` `Environment Gate`
