# Kubernetes 백업 & DR — Velero, etcd, 복구 전략

> **TL;DR**
> - Velero는 Kubernetes 리소스 + PV 데이터를 통째로 백업/복원하며, 클러스터 마이그레이션에도 활용된다
> - etcd 스냅샷은 클러스터 상태의 근본적 백업이며, 관리형 K8s(EKS/AKS)에서는 클라우드 제공자가 관리한다
> - DR 전략은 RPO/RTO 기반으로 설계하며, 멀티 리전/멀티 클라우드 환경에서는 Velero + GitOps 조합이 핵심이다

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Kubernetes 백업 대상 분류

```
[K8s 백업 대상]

1. 클러스터 상태 (etcd)
   ├── 모든 K8s 리소스 정의 (Deployment, Service, ConfigMap, Secret...)
   ├── RBAC, Namespace, CRD
   └── etcd snapshot으로 백업

2. 애플리케이션 데이터 (PV/PVC)
   ├── DB 데이터 (MongoDB, PostgreSQL, Elasticsearch)
   ├── 파일 업로드, 캐시
   └── VolumeSnapshot 또는 Velero restic/kopia로 백업

3. 설정/코드 (GitOps)
   ├── Helm charts, Kustomize manifests
   ├── ArgoCD Application 정의
   └── Git 저장소가 SSOT (Single Source of Truth)

4. 시크릿/인증서
   ├── TLS 인증서, API 키
   ├── Sealed Secrets, External Secrets
   └── 별도 키 관리 시스템 (AWS KMS, Azure Key Vault)
```

### Velero 아키텍처

```
[Velero Architecture]

┌─────────────────────────────────────────────────┐
│  Kubernetes Cluster                             │
│                                                 │
│  ┌──────────────┐                               │
│  │ Velero Server │  (Deployment in velero ns)   │
│  │              │                               │
│  │ - Backup     │                               │
│  │   Controller │                               │
│  │ - Restore    │                               │
│  │   Controller │                               │
│  │ - Schedule   │                               │
│  │   Controller │                               │
│  └──────┬───────┘                               │
│         │                                       │
│  ┌──────┴───────┐                               │
│  │ Node Agent   │  (DaemonSet, kopia/restic)    │
│  │ (각 노드)     │  PV 데이터 파일 레벨 백업      │
│  └──────────────┘                               │
│                                                 │
└─────────┬───────────────────────────────────────┘
          │
          ▼
┌─────────────────────┐    ┌─────────────────────┐
│ Object Storage      │    │ Volume Snapshots     │
│ (S3, Azure Blob)    │    │ (EBS Snapshot,       │
│                     │    │  Azure Disk Snapshot) │
│ - K8s manifests     │    │                     │
│ - PV data (restic)  │    │ - PV data (CSI)     │
│ - Backup metadata   │    │                     │
└─────────────────────┘    └─────────────────────┘
```

### Velero 백업 방식 비교

| 항목 | CSI Snapshot | Kopia (File-level) |
|------|-------------|-------------------|
| 방식 | CSI VolumeSnapshot API | 파일 단위 백업 (restic 후속) |
| 속도 | 빠름 (COW 스냅샷) | 느림 (파일 복사) |
| 저장소 | 클라우드 스냅샷 (같은 리전) | Object Storage (S3, Azure Blob) |
| Cross-Region | 불가 (스냅샷 복사 별도) | **가능** (S3 리전 무관) |
| Cross-Cloud | **불가** | **가능** (S3 호환이면 OK) |
| 증분 백업 | 클라우드 제공자 의존 | 지원 (중복 제거) |
| 추천 사례 | 같은 클러스터/리전 복원 | DR, 클러스터 마이그레이션 |

---

## 실전 예시

### Velero 설치 (AWS)

