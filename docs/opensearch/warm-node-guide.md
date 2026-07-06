# OpenSearch 티어링 최종 구성 가이드 — warm을 Isilon NFS에서 직접 검색 (remote_snapshot)

| 항목 | 값 |
|---|---|
| Helm Chart / Image | opensearch 2.32.0 / opensearchproject/opensearch 2.19.1 |
| 구성 | 3노드 StatefulSet (master+data+ingest+**search** 통합) |
| hot | 0~1d · local-path PVC (250GB) · rollover 1d + 10gb |
| warm | 1~6d · **Isilon NFS에 데이터 상주, remote_snapshot으로 검색** (로컬 삭제) |
| cold | 6~30d · MinIO S3 스냅샷만 보관 (검색 불가, 필요 시 복원) |
| 만료 | 30d · SM 정책으로 스냅샷 삭제 |

## 1. 아키텍처 개요

**목표: 로컬 250GB에는 hot 1일치 + 검색 캐시만 두고, warm 5일치는 Isilon에 두되 Discover에서 즉시 조회 가능하게 한다.**

```
[hot 0~1d]      local-path PVC ─ write/검색 (rollover: 1d 또는 10gb)
      │ rollover 후 1h
      ▼
[warm 진입]     ISM: force_merge → snapshot@Isilon → snapshot@S3(cold 선확보)
      │
      ▼         CronJob(자동화 스크립트):
[warm 1~6d]     remote_snapshot 복원(-r 인덱스, 데이터는 Isilon 상주)
                → 로컬 원본 delete → 디스크 회수
                → Discover는 -r 인덱스로 계속 조회 (읽기전용)
      │ 6d
      ▼
[cold 6~30d]    ISM(-r 정책): remote 인덱스 delete
                → S3 스냅샷만 남음 (조회 필요 시 restore)
      │ 30d
      ▼
[만료]          SM 정책: S3 스냅샷 삭제 / Isilon 스냅샷은 7d 정리
```

핵심 포인트 세 가지:

1. **cold용 S3 스냅샷은 warm 진입 시(로컬 원본이 있을 때) 미리 뜬다.** remote_snapshot 인덱스는 재스냅샷 대상이 될 수 없으므로, 원본이 로컬에 있는 동안 Isilon·S3 두 곳에 스냅샷을 확보한 뒤 로컬을 지운다. snapshot 성공 전에는 delete가 실행되지 않아 유실이 없다.
2. **remote_snapshot 복원 단계는 ISM이 자동화하지 못한다** (restore 액션 부재). 이 단계만 CronJob이 담당한다 (4장).
3. Discover 인덱스 패턴 `icdataops-dev-log-*`는 remote 인덱스(`...-r`)도 매칭하므로 사용자는 hot/warm 구분 없이 최근 6~7일을 조회한다.

## 2. Helm values.yaml

```yaml
# opensearch chart 2.32.0 / image 2.19.1
clusterName: "opensearch-cluster"
nodeGroup: "master"
replicas: 3

image:
  repository: opensearchproject/opensearch
  tag: "2.19.1"

# ── search 롤 추가 (remote_snapshot 검색에 필수) ──
roles:
  - master
  - data
  - ingest
  - search

config:
  opensearch.yml: |
    cluster.name: opensearch-cluster
    network.host: 0.0.0.0

    # Isilon NFS 스냅샷 리포지토리 경로 허용
    path.repo: ["/mnt/isilon-repo"]

    # remote_snapshot 검색 캐시 (local-path에서 할애, 필수)
    node.search.cache.size: 20gb

    # ...기존 보안/기타 설정 유지...

# ── Isilon NFS 마운트 (RWX PVC 방식 권장) ──
extraVolumes:
  - name: isilon-repo
    persistentVolumeClaim:
      claimName: opensearch-isilon-repo-pvc   # RWX, NFS PV 바인딩
extraVolumeMounts:
  - name: isilon-repo
    mountPath: /mnt/isilon-repo

# ── hot 데이터: 기존 local-path 유지 ──
persistence:
  enabled: true
  storageClass: "local-path"
  accessModes: [ ReadWriteOnce ]
  size: 250Gi

podSecurityContext:
  fsGroup: 1000
  runAsUser: 1000
```

