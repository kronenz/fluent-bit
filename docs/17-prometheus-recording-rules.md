# Prometheus 레코딩 룰 적용 가이드 (kube-prometheus-stack)

> 단일 파일 작업 브리프. 레코딩 룰을 **새로 만들거나 고칠 때** 이 문서만 보고 처음부터 끝까지 할 수 있게 썼다.

**Status**: active
**Owner**: kronenz
**Last revised**: 2026-08-05 (§9-0 ruleSelector 인식 조건 추가 — 렌더 4케이스 + 라이브 실측)
**Related**: `ops/airgap-obs-testbed/team-dashboard/deploy/01-queue-rules.yaml` (룰 정본),
`ops/airgap-obs-testbed/team-dashboard/deploy/rules-to-values.py` (values 변환기),
`ops/airgap-obs-testbed/base/helm-values/kps-values.yaml` (승격 대상),
`.claude/rules/grafana-opensearch-dashboards.md` (대시보드 쪽 함정),
`docs/work-history/2026-07-31-team-dashboard-variants.md`

---

## 1. Role and Context

당신은 obs 클러스터(kube-prometheus-stack `kps`)에 **레코딩 룰**을 추가·수정한다.

이 랩에서 레코딩 룰의 목적은 **쿼리 캐싱/속도가 아니라 정규화(normalization)** 다. 원본 메트릭이
대시보드에서 바로 쓰기엔 모양이 틀어져 있는 경우를 룰 계층에서 한 번 바로잡고, 대시보드는 깨끗한
이름만 참조하게 한다. 실제로 정규화한 것들:

- 큐 이름이 **라벨이 아니라 메트릭 이름 안에** 있다 (`yunikorn_fdc_queue_resource`) → `label_replace` 로 `queue` 라벨화
- 밀리코어 단위 → `/1000`
- 리프 큐 사용량이 **Prometheus 에 아예 없다**(YuniKorn 1.5.1은 root 만 노출) → k8s 요청량 × 큐 애노테이션 조인으로 재구성
- 팀/서비스 메타데이터가 메트릭에 없다 → `expr: "1"` 상수 룰(`queue:info`)에 라벨로 실어 조인 테이블로 사용

**안전 관점**: 레코딩 룰은 조용히 실패한다. 잘못 쓰면 에러가 아니라 **빈 시리즈**가 나오고, 그 위에
올린 대시보드는 "0" 또는 "정상"으로 보인다. 관측 못 하는 대상을 건강하다고 단언하게 되는 게 이 작업의
가장 큰 위험이다.

## 2. Topology

| 항목 | 값 (실측 2026-07-31) |
|---|---|
| Prometheus CR | `kps-prometheus` (ns `monitoring`) |
| `ruleSelector` | `matchLabels: {release: kps}` — values 미지정, **차트 기본값**에서 옴(§9-0) |
| `ruleNamespaceSelector` | `{}` (전 네임스페이스) |
| `evaluationInterval` | `30s` |
| `retention` | `3d` |
| `externalLabels` | `{cluster: obs}` — **주의: 로컬 저장 시리즈에는 안 붙는다(§4-2)** |
| 관리 주체 | ArgoCD app `kps` (현재 OutOfSync, autoSync **disabled**) |

현재 적용된 룰: `PrometheusRule/team-queue-normalize` (labels `app=team-dashboard`, `release=kps`),
5개 그룹 44룰, 전부 `health=ok`.

## 3. Target State

- `PrometheusRule` 이 `kubectl apply` 후 **30초 내** Prometheus 에 로드되고 `/api/v1/rules` 에서 `health=ok`
- 새 룰이 의도한 라벨 차원만 갖고, 의도한 시리즈 수를 돌려준다
- 대시보드가 원본 메트릭이 아니라 룰 이름만 참조한다
- 룰이 비면 **왜 비는지** 알 수 있다 (전제 조건이 문서화돼 있음)
- (정착 시) 룰과 그 **전제 조건이 git 에 있어** ArgoCD sync 가 설정을 되돌리지 않는다 (§9)

## 4. Hard Safety Rules

이 작업에 한해 편의보다 우선한다.

1. **`release: kps` 라벨 없이는 룰이 무시된다.** `ruleSelector` 가 `matchLabels: {release: kps}` 라서
   라벨이 없으면 `kubectl apply` 는 성공하고 Prometheus 는 **아무 말 없이 로드하지 않는다**.
   증상: `kubectl get prometheusrule` 에는 보이는데 `/api/v1/rules` 에는 없음.
   이 동작이 어디서 오는지와 values 로 푸는 법은 **§9-0**.

