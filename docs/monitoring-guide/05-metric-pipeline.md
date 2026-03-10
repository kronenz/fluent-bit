# Section 5: Metric 파이프라인 구성 및 점검

> 본 섹션은 kube-prometheus-stack 기반 Metric 파이프라인의 구성 요소(ServiceMonitor, Prometheus, Grafana)와 각 구성 요소의 운영 점검 절차를 기술한다.
> 단일 Prometheus 인스턴스(HA 없음) 구성이므로 재시작 시 수집 공백이 발생한다는 점을 유의한다.

---

## 5.1 ServiceMonitor CR 구성

### 5.1.1 전체 ServiceMonitor 목록

`ServiceMonitor` CR은 Prometheus Operator가 자동으로 감지하여 Prometheus scrape 설정에 반영한다.
아래 표는 기본 배포 시 생성되는 CR 목록이며, 커스텀 애플리케이션 모니터링은 별도 CR로 추가한다.

```bash
kubectl get servicemonitor -n monitoring -o wide
```

| CR명 | 대상 서비스 | 대상 네임스페이스 | 수집 주기 | 라벨 셀렉터 | 비고 |
|------|------------|-----------------|-----------|-------------|------|
| `kube-prometheus-stack-apiserver` | kubernetes (kube-apiserver) | default | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | TLS 인증 필요 |
| `kube-prometheus-stack-coredns` | kube-dns | kube-system | 15s | `app.kubernetes.io/instance: kube-prometheus-stack` | |
| `kube-prometheus-stack-etcd` | etcd | kube-system | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | TLS 인증 필요 |
| `kube-prometheus-stack-kube-controller-manager` | kube-controller-manager | kube-system | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | |
| `kube-prometheus-stack-kube-proxy` | kube-proxy | kube-system | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | |
| `kube-prometheus-stack-kube-scheduler` | kube-scheduler | kube-system | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | |
| `kube-prometheus-stack-kube-state-metrics` | kube-state-metrics | monitoring | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | |
| `kube-prometheus-stack-kubelet` | kubelet | kube-system | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | cAdvisor 포함 |
| `kube-prometheus-stack-node-exporter` | node-exporter | monitoring | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | 전체 노드 |
| `kube-prometheus-stack-operator` | prometheus-operator | monitoring | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | |
| `kube-prometheus-stack-prometheus` | prometheus-operated | monitoring | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | 자기 자신 모니터링 |
| `kube-prometheus-stack-alertmanager` | alertmanager-operated | monitoring | 30s | `app.kubernetes.io/instance: kube-prometheus-stack` | |
| `custom-app-monitor` | custom-app-svc | app-namespace | 60s | `monitoring: custom` | 커스텀 앱 |
| `opensearch-monitor` | opensearch | logging | 60s | `monitoring: custom` | OpenSearch 메트릭 |
| `fluent-bit-monitor` | fluent-bit | logging | 30s | `monitoring: custom` | Fluent Bit 내장 메트릭 |

---

### 5.1.2 ServiceMonitor 작성 기준 및 YAML 예시

ServiceMonitor 작성 시 아래 기준을 반드시 준수한다.

| 항목 | 기준 | 설명 |
|------|------|------|
| `namespace` | `monitoring` | Prometheus와 동일한 네임스페이스에 생성 권장 |
| `labels` | `app.kubernetes.io/instance: kube-prometheus-stack` | Prometheus CR의 `serviceMonitorSelector`와 일치 필요 |
| `namespaceSelector` | 대상 서비스의 네임스페이스 명시 | `any: true` 사용 주의 (보안) |
| `selector.matchLabels` | 대상 서비스의 실제 라벨 | 잘못된 라벨 지정 시 Target 미수집 |
| `endpoints[].port` | 서비스 포트명 (문자열) 또는 번호 | 포트명 사용 권장 (변경에 유연) |
| `endpoints[].interval` | 기본값 30s, 고빈도 필요 시 15s | 과도한 단축은 Prometheus 부하 증가 |
| `endpoints[].path` | `/metrics` (기본값) | 다른 경로 사용 시 명시 |
| `endpoints[].scheme` | `http` 또는 `https` | TLS 사용 시 `tlsConfig` 함께 설정 |

