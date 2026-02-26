# Fluent Bit 멀티 인덱스 출력 설정

## 1. 개요

클러스터별, 로그 유형별로 별도의 OpenSearch 인덱스에 데이터를 전송하기 위한 Fluent Bit 설정입니다. Fluent Bit Operator의 CRD(Custom Resource Definition)를 사용합니다.

### 전체 파이프라인 흐름

```
┌──────────────────────────────────────────────────────────────┐
│                     Fluent Bit 파이프라인                      │
│                                                              │
│  ┌─────────────────┐                                        │
│  │ Input: tail      │──── tag: container.*                   │
│  │ (container log)  │         ↓                              │
│  └─────────────────┘    ┌──────────┐   ┌──────────────────┐ │
│                         │ Filter:  │──▶│ Output: opensearch│ │
│  ┌─────────────────┐   │ modify   │   │ container-logs-*  │ │
│  │ Input: kube_events│── tag: k8sevt.* │                    │ │
│  │ (k8s events)     │   │ + cluster│   ├──────────────────┤ │
│  └─────────────────┘   │ + node   │──▶│ Output: opensearch│ │
│                         │          │   │ k8s-events-*      │ │
│  ┌─────────────────┐   │          │   ├──────────────────┤ │
│  │ Input: systemd   │── tag: systemd.*│ Output: opensearch│ │
│  │ (systemd log)    │   └──────────┘──▶│ systemd-logs-*   │ │
│  └─────────────────┘                   └──────────────────┘ │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## 2. Input 설정

### 2-1. Container Log Input

기존 `cluster-input-hostpath.yaml`을 확장합니다.

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterInput
metadata:
  name: container-logs
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  tail:
    tag: "container.*"
    path: "/var/log/containers/*.log"
    pathKey: source_file
    refreshIntervalSeconds: 5
    memBufLimit: "10MB"
    skipLongLines: true
    db: "/var/log/flb-storage/container-tail-pos.db"
    dbSync: Normal
    readFromHead: false
    storageType: filesystem
    parser: cri
```

> **참고:** 기존 hostpath 방식(`/var/log/*/app*.log`)과 표준 컨테이너 로그 경로(`/var/log/containers/*.log`) 중 환경에 맞는 경로를 선택하세요. CRI 런타임(containerd)을 사용하면 `/var/log/containers/` 경로를 사용합니다.

### 2-2. Kubernetes Event Input

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterInput
metadata:
  name: k8s-events
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  kubernetesEvents:
    tag: "k8sevt.*"
    db: "/var/log/flb-storage/k8s-events-pos.db"
    retentionTime: "1h"
```

> **kubernetes_events 플러그인:** Fluent Bit 2.1+ 내장 플러그인으로, K8s API를 통해 클러스터 이벤트를 수집합니다. DaemonSet 환경에서는 하나의 Pod만 이벤트를 수집하도록 리더 선출이 내부적으로 처리됩니다.

### 2-3. Systemd Log Input

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterInput
metadata:
  name: systemd-logs
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  systemd:
    tag: "systemd.*"
    path: "/var/log/journal"
    db: "/var/log/flb-storage/systemd-pos.db"
    systemdFilter:
      - "_SYSTEMD_UNIT=kubelet.service"
      - "_SYSTEMD_UNIT=containerd.service"
      - "_SYSTEMD_UNIT=docker.service"
    stripUnderscores: true
    storageType: filesystem
```

> **systemdFilter:** 수집 대상 systemd 유닛을 제한합니다. 필요에 따라 `crio.service`, `etcd.service` 등을 추가하세요.

### Input을 위한 추가 Volume Mount

systemd 로그와 K8s events를 수집하려면 FluentBit CR에 volume을 추가해야 합니다.

