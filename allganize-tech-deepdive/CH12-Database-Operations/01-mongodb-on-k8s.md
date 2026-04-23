# MongoDB on Kubernetes

> **TL;DR**: MongoDB는 Document 기반 NoSQL로, ReplicaSet(Primary-Secondary) 구조로 고가용성을 확보하고 Sharding으로 수평 확장한다.
> Kubernetes 위에서는 Percona Operator for MongoDB(PSMDB)가 StatefulSet, PVC, 자동 failover를 관리하여 Day-2 운영 부담을 줄인다.
> Allganize의 AI 메타데이터/대화 이력 저장소로 MongoDB가 활용될 가능성이 높으며, K8s 위 안정 운영이 핵심 역량이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### MongoDB 아키텍처 개요

MongoDB는 **Document Store**로, JSON-like 문서(BSON)를 Collection에 저장한다. RDBMS의 table-row-column 대신 collection-document-field 구조를 사용한다.

```
┌─────────────────────────────────────────────────┐
│                  MongoDB Cluster                 │
│                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────┐│
│  │  mongos     │  │  mongos     │  │  mongos  ││
│  │  (Router)   │  │  (Router)   │  │ (Router) ││
│  └──────┬──────┘  └──────┬──────┘  └────┬─────┘│
│         │                │               │      │
│         └────────┬───────┴───────┬───────┘      │
│                  ▼               ▼               │
│  ┌──────────────────┐  ┌──────────────────┐     │
│  │   Shard 1        │  │   Shard 2        │     │
│  │ ┌───┐ ┌───┐ ┌───┐│  │ ┌───┐ ┌───┐ ┌───┐│     │
│  │ │ P │ │ S │ │ S ││  │ │ P │ │ S │ │ S ││     │
│  │ └───┘ └───┘ └───┘│  │ └───┘ └───┘ └───┘│     │
│  │   ReplicaSet      │  │   ReplicaSet      │     │
│  └──────────────────┘  └──────────────────┘     │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  Config Server ReplicaSet (3 nodes)       │   │
│  │  - Shard 메타데이터, chunk 분배 정보 저장  │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### ReplicaSet (복제 세트)

MongoDB 고가용성의 기본 단위. **최소 3노드** 권장 (Primary 1 + Secondary 2).

```
  Client (Write)          Client (Read - secondary preferred)
       │                           │
       ▼                           ▼
  ┌─────────┐    oplog 복제    ┌─────────┐
  │ PRIMARY  │ ──────────────► │SECONDARY│
  │         │ ──────────────► │   #1    │
  │ (R/W)   │                 └─────────┘
  └─────────┘    oplog 복제    ┌─────────┐
                ──────────────►│SECONDARY│
                               │   #2    │
                               └─────────┘
                               (또는 Arbiter)

  장애 시: Primary 다운 → Secondary 간 election → 새 Primary 승격 (10-12초)
