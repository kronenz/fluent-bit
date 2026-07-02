#!/usr/bin/env python3
"""icdataops-dev 로그 적재량 대시보드 생성기.

목적: **스토리지 용량 관리** — namespace / app label / pod / 소스(컨테이너·systemd) /
멀티라인별 로그 유입량을 실측해 "수집 시 무엇을 필터링(drop)할지" 판단한다.

datasource: grafana-opensearch-datasource (index pattern `icdataops-dev-log*`).
필드는 Fluent Bit(CRI tail + systemd input) → OpenSearch 파이프라인 실측 기준:
  container(log_source:kubernetes): kubernetes.namespace_name / pod_name /
    container_name / labels.app_kubernetes_io/name, logtag(F=완결·P=분할/부분), stream
  systemd(log_source:systemd): SYSTEMD_UNIT(kubelet.service·containerd.service·etcd.service…),
    SYSLOG_IDENTIFIER, HOSTNAME, MESSAGE
바이트 용량(sum _size)은 mapper-size 플러그인 + _size 매핑이 켜져 있어야 값이 나온다(README 참조).
수정은 이 생성기를 고쳐 재생성한다(손편집 금지)."""
import json

DS = {"type": "grafana-opensearch-datasource", "uid": "${datasource}"}
APP_LABEL = "kubernetes.labels.app_kubernetes_io/name.keyword"  # 앱마다 다르면 여기만 교체
BYTES_UNIT = "decbytes"

# ── 쿼리 블록 ────────────────────────────────────────────────────
def dh(interval="auto", iid="9"):
    return {"id": iid, "type": "date_histogram", "field": "@timestamp",
            "settings": {"interval": interval, "min_doc_count": "0", "trimEdges": "0"}}

def terms(field, size=15, iid="8", order_by="_count"):
    return {"id": iid, "type": "terms", "field": field,
            "settings": {"size": str(size), "order": "desc", "orderBy": order_by, "min_doc_count": "1"}}

def m_count():        return [{"id": "1", "type": "count"}]
def m_bytes():        return [{"id": "1", "type": "sum", "field": "_size"}]
def m_avgbytes():     return [{"id": "1", "type": "avg", "field": "_size"}]
def m_card(field):    return [{"id": "1", "type": "cardinality", "field": field}]

def tgt(query="*", metrics=None, aggs=None, refId="A", hide=False, extra=None):
    t = {"refId": refId, "hide": hide, "datasource": DS, "query": query,
         "queryType": "lucene", "timeField": "@timestamp",
         "metrics": metrics or m_count(), "bucketAggs": aggs if aggs is not None else []}
    if extra:
        t.update(extra)
    return t

# ── 패널 팩토리 ─────────────────────────────────────────────────
_pid = [0]
def pid():
    _pid[0] += 1
    return _pid[0]

def base(ptype, title, desc, x, y, w, h, targets=None, **kw):
    p = {"id": pid(), "type": ptype, "title": title, "description": desc,
         "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": targets or []}
    p.update(kw)
    return p

def text_panel(md, x, y, w, h, title=""):
    return {"id": pid(), "type": "text", "title": title, "transparent": True,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"mode": "markdown", "content": md}}

def stat(title, desc, x, y, w, h, query="*", metrics=None, color="blue", unit="short"):
    return base("stat", title, desc, x, y, w, h, [tgt(query, metrics=metrics, aggs=[dh()])],
        fieldConfig={"defaults": {"unit": unit, "color": {"mode": "fixed", "fixedColor": color},
                                  "noValue": "0"}, "overrides": []},
        options={"reduceOptions": {"calcs": ["sum"], "fields": "", "values": False},
                 "graphMode": "area", "colorMode": "value", "textMode": "value"})

