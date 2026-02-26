# OpenSearch 스냅샷 적용 가이드

## 1. 개요

스냅샷은 OpenSearch 인덱스의 백업으로, 데이터 손실 방지, 클러스터 마이그레이션, 재해 복구(DR)를 위해 사용됩니다. 본 가이드에서는 로컬 파일시스템과 S3(MinIO 포함) 기반 스냅샷 설정 및 운영 방법을 다룹니다.

### 스냅샷 유형

| 유형 | 설명 | 용도 |
|------|------|------|
| **수동 스냅샷** | API 호출로 직접 생성 | 배포 전 백업, 임시 백업 |
| **SM 정책 자동 스냅샷** | Cron 스케줄로 자동 생성/삭제 | 일상 백업 운영 |
| **ISM 연동 스냅샷** | ISM 정책 내 snapshot 액션 | Cold tier S3 전환 |

### 스냅샷 특성

- **증분 백업:** 이전 스냅샷과 비교하여 변경된 세그먼트만 저장 (빠르고 효율적)
- **논블로킹:** 스냅샷 중에도 읽기/쓰기 가능
- **원자적:** 스냅샷은 성공 또는 실패 (부분 상태 없음)
- **클러스터 간 복원:** 다른 클러스터로 복원 가능 (버전 호환 범위 내)

## 2. 스냅샷 리포지토리 설정

### 2-1. 로컬 파일시스템 리포지토리

#### 사전 설정

`opensearch.yml`에 스냅샷 저장 경로를 등록합니다.

```yaml
# opensearch.yml (모든 노드)
path.repo: ["/mnt/opensearch-backup"]
```

Kubernetes 환경에서는 PV/PVC를 마운트합니다.

```yaml
# OpenSearch Helm values.yaml에 추가
extraVolumes:
  - name: snapshot-storage
    persistentVolumeClaim:
      claimName: opensearch-snapshot-pvc

extraVolumeMounts:
  - name: snapshot-storage
    mountPath: /mnt/opensearch-backup
```

PersistentVolume 예시:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opensearch-snapshot-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteMany         # NFS 등 공유 스토리지 필요
  persistentVolumeReclaimPolicy: Retain
  storageClassName: nfs
  nfs:
    server: nfs-server.example.com
    path: /exports/opensearch-backup
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: opensearch-snapshot-pvc
  namespace: logging
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs
  resources:
    requests:
      storage: 100Gi
```

> **주의:** 멀티 노드 클러스터에서는 모든 노드가 같은 경로에 접근할 수 있어야 합니다 (NFS, EFS, GlusterFS 등 공유 스토리지 필수).

#### 리포지토리 등록

```bash
curl -X PUT "http://opensearch:9200/_snapshot/local-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "fs",
    "settings": {
      "location": "/mnt/opensearch-backup/snapshots",
      "compress": true,
      "max_snapshot_bytes_per_sec": "200mb",
      "max_restore_bytes_per_sec": "200mb"
    }
  }'
```

### 2-2. AWS S3 리포지토리

```bash
# 1. 자격증명 등록 (모든 노드)
opensearch-keystore add s3.client.default.access_key
opensearch-keystore add s3.client.default.secret_key

# 2. 자격증명 리로드
curl -X POST "http://opensearch:9200/_nodes/reload_secure_settings"

# 3. 리포지토리 등록
curl -X PUT "http://opensearch:9200/_snapshot/s3-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots-prod",
      "base_path": "cluster-bigdata-prod",
      "region": "ap-northeast-2",
      "server_side_encryption": true,
      "storage_class": "standard_ia",
      "max_snapshot_bytes_per_sec": "200mb",
      "max_restore_bytes_per_sec": "200mb"
    }
  }'
