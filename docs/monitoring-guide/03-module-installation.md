# Section 3: 모니터링 모듈 설치

## 목차

- [3.1 설치 순서 및 의존성](#31-설치-순서-및-의존성)
- [3.2 작업 일정](#32-작업-일정)
- [3.3 단계별 설치 절차 (prod 기준)](#33-단계별-설치-절차-prod-기준)
- [3.4 환경별 설치 결과 기록](#34-환경별-설치-결과-기록)
- [3.5 롤백 절차](#35-롤백-절차)

---

## 3.1 설치 순서 및 의존성

각 모듈은 선행 모듈의 정상 기동 여부를 확인한 후 설치한다. 의존 관계를 무시하고 병렬 설치하면 CRD 미등록, 연결 실패 등의 문제가 발생할 수 있다.

| 순서 | 모듈 | 의존 대상 | 설치 방법 | 예상 소요 시간 | 비고 |
|------|------|----------|----------|-------------|------|
| 1 | ArgoCD AppProject / root-app | ArgoCD 기동 완료 | `kubectl apply` / `argocd app create` | 5분 | App of Apps 진입점 |
| 2 | Namespace / RBAC / Secret | - | `kubectl apply` / `kubectl create secret` | 10분 | 수동 생성 항목 포함 |
| 3 | Local PV 바인딩 확인 | Namespace 생성 완료 | `kubectl get pvc` 확인 | 5분 | PVC가 PV를 Bound 상태로 잡아야 함 |
| 4 | kube-prometheus-stack | Namespace, RBAC, Secret, PV | ArgoCD Sync (Helm) | 15~20분 | Prometheus, Grafana, Alertmanager, node-exporter, kube-state-metrics 포함 |
| 5 | ServiceMonitor CR | kube-prometheus-stack CRD 등록 완료 | ArgoCD Sync (Kustomize) | 5분 | CRD 없으면 apply 오류 발생 |
| 6 | PrometheusRule CR | Prometheus 기동 완료 | ArgoCD Sync (Kustomize) | 5분 | 알람 규칙 로드 확인 필요 |
| 7 | Fluent Bit Operator | Namespace, RBAC, Secret | ArgoCD Sync (Helm) | 10분 | Operator가 먼저 기동되어야 CR 처리 가능 |
| 8 | Fluent Bit CR (순서 준수) | Fluent Bit Operator 기동 완료 | ArgoCD Sync (Kustomize) | 10분 | FluentBit → ClusterInput → ClusterFilter → ClusterOutput → FluentBitConfig 순서 |
| 9 | OpenSearch (Hot/Warm) | Namespace, Secret, PV | ArgoCD Sync (Helm) | 20~30분 | 노드 롤링 기동, 클러스터 green 상태 확인 |
| 10 | OpenSearch Dashboards | OpenSearch API 정상 응답 | ArgoCD Sync (Helm) | 10분 | OpenSearch 로그인 인증 확인 |
| 11 | OpenSearch ISM 정책 / 인덱스 템플릿 | OpenSearch 기동 완료 | `kubectl apply` (Kustomize) 또는 API 직접 호출 | 5분 | Hot→Warm→Delete 정책 적용 |
| 12 | k8sAlert | Alertmanager 기동 완료 | ArgoCD Sync (Helm) | 10분 | Alertmanager webhook 수신 확인 |
| 13 | Grafana Datasource / Dashboard | Prometheus, OpenSearch 기동 완료 | ArgoCD Sync (Kustomize) / Grafana API | 10분 | 데이터소스 연결 상태 초록 불 확인 |

---

## 3.2 작업 일정

### 3.2.1 전체 일정 개요

| 일자 | 작업 내용 | 담당자 | 예상 소요 시간 | 완료 기준 | 상태 |
|------|---------|--------|-------------|---------|------|
| D-7 | 인프라 사전 준비 (Local PV 포맷/마운트, 네트워크 bond 설정, Nexus 이미지 미러링, Secret 사전 생성) | 인프라팀 | 4시간 | PV Available 확인, Nexus pull 테스트 통과, bond0/bond1 링크 UP | [ ] |
| D-5 | dev 환경 전체 모듈 설치 및 검증 (메트릭 수집, 로그 파이프라인, 알람 발송 E2E 테스트) | 운영팀 | 4시간 | 모든 Pod Running, 알람 테스트 수신 성공 | [ ] |
| D-3 | staging 환경 전체 모듈 설치 및 검증 (prod 동일 values 적용, 부하 테스트 포함) | 운영팀 | 4시간 | staging 검증 체크리스트 전항목 통과 | [ ] |
| D-1 | prod 설치 리허설 (dry-run), 롤백 계획 최종 확인, 변경 동결 공지 | 운영팀 + 인프라팀 | 2시간 | dry-run 오류 없음, 롤백 절차 문서 최신화 | [ ] |
| D-Day | prod 환경 전체 모듈 설치 실행 (새벽 저트래픽 시간대 권장) | 운영팀 (인프라팀 대기) | 3~4시간 | 전체 모듈 Healthy, E2E 알람 테스트 통과 | [ ] |

### 3.2.2 D-7: 인프라 사전 준비 상세

| 작업 항목 | 담당자 | 완료 기준 | 비고 |
|---------|--------|---------|------|
| NVMe 디스크 파티셔닝 및 포맷 | 인프라팀 | `lsblk` 정상, `mkfs.xfs` 완료 | 4TB NVMe, XFS 권장 |
| Local PV 매니페스트 생성 및 적용 | 인프라팀 | `kubectl get pv` STATUS=Available | StorageClass: local-nvme |
| bond0 / bond1 LACP 링크 확인 | 인프라팀 | `ip link show bond0` state UP | 25G+25G 각 4포트 |
| Nexus 이미지 미러링 (전체 목록) | 운영팀 | `docker pull nexus.internal/...` 성공 | 섹션 2.3.3 이미지 목록 기준 |
| Nexus Helm Chart 미러링 | 운영팀 | `helm search repo nexus-helm/...` 결과 반환 | 섹션 2.3.1 Chart 목록 기준 |
| Kubernetes Secret 사전 생성 | 운영팀 | `kubectl get secret -n monitoring,logging` 확인 | 섹션 2.6.3 기준 |
| ArgoCD 저장소 등록 | 운영팀 | `argocd repo list` 3개 저장소 CONNECTION OK | 섹션 2.6.6 기준 |

### 3.2.3 D-5: dev 환경 설치 검증 항목

| 검증 항목 | 확인 방법 | 합격 기준 |
|---------|---------|---------|
| 모든 Pod 기동 여부 | `kubectl get pods -A` | STATUS=Running, RESTARTS=0 |
| Prometheus 메트릭 수집 | Prometheus UI → Targets 페이지 | 모든 Target UP |
| Fluent Bit 로그 전송 | OpenSearch Dashboards → Discover | 로그 인덱스에 레코드 유입 확인 |
| Alertmanager 알람 발송 | `amtool alert add` 후 Slack/k8sAlert 수신 확인 | 알람 수신 5분 이내 |
| Grafana 대시보드 | Grafana UI → 클러스터 대시보드 | 데이터 정상 시각화 |

---

## 3.3 단계별 설치 절차 (prod 기준)

> 모든 단계는 순서대로 실행한다. 각 단계의 "정상 기준"을 확인한 후 다음 단계로 진행한다.
> 확인 실패 시 즉시 작업을 중단하고 [3.5 롤백 절차](#35-롤백-절차)를 참조한다.

---

### Step 1: ArgoCD AppProject / root-app 등록

#### 1-1. AppProject 생성

```bash
# AppProject 매니페스트 적용
kubectl apply -f monitoring-gitops/projects/monitoring-project.yaml
kubectl apply -f monitoring-gitops/projects/logging-project.yaml

# 생성 확인
kubectl get appproject -n argocd
```

#### 1-2. root-app 등록

```bash
# root-app Application 생성
kubectl apply -f monitoring-gitops/apps/root-app.yaml

# 또는 argocd CLI 사용
argocd app create root-app \
  --repo https://bitbucket.internal/monitoring-gitops \
  --path apps/prod \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace argocd \
  --sync-policy automated \
  --self-heal \
  --project monitoring
```

#### 확인 명령어

```bash
argocd app get root-app
argocd app list
kubectl get applications -n argocd
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| root-app STATUS | Healthy |
| root-app SYNC | Synced |
| 하위 Application 자동 생성 여부 | `argocd app list`에 하위 App 목록 출현 |

---

### Step 2: Namespace / RBAC / Secret 프로비저닝

#### 2-1. Namespace 생성

```bash
kubectl apply -f monitoring-kustomize/base/namespaces/monitoring.yaml
kubectl apply -f monitoring-kustomize/base/namespaces/logging.yaml

# 확인
kubectl get ns monitoring logging
```

#### 2-2. imagePullSecret 생성

```bash
# Nexus 레지스트리 인증 Secret 생성 (monitoring 네임스페이스)
kubectl create secret docker-registry nexus-registry-secret \
  --docker-server=nexus.internal \
  --docker-username=<username> \
  --docker-password=<password> \
  -n monitoring

# Nexus 레지스트리 인증 Secret 생성 (logging 네임스페이스)
kubectl create secret docker-registry nexus-registry-secret \
  --docker-server=nexus.internal \
  --docker-username=<username> \
  --docker-password=<password> \
  -n logging
```

#### 2-3. 운영 Secret 생성

```bash
# OpenSearch 인증
kubectl create secret generic opensearch-credentials \
  --from-literal=username=admin \
  --from-literal=password='<STRONG_PASSWORD>' \
  -n logging

# Grafana admin
kubectl create secret generic grafana-admin-credentials \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='<STRONG_PASSWORD>' \
  -n monitoring

# Alertmanager (Slack + k8sAlert webhook)
kubectl create secret generic alertmanager-secret \
  --from-literal=slack-webhook-url='https://hooks.slack.com/...' \
  --from-literal=k8salert-webhook-url='http://k8salert-svc.monitoring.svc.cluster.local/webhook' \
  -n monitoring
```

#### 확인 명령어

```bash
kubectl get ns monitoring logging
kubectl get secret -n monitoring
kubectl get secret -n logging
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| `monitoring` 네임스페이스 STATUS | Active |
| `logging` 네임스페이스 STATUS | Active |
| `nexus-registry-secret` 존재 여부 | monitoring, logging 양쪽 모두 존재 |
| `opensearch-credentials` 존재 여부 | logging 네임스페이스 존재 |
| `grafana-admin-credentials` 존재 여부 | monitoring 네임스페이스 존재 |
| `alertmanager-secret` 존재 여부 | monitoring 네임스페이스 존재 |

---

### Step 3: Local PV 바인딩 확인

PVC는 kube-prometheus-stack / OpenSearch Helm Chart 설치 시 자동 생성된다. 이 단계에서는 PV가 Available 상태인지 사전 확인하고, 설치 후 Bound 여부를 검증한다.

#### 사전 확인

```bash
# 전체 PV 상태 확인
kubectl get pv -o wide

# StorageClass 확인
kubectl get storageclass local-nvme
```

#### 설치 후 바인딩 확인 (kube-prometheus-stack 설치 이후 재확인)

```bash
# PVC 상태 확인
kubectl get pvc -n monitoring
kubectl get pvc -n logging

# 특정 PV 상세 확인
kubectl describe pv <prometheus-pv-name>
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| Prometheus PV STATUS | Available (설치 전) → Bound (설치 후) |
| OpenSearch Hot PV × 3 STATUS | 모두 Bound |
| OpenSearch Warm PV × 2 STATUS | 모두 Bound |
| Alertmanager PV STATUS | Bound |
| Grafana PV STATUS | Bound |
| PVC STORAGECLASS | `local-nvme` |

---

### Step 4: kube-prometheus-stack 설치

#### 4-1. ArgoCD Sync 실행

```bash
# prometheus-stack Application Sync 트리거
argocd app sync prometheus-stack --prune

# Sync 상태 실시간 모니터링
argocd app wait prometheus-stack --health --sync --timeout 600
```

#### 4-2. ServiceMonitor / PrometheusRule CR 동기화

```bash
# ServiceMonitor CRD 확인 (prometheus-stack 설치 후 자동 등록됨)
kubectl get crd servicemonitors.monitoring.coreos.com
kubectl get crd prometheusrules.monitoring.coreos.com

# Kustomize 기반 CR 동기화
argocd app sync monitoring-crds
argocd app sync prometheus-rules
```

#### 확인 명령어

```bash
# Pod 상태 확인
kubectl get pods -n monitoring

# Prometheus Targets 확인 (port-forward 사용)
kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring &
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets | length'

# ServiceMonitor 목록 확인
kubectl get servicemonitor -n monitoring

# PrometheusRule 목록 확인
kubectl get prometheusrule -n monitoring

# Alertmanager 상태 확인
kubectl port-forward svc/alertmanager-operated 9093:9093 -n monitoring &
curl -s http://localhost:9093/api/v2/status | jq '.cluster.status'
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| prometheus-stack Pod STATUS | 모두 Running |
| Prometheus Pod READY | 1/1 |
| Alertmanager Pod READY | 2/2 (HA 구성) |
| Grafana Pod READY | 1/1 |
| node-exporter DaemonSet DESIRED = READY | 전체 노드 수와 동일 |
| kube-state-metrics READY | 1/1 |
| ServiceMonitor 개수 | 5개 이상 (node-exporter, kube-state-metrics, fluent-bit, opensearch, k8salert) |
| Prometheus Active Targets | 0개 DOWN 없음 |

---

### Step 5: Fluent Bit Operator 설치

#### 5-1. Operator 설치 (ArgoCD Sync)

```bash
argocd app sync fluent-operator --prune
argocd app wait fluent-operator --health --sync --timeout 300
```

#### 5-2. Fluent Bit CR 순서 적용

CR은 반드시 아래 순서로 적용한다. 순서를 어기면 FluentBitConfig가 참조하는 리소스를 찾지 못해 파이프라인이 구성되지 않는다.

```bash
# 1. FluentBit CR (DaemonSet 기본 설정)
kubectl apply -f monitoring-kustomize/base/fluent-bit-configs/fluentbit-cr.yaml -n logging
kubectl rollout status daemonset/fluent-bit -n logging

# 2. ClusterInput (로그 수집 소스 정의)
kubectl apply -f monitoring-kustomize/base/fluent-bit-configs/cluster-input/ -n logging
kubectl get clusterinput -n logging

# 3. ClusterFilter (로그 가공 규칙)
kubectl apply -f monitoring-kustomize/base/fluent-bit-configs/filter/ -n logging
kubectl get clusterfilter -n logging

# 4. ClusterOutput (로그 전송 대상)
kubectl apply -f monitoring-kustomize/base/fluent-bit-configs/output/ -n logging
kubectl get clusteroutput -n logging

# 5. FluentBitConfig (파이프라인 조합)
kubectl apply -f monitoring-kustomize/base/fluent-bit-configs/fluentbitconfig-cr.yaml -n logging
kubectl get fluentbitconfig -n logging
```

또는 ArgoCD를 통한 일괄 Sync (Sync Wave 어노테이션이 CR 파일에 정의된 경우):

```bash
argocd app sync fluent-bit-configs --prune
argocd app wait fluent-bit-configs --health --sync --timeout 300
```

#### 확인 명령어

```bash
# Operator Pod 상태
kubectl get pods -n logging -l app.kubernetes.io/name=fluent-operator

# Fluent Bit DaemonSet 상태
kubectl get daemonset fluent-bit -n logging

# CR 상태 확인
kubectl get fluentbit,clusterinput,clusterfilter,clusteroutput,fluentbitconfig -n logging

# 로그 파이프라인 동작 확인 (Fluent Bit Pod 로그)
kubectl logs -l app.kubernetes.io/name=fluent-bit -n logging --tail=50 | grep -E "error|warn|output"

# OpenSearch로 로그 전송 확인
kubectl logs -l app.kubernetes.io/name=fluent-bit -n logging --tail=20 | grep opensearch
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| fluent-operator Pod STATUS | Running 1/1 |
| fluent-bit DaemonSet DESIRED = READY | 전체 노드 수와 동일 |
| FluentBit CR STATUS | 오류 없음 |
| FluentBitConfig CR 적용 | `kubectl get fluentbitconfig` 항목 존재 |
| Fluent Bit Pod 로그 | `[error]` 없음, output 플러그인 초기화 성공 메시지 |

---

### Step 6: OpenSearch 설치 (Hot/Cold 노드 롤링 기동)

#### 6-1. OpenSearch 클러스터 설치

```bash
argocd app sync opensearch --prune
argocd app wait opensearch --health --sync --timeout 900
```

#### 6-2. 노드 롤링 기동 모니터링

```bash
# StatefulSet 상태 확인 (Hot 노드)
kubectl get statefulset opensearch-master -n logging
kubectl rollout status statefulset/opensearch-master -n logging

# StatefulSet 상태 확인 (Warm 노드, 별도 StatefulSet 사용 시)
kubectl get statefulset opensearch-warm -n logging

# Pod 기동 순서 실시간 모니터링
watch kubectl get pods -n logging -l app.kubernetes.io/name=opensearch
```

#### 6-3. 클러스터 상태 확인

```bash
# OpenSearch 클러스터 헬스 확인
kubectl port-forward svc/opensearch-cluster-master 9200:9200 -n logging &
curl -u admin:<password> -k https://localhost:9200/_cluster/health?pretty

# 노드 목록 확인
curl -u admin:<password> -k https://localhost:9200/_cat/nodes?v

# 인덱스 목록 확인 (초기에는 빈 상태)
curl -u admin:<password> -k https://localhost:9200/_cat/indices?v
```

#### 6-4. OpenSearch Dashboards 설치

```bash
argocd app sync opensearch-dashboards --prune
argocd app wait opensearch-dashboards --health --sync --timeout 300
```

#### 6-5. OpenSearch ISM 정책 / 인덱스 템플릿 적용

```bash
# Kustomize 적용 (Job 또는 ConfigMap 방식)
kubectl apply -k monitoring-kustomize/base/opensearch-ism/ -n logging

# 또는 API 직접 호출
# ISM 정책 등록
curl -u admin:<password> -k -X PUT \
  https://localhost:9200/_plugins/_ism/policies/hot-warm-delete \
  -H 'Content-Type: application/json' \
  -d @opensearch-ism/hot-warm-delete-policy.json

# 인덱스 템플릿 등록
curl -u admin:<password> -k -X PUT \
  https://localhost:9200/_index_template/k8s-logs-template \
  -H 'Content-Type: application/json' \
  -d @opensearch-ism/index-template.json

# 적용 확인
curl -u admin:<password> -k https://localhost:9200/_plugins/_ism/policies?pretty
curl -u admin:<password> -k https://localhost:9200/_index_template/k8s-logs-template?pretty
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| OpenSearch 클러스터 상태 | `"status": "green"` |
| Hot 노드 수 | 3개 모두 Running |
| Warm 노드 수 | 2개 모두 Running |
| Dashboards Pod STATUS | Running 1/1 |
| ISM 정책 등록 | `hot-warm-delete` 정책 존재 |
| 인덱스 템플릿 등록 | `k8s-logs-template` 존재 |
| Fluent Bit → OpenSearch 로그 수신 | `_cat/indices` 에 k8s-logs 인덱스 생성 확인 |

---

### Step 7: k8sAlert 설치 (Alertmanager webhook 연동)

#### 7-1. k8sAlert 설치

```bash
argocd app sync k8salert --prune
argocd app wait k8salert --health --sync --timeout 300
```

#### 7-2. Alertmanager webhook 설정 확인

```bash
# Alertmanager 설정에 k8sAlert webhook 수신 URL이 등록되어 있는지 확인
kubectl port-forward svc/alertmanager-operated 9093:9093 -n monitoring &
curl -s http://localhost:9093/api/v2/status | jq '.config.original' | grep k8salert
```

#### 7-3. 알람 발송 E2E 테스트

```bash
# 테스트 알람 수동 발생 (amtool 사용)
kubectl run amtool --image=nexus.internal/prometheus/alertmanager --rm -it \
  --restart=Never -n monitoring -- \
  amtool --alertmanager.url=http://alertmanager-operated:9093 \
  alert add alertname=TestAlert severity=warning instance=test-node \
  summary="Integration test alert"

# k8sAlert Pod 로그에서 수신 확인
kubectl logs -l app.kubernetes.io/name=k8salert -n monitoring --tail=30

# 테스트 알람 해제
kubectl run amtool-delete --image=nexus.internal/prometheus/alertmanager --rm -it \
  --restart=Never -n monitoring -- \
  amtool --alertmanager.url=http://alertmanager-operated:9093 \
  silence add alertname=TestAlert --duration=1m --comment="cleanup"
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| k8sAlert Pod STATUS | Running 1/1 |
| Alertmanager config에 webhook URL | `k8salert-svc` URL 포함 |
| 테스트 알람 수신 (k8sAlert 로그) | `received alert: TestAlert` 로그 확인 |
| 알람 중복 억제 기능 | 동일 알람 재발송 시 중복 없음 |

---

### Step 8: Grafana Datasource / Dashboard 프로비저닝

#### 8-1. Datasource 프로비저닝 (Helm values 또는 ConfigMap)

kube-prometheus-stack Helm values에 `grafana.additionalDataSources`를 통해 선언적으로 구성한다.

```yaml
# values-prod.yaml 내 datasource 설정 예시
grafana:
  additionalDataSources:
    - name: Prometheus
      type: prometheus
      url: http://prometheus-operated:9090
      isDefault: true
    - name: OpenSearch
      type: grafana-opensearch-datasource
      url: https://opensearch-cluster-master:9200
      basicAuth: true
      basicAuthUser: admin
      secureJsonData:
        basicAuthPassword: ${GF_DATASOURCE_OPENSEARCH_PASSWORD}
```

#### 8-2. Datasource 연결 상태 확인

```bash
# Grafana API로 datasource 목록 확인
kubectl port-forward svc/prometheus-stack-grafana 3000:80 -n monitoring &
curl -s -u admin:<password> http://localhost:3000/api/datasources | jq '.[].name'

# Datasource 헬스체크
curl -s -u admin:<password> http://localhost:3000/api/datasources/1/health | jq '.status'
curl -s -u admin:<password> http://localhost:3000/api/datasources/2/health | jq '.status'
```

#### 8-3. Dashboard 프로비저닝 확인

```bash
# ConfigMap 기반 Dashboard 프로비저닝 확인
kubectl get configmap -n monitoring -l grafana_dashboard=1

# Grafana API로 등록된 Dashboard 목록 확인
curl -s -u admin:<password> http://localhost:3000/api/search | jq '.[].title'
```

#### 8-4. Grafana 플러그인 설치 확인 (OpenSearch datasource 플러그인)

```bash
# 설치된 플러그인 확인
curl -s -u admin:<password> http://localhost:3000/api/plugins?type=datasource | \
  jq '.[] | select(.id=="grafana-opensearch-datasource") | .info.version'
```

| 정상 기준 항목 | 기댓값 |
|-------------|-------|
| Grafana Pod STATUS | Running 1/1 |
| Prometheus Datasource 상태 | `"status": "ok"` |
| OpenSearch Datasource 상태 | `"status": "ok"` |
| 대시보드 수 | 기본 Kubernetes 대시보드 10개 이상 |
| OpenSearch 플러그인 설치 | 버전 문자열 반환 |

---

## 3.4 환경별 설치 결과 기록

설치 완료 후 아래 표에 결과를 기록하여 추적성을 확보한다.

### 3.4.1 dev 환경

| 모듈 | 설치 일시 | Chart / 이미지 버전 | 담당자 | 결과 | 비고 |
|------|---------|------------------|--------|------|------|
| kube-prometheus-stack | | 58.x | | [ ] 성공 / [ ] 실패 | |
| Fluent Bit Operator | | 3.x | | [ ] 성공 / [ ] 실패 | |
| OpenSearch | | 2.x | | [ ] 성공 / [ ] 실패 | |
| OpenSearch Dashboards | | 2.x | | [ ] 성공 / [ ] 실패 | |
| k8sAlert | | - | | [ ] 성공 / [ ] 실패 | |

### 3.4.2 staging 환경

| 모듈 | 설치 일시 | Chart / 이미지 버전 | 담당자 | 결과 | 비고 |
|------|---------|------------------|--------|------|------|
| kube-prometheus-stack | | 58.x | | [ ] 성공 / [ ] 실패 | |
| Fluent Bit Operator | | 3.x | | [ ] 성공 / [ ] 실패 | |
| OpenSearch | | 2.x | | [ ] 성공 / [ ] 실패 | |
| OpenSearch Dashboards | | 2.x | | [ ] 성공 / [ ] 실패 | |
| k8sAlert | | - | | [ ] 성공 / [ ] 실패 | |

### 3.4.3 prod 환경

| 모듈 | 설치 일시 | Chart / 이미지 버전 | 담당자 | 결과 | 비고 |
|------|---------|------------------|--------|------|------|
| kube-prometheus-stack | | 58.x | | [ ] 성공 / [ ] 실패 | |
| ServiceMonitor CRs | | kustomize | | [ ] 성공 / [ ] 실패 | |
| PrometheusRule CRs | | kustomize | | [ ] 성공 / [ ] 실패 | |
| Fluent Bit Operator | | 3.x | | [ ] 성공 / [ ] 실패 | |
| Fluent Bit CRs | | kustomize | | [ ] 성공 / [ ] 실패 | |
| OpenSearch | | 2.x | | [ ] 성공 / [ ] 실패 | |
| OpenSearch Dashboards | | 2.x | | [ ] 성공 / [ ] 실패 | |
| OpenSearch ISM 정책 | | API | | [ ] 성공 / [ ] 실패 | |
| k8sAlert | | - | | [ ] 성공 / [ ] 실패 | |
| Grafana Datasource | | 자동 프로비저닝 | | [ ] 성공 / [ ] 실패 | |

---

## 3.5 롤백 절차

### 3.5.1 롤백 판단 기준 및 절차

| 단계 | 판단 기준 (롤백 트리거) | 롤백 명령어 | 예상 소요 시간 | 담당자 |
|------|---------------------|-----------|-------------|--------|
| **kube-prometheus-stack 롤백** | Pod CrashLoopBackOff 5분 이상 지속 / Prometheus targets 50% 이상 DOWN | `argocd app rollback prometheus-stack` 또는 `helm rollback prometheus-stack -n monitoring` | 10분 | 운영팀 |
| **Fluent Bit Operator 롤백** | Fluent Bit Pod 전체 재시작 반복 / 로그 수집 중단 10분 이상 | `argocd app rollback fluent-operator` 또는 `helm rollback fluent-operator -n logging` | 10분 | 운영팀 |
| **Fluent Bit CR 롤백** | FluentBitConfig 적용 후 파이프라인 오류 / OpenSearch 연결 실패 지속 | `kubectl apply -f <이전버전_CR>` 또는 Git revert 후 `argocd app sync` | 5분 | 운영팀 |
| **OpenSearch 롤백** | 클러스터 상태 red 10분 이상 지속 / 샤드 배분 실패 | `argocd app rollback opensearch` 또는 `helm rollback opensearch -n logging` | 20~30분 | 운영팀 + 인프라팀 |
| **OpenSearch Dashboards 롤백** | Dashboards Pod CrashLoopBackOff / OpenSearch 로그인 실패 | `argocd app rollback opensearch-dashboards` | 5분 | 운영팀 |
| **k8sAlert 롤백** | k8sAlert Pod 기동 실패 / Alertmanager webhook 오류 반복 | `argocd app rollback k8salert` 또는 `helm rollback k8salert -n monitoring` | 5분 | 운영팀 |
| **전체 롤백 (긴급)** | 다수 모듈 동시 장애 / 클러스터 불안정 | ArgoCD 전체 App rollback 순서 역순 실행 | 60분 | 운영팀 + 인프라팀 |

### 3.5.2 ArgoCD 롤백 명령어 참조

```bash
# Application 이전 버전 히스토리 확인
argocd app history <app-name>

# 특정 리비전으로 롤백
argocd app rollback <app-name> <revision-id>

# 예시: prometheus-stack을 리비전 3으로 롤백
argocd app rollback prometheus-stack 3

# Helm 직접 롤백 (ArgoCD 외 긴급 조치)
helm history prometheus-stack -n monitoring
helm rollback prometheus-stack <revision> -n monitoring

# 롤백 후 상태 확인
argocd app get <app-name>
kubectl get pods -n monitoring
```

### 3.5.3 OpenSearch 데이터 보호 절차 (롤백 전 체크)

OpenSearch 롤백 시 데이터 손실 위험이 있으므로 아래 절차를 먼저 수행한다.

```bash
# 1. 인덱스 스냅샷 생성 (S3 또는 NFS 스냅샷 저장소 사전 등록 필요)
curl -u admin:<password> -k -X PUT \
  https://localhost:9200/_snapshot/backup_repo/snapshot_before_rollback?wait_for_completion=true

# 2. 스냅샷 완료 확인
curl -u admin:<password> -k \
  https://localhost:9200/_snapshot/backup_repo/snapshot_before_rollback?pretty | \
  jq '.snapshots[0].state'
# 기댓값: "SUCCESS"

# 3. 클러스터 상태 최종 확인
curl -u admin:<password> -k https://localhost:9200/_cluster/health?pretty | jq '.status'
```

### 3.5.4 롤백 완료 후 검증 체크리스트

| 검증 항목 | 확인 명령어 | 합격 기준 |
|---------|------------|---------|
| 이전 버전 Pod 기동 확인 | `kubectl get pods -A` | 모든 Pod Running |
| Prometheus 메트릭 수집 재개 | `curl http://localhost:9090/api/v1/targets` | 0개 DOWN |
| Fluent Bit 로그 전송 재개 | `kubectl logs -l app.kubernetes.io/name=fluent-bit -n logging --tail=20` | output 오류 없음 |
| OpenSearch 클러스터 상태 | `curl .../cluster/health` | `"status":"green"` |
| Alertmanager 알람 수신 가능 | `amtool alert add` 테스트 | k8sAlert 수신 확인 |
| Grafana 대시보드 데이터 표시 | Grafana UI 접속 | 데이터 갭 허용 범위 내 (롤백 소요시간 이내) |
| ArgoCD App 상태 | `argocd app list` | Healthy / Synced |

---

*이전 섹션: [Section 2: 모니터링 모듈 배포 구성](./02-deployment-configuration.md)*
