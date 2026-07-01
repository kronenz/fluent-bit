# Fluent Operator — 버전별 기능 비교 + 기능 설명 + 운영 영향도 평가 (v3.2.0 → v3.9.0)

> **현재 사용:** v3.2.0 (표에서 `〔현재〕` 표시)  ·  **최신:** v3.9.0 = Helm Chart 4.2.0
> **문서 목적:** 기존 로그 파이프라인(Fluent Bit DaemonSet + Input/Filter/Output 구성)을 운영 중인 상태에서 업그레이드할 때, 어떤 변경이 실제 수집·전송에 영향을 주는지 **영향도 레벨**로 판단할 수 있게 정리.

---

## 영향도 레벨 정의

| 레벨 | 표기 | 의미 | 대응 |
|------|------|------|------|
| **치명** | 🔴 CRITICAL | 조치 없이 업그레이드하면 로그 유실·수집 중단·리소스 삭제 가능 | 사전 백업·마이그레이션 절차 필수, 반드시 스테이징 검증 |
| **주의** | 🟠 HIGH | 동작은 하지만 기본값/스키마 변경으로 기존 설정이 무효화되거나 다르게 동작 | values.yaml 변환·재검증 필요 |
| **경미** | 🟡 MEDIUM | 대체로 하위호환. 새 기능이며 켜지 않으면 기존 동작 유지 | 선택 적용, 회귀 테스트 권장 |
| **안전** | 🟢 LOW | 순수 추가 기능·내부 개선. 기존 파이프라인에 영향 없음 | 조치 불필요 |

> ※ 아래 각 챕터의 표에 **영향도** 열을 추가했습니다. 영향도는 "v3.2.0 파이프라인을 운영하다가 최신으로 올릴 때" 기준입니다.

### 범례 (지원 상태)

| 기호 | 의미 |
|------|------|
| ● 지원 | ＋ 이 버전에서 추가 | ✕ 제거/폐기 | ◐ 변경/대체 | – 미지원 |

> ※ 3.4.0은 주로 CRD 서브차트 정렬·의존성 업데이트라 표에서는 3.3.0 / 3.5.0 사이로 흡수했습니다.

---

## 0. 업그레이드 영향도 한눈에 보기 (Executive Summary)

| 영향도 | 대표 변경 | 무엇이 위험한가 |
|--------|-----------|-----------------|
| 🔴 CRITICAL | CRD 메인차트 → 별도차트 분리 | `helm upgrade`가 CRD를 자동 갱신하지 않음. 잘못 처리 시 기존 `ClusterOutput`/`Filter` 등 **커스텀 리소스가 삭제**되어 파이프라인 정의가 통째로 사라질 수 있음 |
| 🔴 CRITICAL | Fluent Bit 3.1.7 → 5.0.x (메이저 2단계) | 플러그인 파라미터·기본값 변경 가능. 특정 output/filter가 **조용히 동작을 멈추거나 설정 파싱 실패로 파드 크래시** 가능 |
| 🟠 HIGH | 기본 containerRuntime docker → containerd | docker/cri-o 클러스터에서 명시 안 하면 **로그 경로 오인식으로 수집이 안 될 수 있음** |
| 🟠 HIGH | init container 제거 → env ConfigMap | 로그 경로 주입 방식이 바뀜. 커스텀 경로 사용 시 재확인 필요 |
| 🟠 HIGH | 차트 값 `operator.container.*` → `operator.image.*` | 기존 values.yaml의 이미지 지정 키가 **무효화**되어 의도한 이미지가 안 뜰 수 있음 |
| 🟡 MEDIUM | 보안 하드닝(readOnlyRootFilesystem 등, 4.x 계열) | 임의 경로 쓰기를 가정한 설정은 volume 마운트 필요 |
| 🟢 LOW | 신규 output/filter/input 파라미터 다수 | 켜지 않으면 기존 동작 유지 |

---

