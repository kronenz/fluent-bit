# Section 8: 모니터링 모듈 Hot/Cold 데이터 관리 구성 확인

## 개요

본 섹션은 모니터링 클러스터의 데이터 생명주기 관리 구성을 확인하고 검증하는 절차를 기술한다.
OpenSearch의 Hot/Cold 아키텍처, ISM(Index State Management) 정책, Prometheus TSDB 보존 설정,
Grafana 백업 구성을 포함하며 운영 환경에서의 정기 점검 기준을 제시한다.

---

## 8.1 데이터 보존 정책 전체 요약

### 8.1.1 시스템별 보존 정책 현황

| 시스템 | 데이터 유형 | Hot 보존 | Warm 보존 | Cold 보존 | 삭제 정책 | 저장소 위치 |
|--------|------------|---------|-----------|----------|-----------|------------|
| OpenSearch | Container 로그 | 7일 | 30일 | 90일 | 90일 초과 삭제 | NVMe Local PV (Hot/Cold 노드) |
| OpenSearch | K8s Events | 7일 | 30일 | - | 30일 초과 삭제 | NVMe Local PV (Hot 노드) |
| OpenSearch | Systemd 로그 | 7일 | 14일 | 60일 | 60일 초과 삭제 | NVMe Local PV (Hot/Cold 노드) |
| Prometheus | Metrics (TSDB) | 15~30일 | - (단일 구성) | - | retention 설정 기반 자동 삭제 | NVMe Local PV |
| Grafana | Dashboard JSON | GitOps 관리 | - | - | 버전 관리 (Bitbucket) | monitoring-helm-values 레포 |
| Grafana | grafana.db | Local PV 상시 보존 | - | - | 수동 정리 | NVMe Local PV + 주간 백업 |

### 8.1.2 ISM 정책 전환 흐름 요약

```
[Container 로그]
  hot (7d) → warm (30d) → cold (90d) → delete

[K8s Events]
  hot (7d) → warm (30d) → delete

[Systemd 로그]
  hot (7d) → warm (14d) → cold (60d) → delete

[Prometheus TSDB]
  tsdb write (15d~30d) → auto-eviction (retention.time or retention.size 초과 시)
```

---

## 8.2 OpenSearch Hot/Cold 구성

### 8.2.1 노드 역할 구성

| 역할 | Pod 명 | NVMe 경로 | 할당 용량 | rack.awareness | 비고 |
|------|--------|-----------|----------|----------------|------|
| Master | opensearch-master-0 | - | 32Gi (heap) | zone-a | 투표/메타데이터 전용 |
| Master | opensearch-master-1 | - | 32Gi (heap) | zone-b | 투표/메타데이터 전용 |
| Master | opensearch-master-2 | - | 32Gi (heap) | zone-c | 투표/메타데이터 전용 |
| Hot Data | opensearch-data-hot-0 | /mnt/nvme/opensearch/hot | 1.2TB | zone-a | 고 IOPS NVMe, 인덱싱 담당 |
| Hot Data | opensearch-data-hot-1 | /mnt/nvme/opensearch/hot | 1.2TB | zone-b | 고 IOPS NVMe, 인덱싱 담당 |
| Hot Data | opensearch-data-hot-2 | /mnt/nvme/opensearch/hot | 1.2TB | zone-c | 고 IOPS NVMe, 인덱싱 담당 |
| Cold Data | opensearch-data-cold-0 | /mnt/nvme/opensearch/cold | 600GB | zone-a | Bulk storage, 조회 전용 |
| Cold Data | opensearch-data-cold-1 | /mnt/nvme/opensearch/cold | 600GB | zone-b | Bulk storage, 조회 전용 |

> **allocation awareness 설정**: `cluster.routing.allocation.awareness.attributes: rack` 으로 구성되어 있으며, Hot 노드와 Cold 노드는 `node.attr.temp` 속성으로 구분된다.

### 8.2.2 노드 속성 설정 확인

