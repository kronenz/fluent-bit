# Fluent Operator Helm Chart — 버전별 기능 비교 + 기능 설명 + 운영 영향도 (Chart 3.2.0 → 4.2.0)

> **현재 사용:** Helm Chart 3.2.0 (표에서 `〔현재〕` 표시)  ·  **최신:** Helm Chart 4.2.0
> **문서 목적:** 기존 로그 파이프라인(Fluent Bit DaemonSet + Input/Filter/Output 구성)을 운영 중인 상태에서 **Helm Chart를 3.2.0 → 4.2.0으로 업그레이드**할 때, 어떤 변경이 실제 수집·전송에 영향을 주는지 **영향도 레벨**로 판단할 수 있게 정리.

---

## 0. 먼저 알아야 할 것 — 버전 체계와 저장소 이관

이 업그레이드는 단순 버전 상승이 아니라 **차트 저장소 이관 + v4 재편**을 동시에 관통합니다.

| 구간 | Chart 버전 | 제공 저장소 | Chart : Operator(appVersion) 관계 |
|------|-----------|-------------|-----------------------------------|
| 구(舊) | 3.2.0 ~ 3.7.0 | `fluent/fluent-operator` 저장소 내장 차트 | Chart 버전 = Operator 버전 (동일) |
| 신(新) | 4.0.0 ~ 4.2.0 | `fluent/helm-charts` 저장소로 이관 | Chart 4.x ↔ Operator 3.8~3.9 (분리) |

- **Chart 3.x → 4.x의 "메이저" 점프는 Operator 애플리케이션이 4.0이 되어서가 아니라, 차트 패키징이 v4 구조(CRD 분리 등)로 재편됐기 때문**입니다. Chart 4.2.0의 내부 appVersion은 Operator **v3.9.0**입니다.
- 최신 차트는 OCI(`oci://ghcr.io/fluent/helm-charts/fluent-operator`)로도 배포되며 Cosign 서명 검증을 지원합니다. 기존 `https://fluent.github.io/helm-charts/` repo 방식도 유지됩니다.

### Chart 버전 ↔ 내부 구성 매핑

| Chart | 릴리즈 | appVersion(Operator) | Fluent Bit | Fluentd | 성격 |
|-------|--------|----------------------|-----------|---------|------|
| **3.2.0** 〔현재〕 | 2024-08 | v3.2.0 | 3.1.7 | v1.16 | 기준점 |
| 3.3.0 | 2024 하반기 | v3.3.0 | 3.2.5 | v1.17.1 | configFileFormat 등 |
| 3.4.0 | 2025 상반기 | v3.4.0 | 3.2.x | v1.17 | CRD 서브차트 정렬 |
| 3.5.0 | 2025 중반 | v3.5.0 | 4.0.x | v1.17 | Fluent Bit 4.x, 이미지 값 정리 |
| 3.6.0 / 3.7.0 | 2026 초 | v3.6~3.7 | 4.2.x | v1.19 | 구 저장소 마지막 계열 |
| **4.0.0** | 2026 초 | v3.x | 4.x | v1.19 | **v4 재편(CRD 분리 등) — Breaking** |
| **4.1.0** | 2026-05 | v3.8.0 | 5.0.x | v1.19.2 | probe·보안 하드닝 |
| **4.2.0** ◆ | 2026-06-09 | v3.9.0 | 5.0.6 | v1.19.2 | 최신. forward/firehose 등 |

> ※ 구 저장소(3.x)와 신 저장소(4.x)는 릴리즈 채널이 다르므로, 실제 업그레이드 시 `helm repo update` 후 4.x 차트를 받아야 합니다.

---

## 영향도 레벨 정의

| 레벨 | 표기 | 의미 | 대응 |
|------|------|------|------|
| **치명** | 🔴 CRITICAL | 조치 없이 업그레이드하면 로그 유실·수집 중단·리소스 삭제 가능 | 사전 백업·마이그레이션 절차 필수, 반드시 스테이징 검증 |
| **주의** | 🟠 HIGH | 동작은 하지만 기본값/스키마 변경으로 기존 설정이 무효화되거나 다르게 동작 | values.yaml 변환·재검증 필요 |
| **경미** | 🟡 MEDIUM | 대체로 하위호환. 새 기능이며 켜지 않으면 기존 동작 유지 | 선택 적용, 회귀 테스트 권장 |
| **안전** | 🟢 LOW | 순수 추가 기능·내부 개선. 기존 파이프라인에 영향 없음 | 조치 불필요 |

