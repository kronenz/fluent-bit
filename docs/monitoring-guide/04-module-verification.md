# Section 4: 모니터링 모듈 점검

> 본 섹션은 모니터링 스택(Prometheus, Alertmanager, Grafana, Fluent Bit, OpenSearch, k8sAlert) 배포 완료 후 운영 전 수행하는 전체 점검 절차를 기술한다.
> Section 9 성능 테스트의 기준선(Baseline) 측정도 본 섹션에서 수행한다.

---

## 4.1 전체 점검 체크리스트

모든 모듈에 대해 아래 순서로 점검을 진행한다. 각 항목의 결과를 표에 기록하여 운영 인수 문서로 보관한다.

| # | 모듈 | 점검명 | 점검 명령 | 정상 기준 | 결과 |
|---|------|--------|-----------|-----------|------|
| 1 | Prometheus | Pod 실행 상태 확인 | `kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus` | `Running` / `1/1` 또는 `2/2` | |
| 2 | Prometheus | PVC Bound 확인 | `kubectl get pvc -n monitoring -l app.kubernetes.io/name=prometheus` | `Bound` | |
| 3 | Prometheus | Scrape Target 수집 상태 | `kubectl port-forward svc/prometheus-operated 9090 -n monitoring` → `/api/v1/targets` | `state: "up"` 비율 ≥ 95% | |
| 4 | Prometheus | ServiceMonitor 등록 수 | `kubectl get servicemonitor -n monitoring --no-headers \| wc -l` | 배포된 CR 수와 일치 | |
| 5 | Prometheus | PrometheusRule 등록 수 | `kubectl get prometheusrule -n monitoring --no-headers \| wc -l` | 배포된 CR 수와 일치 | |
| 6 | Alertmanager | Pod 실행 상태 확인 | `kubectl get pod -n monitoring -l app.kubernetes.io/name=alertmanager` | `Running` / `2/2` | |
| 7 | Alertmanager | Webhook 수신 확인 | `kubectl port-forward svc/alertmanager-operated 9093 -n monitoring` → `/api/v2/status` | `clusterStatus.uptime` 존재 | |
| 8 | Alertmanager | k8sAlert 연동 확인 | Alertmanager UI → Receivers 탭 | `k8salert-webhook` 수신자 표시 | |
| 9 | Grafana | Pod 실행 상태 확인 | `kubectl get pod -n monitoring -l app.kubernetes.io/name=grafana` | `Running` / `1/1` | |
| 10 | Grafana | 외부 접근 (bond0) | `curl -sk https://<bond0-IP>:3000/api/health` | `{"database":"ok"}` | |
| 11 | Grafana | Datasource 연결 확인 | Grafana UI → Configuration → Data Sources → Test | `Data source connected` | |
| 12 | Grafana | 대시보드 프로비저닝 확인 | Grafana UI → Dashboards → Browse | 사전 정의 대시보드 모두 표시 | |
| 13 | Fluent Bit | Pod 실행 상태 확인 | `kubectl get pod -n logging -l app.kubernetes.io/name=fluent-bit` | `Running` / `1/1` (DaemonSet 전체 노드) | |
| 14 | Fluent Bit | 파이프라인 CR 바인딩 확인 | `kubectl get clusterfluentbitconfig` | `ACTIVE: true` | |
| 15 | Fluent Bit | 로그 수집 및 전송 확인 | `kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=50` | `[engine] started` / OpenSearch 전송 오류 없음 | |
| 16 | Fluent Bit | ClusterOutput 상태 확인 | `kubectl get clusteroutput` | 등록된 출력 플러그인 정상 표시 | |
| 17 | OpenSearch | Pod 실행 상태 확인 | `kubectl get pod -n logging -l app=opensearch` | 모든 Pod `Running` | |
| 18 | OpenSearch | 클러스터 Health 확인 | `kubectl exec -n logging opensearch-master-0 -- curl -sk http://localhost:9200/_cluster/health` | `status: "green"` | |
| 19 | OpenSearch | PVC Bound 확인 | `kubectl get pvc -n logging` | 모든 PVC `Bound` | |
| 20 | OpenSearch Dashboards | 외부 접근 (bond0) | `curl -sk https://<bond0-IP>:5601/api/status` | `status.overall.state: "green"` | |
| 21 | k8sAlert | Pod 실행 상태 확인 | `kubectl get pod -n k8salert` | `Running` / `1/1` | |
| 22 | k8sAlert | Webhook 수신 엔드포인트 확인 | `kubectl logs -n k8salert -l app=k8salert --tail=30` | 수신 로그 정상 출력, 오류 없음 | |
| 23 | ArgoCD | 앱 Sync/Health 상태 | `argocd app list` 또는 ArgoCD UI | 모든 앱 `Synced` / `Healthy` | |

