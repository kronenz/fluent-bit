# OpenSearch Benchmark 2.0.0 컨테이너 + Dataset 패키징 가이드

> 내부 opensearch-benchmark 2.0.0 이미지 기반으로 dataset을 함께 패키징하여 K8s Pod에서 벤치마크 테스트를 실행하는 방법

---

## 1. 전체 구성도

```
┌─────────────────────────────────────────────────────┐
│  osb-client Pod                                     │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │ opensearch-benchmark:2.0.0 (base image)       │  │
│  │                                               │  │
│  │  /opt/osb/workloads/geonames/                 │  │
│  │    ├── workload.json  (base-url 제거됨)        │  │
│  │    ├── index.json                             │  │
│  │    ├── _operations/default.json               │  │
│  │    └── _test-procedures/default.json          │  │
│  │                                               │  │
│  │  /opt/osb/data/geonames/                      │  │
│  │    └── documents.json(.bz2)                   │  │
│  │                                               │  │
│  │  /opt/osb/benchmark.ini  (endpoint 설정)       │  │
│  │  /opt/osb/scripts/*.sh   (테스트 스크립트)      │  │
│  └───────────────────────────────────────────────┘  │
│                        │                            │
│                        ▼                            │
│              opensearch-benchmark                   │
│              execute-test                           │
│              --workload-path=...                    │
│              --target-hosts=...                     │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  OpenSearch Cluster  │
              │  (StorageClass별     │
              │   3회 반복 테스트)    │
              └──────────────────────┘
```

---

## 2. 사전 준비 (인터넷 환경)

### 2.1 Workload 정의 + Data Corpora 수집

```bash
# ── 인터넷 가능 환경에서 실행 ──

# 1) Workload 정의 가져오기
git clone https://github.com/opensearch-project/opensearch-benchmark-workloads.git
mkdir -p build/workloads build/data

# 사용할 workload 복사
cp -r opensearch-benchmark-workloads/geonames build/workloads/
cp -r opensearch-benchmark-workloads/pmc build/workloads/

# 2) Data Corpora 다운로드
#    workload.json의 corpora → base-url + source-file 확인 후 다운로드
#
#    geonames: ~265MB (압축), ~3.3GB (해제)
#    pmc:      ~1.2GB (압축)

# 방법 A: OSB를 한 번 실행하여 자동 다운로드
pip install opensearch-benchmark==2.0.0
opensearch-benchmark execute-test --workload=geonames --test-mode \
  --pipeline=benchmark-only --target-hosts=localhost:9200 2>/dev/null || true

# 다운로드된 데이터 복사
cp -r ~/.benchmark/benchmarks/data/geonames build/data/
cp -r ~/.benchmark/benchmarks/data/pmc build/data/

# 방법 B: 직접 다운로드 (URL은 workload.json에서 확인)
# wget -O build/data/geonames/documents.json.bz2 \
#   "https://dbyiw3u3rf9yr.cloudfront.net/corpora/geonames/documents.json.bz2"
```

### 2.2 workload.json 수정 — base-url 제거

**이 단계가 핵심!** `base-url`을 제거하면 OSB가 인터넷 다운로드를 시도하지 않고 로컬 데이터를 사용한다.

```bash
cd build/workloads/geonames

# workload.json에서 base-url 줄 제거
python3 -c "
import json

with open('workload.json', 'r') as f:
    wl = json.load(f)

for corpus in wl.get('corpora', []):
    for doc in corpus.get('documents', []):
        doc.pop('base-url', None)

with open('workload.json', 'w') as f:
    json.dump(wl, f, indent=2)

print('base-url removed from workload.json')
"
```

pmc workload도 동일하게 처리한다.

---

## 3. Dockerfile 작성

### 3.1 디렉토리 구조

```
osb-build/
├── Dockerfile
├── benchmark.ini              # OSB 설정 파일
├── workloads/
│   ├── geonames/              # workload 정의 (base-url 제거됨)
│   │   ├── workload.json
│   │   ├── index.json
│   │   ├── _operations/
│   │   │   └── default.json
│   │   ├── _test-procedures/
│   │   │   └── default.json
│   │   └── files.txt
│   └── pmc/
│       └── ... (동일 구조)
├── data/
│   ├── geonames/
│   │   └── documents.json.bz2  # (~265MB)
│   └── pmc/
│       └── documents.json.bz2  # (~1.2GB)
├── scripts/
│   ├── run-t1-indexing.sh
│   ├── run-t2-search.sh
│   ├── run-all.sh
│   └── collect-results.sh
└── entrypoint.sh
```

### 3.2 Dockerfile

