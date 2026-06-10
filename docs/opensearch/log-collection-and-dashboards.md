# K8s 로그 수집 · OpenSearch · Grafana 대시보드 구성 가이드

> 대상: rwr 클러스터(Talos) 기준 구축. 프로덕션(systemd 호스트) 적용 시 차이점은 각 절의 "프로덕션 노트" 참고.
> 관련 리포 경로: `ops/logging/` (파이프라인·대시보드·스크립트), `ops/monitoring/kube-prometheus-stack-values-rwr.yaml` (Grafana 데이터소스)

---

## 1. 전체 아키텍처

```
[각 노드]
  컨테이너 stdout/stderr ──> /var/log/containers/*.log (CRI)
  systemd 유닛 로그       ──> journald (/var/log/journal)   ※ Talos에는 없음
        │
        ▼
  fluent-bit DaemonSet (fluent-operator CRD로 구성)
    tail 입력(cri 파서) ─ kubernetes 필터(Owner_References) ─ lua(워크로드 파생) ─┐
    systemd 입력 ─ modify/parser(klog) ──────────────────────────────────────────┤
        │                                                                        ▼
        ▼                                                       OpenSearch (단일노드, ns=logging)
  인덱스: kubernetes-YYYY.MM.DD / systemd-YYYY.MM.DD (일별)
    · ISM: 7일 경과 자동 삭제   · 템플릿: replica 0, refresh 10s
        │
        ▼
  Grafana (kube-prometheus-stack) + grafana-opensearch-datasource 플러그인
    드릴다운 3계층: L0 개요 → L1 워크로드 통계 → L2 상세(raw 로그)
    + Log Capacity(적재 용량 산출) 대시보드
```

| 컴포넌트 | 버전 | 비고 |
|---|---|---|
| fluent-operator (helm) | 3.2.0 | operator only — FluentBit 인스턴스는 CRD로 직접 |
| fluent-bit 이미지 | `ghcr.io/fluent/fluent-operator/fluent-bit:3.2.10` | **operator 전용 이미지 필수** (§7.1) |
| OpenSearch (helm) | 2.32.0 (앱 2.19.1) | 보안 플러그인 비활성(테스트), prometheus-exporter 플러그인 |
| OpenSearch Dashboards (helm) | 2.28.0 | |
| kube-prometheus-stack (helm) | 73.1.0 | Grafana + OpenSearch 데이터소스 플러그인 |

---

## 2. 수집 파이프라인 (fluentbit.fluent.io/v1alpha2 CRD)

파일: `ops/logging/fluentbit-kubernetes-pipeline.yaml` (컨테이너), `fluentbit-systemd-pipeline.yaml` (systemd + FluentBit 인스턴스/공통 설정)

### 2.1 컨테이너 로그 (kubernetes 파이프라인)

| CRD | 이름 | 역할 |
|---|---|---|
| ClusterInput | `kubernetes-containers` | tail `/var/log/containers/*.log`, parser `cri`, 자기 로그(fluent-bit*) 제외 |
| ClusterFilter | `kubernetes-enrich` | ① `message→log` rename ② kubernetes 필터(customPlugin, `Owner_References On`) ③ lua 워크로드 파생 |
| ClusterOutput | `opensearch-kubernetes` | `kubernetes-YYYY.MM.DD` 일별 인덱스, `replaceDots`, `suppressTypeName` |
| ConfigMap | `fluent-bit-lua` | `workload.lua` — operator가 자동 마운트 |

처리 순서가 중요하다:

1. **`message → log` rename** — CRI 파서 출력 키는 `message`인데, kubernetes 필터의 `Merge_Log`(JSON 로그 파싱)는 `log` 키만 본다.
2. **kubernetes 필터** — CRD typed 필드에 `ownerReferences`가 없어 `customPlugin`(raw config)으로 작성. `Owner_References On`이 핵심.
3. **lua `derive_workload`** — ownerReferences[0]을 `kubernetes.workload_kind` / `workload_name` 평탄화 필드로 변환 후 원본 제거(색인 용량 절감).

### 2.2 워크로드 메타 병합 — 왜 이렇게 하나

Grafana는 OpenSearch(로그)와 Prometheus(메트릭)를 한 쿼리에서 조인할 수 없다. 따라서 Deployment/StatefulSet/DaemonSet 단위 로그 필터링은 **수집 시점에 로그 레코드에 워크로드 메타를 병합**하는 방식으로 해결한다.

