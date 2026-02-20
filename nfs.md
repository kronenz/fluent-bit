# NFS Quota Agent 프로젝트 분석 및 Isilon NFS 용량 이슈 개선 가이드

> **대상 레포지토리**: [github.com/dasomel/nfs-quota-agent](https://github.com/dasomel/nfs-quota-agent)
> **라이선스**: Apache-2.0 | **언어**: Go | **커밋**: 60건
> **작성일**: 2026년 2월 20일

---

## 목차

1. [Executive Summary](#1-executive-summary)
2. [문제 정의: NFS PV/PVC 용량 제한 미적용](#2-문제-정의)
3. [NFS Quota Agent 프로젝트 상세 분석](#3-프로젝트-상세-분석)
4. [Dell Isilon NFS 환경 적용 전략](#4-isilon-적용-전략)
5. [단계별 도입 로드맵](#5-도입-로드맵)
6. [모니터링 및 알림 연동](#6-모니터링-및-알림)
7. [리스크 및 완화 전략](#7-리스크-및-완화)
8. [결론 및 권장사항](#8-결론)

---

## 1. Executive Summary

Kubernetes 환경에서 NFS 기반 PersistentVolume(PV)/PersistentVolumeClaim(PVC)을 사용할 때, PVC에 명시한 `storage` 요청량(예: `10Gi`)이 **실제 파일시스템 레벨에서 강제되지 않는** 근본적인 문제가 존재합니다. Kubernetes 메인테이너가 공식적으로 인정한 이 문제는 NFS 프로토콜 자체의 한계에 기인합니다.

**NFS Quota Agent**(nfs-quota-agent)는 이 문제를 해결하기 위해 설계된 오픈소스 Kubernetes 에이전트로, NFS 서버 노드에서 직접 실행되어 **XFS/ext4 프로젝트 쿼터를 자동으로 적용**합니다.

본 문서는 이 프로젝트를 상세 분석하고, **Dell PowerScale(Isilon) NFS** 환경에서 용량 이슈를 개선하기 위한 전략을 제시합니다.

---

## 2. 문제 정의

### 2.1 문제의 본질

NFS 프로토콜은 특정 폴더에 대한 용량 제한(quota) 기능을 내장하고 있지 않습니다. Kubernetes에서 PVC에 `storage: 10Gi`를 요청하더라도, 이는 Kubernetes 스케줄러의 메타데이터일 뿐 실제 NFS 파일시스템에서 강제되는 제한이 아닙니다.

> **Kubernetes 메인테이너 공식 입장**: "PV에 사이즈를 보고하는 것은 기반 파일시스템에 강제를 추가하지 않습니다."

### 2.2 영향받는 NFS 프로비저너

| 프로비저너 | 쿼터 지원 | 비고 |
|---|---|---|
| **csi-driver-nfs** | ❌ 미지원 | Kubernetes SIG Storage 공식 |
| **nfs-subdir-external-provisioner** | ❌ 미지원 | "프로비저닝된 스토리지 제한 미강제" 공식 문서 명시 |
| **nfs-ganesha-provisioner** | ⚠️ XFS quota 옵션 | xfs prjquota 필수, 아카이브됨 |

### 2.3 위험 시나리오

1. **클러스터 전체 장애**: 단일 워크로드가 NFS 공유 스토리지 전체를 잠식하여 동일 NFS 공유를 사용하는 모든 애플리케이션에 장애 발생
2. **모니터링 불일치**: Prometheus/Grafana에서 보이는 PVC 용량과 실제 사용량 불일치로 운영 불확실성
3. **멀티테넌트 통제 불가**: 특정 팀/네임스페이스의 스토리지 사용량 제한이 실질적으로 불가능
4. **ResourceQuota 무력화**: Kubernetes ResourceQuota 정책이 실제 스토리지 사용을 제한하지 못함

---

## 3. 프로젝트 상세 분석

### 3.1 프로젝트 개요

| 항목 | 내용 |
|---|---|
| **이름** | NFS Quota Agent |
| **레포** | github.com/dasomel/nfs-quota-agent |
| **언어** | Go |
| **라이선스** | Apache-2.0 |
| **지원 파일시스템** | XFS (`xfs_quota`), ext4 (`setquota`) |
| **Kubernetes 버전** | v1.20+ |
| **배포 방식** | Helm Chart, Binary, Docker |
| **커밋 수** | 60건 |

### 3.2 디렉토리 구조

```
nfs-quota-agent/
├── .github/workflows/      # CI/CD 파이프라인
├── charts/nfs-quota-agent/  # Helm Chart
├── cmd/nfs-quota-agent/     # 엔트리포인트 (main)
├── docs/                    # 문서 및 스크린샷
├── internal/                # 핵심 비즈니스 로직
├── Dockerfile               # 컨테이너 이미지 빌드
├── Makefile                 # 빌드 자동화
├── go.mod / go.sum          # Go 의존성
├── AGENT.md                 # 에이전트 설명
├── CHANGELOG.md             # 변경 이력
└── README.md / README_ko.md # 영문/한국어 문서
```

### 3.3 핵심 동작 메커니즘

#### Step 1: 파일시스템 자동 감지
에이전트가 시작되면 NFS 서버의 파일시스템 유형(XFS 또는 ext4)을 자동으로 감지합니다.

#### Step 2: PV 감시 (Watcher)
Kubernetes API Server를 Watch하여 다음 조건의 NFS PV를 감지합니다:
- `Bound` 상태인 PV
- 설정된 프로비저너로 생성된 PV (또는 `--process-all-nfs` 시 모든 NFS PV)
- **네이티브 NFS PV** (`pv.Spec.NFS`)와 **CSI 기반 NFS PV** (`nfs.csi.k8s.io`) 모두 지원

#### Step 3: 경로 매핑
NFS 서버 경로를 로컬 경로로 변환합니다:
- **네이티브 NFS**: `pv.Spec.NFS.Path` 사용
- **CSI NFS**: `pv.Spec.CSI.VolumeAttributes["share"]` + `["subdir"]` 사용
- 예: `/data/namespace-pvc-xxx` → `/export/namespace-pvc-xxx`

#### Step 4: 프로젝트 ID 생성
PV 이름으로부터 FNV 해시를 사용하여 고유한 프로젝트 ID를 생성합니다.

#### Step 5: 쿼터 적용
- **XFS**: `xfs_quota`로 프로젝트를 초기화하고 블록 제한 설정
- **ext4**: `chattr`로 프로젝트 속성을 설정하고 `setquota`로 제한 설정
- `/etc/projects`와 `/etc/projid` 파일에 프로젝트 엔트리 생성

#### Step 6: 상태 추적
PV 어노테이션을 업데이트하여 쿼터 상태를 반영합니다:
- `nfs.io/quota-status`: `pending`, `applied`, `failed`

### 3.4 NFS 서버 노드 실행 필수 이유

```
┌─────────────────────────────────────────────────────────────┐
│                     NFS Server Node                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              nfs-quota-agent (Pod)                     │ │
│  │   xfs_quota / setquota commands                        │ │
│  │              ↓                                         │ │
│  │   hostPath: /data  →  container: /export               │ │
│  └────────────────────────────────────────────────────────┘ │
│                          ↓                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │          XFS/ext4 Filesystem (/data)                   │ │
│  │   Project quota can ONLY be set on local filesystem    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**핵심 제약사항:**
- `xfs_quota`와 `setquota`는 **로컬 파일시스템에서만** 동작
- NFS 클라이언트에서는 쿼터 명령 실행 불가
- 실제 디스크에 대한 직접 파일시스템 접근(hostPath) 필요

### 3.5 주요 기능 일람

| 기능 | 설명 | Helm 설정 |
|---|---|---|
| **쿼터 자동 적용** | PV 감지 → 프로젝트 쿼터 자동 설정 | 기본 활성화 |
| **Web UI 대시보드** | 실시간 디스크 사용량, PV/PVC 바인딩 상태, 파일 브라우저 | `webUI.enabled=true` |
| **Prometheus 메트릭** | `:9090` 엔드포인트로 메트릭 노출 | `service.enabled=true` |
| **감사 로깅** | 쿼터 변경 이력 기록 | `audit.enabled=true` |
| **고아 디렉토리 정리** | PV 삭제 후 남은 디렉토리 자동 정리 | `cleanup.enabled=true` |
| **사용량 히스토리** | 시간별 사용량 추이 기록 (30일 보존) | `history.enabled=true` |
| **네임스페이스 정책** | LimitRange/ResourceQuota/어노테이션 기반 정책 | `policy.enabled=true` |

### 3.6 CLI 명령어

```bash
# 쿼터 강제 에이전트 실행 (기본)
nfs-quota-agent run --nfs-base-path=/export --provisioner-name=nfs.csi.k8s.io

# 쿼터 상태 및 디스크 사용량 조회
nfs-quota-agent status --path=/data

# 사용량 상위 디렉토리 표시
nfs-quota-agent top --path=/data -n 10

# 리포트 생성 (JSON/YAML/CSV)
nfs-quota-agent report --path=/data --format=json

# 고아 쿼터 정리 (dry-run)
nfs-quota-agent cleanup --path=/data --kubeconfig=~/.kube/config

# Web UI 대시보드 실행
nfs-quota-agent ui --path=/data --addr=:8080
```

---

## 4. Dell Isilon NFS 환경 적용 전략

### 4.1 Isilon 환경의 근본적 차이점

NFS Quota Agent는 **NFS 서버 노드에서 XFS/ext4 프로젝트 쿼터를 직접 실행**하는 방식입니다. 그러나 Dell PowerScale(Isilon)은 자체 OneFS 파일시스템을 사용하며 `xfs_quota`나 `setquota` 명령을 직접 실행할 수 없습니다.

| 항목 | NFS Quota Agent (자체 NFS) | Isilon 환경 |
|---|---|---|
| 파일시스템 | XFS / ext4 | OneFS (자체 파일시스템) |
| 쿼터 도구 | `xfs_quota`, `setquota` | **SmartQuotas** (라이선스 필요) |
| 쿼터 적용 방식 | OS 레벨 명령어 | REST API(PAPI) 또는 CLI(`isi quota`) |
| 에이전트 실행 위치 | NFS 서버 노드 | Kubernetes 클러스터 내 (어디서든) |

### 4.2 접근 방법: SmartQuotas API 연동

Isilon 환경에서는 NFS Quota Agent의 **Quota Enforcer 모듈을 Isilon SmartQuotas API로 대체**하는 것이 핵심입니다.

#### SmartQuotas 쿼터 유형과 K8s 매핑

| SmartQuotas 유형 | 동작 | K8s 연동 활용 |
|---|---|---|
| **Hard Quota** | 초과 불가, 쓰기 즉시 실패 (EDQUOT) | PVC storage 요청량을 Hard Limit으로 설정 |
| **Soft Quota** | Grace Period 동안 초과 허용 후 차단 | PVC 요청량의 90%를 Soft Limit으로 사전 경고 |
| **Advisory** | 알림만 발송, 차단 없음 | PVC 요청량의 80%에 Advisory 설정으로 모니터링 |
| **Accounting** | 사용량 추적만, 제한 없음 | 초기 도입 단계에서 현황 파악용 |

#### Isilon REST API(PAPI) 쿼터 관리

**쿼터 생성:**
```bash
POST https://<isilon>:8080/platform/1/quota/quotas
Content-Type: application/json

{
  "type": "directory",
  "path": "/ifs/data/k8s-pvs/pvc-xxxx-yyyy",
  "include_snapshots": false,
  "enforced": true,
  "container": true,
  "thresholds": {
    "hard": 10737418240,
    "advisory": 8589934592,
    "soft": 9663676416,
    "soft_grace": 604800
  },
  "thresholds_include_overhead": false
}
```

**쿼터 조회:**
```bash
GET https://<isilon>:8080/platform/1/quota/quotas?path=/ifs/data/k8s-pvs/&type=directory
```

**쿼터 수정 (PVC Resize 시):**
```bash
PUT https://<isilon>:8080/platform/1/quota/quotas/{quota-id}
Content-Type: application/json

{
  "thresholds": {
    "hard": 21474836480
  }
}
```

#### CLI 대안 (SSH 접근 시)

```bash
# 쿼터 생성
isi quota quotas create /ifs/data/k8s-pvs/pvc-xxxx-yyyy \
  directory --hard-threshold=10G \
  --percent-advisory-threshold=80 \
  --percent-soft-threshold=90 --soft-grace=7d

# 쿼터 조회
isi quota quotas list --path=/ifs/data/k8s-pvs/ --type=directory

# 초과 쿼터 확인
isi quota quotas list --exceeded
```

### 4.3 Container Quota 옵션 (필수 권장)

SmartQuotas의 `container: true` 옵션을 설정하면 해당 디렉토리가 독립적인 용량 컨테이너로 취급됩니다. NFS 클라이언트에서 `df` 명령으로 확인할 때 **쿼터 크기가 전체 파일시스템 대신 할당된 쿼터 크기로 표시**되어, Pod 내부에서도 정확한 용량 정보를 확인할 수 있습니다.

### 4.4 Ansible 기반 자동화 (대안)

Dell은 `dellemc.powerscale` Ansible Collection을 공식 제공하고 있어 별도 자동화 파이프라인을 구축할 수 있습니다:

```yaml
- name: Create SmartQuota for K8s PVC
  dellemc.powerscale.smartquota:
    onefs_host: "{{ isilon_host }}"
    api_user: "{{ api_user }}"
    api_password: "{{ api_password }}"
    path: "/ifs/data/k8s-pvs/{{ pvc_name }}"
    quota_type: "directory"
    quota:
      include_snapshots: false
      include_overheads: false
      hard_limit_size: "{{ pvc_size_gi }}"
      advisory_limit_size: "{{ (pvc_size_gi|int * 0.8)|int }}"
      soft_limit_size: "{{ (pvc_size_gi|int * 0.9)|int }}"
      soft_grace_period: 7
      period_unit: "days"
      cap_unit: "GB"
    state: "present"
```

---

## 5. 단계별 도입 로드맵

### Phase 1: 현황 파악 및 계정 쿼터 (주차 1-2)

**목표**: 기존 NFS PV의 실제 사용량 파악

1. 기존 NFS PV/PVC 목록 및 요청 용량 전수조사
   ```bash
   kubectl get pv -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.nfs.path}{"\t"}{.spec.capacity.storage}{"\n"}{end}'
   ```
2. Isilon SmartQuotas 라이선스 확인 및 활성화
3. 기존 PV 경로에 **Accounting Quota** 생성하여 실제 사용량 파악
   ```bash
   isi quota quotas create /ifs/data/k8s-pvs/ directory
   ```
4. PVC 요청량 vs 실제 사용량 불일치 보고서 작성

### Phase 2: 파일럿 적용 (주차 3-4)

**목표**: 비프로덕션 환경에서 검증

1. **자체 NFS 서버 환경**: NFS Quota Agent를 dev/staging 클러스터에 Helm으로 배포
   ```bash
   helm install nfs-quota-agent ./charts/nfs-quota-agent \
     --namespace nfs-quota-agent --create-namespace \
     --set config.nfsBasePath=/export \
     --set config.nfsServerPath=/data \
     --set config.provisionerName=nfs.csi.k8s.io
   ```
2. **Isilon 환경**: 동일 로직을 SmartQuotas API 호출로 구현한 커스텀 컨트롤러 개발 또는 NFS Quota Agent를 fork하여 Isilon 백엔드 추가
3. Hard Quota 초과 시 Pod 내부에서 `EDQUOT` 에러 발생 확인
4. Web UI 대시보드 활성화하여 시각적 모니터링 검증

### Phase 3: 기존 PV 마이그레이션 (주차 5-6)

**목표**: 프로덕션 점진적 적용

1. 기존 PV에 대한 쿼터 일괄 적용 (이미 초과된 PV 식별 후 **Soft Quota부터** 적용)
2. 용량 초과 PV 소유 팀에 정리 공지 및 데이터 정리 협조
3. 점진적 Hard Quota 적용: `Accounting → Advisory → Soft → Hard`
4. 프로덕션 환경 적용 및 전체 운영 프로세스 수립

---

## 6. 모니터링 및 알림

### 6.1 NFS Quota Agent 기본 메트릭 (`:9090`)

NFS Quota Agent는 Prometheus 메트릭 엔드포인트를 내장하고 있으며, 다음과 같은 메트릭을 수집할 수 있습니다:

| 메트릭 | 용도 |
|---|---|
| 디렉토리별 쿼터 할당량 | PVC 요청량과의 일치 확인 |
| 디렉토리별 실제 사용량 | 용량 초과 임박 감지 |
| 쿼터 적용 상태 | `applied`, `pending`, `failed` 추적 |
| 고아 디렉토리 수 | 정리 대상 식별 |

### 6.2 Grafana 대시보드 구성 권장안

- PVC별 용량 사용율 히트맵 (namespace/pvc-name 기준)
- Quota 초과 임박 PVC Top-10 리스트 (80% 이상 사용중)
- Namespace별 총 스토리지 사용량 추이 그래프
- PVC-Quota 동기화 상태 패널 (Reconciler 정상 동작 확인)
- Isilon SmartQuotas 초과 이벤트 타임라인

### 6.3 알림 규칙 (권장)

| 수준 | 조건 | 액션 |
|---|---|---|
| **Warning** | 사용량 > 80% (5분 지속) | Slack/Teams 알림, 담당팀 통보 |
| **Critical** | 사용량 > 95% (3분 지속) | PagerDuty/전화 호출, 즉시 대응 |
| **Info** | 쿼터 동기화 상태 이상 (10분 지속) | Agent 동기화 이상 조사 |

---

## 7. 리스크 및 완화 전략

| 리스크 | 영향 | 완화 방안 |
|---|---|---|
| **기존 PV 용량 초과** | 쿼터 적용 시 즉시 쓰기 차단 → 애플리케이션 장애 | Accounting → Advisory → Soft → Hard 순서로 점진적 적용, 충분한 유예기간 제공 |
| **API 인증 보안** | Isilon API 자격증명 노출 시 스토리지 전체 위험 | K8s Secret으로 관리, RBAC 최소 권한 적용, 서비스 계정 분리 |
| **Agent 장애** | Agent 다운 시 새 PVC에 쿼터 미적용 | Reconciler가 재시작 시 불일치 자동 보정, Liveness Probe 설정 |
| **SmartQuotas 미라이선스** | SmartQuotas는 별도 라이선스 필요 | 사전 라이선스 확인, 미라이선스 시 du+알림 기반 소프트 제한 대안 검토 |
| **Isilon 동시 쓰기 경합** | Hard Quota가 동시 쓰기 시 coalescer로 인해 일시 초과 가능 | Soft Quota와 모니터링 병행, 약간의 여유 버퍼(5-10%) 설정 |
| **네트워크 분리** | Agent가 Isilon 관리 네트워크에 접근 필요 | NetworkPolicy로 Agent Pod만 Isilon API 접근 허용, 별도 관리 VLAN 활용 |
| **SnapshotIQ Reserve** | Isilon에서 예상치 못한 'Disk Quota Exceeded' 에러 발생 가능 | SnapshotIQ reserve 비율 확인 및 조정, 쿼터 에이전트 도입 시 반드시 점검 |

---

## 8. 결론 및 권장사항

### 8.1 핵심 권장사항 요약

- **즉시 적용**: 기존 NFS PV 전수조사 및 Isilon SmartQuotas Accounting Quota 적용으로 현황 파악
- **단기**: NFS Quota Agent를 비프로덕션에 파일럿 배포 (자체 NFS 서버 환경) + Isilon 환경용 SmartQuotas API 연동 컨트롤러 개발/검증
- **중기**: 프로덕션 환경 적용 및 Prometheus/Grafana 모니터링 통합, 점진적 Hard Quota 강제
- **장기**: CSI Driver 레벨의 네이티브 쿼터 연동 검토 또는 블록 스토리지(Longhorn, Rook-Ceph) 전환 평가

### 8.2 NFS Quota Agent의 Isilon 환경 적용 판단

| 시나리오 | 권장 방식 |
|---|---|
| **자체 XFS/ext4 NFS 서버** 사용 중 | NFS Quota Agent **그대로 적용** 가능 |
| **Isilon NFS** 사용 + SmartQuotas 라이선스 보유 | NFS Quota Agent의 **Watcher/Reconciler 로직 재활용** + Quota Enforcer를 SmartQuotas API로 교체 |
| **Isilon NFS** 사용 + SmartQuotas 라이선스 미보유 | NFS Quota Agent의 모니터링/알림 기능만 활용 + `du` 기반 소프트 제한 |
| **혼합 환경** (자체 NFS + Isilon) | NFS Quota Agent 이중 배포: 자체 NFS용 원본 + Isilon용 커스텀 빌드 |

### 8.3 기대 효과

- NFS 공유 스토리지 잠식으로 인한 **클러스터 전체 장애 예방**
- 멀티테넌트 환경에서 **공정한 스토리지 자원 분배**
- PVC 요청 용량과 실제 사용량의 **일치로 모니터링 신뢰성 향상**
- 스토리지 용량 계획 및 **비용 예측의 정확성 개선**

### 참고 자료

- [NFS Quota Agent GitHub](https://github.com/dasomel/nfs-quota-agent) - Apache-2.0
- [Kubernetes Issue: NFS storage capacity doesn't work](https://github.com/kubernetes/kubernetes/issues/124159)
- [nfs-subdir-external-provisioner 공식 문서](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner) - "The provisioned storage limit is not enforced"
- [Dell PowerScale SmartQuotas 백서](https://www.delltechnologies.com/asset/en-us/products/storage/industry-market/h10575-wp-powerscale-onefs-smartquotas.pdf)
- [Dell Ansible PowerScale Collection](https://github.com/dell/ansible-powerscale) - SmartQuota 자동화
- [Dell PowerScale OneFS API Reference - SmartQuotas](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_onefs_api_reference/smartquotas-overview)