2. **`externalLabels` 를 믿고 `cluster` 를 생략하지 말 것.** `externalLabels: {cluster: obs}` 가 있어도
   그건 remote_write/federation/알림에만 붙고 **로컬 TSDB 시리즈에는 붙지 않는다.** 실측:

   ```
   count(up)                → 38
   count(up{cluster="obs"}) → 33     # 5개 타깃에 cluster 없음
   ```

   `cluster` 는 **ServiceMonitor 별 `relabelings`** 로 붙는다(이 클러스터의 관례). 현재 17개 중 13개만
   갖고 있고 `ism-explain-exporter`·`opensearch-exporter`·`kps-coredns`·`vmsingle` 은 없다.
   → 대시보드의 필수 필터 `cluster="$cluster"` 가 그 메트릭을 **통째로 탈락**시킨다.
   새 익스포터를 붙일 때 ServiceMonitor 에 relabeling 을 같이 넣을 것.

3. **상수 룰(`expr: "1"` 또는 숫자)은 `labels:` 에 `cluster` 를 직접 써야 한다.** 계산 결과가 아니라
   리터럴이라 어디서도 라벨이 따라오지 않는다.

4. **서로 의존하는 룰은 같은 그룹에 둔다.** 그룹 **안**에서는 순차 평가라 앞 룰의 결과를 뒤 룰이 바로
   쓸 수 있지만, **그룹끼리는 독립·병렬**이다. 현재 파일은 이 규칙을 어기고 있다(§7 참고).

5. **평문 자격증명 금지.** 검증 명령의 비밀번호는 `$GF_PASS` 등 환경변수로만.

6. **ArgoCD `kps` 를 함부로 sync 하지 말 것.** KSM 패치가 git 에 없어 sync 하면 되돌아간다(§5 Phase 1).
   → 이 위험을 없애는 게 **§9 (helm values 승격)** 이다. 승격을 마치면 sync 가 오히려 정본을 복원한다.

## 5. Phased Workflow

### Phase 1 — Discovery (읽기 전용)

**1-1. 원본 메트릭이 실제로 존재하는지 확인한다.** 추측 금지 — 룰을 쓰기 전에 항상 실측한다.

```bash
export KUBECONFIG=ops/airgap-obs-testbed/docs/obs.kubeconfig
GU=$(kubectl get secret -n monitoring kps-grafana -o jsonpath='{.data.admin-user}' | base64 -d)
GP=$(kubectl get secret -n monitoring kps-grafana -o jsonpath='{.data.admin-password}' | base64 -d)
PROXY=http://grafana.obs.k8s.miribit.lab/api/datasources/proxy/uid/prometheus/api/v1

# 이름 검색
curl -s -u "$GU:$GP" "$PROXY/label/__name__/values" \
  | python3 -c "import json,sys;[print(' ',n) for n in json.load(sys.stdin)['data'] if 'REPLACE_KEYWORD' in n]"

# 라벨 차원 확인 (제일 중요 — 조인 키가 여기서 정해진다)
curl -s -u "$GU:$GP" -G --data-urlencode 'query=REPLACE_METRIC' "$PROXY/query" \
  | python3 -m json.tool | head -40
```

**1-2. 전제 조건(하드 디펜던시)을 확인한다.** 이 랩의 사용량 룰은 kube-state-metrics 애노테이션
허용목록에 의존한다. 없으면 4개 룰이 **조용히 전멸**한다.

```bash
kubectl get deploy -n monitoring kps-kube-state-metrics -o json \
  | python3 -c "import json,sys;[print(' ',a) for c in json.load(sys.stdin)['spec']['template']['spec']['containers'] for a in c.get('args',[]) if 'allowlist' in a]"
# 기대: --metric-annotations-allowlist=pods=[yunikorn.apache.org/queue]

curl -s -u "$GU:$GP" -G --data-urlencode \
  'query=count(kube_pod_annotations{annotation_yunikorn_apache_org_queue!=""})' "$PROXY/query"
# 0 이면 queue:used_* 계열이 전부 빈다
```

> ⚠ **이 패치는 현재 git 에 없고 라이브 클러스터에만 있다.** ArgoCD 가 `kps-kube-state-metrics` 를
> OutOfSync 로 잡고 있어, `kps` 를 sync 하면 되돌아가고 `queue:used_vcores`·`used_memory_bytes`·
> `used_pods`·`consumed_vcores` 가 비게 된다. autoSync 는 꺼져 있어 지금은 안전하다.
> 룰을 오래 유지하려면 **helm values 로 승격해 커밋**해야 한다 → **§9**.

**🟡 Checkpoint 1**: 원본 메트릭 이름·라벨 목록을 적어두고, 전제 조건이 충족됐음을 출력으로 확인했다.

### Phase 2 — 룰 작성

**2-1. 이름 규칙**: `level:metric:operation` (Prometheus 관례). 이 랩의 level 은 집계 축을 뜻한다.

