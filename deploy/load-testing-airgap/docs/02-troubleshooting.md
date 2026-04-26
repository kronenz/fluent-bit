# 트러블슈팅 가이드

사내망 테스트에서 실제 발생한 사례 + 일반적인 실패 패턴.

## 1. opensearch-benchmark 가 정상 실행되지 않음

### 1.1 OOMKilled

```bash
kubectl -n load-test get pod -l scenario=OS-01 -o jsonpath='{.items[*].status.containerStatuses[*].lastState}'
# {"terminated":{"reason":"OOMKilled","exitCode":137,...}}
```

| 원인 | 해결 |
|------|------|
| 메모리 limit 1.5Gi 부족 | **이번 버전에서 4Gi 로 상향** — 그래도 OOM 시 8Gi |
| corpus 로드 시 메모리 spike | TEST_MODE=true 유지 (1k docs) 로 회피 |
| Python multiprocessing fork | `OSB_CLIENTS` 낮춤 (16 → 8) |

```yaml
# 추가 상향이 필요한 경우 (job.yaml patch):
resources:
  limits: { cpu: "8000m", memory: "8Gi" }
```

### 1.2 `FATAL: cannot reach ${OPENSEARCH_URL}`

| 원인 | 확인 | 해결 |
|------|------|------|
| service 이름 불일치 | `kubectl -n monitoring get svc \| grep opensearch` | `lt-config` 의 `OPENSEARCH_URL` 정정 |
| port 다름 (9200 vs 9300) | 위와 동일 | URL 의 port 정정 |
| security plugin 인증 실패 | secret `opensearch-creds` 존재 여부 | `kubectl apply -f 00-prerequisites/opensearch-creds.yaml` |
| TLS (https) | exporter 가 http 로 접근 | URL 을 `https://...` 로, `verify_certs:false` 유지 |

### 1.3 `FATAL: workload not found`

```bash
kubectl -n load-test exec deploy/loggen-spark -- ls /opt/osb-workloads
# 정상: geonames pmc http_logs nyc_taxis ...
```

| 원인 | 해결 |
|------|------|
| 이미지 손상 | Nexus 의 image digest 재확인 → 재pull |
| OSB_WORKLOAD 오타 | `lt-config` 의 `OSB_WORKLOAD` 가 위 ls 결과에 있는지 |

### 1.4 `mapper_parsing_exception` (인덱스 mapping 충돌)

```bash
# 기존 인덱스 삭제 후 재실행
kubectl -n monitoring exec opensearch-lt-node-0 -- \
  curl -u admin:admin -X DELETE http://localhost:9200/geonames
```

### 1.5 401 / 403 (security plugin)

```bash
# secret 존재 확인
kubectl -n load-test get secret opensearch-creds -o jsonpath='{.data.OS_BASIC_AUTH_USER}' | base64 -d
# admin

# secret 변경 후 Job 재생성 (envFrom 은 Job 시작 시점에만 lock)
kubectl -n load-test delete job opensearch-benchmark
kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/
```

---

## 2. opensearch-exporter 가 메트릭을 안 노출

### 증상

```bash
curl http://opensearch-exporter.monitoring.svc:9114/metrics | head
# elasticsearch_exporter_build_info{...} 1
# (그 아래 elasticsearch_cluster_health_status 등이 없음)
```

또는 Pod 가 OOMKilled 반복.

| 원인 | 해결 |
|------|------|
| **메모리 부족** (인덱스 多) | `limits.memory: 128Mi → 512Mi` (이번 버전 적용됨). 여전히 OOM 이면 1Gi |
| **OS 401/403** | `opensearch-creds` secret + envFrom 확인 |
| `--es.uri` 의 host/port 오류 | service 이름 확인 (helm chart 가 `-node` suffix 추가) |

### 검증

```bash
kubectl -n monitoring logs deploy/opensearch-exporter | grep -i 'error\|warn' | head
# error msg: 401 Unauthorized → secret 누락 또는 잘못된 password
# error msg: dial tcp ... no such host → service URL 오타

# secret 적용 확인
kubectl -n monitoring describe deploy/opensearch-exporter | grep -A2 'Environment'
# Environment Variables from:
#   opensearch-creds Secret  Optional: true
```

---

## 3. ImagePullBackOff

```bash
kubectl -n load-test describe pod <pod> | grep -A5 'Events'
# Failed to pull image "nexus.intranet:8082/loadtest/...": ...
```

