#!/usr/bin/env python3
"""exp_report.py <evidence_dir> — 기한 삭제 시험(E-1 ~ E-5) 결과를 Markdown 으로 요약한다.

입력: ilmtest.expobj.jsonl (exp-object-test.sh status) · ilmtest.expread.jsonl (verify) · ilmtest.exp.jsonl (exp_iceberg.py)
      expiry-schedule.txt (선택, mc stat 의 Expiration 시각)
"""
import glob
import json
import os
import sys

# E-1/E-2 기대값 — EXPIRE_DAYS=5, Noncurrent 1d 기준 (age 는 생성 후 경과일)
EXPECT = {
    "versioned": {"age-0.5": "STANDARD", "age-2": "WARM", "age-4.5": "WARM", "age-6": "DM(+비현행)", "nc": "WARM(v1 삭제)", "ow": "STANDARD(+비현행 WARM)"},
    "unversioned": {"age-0.5": "STANDARD", "age-2": "WARM", "age-4.5": "WARM", "age-6": "삭제"},
}


def load(d, name):
    out = []
    for f in glob.glob(os.path.join(d, name)):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return sorted(out, key=lambda o: o.get("ts", ""))


def show(vs):
    if not vs:
        return "(없음)"
    return " → ".join(("DM" if v["dm"] else v["sc"]) for v in vs)   # 최신 → 이전 버전


def main():
    d = sys.argv[1]
    O = load(d, "ilmtest.expobj.jsonl")
    print("## E-1 / E-2 객체 단위 (최신 → 이전 버전)\n")
    if O:
        last = next((o for o in reversed(O) if o["phase"] in ("after-expire", "after-iceberg", "hourly")), O[-1])
        print("기준 시각 {} ({})\n".format(last["ts"], last["phase"]))
        names = list(last["buckets"])
        print("| 키 | Versioning ON (`{}`) | 기대 | Versioning OFF (`{}`) | 기대 |".format(names[0], names[1] if len(names) > 1 else "-"))
        print("|---|---|---|---|---|")
        keys = sorted(set(k for b in last["buckets"].values() for k in b) | set(EXPECT["versioned"]))
        for k in keys:
            vb = last["buckets"][names[0]].get(k)
            nb = last["buckets"][names[1]].get(k) if len(names) > 1 else None
            print("| `{}` | {} | {} | {} | {} |".format(k, show(vb), EXPECT["versioned"].get(k, "-"), show(nb),
                                                    EXPECT["unversioned"].get(k, "-")))
        print("\n| 시각 | 단계 | Warm `exp/` 객체 | Warm `expi/` 객체 |\n|---|---|---|---|")
        prev = None
        for o in O:
            cur = (o.get("warm_exp_objects"), o.get("warm_expi_objects"))
            if cur != prev or o["phase"] != "hourly":
                print("| {} | {} | {} | {} |".format(o["ts"], o["phase"], *cur))
            prev = cur
    R = load(d, "ilmtest.expread.jsonl")
    if R:
        print("\n### 전이된 비현행 버전 읽기\n\n| 키 | 사유 | storageClass | 읽기 |\n|---|---|---|---|")
        for k, c in R[-1]["cases"].items():
            print("| `{}` | {} | {} | {} |".format(k, c.get("why"), c.get("storageClass"),
                                               "✅" if c.get("readable") else "❌ " + str(c.get("error"))))
    E = load(d, "ilmtest.exp.jsonl")
    if E:
        print("\n## E-3 / E-4 Iceberg\n\n| 시각 | 테이블 | 단계 | age0 | age2 | age6 | 전체 스캔 | 가장 오래된 스냅샷 | 비고 |")
        print("|---|---|---|---|---|---|---|---|---|")
        for e in E:
            t = e["table"].split(".", 1)[1]
            if e.get("mode") == "check" and "result" in e:
                r = e["result"]
                cell = lambda k: "-" if k not in r else ("✅ {}".format(r[k].get("rows", "")) if r[k].get("ok") else "❌")
                err = next((r[k].get("error") for k in ("age6", "full_scan") if k in r and r[k].get("error")), "")
                print("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                    e["ts"], t, e["phase"], cell("age0"), cell("age2"), cell("age6"), cell("full_scan"),
                    cell("timetravel_oldest"), "data 파일 {}{}".format(r.get("data_files"), " · " + err[:80] if err else "")))
            elif e.get("mode") == "retention":
                print("| {} | {} | {} | — | — | — | — | — | DELETE {} · expire_snapshots 삭제 파일 {} |".format(
                    e["ts"], t, e["phase"], e.get("delete_summary"), (e.get("expire") or {}).get("deleted_data_files_count")))
        print("\n| 시각 | 단계 | " + " | ".join(sorted({p for o in O for p in o.get("iceberg", {})})) + " |")
        cols = sorted({p for o in O for p in o.get("iceberg", {})})
        print("|---|---|" + "---|" * len(cols))
        prev = None
        for o in O:
            if "iceberg" not in o:
                continue
            cells = []
            for p in cols:
                parts = o["iceberg"].get(p, {})
                cells.append(" · ".join("{}: {}".format(k.split("=")[-1], ",".join("{} {}".format(n, c) for c, n in sorted(v.items())))
                                        for k, v in sorted(parts.items())))
            if cells != prev:
                print("| {} | {} | {} |".format(o["ts"], o["phase"], " | ".join(cells)))
            prev = cells
    sched = os.path.join(d, "expiry-schedule.txt")
    if os.path.exists(sched):
        print("\n## 만료 예정 시각 (`mc stat`, Versioning ON 버킷)\n\n```\n" + open(sched).read().strip() + "\n```")


if __name__ == "__main__":
    main()
