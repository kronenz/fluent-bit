# Step-by-step 핸즈온 테스트 가이드

복사-붙여넣기 가능한 명령 + 각 단계의 **예상 출력** + **확인 포인트** +
**실패 시 대응**. 처음 폐쇄망 환경에 배포하기 전, testbed 에서 모든 시나리오를
한 번씩 검증하기 위한 절차입니다.

> 본 가이드는 testbed (단일 노드 minikube-remote) 기준입니다. 폐쇄망 (멀티
> 노드) 에서는 §STEP 0 의 `IMG_PREFIX` 만 변경하면 그대로 동일 절차로 진행 가능.

---

## STEP 0 — 환경 변수 설정 (1회)

```bash
# 매 step 의 명령에 사용. 새 터미널 열 때마다 다시 실행.
export CTX=minikube-remote                                   # 폐쇄망: airgap-prod
export NS=load-test
export NS_MON=monitoring

# 이미지 prefix — testbed 에서는 로컬 이미지, 폐쇄망에서는 Nexus 경로
export IMG_PREFIX=local                                      # 폐쇄망: nexus
swap_image() {
  if [[ "$IMG_PREFIX" == "local" ]]; then
    sed -e 's|nexus.intranet:8082/loadtest/loadtest-tools:0.1.1|loadtest-tools:0.1.1|g' \
        -e 's|nexus.intranet:8082/loadtest/pause:3.10|registry.k8s.io/pause:3.10|g'
  else
    cat
  fi
}

# 환경 동작 확인
kubectl --context=$CTX get nodes
```

**예상 출력**:
```
NAME       STATUS   ROLES           AGE   VERSION
minikube   Ready    control-plane   17h   v1.35.1
```

**확인**: STATUS=Ready 이어야 함.
**실패 시**: kubectl context 가 잘못됨 → `kubectl config get-contexts` 로 확인.

---

## STEP 1 — 클러스터 사전 검증

### 1.1 monitoring 스택 가동 확인

```bash
kubectl --context=$CTX -n $NS_MON get pods -l 'app.kubernetes.io/name in (prometheus,grafana,alertmanager,kube-state-metrics,prometheus-node-exporter,opensearch)'
```

**예상 출력 (모두 Running)**:
```
NAME                                READY   STATUS    RESTARTS   AGE
alertmanager-kps-alertmanager-0     2/2     Running   0          ...
kps-grafana-...                     3/3     Running   0          ...
kps-kube-state-metrics-...          1/1     Running   0          ...
kps-prometheus-node-exporter-...    1/1     Running   *          ...
opensearch-lt-node-0                1/1     Running   0          ...
prometheus-kps-prometheus-0         2/2     Running   0          ...
```

**확인**: 모든 Pod READY 일치.
**실패 시**:
- Helm release 미설치 → `02-logging/install.sh`, `01-monitoring-core/install.sh` 실행
- node-exporter restart 횟수 ≫ 0 → 정상 (testbed 한계). NE-02 시나리오에서 다룸.

### 1.2 fluent-bit DaemonSet 가동 확인

```bash
kubectl --context=$CTX -n $NS_MON get ds -l app.kubernetes.io/name=fluent-bit
```

**예상 출력**:
```
NAME            DESIRED   CURRENT   READY   ...   AGE
fluent-bit-lt   1         1         1       ...   ...
```

**확인**: DESIRED=CURRENT=READY (모두 동일).

---

## STEP 2 — 사전 객체 적용

### 2.1 namespace + ConfigMap + Secret 배포

```bash
kubectl --context=$CTX apply -f deploy/load-testing-airgap/00-prerequisites/
```

**예상 출력**:
```
namespace/monitoring unchanged
namespace/load-test unchanged
configmap/lt-config created
secret/opensearch-creds created
secret/opensearch-creds created
```

**확인**: 5개 리소스 모두 created/unchanged 여야 함.

### 2.2 사전 적용 검증

```bash
kubectl --context=$CTX -n $NS get cm lt-config -o jsonpath='{.data.OPENSEARCH_URL}'
echo
kubectl --context=$CTX -n $NS get secret opensearch-creds -o jsonpath='{.data.OS_BASIC_AUTH_USER}' | base64 -d
echo
```

**예상 출력**:
```
http://opensearch-lt-node.monitoring.svc:9200
admin
```

