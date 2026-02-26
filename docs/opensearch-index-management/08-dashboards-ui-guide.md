# OpenSearch Dashboards UI 기반 ISM + Snapshot (MinIO S3) 설정 가이드

## 1. 개요

이 문서는 OpenSearch Dashboards 웹 UI를 통해 ISM 정책과 MinIO S3 스냅샷을 설정하는 **단계별 가이드**입니다. CLI(curl) 대신 대시보드 화면에서 직접 조작하는 방법을 설명합니다.

### 사전 준비

| 항목 | 요구사항 |
|------|---------|
| OpenSearch | 2.x 이상 |
| OpenSearch Dashboards | 2.x 이상 |
| MinIO | 배포 완료, 접근 가능 |
| repository-s3 플러그인 | OpenSearch 노드에 설치 완료 |
| MinIO 버킷 | `opensearch-snapshots` 버킷 생성 완료 |

### Dashboards 접속 정보

```
URL:  http://<노드IP>:30561
```

> 현재 환경에서는 보안 플러그인이 비활성화되어 있으므로 별도 로그인 없이 접속 가능합니다.

---

## 2. MinIO S3 연동 사전 설정 (CLI 필수)

> **중요:** 스냅샷 리포지토리 등록을 위한 S3 클라이언트 설정과 자격증명은 Dashboards UI에서 설정할 수 없습니다. 이 단계만 CLI에서 수행하고, 이후 모든 작업은 Dashboards UI에서 진행합니다.

### 2-1. OpenSearch S3 클라이언트 설정

`opensearch.yml`에 MinIO 접속 정보를 추가합니다.

```yaml
# opensearch.yml (모든 OpenSearch 노드)
s3.client.default.endpoint: "minio.logging.svc.cluster.local:9000"
s3.client.default.protocol: http
s3.client.default.path_style_access: true
s3.client.default.region: us-east-1
```

Helm 기반 배포의 경우 `values.yaml`에 추가:

```yaml
# infra/opensearch/values.yaml
config:
  opensearch.yml: |
    s3.client.default.endpoint: "minio.logging.svc.cluster.local:9000"
    s3.client.default.protocol: http
    s3.client.default.path_style_access: true
    s3.client.default.region: us-east-1
```

### 2-2. MinIO 자격증명 등록

```bash
# OpenSearch Pod 내에서 실행
kubectl exec -it -n logging opensearch-cluster-master-0 -- bash

# Keystore에 자격증명 추가
/usr/share/opensearch/bin/opensearch-keystore add s3.client.default.access_key
# → minioadmin 입력

/usr/share/opensearch/bin/opensearch-keystore add s3.client.default.secret_key
# → (MinIO Secret Key 입력)

exit
```

자격증명 리로드 (재시작 불필요):

```bash
curl -X POST "http://opensearch-cluster-master.logging.svc.cluster.local:9200/_nodes/reload_secure_settings"
```

### 2-3. repository-s3 플러그인 확인

```bash
curl -s "http://opensearch-cluster-master.logging.svc.cluster.local:9200/_cat/plugins?v" | grep s3
```

출력 예시:
```
opensearch-cluster-master-0  repository-s3  2.x.x
```

> 플러그인이 없으면 [06-s3-cold-storage.md](./06-s3-cold-storage.md) §2-1을 참고하여 설치하세요.

---

## 3. Dashboards에서 스냅샷 리포지토리 등록

### 3-1. Dev Tools로 리포지토리 등록

Dashboards UI에는 스냅샷 리포지토리 등록을 위한 전용 화면이 없으므로 **Dev Tools**를 사용합니다.

**경로:** 좌측 메뉴 → **Management** → **Dev Tools**

Dev Tools 콘솔에 다음을 입력하고 ▶ (실행) 버튼을 클릭합니다:

```
PUT _snapshot/minio-s3-repo
{
  "type": "s3",
  "settings": {
    "bucket": "opensearch-snapshots",
    "base_path": "snapshots",
    "path_style_access": true,
    "compress": true
  }
}
```

**성공 응답:**

```json
{
  "acknowledged": true
}
```

### 3-2. 리포지토리 연결 검증

Dev Tools에서 실행:

```
POST _snapshot/minio-s3-repo/_verify
```

**성공 응답 예시:**

```json
{
  "nodes": {
    "abc123...": {
      "name": "opensearch-cluster-master-0"
    }
  }
}
```

