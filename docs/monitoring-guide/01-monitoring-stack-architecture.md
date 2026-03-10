# Section 1: 모니터링 스택 아키텍처

## 1.1 클러스터 인프라 현황

### 노드 사양

| 항목 | 사양 | 비고 |
|------|------|------|
| CPU | 96 Core | 물리 코어 기준 |
| Memory | 1 TB | ECC DRAM |
| Storage | NVMe 4 TB | Local PV 전용, 고성능 랜덤 I/O |
| 공용 네트워크 (bond0) | 25G + 25G LACP | Public 트래픽 (Grafana, Dashboards 등) |
| 사설 네트워크 (bond1) | 25G + 25G LACP | Private 트래픽 (Prometheus, OpenSearch 등) |
| 운영체제 | [OS 및 커널 버전 기재] | - |
| 쿠버네티스 버전 | [K8s 버전 기재] | - |
| 컨테이너 런타임 | [Runtime 및 버전 기재] | - |

### 네트워크 구성도

```
┌──────────────────────────────────────────────────────────────────────┐
│                          운영 클러스터 노드                            │
│                                                                      │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐  │
│  │   bond0 (Public Network) │  │    bond1 (Private Network)       │  │
│  │   25G + 25G  LACP        │  │    25G + 25G  LACP               │  │
│  │                          │  │                                  │  │
│  │  ┌─────────┐ ┌─────────┐ │  │  ┌──────────┐  ┌─────────────┐  │  │
│  │  │  eth0   │ │  eth1   │ │  │  │  eth2    │  │   eth3      │  │  │
│  │  │  25GbE  │ │  25GbE  │ │  │  │  25GbE   │  │   25GbE     │  │  │
│  │  └────┬────┘ └────┬────┘ │  │  └────┬─────┘  └──────┬──────┘  │  │
│  │       └─────┬─────┘      │  │       └────────┬───────┘         │  │
│  │          bond0            │  │             bond1                │  │
│  │     (Active-Active)       │  │         (Active-Active)          │  │
│  └──────────┬───────────────┘  └─────────────┬────────────────────┘  │
│             │                                │                       │
│   ┌─────────▼──────────────┐   ┌─────────────▼──────────────────┐   │
│   │   Public 서비스 바인딩  │   │    Private 서비스 바인딩         │   │
│   │  - Grafana :3000       │   │   - Prometheus     :9090        │   │
│   │  - OpenSearch          │   │   - Alertmanager   :9093        │   │
│   │    Dashboards :5601    │   │   - OpenSearch     :9200/:9300  │   │
│   └────────────────────────┘   │   - Fluent Bit     :2020        │   │
│                                │   - k8sAlert       :8080        │   │
│                                │   - node-exporter  :9100        │   │
│                                │   - kube-state-m   :8080        │   │
│                                └────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
                │ bond0                          │ bond1
     ┌──────────▼────────┐           ┌───────────▼───────────┐
     │  Public L3 Switch │           │   Private L3 Switch   │
     │  (External Access)│           │   (Cluster Internal)  │
     └───────────────────┘           └───────────────────────┘
```

### 컴포넌트별 네트워크 바인딩

| 컴포넌트 | 네트워크 인터페이스 | 포트 | 바인딩 이유 |
|----------|-------------------|------|-------------|
| Grafana | bond0 (Public) | 3000 | 개발자/운영자 외부 대시보드 접근 |
| OpenSearch Dashboards | bond0 (Public) | 5601 | 로그 조회 외부 접근 |
| Prometheus | bond1 (Private) | 9090 | 내부 메트릭 수집, 외부 노출 불필요 |
| Alertmanager | bond1 (Private) | 9093 | 내부 알림 처리, 외부 노출 불필요 |
| OpenSearch (HTTP) | bond1 (Private) | 9200 | 클러스터 내부 API 통신 |
| OpenSearch (Transport) | bond1 (Private) | 9300 | OpenSearch 노드 간 내부 통신 |
| Fluent Bit | bond1 (Private) | 2020 | 노드 내 로그 수집, 내부 전송 |
| k8sAlert | bond1 (Private) | 8080 | Alertmanager Webhook 수신 (내부) |
| node-exporter | bond1 (Private) | 9100 | Prometheus scrape 전용 (내부) |
| kube-state-metrics | bond1 (Private) | 8080 | Prometheus scrape 전용 (내부) |