## 1. 차트 구조 · 배포 방식 (Breaking 중심)

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.3.0 | 3.5.0 | 3.6.0 | 3.7.0 | 3.8.0 | 3.9.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| CRD가 메인 차트에 내장 | 🔴 | ● | ● | ● | ✕ | – | – | – |
| CRD 별도 top-level 차트로 분리 | 🔴 | – | – | – | ＋ | ● | ● | ● |
| init container로 로그경로 탐지 | 🟠 | ● | ● | ● | ✕ | – | – | – |
| env ConfigMap 방식(CONTAINER_LOG_PATH) | 🟠 | – | – | – | ＋ | ● | ● | ● |
| 기본 containerRuntime = docker | 🟠 | ● | ● | ● | ◐ | – | – | – |
| 기본 containerRuntime = containerd | 🟠 | – | – | – | ＋ | ● | ● | ● |
| 이미지 값 구조 `operator.image.*` 통합 | 🟠 | – | – | ＋ | ● | ● | ● | ● |
| `logPath` 옵션 | 🟠 | ● | ● | ● | ✕ | – | – | – |

**항목 설명 및 영향**

- **CRD 내장 → 별도 차트 분리 〔🔴 CRITICAL〕** — CRD(`ClusterOutput`, `Filter` 등의 스키마 정의)를 별도 차트로 떼어냈습니다. Helm은 `helm upgrade` 시 CRD를 자동 갱신하지 않으므로, 아무 조치 없이 올리면 신규 필드가 반영 안 되거나, 반대로 CRD를 지우면 **해당 CRD의 모든 커스텀 리소스(=파이프라인 정의)가 연쇄 삭제**됩니다.
  - **조치:** 업그레이드 전 `kubectl get clusteroutput,clusterfilter,... -A -o yaml`로 백업 → CRD를 수동 `kubectl apply --server-side` 하거나 별도 CRD 차트를 `resource-policy: keep`로 설치. 절대 `helm uninstall`로 CRD를 날리지 말 것.
- **init container 제거 → env ConfigMap 〔🟠 HIGH〕** — 로그 경로 탐지 방식이 바뀝니다. 표준 경로를 쓰면 문제 없지만, 커스텀 로그 경로를 init container 전제로 구성했다면 재확인이 필요합니다.
- **기본 containerRuntime docker → containerd 〔🟠 HIGH〕** — **가장 흔한 실수 포인트**입니다. docker나 cri-o 런타임 클러스터에서 기본값(containerd)을 그대로 쓰면 로그 파일 경로/포맷을 잘못 잡아 **수집이 조용히 실패**할 수 있습니다.
  - **조치:** 런타임 확인 후 `--set containerRuntime=docker` (또는 `crio`) 명시.
- **이미지 값 `operator.container.*` → `operator.image.*` 〔🟠 HIGH〕** — 기존 values.yaml에서 이미지를 커스텀(사내 레지스트리 등)했다면 옛 키가 **무시**되어 의도한 이미지가 안 뜹니다.
  - **조치:** `operator.image.{registry,repository,tag}` 구조로 값 이전.
- **`logPath` 옵션 제거 〔🟠 HIGH〕** — containerRuntime 변경과 짝. 옛 `logPath` 키를 쓰고 있었다면 무효가 되므로 런타임 지정 방식으로 옮겨야 합니다.

---

## 2. 운영 · 보안 · 차트 옵션

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.3.0 | 3.5.0 | 3.6.0 | 3.7.0 | 3.8.0 | 3.9.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| FluentBit livenessProbe 템플릿 | 🟡 | – | ＋ | ● | ● | ● | ● | ● |
| operator ServiceMonitor | 🟢 | – | – | – | – | – | ＋ | ● |
| RBAC 생성 비활성화 옵션 | 🟢 | – | – | – | – | – | ＋ | ● |
| cluster-role 추가 RBAC 구성 | 🟢 | – | – | – | ＋ | ● | ● | ● |
| SA/ClusterRole/Binding 이름 변경 | 🟡 | – | – | – | ＋ | ● | ● | ● |
| fluent-bit 포트 구성(operator 경유) | 🟢 | – | – | – | ＋ | ● | ● | ● |
| `scheduler.base` / `scheduler.cap` | 🟢 | – | – | – | ＋ | ● | ● | ● |
| daemonset/statefulset rollout restart | 🟡 | – | – | – | – | – | ＋ | ● |
| HostAliases 지원 | 🟢 | – | – | – | – | – | ＋ | ● |
| 커스텀 positionDB | 🟡 | – | – | – | – | – | ＋ | ● |
| namespaceOverride (FluentBit 차트) | 🟢 | – | – | – | – | – | ＋ | ● |
| FluentBit args/command 노출 | 🟢 | – | – | – | – | – | ＋ | ● |
| FluentBit annotation(operator 값) | 🟢 | – | – | – | – | – | – | ＋ |
| (참고) 보안 하드닝: readOnlyRootFilesystem 등 | 🟡 | – | – | ◐ | ● | ● | ● | ● |

