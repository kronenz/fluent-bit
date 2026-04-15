# K8s 성능 테스트 데이터 백업 및 복원 가이드

| 항목 | 내용 |
|------|------|
| **목적** | K8s 클러스터 성능 테스트 기간의 데이터를 Grafana 스냅샷 + Prometheus TSDB 스냅샷으로 이중 보관하고, STG 클러스터에서 복원하여 재분석 |
| **대상 환경** | 운영(PRD) 클러스터: kube-prometheus-stack 기반, STG 클러스터: 복원 및 재분석 환경 |
| **작성일** | 2026-04-15 |
| **상태** | 🔵 IN PROGRESS |

---

## 목차

1. [전체 아키텍처](#1-전체-아키텍처)
2. [사전 준비](#2-사전-준비)
3. [Grafana 스냅샷 생성](#3-grafana-스냅샷-생성)
4. [Prometheus TSDB 스냅샷 생성](#4-prometheus-tsdb-스냅샷-생성)
5. [스냅샷 외부 스토리지 보관](#5-스냅샷-외부-스토리지-보관)
6. [STG 클러스터에서 Prometheus 복원](#6-stg-클러스터에서-prometheus-복원)
7. [STG Grafana에서 복원 데이터 조회](#7-stg-grafana에서-복원-데이터-조회)
8. [검증 절차](#8-검증-절차)
9. [정리 및 주의사항](#9-정리-및-주의사항)
10. [트러블슈팅](#10-트러블슈팅)

---

## 1. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    PRD 클러스터 (운영)                        │
│                                                             │
│  ┌─────────────┐         ┌──────────────────┐               │
│  │  Prometheus  │         │     Grafana      │               │
│  │    TSDB      │         │                  │               │
│  │  (원본 데이터) │         │  스냅샷 생성 (UI) │               │
│  └──────┬───────┘         └────────┬─────────┘               │
│         │                          │                         │
│    TSDB Snapshot API          Snapshot API                   │
│         │                          │                         │
└─────────┼──────────────────────────┼─────────────────────────┘
          │                          │
          ▼                          ▼
   ┌──────────────────────────────────────┐
   │        외부 스토리지 (S3/NFS)         │
   │                                      │
   │  prometheus-snapshot-YYYYMMDD.tar.gz  │
   │  grafana-snapshot (Grafana DB 내)     │
   └──────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    STG 클러스터 (검증)                        │
│                                                             │
│  ┌──────────────────┐       ┌──────────────────┐            │
│  │ Prometheus        │       │     Grafana      │            │
│  │ (읽기 전용 복원)   │◄──────│  DataSource 추가  │            │
│  │                   │       │  대시보드 Import   │            │
│  │ 스냅샷 데이터 마운트 │       │                  │            │
│  └──────────────────┘       └──────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 사전 준비

### 2-1. PRD 클러스터 — Prometheus Admin API 활성화

TSDB 스냅샷 생성을 위해 Admin API가 활성화되어 있어야 합니다.

```yaml
# kube-prometheus-stack values.yaml (PRD)
prometheus:
  prometheusSpec:
    enableAdminAPI: true
```

현재 상태 확인:

```bash
# 포트포워딩
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &

# Admin API 활성화 여부 확인
curl -s http://localhost:9090/api/v1/status/flags | jq '.data["web.enable-admin-api"]'
# "true" 이어야 함
```

비활성화 상태라면 values.yaml 수정 후 `helm upgrade`를 실행합니다.

### 2-2. PRD 클러스터 — Grafana API Key 준비

```bash
# API Key 생성 (Admin 권한)
curl -s -X POST -H "Content-Type: application/json" \
  -u admin:<ADMIN_PASSWORD> \
  "http://grafana:3000/api/auth/keys" \
  -d '{"name":"snapshot-backup","role":"Admin"}' | jq .

# 응답의 key 값을 기록
```

### 2-3. STG 클러스터 — 복원용 리소스 확인

| 항목 | 요구사항 |
|------|----------|
| PV/PVC | TSDB 스냅샷 크기 이상의 볼륨 (운영 TSDB 크기 확인 후 산정) |
| Prometheus | 별도 인스턴스 또는 기존 STG Prometheus에 추가 마운트 |
| Grafana | 복원 Prometheus를 DataSource로 추가 가능한 환경 |
| 네트워크 | S3/NFS 등 외부 스토리지 접근 가능 |

PRD Prometheus TSDB 크기 확인:

```bash
PROM_POD=$(kubectl get pods -n monitoring \
  -l app.kubernetes.io/name=prometheus \
  -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n monitoring ${PROM_POD} -c prometheus -- \
  du -sh /prometheus/
```

---

## 3. Grafana 스냅샷 생성

### 3-1. UI에서 생성 (단건)

1. 성능 테스트 대시보드 열기
2. 시간 범위를 **테스트 수행 기간**으로 정확히 설정
3. 상단 **Share** (공유 아이콘) → **Snapshot** 탭
4. **Snapshot name**: `k8s-perf-test-YYYYMMDD` 형식 권장
5. **Expire**: `Never` 선택
6. **Local Snapshot** 클릭
7. 생성된 URL 기록

> ⚠️ 스냅샷 생성 전 반드시 시간 범위를 확인하세요. 현재 대시보드에 표시된 시간 범위의 데이터만 스냅샷에 포함됩니다.

### 3-2. API로 생성 (자동화 / 다건)

```bash
GRAFANA_URL="http://grafana:3000"
API_KEY="Bearer <YOUR_API_KEY>"
DASHBOARD_UID="<PERF_TEST_DASHBOARD_UID>"

# 1) 대시보드 JSON 가져오기
DASHBOARD_JSON=$(curl -s -H "Authorization: ${API_KEY}" \
  "${GRAFANA_URL}/api/dashboards/uid/${DASHBOARD_UID}")

# 2) 스냅샷 생성
SNAPSHOT_RESULT=$(curl -s -X POST \
  -H "Authorization: ${API_KEY}" \
  -H "Content-Type: application/json" \
  "${GRAFANA_URL}/api/snapshots" \
  -d "{
    \"dashboard\": $(echo ${DASHBOARD_JSON} | jq '.dashboard'),
    \"name\": \"k8s-perf-test-$(date +%Y%m%d-%H%M%S)\",
    \"expires\": 0
  }")

echo ${SNAPSHOT_RESULT} | jq '{url: .url, deleteUrl: .deleteUrl, key: .key}'
```

### 3-3. 스냅샷 목록 확인

```bash
curl -s -H "Authorization: ${API_KEY}" \
  "${GRAFANA_URL}/api/dashboard/snapshots" | \
  jq '.[] | {name, key, created, url}'
```

### 3-4. 스냅샷 Export (STG 이관용)

Grafana 스냅샷은 Grafana DB에 저장되므로, STG에서 보려면 API로 export/import합니다.

```bash
# PRD에서 스냅샷 데이터 export
SNAPSHOT_KEY="<SNAPSHOT_KEY>"
curl -s "${GRAFANA_URL}/api/snapshots/${SNAPSHOT_KEY}" | \
  jq . > snapshot-export-$(date +%Y%m%d).json
```

STG Grafana에 import하는 방법은 [7장](#7-stg-grafana에서-복원-데이터-조회)에서 다룹니다.

---

## 4. Prometheus TSDB 스냅샷 생성

### 4-1. TSDB 스냅샷 생성

```bash
# PRD Prometheus 포트포워딩
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &

# 스냅샷 생성 (운영 무중단)
SNAP_RESULT=$(curl -s -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot)
echo ${SNAP_RESULT} | jq .

# 응답 예시:
# {
#   "status": "success",
#   "data": {
#     "name": "20260415T093000Z-abcdef1234"
#   }
# }

SNAP_NAME=$(echo ${SNAP_RESULT} | jq -r '.data.name')
echo "Snapshot name: ${SNAP_NAME}"
```

### 4-2. 스냅샷 크기 및 무결성 확인

```bash
PROM_POD=$(kubectl get pods -n monitoring \
  -l app.kubernetes.io/name=prometheus \
  -o jsonpath='{.items[0].metadata.name}')

# 크기 확인
kubectl exec -n monitoring ${PROM_POD} -c prometheus -- \
  du -sh /prometheus/snapshots/${SNAP_NAME}

# 블록 목록 확인 (각 블록은 시간 범위별 디렉토리)
kubectl exec -n monitoring ${PROM_POD} -c prometheus -- \
  ls -la /prometheus/snapshots/${SNAP_NAME}/
```

### 4-3. 스냅샷 로컬 복사

```bash
# 로컬로 복사 (시간 소요될 수 있음)
kubectl cp \
  monitoring/${PROM_POD}:/prometheus/snapshots/${SNAP_NAME} \
  ./prometheus-snapshot-${SNAP_NAME} \
  -c prometheus

# 복사 완료 후 크기 비교
du -sh ./prometheus-snapshot-${SNAP_NAME}
```

> ⚠️ TSDB 크기가 수 GB 이상이면 `kubectl cp`가 느릴 수 있습니다. 이 경우 PVC를 직접 마운트하거나, 임시 Pod에서 `tar` + `kubectl exec`으로 스트리밍 복사하는 방법을 권장합니다.

대용량 스냅샷 복사 대안:

```bash
# tar 스트리밍 방식 (대용량 시 권장)
kubectl exec -n monitoring ${PROM_POD} -c prometheus -- \
  tar czf - -C /prometheus/snapshots ${SNAP_NAME} \
  > prometheus-snapshot-${SNAP_NAME}.tar.gz
```

---

## 5. 스냅샷 외부 스토리지 보관

### 5-1. S3 업로드

```bash
# 압축
tar czf prometheus-perf-test-$(date +%Y%m%d).tar.gz \
  ./prometheus-snapshot-${SNAP_NAME}

# S3 업로드
aws s3 cp prometheus-perf-test-$(date +%Y%m%d).tar.gz \
  s3://<BUCKET>/prometheus-backups/

# 업로드 확인
aws s3 ls s3://<BUCKET>/prometheus-backups/ --human-readable
```

### 5-2. NFS 보관 (사내 스토리지)

```bash
# NFS 마운트 경로에 복사
cp prometheus-perf-test-$(date +%Y%m%d).tar.gz \
  /mnt/nfs/prometheus-backups/

# 체크섬 기록
sha256sum prometheus-perf-test-$(date +%Y%m%d).tar.gz > \
  /mnt/nfs/prometheus-backups/prometheus-perf-test-$(date +%Y%m%d).sha256
```

### 5-3. PRD Prometheus 내 스냅샷 정리

외부 보관 완료 후 PRD Prometheus의 디스크를 확보합니다.

```bash
kubectl exec -n monitoring ${PROM_POD} -c prometheus -- \
  rm -rf /prometheus/snapshots/${SNAP_NAME}

# 정리 확인
kubectl exec -n monitoring ${PROM_POD} -c prometheus -- \
  ls /prometheus/snapshots/
```

---

## 6. STG 클러스터에서 Prometheus 복원

> ℹ️ **핵심 원리:** Prometheus TSDB 스냅샷은 독립적인 데이터 디렉토리입니다. 이를 별도 Prometheus 인스턴스의 `--storage.tsdb.path`로 지정하면, 해당 Prometheus는 스냅샷 데이터를 그대로 서빙합니다. 클러스터가 달라도 문제없습니다.

### 6-1. 스냅샷 데이터를 STG 클러스터로 전송

```bash
# S3에서 다운로드
aws s3 cp s3://<BUCKET>/prometheus-backups/prometheus-perf-test-20260415.tar.gz .

# 압축 해제
tar xzf prometheus-perf-test-20260415.tar.gz

# 체크섬 검증 (NFS 보관 시)
sha256sum -c prometheus-perf-test-20260415.sha256
```

### 6-2. 방법 A — 전용 PVC + Deployment (권장)

STG 클러스터에 복원 전용 Prometheus를 배포합니다. 기존 STG Prometheus에 영향을 주지 않습니다.

**PVC 생성:**

```yaml
# prom-restore-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prom-perf-test-data
  namespace: monitoring
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 50Gi          # 스냅샷 크기에 맞게 조정
  storageClassName: <STG_STORAGE_CLASS>
```

```bash
kubectl apply -f prom-restore-pvc.yaml -n monitoring
```

**스냅샷 데이터 PVC에 복사:**

```bash
# 임시 Pod으로 PVC 마운트 후 데이터 복사
kubectl run prom-data-loader --rm -it \
  --image=busybox \
  -n monitoring \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "loader",
        "image": "busybox",
        "command": ["sh"],
        "stdin": true,
        "tty": true,
        "volumeMounts": [{
          "name": "data",
          "mountPath": "/data"
        }]
      }],
      "volumes": [{
        "name": "data",
        "persistentVolumeClaim": {
          "claimName": "prom-perf-test-data"
        }
      }]
    }
  }'

# 임시 Pod 내부에서 (별도 터미널)
kubectl cp ./prometheus-snapshot-${SNAP_NAME}/ \
  monitoring/prom-data-loader:/data/ 
```

또는 tar 스트리밍으로 직접 복사:

```bash
# 로컬 → PVC 직접 복사
kubectl run prom-data-loader \
  --image=busybox \
  -n monitoring \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "loader",
        "image": "busybox",
        "command": ["sleep","3600"],
        "volumeMounts": [{
          "name": "data",
          "mountPath": "/data"
        }]
      }],
      "volumes": [{
        "name": "data",
        "persistentVolumeClaim": {
          "claimName": "prom-perf-test-data"
        }
      }]
    }
  }'

# 데이터 복사
kubectl cp ./prometheus-snapshot-${SNAP_NAME}/ \
  monitoring/prom-data-loader:/data/

# PVC 내 데이터 확인
kubectl exec -n monitoring prom-data-loader -- ls -la /data/

# 임시 Pod 삭제
kubectl delete pod prom-data-loader -n monitoring
```

**복원용 Prometheus Deployment:**

```yaml
# prom-restore-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus-perf-review
  namespace: monitoring
  labels:
    app: prometheus-perf-review
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prometheus-perf-review
  template:
    metadata:
      labels:
        app: prometheus-perf-review
    spec:
      securityContext:
        runAsUser: 65534
        runAsGroup: 65534
        fsGroup: 65534
      containers:
        - name: prometheus
          image: prom/prometheus:v2.53.0
          args:
            - "--config.file=/etc/prometheus/prometheus.yml"
            - "--storage.tsdb.path=/prometheus"
            - "--storage.tsdb.retention.time=365d"
            - "--storage.tsdb.no-lockfile"        # 읽기 전용 안전 옵션
            - "--web.listen-address=:9090"
            - "--web.enable-lifecycle"
          ports:
            - containerPort: 9090
          volumeMounts:
            - name: tsdb-data
              mountPath: /prometheus
              readOnly: false
            - name: config
              mountPath: /etc/prometheus
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 4Gi
      volumes:
        - name: tsdb-data
          persistentVolumeClaim:
            claimName: prom-perf-test-data
        - name: config
          configMap:
            name: prometheus-perf-review-config
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-perf-review-config
  namespace: monitoring
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
    # 스크랩 대상 없음 — 과거 데이터 조회 전용
---
apiVersion: v1
kind: Service
metadata:
  name: prometheus-perf-review
  namespace: monitoring
spec:
  type: ClusterIP
  selector:
    app: prometheus-perf-review
  ports:
    - port: 9090
      targetPort: 9090
      protocol: TCP
```

```bash
kubectl apply -f prom-restore-deployment.yaml -n monitoring

# Pod 상태 확인
kubectl get pods -n monitoring -l app=prometheus-perf-review

# 로그 확인 — "Server is ready to receive web requests" 메시지 확인
kubectl logs -n monitoring -l app=prometheus-perf-review | tail -20
```

### 6-3. 방법 B — Docker Compose (로컬/VM 복원)

K8s 없이 단독 서버에서 빠르게 복원할 때 사용합니다.

```yaml
# docker-compose.yaml
version: "3.8"
services:
  prometheus:
    image: prom/prometheus:v2.53.0
    container_name: prom-perf-review
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=365d"
      - "--storage.tsdb.no-lockfile"
      - "--web.listen-address=:9090"
    volumes:
      - ./prometheus-snapshot-${SNAP_NAME}:/prometheus
      - ./prometheus-minimal.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9091:9090"

  grafana:
    image: grafana/grafana:11.0.0
    container_name: grafana-perf-review
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    ports:
      - "3001:3000"
    depends_on:
      - prometheus
```

```yaml
# prometheus-minimal.yml
global:
  scrape_interval: 15s
```

```bash
docker-compose up -d

# 접속: Prometheus http://localhost:9091, Grafana http://localhost:3001
```

---

## 7. STG Grafana에서 복원 데이터 조회

### 7-1. DataSource 추가

STG Grafana에서 복원된 Prometheus를 데이터소스로 추가합니다.

```bash
# API로 DataSource 추가
curl -s -X POST \
  -H "Content-Type: application/json" \
  -u admin:<STG_ADMIN_PASSWORD> \
  "http://<STG_GRAFANA>:3000/api/datasources" \
  -d '{
    "name": "Prometheus-PerfTest-Review",
    "type": "prometheus",
    "url": "http://prometheus-perf-review.monitoring.svc.cluster.local:9090",
    "access": "proxy",
    "isDefault": false,
    "jsonData": {
      "timeInterval": "15s"
    }
  }' | jq .
```

UI에서 추가할 경우:

1. STG Grafana → **Configuration** → **Data Sources** → **Add data source**
2. Type: **Prometheus**
3. URL: `http://prometheus-perf-review.monitoring.svc.cluster.local:9090`
4. **Save & Test** → `Data source is working` 확인

### 7-2. 성능 테스트 대시보드 Import

PRD에서 사용한 성능 테스트 대시보드를 STG에 import합니다.

```bash
# PRD에서 대시보드 export
curl -s -H "Authorization: Bearer <PRD_API_KEY>" \
  "http://<PRD_GRAFANA>:3000/api/dashboards/uid/<DASHBOARD_UID>" | \
  jq '{dashboard: .dashboard, overwrite: true}' | \
  jq '.dashboard.id = null' \
  > perf-dashboard-export.json

# STG에 import
curl -s -X POST \
  -H "Content-Type: application/json" \
  -u admin:<STG_ADMIN_PASSWORD> \
  "http://<STG_GRAFANA>:3000/api/dashboards/db" \
  -d @perf-dashboard-export.json | jq .
```

> ⚠️ Import 후 대시보드의 DataSource를 `Prometheus-PerfTest-Review`로 변경해야 합니다. 대시보드 Settings → Variables 또는 각 패널의 DataSource 선택을 확인하세요.

### 7-3. Grafana 스냅샷 Import (STG)

PRD에서 export한 스냅샷 JSON을 STG Grafana에 import합니다.

```bash
# 3-4에서 export한 파일 사용
SNAPSHOT_FILE="snapshot-export-20260415.json"

# STG Grafana에 스냅샷 import
curl -s -X POST \
  -H "Content-Type: application/json" \
  -u admin:<STG_ADMIN_PASSWORD> \
  "http://<STG_GRAFANA>:3000/api/snapshots" \
  -d @${SNAPSHOT_FILE} | jq '{url: .url, key: .key}'
```

---

## 8. 검증 절차

### 8-1. Prometheus 복원 데이터 검증

```bash
# STG에서 복원 Prometheus 포트포워딩
kubectl port-forward -n monitoring svc/prometheus-perf-review 9091:9090 &

# 데이터 시간 범위 확인 — TSDB의 min/max time 조회
curl -s http://localhost:9091/api/v1/status/tsdb | jq '.data | {
  headMinTime: .headStats.minTime,
  headMaxTime: .headStats.maxTime,
  numSeries: .headStats.numSeries,
  numBlocks: (.blockStats // [] | length)
}'
```

기대 결과: `minTime` ~ `maxTime`이 성능 테스트 기간을 포함해야 합니다.

### 8-2. 주요 메트릭 쿼리 테스트

```bash
# 성능 테스트 기간의 CPU 메트릭 존재 확인
curl -s "http://localhost:9091/api/v1/query?query=node_cpu_seconds_total" | \
  jq '.data.result | length'
# 결과가 0이 아니어야 함

# 특정 시간 범위 데이터 확인
START="2026-04-10T09:00:00Z"
END="2026-04-10T18:00:00Z"
curl -s "http://localhost:9091/api/v1/query_range?query=up&start=${START}&end=${END}&step=60s" | \
  jq '.data.result | length'
```

### 8-3. PRD vs STG 데이터 일치 검증

동일 쿼리를 PRD Prometheus와 STG 복원 Prometheus에서 실행하여 결과를 비교합니다.

```bash
# 검증 쿼리 예시 (성능 테스트 기간 내 특정 시점)
QUERY="sum(rate(container_cpu_usage_seconds_total[5m]))"
TIME="2026-04-10T12:00:00Z"

# PRD
PRD_RESULT=$(curl -s "http://localhost:9090/api/v1/query?query=${QUERY}&time=${TIME}" | \
  jq -r '.data.result[0].value[1]')

# STG (복원)
STG_RESULT=$(curl -s "http://localhost:9091/api/v1/query?query=${QUERY}&time=${TIME}" | \
  jq -r '.data.result[0].value[1]')

echo "PRD: ${PRD_RESULT}"
echo "STG: ${STG_RESULT}"
# 두 값이 동일해야 함
```

### 8-4. Grafana 스냅샷 검증

| 확인 항목 | 방법 | 기대 결과 |
|-----------|------|-----------|
| 스냅샷 URL 접근 | 브라우저에서 스냅샷 URL 열기 | 대시보드 패널 정상 렌더링 |
| 시간 범위 | 스냅샷 상단 시간 표시 확인 | 테스트 수행 기간과 일치 |
| 패널 데이터 | 각 패널에 데이터 존재 확인 | "No data" 없음 |
| STG import 스냅샷 | STG Grafana에서 스냅샷 열기 | PRD 스냅샷과 동일 내용 |

### 8-5. STG Grafana 대시보드 검증

- [ ] DataSource `Prometheus-PerfTest-Review` 연결 상태: **Data source is working**
- [ ] 대시보드에서 시간 범위를 테스트 기간으로 설정 시 데이터 정상 표시
- [ ] 각 패널 쿼리가 정상 실행 (에러 패널 없음)
- [ ] 기존 STG Prometheus DataSource와 독립적으로 동작 확인
- [ ] 새로운 PromQL 쿼리로 자유롭게 재분석 가능 확인

---

## 9. 정리 및 주의사항

### 9-1. 보관 정책

| 대상 | 보관 위치 | 보관 기간 | 비고 |
|------|-----------|-----------|------|
| Grafana 스냅샷 | Grafana DB (PRD/STG) | 영구 (수동 삭제 전까지) | 용량 부담 적음 |
| TSDB 스냅샷 압축파일 | S3 / NFS | 6개월 ~ 1년 권장 | 용량 큰 경우 lifecycle 정책 적용 |
| STG 복원 Prometheus | STG 클러스터 PVC | 분석 완료 후 삭제 | 상시 운영 불필요 |

### 9-2. 분석 완료 후 STG 리소스 정리

```bash
# 복원용 Prometheus 삭제
kubectl delete -f prom-restore-deployment.yaml -n monitoring

# PVC 삭제
kubectl delete pvc prom-perf-test-data -n monitoring

# Grafana DataSource 삭제 (선택)
DS_ID=$(curl -s -u admin:<PASSWORD> \
  "http://<STG_GRAFANA>:3000/api/datasources/name/Prometheus-PerfTest-Review" | jq '.id')
curl -s -X DELETE -u admin:<PASSWORD> \
  "http://<STG_GRAFANA>:3000/api/datasources/${DS_ID}"
```

### 9-3. 주의사항

- **TSDB 버전 호환:** 복원 Prometheus 버전은 스냅샷 생성 시 PRD Prometheus 버전과 동일하거나 상위 버전이어야 합니다. 하위 버전에서는 블록 포맷을 읽지 못할 수 있습니다.
- **External Labels:** PRD Prometheus에 `external_labels`가 설정되어 있다면, 복원 인스턴스에서도 동일하게 설정해야 쿼리 시 label 필터가 일치합니다.
- **읽기 전용 운영:** 복원 Prometheus는 `--storage.tsdb.no-lockfile` 플래그를 사용하여 새 데이터 수집 없이 안전하게 운영합니다. 스크랩 설정을 비워두면 신규 데이터가 쌓이지 않습니다.
- **시간대:** Prometheus는 UTC 기준으로 데이터를 저장합니다. Grafana에서 조회 시 대시보드 timezone 설정을 확인하세요.

---

## 10. 트러블슈팅

### 복원 Prometheus 시작 시 "lock file exists" 오류

`--storage.tsdb.no-lockfile` 플래그가 누락되었거나, 기존 lock 파일이 스냅샷에 포함된 경우입니다.

```bash
# lock 파일 수동 삭제
kubectl exec -n monitoring <RESTORE_POD> -- rm -f /prometheus/lock

# 또는 Deployment args에 플래그 추가 확인
args:
  - "--storage.tsdb.no-lockfile"
```

### 복원 후 "No data" 표시

- Grafana 시간 범위가 스냅샷 데이터 범위와 일치하는지 확인합니다.
- TSDB status API로 실제 데이터 시간 범위를 조회합니다:

```bash
curl -s http://localhost:9091/api/v1/status/tsdb | jq '.data'
```

- DataSource URL이 복원 Prometheus 서비스 주소와 일치하는지 확인합니다.

### kubectl cp 시 "tar: Removing leading / from member names" 경고

정상 동작이며 무시해도 됩니다. 절대 경로가 상대 경로로 변환되는 것일 뿐 데이터에 영향 없습니다.

### TSDB 스냅샷 크기가 너무 클 때

특정 기간만 필요하다면 `promtool`로 시간 범위를 지정하여 추출할 수 있습니다.

```bash
# promtool이 포함된 Pod에서 실행
START=$(date -d "2026-04-10 09:00:00" +%s)000
END=$(date -d "2026-04-10 18:00:00" +%s)000

promtool tsdb create-blocks-from openmetrics \
  --min-time=${START} \
  --max-time=${END} \
  /prometheus/snapshots/${SNAP_NAME} \
  /tmp/filtered-snapshot
```

### Prometheus 버전 불일치로 블록 로딩 실패

PRD Prometheus 버전을 확인하고 동일 버전의 이미지를 사용합니다.

```bash
# PRD 버전 확인
curl -s http://localhost:9090/api/v1/status/buildinfo | jq '.data.version'

# 복원 Deployment 이미지 태그를 동일하게 설정
image: prom/prometheus:v<동일_버전>
```
