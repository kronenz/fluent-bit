# CSI Drivers — Container Storage Interface 심화

> **TL;DR**
> - CSI(Container Storage Interface)는 Kubernetes와 스토리지 시스템 간의 표준 인터페이스이다
> - 클라우드 환경에서는 EBS CSI Driver(AWS), Azure Disk CSI Driver를 사용하며, IRSA/Workload Identity로 권한을 부여한다
> - 온프레미스에서는 Rook-Ceph(분산 스토리지)나 Longhorn(경량 스토리지)으로 Kubernetes-native 스토리지를 구축한다

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 15min

---

## 핵심 개념

### CSI 아키텍처

CSI는 Kubernetes가 다양한 스토리지 시스템과 통신하기 위한 표준 gRPC 인터페이스다. In-tree 플러그인(K8s 코드에 내장)에서 Out-of-tree CSI Driver(독립 배포)로 전환되었다.

```
[CSI Architecture]

┌─────────────────────────────────────────────────────┐
│  Kubernetes Control Plane                           │
│                                                     │
│  kube-controller-manager                            │
│       │                                             │
│       ▼                                             │
│  PV Controller ──► Attach/Detach Controller         │
│                          │                          │
└──────────────────────────┼──────────────────────────┘
                           │  CSI gRPC
                           ▼
┌─────────────────────────────────────────────────────┐
│  CSI Driver (DaemonSet + Deployment)                │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐                 │
│  │ Controller   │  │ Node Plugin  │  (DaemonSet)    │
│  │ Plugin       │  │              │                 │
│  │ (Deployment) │  │ - NodeStage  │                 │
│  │              │  │ - NodePublish│                 │
│  │ - CreateVol  │  │ - Mount/     │                 │
│  │ - DeleteVol  │  │   Unmount    │                 │
│  │ - Attach     │  │              │                 │
│  │ - Snapshot   │  │              │                 │
│  └──────┬───────┘  └──────┬───────┘                 │
│         │                 │                         │
└─────────┼─────────────────┼─────────────────────────┘
          │                 │
          ▼                 ▼
   ┌─────────────────────────────┐
   │  Storage Backend            │
   │  (AWS EBS, Azure Disk,      │
   │   Ceph, NFS, Longhorn)     │
   └─────────────────────────────┘
```

### CSI 컴포넌트 역할

| 컴포넌트 | 배포 방식 | 역할 |
|----------|----------|------|
| Controller Plugin | Deployment (1-2개) | 볼륨 생성/삭제, Attach/Detach, 스냅샷 |
| Node Plugin | DaemonSet (모든 노드) | 볼륨 마운트/언마운트, 포맷, 노드 등록 |
| CSI Sidecar (external-provisioner) | Controller 내 Sidecar | PVC 감시 → CreateVolume 호출 |
| CSI Sidecar (external-attacher) | Controller 내 Sidecar | VolumeAttachment 감시 → Attach 호출 |
| CSI Sidecar (external-snapshotter) | Controller 내 Sidecar | VolumeSnapshot 감시 → 스냅샷 생성 |

### 볼륨 마운트 흐름

```
[Pod 생성 시 볼륨 마운트 흐름]

1. PVC 생성
   └── external-provisioner가 감지
       └── Controller Plugin: CreateVolume()
           └── AWS: EBS 볼륨 생성 (vol-xxx)
           └── PV 오브젝트 생성

2. Pod 스케줄링
   └── kube-scheduler가 노드 선택
       └── Attach/Detach Controller 동작

3. Volume Attach
   └── external-attacher가 VolumeAttachment 감지
       └── Controller Plugin: ControllerPublishVolume()
           └── AWS: EBS를 EC2 인스턴스에 Attach

4. Volume Mount (NodeStage + NodePublish)
   └── kubelet이 Node Plugin 호출
       └── NodeStageVolume(): 블록 디바이스를 포맷 + 글로벌 마운트
       └── NodePublishVolume(): Pod 경로에 바인드 마운트
           └── /var/lib/kubelet/pods/<pod-id>/volumes/...

5. Pod 시작
   └── 컨테이너에서 mountPath로 접근 가능
```

---

## 실전 예시