**Hot 노드 opensearch.yml 주요 설정:**

```yaml
node.roles: [ data_hot, data_content ]
node.attr.temp: hot
node.attr.rack: zone-a   # 각 노드별 상이
```

**Cold 노드 opensearch.yml 주요 설정:**

```yaml
node.roles: [ data_cold ]
node.attr.temp: cold
node.attr.rack: zone-a   # 각 노드별 상이
```

### 8.2.3 ISM Policy 상세 구성

| 정책명 | 상태명 | 전이 조건 | 액션 | 대상 인덱스 패턴 |
|--------|--------|----------|------|----------------|
| container-logs-policy | hot | min_index_age: 7d | force_merge, index_priority(100) | container-logs-* |
| container-logs-policy | warm | min_index_age: 30d | allocation(temp=cold), index_priority(50) | container-logs-* |
| container-logs-policy | cold | min_index_age: 90d | read_only | container-logs-* |
| container-logs-policy | delete | 즉시 | delete | container-logs-* |
| k8s-events-policy | hot | min_index_age: 7d | force_merge, index_priority(100) | k8s-events-* |
| k8s-events-policy | warm | min_index_age: 30d | - | k8s-events-* |
| k8s-events-policy | delete | 즉시 | delete | k8s-events-* |
| systemd-logs-policy | hot | min_index_age: 7d | force_merge, index_priority(100) | systemd-logs-* |
| systemd-logs-policy | warm | min_index_age: 14d | allocation(temp=cold), index_priority(50) | systemd-logs-* |
| systemd-logs-policy | cold | min_index_age: 60d | read_only | systemd-logs-* |
| systemd-logs-policy | delete | 즉시 | delete | systemd-logs-* |

> **min_size 조건**: 인덱스 크기가 50GB를 초과하는 경우 min_index_age 조건에 관계없이 warm 전환이 조기 트리거될 수 있도록 OR 조건으로 구성한다.

### 8.2.4 ISM Policy JSON 예시 (container-logs-policy)

```json
{
  "policy": {
    "description": "Container logs lifecycle: hot 7d, warm 30d, cold 90d, delete",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          { "index_priority": { "priority": 100 } }
        ],
        "transitions": [
          {
            "state_name": "warm",
            "conditions": {
              "min_index_age": "7d"
            }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "allocation": {
              "require": { "temp": "cold" }
            }
          },
          { "index_priority": { "priority": 50 } },
          { "force_merge": { "max_num_segments": 1 } }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": {
              "min_index_age": "30d"
            }
          }
        ]
      },
      {
        "name": "cold",
        "actions": [
          { "read_only": {} }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "90d"
            }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          { "delete": {} }
        ],
        "transitions": []
      }
    ],
    "ism_template": [
      {
        "index_patterns": ["container-logs-*"],
        "priority": 100
      }
    ]
  }
}
```

### 8.2.5 Hot → Cold 이전 동작 확인 절차

**사전 준비:**

```bash
# OpenSearch 접속 정보 확인
OPENSEARCH_HOST="https://opensearch.monitoring.svc.cluster.local:9200"
OPENSEARCH_USER="admin"
OPENSEARCH_PASS="<password>"

# 이하 명령어는 모니터링 네임스페이스 내 임시 Pod 또는 포트포워드를 통해 실행
kubectl port-forward -n monitoring svc/opensearch 9200:9200 &
```

**Step 1: ISM Policy 적용 상태 확인**

```bash
# 특정 인덱스의 ISM 상태 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_plugins/_ism/explain/container-logs-2025.01.01" \
  | jq '.index_details'
```

예상 응답:

```json
{
  "container-logs-2025.01.01": {
    "index.plugins.index_state_management.policy_id": "container-logs-policy",
    "index.plugins.index_state_management.state.name": "warm",
    "index.plugins.index_state_management.action.name": "allocation",
    "index.plugins.index_state_management.step.name": "attempt_call_api"
  }
}
```

