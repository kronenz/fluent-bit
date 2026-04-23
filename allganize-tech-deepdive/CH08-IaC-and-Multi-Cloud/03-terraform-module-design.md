# Terraform 모듈 설계

> **TL;DR**: Terraform 모듈은 재사용 가능한 인프라 컴포넌트로, input variables/output values로 인터페이스를 정의한다.
> 모듈 버전 관리(Git 태그/Registry)로 안정적인 배포를 보장하고, 환경별로 동일 모듈을 다른 파라미터로 호출한다.
> 좋은 모듈은 "필요한 것만 노출하고, 합리적 기본값을 제공하며, 의견을 강제하지 않는다."

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 모듈 구조

```
모듈 = 재사용 가능한 .tf 파일의 디렉토리

modules/
├── vpc/
│   ├── main.tf          # 리소스 정의
│   ├── variables.tf     # Input 변수
│   ├── outputs.tf       # Output 값
│   ├── versions.tf      # Provider 요구사항
│   ├── locals.tf        # 내부 계산 값
│   ├── data.tf          # Data source 조회
│   └── README.md        # 사용법 문서
├── eks/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── iam.tf           # IAM 역할/정책 (리소스가 많으면 파일 분리)
│   ├── node-groups.tf
│   └── addons.tf
└── rds/
    └── ...
```

### Root Module vs Child Module

```
┌────────────────────────────────────────────────────┐
│  Root Module (environments/prod/)                   │
│                                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  │
│  │ module "vpc" │  │ module "eks" │  │module"rds"│  │
│  │             │  │             │  │          │  │
│  │ source =   │  │ source =   │  │ source = │  │
│  │ "../../    │  │ "../../    │  │ "../../  │  │
│  │  modules/  │  │  modules/  │  │  modules/│  │
│  │  vpc"      │  │  eks"      │  │  rds"    │  │
│  │             │  │             │  │          │  │
│  │ cidr =     │  │ cluster_   │  │ engine = │  │
│  │ "10.0.0/16"│  │ name =     │  │ "mysql"  │  │
│  └──────┬──────┘  │ "alli-prod"│  └────┬─────┘  │
│         │         └──────┬──────┘       │        │
│         │                │              │        │
│         ▼                ▼              ▼        │
│  Output: vpc_id    Output: endpoint  Output: url │
└────────────────────────────────────────────────────┘
         │                │              │
         ▼                ▼              ▼
     AWS VPC          AWS EKS        AWS RDS
```

### Input Variables 설계

```hcl
# modules/eks/variables.tf

# 필수 변수 (default 없음)
variable "cluster_name" {
  description = "EKS cluster name"
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.cluster_name))
    error_message = "Cluster name must be 3-40 chars, lowercase alphanumeric and hyphens."
  }
}

variable "vpc_id" {
  description = "VPC ID where EKS will be deployed"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for EKS"
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "At least 2 subnets required for EKS HA."
  }
}

# 선택 변수 (합리적 기본값 제공)
variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.29"
}

variable "node_groups" {
  description = "Map of EKS managed node group configurations"
  type = map(object({
    instance_types = list(string)
    min_size       = number
    max_size       = number
    desired_size   = number
    disk_size      = optional(number, 50)
    labels         = optional(map(string), {})
    taints = optional(list(object({
      key    = string
      value  = string
      effect = string
    })), [])
  }))
  default = {
    default = {
      instance_types = ["m5.large"]
      min_size       = 2
      max_size       = 10
      desired_size   = 3
    }
  }
}

variable "enable_cluster_autoscaler" {
  description = "Enable Cluster Autoscaler IRSA"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags for all resources"
  type        = map(string)
  default     = {}
}
```

### Output Values 설계

```hcl
# modules/eks/outputs.tf

output "cluster_id" {
  description = "EKS cluster ID"
  value       = aws_eks_cluster.main.id
}

output "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = aws_eks_cluster.main.endpoint
}

output "cluster_certificate_authority" {
  description = "Base64 encoded CA certificate"
  value       = aws_eks_cluster.main.certificate_authority[0].data
  sensitive   = true    # plan/apply 출력에서 마스킹
}

output "oidc_provider_arn" {
  description = "OIDC Provider ARN for IRSA"
  value       = aws_iam_openid_connect_provider.eks.arn
}

output "node_security_group_id" {
  description = "Security group ID for worker nodes"
  value       = aws_security_group.node.id
}
```

