# 07. 부하 테스트 환경 구성 가이드

`docs/load-testing/01-05`의 시나리오를 실행할 수 있는 Kubernetes 환경을 준비하기 위한 단계별 가이드입니다. **테스트베드(외부망 minikube)**, **에어갭(내부망)** 두 환경을 모두 다룹니다.

---

## 1. 사전 요구사항

| 항목 | 요구사항 |
|------|----------|
| Kubernetes 클러스터 | v1.32+ (테스트베드 minikube / 운영 vanilla k8s) |
| 노드 자원 | 단일 노드 검증: 8 CPU / 16 GiB RAM / 50 GiB disk |
| 운영 클러스터 | 노드 ≥ 3, 부하기와 대상 분리 권장 |
| 로컬 도구 | `kubectl` 1.32+, `helm` 3, `docker` (이미지 빌드용) |
| Helm 저장소 | (인터넷) prometheus-community / opensearch / fluent |
| Helm 저장소 | (에어갭) `helm pull`로 사전 다운로드 후 `--repo file://` |

---

## 2. 변수 정의 — `lt-config` ConfigMap

모든 테스트 Job/스크립트가 `deploy/load-testing/lt-config.yaml`의 ConfigMap 값을 읽어 동작합니다. **환경 이전 시 이 한 파일만 수정**하면 됩니다.

### 2.1 변수 그룹

| 그룹 | 변수 | 기본값 | 의미 |
|------|------|--------|------|
| **Image** | `LOADTEST_IMAGE` | `loadtest-tools:0.1.0` | 통합 도구 이미지 (에어갭: `${NEXUS}/loadtest-tools:0.1.0`) |
| **Endpoints** | `PROMETHEUS_URL` | `http://kps-prometheus.monitoring.svc:9090` | Prometheus API |
| | `OPENSEARCH_URL` | `http://opensearch-lt-node.monitoring.svc:9200` | OpenSearch REST |
| | `ALERTMANAGER_URL` | `http://kps-alertmanager.monitoring.svc:9093` | Alertmanager API |
| | `GRAFANA_URL` | `http://kps-grafana.monitoring.svc` | Grafana base URL |
| | `NODE_EXPORTER_SVC` | `http://kps-prometheus-node-exporter.monitoring.svc:9100` | NE-02 부하 대상 |
| | `KSM_SVC` | `http://kps-kube-state-metrics.monitoring.svc:8080` | KSM 메트릭 endpoint |
| **Dashboard UIDs** | `DASH_OVERVIEW`, `DASH_OPENSEARCH`, ... | `lt-overview`, `lt-opensearch`, ... | 대시보드 식별자 |
| **Fluent-bit (FB)** | `FLOG_REPLICAS` | `3` (운영: 10) | flog Pod 수 |
| | `FLOG_DELAY` | `100us` | 라인 간 지연 (작을수록 부하↑) |
| **Avalanche (PR)** | `AVALANCHE_REPLICAS` | `2` (운영: 20) | 합성 endpoint 수 |
| | `AVALANCHE_GAUGE_METRIC_COUNT` | `200` | Pod당 metric 수 |
| | `AVALANCHE_SERIES_COUNT` | `200` | metric당 series 수 |
| **k6** | `K6_PROMQL_VUS` | `20` | PR-03 동시 사용자 |
| | `K6_PROMQL_DURATION` | `5m` | PR-03 부하 시간 |
| | `K6_SEARCH_VU_TARGET` | `50` | OS-02 최대 VU |
| **kube-burner (KSM)** | `KSM_BURNER_ITERATIONS` | `100` (운영: 10000) | Pod 생성 수 |
| | `KSM_BURNER_QPS` | `20` | API QPS 제한 |
| **hey (NE)** | `HEY_CONCURRENCY` | `50` | 동시 연결 |
| | `HEY_DURATION` | `2m` | 부하 시간 |
| | `HEY_RPS_PER_WORKER` | `50` | worker당 RPS |
| **opensearch-benchmark (OS)** | `OSB_WORKLOAD` | `geonames` | 벤치마크 워크로드 |
| | `OSB_TEST_PROCEDURE` | `append-no-conflicts-index-only` | 절차 |

### 2.2 환경별 적용 패턴

