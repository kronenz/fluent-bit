# etcd Deep Dive

> **TL;DR**: etcd는 Kubernetes 클러스터의 모든 상태를 저장하는 분산 Key-Value 스토어로, Raft consensus 알고리즘으로 일관성을 보장한다.
> 백업/복구는 etcdctl snapshot으로 수행하며, 정기 백업은 클러스터 운영의 생명선이다.
> 성능 튜닝의 핵심은 SSD 사용, 전용 디스크, 적절한 compaction과 defrag이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### etcd 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                  etcd Cluster (3 nodes)              │
│                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐      │
│  │  etcd-1   │    │  etcd-2   │    │  etcd-3   │      │
│  │ (Leader)  │◄──►│(Follower) │◄──►│(Follower) │      │
│  │           │    │           │    │           │      │
│  │  WAL      │    │  WAL      │    │  WAL      │      │
│  │  Snap     │    │  Snap     │    │  Snap     │      │
│  │  DB(boltdb)│   │  DB(boltdb)│   │  DB(boltdb)│     │
│  └──────────┘    └──────────┘    └──────────┘      │
│       ▲                                             │
│       │  Raft Log Replication                       │
│       │  (Leader → Followers)                       │
└───────┼─────────────────────────────────────────────┘
        │
   kube-apiserver (유일한 클라이언트)
```

### Raft Consensus 알고리즘

Raft는 **Leader 기반 합의 프로토콜**로, 분산 환경에서 데이터 일관성을 보장한다.

**3가지 역할:**
- **Leader**: 모든 쓰기 요청을 처리하고 Follower에 복제
- **Follower**: Leader의 로그를 수신하고 적용
- **Candidate**: Leader 선출을 시도하는 상태

**Leader Election 과정:**
```
시간 ──────────────────────────────────────────────►

Node-1: Follower ──[timeout]──► Candidate ──[과반수 투표]──► Leader
Node-2: Follower ──────────────► 투표(vote) ─────────────► Follower
Node-3: Follower ──────────────► 투표(vote) ─────────────► Follower

Term 1                          Term 2
```

**쓰기 과정 (Log Replication):**
```
Client ──► Leader
              │
              ├─ 1. WAL에 로그 기록
              │
              ├─ 2. Follower들에게 AppendEntries RPC
              │     ┌──► Follower-1: WAL 기록, ACK
              │     └──► Follower-2: WAL 기록, ACK
              │
              ├─ 3. Quorum(2/3) 확인 후 Commit
              │
              └─ 4. Client에 응답 + State Machine(boltdb) 적용
```

**Quorum 계산:**

| 클러스터 크기 | Quorum | 허용 장애 수 |
|--------------|--------|-------------|
| 1 | 1 | 0 |
| 3 | 2 | 1 |
| 5 | 3 | 2 |
| 7 | 4 | 3 |

> 짝수 노드는 비추천: 4노드는 3노드와 동일하게 1노드 장애만 허용하면서 네트워크 오버헤드만 증가.

### etcd 데이터 저장 구조

```
/var/lib/etcd/
├── member/
│   ├── wal/           ← Write-Ahead Log (순차 쓰기, 내구성 보장)
│   │   ├── 0000000000000000-0000000000000000.wal
│   │   └── 0000000000000001-0000000000001000.wal
│   └── snap/          ← Snapshot (주기적 상태 덤프)
│       └── 0000000000000002-0000000000001000.snap
```

- **WAL**: 모든 변경사항을 순차적으로 기록. 크래시 복구에 사용
- **Snapshot**: WAL이 일정 크기가 되면 상태를 스냅샷으로 저장하고 오래된 WAL 삭제
- **boltdb**: 실제 Key-Value 데이터를 저장하는 B+ 트리 기반 임베디드 DB

### MVCC (Multi-Version Concurrency Control)

etcd는 모든 키의 **모든 버전**을 보관한다 (compaction 전까지).

```
Key: /registry/pods/default/my-pod

Revision 100: {spec: {replicas: 1}}   ← 생성
Revision 150: {spec: {replicas: 3}}   ← 업데이트
Revision 200: {spec: {replicas: 5}}   ← 업데이트
                                       ← 현재 revision

→ Compaction(rev=150) 이후: rev 100의 데이터 삭제
→ Watch는 특정 revision부터의 변경사항을 스트리밍 가능
```

### 장애 시나리오

**시나리오 1: Leader 장애**
```
etcd-1(Leader) ✗ DOWN
    │
    ▼
