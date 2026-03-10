# Section 0: 문서 개요

## 0.1 문서 목적 및 범위

본 문서는 **운영 클러스터 모니터링 스택 배포 작업**에 관한 공식 운영 가이드이다. 메트릭 수집, 로그 파이프라인, 알림 체계를 포함한 전체 모니터링 스택의 사전 준비, 배포 절차, 사후 점검 방법을 기술한다.

### 문서 목적

| 항목 | 내용 |
|------|------|
| 목적 | 운영 클러스터에 모니터링 스택을 안전하고 재현 가능한 방식으로 배포하기 위한 절차 표준화 |
| 대상 독자 | 클러스터 운영자, SRE, DevOps 엔지니어 |
| 적용 환경 | 온프레미스 운영 쿠버네티스 클러스터 |
| 작업 유형 | 신규 배포, 버전 업그레이드, 설정 변경, 장애 복구 |

### 문서 범위

| 범위 | 포함 여부 | 비고 |
|------|-----------|------|
| Metric 파이프라인 (kube-prometheus-stack) | 포함 | Prometheus 단일 인스턴스, Grafana, Alertmanager |
| Log 파이프라인 (Fluent Bit + OpenSearch) | 포함 | Fluent Bit Operator, OpenSearch 클러스터, Dashboards |
| Alert 파이프라인 (PrometheusRule → k8sAlert) | 포함 | Alertmanager 라우팅, k8sAlert 커스텀 수신기 |
| GitOps 배포 (ArgoCD App of Apps) | 포함 | Bitbucket 연동, Kustomize/Helm 관리 |
| 인프라 구성 (노드, 네트워크, 스토리지) | 참조 | 상세 인프라 가이드 별도 문서 참조 |
| 개발 환경 배포 | 미포함 | 별도 개발 환경 가이드 참조 |
| 보안 정책 (RBAC, NetworkPolicy) | 포함 | 각 섹션 내 보안 항목으로 기술 |

---

## 0.2 문서 이력

| 버전 | 일자 | 작성자 | 변경 내용 | 승인자 |
|------|------|--------|-----------|--------|
| 0.1 | YYYY-MM-DD | [작성자명] | 초안 작성 - 문서 구조 및 개요 수립 | [승인자명] |
| 0.2 | YYYY-MM-DD | [작성자명] | Section 1 아키텍처 초안 추가 | [승인자명] |
| 0.3 | YYYY-MM-DD | [작성자명] | Section 2~4 배포 절차 초안 추가 | [승인자명] |
| 0.4 | YYYY-MM-DD | [작성자명] | 내부 검토 반영, 오류 수정 | [승인자명] |
| 1.0 | YYYY-MM-DD | [작성자명] | 최초 공식 배포 버전 | [승인자명] |
| 1.1 | YYYY-MM-DD | [작성자명] | [변경 내용 기재] | [승인자명] |
| 1.2 | YYYY-MM-DD | [작성자명] | [변경 내용 기재] | [승인자명] |

> **작성 규칙**: 버전 0.x는 초안, 1.0 이상은 공식 승인 버전. 주요 구조 변경 시 주 버전(Major) 증가, 내용 수정 시 부 버전(Minor) 증가.

---

## 0.3 용어 및 약어 정의

### 쿠버네티스 및 모니터링 핵심 용어

| 용어 / 약어 | 풀네임 | 정의 |
|-------------|--------|------|
| kube-prometheus-stack | Kube Prometheus Stack | Prometheus, Alertmanager, Grafana, kube-state-metrics, node-exporter를 통합 배포하는 Helm Chart 번들. 운영 클러스터의 메트릭 수집 핵심 컴포넌트 |
| ServiceMonitor | Service Monitor CR | Prometheus Operator가 제공하는 CRD. 특정 서비스의 메트릭 수집 대상과 방법을 선언적으로 정의하는 쿠버네티스 커스텀 리소스 |
| PrometheusRule | Prometheus Rule CR | 알림 조건(Alerting Rule)과 기록 규칙(Recording Rule)을 선언적으로 정의하는 쿠버네티스 커스텀 리소스 |
| Alertmanager | Alert Manager | Prometheus에서 발생한 알림을 수신, 그룹화, 억제, 라우팅하여 최종 수신 채널로 전달하는 컴포넌트 |
| k8sAlert | Kubernetes Alert (Custom) | Alertmanager의 Webhook을 수신하여 내부 알림 채널(메신저, 이메일 등)로 가공 전달하는 사내 개발 커스텀 알림 수신 서비스 |
| Prometheus | Prometheus | 시계열 메트릭 수집 및 저장 오픈소스. 본 클러스터에서는 단일(Single) 인스턴스로 운영 |
| Grafana | Grafana | Prometheus 등 다양한 데이터소스를 시각화하는 대시보드 플랫폼 |

