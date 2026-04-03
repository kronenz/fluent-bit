# MongoDB 핵심 (MongoDB Essentials) - Allganize 면접 준비

---

> **TL;DR**
> 1. MongoDB는 **WiredTiger** 스토리지 엔진 기반의 **도큐먼트(Document) DB**로, 스키마 유연성이 강점이다
> 2. **레플리카셋(Replica Set)**으로 고가용성, **샤딩(Sharding)**으로 수평 확장을 구현한다
> 3. K8s에서는 **MongoDB Community Operator + StatefulSet**으로 운영하며, 인덱스 최적화가 성능의 핵심이다

---

## 1. MongoDB 아키텍처

### WiredTiger 스토리지 엔진

```
[Application]
     |
[MongoDB Server (mongod)]
     |
[WiredTiger Engine]
  ├── In-Memory Cache (WiredTiger Cache)
  │     └── B-Tree 인덱스 + 도큐먼트 캐시
  ├── Journal (WAL - Write Ahead Log)
  │     └── 장애 복구용 트랜잭션 로그
  └── Data Files (.wt)
        └── 압축된 실제 데이터 파일
```

#### WiredTiger 핵심 특성

| 특성 | 설명 |
|------|------|
| **Document-Level Locking** | 도큐먼트 단위 잠금 (높은 동시성) |
| **Compression** | snappy(기본), zlib, zstd 지원 (디스크 절약) |
| **Checkpoint** | 60초마다 데이터를 디스크에 동기화 |
| **Cache** | 기본값: (RAM - 1GB) / 2 또는 256MB 중 큰 값 |

```bash
# WiredTiger 캐시 확인
mongo --eval "db.serverStatus().wiredTiger.cache"

# 캐시 크기 설정 (mongod.conf)
# storage:
#   wiredTiger:
#     engineConfig:
#       cacheSizeGB: 4
```

### 도큐먼트 모델 (Document Model)

```javascript
// RDBMS vs MongoDB
// RDBMS: users 테이블 + addresses 테이블 + JOIN
// MongoDB: 하나의 도큐먼트에 내장 (Embedding)

{
  "_id": ObjectId("507f1f77bcf86cd799439011"),
  "name": "김개발",
  "email": "dev@allganize.ai",
  "department": "DevOps",
  "addresses": [                    // 내장 도큐먼트 (Embedded)
    {
      "type": "office",
      "city": "서울",
      "zip": "06164"
    }
  ],
  "projects": [                     // 참조 (Reference) 방식도 가능
    ObjectId("507f1f77bcf86cd799439012"),
    ObjectId("507f1f77bcf86cd799439013")
  ],
  "metadata": {
    "created_at": ISODate("2024-01-15T09:00:00Z"),
    "updated_at": ISODate("2024-06-01T14:30:00Z")
  }
}
```

#### 설계 원칙: Embedding vs Reference

| 기준 | Embedding (내장) | Reference (참조) |
|------|-----------------|-----------------|
| **관계** | 1:1, 1:Few | 1:Many, Many:Many |
| **접근 패턴** | 함께 읽는 데이터 | 독립적으로 접근하는 데이터 |
| **크기** | 16MB 이하 (도큐먼트 제한) | 크기 제한 없음 |
| **AI 서비스 예시** | 사용자 + 설정 | 사용자 + 대화 이력(수천 건) |

---

## 2. 레플리카셋 구조와 선출 과정

### 레플리카셋 아키텍처

```
[Client/Application]
     |
     ├── Write ──→ [Primary]
     │                 |
     │          Oplog 복제 (비동기)
     │              /      \
     └── Read ──→ [Secondary] [Secondary]
                         |
                    [Arbiter] (선택적, 투표만 참여)
```

### 선출 (Election) 과정

```
1. Primary 장애 감지 (heartbeat 10초 간격, timeout 10초)
2. Secondary들이 선출 시작 (Raft 프로토콜 기반)
3. 투표 조건:
   - 과반수(Majority) 득표
   - Oplog가 가장 최신인 노드 우선
   - Priority 높은 노드 우선
4. 새 Primary 선출 (보통 10~12초)
5. 클라이언트 자동 재연결 (Connection String의 replicaSet 옵션)
```

#### 선출 관련 설정