```dockerfile
# ============================================================
# OpenSearch Benchmark 2.0.0 + Dataset 패키징
# ============================================================
# 내부에 준비된 opensearch-benchmark:2.0.0 이미지를 base로 사용
FROM <private-registry>/opensearch-benchmark:2.0.0

USER root

# 추가 유틸리티 설치 (필요 시)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl jq vim procps \
    && rm -rf /var/lib/apt/lists/* \
    || true

# ── 작업 디렉토리 ──
WORKDIR /opt/osb

# ── benchmark.ini (OSB 설정) ──
COPY benchmark.ini /opt/osb/benchmark.ini

# ── Workload 정의 복사 (base-url 제거된 버전) ──
COPY workloads/ /opt/osb/workloads/

# ── Data Corpora 복사 (대용량) ──
# OSB가 데이터를 찾는 기본 경로에 배치
# OSB 2.x: ~/.benchmark/benchmarks/data/<workload명>/
RUN mkdir -p /root/.benchmark/benchmarks/data
COPY data/geonames/ /root/.benchmark/benchmarks/data/geonames/
COPY data/pmc/ /root/.benchmark/benchmarks/data/pmc/

# ── 테스트 스크립트 복사 ──
COPY scripts/ /opt/osb/scripts/
RUN chmod +x /opt/osb/scripts/*.sh

# ── 진입점 ──
COPY entrypoint.sh /opt/osb/entrypoint.sh
RUN chmod +x /opt/osb/entrypoint.sh

# 결과 저장 디렉토리
RUN mkdir -p /opt/osb/results

ENTRYPOINT ["/opt/osb/entrypoint.sh"]
```

> **이미지 크기 주의**: geonames 데이터(~265MB bz2)와 pmc 데이터(~1.2GB bz2)가 포함되므로 이미지가 약 1.5~2GB가 될 수 있다. 데이터가 너무 크면 PVC로 분리하는 방법도 고려.

---

## 4. 설정 파일

### 4.1 benchmark.ini

```ini
[meta]
config.version = 17

[system]
env.name = local

[node]
root.dir = /root/.benchmark
src.root.dir = /root/.benchmark/benchmarks

[source]
# ★ 오프라인 모드: Git에서 workload를 가져오지 않음
remote.repo.url =
offline.mode = true

[benchmarks]
# 데이터 캐시 경로 (이미 COPY로 배치됨)
local.dataset.cache = /root/.benchmark/benchmarks/data

[results_publishing]
datastore.type = in-memory

[driver]
# 네트워크 타임아웃 (대용량 색인 시 늘려야 할 수 있음)
on.error = abort

[client]
# SSL/TLS 관련 설정 (필요 시)
# options.verify_certs = false
# options.use_ssl = true
# options.ca_certs = /path/to/ca.pem
```

### 4.2 entrypoint.sh

```bash
#!/bin/bash
set -e

echo "============================================="
echo " OpenSearch Benchmark 2.0.0 + Dataset"
echo "============================================="

# OSB 버전 확인
echo "OSB Version: $(opensearch-benchmark --version 2>/dev/null || echo 'checking...')"
echo ""

# 환경변수 확인
echo "Configuration:"
echo "  OS_ENDPOINT:    ${OS_ENDPOINT:-not set}"
echo "  OS_USER:        ${OS_USER:-admin}"
echo "  OS_USE_SSL:     ${OS_USE_SSL:-false}"
echo "  STORAGE_TYPE:   ${STORAGE_TYPE:-not set}"
echo ""

# Workload 확인
echo "Available workloads:"
ls -d /opt/osb/workloads/*/
echo ""

# Data 확인
echo "Available data corpora:"
ls -lh /root/.benchmark/benchmarks/data/*/
echo ""

# 스크립트 확인
echo "Available scripts:"
ls /opt/osb/scripts/
echo ""

echo "============================================="
echo " Ready. Use kubectl exec to run tests."
echo "============================================="
echo ""
echo "Quick start:"
echo "  # T1: Bulk Indexing"
echo "  /opt/osb/scripts/run-t1-indexing.sh"
echo ""
echo "  # T2: Search Query"
echo "  /opt/osb/scripts/run-t2-search.sh"
echo ""
echo "  # Run all tests"
echo "  /opt/osb/scripts/run-all.sh"
echo ""

# Pod를 계속 실행 상태로 유지
exec tail -f /dev/null
```

---

## 5. 테스트 스크립트

### 5.1 run-t1-indexing.sh

