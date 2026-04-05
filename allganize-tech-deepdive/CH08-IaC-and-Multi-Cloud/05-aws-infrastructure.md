# AWS 인프라 설계

> **TL;DR**: AWS 인프라의 핵심은 VPC 네트워크 설계(Public/Private Subnet, NAT GW, IGW)와 EKS 클러스터 구성이다.
> IAM Role 기반 최소 권한 원칙과 IRSA(IAM Roles for Service Accounts)로 Pod 레벨 보안을 확보한다.
> RI, Savings Plans, Spot Instance를 조합하여 AI/LLM 워크로드의 비용을 최적화한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### VPC 네트워크 설계

```
┌─────────────────────────────── VPC (10.0.0.0/16) ───────────────────────────┐
│                                                                              │
│  ┌─── AZ-a ───────────┐  ┌─── AZ-b ───────────┐  ┌─── AZ-c ───────────┐  │
│  │                     │  │                     │  │                     │  │
│  │  Public Subnet      │  │  Public Subnet      │  │  Public Subnet      │  │
│  │  10.0.0.0/24        │  │  10.0.1.0/24        │  │  10.0.2.0/24        │  │
│  │  ┌───────────┐      │  │  ┌───────────┐      │  │  ┌───────────┐      │  │
│  │  │ NAT GW    │      │  │  │ NAT GW    │      │  │  │ NAT GW    │      │  │
│  │  │ ALB       │      │  │  │ ALB       │      │  │  │ ALB       │      │  │
│  │  └───────────┘      │  │  └───────────┘      │  │  └───────────┘      │  │
│  │         │           │  │         │           │  │         │           │  │
│  │  ───────┼───────    │  │  ───────┼───────    │  │  ───────┼───────    │  │
│  │         │           │  │         │           │  │         │           │  │
│  │  Private Subnet     │  │  Private Subnet     │  │  Private Subnet     │  │
│  │  10.0.10.0/24       │  │  10.0.11.0/24       │  │  10.0.12.0/24       │  │
│  │  ┌───────────┐      │  │  ┌───────────┐      │  │  ┌───────────┐      │  │
│  │  │ EKS Nodes │      │  │  │ EKS Nodes │      │  │  │ EKS Nodes │      │  │
│  │  │ App Pods  │      │  │  │ App Pods  │      │  │  │ App Pods  │      │  │
│  │  └───────────┘      │  │  └───────────┘      │  │  └───────────┘      │  │
│  │         │           │  │         │           │  │         │           │  │
│  │  ───────┼───────    │  │  ───────┼───────    │  │  ───────┼───────    │  │
│  │         │           │  │         │           │  │         │           │  │
│  │  DB Subnet          │  │  DB Subnet          │  │  DB Subnet          │  │
│  │  10.0.20.0/24       │  │  10.0.21.0/24       │  │  10.0.22.0/24       │  │
│  │  ┌───────────┐      │  │  ┌───────────┐      │  │  ┌───────────┐      │  │
│  │  │ RDS       │      │  │  │ RDS       │      │  │  │ RDS       │      │  │
│  │  │ ElastiCache│     │  │  │ (Standby) │      │  │  │ (Replica) │      │  │
│  │  └───────────┘      │  │  └───────────┘      │  │  └───────────┘      │  │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘  │
│                                                                              │
│  ┌──────────────┐                                                           │
│  │ Internet GW  │ ◀── Public Subnet 트래픽 → 인터넷                         │
│  └──────────────┘                                                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

**서브넷 역할 분리**:
- **Public Subnet**: ALB(Application Load Balancer), NAT Gateway, Bastion Host 배치. Internet Gateway를 통해 인터넷 직접 접근
- **Private Subnet**: EKS Worker Nodes, Application Pods 배치. NAT Gateway를 통해서만 외부 접근(아웃바운드)
- **DB Subnet**: RDS, ElastiCache 등 데이터 저장소. 인터넷 접근 완전 차단, Private Subnet에서만 접근 가능

### VPC Terraform 코드

```hcl
# VPC
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "alli-prod-vpc"
    "kubernetes.io/cluster/alli-prod" = "shared"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "alli-prod-igw" }
}

