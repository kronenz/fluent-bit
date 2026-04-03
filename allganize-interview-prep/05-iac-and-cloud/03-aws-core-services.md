# 03. AWS 핵심 서비스 (AWS Core Services)

> **TL;DR**
> - VPC 네트워크 설계 -> EKS 컴퓨팅 -> S3/RDS 데이터 -> IAM 보안 순서로 이해하면 AWS 아키텍처의 뼈대가 잡힌다
> - IAM의 최소 권한 원칙(Least Privilege)과 IRSA는 면접에서 반드시 나오는 주제다
> - 온프레미스에서 네트워크/스토리지/보안을 직접 구축한 경험은 각 서비스의 동작 원리를 깊이 이해하는 강점이 된다

---

## 1. VPC (Virtual Private Cloud)

### 1-1. 핵심 구성 요소

```
                     [Internet]
                         |
                    [Internet Gateway]
                         |
              ┌──────────┴──────────┐
              |    Public Subnet     |
              |   (NAT Gateway)      |
              |   (Bastion Host)     |
              |   (ALB)              |
              └──────────┬──────────┘
                         |
              ┌──────────┴──────────┐
              |   Private Subnet     |
              |   (EKS Nodes)        |
              |   (Application)      |
              └──────────┬──────────┘
                         |
              ┌──────────┴──────────┐
              |  DB/Isolated Subnet  |
              |   (RDS Aurora)       |
              |   (ElastiCache)      |
              └─────────────────────┘
```

### 1-2. 서브넷 설계 (Subnet Design)

```hcl
# VPC 생성
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "allganize-prod-vpc" }
}

# 퍼블릭 서브넷 (Public Subnet)
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet("10.0.0.0/16", 8, count.index)       # 10.0.0.0/24, 10.0.1.0/24
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                     = "public-${count.index + 1}"
    "kubernetes.io/role/elb" = "1"  # ALB가 이 서브넷을 사용
  }
}

# 프라이빗 서브넷 (Private Subnet)
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet("10.0.0.0/16", 8, count.index + 10)  # 10.0.10.0/24, 10.0.11.0/24
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name                              = "private-${count.index + 1}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}
```

### 1-3. NAT Gateway와 Internet Gateway

```hcl
# Internet Gateway: 퍼블릭 서브넷의 인터넷 출입구
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

# NAT Gateway: 프라이빗 서브넷 -> 인터넷 (아웃바운드만)
resource "aws_eip" "nat" {
  domain = "vpc"
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id  # 퍼블릭 서브넷에 배치
}

# 프라이빗 서브넷 라우트 테이블
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
}
```

### 1-4. VPC 피어링 (VPC Peering)

서로 다른 VPC 간 **프라이빗 통신**을 가능하게 한다.

```hcl
resource "aws_vpc_peering_connection" "prod_to_shared" {
  vpc_id      = aws_vpc.prod.id
  peer_vpc_id = aws_vpc.shared_services.id
  auto_accept = true  # 같은 계정일 때

  tags = { Name = "prod-to-shared" }
}

# 양쪽 VPC의 라우트 테이블에 상대방 CIDR 추가 필요
resource "aws_route" "prod_to_shared" {
  route_table_id            = aws_route_table.prod_private.id
  destination_cidr_block    = "10.1.0.0/16"  # shared VPC CIDR
  vpc_peering_connection_id = aws_vpc_peering_connection.prod_to_shared.id
}
```

> **폐쇄망 경험 연결:** 온프레미스에서 VLAN 간 라우팅을 직접 구성해본 경험이 있다면, VPC 서브넷 설계와 라우트 테이블 개념이 1:1로 대응된다.

---

## 2. EC2와 EKS

### 2-1. EC2 핵심 개념

| 개념 | 설명 |
|------|------|
| AMI (Amazon Machine Image) | OS + 소프트웨어가 포함된 이미지 |
| Instance Type | 컴퓨팅 사양 (예: t3.medium = 2vCPU, 4GB) |
| Security Group | 인스턴스 레벨 방화벽 (Stateful) |
| Key Pair | SSH 접속용 키 쌍 |
| User Data | 인스턴스 최초 부팅 시 실행 스크립트 |

### 2-2. EKS (Elastic Kubernetes Service)

```hcl
# EKS 클러스터 생성
resource "aws_eks_cluster" "main" {
  name     = "allganize-prod"
  version  = "1.29"
  role_arn = aws_iam_role.eks_cluster.arn

  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    endpoint_public_access  = false  # 프라이빗 클러스터
  }

  enabled_cluster_log_types = [
    "api", "audit", "authenticator",
    "controllerManager", "scheduler"
  ]
}

# Managed Node Group
resource "aws_eks_node_group" "workers" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "workers"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = aws_subnet.private[*].id

  capacity_type  = "ON_DEMAND"
  instance_types = ["t3.xlarge"]

  scaling_config {
    desired_size = 3
    max_size     = 10
    min_size     = 2
  }

  update_config {
    max_unavailable = 1  # 롤링 업데이트 시 동시 중단 노드 수
  }
}
```

