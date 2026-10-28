# 13. Hot→Warm ILM × Iceberg 연동 테스트 (Hot 단일 접근)

> 대상: Hot S3 → Warm S3 **ILM Transition 만** 적용 (Replication 미사용)
> 전제: 모든 Iceberg 입출력은 **Hot 엔드포인트로만** 수행, Warm 은 tier 저장소로만 사용
> 관련: [04 ILM 정책 설계](../04-ilm-policy-design/) · [08 테스트 시나리오 T-05~T-09](../08-test-scenarios/) · [09 운영/진단](../09-operations/)
> 스크립트: [`scripts/`](./scripts/) (초안 — 🔍 표시는 사용 버전에서 확인 필요)

---

## 1. 목적

Hot → Warm ILM Transition 정책이 걸린 상태에서

1. Iceberg 읽기·쓰기를 **Hot 엔드포인트만으로** 해도 정합성·가용성 문제가 없는지
2. 정책이 **의도대로**(`data/` 만 전이, `metadata/` 제외, 기한 내 전이) 적용되는지

를 **연속 적재 부하** 아래에서 확인하고, 그 결과를 **메트릭·로그 증적**으로 남긴다.

### 검증 항목 구성

| 구분 | 확인 내용 | 시험 | 판정 항목 |
|---|---|---|---|
| ① 기능 검증 | ILM 적용 · 전이 · 전이 객체 조회 · 접근 통제 | 0d 스모크 · 1d 연속 (§4~§8) | J-1 ~ J-8 |
| ② 성능 · 부하 | **데이터가 이미 있는 버킷**에 규칙을 걸 때 전이 소요 · 처리율, 전이 중/후 Iceberg 쓰기 · 읽기 지연, Hot 자원 | 백로그 전이 시험 (§11) | P-1 ~ P-4 |
| ③ 영향도 | 규칙 적용 · 전이 후에도 **스키마 · 테이블 정의 변경 없이** Iceberg · HMS · Spark 가 그대로 동작 | 전/후 정의 비교 + 전이 후 스키마 변경 (§11) | I-1 ~ I-5 |
| 기한 삭제 | Hot 1일 → Warm → 보존 기한(예: 5일) 지난 데이터가 Warm 에서 지워지는지, Iceberg 가 깨지지 않는지 — **기다리지 않고** 검증 | mtime 소급 + 실시간 확인점 (§12) | E-0 ~ E-5 |

운영 구성 · 폐쇄망 재현 · 개발자 안내는 [14장](../14-ilm-config-guide/) 에 정리했다.

## 2. 구성

| 구성요소 | 내용 |
|---|---|
| Hot S3 | `warehouse` 버킷(Iceberg 테이블). ILM 규칙 · tier `WARM-TIER` 를 등록한다 |
| Warm S3 | tier 전용 버킷. **ILM 규칙 없음**, Hot 의 tier 계정만 접근 |
| 클라이언트 | Spark(K8s CronJob) → Hot 엔드포인트 + HMS 만. Warm 접근은 네트워크·자격증명으로 차단 |
| 카탈로그 | Hive Metastore |
| 수집 | 로그: Fluent Bit → OpenSearch/Loki · 메트릭: vmagent → VictoriaMetrics → Grafana |

```
 Writer(10분) ─┐                         ┌─ audit webhook ──► Fluent Bit ──► OpenSearch/Loki
 Verifier(30분)┼─► Hot S3 (warehouse) ───┤
 State(1시간) ─┘      │  ILM Transition   └─ /minio/v2/metrics ──► vmagent ──► VictoriaMetrics ──► Grafana
                      ▼
               Warm S3 (tier 버킷) ── audit webhook ──► Fluent Bit   (접근 계정 = tier 계정만 ✅)
```

## 3. ILM 규칙 (테스트용)

| ID | prefix | 동작 | 값 |
|---|---|---|---|
| R-1 | `<db>/<tbl>/data/` | Transition → `WARM-TIER` | 1d (사전 확인 시 0d 1회) |
| R-2 | `<db>/<tbl>/metadata/` | **규칙 없음** (전이 제외) | — |
| R-3 | `<db>/<tbl>/data/` | Noncurrent expire (Versioning ON 일 때만) | 최소 1d |
| R-6 | `<db>/<tbl>/` | 고아 delete marker 정리 (Versioning ON 일 때만) | — |
| ✗ | — | current Expiration · warm tier 버킷 규칙 | **금지** |