| level | 뜻 | 예 |
|---|---|---|
| `queue:` | 큐 1개당 1시리즈 | `queue:used_vcores` |
| `team:` | 팀 1개당 1시리즈 | `team:quota_vcores` |
| `cluster:` | 클러스터 전체 1시리즈 | `cluster:capacity_vcores` |

**2-2. 그룹 배치**: 의존하는 룰은 **같은 그룹에, 의존 대상보다 뒤에** 놓는다(§4-4).

**2-3. 라벨 위생**: 조인·표시에 쓸 라벨만 남기고 나머지는 **룰 단계에서 벗긴다.** 대시보드
transform 으로 지우는 건 위치 의존적이라 프레임 수가 바뀌면 깨진다.

```promql
# 나쁨 — resource/state/project/namespace/pod/container/job/instance/endpoint/service 가 전부 따라온다
queue:quota_vcores{cluster="$cluster"}

# 좋음 — 조인 키만 남긴다
max by (cluster, queue) (queue:quota_vcores{cluster="$cluster"})
```

`sum` 이 아니라 `max` 를 쓴 이유: 지금은 큐당 1시리즈라 둘 다 같지만, 스케줄러 replica 가 늘면
`sum` 은 조용히 2배가 된다. **집계 함수는 "중복이 생겨도 맞는" 쪽을 고른다.**

**🟡 Checkpoint 2**: 룰마다 결과 라벨 차원을 주석으로 적었다.

### Phase 3 — 적용

경로가 둘이다. **운영 정착은 B(helm values)** 가 정답이고, A 는 반복 개발 중에만 쓴다.

| | A. `kubectl apply` (CR 직접) | B. helm values (§9) |
|---|---|---|
| 반영 속도 | 즉시 | 커밋 → ArgoCD sync |
| `release: kps` 라벨 | **직접 써야 함**(빠뜨리면 조용히 무시) | 차트가 자동 부착 |
| ArgoCD sync 시 | 앱 밖 리소스라 무관하지만, **전제 조건(KSM)이 날아갈 수 있다** | sync 가 정본을 복원 |
| 용도 | 룰 개발·시행착오 | 정착 |

**A — 개발 중 빠른 반영**

```bash
kubectl apply -f ops/airgap-obs-testbed/team-dashboard/deploy/01-queue-rules.yaml
# 로드 확인 (evaluationInterval 30s → 최대 30초 대기)
kubectl get prometheusrule -n monitoring team-queue-normalize \
  -o jsonpath='{.metadata.labels}{"\n"}'   # release: kps 확인
```

Prometheus 재시작 불필요 — operator 가 configmap-reload 로 반영한다.

**B — 정착**: §9 으로.

### Phase 4 — 검증 (완료 선언 전 필수)

**4-1. 룰이 로드됐고 건강한가**

`PREFIX` 는 내 그룹 이름의 접두사(예: `queue-`, `team-`). 안 걸러면 kube-prometheus 기본 룰 15개
그룹까지 같이 나와 내 것을 놓친다.

```bash
PREFIX='queue-|team-'
curl -s -u "$GU:$GP" "$PROXY/rules?type=record" | PREFIX="$PREFIX" python3 -c "
import json,os,re,sys
pat=re.compile('^('+os.environ['PREFIX']+')')
gs=[g for g in json.load(sys.stdin)['data']['groups'] if pat.match(g['name'])]
if not gs: print('  ✗ 그룹 없음 — release: kps 라벨을 확인할 것'); sys.exit(1)
for g in gs:
    bad=[r['name'] for r in g['rules'] if r.get('health')!='ok']
    print(f\"  {g['name']:20} rules={len(g['rules']):2} eval={g['evaluationTime']:.4f}s \"
          f\"{'ok' if not bad else 'BAD: '+str(bad)}\")"
```

**4-2. 시리즈 수가 기대와 맞는가** — 0 도, 예상보다 많은 것도 둘 다 버그다.

```bash
for m in queue:info queue:quota_vcores queue:used_vcores queue:utilization_vcores; do
  n=$(curl -s -u "$GU:$GP" -G --data-urlencode "query=count($m)" "$PROXY/query" \
      | python3 -c "import json,sys;r=json.load(sys.stdin)['data']['result'];print(r[0]['value'][1] if r else 0)")
  printf '  %-28s %s\n' "$m" "$n"
done
```

**4-3. 독립 경로 대조** — 최소 1개 룰은 다른 경로로 구한 값과 맞춰본다. 조인이 틀려도 그럴듯한 숫자가
나오기 때문에 이 단계 없이는 정합성을 못 믿는다.

`queue:used_*` 계열은 **YuniKorn REST 의 `allocatedResource`** 와 대조할 수 있다. 룰은 k8s 요청량 ×
애노테이션 조인으로 재구성한 값이고 REST 는 스케줄러가 실제로 할당한 값이라, 경로가 완전히 독립이다.