> RWX PV/PVC 매니페스트, Isilon export 권한(uid 1000), NFSv3 mountOptions는 기존 가이드(opensearch-helm-isilon-nfs-guide.md) 2~3장과 동일. `node.search.cache.size`만큼 로컬 디스크가 상시 점유되므로 hot 용량 계산에 반영할 것 (250GB − 20GB 캐시 − 여유분).

적용:

```bash
helm upgrade opensearch opensearch/opensearch -n opensearch --version 2.32.0 -f values.yaml
kubectl -n opensearch rollout status statefulset/opensearch-cluster-master
```

## 3. 리포지토리 및 ISM / SM 설정

### 3-1. 리포지토리 등록

```json
PUT _snapshot/isilon-nfs-repo
{ "type": "fs", "settings": { "location": "/mnt/isilon-repo", "compress": true } }

POST _snapshot/isilon-nfs-repo/_verify

# minio-s3-repo는 기존 등록 유지, 검증만
POST _snapshot/minio-s3-repo/_verify
```

### 3-2. 기본 ISM 정책 (로컬 인덱스용)

hot에서 rollover하고, warm 진입 시 Isilon(warm 검색용)과 S3(cold 보관용) 스냅샷을 모두 확보한다. 로컬 삭제는 ISM이 아니라 CronJob이 remote 복원 성공을 확인한 뒤 수행한다.

```json
PUT _plugins/_ism/policies/icdataops-dev-log-policy
{
  "policy": {
    "description": "hot 1d/10gb local -> warm: snapshot to Isilon+S3 (restore/delete는 CronJob)",
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
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "snapshot": {
              "repository": "isilon-nfs-repo",
              "snapshot": "warm-icdataops-dev-log"
            }
          },
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "10m" },
            "snapshot": {
              "repository": "minio-s3-repo",
              "snapshot": "cold-icdataops-dev-log"
            }
          }
        ],
        "transitions": []
      }
    ]
  }
}
```

- `min_rollover_age: 1h` — 1d든 10gb든 rollover가 끝난 인덱스를 1시간 뒤 warm으로. 크기 기반 rollover와 궁합이 맞는 조건.
- warm state에 `transitions`가 없다 — 로컬 원본의 마지막 상태는 "두 스냅샷 완료"이고, 이후 삭제는 CronJob 몫이다.
- 스냅샷 이름에 ISM이 타임스탬프를 자동으로 붙인다.

### 3-3. remote 인덱스용 ISM 정책 (`-r` 패턴)

CronJob이 복원한 remote 인덱스는 6d(생성 시점 기준, 복원 시 원본 creation_date가 보존됨)에 삭제한다. priority를 높여 기본 정책보다 우선 매칭시킨다.

```json
PUT _plugins/_ism/policies/icdataops-dev-log-remote-policy
{
  "policy": {
    "description": "remote_snapshot warm index: delete at 6d (S3 cold snapshot only remains)",
    "default_state": "warm_remote",
    "ism_template": [
      { "index_patterns": ["icdataops-dev-log-*-r"], "priority": 200 }
    ],
    "states": [
      {
        "name": "warm_remote",
        "actions": [],
        "transitions": [
          { "state_name": "purge", "conditions": { "min_index_age": "6d" } }
        ]
      },
      {
        "name": "purge",
        "actions": [ { "delete": {} } ],
        "transitions": []
      }
    ]
  }
}
```

> ism_template이 복원 인덱스에 적용되지 않는 케이스에 대비해, CronJob이 복원 직후 `_plugins/_ism/add`로 명시 연결한다(4장 스크립트에 포함). 이중 적용은 무해하다.

### 3-4. SM 정책 (스냅샷 보존/정리)