**일반 애플리케이션 ServiceMonitor YAML 예시**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: custom-app-monitor
  namespace: monitoring                    # Prometheus와 동일 네임스페이스
  labels:
    app.kubernetes.io/instance: kube-prometheus-stack   # serviceMonitorSelector 매칭
spec:
  namespaceSelector:
    matchNames:
      - app-namespace                      # 대상 서비스가 위치한 네임스페이스
  selector:
    matchLabels:
      app: custom-app                      # 대상 Service의 라벨
  endpoints:
    - port: metrics                        # Service의 포트명
      interval: 60s
      path: /metrics
      scheme: http
```

**TLS 인증이 필요한 ServiceMonitor YAML 예시 (etcd 등)**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: etcd-monitor
  namespace: monitoring
  labels:
    app.kubernetes.io/instance: kube-prometheus-stack
spec:
  namespaceSelector:
    matchNames:
      - kube-system
  selector:
    matchLabels:
      component: etcd
  endpoints:
    - port: metrics
      interval: 30s
      scheme: https
      tlsConfig:
        caFile: /etc/prometheus/secrets/etcd-certs/ca.crt
        certFile: /etc/prometheus/secrets/etcd-certs/client.crt
        keyFile: /etc/prometheus/secrets/etcd-certs/client.key
        insecureSkipVerify: false
```

---

### 5.1.3 Prometheus 셀렉터 매칭 구성 확인

Prometheus CR이 ServiceMonitor를 감지하려면 `serviceMonitorSelector` 설정이 일치해야 한다.

```bash
# Prometheus CR의 selector 확인
kubectl get prometheus -n monitoring kube-prometheus-stack-prometheus \
  -o jsonpath='{.spec.serviceMonitorSelector}' | jq .
```

**kube-prometheus-stack `values.yaml` 관련 설정**

```yaml
prometheus:
  prometheusSpec:
    # 특정 라벨만 감지 (기본값: 해당 릴리즈 라벨만)
    serviceMonitorSelector:
      matchLabels:
        app.kubernetes.io/instance: kube-prometheus-stack

    # 모든 네임스페이스의 ServiceMonitor 감지
    serviceMonitorNamespaceSelector: {}

    # 또는 모든 ServiceMonitor 감지 (라벨 무관)
    # serviceMonitorSelector: {}
```

> **주의**: `serviceMonitorSelector: {}` 설정 시 클러스터 내 모든 ServiceMonitor를 수집하므로 의도치 않은 타겟이 추가될 수 있다. 운영 환경에서는 라벨 기반 셀렉터 사용을 권장한다.

---

## 5.2 Prometheus 수집 설정

### 5.2.1 scrape_config 주요 설정

| 항목 | 값 | 설명 |
|------|-----|------|
| `global.scrape_interval` | `30s` | 전체 기본 수집 주기 |
| `global.scrape_timeout` | `10s` | 수집 타임아웃 (scrape_interval보다 짧아야 함) |
| `global.evaluation_interval` | `30s` | PrometheusRule 평가 주기 |
| `global.external_labels.cluster` | `<클러스터명>` | 외부 전송 시 레이블 추가 |
| `global.external_labels.env` | `production` | 환경 구분 레이블 |
| `scrape_configs[].honor_labels` | `false` (기본) | 타겟 레이블이 Prometheus 레이블 덮어쓰기 방지 |
| `scrape_configs[].metrics_path` | `/metrics` (기본) | 수집 엔드포인트 경로 |
| `scrape_configs[].scheme` | `http` (기본) | 수집 프로토콜 |
| `storage.tsdb.path` | `/prometheus` | TSDB 데이터 저장 경로 (Local PV 마운트) |
| `storage.tsdb.retention.time` | `15d` | 데이터 보존 기간 |
| `storage.tsdb.retention.size` | `500GB` | 데이터 보존 최대 크기 |
| `web.enable-lifecycle` | `true` | API를 통한 설정 재로드 활성화 |
| `web.enable-admin-api` | `false` (기본) | 관리 API (운영 환경 비활성화 권장) |