```

#### S3 설정 옵션

| 설정 | 설명 | 기본값 |
|------|------|--------|
| `bucket` | S3 버킷 이름 | (필수) |
| `base_path` | 버킷 내 스냅샷 저장 경로 | 루트 |
| `region` | AWS 리전 | (필수) |
| `server_side_encryption` | 서버 측 암호화 (SSE-S3) | false |
| `storage_class` | 스토리지 클래스 | standard |
| `max_snapshot_bytes_per_sec` | 스냅샷 생성 속도 제한 | 40mb |
| `max_restore_bytes_per_sec` | 복원 속도 제한 | 40mb |
| `canned_acl` | S3 ACL | private |
| `buffer_size` | 멀티파트 업로드 버퍼 크기 | 100mb |

#### S3 Storage Class 선택

| Storage Class | 비용 | 최소 보관 | 용도 |
|--------------|------|----------|------|
| `standard` | $$$ | 없음 | 자주 복원하는 스냅샷 |
| `standard_ia` | $$ | 30일 | 일반적인 백업 (권장) |
| `onezone_ia` | $ | 30일 | 단일 AZ 백업 |
| `intelligent_tiering` | $$ | 없음 | 접근 패턴 불확실 시 |
| `glacier_ir` | $ | 90일 | 장기 아카이브 (즉시 복원) |

### 2-3. MinIO 리포지토리

```bash
# 1. opensearch.yml에 MinIO 엔드포인트 설정
# s3.client.default.endpoint: "minio.logging.svc.cluster.local:9000"
# s3.client.default.protocol: http
# s3.client.default.path_style_access: true

# 2. 자격증명 등록
opensearch-keystore add s3.client.default.access_key
opensearch-keystore add s3.client.default.secret_key

# 3. 리포지토리 등록
curl -X PUT "http://opensearch:9200/_snapshot/minio-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots",
      "base_path": "cluster-bigdata-prod",
      "path_style_access": true,
      "compress": true
    }
  }'
```

### 2-4. 복수 리포지토리 (Named Client)

AWS S3와 MinIO를 동시에 사용하는 경우:

```yaml
# opensearch.yml
# AWS S3 클라이언트
s3.client.aws.region: ap-northeast-2

# MinIO 클라이언트
s3.client.minio.endpoint: "minio.logging.svc.cluster.local:9000"
s3.client.minio.protocol: http
s3.client.minio.path_style_access: true
```

```bash
# AWS S3 자격증명
opensearch-keystore add s3.client.aws.access_key
opensearch-keystore add s3.client.aws.secret_key

# MinIO 자격증명
opensearch-keystore add s3.client.minio.access_key
opensearch-keystore add s3.client.minio.secret_key

# AWS S3 리포지토리
curl -X PUT "http://opensearch:9200/_snapshot/aws-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots-aws",
      "base_path": "snapshots",
      "client": "aws"
    }
  }'

# MinIO 리포지토리
curl -X PUT "http://opensearch:9200/_snapshot/minio-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots",
      "base_path": "snapshots",
      "client": "minio",
      "path_style_access": true
    }
  }'
```

### 리포지토리 검증

```bash
# 등록된 리포지토리 목록
curl -s "http://opensearch:9200/_snapshot?pretty"

# 특정 리포지토리 상세
curl -s "http://opensearch:9200/_snapshot/s3-backup?pretty"

# 연결 검증 (모든 노드에서 접근 가능 확인)
curl -X POST "http://opensearch:9200/_snapshot/s3-backup/_verify?pretty"
```

## 3. 수동 스냅샷 관리

### 3-1. 스냅샷 생성

```bash
# 전체 로그 인덱스 스냅샷
curl -X PUT "http://opensearch:9200/_snapshot/s3-backup/snapshot-$(date +%Y%m%d-%H%M%S)?wait_for_completion=false" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "container-logs-*,k8s-events-*,systemd-logs-*",
    "ignore_unavailable": true,
    "include_global_state": false,
    "partial": false
  }'
```

#### 스냅샷 생성 옵션

| 옵션 | 설명 | 권장값 |
|------|------|--------|
| `indices` | 스냅샷 대상 인덱스 패턴 | 와일드카드 사용 |
| `ignore_unavailable` | 없는 인덱스 무시 | true |
| `include_global_state` | 클러스터 설정 포함 여부 | false (로그 백업) |
| `partial` | 일부 샤드 실패 시 계속 진행 | false |
| `wait_for_completion` | 동기/비동기 | false (대용량) |

### 3-2. 스냅샷 상태 확인

```bash
# 진행 중인 스냅샷 상태
curl -s "http://opensearch:9200/_snapshot/s3-backup/snapshot-20260226-120000/_status?pretty"

# 스냅샷 목록 (전체)
curl -s "http://opensearch:9200/_snapshot/s3-backup/_all?pretty"