```bash
#!/bin/bash
# ── T1: Bulk Indexing Test (geonames) ──
set -e

# 환경변수에서 설정 읽기 (K8s ConfigMap/env로 주입)
OS_ENDPOINT="${OS_ENDPOINT:?'OS_ENDPOINT env required (e.g. opensearch-cluster:9200)'}"
OS_USER="${OS_USER:-admin}"
OS_PASS="${OS_PASS:-admin}"
OS_USE_SSL="${OS_USE_SSL:-false}"
STORAGE_TYPE="${STORAGE_TYPE:-unknown}"
RUN_NUM="${1:-1}"
TOTAL_RUNS="${2:-3}"

# 결과 디렉토리
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULT_DIR="/opt/osb/results/${STORAGE_TYPE}/t1-indexing"
mkdir -p "${RESULT_DIR}"

echo "============================================="
echo " T1: Bulk Indexing Test (geonames)"
echo " Storage:  ${STORAGE_TYPE}"
echo " Target:   ${OS_ENDPOINT}"
echo " SSL:      ${OS_USE_SSL}"
echo " Run:      ${RUN_NUM}/${TOTAL_RUNS}"
echo "============================================="

# client-options 구성
CLIENT_OPTS="basic_auth_user:${OS_USER},basic_auth_password:${OS_PASS}"
if [ "${OS_USE_SSL}" = "true" ]; then
  CLIENT_OPTS="${CLIENT_OPTS},use_ssl:true,verify_certs:false"
else
  CLIENT_OPTS="${CLIENT_OPTS},use_ssl:false"
fi

# 이전 인덱스 정리
echo "[1/4] Cleaning up..."
PROTOCOL="http"
[ "${OS_USE_SSL}" = "true" ] && PROTOCOL="https"

curl -sk -X DELETE "${PROTOCOL}://${OS_USER}:${OS_PASS}@${OS_ENDPOINT}/geonames" || true
curl -sk -X POST "${PROTOCOL}://${OS_USER}:${OS_PASS}@${OS_ENDPOINT}/_cache/clear" || true
sleep 5

# OS Cache flush (privileged 필요)
echo "[2/4] Flushing caches..."
sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || echo "(cache flush skipped - not privileged)"

# 벤치마크 실행
echo "[3/4] Running opensearch-benchmark..."
opensearch-benchmark execute-test \
  --workload-path=/opt/osb/workloads/geonames \
  --pipeline=benchmark-only \
  --target-hosts="${OS_ENDPOINT}" \
  --client-options="${CLIENT_OPTS}" \
  --test-procedure=append-no-conflicts \
  --on-error=abort \
  --kill-running-processes \
  2>&1 | tee "${RESULT_DIR}/run${RUN_NUM}_${TIMESTAMP}.log"

echo "[4/4] Results saved to ${RESULT_DIR}/"
echo "Done."
```

### 5.2 run-t2-search.sh

```bash
#!/bin/bash
# ── T2: Search Query Test (pmc) ──
set -e

OS_ENDPOINT="${OS_ENDPOINT:?'OS_ENDPOINT env required'}"
OS_USER="${OS_USER:-admin}"
OS_PASS="${OS_PASS:-admin}"
OS_USE_SSL="${OS_USE_SSL:-false}"
STORAGE_TYPE="${STORAGE_TYPE:-unknown}"
RUN_NUM="${1:-1}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULT_DIR="/opt/osb/results/${STORAGE_TYPE}/t2-search"
mkdir -p "${RESULT_DIR}"

echo "===== T2: Search Query Test (pmc) ====="
echo " Storage: ${STORAGE_TYPE} | Run: ${RUN_NUM}"

CLIENT_OPTS="basic_auth_user:${OS_USER},basic_auth_password:${OS_PASS}"
[ "${OS_USE_SSL}" = "true" ] && CLIENT_OPTS="${CLIENT_OPTS},use_ssl:true,verify_certs:false"

opensearch-benchmark execute-test \
  --workload-path=/opt/osb/workloads/pmc \
  --pipeline=benchmark-only \
  --target-hosts="${OS_ENDPOINT}" \
  --client-options="${CLIENT_OPTS}" \
  --on-error=abort \
  --kill-running-processes \
  2>&1 | tee "${RESULT_DIR}/run${RUN_NUM}_${TIMESTAMP}.log"

echo "Done. Results: ${RESULT_DIR}/"
```

### 5.3 run-all.sh

```bash
#!/bin/bash
# ── 전체 테스트 자동 실행 (T1 + T2, 3회 반복) ──
set -e

OS_ENDPOINT="${OS_ENDPOINT:?'OS_ENDPOINT env required'}"
STORAGE_TYPE="${STORAGE_TYPE:?'STORAGE_TYPE env required (local-path|isilon-hdd|ssd)'}"
COOLDOWN="${COOLDOWN:-60}"
RUNS="${RUNS:-3}"

echo "============================================="
echo " Full Benchmark Suite"
echo " Storage: ${STORAGE_TYPE}"
echo " Endpoint: ${OS_ENDPOINT}"
echo " Runs: ${RUNS}"
echo " Cooldown: ${COOLDOWN}s"
echo "============================================="

# ── T1: Bulk Indexing ──
echo ""
echo "========== T1: Bulk Indexing (geonames) =========="
for i in $(seq 1 ${RUNS}); do
  echo "--- Run ${i}/${RUNS} ---"
  /opt/osb/scripts/run-t1-indexing.sh ${i} ${RUNS}
  echo "Cooldown ${COOLDOWN}s..."
  sleep ${COOLDOWN}
done

# ── T2: Search Query ──
echo ""
echo "========== T2: Search Query (pmc) =========="
for i in $(seq 1 ${RUNS}); do
  echo "--- Run ${i}/${RUNS} ---"
  /opt/osb/scripts/run-t2-search.sh ${i}
  echo "Cooldown ${COOLDOWN}s..."
  sleep ${COOLDOWN}
done

echo ""
echo "============================================="
echo " All tests completed for ${STORAGE_TYPE}"
echo " Results: /opt/osb/results/${STORAGE_TYPE}/"
echo "============================================="
ls -R /opt/osb/results/${STORAGE_TYPE}/
```

---

## 6. Docker Build & Push