### Local PV 구성 현황

| PV명 | 노드 | NVMe 경로 | 용량 | 할당 컴포넌트 | 스토리지 클래스 |
|------|------|-----------|------|---------------|----------------|
| pv-prometheus-[node] | [노드명] | `/dev/nvme0n1p1` | 500 Gi | Prometheus TSDB | local-storage |
| pv-alertmanager-[node] | [노드명] | `/dev/nvme0n1p2` | 50 Gi | Alertmanager 데이터 | local-storage |
| pv-grafana-[node] | [노드명] | `/dev/nvme0n1p3` | 50 Gi | Grafana 대시보드/플러그인 | local-storage |
| pv-opensearch-master-[node] | [노드명] | `/dev/nvme0n1p4` | 200 Gi | OpenSearch Master 노드 | local-storage |
| pv-opensearch-hot-[node] | [노드명] | `/dev/nvme0n1p5` | 2 Ti | OpenSearch Hot 노드 (최신 로그) | local-storage |
| pv-opensearch-cold-[node] | [노드명] | `/dev/nvme0n1p6` | 1 Ti | OpenSearch Cold 노드 (보관 로그) | local-storage |
| pv-opensearch-dash-[node] | [노드명] | `/dev/nvme0n1p7` | 50 Gi | OpenSearch Dashboards | local-storage |

> **참고**: NVMe 경로 및 파티션 정보는 실제 노드 구성에 맞게 수정 필요. `lsblk`, `pvs` 명령으로 확인.

---

## 1.2 모니터링 스택 전체 아키텍처

### 3개 파이프라인 통합 구성도

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                     운영 클러스터 모니터링 스택 전체 구성                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

  ┌───────────────────────────────────────────────────────────────────────────┐
  │                         애플리케이션 / 시스템                               │
  │  [App Pod]  [System Service]  [K8s Component]  [Node OS]                 │
  └──────┬────────────┬──────────────────┬────────────────┬──────────────────┘
         │ /metrics   │ 로그 (stdout)     │ /metrics       │ Node 메트릭
         │            │                  │                │
  ═══════╪════════════╪══════════════════╪════════════════╪══════ METRIC PIPELINE
         │            │                  │                │
  ┌──────▼──────┐     │        ┌─────────▼──────────────┐ │
  │ServiceMonitor│     │        │  kube-prometheus-stack  │ │
  │    (CR)      │     │        │  ┌─────────────────┐   │ │
  └──────┬───────┘     │        │  │   Prometheus    │◄──┘ │
         └─────────────┼────────►  │  (단일 인스턴스) │     │
                       │        │  └────────┬────────┘     │
                       │        │           │  ┌──────────┐ │
                       │        │           │  │ Grafana  │ │
                       │        │           │  └──────────┘ │
                       │        └───────────┼───────────────┘
                       │                    │
  ═════════════════════╪════════════════════╪═════════════════ LOG PIPELINE
                       │                    │
  ┌────────────────────▼──────┐             │
  │  Fluent Bit (DaemonSet)   │             │
  │  [Operator CR 기반 설정]  │             │
  └───────────┬───────────────┘             │
              │                             │
  ┌───────────▼───────────────────────────┐ │
  │       Fluent Bit Operator             │ │
  │  ClusterInput / ClusterFilter /       │ │
  │  ClusterOutput / FluentBitConfig (CR) │ │
  └───────────┬───────────────────────────┘ │
              │                             │
  ┌───────────▼───────────────────────────┐ │
  │           OpenSearch 클러스터          │ │
  │  [Master] [Hot Node] [Cold Node]      │ │
  └───────────┬───────────────────────────┘ │
              │                             │
  ┌───────────▼───────────────────────────┐ │
  │       OpenSearch Dashboards            │ │
  └───────────────────────────────────────┘ │
                                            │
  ══════════════════════════════════════════╪═══════════════ ALERT PIPELINE
                                            │
  ┌──────────────────┐          ┌───────────▼──────────────┐
  │ PrometheusRule   │          │       Alertmanager        │
  │     (CR)         ├─────────►│  (그룹화 / 억제 / 라우팅) │
  └──────────────────┘          └───────────┬──────────────┘
                                            │
                               ┌────────────▼──────────────┐
                               │    k8sAlert (Custom)       │
                               │  Webhook 수신 + 가공       │
                               └────────────┬──────────────┘
                                            │
                          ┌─────────────────┼──────────────────┐
                          │                 │                  │
                   ┌──────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐
                   │   메신저     │  │   이메일      │  │  기타 채널   │
                   │ (Slack 등)  │  │  (SMTP)      │  │             │
                   └─────────────┘  └──────────────┘  └─────────────┘

  ════════════════════════════════════════════════════════════════════ GITOPS
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  ArgoCD (App of Apps)  ←─────  Bitbucket (Git 저장소)                   │
  │  └── monitoring-apps                                                     │
  │       ├── kube-prometheus-stack (Helm + Kustomize)                       │
  │       ├── fluent-bit-operator   (Helm + Kustomize)                       │
  │       ├── opensearch            (Helm + Kustomize)                       │
  │       └── alertmanager-config   (Kustomize)                              │
  │                     ↑ 이미지/차트 Pull                                   │
  │                 Nexus Registry (Helm Chart Proxy / Image Mirror)         │
  └──────────────────────────────────────────────────────────────────────────┘
