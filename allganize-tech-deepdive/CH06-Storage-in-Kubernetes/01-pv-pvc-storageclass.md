# PV / PVC / StorageClass — Kubernetes 스토리지 기초

> **TL;DR**
> - PV(PersistentVolume)는 클러스터 레벨 스토리지 리소스, PVC(PersistentVolumeClaim)는 사용자의 스토리지 요청이다
> - Access Mode(RWO/RWX/ROX)는 볼륨의 동시 접근 방식을 제어하며, 워크로드 특성에 맞게 선택해야 한다
> - StorageClass + Dynamic Provisioning으로 PV 수동 생성 없이 자동으로 스토리지를 프로비저닝한다

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### PV / PVC 아키텍처

Kubernetes는 스토리지를 Pod에서 분리하여 독립적인 라이프사이클로 관리한다.

```
[Kubernetes Storage Architecture]

Cluster Admin                         Developer
     │                                    │
     ▼                                    ▼
┌──────────────┐    Binding        ┌──────────────┐
│ PersistentVol│◄─────────────────►│ PersistentVol│
│ ume (PV)     │    (자동/수동)     │ umeClaim(PVC)│
│              │                   │              │
│ capacity: 50Gi                   │ request: 50Gi│
│ accessModes: │                   │ accessModes: │
│   - RWO      │                   │   - RWO      │
│ storageClass:│                   │ storageClass: │
│   gp3        │                   │   gp3        │
└──────┬───────┘                   └──────┬───────┘
       │                                  │
       │         ┌──────────┐             │
       └────────►│ 실제 저장소 │◄────────────┘
                 │ (EBS,NFS, │   mount
                 │  Ceph 등) │◄──── Pod
                 └──────────┘
```

### PV 라이프사이클

```
Provisioning ──► Available ──► Bound ──► Released ──► (Reclaim Policy)
  (생성)          (사용 가능)    (PVC 바인딩)  (PVC 삭제)       │
                                                         ├── Retain  (수동 정리)
                                                         ├── Delete  (자동 삭제)
                                                         └── Recycle (Deprecated)
```

### Static Provisioning vs Dynamic Provisioning

```
[Static Provisioning]                [Dynamic Provisioning]

Admin: PV 수동 생성                   Admin: StorageClass만 정의
  │                                     │
  ▼                                     ▼
PV (capacity: 100Gi)                StorageClass (gp3)
  │                                     │
  ▼                                     ▼
User: PVC 생성                       User: PVC 생성 (storageClassName: gp3)
  │                                     │
  ▼                                     ▼
PV-PVC Binding                       PV 자동 생성 + Binding
                                        │
                                        ▼
                                     EBS/Azure Disk 자동 프로비저닝
```

### Access Modes (접근 모드)

| 모드 | 약어 | 의미 | 대표 사용처 |
|------|------|------|------------|
| ReadWriteOnce | RWO | 단일 노드에서 읽기/쓰기 | EBS, Azure Disk, 일반 DB |
| ReadOnlyMany | ROX | 여러 노드에서 읽기 전용 | 정적 콘텐츠, ML 모델 파일 |
| ReadWriteMany | RWX | 여러 노드에서 읽기/쓰기 | NFS, EFS, Azure Files, 공유 업로드 |
| ReadWriteOncePod | RWOP | 단일 Pod에서만 읽기/쓰기 (K8s 1.29+) | 민감 데이터, 락 필요 워크로드 |

```
[Access Mode 선택 기준]

워크로드가 단일 Pod? ─── Yes ──► RWO (또는 RWOP)
       │
       No
       │
여러 Pod에서 쓰기 필요? ─── Yes ──► RWX (NFS/EFS 필요)
       │
       No
       │
읽기만 필요? ─── Yes ──► ROX
```

### StorageClass 정의

```yaml
# AWS EBS gp3 StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"        # MB/s
  encrypted: "true"
  fsType: ext4
reclaimPolicy: Delete      # PVC 삭제 시 EBS도 삭제
volumeBindingMode: WaitForFirstConsumer  # Pod 스케줄링 시 바인딩
allowVolumeExpansion: true  # 볼륨 확장 허용
```

```yaml
# Azure Disk Premium StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: managed-premium
provisioner: disk.csi.azure.com
parameters:
  skuName: Premium_LRS
  cachingMode: ReadOnly
  kind: Managed
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

### volumeBindingMode 비교

| 모드 | 동작 | 사용 사례 |
|------|------|----------|
| Immediate | PVC 생성 즉시 PV 프로비저닝 | 단일 AZ 클러스터 |
| WaitForFirstConsumer | Pod가 스케줄링될 때 PV 생성 | **멀티 AZ 클러스터 (권장)** |

```
[WaitForFirstConsumer가 중요한 이유]