```javascript
// 레플리카셋 구성
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo-0:27017", priority: 10 },  // Primary 우선
    { _id: 1, host: "mongo-1:27017", priority: 5 },
    { _id: 2, host: "mongo-2:27017", priority: 5 }
  ],
  settings: {
    electionTimeoutMillis: 10000,    // 10초 (기본값)
    heartbeatIntervalMillis: 2000    // 2초
  }
});

// 레플리카셋 상태 확인
rs.status()

// Write Concern 설정 (데이터 안전성)
db.collection.insertOne(
  { data: "important" },
  { writeConcern: { w: "majority", j: true } }
  // w: "majority" = 과반수 노드에 쓰기 완료 확인
  // j: true = Journal에 기록 확인
);
```

### Read Preference 옵션

| 모드 | 설명 | 적합 상황 |
|------|------|----------|
| **primary** (기본) | Primary에서만 읽기 | 최신 데이터 필수 |
| **primaryPreferred** | Primary 우선, 불가 시 Secondary | 일반적 읽기 |
| **secondary** | Secondary에서만 읽기 | 리포트, 분석 |
| **secondaryPreferred** | Secondary 우선 | 읽기 부하 분산 |
| **nearest** | 네트워크 지연 최소 노드 | 지리적 분산 |

---

## 3. 샤딩 전략

### 샤딩 아키텍처

```
[Application]
      |
[mongos Router] ←── 라우팅 (어느 샤드로 보낼지 결정)
      |
[Config Server RS] ←── 메타데이터 (청크-샤드 매핑)
      |
  ┌───┼───┐
  |   |   |
[Shard1] [Shard2] [Shard3]  ←── 각각 레플리카셋
```

### 샤드 키(Shard Key) 전략

| 전략 | 방법 | 장점 | 단점 |
|------|------|------|------|
| **Range Sharding** | 값의 범위로 분할 | 범위 쿼리 효율적 | 핫스팟 위험 |
| **Hash Sharding** | 해시값으로 분할 | 균등 분산 | 범위 쿼리 비효율 |
| **Zone Sharding** | 특정 범위를 특정 샤드에 배치 | 데이터 지역성 보장 | 설정 복잡 |

#### 좋은 샤드 키의 조건

```
1. High Cardinality (높은 카디널리티) - 값의 종류가 많을 것
2. Even Distribution (균등 분산) - 특정 값에 쏠리지 않을 것
3. Query Targeting (쿼리 대상) - 자주 쿼리하는 필드일 것

나쁜 예: { status: "active" }  -> 대부분 "active", 쏠림 심함
좋은 예: { tenant_id: 1, created_at: ISODate() }  -> 복합 키, 균등 분산
```

```javascript
// 샤딩 활성화
sh.enableSharding("ai_service")

// Hash Sharding 적용
sh.shardCollection("ai_service.conversations", { user_id: "hashed" })

// Zone Sharding (고객사별 데이터 격리)
sh.addShardTag("shard-kr", "korea")
sh.addShardTag("shard-jp", "japan")
sh.addTagRange(
  "ai_service.conversations",
  { region: "KR" }, { region: "KS" },  // KR로 시작하는 범위
  "korea"
)

// 샤딩 상태 확인
sh.status()
db.conversations.getShardDistribution()
```

---

## 4. 인덱스 종류와 최적화

### 인덱스 종류

| 인덱스 | 용도 | 예시 |
|--------|------|------|
| **Single Field** | 단일 필드 검색 | `{ email: 1 }` |
| **Compound** | 복합 조건 검색 | `{ tenant_id: 1, created_at: -1 }` |
| **Multikey** | 배열 필드 검색 | `{ tags: 1 }` |
| **Text** | 텍스트 전문 검색 | `{ content: "text" }` |
| **Wildcard** | 동적 필드 검색 | `{ "metadata.$**": 1 }` |
| **TTL** | 자동 문서 만료 | `{ expireAt: 1 }, { expireAfterSeconds: 0 }` |
| **Partial** | 조건부 인덱싱 (디스크 절약) | `{ status: 1 }, { partialFilterExpression: {...} }` |

### ESR Rule (Equality, Sort, Range)

```javascript
// 쿼리: tenant_id == "allganize" AND created_at > 30일전 ORDER BY score DESC

// 나쁜 인덱스 (Range -> Sort -> Equality)
db.conversations.createIndex({ created_at: 1, score: -1, tenant_id: 1 })

// 좋은 인덱스 (ESR: Equality -> Sort -> Range)
db.conversations.createIndex({ tenant_id: 1, score: -1, created_at: 1 })
// E: tenant_id (등호 조건)
// S: score (정렬)
// R: created_at (범위 조건)
```

### 인덱스 분석 도구

