#!/usr/bin/env bash
# run-perf-impact.sh — ② 성능·부하 / ③ 영향도 시험을 한 번에 실행한다 (작업 PC 에서, kubectl 로)
#
#   P-1 기존 객체 전이 소요·처리율   P-2 전이 중 쓰기·읽기 지연   P-3 전이 후 지연   P-4 Hot/Warm 자원
#   I-1 HMS 정의 불변  I-2 Iceberg 스키마·파티션·속성 불변  I-3 데이터 파일 경로 불변  I-4 전이 후 스키마 변경  I-5 Spark 설정 무변경
#
# 순서: 백로그 적재(규칙 없음) → 전 정의 기록 → 기준선 측정 → 규칙 병합 적용 → 전이 완료까지 측정 → 후 정의 기록
#       → 전이 후 측정 → 스키마 변경 시험 → 증적 회수 → perf_report.py
# 전제: 02-deploy.sh 완료(ConfigMap ilmtest-config/jobs, Secret ilmtest-s3), toolbox Pod(MC_HOST_HOT/WARM), tier 등록.
#       기존 규칙은 유지된다(MERGE=1). 실행 중인 1d 연속 테스트와 같은 버킷을 써도 된다 — 다른 DB(prefix)로 격리.
# 사용:
#   source testbed/config.corp.env   # 또는 config.env
#   PERF_DB=ilmperf RUN_ID=perf-$(date +%Y%m%d) perf/run-perf-impact.sh
# 주요 변수 (기본값):
#   BACKLOG_COMMITS=40 BACKLOG_FILES=100 BACKLOG_ROWS=600000   → data 파일 4,000개 · 약 1 GiB
#   PROBE_SECONDS=900 PROBE_INTERVAL=60 FULL_EVERY=5          → 기준선·전이 후 각 15분
#   TRANSITION_TIMEOUT=14400                                   → 전이 완료 대기 상한(초)
#   SCANNER_SPEED=                                             → 지정 시(fast|fastest) 시험 중에만 바꾸고 끝나면 default 로 원복
#   CONFIG_ENV=testbed/config.corp.env                         → toolbox 안에서 source 할 설정 파일
#   ALLOW_CURRENT_EXPIRATION=1                                 → 같은 버킷에 기한 삭제 시험(run-expiry.sh) 규칙이 남아 있을 때만
#                                                                (권장 순서: 성능 시험을 기한 삭제 시험보다 먼저)
set -euo pipefail
cd "$(dirname "$0")/.."
source ./lib.sh
: "${K8S_NS:?config 를 source 하세요}"
NS=$K8S_NS
PERF_DB=${PERF_DB:-ilmperf}
RUN_ID=${RUN_ID:-perf-$(date -u +%Y%m%d)}
EV=/shared/evidence/$RUN_ID
OUT=${OUT:-../results/$RUN_ID}
CONFIG_ENV=${CONFIG_ENV:-testbed/config.corp.env}
PROBE_SECONDS=${PROBE_SECONDS:-900}
PROBE_INTERVAL=${PROBE_INTERVAL:-60}
FULL_EVERY=${FULL_EVERY:-5}
TRANSITION_TIMEOUT=${TRANSITION_TIMEOUT:-14400}
J="DB=$PERF_DB EVIDENCE_DIR=$EV"
mkdir -p "$OUT"
log() { echo "[$(date -u +%T)] $*"; }
TB=$(kubectl -n "$NS" get pod -l app.kubernetes.io/name=toolbox -o jsonpath='{.items[0].metadata.name}')
tb() { kubectl -n "$NS" exec "$TB" -- bash -c "$1"; }
phase() { tb "echo '{\"event\":\"ilmtest.perfphase\",\"phase\":\"$1\",\"ts\":\"'\$(date -u +%FT%TZ)'\"}' >> $EV/ilmtest.perfphase.jsonl"; }
job() {  # job <name> <script> [KEY=VAL...] — 실행 후 완료 대기
  local name=$1 py=$2; shift 2
  perf/perf-job.sh "$name" "$py" $J "$@" >/dev/null
  wait_job "$NS" "$name" "${JOB_TIMEOUT:-3600}" || { log "❌ $name 실패"; kubectl -n "$NS" logs "job/$name" --tail=30; exit 1; }
}

sync_jobs "$NS"
log "0) toolbox 준비 · 증적 디렉터리 $EV"
tb "mkdir -p /tmp/s/testbed && mkdir -m 1777 -p $EV"
for f in 00-apply-ilm.sh perf/perf_sampler.py "$CONFIG_ENV"; do kubectl -n "$NS" cp "$f" "$NS/$TB:/tmp/s/${f#perf/}"; done
TOP_PID=""
cleanup() {
  [[ -n "$TOP_PID" ]] && kill "$TOP_PID" 2>/dev/null || true
  if [[ -n "${SCANNER_SPEED:-}" ]]; then tb "mc admin config set \$HOT_ALIAS scanner speed=default >/dev/null" || true; log "Scanner speed=default 원복"; fi
}
trap cleanup EXIT
# P-4: Pod 자원 (kubectl top, 15초)
( while true; do ts=$(date -u +%FT%TZ)
    kubectl -n "$NS" top pod --no-headers 2>/dev/null | awk -v ts="$ts" '$1 ~ /^(minio-hot|minio-warm|hive-metastore|postgres|perf-)/ {print ts, $1, $2, $3}' >> "$OUT/top.txt"
    sleep 15; done ) & TOP_PID=$!

