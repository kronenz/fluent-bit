# Terraform State 관리

> **TL;DR**: Terraform State는 Remote Backend(S3+DynamoDB)에 저장하여 팀 협업과 동시성 제어를 보장한다.
> State Lock으로 동시 수정 충돌을 방지하고, terraform import/state mv로 기존 리소스를 안전하게 관리한다.
> State 분리 전략(환경별, 서비스별)이 대규모 인프라 운영의 핵심이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### Remote Backend 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│                    Remote Backend                         │
│                                                          │
│  ┌──────────┐    State Read/Write    ┌──────────────┐   │
│  │ Developer │──────────────────────▶│  S3 Bucket   │   │
│  │ (tf plan) │                       │              │   │
│  └──────────┘                        │ tfstate file │   │
│       │                              │ + versioning │   │
│       │  Lock Acquire/Release        └──────────────┘   │
│       │                                                  │
│       └─────────────────────────────▶┌──────────────┐   │
│                                      │  DynamoDB    │   │
│  ┌──────────┐   Lock 충돌 시 대기    │              │   │
│  │ CI/CD    │──────────────────────▶│  Lock Table  │   │
│  │ (tf apply)│                       │  (LockID)    │   │
│  └──────────┘                        └──────────────┘   │
│                                                          │
│  ┌──────────┐                        ┌──────────────┐   │
│  │ KMS Key  │───── 암호화 ──────────▶│  State 암호화│   │
│  └──────────┘                        └──────────────┘   │
└──────────────────────────────────────────────────────────┘
```

### Backend 설정

```hcl
# backend.tf
terraform {
  backend "s3" {
    bucket         = "alli-terraform-state"
    key            = "prod/ap-northeast-2/eks/terraform.tfstate"
    region         = "ap-northeast-2"
    encrypt        = true
    kms_key_id     = "alias/terraform-state-key"
    dynamodb_table = "terraform-state-lock"
  }
}
```

**S3 버킷 설정 (부트스트랩)**:
```hcl
# 이 리소스는 State 저장소 자체이므로 local backend로 먼저 생성
resource "aws_s3_bucket" "terraform_state" {
  bucket = "alli-terraform-state"

  lifecycle {
    prevent_destroy = true   # 실수로 삭제 방지
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"       # State 히스토리 보존
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.terraform.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "terraform_lock" {
  name         = "terraform-state-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
```

### State Lock 동작 원리

```
Developer A: terraform apply          Developer B: terraform apply
     │                                      │
     ▼                                      ▼
 Lock 획득 요청                         Lock 획득 요청
     │                                      │
     ▼                                      ▼
 DynamoDB PutItem                       DynamoDB PutItem
 (ConditionalCheck)                     (ConditionalCheck)
     │                                      │
     ▼                                      ▼
 Lock 획득 성공 ✅                       Lock 획득 실패 ❌
 → Plan/Apply 진행                      → "Error: state locked"
     │                                  → LockID, Who, When 표시
     ▼                                      │
 Apply 완료                              대기 또는 수동 해제
     │                                  terraform force-unlock <ID>
     ▼
 Lock 해제
 (DynamoDB DeleteItem)
```

**Lock 강제 해제** (CI 장애 등으로 Lock이 남은 경우):
```bash
# Lock 정보 확인
terraform plan
# Error: Error locking state: Error acquiring the state lock
# Lock Info:
#   ID:        a1b2c3d4-e5f6-7890-abcd-ef1234567890
#   Path:      alli-terraform-state/prod/.../terraform.tfstate
#   Operation: OperationTypeApply
#   Who:       ci-runner@ip-10-0-1-100
#   Created:   2024-01-15 03:22:10.123456 +0000 UTC

# 강제 해제 (주의: 다른 사람이 실제 apply 중이 아닌지 반드시 확인)
terraform force-unlock a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### State 분리 전략

```
방법 1: 디렉토리 기반 분리 (추천)

infrastructure/
├── global/                    # State: global/terraform.tfstate
│   ├── iam/
│   └── route53/
├── environments/
│   ├── dev/                   # State: dev/terraform.tfstate
│   │   ├── vpc/
│   │   └── eks/
│   ├── staging/               # State: staging/terraform.tfstate
│   └── prod/                  # State: prod/terraform.tfstate
│       ├── vpc/
│       ├── eks/
│       └── rds/
└── modules/                   # State 없음 (재사용 모듈)


방법 2: Workspace 기반 분리

terraform workspace new dev
terraform workspace new staging
terraform workspace new prod
terraform workspace select prod

→ 같은 코드, 다른 State
→ S3 Key: env:/prod/terraform.tfstate
→ 주의: 환경 간 설정 차이가 큰 경우 부적합
```

**State 참조 (Cross-State Reference)**:
```hcl
# EKS 모듈에서 VPC State 참조
data "terraform_remote_state" "vpc" {
  backend = "s3"
  config = {
    bucket = "alli-terraform-state"
    key    = "prod/ap-northeast-2/vpc/terraform.tfstate"
    region = "ap-northeast-2"
  }
}

resource "aws_eks_cluster" "main" {
  name     = "alli-prod"
  role_arn = var.cluster_role_arn

  vpc_config {
    subnet_ids = data.terraform_remote_state.vpc.outputs.private_subnet_ids
  }
}
```

### terraform import

기존 수동 생성된 리소스를 Terraform 관리로 편입한다.

```bash
# 기존 방식 (CLI)
terraform import aws_vpc.main vpc-0abc123def456
terraform import aws_subnet.private[0] subnet-0abc123
terraform import aws_security_group.eks sg-0abc123

# Terraform 1.5+ import 블록 (선언적)
```

```hcl
# import.tf (Terraform 1.5+)
import {
  to = aws_vpc.main
  id = "vpc-0abc123def456"
}

import {
  to = aws_subnet.private[0]
  id = "subnet-0abc123"
}

# Plan으로 import 결과 미리 확인
# terraform plan -generate-config-out=generated.tf
# → 리소스의 현재 설정을 .tf 파일로 자동 생성
```

### terraform state 명령어

```bash
# State 내 리소스 목록 확인
terraform state list
# aws_vpc.main
# aws_subnet.private[0]
# aws_subnet.private[1]
# module.eks.aws_eks_cluster.main

# 특정 리소스 상세 확인
terraform state show aws_vpc.main

# 리소스 이름 변경 (리소스 재생성 없이)
terraform state mv aws_vpc.main aws_vpc.primary
# → .tf 코드에서도 이름을 main → primary로 변경 필요

# 모듈로 이동
terraform state mv aws_vpc.main module.network.aws_vpc.main

# State에서 리소스 제거 (실제 인프라는 유지)
terraform state rm aws_instance.temp
# → Terraform이 더 이상 이 리소스를 추적하지 않음
# → 다른 도구나 수동으로 관리하려 할 때 사용

# State 강제 갱신 (실제 인프라와 동기화)
terraform refresh    # deprecated
terraform apply -refresh-only
```

## 실전 예시

### State 마이그레이션: Local → Remote

```bash
# 1. 현재 local state 백업
cp terraform.tfstate terraform.tfstate.backup

# 2. backend.tf 추가
cat > backend.tf << 'EOF'
terraform {
  backend "s3" {
    bucket         = "alli-terraform-state"
    key            = "prod/network/terraform.tfstate"
    region         = "ap-northeast-2"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}
EOF

# 3. Backend 마이그레이션 실행
terraform init -migrate-state
# Terraform will ask:
# "Do you want to copy existing state to the new backend?"
# → yes

# 4. 마이그레이션 확인
terraform plan
# → "No changes. Your infrastructure matches the configuration."
```

### moved 블록으로 리팩토링

```hcl
# Terraform 1.1+: 코드에서 리소스 이름을 변경할 때
# state mv 대신 moved 블록 사용 (협업에 안전)

moved {
  from = aws_vpc.main
  to   = aws_vpc.primary
}

moved {
  from = aws_subnet.private
  to   = module.network.aws_subnet.private
}

# terraform plan 실행 시:
# aws_vpc.main has moved to aws_vpc.primary
# → 리소스 재생성 없이 State만 업데이트
```

### 대규모 State 관리 팁

```bash
# State 크기 확인
terraform state pull | wc -c
# 10MB 이상이면 분리 검토

# 특정 리소스만 Plan (대규모 State에서 속도 향상)
terraform plan -target=module.eks
terraform plan -refresh=false  # refresh 스킵 (주의해서 사용)

# State 내 리소스 수 확인
terraform state list | wc -l
# 200개 이상이면 State 분리 권장
```

## 면접 Q&A

### Q: Terraform State를 왜 Remote Backend에 저장해야 하나요?

**30초 답변**:
Local State는 한 사람만 사용할 수 있고, 파일 분실 위험이 있습니다. Remote Backend(S3+DynamoDB)를 사용하면 팀 전체가 동일한 State를 공유하고, State Lock으로 동시 수정 충돌을 방지하며, 버전 관리로 롤백이 가능합니다.

**2분 답변**:
Remote Backend는 세 가지 핵심 문제를 해결합니다.

첫째, 협업입니다. Local State는 개인 PC에만 존재하므로 팀원이 인프라를 수정하면 State 충돌이 발생합니다. S3 Backend는 중앙 저장소 역할을 합니다.

둘째, 동시성 제어입니다. DynamoDB Lock Table이 동시 apply를 방지합니다. Lock은 PutItem의 ConditionalCheck로 구현되어, 이미 Lock이 존재하면 후속 요청이 실패합니다. CI/CD 파이프라인이 동시에 실행되는 상황에서 필수적입니다.

셋째, 안전성입니다. S3 versioning으로 모든 State 변경 이력이 보존되어, 잘못된 apply 후에도 이전 State로 복구할 수 있습니다. KMS 암호화로 State에 포함된 민감 정보(DB 비밀번호 등)도 보호합니다.

추가로 CI/CD와의 통합을 고려하면, 로컬 개발자와 CI Runner가 동일한 Remote State를 사용해야 일관된 Plan/Apply가 가능합니다.

**💡 경험 연결**:
온프레미스에서 공유 NAS에 설정 파일을 저장하고 파일 잠금으로 동시 편집을 방지했던 것과 유사합니다. S3+DynamoDB는 이 패턴을 클라우드 네이티브하게 구현한 것입니다.

**⚠️ 주의**:
State에는 DB 비밀번호, API 키 등 민감 정보가 평문으로 저장될 수 있습니다. 반드시 S3 암호화(KMS)를 활성화하고, 접근 권한을 최소화해야 합니다.

---

### Q: terraform import는 언제, 어떻게 사용하나요?

**30초 답변**:
기존에 수동으로 생성한 클라우드 리소스를 Terraform 관리로 편입할 때 사용합니다. `terraform import <리소스주소> <실제ID>`로 State에 매핑을 추가한 뒤, 해당 리소스의 .tf 코드를 작성하여 Plan에서 차이가 없도록 맞춥니다.

**2분 답변**:
Import는 크게 세 가지 시나리오에서 사용합니다.

첫째, 레거시 인프라의 IaC 전환입니다. 콘솔이나 CLI로 생성한 기존 리소스를 Terraform으로 가져옵니다. 이때 핵심은 import 후 `terraform plan`에서 "No changes"가 나올 때까지 .tf 코드를 조정하는 것입니다.

둘째, State 복구입니다. State가 손상되었을 때 기존 리소스를 다시 import하여 State를 재구축합니다.

셋째, State 리팩토링입니다. 한 State에서 다른 State로 리소스를 이동할 때, 원본에서 `state rm` 후 대상에서 `import`합니다.

Terraform 1.5부터는 `import` 블록을 .tf 파일에 선언적으로 작성할 수 있고, `-generate-config-out` 옵션으로 리소스 설정을 자동 생성할 수 있어 대규모 import가 훨씬 편해졌습니다.

**💡 경험 연결**:
온프레미스 환경에서 수동으로 구축된 서버들을 Ansible 관리로 편입했던 경험이 있는데, Terraform import도 동일한 "기존 인프라의 코드화" 과정입니다.

**⚠️ 주의**:
Import는 State만 업데이트하고 .tf 코드는 자동 생성하지 않습니다(1.5+ generate-config 제외). Import 후 반드시 .tf 코드를 작성하고 `plan`으로 확인해야 합니다.

---

### Q: State가 꼬였을 때(State drift) 어떻게 해결하나요?

**30초 답변**:
State drift는 누군가 콘솔에서 직접 리소스를 수정했을 때 발생합니다. `terraform plan`을 실행하면 drift를 감지하고, `terraform apply -refresh-only`로 State를 실제 인프라에 맞게 갱신하거나, plan 결과를 apply하여 코드 상태로 되돌릴 수 있습니다.

**2분 답변**:
State drift 대응은 상황에 따라 다릅니다.

**시나리오 1: 콘솔 수정 감지**
`terraform plan` 실행 시 예상치 않은 변경이 표시됩니다. 콘솔 수정이 의도된 것이면 `apply -refresh-only`로 State를 실제에 맞추고, .tf 코드도 수정합니다. 의도되지 않은 것이면 `terraform apply`로 코드 상태로 원복합니다.

**시나리오 2: State와 코드 불일치**
`terraform state list`로 State 내 리소스를 확인하고, `state show`로 상세 속성을 비교합니다. 필요 시 `state rm` + `import`로 매핑을 재설정합니다.

**시나리오 3: 리소스가 외부에서 삭제됨**
Plan에서 "read during apply" 에러가 발생합니다. `state rm`으로 State에서 제거하면 Terraform이 새로 생성합니다.

예방을 위해 정기적으로 `terraform plan`을 CI에서 실행하여 drift를 조기 감지하는 것이 좋습니다. Drift detection을 자동화하면 콘솔 변경을 즉시 알 수 있습니다.

**💡 경험 연결**:
설정 관리 도구(Ansible 등)와 수동 변경이 공존하는 환경에서 "Configuration Drift"는 항상 골치아픈 문제였습니다. Terraform의 Plan은 이 drift를 자동 감지하는 강력한 도구입니다.

**⚠️ 주의**:
`terraform refresh`(deprecated)나 `apply -refresh-only`는 State만 갱신하고 코드는 수정하지 않습니다. 반드시 코드도 함께 업데이트해야 다음 apply에서 의도치 않은 롤백이 발생하지 않습니다.

## Allganize 맥락

- **멀티 환경 State 분리**: Allganize의 dev/staging/prod 환경을 각각 독립된 State로 관리하면, prod apply가 dev State에 영향을 주지 않는다.
- **AWS + Azure 이중 State**: AWS 인프라와 Azure 인프라는 별도 State로 분리하되, `terraform_remote_state` data source로 상호 참조가 가능하다.
- **CI/CD State Lock**: Atlantis나 GitHub Actions에서 자동 Plan/Apply 실행 시, DynamoDB Lock이 동시 실행을 방지하여 State 충돌 사고를 예방한다.
- **JD 연결 — "Terraform 경험"**: State 관리는 Terraform 실무 경험의 핵심 지표이다. "Remote Backend + Lock + 암호화를 어떻게 구성했는가"를 구체적으로 설명할 수 있어야 한다.
- **레거시 전환 경험**: 온프레미스 인프라를 Terraform으로 import하여 코드화한 경험은 Allganize에서 기존 수동 인프라를 IaC로 전환하는 작업에 직접 적용 가능하다.

---
**핵심 키워드**: `Remote Backend` `S3` `DynamoDB` `State Lock` `terraform import` `state mv` `state rm` `moved 블록` `State Drift` `force-unlock` `-refresh-only`