# NAT Gateway (AZ별)
resource "aws_eip" "nat" {
  count  = 3
  domain = "vpc"
  tags   = { Name = "alli-prod-nat-eip-${count.index}" }
}

resource "aws_nat_gateway" "main" {
  count         = 3
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = { Name = "alli-prod-nat-${count.index}" }

  depends_on = [aws_internet_gateway.main]
}

# Public Subnets
resource "aws_subnet" "public" {
  count                   = 3
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet("10.0.0.0/16", 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "alli-prod-public-${count.index}"
    "kubernetes.io/role/elb" = "1"
  }
}

# Private Subnets (EKS Nodes)
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

# Route Tables
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "alli-prod-public-rt" }
}

resource "aws_route_table" "private" {
  count  = 3
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = { Name = "alli-prod-private-rt-${count.index}" }
}
```

### EKS 클러스터 구성

```hcl
# EKS Cluster
resource "aws_eks_cluster" "main" {
  name     = "alli-prod"
  version  = "1.29"
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    endpoint_public_access  = true    # kubectl 접근 (IP 제한 권장)
    public_access_cidrs     = ["203.0.113.0/24"]  # 오피스 IP만
    security_group_ids      = [aws_security_group.cluster.id]
  }

  enabled_cluster_log_types = [
    "api", "audit", "authenticator", "controllerManager", "scheduler"
  ]

  encryption_config {
    provider {
      key_arn = aws_kms_key.eks.arn
    }
    resources = ["secrets"]   # etcd 시크릿 암호화
  }

  depends_on = [
    aws_iam_role_policy_attachment.cluster_policy,
    aws_iam_role_policy_attachment.cluster_vpc_controller,
  ]
}

# Managed Node Groups
resource "aws_eks_node_group" "general" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "general"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = aws_subnet.private[*].id

  instance_types = ["m5.xlarge"]   # 4 vCPU, 16 GB

  scaling_config {
    desired_size = 5
    min_size     = 3
    max_size     = 20
  }

  update_config {
    max_unavailable_percentage = 25   # Rolling Update
  }

  labels = {
    workload = "general"
  }

  tags = { Name = "alli-prod-general" }
}

resource "aws_eks_node_group" "gpu" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "gpu-inference"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = aws_subnet.private[*].id

  instance_types = ["g4dn.xlarge"]   # 1 GPU, 4 vCPU, 16 GB
  ami_type       = "AL2_x86_64_GPU"

  scaling_config {
    desired_size = 2
    min_size     = 0
    max_size     = 10
  }

  taint {
    key    = "nvidia.com/gpu"
    value  = "true"
    effect = "NO_SCHEDULE"
  }

  labels = {
    workload     = "gpu"
    "nvidia.com/gpu" = "true"
  }
}
```

### IAM & IRSA (IAM Roles for Service Accounts)

```
┌─────────────────────────────────────────────────┐
│                IRSA 동작 원리                     │
│                                                  │
│  K8s ServiceAccount                              │
│  (annotation: arn:aws:iam::ROLE)                 │
│       │                                          │
│       ▼                                          │
│  Pod에 OIDC Token 주입                            │
│  (projected volume)                              │
│       │                                          │
│       ▼                                          │
│  AWS STS AssumeRoleWithWebIdentity               │
│       │                                          │
│       ▼                                          │
│  임시 AWS 자격 증명 발급                           │
│  (Pod별 독립적인 IAM Role)                        │
│                                                  │
│  장점: Node Role이 아닌 Pod별 최소 권한            │
└─────────────────────────────────────────────────┘
```

```hcl
# OIDC Provider
data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# S3 접근용 IRSA
resource "aws_iam_role" "s3_reader" {
  name = "alli-prod-s3-reader"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.eks.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${replace(aws_eks_cluster.main.identity[0].oidc[0].issuer, "https://", "")}:sub" =
            "system:serviceaccount:alli-app:model-loader"
          "${replace(aws_eks_cluster.main.identity[0].oidc[0].issuer, "https://", "")}:aud" =
            "sts.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "s3_reader" {
  role = aws_iam_role.s3_reader.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket"
      ]
      Resource = [
        "arn:aws:s3:::alli-models",
        "arn:aws:s3:::alli-models/*"
      ]
    }]
  })
}