> ⚠ `kubectl exec` 는 안 된다 — 스케줄러 이미지는 **distroless 라 셸도 wget 도 없다**
> (`exec: "sh": executable file not found`). **port-forward 로 접근**할 것.

```bash
kubectl port-forward -n yunikorn svc/yunikorn-service 19080:9080 >/dev/null 2>&1 &
PF=$!
until curl -s -m 1 -o /dev/null http://127.0.0.1:19080/ws/v1/partitions; do sleep 0.5; done

curl -s http://127.0.0.1:19080/ws/v1/partition/default/queues | python3 -c "
import json,sys
def walk(q, d=0):
    a = q.get('allocatedResource') or {}
    if a: print(f\"  {'  '*d}{q['queuename']:22} {a}\")
    for c in q.get('children') or []: walk(c, d+1)
walk(json.load(sys.stdin))"
kill $PF
```

실측 대조 결과 (2026-07-31) — 세 룰이 전부 정확히 일치했다:

| 룰 | 룰 값 | REST `allocatedResource` |
|---|---|---|
| `queue:used_vcores{queue="root.fdc"}` | `1.5` | `vcore: 1500` (밀리코어) ✓ |
| `queue:used_memory_bytes{queue="root.fdc"}` | `1610612736` | `memory: 1610612736` ✓ |
| `queue:used_pods{queue="root.fdc"}` | `3` | `pods: 3` ✓ |

> REST 는 **할당이 있는 큐만** 돌려준다(현재 root.fdc·root.smartbig). 나머지 4개가 안 보이는 건
> 정상이며, 이게 곧 "미관측이 아니라 진짜 할당 0"임을 확인해 주는 근거이기도 하다.
> 단 `queue:used_*` 쪽은 **시리즈 자체가 없어** 패널에서는 0 이 아니라 "관측 없음"으로 다뤄야 한다.

**4-4. 연산자 우선순위 함정 검산** — PromQL 은 `/` 가 좌결합이라 아래가 서로 다르다.

```promql
X / on(queue) group_left() Y / 1000     # (X/Y)/1000  ← 의도와 다름
X / on(queue) group_left() (Y / 1000)   # 의도한 것
```

과거 이 실수로 25.86% 가 0.00% 로 나왔다. **나눗셈이 2개 이상이면 반드시 괄호**를 치고 손계산으로 확인.

**4-5. 그룹 간 의존 검사** (§4-4 위반 탐지) — 정적 검사라 클러스터 없이도 돌릴 수 있다.

```bash
python3 - 01-queue-rules.yaml <<'PY'
import re, sys, yaml
d = yaml.safe_load(open(sys.argv[1]).read())
produced = {}
for g in d["spec"]["groups"]:
    for r in g.get("rules", []):
        produced.setdefault(r["record"], g["name"])
bad = 0
for g in d["spec"]["groups"]:
    for r in g.get("rules", []):
        for name, src in produced.items():
            if name == r["record"]:
                continue
            if re.search(r"\b" + re.escape(name) + r"\b", r.get("expr", "")) and src != g["name"]:
                print(f"  ✗ {r['record']:28} [{g['name']}] 가 {name} [{src}] 참조 — 그룹 다름")
                bad += 1
print("  ✓ 그룹 간 의존 없음" if not bad else f"  {bad}건")
PY
```

현재 파일은 **10건 검출**된다(§7). 자체 회복되는 성질이라 지금 당장 깨지진 않지만, 새 룰을 추가할 때는
이 검사가 0 이 되게 배치할 것.

**🟡 Checkpoint 4**: 4-1~4-5 전부 통과. 대시보드가 있다면
`ops/airgap-obs-testbed/team-dashboard/deploy/verify.py` 도 통과.

## 6. Reference Templates

### 6-1. 골격

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: REPLACE_NAME
  namespace: monitoring
  labels:
    release: kps            # ★ 없으면 ruleSelector 에 안 걸려 조용히 무시된다
    app: REPLACE_APP
spec:
  groups:
    - name: REPLACE_GROUP
      interval: 30s
      rules:
        - record: level:metric:operation
          expr: |
            REPLACE_PROMQL
```

### 6-2. 메트릭 **이름**에 든 차원을 라벨로 끌어내기

YuniKorn 1.5.1은 큐 이름이 메트릭 이름 안에 있다(`yunikorn_fdc_queue_resource`). 게다가 애노테이션
표기(`root.fdc`)와 달라 접두사를 붙여야 한다.

```yaml
- record: queue:quota_vcores
  expr: |
    label_replace(
      {__name__=~"yunikorn_[a-z0-9]+_queue_resource",
       __name__!="yunikorn_root_queue_resource",     # root 는 클러스터 총량이라 제외
       resource="vcore", state="guaranteed"},
      "queue", "root.$1", "__name__", "yunikorn_(.+)_queue_resource"
    ) / 1000                                          # 밀리코어 → 코어