```json
# S3 cold 스냅샷: 30d 보존
POST _plugins/_sm/policies/icdataops-cold-retention
{
  "description": "MinIO cold snapshot 30d retention",
  "creation": { "schedule": { "cron": { "expression": "0 2 * * *", "timezone": "Asia/Seoul" } } },
  "deletion": {
    "schedule": { "cron": { "expression": "0 3 * * *", "timezone": "Asia/Seoul" } },
    "condition": { "max_age": "30d", "min_count": 1 }
  },
  "snapshot_config": {
    "repository": "minio-s3-repo",
    "indices": "icdataops-dev-log*",
    "include_global_state": false,
    "ignore_unavailable": true
  }
}

# Isilon warm 스냅샷: remote 인덱스 삭제(6d) 이후엔 불필요 → 8d 정리
POST _plugins/_sm/policies/icdataops-warm-retention
{
  "description": "Isilon warm snapshot cleanup",
  "creation": { "schedule": { "cron": { "expression": "30 2 * * *", "timezone": "Asia/Seoul" } } },
  "deletion": {
    "schedule": { "cron": { "expression": "30 3 * * *", "timezone": "Asia/Seoul" } },
    "condition": { "max_age": "8d", "min_count": 1 }
  },
  "snapshot_config": {
    "repository": "isilon-nfs-repo",
    "indices": "icdataops-dev-log*",
    "include_global_state": false,
    "ignore_unavailable": true
  }
}
```

> 주의: remote_snapshot 인덱스가 아직 참조 중인 Isilon 스냅샷을 지우면 해당 인덱스가 깨진다. remote 삭제(6d)보다 보존(8d)을 길게 잡은 이유. ISM/CronJob 지연으로 remote가 6d를 넘겨 남아있을 가능성이 있으면 여유를 더 둘 것.

## 4. warm 전환 자동화 CronJob (restore → 로컬 delete)

ISM이 못 하는 한 단계 — "Isilon 스냅샷을 remote_snapshot으로 복원하고 로컬 원본을 지우는 것" — 을 30분 주기 CronJob으로 처리한다.

동작 순서(인덱스별): ① warm state 도달 + 두 스냅샷 SUCCESS 확인 → ② `{index}-r`로 remote 복원 → ③ green 대기 → ④ remote 정책 연결 → ⑤ 로컬 원본 delete. 어느 단계든 실패하면 그 인덱스는 건너뛰고 다음 주기에 재시도하므로, 로컬 원본이 먼저 지워지는 일은 없다.

