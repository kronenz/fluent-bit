# StatefulSet + Storage — 상태 유지 워크로드 패턴

> **TL;DR**
> - StatefulSet은 volumeClaimTemplates로 각 Pod에 전용 PVC를 자동 생성하여 안정적인 스토리지 바인딩을 보장한다
> - 볼륨 확장(Volume Expansion)은 StorageClass의 allowVolumeExpansion과 CSI Driver 지원이 필요하며, 파일시스템 리사이즈까지 자동 수행된다
> - VolumeSnapshot은 CSI 기반의 시점 복구(Point-in-Time Recovery) 메커니즘으로, 백업과 클론에 활용한다

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### StatefulSet + PVC 패턴

StatefulSet은 Deployment와 달리 Pod에 고유한 정체성(Identity)을 부여하고, 각 Pod에 전용 PVC를 자동 생성한다.

```
[StatefulSet Storage 패턴]

StatefulSet: mongodb (replicas: 3)
│
├── Pod: mongodb-0 ──► PVC: data-mongodb-0 ──► PV: pvc-aaa ──► EBS vol-001
├── Pod: mongodb-1 ──► PVC: data-mongodb-1 ──► PV: pvc-bbb ──► EBS vol-002
└── Pod: mongodb-2 ──► PVC: data-mongodb-2 ──► PV: pvc-ccc ──► EBS vol-003

[Pod 재시작/재스케줄 시]
mongodb-1 삭제 → 재생성 → 같은 PVC(data-mongodb-1) 재마운트
                          데이터 보존됨 ✅

[Deployment와의 차이]
Deployment:  Pod-xyz-abc ──► PVC 공유 (RWX 필요) 또는 데이터 유실
StatefulSet: Pod-0, Pod-1  ──► 각자 전용 PVC (RWO 가능)
```

### StatefulSet + volumeClaimTemplates

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mongodb
  namespace: database
spec:
  serviceName: mongodb-headless    # Headless Service 필수
  replicas: 3
  selector:
    matchLabels:
      app: mongodb
  template:
    metadata:
      labels:
        app: mongodb
    spec:
      containers:
      - name: mongodb
        image: mongo:7.0
        ports:
        - containerPort: 27017
        volumeMounts:
        - name: data
          mountPath: /data/db
        - name: config
          mountPath: /data/configdb
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        env:
        - name: MONGO_INITDB_ROOT_USERNAME
          valueFrom:
            secretKeyRef:
              name: mongodb-secret
              key: username
        - name: MONGO_INITDB_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mongodb-secret
              key: password
  volumeClaimTemplates:            # 핵심: Pod별 PVC 자동 생성
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: gp3
      resources:
        requests:
          storage: 100Gi
  - metadata:
      name: config
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: gp3
      resources:
        requests:
          storage: 5Gi
---
# Headless Service (StatefulSet 필수)
apiVersion: v1
kind: Service
metadata:
  name: mongodb-headless
  namespace: database
spec:
  clusterIP: None              # Headless
  selector:
    app: mongodb
  ports:
  - port: 27017
    targetPort: 27017
```

### StatefulSet Pod의 DNS와 스토리지 정체성

```
[StatefulSet Identity]

Pod Name          DNS (Headless Service)                    PVC
─────────────────────────────────────────────────────────────────
mongodb-0         mongodb-0.mongodb-headless.database.svc   data-mongodb-0
mongodb-1         mongodb-1.mongodb-headless.database.svc   data-mongodb-1
mongodb-2         mongodb-2.mongodb-headless.database.svc   data-mongodb-2

순서 보장:
  생성: mongodb-0 → mongodb-1 → mongodb-2  (순차)
  삭제: mongodb-2 → mongodb-1 → mongodb-0  (역순)

Pod 재시작 시:
  mongodb-1 삭제 → 새 mongodb-1 생성
  → 같은 DNS, 같은 PVC(data-mongodb-1) 유지
  → 데이터 무손실
```

### StatefulSet 스케일링과 PVC

```
[Scale Up]
replicas: 3 → 4
  → mongodb-3 Pod 생성
  → data-mongodb-3 PVC 자동 생성
  → 새 EBS 볼륨 프로비저닝

