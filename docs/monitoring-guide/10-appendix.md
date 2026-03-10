# Section 10: 부록

> **문서 위치**: `docs/monitoring-guide/10-appendix.md`
> **최종 수정**: 2026-03-10
> **작성 대상**: 운영 클러스터 모니터링 스택 전체

---

## 목차

- [A. 전체 컴포넌트 버전 일람](#a-전체-컴포넌트-버전-일람)
- [B. 네임스페이스 및 리소스 할당 요약](#b-네임스페이스-및-리소스-할당-요약)
- [C. 전체 CR 목록](#c-전체-cr-목록)
- [D. 주요 접속 URL 및 계정 관리](#d-주요-접속-url-및-계정-관리)
- [E. 운영 중 자주 쓰는 명령어 모음](#e-운영-중-자주-쓰는-명령어-모음)
- [F. 정기 점검 운영 체크리스트](#f-정기-점검-운영-체크리스트)
- [G. 문서 변경 이력](#g-문서-변경-이력)

---

## A. 전체 컴포넌트 버전 일람

모니터링 스택을 구성하는 모든 컴포넌트의 버전 및 Helm Chart 정보를 정리합니다.
신규 배포 또는 업그레이드 시 아래 표를 기준으로 버전을 확인하십시오.

### A.1 Metric 파이프라인

| 컴포넌트 | 앱 버전 | Helm Chart 버전 | Nexus 경로 | 비고 |
|---|---|---|---|---|
| kube-prometheus-stack | Operator 포함 통합 | `73.x.x` | `helm-charts/kube-prometheus-stack` | Prometheus, Alertmanager, Grafana 포함 |
| Prometheus | `v2.x.x` | kube-prometheus-stack 내장 | — | kube-prometheus-stack 서브차트 |
| Alertmanager | `v0.27.x` | kube-prometheus-stack 내장 | — | kube-prometheus-stack 서브차트 |
| Grafana | `v11.x.x` | kube-prometheus-stack 내장 | — | kube-prometheus-stack 서브차트 |
| kube-state-metrics | `v2.x.x` | kube-prometheus-stack 내장 | — | kube-prometheus-stack 서브차트 |
| prometheus-node-exporter | `v1.x.x` | kube-prometheus-stack 내장 | — | kube-prometheus-stack 서브차트 |

### A.2 Log 파이프라인

| 컴포넌트 | 앱 버전 | Helm Chart 버전 | Nexus 경로 | 비고 |
|---|---|---|---|---|
| fluent-operator | `v3.x.x` | `3.x.x` | `helm-charts/fluent-operator` | FluentBit CRD 및 Operator 포함 |
| Fluent Bit | `v3.x.x` | fluent-operator 내장 | `docker/fluent/fluent-bit` | DaemonSet으로 배포 |
| OpenSearch | `v2.x.x` | `2.x.x` | `helm-charts/opensearch` | 클러스터 모드 |
| opensearch-dashboards | `v2.x.x` | `2.x.x` | `helm-charts/opensearch-dashboards` | Kibana 대체 UI |

### A.3 Alert 파이프라인

| 컴포넌트 | 앱 버전 | Helm Chart 버전 | Nexus 경로 | 비고 |
|---|---|---|---|---|
| k8sAlert | `v1.x.x` | N/A (내부 배포) | `docker/k8salert/k8salert` | 사내 개발 커스텀 알림 서버 |

### A.4 GitOps 인프라

| 컴포넌트 | 앱 버전 | Helm Chart 버전 | Nexus 경로 | 비고 |
|---|---|---|---|---|
| ArgoCD | `v2.x.x` | `7.x.x` | `helm-charts/argo-cd` | App of Apps 패턴 |

> **참고**: 구체적인 버전 숫자(patch 버전)는 Nexus 레지스트리 또는 ArgoCD Application 스펙(`spec.source.targetRevision`)에서 확인하십시오.

---

## B. 네임스페이스 및 리소스 할당 요약

클러스터 전체 리소스(96 Core CPU, 1TB Memory, NVMe 4TB)를 기준으로 모니터링 스택에 할당된 리소스를 정리합니다.

### B.1 monitoring 네임스페이스

| 컴포넌트 | CPU Request | CPU Limit | Memory Request | Memory Limit | PV 용량 | 비고 |
|---|---|---|---|---|---|---|
| Prometheus | `2000m` | `4000m` | `8Gi` | `16Gi` | `500Gi` | NVMe Local PV, TSDB 저장소 |
| Alertmanager | `100m` | `200m` | `256Mi` | `512Mi` | `10Gi` | 알림 상태 유지용 PV |
| Grafana | `500m` | `1000m` | `512Mi` | `1Gi` | `10Gi` | 대시보드/플러그인 저장 |
| kube-state-metrics | `100m` | `200m` | `128Mi` | `256Mi` | — | PV 없음 |
| prometheus-node-exporter | `100m` | `200m` | `128Mi` | `256Mi` | — | DaemonSet, PV 없음 |
| **소계 (monitoring)** | **2,800m** | **5,600m** | **9,024Mi** | **18,048Mi** | **520Gi** | |

### B.2 logging 네임스페이스

| 컴포넌트 | CPU Request | CPU Limit | Memory Request | Memory Limit | PV 용량 | 비고 |
|---|---|---|---|---|---|---|
| fluent-operator | `100m` | `200m` | `128Mi` | `256Mi` | — | Operator Pod |
| Fluent Bit (per node) | `200m` | `500m` | `256Mi` | `512Mi` | — | DaemonSet, 노드당 할당 |
| OpenSearch (data node) | `4000m` | `8000m` | `16Gi` | `32Gi` | `1Ti` | NVMe Local PV, 노드당 |
| OpenSearch (master node) | `1000m` | `2000m` | `4Gi` | `8Gi` | `50Gi` | 전용 마스터 노드 3대 |
| opensearch-dashboards | `200m` | `500m` | `512Mi` | `1Gi` | — | PV 없음 |
| **소계 (logging)** | **5,500m+** | **11,200m+** | **20,896Mi+** | **41,792Mi+** | **1Ti+** | 노드 수에 따라 변동 |

### B.3 k8salert 네임스페이스

| 컴포넌트 | CPU Request | CPU Limit | Memory Request | Memory Limit | PV 용량 | 비고 |
|---|---|---|---|---|---|---|
| k8sAlert | `200m` | `500m` | `256Mi` | `512Mi` | — | Webhook 수신 서버 |
| **소계 (k8salert)** | **200m** | **500m** | **256Mi** | **512Mi** | — | |

### B.4 전체 리소스 할당 요약

| 구분 | CPU Request | CPU Limit | Memory Request | Memory Limit | PV 총용량 |
|---|---|---|---|---|---|
| 모니터링 스택 전체 | ~8,500m | ~17,300m | ~30Gi | ~60Gi | ~1.5Ti |
| 클러스터 총 용량 | 96,000m (96 Core) | 96,000m | 1,048,576Mi (1TB) | 1,048,576Mi | 4Ti (NVMe) |
| 사용률 (예상) | ~8.8% | ~18% | ~2.9% | ~5.9% | ~37.5% |

> **참고**: OpenSearch 데이터 노드 수, Fluent Bit DaemonSet 노드 수에 따라 실제 수치가 달라집니다. `kubectl top pod -n <namespace>` 명령으로 실시간 사용량을 확인하십시오.

---

## C. 전체 CR 목록

ArgoCD를 통해 배포되는 모든 Custom Resource의 목록입니다.
CR 변경은 반드시 Bitbucket 리포지토리를 통해 GitOps 방식으로 적용하십시오.

### C.1 ServiceMonitor CR 목록

Prometheus가 메트릭을 수집하는 대상을 정의하는 CR입니다.

| CR 명 | 네임스페이스 | 대상 서비스 | 수집 주기 | 포트/Path | 비고 |
|---|---|---|---|---|---|
| `prometheus-kube-prometheus-prometheus` | `monitoring` | Prometheus 자기 자신 | `30s` | `:9090/metrics` | 자동 생성 |
| `prometheus-kube-prometheus-alertmanager` | `monitoring` | Alertmanager | `30s` | `:9093/metrics` | 자동 생성 |
| `prometheus-kube-prometheus-grafana` | `monitoring` | Grafana | `30s` | `:3000/metrics` | 자동 생성 |
| `prometheus-kube-state-metrics` | `monitoring` | kube-state-metrics | `30s` | `:8080/metrics` | 자동 생성 |
| `prometheus-node-exporter` | `monitoring` | node-exporter (DaemonSet) | `15s` | `:9100/metrics` | 자동 생성 |
| `fluent-operator-monitor` | `logging` | fluent-operator | `30s` | `:2020/metrics` | 커스텀 CR |
| `fluent-bit-monitor` | `logging` | Fluent Bit | `15s` | `:2020/api/v1/metrics/prometheus` | 커스텀 CR |
| `opensearch-monitor` | `logging` | OpenSearch cluster | `60s` | `:9200/_prometheus/metrics` | 플러그인 필요 |
| `k8salert-monitor` | `k8salert` | k8sAlert | `30s` | `:8080/metrics` | 커스텀 CR |
| `kube-apiserver` | `default` | kubernetes API server | `30s` | `:443/metrics` | 자동 생성 |
| `kubelet` | `kube-system` | kubelet / cAdvisor | `15s` | `:10250/metrics` | 자동 생성 |
| `coredns` | `kube-system` | CoreDNS | `30s` | `:9153/metrics` | 자동 생성 |

### C.2 PrometheusRule CR 목록

알림 규칙 및 레코딩 규칙을 정의하는 CR입니다.

| CR 명 | 네임스페이스 | 그룹 수 | 규칙 수 | 최고 Severity | 주요 대상 |
|---|---|---|---|---|---|
| `prometheus-kube-prometheus-alertmanager.rules` | `monitoring` | 1 | 5 | `warning` | Alertmanager 내부 |
| `prometheus-kube-prometheus-k8s.rules` | `monitoring` | 3 | 20+ | `warning` | Kubernetes 클러스터 |
| `prometheus-kube-prometheus-node.rules` | `monitoring` | 2 | 15+ | `warning` | 노드 리소스 |
| `prometheus-kube-prometheus-kubernetes-system` | `monitoring` | 4 | 30+ | `critical` | API server, etcd |
| `prometheus-kube-prometheus-prometheus` | `monitoring` | 2 | 10 | `warning` | Prometheus 자체 |
| `custom-node-alerts` | `monitoring` | 2 | 8 | `critical` | CPU/Memory/Disk 임계치 |
| `custom-pod-alerts` | `monitoring` | 2 | 6 | `critical` | Pod OOMKilled, CrashLoop |
| `custom-network-alerts` | `monitoring` | 1 | 4 | `warning` | bond0/bond1 트래픽 |
| `custom-opensearch-alerts` | `monitoring` | 2 | 6 | `critical` | 인덱스 상태, JVM Heap |
| `custom-fluent-bit-alerts` | `monitoring` | 1 | 4 | `warning` | 로그 수집 지연/오류 |
| `custom-k8salert-alerts` | `monitoring` | 1 | 3 | `warning` | webhook 수신 실패 |

### C.3 Fluent Bit Operator CR 목록

Fluent Bit Operator가 관리하는 CR입니다. `Cluster` 접두사가 붙은 CR은 클러스터 전역 적용입니다.

**FluentBitConfig / ClusterFluentBitConfig**

| CR 명 | 종류 | 네임스페이스 | 역할 | 비고 |
|---|---|---|---|---|
| `cluster-fluentbit-config` | `ClusterFluentBitConfig` | cluster-scoped | 전역 Fluent Bit 파이프라인 조합 | Input/Filter/Output 바인딩 |

**Input CR**

| CR 명 | 종류 | 네임스페이스 | 역할 | 비고 |
|---|---|---|---|---|
| `cluster-input-tail` | `ClusterInput` | cluster-scoped | 노드 전체 컨테이너 로그 수집 | `/var/log/containers/*.log` |
| `cluster-input-systemd` | `ClusterInput` | cluster-scoped | systemd 저널 로그 수집 | kubelet, containerd 등 |

**Filter CR**

| CR 명 | 종류 | 네임스페이스 | 역할 | 비고 |
|---|---|---|---|---|
| `cluster-filter-kubernetes` | `ClusterFilter` | cluster-scoped | Pod 메타데이터 태깅 | namespace, pod_name 등 enrichment |
| `cluster-filter-modify-drop` | `ClusterFilter` | cluster-scoped | 불필요 필드 제거 | `kubernetes.labels.*` 정리 |
| `cluster-filter-nest` | `ClusterFilter` | cluster-scoped | 필드 중첩 구조 변환 | OpenSearch 인덱스 매핑 호환 |
| `cluster-filter-multiline` | `ClusterFilter` | cluster-scoped | Java 스택트레이스 멀티라인 처리 | 패턴 기반 병합 |

**Output CR**

| CR 명 | 종류 | 네임스페이스 | 역할 | 비고 |
|---|---|---|---|---|
| `cluster-output-opensearch` | `ClusterOutput` | cluster-scoped | OpenSearch로 로그 전송 | Hot tier 인덱스 대상 |
| `cluster-output-opensearch-audit` | `ClusterOutput` | cluster-scoped | 감사 로그 전용 OpenSearch 전송 | 별도 인덱스 패턴 |

---

## D. 주요 접속 URL 및 계정 관리

운영 환경에서 각 서비스에 접속하기 위한 URL, 포트, 네트워크 인터페이스 정보입니다.

> **네트워크 구분**
> - **bond0 (Public)**: 25G+25G LACP — 외부 운영자 접근 허용
> - **bond1 (Private)**: 25G+25G LACP — 클러스터 내부 서비스 간 통신 전용

| 서비스 | URL (예시) | 네트워크 | 포트 | 프로토콜 | 계정 관리 방법 | 접근 제한 |
|---|---|---|---|---|---|---|
| Grafana | `http://<bond0-IP>:3000` | bond0 (Public) | `3000` | HTTP | Kubernetes Secret (`grafana-admin-secret`) | 운영자 접근 허용 |
| OpenSearch Dashboards | `http://<bond0-IP>:5601` | bond0 (Public) | `5601` | HTTP | Kubernetes Secret (`opensearch-credentials`) | 운영자 접근 허용 |
| Prometheus | `http://<bond1-IP>:9090` | bond1 (Private) | `9090` | HTTP | 인증 없음 (내부 전용) | 클러스터 내부만 |
| Alertmanager | `http://<bond1-IP>:9093` | bond1 (Private) | `9093` | HTTP | 인증 없음 (내부 전용) | 클러스터 내부만 |
| OpenSearch API | `http://<bond1-IP>:9200` | bond1 (Private) | `9200` | HTTP | Kubernetes Secret (`opensearch-credentials`) | 클러스터 내부만 |
| ArgoCD UI | `https://<bond0-IP>:443` | bond0 (Public) | `443` | HTTPS | Kubernetes Secret (`argocd-initial-admin-secret`) | 운영자 접근 허용 |
| k8sAlert Webhook | `http://<bond1-IP>:8080` | bond1 (Private) | `8080` | HTTP | Webhook Token (Kubernetes Secret) | Alertmanager → k8sAlert |

### D.1 계정 관리 원칙

| 원칙 | 내용 |
|---|---|
| Secret 저장 위치 | 모든 인증 정보는 Kubernetes Secret으로 관리 (평문 저장 금지) |
| GitOps 처리 | Secret 값은 Bitbucket에 암호화(Sealed Secret 또는 External Secrets) 상태로 저장 |
| 비밀번호 변경 주기 | 분기 1회 이상 변경 권장 |
| 접근 로그 | Grafana, ArgoCD의 접근 로그를 OpenSearch에 수집하여 감사 추적 |
| 내부 전용 서비스 | Prometheus, Alertmanager는 bond1(Private)에서만 접근 — NodePort/LoadBalancer 불필요 |

---

## E. 운영 중 자주 쓰는 명령어 모음

### E.1 Metric 관련 명령어

```bash
# ServiceMonitor CR 목록 조회
kubectl get servicemonitor -n monitoring

# ServiceMonitor 상세 조회
kubectl describe servicemonitor <name> -n monitoring

# PrometheusRule CR 목록 조회
kubectl get prometheusrule -n monitoring

# PrometheusRule 상세 조회 (YAML)
kubectl get prometheusrule <name> -n monitoring -o yaml

# Prometheus 수집 타겟 상태 확인 (API)
curl http://prometheus:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health, lastError: .lastError}'

# Prometheus 로드된 룰 전체 확인 (API)
curl http://prometheus:9090/api/v1/rules | jq '.data.groups[].name'

# PrometheusRule 파일 문법 검사 (배포 전 검증)
promtool check rules <rule-file.yaml>

# 특정 메트릭 즉시 쿼리
curl 'http://prometheus:9090/api/v1/query?query=up' | jq '.data.result[]'

# Prometheus Pod 상태 확인
kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus

# Prometheus 로그 확인
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus --tail=100 -f
```

### E.2 Log 관련 명령어

```bash
# Fluent Bit Operator CR 전체 목록 조회
kubectl get clusterfluentbitconfig,clusterinput,clusterfilter,clusteroutput

# 네임스페이스 범위 CR 조회
kubectl get fluentbitconfig,input,filter,output -n logging

# Fluent Bit DaemonSet Pod 상태 확인
kubectl get pod -n logging -l app.kubernetes.io/name=fluent-bit -o wide

# Fluent Bit 로그 확인 (전체 노드)
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=100

# 특정 노드의 Fluent Bit 로그 확인
kubectl logs -n logging <fluent-bit-pod-name> --tail=200 -f

# fluent-operator 로그 확인
kubectl logs -n logging -l app.kubernetes.io/name=fluent-operator --tail=100

# OpenSearch 클러스터 상태 확인
curl http://opensearch:9200/_cat/health?v

# OpenSearch 인덱스 목록 (이름순 정렬)
curl 'http://opensearch:9200/_cat/indices?v&s=index'

# OpenSearch 인덱스 목록 (용량 내림차순)
curl 'http://opensearch:9200/_cat/indices?v&s=store.size:desc'

# 특정 인덱스의 ISM 정책 상태 확인
curl http://opensearch:9200/_plugins/_ism/explain/<index-name>

# ISM 정책 목록 조회
curl http://opensearch:9200/_plugins/_ism/policies

# OpenSearch 노드 상태 확인
curl http://opensearch:9200/_cat/nodes?v

# OpenSearch 샤드 상태 확인 (unassigned 확인)
curl 'http://opensearch:9200/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason'
```

### E.3 Alert 관련 명령어

```bash
# Alertmanager 라우팅 설정 확인 (Pod 내부)
kubectl exec -n monitoring <alertmanager-pod> -- \
  amtool config routes show --config.file=/etc/alertmanager/alertmanager.yml

# 현재 발화 중인 알림 목록 조회
amtool alert query --alertmanager.url=http://alertmanager:9093

# Alertmanager API로 활성 알림 조회
curl http://alertmanager:9093/api/v2/alerts | jq '.[] | {alertname: .labels.alertname, severity: .labels.severity, status: .status.state}'

# Alertmanager API로 Silence 목록 조회
curl http://alertmanager:9093/api/v2/silences | jq '.[] | select(.status.state == "active")'

# Silence 생성 (특정 알림 억제 - 유지보수 시)
amtool silence add --alertmanager.url=http://alertmanager:9093 \
  alertname="<AlertName>" \
  --comment="maintenance window" \
  --duration=2h

# Silence 해제
amtool silence expire --alertmanager.url=http://alertmanager:9093 <silence-id>

# k8sAlert 로그 확인
kubectl logs -n k8salert -l app=k8salert --tail=100 -f

# k8sAlert Pod 상태 확인
kubectl get pod -n k8salert -o wide

# Alertmanager webhook 수신 테스트
curl -X POST http://alertmanager:9093/api/v2/alerts \
  -H "Content-Type: application/json" \
  -d '[{"labels":{"alertname":"TestAlert","severity":"info"}}]'
```

### E.4 ArgoCD 관련 명령어

```bash
# ArgoCD 애플리케이션 전체 목록 조회
argocd app list

# 특정 앱 상태 상세 조회
argocd app get <app-name>

# 앱 동기화 (GitOps 반영)
argocd app sync <app-name>

# 동기화 전 변경사항 미리 확인 (dry-run)
argocd app diff <app-name>

# App of Apps 루트 앱 동기화
argocd app sync root-app --sync-option CreateNamespace=true

# 앱 히스토리 조회
argocd app history <app-name>

# 특정 리비전으로 롤백
argocd app rollback <app-name> <revision-id>

# ArgoCD 서버 로그인
argocd login <argocd-server-address> --username admin --password <password>

# 레포지토리 목록 조회
argocd repo list

# 앱 강제 새로고침 (캐시 무시)
argocd app get <app-name> --refresh
```

### E.5 일반 클러스터 점검 명령어

```bash
# 네임스페이스별 Pod 전체 상태 확인
kubectl get pod -n monitoring -o wide
kubectl get pod -n logging -o wide
kubectl get pod -n k8salert -o wide

# 리소스 사용량 확인 (Pod)
kubectl top pod -n monitoring
kubectl top pod -n logging

# 리소스 사용량 확인 (Node)
kubectl top node

# PersistentVolume 상태 확인
kubectl get pv | grep -E 'monitoring|logging'

# PersistentVolumeClaim 상태 확인
kubectl get pvc -n monitoring
kubectl get pvc -n logging

# 이벤트 확인 (최근 1시간)
kubectl get events -n monitoring --sort-by='.lastTimestamp' | tail -30
kubectl get events -n logging --sort-by='.lastTimestamp' | tail -30

# 노드 상태 확인
kubectl get node -o wide
kubectl describe node <node-name> | grep -A5 "Conditions:"
```

---

## F. 정기 점검 운영 체크리스트

모니터링 스택의 안정적 운영을 위해 아래 주기별 점검 항목을 수행합니다.
점검 완료 후 "최종점검일" 컬럼을 갱신하십시오.

### F.1 일간 점검 항목

| # | 점검 항목 | 파이프라인 | 점검 방법 | 기대 결과 | 담당자 | 최종점검일 |
|---|---|---|---|---|---|---|
| D-01 | 전체 Pod Running 상태 확인 | 공통 | `kubectl get pod -n monitoring,logging,k8salert` | 모든 Pod `Running` / `1/1` | 운영팀 | |
| D-02 | Prometheus 타겟 수집 상태 확인 | Metric | Prometheus UI → Targets 또는 API | `up` 타겟 100%, `down` 없음 | 운영팀 | |
| D-03 | 활성 알림 발화 여부 확인 | Alert | Alertmanager UI 또는 `amtool alert query` | 신규 `critical` 알림 없음 | 운영팀 | |
| D-04 | OpenSearch 클러스터 상태 확인 | Log | `curl opensearch:9200/_cat/health?v` | 상태 `green` | 운영팀 | |
| D-05 | 오늘자 로그 인덱스 생성 확인 | Log | `curl opensearch:9200/_cat/indices?v&s=index` | 오늘 날짜 인덱스 존재 | 운영팀 | |
| D-06 | Fluent Bit 로그 오류 확인 | Log | `kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit` | `[error]` 로그 없음 | 운영팀 | |
| D-07 | k8sAlert 수신 상태 확인 | Alert | `kubectl logs -n k8salert -l app=k8salert --tail=50` | 오류 없음, 정상 수신 | 운영팀 | |
| D-08 | ArgoCD 앱 Sync 상태 확인 | GitOps | `argocd app list` | 모든 앱 `Synced` / `Healthy` | 운영팀 | |
| D-09 | 노드 디스크 사용률 확인 | 인프라 | Grafana 노드 대시보드 또는 `kubectl top node` | NVMe 사용률 < 80% | 운영팀 | |
| D-10 | Prometheus TSDB 용량 확인 | Metric | Grafana 또는 `curl prometheus:9090/api/v1/query?query=prometheus_tsdb_head_chunks` | PVC 사용률 < 80% | 운영팀 | |

### F.2 주간 점검 항목

| # | 점검 항목 | 파이프라인 | 점검 방법 | 기대 결과 | 담당자 | 최종점검일 |
|---|---|---|---|---|---|---|
| W-01 | PrometheusRule 문법 및 발화 이력 검토 | Alert | Prometheus UI → Rules / Alertmanager history | 모든 룰 `ok` 상태 | 운영팀 | |
| W-02 | ISM 정책 실행 결과 확인 | Log | `curl opensearch:9200/_plugins/_ism/explain/*` | 정책 오류 없음, Hot→Warm 이동 정상 | 운영팀 | |
| W-03 | OpenSearch 샤드 상태 확인 | Log | `curl opensearch:9200/_cat/shards?v` | `UNASSIGNED` 샤드 없음 | 운영팀 | |
| W-04 | Grafana 대시보드 정상 렌더링 확인 | Metric | Grafana UI 주요 대시보드 수동 점검 | 모든 패널 데이터 표시 | 운영팀 | |
| W-05 | ArgoCD 동기화 이력 및 오류 검토 | GitOps | `argocd app history <app>` for all apps | 배포 실패 이력 없음 | 운영팀 | |
| W-06 | Fluent Bit 메트릭 수집 속도 확인 | Log | Prometheus `fluentbit_input_records_total` 쿼리 | 예상 범위 내 수집량 | 운영팀 | |
| W-07 | k8sAlert 발송 성공률 확인 | Alert | k8sAlert 로그 / 수신 채널 확인 | 발송 실패 없음 | 운영팀 | |
| W-08 | 리소스 사용량 트렌드 검토 | 인프라 | `kubectl top pod/node` + Grafana 주간 리포트 | 이상 급증 없음 | 운영팀 | |
| W-09 | PV 용량 사용률 점검 | 인프라 | `kubectl get pvc -n monitoring,logging` | 모든 PVC < 75% | 운영팀 | |
| W-10 | 보안 이벤트 감사 로그 검토 | 공통 | OpenSearch 감사 인덱스 조회 | 비정상 접근 없음 | 보안팀 | |

### F.3 월간 점검 항목

| # | 점검 항목 | 파이프라인 | 점검 방법 | 기대 결과 | 담당자 | 최종점검일 |
|---|---|---|---|---|---|---|
| M-01 | 컴포넌트 버전 업데이트 검토 | 공통 | 각 Helm Chart 최신 버전 확인 후 업그레이드 계획 수립 | 보안 패치 적용 계획 존재 | 운영팀 | |
| M-02 | OpenSearch 인덱스 보존 정책 준수 확인 | Log | Hot/Warm/Cold 인덱스 분포 확인 | ISM 정책에 따른 분포 유지 | 운영팀 | |
| M-03 | Prometheus 장기 보존 데이터 확인 | Metric | TSDB 리텐션 설정 vs 실제 데이터 범위 확인 | 설정된 보존 기간 준수 | 운영팀 | |
| M-04 | 알림 룰 적절성 검토 | Alert | PrometheusRule 전체 검토 + 오탐/미탐 이력 분석 | 불필요한 룰 제거, 임계치 조정 | 운영팀 | |
| M-05 | 계정 비밀번호 변경 | 공통 | Grafana, OpenSearch, ArgoCD 관리자 계정 | 신규 비밀번호 Secret 업데이트 완료 | 보안팀 | |
| M-06 | 장애 대응 훈련 (Runbook 검증) | 공통 | 임의의 컴포넌트 중단 후 복구 절차 수행 | 10분 이내 복구 완료 | 운영팀 | |
| M-07 | 백업 및 복구 테스트 | 공통 | TSDB 스냅샷, OpenSearch 스냅샷 복구 테스트 | 데이터 손실 없이 복구 성공 | 운영팀 | |
| M-08 | 네트워크 인터페이스 상태 확인 | 인프라 | bond0/bond1 LACP 상태, 트래픽 사용률 확인 | LACP Active-Active 정상 동작 | 인프라팀 | |
| M-09 | 문서 최신화 | 공통 | 이 문서 포함 전체 운영 문서 현행화 | 실제 운영 상태와 문서 일치 | 운영팀 | |
| M-10 | 용량 계획 검토 | 인프라 | 월간 성장률 기반 6개월 이후 용량 예측 | 용량 부족 사전 예측 및 대응 계획 | 운영팀 | |

---

## G. 문서 변경 이력

| 버전 | 일자 | 작성자 | 변경 내용 | 승인자 |
|---|---|---|---|---|
| v1.0 | 2026-03-10 | — | 최초 작성: 부록 전체 (A~G항) 초안 완성 | — |
| v1.1 | | | | |
| v1.2 | | | | |
| v2.0 | | | 대규모 개정 시 사용 | |

> **문서 변경 원칙**
> - 컴포넌트 버전 변경 시 반드시 A항 버전 일람을 갱신합니다.
> - 리소스 할당 변경 시 B항을 갱신합니다.
> - CR 추가/삭제 시 C항을 갱신합니다.
> - 모든 변경은 Bitbucket PR을 통해 리뷰 후 병합합니다.

---

*이전 섹션: [Section 9: 모니터링 모듈 성능 테스트](./09-performance-testing.md)*
*상위 문서: [README - 전체 문서 목차](./README.md)*
