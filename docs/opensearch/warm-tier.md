# OpenSearch warm 노드 티어링 구성 가이드 — hot(local) / warm(Isilon PVC 전용 노드, read_only)

| 항목 | 값 |
|---|---|
| Helm Chart / Image | opensearch 2.32.0 / opensearchproject/opensearch 2.19.1 |
| hot 노드 | 기존 3노드 — master/ingest/data/remote_cluster_client · local-path PVC 250GB · `node.attr.temp: hot` |
| warm 노드 | **신규 2노드** — data 전용 · **Isilon NFS PVC** (16TB 활용) · `node.attr.temp: warm` |
| 수명 주기 | hot 0~1d (write) → warm 1~30d (read_only, warm 노드로 샤드 이동) → 30d delete |
| 자동화 | **ISM 정책 하나로 완결 — CronJob 불필요** |
| 조회 | hot+warm 30일 전체가 항상 열려있는 인덱스 → Discover 즉시 조회 |

> 수명 주기는 hot → warm → (30d) delete 로 구성한다. warm에서 hot으로 되돌아가는 단계는 없으며, 과거 데이터 재색인이 필요하면 수동으로 처리한다.

---

## 1. 아키텍처 개요

remote_snapshot 방식과 달리, 인덱스를 스냅샷으로 변환하지 않고 **샤드가 배치되는 노드만 바꾸는** 정통 hot/warm 노드 티어링이다.

```
[hot 0~1d]     hot 노드(×3, local-path) 에 샤드 배치 · write
     │ rollover(1d 또는 10gb) 후 1h → ISM warm state
     ▼
[warm 전환]    ISM: ① read_only  ② force_merge
                    ③ allocation require temp=warm → 샤드가 warm 노드로 이동
     ▼
[warm 1~30d]   warm 노드(×2, Isilon NFS PVC) 상주 · 읽기전용 · Discover 즉시 조회
     │ 30d
     ▼
[delete]       ISM delete
```

**장점**: CronJob·search 롤·캐시·`-r` 인덱스·복원 로직 전부 불필요. ISM `allocation` 액션만으로 전 과정 자동화. 인덱스가 항상 정식 인덱스로 존재해 조회가 자연스럽다.

**대가와 완화**: warm 데이터가 Lucene-on-NFS로 구동된다. 아래 3종 완화책을 본 가이드에 반영했다:

| 리스크 | 완화 |
|---|---|
| mmap ↔ NFS 궁합 (성능/안정성) | 인덱스 `index.store.type: niofs` (템플릿에서 생성 시점 지정) |
| NFS 파일 락 이슈 | warm 진입 즉시 `read_only` — 쓰기 경로 자체를 차단, NFSv3 `nolock` 마운트 |
| warm 노드/Isilon 장애 시 데이터 유실 | warm 노드 2대 + replica 1 유지, (선택) 주 1회 S3 스냅샷 백업 |

## 2. Isilon PVC 준비

warm 노드는 StatefulSet volumeClaimTemplate로 PVC를 만들므로 두 방법 중 하나:

**방법 A (권장) — Dell CSI PowerScale StorageClass**: 동적 프로비저닝. StorageClass 이름만 values에 지정하면 끝.

```yaml
# 예: csi-powerscale 설치 후
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: isilon-nfs
provisioner: csi-isilon.dellemc.com
parameters:
  AccessZone: System
  IsiPath: /ifs/data/opensearch-warm
reclaimPolicy: Retain
```

**방법 B — 정적 NFS PV 사전 생성**: warm Pod 수만큼 PV를 만들어 두면 volumeClaimTemplate이 바인딩한다. `storageClassName`을 임의 이름(예: `isilon-nfs`)으로 통일하고, PV마다 Isilon 하위 경로를 다르게 지정(노드 간 데이터 경로 분리 필수):

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: warm-data-0
spec:
  capacity: { storage: 8Ti }
  accessModes: [ ReadWriteOnce ]
  storageClassName: isilon-nfs
  persistentVolumeReclaimPolicy: Retain
  mountOptions: [ "vers=3", "nolock", "hard", "timeo=600", "rsize=1048576", "wsize=1048576" ]
  nfs:
    server: isilon.example.internal
    path: /ifs/data/opensearch-warm/node-0     # node-1은 별도 경로
```

> ⚠ 두 warm 노드가 같은 NFS 경로를 데이터 디렉터리로 공유하면 안 된다. 반드시 노드별 경로 분리.
> Isilon export는 uid 1000 쓰기 가능해야 한다 (`chown 1000:1000`).

## 3. Helm 구성 — nodeGroup 2개

opensearch 차트는 `nodeGroup`을 달리해 같은 클러스터에 여러 StatefulSet을 배포하는 구조를 공식 지원한다. **release 2개**로 설치한다.

### 3-1. hot values (기존 release 수정) — `values-hot.yaml`

```yaml
clusterName: "opensearch-cluster"
nodeGroup: "master"                  # 기존 nodeGroup 이름 유지
replicas: 3