```bash
# 1. S3 버킷 생성
aws s3 mb s3://velero-backup-allganize --region ap-northeast-2

# 2. IAM Policy 생성
cat > velero-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVolumes",
        "ec2:DescribeSnapshots",
        "ec2:CreateTags",
        "ec2:CreateVolume",
        "ec2:CreateSnapshot",
        "ec2:DeleteSnapshot"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:PutObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": "arn:aws:s3:::velero-backup-allganize/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::velero-backup-allganize"
    }
  ]
}
EOF

aws iam create-policy \
  --policy-name VeleroAccessPolicy \
  --policy-document file://velero-policy.json

# 3. IRSA 설정
eksctl create iamserviceaccount \
  --name velero-server \
  --namespace velero \
  --cluster my-cluster \
  --attach-policy-arn arn:aws:iam::policy/VeleroAccessPolicy \
  --approve

# 4. Velero 설치 (Helm)
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm install velero vmware-tanzu/velero \
  --namespace velero --create-namespace \
  --set configuration.backupStorageLocation[0].name=aws \
  --set configuration.backupStorageLocation[0].provider=aws \
  --set configuration.backupStorageLocation[0].bucket=velero-backup-allganize \
  --set configuration.backupStorageLocation[0].config.region=ap-northeast-2 \
  --set configuration.volumeSnapshotLocation[0].name=aws \
  --set configuration.volumeSnapshotLocation[0].provider=aws \
  --set configuration.volumeSnapshotLocation[0].config.region=ap-northeast-2 \
  --set serviceAccount.server.name=velero-server \
  --set serviceAccount.server.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::role/velero-irsa-role \
  --set deployNodeAgent=true \
  --set nodeAgent.podVolumePath=/var/lib/kubelet/pods
```

### Velero 백업 운영

```bash
# 전체 클러스터 백업
velero backup create cluster-full-20240315 \
  --wait

# 특정 네임스페이스 백업
velero backup create backend-backup-20240315 \
  --include-namespaces backend,database \
  --wait

# 특정 리소스만 백업 (PV 데이터 포함)
velero backup create db-backup-20240315 \
  --include-namespaces database \
  --include-resources statefulsets,persistentvolumeclaims,persistentvolumes,secrets \
  --default-volumes-to-fs-backup \
  --wait

# 레이블 기반 백업
velero backup create critical-backup \
  --selector "tier=critical" \
  --wait

# 백업 상태 확인
velero backup get
# NAME                       STATUS      ERRORS   WARNINGS   CREATED
# cluster-full-20240315      Completed   0        0          2024-03-15 02:00:00
# backend-backup-20240315    Completed   0        1          2024-03-15 02:05:00

# 백업 상세 정보
velero backup describe cluster-full-20240315 --details
```

### Velero 스케줄 백업

```bash
# 매일 새벽 2시 전체 백업 (7일 보존)
velero schedule create daily-full \
  --schedule="0 2 * * *" \
  --ttl 168h0m0s \
  --wait

# 매시간 DB 네임스페이스 백업 (24시간 보존)
velero schedule create hourly-db \
  --schedule="0 * * * *" \
  --include-namespaces database \
  --default-volumes-to-fs-backup \
  --ttl 24h0m0s

# 스케줄 확인
velero schedule get
# NAME         STATUS    CREATED                          SCHEDULE      BACKUP TTL
# daily-full   Enabled   2024-03-15 10:00:00 +0900 KST   0 2 * * *    168h0m0s
# hourly-db    Enabled   2024-03-15 10:05:00 +0900 KST   0 * * * *    24h0m0s
```

### Velero 복원

```bash
# 전체 복원 (다른 클러스터로 마이그레이션 시)
velero restore create --from-backup cluster-full-20240315 \
  --wait

# 특정 네임스페이스만 복원
velero restore create --from-backup cluster-full-20240315 \
  --include-namespaces database \
  --wait

# 네임스페이스 매핑 (이름 변경)
velero restore create --from-backup backend-backup-20240315 \
  --namespace-mappings "backend:backend-staging" \
  --wait

# 기존 리소스가 있을 때 정책
velero restore create --from-backup cluster-full-20240315 \
  --existing-resource-policy update \
  --wait

# 복원 상태 확인
velero restore get
# NAME                                   BACKUP                    STATUS
# cluster-full-20240315-20240315120000   cluster-full-20240315     Completed
```

