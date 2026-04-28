# Bitbucket SSH Access Key 기반 git sync 가이드

provisioner Job 의 git 인증을 HTTP Access Token 대신 **SSH access key (deploy key)**
로 전환하는 절차. organization 별 dashboard repo 분리 운영도 같은 패턴 확장.

---

## 0. HTTP Token vs SSH Key — 어느 쪽을 쓸까

| 항목 | HTTP Access Token | SSH Access Key |
|------|-------------------|-----------------|
| Bitbucket 설정 위치 | User Profile → HTTP access tokens | Repository → Settings → Access keys |
| 권한 범위 | repository / project / global 선택 | 단일 repository **(deploy key)** |
| 만료 | 발급 시 지정 (180일 등) | 만료 없음 (수동 폐기) |
| 폐쇄망 친화도 | http(s) proxy 설정만 | port 22 (or 7999 for BBDC) 통과 필요 |
| 노출 위험 | URL 에 박히면 process list 누출 | private key 가 Secret 안에만 — 더 안전 |
| 운영 권장 | 일반 sync (단순) | **org 별 분리 / read-only 강제 / token rotation 정책 까다로울 때** |
| Secret 구조 | `token` + `username` | `id_rsa` (or ed25519) + `known_hosts` |

조직 별로 별도 repo + 팀 별 Read-only 권한 분리 운영이 목표라면 **SSH access key**
가 적합 — Bitbucket Cloud/DC 모두 repository 단위 deploy key 발급이 standard.

---

## 1. 사전 작업 (인터넷 zone 또는 운영 zone host)

### 1.1 SSH key pair 생성 (ed25519, password-less)

```bash
# 운영 zone 의 작업 host 에서
ssh-keygen -t ed25519 -N '' -C 'svc-loadtest@grafana-gitops' \
  -f /tmp/grafana-gitops-deploy

# 생성 결과:
# /tmp/grafana-gitops-deploy       (private key — Secret 으로만 보관)
# /tmp/grafana-gitops-deploy.pub   (public key — Bitbucket 에 업로드)
```

> **알고리즘**: ed25519 권장 (짧고 빠름). 기관 정책상 RSA 만 허용 시 `-t rsa -b 4096`.

### 1.2 Bitbucket 에 public key 업로드

#### Bitbucket Data Center (사내 운영)
1. Repository 진입: `LOADTEST/grafana-dashboards`
2. **Settings → Access keys → Add key**
3. Label: `grafana-gitops-provisioner` (식별자)
4. Permission: **Read** (sync only — drift 양방향 동기화하려면 Write)
5. Key text: `cat /tmp/grafana-gitops-deploy.pub` 결과 붙여넣기
6. Save

#### Bitbucket Cloud
- Repository → **Repository settings → Access keys** (sidebar)
- Bitbucket Cloud 의 access key 는 **read-only 만** — write 동기화 필요 시 deploy
  account + app password 또는 Repository Access Token 사용 권장.

### 1.3 Bitbucket SSH host key 추출 (`known_hosts`)

MITM 방지 — 신뢰된 host key 를 미리 저장해 첫 sync 시 verify:

```bash
# Bitbucket DC (보통 7999 포트 사용; 22 포트인 경우 -p 22 또는 생략)
ssh-keyscan -p 7999 -t ed25519,rsa bitbucket.intranet > /tmp/known_hosts
cat /tmp/known_hosts

# Bitbucket Cloud
ssh-keyscan -t ed25519,rsa bitbucket.org > /tmp/known_hosts
```

> **운영 보안**: ssh-keyscan 결과는 별도 채널로 fingerprint 공식 문서와 대조 후
> `known_hosts` 채택. Bitbucket Cloud 의 fingerprint 는 Atlassian 공식 페이지에
> 공개됨 (`https://confluence.atlassian.com/.../bitbucket-cloud-ssh-fingerprints`).

---

## 2. Kubernetes Secret 작성

```bash
kubectl -n gitops create secret generic git-ssh \
  --from-file=id_rsa=/tmp/grafana-gitops-deploy \
  --from-file=known_hosts=/tmp/known_hosts \
  --from-literal=username='svc-loadtest' \
  --from-literal=email='svc-loadtest@example.com'

# 검증 — id_rsa 는 mode 0400 으로 마운트되어야 함 (자동 처리됨)
kubectl -n gitops describe secret git-ssh
```

> **클러스터 내 보호**: gitops ns 의 SA 권한 최소화 — `secret/git-ssh` 를
> read 할 수 있는 SA 는 provisioner 만 한정 (별도 RoleBinding 권장).

---

## 3. provisioner Job 패치

`40-provisioner-job.yaml` 의 env / args / volumes 만 교체하면 됨. 기존 파일을
복사해서 `40-provisioner-job-ssh.yaml` 로 보관 권장.

### 3.1 변경 포인트