```bash
# ── 폐쇄망 빌드 서버에서 실행 ──

cd osb-build/

# Base 이미지가 이미 내부 Registry에 있으므로 바로 빌드
docker build -t <private-registry>/osb-client:2.0.0 .

# 이미지 크기 확인
docker images | grep osb-client

# Push
docker push <private-registry>/osb-client:2.0.0
```

> **빌드 팁**: 데이터 파일이 크므로 `.dockerignore`에 불필요한 파일을 넣어 빌드 context 크기를 줄인다.

```
# .dockerignore
.git
opensearch-benchmark-workloads/.git
*.md
```

---

## 7. K8s 배포

### 7.1 ConfigMap — OpenSearch 연결 설정

```yaml
# k8s/osb-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: osb-config
  namespace: os-perf-test
data:
  # ── OpenSearch 엔드포인트 ──
  OS_ENDPOINT: "opensearch-cluster-master.opensearch.svc.cluster.local:9200"

  # ── 인증 정보 ──
  OS_USER: "admin"
  OS_USE_SSL: "false"

  # ── 테스트 설정 ──
  COOLDOWN: "60"
  RUNS: "3"
```

### 7.2 Secret — 패스워드

```yaml
# k8s/osb-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: osb-secret
  namespace: os-perf-test
type: Opaque
stringData:
  OS_PASS: "admin"    # 실제 패스워드로 변경
```

### 7.3 PVC — 결과 저장

```yaml
# k8s/osb-results-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: osb-results-pvc
  namespace: os-perf-test
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: local-path    # 결과 저장용이므로 아무 SC 가능
  resources:
    requests:
      storage: 10Gi
```

### 7.4 Deployment

```yaml
# k8s/osb-client-deploy.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: osb-client
  namespace: os-perf-test
  labels:
    app: osb-client
spec:
  replicas: 1
  selector:
    matchLabels:
      app: osb-client
  template:
    metadata:
      labels:
        app: osb-client
    spec:
      containers:
      - name: osb
        image: <private-registry>/osb-client:2.0.0
        imagePullPolicy: IfNotPresent

        # ── 환경변수: ConfigMap + Secret ──
        envFrom:
        - configMapRef:
            name: osb-config
        - secretRef:
            name: osb-secret

        # ── 스토리지 유형 (테스트마다 변경) ──
        env:
        - name: STORAGE_TYPE
          value: "local-path"    # ← 테스트 대상에 따라 변경
                                  #    local-path / isilon-hdd / ssd

        resources:
          requests:
            cpu: "2"
            memory: 4Gi
          limits:
            cpu: "4"
            memory: 8Gi

        volumeMounts:
        - name: results
          mountPath: /opt/osb/results

      volumes:
      - name: results
        persistentVolumeClaim:
          claimName: osb-results-pvc

      imagePullSecrets:
      - name: registry-secret

      # osb-client는 어느 노드든 상관없음
      # Data Node가 아닌 곳에 배치하여 간섭 최소화
      # affinity:
      #   nodeAffinity:
      #     requiredDuringSchedulingIgnoredDuringExecution:
      #       nodeSelectorTerms:
      #       - matchExpressions:
      #         - key: node-role
      #           operator: NotIn
      #           values: ["opensearch-data"]
```

---

## 8. 테스트 실행

### 8.1 배포

```bash
# Namespace 생성
kubectl create namespace os-perf-test 2>/dev/null || true

# Registry Secret (이미 있으면 스킵)
kubectl create secret docker-registry registry-secret \
  --docker-server=<private-registry> \
  --docker-username=<user> \
  --docker-password=<pass> \
  -n os-perf-test 2>/dev/null || true

# ConfigMap, Secret, PVC, Deployment 배포
kubectl apply -f k8s/osb-config.yaml
kubectl apply -f k8s/osb-secret.yaml
kubectl apply -f k8s/osb-results-pvc.yaml
kubectl apply -f k8s/osb-client-deploy.yaml

# Pod 상태 확인
kubectl get pods -n os-perf-test -w
```

### 8.2 테스트 실행

```bash
# Pod 이름 확인
OSB_POD=$(kubectl get pod -n os-perf-test -l app=osb-client -o jsonpath='{.items[0].metadata.name}')

# ── 방법 1: 전체 자동 실행 ──
kubectl exec -n os-perf-test ${OSB_POD} -- /opt/osb/scripts/run-all.sh

# ── 방법 2: 개별 실행 ──
# T1: Bulk Indexing 1회차
kubectl exec -n os-perf-test ${OSB_POD} -- /opt/osb/scripts/run-t1-indexing.sh 1 3

# T2: Search Query 1회차
kubectl exec -n os-perf-test ${OSB_POD} -- /opt/osb/scripts/run-t2-search.sh 1

# ── 방법 3: Pod에 접속하여 직접 실행 ──
kubectl exec -it -n os-perf-test ${OSB_POD} -- bash

# Pod 내부에서:
opensearch-benchmark execute-test \
  --workload-path=/opt/osb/workloads/geonames \
  --pipeline=benchmark-only \
  --target-hosts=${OS_ENDPOINT} \
  --client-options="basic_auth_user:${OS_USER},basic_auth_password:${OS_PASS},use_ssl:false" \
  --test-procedure=append-no-conflicts
```