### 범례 (지원 상태)

| 기호 | 의미 |
|------|------|
| ● 지원 | ＋ 이 버전에서 추가 | ✕ 제거/폐기 | ◐ 변경/대체 | – 미지원 |

> ※ 이후 표의 열은 Chart 버전입니다: **3.2.0(현재) · 3.4.0 · 3.6.0 · 4.0.0 · 4.1.0 · 4.2.0(최신)**. (3.3.0/3.5.0/3.7.0은 인접 열로 흡수)

---

## 1. 업그레이드 영향도 한눈에 보기 (Executive Summary)

| 영향도 | 대표 변경 | 발생 Chart | 무엇이 위험한가 |
|--------|-----------|-----------|-----------------|
| 🔴 CRITICAL | CRD 메인차트 → 별도차트 분리 | **4.0.0** | `helm upgrade`가 CRD를 자동 갱신 안 함. 잘못 처리 시 기존 `ClusterOutput`/`Filter` 등 **커스텀 리소스가 삭제**되어 파이프라인 정의가 통째로 사라질 수 있음 |
| 🔴 CRITICAL | Fluent Bit 3.1.7 → 5.0.6 (메이저 2단계) | 3.5.0/4.1.0 | 플러그인 파라미터·기본값 변경 가능. 특정 output/filter가 **조용히 멈추거나 설정 파싱 실패로 파드 크래시** 가능 |
| 🟠 HIGH | 기본 containerRuntime docker → containerd | **4.0.0** | docker/cri-o 클러스터에서 명시 안 하면 **로그 경로 오인식으로 수집 실패** 가능 |
| 🟠 HIGH | init container 제거 → env ConfigMap | **4.0.0** | 로그 경로 주입 방식 변경. 커스텀 경로 사용 시 재확인 필요 |
| 🟠 HIGH | 차트 값 `operator.container.*` → `operator.image.*` | 3.5.0 | 기존 values.yaml 이미지 키가 **무효화**되어 의도한 이미지가 안 뜰 수 있음 |
| 🟠 HIGH | 차트 저장소 이관 (fluent-operator → helm-charts) | 4.0.0 | repo/차트 경로가 바뀜. 배포 파이프라인(ArgoCD/Flux 등) 소스 갱신 필요 |
| 🟡 MEDIUM | 보안 하드닝(readOnlyRootFilesystem 등) | 4.1.0 | 임의 경로 쓰기를 가정한 설정은 volume 마운트 필요 |
| 🟢 LOW | 신규 output/filter/input 파라미터 다수 | 전반 | 켜지 않으면 기존 동작 유지 |

---

## 2. 차트 구조 · 배포 방식 (Breaking 중심)

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.4.0 | 3.6.0 | 4.0.0 | 4.1.0 | 4.2.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| CRD가 메인 차트에 내장 | 🔴 | ● | ● | ● | ✕ | – | – |
| CRD 별도 top-level 차트로 분리 | 🔴 | – | – | – | ＋ | ● | ● |
| init container로 로그경로 탐지 | 🟠 | ● | ● | ● | ✕ | – | – |
| env ConfigMap 방식(CONTAINER_LOG_PATH) | 🟠 | – | – | – | ＋ | ● | ● |
| 기본 containerRuntime = docker | 🟠 | ● | ● | ● | ◐ | – | – |
| 기본 containerRuntime = containerd | 🟠 | – | – | – | ＋ | ● | ● |
| 이미지 값 구조 `operator.image.*` 통합 | 🟠 | – | – | ● | ● | ● | ● |
| `logPath` 옵션 | 🟠 | ● | ● | ● | ✕ | – | – |
| 차트 저장소: helm-charts로 이관 | 🟠 | – | – | – | ＋ | ● | ● |
| OCI 배포 + Cosign 서명 검증 | 🟢 | – | – | – | ＋ | ● | ● |

**항목 설명 및 영향**