**실패 시**:
- 빈 값 → ConfigMap/Secret 미적용 → STEP 2.1 재실행
- Secret 값이 다름 → opensearch-creds.yaml 의 stringData 수정 후 재apply

---

## STEP 3 — 백그라운드 부하 발생기 가동

### 3.1 모든 부하 발생기 배포

```bash
for f in deploy/load-testing-airgap/10-load-generators/*.yaml; do
  cat "$f" | swap_image | kubectl --context=$CTX apply -f -
done
```

**예상 출력**:
```
deployment.apps/avalanche unchanged
service/avalanche unchanged
servicemonitor.monitoring.coreos.com/avalanche unchanged
deployment.apps/flog-loader unchanged
configmap/loggen-spark-script unchanged
deployment.apps/loggen-spark unchanged
deployment.apps/opensearch-exporter unchanged
service/opensearch-exporter unchanged
servicemonitor.monitoring.coreos.com/opensearch-exporter unchanged
```

### 3.2 가동 확인

```bash
kubectl --context=$CTX -n $NS get deploy -l role=load-generator
```

**예상 출력**:
```
NAME           READY   UP-TO-DATE   AVAILABLE
avalanche      2/2     2            2
flog-loader    3/3     3            3
loggen-spark   3/3     3            3
```

**확인**: READY 컬럼이 모두 X/X 로 일치.
**실패 시**:
- 0/N → ImagePullBackOff → `kubectl describe pod` 로 원인 확인. testbed 면 IMG_PREFIX=local 인지 확인.

### 3.3 인덱스 채워지는지 확인 (5분 대기 후)

```bash
sleep 300
kubectl --context=$CTX -n $NS_MON exec opensearch-lt-node-0 -- \
  curl -s -u admin:admin http://localhost:9200/_cat/indices/logs-fb-*?v
```

**예상 출력**:
```
health status index           uuid                   pri rep docs.count   docs.deleted store.size
green  open   logs-fb-2026-04 ...                    1   0   1530000      0            ...
```

**확인**: docs.count > 0 (flog 가 OS 로 흘러들어가는 중).
**실패 시**:
- index 없음 → fluent-bit DaemonSet 로그 확인 (`kubectl -n $NS_MON logs ds/fluent-bit-lt | grep -i error`).
- single-node OS 라면 health=yellow 정상 (replica unassign).

---

## STEP 4 — 시나리오별 핸즈온 (가벼운 것부터)

각 시나리오: ① apply → ② 모니터 → ③ 결과 확인 → ④ 정리. 이 패턴 반복.

### 4.1 NE-02 — hey × node-exporter (소요 2분)

```bash
# ① apply
cat deploy/load-testing-airgap/20-scenarios/NE-02-hey-node-exporter/job.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

# ② 모니터 (Job 종료까지)
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=180s job/hey-node-exporter

# ③ 결과 확인
kubectl --context=$CTX -n $NS logs job/hey-node-exporter | tail -25
```

**기대 결과 (정상 클러스터)**:
```
Status code distribution:
  [200] 300000 responses

Summary:
  Average: 0.0156 secs
```

**testbed 결과 (NE limit 부족)**:
```
Status code distribution:
  [200] 13 responses
  [503] 239 responses

Error distribution:
  [6112] connect: connection refused
```

**확인**: 200 비율이 90%+ 면 PASS. testbed 처럼 1% 미만이면 NE limit 부족 → §"node-exporter limit 문제" 로 이동.

```bash
# ④ 정리
kubectl --context=$CTX -n $NS delete job hey-node-exporter
```

### 4.2 OS-01 — opensearch-benchmark (소요 1~2분)

```bash
# ① apply
cat deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/job.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

# ② 모니터 — pre-flight 단계 확인 (즉시 출력됨)
kubectl --context=$CTX -n $NS logs -f job/opensearch-benchmark
```

**1분 내 예상 출력 (pre-flight)**:
```
================ OSB pre-flight diagnostic ================
[1/4] opensearch-benchmark version: 1.7.0
[2/4] Workload directory: README.md, files.txt, ...
[3/4] OpenSearch reachability: { "status": "green" or "yellow" }
[4/4] Disk + memory
============== OSB execution ==============
```

