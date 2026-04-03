# 05. 쿠버네티스 스토리지 (Storage in Kubernetes)

> **TL;DR**
> - K8s 스토리지는 **PV(인프라) → PVC(요청) → Pod(사용)** 3단계로 분리되어 있다.
> - **StorageClass**와 **CSI 드라이버**로 동적 프로비저닝하면 수동 PV 생성이 필요 없다.
> - **StatefulSet + volumeClaimTemplates** 패턴이 유상태 워크로드 스토리지의 표준이다.

---

## 1. 스토리지 아키텍처 개요

```
┌─── 인프라 관리자 ───┐     ┌─── 개발자/사용자 ───┐     ┌─── 워크로드 ───┐
│                     │     │                     │     │               │
│  PersistentVolume   │ ←→  │ PersistentVolumeClaim│ ←→  │     Pod       │
│  (PV)               │     │ (PVC)               │     │               │
│  실제 스토리지 정의  │     │ "이만큼 필요해요"     │     │ 볼륨 마운트    │
│                     │     │                     │     │               │
└─────────────────────┘     └─────────────────────┘     └───────────────┘
         ↑
    StorageClass
    (자동 프로비저닝)
```

---

## 2. PersistentVolume (PV)

**클러스터 레벨의 스토리지 리소스**다. 관리자가 생성하거나 StorageClass가 자동 생성한다.

```yaml
# 수동 PV 생성 (온프레미스 NFS 예시)
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-pv-01
spec:
  capacity:
    storage: 100Gi
  accessModes:
  - ReadWriteMany                  # 여러 Pod에서 동시 읽기/쓰기
  persistentVolumeReclaimPolicy: Retain   # PVC 삭제 후에도 데이터 보존
  storageClassName: nfs
  nfs:
    server: 10.0.1.100
    path: /exports/data01
---
# 로컬 디스크 PV (고성능 요구 시)
apiVersion: v1
kind: PersistentVolume
metadata:
  name: local-pv-ssd
spec:
  capacity:
    storage: 500Gi
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-ssd
  local:
    path: /mnt/ssd/data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - worker-node-01
```

### Access Modes

| 모드 | 약자 | 설명 |
|------|------|------|
| **ReadWriteOnce** | RWO | 단일 노드에서 읽기/쓰기 |
| **ReadOnlyMany** | ROX | 여러 노드에서 읽기 전용 |
| **ReadWriteMany** | RWX | 여러 노드에서 읽기/쓰기 |
| **ReadWriteOncePod** | RWOP | 단일 Pod에서만 읽기/쓰기 (K8s 1.27+) |

### Reclaim Policy

| 정책 | 동작 |
|------|------|
| **Retain** | PVC 삭제해도 PV와 데이터 유지 (수동 정리) |
| **Delete** | PVC 삭제 시 PV와 스토리지 함께 삭제 |
| **Recycle** | 데이터 삭제 후 재사용 (deprecated) |

---

## 3. PersistentVolumeClaim (PVC)

**사용자가 스토리지를 요청**하는 리소스다. PV와 바인딩된다.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-data-pvc
  namespace: production
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: nfs
  resources:
    requests:
      storage: 50Gi             # 필요한 용량
```

```yaml
# Pod에서 PVC 사용
apiVersion: v1
kind: Pod
metadata:
  name: app-pod
spec:
  containers:
  - name: app
    image: myapp:1.0
    volumeMounts:
    - name: data
      mountPath: /app/data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: app-data-pvc     # PVC 이름 참조
```

```bash
# PV/PVC 상태 확인
kubectl get pv
kubectl get pvc -n production

# 바인딩 상태 확인
kubectl describe pvc app-data-pvc -n production

# PV-PVC 매핑 확인
kubectl get pv -o custom-columns='NAME:.metadata.name,CAPACITY:.spec.capacity.storage,STATUS:.status.phase,CLAIM:.spec.claimRef.name'
```

---

## 4. StorageClass와 동적 프로비저닝

**StorageClass**를 정의하면 PVC 생성 시 **PV가 자동으로 생성**된다.

```yaml
# NFS 동적 프로비저닝 (nfs-subdir-external-provisioner)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-dynamic
provisioner: nfs-subdir-external-provisioner
parameters:
  archiveOnDelete: "true"          # 삭제 시 백업 디렉토리로 이동
  pathPattern: "${.PVC.namespace}/${.PVC.name}"
reclaimPolicy: Delete
volumeBindingMode: Immediate
---
# 로컬 스토리지 StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-ssd
provisioner: kubernetes.io/no-provisioner   # 수동 PV 필요
volumeBindingMode: WaitForFirstConsumer     # Pod 스케줄링 후 바인딩
---
# Ceph RBD StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: ceph-cluster-1
  pool: kubernetes
  imageFormat: "2"
  imageFeatures: layering
  csi.storage.k8s.io/provisioner-secret-name: csi-rbd-secret
  csi.storage.k8s.io/provisioner-secret-namespace: ceph-system