```yaml
# pipeline/fluentbit-cr.yaml에 추가
spec:
  volumes:
    - name: varlog
      hostPath:
        path: /var/log
        type: DirectoryOrCreate
    - name: flb-storage
      hostPath:
        path: /var/log/flb-storage/
        type: DirectoryOrCreate
    - name: lua-scripts
      configMap:
        name: fluent-bit-lua-scripts
    # --- 추가 볼륨 ---
    - name: journal
      hostPath:
        path: /var/log/journal
        type: DirectoryOrCreate
    - name: containers-log
      hostPath:
        path: /var/log/containers
        type: DirectoryOrCreate

  volumesMounts:
    - name: varlog
      mountPath: /var/log
    - name: flb-storage
      mountPath: /var/log/flb-storage/
    - name: lua-scripts
      mountPath: /fluent-bit/scripts
    # --- 추가 마운트 ---
    - name: journal
      mountPath: /var/log/journal
      readOnly: true
    - name: containers-log
      mountPath: /var/log/containers
      readOnly: true
```

## 3. Filter 설정

### 3-1. Container Log Filter (Kubernetes 메타데이터 추가)

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterFilter
metadata:
  name: container-kubernetes-metadata
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  match: "container.*"
  filters:
    - kubernetes:
        kubeURL: "https://kubernetes.default.svc:443"
        kubeCAFile: "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        kubeTokenFile: "/var/run/secrets/kubernetes.io/serviceaccount/token"
        mergeLog: true
        keepLog: false
        k8sLoggingParser: true
        labels: true
        annotations: false
```

### 3-2. 공통 클러스터명 추가 Filter

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterFilter
metadata:
  name: add-cluster-name
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  match: "*"
  filters:
    - modify:
        rules:
          - add:
              cluster_name: "bigdata-prod"
```

> **중요:** `cluster_name` 값을 각 클러스터에 맞게 변경하세요. 이 값이 인덱스 이름에 포함됩니다.

### 3-3. Systemd Log Node 이름 추가 Filter

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterFilter
metadata:
  name: systemd-add-node
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  match: "systemd.*"
  filters:
    - modify:
        rules:
          - add:
              node_name: "${NODE_NAME}"
```

> **`${NODE_NAME}`:** FluentBit CR의 `env` 설정에서 Downward API로 주입합니다.

```yaml
# fluentbit-cr.yaml의 spec에 추가
spec:
  env:
    - name: NODE_NAME
      valueFrom:
        fieldRef:
          fieldPath: spec.nodeName
    - name: CLUSTER_NAME
      value: "bigdata-prod"
```

## 4. Output 설정

### 4-1. Container Log Output

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterOutput
metadata:
  name: opensearch-container-logs
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  match: "container.*"
  opensearch:
    host: opensearch-cluster-master.logging.svc.cluster.local
    port: 9200
    index: "container-logs-bigdata-prod"
    logstashFormat: true
    logstashPrefix: "container-logs-bigdata-prod"
    logstashDateFormat: "%Y.%m.%d"
    replaceDots: true
    suppressTypeName: true
    traceError: true
    bufferSize: "5MB"
```

### 4-2. K8s Event Log Output

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterOutput
metadata:
  name: opensearch-k8s-events
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  match: "k8sevt.*"
  opensearch:
    host: opensearch-cluster-master.logging.svc.cluster.local
    port: 9200
    index: "k8s-events-bigdata-prod"
    logstashFormat: true
    logstashPrefix: "k8s-events-bigdata-prod"
    logstashDateFormat: "%Y.%m.%d"
    replaceDots: true
    suppressTypeName: true
    traceError: true
    bufferSize: "2MB"
```

### 4-3. Systemd Log Output

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterOutput
metadata:
  name: opensearch-systemd-logs
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  match: "systemd.*"
  opensearch:
    host: opensearch-cluster-master.logging.svc.cluster.local
    port: 9200
    index: "systemd-logs-bigdata-prod"
    logstashFormat: true
    logstashPrefix: "systemd-logs-bigdata-prod"
    logstashDateFormat: "%Y.%m.%d"
    replaceDots: true
    suppressTypeName: true
    traceError: true
    bufferSize: "2MB"
```

## 5. 멀티 클러스터 설정 방법

각 클러스터의 Fluent Bit에서 `cluster_name`과 `logstashPrefix`를 변경하여 클러스터별 인덱스를 생성합니다.

### 클러스터별 변경 항목

