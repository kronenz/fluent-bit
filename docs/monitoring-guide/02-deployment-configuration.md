# Section 2: 모니터링 모듈 배포 구성

## 목차

- [2.1 전제 조건 및 도구 버전](#21-전제-조건-및-도구-버전)
- [2.2 GitOps 저장소 디렉토리 구조](#22-gitops-저장소-디렉토리-구조)
- [2.3 Helm Chart 구성](#23-helm-chart-구성)
- [2.4 Kustomize 구성 전략](#24-kustomize-구성-전략)
- [2.5 ArgoCD App of Apps 구성](#25-argocd-app-of-apps-구성)
- [2.6 사전 리소스 준비 체크리스트](#26-사전-리소스-준비-체크리스트)

---

## 2.1 전제 조건 및 도구 버전

### 2.1.1 CLI 도구 버전 요구사항

| 도구 | 최소 버전 | 권장 버전 | 설치 확인 명령어 | 비고 |
|------|-----------|-----------|-----------------|------|
| `kubectl` | 1.28 | 1.29 | `kubectl version --client` | 클러스터 API 버전과 ±1 범위 |
| `kustomize` | 5.0 | 5.3 | `kustomize version` | kubectl 내장 버전과 별도 설치 구분 |
| `helm` | 3.12 | 3.14 | `helm version` | OCI 레지스트리 지원 필수 |
| `argocd` CLI | 2.8 | 2.10 | `argocd version --client` | ArgoCD 서버 버전과 일치 권장 |
| `jq` | 1.6 | 1.7 | `jq --version` | 스크립트 JSON 파싱용 |
| `yq` | 4.30 | 4.40 | `yq --version` | YAML 인라인 편집용 |
| `curl` | 7.68 | 8.x | `curl --version` | Nexus / API 헬스체크용 |

### 2.1.2 필요 권한 요구사항

| 도구 | 필요 권한 | 확인 명령어 | 비고 |
|------|-----------|-------------|------|
| `kubectl` | `cluster-admin` 또는 커스텀 ClusterRole | `kubectl auth can-i '*' '*' --all-namespaces` | 네임스페이스 생성 / CRD 설치 포함 |
| `helm` | 대상 네임스페이스 `admin` | `kubectl auth can-i create deployments -n monitoring` | Tiller 없는 Helm 3 기준 |
| `argocd` CLI | ArgoCD `admin` 역할 | `argocd account get-user-info` | App / Project 생성 권한 |
| Nexus (Helm) | `nx-repository-view-helm-*-read` | Nexus UI → 계정 → 역할 확인 | Chart pull 전용 |
| Nexus (OCI) | `nx-repository-view-docker-*-read` | `docker login <nexus-host>` | 컨테이너 이미지 pull |
| Bitbucket | 저장소 `READ` + Webhook `WRITE` | Bitbucket → Personal Access Token 권한 탭 | ArgoCD repo 등록용 |
| OpenSearch | `all_access` 역할 (초기 설정 시) | `curl -u admin https://<os-host>/_cat/health` | ISM 정책 / 인덱스 템플릿 등록 시 필요 |

---

## 2.2 GitOps 저장소 디렉토리 구조

세 개의 Bitbucket 저장소로 역할을 분리한다. 각 저장소의 목적과 전체 디렉토리 구조는 아래와 같다.

```
monitoring-gitops/                        # ArgoCD Application 정의 저장소
├── apps/
│   ├── root-app.yaml                     # App of Apps 진입점 (wave 0)
│   └── prod/
│       ├── prometheus-app.yaml           # kube-prometheus-stack Application
│       ├── fluent-operator-app.yaml      # Fluent Bit Operator Application
│       ├── opensearch-app.yaml           # OpenSearch Application
│       └── k8salert-app.yaml             # k8sAlert Application
├── projects/
│   ├── monitoring-project.yaml           # ArgoCD AppProject (monitoring 네임스페이스)
│   └── logging-project.yaml              # ArgoCD AppProject (logging 네임스페이스)
└── clusters/
    ├── dev/
    │   └── apps/                         # dev 환경 Application 오버라이드
    ├── staging/
    │   └── apps/
    └── prod/
        └── apps/

monitoring-helm-values/                   # Helm values 파일 저장소
├── kube-prometheus-stack/
│   ├── values-base.yaml                  # 공통 기본값 (모든 환경 상속)
│   ├── values-dev.yaml                   # dev 환경 오버라이드
│   ├── values-staging.yaml               # staging 환경 오버라이드
│   └── values-prod.yaml                  # prod 환경 오버라이드 (리소스 최대)
├── fluent-operator/
│   ├── values-base.yaml
│   ├── values-dev.yaml
│   ├── values-staging.yaml
│   └── values-prod.yaml
├── opensearch/
│   ├── values-base.yaml
│   ├── values-dev.yaml
│   ├── values-staging.yaml
│   └── values-prod.yaml
└── k8salert/
    ├── values-base.yaml
    ├── values-dev.yaml
    ├── values-staging.yaml
    └── values-prod.yaml

monitoring-kustomize/                     # Kustomize 리소스 저장소
├── base/
│   ├── kustomization.yaml
│   ├── namespaces/
│   │   ├── monitoring.yaml
│   │   └── logging.yaml
│   ├── service-monitors/
│   │   ├── kustomization.yaml
│   │   ├── node-exporter-sm.yaml
│   │   ├── kube-state-metrics-sm.yaml
│   │   ├── fluent-bit-sm.yaml
│   │   ├── opensearch-sm.yaml
│   │   └── k8salert-sm.yaml
│   ├── prometheus-rules/
│   │   ├── kustomization.yaml
│   │   ├── node-rules.yaml               # 노드 자원 알람
│   │   ├── pod-rules.yaml                # Pod 상태 알람
│   │   ├── fluent-bit-rules.yaml         # 로그 파이프라인 알람
│   │   └── opensearch-rules.yaml         # OpenSearch 클러스터 알람
│   ├── fluent-bit-configs/
│   │   ├── kustomization.yaml
│   │   ├── cluster-input/
│   │   │   ├── systemd-input.yaml
│   │   │   └── tail-input.yaml
│   │   ├── filter/
│   │   │   ├── kubernetes-filter.yaml
│   │   │   ├── modify-filter.yaml
│   │   │   └── throttle-filter.yaml
│   │   └── output/
│   │       ├── opensearch-output.yaml
│   │       └── stdout-output.yaml        # 디버그용
│   └── opensearch-ism/
│       ├── kustomization.yaml
│       ├── hot-warm-delete-policy.yaml
│       └── index-template.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml
    │   ├── patches/
    │   │   ├── prometheus-storage-patch.yaml
    │   │   └── fluent-bit-resources-patch.yaml
    │   └── configmaps/
    ├── staging/
    │   ├── kustomization.yaml
    │   └── patches/
    └── prod/
        ├── kustomization.yaml
        ├── patches/
        │   ├── prometheus-storage-patch.yaml   # NVMe 4TB PV 참조
        │   ├── opensearch-hot-patch.yaml       # Hot 노드 리소스 증설
        │   └── alertmanager-patch.yaml
        └── secrets/
            └── kustomize-secret-ref.yaml       # External Secret 참조
```

---

## 2.3 Helm Chart 구성

### 2.3.1 사용 Chart 목록

| Chart 명 | Chart 버전 | 앱 버전 | 원본 출처 (upstream) | Nexus 경로 | 설치 네임스페이스 |
|----------|-----------|---------|---------------------|-----------|-----------------|
| `kube-prometheus-stack` | 58.x | Prometheus 2.51 / Grafana 10.4 | `https://prometheus-community.github.io/helm-charts` | `https://nexus.internal/repository/helm-proxy/` | `monitoring` |
| `fluent-operator` | 3.x | Fluent Bit 3.x | `https://fluent.github.io/helm-charts` | `https://nexus.internal/repository/helm-proxy/` | `logging` |
| `opensearch` | 2.x | OpenSearch 2.x | `https://opensearch-project.github.io/helm-charts` | `https://nexus.internal/repository/helm-proxy/` | `logging` |
| `opensearch-dashboards` | 2.x | OpenSearch Dashboards 2.x | `https://opensearch-project.github.io/helm-charts` | `https://nexus.internal/repository/helm-proxy/` | `logging` |

### 2.3.2 Nexus Helm 저장소 등록

```bash
# Nexus Helm proxy 저장소 등록 (최초 1회)
helm repo add nexus-helm https://nexus.internal/repository/helm-proxy/ \
  --username <username> --password <password>

helm repo update

# Chart 가용 여부 확인
helm search repo nexus-helm/kube-prometheus-stack
helm search repo nexus-helm/fluent-operator
helm search repo nexus-helm/opensearch
```

### 2.3.3 컨테이너 이미지 미러링 현황

| 이미지 | 원본 레지스트리 | Nexus 미러 경로 | 비고 |
|--------|---------------|----------------|------|
| `quay.io/prometheus/prometheus` | quay.io | `nexus.internal/prometheus/prometheus` | Prometheus 본체 |
| `quay.io/prometheus/alertmanager` | quay.io | `nexus.internal/prometheus/alertmanager` | Alertmanager |
| `grafana/grafana` | docker.io | `nexus.internal/grafana/grafana` | Grafana |
| `fluent/fluent-operator` | docker.io | `nexus.internal/fluent/fluent-operator` | Operator |
| `cr.fluentbit.io/fluent/fluent-bit` | cr.fluentbit.io | `nexus.internal/fluent/fluent-bit` | DaemonSet |
| `opensearchproject/opensearch` | docker.io | `nexus.internal/opensearch/opensearch` | OpenSearch |
| `opensearchproject/opensearch-dashboards` | docker.io | `nexus.internal/opensearch/opensearch-dashboards` | Dashboards |

---

## 2.4 Kustomize 구성 전략

### 2.4.1 Base / Overlay 구조 설명

```
base/                     # 환경 공통 리소스 정의
  └── 변경 없이 모든 환경에서 사용하는 최소 공통 매니페스트

overlays/dev/             # dev 환경 패치 레이어
overlays/staging/         # staging 환경 패치 레이어
overlays/prod/            # prod 환경 패치 레이어 (이 문서의 기준)
```

Base 레이어에는 ServiceMonitor, PrometheusRule, FluentBit CR 등 환경 독립적인 리소스를 정의한다. Overlay 레이어에서는 Strategic Merge Patch 또는 JSON 6902 Patch를 통해 환경별 차이(스토리지 크기, 리소스 요청/제한, 레플리카 수 등)만 덮어쓴다.

### 2.4.2 환경별 패치 전략

| 리소스 | 패치 유형 | 대상 환경 | 패치 내용 요약 |
|--------|-----------|-----------|--------------|
| Prometheus PVC | Strategic Merge Patch | staging, prod | storage: dev 50Gi → staging 200Gi → prod 500Gi (NVMe Local PV) |
| Prometheus 리소스 | Strategic Merge Patch | prod | requests: cpu 4, memory 16Gi / limits: cpu 8, memory 32Gi |
| OpenSearch Hot 노드 | Strategic Merge Patch | prod | replicas: 3, storage 1Ti, cpu 16, memory 64Gi |
| OpenSearch Warm 노드 | Strategic Merge Patch | prod | replicas: 2, storage 2Ti, cpu 8, memory 32Gi |
| Fluent Bit DaemonSet | JSON 6902 Patch | prod | resources.limits.memory: 512Mi → 1Gi |
| Alertmanager | Strategic Merge Patch | prod | replicas: 2 (HA), storage 10Gi |
| Grafana | Strategic Merge Patch | staging, prod | persistence 활성화, admin password Secret 참조 |
| FluentBitConfig | Strategic Merge Patch | prod | throttle rate 증가, OpenSearch TLS 활성화 |

### 2.4.3 Secret 관리 전략

운영 환경에서 Secret 원문을 Git에 직접 저장하지 않는다. 아래 전략을 단계적으로 적용한다.

| 대상 Secret | 관리 방법 | 위치 | 비고 |
|------------|-----------|------|------|
| OpenSearch admin 비밀번호 | Kubernetes Secret (수동 생성) | 클러스터 내 `logging` 네임스페이스 | 최초 배포 전 Ops팀이 직접 생성 |
| Grafana admin 비밀번호 | Kubernetes Secret (수동 생성) | 클러스터 내 `monitoring` 네임스페이스 | Helm values에서 `existingSecret` 참조 |
| Alertmanager Slack/k8sAlert webhook | Kubernetes Secret (수동 생성) | 클러스터 내 `monitoring` 네임스페이스 | `alertmanager-secret` 명칭 통일 |
| Bitbucket 접근 토큰 | ArgoCD repo-creds (ArgoCD 내부 저장) | ArgoCD `argocd` 네임스페이스 | `argocd repo add` 명령으로 등록 |
| Nexus 인증 정보 | Kubernetes Secret (imagePullSecret) | 각 모듈 네임스페이스 | `nexus-registry-secret` 명칭 통일 |

```bash
# Secret 사전 생성 예시 (prod 환경 기준)
kubectl create secret generic opensearch-credentials \
  --from-literal=username=admin \
  --from-literal=password='<STRONG_PASSWORD>' \
  -n logging

kubectl create secret generic grafana-admin-credentials \
  --from-literal=admin-user=admin \
  --from-literal=admin-password='<STRONG_PASSWORD>' \
  -n monitoring

kubectl create secret generic alertmanager-secret \
  --from-literal=slack-webhook-url='https://hooks.slack.com/...' \
  --from-literal=k8salert-webhook-url='http://k8salert-svc/webhook' \
  -n monitoring
```

---

## 2.5 ArgoCD App of Apps 구성

### 2.5.1 AppProject 구성

| 프로젝트 명 | 허용 소스 저장소 | 허용 대상 클러스터 | 허용 네임스페이스 | 클러스터 리소스 생성 허용 |
|------------|----------------|-----------------|----------------|------------------------|
| `monitoring` | `https://bitbucket.internal/monitoring-gitops` | `https://kubernetes.default.svc` | `monitoring`, `argocd` | Namespace, ClusterRole, ClusterRoleBinding, CRD |
| `logging` | `https://bitbucket.internal/monitoring-gitops` | `https://kubernetes.default.svc` | `logging` | Namespace, ClusterRole, ClusterRoleBinding |
| `alerting` | `https://bitbucket.internal/monitoring-gitops` | `https://kubernetes.default.svc` | `monitoring` | ClusterRole, ClusterRoleBinding |

### 2.5.2 Application 목록

| App 명 | 소스 저장소 | 소스 경로 | 대상 네임스페이스 | Sync 정책 | Auto Prune | Self Heal | Sync Wave |
|--------|------------|---------|-----------------|----------|-----------|----------|-----------|
| `root-app` | monitoring-gitops | `apps/prod/` | `argocd` | Automated | 비활성화 | 활성화 | 0 |
| `monitoring-namespaces` | monitoring-kustomize | `overlays/prod/` | `monitoring`, `logging` | Automated | 활성화 | 활성화 | 1 |
| `prometheus-stack` | monitoring-helm-values | `kube-prometheus-stack/` | `monitoring` | Automated | 활성화 | 활성화 | 2 |
| `fluent-operator` | monitoring-helm-values | `fluent-operator/` | `logging` | Automated | 활성화 | 활성화 | 2 |
| `opensearch` | monitoring-helm-values | `opensearch/` | `logging` | Automated | 활성화 | 활성화 | 3 |
| `opensearch-dashboards` | monitoring-helm-values | `opensearch-dashboards/` | `logging` | Automated | 활성화 | 활성화 | 4 |
| `k8salert` | monitoring-helm-values | `k8salert/` | `monitoring` | Automated | 활성화 | 활성화 | 4 |
| `monitoring-crds` | monitoring-kustomize | `base/service-monitors/` | `monitoring` | Automated | 활성화 | 활성화 | 2 |
| `prometheus-rules` | monitoring-kustomize | `base/prometheus-rules/` | `monitoring` | Automated | 활성화 | 활성화 | 3 |
| `fluent-bit-configs` | monitoring-kustomize | `base/fluent-bit-configs/` | `logging` | Automated | 활성화 | 활성화 | 3 |

> **주의**: Auto Prune 활성화 시 Git에서 리소스를 삭제하면 클러스터에서도 즉시 삭제된다. root-app의 Auto Prune은 반드시 비활성화 상태를 유지한다.

### 2.5.3 Sync Wave 순서

| Wave | 대상 Application | 이유 |
|------|----------------|------|
| 0 | `root-app` | 모든 하위 Application의 부모. 최우선 생성 필요 |
| 1 | `monitoring-namespaces` | Namespace 및 RBAC가 선행 생성되어야 이후 리소스 배포 가능 |
| 2 | `prometheus-stack`, `fluent-operator`, `monitoring-crds` | CRD 등록 및 Operator 기동. ServiceMonitor CRD가 없으면 Wave 3 리소스 적용 실패 |
| 3 | `opensearch`, `prometheus-rules`, `fluent-bit-configs` | Prometheus가 먼저 기동되어야 PrometheusRule이 인식됨. OpenSearch가 먼저 기동되어야 Fluent Bit output 연결 가능 |
| 4 | `opensearch-dashboards`, `k8salert` | OpenSearch API 사용 가능 상태 이후 Dashboards 기동. Alertmanager가 준비된 후 k8sAlert webhook 연동 |

### 2.5.4 root-app.yaml 예시

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-app
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: monitoring
  source:
    repoURL: https://bitbucket.internal/monitoring-gitops
    targetRevision: main
    path: apps/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      selfHeal: true
      prune: false    # root-app은 반드시 prune 비활성화
```

---

## 2.6 사전 리소스 준비 체크리스트

아래 체크리스트는 모든 모듈 설치 이전에 완료해야 한다. 각 항목의 확인 명령어를 실행하여 정상 상태를 검증한다.

### 2.6.1 Namespace 준비

| 항목 | 확인 명령어 | 정상 기준 | 상태 |
|------|------------|----------|------|
| `monitoring` 네임스페이스 존재 | `kubectl get ns monitoring` | STATUS: Active | [ ] |
| `logging` 네임스페이스 존재 | `kubectl get ns logging` | STATUS: Active | [ ] |
| `argocd` 네임스페이스 존재 | `kubectl get ns argocd` | STATUS: Active | [ ] |
| 네임스페이스 레이블 설정 | `kubectl get ns monitoring --show-labels` | `monitoring=enabled` 레이블 포함 | [ ] |

### 2.6.2 Local PV 준비 (NVMe 4TB)

| 항목 | 대상 | 용량 | 확인 명령어 | 정상 기준 | 상태 |
|------|------|------|------------|----------|------|
| Prometheus PV | `monitoring` | 500Gi | `kubectl get pv \| grep prometheus` | STATUS: Available 또는 Bound | [ ] |
| Alertmanager PV | `monitoring` | 10Gi | `kubectl get pv \| grep alertmanager` | STATUS: Available 또는 Bound | [ ] |
| OpenSearch Hot 노드 PV (×3) | `logging` | 1Ti × 3 | `kubectl get pv \| grep opensearch-hot` | 3개 모두 Available | [ ] |
| OpenSearch Warm 노드 PV (×2) | `logging` | 2Ti × 2 | `kubectl get pv \| grep opensearch-warm` | 2개 모두 Available | [ ] |
| Grafana PV | `monitoring` | 20Gi | `kubectl get pv \| grep grafana` | STATUS: Available 또는 Bound | [ ] |
| StorageClass 등록 | 전체 | - | `kubectl get sc local-nvme` | PROVISIONER: kubernetes.io/no-provisioner | [ ] |

### 2.6.3 Secrets 준비

| Secret 명 | 네임스페이스 | 키 목록 | 확인 명령어 | 상태 |
|-----------|------------|--------|------------|------|
| `opensearch-credentials` | `logging` | `username`, `password` | `kubectl get secret opensearch-credentials -n logging` | [ ] |
| `grafana-admin-credentials` | `monitoring` | `admin-user`, `admin-password` | `kubectl get secret grafana-admin-credentials -n monitoring` | [ ] |
| `alertmanager-secret` | `monitoring` | `slack-webhook-url`, `k8salert-webhook-url` | `kubectl get secret alertmanager-secret -n monitoring` | [ ] |
| `nexus-registry-secret` | `monitoring` | `.dockerconfigjson` | `kubectl get secret nexus-registry-secret -n monitoring` | [ ] |
| `nexus-registry-secret` | `logging` | `.dockerconfigjson` | `kubectl get secret nexus-registry-secret -n logging` | [ ] |

### 2.6.4 RBAC / ServiceAccount 준비

| 항목 | 확인 명령어 | 정상 기준 | 상태 |
|------|------------|----------|------|
| Prometheus ServiceAccount | `kubectl get sa prometheus -n monitoring` | ServiceAccount 존재 | [ ] |
| Fluent Bit ServiceAccount | `kubectl get sa fluent-bit -n logging` | ServiceAccount 존재 | [ ] |
| Prometheus ClusterRole | `kubectl get clusterrole prometheus` | ClusterRole 존재 | [ ] |
| Prometheus ClusterRoleBinding | `kubectl get clusterrolebinding prometheus` | ClusterRoleBinding 존재 | [ ] |
| Fluent Bit ClusterRole | `kubectl get clusterrole fluent-bit` | ClusterRole 존재 | [ ] |
| node-exporter DaemonSet 권한 | `kubectl auth can-i list nodes --as=system:serviceaccount:monitoring:node-exporter` | yes | [ ] |

### 2.6.5 네트워크 준비

| 항목 | 확인 명령어 | 정상 기준 | 상태 |
|------|------------|----------|------|
| bond0 (Public 25G+25G LACP) 링크 상태 | `ip link show bond0` | state UP | [ ] |
| bond1 (Private 25G+25G LACP) 링크 상태 | `ip link show bond1` | state UP | [ ] |
| Nexus 레지스트리 접근 가능 여부 | `curl -s https://nexus.internal/ping` | HTTP 200 | [ ] |
| Bitbucket 접근 가능 여부 | `curl -s https://bitbucket.internal/status` | HTTP 200 | [ ] |
| DNS 해상도 확인 | `nslookup nexus.internal` | IP 주소 반환 | [ ] |
| ArgoCD 서버 접근 가능 여부 | `argocd app list` | 명령 성공 | [ ] |

### 2.6.6 ArgoCD 저장소 등록

| 저장소 | 등록 명령어 | 확인 명령어 | 상태 |
|--------|------------|------------|------|
| `monitoring-gitops` | `argocd repo add https://bitbucket.internal/monitoring-gitops --username <user> --password <token>` | `argocd repo list` | [ ] |
| `monitoring-helm-values` | `argocd repo add https://bitbucket.internal/monitoring-helm-values --username <user> --password <token>` | `argocd repo list` | [ ] |
| `monitoring-kustomize` | `argocd repo add https://bitbucket.internal/monitoring-kustomize --username <user> --password <token>` | `argocd repo list` | [ ] |

---

*다음 섹션: [Section 3: 모니터링 모듈 설치](./03-module-installation.md)*
