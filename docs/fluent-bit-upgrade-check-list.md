# 기존 3.2.0 values.yaml을 그대로 사용해 Chart 4.2.0(Operator v3.9.0)로 배포할 때 — 구성 변경 확인 리스트

> **전제:** 예전 `fluent-operator` chart 3.2.0에서 쓰던 `values.yaml`을 **수정 없이** 최신 chart 4.2.0(내부 Operator v3.9.0, Fluent Bit 5.0.6)에 그대로 `-f values.yaml`로 넣어 배포하는 상황.
> **핵심 결론:** 그대로 넣으면 **일부 키는 조용히 무시(no-op)** 되고, **CRD·런타임·이미지 관련 항목은 실제 배포가 깨지거나 로그 수집이 멈출 수 있습니다.** 아래 항목을 배포 전 반드시 확인하세요.

---

## 상태 표기

| 표기 | 의미 |
|------|------|
| 🔴 BROKEN | 그대로 두면 배포 실패 또는 로그 수집 중단 위험 |
| 🟠 IGNORED | 키가 무시됨(no-op). 의도한 설정이 적용 안 됨 → 재작성 필요 |
| 🟡 CHECK | 동작은 하나 기본값/동작 변화로 결과가 달라질 수 있음 |
| 🟢 OK | 대체로 그대로 통용 |

---

## A. 오퍼레이터(operator) 블록

| # | 3.2.0 values 키 | 4.2.0에서의 상태 | 확인/조치 |
|---|-----------------|------------------|-----------|
| A-1 | `operator.initcontainer.repository` / `.tag` | 🟠 IGNORED | init container 자체가 제거됨. 이 키는 무시됨. 사설 레지스트리로 init 이미지를 지정했다면 더 이상 불필요 → 삭제 |
| A-2 | `operator.container.repository` / `.tag` | 🟠 IGNORED | 이미지 키가 `operator.image.{registry,repository,tag}` 로 변경됨. 옛 키는 무시되어 **의도한(사내 레지스트리) 이미지가 아닌 기본 이미지가 뜰 수 있음** → `operator.image.*` 로 재작성 |
| A-3 | `logPath.containerd` / `logPath.crio` (혹은 최상위 `logPath`) | 🔴 BROKEN | `logPath` 옵션 제거됨. docker 전제로 경로를 지정하던 구성이 무효 → `containerRuntime` 방식으로 이전 필요 (아래 B 참고) |
| A-4 | `operator.resources` | 🟢 OK | 통용. 값 유지 |
| A-5 | `operator.annotations` / `operator.labels` | 🟢 OK | 통용 |
| A-6 | `operator.imagePullSecrets` | 🟢 OK | 통용(키 위치 확인 권장) |

---

## B. 컨테이너 런타임 · 로그 경로 (가장 위험)

| # | 항목 | 상태 | 확인/조치 |
|---|------|------|-----------|
| B-1 | 기본 컨테이너 런타임 가정 | 🔴 BROKEN | 3.2.0은 **docker** 전제, 4.x는 기본 **containerd**. 클러스터가 docker/cri-o면 **로그 파일 경로를 잘못 잡아 수집이 조용히 실패**. → `--set containerRuntime=docker`(또는 `crio`) 명시 |
| B-2 | 로그 경로 주입 방식 | 🟡 CHECK | init container 탐지 → env ConfigMap(`CONTAINER_LOG_PATH`) 방식으로 변경. 표준 경로면 자동 처리되나, 커스텀 로그 경로를 쓰던 환경은 값 확인 |
| B-3 | `fluentbit.filter.containerd.enable` | 🟡 CHECK | containerd 로그 포맷 변환 필터. 런타임 설정과 일관되게 맞춰야 파싱 정상 |

---

## C. CRD (파이프라인 정의 보존 — 최우선)

