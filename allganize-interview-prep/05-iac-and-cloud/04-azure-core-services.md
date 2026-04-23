# 04. Azure 핵심 서비스 (Azure Core Services)

> **TL;DR**
> - Azure는 VNET/NSG로 네트워크를 격리하고, AKS로 컨테이너를 운영하며, Azure AD(Entra ID)로 모든 인증을 통합한다
> - AWS 경험이 있다면 서비스 매핑(VPC->VNET, IAM->Azure AD)으로 빠르게 Azure를 이해할 수 있다
> - 온프레미스 Active Directory 경험은 Azure AD 통합 설계에서 직접적인 강점이 된다

---

## 1. VNET, NSG, Azure Load Balancer

### 1-1. VNET (Virtual Network)

AWS의 VPC에 대응하는 Azure의 가상 네트워크다.

```
                     [Internet]
                         |
              ┌──────────┴──────────┐
              |   Public Subnet      |
              |   (Azure LB)         |
              |   (Application GW)   |
              |   NSG: Allow 443     |
              └──────────┬──────────┘
                         |
              ┌──────────┴──────────┐
              |   App Subnet         |
              |   (AKS Nodes)        |
              |   NSG: Allow from LB |
              └──────────┬──────────┘
                         |
              ┌──────────┴──────────┐
              |   DB Subnet          |
              |   (Cosmos DB PE)     |
              |   NSG: Allow from App|
              └─────────────────────┘
```

```hcl
# Azure Provider 설정
provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# Resource Group (Azure 고유 개념: 모든 리소스의 논리적 컨테이너)
resource "azurerm_resource_group" "main" {
  name     = "rg-allganize-prod"
  location = "koreacentral"

  tags = {
    Environment = "production"
    Team        = "platform"
    ManagedBy   = "terraform"
  }
}

# VNET 생성
resource "azurerm_virtual_network" "main" {
  name                = "vnet-allganize-prod"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.0.0.0/16"]
}

# 서브넷 (Azure는 서브넷이 VNET의 하위 리소스)
resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_subnet" "db" {
  name                 = "snet-db"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.2.0/24"]

  # Private Endpoint용 서브넷 설정
  private_endpoint_network_policies = "Enabled"
}
```

### 1-2. NSG (Network Security Group)

AWS의 Security Group에 대응하지만, **Stateful이 아닌 규칙 기반**이다.

```hcl
resource "azurerm_network_security_group" "aks" {
  name                = "nsg-aks"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  # 인바운드: HTTPS만 허용
  security_rule {
    name                       = "AllowHTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.0.0/24"  # LB 서브넷
    destination_address_prefix = "10.0.1.0/24"   # AKS 서브넷
  }

  # 인바운드: 나머지 차단
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

# NSG를 서브넷에 연결
resource "azurerm_subnet_network_security_group_association" "aks" {
  subnet_id                 = azurerm_subnet.aks.id
  network_security_group_id = azurerm_network_security_group.aks.id
}
```

### 1-3. Azure Load Balancer

| 구분 | Azure Load Balancer (L4) | Application Gateway (L7) |
|------|-------------------------|--------------------------|
| 프로토콜 | TCP/UDP | HTTP/HTTPS |
| AWS 대응 | NLB | ALB |
| WAF | 미지원 | 지원 (WAF v2) |
| SSL 종료 | 미지원 | 지원 |
| 사용 사례 | TCP 부하 분산 | 웹 애플리케이션 |

```hcl
# 내부 로드 밸런서 (Internal LB)
resource "azurerm_lb" "internal" {
  name                = "lb-allganize-internal"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Standard"

  frontend_ip_configuration {
    name                          = "internal-frontend"
    subnet_id                     = azurerm_subnet.aks.id
    private_ip_address_allocation = "Static"
    private_ip_address            = "10.0.1.100"
  }
}
```

---

## 2. AKS (Azure Kubernetes Service)

### 2-1. AKS 클러스터 생성

