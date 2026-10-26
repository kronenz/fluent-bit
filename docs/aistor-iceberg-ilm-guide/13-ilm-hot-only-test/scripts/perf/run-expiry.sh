#!/usr/bin/env bash
# run-expiry.sh — "Hot 1일 → Warm → 기한 지나면 삭제" 를 기다리지 않고 지금 검증한다 (E-0 ~ E-5)
#
#   E-0 mtime 소급 가능 여부 (불가 → 실시간 일정으로 전환, 03-agent-runbook §6)
#   E-1 객체 단위 (Versioning ON):  age 0.5/2/4.5/6 · 비현행 만료 · 덮어쓰기 비교
#   E-2 객체 단위 (Versioning OFF): 같은 나이 — 만료 = 즉시 영구 삭제 + Warm 삭제
#   E-3 Iceberg + ILM current Expiration (금지 규칙이 실제로 테이블을 깨는지)
#   E-4 Iceberg 권장 방식 — Iceberg 보존 작업(DELETE + expire_snapshots) + ILM 비현행 만료
#   E-5 실시간 확인점 추적 (CronJob ilmtest-exp-status, 매시 45분)
#
# 원리: MinIO 는 X-Minio-Source-Mtime(사이트 복제 내부 헤더)을 객체 mtime 으로 받는다 → 일수 경과를 즉시 재현.
#       ILM 은 mtime + Days 를 **다음 00:00 UTC 로 올림**한 시각에 실행한다 (mc stat 의 Expiration 으로 확인 가능).
#       규칙은 실제 시간 흐름대로 두 단계로 건다: ① Transition 만 → ② Transition + Expiration (+ Noncurrent)
#       (처음부터 같이 걸면 이미 만료일이 지난 객체는 전이 없이 바로 만료된다)
# 전제: run-perf-impact.sh 와 같음 + 관리자 키(MC_HOST_HOT/WARM, toolbox) + Secret ilmtest-tier(tier 계정, tier 자동 생성 시)
# 사용:
#   source testbed/config.corp.env
#   RUN_ID=exp-$(date +%Y%m%d) EXPIRE_DAYS=5 perf/run-expiry.sh
# 같은 버킷에 이 시험이 건 current Expiration 규칙(시험용)이 남아 있으므로 규칙 적용은 모두 ALLOW_CURRENT_EXPIRATION=1 로 한다.
# 재실행은 새 이름으로 (VB · NB · EXP_DB1 · EXP_DB2 · RUN_ID) — 같은 키에 소급 PUT 을 다시 하면 버전 순서가 섞인다. SKIP_OBJ=1 은 E-1/E-2 생략.
# 변수: EXPIRE_DAYS=5 (Transition 1d + Warm 4일 보관 = 생성 후 5일) · NONCURRENT_DAYS=1 · EXP_DB1=ilmexp · EXP_DB2=ilmexp2
set -euo pipefail
cd "$(dirname "$0")/.."
source ./lib.sh
: "${K8S_NS:?config 를 source 하세요}"
NS=$K8S_NS
RUN_ID=${RUN_ID:-exp-$(date -u +%Y%m%d)}
EV=/shared/evidence/$RUN_ID
OUT=${OUT:-../results/$RUN_ID}
CONFIG_ENV=${CONFIG_ENV:-testbed/config.corp.env}
EXPIRE_DAYS=${EXPIRE_DAYS:-5}
NONCURRENT_DAYS=${NONCURRENT_DAYS:-1}
DB1=${EXP_DB1:-ilmexp}; DB2=${EXP_DB2:-ilmexp2}
VB=${VB:-ilm-age-test}; NB=${NB:-ilm-age-nv}
mkdir -p "$OUT"
log() { echo "[$(date -u +%T)] $*"; }
TB=$(kubectl -n "$NS" get pod -l app.kubernetes.io/name=toolbox -o jsonpath='{.items[0].metadata.name}')
tb() { kubectl -n "$NS" exec "$TB" -- bash -c "$1"; }
phase() { tb "echo '{\"event\":\"ilmtest.perfphase\",\"phase\":\"$1\",\"ts\":\"'\$(date -u +%FT%TZ)'\"}' >> $EV/ilmtest.perfphase.jsonl"; }
job() {
  local name=$1; shift
  perf/perf-job.sh "$name" exp_iceberg.py EVIDENCE_DIR="$EV" "$@" >/dev/null
  wait_job "$NS" "$name" 900 || { log "❌ $name 실패"; kubectl -n "$NS" logs "job/$name" --tail=30; exit 1; }
  kubectl -n "$NS" logs "job/$name" | grep '^{"event"' | tail -1
}
until_ok() {  # until_ok <설명> <toolbox 조건 명령> [timeout]
  local t=${3:-900}
  for ((i = 0; i < t; i += 10)); do tb "$2" >/dev/null 2>&1 && { log "   ✔ $1 (${i}s)"; return 0; }; sleep 10; done
  log "   ✘ $1 — ${t}s 안에 안 됨 (Scanner 지연일 수 있음, status 로 확인)"; return 1
}
EXPOBJ="cd /tmp/s && EVIDENCE_DIR=$EV VB=$VB NB=$NB EXPIRE_DAYS=$EXPIRE_DAYS EXP_ICEBERG_PREFIXES=\"\${BUCKET:-warehouse}/$DB1.db/events/data/ \${BUCKET:-warehouse}/$DB2.db/events/data/\" bash exp-object-test.sh"
sc() {  # sc <bucket/key> → 최신 버전 storageClass (DM 이면 DM, 없으면 NONE)
  echo "mc ls --versions --json HOT/$1 | python3 -c 'import json,sys
L=[json.loads(l) for l in sys.stdin if l.strip()]
t=max(L,key=lambda o:o[\"versionOrdinal\"]) if L else None
print(\"NONE\" if not t else (\"DM\" if t.get(\"isDeleteMarker\") else t.get(\"storageClass\",\"STANDARD\")))'"
}

sync_jobs "$NS"
log "0) toolbox 준비 · $EV"
tb "mkdir -p /tmp/s/testbed && mkdir -m 1777 -p $EV"
for f in 00-apply-ilm.sh perf/s3_backdate.py perf/exp-object-test.sh "$CONFIG_ENV"; do kubectl -n "$NS" cp "$f" "$NS/$TB:/tmp/s/${f#perf/}"; done

log "E-0) mtime 소급 확인"
tb "mc mb -p HOT/$VB HOT/$NB >/dev/null && mc version enable HOT/$VB >/dev/null"
got=$(tb "cd /tmp/s && python3 -W ignore s3_backdate.py put $VB probe/backdate 6 >/dev/null && mc stat --json HOT/$VB/probe/backdate" \
      | python3 -c 'import json,sys,datetime;o=json.load(sys.stdin);t=datetime.datetime.strptime(o["lastModified"][:19],"%Y-%m-%dT%H:%M:%S");print(round((datetime.datetime.utcnow()-t).total_seconds()/86400,1))')
tb "mc rm --versions --force HOT/$VB/probe/backdate >/dev/null" || true
log "   PUT(6일 전) → 객체 나이 ${got}일"
if ! python3 -c "import sys; sys.exit(0 if abs(float('$got') - 6) < 0.1 else 1)"; then
  log "❌ 이 S3 는 mtime 소급을 받지 않는다 → 실시간 일정으로 검증 (03-agent-runbook.md §6)"; exit 3
fi

log "   tier 확인: WARM-EXP(exp/) · WARM-EXPI(expi/) — Warm 쪽 객체 수를 정확히 세려고 시험 전용 prefix 를 쓴다"
for t in WARM-EXP:exp/ WARM-EXPI:expi/; do
  if ! tb "mc ilm tier ls HOT 2>/dev/null | grep -q '${t%%:*}'"; then
    kubectl -n "$NS" get secret ilmtest-tier >/dev/null || { log "❌ tier ${t%%:*} 없음 · Secret ilmtest-tier 없음 — 수동 등록 필요"; exit 1; }
    { kubectl -n "$NS" get secret ilmtest-tier -o jsonpath='{.data.access_key}' | base64 -d; echo
      kubectl -n "$NS" get secret ilmtest-tier -o jsonpath='{.data.secret_key}' | base64 -d; echo; } \
    | kubectl -n "$NS" exec -i "$TB" -- bash -c "read -r AK; read -r SK; mc ilm tier add minio HOT ${t%%:*} --endpoint \${WARM_TIER_ENDPOINT:-http://minio-warm.$NS.svc:9000} \
        --access-key \"\$AK\" --secret-key \"\$SK\" --bucket \${WARM_TIER_BUCKET:-warm-tier} --prefix ${t#*:} >/dev/null"
    log "   tier ${t%%:*} 등록"
  fi
done

if [[ "${SKIP_OBJ:-0}" != 1 ]]; then
log "E-1/E-2) 객체 단위 — ① Transition 1d"
tb "$EXPOBJ setup >/dev/null"
until_ok "age ≥1일 객체 Warm 전이" "[ \"\$($(sc $VB/obj/age-6))\" = WARM-EXP ] && [ \"\$($(sc $NB/obj/age-2))\" = WARM-EXP ] && [ \"\$($(sc $VB/obj/age-0.5))\" = STANDARD ]"
tb "$EXPOBJ newver >/dev/null"
log "   ② Transition 1d + Expiration ${EXPIRE_DAYS}d + Noncurrent 1d + 고아 DM 정리"
tb "$EXPOBJ expire >/dev/null"; phase obj-expire-applied
until_ok "age-6 만료 (VB: delete marker · NB: 삭제)" "[ \"\$($(sc $VB/obj/age-6))\" = DM ] && [ \"\$($(sc $NB/obj/age-6))\" = NONE ]"
until_ok "nc v1(3일 전부터 비현행) 만료" "[ \$(mc ls --versions HOT/$VB/obj/nc | wc -l) = 1 ]"
tb "$EXPOBJ status after-expire >/dev/null; $EXPOBJ verify >/dev/null"
tb "for k in age-0.5 age-2 age-4.5 nc ow; do echo \"\$k \$(mc stat HOT/$VB/obj/\$k | grep -o 'Expiration: .*' || echo -)\"; done" | tee "$OUT/expiry-schedule.txt"
fi

log "E-3/E-4) Iceberg — 배치 age6 · age2 · age0 적재"
job exp-setup-$DB1 DB="$DB1" MODE=setup >/dev/null
job exp-setup-$DB2 DB="$DB2" MODE=setup >/dev/null
tb "cd /tmp/s && export RUN_ID=$RUN_ID TRANSITION_DAYS=1 SCANNER_GRACE_HOURS=0 && source ./$CONFIG_ENV && export TIER_NAME=WARM-EXPI NONCURRENT_EXPIRE_DAYS=$NONCURRENT_DAYS \
    && for db in $DB1 $DB2; do DB=\$db TABLE_PREFIX=\$db.db/events MERGE=1 RULE_ID_PREFIX=\$db- ALLOW_CURRENT_EXPIRATION=1 bash 00-apply-ilm.sh > /tmp/s/apply-\$db.out 2>&1 || exit 1; done"
log "   data 파일 mtime 소급 (age6 → 6일 · age2 → 2일) — 규칙이 이미 있으므로 PUT 즉시 전이된다"
tb "cd /tmp/s && python3 - $EV/ilmtest.exp.jsonl $DB1 $DB2 <<'PY' | while read p d; do python3 -W ignore s3_backdate.py rewrite \${BUCKET:-warehouse} \$p \$d; done
import json, sys
todo = {}
for l in open(sys.argv[1]):
    o = json.loads(l)
    if o.get('mode') == 'setup' and o.get('status') == 'ok' and o['table'].split('.')[1] in sys.argv[2:]:
        for b in o['batches'].values():
            if b['age_days'] > 0:
                for p in b['prefixes']:
                    todo[p] = b['age_days']
for p, a in sorted(todo.items()):
    print(p, a)
PY"
job exp-check0-$DB1 DB="$DB1" MODE=check EXP_PHASE=after-transition
job exp-check0-$DB2 DB="$DB2" MODE=check EXP_PHASE=after-transition

log "E-3) $DB1 에 current Expiration ${EXPIRE_DAYS}d (시험 전용 허용)"
tb "cd /tmp/s && export RUN_ID=$RUN_ID TRANSITION_DAYS=1 && source ./$CONFIG_ENV && export TIER_NAME=WARM-EXPI NONCURRENT_EXPIRE_DAYS=$NONCURRENT_DAYS \
    && DB=$DB1 TABLE_PREFIX=$DB1.db/events MERGE=1 RULE_ID_PREFIX=$DB1- EXPIRE_DAYS=$EXPIRE_DAYS ALLOW_CURRENT_EXPIRATION=1 bash 00-apply-ilm.sh > /tmp/s/apply-$DB1-exp.out 2>&1"
phase iceberg-expiration-applied
until_ok "$DB1 age6 파일 만료(DM)" "mc ls --versions HOT/\${BUCKET:-warehouse}/$DB1.db/events/data/ --recursive | grep -q ' DEL '"
job exp-check1-$DB1 DB="$DB1" MODE=check EXP_PHASE=after-ilm-expiration

log "E-4) $DB2 Iceberg 보존 작업 (event_ts < now-${EXPIRE_DAYS}d DELETE → expire_snapshots)"
job exp-retention-$DB2 DB="$DB2" MODE=retention RETAIN_DAYS="$EXPIRE_DAYS"
job exp-check1-$DB2 DB="$DB2" MODE=check EXP_PHASE=after-iceberg-retention
tb "$EXPOBJ status after-iceberg >/dev/null"

log "E-5) 실시간 확인점 추적 CronJob (매시 45분 → $EV/ilmtest.expobj.jsonl)"
kubectl -n "$NS" create configmap ilmtest-exp --dry-run=client -o yaml --from-file=perf/exp-object-test.sh --from-file=perf/s3_backdate.py | kubectl -n "$NS" apply -f - >/dev/null
sed "s#__EV__#$EV#; s#__VB__#$VB#; s#__NB__#$NB#; s#__PREFIXES__#${BUCKET:-warehouse}/$DB1.db/events/data/ ${BUCKET:-warehouse}/$DB2.db/events/data/#" perf/exp-status-cronjob.yaml | render | kubectl -n "$NS" apply -f - 2>&1 | grep -v '^Warning' || true

log "증적 회수 → $OUT"
for f in $(tb "ls $EV"); do [[ "$f" == *.jsonl ]] && tb "cat $EV/$f" > "$OUT/$f"; done
python3 perf/exp_report.py "$OUT" | tee "$OUT/expiry-report.md"
log "완료 — 실시간 확인점은 expiry-schedule.txt 의 Expiration 시각 + 비현행 ${NONCURRENT_DAYS}일 (다음 00:00 UTC 올림)"