| # | 항목 | 상태 | 확인/조치 |
|---|------|------|-----------|
| C-1 | CRD 설치/업그레이드 방식 | 🔴 BROKEN | 3.2.0은 CRD가 차트에 내장(서브차트). 4.x는 **별도 차트로 분리**되고 `helm upgrade`는 CRD를 자동 갱신하지 않음. 아무 조치 없이 올리면 **신규 CRD 필드 미반영** 또는 처리 실수 시 **기존 `ClusterOutput`/`Filter` 등 커스텀 리소스 연쇄 삭제** |
| C-2 | 옛 서브차트 값 `fluentbit-crds.*` / `fluentd-crds.*` (있었다면) | 🟠 IGNORED | 서브차트 제거로 무시됨 → CRD 별도 차트(`fluent-operator-fluent-bit-crds`, `fluent-operator-fluentd-crds`) 설치로 전환 |
| C-3 | 업그레이드 전 백업 | 🔴 필수 | `kubectl get clusteroutput,clusterfilter,clusterinput,clusterparser,fluentbit,fluentd -A -o yaml`로 백업 후 진행 |

---

## D. Fluent Bit 블록

| # | 3.2.0 values 키 | 상태 | 확인/조치 |
|---|-----------------|------|-----------|
| D-1 | `fluentbit.image.repository: kubesphere/fluent-bit` (또는 옛 경로) | 🟠 IGNORED / 🟡 | 기본 이미지가 `ghcr.io/fluent/fluent-operator/fluent-bit`(태그 5.0.6)로 변경. 옛 repository를 고정해뒀다면 **구버전 이미지로 뜨거나 pull 실패** 가능 → 신 경로로 재작성하거나 이미지 키 제거해 기본값 사용 |
| D-2 | `fluentbit.image.tag` 고정 | 🔴/🟡 | 3.x 태그로 고정돼 있으면 Operator v3.9.0가 기대하는 CRD/기능과 **버전 불일치**. 동적 리로드·신규 필드가 안 맞을 수 있음 → 태그 고정 해제 또는 5.0.x로 |
| D-3 | `fluentbit.input.tail.*` (memBufLimit 등) | 🟡 CHECK | 대체로 통용되나 Fluent Bit 5.x에서 일부 파라미터 기본값·동작 변화 가능 → 기동 후 로그 확인 |
| D-4 | `fluentbit.filter.*` (kubernetes/containerd/systemd) | 🟡 CHECK | 통용. 단 containerd 필터는 B-3와 함께 확인 |
| D-5 | `fluentbit.output.*` (es/loki/kafka 등) | 🟡 CHECK | 키는 통용되나 **Fluent Bit 3→5 메이저 점프로 output 기본값·필수 파라미터가 바뀌었을 수 있음** → 각 백엔드로 실제 적재 엔드투엔드 검증 |
| D-6 | `fluentbit.resources` / `tolerations` / `nodeSelector` | 🟢 OK | 통용 |
| D-7 | 파일시스템 버퍼(`storageType: filesystem`) 사용 시 | 🟡 CHECK | 4.1.0의 보안 하드닝(readOnlyRootFilesystem)으로 **버퍼 경로 쓰기 실패** 가능 → 해당 경로에 volume/volumeMount 추가 확인 |

---

## E. Fluentd 블록 (사용 중일 때만)

| # | 3.2.0 values 키 | 상태 | 확인/조치 |
|---|-----------------|------|-----------|
| E-1 | `fluentd.image.repository: kubesphere/fluentd` / `tag: v1.15.x` | 🟠 IGNORED / 🟡 | 기본 이미지가 `fluent/fluent-operator/fluentd`(v1.19.2)로 변경. 옛 kubesphere 경로/태그 고정 시 **구버전으로 뜨거나 pull 실패** → 신 경로로 재작성 또는 이미지 키 제거 |
| E-2 | `fluentd.output.*` (es/kafka/opensearch buffer 등) | 🟡 CHECK | Fluentd v1.15→v1.19 업그레이드로 플러그인 호환성 확인 |
| E-3 | `fluentd.forward.port` 등 | 🟢 OK | 통용. (2계층 구성 시 forward 메타데이터 옵션은 신규 `retainMetadataInForwardMode` 참고) |

---

## F. 공통 / 메타

