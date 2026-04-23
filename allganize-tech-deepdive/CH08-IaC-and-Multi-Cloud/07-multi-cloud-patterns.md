# 멀티클라우드 패턴

> **TL;DR**: 멀티클라우드는 AWS+Azure를 동시에 운영하여 가용성을 높이고 벤더 종속(Lock-in)을 줄이는 전략이다.
> 클라우드 간 네트워크 연결(VPN/ExpressRoute+Direct Connect), 통합 DR 전략, 추상화 계층 설계가 핵심이다.
> 복잡성 증가라는 트레이드오프를 인정하고, "왜 멀티클라우드인가"에 대한 명확한 근거가 필요하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### 멀티클라우드 동기

```
┌──────────────────────────────────────────────────────────────┐
│                 멀티클라우드를 선택하는 이유                     │
│                                                              │
│  1. 가용성 (Availability)                                    │
│     → 하나의 CSP 장애 시 다른 CSP로 트래픽 전환               │
│     → SLA: 단일 99.99% → 멀티 99.9999% 이론적 가능          │
│                                                              │
│  2. 벤더 종속 회피 (Vendor Lock-in Avoidance)                 │
│     → 특정 CSP 가격 인상/정책 변경 시 이동 가능               │
│     → 협상력 확보 (가격, 지원)                                │
│                                                              │
│  3. 규제 준수 (Compliance)                                   │
│     → 데이터 주권법: 특정 국가에 데이터 저장 필수              │
│     → 고객 요구: "우리 데이터는 Azure에만"                    │
│                                                              │
│  4. Best-of-Breed 활용                                       │
│     → AWS: ML/AI 생태계 (SageMaker, Bedrock)                │
│     → Azure: Enterprise 통합 (AAD, Office365)                │
│     → GCP: BigQuery, Vertex AI                               │
│                                                              │
│  5. 인수합병 (M&A)                                           │
│     → 인수한 회사가 다른 CSP 사용 중                          │
└──────────────────────────────────────────────────────────────┘
```

### 멀티클라우드 아키텍처 패턴

```
패턴 1: Active-Active (양쪽 모두 트래픽 처리)

┌─────────────────────────────────────────────────────────────┐
│                     Global DNS (Route53)                      │
│                     Latency/Geolocation Routing              │
│                            │                                 │
│              ┌─────────────┴──────────────┐                  │
│              │                            │                  │
│              ▼                            ▼                  │
│  ┌──── AWS (Seoul) ─────┐   ┌──── Azure (Korea) ───┐       │
│  │                      │   │                       │       │
│  │  EKS Cluster         │   │  AKS Cluster          │       │
│  │  ┌────────────────┐  │   │  ┌────────────────┐   │       │
│  │  │ Alli API       │  │   │  │ Alli API       │   │       │
│  │  │ Alli Worker    │  │   │  │ Alli Worker    │   │       │
│  │  │ Model Server   │  │   │  │ Model Server   │   │       │
│  │  └────────────────┘  │   │  └────────────────┘   │       │
│  │                      │   │                       │       │
│  │  RDS (Primary)       │   │  CosmosDB             │       │
│  │  S3 (Models)         │   │  Blob (Models)        │       │
│  └───────────┬──────────┘   └──────────┬────────────┘       │
│              │                         │                     │
│              └─── VPN / Peering ───────┘                     │
│                   (데이터 동기화)                              │
└─────────────────────────────────────────────────────────────┘


패턴 2: Active-Passive (한쪽은 DR 대기)

┌─────────────────────────────────────────────────────────────┐
│                     Global DNS                               │
│                     Failover Routing                         │
│                            │                                 │
│              ┌─────────────┴──────────────┐                  │
│              │ (active)                   │ (passive)         │
│              ▼                            ▼                  │
│  ┌──── AWS (Primary) ──┐    ┌──── Azure (DR) ──────┐       │
│  │                      │    │                       │       │
│  │  Full Service        │    │  Minimal Infra        │       │
│  │  (EKS, RDS, etc.)   │    │  (AKS: 최소 노드)     │       │
│  │                      │    │  DB: Read Replica      │       │
│  │                      │    │                       │       │
│  │  ────── 데이터 복제 ─────▶│                       │       │
│  │         (비동기)      │    │  Failover 시:         │       │
│  │                      │    │  Scale-up + Promote   │       │
│  └──────────────────────┘    └───────────────────────┘       │
│                                                              │
│  RPO: 수분 (비동기 복제 지연)                                 │
│  RTO: 15-30분 (스케일업 + DNS 전환)                           │
└─────────────────────────────────────────────────────────────┘


패턴 3: 워크로드 분산 (서비스별 최적 클라우드 배치)

┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  ┌──── AWS ──────────────┐   ┌──── Azure ────────────┐      │
│  │                       │   │                       │      │
│  │  AI/ML 워크로드        │   │  Enterprise 고객     │      │
│  │  - Model Training     │   │  - AAD 통합 필요 고객 │      │
│  │  - SageMaker Endpoint │   │  - Azure 전용 계약    │      │
│  │  - GPU 인스턴스 활용   │   │  - Compliance 요구   │      │
│  │                       │   │                       │      │
│  │  Core Platform        │   │  Regional Service     │      │
│  │  - 주 서비스 운영     │   │  - 특정 리전 서비스   │      │
│  │                       │   │                       │      │
│  └───────────────────────┘   └───────────────────────┘      │
│                                                              │
│  공유 계층: Terraform 모듈, CI/CD, Monitoring                │
└─────────────────────────────────────────────────────────────┘
```