### 8.3 스토리지 변경 후 반복

```bash
# 1) OpenSearch 클러스터의 StorageClass 변경
#    → Helm values.yaml에서 persistence.storageClass 변경
#    → helm upgrade opensearch ./opensearch -f values-isilon.yaml -n opensearch
#    → 클러스터 Green 상태 대기

# 2) osb-client의 STORAGE_TYPE 환경변수 변경
kubectl set env deployment/osb-client \
  STORAGE_TYPE=isilon-hdd \
  -n os-perf-test

# Pod 재시작 대기
kubectl rollout status deployment/osb-client -n os-perf-test

# 3) 테스트 재실행
kubectl exec -n os-perf-test ${OSB_POD} -- /opt/osb/scripts/run-all.sh
```

### 8.4 결과 수집

```bash
# Pod에서 로컬로 결과 복사
kubectl cp os-perf-test/${OSB_POD}:/opt/osb/results ./benchmark-results/

# 결과 구조 확인
tree ./benchmark-results/
# benchmark-results/
# ├── local-path/
# │   ├── t1-indexing/
# │   │   ├── run1_20260324_100000.log
# │   │   ├── run2_20260324_102000.log
# │   │   └── run3_20260324_104000.log
# │   └── t2-search/
# │       └── ...
# ├── isilon-hdd/
# │   └── ...
# └── ssd/
#     └── ...
```

---

## 9. 고급 설정

### 9.1 SSL/TLS 연결

OpenSearch가 HTTPS를 사용하는 경우:

```yaml
# ConfigMap 변경
data:
  OS_ENDPOINT: "opensearch-cluster-master.opensearch.svc.cluster.local:9200"
  OS_USE_SSL: "true"
```

자체 서명 인증서를 사용하는 경우, CA 인증서를 마운트:

```yaml
# Deployment에 추가
volumes:
- name: ca-cert
  secret:
    secretName: opensearch-ca-cert
containers:
- name: osb
  volumeMounts:
  - name: ca-cert
    mountPath: /opt/osb/certs
    readOnly: true
  env:
  - name: OS_CA_CERT
    value: "/opt/osb/certs/ca.crt"
```

스크립트에서:
```bash
CLIENT_OPTS="basic_auth_user:${OS_USER},basic_auth_password:${OS_PASS}"
CLIENT_OPTS="${CLIENT_OPTS},use_ssl:true,verify_certs:true"
CLIENT_OPTS="${CLIENT_OPTS},ca_certs:${OS_CA_CERT}"
```

### 9.2 데이터를 PVC로 분리 (이미지 크기 축소)

데이터가 너무 커서 이미지에 포함하기 어려운 경우:

```yaml
# PVC에 데이터를 별도로 적재
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: osb-data-pvc
  namespace: os-perf-test
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: local-path
  resources:
    requests:
      storage: 20Gi
---
# 데이터 로드용 임시 Pod
apiVersion: v1
kind: Pod
metadata:
  name: data-loader
  namespace: os-perf-test
spec:
  containers:
  - name: loader
    image: busybox
    command: ["sleep", "3600"]
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: osb-data-pvc
```

```bash
# 데이터 복사
kubectl cp build/data/geonames/ os-perf-test/data-loader:/data/geonames/
kubectl cp build/data/pmc/ os-perf-test/data-loader:/data/pmc/
kubectl delete pod data-loader -n os-perf-test
```

Deployment에서 데이터 PVC 마운트:
```yaml
volumeMounts:
- name: osb-data
  mountPath: /root/.benchmark/benchmarks/data
volumes:
- name: osb-data
  persistentVolumeClaim:
    claimName: osb-data-pvc
```

### 9.3 OSB 2.x 명령어 참고

OSB 2.x에서는 일부 명령어 용어가 변경되었다:

| OSB 1.x | OSB 2.x |
|---------|---------|
| `opensearch-benchmark run` | `opensearch-benchmark execute-test` |
| `--track` | `--workload` |
| `--track-path` | `--workload-path` |
| `--challenge` | `--test-procedure` |
| `--car` | `--provision-config-instance` |
| `race.json` | `test_execution.json` |
| `--race-id` | `--test-execution-id` |

---

## 10. 트러블슈팅

**문제 1**: `No data file found for source-file [documents.json]`
```
원인: 데이터 파일 경로 불일치
확인: ls -la /root/.benchmark/benchmarks/data/geonames/
      workload.json의 source-file 이름과 실제 파일명 비교
해결: 파일명이 documents.json.bz2인지, documents.json인지 확인
      OSB가 bz2를 자동 해제하므로 압축 상태로 두어도 됨
```

**문제 2**: `Connection refused` / `Connection timeout`
```
원인: OpenSearch 엔드포인트 접근 불가
확인: kubectl exec ${OSB_POD} -- curl -sk http://${OS_ENDPOINT}/_cluster/health
해결: Service DNS 확인, 포트 확인, NetworkPolicy 확인
```

**문제 3**: `SSL: CERTIFICATE_VERIFY_FAILED`
```
원인: HTTPS 사용 시 인증서 검증 실패
해결: client-options에 verify_certs:false 추가
      또는 CA 인증서를 마운트하여 ca_certs 경로 지정
```

