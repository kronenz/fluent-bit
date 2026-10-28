"""Tag 기반 ILM — Scanner 에 덜 의존하는 전이 · Iceberg 와 충돌하지 않는 삭제 (T-1 · T-2)

Iceberg S3FileIO 의 객체 태그 기능을 쓴다 (Iceberg AWS 문서 "S3 Tags"):
  s3.write.tags.<k>=<v>   이 카탈로그로 쓰는 모든 객체에 태그
  s3.delete-enabled=false  삭제 대신 태그만 단다 (soft delete)
  s3.delete.tags.<k>=<v>   삭제 대상에 붙일 태그
ILM 규칙은 And{Prefix: <tbl>/data/, Tag} 로 걸어 태그 붙은 data 파일만 대상이 되게 한다.

MODE=setup    : 테이블 생성 + 배치 old · new 적재 (DB 는 env)
MODE=tier     : 'tiered' 카탈로그(write tag ilm-tier=warm)로 old 배치만 rewrite_data_files
                → 새 파일이 PUT 즉시 전이(Transition 0d + tag) — Scanner 대기 없음
MODE=softdel  : 'softdel' 카탈로그(delete-enabled=false, delete tag iceberg-deleted=true)로
                old 배치 DELETE → expire_snapshots → 파일은 지워지지 않고 태그만
MODE=check    : 배치별 count · checksum · 전체 스캔 · data 파일 목록

로그: event=ilmtest.tag
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CATALOG, DB, EVENTS_T, LEDGER_T, ROW_CHECKSUM_SQL, Timer, log, spark_session  # noqa: E402
from writer import ensure_tables  # noqa: E402

MODE = os.environ.get("MODE", "check")
ROWS = int(os.environ.get("TAG_ROWS", "100000"))
TBL = EVENTS_T.split(".", 1)[1]   # <db>.<table>


def clone_catalog(spark, name, extra):
    """hive_prod 설정을 복사한 별도 카탈로그 — FileIO 속성(태그)만 다르게."""
    pre = "spark.sql.catalog.{}".format(CATALOG)
    for k, v in spark.sparkContext.getConf().getAll():
        if k == pre or k.startswith(pre + "."):
            spark.conf.set(k.replace(pre, "spark.sql.catalog." + name, 1), v)
    for k, v in extra.items():
        spark.conf.set("spark.sql.catalog.{}.{}".format(name, k), v)
    return name


def setup(spark):
    ensure_tables(spark)
    done = {r["batch_id"] for r in spark.table(LEDGER_T).select("batch_id").collect()}
    now = datetime.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    for b, age_h in (("old", 72), ("new", 0)):
        if b in done:
            continue
        ts = (now - datetime.timedelta(hours=age_h)).strftime("%Y-%m-%d %H:%M:%S")
        df = spark.sql("""SELECT '{b}' AS batch_id, id, timestamp_millis(unix_millis(timestamp'{ts}') + pmod(id, 3600000)) AS event_ts,
                          sha2(concat('{b}', ':', cast(id AS STRING)), 256) AS payload FROM range({n})""".format(b=b, ts=ts, n=ROWS)).repartition(4).cache()
        c = df.selectExpr("sum({}) AS c".format(ROW_CHECKSUM_SQL)).first()["c"]
        df.writeTo(EVENTS_T).option("distribution-mode", "none").append()
        snap = spark.sql("SELECT snapshot_id, committed_at FROM {}.snapshots ORDER BY committed_at DESC LIMIT 1".format(EVENTS_T)).first()
        spark.sql("INSERT INTO {} VALUES ('{}', timestamp'{}', {}, {}, {}, timestamp'{}', 0)".format(
            LEDGER_T, b, ts, ROWS, c, snap["snapshot_id"], snap["committed_at"]))
    return files(spark)


def files(spark, cat=None):
    t = "{}.{}".format(cat or CATALOG, TBL)
    return sorted(r["file_path"].split("/data/", 1)[1] for r in spark.sql("SELECT file_path FROM {}.files".format(t)).collect())


def tier(spark):
    cat = clone_catalog(spark, "tiered", {"s3.write.tags.ilm-tier": "warm"})
    with Timer() as t:
        r = spark.sql("""CALL {c}.system.rewrite_data_files(table => '{t}', where => "batch_id = 'old'",
                         options => map('rewrite-all', 'true', 'min-input-files', '1'))""".format(c=cat, t=TBL)).first().asDict()
    return {"rewrite": r, "rewrite_ms": t.ms, "files_after": files(spark)}


def softdel(spark):
    cat = clone_catalog(spark, "softdel", {"s3.delete-enabled": "false", "s3.delete.tags.iceberg-deleted": "true"})
    before = files(spark)
    with Timer() as t:
        spark.sql("DELETE FROM {}.{} WHERE batch_id = 'old'".format(cat, TBL))
        spark.sql("DELETE FROM {} WHERE batch_id = 'old'".format(LEDGER_T))
        now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        e = spark.sql("CALL {}.system.expire_snapshots(table => '{}', older_than => TIMESTAMP '{}', retain_last => 1)"
                      .format(cat, TBL, now)).first().asDict()
    after = files(spark)
    return {"expire": e, "ms": t.ms, "removed_from_table": sorted(set(before) - set(after)), "files_after": after}


def check(spark):
    ledger = {r["batch_id"]: r for r in spark.table(LEDGER_T).collect()}
    res = {}
    for b in sorted(ledger):
        try:
            c = spark.sql("SELECT count(*) AS c, sum({}) AS s FROM {} WHERE batch_id = '{}'".format(ROW_CHECKSUM_SQL, EVENTS_T, b)).first()
            res[b] = {"ok": c["c"] == ledger[b]["rows"] and c["s"] == ledger[b]["checksum"], "rows": c["c"]}
        except Exception as e:
            res[b] = {"ok": False, "error": str(e).splitlines()[0][:200]}
    try:
        res["full_scan"] = {"ok": True, "rows": spark.sql("SELECT count(*) AS c, sum({}) AS s FROM {}".format(ROW_CHECKSUM_SQL, EVENTS_T)).first()["c"]}
    except Exception as e:
        res["full_scan"] = {"ok": False, "error": str(e).splitlines()[0][:200]}
    return {"result": res, "files": files(spark)}


def main():
    spark = spark_session("ilmtest-tag-" + MODE)
    try:
        out = {"setup": setup, "tier": tier, "softdel": softdel, "check": check}[MODE](spark)
        log("ilmtest.tag", mode=MODE, db=DB, status="ok", **(out if isinstance(out, dict) else {"files": out}))
    except Exception as e:
        log("ilmtest.tag", mode=MODE, db=DB, status="error", error=str(e)[:2000])
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