적용·검증: [`scripts/00-apply-ilm.sh`](./scripts/00-apply-ilm.sh) — 기존 규칙 백업 → JSON import → 위험 규칙 검사.

## 4. 부하와 검증 Job

| Job | 주기 | 내용 | 로그 이벤트 |
|---|---|---|---|
| Writer | 10분 | 시간 파티션 테이블에 append(배치당 N 행) + ledger 에 행 수·checksum·snapshot 기록 | `ilmtest.write` |
| Verifier | 30분 | 배치별 count·checksum ↔ ledger 대조, **가장 오래된 스냅샷 time travel** 조회, 읽기 지연 측정 | `ilmtest.verify` |
| State snapshot | 1시간 | prefix 별 `storageClass` 분포 · 기한 초과 미전이 · ILM 규칙 · tier 상태 | `ilmtest.state` |
| ILM trace | 상시 | `mc admin trace --call ilm,scanner` 🔍 | `ilmtest.trace` |
| 유지보수 | D2 이후 1회 | 전이된 파일 대상 `rewrite_data_files` → `expire_snapshots` | `ilmtest.maintenance` |

모든 Job 은 **한 줄 JSON** 을 stdout 으로 내보내고 Fluent Bit 이 Pod 로그로 수집한다 (`event` 필드로 구분).

## 5. 모니터링 · 증적

| 구분 | 대상 | 수단 |
|---|---|---|
| 전이 진행 | `minio_cluster_ilm_transitioned_{objects,bytes}` · `minio_node_ilm_transition_{pending,active}_tasks` · `minio_node_ilm_transition_missed_immediate_tasks` 🔍 | vmagent ([`scripts/monitoring/vmagent-scrape.yml`](./scripts/monitoring/vmagent-scrape.yml)) |
| Scanner | `minio_node_scanner_*` · `mc admin scanner status` 🔍 | 메트릭 + State snapshot |
| 용량 | Hot · Warm 버킷 사용량 추이 | 메트릭 |
| ILM 이벤트 | `mc admin trace --call ilm,scanner --json` 🔍 | [`scripts/k8s/trace-collector.yaml`](./scripts/k8s/collectors.yaml) |
| 접근 통제 | Hot · Warm **audit log** | `audit_webhook` → Fluent Bit ([`scripts/fluent-bit/`](./scripts/fluent-bit/)) |
| 애플리케이션 | Writer · Verifier · State | Pod 로그 → Fluent Bit |

주요 PromQL 은 [`scripts/monitoring/queries.md`](./scripts/monitoring/queries.md) 참고.

## 6. 판정 기준

| # | 항목 | 통과 기준 | 증적 |
|---|---|---|---|
| J-1 | data 전이 | 기한(Transition 일수 + Scanner 1사이클) 경과 `data/` current 객체 **100% WARM-TIER** (`overdue=0`) | `ilmtest.state` |
| J-2 | metadata 제외 | `metadata/` 전이 객체 **0건** | `ilmtest.state` |
| J-3 | 정합성 | Verifier count·checksum **매 주기 100% 일치** | `ilmtest.verify` |
| J-4 | 전이 객체 조회 | 전이 파일이 포함된 과거 스냅샷 · 파티션 조회 성공 (Hot 엔드포인트만) | `ilmtest.verify` |
| J-5 | 쓰기 영향 없음 | Writer 실패 0, 커밋 지연 유의미한 변화 없음 | `ilmtest.write` |
| J-6 | 유지보수 | 전이 파일 대상 compaction · expire 성공 | `ilmtest.maintenance` |
| J-7 | 접근 통제 | Warm audit log 에 tier 계정 외 accessKey **0건** | audit log |
| J-8 | 오류 | ILM 전이 실패 0, trace 에러 0 | 메트릭 · `ilmtest.trace` |
| 참고 | 성능 | 전이 전/후 읽기 지연 비교 (기록만) | `ilmtest.verify` |

