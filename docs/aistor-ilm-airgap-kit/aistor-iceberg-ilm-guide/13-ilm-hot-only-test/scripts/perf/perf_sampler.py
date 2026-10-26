#!/usr/bin/env python3
"""perf_sampler.py — 기존 버킷에 규칙을 건 뒤 전이 진행과 Hot 부하를 일정 간격으로 기록한다 (toolbox 에서 실행).

매 SAMPLE_SEC 초:
  - 대상 prefix(PERF_PREFIX/data/) current 객체 storageClass 분포 (mc ls --recursive --json)
  - Hot 메트릭: ILM 전이 대기/진행 · 전이 누적 · scanner 누적 · tier 요청 · 프로세스 CPU/RSS
전부 전이되면(STANDARD 0) DONE_HOLD 회 더 찍고 끝낸다. EVIDENCE_DIR/STOP_SAMPLER 파일로도 멈춘다.

로그: event=ilmtest.perfsample  (EVIDENCE_DIR/ilmtest.perfsample.jsonl)
"""
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

HOT = os.environ.get("HOT_ALIAS", "HOT")
BUCKET = os.environ.get("BUCKET", "warehouse")
PREFIX = os.environ["PERF_PREFIX"].rstrip("/") + "/data/"
URLS = [u for u in os.environ.get("HOT_METRICS_URLS", "").split(",") if u]
SAMPLE_SEC = int(os.environ.get("SAMPLE_SEC", "15"))
MAX_SEC = int(os.environ.get("SAMPLER_MAX_SEC", str(6 * 3600)))
DONE_HOLD = int(os.environ.get("DONE_HOLD", "8"))
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR", ".")
KEEP = ("minio_node_ilm_transition_", "minio_node_ilm_action_count_transition", "minio_node_scanner_",
        "minio_node_ilm_versions_scanned", "minio_node_tier_requests_", "minio_node_process_cpu_total_seconds",
        "minio_node_process_resident_memory_bytes", "minio_cluster_ilm_transitioned_")


def metrics():
    out = {}
    for u in URLS:
        try:
            body = urllib.request.urlopen(u, timeout=10).read().decode()
        except Exception as e:
            out["error:" + u] = str(e)[:200]
            continue
        for line in body.splitlines():
            if line.startswith("#") or not line.startswith(KEEP):
                continue
            name, _, val = line.rpartition(" ")
            try:
                out[name] = out.get(name, 0) + float(val)
            except ValueError:
                pass
    return out


def classes():
    r = subprocess.run(["mc", "ls", "--recursive", "--json", "{}/{}/{}".format(HOT, BUCKET, PREFIX)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    c = {}
    for line in r.stdout.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "file":
            sc = o.get("storageClass") or "STANDARD"
            c[sc] = c.get(sc, 0) + 1
    return c


def main():
    t0 = time.time()
    hold = 0
    path = os.path.join(EVIDENCE_DIR, "ilmtest.perfsample.jsonl")
    while time.time() - t0 < MAX_SEC and not os.path.exists(os.path.join(EVIDENCE_DIR, "STOP_SAMPLER")):
        s0 = time.time()
        c = classes()
        rec = {"event": "ilmtest.perfsample", "ts": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
               "elapsed_s": int(s0 - t0), "prefix": PREFIX, "classes": c,
               "standard": c.get("STANDARD", 0), "total": sum(c.values()), "list_ms": int((time.time() - s0) * 1000),
               "metrics": metrics()}
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()
        with open(path, "a") as f:
            f.write(line)
        if rec["total"] and rec["standard"] == 0:
            hold += 1
            if hold > DONE_HOLD:
                break
        time.sleep(max(0, SAMPLE_SEC - (time.time() - s0)))


if __name__ == "__main__":
    main()