**항목 설명 및 영향**

- **FluentBit livenessProbe 〔🟡 MEDIUM〕** — 헬스체크로 멈춘 수집기를 자동 재시작. 이점이 크지만, 프로브 임계값(timeout/failureThreshold)이 부적절하면 정상 파드가 재시작될 수 있어 값 점검 권장.
- **operator ServiceMonitor / RBAC 비활성화 / 추가 RBAC / 이름 변경 〔🟢~🟡〕** — 대부분 선택형 옵션이라 켜지 않으면 기존 동작 유지. 단 SA/Role 이름을 바꾸면 기존에 그 이름을 참조하던 리소스와의 정합성 확인 필요(🟡).
- **`scheduler.base`/`scheduler.cap` 〔🟢 LOW〕** — 재시도 백오프 튜닝. 미설정 시 기본 동작 유지.
- **rollout restart 〔🟡 MEDIUM〕** — 설정 변경 시 파드 순차 재시작. 대규모 DaemonSet에서 한꺼번에 재시작되면 순간적으로 수집 공백이 생길 수 있어 롤아웃 전략 확인 권장.
- **커스텀 positionDB 〔🟡 MEDIUM〕** — 읽기 위치 DB 경로 지정. 경로를 잘못 바꾸면 재시작 후 **로그를 처음부터 다시 읽거나(중복) 건너뛸(누락)** 수 있어 주의.
- **HostAliases / namespaceOverride / args·command / annotation 〔🟢 LOW〕** — 순수 추가 옵션. 미사용 시 영향 없음.
- **보안 하드닝(readOnlyRootFilesystem 등) 〔🟡 MEDIUM〕** — 4.x 계열에서 루트 파일시스템이 읽기전용이 됨. 임의 경로에 파일을 쓰던 커스텀 설정(예: 특정 위치의 버퍼/positionDB)은 **쓰기 실패**할 수 있어 volume 마운트 추가 필요.

---

## 3. Input · Filter 기능

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.3.0 | 3.5.0 | 3.6.0 | 3.7.0 | 3.8.0 | 3.9.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| tail input: `bufferChunkSize` | 🟢 | – | – | ＋ | ● | ● | ● | ● |
| tail input: `offsetKey` | 🟢 | – | – | – | – | – | ＋ | ● |
| tail input: skip empty lines | 🟢 | – | – | – | – | – | ＋ | ● |
| tail/systemd input: `storage.path` | 🟡 | – | – | – | – | – | ＋ | ● |
| syslog input: `Tag` 파라미터 | 🟢 | – | – | – | ＋ | ● | ● | ● |
| filter: `enable_flb_null` | 🟢 | – | – | – | ＋ | ● | ● | ● |
| filter: `multiline_buffer_limit` | 🟡 | – | – | – | – | ＋ | ● | ● |
| grep filter: `logical_op` | 🟡 | – | – | – | – | – | ＋ | ● |
| lua filter: `type_array_key` / 네임스페이스 CRD | 🟢 | – | – | – | – | – | ＋ | ● |

**항목 설명 및 영향**