- **CRD 내장 → 별도 차트 분리 〔🔴 CRITICAL / Chart 4.0.0〕** — CRD(`ClusterOutput`, `Filter` 등의 스키마 정의)를 별도 차트(`fluent-operator-fluent-bit-crds`, `fluent-operator-fluentd-crds`)로 떼어냈습니다. Helm은 `helm upgrade` 시 CRD를 자동 갱신하지 않으므로, 아무 조치 없이 올리면 신규 필드가 반영 안 되거나, CRD를 지우면 **해당 CRD의 모든 커스텀 리소스(=파이프라인 정의)가 연쇄 삭제**됩니다.
  - **조치:** 업그레이드 전 커스텀 리소스 백업 → CRD를 수동 `kubectl apply --server-side` 하거나 별도 CRD 차트를 `resource-policy: keep`로 설치. 절대 `helm uninstall`로 CRD를 날리지 말 것.
- **init container 제거 → env ConfigMap 〔🟠 HIGH / 4.0.0〕** — 로그 경로 탐지 방식이 바뀝니다. 표준 경로면 문제없지만, 커스텀 로그 경로를 init container 전제로 구성했다면 재확인 필요.
- **기본 containerRuntime docker → containerd 〔🟠 HIGH / 4.0.0〕** — **가장 흔한 실수 포인트**. docker/cri-o 런타임 클러스터에서 기본값(containerd)을 그대로 쓰면 로그 경로/포맷을 잘못 잡아 **수집이 조용히 실패**할 수 있습니다.
  - **조치:** `--set containerRuntime=docker` (또는 `crio`) 명시.
- **이미지 값 `operator.container.*` → `operator.image.*` 〔🟠 HIGH / 3.5.0〕** — 이미지를 커스텀(사내 레지스트리 등)했다면 옛 키가 무시되어 의도한 이미지가 안 뜹니다. `operator.image.{registry,repository,tag}`로 이전.
- **`logPath` 옵션 제거 〔🟠 HIGH / 4.0.0〕** — containerRuntime 변경과 짝. 옛 `logPath` 키가 무효가 되므로 런타임 지정 방식으로 이전.
- **차트 저장소 이관 〔🟠 HIGH / 4.0.0〕** — 차트가 `fluent/helm-charts` 저장소로 옮겨졌습니다. GitOps(ArgoCD/Flux) 등에서 차트 소스 URL·경로를 갱신해야 합니다. (기존 `fluent` helm repo 이름은 유지)
- **OCI 배포 + Cosign 〔🟢 LOW / 4.0.0〕** — OCI 아티팩트 배포와 서명 검증 지원. 선택 사항이라 기존 https 방식 유지 가능.

---

## 3. 운영 · 보안 · 차트 옵션

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.4.0 | 3.6.0 | 4.0.0 | 4.1.0 | 4.2.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| FluentBit livenessProbe 템플릿 | 🟡 | – | ● | ● | ● | ● | ● |
| operator liveness/readiness(/healthz,/readyz) | 🟡 | – | – | – | – | ＋ | ● |
| 보안 하드닝(readOnlyRootFilesystem, non-root 등) | 🟡 | – | – | – | ◐ | ＋ | ● |
| operator ServiceMonitor | 🟢 | – | – | ＋ | ● | ● | ● |
| RBAC 생성 비활성화 옵션 | 🟢 | – | – | ＋ | ● | ● | ● |
| cluster-role 추가 RBAC 구성 | 🟢 | – | – | ● | ● | ● | ● |
| SA/ClusterRole/Binding 이름 변경 | 🟡 | – | – | ● | ● | ● | ● |
| fluent-bit 포트 구성(operator 경유) | 🟢 | – | – | ● | ● | ● | ● |
| `scheduler.base` / `scheduler.cap` | 🟢 | – | – | ● | ● | ● | ● |
| daemonset/statefulset rollout restart | 🟡 | – | – | – | ● | ● | ● |
| HostAliases 지원 | 🟢 | – | – | – | ● | ● | ● |
| 커스텀 positionDB | 🟡 | – | – | – | ● | ● | ● |
| namespaceOverride (FluentBit 차트) | 🟢 | – | – | – | ● | ● | ● |
| FluentBit args/command 노출 | 🟢 | – | – | – | ● | ● | ● |
| FluentBit annotation(operator 값) | 🟢 | – | – | – | – | – | ＋ |
| collector StatefulSet PVC storageClassName | 🟡 | – | – | – | – | – | ＋ |