J-1 ~ J-5 는 [`scripts/judge.py`](./scripts/judge.py) 가 수집 로그(JSONL)에서 자동 판정한다.

## 7. 일정 (약 4일)

| 시점 | 작업 | 확인 |
|---|---|---|
| D0 | 구성 · 규칙 적용 · 베이스라인 · Writer/Verifier/State 시작 (선택: 0d 규칙으로 사전 확인 후 1d 로 교체) | 규칙 검사 통과, 첫 `ilmtest.write` |
| D1~D2 | 연속 적재, 첫 전이 | J-1 · J-2 · J-3 ~ J-5 |
| D2~D3 | 유지보수 실행, noncurrent 만료 | J-6 · R-3 |
| D3 | 증적 수집 · 판정표 작성 (선택: Warm 중단 시 영향 범위 — [08 T-20](../08-test-scenarios/)) | J-7 · J-8 · 결과 기록 |

## 8. 실행 순서

```bash
cd scripts
cp config.env.example config.env && vi config.env       # 엔드포인트·버킷·테이블·주기
source config.env

./00-apply-ilm.sh --dry-run                             # 1) 규칙 미리보기
./00-apply-ilm.sh                                       #    백업 → 적용 → 위험 규칙 검사

# 2) Secret (자격증명은 여기에만)
kubectl create ns "$K8S_NS"
kubectl -n "$K8S_NS" create secret generic ilmtest-s3 \
  --from-literal=HOT_ENDPOINT="$HOT_ENDPOINT" \
  --from-literal=AWS_ACCESS_KEY_ID=... --from-literal=AWS_SECRET_ACCESS_KEY=... \
  --from-literal=MC_HOST_HOT="https://<ak>:<sk>@${HOT_ENDPOINT#*://}"
kubectl -n "$K8S_NS" create secret generic ilmtest-os \
  --from-literal=OS_HOST=... --from-literal=OS_PORT=9200 --from-literal=OS_USER=... --from-literal=OS_PASSWORD=...

./02-deploy.sh                                          # 3) ConfigMap · CronJob · trace · audit 수신기
./01-setup-audit.sh                                     # 4) Hot/Warm audit webhook → 수신기
#    + fluent-bit/app-tail-snippet.yaml 을 기존 Fluent Bit DaemonSet 에 병합
#    + monitoring/vmagent-scrape.yml 을 vmagent 에 추가

# 5) D2 이후 유지보수 1회
kubectl -n "$K8S_NS" create job --from=cronjob/ilmtest-maintenance ilmtest-maint-$(date +%H%M)

# 6) 종료 후 증적 수집 · 판정
OS_URL=https://<opensearch>:9200 OS_AUTH=user:pass ./collect-evidence.sh evidence/$(date +%Y%m%d)
python3 judge.py evidence/$(date +%Y%m%d)
```

### 테스트베드로 실행 (corp 클러스터 실측 절차)

실제 AIStor 가 없을 때 K8s 안에 MinIO hot/warm 두 배포 + HMS 를 띄워 같은 흐름을 돌린다.
결과: [`results/REPORT-smoke-20261025.md`](./results/REPORT-smoke-20261025.md)