image:
  repository: opensearchproject/opensearch
  tag: "2.19.1"

roles:
  - master
  - ingest
  - data
  - remote_cluster_client

config:
  opensearch.yml: |
    cluster.name: opensearch-cluster
    network.host: 0.0.0.0
    node.attr.temp: hot              # ★ 추가 (재기동 필요)
    # ...기존 보안/기타 설정 유지...

persistence:
  enabled: true
  storageClass: "local-path"
  accessModes: [ ReadWriteOnce ]
  size: 250Gi
```

### 3-2. warm values (신규 release) — `values-warm.yaml`

```yaml
clusterName: "opensearch-cluster"    # 동일 클러스터명 = 같은 클러스터 조인
nodeGroup: "warm"
replicas: 2

image:
  repository: opensearchproject/opensearch
  tag: "2.19.1"

roles:
  - data                             # data 전용 (master 아님 — quorum은 기존 3노드)

# 기존 마스터 노드그룹의 discovery 서비스 지정 (필수)
masterService: "opensearch-cluster-master"

config:
  opensearch.yml: |
    cluster.name: opensearch-cluster
    network.host: 0.0.0.0
    node.attr.temp: warm             # ★
    # 보안 인증서/설정은 hot과 동일하게 (같은 클러스터이므로)

persistence:
  enabled: true
  storageClass: "isilon-nfs"         # 2장에서 준비한 StorageClass
  accessModes: [ ReadWriteOnce ]
  size: 6Ti

# 검색 위주라 리소스는 hot보다 가볍게 시작 가능
resources:
  requests: { cpu: "1", memory: 4Gi }
  limits:   { cpu: "2", memory: 8Gi }
opensearchJavaOpts: "-Xms2g -Xmx2g"
```

### 3-3. 배포

```bash
# hot: node.attr 추가 반영 (롤링 재기동 — green + replica 확인 후)
helm upgrade opensearch opensearch/opensearch -n opensearch --version 2.32.0 -f values-hot.yaml

# warm: 신규 release
helm install opensearch-warm opensearch/opensearch -n opensearch --version 2.32.0 -f values-warm.yaml