**Step 2: Allocation Awareness 설정 확인**

```bash
# 인덱스 샤드 할당 정보 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_cat/shards/container-logs-2025.01.01?v&h=index,shard,prirep,state,node,store" \
  | column -t

# Cold 노드로 이전 중인 샤드 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_cat/recovery/container-logs-2025.01.01?v&active_only=true"
```

**Step 3: 샤드 재배치 완료 확인**

```bash
# 클러스터 전체 샤드 재배치 상태 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_cluster/health?pretty" \
  | jq '{status, relocating_shards, initializing_shards, unassigned_shards}'

# Cold 노드의 인덱스 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_cat/indices?v&h=index,health,status,pri,rep,store.size,creation.date.string" \
  | grep "container-logs"
```

**Step 4: 노드별 디스크 사용량 확인**

```bash
# 노드별 디스크 사용량 및 역할 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_cat/nodes?v&h=name,node.role,disk.used,disk.avail,disk.used_percent" \
  | column -t
```

**Step 5: 특정 날짜 범위 인덱스 전체 상태 점검**

```bash
# 최근 90일 container-logs 인덱스 ISM 상태 일괄 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_plugins/_ism/explain/container-logs-*" \
  | jq '[to_entries[] | {index: .key, state: .value["index.plugins.index_state_management.state.name"]}]'
```

### 8.2.6 스냅샷 저장소 (MinIO) 연동 구성 확인

**저장소 등록 확인:**

```bash
# 등록된 스냅샷 저장소 목록 조회
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_snapshot?pretty"
```

**저장소 신규 등록 (MinIO):**

```bash
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X PUT "${OPENSEARCH_HOST}/_snapshot/minio-backup" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots",
      "endpoint": "http://minio.minio.svc.cluster.local:9000",
      "path_style_access": true,
      "access_key": "<MINIO_ACCESS_KEY>",
      "secret_key": "<MINIO_SECRET_KEY>"
    }
  }'
```

**스냅샷 수동 생성:**

```bash
# 스냅샷 생성 (비동기)
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X PUT "${OPENSEARCH_HOST}/_snapshot/minio-backup/snapshot-$(date +%Y%m%d)?wait_for_completion=false" \
  -H "Content-Type: application/json" \
  -d '{
    "indices": "container-logs-*,k8s-events-*,systemd-logs-*",
    "ignore_unavailable": true,
    "include_global_state": false
  }'

# 스냅샷 생성 진행 상태 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_snapshot/minio-backup/snapshot-$(date +%Y%m%d)?pretty" \
  | jq '.snapshots[0] | {state, start_time, end_time, indices: (.indices | length)}'
```

**SM (Snapshot Management) 정책 확인:**

```bash
# SM 정책 목록 조회
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_plugins/_sm/policies?pretty"

# SM 정책 상세 조회
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_plugins/_sm/policies/daily-snapshot?pretty" \
  | jq '.policy | {name, description, creation: .creation.schedule, deletion: .deletion}'
```

**SM 정책 등록 예시:**

```json
{
  "description": "Daily snapshot policy for monitoring indices",
  "creation": {
    "schedule": {
      "cron": {
        "expression": "0 2 * * *",
        "timezone": "Asia/Seoul"
      }
    },
    "time_limit": "1h"
  },
  "deletion": {
    "schedule": {
      "cron": {
        "expression": "0 3 * * *",
        "timezone": "Asia/Seoul"
      }
    },
    "condition": {
      "max_count": 30,
      "max_age": "30d"
    },
    "time_limit": "1h"
  },
  "snapshot_config": {
    "repository": "minio-backup",
    "indices": "container-logs-*,k8s-events-*,systemd-logs-*",
    "ignore_unavailable": true,
    "include_global_state": false
  }
}
```

### 8.2.7 인덱스 삭제 정책 동작 확인

**ISM delete 액션 검증:**