```bash
cd scripts
kubectl create ns ilm-test
source lib.sh && kapply ilm-test testbed/00-shared.yaml  # RWX 볼륨 + minio/mc 바이너리 + Iceberg jar (폐쇄망: IMAGE_REGISTRY · MAVEN_REPO · RWX_SC/RWO_SC)
NS=ilm-test testbed/setup.sh                              # Secret · MinIO · 사용자/버킷/tier · HMS

# 0d 스모크 (CronJob 정지 + 수동 실행) — 수신기(fluent-bit-audit)가 MinIO 보다 먼저 떠 있어야 audit 가 남는다
export RUN_ID=smoke DB=ilmsmoke TRANSITION_DAYS=0 SCANNER_GRACE_HOURS=0
source testbed/config.corp.env && CRON_SUSPEND=1 ./02-deploy.sh
#   toolbox 안에서: mkdir -m 1777 /shared/evidence/$RUN_ID && ./00-apply-ilm.sh
kubectl -n ilm-test create job --from=cronjob/ilmtest-writer smoke-w1    # 배치 수만큼 반복
kubectl -n ilm-test create job --from=cronjob/ilmtest-state smoke-s1
kubectl -n ilm-test create job --from=cronjob/ilmtest-verifier smoke-v1
kubectl -n ilm-test create job --from=cronjob/ilmtest-maintenance smoke-m1

# 1d 연속
export RUN_ID=run-1d-$(date +%Y%m%d) DB=ilmtest TRANSITION_DAYS=1 SCANNER_GRACE_HOURS=24
#   toolbox 안에서 증적 디렉터리 생성 + 00-apply-ilm.sh 재실행 (규칙 교체)
source testbed/config.corp.env && CRON_SUSPEND=0 ./02-deploy.sh
kubectl -n ilm-test patch cronjob ilmtest-maintenance --type merge -p '{"spec":{"schedule":"0 21 <D2> <월> *","suspend":false}}'

# 판정 · 정리
kubectl -n ilm-test exec deploy/ilmtest-toolbox -- python3 /tmp/s/judge.py /shared/evidence/$RUN_ID
kubectl delete ns ilm-test
```

### 스크립트 구성

| 파일 | 역할 |
|---|---|
| `config.env.example` | 공통 설정 템플릿 (자격증명 없음) |
| `00-apply-ilm.sh` | ILM 규칙 백업 · 생성(R-1/R-3/R-6) · 적용 · 위험 규칙 / Warm tier 버킷 규칙 검사 |
| `01-setup-audit.sh` | Hot/Warm `audit_webhook` → Fluent Bit |
| `02-deploy.sh` | ns · ConfigMap · `k8s/` 배포 |
| `spark/writer.py` · `verifier.py` · `maintenance.py` | 부하 · 정합성 검증 · 유지보수 (`common.py`, `run-spark.sh` 공유) |
| `state_snapshot.py` | prefix 별 storageClass · overdue · 규칙 해시 → `ilmtest.state` |
| `k8s/cronjobs.yaml` · `k8s/collectors.yaml` | CronJob 4종 · trace 수집기 · audit 수신기 |
| `fluent-bit/audit-receiver.yaml` · `app-tail-snippet.yaml` | audit 수신(+ J-7 경보) · Pod 로그 수집 |
| `monitoring/vmagent-scrape.yml` · `queries.md` | 메트릭 수집 · 판정용 쿼리 |
| `collect-evidence.sh` · `judge.py` | 증적 수집 · J-1~J-6 자동 판정 |
| `lib.sh` | `render`/`kapply`(폐쇄망 이미지 · jar · StorageClass 치환) · `wait_job` · `sync_jobs` |
| `perf/run-perf-impact.sh` | ② ③ 시험 일괄 실행 — 백로그 → 기준선 → 규칙 병합 → 전이 → 전이 후 → 스키마 변경 → 보고서 |
| `perf/run-expiry.sh` | 기한 삭제 시험 일괄 실행 — mtime 소급 확인 → 객체(E-1/2) → Iceberg(E-3/4) → 실시간 추적 CronJob |
| `spark/perf_backlog.py` · `perf_probe.py` · `schema_check.py` · `exp_iceberg.py` | 백로그 적재 · 지연 측정 · 정의 기록/스키마 변경 · 기한 삭제 Iceberg 시험 |
| `perf/perf_sampler.py` · `hms_snapshot.sh` · `perf-job.sh` | 전이 진행 · Hot 메트릭 샘플 · HMS 정의 기록 · Spark Job 1회 실행 |
| `perf/s3_backdate.py` · `exp-object-test.sh` · `exp-status-cronjob.yaml` | 객체 mtime 소급(SigV4, 표준 라이브러리) · 객체 단위 만료 시험 · 확인점 추적 |
| `perf/perf_report.py` · `exp_report.py` | 결과 Markdown 생성 |
| `spark/tag_tiering.py` | 태그 기반 즉시 전이(T-1) · soft delete(T-2) 시험 — 별도 카탈로그에 `s3.write.tags.*` / `s3.delete-enabled=false` ([15장](../15-aistor-engineer-briefing/)) |