| 메시지 | 원인 | 해결 |
|--------|------|------|
| `unauthorized` | imagePullSecret 미설정 | `kubectl create secret docker-registry nexus-cred ...` 후 patch |
| `no such host` | DNS 미해결 | 노드의 `/etc/hosts` 또는 사내 DNS 등록 |
| `x509: certificate signed by unknown authority` | 사내 CA 미신뢰 | 노드의 `/etc/docker/certs.d/<host>/ca.crt` 배치 + `systemctl reload docker` |
| `manifest unknown` | 태그 오타 또는 미푸시 | Nexus UI 에서 태그 확인 |

`imagePullSecrets` patch:
```bash
for ns in load-test monitoring; do
  kubectl create secret docker-registry nexus-cred \
    --docker-server=nexus.intranet:8082 \
    --docker-username=$NEXUS_USER \
    --docker-password=$NEXUS_PASS \
    -n $ns
done

# Deployment / Job 에 imagePullSecrets 추가
kubectl -n load-test patch deploy/flog-loader --type=merge -p='
spec: { template: { spec: { imagePullSecrets: [{ name: nexus-cred }] } } }
'
```

---

## 4. OOMKilled (일반 패턴)

이번 버전에서 상향한 limit:

| 컴포넌트 | 이전 | 현재 | 추가 상향 시 |
|----------|------|------|--------------|
| opensearch-benchmark | 1.5Gi | **4Gi**  | 8Gi |
| k6-opensearch-search | 512Mi | **1Gi**  | 2Gi |
| k6-promql            | 512Mi | **1Gi**  | 1.5Gi |
| opensearch-exporter  | 128Mi | **512Mi** | 1Gi |
| avalanche            | 256Mi | **512Mi** | 1Gi |
| kube-burner          | 512Mi | **768Mi** | 1.5Gi |

```bash
# 임시 상향 (재apply 전)
kubectl -n load-test patch deploy/<name> --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"2Gi"}
]'
```

---

## 5. fluent-bit 가 logs-fb-* 인덱스를 못 만듦

| 증상 | 원인 | 해결 |
|------|------|------|
| `_cat/indices` 에 `logs-fb-*` 없음 | flog 미가동 | flog-loader 가동 후 5분 대기 |
| `error: 401` (fluent-bit 로그) | OS security 인증 누락 | fluent-bit values 의 output 에 admin 자격 추가 |
| `error: out of memory` | filesystem buffer fill | DaemonSet limit 상향 또는 OS ingest rate 정상화 |

```bash
kubectl -n kube-system logs ds/fluent-bit | grep -E 'error|warn' | head
```

---

## 6. KSM-04 의 namespace cleanup 실패

```bash
kubectl get ns -o name | grep '^namespace/kburner-' | wc -l
# 50  ← 잔재
```

| 원인 | 해결 |
|------|------|
| Job 강제 종료로 cleanup hook 못 돔 | `kubectl get ns -o name \| grep kburner- \| xargs -r kubectl delete` |
| finalizer 걸림 | `kubectl get ns kburner-1 -o yaml \| grep finalizers` 후 metadata.finalizers 비우기 |

---

## 7. k6 임계 (threshold) 위반

```
✗ http_req_duration..............: avg=124ms p(95)=1247ms ...
   ✗ p(95)<500
   ✗ p(99)<1500
ERRO[0312] thresholds on metrics 'http_req_duration' have been crossed
```

→ Job exit code 99 (k6 의 threshold 실패 시그널)

| 시나리오 | 위반 시 의미 | 1차 액션 |
|----------|-------------|----------|
| OS-02 (heavy search) | OS 가 50 VU 검색을 못 버팀 | OS replicas / heap / shard 수 검토 |
| OS-16 (light search)  | ★ 운영 SLO 미달 — heavy ingest 와 동시성 부족 | indexing/search thread pool 분리 검토 |
| PR-03/04 (PromQL)     | Prometheus query saturation | resources 증설, query timeout 조정 |
| NE-02 (hey)           | node-exporter saturation | RPS 낮춤 또는 `--web.max-requests` 상향 |

---

## 8. dry-run 검증

새 매니페스트 적용 전 client-side validation:

```bash
kubectl apply --dry-run=client \
  -f deploy/load-testing-airgap/00-prerequisites/ \
  -f deploy/load-testing-airgap/10-load-generators/ \
  -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/
```