def stat_card(title, desc, x, y, w, h, field, query="*", color="purple"):
    big = {"id": "9", "type": "date_histogram", "field": "@timestamp",
           "settings": {"interval": "1y", "min_doc_count": "0"}}
    return base("stat", title, desc, x, y, w, h, [tgt(query, metrics=m_card(field), aggs=[big])],
        fieldConfig={"defaults": {"unit": "short", "color": {"mode": "fixed", "fixedColor": color},
                                  "noValue": "0"}, "overrides": []},
        options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                 "graphMode": "none", "colorMode": "value", "textMode": "value"})

def timeseries(title, desc, x, y, w, h, targets, unit="short", bars=True):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 1, "fillOpacity": 40,
              "gradientMode": "opacity", "showPoints": "never", "barAlignment": 0,
              "spanNulls": False, "stacking": {"mode": "normal", "group": "A"},
              "axisPlacement": "auto", "axisGridShow": True}
    return base("timeseries", title, desc, x, y, w, h, targets,
        fieldConfig={"defaults": {"unit": unit, "custom": custom,
                                  "color": {"mode": "palette-classic"}}, "overrides": []},
        options={"legend": {"displayMode": "table", "placement": "bottom",
                            "calcs": ["sum", "max"], "showLegend": True},
                 "tooltip": {"mode": "multi", "sort": "desc"}})

def bargauge(title, desc, x, y, w, h, targets, unit="short", color="continuous-BlPu"):
    return base("bargauge", title, desc, x, y, w, h, targets,
        fieldConfig={"defaults": {"unit": unit, "color": {"mode": color},
                     "thresholds": {"mode": "absolute", "steps": [{"color": "blue", "value": None}]}},
                     "overrides": []},
        options={"displayMode": "gradient", "orientation": "horizontal",
                 "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                 "showUnfilled": True, "valueMode": "color", "namePlacement": "left"})

def piechart(title, desc, x, y, w, h, targets, unit="short"):
    return base("piechart", title, desc, x, y, w, h, targets,
        fieldConfig={"defaults": {"unit": unit, "color": {"mode": "palette-classic"}}, "overrides": []},
        options={"pieType": "donut", "displayLabels": ["name", "percent"],
                 "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                 "legend": {"displayMode": "table", "placement": "right",
                            "calcs": ["lastNotNull"], "showLegend": True},
                 "tooltip": {"mode": "single", "sort": "none"}})

def table(title, desc, x, y, w, h, targets, renames, sort_col, color_field=None):
    overrides = []
    if color_field:
        overrides.append({"matcher": {"id": "byName", "options": color_field},
            "properties": [
                {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}},
                {"id": "color", "value": {"mode": "continuous-BlPu"}}]})
    return base("table", title, desc, x, y, w, h, targets,
        fieldConfig={"defaults": {"unit": "short",
            "custom": {"align": "auto", "filterable": True}}, "overrides": overrides},
        options={"showHeader": True, "footer": {"show": True, "reducer": ["sum"], "fields": ""},
                 "sortBy": [{"displayName": sort_col, "desc": True}]},
        transformations=[{"id": "organize", "options": {"renameByName": renames}}])

# ── 변수 ────────────────────────────────────────────────────────
def dsvar():
    return {"name": "datasource", "label": "데이터소스(icdataops-dev-log*)", "type": "datasource",
            "query": "grafana-opensearch-datasource", "current": {}, "hide": 0, "refresh": 1}

def kwvar():
    return {"name": "keyword", "label": "키워드(lucene)", "type": "textbox", "query": "*",
            "current": {"selected": False, "text": "*", "value": "*"}, "hide": 0,
            "options": [{"selected": True, "text": "*", "value": "*"}]}

def dashboard(uid, title, desc, panels):
    return {"uid": uid, "title": title, "description": desc,
            "tags": ["icdataops", "logs", "storage", "capacity"],
            "timezone": "Asia/Seoul", "schemaVersion": 39, "version": 1, "editable": True,
            "graphTooltip": 1, "refresh": "", "time": {"from": "now-6h", "to": "now"},
            "templating": {"list": [dsvar(), kwvar()]}, "panels": panels}

