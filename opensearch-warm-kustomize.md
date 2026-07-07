# Kustomize + Helm으로 OpenSearch hot/warm 티어 구성하기

warm 노드 티어링(방식 C: hot ×3 local-path + warm ×2 Isilon PVC)을 **kustomize의 helmCharts 인플레이션**으로 선언적으로 관리하는 가이드. Helm release 2개(hot/warm nodeGroup)와 부속 리소스(StorageClass/PV, 정책 적용 Job)를 하나의 `kustomize build`로 렌더링한다.

| 요구 도구 | 버전 |
|---|---|
| kustomize | v4.1+ (helmCharts 지원) — kubectl 내장 kustomize 사용 시 kubectl 1.27+ 권장 |
| helm | v3.x — kustomize가 내부적으로 호출하므로 PATH에 필요 |
| chart | opensearch 2.32.0 / image 2.19.1 |

---

## 1. 디렉터리 구조

```
opensearch-tiering/
├── base/
│   ├── kustomization.yaml          # helmCharts 2개 (hot / warm) 인플레이션
│   ├── values-hot.yaml             # 공통 hot values
│   ├── values-warm.yaml            # 공통 warm values
│   └── resources/
│       ├── namespace.yaml
│       └── ism-apply-job.yaml      # (선택) ISM 정책/템플릿 적용 Job
└── overlays/
    └── dev/
        ├── kustomization.yaml      # dev 전용 오버라이드 + PV
        ├── values-hot-dev.yaml     # (valuesMerge용) dev 오버라이드
        ├── values-warm-dev.yaml
        └── resources/
            ├── isilon-pv-0.yaml    # 정적 NFS PV (CSI 미사용 시)
            └── isilon-pv-1.yaml
```

## 2. base

### 2-1. base/kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: opensearch

resources:
  - resources/namespace.yaml
  - resources/ism-apply-job.yaml

helmCharts:
  # ── hot nodeGroup (기존 3노드) ──
  - name: opensearch
    repo: https://opensearch-project.github.io/helm-charts
    version: 2.32.0
    releaseName: opensearch          # 기존 release명 유지
    namespace: opensearch
    valuesFile: values-hot.yaml

  # ── warm nodeGroup (신규 2노드) ──
  - name: opensearch
    repo: https://opensearch-project.github.io/helm-charts
    version: 2.32.0
    releaseName: opensearch-warm
    namespace: opensearch
    valuesFile: values-warm.yaml
```

### 2-2. base/values-hot.yaml

```yaml
clusterName: "opensearch-cluster"
nodeGroup: "master"
replicas: 3

image:
  repository: opensearchproject/opensearch
  tag: "2.19.1"

roles:
  - master
  - ingest
  - data
  - remote_cluster_client

config:
  opensearch.yml: |
    cluster.name: opensearch-cluster
    network.host: 0.0.0.0
    node.attr.temp: hot
    # ...기존 보안/기타 설정...

persistence:
  enabled: true
  storageClass: "local-path"
  accessModes: [ ReadWriteOnce ]
  size: 250Gi

podSecurityContext:
  fsGroup: 1000
  runAsUser: 1000
```

### 2-3. base/values-warm.yaml

```yaml
clusterName: "opensearch-cluster"     # 동일 클러스터명 = 같은 클러스터 조인
nodeGroup: "warm"
replicas: 2

image:
  repository: opensearchproject/opensearch
  tag: "2.19.1"

roles:
  - data                              # data 전용 (quorum은 hot 3노드)

masterService: "opensearch-cluster-master"   # 기존 discovery 서비스

config:
  opensearch.yml: |
    cluster.name: opensearch-cluster
    network.host: 0.0.0.0
    node.attr.temp: warm
    # 보안 인증서/설정은 hot과 동일 소스로

persistence:
  enabled: true
  storageClass: "isilon-nfs"
  accessModes: [ ReadWriteOnce ]
  size: 6Ti

resources:
  requests: { cpu: "1", memory: 4Gi }
  limits:   { cpu: "2", memory: 8Gi }
opensearchJavaOpts: "-Xms2g -Xmx2g"

podSecurityContext:
  fsGroup: 1000
  runAsUser: 1000
