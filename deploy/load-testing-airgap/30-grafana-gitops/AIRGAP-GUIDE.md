# Grafana GitOps — 폐쇄망 적용 가이드

testbed (minikube + gitea) 에서 검증된 매니페스트를 폐쇄망 운영 환경에
이전하는 단계별 절차. 핵심은 두 가지:

1. **이미지** : `loadtest-tools:0.1.2` 가 Nexus 에 있어야 함 (gitea 는 운영에서 불필요)
2. **git source** : testbed 의 gitea (`http://gitea.gitops.svc:3000/...`) →
   운영의 사내 Bitbucket (`https://bitbucket.intranet/scm/loadtest/...`)

---

## 0. 한 눈에 보는 차이표

| 컴포넌트 | testbed (minikube) | 폐쇄망 운영 |
|----------|--------------------|--------------|
| `00-namespace.yaml` | `gitops` ns | 그대로 |
| `10-gitea.yaml` | gitea pod 띄움 | **불필요** (사내 Bitbucket 사용) |
| `20-repo-content.yaml` | ConfigMap 으로 시뮬레이션 | **불필요** (Bitbucket 이 source) |
| `30-seed-job.yaml` | ConfigMap → gitea push | **불필요** |
| `40-provisioner-job.yaml` | gitea clone → Grafana API | **GIT_REMOTE_URL/CRED 만 교체** + CronJob 변환 |
| 이미지 path | `loadtest-tools:0.1.2` (local) | `nexus.intranet:8082/loadtest/loadtest-tools:0.1.2` |
| 인증 | basic auth (gitops/gitops-pw) | Bitbucket PAT (personal access token) |

---

## 1. 사전 준비

### 1.1 Nexus 이미지 확인

`loadtest-tools:0.1.2` 는 OSB 시나리오에서 이미 사용되므로 보통 이미 mirror 됨.
미러 안 됐으면:

```bash
# 인터넷 zone 에서 (이미 0.1.2 air-gap bundle 보유 시)
docker load -i dist/loadtest-airgap-bundle-0.1.2/image/loadtest-tools-0.1.2.tar.gz
docker tag loadtest-tools:0.1.2 nexus.intranet:8082/loadtest/loadtest-tools:0.1.2
docker push nexus.intranet:8082/loadtest/loadtest-tools:0.1.2

# 또는 자동 스크립트
bash dist/loadtest-airgap-bundle-0.1.2/scripts/push-to-nexus.sh \
     dist/loadtest-airgap-bundle-0.1.2/image/loadtest-tools-0.1.2.tar.gz
```

### 1.2 Bitbucket repo 준비

운영 zone 의 사내 Bitbucket 에 repo 생성 + 초기 import:

```bash
# 인터넷 zone 에서 testbed gitea 의 검증된 repo 를 그대로 가져옴
git clone http://gitops:gitops-pw@<minikube-ip>:30300/gitops/grafana-dashboards.git
cd grafana-dashboards

# 운영 Bitbucket 으로 push
git remote add airgap https://<user>@bitbucket.intranet/scm/loadtest/grafana-dashboards.git
git push airgap main

# .git/config 에 적힌 token 은 commit 후 정리
```

운영 zone 의 git 사용자는 **read-only PAT** 만 부여:
- Project: `LOADTEST`
- Repository: `grafana-dashboards`
- Permission: `Repository Read` only (provisioner 는 push 하지 않음)

### 1.3 Secret 생성 (Bitbucket PAT)

```bash
kubectl -n gitops create secret generic bitbucket-creds \
  --from-literal=username='svc-loadtest' \
  --from-literal=token='<PAT-readonly>'
```

### 1.4 Grafana admin 자격 분리 (권장)

운영 환경에선 `admin/admin` 그대로 두지 말고 별도 service account / API key 권장:

```bash
# Grafana UI: Configuration → Service accounts → New
#   Name : grafana-provisioner
#   Role : Server Admin (조직 생성 권한 필요)
# → Generate token → 복사

kubectl -n gitops create secret generic grafana-creds \
  --from-literal=token='<sa-token>'
```

