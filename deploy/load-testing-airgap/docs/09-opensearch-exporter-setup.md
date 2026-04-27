# OpenSearch Exporter 구성 가이드

OpenSearch 의 Prometheus 메트릭을 노출하는 두 방식의 비교 + 권장 (plugin) 설치 절차.

## 0. 두 옵션 비교

| 항목 | 옵션 A — 외부 sidecar | 옵션 B — OS plugin (권장) |
|------|----------------------|--------------------------|
| 도구 | `prometheus-community/elasticsearch-exporter` (별도 Pod) | `aiven/prometheus-exporter-plugin-for-opensearch` (OS pod 내부) |
| 메트릭 prefix | `elasticsearch_*` | `opensearch_*` |
| 노출 endpoint | 별도 svc (예: 9114) | OS REST 9200 의 `/_prometheus/metrics` |
| 추가 Pod | 1개 (sidecar Deployment) | 0개 (init container 만) |
| 설치 방법 | helm install/Deployment | OS helm values + plugin .zip |
| 인증 | basic auth env (admin:admin 시크릿) | OS REST 와 동일 (security 비활성 시 인증 불필요) |
| OS 버전 호환성 | 거의 모든 OS/ES 버전 | OS 버전 정확히 일치 (`<X.Y.Z>.0`) |
| 폐쇄망 친화도 | sidecar image 만 mirror | plugin .zip 1개만 mirror |
| 메트릭 풍부도 | cluster + 일부 indices | cluster + per-index + per-node 전부 (228+) |
| 운영 관리 | 추가 컴포넌트 | OS 자체에 묶임 — life cycle 단일 |

운영 권장: **옵션 B (plugin)**. 단일 컴포넌트로 묶이고 메트릭이 더 풍부.

---

## 1. 옵션 B — Plugin 설치 (권장)

### 1.1 사전 준비

| 항목 | 값 |
|------|-----|
| OpenSearch helm chart | `opensearch/opensearch` (`opensearch-2.32.0` 이상) |
| OS 버전 | `2.19.x` (chart 가 패키징한 버전과 일치) |
| Plugin 이름 | `prometheus-exporter` |
| Plugin 버전 | `<OS-Major>.<Minor>.<Patch>.0` — 예: OS 2.19.1 → plugin `2.19.1.0` |
| 다운로드 URL | https://github.com/aiven/prometheus-exporter-plugin-for-opensearch/releases |

### 1.2 폐쇄망 친화 설치 — `extraInitContainers` (검증된 패턴)

helm 의 자동 `plugins.installList` 는 외부 HTTPS URL 을 직접 다운받음 →
폐쇄망에서 사용 어려움. 대안: plugin .zip 을 **ConfigMap 으로 in-cluster 노출**
하고 init container 가 `file://` URL 로 설치.

#### 1.2.1 plugin .zip → ConfigMap

```bash
# 인터넷 zone 에서
curl -fsSL --max-time 60 -o /tmp/prometheus-exporter-2.19.1.0.zip \
  https://github.com/aiven/prometheus-exporter-plugin-for-opensearch/releases/download/2.19.1.0/prometheus-exporter-2.19.1.0.zip

# 폐쇄망: Nexus raw repo 에 업로드해두고 host 에서 curl 로 받기
#   curl -fsSL https://nexus.intranet:8082/repository/opensearch-plugins/prometheus-exporter-2.19.1.0.zip \
#        -o /tmp/prometheus-exporter-2.19.1.0.zip

kubectl -n monitoring create configmap opensearch-prometheus-plugin \
  --from-file=prometheus-exporter-2.19.1.0.zip=/tmp/prometheus-exporter-2.19.1.0.zip
```

#### 1.2.2 helm values 추가 적용

`deploy/load-testing-airgap/00-prerequisites/opensearch-helm-values.yaml` 의
핵심 부분 (전체는 파일 참조):