## 9. 주의사항

| # | 주의 | 대응 |
|---|---|---|
| 1 | `mc ls` 크기는 **논리 크기** — 전이 후에도 그대로 | 전이 여부는 `storageClass` 로만 판단 |
| 2 | Scanner 가 느리면 기한이 지나도 전이 지연 | "안 돈다" 판단 전 Scanner 사이클 확인 ([09](../09-operations/)) — J-1 기한에 1사이클 포함 |
| 3 | 스크레이프 라벨 `tier` 가 MinIO 라벨과 충돌 → 대시보드 에러 없이 0 | 배포 구분 라벨은 `deployment` |
| 4 | `--noncurrent-expire-days` 최소 1일 (0 거부) | R-3 은 1 이상 |
| 5 | Warm tier 버킷에 ILM 규칙 → hot 에는 stub 만 남고 실데이터 소실 | `00-apply-ilm.sh` 가 검사 |
| 6 | `mc ls --versions --json` 에 `isLatest` 없음 | 최신 판정은 키별 `versionOrdinal` 최댓값 |
| 7 | 테스트 중 Scanner 가속 시 사용자 I/O 영향 | 종료 후 반드시 원복 ([04 §6](../04-ilm-policy-design/)) |
| 8 | ★ Fluent Bit http input 은 URI 태그의 `-` 를 `_` 로 바꾼다 (`/minio-hot` → `minio_hot`) | match 를 `minio_hot` 로. `minio-hot` 이면 에러 없이 0건 |
| 9 | MinIO audit `queue_dir` 사용 시 묶음 전송 → Fluent Bit `invalid JSON message` | `queue_dir` 미사용, 수신기를 MinIO 보다 먼저 기동 |
| 10 | 0d 규칙은 PUT 직후 전이(Scanner 무관), 1d 규칙은 Scanner 방문 시 전이 | 스모크 결과로 1d 동작을 추정하지 말 것 |
| 11 | 지운 전이 파일은 비현행(WARM-TIER) 버전으로 Warm 에 남는다 | R-3(noncurrent 만료) 없으면 Warm 용량이 회수되지 않음 |
| 12 | 클러스터 ILM 메트릭(`minio_cluster_ilm_transitioned_*`)은 Scanner 기준이라 늦다 | 즉시값은 `minio_node_ilm_action_count_transition_action` |
| 13 | MinIO 커뮤니티 이미지·바이너리 배포 중단(quay 401 · dl.min.io 410) | 테스트베드는 캐시 이미지에서 추출 ([`testbed/00-shared.yaml`](./scripts/testbed/00-shared.yaml)) |
| 14 | ★ `mc ilm rule import` 는 버킷 규칙 **전체 교체** | `00-apply-ilm.sh` `MERGE=1` + `RULE_ID_PREFIX` (테이블별 규칙 공존) |
| 15 | ★ ILM 시각 = `mtime + Days` → **다음 00:00 UTC 로 올림** (전이 · 만료 · 비현행 모두) | 1d 규칙도 최대 2일. `mc stat` 의 `Expiration` 으로 예정 시각 확인. 1d 연속의 첫 전이는 10-27 00:00 UTC 이후 |
| 16 | mtime 소급 PUT 은 버전 순서도 mtime 기준 — 기존 키에 과거 mtime 으로 쓰면 '이전 버전'이 된다 | `s3_backdate.py rewrite` 가 원본 버전을 지운다 (시험 데이터 전용) |
| 17 | ★ Versioning ON 에서 **전이된 current 버전이 ILM 만료**되면 Warm 원본은 즉시 삭제, 비현행 기록만 남고 GET 은 NoSuchKey (MinIO 2024-10) | 버전 복구 불가 — 운영 버전에서 E-1 로 재확인 |
| 18 | 만료일이 이미 지난 객체는 PUT 즉시 처리 (Scanner 무관) | 소급 시험이 빠른 이유. 0d 전이와 같은 경로 |
| 19 | toolbox 512 Mi 에서 `mc pipe` OOMKilled | toolbox 1 Gi · 업로드는 `s3_backdate.py put … 0` |
| 20 | `02-deploy.sh` 재실행 시 maintenance CronJob 스케줄 초기화 · 설정 ConfigMap 덮어씀 | 스크립트만 바꿀 때는 `sync_jobs <ns>` |

