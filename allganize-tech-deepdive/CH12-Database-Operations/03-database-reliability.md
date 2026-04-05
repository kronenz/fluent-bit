# Database Reliability Engineering

> **TL;DR**: 데이터베이스 안정성은 Connection Pooling으로 연결 효율화, Read Replica로 읽기 부하 분산, 자동 Failover로 장애 복구, 일관성 패턴으로 데이터 정합성을 보장하는 4가지 축으로 구성된다.
> 클라우드 네이티브 환경에서는 Sidecar Proxy(PgBouncer, ProxySQL), Operator 기반 자동 failover, eventual consistency 패턴이 핵심이다.
> Allganize의 AI 서비스에서 DB 장애는 곧 서비스 장애이므로, 이 네 가지 영역의 깊은 이해가 필수다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 15min

---

## 핵심 개념

### 1. Connection Pooling

데이터베이스 연결 생성은 비용이 크다(TCP handshake + 인증 + 메모리 할당). Connection Pool은 미리 생성한 연결을 재사용하여 오버헤드를 줄인다.

```
  Without Pool                          With Pool
  ┌──────┐    매번 새 연결              ┌──────┐
  │App-1 │──┐                          │App-1 │──┐
  │App-2 │──┼──► DB (연결 폭발)        │App-2 │──┤    ┌────────────┐
  │App-3 │──┤   max_conn 초과          │App-3 │──┼──► │ Pool       │──► DB
  │ ...  │──┤   → Connection refused   │ ...  │──┤    │ (20 conns) │   (안정)
  │App-N │──┘                          │App-N │──┘    └────────────┘
  └──────┘                             └──────┘
  (N개 연결 생성/소멸 반복)              (20개 연결 재사용)
```

**Pooling 계층:**

| 계층 | 도구 | 특성 |
|---|---|---|
| **Application-level** | HikariCP(Java), SQLAlchemy Pool(Python) | 앱 프로세스 내, Pod 단위 |
| **Sidecar Proxy** | PgBouncer, ProxySQL | Pod 내 sidecar, 앱 언어 무관 |
| **External Proxy** | PgBouncer(standalone), ProxySQL | 별도 Deployment, 중앙 관리 |
| **Cloud Managed** | RDS Proxy, Azure SQL Proxy | 완전 관리형, 서버리스 연동 |

**PgBouncer (PostgreSQL) K8s Sidecar 패턴:**

```yaml
# Pod에 PgBouncer sidecar 추가
spec:
  containers:
    - name: app
      image: my-app:latest
      env:
        - name: DATABASE_URL
          value: "postgresql://user:pass@localhost:6432/mydb"  # sidecar로 연결
    - name: pgbouncer
      image: bitnami/pgbouncer:latest
      ports:
        - containerPort: 6432
      env:
        - name: PGBOUNCER_DATABASE
          value: "mydb"
        - name: PGBOUNCER_POOL_MODE
          value: "transaction"        # transaction 단위 연결 공유
        - name: PGBOUNCER_MAX_CLIENT_CONN
          value: "200"                # 앱 → PgBouncer 최대 연결
        - name: PGBOUNCER_DEFAULT_POOL_SIZE
          value: "20"                 # PgBouncer → DB 실제 연결
        - name: POSTGRESQL_HOST
          value: "postgres-primary.db.svc"
```

**Pool Mode 비교 (PgBouncer):**

| Mode | 동작 | 제약 | 용도 |
|---|---|---|---|
| **Session** | 세션 종료까지 연결 점유 | 없음 | Prepared statement 필요 시 |
| **Transaction** | 트랜잭션 종료 후 반환 | SET/PREPARE 제한 | 대부분의 웹 앱 (권장) |
| **Statement** | 쿼리 단위 반환 | 트랜잭션 불가 | 단순 read-only |

### 2. Read Replicas (읽기 복제본)

쓰기는 Primary에, 읽기는 Replica에 분산하여 처리량을 확장한다.