---

## etcd 백업 및 복원

### etcd 스냅샷

```
[etcd 백업의 중요성]

etcd = Kubernetes의 모든 상태가 저장되는 분산 KV 스토어

etcd 손실 = 클러스터 전체 설정 유실
  ├── 모든 Deployment, Service, ConfigMap 정의 소실
  ├── RBAC, Namespace 설정 소실
  └── CRD (Custom Resource) 소실

관리형 K8s (EKS/AKS):
  └── 클라우드 제공자가 etcd 백업 관리 (사용자 접근 불가)

자체 관리 K8s (kubeadm):
  └── 직접 etcd 스냅샷 관리 필요 ⚠️
```

```bash
# kubeadm 환경에서 etcd 스냅샷 생성
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 스냅샷 검증
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-snapshot-20240315.db \
  --write-out=table
# +----------+----------+------------+------------+
# |   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# +----------+----------+------------+------------+
# | 5a1abc23 |   152340 |       1847 |     5.2 MB |
# +----------+----------+------------+------------+

# etcd 스냅샷에서 복원
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot-20240315.db \
  --data-dir=/var/lib/etcd-restore \
  --name=master-1 \
  --initial-cluster="master-1=https://10.0.1.10:2380" \
  --initial-advertise-peer-urls=https://10.0.1.10:2380
```

### etcd 자동 백업 (CronJob — 자체 관리 클러스터)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup
  namespace: kube-system
spec:
  schedule: "0 */6 * * *"     # 6시간마다
  jobTemplate:
    spec:
      template:
        spec:
          hostNetwork: true
          nodeSelector:
            node-role.kubernetes.io/control-plane: ""
          tolerations:
          - key: node-role.kubernetes.io/control-plane
            effect: NoSchedule
          containers:
          - name: etcd-backup
            image: registry.k8s.io/etcd:3.5.12-0
            command:
            - /bin/sh
            - -c
            - |
              TIMESTAMP=$(date +%Y%m%d-%H%M%S)
              etcdctl snapshot save /backup/etcd-${TIMESTAMP}.db \
                --endpoints=https://127.0.0.1:2379 \
                --cacert=/etc/kubernetes/pki/etcd/ca.crt \
                --cert=/etc/kubernetes/pki/etcd/server.crt \
                --key=/etc/kubernetes/pki/etcd/server.key

              # 검증
              etcdctl snapshot status /backup/etcd-${TIMESTAMP}.db

              # 7일 이상 된 백업 삭제
              find /backup -name "etcd-*.db" -mtime +7 -delete

              echo "etcd backup completed: etcd-${TIMESTAMP}.db"
            volumeMounts:
            - name: etcd-certs
              mountPath: /etc/kubernetes/pki/etcd
              readOnly: true
            - name: backup
              mountPath: /backup
          volumes:
          - name: etcd-certs
            hostPath:
              path: /etc/kubernetes/pki/etcd
          - name: backup
            persistentVolumeClaim:
              claimName: etcd-backup-pvc
          restartPolicy: OnFailure
```

---

## DR 전략 (Disaster Recovery)

### RPO / RTO 기반 DR 등급

```
[DR 등급 설계]

                    RPO (데이터 손실 허용)
                    │
            0분     │     1시간      24시간
            ├───────┼───────┼─────────┤
            │       │       │         │
Tier 1 ─────┤  Active-Active (RPO ≈ 0, RTO < 5min)
(LLM API)   │  멀티 리전 동시 운영
            │  비용: $$$$$
            │
Tier 2 ──────────────┤  Active-Standby (RPO < 1h, RTO < 30min)
(내부 도구)           │  Velero 시간별 백업 + Standby 클러스터
                     │  비용: $$$
                     │
