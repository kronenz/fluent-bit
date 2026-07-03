# OpenSearch Helm 차트에 Isilon NFS 스냅샷 리포지토리(path.repo) 마운트 가이드

| 항목 | 값 |
|---|---|
| Helm Chart | opensearch (opensearch-project/helm-charts) **2.32.0** |
| Image | opensearchproject/opensearch **2.19.1** |
| 목적 | Isilon NFS를 `fs` 타입 스냅샷 리포지토리로 사용 (ISM warm 티어) |
| 마운트 경로 | `/mnt/isilon-repo` (전 노드 동일 경로 필수) |

---

## 1. 개념 정리

**`opensearch.yml` 자체는 마운트를 수행하지 못한다.** 역할이 나뉜다:

- **Kubernetes (Helm values)**: NFS 볼륨을 Pod에 마운트 → `extraVolumes` + `extraVolumeMounts`
- **`opensearch.yml`**: 마운트된 경로를 스냅샷 저장소로 허용 → `path.repo`

즉 "opensearch.yml에서 Isilon path mount"는 불가능하지만, **Helm values에서 마운트 + opensearch.yml에서 path.repo 등록** 조합으로 목적을 달성한다. 두 설정 모두 opensearch 차트 2.32.0에서 지원하는 표준 values 키다.

```
[Isilon NFS export]
   └─ (방법 A) RWX PV/PVC ──┐
   └─ (방법 B) nfs 인라인 ──┼─ extraVolumes / extraVolumeMounts → Pod 내 /mnt/isilon-repo
                            │
config.opensearch.yml ──────┴─ path.repo: ["/mnt/isilon-repo"]
                                → PUT _snapshot/isilon-nfs-repo (type: fs)
```

## 2. 사전 준비 (Isilon 측)

1. NFS export 생성 (예: `/ifs/data/opensearch-repo`)
2. **클라이언트 허용**: K8s 워커 노드 IP 대역 등록
3. **권한**: OpenSearch 컨테이너는 uid/gid **1000**으로 동작한다. 다음 중 하나 적용:
   - export 디렉터리 소유자를 `1000:1000`으로 변경 (권장)
   - Isilon export 옵션에서 `map root` / run-as-root 매핑 조정
4. 마운트 테스트 (워커 노드에서):
   ```bash
   mount -t nfs -o vers=3 <isilon-smartconnect-fqdn>:/ifs/data/opensearch-repo /mnt/test
   touch /mnt/test/probe && rm /mnt/test/probe
   ```

## 3. 방법 A (권장): RWX PV/PVC + extraVolumes

정적 NFS PV를 만들어 PVC로 바인딩한다. 재사용성과 관리성이 좋고, Dell CSI PowerScale 드라이버가 있다면 StorageClass 동적 프로비저닝으로 대체 가능하다.

### 3-1. PV / PVC 매니페스트

```yaml
# isilon-repo-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opensearch-isilon-repo-pv
spec:
  capacity:
    storage: 500Gi              # NFS라 명목상 값
  accessModes:
    - ReadWriteMany             # 3개 Pod 동시 마운트 필수
  persistentVolumeReclaimPolicy: Retain
  mountOptions:
    - vers=3
    - nolock                    # Isilon NLM 이슈 회피 (스냅샷 저장 용도에는 안전)
    - hard
    - timeo=600
  nfs:
    server: isilon.example.internal      # SmartConnect FQDN 권장
    path: /ifs/data/opensearch-repo
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: opensearch-isilon-repo-pvc
  namespace: opensearch          # OpenSearch 설치 네임스페이스
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""           # 정적 바인딩
  volumeName: opensearch-isilon-repo-pv
  resources:
    requests:
      storage: 500Gi
```

```bash
kubectl apply -f isilon-repo-pv.yaml
kubectl -n opensearch get pvc opensearch-isilon-repo-pvc   # Bound 확인
```

### 3-2. values.yaml (핵심 부분)

