# etcd 조건부 defrag Job — 개선 알람 수식 연동 실행 가이드 (kubespray / etcd.service)

> 목적: `etcdDatabaseHighFragmentationRatio` **개선 수식**(쿼터 상대 항 + `in_use` 바닥 800Mi)과
> **동일한 조건**을 만족할 때만 `etcdctl defrag`를 실행하는 Job을 구성합니다. 고정 주기 defrag의
> 위험(불필요한 stop-the-world 반복)을 피하고, 실제로 회수 가치가 있을 때만 멤버를 1대씩 롤링 처리합니다.
> 배경: defrag는 멤버를 **stop-the-world**로 블로킹하므로, 조각 비율이 잠깐 높다고 자주 돌리면
> 200대 규모에서 위험합니다. 따라서 트리거를 **쿼터 대비 의미 있는 크기 + 조각**으로 게이트합니다.
> 다이어그램: 첨부 `etcd-defrag-job-logic.drawio` (실행 로직 전체 흐름).
>
> **전제(이 환경)**: 클러스터는 **kubespray**로 설치되어 etcd가 **kubeadm static-pod가 아니라
> 호스트 systemd 서비스 `etcd.service`** 로 동작합니다. 따라서
> ① `etcdctl` 바이너리(`/usr/local/bin/etcdctl`)와 ② 클라이언트 인증서(`/etc/ssl/etcd/ssl/`)가
> **이미 etcd 호스트(=stacked control-plane)에 존재**합니다. 별도 도구·이미지를 **반입하지 않고**,
> 호스트의 etcdctl과 인증서를 그대로 마운트해 **스크립트로만** 실행합니다.
> 대상: **icdataops-dev**(etcd 3멤버) · **icdataops-prd**(etcd 5멤버).

---

## 1. 트리거 조건 (개선 알람 수식과 동일)

defrag Job은 아래 조건이 참일 때만 실행합니다. **개선 알람과 같은 식**이므로, 알람이 울리는
상황 = defrag가 필요한 상황으로 일치합니다. (알람 수식 정본: `etcd-defragmentation-alert-and-quota.md` §3)

| 조건 | 식 | 의미 |
|---|---|---|
| 조각 | `in_use / total < 0.5` | 물리 파일의 절반 이상이 회수 가능한 빈 공간 |
| 쿼터 상대 | `total / quota > 0.5` (= `total > 4Gi`, 8Gi 기준) | 물리 DB가 쿼터의 절반 초과 — 회수 가치 있음 |
| 절대 바닥 | `in_use > 800Mi` | 소규모 노이즈 방지 |
| **또는 (즉시)** | `total / quota > 0.8` (= `total > 6.4Gi`) | 쿼터 압박 — 조각 무관, 즉시 회수 |

> `quota`는 축소 후 값 **8Gi(8589934592)** 를 상수로 사용합니다. etcd `endpoint status`에는 쿼터가
> 포함되지 않으므로 식에는 리터럴(4Gi/6.4Gi)로 박아 쓰는 것이 명확합니다. **dev 클러스터의 쿼터가
> 8Gi가 아니라면** 스크립트의 `QUOTA` 환경변수만 바꾸면 4Gi/6.4Gi 임계가 자동 재계산됩니다(§4).

---

## 2. 실행 방식 — etcdctl 스크립트 (도구 미반입, jq 불필요)