**문제 4**: `Could not execute workload` (메모리 부족)
```
원인: OSB Pod의 메모리 부족
해결: Pod resources.limits.memory를 8Gi 이상으로 설정
      geonames workload는 최소 4GB 이상 권장
```

**문제 5**: `Could not reach remote workload repository`
```
원인: OSB가 GitHub에서 workload를 가져오려고 시도
해결: --workload-path 옵션을 사용하고 있는지 확인
      --workload=geonames 대신 --workload-path=/opt/osb/workloads/geonames 사용
      benchmark.ini에 offline.mode = true 설정 확인
```

---

> **끝.**

# opensearch-benchmark 2.0.0 + http_logs Dockerfile 구성 가이드

---

## 1. 전체 흐름

```
[인터넷 PC]                    [폐쇄망]
                                
 ① git clone workloads         ④ docker build
 ② 데이터 다운로드               ⑤ docker push → Private Registry
 ③ base-url 제거               ⑥ K8s Pod 배포 → 테스트 실행
      │                              │
      └── USB/SCP 이관 ──────────────┘
```

---

## 2. 인터넷 PC에서 준비

### 2.1 http_logs workload 파일 가져오기

```powershell
# ── Windows PowerShell ──

# workloads 프로젝트 clone
git clone https://github.com/opensearch-project/opensearch-benchmark-workloads.git

# http_logs만 추출
mkdir osb-build\workloads
Copy-Item -Recurse opensearch-benchmark-workloads\http_logs osb-build\workloads\http_logs
```

http_logs 디렉토리 구조 확인:

```
osb-build\workloads\http_logs\
├── workload.json           # ★ 메인 정의 (corpora, base-url 포함)
├── workload.py             # 동적 기능 (파라미터 처리)
├── index.json              # 인덱스 매핑/설정
├── _operations/
│   └── default.json        # 색인/검색 오퍼레이션 정의
├── _test-procedures/
│   └── default.json        # append-no-conflicts 등 테스트 프로시저
├── files.txt               # 데이터 파일 목록
└── README.md
```

### 2.2 데이터 다운로드

http_logs의 `workload.json`을 열어서 `corpora` → `documents` 항목을 확인한다. http_logs는 **여러 파일로 분할**되어 있다.

```powershell
# workload.json에서 데이터 URL 확인
# 아래 명령으로 base-url과 source-file 목록을 추출
python3 -c "
import json
with open('osb-build/workloads/http_logs/workload.json') as f:
    wl = json.load(f)
for corpus in wl.get('corpora', []):
    for doc in corpus.get('documents', []):
        base = doc.get('base-url', '???')
        src = doc.get('source-file', '???')
        size = doc.get('compressed-bytes', 0)
        print(f'{base}/{src}  ({size/1024/1024:.0f}MB)')
"
```

데이터 다운로드:

```powershell
$ProgressPreference = 'SilentlyContinue'
mkdir osb-build\data\http_logs -Force

# ── workload.json에 나온 모든 파일을 다운로드 ──
# (아래는 예시 — 실제 URL과 파일명은 workload.json에서 확인)

# 방법 1: curl.exe (Windows 10+ 내장)
curl.exe -L -o osb-build\data\http_logs\documents-181998.json.bz2 `
  "https://dbyiw3u3rf9yr.cloudfront.net/corpora/http_logs/documents-181998.json.bz2"

curl.exe -L -o osb-build\data\http_logs\documents-191998.json.bz2 `
  "https://dbyiw3u3rf9yr.cloudfront.net/corpora/http_logs/documents-191998.json.bz2"

curl.exe -L -o osb-build\data\http_logs\documents-201998.json.bz2 `
  "https://dbyiw3u3rf9yr.cloudfront.net/corpora/http_logs/documents-201998.json.bz2"

curl.exe -L -o osb-build\data\http_logs\documents-211998.json.bz2 `
  "https://dbyiw3u3rf9yr.cloudfront.net/corpora/http_logs/documents-211998.json.bz2"

curl.exe -L -o osb-build\data\http_logs\documents-221998.json.bz2 `
  "https://dbyiw3u3rf9yr.cloudfront.net/corpora/http_logs/documents-221998.json.bz2"

# ... workload.json에 명시된 모든 파일

# 다운로드 확인
Get-ChildItem osb-build\data\http_logs\ | Format-Table Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}
```

> **중요**: http_logs는 총 약 **1.6GB** (압축), 비압축 시 **~31GB**. 파일이 여러 개로 나뉘어 있으므로 workload.json의 documents 배열에 있는 파일을 **빠짐없이** 모두 받아야 한다.

### 2.3 workload.json에서 base-url 제거

```powershell
cd osb-build

python3 -c "
import json

with open('workloads/http_logs/workload.json', 'r') as f:
    wl = json.load(f)

count = 0
for corpus in wl.get('corpora', []):
    for doc in corpus.get('documents', []):
        if 'base-url' in doc:
            del doc['base-url']
            count += 1

with open('workloads/http_logs/workload.json', 'w') as f:
    json.dump(wl, f, indent=2)