Tier 3 ──────────────────────────────┤  Backup-Restore (RPO < 24h, RTO < 4h)
(개발 환경)                           │  Velero 일별 백업 + 필요 시 복원
                                     │  비용: $
```

### DR 시나리오별 복구 전략

```
[시나리오 1: 단일 Pod/Service 장애]
  ├── 자동 복구: K8s Self-healing (ReplicaSet)
  ├── RPO: 0 (데이터 손실 없음, PV 무관)
  └── RTO: 수 초 (Pod 재시작)

[시나리오 2: 노드 장애]
  ├── 자동 복구: Pod 다른 노드로 재스케줄
  ├── PV: EBS는 같은 AZ 노드로만 이동 ⚠️
  ├── RPO: 0
  └── RTO: 수 분 (Pod 재스케줄 + PV Attach)

[시나리오 3: AZ 장애]
  ├── 멀티 AZ 클러스터: 다른 AZ 노드에서 Pod 재생성
  ├── PV: EBS는 AZ 간 이동 불가 → 스냅샷 복원 필요 ⚠️
  ├── RPO: 마지막 스냅샷 시점
  └── RTO: 수십 분 (스냅샷 복원 + Pod 재생성)

[시나리오 4: 리전 장애 (대규모 DR)]
  ├── 다른 리전 클러스터에서 복원
  ├── Velero: S3 Cross-Region Replication + 복원
  ├── GitOps: ArgoCD가 새 클러스터에 앱 배포
  ├── RPO: 마지막 Velero 백업 시점
  └── RTO: 수 시간 (클러스터 준비 + 데이터 복원)

[시나리오 5: 클러스터 전체 손실 / 인적 오류]
  ├── etcd 스냅샷 + Velero 백업에서 전체 복원
  ├── GitOps 매니페스트로 앱 재배포
  ├── RPO: 마지막 백업 시점
  └── RTO: 수 시간
```

### 멀티 클라우드 DR 구성

```
[Allganize Multi-Cloud DR]

┌─────────────────┐         ┌─────────────────┐
│  AWS EKS        │         │  Azure AKS      │
│  (Primary)      │         │  (DR Standby)   │
│                 │         │                 │
│  Alli LLM API   │         │  (스케일 0)      │
│  MongoDB        │         │                 │
│  Elasticsearch  │         │                 │
└────────┬────────┘         └────────┬────────┘
         │                           │
         ▼                           ▼
┌─────────────────┐         ┌─────────────────┐
│  S3 Bucket      │────────►│  Azure Blob     │
│  (Velero 백업)   │  Cross  │  (Velero 백업)   │
│                 │  Cloud  │                 │
│                 │  Sync   │                 │
└─────────────────┘         └─────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  GitOps Repository (GitHub)             │
│                                         │
│  ├── apps/                              │
│  │   ├── base/          (공통 매니페스트) │
│  │   ├── overlays/aws/  (AWS 설정)       │
│  │   └── overlays/azure/(Azure 설정)     │
│  └── infrastructure/                    │
│      ├── aws/                           │
│      └── azure/                         │
└─────────────────────────────────────────┘

DR 발동 시:
1. Azure AKS 스케일 업
2. Velero로 Azure Blob에서 PV 데이터 복원
3. ArgoCD가 Git에서 앱 매니페스트 동기화
4. DNS 전환 (Route53 → Azure Traffic Manager)
```

### DR 테스트 자동화

```bash
#!/bin/bash
# dr-test.sh — 분기별 DR 훈련 스크립트
set -euo pipefail

DR_CLUSTER="aks-dr-cluster"
BACKUP_NAME=$(velero backup get -o json | jq -r '.items[-1].metadata.name')
NAMESPACE="backend"

echo "=== [1/5] DR 클러스터 접속 확인 ==="
kubectl --context ${DR_CLUSTER} cluster-info