- **`bufferChunkSize` / `offsetKey` / skip empty lines / syslog `Tag` / `enable_flb_null` / lua 확장 〔🟢 LOW〕** — 모두 명시적으로 설정할 때만 동작하는 추가 파라미터. 기존 파이프라인에 영향 없음.
- **`storage.path` (filesystem 버퍼) 〔🟡 MEDIUM〕** — 메모리→파일시스템 버퍼로 바꾸는 옵션. 유실 방지에 유리하지만, 경로·용량을 잘못 잡으면 디스크 압박이나 보안 하드닝(readOnly FS)과 충돌할 수 있어 volume 설계와 함께 검토.
- **`multiline_buffer_limit` 〔🟡 MEDIUM〕** — 멀티라인 병합 버퍼 상한. 기존에 멀티라인 필터를 쓰고 있었다면, 상한 도입으로 아주 긴 스택트레이스가 잘릴 가능성이 있어 값 확인 권장.
- **grep `logical_op` 〔🟡 MEDIUM〕** — 필터 조건 결합 방식. 기존 grep 규칙을 재작성해 적용할 경우 필터 로직이 바뀌므로 결과 검증 필요.

---

## 4. Output 플러그인

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.3.0 | 3.5.0 | 3.6.0 | 3.7.0 | 3.8.0 | 3.9.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| ES: `reload_after` / `sniffer_class_name` | 🟡 | – | ＋ | ● | ● | ● | ● | ● |
| loki: `retry_limit` (기본 output) | 🟡 | – | ＋ | ● | ● | ● | ● | ● |
| loki: structured metadata | 🟡 | – | – | – | – | – | ＋ | ● |
| opensearch: 파라미터 확장 | 🟢 | – | – | – | – | ＋ | ● | ● |
| http: `storage.total_limit_size` | 🟡 | – | – | – | – | ＋ | ● | ● |
| OpenTelemetry: `storage.total_limit_size` | 🟡 | – | – | – | ＋ | ● | ● | ● |
| OpenTelemetry: `logs_body_key` | 🟢 | – | – | – | – | – | ＋ | ● |
| stackdriver: `text_payload_key` | 🟢 | – | – | – | – | – | ＋ | ● |
| syslog output: `workers` | 🟡 | – | – | – | – | – | ＋ | ● |
| kafka: `rdkafka_group` (rdkafka gem) | 🟡 | – | – | – | – | ＋ | ● | ● |
| forward: `retainMetadataInForwardMode` | 🟡 | – | – | – | – | – | – | ＋ |
| firehose: 추가 설정 | 🟢 | – | – | – | – | – | – | ＋ |
| Fluentd: null output 플러그인 | 🟢 | – | – | – | – | – | ＋ | ● |
| Fluentd: `pluginSortOrder` | 🟢 | – | – | – | – | – | ＋ | ● |

> **⚠ 공통 주의 〔🔴 간접〕** — 이 표의 output들은 모두 Fluent Bit 3.1.7 → 5.0.x 메이저 업그레이드의 영향을 받습니다. 파라미터가 추가된 것과 별개로, **기존 output의 기본값·필수 파라미터가 5.x에서 바뀌었을 수 있어** 업그레이드 후 각 백엔드(ES/Loki/Kafka 등)로 실제 로그가 들어오는지 엔드투엔드 검증이 필요합니다.

**항목 설명 및 영향**

- **ES `reload_after`/`sniffer_class_name`, loki `retry_limit` 〔🟡 MEDIUM〕** — 기존에 쓰던 ES/Loki output이라면, 이 파라미터를 도입할 때 연결 재설정·재시도 동작이 바뀌므로 전송 안정성에 영향. 도입 시 부하 테스트 권장.
- **loki structured metadata 〔🟡 MEDIUM〕** — Loki 3.x 필요. 백엔드 Loki 버전이 낮으면 오히려 전송 실패 원인이 될 수 있어 백엔드 호환성 확인 필수.
- **http/OTel `storage.total_limit_size` 〔🟡 MEDIUM〕** — 버퍼 상한 도입. 상한이 너무 작으면 백엔드 지연 시 **로그가 드롭**되고, 없으면 디스크가 참. 트래픽에 맞게 산정 필요.
- **syslog `workers`, kafka `rdkafka_group` 〔🟡 MEDIUM〕** — 병렬/라이브러리 변경은 처리량을 높이지만 순서 보장·리소스 사용에 영향을 줄 수 있어 검증 권장.
- **forward `retainMetadataInForwardMode` 〔🟡 MEDIUM〕** — Fluent Bit→Fluentd 2계층 구성일 때 메타데이터 유지. 켜면 다운스트림 Fluentd의 라우팅/필드 처리가 달라질 수 있어 양쪽 함께 검증.
- **opensearch 확장 / OTel `logs_body_key` / stackdriver `text_payload_key` / firehose / null output / pluginSortOrder 〔🟢 LOW〕** — 신규·선택 파라미터. 미사용 시 영향 없음.