```

### 2-4. base/resources/ism-apply-job.yaml (선택 — 정책도 GitOps로)

ISM 정책·인덱스 템플릿은 K8s 리소스가 아니라 API 호출이므로, 선언 관리하려면 Job으로 감싼다:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ism-policies
data:
  apply.sh: |
    #!/bin/bash
    set -e
    OS="https://opensearch-cluster-master:9200"
    A="-u ${OS_USER}:${OS_PASS} -k -s -H Content-Type:application/json"
    # 인덱스 템플릿 (niofs + hot 배치 고정)
    curl $A -X PUT "$OS/_index_template/icdataops-dev-log-template" -d @/policies/template.json
    # ISM 정책 (있으면 갱신 실패는 무시 — seq_no 갱신은 수동/파이프라인에서)
    curl $A -X PUT "$OS/_plugins/_ism/policies/icdataops-dev-log-policy" -d @/policies/policy.json || true
  template.json: |
    { "index_patterns": ["icdataops-dev-log-*"], "priority": 200,
      "template": { "settings": {
        "number_of_shards": 1, "number_of_replicas": 1,
        "index.store.type": "niofs",
        "index.routing.allocation.require.temp": "hot",
        "plugins.index_state_management.rollover_alias": "icdataops-dev-log" } } }
  policy.json: |
    { "policy": { "description": "hot 1d/10gb -> warm 30d (Isilon warm nodes) -> delete",
      "default_state": "hot",
      "ism_template": [ { "index_patterns": ["icdataops-dev-log-*"], "priority": 100 } ],
      "states": [
        { "name": "hot",
          "actions": [ { "rollover": { "min_index_age": "1d", "min_primary_shard_size": "10gb" } } ],
          "transitions": [ { "state_name": "warm", "conditions": { "min_rollover_age": "1h" } } ] },
        { "name": "warm",
          "actions": [
            { "read_only": {} },
            { "force_merge": { "max_num_segments": 1 } },
            { "retry": { "count": 5, "backoff": "exponential", "delay": "10m" },
              "allocation": { "require": { "temp": "warm" } } } ],
          "transitions": [ { "state_name": "delete", "conditions": { "min_index_age": "30d" } } ] },
        { "name": "delete",
          "actions": [ { "retry": { "count": 3, "backoff": "exponential", "delay": "10m" }, "delete": {} } ] } ] } }
---
apiVersion: batch/v1
kind: Job
metadata:
  name: ism-apply
  annotations:
    kustomize.config.k8s.io/behavior: replace   # 재적용 시 교체
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: apply
          image: curlimages/curl:8.7.1
          command: ["/bin/sh", "/policies/apply.sh"]
          env:
            - name: OS_USER
              valueFrom: { secretKeyRef: { name: opensearch-credentials, key: username } }
            - name: OS_PASS
              valueFrom: { secretKeyRef: { name: opensearch-credentials, key: password } }
          volumeMounts:
            - { name: policies, mountPath: /policies }
      volumes:
        - name: policies
          configMap: { name: ism-policies, defaultMode: 0755 }
```

> 기존 정책 갱신은 `?if_seq_no=&if_primary_term=`가 필요해 단순 PUT은 실패한다. Job은 최초 등록용으로 쓰고 갱신은 파이프라인/수동으로 처리하거나, 스크립트에 GET→seq_no 파싱 로직을 추가한다.

## 3. overlay (dev)

### 3-1. overlays/dev/kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base
  - resources/isilon-pv-0.yaml
  - resources/isilon-pv-1.yaml

# 환경별 values 오버라이드: base helmCharts에 병합
helmCharts:
  - name: opensearch
    releaseName: opensearch
    additionalValuesFiles:
      - values-hot-dev.yaml
  - name: opensearch
    releaseName: opensearch-warm
    additionalValuesFiles:
      - values-warm-dev.yaml

# 인플레이션 결과에 대한 세부 패치도 가능 (values로 안 되는 부분)
patches:
  - target:
      kind: StatefulSet
      name: opensearch-cluster-warm
    patch: |-
      - op: add
        path: /spec/template/metadata/labels/tier
        value: warm
```

> `additionalValuesFiles`는 kustomize v5+ 기능. v4를 쓰면 overlay에서 helmCharts를 재선언(valuesFile을 dev용으로 교체)하거나, 렌더링 결과를 patches로만 조정한다.

### 3-2. overlays/dev/values-warm-dev.yaml (예: dev는 warm 1대·용량 축소)

```yaml
replicas: 2
persistence:
  size: 4Ti