```yaml
# warm-tiering-cronjob.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: warm-tiering-script
  namespace: opensearch
data:
  tiering.sh: |
    #!/bin/bash
    set -uo pipefail
    OS="https://opensearch-cluster-master.opensearch.svc:9200"
    AUTH="-u ${OS_USER}:${OS_PASS} -k"
    PATTERN="icdataops-dev-log-"
    ISILON_REPO="isilon-nfs-repo"
    S3_REPO="minio-s3-repo"

    api() { curl -s $AUTH "$@"; }

    # warm state에 있는 로컬 인덱스 목록 (-r 제외)
    INDICES=$(api "$OS/_plugins/_ism/explain/${PATTERN}*?size=100" \
      | jq -r 'to_entries[] | select(.value.state.name? == "warm")
               | .key | select(endswith("-r") | not)')

    for IDX in $INDICES; do
      echo "== $IDX =="
      # 이미 remote가 있으면 로컬 삭제만 재시도
      REMOTE="${IDX}-r"
      HAS_REMOTE=$(api -o /dev/null -w "%{http_code}" "$OS/$REMOTE")

      if [ "$HAS_REMOTE" != "200" ]; then
        # 두 리포지토리 모두에서 이 인덱스를 포함한 SUCCESS 스냅샷 확인
        SNAP_I=$(api "$OS/_snapshot/$ISILON_REPO/warm-${PATTERN}*" \
          | jq -r --arg i "$IDX" '[.snapshots[] | select(.state=="SUCCESS")
                | select(.indices[] | . == $i)] | sort_by(.start_time_in_millis)
                | last | .snapshot // empty')
        SNAP_S=$(api "$OS/_snapshot/$S3_REPO/cold-${PATTERN}*" \
          | jq -r --arg i "$IDX" '[.snapshots[] | select(.state=="SUCCESS")
                | select(.indices[] | . == $i)] | length')
        if [ -z "$SNAP_I" ] || [ "$SNAP_S" -eq 0 ]; then
          echo "  snapshots not ready (isilon=$SNAP_I s3_count=$SNAP_S) → skip"; continue
        fi

        # remote_snapshot 복원 (데이터는 Isilon에 상주)
        RC=$(api -o /tmp/r.json -w "%{http_code}" -X POST \
          "$OS/_snapshot/$ISILON_REPO/$SNAP_I/_restore" \
          -H 'Content-Type: application/json' -d "{
            \"indices\": \"$IDX\",
            \"storage_type\": \"remote_snapshot\",
            \"rename_pattern\": \"(.+)\",
            \"rename_replacement\": \"\$1-r\"
          }")
        if [ "$RC" != "200" ]; then echo "  restore failed:"; cat /tmp/r.json; continue; fi
      fi

      # green 대기 (최대 10분)
      RC=$(api -o /dev/null -w "%{http_code}" \
        "$OS/_cluster/health/$REMOTE?wait_for_status=green&timeout=600s")
      if [ "$RC" != "200" ]; then echo "  $REMOTE not green → skip delete"; continue; fi

      # remote 정책 명시 연결 (이미 연결돼 있어도 무해)
      api -X POST "$OS/_plugins/_ism/add/$REMOTE" \
        -H 'Content-Type: application/json' \
        -d '{"policy_id":"icdataops-dev-log-remote-policy"}' > /dev/null

      # 로컬 원본 삭제 → 디스크 회수
      RC=$(api -o /tmp/d.json -w "%{http_code}" -X DELETE "$OS/$IDX")
      if [ "$RC" == "200" ]; then echo "  local $IDX deleted (disk reclaimed)"
      else echo "  delete failed:"; cat /tmp/d.json; fi
    done
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: opensearch-warm-tiering
  namespace: opensearch
spec:
  schedule: "*/30 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: tiering
              image: badouralix/curl-jq:latest   # curl+jq 포함 경량 이미지 (사내 레지스트리 미러 권장)
              command: ["/bin/bash", "/scripts/tiering.sh"]
              env:
                - name: OS_USER
                  valueFrom: { secretKeyRef: { name: opensearch-credentials, key: username } }
                - name: OS_PASS
                  valueFrom: { secretKeyRef: { name: opensearch-credentials, key: password } }
              volumeMounts:
                - { name: script, mountPath: /scripts }
          volumes:
            - name: script
              configMap: { name: warm-tiering-script, defaultMode: 0755 }
```

## 5. 검증 시나리오

```text
# 1) 캐시/롤 반영 확인
GET _cat/nodes?v&h=name,node.role        # 각 노드 role에 s(search) 포함 확인

# 2) rollover된 인덱스가 warm state에서 두 스냅샷을 완료했는지
GET _plugins/_ism/explain/icdataops-dev-log-*?pretty&size=30
GET _snapshot/isilon-nfs-repo/warm-icdataops-dev-log*
GET _snapshot/minio-s3-repo/cold-icdataops-dev-log*

# 3) CronJob 1주기 후: remote 인덱스 생성 + 로컬 원본 삭제 확인
GET _cat/indices/icdataops-dev-log-*?v&h=index,status,store.size,creation.date.string&s=index
#   → 최신(write)만 원본, 이전 것들은 *-r 만 존재. -r의 store.size는 캐시분만 표시됨

# 4) Discover 확인: 패턴 icdataops-dev-log-* 로 최근 6~7일 조회
#    -r 인덱스 데이터가 검색되는지, 응답 속도 확인 (첫 조회는 캐시 미스로 느릴 수 있음)

# 5) 디스크 회수 확인
GET _cat/allocation?v
```