[Scale Down]
replicas: 4 → 3
  → mongodb-3 Pod 삭제
  → data-mongodb-3 PVC는 삭제되지 않음 ⚠️
  → 수동으로 PVC 정리 필요 (데이터 보호 목적)

[다시 Scale Up]
replicas: 3 → 4
  → mongodb-3 Pod 생성
  → 기존 data-mongodb-3 PVC 재사용 ✅
  → 데이터 보존됨
```

---

## 볼륨 확장 (Volume Expansion)

### 요구 사항

```
[Volume Expansion 체크리스트]

1. StorageClass에 allowVolumeExpansion: true 설정
2. CSI Driver가 EXPAND_VOLUME capability 지원
3. 축소(Shrink)는 불가능 — 확장만 가능
4. 파일시스템 리사이즈는 kubelet이 자동 수행 (NodeExpandVolume)
```

### 볼륨 확장 절차

```bash
# 1. 현재 PVC 크기 확인
kubectl get pvc data-mongodb-0 -n database
# NAME              STATUS   VOLUME       CAPACITY   ACCESS MODES
# data-mongodb-0    Bound    pvc-aaa      100Gi      RWO

# 2. PVC 크기 수정 (100Gi → 200Gi)
kubectl patch pvc data-mongodb-0 -n database -p \
  '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'

# 3. 확장 진행 상태 확인
kubectl describe pvc data-mongodb-0 -n database
# Conditions:
#   Type                      Status
#   FileSystemResizePending   True     ← 파일시스템 리사이즈 대기 중

# 4. Pod 재시작 필요 여부 (CSI Driver에 따라 다름)
#    - EBS CSI: 온라인 확장 지원 (재시작 불필요)
#    - Azure Disk CSI: 온라인 확장 지원 (K8s 1.26+)
#    - 일부 CSI: Pod 삭제 후 재생성 필요

# 5. 확장 완료 확인
kubectl get pvc data-mongodb-0 -n database
# CAPACITY   200Gi   ← 확장 완료
```

```yaml
# 여러 PVC를 한 번에 확장하는 스크립트
# expand-pvcs.sh
#!/bin/bash
NAMESPACE="database"
NEW_SIZE="200Gi"

for i in 0 1 2; do
  echo "Expanding data-mongodb-${i}..."
  kubectl patch pvc "data-mongodb-${i}" -n ${NAMESPACE} -p \
    "{\"spec\":{\"resources\":{\"requests\":{\"storage\":\"${NEW_SIZE}\"}}}}"
done

# 확인
kubectl get pvc -n ${NAMESPACE}
```

### 볼륨 확장 흐름

```
[Volume Expansion Flow]

1. kubectl patch pvc (storage: 100Gi → 200Gi)
   │
   ▼
2. external-resizer Sidecar 감지
   │
   ▼
3. CSI Controller: ControllerExpandVolume()
   └── AWS: EBS ModifyVolume API 호출
   └── 블록 디바이스 크기 증가 (수 분 소요)
   │
   ▼
4. PVC Condition: FileSystemResizePending
   │
   ▼
5. kubelet (Node Plugin): NodeExpandVolume()
   └── resize2fs (ext4) 또는 xfs_growfs (xfs) 실행
   └── 파일시스템 크기 증가
   │
   ▼
6. PVC Capacity 업데이트: 200Gi ✅
```

---

## VolumeSnapshot (볼륨 스냅샷)

### 스냅샷 아키텍처

```
[VolumeSnapshot Architecture]

┌─────────────────┐     ┌─────────────────────┐
│ VolumeSnapshot   │────►│ VolumeSnapshotContent│
│ (사용자 요청)     │     │ (실제 스냅샷)         │
│                  │     │                     │
│ name: snap-01    │     │ snapshotHandle:     │
│ source:          │     │   snap-0abc123      │
│   pvc: data-0    │     │ (AWS EBS Snapshot)  │
└─────────────────┘     └─────────────────────┘
         │
         │  참조
         ▼