reclaimPolicy: Delete
allowVolumeExpansion: true            # 볼륨 확장 허용
```

### volumeBindingMode 비교

| 모드 | 동작 | 사용 시나리오 |
|------|------|--------------|
| **Immediate** | PVC 생성 즉시 PV 바인딩 | NFS, 클라우드 스토리지 |
| **WaitForFirstConsumer** | Pod 스케줄링 후 바인딩 | 로컬 스토리지, 토폴로지 제약 |

```bash
# 기본 StorageClass 설정
kubectl patch storageclass nfs-dynamic \
  -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

# StorageClass 목록 확인
kubectl get storageclass
```

---

## 5. CSI (Container Storage Interface) 드라이버

**CSI**는 K8s와 스토리지 시스템 간의 표준 인터페이스다.

```
┌─── Kubernetes ───┐     ┌─── CSI Driver ───┐     ┌─── Storage ───┐
│                  │     │                   │     │               │
│  kubelet         │ ←→  │  Node Plugin      │ ←→  │  Ceph         │
│  kube-controller │ ←→  │  Controller Plugin│ ←→  │  NFS          │
│                  │     │                   │     │  Local Disk   │
└──────────────────┘     └───────────────────┘     └───────────────┘
```

### 온프레미스에서 자주 사용하는 CSI 드라이버

| 드라이버 | 스토리지 | 특징 |
|----------|----------|------|
| **rook-ceph** | Ceph | 분산 스토리지, RWO/RWX 모두 지원 |
| **nfs-subdir-external-provisioner** | NFS | 간단한 동적 프로비저닝 |
| **local-path-provisioner** | 로컬 디스크 | Rancher 제공, 테스트용 |
| **longhorn** | 분산 블록 | Rancher 제공, 설치 간편 |
| **openebs** | 다양한 백엔드 | 유연한 스토리지 엔진 |

```bash
# CSI 드라이버 목록 확인
kubectl get csidrivers

# CSI 노드 정보 확인
kubectl get csinodes
```

### Rook-Ceph 배포 예시 (온프레미스)

```yaml
# CephCluster 리소스 (Rook Operator가 관리)
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata:
  name: rook-ceph
  namespace: rook-ceph
spec:
  dataDirHostPath: /var/lib/rook
  mon:
    count: 3
    allowMultiplePerNode: false
  storage:
    useAllNodes: true
    useAllDevices: false
    devices:
    - name: "sdb"               # 전용 디스크 지정
    - name: "sdc"
---
# CephBlockPool + StorageClass
apiVersion: ceph.rook.io/v1
kind: CephBlockPool
metadata:
  name: replicapool
  namespace: rook-ceph
spec:
  replicated:
    size: 3                     # 3중 복제
```

---

## 6. StatefulSet과 스토리지 패턴

### 6-1. volumeClaimTemplates

StatefulSet의 핵심 기능으로, **Pod마다 고유한 PVC를 자동 생성**한다.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
spec:
  serviceName: redis-headless
  replicas: 6
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: redis-data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: redis-data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: ceph-rbd
      resources:
        requests:
          storage: 20Gi
```

```bash
# 생성되는 PVC 이름 패턴
# redis-data-redis-cluster-0
# redis-data-redis-cluster-1
# redis-data-redis-cluster-2
# ...

kubectl get pvc -l app=redis
```

**중요:** StatefulSet 삭제 시 **PVC는 자동으로 삭제되지 않는다**. 데이터 보호를 위한 의도적 설계다.

### 6-2. 패턴별 스토리지 구성

```
┌─── 무상태 앱 (Deployment) ───┐
│ emptyDir  : 임시 데이터        │
│ ConfigMap : 설정 파일           │
│ Secret    : 인증 정보           │
│ PVC (RWX) : 공유 파일 (NFS)    │
└──────────────────────────────┘

┌─── 유상태 앱 (StatefulSet) ──┐
│ volumeClaimTemplates : Pod별  │
│   고유 PVC (RWO, Ceph RBD)   │
│ Headless Service : Pod별 DNS  │
└──────────────────────────────┘

┌─── 배치 작업 (Job) ──────────┐
│ PVC (RWX) : 결과 저장 (NFS)   │
│ emptyDir  : 중간 처리 데이터   │
└──────────────────────────────┘
```

---

## 7. 볼륨 확장 (Volume Expansion)

```yaml
# StorageClass에서 확장 허용
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: expandable-storage
provisioner: rbd.csi.ceph.com
allowVolumeExpansion: true        # 이 설정이 필요
```