```bash
# 삭제 대상 인덱스 (90일 초과 container-logs) 조회
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_plugins/_ism/explain/container-logs-*" \
  | jq '[to_entries[] | select(.value["index.plugins.index_state_management.state.name"] == "delete") | .key]'

# ISM 실행 이력 확인 (최근 10건)
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_plugins/_ism/history/indexes?pretty&size=10" \
  | jq '.history[] | select(.action_name == "delete") | {index, timestamp, message}'
```

**디스크 Watermark 모니터링:**

```bash
# 클러스터 설정에서 Watermark 임계값 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_cluster/settings?include_defaults=true&pretty" \
  | jq '.defaults.cluster.routing.allocation.disk'

# 노드별 디스크 사용률 및 Watermark 초과 여부 확인
curl -s -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -X GET "${OPENSEARCH_HOST}/_cat/allocation?v&h=node,disk.used,disk.avail,disk.percent,shards" \
  | column -t
```

> **권고사항**: 디스크 사용률 80% 이상 시 Low watermark 알람 발생. 90% 이상 시 신규 샤드 할당 중단. ISM 삭제 정책이 정상 동작하는지 주기적으로 확인 필요.

---

## 8.3 Prometheus 데이터 보존 구성

### 8.3.1 Local PV 기반 TSDB 보존 설정

| 설정 항목 | 설정값 | 설명 | NVMe 경로 | 현재 사용량 확인 방법 |
|----------|--------|------|-----------|---------------------|
| `--storage.tsdb.retention.time` | 15d (기본) / 30d (권장) | 보존 기간 초과 시 자동 삭제 | `/mnt/nvme/prometheus/data` | `df -h /mnt/nvme/prometheus/data` |
| `--storage.tsdb.retention.size` | 500GB | 용량 초과 시 오래된 블록 삭제 | `/mnt/nvme/prometheus/data` | `du -sh /mnt/nvme/prometheus/data` |
| `--storage.tsdb.wal-compression` | true | WAL 압축으로 I/O 절감 | `/mnt/nvme/prometheus/data/wal` | - |
| `--storage.tsdb.min-block-duration` | 2h | 최소 블록 생성 주기 | - | - |
| `--storage.tsdb.max-block-duration` | 24h | 최대 블록 압축 주기 | - | - |

**Prometheus values.yaml 설정 예시:**

```yaml
prometheus:
  prometheusSpec:
    retention: "30d"
    retentionSize: "500GB"
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-nvme
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 600Gi
    additionalArgs:
      - name: storage.tsdb.wal-compression
        value: "true"
      - name: storage.tsdb.min-block-duration
        value: "2h"
      - name: storage.tsdb.max-block-duration
        value: "24h"
```

**현재 TSDB 사용량 확인:**

```bash
# Prometheus Pod 내부에서 TSDB 상태 확인
kubectl exec -n monitoring prometheus-kube-prometheus-prometheus-0 -- \
  promtool tsdb analyze /prometheus

# Prometheus API를 통한 TSDB 상태 조회
curl -s http://localhost:9090/api/v1/status/tsdb | jq '.data | {
  headStats: .headStats,
  chunkCount: .headStats.chunkCount,
  numSeries: .headStats.numSeries,
  minTime: (.headStats.minTime / 1000 | todate),
  maxTime: (.headStats.maxTime / 1000 | todate)
}'
```

### 8.3.2 단일 구성 제약 및 권고사항

| 제약 항목 | 현재 상태 | 위험도 | 권고사항 |
|----------|----------|--------|---------|
| HA 미구성 | 단일 Prometheus 인스턴스 | 높음 | Pod 재시작 시 scrape 데이터 일시 유실 가능. PodDisruptionBudget 설정 필수 |
| Remote Write 미구성 | Local PV 단독 저장 | 중간 | 향후 Thanos/Cortex 연동을 통한 장기 보존 및 HA 확장 검토 |
| WAL 보호 미비 | 기본 설정 | 낮음 | WAL 디렉토리를 별도 PV로 분리하거나 정기 스냅샷 수행 권장 |
| 메트릭 카디널리티 | 모니터링 필요 | 중간 | 500K series 초과 시 메모리 증가 급격. 불필요한 label 제거 |