```hcl
resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-allganize-prod"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = "allganize-prod"
  kubernetes_version  = "1.29"

  # 기본 노드 풀 (System Pool)
  default_node_pool {
    name                = "system"
    node_count          = 3
    vm_size             = "Standard_D4s_v3"  # 4vCPU, 16GB
    vnet_subnet_id      = azurerm_subnet.aks.id
    os_disk_size_gb     = 100
    max_pods            = 50
    zones               = [1, 2, 3]  # 가용 영역 분산

    node_labels = {
      "nodepool-type" = "system"
    }
  }

  # Azure AD 통합
  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = var.tenant_id
  }

  # Managed Identity (서비스 주체 대신 권장)
  identity {
    type = "SystemAssigned"
  }

  # 네트워크 설정 (Azure CNI)
  network_profile {
    network_plugin    = "azure"      # Azure CNI (Pod에 VNET IP 직접 할당)
    network_policy    = "calico"     # 네트워크 정책 엔진
    load_balancer_sku = "standard"
    service_cidr      = "172.16.0.0/16"
    dns_service_ip    = "172.16.0.10"
  }

  # 모니터링 연동
  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }
}
```

### 2-2. Node Pool 관리

```hcl
# 사용자 워크로드용 노드 풀 (User Pool)
resource "azurerm_kubernetes_cluster_node_pool" "worker" {
  name                  = "worker"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = "Standard_D8s_v3"  # 8vCPU, 32GB
  node_count            = 3
  min_count             = 2
  max_count             = 20
  enable_auto_scaling   = true
  vnet_subnet_id        = azurerm_subnet.aks.id
  zones                 = [1, 2, 3]

  node_labels = {
    "nodepool-type" = "worker"
    "workload"      = "allganize-app"
  }

  node_taints = []  # Taint 없음 -> 일반 워크로드 스케줄링
}

# GPU 노드 풀 (AI/ML 워크로드용)
resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  name                  = "gpu"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = "Standard_NC6s_v3"  # Tesla V100
  node_count            = 0
  min_count             = 0
  max_count             = 4
  enable_auto_scaling   = true
  vnet_subnet_id        = azurerm_subnet.aks.id

  node_labels = {
    "nodepool-type"          = "gpu"
    "nvidia.com/gpu.present" = "true"
  }

  node_taints = [
    "nvidia.com/gpu=present:NoSchedule"  # GPU 요청하는 Pod만 스케줄링
  ]
}
```

### 2-3. Azure AD (Entra ID) 통합

AKS와 Azure AD를 통합하면 **쿠버네티스 RBAC를 Azure AD 그룹으로 관리**할 수 있다.

```yaml
# Azure AD 그룹 기반 ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: platform-admins
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: Group
    name: "00000000-0000-0000-0000-000000000000"  # Azure AD 그룹 Object ID
    apiGroup: rbac.authorization.k8s.io
```

> **폐쇄망 경험 연결:** 온프레미스에서 Active Directory를 운영한 경험이 있다면, Azure AD와의 통합, 하이브리드 ID(Hybrid Identity) 구성, 조건부 액세스(Conditional Access) 설계에서 강점이 된다.

---

## 3. Blob Storage와 Cosmos DB

### 3-1. Azure Blob Storage

AWS S3에 대응하는 오브젝트 스토리지다.

```hcl
resource "azurerm_storage_account" "main" {
  name                     = "stallganizeprod"  # 전역 고유, 소문자+숫자만
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "GRS"  # Geo-Redundant Storage (지역 간 복제)
  min_tls_version          = "TLS1_2"

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30  # 삭제 후 30일간 복구 가능
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  network_rules {
    default_action = "Deny"
    ip_rules       = []
    virtual_network_subnet_ids = [azurerm_subnet.aks.id]
  }
}

# Blob 컨테이너 (S3 Bucket에 대응)
resource "azurerm_storage_container" "data" {
  name                  = "allganize-data"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}
```

### 3-2. Azure Blob vs AWS S3 비교

| 구분 | AWS S3 | Azure Blob |
|------|--------|------------|
| 최상위 단위 | Bucket | Storage Account |
| 하위 단위 | (접두사 기반) | Container |
| 접근 티어 | Standard/IA/Glacier | Hot/Cool/Cold/Archive |
| 복제 옵션 | Cross-Region Replication | LRS/ZRS/GRS/GZRS |
| 정적 웹 호스팅 | S3 Website | Static Website |

### 3-3. Cosmos DB

글로벌 분산 NoSQL 데이터베이스(AWS DynamoDB에 대응하지만 다중 API 지원).

```hcl
resource "azurerm_cosmosdb_account" "main" {
  name                = "cosmos-allganize-prod"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # 자동 장애 조치 (Automatic Failover)
  automatic_failover_enabled = true

  consistency_policy {
    consistency_level = "Session"  # 가장 널리 사용되는 일관성 수준
  }

  geo_location {
    location          = "koreacentral"
    failover_priority = 0  # Primary
  }

  geo_location {
    location          = "japaneast"
    failover_priority = 1  # Secondary
  }

  # Private Endpoint로만 접근 허용
  is_virtual_network_filter_enabled = true
  public_network_access_enabled     = false
}

# SQL API Database
resource "azurerm_cosmosdb_sql_database" "main" {
  name                = "allganize-db"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name

  autoscale_settings {
    max_throughput = 4000  # 자동 스케일링 (400~4000 RU/s)
  }
}
```