- Pod의 ownerReference는 직접 소유자만 가리킨다 → lua에서 환원:
  - `ReplicaSet` → 이름 끝 `-<hash>` 제거 → **Deployment**
  - `Job` 이름이 `-<숫자>`로 끝나면 → **CronJob**
  - static pod(kube-apiserver 등)는 ownerReference kind=**Node** (정상 분류)
- 결과 필드: `kubernetes.workload_kind` ∈ {Deployment, StatefulSet, DaemonSet, CronJob, Job, Node, Pod}, `kubernetes.workload_name`
- 알려진 한계: Deployment 없이 직접 만든 ReplicaSet은 Deployment로 환원됨(실무상 드묾).

### 2.3 systemd 로그 (프로덕션용)

- ClusterInput `systemd`: `/var/log/journal`, `systemdFilter`로 kubelet/containerd/sshd 등 핵심 유닛만.
- klog 파서(`I/W/E/F` severity)로 level 추출 → `systemd-YYYY.MM.DD` 인덱스.
- **프로덕션 노트**: Talos에는 journald가 없어 rwr에서는 동작하지 않음(정상). static pod 컴포넌트(kube-apiserver, controller-manager 등)는 journald가 아니라 **컨테이너 파이프라인**으로 수집된다 — systemd 유닛으로 직접 띄운 바이너리 설치형만 `systemdFilter`에 유닛 추가.

### 2.4 FluentBit 인스턴스 (공통)

```yaml
spec:
  image: ghcr.io/fluent/fluent-operator/fluent-bit:3.2.10   # §7.1 함정 참고
  fluentBitConfigName: systemd-to-opensearch
  metricsPort: 2020          # httpPort 아님
  tolerations: [{operator: Exists}]
```

ClusterFluentBitConfig의 셀렉터는 `matchExpressions: pipeline In (systemd, kubernetes)` — 두 파이프라인을 한 DaemonSet이 처리.

---

## 3. 인덱스 보존(ISM) · 용량 통제

파일: `ops/logging/opensearch-ism.sh` (멱등 스크립트, `RETENTION_DAYS` 환경변수로 조정)

| 항목 | 값 | 효과 |
|---|---|---|
| ISM 정책 `log-retention` | hot → **7일 경과 시 delete** | 디스크 초과 방지. `ism_template`으로 신규 일별 인덱스 자동 부착 |
| 인덱스 템플릿 `logs-defaults` | `number_of_replicas: 0` | 단일노드 yellow 해소 + 저장량 절반 |
| | `refresh_interval: 10s` | 색인 오버헤드 감소 |

```bash
KUBECONFIG=<kubeconfig> RETENTION_DAYS=7 ./ops/logging/opensearch-ism.sh
```

- 보존일수 산정: Log Capacity 대시보드로 측정한 일일 증가량 × 보존일수 ≤ 디스크의 ~70%.
- 재실행 시 기존 인덱스에 "already has a policy"는 정상(멱등). 정책 내용 변경은 ISM update API 필요.

---

## 4. Grafana OpenSearch 데이터소스

파일: `ops/monitoring/kube-prometheus-stack-values-rwr.yaml` → helm upgrade로 적용

```yaml
grafana:
  plugins: [grafana-opensearch-datasource]
  additionalDataSources:
    - name: OpenSearch-logs
      type: grafana-opensearch-datasource
      uid: os-logs
      url: http://opensearch-cluster-master.logging.svc:9200
      jsonData:
        database: "[kubernetes-]YYYY.MM.DD"   # ← 와일드카드(kubernetes-*) 금지, §7.4
        interval: Daily
        timeField: "@timestamp"
        version: "2.19.1"                     # OpenSearch 엔진 버전
        flavor: opensearch
        logMessageField: log
        logLevelField: level
```

systemd 로그는 인덱스 패턴이 달라(`systemd-YYYY.MM.DD`) **별도 데이터소스**를 추가한다:

```yaml
    - name: OpenSearch-systemd
      type: grafana-opensearch-datasource
      uid: os-logs-systemd
      url: http://opensearch-cluster-master.logging.svc:9200
      jsonData:
        database: "[systemd-]YYYY.MM.DD"
        interval: Daily
        timeField: "@timestamp"
        logMessageField: MESSAGE
        logLevelField: severity      # klog 파서 산출(I/W/E/F)
```

---

## 5. 로그 대시보드 — 드릴다운 3계층

파일: `ops/logging/grafana-k8slogs-l{0,1,2}.json` → configmap(`grafana_dashboard=1`, 폴더 Logging) 사이드카 로드
접근: `http://grafana-rwr.miribit.lab/d/k8slogs-l0-overview`