```

### 6-3. 메트릭에 없는 사용량을 k8s 에서 재구성 (애노테이션 조인)

```yaml
- record: queue:used_vcores
  expr: |
    sum by (cluster, queue) (
      kube_pod_container_resource_requests{resource="cpu"}
      * on (namespace, pod) group_left(queue)
      label_replace(
        kube_pod_annotations{annotation_yunikorn_apache_org_queue!=""},
        "queue", "$1", "annotation_yunikorn_apache_org_queue", "(.+)")
    )
```

전제: KSM `--metric-annotations-allowlist=pods=[yunikorn.apache.org/queue]` (§5 Phase 1-2).

### 6-4. 메타데이터 조인 테이블 (상수 룰)

메트릭에 없는 팀/서비스 정보를 값 `1` 짜리 시리즈의 **라벨**로 싣는다. 이후 `group_left` 로 붙인다.

```yaml
- record: queue:info
  expr: "1"
  labels:
    cluster: obs            # ★ 상수 룰은 cluster 를 직접 써야 한다
    queue: root.fdc
    service: FDC
    team: "AI/Data Platform"
    ldap: fdc
    ns_app: app-fdc
```

사용:

```promql
sum by (cluster, team) (
  queue:used_vcores * on (cluster, queue) group_left(team) queue:info
)
```

> 표시용 자유 텍스트(`bucket: "fdc, ic-lfdc, ic-m…"` 같은 잘린 목록)는 라벨에 넣어도 되지만
> **조인 키로는 쓸 수 없다.** 값이 사람이 읽는 문자열이지 식별자가 아니다.

### 6-5. 비율 룰

```yaml
- record: queue:utilization_vcores
  expr: queue:used_vcores / on (cluster, queue) group_left() queue:quota_vcores
```

결과는 **0..1 스케일**이다. 대시보드에서 `unit: percentunit` + 임계 `0.75/0.90/1.00` 로 받는다.
`40/55/…` 같은 0..100 임계를 주면 전 값이 최저 구간에 몰려 **에러 없이 균일하게** 렌더된다.

### 6-6. 랩 스케일 상수

실계 값을 랩 크기로 줄여 쓸 때, 원래 값을 **라벨로 보존**해 나중에 되찾을 수 있게 한다.

```yaml
- record: cluster:shared_pool_vcores
  expr: "6.768"
  labels: {cluster: obs, scale: "lab-1/500", real_value: "3384"}