# 최근 스냅샷만 조회
curl -s "http://opensearch:9200/_snapshot/s3-backup/_all?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for snap in sorted(data.get('snapshots', []), key=lambda x: x.get('start_time', ''), reverse=True)[:10]:
  state = snap['state']
  indices = len(snap['indices'])
  start = snap.get('start_time', 'N/A')
  end = snap.get('end_time', 'in progress')
  duration = snap.get('duration_in_millis', 0)
  print(f\"{snap['snapshot']}: state={state}, indices={indices}, start={start}, duration={duration/1000:.0f}s\")
"
```

### 3-3. 스냅샷 삭제

```bash
# 특정 스냅샷 삭제
curl -X DELETE "http://opensearch:9200/_snapshot/s3-backup/snapshot-20260101-120000"

# 오래된 스냅샷 일괄 삭제 스크립트
#!/bin/bash
REPO="s3-backup"
OPENSEARCH_URL="http://opensearch:9200"
RETENTION_DAYS=30

cutoff_date=$(date -d "${RETENTION_DAYS} days ago" +%Y%m%d)

curl -s "${OPENSEARCH_URL}/_snapshot/${REPO}/_all" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for snap in data.get('snapshots', []):
  name = snap['snapshot']
  # snapshot-YYYYMMDD-HHMMSS 형식에서 날짜 추출
  parts = name.split('-')
  if len(parts) >= 2:
    date_part = parts[1]
    if date_part < '${cutoff_date}':
      print(name)
" | while read snapshot; do
  echo "삭제: ${snapshot}"
  curl -X DELETE "${OPENSEARCH_URL}/_snapshot/${REPO}/${snapshot}"
  echo ""
done
```

> **경고:** S3에서 직접 파일을 삭제하면 리포지토리가 손상됩니다. 반드시 OpenSearch API를 사용하세요.

## 4. Snapshot Management (SM) 자동화 정책

SM 정책을 사용하면 스냅샷 생성과 삭제를 cron 스케줄로 자동화할 수 있습니다.

### 4-1. 로그 유형별 SM 정책

#### Container Log 일일 스냅샷

```bash
curl -X POST "http://opensearch:9200/_plugins/_sm/policies/daily-container-logs-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "Container log 일일 자동 스냅샷 - 30일 보관",
    "creation": {
      "schedule": {
        "cron": {
          "expression": "0 2 * * *",
          "timezone": "Asia/Seoul"
        }
      }
    },
    "deletion": {
      "schedule": {
        "cron": {
          "expression": "0 3 * * *",
          "timezone": "Asia/Seoul"
        }
      },
      "condition": {
        "max_age": "30d",
        "max_count": 30,
        "min_count": 7
      }
    },
    "snapshot_config": {
      "date_format": "yyyy-MM-dd-HH:mm",
      "timezone": "Asia/Seoul",
      "indices": "container-logs-*",
      "repository": "s3-backup",
      "ignore_unavailable": true,
      "include_global_state": false,
      "partial": true
    }
  }'
```

#### K8s Event 일일 스냅샷

```bash
curl -X POST "http://opensearch:9200/_plugins/_sm/policies/daily-k8s-events-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "K8s event log 일일 자동 스냅샷 - 14일 보관",
    "creation": {
      "schedule": {
        "cron": {
          "expression": "0 2 * * *",
          "timezone": "Asia/Seoul"
        }
      }
    },
    "deletion": {
      "schedule": {
        "cron": {
          "expression": "0 3 * * *",
          "timezone": "Asia/Seoul"
        }
      },
      "condition": {
        "max_age": "14d",
        "max_count": 14,
        "min_count": 3
      }
    },
    "snapshot_config": {
      "date_format": "yyyy-MM-dd-HH:mm",
      "timezone": "Asia/Seoul",
      "indices": "k8s-events-*",
      "repository": "s3-backup",
      "ignore_unavailable": true,
      "include_global_state": false,
      "partial": true
    }
  }'
```

#### Systemd Log 일일 스냅샷

```bash
curl -X POST "http://opensearch:9200/_plugins/_sm/policies/daily-systemd-logs-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "description": "Systemd log 일일 자동 스냅샷 - 30일 보관",
    "creation": {
      "schedule": {
        "cron": {
          "expression": "0 2 * * *",
          "timezone": "Asia/Seoul"
        }
      }
    },
    "deletion": {
      "schedule": {
        "cron": {
          "expression": "0 3 * * *",
          "timezone": "Asia/Seoul"
        }
      },
      "condition": {
        "max_age": "30d",
        "max_count": 30,
        "min_count": 7
      }
    },
    "snapshot_config": {
      "date_format": "yyyy-MM-dd-HH:mm",
      "timezone": "Asia/Seoul",
      "indices": "systemd-logs-*",
      "repository": "s3-backup",
      "ignore_unavailable": true,
      "include_global_state": false,
      "partial": true
    }
  }'
