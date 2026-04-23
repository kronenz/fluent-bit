# 02. 멀티클라우드 전략 (Multi-Cloud Strategy)

> **TL;DR**
> - 멀티클라우드(Multi-Cloud)는 벤더 종속 회피, 규제 대응, 가용성 극대화를 위한 전략이다
> - 추상화 계층(Abstraction Layer)과 서비스 메시(Service Mesh)가 멀티클라우드의 핵심 설계 패턴이다
> - 폐쇄망/온프레미스 운영 경험은 하이브리드 클라우드(Hybrid Cloud) 설계에서 직접적인 강점이 된다

---

## 1. AWS vs Azure 서비스 매핑 비교표

### 1-1. 컴퓨팅 (Compute)

| 카테고리 | AWS | Azure | 비고 |
|---------|-----|-------|------|
| 가상 서버 | EC2 | Virtual Machines | 기본 IaaS |
| 컨테이너 오케스트레이션 | EKS | AKS | 관리형 쿠버네티스 |
| 서버리스 컨테이너 | Fargate | Container Instances | Pod 단위 실행 |
| 서버리스 함수 | Lambda | Azure Functions | 이벤트 기반 |
| 배치 처리 | AWS Batch | Azure Batch | 대규모 병렬 처리 |

### 1-2. 네트워킹 (Networking)

| 카테고리 | AWS | Azure | 비고 |
|---------|-----|-------|------|
| 가상 네트워크 | VPC | VNET | 논리적 격리 |
| 로드 밸런서 (L7) | ALB | Application Gateway | HTTP/HTTPS |
| 로드 밸런서 (L4) | NLB | Azure Load Balancer | TCP/UDP |
| DNS | Route 53 | Azure DNS | 도메인 관리 |
| CDN | CloudFront | Azure CDN / Front Door | 글로벌 캐싱 |
| 전용 연결 | Direct Connect | ExpressRoute | 온프레미스 연결 |

### 1-3. 스토리지 & 데이터베이스 (Storage & Database)

| 카테고리 | AWS | Azure | 비고 |
|---------|-----|-------|------|
| 오브젝트 스토리지 | S3 | Blob Storage | 비정형 데이터 |
| 블록 스토리지 | EBS | Managed Disks | VM 디스크 |
| 파일 스토리지 | EFS | Azure Files | NFS/SMB |
| 관계형 DB | RDS / Aurora | Azure SQL / PostgreSQL | 관리형 RDBMS |
| NoSQL (문서) | DynamoDB | Cosmos DB | 글로벌 분산 |
| 캐시 | ElastiCache | Azure Cache for Redis | 인메모리 |

### 1-4. 보안 & ID (Security & Identity)

| 카테고리 | AWS | Azure | 비고 |
|---------|-----|-------|------|
| ID 관리 | IAM | Azure AD (Entra ID) | 인증/인가 |
| 비밀 관리 | Secrets Manager | Key Vault | 자격 증명 |
| 인증서 | ACM | App Service Certificates | TLS |
| 감사 로그 | CloudTrail | Activity Log | API 호출 기록 |

### 1-5. 모니터링 (Monitoring)

| 카테고리 | AWS | Azure | 비고 |
|---------|-----|-------|------|
| 메트릭/로그 | CloudWatch | Azure Monitor | 통합 모니터링 |
| APM | X-Ray | Application Insights | 트레이싱 |
| 로그 분석 | CloudWatch Logs Insights | Log Analytics | 쿼리 기반 분석 |

---

## 2. 멀티클라우드 설계 패턴

### 2-1. 추상화 계층 패턴 (Abstraction Layer)

클라우드별 차이를 숨기고 **통일된 인터페이스**를 제공하는 패턴이다.

```
                   [Application Layer]
                         |
                  [Abstraction Layer]
                   /              \
           [AWS Provider]    [Azure Provider]
                |                   |
             AWS API            Azure API
```

**테라폼을 활용한 추상화 예시:**

```hcl
# modules/kubernetes-cluster/main.tf
# 클라우드에 관계없이 동일한 인터페이스로 K8s 클러스터 생성

variable "cloud_provider" {
  type = string
  validation {
    condition     = contains(["aws", "azure"], var.cloud_provider)
    error_message = "aws 또는 azure만 지원합니다."
  }
}

variable "cluster_config" {
  type = object({
    name         = string
    k8s_version  = string
    node_count   = number
    node_size    = string  # small, medium, large로 추상화
  })
}

# 클라우드별 인스턴스 타입 매핑
locals {
  instance_type_map = {
    aws = {
      small  = "t3.medium"
      medium = "t3.xlarge"
      large  = "t3.2xlarge"
    }
    azure = {
      small  = "Standard_D2s_v3"
      medium = "Standard_D4s_v3"
      large  = "Standard_D8s_v3"
    }
  }
}

module "eks" {
  source = "./aws-eks"
  count  = var.cloud_provider == "aws" ? 1 : 0

  cluster_name = var.cluster_config.name
  k8s_version  = var.cluster_config.k8s_version
  node_count   = var.cluster_config.node_count
  node_type    = local.instance_type_map["aws"][var.cluster_config.node_size]
}

module "aks" {
  source = "./azure-aks"
  count  = var.cloud_provider == "azure" ? 1 : 0

  cluster_name = var.cluster_config.name
  k8s_version  = var.cluster_config.k8s_version
  node_count   = var.cluster_config.node_count
  node_type    = local.instance_type_map["azure"][var.cluster_config.node_size]
}
```