**항목 설명 및 영향**

- **FluentBit livenessProbe 〔🟡 MEDIUM〕** — 멈춘 수집기를 자동 재시작. 프로브 임계값이 부적절하면 정상 파드가 재시작될 수 있어 값 점검 권장.
- **operator liveness/readiness 〔🟡 MEDIUM / 4.1.0〕** — 오퍼레이터 자체 헬스체크(`/healthz`, `/readyz`). 오퍼레이터 장애 감지·복구를 개선.
- **보안 하드닝 〔🟡 MEDIUM / 4.1.0〕** — non-root 실행·읽기전용 루트 FS·capability drop·seccomp가 기본 적용. 임의 경로에 파일을 쓰던 설정(버퍼/positionDB 등)은 **쓰기 실패**할 수 있어 volume 마운트 추가 필요.
- **ServiceMonitor / RBAC 비활성화 / 추가 RBAC / 이름 변경 〔🟢~🟡〕** — 대부분 선택형. SA/Role 이름을 바꾸면 이를 참조하던 리소스와 정합성 확인 필요(🟡).
- **`scheduler.base`/`scheduler.cap` 〔🟢 LOW〕** — 재시도 백오프 튜닝. 미설정 시 기본 동작.
- **rollout restart 〔🟡 MEDIUM〕** — 설정 변경 시 순차 재시작. 대규모 DaemonSet에서 한꺼번에 재시작되면 순간 수집 공백 가능, 롤아웃 전략 확인 권장.
- **커스텀 positionDB 〔🟡 MEDIUM〕** — 읽기 위치 DB 경로. 잘못 바꾸면 재시작 후 **중복(처음부터 재읽기) 또는 누락** 발생. 보안 하드닝의 readOnly FS와도 충돌 주의.
- **collector PVC storageClassName 〔🟡 MEDIUM / 4.2.0〕** — collector StatefulSet의 영구 볼륨 스토리지 클래스 지정. 파일시스템 버퍼를 쓸 때 스토리지 정책과 맞춰야 함.
- **그 외(HostAliases/namespaceOverride/args·command/annotation) 〔🟢 LOW〕** — 순수 추가 옵션. 미사용 시 영향 없음.

---

## 4. Input · Filter 기능

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.4.0 | 3.6.0 | 4.0.0 | 4.1.0 | 4.2.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| tail input: `bufferChunkSize` | 🟢 | – | – | ● | ● | ● | ● |
| tail input: `offsetKey` | 🟢 | – | – | – | ● | ● | ● |
| tail input: skip empty lines | 🟢 | – | – | – | ● | ● | ● |
| tail/systemd input: `storage.path` | 🟡 | – | – | – | ● | ● | ● |
| syslog input: `Tag` 파라미터 | 🟢 | – | – | ● | ● | ● | ● |
| filter: `enable_flb_null` | 🟢 | – | – | ● | ● | ● | ● |
| filter: `multiline_buffer_limit` | 🟡 | – | – | – | ● | ● | ● |
| grep filter: `logical_op` | 🟡 | – | – | – | ● | ● | ● |
| lua filter: `type_array_key` / 네임스페이스 CRD | 🟢 | – | – | – | ● | ● | ● |

**항목 설명 및 영향**

- **`bufferChunkSize` / `offsetKey` / skip empty lines / syslog `Tag` / `enable_flb_null` / lua 확장 〔🟢 LOW〕** — 명시 설정 시에만 동작하는 추가 파라미터. 기존 파이프라인 영향 없음.
- **`storage.path` (filesystem 버퍼) 〔🟡 MEDIUM〕** — 메모리→파일시스템 버퍼. 유실 방지에 유리하나 경로·용량을 잘못 잡으면 디스크 압박·readOnly FS 충돌 가능. volume 설계와 함께 검토.
- **`multiline_buffer_limit` 〔🟡 MEDIUM〕** — 멀티라인 병합 버퍼 상한. 기존 멀티라인 필터 사용 시 아주 긴 스택트레이스가 잘릴 가능성이 있어 값 확인 권장.
- **grep `logical_op` 〔🟡 MEDIUM〕** — 필터 조건을 AND/OR로 결합. 기존 grep 규칙을 재작성하면 로직이 바뀌므로 결과 검증 필요.

---

## 5. Output 플러그인

