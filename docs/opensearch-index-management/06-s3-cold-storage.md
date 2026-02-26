# S3 기반 Cold 데이터 저장 가이드

## 1. 개요

OpenSearch의 ISM 정책에서 Cold 단계의 인덱스 데이터를 S3(또는 S3 호환 스토리지)에 저장하여 로컬 디스크 비용을 절감할 수 있습니다. 이를 **Searchable Snapshots** 방식이라 하며, 데이터는 S3에 보관되고 검색 시 필요한 부분만 캐싱하여 조회합니다.

### 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         OpenSearch 클러스터                               │
│                                                                         │
│  ┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌───────────┐ │
│  │  Hot      │────▶│  Warm    │────▶│  Snapshot    │────▶│  Cold     │ │
│  │  (로컬)   │     │  (로컬)  │     │  (S3 저장)   │     │(S3 검색)  │ │
│  │  0~7일    │     │  7~30일  │     │  30일        │     │ 30~90일   │ │
│  └──────────┘     └──────────┘     └──────────────┘     └───────────┘ │
│       ↓                ↓                  ↓                    ↓       │
│   로컬 디스크      로컬 디스크         S3 버킷             S3 버킷     │
│   (SSD)           (HDD 가능)       (스냅샷 저장)      (Searchable     │
│                                                       Snapshot)       │
│                                                            ↓          │
│                                                    ┌───────────┐      │
│                                                    │  Delete    │      │
│                                                    │  90일+     │      │
│                                                    └───────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↕
                          ┌─────────────────┐
                          │   S3 / MinIO     │
                          │   Object Store   │
                          │                  │
                          │  snapshots/      │
                          │  ├── container/  │
                          │  ├── k8s-events/ │
                          │  └── systemd/    │
                          └─────────────────┘
```

### 비용 절감 효과

| 저장 방식 | 90일 보관 비용 (10TB 기준) | 검색 가능 여부 |
|-----------|--------------------------|--------------|
| 전체 로컬 SSD | $$$$$ | 즉시 검색 |
| Hot(SSD) + Warm(HDD) | $$$$ | 즉시 검색 |
| Hot + Warm + Cold(S3) | $$ | 검색 가능 (지연 있음) |
| Hot + Warm + S3 스냅샷만 | $ | 복원 후 검색 |

## 2. 사전 요구사항

### 2-1. repository-s3 플러그인 설치

모든 OpenSearch 노드에 `repository-s3` 플러그인이 설치되어 있어야 합니다.

```bash
# 각 노드에서 실행
sudo /usr/share/opensearch/bin/opensearch-plugin install repository-s3
sudo systemctl restart opensearch
```

**Docker/Kubernetes 환경:**

```dockerfile
FROM opensearchproject/opensearch:2.19.0
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch repository-s3
```

Helm values에서 커스텀 이미지 사용:

```yaml
# infra/opensearch/values.yaml
image:
  repository: my-registry/opensearch-with-s3
  tag: "2.19.0"
```

### 2-2. Search 노드 역할 설정 (Searchable Snapshots용)

Cold tier의 Searchable Snapshots를 사용하려면 `search` 역할의 노드가 필요합니다.

```yaml
# opensearch.yml (search 노드)
node.roles: [search]

# 또는 기존 노드에 역할 추가
node.roles: [data, search]
```

> **소규모 클러스터:** 기존 data 노드에 `search` 역할을 추가해도 됩니다.
> **대규모 클러스터:** 전용 search 노드를 별도로 구성하는 것을 권장합니다.

## 3. S3 스토리지 설정

### 3-1. AWS S3 설정

#### IAM 정책 생성

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3BucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLocation",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:ListBucketVersions"
      ],
      "Resource": "arn:aws:s3:::opensearch-cold-storage"
    },
    {
      "Sid": "S3ObjectAccess",
      "Effect": "Allow",
      "Action": [
        "s3:AbortMultipartUpload",
        "s3:DeleteObject",
        "s3:GetObject",
        "s3:ListMultipartUploadParts",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::opensearch-cold-storage/*"
    }
  ]
}
```

#### 자격증명 등록 (Keystore)