### 2-2. 서비스 메시 패턴 (Service Mesh)

클라우드 간 서비스 통신을 **메시(Mesh)**로 연결하는 패턴이다.

```
[AWS EKS]                          [Azure AKS]
  Pod A  <-- Istio/Linkerd -->  Pod B
    |        mTLS 암호화           |
  Envoy     트래픽 관리         Envoy
  Sidecar   관측성              Sidecar
```

**주요 구성 요소:**

| 구성 요소 | 역할 | 도구 예시 |
|-----------|------|----------|
| 데이터 플레인 (Data Plane) | 트래픽 프록시 | Envoy, Linkerd-proxy |
| 컨트롤 플레인 (Control Plane) | 정책/설정 관리 | Istiod, Linkerd |
| 멀티클러스터 (Multi-Cluster) | 클라우드 간 연결 | Istio Multi-Primary |

### 2-3. GitOps 기반 멀티클라우드 배포

```
[Git Repository]
      |
  [ArgoCD / Flux]
    /          \
[AWS EKS]   [Azure AKS]
  - App v2.1    - App v2.1
  - ConfigMap    - ConfigMap
  - Secrets      - Secrets (External Secrets)
```

```yaml
# ArgoCD ApplicationSet으로 멀티클러스터 배포
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: allganize-app
spec:
  generators:
    - list:
        elements:
          - cluster: aws-prod
            url: https://eks.ap-northeast-2.amazonaws.com
          - cluster: azure-prod
            url: https://aks.koreacentral.azmk8s.io
  template:
    metadata:
      name: "app-{{cluster}}"
    spec:
      source:
        repoURL: https://github.com/allganize/k8s-manifests
        targetRevision: main
        path: "overlays/{{cluster}}"
      destination:
        server: "{{url}}"
        namespace: allganize
```

---

## 3. 비용 최적화 전략

### 3-1. AWS 비용 최적화

| 전략 | 설명 | 절감율 |
|------|------|--------|
| Reserved Instances (RI) | 1~3년 약정으로 할인 | 최대 72% |
| Savings Plans | 시간당 사용량 약정 (유연) | 최대 66% |
| Spot Instances | 미사용 용량 입찰 구매 | 최대 90% |
| Graviton (ARM) | ARM 기반 인스턴스 | 20~40% |
| Right-sizing | 실사용량 기반 스펙 조정 | 10~30% |

### 3-2. Azure 비용 최적화

| 전략 | 설명 | 절감율 |
|------|------|--------|
| Reserved VM Instances | 1~3년 약정 | 최대 72% |
| Azure Savings Plan | 컴퓨팅 사용량 약정 | 최대 65% |
| Spot VMs | 미사용 용량 활용 | 최대 90% |
| Azure Hybrid Benefit | 기존 Windows/SQL 라이선스 활용 | 최대 85% |
| Dev/Test Pricing | 비프로덕션 환경 할인 | 최대 55% |

### 3-3. 멀티클라우드 비용 관리 도구

```hcl
# Spot 인스턴스를 활용한 EKS 노드 그룹 예시
resource "aws_eks_node_group" "spot_workers" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "spot-workers"
  capacity_type   = "SPOT"

  instance_types = [
    "t3.xlarge",
    "t3a.xlarge",
    "m5.xlarge",
    "m5a.xlarge"  # 다양한 타입으로 Spot 가용성 확보
  ]

  scaling_config {
    desired_size = 3
    max_size     = 10
    min_size     = 1
  }
}
```

| 도구 | 설명 |
|------|------|
| AWS Cost Explorer / Azure Cost Management | 각 클라우드 네이티브 비용 분석 |
| Infracost | 테라폼 `plan` 단계에서 비용 예측 |
| Kubecost | 쿠버네티스 워크로드별 비용 분석 |
| FinOps Foundation 프레임워크 | 조직 차원 비용 거버넌스 |

---

## 4. 올거나이즈 맥락: 왜 멀티클라우드가 필요한가

### 4-1. 글로벌 고객 대응

올거나이즈는 AI 기반 엔터프라이즈 솔루션을 제공하며, 고객이 선택한 클라우드에서 서비스를 제공해야 한다.

```
[한국 고객]           [일본 고객]           [미국 고객]
AWS Seoul            Azure Japan East     AWS us-east-1
ap-northeast-2       japaneast            us-east-1
  |                    |                    |
  +----- 동일한 IaC 코드베이스로 관리 ------+
```

### 4-2. 규제 및 컴플라이언스 (Compliance)