kube-prometheus-stack Helm 값으로 위 설정을 관리한다.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    scrapeInterval: "30s"
    scrapeTimeout: "10s"
    evaluationInterval: "30s"
    externalLabels:
      cluster: production-k8s
      env: production
    retention: "15d"
    retentionSize: "500GB"
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-storage
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 600Gi           # retentionSize보다 여유 있게 설정
```

---

### 5.2.2 단일 인스턴스 구성 제약 및 운영 고려사항

현재 구성은 **단일 Prometheus 인스턴스(HA 없음)**이다. 운영 시 아래 제약 사항을 인지하고 대응 방안을 준비한다.

| 제약 사항 | 설명 | 영향 | 대응 방안 |
|----------|------|------|-----------|
| **재시작 시 수집 공백 발생** | Pod 재시작 구간(통상 30초~수 분) 동안 메트릭 수집 중단 | 해당 구간 그래프 공백, 알람 오탐 가능 | 계획 재시작은 저트래픽 시간대 수행, 재시작 후 즉시 Targets 확인 |
| **HA 미구성** | 이중화 없음 — Prometheus 다운 시 수집 완전 중단 | 모니터링 및 알람 기능 전체 중단 | 정기 백업(TSDB 스냅샷), 복구 절차 사전 숙지 |
| **TSDB 단일 저장소** | Local PV 단일 노드 의존 | 해당 노드 장애 시 데이터 접근 불가 | PV 노드 고정(nodeAffinity) 확인, 노드 장애 대응 절차 준비 |
| **대규모 클러스터 스케일 한계** | 수집 타겟 과다 시 메모리/CPU 급증 | OOM, 수집 지연 | 1000+ 타겟 환경에서 Thanos/Cortex 도입 검토 |
| **카디널리티 급증 위험** | 고유값이 많은 라벨 사용 시 TSDB 폭발 | 메모리 부족, 수집 불가 | 라벨 설계 가이드 준수, `prometheus_tsdb_symbol_table_size_bytes` 모니터링 |
| **업그레이드 중단** | Helm upgrade 시 Pod 재시작 | 수집 공백 | 업그레이드 전 스냅샷, 저트래픽 시간대 수행 |

---

### 5.2.3 Local PV Retention 설정

Prometheus TSDB는 Local PV (NVMe 4TB 중 할당분)에 저장된다.
`retention.time`과 `retention.size` 중 먼저 충족되는 조건으로 오래된 데이터가 삭제된다.

| 설정 항목 | 값 | 위치 | 설명 |
|----------|-----|------|------|
| `retention.time` | `15d` | `prometheusSpec.retention` | 15일 이후 데이터 자동 삭제 |
| `retention.size` | `500GB` | `prometheusSpec.retentionSize` | TSDB 크기 500GB 초과 시 오래된 블록 삭제 |
| PVC 요청 크기 | `600Gi` | PVC spec | retention.size 대비 20% 여유 확보 |
| StorageClass | `local-storage` | StorageClass | Local PV 정적 프로비저닝 |
| 마운트 경로 | `/prometheus` | Pod volumeMount | TSDB 저장 경로 |
| NVMe 디스크 경로 | `/dev/nvme*` | 호스트 노드 | Local PV 바인딩 대상 |

```bash
# 현재 TSDB 사용량 확인
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 \
  -- df -h /prometheus

# TSDB 블록 목록 확인
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 \
  -- ls -lh /prometheus/

# Prometheus 설정 확인 (retention 포함)
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 \
  -- cat /etc/prometheus/config_out/prometheus.env.yaml | grep -E 'retention|storage'