---

## 4.2 컴포넌트별 상태 점검

### 4.2.1 Pod Running 상태 (네임스페이스별)

#### monitoring 네임스페이스

```bash
kubectl get pod -n monitoring -o wide
```

| Pod명 (prefix) | 종류 | 예상 수 | 정상 상태 | 비고 |
|----------------|------|---------|-----------|------|
| `prometheus-kube-prometheus-stack-prometheus-0` | StatefulSet | 1 | `Running 2/2` | Prometheus + config-reloader |
| `alertmanager-kube-prometheus-stack-alertmanager-0` | StatefulSet | 1 | `Running 2/2` | Alertmanager + config-reloader |
| `kube-prometheus-stack-grafana-*` | Deployment | 1 | `Running 3/3` | Grafana + init containers |
| `kube-prometheus-stack-kube-state-metrics-*` | Deployment | 1 | `Running 1/1` | |
| `kube-prometheus-stack-prometheus-node-exporter-*` | DaemonSet | 노드 수 | `Running 1/1` | 전체 노드 배포 확인 |
| `kube-prometheus-stack-operator-*` | Deployment | 1 | `Running 1/1` | Prometheus Operator |

#### logging 네임스페이스

```bash
kubectl get pod -n logging -o wide
```

| Pod명 (prefix) | 종류 | 예상 수 | 정상 상태 | 비고 |
|----------------|------|---------|-----------|------|
| `fluent-bit-*` | DaemonSet | 노드 수 | `Running 1/1` | 전체 노드 배포 확인 |
| `opensearch-master-*` | StatefulSet | 3 | `Running 1/1` | |
| `opensearch-data-hot-*` | StatefulSet | 설정값 | `Running 1/1` | |
| `opensearch-data-cold-*` | StatefulSet | 설정값 | `Running 1/1` | |
| `opensearch-dashboards-*` | Deployment | 1 | `Running 1/1` | |

#### k8salert 네임스페이스

```bash
kubectl get pod -n k8salert -o wide
```

| Pod명 (prefix) | 종류 | 예상 수 | 정상 상태 | 비고 |
|----------------|------|---------|-----------|------|
| `k8salert-*` | Deployment | 1 | `Running 1/1` | Webhook 수신 서버 |

---

### 4.2.2 Local PV / PVC Bound 상태

Local PV는 NVMe 디스크 경로에 정적 프로비저닝되며, Bound 상태가 아닌 경우 해당 노드의 경로 및 StorageClass를 확인한다.

```bash
# PV 전체 목록 확인
kubectl get pv -o wide

# PVC 상태 확인
kubectl get pvc -n monitoring
kubectl get pvc -n logging
```