```

**핵심 메커니즘:**
- **oplog (Operation Log)**: Primary의 모든 쓰기 연산을 capped collection에 기록, Secondary가 이를 복제
- **Election**: Primary 장애 시 Raft-like 프로토콜로 새 Primary 선출 (과반수 투표)
- **Write Concern**: `w:1`(Primary만), `w:majority`(과반수 확인), `w:all`(전체 확인)
- **Read Preference**: `primary`, `primaryPreferred`, `secondary`, `secondaryPreferred`, `nearest`

### Sharding (수평 분할)

데이터를 **Shard Key** 기준으로 여러 Shard에 분산 저장한다.

| Shard Key 전략 | 장점 | 단점 |
|---|---|---|
| **Hashed Sharding** | 균등 분산, hotspot 방지 | Range query 비효율 |
| **Ranged Sharding** | Range query 효율적 | 데이터 편중(hotspot) 가능 |
| **Zone Sharding** | 지역별 데이터 배치 가능 | 설계 복잡도 증가 |

**Shard Key 선택 원칙:**
- 카디널리티(Cardinality)가 높을 것 (고유 값이 많을수록 균등 분산)
- 쓰기 분산이 될 것 (monotonic 증가 키는 단일 shard에 집중)
- 자주 사용하는 쿼리의 조건과 일치할 것

### Kubernetes에서의 MongoDB 운영

#### Percona Operator for MongoDB (PSMDB)

```
┌──────────────────────────────────────────────┐
│              Kubernetes Cluster               │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │     PSMDB Operator (Deployment)        │  │
│  │     - CRD: PerconaServerMongoDB        │  │
│  │     - Reconciliation Loop 실행         │  │
│  └───────────────┬────────────────────────┘  │
│                  │ watch & reconcile          │
│                  ▼                            │
│  ┌────────────────────────────────────────┐  │
│  │  StatefulSet: mongodb-rs0               │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐     │  │
│  │  │ Pod-0  │ │ Pod-1  │ │ Pod-2  │     │  │
│  │  │Primary │ │Second. │ │Second. │     │  │
│  │  │  PVC   │ │  PVC   │ │  PVC   │     │  │
│  │  └────────┘ └────────┘ └────────┘     │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Service: mongodb-rs0 (Headless)       │  │
│  │  - mongodb-rs0-0.mongodb-rs0.ns.svc    │  │
│  │  - mongodb-rs0-1.mongodb-rs0.ns.svc    │  │
│  │  - mongodb-rs0-2.mongodb-rs0.ns.svc    │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

**Percona Operator 핵심 기능:**
- **자동 ReplicaSet 구성**: Pod 생성 시 자동으로 `rs.initiate()` 수행
- **자동 Failover**: Primary Pod 삭제/장애 시 새 Primary 선출 + DNS 업데이트
- **자동 Backup**: S3/GCS/Azure Blob으로 스케줄 백업 (Physical + Logical)
- **Rolling Update**: MongoDB 버전 업그레이드 시 Secondary → Primary 순으로 무중단 업데이트
- **TLS/Auth 자동 설정**: cert-manager 연동으로 인증서 자동 관리

#### PSMDB CR (Custom Resource) 예시

```yaml
apiVersion: psmdb.percona.com/v1
kind: PerconaServerMongoDB
metadata:
  name: my-cluster
  namespace: mongodb
spec:
  image: percona/percona-server-mongodb:7.0.8-5
  replsets:
    - name: rs0
      size: 3                          # ReplicaSet 멤버 수
      affinity:
        antiAffinityTopologyKey: "kubernetes.io/hostname"  # Pod 분산
      resources:
        limits:
          cpu: "2"
          memory: "4Gi"
        requests:
          cpu: "1"
          memory: "2Gi"
      volumeSpec:
        persistentVolumeClaim:
          storageClassName: gp3-encrypted
          resources:
            requests:
              storage: 100Gi
  sharding:
    enabled: true
    mongos:
      size: 3
    configsvrReplSet:
      size: 3
  backup:
    enabled: true
    storages:
      s3-backup:
        type: s3
        s3:
          bucket: my-mongodb-backups
          region: ap-northeast-2
    tasks:
      - name: daily-backup
        enabled: true
        schedule: "0 2 * * *"          # 매일 02:00 UTC
        storageName: s3-backup
        compressionType: gzip
```

### 백업과 복구

| 방식 | 도구 | 특성 |
|---|---|---|
| **Logical Backup** | `mongodump`/`mongorestore` | JSON/BSON export, 느리지만 유연, 부분 복구 가능 |
| **Physical Backup** | Percona Backup (PBM) | 파일시스템 스냅샷, 빠르지만 전체 복구만 가능 |
| **Continuous Backup** | oplog 기반 PITR | Point-in-Time Recovery, 초 단위 복구 가능 |

```
백업 전략 (3-2-1 Rule 적용):
┌───────────────────────────────────────────┐
│  Daily Full Backup → S3 (30일 보관)       │
│  Continuous oplog → S3 (PITR 7일)         │
│  Weekly Full → Cross-Region S3 (90일)     │
└───────────────────────────────────────────┘
```