```yaml
# values.yaml — opensearch chart 2.32.0 / image 2.19.1
clusterName: "opensearch-cluster"
nodeGroup: "master"              # 단일 nodeGroup(3노드 통합 역할) 구성 기준

replicas: 3

image:
  repository: opensearchproject/opensearch
  tag: "2.19.1"

# 통합 역할 (현재 구성 유지). warm remote_snapshot 검색까지 원하면 search 추가
roles:
  - master
  - data
  - ingest
  # - search                    # (선택) searchable snapshot 사용 시

# ── ① opensearch.yml: path.repo 등록 ──────────────────────────
config:
  opensearch.yml: |
    cluster.name: opensearch-cluster
    network.host: 0.0.0.0

    # Isilon NFS 스냅샷 리포지토리 허용 경로
    path.repo: ["/mnt/isilon-repo"]

    # (선택) search 롤 사용 시 remote_snapshot 캐시
    # node.search.cache.size: 10gb

    plugins.security.ssl.transport.enforce_hostname_verification: false
    # ...기존 보안/기타 설정 유지...

# ── ② NFS 볼륨 마운트 ─────────────────────────────────────────
extraVolumes:
  - name: isilon-repo
    persistentVolumeClaim:
      claimName: opensearch-isilon-repo-pvc

extraVolumeMounts:
  - name: isilon-repo
    mountPath: /mnt/isilon-repo
    # readOnly 지정 금지 — 스냅샷 쓰기 필요

# ── ③ hot 데이터용 기존 local-path PVC는 그대로 유지 ─────────
persistence:
  enabled: true
  storageClass: "local-path"
  accessModes:
    - ReadWriteOnce
  size: 100Gi

# ── ④ NFS 파일 소유권 정합 (차트 기본값이지만 명시) ──────────
podSecurityContext:
  fsGroup: 1000
  runAsUser: 1000

securityContext:
  runAsNonRoot: true
  runAsUser: 1000
```

## 4. 방법 B (간단): NFS 인라인 볼륨

PV/PVC 없이 Pod 스펙에 NFS를 직접 선언한다. 개발 환경에서 빠르게 검증할 때 유용하다. `extraVolumes`만 다르고 나머지는 방법 A와 동일하다.

```yaml
extraVolumes:
  - name: isilon-repo
    nfs:
      server: isilon.example.internal
      path: /ifs/data/opensearch-repo
      readOnly: false

extraVolumeMounts:
  - name: isilon-repo
    mountPath: /mnt/isilon-repo
```

> 주의: 인라인 방식은 `mountOptions`(vers, nolock 등)를 지정할 수 없다. NFSv3 옵션 제어가 필요하면 방법 A를 사용할 것.

## 5. 적용 및 검증

### 5-1. Helm 업그레이드 (롤링 재기동 발생)

```bash
helm upgrade opensearch opensearch/opensearch \
  -n opensearch \
  --version 2.32.0 \
  -f values.yaml

# StatefulSet 롤링 상태 확인 — 반드시 한 노드씩 green 복귀 후 진행되는지 관찰
kubectl -n opensearch rollout status statefulset/opensearch-cluster-master
```

> `path.repo`는 정적 설정이라 **재기동이 필요**하다. 3노드 클러스터이므로 quorum 유지(동시 2대 다운 금지)에 유의. 지난 장애 재발 방지를 위해 업그레이드 전 `GET _cluster/health`가 green이고 hot 인덱스 replica가 1 이상인지 먼저 확인할 것.

### 5-2. 마운트 확인

```bash
kubectl -n opensearch exec opensearch-cluster-master-0 -- df -h /mnt/isilon-repo
kubectl -n opensearch exec opensearch-cluster-master-0 -- touch /mnt/isilon-repo/.probe
kubectl -n opensearch exec opensearch-cluster-master-1 -- ls -la /mnt/isilon-repo/.probe   # 교차 확인
kubectl -n opensearch exec opensearch-cluster-master-0 -- rm /mnt/isilon-repo/.probe
```

Pod 0에서 만든 파일이 Pod 1에서 보여야 정상(RWX 공유 확인).

### 5-3. 리포지토리 등록 (Dev Tools)

```json
PUT _snapshot/isilon-nfs-repo
{
  "type": "fs",
  "settings": {
    "location": "/mnt/isilon-repo",
    "compress": true,
    "chunk_size": "1gb"
  }
}

POST _snapshot/isilon-nfs-repo/_verify
```

`_verify`가 3개 노드 모두 성공을 반환해야 한다. 실패 노드가 있으면 해당 Pod의 마운트/권한을 재확인.

### 5-4. 수동 스냅샷 테스트

```json
PUT _snapshot/isilon-nfs-repo/test-snapshot?wait_for_completion=true
{
  "indices": "icdataops-dev-log-2026.07.02-000182",
  "include_global_state": false
}

GET _snapshot/isilon-nfs-repo/test-snapshot

DELETE _snapshot/isilon-nfs-repo/test-snapshot
```

## 6. ISM 정책: hot 1d (local PVC) → warm 5d (Isilon NFS) → cold 30d (MinIO S3)

**결론: 가능하다.** 단, ISM의 티어 의미를 정확히 이해하고 구성해야 한다.