## 6. 운영 노트

- **조회 창**: Discover에서는 hot(로컬) + warm(-r, Isilon)이 함께 보여 약 6~7일. 6d 이후는 S3 스냅샷만 남아 조회 불가 → 필요 시 restore (일반 restore 또는 remote_snapshot).
- **성능**: warm 검색은 NFS I/O를 탄다. 캐시(20gb) 히트 시 로컬 수준, 미스 시 Isilon 응답에 좌우. 최근 데이터 위주의 간헐 조회면 충분하나, warm 구간 대상 무거운 집계 대시보드는 피할 것.
- **replica**: hot 인덱스는 replica ≥ 1 유지 (local-path 노드 유실 대비 — node-2 PV 사고 재발 방지). remote 인덱스는 원본이 Isilon 스냅샷이므로 replica 불필요.
- **장애 격리**: Isilon 장애 시 warm 조회만 실패하고 hot 색인/조회는 영향 없다. 복구 후 -r 인덱스는 자동 회복되나, stale 상태가 길면 close/open 또는 재복원.
- **순서 보장**: CronJob은 "스냅샷 2건 SUCCESS → 복원 green → 삭제" 순서를 강제하므로 어느 단계 실패에도 데이터는 로컬·Isilon·S3 중 최소 한 곳에 존재한다.

## 7. 트러블슈팅

| 증상 | 조치 |
|---|---|
| restore 시 `storage_type` 거부 / unknown parameter | search 롤 미적용 노드뿐이거나 캐시 미설정. `_cat/nodes` role, `node.search.cache.size` 확인 후 재기동 |
| -r 인덱스 yellow/red 지속 | search 롤 노드의 캐시 여유 부족 또는 Isilon 접근 불가. Pod에서 `/mnt/isilon-repo` 접근 확인 |
| CronJob이 계속 skip (snapshots not ready) | warm state의 snapshot 액션 실패 여부를 `_ism/explain`의 step_status/retry_count로 확인. 리포지토리 `_verify` 재실행 |
| -r 인덱스가 hot 정책에 붙음 | remote-policy(priority 200) 등록 누락. 등록 후 `_plugins/_ism/change_policy`로 교체 |
| Isilon 스냅샷 삭제 후 -r 검색 오류 | SM warm-retention의 max_age가 remote 수명(6d)보다 짧게 설정됨. 8d 이상으로 조정, 깨진 -r는 delete 후 S3에서 복원 |
| warm 첫 조회가 매우 느림 | 정상(캐시 워밍). 반복 조회 대상이면 캐시 크기 증설 또는 해당 기간 일반 restore 검토 |

## 8. 마이그레이션 순서 (기존 hot 3d → 신규 구성)

1. values.yaml 반영 → `helm upgrade` 롤링 재기동 (green 유지, 동시 2노드 다운 금지)
2. `isilon-nfs-repo` 등록 + `_verify` + 테스트 스냅샷/remote 복원 1회 수동 검증
3. ISM 정책 2종 + SM 정책 2종 등록
4. CronJob 배포 (처음엔 schedule을 수동 트리거로 검증: `kubectl create job --from=cronjob/opensearch-warm-tiering test1`)
5. 기존 인덱스에 정책 적용 — 나이 든 인덱스가 즉시 warm 처리(스냅샷 2건 + 로컬 삭제)되므로 Isilon/S3 용량과 처리 부하를 감안해 오래된 것부터 소량씩:
   ```text
   POST _plugins/_ism/change_policy/icdataops-dev-log-2026.06.2*
   { "policy_id": "icdataops-dev-log-policy", "include": [{ "state": "hot" }] }
   ```
6. 1~2일 관찰: `_ism/explain` failed 여부, CronJob 로그, 디스크 회수 추이(`_cat/allocation`), Discover 조회 창