| 기능 / 변경 항목 | 영향도 | 3.2.0〔현재〕 | 3.4.0 | 3.6.0 | 4.0.0 | 4.1.0 | 4.2.0 |
|------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| ES: `reload_after` / `sniffer_class_name` | 🟡 | – | ● | ● | ● | ● | ● |
| loki: `retry_limit` (기본 output) | 🟡 | – | ● | ● | ● | ● | ● |
| loki: structured metadata | 🟡 | – | – | – | ● | ● | ● |
| opensearch: 파라미터 확장 | 🟢 | – | – | ● | ● | ● | ● |
| http: `storage.total_limit_size` | 🟡 | – | – | ● | ● | ● | ● |
| OpenTelemetry: `storage.total_limit_size` | 🟡 | – | – | ● | ● | ● | ● |
| OpenTelemetry: `logs_body_key` | 🟢 | – | – | – | ● | ● | ● |
| stackdriver: `text_payload_key` | 🟢 | – | – | – | ● | ● | ● |
| syslog output: `workers` | 🟡 | – | – | – | ● | ● | ● |
| kafka: `rdkafka_group` (rdkafka gem) | 🟡 | – | – | ● | ● | ● | ● |
| forward: `retainMetadataInForwardMode` | 🟡 | – | – | – | – | – | ＋ |
| firehose: 추가 설정 | 🟢 | – | – | – | – | – | ＋ |
| Fluentd: null output 플러그인 | 🟢 | – | – | – | ● | ● | ● |
| Fluentd: `pluginSortOrder` | 🟢 | – | – | – | ● | ● | ● |

> **⚠ 공통 주의 〔🔴 간접〕** — 이 표의 output들은 모두 Fluent Bit 3.1.7 → 5.0.6 메이저 업그레이드의 영향을 받습니다. 파라미터 추가와 별개로, **기존 output의 기본값·필수 파라미터가 5.x에서 바뀌었을 수 있어** 업그레이드 후 각 백엔드(ES/Loki/Kafka 등)로 실제 로그가 들어오는지 엔드투엔드 검증이 필요합니다.

**항목 설명 및 영향**

- **ES `reload_after`/`sniffer_class_name`, loki `retry_limit` 〔🟡 MEDIUM〕** — 기존 ES/Loki output이라면 도입 시 연결 재설정·재시도 동작이 바뀌므로 전송 안정성에 영향. 부하 테스트 권장.
- **loki structured metadata 〔🟡 MEDIUM〕** — Loki 3.x 필요. 백엔드 Loki 버전이 낮으면 오히려 전송 실패 원인이 될 수 있어 호환성 확인 필수.
- **http/OTel `storage.total_limit_size` 〔🟡 MEDIUM〕** — 버퍼 상한. 너무 작으면 백엔드 지연 시 **로그 드롭**, 없으면 디스크가 참. 트래픽에 맞게 산정.
- **syslog `workers`, kafka `rdkafka_group` 〔🟡 MEDIUM〕** — 병렬/라이브러리 변경은 처리량을 높이나 순서 보장·리소스에 영향을 줄 수 있어 검증 권장.
- **forward `retainMetadataInForwardMode` 〔🟡 MEDIUM / 4.2.0〕** — Fluent Bit→Fluentd 2계층에서 메타데이터 유지. 켜면 다운스트림 Fluentd 라우팅/필드 처리가 달라질 수 있어 양쪽 함께 검증.
- **opensearch 확장 / OTel `logs_body_key` / stackdriver `text_payload_key` / firehose / null output / pluginSortOrder 〔🟢 LOW〕** — 신규·선택 파라미터. 미사용 시 영향 없음.

---

## 6. 번들 이미지 · 런타임

| 구성요소 | 영향도 | 3.2.0〔현재〕 | 3.4.0 | 3.6.0 | 4.0.0 | 4.1.0 | 4.2.0 |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Fluent Bit** | 🔴 | 3.1.7 | 3.2.x | 4.2.x | 4.x | 5.0.x | 5.0.6 |
| **Fluentd** | 🟡 | v1.16 | v1.17 | v1.19 | v1.19 | v1.19.2 | v1.19.2 |
| **Operator(appVersion)** | 🟡 | v3.2.0 | v3.4.0 | v3.6~3.7 | v3.x | v3.8.0 | v3.9.0 |

