# Kubernetes 클러스터 모니터링 구축 운영 문서

**운영 클러스터 배포를 위한 작업 준비 · 절차 · 점검 가이드**

---

본 문서 세트는 운영 클러스터에 Metric/Log/Alert 모니터링 스택을 배포하고 안정적으로 운영하기 위한 전 과정을 다룹니다.
ArgoCD GitOps 방식으로 배포되는 kube-prometheus-stack, Fluent Bit Operator, OpenSearch, k8sAlert 컴포넌트의 설치부터 일상 운영까지 단계별로 기술합니다.
각 섹션은 독립적으로 참조할 수 있으나, 신규 배포 시에는 Section 0부터 순서대로 진행하십시오.

---

## 인프라 사양 요약

| 항목 | 사양 | 비고 |
|---|---|---|
| CPU | 96 Core | 물리 서버 기준 |
| Memory | 1 TB | |
| Storage | NVMe 4 TB | Local PersistentVolume |
| Network (bond0) | 25G + 25G LACP | Public 인터페이스, 운영자 접근 |
| Network (bond1) | 25G + 25G LACP | Private 인터페이스, 클러스터 내부 통신 |
| Container Registry | Nexus | 폐쇄망 환경, 외부 이미지 미사용 |
| GitOps | ArgoCD App of Apps | Bitbucket 연동 |

---

## 모니터링 스택 구성 요약

| 파이프라인 | 구성 요소 | 역할 |
|---|---|---|
| **Metric** | kube-prometheus-stack (Prometheus + Alertmanager + Grafana + kube-state-metrics + node-exporter) | 클러스터 및 워크로드 메트릭 수집 · 시각화 |
| **Log** | Fluent Bit Operator + Fluent Bit + OpenSearch + OpenSearch Dashboards | 컨테이너/시스템 로그 수집 · 저장 · 조회 |
| **Alert** | PrometheusRule CR → Alertmanager → k8sAlert | 임계치 기반 알림 생성 · 발송 |

---

## 문서 목차

| # | 섹션 제목 | 파일 | 주요 내용 |
|---|---|---|---|
| 0 | 문서 개요 | [00-document-overview.md](./00-document-overview.md) | 문서 구조, 용어 정의, 전제 조건, 역할 분담 |
| 1 | 모니터링 스택 아키텍처 | [01-monitoring-stack-architecture.md](./01-monitoring-stack-architecture.md) | 전체 아키텍처 다이어그램, 컴포넌트 관계, 데이터 흐름 |
| 2 | 모니터링 모듈 배포 구성 | [02-deployment-configuration.md](./02-deployment-configuration.md) | Helm values, ArgoCD Application 스펙, GitOps 레포 구조 |
| 3 | 모니터링 모듈 설치 | [03-module-installation.md](./03-module-installation.md) | 순서별 설치 절차, Namespace 생성, Helm 배포 명령 |
| 4 | 모니터링 모듈 점검 | [04-module-verification.md](./04-module-verification.md) | 설치 후 동작 확인 체크리스트, Pod/Service/PV 상태 검증 |
| 5 | Metric 파이프라인 구성 및 점검 | [05-metric-pipeline.md](./05-metric-pipeline.md) | ServiceMonitor CR 작성, Prometheus 수집 확인, Grafana 대시보드 |
| 6 | Log 파이프라인 구성 및 점검 | [06-log-pipeline.md](./06-log-pipeline.md) | Fluent Bit CR 파이프라인, OpenSearch 인덱스 매핑, 수집 확인 |
| 7 | Alert 파이프라인 구성 및 점검 | [07-alert-pipeline.md](./07-alert-pipeline.md) | PrometheusRule CR 작성, Alertmanager 라우팅, k8sAlert 연동 |
| 8 | Hot/Cold 데이터 관리 구성 확인 | [08-hot-cold-data-management.md](./08-hot-cold-data-management.md) | OpenSearch ISM 정책, Hot/Warm/Cold 티어, Prometheus 보존 정책 |
| 9 | 모니터링 모듈 성능 테스트 | [09-performance-testing.md](./09-performance-testing.md) | 부하 테스트 시나리오, 메트릭 수집 지연 측정, 성능 기준치 |
| 10 | 부록 | [10-appendix.md](./10-appendix.md) | 버전 일람, 리소스 할당, CR 목록, URL, 명령어 모음, 체크리스트 |

---

## 섹션별 상세 설명

### Section 0: 문서 개요
이 가이드 전체의 범위와 목적을 정의합니다. 주요 용어(ServiceMonitor, PrometheusRule, ClusterInput 등), 사전 요구 사항(클러스터 접근 권한, ArgoCD 계정, Bitbucket 레포 접근), 그리고 팀별 역할 분담표를 포함합니다.

### Section 1: 모니터링 스택 아키텍처
세 개의 파이프라인(Metric / Log / Alert)이 어떻게 연결되는지 전체 아키텍처를 설명합니다. bond0/bond1 네트워크 인터페이스에 따른 트래픽 분리, ArgoCD App of Apps 구조, Nexus 이미지 레지스트리 연동 방식을 다룹니다.

### Section 2: 모니터링 모듈 배포 구성
각 컴포넌트의 Helm `values.yaml` 핵심 설정과 ArgoCD `Application` CR 스펙을 설명합니다. 리소스 requests/limits, PV 클래스, 이미지 레지스트리 오버라이드, 네트워크 정책 등 운영 환경 특화 설정을 포함합니다.