| 규제 | 요구 사항 | 클라우드 대응 |
|------|----------|-------------|
| 한국 개인정보보호법 | 국내 데이터 저장 | AWS 서울, Azure Korea |
| GDPR (유럽) | EU 내 데이터 처리 | AWS Frankfurt, Azure West Europe |
| 금융 규제 | 망분리, 전용 환경 | Dedicated Host, 폐쇄망 VPC |
| 공공 클라우드 인증 | CSAP 인증 클라우드 | AWS, Azure (국내 인증) |

### 4-3. 온프레미스/폐쇄망 경험의 가치

```
[On-Premises / Air-gapped]        [Multi-Cloud]
        |                               |
  네트워크 격리 설계          -->  VPC/VNET 보안 설계
  수동 인프라 관리            -->  IaC 자동화 필요성 체감
  폐쇄망 패키지 미러링        -->  Private Registry 운영
  물리 장비 이중화            -->  Multi-AZ/Region 설계
  자체 모니터링 구축          -->  Observability 설계
```

> **핵심 메시지:** 폐쇄망에서 직접 인프라를 설계하고 운영한 경험은, 클라우드의 "마법" 뒤에 숨겨진 실제 동작 원리를 이해한다는 것을 의미한다. 네트워크 격리, 보안, 이중화를 물리적 수준에서 경험했기 때문에, 클라우드 환경에서도 더 견고한 아키텍처를 설계할 수 있다.

---

## 면접 Q&A

### Q1. "왜 멀티클라우드를 해야 하나요? 단일 클라우드가 더 간단하지 않나요?"

> **이렇게 대답한다:**
> 맞습니다. 단일 클라우드가 운영 복잡도는 낮습니다. 하지만 멀티클라우드는 세 가지 상황에서 필수입니다. 첫째, **고객 요구** - 엔터프라이즈 고객이 자사 클라우드에서만 서비스를 운영해야 할 때. 둘째, **규제 대응** - 데이터 주권법(Data Sovereignty)으로 특정 리전/클라우드를 사용해야 할 때. 셋째, **벤더 종속 방지** - 가격 협상력 확보와 장애 시 대안 확보. 올거나이즈처럼 글로벌 엔터프라이즈 고객을 상대하는 회사에서는 고객 선택에 따른 멀티클라우드 대응이 필수적입니다.

### Q2. "멀티클라우드 환경에서 IaC를 어떻게 관리하나요?"

> **이렇게 대답한다:**
> 테라폼의 **모듈 추상화**를 활용합니다. 공통 인터페이스(변수/출력)를 정의하고, 클라우드별 구현을 별도 모듈로 분리합니다. 디렉토리 구조는 `modules/aws-*`, `modules/azure-*`로 나누고, `environments/` 아래에서 클라우드별 변수 파일로 호출합니다. CI/CD에서는 ArgoCD ApplicationSet으로 여러 클러스터에 동시 배포합니다.

### Q3. "온프레미스 경험이 클라우드 업무에 어떻게 도움이 되나요?"

> **이렇게 대답한다:**
> 클라우드 서비스의 내부 동작 원리를 깊이 이해할 수 있습니다. 예를 들어 VPC를 설계할 때, 실제 VLAN과 라우팅 테이블을 직접 구성해본 경험이 있어서 서브넷 설계, NAT 동작, 방화벽 규칙을 더 정확하게 이해합니다. 또한 폐쇄망에서 패키지 미러링, 레지스트리 구축, 인증서 관리를 직접 해본 경험은 Private 환경의 클라우드 운영에 그대로 적용됩니다.

### Q4. "클라우드 비용 최적화는 어떻게 접근하나요?"

> **이렇게 대답한다:**
> 3단계로 접근합니다. 첫째, **가시성 확보** - 태깅(Tagging) 전략을 세우고 팀/서비스별 비용을 추적합니다. 둘째, **Right-sizing** - 실제 사용량 대비 과도한 스펙을 식별하고 조정합니다. 셋째, **약정 할인** - 안정적 워크로드는 RI/Savings Plan, 배치 처리는 Spot을 활용합니다. 테라폼 PR에 Infracost를 연동하면 코드 변경 시점에 비용 영향을 미리 확인할 수 있습니다.

### Q5. "하이브리드 클라우드(온프레미스 + 클라우드) 연결은 어떻게 하나요?"

> **이렇게 대답한다:**
> 네트워크는 **AWS Direct Connect** 또는 **Azure ExpressRoute**로 전용 회선을 구성하고, VPN을 백업으로 사용합니다. 쿠버네티스 환경에서는 온프레미스에 Rancher나 OpenShift를, 클라우드에 EKS/AKS를 두고 서비스 메시(Istio)로 연결합니다. 데이터 동기화는 용도에 따라 CDC(Change Data Capture)나 오브젝트 스토리지 복제를 사용합니다.

---

**핵심 키워드 5선:**
`멀티클라우드 추상화 (Multi-Cloud Abstraction)`, `서비스 매핑 (Service Mapping)`, `비용 최적화 (Cost Optimization)`, `하이브리드 클라우드 (Hybrid Cloud)`, `벤더 종속 방지 (Vendor Lock-in Avoidance)`
