"""Expiry test — Hot 1d → Warm → 기한 삭제를 Iceberg 테이블에서 검증한다 (E-3 · E-4).

MODE=setup     : 테이블 생성 + 배치 3개(age6 · age2 · age0) 적재. event_ts 도 그 나이로 넣는다.
                 배치별 data 파티션 prefix 를 로그로 남긴다 → s3_backdate.py 로 객체 mtime 을 같은 나이로 맞춘다.
MODE=check     : 배치별 count · 전체 스캔 · 가장 오래된 스냅샷 time travel 을 시도하고 성공/실패를 기록한다.
MODE=retention : Iceberg 쪽 보존 정책 — event_ts 가 RETAIN_DAYS 보다 오래된 행 DELETE → expire_snapshots.
                 (권장 방식: 삭제는 Iceberg 가, Warm 실데이터 회수는 ILM noncurrent 만료가 한다)

로그: event=ilmtest.exp
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EVENTS_T, LEDGER_T, ROW_CHECKSUM_SQL, Timer, log, spark_session  # noqa: E402
from writer import ensure_tables  # noqa: E402

MODE = os.environ.get("MODE", "check")
PHASE = os.environ.get("EXP_PHASE", MODE)
AGES = [float(x) for x in os.environ.get("EXP_AGES", "6,2,0").split(",")]
ROWS = int(os.environ.get("EXP_ROWS", "100000"))
RETAIN_DAYS = float(os.environ.get("RETAIN_DAYS", "5"))


def cause(e):
    """Py4J 예외에서 근본 원인 한 줄 (예: NotFoundException: Location does not exist: s3://…)"""
    lines = [l.strip() for l in str(e).splitlines() if "Exception:" in l]
    root = next((l for l in reversed(lines) if not l.startswith(("py4j", "org.apache.spark.SparkException"))), None)
    return (root or str(e).split("\n")[0])[:300]


def batch_name(age):
    return "age{:g}".format(age)


def setup(spark):
    ensure_tables(spark)
    now = datetime.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    out = {}
    done = {r["batch_id"] for r in spark.table(LEDGER_T).select("batch_id").collect()}
    for age in AGES:
        b = batch_name(age)
        if b in done:   # 재실행 시 중복 적재 방지
            continue
        start = now - datetime.timedelta(days=age)
        ts = start.strftime("%Y-%m-%d %H:%M:%S")
        df = spark.sql("""
            SELECT '{b}' AS batch_id, id, timestamp_millis(unix_millis(timestamp'{ts}') + pmod(id, 3600000)) AS event_ts,
                   sha2(concat('{b}', ':', cast(id AS STRING)), 256) AS payload
            FROM range({n})""".format(b=b, ts=ts, n=ROWS)).repartition(4).cache()
        checksum = df.selectExpr("sum({}) AS c".format(ROW_CHECKSUM_SQL)).first()["c"]
        df.writeTo(EVENTS_T).option("distribution-mode", "none").append()
        df.unpersist()
        snap = spark.sql("SELECT snapshot_id, committed_at FROM {}.snapshots ORDER BY committed_at DESC LIMIT 1"
                         .format(EVENTS_T)).first()
        spark.sql("INSERT INTO {} VALUES ('{}', timestamp'{}', {}, {}, {}, timestamp'{}', 0)".format(
            LEDGER_T, b, ts, ROWS, checksum, snap["snapshot_id"], snap["committed_at"]))
        prefixes = sorted({p.rsplit("/", 1)[0] + "/" for p in (r["file_path"] for r in spark.sql(
            "SELECT file_path FROM {}.files WHERE readable_metrics.batch_id.lower_bound = '{}'".format(EVENTS_T, b)).collect())})
        out[b] = {"age_days": age, "prefixes": [p.split("://", 1)[1].split("/", 1)[1] for p in prefixes]}
    return {"batches": out}


def check(spark):
    res = {}
    ledger = {r["batch_id"]: r for r in spark.table(LEDGER_T).collect()}
    for b in sorted(ledger):
        try:
            with Timer() as t:
                c = spark.sql("SELECT count(*) AS c, sum({}) AS s FROM {} WHERE batch_id = '{}'"
                              .format(ROW_CHECKSUM_SQL, EVENTS_T, b)).first()
            res[b] = {"ok": c["c"] == ledger[b]["rows"] and c["s"] == ledger[b]["checksum"], "rows": c["c"], "ms": t.ms}
        except Exception as e:
            res[b] = {"ok": False, "error": cause(e)}
    try:
        c = spark.sql("SELECT count(*) AS c, sum({}) AS s FROM {}".format(ROW_CHECKSUM_SQL, EVENTS_T)).first()
        res["full_scan"] = {"ok": True, "rows": c["c"]}
    except Exception as e:
        res["full_scan"] = {"ok": False, "error": cause(e)}
    snap = spark.sql("SELECT snapshot_id FROM {}.snapshots ORDER BY committed_at LIMIT 1".format(EVENTS_T)).first()
    try:
        c = spark.sql("SELECT sum({}) AS s FROM {} VERSION AS OF {}".format(ROW_CHECKSUM_SQL, EVENTS_T, snap["snapshot_id"])).first()
        res["timetravel_oldest"] = {"ok": True, "snapshot_id": snap["snapshot_id"]}
    except Exception as e:
        res["timetravel_oldest"] = {"ok": False, "error": cause(e)}
    res["snapshots"] = spark.sql("SELECT count(*) AS c FROM {}.snapshots".format(EVENTS_T)).first()["c"]
    res["data_files"] = spark.sql("SELECT count(*) AS c FROM {}.files".format(EVENTS_T)).first()["c"]
    return {"result": res}


def retention(spark):
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=RETAIN_DAYS)
    cut = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    out = {"retain_days": RETAIN_DAYS, "cutoff": cut}
    with Timer() as t:
        spark.sql("DELETE FROM {} WHERE event_ts < timestamp'{}'".format(EVENTS_T, cut))
    out["delete_ms"] = t.ms
    s = spark.sql("SELECT summary FROM {}.snapshots ORDER BY committed_at DESC LIMIT 1".format(EVENTS_T)).first()["summary"]
    out["delete_summary"] = {k: s.get(k) for k in ("deleted-data-files", "deleted-records", "added-data-files", "added-delete-files")}
    # 지운 배치는 ledger 에서도 뺀다 (이후 check 의 기대값)
    spark.sql("DELETE FROM {} WHERE batch_start < timestamp'{}'".format(LEDGER_T, cut))
    with Timer() as t:
        r = spark.sql("CALL {}.system.expire_snapshots(table => '{}', older_than => TIMESTAMP '{}', retain_last => 1)".format(
            EVENTS_T.split(".")[0], ".".join(EVENTS_T.split(".")[1:]),
            datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))).first().asDict()
    out.update(expire_ms=t.ms, expire=r)
    return out


def main():
    spark = spark_session("ilmtest-exp-" + MODE)
    try:
        out = {"setup": setup, "check": check, "retention": retention}[MODE](spark)
        log("ilmtest.exp", mode=MODE, phase=PHASE, status="ok", **out)
    except Exception as e:
        log("ilmtest.exp", mode=MODE, phase=PHASE, status="error", error=str(e)[:2000])
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