**testbed (single-node) 한정 — hang 발생 시**:
- `[INFO] Test Execution ID: ...` 후 진척 없음
- 원인: replica=1 default + single-node → unassigned shards
- 우회:
  ```bash
  kubectl --context=$CTX -n $NS_MON exec opensearch-lt-node-0 -- \
    curl -X PUT -u admin:admin "http://localhost:9200/*/_settings" \
    -H 'Content-Type: application/json' \
    -d '{"index":{"number_of_replicas":0}}'
  ```
  적용 후 Job 삭제/재생성.

**정상 종료 시**:
```
============== OSB SUCCESS ==============
{ "throughput": ..., "latency_p95": ..., ... }
```

```bash
# ④ 정리
kubectl --context=$CTX -n $NS delete job opensearch-benchmark
```

### 4.3 KSM-02-04 — kube-burner pod density (소요 5~7분)

```bash
# ① apply (testbed iter=50 안전치)
cat deploy/load-testing-airgap/20-scenarios/KSM-02-04-kube-burner/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

# ② 모니터 (10분 timeout)
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=900s job/kube-burner-pod-density

# ③ 결과 확인
kubectl --context=$CTX -n $NS logs job/kube-burner-pod-density | tail -10
```

**기대 출력 (마지막 줄)**:
```
... level=info msg="Job pod-density took 5m25s"
... level=info msg="Garbage collecting jobs"
... level=info msg="👋 Exiting kube-burner kube-burner-pod-density-..."
```

**확인**: `Job pod-density took ...` 출력 + Job complete (1/1).

```bash
# ④ 정리
kubectl --context=$CTX -n $NS delete job kube-burner-pod-density
kubectl --context=$CTX get ns -o name | grep '^namespace/kburner-' | xargs -r kubectl --context=$CTX delete --wait=false
```

### 4.4 NE-OOM-tuning — RPS ramp (소요 5분)

```bash
# ① apply
cat deploy/load-testing-airgap/20-scenarios/NE-OOM-tuning/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

# ② 모니터
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=600s job/ne-oom-tuning

# ③ 결과 추출 (RSS 곡선)
kubectl --context=$CTX -n $NS logs job/ne-oom-tuning | grep 'RSS peak'
```

**기대 출력 (정상 limit 클러스터)**:
```
[stage=baseline] node-exporter RSS peak = 30 MB
[stage=normal]   node-exporter RSS peak = 80 MB
[stage=high]     node-exporter RSS peak = 150 MB
[stage=peak]     node-exporter RSS peak = 250 MB
```

**testbed 결과 (32Mi limit)**:
```
[stage=baseline] node-exporter RSS peak = 45 MB
[stage=normal]   node-exporter RSS peak = 0 MB     ← 죽음
[stage=high]     node-exporter RSS peak = 0 MB
[stage=peak]     node-exporter RSS peak = 0 MB
```

**확인**: RSS peak 가 모든 stage 에서 0 이 아니면 PASS. testbed 처럼 baseline 만 살아있으면 → NE limit 부족 (§"node-exporter limit 문제" 참고).

```bash
# ④ 정리
kubectl --context=$CTX -n $NS delete job ne-oom-tuning
```

### 4.5 KSM-OOM-tuning (소요 5분)

```bash
cat deploy/load-testing-airgap/20-scenarios/KSM-OOM-tuning/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=600s job/ksm-oom-tuning
kubectl --context=$CTX -n $NS logs job/ksm-oom-tuning | grep -E 'stage=|DONE'
```

**기대 출력**:
```
[stage=baseline] KSM RSS=40 MB, scrape_duration=0.05s
[stage=ramp-1]   KSM RSS=80 MB, scrape_duration=0.4s
[stage=ramp-3]   KSM RSS=150 MB, scrape_duration=0.9s
[stage=ramp-6]   KSM RSS=200 MB, scrape_duration=1.5s
[stage=post]     KSM RSS=70 MB, scrape_duration=0.2s
=== DONE ===
```

```bash
# 정리
kubectl --context=$CTX -n $NS delete job ksm-oom-tuning
kubectl --context=$CTX get ns -o name | grep '^namespace/ksm-oom-' | xargs -r kubectl --context=$CTX delete --wait=false
```

### 4.6 PR-03-04 — k6 PromQL (소요 5분)

```bash
cat deploy/load-testing-airgap/20-scenarios/PR-03-04-k6-promql/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=420s job/k6-promql
kubectl --context=$CTX -n $NS logs job/k6-promql | tail -30
```