```bash
# PVC 용량 확장 (축소는 불가)
kubectl patch pvc app-data-pvc \
  -p '{"spec":{"resources":{"requests":{"storage":"100Gi"}}}}'

# 확장 상태 확인
kubectl get pvc app-data-pvc -o yaml | grep -A 5 status
```

---

## 8. 볼륨 스냅샷 (Volume Snapshot)

```yaml
# VolumeSnapshotClass 정의
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ceph-snapshot-class
driver: rbd.csi.ceph.com
deletionPolicy: Delete
parameters:
  clusterID: ceph-cluster-1
  csi.storage.k8s.io/snapshotter-secret-name: csi-rbd-secret
  csi.storage.k8s.io/snapshotter-secret-namespace: ceph-system
---
# 스냅샷 생성
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: db-snapshot-20260403
spec:
  volumeSnapshotClassName: ceph-snapshot-class
  source:
    persistentVolumeClaimName: data-postgres-0
---
# 스냅샷에서 복원
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-db-data
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: ceph-rbd
  resources:
    requests:
      storage: 50Gi
  dataSource:
    name: db-snapshot-20260403
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

---

## 9. 실전 디버깅

```bash
# PVC가 Pending 상태일 때 확인 사항
kubectl describe pvc <pvc-name>
# 1. StorageClass가 존재하는지
# 2. Provisioner가 동작 중인지
# 3. 용량/accessMode가 매칭되는 PV가 있는지

# PV가 Available인데 PVC에 바인딩 안 될 때
# → storageClassName이 일치하는지 확인
# → accessMode가 일치하는지 확인

# Pod가 마운트 실패할 때
kubectl describe pod <pod-name>
# "Unable to attach or mount volumes" → CSI 드라이버 상태 확인
kubectl get pods -n kube-system | grep csi

# NFS 마운트 실패
# → NFS 서버 접근 가능 확인
# → showmount -e <nfs-server>
# → 방화벽 규칙 확인 (port 2049)
```

---

## 면접 Q&A

### Q1. "PV와 PVC의 관계를 설명해주세요."

> **이렇게 대답한다:**
> "**PV는 인프라 관리자가 제공하는 실제 스토리지**이고, **PVC는 사용자가 요청하는 스토리지 사양**입니다. PVC를 생성하면 조건에 맞는 PV와 자동 바인딩됩니다. StorageClass를 사용하면 PV를 수동 생성할 필요 없이 **동적 프로비저닝**으로 PVC 생성 시 PV가 자동 생성됩니다. 이렇게 분리하면 **인프라 관심사와 애플리케이션 관심사가 분리**되어 각 팀이 독립적으로 작업할 수 있습니다."

### Q2. "온프레미스 환경에서 K8s 스토리지를 어떻게 구성하나요?"

> **이렇게 대답한다:**
> "온프레미스에서는 크게 세 가지 방식을 사용합니다. **NFS**는 설정이 간단하고 RWX를 지원하여 공유 데이터에 적합합니다. **Ceph(Rook-Ceph)**는 블록(RBD), 파일시스템(CephFS), 오브젝트(RGW) 모두 지원하는 분산 스토리지로 프로덕션에 적합합니다. **로컬 디스크**는 DB처럼 I/O 성능이 중요한 워크로드에 사용하되, 노드 장애 시 데이터 손실 위험이 있으므로 애플리케이션 레벨 복제가 필요합니다."

### Q3. "StatefulSet에서 PVC가 자동 삭제되지 않는 이유는?"

> **이렇게 대답한다:**
> "**데이터 보호**를 위한 의도적 설계입니다. StatefulSet을 스케일 다운하거나 삭제해도 PVC와 그 안의 데이터는 남습니다. DB 데이터가 실수로 삭제되면 복구가 어렵기 때문입니다. PVC를 정리하려면 **수동으로 삭제**해야 하며, 이 과정에서 데이터 백업 여부를 한 번 더 확인하는 안전장치가 됩니다."

### Q4. "볼륨이 마운트되지 않을 때 어떻게 디버깅하나요?"

> **이렇게 대답한다:**
> "단계별로 확인합니다. 먼저 `kubectl describe pod`에서 **이벤트**를 확인하고, PVC가 **Bound 상태인지** 확인합니다. Pending이면 StorageClass 존재 여부, Provisioner 동작 여부, 용량과 accessMode 매칭을 점검합니다. NFS라면 **서버 접근성과 방화벽(port 2049)**을, Ceph라면 **CSI 드라이버 Pod 상태와 Ceph 클러스터 health**를 확인합니다."

---

`#PersistentVolume` `#StorageClass` `#CSI` `#동적프로비저닝` `#StatefulSet스토리지`