### 6-1. 동작 방식 (중요)

ISM에는 Elasticsearch ILM의 `searchable_snapshot`처럼 "인덱스를 통째로 다른 스토리지로 이동"하는 액션이 없다. 따라서 아래 의미로 구현된다:

| 티어 | 기간 (인덱스 나이) | 데이터 위치 | 상태 |
|---|---|---|---|
| hot | 0 ~ 1d | local-path PVC | write index, 색인+검색 |
| warm | 1d ~ 6d | local-path PVC + **Isilon 스냅샷 백업** | 읽기 검색 가능, 로컬 유지 |
| cold | 6d ~ 30d | **MinIO S3 스냅샷만** (로컬 삭제) | 즉시 검색 불가, 필요 시 복원 |
| 만료 | 30d | 스냅샷 정리 (SM 정책) | - |

- `min_index_age`는 **인덱스 생성 시점 기준 누적 나이**다. warm 5일 유지 = warm→cold 전환 조건 `6d` (hot 1d + warm 5d).
- warm에서 로컬까지 지우고 Isilon만으로 검색하려면 search 롤 + `remote_snapshot` 복원이 필요한데, 이 복원 단계는 ISM이 자동화하지 못한다(외부 스크립트 필요). 아래 정책은 운영 부담이 없는 **로컬 유지 + Isilon 백업** 방식이다.

### 6-2. 전체 ISM 정책 JSON

```json
PUT _plugins/_ism/policies/icdataops-dev-log-policy
{
  "policy": {
    "description": "hot 1d(local) -> warm 5d(Isilon NFS snapshot) -> cold(S3) -> delete 30d",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["icdataops-dev-log*"],
        "priority": 100
      }
    ],
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_index_age": "1d",
              "min_primary_shard_size": "30gb"
            }
          }
        ],
        "transitions": [
          { "state_name": "warm", "conditions": { "min_index_age": "1d" } }
        ]
      },
      {
        "name": "warm",
        "actions": [
          { "index_priority": { "priority": 50 } },
          { "force_merge": { "max_num_segments": 1 } },
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "snapshot": {
              "repository": "isilon-nfs-repo",
              "snapshot": "icdataops-dev-log-warm"
            }
          }
        ],
        "transitions": [
          { "state_name": "cold", "conditions": { "min_index_age": "6d" } }
        ]
      },
      {
        "name": "cold",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "snapshot": {
              "repository": "minio-s3-repo",
              "snapshot": "icdataops-dev-log-cold"
            }
          },
          { "delete": {} }
        ],
        "transitions": []
      }
    ]
  }
}
```

포인트:

- **warm→cold 전환은 `6d`** (hot 1d + warm 5d 누적). "warm 5d"를 `5d`로 넣으면 warm이 4일밖에 안 된다.
- cold state에서 **S3 스냅샷 성공 후 로컬 인덱스를 delete** 한다. ISM은 state 내 액션을 순서대로 실행하며 snapshot이 실패하면 delete로 진행하지 않으므로 데이터 유실 없이 안전하다. `retry`로 NFS/S3 일시 장애에 대비한다.
- ISM은 스냅샷 이름 뒤에 타임스탬프를 자동으로 붙여 충돌을 방지한다.
- 로컬 인덱스가 6일이면 삭제되므로 **"30d까지 보관"의 실체는 MinIO 스냅샷**이다. 30일 보존/만료는 인덱스 정책이 아니라 아래 SM(Snapshot Management) 정책이 담당한다.

### 6-3. 스냅샷 30일 보존/정리 (SM 정책)

cold 스냅샷을 30일 뒤 자동 삭제:

```json
POST _plugins/_sm/policies/icdataops-cold-retention
{
  "description": "MinIO cold snapshot 30d retention",
  "creation": {
    "schedule": { "cron": { "expression": "0 2 * * *", "timezone": "Asia/Seoul" } }
  },
  "deletion": {
    "schedule": { "cron": { "expression": "0 3 * * *", "timezone": "Asia/Seoul" } },
    "condition": {
      "max_age": "30d",
      "min_count": 1
    }
  },
  "snapshot_config": {
    "repository": "minio-s3-repo",
    "indices": "icdataops-dev-log*",
    "ignore_unavailable": true,
    "include_global_state": false
  }
}
```

Isilon warm 스냅샷도 무한히 쌓이므로 동일한 방식으로 `isilon-nfs-repo`에 대해 `max_age: 7d` 정도의 SM 정책을 하나 더 만들어 정리한다. (SM의 creation과 ISM의 snapshot 액션이 겹치는 게 싫다면, deletion 스케줄만 활용하거나 creation cron을 sm 스냅샷 전용 이름으로 분리해 운영한다.)