---

## 실전 예시

### MongoDB ReplicaSet 상태 확인

```bash
# ReplicaSet 상태 확인 (mongo shell)
mongosh --eval "rs.status()"

# 복제 지연(replication lag) 확인
mongosh --eval "rs.printSecondaryReplicationInfo()"

# Percona Operator로 배포된 클러스터 상태
kubectl get psmdb -n mongodb
kubectl describe psmdb my-cluster -n mongodb

# Pod 상태 및 Primary 확인
kubectl exec -it my-cluster-rs0-0 -n mongodb -- mongosh --eval "rs.isMaster()"
```

### 성능 모니터링 쿼리

```javascript
// 느린 쿼리 확인 (100ms 이상)
db.setProfilingLevel(1, { slowms: 100 })
db.system.profile.find().sort({ ts: -1 }).limit(5)

// 인덱스 사용 확인
db.collection.find({ field: "value" }).explain("executionStats")

// 현재 연결 수 확인
db.serverStatus().connections

// WiredTiger 캐시 사용률
db.serverStatus().wiredTiger.cache
```

### Failover 테스트

```bash
# Primary Pod 강제 삭제로 failover 테스트
kubectl delete pod my-cluster-rs0-0 -n mongodb

# 새 Primary 선출 확인 (10-12초 내)
kubectl exec -it my-cluster-rs0-1 -n mongodb -- \
  mongosh --eval "rs.isMaster().primary"

# Percona Operator가 Pod를 재생성하는지 확인
kubectl get pods -n mongodb -w
```

---

## 면접 Q&A

### Q: MongoDB ReplicaSet의 동작 원리와 failover 과정을 설명해주세요.

**30초 답변**:
MongoDB ReplicaSet은 Primary 1대와 Secondary 2대 이상으로 구성됩니다. Primary의 모든 쓰기는 oplog에 기록되고 Secondary가 이를 복제합니다. Primary 장애 시 Secondary 간 election이 발생하여 10~12초 내에 새 Primary가 선출됩니다.

**2분 답변**:
ReplicaSet은 동일한 데이터를 여러 노드에 복제하여 고가용성을 보장합니다. Primary는 모든 쓰기 연산을 처리하고, 이를 oplog(capped collection)에 기록합니다. Secondary는 Primary의 oplog를 비동기로 복제하여 데이터를 동기화합니다. Primary가 heartbeat(기본 2초)에 응답하지 않으면 `electionTimeoutMillis`(기본 10초) 후 election이 시작됩니다. 과반수(majority) 투표를 받은 Secondary가 새 Primary로 승격됩니다. 이때 Write Concern 설정이 중요한데, `w:majority`로 설정하면 과반수 노드에 쓰기가 완료된 후 응답하므로 failover 시 데이터 유실을 방지할 수 있습니다. 반면 `w:1`은 Primary만 확인하므로 빠르지만 failover 시 마지막 쓰기가 유실될 수 있습니다. Kubernetes 환경에서는 Percona Operator가 StatefulSet과 Headless Service를 통해 안정적인 네트워크 ID를 부여하고, Pod 재시작 시 동일 PVC에 재연결되어 데이터를 보존합니다.

**💡 경험 연결**:
온프레미스에서 3노드 ReplicaSet을 운영할 때, 네트워크 파티션으로 Primary가 isolated되면서 두 개의 Primary가 발생한 적이 있습니다. `w:majority` 설정이 아니었기 때문에 일부 쓰기가 rollback되었고, 이후 모든 프로덕션 MongoDB에 `w:majority`를 기본값으로 설정하는 정책을 수립했습니다.

**⚠️ 주의**:
"Secondary가 바로 Primary가 된다"고 단순화하지 말 것. election 과정, 투표 조건(priority, oplog 최신성), Write Concern에 따른 데이터 보장 수준까지 설명해야 한다.

### Q: Kubernetes에서 MongoDB를 운영할 때 StatefulSet이 필요한 이유는?