```

⚠ `real_value` 는 **라벨(문자열)** 이라 산술에 못 쓴다. 계산에 쓰려면 별도 룰로 만들 것
(`cluster:plan_shared_pool_vcores` = `3384`).

## 7. 이 리포의 현재 룰에서 고칠 점 (미조치)

발견했으나 이번 작업 범위 밖이라 손대지 않았다. 다음에 이 파일을 만질 때 같이 처리할 것.

- ★ **그룹 간 의존이 있다.** `queue-utilization` 그룹의 룰이 `queue-quota`·`queue-usage` 그룹의 결과를
  참조하고, `team-rollup` 도 마찬가지다. 그룹은 서로 **독립·병렬 평가**라, 콜드 스타트나 입력 룰이
  바뀐 직후 한 인터벌(30s) 동안 **낡은 값 또는 빈 값**으로 계산될 수 있다. 자체 회복되므로 치명적이진
  않지만, 의존 룰은 같은 그룹에 순서대로 두는 게 정석이다.
- **`team:quota_vcores:ratio`** 라는 이름이 TSDB 에 남아 있는데 정의된 룰이 없다(현재 빈 시리즈).
  과거 룰의 잔재로 보인다 — retention 3d 지나면 사라진다.
- **memory 쿼터는 랩 임시치**(scaled vcore × 2Gi). YuniKorn 이 실제로 memory 로 스케줄하는데 원본
  배분표에 memory 열이 없어 생긴 공백. 실제 큐 memory 쿼터를 받으면 그게 정본이 되어야 한다.
- **`queue:plan_trino_vcores`·`queue:plan_pods` 는 `root.fdc`/`root.yms` 에 시리즈가 없다**(원본 표의
  병합 셀 = 팀 공통). 0 이 아니라 **부재**이므로 패널에서 "없음"으로 다뤄야 한다.

## 8. Things NOT to Do

- **속도 목적으로 룰을 만들지 말 것.** 이 랩의 데이터 크기에서 쿼리 속도는 문제가 아니다. 룰이 늘면
  카디널리티와 유지보수 비용만 는다. 정규화·재구성·상수화 셋 중 하나에 해당할 때만 만든다.
- **대시보드에서 쓸 수 있는 걸 룰로 옮기지 말 것.** 한 패널에서만 쓰는 표현식은 패널에 두는 게 낫다.
  룰은 **여러 대시보드가 공유**하거나 **원본이 그대로는 못 쓸 때**만.
- **`scrape_interval` 보다 짧은 `interval` 금지.**
- **없는 값을 0 으로 채워 룰에 굳히지 말 것.** zero-fill 은 표시 계층(패널)에서 한다. 룰에서 0 으로
  만들면 "미관측"과 "진짜 0"을 영구히 구분할 수 없게 된다.
- **ArgoCD `kps` sync 를 이 작업의 일부로 실행하지 말 것** (§4-6).

## 9. helm values 로 승격 (kube-prometheus-stack 73.1.0) — 권장 경로

이 절의 모든 키·라벨·이름은 **73.1.0 차트 실물을 내려받아 `helm template` 으로 렌더해 확인**했다.
추측한 값 없음.

### 9-0. 룰 yaml 이 인식되게 하려면 — values 에서 무엇을 켜야 하나

**결론: 켤 것이 없다. 이미 켜져 있다.** 차트 기본값 `ruleSelectorNilUsesHelmValues: true` 가
`ruleSelector: {matchLabels: {release: kps}}` 를 만들고, 오퍼레이터는 그 라벨로 룰을 고른다.
→ **values 를 안 건드리고 룰 yaml 에 `release: kps` 라벨만 붙이면 인식된다.**

렌더 로직(73.1.0 `templates/prometheus/prometheus.yaml` 253-262행) — 3분기다:

```gotemplate
{{- if .Values.prometheus.prometheusSpec.ruleSelector }}
  ruleSelector: {{ 값 그대로 }}
{{- else if .Values.prometheus.prometheusSpec.ruleSelectorNilUsesHelmValues }}
  ruleSelector:
    matchLabels:
      release: "kps"                     ← 기본값이 여기로 온다
{{ else }}
  ruleSelector: {}                       ← 모든 PrometheusRule 수용
{{- end }}
```

`helm template` 로 실제 렌더해 확인한 4가지:

| values 설정 | 렌더된 `ruleSelector` | 룰 yaml 에 라벨 |
|---|---|---|
| (미지정 — **현재**) | `{matchLabels: {release: kps}}` | **`release: kps` 필요** |
| `ruleSelectorNilUsesHelmValues: false` | `{}` | 불필요 (아무 라벨이나) |
| `ruleSelector: {matchLabels: {prometheus-rule: team-dashboard}}` | 그대로 | 그 라벨 필요 |
| `+ ruleNamespaceSelector: {matchLabels: {monitoring: "true"}}` | ns 도 제한 | ns 라벨도 필요 |

`ruleNamespaceSelector` 기본값은 `{}` = **전 네임스페이스**. 그래서 룰을 `monitoring` 밖에 둬도 된다.

**실측(라이브)** — 라벨 유무만 바꿔 확인했다:

```
① 라벨 없이 apply  → kubectl 성공, 리소스 존재, 그런데 /api/v1/rules 에 없음  ✗
② release=kps 라벨 추가 → 35초 내 등장                                      ✓  (재시작 불필요)
```

★ **이게 §4-1 이 말하는 "조용한 실패" 의 정체다.** apply 가 성공하고 `kubectl get prometheusrule`
에도 보이므로 배포된 줄 안다. 오퍼레이터만 말없이 건너뛴다.

★ **현재 이 리포의 values 에는 비대칭이 있다.**

```yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false   # ← ServiceMonitor 는 라벨 불필요
    podMonitorSelectorNilUsesHelmValues: false       # ← PodMonitor 도 불필요
    # ruleSelectorNilUsesHelmValues 는 미지정 → 기본 true → 룰만 라벨 필요
```

ServiceMonitor·PodMonitor 는 라벨 없이 받게 풀어놨는데 **룰만 라벨을 요구**한다. 의도한 것이 아니라면
아래 한 줄로 셋을 맞출 수 있다(그러면 라벨 누락 사고 자체가 사라진다):

```yaml
prometheus:
  prometheusSpec:
    ruleSelectorNilUsesHelmValues: false
```

단, 푸는 순간 **클러스터의 모든 PrometheusRule 을 무조건 로드**한다. 남이 만든 룰까지 들어오므로
멀티테넌트라면 그대로 두고 라벨을 붙이는 편이 안전하다. §9-2 처럼 values 경로로 룰을 넣으면
차트가 라벨을 자동으로 붙여주므로 **이 설정을 건드릴 이유가 없다.**

### 9-1. 왜 옮기는가

룰을 `kubectl apply` 로만 넣어두면 두 가지가 깨진다.

1. **`release: kps` 라벨을 사람이 기억해야 한다.** 빠뜨리면 apply 는 성공하고 Prometheus 는
   조용히 무시한다(§4-1).
2. **더 위험한 건 전제 조건이다.** KSM allowlist 는 현재 **라이브에만 있고 git 에 없다**.
   ArgoCD 가 `kps-kube-state-metrics` 를 OutOfSync 로 잡고 있어 sync 한 번에 되돌아가고
   `queue:used_*` 4종이 조용히 빈다(§5 Phase 1-2). values 로 올려 두면 sync 가 오히려
   **정본을 복원하는 방향**으로 바뀐다.

### 9-2. 룰 — `additionalPrometheusRulesMap`

```yaml
# kps-values.yaml
additionalPrometheusRulesMap:
  team-queue-normalize:              # ← 맵 키가 리소스 이름 일부가 된다
    groups:
      - name: queue-quota
        interval: 30s
        rules:
          - record: queue:quota_vcores
            expr: |
              label_replace(...) / 1000