```

### 4-2. SM 삭제 조건 설명

| 조건 | 설명 |
|------|------|
| `max_age` | 이 기간보다 오래된 스냅샷 삭제 |
| `max_count` | 최대 스냅샷 수 초과 시 오래된 것부터 삭제 |
| `min_count` | 최소 보관 스냅샷 수 (max_age에 의해 삭제되더라도 유지) |

> **안전장치:** `min_count`를 설정하면 삭제 조건에 해당하더라도 최소 N개의 스냅샷은 유지됩니다.

### 4-3. SM 정책 관리

```bash
# 정책 목록 조회
curl -s "http://opensearch:9200/_plugins/_sm/policies?pretty"

# 특정 정책 상세
curl -s "http://opensearch:9200/_plugins/_sm/policies/daily-container-logs-backup?pretty"

# 실행 상태 확인
curl -s "http://opensearch:9200/_plugins/_sm/policies/daily-container-logs-backup/_explain?pretty"

# 정책 일시 중지
curl -X POST "http://opensearch:9200/_plugins/_sm/policies/daily-container-logs-backup/_stop"

# 정책 재시작
curl -X POST "http://opensearch:9200/_plugins/_sm/policies/daily-container-logs-backup/_start"

# 정책 삭제
curl -X DELETE "http://opensearch:9200/_plugins/_sm/policies/daily-container-logs-backup"
```

## 5. 스냅샷 복원

### 5-1. 전체 인덱스 복원

```bash
# 스냅샷 내 인덱스 목록 확인
curl -s "http://opensearch:9200/_snapshot/s3-backup/daily-container-logs-backup-2026-02-25-02:00-abc123?pretty"

# 전체 복원
curl -X POST "http://opensearch:9200/_snapshot/s3-backup/daily-container-logs-backup-2026-02-25-02:00-abc123/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "*",
    "ignore_unavailable": true,
    "include_global_state": false
  }'
```

### 5-2. 특정 인덱스만 복원

```bash
curl -X POST "http://opensearch:9200/_snapshot/s3-backup/daily-container-logs-backup-2026-02-25-02:00-abc123/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "container-logs-bigdata-prod-2026.02.20",
    "ignore_unavailable": true,
    "include_global_state": false
  }'
```

### 5-3. 이름 변경하여 복원

기존 인덱스와 충돌을 방지하기 위해 접두사를 추가합니다.

```bash
curl -X POST "http://opensearch:9200/_snapshot/s3-backup/daily-container-logs-backup-2026-02-25-02:00-abc123/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "container-logs-bigdata-prod-2026.02.20",
    "ignore_unavailable": true,
    "include_global_state": false,
    "rename_pattern": "(.+)",
    "rename_replacement": "restored-$1"
  }'
```

결과: `restored-container-logs-bigdata-prod-2026.02.20` 인덱스 생성

### 5-4. Searchable Snapshot으로 복원 (S3에서 직접 검색)

데이터를 로컬 디스크에 복사하지 않고 S3에서 직접 검색합니다.

```bash
curl -X POST "http://opensearch:9200/_snapshot/s3-backup/daily-container-logs-backup-2026-02-25-02:00-abc123/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "container-logs-bigdata-prod-2026.02.20",
    "storage_type": "remote_snapshot",
    "rename_pattern": "(.+)",
    "rename_replacement": "cold-$1"
  }'
```

> **주의:** `storage_type: "remote_snapshot"`은 `search` 역할의 노드가 필요합니다.

### 5-5. 복원 상태 확인

```bash
# 복원 진행 상태
curl -s "http://opensearch:9200/_recovery?pretty&active_only=true"

# 특정 인덱스 복원 상태
curl -s "http://opensearch:9200/restored-container-logs-bigdata-prod-2026.02.20/_recovery?pretty"
```

## 6. 재해 복구 (DR) 시나리오

### 6-1. 클러스터 전체 장애 시 복구

```bash
# 1. 새 클러스터에 repository-s3 플러그인 설치 및 설정

# 2. 스냅샷 리포지토리 등록 (기존과 동일한 S3 버킷)
curl -X PUT "http://new-opensearch:9200/_snapshot/s3-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots-prod",
      "base_path": "cluster-bigdata-prod",
      "region": "ap-northeast-2"
    }
  }'

# 3. 사용 가능한 스냅샷 목록 확인
curl -s "http://new-opensearch:9200/_snapshot/s3-backup/_all?pretty"