### AWS EBS CSI Driver 설치 및 설정

```bash
# 1. IRSA(IAM Roles for Service Accounts) 설정
eksctl create iamserviceaccount \
  --name ebs-csi-controller-sa \
  --namespace kube-system \
  --cluster my-cluster \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --role-only \
  --attach-policy-arn arn:aws:iam::policy/service-role/AmazonEBSCSIDriverPolicy \
  --approve

# 2. EKS Add-on으로 설치 (권장)
aws eks create-addon \
  --cluster-name my-cluster \
  --addon-name aws-ebs-csi-driver \
  --service-account-role-arn arn:aws:iam::role/AmazonEKS_EBS_CSI_DriverRole

# 3. 설치 확인
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
# ebs-csi-controller-xxx   6/6   Running
# ebs-csi-node-xxxxx       3/3   Running (DaemonSet)
```

```yaml
# EBS gp3 StorageClass (성능 최적화)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3-high-iops
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "10000"            # 최대 16,000
  throughput: "500"        # 최대 1,000 MB/s
  encrypted: "true"
  kmsKeyId: arn:aws:kms:ap-northeast-2:123456:key/xxx
  fsType: ext4
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

### Azure Disk CSI Driver 설정

```bash
# AKS에서는 기본 설치됨 (확인)
kubectl get pods -n kube-system -l app=csi-azuredisk-controller
# csi-azuredisk-controller-xxx   6/6   Running

kubectl get pods -n kube-system -l app=csi-azuredisk-node
# csi-azuredisk-node-xxxxx       3/3   Running (DaemonSet)
```

```yaml
# Azure Premium SSD v2 StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: azure-premiumv2
provisioner: disk.csi.azure.com
parameters:
  skuName: PremiumV2_LRS
  cachingMode: None         # Premium v2는 캐싱 미지원
  DiskIOPSReadWrite: "5000"
  DiskMBpsReadWrite: "200"
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
---
# Azure Files (RWX 지원) StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: azure-files-premium
provisioner: file.csi.azure.com
parameters:
  skuName: Premium_LRS
  protocol: nfs              # NFSv4.1 프로토콜
mountOptions:
  - nconnect=4               # 병렬 연결로 성능 향상
reclaimPolicy: Retain
volumeBindingMode: Immediate  # Azure Files는 AZ 제약 없음
allowVolumeExpansion: true
```

### Rook-Ceph (온프레미스 분산 스토리지)

```
[Rook-Ceph Architecture]

┌─────────────────────────────────────────────┐
│  Kubernetes Cluster                         │
│                                             │
│  ┌───────────┐   Rook Operator              │
│  │ Rook      │──────────────────┐           │
│  │ Operator  │                  │           │
│  └───────────┘                  ▼           │
│                          ┌─────────────┐    │
│                          │ Ceph Cluster │    │
│  ┌─────┐ ┌─────┐ ┌─────┐│             │    │
│  │Node1│ │Node2│ │Node3││ MON  x3     │    │
│  │ OSD │ │ OSD │ │ OSD ││ MGR  x2     │    │
│  │ ▼   │ │ ▼   │ │ ▼   ││ MDS  x2     │    │
│  │/dev/│ │/dev/│ │/dev/││ (CephFS용)  │    │
│  │sdb  │ │sdb  │ │sdb  ││             │    │
│  └─────┘ └─────┘ └─────┘└─────────────┘    │
│                                             │
│  Storage 제공:                               │
│  ├── RBD (Block)   → RWO       PV/PVC      │
│  ├── CephFS (File) → RWX       PV/PVC      │
│  └── RGW (Object)  → S3 호환               │
└─────────────────────────────────────────────┘
```

```yaml
# Rook-Ceph 설치 (Helm)
# 1. Operator 설치
# helm install rook-ceph rook-release/rook-ceph \
#   --namespace rook-ceph --create-namespace

# 2. Ceph Cluster 정의
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata:
  name: rook-ceph
  namespace: rook-ceph
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v18.2
  dataDirHostPath: /var/lib/rook
  mon:
    count: 3
    allowMultiplePerNode: false
  mgr:
    count: 2
  dashboard:
    enabled: true
  storage:
    useAllNodes: true
    useAllDevices: false
    devices:
    - name: sdb        # 전용 디스크 지정
    - name: sdc
