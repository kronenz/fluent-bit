#!/usr/bin/env bash
# hms_snapshot.sh <db> <table> <phase> — HMS(PostgreSQL) 에 저장된 테이블 정의를 한 줄 JSON 으로 출력 (영향도 I-1)
# 비교 대상: TBL_TYPE · SD LOCATION · INPUT/OUTPUT FORMAT · SERDE · 컬럼 · TABLE_PARAMS(키 목록, table_type)
# metadata_location 은 커밋마다 바뀌므로 값 대신 "s3://<bucket>/<db>.db/<tbl>/metadata/" 아래인지 만 본다.
set -euo pipefail
DB=${1:?db}; TBL=${2:?table}; PHASE=${3:?phase}; NS=${K8S_NS:-ilm-test}
kubectl -n "$NS" exec -i deploy/postgres -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v db="$1" -v tbl="$2"' _ "$DB" "$TBL" <<'SQL' \
  | python3 -c '
import json, sys
phase = sys.argv[1]
rows = [l.split("|", 1) for l in sys.stdin.read().splitlines() if "|" in l]
d = {}
for k, v in rows:
    d.setdefault(k, []).append(v)
params = dict(p.split("=", 1) for p in d.get("param", []))
ml = params.pop("metadata_location", "")
# 커밋마다 바뀌는 값은 비교에서 뺀다
for k in [k for k in params if k.startswith(("current-snapshot", "previous_metadata_location", "snapshot-count",
                                             "numFiles", "numRows", "totalSize", "transient_lastDdlTime"))]:
    params.pop(k)
out = {"event": "ilmtest.hms", "phase": phase, "tbl_type": d.get("tbl_type", [""])[0],
       "location": d.get("location", [""])[0], "formats": d.get("fmt", []), "columns": d.get("col", []),
       "params": params, "params_sha": __import__("hashlib").sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16], "metadata_location_prefix": ml.rsplit("/", 1)[0] + "/"}
print(json.dumps(out, ensure_ascii=False, sort_keys=True))' "$PHASE"
SELECT 'tbl_type|' || t."TBL_TYPE" FROM "TBLS" t JOIN "DBS" d ON d."DB_ID" = t."DB_ID" WHERE d."NAME" = :'db' AND t."TBL_NAME" = :'tbl';
SELECT 'location|' || s."LOCATION" FROM "TBLS" t JOIN "DBS" d ON d."DB_ID" = t."DB_ID" JOIN "SDS" s ON s."SD_ID" = t."SD_ID" WHERE d."NAME" = :'db' AND t."TBL_NAME" = :'tbl';
SELECT 'fmt|' || coalesce(s."INPUT_FORMAT", '') || ' / ' || coalesce(s."OUTPUT_FORMAT", '') || ' / ' || coalesce(se."SLIB", '')
  FROM "TBLS" t JOIN "DBS" d ON d."DB_ID" = t."DB_ID" JOIN "SDS" s ON s."SD_ID" = t."SD_ID" LEFT JOIN "SERDES" se ON se."SERDE_ID" = s."SERDE_ID"
  WHERE d."NAME" = :'db' AND t."TBL_NAME" = :'tbl';
SELECT 'col|' || c."COLUMN_NAME" || ':' || c."TYPE_NAME" FROM "TBLS" t JOIN "DBS" d ON d."DB_ID" = t."DB_ID" JOIN "SDS" s ON s."SD_ID" = t."SD_ID"
  JOIN "COLUMNS_V2" c ON c."CD_ID" = s."CD_ID" WHERE d."NAME" = :'db' AND t."TBL_NAME" = :'tbl' ORDER BY c."INTEGER_IDX";
SELECT 'param|' || p."PARAM_KEY" || '=' || p."PARAM_VALUE" FROM "TBLS" t JOIN "DBS" d ON d."DB_ID" = t."DB_ID"
  JOIN "TABLE_PARAMS" p ON p."TBL_ID" = t."TBL_ID" WHERE d."NAME" = :'db' AND t."TBL_NAME" = :'tbl' ORDER BY 1;
SQL