etcd-2, etcd-3: election timeout 초과
    │
    ▼
etcd-2 → Candidate (Term 증가, RequestVote)
    │
    ▼
etcd-3 → 투표
    │
    ▼
etcd-2 → 새 Leader (수 초 내 복구)
```

**시나리오 2: 네트워크 파티션**
```
 [Partition A]          [Partition B]
 etcd-1 (Leader)        etcd-2, etcd-3
     │                       │
     ▼                       ▼
 Quorum 불가 (1/3)      새 Leader 선출 (2/3 quorum)
 읽기만 가능 (stale)     정상 운영
     │                       │
     ▼                       ▼
 apiserver timeout       apiserver 전환
```

**시나리오 3: 디스크 I/O 병목**
```
증상: etcd latency 증가 → apiserver timeout → kubectl 응답 지연
원인: WAL 쓰기 지연 (HDD, 다른 프로세스와 디스크 공유)
해결: SSD 전용 디스크, I/O 스케줄러 조정, 디스크 공유 금지
```

---

## 실전 예시

### etcd 클러스터 상태 확인

```bash
# 멤버 목록 확인
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  member list -w table

# 클러스터 건강 상태
ETCDCTL_API=3 etcdctl \
  --endpoints=https://etcd-1:2379,https://etcd-2:2379,https://etcd-3:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health -w table

# 리더 확인
ETCDCTL_API=3 etcdctl \
  --endpoints=https://etcd-1:2379,https://etcd-2:2379,https://etcd-3:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table
```

### 백업 (Snapshot)

```bash
# 스냅샷 생성
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /backup/etcd-$(date +%Y%m%d-%H%M%S).db

# 스냅샷 검증
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-20240101-120000.db -w table

# CronJob으로 자동 백업 (예시)
# 0 */6 * * * /usr/local/bin/etcd-backup.sh
```

### 복구 (Restore)

```bash
# 1. 모든 etcd 멤버 중지
systemctl stop etcd  # 또는 static pod의 매니페스트 이동

# 2. 각 노드에서 스냅샷 복구
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot.db \
  --name etcd-1 \
  --initial-cluster etcd-1=https://10.0.1.1:2380,etcd-2=https://10.0.1.2:2380,etcd-3=https://10.0.1.3:2380 \
  --initial-cluster-token etcd-cluster-1 \
  --initial-advertise-peer-urls https://10.0.1.1:2380 \
  --data-dir /var/lib/etcd-restored

# 3. 데이터 디렉토리 교체
mv /var/lib/etcd /var/lib/etcd-old
mv /var/lib/etcd-restored /var/lib/etcd

# 4. etcd 재시작
systemctl start etcd
```

### 성능 튜닝

```bash
# 디스크 I/O 성능 측정 (WAL은 fsync 성능이 핵심)
fio --rw=write --ioengine=sync --fdatasync=1 \
    --directory=/var/lib/etcd --size=22m \
    --bs=2300 --name=etcd-fio

# 권장: fsync 99th percentile < 10ms

# etcd 메트릭 확인 (Prometheus)
curl -s https://127.0.0.1:2379/metrics \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key | grep -E 'etcd_disk|etcd_network'

# 주요 메트릭:
# etcd_disk_wal_fsync_duration_seconds    ← 10ms 이하 유지
# etcd_disk_backend_commit_duration_seconds
# etcd_network_peer_round_trip_time_seconds
# etcd_server_proposals_failed_total
```

### Compaction & Defragmentation

```bash
# 수동 compaction (revision 기반)
rev=$(ETCDCTL_API=3 etcdctl endpoint status --write-out="json" | \
  python3 -c "import sys,json; print(json.loads(sys.stdin.read())[0]['Status']['header']['revision'])")

ETCDCTL_API=3 etcdctl compact $rev

# Auto-compaction 설정 (etcd 시작 옵션)
# --auto-compaction-retention=1h  (1시간 이전 리비전 자동 삭제)
# --auto-compaction-mode=periodic

# Defragmentation (각 노드에서 순차적으로 실행)
ETCDCTL_API=3 etcdctl \
  --endpoints=https://etcd-1:2379 \
  defrag

# DB 크기 확인
ETCDCTL_API=3 etcdctl endpoint status -w table
# DB SIZE 컬럼 확인, 기본 quota는 2GB (--quota-backend-bytes)
```

### etcd 알람 처리

```bash
# 알람 확인 (NOSPACE 등)
ETCDCTL_API=3 etcdctl alarm list