```

---

## 5.3 Grafana 대시보드 구성

### 5.3.1 프로비저닝 방식

kube-prometheus-stack은 두 가지 방식으로 Grafana 대시보드를 자동 프로비저닝한다.

| 방식 | 설명 | 장점 | 단점 | 사용 시나리오 |
|------|------|------|------|---------------|
| **ConfigMap 방식** | 대시보드 JSON을 ConfigMap에 저장, 특정 네임스페이스에서 자동 감지 | 단순, ArgoCD GitOps 관리 용이 | Pod 재시작 필요 (sidecar 없을 때) | 기본 내장 대시보드 |
| **Sidecar 방식** | `grafana-sc-dashboard` 사이드카 컨테이너가 ConfigMap 변경 감지 후 자동 로드 | 재시작 없이 대시보드 갱신 | 사이드카 리소스 추가 소비 | 운영 중 대시보드 추가/수정 |

kube-prometheus-stack 기본 구성은 Sidecar 방식을 사용한다.

```yaml
# values.yaml
grafana:
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard          # ConfigMap의 이 라벨을 감지
      labelValue: "1"
      searchNamespace: ALL              # 모든 네임스페이스 감지
```

대시보드 ConfigMap 예시:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"             # sidecar가 감지하는 라벨
data:
  my-dashboard.json: |
    { ... Grafana JSON ... }
```

---

### 5.3.2 대시보드 목록

| 대시보드명 | Grafana ID | 용도 | Datasource | 관리 방법 | 비고 |
|-----------|-----------|------|------------|-----------|------|
| Kubernetes / Compute Resources / Cluster | 내장 | 클러스터 전체 CPU/메모리 현황 | Prometheus | Helm 내장 | kube-prometheus-stack 기본 |
| Kubernetes / Compute Resources / Namespace | 내장 | 네임스페이스별 리소스 현황 | Prometheus | Helm 내장 | |
| Kubernetes / Compute Resources / Node | 내장 | 노드별 리소스 현황 | Prometheus | Helm 내장 | |
| Kubernetes / Compute Resources / Pod | 내장 | Pod 상세 리소스 현황 | Prometheus | Helm 내장 | |
| Node Exporter / Full | 1860 | 노드 상세 메트릭 (CPU, MEM, Disk, Net) | Prometheus | ConfigMap / Grafana.com | 96코어, 1TB 메모리 확인 |
| Node Exporter / Nodes | 내장 | 노드 요약 현황 | Prometheus | Helm 내장 | |
| Kubernetes / Networking / Cluster | 내장 | bond0/bond1 네트워크 트래픽 현황 | Prometheus | Helm 내장 | |
| Kubernetes / API Server | 내장 | API Server 요청 처리 현황 | Prometheus | Helm 내장 | |
| Kubernetes / Scheduler | 내장 | 스케줄러 현황 | Prometheus | Helm 내장 | |
| Kubernetes / Controller Manager | 내장 | Controller Manager 현황 | Prometheus | Helm 내장 | |
| Kubernetes / etcd | 내장 | etcd 클러스터 상태 | Prometheus | Helm 내장 | |
| Kubernetes / Persistent Volumes | 내장 | PV/PVC 사용률 현황 | Prometheus | Helm 내장 | Local PV 모니터링 |
| Alertmanager / Overview | 내장 | Alertmanager 알람 현황 | Prometheus | Helm 내장 | |
| Prometheus / Overview | 내장 | Prometheus 자체 상태 | Prometheus | Helm 내장 | |
| OpenSearch Overview | 커스텀 | OpenSearch 클러스터 상태 | Prometheus | ConfigMap (커스텀) | opensearch-exporter 메트릭 |
| Fluent Bit Overview | 커스텀 | 로그 수집/전송 처리량 | Prometheus | ConfigMap (커스텀) | Fluent Bit 내장 메트릭 |
| Namespace Overview | 커스텀 | 네임스페이스 요약 (운영 현황판) | Prometheus | ConfigMap (커스텀) | 전체 현황 한 눈에 |

---

### 5.3.3 Datasource 구성