```
                    ┌─────────────┐
  Write ───────────►│   Primary   │
                    │   (R/W)     │
                    └──────┬──────┘
                           │ Replication (async/semi-sync)
                    ┌──────┴──────┐
                    ▼             ▼
              ┌──────────┐ ┌──────────┐
  Read ──────►│ Replica 1│ │ Replica 2│◄────── Read
              │  (R/O)   │ │  (R/O)   │
              └──────────┘ └──────────┘

  Application 레벨 구현:
  ┌─────────────┐
  │   App Code  │
  │             │
  │ if write:   │──► primary-svc.db.svc:5432
  │ if read:    │──► replica-svc.db.svc:5432  (Service가 replica Pod로 LB)
  └─────────────┘
```

**복제 방식 비교:**

| 방식 | 지연 | 데이터 보장 | 성능 영향 |
|---|---|---|---|
| **동기(Synchronous)** | 없음 | 강한 일관성 | Primary 쓰기 느려짐 |
| **반동기(Semi-sync)** | 최소 | 1+개 replica 확인 | 약간 느려짐 |
| **비동기(Asynchronous)** | ms~sec | 유실 가능 | Primary 영향 없음 |

**Kubernetes에서의 Read/Write 분리:**
```
┌─────────────────────────────────────────────┐
│  Service 구성                                │
│                                             │
│  postgres-primary (ClusterIP)               │
│    → selector: role=primary                 │
│    → 쓰기 트래픽 전용                        │
│                                             │
│  postgres-replica (ClusterIP)               │
│    → selector: role=replica                 │
│    → 읽기 트래픽 전용                        │
│    → sessionAffinity: None (라운드 로빈)     │
│                                             │
│  또는 Operator가 자동으로 Service 관리        │
│  (CloudNativePG, Percona Operator)          │
└─────────────────────────────────────────────┘
```

### 3. Failover (장애 조치)

Primary 장애 시 자동으로 Replica를 승격시켜 서비스를 유지한다.

```
  정상 상태:
  App ──► Primary ──► Replica-1, Replica-2

  장애 발생:
  App ──► Primary (DEAD)
              │
              ▼
  ┌──────────────────────────────────────────┐
  │  Failover 과정 (Operator/Sentinel)       │
  │  1. 장애 감지 (health check 실패)        │
  │  2. 최신 데이터 가진 Replica 선택         │
  │  3. Replica → Primary 승격               │
  │  4. 나머지 Replica가 새 Primary를 follow  │
  │  5. Service endpoint 업데이트             │
  │  6. 구 Primary 복구 후 Replica로 합류     │
  └──────────────────────────────────────────┘

  복구 후:
  App ──► New Primary (구 Replica-1)
              │
              ▼
          Replica-2, Replica-3 (구 Primary)
```

**DB별 Failover 메커니즘:**

| DB | 메커니즘 | K8s Operator | 전환 시간 |
|---|---|---|---|
| **PostgreSQL** | Patroni / repmgr | CloudNativePG, Crunchy PGO | 5-15초 |
| **MySQL** | Group Replication | Percona XtraDB Operator | 10-30초 |
| **MongoDB** | ReplicaSet Election | Percona PSMDB Operator | 10-12초 |
| **Redis** | Sentinel / Cluster | Redis Operator | 5-10초 |

**CloudNativePG Failover 예시:**

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: alli-pg
spec:
  instances: 3
  primaryUpdateStrategy: unsupervised    # 자동 failover
  failoverDelay: 0                       # 즉시 failover
  postgresql:
    parameters:
      max_connections: "200"
      shared_buffers: "1GB"
      synchronous_commit: "on"           # 동기 복제
  monitoring:
    enablePodMonitor: true
  backup:
    barmanObjectStore:
      destinationPath: "s3://alli-pg-backup/"
      s3Credentials:
        accessKeyId:
          name: pg-backup-secret
          key: ACCESS_KEY_ID
        secretAccessKey:
          name: pg-backup-secret
          key: ACCESS_SECRET_KEY
```

### 4. Data Consistency Patterns (데이터 일관성 패턴)

분산 시스템에서 완벽한 일관성, 가용성, 파티션 허용성을 동시에 만족시킬 수 없다(CAP Theorem). 실무에서는 요구사항에 따라 일관성 수준을 선택한다.

```
          CAP Theorem
          ┌───────────┐
          │Consistency│
          └─────┬─────┘
               / \
              /   \
             /     \
   ┌────────┐       ┌──────────┐
   │  CA    │       │   CP     │
   │(RDBMS │       │(MongoDB  │
   │ 단일)  │       │ w:majority)
   └────────┘       └──────────┘
              \   /
               \ /
          ┌────┴────┐
          │   AP    │
          │(Cassandra│
          │ DynamoDB)│
          └─────────┘
     Availability    Partition Tolerance
