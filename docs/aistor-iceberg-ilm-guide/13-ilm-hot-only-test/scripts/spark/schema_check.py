"""Schema check — ILM 적용 전/후 테이블 정의가 그대로인지 기록한다 (영향도 검증 I-1~I-4).

SCHEMA_PHASE(예: pre-rule / post-transition)마다 한 줄씩 남기고, 구간끼리 비교한다.
  schema_json · partitioning · location · provider · table_properties(스냅샷 관련 키 제외)
  pinned_files_sha : PIN_BATCH(기본 bl039) 커밋 스냅샷 기준 data 파일 경로 목록 해시 — 전이로 경로가 바뀌지 않음
EVOLVE=1 이면 전이 후 스키마 변경(ADD COLUMN → 옛 파일 null 읽기 → 새 컬럼 쓰기/읽기 → DROP COLUMN)을 시험한다.

로그: event=ilmtest.schema
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EVENTS_LOC, EVENTS_T, LEDGER_T, Timer, log, spark_session  # noqa: E402

PHASE = os.environ.get("SCHEMA_PHASE", "check")
PIN_BATCH = os.environ.get("PIN_BATCH", "bl039")
# 커밋마다 바뀌는 값 — 비교에서 뺀다
VOLATILE = ("current-snapshot", "snapshot-count", "metadata_location", "previous_metadata_location")


def describe(spark):
    rows = spark.sql("DESCRIBE TABLE EXTENDED {}".format(EVENTS_T)).collect()
    info, part, sect = {}, [], None
    for r in rows:
        k, v = (r["col_name"] or "").strip(), (r["data_type"] or "").strip()
        if k.startswith("#"):
            sect = k
            continue
        if sect == "# Partitioning" and k:
            part.append(v)
        elif sect == "# Metadata Columns":
            continue
        elif sect == "# Detailed Table Information" and k:
            info[k] = v
    return info, part


def snapshot(spark):
    out = {"phase": PHASE}
    out["schema_json"] = spark.table(EVENTS_T).schema.json()
    out["schema_sha"] = hashlib.sha256(out["schema_json"].encode()).hexdigest()[:16]
    info, part = describe(spark)
    out.update(partitioning=part, location=info.get("Location"), provider=info.get("Provider"),
               location_ok=info.get("Location") == EVENTS_LOC)
    props = {r["key"]: r["value"] for r in spark.sql("SHOW TBLPROPERTIES {}".format(EVENTS_T)).collect()}
    out["table_properties"] = {k: v for k, v in sorted(props.items()) if not k.startswith(VOLATILE)}
    out["props_sha"] = hashlib.sha256(repr(out["table_properties"]).encode()).hexdigest()[:16]

    pin = spark.sql("SELECT snapshot_id FROM {} WHERE batch_id = '{}'".format(LEDGER_T, PIN_BATCH)).first()
    if pin:
        paths = sorted(r["file_path"] for r in spark.sql(
            "SELECT file_path FROM {}.files VERSION AS OF {}".format(EVENTS_T, pin["snapshot_id"])).collect())
        out.update(pinned_snapshot=pin["snapshot_id"], pinned_files=len(paths),
                   pinned_files_sha=hashlib.sha256("\n".join(paths).encode()).hexdigest()[:16],
                   pinned_files_sample=paths[:2])
    out["snapshots"] = spark.sql("SELECT count(*) AS c FROM {}.snapshots".format(EVENTS_T)).first()["c"]
    return out


def evolve(spark):
    """전이된 파일 위에서 스키마 변경 — 메타데이터만 바뀌고 옛 파일은 그대로 읽혀야 한다."""
    res = {}
    old_rows = spark.sql("SELECT count(*) AS c FROM {} WHERE batch_id = 'bl000'".format(EVENTS_T)).first()["c"]
    with Timer() as t:
        spark.sql("ALTER TABLE {} ADD COLUMN ilm_note STRING".format(EVENTS_T))
    res["add_column_ms"] = t.ms
    with Timer() as t:
        r = spark.sql("SELECT count(*) AS c, count(ilm_note) AS nn FROM {} WHERE batch_id = 'bl000'"
                      .format(EVENTS_T)).first()
    res["old_read"] = {"ok": r["c"] == old_rows and r["nn"] == 0, "rows": r["c"], "non_null": r["nn"], "ms": t.ms}
    spark.sql("""INSERT INTO {} SELECT 'evolve' AS batch_id, id, current_timestamp() AS event_ts,
                 sha2(cast(id AS STRING), 256) AS payload, 'after-ilm' AS ilm_note FROM range(1000)""".format(EVENTS_T))
    r = spark.sql("SELECT count(*) AS c FROM {} WHERE ilm_note = 'after-ilm'".format(EVENTS_T)).first()
    res["new_write_read"] = {"ok": r["c"] == 1000, "rows": r["c"]}
    # 원상복구 — 이후 측정 Job 이 같은 스키마로 쓰도록. 'evolve' 행은 ledger 대상이 아니므로 지운다
    spark.sql("DELETE FROM {} WHERE batch_id = 'evolve'".format(EVENTS_T))
    spark.sql("ALTER TABLE {} DROP COLUMN ilm_note".format(EVENTS_T))
    res["restored"] = "ilm_note" not in spark.table(EVENTS_T).columns
    res["ok"] = res["old_read"]["ok"] and res["new_write_read"]["ok"] and res["restored"]
    return res


def main():
    spark = spark_session("ilmtest-schema-" + PHASE)
    try:
        out = snapshot(spark)
        if os.environ.get("EVOLVE") == "1":
            out["evolve"] = evolve(spark)
        out["status"] = "fail" if (out.get("evolve", {}).get("ok") is False or not out["location_ok"]) else "ok"
        log("ilmtest.schema", **out)
    except Exception as e:
        log("ilmtest.schema", phase=PHASE, status="error", error=str(e)[:2000])
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