### 클라우드 간 네트워크 연결

```
┌─────────────────────────────────────────────────────────────┐
│              Cross-Cloud Network Connectivity                 │
│                                                              │
│  방법 1: VPN (IPsec)                                        │
│  ┌──────────┐         IPsec Tunnel        ┌──────────┐     │
│  │ AWS VPC  │◀═══════════════════════════▶│Azure VNET│     │
│  │ VPN GW   │    (인터넷 경유, 암호화)      │ VPN GW   │     │
│  └──────────┘                              └──────────┘     │
│  비용: ~$70/월 (양쪽 GW)                                    │
│  대역폭: ~1.25 Gbps                                        │
│  지연: 가변적 (인터넷 경유)                                  │
│                                                              │
│  방법 2: 전용선 (ExpressRoute + Direct Connect)              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │ AWS VPC  │────│ 공통     │────│Azure VNET│              │
│  │ Direct   │    │ Colocation│    │ Express  │              │
│  │ Connect  │    │ (Equinix) │    │ Route    │              │
│  └──────────┘    └──────────┘    └──────────┘              │
│  비용: $500+/월                                             │
│  대역폭: 1-100 Gbps                                        │
│  지연: 일정하고 낮음 (전용선)                                │
│                                                              │
│  방법 3: 메가포트/Equinix Cloud Exchange                     │
│  → 단일 물리 연결로 여러 CSP에 가상 연결                     │
│  → 가장 유연하지만 추가 비용 발생                            │
└─────────────────────────────────────────────────────────────┘
```