```

### 전체 컴포넌트 목록 및 역할

| 컴포넌트 | 역할 | 네임스페이스 | 버전 | 배포 방식 |
|----------|------|-------------|------|-----------|
| Prometheus | 메트릭 수집 및 시계열 저장 (단일 인스턴스) | monitoring | [버전 기재] | Helm (kube-prometheus-stack) |
| Alertmanager | 알림 그룹화/억제/라우팅 | monitoring | [버전 기재] | Helm (kube-prometheus-stack) |
| Grafana | 메트릭 시각화 대시보드 | monitoring | [버전 기재] | Helm (kube-prometheus-stack) |
| kube-state-metrics | 쿠버네티스 오브젝트 상태 메트릭 수출 | monitoring | [버전 기재] | Helm (kube-prometheus-stack) |
| node-exporter | 노드 OS/HW 메트릭 수출 (DaemonSet) | monitoring | [버전 기재] | Helm (kube-prometheus-stack) |
| Fluent Bit Operator | Fluent Bit CR 관리 컨트롤러 | fluent-bit | [버전 기재] | Helm |
| Fluent Bit | 로그 수집 에이전트 (DaemonSet) | fluent-bit | [버전 기재] | Fluent Bit Operator 관리 |
| OpenSearch | 분산 로그 검색/저장 엔진 | opensearch | [버전 기재] | Helm |
| OpenSearch Dashboards | 로그 시각화 UI | opensearch | [버전 기재] | Helm |
| k8sAlert | Alertmanager Webhook 수신 및 알림 전달 | monitoring | [버전 기재] | Kustomize (사내 이미지) |
| ArgoCD | GitOps CD 컨트롤러 | argocd | [버전 기재] | Helm |
| ArgoCD App of Apps | 모니터링 스택 최상위 ArgoCD Application | argocd | - | Kustomize |

---

## 1.3 Metric 파이프라인 아키텍처

### 파이프라인 구성도

```
┌─────────────────────────────────────────────────────────────────────┐
│                      METRIC PIPELINE                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  수집 대상                   수집 설정              저장 / 시각화   │
│  ──────────                  ──────────              ─────────────  │
│                                                                     │
│  ┌───────────────┐                                                  │
│  │  애플리케이션  │──/metrics──►┌─────────────────┐               │
│  │   Pod         │             │ ServiceMonitor  │               │
│  └───────────────┘             │     (CR)        │               │
│                                │ namespace:      │               │
│  ┌───────────────┐             │   monitoring    │               │
│  │  K8s 시스템   │──/metrics──►│ labelSelector:  ├─────────────┐ │
│  │  컴포넌트     │             │   release:kps   │             │ │
│  └───────────────┘             └─────────────────┘             │ │
│                                                                 ▼ │
│  ┌───────────────┐             ┌─────────────────┐   ┌──────────────────┐│
│  │  node-exporter│──/metrics──►│ kube-state-     │   │   Prometheus     ││
│  │  (DaemonSet)  │             │ metrics         │──►│  (단일 인스턴스)  ││
│  └───────────────┘             └─────────────────┘   │  TSDB 저장       ││
│                                                       │  Local PV        ││
│  ┌───────────────┐                                    └────────┬─────────┘│
│  │  kube-state-  │──/metrics──────────────────────────────────┘          │
│  │  metrics      │                                             │          │
│  └───────────────┘                                             │          │
│                                                                ▼          │
│                                              ┌─────────────────────────┐  │
│                                              │        Grafana          │  │
│                                              │  DataSource: Prometheus │  │
│                                              │  bond0 (Public) :3000   │  │
│                                              └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### kube-prometheus-stack 컴포넌트 구성