**항목 설명 및 영향**

- **Fluent Bit 3.1.7 → 5.0.6 〔🔴 CRITICAL〕** — 로그 수집 엔진 자체의 메이저 2단계 업그레이드. YAML 설정 정식화·blob·eBPF 등 신기능과 함께 **플러그인 파라미터/기본값 변경, 일부 동작 변화**가 포함될 수 있습니다. 특정 input/filter/output이 조용히 멈추거나, 설정 파싱 실패로 파드가 크래시할 수 있는 **가장 광범위한 영향원**입니다.
  - **조치:** 스테이징에서 실제 설정으로 기동 확인 → 각 백엔드 수집 검증 → classic/yaml 설정 포맷 사용 시 파싱 이슈 점검(과거 chart 3.3.0에서 YAML+리스트 파싱 버그 사례 있음).
- **Fluentd v1.16 → v1.19.2 〔🟡 MEDIUM〕** — 2계층(Fluentd) 구성 시 해당. 플러그인 호환성 확인 권장. Fluent Bit만 쓰면 영향 적음.
- **Operator appVersion 〔🟡 MEDIUM〕** — Chart 4.2.0의 실제 오퍼레이터는 v3.9.0. CRD 스키마와 컨트롤러 동작이 이 버전 기준으로 정렬됩니다.

---

## 7. 결론 — 현재 Chart 3.2.0 대비 최신 Chart 4.2.0의 차이 + 영향도

| 구분 | Chart 3.2.0 (현재) | Chart 4.2.0 (최신) | 영향도 |
|------|--------------------|--------------------|:---:|
| **차트 저장소** | fluent-operator 저장소 내장 | helm-charts 저장소(+OCI/Cosign) | 🟠 |
| **패키징** | CRD 내장, init container 사용 | CRD 별도 차트 분리, init container 제거·env ConfigMap | 🔴 |
| **기본 런타임** | docker (`logPath` 지정) | containerd (`logPath` 제거) | 🟠 |
| **차트 값** | `operator.container.*` | `operator.image.*` 로 통합 | 🟠 |
| **Fluent Bit** | 3.1.7 | 5.0.6 (메이저 2단계↑, YAML·blob·eBPF 등) | 🔴 |
| **Fluentd** | v1.16 | v1.19.2 (null output, pluginSortOrder) | 🟡 |
| **Operator** | v3.2.0 | v3.9.0 | 🟡 |
| **Output** | ES/loki 기본 수준 | opensearch·http·OTel·firehose·forward·syslog workers 등 대폭 확장 | 🟡 |
| **Filter/Input** | 기본 | multiline_buffer_limit·grep logical_op·offsetKey·storage.path 등 추가 | 🟡 |
| **운영/보안** | 제한적 | ServiceMonitor·RBAC·rollout restart·probe·보안 하드닝 | 🟡 |
| **안정성** | – | logfmt/parser 크래시 방지, namespace 필터링·파라미터명 다수 수정 | 🟢 |

**요약**

Chart 3.2.0은 대부분의 최신 기능이 아직 없는 기준점입니다. **Chart 4.0.0을 기점으로 저장소 이관과 v4 재편(Breaking)**이 함께 일어나 CRD 분리·런타임 기본값 변경·이미지 값 스키마 변경이 발생했고, **Chart 4.1.0에서 보안 하드닝, 4.2.0에서 forward/firehose 등**이 더해졌습니다. 3.2.0 → 4.2.0은 새 기능을 얻는 이점과 함께 (1) 차트 저장소·구조 변경 마이그레이션, (2) CRD 처리, (3) Fluent Bit 메이저 업그레이드 설정 호환성 검증이 모두 필요한 업그레이드입니다.

---

## 8. 운영 관점 업그레이드 절차 (영향도 기반)

### 8.1. 사전 백업 〔🔴 필수〕
```bash
# 파이프라인 정의(커스텀 리소스) 전체 백업 — CRD 삭제 사고 대비
kubectl get clusteroutput,clusterfilter,clusterinput,clusterparser -A -o yaml > backup-cr.yaml
kubectl get fluentbit,fluentd -A -o yaml > backup-fluent.yaml
# 현재 사용 중인 values 백업 — 값 스키마 변환 대비
helm get values fluent-operator -n fluent > values-3.2.0.yaml
```