echo "=== [2/5] 최신 백업 확인 ==="
echo "Restoring from: ${BACKUP_NAME}"
velero backup describe ${BACKUP_NAME}

echo "=== [3/5] 복원 실행 ==="
velero restore create dr-test-$(date +%Y%m%d) \
  --from-backup ${BACKUP_NAME} \
  --include-namespaces ${NAMESPACE} \
  --kubecontext ${DR_CLUSTER} \
  --wait

echo "=== [4/5] 서비스 상태 확인 ==="
kubectl --context ${DR_CLUSTER} get pods -n ${NAMESPACE}
kubectl --context ${DR_CLUSTER} rollout status deployment/backend-api -n ${NAMESPACE} --timeout=300s

echo "=== [5/5] API 헬스 체크 ==="
ENDPOINT=$(kubectl --context ${DR_CLUSTER} get svc backend-api -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl -sf "http://${ENDPOINT}/healthz" && echo "DR Test PASSED" || echo "DR Test FAILED"
```

### 백업 모니터링

```yaml
# Velero 백업 실패 시 알림 (Prometheus Alert)
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: velero-alerts
  namespace: monitoring
spec:
  groups:
  - name: velero
    rules:
    - alert: VeleroBackupFailed
      expr: |
        increase(velero_backup_failure_total[1h]) > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Velero 백업 실패"
        description: "최근 1시간 내 Velero 백업이 실패했습니다. 즉시 확인 필요."

    - alert: VeleroBackupNotRunRecently
      expr: |
        time() - velero_backup_last_successful_timestamp{schedule="daily-full"} > 86400 * 1.5
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Velero 일일 백업이 36시간 이상 실행되지 않음"
        description: "daily-full 스케줄 백업이 예정 시간에 실행되지 않았습니다."
```

---

## 면접 Q&A

### Q1: "Kubernetes 클러스터의 백업 전략을 설계해주세요"

**30초 답변**:
세 가지 레이어로 설계합니다. 첫째, GitOps로 모든 매니페스트를 Git에 저장하여 앱 배포 상태를 백업합니다. 둘째, Velero로 K8s 리소스와 PV 데이터를 S3에 정기 백업합니다. 셋째, 자체 관리 클러스터라면 etcd 스냅샷을 별도로 관리합니다.

**2분 답변**:
백업 전략은 RPO(허용 가능한 데이터 손실)와 RTO(복구 목표 시간)를 먼저 정의합니다.

첫째 레이어는 GitOps입니다. ArgoCD + Git 저장소에 모든 Kubernetes 매니페스트가 있으므로, 앱 배포 상태는 Git이 SSOT(Single Source of Truth)입니다. 클러스터를 새로 만들어도 ArgoCD만 연결하면 앱이 재배포됩니다.

둘째 레이어는 Velero입니다. GitOps로 복구할 수 없는 것들, 즉 PV 데이터, Secret, 동적으로 생성된 리소스를 백업합니다. 일별 전체 백업(7일 보존)과 시간별 DB 네임스페이스 백업(24시간 보존)을 스케줄링합니다. kopia를 사용하면 파일 레벨 증분 백업이 가능하여 Cross-Region, Cross-Cloud 복원도 가능합니다.

셋째 레이어는 etcd 스냅샷입니다. 관리형(EKS/AKS)에서는 클라우드가 관리하지만, kubeadm 환경에서는 6시간마다 스냅샷을 생성하고 외부 스토리지에 보관합니다.

모든 백업의 실패/성공을 Prometheus + Alertmanager로 모니터링하고, 분기별 DR 훈련으로 실제 복원을 검증합니다.

**💡 경험 연결**:
온프레미스에서 백업 솔루션(Veeam, NetBackup 등)을 운영하며 일별/주별/월별 백업 정책을 수립했던 경험이 있습니다. Kubernetes에서도 동일한 원칙이 적용되며, Velero가 이러한 역할을 수행합니다.

**⚠️ 주의**:
백업은 "복원 테스트를 하지 않으면 백업이 아니다." Velero 백업이 Completed 상태여도 실제 복원이 되는지 정기적으로 검증해야 한다.

### Q2: "etcd 백업은 왜 별도로 관리해야 하나요?"

**30초 답변**:
etcd는 Kubernetes의 모든 클러스터 상태가 저장되는 분산 KV 스토어입니다. etcd가 손실되면 모든 리소스 정의가 유실됩니다. EKS/AKS 같은 관리형에서는 클라우드가 자동 관리하지만, kubeadm 환경에서는 직접 스냅샷을 관리해야 합니다.

**2분 답변**:
etcd에는 Kubernetes의 모든 오브젝트가 저장됩니다. Deployment, Service, ConfigMap, Secret, RBAC, CRD 등 클러스터의 선언적 상태 전체가 etcd에 있습니다. etcd가 손실되면 클러스터는 존재하지만 "무엇을 실행해야 하는지" 모르는 상태가 됩니다.

Velero는 Kubernetes API를 통해 리소스를 백업하므로, API Server가 정상이어야 동작합니다. 반면 etcd 스냅샷은 API Server와 무관하게 etcd 데이터를 직접 백업합니다. 따라서 API Server 장애 시에도 etcd 스냅샷으로 복구할 수 있습니다.

관리형 K8s(EKS, AKS, GKE)에서는 Control Plane을 클라우드가 관리하므로 etcd 백업도 자동입니다. 사용자는 접근할 수 없고, 클라우드 SLA로 보호됩니다.

자체 관리 클러스터(kubeadm)에서는 반드시 etcd 스냅샷을 정기적으로 생성하고, 클러스터 외부(NFS, S3)에 보관해야 합니다. 스냅샷 주기는 RPO에 따라 결정합니다.

**💡 경험 연결**:
온프레미스에서 Active Directory나 DNS 서버의 설정 백업을 별도로 관리했던 것과 같은 맥락입니다. etcd는 Kubernetes의 "두뇌"이므로 별도의 백업 체계가 필요합니다.

**⚠️ 주의**:
etcd 스냅샷에는 Secret이 평문(Base64)으로 포함된다. 스냅샷 파일의 접근 권한과 암호화에 주의해야 한다. etcd encryption at rest를 활성화하면 스냅샷 내 Secret도 암호화된다.

### Q3: "DR 훈련을 어떻게 진행하시겠습니까?"

**30초 답변**:
분기별로 실제 DR 복원 테스트를 수행합니다. Velero 백업에서 별도 네임스페이스 또는 DR 클러스터로 복원하고, API 헬스 체크와 데이터 무결성을 검증합니다. 결과를 문서화하여 RPO/RTO 달성 여부를 확인합니다.

**2분 답변**:
DR 훈련은 네 단계로 진행합니다.

첫째, 복원 범위를 정의합니다. 전체 클러스터 복원인지, 특정 서비스만인지 결정합니다. 처음에는 단일 네임스페이스부터 시작하여 점차 범위를 넓힙니다.

둘째, 격리된 환경에서 복원합니다. DR 클러스터 또는 별도 네임스페이스에 Velero restore를 실행합니다. namespace-mappings로 이름을 변경하여 운영에 영향을 주지 않습니다.

셋째, 검증합니다. Pod 상태, API 헬스 체크, 데이터 무결성(DB 레코드 수, 최근 데이터 존재 여부)을 확인합니다. 실제 RTO(복원에 걸린 시간)를 측정합니다.

넷째, 결과를 문서화합니다. 복원 시간, 발견된 문제점, 개선 사항을 기록합니다. 목표 RPO/RTO를 달성했는지 평가하고, 미달 시 백업 주기나 아키텍처를 조정합니다.

자동화 스크립트로 DR 테스트를 반복 가능하게 만들고, 결과를 Slack/Teams로 알림하여 팀 전체가 인지하도록 합니다.

**💡 경험 연결**:
폐쇄망 환경에서 연 2회 DR 훈련을 진행했던 경험이 있습니다. 실제 훈련에서 발견된 문제(백업 파일 손상, 네트워크 설정 누락 등)는 문서만으로는 확인할 수 없는 것들이었습니다.

**⚠️ 주의**:
DR 훈련 없는 백업은 "슈뢰딩거의 백업"이다. 복원해보기 전까지는 백업이 유효한지 알 수 없다. 반드시 정기적으로 복원 테스트를 수행해야 한다.

### Q4: "Velero의 CSI Snapshot과 Kopia(File-level) 백업의 차이는?"

**30초 답변**:
CSI Snapshot은 스토리지 레벨의 COW(Copy-on-Write) 스냅샷으로 빠르지만 같은 클라우드/리전에서만 복원 가능합니다. Kopia는 파일 단위로 데이터를 S3에 백업하여 느리지만 Cross-Region, Cross-Cloud 복원이 가능합니다.

**2분 답변**:
CSI Snapshot 방식은 CSI Driver의 VolumeSnapshot API를 활용합니다. AWS에서는 EBS Snapshot, Azure에서는 Managed Disk Snapshot이 생성됩니다. 장점은 속도가 빠르고(COW 방식), 증분 스냅샷이 효율적이라는 것입니다. 단점은 같은 클라우드 프로바이더, 일반적으로 같은 리전에서만 복원 가능하다는 것입니다.

Kopia(이전 restic) 방식은 Node Agent(DaemonSet)가 PV의 파일을 직접 읽어서 S3 같은 Object Storage에 저장합니다. 중복 제거(Deduplication)와 암호화를 지원합니다. 장점은 저장 위치가 S3 호환이면 어디든 가능하므로 Cross-Region, Cross-Cloud DR에 적합합니다. 단점은 파일을 직접 읽으므로 대용량 볼륨에서 시간이 오래 걸립니다.

실무 전략은 두 방식을 병행하는 것입니다. 일상적인 백업은 CSI Snapshot으로 빠르게, DR 목적의 백업은 Kopia로 Cross-Region S3에 저장합니다.

**💡 경험 연결**:
온프레미스에서 스토리지 스냅샷(빠른 복원)과 테이프 백업(장기 보관, 오프사이트)을 병행했던 것과 같은 전략입니다.

**⚠️ 주의**:
Kopia/restic 백업 시 Pod가 실행 중인 상태에서 파일을 복사하므로, DB의 경우 파일 수준 일관성이 보장되지 않을 수 있다. DB는 자체 백업 도구(mongodump, pg_dump)를 병행하는 것이 안전하다.

---

## Allganize 맥락

| JD 요구사항 | 연결 포인트 |
|------------|------------|
| AWS/Azure 멀티클라우드 | Velero Kopia로 Cross-Cloud DR 구현 |
| AI/LLM 서비스 가용성 | RPO/RTO 기반 DR 등급 설계, Active-Standby 구성 |
| 복원력(Resilience) | Velero 스케줄 백업 + 모니터링 + 정기 DR 훈련 |
| Kubernetes 운영 | etcd 관리(관리형은 자동), Velero 복원 절차 숙지 |
| 온프레미스 경험 | 기존 백업/DR 운영 경험을 K8s + 클라우드로 전환 |

Allganize의 Alli 서비스는 고객의 AI 서비스를 운영하므로 데이터 손실이 치명적이다. MongoDB(사용자 데이터), Elasticsearch(검색 인덱스), LLM 모델 파일 등의 백업이 필수이며, AWS-Azure 간 Cross-Cloud DR 능력이 경쟁 우위가 된다.

---

**핵심 키워드**: `Velero` `etcd snapshot` `Disaster Recovery` `RPO` `RTO` `Kopia` `Cross-Cloud DR` `VolumeSnapshot` `GitOps` `Backup Schedule`