```yaml
spec:
  template:
    spec:
      containers:
        - name: provisioner
          image: nexus.intranet:8082/loadtest/loadtest-tools:0.1.2
          env:
            # Bitbucket SSH clone URL (HTTP 가 아님)
            - name: GIT_REMOTE_URL
              value: "ssh://git@bitbucket.intranet:7999/loadtest/grafana-dashboards.git"
            # SSH 환경
            - name: GIT_SSH_COMMAND
              value: "ssh -i /etc/git-ssh/id_rsa -o UserKnownHostsFile=/etc/git-ssh/known_hosts -o StrictHostKeyChecking=yes"
            - { name: GIT_USER,  valueFrom: { secretKeyRef: { name: git-ssh, key: username } } }
            # 그 외 Grafana / Prometheus URL 은 동일 (HTTP 가이드와 같음)
            - { name: GRAFANA_URL,    value: "http://kps-grafana.monitoring.svc:80" }
            - { name: GRAFANA_USER,   value: "admin" }
            - { name: GRAFANA_PASS,   valueFrom: { secretKeyRef: { name: kps-grafana, key: admin-password } } }
            - { name: PROMETHEUS_URL, value: "http://kps-prometheus.monitoring.svc:9090" }
          volumeMounts:
            - name: git-ssh
              mountPath: /etc/git-ssh
              readOnly: true
          command: ["bash", "-c"]
          args:
            - |
              set -e
              # 핵심: HTTP Bearer 분기 제거 → SSH clone (env 의 GIT_SSH_COMMAND 가 자동 적용)
              cd /tmp
              rm -rf repo
              git clone "${GIT_REMOTE_URL}" repo
              cd repo
              echo "  repo HEAD: $(git rev-parse --short HEAD)"
              # ... (이하 기존 [3/5] ~ [5/5] 동일 — Grafana API 호출 부분)
      volumes:
        - name: git-ssh
          secret:
            secretName: git-ssh
            defaultMode: 0400      # private key 권한 강제
```

### 3.2 sed 일괄 패치 (HTTP → SSH 전환 자동화)

`40-provisioner-job-ssh.yaml` 을 한 번 만들어두면 이후엔 그것만 적용:

```bash
DIR=deploy/load-testing-airgap/30-grafana-gitops
cp $DIR/40-provisioner-job.yaml $DIR/40-provisioner-job-ssh.yaml

# 위 §3.1 차이만 직접 편집하거나 patch 적용
kubectl apply -f $DIR/40-provisioner-job-ssh.yaml
```

운영 CronJob 으로 변환 (10분 sync) 도 동일 — `kind: Job` → `kind: CronJob` +
`schedule: "*/10 * * * *"`.

---

## 4. Organization 별 repo 분리 (확장 패턴)

조직마다 dashboard 책임자가 다르고 read 권한도 분리하려면 repo 자체를 분리:

```
bitbucket.intranet/scm/
├── loadtest-engineering/grafana-dashboards     ← Engineering 전용
├── loadtest-dataplatform/grafana-dashboards    ← DataPlatform 전용
├── loadtest-security/grafana-dashboards
├── loadtest-operations/grafana-dashboards
└── loadtest-research/grafana-dashboards
```

각 repo 에 별도 SSH access key 를 발급, Secret 도 분리:

```bash
for ORG in engineering dataplatform security operations research; do
  ssh-keygen -t ed25519 -N '' -C "svc-loadtest@$ORG" -f /tmp/key-$ORG
  # → public key 를 해당 org repo 의 Access Keys 에 업로드
  kubectl -n gitops create secret generic git-ssh-$ORG \
    --from-file=id_rsa=/tmp/key-$ORG \
    --from-file=known_hosts=/tmp/known_hosts \
    --from-literal=username='svc-loadtest' \
    --from-literal=email="svc-loadtest+$ORG@example.com"
done
```

provisioner Job 의 **org-loop 안에서** 각 org 별 SSH key + remote URL 을 해석:

```bash
for ORG in $ORGS; do
  ORG_LC=$(echo "$ORG" | tr '[:upper:]' '[:lower:]')
  # 매 iteration 마다 ssh agent 갱신은 비효율 → fixed key 마다 별도 dir
  GIT_SSH_KEY="/etc/git-ssh-$ORG_LC/id_rsa"
  GIT_KNOWN_HOSTS="/etc/git-ssh-$ORG_LC/known_hosts"
  REMOTE="ssh://git@bitbucket.intranet:7999/loadtest-$ORG_LC/grafana-dashboards.git"
  GIT_SSH_COMMAND="ssh -i $GIT_SSH_KEY -o UserKnownHostsFile=$GIT_KNOWN_HOSTS -o StrictHostKeyChecking=yes" \
    git clone "$REMOTE" /tmp/repo-$ORG_LC
  # 이후 Grafana API 적용은 해당 org context 에서만
  apply_to_grafana_org "$ORG" "/tmp/repo-$ORG_LC"
done
```

이 변형은 5개 Secret + 5번 clone 으로 동작. 단점은 RBAC 설정 + Secret 회전이
배가 됨 — 단순 운영이라면 §3 의 단일 repo 가 적정.

---

## 5. 검증 + 트러블슈팅

### 5.1 Secret + Permission

