# fluent-bit 워크로드 메타 병합 — Owner_References + lua 필터 구성 가이드

> 목적: 컨테이너 로그에 `kubernetes.workload_kind` / `kubernetes.workload_name` 필드를 추가하여
> OpenSearch/Grafana에서 Deployment / StatefulSet / DaemonSet 단위로 로그를 필터링한다.
> 배경: Grafana는 OpenSearch(로그)와 Prometheus(메트릭)를 한 쿼리에서 조인할 수 없으므로,
> 워크로드 단위 필터는 **수집 시점에 fluent-bit가 로그 레코드에 병합**하는 방식으로 해결한다.
> 실제 배포본: `ops/logging/fluentbit-kubernetes-pipeline.yaml`

---

## 1. 전제 조건 (둘 다 필수)

| 항목 | 요구사항 | 미충족 시 증상 |
|---|---|---|
| fluent-bit 버전 | **>= 3.2** (`Owner_References` 지원) | 3.1.x는 `unknown configuration property 'owner_references'`로 **기동 실패** |
| 이미지 (fluent-operator 사용 시) | **`ghcr.io/fluent/fluent-operator/fluent-bit:3.2.x`** (config watcher 내장) | 업스트림 `fluent/fluent-bit` 이미지는 operator 생성 설정을 읽지 않고 기본 설정(cpu→stdout)으로 떠서 **아무것도 수집 안 됨** |
| RBAC | fluent-bit SA에 `pods get` | kubernetes 필터가 메타를 못 붙임 (보통 이미 있음) |

버전 사전 검증 (인터넷 가능한 곳에서):

```bash
docker run --rm <이미지> /fluent-bit/bin/fluent-bit \
  -i dummy -F kubernetes -p Owner_References=On -m '*' -o null
# "unknown configuration property 'owner_references'" 출력 시 버전 미달
```

---

## 2. 필터 체인 구성

처리 순서가 중요하다: **rename → kubernetes(Owner_References) → lua** 순.

### 2.1 classic 설정 (fluent-bit.conf 직접 관리 시)

```
# (1) CRI 파서 출력 키 message → log (kubernetes 필터 Merge_Log가 log 키만 JSON 파싱)
[FILTER]
    Name          modify
    Match         kube.*
    Hard_rename   message log

# (2) kubernetes 메타 + ownerReferences 부착
[FILTER]
    Name             kubernetes
    Match            kube.*
    Kube_URL         https://kubernetes.default.svc:443
    Kube_CA_File     /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    Kube_Token_File  /var/run/secrets/kubernetes.io/serviceaccount/token
    Kube_Tag_Prefix  kube.var.log.containers.
    Labels           On
    Annotations      Off
    Merge_Log        On
    Keep_Log         On
    Owner_References On
    Buffer_Size      512k

# (3) 워크로드 파생
[FILTER]
    Name           lua
    Match          kube.*
    script         workload.lua
    call           derive_workload
    time_as_table  true
```

### 2.2 fluent-operator CRD (fluentbit.fluent.io/v1alpha2)

CRD의 typed `kubernetes:` 필드에는 `ownerReferences`가 **없으므로** `customPlugin`(raw)으로 쓴다.
lua 스크립트는 fluent-bit 네임스페이스의 ConfigMap으로 두면 operator가 자동 마운트한다.

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterFilter
metadata:
  name: kubernetes-enrich
  labels: { fluentbit.fluent.io/enabled: "true", pipeline: kubernetes }
spec:
  match: kube.*
  filters:
    - modify:
        rules:
          - hardRename: { message: log }
    - customPlugin:
        config: |
          Name             kubernetes
          Match            kube.*
          Kube_URL         https://kubernetes.default.svc:443
          Kube_CA_File     /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
          Kube_Token_File  /var/run/secrets/kubernetes.io/serviceaccount/token
          Kube_Tag_Prefix  kube.var.log.containers.
          Labels           On
          Annotations      Off
          Merge_Log        On
          Keep_Log         On
          Owner_References On
          Buffer_Size      512k
    - lua:
        script:
          name: fluent-bit-lua      # 아래 ConfigMap
          key: workload.lua
        call: derive_workload
        timeAsTable: true