계층당 6패널 이하로 쿼리 부하를 분산하고, **클릭 시 변수 + 시간범위가 다음 계층으로 전달**된다.

| 계층 | uid | 변수 | 패널 | 드릴다운 |
|---|---|---|---|---|
| L0 클러스터 개요 | `k8slogs-l0-overview` | (없음) | 총/stderr/에러의심 stat, 네임스페이스별 추이, 네임스페이스·워크로드종류 표 | 표 행·시리즈 클릭 → L1 |
| L1 워크로드 통계 | `k8slogs-l1-workload` | namespace, workload_kind | stat 2, 워크로드별/종류별 추이, kind+workload 중첩 표, 에러의심 표 | 워크로드 클릭 → L2 |
| L2 로그 상세 | `k8slogs-l2-detail` | + workload, pod, container, **node**, level, **keyword**(lucene) | 매치수, Pod별/레벨별 추이, **로그 원본 500건**, Top Pod(+node)/컨테이너 | Top Pod 클릭 → 셀프 드릴 또는 **노드 호스트 로그로 교차 이동** |
| systemd 호스트 로그 | `k8slogs-systemd` | host, unit, severity, keyword (**데이터소스 os-logs-systemd**) | stat 3, 유닛별/호스트별 추이, 호스트x유닛 표, 로그 원본 | 호스트 행 클릭 → 셀프 드릴 또는 **해당 노드 파드 로그(L2)로 교차 이동** |

각 대시보드 상단에 **사용 가이드 text 패널**(드릴다운 흐름, 필드 의미, 주의사항)이 있고, 모든 패널에 description(패널 제목 옆 i 아이콘)이 달려 있다. systemd 대시보드는 같은 태그(`k8slogs`)라 상단 네비 링크로 상호 이동된다.

**컨테이너 로그 ↔ 호스트 로그 양방향 연계**: 연결 키는 노드 이름 — 컨테이너 로그의 `kubernetes.host` ≡ journald의 `HOSTNAME`. systemd 표에서 호스트 행 클릭 → 같은 노드·같은 시간대의 파드 로그(L2, `var-node`)로, L2 Top Pod 표에서 행 클릭 → 그 파드가 떠 있는 노드의 kubelet/containerd/kernel 로그(systemd, `var-host`)로 이동한다. kubelet·OOM 등 노드 데몬 원인과 파드 증상을 오가며 역추적하는 용도. 전제: 두 필드의 호스트 표기가 같아야 한다(FQDN 여부가 다르면 수집 lua에서 정규화).

### 5.1 드릴다운 전달 메커니즘 (대시보드 제작 시 재사용)

| 전달 대상 | 데이터링크 문법 |
|---|---|
| 시간범위 | `${__url_time_range}` |
| 표 행 값 | `${__data.fields.<컬럼명>}` (organize rename 후 표시명, ASCII 권장) |
| 시계열 시리즈 값 | `${__field.labels["kubernetes.workload_name.keyword"]}` |
| 현재 변수 선택값 | `${namespace:queryparam}` (multi-value도 `var-x=a&var-x=b`로 직렬화) |

상단 네비게이션은 `type: dashboards` 링크(tag `k8slogs`, keepTime + includeVars) — 계층 간 이동 시 컨텍스트 유지.

### 5.2 사용 팁

- L2 키워드 칸은 lucene 자유 입력: `*timeout*`, `log:*panic*`, `stream:stderr AND log:*error*`. **비우지 말 것**(기본 `*`).
- 워크로드 종류 `Node` = static pod(kube-apiserver, controller-manager, scheduler 등).
- `level` 필터는 JSON 로그(level 필드 보유)에만 적용 — 텍스트(klog) 로그는 level 없음.

---

## 6. Log Capacity — 적재 용량 산출 대시보드

파일: `ops/logging/grafana-log-capacity.json` (uid `log-capacity`)

테스트 환경(워크로드 없음)에서 프로덕션 용량을 산출하는 방법론:

1. **환경 불변 상수를 테스트에서 측정**: 확장계수(OpenSearch 디스크 ÷ 원시 로그 bytes), 문서당 평균 크기.
2. **환경 변수는 파라미터로 외삽**: 노드 수, 노드당 일일 로그량(MB), 보존일수, 복제본, 헤드룸 — 대시보드 textbox 변수.
3. **산식**(대시보드가 자동 계산):
   - 일일 디스크 증가 = 노드수 × 노드당MB × 확장계수 × (1+replica)
   - 로컬 스토리지 = 일일 증가 × 보존일수 × (1+헤드룸%)
   - S3 스냅샷 = primary 일일 증가 × 스냅샷 보존일수 × (1+오버헤드%)