**기대 출력 (k6 summary)**:
```
✓ http_req_duration..............: avg=124ms p(95)=1247ms p(99)=2891ms
✓ http_req_failed................: 0.21%

✓ p(95)<2000
✓ rate<0.01
```

**확인**: thresholds (`✓ p(95)<2000`, `✓ rate<0.01`) 모두 통과.

```bash
kubectl --context=$CTX -n $NS delete job k6-promql
```

### 4.7 OS-02 — k6 heavy search (소요 7분)

```bash
# 인덱스 사전 채움 확인
kubectl --context=$CTX -n $NS_MON exec opensearch-lt-node-0 -- \
  curl -s -u admin:admin 'http://localhost:9200/logs-fb-*/_count'
# {"count":1500000,...} ≥ 100k 권장
```

```bash
cat deploy/load-testing-airgap/20-scenarios/OS-02-k6-heavy-search/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=600s job/k6-opensearch-search
kubectl --context=$CTX -n $NS logs job/k6-opensearch-search | tail -30
```

**기대 thresholds**:
- `p(95)<500` ✓
- `p(99)<1500` ✓
- `rate<0.005` ✓

```bash
kubectl --context=$CTX -n $NS delete job k6-opensearch-search
```

### 4.8 OS-16 — k6 light search (★ 핵심 SLO, 30분 소요)

```bash
# 사전: flog + loggen-spark 동시 가동 (이미 §3 에서 적용됨)

cat deploy/load-testing-airgap/20-scenarios/OS-16-k6-light-search/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

# 30분 소요 — wait 또는 다른 작업
kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=2400s job/k6-opensearch-light-search

kubectl --context=$CTX -n $NS logs job/k6-opensearch-light-search | tail -30
```

**기대 thresholds (★)**:
- `p(95)<5000` ✓ ← 운영 SLO
- `p(99)<10000` ✓
- `rate<0.01` ✓

```bash
kubectl --context=$CTX -n $NS delete job k6-opensearch-light-search
```

### 4.9 FB-OOM-tuning (소요 18분 자동 ramp)

```bash
cat deploy/load-testing-airgap/20-scenarios/FB-OOM-tuning/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=1500s job/fb-oom-tuning
kubectl --context=$CTX -n $NS logs job/fb-oom-tuning | grep 'RSS peak'
```

**기대 출력**:
```
[stage=baseline] fluent-bit RSS peak = 60 MB
[stage=normal]   fluent-bit RSS peak = 150 MB
[stage=high]     fluent-bit RSS peak = 400 MB
[stage=peak]     fluent-bit RSS peak = 800 MB
```

**확인**: peak stage 까지 정상 측정 + 운영 limit = peak × 1.5 결정.

```bash
kubectl --context=$CTX -n $NS delete job fb-oom-tuning
```

### 4.10 CHAOS-FB-restart (소요 3분)

```bash
cat deploy/load-testing-airgap/20-scenarios/CHAOS-FB-restart/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=300s job/chaos-fb-restart
kubectl --context=$CTX -n $NS logs job/chaos-fb-restart | tail -15
```

**기대 출력**:
```
=== 결과 ===
Δ count = 65000 (over 60s, expected ≥ 60000)
[PASS] ingest 끊김 없음 — offset DB 가 보존됨
```

**실패 시**: `[FAIL] ingest gap 의심` → fluent-bit storage path 가 hostPath 인지 확인.

```bash
kubectl --context=$CTX -n $NS delete job chaos-fb-restart
```

### 4.11 CHAOS-OS-07 (testbed = 의도된 FAIL, 멀티노드 = PASS)

```bash
cat deploy/load-testing-airgap/20-scenarios/CHAOS-OS-07-node-failure/scenario.yaml \
  | swap_image | kubectl --context=$CTX apply -f -

kubectl --context=$CTX -n $NS wait --for=condition=complete --timeout=900s job/chaos-os-07-node-failure || true
kubectl --context=$CTX -n $NS logs job/chaos-os-07-node-failure | tail -20
```

**testbed 기대 출력**:
```
RED 진입       : 5 s
YELLOW 진입    : 15 s
GREEN 회복     : NOT RECOVERED in 600s s
[FAIL] green 회복 실패 — replica ≥ 1 필요
```

testbed 에서는 의도된 FAIL. 멀티노드 (replica ≥ 1) 에서 재실행하면 PASS 예상.