```hcl
# AWS Side: VPN Gateway
resource "aws_vpn_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "alli-prod-vgw" }
}

resource "aws_customer_gateway" "azure" {
  bgp_asn    = 65515                  # Azure VPN GW 기본 ASN
  ip_address = azurerm_public_ip.vpn.ip_address
  type       = "ipsec.1"
  tags       = { Name = "azure-cgw" }
}

resource "aws_vpn_connection" "azure" {
  vpn_gateway_id      = aws_vpn_gateway.main.id
  customer_gateway_id = aws_customer_gateway.azure.id
  type                = "ipsec.1"
  static_routes_only  = false         # BGP 사용

  tags = { Name = "aws-to-azure-vpn" }
}

# Azure Side: VPN Gateway
resource "azurerm_virtual_network_gateway" "main" {
  name                = "alli-prod-vpn-gw"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  type                = "Vpn"
  vpn_type            = "RouteBased"
  sku                 = "VpnGw1"
  enable_bgp          = true

  ip_configuration {
    public_ip_address_id = azurerm_public_ip.vpn.id
    subnet_id            = azurerm_subnet.gateway.id
  }

  bgp_settings {
    asn = 65515
  }
}

resource "azurerm_local_network_gateway" "aws" {
  name                = "aws-lng"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  gateway_address     = aws_vpn_connection.azure.tunnel1_address
  address_space       = ["10.0.0.0/16"]   # AWS VPC CIDR
}

resource "azurerm_virtual_network_gateway_connection" "aws" {
  name                       = "aws-connection"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  type                       = "IPsec"
  virtual_network_gateway_id = azurerm_virtual_network_gateway.main.id
  local_network_gateway_id   = azurerm_local_network_gateway.aws.id
  shared_key                 = var.vpn_shared_key   # Key Vault에서 관리
}
```

### DR (Disaster Recovery) 전략

```
┌─────────────────────────────────────────────────────────────┐
│              DR 전략 레벨별 비교                              │
│                                                              │
│  Level   │ RTO    │ RPO    │ 비용   │ 구현                   │
│  ────────┼────────┼────────┼────────┼───────────────────     │
│  Backup  │ 24h+   │ 24h    │ $      │ 크로스 리전 백업       │
│  Pilot   │ 4h     │ 1h     │ $$     │ 최소 인프라 + 복제     │
│  Light   │                                                   │
│  Warm    │ 15-30m │ 분     │ $$$    │ 축소 운영 + DB 복제    │
│  Standby │        │        │        │                        │
│  Hot     │ < 5m   │ 초     │ $$$$   │ Active-Active          │
│  Standby │        │        │        │ + 동기 복제            │
│                                                              │
│  Allganize 추천: Warm Standby (비용 대비 효과 최적)          │
└─────────────────────────────────────────────────────────────┘
```

**Cross-Cloud DR 구현**:

```
정상 상태:
  DNS (Route53) → AWS EKS (Active)
                  Azure AKS (Warm Standby, 축소 운영)

  데이터 복제:
  AWS RDS ──(비동기)──▶ Azure DB for PostgreSQL
  AWS S3  ──(동기화)──▶ Azure Blob Storage

장애 발생:
  1. Health Check 실패 감지 (Route53 / 외부 모니터링)
  2. DNS Failover: Route53 → Azure AKS
  3. Azure AKS Node Pool Scale-up (2 → 10 nodes)
  4. Azure DB: Read Replica → Primary 승격
  5. 알림: PagerDuty + Slack → 엔지니어 대응

복구 완료:
  6. AWS 장애 복구 확인
  7. 데이터 동기화 (Azure → AWS delta sync)
  8. DNS Failback: Route53 → AWS EKS
  9. Azure AKS Scale-down (10 → 2 nodes)
```

### 벤더 종속 회피 전략