```yaml
extraVolumes:
  - name: opensearch-prometheus-plugin
    configMap:
      name: opensearch-prometheus-plugin
  - name: opensearch-plugins-shared       # init/main 공유 plugins 디렉터리
    emptyDir: {}

extraVolumeMounts:
  - name: opensearch-plugins-shared
    mountPath: /usr/share/opensearch/plugins

extraInitContainers:
  - name: install-prometheus-exporter
    image: opensearchproject/opensearch:2.19.1
    command:
      - bash
      - -c
      - |
        set -e
        # ① 빌트인 plugin (security/alerting/observability/...) 보존
        cp -r /usr/share/opensearch/plugins/. /shared-plugins/ 2>/dev/null || true
        # ② plugins 디렉터리를 shared volume 으로 redirect
        rm -rf /usr/share/opensearch/plugins
        ln -s /shared-plugins /usr/share/opensearch/plugins
        # ③ idempotent 설치
        if [ -d /shared-plugins/prometheus-exporter ]; then
          echo "already installed"
        else
          bin/opensearch-plugin install --batch \
            file:///opt/plugin/prometheus-exporter-2.19.1.0.zip
        fi
        ls -1 /shared-plugins
    volumeMounts:
      - { name: opensearch-prometheus-plugin, mountPath: /opt/plugin, readOnly: true }
      - { name: opensearch-plugins-shared,    mountPath: /shared-plugins }
    resources:
      requests: { cpu: "100m", memory: "256Mi" }
      limits:   { cpu: "1000m", memory: "512Mi" }
```

> **왜 shared volume 이 필요한가**: OS image 의 `/usr/share/opensearch/plugins`
> 에 emptyDir 를 직접 마운트하면 빌트인 plugin (security 등) 이 모두 가려짐.
> init 가 빌트인을 emptyDir 로 복사 → symlink 로 redirect → 그 위에 추가 설치
> 하면 main 컨테이너가 빌트인 + 추가 plugin 모두 사용 가능.

#### 1.2.3 helm upgrade

```bash
helm upgrade opensearch-lt opensearch/opensearch \
  --version 2.32.0 -n monitoring --reuse-values \
  -f deploy/load-testing-airgap/00-prerequisites/opensearch-helm-values.yaml

kubectl -n monitoring rollout status sts/opensearch-lt-node --timeout=300s
```

#### 1.2.4 자동화 스크립트

위 1.2.1 ~ 1.2.3 + ServiceMonitor 적용까지 한 번에:

```bash
bash deploy/load-testing-airgap/00-prerequisites/setup-os-prometheus-plugin.sh

# 폐쇄망:
PLUGIN_URL=https://nexus.intranet:8082/repository/opensearch-plugins/prometheus-exporter-2.19.1.0.zip \
  bash deploy/load-testing-airgap/00-prerequisites/setup-os-prometheus-plugin.sh
```

### 1.3 ServiceMonitor 적용

`/_prometheus/metrics` 가 OS REST 9200 에 자동 노출 — kps-prometheus 가 scrape
하도록 `ServiceMonitor` 1개:

```bash
kubectl apply -f deploy/load-testing-airgap/00-prerequisites/opensearch-servicemonitor.yaml
```

핵심 selector — chart 가 부여하는 `app.kubernetes.io/instance` 라벨에 맞춤:

```yaml
spec:
  selector:
    matchLabels:
      app.kubernetes.io/instance: opensearch-lt
  endpoints:
    - port: http                       # 9200 의 포트 이름
      path: /_prometheus/metrics
      interval: 30s
      scrapeTimeout: 25s
```

> **selector 트랩**: 다른 chart (ECK, Strimzi 등) 는 `app.kubernetes.io/name: opensearch`
> 를 사용하지만 opensearch helm chart 는 `instance` 라벨이 핵심. 매칭 안 되면
> `kubectl -n monitoring get svc -l app.kubernetes.io/instance=opensearch-lt` 로
> 실제 라벨 확인 후 selector 조정.

### 1.4 보안 plugin 활성 클러스터

`plugins.security.disabled: false` 인 운영 환경에선 `/_prometheus/metrics` 도
basic auth 필요:

```yaml
spec:
  endpoints:
    - port: http
      path: /_prometheus/metrics
      basicAuth:
        username:
          name: opensearch-creds
          key: username
        password:
          name: opensearch-creds
          key: password
      tlsConfig:
        insecureSkipVerify: true       # self-signed 운영 cert
```

---

## 2. 검증

### 2.1 plugin 자체

