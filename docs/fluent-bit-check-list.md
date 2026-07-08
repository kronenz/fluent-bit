# Fluent Operator Helm values.yaml — AS-IS(3.2.0) → TO-BE(4.2.0) 스키마 대조표

> **AS-IS:** 구 `fluent-operator` chart 3.2.0 계열 values.yaml (kubesphere 이미지 계열)
> **TO-BE:** 최신 `fluent/helm-charts` chart 4.2.0 values.yaml (Operator v3.9.0 / Fluent Bit 5.0.x)
> 실제 values.yaml의 키 경로(dot notation) 그대로 좌우 대조. **변경/삭제/신규**를 표기했습니다.

## 표기

| 표기 | 의미 |
|------|------|
| 🔴 REMOVED | 키가 사라짐. 그대로 두면 무시(no-op) 또는 오류 |
| 🟠 RENAMED/MOVED | 키 경로·이름이 바뀜. 값 이전 필요 |
| 🟡 CHANGED | 키는 유지되나 기본값/의미 변경 |
| 🟢 SAME | 동일하게 통용 |
| 🆕 NEW | TO-BE에서 새로 추가된 키 |

---

## 1. 최상위 (top-level)

| AS-IS (chart 3.2.0) | TO-BE (chart 4.2.0) | 구분 | 비고 |
|---------------------|----------------------|:---:|------|
| `logPath:` <br>(하위 `containerd`/`crio` 경로 지정) | `containerRuntime: containerd` | 🟠 RENAMED | 로그 경로를 직접 적던 방식 → 런타임 종류 지정 방식. 값: `containerd`/`crio`/`docker` |
| *(암묵적 docker 가정)* | `containerRuntime` 기본값 `containerd` | 🟡 CHANGED | **기본 런타임이 docker→containerd**. docker/cri-o면 명시 필수 |
| `Kubernetes: true` | `Kubernetes: true` | 🟢 SAME | 기본 파이프라인 배포 스위치 |
| `nameOverride: ""` | `nameOverride: ""` | 🟢 SAME | |
| `fullnameOverride: ""` | `fullnameOverride: ""` | 🟢 SAME | |
| `namespaceOverride: ""` | `namespaceOverride: ""` | 🟢 SAME | |
| *(서브차트 값) `fluentbit-crds.*` / `fluentd-crds.*`* | *(제거)* | 🔴 REMOVED | CRD가 별도 top-level 차트로 분리. 이 값들은 무시됨 |

---

## 2. operator 블록

| AS-IS (chart 3.2.0) | TO-BE (chart 4.2.0) | 구분 | 비고 |
|---------------------|----------------------|:---:|------|
| `operator.initcontainer.repository` | *(제거)* | 🔴 REMOVED | init container 자체 제거 |
| `operator.initcontainer.tag` | *(제거)* | 🔴 REMOVED | 동일 |
| `operator.container.repository` | `operator.image.repository` | 🟠 RENAMED | 예: `fluent/fluent-operator/fluent-operator` |
| `operator.container.tag` | `operator.image.tag` | 🟠 RENAMED | 기본값=chart appVersion(v3.9.0) |
| *(레지스트리 분리 없음)* | `operator.image.registry: ghcr.io` | 🆕 NEW | 레지스트리 분리 지정 |
| `operator.resources.*` | `operator.resources.*` | 🟢 SAME | limits/requests 동일 구조 |
| `operator.annotations` | `operator.annotations` | 🟢 SAME | |
| `operator.labels` | `operator.labels` | 🟢 SAME | |
| `operator.imagePullSecrets` | `operator.imagePullSecrets` | 🟢 SAME | |
| *(없음)* | `operator.enable: true` | 🆕 NEW | 오퍼레이터 배포 on/off |
| *(없음)* | `operator.nodeSelector` / `affinity` / `tolerations` / `priorityClassName` | 🆕 NEW | 스케줄링 옵션 |
| *(없음)* | `operator.podSecurityContext` / `operator.securityContext` | 🆕 NEW | 보안 컨텍스트(하드닝) |
| *(없음)* | `operator.rbac.create` | 🆕 NEW | RBAC 생성 on/off |
| *(없음)* | `operator.rbac.clusterRole.name` / `clusterRoleBinding.name` | 🆕 NEW | 이름 지정 |
| *(없음)* | `operator.rbac.additionalRules` | 🆕 NEW | 추가 RBAC 규칙 |
| *(없음)* | `operator.disableComponentControllers` | 🆕 NEW | `fluent-bit`/`fluentd` 컨트롤러 비활성화 |
| *(없음)* | `operator.extraArgs` | 🆕 NEW | 예: `--watch-namespaces=logging` |
| *(없음)* | `operator.service.*` | 🆕 NEW | 메트릭 서비스(enable/type/port 등) |
| *(없음)* | `operator.serviceMonitor.*` | 🆕 NEW | Prometheus ServiceMonitor |
| *(없음)* | `operator.serviceAccount.name` | 🆕 NEW | SA 이름 지정 |

