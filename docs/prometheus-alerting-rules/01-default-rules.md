# kube-prometheus-stack 기본 내장 Alerting Rules

> kube-prometheus-stack v73.1.0 기준 | Kubernetes 1.14+

---

## 목차

- [1. alertmanager.rules](#1-alertmanagerrules)
- [2. config-reloaders](#2-config-reloaders)
- [3. etcd](#3-etcd)
- [4. general.rules](#4-generalrules)
- [5. kube-apiserver-slos](#5-kube-apiserver-slos)
- [6. kube-state-metrics](#6-kube-state-metrics)
- [7. kubernetes-apps](#7-kubernetes-apps)
- [8. kubernetes-resources](#8-kubernetes-resources)
- [9. kubernetes-storage](#9-kubernetes-storage)
- [10. kubernetes-system](#10-kubernetes-system)
- [11. kubernetes-system-apiserver](#11-kubernetes-system-apiserver)
- [12. kubernetes-system-controller-manager](#12-kubernetes-system-controller-manager)
- [13. kubernetes-system-kube-proxy](#13-kubernetes-system-kube-proxy)
- [14. kubernetes-system-kubelet](#14-kubernetes-system-kubelet)
- [15. kubernetes-system-scheduler](#15-kubernetes-system-scheduler)
- [16. node-exporter](#16-node-exporter)
- [17. node-network](#17-node-network)
- [18. prometheus](#18-prometheus)
- [19. prometheus-operator](#19-prometheus-operator)
- [Severity 등급 요약](#severity-등급-요약)

---

## 1. alertmanager.rules

**목적**: Alertmanager 자체의 가용성과 정상 동작을 감시합니다. Alert 파이프라인이 정상적으로 동작하지 않으면 모든 알림이 유실될 수 있으므로 최우선으로 관리해야 합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `AlertmanagerFailedReload` | critical | 설정 리로드 실패 | 10m |
| `AlertmanagerMembersInconsistent` | critical | 클러스터 멤버 디스커버리 불일치 | 15m |
| `AlertmanagerFailedToSendAlerts` | warning | 특정 integration으로의 알림 전송 실패 | 5m |
| `AlertmanagerClusterFailedToSendAlerts` | critical | 클러스터 전체가 critical integration으로 전송 실패 (1%+ 실패율) | 5m |
| `AlertmanagerClusterFailedToSendAlerts` | warning | 클러스터 전체가 non-critical integration으로 전송 실패 | 5m |
| `AlertmanagerConfigInconsistent` | critical | 클러스터 내 인스턴스 간 설정 불일치 | 20m |
| `AlertmanagerClusterDown` | critical | 클러스터 인스턴스 절반 이상 다운 | 5m |
| `AlertmanagerClusterCrashlooping` | critical | 클러스터 인스턴스 절반 이상 CrashLoop | 10m |

**운영 포인트**:
- Alertmanager는 HA 구성(최소 3개 replica)이 기본이며, 클러스터 멤버 불일치 시 alert 중복/누락 발생 가능
- `AlertmanagerFailedToSendAlerts`가 발생하면 Slack/PagerDuty 등 receiver 설정을 즉시 확인

---

## 2. config-reloaders

**목적**: Prometheus Operator가 사용하는 config-reloader sidecar의 설정 동기화 실패를 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `ConfigReloaderSidecarErrors` | warning | config-reloader sidecar가 설정 리로드에 실패 | 10m |

**운영 포인트**:
- 이 alert가 발생하면 Prometheus/Alertmanager의 설정이 최신 상태가 아닌 것을 의미
- ConfigMap/Secret 변경 후 반영되지 않는 경우 이 alert를 먼저 확인
- `reloader_last_reload_successful` 메트릭을 대시보드에 추가 권장

---

## 3. etcd

**목적**: Kubernetes의 핵심 데이터 저장소인 etcd 클러스터의 건강 상태를 감시합니다. etcd 장애는 전체 클러스터 장애로 직결됩니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `etcdMembersDown` | warning | 클러스터 멤버 다운 | 3m |
| `etcdInsufficientMembers` | critical | 쿼럼(quorum) 유지 불가 위험 | 3m |
| `etcdNoLeader` | critical | 리더 없음 (클러스터 쓰기 불가) | 1m |
| `etcdHighNumberOfLeaderChanges` | warning | 15분 내 잦은 리더 변경 (불안정) | 5m |
| `etcdHighNumberOfFailedGRPCRequests` | warning | gRPC 요청 실패율 > 1% | 10m |
| `etcdHighNumberOfFailedGRPCRequests` | critical | gRPC 요청 실패율 > 5% | 5m |
| `etcdGRPCRequestsSlow` | critical | gRPC 요청 99th 백분위 > 150ms | 10m |
| `etcdMemberCommunicationSlow` | warning | 멤버 간 통신 지연 99th > 150ms | 10m |
| `etcdHighNumberOfFailedProposals` | warning | 15분 내 proposal 실패 > 5 | 15m |
| `etcdHighFsyncDurations` | warning | WAL fsync 지연 99th > 500ms | 10m |
| `etcdHighFsyncDurations` | critical | WAL fsync 지연 99th > 1s | 10m |
| `etcdHighCommitDurations` | warning | commit 지연 99th > 250ms | 10m |
| `etcdDatabaseQuotaLowSpace` | critical | DB 크기가 quota의 95% 초과 | 10m |
| `etcdExcessiveDatabaseGrowth` | warning | 4시간 내 DB quota 소진 예측 | 10m |
| `etcdDatabaseHighFragmentationRatio` | warning | DB 사용률이 할당의 50% 미만 (과도한 단편화) | 10m |

**운영 포인트**:
- `etcdNoLeader`와 `etcdInsufficientMembers`는 **최고 긴급도**로 즉시 대응 필요
- `etcdDatabaseQuotaLowSpace` 발생 시 `etcdctl defrag` 및 히스토리 compaction 검토
- managed Kubernetes(EKS/GKE/AKS) 환경에서는 etcd가 관리형이므로 이 Rule Group을 비활성화할 수 있음
- 자체 관리 클러스터에서는 etcd 전용 디스크(SSD) 및 별도 모니터링 필수

---

## 4. general.rules

**목적**: 모니터링 파이프라인의 전반적인 건강 상태를 확인하는 메타 레벨 규칙입니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `TargetDown` | warning | 특정 job/service의 타겟 10% 이상 다운 | 10m |
| `Watchdog` | none | 알림 파이프라인 정상 동작 확인용 (항상 firing) | - |
| `InfoInhibitor` | none | warning/critical 발생 시 info 등급 알림 억제 | - |

**운영 포인트**:
- **`Watchdog`는 절대 silence 처리하면 안 됨** — Alertmanager 및 notification 채널의 e2e 동작을 검증하는 핵심 alert
- PagerDuty/OpsGenie의 heartbeat 기능과 연동하여 "alert가 오지 않는 것 자체"를 감지하는 데 활용
- `TargetDown`은 ServiceMonitor 설정 오류를 빠르게 발견하는 데 유용

---

## 5. kube-apiserver-slos

**목적**: Kubernetes API Server의 SLO(Service Level Objective)를 Error Budget Burn Rate 방식으로 모니터링합니다. Google SRE 방법론의 Multi-Window, Multi-Burn-Rate 패턴을 적용합니다.

| Alert | Severity | 감시 윈도우 | 설명 |
|-------|----------|-------------|------|
| `KubeAPIErrorBudgetBurn` | critical | 1h / 5m | 에러 버짓 소진 속도 14.4x 초과 (매우 빠른 소진) |
| `KubeAPIErrorBudgetBurn` | critical | 6h / 30m | 에러 버짓 소진 속도 6.0x 초과 |
| `KubeAPIErrorBudgetBurn` | warning | 1d / 2h | 에러 버짓 소진 속도 3.0x 초과 |
| `KubeAPIErrorBudgetBurn` | warning | 3d / 6h | 에러 버짓 소진 속도 1.0x 초과 (느린 소진) |

**운영 포인트**:
- 이 alert는 단순 에러율이 아닌 **"얼마나 빠르게 SLO를 위반하고 있는가"**를 측정
- 1h/5m 윈도우의 critical은 즉시 대응이 필요한 급격한 API 품질 저하를 의미
- 3d/6h 윈도우의 warning은 천천히 누적되는 문제이므로 근무 시간 내 조사
- `apiserver_request:burnrate*` recording rule에 의존하므로 recording rule도 함께 활성화 필요

---

## 6. kube-state-metrics

**목적**: kube-state-metrics 컴포넌트 자체의 건강 상태를 감시합니다. 이 컴포넌트가 다운되면 Kubernetes 오브젝트 기반의 모든 alert가 동작하지 않습니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeStateMetricsListErrors` | critical | List 작업에서 높은 에러율 | 15m |
| `KubeStateMetricsWatchErrors` | critical | Watch 작업에서 높은 에러율 | 15m |
| `KubeStateMetricsShardingMismatch` | critical | 샤딩 설정 불일치로 메트릭 중복/누락 | 15m |
| `KubeStateMetricsShardsMissing` | critical | 샤드 누락으로 일부 K8s 오브젝트 노출 안 됨 | 15m |

**운영 포인트**:
- 모든 alert가 critical — kube-state-metrics 장애는 모니터링 블라인드 스팟을 만듬
- RBAC 권한 문제가 주요 원인이므로 ClusterRole 설정 확인
- 대규모 클러스터에서는 sharding 활성화 시 이 alert가 특히 중요

---

## 7. kubernetes-apps

**목적**: Deployment, StatefulSet, DaemonSet, Job, HPA, PDB 등 애플리케이션 워크로드 수준의 문제를 감시합니다. 운영팀에서 가장 빈번하게 접하는 alert 그룹입니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubePodCrashLooping` | warning | Pod CrashLoopBackOff 상태 | 15m |
| `KubePodNotReady` | warning | Pod가 Ready 상태가 아님 | 15m |
| `KubeDeploymentGenerationMismatch` | warning | Deployment generation 불일치 (롤아웃 실패) | 15m |
| `KubeDeploymentReplicasMismatch` | warning | Deployment 레플리카 수 불일치 | 15m |
| `KubeDeploymentRolloutStuck` | warning | Deployment 롤아웃 진행 중단 | 15m |
| `KubeStatefulSetReplicasMismatch` | warning | StatefulSet 레플리카 불일치 | 15m |
| `KubeStatefulSetGenerationMismatch` | warning | StatefulSet generation 불일치 | 15m |
| `KubeStatefulSetUpdateNotRolledOut` | warning | StatefulSet 업데이트 미완료 | 15m |
| `KubeDaemonSetRolloutStuck` | warning | DaemonSet 롤아웃 중단 | 15m |
| `KubeContainerWaiting` | warning | 컨테이너가 Waiting 상태에서 멈춤 | 1h |
| `KubeDaemonSetNotScheduled` | warning | DaemonSet Pod가 스케줄링되지 않음 | 10m |
| `KubeDaemonSetMisScheduled` | warning | DaemonSet Pod가 부적절한 노드에서 실행 중 | 15m |
| `KubeJobNotCompleted` | warning | Job이 12시간 초과 미완료 | 12h |
| `KubeJobFailed` | warning | Job 실패 | 15m |
| `KubeHpaReplicasMismatch` | warning | HPA 원하는 레플리카 수 미충족 | 15m |
| `KubeHpaMaxedOut` | warning | HPA가 최대 레플리카로 실행 중 | 15m |
| `KubePdbNotEnoughHealthyPods` | warning | PDB healthy pod 부족 | 15m |

**운영 포인트**:
- `KubePodCrashLooping`은 가장 흔한 alert — 로그 확인 및 리소스 제한/OOM 여부 점검
- `KubeHpaMaxedOut`은 트래픽 급증 또는 HPA 설정 부족을 의미하므로 용량 계획 검토
- `KubeDeploymentRolloutStuck`은 이미지 pull 실패, readiness probe 실패 등이 원인
- `KubePdbNotEnoughHealthyPods`는 노드 드레인/업그레이드 시 자주 발생

---

## 8. kubernetes-resources

**목적**: 클러스터 리소스(CPU/Memory) 오버커밋, Quota 사용률 등을 감시합니다. 용량 계획(Capacity Planning)의 핵심 지표입니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeCPUOvercommit` | warning | 클러스터 CPU request 합이 allocatable 초과 | 10m |
| `KubeMemoryOvercommit` | warning | 클러스터 Memory request 합이 allocatable 초과 | 10m |
| `KubeCPUQuotaOvercommit` | warning | Namespace CPU quota 합이 노드 할당량 초과 | 5m |
| `KubeMemoryQuotaOvercommit` | warning | Namespace Memory quota 합이 노드 할당량 초과 | 5m |
| `KubeQuotaAlmostFull` | info | Namespace quota 사용률 90~100% | 15m |
| `KubeQuotaFullyUsed` | info | Namespace quota 100% 소진 | 15m |
| `KubeQuotaExceeded` | warning | Namespace quota 초과 | 15m |
| `CPUThrottlingHigh` | info | 컨테이너 CPU throttling 25% 초과 | 15m |

**운영 포인트**:
- `KubeCPUOvercommit` / `KubeMemoryOvercommit`은 노드 장애 시 Pod 재스케줄링 실패 위험을 의미
- `CPUThrottlingHigh`는 기본 info지만, 성능 민감 워크로드에서는 severity를 상향 조정 권장
- Quota alert은 멀티테넌트 환경에서 특히 중요

---

## 9. kubernetes-storage

**목적**: PersistentVolume(PV)과 PersistentVolumeClaim(PVC)의 용량 및 상태를 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubePersistentVolumeFillingUp` | critical | PV 잔여 공간 3% 미만 | 1m |
| `KubePersistentVolumeFillingUp` | warning | 4일 내 PV 용량 소진 예측 (잔여 15% 미만) | 1h |
| `KubePersistentVolumeInodesFillingUp` | critical | PV inode 잔여 3% 미만 | 1m |
| `KubePersistentVolumeInodesFillingUp` | warning | 4일 내 PV inode 소진 예측 | 1h |
| `KubePersistentVolumeErrors` | critical | PV 상태가 Failed 또는 Pending | 5m |

**운영 포인트**:
- **데이터 유실 방지의 최후 방어선** — PV 가득 참 시 DB 장애, 로그 유실 등 치명적 결과
- `predict_linear()` 함수로 추세를 예측하는 warning 수준에서 선제 대응이 핵심
- inode 부족은 작은 파일이 대량 생성되는 워크로드(예: 로그 수집)에서 발생
- CSI 드라이버의 볼륨 확장(resize) 가능 여부를 사전에 확인

---

## 10. kubernetes-system

**목적**: Kubernetes 시스템 전반의 버전 일관성과 API 클라이언트 에러를 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeVersionMismatch` | warning | 클러스터 내 K8s 컴포넌트 버전 불일치 | 15m |
| `KubeClientErrors` | warning | API Server 클라이언트 에러율 > 1% | 15m |

**운영 포인트**:
- `KubeVersionMismatch`는 롤링 업그레이드 중 일시적으로 발생 가능 — 업그레이드 완료 후에도 지속되면 조사
- `KubeClientErrors`는 네트워크 문제 또는 RBAC 설정 오류 가능성

---

## 11. kubernetes-system-apiserver

**목적**: Kubernetes API Server의 가용성, 인증서 만료, Aggregated API 상태를 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeClientCertificateExpiration` | warning | 클라이언트 인증서 7일 내 만료 예정 | - |
| `KubeClientCertificateExpiration` | critical | 클라이언트 인증서 24시간 내 만료 예정 | - |
| `KubeAggregatedAPIErrors` | warning | Aggregated API 에러 발생 | 10m |
| `KubeAggregatedAPIDown` | warning | Aggregated API 가용성 85% 미만 | 5m |
| `KubeAPIDown` | critical | Prometheus가 API Server를 디스커버리하지 못함 | 15m |
| `KubeAPITerminatedRequests` | warning | API Server가 수신 요청의 20% 이상을 종료 | 5m |

**운영 포인트**:
- **인증서 만료 alert는 클러스터 전체 장애를 예방하는 핵심 경보**
- `KubeAPIDown`은 Prometheus 자체 네트워크 문제일 수도 있으므로 양방향 확인
- `KubeAggregatedAPIDown`은 metrics-server, custom API server 등에 영향

---

## 12. kubernetes-system-controller-manager

**목적**: kube-controller-manager의 가용성을 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeControllerManagerDown` | critical | Controller Manager가 Prometheus 타겟에서 사라짐 | 15m |

**운영 포인트**:
- Controller Manager 다운 시 ReplicaSet, Deployment, Node 등의 컨트롤러가 동작 중단
- managed K8s 환경에서는 컨트롤 플레인 메트릭 노출 설정 필요 (미노출 시 false positive 가능)

---

## 13. kubernetes-system-kube-proxy

**목적**: kube-proxy의 가용성을 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeProxyDown` | critical | kube-proxy가 Prometheus 타겟에서 사라짐 | 15m |

**운영 포인트**:
- kube-proxy 장애 시 Service 네트워킹(ClusterIP, NodePort)이 중단될 수 있음
- iptables/IPVS 모드에 따라 영향 범위가 다름
- managed K8s에서 kube-proxy 메트릭을 노출하지 않는 경우 이 Rule을 비활성화

---

## 14. kubernetes-system-kubelet

**목적**: kubelet과 노드 상태를 감시합니다. 노드 레벨의 문제를 가장 먼저 감지하는 Rule Group입니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeNodeNotReady` | warning | 노드 NotReady 상태 | 15m |
| `KubeNodePressure` | info | 노드에 Memory/Disk/PID Pressure 발생 | 10m |
| `KubeNodeUnreachable` | warning | 노드 Unreachable taint 적용됨 | 15m |
| `KubeletTooManyPods` | info | kubelet Pod 용량 95% 초과 | 15m |
| `KubeNodeReadinessFlapping` | warning | 15분 내 노드 Readiness 2회 이상 변경 | 15m |
| `KubeNodeEviction` | info | 노드에서 Pod eviction 발생 | - |
| `KubeletPlegDurationHigh` | warning | PLEG 처리 99th 백분위 > 10s | 5m |
| `KubeletPodStartUpLatencyHigh` | warning | Pod 시작 지연 99th > 60s | 15m |
| `KubeletClientCertificateExpiration` | warning | kubelet 클라이언트 인증서 7일 내 만료 | - |
| `KubeletClientCertificateExpiration` | critical | kubelet 클라이언트 인증서 24시간 내 만료 | - |
| `KubeletServerCertificateExpiration` | warning | kubelet 서버 인증서 7일 내 만료 | - |
| `KubeletServerCertificateExpiration` | critical | kubelet 서버 인증서 24시간 내 만료 | - |
| `KubeletClientCertificateRenewalErrors` | warning | 클라이언트 인증서 갱신 실패 | 15m |
| `KubeletServerCertificateRenewalErrors` | warning | 서버 인증서 갱신 실패 | 15m |
| `KubeletDown` | critical | kubelet 타겟 사라짐 | 15m |

**운영 포인트**:
- `KubeNodeNotReady`는 노드 장애의 시작점 — 즉시 `kubectl describe node` 확인
- `KubeletPlegDurationHigh`는 컨테이너 런타임(containerd) 성능 문제 가능성
- 인증서 관련 alert 4개는 **자동 갱신(auto-rotation) 설정 여부를 반드시 확인**
- `KubeNodeReadinessFlapping`은 네트워크 불안정 또는 kubelet 리소스 부족 징후

---

## 15. kubernetes-system-scheduler

**목적**: kube-scheduler의 가용성을 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `KubeSchedulerDown` | critical | Scheduler가 Prometheus 타겟에서 사라짐 | 15m |

**운영 포인트**:
- Scheduler 다운 시 새로운 Pod가 노드에 할당되지 못함
- managed K8s 환경에서는 메트릭 노출 여부에 따라 false positive 가능

---

## 16. node-exporter

**목적**: 노드(서버)의 하드웨어 및 OS 수준 리소스를 감시합니다. 디스크, 메모리, CPU, 네트워크, 파일 디스크립터, RAID, 시스템 서비스 등 인프라 기반을 포괄합니다.

### Critical

| Alert | 설명 |
|-------|------|
| `NodeFilesystemSpaceFillingUp` | 파일시스템 4시간 내 용량 소진 예측 |
| `NodeFilesystemAlmostOutOfSpace` | 파일시스템 잔여 3% 미만 |
| `NodeFilesystemFilesFillingUp` | 4시간 내 inode 소진 예측 |
| `NodeFilesystemAlmostOutOfFiles` | inode 잔여 3% 미만 |
| `NodeFileDescriptorLimit` | 파일 디스크립터 사용률 90% 초과 |
| `NodeRAIDDegraded` | RAID 어레이 디스크 장애로 degraded |

### Warning

| Alert | 설명 |
|-------|------|
| `NodeFilesystemSpaceFillingUp` | 24시간 내 파일시스템 용량 소진 예측 |
| `NodeFilesystemAlmostOutOfSpace` | 파일시스템 잔여 5% 미만 |
| `NodeFilesystemFilesFillingUp` | 24시간 내 inode 소진 예측 |
| `NodeFilesystemAlmostOutOfFiles` | inode 잔여 5% 미만 |
| `NodeNetworkReceiveErrs` | 네트워크 수신 에러 다수 발생 |
| `NodeNetworkTransmitErrs` | 네트워크 송신 에러 다수 발생 |
| `NodeHighNumberConntrackEntriesUsed` | conntrack 항목 75% 초과 사용 |
| `NodeTextFileCollectorScrapeError` | node-exporter textfile collector 실패 |
| `NodeClockSkewDetected` | 시스템 시계 50ms 이상 오차 |
| `NodeClockNotSynchronising` | 시계 동기화 실패 |
| `NodeRAIDDiskFailure` | RAID 어레이 내 디스크 장애 |
| `NodeFileDescriptorLimit` | 파일 디스크립터 사용률 70% 초과 |
| `NodeSystemSaturation` | 코어당 Load > 2.0 |
| `NodeMemoryMajorPagesFaults` | Major page fault > 500/s |
| `NodeMemoryHighUtilization` | 메모리 사용률 90% 초과 |
| `NodeDiskIOSaturation` | 디스크 I/O 큐 깊이 높음 |
| `NodeSystemdServiceFailed` | systemd 서비스 failed 상태 진입 |
| `NodeSystemdServiceCrashlooping` | systemd 서비스 과도한 재시작 |
| `NodeBondingDegraded` | 본딩 인터페이스 degraded |

### Info

| Alert | 설명 |
|-------|------|
| `NodeCPUHighUsage` | CPU 사용률 90% 초과 지속 |

**운영 포인트**:
- `NodeFilesystemSpaceFillingUp`은 **가장 빈번한 인프라 alert** — `/var/log`, `/var/lib/docker` 등 주요 파티션 모니터링
- `NodeClockSkewDetected`는 분산 시스템에서 심각한 문제를 유발 (인증서 검증 실패, 로그 순서 꼬임)
- `NodeHighNumberConntrackEntriesUsed`는 고트래픽 환경에서 연결 드롭의 원인
- `NodeMemoryHighUtilization`은 OOM Killer 발동 전 선제 감지

---

## 17. node-network

**목적**: 노드의 네트워크 인터페이스 안정성을 감시합니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `NodeNetworkInterfaceFlapping` | warning | 네트워크 인터페이스 up/down 상태 빈번 변경 | 2m |

**운영 포인트**:
- 물리 NIC, 본딩, 가상 인터페이스 등의 불안정을 조기 감지
- veth(Pod 네트워크) 인터페이스는 제외됨
- 스위치 포트 설정, 케이블 불량, 드라이버 이슈 등이 원인

---

## 18. prometheus

**목적**: Prometheus 서버 자체의 건강 상태를 감시합니다. 모니터링 시스템이 정상이어야 다른 모든 alert가 동작합니다.

| Alert | Severity | 설명 |
|-------|----------|------|
| `PrometheusBadConfig` | critical | 설정 리로드 실패 |
| `PrometheusSDRefreshFailure` | warning | Service Discovery 갱신 실패 |
| `PrometheusKubernetesListWatchFailures` | warning | K8s SD List/Watch 실패 |
| `PrometheusNotificationQueueRunningFull` | warning | 알림 큐 30분 내 가득 참 예측 |
| `PrometheusErrorSendingAlertsToSomeAlertmanagers` | warning | 일부 Alertmanager로 전송 시 1% 이상 에러 |
| `PrometheusErrorSendingAlertsToAnyAlertmanager` | critical | 모든 Alertmanager로 전송 시 3% 이상 에러 |
| `PrometheusNotConnectedToAlertmanagers` | warning | Alertmanager 연결 없음 |
| `PrometheusTSDBReloadsFailing` | warning | TSDB 블록 리로드 실패 |
| `PrometheusTSDBCompactionsFailing` | warning | TSDB compaction 실패 |
| `PrometheusNotIngestingSamples` | warning | 샘플 수집 중단 |
| `PrometheusDuplicateTimestamps` | warning | 중복 타임스탬프로 샘플 드롭 |
| `PrometheusOutOfOrderTimestamps` | warning | 순서 맞지 않는 타임스탬프로 샘플 드롭 |
| `PrometheusRemoteStorageFailures` | critical | Remote Storage 전송 실패 |
| `PrometheusRemoteWriteBehind` | critical | Remote Write 지연 |
| `PrometheusRemoteWriteDesiredShards` | warning | Remote Write shard 한도 초과 |
| `PrometheusRuleFailures` | critical | Rule 평가 실패 |
| `PrometheusMissingRuleEvaluations` | warning | Rule 평가 누락 (느린 그룹) |
| `PrometheusTargetLimitHit` | warning | 타겟 한도 초과로 드롭 |
| `PrometheusLabelLimitHit` | warning | 라벨 한도 초과로 드롭 |
| `PrometheusScrapeBodySizeLimitHit` | warning | 스크랩 바디 크기 한도 초과 |
| `PrometheusScrapeSampleLimitHit` | warning | 샘플 한도 초과로 스크랩 실패 |
| `PrometheusTargetSyncFailure` | critical | 타겟 동기화 실패 |
| `PrometheusHighQueryLoad` | warning | Query API 가용 용량 20% 미만 |

**운영 포인트**:
- `PrometheusBadConfig`와 `PrometheusRuleFailures`는 **설정 변경 후 즉시 확인**
- `PrometheusNotConnectedToAlertmanagers`가 발생하면 모든 alert가 전달되지 않음
- Remote Write 관련 alert는 Thanos/Mimir/Cortex 연동 시 필수
- `PrometheusHighQueryLoad`는 Grafana 대시보드 쿼리 최적화가 필요함을 의미

---

## 19. prometheus-operator

**목적**: Prometheus Operator 자체의 건강 상태를 감시합니다. Operator가 정상이어야 PrometheusRule, ServiceMonitor 등의 CRD 변경이 반영됩니다.

| Alert | Severity | 설명 | 기본 지속시간 |
|-------|----------|------|---------------|
| `PrometheusOperatorListErrors` | warning | List 작업 에러 | 15m |
| `PrometheusOperatorWatchErrors` | warning | Watch 작업 에러 | 15m |
| `PrometheusOperatorSyncFailed` | warning | 마지막 reconciliation 실패 | 10m |
| `PrometheusOperatorReconcileErrors` | warning | 오브젝트 reconcile 에러 | 10m |
| `PrometheusOperatorStatusUpdateErrors` | warning | 오브젝트 상태 업데이트 에러 | 10m |
| `PrometheusOperatorNodeLookupErrors` | warning | 노드 조회 에러 | 10m |
| `PrometheusOperatorNotReady` | warning | Operator가 Ready 상태가 아님 | 5m |
| `PrometheusOperatorRejectedResources` | warning | 모니터링 리소스를 거부함 | 15m |

**운영 포인트**:
- `PrometheusOperatorRejectedResources`는 PrometheusRule/ServiceMonitor YAML 문법 오류 가능성
- Operator 업그레이드 후 CRD 호환성 문제로 alert 발생 가능

---

## Severity 등급 요약

| 등급 | 의미 | 대응 시간 | 예시 |
|------|------|-----------|------|
| **critical** | 즉시 대응 필요, 서비스 영향 중 | 5~15분 내 | `KubeAPIDown`, `etcdNoLeader`, `KubeletDown` |
| **warning** | 빠른 조사 필요, 잠재적 서비스 영향 | 업무 시간 내 | `KubePodCrashLooping`, `NodeMemoryHighUtilization` |
| **info** | 인지 필요, 즉각 대응 불필요 | 다음 점검 시 | `CPUThrottlingHigh`, `KubeNodePressure` |
| **none** | 시스템 내부용 (silence 불가) | - | `Watchdog`, `InfoInhibitor` |

---

## Rule 활성화/비활성화

`values.yaml`에서 개별 Rule을 제어할 수 있습니다:

```yaml
defaultRules:
  create: true
  rules:
    alertmanager: true
    configReloaders: true
    etcd: true              # managed K8s에서는 false 가능
    general: true
    kubeApiserver: true
    kubeApiserverSlos: true
    kubeStateMetrics: true
    kubelet: true
    kubernetesApps: true
    kubernetesResources: true
    kubernetesStorage: true
    kubernetesSystem: true
    network: true
    node: true
    nodeExporterAlerting: true
    prometheus: true
    prometheusOperator: true
  # 개별 alert 비활성화
  disabled:
    KubeProxyDown: true       # managed K8s에서 메트릭 미노출 시
    KubeSchedulerDown: true   # managed K8s에서 메트릭 미노출 시
    KubeControllerManagerDown: true  # managed K8s에서 메트릭 미노출 시
```

---

## 참고

- [kube-prometheus-stack rules 디렉토리](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack/templates/prometheus/rules-1.14)
- [Prometheus Alerting Rules 공식 문서](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