| PVC명 | 네임스페이스 | 바인딩 PV | StorageClass | 용량 | 정상 상태 | 비고 |
|-------|-------------|-----------|--------------|------|-----------|------|
| `prometheus-kube-prometheus-stack-prometheus-0` | monitoring | local-pv-prometheus | local-storage | 500Gi | `Bound` | Prometheus TSDB |
| `alertmanager-kube-prometheus-stack-alertmanager-0` | monitoring | local-pv-alertmanager | local-storage | 10Gi | `Bound` | |
| `opensearch-data-opensearch-master-0` | logging | local-pv-os-master-0 | local-storage | 설정값 | `Bound` | |
| `opensearch-data-opensearch-master-1` | logging | local-pv-os-master-1 | local-storage | 설정값 | `Bound` | |
| `opensearch-data-opensearch-master-2` | logging | local-pv-os-master-2 | local-storage | 설정값 | `Bound` | |
| `opensearch-data-opensearch-data-hot-*` | logging | local-pv-os-hot-* | local-storage | 설정값 | `Bound` | |
| `opensearch-data-opensearch-data-cold-*` | logging | local-pv-os-cold-* | local-storage | 설정값 | `Bound` | |

---

### 4.2.3 ArgoCD Sync / Health 상태

```bash
# ArgoCD CLI 사용 시
argocd app list

# kubectl 사용 시
kubectl get application -n argocd
```

| 앱명 | 네임스페이스 | Sync 상태 | Health 상태 | 비고 |
|------|-------------|-----------|-------------|------|
| `kube-prometheus-stack` | monitoring | `Synced` | `Healthy` | Helm Chart 관리 |
| `fluent-bit-operator` | logging | `Synced` | `Healthy` | Helm Chart 관리 |
| `opensearch` | logging | `Synced` | `Healthy` | Helm Chart 관리 |
| `opensearch-dashboards` | logging | `Synced` | `Healthy` | Helm Chart 관리 |
| `k8salert` | k8salert | `Synced` | `Healthy` | 커스텀 매니페스트 |
| `monitoring-cr` | monitoring | `Synced` | `Healthy` | ServiceMonitor/PrometheusRule CR |
| `logging-cr` | logging | `Synced` | `Healthy` | FluentBit Pipeline CR |

> **OutOfSync 발생 시**: `argocd app diff <앱명>` 으로 드리프트 내용 확인 후 `argocd app sync <앱명>` 수행.

---

### 4.2.4 CR 적용 상태 확인

#### ServiceMonitor 등록 목록

```bash
kubectl get servicemonitor -n monitoring
```

| CR명 | 대상 서비스 | 네임스페이스 | 수집 주기 | 등록 상태 |
|------|------------|-------------|-----------|-----------|
| `kube-prometheus-stack-apiserver` | kube-apiserver | default | 30s | 정상 |
| `kube-prometheus-stack-coredns` | kube-dns | kube-system | 15s | 정상 |
| `kube-prometheus-stack-etcd` | etcd | kube-system | 30s | 정상 |
| `kube-prometheus-stack-kube-controller-manager` | kube-controller-manager | kube-system | 30s | 정상 |
| `kube-prometheus-stack-kube-scheduler` | kube-scheduler | kube-system | 30s | 정상 |
| `kube-prometheus-stack-kube-state-metrics` | kube-state-metrics | monitoring | 30s | 정상 |
| `kube-prometheus-stack-kubelet` | kubelet | kube-system | 30s | 정상 |
| `kube-prometheus-stack-node-exporter` | node-exporter | monitoring | 30s | 정상 |

#### PrometheusRule 등록 목록

```bash
kubectl get prometheusrule -n monitoring
```

| CR명 | 규칙 그룹 수 | 알람 규칙 수 | 등록 상태 |
|------|------------|-------------|-----------|
| `kube-prometheus-stack-alertmanager.rules` | 1 | ~5 | 정상 |
| `kube-prometheus-stack-etcd` | 1 | ~10 | 정상 |
| `kube-prometheus-stack-general.rules` | 1 | ~5 | 정상 |
| `kube-prometheus-stack-k8s.rules` | 3 | ~20 | 정상 |
| `kube-prometheus-stack-kube-apiserver*` | 2 | ~15 | 정상 |
| `kube-prometheus-stack-kubernetes-resources` | 1 | ~10 | 정상 |
| `kube-prometheus-stack-kubernetes-storage` | 1 | ~8 | 정상 |
| `kube-prometheus-stack-node*` | 3 | ~30 | 정상 |
| `kube-prometheus-stack-prometheus` | 1 | ~10 | 정상 |
| `custom-app-rules` | 사용자 정의 | 사용자 정의 | 정상 |