# 5노드 조인 + temp 속성 확인
# GET _cat/nodes?v&h=name,node.role,attr.temp   ← Dev Tools
kubectl -n opensearch get pods -l app.kubernetes.io/instance=opensearch-warm
```

## 4. 인덱스 템플릿 — 신규 인덱스는 hot 노드에서 niofs로 생성

`index.store.type`은 생성 시점에만 지정 가능하므로 템플릿에 넣는다. niofs는 mmap을 쓰지 않아 NFS 위에서 안전하며, 로그 워크로드의 hot 구간 성능 영향은 미미하다.

```json
PUT _index_template/icdataops-dev-log-template
{
  "index_patterns": ["icdataops-dev-log-*"],
  "priority": 200,
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1,
      "index.store.type": "niofs",
      "index.routing.allocation.require.temp": "hot",
      "plugins.index_state_management.rollover_alias": "icdataops-dev-log"
    }
  }
}
```

- `require.temp: hot` — 신규(write) 인덱스가 반드시 hot 노드에 생성되도록 고정. warm 전환 시 ISM allocation이 이 값을 `warm`으로 바꾼다.
- 기존 인덱스는 store.type을 바꿀 수 없으므로 rollover로 자연 교체될 때까지 mmap 기반으로 남는다. 그 인덱스들은 warm 이동을 보류(6-3 참조)하거나 감수하고 이동.

## 5. ISM 정책 — 단일 정책으로 완결

```json
PUT _plugins/_ism/policies/icdataops-dev-log-policy
{
  "policy": {
    "description": "hot 1d/10gb (local, hot nodes) -> warm 30d (read_only, Isilon warm nodes) -> delete",
    "default_state": "hot",
    "ism_template": [
      { "index_patterns": ["icdataops-dev-log-*"], "priority": 100 }
    ],
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_index_age": "1d",
              "min_primary_shard_size": "10gb"
            }
          }
        ],
        "transitions": [
          { "state_name": "warm", "conditions": { "min_rollover_age": "1h" } }
        ]
      },
      {
        "name": "warm",
        "actions": [
          { "read_only": {} },
          { "force_merge": { "max_num_segments": 1 } },
          { "index_priority": { "priority": 20 } },
          {
            "retry": { "count": 5, "backoff": "exponential", "delay": "10m" },
            "allocation": { "require": { "temp": "warm" } }
          }
        ],
        "transitions": [
          { "state_name": "delete", "conditions": { "min_index_age": "30d" } }
        ]
      },
      {
        "name": "delete",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "delete": {}
          }
        ]
      }
    ]
  }
}
```

- 액션 순서가 중요하다: **read_only → force_merge를 hot 노드(로컬 디스크)에서 끝낸 뒤** allocation으로 이동한다. 병합된 세그먼트가 NFS로 한 번만 복사되고, NFS 위에서 무거운 merge I/O가 발생하지 않는다.
- replica 1 유지 → 프라이머리/레플리카가 warm 2노드에 분산되어 노드 1대 장애에도 조회 지속.
- warm 노드를 1대만 운영하려면 warm actions에 `{ "replica_count": { "number_of_replicas": 0 } }`를 read_only 다음에 추가 (장애 시 warm 조회 불가 감수, 6-4 백업 권장).

## 6. 운영 설정

### 6-1. 기존 인덱스 정책 적용

```text
POST _plugins/_ism/change_policy/icdataops-dev-log-*
{
  "policy_id": "icdataops-dev-log-policy",
  "include": [{ "state": "hot" }, { "state": "warm" }]
}
```

### 6-2. 검증

```text
GET _cat/nodes?v&h=name,node.role,attr.temp          # warm 2노드 + temp 속성
GET _plugins/_ism/explain/icdataops-dev-log-*?pretty&size=30
GET _cat/shards/icdataops-dev-log-*?v&h=index,shard,prirep,state,node&s=index
#   → 1d 지난 인덱스의 샤드가 opensearch-cluster-warm-* 노드에 있는지
GET _cat/allocation?v                                 # hot 노드 디스크 회수 확인
```

Discover: 패턴 `icdataops-dev-log-*`, 시간 범위 30일 — hot/warm 구분 없이 단일 결과.

### 6-3. 기존(mmap) 인덱스 처리

템플릿 적용 전에 만들어진 인덱스는 niofs가 아니다. 선택지:
- 그대로 warm 이동 (dev 로그 + read_only라 리스크 제한적) — 기본 권장
- 민감하면 해당 인덱스만 warm 전환을 지연: `POST _plugins/_ism/remove/<index>` 후 로컬에서 수명 만료

### 6-4. (선택) 유실 대비 백업 — SM 주 1회 S3 스냅샷

warm이 Isilon 유일본이 되는 게 부담스러우면 느슨한 백업만 유지:

```json
POST _plugins/_sm/policies/icdataops-weekly-backup
{
  "description": "weekly S3 backup of log indices",
  "creation": { "schedule": { "cron": { "expression": "0 3 * * 0", "timezone": "Asia/Seoul" } } },
  "deletion": {
    "schedule": { "cron": { "expression": "0 4 * * 0", "timezone": "Asia/Seoul" } },
    "condition": { "max_age": "35d", "min_count": 2 }
  },
  "snapshot_config": {
    "repository": "minio-s3-repo",
    "indices": "icdataops-dev-log*",
    "include_global_state": false,
    "ignore_unavailable": true
  }
}
```

### 6-5. 용량/성능 참고

- warm 30일치: 일 ~10GB × 30d × 2(replica) = ~600GB — 16TB의 4%, 매우 여유
- 일일 hot→warm 이동 트래픽: ~10-20GB (force_merge 후) — NFS 쓰기로 무리 없음
- warm 검색: niofs + NFS read라 로컬보다 느리지만, read_only·병합 완료 상태라 세그먼트 수가 적어 로그 조회 용도로는 충분

## 7. 트러블슈팅

| 증상 | 조치 |
|---|---|
| warm Pod가 클러스터 미조인 | `masterService` 값, 보안 인증서 동일 여부, `cluster.name` 일치 확인 |
| allocation 후 샤드 UNASSIGNED | `_cluster/allocation/explain` — warm 노드 디스크 워터마크, PV 바인딩, temp 속성 오타 확인 |
| warm 전환이 안 됨 (`step_status: failed`) | `_ism/explain` 상세 — allocation retry 소진 시 `POST _plugins/_ism/retry/<index>` |
| warm 검색이 비정상적으로 느림 | 해당 인덱스 `index.store.type` 확인 (mmapfs면 구인덱스) · NFS rsize/wsize 튜닝 · Isilon 부하 |
| warm 노드 재기동 후 샤드 복구 지연 | NFS 재마운트/stale handle — Pod 재기동, PV 상태 확인 |
| hot 노드에 warm 샤드가 남아있음 | replica가 warm 노드 수보다 많음 (2노드에 replica 1까지만) 또는 warm 디스크 부족 |

## 8. 적용 순서 요약

1. Isilon export + StorageClass(또는 정적 PV 2개) 준비
2. hot values에 `node.attr.temp: hot` 추가 → `helm upgrade` (롤링, green 확인)
3. `helm install opensearch-warm` (warm nodeGroup 2노드) → 5노드 조인 확인
4. 인덱스 템플릿 갱신 (niofs + require.temp: hot + rollover_alias)
5. ISM 정책 등록 → 신규 rollover 인덱스부터 자동 적용
6. 기존 인덱스 change_policy (오래된 것부터 소량씩 — 일제히 warm 이동 시 NFS 쓰기 몰림)
7. 1~2일 관찰: 샤드 배치, hot 디스크 회수, Discover 30일 조회, `_ism/explain` failed 여부