### 모듈 호출

```hcl
# environments/prod/main.tf

module "vpc" {
  source = "../../modules/vpc"

  name               = "alli-prod"
  cidr               = "10.0.0.0/16"
  availability_zones = ["ap-northeast-2a", "ap-northeast-2b", "ap-northeast-2c"]

  private_subnets = ["10.0.10.0/24", "10.0.11.0/24", "10.0.12.0/24"]
  public_subnets  = ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = false    # prod: AZ별 NAT GW

  tags = local.common_tags
}

module "eks" {
  source = "../../modules/eks"

  cluster_name       = "alli-prod"
  kubernetes_version = "1.29"
  vpc_id             = module.vpc.vpc_id           # VPC 모듈 output 참조
  subnet_ids         = module.vpc.private_subnet_ids

  node_groups = {
    general = {
      instance_types = ["m5.xlarge"]
      min_size       = 3
      max_size       = 20
      desired_size   = 5
    }
    gpu = {
      instance_types = ["g4dn.xlarge"]
      min_size       = 0
      max_size       = 10
      desired_size   = 2
      labels = {
        "workload-type" = "gpu"
      }
      taints = [{
        key    = "nvidia.com/gpu"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
  }

  tags = local.common_tags
}
```

### 모듈 버전 관리

```hcl
# 방법 1: Git 태그 (Private 모듈)
module "vpc" {
  source = "git::https://github.com/allganize/terraform-modules.git//vpc?ref=v1.2.0"
}

# 방법 2: Git 브랜치 (개발 중)
module "vpc" {
  source = "git::https://github.com/allganize/terraform-modules.git//vpc?ref=feature/ipv6"
}

# 방법 3: Terraform Registry (Public 모듈)
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"    # 5.x 최신
}

# 방법 4: Private Registry (Terraform Cloud/Enterprise)
module "vpc" {
  source  = "app.terraform.io/allganize/vpc/aws"
  version = "1.2.0"
}
```

**버전 관리 전략**:
```
Git 태그 기반 Semantic Versioning

v1.0.0 → v1.0.1  (patch: 버그 수정, 하위 호환)
v1.0.0 → v1.1.0  (minor: 새 변수 추가, 하위 호환)
v1.0.0 → v2.0.0  (major: 변수명 변경, Breaking Change)

Root Module에서:
  source = "...?ref=v1.2.0"   # 정확한 버전 고정 (prod)
  source = "...?ref=v1"       # 1.x 최신 (dev, 비추천)
  source = "...?ref=main"     # 최신 (절대 prod에서 사용 금지)
```

### Locals로 내부 복잡성 캡슐화

```hcl
# modules/eks/locals.tf
locals {
  cluster_name = var.cluster_name

  # 공통 태그 계산
  default_tags = merge(
    var.tags,
    {
      "kubernetes.io/cluster/${local.cluster_name}" = "owned"
      ManagedBy = "terraform"
      Module    = "eks"
    }
  )

  # Node group 기본값 병합
  node_groups = {
    for name, config in var.node_groups : name => merge(
      {
        disk_size = 50
        labels    = {}
        taints    = []
      },
      config
    )
  }
}
```

## 실전 예시

### 모듈 테스트 (Terratest)

```go
// modules/vpc/test/vpc_test.go
package test

import (
    "testing"
    "github.com/gruntwork-io/terratest/modules/terraform"
    "github.com/stretchr/testify/assert"
)

func TestVpcModule(t *testing.T) {
    terraformOptions := terraform.WithDefaultRetryableErrors(t, &terraform.Options{
        TerraformDir: "../examples/simple",
        Vars: map[string]interface{}{
            "name": "test-vpc",
            "cidr": "10.99.0.0/16",
        },
    })

    defer terraform.Destroy(t, terraformOptions)
    terraform.InitAndApply(t, terraformOptions)

    vpcId := terraform.Output(t, terraformOptions, "vpc_id")
    assert.NotEmpty(t, vpcId)
    assert.Contains(t, vpcId, "vpc-")
}
```

### 모듈 문서 자동 생성 (terraform-docs)