**테스트베드(소규모)**:
```bash
# 기본값 그대로 사용
kubectl apply -f deploy/load-testing/lt-config.yaml
```

**운영 / 대규모 환경**: 다음 중 하나
```bash
# (a) 직접 편집 후 apply
vi deploy/load-testing/lt-config.yaml   # FLOG_REPLICAS, KSM_BURNER_ITERATIONS, ...
kubectl apply -f deploy/load-testing/lt-config.yaml

# (b) kustomize patch (권장 — 원본 보존)
cat > overlays/prod/kustomization.yaml <<EOF
resources: ["../.."]
patches:
  - target: { kind: ConfigMap, name: lt-config }
    patch: |
      - op: replace
        path: /data/FLOG_REPLICAS
        value: "10"
      - op: replace
        path: /data/AVALANCHE_REPLICAS
        value: "20"
      - op: replace
        path: /data/KSM_BURNER_ITERATIONS
        value: "10000"
      - op: replace
        path: /data/PROMETHEUS_URL
        value: "http://prometheus.prod.intranet:9090"
      - op: replace
        path: /data/GRAFANA_URL
        value: "http://grafana.prod.intranet"
images:
  - name: loadtest-tools
    newName: nexus.intranet:8082/loadtest/loadtest-tools
    newTag: "0.1.0"
EOF
kubectl apply -k overlays/prod
```

---

## 3. 인프라 설치 절차

### 3.1 테스트베드 (외부망 minikube)

```bash
# 0. minikube 클러스터 준비 (호스트당 1회)
ssh <minikube-host> 'sg docker -c "
  minikube start \
    --driver=docker --cpus=8 --memory=16384 --disk-size=50g \
    --kubernetes-version=stable \
    --listen-address=0.0.0.0 \
    --apiserver-ips=<host-ip> \
    --apiserver-names=<host-name> \
    --addons=metrics-server,ingress
"'

# 1. 통합 도구 이미지 빌드 → minikube 적재
ssh <minikube-host> 'cd /tmp && \
  scp <local>:docker/loadtest-tools/* /tmp/loadtest-tools/ && \
  bash /tmp/loadtest-tools/build.sh && \
  sg docker -c "minikube image load loadtest-tools:0.1.0"'

# 2. monitoring core 배포
bash deploy/load-testing/01-monitoring-core/install.sh

# 3. logging stack (선택)
bash deploy/load-testing/02-logging/install.sh

# 4. 환경 변수 ConfigMap
kubectl apply -f deploy/load-testing/00-namespaces.yaml
kubectl apply -f deploy/load-testing/lt-config.yaml

# 5. 대시보드
bash deploy/load-testing/05-dashboards/install.sh
```

### 3.2 에어갭 (내부망)

```mermaid
flowchart LR
  A[외부망 빌드 호스트] -->|build.sh| I[loadtest-tools:0.1.0]
  I -->|airgap-export.sh| B[loadtest-airgap-X.tar.gz]
  B -->|scp| H[에어갭 호스트]
  H -->|airgap-import.sh| R[(Nexus)]
  R --> K[K8s Pods]
```

```bash
# 외부망에서
cd docker/loadtest-tools
bash build.sh
bash airgap-export.sh
# loadtest-airgap-0.1.0-YYYYMMDD.tar.gz 생성

# 에어갭으로 이전
scp loadtest-airgap-*.tar.gz <airgap-host>:/tmp/

# 에어갭에서
ssh <airgap-host>
tar -xzf /tmp/loadtest-airgap-*.tar.gz -C /tmp
cd /tmp/airgap-bundle
REGISTRY=nexus.intranet:8082/loadtest bash airgap-import.sh
# Nexus push 완료, helm 차트는 /tmp/airgap-bundle/charts/

# 매니페스트 적용 (kustomize overlay 사용)
cd /tmp/airgap-bundle/manifests/load-testing
kustomize edit set image loadtest-tools=nexus.intranet:8082/loadtest/loadtest-tools:0.1.0
kubectl apply -k .
```

---

## 4. 외부 접근 구성 (테스트베드)

minikube docker driver는 NodePort/Ingress가 호스트 외부에 자동 노출되지 않습니다. 다음 socat systemd 서비스로 영구 forwarding:

| 서비스 | 외부 → 내부 | 용도 |
|--------|------------|------|
| `minikube-grafana-3000.service` | `:3000 → 192.168.49.2:30030` | Grafana (NodePort) |
| `minikube-prom-9090.service` | `:9090 → 192.168.49.2:30090` | Prometheus (NodePort) |
| `minikube-ingress-80.service` | `:80 → 192.168.49.2:80` | Ingress (host-based routing) |
| `minikube-ingress-443.service` | `:443 → 192.168.49.2:443` | Ingress TLS |

운영 환경에서는 LoadBalancer / Ingress + 사내 DNS / TLS 정책을 적용하세요.

---

## 5. 검증 체크리스트

배포 직후 다음을 차례로 확인:

```bash
CTX=minikube-remote   # 또는 prod-cluster

# 5.1 Helm releases
helm --kube-context=$CTX -n monitoring list
# kps, opensearch-lt, fluent-bit-lt 모두 STATUS: deployed

# 5.2 Pod 상태
kubectl --context=$CTX -n monitoring get pods
# 모든 Pod READY 1/1 (Grafana는 3/3)

# 5.3 ConfigMap 변수 확인
kubectl --context=$CTX -n load-test describe configmap lt-config
# 39개 키 모두 확인

# 5.4 Endpoint 도달성
kubectl --context=$CTX -n monitoring exec deploy/opensearch-exporter -- \
  wget -qO- http://localhost:9114/healthz
kubectl --context=$CTX -n load-test exec deploy/avalanche -- wget -qO- http://localhost:9001/metrics | head -3

# 5.5 Prometheus target health
curl -sG '${PROMETHEUS_URL}/api/v1/query' \
  --data-urlencode 'query=count by (job) (up==1)' | jq
# 모든 핵심 job: apiserver, kubelet, node-exporter, kube-state-metrics,
# kps-prometheus, kps-grafana, fluent-bit-lt, opensearch-exporter

# 5.6 대시보드 자동 로드 확인
curl -s -u admin:admin '${GRAFANA_URL}/api/search?tag=load-test' | jq '.[].title'
# 6개 대시보드 (Overview + 5개 컴포넌트)
```

---

## 6. 환경 비교 표

| 항목 | 테스트베드 (minikube) | 운영 / 에어갭 |
|------|----------------------|--------------|
| 노드 수 | 1 | 3+ (HA / 분리) |
| OpenSearch 모드 | single-node, 보안 비활성 | 3+ data, 3 master, 보안 활성 |
| Prometheus retention | 6h | 15d+ |
| Grafana auth | admin/admin | SSO/OIDC |
| 이미지 | 호스트 docker → minikube image load | Nexus push, Pod pull |
| 변수 | `lt-config.yaml` 직접 편집 | kustomize overlay (`overlays/prod/`) |
| 부하 규모 | FLOG_REPLICAS=3, KSM_BURNER=100 | FLOG_REPLICAS=10, KSM_BURNER=10000 |
| 대시보드 접근 | `http://192.168.101.197:3000` (socat) | 사내 Ingress + SSO |

---

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `ImagePullBackOff` (테스트베드) | minikube containerd에 이미지 미적재 | `minikube image load loadtest-tools:0.1.0` |
| `ImagePullBackOff` (에어갭) | Nexus 인증 실패 | `kubectl create secret docker-registry` + `imagePullSecrets` |
| Grafana OOMKilled | 256Mi 부족 | `values.yaml`의 grafana resources 상향 |
| OpenSearch 시작 실패 | `vm.max_map_count` 부족 | sysctl 또는 chart의 `sysctlInit: enabled: true` |
| Job pod template immutable | 매니페스트 수정 후 apply | 기존 Job `kubectl delete` 후 재생성 |
| ServiceMonitor 미픽업 | 라벨 불일치 | `prometheusSpec.serviceMonitorSelector: {}` 확인 |
| `$(VAR)` 치환 안 됨 | env: 또는 envFrom: 누락 | Job spec에 ConfigMap reference 추가 |

---

## 8. 다음 단계

설치 완료 후:
- **시나리오별 실행 방법**: [`08-scenario-catalog.md`](./08-scenario-catalog.md)
- **운영 절차서**: [`06-test-execution-plan.md`](./06-test-execution-plan.md)
- **개별 가이드**: `01-opensearch-load-test.md` ~ `05-kube-state-metrics-load-test.md`
