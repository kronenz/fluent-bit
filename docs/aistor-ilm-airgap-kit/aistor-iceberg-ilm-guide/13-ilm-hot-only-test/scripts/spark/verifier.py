"""Verifier — ledger 와 실제 테이블을 대조하고, 전이됐을 오래된 데이터·스냅샷을 조회한다.

로그: event=ilmtest.verify
  J-3: mismatched / missing / extra == 0
  J-4: old_read.ok, timetravel.ok  (전이 기한이 지난 배치·가장 오래된 스냅샷)
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (EVENTS_T, LEDGER_T, ROW_CHECKSUM_SQL, Timer, log,  # noqa: E402
                    spark_session)

TRANSITION_DAYS = int(os.environ.get("TRANSITION_DAYS", "1"))
GRACE_HOURS = int(os.environ.get("SCANNER_GRACE_HOURS", "24"))


def main():
    spark = spark_session("ilmtest-verifier")
    out = {"status": "ok"}
    try:
        ledger = {r["batch_id"]: r for r in spark.table(LEDGER_T).collect()}

        # ── J-3 전체 정합성 ───────────────────────────────
        with Timer() as t:
            actual = {r["batch_id"]: r for r in spark.sql("""
                SELECT batch_id, count(*) AS rows, sum({}) AS checksum
                FROM {} GROUP BY batch_id""".format(ROW_CHECKSUM_SQL, EVENTS_T)).collect()}
        mismatched = [b for b in ledger if b in actual and
                      (actual[b]["rows"] != ledger[b]["rows"] or actual[b]["checksum"] != ledger[b]["checksum"])]
        missing = [b for b in ledger if b not in actual]
        extra = [b for b in actual if b not in ledger]
        out.update(batches=len(ledger), mismatched=len(mismatched), missing=len(missing), extra=len(extra),
                   mismatched_sample=mismatched[:5], missing_sample=missing[:5], full_scan_ms=t.ms)

        # ── J-4a 전이 기한이 지난 배치만 조회 (= warm 에서 읽히는 파일) ──
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=TRANSITION_DAYS, hours=GRACE_HOURS)
        old = [b for b, r in ledger.items() if r["batch_start"] < cutoff]
        if old:
            lo, hi = min(old), max(old)
            expected = sum(ledger[b]["rows"] for b in old)
            with Timer() as t:
                got = spark.sql("SELECT count(*) AS c FROM {} WHERE batch_id BETWEEN '{}' AND '{}'"
                                .format(EVENTS_T, lo, hi)).first()["c"]
            out["old_read"] = {"ok": got == expected, "batches": len(old), "expected": expected,
                               "got": got, "ms": t.ms}
        else:
            out["old_read"] = {"ok": None, "reason": "전이 기한이 지난 배치 없음"}

        # ── J-4b 가장 오래된 스냅샷 time travel ──────────────
        snap = spark.sql("SELECT snapshot_id, committed_at FROM {}.snapshots ORDER BY committed_at LIMIT 1"
                         .format(EVENTS_T)).first()
        if snap:
            expected = sum(r["rows"] for r in ledger.values() if r["committed_at"] <= snap["committed_at"])
            with Timer() as t:
                got = spark.sql("SELECT count(*) AS c FROM {} VERSION AS OF {}"
                                .format(EVENTS_T, snap["snapshot_id"])).first()["c"]
            # expire_snapshots 이후 가장 오래된 스냅샷은 여러 배치를 포함할 수 있다 — ledger 누적치와 비교
            out["timetravel"] = {"ok": got == expected, "snapshot_id": snap["snapshot_id"],
                                 "committed_at": snap["committed_at"], "expected": expected,
                                 "got": got, "ms": t.ms}

        # ── 참고: 최근 배치 읽기 지연 (hot 데이터 기준선) ──────
        latest = max(ledger) if ledger else None
        if latest:
            with Timer() as t:
                spark.sql("SELECT count(*) FROM {} WHERE batch_id = '{}'".format(EVENTS_T, latest)).first()
            out["recent_read_ms"] = t.ms

        bad = out["mismatched"] or out["missing"] or out["extra"] \
            or out["old_read"].get("ok") is False or out.get("timetravel", {}).get("ok") is False
        out["status"] = "fail" if bad else "ok"
        log("ilmtest.verify", **out)
        if bad:
            sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:
        log("ilmtest.verify", status="error", error=str(e)[:2000], **{k: v for k, v in out.items() if k != "status"})
        raise
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