Provisioner 의 Authorization 헤더를 `Bearer ${TOKEN}` 으로 교체 (아래 4.3 참고).

---

## 2. 매니페스트 변경

### 2.1 적용 대상 (운영)

**적용 O**: `00-namespace.yaml` / `40-provisioner-job.yaml` (수정본)
**적용 X**: `10-gitea.yaml` / `20-repo-content.yaml` / `30-seed-job.yaml`

### 2.2 `40-provisioner-job.yaml` 운영용 패치

`env` 3개 + image path + (선택) Bearer 인증 + CronJob 변환:

```yaml
apiVersion: batch/v1
kind: CronJob                              # ← Job → CronJob
metadata:
  name: grafana-provisioner
  namespace: gitops
spec:
  schedule: "*/10 * * * *"                 # 10분마다 drift 동기화
  concurrencyPolicy: Forbid                # 중복 실행 방지
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
  jobTemplate:
    spec:
      backoffLimit: 0
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: provisioner
              # ── 변경 1 : Nexus 경로
              image: nexus.intranet:8082/loadtest/loadtest-tools:0.1.2
              imagePullPolicy: IfNotPresent
              env:
                # ── 변경 2 : Bitbucket clone URL
                - { name: GIT_REMOTE_URL,
                    value: "https://bitbucket.intranet/scm/loadtest/grafana-dashboards.git" }
                - { name: GIT_USER, valueFrom: { secretKeyRef: { name: bitbucket-creds, key: username } } }
                - { name: GIT_PASS, valueFrom: { secretKeyRef: { name: bitbucket-creds, key: token    } } }
                # ── 변경 3 : 운영 Grafana svc / Prometheus svc
                - { name: GRAFANA_URL,    value: "http://kps-grafana.monitoring.svc:80" }
                - { name: GRAFANA_USER,   value: "admin" }      # 또는 SA token (4.3)
                - { name: GRAFANA_PASS,   value: "<운영 admin pw>" }
                - { name: PROMETHEUS_URL, value: "http://kps-prometheus.monitoring.svc:9090" }
              command: ["bash", "-c"]
              args:
                # 본문은 testbed 와 동일 (UID readonly bug 수정본 그대로)
```

### 2.3 sed 일괄 패치 (image swap 불필요 — 운영은 Nexus 경로 그대로)

testbed 에서 사용한 image swap (`loadtest-tools:0.1.2` 로 변환) 은 운영에선 적용 X.
**운영은 매니페스트 그대로 `kubectl apply`**.

---

## 3. 적용 순서 (운영)

```bash
CTX=prod-cluster
DIR=deploy/load-testing-airgap/30-grafana-gitops

# 1. namespace
kubectl --context=$CTX apply -f $DIR/00-namespace.yaml

# 2. secret (사전 준비 1.3 에서 이미 생성했으면 skip)
kubectl --context=$CTX -n gitops get secret bitbucket-creds || \
  echo "FAIL: bitbucket-creds 미생성 (1.3 참고)"

# 3. provisioner CronJob (운영용 패치본)
kubectl --context=$CTX apply -f $DIR/40-provisioner-job.yaml.airgap

# 4. 즉시 1회 실행 (10분 기다리지 않고 검증)
kubectl --context=$CTX -n gitops create job --from=cronjob/grafana-provisioner first-run

# 5. 결과
kubectl --context=$CTX -n gitops wait --for=condition=complete job/first-run --timeout=300s
kubectl --context=$CTX -n gitops logs job/first-run | tail -40
```

성공 로그 끝부분:
```
[5/5] 검증 — 각 org 대시보드 카운트
  Engineering: dashboards=10 folders=4
  ...
================ provision 완료 ================
```

---

## 4. 검증 체크리스트

### 4.1 organization / folder / dashboard 적용 확인

