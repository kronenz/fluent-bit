# 03. 에이전트 실행 지시서 — 폐쇄망에서 ILM 시험을 다시 돌리고 결과서를 낸다

> 이 문서는 **폐쇄망의 코딩 에이전트(또는 담당자)** 가 처음부터 끝까지 따라 하도록 쓴 지시서다.
> 환경 구성은 [02-test-environment.md](./02-test-environment.md), 설정 근거는 [01-s3-bucket-setup.md](./01-s3-bucket-setup.md), 기준 결과는 [13장](../13-ilm-hot-only-test/README.md).
> 작업 디렉터리: `docs/aistor-iceberg-ilm-guide/13-ilm-hot-only-test/scripts` (이하 `scripts/`)

## 0. 임무

Hot → Warm ILM (Hot 1일 → Warm, 보존 기한 삭제) 을 Iceberg 테이블에 적용했을 때

1. **기능** — 규칙대로 전이되고, 전이된 데이터를 Hot 엔드포인트만으로 읽고 쓰는가 (J-1 ~ J-8)
2. **성능 · 부하** — 데이터가 이미 있는 버킷에 규칙을 걸 때 전이 소요 · 서비스 지연 · 자원 (P-1 ~ P-4)
3. **영향도** — Iceberg · HMS · Spark 정의 · 설정 변경 없이 동작하는가 (I-1 ~ I-5)
4. **기한 삭제** — 기한 지난 데이터가 Warm 에서 지워지는가, Iceberg 가 깨지지 않는가 (E-0 ~ E-5)

를 이 환경에서 측정하고, §7 형식의 결과서를 `13-ilm-hot-only-test/results/` 에 남긴다.

## 1. 시작 전에 사람에게 받을 것

| 항목 | 예 | 없으면 |
|---|---|---|
| kubeconfig · 네임스페이스 | `ilm-test` | 중단하고 요청 |
| 모드 | A(운영 AIStor 시험 버킷) / B(테스트베드) | B 로 진행할지 확인 |
| 사내 레지스트리 · Maven 미러 · StorageClass | `IMAGE_REGISTRY` · `MAVEN_REPO` · `RWX_SC` · `RWO_SC` | 이미지 pull 실패 시 확인 |
| (A) Hot · Warm 엔드포인트, 시험 버킷 이름, tier 이름 | `https://hot-s3…` · `warehouse-ilmtest` · `WARM-TIER` | 중단하고 요청 |
| (A) Secret 생성 완료 여부 | `ilmtest-s3` · `ilmtest-admin` · `ilmtest-tier` | 사람이 만든다 — 에이전트는 값을 받지도 쓰지도 않는다 |
| 기한 정책 | `EXPIRE_DAYS=5` (Hot 1일 + Warm 4일) | 기본값 5 로 진행하고 결과서에 명시 |

## 2. 반드시 지킬 것

1. **자격증명을 출력 · 저장하지 않는다.** Secret 값을 `echo` · 로그 · 파일 · 결과서에 남기지 않는다. 필요하면 `kubectl … | kubectl exec -i … read` 처럼 stdin 으로만 넘긴다.
2. **시험 버킷 · 시험 DB 만** 건드린다. 운영 테이블 prefix 에 규칙을 걸지 않는다. 규칙 적용은 항상 `00-apply-ilm.sh` (백업 + 위험 규칙 검사) 로 하고 `MERGE=1` 을 붙인다 — `mc ilm rule import` 는 버킷 규칙 **전체를 교체**한다.
3. `ALLOW_CURRENT_EXPIRATION=1` 은 `run-expiry.sh` 안에서만 쓴다 (금지 규칙이 테이블을 깨는지 보는 시험). 다른 곳에서 쓰지 않는다.
4. Scanner 속도를 바꿨으면 끝나기 전에 `speed=default` 로 되돌린다 (`run-perf-impact.sh` 는 trap 으로 자동 원복).
5. 실패를 숨기지 않는다. 기대와 다른 결과는 결과서 "관찰" 에 증적 파일과 함께 적는다. 수치를 고치거나 다시 돌려 좋은 값만 고르지 않는다.
6. 끝나면 정리 여부를 사람에게 묻는다 (`kubectl delete ns` 는 묻고 나서).

