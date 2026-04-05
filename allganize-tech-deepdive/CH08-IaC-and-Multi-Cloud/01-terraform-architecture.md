# Terraform 아키텍처 기초

> **TL;DR**: Terraform은 Provider-Resource 모델로 인프라를 선언적으로 정의하고, Plan-Apply 2단계 워크플로로 안전하게 변경을 적용한다.
> State 파일이 실제 인프라와 코드 사이의 "진실의 원천(Single Source of Truth)" 역할을 수행한다.
> HCL(HashiCorp Configuration Language)로 멀티클라우드 인프라를 동일한 문법으로 관리할 수 있다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Terraform 동작 흐름

```
  개발자가 .tf 파일 작성
         │
         ▼
  ┌──────────────┐
  │ terraform init│  ◀── Provider 플러그인 다운로드
  └──────┬───────┘      .terraform/ 디렉토리 생성
         │
         ▼
  ┌──────────────┐
  │ terraform plan│  ◀── State vs Config 비교 → Diff 계산
  └──────┬───────┘      실제 변경 없음 (Dry-Run)
         │
         ▼
  ┌───────────────┐
  │ terraform apply│  ◀── Provider API 호출 → 리소스 생성/수정/삭제
  └──────┬────────┘      State 파일 업데이트
         │
         ▼
  ┌──────────────────┐
  │ State File 갱신   │  ◀── terraform.tfstate (JSON)
  └──────────────────┘
```

### Provider (프로바이더)

Provider는 Terraform이 특정 클라우드/서비스 API와 통신하기 위한 플러그인이다.

```hcl
# AWS Provider 설정
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"    # 5.x 최신 버전 사용
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.80"
    }
  }
  required_version = ">= 1.6.0"
}

provider "aws" {
  region = "ap-northeast-2"   # 서울 리전

  default_tags {
    tags = {
      Environment = "production"
      ManagedBy   = "terraform"
      Team        = "devops"
    }
  }
}
```

- **hashicorp/aws**: AWS 리소스 (EC2, VPC, EKS, IAM 등)
- **hashicorp/azurerm**: Azure 리소스 (VNET, AKS, AAD 등)
- **hashicorp/kubernetes**: K8s 리소스 (Deployment, Service 등)
- **hashicorp/helm**: Helm Chart 배포

### Resource (리소스)

실제 인프라 객체를 선언적으로 정의한다.

```hcl
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "alli-prod-vpc"
  }
}

resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet("10.0.0.0/16", 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "alli-prod-private-${count.index}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}
```

**리소스 라이프사이클**:
```
+create  : 새 리소스 생성
~update  : 기존 리소스 수정 (in-place)
-/+replace: 삭제 후 재생성 (ForceNew 속성 변경 시)
-destroy : 리소스 삭제
```

### Data Source (데이터 소스)

기존 리소스의 정보를 읽기 전용으로 조회한다. 직접 관리하지 않는 외부 리소스 참조에 사용한다.

```hcl
# 이미 존재하는 AMI 조회
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]  # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

# 현재 AWS 계정 정보
data "aws_caller_identity" "current" {}

# 사용 가능한 AZ 목록
data "aws_availability_zones" "available" {
  state = "available"
}
```

### State (상태 파일)

```
┌─────────────────────────────────────────────┐
│              Terraform State                 │
│                                             │
│  .tf 코드 ◀──── State ────▶ 실제 인프라     │
│  (Desired)      (Mapping)    (Actual)        │
│                                             │
│  State는 "코드에 선언된 리소스"와             │
│  "실제 클라우드에 존재하는 리소스"를           │
│  1:1 매핑하는 JSON 파일                      │
└─────────────────────────────────────────────┘
```

State가 중요한 이유:
1. **성능**: 매번 클라우드 API를 호출하지 않고 State에서 현재 상태를 파악
2. **매핑**: `aws_vpc.main` → `vpc-0abc123def456` 같은 ID 매핑 유지
3. **의존성 추적**: 리소스 간 의존 관계 그래프 저장
4. **협업**: 팀원 간 인프라 상태 공유 (Remote Backend 필수)