| Datasource 이름 | 유형 | URL | 기본 Datasource | 인증 | 비고 |
|----------------|------|-----|----------------|------|------|
| `Prometheus` | Prometheus | `http://prometheus-operated.monitoring.svc.cluster.local:9090` | 예 | 없음 | 기본 메트릭 소스 |
| `Alertmanager` | Alertmanager | `http://alertmanager-operated.monitoring.svc.cluster.local:9093` | 아니오 | 없음 | 알람 현황 조회 |
| `OpenSearch` | OpenSearch | `https://opensearch.logging.svc.cluster.local:9200` | 아니오 | Basic Auth | 로그 검색 (옵션) |

```yaml
# values.yaml - Grafana datasource 설정
grafana:
  additionalDataSources:
    - name: Prometheus
      type: prometheus
      url: http://prometheus-operated.monitoring.svc.cluster.local:9090
      isDefault: true
      access: proxy
    - name: Alertmanager
      type: alertmanager
      url: http://alertmanager-operated.monitoring.svc.cluster.local:9093
      access: proxy
      jsonData:
        handleGrafanaManagedAlerts: false
        implementation: prometheus
```

---

## 5.4 Metric 파이프라인 점검

### 5.4.1 점검 항목 표

| # | 점검 항목 | 점검 방법 | 정상 기준 | 결과 |
|---|----------|-----------|-----------|------|
| 1 | Prometheus Pod 상태 | `kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus` | `Running 2/2` | |
| 2 | Prometheus 자체 Health | `curl http://localhost:9090/-/ready` (port-forward) | `Prometheus Server is Ready.` | |
| 3 | 전체 Targets 수집 상태 | Prometheus UI → Status → Targets | `state: up` 비율 ≥ 95% | |
| 4 | ServiceMonitor 등록 수 확인 | `kubectl get servicemonitor -n monitoring --no-headers \| wc -l` | 배포 목록과 수량 일치 | |
| 5 | PrometheusRule 적용 확인 | Prometheus UI → Status → Rules | 모든 규칙 그룹 정상 로드 | |
| 6 | Alertmanager 연동 확인 | Prometheus UI → Status → Runtime & Build Info → Alertmanagers | Alertmanager URL 표시 | |
| 7 | TSDB 상태 확인 | `curl http://localhost:9090/api/v1/status/tsdb` | `headStats.numSeries` > 0 | |
| 8 | WAL 정상 여부 | `kubectl logs -n monitoring prometheus-* -c prometheus \| grep -i "wal\|corrupt"` | 오류 로그 없음 | |
| 9 | Grafana Datasource 연결 | Grafana UI → Configuration → Data Sources → Test | `Data source connected` | |
| 10 | Grafana 대시보드 데이터 표시 | `Kubernetes / Compute Resources / Cluster` 대시보드 확인 | 전체 패널 데이터 표시 | |
| 11 | 수집 대상 누락 확인 | Prometheus UI → Status → Targets → 필터: `state=down` | 결과 없음 (down 타겟 0) | |
| 12 | 메트릭 카디널리티 확인 | `curl http://localhost:9090/api/v1/status/tsdb \| jq '.data.seriesCountByMetricName[:5]'` | 상위 시리즈 수 이상값 없음 | |

---

### 5.4.2 Prometheus Target 수집 상태 확인

```bash
# port-forward 설정
kubectl port-forward svc/prometheus-operated 9090:9090 -n monitoring &

# 전체 타겟 상태 조회
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, health: .health, lastScrape: .lastScrape}'

# down 상태 타겟만 필터링
curl -s 'http://localhost:9090/api/v1/targets?state=unhealthy' | jq '.data.activeTargets[] | {job: .labels.job, instance: .labels.instance, lastError: .lastError}'

# 타겟 수 요약
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets | group_by(.health) | map({health: .[0].health, count: length})'
```

---

### 5.4.3 ServiceMonitor CR별 수집 확인

Prometheus UI에서 `Status → Targets`를 확인하거나, 아래 API를 통해 점검한다.