#### FluentBitConfig 파이프라인 바인딩 확인

```bash
# Fluent Bit Operator CR 전체 확인
kubectl get clusterfluentbitconfig,clusterinput,clusterfilter,clusteroutput
```

| 리소스 종류 | CR명 | 바인딩 상태 | 비고 |
|------------|------|------------|------|
| `ClusterFluentBitConfig` | `fluent-bit-config` | Active | 파이프라인 조합 설정 |
| `ClusterInput` | `tail-kube-logs` | Active | `/var/log/containers/*.log` 수집 |
| `ClusterInput` | `systemd-input` | Active | systemd journal 수집 |
| `ClusterFilter` | `kubernetes-filter` | Active | k8s 메타데이터 enrichment |
| `ClusterFilter` | `modify-filter` | Active | 필드 추가/수정 |
| `ClusterOutput` | `opensearch-output` | Active | OpenSearch 전송 |
| `ClusterOutput` | `stdout-debug` | (비활성) | 디버그 용도, 운영 시 비활성화 |

> **파이프라인 바인딩 미연결 시**: `kubectl describe clusterfluentbitconfig <이름>` 으로 selector 확인.

---

### 4.2.5 Ingress / TLS / 외부 접근 확인 (bond0 기준)

bond0 인터페이스(Public, 25G+25G LACP)를 통한 외부 접근을 확인한다.

```bash
# Ingress 목록 확인
kubectl get ingress -A

# 또는 NodePort/LoadBalancer 서비스 확인
kubectl get svc -n monitoring
kubectl get svc -n logging
```

| 서비스 | 접근 주소 (bond0 IP 기준) | 포트 | 프로토콜 | TLS | 접근 확인 명령 |
|--------|--------------------------|------|---------|-----|----------------|
| Grafana | `https://<bond0-IP>:3000` | 3000 | HTTPS | 필요 | `curl -sk https://<bond0-IP>:3000/api/health` |
| Prometheus | `http://<bond0-IP>:9090` | 9090 | HTTP | 선택 | `curl -s http://<bond0-IP>:9090/-/ready` |
| Alertmanager | `http://<bond0-IP>:9093` | 9093 | HTTP | 선택 | `curl -s http://<bond0-IP>:9093/-/ready` |
| OpenSearch Dashboards | `https://<bond0-IP>:5601` | 5601 | HTTPS | 필요 | `curl -sk https://<bond0-IP>:5601/api/status` |
| OpenSearch API | `https://<bond0-IP>:9200` | 9200 | HTTPS | 필요 | `curl -sk https://<bond0-IP>:9200/_cluster/health` |
| k8sAlert Webhook | `http://<bond0-IP>:8080` | 8080 | HTTP | 선택 | `curl -s http://<bond0-IP>:8080/health` |

> **접근 불가 시 확인 순서**: Pod Running → Service 포트 → NodePort/Ingress 설정 → 방화벽/네트워크 정책

---

## 4.3 리소스 사용량 기준선 측정

> 기준선 측정은 배포 완료 후 안정화 기간(최소 1시간) 이후 수행한다.
> 측정 결과는 Section 9 성능 테스트와 비교하는 기준값으로 활용한다.
> `kubectl top` 명령은 metrics-server가 활성화된 환경에서 사용 가능하다.

```bash
# Pod 별 리소스 사용량 확인
kubectl top pod -n monitoring
kubectl top pod -n logging
kubectl top pod -n k8salert

# PV 사용량 확인 (Prometheus)
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 \
  -- df -h /prometheus

# PV 사용량 확인 (OpenSearch)
kubectl exec -n logging opensearch-master-0 -- df -h /usr/share/opensearch/data
```