```bash
# init 로그 — "prometheus-exporter" 가 plugins 목록에 보여야 함
kubectl -n monitoring logs opensearch-lt-node-0 -c install-prometheus-exporter | tail -20

# endpoint 직접 호출 (보안 plugin 비활성 기준)
kubectl -n monitoring exec opensearch-lt-node-0 -- \
  curl -s http://localhost:9200/_prometheus/metrics | grep -c '^# TYPE opensearch_'
# 200+ 메트릭이면 OK
```

### 2.2 prometheus 가 scrape 했는지

```bash
kubectl -n monitoring port-forward svc/kps-prometheus 19090:9090 &
sleep 2

# (a) target 상태 — health=up 이어야 함
curl -s "http://localhost:19090/api/v1/targets" \
  | jq -r '.data.activeTargets[] | select(.scrapePool | test("opensearch-plugin")) | "\(.health) \(.lastError // "OK")"'

# (b) metric 수집 확인
N=$(curl -s "http://localhost:19090/api/v1/label/__name__/values" \
    | jq -r '.data[]' | grep -c '^opensearch_')
echo "opensearch_* metric count = $N"     # 200+ 정상

# (c) 핵심 query
curl -s --data-urlencode 'query=opensearch_cluster_status' \
  "http://localhost:19090/api/v1/query" | jq '.data.result[0].value'
```

### 2.3 Grafana dashboard

```bash
kubectl -n monitoring port-forward svc/kps-grafana 13000:80 &

# 적용된 OS 대시보드 확인
curl -s -u admin:admin "http://localhost:13000/api/search?query=OpenSearch" \
  | jq -r '.[] | "\(.uid)  \(.title)"'

# 권장 dashboard:
#   lt-opensearch-6scenarios   Load Test • OpenSearch (6 scenarios — bulk/mixed/wave/sustained/chaos)
```

---

## 3. 기존 sidecar exporter 정리 (선택)

옵션 A 의 `opensearch-exporter` Deployment 가 남아있으면 동일 cluster 에 대해
두 종류 메트릭이 중복 수집됨. 옵션 B 로 전환했다면 sidecar 제거 권장:

```bash
# 1. 임시 비활성 (롤백 여지)
kubectl -n monitoring scale deployment opensearch-exporter --replicas=0

# 2. 일주일 운영하며 dashboard 영향 없는지 확인 후 완전 제거
kubectl -n monitoring delete deployment opensearch-exporter
kubectl -n monitoring delete servicemonitor opensearch-exporter   # 있으면
kubectl -n monitoring delete service opensearch-exporter
```

기존 elasticsearch-exporter 기반 dashboard 가 있으면 metric 이름을
`elasticsearch_*` → `opensearch_*` 로 일괄 변환. 변환 매핑은
`08-opensearch-test-scenarios-guide.md §0.1` 참고.

---

## 4. 트러블슈팅

### 4.1 init container CrashLoopBackOff — `cp: preserving times: Operation not permitted`

`cp -a` 는 시간/소유권 보존 시도 → fsgroup + emptyDir 환경에서 실패. **`cp -r`
+ `2>/dev/null || true`** 로 변경 (현재 helm-values 에 반영됨).

### 4.2 plugin install — `version mismatch`

plugin 버전과 OS 버전이 정확히 일치해야 함 (`X.Y.Z.0` 패턴). chart 가 OS 2.19.1
패키징하면 plugin 도 `2.19.1.0`. 새 release 가 미존재 시:
- chart 의 `image.tag` 를 plugin 이 지원하는 최근 버전 (예 `2.19.0`) 으로 다운그레이드
- 또는 plugin release tracker 에서 새 버전 대기

### 4.3 ServiceMonitor 가 매칭 안 됨 — prometheus 에 metric 0개

```bash
# 실제 service 라벨 확인
kubectl -n monitoring get svc -l app.kubernetes.io/instance=opensearch-lt -o name
# → service/opensearch-lt-node 가 출력되어야 함

# dropped target 으로 보이면 selector 가 service 와 안 맞는 것:
curl -s http://localhost:19090/api/v1/targets | jq -r '.data.droppedTargets[]?.discoveredLabels."__meta_kubernetes_service_name"' | grep opensearch
```

### 4.4 cluster_status 가 "비정상" 으로 보임

옵션 B 의 `opensearch_cluster_status` 는 **0=green, 1=yellow, 2=red** 단일
gauge. 옵션 A 는 `elasticsearch_cluster_health_status{color}` 0/1 — 다른
구조이므로 dashboard 표시 시 매핑 필요.