---

## 3. fluentbit 블록 — 이미지·기본

| AS-IS (chart 3.2.0) | TO-BE (chart 4.2.0) | 구분 | 비고 |
|---------------------|----------------------|:---:|------|
| `fluentbit.enable` | `fluentbit.enable` | 🟢 SAME | |
| `fluentbit.image.repository:` <br>`kubesphere/fluent-bit` | `fluentbit.image.repository:` <br>`fluent/fluent-operator/fluent-bit` | 🟠 CHANGED | **레지스트리/경로 변경**. 옛 경로 고정 시 pull 실패·구버전 |
| *(레지스트리 분리 없음)* | `fluentbit.image.registry: ghcr.io` | 🆕 NEW | |
| `fluentbit.image.tag: v2.x/3.x` | `fluentbit.image.tag: "5.0.x"` | 🟡 CHANGED | **Fluent Bit 메이저 상승**. 태그 고정 시 버전 불일치 주의 |
| `fluentbit.resources.*` | `fluentbit.resources.*` | 🟢 SAME | |
| `fluentbit.annotations` | `fluentbit.annotations` | 🟢 SAME | exclude/scrape 힌트 |
| `fluentbit.tolerations` / `nodeSelector` / `affinity` | 동일 | 🟢 SAME | |
| `fluentbit.namespaceFluentBitCfgSelector` | `fluentbit.namespaceFluentBitCfgSelector` | 🟢 SAME | |
| *(없음/제한적)* | `fluentbit.namespaceOverride` | 🆕 NEW | FluentBit 리소스 네임스페이스 override |
| *(없음)* | `fluentbit.positionDB.hostPath.path` | 🆕 NEW | 위치 DB 경로(기본 `/var/lib/fluent-bit/`) |
| *(없음)* | `fluentbit.livenessProbe.*` | 🆕 NEW | liveness probe(포트 2020 등) |
| *(없음)* | `fluentbit.serviceMonitor.*` | 🆕 NEW | Prometheus ServiceMonitor |
| *(없음)* | `fluentbit.securityContext` / `podSecurityContext` | 🆕 NEW | 보안 컨텍스트 |
| *(없음)* | `fluentbit.initContainers` | 🆕 NEW | FluentBit용 init 컨테이너 |
| *(없음)* | `fluentbit.command` / `fluentbit.args` | 🆕 NEW | 커맨드/인자 override |
| *(없음)* | `fluentbit.envVars` | 🆕 NEW | 환경변수 |
| *(없음)* | `fluentbit.schedulerName` | 🆕 NEW | 스케줄러 지정 |
| *(없음)* | `fluentbit.additionalVolumes` / `additionalVolumesMounts` | 🆕 NEW | 추가 볼륨 |
| *(없음)* | `fluentbit.ports` | 🆕 NEW | 추가 포트(syslog 등) |
| *(없음)* | `fluentbit.hostNetwork` | 🆕 NEW | 호스트 네트워크 |
| *(없음)* | `fluentbit.disableLogVolumes` | 🆕 NEW | varlibcontainers 등 hostPath 마운트 제거 |

---

## 4. fluentbit.input / filter