| 컴포넌트 | Pod명 | CPU 사용량 (cores) | Memory 사용량 | PV 사용량 | 측정 일시 | 비고 |
|---------|-------|-------------------|---------------|-----------|-----------|------|
| prometheus-server | `prometheus-kube-prometheus-stack-prometheus-0` | | | /prometheus | | TSDB 포함 |
| alertmanager | `alertmanager-kube-prometheus-stack-alertmanager-0` | | | /alertmanager | | |
| grafana | `kube-prometheus-stack-grafana-*` | | | N/A | | PV 미사용 |
| fluent-bit | `fluent-bit-<node>` (대표 1개) | | | N/A | | DaemonSet |
| opensearch-master-0 | `opensearch-master-0` | | | /usr/share/opensearch/data | | |
| opensearch-master-1 | `opensearch-master-1` | | | /usr/share/opensearch/data | | |
| opensearch-master-2 | `opensearch-master-2` | | | /usr/share/opensearch/data | | |
| opensearch-data-hot-0 | `opensearch-data-hot-0` | | | /usr/share/opensearch/data | | NVMe |
| opensearch-data-hot-1 | `opensearch-data-hot-1` | | | /usr/share/opensearch/data | | NVMe |
| opensearch-data-cold-0 | `opensearch-data-cold-0` | | | /usr/share/opensearch/data | | |
| opensearch-dashboards | `opensearch-dashboards-*` | | | N/A | | PV 미사용 |
| k8salert | `k8salert-*` | | | N/A | | PV 미사용 |

**서버 전체 기준선 (인프라)**

| 측정 항목 | 측정 명령 | 기준선 값 | 측정 일시 |
|----------|-----------|----------|-----------|
| 전체 CPU 사용률 | `kubectl top node` | | |
| 전체 Memory 사용률 | `kubectl top node` | | |
| NVMe I/O (write) | `iostat -x 1 5` (노드 직접) | | |
| NVMe I/O (read) | `iostat -x 1 5` (노드 직접) | | |
| bond0 네트워크 처리량 | `sar -n DEV 1 5` (노드 직접) | | |
| bond1 네트워크 처리량 | `sar -n DEV 1 5` (노드 직접) | | |

> **측정 담당자**: \_\_\_\_\_\_\_\_\_\_  **측정 일시**: \_\_\_\_\_\_\_\_\_\_\_\_\_\_

---

## 4.4 주요 장애 패턴 및 조치

배포 후 발생 빈도가 높은 장애 패턴과 조치 방법을 정리한다.