```

★ **`release: kps` 를 직접 쓰지 말 것.** 차트가 붙인다 — `_helpers.tpl` 의
`kube-prometheus-stack.labels` 에 `release: {{ $.Release.Name | quote }}` 가 있고,
`prometheusSpec.ruleSelectorNilUsesHelmValues` 기본값이 `true` 라 오퍼레이터가 그 라벨로 고른다.
(라이브 CR 도 `ruleSelector: {matchLabels: {release: kps}}` 로 확인)
→ **values 경로에서는 §4-1 의 라벨 누락 사고가 원천 차단된다.**

★ **이름이 바뀐다 — 전환 시 룰이 두 벌 돈다.** 렌더 실측:

```
name: kube-prometheus-stack-team-queue-normalize      ← kps- 로 시작하지 않는다
```

템플릿이 `fullnameOverride`(=`kps`)가 아니라 **`nameOverride` 를 따르는 `name` 헬퍼**를 쓴다.
기존 CR 이름은 `team-queue-normalize` 라 **이름이 달라 공존**한다. 같은 룰이 두 벌 평가되므로
전환 후 반드시 이전 CR 을 지운다:

```bash
kubectl delete prometheusrule -n monitoring team-queue-normalize
```

### 9-3. 전제 조건도 같이 올린다 — KSM allowlist

`extraArgs` 를 쓸 필요 없다. KSM 서브차트(5.33.x)에 **전용 값**이 있다.

```yaml
kube-state-metrics:
  metricAnnotationsAllowList:        # ← List  (대문자 L)
    - pods=[yunikorn.apache.org/queue]
  metricLabelsAllowlist:             # ← list  (소문자 l)
    - pods=[service,team]
    - namespaces=[team,service,queue,tier]
  prometheus:                        # 기존 cluster relabeling 유지 (§4-2)
    monitor:
      relabelings:
        - replacement: obs
          targetLabel: cluster
```

★ **두 키의 대소문자가 서로 다르다** (`AllowList` vs `Allowlist`, 차트 values.yaml 397·406행).
Helm 은 모르는 값을 **에러 없이 무시**하므로 오타 나면 조용히 안 먹는다. 렌더로 확인할 것.

렌더 결과가 라이브 args 와 **문자열까지 동일**함을 확인했다 — 즉 이 값으로 sync 하면 패치가
되돌아가는 게 아니라 그대로 재현된다:

```
- --metric-labels-allowlist=pods=[service,team],namespaces=[team,service,queue,tier]
- --metric-annotations-allowlist=pods=[yunikorn.apache.org/queue]
```

### 9-4. 변환은 손으로 하지 않는다

정본은 `01-queue-rules.yaml` 이고, values 스니펫은 **생성물**이다.

```bash
python3 ops/airgap-obs-testbed/team-dashboard/deploy/rules-to-values.py
#   → ops/airgap-obs-testbed/base/helm-values/_kps-values-rules-snippet.yaml
python3 ops/airgap-obs-testbed/team-dashboard/deploy/rules-to-values.py --check   # CI: 정본과 일치 확인
```

여러 줄 PromQL 을 블록 스칼라(`|`)로 내보내므로 사람이 읽고 고칠 수 있다.
(PyYAML 기본 출력은 `\n` 이스케이프된 한 줄이라 사실상 수정 불가)

★ **주석은 변환에서 사라진다.** `01-queue-rules.yaml` 에는 함정 설명이 많다(밀리코어 `/1000`,
`root` 제외 이유, 병합셀 `scope` 라벨…). values 를 직접 손대기 시작하면 그 맥락이 영구히 없어진다.
**정본은 항상 원본 CR 파일**로 두고 스니펫은 재생성만 할 것.

### 9-5. 적용 절차

```bash
# 1) 스니펫 재생성
python3 ops/airgap-obs-testbed/team-dashboard/deploy/rules-to-values.py

# 2) kps-values.yaml 에 병합 (additionalPrometheusRulesMap + kube-state-metrics)

# 3) 커밋 전에 렌더로 미리 확인 — sync 후에 발견하면 늦다
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