> 옵션 A([`etcd-defrag`](https://github.com/ahrtr/etcd-defrag) 도구의 `--defrag-rule`)는 한 번에 룰
> 평가+롤링을 처리하지만 **별도 바이너리·이미지 반입이 필요**합니다. 이 환경은 **도구 미반입 방침**이므로
> 호스트에 이미 있는 `etcdctl`만 쓰는 **스크립트 방식**을 채택합니다. 아래 스크립트의 전문(全文)은
> §4의 ConfigMap에 그대로 들어갑니다.

### 2.1 kubespray 경로·접속 (kubeadm과 다른 점)

| 항목 | kubeadm (static-pod) | **kubespray (etcd.service) — 이 환경** |
|---|---|---|
| CA | `/etc/kubernetes/pki/etcd/ca.crt` | **`/etc/ssl/etcd/ssl/ca.pem`** |
| 클라이언트 인증서 | `.../server.crt` | **`/etc/ssl/etcd/ssl/admin-<node>.pem`** (없으면 `member-<node>.pem`) |
| 키 | `.../server.key` | **`/etc/ssl/etcd/ssl/admin-<node>-key.pem`** |
| etcdctl | 컨테이너 이미지 동봉 | **호스트 `/usr/local/bin/etcdctl`** (kubespray 설치) |
| 로컬 엔드포인트 | `https://127.0.0.1:2379` | 동일 (`ETCD_LISTEN_CLIENT_URLS`에 127.0.0.1 포함) |
| 멤버 발견 | `--cluster` | `member list`가 광고 client URL(=노드 IP)을 반환 → 한 노드 Pod가 전 멤버 롤링 |

- 인증서 파일명은 **노드별로 다릅니다**(`admin-<inventory_hostname>.pem`). 스크립트가 `hostname`으로
  자동 탐지하고, 실패 시 `admin-*.pem`/`member-*.pem` 글롭으로 폴백합니다(각 etcd 노드엔 자기 인증서 1개).
- kubespray admin 인증서는 **클라이언트 인증서(clientAuth)** 라 클러스터 내 어느 멤버에도 붙습니다.
  따라서 한 Pod가 로컬(127.0.0.1)로 접속→멤버 목록(노드 IP) 발견→각 노드 IP로 순차 defrag가 가능합니다.

### 2.2 핵심 로직 (jq 없이 — busybox `awk`/`sed`/`tr`만 사용)

폐쇄망·최소 이미지(busybox)에서도 돌도록 **jq/python 의존을 제거**하고 `etcdctl -w json`을
`awk`로 파싱합니다. 큰 정수(uint64) member_id 비교는 부동소수 오차를 피해 **문자열 비교**로 합니다.

```sh
# 멤버 client URL (노드 IP) 수집 — jq 없이
ec member list -w json | tr ',' '\n' | sed -n 's/.*"clientURLs":\["\([^"]*\)".*/\1/p'

# 멤버 1대 상태: dbSize(total) / dbSizeInUse / leader 판정
J="$(ec --endpoints="$M" endpoint status -w json)"
TOTAL=$(printf '%s' "$J" | tr ',{}[]' '\n' | awk -F: '/"dbSize":/&&!/InUse/{gsub(/[^0-9]/,"",$2);print $2;exit}')
INUSE=$(printf '%s' "$J" | tr ',{}[]' '\n' | awk -F: '/"dbSizeInUse":/{gsub(/[^0-9]/,"",$2);print $2;exit}')
```

- 트리거 판정은 §1 표와 동일: `(in_use*2 < total && total>4Gi && in_use>800Mi) || total>6.4Gi`.
- **DRY_RUN=1**이면 상태 조회·health 검사(읽기 전용, 안전)는 그대로 하고 **defrag/alarm disarm만 건너뜁니다**
  → stop-the-world 없이 인증서 마운트·엔드포인트 도달·멤버 발견·임계 판정 전 과정을 검증할 수 있습니다(§5).

---

## 3. 안전 수칙 (stop-the-world 작업)

| 수칙 | 이유 |
|---|---|
| **한 번에 한 멤버만** | 동시 defrag 시 정족수(quorum) 손실 위험 |
| **follower 먼저 · leader 마지막** | 리더 변경 충격 최소화 |
| **`--command-timeout` 넉넉히** | 큰 DB는 정지시간이 길어짐(∝ 크기). dev 60s / prd 120s 권장 |
| **사이마다 `endpoint health`** | 정상 복귀를 확인한 뒤 다음 멤버로 진행(실패 시 즉시 중단) |
| **NOSPACE면 `alarm disarm`** | 쿼터 초과로 read-only가 된 경우 defrag 후 해제 |
| **`concurrencyPolicy: Forbid`** | 이전 실행이 안 끝났으면 다음 실행을 막아 중첩 defrag 방지 |

---

## 4. CronJob 매니페스트 (kubespray / 호스트 etcd.service)

설계: **스크립트는 ConfigMap 1개로 공유**(클러스터 무관), dev/prd는 **CronJob의 env·schedule만 다르게**
가져갑니다. Pod는 stacked control-plane 노드(=etcd 호스트)에 스케줄되어 `hostNetwork`로 127.0.0.1:2379에
접속하고, 호스트의 **etcdctl 바이너리와 인증서 디렉터리를 hostPath로 마운트**합니다(도구 미반입).

> ⚠ **전제 — stacked etcd**: 위 CronJob은 etcd가 **k8s control-plane 노드에 동거(stacked)** 한다고
> 가정합니다. kubespray에서 etcd를 **전용 etcd-only 노드**(k8s 비참여)로 분리했다면 그 노드엔 kubelet이
> 없어 **Pod가 스케줄될 수 없습니다** → 이 경우 §7의 **systemd timer** 방식을 쓰세요.
> 멤버 수(dev 3 / prd 5)와 무관하게 적용되는 제약입니다.

### 4.0 공유 스크립트 ConfigMap (dev·prd 양쪽 클러스터에 동일 적용)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: etcd-conditional-defrag-script
  namespace: kube-system
data:
  defrag.sh: |
    #!/bin/sh
    set -eu
    # ---- 설정 (CronJob env로 주입; 미주입 시 보수적 기본값) ----
    ENDPOINT_LOCAL="${ENDPOINT_LOCAL:-https://127.0.0.1:2379}"  # 초기 접속(로컬 멤버)
    CERT_DIR="${CERT_DIR:-/etc/ssl/etcd/ssl}"                   # kubespray 호스트 인증서
    QUOTA="${QUOTA:-8589934592}"                                # 8Gi (클러스터별 조정)
    FLOOR="${FLOOR:-838860800}"                                 # 800Mi 절대 바닥
    CMD_TIMEOUT="${CMD_TIMEOUT:-60s}"                           # defrag 타임아웃(DB↑→↑)
    DRY_RUN="${DRY_RUN:-0}"                                     # 1이면 defrag/disarm 미실행
    HALF=$(( QUOTA / 2 ))          # total/quota>0.5  → total>4Gi
    P80=$(( QUOTA * 8 / 10 ))      # total/quota>0.8  → total>6.4Gi(즉시)

    hr() { awk -v b="$1" 'BEGIN{printf "%.0fMi", b/1048576}'; }

    # ---- 인증서 자동 탐지 (admin-<node> 우선 → member-<node> → 글롭 폴백) ----
    NODE="$(hostname 2>/dev/null | cut -d. -f1)"
    CA="$CERT_DIR/ca.pem"; CERT=""
    for f in "$CERT_DIR/admin-$NODE.pem" $CERT_DIR/admin-*.pem \
             "$CERT_DIR/member-$NODE.pem" $CERT_DIR/member-*.pem; do
      case "$f" in *'*'*) continue;; *-key.pem) continue;; esac   # 미매치 글롭·키파일 스킵
      [ -r "$f" ] && { CERT="$f"; break; }
    done
    KEY="$(printf '%s' "$CERT" | sed 's/\.pem$/-key.pem/')"
    { [ -r "$CA" ] && [ -r "$CERT" ] && [ -r "$KEY" ]; } \
      || { echo "ERROR: 인증서 없음 (CA=$CA CERT=$CERT)"; exit 1; }
    E="--cacert=$CA --cert=$CERT --key=$KEY"
    ec() { ETCDCTL_API=3 etcdctl $E "$@"; }     # 공통 래퍼

    status_of() {  # $1=endpoint → "TOTAL INUSE ISLEADER"
      J="$(ec --endpoints="$1" endpoint status -w json)"
      T=$(printf '%s' "$J" | tr ',{}[]' '\n' | awk -F: '/"dbSize":/&&!/InUse/{gsub(/[^0-9]/,"",$2);print $2;exit}')
      U=$(printf '%s' "$J" | tr ',{}[]' '\n' | awk -F: '/"dbSizeInUse":/{gsub(/[^0-9]/,"",$2);print $2;exit}')
      S=$(printf '%s' "$J" | tr ',{}[]' '\n' | awk -F: '/"member_id":/{gsub(/[^0-9]/,"",$2);print $2;exit}')
      L=$(printf '%s' "$J" | tr ',{}[]' '\n' | awk -F: '/"leader":/{gsub(/[^0-9]/,"",$2);print $2;exit}')
      IL=0; [ -n "$S" ] && [ "$S" = "$L" ] && IL=1     # uint64는 문자열 비교
      echo "${T:-} ${U:-} $IL"
    }
    need_defrag() {  # $1=TOTAL $2=INUSE → 0(필요)/1(불필요)
      [ -n "${1:-}" ] && [ -n "${2:-}" ] || return 1
      if { [ $(( $2 * 2 )) -lt "$1" ] && [ "$1" -gt "$HALF" ] && [ "$2" -gt "$FLOOR" ]; } \
         || [ "$1" -gt "$P80" ]; then return 0; else return 1; fi
    }

    # ---- 1) 로컬 멤버 건강 선확인 ----
    ec --endpoints="$ENDPOINT_LOCAL" endpoint health >/dev/null \
      || { echo "ERROR: 로컬 멤버 unhealthy, 중단"; exit 1; }

    # ---- 2) 멤버(노드 IP) 수집 + follower 먼저·leader 마지막 정렬 ----
    ALL="$(ec --endpoints="$ENDPOINT_LOCAL" member list -w json \
            | tr ',' '\n' | sed -n 's/.*"clientURLs":\["\([^"]*\)".*/\1/p')"
    [ -n "$ALL" ] || { echo "ERROR: 멤버 목록 비어있음"; exit 1; }
    FOLLOWERS=""; LEADER=""
    for M in $ALL; do
      set -- $(status_of "$M")
      if [ "${3:-0}" = "1" ]; then LEADER="$M"; else FOLLOWERS="$FOLLOWERS $M"; fi
    done

    [ "$DRY_RUN" = "1" ] && echo "===== DRY-RUN (실제 defrag/disarm 미실행) ====="
    echo "QUOTA=$QUOTA  4Gi=$HALF  6.4Gi=$P80  FLOOR(800Mi)=$FLOOR"
    echo "leader=$LEADER  followers=$FOLLOWERS"

    # ---- 3) follower → leader 순차 처리 ----
    for M in $FOLLOWERS $LEADER; do
      [ -n "$M" ] || continue
      set -- $(status_of "$M"); T="${1:-}"; U="${2:-}"
      if need_defrag "$T" "$U"; then
        echo "DEFRAG  $M  total=$(hr "${T:-0}") in_use=$(hr "${U:-0}") (조건 충족)"
        if [ "$DRY_RUN" = "1" ]; then
          echo "  [DRY-RUN] etcdctl defrag --endpoints=$M --command-timeout=$CMD_TIMEOUT 생략"
        else
          ec --endpoints="$M" defrag --command-timeout="$CMD_TIMEOUT"
          ec --endpoints="$M" endpoint health >/dev/null \
            && echo "  health OK → 다음 멤버" \
            || { echo "  ERROR: $M defrag 후 unhealthy, 중단"; exit 1; }
        fi
      else
        echo "SKIP    $M  total=$(hr "${T:-0}") in_use=$(hr "${U:-0}") (조건 미달)"
      fi
    done

    # ---- 4) NOSPACE 알람 해제 ----
    if ec --endpoints="$ENDPOINT_LOCAL" alarm list 2>/dev/null | grep -q NOSPACE; then
      if [ "$DRY_RUN" = "1" ]; then echo "[DRY-RUN] NOSPACE 감지 → alarm disarm 생략"
      else echo "NOSPACE 감지 → disarm"; ec --endpoints="$ENDPOINT_LOCAL" alarm disarm; fi
    fi
    echo "완료."
```

> 이미지는 **사내 레지스트리에 미러된 busybox**(sh/awk/sed/tr/grep/cut 포함)를 사용합니다. etcdctl은
> 정적(static, CGO 비활성) 바이너리라 busybox에서도 그대로 실행됩니다 — **추가 도구 반입 없음**.

### 4.1 icdataops-**dev** CronJob (etcd 3멤버)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-conditional-defrag
  namespace: kube-system
  labels: { app: etcd-conditional-defrag, cluster: icdataops-dev }
spec:
  schedule: "0 * * * *"             # 매시 정각 — 조건 미달이면 즉시 no-op (권장 근거 §6)
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 300
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        spec:
          hostNetwork: true               # 127.0.0.1:2379 접근
          dnsPolicy: Default              # 노드 IP만 쓰므로 클러스터 DNS 불필요
          nodeSelector:
            node-role.kubernetes.io/control-plane: ""   # stacked etcd 노드
          tolerations:
            - operator: Exists            # control-plane taint 허용
          restartPolicy: Never
          containers:
            - name: defrag
              image: <레지스트리>/busybox:1.36   # 미러된 minimal 이미지
              command: ["/bin/sh", "/scripts/defrag.sh"]
              env:
                - { name: QUOTA,       value: "8589934592" }   # 8Gi (dev 쿼터가 다르면 수정)
                - { name: CMD_TIMEOUT, value: "60s" }
                - { name: DRY_RUN,     value: "0" }            # 테스트 시 "1"
              volumeMounts:
                - { name: script,    mountPath: /scripts, readOnly: true }
                - { name: etcdctl,   mountPath: /usr/local/bin/etcdctl, readOnly: true }
                - { name: etcd-certs, mountPath: /etc/ssl/etcd/ssl, readOnly: true }
          volumes:
            - name: script
              configMap: { name: etcd-conditional-defrag-script, defaultMode: 0555 }
            - name: etcdctl
              hostPath: { path: /usr/local/bin/etcdctl, type: File }
            - name: etcd-certs
              hostPath: { path: /etc/ssl/etcd/ssl, type: Directory }
```

### 4.2 icdataops-**prd** CronJob (etcd 5멤버)

dev와 **schedule·command-timeout만 다릅니다**(5멤버·고 QPS·200대 규모 → 정지시간 여유 + 저빈도).

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-conditional-defrag
  namespace: kube-system
  labels: { app: etcd-conditional-defrag, cluster: icdataops-prd }
spec:
  schedule: "0 */6 * * *"           # 6시간마다 — 조각은 시간 단위로 천천히 누적(권장 근거 §6)
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 300
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        spec:
          hostNetwork: true
          dnsPolicy: Default
          nodeSelector:
            node-role.kubernetes.io/control-plane: ""   # stacked etcd 노드
          tolerations:
            - operator: Exists
          restartPolicy: Never
          containers:
            - name: defrag
              image: <레지스트리>/busybox:1.36
              command: ["/bin/sh", "/scripts/defrag.sh"]
              env:
                - { name: QUOTA,       value: "8589934592" }   # 8Gi (alert-and-quota.md §5)
                - { name: CMD_TIMEOUT, value: "120s" }         # 5멤버·큰 DB 여유
                - { name: DRY_RUN,     value: "0" }
              volumeMounts:
                - { name: script,    mountPath: /scripts, readOnly: true }
                - { name: etcdctl,   mountPath: /usr/local/bin/etcdctl, readOnly: true }
                - { name: etcd-certs, mountPath: /etc/ssl/etcd/ssl, readOnly: true }
          volumes:
            - name: script
              configMap: { name: etcd-conditional-defrag-script, defaultMode: 0555 }
            - name: etcdctl
              hostPath: { path: /usr/local/bin/etcdctl, type: File }
            - name: etcd-certs
              hostPath: { path: /etc/ssl/etcd/ssl, type: Directory }
```

---

## 5. dry-run으로 스크립트 테스트 (정지시간 0)

`DRY_RUN=1`이면 **상태 조회·멤버 발견·health 검사·임계 판정까지 전부 실행**하고 **defrag와
alarm disarm만 건너뜁니다.** 인증서 마운트·엔드포인트 도달·파싱이 맞는지 안전하게 검증합니다.

### 5.1 호스트에서 직접 (가장 빠른 검증 — Pod 없이)

etcd(=control-plane) 노드에 SSH 후, ConfigMap의 `defrag.sh`를 그대로 한 파일로 저장해 실행합니다.

```sh
# (스크립트를 /tmp/defrag.sh로 저장했다고 가정)
DRY_RUN=1 QUOTA=8589934592 sh /tmp/defrag.sh
# 기대 출력 예:
#   ===== DRY-RUN (실제 defrag/disarm 미실행) =====
#   QUOTA=8589934592  4Gi=4294967296  6.4Gi=6871947674  FLOOR(800Mi)=838860800
#   leader=https://10.x.x.3:2379  followers= https://10.x.x.1:2379 https://10.x.x.2:2379
#   SKIP    https://10.x.x.1:2379  total=1490Mi in_use=786Mi (조건 미달)
#   ...
#   완료.
```

확인 포인트: ① `ERROR: 인증서 없음`이 안 떠야 함(경로/파일명 자동탐지 OK) ② leader/followers가
멤버 수(dev 3 / prd 5)와 일치 ③ total/in_use 수치가 `endpoint status -w table`과 일치
④ 현재 조건 미달이면 전부 `SKIP`(정상 — 알람이 안 울리는 상태라면 defrag 불필요).

### 5.2 k8s에서 일회성 Job으로 (실제 배포 경로 그대로 검증)

CronJob을 만든 뒤, **DRY_RUN=1로 override한 일회성 Job**을 띄워 마운트·스케줄·RBAC까지 점검합니다.

```sh
# CronJob에서 즉시 1회 Job 생성 (스케줄 무관)
kubectl -n kube-system create job etcd-defrag-dryrun --from=cronjob/etcd-conditional-defrag

# 생성된 Job의 DRY_RUN을 1로 패치하려면, 대신 아래처럼 매니페스트를 복사해 env만 바꿔 적용하는 것이 안전:
#   kubectl -n kube-system get cronjob etcd-conditional-defrag -o yaml > /tmp/cj.yaml
#   (jobTemplate.spec.template.spec.containers[0].env 의 DRY_RUN을 "1"로 수정 후)
#   kubectl -n kube-system create -f <(yq '.spec.jobTemplate.spec' /tmp/cj.yaml ...)   # 환경에 맞게

# 로그 확인
kubectl -n kube-system logs job/etcd-defrag-dryrun
kubectl -n kube-system delete job etcd-defrag-dryrun   # 검증 후 정리
```

> 가장 단순·확실한 방법: **CronJob 매니페스트의 `DRY_RUN` env를 "1"로 둔 채 먼저 배포**해 1주기
> 돌려 로그를 확인하고, 정상이면 `DRY_RUN`을 `"0"`으로 패치합니다.
> `kubectl -n kube-system patch cronjob etcd-conditional-defrag --type=json \`
> `  -p='[{"op":"replace","path":"/spec/jobTemplate/spec/template/spec/containers/0/env/2/value","value":"0"}]'`

---

## 6. 검사 주기 권장 (alert `for: 30m` 연동)

**결론: dev는 매시(`0 * * * *`), prd는 6시간(`0 */6 * * *`)을 권장합니다.** 근거는 다음과 같습니다.

1. **`for: 30m`보다 더 자주 검사할 이유가 없다.** 개선 알람은 조건이 **30분 지속**돼야 발화합니다
   (churn 일시 스파이크 무시). 그보다 짧은 주기(5~15분)로 검사해도, 게이트(`total/quota>0.5`,
   `in_use/total<0.5`)가 **이미 30분 지속성을 전제**하므로 잡아낼 것이 없고 **stop-the-world 위험만** 늘립니다.
2. **조건은 한 번 참이 되면 defrag 전까지 사라지지 않는다.** 조각(free page)은 자가 치유되지 않아
   `total`이 줄지 않습니다. 즉 검사 주기가 길어도 **"놓치는" 일이 없습니다** — 다음 주기에 반드시 처리됩니다.
   따라서 빈도는 "탐지"가 아니라 **"발화한 알람을 얼마나 빨리 해소하느냐"** 의 문제일 뿐입니다.
3. **조각이 쿼터 게이트(물리 DB > 4Gi)를 넘기는 속도는 시간~일 단위**입니다(쓰기/compaction 누적).
   분 단위로 들여다볼 변화가 아닙니다.
4. **dev = 매시**: 규모가 작고 위험이 낮아, 발화한 알람을 ≤1시간 내 해소해 페이지 잔류를 줄입니다.
   1시간은 `for:30m`보다 길어 "확정된 조건"에만 작동합니다.
5. **prd = 6시간**: 5멤버·고 QPS·200대 규모에서는 **깨우는 횟수를 줄이는 편이 운영상 안전**합니다.
   조건이 지속되므로 6시간 주기여도 반드시 처리되고, status 읽기/순차 defrag의 빈도를 낮춥니다.
   (페이지가 떠 있는 시간을 더 줄이고 싶다면 prd도 매시로 올려도 무방합니다 — Job 자체가 조건 미달 시
   no-op이라 비용이 거의 없습니다.)

| 클러스터 | schedule | command-timeout | 의도 |
|---|---|---|---|
| icdataops-dev | `0 * * * *` (1h) | 60s | 빠른 해소, 낮은 위험 |
| icdataops-prd | `0 */6 * * *` (6h) | 120s | 저빈도·여유 timeout(고 QPS 보호) |

> **절대 30분 미만으로 두지 말 것** — 알람의 `for:30m` 창보다 짧으면 게이트가 거르기도 전에
> 헛돌고, 최악의 경우 churn 중 조각률 순간 변동에 반응할 여지를 늘립니다.

---

## 7. (대안) 전용 etcd 노드인 경우 — systemd timer

etcd가 k8s 비참여 **전용 노드**라면 CronJob을 스케줄할 수 없습니다(§4 ⚠). 이 경우 **각 etcd 노드에서가
아니라 한 노드에서만** 아래 timer를 돌립니다(스크립트가 멤버를 자동 발견해 전 멤버를 롤링).

```ini
# /etc/systemd/system/etcd-defrag.service
[Unit]
Description=etcd conditional defrag (조건부)
After=etcd.service
[Service]
Type=oneshot
Environment=QUOTA=8589934592 CMD_TIMEOUT=120s DRY_RUN=0
ExecStart=/usr/local/bin/etcd-defrag.sh        # §4.0 defrag.sh를 호스트에 배치
```
```ini
# /etc/systemd/system/etcd-defrag.timer
[Unit]
Description=etcd conditional defrag schedule
[Timer]
OnCalendar=*-*-* 00/6:00:00     # prd 6시간 (dev는 hourly)
Persistent=true
RandomizedDelaySec=300          # 다중 노드 동시기동 방지
[Install]
WantedBy=timers.target
```
```sh
# DRY-RUN 테스트
DRY_RUN=1 /usr/local/bin/etcd-defrag.sh
# 활성화
systemctl daemon-reload && systemctl enable --now etcd-defrag.timer
systemctl list-timers etcd-defrag.timer
```

---

## 8. 사후 검증 / 관측

- **즉시 확인**: `etcdctl endpoint status --cluster -w table` → `DB SIZE`가 `in_use` 수준으로 줄었는지.
- **메트릭**: `etcd_mvcc_db_total_size_in_bytes`가 하강하고 `in_use/total` 비율이 1.0 근처로 회복.
- **알람 연동**: 개선 조각 알람(alert-and-quota.md §3)과 같은 조건이므로, defrag 성공 후 해당 알람도 자동 해소됩니다.
- **로그**: Job/timer 로그에 멤버별 `DEFRAG`/`SKIP` 결과와 수치가 남습니다(DRY-RUN 포함).

---

## 부록 — etcdctl 명령 레퍼런스 (kubespray 경로)

```sh
# 공통 인증 (admin-<node>는 노드별 파일명)
E="--cacert=/etc/ssl/etcd/ssl/ca.pem \
   --cert=/etc/ssl/etcd/ssl/admin-$(hostname -s).pem \
   --key=/etc/ssl/etcd/ssl/admin-$(hostname -s)-key.pem"

# 상태(크기) 수집 — dbSize(total) / dbSizeInUse
etcdctl $E endpoint status --cluster -w table
etcdctl $E endpoint status --cluster -w json

# 멤버 목록(클라이언트 URL)
etcdctl $E member list -w table

# 멤버별 defrag (반드시 1대씩, follower 먼저·leader 마지막)
etcdctl $E defrag --endpoints=https://<member-ip>:2379 --command-timeout=120s

# 건강 확인 (다음 멤버로 넘어가기 전)
etcdctl $E endpoint health --endpoints=https://<member-ip>:2379

# NOSPACE 알람 확인·해제
etcdctl $E alarm list
etcdctl $E alarm disarm
```
