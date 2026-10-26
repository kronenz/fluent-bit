"""Maintenance — 전이된 파일 대상 compaction → expire_snapshots (D2 이후 수동 1회).

로그: event=ilmtest.maintenance  (J-6)
실행: kubectl -n ilm-test create job --from=cronjob/ilmtest-maintenance ilmtest-maint-$(date +%H%M)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CATALOG, DB, EVENTS_T, TABLE, Timer, log, spark_session  # noqa: E402

TRANSITION_DAYS = int(os.environ.get("TRANSITION_DAYS", "1"))
GRACE_HOURS = int(os.environ.get("SCANNER_GRACE_HOURS", "24"))
RETAIN_LAST = int(os.environ.get("RETAIN_LAST", "10"))


def main():
    spark = spark_session("ilmtest-maintenance")
    ident = "{}.{}".format(DB, TABLE)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=TRANSITION_DAYS, hours=GRACE_HOURS)
    cutoff_s = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    try:
        before = spark.sql("SELECT count(*) AS c FROM {}".format(EVENTS_T)).first()["c"]

        # 1) 전이 기한이 지난 파티션만 compaction — 읽기는 warm(Hot 경유), 쓰기는 hot 신규 파일
        with Timer() as t1:
            rw = spark.sql("""
                CALL {}.system.rewrite_data_files(
                    table => '{}', where => "event_ts < timestamp'{}'",
                    options => map('min-input-files', '2'))""".format(CATALOG, ident, cutoff_s)).first()
        log("ilmtest.maintenance", step="rewrite_data_files", status="ok", ms=t1.ms,
            rewritten_files=rw["rewritten_data_files_count"], added_files=rw["added_data_files_count"],
            rewritten_bytes=rw.asDict().get("rewritten_bytes_count"))

        # 2) 스냅샷 만료 — 지운 파일은 Versioning ON 이면 noncurrent 로 남는다 (R-3 이 회수)
        with Timer() as t2:
            ex = spark.sql("""
                CALL {}.system.expire_snapshots(
                    table => '{}', older_than => timestamp'{}', retain_last => {})""".format(
                CATALOG, ident, datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), RETAIN_LAST)).first()
        log("ilmtest.maintenance", step="expire_snapshots", status="ok", ms=t2.ms,
            deleted_data_files=ex["deleted_data_files_count"],
            deleted_manifest_files=ex["deleted_manifest_files_count"],
            deleted_manifest_lists=ex["deleted_manifest_lists_count"])

        after = spark.sql("SELECT count(*) AS c FROM {}".format(EVENTS_T)).first()["c"]
        log("ilmtest.maintenance", step="verify", status="ok" if before == after else "fail",
            rows_before=before, rows_after=after)
        if before != after:
            sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:
        log("ilmtest.maintenance", step="error", status="fail", error=str(e)[:2000])
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