```bash
kubectl --context=$CTX -n $NS delete job chaos-os-07-node-failure
```

---

## STEP 5 — 종합 확인

### 5.1 모든 Job 종료 + 결과 일람

```bash
kubectl --context=$CTX -n $NS get jobs
```

각 시나리오의 STATUS 가 Complete 인지 확인. Failed 가 있으면 logs 재확인.

### 5.2 OOMKilled 발생 횟수

```bash
for ns in $NS_MON $NS; do
  echo "=== $ns ==="
  kubectl --context=$CTX -n $ns get pod \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].restartCount}{"\n"}{end}' \
    | awk '$2 > 0'
done
```

**기대**: 출력 비어있음 (운영 정상). testbed 면 node-exporter restart 표시 정상.

### 5.3 Grafana 대시보드 확인

```
http://<grafana-host>/d/lt-overview        ← 통합 Overview
http://<grafana-host>/d/lt-opensearch       ← OS 시나리오
http://<grafana-host>/d/lt-fluent-bit       ← FB 시나리오
http://<grafana-host>/d/lt-prometheus       ← PR 시나리오
http://<grafana-host>/d/lt-node-exporter    ← NE 시나리오
http://<grafana-host>/d/lt-ksm              ← KSM 시나리오
```

각 패널에 데이터 채워졌는지 확인.

---

## node-exporter limit 문제 (testbed 즉시 fix)

NE-02 / NE-OOM 에서 503 / connection refused / RSS=0 발생 시:

```bash
# 현재 limit 확인
kubectl --context=$CTX -n $NS_MON describe ds kps-prometheus-node-exporter \
  | grep -A2 -i 'limits'
# 32Mi 면 비정상 (request 64Mi 대비 작음)

# 임시 패치
kubectl --context=$CTX -n $NS_MON patch ds kps-prometheus-node-exporter --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"256Mi"}
]'

# 영구 적용은 helm values 수정:
# prometheus-node-exporter:
#   resources:
#     limits: { memory: 256Mi, cpu: 500m }
```

수정 후 NE-02 재실행 → 100% 200 응답 확인.

---

## 정리 (모든 테스트 종료 후)

```bash
# 모든 Job 정리
kubectl --context=$CTX -n $NS delete jobs --all

# 부하 발생기 중지 (선택)
kubectl --context=$CTX -n $NS scale deploy --all --replicas=0
# 또는 완전 제거
# kubectl delete -f deploy/load-testing-airgap/10-load-generators/

# kube-burner / ksm-oom 잔재 namespace
kubectl --context=$CTX get ns -o name \
  | grep -E '^namespace/(kburner|ksm-oom)-' \
  | xargs -r kubectl --context=$CTX delete --wait=false
```

---

## 시나리오별 소요 시간 요약

| # | 시나리오 | 소요 | 누적 |
|---|----------|------|------|
| STEP 0 ~ 3 (사전 준비) | — | 6m | 6m |
| 4.1 NE-02 | 2m | 2m | 8m |
| 4.2 OS-01 | 1~2m | 2m | 10m |
| 4.3 KSM-02-04 | 5~7m | 7m | 17m |
| 4.4 NE-OOM-tuning | 5m | 5m | 22m |
| 4.5 KSM-OOM-tuning | 5m | 5m | 27m |
| 4.6 PR-03-04 | 5m | 5m | 32m |
| 4.7 OS-02 | 7m | 7m | 39m |
| 4.8 OS-16 (★) | 30m | 30m | 69m |
| 4.9 FB-OOM-tuning | 18m | 18m | 87m |
| 4.10 CHAOS-FB-restart | 3m | 3m | 90m |
| 4.11 CHAOS-OS-07 | 10m | 10m | 100m |

전체 약 **1시간 40분**. 4.8 OS-16 (30분) 동안 다른 시나리오 병행 가능.

---

## 다음 단계

testbed 검증 완료 후:
1. `docs/06-testbed-handson-results.md` 에 실측값 기록
2. 발견된 이슈 (NE limit 등) 운영 helm values 에 반영
3. 폐쇄망 으로 이전: §STEP 0 의 `IMG_PREFIX=nexus` 로 변경 + `00-prerequisites/lt-config.yaml`, `opensearch-creds.yaml` 의 endpoint/자격 변경