### 2-3. Managed Node Group vs Fargate

| 구분 | Managed Node Group | Fargate |
|------|-------------------|---------|
| 관리 수준 | EC2 노드 관리 필요 | 완전 서버리스 |
| 비용 모델 | EC2 인스턴스 비용 | Pod별 vCPU/메모리 과금 |
| DaemonSet | 지원 | 미지원 |
| GPU | 지원 | 미지원 |
| 사용 사례 | 범용 워크로드 | 배치, 간헐적 작업 |

---

## 3. S3와 RDS (Aurora)

### 3-1. S3 (Simple Storage Service)

```hcl
resource "aws_s3_bucket" "data" {
  bucket = "allganize-prod-data"
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

# 수명주기 정책: 90일 후 Glacier로 이동
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "archive-old-data"
    status = "Enabled"

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}
```

### 3-2. RDS Aurora

```hcl
resource "aws_rds_cluster" "main" {
  cluster_identifier     = "allganize-prod"
  engine                 = "aurora-postgresql"
  engine_version         = "15.4"
  database_name          = "allganize"
  master_username        = "admin"
  master_password        = var.db_password  # Secrets Manager 연동 권장
  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = aws_db_subnet_group.main.name

  backup_retention_period = 7
  preferred_backup_window = "03:00-04:00"
  storage_encrypted       = true
  deletion_protection     = true

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 16
  }
}

resource "aws_rds_cluster_instance" "main" {
  count              = 2  # Writer + Reader
  identifier         = "allganize-prod-${count.index}"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
}
```

---

## 4. IAM (Identity and Access Management)

### 4-1. IAM 핵심 구조

```
IAM User / Role / Group
       |
   IAM Policy (JSON)
       |
   ┌───┴───┐
   | Effect | : Allow / Deny
   | Action | : s3:GetObject, ec2:RunInstances
   | Resource| : arn:aws:s3:::my-bucket/*
   | Condition| : IP, MFA, 시간 등
   └───────┘
```

### 4-2. IAM 정책 예시

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3ReadOnly",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::allganize-prod-data",
        "arn:aws:s3:::allganize-prod-data/*"
      ],
      "Condition": {
        "IpAddress": {
          "aws:SourceIp": "10.0.0.0/16"
        }
      }
    }
  ]
}
```

### 4-3. IRSA (IAM Roles for Service Accounts)

쿠버네티스 Pod에 **AWS IAM 역할을 직접 부여**하는 방식이다. 노드 레벨 권한이 아닌 **Pod 레벨 최소 권한**을 구현한다.

```hcl
# OIDC Provider 설정 (EKS 클러스터당 1개)
data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# Pod용 IAM Role
resource "aws_iam_role" "app_s3_reader" {
  name = "allganize-app-s3-reader"

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
          "${replace(aws_eks_cluster.main.identity[0].oidc[0].issuer, "https://", "")}:sub" = "system:serviceaccount:allganize:app-sa"
        }
      }
    }]
  })
}