┌─────────────────┐
│ VolumeSnapshot   │
│ Class            │
│                  │
│ driver:          │
│   ebs.csi.aws.com│
│ deletionPolicy:  │
│   Retain         │
└─────────────────┘
```

### 스냅샷 생성 및 복원

```yaml
# 1. VolumeSnapshotClass 정의
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ebs-snapshot-class
driver: ebs.csi.aws.com
deletionPolicy: Retain         # 스냅샷 보존
parameters:
  tagSpecification_1: "Environment=production"
  tagSpecification_2: "ManagedBy=kubernetes"
---
# 2. VolumeSnapshot 생성 (특정 PVC의 스냅샷)
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: mongodb-data-snap-20240315
  namespace: database
spec:
  volumeSnapshotClassName: ebs-snapshot-class
  source:
    persistentVolumeClaimName: data-mongodb-0    # 소스 PVC
---
# 3. 스냅샷에서 새 PVC 복원
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-mongodb-0-restored
  namespace: database
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: gp3
  resources:
    requests:
      storage: 100Gi           # 원본 이상의 크기
  dataSource:
    name: mongodb-data-snap-20240315
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

```bash
# 스냅샷 상태 확인
kubectl get volumesnapshot -n database
# NAME                           READYTOUSE   SOURCEPVC        RESTORESIZE   AGE
# mongodb-data-snap-20240315     true         data-mongodb-0   100Gi         5m

# 스냅샷 상세 정보
kubectl describe volumesnapshot mongodb-data-snap-20240315 -n database

# 스냅샷에서 복원된 PVC 확인
kubectl get pvc data-mongodb-0-restored -n database
# STATUS   VOLUME       CAPACITY
# Bound    pvc-new123   100Gi
```

### 정기 스냅샷 자동화 (CronJob)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mongodb-snapshot
  namespace: database
spec:
  schedule: "0 2 * * *"        # 매일 새벽 2시
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: snapshot-creator
          containers:
          - name: snapshot
            image: bitnami/kubectl:1.29
            command:
            - /bin/sh
            - -c
            - |
              TIMESTAMP=$(date +%Y%m%d-%H%M%S)
              for i in 0 1 2; do
                cat <<SNAP | kubectl apply -f -
              apiVersion: snapshot.storage.k8s.io/v1
              kind: VolumeSnapshot
              metadata:
                name: mongodb-data-${i}-${TIMESTAMP}
                namespace: database
              spec:
                volumeSnapshotClassName: ebs-snapshot-class
                source:
                  persistentVolumeClaimName: data-mongodb-${i}
              SNAP
              done
              # 7일 이상 된 스냅샷 정리
              kubectl get volumesnapshot -n database \
                --sort-by=.metadata.creationTimestamp \
                -o name | head -n -21 | xargs -r kubectl delete -n database
          restartPolicy: OnFailure
```

---

## 실전 예시

### Elasticsearch StatefulSet 패턴

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
  namespace: logging
spec:
  serviceName: elasticsearch-headless
  replicas: 3
  podManagementPolicy: Parallel    # ES는 순서 불필요, 병렬 시작
  selector:
    matchLabels:
      app: elasticsearch
  template:
    metadata:
      labels:
        app: elasticsearch
    spec:
      initContainers:
      - name: fix-permissions
        image: busybox:1.36
        command: ["sh", "-c", "chown -R 1000:1000 /usr/share/elasticsearch/data"]
        volumeMounts:
        - name: data
          mountPath: /usr/share/elasticsearch/data
      - name: increase-vm-max-map
        image: busybox:1.36
        command: ["sysctl", "-w", "vm.max_map_count=262144"]
        securityContext:
          privileged: true
      containers:
      - name: elasticsearch
        image: elasticsearch:8.12.0
        ports:
        - containerPort: 9200
        - containerPort: 9300
        env:
        - name: node.name
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: cluster.name
          value: "es-cluster"
        - name: discovery.seed_hosts
          value: "elasticsearch-headless"
        - name: cluster.initial_master_nodes
          value: "elasticsearch-0,elasticsearch-1,elasticsearch-2"
        - name: ES_JAVA_OPTS
          value: "-Xms2g -Xmx2g"
        volumeMounts:
        - name: data
          mountPath: /usr/share/elasticsearch/data
        resources:
          requests:
            cpu: "1"
            memory: "4Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: gp3-high-iops    # 높은 IOPS 필요
      resources:
        requests:
          storage: 500Gi
```