| 컴포넌트 | 배포 형태 | 복제본 수 | 스토리지 | 주요 설정 |
|----------|-----------|-----------|----------|-----------|
| Prometheus | StatefulSet | 1 (단일 인스턴스) | Local PV 500Gi | Retention: [보관기간 기재], scrapeInterval: 30s |
| Alertmanager | StatefulSet | [복제본 수 기재] | Local PV 50Gi | Cluster 구성 여부 확인 |
| Grafana | Deployment | 1 | Local PV 50Gi | bond0 바인딩, Admin 계정 별도 관리 |
| kube-state-metrics | Deployment | 1 | 없음 (메모리) | 쿠버네티스 API 서버 접근 필요 |
| node-exporter | DaemonSet | 노드 수 | 없음 | 전체 노드 메트릭 수집 |
| Prometheus Operator | Deployment | 1 | 없음 | CR 감시 및 설정 동기화 |

### ServiceMonitor CR 관리 전략

| 항목 | 규칙 | 예시 |
|------|------|------|
| 네이밍 규칙 | `{앱명}-servicemonitor` | `myapp-servicemonitor` |
| 네임스페이스 | 앱과 동일 네임스페이스 배치 | `namespace: my-namespace` |
| 라벨 (필수) | `release: kube-prometheus-stack` | Prometheus ServiceMonitor selector 매칭 |
| 라벨 (권장) | `app: {앱명}`, `team: {팀명}` | 관리 편의성 |
| 수집 주기 (기본) | `interval: 30s` | 표준 수집 주기 |
| 수집 주기 (고빈도) | `interval: 15s` | 고빈도 알림 필요 컴포넌트 |
| 수집 주기 (저빈도) | `interval: 60s` | 변화 적은 인프라 메트릭 |
| TLS 설정 | `scheme: https` + `tlsConfig` | 내부 CA 인증서 사용 시 |
| 인증 설정 | `basicAuth` 또는 `bearerTokenSecret` | 인증 필요 엔드포인트 |
| 경로 기본값 | `path: /metrics` | 변경 시 명시 필요 |

---

## 1.4 Log 파이프라인 아키텍처

### 파이프라인 구성도

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          LOG PIPELINE                                    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  로그 소스                수집/처리                   저장/시각화         │
│  ──────────              ──────────                  ─────────────       │
│                                                                          │
│  ┌──────────────┐   tail  ┌──────────────────────────────────────────┐  │
│  │ 컨테이너 로그 ├────────►│           Fluent Bit (DaemonSet)         │  │
│  │ /var/log/... │         │                                          │  │
│  └──────────────┘         │  설정: FluentBitConfig (CR) 기반         │  │
│                           │  ┌───────────┐  ┌───────────────────┐   │  │
│  ┌──────────────┐         │  │ClusterInput│  │ ClusterFilter     │   │  │
│  │ systemd 로그  ├────────►│  │  (CR)     │─►│   (CR)            │   │  │
│  │ journald     │  systemd│  │ - tail    │  │ - kubernetes      │   │  │
│  └──────────────┘         │  │ - systemd │  │   metadata        │   │  │
│                           │  └───────────┘  │ - parser          │   │  │
│  ┌──────────────┐         │                 │ - grep/modify     │   │  │
│  │ 노드 OS 로그  ├────────►│                 └────────┬──────────┘   │  │
│  │ /var/log/... │  tail   │                          │              │  │
│  └──────────────┘         │                 ┌────────▼──────────┐   │  │
│                           │                 │  ClusterOutput    │   │  │
│                           │                 │     (CR)          │   │  │
│                           │                 │  - OpenSearch     │   │  │
│                           │                 └────────┬──────────┘   │  │
│                           └──────────────────────────┼──────────────┘  │
│                                                       │                 │
│                           ┌───────────────────────────▼──────────────┐  │
│                           │       Fluent Bit Operator                 │  │
│                           │  FluentBit CR (DaemonSet 생명주기 관리)   │  │
│                           │  FluentBitConfig CR (설정 조합/적용)      │  │
│                           └───────────────────────────┬──────────────┘  │
│                                                       │                 │
│                           ┌───────────────────────────▼──────────────┐  │
│                           │         OpenSearch 클러스터               │  │
│                           │  ┌─────────┐ ┌─────────┐ ┌──────────┐  │  │
│                           │  │ Master  │ │Hot Node │ │Cold Node │  │  │
│                           │  │ (3노드) │ │(NVMe)   │ │(NVMe)   │  │  │
│                           │  └─────────┘ └─────────┘ └──────────┘  │  │
│                           │     ISM 정책 (Index Lifecycle 자동화)    │  │
│                           └───────────────────────────┬──────────────┘  │
│                                                       │                 │
│                           ┌───────────────────────────▼──────────────┐  │
│                           │       OpenSearch Dashboards               │  │
│                           │      bond0 (Public) :5601                 │  │
│                           └──────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