### 로그 파이프라인 관련 용어

| 용어 / 약어 | 풀네임 | 정의 |
|-------------|--------|------|
| Fluent Bit Operator | Fluent Bit Operator | Fluent Bit DaemonSet과 관련 설정 CR을 쿠버네티스 Operator 패턴으로 관리하는 컨트롤러 |
| Fluent Bit | Fluent Bit | 경량 로그 수집 및 전달 에이전트. 각 노드에 DaemonSet 형태로 배포되어 컨테이너 로그를 수집 |
| ClusterInput | Cluster Input CR | Fluent Bit Operator에서 클러스터 전체 범위의 로그 입력 소스를 정의하는 CR (예: tail, systemd) |
| ClusterFilter | Cluster Filter CR | Fluent Bit Operator에서 클러스터 전체 범위의 로그 파싱/변환 규칙을 정의하는 CR (예: kubernetes metadata enrichment) |
| ClusterOutput | Cluster Output CR | Fluent Bit Operator에서 클러스터 전체 범위의 로그 출력 대상을 정의하는 CR (예: OpenSearch 엔드포인트) |
| FluentBitConfig | FluentBit Config CR | ClusterInput, ClusterFilter, ClusterOutput을 조합하여 하나의 완전한 Fluent Bit 파이프라인 설정을 구성하는 CR |
| OpenSearch | OpenSearch | Elasticsearch 기반 분산 검색 및 분석 엔진. 로그 저장 및 검색 백엔드 |
| OpenSearch Dashboards | OpenSearch Dashboards | OpenSearch 데이터를 시각화하는 Kibana 기반 UI 플랫폼 |
| ISM | Index State Management | OpenSearch 인덱스의 생명주기(롤오버, 보관, 삭제 등)를 자동으로 관리하는 정책 기능 |

### GitOps 및 배포 관련 용어

| 용어 / 약어 | 풀네임 | 정의 |
|-------------|--------|------|
| GitOps | Git Operations | Git 저장소를 단일 진실 원천(Single Source of Truth)으로 사용하여 인프라 및 애플리케이션 배포를 선언적으로 관리하는 방법론 |
| ArgoCD | Argo CD | 쿠버네티스를 위한 선언적 GitOps 지속적 배포(CD) 도구. Git 저장소 상태와 클러스터 실제 상태를 지속적으로 동기화 |
| App of Apps | App of Apps Pattern | ArgoCD Application 리소스가 다른 ArgoCD Application 리소스들을 관리하는 계층적 배포 패턴 |
| Kustomize | Kustomize | 쿠버네티스 매니페스트를 템플릿 없이 패치와 오버레이 방식으로 환경별 커스터마이징하는 도구 |
| Helm | Helm | 쿠버네티스 애플리케이션 패키지 관리자. Chart 단위로 복잡한 쿠버네티스 리소스를 패키징하고 배포 |
| Nexus | Nexus Repository Manager | Sonatype이 제공하는 아티팩트 저장소. 본 환경에서는 Helm Chart Proxy 및 Container Image Mirror로 활용 |
| Bitbucket | Bitbucket | Atlassian의 Git 저장소 관리 플랫폼. GitOps 원본 저장소로 사용 |

### 인프라 관련 용어

