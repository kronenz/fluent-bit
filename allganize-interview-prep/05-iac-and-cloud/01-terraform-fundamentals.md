# 01. 테라폼 기초 (Terraform Fundamentals)

> **TL;DR**
> - 테라폼(Terraform)은 HCL로 인프라를 코드로 선언하고, State 파일로 실제 인프라와 동기화하는 IaC 도구다
> - `init` -> `plan` -> `apply` -> `destroy` 워크플로우를 이해하면 운영의 80%를 커버한다
> - 폐쇄망(Air-gapped) 온프레미스 경험은 Provider 미러링, 로컬 State 관리 등에서 강점이 된다

---

## 1. HCL 문법 기초 (HashiCorp Configuration Language)

### 1-1. 핵심 블록 구조

테라폼의 모든 설정은 **블록(Block)** 단위로 구성된다.

```hcl
# terraform 블록: 버전 및 백엔드 설정
terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# provider 블록: 클라우드 공급자 설정
provider "aws" {
  region = "ap-northeast-2"  # 서울 리전
}
```

### 1-2. Resource (리소스)

실제 인프라 자원을 생성/관리하는 핵심 블록이다.

```hcl
resource "aws_instance" "web_server" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.medium"

  tags = {
    Name        = "allganize-web"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}
```

### 1-3. Data Source (데이터 소스)

이미 존재하는 리소스를 **읽기 전용**으로 참조한다.

```hcl
# 최신 Amazon Linux 2 AMI를 조회
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
}

resource "aws_instance" "app" {
  ami           = data.aws_ami.amazon_linux.id
  instance_type = "t3.medium"
}
```

### 1-4. Variable / Output / Locals

```hcl
# variable: 외부에서 값을 주입받는다
variable "environment" {
  description = "배포 환경 (dev/staging/prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment는 dev, staging, prod 중 하나여야 합니다."
  }
}

# locals: 내부에서 계산된 값을 재사용한다
locals {
  common_tags = {
    Environment = var.environment
    Team        = "platform"
    ManagedBy   = "terraform"
  }
  name_prefix = "allganize-${var.environment}"
}

# output: 다른 모듈이나 사용자에게 값을 노출한다
output "instance_public_ip" {
  description = "웹 서버 퍼블릭 IP"
  value       = aws_instance.web_server.public_ip
}
```

---

## 2. State 파일 관리

### 2-1. State란 무엇인가

State 파일(`terraform.tfstate`)은 **테라폼이 관리하는 리소스의 현재 상태**를 JSON으로 기록한 파일이다. 테라폼은 이 파일을 기준으로 실제 인프라와의 차이(Drift)를 계산한다.

| 구분 | 로컬 State | 리모트 State |
|------|-----------|-------------|
| 저장 위치 | 작업 디렉토리 | S3, Azure Blob 등 |
| 팀 협업 | 불가 (충돌 위험) | 가능 (Lock 지원) |
| 보안 | 파일 시스템 의존 | 암호화 + 접근 제어 |
| 폐쇄망 적합성 | 높음 | 내부 Minio/NFS 활용 |

### 2-2. Remote Backend (S3 + DynamoDB)

```hcl
terraform {
  backend "s3" {
    bucket         = "allganize-terraform-state"
    key            = "prod/vpc/terraform.tfstate"
    region         = "ap-northeast-2"
    encrypt        = true
    dynamodb_table = "terraform-lock"  # State Lock용
  }
}
```

**DynamoDB Lock 테이블 생성 (부트스트랩):**

```hcl
resource "aws_dynamodb_table" "terraform_lock" {
  name         = "terraform-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
```

> **폐쇄망 경험 연결:** 온프레미스에서는 MinIO를 S3 호환 백엔드로 사용하거나, Consul/PostgreSQL을 State Backend로 활용한 경험이 있다면 강점이다.

---

## 3. Provider 구조와 Module 작성법

### 3-1. Provider 동작 원리

Provider는 테라폼과 클라우드 API 사이의 **번역기(Adapter)**다.

```
테라폼 코어 <--gRPC--> Provider 플러그인 <--REST API--> AWS/Azure
```

**폐쇄망 Provider 미러링:**

```bash
# 인터넷이 되는 환경에서 Provider 다운로드
terraform providers mirror /path/to/mirror

# 폐쇄망에서 미러 디렉토리 참조
# ~/.terraformrc
provider_installation {
  filesystem_mirror {
    path    = "/opt/terraform/providers"
    include = ["registry.terraform.io/*/*"]
  }
  direct {
    exclude = ["registry.terraform.io/*/*"]
  }
}
```

### 3-2. Module 작성법

모듈은 **재사용 가능한 테라폼 코드 패키지**다.

```
modules/
  vpc/
    main.tf       # 리소스 정의
    variables.tf  # 입력 변수
    outputs.tf    # 출력 값
    versions.tf   # Provider 버전
```

```hcl
# modules/vpc/main.tf
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-vpc"
  })
}

resource "aws_subnet" "private" {
  count             = length(var.private_subnets)
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.private_subnets[count.index]
  availability_zone = var.azs[count.index]

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-private-${count.index + 1}"
    Tier = "private"
  })
}

# 모듈 호출
module "vpc" {
  source = "./modules/vpc"

  vpc_cidr        = "10.0.0.0/16"
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  azs             = ["ap-northeast-2a", "ap-northeast-2c"]
  name_prefix     = "allganize-prod"
  common_tags     = local.common_tags
}
```

---

## 4. 워크플로우: init / plan / apply / destroy

