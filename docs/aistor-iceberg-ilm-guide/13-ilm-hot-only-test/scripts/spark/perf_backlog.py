"""Perf backlog — ILM 규칙이 없는 상태의 '기존 테이블'을 만든다 (성능·부하 검증 P-1 사전 적재).

commit i 마다 한 시간 파티션에 BACKLOG_FILES 개 파일을 쓴다 → data 파일 수 = COMMITS × FILES.
파일 수를 맞추려고 쓰기 옵션 distribution-mode=none 을 쓴다 (테이블 속성은 바꾸지 않는다 — 영향도 검증 대상).
ledger 에 commit 별 행 수·checksum 을 남겨 정합성(J-3)을 같은 방식으로 판정한다.

로그: event=ilmtest.backlog
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EVENTS_T, LEDGER_T, ROW_CHECKSUM_SQL, Timer, log, spark_session  # noqa: E402
from writer import ensure_tables  # noqa: E402

COMMITS = int(os.environ.get("BACKLOG_COMMITS", "40"))
FILES = int(os.environ.get("BACKLOG_FILES", "100"))
ROWS = int(os.environ.get("BACKLOG_ROWS", "600000"))


def main():
    spark = spark_session("ilmtest-perf-backlog")
    base = datetime.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    try:
        ensure_tables(spark)
        done = {r["batch_id"] for r in spark.table(LEDGER_T).select("batch_id").collect()}
        for i in range(COMMITS):
            batch_id = "bl{:03d}".format(i)
            if batch_id in done:
                continue
            start = base - datetime.timedelta(hours=COMMITS - i)   # 과거 시간 파티션 — 오래된 기존 데이터 모사
            ts = start.strftime("%Y-%m-%d %H:%M:%S")
            df = spark.sql("""
                SELECT '{b}' AS batch_id, id,
                       timestamp_millis(unix_millis(timestamp'{ts}') + pmod(id, 3600000)) AS event_ts,
                       sha2(concat('{b}', ':', cast(id AS STRING)), 256) AS payload
                FROM range({n})""".format(b=batch_id, ts=ts, n=ROWS)).repartition(FILES).cache()
            checksum = df.selectExpr("sum({}) AS c".format(ROW_CHECKSUM_SQL)).first()["c"]
            with Timer() as t:
                df.writeTo(EVENTS_T).option("distribution-mode", "none").append()
            df.unpersist()
            snap = spark.sql("""
                SELECT snapshot_id, committed_at, summary['added-data-files'] AS added_files,
                       summary['added-files-size'] AS added_bytes
                FROM {}.snapshots ORDER BY committed_at DESC LIMIT 1""".format(EVENTS_T)).first()
            spark.sql("INSERT INTO {} VALUES ('{}', timestamp'{}', {}, {}, {}, timestamp'{}', {})".format(
                LEDGER_T, batch_id, ts, ROWS, checksum, snap["snapshot_id"], snap["committed_at"], t.ms))
            log("ilmtest.backlog", status="ok", batch_id=batch_id, rows=ROWS, checksum=checksum,
                added_files=snap["added_files"], added_bytes=snap["added_bytes"], write_ms=t.ms)
    except Exception as e:
        log("ilmtest.backlog", status="fail", error=str(e)[:2000])
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