---

## 5. 번들 이미지 · 런타임

| 구성요소 | 영향도 | 3.2.0〔현재〕 | 3.3.0 | 3.5.0 | 3.6.0 | 3.7.0 | 3.8.0 | 3.9.0 |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Fluent Bit** | 🔴 | 3.1.7 | 3.2.5 | 4.0.x | 4.2.2 | 4.2.3 | 4.2.x | 5.0.x |
| **Fluentd** | 🟡 | v1.16 | v1.17.1 | v1.17 | v1.19.1 | v1.19.2 | v1.19.2 | v1.19.2 |
| **Go** | 🟢 | 1.22 | 1.23 | 1.24 | 1.25.3 | 1.25 | 1.25 | 1.26.3 |

**항목 설명 및 영향**

- **Fluent Bit 3.1.7 → 5.0.x 〔🔴 CRITICAL〕** — 로그 수집 엔진 자체의 메이저 2단계 업그레이드. YAML 설정 정식화·blob·eBPF 등 신기능과 함께 **플러그인 파라미터/기본값 변경, 일부 동작 변화**가 포함될 수 있습니다. 특정 input/filter/output이 조용히 멈추거나, 설정 파싱 실패로 파드가 크래시할 수 있는 **가장 광범위한 영향원**입니다.
  - **조치:** 스테이징에서 실제 설정으로 기동 확인 → 각 백엔드 수집 검증 → classic/yaml 설정 포맷 사용 시 파싱 이슈 점검(과거 3.3.0에서 YAML+리스트 파싱 버그 사례 있음).
- **Fluentd v1.16 → v1.19.2 〔🟡 MEDIUM〕** — 2계층(Fluentd) 구성을 쓸 때 해당. 플러그인 호환성 확인 권장. Fluent Bit만 쓰는 경우 영향 적음.
- **Go 버전 〔🟢 LOW〕** — 오퍼레이터 빌드 런타임. 사용자 설정과 무관.

---

## 6. 결론 — 현재 v3.2.0 대비 최신 v3.9.0의 차이 + 영향도

| 구분 | v3.2.0 (현재) | v3.9.0 / Chart 4.2.0 (최신) | 영향도 |
|------|---------------|------------------------------|:---:|
| **패키징** | CRD 내장, init container 사용 | CRD 별도 차트 분리, init container 제거·env ConfigMap | 🔴 |
| **기본 런타임** | docker (`logPath` 지정) | containerd (`logPath` 제거) | 🟠 |
| **차트 값** | `operator.container.*` | `operator.image.*` 로 통합 | 🟠 |
| **Fluent Bit** | 3.1.7 | 5.0.x (메이저 2단계↑, YAML·blob·eBPF 등) | 🔴 |
| **Fluentd** | v1.16 | v1.19.2 (null output, pluginSortOrder) | 🟡 |
| **Output** | ES/loki 기본 수준 | opensearch·http·OTel·firehose·forward·syslog workers 등 대폭 확장 | 🟡 |
| **Filter/Input** | 기본 | multiline_buffer_limit·grep logical_op·offsetKey·storage.path 등 추가 | 🟡 |
| **운영/보안** | 제한적 | ServiceMonitor·RBAC·rollout restart·HostAliases·probe·하드닝 | 🟡 |
| **안정성** | – | logfmt/parser 크래시 방지, namespace 필터링·파라미터명 다수 수정 | 🟢 |

---