| 설정 항목 | Cluster A | Cluster B | Cluster C |
|-----------|-----------|-----------|-----------|
| `cluster_name` (filter) | `bigdata-prod` | `bigdata-dev` | `ml-platform-prod` |
| Container `logstashPrefix` | `container-logs-bigdata-prod` | `container-logs-bigdata-dev` | `container-logs-ml-platform-prod` |
| K8s Event `logstashPrefix` | `k8s-events-bigdata-prod` | `k8s-events-bigdata-dev` | `k8s-events-ml-platform-prod` |
| Systemd `logstashPrefix` | `systemd-logs-bigdata-prod` | `systemd-logs-bigdata-dev` | `systemd-logs-ml-platform-prod` |

### 환경변수 기반 동적 설정 (권장)

`CLUSTER_NAME` 환경변수를 사용하면 동일한 매니페스트를 여러 클러스터에서 재사용할 수 있습니다.

```yaml
# FluentBit CR에서 환경변수 정의
spec:
  env:
    - name: CLUSTER_NAME
      value: "bigdata-prod"  # 클러스터별로 변경

# Output에서 환경변수 참조
spec:
  opensearch:
    logstashPrefix: "container-logs-${CLUSTER_NAME}"
```

> **주의:** Fluent Bit Operator CRD에서 환경변수 치환이 지원되지 않는 경우, Kustomize overlay 또는 Helm values를 사용하여 클러스터별로 값을 주입하세요.

### Kustomize Overlay 예시

```
overlays/
├── bigdata-prod/
│   └── kustomization.yaml
├── bigdata-dev/
│   └── kustomization.yaml
└── ml-platform-prod/
    └── kustomization.yaml
```

```yaml
# overlays/bigdata-prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base/pipeline
patches:
  - target:
      kind: ClusterFilter
      name: add-cluster-name
    patch: |-
      - op: replace
        path: /spec/filters/0/modify/rules/0/add/cluster_name
        value: "bigdata-prod"
  - target:
      kind: ClusterOutput
      name: opensearch-container-logs
    patch: |-
      - op: replace
        path: /spec/opensearch/logstashPrefix
        value: "container-logs-bigdata-prod"
  - target:
      kind: ClusterOutput
      name: opensearch-k8s-events
    patch: |-
      - op: replace
        path: /spec/opensearch/logstashPrefix
        value: "k8s-events-bigdata-prod"
  - target:
      kind: ClusterOutput
      name: opensearch-systemd-logs
    patch: |-
      - op: replace
        path: /spec/opensearch/logstashPrefix
        value: "systemd-logs-bigdata-prod"
```

## 6. 생성되는 인덱스 예시

위 설정이 적용된 후 OpenSearch에 생성되는 인덱스:

```
# Cluster: bigdata-prod
container-logs-bigdata-prod-2026.02.26
container-logs-bigdata-prod-2026.02.25
k8s-events-bigdata-prod-2026.02.26
k8s-events-bigdata-prod-2026.02.25
systemd-logs-bigdata-prod-2026.02.26
systemd-logs-bigdata-prod-2026.02.25

# Cluster: bigdata-dev
container-logs-bigdata-dev-2026.02.26
k8s-events-bigdata-dev-2026.02.26
systemd-logs-bigdata-dev-2026.02.26

# Cluster: ml-platform-prod
container-logs-ml-platform-prod-2026.02.26
k8s-events-ml-platform-prod-2026.02.26
systemd-logs-ml-platform-prod-2026.02.26
```

## 7. OpenSearch Dashboards 인덱스 패턴

Dashboards에서 데이터를 조회하기 위한 인덱스 패턴 설정:

| 용도 | 인덱스 패턴 | 설명 |
|------|------------|------|
| 전체 Container 로그 | `container-logs-*` | 모든 클러스터 컨테이너 로그 |
| 특정 클러스터 Container | `container-logs-bigdata-prod-*` | 특정 클러스터 필터링 |
| 전체 K8s Event | `k8s-events-*` | 모든 클러스터 이벤트 |
| 전체 Systemd | `systemd-logs-*` | 모든 클러스터 시스템 로그 |
| 전체 로그 (통합) | `*-logs-*,k8s-events-*` | 모든 로그 통합 검색 |