```bash
# port-forward (운영에선 ingress URL 사용)
kubectl --context=$CTX -n monitoring port-forward svc/kps-grafana 13000:80 &

# 1. orgs
curl -s -u admin:<pw> http://localhost:13000/api/orgs | jq '.[].name'
# → Engineering / DataPlatform / Security / Operations / Research / Main Org.

# 2. 각 org 의 nested 포함 폴더
for OID in 2 3 4 5 6; do
  curl -s -u admin:<pw> -X POST http://localhost:13000/api/user/using/$OID >/dev/null
  COUNT=$(curl -s -u admin:<pw> "http://localhost:13000/api/search?type=dash-folder&limit=1000" | jq 'length')
  DASH=$(curl  -s -u admin:<pw> "http://localhost:13000/api/search?type=dash-db&limit=1000"     | jq 'length')
  echo "org $OID : folders=$COUNT dashboards=$DASH"
done
# 기대: 모든 org folders=8 dashboards=10
```

### 4.2 CronJob schedule 확인

```bash
kubectl --context=$CTX -n gitops get cronjob grafana-provisioner
# NAME                  SCHEDULE       SUSPEND   ACTIVE   LAST SCHEDULE
# grafana-provisioner   */10 * * * *   False     0        <2m
```

### 4.3 (선택) SA token 으로 변환 후 재검증

```bash
TOKEN=$(kubectl -n gitops get secret grafana-creds -o jsonpath='{.data.token}' | base64 -d)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:13000/api/orgs | jq length
# 6
```

provisioner 매니페스트의 args 안 `AUTH=` 부분만 변경:
```bash
# 기존
AUTH=(-u "${GRAFANA_USER}:${GRAFANA_PASS}")
# 변경
AUTH=(-H "Authorization: Bearer ${GRAFANA_TOKEN}")
```
+ env 에 `GRAFANA_TOKEN` 추가하고 `GRAFANA_USER/PASS` 제거.

---

## 5. 운영 자동화 권장 보강

### 5.1 삭제 동기화 (drift 양방향 복원)

현재 provisioner 는 git → Grafana **upsert 만**. git 에서 dashboard 파일을
지워도 Grafana 에는 남음. 운영에선 다음 블록을 `[5/5]` 직전에 추가 권장:

```bash
echo "[4.5/5] 고아 dashboard 삭제 (git 에 없는 uid)"
# git 에 있는 uid 목록
GIT_UIDS=$(find dashboards -name '*.json' -exec jq -r '.uid' {} \; | sort -u)
# Grafana 에 등록된 uid 목록
LIVE_UIDS=$(curl -fsS "${AUTH[@]}" "${GRAFANA_URL}/api/search?type=dash-db&limit=5000" \
            | jq -r '.[].uid' | sort -u)
# diff → 삭제
for u in $(comm -13 <(echo "$GIT_UIDS") <(echo "$LIVE_UIDS")); do
  curl -fsS "${AUTH[@]}" -X DELETE "${GRAFANA_URL}/api/dashboards/uid/${u}" >/dev/null
  echo "  - 삭제 $u"
done
```

### 5.2 폴더 권한 (조직별 RBAC)

조직별 권한이 필요하면 `repo/permissions.yaml` 추가 후 provisioner 가 적용:

```yaml
# repo/permissions.yaml
- folderUid: ingest-pipeline
  permissions:
    - { teamId: 1, permission: 1 }   # Viewer
    - { teamId: 2, permission: 2 }   # Editor
```

provisioner 안에서:
```bash
curl -fsS "${AUTH[@]}" "${CT[@]}" -X POST \
  "${GRAFANA_URL}/api/folders/${UID}/permissions" \
  -d @permissions.yaml
```

### 5.3 모니터링

CronJob 실패 알림 (kube-prometheus-stack alert rule 추가):
```yaml
- alert: GrafanaProvisionerFailed
  expr: kube_job_status_failed{namespace="gitops", job_name=~"grafana-provisioner.*"} > 0
  for: 5m
  annotations:
    summary: "Grafana GitOps provisioner 실패 — 대시보드 sync 중단"
```