표준 dashboard 표기 (1=G/2=Y/3=R) 변환: `opensearch_cluster_status + 1`.

### 4.5 보안 plugin 클러스터에서 401

`/_prometheus/metrics` 도 권한 필요. `opensearch_security` 의 role 매핑:
```bash
# admin 사용자에게 cluster_monitor 권한 (또는 dedicated user) 매핑
```
ServiceMonitor 의 `basicAuth` 또는 `authorization` 필드 사용.

---

## 5. 운영 적용 체크리스트

배포 전:
- [ ] plugin .zip 이 Nexus raw repo 에 업로드됨
- [ ] OS 버전과 plugin 버전이 정확히 일치 (`<X.Y.Z>.0`)
- [ ] OS 운영 cluster 가 helm chart 기반 (kustomize/operator 인 경우 별도 절차)
- [ ] 보안 plugin 활성 시 dedicated monitoring user 발급

배포 후:
- [ ] `init` 컨테이너 로그에 plugin 설치 성공 출력
- [ ] `kubectl exec ... curl localhost:9200/_prometheus/metrics | head` 정상
- [ ] prometheus 가 200+ `opensearch_*` 메트릭 수집
- [ ] Grafana 의 OS dashboard query 가 데이터 반환
- [ ] 기존 elasticsearch-exporter sidecar 비활성/제거
- [ ] 알람 (PrometheusRule) 의 metric 이름도 `opensearch_*` 로 전환

---

## 6. 부록 — 메트릭 이름 매핑 cheat sheet

옵션 A (sidecar) → 옵션 B (plugin):

```
elasticsearch_cluster_health_status{color="green"}  → opensearch_cluster_status == 0
elasticsearch_cluster_health_unassigned_shards      → opensearch_cluster_shards_number{type="unassigned"}
elasticsearch_cluster_health_initializing_shards    → opensearch_cluster_shards_number{type="initializing"}
elasticsearch_cluster_health_relocating_shards      → opensearch_cluster_shards_number{type="relocating"}
elasticsearch_cluster_health_number_of_nodes        → opensearch_cluster_nodes_number

elasticsearch_indices_indexing_index_total          → opensearch_indices_indexing_index_count
elasticsearch_indices_indexing_index_time_seconds_total
                                                     → opensearch_indices_indexing_index_time_seconds
elasticsearch_indices_search_query_total            → opensearch_indices_search_query_count
elasticsearch_indices_search_query_time_seconds_total
                                                     → opensearch_indices_search_query_time_seconds
elasticsearch_indices_segments_count                → opensearch_indices_segments_number

elasticsearch_thread_pool_queue_count{type="..."}   → opensearch_threadpool_tasks_number{name="...",type="queue"}
elasticsearch_thread_pool_rejected_count{type="..."}→ opensearch_threadpool_threads_count{name="...",type="rejected"}

elasticsearch_jvm_memory_used_bytes{area="heap"} / max
                                                     → opensearch_jvm_mem_heap_used_percent (직접 %)
elasticsearch_jvm_gc_collection_seconds_sum         → opensearch_jvm_gc_collection_time_seconds
elasticsearch_breakers_tripped                      → opensearch_circuitbreaker_tripped_count

elasticsearch_filesystem_data_available_bytes       → opensearch_fs_total_available_bytes
elasticsearch_filesystem_data_size_bytes            → opensearch_fs_total_total_bytes
```

---

## 7. 참고 자료

- Plugin 소스: https://github.com/aiven/prometheus-exporter-plugin-for-opensearch
- helm chart values 전체: `deploy/load-testing-airgap/00-prerequisites/opensearch-helm-values.yaml`
- ServiceMonitor: `deploy/load-testing-airgap/00-prerequisites/opensearch-servicemonitor.yaml`
- 자동 설치 스크립트: `deploy/load-testing-airgap/00-prerequisites/setup-os-prometheus-plugin.sh`
- 매트릭 기반 가이드: `deploy/load-testing-airgap/docs/08-opensearch-test-scenarios-guide.md`
- 6시나리오 dashboard: `deploy/load-testing/05-dashboards/Load Test • OpenSearch (6 scenarios — bulk_mixed_wave_sustained_chaos).json`