---
# 3. CephBlockPool + StorageClass
apiVersion: ceph.rook.io/v1
kind: CephBlockPool
metadata:
  name: replicapool
  namespace: rook-ceph
spec:
  replicated:
    size: 3             # 3중 복제
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-block
provisioner: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  pool: replicapool
  imageFormat: "2"
  imageFeatures: layering,fast-diff,object-map,deep-flatten
  csi.storage.k8s.io/provisioner-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/provisioner-secret-namespace: rook-ceph
  csi.storage.k8s.io/node-stage-secret-name: rook-csi-rbd-node
  csi.storage.k8s.io/node-stage-secret-namespace: rook-ceph
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
```

### Longhorn (경량 분산 스토리지)

```
[Longhorn Architecture]

┌──────────────────────────────────────────┐
│  Kubernetes Cluster                      │
│                                          │
│  Longhorn Manager (DaemonSet)            │
│  ┌──────┐  ┌──────┐  ┌──────┐           │
│  │Node 1│  │Node 2│  │Node 3│           │
│  │      │  │      │  │      │           │
│  │ Vol  │──│Replica│──│Replica│  3중 복제 │
│  │Engine│  │      │  │      │           │
│  │  ▼   │  │  ▼   │  │  ▼   │           │
│  │/data │  │/data │  │/data │           │
│  └──────┘  └──────┘  └──────┘           │
│                                          │
│  특징:                                    │
│  ├── 설치 간편 (Helm 한 줄)               │
│  ├── Web UI 내장                         │
│  ├── 자동 스냅샷/백업                     │
│  └── iSCSI 기반 (별도 HW 불필요)         │
└──────────────────────────────────────────┘
```

```bash
# Longhorn 설치
helm repo add longhorn https://charts.longhorn.io
helm install longhorn longhorn/longhorn \
  --namespace longhorn-system --create-namespace \
  --set defaultSettings.defaultReplicaCount=3 \
  --set defaultSettings.backupTarget="s3://longhorn-backup@ap-northeast-2/" \
  --set defaultSettings.backupTargetCredentialSecret=longhorn-s3-secret
```

```yaml
# Longhorn StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "3"
  staleReplicaTimeout: "2880"
  dataLocality: best-effort     # 데이터를 Pod과 같은 노드에 배치
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
```

### CSI Driver 비교표

| 항목 | EBS CSI | Azure Disk CSI | Rook-Ceph | Longhorn |
|------|---------|----------------|-----------|----------|
| 환경 | AWS | Azure | On-prem / Any | On-prem / Any |
| Access Mode | RWO | RWO | RWO(RBD), RWX(CephFS) | RWO |
| 스냅샷 | EBS Snapshot | Azure Snapshot | Ceph Snapshot | 내장 스냅샷 |
| 복제 | Cross-AZ 불가 | ZRS 옵션 | 3중 복제 (설정) | N중 복제 (설정) |
| 복잡도 | 낮음 (관리형) | 낮음 (관리형) | **높음** (Ceph 운영) | 중간 |
| 성능 | io2: 64K IOPS | Premium v2: 80K IOPS | SSD 기반 높음 | 중간 |
| 운영 부담 | AWS 관리 | Azure 관리 | **Ceph 전문 지식 필요** | 비교적 낮음 |

### CSI Driver 트러블슈팅

```bash
# 1. CSI Driver Pod 상태 확인
kubectl get pods -n kube-system | grep csi
# ebs-csi-controller-xxx   6/6   Running
# ebs-csi-node-xxxxx       3/3   Running

# 2. CSI Driver 로그 확인
kubectl logs -n kube-system deployment/ebs-csi-controller \
  -c csi-provisioner --tail=50

# 3. VolumeAttachment 상태 확인
kubectl get volumeattachment
# NAME              ATTACHER           PV         NODE        ATTACHED
# csi-xxx           ebs.csi.aws.com    pvc-xxx    node-1      true

# 4. CSINode 정보 확인
kubectl get csinode
# NAME     DRIVERS   AGE
# node-1   1         30d