**WAL 복구 절차:**

```bash
# Prometheus Pod 비정상 종료 후 WAL 손상 여부 확인
kubectl exec -n monitoring prometheus-kube-prometheus-prometheus-0 -- \
  promtool tsdb analyze /prometheus 2>&1 | grep -i "error\|corrupt"

# WAL 복구 (손상된 경우)
kubectl exec -n monitoring prometheus-kube-prometheus-prometheus-0 -- \
  promtool tsdb create-blocks-from rules \
    --output-dir /prometheus/wal-repair \
    /prometheus/wal

# 복구 불가 시 WAL 제거 후 재수집 (데이터 손실 감수)
kubectl scale -n monitoring statefulset prometheus-kube-prometheus-prometheus --replicas=0
# WAL 디렉토리 백업 후 제거
kubectl scale -n monitoring statefulset prometheus-kube-prometheus-prometheus --replicas=1
```

### 8.3.3 Prometheus 스냅샷 수동 백업 절차

**Step 1: Admin API 활성화 확인**

```yaml
# kube-prometheus-stack values.yaml에서 admin API 활성화 확인
prometheus:
  prometheusSpec:
    enableAdminAPI: true
```

**Step 2: 스냅샷 생성**

```bash
# Prometheus 스냅샷 생성 (Admin API 필요)
curl -s -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot \
  | jq '.data.name'
# 예: "20250101T020000Z-abc123"

# 포트포워드를 통한 외부 접근
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &
curl -s -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot
```

**Step 3: 스냅샷 복사**

```bash
SNAPSHOT_NAME="20250101T020000Z-abc123"

# Pod 내부 스냅샷 경로 확인
kubectl exec -n monitoring prometheus-kube-prometheus-prometheus-0 -- \
  ls /prometheus/snapshots/

# 스냅샷을 로컬로 복사
kubectl cp monitoring/prometheus-kube-prometheus-prometheus-0:/prometheus/snapshots/${SNAPSHOT_NAME} \
  /backup/prometheus/${SNAPSHOT_NAME}

# 복사된 스냅샷 크기 확인
du -sh /backup/prometheus/${SNAPSHOT_NAME}
```

**Step 4: 스냅샷 정합성 검증**

```bash
# promtool을 사용한 스냅샷 검증
promtool tsdb analyze /backup/prometheus/${SNAPSHOT_NAME}
```

---

## 8.4 Grafana 백업 구성

### 8.4.1 백업 대상 목록

| 백업 대상 | 백업 방법 | 주기 | 저장 위치 | 담당자 | 비고 |
|----------|----------|------|----------|--------|------|
| Dashboard JSON | Bitbucket GitOps 자동 동기화 | 변경 즉시 (ArgoCD) | monitoring-helm-values 레포 | 개발팀 | Grafana provisioning 디렉토리 연동 |
| Datasource 설정 | values.yaml 관리 | ArgoCD sync 시 적용 | monitoring-helm-values 레포 | 운영팀 | Prometheus, OpenSearch 연결 정보 포함 |
| PrometheusRule CR | Kustomize GitOps | ArgoCD sync 시 적용 | monitoring-kustomize 레포 | 운영팀 | 알람 규칙 전체 포함 |
| AlertManager 설정 | values.yaml / Secret 관리 | ArgoCD sync 시 적용 | monitoring-helm-values 레포 | 운영팀 | Slack/PagerDuty 웹훅 포함 |
| grafana.db | kubectl cp + Local PV 스냅샷 | 주 1회 (매주 일요일 02:00) | NAS 백업 스토리지 / S3 | 운영팀 | 사용자 설정, 어노테이션, API 키 포함 |

### 8.4.2 자동 백업 절차 (Provisioning → Bitbucket 동기화)

**Grafana Dashboard Provisioning 구성 (values.yaml):**