V=ops/airgap-obs-testbed/base/helm-values
# 병합 전에도 확인할 수 있게 스니펫을 -f 로 함께 준다 (병합 후엔 두 번째 -f 를 빼면 된다)
helm template kps prometheus-community/kube-prometheus-stack --version 73.1.0 \
  -n monitoring -f $V/kps-values.yaml -f $V/_kps-values-rules-snippet.yaml \
  --show-only templates/prometheus/additionalPrometheusRules.yaml \
  | grep -E "^      name:|release:|- name: "

helm template kps prometheus-community/kube-prometheus-stack --version 73.1.0 \
  -n monitoring -f $V/kps-values.yaml \
  --show-only charts/kube-state-metrics/templates/deployment.yaml | grep allowlist
```

> ⚠ **`--show-only` 의 에러 메시지가 오해를 부른다.** 해당 템플릿이 아무것도 렌더하지 않으면
> helm 은 빈 출력이 아니라
> `Error: could not find template templates/prometheus/additionalPrometheusRules.yaml in chart`
> 를 낸다. **템플릿이 없다는 뜻이 아니라 값이 비어 있다는 뜻**이다
> (`additionalPrometheusRulesMap` 이 `{}` 면 `{{- if }}` 가 통째로 걸러진다).
> KSM 쪽 `grep allowlist` 가 아무것도 못 찾는 것도 같은 이유 — 값을 아직 안 넣은 것이다.

```bash

# 4) 커밋 → ArgoCD sync (앱: kps)

# 5) 이전 CR 삭제 — 안 하면 룰이 두 벌 돈다
kubectl delete prometheusrule -n monitoring team-queue-normalize

# 6) Phase 4 검증 전부 재실행 (특히 4-2 시리즈 수, 4-3 REST 대조)
```

### 9-6. sync 직후 반드시 확인할 것

ArgoCD sync 는 kps 의 **다른 드리프트도 함께** 적용한다. 룰만 보지 말고 전제 조건을 다시 본다.

```bash
# 전제 조건이 살아 있나 (0 이면 queue:used_* 가 전멸한 것)
curl -s -u "$GU:$GP" -G --data-urlencode \
  'query=count(kube_pod_annotations{annotation_yunikorn_apache_org_queue!=""})' "$PROXY/query"

# 룰이 한 벌만 도는가 (2 면 이전 CR 을 안 지운 것)
kubectl get prometheusrule -A -o json | python3 -c "
import json,sys
n=[i['metadata']['name'] for i in json.load(sys.stdin)['items']
   if any(g['name'].startswith(('queue-','team-')) for g in i['spec']['groups'])]
print('  룰 리소스:', n, '→', 'OK' if len(n)==1 else '⚠ 중복')"
```

### 9-7. 롤백

values 를 되돌리고 sync 하면 `additionalPrometheusRulesMap` 이 만든 CR 은 ArgoCD 가 회수한다.
급하면 A 경로(`kubectl apply -f 01-queue-rules.yaml`)로 즉시 복구할 수 있다 — 이름이 달라
values 판과 충돌하지 않는다. 단 **복구 후 한쪽을 반드시 정리**할 것(10-6 중복 검사).

## 10. Definition of Done

- [ ] `PrometheusRule` 에 `release: kps` 라벨이 있다
- [ ] `/api/v1/rules?type=record` 에서 새 그룹이 보이고 전 룰 `health=ok`
- [ ] 각 룰의 시리즈 수가 기대치와 일치 (0 도 초과도 아님)
- [ ] 최소 1개 룰을 독립 경로(REST API·손계산)로 대조해 값이 맞다
- [ ] 나눗셈 2개 이상인 식은 괄호가 있고 손계산으로 확인됐다
- [ ] 새로 추가한 룰에 대해 그룹 간 의존 검사(4-5)가 늘지 않았다
- [ ] 결과 라벨 차원이 룰마다 주석으로 적혀 있다
- [ ] 전제 조건(KSM allowlist, ServiceMonitor cluster relabeling)이 문서에 남았다
- [ ] 대시보드가 있다면 `deploy/verify.py` 통과

**helm values 로 정착시킨 경우 (§9) 추가로:**

- [ ] `rules-to-values.py --check` 통과 (스니펫이 룰 정본과 일치)
- [ ] `helm template` 렌더 결과에 `release: "kps"` 라벨이 있다
- [ ] KSM allowlist 렌더 결과가 기존 라이브 args 와 문자열까지 같다
- [ ] sync 후 이전 CR(`team-queue-normalize`)을 삭제해 **룰이 한 벌만** 돈다 (§9-6)
- [ ] sync 후 `kube_pod_annotations{annotation_yunikorn_apache_org_queue!=""}` 가 0 이 아니다

최종 보고: 룰 이름 · 그룹 · 라벨 차원 · 시리즈 수 표.