# DB 크기 초과(NOSPACE) 시 복구 절차:
# 1. Compaction 실행
ETCDCTL_API=3 etcdctl compact $(ETCDCTL_API=3 etcdctl endpoint status -w json | python3 -c "import sys,json; print(json.loads(sys.stdin.read())[0]['Status']['header']['revision'])")

# 2. Defrag 실행
ETCDCTL_API=3 etcdctl defrag --endpoints=https://etcd-1:2379,https://etcd-2:2379,https://etcd-3:2379

# 3. 알람 해제
ETCDCTL_API=3 etcdctl alarm disarm
```

---

## 면접 Q&A

### Q: Raft consensus 알고리즘을 간단히 설명해주세요.
**30초 답변**:
Raft는 Leader 기반 합의 알고리즘으로, Leader가 모든 쓰기를 처리하고 Follower에 복제합니다. 과반수(Quorum)가 확인(ACK)하면 커밋합니다. Leader가 죽으면 Follower 중 하나가 새 Leader로 선출됩니다.

**2분 답변**:
Raft는 분산 시스템에서 로그 복제를 통해 일관성을 보장하는 합의 알고리즘입니다. 세 가지 핵심 메커니즘이 있습니다. 첫째, Leader Election입니다. Follower가 heartbeat timeout 내에 Leader로부터 메시지를 받지 못하면 Candidate가 되어 투표를 요청하고, 과반수 표를 받으면 Leader가 됩니다. Term(임기) 개념으로 오래된 Leader의 요청을 거부합니다. 둘째, Log Replication입니다. 클라이언트의 쓰기 요청은 Leader가 받아 WAL에 기록하고, AppendEntries RPC로 Follower에 전파합니다. Quorum(N/2+1)이 WAL 기록을 확인하면 커밋하고 State Machine(boltdb)에 적용합니다. 셋째, Safety입니다. 가장 최신 로그를 가진 노드만 Leader가 될 수 있어 커밋된 데이터의 손실을 방지합니다. etcd에서는 3노드가 표준이며 1노드 장애를 허용합니다. 5노드면 2노드 장애를 허용하지만, 쓰기 latency가 증가합니다. Raft의 강점은 Paxos 대비 이해하기 쉽고 구현이 명확하다는 점입니다.

**경험 연결**:
3노드 etcd 클러스터에서 2노드가 동시에 디스크 장애를 겪어 quorum이 깨진 경험이 있습니다. 이때 마지막 정상 스냅샷으로 단일 노드를 복구하고, 나머지 멤버를 추가하여 클러스터를 재구성했습니다. 이 경험으로 정기 백업의 중요성을 절감했습니다.

**주의**:
"Leader에게 모든 읽기/쓰기가 간다"는 기본 동작이지만, etcd는 `--read-only` 설정이나 Serializable Read 옵션으로 Follower에서 읽기를 허용할 수 있다. 다만 이 경우 stale read 가능성이 있다.

### Q: etcd 백업/복구 절차를 설명해주세요.
**30초 답변**:
`etcdctl snapshot save`로 스냅샷을 생성하고, 복구 시 `etcdctl snapshot restore`로 새 데이터 디렉토리를 만듭니다. 각 etcd 멤버에서 동일한 스냅샷으로 복구하고, initial-cluster 정보를 맞추어 재시작합니다.

**2분 답변**:
백업은 `etcdctl snapshot save` 명령으로 수행하며, etcd의 boltdb 전체를 일관된 상태로 파일에 저장합니다. TLS 인증서가 필요하며, Leader 노드에서 실행하는 것이 권장됩니다. 운영 환경에서는 CronJob으로 6시간 또는 1시간 간격으로 백업하고, S3 같은 외부 저장소에 보관합니다. 복구 절차는 다음과 같습니다: (1) 모든 etcd 프로세스를 중지합니다. (2) 각 노드에서 `etcdctl snapshot restore`를 실행하되, --name, --initial-cluster, --initial-advertise-peer-urls를 각 노드에 맞게 지정합니다. (3) 새로 생성된 데이터 디렉토리로 교체합니다. (4) etcd를 재시작합니다. 중요한 점은 스냅샷에 etcd 멤버 정보가 포함되지 않으므로, restore 시 새 클러스터로 초기화된다는 것입니다. 또한 스냅샷 시점 이후의 변경은 유실되므로, 복구 후 애플리케이션 상태를 확인해야 합니다.

**경험 연결**:
주기적 백업을 설정하지 않았던 초기에 etcd 데이터 디렉토리 손상을 겪은 적이 있습니다. 이후 백업 스크립트와 검증 절차를 자동화하고, 분기별로 복구 훈련(DR drill)을 실시하여 실제 장애 시 30분 이내 복구가 가능하도록 만들었습니다.

**주의**:
EKS/AKS에서는 etcd를 직접 관리하지 않으므로, etcd 백업/복구를 직접 수행할 일은 없다. 하지만 원리를 이해하면 Velero 같은 K8s 리소스 백업 도구의 한계를 파악할 수 있다.

### Q: etcd 성능이 저하될 때 어떻게 진단하고 해결하나요?
**30초 답변**:
etcd의 `etcd_disk_wal_fsync_duration_seconds` 메트릭을 확인하여 디스크 I/O 병목을 진단합니다. SSD 전용 디스크 사용, 정기적 compaction/defrag 실행, DB 크기 모니터링이 핵심입니다.

**2분 답변**:
etcd 성능 저하의 주요 원인과 해결 방법을 단계별로 접근합니다. 먼저 디스크 I/O입니다. `etcd_disk_wal_fsync_duration_seconds`의 99th percentile이 10ms를 초과하면 WAL 쓰기가 병목입니다. 해결책은 SSD 전용 디스크를 할당하고, I/O 스케줄러를 noop/none으로 설정하는 것입니다. 다음으로 DB 크기입니다. etcd의 기본 quota는 2GB이며, 초과하면 NOSPACE 알람이 발생하고 쓰기가 차단됩니다. auto-compaction을 활성화하고, 주기적으로 defrag을 실행합니다. 네트워크 지연도 원인이 될 수 있습니다. `etcd_network_peer_round_trip_time_seconds`가 높으면 노드 간 통신이 느린 것입니다. etcd 노드는 같은 AZ 또는 가까운 네트워크에 배치해야 합니다. 마지막으로 요청 과부하입니다. 대량의 watch나 list 요청이 etcd에 부하를 줄 수 있으므로, apiserver의 --watch-cache-sizes와 etcd의 rate limiter 설정을 조정합니다. 모니터링은 etcd의 `/metrics` 엔드포인트를 Prometheus로 수집하고 Grafana 대시보드를 구성합니다.

**경험 연결**:
etcd와 다른 프로세스가 같은 디스크를 공유하면서 WAL fsync 지연이 100ms를 넘었던 경험이 있습니다. etcd 전용 NVMe SSD를 할당하고 `ionice -c2 -n0`으로 I/O 우선순위를 높여 해결했습니다. 이후 모니터링 대시보드에 etcd 디스크 메트릭을 추가하여 사전 예방이 가능해졌습니다.

**주의**:
defrag는 etcd를 잠시 멈추게 할 수 있으므로, 반드시 한 노드씩 순차적으로 실행해야 한다. 동시에 모든 노드를 defrag하면 클러스터가 일시 중단될 수 있다.

---

## Allganize 맥락

- **EKS/AKS의 etcd**: Managed Kubernetes에서는 etcd를 직접 관리하지 않지만, etcd의 원리를 이해하면 "kubectl이 느려졌다" 같은 문제의 근본 원인을 추론할 수 있다. apiserver latency가 높으면 etcd 병목을 의심하고, 클라우드 제공자의 Control Plane 모니터링을 활용할 수 있다.
- **Kubernetes 리소스 크기 관리**: Allganize의 AI 파이프라인에서 ConfigMap이나 Secret에 대용량 모델 설정을 저장하면 etcd 부하가 증가한다. 1MB 이상의 데이터는 etcd에 저장하지 않고 S3나 외부 스토리지를 사용해야 한다 (etcd 단일 값 제한: 1.5MB).
- **백업 전략**: 비록 etcd를 직접 관리하지 않더라도, Velero로 K8s 리소스를 백업하는 것은 필수다. etcd 스냅샷과 Velero 백업의 차이를 이해하는 것이 중요하다.
- **폐쇄망 경험 활용**: 온프레미스에서 etcd를 직접 운영한 경험은 클러스터 장애 시 "etcd가 원인인가?"를 빠르게 판단할 수 있는 역량으로 연결된다.

---
**핵심 키워드**: `etcd` `Raft-consensus` `quorum` `WAL` `snapshot` `compaction` `defragmentation` `MVCC` `backup-restore`