```
terraform init       # Provider 다운로드, 백엔드 초기화
    |
terraform plan       # 변경 사항 미리보기 (Dry-run)
    |
terraform apply      # 실제 인프라 변경 적용
    |
terraform destroy    # 전체 리소스 삭제 (주의!)
```

### 실전 팁

```bash
# plan 결과를 파일로 저장하여 정확히 그 계획을 apply
terraform plan -out=tfplan
terraform apply tfplan

# 특정 리소스만 대상으로 지정
terraform plan -target=module.vpc
terraform apply -target=aws_instance.web_server

# 변수 파일 분리 (환경별 관리)
terraform plan -var-file=environments/prod.tfvars
```

---

## 5. 고급 기능: State Lock, Import, Workspace

### 5-1. State Lock

팀원 동시 작업 시 State 파일 충돌을 방지하는 **잠금 메커니즘**이다.

```bash
# Lock이 걸려 있을 때 강제 해제 (비상 시에만!)
terraform force-unlock <LOCK_ID>
```

### 5-2. Import (기존 리소스 가져오기)

수동으로 만든 리소스를 테라폼 관리 하에 편입시킨다.

```bash
# 기존 방식 (CLI)
terraform import aws_instance.web_server i-0abc123def456

# Terraform 1.5+ import 블록 (권장)
```

```hcl
import {
  to = aws_instance.web_server
  id = "i-0abc123def456"
}
```

> **폐쇄망 경험 연결:** 온프레미스에서 수동으로 관리하던 인프라를 IaC로 전환할 때 `import` 기능이 핵심이다. 이 경험은 레거시 인프라 마이그레이션 면접 질문에서 강력한 답변이 된다.

### 5-3. Workspace

하나의 코드베이스로 **여러 환경을 분리 관리**한다.

```bash
terraform workspace new dev
terraform workspace new staging
terraform workspace new prod
terraform workspace select prod
terraform workspace list
```

```hcl
# Workspace 이름을 활용한 환경 분기
locals {
  instance_type = {
    dev     = "t3.small"
    staging = "t3.medium"
    prod    = "t3.large"
  }
}

resource "aws_instance" "app" {
  instance_type = local.instance_type[terraform.workspace]
}
```

---

## 면접 Q&A

### Q1. "테라폼의 State 파일은 왜 필요한가요?"

> **이렇게 대답한다:**
> State 파일은 테라폼이 선언된 코드와 실제 인프라 사이의 **매핑 정보**를 저장합니다. 이를 통해 `plan` 시 변경 사항을 정확히 계산하고, 리소스 간 의존성을 추적합니다. State 없이는 테라폼이 어떤 리소스를 관리하는지 알 수 없기 때문에, 매번 전체 인프라를 새로 만들려 할 것입니다. 팀 환경에서는 S3 + DynamoDB 같은 Remote Backend를 사용해 State를 중앙 관리하고, Lock으로 동시 변경을 방지합니다.

### Q2. "terraform plan과 apply의 차이는?"

> **이렇게 대답한다:**
> `plan`은 현재 State와 코드를 비교해 **변경 예정 사항을 보여주는 Dry-run**입니다. 실제 인프라를 변경하지 않습니다. `apply`는 plan 결과를 **실제로 적용**합니다. 운영 환경에서는 반드시 `plan -out=tfplan`으로 계획을 저장한 뒤, 리뷰 후 `apply tfplan`으로 정확히 동일한 계획을 적용하는 것이 안전합니다.

### Q3. "온프레미스 폐쇄망에서 테라폼을 어떻게 사용하나요?"

> **이렇게 대답한다:**
> 세 가지 핵심 과제가 있습니다. 첫째, **Provider 미러링** - 인터넷이 되는 환경에서 `terraform providers mirror`로 플러그인을 다운로드하고, `.terraformrc`에 `filesystem_mirror`를 설정합니다. 둘째, **State Backend** - S3 대신 MinIO나 Consul, PostgreSQL을 내부에 구축합니다. 셋째, **Module Registry** - 공개 레지스트리 대신 Git 리포지토리나 로컬 경로를 모듈 소스로 사용합니다. 실제로 폐쇄망에서 이런 환경을 구축하고 운영한 경험이 있으며, 이 과정에서 네트워크 제약 하에서의 문제 해결 능력을 쌓았습니다.

### Q4. "모듈을 왜 만들어야 하나요? 그냥 복사하면 안 되나요?"

> **이렇게 대답한다:**
> 복사-붙여넣기는 초기에 빠르지만, 환경이 10개, 100개로 늘어나면 **변경 사항 전파가 불가능**해집니다. 모듈은 입력(Variable)과 출력(Output)을 정의하는 인터페이스를 제공하여, 하나의 코드 변경이 모든 환경에 일관되게 적용됩니다. 또한 모듈 버저닝을 통해 프로덕션은 안정 버전, 개발은 최신 버전을 사용하는 **점진적 롤아웃**이 가능합니다.

### Q5. "기존에 수동으로 만든 인프라를 테라폼으로 관리하려면?"

> **이렇게 대답한다:**
> `terraform import`를 사용합니다. Terraform 1.5부터는 코드에 `import` 블록을 선언하는 방식이 권장됩니다. 실무에서는 먼저 리소스에 대응하는 HCL 코드를 작성하고, import를 실행한 뒤, `plan`으로 drift가 없는지 확인합니다. 온프레미스에서 수년간 수동 관리하던 인프라를 IaC로 전환한 경험이 있다면, 이 과정에서의 어려움과 해결 방법을 구체적으로 설명할 수 있습니다.

---

**핵심 키워드 5선:**
`HCL`, `State 관리 (State Management)`, `Remote Backend`, `Module 재사용 (Module Reusability)`, `Provider 미러링 (Provider Mirroring)`