```bash
# terraform-docs 설치 후
terraform-docs markdown table modules/eks/ > modules/eks/README.md

# .pre-commit-config.yaml 에 추가하여 자동화
# - repo: https://github.com/terraform-docs/terraform-docs
#   hooks:
#     - id: terraform-docs-go
#       args: ["markdown", "table", "--output-file", "README.md"]
```

### 환경별 모듈 파라미터 차이

```hcl
# environments/dev/terraform.tfvars
cluster_name       = "alli-dev"
kubernetes_version = "1.29"
node_groups = {
  default = {
    instance_types = ["t3.large"]     # dev: 작은 인스턴스
    min_size       = 1
    max_size       = 3
    desired_size   = 2
  }
}

# environments/prod/terraform.tfvars
cluster_name       = "alli-prod"
kubernetes_version = "1.29"
node_groups = {
  general = {
    instance_types = ["m5.xlarge"]    # prod: 안정적인 인스턴스
    min_size       = 3
    max_size       = 20
    desired_size   = 5
  }
  gpu = {
    instance_types = ["g4dn.xlarge"]  # prod: GPU 노드
    min_size       = 0
    max_size       = 10
    desired_size   = 2
  }
}
```

## 면접 Q&A

### Q: Terraform 모듈을 왜 사용하고, 어떻게 설계하나요?

**30초 답변**:
모듈은 인프라 코드의 재사용 단위입니다. VPC, EKS 같은 인프라 패턴을 모듈로 만들면 dev/staging/prod에서 동일한 구조를 다른 파라미터로 배포할 수 있습니다. 좋은 모듈은 명확한 input/output 인터페이스와 합리적 기본값을 가집니다.

**2분 답변**:
모듈 설계의 핵심 원칙은 세 가지입니다.

첫째, 적절한 추상화 수준입니다. 너무 작으면(리소스 1개 = 모듈 1개) 의미 없고, 너무 크면(인프라 전체 = 모듈 1개) 재사용이 불가합니다. "하나의 논리적 서비스 단위"가 좋은 기준입니다. 예를 들어 VPC 모듈은 VPC + Subnets + NAT GW + Route Tables를 포함합니다.

둘째, 인터페이스 설계입니다. 필수 변수는 최소화하고, 선택 변수에 합리적 기본값을 제공합니다. `validation` 블록으로 잘못된 입력을 조기에 차단합니다. Output은 다른 모듈에서 필요한 ID, ARN, endpoint를 노출합니다.

셋째, 버전 관리입니다. Git 태그로 Semantic Versioning을 적용하고, Breaking Change가 있으면 major 버전을 올립니다. 프로덕션에서는 반드시 특정 버전을 고정합니다.

실무에서는 처음부터 모듈화하지 않고, 두 번째 환경을 만들 때 기존 코드를 모듈로 추출하는 "Extract Module" 패턴이 효과적입니다.

**💡 경험 연결**:
온프레미스에서 표준 서버 빌드 스크립트를 만들어 여러 프로젝트에서 재사용했던 것과 같은 개념입니다. Terraform 모듈은 "인프라 표준 빌드"의 코드화된 버전입니다.

**⚠️ 주의**:
모듈에 Provider를 직접 정의하면 안 됩니다. Provider는 Root Module에서만 정의하고, 모듈은 `required_providers`만 명시합니다. 모듈이 Provider를 내장하면 multi-region/multi-account 배포가 불가능해집니다.

---

### Q: 모듈 버전 관리는 어떻게 하나요?

**30초 답변**:
Git 태그 기반 Semantic Versioning을 사용합니다. `?ref=v1.2.0`으로 정확한 버전을 고정하고, Breaking Change가 있으면 major 버전을 올립니다. Terraform Registry를 사용하면 `version = "~> 1.2"`처럼 constraint를 지정할 수 있습니다.

**2분 답변**:
모듈 버전 관리는 안정적인 인프라 운영의 기반입니다. 우리 팀에서는 Git 모노레포에 모듈을 관리하고, 각 모듈 변경 시 태그를 생성합니다.

버전 전략은 다음과 같습니다. Patch(v1.0.x)는 버그 수정으로 자동 적용 가능, Minor(v1.x.0)는 새 변수 추가 등 하위 호환 변경, Major(vX.0.0)는 변수명 변경이나 리소스 구조 변경 등 Breaking Change입니다.