**Cosmos DB 일관성 수준 (Consistency Levels):**

```
Strong  >  Bounded Staleness  >  Session  >  Consistent Prefix  >  Eventual
강한 일관성                      (기본/권장)                       최종 일관성
높은 지연시간                                                   낮은 지연시간
```

---

## 4. Azure AD (Entra ID)와 Managed Identity

### 4-1. Azure AD 핵심 개념

| 개념 | AWS 대응 | 설명 |
|------|---------|------|
| Tenant | Account (Organization) | Azure AD의 최상위 단위 |
| Subscription | Account | 과금 및 리소스 경계 |
| Resource Group | (없음) | 리소스의 논리적 그룹 |
| Azure AD User/Group | IAM User/Group | 사용자/그룹 관리 |
| Service Principal | IAM Role | 애플리케이션용 ID |
| Managed Identity | IRSA (유사) | Azure 리소스에 자동 부여되는 ID |
| RBAC Role | IAM Policy | 권한 정의 |

### 4-2. Managed Identity

Azure 리소스에 **자동으로 부여되는 ID**로, 자격 증명(Credential)을 코드에 포함하지 않아도 된다.

```hcl
# System-assigned Managed Identity (리소스와 생명주기 동일)
resource "azurerm_kubernetes_cluster" "main" {
  # ... (생략)
  identity {
    type = "SystemAssigned"
  }
}

# User-assigned Managed Identity (독립적 생명주기)
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-allganize-app"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

# Managed Identity에 역할 할당
resource "azurerm_role_assignment" "app_storage_reader" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}
```

### 4-3. AKS Workload Identity (IRSA의 Azure 버전)

```hcl
# AKS에서 Workload Identity 활성화
resource "azurerm_kubernetes_cluster" "main" {
  # ... (생략)
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
}

# Federated Credential 설정
resource "azurerm_federated_identity_credential" "app" {
  name                = "fed-allganize-app"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.app.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject             = "system:serviceaccount:allganize:app-sa"
}
```

```yaml
# 쿠버네티스 ServiceAccount에 Managed Identity 연결
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: allganize
  annotations:
    azure.workload.identity/client-id: "<MANAGED_IDENTITY_CLIENT_ID>"
  labels:
    azure.workload.identity/use: "true"
```

---

## 5. Azure Monitor와 Application Insights

### 5-1. Azure Monitor 아키텍처

```
[Azure Resources]
      |
  [Diagnostic Settings]
      |
  ┌───┴────────────────┐
  |  Log Analytics      |  <-- 로그/메트릭 통합 저장소
  |  Workspace          |      KQL(Kusto Query Language)로 분석
  └───┬────────────────┘
      |
  ┌───┴────┐  ┌──────────────────┐
  | Alerts  |  | Application      |
  | (경보)  |  | Insights (APM)   |
  └────────┘  └──────────────────┘
```

```hcl
# Log Analytics Workspace
resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-allganize-prod"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 90
}

# 경보 규칙 (Alert Rule)
resource "azurerm_monitor_metric_alert" "aks_cpu" {
  name                = "alert-aks-high-cpu"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_kubernetes_cluster.main.id]
  description         = "AKS 노드 CPU 사용률 80% 초과"
  severity            = 2
  frequency           = "PT5M"    # 5분마다 평가
  window_size         = "PT15M"   # 15분 윈도우

  criteria {
    metric_namespace = "Insights.Container/nodes"
    metric_name      = "cpuUsagePercentage"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 80
  }

  action {
    action_group_id = azurerm_monitor_action_group.platform_team.id
  }
}
```

### 5-2. Application Insights

애플리케이션 성능 모니터링(APM) 서비스다 (AWS X-Ray에 대응).

```hcl
resource "azurerm_application_insights" "main" {
  name                = "appi-allganize-prod"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
}

output "instrumentation_key" {
  value     = azurerm_application_insights.main.instrumentation_key
  sensitive = true
}

output "connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}
```

### 5-3. KQL (Kusto Query Language) 예시