| # | 증상 | 원인 | 확인 명령 | 조치 방법 |
|---|------|------|-----------|-----------|
| 1 | Pod `Pending` 상태 지속, PVC `Pending` | Local PV NVMe 경로 오류 또는 노드 레이블 불일치 | `kubectl describe pvc <pvc명> -n <ns>` / `kubectl describe pv <pv명>` | ① 해당 노드 NVMe 마운트 경로 확인 (`lsblk`, `df -h`) ② PV nodeAffinity의 hostname 레이블과 노드 실제 레이블 비교 (`kubectl get node --show-labels`) ③ PV/PVC 재생성 또는 노드 레이블 수정 |
| 2 | Fluent Bit 로그가 OpenSearch에 인입되지 않음, `ClusterFluentBitConfig` 비활성 | FluentBitConfig 파이프라인 label selector mismatch | `kubectl describe clusterfluentbitconfig <이름>` → `Selector` 항목 확인 | ① `ClusterFluentBitConfig`의 `fluentBitConfigSelector` 라벨과 FluentBit DaemonSet 레이블 비교 ② 누락된 라벨 추가: `kubectl label fluentbit <이름> -n logging <key>=<value>` ③ 파이프라인 재로드 확인 |
| 3 | Prometheus Targets 화면에서 특정 서비스 `Unknown` 또는 누락 | ServiceMonitor 라벨이 Prometheus `serviceMonitorSelector`와 불일치 | `kubectl get prometheus -n monitoring -o yaml \| grep -A5 serviceMonitorSelector` / `kubectl get servicemonitor <이름> -n monitoring -o yaml \| grep labels` | ① Prometheus CR의 `serviceMonitorSelector.matchLabels` 값 확인 ② 해당 ServiceMonitor에 필요한 라벨 추가: `kubectl label servicemonitor <이름> -n monitoring <key>=<value>` ③ 변경 후 Prometheus Pod reload 확인 |
| 4 | Alertmanager에 알람이 수신되지 않음, PrometheusRule 미반영 | PrometheusRule의 `ruleSelector` 또는 네임스페이스 selector 불일치 | `kubectl get prometheus -n monitoring -o yaml \| grep -A10 ruleSelector` / `kubectl describe prometheusrule <이름> -n monitoring` | ① Prometheus CR의 `ruleSelector.matchLabels` 확인 ② 해당 PrometheusRule에 필요한 라벨 추가 ③ `kubectl get prometheusrule -n monitoring --show-labels` 로 현재 라벨 전체 확인 |
| 5 | k8sAlert로 알람 메시지가 전달되지 않음, Alertmanager 로그에 `connection refused` | k8sAlert Webhook URL 연결 실패 (서비스 다운 또는 URL 오류) | `kubectl logs -n monitoring alertmanager-* \| grep -i webhook` / `kubectl get svc -n k8salert` / `curl -s http://<k8salert-svc>:8080/health` | ① k8sAlert Pod 상태 확인: `kubectl get pod -n k8salert` ② Service/Endpoint 확인: `kubectl get ep -n k8salert` ③ Alertmanager 설정의 Webhook URL 수정: `kubectl edit secret alertmanager-kube-prometheus-stack-alertmanager -n monitoring` ④ Alertmanager 재시작 |
| 6 | OpenSearch 클러스터 `yellow` 또는 `red` 상태 | 샤드 미할당 (Unassigned shards) — 노드 다운 또는 디스크 부족 | `curl -s http://localhost:9200/_cluster/health?pretty` / `curl -s http://localhost:9200/_cat/shards?v\&h=index,shard,prirep,state,node,reason` | ① `red`: 주 샤드 미할당 — 해당 데이터 노드 Pod 상태 확인 후 재시작 ② `yellow`: 복제 샤드 미할당 — 단일 노드 구성이면 정상, 다중 노드면 디스크 용량 확인 ③ 디스크 임계값 확인: `curl -s http://localhost:9200/_cluster/settings` (watermark 설정) ④ ISM 정책으로 오래된 인덱스 삭제 검토 |
| 7 | Grafana 대시보드 전체 `No data` 또는 패널 오류 | Prometheus Datasource 연결 실패 (URL 오류 또는 인증 문제) | Grafana UI → Configuration → Data Sources → Prometheus → Test 클릭 / `kubectl logs -n monitoring kube-prometheus-stack-grafana-* -c grafana \| grep -i datasource` | ① Datasource URL 확인: `http://prometheus-operated.monitoring.svc.cluster.local:9090` ② Service 존재 확인: `kubectl get svc prometheus-operated -n monitoring` ③ Grafana Pod에서 직접 접근 테스트: `kubectl exec -n monitoring <grafana-pod> -- curl -s http://prometheus-operated:9090/-/ready` |
| 8 | ArgoCD 앱이 `OutOfSync` 상태로 계속 유지 | Git 저장소의 매니페스트와 클러스터 실제 상태 불일치 (수동 변경, Helm 값 드리프트 등) | `argocd app diff <앱명>` / `argocd app get <앱명>` / `kubectl get application <앱명> -n argocd -o yaml` | ① `argocd app diff <앱명>` 으로 차이점 확인 ② 클러스터에 수동 변경이 있다면 Git으로 원복: `argocd app sync <앱명> --force` ③ 의도적인 변경이라면 Git 저장소 업데이트 후 동기화 ④ `ignoreDifferences` 설정으로 허용할 드리프트 무시 처리 검토 |

---

*다음 섹션: [Section 5: Metric 파이프라인 구성 및 점검](./05-metric-pipeline.md)*
