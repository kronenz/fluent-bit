# 02. 테스트 환경 구성 — 폐쇄망 재현

> 목적: 13장 시험(기능 · 성능 · 영향도 · 기한 삭제)을 **폐쇄망**에서 그대로 다시 돌릴 수 있게 반입물 · 설정 · 순서를 정리한다.
> 실행 담당이 사람이든 에이전트든 같은 절차를 쓴다. 에이전트 지시서는 [03-agent-runbook.md](./03-agent-runbook.md).
> 스크립트: [`13-ilm-hot-only-test/scripts/`](../13-ilm-hot-only-test/scripts/) — 이 디렉터리 전체를 반입한다.

## 1. 두 가지 구성

| 모드 | S3 | HMS | 언제 |
|---|---|---|---|
| **A. 운영 AIStor** (권장) | 실제 Hot · Warm AIStor 의 **시험 전용 버킷** | 시험용 HMS(테스트베드) 또는 운영 HMS 의 시험 DB | 운영 버전에서 결과를 내야 할 때 |
| B. 테스트베드 | K8s 안 MinIO hot/warm 2개 (`testbed/`) | 테스트베드 HMS (PostgreSQL 16 + Hive 3.1.3) | AIStor 를 쓸 수 없을 때 · 스크립트 사전 점검 |

두 모드 모두 시험 Job · 수집기는 K8s 네임스페이스 하나(`ilm-test`)에 뜬다.

```
작업 PC (kubectl · 이 저장소)
  └─ ns ilm-test
       ├─ toolbox (mc · python3)          설정 · 상태 조회 · mtime 소급
       ├─ Spark Job (apache/spark)        적재 · 검증 · 측정 · 스키마 확인
       ├─ fluent-bit-audit · ilmtest-trace 증적 수집
       ├─ [B] minio-hot · minio-warm · postgres · hive-metastore
       └─ PVC ilmtest-shared (RWX)        /shared/bin(mc) · /shared/jars · /shared/evidence
```

## 2. 반입 목록

### 2-1. 컨테이너 이미지 (사내 레지스트리로 미러)

| 이미지 | 용도 | 모드 |
|---|---|---|
| `apache/spark:3.5.3-python3` | Spark Job 전부 | A · B |
| `python:3.12-slim` | toolbox · state · exp-status CronJob | A · B |
| `debian:12-slim` | trace 수집기 · [B] MinIO 실행 셸 | A · B |
| `fluent/fluent-bit:4.0.3` | audit 수신 | A · B |
| `curlimages/curl:8.10.1` | jar 내려받기 Job (`MAVEN_REPO` 사용 시) | A · B |
| `minio/minio:RELEASE.2024-10-13T13-34-11Z` (또는 AIStor `mc` 포함 이미지) | `mc` · `minio` 바이너리를 공유 볼륨에 복사 | A(`mc` 만) · B |
| `postgres:16` · `apache/hive:3.1.3` | 테스트베드 HMS | B (A 에서 시험용 HMS 를 띄울 때도) |

```bash
# 미러 예시 (반입 PC → 사내 레지스트리)
for i in apache/spark:3.5.3-python3 python:3.12-slim debian:12-slim fluent/fluent-bit:4.0.3 \
         curlimages/curl:8.10.1 postgres:16 apache/hive:3.1.3 minio/minio:RELEASE.2024-10-13T13-34-11Z; do
  skopeo copy docker://docker.io/$i docker://registry.local/mirror/$i     # 또는 docker save/load
done
```

> ⚠️ MinIO 커뮤니티 이미지 · 바이너리 배포가 중단됐다 (`quay.io` 401, `dl.min.io` 410 — 2026-10 확인). 반입 PC 캐시에서 가져오거나 AIStor 가 제공하는 `mc` 를 쓴다.

### 2-2. Jar · 바이너리

| 파일 | 위치 | 비고 |
|---|---|---|
| `iceberg-spark-runtime-3.5_2.12-1.9.0.jar` | `/shared/jars/` | Maven Central → 사내 Nexus (`MAVEN_REPO`) 또는 직접 복사 |
| `iceberg-aws-bundle-1.9.0.jar` | `/shared/jars/` | 같음 |
| `mc` (AIStor 버전 권장) · [B] `minio` | `/shared/bin/` | `ilmtest-bootstrap-bins` Job 이 이미지에서 복사 |

Python 패키지는 필요 없다 — 모든 스크립트가 표준 라이브러리만 쓴다 (`s3_backdate.py` 의 SigV4 서명 포함).

### 2-3. 클러스터 요구 사항

| 항목 | 값 |
|---|---|
| StorageClass | RWX 1개 (`ilmtest-shared` 10 Gi) · [B] RWO 2개 이상 (MinIO 20 Gi × 2 · PostgreSQL) |
| 자원 | 상주 약 1.5 Gi (B) · Spark Job 1개당 요청 1~2 CPU · 4 Gi (동시 최대 2~3개) |
| 네트워크 | ns → Hot S3 · HMS. **Warm 은 Hot(tier) 만** — 시험 Pod 에서 Warm 으로는 toolbox 관리 조회만 |
| 권한 | ns 생성 · Job/CronJob/Deployment · Secret · `kubectl top`(metrics-server) |

## 3. 폐쇄망 치환 (`lib.sh`)

매니페스트는 corp 기준으로 쓰여 있고, 배포 스크립트가 아래 변수로 바꿔 적용한다.

| 변수 | 바뀌는 것 |
|---|---|
| `IMAGE_REGISTRY=registry.local/mirror` | 모든 `image:` 앞에 붙임 (`quay.io/` · `docker.io/` 는 뗌). corp 전용 `nodeName` · `imagePullPolicy: Never` 제거 |
| `MAVEN_REPO=https://nexus.local/repository/maven-public` | jar 내려받기 주소 |
| `RWX_SC=<rwx-class>` · `RWO_SC=<rwo-class>` | `juicefs` · `csi-cinder-sc-delete` 대체 |