log "1) 백로그 적재 (규칙 없는 기존 테이블 $PERF_DB.events)"
PERF_CPU=2 job perf-backlog perf_backlog.py BACKLOG_COMMITS="${BACKLOG_COMMITS:-40}" BACKLOG_FILES="${BACKLOG_FILES:-100}" BACKLOG_ROWS="${BACKLOG_ROWS:-600000}"

log "2) 규칙 적용 전 정의 기록 (I-1 · I-2 · I-3)"
perf/hms_snapshot.sh "$PERF_DB" events pre-rule >> "$OUT/ilmtest.hms.jsonl"
job perf-schema-pre schema_check.py SCHEMA_PHASE=pre-rule PIN_BATCH="bl$(printf %03d $(( ${BACKLOG_COMMITS:-40} - 1 )))"

log "3) 전이 샘플러 시작 + 기준선 측정 ${PROBE_SECONDS}s"
tb "cd /tmp/s && (PERF_PREFIX=$PERF_DB.db/events EVIDENCE_DIR=$EV SAMPLE_SEC=15 DONE_HOLD=${DONE_HOLD:-1000000} SAMPLER_MAX_SEC=$((TRANSITION_TIMEOUT + PROBE_SECONDS + 600)) nohup python3 -W ignore perf_sampler.py > /tmp/s/sampler-$RUN_ID.out 2>&1 &)"
phase baseline-start
job perf-probe-baseline perf_probe.py PROBE_PHASE=baseline PROBE_SECONDS="$PROBE_SECONDS" PROBE_INTERVAL="$PROBE_INTERVAL" FULL_EVERY="$FULL_EVERY"

log "4) 규칙 병합 적용 (Transition 0d → \$TIER_NAME, prefix $PERF_DB.db/events/data/)"
[[ -n "${SCANNER_SPEED:-}" ]] && { tb "mc admin config set \$HOT_ALIAS scanner speed=$SCANNER_SPEED >/dev/null"; log "Scanner speed=$SCANNER_SPEED (시험 중에만)"; }
perf/perf-job.sh perf-probe-transition perf_probe.py $J PROBE_PHASE=transition PROBE_SECONDS="$TRANSITION_TIMEOUT" \
  PROBE_INTERVAL="$PROBE_INTERVAL" FULL_EVERY="$FULL_EVERY" >/dev/null
kubectl -n "$NS" wait --for=condition=Ready pod -l job-name=perf-probe-transition --timeout=300s >/dev/null
tb "cd /tmp/s && export RUN_ID=$RUN_ID DB=$PERF_DB TRANSITION_DAYS=0 SCANNER_GRACE_HOURS=0 && source ./$CONFIG_ENV \
    && MERGE=1 RULE_ID_PREFIX=$PERF_DB- ${ALLOW_CURRENT_EXPIRATION:+ALLOW_CURRENT_EXPIRATION=1} bash 00-apply-ilm.sh > /tmp/s/apply-$RUN_ID.out 2>&1" \
  || { tb "cat /tmp/s/apply-$RUN_ID.out"; exit 1; }
phase rule-applied

log "5) 전이 완료 대기 (STANDARD 0, 최대 ${TRANSITION_TIMEOUT}s)"
for ((t = 0; t < TRANSITION_TIMEOUT; t += 30)); do
  st=$(tb "tail -1 $EV/ilmtest.perfsample.jsonl" | python3 -c 'import json,sys;o=json.loads(sys.stdin.read());print(o["standard"],o["total"])')
  [[ $((t % 300)) == 0 ]] && log "   STANDARD/전체 = ${st/ //}"
  [[ "${st%% *}" == 0 ]] && break
  sleep 30
done
phase transition-done
tb "touch $EV/STOP_PROBE"; wait_job "$NS" perf-probe-transition 600 || true; tb "rm -f $EV/STOP_PROBE"
[[ -n "${SCANNER_SPEED:-}" ]] && { tb "mc admin config set \$HOT_ALIAS scanner speed=default >/dev/null"; SCANNER_SPEED=""; phase scanner-default; log "Scanner speed=default 원복"; }

log "6) 전이 후 정의 기록 · 전이 후 측정 ${PROBE_SECONDS}s"
perf/hms_snapshot.sh "$PERF_DB" events post-transition >> "$OUT/ilmtest.hms.jsonl"
job perf-schema-post schema_check.py SCHEMA_PHASE=post-transition PIN_BATCH="bl$(printf %03d $(( ${BACKLOG_COMMITS:-40} - 1 )))"
job perf-probe-post perf_probe.py PROBE_PHASE=post PROBE_SECONDS="$PROBE_SECONDS" PROBE_INTERVAL="$PROBE_INTERVAL" FULL_EVERY="$FULL_EVERY"

log "7) 전이된 파일 위 스키마 변경 (I-4: ADD COLUMN → 옛 파일 null → 새 컬럼 쓰기 → DROP 원복)"
job perf-schema-evolve schema_check.py SCHEMA_PHASE=post-evolve EVOLVE=1 PIN_BATCH="bl$(printf %03d $(( ${BACKLOG_COMMITS:-40} - 1 )))"
perf/hms_snapshot.sh "$PERF_DB" events post-evolve >> "$OUT/ilmtest.hms.jsonl"
tb "touch $EV/STOP_SAMPLER"

log "8) 증적 회수 → $OUT"
for f in $(tb "ls $EV"); do [[ "$f" == *.jsonl ]] && tb "cat $EV/$f" > "$OUT/$f"; done
kubectl -n "$NS" cp "$NS/$TB:/tmp/s/apply-$RUN_ID.out" "$OUT/apply-rules.out" >/dev/null 2>&1 || true
python3 perf/perf_report.py "$OUT" "$OUT/top.txt" | tee "$OUT/perf-report.md"
log "완료 — 보고서 $OUT/perf-report.md"