## 3. 사전 점검 (10분)

```bash
cd scripts
source config.env                    # 모드 B: source testbed/config.corp.env
source lib.sh
kubectl -n $K8S_NS get pods          # toolbox Running · (B) minio-hot/warm · hive-metastore Running
TB=$(kubectl -n $K8S_NS get pod -l app.kubernetes.io/name=toolbox -o jsonpath='{.items[0].metadata.name}')
kubectl -n $K8S_NS exec $TB -- bash -c 'mc ilm tier ls HOT; mc version info HOT/$BUCKET; mc admin config get HOT scanner'
kubectl -n $K8S_NS exec $TB -- ls /shared/bin /shared/jars
```

| 확인 | 통과 기준 | 실패 시 |
|---|---|---|
| tier | `$TIER_NAME` 이 목록에 있음 | 01장 §3 (사람에게 요청) |
| Versioning | `Enabled` | 01장 §3 |
| Scanner | `speed=default` | 다른 값이면 기록하고 사람에게 확인 |
| `/shared/bin/mc` · jar 2개 | 존재 | `02-test-environment.md` §4-1 |
| `kubectl top pod` | 값이 나옴 | metrics-server 없음 → P-4 는 MinIO CPU 메트릭만으로 판정 |

## 4. 실행

순서를 지킨다: **4-1 → 4-2 → 4-3 → 4-4**. 4-3 은 같은 버킷에 시험용 current Expiration 규칙을 남기므로, 그 뒤의 규칙 적용은
위험 규칙 검사에서 (적용 전에) 멈춘다. 4-4 를 4-3 뒤에 하려면 `ALLOW_CURRENT_EXPIRATION=1` 을 붙이지 말고 시험 규칙(`<EXP_DB>-r1-…`)을 먼저 지운다:
`mc ilm rule rm --id <ID> HOT/<버킷>`.

### 4-1. 기능 — 0d 스모크 (15분)

```bash
CFG=config.env                       # 모드 B: CFG=testbed/config.corp.env
export RUN_ID=smoke-$(date -u +%Y%m%d) DB=ilmsmoke TRANSITION_DAYS=0 SCANNER_GRACE_HOURS=0
source $CFG && CRON_SUSPEND=1 ./02-deploy.sh
kubectl -n $K8S_NS exec $TB -- mkdir -p /tmp/s/testbed
kubectl -n $K8S_NS exec $TB -- mkdir -m 1777 -p /shared/evidence/$RUN_ID
kubectl -n $K8S_NS cp 00-apply-ilm.sh $K8S_NS/$TB:/tmp/s/00-apply-ilm.sh
kubectl -n $K8S_NS cp $CFG $K8S_NS/$TB:/tmp/s/$CFG
apply_rules() {   # apply_rules [--dry-run] — toolbox 에서 00-apply-ilm.sh (기존 규칙 유지 · 적용 전 위험 규칙 검사)
  kubectl -n $K8S_NS exec $TB -- bash -c "cd /tmp/s && export RUN_ID=$RUN_ID DB=$DB TRANSITION_DAYS=$TRANSITION_DAYS SCANNER_GRACE_HOURS=$SCANNER_GRACE_HOURS \
    && source ./$CFG && MERGE=1 RULE_ID_PREFIX=$DB- bash 00-apply-ilm.sh $*"
}
apply_rules --dry-run && apply_rules
for i in 1 2 3; do kubectl -n $K8S_NS create job --from=cronjob/ilmtest-writer smoke-w$i; wait_job $K8S_NS smoke-w$i 900; done
kubectl -n $K8S_NS create job --from=cronjob/ilmtest-state smoke-s1;     wait_job $K8S_NS smoke-s1 600
kubectl -n $K8S_NS create job --from=cronjob/ilmtest-verifier smoke-v1;  wait_job $K8S_NS smoke-v1 900
kubectl -n $K8S_NS create job --from=cronjob/ilmtest-maintenance smoke-m1; wait_job $K8S_NS smoke-m1 1200
kubectl -n $K8S_NS create job --from=cronjob/ilmtest-state smoke-s2;     wait_job $K8S_NS smoke-s2 600
kubectl -n $K8S_NS cp judge.py $K8S_NS/$TB:/tmp/s/
kubectl -n $K8S_NS exec $TB -- python3 /tmp/s/judge.py /shared/evidence/$RUN_ID | tee ../results/$RUN_ID-judge.md
```