# 4. 최신 스냅샷에서 전체 복원
curl -X POST "http://new-opensearch:9200/_snapshot/s3-backup/LATEST_SNAPSHOT/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "*",
    "ignore_unavailable": true,
    "include_global_state": false
  }'

# 5. 인덱스 템플릿 재적용
# (include_global_state: false이므로 템플릿은 수동 적용 필요)
# 02-index-templates.md 참조

# 6. ISM 정책 재적용
# 03-ism-policies.md 참조
```

### 6-2. 특정 인덱스 손상 시 복구

```bash
# 1. 손상된 인덱스 삭제
curl -X DELETE "http://opensearch:9200/container-logs-bigdata-prod-2026.02.20"

# 2. 스냅샷에서 해당 인덱스만 복원
curl -X POST "http://opensearch:9200/_snapshot/s3-backup/daily-container-logs-backup-2026-02-20-02:00-abc123/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "container-logs-bigdata-prod-2026.02.20",
    "ignore_unavailable": true,
    "include_global_state": false
  }'
```

### 6-3. 다른 클러스터로 데이터 마이그레이션

```bash
# 소스 클러스터에서 스냅샷 생성 → S3 저장
# 대상 클러스터에서 같은 S3 리포지토리 등록 → 복원

# 대상 클러스터에서:
curl -X PUT "http://target-opensearch:9200/_snapshot/migration-repo" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots-prod",
      "base_path": "cluster-bigdata-prod",
      "region": "ap-northeast-2",
      "readonly": true
    }
  }'

# readonly: true로 설정하여 소스 스냅샷을 보호
```

## 7. Kubernetes CronJob 기반 스냅샷

SM 정책 대신 Kubernetes CronJob으로 스냅샷을 관리할 수도 있습니다.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: opensearch-daily-snapshot
  namespace: logging
spec:
  schedule: "0 2 * * *"             # 매일 새벽 2시 (UTC)
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 7
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 3
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: snapshot
              image: curlimages/curl:latest
              env:
                - name: OPENSEARCH_URL
                  value: "http://opensearch-cluster-master.logging.svc.cluster.local:9200"
                - name: REPO_NAME
                  value: "s3-backup"
              command:
                - /bin/sh
                - -c
                - |
                  set -e
                  DATE=$(date +%Y%m%d-%H%M%S)

                  echo "=== 스냅샷 생성: snapshot-${DATE} ==="
                  curl -sf -X PUT "${OPENSEARCH_URL}/_snapshot/${REPO_NAME}/snapshot-${DATE}?wait_for_completion=true" \
                    -H 'Content-Type: application/json' \
                    -d '{
                      "indices": "container-logs-*,k8s-events-*,systemd-logs-*",
                      "ignore_unavailable": true,
                      "include_global_state": false
                    }'

                  echo ""
                  echo "=== 오래된 스냅샷 정리 (30일 이전) ==="
                  CUTOFF=$(date -d "30 days ago" +%Y%m%d)
                  curl -sf "${OPENSEARCH_URL}/_snapshot/${REPO_NAME}/_all" | \
                    python3 -c "
                  import json,sys
                  data=json.load(sys.stdin)
                  for snap in data.get('snapshots', []):
                    name = snap['snapshot']
                    if name.startswith('snapshot-'):
                      date_part = name.split('-')[1]
                      if date_part < '${CUTOFF}':
                        print(name)
                  " | while read old_snapshot; do
                    echo "삭제: ${old_snapshot}"
                    curl -sf -X DELETE "${OPENSEARCH_URL}/_snapshot/${REPO_NAME}/${old_snapshot}"
                  done

                  echo ""
                  echo "=== 완료 ==="
```

## 8. 모니터링 및 알림

### 스냅샷 상태 확인 스크립트

