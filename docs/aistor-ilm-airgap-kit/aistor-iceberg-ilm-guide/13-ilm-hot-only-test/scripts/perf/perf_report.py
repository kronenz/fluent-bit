#!/usr/bin/env python3
"""perf_report.py <evidence_dir> [top.txt] — 성능·부하(P-*) · 영향도(I-*) 결과를 Markdown 으로 요약한다.

입력 (evidence_dir):
  ilmtest.perfphase.jsonl  : 구간 경계 (rule-applied 등, 수동 기록)
  ilmtest.perfsample.jsonl : 전이 진행 · Hot 메트릭 (perf_sampler.py)
  ilmtest.probe.jsonl      : 쓰기·읽기 지연 (perf_probe.py)
  ilmtest.schema.jsonl     : Iceberg 정의 (schema_check.py)
  ilmtest.hms.jsonl        : HMS 정의 (hms_snapshot.sh)
  top.txt (선택)           : "<ts> <pod> <cpu>m <mem>Mi" (kubectl top 기록)
"""
import datetime
import glob
import json
import os
import statistics
import sys


def load(d, name):
    out = []
    for f in glob.glob(os.path.join(d, name)):
        for line in open(f, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return sorted(out, key=lambda o: o.get("ts", ""))


def ts(s):
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def fmt(v):
    return "-" if v is None else str(v)


def main():
    d = sys.argv[1]
    top = sys.argv[2] if len(sys.argv) > 2 else None
    phases = {p["phase"]: p for p in load(d, "ilmtest.perfphase.jsonl")}
    S = load(d, "ilmtest.perfsample.jsonl")
    P = load(d, "ilmtest.probe.jsonl")
    print("## P-1 전이 진행 (기존 객체)\n")
    applied = phases.get("rule-applied", {}).get("ts")
    if applied and S:
        t0 = ts(applied)
        after = [s for s in S if s["ts"] >= applied]
        total0 = max((s["total"] for s in after), default=0)
        marks = {}
        for s in after:
            done = s["total"] - s["standard"]
            for q in (0.01, 0.5, 0.9, 1.0):
                if q not in marks and s["total"] and done >= q * s["total"]:
                    marks[q] = s
        print("| 지점 | 시각 (UTC) | 규칙 적용 후 | 전이/전체 |\n|---|---|---|---|")
        print("| 규칙 적용 | {} | 0 s | - |".format(applied))
        for q, s in sorted(marks.items()):
            print("| {:.0f}% | {} | {} s | {}/{} |".format(q * 100, s["ts"], int((ts(s["ts"]) - t0).total_seconds()),
                                                        s["total"] - s["standard"], s["total"]))
        if 0.01 in marks and 1.0 in marks:
            dt = (ts(marks[1.0]["ts"]) - ts(marks[0.01]["ts"])).total_seconds() or 1
            print("\n처리율(1%→100%): {:.1f} 객체/s · 대상 {} 객체".format(total0 / dt, total0))
        m0, m1 = after[0]["metrics"], after[-1]["metrics"]
        keys = sorted(k for k in m1 if k.startswith(("minio_node_scanner_objects_scanned", "minio_node_scanner_bucket_scans_finished",
                                                     "minio_node_ilm_action_count_transition", "minio_node_tier_requests",
                                                     "minio_node_ilm_transition_missed")))
        print("\n| 메트릭 (규칙 적용 후 증가분) | 값 |\n|---|---|")
        for k in keys:
            print("| `{}` | {:g} |".format(k, m1.get(k, 0) - m0.get(k, 0)))
        pend = [s["metrics"].get("minio_node_ilm_transition_pending_tasks", 0) for s in after]
        act = [s["metrics"].get("minio_node_ilm_transition_active_tasks", 0) for s in after]
        print("| 전이 대기 작업 최대 | {:g} |\n| 전이 진행 작업 최대 | {:g} |".format(max(pend or [0]), max(act or [0])))
        # Hot 프로세스 CPU (MinIO 자체 메트릭, 구간 평균 코어)
        print("\n| 구간 | Hot CPU 평균 (코어, MinIO 메트릭) |\n|---|---|")
        for name, lo, hi in segments(phases, S):
            seg = [s for s in S if lo <= s["ts"] < hi and cpu(s) is not None]
            if len(seg) >= 2:
                dc = cpu(seg[-1]) - cpu(seg[0])
                dt = (ts(seg[-1]["ts"]) - ts(seg[0]["ts"])).total_seconds() or 1
                print("| {} | {:.3f} |".format(name, dc / dt))
    else:
        print("규칙 적용 기록(rule-applied) 또는 sample 없음")

    print("\n## P-2 / P-3 쓰기·읽기 지연 (구간별, ms)\n")
    print("| 구간 | 회 | 오류 | write p50/p95 | 고정 파티션 읽기 p50/p95 | 메타데이터 조회 p50 | 전체 스캔 p50 | 정합성 |")
    print("|---|---|---|---|---|---|---|---|")
    for ph in sorted({p.get("phase") for p in P}, key=lambda x: min(p["ts"] for p in P if p.get("phase") == x)):
        xs = [p for p in P if p.get("phase") == ph]
        ok = [p for p in xs if p.get("status") != "error"]
        w = [p["write_ms"] for p in ok if "write_ms" in p]
        r = [p["part_read_ms"] for p in ok if "part_read_ms" in p]
        m = [p["meta_ms"] for p in ok if "meta_ms" in p]
        f = [p["full_scan_ms"] for p in ok if "full_scan_ms" in p]
        fo = [p["full_ok"] for p in ok if "full_ok" in p]
        print("| {} | {} | {} | {}/{} | {}/{} | {} | {} | {} |".format(
            ph, len(xs), len(xs) - len(ok), fmt(pct(w, .5)), fmt(pct(w, .95)), fmt(pct(r, .5)), fmt(pct(r, .95)),
            fmt(pct(m, .5)), fmt(pct(f, .5)), "{}/{} 일치".format(sum(1 for x in fo if x), len(fo)) if fo else "-"))

    if top and os.path.exists(top):
        print("\n## P-4 Pod 자원 (kubectl top, 구간별 평균/최대)\n")
        rows = []
        for line in open(top):
            p = line.split()
            if len(p) == 4:
                rows.append((p[0], p[1].rsplit("-", 2)[0] if not p[1].startswith("minio") else p[1], int(p[2].rstrip("m")), int(p[3].rstrip("Mi"))))
        print("| 구간 | Pod | CPU 평균/최대 (m) | 메모리 최대 (Mi) |\n|---|---|---|---|")
        for name, lo, hi in segments(phases, S):
            for pod in ("minio-hot-0", "minio-warm-0"):
                seg = [r for r in rows if r[1] == pod and lo <= r[0] < hi]
                if seg:
                    print("| {} | {} | {}/{} | {} |".format(name, pod, int(statistics.mean(r[2] for r in seg)),
                                                           max(r[2] for r in seg), max(r[3] for r in seg)))

    print("\n## 영향도 (I-*)\n")
    for name, f, keys in (("Iceberg (Spark)", "ilmtest.schema.jsonl", ("schema_sha", "partitioning", "location", "props_sha", "pinned_files", "pinned_files_sha")),
                          ("HMS", "ilmtest.hms.jsonl", ("tbl_type", "location", "columns", "formats", "params_sha", "metadata_location_prefix"))):
        X = load(d, f)
        if not X:
            continue
        print("| {} | ".format(name) + " | ".join(x.get("phase", "-") for x in X) + " | 동일 |")
        print("|---|" + "---|" * (len(X) + 1))
        for k in keys:
            vals = [json.dumps(x.get(k), ensure_ascii=False) for x in X]
            print("| `{}` | ".format(k) + " | ".join(v[:60] for v in vals) + " | {} |".format("✅" if len(set(vals)) == 1 else "❌"))
        ev = [x["evolve"] for x in X if "evolve" in x]
        if ev:
            print("\n스키마 변경 시험: " + json.dumps(ev[-1], ensure_ascii=False))
        print()


def cpu(s):
    v = [x for k, x in s["metrics"].items() if k.startswith("minio_node_process_cpu_total_seconds")]
    return sum(v) if v else None


def segments(phases, S):
    """baseline(규칙 전) · transition(규칙 적용 ~ 전이 완료) · post(전이 완료 후)"""
    a = phases.get("rule-applied", {}).get("ts")
    done = phases.get("transition-done", {}).get("ts")
    if not done and a:
        done = next((s["ts"] for s in S if s["ts"] >= a and s["total"] and s["standard"] == 0), None)
    end = "9999"
    out = [("baseline", "0000", a or end)]
    if a:
        out.append(("transition", a, done or end))
    if done:
        out.append(("post", done, end))
    return out


if __name__ == "__main__":
    main()