J-7 (Warm 접근 계정) · J-8 (전이 실패) 은 수기 확인:

```bash
kubectl -n $K8S_NS exec $TB -- bash -c "python3 - <<'PY'
import json, collections
c = collections.Counter()
for l in open('/shared/evidence/$RUN_ID/audit-minio-warm.jsonl'):
    o = json.loads(l); c[(o.get('accessKey'), o.get('api', {}).get('name'))] += 1
print(c)
PY
wc -l /shared/evidence/$RUN_ID/alert-warm-access.jsonl 2>/dev/null || echo 'alert 0'"
```

통과: J-1 ~ J-6 ✅ · Warm accessKey 가 tier 계정 하나(설정 작업 시각의 관리자 접근은 제외) · trace 에 에러 없음.

### 4-2. 성능 · 영향도 (약 1시간)

```bash
source config.env
RUN_ID=perf-$(date -u +%Y%m%d) PERF_DB=ilmperf perf/run-perf-impact.sh 2>&1 | tee ../results/perf-run.log
# 대량 백로그를 보려면: BACKLOG_COMMITS=200 BACKLOG_FILES=100 (2만 파일) — 전이 대기가 길어진다 (TRANSITION_TIMEOUT)
# Scanner 가속 비교: 같은 명령을 PERF_DB=ilmperf2 SCANNER_SPEED=fastest RUN_ID=perf-fast-… 로 한 번 더
```

산출: `results/<RUN_ID>/perf-report.md` (P-1 ~ P-4, I-1 ~ I-4 표). I-5 는 "시험 중 `scripts/spark/run-spark.sh` · `ilmtest-config` 를 바꾸지 않았다" 를 확인해 적는다.

| 판정 | 기준 |
|---|---|
| P-1 | 대상 객체 100% 전이 · `transition_missed_immediate_tasks` 증가 0 · tier 요청 실패 0. 소요 · 처리율은 기록 (백로그가 수백 개 이하면 처리율이 Scanner 대기 시간에 묻힌다 — 기본 규모 4,000개 이상으로) |
| P-2 | 전이 중 오류 0 · 정합성 전부 일치 · 쓰기 p50 변화 ±20% 이내 (기록) |
| P-3 | 오류 0 · 정합성 일치. 읽기 지연 증가율은 기록 (기준 환경: 파티션 +26% · 전체 스캔 +40%) |
| P-4 | Hot · Warm 이 OOM · 재시작 없음. CPU · 메모리 피크 기록 |
| I-1 ~ I-3 | 표의 "동일" 열 전부 ✅ |
| I-4 | `evolve.ok = true` (옛 파일 null 읽기 · 새 컬럼 쓰기 · 원복) |

### 4-3. 기한 삭제 (5분 + 실시간 1~2일)

```bash
source config.env
RUN_ID=exp-$(date -u +%Y%m%d) EXPIRE_DAYS=5 perf/run-expiry.sh 2>&1 | tee ../results/exp-run.log
```