```bash
# 모든 OpenSearch 노드에서 실행
/usr/share/opensearch/bin/opensearch-keystore add s3.client.default.access_key
# → Access Key 입력

/usr/share/opensearch/bin/opensearch-keystore add s3.client.default.secret_key
# → Secret Key 입력

# 변경사항 즉시 반영 (재시작 불필요)
curl -X POST "http://opensearch:9200/_nodes/reload_secure_settings"
```

#### EKS IRSA (IAM Roles for Service Accounts) 설정

EKS 환경에서는 ServiceAccount에 IAM 역할을 바인딩합니다.

```bash
# 1. OIDC 프로바이더 연결
eksctl utils associate-iam-oidc-provider --cluster my-cluster --approve

# 2. ServiceAccount 생성 및 IAM 역할 바인딩
eksctl create iamserviceaccount \
  --name opensearch-sa \
  --namespace logging \
  --cluster my-cluster \
  --role-name OpenSearchS3Role \
  --attach-policy-arn arn:aws:iam::123456789012:policy/OpenSearchS3Policy \
  --approve
```

OpenSearch Helm values에서 ServiceAccount 지정:

```yaml
serviceAccount:
  create: false
  name: opensearch-sa
```

Keystore에 역할 정보 등록:

```bash
opensearch-keystore add s3.client.default.role_arn
# → arn:aws:iam::123456789012:role/OpenSearchS3Role 입력

opensearch-keystore add s3.client.default.role_session_name
# → opensearch-snapshot-session 입력

opensearch-keystore add s3.client.default.identity_token_file
# → /var/run/secrets/eks.amazonaws.com/serviceaccount/token 입력
```

### 3-2. MinIO (On-Premise S3 호환 스토리지) 설정

온프레미스 환경에서는 MinIO를 S3 호환 스토리지로 사용할 수 있습니다.

#### MinIO 배포 (Kubernetes)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
  namespace: logging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      containers:
        - name: minio
          image: minio/minio:latest
          command: ["server", "/data", "--console-address", ":9001"]
          env:
            - name: MINIO_ROOT_USER
              value: "minioadmin"
            - name: MINIO_ROOT_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: minio-secret
                  key: password
          ports:
            - containerPort: 9000
              name: api
            - containerPort: 9001
              name: console
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: minio-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: minio
  namespace: logging
spec:
  selector:
    app: minio
  ports:
    - name: api
      port: 9000
      targetPort: 9000
    - name: console
      port: 9001
      targetPort: 9001
```

#### OpenSearch S3 클라이언트 설정 (MinIO용)

`opensearch.yml`에 MinIO 엔드포인트 설정:

```yaml
# opensearch.yml
s3.client.default.endpoint: "minio.logging.svc.cluster.local:9000"
s3.client.default.protocol: http
s3.client.default.path_style_access: true
s3.client.default.region: us-east-1    # 필수 (MinIO에서는 무시됨)
```

> **주의:** `endpoint`에 `http://` 프로토콜을 포함하지 마세요. `protocol` 속성으로 별도 지정합니다. 프로토콜을 endpoint에 포함하면 "Connect timed out" 오류가 발생합니다.

Keystore에 MinIO 자격증명 등록:

```bash
opensearch-keystore add s3.client.default.access_key
# → minioadmin 입력

opensearch-keystore add s3.client.default.secret_key
# → MinIO Secret Key 입력
```

#### MinIO 버킷 생성

```bash
# mc (MinIO Client) 사용
mc alias set myminio http://minio.logging.svc.cluster.local:9000 minioadmin minioadmin
mc mb myminio/opensearch-snapshots
mc mb myminio/opensearch-cold-storage
```

## 4. S3 스냅샷 리포지토리 등록

### AWS S3

```bash
curl -X PUT "http://opensearch:9200/_snapshot/s3-snapshot-repo" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-cold-storage",
      "base_path": "snapshots",
      "region": "ap-northeast-2"
    }
  }'
```

### MinIO

```bash
curl -X PUT "http://opensearch:9200/_snapshot/s3-snapshot-repo" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots",
      "base_path": "snapshots",
      "path_style_access": true
    }
  }'
```

### 리포지토리 검증

```bash
# 등록 확인
curl -s "http://opensearch:9200/_snapshot/s3-snapshot-repo?pretty"

# 연결 검증 (모든 노드에서 S3 접근 가능 확인)
curl -X POST "http://opensearch:9200/_snapshot/s3-snapshot-repo/_verify?pretty"
```