---

## 6. 트러블슈팅

### 6.1 `bash: UID: readonly variable`

testbed 에서 발견된 버그 (이미 수정 반영). `UID` 는 bash 의 readonly 변수
(current user ID) — 일반 변수로 사용 불가. 매니페스트에 `F_UID` 로 rename
완료. 직접 수정한 변형이 있으면 동일 패턴 (`PUID`, `FUID`) 으로 회피.

### 6.2 `data source with the same name already exists` (409)

org 마다 datasource 1회만 생성하면 정상. 재실행 시 409 가 정상이므로
`case $DS_CODE in 200|201|409|422|400)` 로 모두 success 처리됨.

### 6.3 `parentUid` 무시되어 nested 폴더 안 만들어짐

Grafana 11 미만은 nested 폴더 미지원. testbed 는 12.1.0 → OK. 운영
Grafana 가 10.x 이면 helm chart upgrade 필요:
```bash
helm -n monitoring upgrade kps prometheus-community/kube-prometheus-stack \
     --set grafana.image.tag=12.1.0 --reuse-values
```

### 6.4 `/api/folders` 가 4개만 반환

Grafana 의 의도된 동작 — `/api/folders` 는 top-level 만 반환 (backward-compat).
nested 포함 전체는 `/api/search?type=dash-folder` 사용.

### 6.5 Bitbucket clone 실패 (`Authentication failed`)

PAT 의 권한 부족. `Repository Read` 가 필요. project-level 도 아닌 반드시
**repository-level** PAT.

### 6.6 image pull `unauthorized`

Nexus credential 누락. monitoring/gitops ns 에 imagePullSecret 적용:
```bash
kubectl -n gitops create secret docker-registry nexus-cred \
  --docker-server=nexus.intranet:8082 \
  --docker-username=svc-loadtest --docker-password='<pw>'

kubectl -n gitops patch sa default \
  -p '{"imagePullSecrets":[{"name":"nexus-cred"}]}'
```

### 6.7 CronJob 이 schedule 대로 안 도는 경우

```bash
kubectl -n gitops describe cronjob grafana-provisioner
# Events: 마지막 schedule 시각 + 사유 확인
# - "Cannot determine if job needs to be started: too many missed start times"
#   → suspend 후 재개 필요:
kubectl -n gitops patch cronjob grafana-provisioner -p '{"spec":{"suspend":false}}'
```

---

## 7. 롤백

### 7.1 일시 정지 (CronJob 만)

```bash
kubectl --context=$CTX -n gitops patch cronjob grafana-provisioner \
  -p '{"spec":{"suspend":true}}'
```

대시보드는 그대로 유지. 다시 활성화 시 `suspend:false`.

### 7.2 완전 제거

```bash
# CronJob + Job 이력
kubectl --context=$CTX -n gitops delete cronjob grafana-provisioner
kubectl --context=$CTX -n gitops delete jobs --all

# (선택) 추가된 organization 5개 + 폴더/대시보드 모두 제거
TOKEN=$(kubectl -n gitops get secret grafana-creds -o jsonpath='{.data.token}' | base64 -d)
GR=http://localhost:13000   # port-forward 필요
for ORG in Engineering DataPlatform Security Operations Research; do
  OID=$(curl -s -H "Authorization: Bearer $TOKEN" $GR/api/orgs \
        | jq -r --arg n "$ORG" '.[] | select(.name == $n) | .id')
  [ -n "$OID" ] && curl -s -H "Authorization: Bearer $TOKEN" -X DELETE $GR/api/orgs/$OID
done

# namespace 까지 제거
kubectl --context=$CTX delete ns gitops
```

### 7.3 Bitbucket repo 보존

provisioner 가 push 권한이 없으므로 git 은 원본 그대로 유지. 안전.

---