- 종료 코드 **3** = E-0 실패 (이 S3 가 mtime 소급을 받지 않음) → §6 로 간다.
- 산출: `results/<RUN_ID>/expiry-report.md` · `expiry-schedule.txt` (만료 예정 시각).
- CronJob `ilmtest-exp-status` 가 매시 45분 상태를 남긴다. `expiry-schedule.txt` 의 가장 이른 시각 + 1일(→ 00:00 UTC) 이후에 증적을 다시 회수해 `perf/exp_report.py` 로 결과서를 갱신한다.

| 판정 | 기준 (EXPIRE_DAYS=5) |
|---|---|
| E-1 | 0.5일 STANDARD · 2/4.5일 Warm · 6일 delete marker · 3일 전부터 비현행인 버전 삭제 |
| E-2 | 6일 객체 없음 (Versioning OFF) |
| E-3 | ILM current Expiration 후 age6 · 전체 스캔 · time travel **실패**가 정상 결과 (금지 근거). 성공하면 오히려 관찰로 보고 |
| E-4 | 보존 작업 후 전체 스캔 · time travel 성공 · 지운 파일이 비현행 Warm 버전으로 남음 |
| E-5 | 확인점 이후: E-4 age6 파티션 비현행 Warm 버전 0 · delete marker 정리 |
| F-1 | ILM 만료된 전이 버전의 비현행 기록이 읽히는지(`expread`) — 결과를 그대로 기록 (기준 환경: 읽히지 않음) |

### 4-4. 1d 연속 (3~4일)

```bash
export RUN_ID=run-1d-$(date -u +%Y%m%d) DB=ilmtest TRANSITION_DAYS=1 SCANNER_GRACE_HOURS=24
kubectl -n $K8S_NS exec $TB -- mkdir -m 1777 -p /shared/evidence/$RUN_ID
apply_rules                          # 4-1 에서 정의한 함수 (Transition 1d · Noncurrent · DM 정리)
source $CFG && CRON_SUSPEND=0 ./02-deploy.sh
kubectl -n $K8S_NS patch cronjob ilmtest-maintenance --type merge -p '{"spec":{"schedule":"0 21 <D+2> <월> *","suspend":false}}'
```

첫 전이는 **시작 + 1일 → 다음 00:00 UTC 이후** Scanner 방문 시. D+3 이후 `judge.py /shared/evidence/$RUN_ID` + J-7 · J-8 수기 확인.
`02-deploy.sh` 를 다시 실행하면 maintenance 스케줄이 초기화된다 — 패치를 다시 한다.

## 5. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| audit 파일이 안 생김 | Fluent Bit http input 태그는 `-` → `_` (`/minio-hot` → `minio_hot`) · 수신기가 S3 보다 늦게 뜸 | match 확인 · 수신기 먼저 띄운 뒤 S3 재시작 |
| Fluent Bit `invalid JSON message` | audit `queue_dir` 사용 시 묶음 전송 | `queue_dir` 제거 |
| `mv: Operation not permitted` | 증적 디렉터리 sticky + 다른 UID | 실행마다 `RUN_ID` 새로 |
| toolbox `OOMKilled` | `mc pipe` 등 큰 버퍼 | toolbox 1 Gi · `mc pipe` 대신 `s3_backdate.py put … 0` |
| 위험 규칙 검사 실패 | 같은 버킷의 다른 시험 규칙(current Expiration) | 기한 삭제 시험 규칙이면 정상 — `run-expiry.sh` 외 적용은 시험 규칙 정리 후 |
| 전이가 안 됨 | 00:00 UTC 올림 · Scanner 사이클 · prefix 불일치 | `mc stat` 의 예정 시각 · `DESCRIBE TABLE EXTENDED` Location ↔ 규칙 prefix |
| CronJob 을 다시 켜자마자 실행 | 놓친 마지막 스케줄 즉시 실행 | 설정을 먼저 바꾼 뒤 해제 |
| 메트릭 수집 실패 | AIStor metrics 인증 · v3 경로 | `HOT_METRICS_URLS` 수정, 실패해도 다른 판정은 진행하고 기록 |