**30초 답변**:
MongoDB는 상태를 가진(stateful) 워크로드이므로, 안정적인 네트워크 ID(Pod 이름)와 영구 스토리지(PVC)가 필요합니다. StatefulSet은 Pod마다 고유한 이름과 개별 PVC를 보장하여 ReplicaSet 멤버 식별과 데이터 보존을 가능하게 합니다.

**2분 답변**:
Deployment과 달리 StatefulSet은 세 가지 보장을 제공합니다. 첫째, 순차적이고 안정적인 Pod 이름입니다. `mongodb-0`, `mongodb-1`, `mongodb-2`로 고정되어 ReplicaSet 설정에서 각 멤버를 식별할 수 있습니다. 둘째, Headless Service와 결합하여 `mongodb-0.mongodb-svc.ns.svc.cluster.local` 같은 고정 DNS를 제공합니다. MongoDB 드라이버가 각 멤버에 직접 연결할 수 있어 Read Preference 구현이 가능합니다. 셋째, `volumeClaimTemplates`로 Pod마다 개별 PVC를 생성하고, Pod가 재시작되어도 동일 PVC에 재연결됩니다. 추가로 순서 보장된 스케일링이 중요합니다. Scale-down 시 가장 높은 번호의 Pod부터 제거되므로, Primary를 마지막에 처리하는 전략이 가능합니다. Percona Operator는 이러한 StatefulSet 위에 MongoDB 특화 로직(자동 rs.initiate, failover 처리, 백업 스케줄)을 추가하여 운영 부담을 크게 줄여줍니다.

**💡 경험 연결**:
Deployment으로 MongoDB를 배포했다가 Pod 재시작 시 hostname이 변경되어 ReplicaSet 구성이 깨지는 문제를 경험한 적이 있습니다. StatefulSet으로 전환 후 안정적으로 운영할 수 있었고, 이 경험이 stateful 워크로드의 K8s 운영 원칙을 이해하는 계기가 되었습니다.

**⚠️ 주의**:
StatefulSet의 `podManagementPolicy`가 `OrderedReady`(기본값)인 경우 Pod가 순차적으로 생성되므로 초기 프로비저닝이 느릴 수 있다. MongoDB는 `Parallel` 정책을 사용해도 되지만, Operator가 이를 관리하므로 직접 변경하지 않는 것이 안전하다.

### Q: MongoDB Sharding은 언제 도입해야 하고, Shard Key는 어떻게 선택하나요?

**30초 답변**:
단일 ReplicaSet으로 처리할 수 없는 쓰기 부하나 데이터 용량(수 TB 이상)일 때 Sharding을 도입합니다. Shard Key는 높은 카디널리티, 균등한 쓰기 분산, 주요 쿼리 패턴과의 일치를 기준으로 선택합니다.

**2분 답변**:
Sharding 도입 시점은 세 가지 신호로 판단합니다. 첫째, 단일 노드의 디스크 용량 한계에 도달할 때. 둘째, 쓰기 throughput이 단일 Primary의 처리 한계를 초과할 때. 셋째, Working Set(자주 접근하는 데이터)이 RAM을 초과하여 캐시 효율이 떨어질 때. Shard Key 선택은 MongoDB 운영에서 가장 중요한 결정 중 하나인데, 한번 설정하면 변경이 매우 어렵기 때문입니다(MongoDB 5.0부터 resharding 가능하지만 비용이 큼). AI 서비스 맥락에서 예를 들면, 대화 이력 컬렉션에서 `user_id`를 hashed shard key로 사용하면 사용자별 균등 분산이 됩니다. 반면 `created_at`을 range shard key로 사용하면 최신 데이터가 하나의 shard에 집중되는 hotspot이 발생합니다. 복합 shard key(`{tenant_id: 1, created_at: 1}`)를 사용하면 tenant별 분산과 시간 범위 쿼리 모두를 만족시킬 수 있습니다.