```

**일관성 패턴 비교:**

| 패턴 | 설명 | 사용 사례 |
|---|---|---|
| **Strong Consistency** | 쓰기 후 모든 읽기에서 최신 값 보장 | 금융 거래, 재고 관리 |
| **Eventual Consistency** | 일정 시간 후 모든 노드 수렴 | 소셜 피드, 로그 |
| **Read-Your-Writes** | 쓴 사용자는 즉시 최신 값 확인 | 사용자 프로필 수정 |
| **Monotonic Reads** | 한 번 읽은 값보다 과거 값을 읽지 않음 | 대화 이력 조회 |
| **Causal Consistency** | 인과 관계가 있는 쓰기는 순서 보장 | 댓글-대댓글 관계 |

**실무 구현 패턴:**

```
  Read-Your-Writes 구현 (AI 대화 서비스):

  1. 사용자가 메시지 전송 (Write → Primary)
  2. 같은 사용자의 대화 이력 조회 → Primary에서 읽기
  3. 다른 사용자의 대화 분석 조회 → Replica에서 읽기

  구현 방법:
  ┌─────────────────────────────────────────┐
  │  // Application 레벨                    │
  │  if (request.userId == writer.userId    │
  │      && timeSince(lastWrite) < 5s) {    │
  │    query(PRIMARY);    // stale read 방지│
  │  } else {                               │
  │    query(REPLICA);    // 읽기 분산      │
  │  }                                      │
  └─────────────────────────────────────────┘
```

**분산 트랜잭션 패턴:**

```
  Saga Pattern (Choreography):
  ┌────────┐    event    ┌────────┐    event    ┌────────┐
  │Order   │ ──────────► │Payment │ ──────────► │AI Task │
  │Service │             │Service │             │Service │
  │        │ ◄────────── │        │ ◄────────── │        │
  └────────┘  compensate └────────┘  compensate └────────┘

  실패 시: 보상 트랜잭션(compensating transaction)으로 롤백
  - Order 취소 → Payment 환불 → AI Task 취소

  Outbox Pattern:
  ┌──────────────────────────┐
  │  Service A               │
  │  ┌────────┐ ┌──────────┐│     ┌─────────┐
  │  │ Table  │ │ Outbox   ││────►│  Kafka  │──► Service B
  │  │ (data) │ │ (events) ││ CDC │         │
  │  └────────┘ └──────────┘│     └─────────┘
  │  같은 DB 트랜잭션으로    │
  │  data + event 동시 저장  │
  └──────────────────────────┘
```

---

## 실전 예시

### Connection Pool 모니터링

```bash
# PgBouncer 상태 확인
psql -h localhost -p 6432 -U pgbouncer pgbouncer -c "SHOW POOLS;"
psql -h localhost -p 6432 -U pgbouncer pgbouncer -c "SHOW STATS;"

# MongoDB 연결 수 확인
mongosh --eval "db.serverStatus().connections"
# { current: 45, available: 51155, totalCreated: 1234 }

# Kubernetes에서 PgBouncer 메트릭 확인 (Prometheus)
# pgbouncer_pools_server_active_connections
# pgbouncer_pools_client_waiting_connections  ← 0이 아니면 pool 부족
```

### Failover 테스트 (CloudNativePG)

```bash
# 현재 Primary 확인
kubectl get pods -n db -l cnpg.io/cluster=alli-pg \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.role}{"\n"}{end}'

# Primary Pod 삭제로 failover 트리거
kubectl delete pod alli-pg-1 -n db

# failover 완료 확인 (새 Primary 선출)
kubectl get cluster alli-pg -n db -o jsonpath='{.status.currentPrimary}'

# switchover (계획된 전환, 더 안전)
kubectl cnpg promote alli-pg alli-pg-2 -n db
```

### Replication Lag 모니터링

```sql
-- PostgreSQL: replica lag 확인
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
       (extract(epoch from now()) - extract(epoch from replay_lag))::int AS lag_seconds
FROM pg_stat_replication;