```
┌─────────────────────────────────────────────────────────────┐
│            Vendor Lock-in 회피 전략                           │
│                                                              │
│  계층별 추상화                                               │
│                                                              │
│  ┌─ Application 계층 ─────────────────────────────────────┐ │
│  │  K8s Deployment/Service (양쪽 동일)                     │ │
│  │  Helm Chart로 배포 표준화                               │ │
│  │  CSP 종속 API 사용 최소화                               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Platform 계층 ────────────────────────────────────────┐ │
│  │  Kubernetes (EKS / AKS) → K8s API 동일                 │ │
│  │  Ingress: NGINX (양쪽 동일) vs ALB/AppGW (CSP 종속)   │ │
│  │  Monitoring: Prometheus+Grafana (양쪽 동일)            │ │
│  │  GitOps: ArgoCD (양쪽 동일)                            │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Infrastructure 계층 ──────────────────────────────────┐ │
│  │  Terraform: 동일 워크플로, Provider만 교체              │ │
│  │  네트워크: CIDR 설계 통일                               │ │
│  │  IAM: IRSA / Workload Identity → 패턴 유사             │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Data 계층 (가장 어려움) ──────────────────────────────┐ │
│  │  DB: PostgreSQL (양쪽 매니지드 서비스 존재)             │ │
│  │  Object Storage: S3 API 호환 (MinIO 등)               │ │
│  │  Queue: Kafka (vs SQS/Service Bus → 종속)             │ │
│  │  Cache: Redis (ElastiCache / Azure Cache)             │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  원칙: "이식 가능한 기술 선택 + 종속 서비스는 인터페이스 격리"│
└─────────────────────────────────────────────────────────────┘
```

### 비용 비교

```
┌─────────────────────────────────────────────────────────────┐
│          AWS vs Azure 비용 비교 (서울/한국중부 리전)          │
│                                                              │
│  항목              │ AWS             │ Azure                 │
│  ─────────────────┼─────────────────┼─────────────────────  │
│  K8s 관리 비용     │ EKS: $0.10/h    │ AKS: 무료 (Free)     │
│  (컨트롤 플레인)   │ ($73/월)        │ Standard: $0.10/h    │
│                   │                 │ ($73/월)              │
│  ─────────────────┼─────────────────┼─────────────────────  │
│  VM (4vCPU 16GB)  │ m5.xlarge       │ Standard_D4s_v3      │
│  On-Demand        │ $0.192/h        │ $0.192/h             │
│  1yr RI           │ $0.121/h (37%)  │ $0.121/h (37%)       │
│  ─────────────────┼─────────────────┼─────────────────────  │
│  GPU (V100)       │ p3.2xlarge      │ Standard_NC6s_v3     │
│  On-Demand        │ $3.06/h         │ $3.06/h              │
│  ─────────────────┼─────────────────┼─────────────────────  │
│  NAT Gateway      │ $0.045/h +      │ $0.045/h +           │
│                   │ $0.045/GB       │ $0.045/GB            │
│  ─────────────────┼─────────────────┼─────────────────────  │
│  Object Storage   │ S3: $0.025/GB   │ Blob: $0.02/GB       │
│  (Standard)       │                 │ (Hot tier)           │
│  ─────────────────┼─────────────────┼─────────────────────  │
│  Data Transfer    │ $0.08-0.12/GB   │ $0.08-0.12/GB        │
│  (Outbound)       │ (리전별 상이)   │ (리전별 상이)        │
│                                                              │
│  * 가격은 참고용이며 실제 계약/볼륨에 따라 달라짐             │
│  * 양쪽 모두 EDP(Enterprise Discount Program) 협상 가능      │
└─────────────────────────────────────────────────────────────┘
```

## 실전 예시

### 통합 Terraform 구조

```
infrastructure/
├── aws/
│   ├── environments/
│   │   ├── dev/
│   │   ├── staging/
│   │   └── prod/
│   │       ├── main.tf
│   │       ├── backend.tf        # S3 backend
│   │       └── terraform.tfvars
│   └── modules/
│       ├── vpc/
│       ├── eks/
│       └── rds/
├── azure/
│   ├── environments/
│   │   ├── dev/
│   │   ├── staging/
│   │   └── prod/
│   │       ├── main.tf
│   │       ├── backend.tf        # azurerm backend
│   │       └── terraform.tfvars
│   └── modules/
│       ├── vnet/
│       ├── aks/
│       └── cosmosdb/
├── shared/                        # 클라우드 공통 설정
│   ├── dns/                       # Route53 (Global DNS)
│   └── monitoring/                # Datadog, PagerDuty
└── modules/
    └── k8s-base/                  # K8s 공통 리소스 (NGINX, cert-manager)
```