Immediate 모드:
  PVC 생성 → EBS가 AZ-a에 생성됨
  Pod 스케줄 → AZ-b 노드에 배치됨
  ❌ 마운트 실패! (EBS는 같은 AZ에서만 접근 가능)

WaitForFirstConsumer 모드:
  PVC 생성 → 대기 (Pending 상태)
  Pod 스케줄 → AZ-b 노드에 배치됨
  PV 프로비저닝 → AZ-b에 EBS 생성
  ✅ 마운트 성공!
```

---

## 실전 예시

### PVC 생성 및 Pod 마운트

```yaml
# PVC 정의
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-data-pvc
  namespace: backend
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: gp3
  resources:
    requests:
      storage: 50Gi
---
# Pod에서 PVC 사용
apiVersion: v1
kind: Pod
metadata:
  name: backend-app
  namespace: backend
spec:
  containers:
  - name: app
    image: harbor.internal.corp/myapp/backend:v1.0.0
    volumeMounts:
    - name: data-volume
      mountPath: /app/data
  volumes:
  - name: data-volume
    persistentVolumeClaim:
      claimName: app-data-pvc
```

### Static PV (NFS 예시 — 온프레미스)

```yaml
# 관리자가 수동 생성하는 PV
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-pv-shared
spec:
  capacity:
    storage: 200Gi
  accessModes:
    - ReadWriteMany        # NFS는 RWX 지원
  persistentVolumeReclaimPolicy: Retain
  nfs:
    server: 10.0.1.100
    path: /exports/shared
  mountOptions:
    - hard
    - nfsvers=4.1
    - rsize=1048576
    - wsize=1048576
---
# PVC (storageClassName을 비워두면 Static PV와 매칭)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shared-data
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""     # Static Binding
  resources:
    requests:
      storage: 200Gi
```

### PV/PVC 상태 점검 명령어

```bash
# PV 목록 및 상태 확인
kubectl get pv
# NAME          CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM
# pvc-abc123    50Gi       RWO            Delete           Bound    backend/app-data-pvc

# PVC 목록 및 바인딩 상태 확인
kubectl get pvc -n backend
# NAME           STATUS   VOLUME       CAPACITY   ACCESS MODES   STORAGECLASS
# app-data-pvc   Bound    pvc-abc123   50Gi       RWO            gp3

# PVC가 Pending인 경우 이벤트 확인
kubectl describe pvc app-data-pvc -n backend

# StorageClass 확인
kubectl get sc
# NAME            PROVISIONER          RECLAIMPOLICY   VOLUMEBINDINGMODE
# gp3 (default)   ebs.csi.aws.com     Delete          WaitForFirstConsumer

# PV의 실제 볼륨 정보 확인
kubectl get pv pvc-abc123 -o jsonpath='{.spec.csi.volumeHandle}'
# vol-0abc123def456 (AWS EBS Volume ID)
```

### PVC Pending 트러블슈팅

```
[PVC가 Pending인 경우 체크리스트]

1. StorageClass 존재 여부
   kubectl get sc

2. CSI Driver 상태
   kubectl get pods -n kube-system | grep csi

3. volumeBindingMode 확인
   WaitForFirstConsumer → Pod가 생성되기 전까지 Pending은 정상

4. Capacity 부족
   AWS: EC2 EBS 볼륨 제한 확인
   Azure: Disk quota 확인

5. AZ 불일치 (Immediate 모드)
   PV의 AZ와 Pod의 노드 AZ 확인

6. 권한 문제
   CSI Driver의 IAM Role/Service Principal 확인
