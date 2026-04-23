# Azure 인프라 설계

> **TL;DR**: Azure 인프라는 VNET/Subnet으로 네트워크를 설계하고, AKS(Azure Kubernetes Service)로 컨테이너를 운영한다.
> AAD(Azure Active Directory) 통합으로 K8s RBAC과 Azure IAM을 연결하고, Azure Policy로 조직 표준을 강제한다.
> Azure Advisor와 예약 인스턴스로 비용을 최적화하며, AWS와의 차이점을 이해하는 것이 멀티클라우드 운영의 핵심이다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Azure vs AWS 용어 매핑

```
┌──────────────────┬──────────────────┬─────────────────────────┐
│ 개념              │ AWS              │ Azure                   │
├──────────────────┼──────────────────┼─────────────────────────┤
│ 가상 네트워크     │ VPC              │ VNET                    │
│ 서브넷           │ Subnet           │ Subnet                  │
│ 인터넷 게이트웨이 │ IGW              │ (VNET에 내장)            │
│ NAT              │ NAT Gateway      │ NAT Gateway             │
│ 방화벽 규칙      │ Security Group   │ NSG (Network Security   │
│                  │                  │  Group)                  │
│ 라우팅           │ Route Table      │ Route Table (UDR)       │
│ K8s 서비스       │ EKS              │ AKS                     │
│ 컨테이너 레지스트리│ ECR              │ ACR                     │
│ IAM              │ IAM Role/Policy  │ Azure RBAC + AAD        │
│ 비밀 관리        │ Secrets Manager  │ Key Vault               │
│ 오브젝트 스토리지 │ S3               │ Blob Storage            │
│ DNS              │ Route 53         │ Azure DNS               │
│ CDN              │ CloudFront       │ Azure Front Door / CDN  │
│ 모니터링         │ CloudWatch       │ Azure Monitor           │
│ 리소스 그룹      │ (태그 기반)       │ Resource Group          │
└──────────────────┴──────────────────┴─────────────────────────┘
```

### VNET 네트워크 설계

```
┌────────────────── Resource Group: alli-prod-rg ──────────────────┐
│                                                                   │
│  ┌──────────────── VNET (10.1.0.0/16) ────────────────────────┐  │
│  │                                                             │  │
│  │  ┌── aks-subnet (10.1.0.0/20) ──────────────────────────┐  │  │
│  │  │                                                       │  │  │
│  │  │  AKS Nodes + Pods (Azure CNI)                        │  │  │
│  │  │  → /20 = 4,096 IPs (Node + Pod이 같은 서브넷)        │  │  │
│  │  │                                                       │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  ┌── appgw-subnet (10.1.16.0/24) ───────────────────────┐  │  │
│  │  │  Application Gateway (Ingress Controller)             │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  ┌── db-subnet (10.1.20.0/24) ──────────────────────────┐  │  │
│  │  │  Azure Database for PostgreSQL (Flexible Server)      │  │  │
│  │  │  Cosmos DB (MongoDB API)                              │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  ┌── pe-subnet (10.1.30.0/24) ──────────────────────────┐  │  │
│  │  │  Private Endpoints (Key Vault, ACR, Storage)          │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  │                                                             │  │
│  │  NAT Gateway ──▶ 아웃바운드 인터넷 (고정 Public IP)        │  │
│  │                                                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌── NSG (Network Security Group) ─────────────────────────────┐  │
│  │  Allow: HTTPS(443) from Internet → AppGW Subnet             │  │
│  │  Allow: AKS API → AKS Subnet                               │  │
│  │  Allow: AKS Subnet → DB Subnet (PostgreSQL 5432)           │  │
│  │  Deny:  All other inbound                                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### VNET Terraform 코드

```hcl
# Resource Group
resource "azurerm_resource_group" "main" {
  name     = "alli-prod-rg"
  location = "koreacentral"

  tags = {
    Environment = "production"
    ManagedBy   = "terraform"
    Service     = "alli"
  }
}