```javascript
// 쿼리 실행 계획 확인
db.conversations.find({
  tenant_id: "allganize",
  created_at: { $gte: ISODate("2024-01-01") }
}).sort({ score: -1 }).explain("executionStats")

// 주요 확인 포인트
// stage: "IXSCAN" (인덱스 사용) vs "COLLSCAN" (풀 스캔 - 위험!)
// nReturned vs totalDocsExamined 비율 (1에 가까울수록 좋음)
// executionTimeMillis: 실행 시간

// 사용되지 않는 인덱스 찾기
db.conversations.aggregate([{ $indexStats: {} }])
// accesses.ops가 0인 인덱스는 제거 후보

// 슬로우 쿼리 프로파일링
db.setProfilingLevel(1, { slowms: 100 })
db.system.profile.find().sort({ ts: -1 }).limit(10).pretty()
```

---

## 5. K8s에서 MongoDB 운영

### MongoDB Community Operator

```bash
# Operator 설치
helm repo add mongodb https://mongodb.github.io/helm-charts
helm install community-operator mongodb/community-operator \
  --namespace mongodb --create-namespace
```

```yaml
# mongodb-replicaset.yaml
apiVersion: mongodbcommunity.mongodb.com/v1
kind: MongoDBCommunity
metadata:
  name: mongodb
  namespace: mongodb
spec:
  members: 3
  type: ReplicaSet
  version: "7.0.8"
  security:
    authentication:
      modes: ["SCRAM"]
  users:
    - name: admin
      db: admin
      passwordSecretRef:
        name: mongodb-admin-password
      roles:
        - name: clusterAdmin
          db: admin
        - name: userAdminAnyDatabase
          db: admin
      scramCredentialsSecretName: admin-scram
  statefulSet:
    spec:
      template:
        spec:
          containers:
            - name: mongod
              resources:
                requests:
                  cpu: "1"
                  memory: "4Gi"
                limits:
                  cpu: "2"
                  memory: "8Gi"
      volumeClaimTemplates:
        - metadata:
            name: data-volume
          spec:
            accessModes: ["ReadWriteOnce"]
            storageClassName: fast-ssd
            resources:
              requests:
                storage: 100Gi
        - metadata:
            name: logs-volume
          spec:
            accessModes: ["ReadWriteOnce"]
            resources:
              requests:
                storage: 10Gi
  additionalMongodConfig:
    storage.wiredTiger.engineConfig.cacheSizeGB: 2
    net.maxIncomingConnections: 1000
```

### StatefulSet 핵심 포인트

```
StatefulSet이 MongoDB에 적합한 이유:
1. 안정적 네트워크 ID (mongo-0, mongo-1, mongo-2)
2. 안정적 스토리지 (PVC가 Pod에 영구 바인딩)
3. 순서 보장 (0 -> 1 -> 2 순서로 시작/종료)
4. Headless Service로 개별 Pod DNS 제공
```

```yaml
# headless-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: mongodb-svc
  namespace: mongodb
spec:
  clusterIP: None           # Headless Service
  selector:
    app: mongodb
  ports:
    - port: 27017
# DNS: mongodb-0.mongodb-svc.mongodb.svc.cluster.local
```

---

## 6. 백업/복구 전략

### 백업 방법 비교

| 방법 | 도구 | 장점 | 단점 |
|------|------|------|------|
| **논리 백업** | `mongodump` | 이식성 높음, 컬렉션 단위 | 대용량 시 느림 |
| **물리 백업** | 파일시스템 스냅샷 | 빠름, 대용량 적합 | 같은 버전/설정 필요 |
| **연속 백업** | Oplog 기반 PITR | 시점 복구 가능 | 설정 복잡 |

### 백업 스크립트

```bash
#!/bin/bash
# mongodb-backup.sh

BACKUP_DIR="/backup/mongodb/$(date +%Y%m%d_%H%M%S)"
MONGO_URI="mongodb://admin:password@mongodb-0.mongodb-svc:27017,mongodb-1.mongodb-svc:27017,mongodb-2.mongodb-svc:27017/?replicaSet=rs0&authSource=admin"

# 논리 백업 (압축)
mongodump --uri="$MONGO_URI" \
  --out="$BACKUP_DIR" \
  --gzip \
  --oplog                    # PITR용 oplog 포함

# 오래된 백업 정리 (30일)
find /backup/mongodb -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +

echo "Backup completed: $BACKUP_DIR"
```

### 복구

```bash
# 전체 복구
mongorestore --uri="$MONGO_URI" \
  --gzip \
  --oplogReplay \             # oplog 재생 (PITR)
  "$BACKUP_DIR"

# 특정 컬렉션만 복구
mongorestore --uri="$MONGO_URI" \
  --gzip \
  --nsInclude="ai_service.conversations" \
  "$BACKUP_DIR"
```