### Plan / Apply 분리의 가치

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Developer  │     │   Reviewer   │     │   Approver   │
│              │     │              │     │              │
│  tf plan     │────▶│  PR에서      │────▶│  tf apply    │
│  실행 & 확인 │     │  plan 결과   │     │  승인 실행   │
│              │     │  리뷰        │     │              │
└──────────────┘     └──────────────┘     └──────────────┘

  "plan에서 본 것 = apply에서 실행되는 것" 보장
  → -out=planfile 옵션으로 plan 결과를 저장하여 apply에 전달
```

```bash
# Plan 결과를 파일로 저장
terraform plan -out=tfplan

# 저장된 plan을 그대로 적용 (재계산 없음)
terraform apply tfplan
```

## 실전 예시

### 프로젝트 디렉토리 구조

```
infrastructure/
├── environments/
│   ├── dev/
│   │   ├── main.tf          # 모듈 호출
│   │   ├── variables.tf     # 환경별 변수
│   │   ├── terraform.tfvars # 변수 값
│   │   ├── outputs.tf       # 출력 값
│   │   └── backend.tf       # S3 backend 설정
│   ├── staging/
│   │   └── ...
│   └── prod/
│       └── ...
├── modules/
│   ├── vpc/
│   ├── eks/
│   └── rds/
└── global/
    ├── iam/
    └── route53/
```

### 기본 워크플로 실행

```bash
# 1. 초기화 (Provider 다운로드, Backend 설정)
cd infrastructure/environments/prod
terraform init

# 2. 코드 포맷팅 & 검증
terraform fmt -recursive
terraform validate

# 3. Plan (변경사항 미리보기)
terraform plan -out=tfplan

# 출력 예시:
# Terraform will perform the following actions:
#
#   # aws_vpc.main will be created
#   + resource "aws_vpc" "main" {
#       + cidr_block           = "10.0.0.0/16"
#       + enable_dns_hostnames = true
#       + id                   = (known after apply)
#       ...
#     }
#
# Plan: 1 to add, 0 to change, 0 to destroy.

# 4. Apply (실제 적용)
terraform apply tfplan

# 5. 출력값 확인
terraform output vpc_id
```

### 리소스 의존성 그래프

```bash
# 의존성 그래프 생성 (DOT 형식)
terraform graph | dot -Tpng > graph.png

# 특정 리소스만 적용
terraform apply -target=aws_vpc.main
```

```
의존성 자동 해석 예시:

aws_vpc.main
    │
    ├──▶ aws_subnet.private[0..2]
    │         │
    │         └──▶ aws_nat_gateway.main
    │                   │
    │                   └──▶ aws_route_table.private
    │
    └──▶ aws_subnet.public[0..2]
              │
              └──▶ aws_internet_gateway.main
                        │
                        └──▶ aws_route_table.public