4. 로그가 실제로 흐르면 라이브 패널(opensearch prometheus-exporter 메트릭 기반 시간당/일별 인덱스 증가)이 실측값을 보여줘 **자가 보정**된다.

---

## 7. 운영 함정 모음 (실측 — 재발 시 여기부터)

### 7.1 fluent-bit가 멀쩡해 보이는데 아무것도 수집 안 됨
**원인**: FluentBit CR 이미지를 업스트림 `fluent/fluent-bit`로 지정. 업스트림 엔트리포인트는 기본 설정(cpu→stdout)을 읽는다. **operator가 생성한 Secret(`/fluent-bit/config`)을 읽으려면 config watcher 내장 `ghcr.io/fluent/fluent-operator/fluent-bit` 이미지 필수.**
**증상 확인**: `kubectl logs ds/fluent-bit`에 `cpu.local` 레코드가 찍히면 이 문제다.

### 7.2 `Owner_References`는 fluent-bit ≥ 3.2
3.1.x는 unknown property로 **기동 실패**. 사전 검증:
```bash
docker run --rm <이미지> /fluent-bit/bin/fluent-bit -i dummy -F kubernetes -p Owner_References=On -m '*' -o null
```

### 7.3 operator 생성 설정의 확인 위치
렌더링된 최종 설정 Secret 이름 = **ClusterFluentBitConfig 이름** (예: `systemd-to-opensearch`). 디버깅 시 이 Secret을 디코드해서 [FILTER] 순서/파라미터를 확인.

### 7.4 Grafana 데이터소스 "Index not found"
`database`에 와일드카드(`kubernetes-*`) 대신 **일별 패턴 `[kubernetes-]YYYY.MM.DD` + `interval: Daily`** 를 써야 한다.

### 7.5 대시보드 변수 드롭다운이 안 뜸 (전 변수 깨짐)
OpenSearch 플러그인의 metricFindQuery는 변수 query를 **plain string**으로 받아 `JSON.parse()` 한다. Prometheus처럼 object-form(`{"query":..., "refId":...}`)으로 넣으면 전부 깨진다.
올바른 형식: `"query": "{\"find\":\"terms\",\"field\":\"kubernetes.namespace_name.keyword\"}"`

### 7.6 쿼리는 성공하는데(전 패널 No data) 결과가 0건
**textbox 변수 값은 lucene 이스케이프된다** — 기본값 `*`가 `\*`(리터럴 별표 검색)로 치환되어 AND로 붙은 모든 패널이 0건. 패널 쿼리에서 **`(${keyword:raw})`** 형식 지정자로 이스케이프를 꺼야 한다.
**디버깅 정석**: OpenSearch query insights 인덱스(`top_queries-*`)의 `source` 필드에 실제 수신 쿼리 본문이 남는다 — 수동 테스트와 브라우저발 쿼리를 diff하면 즉시 확정.

### 7.7 Grafana 파드 재시작 후 도메인 접속 502
opst-mt01의 `rwr-grafana-tunnel`(kubectl port-forward)이 stale 됨(프로세스 생존 + 포워딩 실패). helm upgrade 등으로 Grafana가 재기동되면 `systemctl restart rwr-grafana-tunnel` 필요.

---

## 8. 리소스 목록

| 경로 | 내용 |
|---|---|
| `ops/logging/fluentbit-kubernetes-pipeline.yaml` | 컨테이너 로그 파이프라인 CRD + lua ConfigMap |
| `ops/logging/fluentbit-systemd-pipeline.yaml` | systemd 파이프라인 CRD + 공통 설정 + FluentBit 인스턴스 |
| `ops/logging/opensearch-values.yaml` 외 2 | OpenSearch / Dashboards / fluent-operator helm values |
| `ops/logging/opensearch-ism.sh` | ISM 보존 정책 + 인덱스 템플릿 적용 (멱등) |
| `ops/logging/grafana-k8slogs-l{0,1,2}.json` | 드릴다운 3계층 대시보드 |
| `ops/logging/grafana-k8slogs-systemd.json` | systemd 호스트 로그 대시보드 (별도 데이터소스) |
| `ops/logging/grafana-log-capacity.json` | 적재 용량 산출 대시보드 |
| `ops/logging/servicemonitors.yaml` | fluent-bit / OpenSearch 메트릭 수집 |
| `ops/monitoring/kube-prometheus-stack-values-rwr.yaml` | Grafana 플러그인 + 데이터소스 |