# 소스 필터 lucene (keyword 결합)
def q(*clauses):
    parts = ["(%s)" % c for c in clauses] + ["(${keyword})"]
    return " AND ".join(parts)

KUBE = "log_source:kubernetes"
SYSD = "log_source:systemd"

# ════════════════════════════════════════════════════════════════
HEADER = """## 🗄️ icdataops-dev 로그 적재량 · 스토리지 필터링 분석
**목적: 수집(Fluent Bit) 시 무엇을 drop할지 판단** — 어떤 namespace·app·pod·소스·멀티라인이
스토리지를 많이 먹는지 상위 기여자를 찾습니다. 데이터: OpenSearch `icdataops-dev-log*`.

- **라인수(count)** = 색인 문서 수(≈로그 줄 수). **용량(bytes)** = `sum(_size)` — mapper-size 플러그인이
  켜져 있어야 값이 나옵니다(안 나오면 라인수로 판단 + README의 `_size` 활성 방법 참조).
- 상위 막대/표에서 **값이 크고 운영 가치가 낮은 항목**(access log·debug·헬스체크·과다 로깅 파드)이 1순위 필터 후보.
- 소스: **컨테이너**(`log_source:kubernetes`) vs **systemd**(kubelet·containerd·etcd…). 멀티라인은 `logtag`(P=분할/부분)로 근사."""