### 8.2. values.yaml 변환 점검 〔🟠 필수〕
- `operator.container.*` → `operator.image.*` 이전
- `operator.initcontainer.*`, `logPath.*` 키 제거
- `containerRuntime` 값 재확인(docker/cri-o면 명시)
- CRD 서브차트 값(`fluentbit-crds.*` 등) 제거 → CRD 별도 관리로 전환
- GitOps(ArgoCD/Flux) 사용 시 차트 소스를 helm-charts 저장소/OCI로 갱신

### 8.3. CRD 처리 〔🔴 필수, 둘 중 택1〕
```bash
helm repo update

# 방법 A) 수동 관리
helm pull fluent/fluent-operator --version 4.2.0 --untar
kubectl apply --server-side --force-conflicts -f fluent-operator/crds/

# 방법 B) CRD 별도 차트로 Helm 관리 (권장, 삭제 방지)
helm install fluent-operator-fluent-bit-crds fluent/fluent-operator-fluent-bit-crds -n fluent \
  --set additionalAnnotations."helm\.sh/resource-policy"=keep
helm install fluent-operator-fluentd-crds fluent/fluent-operator-fluentd-crds -n fluent \
  --set additionalAnnotations."helm\.sh/resource-policy"=keep
```

### 8.4. 업그레이드 & 검증 〔🔴 필수〕
```bash
# repo 방식
helm upgrade fluent-operator fluent/fluent-operator --version 4.2.0 -n fluent -f values-4.x.yaml
# 또는 OCI 방식
helm upgrade --install fluent-operator oci://ghcr.io/fluent/helm-charts/fluent-operator \
  --version 4.2.0 -n fluent -f values-4.x.yaml
```
검증 체크리스트:
- [ ] 🔴 오퍼레이터/DaemonSet 파드 Running, 재시작 루프 없음
- [ ] 🔴 기존 `ClusterOutput`/`Filter` 등 커스텀 리소스가 그대로 존재
- [ ] 🔴 각 백엔드(ES/Loki/Kafka 등)에 로그가 실제로 들어오는지 엔드투엔드 확인
- [ ] 🟠 docker/cri-o 클러스터라면 로그 경로 정상 인식 확인
- [ ] 🟡 readOnlyRootFilesystem로 인한 쓰기 실패 로그 없음(필요 시 volume 추가)
- [ ] 🟡 멀티라인/grep 필터 결과가 기존과 동일한지 샘플 비교

### 8.5. 롤백 준비 〔🔴 필수〕
- 백업한 `values-3.2.0.yaml`, `backup-cr.yaml` 보관
- 문제 발생 시 이전 차트 버전으로 `helm rollback` + CRD/CR 복원 경로 사전 확인

---

## 9. 권장 업그레이드 전략

Fluent Bit 메이저 2단계(3→4→5)와 차트 3.x→4.x(저장소 이관 + v4 재편)가 한꺼번에 걸리므로, **단번에 3.2.0 → 4.2.0으로 점프하기보다** 가능하면 중간 단계(예: 구 저장소 마지막 계열인 3.6.0/3.7.0 → 신 저장소 4.0.0 → 4.2.0)를 경유해 Breaking 변경을 나눠 검증하는 것이 안전합니다. 특히 프로덕션은 반드시 스테이징에서 동일 설정으로 먼저 재현·검증 후 적용하세요.

---

*출처: fluent/helm-charts Releases(fluent-operator-4.0.0~4.2.0) 및 README·MIGRATION-v4.md, fluent/fluent-operator Releases·CHANGELOG.md, fluentbit.io 릴리즈 공지 (2026-07 기준). Chart 버전↔appVersion·이미지 매핑과 기능 최초 등장 시점은 릴리즈 노트/PR 기준이며, 구 저장소(3.x)의 일부 세부 패치 버전·날짜는 태그 시점에 따라 다를 수 있습니다. 영향도 레벨은 일반적인 로그 파이프라인(Fluent Bit DaemonSet + CRD 기반 Input/Filter/Output) 운영을 가정한 판단이며, 실제 영향은 각 환경의 설정·백엔드·런타임에 따라 달라질 수 있습니다. 적용 전 해당 Chart 버전의 원문 릴리즈 노트와 values.yaml을 반드시 대조하시기 바랍니다.*