```bash
cd 13-ilm-hot-only-test/scripts && source lib.sh
IMAGE_REGISTRY=registry.local/mirror RWX_SC=nfs-rwx render testbed/00-shared.yaml | less   # 적용 전 확인
```

## 4. 구성 순서

### 4-1. 공통

```bash
cd 13-ilm-hot-only-test/scripts
export IMAGE_REGISTRY=registry.local/mirror MAVEN_REPO=https://nexus.local/repository/maven-public RWX_SC=<rwx> RWO_SC=<rwo>
source lib.sh
kubectl create ns ilm-test
kapply ilm-test testbed/00-shared.yaml                 # PVC + mc/minio 복사 + Iceberg jar
wait_job ilm-test ilmtest-bootstrap-bins 600 && wait_job ilm-test ilmtest-bootstrap-jars 600
```

### 4-2. 모드 B — 테스트베드

```bash
NS=ilm-test testbed/setup.sh          # Secret(무작위, 출력 안 함) · MinIO · 사용자/버킷/tier · HMS 스키마
source testbed/config.corp.env        # 엔드포인트가 ns 안 서비스 이름이라 그대로 쓴다
```

### 4-3. 모드 A — 운영 AIStor

1. AIStor 관리자가 [01장](./01-s3-bucket-setup.md) §2~§3 으로 **시험 전용** Hot 버킷 · Warm tier 버킷 · 서비스/tier 계정 · tier 를 만든다.
   (Warm `--prefix` 로 시험 tier 를 분리하면 Warm 쪽 객체 수를 정확히 셀 수 있다.)
2. Secret 을 만든다 (값은 담당자가 직접 입력, 저장소 · 로그에 남기지 않는다).

```bash
kubectl -n ilm-test create secret generic ilmtest-s3 \
  --from-literal=HOT_ENDPOINT=https://hot-s3.example.internal \
  --from-literal=AWS_ACCESS_KEY_ID=<svc> --from-literal=AWS_SECRET_ACCESS_KEY=<svc-secret> \
  --from-literal=MC_HOST_HOT='https://<admin>:<admin-secret>@hot-s3.example.internal'
kubectl -n ilm-test create secret generic ilmtest-admin \
  --from-literal=MC_HOST_HOT='https://<admin>:<admin-secret>@hot-s3.example.internal' \
  --from-literal=MC_HOST_WARM='https://<admin>:<admin-secret>@warm-s3.example.internal'
kubectl -n ilm-test create secret generic ilmtest-tier --from-literal=access_key=<tier> --from-literal=secret_key=<tier-secret>
```

3. HMS: 시험용 HMS 를 띄우려면 `testbed/20-metastore.yaml` 과 `setup.sh` §4 만 실행하고 `hive-site.xml` 의 `fs.s3a.endpoint` 를 Hot 으로. 운영 HMS 를 쓰면 **시험 DB 이름**(`ilmtest` · `ilmperf` · `ilmexp*`)이 운영과 겹치지 않는지 확인.
4. `cp config.env.example config.env` → 엔드포인트 · `HMS_URI` · `K8S_NS` · `TIER_NAME` · `HOT_METRICS_URLS` 수정 → `source config.env`.
5. toolbox 는 `kapply ilm-test testbed/30-toolbox.yaml` 로 띄운다 (Secret `ilmtest-admin` 사용).

### 4-4. 시험 Job · 수집기

```bash
source config.env            # 또는 testbed/config.corp.env
RUN_ID=smoke-$(date +%Y%m%d) DB=ilmsmoke TRANSITION_DAYS=0 SCANNER_GRACE_HOURS=0 CRON_SUSPEND=1 ./02-deploy.sh
```

`02-deploy.sh` 는 ConfigMap(`ilmtest-config` · `ilmtest-jobs` · `ilmtest-fluent-bit`) · CronJob · trace · audit 수신기를 만든다.
**audit 수신기가 MinIO/AIStor 보다 먼저 떠 있어야** 감사 로그가 남는다 (수신기가 없으면 버린다). AIStor audit 설정은 `01-setup-audit.sh`.

## 5. 시험 실행 순서 · 소요

| 순서 | 시험 | 명령 | 소요 |
|---|---|---|---|
| 1 | 0d 스모크 (①) | README §8 "0d 스모크" | 15분 |
| 2 | 성능 · 영향도 (② ③) | `perf/run-perf-impact.sh` | 기본 규모 약 1시간 (백로그 5분 + 기준선 15분 + 전이 + 전이 후 15분) |
| 3 | 기한 삭제 (E) | `perf/run-expiry.sh` | 5분 + 실시간 확인점 1~2일 |
| 4 | 1d 연속 (①) | README §8 "1d 연속" | 3~4일 |

각 시험은 다른 DB(prefix)를 쓰므로 같은 버킷에서 겹쳐 돌려도 된다. 단 성능 시험 중의 지연 수치에는 다른 시험 부하가 섞인다 — 성능 시험은 가능하면 단독으로.

## 6. 정리

```bash
kubectl delete ns ilm-test                       # Job · PVC(Delete 정책이면 볼륨까지)
# 모드 A: 시험 버킷 · 규칙 · tier 정리 (AIStor 관리자)
mc ilm rule export HOT/<시험버킷> > final-rules.json && mc rb --force HOT/<시험버킷>
mc ilm tier rm HOT WARM-EXP WARM-EXPI            # 시험 전용 tier 를 만들었다면 (객체가 남아 있으면 거부됨)
mc admin config set HOT scanner speed=default    # 바꿨다면
```