def build():
    _pid[0] = 0
    P = []
    P.append(text_panel(HEADER, 0, 0, 24, 5))

    # ── 개요 stat row (y=5) ──
    P.append(stat("전체 라인수", "선택 기간 총 색인 문서(≈줄) 수", 0, 5, 5, 4, q("*"), m_count(), "blue"))
    P.append(stat("컨테이너 라인수", "log_source:kubernetes", 5, 5, 5, 4, q(KUBE), m_count(), "green"))
    P.append(stat("systemd 라인수", "log_source:systemd (kubelet·containerd·etcd…)", 10, 5, 5, 4, q(SYSD), m_count(), "orange"))
    P.append(stat_card("네임스페이스 수", "고유 namespace", 15, 5, 4, 4, "kubernetes.namespace_name.keyword", q(KUBE)))
    P.append(stat("전체 용량(bytes)", "sum(_size) — mapper-size 활성 시", 19, 5, 5, 4, q("*"), m_bytes(), "purple", BYTES_UNIT))

    # ── 소스별 (y=9) ──
    P.append(timeseries("소스별 유입 추이 (라인/시간, 누적)", "컨테이너 vs systemd 유입률 — 급증 구간 = 필터 검토",
        0, 9, 16, 8, [tgt(q("*"), aggs=[terms("log_source.keyword", 5, "2"), dh()])]))
    P.append(piechart("소스 비중 (라인수)", "컨테이너 vs systemd 적재 비중",
        16, 9, 8, 8, [tgt(q("*"), aggs=[terms("log_source.keyword", 5)])]))

    # ── Top 네임스페이스 (y=17) ── 필터 후보 핵심
    P.append(bargauge("Top 네임스페이스 — 라인수 (필터 1순위 후보)", "컨테이너 로그, 상위 15",
        0, 17, 12, 10, [tgt(q(KUBE), aggs=[terms("kubernetes.namespace_name.keyword", 15)])]))
    P.append(table("네임스페이스 요약 (라인·파드수·용량)", "용량은 _size 활성 시",
        12, 17, 12, 10,
        [tgt(q(KUBE), metrics=[{"id": "1", "type": "count"},
                               {"id": "2", "type": "cardinality", "field": "kubernetes.pod_name.keyword"},
                               {"id": "3", "type": "sum", "field": "_size"}],
             aggs=[terms("kubernetes.namespace_name.keyword", 30)])],
        {"kubernetes.namespace_name.keyword": "네임스페이스", "Count": "라인수",
         "Unique Count": "파드수", "Sum _size": "용량(bytes)"},
        sort_col="라인수", color_field="라인수"))

    # ── Top 앱라벨 / Top 파드 (y=27) ──
    P.append(bargauge("Top 앱 라벨 — 라인수", "kubernetes.labels.app_kubernetes_io/name, 상위 15",
        0, 27, 12, 10, [tgt(q(KUBE), aggs=[terms(APP_LABEL, 15)])]))
    P.append(table("Top 파드 — 라인수 (과다 로깅 파드 식별)", "상위 25 · 개별 파드 폭주 탐지",
        12, 27, 12, 10,
        [tgt(q(KUBE), metrics=[{"id": "1", "type": "count"}, {"id": "3", "type": "sum", "field": "_size"}],
             aggs=[terms("kubernetes.pod_name.keyword", 25)])],
        {"kubernetes.pod_name.keyword": "파드", "Count": "라인수", "Sum _size": "용량(bytes)"},
        sort_col="라인수", color_field="라인수"))

    # ── systemd 컴포넌트 (y=37) ──
    P.append(bargauge("systemd 유닛별 라인수 (kubelet·containerd·etcd…)", "log_source:systemd",
        0, 37, 12, 9, [tgt(q(SYSD), aggs=[terms("SYSTEMD_UNIT.keyword", 15)])]))
    P.append(timeseries("systemd 유닛 유입 추이", "노드 컴포넌트 로그 급증 감지",
        12, 37, 12, 9, [tgt(q(SYSD), aggs=[terms("SYSTEMD_UNIT.keyword", 8, "2"), dh()])]))

    # ── 멀티라인 분석 (y=46) ──
    P.append(text_panel(
        "### 🧵 멀티라인 분석 (필터링 판단)\n"
        "`logtag` = CRI 라인 태그: **F=완결 라인**, **P=분할/부분 라인**(런타임이 16KB에서 자르거나 멀티라인 조각). "
        "P 비중·용량이 크면 스택트레이스·대형 로그가 많다는 신호 → 멀티라인 파서/필터 검토 대상.\n"
        "> ⚠️ 파이프라인이 멀티라인을 **조인**하면 조인된 문서는 `logtag=F`가 되어 P로는 안 잡힙니다. "
        "정확한 앱-멀티라인 판별은 파이프라인에 `multiline` 마커 필드 추가 권장(README 참조).",
        0, 46, 24, 3))
    P.append(piechart("logtag 비중 (F 완결 : P 분할)", "P = 멀티라인/분할 조각",
        0, 49, 8, 9, [tgt(q(KUBE), aggs=[terms("logtag.keyword", 5)])]))
    P.append(timeseries("logtag 유입 추이 (F vs P)", "P 급증 = 대형/멀티라인 로그 유입",
        8, 49, 16, 9, [tgt(q(KUBE), aggs=[terms("logtag.keyword", 5, "2"), dh()])]))

    # ── 용량 관점(평균 문서 크기) (y=58) ── 멀티라인/뚱뚱한 로그 식별
    P.append(table("네임스페이스별 평균 문서 크기 (뚱뚱한 로그 = 멀티라인 후보)", "avg(_size) — _size 활성 시. 크면 멀티라인/대형 로그",
        0, 58, 24, 9,
        [tgt(q(KUBE), metrics=[{"id": "1", "type": "avg", "field": "_size"},
                               {"id": "2", "type": "count"}],
             aggs=[terms("kubernetes.namespace_name.keyword", 30, order_by="1")])],
        {"kubernetes.namespace_name.keyword": "네임스페이스", "Average _size": "평균크기(bytes)",
         "Count": "라인수"}, sort_col="평균크기(bytes)", color_field="평균크기(bytes)"))

    return dashboard("icdataops-logvol", "icdataops-dev — 로그 적재량 · 스토리지 필터링 분석",
                     "namespace/app/pod/소스/멀티라인별 로그 적재량으로 수집 필터링(drop) 대상을 판단", P)

if __name__ == "__main__":
    import sys, os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logvol-dashboard.json")
    d = build()
    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"wrote {out}: {len(d['panels'])} panels")