# VNET
resource "azurerm_virtual_network" "main" {
  name                = "alli-prod-vnet"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.1.0.0/16"]

  tags = azurerm_resource_group.main.tags
}

# AKS Subnet (/20 - Azure CNI에서 Node+Pod IP 필요)
resource "azurerm_subnet" "aks" {
  name                 = "aks-subnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.1.0.0/20"]
}

# Application Gateway Subnet
resource "azurerm_subnet" "appgw" {
  name                 = "appgw-subnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.1.16.0/24"]
}

# DB Subnet
resource "azurerm_subnet" "db" {
  name                 = "db-subnet"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.1.20.0/24"]

  delegation {
    name = "postgresql"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action"
      ]
    }
  }
}

# Private Endpoint Subnet
resource "azurerm_subnet" "pe" {
  name                                      = "pe-subnet"
  resource_group_name                       = azurerm_resource_group.main.name
  virtual_network_name                      = azurerm_virtual_network.main.name
  address_prefixes                          = ["10.1.30.0/24"]
  private_endpoint_network_policies_enabled = true
}

# NAT Gateway (아웃바운드 고정 IP)
resource "azurerm_public_ip" "nat" {
  name                = "alli-prod-nat-pip"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_nat_gateway" "main" {
  name                    = "alli-prod-nat"
  resource_group_name     = azurerm_resource_group.main.name
  location                = azurerm_resource_group.main.location
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
}

resource "azurerm_nat_gateway_public_ip_association" "main" {
  nat_gateway_id       = azurerm_nat_gateway.main.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

resource "azurerm_subnet_nat_gateway_association" "aks" {
  subnet_id      = azurerm_subnet.aks.id
  nat_gateway_id = azurerm_nat_gateway.main.id
}

# NSG
resource "azurerm_network_security_group" "aks" {
  name                = "alli-prod-aks-nsg"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  security_rule {
    name                       = "AllowHTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "Internet"
    destination_address_prefix = "10.1.16.0/24"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}
```

### AKS 클러스터 구성

```hcl
# AKS Cluster
resource "azurerm_kubernetes_cluster" "main" {
  name                = "alli-prod-aks"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = "alli-prod"
  kubernetes_version  = "1.29"
  sku_tier            = "Standard"     # SLA 보장 (99.95%)

  # Azure CNI (Pod에 VNET IP 직접 할당)
  network_profile {
    network_plugin    = "azure"
    network_policy    = "calico"       # NetworkPolicy 지원
    service_cidr      = "172.16.0.0/16"
    dns_service_ip    = "172.16.0.10"
    load_balancer_sku = "standard"

    outbound_type = "userAssignedNATGateway"   # NAT GW 사용
  }

  # System Node Pool (K8s 시스템 컴포넌트)
  default_node_pool {
    name                = "system"
    vm_size             = "Standard_D4s_v3"   # 4 vCPU, 16 GB
    min_count           = 2
    max_count           = 5
    enable_auto_scaling = true
    vnet_subnet_id      = azurerm_subnet.aks.id
    os_disk_type        = "Managed"
    os_disk_size_gb     = 100

    node_labels = {
      "nodepool-type" = "system"
    }

    only_critical_addons_enabled = true   # 시스템 Pod만 스케줄링

    upgrade_settings {
      max_surge = "25%"
    }
  }

  # AAD 통합 (Azure RBAC)
  azure_active_directory_role_based_access_control {
    managed                = true
    azure_rbac_enabled     = true
    admin_group_object_ids = [var.aks_admin_group_id]
  }

  # Managed Identity
  identity {
    type = "SystemAssigned"
  }

  # Azure Monitor 연동
  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }

  # Azure Key Vault CSI Driver
  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "2m"
  }

  # Maintenance Window
  maintenance_window {
    allowed {
      day   = "Sunday"
      hours = [2, 3, 4]     # 일요일 새벽 유지보수
    }
  }

  tags = azurerm_resource_group.main.tags
}