**💡 경험 연결**:
로그 수집 시스템에서 timestamp를 shard key로 사용하여 최신 데이터가 단일 shard에 집중되는 문제를 경험했습니다. hashed(`_id`) 기반으로 변경 후 쓰기가 균등 분산되었지만, 시간 범위 쿼리 성능이 저하되어 결국 복합 키를 도입했습니다.

**⚠️ 주의**:
Sharding을 도입하면 운영 복잡도가 크게 증가한다(mongos, config server 추가). ReplicaSet으로 충분한 상황에서 조기에 도입하지 말 것. "Scale-up first, shard later" 원칙을 기억하자.

### Q: MongoDB 백업 전략을 설명해주세요.

**30초 답변**:
`mongodump`을 이용한 logical backup과 Percona Backup for MongoDB(PBM)를 이용한 physical backup을 조합합니다. oplog 기반 PITR(Point-in-Time Recovery)로 초 단위 복구가 가능하며, 3-2-1 원칙(3 copies, 2 media, 1 offsite)을 적용합니다.

**2분 답변**:
MongoDB 백업은 세 가지 계층으로 구성합니다. 첫째, **Daily Full Backup**: Percona Operator의 backup task로 매일 S3에 physical backup을 수행합니다. Secondary에서 실행되므로 Primary 성능에 영향이 없습니다. 둘째, **Continuous oplog Backup**: oplog를 지속적으로 S3에 스트리밍하여 PITR을 가능하게 합니다. 장애 발생 시 "어제 백업 + 오늘 oplog"를 결합하여 특정 시점으로 복구할 수 있습니다. 셋째, **Cross-Region Copy**: 재해 복구(DR)를 위해 주간 백업을 다른 리전의 S3로 복사합니다. 복구 테스트도 중요한데, 분기별로 별도 네임스페이스에 백업을 복원하여 데이터 정합성을 검증하는 프로세스를 운영해야 합니다. Kubernetes 환경에서는 Percona Operator가 CronJob 대신 CR의 `backup.tasks`로 스케줄을 관리하므로, 백업 상태를 `kubectl get psmdb-backup`으로 통합 모니터링할 수 있습니다.

**💡 경험 연결**:
mongodump으로만 백업하던 환경에서 100GB 이상 데이터의 복구에 수 시간이 걸리는 문제가 있었습니다. PBM 기반 physical backup으로 전환 후 복구 시간을 30분 이내로 단축했습니다.

**⚠️ 주의**:
백업은 했지만 복구 테스트를 하지 않는 것이 가장 흔한 실수. "백업이 아니라 복구가 목적"이라는 관점을 면접에서 보여줘야 한다.

---

## Allganize 맥락

- **AI 메타데이터 저장**: Allganize의 Alli 플랫폼에서 대화 이력, 사용자 피드백, 모델 메타데이터 등 비정형 데이터를 MongoDB에 저장할 가능성이 높다. Document 모델이 스키마 변경이 잦은 AI 서비스에 적합하다.
- **멀티 테넌트 설계**: SaaS 서비스에서 tenant별 데이터 격리가 중요하다. 컬렉션 레벨 분리 또는 `tenant_id` 필드 기반 sharding으로 구현 가능하다.
- **AWS/Azure 환경**: EKS에서는 EBS gp3를 MongoDB PVC로 사용하고, 백업은 S3에 저장한다. 관리형 서비스(DocumentDB, Cosmos DB)와 자체 운영(Percona Operator) 중 선택 근거를 설명할 수 있어야 한다. DocumentDB는 MongoDB 호환이지만 100% 호환은 아니므로(Change Stream 제한 등) 주의가 필요하다.
- **성능 최적화**: LLM 응답 지연에 DB latency가 추가되면 사용자 경험에 직접 영향. WiredTiger 캐시 크기를 Pod memory의 50%로 설정하고, 인덱스 설계로 쿼리 성능을 보장해야 한다.

---
**핵심 키워드**: `ReplicaSet` `oplog` `Sharding` `Shard-Key` `Percona-Operator` `StatefulSet` `Write-Concern` `PITR` `WiredTiger`