```

---

## 3. lua 스크립트 전문 (workload.lua)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-lua
  namespace: logging               # fluent-bit가 도는 네임스페이스
data:
  workload.lua: |
    function derive_workload(tag, ts, record)
      local k = record["kubernetes"]
      if k == nil then
        return 0, ts, record
      end
      local kind = "Pod"
      local name = k["pod_name"] or "unknown"
      local owners = k["ownerReferences"] or k["owner_references"]
      if owners ~= nil and owners[1] ~= nil then
        kind = owners[1]["kind"] or kind
        name = owners[1]["name"] or name
        if kind == "ReplicaSet" then
          -- Deployment 환원: ReplicaSet 이름 끝 -<hash> 제거
          local base = string.match(name, "^(.+)%-[a-z0-9]+$")
          if base ~= nil then
            kind = "Deployment"
            name = base
          end
        elseif kind == "Job" then
          -- CronJob 환원: Job 이름이 -<숫자>(스케줄 타임스탬프)로 끝나는 경우
          local base = string.match(name, "^(.+)%-%d+$")
          if base ~= nil then
            kind = "CronJob"
            name = base
          end
        end
      end
      k["workload_kind"] = kind
      k["workload_name"] = name
      k["ownerReferences"] = nil       -- 원본 제거(색인 용량 절감)
      k["owner_references"] = nil
      record["kubernetes"] = k
      record["cluster"] = "CHANGE-ME"  -- 클러스터 식별 라벨(환경별 수정)
      record["log_source"] = "kubernetes"
      return 2, ts, record
    end
```

리턴 코드 의미: `2` = 레코드 수정됨(타임스탬프 유지), `0` = 수정 없음.

---

## 4. 파생 규칙

ownerReferences는 Pod의 **직접 소유자**만 가리키므로 lua에서 환원한다.

| Pod 소유자 (ownerReferences[0].kind) | 파생 결과 workload_kind | workload_name |
|---|---|---|
| ReplicaSet (`myapp-7f9c8d6b5`) | **Deployment** | `myapp` (끝 -hash 제거) |
| StatefulSet | StatefulSet | 그대로 |
| DaemonSet | DaemonSet | 그대로 |
| Job (`backup-1781065200`) | **CronJob** | `backup` (끝 -숫자 제거) |
| Job (숫자 접미사 없음) | Job | 그대로 |
| Node | **Node** (= static pod: kube-apiserver, controller-manager, scheduler, etcd) | 노드 이름 |
| (소유자 없음) | Pod | pod_name |

알려진 한계: Deployment 없이 직접 만든 ReplicaSet도 Deployment로 환원된다(실무상 드묾).

---

## 5. 검증

적용 후 **신규 문서부터** 필드가 붙는다(기존 인덱스는 백필 안 됨).

```bash
# 1) 필드 존재 확인
curl -s "localhost:9200/kubernetes-*/_search?size=1&pretty" \
  -H 'Content-Type: application/json' \
  -d '{"query":{"exists":{"field":"kubernetes.workload_kind"}}}'

# 2) 종류 분포 확인 — DaemonSet/Deployment/StatefulSet/Node 등이 나오면 정상
curl -s "localhost:9200/kubernetes-*/_search?size=0" \
  -H 'Content-Type: application/json' \
  -d '{"aggs":{"k":{"terms":{"field":"kubernetes.workload_kind.keyword"}}}}'
```

정상 예: `openstack-cinder-csi-controllerplugin-bf8ffc8bc-s7mhc` →
`workload_kind=Deployment`, `workload_name=openstack-cinder-csi-controllerplugin`.

트러블슈팅:
- 필드가 안 붙음 → fluent-bit 로그에서 lua 에러 확인, 렌더링된 설정(operator는 ClusterFluentBitConfig 이름과 같은 Secret)에서 [FILTER] 순서 확인.
- 파드가 떠 있는데 수집 0건 → `kubectl logs ds/fluent-bit`에 `cpu.local`이 보이면 §1의 이미지 문제.