# K8s ServiceAccount
resource "kubernetes_service_account" "model_loader" {
  metadata {
    name      = "model-loader"
    namespace = "alli-app"
    annotations = {
      "eks.amazonaws.com/role-arn" = aws_iam_role.s3_reader.arn
    }
  }
}
```

### 비용 최적화

```
┌─────────────────────────────────────────────────────────────┐
│                    AWS 비용 최적화 전략                       │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ On-Demand   │  │ Reserved (RI)│  │ Spot Instance    │   │
│  │             │  │ / Savings    │  │                  │   │
│  │ 기본 요금    │  │ Plans        │  │ 최대 90% 할인    │   │
│  │ 유연성 최대  │  │ 30-72% 할인  │  │ 중단 가능성 있음 │   │
│  │             │  │ 1년/3년 약정 │  │                  │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
│                                                             │
│  Allganize 적용 예시:                                       │
│                                                             │
│  ┌─ EKS Node Group 전략 ──────────────────────────────┐    │
│  │                                                     │    │
│  │  general (항상 필요)  : RI/Savings Plans (72% 할인)  │    │
│  │  peak (피크 대응)     : On-Demand (유연성)           │    │
│  │  batch (배치 처리)    : Spot Instance (비용 절감)     │    │
│  │  gpu (추론 서빙)      : RI + On-Demand 혼합          │    │
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

```hcl
# Spot Instance Node Group (배치/비핵심 워크로드)
resource "aws_eks_node_group" "spot" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "spot-batch"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = aws_subnet.private[*].id
  capacity_type   = "SPOT"

  instance_types = [
    "m5.xlarge",
    "m5a.xlarge",
    "m5d.xlarge",
    "m4.xlarge"      # 다양한 타입으로 Spot 가용성 확보
  ]

  scaling_config {
    desired_size = 3
    min_size     = 0
    max_size     = 20
  }

  taint {
    key    = "spot"
    value  = "true"
    effect = "NO_SCHEDULE"
  }

  labels = {
    capacity = "spot"
  }
}

# Karpenter로 동적 노드 프로비저닝 (Spot + On-Demand 혼합)
resource "helm_release" "karpenter" {
  namespace  = "karpenter"
  name       = "karpenter"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = "v0.33.0"

  set {
    name  = "settings.clusterName"
    value = aws_eks_cluster.main.name
  }

  set {
    name  = "settings.clusterEndpoint"
    value = aws_eks_cluster.main.endpoint
  }
}
```

**추가 비용 최적화 방법**:

```
1. NAT Gateway 비용 절감
   - dev 환경: Single NAT GW ($32/월 → AZ별 $96/월 절약)
   - VPC Endpoint로 AWS 서비스 트래픽을 NAT GW 우회
     → S3, ECR, CloudWatch 등

2. EBS 스토리지 최적화
   - gp3 사용 (gp2 대비 20% 저렴, 성능 설정 가능)
   - 미사용 EBS 볼륨 정기 정리

3. 데이터 전송 비용
   - CloudFront로 S3 직접 전송 감소
   - VPC Endpoint로 내부 트래픽 유지
   - 같은 AZ 내 통신 권장 (Cross-AZ 비용 회피)
```

## 실전 예시

### VPC Endpoint 설정

```hcl
# S3 Gateway Endpoint (무료)
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.ap-northeast-2.s3"

  route_table_ids = aws_route_table.private[*].id

  tags = { Name = "alli-prod-s3-endpoint" }
}

# ECR Interface Endpoint (프라이빗 서브넷에서 이미지 Pull)
resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.ap-northeast-2.ecr.api"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoint.id]

  tags = { Name = "alli-prod-ecr-api-endpoint" }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.ap-northeast-2.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoint.id]

  tags = { Name = "alli-prod-ecr-dkr-endpoint" }
}
```

### EKS Add-ons