| # | 3.2.0 values 키 | 상태 | 확인/조치 |
|---|-----------------|------|-----------|
| F-1 | `nameOverride` / `fullnameOverride` / `namespaceOverride` | 🟢 OK | 대체로 통용. 리소스 이름 관련이라 기존 릴리즈와 정합성만 확인 |
| F-2 | `configFileFormat` (classic/yaml) | 🟡 CHECK | 3.2.0에 없었다면 미설정=classic. yaml로 바꿀 계획이면 Fluent Bit 5.x 파싱 확인 |
| F-3 | 차트 저장소 소스 | 🟠 | 차트가 `fluent/helm-charts`(+OCI)로 이관. GitOps(ArgoCD/Flux) 소스 URL/차트명 갱신 필요 |
| F-4 | 신규 보안 컨텍스트 기본값 | 🟡 CHECK | 4.x는 non-root/readOnly FS/capability drop 기본 적용. 커스텀 쓰기 경로가 있으면 volume 필요 |

---

## G. 배포 전 최종 점검 순서 (요약)

1. **[🔴] 백업** — 커스텀 리소스(ClusterOutput/Filter 등)와 현재 values를 전량 백업
   ```bash
   kubectl get clusteroutput,clusterfilter,clusterinput,clusterparser,fluentbit,fluentd -A -o yaml > backup-cr.yaml
   helm get values fluent-operator -n fluent > values-3.2.0.yaml
   ```
2. **[🟠] values 재작성** — 아래 키를 변환/삭제
   - `operator.initcontainer.*` → 삭제
   - `operator.container.*` → `operator.image.{registry,repository,tag}`
   - `logPath.*` → 삭제하고 `containerRuntime` 지정
   - `fluentbit.image.*` / `fluentd.image.*` → 신 레지스트리 경로 또는 키 제거(기본값 사용)
   - 옛 CRD 서브차트 값 제거
3. **[🔴] CRD 선처리** — 수동 `kubectl apply --server-side -f crds/` 또는 별도 CRD 차트 설치(`resource-policy: keep`)
4. **[🔴] 런타임 확인** — docker/cri-o면 `--set containerRuntime=docker`(또는 `crio`)
5. **[🟡] 스테이징 배포 & 검증** — 파드 Running, CR 보존, 각 백엔드 로그 적재, 버퍼 쓰기 실패 없음
6. **[🔴] 롤백 경로 확보** — `helm rollback` + CR 복원 절차 사전 확인

---

## H. "그대로 배포"의 대표 증상 예측

| 증상 | 원인 항목 |
|------|-----------|
| 오퍼레이터가 사내 레지스트리 이미지가 아닌 기본 이미지로 뜸 | A-2 (operator.container.* 무시) |
| docker/cri-o 클러스터에서 로그가 안 들어옴(파드는 정상) | B-1 (containerRuntime 기본값 변경) |
| Fluent Bit/Fluentd가 구버전 이미지로 뜨거나 ImagePullBackOff | D-1/D-2, E-1 (이미지 경로/태그 고정) |
| 새 CRD 필드를 쓰는 리소스가 적용 안 됨 | C-1 (CRD 자동 미갱신) |
| 파일시스템 버퍼 경로 쓰기 실패 로그 | D-7/F-4 (readOnly 루트 FS) |
| 특정 output이 조용히 로그를 안 보냄 | D-5 (Fluent Bit 5.x 파라미터 변화) |

---

*본 리스트는 fluent-operator chart 3.2.0(구 저장소, kubesphere 이미지 계열)의 일반적인 values.yaml 구조와 chart 4.2.0/Operator v3.9.0의 values 스키마를 대조한 것입니다. 실제 사용 중인 values.yaml의 키 구성에 따라 해당 여부가 달라질 수 있으니, `helm get values`로 현재 값을 추출해 위 A~F 항목과 1:1 대조하시길 권장합니다. 출처: fluent/helm-charts·fluent/fluent-operator values.yaml 및 릴리즈 노트, MIGRATION-v4.md (2026-07 기준).*
