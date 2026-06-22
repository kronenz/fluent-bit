# etcd 조건부 defrag Job — 개선 알람 수식 연동 실행 가이드

> 목적: `etcdDatabaseHighFragmentationRatio` **개선 수식**(쿼터 상대 항 + `in_use` 바닥 800Mi)과
> **동일한 조건**을 만족할 때만 `etcdctl defrag`를 실행하는 Job을 구성합니다. 고정 주기 defrag의
> 위험(불필요한 stop-the-world 반복)을 피하고, 실제로 회수 가치가 있을 때만 멤버를 1대씩 롤링 처리합니다.
> 배경: defrag는 멤버를 **stop-the-world**로 블로킹하므로, 조각 비율이 잠깐 높다고 자주 돌리면
> 200대 규모에서 위험합니다. 따라서 트리거를 **쿼터 대비 의미 있는 크기 + 조각**으로 게이트합니다.
> 다이어그램: 첨부 `etcd-defrag-job-logic.drawio` (실행 로직 전체 흐름).

---

## 1. 트리거 조건 (개선 알람 수식과 동일)

defrag Job은 아래 조건이 참일 때만 실행합니다. **§개선 알람과 같은 식**이므로, 알람이 울리는
상황 = defrag가 필요한 상황으로 일치합니다.

| 조건 | 식 | 의미 |
|---|---|---|
| 조각 | `in_use / total < 0.5` | 물리 파일의 절반 이상이 회수 가능한 빈 공간 |
| 쿼터 상대 | `total / quota > 0.5` (= `total > 4Gi`, 8Gi 기준) | 물리 DB가 쿼터의 절반 초과 — 회수 가치 있음 |
| 절대 바닥 | `in_use > 800Mi` | 소규모 노이즈 방지 |
| **또는 (즉시)** | `total / quota > 0.8` (= `total > 6.4Gi`) | 쿼터 압박 — 조각 무관, 즉시 회수 |

> `quota`는 축소 후 값 **8Gi(8589934592)** 를 상수로 사용합니다. etcd `endpoint status`에는 쿼터가
> 포함되지 않으므로 식에는 리터럴(4Gi/6.4Gi)로 박아 쓰는 것이 명확합니다.

---

## 2. 실행 방식

### 옵션 A (권장) — `etcd-defrag` 도구 (`--defrag-rule`)