```bash
# private key mode 확인 (0400 이어야 함 — defaultMode: 0400)
kubectl -n gitops run ssh-test --image=loadtest-tools:0.1.2 --restart=Never --rm -i \
  --overrides='{"spec":{"volumes":[{"name":"k","secret":{"secretName":"git-ssh","defaultMode":256}}],"containers":[{"name":"ssh-test","image":"loadtest-tools:0.1.2","stdin":true,"volumeMounts":[{"name":"k","mountPath":"/etc/git-ssh"}]}]}}' \
  -- ls -la /etc/git-ssh
# → -r-------- ... id_rsa
```

### 5.2 SSH 접근 테스트 (clone 없이)

```bash
kubectl -n gitops run ssh-test --image=loadtest-tools:0.1.2 --restart=Never --rm -i \
  --overrides='{"spec":{"volumes":[{"name":"k","secret":{"secretName":"git-ssh","defaultMode":256}}],"containers":[{"name":"ssh-test","image":"loadtest-tools:0.1.2","stdin":true,"volumeMounts":[{"name":"k","mountPath":"/etc/git-ssh"}]}]}}' \
  -- bash -c '
    ssh -i /etc/git-ssh/id_rsa \
        -o UserKnownHostsFile=/etc/git-ssh/known_hosts \
        -p 7999 \
        git@bitbucket.intranet info
  '
# 정상이면 ATL_NEXT_PASSWORD: ... welcome to Bitbucket 또는 PROJECT 목록 출력.
```

### 5.3 흔한 에러

| 증상 | 원인 / 조치 |
|------|-------------|
| `Permission denied (publickey)` | public key 가 Bitbucket 에 등록 안 됨 또는 Read 권한 없음 |
| `Host key verification failed` | `known_hosts` 누락 또는 서버 host key 변경 → ssh-keyscan 재실행 |
| `WARNING: UNPROTECTED PRIVATE KEY FILE` | Secret 의 defaultMode 가 0400 이 아님 — 매니페스트 확인 |
| `kex_exchange_identification: Connection closed` | port 22 가 아닌 7999 사용? (Bitbucket DC 기본 7999) |
| `git clone` hang | egress 7999 차단 — NetworkPolicy / 사내 방화벽 점검 |
| RSA 만 허용되는 구버전 서버 | `-t rsa -b 4096` 으로 재발급 |

### 5.4 known_hosts rotation

Bitbucket DC 가 host key 를 갱신하면 (드문 경우) `known_hosts` 업데이트 필요:
```bash
ssh-keyscan -p 7999 bitbucket.intranet > /tmp/known_hosts
kubectl -n gitops create secret generic git-ssh \
  --from-file=known_hosts=/tmp/known_hosts \
  --dry-run=client -o yaml | kubectl apply -f -
# (id_rsa 는 그대로 유지 — known_hosts 만 patch)
```

---

## 6. 운영 적용 체크리스트

배포 전:
- [ ] SSH key pair 생성 (ed25519, password-less)
- [ ] Bitbucket repo Settings → Access keys 에 public key 등록 (Read)
- [ ] `known_hosts` 확보 (ssh-keyscan + fingerprint 공식 문서 대조)
- [ ] `git-ssh` Secret 작성 (id_rsa + known_hosts + username + email)
- [ ] Job 의 image (`loadtest-tools:0.1.2`) 가 Nexus 에 mirror 되어 있음
- [ ] 사내 방화벽: gitops ns → bitbucket:7999 egress 허용

배포 후:
- [ ] 첫 Job 실행 로그에 `Cloning into 'repo'...` + HEAD hash 출력
- [ ] Grafana 5조직 모두 dashboards=N folders=M 정상
- [ ] 임의 dashboard UI 수정 → 10분 후 자동 복원되는지 (drift sync)
- [ ] CronJob 알림 (PrometheusRule) 등록

---

## 7. 인증 모드 선택 정리

```
운영 시 추천 분기:

  - 단일 dashboard repo + 운영 보안 정책 단순  → HTTP Access Token (현 default)
  - org 별 분리 + read-only 강제 + 키 rotation 정책 까다로움  → SSH Access Key
  - 양쪽 모두 — Bearer http.extraheader / GIT_SSH_COMMAND 패턴 — 동일 Job 매니페스트의
    env / volumes 차이만 swap 하면 됨.
```

운영용 매니페스트 두 변형을 함께 보관하면 (`40-provisioner-job.yaml` HTTP +
`40-provisioner-job-ssh.yaml` SSH) 보안 사고 시 즉시 모드 전환 가능.

---

## 8. 관련 파일

- HTTP Token 가이드: `deploy/load-testing-airgap/30-grafana-gitops/AIRGAP-GUIDE.md`
- 현재 (HTTP Bearer) provisioner: `deploy/load-testing-airgap/30-grafana-gitops/40-provisioner-job.yaml`
- testbed gitea seed (HTTP only): `deploy/load-testing-airgap/30-grafana-gitops/30-seed-job.yaml`
- 5조직 GitOps 흐름: `deploy/load-testing-airgap/30-grafana-gitops/README.md`
