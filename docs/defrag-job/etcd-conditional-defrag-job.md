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
> **전제(이 환경)**: kubespray 설치 → etcd가 호스트 systemd 서비스 `etcd.service`로 동작하며,
> **etcd는 k8s 비참여 전용 노드**(`etcd` 인벤토리 그룹, kubelet 없음)에 있습니다. 인증서는 etcd 노드의
> `/etc/ssl/etcd/ssl/`. 따라서 defrag Job Pod는 **워커 노드에서 돌고 etcd 노드 IP:2379에 네트워크로
> 접속**하며, 인증서는 **hostPath가 아니라 Secret**으로 주입합니다(§3). 대상: **icdataops-dev**(etcd
> 3멤버) · **icdataops-prd**(etcd 5멤버).

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

## 3. k8s 리소스 전체 (etcd 전용 노드 — 네트워크 접속 + Secret)

### 3.0 아키텍처 — 왜 hostPath/hostNetwork를 못 쓰나

etcd가 **k8s 비참여 전용 노드**에 있으므로:

| 항목 | stacked였다면 | **전용 etcd 노드(이 환경)** |
|---|---|---|
| Pod 실행 위치 | etcd=control-plane 노드 | **워커 노드**(etcd 노드엔 kubelet 없음 → 스케줄 불가) |
| etcd 접속 | `hostNetwork`+`127.0.0.1:2379` | **네트워크로 etcd 노드 IP:2379** (`--endpoints`에 전 멤버 IP) |
| 인증서 | `hostPath`로 호스트 디렉터리 | **Secret으로 주입**(etcd 노드 인증서를 복사해 등록) |
| 권한 | (노드 권한) | **전용 ServiceAccount(토큰 비마운트) + Secret(RBAC로 접근 제한)** |

전제·요구사항:
- **네트워크 도달성**: 워커 Pod 네트워크 → etcd 노드 `:2379` TCP가 열려 있어야 합니다(방화벽/보안그룹).
  CNI가 cilium이므로 egress 차단 정책이 있으면 **NetworkPolicy로 명시 허용**(§3.4)해야 합니다.
- **서버 인증서 SAN**: etcd가 광고하는 client URL(= etcd 노드 IP)로 접속하므로, kubespray member 인증서
  SAN에 그 IP가 포함되어 있어야 hostname 검증을 통과합니다(kubespray 기본 포함 — 노드 IP·hostname).
- **클라이언트 인증서**: kubespray `admin-<etcd-node>.pem`은 **CA 서명 client 인증서**라 어느 위치에서
  접속하든 유효합니다(etcd `--client-cert-auth`는 CA 체인만 검증, CN 화이트리스트 없음). 멤버별 1장 중
  **아무 etcd 노드의 admin 인증서 1세트**(ca/cert/key)를 Secret에 넣으면 됩니다.
- **이미지**: `ghcr.io/ahrtr/etcd-defrag:v0.41.0`(ko 빌드 distroless, **User=65532·ENTRYPOINT
  `/ko-app/etcd-defrag`** → k8s `command` 오버라이드 금지, `args`만 전달)을 **Nexus docker 저장소에
  반입**해 사용합니다. 반입용 이미지 tar·푸시 스크립트·단일 적용 YAML 세트는
  **`ops/etcd-defrag/`** 에 있습니다(§8).

> 아래 리소스를 **클러스터별(dev/prd)로 각각** 적용합니다. 네임스페이스·SA·Secret·NetworkPolicy는
> 공통 형태이고, CronJob의 `--endpoints`·schedule·timeout만 다릅니다.

### 3.1 Namespace + ServiceAccount (최소 권한)

defrag Job은 **k8s API를 전혀 호출하지 않습니다**(etcd에 직접 TLS로 붙음). 따라서 **Role/RoleBinding이
불필요**하고, SA 토큰도 마운트하지 않습니다(자격증명은 오직 etcd client 인증서 Secret 하나).

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: etcd-maintenance
  labels:
    # PodSecurity: restricted 강제 (권한상승·root·hostPath 전면 차단)
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: etcd-defrag
  namespace: etcd-maintenance
automountServiceAccountToken: false      # API 미사용 → 토큰 비마운트(최소 권한)
```

### 3.2 Secret — etcd client 인증서 (자격증명)

평문 인증서를 매니페스트에 박지 말고 **etcd 노드의 실제 파일로부터 생성**합니다. (GitOps라면
SealedSecrets/ExternalSecrets로 암호화해 보관 — 평문 Secret을 git에 커밋 금지.)

```sh
# 1) etcd 노드(아무 1대)에서 인증서 3종을 관리 호스트로 복사 (admin = client 인증서)
#    예: scp root@<dev-etcd-1>:/etc/ssl/etcd/ssl/{ca.pem,admin-<dev-etcd-1>.pem,admin-<dev-etcd-1>-key.pem} /tmp/ec/