## 8. air-gap 적용 체크리스트 (운영 zone 작업자용)

배포 전 체크:
- [ ] `nexus.intranet:8082/loadtest/loadtest-tools:0.1.2` 가 존재 (`docker pull`)
- [ ] Bitbucket repo `LOADTEST/grafana-dashboards` 가 main branch 기준 최신
- [ ] PAT (read-only) 발급 완료
- [ ] Grafana 버전 ≥ 11 (nested folder 지원)
- [ ] 운영 Prometheus svc 이름 확인 (kube-prometheus-stack 의 release name 에 따라
      `kps-prometheus` / `prometheus-operated` 등 다를 수 있음)

배포 후 체크:
- [ ] CronJob 1회 수동 실행 (`kubectl create job --from=cronjob/...`)
- [ ] 5/5 단계 로그가 모두 success
- [ ] org 5개 모두 folders=8, dashboards=10
- [ ] 임의 dashboard 1개를 UI 에서 수정 → 10분 뒤 자동 복원되는지 (drift sync)
- [ ] CronJob 알림 (5.3) 등록

---

## 9. 운영 zone 으로 이전할 파일 목록

```
deploy/load-testing-airgap/30-grafana-gitops/
├── 00-namespace.yaml                          ← 그대로
└── 40-provisioner-job.yaml.airgap             ← 본 가이드 §2.2 기준 신규 생성

(선택) docs/load-testing-airgap/30-grafana-gitops/AIRGAP-GUIDE.md  ← 본 문서
```

`10-gitea.yaml` / `20-repo-content.yaml` / `30-seed-job.yaml` 는 **이전 X**
(testbed 한정).

---

## 부록 A. 운영용 provisioner 매니페스트 전문

testbed 의 `40-provisioner-job.yaml` 을 운영 패치한 전체 예시. 별도 파일로
저장 시 이름은 `40-provisioner-job.yaml.airgap` 권장.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: grafana-provisioner
  namespace: gitops
  labels: { app: grafana-provisioner, role: provisioner }
spec:
  schedule: "*/10 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
  jobTemplate:
    spec:
      backoffLimit: 0
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: provisioner
              image: nexus.intranet:8082/loadtest/loadtest-tools:0.1.2
              imagePullPolicy: IfNotPresent
              env:
                - { name: GIT_REMOTE_URL,
                    value: "https://bitbucket.intranet/scm/loadtest/grafana-dashboards.git" }
                - { name: GIT_USER, valueFrom: { secretKeyRef: { name: bitbucket-creds, key: username } } }
                - { name: GIT_PASS, valueFrom: { secretKeyRef: { name: bitbucket-creds, key: token    } } }
                - { name: GRAFANA_URL,    value: "http://kps-grafana.monitoring.svc:80" }
                - { name: GRAFANA_USER,   value: "admin" }
                - { name: GRAFANA_PASS,
                    valueFrom: { secretKeyRef: { name: kps-grafana, key: admin-password } } }
                - { name: PROMETHEUS_URL, value: "http://kps-prometheus.monitoring.svc:9090" }
              command: ["bash", "-c"]
              args:
                # ↓ testbed 40-provisioner-job.yaml 의 args 본문 그대로 복사
                - |
                  set -e
                  AUTH=(-u "${GRAFANA_USER}:${GRAFANA_PASS}")
                  CT=(-H "Content-Type: application/json")
                  trap 'echo "[FAIL] line=$LINENO cmd=$BASH_COMMAND" >&2' ERR
                  # ... (이하 testbed 와 동일)
              resources:
                requests: { cpu: "100m", memory: "128Mi" }
                limits:   { cpu: "1000m", memory: "512Mi" }
```

> **TIP**: 본문이 길어 매번 복사하지 않고 싶다면, args 를 ConfigMap 으로
> 분리해 `command: ["bash", "/scripts/provision.sh"]` + volumeMount 패턴으로
> 변환 가능. 운영 보강 단계에서 권장.