```yaml
grafana:
  dashboardProviders:
    dashboardproviders.yaml:
      apiVersion: 1
      providers:
        - name: 'gitops-dashboards'
          orgId: 1
          folder: 'GitOps'
          type: file
          disableDeletion: true
          editable: false
          options:
            path: /var/lib/grafana/dashboards/gitops

  dashboardsConfigMaps:
    gitops: "grafana-dashboards-configmap"

  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        - name: Prometheus
          type: prometheus
          url: http://prometheus-operated.monitoring.svc.cluster.local:9090
          isDefault: true
        - name: OpenSearch
          type: grafana-opensearch-datasource
          url: https://opensearch.monitoring.svc.cluster.local:9200
          jsonData:
            timeField: "@timestamp"
```

**Bitbucket 동기화 확인:**

```bash
# ArgoCD에서 Grafana 앱 동기화 상태 확인
argocd app get monitoring-grafana

# 대시보드 ConfigMap 확인
kubectl get configmap -n monitoring grafana-dashboards-configmap -o yaml \
  | grep "dashboard_count\|last_sync"
```

### 8.4.3 수동 백업 명령어

**grafana.db 수동 백업 (kubectl cp):**

```bash
# Grafana Pod 이름 확인
GRAFANA_POD=$(kubectl get pod -n monitoring -l app.kubernetes.io/name=grafana -o jsonpath='{.items[0].metadata.name}')

# grafana.db 백업
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
kubectl cp monitoring/${GRAFANA_POD}:/var/lib/grafana/grafana.db \
  /backup/grafana/grafana.db.${BACKUP_DATE}

# 백업 파일 무결성 확인
sqlite3 /backup/grafana/grafana.db.${BACKUP_DATE} "SELECT COUNT(*) FROM dashboard;"
```

**grafana-backup-tool을 사용한 대시보드 내보내기:**

```bash
# grafana-backup-tool 설치 (임시 Pod 사용 권장)
pip install grafana-backup

# 환경 변수 설정
export GRAFANA_URL="http://localhost:3000"
export GRAFANA_TOKEN="<Service Account Token>"

# 대시보드 전체 내보내기
grafana-backup save \
  --destination /backup/grafana/dashboards-${BACKUP_DATE}

# 알림 채널 내보내기
grafana-backup save \
  --components alert-channels \
  --destination /backup/grafana/alert-channels-${BACKUP_DATE}
```

**Grafana API를 통한 대시보드 목록 확인:**

```bash
# 포트포워드
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 &

# 대시보드 목록 조회
curl -s -u admin:<password> http://localhost:3000/api/search?type=dash-db \
  | jq '[.[] | {uid, title, folderTitle}]'

# 특정 대시보드 JSON 내보내기
DASHBOARD_UID="<uid>"
curl -s -u admin:<password> \
  http://localhost:3000/api/dashboards/uid/${DASHBOARD_UID} \
  | jq '.dashboard' > /backup/grafana/dashboard-${DASHBOARD_UID}.json
```

### 8.4.4 복구 절차

| 복구 대상 | 복구 방법 | 예상 소요 시간 | 검증 방법 |
|----------|----------|---------------|---------|
| Dashboard JSON | ArgoCD 앱 Sync → Grafana 재시작 | 5분 이내 | Grafana UI에서 대시보드 목록 확인 |
| Datasource 설정 | values.yaml 업데이트 → Helm upgrade | 3분 이내 | Grafana → Connections → Data sources 확인 |
| PrometheusRule CR | `kubectl apply -k monitoring-kustomize/` | 2분 이내 | `kubectl get prometheusrule -n monitoring` 확인 |
| AlertManager 설정 | values.yaml 업데이트 → Helm upgrade | 5분 이내 | Alertmanager UI → Status 확인 |
| grafana.db | kubectl cp 역방향 복원 → Pod 재시작 | 10분 이내 | 사용자 계정, 어노테이션 복원 여부 확인 |
| 전체 Grafana 재설치 | ArgoCD 앱 삭제 후 재배포 | 20분 이내 | 대시보드, 알람, 데이터소스 전체 확인 |

