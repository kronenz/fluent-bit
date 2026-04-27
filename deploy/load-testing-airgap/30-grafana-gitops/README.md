# Grafana GitOps 배포 (testbed)

Bitbucket → (운영) / **gitea (=GitLab 호환)** → (testbed) 의 git 저장소를
source-of-truth 로 5개 조직에 동일한 폴더 트리 + 동일한 대시보드를 멱등 배포.

## 컴포넌트

| 파일 | 역할 |
|------|------|
| `00-namespace.yaml` | `gitops` ns |
| `10-gitea.yaml` | gitea (GitLab 호환 git server, sqlite + emptyDir) — testbed 용 |
| `20-repo-content.yaml` | bitbucket repo 의 testbed 시뮬레이션 (ConfigMap) |
| `30-seed-job.yaml` | ConfigMap → gitea 로 push (testbed 한정) |
| `40-provisioner-job.yaml` | gitea clone → Grafana API 로 5조직 적용 (멱등) |

## 가상 조직 / 폴더 / 대시보드

```
조직 (5):
  Engineering / DataPlatform / Security / Operations / Research

폴더 트리 (모든 조직 동일):
  Ingest Pipeline/
    OpenSearch/
      • OpenSearch Cluster Overview
      • OpenSearch Index Performance
    Fluent Bit/
      • Fluent Bit Pipeline Throughput
      • Fluent Bit Memory Usage
  Infrastructure/
    Compute/
      • Node Overview
      • Pod Resource Usage
    Network/
      • Network Connectivity
  Application/
    • Spark Jobs
    • Trino Queries
  Chaos And Reliability/
    • Chaos Failure Drill

총: 4 top-level + 4 nested folders × 5 orgs = 40 folders
   10 dashboards × 5 orgs = 50 dashboards
```

## 운영 swap (bitbucket 으로 전환)

testbed → 운영 시 변경:
1. `00/10/20/30` 모두 제거 (gitea + seed Job 불필요)
2. Bitbucket HTTP Access Token 생성 + Secret:
   ```bash
   kubectl -n gitops create secret generic git-token \
     --from-literal=token='<bitbucket-access-token>' \
     --from-literal=username='svc-loadtest' \
     --from-literal=email='svc-loadtest@example.com'
   ```
3. `40-provisioner-job.yaml` 의 env 만 변경 (인증은 Bearer http.extraheader — basic auth 미사용):
   ```yaml
   env:
     - { name: GIT_REMOTE_URL, value: "https://bitbucket.example.com/scm/loadtest/grafana-dashboards.git" }
     - { name: GIT_TOKEN, valueFrom: { secretKeyRef: { name: git-token, key: token    } } }
     - { name: GIT_USER,  valueFrom: { secretKeyRef: { name: git-token, key: username } } }
   ```
3. CronJob 으로 변경 (5~10분 주기 sync):
   ```yaml
   kind: CronJob
   spec:
     schedule: "*/10 * * * *"
     jobTemplate: { spec: { template: { ... } } }
   ```

## 배포 절차

```bash
CTX=minikube-remote
DIR=deploy/load-testing-airgap/30-grafana-gitops

# testbed 한정 image swap (Nexus 미사용)
SWAP='sed -e s|nexus.intranet:8082/loadtest/loadtest-tools:0.1.2|loadtest-tools:0.1.2|g'

# 1. ns + gitea
kubectl --context=$CTX apply -f $DIR/00-namespace.yaml
kubectl --context=$CTX apply -f $DIR/10-gitea.yaml
kubectl --context=$CTX -n gitops wait --for=condition=ready pod -l app=gitea --timeout=180s

# 2. repo content + seed
kubectl --context=$CTX apply -f $DIR/20-repo-content.yaml
cat $DIR/30-seed-job.yaml | $SWAP | kubectl --context=$CTX apply -f -
kubectl --context=$CTX -n gitops wait --for=condition=complete job/gitea-seed --timeout=180s

# 3. provision
cat $DIR/40-provisioner-job.yaml | $SWAP | kubectl --context=$CTX apply -f -
kubectl --context=$CTX -n gitops wait --for=condition=complete job/grafana-provisioner --timeout=300s

# 4. 결과
kubectl --context=$CTX -n gitops logs job/grafana-provisioner | tail -30
```

## 검증

```bash
# Grafana 의 organization 목록
kubectl -n monitoring port-forward svc/kps-grafana 3000:80 &
curl -s -u admin:admin http://localhost:3000/api/orgs | jq '.[] | .name'
# Engineering / DataPlatform / Security / Operations / Research / Main Org.

# 특정 org 의 폴더/대시보드
ORG_ID=2  # Engineering
curl -s -u admin:admin -X POST http://localhost:3000/api/user/using/$ORG_ID
curl -s -u admin:admin http://localhost:3000/api/folders | jq '.[] | {uid, title, parentUid}'
curl -s -u admin:admin "http://localhost:3000/api/search?type=dash-db" | jq 'length'
# 10
```

## UI 접근

- Grafana: http://<minikube-ip>:30030 (admin/admin) → 우상단 org 전환
- gitea  : http://<minikube-ip>:30300 (gitops/gitops-pw) → repo 확인

## 재실행 (drift 복원)

provisioner 는 멱등 — 누가 UI 에서 dashboard 를 변경해도 다음 sync 에서
git 의 상태로 복원됨:

```bash
kubectl --context=$CTX -n gitops delete job grafana-provisioner
cat $DIR/40-provisioner-job.yaml | $SWAP | kubectl --context=$CTX apply -f -
```

## 한계 / TODO

- **삭제 동기화 미구현**: git 에서 dashboard 파일을 지워도 Grafana 는 안 지움 →
  `/api/search` 조회 후 git 에 없는 uid 만 `DELETE /api/dashboards/uid/{uid}`
  로 보강 가능 (nice-to-have).
- **datasource org 별 중복**: 각 org 가 자체 Prometheus DS 를 가짐 (의도된 설계)
- **gitea emptyDir**: 재기동 시 repo 휘발 → 영구 보관 필요 시 PVC 추가
- **Nested folders**: Grafana 11+ 필요. testbed 는 12.1.0 → OK
- **권한 (RBAC)**: 폴더별 viewer/editor 분리 필요 시 `/api/folders/{uid}/permissions` 추가
