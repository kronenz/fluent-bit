"""Perf probe — 한 Spark 세션으로 일정 간격 쓰기·읽기 지연을 반복 측정한다 (성능·부하 검증 P-2/P-3).

규칙 적용 전(기준선) → 적용 후 전이 진행 중 → 전이 완료 후, 같은 Job 을 구간마다 돌려 비교한다.
구간 이름은 PROBE_PHASE 로 준다. 매 회:
  write_ms     : PROBE_ROWS 행 append (+ ledger)
  part_read_ms : 고정 파티션(bl000, 기존 파일 BACKLOG_FILES 개) 전체 읽기 — hot → warm 으로 바뀌는 비용
  meta_ms      : files 메타데이터 테이블 조회 (metadata/ 만 읽음 — 전이 대상 아님)
FULL_EVERY 회마다 전체 테이블 checksum 을 ledger 와 대조한다 (full_scan_ms · 정합성).

로그: event=ilmtest.probe
"""
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EVENTS_T, LEDGER_T, ROW_CHECKSUM_SQL, Timer, log, spark_session  # noqa: E402

PHASE = os.environ.get("PROBE_PHASE", "baseline")
DURATION = int(os.environ.get("PROBE_SECONDS", "900"))
INTERVAL = int(os.environ.get("PROBE_INTERVAL", "60"))
ROWS = int(os.environ.get("PROBE_ROWS", "20000"))
FULL_EVERY = int(os.environ.get("FULL_EVERY", "5"))
STOP_FILE = os.path.join(os.environ.get("EVIDENCE_DIR", "/tmp"), "STOP_PROBE")


def one(spark, n):
    out = {"phase": PHASE, "seq": n}
    batch_id = "pr" + datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    df = spark.sql("""
        SELECT '{b}' AS batch_id, id, current_timestamp() AS event_ts,
               sha2(concat('{b}', ':', cast(id AS STRING)), 256) AS payload
        FROM range({n})""".format(b=batch_id, n=ROWS)).cache()
    checksum = df.selectExpr("sum({}) AS c".format(ROW_CHECKSUM_SQL)).first()["c"]
    with Timer() as t:
        df.writeTo(EVENTS_T).append()
    df.unpersist()
    out["write_ms"] = t.ms
    snap = spark.sql("SELECT snapshot_id, committed_at FROM {}.snapshots ORDER BY committed_at DESC LIMIT 1"
                     .format(EVENTS_T)).first()
    spark.sql("INSERT INTO {} VALUES ('{}', current_timestamp(), {}, {}, {}, timestamp'{}', {})".format(
        LEDGER_T, batch_id, ROWS, checksum, snap["snapshot_id"], snap["committed_at"], t.ms))

    with Timer() as t:
        r = spark.sql("SELECT count(*) AS c, sum({}) AS s FROM {} WHERE batch_id = 'bl000'"
                      .format(ROW_CHECKSUM_SQL, EVENTS_T)).first()
    out.update(part_read_ms=t.ms, part_rows=r["c"])

    with Timer() as t:
        out["data_files"] = spark.sql("SELECT count(*) AS c FROM {}.files".format(EVENTS_T)).first()["c"]
    out["meta_ms"] = t.ms

    if n % FULL_EVERY == 0:
        with Timer() as t:
            act = spark.sql("SELECT count(*) AS c, sum({}) AS s FROM {}".format(ROW_CHECKSUM_SQL, EVENTS_T)).first()
        exp = spark.sql("SELECT sum(rows) AS c, sum(checksum) AS s FROM {}".format(LEDGER_T)).first()
        out.update(full_scan_ms=t.ms, full_ok=(act["c"] == exp["c"] and act["s"] == exp["s"]),
                   full_rows=act["c"], expected_rows=exp["c"])
    return out


def main():
    spark = spark_session("ilmtest-perf-probe-" + PHASE)
    t_end = time.time() + DURATION
    n = 0
    try:
        while time.time() < t_end and not os.path.exists(STOP_FILE):
            t0 = time.time()
            try:
                out = one(spark, n)
                out["status"] = "fail" if out.get("full_ok") is False else "ok"
            except Exception as e:  # 한 회 실패도 증적으로 남기고 계속 측정
                out = {"phase": PHASE, "seq": n, "status": "error", "error": str(e)[:1000]}
            log("ilmtest.probe", **out)
            n += 1
            time.sleep(max(0, INTERVAL - (time.time() - t0)))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