**grafana.db 복구 절차:**

```bash
# Grafana Pod 중지
kubectl scale -n monitoring deployment monitoring-grafana --replicas=0

# 백업 파일 복원
RESTORE_FILE="/backup/grafana/grafana.db.20250101_020000"
kubectl cp ${RESTORE_FILE} \
  monitoring/${GRAFANA_POD}:/var/lib/grafana/grafana.db

# Grafana 재기동
kubectl scale -n monitoring deployment monitoring-grafana --replicas=1

# 기동 확인
kubectl rollout status -n monitoring deployment/monitoring-grafana
```

---

## 8.5 Hot/Cold 점검 체크리스트

| 점검 항목 | 점검 주기 | 확인 방법 | 최종 점검일 | 담당자 | 비고 |
|----------|----------|----------|------------|--------|------|
| ISM Policy 적용 상태 | 주 1회 (월요일) | `GET /_plugins/_ism/explain/<index>` | - | 운영팀 | 모든 정책 대상 인덱스 패턴 일괄 확인 |
| Hot → Cold 이전 동작 | 주 1회 (월요일) | `GET /_cat/shards?h=index,node,state` + 노드 속성 확인 | - | 운영팀 | 이전 중 샤드 relocating 상태 확인 |
| 스냅샷 생성 상태 | 매일 | `GET /_snapshot/minio-backup/_all` | - | 운영팀 | 전일 스냅샷 SUCCESS 여부 확인 |
| Prometheus 디스크 사용률 | 매일 | Grafana → Node Exporter 대시보드 / `df -h` | - | 운영팀 | 80% 초과 시 즉시 보고 |
| Grafana 백업 상태 | 주 1회 (월요일) | 백업 스토리지 파일 존재 여부 확인 | - | 운영팀 | grafana.db 백업 파일 날짜 및 크기 확인 |
| 인덱스 삭제 동작 | 주 1회 (월요일) | ISM history 조회 + 인덱스 목록 날짜 확인 | - | 운영팀 | 90일 초과 인덱스 잔존 여부 확인 |
| OpenSearch 디스크 Watermark | 매일 | `GET /_cat/allocation?v` | - | 운영팀 | Low(80%) / High(90%) 초과 여부 확인 |
| Cold 노드 샤드 배포 | 주 1회 | `GET /_cat/nodes?v` + Cold 노드 샤드 수 확인 | - | 운영팀 | Cold 노드에 warm/cold 인덱스만 배치되어 있는지 확인 |
| ISM 오류 인덱스 확인 | 주 1회 | `GET /_plugins/_ism/explain/*?show_policy_query_results=false` | - | 운영팀 | failed 상태 인덱스에 대한 재시도 또는 수동 처리 |
| SM 정책 실행 이력 | 주 1회 | `GET /_plugins/_sm/policies/<name>/explain` | - | 운영팀 | 스냅샷 생성/삭제 정책 정상 실행 여부 |

---

## 참고사항

- ISM 정책 변경 시 기존 인덱스에 즉시 적용되지 않으므로 `POST /_plugins/_ism/change_policy/<index>` 를 통해 수동 적용이 필요하다.
- Hot → Cold 이전은 ISM이 allocation requirement를 설정한 후 OpenSearch 클러스터가 비동기로 샤드를 재배치하므로, 대용량 인덱스의 경우 완료까지 수 시간 소요될 수 있다.
- Prometheus 단일 구성에서 Pod 재시작 시 scrape 주기(기본 15초) 동안 데이터 수집이 중단되나, TSDB 데이터 자체는 보존된다.
- grafana.db에는 사용자 어노테이션, API 키, 플러그인 설정이 포함되므로 GitOps만으로는 완전한 복원이 불가하다. 정기적인 grafana.db 백업이 필수이다.
