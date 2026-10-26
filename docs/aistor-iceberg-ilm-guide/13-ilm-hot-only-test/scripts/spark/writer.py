"""Writer — 주기적으로 events 테이블에 1 배치 append 하고 ledger 에 기대값을 기록한다.

로그: event=ilmtest.write  (J-5 판정: status, write_ms)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (EVENTS_LOC, EVENTS_T, LEDGER_LOC, LEDGER_T, ROW_CHECKSUM_SQL, Timer, log,  # noqa: E402
                    spark_session)

ROWS = int(os.environ.get("ROWS_PER_BATCH", "200000"))


def ensure_tables(spark):
    spark.sql("CREATE NAMESPACE IF NOT EXISTS {}".format(EVENTS_T.rsplit(".", 1)[0]))
    spark.sql("""
        CREATE TABLE IF NOT EXISTS {} (
            batch_id STRING, id BIGINT, event_ts TIMESTAMP, payload STRING)
        USING iceberg
        PARTITIONED BY (hours(event_ts))
        LOCATION '{}'
        TBLPROPERTIES ('format-version'='2')""".format(EVENTS_T, EVENTS_LOC))
    # ledger 는 ILM 대상 prefix(events/data/) 밖에 둔다
    spark.sql("""
        CREATE TABLE IF NOT EXISTS {} (
            batch_id STRING, batch_start TIMESTAMP, rows BIGINT, checksum BIGINT,
            snapshot_id BIGINT, committed_at TIMESTAMP, write_ms BIGINT)
        USING iceberg
        LOCATION '{}'
        TBLPROPERTIES ('format-version'='2')""".format(LEDGER_T, LEDGER_LOC))


def main():
    start = datetime.datetime.utcnow().replace(second=0, microsecond=0)
    batch_id = start.strftime("%Y%m%dT%H%M")
    spark = spark_session("ilmtest-writer-" + batch_id)
    try:
        ensure_tables(spark)
        if spark.sql("SELECT 1 FROM {} WHERE batch_id = '{}'".format(LEDGER_T, batch_id)).take(1):
            log("ilmtest.write", status="skip", batch_id=batch_id, reason="already written")
            return

        df = spark.sql("""
            SELECT '{b}' AS batch_id, id,
                   timestamp_millis(unix_millis(timestamp'{ts}') + id) AS event_ts,
                   sha2(concat('{b}', ':', cast(id AS STRING)), 256) AS payload
            FROM range({n})""".format(b=batch_id, ts=start.strftime("%Y-%m-%d %H:%M:%S"), n=ROWS)).cache()
        checksum = df.selectExpr("sum({}) AS c".format(ROW_CHECKSUM_SQL)).first()["c"]

        with Timer() as t:
            df.writeTo(EVENTS_T).append()

        snap = spark.sql("""
            SELECT snapshot_id, committed_at, summary['added-data-files'] AS added_files
            FROM {}.snapshots ORDER BY committed_at DESC LIMIT 1""".format(EVENTS_T)).first()

        spark.sql("""
            INSERT INTO {} VALUES ('{b}', timestamp'{ts}', {n}, {c}, {s}, timestamp'{ca}', {ms})""".format(
            LEDGER_T, b=batch_id, ts=start.strftime("%Y-%m-%d %H:%M:%S"), n=ROWS, c=checksum,
            s=snap["snapshot_id"], ca=snap["committed_at"], ms=t.ms))

        log("ilmtest.write", status="ok", batch_id=batch_id, rows=ROWS, checksum=checksum,
            snapshot_id=snap["snapshot_id"], added_files=snap["added_files"], write_ms=t.ms)
    except Exception as e:  # 실패도 증적 — 메시지를 남기고 Job 을 실패시킨다
        log("ilmtest.write", status="fail", batch_id=batch_id, error=str(e)[:2000])
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