### Section 3: 모니터링 모듈 설치
배포 순서(Namespace → CRD → Operator → 스택 컴포넌트 순)와 각 단계별 kubectl/argocd 명령을 제공합니다. 폐쇄망 환경에서의 이미지 사전 로드 절차도 포함합니다.

### Section 4: 모니터링 모듈 점검
설치 직후 수행하는 동작 확인 절차입니다. Pod Running 여부, Service Endpoint 존재 여부, PVC Bound 여부, ArgoCD Sync 상태 등을 체크리스트 형식으로 검증합니다.

### Section 5: Metric 파이프라인 구성 및 점검
ServiceMonitor CR 작성 방법과 Prometheus 타겟 등록 확인 절차를 설명합니다. Grafana 데이터소스 설정, 기본 대시보드 임포트, PromQL 기본 쿼리 예제를 포함합니다.

### Section 6: Log 파이프라인 구성 및 점검
Fluent Bit Operator의 CR(ClusterInput, ClusterFilter, ClusterOutput) 작성 방법을 다룹니다. OpenSearch 인덱스 템플릿 설정, 멀티라인 로그 처리, 로그 수집 정상 여부 확인 방법을 포함합니다.

### Section 7: Alert 파이프라인 구성 및 점검
PrometheusRule CR 작성 문법, Alertmanager 라우팅 설정(receivers, routes), k8sAlert webhook 연동 설정을 설명합니다. 테스트 알림 발송 및 수신 확인 절차를 포함합니다.

### Section 8: Hot/Cold 데이터 관리 구성 확인
OpenSearch ISM(Index State Management) 정책을 통한 Hot → Warm → Cold → Delete 전환 설정을 설명합니다. Prometheus TSDB 장기 보존 설정, 데이터 백업 및 스냅샷 구성도 포함합니다.

### Section 9: 모니터링 모듈 성능 테스트
배포 후 모니터링 스택 자체의 성능을 검증하는 절차입니다. 메트릭 수집 지연(scrape latency), 로그 처리량(records/sec), 알림 발화 지연(alert evaluation latency) 측정 방법과 합격 기준치를 정의합니다.

### Section 10: 부록
버전 일람, 네임스페이스별 리소스 할당, 전체 CR 목록, 접속 URL, 자주 쓰는 운영 명령어, 정기 점검 체크리스트, 문서 변경 이력을 집약합니다.

---

## 관련 문서

아래 문서는 이 가이드와 연계하여 참조하십시오.

| 문서 | 경로 | 설명 |
|---|---|---|
| 서비스팀 모니터링 가이드 | [docs/service-team-guide.md](../service-team-guide.md) | 서비스 개발팀을 위한 ServiceMonitor/PrometheusRule 작성 가이드 |
| 트러블슈팅 가이드 | [docs/troubleshooting.md](../troubleshooting.md) | 장애 유형별 원인 분석 및 조치 방법 |
| OOM 튜닝 가이드 | [docs/oom-tuning-guide.md](../oom-tuning-guide.md) | 컴포넌트 메모리 한계치 조정 및 OOMKilled 대응 |
| Prometheus 알림 가이드 | [docs/prometheus-alert-guide.md](../prometheus-alert-guide.md) | PrometheusRule CR 상세 작성 지침 |
| Prometheus 알림 룰 모음 | [docs/prometheus-alerting-rules/](../prometheus-alerting-rules/) | 사전 정의된 PrometheusRule CR YAML 파일 모음 |
| OpenSearch 인덱스 관리 | [docs/opensearch-index-management/](../opensearch-index-management/) | ISM 정책, 인덱스 템플릿, 스냅샷 설정 상세 가이드 |

---

## 빠른 참조

### 긴급 상황 대응 순서

| 상황 | 첫 번째 확인 | 참조 섹션 |
|---|---|---|
| 메트릭 수집 중단 | `kubectl get pod -n monitoring` → Prometheus Pod 상태 | Section 4, Section 5 |
| 로그 수집 중단 | `kubectl get pod -n logging` → Fluent Bit DaemonSet 상태 | Section 4, Section 6 |
| 알림 미발송 | `curl alertmanager:9093/api/v2/alerts` → 활성 알림 확인 | Section 7, Appendix E.3 |
| ArgoCD Sync 실패 | `argocd app list` → Out of Sync 앱 확인 | Section 3, Appendix E.4 |
| OpenSearch 클러스터 Red | `curl opensearch:9200/_cat/health?v` → 샤드 상태 확인 | Section 8, Appendix E.2 |
| Pod OOMKilled 발생 | `kubectl describe pod <pod>` → 이벤트/Limits 확인 | docs/oom-tuning-guide.md |

### 주요 네임스페이스

| 네임스페이스 | 용도 | 주요 컴포넌트 |
|---|---|---|
| `monitoring` | Metric + Alert 파이프라인 | Prometheus, Alertmanager, Grafana, kube-state-metrics, node-exporter |
| `logging` | Log 파이프라인 | fluent-operator, Fluent Bit, OpenSearch, OpenSearch Dashboards |
| `k8salert` | 알림 수신 서버 | k8sAlert |
| `argocd` | GitOps 관리 | ArgoCD Server, Application Controller, Repo Server |

---

*문서 버전: v1.0 | 최종 수정: 2026-03-10*
