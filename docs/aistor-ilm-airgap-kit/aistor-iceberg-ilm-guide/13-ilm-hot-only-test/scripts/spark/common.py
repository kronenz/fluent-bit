"""ilmtest Spark Job 공통 — 설정·로그 헬퍼.

Spark 카탈로그 설정은 run-spark.sh 의 --conf 로 주입한다 (06장 §2 기준, S3FileIO · Hot 엔드포인트만).
apache/spark:3.5.x 의 Python 은 3.8 이므로 typing 은 구식 문법을 쓴다.
"""
import datetime
import json
import os
import sys
import time

CATALOG = os.environ.get("CATALOG", "hive_prod")
DB = os.environ.get("DB", "ilmtest")
TABLE = os.environ.get("TABLE", "events")
LEDGER = os.environ.get("LEDGER_TABLE", "ledger")

BUCKET = os.environ.get("BUCKET", "warehouse")

EVENTS_T = "{}.{}.{}".format(CATALOG, DB, TABLE)
LEDGER_T = "{}.{}.{}".format(CATALOG, DB, LEDGER)
# HMS 네임스페이스 위치는 file: 이라(HMS 함정) 테이블 위치를 S3 로 명시한다 → ILM prefix 와 1:1
EVENTS_LOC = "s3://{}/{}.db/{}".format(BUCKET, DB, TABLE)
LEDGER_LOC = "s3://{}/{}.db/{}".format(BUCKET, DB, LEDGER)

# 행 checksum: 배치·행 단위로 결정적이고, ANSI 모드에서도 overflow 없이 합산되도록 pmod 로 축소
ROW_CHECKSUM_SQL = "pmod(xxhash64(batch_id, id, payload), 1000000007)"


def now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR")   # 공유 볼륨(RWX) — Pod 로그 수집이 없을 때의 증적 경로


def log(event, **fields):
    """한 줄 JSON 을 stdout(Fluent Bit 수집용)과 EVIDENCE_DIR/<event>.jsonl 에 남긴다.
    Spark 자체 로그는 stderr 로 가므로 섞이지 않는다."""
    rec = {"event": event, "ts": now_iso(), "table": EVENTS_T}
    rec.update(fields)
    line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    if EVIDENCE_DIR:
        with open(os.path.join(EVIDENCE_DIR, event + ".jsonl"), "a") as f:
            f.write(line)


class Timer(object):
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.time() - self.t0) * 1000)
        return False


def spark_session(app):
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.appName(app).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