| 용어 / 약어 | 풀네임 | 정의 |
|-------------|--------|------|
| Local PV | Local Persistent Volume | 쿠버네티스에서 특정 노드의 로컬 디스크를 Persistent Volume으로 사용하는 방식. NFS 불필요, 고성능 I/O |
| NVMe | Non-Volatile Memory Express | 고성능 SSD 인터페이스 규격. 본 클러스터에서 Local PV 백엔드로 사용 (노드당 4TB) |
| bond0 | Network Bond 0 (Public) | 공용(Public) 네트워크용 LACP 본딩 인터페이스. 25G + 25G 이중화 구성. Grafana, Dashboards 등 외부 접근 서비스 바인딩 |
| bond1 | Network Bond 1 (Private) | 사설(Private) 네트워크용 LACP 본딩 인터페이스. 25G + 25G 이중화 구성. Prometheus, OpenSearch 등 내부 서비스 바인딩 |
| LACP | Link Aggregation Control Protocol | 다수의 물리 네트워크 포트를 하나의 논리 인터페이스로 묶어 대역폭 확장 및 이중화를 제공하는 IEEE 802.3ad 표준 프로토콜 |
| CR | Custom Resource | 쿠버네티스 CRD(Custom Resource Definition)에 기반하여 생성된 사용자 정의 리소스 인스턴스 |
| CRD | Custom Resource Definition | 쿠버네티스 API를 확장하여 사용자 정의 리소스 타입을 등록하는 쿠버네티스 오브젝트 |
| DaemonSet | DaemonSet | 클러스터의 모든(또는 선택된) 노드에 정확히 하나의 Pod를 배포하고 유지하는 쿠버네티스 워크로드 리소스 |
| SRE | Site Reliability Engineering | 소프트웨어 엔지니어링 원칙을 적용하여 운영 신뢰성을 높이는 엔지니어링 분야 및 역할 |

---

## 0.4 참조 문서 및 링크 목록

### 내부 문서

| 문서명 | 경로 / 위치 | 설명 |
|--------|-------------|------|
| 모니터링 스택 아키텍처 | `docs/monitoring-guide/01-monitoring-stack-architecture.md` | 전체 모니터링 스택 아키텍처 상세 설명 |
| 사전 준비 가이드 | `docs/monitoring-guide/02-pre-deployment-checklist.md` | 배포 전 환경 점검 체크리스트 |
| Metric 배포 절차 | `docs/monitoring-guide/03-metric-pipeline-deployment.md` | kube-prometheus-stack 배포 절차 |
| Log 배포 절차 | `docs/monitoring-guide/04-log-pipeline-deployment.md` | Fluent Bit + OpenSearch 배포 절차 |
| Alert 배포 절차 | `docs/monitoring-guide/05-alert-pipeline-deployment.md` | PrometheusRule + Alertmanager 배포 절차 |
| 사후 검증 가이드 | `docs/monitoring-guide/06-post-deployment-verification.md` | 배포 후 통합 검증 절차 |
| OOM 튜닝 가이드 | `docs/oom-tuning-guide.md` | 메모리 부족 발생 시 튜닝 가이드 |
| OpenSearch ISM 가이드 | `docs/opensearch-index-management/` | OpenSearch 인덱스 생명주기 관리 |
| Prometheus 알림 규칙 가이드 | `docs/prometheus-alerting-rules/` | PrometheusRule CR 작성 및 관리 가이드 |
| 장애 대응 가이드 | `docs/troubleshooting.md` | 주요 장애 시나리오별 대응 절차 |

### 공식 외부 문서

| 문서명 | URL | 버전 |
|--------|-----|------|
| kube-prometheus-stack Helm Chart | https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack | 최신 |
| Prometheus 공식 문서 | https://prometheus.io/docs/ | 최신 |
| Alertmanager 공식 문서 | https://prometheus.io/docs/alerting/latest/alertmanager/ | 최신 |
| Fluent Bit 공식 문서 | https://docs.fluentbit.io/ | 최신 |
| Fluent Bit Operator 문서 | https://github.com/fluent/fluent-operator | 최신 |
| OpenSearch 공식 문서 | https://opensearch.org/docs/latest/ | 최신 |
| ArgoCD 공식 문서 | https://argo-cd.readthedocs.io/ | 최신 |
| Kustomize 공식 문서 | https://kustomize.io/ | 최신 |
| Helm 공식 문서 | https://helm.sh/docs/ | 최신 |

### 내부 시스템 접근 링크 (플레이스홀더)