## 10. 결과 기록표

| # | 0d 스모크 (2026-10-25) | 1d 연속 (`run-1d-20261025`) | 증적 위치 | 비고 |
|---|---|---|---|---|
| J-1 | ✅ 전이율 1.0 · overdue 0 | ✅ 첫 전이 10-27 00:15 UTC (00:00 올림 확인) · 전이율 0.53 · overdue 0 | `ilmtest.state.jsonl` | |
| J-2 | ✅ metadata 전이 0 | ✅ metadata 전이 0 | `ilmtest.state.jsonl` | |
| J-3 | ✅ 4/4 일치 | ✅ 103/103 일치 | `ilmtest.verify.jsonl` | |
| J-4 | ✅ old_read 4 · time travel 실패 0 | ✅ old_read 7 · time travel 실패 0 · 읽기 p50 417 → 642 ms | `ilmtest.verify.jsonl` | |
| J-5 | ✅ 실패 0 · p50 2457 → 2345 ms | ✅ 311회 실패 0 · p50 2505 → 2541 ms | `ilmtest.write.jsonl` | |
| J-6 | ✅ | ✅ 유지보수 3 이벤트 · 실패 0 (10-27 21:00 UTC) | `ilmtest.maintenance.jsonl` | |
| J-7 | ✅ Warm 접근 = `tier-svc` 뿐 | ✅ `tier-svc` 95,667건 · 그 외 `warmadmin` 274건 = 시험 도구(기한 삭제 추적 CronJob · 수동 조회)만, 서비스 계정 0 | `audit-minio-warm.jsonl` · `alert-warm-access.jsonl` | |
| J-8 | ✅ missed 0 · trace 에러 0 | ✅ missed(전이 · 만료 · tier journal) 0 · trace 680만 줄 중 에러 0 | `trace.jsonl` · state metrics | |

상세: [`results/REPORT-smoke-20261025.md`](./results/REPORT-smoke-20261025.md)

| # | 시험 (2026-10-26) | 결과 | 상세 |
|---|---|---|---|
| P-1 | 기존 4,000 객체에 0d 규칙 병합 적용 | ✅ 914초 (4.5개/s, Scanner 기본) · `fastest` 25초 · 실패 0 | [perf-impact](./results/REPORT-perf-impact-20261026.md) |
| P-2 | 전이 중 지연 | ✅ 쓰기 p50 482 → 488 ms · 파티션 읽기 +22% · 전체 스캔 +29% · 오류 0 | 같음 |
| P-3 | 전이 후 지연 | ✅ 파티션 읽기 +26% · 전체 스캔 +40% · 정합성 일치 | 같음 |
| P-4 | 자원 | ✅ 기본 속도 Hot CPU +11% · ⚠️ `fastest` 유휴 Hot 82m 상시 · Warm 피크 380m/990 Mi | 같음 |
| I-1~I-5 | HMS · Iceberg 정의 · 파일 경로 · 스키마 변경 · Spark 설정 | ✅ 3시점 동일 · ADD/DROP COLUMN 정상 | 같음 |
| E-0~E-4 | 기한 삭제 (mtime 소급) | ✅ 객체 만료 · Warm 삭제 · Iceberg 보존 작업 정상 / ❌(의도) ILM 만료가 Iceberg 를 깸 / ⚠️ F-1 | [expiry](./results/REPORT-expiry-20261026.md) |
| E-5 | 실시간 확인점 | ✅ 10-27 00:00: age-4.5 만료 · age-0.5 전이 / 10-28 00:00: Iceberg 가 지운 파일의 비현행 Warm 버전 · DM 소멸 | 같음 |

## 11. 성능 · 부하(②) · 영향도(③) 시험

**데이터가 이미 있는 버킷**에 규칙을 걸 때를 재현한다 — 규칙 없이 테이블을 채운 뒤(백로그) 규칙을 **병합** 적용하고,
Scanner 가 기존 객체를 전이하는 동안과 그 뒤의 Iceberg 쓰기 · 읽기 지연, Hot/Warm 자원, 테이블 정의 변화를 기록한다.