## 7. 운영 관점 업그레이드 절차 (영향도 기반)

### 7.1. 사전 백업 〔🔴 필수〕
```bash
# 파이프라인 정의(커스텀 리소스) 전체 백업 — CRD 삭제 사고 대비
kubectl get clusteroutput,clusterfilter,clusterinput,clusterparser -A -o yaml > backup-cr.yaml
kubectl get fluentbit,fluentd -A -o yaml > backup-fluent.yaml
# 현재 사용 중인 values 백업 — 값 스키마 변환 대비
helm get values fluent-operator -n fluent > values-3.2.0.yaml
```

### 7.2. values.yaml 변환 점검 〔🟠 필수〕
- `operator.container.*` → `operator.image.*` 이전
- `operator.initcontainer.*`, `logPath.*` 키 제거
- `containerRuntime` 값 재확인(docker/cri-o면 명시)
- CRD 서브차트 값(`fluentbit-crds.*` 등) 제거 → CRD 별도 관리로 전환

### 7.3. CRD 처리 〔🔴 필수, 둘 중 택1〕
```bash
# 방법 A) 수동 관리
helm pull fluent/fluent-operator --version 4.2.0 --untar
kubectl apply --server-side --force-conflicts -f fluent-operator/crds/

# 방법 B) CRD 별도 차트로 Helm 관리 (권장, 삭제 방지)
helm install fluent-operator-fluent-bit-crds fluent/fluent-operator-fluent-bit-crds -n fluent \
  --set additionalAnnotations."helm\.sh/resource-policy"=keep
helm install fluent-operator-fluentd-crds fluent/fluent-operator-fluentd-crds -n fluent \
  --set additionalAnnotations."helm\.sh/resource-policy"=keep
```

### 7.4. 업그레이드 & 검증 〔🔴 필수〕
```bash
helm upgrade fluent-operator fluent/fluent-operator --version 4.2.0 -n fluent -f values-4.x.yaml
```
검증 체크리스트:
- [ ] 🔴 오퍼레이터/DaemonSet 파드 Running, 재시작 루프 없음
- [ ] 🔴 기존 `ClusterOutput`/`Filter` 등 커스텀 리소스가 그대로 존재
- [ ] 🔴 각 백엔드(ES/Loki/Kafka 등)에 로그가 실제로 들어오는지 엔드투엔드 확인
- [ ] 🟠 docker/cri-o 클러스터라면 로그 경로 정상 인식 확인
- [ ] 🟡 readOnlyRootFilesystem로 인한 쓰기 실패 로그 없음(필요 시 volume 추가)
- [ ] 🟡 멀티라인/grep 필터 결과가 기존과 동일한지 샘플 비교

### 7.5. 롤백 준비 〔🔴 필수〕
- 백업한 `values-3.2.0.yaml`, `backup-cr.yaml` 보관
- 문제 발생 시 이전 차트 버전으로 `helm rollback` + CRD/CR 복원 경로 사전 확인

---

## 8. 권장 업그레이드 전략

Fluent Bit 메이저 2단계(3→4→5)와 차트 v3→v4가 한꺼번에 걸리므로, **단번에 3.2.0 → 4.2.0으로 점프하기보다** 가능하면 중간 단계(예: v4 진입 시점인 3.6.0 계열)를 경유해 Breaking 변경을 나눠 검증하는 것이 안전합니다. 특히 프로덕션은 반드시 스테이징에서 동일 설정으로 먼저 재현·검증 후 적용하세요.

---

*출처: fluent/fluent-operator GitHub Releases·CHANGELOG.md, fluent/helm-charts README·MIGRATION-v4.md, fluentbit.io 릴리즈 공지 (2026-07 기준). 영향도 레벨은 일반적인 로그 파이프라인(Fluent Bit DaemonSet + CRD 기반 Input/Filter/Output) 운영을 가정한 판단이며, 실제 영향은 각 환경의 설정·백엔드·런타임에 따라 달라질 수 있습니다. 적용 전 해당 버전의 원문 릴리즈 노트와 values.yaml을 반드시 대조하시기 바랍니다.*