# User Node Pool (Application 워크로드)
resource "azurerm_kubernetes_cluster_node_pool" "app" {
  name                  = "app"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = "Standard_D8s_v3"   # 8 vCPU, 32 GB
  min_count             = 3
  max_count             = 20
  enable_auto_scaling   = true
  vnet_subnet_id        = azurerm_subnet.aks.id

  node_labels = {
    "nodepool-type" = "application"
    "workload"      = "general"
  }

  tags = azurerm_resource_group.main.tags
}

# GPU Node Pool (AI 추론)
resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  name                  = "gpu"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = "Standard_NC6s_v3"   # 1 V100 GPU
  min_count             = 0
  max_count             = 10
  enable_auto_scaling   = true
  vnet_subnet_id        = azurerm_subnet.aks.id

  node_labels = {
    "nodepool-type"      = "gpu"
    "nvidia.com/gpu"     = "true"
  }

  node_taints = [
    "nvidia.com/gpu=true:NoSchedule"
  ]

  tags = azurerm_resource_group.main.tags
}
```

### AAD (Azure Active Directory) 통합

```
┌────────────────────────────────────────────────────────┐
│               AAD + AKS RBAC 통합                       │
│                                                        │
│  Azure AD                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐               │
│  │ User    │  │ Group   │  │ Service │               │
│  │ (개발자) │  │ (DevOps)│  │ Principal│              │
│  └────┬────┘  └────┬────┘  └────┬────┘               │
│       │            │            │                      │
│       ▼            ▼            ▼                      │
│  ┌──────────────────────────────────┐                 │
│  │  AKS Azure RBAC                  │                 │
│  │                                  │                 │
│  │  ClusterRole: cluster-admin      │                 │
│  │  → AAD Group: DevOps-Admin       │                 │
│  │                                  │                 │
│  │  Role: namespace-developer       │                 │
│  │  → AAD Group: Backend-Dev        │                 │
│  │  → Namespace: alli-app           │                 │
│  │                                  │                 │
│  │  Role: namespace-viewer          │                 │
│  │  → AAD Group: QA-Team            │                 │
│  │  → Namespace: alli-app           │                 │
│  └──────────────────────────────────┘                 │
│                                                        │
│  kubectl 접근 시:                                       │
│  1. az login (AAD 인증)                                │
│  2. az aks get-credentials                             │
│  3. kubectl → AAD Token 자동 사용                       │
│  4. AKS API Server → AAD 토큰 검증 → RBAC 확인         │
└────────────────────────────────────────────────────────┘
```

```hcl
# AAD Group 기반 K8s RBAC
resource "azurerm_role_assignment" "aks_cluster_admin" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service Cluster Admin Role"
  principal_id         = var.devops_admin_group_id
}

resource "azurerm_role_assignment" "aks_user" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = var.developer_group_id
}

# Namespace 레벨 RBAC (K8s RoleBinding)
resource "kubernetes_role_binding" "developer" {
  metadata {
    name      = "developer-binding"
    namespace = "alli-app"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = "edit"
  }

  subject {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Group"
    name      = var.developer_group_id   # AAD Group Object ID
  }
}
```

### Azure Policy

```hcl
# AKS에 Azure Policy 활성화
resource "azurerm_kubernetes_cluster" "main" {
  # ... (위 설정에 추가)

  azure_policy_enabled = true
}

# 정책 할당: 컨테이너는 허용된 레지스트리에서만 Pull
resource "azurerm_resource_group_policy_assignment" "allowed_registries" {
  name                 = "aks-allowed-registries"
  resource_group_id    = azurerm_resource_group.main.id
  policy_definition_id = "/providers/Microsoft.Authorization/policyDefinitions/febd0533-8e55-448f-b837-bd0e06f16469"

  parameters = jsonencode({
    allowedContainerImagesRegex = {
      value = "alliganizeprod\\.azurecr\\.io/.+"
    }
    effect = {
      value = "deny"
    }
  })
}