### 6-4. 기존 인덱스에 적용

```json
# 신규 인덱스는 ism_template로 자동 적용. 기존 인덱스는 수동 연결:
POST _plugins/_ism/add/icdataops-dev-log*
{ "policy_id": "icdataops-dev-log-policy" }

# 이미 다른 정책이 붙어있으면:
POST _plugins/_ism/change_policy/icdataops-dev-log*
{
  "policy_id": "icdataops-dev-log-policy",
  "include": [{ "state": "hot" }]
}
```

주의: 기존 AS-IS 정책(hot 3d → cold)에서 넘어올 때, 이미 나이가 6d를 넘은 인덱스는 정책 적용 즉시 cold state로 진입해 **S3 스냅샷 후 로컬에서 삭제**된다. 의도한 동작인지 사전에 대상 인덱스 목록을 확인할 것:

```text
GET _cat/indices/icdataops-dev-log*?v&h=index,creation.date.string,store.size&s=creation.date
```

### 6-5. cold 데이터 조회가 필요할 때 (복원)

```json
# 일반 복원 (로컬 디스크로)
POST _snapshot/minio-s3-repo/<스냅샷명>/_restore
{
  "indices": "icdataops-dev-log-2026.06.25-000176",
  "rename_pattern": "(.+)",
  "rename_replacement": "restored-$1"
}

# 디스크 절약형 (search 롤 구성 시): 데이터를 S3에 둔 채 검색
POST _snapshot/minio-s3-repo/<스냅샷명>/_restore
{
  "indices": "icdataops-dev-log-2026.06.25-000176",
  "storage_type": "remote_snapshot",
  "rename_pattern": "(.+)",
  "rename_replacement": "remote-$1"
}
```

### 6-6. 정책 동작 검증

```text
GET _plugins/_ism/explain/icdataops-dev-log*?pretty&size=30
```

각 인덱스의 `state`가 나이에 맞게 hot/warm/cold로 배치되는지, `step_status: failed`나 `retry_count` 증가가 없는지 확인한다. ISM 기본 실행 주기(5분) 때문에 전환 반영에 수 분이 걸릴 수 있다.

## 7. 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| Pod가 `ContainerCreating`에서 멈춤 | NFS 마운트 실패. 워커 노드에 `nfs-common`(Ubuntu) 설치 여부, Isilon export 클라이언트 허용 IP 확인 |
| `_verify` 시 `access_denied` / `repository_verification_exception` | export 디렉터리 권한. uid 1000 쓰기 가능해야 함. Isilon에서 `chown 1000:1000` 또는 매핑 조정 |
| 일부 노드만 verify 실패 | 해당 Pod가 뜬 워커 노드의 NFS 접근 불가 (방화벽/export 허용 목록) |
| `doesn't match any of the locations specified by path.repo` | `path.repo` 미반영. Pod 재기동 여부와 `config.opensearch.yml` 렌더링 확인: `kubectl exec ... -- grep path.repo /usr/share/opensearch/config/opensearch.yml` |
| 스냅샷 속도 저하 | NFSv3 `mountOptions` 튜닝(`rsize`/`wsize` 1MB), Isilon SmartConnect로 노드 분산 |
| stale file handle | Isilon 측 export 변경/이동 발생. Pod 재기동으로 재마운트 |

## 8. 요약 체크리스트

1. Isilon export 생성 + uid 1000 쓰기 권한 + 워커 노드 IP 허용
2. RWX PV/PVC 생성 (방법 A) 또는 nfs 인라인 (방법 B)
3. values.yaml: `extraVolumes`/`extraVolumeMounts` + `config.opensearch.yml`의 `path.repo`
4. `helm upgrade` → 롤링 재기동 (green 유지 확인)
5. 마운트 교차 확인 → `PUT _snapshot/isilon-nfs-repo` 등록 → `_verify` → 테스트 스냅샷
6. ISM 정책 등록: hot(rollover 1d) → warm 6d 전환(Isilon snapshot) → cold(S3 snapshot + 로컬 delete)
7. SM 정책: MinIO cold 스냅샷 30d 보존/정리, Isilon warm 스냅샷 7d 정리
8. 기존 인덱스 `_ism/add` 적용 전, 나이 6d 초과 인덱스의 즉시 cold 진입 영향 확인
9. `_ism/explain`으로 state 배치와 failed 여부 검증