```bash
#!/bin/bash
# check-snapshots.sh
OPENSEARCH_URL="${OPENSEARCH_URL:-http://opensearch-cluster-master.logging.svc.cluster.local:9200}"
REPO="${1:-s3-backup}"

echo "=== 리포지토리 상태 ==="
curl -s "${OPENSEARCH_URL}/_snapshot/${REPO}?pretty"

echo ""
echo "=== 최근 스냅샷 (최근 10개) ==="
curl -s "${OPENSEARCH_URL}/_snapshot/${REPO}/_all?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
snapshots = sorted(data.get('snapshots', []), key=lambda x: x.get('start_time', ''), reverse=True)[:10]
for snap in snapshots:
  state = snap['state']
  idx_count = len(snap['indices'])
  start = snap.get('start_time', 'N/A')
  duration_ms = snap.get('duration_in_millis', 0)
  duration_s = duration_ms / 1000
  shards = snap.get('shards', {})
  failed = shards.get('failed', 0)
  status = '✓' if state == 'SUCCESS' else '✗'
  print(f'  {status} {snap[\"snapshot\"]}: state={state}, indices={idx_count}, duration={duration_s:.0f}s, failed_shards={failed}')
"

echo ""
echo "=== 진행 중인 스냅샷 ==="
curl -s "${OPENSEARCH_URL}/_snapshot/${REPO}/_status?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
snapshots = data.get('snapshots', [])
if not snapshots:
  print('  없음')
else:
  for snap in snapshots:
    state = snap.get('state', 'N/A')
    stats = snap.get('stats', {})
    total_size = stats.get('total', {}).get('size_in_bytes', 0) / (1024**3)
    done_size = stats.get('incremental', {}).get('size_in_bytes', 0) / (1024**3)
    print(f'  {snap[\"snapshot\"]}: state={state}, total={total_size:.2f}GB, done={done_size:.2f}GB')
"

echo ""
echo "=== SM 정책 상태 ==="
for policy in daily-container-logs-backup daily-k8s-events-backup daily-systemd-logs-backup; do
  status=$(curl -s "${OPENSEARCH_URL}/_plugins/_sm/policies/${policy}/_explain" 2>/dev/null | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('policies', [{}])[0].get('policy', {}).get('enabled', 'N/A'))" 2>/dev/null)
  echo "  ${policy}: enabled=${status:-not found}"
done
```

## 9. 트러블슈팅

### 스냅샷 실패 원인

| 오류 | 원인 | 해결 |
|------|------|------|
| `repository_missing_exception` | 리포지토리 미등록 또는 삭제됨 | 리포지토리 재등록 |
| `snapshot_restore_exception` | 같은 이름의 인덱스 존재 | rename_pattern 사용 또는 기존 인덱스 삭제 |
| `repository_verification_exception` | S3 접근 권한 없음 | IAM 정책/자격증명 확인 |
| `concurrent_snapshot_execution_exception` | 이미 스냅샷 진행 중 | 완료 대기 후 재시도 |
| `snapshot_in_progress_exception` | 삭제 중인 스냅샷 존재 | 완료 대기 |

### S3 연결 문제 디버깅

```bash
# 1. 리포지토리 검증
curl -X POST "http://opensearch:9200/_snapshot/s3-backup/_verify?pretty"

# 2. 노드별 접근 확인
curl -s "http://opensearch:9200/_nodes?pretty" | python3 -c "
import json,sys
data=json.load(sys.stdin)
for node_id, node in data.get('nodes', {}).items():
  print(f\"{node['name']}: {node['transport_address']}\")
"

# 3. OpenSearch 로그에서 S3 오류 확인
kubectl logs -n logging -l app=opensearch --tail=100 | grep -i "s3\|snapshot\|repository"

# 4. MinIO 연결 시 endpoint 형식 확인
# 올바른: minio.logging.svc.cluster.local:9000
# 잘못된: http://minio.logging.svc.cluster.local:9000  (프로토콜 포함 X)
```

## 10. 베스트 프랙티스

1. **증분 백업 활용:** 매일 스냅샷을 생성하면 변경된 세그먼트만 저장되므로 시간과 비용이 절약됩니다.
2. **SM 정책 사용:** CronJob 대신 SM 정책을 사용하면 OpenSearch 내에서 통합 관리됩니다.
3. **min_count 설정:** SM 삭제 조건에 `min_count`를 설정하여 최소 백업을 보장합니다.
4. **복원 테스트:** 정기적으로 (월 1회) 스냅샷 복원을 테스트하여 백업 무결성을 확인합니다.
5. **S3 버전 관리:** S3 버킷의 버전 관리를 활성화하여 실수로 삭제된 스냅샷을 복구할 수 있게 합니다.
6. **cross-region 복제:** 재해 복구를 위해 S3 버킷의 cross-region 복제를 설정합니다.
7. **속도 제한:** `max_snapshot_bytes_per_sec`를 적절히 설정하여 스냅샷이 서비스 성능에 영향을 미치지 않도록 합니다.
8. **include_global_state: false:** 로그 백업에서는 클러스터 설정을 포함하지 않는 것이 좋습니다. 설정 변경과 데이터 백업을 분리합니다.
