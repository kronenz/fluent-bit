# etcd 조건부 defrag — `etcd-defrag` 도구 기준 실행 가이드 (kubespray / etcd.service)

> 목적: `etcdDatabaseHighFragmentationRatio` **개선 수식**과 **동일한 조건**일 때만 defrag를 실행하되,
> 직접 짠 bash 스크립트(파싱·정렬·health 루프) 대신 **etcd 메인테이너가 만든 전용 도구
> [`etcd-defrag`](https://github.com/ahrtr/etcd-defrag)(ahrtr)** 를 씁니다. 트리거를 **한 줄 룰**(`--defrag-rule`)로
> 표현하므로 코드가 짧고, **고객에게 "이 조건이면 돈다"를 그대로 보여줄 수 있습니다.**
>
> **스크립트 버전과의 관계**: 동일 트리거·동일 안전수칙입니다. 폐쇄망에서 **도구 이미지 반입이
> 불가**하면 스크립트 버전(`etcd-conditional-defrag-job.md`)을, **이미지 미러가 가능**하면 이 도구 버전을
> 쓰세요. 알람 수식 정본은 `etcd-defragmentation-alert-and-quota.md` §3.
>
> **전제(이 환경)**: kubespray 설치 → etcd가 호스트 systemd 서비스 `etcd.service`(stacked control-plane).
> 인증서는 `/etc/ssl/etcd/ssl/`. 대상: **icdataops-dev**(etcd 3멤버) · **icdataops-prd**(etcd 5멤버).

---

## 1. 트리거 조건 (개선 알람 수식과 동일)

| 조건 | 식 | 의미 |
|---|---|---|
| 조각 | `in_use / total < 0.5` | 물리 파일의 절반 이상이 회수 가능한 빈 공간 |
| 쿼터 상대 | `total / quota > 0.5` (= `total > 4Gi`, 8Gi 기준) | 물리 DB가 쿼터의 절반 초과 — 회수 가치 있음 |
| 절대 바닥 | `in_use > 800Mi` | 소규모 노이즈 방지 |
| **또는 (즉시)** | `total / quota > 0.8` (= `total > 6.4Gi`) | 쿼터 압박 — 조각 무관, 즉시 회수 |

---

## 2. 도구 방식 — `--defrag-rule` 한 줄로 표현

### 2.1 룰 변수 (도구가 각 멤버에서 직접 읽음)

`etcd-defrag`는 멤버마다 아래 변수를 읽어 `--defrag-rule` 불리언 식을 평가하고, **참인 멤버만**
defrag합니다(거짓이면 no-op). 변수는 다음 5개입니다.

| 변수 | 정의 | 대응 |
|---|---|---|
| `dbSize` | etcd DB 물리 크기(bytes) | `total` |
| `dbSizeInUse` | 논리 실사용 크기(bytes) | `in_use` |
| `dbSizeFree` | `dbSize - dbSizeInUse` | 회수 가능량 |
| `dbQuota` | 쿼터(bytes) | `quota` |
| `dbQuotaUsage` | **`dbSize / dbQuota`** | 쿼터 사용률 |

> ⚠ **핵심 함정 — `dbQuota`의 출처**: etcd `endpoint status`에는 쿼터가 없어서, 도구는 쿼터를
> **`--etcd-storage-quota-bytes` 플래그값(기본 2Gi=2147483648)** 으로 채웁니다. 우리 쿼터는 **8Gi**이므로
> **반드시 `--etcd-storage-quota-bytes=8589934592`를 넘겨야** `dbQuota`·`dbQuotaUsage`가 맞습니다.
> 안 넘기면 2Gi 기준으로 평가돼 **거의 항상 즉시 defrag**가 되는 오작동이 납니다.

### 2.2 우리 트리거 = 한 줄 룰

§1 표를 그대로 옮긴 식입니다. 정수 나눗셈 함정을 피하려고 비율은 곱셈/`dbQuota` 정수식으로 씁니다
(도구 README 예시 스타일과 동일).

```text
(dbSizeInUse*2 < dbSize && dbSize > dbQuota/2 && dbSizeInUse > 800*1024*1024) || dbSize > dbQuota*80/100
```

| 룰 조각 | §1 조건 |
|---|---|
| `dbSizeInUse*2 < dbSize` | 조각: `in_use/total < 0.5` |
| `dbSize > dbQuota/2` | 쿼터 상대: `total/quota > 0.5` (8Gi → 4Gi) |
| `dbSizeInUse > 800*1024*1024` | 절대 바닥: `in_use > 800Mi` |
| `\|\| dbSize > dbQuota*80/100` | 즉시: `total/quota > 0.8` (8Gi → 6.4Gi) |

> `dbQuota`를 식에 직접 쓰므로 **쿼터가 바뀌어도(예 dev가 2Gi) 룰은 그대로** 두고
> `--etcd-storage-quota-bytes`만 바꾸면 4Gi/6.4Gi 임계가 자동 재계산됩니다.
> (동치 표현: `(dbSizeInUse*2 < dbSize && dbQuotaUsage > 0.5 && dbSizeInUse > 800*1024*1024) || dbQuotaUsage > 0.8`)

### 2.3 도구가 자동으로 해주는 것 (스크립트에서 손으로 짜던 부분)

| 직접 스크립트 | `etcd-defrag` 플래그 |
|---|---|
| 멤버 발견 + follower 먼저·**leader 마지막** | `--cluster` (멤버 자동 발견, **리더 마지막 처리 내장**) |
| 멤버 사이 health 확인 | 내장(실패 시 중단; `--continue-on-error`로 변경 가능) |
| 리더 충격 최소화 | `--move-leader` (리더 defrag 전 리더십 이동) |
| defrag 사이 간격 | `--wait-between-defrags=30s` |
| NOSPACE `alarm disarm` | `--auto-disalarm` (성공 후 자동 해제) |
| compaction 분리 | `--compaction=false` (auto-compaction에 위임) |

→ bash 파싱·정렬·루프가 전부 사라지고 **선언적 플래그**만 남습니다.

---

## 3. CronJob 매니페스트 (도구 이미지 + 호스트 인증서)

스크립트 버전과 달리 **ConfigMap이 필요 없습니다.** 이미지(`etcd-defrag`)에 도구가 들어 있고,
호스트의 **인증서 디렉터리만 hostPath로 마운트**합니다.

> **인증서 파일명 = 노드별**(`admin-<node>.pem`)이라, 도구 방식은 **Pod를 특정 control-plane 노드에
> 고정**(`kubernetes.io/hostname`)해 인증서 경로를 정적으로 박는 것이 가장 깔끔합니다. 그 노드 하나에서
> `--cluster`로 전 멤버를 롤링하므로 문제 없습니다. (노드 고정 없이 자동탐지가 필요하면 스크립트 버전을 쓰세요.)
> 폐쇄망은 `ghcr.io/ahrtr/etcd-defrag`를 사내 레지스트리에 **미러**해 사용합니다.

### 3.1 icdataops-**dev** CronJob (etcd 3멤버)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-conditional-defrag
  namespace: kube-system
  labels: { app: etcd-conditional-defrag, cluster: icdataops-dev }
spec:
  schedule: "0 * * * *"             # 매시 — 조건 미달이면 즉시 no-op (권장 근거 §5)
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
          dnsPolicy: Default
          nodeSelector:
            kubernetes.io/hostname: <dev-cp-1>     # 인증서 파일명 고정용(이 노드 기준)
          tolerations:
            - operator: Exists            # control-plane taint 허용
          restartPolicy: Never
          containers:
            - name: defrag
              image: <레지스트리>/etcd-defrag:<버전>   # ghcr.io/ahrtr/etcd-defrag 미러
              command: ["etcd-defrag"]
              args:
                - "--endpoints=https://127.0.0.1:2379"
                - "--cluster"
                - "--cacert=/etc/ssl/etcd/ssl/ca.pem"
                - "--cert=/etc/ssl/etcd/ssl/admin-<dev-cp-1>.pem"
                - "--key=/etc/ssl/etcd/ssl/admin-<dev-cp-1>-key.pem"
                - "--etcd-storage-quota-bytes=8589934592"     # 8Gi — dbQuota 출처(필수!)
                - "--defrag-rule=(dbSizeInUse*2 < dbSize && dbSize > dbQuota/2 && dbSizeInUse > 800*1024*1024) || dbSize > dbQuota*80/100"
                - "--compaction=false"
                - "--move-leader"
                - "--wait-between-defrags=30s"
                - "--auto-disalarm"
                - "--command-timeout=60s"
              volumeMounts:
                - { name: etcd-certs, mountPath: /etc/ssl/etcd/ssl, readOnly: true }
          volumes:
            - name: etcd-certs
              hostPath: { path: /etc/ssl/etcd/ssl, type: Directory }
```

### 3.2 icdataops-**prd** CronJob (etcd 5멤버)

dev와 **schedule·command-timeout·고정 노드/인증서만 다릅니다**(5멤버·고 QPS → 저빈도·여유 timeout).

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-conditional-defrag
  namespace: kube-system
  labels: { app: etcd-conditional-defrag, cluster: icdataops-prd }
spec:
  schedule: "0 */6 * * *"           # 6시간 — 조각은 시간 단위로 누적 (권장 근거 §5)
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
            kubernetes.io/hostname: <prd-cp-1>     # 인증서 파일명 고정용
          tolerations:
            - operator: Exists
          restartPolicy: Never
          containers:
            - name: defrag
              image: <레지스트리>/etcd-defrag:<버전>
              command: ["etcd-defrag"]
              args:
                - "--endpoints=https://127.0.0.1:2379"
                - "--cluster"
                - "--cacert=/etc/ssl/etcd/ssl/ca.pem"
                - "--cert=/etc/ssl/etcd/ssl/admin-<prd-cp-1>.pem"
                - "--key=/etc/ssl/etcd/ssl/admin-<prd-cp-1>-key.pem"
                - "--etcd-storage-quota-bytes=8589934592"     # 8Gi (필수!)
                - "--defrag-rule=(dbSizeInUse*2 < dbSize && dbSize > dbQuota/2 && dbSizeInUse > 800*1024*1024) || dbSize > dbQuota*80/100"
                - "--compaction=false"
                - "--move-leader"
                - "--wait-between-defrags=30s"
                - "--auto-disalarm"
                - "--command-timeout=120s"        # 5멤버·큰 DB 여유
              volumeMounts:
                - { name: etcd-certs, mountPath: /etc/ssl/etcd/ssl, readOnly: true }
          volumes:
            - name: etcd-certs
              hostPath: { path: /etc/ssl/etcd/ssl, type: Directory }
```

> ⚠ **stacked etcd 전제**: etcd가 k8s 비참여 **전용 노드**라면 Pod를 스케줄할 수 없습니다 →
> 그 etcd 노드에서 `etcd-defrag`를 **systemd timer**로 직접 돌리세요(§6).

---

## 4. dry-run 테스트 (`--dry-run`, 정지시간 0)

도구에 **`--dry-run`** 이 내장되어 있습니다: *"evaluate whether or not endpoints require
defragmentation, but don't actually perform it"* — 룰을 멤버별로 평가만 하고 **실제 defrag/disarm은 안 합니다.**

### 4.1 호스트에서 직접 (도구 바이너리/이미지로 1회)

```sh
# 미러 이미지로 1회 평가 (도커/포드만 — 또는 바이너리 직접)
etcd-defrag --dry-run \
  --endpoints=https://127.0.0.1:2379 --cluster \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/admin-$(hostname -s).pem \
  --key=/etc/ssl/etcd/ssl/admin-$(hostname -s)-key.pem \
  --etcd-storage-quota-bytes=8589934592 \
  --defrag-rule="(dbSizeInUse*2 < dbSize && dbSize > dbQuota/2 && dbSizeInUse > 800*1024*1024) || dbSize > dbQuota*80/100"
# 출력: 멤버별 dbSize/dbSizeInUse와 "rule evaluated true/false → would defrag / skip"
```

확인 포인트: ① 멤버 수(dev 3 / prd 5) 전수 평가 ② `dbQuota`가 8Gi로 보일 것(2Gi면 플래그 누락)
③ 현재 조건 미달이면 전부 skip(정상).

### 4.2 k8s에서 일회성 Job으로 (실제 배포 경로 검증)

가장 확실한 방법은 **CronJob args에 `--dry-run`을 넣어 먼저 배포**해 1주기 로그를 본 뒤 빼는 것입니다.

```sh
# CronJob에서 즉시 1회 Job 생성
kubectl -n kube-system create job etcd-defrag-dryrun --from=cronjob/etcd-conditional-defrag
kubectl -n kube-system logs job/etcd-defrag-dryrun         # (단, --dry-run을 args에 둔 상태에서)
kubectl -n kube-system delete job etcd-defrag-dryrun
```

> 운영 적용 순서: **args 끝에 `--dry-run` 추가 → 배포 → 1주기 로그 확인 → `--dry-run` 제거(patch) → 재적용.**

---

## 5. 검사 주기 권장 (alert `for: 30m` 연동)

스크립트 버전과 동일합니다. **dev 매시(`0 * * * *`), prd 6시간(`0 */6 * * *`).**

- 알람이 `for: 30m`이라 **그보다 짧게 검사할 이유가 없습니다**(게이트가 이미 30분 지속을 전제).
- 조각은 자가치유되지 않아 **조건이 한번 참이면 defrag 전까지 유지** → 주기가 길어도 "놓침"이 없고,
  빈도는 *발화한 알람을 얼마나 빨리 해소하느냐*의 문제일 뿐.
- prd(5멤버·고 QPS)는 깨우는 횟수를 줄이는 편이 안전. **30분 미만은 금지.**

| 클러스터 | schedule | command-timeout |
|---|---|---|
| icdataops-dev | `0 * * * *` (1h) | 60s |
| icdataops-prd | `0 */6 * * *` (6h) | 120s |

---

## 6. (대안) 전용 etcd 노드인 경우 — systemd timer로 도구 실행

```ini
# /etc/systemd/system/etcd-defrag.service
[Unit]
Description=etcd conditional defrag (etcd-defrag tool)
After=etcd.service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/etcd-defrag \
  --endpoints=https://127.0.0.1:2379 --cluster \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/admin-%H.pem --key=/etc/ssl/etcd/ssl/admin-%H-key.pem \
  --etcd-storage-quota-bytes=8589934592 \
  --defrag-rule=(dbSizeInUse*2 < dbSize && dbSize > dbQuota/2 && dbSizeInUse > 800*1024*1024) || dbSize > dbQuota*80/100 \
  --compaction=false --move-leader --wait-between-defrags=30s --auto-disalarm --command-timeout=120s
```
```ini
# /etc/systemd/system/etcd-defrag.timer
[Timer]
OnCalendar=*-*-* 00/6:00:00      # prd 6시간 (dev는 hourly)
Persistent=true
RandomizedDelaySec=300
[Install]
WantedBy=timers.target
```
```sh
# DRY-RUN: 위 ExecStart에 --dry-run 추가해 1회 수동 실행
systemctl daemon-reload && systemctl enable --now etcd-defrag.timer
```
> `%H`는 systemd가 노드 hostname으로 치환합니다 — 인증서 파일명이 노드별이라 유용합니다.
> (kubespray inventory hostname과 OS hostname이 다르면 실제 파일명으로 박으세요.)

---

## 7. 사후 검증 / 관측

- **즉시 확인**: `etcdctl ... endpoint status --cluster -w table` → `DB SIZE`가 `in_use` 수준으로 감소.
- **메트릭**: `etcd_mvcc_db_total_size_in_bytes` 하강, `in_use/total` 비율 1.0 근처 회복.
- **알람 연동**: 개선 조각 알람(alert-and-quota.md §3)과 같은 조건이므로 defrag 성공 후 자동 해소.
- **로그**: 도구가 멤버별 `dbSize/dbSizeInUse`, 룰 평가 결과, defrag/skip을 출력(`--dry-run` 포함).

---

## 부록 — `etcd-defrag` 주요 플래그 (README 기준)

| 플래그 | 설명 | 기본 |
|---|---|---|
| `--endpoints` | 콤마구분 엔드포인트 | `127.0.0.1:2379` |
| `--cluster` | 멤버 목록 자동 발견(리더 마지막) | off |
| `--dry-run` | 평가만, 실제 defrag 안 함 | off |
| `--defrag-rule` | 룰 식(빈값/참이면 defrag) | (빈값) |
| `--etcd-storage-quota-bytes` | **`dbQuota` 출처** | `2147483648`(2Gi) |
| `--compaction` | defrag 전 compaction 수행 | `true` |
| `--move-leader` | 리더 defrag 전 리더십 이동 | off |
| `--wait-between-defrags` | defrag 사이/리더이동 후 대기 | — |
| `--auto-disalarm` | 성공 후 NOSPACE 자동 해제 | off |
| `--disalarm-threshold` | 자동 해제 임계(dbSize/quota) | `0.9` |
| `--continue-on-error` | 실패해도 다음 멤버 진행 | off |
| `--cacert`/`--cert`/`--key` | TLS | — |
| `--command-timeout` | 명령 타임아웃(dial 제외) | `30s` |

룰 변수: `dbSize`, `dbSizeInUse`, `dbSizeFree`(=dbSize−dbSizeInUse), `dbQuota`, `dbQuotaUsage`(=dbSize/dbQuota).
README 예시: `dbQuotaUsage > 0.8 || dbSizeFree > 200*1024*1024`.