# 정책 할당: 리소스에 태그 필수
resource "azurerm_resource_group_policy_assignment" "require_tags" {
  name                 = "require-environment-tag"
  resource_group_id    = azurerm_resource_group.main.id
  policy_definition_id = "/providers/Microsoft.Authorization/policyDefinitions/871b6d14-10aa-478d-b466-ef6698f0e25f"

  parameters = jsonencode({
    tagName = {
      value = "Environment"
    }
  })
}
```

### 비용 관리

```
┌─────────────────────────────────────────────────────┐
│              Azure 비용 최적화 전략                    │
│                                                     │
│  1. Azure Advisor 권장사항                           │
│     - 미활용 VM 식별 (CPU < 5%)                     │
│     - Right-sizing 제안                             │
│     - 예약 인스턴스 구매 권장                        │
│                                                     │
│  2. Azure Reservations (예약 인스턴스)               │
│     - 1년: ~35% 할인                                │
│     - 3년: ~55% 할인                                │
│     - AKS Node Pool 기본 용량에 적용                 │
│                                                     │
│  3. Spot VM (AKS Spot Node Pool)                    │
│     - 최대 90% 할인                                 │
│     - Eviction Policy: Delete/Deallocate            │
│     - 배치 처리, 개발 환경에 적합                    │
│                                                     │
│  4. Azure Cost Management                           │
│     - Budget Alert 설정                             │
│     - Resource Group별 비용 추적                    │
│     - 태그 기반 비용 할당                            │
│                                                     │
│  5. Dev/Test 구독                                   │
│     - 개발 환경 전용 구독 (할인된 요금)              │
│     - Visual Studio 구독자 크레딧 활용               │
└─────────────────────────────────────────────────────┘
```

```hcl
# Spot Node Pool (배치 워크로드용)
resource "azurerm_kubernetes_cluster_node_pool" "spot" {
  name                  = "spot"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = "Standard_D4s_v3"
  min_count             = 0
  max_count             = 20
  enable_auto_scaling   = true
  priority              = "Spot"
  eviction_policy       = "Delete"
  spot_max_price        = -1    # 현재 Spot 가격 사용

  node_labels = {
    "kubernetes.azure.com/scalesetpriority" = "spot"
  }

  node_taints = [
    "kubernetes.azure.com/scalesetpriority=spot:NoSchedule"
  ]
}

# Budget Alert
resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "alli-prod-monthly-budget"
  resource_group_id = azurerm_resource_group.main.id

  amount     = 10000   # $10,000/월
  time_grain = "Monthly"

  time_period {
    start_date = "2024-01-01T00:00:00Z"
    end_date   = "2025-12-31T00:00:00Z"
  }

  notification {
    enabled   = true
    threshold = 80   # 80% 도달 시
    operator  = "GreaterThan"
    contact_emails = ["devops@allganize.ai"]
  }

  notification {
    enabled   = true
    threshold = 100  # 100% 도달 시
    operator  = "GreaterThan"
    contact_emails = ["devops@allganize.ai", "cto@allganize.ai"]
  }
}
```

## 실전 예시

### ACR (Azure Container Registry) + AKS 연동

```hcl
resource "azurerm_container_registry" "main" {
  name                = "alliganizeprod"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Premium"        # Geo-replication, Private Link
  admin_enabled       = false            # Managed Identity 사용

  georeplications {
    location = "japaneast"               # DR용 복제
  }
}

# AKS → ACR Pull 권한
resource "azurerm_role_assignment" "aks_acr" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
}
```

### Key Vault + AKS CSI Driver

```hcl
resource "azurerm_key_vault" "main" {
  name                = "alli-prod-kv"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  enable_rbac_authorization = true   # RBAC 기반 접근 제어

  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
    virtual_network_subnet_ids = [azurerm_subnet.aks.id]
  }
}