---

## 면접 Q&A

### Q1: "StatefulSet의 volumeClaimTemplates가 Deployment와 다른 점은?"

**30초 답변**:
Deployment는 모든 Pod이 하나의 PVC를 공유하거나 각 Pod마다 수동으로 PVC를 생성해야 합니다. StatefulSet의 volumeClaimTemplates는 Pod 생성 시 자동으로 전용 PVC를 만들어 주며, Pod 재시작 시에도 같은 PVC를 재마운트하여 데이터를 보존합니다.

**2분 답변**:
volumeClaimTemplates는 StatefulSet의 핵심 기능입니다. Pod 이름이 ordinal index(0, 1, 2)로 고정되는 것처럼, PVC도 `{template-name}-{statefulset-name}-{index}` 형식으로 고정됩니다.

예를 들어 StatefulSet `mongodb`의 volumeClaimTemplate `data`는 `data-mongodb-0`, `data-mongodb-1`, `data-mongodb-2` PVC를 자동 생성합니다. mongodb-1 Pod가 삭제되고 재생성되면, 새 Pod은 기존 `data-mongodb-1` PVC를 다시 마운트합니다.

Scale Down 시 PVC는 삭제되지 않습니다. 이는 의도적인 설계로, 데이터 보호가 목적입니다. 다시 Scale Up하면 기존 PVC가 재사용됩니다. 불필요한 PVC는 관리자가 수동으로 삭제해야 합니다.

Deployment는 이런 보장이 없습니다. ReplicaSet은 Pod에 랜덤한 이름을 부여하므로 특정 PVC에 대한 안정적인 바인딩이 불가능합니다. 따라서 DB, 메시지 큐 등 상태 유지가 필요한 워크로드는 StatefulSet을 사용합니다.

**💡 경험 연결**:
온프레미스에서 DB 서버의 데이터 볼륨을 서버에 고정 마운트하여 운영했던 것과 같은 개념입니다. StatefulSet은 이러한 "서버-볼륨 고정 매핑"을 Kubernetes에서 자동화한 것입니다.

**⚠️ 주의**:
StatefulSet을 삭제해도 PVC는 남는다. `kubectl delete statefulset mongodb`는 Pod만 삭제하고 PVC는 보존한다. PVC까지 삭제하려면 별도로 `kubectl delete pvc -l app=mongodb`를 실행해야 한다.

### Q2: "운영 중인 PVC의 크기를 확장하는 방법은?"

**30초 답변**:
StorageClass에 allowVolumeExpansion이 true로 설정되어 있으면, PVC의 spec.resources.requests.storage 값을 kubectl patch로 증가시킵니다. EBS CSI는 온라인 확장을 지원하므로 Pod 재시작 없이 확장됩니다.

**2분 답변**:
볼륨 확장은 두 단계로 진행됩니다.

첫째, 블록 디바이스 확장입니다. PVC의 storage 값을 변경하면 CSI Controller가 클라우드 API를 호출하여 실제 볼륨 크기를 늘립니다. AWS EBS는 ModifyVolume API, Azure Disk는 Disk Update API를 사용합니다.

둘째, 파일시스템 확장입니다. kubelet의 Node Plugin이 resize2fs(ext4) 또는 xfs_growfs(XFS)를 실행하여 파일시스템을 확장합니다. 이 과정은 자동이며, PVC의 Condition이 FileSystemResizePending에서 정상으로 변경됩니다.

주의할 점은 축소(Shrink)가 불가능하다는 것입니다. 한 번 확장하면 줄일 수 없으므로 적절한 크기를 신중히 결정해야 합니다. 또한 EBS는 볼륨 수정 후 6시간 쿨다운이 있어 연속 확장이 불가합니다.

StatefulSet의 volumeClaimTemplates 크기는 이미 생성된 PVC에 영향을 주지 않습니다. 기존 PVC는 개별적으로 patch해야 하고, template 변경은 새로 생성되는 PVC에만 적용됩니다.