## 5. ISM 정책: S3 Cold Tier 적용

### 5-1. Snapshot + Searchable Snapshot 방식

ISM 정책에 `snapshot` 액션과 `convert_index_to_remote` 액션을 추가하여 Cold 데이터를 S3에 보관하면서도 검색 가능하게 합니다.

```json
{
  "policy": {
    "description": "Container log - S3 Cold tier (90일 보관, 30일부터 S3)",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["container-logs-*"],
        "priority": 100
      }
    ],
    "states": [
      {
        "name": "hot",
        "actions": [],
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
            "retry": { "count": 3, "backoff": "exponential", "delay": "1m" },
            "read_only": {}
          },
          {
            "replica_count": { "number_of_replicas": 1 }
          },
          {
            "index_priority": { "priority": 50 }
          }
        ],
        "transitions": [
          {
            "state_name": "snapshot_to_s3",
            "conditions": {
              "min_index_age": "25d"
            }
          }
        ]
      },
      {
        "name": "snapshot_to_s3",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "snapshot": {
              "repository": "s3-snapshot-repo",
              "snapshot": "{{ctx.index}}-{{ctx.execution_time}}"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "cold_s3",
            "conditions": {
              "min_index_age": "30d"
            }
          }
        ]
      },
      {
        "name": "cold_s3",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "convert_index_to_remote": {
              "repository": "s3-snapshot-repo"
            }
          }
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
          {
            "delete": {}
          }
        ],
        "transitions": []
      }
    ]
  }
}
```

### 핵심 액션 설명

| 액션 | 단계 | 설명 |
|------|------|------|
| `snapshot` | snapshot_to_s3 | 인덱스 데이터를 S3 리포지토리에 스냅샷으로 저장 |
| `convert_index_to_remote` | cold_s3 | 로컬 인덱스를 삭제하고 S3 스냅샷을 Searchable Snapshot으로 전환 |
| `delete` | delete | S3의 스냅샷 데이터도 함께 삭제 |

### 동작 흐름

```
1. Hot (0~7일)
   └─ 로컬 디스크에 데이터 저장, 읽기/쓰기 가능

2. Warm (7~25일)
   └─ 읽기 전용, 로컬 디스크 유지

3. Snapshot to S3 (25~30일)
   └─ S3에 스냅샷 생성 (로컬 데이터도 유지)
   └─ 스냅샷 완료 후 cold_s3 단계 대기

4. Cold S3 (30~90일)
   └─ convert_index_to_remote 실행
   └─ 로컬 인덱스 삭제 → S3 Searchable Snapshot으로 대체
   └─ 검색 시 S3에서 필요한 세그먼트만 캐싱하여 조회
   └─ 로컬 디스크 공간 회수

5. Delete (90일+)
   └─ S3 스냅샷 및 인덱스 모두 삭제
```

### 5-2. Snapshot 후 로컬 삭제 방식 (검색 불필요 시)

Cold 데이터를 검색할 필요가 없다면, 스냅샷만 S3에 보관하고 로컬 인덱스를 삭제하는 더 간단한 방식을 사용할 수 있습니다.

```json
{
  "policy": {
    "description": "Container log - S3 archive only (검색 불필요 시)",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["container-logs-*"],
        "priority": 100
      }
    ],
    "states": [
      {
        "name": "hot",
        "actions": [],
        "transitions": [
          {
            "state_name": "warm",
            "conditions": { "min_index_age": "7d" }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          { "read_only": {} },
          { "replica_count": { "number_of_replicas": 0 } }
        ],
        "transitions": [
          {
            "state_name": "archive",
            "conditions": { "min_index_age": "30d" }
          }
        ]
      },
      {
        "name": "archive",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "snapshot": {
              "repository": "s3-snapshot-repo",
              "snapshot": "archive-{{ctx.index}}-{{ctx.execution_time}}"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": { "min_index_age": "31d" }
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
    ]
  }
}
```

> **차이점:** `convert_index_to_remote` 없이 `snapshot` + `delete`만 사용합니다. 데이터는 S3 스냅샷으로만 존재하며, 복원하려면 수동 restore가 필요합니다.

## 6. 로그 유형별 S3 Cold Tier 적용

### 적용 전략