```

---

## 면접 Q&A

### Q1: "PV와 PVC의 차이를 설명해주세요"

**30초 답변**:
PV는 클러스터 레벨의 스토리지 리소스이고, PVC는 사용자가 원하는 스토리지를 요청하는 명세입니다. PVC가 생성되면 조건에 맞는 PV와 바인딩되어 Pod에서 사용할 수 있습니다. 이렇게 분리하면 스토리지 관리와 사용을 독립적으로 할 수 있습니다.

**2분 답변**:
PV(PersistentVolume)는 클러스터 관리자가 프로비저닝하는 실제 스토리지 리소스입니다. AWS EBS, Azure Disk, NFS 등 다양한 백엔드를 추상화합니다. PVC(PersistentVolumeClaim)는 개발자가 필요한 스토리지 크기와 접근 모드를 선언하는 요청서입니다.

이 분리가 중요한 이유는 관심사 분리(Separation of Concerns) 때문입니다. 인프라 팀은 스토리지 종류와 성능을 관리하고, 개발 팀은 필요한 용량만 요청하면 됩니다. StorageClass를 사용하면 Dynamic Provisioning으로 PV를 수동 생성할 필요 없이 PVC 요청 시 자동으로 EBS나 Azure Disk가 생성됩니다.

volumeBindingMode를 WaitForFirstConsumer로 설정하면 Pod가 스케줄링될 때 해당 AZ에 볼륨을 생성하므로 멀티 AZ 환경에서 마운트 실패를 방지할 수 있습니다. reclaimPolicy는 운영 환경에서 Retain을 사용하여 PVC 삭제 시 데이터를 보존하는 것이 안전합니다.

**💡 경험 연결**:
온프레미스에서 NFS 기반 공유 스토리지를 운영했던 경험이 있습니다. Kubernetes에서는 이를 PV/PVC로 추상화하여 관리하며, 클라우드 환경에서는 StorageClass를 통한 Dynamic Provisioning으로 자동화할 수 있다는 점이 큰 차이입니다.

**⚠️ 주의**:
"PV는 디스크 자체"라고 단순화하면 안 된다. PV는 디스크를 Kubernetes 오브젝트로 추상화한 것이며, 하나의 물리 디스크가 여러 PV가 될 수도, 여러 디스크가 하나의 PV가 될 수도 있다.

### Q2: "RWO, RWX, ROX의 차이와 사용 사례를 설명해주세요"

**30초 답변**:
RWO(ReadWriteOnce)는 단일 노드에서만 읽기/쓰기가 가능하며 EBS, Azure Disk 등 블록 스토리지에 사용합니다. RWX(ReadWriteMany)는 여러 노드에서 동시에 읽기/쓰기가 가능하며 NFS, EFS에 사용합니다. ROX(ReadOnlyMany)는 여러 노드에서 읽기만 가능하며 ML 모델 파일 배포 등에 활용합니다.

**2분 답변**:
Access Mode는 볼륨에 대한 동시 접근 방식을 정의합니다.

RWO는 가장 일반적인 모드로, 하나의 노드에서만 마운트 가능합니다. 같은 노드의 여러 Pod에서는 접근 가능하지만, 다른 노드의 Pod에서는 불가합니다. PostgreSQL, MongoDB 같은 단일 인스턴스 DB에 적합합니다. AWS EBS, Azure Disk 등 블록 스토리지는 기본적으로 RWO만 지원합니다.

RWX는 여러 노드의 Pod에서 동시에 읽기/쓰기가 가능합니다. 파일 업로드 디렉토리를 여러 Pod가 공유하거나, AI 학습 데이터를 여러 Worker가 접근하는 경우에 필요합니다. NFS, AWS EFS, Azure Files 같은 파일 시스템 스토리지가 RWX를 지원합니다.

ROX는 여러 노드에서 읽기만 가능합니다. 미리 학습된 ML 모델 파일을 여러 추론 서버 Pod에 배포하는 패턴에서 유용합니다. Allganize의 LLM 서비스처럼 모델 파일을 여러 Pod에서 동시에 로드해야 하는 경우에 적합합니다.

**💡 경험 연결**:
온프레미스 환경에서 NFS를 사용하여 여러 서버 간 파일 공유를 운영한 경험이 있습니다. Kubernetes에서는 이를 RWX Access Mode로 추상화하여 관리하며, 클라우드에서는 EFS나 Azure Files로 대체합니다.

**⚠️ 주의**:
RWO는 "단일 Pod"가 아니라 "단일 노드" 제한이다. 같은 노드에 스케줄된 여러 Pod는 RWO 볼륨을 공유할 수 있다. K8s 1.29+의 RWOP(ReadWriteOncePod)가 진정한 단일 Pod 제한이다.

### Q3: "Dynamic Provisioning이 실패하는 원인과 해결 방법은?"

**30초 답변**:
주요 원인은 CSI Driver 미설치, StorageClass 설정 오류, IAM 권한 부족, AZ 불일치입니다. kubectl describe pvc로 이벤트를 확인하고, CSI Driver Pod 상태와 로그를 점검하여 원인을 파악합니다.

**2분 답변**:
Dynamic Provisioning 실패 시 체계적으로 진단합니다.

첫째, PVC 이벤트를 확인합니다. `kubectl describe pvc`에서 Events 섹션이 가장 중요한 단서입니다. "no persistent volumes available"이면 StorageClass나 CSI Driver 문제, "waiting for first consumer"면 WaitForFirstConsumer 모드에서의 정상 대기 상태입니다.

둘째, CSI Driver 상태를 확인합니다. `kubectl get pods -n kube-system | grep csi`로 Driver Pod가 Running인지, `kubectl logs`로 에러 로그를 확인합니다. EBS CSI Driver의 경우 IRSA(IAM Roles for Service Accounts) 설정이 누락되면 "Access Denied" 에러가 발생합니다.

셋째, 클라우드 쿼터를 확인합니다. AWS는 리전별 EBS 볼륨 수 제한이 있고, Azure는 Subscription 레벨의 Disk 쿼터가 있습니다.

넷째, volumeBindingMode를 확인합니다. WaitForFirstConsumer인 경우 Pod가 생성되기 전까지 PVC는 Pending 상태가 정상입니다. 이를 모르면 불필요한 트러블슈팅을 하게 됩니다.

**💡 경험 연결**:
인프라 운영에서 스토리지 프로비저닝 실패는 흔한 장애 유형입니다. 온프레미스에서는 디스크 어레이 용량 부족이 주 원인이었고, 클라우드에서는 IAM 권한과 쿼터가 추가됩니다. 체계적인 점검 순서를 갖추는 것이 핵심입니다.

**⚠️ 주의**:
WaitForFirstConsumer 모드에서 PVC Pending은 정상이다. 이를 에러로 오인하여 Immediate 모드로 변경하면 멀티 AZ 환경에서 더 심각한 마운트 실패가 발생할 수 있다.

### Q4: "reclaimPolicy Retain과 Delete의 차이와 선택 기준은?"

**30초 답변**:
Delete는 PVC 삭제 시 PV와 실제 스토리지(EBS, Disk)도 함께 삭제됩니다. Retain은 PVC가 삭제되어도 PV와 데이터가 보존됩니다. 개발 환경은 Delete, 운영 환경의 중요 데이터는 Retain을 사용합니다.

**2분 답변**:
reclaimPolicy는 PVC가 삭제된 후 PV의 처리 방식을 결정합니다.

Delete 정책은 PVC 삭제 시 PV와 백엔드 스토리지(EBS, Azure Disk)가 모두 자동 삭제됩니다. 리소스 정리가 자동화되어 편리하지만, 실수로 PVC를 삭제하면 데이터 복구가 불가능합니다. 개발/테스트 환경에서 주로 사용합니다.

Retain 정책은 PVC가 삭제되어도 PV가 Released 상태로 남고, 실제 스토리지도 보존됩니다. 데이터 복구가 가능하지만, 관리자가 수동으로 PV를 정리해야 합니다. 운영 환경의 데이터베이스, 중요 로그 등에 사용합니다.

실무에서는 StorageClass를 환경별로 분리합니다. `gp3-dev`는 Delete, `gp3-prod`는 Retain으로 설정하고, 네임스페이스 기반의 ResourceQuota와 결합하여 관리합니다. 추가로 VolumeSnapshot을 병행하면 Retain 없이도 Delete 정책에서 안전하게 운영할 수 있습니다.

**💡 경험 연결**:
온프레미스에서 LUN 삭제 전 반드시 스냅샷을 확보하는 운영 정책을 수립했던 경험이 있습니다. Kubernetes에서는 reclaimPolicy와 VolumeSnapshot으로 같은 목적을 달성합니다.

**⚠️ 주의**:
Retain으로 남은 PV는 다른 PVC에 자동 바인딩되지 않는다. 재사용하려면 관리자가 PV의 `.spec.claimRef`를 수동으로 제거해야 한다.

---

## Allganize 맥락

| JD 요구사항 | 연결 포인트 |
|------------|------------|
| AWS/Azure K8s 운영 | EBS CSI, Azure Disk CSI를 통한 Dynamic Provisioning |
| AI/LLM 서비스 | 모델 파일 저장에 RWX(EFS/Azure Files) 또는 ROX 활용 |
| 멀티클라우드 | StorageClass 추상화로 클라우드별 스토리지 차이 흡수 |
| 복원력(Resilience) | reclaimPolicy Retain + VolumeSnapshot으로 데이터 보호 |
| 온프레미스 경험 활용 | NFS Static PV 운영 경험 → 클라우드 Dynamic Provisioning 전환 설명 |

Allganize의 Alli LLM 서비스는 대용량 모델 파일을 여러 추론 Pod에서 동시에 로드해야 한다. 이 경우 EFS(RWX)에 모델을 저장하고, 각 Pod에서 마운트하는 패턴이 일반적이다. StorageClass의 `volumeBindingMode: WaitForFirstConsumer`는 멀티 AZ EKS 클러스터에서 필수 설정이다.

---

**핵심 키워드**: `PersistentVolume` `PersistentVolumeClaim` `StorageClass` `Dynamic Provisioning` `Access Modes` `RWO` `RWX` `WaitForFirstConsumer` `reclaimPolicy`