## 6. mtime 소급이 안 될 때 (E-0 실패)

`X-Minio-Source-Mtime` 를 받지 않는 S3 라면 실제 시간으로 검증한다.

1. 시험 버킷에 `EXPIRE_DAYS` 를 줄인 규칙 (`Transition 1 · Expiration 2 · Noncurrent 1`) 을 `00-apply-ilm.sh` 로 걸고 (`ALLOW_CURRENT_EXPIRATION=1` 은 **Iceberg 가 아닌 객체 prefix** 에만).
2. `perf/exp-object-test.sh setup` 대신 일반 PUT 으로 객체를 만든다 — 나이는 0 에서 시작.
3. `perf/exp-status-cronjob.yaml` 을 배포해 매시 기록 → D+1, D+2, D+3 의 00:00 UTC 이후 상태로 E-1 · E-2 를 판정.
4. Iceberg(E-3 · E-4) 는 `exp_iceberg.py MODE=setup EXP_AGES=0` → D+2 에 `MODE=retention RETAIN_DAYS=2` → 확인점.
5. 결과서에 "실시간 검증(소급 불가)" 와 날짜별 기록을 남긴다.

## 7. 결과서 형식

파일: `13-ilm-hot-only-test/results/REPORT-<환경>-<YYYYMMDD>.md` — 아래 틀을 채운다. 수치는 증적 파일에서 옮기고 출처 파일을 적는다.

```markdown
# ILM 시험 결과 — <환경 이름> (<YYYY-MM-DD>)

> 환경: <AIStor 버전 · 노드 수> · <mc 버전> · HMS <버전> · Spark 3.5.3 + Iceberg 1.9.0 · 모드 <A/B>
> 규칙: Transition <1>d → <tier> · Noncurrent <1>d · 보존 <5>일 (Iceberg 보존 작업) · 버킷 <이름> (Versioning <ON>)
> 증적: results/<RUN_ID 들>/

## 1. 결론
| 구분 | 판정 | 한 줄 요약 |
|---|---|---|
| ① 기능 J-1~J-8 | ✅/❌/⏳ | |
| ② 성능 P-1~P-4 | | 전이 처리율 <n>개/s · 읽기 지연 +<n>% · 쓰기 영향 <없음> |
| ③ 영향도 I-1~I-5 | | |
| 기한 삭제 E-0~E-5 | | 소급 <가능/불가> · Warm 삭제 <확인/대기> |

## 2. 판정표
(judge.py · perf-report.md · expiry-report.md 표를 그대로 붙이고, 수기 판정(J-7 · J-8 · I-5 · E-5)을 채운다)

## 3. 기준 환경(13장, 2026-10-26)과 비교
| 항목 | 기준 | 이번 | 차이 해석 |
|---|---|---|---|
| P-1 처리율 (default) | 4.5개/s (단일 노드) | | |
| P-3 파티션 읽기 증가 | +26% | | |
| F-1 만료된 전이 버전 읽기 | 읽히지 않음 | | |

## 4. 관찰 · 이상
| # | 관찰 | 증적 파일 | 영향 |

## 5. 남은 확인 · 정리
- 실시간 확인점: <시각> — <확인할 것>
- 정리: ns 삭제 <예정/완료> · Scanner <default 확인> · 시험 규칙 · tier <제거 여부>
```

## 8. 끝내기

1. 결과서 · `results/<RUN_ID>/` 원시 증적을 저장소에 남긴다. **audit 원시 로그(`audit-minio-*.jsonl`)는 서명 헤더 · 내부 IP 가 있으니 커밋하지 않고** 요약만 남긴다.
2. Scanner `default` 확인 · 시험 규칙 목록을 결과서에 첨부(`mc ilm rule export`).
3. 사람에게 정리 여부를 묻고, 승인되면 `kubectl delete ns $K8S_NS` 와 모드 A 시험 버킷 정리 (02장 §6).