print(f'Done. Removed base-url from {count} document entries.')
"
```

---

## 3. 빌드 디렉토리 구조

```
osb-build/
├── Dockerfile
├── entrypoint.sh
├── run-test.sh
├── workloads/
│   └── http_logs/
│       ├── workload.json        ← base-url 제거됨
│       ├── workload.py
│       ├── index.json
│       ├── _operations/
│       │   └── default.json
│       ├── _test-procedures/
│       │   └── default.json
│       └── files.txt
└── data/
    └── http_logs/
        ├── documents-181998.json.bz2
        ├── documents-191998.json.bz2
        ├── documents-201998.json.bz2
        ├── documents-211998.json.bz2
        ├── documents-221998.json.bz2
        └── ...                  ← workload.json에 명시된 전체 파일
```

---

## 4. Dockerfile

```dockerfile
# ============================================================
# OpenSearch Benchmark 2.0.0 + http_logs dataset
# ============================================================
FROM <private-registry>/opensearch-benchmark:2.0.0

USER root

# ── http_logs workload 정의 복사 ──
COPY workloads/http_logs/ /opt/osb/workloads/http_logs/

# ── http_logs 데이터 복사 ──
# OSB가 데이터를 찾는 경로: ~/.benchmark/benchmarks/data/<workload명>/
RUN mkdir -p /root/.benchmark/benchmarks/data/http_logs
COPY data/http_logs/ /root/.benchmark/benchmarks/data/http_logs/

# ── 테스트 스크립트 ──
COPY entrypoint.sh /opt/osb/entrypoint.sh
COPY run-test.sh   /opt/osb/run-test.sh
RUN chmod +x /opt/osb/entrypoint.sh /opt/osb/run-test.sh

RUN mkdir -p /opt/osb/results

ENTRYPOINT ["/opt/osb/entrypoint.sh"]
```

> 이미지 크기: base(~500MB) + 데이터(~1.6GB) ≈ **약 2.1GB**

---

## 5. entrypoint.sh

```bash
#!/bin/bash

echo "============================================"
echo " OSB 2.0.0 + http_logs (append-no-conflicts)"
echo "============================================"
echo ""
echo " OS_ENDPOINT : ${OS_ENDPOINT:-not set}"
echo " OS_USER     : ${OS_USER:-admin}"
echo " OS_USE_SSL  : ${OS_USE_SSL:-false}"
echo " STORAGE_TYPE: ${STORAGE_TYPE:-not set}"
echo ""
echo " Workload    : /opt/osb/workloads/http_logs/"
echo " Data        :"
ls -lh /root/.benchmark/benchmarks/data/http_logs/ 2>/dev/null | head -10
echo ""
echo " Usage:"
echo "   /opt/osb/run-test.sh                    # 3회 반복 실행"
echo "   /opt/osb/run-test.sh 1                  # 1회만 실행"
echo ""

exec tail -f /dev/null
```

---

## 6. run-test.sh

```bash
#!/bin/bash
set -e

# ── 환경변수 (K8s ConfigMap/env로 주입) ──
OS_ENDPOINT="${OS_ENDPOINT:?'OS_ENDPOINT 환경변수 필요 (예: opensearch-cluster:9200)'}"
OS_USER="${OS_USER:-admin}"
OS_PASS="${OS_PASS:-admin}"
OS_USE_SSL="${OS_USE_SSL:-false}"
STORAGE_TYPE="${STORAGE_TYPE:-unknown}"
RUNS="${1:-3}"
COOLDOWN="${COOLDOWN:-60}"

# ── client-options 구성 ──
CLIENT_OPTS="basic_auth_user:${OS_USER},basic_auth_password:${OS_PASS}"
if [ "${OS_USE_SSL}" = "true" ]; then
  CLIENT_OPTS="${CLIENT_OPTS},use_ssl:true,verify_certs:false"
fi

RESULT_DIR="/opt/osb/results/${STORAGE_TYPE}"
mkdir -p "${RESULT_DIR}"

echo "╔═══════════════════════════════════════════╗"
echo "║  http_logs — append-no-conflicts          ║"
echo "║  Storage : ${STORAGE_TYPE}"
echo "║  Target  : ${OS_ENDPOINT}"
echo "║  Runs    : ${RUNS}"
echo "╚═══════════════════════════════════════════╝"

PROTO="http"
[ "${OS_USE_SSL}" = "true" ] && PROTO="https"

for i in $(seq 1 ${RUNS}); do
  TS=$(date +%Y%m%d_%H%M%S)
  echo ""
  echo "━━━ Run ${i}/${RUNS} ━━━"

  # 인덱스 정리
  echo "[1/3] 인덱스 정리..."
  curl -sk -X DELETE "${PROTO}://${OS_USER}:${OS_PASS}@${OS_ENDPOINT}/logs-*" || true
  curl -sk -X POST "${PROTO}://${OS_USER}:${OS_PASS}@${OS_ENDPOINT}/_cache/clear" || true
  sleep 5

  # 벤치마크 실행
  echo "[2/3] opensearch-benchmark 실행..."
  opensearch-benchmark execute-test \
    --workload-path=/opt/osb/workloads/http_logs \
    --pipeline=benchmark-only \
    --target-hosts="${OS_ENDPOINT}" \
    --client-options="${CLIENT_OPTS}" \
    --test-procedure=append-no-conflicts \
    --on-error=abort \
    --kill-running-processes \
    2>&1 | tee "${RESULT_DIR}/run${i}_${TS}.log"

  echo "[3/3] 결과 저장: ${RESULT_DIR}/run${i}_${TS}.log"

  if [ ${i} -lt ${RUNS} ]; then
    echo "Cooldown ${COOLDOWN}초..."
    sleep ${COOLDOWN}
  fi