| 단계 | 내용 | 산출 |
|---|---|---|
| 백로그 | `perf_backlog.py` — 과거 시간 파티션 40개 × 파일 100개 (규칙 없음) | `ilmtest.backlog` |
| 전 정의 | `hms_snapshot.sh` (HMS DB) · `schema_check.py` (스키마 · 파티션 · 속성 · 위치 · 고정 스냅샷 파일 경로 해시) | `ilmtest.hms` · `ilmtest.schema` |
| 기준선 | `perf_probe.py` 15분 — 1분마다 쓰기 · 고정 파티션 읽기 · 메타데이터 조회 · 5회마다 전체 스캔 + ledger 대조 | `ilmtest.probe` (phase=baseline) |
| 규칙 적용 | `00-apply-ilm.sh MERGE=1 RULE_ID_PREFIX=<db>-` (Transition 0d — 기존 객체 전부 대상) | `ilmtest.perfphase` |
| 전이 | 프로브 계속 + `perf_sampler.py` 15초 (storageClass 분포 · ILM/Scanner/tier 메트릭 · CPU) | phase=transition · `ilmtest.perfsample` |
| 전이 후 | 정의 재기록 → 프로브 15분 → 스키마 변경(ADD → 옛 파일 null → 새 컬럼 쓰기 → DROP) | phase=post · `evolve` |

```bash
source testbed/config.corp.env      # 또는 config.env
RUN_ID=perf-$(date +%Y%m%d) PERF_DB=ilmperf perf/run-perf-impact.sh        # 약 1시간
RUN_ID=perf-fast-$(date +%Y%m%d) PERF_DB=ilmperf2 SCANNER_SPEED=fastest perf/run-perf-impact.sh   # 가속 비교 (끝나면 자동 원복)
```

## 12. 기한 삭제 시험 — Hot 1일 → Warm → 삭제를 기다리지 않고 확인

5일을 기다리는 대신 **객체 mtime 을 과거로 써서**(MinIO 사이트 복제 내부 헤더 `X-Minio-Source-Mtime`, 관리자 키) 일수 경과를 만든다.
delete marker 의 나이처럼 소급할 수 없는 부분은 **실시간 확인점**(`mc stat` 의 예정 시각)을 CronJob 이 매시 기록한다.

| # | 시험 | 기대 |
|---|---|---|
| E-0 | 소급 가능 여부 | 6일 전으로 PUT → 나이 6일. 안 되면 실시간 일정으로 ([14장 runbook §6](../14-ilm-config-guide/03-agent-runbook.md)) |
| E-1 | 객체 · Versioning ON, 나이 0.5/2/4.5/6일 + 비현행 | Hot 유지 / Warm / Warm / 만료(delete marker) · 비현행 만료 |
| E-2 | 객체 · Versioning OFF | 6일 객체 즉시 영구 삭제 + Warm 원본 삭제 |
| E-3 | Iceberg + ILM current Expiration (금지 규칙) | 테이블 조회 실패 — 금지 근거 |
| E-4 | Iceberg 보존 작업(DELETE + expire_snapshots) + ILM 비현행 만료 (권장) | 테이블 정상 · 지운 파일은 비현행 Warm 버전 → 1일(→ 00:00) 뒤 삭제 |
| E-5 | 실시간 확인점 | CronJob `ilmtest-exp-status` 매시 45분 |

```bash
RUN_ID=exp-$(date +%Y%m%d) EXPIRE_DAYS=5 perf/run-expiry.sh      # 5분. 재실행은 새 이름(VB · NB · EXP_DB1 · EXP_DB2)
```

규칙은 실제 시간 흐름대로 두 단계(① Transition 만 → ② + Expiration)로 건다. 처음부터 같이 걸면 이미 만료일이 지난 객체는 전이 없이 바로 만료된다.
같은 버킷에 E-3 용 current Expiration 규칙이 남으므로, 그 뒤 다른 시험의 규칙 적용은 위험 규칙 검사에서 멈춘다 — **성능 시험을 먼저** 하거나 시험 규칙을 지운다.