### K8s CronJob으로 자동 백업

```yaml
# mongodb-backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mongodb-backup
  namespace: mongodb
spec:
  schedule: "0 2 * * *"          # 매일 02:00
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: mongo:7.0
              command: ["/bin/bash", "-c"]
              args:
                - |
                  mongodump --uri="$MONGO_URI" \
                    --out="/backup/$(date +%Y%m%d)" \
                    --gzip --oplog
              env:
                - name: MONGO_URI
                  valueFrom:
                    secretKeyRef:
                      name: mongodb-backup-secret
                      key: uri
              volumeMounts:
                - name: backup-storage
                  mountPath: /backup
          restartPolicy: OnFailure
          volumes:
            - name: backup-storage
              persistentVolumeClaim:
                claimName: mongodb-backup-pvc
```

---

## 면접 Q&A

### Q1. "MongoDB의 WiredTiger 엔진에 대해 설명해주세요"

> **이렇게 대답한다:**
> "WiredTiger는 MongoDB 3.2부터 기본 스토리지 엔진으로, Document-Level Locking으로 높은 동시성을 지원합니다. 내부적으로 B-Tree 인덱스, WAL(Journal) 기반 장애 복구, snappy/zstd 압축을 제공합니다. 캐시 크기는 기본 (RAM-1GB)/2이며, 60초마다 Checkpoint로 데이터를 디스크에 동기화합니다. AI 서비스에서 대화 이력처럼 빈번한 쓰기가 발생하는 워크로드에서 Document-Level Locking이 특히 유리합니다."

### Q2. "레플리카셋에서 Primary가 죽으면 어떻게 되나요?"

> **이렇게 대답한다:**
> "Secondary 노드들이 heartbeat timeout(기본 10초) 후 Raft 기반 선출을 시작합니다. Oplog가 가장 최신이고 Priority가 높은 노드가 과반수 투표로 새 Primary가 됩니다. 전체 failover는 보통 10~12초 내에 완료됩니다. 클라이언트는 Connection String에 replicaSet 옵션을 사용하면 자동 재연결됩니다. 중요한 데이터는 writeConcern: majority로 과반수 노드 쓰기를 보장하여, failover 시에도 데이터 손실을 방지합니다."

### Q3. "샤드 키를 잘못 선택하면 어떤 문제가 발생하나요?"

> **이렇게 대답한다:**
> "Low Cardinality 키(예: status, boolean)를 선택하면 Jumbo Chunk이 발생하여 밸런서가 마이그레이션할 수 없습니다. Monotonically Increasing 키(예: ObjectId, timestamp)를 Range Sharding하면 모든 쓰기가 마지막 샤드에 집중되는 핫스팟이 발생합니다. 이를 방지하려면 Hash Sharding이나 복합 키(tenant_id + created_at)를 사용합니다. 샤드 키는 4.4 이후 변경 가능하지만 비용이 크므로, 초기 설계가 매우 중요합니다."

### Q4. "MongoDB 인덱스 최적화 경험을 이야기해주세요"

> **이렇게 대답한다:**
> "ESR Rule(Equality, Sort, Range)을 기본으로 복합 인덱스를 설계합니다. explain()의 executionStats로 COLLSCAN 여부, nReturned 대비 totalDocsExamined 비율을 확인하고, indexStats로 미사용 인덱스를 정리합니다. Partial Index로 활성 데이터만 인덱싱하여 디스크와 메모리를 절약하고, TTL Index로 만료 데이터를 자동 삭제합니다. 프로파일링(slowms: 100)으로 슬로우 쿼리를 상시 모니터링하는 것도 필수입니다."

### Q5. "K8s에서 MongoDB를 운영할 때 주의할 점은?"

> **이렇게 대답한다:**
> "첫째, StatefulSet + Headless Service로 안정적 네트워크 ID와 영구 스토리지를 보장해야 합니다. 둘째, MongoDB Community Operator를 사용하면 레플리카셋 구성, 버전 업그레이드, 사용자 관리를 자동화할 수 있습니다. 셋째, PVC의 StorageClass를 SSD 기반으로 설정하고, WiredTiger 캐시 크기를 Pod의 메모리 limits에 맞게 조정해야 합니다. 넷째, Anti-Affinity Rule로 레플리카셋 멤버를 서로 다른 노드에 배치하여 노드 장애 시 가용성을 확보합니다."

---

## 핵심 키워드 5선

`WiredTiger (Document-Level Locking)` `Replica Set Election (Raft)` `Shard Key 설계 (ESR Rule)` `MongoDB Operator (StatefulSet)` `writeConcern: majority`