| 로그 유형 | S3 Cold 적용 | 방식 | 이유 |
|-----------|:-----------:|------|------|
| Container Log | O | Searchable Snapshot | 장기 보관 + 검색 필요 |
| K8s Event | X | 로컬 삭제 | 30일이면 충분, S3 불필요 |
| Systemd Log | O | Archive (스냅샷만) | 장기 보관 필요하나 검색 빈도 낮음 |

### 적용 명령

```bash
# Container Log: Searchable Snapshot 방식
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/container-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-container-logs-s3.json

# Systemd Log: Archive 방식
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/systemd-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-systemd-logs-s3.json
```

## 7. Searchable Snapshot 성능 튜닝

### 파일 캐시 설정

Searchable Snapshot은 S3에서 가져온 세그먼트를 로컬에 캐싱합니다. 캐시 비율을 조정하여 성능을 최적화합니다.

```bash
# 캐시 비율 설정 (remote 데이터가 로컬 캐시의 N배까지 허용)
curl -X PUT "http://opensearch:9200/_cluster/settings" \
  -H 'Content-Type: application/json' \
  -d '{
    "persistent": {
      "cluster.filecache.remote_data_ratio": "5"
    }
  }'
```

| 설정값 | 의미 | 권장 환경 |
|--------|------|----------|
| 2 | 캐시 크기의 2배까지 remote 데이터 | 검색 빈번, 빠른 응답 필요 |
| 5 | 캐시 크기의 5배까지 remote 데이터 | 일반적인 로그 검색 |
| 10 | 캐시 크기의 10배까지 remote 데이터 | 검색 드문 아카이브 |

### Force Merge (스냅샷 전 최적화)

스냅샷 전에 세그먼트를 병합하면 S3에서의 검색 성능이 향상됩니다.

```bash
# Warm 단계에서 force merge 수행
curl -X POST "http://opensearch:9200/container-logs-bigdata-prod-2026.01.15/_forcemerge?max_num_segments=1"
```

ISM 정책의 Warm 단계에 force_merge 액션 추가:

```json
{
  "name": "warm",
  "actions": [
    { "read_only": {} },
    {
      "force_merge": {
        "max_num_segments": 1
      }
    },
    { "replica_count": { "number_of_replicas": 1 } }
  ],
  "transitions": [...]
}
```

## 8. 모니터링

### S3 Cold 인덱스 확인

```bash
# remote_snapshot 유형의 인덱스 목록
curl -s "http://opensearch:9200/_cat/indices?v&h=index,store.size,status,health" | grep -i cold

# Searchable Snapshot 상태 확인
curl -s "http://opensearch:9200/_cat/segments/container-logs-*?v&h=index,shard,segment,size,searchable"
```

### S3 스토리지 사용량 확인

```bash
# 스냅샷 리포지토리의 스냅샷 목록
curl -s "http://opensearch:9200/_snapshot/s3-snapshot-repo/_all?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for snap in data.get('snapshots', []):
  print(f\"{snap['snapshot']}: state={snap['state']}, indices={len(snap['indices'])}개\")
"

# 특정 스냅샷 상세
curl -s "http://opensearch:9200/_snapshot/s3-snapshot-repo/container-logs-bigdata-prod-2026.01.15-*?pretty"
```

## 9. 주의사항

1. **`convert_index_to_remote` 전에 `snapshot`이 필수:** 같은 ISM 정책 내에서 snapshot 액션이 먼저 실행되어야 합니다.
2. **Cold 인덱스는 읽기 전용:** Searchable Snapshot으로 전환된 인덱스는 쓰기가 불가능합니다.
3. **S3 비용 고려:** 스토리지 비용은 저렴하지만 GET 요청 비용이 발생합니다. 검색 빈도가 높으면 비용이 증가할 수 있습니다.
4. **네트워크 지연:** S3에서 데이터를 가져오므로 로컬 디스크 대비 검색 지연이 발생합니다 (보통 수백ms~수초).
5. **S3 스냅샷 직접 삭제 금지:** S3 콘솔에서 직접 파일을 삭제하면 안 됩니다. 반드시 OpenSearch API를 통해 삭제하세요.
6. **OpenSearch 버전:** Searchable Snapshots는 OpenSearch 2.4+, `convert_index_to_remote`는 OpenSearch 2.14+ 에서 지원됩니다.
