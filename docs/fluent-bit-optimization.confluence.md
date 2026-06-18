# fluent-bit 컨테이너 로그 파이프라인 최적화 (200노드 · 일 수백 GB)

> 대상: Spark · Trino · Airflow · Postgres · Monitoring 스택이 도는 200노드 클러스터에서
> fluent-operator(CR 기반) fluent-bit이 컨테이너 로그를 OpenSearch(master·coord·data 일체형 5노드)로
> 적재하는 파이프라인. **버스트 부하·apiserver 부하·저장 총량**을 함께 잡는 구성.

---

## 1. 다이어그램

> 📌 Confluence: **Gliffy Diagram** 매크로 삽입 → **Import** → `fluent-bit-pipeline.gliffy` 업로드.
> (Gliffy 네이티브 JSON 포맷, `contentType: application/gliffy+json`, version 1.3)

흐름: **200 Nodes → CRI 로그 → fluent-bit(INPUT→FILTER a~d→OUTPUT) → OpenSearch**

---

## 2. 핵심 최적화 5

| # | 최적화 | 어디서 | 효과 |
|---|--------|--------|------|
| ① | **filesystem 버퍼** | INPUT `storage.type filesystem` + SERVICE storage | 버스트를 디스크로 흡수 → 역압·로그 유실 방지 |
| ② | **useKubelet** | FILTER kubernetes | 메타조회를 apiserver→로컬 kubelet으로 → **200노드 apiserver 부하 소거** |
| ③ | **multiline** | INPUT `cri` + FILTER multiline | Spark/Trino(java)·Airflow(python) 스택트레이스를 1 doc로 → doc 폭증·에러탐지 깨짐 방지 |
| ④ | **trim / throttle** | FILTER d-trim, c-throttle | 노이즈·고용량 필드 제거 + 폭주 소스 캡 → **총량 감소(샤드 증가 둔화)** |
| ⑤ | **generateID** | OUTPUT opensearch | 타임아웃 재시도 시 **중복 색인 방지**(at-least-once 멱등) |

---

## 3. 파이프라인 단계별 설정 요지

### 3.1 SERVICE (`ClusterFluentBitConfig`)
- `flushSeconds: 5` — bulk 요청 횟수↓ (지연 +몇 초 trade)
- `storage.path: /var/log/flb-storage` + **hostPath 볼륨 마운트 필수** (안 물리면 ephemeral에 쌓여 OOM/유실)
- `maxChunksUp` / `backlogMemLimit` — 메모리에 올릴 청크 한도, 나머지 디스크
- `httpServer: true` — `/api/v1/storage`·`/api/v1/metrics`로 **버퍼 백로그 실측**

### 3.2 INPUT (`ClusterInput` tail)
- `storage.type: filesystem` — 메모리 아닌 **디스크 버퍼**(50MB 메모리버퍼는 200노드 버스트에 과소)
- `multilineParser: cri` — CRI partial(P/F) 라인 재조립 **필수**
- `db` offset DB도 버퍼 경로에 · `skipLongLines` · `bufferMaxSize 8MB`(대형 스택 라인 수용)

### 3.3 FILTER (`ClusterFilter`, 이름 알파벳순 = 실행순서)
- **a-kubernetes**: `useKubelet: true` (+ `kubeletPort 10250`, RBAC `nodes/proxy`, hostNetwork 필요),
  `mergeLog: true`, `keepLog: false`(JSON 중복 제거), `k8sLoggingParser: false`(파서 중앙 통제)
- **b-multiline**: java/python — 워크로드별 match 분리 권장(혼합 오탐 방지)
- **c-throttle**: Spark만 캡(`match kube.*spark*`) — **드롭(무손실 아님)**, 노드별 rate
- **d-trim**: 노이즈 로그(`grep exclude` health/200) + 고용량 필드(`modify remove` filepath·annotations) 제거.
  ⚠ mandatory 필드(namespace/pod/container/host/workload)는 **절대 제거 금지**

### 3.4 OUTPUT (`ClusterOutput` opensearch)
- `logstashFormat: true` → `k8s-YYYY.MM.DD` 일배치 인덱스(ISM rollover 연계)
- `suppressTypeName: true`(OpenSearch 2.x 필수) · `generateID: true`(멱등)
- `Buffer_Size`는 **응답 읽기 버퍼**(호출빈도 아님) — 크게/`False` 권장
- 호출빈도·부하는 `flushSeconds`·청크크기·`workers`로 조절

---

## 4. 주의 / 함정 (실측 기반)

- **`Buffer_Size` ≠ 배치/호출 크기** — OpenSearch 응답 읽는 버퍼. 줄여도 호출 안 늘고, 너무 작으면 `could not flush` 에러.
- **`keepLog: false`의 사각지대** — JSON 로그가 `log` 필드를 잃어 본문 토큰 검색(`log:error`)에서 누락 →
  에러탐지 쿼리를 `msg`/구조화 필드까지 확장(`level:err* OR log:(...) OR msg:(...)`).
- **mandatory 필터에 level/severity 금지** — 구조화 로그에만 존재 → 평문(klog/postgres) 로그가 0건으로 사라짐.
- **useKubelet 전제** — `nodes/proxy` RBAC + hostNetwork. 보안정책이 hostNetwork 막으면 사용 불가.
- **CR 이름 알파벳순 = 체인 순서** — enrich(a)를 trim(d)보다 앞에. ClusterParser(`cri`/`klog`) export 포함 필수.

---

## 5. 검증 게이트

```bash
# 렌더 결과 확인
kubectl get secret <CFBC명> -n <ns> -o jsonpath='{.data.fluent-bit\.conf}' | base64 -d | less
# 버퍼 백로그 실측(버스트 때 쌓였다 빠지나)
curl -s http://<flb-pod>:2020/api/v1/storage | python3 -m json.tool
curl -s http://<flb-pod>:2020/api/v1/metrics | grep -E 'retried|dropped|errors'
```

---

_출처: fluent-bit container log pipeline 설계 논의 · airgap-obs-testbed · 2026-06-18_