프로덕션에서는 정확한 버전(`ref=v1.2.0`)을 고정하고, 업그레이드는 별도 PR로 진행합니다. CHANGELOG.md를 유지하여 각 버전의 변경사항을 추적합니다. 모듈 업그레이드 시에는 dev 환경에서 먼저 테스트하고, Plan에서 의도치 않은 변경이 없는지 확인 후 prod에 적용합니다.

Private Terraform Registry를 운영하면 버전 검색과 문서 자동 생성, 다운로드 통계 등 추가적인 관리 기능을 활용할 수 있습니다.

**💡 경험 연결**:
소프트웨어 배포에서 버전 관리가 중요하듯, 인프라 모듈도 동일합니다. 온프레미스에서 Ansible Role의 버전을 고정하여 프로덕션 안정성을 유지했던 것과 같은 원칙입니다.

**⚠️ 주의**:
`ref=main`이나 버전 미지정은 프로덕션에서 절대 사용하면 안 됩니다. 누군가 모듈을 수정하면 다음 `terraform init`에서 예상치 못한 변경이 발생합니다.

---

### Q: Public 모듈(terraform-aws-modules)을 사용해도 되나요?

**30초 답변**:
사용해도 되지만 주의가 필요합니다. 검증된 Public 모듈은 커뮤니티 베스트 프랙티스가 반영되어 있어 시간을 절약합니다. 다만 프로덕션에서는 버전을 고정하고, 모듈 코드를 읽어서 무엇을 생성하는지 이해한 상태에서 사용해야 합니다.

**2분 답변**:
Public 모듈 사용은 트레이드오프입니다.

장점으로는 커뮤니티 검증, 빠른 구축, 보안 모범 사례 반영이 있습니다. `terraform-aws-modules/vpc/aws`는 수천 개 조직이 사용하며, 엣지 케이스가 잘 처리되어 있습니다.

단점으로는 불필요한 복잡성, 외부 의존성, 업그레이드 리스크가 있습니다. VPC 모듈이 200개 이상의 변수를 가지고 있어 학습 곡선이 높고, major 업그레이드 시 Breaking Change 대응이 필요합니다.

실무 전략으로는 "Wrap & Extend" 패턴을 추천합니다. Public 모듈을 자체 모듈로 감싸서 우리 조직에 필요한 변수만 노출하고, 내부 정책(태그, 네이밍 규칙)을 적용합니다. 이렇게 하면 Public 모듈의 이점을 누리면서 조직 표준을 유지할 수 있습니다.

**💡 경험 연결**:
오픈소스 도구를 도입할 때 "그대로 사용" vs "커스터마이즈" 판단은 항상 필요합니다. 핵심은 블랙박스로 쓰지 않고 내부를 이해한 상태로 사용하는 것입니다.

**⚠️ 주의**:
Public 모듈의 버전을 올릴 때는 반드시 CHANGELOG를 읽고, dev에서 테스트 후 적용합니다. Major 업그레이드는 State 변경이 수반될 수 있습니다.

## Allganize 맥락

- **EKS/AKS 모듈 표준화**: Allganize는 AWS(EKS)와 Azure(AKS)에 K8s를 운영하므로, 각 클라우드별 K8s 모듈을 표준화하면 일관된 클러스터 설정(노드 크기, 네트워크 정책, 보안 설정)을 보장할 수 있다.
- **AI 워크로드 특화 모듈**: GPU 노드 그룹, 대용량 스토리지, 모델 서빙 엔드포인트 등 LLM 서비스 특화 인프라를 모듈화하면 새로운 모델 배포 시 빠르게 인프라를 프로비저닝할 수 있다.
- **환경별 파라미터 관리**: dev(소규모, Spot), staging(중규모), prod(대규모, RI/On-demand)를 동일 모듈의 다른 파라미터로 운영하여 환경 간 일관성을 유지한다.
- **JD 연결 — "IaC 자동화"**: 모듈 설계 능력은 단순 Terraform 사용자와 IaC 설계자를 구분하는 핵심 역량이다.

---
**핵심 키워드**: `Module` `variables.tf` `outputs.tf` `source` `version` `Git 태그` `Semantic Versioning` `Terraform Registry` `validation` `locals` `Terratest`