[`etcd-defrag`](https://github.com/ahrtr/etcd-defrag) (etcd 메인테이너 ahrtr)는 **조건 평가 + 클러스터
health 검사 + 멤버 순차 defrag(leader 마지막)** 를 한 번에 처리합니다. 위 트리거를 룰로 그대로 표현합니다.

```bash
etcd-defrag \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  --cluster \                       # 멤버 자동 발견 + leader 마지막 롤링
  --compaction=false \              # compaction은 별도(auto-compaction)에 맡김
  --defrag-rule="(dbSizeInUse*2 < dbSize && dbSize > 4294967296 && dbSizeInUse > 838860800) \
                 || dbSize > 6871947674"
```

- `dbSize`(= `total`), `dbSizeInUse`(= `in_use`)는 도구가 각 멤버에서 직접 읽습니다.
- `4294967296` = 4Gi(쿼터 50%), `6871947674` = 6.4Gi(쿼터 80%), `838860800` = 800Mi.
- 룰 미충족 멤버는 **건너뜁니다(no-op)**. 폐쇄망은 이미지를 사내 레지스트리에 미러해서 사용합니다.

### 옵션 B — `etcdctl` 스크립트 (도구 미반입 시)

```bash
#!/usr/bin/env bash
set -euo pipefail
E="--cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key"
QUOTA=8589934592                     # 8Gi
HALF=$((QUOTA/2)); P80=$((QUOTA*8/10)); FLOOR=$((800*1024*1024))

# 1) 멤버 목록·크기 수집
mapfile -t MEMBERS < <(etcdctl $E member list -w json | jq -r '.members[].clientURLs[0]')
# 리더를 마지막에 두기 위해 정렬 (follower 먼저)
LEADER=$(etcdctl $E endpoint status --cluster -w json | jq -r '.[]|select(.Status.leader==.Status.header.member_id)|.Endpoint')

need_defrag() {  # $1=endpoint  → 0(필요) / 1(불필요)
  read TOTAL INUSE < <(etcdctl $E endpoint status --endpoints="$1" -w json \
      | jq -r '.[0].Status|"\(.dbSize) \(.dbSizeInUse)"')
  if { [ $((INUSE*2)) -lt "$TOTAL" ] && [ "$TOTAL" -gt "$HALF" ] && [ "$INUSE" -gt "$FLOOR" ]; } \
     || [ "$TOTAL" -gt "$P80" ]; then return 0; else return 1; fi
}

# 2) 클러스터 건강 확인
etcdctl $E endpoint health --cluster || { echo "cluster unhealthy, abort"; exit 1; }

# 3) follower 먼저, leader 마지막으로 1대씩
for M in "${MEMBERS[@]}" ; do [ "$M" = "$LEADER" ] && continue
  if need_defrag "$M"; then
    echo "defrag $M"; etcdctl $E defrag --endpoints="$M" --command-timeout=60s
    etcdctl $E endpoint health --endpoints="$M"     # 정상 복귀 확인 후 다음
  else echo "skip $M (조건 미달)"; fi
done
if need_defrag "$LEADER"; then
  echo "defrag leader $LEADER"; etcdctl $E defrag --endpoints="$LEADER" --command-timeout=60s
  etcdctl $E endpoint health --endpoints="$LEADER"
fi

# 4) NOSPACE 알람이 있었다면 해제
etcdctl $E alarm list | grep -q NOSPACE && etcdctl $E alarm disarm || true
```

---

## 3. 안전 수칙 (stop-the-world 작업)

| 수칙 | 이유 |
|---|---|
| **한 번에 한 멤버만** | 동시 defrag 시 정족수(quorum) 손실 위험 |
| **follower 먼저 · leader 마지막** | 리더 변경 충격 최소화 |
| **`--command-timeout` 넉넉히(예 60s)** | 큰 DB는 정지시간이 길어짐(∝ 크기) |
| **사이마다 `endpoint health`** | 정상 복귀를 확인한 뒤 다음 멤버로 진행 |
| **NOSPACE면 `alarm disarm`** | 쿼터 초과로 read-only가 된 경우 defrag 후 해제 |

---

## 4. CronJob 매니페스트 (kubeadm / static-pod etcd 기준)

control-plane 노드에서 로컬 etcd(`127.0.0.1:2379`)에 붙고, 클라이언트 인증서를 hostPath로 마운트합니다.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-conditional-defrag
  namespace: kube-system
spec:
  schedule: "0 */6 * * *"            # 6시간마다 — 조건 미달이면 즉시 no-op
  concurrencyPolicy: Forbid          # 동시 실행 금지(중첩 defrag 방지)
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        spec:
          hostNetwork: true          # 127.0.0.1:2379 접근
          nodeSelector:
            node-role.kubernetes.io/control-plane: ""
          tolerations:
            - operator: Exists       # control-plane taint 허용
          restartPolicy: Never
          containers:
            - name: defrag
              image: <레지스트리>/etcd-defrag:v0.x   # 또는 etcdctl 포함 etcd 이미지
              command: ["etcd-defrag"]
              args:
                - "--endpoints=https://127.0.0.1:2379"
                - "--cacert=/etc/kubernetes/pki/etcd/ca.crt"
                - "--cert=/etc/kubernetes/pki/etcd/server.crt"
                - "--key=/etc/kubernetes/pki/etcd/server.key"
                - "--cluster"
                - "--compaction=false"
                - "--defrag-rule=(dbSizeInUse*2 < dbSize && dbSize > 4294967296 && dbSizeInUse > 838860800) || dbSize > 6871947674"
              volumeMounts:
                - { name: etcd-certs, mountPath: /etc/kubernetes/pki/etcd, readOnly: true }
          volumes:
            - name: etcd-certs
              hostPath: { path: /etc/kubernetes/pki/etcd, type: Directory }
```

> 옵션 B(스크립트) 사용 시 `command: ["/bin/bash","-c", "<위 스크립트>"]`, 이미지는 `etcdctl`+`jq` 포함본을 사용합니다.
> 관리형/비-kubeadm etcd는 인증서 경로·엔드포인트를 환경에 맞게 바꿉니다. `--cluster`가 멤버를 자동 발견하므로
> 단일 control-plane 노드 Pod에서 전 멤버를 롤링할 수 있습니다.

---

## 5. 사후 검증 / 관측

- **즉시 확인**: `etcdctl endpoint status --cluster -w table` → `DB SIZE`가 `in_use` 수준으로 줄었는지.
- **메트릭**: `etcd_mvcc_db_total_size_in_bytes`가 하강하고 `in_use/total` 비율이 1.0 근처로 회복.
- **알람 연동**: 개선 조각 알람(§)과 같은 조건이므로, defrag 성공 후 해당 알람도 자동 해소됩니다.
- **로그**: Job 로그에 멤버별 `defrag`/`skip` 결과가 남도록 합니다(옵션 A·B 모두 출력).

---

## 부록 — etcdctl 명령 레퍼런스

```bash
# 상태(크기) 수집 — dbSize(total) / dbSizeInUse
etcdctl endpoint status --cluster -w json

# 멤버별 defrag (반드시 1대씩)
etcdctl defrag --endpoints=https://<member>:2379 --command-timeout=60s

# 건강 확인 (다음 멤버로 넘어가기 전)
etcdctl endpoint health --endpoints=https://<member>:2379

# NOSPACE 알람 확인·해제
etcdctl alarm list
etcdctl alarm disarm
```