**💡 경험 연결**:
온프레미스에서 LVM으로 논리 볼륨을 확장했던 경험이 있습니다. `lvextend` + `resize2fs`의 조합이 Kubernetes에서는 CSI + kubelet으로 자동화된 것입니다.

**⚠️ 주의**:
volumeClaimTemplates의 storage 값을 변경해도 기존 PVC는 변경되지 않는다. 새로운 replicas에만 적용된다. 기존 PVC 확장은 반드시 개별 patch가 필요하다.

### Q3: "VolumeSnapshot의 활용 사례와 제약 사항은?"

**30초 답변**:
VolumeSnapshot은 PVC의 시점 복사본(Point-in-Time Copy)입니다. DB 백업, 데이터 클론, 블루/그린 마이그레이션에 활용합니다. 제약 사항은 CSI Driver 지원이 필요하고, 스냅샷 생성 시 I/O 일시 중단이 발생할 수 있으며, cross-namespace 복원이 불가능합니다.

**2분 답변**:
VolumeSnapshot은 세 가지 Kubernetes 리소스로 구성됩니다. VolumeSnapshotClass(스냅샷 정책), VolumeSnapshot(사용자 요청), VolumeSnapshotContent(실제 스냅샷)입니다. PV/PVC/StorageClass와 동일한 패턴입니다.

활용 사례는 첫째, DB 백업입니다. CronJob으로 정기적으로 VolumeSnapshot을 생성하고, 장애 시 스냅샷에서 새 PVC를 프로비저닝하여 복원합니다. 둘째, 테스트 데이터 준비입니다. 운영 DB의 스냅샷으로 테스트 환경의 PVC를 생성하면 실제 데이터로 테스트할 수 있습니다. 셋째, 볼륨 마이그레이션입니다. 스냅샷에서 다른 StorageClass의 PVC를 생성하여 스토리지 타입을 변경할 수 있습니다.

제약 사항은 CSI Driver가 CREATE_DELETE_SNAPSHOT capability를 지원해야 합니다. 스냅샷은 같은 namespace 내에서만 복원 가능합니다. 또한 애플리케이션 수준의 일관성(Consistency)은 보장하지 않으므로, DB의 경우 스냅샷 전에 fsync나 flush를 수행하는 것이 안전합니다.

**💡 경험 연결**:
스토리지 어레이의 스냅샷 기능을 사용하여 백업과 복원을 수행했던 경험이 있습니다. VolumeSnapshot은 이를 Kubernetes API로 표준화한 것이며, CSI Driver가 실제 스냅샷 생성을 스토리지 백엔드에 위임합니다.

**⚠️ 주의**:
VolumeSnapshot은 crash-consistent이지 application-consistent가 아니다. MongoDB의 경우 `db.fsyncLock()`으로 쓰기를 중단한 후 스냅샷을 생성하는 것이 안전하다.

---

## Allganize 맥락

| JD 요구사항 | 연결 포인트 |
|------------|------------|
| AI/LLM 서비스 운영 | Elasticsearch/MongoDB StatefulSet으로 벡터 DB 운영 |
| 복원력(Resilience) | VolumeSnapshot 기반 정기 백업 + 빠른 복원 |
| AWS/Azure K8s | EBS/Azure Disk의 온라인 볼륨 확장 활용 |
| 데이터 관리 | StatefulSet Scale Down 시 PVC 보존으로 데이터 보호 |
| 성능 최적화 | gp3 IOPS/Throughput 파라미터 튜닝으로 DB 성능 확보 |

Allganize의 Alli 서비스는 Elasticsearch(검색), MongoDB(메타데이터)를 StatefulSet으로 운영할 가능성이 높다. LLM의 벡터 데이터베이스도 StatefulSet 패턴으로 운영되며, 데이터 증가에 따른 볼륨 확장과 정기 스냅샷 백업이 필수적이다.

---

**핵심 키워드**: `StatefulSet` `volumeClaimTemplates` `Volume Expansion` `VolumeSnapshot` `ordinal index` `Headless Service` `podManagementPolicy` `allowVolumeExpansion`