```

### Variables와 Outputs

```hcl
# variables.tf
variable "environment" {
  description = "Environment name (dev/staging/prod)"
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

# outputs.tf
output "vpc_id" {
  description = "The ID of the VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "List of private subnet IDs"
  value       = aws_subnet.private[*].id
}
```

## 면접 Q&A

### Q: Terraform의 Plan-Apply 워크플로가 왜 중요한가요?

**30초 답변**:
Plan은 실제 변경 전 Dry-Run으로 "무엇이 변경될지" 미리 확인하는 단계입니다. Apply는 Plan 결과를 실제로 적용합니다. 이 분리를 통해 실수로 인한 인프라 파괴를 방지하고, PR 리뷰 시 Plan 결과를 공유하여 팀 합의를 거칠 수 있습니다.

**2분 답변**:
Terraform의 Plan-Apply 분리는 인프라 변경의 안전성을 보장하는 핵심 메커니즘입니다. Plan 단계에서 State와 실제 인프라, 코드를 3-way 비교하여 정확한 변경 사항을 계산합니다. `-out=planfile` 옵션으로 Plan을 저장하면, Apply 시 정확히 그 Plan만 실행되어 "Plan에서 본 것 = Apply에서 실행되는 것"이 보장됩니다.

CI/CD와 결합하면 더 강력해집니다. PR 생성 시 자동으로 `terraform plan`을 실행하고 결과를 코멘트로 달아 리뷰어가 인프라 변경을 코드 리뷰처럼 검토할 수 있습니다. 승인 후 merge 시에만 apply가 실행되는 구조로 운영하면, 프로덕션 인프라 변경에 대한 거버넌스가 확보됩니다.

**💡 경험 연결**:
폐쇄망 환경에서 인프라 변경은 변경 관리 프로세스(RFC)를 거쳤는데, Terraform의 Plan-Apply는 이를 코드 레벨에서 자동화한 것과 같습니다. Plan 결과가 곧 변경 영향도 분석서 역할을 합니다.

**⚠️ 주의**:
`terraform apply` 없이 `-auto-approve`를 사용하면 Plan 리뷰 없이 바로 적용되므로 프로덕션에서는 절대 사용하지 않아야 합니다.

---

### Q: Terraform의 Resource와 Data Source의 차이는 무엇인가요?

**30초 답변**:
Resource는 Terraform이 직접 생성/수정/삭제를 관리하는 인프라 객체입니다. Data Source는 이미 존재하는 외부 리소스의 정보를 읽기 전용으로 조회하는 것입니다. Resource는 라이프사이클을 관리하고, Data Source는 참조만 합니다.

**2분 답변**:
Resource는 Terraform이 전체 라이프사이클(CRUD)을 관리합니다. `terraform destroy` 시 삭제되고, 속성 변경 시 update 또는 replace가 실행됩니다. State에 매핑되어 추적됩니다.

Data Source는 Terraform 외부에서 생성된 리소스나 동적 정보를 조회합니다. 예를 들어, 다른 팀이 관리하는 VPC ID를 참조하거나, 최신 AMI ID를 조회할 때 사용합니다. `terraform destroy`를 해도 Data Source로 참조한 리소스는 영향받지 않습니다.

실무에서는 조직 경계에 따라 구분합니다. 우리 팀이 관리하는 EKS 클러스터는 Resource로, 네트워크 팀이 관리하는 VPC는 Data Source로 참조하는 식입니다. 이렇게 하면 각 팀의 Terraform State가 독립적으로 유지되면서도 서로의 리소스를 참조할 수 있습니다.

**💡 경험 연결**:
온프레미스에서도 "우리가 관리하는 서버"와 "다른 팀에서 제공하는 공유 인프라"를 구분했는데, Terraform의 Resource/Data Source 구분이 이 개념과 정확히 일치합니다.

**⚠️ 주의**:
Data Source 조회 실패 시 전체 Plan이 실패하므로, 참조하는 외부 리소스가 반드시 존재해야 합니다. `try()` 함수나 `optional` 속성으로 방어 코드를 작성하는 것이 좋습니다.

---

### Q: Terraform State가 손상되거나 분실되면 어떻게 대응하나요?

**30초 답변**:
Remote Backend(S3 + versioning)를 사용하면 이전 버전으로 복구할 수 있습니다. 만약 State가 완전히 분실되면 `terraform import`로 기존 리소스를 하나씩 State에 다시 등록해야 합니다. 최악의 경우 리소스를 전부 재생성하는 것보다 import가 안전합니다.

**2분 답변**:
State 분실은 Terraform 운영에서 가장 심각한 사고 중 하나입니다. 대응 전략은 단계별로 나뉩니다.

첫째, 예방 차원에서 S3 Backend에 versioning을 활성화하고, DynamoDB로 State Lock을 걸어 동시 수정을 방지합니다. State 파일 자체도 암호화합니다.

둘째, 복구 시나리오입니다. S3 versioning이 있으면 이전 버전으로 롤백합니다. 없으면 `terraform import`로 기존 클라우드 리소스를 새 State에 매핑합니다. `terraform import aws_vpc.main vpc-0abc123`처럼 리소스 타입과 실제 ID를 지정합니다.

셋째, 대규모 인프라에서는 수동 import가 비현실적이므로 `terraformer`나 `import` 블록(Terraform 1.5+)을 사용하여 자동화합니다.

**💡 경험 연결**:
온프레미스 환경에서 CMDB(Configuration Management Database) 동기화가 깨지는 상황과 유사합니다. State는 클라우드 인프라의 CMDB와 같으므로 항상 백업과 버전 관리가 필수입니다.

**⚠️ 주의**:
State가 없는 상태에서 `terraform apply`를 실행하면 이미 존재하는 리소스를 중복 생성하려 시도합니다. 반드시 import 먼저 수행해야 합니다.

---

### Q: Provider 버전 관리는 어떻게 하나요?

**30초 답변**:
`required_providers` 블록에서 version constraint를 지정하고, `terraform init` 시 생성되는 `.terraform.lock.hcl` 파일로 정확한 버전을 고정합니다. 이 lock 파일을 Git에 커밋하여 팀 전체가 동일한 Provider 버전을 사용하도록 합니다.

**2분 답변**:
Provider 버전 관리는 인프라 재현성의 핵심입니다. `~> 5.0`은 5.x 범위의 최신 버전을 허용하고, `= 5.31.0`은 정확한 버전을 고정합니다. `.terraform.lock.hcl`은 npm의 `package-lock.json`과 같은 역할로, 실제 다운로드된 Provider의 해시값을 포함합니다.

프로덕션에서는 `~>` (pessimistic constraint)를 사용하되, `.terraform.lock.hcl`을 반드시 커밋합니다. Provider 업그레이드는 별도 PR로 진행하고, `terraform plan`에서 의도치 않은 변경이 없는지 확인 후 적용합니다.

멀티 플랫폼 환경(CI에서 Linux, 로컬에서 macOS)에서는 `terraform providers lock -platform=linux_amd64 -platform=darwin_amd64`로 여러 플랫폼의 해시를 lock 파일에 추가합니다.

**💡 경험 연결**:
패키지 버전 고정은 어떤 환경이든 중요합니다. 온프레미스에서 OS 패치 버전을 고정하듯, Terraform Provider도 정확한 버전 관리가 인프라 안정성의 기본입니다.

**⚠️ 주의**:
`.terraform.lock.hcl`을 `.gitignore`에 넣으면 안 됩니다. 팀원마다 다른 Provider 버전이 적용되어 Plan 결과가 달라질 수 있습니다.

## Allganize 맥락

- **멀티클라우드 IaC**: Allganize는 AWS와 Azure에서 K8s 기반으로 Alli 서비스를 운영한다. Terraform으로 두 클라우드를 동일한 HCL 코드 체계로 관리하면 일관된 인프라 거버넌스가 가능하다.
- **Provider 분리 운영**: AWS Provider와 Azure Provider를 별도 디렉토리(State)로 분리하되, Data Source로 상호 참조하는 패턴이 멀티클라우드 Terraform의 핵심이다.
- **JD 연결 — "IaC(Terraform/Pulumi) 경험"**: Terraform의 동작 원리(Provider, State, Plan/Apply)를 정확히 이해하고 있음을 보여주는 것이 1차 기술면접의 기본 관문이다.
- **온프레미스 경험 연결**: 폐쇄망에서의 변경관리(RFC) 경험은 Terraform의 Plan-Review-Apply 워크플로와 자연스럽게 연결되며, 이를 코드화/자동화했다는 점이 DevOps 전환의 핵심 스토리다.

---
**핵심 키워드**: `Provider` `Resource` `Data Source` `State` `Plan/Apply` `HCL` `.terraform.lock.hcl` `terraform init` `terraform import`