```hcl
# CoreDNS
resource "aws_eks_addon" "coredns" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "coredns"
  resolve_conflicts_on_update = "OVERWRITE"
}

# kube-proxy
resource "aws_eks_addon" "kube_proxy" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "kube-proxy"
  resolve_conflicts_on_update = "OVERWRITE"
}

# VPC CNI (Pod 네트워킹)
resource "aws_eks_addon" "vpc_cni" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "vpc-cni"
  service_account_role_arn = aws_iam_role.vpc_cni.arn
  resolve_conflicts_on_update = "OVERWRITE"

  configuration_values = jsonencode({
    env = {
      ENABLE_PREFIX_DELEGATION = "true"   # Pod 밀도 향상
      WARM_PREFIX_TARGET       = "1"
    }
  })
}

# EBS CSI Driver
resource "aws_eks_addon" "ebs_csi" {
  cluster_name             = aws_eks_cluster.main.name
  addon_name               = "aws-ebs-csi-driver"
  service_account_role_arn = aws_iam_role.ebs_csi.arn
}
```

## 면접 Q&A

### Q: VPC를 어떻게 설계하나요?

**30초 답변**:
3-tier 구조로 Public(ALB, NAT GW), Private(EKS Nodes), DB(RDS) 서브넷을 분리하고, 3개 AZ에 걸쳐 고가용성을 확보합니다. Private 서브넷은 NAT Gateway를 통해서만 외부에 접근하고, DB 서브넷은 인터넷 접근이 완전히 차단됩니다.

**2분 답변**:
VPC 설계의 핵심은 보안과 가용성의 균형입니다.

CIDR 설계부터 시작합니다. `/16` VPC로 충분한 IP 공간을 확보하고, 서브넷은 `/24`로 분할합니다. 향후 VPC Peering이나 Transit Gateway 연결을 고려하여 다른 VPC/온프레미스와 CIDR이 겹치지 않도록 IP 계획을 수립합니다.

서브넷 역할을 명확히 분리합니다. Public 서브넷에는 인터넷과 직접 통신하는 ALB와 NAT Gateway만 배치합니다. EKS Worker Node는 반드시 Private 서브넷에 배치하여 직접 인터넷 노출을 방지합니다. 데이터베이스는 별도 서브넷 그룹으로 격리합니다.

NAT Gateway는 프로덕션에서 AZ별로 배치하여 단일 장애점을 제거합니다. 다만 개발 환경에서는 비용 절감을 위해 Single NAT Gateway를 사용합니다.

EKS와의 연동을 위해 서브넷에 `kubernetes.io/role/internal-elb`(Private), `kubernetes.io/role/elb`(Public) 태그를 부착합니다.

**💡 경험 연결**:
온프레미스에서 DMZ, 내부망, DB망을 VLAN으로 분리했던 것과 동일한 보안 원칙입니다. AWS VPC의 Public/Private/DB 서브넷이 각각 DMZ/내부망/DB망에 대응합니다.

**⚠️ 주의**:
CIDR 설계는 나중에 변경이 매우 어렵습니다. 처음부터 충분히 큰 범위를 할당하고, 향후 네트워크 확장 계획을 반영해야 합니다.

---

### Q: IRSA(IAM Roles for Service Accounts)는 무엇이고 왜 중요한가요?

**30초 답변**:
IRSA는 K8s Pod에 AWS IAM Role을 직접 부여하는 메커니즘입니다. 기존에는 Node의 IAM Role을 모든 Pod이 공유했지만, IRSA를 사용하면 Pod별로 독립적인 최소 권한을 할당할 수 있습니다. OIDC 기반으로 동작하며, EKS의 보안 모범 사례입니다.

**2분 답변**:
IRSA 이전에는 EC2 Instance Profile(Node Role)에 필요한 모든 AWS 권한을 부여했습니다. 이는 해당 Node의 모든 Pod이 동일한 권한을 가진다는 의미로, S3 접근이 필요한 Pod 하나 때문에 Node 전체에 S3 권한을 부여해야 했습니다.

IRSA는 K8s ServiceAccount에 IAM Role ARN을 annotation으로 연결합니다. Pod가 생성되면 EKS가 OIDC Token을 projected volume으로 주입하고, AWS SDK가 이 토큰으로 STS AssumeRoleWithWebIdentity를 호출하여 임시 자격 증명을 받습니다.

이를 통해 "model-loader Pod는 S3 읽기만", "log-shipper Pod는 CloudWatch 쓰기만" 같은 세밀한 권한 분리가 가능합니다. AI 서비스에서는 모델 파일 접근, 추론 결과 저장, 메트릭 전송 등 Pod마다 필요한 AWS 권한이 다르므로 IRSA가 필수적입니다.