```

### 3-3. overlays/dev/resources/isilon-pv-0.yaml (정적 PV 방식일 때)

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: warm-data-opensearch-cluster-warm-0     # PVC명과 매칭되게
spec:
  capacity: { storage: 6Ti }
  accessModes: [ ReadWriteOnce ]
  storageClassName: isilon-nfs
  persistentVolumeReclaimPolicy: Retain
  mountOptions: [ "vers=3", "nolock", "hard", "timeo=600", "rsize=1048576", "wsize=1048576" ]
  claimRef:
    namespace: opensearch
    name: opensearch-cluster-warm-opensearch-cluster-warm-0   # <persistence.name 접두>-<sts pod명>
  nfs:
    server: isilon.example.internal
    path: /ifs/data/opensearch-warm/node-0
```

`isilon-pv-1.yaml`은 `node-1` 경로 + `...-warm-1` claimRef로 동일 구성. PVC 실제 이름은 chart의 volumeClaimTemplate 규칙을 따르므로 **한 번 dry-run으로 확인 후 claimRef를 맞출 것** (5-1 참조). CSI PowerScale StorageClass를 쓰면 이 PV 파일들 자체가 불필요하다.

## 4. 빌드/배포

```bash
# helmCharts 인플레이션에는 --enable-helm 플래그 필수
kustomize build --enable-helm overlays/dev | less        # 렌더링 검토

# 적용
kustomize build --enable-helm overlays/dev | kubectl apply -f -

# kubectl 내장 kustomize 사용 시 (1.27+)
kubectl kustomize --enable-helm overlays/dev | kubectl apply -f -
```

주의사항:

1. **차트는 `charts/` 하위에 자동 pull**된다 (`base/charts/opensearch-2.32.0/...`). Git에는 `.gitignore`로 제외하거나, 에어갭 환경이면 미리 커밋해 두고 `repo` 대신 로컬 경로를 쓴다.
2. **helm으로 이미 설치된 기존 release와의 충돌**: kustomize 인플레이션은 `helm template` 결과를 apply하는 것이라 helm release 메타데이터(secret)와 별개다. 기존 `helm install opensearch`로 깔린 클러스터에 이 방식을 겹치면 소유권 충돌이 난다. 마이그레이션 방법:
   - 간단: hot은 기존 helm release로 유지하고, **warm만** kustomize 관리 (base에서 hot helmCharts 제거)
   - 정석: 기존 release를 `helm uninstall --keep-history` 없이 두고, 렌더링 결과에 `kubectl apply --server-side --force-conflicts`로 소유권 이전 후 helm secret 정리 — StatefulSet/PVC는 삭제되지 않게 반드시 dry-run 검증
3. StatefulSet 이름은 `<clusterName>-<nodeGroup>` 규칙: hot=`opensearch-cluster-master`, warm=`opensearch-cluster-warm`.

## 5. 검증

```bash
# 5-1. 렌더링에서 PVC 이름 확인 (정적 PV claimRef 맞추기)
kustomize build --enable-helm overlays/dev | grep -A3 "volumeClaimTemplates" -n
kubectl -n opensearch get pvc | grep warm

# 5-2. 노드 조인 + temp 속성
kubectl -n opensearch get pods
# Dev Tools: GET _cat/nodes?v&h=name,node.role,attr.temp

# 5-3. ISM Job 완료 + 정책 확인
kubectl -n opensearch logs job/ism-apply
# Dev Tools: GET _plugins/_ism/policies/icdataops-dev-log-policy

# 5-4. 티어 동작 (rollover 후)
# GET _cat/shards/icdataops-dev-log-*?v&h=index,prirep,state,node&s=index
```

## 6. ArgoCD 연동 (참고)

ArgoCD에서 helmCharts 인플레이션을 쓰려면 kustomize 빌드 옵션에 플래그 추가:

```yaml
# argocd-cm ConfigMap
data:
  kustomize.buildOptions: --enable-helm
```

이후 Application의 `spec.source.path`를 `overlays/dev`로 지정하면 렌더링·동기화가 자동화된다. (helm 바이너리는 argocd-repo-server 이미지에 포함되어 있음)

## 7. 적용 순서 요약

1. base/overlay 작성 → `kustomize build --enable-helm` 렌더링 검토 (특히 warm StatefulSet, PVC명)
2. 정적 PV의 claimRef를 렌더링된 PVC명에 맞춤 (CSI면 생략)
3. hot: 기존 helm 관리 유지 여부 결정 (4장 주의 2)
4. `kubectl apply` → warm 2노드 조인 확인 (`attr.temp` 포함)
5. ism-apply Job으로 템플릿/정책 등록 → `_ism/explain` 검증
6. 기존 인덱스 change_policy (오래된 것부터 소량씩)