### Cross-Cloud 모니터링

```
┌─────────────────────────────────────────────────────────────┐
│              통합 모니터링 아키텍처                            │
│                                                              │
│  ┌── AWS EKS ──────────┐    ┌── Azure AKS ─────────┐       │
│  │                      │    │                       │       │
│  │  Prometheus          │    │  Prometheus            │       │
│  │  (metrics 수집)      │    │  (metrics 수집)        │       │
│  │       │              │    │       │                │       │
│  └───────┼──────────────┘    └───────┼────────────────┘       │
│          │                           │                       │
│          └──────────┬────────────────┘                       │
│                     │                                        │
│                     ▼                                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           Datadog / Grafana Cloud                     │   │
│  │           (통합 대시보드)                               │   │
│  │                                                      │   │
│  │  - 양쪽 클러스터 메트릭 통합 뷰                       │   │
│  │  - Cross-cloud 알림 (AWS 장애 → Azure 상태 확인)      │   │
│  │  - 비용 모니터링 (양쪽 합산)                          │   │
│  └──────────────────────────────────────────────────────┘   │
│                     │                                        │
│                     ▼                                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           PagerDuty + Slack                           │   │
│  │           (통합 알림)                                  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 통합 배포 파이프라인

```yaml
# .github/workflows/deploy.yml (멀티클라우드 배포)
name: Multi-Cloud Deploy

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}
    steps:
      - uses: actions/checkout@v4

      # ECR + ACR 동시 Push
      - name: Build & Push to ECR
        run: |
          docker build -t $ECR_REPO:$TAG .
          docker push $ECR_REPO:$TAG

      - name: Build & Push to ACR
        run: |
          docker build -t $ACR_REPO:$TAG .
          docker push $ACR_REPO:$TAG

  deploy-aws:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to EKS
        run: |
          aws eks update-kubeconfig --name alli-prod
          kubectl set image deployment/alli-api \
            alli-api=$ECR_REPO:${{ needs.build.outputs.image_tag }}

  deploy-azure:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to AKS
        run: |
          az aks get-credentials --name alli-prod-aks -g alli-prod-rg
          kubectl set image deployment/alli-api \
            alli-api=$ACR_REPO:${{ needs.build.outputs.image_tag }}