done

echo ""
echo "═══ 완료 ═══"
echo "결과 파일:"
ls -la ${RESULT_DIR}/*.log
```

---

## 7. Docker Build

```bash
# ── 폐쇄망 빌드 서버 ──
cd osb-build/

docker build -t <private-registry>/osb-http-logs:2.0.0 .

# 크기 확인
docker images | grep osb-http-logs

# Push
docker push <private-registry>/osb-http-logs:2.0.0
```

---

## 8. K8s 배포

```yaml
# osb-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: osb-config
  namespace: os-perf-test
data:
  OS_ENDPOINT: "opensearch-cluster-master.opensearch.svc.cluster.local:9200"
  OS_USER: "admin"
  OS_USE_SSL: "false"
  COOLDOWN: "60"
---
# osb-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: osb-secret
  namespace: os-perf-test
type: Opaque
stringData:
  OS_PASS: "admin"
---
# osb-deploy.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: osb-client
  namespace: os-perf-test
spec:
  replicas: 1
  selector:
    matchLabels:
      app: osb-client
  template:
    metadata:
      labels:
        app: osb-client
    spec:
      containers:
      - name: osb
        image: <private-registry>/osb-http-logs:2.0.0
        imagePullPolicy: IfNotPresent
        envFrom:
        - configMapRef:
            name: osb-config
        - secretRef:
            name: osb-secret
        env:
        - name: STORAGE_TYPE
          value: "local-path"      # ← 테스트마다 변경
        resources:
          requests:
            cpu: "2"
            memory: 4Gi
          limits:
            cpu: "4"
            memory: 8Gi
        volumeMounts:
        - name: results
          mountPath: /opt/osb/results
      volumes:
      - name: results
        emptyDir: {}
      imagePullSecrets:
      - name: registry-secret
```

---

## 9. 실행

```bash
# 배포
kubectl create namespace os-perf-test 2>/dev/null || true
kubectl apply -f osb-configmap.yaml
kubectl apply -f osb-secret.yaml
kubectl apply -f osb-deploy.yaml

# Pod 확인
kubectl get pods -n os-perf-test -w

# Pod 이름
OSB=$(kubectl get pod -n os-perf-test -l app=osb-client -o jsonpath='{.items[0].metadata.name}')

# ── 테스트 실행 ──
# 3회 반복 (기본값)
kubectl exec -n os-perf-test $OSB -- /opt/osb/run-test.sh

# 1회만 테스트 (빠른 확인용)
kubectl exec -n os-perf-test $OSB -- /opt/osb/run-test.sh 1

# Pod 접속 후 직접 실행
kubectl exec -it -n os-perf-test $OSB -- bash
opensearch-benchmark execute-test \
  --workload-path=/opt/osb/workloads/http_logs \
  --pipeline=benchmark-only \
  --target-hosts=$OS_ENDPOINT \
  --client-options="basic_auth_user:$OS_USER,basic_auth_password:$OS_PASS" \
  --test-procedure=append-no-conflicts

# ── 스토리지 교체 후 반복 ──
# OpenSearch StorageClass 변경 후:
kubectl set env deploy/osb-client STORAGE_TYPE=isilon-hdd -n os-perf-test
kubectl exec -n os-perf-test $OSB -- /opt/osb/run-test.sh

kubectl set env deploy/osb-client STORAGE_TYPE=ssd -n os-perf-test
kubectl exec -n os-perf-test $OSB -- /opt/osb/run-test.sh

# ── 결과 수집 ──
kubectl cp os-perf-test/$OSB:/opt/osb/results ./results/
```

---

## 10. append-no-conflicts에서 나오는 측정 항목

테스트 완료 시 OSB가 출력하는 주요 지표:

| 측정 항목 | 설명 | 스토리지 비교 포인트 |
|----------|------|:---:|
| **Indexing throughput** (docs/sec) | 초당 색인 문서 수 | ★★★★★ |
| **Indexing latency** (p50/p90/p99) | 색인 지연시간 | ★★★★ |
| **Merge time** | Segment merge 소요 시간 | ★★★★★ |
| **Refresh time** | Index refresh 소요 시간 | ★★★★ |
| **Flush time** | Translog flush 소요 시간 | ★★★★ |
| **Index size** (GB) | 최종 인덱스 크기 | ★★★ |
| **Segment count** | 최종 segment 수 | ★★★ |
| Query latency (default) | 기본 검색 쿼리 지연시간 | ★★★★ |
| Query latency (term/range/agg) | 각 쿼리 유형별 지연시간 | ★★★★ |

---

> **끝.**