| AS-IS (chart 3.2.0) | TO-BE (chart 4.2.0) | 구분 | 비고 |
|---------------------|----------------------|:---:|------|
| `fluentbit.input.tail.enable` | 동일 | 🟢 SAME | |
| `fluentbit.input.tail.memBufLimit` | 동일 | 🟢 SAME | |
| `fluentbit.input.tail.path` | 동일 | 🟢 SAME | `/var/log/containers/*.log` |
| `fluentbit.input.tail.skipLongLines` | 동일 | 🟢 SAME | |
| *(없음)* | `fluentbit.input.tail.bufferChunkSize` / `bufferMaxSize` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.tail.skipEmptyLines` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.tail.readFromHead` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.tail.storageType` (memory/filesystem) | 🆕 NEW | 파일시스템 버퍼 |
| *(없음)* | `fluentbit.input.tail.pauseOnChunksOverlimit` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.tail.refreshIntervalSeconds` | 🆕 NEW | |
| `fluentbit.input.systemd.enable` | 동일 | 🟢 SAME | |
| *(없음)* | `fluentbit.input.systemd.includeKubelet` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.systemd.stripUnderscores` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.systemd.storageType` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.systemd.systemdFilter.*` | 🆕 NEW | |
| *(없음)* | `fluentbit.input.nodeExporterMetrics` / `fluentBitMetrics` | 🆕 NEW | 메트릭 입력 |
| `fluentbit.filter.kubernetes.enable` | 동일 | 🟢 SAME | labels/annotations 포함 |
| `fluentbit.filter.containerd.enable` | 동일 | 🟢 SAME | 런타임 설정과 일관성 확인 |
| `fluentbit.filter.systemd.enable` | 동일 | 🟢 SAME | |
| *(없음)* | `fluentbit.filter.multiline.*` (parsers: go/python/java 등) | 🆕 NEW | 멀티라인 필터 |
| *(없음)* | `fluentbit.filter.kubeedge.*` | 🆕 NEW | KubeEdge 통합 |
| *(없음)* | `fluentbit.parsers.javaMultiline.enable` | 🆕 NEW | Java 멀티라인 파서 |
| *(없음)* | `fluentbit.namespaceClusterFbCfg` | 🆕 NEW | configmap/secret 배포 네임스페이스 |

---

## 5. fluentbit.output

| AS-IS (chart 3.2.0) | TO-BE (chart 4.2.0) | 구분 | 비고 |
|---------------------|----------------------|:---:|------|
| `fluentbit.output.es.enable` / `host` / `port` / `logstashPrefix` | 동일 | 🟢 SAME | ES 기본 |
| *(없음)* | `fluentbit.output.es.bufferSize` / `traceError` | 🆕 NEW | |
| `fluentbit.output.kafka.enable` / `brokers` | 동일 | 🟢 SAME | (AS-IS의 `topics`/`topicKey` 확인) |
| `fluentbit.output.loki.enable` / `host` / `port` | 동일 | 🟢 SAME | |
| *(없음)* | `fluentbit.output.loki.retryLimit` | 🆕 NEW | |
| *(없음)* | `fluentbit.output.opensearch` | 🆕 NEW | OpenSearch 출력 |
| *(없음)* | `fluentbit.output.opentelemetry` | 🆕 NEW | OTel 출력 |
| *(없음)* | `fluentbit.output.stdout.enable` | 🆕 NEW | |
| *(없음)* | `fluentbit.output.stackdriver` | 🆕 NEW | |
| *(없음)* | `fluentbit.output.prometheusMetricsExporter` | 🆕 NEW | |
| *(없음)* | `fluentbit.service.storage` (filesystem 버퍼) | 🆕 NEW | |
| *(없음)* | `fluentbit.service.schedulerBase` / `schedulerCap` | 🆕 NEW | 재시도 백오프 |

---

## 6. fluentd 블록 (사용 시)

| AS-IS (chart 3.2.0) | TO-BE (chart 4.2.0) | 구분 | 비고 |
|---------------------|----------------------|:---:|------|
| `fluentd.enable` | `fluentd.enable` | 🟢 SAME | 기본 false |
| `fluentd.name` | `fluentd.name` | 🟢 SAME | |
| `fluentd.image.repository:` <br>`kubesphere/fluentd` | `fluentd.image.repository:` <br>`fluent/fluent-operator/fluentd` | 🟠 CHANGED | **레지스트리/경로 변경** |
| *(레지스트리 분리 없음)* | `fluentd.image.registry: ghcr.io` | 🆕 NEW | |
| `fluentd.image.tag: v1.15.x` | `fluentd.image.tag: v1.19.2` | 🟡 CHANGED | Fluentd 버전 상승 |
| `fluentd.replicas` | `fluentd.replicas` | 🟢 SAME | collector 모드에만 적용 |
| `fluentd.forward.port` | `fluentd.forward.port` | 🟢 SAME | |
| `fluentd.watchedNamespaces` | `fluentd.watchedNamespaces` | 🟢 SAME | |
| `fluentd.resources.*` | `fluentd.resources.*` | 🟢 SAME | |
| *(없음)* | `fluentd.mode` (collector/agent) | 🆕 NEW | StatefulSet/DaemonSet 선택 |
| *(없음)* | `fluentd.port` | 🆕 NEW | |
| *(없음)* | `fluentd.schedulerName` | 🆕 NEW | |
| *(없음)* | `fluentd.envVars` | 🆕 NEW | |
| *(없음)* | `fluentd.podSecurityContext` / `securityContext` | 🆕 NEW | |
| *(없음)* | `fluentd.priorityClassName` | 🆕 NEW | |
| *(없음)* | `fluentd.logLevel` | 🆕 NEW | |
| *(없음)* | `fluentd.extras` | 🆕 NEW | 추가 설정 |
| `fluentd.output.es.*` (host/port/logstashPrefix/buffer) | 동일 | 🟢 SAME | |
| `fluentd.output.kafka.*` (brokers/topicKey/buffer) | 동일 | 🟢 SAME | |
| *(없음)* | `fluentd.output.opensearch` | 🆕 NEW | |
| *(없음)* | `fluentd.forward.retainMetadataInForwardMode` | 🆕 NEW | forward 메타데이터 유지 |

---

## 7. AS-IS values를 그대로 넣었을 때 — 즉시 조치 필요 항목만 (핵심 요약)

| AS-IS 키 | 무슨 일이 | TO-BE 조치 |
|----------|-----------|------------|
| `operator.initcontainer.*` | 무시(no-op) | 삭제 |
| `operator.container.repository/tag` | 무시 → 기본 이미지로 뜸 | `operator.image.repository/tag` (+`registry`) |
| `logPath.*` | 무시 → 경로 지정 안 됨 | `containerRuntime` 로 대체 |
| *(docker 런타임 가정)* | **로그 수집 실패 가능** | `containerRuntime: docker`/`crio` 명시 |
| `fluentbit.image.repository: kubesphere/*` | pull 실패/구버전 | `fluent/fluent-operator/fluent-bit` (+`registry: ghcr.io`) |
| `fluentbit.image.tag: 3.x` | 버전 불일치 | 태그 고정 해제 또는 5.0.x |
| `fluentd.image.repository: kubesphere/*` | pull 실패/구버전 | `fluent/fluent-operator/fluentd` |
| `fluentbit-crds.*` / `fluentd-crds.*` | 무시 | 별도 CRD 차트로 관리 |
| *(CRD 자동 갱신 기대)* | **CRD 미갱신 / 삭제 위험** | 수동 apply 또는 CRD 차트 설치 |

---

## 8. 최소 변환 예시 (before → after 발췌)

**AS-IS (chart 3.2.0)**
```yaml
logPath:
  containerd: /var/log/containers
operator:
  initcontainer:
    repository: "docker"
    tag: "20.10"
  container:
    repository: "kubesphere/fluent-operator"
    tag: "v3.2.0"
fluentbit:
  image:
    repository: "kubesphere/fluent-bit"
    tag: "v2.1.10"
fluentd:
  enable: true
  image:
    repository: "kubesphere/fluentd"
    tag: "v1.15.3"
```

**TO-BE (chart 4.2.0)**
```yaml
containerRuntime: containerd        # docker/cri-o면 해당 값으로
operator:
  image:
    registry: ghcr.io
    repository: fluent/fluent-operator/fluent-operator
    tag: ""                         # 비우면 chart appVersion(v3.9.0)
fluentbit:
  image:
    registry: ghcr.io
    repository: fluent/fluent-operator/fluent-bit
    tag: "5.0.6"
fluentd:
  enable: true
  image:
    registry: ghcr.io
    repository: fluent/fluent-operator/fluentd
    tag: v1.19.2
# CRD는 values가 아니라 별도 차트/수동 apply로 관리
```

---

*본 대조표는 fluent/helm-charts chart 4.2.0 values.yaml 원문(671줄)과, 구 fluent-operator chart 3.2.0 계열 values.yaml 구조(kubesphere 이미지·initcontainer·logPath 기반)를 대조한 것입니다. AS-IS 측 일부 키는 사용 중이던 정확한 3.2.x 패치·커스터마이즈에 따라 다를 수 있으니, `helm get values`로 실제 값을 추출해 좌측과 1:1 대조하시길 권장합니다. 출처: fluent/helm-charts·fluent/fluent-operator values.yaml, GitHub issue #652, Verrazzano 문서, MIGRATION-v4.md (2026-07 기준).*
