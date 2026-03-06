# Production 추가 권장 Alerting Rules

> kube-prometheus-stack 기본 Rule로 커버되지 않는 영역에 대한 추가 검토 가이드

---

## 목차

- [개요](#개요)
- [1. CoreDNS](#1-coredns)
- [2. Ingress Controller (NGINX)](#2-ingress-controller-nginx)
- [3. cert-manager (인증서 관리)](#3-cert-manager-인증서-관리)
- [4. ArgoCD (GitOps)](#4-argocd-gitops)
- [5. Velero (백업/복구)](#5-velero-백업복구)
- [6. Container Runtime / CRI](#6-container-runtime--cri)
- [7. Network Policy / CNI](#7-network-policy--cni)
- [8. Pod 보안 및 이상 탐지](#8-pod-보안-및-이상-탐지)
- [9. 클러스터 용량 계획](#9-클러스터-용량-계획)
- [10. Namespace / Multi-Tenancy](#10-namespace--multi-tenancy)
- [추가 Rule 적용 우선순위 매트릭스](#추가-rule-적용-우선순위-매트릭스)
- [Helm values.yaml 통합 가이드](#helm-valuesyaml-통합-가이드)

---

## 개요

kube-prometheus-stack의 기본 Rule은 Kubernetes 코어 컴포넌트와 인프라 수준의 모니터링을 잘 커버하지만, 실제 Production 운영에서는 다음 영역에 대한 추가 모니터링이 필수적입니다:

```
┌─────────────────────────────────────────────────────────────┐
│                    Production Alert 계층                      │
├─────────────────────────────────────────────────────────────┤
│  [L4] 애플리케이션 레벨    │ 비즈니스 메트릭, SLI/SLO        │
│  [L3] 플랫폼 서비스 레벨   │ Ingress, DNS, 인증서, GitOps   │  ← 이 문서
│  [L2] K8s 워크로드 레벨    │ Pod, Deployment, Storage       │  ← 기본 Rule
│  [L1] 인프라/노드 레벨     │ Node, kubelet, etcd            │  ← 기본 Rule
└─────────────────────────────────────────────────────────────┘
```

이 문서는 **L3 플랫폼 서비스 레벨**을 중심으로 추가 Rule을 제안합니다.

---

## 1. CoreDNS

**왜 중요한가**: CoreDNS는 클러스터 내 모든 서비스 디스커버리의 핵심입니다. CoreDNS 장애 시 Pod 간 통신, 외부 서비스 호출이 전부 실패합니다.

**필요 조건**: kube-prometheus-stack에서 `coreDns.enabled: true` (기본 활성화)

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: coredns-custom-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: coredns.custom.rules
      rules:
        # CoreDNS Pod 다운
        - alert: CoreDNSDown
          expr: |
            absent(up{job="kube-dns"} == 1)
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "CoreDNS가 다운되었습니다"
            description: "CoreDNS Pod가 5분 이상 응답하지 않습니다. 클러스터 내 DNS 해석이 불가능합니다."
            runbook_url: "https://runbooks.example.com/coredns-down"

        # DNS 응답 지연 (99th percentile > 1s)
        - alert: CoreDNSLatencyHigh
          expr: |
            histogram_quantile(0.99,
              sum(rate(coredns_dns_request_duration_seconds_bucket{job="kube-dns"}[5m])) by (le, server)
            ) > 1
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "CoreDNS 응답 지연이 높습니다"
            description: "CoreDNS 99th 백분위 응답 시간이 1초를 초과합니다. Pod 통신에 지연이 발생할 수 있습니다."

        # SERVFAIL 응답 비율 높음
        - alert: CoreDNSErrorsHigh
          expr: |
            sum(rate(coredns_dns_responses_total{job="kube-dns", rcode="SERVFAIL"}[5m]))
            /
            sum(rate(coredns_dns_responses_total{job="kube-dns"}[5m]))
            > 0.03
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "CoreDNS SERVFAIL 비율이 3%를 초과합니다"
            description: "DNS 질의의 3% 이상이 SERVFAIL로 응답하고 있습니다. upstream DNS 또는 네트워크 문제를 확인하세요."

        # CoreDNS Panic 발생
        - alert: CoreDNSPanicsDetected
          expr: |
            increase(coredns_panics_total{job="kube-dns"}[10m]) > 0
          for: 0m
          labels:
            severity: critical
          annotations:
            summary: "CoreDNS에서 panic이 발생했습니다"
            description: "CoreDNS에서 panic이 감지되었습니다. Pod 로그를 즉시 확인하세요."

        # Forward 플러그인 에러 (외부 DNS 전달 실패)
        - alert: CoreDNSForwardHealthcheckFailures
          expr: |
            sum(rate(coredns_forward_healthcheck_failures_total{job="kube-dns"}[5m])) by (to) > 0
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "CoreDNS forward 헬스체크 실패"
            description: "CoreDNS가 upstream DNS 서버({{ $labels.to }})로의 헬스체크에 실패하고 있습니다."
```

**참고**: [CoreDNS Prometheus 메트릭 문서](https://coredns.io/plugins/metrics/) | [coredns-mixin](https://github.com/povilasv/coredns-mixin)

---

## 2. Ingress Controller (NGINX)

**왜 중요한가**: 클러스터 외부 트래픽의 진입점입니다. Ingress 장애는 곧 서비스 전체 장애입니다.

**필요 조건**: ingress-nginx의 `controller.metrics.enabled: true`, `controller.metrics.serviceMonitor.enabled: true`

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ingress-nginx-custom-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: ingress-nginx.custom.rules
      rules:
        # NGINX Ingress Controller 다운
        - alert: NginxIngressControllerDown
          expr: |
            absent(up{job="ingress-nginx-controller-metrics"} == 1)
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "NGINX Ingress Controller가 다운되었습니다"
            description: "외부에서 클러스터 서비스로의 접근이 불가능할 수 있습니다."

        # 5xx 에러율 높음
        - alert: NginxIngress5xxRateHigh
          expr: |
            sum(rate(nginx_ingress_controller_requests{status=~"5.."}[5m])) by (ingress, namespace)
            /
            sum(rate(nginx_ingress_controller_requests[5m])) by (ingress, namespace)
            > 0.05
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Ingress {{ $labels.namespace }}/{{ $labels.ingress }}의 5xx 에러율이 5%를 초과"
            description: "백엔드 서비스 장애 또는 설정 오류를 확인하세요."

        # 요청 지연 높음 (P95 > 5s)
        - alert: NginxIngressLatencyHigh
          expr: |
            histogram_quantile(0.95,
              sum(rate(nginx_ingress_controller_request_duration_seconds_bucket[5m])) by (le, ingress, namespace)
            ) > 5
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Ingress {{ $labels.namespace }}/{{ $labels.ingress }} P95 지연 5초 초과"
            description: "백엔드 응답 시간 또는 Ingress 자체 처리 시간을 확인하세요."

        # Ingress 설정 리로드 실패
        - alert: NginxIngressConfigReloadFailed
          expr: |
            nginx_ingress_controller_config_last_reload_successful == 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "NGINX Ingress 설정 리로드 실패"
            description: "최근 설정 변경이 반영되지 않았습니다. Ingress 리소스 문법 오류를 확인하세요."

        # SSL 인증서 만료 임박
        - alert: NginxIngressSSLCertExpiringSoon
          expr: |
            (nginx_ingress_controller_ssl_expire_time_seconds - time()) / 86400 < 7
          for: 1h
          labels:
            severity: warning
          annotations:
            summary: "Ingress SSL 인증서 7일 내 만료 예정"
            description: "호스트 {{ $labels.host }}의 인증서가 {{ $value | humanizeDuration }} 후 만료됩니다."

        # 연결 수 급증 감지
        - alert: NginxIngressConnectionSpike
          expr: |
            sum(nginx_ingress_controller_nginx_process_connections) > 10000
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "NGINX Ingress 활성 연결 수 10,000 초과"
            description: "트래픽 급증 또는 slowloris 공격 가능성을 확인하세요."
```

**참고**: [NGINX Ingress 모니터링 가이드](https://www.aviator.co/blog/how-to-monitor-and-alert-on-nginx-ingress-in-kubernetes/)

---

## 3. cert-manager (인증서 관리)

**왜 중요한가**: TLS 인증서 자동 발급/갱신이 실패하면 HTTPS 서비스가 중단됩니다. 인증서 만료는 전체 서비스 장애를 초래할 수 있습니다.

**필요 조건**: cert-manager의 Prometheus 메트릭 노출 활성화 (`prometheus.servicemonitor.enabled: true`)

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-custom-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: cert-manager.custom.rules
      rules:
        # cert-manager 컨트롤러 다운
        - alert: CertManagerDown
          expr: |
            absent(up{job="cert-manager"} == 1)
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "cert-manager가 다운되었습니다"
            description: "인증서 자동 갱신이 중단되었습니다. 인증서 만료 위험이 있습니다."

        # Certificate 리소스 Not Ready
        - alert: CertManagerCertificateNotReady
          expr: |
            certmanager_certificate_ready_status{condition="True"} == 0
          for: 15m
          labels:
            severity: critical
          annotations:
            summary: "인증서 {{ $labels.namespace }}/{{ $labels.name }}이 Ready가 아닙니다"
            description: "인증서 발급 또는 갱신에 실패했습니다. `kubectl describe certificate`로 상태를 확인하세요."

        # 인증서 30일 내 만료
        - alert: CertManagerCertificateExpiring30d
          expr: |
            (certmanager_certificate_expiration_timestamp_seconds - time()) / 86400 < 30
          for: 1h
          labels:
            severity: info
          annotations:
            summary: "인증서 {{ $labels.namespace }}/{{ $labels.name }} 30일 내 만료"
            description: "{{ $value | printf \"%.0f\" }}일 후 만료됩니다. cert-manager 자동 갱신 상태를 확인하세요."

        # 인증서 7일 내 만료
        - alert: CertManagerCertificateExpiring7d
          expr: |
            (certmanager_certificate_expiration_timestamp_seconds - time()) / 86400 < 7
          for: 1h
          labels:
            severity: warning
          annotations:
            summary: "인증서 {{ $labels.namespace }}/{{ $labels.name }} 7일 내 만료"
            description: "자동 갱신이 실패한 것으로 보입니다. 즉시 수동 조치가 필요합니다."

        # 인증서 1일 내 만료
        - alert: CertManagerCertificateExpiring1d
          expr: |
            (certmanager_certificate_expiration_timestamp_seconds - time()) / 86400 < 1
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "인증서 {{ $labels.namespace }}/{{ $labels.name }} 24시간 내 만료"
            description: "긴급 수동 인증서 갱신이 필요합니다."

        # ACME 주문 실패
        - alert: CertManagerACMEOrderFailed
          expr: |
            increase(certmanager_http_acme_client_request_count{status="error"}[1h]) > 5
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "cert-manager ACME 요청 실패 다수 발생"
            description: "Let's Encrypt 등 ACME 서버와의 통신에 문제가 있습니다."
```

**참고**: [cert-manager Prometheus 메트릭 문서](https://cert-manager.io/docs/devops-tips/prometheus-metrics/) | [cert-manager alert 예시](https://gist.github.com/PhilipSchmid/33fb3ebe77a473a97591a5bab33a2b10)

---

## 4. ArgoCD (GitOps)

**왜 중요한가**: GitOps 기반 배포 파이프라인의 핵심입니다. ArgoCD 장애 시 배포/롤백이 불가능해집니다.

**필요 조건**: ArgoCD의 `server.metrics.enabled: true`, `controller.metrics.enabled: true`

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: argocd-custom-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: argocd.custom.rules
      rules:
        # ArgoCD Application Sync 실패
        - alert: ArgoCDAppSyncFailed
          expr: |
            argocd_app_info{sync_status="OutOfSync"} == 1
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "ArgoCD App {{ $labels.name }}이 OutOfSync 상태"
            description: "30분 이상 Git 소스와 동기화되지 않고 있습니다."

        # ArgoCD Application Health 비정상
        - alert: ArgoCDAppUnhealthy
          expr: |
            argocd_app_info{health_status!~"Healthy|Progressing"} == 1
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "ArgoCD App {{ $labels.name }} 헬스 상태 비정상 ({{ $labels.health_status }})"
            description: "애플리케이션 상태가 Degraded/Missing/Unknown입니다."

        # ArgoCD Server 다운
        - alert: ArgoCDServerDown
          expr: |
            absent(up{job="argocd-server-metrics"} == 1)
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "ArgoCD Server가 다운되었습니다"
            description: "ArgoCD UI 및 API에 접근할 수 없습니다."

        # ArgoCD Controller Sync 오류 누적
        - alert: ArgoCDSyncErrorsHigh
          expr: |
            sum(increase(argocd_app_sync_total{phase!="Succeeded"}[1h])) > 5
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "ArgoCD Sync 실패가 1시간 내 5회 이상"
            description: "반복적인 sync 실패는 매니페스트 오류 또는 클러스터 권한 문제를 의미합니다."

        # ArgoCD Repo Server 응답 지연
        - alert: ArgoCDRepoServerLatencyHigh
          expr: |
            histogram_quantile(0.95,
              sum(rate(argocd_git_request_duration_seconds_bucket[5m])) by (le)
            ) > 10
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "ArgoCD Repo Server Git 요청 P95 지연 10초 초과"
            description: "Git 리포지토리 접근이 느립니다. 네트워크 또는 리포 크기를 확인하세요."
```

---

## 5. Velero (백업/복구)

**왜 중요한가**: 클러스터 및 워크로드 백업/복구 도구입니다. 백업이 실패하면 재해 복구(DR)가 불가능합니다.

**필요 조건**: Velero의 `metrics.enabled: true`, `metrics.serviceMonitor.enabled: true`

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: velero-custom-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: velero.custom.rules
      rules:
        # 백업 실패
        - alert: VeleroBackupFailed
          expr: |
            increase(velero_backup_failure_total[24h]) > 0
          for: 1h
          labels:
            severity: critical
          annotations:
            summary: "Velero 백업이 실패했습니다"
            description: "지난 24시간 내 백업 실패가 발생했습니다. `velero backup get`으로 상태를 확인하세요."

        # 백업이 오래 전 마지막 성공
        - alert: VeleroBackupNotRunRecently
          expr: |
            time() - velero_backup_last_successful_timestamp > 86400 * 2
          for: 1h
          labels:
            severity: warning
          annotations:
            summary: "Velero 백업이 2일 이상 성공하지 못했습니다"
            description: "스케줄된 백업이 정상적으로 동작하는지 확인하세요."

        # 백업 일부 실패 (partial failure)
        - alert: VeleroBackupPartialFailure
          expr: |
            increase(velero_backup_partial_failure_total[24h]) > 0
          for: 1h
          labels:
            severity: warning
          annotations:
            summary: "Velero 백업이 부분적으로 실패했습니다"
            description: "일부 리소스가 백업에서 누락되었습니다."

        # 복구 실패
        - alert: VeleroRestoreFailed
          expr: |
            increase(velero_restore_failure_total[24h]) > 0
          for: 15m
          labels:
            severity: critical
          annotations:
            summary: "Velero 복구가 실패했습니다"
            description: "복구 작업이 실패했습니다. `velero restore get`으로 상태를 확인하세요."

        # Velero 서버 다운
        - alert: VeleroServerDown
          expr: |
            absent(up{job="velero"} == 1)
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Velero 서버가 다운되었습니다"
            description: "백업/복구 스케줄이 실행되지 않습니다."
```

---

## 6. Container Runtime / CRI

**왜 중요한가**: containerd/CRI-O 등 컨테이너 런타임의 문제는 Pod 생성/시작 실패로 직결됩니다.

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: container-runtime-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: container-runtime.rules
      rules:
        # 컨테이너 OOMKilled 빈번 발생
        - alert: ContainerOOMKilledFrequent
          expr: |
            sum(increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[1h])) by (namespace, pod, container) > 2
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "{{ $labels.namespace }}/{{ $labels.pod }}/{{ $labels.container }}에서 OOMKilled 빈번 발생"
            description: "1시간 내 2회 이상 OOMKilled. 메모리 limits 조정이 필요합니다."

        # 이미지 Pull 실패 지속
        - alert: ContainerImagePullBackOff
          expr: |
            sum(kube_pod_container_status_waiting_reason{reason="ImagePullBackOff"}) by (namespace, pod) > 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "{{ $labels.namespace }}/{{ $labels.pod }} 이미지 Pull 실패"
            description: "컨테이너 이미지를 가져올 수 없습니다. 이미지 경로, 태그, Registry 인증 정보를 확인하세요."

        # CreateContainerError 지속
        - alert: ContainerCreateError
          expr: |
            sum(kube_pod_container_status_waiting_reason{reason="CreateContainerError"}) by (namespace, pod) > 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "{{ $labels.namespace }}/{{ $labels.pod }} 컨테이너 생성 실패"
            description: "볼륨 마운트, 보안 컨텍스트, ConfigMap/Secret 누락 등을 확인하세요."
```

---

## 7. Network Policy / CNI

**왜 중요한가**: CNI(Calico, Cilium 등) 장애는 Pod 네트워킹 전체에 영향을 미칩니다.

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: network-cni-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: network-cni.rules
      rules:
        # Pod IP 할당 실패 (IPAM 소진)
        - alert: PodIPAllocationFailure
          expr: |
            sum(kube_pod_status_phase{phase="Pending"}) by (namespace) > 10
            and
            sum(kube_pod_status_reason{reason="FailedCreatePodSandBox"}) by (namespace) > 0
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "Pod IP 할당 실패 의심 (네임스페이스: {{ $labels.namespace }})"
            description: "IPAM 풀 소진 또는 CNI 플러그인 장애를 확인하세요."

        # kube-proxy iptables sync 실패 (기본 Rule에 없는 세부 항목)
        - alert: KubeProxySyncFailures
          expr: |
            increase(kubeproxy_sync_proxy_rules_iptables_total{result="failure"}[15m]) > 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "kube-proxy iptables 동기화 실패"
            description: "Service 라우팅이 정상적으로 업데이트되지 않을 수 있습니다."
```

---

## 8. Pod 보안 및 이상 탐지

**왜 중요한가**: 비정상적인 Pod 동작은 보안 사고나 설정 오류의 신호일 수 있습니다.

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: pod-security-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: pod-security.rules
      rules:
        # 네임스페이스에 과도한 Pod 재시작
        - alert: NamespaceHighRestartRate
          expr: |
            sum(increase(kube_pod_container_status_restarts_total[1h])) by (namespace) > 20
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "네임스페이스 {{ $labels.namespace }}에서 Pod 재시작이 과도하게 발생"
            description: "1시간 내 20회 이상의 컨테이너 재시작. 리소스 부족이나 애플리케이션 오류를 확인하세요."

        # 특권(Privileged) 컨테이너 실행 감지
        - alert: PrivilegedContainerRunning
          expr: |
            kube_pod_spec_containers_privileged == 1
          for: 5m
          labels:
            severity: info
          annotations:
            summary: "{{ $labels.namespace }}/{{ $labels.pod }}에서 특권 컨테이너 실행 중"
            description: "보안 정책에 따라 특권 컨테이너 사용이 정당한지 검토하세요."

        # Failed Pod 누적
        - alert: PodFailedAccumulation
          expr: |
            sum(kube_pod_status_phase{phase="Failed"}) by (namespace) > 5
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "네임스페이스 {{ $labels.namespace }}에 Failed Pod가 5개 이상"
            description: "Failed 상태의 Pod를 정리하고 원인을 조사하세요."
```

---

## 9. 클러스터 용량 계획

**왜 중요한가**: 기본 Rule의 리소스 오버커밋 alert를 보완하여 보다 세밀한 용량 관리를 지원합니다.

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: capacity-planning-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: capacity-planning.rules
      rules:
        # 클러스터 노드 수 부족 (Pending Pod 지속)
        - alert: ClusterPendingPodsHigh
          expr: |
            sum(kube_pod_status_phase{phase="Pending"}) > 10
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "클러스터에 Pending Pod가 10개 이상"
            description: "리소스 부족으로 스케줄링 대기 중인 Pod가 많습니다. 노드 추가를 검토하세요."

        # 노드 Allocatable 메모리 80% 이상 사용
        - alert: NodeAllocatableMemoryHigh
          expr: |
            sum(container_memory_working_set_bytes{image!=""}) by (node)
            /
            sum(kube_node_status_allocatable{resource="memory"}) by (node)
            > 0.85
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "노드 {{ $labels.node }}의 allocatable 메모리 85% 초과 사용"
            description: "Pod 추가 배치가 어려울 수 있습니다."

        # Cluster Autoscaler 스케일업 실패 (CA 사용 시)
        - alert: ClusterAutoscalerScaleUpFailed
          expr: |
            increase(cluster_autoscaler_failed_scale_ups_total[1h]) > 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Cluster Autoscaler 스케일업 실패"
            description: "노드 그룹 제한, 클라우드 API 오류, 또는 인스턴스 타입 가용성을 확인하세요."

        # Cluster Autoscaler Unschedulable Pod 존재
        - alert: ClusterAutoscalerUnschedulablePods
          expr: |
            cluster_autoscaler_unschedulable_pods_count > 0
          for: 30m
          labels:
            severity: warning
          annotations:
            summary: "스케줄 불가능한 Pod가 30분 이상 존재"
            description: "Autoscaler가 처리하지 못하는 Pod가 있습니다. nodeSelector, affinity, taint 설정을 확인하세요."
```

---

## 10. Namespace / Multi-Tenancy

**왜 중요한가**: 멀티테넌트 환경에서 네임스페이스 단위의 리소스 격리 및 모니터링이 필요합니다.

### 권장 Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: namespace-governance-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: namespace-governance.rules
      rules:
        # ResourceQuota 미설정 네임스페이스 (사용자 네임스페이스)
        - alert: NamespaceMissingResourceQuota
          expr: |
            count by (namespace) (kube_namespace_labels)
            unless
            count by (namespace) (kube_resourcequota)
          for: 1h
          labels:
            severity: info
          annotations:
            summary: "네임스페이스 {{ $labels.namespace }}에 ResourceQuota가 없습니다"
            description: "멀티테넌트 환경에서는 모든 네임스페이스에 ResourceQuota 설정을 권장합니다."

        # LimitRange 미설정 네임스페이스
        - alert: NamespaceMissingLimitRange
          expr: |
            count by (namespace) (kube_namespace_labels)
            unless
            count by (namespace) (kube_limitrange)
          for: 1h
          labels:
            severity: info
          annotations:
            summary: "네임스페이스 {{ $labels.namespace }}에 LimitRange가 없습니다"
            description: "기본 리소스 제한이 없으면 단일 Pod가 노드 리소스를 독점할 수 있습니다."
```

---

## 추가 Rule 적용 우선순위 매트릭스

Production 환경의 성숙도와 인프라 구성에 따라 단계적으로 적용하세요.

### Phase 1: 필수 (Day-1)

| 카테고리 | 이유 | 비고 |
|----------|------|------|
| CoreDNS | 클러스터 네트워킹의 근본 | 기본 ServiceMonitor는 있으나 alert가 미약 |
| cert-manager | 인증서 만료 = 서비스 장애 | Let's Encrypt 자동 갱신 실패 시 HTTPS 중단 |
| Container Runtime | OOMKilled, ImagePullBackOff | 가장 빈번한 Pod 문제 |

### Phase 2: 권장 (Day-7)

| 카테고리 | 이유 | 비고 |
|----------|------|------|
| Ingress NGINX | 외부 트래픽 진입점 | 5xx 모니터링, SSL 만료 체크 |
| Velero | DR 불가 사전 방지 | 백업 실패 시 복구 불능 |
| 용량 계획 | Pending Pod 사전 감지 | Autoscaler 환경에서 특히 중요 |

### Phase 3: 강화 (Day-30)

| 카테고리 | 이유 | 비고 |
|----------|------|------|
| ArgoCD | GitOps 배포 파이프라인 안정성 | OutOfSync 장기 방치 방지 |
| Network/CNI | 네트워크 장애 심층 감지 | CNI 종류에 따라 메트릭이 다름 |
| Pod 보안 | 이상 징후 조기 감지 | 특권 컨테이너, 과도한 재시작 |
| Namespace 거버넌스 | 멀티테넌트 운영 성숙도 | Quota/LimitRange 미설정 감지 |

---

## Helm values.yaml 통합 가이드

kube-prometheus-stack에서 커스텀 Rule을 추가하는 두 가지 방법:

### 방법 1: additionalPrometheusRulesMap (권장)

`values.yaml` 내에 직접 정의합니다.

```yaml
additionalPrometheusRulesMap:
  custom-coredns-rules:
    groups:
      - name: coredns.custom.rules
        rules:
          - alert: CoreDNSDown
            expr: absent(up{job="kube-dns"} == 1)
            for: 5m
            labels:
              severity: critical
            annotations:
              summary: "CoreDNS가 다운되었습니다"
  custom-cert-manager-rules:
    groups:
      - name: cert-manager.custom.rules
        rules:
          - alert: CertManagerCertificateNotReady
            expr: certmanager_certificate_ready_status{condition="True"} == 0
            for: 15m
            labels:
              severity: critical
            annotations:
              summary: "인증서 Not Ready"
```

### 방법 2: 별도 PrometheusRule 리소스 배포

별도 Helm Chart 또는 Kustomize로 PrometheusRule 매니페스트를 관리합니다.

```yaml
# kustomization.yaml
resources:
  - rules/coredns-custom-alerts.yaml
  - rules/cert-manager-custom-alerts.yaml
  - rules/ingress-nginx-custom-alerts.yaml
  - rules/velero-custom-alerts.yaml
  - rules/argocd-custom-alerts.yaml
```

> PrometheusRule에 `release: kube-prometheus-stack` 라벨이 있어야 Prometheus Operator가 해당 Rule을 인식합니다. `ruleSelector` 설정에 따라 다를 수 있으므로 Prometheus CR의 `spec.ruleSelector`를 확인하세요.

---

## 참고 자료

- [Awesome Prometheus Alerts](https://samber.github.io/awesome-prometheus-alerts/rules.html)
- [cert-manager Prometheus 메트릭](https://cert-manager.io/docs/devops-tips/prometheus-metrics/)
- [CoreDNS 메트릭 플러그인](https://coredns.io/plugins/metrics/)
- [coredns-mixin (Prometheus Alerts)](https://github.com/povilasv/coredns-mixin)
- [NGINX Ingress 모니터링](https://www.aviator.co/blog/how-to-monitor-and-alert-on-nginx-ingress-in-kubernetes/)
- [Azure AKS CoreDNS PrometheusRule 예시](https://github.com/Azure/AKS/blob/master/examples/kube-prometheus/coredns-prometheusRule.yaml)
- [Kubernetes 모니터링 Best Practices](https://trilio.io/kubernetes-best-practices/kubernetes-monitoring-best-practices/)