| 시스템 | URL | 비고 |
|--------|-----|------|
| Bitbucket (GitOps 저장소) | `https://bitbucket.[내부도메인]/` | VPN 접속 필요 |
| Nexus Registry | `https://nexus.[내부도메인]/` | 사내망 접속 |
| ArgoCD UI | `https://argocd.[내부도메인]/` | 클러스터 내부 접근 |
| Grafana | `https://grafana.[내부도메인]/` | bond0 Public 바인딩 |
| OpenSearch Dashboards | `https://dashboards.[내부도메인]/` | bond0 Public 바인딩 |

---

## 0.5 작업 담당자 및 역할

### 역할 정의

| 역할 | 설명 | 필요 권한 |
|------|------|-----------|
| 작업 책임자 (Owner) | 전체 작업 계획 수립, 승인 획득, 작업 최종 책임 | 클러스터 관리자(cluster-admin) |
| 배포 실행자 (Operator) | 실제 배포 명령 수행, 설정 파일 적용 | 네임스페이스 관리자, ArgoCD 동기화 권한 |
| 검증 담당자 (Verifier) | 배포 후 기능 점검 및 검증 보고서 작성 | 읽기 전용 + 메트릭 쿼리 권한 |
| 롤백 담당자 (Rollback) | 장애 발생 시 롤백 절차 수행 | 작업 책임자와 동일 수준 |
| 보안 담당자 (Security) | 보안 정책 검토, RBAC 설정 확인 | 보안 감사 권한 |
| 승인자 (Approver) | 작업 계획 및 결과 최종 승인 | 관리 권한 (직책 기반) |

### 담당자 목록

| 역할 | 담당자 | 연락처 | 관련 섹션 |
|------|--------|--------|-----------|
| 작업 책임자 | [담당자명] | [이메일] / [전화] | 전체 |
| Metric 파이프라인 담당 | [담당자명] | [이메일] / [전화] | Section 3 (Metric 배포) |
| Log 파이프라인 담당 | [담당자명] | [이메일] / [전화] | Section 4 (Log 배포) |
| Alert 파이프라인 담당 | [담당자명] | [이메일] / [전화] | Section 5 (Alert 배포) |
| GitOps / ArgoCD 담당 | [담당자명] | [이메일] / [전화] | Section 2, 3, 4, 5 |
| 인프라 담당 (노드/네트워크) | [담당자명] | [이메일] / [전화] | Section 1, 2 |
| 검증 담당자 | [담당자명] | [이메일] / [전화] | Section 6 (검증) |
| 보안 담당자 | [담당자명] | [이메일] / [전화] | Section 2, 보안 항목 전체 |
| 승인자 | [담당자명] | [이메일] / [전화] | 작업 계획 및 완료 보고 |
| 비상 연락처 (On-Call) | [담당자명] | [전화] (24h) | 장애 대응 전체 |

### RACI 매트릭스

| 작업 항목 | 작업 책임자 | 배포 실행자 | 검증 담당자 | 보안 담당자 | 승인자 |
|-----------|-------------|-------------|-------------|-------------|--------|
| 작업 계획 수립 | **R/A** | C | C | C | A |
| 사전 점검 수행 | A | **R** | C | C | I |
| Metric 파이프라인 배포 | A | **R** | C | I | I |
| Log 파이프라인 배포 | A | **R** | C | I | I |
| Alert 파이프라인 배포 | A | **R** | C | I | I |
| 배포 후 검증 | A | C | **R** | I | I |
| 보안 설정 검토 | C | C | I | **R** | A |
| 완료 보고서 작성 | **R** | C | C | I | A |
| 롤백 결정 및 수행 | **R/A** | R | C | I | A |

> **범례**: R = Responsible(실행), A = Accountable(책임), C = Consulted(자문), I = Informed(통보)

### 비상 연락 및 에스컬레이션 절차

| 단계 | 조건 | 연락 대상 | 조치 시간 |
|------|------|-----------|-----------|
| 1단계 | 배포 중 경고(Warning) 발생 | 배포 실행자 자체 처리 | 15분 이내 |
| 2단계 | 배포 실패 또는 서비스 이상 | 작업 책임자 즉시 보고 | 즉시 |
| 3단계 | 서비스 장애 또는 데이터 손실 우려 | 작업 책임자 + 승인자 + On-Call | 즉시, 롤백 검토 |
| 4단계 | 장애 지속 (30분 이상) | 전체 담당자 + 경영진 보고 | 즉시, 전사 대응 |