-- MySQL: replica lag 확인
SHOW SLAVE STATUS\G
-- Seconds_Behind_Master 값 확인
```

---

## 면접 Q&A

### Q: Connection Pooling이 필요한 이유와 K8s 환경에서의 구현 방법을 설명해주세요.

**30초 답변**:
DB 연결 생성 비용이 크고, K8s에서는 Pod 수가 동적으로 변하므로 연결 폭발이 발생할 수 있습니다. Sidecar 패턴으로 PgBouncer를 Pod에 배치하면 앱 연결은 많아도 실제 DB 연결은 pool size로 제한되어 안정적입니다.

**2분 답변**:
DB 연결 하나당 TCP handshake, 인증, 메모리 할당(PostgreSQL은 연결당 ~10MB 프로세스)이 필요합니다. K8s 환경에서는 HPA로 Pod가 동적으로 증가하면 연결 수가 `Pod 수 x 앱 내 pool size`로 급증합니다. 예를 들어 50 Pod x 20 connections = 1000 연결인데, PostgreSQL의 기본 max_connections은 100입니다. 이를 해결하는 방법은 계층별로 다릅니다. 첫째, **Application Pool**(HikariCP 등)로 Pod 내부 연결을 관리합니다. 둘째, **Sidecar PgBouncer**로 여러 앱 연결을 소수의 DB 연결로 다중화합니다. Transaction pooling 모드를 사용하면 트랜잭션 단위로 연결을 공유하여 효율이 극대화됩니다. 셋째, AWS 환경에서는 **RDS Proxy**가 IAM 인증 + 자동 failover + connection pooling을 통합 제공합니다. 모니터링은 `client_waiting_connections` 메트릭이 핵심인데, 이 값이 0이 아니면 pool size가 부족하다는 신호입니다.

**💡 경험 연결**:
마이크로서비스 전환 후 서비스 수가 증가하면서 DB 연결 수가 max_connections를 초과하여 장애가 발생한 경험이 있습니다. PgBouncer를 도입하여 실제 DB 연결을 1/10로 줄이면서도 앱의 동시 처리량을 유지했습니다.

**⚠️ 주의**:
PgBouncer의 transaction pooling 모드에서는 prepared statement와 session-level 설정(SET)이 동작하지 않는다. ORM의 prepared statement 설정을 확인해야 한다.

### Q: DB Failover 시 애플리케이션의 다운타임을 최소화하는 방법은?

**30초 답변**:
Kubernetes Operator가 자동 failover를 수행하고, Service endpoint가 새 Primary로 업데이트됩니다. 애플리케이션은 connection retry 로직과 circuit breaker를 구현하여 failover 동안의 일시적 오류를 처리합니다.

**2분 답변**:
Failover 시 다운타임 최소화는 인프라와 애플리케이션 양쪽에서 준비해야 합니다. 인프라 측에서는, Operator(CloudNativePG, Percona)가 health check 실패를 감지하고 가장 최신 데이터를 가진 replica를 승격합니다. Service의 endpoint가 새 Primary Pod로 업데이트되므로, 애플리케이션은 DNS를 통해 자동으로 새 Primary에 연결됩니다. 이 과정은 보통 5-15초입니다. 애플리케이션 측에서는 세 가지 패턴이 필요합니다. 첫째, **Connection Retry**: exponential backoff로 재연결을 시도합니다. 둘째, **Circuit Breaker**: 연속 실패 시 빠르게 실패하여 연결 자원 소모를 방지합니다. 셋째, **Idempotent Operations**: failover 중 쓰기가 중복될 수 있으므로, 멱등성을 보장하는 설계(unique constraint, upsert)가 필요합니다. DNS cache TTL도 중요한데, Pod의 `dnsConfig.options`에서 `ndots: 2`와 짧은 TTL을 설정하면 endpoint 변경이 빠르게 반영됩니다.

**💡 경험 연결**:
PostgreSQL primary 장애 시 Patroni가 자동 failover를 수행했지만, 애플리케이션에 retry 로직이 없어 5초 동안 모든 요청이 500 에러를 반환한 경험이 있습니다. connection pool의 `connectionTimeout`과 retry 로직을 추가한 후 failover 시 사용자 체감 영향을 거의 없앨 수 있었습니다.

**⚠️ 주의**:
Failover 후 구 Primary가 복구되면 자동으로 Replica로 합류하는지(auto-rejoin), 수동 개입이 필요한지 Operator 동작을 확인해야 한다. 데이터 divergence가 있으면 수동 pg_rewind가 필요할 수 있다.

### Q: Eventual Consistency 환경에서 데이터 정합성을 보장하는 방법은?

**30초 답변**:
Read-Your-Writes 패턴으로 쓴 사용자는 Primary에서 읽고, 나머지는 Replica에서 읽습니다. 중요한 트랜잭션은 동기 복제를 사용하고, 서비스 간 데이터 일관성은 Saga 패턴이나 Outbox 패턴으로 보장합니다.

**2분 답변**:
Eventual Consistency는 성능과 가용성을 위해 일관성을 일시적으로 완화하는 것이므로, 비즈니스 요구사항에 따라 적절한 보장 수준을 선택해야 합니다. 첫째, **읽기 일관성**: Read-Your-Writes가 필요한 경우(사용자가 방금 보낸 메시지를 대화 이력에서 확인), 쓴 직후에는 Primary에서 읽거나 쓰기 시점의 LSN/oplog timestamp를 기록하여 Replica가 해당 시점까지 따라잡았는지 확인합니다. 둘째, **서비스 간 일관성**: 마이크로서비스에서 하나의 비즈니스 트랜잭션이 여러 DB에 걸칠 때 Saga 패턴을 사용합니다. 각 서비스가 로컬 트랜잭션을 수행하고, 실패 시 보상 트랜잭션으로 롤백합니다. 셋째, **이벤트 발행 보장**: DB 변경과 이벤트 발행의 원자성을 위해 Outbox 패턴을 사용합니다. 비즈니스 데이터와 이벤트를 같은 DB 트랜잭션으로 저장하고, CDC(Change Data Capture)로 이벤트를 Kafka에 발행합니다. Allganize 맥락에서, AI 대화 저장과 분석 파이프라인 트리거가 이 패턴의 좋은 사용 사례입니다.

**💡 경험 연결**:
비동기 복제 환경에서 사용자가 설정을 변경한 직후 새로고침했을 때 이전 값이 보이는 "stale read" 문제를 겪었습니다. Read-Your-Writes 패턴을 적용하여 최근 쓰기한 사용자의 읽기를 Primary로 라우팅하여 해결했습니다.

**⚠️ 주의**:
"Eventual Consistency는 데이터가 언젠가 맞춰진다"는 너무 단순한 설명. 구체적으로 어떤 보장(Read-Your-Writes, Monotonic Reads, Causal)이 필요한지 비즈니스 요구사항과 연결하여 답변해야 한다.

---

## Allganize 맥락

- **AI 서비스 DB 아키텍처**: Allganize의 Alli 서비스는 다수의 DB를 사용할 수 있다(PostgreSQL: 메인 데이터, MongoDB: 비정형 데이터, Elasticsearch: 검색, Redis: 캐시). 각 DB의 connection pooling과 failover 전략을 통합적으로 이해해야 한다.
- **멀티 테넌트 데이터 격리**: SaaS에서 tenant 간 데이터 격리는 필수. Row-Level Security(PostgreSQL), DB 분리, 또는 스키마 분리 중 적절한 전략을 선택해야 한다.
- **글로벌 서비스**: AWS/Azure 멀티 리전 서비스에서는 리전 간 replication lag이 수십~수백 ms가 될 수 있다. Causal Consistency 패턴이나 리전별 Primary 분리(Active-Active)를 고려해야 한다.
- **비용 최적화**: Read Replica를 Analytics 쿼리 전용으로 분리하면 Primary의 OLTP 성능을 보호하면서 AI 모델 학습/분석용 데이터 접근을 제공할 수 있다.
- **장애 대응 문화**: DB failover 시 자동 알림(PagerDuty/Slack), runbook 자동 실행, 사후 분석(post-mortem)까지 이어지는 프로세스를 갖추고 있음을 어필하면 좋다.

---
**핵심 키워드**: `Connection-Pooling` `PgBouncer` `Read-Replica` `Failover` `Eventual-Consistency` `Read-Your-Writes` `Saga-Pattern` `Outbox-Pattern` `CAP-Theorem` `CloudNativePG`