### Fluent Bit Operator CR 계층 구성

| CR 종류 | 역할 | 적용 범위 | 주요 설정 예시 |
|---------|------|-----------|----------------|
| FluentBit | Fluent Bit DaemonSet 자체 정의 (이미지, 리소스, 마운트 등) | 클러스터 전체 | image, resources, tolerations, volumeMounts |
| FluentBitConfig | 여러 CR을 조합하여 최종 Fluent Bit 설정 파일 생성 | FluentBit CR 참조 | inputSelector, filterSelector, outputSelector |
| ClusterInput | 로그 입력 소스 정의 (클러스터 전체 범위) | 네임스페이스 무관 | plugin: tail, path: /var/log/containers/*.log |
| ClusterFilter | 로그 파싱 및 변환 규칙 정의 | 네임스페이스 무관 | plugin: kubernetes (메타데이터 추가), parser, grep |
| ClusterOutput | 로그 출력 대상 정의 | 네임스페이스 무관 | plugin: opensearch, host, port, index |
| Input | 로그 입력 소스 (특정 네임스페이스 범위) | 특정 네임스페이스 | 네임스페이스별 격리 수집 시 사용 |
| Filter | 로그 필터 (특정 네임스페이스 범위) | 특정 네임스페이스 | 네임스페이스별 격리 처리 시 사용 |
| Output | 로그 출력 (특정 네임스페이스 범위) | 특정 네임스페이스 | 네임스페이스별 다른 대상 출력 시 사용 |

### OpenSearch 클러스터 구성

| 노드 역할 | 복제본 수 | 주요 기능 | 스토리지 | 리소스 (권장) |
|----------|-----------|-----------|----------|---------------|
| Master | 3 | 클러스터 상태 관리, 샤드 배분, 리더 선출 | Local PV 200Gi | CPU: 4, Mem: 16Gi |
| Hot Node (Data) | [노드 수 기재] | 최신 로그 인덱싱/검색 (고성능 NVMe) | Local PV 2Ti/노드 | CPU: 16, Mem: 64Gi |
| Cold Node (Data) | [노드 수 기재] | 보관 로그 저장 (ISM 정책으로 이동) | Local PV 1Ti/노드 | CPU: 8, Mem: 32Gi |
| Dashboards | 1 | OpenSearch UI 서빙 | Local PV 50Gi | CPU: 2, Mem: 4Gi |
| Coordinator | [선택 사항] | 검색 요청 분산 라우팅 | 없음 | CPU: 4, Mem: 16Gi |

### 인덱스 네이밍 규칙

| 인덱스 유형 | 네이밍 형식 | 예시 | 보관 정책 |
|------------|------------|------|-----------|
| 애플리케이션 로그 | `app-{cluster}-YYYY.MM.DD` | `app-prod-2024.03.10` | Hot 7일 → Cold 30일 → 삭제 |
| 시스템 로그 | `sys-{cluster}-YYYY.MM.DD` | `sys-prod-2024.03.10` | Hot 3일 → Cold 14일 → 삭제 |
| 인프라 로그 | `infra-{cluster}-YYYY.MM.DD` | `infra-prod-2024.03.10` | Hot 3일 → Cold 14일 → 삭제 |
| 보안 감사 로그 | `audit-{cluster}-YYYY.MM.DD` | `audit-prod-2024.03.10` | Hot 7일 → Cold 90일 → 삭제 |
| 이벤트 로그 | `event-{cluster}-YYYY.MM.DD` | `event-prod-2024.03.10` | Hot 3일 → Cold 7일 → 삭제 |

> **ISM 정책 적용**: 각 인덱스 유형별로 OpenSearch ISM 정책을 정의하여 Hot → Cold → 삭제 전환을 자동화.
> ISM 정책 상세 내용은 `docs/opensearch-index-management/` 참조.

---

## 1.5 Alert 파이프라인 아키텍처

### 파이프라인 구성도

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         ALERT PIPELINE                                   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  규칙 정의           평가/발생               처리/라우팅    최종 전달     │
│  ──────────          ──────────              ──────────     ──────────   │
│                                                                          │
│  ┌─────────────┐     ┌────────────────────┐                             │
│  │PrometheusRule│────►│     Prometheus     │                             │
│  │   (CR)      │     │                    │                             │
│  │ - 알림 조건  │     │  규칙 평가 주기:   │                             │
│  │   (expr)    │     │  [평가주기 기재]   │                             │
│  │ - 심각도    │     │  (예: 1m)          │                             │
│  │   (labels)  │     │                    │                             │
│  │ - 대기시간  │     └──────────┬─────────┘                             │
│  │   (for)     │                │ ALERTS (HTTP)                         │
│  └─────────────┘                ▼                                       │
│                       ┌────────────────────┐                            │
│                       │    Alertmanager     │                            │
│                       │                    │                            │
│                       │  ┌──────────────┐  │                            │
│                       │  │  그룹화      │  │                            │
│                       │  │ (groupBy)    │  │                            │
│                       │  └──────┬───────┘  │                            │
│                       │         │          │                            │
│                       │  ┌──────▼───────┐  │                            │
│                       │  │  억제        │  │                            │
│                       │  │ (inhibit)    │  │                            │
│                       │  └──────┬───────┘  │                            │
│                       │         │          │                            │
│                       │  ┌──────▼───────┐  │                            │
│                       │  │  라우팅      │  │                            │
│                       │  │  (routes)    │  │                            │
│                       │  └──────┬───────┘  │                            │
│                       └─────────┼──────────┘                            │
│                                 │ Webhook                               │
│                                 ▼                                       │
│                       ┌────────────────────┐                            │
│                       │   k8sAlert (Custom) │                            │
│                       │                    │                            │
│                       │  - 알림 포맷 가공  │                            │
│                       │  - 중복 제거       │                            │
│                       │  - 수신 채널 분기  │                            │
│                       └─────────┬──────────┘                            │
│                                 │                                       │
│              ┌──────────────────┼────────────────────────┐             │
│              │                  │                        │             │
│     ┌────────▼───────┐  ┌───────▼────────┐  ┌──────────▼──────────┐  │
│     │  메신저 채널    │  │   이메일        │  │   기타 채널          │  │
│     │  (Slack/Teams) │  │  (SMTP)        │  │  (PagerDuty 등)     │  │
│     └────────────────┘  └────────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 컴포넌트별 역할

| 컴포넌트 | 역할 | 입력 | 출력 | 위치 |
|----------|------|------|------|------|
| PrometheusRule (CR) | 알림 규칙 선언 (GitOps 관리) | PromQL 표현식 + 메타데이터 | Prometheus 규칙 파일 | Git 저장소 → 클러스터 |
| Prometheus | PrometheusRule 주기적 평가, 발화된 알림 전송 | 메트릭 TSDB, PrometheusRule | Alertmanager HTTP API | monitoring 네임스페이스 |
| Alertmanager | 알림 수신, 그룹화, 억제, 라우팅 | Prometheus ALERTS | Webhook (k8sAlert) | monitoring 네임스페이스 |
| k8sAlert | Webhook 수신, 알림 포맷 변환, 채널 전달 | Alertmanager Webhook JSON | 메신저/이메일 API | monitoring 네임스페이스 |

### Alert 라우팅 정책

| Severity | Receiver | 그룹 대기 시간 | 반복 간격 | 억제 규칙 | 발송 채널 |
|----------|----------|---------------|-----------|-----------|-----------|
| critical | critical-receiver | 1m | 1h | warning에 의해 억제되지 않음 | 메신저 + 이메일 + On-Call |
| warning | warning-receiver | 5m | 4h | critical 발생 시 동일 경보 억제 | 메신저 + 이메일 |
| info | info-receiver | 10m | 12h | warning/critical 발생 시 억제 | 메신저 |
| none | null-receiver | - | - | 모든 알림 버림 | 없음 (음소거) |

> **억제 규칙 예시**: 상위 심각도(critical) 알림 발생 시 동일 `alertname`, `namespace`를 가진 하위 심각도(warning) 알림 자동 억제.

---

## 1.6 포트 및 네트워크 구성

| 컴포넌트 | 포트 | 프로토콜 | 바인딩 인터페이스 | 방향 | 설명 |
|----------|------|---------|-----------------|------|------|
| Prometheus | 9090 | TCP/HTTP | bond1 (Private) | 인바운드 | 메트릭 쿼리 API, Alertmanager 연동 |
| Alertmanager | 9093 | TCP/HTTP | bond1 (Private) | 인바운드 | 알림 수신 (Prometheus), UI 접근 |
| Alertmanager | 9094 | TCP | bond1 (Private) | 양방향 | Alertmanager 클러스터 내부 통신 |
| Grafana | 3000 | TCP/HTTP | bond0 (Public) | 인바운드 | 대시보드 UI 접근 (사용자) |
| OpenSearch (HTTP) | 9200 | TCP/HTTP | bond1 (Private) | 인바운드 | REST API, Fluent Bit 로그 전송 |
| OpenSearch (Transport) | 9300 | TCP | bond1 (Private) | 양방향 | OpenSearch 노드 간 클러스터 통신 |
| OpenSearch Dashboards | 5601 | TCP/HTTP | bond0 (Public) | 인바운드 | 로그 조회 UI 접근 (사용자) |
| Fluent Bit (HTTP Server) | 2020 | TCP/HTTP | bond1 (Private) | 인바운드 | 상태 확인 및 메트릭 수집 엔드포인트 |
| k8sAlert | 8080 | TCP/HTTP | bond1 (Private) | 인바운드 | Alertmanager Webhook 수신 |
| node-exporter | 9100 | TCP/HTTP | bond1 (Private) | 인바운드 | Prometheus scrape 대상 |
| kube-state-metrics | 8080 | TCP/HTTP | bond1 (Private) | 인바운드 | Prometheus scrape 대상 |
| kube-state-metrics (Telemetry) | 8081 | TCP/HTTP | bond1 (Private) | 인바운드 | kube-state-metrics 자체 메트릭 |

### 네트워크 정책 요약

| 출발지 | 목적지 | 포트 | 허용 이유 |
|--------|--------|------|-----------|
| Prometheus | node-exporter (모든 노드) | 9100 | 노드 메트릭 수집 |
| Prometheus | kube-state-metrics | 8080 | K8s 오브젝트 메트릭 수집 |
| Prometheus | ServiceMonitor 대상 서비스 | [앱 메트릭 포트] | 애플리케이션 메트릭 수집 |
| Prometheus | Alertmanager | 9093 | 알림 전송 |
| Alertmanager | k8sAlert | 8080 | Webhook 알림 전달 |
| k8sAlert | 외부 메신저/이메일 서버 | 443/25 | 최종 알림 발송 |
| Fluent Bit (DaemonSet) | OpenSearch | 9200 | 로그 데이터 전송 |
| Grafana | Prometheus | 9090 | 메트릭 쿼리 |
| OpenSearch Dashboards | OpenSearch | 9200 | 로그 쿼리 |
| ArgoCD | Bitbucket | 443 | GitOps 동기화 (Git Pull) |
| 클러스터 전체 | Nexus | 443 | Helm Chart / 이미지 Pull |

---

## 1.7 외부 의존성 구성

### 1.7.1 Bitbucket 저장소 구성

| 저장소명 | 용도 | 주요 경로 | 브랜치 전략 | 접근 권한 |
|---------|------|-----------|------------|-----------|
| monitoring-gitops | ArgoCD App of Apps 정의, 최상위 배포 진입점 | `apps/` (Application CRs), `base/`, `overlays/` | main (운영), dev (개발) | ArgoCD 읽기 전용 |
| monitoring-helm-values | 각 Helm Chart의 values.yaml 커스터마이징 | `kube-prometheus-stack/`, `opensearch/`, `fluent-bit/` | main, dev | 운영팀 쓰기, ArgoCD 읽기 |
| monitoring-kustomize | Kustomize 오버레이, CR 매니페스트 (ServiceMonitor, PrometheusRule 등) | `servicemonitors/`, `prometheusrules/`, `fluent-bit-cr/` | main, dev | 운영팀 쓰기, ArgoCD 읽기 |

#### 저장소 구조 예시 (monitoring-gitops)

```
monitoring-gitops/
├── apps/
│   ├── kustomization.yaml          # App of Apps 진입점
│   ├── kube-prometheus-stack.yaml  # ArgoCD Application
│   ├── fluent-bit-operator.yaml    # ArgoCD Application
│   ├── opensearch.yaml             # ArgoCD Application
│   └── k8s-alert.yaml             # ArgoCD Application
├── base/
│   └── argocd-app-template.yaml   # Application 공통 템플릿
└── overlays/
    ├── production/
    │   └── kustomization.yaml
    └── staging/
        └── kustomization.yaml
```

#### 브랜치 보호 정책

| 저장소 | 보호 브랜치 | PR 필수 승인 수 | 강제 푸시 허용 | 비고 |
|--------|-----------|----------------|----------------|------|
| monitoring-gitops | main | 2명 이상 | 불가 | 운영 배포 직접 반영 |
| monitoring-helm-values | main | 1명 이상 | 불가 | Helm values 변경 |
| monitoring-kustomize | main | 1명 이상 | 불가 | CR 매니페스트 변경 |

### 1.7.2 Nexus Registry 구성

#### Helm Chart Proxy

| 저장소명 (Nexus) | 원본 Upstream URL | 프록시 대상 Chart | 캐시 정책 |
|----------------|------------------|-----------------|-----------|
| helm-proxy-prometheus-community | https://prometheus-community.github.io/helm-charts | kube-prometheus-stack | 24h TTL |
| helm-proxy-fluent | https://fluent.github.io/helm-charts | fluent-operator | 24h TTL |
| helm-proxy-opensearch | https://opensearch-project.github.io/helm-charts | opensearch, opensearch-dashboards | 24h TTL |
| helm-proxy-argo | https://argoproj.github.io/argo-helm | argo-cd | 24h TTL |
| helm-hosted-internal | (내부 전용) | 사내 개발 Chart | 무기한 보관 |

#### Container Image Mirror

| 저장소명 (Nexus) | 원본 Registry | 미러링 대상 이미지 | 갱신 주기 |
|----------------|--------------|-----------------|-----------|
| docker-proxy-dockerhub | https://registry-1.docker.io | Prometheus, Grafana, Alertmanager | 요청 시 자동 캐시 |
| docker-proxy-quay | https://quay.io | Fluent Bit Operator, OpenSearch | 요청 시 자동 캐시 |
| docker-proxy-ghcr | https://ghcr.io | kube-state-metrics, node-exporter | 요청 시 자동 캐시 |
| docker-hosted-internal | (내부 전용) | k8sAlert (사내 개발 이미지) | 수동 Push |

#### Nexus 설정 주의사항

| 항목 | 내용 |
|------|------|
| 인증 | 이미지 Pull 시 `imagePullSecret` 필요 (네임스페이스별 생성) |
| TLS | 내부 CA 서명 인증서 사용 시 노드 `/etc/docker/certs.d/` 또는 containerd 설정 필요 |
| 방화벽 | 클러스터 노드 → Nexus 443 포트 허용 필요 |
| 저장 용량 | Nexus 호스트 디스크 여유 공간 주기적 점검 필요 |
| Blob Store | 각 Repository별 Blob Store 분리 권장 (용량 관리 편의) |