```bash
# job별 타겟 요약 확인
curl -s http://localhost:9090/api/v1/targets | \
  jq '.data.activeTargets | group_by(.labels.job) | map({job: .[0].labels.job, count: length, health: ([.[].health] | unique)})'
```

| ServiceMonitor CR명 | 수집 대상 (job) | 수집 주기 | 최근 수집 시각 | 상태 | 비고 |
|--------------------|----------------|-----------|--------------|------|------|
| `kube-prometheus-stack-apiserver` | `apiserver` | 30s | | | |
| `kube-prometheus-stack-coredns` | `coredns` | 15s | | | |
| `kube-prometheus-stack-etcd` | `etcd` | 30s | | | |
| `kube-prometheus-stack-kube-controller-manager` | `kube-controller-manager` | 30s | | | |
| `kube-prometheus-stack-kube-proxy` | `kube-proxy` | 30s | | | |
| `kube-prometheus-stack-kube-scheduler` | `kube-scheduler` | 30s | | | |
| `kube-prometheus-stack-kube-state-metrics` | `kube-state-metrics` | 30s | | | |
| `kube-prometheus-stack-kubelet` | `kubelet` | 30s | | | cAdvisor 포함 |
| `kube-prometheus-stack-node-exporter` | `node-exporter` | 30s | | | 노드 수만큼 타겟 |
| `kube-prometheus-stack-operator` | `prometheus-operator` | 30s | | | |
| `kube-prometheus-stack-prometheus` | `prometheus` | 30s | | | |
| `kube-prometheus-stack-alertmanager` | `alertmanager` | 30s | | | |
| `custom-app-monitor` | `custom-app` | 60s | | | |
| `opensearch-monitor` | `opensearch` | 60s | | | |
| `fluent-bit-monitor` | `fluent-bit` | 30s | | | |

---

### 5.4.4 검증 PromQL 쿼리 목록

Prometheus UI (`/graph`) 또는 Grafana Explore에서 아래 쿼리를 실행하여 파이프라인 정상 여부를 검증한다.

```bash
# Prometheus API를 통한 쿼리 실행 예시
curl -s "http://localhost:9090/api/v1/query?query=up" | jq '.data.result | length'
```

| # | PromQL 쿼리 | 검증 목적 | 정상 기준 | 결과값 |
|---|-------------|----------|-----------|--------|
| 1 | `up == 1` | 전체 수집 타겟 Up 상태 | 전체 타겟 수와 일치 (down 없음) | |
| 2 | `count(up == 0)` | Down 타겟 수 확인 | `0` (또는 결과 없음) | |
| 3 | `count(up) by (job)` | job별 타겟 수 확인 | 각 job별 예상 타겟 수와 일치 | |
| 4 | `rate(node_cpu_seconds_total{mode!="idle"}[5m])` | 노드 CPU 수집 정상 여부 | 96코어 기준 값 반환 | |
| 5 | `sum(node_cpu_seconds_total) by (instance)` | 노드별 CPU 메트릭 수집 | 모든 노드 인스턴스 반환 | |
| 6 | `container_memory_working_set_bytes{container!=""}` | 컨테이너 메모리 메트릭 수집 | 모든 실행 중 컨테이너 반환 | |
| 7 | `sum(container_memory_working_set_bytes{container!=""}) by (namespace)` | 네임스페이스별 메모리 사용량 | 각 네임스페이스 값 반환 | |
| 8 | `kube_pod_status_phase` | Pod 상태 메트릭 수집 | Running/Pending/Failed 값 반환 | |
| 9 | `kube_pod_status_phase{phase="Running"} == 1` | Running Pod 목록 | 실제 Running Pod 수와 일치 | |
| 10 | `kube_node_status_condition{condition="Ready",status="true"}` | 노드 Ready 상태 | 전체 노드 수와 일치, 값 = 1 | |
| 11 | `kube_node_status_condition{condition="Ready",status="true"} == 0` | 노드 NotReady 확인 | 결과 없음 | |
| 12 | `kubelet_running_pods` | kubelet 실행 중 Pod 수 | 노드별 실제 Pod 수와 유사 | |
| 13 | `kubelet_running_containers` | kubelet 실행 중 컨테이너 수 | 양수 값 반환 | |
| 14 | `prometheus_tsdb_head_series` | Prometheus TSDB 시리즈 수 | 양수 값, 급격한 증가 없음 | |
| 15 | `rate(prometheus_tsdb_head_samples_appended_total[5m])` | Prometheus 샘플 수집 속도 | 양수 값 (수집 중) | |
| 16 | `prometheus_target_scrape_pool_targets` | scrape pool별 타겟 수 | 배포된 ServiceMonitor 타겟 수 합계 | |
| 17 | `node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes` | 노드 메모리 가용률 | 1TB 기준 충분한 여유 | |
| 18 | `node_filesystem_avail_bytes{mountpoint="/"}` | 노드 루트 디스크 여유 공간 | 여유 공간 > 20% | |
| 19 | `node_filesystem_avail_bytes{mountpoint=~"/mnt/.*\|/data.*"}` | NVMe 마운트 포인트 여유 공간 | 여유 공간 > 20% | |
| 20 | `ALERTS{alertstate="firing"}` | 현재 발화 중인 알람 | 예상한 알람만 표시 | |

