# Terraform 치트시트 (Cheatsheet)

> **TL;DR**
> 1. `init` -> `plan` -> `apply` -> `destroy`가 기본 워크플로우
> 2. State 파일은 인프라의 진실 공급원(Source of Truth)이며 반드시 원격 보관
> 3. 모듈(Module)과 변수(Variable)로 재사용 가능한 IaC를 구성한다

---

## 1. CLI 핵심 명령어

```bash
# 초기화 (프로바이더 다운로드, 백엔드 설정)
terraform init
terraform init -upgrade          # 프로바이더 업그레이드
terraform init -reconfigure      # 백엔드 재설정

# 계획 (변경사항 미리보기)
terraform plan
terraform plan -out=plan.tfplan  # 플랜 파일 저장
terraform plan -target=aws_instance.web  # 특정 리소스만

# 적용
terraform apply
terraform apply plan.tfplan      # 저장된 플랜 적용
terraform apply -auto-approve    # 확인 생략 (CI/CD용)

# 삭제
terraform destroy
terraform destroy -target=aws_instance.web

# 포맷 / 검증
terraform fmt                    # HCL 포맷 정리
terraform fmt -check             # CI에서 포맷 검사
terraform validate               # 구문 검증

# 출력값 확인
terraform output
terraform output -json
terraform output vpc_id
```

---

## 2. HCL 핵심 패턴

### 변수 (Variable)

```hcl
# 변수 정의
variable "env" {
  type        = string
  default     = "dev"
  description = "배포 환경"
}

variable "instance_types" {
  type = map(string)
  default = {
    dev  = "t3.micro"
    prod = "t3.large"
  }
}

# 사용
resource "aws_instance" "web" {
  instance_type = var.instance_types[var.env]
}
```

### 조건문 (Conditional)

```hcl
# 삼항 연산자
count = var.env == "prod" ? 3 : 1

# 조건부 리소스 생성
resource "aws_cloudwatch_alarm" "cpu" {
  count = var.env == "prod" ? 1 : 0
  # ...
}
```

### 반복 (Loop)

```hcl
# count
resource "aws_subnet" "private" {
  count      = length(var.azs)
  cidr_block = cidrsubnet(var.vpc_cidr, 8, count.index)
}

# for_each (권장)
resource "aws_subnet" "private" {
  for_each   = toset(var.azs)
  cidr_block = cidrsubnet(var.vpc_cidr, 8, index(var.azs, each.value))
}

# for 표현식
output "subnet_ids" {
  value = [for s in aws_subnet.private : s.id]
}

# dynamic 블록
dynamic "ingress" {
  for_each = var.ingress_rules
  content {
    from_port   = ingress.value.from
    to_port     = ingress.value.to
    protocol    = ingress.value.protocol
    cidr_blocks = ingress.value.cidrs
  }
}
```

### 모듈 호출 (Module)

```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0.0"

  name = "my-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["ap-northeast-2a", "ap-northeast-2c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = var.env != "prod"
}
```

---

## 3. State 관리 명령어

```bash
# State 목록 조회
terraform state list
terraform state show aws_instance.web

# State에서 리소스 제거 (실제 삭제 안 함)
terraform state rm aws_instance.web

# State 리소스 이동 (리팩토링 시)
terraform state mv aws_instance.web aws_instance.api

# State 가져오기 (기존 리소스 Import)
terraform import aws_instance.web i-1234567890

# import 블록 (v1.5+)
import {
  to = aws_instance.web
  id = "i-1234567890"
}

# 원격 백엔드 설정 (S3)
terraform {
  backend "s3" {
    bucket         = "my-tf-state"
    key            = "prod/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "tf-lock"
    encrypt        = true
  }
}

# State 강제 잠금 해제 (주의!)
terraform force-unlock <LOCK_ID>
```

---

## 4. 자주 쓰는 함수

| 함수 | 설명 | 예시 |
|---|---|---|
| `lookup` | Map에서 키 조회 | `lookup(var.amis, var.region, "default")` |
| `merge` | Map 병합 | `merge(var.default_tags, var.extra_tags)` |
| `flatten` | 중첩 리스트 평탄화 | `flatten([var.public_subnets, var.private_subnets])` |
| `try` | 에러 시 대체값 | `try(var.config.name, "default")` |
| `coalesce` | 첫 번째 non-null | `coalesce(var.name, "unnamed")` |
| `cidrsubnet` | CIDR 서브넷 계산 | `cidrsubnet("10.0.0.0/16", 8, 1)` |
| `templatefile` | 템플릿 렌더링 | `templatefile("user_data.sh", { env = var.env })` |
| `jsonencode` | JSON 문자열 변환 | `jsonencode(var.policy)` |
| `toset` | Set 변환 (for_each용) | `toset(["a", "b", "c"])` |
| `format` | 문자열 포맷 | `format("%s-%s", var.project, var.env)` |

---

## 5. 실전 팁

```bash
# 특정 리소스만 적용
terraform apply -target=module.vpc

# 변수 파일 지정
terraform plan -var-file=prod.tfvars

# 환경변수로 변수 전달
export TF_VAR_env="prod"

# 디버그 로그
export TF_LOG=DEBUG
export TF_LOG_PATH=./terraform.log

# 워크스페이스 (환경 분리)
terraform workspace list
terraform workspace new prod
terraform workspace select prod
```

---

## 6. 면접 빈출 질문

**Q1. `terraform plan`에서 변경이 없는데 `apply`하면 어떻게 되나?**
> - 아무 변경도 일어나지 않는다
> - Terraform은 State와 실제 인프라를 비교하여 차이(drift)가 있을 때만 변경
> - `plan`의 결과가 "No changes"이면 `apply`도 동일

**Q2. State 파일이 손상되거나 분실되면 어떻게 복구하나?**
> 1. S3 버전관리(Versioning)에서 이전 버전 복구
> 2. 불가능하면 `terraform import`로 기존 리소스를 하나씩 재등록
> 3. 예방: 원격 백엔드 + 버전관리 + DynamoDB 잠금 필수
> 4. `terraform state pull/push`로 수동 백업도 가능

**Q3. `count`와 `for_each`의 차이와 사용 기준은?**
> - `count`: 인덱스 기반, 중간 삭제 시 뒤 리소스가 전부 재생성
> - `for_each`: 키 기반, 특정 항목 삭제해도 나머지 영향 없음
> - 실무에서는 `for_each`를 권장 (안정적인 리소스 주소)
> - `count`는 단순 on/off (0 또는 1)에만 사용

---

**핵심 키워드**: `State`, `Plan/Apply`, `for_each vs count`, `Remote Backend`, `Module`