> **실패 시 확인사항:**
> - MinIO가 실행 중인지 확인
> - endpoint, access_key, secret_key가 올바른지 확인
> - 버킷이 존재하는지 확인
> - `path_style_access: true` 가 설정되었는지 확인

### 3-3. 등록된 리포지토리 확인

```
GET _snapshot?pretty
```

또는 **Snapshot Management** 화면에서 확인:

**경로:** 좌측 메뉴 → **OpenSearch Plugins** → **Snapshot Management** → **Repositories** 탭

여기서 `minio-s3-repo`가 표시되어야 합니다.

---

## 4. Dashboards UI에서 ISM 정책 생성

### 4-1. Index Management 메뉴 진입

**경로:** 좌측 메뉴(☰) → **OpenSearch Plugins** → **Index Management**

왼쪽 사이드바에서 **Policies** 를 클릭합니다.

### 4-2. Container Log ISM 정책 생성

**[Create policy]** 버튼을 클릭합니다.

#### Step 1: 정책 ID 입력

| 항목 | 입력값 |
|------|--------|
| **Policy ID** | `container-logs-policy` |

**Configuration method** 에서 **JSON editor** 를 선택합니다.

#### Step 2: JSON 편집기에 정책 입력

아래 JSON을 전체 복사하여 편집기에 붙여넣습니다:

```json
{
  "policy": {
    "description": "Container log lifecycle - Hot(7d) → Warm(30d) → Snapshot S3(25d) → Cold S3(90d) → Delete",
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
            "force_merge": { "max_num_segments": 1 }
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
              "repository": "minio-s3-repo",
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
            "replica_count": { "number_of_replicas": 0 }
          },
          {
            "read_only": {}
          },
          {
            "index_priority": { "priority": 0 }
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

#### Step 3: 정책 생성 완료

**[Create]** 버튼을 클릭합니다.

> **Visual Editor로 생성하려면:**
> Configuration method에서 **Visual editor**를 선택하면 상태(state)와 전환(transition)을 드래그앤드롭으로 구성할 수 있습니다. 아래 별도 섹션에서 Visual Editor 사용법을 설명합니다.

### 4-3. K8s Event Log ISM 정책 생성

동일하게 **[Create policy]** → **JSON editor** → 아래 JSON 붙여넣기:

```json
{
  "policy": {
    "description": "K8s event log lifecycle - Hot(7d) → Warm(30d) → Delete",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["k8s-events-*"],
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
            "replica_count": { "number_of_replicas": 0 }
          },
          {
            "index_priority": { "priority": 25 }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "30d"
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

### 4-4. Systemd Log ISM 정책 생성

**[Create policy]** → **JSON editor** → 아래 JSON 붙여넣기:

```json
{
  "policy": {
    "description": "Systemd log lifecycle - Hot(7d) → Warm(14d) → Snapshot Archive S3(14d) → Delete(60d)",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["systemd-logs-*"],
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
            "force_merge": { "max_num_segments": 1 }
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
            "state_name": "archive_to_s3",
            "conditions": {
              "min_index_age": "14d"
            }
          }
        ]
      },
      {
        "name": "archive_to_s3",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "snapshot": {
              "repository": "minio-s3-repo",
              "snapshot": "archive-{{ctx.index}}-{{ctx.execution_time}}"
            }
          },
          {
            "replica_count": { "number_of_replicas": 0 }
          },
          {
            "index_priority": { "priority": 0 }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "60d"
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

---

## 5. Visual Editor로 ISM 정책 생성하기

JSON 대신 시각적으로 정책을 구성하는 방법입니다.

### 5-1. Visual Editor 진입

1. 좌측 메뉴 → **OpenSearch Plugins** → **Index Management** → **Policies**
2. **[Create policy]** 클릭
3. **Policy ID** 입력: `container-logs-policy`
4. **Configuration method**: **Visual editor** 선택

### 5-2. State 추가

#### Hot State 구성

1. **[Add state]** 클릭
2. **State name**: `hot`
3. **Order**: 1 (첫 번째 상태)
4. Actions: 없음 (비워둠)
5. **Transitions**:
   - **[Add transition]** 클릭
   - **Destination state**: `warm`
   - **Condition**: Minimum index age → `7d`

#### Warm State 구성

1. **[Add state]** 클릭
2. **State name**: `warm`
3. **Actions**:
   - **[Add action]** → **Read only** 선택
   - **[Add action]** → **Set number of replicas** → `1`
   - **[Add action]** → **Force merge** → Max num segments: `1`
   - **[Add action]** → **Set index priority** → Priority: `50`
4. **Transitions**:
   - **Destination state**: `snapshot_to_s3`
   - **Condition**: Minimum index age → `25d`

#### Snapshot to S3 State 구성

1. **[Add state]** 클릭
2. **State name**: `snapshot_to_s3`
3. **Actions**:
   - **[Add action]** → **Snapshot** 선택
   - **Repository**: `minio-s3-repo`
   - **Snapshot name**: `{{ctx.index}}-{{ctx.execution_time}}`
4. **Transitions**:
   - **Destination state**: `cold_s3`
   - **Condition**: Minimum index age → `30d`

#### Cold S3 State 구성

1. **[Add state]** 클릭
2. **State name**: `cold_s3`
3. **Actions**:
   - **[Add action]** → **Read only** 선택
   - **[Add action]** → **Set number of replicas** → `0`
   - **[Add action]** → **Set index priority** → Priority: `0`
4. **Transitions**:
   - **Destination state**: `delete`
   - **Condition**: Minimum index age → `90d`

#### Delete State 구성

1. **[Add state]** 클릭
2. **State name**: `delete`
3. **Actions**:
   - **[Add action]** → **Delete** 선택
4. **Transitions**: 없음

### 5-3. ISM Template 설정

페이지 하단의 **ISM templates** 섹션:

1. **[Add template]** 클릭
2. **Index patterns**: `container-logs-*`
3. **Priority**: `100`

### 5-4. 정책 생성

**[Create]** 버튼을 클릭하여 정책을 생성합니다.

---

## 6. 기존 인덱스에 ISM 정책 적용

### 6-1. UI에서 정책 적용

1. 좌측 메뉴 → **OpenSearch Plugins** → **Index Management** → **Indices**
2. 정책을 적용할 인덱스를 **체크박스**로 선택
   - `container-logs-*` 인덱스들을 모두 선택
3. 상단 **[Actions]** 드롭다운 → **Apply policy** 클릭
4. 드롭다운에서 `container-logs-policy` 선택
5. **[Apply]** 클릭

### 6-2. 적용 상태 확인

1. **Index Management** → **Policy managed indices** 탭 클릭
2. 각 인덱스의 ISM 상태를 확인:
   - **Policy**: 적용된 정책명
   - **State**: 현재 단계 (hot/warm/cold 등)
   - **Action**: 현재 실행 중인 액션
   - **Info**: 상세 정보/오류 메시지

### 6-3. 인덱스별 ISM 상태 상세 확인

**Policy managed indices** 목록에서 특정 인덱스를 클릭하면 상세 정보를 볼 수 있습니다:

- 현재 state와 다음 transition 조건
- 마지막 실행된 액션
- 오류 발생 시 재시도 정보

또는 **Dev Tools**에서:

```
POST _plugins/_ism/explain/container-logs-bigdata-prod-2026.02.26
```

---

## 7. Dashboards UI에서 스냅샷 관리

### 7-1. Snapshot Management 메뉴 진입

**경로:** 좌측 메뉴(☰) → **OpenSearch Plugins** → **Snapshot Management**

이 화면에서 다음을 관리할 수 있습니다:
- **Snapshots**: 스냅샷 목록, 생성, 삭제, 복원
- **Repositories**: 등록된 리포지토리 목록
- **SM Policies**: 자동 스냅샷 정책

### 7-2. 리포지토리 확인

**Repositories** 탭에서:

| 열 | 설명 |
|-----|------|
| **Repository** | 리포지토리 이름 (`minio-s3-repo`) |
| **Type** | 유형 (`s3`) |
| **Status** | 연결 상태 |

### 7-3. 수동 스냅샷 생성

1. **Snapshots** 탭 클릭
2. **[Take snapshot]** 버튼 클릭
3. 다음 정보를 입력:

| 항목 | 입력값 | 설명 |
|------|--------|------|
| **Snapshot name** | `manual-backup-20260226` | 스냅샷 이름 |
| **Repository** | `minio-s3-repo` | 드롭다운에서 선택 |
| **Indices** | `container-logs-*,k8s-events-*,systemd-logs-*` | 또는 개별 선택 |
| **Include cluster state** | 체크 해제 | 로그 백업에는 불필요 |
| **Ignore unavailable indices** | 체크 | 없는 인덱스 무시 |

4. **[Add]** 또는 **[Take snapshot]** 클릭

### 7-4. 스냅샷 상태 확인

**Snapshots** 탭에서 각 스냅샷의 상태를 확인합니다:

| 상태 | 아이콘 | 설명 |
|------|--------|------|
| **IN_PROGRESS** | 🔄 | 스냅샷 진행 중 |
| **SUCCESS** | ✅ | 스냅샷 완료 |
| **FAILED** | ❌ | 스냅샷 실패 |
| **PARTIAL** | ⚠️ | 일부 샤드 실패 |

스냅샷을 클릭하면 상세 정보를 볼 수 있습니다:
- 포함된 인덱스 목록
- 시작/종료 시간
- 총 샤드 수 및 실패한 샤드 수
- 스냅샷 크기

### 7-5. 스냅샷에서 복원

1. **Snapshots** 탭에서 복원할 스냅샷 선택
2. **[Restore]** 버튼 클릭 (또는 스냅샷 이름 클릭 → Restore)
3. 복원 설정:

| 항목 | 설정 | 설명 |
|------|------|------|
| **Indices to restore** | 전체 또는 특정 인덱스 선택 | 필요한 인덱스만 선택 가능 |
| **Rename indices** | `restored-<original>` | 기존 인덱스와 충돌 방지 |
| **Custom index settings** | replica: 0 등 | 복원 시 설정 오버라이드 |

4. **[Restore snapshot]** 클릭

### 7-6. 스냅샷 삭제

1. **Snapshots** 탭에서 삭제할 스냅샷을 체크박스로 선택
2. **[Delete]** 버튼 클릭
3. 확인 다이얼로그에서 스냅샷 이름 입력 후 삭제 확인

> **주의:** 삭제된 스냅샷은 MinIO에서도 데이터가 제거됩니다. 복구할 수 없으므로 신중하게 삭제하세요.

---

## 8. Dashboards UI에서 SM(Snapshot Management) 자동화 정책 생성

### 8-1. SM 정책 생성 화면 진입

1. **Snapshot Management** → **SM Policies** 탭
2. **[Create policy]** 클릭

### 8-2. Container Log 일일 자동 스냅샷 정책

#### Policy settings

| 항목 | 입력값 |
|------|--------|
| **Policy name** | `daily-container-logs-backup` |
| **Description** | `Container log 일일 자동 스냅샷 - MinIO S3 30일 보관` |

#### Source and destination

| 항목 | 입력값 |
|------|--------|
| **Repository** | 드롭다운에서 `minio-s3-repo` 선택 |
| **Snapshot name** | `container-logs-{yyyy}-{MM}-{dd}-{HH}:{mm}` |
| **Indices** | `container-logs-*` |
| **Include cluster state** | 체크 해제 |

> **스냅샷 이름 변수:** `{yyyy}`, `{MM}`, `{dd}`, `{HH}`, `{mm}`을 조합하여 날짜 기반 이름을 자동 생성합니다.

#### Snapshot schedule (생성 스케줄)

| 항목 | 입력값 |
|------|--------|
| **Frequency** | **Daily** |
| **Time** | `02:00` (새벽 2시) |
| **Timezone** | `Asia/Seoul` |

또는 **Custom cron expression** 선택 시:
```
0 2 * * *
```

#### Retention (보관 정책)

| 항목 | 입력값 | 설명 |
|------|--------|------|
| **Max age** | `30d` | 30일 이상 된 스냅샷 삭제 |
| **Max count** | `30` | 최대 30개 보관 |
| **Min count** | `7` | 최소 7개는 항상 유지 |
| **Deletion frequency** | **Daily** |
| **Deletion time** | `03:00` (새벽 3시) |
| **Deletion timezone** | `Asia/Seoul` |

#### 알림 (Notifications) - 선택사항

| 항목 | 설정 |
|------|------|
| **Notify on creation** | 체크 (성공 시 알림) |
| **Notify on failure** | 체크 (실패 시 알림) |
| **Notify on deletion** | 체크 해제 |
| **Channel** | Slack, Email 등 사전 설정된 채널 선택 |

**[Create]** 버튼을 클릭하여 정책을 생성합니다.

### 8-3. K8s Event Log 일일 자동 스냅샷 정책

동일하게 **[Create policy]** 클릭 후:

| 항목 | 입력값 |
|------|--------|
| **Policy name** | `daily-k8s-events-backup` |
| **Description** | `K8s event log 일일 자동 스냅샷 - MinIO S3 14일 보관` |
| **Repository** | `minio-s3-repo` |
| **Snapshot name** | `k8s-events-{yyyy}-{MM}-{dd}-{HH}:{mm}` |
| **Indices** | `k8s-events-*` |
| **Schedule** | Daily, 02:00, Asia/Seoul |
| **Max age** | `14d` |
| **Max count** | `14` |
| **Min count** | `3` |
| **Deletion schedule** | Daily, 03:00, Asia/Seoul |

### 8-4. Systemd Log 일일 자동 스냅샷 정책

| 항목 | 입력값 |
|------|--------|
| **Policy name** | `daily-systemd-logs-backup` |
| **Description** | `Systemd log 일일 자동 스냅샷 - MinIO S3 30일 보관` |
| **Repository** | `minio-s3-repo` |
| **Snapshot name** | `systemd-logs-{yyyy}-{MM}-{dd}-{HH}:{mm}` |
| **Indices** | `systemd-logs-*` |
| **Schedule** | Daily, 02:00, Asia/Seoul |
| **Max age** | `30d` |
| **Max count** | `30` |
| **Min count** | `7` |
| **Deletion schedule** | Daily, 03:00, Asia/Seoul |

### 8-5. SM 정책 요약

생성 후 **SM Policies** 탭에서 3개 정책이 표시됩니다:

| 정책명 | 대상 인덱스 | 스케줄 | 보관기간 | 최소 보관 |
|--------|-----------|--------|---------|----------|
| `daily-container-logs-backup` | `container-logs-*` | 매일 02:00 | 30일 | 7개 |
| `daily-k8s-events-backup` | `k8s-events-*` | 매일 02:00 | 14일 | 3개 |
| `daily-systemd-logs-backup` | `systemd-logs-*` | 매일 02:00 | 30일 | 7개 |

### 8-6. SM 정책 관리

**SM Policies** 탭에서 각 정책에 대해:

| 작업 | 방법 |
|------|------|
| **상태 확인** | 정책 이름 클릭 → 마지막 실행 시간, 결과 확인 |
| **일시 중지** | 정책 선택 → **[Disable]** 클릭 |
| **재시작** | 정책 선택 → **[Enable]** 클릭 |
| **수정** | 정책 이름 클릭 → **[Edit]** 클릭 |
| **삭제** | 정책 선택 → **[Delete]** 클릭 |

---

## 9. Dashboards UI에서 인덱스 템플릿 생성

### 9-1. Index Templates 화면 진입

**경로:** 좌측 메뉴 → **OpenSearch Plugins** → **Index Management** → **Templates**

### 9-2. Container Log 인덱스 템플릿 생성

1. **[Create template]** 클릭
2. 기본 정보 입력:

| 항목 | 입력값 |
|------|--------|
| **Template name** | `container-logs-template` |
| **Index patterns** | `container-logs-*` |
| **Priority** | `100` |

3. **Index settings** 탭에서 JSON 입력:

```json
{
  "index": {
    "number_of_shards": 2,
    "number_of_replicas": 1,
    "refresh_interval": "10s",
    "codec": "best_compression",
    "plugins": {
      "index_state_management": {
        "policy_id": "container-logs-policy"
      }
    }
  }
}
```

4. **Mappings** 탭에서 필드 매핑을 JSON으로 입력하거나, UI에서 개별 필드를 추가:

```json
{
  "properties": {
    "@timestamp": { "type": "date" },
    "cluster_name": { "type": "keyword" },
    "namespace": { "type": "keyword" },
    "pod_name": { "type": "keyword" },
    "container_name": { "type": "keyword" },
    "node_name": { "type": "keyword" },
    "level": { "type": "keyword" },
    "message": {
      "type": "text",
      "fields": {
        "keyword": { "type": "keyword", "ignore_above": 256 }
      }
    },
    "source_file": { "type": "keyword" },
    "stream": { "type": "keyword" },
    "loggerName": { "type": "keyword" },
    "thread": { "type": "keyword" }
  }
}
```

5. **[Create template]** 클릭

### 9-3. K8s Event / Systemd 템플릿

동일한 방법으로 나머지 2개 템플릿을 생성합니다. 상세 매핑은 [02-index-templates.md](./02-index-templates.md)를 참고하세요.

---

## 10. Dashboards UI에서 모니터링

### 10-1. 인덱스 상태 확인

**경로:** **Index Management** → **Indices**

| 컬럼 | 설명 |
|------|------|
| **Index** | 인덱스 이름 |
| **Health** | green/yellow/red |
| **Status** | open/close |
| **Managed by policy** | 적용된 ISM 정책 이름 |
| **Total size** | 인덱스 전체 크기 |
| **Primaries size** | Primary 샤드 크기 |
| **Total documents** | 문서 수 |

**필터링 팁:**
- 검색창에 `container-logs-` 입력하면 해당 인덱스만 필터링
- **Health** 컬럼 클릭으로 비정상 인덱스 먼저 정렬

### 10-2. ISM 정책 실행 상태 확인

**경로:** **Index Management** → **Policy managed indices**

| 컬럼 | 설명 |
|------|------|
| **Index** | 인덱스 이름 |
| **Policy** | 적용된 ISM 정책 |
| **State** | 현재 단계 (hot/warm/snapshot_to_s3/cold_s3/delete) |
| **Action** | 현재 실행 중인 액션 |
| **Started time** | 현재 단계 시작 시간 |
| **Info** | 상세 정보 (오류 시 에러 메시지) |

**실패한 정책 확인:**
- **Info** 컬럼에 빨간색 에러 아이콘이 표시된 인덱스를 찾습니다
- 해당 인덱스를 클릭하면 상세 에러 메시지와 재시도 정보가 표시됩니다

### 10-3. 스냅샷 현황 확인

**경로:** **Snapshot Management** → **Snapshots** 탭

| 컬럼 | 설명 |
|------|------|
| **Snapshot** | 스냅샷 이름 |
| **Status** | SUCCESS / IN_PROGRESS / FAILED / PARTIAL |
| **Repository** | 저장된 리포지토리 |
| **Start time** | 시작 시간 |
| **End time** | 종료 시간 |
| **Indices** | 포함된 인덱스 수 |

### 10-4. Dev Tools로 상세 모니터링

**경로:** **Management** → **Dev Tools**

자주 사용하는 모니터링 쿼리:

```
# 클러스터 전체 헬스
GET _cluster/health

# 인덱스별 크기 및 문서 수
GET _cat/indices/container-logs-*?v&s=index&h=index,health,docs.count,store.size

# ISM 정책 실행 상태 (특정 인덱스)
POST _plugins/_ism/explain/container-logs-bigdata-prod-2026.02.26

# ISM 정책 실행 상태 (전체)
POST _plugins/_ism/explain/container-logs-*

# 디스크 사용량
GET _cat/allocation?v&h=node,disk.used,disk.avail,disk.percent

# 스냅샷 리포지토리 상태
GET _snapshot/minio-s3-repo

# 전체 스냅샷 목록
GET _snapshot/minio-s3-repo/_all

# SM 정책 실행 상태
GET _plugins/_sm/policies/daily-container-logs-backup/_explain

# 노드별 샤드 분배
GET _cat/shards?v&h=index,shard,prirep,state,node&s=index
```

---

## 11. 트러블슈팅

### 11-1. ISM 정책이 snapshot 단계에서 실패하는 경우

**증상:** Policy managed indices에서 `snapshot_to_s3` 상태, Info에 에러 표시

**확인 방법:**
1. Dev Tools에서:
```
POST _plugins/_ism/explain/container-logs-bigdata-prod-2026.01.15
```

2. 일반적인 원인:

| 에러 메시지 | 원인 | 해결 |
|------------|------|------|
| `repository_missing_exception` | `minio-s3-repo` 미등록 | §3에서 리포지토리 재등록 |
| `repository_verification_exception` | MinIO 접근 불가 | MinIO 상태/자격증명 확인 |
| `snapshot_creation_exception` | 동일 스냅샷 이름 존재 | 기존 스냅샷 삭제 |
| `connect timed out` | endpoint에 프로토콜 포함 | `http://` 제거, `protocol: http` 별도 설정 |

3. 수동 재시도 (Dev Tools):
```
POST _plugins/_ism/retry/container-logs-bigdata-prod-2026.01.15
{
  "state": "snapshot_to_s3"
}
```

### 11-2. 인덱스가 Yellow 상태인 경우

**증상:** Indices 목록에서 Health가 yellow

**원인:** Replica 샤드를 할당할 노드 부족 (단일 노드 환경)

**해결 (Dev Tools):**
```
PUT container-logs-*/_settings
{
  "index.number_of_replicas": 0
}
```

또는 인덱스 템플릿의 replica를 0으로 수정:
1. **Index Management** → **Templates** → `container-logs-template` 클릭
2. **[Edit]** → Index settings에서 `number_of_replicas`를 `0`으로 변경
3. **[Save]**

> 기존 인덱스에는 영향 없음. 새로 생성되는 인덱스부터 적용됩니다.

### 11-3. MinIO 연결 실패

**확인 순서 (Dev Tools):**

```
# 1. 리포지토리 등록 확인
GET _snapshot/minio-s3-repo

# 2. 연결 검증
POST _snapshot/minio-s3-repo/_verify

# 3. MinIO Pod 상태 확인 (터미널)
# kubectl get pods -n logging -l app=minio
# kubectl logs -n logging -l app=minio --tail=20
```

**일반적인 MinIO 연결 문제:**

| 문제 | 원인 | 해결 |
|------|------|------|
| Connection refused | MinIO 미실행 | MinIO Pod 재시작 |
| Access Denied | 자격증명 오류 | Keystore 재설정 후 reload |
| Bucket not found | 버킷 미생성 | MinIO Console에서 버킷 생성 |
| Connect timed out | endpoint 형식 오류 | `http://` 제거 확인 |
| SSL handshake error | protocol 불일치 | `protocol: http` 확인 |

### 11-4. SM 정책이 실행되지 않는 경우

1. **SM Policies** 탭에서 해당 정책의 **Enabled** 상태 확인
2. 정책 이름 클릭 → **Last execution** 섹션에서 마지막 실행 결과 확인
3. Dev Tools에서 상세 확인:

```
GET _plugins/_sm/policies/daily-container-logs-backup/_explain
```

---

## 12. 전체 설정 순서 체크리스트

아래 순서대로 진행하면 ISM + MinIO S3 스냅샷 전체 설정이 완료됩니다.

### Phase 1: 인프라 사전 설정 (CLI)

- [ ] MinIO 배포 및 버킷 생성 (`opensearch-snapshots`)
- [ ] OpenSearch에 `repository-s3` 플러그인 설치 확인
- [ ] `opensearch.yml`에 MinIO S3 클라이언트 설정 추가
- [ ] Keystore에 MinIO 자격증명 등록
- [ ] `_nodes/reload_secure_settings` 실행

### Phase 2: 리포지토리 등록 (Dashboards Dev Tools)

- [ ] `minio-s3-repo` 스냅샷 리포지토리 등록 (`PUT _snapshot/minio-s3-repo`)
- [ ] `_verify` 로 연결 검증

### Phase 3: ISM 정책 생성 (Dashboards UI)

- [ ] `container-logs-policy` 생성 (Hot→Warm→Snapshot→Cold→Delete)
- [ ] `k8s-events-policy` 생성 (Hot→Warm→Delete)
- [ ] `systemd-logs-policy` 생성 (Hot→Warm→Archive→Delete)

### Phase 4: 인덱스 템플릿 생성 (Dashboards UI)

- [ ] `container-logs-template` 생성 (패턴: `container-logs-*`)
- [ ] `k8s-events-template` 생성 (패턴: `k8s-events-*`)
- [ ] `systemd-logs-template` 생성 (패턴: `systemd-logs-*`)

### Phase 5: SM 자동화 정책 생성 (Dashboards UI)

- [ ] `daily-container-logs-backup` SM 정책 생성
- [ ] `daily-k8s-events-backup` SM 정책 생성
- [ ] `daily-systemd-logs-backup` SM 정책 생성

### Phase 6: 기존 인덱스에 정책 적용 (Dashboards UI)

- [ ] `container-logs-*` 인덱스에 `container-logs-policy` 적용
- [ ] `k8s-events-*` 인덱스에 `k8s-events-policy` 적용
- [ ] `systemd-logs-*` 인덱스에 `systemd-logs-policy` 적용

### Phase 7: 검증

- [ ] ISM 정책 적용 확인 (Policy managed indices)
- [ ] 테스트 스냅샷 수동 생성/복원 테스트
- [ ] SM 정책 실행 확인 (다음날 새벽)
- [ ] MinIO에 스냅샷 데이터 저장 확인
