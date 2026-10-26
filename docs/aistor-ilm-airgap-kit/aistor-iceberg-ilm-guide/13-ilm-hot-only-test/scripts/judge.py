#!/usr/bin/env python3
"""judge.py <evidence_dir> — 수집한 JSONL 로그에서 J-1 ~ J-6 을 판정해 Markdown 표로 출력한다.

입력: <evidence_dir>/*.jsonl  (collect-evidence.sh 산출물, 한 줄 = 한 이벤트)
J-7(Warm 접근)·J-8(ILM 오류)은 audit log·메트릭 확인 결과를 수기로 기록한다.
"""
import glob
import json
import os
import statistics
import sys


def load(d):
    ev = {"ilmtest.write": [], "ilmtest.verify": [], "ilmtest.state": [], "ilmtest.maintenance": []}
    for f in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            o = o.get("_source", o)          # OpenSearch export 형식 허용
            if o.get("event") in ev:
                ev[o["event"]].append(o)
    for v in ev.values():
        v.sort(key=lambda o: o.get("ts", ""))
    return ev


def p50(xs):
    return int(statistics.median(xs)) if xs else None


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    ev = load(d)
    W, V, S, M = ev["ilmtest.write"], ev["ilmtest.verify"], ev["ilmtest.state"], ev["ilmtest.maintenance"]
    rows = []

    # J-1: 전이가 한 번이라도 일어났고, 마지막 상태에서 기한 초과 미전이 0
    first_tr = next((s for s in S if s.get("data", {}).get("transitioned", 0) > 0), None)
    last = S[-1] if S else None
    if not last:
        rows.append(("J-1", "⏳", "state 이벤트 없음"))
    else:
        ok = first_tr is not None and last["data"]["overdue"] == 0
        rows.append(("J-1", "✅" if ok else ("⏳" if first_tr is None else "❌"),
                     "첫 전이 {} · 최종 전이율 {} · overdue {} (최대 {})".format(
                         first_tr["ts"] if first_tr else "-", last["data"].get("transitioned_ratio"),
                         last["data"]["overdue"], max(s["data"]["overdue"] for s in S if "data" in s))))

    # J-2: metadata/ 전이 0 (전 기간)
    mt = max((s.get("metadata", {}).get("transitioned", 0) for s in S), default=None)
    rows.append(("J-2", "⏳" if mt is None else ("✅" if mt == 0 else "❌"), "metadata 전이 최대 {}건".format(mt)))

    # J-3: 매 주기 정합성
    bad = [v for v in V if v.get("mismatched") or v.get("missing") or v.get("extra") or v.get("status") == "error"]
    rows.append(("J-3", "⏳" if not V else ("✅" if not bad else "❌"),
                 "verify {}회 중 불일치 {}회".format(len(V), len(bad))))

    # J-4: 전이 이후 old_read / timetravel 성공
    after = [v for v in V if first_tr and v["ts"] >= first_tr["ts"]]
    old_ok = [v for v in after if v.get("old_read", {}).get("ok") is True]
    old_ng = [v for v in after if v.get("old_read", {}).get("ok") is False]
    tt_ng = [v for v in after if v.get("timetravel", {}).get("ok") is False]
    rows.append(("J-4", "⏳" if not old_ok else ("✅" if not old_ng and not tt_ng else "❌"),
                 "전이 후 old_read 성공 {} / 실패 {} · time travel 실패 {}".format(len(old_ok), len(old_ng), len(tt_ng))))

    # J-5: Writer 실패 0, 전이 전/후 write_ms 비교
    fails = [w for w in W if w.get("status") == "fail"]
    ok_w = [w for w in W if w.get("status") == "ok"]
    pre = [w["write_ms"] for w in ok_w if not first_tr or w["ts"] < first_tr["ts"]]
    post = [w["write_ms"] for w in ok_w if first_tr and w["ts"] >= first_tr["ts"]]
    rows.append(("J-5", "⏳" if not W else ("✅" if not fails else "❌"),
                 "write {}회 · 실패 {} · write_ms p50 전이 전 {} / 후 {}".format(len(W), len(fails), p50(pre), p50(post))))

    # J-6: 유지보수
    m_fail = [m for m in M if m.get("status") == "fail"]
    rows.append(("J-6", "⏳" if not M else ("✅" if not m_fail else "❌"),
                 "maintenance 이벤트 {} · 실패 {}".format(len(M), len(m_fail))))

    # 참고: 읽기 지연
    old_ms = [v["old_read"]["ms"] for v in after if v.get("old_read", {}).get("ms") is not None]
    rec_ms = [v["recent_read_ms"] for v in V if v.get("recent_read_ms") is not None]
    rows.append(("참고", "—", "읽기 p50: 최근 배치(hot) {} ms · 전이 배치(warm) {} ms".format(p50(rec_ms), p50(old_ms))))

    print("| # | 판정 | 근거 |\n|---|---|---|")
    for r in rows:
        print("| {} | {} | {} |".format(*r))
    print("\n기간: {} ~ {} · 증적: {}".format(
        min((x["ts"] for x in W + V + S), default="-"), max((x["ts"] for x in W + V + S), default="-"), d))


if __name__ == "__main__":
    main()
