#!/usr/bin/env python3
"""State snapshot — Hot 버킷의 테이블 prefix 별 storageClass 분포와 전이 기한 초과 객체를 집계한다.

로그: event=ilmtest.state  (J-1: data.overdue == 0, J-2: metadata.transitioned == 0)
필요: mc (MC_HOST_HOT 또는 alias), Python 3.8+

주의 (이전 테스트 함정):
  - mc ls 의 size 는 논리 크기 → 바이트 위치는 storageClass 로만 판단
  - mc ls --versions --json 에는 isLatest 가 없다 → 키별 versionOrdinal 최댓값이 최신
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

HOT = os.environ.get("HOT_ALIAS", "HOT")
BUCKET = os.environ["BUCKET"]
TIER = os.environ.get("TIER_NAME", "WARM-TIER")
PREFIX = os.environ.get("TABLE_PREFIX") or "{}.db/{}".format(os.environ["DB"], os.environ["TABLE"])
TRANSITION_DAYS = int(os.environ.get("TRANSITION_DAYS", "1"))
GRACE_HOURS = int(os.environ.get("SCANNER_GRACE_HOURS", "24"))
SAMPLE = 5
EVIDENCE_DIR = os.environ.get("EVIDENCE_DIR")
# 메트릭 엔드포인트(인증 public 가정) — Prometheus 가 없는 환경에서도 ILM·Scanner 수치를 증적으로 남긴다
METRICS_URLS = [u for u in os.environ.get("HOT_METRICS_URLS", "").split(",") if u]
METRIC_PREFIXES = ("minio_cluster_ilm_", "minio_node_ilm_", "minio_node_scanner_", "minio_cluster_usage_",
                   "minio_bucket_usage_total_bytes", "minio_bucket_usage_object_total")


def mc(*args, check=True):
    r = subprocess.run(["mc"] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=600)
    if check and r.returncode != 0:
        raise RuntimeError("mc {} failed: {}".format(" ".join(args), r.stderr.strip()[:500]))
    return r.stdout


def parse_ts(s):
    # 예: 2026-10-25T09:01:02.123456789+09:00 / ...Z — 소수부는 6자리로 잘라 fromisoformat 호환
    if not s:
        return None
    m = re.match(r"^(.{19})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$", s)
    if not m:
        return None
    frac = "." + (m.group(2) + "000000")[:6] if m.group(2) else ""
    tz = "+00:00" if m.group(3) == "Z" else m.group(3)
    return datetime.datetime.fromisoformat(m.group(1) + frac + tz)


def scan(sub, check_overdue):
    """sub(data/ | metadata/) 아래 모든 버전을 읽어 current/noncurrent/DM 을 분리 집계.

    check_overdue: 전이 기한 초과 판정 여부 (data/ 만 해당 — metadata/ 는 전이 대상이 아니다)
    """
    path = "{}/{}/{}/{}/".format(HOT, BUCKET, PREFIX.rstrip("/"), sub)
    by_key = defaultdict(list)
    for line in mc("ls", "--recursive", "--versions", "--json", path, check=False).splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("status") == "error" or "key" not in o:
            continue
        by_key[o["key"]].append(o)

    now = datetime.datetime.now(datetime.timezone.utc)
    deadline = datetime.timedelta(days=TRANSITION_DAYS, hours=GRACE_HOURS)
    cur = defaultdict(lambda: {"objects": 0, "bytes": 0})
    nonc = defaultdict(lambda: {"objects": 0, "bytes": 0})
    dm = 0
    overdue = []
    oldest_untransitioned = None
    for key, vers in by_key.items():
        vers.sort(key=lambda v: v.get("versionOrdinal", 0))
        for i, v in enumerate(vers):
            latest = i == len(vers) - 1
            if v.get("isDeleteMarker"):
                dm += 1
                continue
            sc = v.get("storageClass") or "STANDARD"
            bucket = cur if latest else nonc
            bucket[sc]["objects"] += 1
            bucket[sc]["bytes"] += int(v.get("size", 0))
            if latest and sc != TIER and check_overdue:
                lm = parse_ts(v.get("lastModified"))
                if lm and (oldest_untransitioned is None or lm < oldest_untransitioned):
                    oldest_untransitioned = lm
                if lm and now - lm > deadline:
                    overdue.append({"key": key, "lastModified": v.get("lastModified"), "storageClass": sc})

    total_cur = sum(x["objects"] for x in cur.values())
    res = {
        "keys": len(by_key),
        "current": dict(cur),
        "noncurrent": dict(nonc),
        "delete_markers": dm,
        "transitioned": cur.get(TIER, {}).get("objects", 0),
        "transitioned_ratio": round(cur.get(TIER, {}).get("objects", 0) / total_cur, 4) if total_cur else None,
    }
    if check_overdue:
        res["overdue"] = len(overdue)
        res["overdue_sample"] = sorted(overdue, key=lambda x: x["lastModified"])[:SAMPLE]
        res["oldest_untransitioned_age_h"] = (
            round((now - oldest_untransitioned).total_seconds() / 3600, 1) if oldest_untransitioned else None)
    return res


def scrape_metrics():
    """ILM/Scanner/용량 계열만 골라 {이름{라벨}: 값} 으로 반환 (노드 합산 없이 원본 그대로)."""
    import urllib.request
    out = {}
    for url in METRICS_URLS:
        try:
            body = urllib.request.urlopen(url, timeout=20).read().decode()
        except Exception as e:  # 메트릭 실패는 state 판정과 무관 — 기록만
            out["_error:" + url] = str(e)[:200]
            continue
        for line in body.splitlines():
            if line.startswith(METRIC_PREFIXES):
                name, _, val = line.rpartition(" ")
                try:
                    out[name] = float(val)
                except ValueError:
                    pass
    return out


def main():
    out = {"event": "ilmtest.state", "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "bucket": BUCKET, "prefix": PREFIX, "tier": TIER, "deadline_h": TRANSITION_DAYS * 24 + GRACE_HOURS}
    try:
        out["data"] = scan("data", check_overdue=True)
        out["metadata"] = scan("metadata", check_overdue=False)
        rules = mc("ilm", "rule", "export", "{}/{}".format(HOT, BUCKET), check=False)
        out["ilm_rules_sha256"] = hashlib.sha256(rules.encode()).hexdigest()[:16]  # 규칙 변경 감지
        out["ilm_rule_ids"] = [r.get("ID") for r in json.loads(rules or "{}").get("Rules", [])] if rules.strip() else []
        # 2023+ mc 는 `mc ilm tier`, 구버전은 `mc admin tier`
        tier = mc("ilm", "tier", "info", HOT, TIER, "--json", check=False) \
            or mc("admin", "tier", "info", HOT, TIER, "--json", check=False)
        out["tier_info"] = [json.loads(l) for l in tier.splitlines() if l.startswith("{")][:3]
        if METRICS_URLS:
            out["metrics"] = scrape_metrics()
        out["status"] = "ok" if out["data"]["overdue"] == 0 and out["metadata"]["transitioned"] == 0 else "warn"
    except Exception as e:
        out.update(status="error", error=str(e)[:2000])
    line = json.dumps(out, ensure_ascii=False, default=str)
    print(line, flush=True)
    if EVIDENCE_DIR:
        with open(os.path.join(EVIDENCE_DIR, "ilmtest.state.jsonl"), "a") as f:
            f.write(line + "\n")
    sys.exit(0 if out["status"] != "error" else 1)


if __name__ == "__main__":
    main()