# 5. 볼륨이 Attach되지 않는 경우
kubectl describe volumeattachment csi-xxx
# Events에서 에러 메시지 확인
```

---

## 면접 Q&A

### Q1: "CSI란 무엇이고, 왜 필요한가요?"

**30초 답변**:
CSI(Container Storage Interface)는 Kubernetes와 외부 스토리지 시스템 간의 표준 gRPC 인터페이스입니다. 이전에는 스토리지 플러그인이 Kubernetes 코드에 내장(In-tree)되어 있어 업데이트가 어려웠지만, CSI로 분리하면서 스토리지 벤더가 독립적으로 Driver를 개발하고 배포할 수 있게 되었습니다.

**2분 답변**:
CSI 이전에는 AWS EBS, NFS 등의 스토리지 코드가 Kubernetes 소스 코드에 직접 포함되어 있었습니다. 이로 인해 새로운 스토리지를 추가하거나 버그를 수정하려면 Kubernetes 전체를 릴리스해야 했습니다.

CSI는 이 문제를 Controller Plugin과 Node Plugin이라는 두 가지 gRPC 서비스로 해결합니다. Controller Plugin은 Deployment로 배포되어 볼륨 생성/삭제, Attach/Detach를 담당하고, Node Plugin은 DaemonSet으로 모든 노드에 배포되어 볼륨 마운트/언마운트를 담당합니다.

CSI Sidecar 컨테이너(external-provisioner, external-attacher, external-snapshotter)가 Kubernetes API를 감시하다가 CSI Driver의 gRPC 메서드를 호출하는 브릿지 역할을 합니다. 이 아키텍처 덕분에 EBS CSI, Azure Disk CSI, Rook-Ceph CSI 등 다양한 스토리지를 동일한 방식으로 사용할 수 있습니다.

**💡 경험 연결**:
온프레미스에서 스토리지 시스템(SAN/NAS)과 서버 간의 연결을 관리했던 경험이 있습니다. CSI는 이러한 스토리지 연결을 Kubernetes가 표준화한 것으로, 스토리지 벤더에 관계없이 동일한 PV/PVC 인터페이스를 사용할 수 있다는 점이 핵심입니다.

**⚠️ 주의**:
CSI Driver의 버전 호환성을 반드시 확인해야 한다. Kubernetes 버전과 CSI Driver 버전의 호환 매트릭스가 있으며, 불일치 시 볼륨 마운트 실패가 발생할 수 있다.

### Q2: "EBS CSI Driver에서 IRSA가 필요한 이유는?"

**30초 답변**:
IRSA(IAM Roles for Service Accounts)는 Kubernetes ServiceAccount에 AWS IAM Role을 직접 매핑합니다. EBS CSI Driver가 EBS 볼륨을 생성/삭제하려면 AWS API 권한이 필요한데, 노드의 Instance Profile 대신 IRSA를 사용하면 최소 권한 원칙을 적용할 수 있습니다.

**2분 답변**:
EBS CSI Driver는 AWS API를 호출하여 EBS 볼륨을 생성, Attach, 삭제합니다. 이를 위해 ec2:CreateVolume, ec2:AttachVolume 등의 IAM 권한이 필요합니다.

과거에는 EC2 Instance Profile에 이러한 권한을 부여했는데, 이 방식은 해당 노드의 모든 Pod이 같은 권한을 갖게 되어 보안상 문제가 있었습니다.

IRSA는 OIDC(OpenID Connect)를 통해 Kubernetes ServiceAccount와 IAM Role을 1:1 매핑합니다. EBS CSI Controller Pod만 EBS 관리 권한을 갖고, 다른 Pod은 해당 권한에 접근할 수 없습니다. Azure에서는 동일한 개념이 Workload Identity입니다.

EKS Add-on으로 설치하면 IRSA 설정이 간소화됩니다. eksctl이 IAM Role 생성과 ServiceAccount 연결을 자동으로 처리합니다.

**💡 경험 연결**:
인프라 보안에서 최소 권한 원칙(Principle of Least Privilege)은 기본 중의 기본입니다. IRSA는 이 원칙을 Kubernetes Pod 레벨에서 구현한 것으로, 온프레미스에서 서비스 계정별로 권한을 분리했던 것과 같은 맥락입니다.

**⚠️ 주의**:
IRSA 설정이 누락되면 CSI Driver가 "AccessDenied" 에러를 발생시키고, PVC가 영구 Pending 상태가 된다. EKS 클러스터의 OIDC Provider가 활성화되어 있는지 반드시 확인해야 한다.

### Q3: "온프레미스에서 Kubernetes 스토리지를 구축한다면 어떤 방법을 선택하시겠습니까?"

**30초 답변**:
규모와 요구사항에 따라 다릅니다. 대규모 환경에서 RWX와 오브젝트 스토리지가 필요하면 Rook-Ceph, 소규모 환경에서 간단한 블록 스토리지가 필요하면 Longhorn을 선택합니다. 기존 NFS 인프라가 있다면 NFS CSI Driver도 고려합니다.

**2분 답변**:
온프레미스 Kubernetes 스토리지 선택은 세 가지 기준으로 판단합니다.

첫째, 규모입니다. 10노드 이상이고 수십 TB 이상의 데이터를 관리해야 하면 Rook-Ceph가 적합합니다. Ceph는 블록(RBD), 파일(CephFS), 오브젝트(RGW) 세 가지 스토리지를 하나의 클러스터에서 제공하며, PB 스케일까지 확장 가능합니다. 단점은 Ceph 운영 복잡도가 높다는 것입니다.

둘째, 운영 부담입니다. 5노드 이하의 소규모 클러스터이거나 스토리지 전담 인력이 없으면 Longhorn이 적합합니다. Helm 한 줄로 설치하고, Web UI로 관리하며, 자동 스냅샷과 S3 백업을 기본 제공합니다.

셋째, 기존 인프라입니다. 이미 NFS 서버나 SAN이 있다면 NFS CSI Driver나 Static PV로 기존 투자를 활용할 수 있습니다. 다만 NFS의 단일 장애점(SPOF) 문제를 해결하기 위해 이중화 구성이 필요합니다.

제 경우 폐쇄망 환경에서 기존 NFS를 활용하면서 Longhorn을 병행 도입하는 방식을 선택할 것입니다. NFS는 RWX 공유 데이터에, Longhorn은 RWO DB 워크로드에 사용합니다.

**💡 경험 연결**:
온프레미스 스토리지 운영 경험이 직접적으로 활용됩니다. SAN/NAS 운영, RAID 구성, 디스크 모니터링, 장애 대응 등의 경험이 Rook-Ceph나 Longhorn 운영에서도 동일하게 적용됩니다.

**⚠️ 주의**:
Rook-Ceph를 선택할 때 "설치는 쉽지만 운영은 어렵다"는 점을 인지해야 한다. OSD 장애, MON 복구, PG(Placement Group) 관리 등 Ceph 고유의 운영 지식이 필요하다.

---

## Allganize 맥락

| JD 요구사항 | 연결 포인트 |
|------------|------------|
| AWS EKS 운영 | EBS CSI Driver + IRSA 설정, gp3 StorageClass 최적화 |
| Azure AKS 운영 | Azure Disk/Files CSI Driver, Workload Identity |
| AI/LLM 서비스 | 모델 파일 공유를 위한 EFS CSI(RWX) 또는 Azure Files CSI |
| 멀티클라우드 전략 | CSI 추상화 레이어로 클라우드별 스토리지 차이 흡수 |
| 온프레미스 경험 | NFS/SAN 운영 경험 → Rook-Ceph/Longhorn 전환 시 강점 |

Allganize의 Alli 서비스는 AWS와 Azure 모두에서 운영되므로, 각 클라우드의 CSI Driver 특성을 이해하는 것이 중요하다. 특히 LLM 모델 파일(수 GB~수십 GB)을 여러 추론 Pod에서 공유해야 하므로 EFS CSI(AWS) 또는 Azure Files CSI의 RWX 지원이 핵심이다.

---

**핵심 키워드**: `CSI` `Container Storage Interface` `EBS CSI Driver` `Azure Disk CSI` `IRSA` `Rook-Ceph` `Longhorn` `Controller Plugin` `Node Plugin`