# AKS Identity → Key Vault 접근 권한
resource "azurerm_role_assignment" "kv_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_kubernetes_cluster.main.key_vault_secrets_provider[0].secret_identity[0].object_id
}
```

## 면접 Q&A

### Q: AWS와 Azure의 네트워크 설계 차이점은 무엇인가요?

**30초 답변**:
가장 큰 차이는 Azure에는 별도 Internet Gateway가 없고 VNET이 기본적으로 아웃바운드 인터넷을 지원한다는 점입니다. 또한 Azure는 NSG(Network Security Group)를 서브넷 또는 NIC 레벨에 연결하고, AWS의 Security Group은 인스턴스 레벨입니다. AKS의 Azure CNI는 Pod에 VNET IP를 직접 할당하여 더 큰 서브넷(/20 이상)이 필요합니다.

**2분 답변**:
네트워크 설계에서 핵심 차이점은 세 가지입니다.

첫째, 인터넷 접근 모델입니다. AWS는 IGW를 명시적으로 생성하고 Route Table에 연결해야 합니다. Azure VNET은 기본적으로 아웃바운드 인터넷이 가능하지만, 보안을 위해 NAT Gateway로 아웃바운드를 제어하는 것이 권장됩니다.

둘째, 보안 그룹 모델입니다. AWS Security Group은 Stateful(인바운드 허용 시 아웃바운드 자동 허용)이고 인스턴스에 연결됩니다. Azure NSG는 서브넷 또는 NIC에 연결되며, 명시적 우선순위(priority) 기반 규칙입니다.

셋째, K8s 네트워킹입니다. EKS의 VPC CNI는 Pod에 VPC 서브넷 IP를 할당하지만 Prefix Delegation으로 IP 효율성을 높일 수 있습니다. AKS의 Azure CNI는 Pod에 VNET IP를 직접 할당하므로 서브넷을 크게 잡아야 합니다(/20 이상 권장). AKS는 Azure CNI Overlay 모드도 지원하여 Pod IP를 VNET과 분리할 수 있습니다.

**💡 경험 연결**:
온프레미스 네트워크에서 VLAN, ACL, 방화벽 규칙을 설계했던 경험이 양쪽 클라우드 네트워크 설계에 모두 적용됩니다. 핵심 보안 원칙(최소 권한, 계층 분리)은 동일하고, 구현 방법만 다릅니다.

**⚠️ 주의**:
Azure CNI에서 서브넷 크기 계산을 잘못하면 IP 고갈이 발생합니다. (Node수 x Node당 최대 Pod수) + 여유분으로 계산해야 합니다. 기본 Node당 30 Pods이므로, 10 Node면 300+ IP가 필요합니다.

---

### Q: AKS와 AAD 통합은 왜 중요한가요?

**30초 답변**:
AAD 통합으로 K8s 인증을 회사 계정(Azure AD)과 연결합니다. 별도의 K8s 사용자 관리 없이 AAD 그룹 멤버십으로 클러스터 접근 권한을 제어하고, 퇴사자 계정을 비활성화하면 K8s 접근도 자동 차단됩니다. 조직의 SSO, MFA 정책이 K8s에도 적용됩니다.

**2분 답변**:
AAD 통합은 보안과 운영 효율성 두 가지 측면에서 중요합니다.

보안 측면에서, AAD 없이는 K8s 자체 인증(kubeconfig 토큰, 인증서)을 사용하는데, 이는 관리가 어렵고 보안 위험이 있습니다. AAD를 사용하면 회사의 보안 정책(MFA, 조건부 접근, 세션 만료)이 K8s에 그대로 적용됩니다.

운영 측면에서, AAD 그룹 기반으로 K8s RBAC을 설정하면 "DevOps 그룹 = cluster-admin", "Backend 그룹 = namespace developer" 같은 매핑이 가능합니다. 신규 입사자를 AAD 그룹에 추가하면 K8s 권한이 자동 부여되고, 퇴사 시 AAD 계정 비활성화로 모든 접근이 차단됩니다.

Azure RBAC Enabled 모드를 사용하면 K8s RoleBinding 없이 Azure IAM에서 직접 K8s 권한을 관리할 수도 있습니다. Azure Portal에서 누가 어떤 클러스터에 접근하는지 감사 로그도 확인됩니다.

**💡 경험 연결**:
온프레미스에서 Active Directory/LDAP로 서버 접근을 제어했던 것과 동일한 개념입니다. 중앙 계정 관리의 원칙은 클라우드에서도 변하지 않습니다.

**⚠️ 주의**:
AAD 장애 시 K8s 인증이 불가능할 수 있으므로, break-glass 계정(로컬 admin)을 비상용으로 준비해야 합니다. `admin_group_object_ids`에 비상 접근 그룹을 포함시킵니다.

---

### Q: Azure Policy를 어떻게 활용하나요?

**30초 답변**:
Azure Policy는 조직 표준을 자동으로 강제하는 거버넌스 도구입니다. AKS에서는 "허용된 컨테이너 레지스트리만 사용", "루트 컨테이너 실행 금지", "리소스 요청/제한 필수" 같은 정책을 적용합니다. 위반 시 리소스 생성을 차단(deny)하거나 감사(audit)합니다.

**2분 답변**:
Azure Policy는 세 가지 수준에서 활용됩니다.

첫째, 플랫폼 레벨입니다. 모든 리소스에 필수 태그(Environment, Owner)를 요구하고, 허용된 리전에서만 리소스 생성을 허용합니다. 특정 VM SKU 사용을 제한하여 비용을 통제합니다.

둘째, AKS 레벨입니다. Azure Policy for Kubernetes는 내부적으로 OPA Gatekeeper를 사용합니다. 허용된 ACR에서만 이미지 Pull, 루트 컨테이너 실행 금지, 호스트 네트워크 사용 금지, 리소스 requests/limits 필수 등의 정책을 적용합니다.

셋째, 감사(Audit) 모드입니다. 처음에는 audit 모드로 정책을 적용하여 기존 위반 사항을 파악하고, 수정 후 deny 모드로 전환합니다. 이렇게 하면 정책 도입 시 기존 워크로드가 갑자기 차단되는 사고를 방지합니다.

**💡 경험 연결**:
온프레미스에서 서버 표준(OS 버전, 패치 정책, 보안 설정)을 강제했던 것과 같은 개념입니다. Azure Policy는 이를 클라우드 네이티브하게 자동화한 것입니다.

**⚠️ 주의**:
Azure Policy 적용 시 기존 리소스는 영향받지 않습니다(deny는 새 생성/수정만 차단). 기존 위반 리소스를 정리하려면 remediation task를 별도로 실행해야 합니다.

## Allganize 맥락

- **AKS 기반 Alli 서비스**: Allganize는 Azure에서도 K8s 기반으로 Alli를 운영한다. AKS의 AAD 통합, Azure Policy, Key Vault CSI Driver가 보안과 거버넌스의 기반이다.
- **Korea Central 리전**: 한국 고객 서비스를 위해 Korea Central 리전을 주로 사용하며, DR을 위해 Japan East 리전에 복제를 구성한다.
- **AWS + Azure 동시 운영**: AWS(EKS)와 Azure(AKS)를 동시에 운영하므로, 양쪽 인프라의 차이점(네트워크 모델, IAM 구조, 비용 모델)을 이해하는 것이 필수이다.
- **JD 연결 — "Azure 인프라 관리 경험"**: AWS 경험만으로는 부족하다. Azure 특유의 개념(Resource Group, AAD, Azure Policy, Managed Identity)을 이해하고 있음을 보여야 한다.

---
**핵심 키워드**: `VNET` `AKS` `Azure CNI` `AAD` `Managed Identity` `NSG` `Azure Policy` `Key Vault` `ACR` `Azure Advisor` `Spot VM` `Budget Alert` `Resource Group`