**💡 경험 연결**:
온프레미스에서 서버별로 서비스 계정을 분리하고 최소 권한을 부여했던 원칙과 동일합니다. IRSA는 이를 컨테이너/Pod 레벨로 확장한 것입니다.

**⚠️ 주의**:
IRSA Condition에서 ServiceAccount의 namespace와 name을 정확히 지정해야 합니다. 와일드카드(`*`)를 사용하면 다른 namespace의 Pod이 해당 Role을 사용할 수 있어 보안 위험이 있습니다.

---

### Q: AWS 비용 최적화는 어떻게 하나요?

**30초 답변**:
세 가지 축으로 접근합니다. 첫째, 컴퓨팅은 RI/Savings Plans(상시 워크로드)와 Spot(배치 워크로드)을 혼합합니다. 둘째, 네트워크는 VPC Endpoint로 NAT Gateway 트래픽을 줄입니다. 셋째, 스토리지는 gp3 EBS와 S3 Lifecycle Policy를 적용합니다.

**2분 답변**:
비용 최적화는 가시성 확보부터 시작합니다. AWS Cost Explorer와 태그 기반 비용 할당으로 서비스/팀별 비용을 추적합니다.

컴퓨팅 최적화에서는 Karpenter를 사용하여 워크로드에 맞는 인스턴스를 동적으로 선택합니다. 기본 용량은 Compute Savings Plans(최대 66% 할인)으로 커버하고, 변동 트래픽은 On-Demand, 배치 처리는 Spot Instance(최대 90% 할인)를 사용합니다. GPU 인스턴스는 비용이 높으므로 RI를 적극 활용합니다.

네트워크 비용은 흔히 간과되지만 상당합니다. S3, ECR, CloudWatch용 VPC Endpoint를 설정하면 NAT Gateway 데이터 처리 비용($0.045/GB)을 절약합니다. 특히 ECR에서 컨테이너 이미지를 자주 Pull하는 EKS 환경에서 효과가 큽니다.

스토리지는 gp3(gp2 대비 20% 저렴)를 기본으로 사용하고, S3는 Intelligent-Tiering으로 자동 계층화합니다. 미사용 EBS 볼륨과 오래된 스냅샷을 정기적으로 정리합니다.

**💡 경험 연결**:
온프레미스에서 서버 자원 사용률을 모니터링하고 과잉 프로비저닝을 줄였던 경험이 클라우드 비용 최적화와 직결됩니다. Right-sizing의 원칙은 동일하고, 클라우드에서는 RI/Spot 같은 추가 레버가 있습니다.

**⚠️ 주의**:
Spot Instance는 2분 전 경고로 중단될 수 있으므로 Stateless 워크로드에만 사용해야 합니다. Karpenter의 consolidation 기능으로 Spot 중단 시 자동 대체를 설정합니다.

## Allganize 맥락

- **EKS 기반 Alli 서비스**: Allganize의 AI 서비스 "Alli"는 AWS EKS 위에서 운영된다. VPC 설계, Node Group 구성, IRSA 설정이 서비스 안정성과 보안의 기반이다.
- **GPU 워크로드**: LLM 추론을 위한 GPU 인스턴스(g4dn, p4d 등)를 별도 Node Group으로 관리하고, Taint/Toleration으로 GPU Pod만 스케줄링한다.
- **비용 민감 스타트업**: AI 스타트업은 GPU 비용이 크므로, RI/Spot 혼합 전략과 Karpenter 기반 동적 스케일링이 비용 효율성의 핵심이다.
- **JD 연결 — "AWS 인프라 관리 경험"**: VPC 설계부터 EKS 운영, 비용 최적화까지 AWS 인프라 전반을 Terraform으로 관리할 수 있음을 보여주는 것이 핵심이다.
- **온프레미스 → 클라우드 전환 스토리**: DMZ/내부망/DB망 설계 경험은 VPC 서브넷 설계에, 서버별 계정 분리 경험은 IRSA에 자연스럽게 연결된다.

---
**핵심 키워드**: `VPC` `Subnet` `NAT Gateway` `Internet Gateway` `EKS` `Managed Node Group` `IRSA` `OIDC` `Spot Instance` `Savings Plans` `VPC Endpoint` `Karpenter` `gp3`