```kusto
// AKS Pod 재시작 횟수 상위 10개
KubePodInventory
| where TimeGenerated > ago(24h)
| where ClusterName == "aks-allganize-prod"
| summarize RestartCount = max(PodRestartCount) by Name, Namespace
| top 10 by RestartCount desc

// 5xx 에러 발생 추이
requests
| where timestamp > ago(1h)
| where resultCode startswith "5"
| summarize count() by bin(timestamp, 5m), operation_Name
| render timechart
```

> **폐쇄망 경험 연결:** 온프레미스에서 ELK Stack이나 Prometheus+Grafana로 모니터링을 구축한 경험이 있다면, Azure Monitor의 아키텍처(Log Analytics = Elasticsearch, KQL = Kibana 쿼리, Alerts = AlertManager)를 빠르게 이해할 수 있다.

---

## 면접 Q&A

### Q1. "AWS와 Azure의 네트워크 설계에서 가장 큰 차이는?"

> **이렇게 대답한다:**
> 구조적으로 가장 큰 차이는 **Resource Group** 개념입니다. Azure는 모든 리소스가 Resource Group에 속해야 하며, 이것이 리소스 관리와 RBAC의 기본 단위가 됩니다. 네트워크 측면에서는 Azure의 NSG가 서브넷과 NIC 양쪽에 연결할 수 있다는 점, 그리고 Azure CNI가 Pod에 VNET IP를 직접 할당하여 네트워크 정책이 더 직관적이라는 점이 다릅니다. AWS는 Security Group이 Stateful인 반면, Azure NSG는 명시적으로 인바운드/아웃바운드 규칙을 모두 정의해야 합니다.

### Q2. "AKS에서 Azure AD 통합은 왜 중요한가요?"

> **이렇게 대답한다:**
> 엔터프라이즈 환경에서는 사용자 인증을 **중앙에서 통합 관리**하는 것이 필수입니다. Azure AD 통합을 하면 kubeconfig에 개인 인증서를 넣는 대신, Azure AD 자격 증명으로 `kubectl`을 사용합니다. 조건부 액세스(Conditional Access)로 MFA 강제, 특정 네트워크에서만 접근 허용 등의 정책도 적용할 수 있습니다. 온프레미스에서 Active Directory로 서버 접근을 관리한 경험이 있다면, 이 개념이 그대로 확장된 것입니다.

### Q3. "Managed Identity와 Service Principal의 차이는?"

> **이렇게 대답한다:**
> **Service Principal**은 애플리케이션용 ID로, Client ID + Client Secret(또는 인증서)을 직접 관리해야 합니다. 시크릿 만료, 로테이션 관리가 필요합니다. **Managed Identity**는 Azure가 자동으로 자격 증명을 생성하고 로테이션하며, 코드에 시크릿을 포함할 필요가 없습니다. AWS의 IRSA와 유사한 개념으로, 가능한 한 Managed Identity를 사용하는 것이 보안 모범 사례입니다.

### Q4. "Cosmos DB를 선택하는 기준은?"

> **이렇게 대답한다:**
> Cosmos DB는 세 가지 상황에서 선택합니다. 첫째, **글로벌 분산이 필요할 때** - 멀티 리전 쓰기(Multi-Region Write)를 네이티브로 지원합니다. 둘째, **다중 데이터 모델이 필요할 때** - SQL, MongoDB, Cassandra, Gremlin API를 하나의 서비스로 지원합니다. 셋째, **SLA가 극도로 높아야 할 때** - 99.999% 가용성 SLA를 제공합니다. 다만, RU(Request Unit) 기반 과금이므로 비용 예측과 최적화가 중요합니다.

### Q5. "Azure Monitor에서 KQL을 사용해본 경험이 있나요?"

> **이렇게 대답한다:**
> KQL은 파이프라인 기반 쿼리 언어로, Linux의 `|` (파이프)와 유사한 구조입니다. `테이블 | where 조건 | summarize 집계 | render 시각화` 패턴으로 작성합니다. 온프레미스에서 ELK Stack의 Kibana 쿼리나 Splunk SPL을 사용한 경험이 있다면 KQL은 빠르게 익힐 수 있습니다. 주요 활용 사례는 Pod 재시작 추적, 에러율 분석, 노드 리소스 사용량 트렌드 파악 등입니다.

---

**핵심 키워드 5선:**
`VNET/NSG 네트워크 격리`, `AKS + Azure AD 통합`, `Managed Identity (관리 ID)`, `Cosmos DB 글로벌 분산`, `Azure Monitor + KQL`