# 2) Secret 생성 (키 이름을 ca.pem/client.pem/client-key.pem 으로 표준화)
kubectl -n etcd-maintenance create secret generic etcd-client-certs \
  --from-file=ca.pem=/tmp/ec/ca.pem \
  --from-file=client.pem=/tmp/ec/admin-<dev-etcd-1>.pem \
  --from-file=client-key.pem=/tmp/ec/admin-<dev-etcd-1>-key.pem

# 3) 로컬 사본 즉시 삭제
shred -u /tmp/ec/* 2>/dev/null || rm -f /tmp/ec/*
```

> Secret 접근 제한(권한구성): 이 Secret을 읽을 수 있는 주체를 최소화합니다. 네임스페이스를
> `etcd-maintenance`로 격리하고, 운영자 외 일반 Role에서 이 ns의 `secrets` get/list를 부여하지 마세요.
> (감사: `kubectl -n etcd-maintenance get rolebindings,clusterrolebindings -o wide`로 노출 주체 점검.)

### 3.3 icdataops-**dev** CronJob (etcd 3멤버)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-conditional-defrag
  namespace: etcd-maintenance
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
      activeDeadlineSeconds: 1800     # 30분 내 미완료 시 중단(걸림 방지)
      template:
        metadata:
          labels: { app: etcd-conditional-defrag }
        spec:
          serviceAccountName: etcd-defrag
          automountServiceAccountToken: false
          restartPolicy: Never
          securityContext:                # 파드: restricted 준수 + Secret 읽기용 fsGroup
            runAsNonRoot: true
            runAsUser: 65532
            runAsGroup: 65532
            fsGroup: 65532                 # Secret 파일(mode 0440) 그룹 읽기 허용
            seccompProfile: { type: RuntimeDefault }
          containers:
            - name: defrag
              image: <NEXUS>/etcd-defrag:v0.41.0   # ghcr.io/ahrtr/etcd-defrag 미러
              # command 생략 — 이미지 ENTRYPOINT(/ko-app/etcd-defrag) 사용
              # (이 이미지는 ko 빌드 distroless라 PATH에 etcd-defrag 바이너리가 없음)
              args:
                # etcd 노드 IP 전체 나열(1대만 살아도 --cluster가 나머지 발견; 전수 나열=가용성)
                - "--endpoints=https://<dev-etcd-1>:2379,https://<dev-etcd-2>:2379,https://<dev-etcd-3>:2379"
                - "--cluster"
                - "--cacert=/etc/etcd-certs/ca.pem"
                - "--cert=/etc/etcd-certs/client.pem"
                - "--key=/etc/etcd-certs/client-key.pem"
                - "--etcd-storage-quota-bytes=8589934592"     # 8Gi — dbQuota 출처(필수!)
                - "--defrag-rule=(dbSizeInUse*2 < dbSize && dbSize > dbQuota/2 && dbSizeInUse > 800*1024*1024) || dbSize > dbQuota*80/100"
                - "--compaction=false"
                - "--move-leader"
                - "--wait-between-defrags=30s"
                - "--auto-disalarm"
                - "--command-timeout=60s"
              securityContext:              # 컨테이너: 권한상승 차단·루트FS 읽기전용·cap 제거
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities: { drop: ["ALL"] }
              volumeMounts:
                - { name: certs, mountPath: /etc/etcd-certs, readOnly: true }
                - { name: tmp,   mountPath: /tmp }      # readOnlyRootFs 대비 쓰기영역
              resources:
                requests: { cpu: "50m", memory: "64Mi" }
                limits:   { cpu: "500m", memory: "256Mi" }
          volumes:
            - name: certs
              secret:
                secretName: etcd-client-certs
                defaultMode: 0440          # fsGroup(65532) 그룹 읽기
            - name: tmp
              emptyDir: {}
```

### 3.4 icdataops-**prd** CronJob (etcd 5멤버)

dev와 **`--endpoints`(5대)·schedule·command-timeout만 다릅니다**(고 QPS → 저빈도·여유 timeout).
SA/Secret/NetworkPolicy/securityContext는 동일(같은 ns 또는 prd 전용 ns에 동형 적용).

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-conditional-defrag
  namespace: etcd-maintenance
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
      activeDeadlineSeconds: 3600     # 5멤버·큰 DB 여유
      template:
        metadata:
          labels: { app: etcd-conditional-defrag }
        spec:
          serviceAccountName: etcd-defrag
          automountServiceAccountToken: false
          restartPolicy: Never
          securityContext:
            runAsNonRoot: true
            runAsUser: 65532
            runAsGroup: 65532
            fsGroup: 65532
            seccompProfile: { type: RuntimeDefault }
          containers:
            - name: defrag
              image: <NEXUS>/etcd-defrag:v0.41.0
              # command 생략 — 이미지 ENTRYPOINT(/ko-app/etcd-defrag) 사용
              # (이 이미지는 ko 빌드 distroless라 PATH에 etcd-defrag 바이너리가 없음)
              args:
                - "--endpoints=https://<prd-etcd-1>:2379,https://<prd-etcd-2>:2379,https://<prd-etcd-3>:2379,https://<prd-etcd-4>:2379,https://<prd-etcd-5>:2379"
                - "--cluster"
                - "--cacert=/etc/etcd-certs/ca.pem"
                - "--cert=/etc/etcd-certs/client.pem"
                - "--key=/etc/etcd-certs/client-key.pem"
                - "--etcd-storage-quota-bytes=8589934592"     # 8Gi (필수!)
                - "--defrag-rule=(dbSizeInUse*2 < dbSize && dbSize > dbQuota/2 && dbSizeInUse > 800*1024*1024) || dbSize > dbQuota*80/100"
                - "--compaction=false"
                - "--move-leader"
                - "--wait-between-defrags=30s"
                - "--auto-disalarm"
                - "--command-timeout=120s"        # 5멤버·큰 DB 여유
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities: { drop: ["ALL"] }
              volumeMounts:
                - { name: certs, mountPath: /etc/etcd-certs, readOnly: true }
                - { name: tmp,   mountPath: /tmp }
              resources:
                requests: { cpu: "50m", memory: "64Mi" }
                limits:   { cpu: "500m", memory: "256Mi" }
          volumes:
            - name: certs
              secret: { secretName: etcd-client-certs, defaultMode: 0440 }
            - name: tmp
              emptyDir: {}
```

### 3.5 NetworkPolicy — egress를 etcd 노드:2379로만 (cilium)

기본 egress 차단 정책이 있는 경우, defrag Pod가 etcd 노드 `:2379`로만 나가도록 명시 허용합니다.
(IP로 접속하므로 DNS egress는 불필요.)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: etcd-defrag-egress
  namespace: etcd-maintenance
spec:
  podSelector:
    matchLabels: { app: etcd-conditional-defrag }
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock: { cidr: <dev-etcd-1>/32 }
        - ipBlock: { cidr: <dev-etcd-2>/32 }
        - ipBlock: { cidr: <dev-etcd-3>/32 }
        # prd는 etcd 5대 CIDR로 (또는 etcd 서브넷 1개로) 교체
      ports:
        - { protocol: TCP, port: 2379 }
```

> ⚠ **전용 etcd 노드가 k8s에서 완전히 분리(라우팅 불가)** 라면 k8s CronJob 자체가 불가합니다 →
> etcd 노드에서 `etcd-defrag`를 **systemd timer**로 직접 돌리세요(§6). 이때는 로컬 접속이라 Secret도 불필요.

---

## 4. dry-run 테스트 (`--dry-run`, 정지시간 0)

도구에 **`--dry-run`** 이 내장되어 있습니다: *"evaluate whether or not endpoints require
defragmentation, but don't actually perform it"* — 룰을 멤버별로 평가만 하고 **실제 defrag/disarm은 안 합니다.**

### 4.1 etcd 노드에서 직접 (바이너리 1회 — 가장 빠른 확인)

etcd 노드는 인증서·로컬 etcd가 다 있으므로 가장 간단합니다(바이너리 미러만 있으면 됨).

```sh
# etcd 노드에 SSH 후 (로컬 접속 → 127.0.0.1 + 자기 admin 인증서)
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

## 8. 반입 자산 (이미지 + 단일 YAML 세트) — `ops/etcd-defrag/`

| 파일 | 용도 |
|---|---|
| `ops/etcd-defrag/images/etcd-defrag-v0.41.0-linux-amd64.tar.gz` | `docker save`본(13MB, amd64) — Nexus 반입 원본(+`.sha256`) |
| `ops/etcd-defrag/import-image.sh` | `save`(인터넷측) / `push`(폐쇄망 Nexus) 2단계 |
| `ops/etcd-defrag/etcd-conditional-defrag.yaml` | ns·SA·NetworkPolicy·CronJob **단일 적용 세트**(placeholder 치환) |
| `ops/etcd-defrag/README.md` | 반입·적용 절차 |

```sh
# 이미지 Nexus 반입
./import-image.sh save                                  # 인터넷측: tar 생성
NEXUS=nexus.example.com:8082/dataops ./import-image.sh push   # 폐쇄망: load→tag→push

# 매니페스트 적용 (Secret 먼저 생성 → placeholder 치환 → apply)
kubectl -n etcd-maintenance create secret generic etcd-client-certs \
  --from-file=ca.pem=ca.pem --from-file=client.pem=admin-<node>.pem \
  --from-file=client-key.pem=admin-<node>-key.pem
kubectl apply -f etcd-conditional-defrag.yaml
```

> 이미지 사실(검증됨): `arch amd64/linux`, `User=65532`(ko distroless nonroot),
> `ENTRYPOINT=/ko-app/etcd-defrag` → **`command` 오버라이드 금지, `args`만 전달**.
> digest `sha256:c7b34d25…ec7db1e4`. 위 세트의 `runAsUser:65532`는 이미지 기본 user와 일치합니다.

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