---

### 5.4.5 Grafana 대시보드 데이터 조회 확인

```bash
# Grafana API를 통한 대시보드 목록 확인
curl -s -u admin:<password> http://localhost:3000/api/search | jq '.[].title'

# 특정 대시보드 UID 확인
curl -s -u admin:<password> http://localhost:3000/api/search?query=cluster | jq '.[].uid'

# Grafana Health 확인
curl -s http://localhost:3000/api/health
```

| 대시보드명 | 확인 방법 | 정상 기준 | 결과 |
|-----------|-----------|-----------|------|
| Kubernetes / Compute Resources / Cluster | 모든 패널 로드 확인 | CPU/Memory 패널 데이터 표시 | |
| Node Exporter / Full | 노드 선택 후 패널 확인 | 96코어, 1TB 기준 수치 표시 | |
| Kubernetes / Persistent Volumes | PV 목록 및 사용률 확인 | Local PV 사용률 표시 | |
| Alertmanager / Overview | 알람 그룹 표시 확인 | 알람 발화/해소 현황 표시 | |

---

## 5.5 Metric 파이프라인 장애 패턴 및 조치

| # | 증상 | 원인 | 확인 명령 | 조치 방법 |
|---|------|------|-----------|-----------|
| 1 | 특정 타겟 `state: down`, `connection refused` | 대상 서비스 다운 또는 ServiceMonitor 포트/라벨 오류 | `kubectl get pod -n <namespace>` / `kubectl get svc -n <namespace>` / Prometheus UI Targets에서 `lastError` 확인 | ① 대상 Pod/Service 상태 확인 및 재시작 ② ServiceMonitor의 `selector`, `port` 설정 재검토 ③ 대상 서비스에서 `/metrics` 직접 접근 테스트 |
| 2 | Prometheus 메모리 급증, OOM Kill | 고 카디널리티 메트릭 (라벨 값 과다) | `prometheus_tsdb_head_series` 값 확인 / `curl http://localhost:9090/api/v1/status/tsdb \| jq '.data.seriesCountByMetricName[:10]'` | ① 고 카디널리티 메트릭 원인 ServiceMonitor 식별 ② 해당 CR에 `metricRelabelings`로 불필요한 라벨 제거 또는 메트릭 드롭 ③ Prometheus 메모리 limits 증가 (임시) ④ 재발 방지를 위한 라벨 설계 리뷰 |
| 3 | 특정 타겟 `scrape timeout`, 수집 지연 | 타겟 응답 느림 또는 `scrapeTimeout` 설정 부족 | Prometheus UI Targets → `lastError: context deadline exceeded` / `rate(prometheus_target_scrape_duration_seconds[5m])` | ① ServiceMonitor에서 해당 타겟의 `scrapeTimeout` 값 증가 (예: `10s` → `30s`) ② 대상 서비스 성능 점검 ③ `scrapeTimeout`은 반드시 `scrapeInterval`보다 짧게 설정 |
| 4 | Prometheus 시작 실패 또는 데이터 조회 오류, `TSDB corruption` 로그 | TSDB 블록 손상 (갑작스러운 종료, 디스크 오류 등) | `kubectl logs -n monitoring prometheus-* -c prometheus \| grep -i "corrupt\|error\|tsdb"` / `kubectl exec prometheus-* -- ls /prometheus/` | ① 손상된 블록 식별: `kubectl exec prometheus-* -- promtool tsdb analyze /prometheus` ② 손상된 블록 디렉토리 제거 (데이터 손실 감수) ③ 삭제 후 Prometheus 재시작 ④ 재발 방지: 노드 유지보수 전 graceful shutdown 절차 준수 |
| 5 | Prometheus 시작 지연, WAL 재생 오류 | WAL (Write-Ahead Log) 파일 손상 또는 WAL 재생 크기 과다 | `kubectl logs -n monitoring prometheus-* -c prometheus \| grep -i "wal\|replay"` | ① WAL 재생 진행 중이면 완료까지 대기 (대규모 WAL은 수 분 소요) ② WAL 손상 시: `/prometheus/wal` 디렉토리 백업 후 삭제, Prometheus 재시작 ③ 데이터 일부 손실 발생 — Section 9 테스트 일정 재조정 |
| 6 | Prometheus Pod OOM Kill 반복 | 수집 타겟 과다, 카디널리티 급증, 또는 메모리 limits 설정 과소 | `kubectl describe pod -n monitoring prometheus-* \| grep -A5 "OOMKilled"` / `kubectl top pod -n monitoring` | ① 즉시 조치: Helm values에서 `resources.limits.memory` 증가 후 업그레이드 ② 근본 원인 파악: `prometheus_tsdb_head_series` 및 카디널리티 분석 ③ 고 카디널리티 ServiceMonitor에 `metricRelabelings` 적용 ④ 장기적으로 단일 인스턴스 한계 검토 (Thanos/Victoria Metrics 도입 검토) |
| 7 | Grafana 전체 패널 `No data` | Prometheus Datasource URL 오류 또는 Prometheus 자체 다운 | Grafana → Configuration → Data Sources → Test / `kubectl get svc prometheus-operated -n monitoring` | ① `prometheus-operated` 서비스 존재 및 엔드포인트 확인 ② Grafana Pod에서 직접 curl 테스트: `kubectl exec -n monitoring <grafana-pod> -- curl -s http://prometheus-operated.monitoring.svc.cluster.local:9090/-/ready` ③ Prometheus Pod 상태 확인 및 재시작 |
| 8 | Grafana 대시보드 일부 패널 `No data` 또는 데이터 누락 | 특정 메트릭 수집 중단, 라벨 변경으로 쿼리 불일치 | 해당 패널 Edit → Query 탭 → 직접 쿼리 실행 | ① 패널의 PromQL을 Prometheus UI에서 직접 실행하여 데이터 존재 여부 확인 ② 메트릭명 또는 라벨 변경 여부 확인 (kube-prometheus-stack 업그레이드 후 메트릭명 변경 가능) ③ 대시보드 쿼리 수정 |
| 9 | `up` 메트릭은 있으나 Alertmanager에 알람 미전달 | PrometheusRule ruleSelector 불일치 또는 Alertmanager 연결 오류 | Prometheus UI → Status → Rules / Prometheus UI → Status → Alertmanagers | ① Rules 페이지에서 해당 규칙 그룹 로드 여부 확인 ② 로드 안 된 경우: `kubectl get prometheusrule -n monitoring --show-labels` 로 라벨 확인, Prometheus CR의 `ruleSelector`와 비교 ③ Alertmanager 연결 확인: `kubectl get secret alertmanager-kube-prometheus-stack-alertmanager -n monitoring -o yaml` |

---

*이전 섹션: [Section 4: 모니터링 모듈 점검](./04-module-verification.md)*