# 쿠버네티스 ServiceAccount에 IAM Role 연결
resource "kubernetes_service_account" "app" {
  metadata {
    name      = "app-sa"
    namespace = "allganize"
    annotations = {
      "eks.amazonaws.com/role-arn" = aws_iam_role.app_s3_reader.arn
    }
  }
}
```

---

## 5. ALB/NLB, CloudWatch, CloudTrail

### 5-1. ALB (Application Load Balancer) vs NLB (Network Load Balancer)

| 구분 | ALB (L7) | NLB (L4) |
|------|----------|----------|
| 프로토콜 | HTTP/HTTPS/gRPC | TCP/UDP/TLS |
| 라우팅 | 경로, 호스트, 헤더 기반 | IP, 포트 기반 |
| 성능 | 밀리초 지연 | 마이크로초 지연 |
| 고정 IP | 미지원 | 지원 (EIP 연결 가능) |
| EKS 연동 | AWS Load Balancer Controller | AWS Load Balancer Controller |
| 사용 사례 | 웹 애플리케이션, API | 고성능 TCP, gRPC |

```hcl
# EKS에서 ALB Ingress 사용 (AWS Load Balancer Controller)
resource "helm_release" "aws_lb_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"

  set {
    name  = "clusterName"
    value = aws_eks_cluster.main.name
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.lb_controller.arn
  }
}
```

### 5-2. CloudWatch

```hcl
# 사용자 정의 경보 (Custom Alarm)
resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "allganize-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300  # 5분
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "CPU 사용률이 80%를 3회 연속 초과"

  alarm_actions = [aws_sns_topic.alerts.arn]

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.main.name
  }
}
```

### 5-3. CloudTrail

모든 AWS API 호출을 **감사 로그(Audit Log)**로 기록한다.

```hcl
resource "aws_cloudtrail" "main" {
  name                       = "allganize-audit-trail"
  s3_bucket_name             = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true
  is_multi_region_trail      = true
  enable_log_file_validation = true  # 로그 위변조 방지

  event_selector {
    read_write_type           = "All"
    include_management_events = true

    data_resource {
      type   = "AWS::S3::Object"
      values = ["arn:aws:s3:::allganize-prod-data/"]
    }
  }
}
```

> **폐쇄망 경험 연결:** 온프레미스에서 syslog, auditd 등으로 감사 로그를 직접 구축한 경험이 있다면, CloudTrail의 필요성과 설계 원칙을 깊이 설명할 수 있다.

---

## 면접 Q&A

### Q1. "VPC를 설계할 때 가장 중요한 고려 사항은?"

> **이렇게 대답한다:**
> 세 가지를 먼저 고려합니다. 첫째, **CIDR 대역 설계** - 향후 VPC 피어링이나 Direct Connect를 고려해 다른 네트워크와 겹치지 않도록 합니다. 둘째, **서브넷 계층 분리** - Public(LB), Private(App), Isolated(DB) 3계층으로 나누어 보안 경계를 명확히 합니다. 셋째, **AZ 분산** - 최소 2개 AZ에 서브넷을 배치하여 고가용성을 확보합니다. 온프레미스에서 물리 네트워크 세그먼트를 직접 설계한 경험이 이런 논리적 설계에 큰 도움이 됩니다.

### Q2. "IRSA가 왜 필요한가요? 노드에 IAM Role을 붙이면 안 되나요?"

> **이렇게 대답한다:**
> 노드 레벨 IAM Role을 사용하면, 해당 노드의 **모든 Pod가 동일한 권한**을 갖게 됩니다. S3 읽기만 필요한 Pod도 RDS 접근 권한을 갖게 되는 것입니다. IRSA는 **ServiceAccount 단위로 IAM Role을 할당**하여 최소 권한 원칙(Least Privilege)을 Pod 수준에서 구현합니다. OIDC 기반으로 동작하며, Pod의 Projected Service Account Token을 STS에서 검증하는 방식입니다.

### Q3. "Aurora와 일반 RDS의 차이는?"

> **이렇게 대답한다:**
> Aurora는 AWS가 자체 개발한 **클라우드 네이티브 스토리지 엔진** 위에 MySQL/PostgreSQL 호환 레이어를 올린 것입니다. 핵심 차이는 스토리지입니다. 일반 RDS는 EBS 기반으로 단일 AZ 스토리지인 반면, Aurora는 **3개 AZ에 6개 사본**을 자동 복제하여 내구성과 성능이 뛰어납니다. Aurora Serverless v2를 사용하면 부하에 따라 자동 스케일링도 가능합니다.

### Q4. "ALB와 NLB를 각각 언제 사용하나요?"

> **이렇게 대답한다:**
> **ALB**는 HTTP/HTTPS 트래픽에 사용합니다. URL 경로, 호스트 헤더 기반 라우팅이 필요하거나 WAF를 연동할 때 적합합니다. **NLB**는 TCP/UDP 레벨에서 동작하며, 극도로 낮은 지연시간이 필요하거나 고정 IP가 필요할 때 사용합니다. EKS 환경에서는 일반적으로 HTTP API는 ALB Ingress, gRPC나 TCP 서비스는 NLB를 사용합니다.

### Q5. "CloudTrail과 CloudWatch의 차이는?"

> **이렇게 대답한다:**
> **CloudTrail**은 "누가(Who) 언제(When) 무엇을(What) 했는가"에 대한 **API 호출 감사 로그**입니다. 보안 및 컴플라이언스 목적입니다. **CloudWatch**는 "시스템이 지금 어떤 상태인가"에 대한 **메트릭, 로그, 경보** 서비스입니다. 운영 모니터링 목적입니다. 온프레미스로 비유하면, CloudTrail은 auditd/보안 로그, CloudWatch는 Prometheus + Grafana + syslog에 해당합니다.

---

**핵심 키워드 5선:**
`VPC 3계층 설계 (3-Tier VPC Design)`, `EKS Managed Node Group`, `IRSA (IAM Roles for Service Accounts)`, `Aurora Serverless`, `CloudTrail 감사 로그 (Audit Log)`
