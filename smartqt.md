# Isilon SmartQuotas를 활용한 Kubernetes NFS PV 용량 강제 및 모니터링 가이드

> **작성일**: 2026년 2월 20일
> **배경**: NFS Quota Agent(github.com/dasomel/nfs-quota-agent) 검토 결과를 토대로, Isilon 환경에 맞는 실질적 개선 방안 도출

---

## 1. 검토 경위 및 결론

### 1.1 출발점: NFS PV/PVC 용량 제한이 안 되는 문제

Kubernetes에서 NFS 기반 PV/PVC를 사용할 때, PVC에 `storage: 10Gi`를 요청해도 실제 파일시스템 레벨에서 쿼터가 강제되지 않습니다. csi-driver-nfs, nfs-subdir-external-provisioner 모두 마찬가지이며, 한 워크로드가 NFS 전체 스토리지를 잠식할 수 있는 위험이 있습니다.

### 1.2 NFS Quota Agent 검토 결과

[dasomel/nfs-quota-agent](https://github.com/dasomel/nfs-quota-agent)는 이 문제를 해결하기 위한 Go 기반 오픈소스 에이전트입니다. 핵심 동작은 다음과 같습니다:

- Kubernetes API를 Watch하여 NFS PV 감지
- NFS 서버 노드에서 `xfs_quota`/`setquota`로 프로젝트 쿼터 자동 적용
- XFS/ext4 파일시스템 지원, Helm Chart/Web UI/Prometheus 메트릭 내장

**그러나 프로젝트 README에 명시된 핵심 제약이 있습니다:**

> *"The agent **must** run on the NFS server node. This is not optional."*
> *"Quota commands are local-only — xfs_quota and setquota only work on local filesystems"*

### 1.3 Isilon 환경에 적용 불가한 이유

| NFS Quota Agent 요구사항 | Isilon 환경 |
|---|---|
| NFS 서버에 에이전트 바이너리 설치 | ❌ OneFS는 폐쇄형 OS, 임의 소프트웨어 설치 불가 |
| `xfs_quota` / `setquota` 실행 | ❌ OneFS 파일시스템, 해당 명령어 미존재 |
| hostPath로 NFS export 디렉토리 마운트 | ❌ Isilon은 K8s 노드가 아님 |

### 1.4 최종 결론: Isilon에는 이미 답이 있다

NFS Quota Agent가 OS 레벨 명령어로 해결하려는 바로 그 기능을, **Isilon은 SmartQuotas라는 네이티브 기능으로 이미 제공**하고 있습니다. 별도 에이전트를 설치할 필요 없이 Isilon 자체 기능을 활성화하면 됩니다.

| 비교 항목 | NFS Quota Agent | Isilon SmartQuotas |
|---|---|---|
| 쿼터 적용 방식 | OS 레벨 명령어 (xfs_quota) | Isilon 네이티브 기능 |
| 설치 필요 여부 | NFS 서버에 에이전트 설치 필수 | **설치 불필요** (Isilon 내장) |
| 보안 이슈 | NFS 서버에 privileged Pod 배포 | **없음** (벤더 공식 기능) |
| 다른 부서 협조 | NFS 서버 운영팀 에이전트 설치 승인 | **SmartQuotas 활성화 요청만** |
| 쿼터 강제력 | Hard (파일시스템 레벨 차단) | Hard (EDQUOT 에러 반환) |
| 모니터링 | Prometheus 메트릭 내장 | CLI/WebUI/API + rpc.quotad |

---

## 2. Isilon SmartQuotas 핵심 개념

### 2.1 쿼터 유형

| 유형 | 동작 | K8s PVC 연동 활용 |
|---|---|---|
| **Hard** | 초과 불가, 쓰기 즉시 실패 (EDQUOT) | PVC 요청 용량 = Hard Limit |
| **Soft** | Grace Period 동안 초과 허용 후 차단 | PVC 용량의 90%에 설정 → 사전 경고 |
| **Advisory** | 알림만 발송, 차단 없음 | PVC 용량의 80%에 설정 → 모니터링 |
| **Accounting** | 사용량 추적만, 제한 없음 | 초기 도입 시 현황 파악용 |

### 2.2 Container 옵션 (필수 권장)

`--container true` 옵션을 설정하면, 해당 디렉토리가 **독립적인 파일시스템처럼** 동작합니다.

**Container 미설정 시 (기본):**
```
# Pod 내부에서 df -h 실행 결과
Filesystem                     Size  Used  Avail  Use%
isilon:/ifs/data/k8s-pvs/pvc1  50T   30T   20T    60%   ← Isilon 전체 용량이 보임
```

**Container 설정 시:**
```
# Pod 내부에서 df -h 실행 결과
Filesystem                     Size  Used  Avail  Use%
isilon:/ifs/data/k8s-pvs/pvc1  10G   6G    4G     60%   ← 쿼터 크기가 보임
```

이렇게 해야 Pod 내부에서도 PVC 요청 용량과 일치하는 정보를 볼 수 있고, Prometheus node_exporter의 `node_filesystem_*` 메트릭도 정확해집니다.

---

## 3. 실전 적용 가이드

### 3.1 사전 확인

```bash
# 1. SmartQuotas 라이선스 확인
isi license list | grep SmartQuotas

# 2. SmartQuotas 서비스 활성화 확인
isi services -a | grep quota

# 3. K8s PV가 사용하는 Isilon 경로 확인
# Kubernetes 쪽에서 실행
kubectl get pv -o custom-columns=\
  'NAME:.metadata.name,NFS_PATH:.spec.nfs.path,CAPACITY:.spec.capacity.storage,STATUS:.status.phase'
```

**SmartQuotas 라이선스가 없는 경우:**
Dell 영업 담당에게 라이선스 활성화를 요청해야 합니다. 라이선스 없이는 쿼터 기능 자체를 사용할 수 없습니다.

### 3.2 Phase 1: 현황 파악 — Accounting Quota (제한 없음, 안전)

기존 PV에 대해 **사용량만 추적**하는 Accounting Quota를 먼저 적용합니다. 이 단계에서는 어떤 제한도 걸리지 않으므로 서비스 영향이 전혀 없습니다.

```bash
# 기존 PV 디렉토리에 Accounting Quota 일괄 생성 (Isilon CLI)
# 예: /ifs/data/k8s-pvs/ 하위 모든 PV 디렉토리

# 개별 생성
isi quota quotas create /ifs/data/k8s-pvs/default-pvc-abc123 directory

# 전체 하위 디렉토리에 default quota 적용 (자동 상속)
isi quota quotas create /ifs/data/k8s-pvs/ default-directory
```

```bash
# 사용량 현황 조회
isi quota quotas list --path=/ifs/data/k8s-pvs/ \
  --type=directory --format=table

# 출력 예시:
# Type       Path                                    Snap  Hard   Soft  Adv   Used
# directory  /ifs/data/k8s-pvs/default-pvc-abc123    No    -      -     -     8.5G
# directory  /ifs/data/k8s-pvs/prod-data-xyz789      No    -      -     -     45.2G
# directory  /ifs/data/k8s-pvs/dev-logs-def456       No    -      -     -     12.1G
```

**이 결과를 K8s PVC 요청량과 비교합니다:**

```bash
# K8s PVC 요청량 목록
kubectl get pvc --all-namespaces -o custom-columns=\
  'NAMESPACE:.metadata.namespace,NAME:.metadata.name,CAPACITY:.spec.resources.requests.storage,STATUS:.status.phase'
```

여기서 "PVC 요청 10Gi인데 실제 45Gi 쓰고 있는" PV를 식별하는 것이 핵심입니다.

### 3.3 Phase 2: 신규 PV에 Enforcement Quota 적용

신규로 생성되는 PV부터 Hard Quota를 적용합니다. 기존 PV는 아직 건드리지 않습니다.

```bash
# 신규 PV 디렉토리에 쿼터 생성 (예: PVC 요청량 10Gi)
isi quota quotas create /ifs/data/k8s-pvs/newapp-pvc-xxx \
  directory \
  --hard-threshold=10G \
  --percent-advisory-threshold=80 \
  --percent-soft-threshold=90 \
  --soft-grace=7d \
  --container=true \
  --enforced=true
```

**이 명령 하나로 다음이 모두 설정됩니다:**
- Hard Limit: 10G (초과 시 EDQUOT 에러, 쓰기 차단)
- Soft Limit: 9G (90%, 7일 유예 후 차단)
- Advisory: 8G (80%, 알림만, 차단 없음)
- Container: Pod 내부 df에서 10G로 표시

**검증:**
```bash
# Pod 내부에서 테스트
kubectl exec -it test-pod -- df -h /mnt/data
# → 10G로 표시되면 정상

kubectl exec -it test-pod -- dd if=/dev/zero of=/mnt/data/test bs=1M count=11000
# → 10G 초과 시 "Disk quota exceeded" 에러 발생하면 정상
```

### 3.4 Phase 3: 기존 PV 점진적 마이그레이션

기존에 이미 용량을 초과한 PV가 있을 수 있으므로, 바로 Hard Quota를 걸면 서비스 장애가 발생합니다. 단계적으로 접근합니다.

**Step 1 — 초과 PV 식별:**
```bash
# Isilon에서 초과 여부 확인 (Accounting 결과 기반)
# PVC 요청량 10Gi인데 실제 사용량이 15Gi인 경우 등 식별
isi quota quotas list --path=/ifs/data/k8s-pvs/ --type=directory --format=csv > quota_report.csv
```

**Step 2 — 초과하지 않은 PV부터 Hard Quota 적용:**
```bash
# 실제 사용량 < PVC 요청량인 PV에 Hard Quota 적용
isi quota quotas create /ifs/data/k8s-pvs/safe-pvc-001 \
  directory --hard-threshold=10G --container=true --enforced=true
```

**Step 3 — 초과 PV는 담당팀 통보 후 정리 기간 부여:**
```bash
# 초과 PV에는 현재 사용량보다 넉넉한 Advisory만 설정
isi quota quotas create /ifs/data/k8s-pvs/over-pvc-002 \
  directory --advisory-threshold=50G --enforced=true

# 담당팀에 데이터 정리 요청 후, 정리 완료 시점에 Hard Quota 적용
isi quota quotas modify /ifs/data/k8s-pvs/over-pvc-002 \
  directory --hard-threshold=10G --container=true
```

### 3.5 자동화: 스토리지팀에 요청할 스크립트

PVC가 생성될 때마다 수동으로 쿼터를 걸 수 없으므로, 스토리지팀에 아래 스크립트를 cron으로 실행하도록 요청합니다.

```bash
#!/bin/bash
# sync_k8s_quotas.sh
# K8s PV 목록과 Isilon 쿼터를 동기화하는 스크립트
# Isilon 서버에서 cron으로 실행 (예: 매 5분)

ISILON_PV_BASE="/ifs/data/k8s-pvs"
KUBECONFIG="/path/to/kubeconfig"  # K8s API 접근용 (또는 kubectl proxy)

# 1. K8s에서 Bound 상태인 NFS PV 목록 가져오기
kubectl --kubeconfig=$KUBECONFIG get pv -o json | \
  jq -r '.items[] | 
    select(.status.phase=="Bound") | 
    select(.spec.nfs.path // "" | startswith("'$ISILON_PV_BASE'")) |
    "\(.spec.nfs.path)\t\(.spec.capacity.storage)"' | \
while IFS=$'\t' read -r pv_path pv_capacity; do

  # 2. 이미 쿼터가 있는지 확인
  existing=$(isi quota quotas list --path="$pv_path" --type=directory --format=json 2>/dev/null | jq '.quotas | length')
  
  if [ "$existing" = "0" ]; then
    # 3. 쿼터 생성
    echo "[$(date)] Creating quota: $pv_path ($pv_capacity)"
    isi quota quotas create "$pv_path" directory \
      --hard-threshold="$pv_capacity" \
      --percent-advisory-threshold=80 \
      --percent-soft-threshold=90 \
      --soft-grace=7d \
      --container=true \
      --enforced=true
  fi
done
```

또는 kubectl 접근이 어려우면, **프로비저너가 디렉토리를 생성할 때 default-directory quota를 상속**하도록 설정할 수 있습니다:

```bash
# PV 상위 디렉토리에 default-directory quota 설정
# 하위에 새 디렉토리가 생성되면 자동으로 이 쿼터를 상속
isi quota quotas create /ifs/data/k8s-pvs/ default-directory \
  --hard-threshold=10G \
  --container=true \
  --enforced=true
```

> ⚠️ **주의**: default-directory는 모든 하위 디렉토리에 동일한 쿼터를 적용하므로, PVC마다 다른 용량을 요청하는 경우에는 적합하지 않습니다. 이 경우 위의 스크립트 방식이나 REST API 자동화가 필요합니다.

---

## 4. 모니터링

### 4.1 Isilon WebUI에서 직접 확인

**File System > SmartQuotas > Quotas & Usage**에서 쿼터별 사용량, 초과 여부, 알림 내역을 GUI로 확인할 수 있습니다.

### 4.2 CLI 기반 모니터링

```bash
# 전체 쿼터 사용량 조회
isi quota quotas list --path=/ifs/data/k8s-pvs/ --type=directory --format=table

# 초과된 쿼터만 조회 (가장 중요한 명령)
isi quota quotas list --exceeded

# 특정 PV 상세 조회
isi quota quotas view --path=/ifs/data/k8s-pvs/prod-data-xyz789 --type=directory

# 쿼터 리포트 생성
isi quota reports create
isi quota reports list
```

### 4.3 rpc.quotad를 통한 클라이언트 쿼터 확인

OneFS 8.2 이상에서는 `rpc.quotad` 서비스가 기본 활성화되어 있어, NFS 클라이언트(K8s 노드)에서 Linux `quota` 명령으로 쿼터 정보를 직접 조회할 수 있습니다.

```bash
# K8s 노드 또는 Pod에서 실행
quota -v
# 또는
repquota -a
```

### 4.4 Prometheus 연동

Isilon에서 직접 Prometheus 메트릭을 노출하지는 않지만, 다음 방법으로 연동할 수 있습니다:

**방법 1: node_exporter의 filesystem 메트릭 활용 (container=true 설정 시)**

SmartQuotas에서 `--container=true`를 설정하면 NFS 마운트 시 쿼터 크기가 파일시스템 크기로 보고됩니다. 따라서 K8s 노드의 node_exporter가 수집하는 `node_filesystem_size_bytes`, `node_filesystem_avail_bytes` 메트릭이 자동으로 쿼터 크기를 반영합니다.

```promql
# PVC 사용률 (container=true 설정 시 자동으로 쿼터 기준)
1 - (node_filesystem_avail_bytes{mountpoint=~"/var/lib/kubelet/pods/.*/volumes/.*"} 
    / node_filesystem_size_bytes{mountpoint=~"/var/lib/kubelet/pods/.*/volumes/.*"})
```

**방법 2: 커스텀 Exporter 스크립트**

```bash
#!/bin/bash
# isilon_quota_exporter.sh
# cron으로 실행하여 Prometheus textfile collector에 메트릭 출력

OUTPUT="/var/lib/node_exporter/textfile_collector/isilon_quota.prom"

echo "# HELP isilon_quota_hard_bytes Hard quota limit in bytes" > $OUTPUT
echo "# TYPE isilon_quota_hard_bytes gauge" >> $OUTPUT
echo "# HELP isilon_quota_used_bytes Current usage in bytes" >> $OUTPUT  
echo "# TYPE isilon_quota_used_bytes gauge" >> $OUTPUT

isi quota quotas list --path=/ifs/data/k8s-pvs/ --type=directory --format=json | \
  jq -r '.quotas[] | 
    "isilon_quota_hard_bytes{path=\"\(.path)\"} \(.thresholds.hard // 0)\n" +
    "isilon_quota_used_bytes{path=\"\(.path)\"} \(.usage.logical // 0)"' >> $OUTPUT
```

### 4.5 Grafana 대시보드 권장 패널

- **PVC별 사용률 히트맵**: 80% 이상 노란색, 95% 이상 빨간색
- **초과 임박 PVC Top-10**: Hard Limit 대비 사용량 상위 목록
- **Namespace별 총 스토리지 사용량 추이**: 시간대별 그래프
- **쿼터 초과 이벤트 타임라인**: Advisory/Soft/Hard 초과 이력

### 4.6 알림 규칙

**Isilon 자체 알림 (SmartQuotas Notification):**
```bash
# Advisory 초과 시 이메일 알림
isi quota notifications create /ifs/data/k8s-pvs/ directory \
  advisory exceeded \
  --action-email-address=k8s-ops@company.com \
  --holdoff=3600

# Hard 초과 시 이메일 알림
isi quota notifications create /ifs/data/k8s-pvs/ directory \
  hard exceeded \
  --action-email-address=k8s-ops@company.com,storage-team@company.com \
  --holdoff=0
```

**Prometheus AlertManager (container=true + node_exporter 기반):**
```yaml
groups:
- name: nfs-quota-alerts
  rules:
  - alert: NFSQuotaUsageWarning
    expr: |
      (1 - node_filesystem_avail_bytes{fstype="nfs4"} 
           / node_filesystem_size_bytes{fstype="nfs4"}) > 0.8
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "NFS PV 사용률 80% 초과: {{ $labels.mountpoint }}"

  - alert: NFSQuotaUsageCritical
    expr: |
      (1 - node_filesystem_avail_bytes{fstype="nfs4"} 
           / node_filesystem_size_bytes{fstype="nfs4"}) > 0.95
    for: 3m
    labels:
      severity: critical
    annotations:
      summary: "NFS PV 사용률 95% 초과 - 즉시 대응: {{ $labels.mountpoint }}"
```

---

## 5. 스토리지팀 요청 시 포인트

### 5.1 요청 사항 정리 (스토리지팀에 전달)

이 요청은 **Isilon에 새 소프트웨어를 설치하는 것이 아니라**, Isilon이 이미 보유한 SmartQuotas 기능을 활성화해 달라는 것입니다.

| 요청 항목 | 상세 | 비고 |
|---|---|---|
| SmartQuotas 라이선스 확인 | `isi license list` 결과 공유 | 미활성 시 Dell 영업 접촉 |
| K8s PV 디렉토리에 Directory Quota 생성 | Hard + Advisory + container=true | 1회성 설정 |
| 신규 PV에 대한 자동 쿼터 적용 | cron 스크립트 또는 default-directory | 운영 프로세스 |
| 초과 알림 이메일 설정 | SmartQuotas Notification 기능 | Isilon 자체 기능 |
| 쿼터 리포트 주기 설정 | `isi quota reports` 스케줄 | 주 1회 권장 |

### 5.2 설득 포인트

1. **Isilon 자체 기능이므로 보안 이슈 없음**: Dell이 공식 지원하는 OneFS 네이티브 기능이며, 외부 소프트웨어 설치가 아닙니다.
2. **서비스 영향 없음**: Accounting Quota부터 시작하면 기존 워크로드에 영향이 전혀 없습니다.
3. **스토리지팀 부담 감소**: 현재 쿼터 미적용 상태에서 한 워크로드가 NFS 전체를 잠식하면 장애 대응은 결국 스토리지팀 몫입니다. 쿼터를 미리 설정하면 장애 예방이 됩니다.
4. **최소한의 작업량**: 초기에 `isi quota quotas create` 명령 몇 번이면 되고, 이후 자동화 스크립트 cron 등록 한 번이면 끝입니다.

---

## 6. 요약

### 6.1 왜 NFS Quota Agent 대신 SmartQuotas인가

NFS Quota Agent는 **Linux NFS 서버용**으로 설계되었고, NFS 서버 노드에서 직접 실행해야 합니다. Isilon은 폐쇄형 OneFS이므로 에이전트를 설치할 수 없고, 설치할 필요도 없습니다. Isilon SmartQuotas가 동일한 기능(파일시스템 레벨 용량 강제)을 네이티브로 제공하기 때문입니다.

### 6.2 액션 플랜

| 단계 | 기간 | 내용 | 담당 |
|---|---|---|---|
| **1. 라이선스 확인** | 즉시 | SmartQuotas 라이선스 활성화 확인 | 스토리지팀 |
| **2. 현황 파악** | 1주 | Accounting Quota 적용, PVC vs 실제 사용량 비교 | 인프라팀 + 스토리지팀 |
| **3. 신규 PV 쿼터** | 2주 | 신규 PV에 Hard Quota + container=true 적용 | 스토리지팀 |
| **4. 기존 PV 정리** | 3-4주 | 초과 PV 식별 → 담당팀 통보 → 점진적 Hard Quota | 인프라팀 + 개발팀 |
| **5. 자동화** | 4-5주 | cron 스크립트 또는 default-directory 설정 | 스토리지팀 |
| **6. 모니터링** | 5-6주 | container=true 기반 Prometheus/Grafana 대시보드 구축 | 인프라팀 |
| **7. 알림 설정** | 6주 | SmartQuotas Notification + AlertManager 규칙 | 인프라팀 + 스토리지팀 |

### 6.3 참고 자료

- [Dell PowerScale SmartQuotas 백서](https://www.delltechnologies.com/asset/en-us/products/storage/industry-market/h10575-wp-powerscale-onefs-smartquotas.pdf)
- [Dell PowerScale OneFS CLI - SmartQuotas](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_administration_guide_cli/smartquotas-overview)
- [Dell Ansible PowerScale Collection - SmartQuota 모듈](https://github.com/dell/ansible-powerscale)
- [Dell InfoHub - SmartQuotas Best Practices](https://infohub.delltechnologies.com/l/storage-quota-management-and-provisioning-with-dell-powerscale-smartquotas-1/smartquotas-best-practices)
- [NFS Quota Agent (참고)](https://github.com/dasomel/nfs-quota-agent) — 문제 인식 및 아키텍처 참고용
- [Kubernetes Issue #124159](https://github.com/kubernetes/kubernetes/issues/124159) — NFS storage capacity 미적용 공식 이슈