```

## 면접 Q&A

### Q: 멀티클라우드의 장점과 단점은 무엇인가요?

**30초 답변**:
장점은 가용성 향상(한 CSP 장애 시 다른 CSP로 전환), 벤더 종속 회피, 각 CSP의 강점 활용입니다. 단점은 복잡성 증가(운영팀 역량 필요), 비용 증가(이중 인프라, 데이터 전송), 최적화 어려움(각 CSP 고유 기능 활용 제한)입니다.

**2분 답변**:
멀티클라우드의 장점은 명확합니다. 첫째, 한 CSP의 리전 장애 시 다른 CSP로 Failover하여 서비스 연속성을 보장합니다. 2023년에도 AWS, Azure 모두 major outage가 있었고, 단일 CSP 의존은 리스크입니다. 둘째, 협상력입니다. 두 CSP에서 운영 가능한 아키텍처가 있으면 가격/계약 협상에서 유리합니다. 셋째, 규제 요건입니다. 특정 고객이 "우리 데이터는 Azure에서만 처리" 같은 요구를 할 때 대응 가능합니다.

하지만 트레이드오프도 큽니다. 가장 큰 것은 운영 복잡성입니다. 두 CSP의 네트워크 모델, IAM 구조, 서비스 특성을 모두 이해한 엔지니어가 필요합니다. 데이터 일관성도 도전인데, 클라우드 간 DB 동기화에는 지연이 있어 강한 일관성(Strong Consistency)이 어렵습니다.

비용도 단순히 "2배"는 아니지만, 이중 NAT Gateway, 데이터 전송 비용, 두 CSP의 관리형 서비스 이중 운영 등으로 상당히 증가합니다.

현실적 접근은 "모든 것을 멀티"가 아니라 "핵심 서비스만 멀티, 나머지는 주 CSP"입니다. Allganize처럼 K8s 기반이면 Application 계층은 이식이 비교적 쉽고, 데이터 계층이 가장 어렵습니다.

**💡 경험 연결**:
온프레미스에서 이중화(Active-Standby 서버, 이중 네트워크)를 구축했던 경험이 멀티클라우드 DR 설계에 직접 연결됩니다. 이중화의 핵심 원칙(독립적 장애 도메인, 자동 Failover, 정기 테스트)은 동일합니다.

**⚠️ 주의**:
"멀티클라우드 = 무조건 좋다"는 오해입니다. 운영 역량이 부족하면 오히려 양쪽 모두 불안정해집니다. 팀 규모와 역량에 맞는 전략을 선택해야 합니다.

---

### Q: 멀티클라우드에서 벤더 종속을 어떻게 줄이나요?

**30초 답변**:
세 가지 계층에서 접근합니다. 인프라 계층은 Terraform으로 양쪽 동일 워크플로를 사용하고, 플랫폼 계층은 K8s와 오픈소스 도구(Prometheus, ArgoCD)로 통일합니다. 데이터 계층은 PostgreSQL 같은 호환 가능한 DB를 선택하고, CSP 종속 서비스(SQS, Service Bus)는 인터페이스로 격리합니다.

**2분 답변**:
벤더 종속 회피의 핵심은 "추상화 계층"과 "이식 가능한 기술 선택"입니다.

인프라 계층에서 Terraform은 HCL이라는 동일한 언어로 AWS와 Azure를 모두 관리합니다. Provider만 교체하면 되므로 "인프라를 코드로 관리하는 능력"자체가 이식 가능합니다.

플랫폼 계층에서 K8s는 양쪽 모두 CNCF 표준을 따르므로, Deployment, Service, Ingress 등 K8s 매니페스트가 거의 동일합니다. 다만 Ingress Controller(ALB vs AppGW)나 StorageClass는 CSP별로 다르므로, NGINX Ingress 같은 오픈소스를 사용하면 차이를 줄일 수 있습니다.

데이터 계층이 가장 어렵습니다. DynamoDB(AWS 전용)보다 PostgreSQL(양쪽 매니지드 서비스 존재)을 선택하고, SQS 대신 Kafka를 사용하면 이식성이 높아집니다. 하지만 CSP 고유 서비스가 성능이나 비용에서 유리한 경우가 많으므로, 무조건 회피하기보다 "인터페이스를 격리"하여 교체 비용을 낮추는 것이 현실적입니다.

실질적으로는 Adapter 패턴을 적용합니다. 예를 들어 Object Storage 접근을 추상화하여, S3 SDK 직접 호출 대신 Storage Interface를 만들고 AWS/Azure 구현체를 교체 가능하게 합니다.

**💡 경험 연결**:
특정 벤더 장비에 종속된 경험이 있다면, 그때 느꼈던 불편함(마이그레이션 어려움, 가격 협상 불리)이 클라우드에서도 동일하게 적용됩니다. "표준 기술 우선 선택"의 원칙은 어디서나 유효합니다.

**⚠️ 주의**:
벤더 종속 회피에 과도하게 집중하면, 각 CSP의 강점(관리형 서비스, 자동 최적화)을 포기하게 됩니다. "완전한 이식성"보다 "합리적 수준의 이식성"을 목표로 해야 합니다.

---

### Q: 멀티클라우드 DR 전략을 어떻게 설계하나요?

**30초 답변**:
주 클라우드(AWS)에서 Active 운영, 보조 클라우드(Azure)에서 Warm Standby를 유지합니다. 데이터는 비동기로 복제하고, DNS Failover로 장애 시 자동 전환합니다. RPO(데이터 손실)와 RTO(복구 시간) 목표에 따라 복제 방식과 Standby 규모를 결정합니다.

**2분 답변**:
멀티클라우드 DR은 비즈니스 요구사항(RPO/RTO)과 비용의 균형점을 찾는 것이 핵심입니다.

Warm Standby 패턴을 기준으로 설명하면, AWS(주)에서 전체 서비스를 운영하고, Azure(보조)에서 최소한의 인프라(AKS 2노드, DB Read Replica)를 유지합니다. 정상 시 Azure 비용은 주 클라우드의 20-30% 수준입니다.

데이터 복제는 계층별로 다릅니다. DB는 논리적 복제(pg_dump/WAL shipping)나 서드파티 도구(Debezium CDC)로 Cross-cloud 복제합니다. Object Storage는 AWS S3 → Azure Blob 간 sync 도구(rclone)를 사용합니다. Container Image는 양쪽 레지스트리(ECR, ACR)에 동시 Push합니다.

Failover 프로세스는 자동화해야 합니다. Route53 Health Check → Failover → Azure DNS로 트래픽 전환. 동시에 Azure AKS Node Pool을 Auto-scaling으로 확장하고, DB를 Primary로 승격합니다.

가장 중요한 것은 정기 DR 테스트입니다. 분기 1회 이상 실제 Failover를 테스트하여, Runbook이 동작하는지 확인합니다. 테스트하지 않은 DR은 DR이 아닙니다.

**💡 경험 연결**:
온프레미스에서 DR 사이트를 운영하고 정기 전환 테스트를 했던 경험이 있다면, 그 프로세스가 클라우드 DR과 거의 동일합니다. 핵심은 "자동화된 Failover + 정기 테스트 + 명확한 Runbook"입니다.

**⚠️ 주의**:
Cross-cloud 데이터 전송 비용이 상당할 수 있습니다. 복제 데이터량과 빈도를 정확히 계산하여 비용을 사전에 파악해야 합니다. 또한 데이터 일관성 지연(RPO)으로 인해 Failover 직후 일부 데이터 손실이 발생할 수 있음을 비즈니스 팀과 합의해야 합니다.

## Allganize 맥락

- **AWS + Azure 멀티클라우드 운영**: Allganize는 실제로 AWS와 Azure에서 Alli 서비스를 운영한다. 이는 면접에서 멀티클라우드 관련 질문이 나올 확률이 매우 높다는 의미이다.
- **고객별 배포 유연성**: B2B AI 서비스 특성상, 고객이 특정 CSP를 요구할 수 있다. K8s 기반 아키텍처로 양쪽 배포가 가능한 구조가 핵심이다.
- **LLM 워크로드 특성**: 대용량 모델 파일(수십 GB)의 Cross-cloud 동기화, GPU 인스턴스 가용성 차이, 추론 latency 요구사항 등 AI 특화 멀티클라우드 과제가 있다.
- **JD 연결 — "AWS/Azure 멀티클라우드 경험"**: JD에 명시된 핵심 요구사항이다. 단순히 "두 CSP를 안다"가 아니라 "왜 멀티클라우드인지, 어떻게 운영하는지, 트레이드오프는 무엇인지"를 구조적으로 설명할 수 있어야 한다.
- **비용 최적화 연결**: 멀티클라우드 비용은 단일 클라우드보다 높으므로, 비용 최적화 역량이 더욱 중요하다. 양쪽 CSP의 가격 모델을 이해하고 비교할 수 있어야 한다.

---
**핵심 키워드**: `Multi-Cloud` `Active-Active` `Active-Passive` `Warm Standby` `VPN` `ExpressRoute` `Direct Connect` `DR` `RPO` `RTO` `Vendor Lock-in` `Failover` `Cross-Cloud Replication` `CIDR Planning`
