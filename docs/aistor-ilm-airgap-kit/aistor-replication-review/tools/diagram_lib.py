"""하나의 다이어그램 스펙에서 draw.io(.drawio)와 Confluence Gliffy(.gliffy)를 동시에 생성한다.

스타일은 AWS 아키텍처 다이어그램(흰 배경, 얇은 컬러 그룹 박스 + 좌상단 배지,
아이콘 + 하단 라벨, 검정 직교 화살표 + 무배경 라벨)을 따른다.
좌표는 모두 절대 좌표(px)이며, 두 포맷에 동일하게 적용된다.
"""
import json
from xml.sax.saxutils import escape

INK = "#232F3E"
MUTED = "#5E6C84"
WHITE = "#FFFFFF"

# 그룹/아이콘 팔레트 (AWS 아키텍처 아이콘 계열 색)
PURPLE = "#8C4FFF"   # k8s 클러스터 / VPC 계열
GREEN = "#7AA116"    # 네트워크 / public subnet 계열
ORANGE = "#ED7100"   # 스토리지 / 레지스트리 계열
BLUE = "#326CE5"     # Kubernetes
RED = "#DD344C"      # 경고 / 충돌
TEAL = "#01A88D"     # 카탈로그
GREY = "#7D8998"
AISTOR = "#C72C48"   # AIStor(MinIO) 브랜드 계열 레드

RES_GLYPH = {"res:glacier": "Tier", "res:route_53": "DNS", "res:elastic_load_balancing": "LB",
             "res:network_firewall": "FW", "res:backup": "Backup"}


def _lines(text):
    return escape(text).replace("\n", "<br>")


class Diagram:
    def __init__(self, name, title, width=1500, height=860, subtitle=None):
        self.name = name
        self.width = width
        self.height = height
        self.groups, self.edges, self.nodes, self.labels = [], [], [], []
        self.bbox = {}
        self._id = 10
        self.text(40, 16, width - 80, 30, title, size=22, bold=True, color="#000000", align="left")
        if subtitle:
            self.text(40, 48, width - 80, 20, subtitle, size=12, color=MUTED, align="left")

    def _nid(self):
        self._id += 1
        return f"c{self._id}"

    # ---------- primitives ----------
    def group(self, gid, x, y, w, h, label, color, badge="", dashed=False, fill=WHITE, stroke=1.5):
        self.bbox[gid] = (x, y, w, h)
        self.groups.append(dict(kind="group", id=gid, x=x, y=y, w=w, h=h, label=label,
                                color=color, badge=badge, dashed=dashed, fill=fill, stroke=stroke))

    def icon(self, iid, cx, cy, label, kind="app", color=BLUE, glyph="", size=52, label_w=150, dim=False,
             dashed=False):
        x, y = cx - size / 2, cy - size / 2
        self.bbox[iid] = (x, y, size, size)
        self.nodes.append(dict(kind="icon", id=iid, x=x, y=y, w=size, h=size, icon=kind,
                               color=GREY if dim else color, glyph=glyph, dim=dim, dashed=dashed))
        if not label:
            return
        nl = label.count("\n") + 1
        self.text(cx - label_w / 2, y + size + 4, label_w, 16 * nl + 4, label, size=12,
                  color=GREY if dim else INK, align="center")

    def box(self, bid, x, y, w, h, text, stroke=INK, fill=WHITE, size=12, bold=False,
            align="center", dashed=False, color=INK, rounded=True):
        self.bbox[bid] = (x, y, w, h)
        self.nodes.append(dict(kind="box", id=bid, x=x, y=y, w=w, h=h, text=text, stroke=stroke,
                               fill=fill, size=size, bold=bold, align=align, dashed=dashed,
                               color=color, rounded=rounded))

    def text(self, x, y, w, h, text, size=12, color=INK, bold=False, align="center", bg=None):
        self.labels.append(dict(kind="text", id=self._nid(), x=x, y=y, w=w, h=h, text=text,
                                size=size, color=color, bold=bold, align=align, bg=bg))

    def step(self, cx, cy, n, color=INK, r=11):
        """번호 배지(원)."""
        self.labels.append(dict(kind="step", id=self._nid(), x=cx - r, y=cy - r, w=2 * r, h=2 * r,
                                text=str(n), color=color))

    def port(self, nid, side, off=0):
        x, y, w, h = self.bbox[nid]
        return {"l": (x, y + h / 2 + off), "r": (x + w, y + h / 2 + off),
                "t": (x + w / 2 + off, y), "b": (x + w / 2 + off, y + h)}[side]

    def edge(self, pts, label=None, at=None, dashed=False, color=INK, both=False, width=1.5,
             label_w=150, label_color=None, arrow=True):
        pts = [tuple(map(float, p)) for p in pts]
        self.edges.append(dict(pts=pts, dashed=dashed, color=color, both=both, width=width, arrow=arrow))
        if label:
            if at is None:  # 가장 긴 세그먼트 중앙
                segs = list(zip(pts, pts[1:]))
                a, b = max(segs, key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
                at = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            nl = label.count("\n") + 1
            h = 15 * nl + 4
            self.text(at[0] - label_w / 2, at[1] - h / 2, label_w, h, label, size=11,
                      color=label_color or color, bg=WHITE)

    # ---------- draw.io ----------
    def _drawio_icon_style(self, n):
        c = n["color"]
        base = ("aspect=fixed;html=1;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
                f"fillColor={c};strokeColor=#ffffff;fontColor={WHITE};")
        k = n["icon"]
        if k == "s3":
            return base + "sketch=0;outlineConnect=0;dashed=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.s3;"
        if k.startswith("res:"):
            return base + f"sketch=0;outlineConnect=0;dashed=0;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{k[4:]};"
        if k in ("bucket", "bucket_obj", "users"):
            shp = {"bucket": "bucket", "bucket_obj": "bucket_with_objects", "users": "users"}[k]
            dash = "dashed=1;" if n.get("dashed") else "dashed=0;"
            return ("sketch=0;outlineConnect=0;html=1;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
                    f"aspect=fixed;pointerEvents=1;fillColor={c};strokeColor=none;{dash}shape=mxgraph.aws4.{shp};")
        if k == "doc":
            dash = "dashed=1;dashPattern=4 3;" if n.get("dashed") else ""
            return (f"shape=note;size=10;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={c};strokeWidth=1.5;"
                    f"{dash}fontColor={c};fontSize=10;fontStyle=1;")
        if k.startswith("k8s:"):
            return base + f"sketch=0;dashed=0;shape=mxgraph.kubernetes.icon;prIcon={k[4:]};"
        if k == "db":
            return (f"shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=8;"
                    f"fillColor={c};strokeColor={c};fontColor={WHITE};fontStyle=1;fontSize=11;")
        if k == "user":
            return (f"shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;"
                    f"fillColor={c};strokeColor={c};")
        # 일반 앱: 둥근 정사각 + 글리프
        return (f"rounded=1;arcSize=14;whiteSpace=wrap;html=1;fillColor={c};strokeColor=none;"
                f"fontColor={WHITE};fontStyle=1;fontSize=12;")

    def to_drawio(self):
        cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']

        def geo(x, y, w, h):
            return f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" as="geometry"/>'

        for g in self.groups:
            dash = "dashed=1;dashPattern=6 4;" if g["dashed"] else ""
            st = (f"rounded=0;whiteSpace=wrap;html=1;fillColor={g['fill']};strokeColor={g['color']};"
                  f"strokeWidth={g['stroke']};{dash}verticalAlign=top;align=left;spacingLeft=34;spacingTop=4;"
                  f"fontSize=13;fontColor={INK};container=0;")
            cells.append(f'<mxCell id="{g["id"]}" value="{escape(_lines(g["label"]))}" style="{st}" '
                         f'vertex="1" parent="1">{geo(g["x"], g["y"], g["w"], g["h"])}</mxCell>')
            if g["badge"] is not None:
                st = (f"rounded=0;html=1;fillColor={g['color']};strokeColor=none;fontColor={WHITE};"
                      "fontSize=11;fontStyle=1;")
                cells.append(f'<mxCell id="{g["id"]}_b" value="{escape(g["badge"])}" style="{st}" vertex="1" '
                             f'parent="1">{geo(g["x"], g["y"], 26, 26)}</mxCell>')

        for i, e in enumerate(self.edges):
            pts = e["pts"]
            dash = "dashed=1;dashPattern=6 4;" if e["dashed"] else ""
            start = "startArrow=block;startFill=1;" if e["both"] else "startArrow=none;"
            end = "endArrow=block;endFill=1;" if e["arrow"] else "endArrow=none;"
            st = (f"html=1;rounded=0;{end}{start}strokeColor={e['color']};"
                  f"strokeWidth={e['width']};{dash}edgeStyle=none;")
            wp = "".join(f'<mxPoint x="{x:.0f}" y="{y:.0f}"/>' for x, y in pts[1:-1])
            wp = f'<Array as="points">{wp}</Array>' if wp else ""
            cells.append(
                f'<mxCell id="e{i}" value="" style="{st}" edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                f'<mxPoint x="{pts[0][0]:.0f}" y="{pts[0][1]:.0f}" as="sourcePoint"/>'
                f'<mxPoint x="{pts[-1][0]:.0f}" y="{pts[-1][1]:.0f}" as="targetPoint"/>{wp}</mxGeometry></mxCell>')

        for n in self.nodes:
            if n["kind"] == "icon":
                val = "" if n["icon"] in ("s3", "user", "bucket", "bucket_obj", "users") or \
                    n["icon"].startswith(("k8s:", "res:")) else n["glyph"]
                cells.append(f'<mxCell id="{n["id"]}" value="{escape(_lines(val))}" style="{self._drawio_icon_style(n)}" '
                             f'vertex="1" parent="1">{geo(n["x"], n["y"], n["w"], n["h"])}</mxCell>')
            else:
                dash = "dashed=1;dashPattern=6 4;" if n["dashed"] else ""
                st = (f"rounded={1 if n['rounded'] else 0};arcSize=8;whiteSpace=wrap;html=1;fillColor={n['fill']};"
                      f"strokeColor={n['stroke']};{dash}fontSize={n['size']};fontColor={n['color']};"
                      f"fontStyle={1 if n['bold'] else 0};align={n['align']};spacing=6;")
                cells.append(f'<mxCell id="{n["id"]}" value="{escape(_lines(n["text"]))}" style="{st}" '
                             f'vertex="1" parent="1">{geo(n["x"], n["y"], n["w"], n["h"])}</mxCell>')

        for t in self.labels:
            if t["kind"] == "step":
                st = (f"ellipse;html=1;fillColor={t['color']};strokeColor={WHITE};strokeWidth=2;fontColor={WHITE};"
                      "fontSize=11;fontStyle=1;align=center;verticalAlign=middle;")
            else:
                bg = f"labelBackgroundColor={t['bg']};" if t["bg"] else ""
                st = (f"text;html=1;whiteSpace=wrap;fontSize={t['size']};fontColor={t['color']};"
                      f"fontStyle={1 if t['bold'] else 0};align={t['align']};verticalAlign=middle;{bg}")
            cells.append(f'<mxCell id="{t["id"]}" value="{escape(_lines(t["text"]))}" style="{st}" '
                         f'vertex="1" parent="1">{geo(t["x"], t["y"], t["w"], t["h"])}</mxCell>')

        return (f'<mxfile host="app.diagrams.net" type="device" version="24.0.0"><diagram name="{escape(self.name)}" '
                f'id="{escape(self.name)}"><mxGraphModel dx="{self.width}" dy="{self.height}" grid="1" gridSize="10" '
                f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
                f'pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0"><root>'
                + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>\n")

    # ---------- Gliffy ----------
    def to_gliffy(self):
        objs = []
        state = {"id": 0}

        def nid():
            state["id"] += 1
            return state["id"]

        def html(text, size, color, bold=False, align="center"):
            w = "font-weight:bold;" if bold else ""
            return (f'<p style="text-align:{align};"><span style="font-size:{size}px;line-height:{size + 3}px;'
                    f'color:{color};{w}">{_lines(text)}</span></p>')

        def text_graphic(h):
            return {"type": "Text", "Text": {"tid": None, "valign": "middle", "overflow": "none",
                                             "vposition": "none", "hposition": "none", "html": h,
                                             "paddingLeft": 4, "paddingRight": 4, "paddingBottom": 3,
                                             "paddingTop": 3}}

        def shape(uid, tid, x, y, w, h, stroke, fill, sw=2, dash=None, text_html=None):
            children = []
            if text_html:
                children.append({"x": 0, "y": 0, "rotation": 0, "id": nid(), "uid": None, "width": w,
                                 "height": h, "lockAspectRatio": False, "lockShape": False, "order": 0,
                                 "graphic": text_graphic(text_html), "linkMap": []})
            objs.append({"x": x, "y": y, "rotation": 0, "id": nid(), "uid": f"com.gliffy.shape.basic.basic_v1.default.{uid}",
                         "width": w, "height": h, "lockAspectRatio": False, "lockShape": False, "order": 0,
                         "graphic": {"type": "Shape", "Shape": {"tid": f"com.gliffy.stencil.{tid}.basic_v1",
                                                                 "strokeWidth": sw, "strokeColor": stroke,
                                                                 "fillColor": fill, "gradient": False,
                                                                 "dashStyle": dash, "dropShadow": False, "state": 0,
                                                                 "opacity": 1, "shadowX": 0, "shadowY": 0}},
                         "children": children, "linkMap": [], "hidden": False})

        def text(x, y, w, h, h_):
            objs.append({"x": x, "y": y, "rotation": 0, "id": nid(),
                         "uid": "com.gliffy.shape.basic.basic_v1.default.text", "width": w, "height": h,
                         "lockAspectRatio": False, "lockShape": False, "order": 0, "graphic": text_graphic(h_),
                         "children": [], "linkMap": [], "hidden": False})

        for g in self.groups:
            shape("rectangle", "rectangle", g["x"], g["y"], g["w"], g["h"], g["color"], g["fill"],
                  sw=g["stroke"], dash="6,4" if g["dashed"] else None)
            if g["badge"] is not None:
                shape("rectangle", "rectangle", g["x"], g["y"], 26, 26, g["color"], g["color"], sw=0,
                      text_html=html(g["badge"], 11, WHITE, True))
            text(g["x"] + 30, g["y"] + 2, g["w"] - 34, 18 * (g["label"].count("\n") + 1) + 4,
                 html(g["label"], 13, INK, False, "left"))

        for e in self.edges:
            xs = [p[0] for p in e["pts"]]
            ys = [p[1] for p in e["pts"]]
            objs.append({"x": 0, "y": 0, "rotation": 0, "id": nid(),
                         "uid": "com.gliffy.shape.basic.basic_v1.default.line",
                         "width": max(xs) - min(xs) or 1, "height": max(ys) - min(ys) or 1,
                         "lockAspectRatio": False, "lockShape": False, "order": 0,
                         "graphic": {"type": "Line", "Line": {
                             "strokeWidth": e["width"], "strokeColor": e["color"], "fillColor": "none",
                             "dashStyle": "6,4" if e["dashed"] else None,
                             "startArrow": 1 if e["both"] else 0, "endArrow": 1 if e["arrow"] else 0,
                             "startArrowRotation": "auto", "endArrowRotation": "auto",
                             "interpolationType": "linear", "cornerRadius": None,
                             "controlPath": [[round(x, 1), round(y, 1)] for x, y in e["pts"]],
                             "lockSegments": {}, "ortho": False}},
                         "children": [], "linkMap": [], "hidden": False,
                         "constraints": {"constraints": [], "startConstraint": None, "endConstraint": None}})

        for n in self.nodes:
            if n["kind"] == "icon":
                k = n["icon"]
                glyph = n["glyph"] or {"s3": "S3", "db": "DB", "user": "User", "k8s:user": "User", "users": "Users",
                                       "k8s:ing": "Ingress", "k8s:job": "Job", "bucket": "Bucket",
                                       "bucket_obj": "Bucket"}.get(k, "") or RES_GLYPH.get(k, "") or (
                    "K8s" if k.startswith("k8s:") else "")
                if k == "doc":
                    shape("rectangle", "rectangle", n["x"], n["y"], n["w"], n["h"], n["color"], WHITE, sw=1.5,
                          dash="4,3" if n.get("dashed") else None, text_html=html(glyph, 10, n["color"], True))
                    continue
                uid, tid = ("ellipse", "ellipse") if k in ("user", "users") else ("round_rectangle", "round_rectangle")
                shape(uid, tid, n["x"], n["y"], n["w"], n["h"], n["color"], n["color"], sw=1,
                      dash="4,3" if n.get("dashed") else None, text_html=html(glyph, 12, WHITE, True))
            else:
                uid, tid = ("round_rectangle", "round_rectangle") if n["rounded"] else ("rectangle", "rectangle")
                shape(uid, tid, n["x"], n["y"], n["w"], n["h"], n["stroke"], n["fill"], sw=1.5,
                      dash="6,4" if n["dashed"] else None,
                      text_html=html(n["text"], n["size"], n["color"], n["bold"], n["align"]))

        for t in self.labels:
            if t["kind"] == "step":
                shape("ellipse", "ellipse", t["x"], t["y"], t["w"], t["h"], WHITE, t["color"], sw=2,
                      text_html=html(t["text"], 11, WHITE, True))
            elif t["bg"]:
                shape("rectangle", "rectangle", t["x"], t["y"], t["w"], t["h"], t["bg"], t["bg"], sw=0,
                      text_html=html(t["text"], t["size"], t["color"], t["bold"], t["align"]))
            else:
                text(t["x"], t["y"], t["w"], t["h"], html(t["text"], t["size"], t["color"], t["bold"], t["align"]))

        for i, o in enumerate(objs):
            o["order"] = i

        return json.dumps({
            "contentType": "application/gliffy+json", "version": "1.3",
            "stage": {"background": WHITE, "width": self.width, "height": self.height, "maxWidth": 5000,
                      "maxHeight": 5000, "nodeIndex": state["id"] + 1, "autoFit": True, "exportBorder": False,
                      "gridOn": True, "snapToGrid": True, "drawingGuidesOn": True, "pageBreaksOn": False,
                      "printGridOn": False, "printPaper": "LETTER", "printShrinkToFit": False,
                      "printPortrait": True, "maxGraphicSize": 5000, "shapeStyles": {}, "lineStyles": {},
                      "textStyles": {}, "themeData": None, "viewportType": "default", "fitBucketToContent": True,
                      "objects": objs,
                      "layers": [{"guid": "baseLayer", "order": 0, "name": "Layer 0", "active": True,
                                  "locked": False, "visible": True, "nodeIndex": 0}]},
            "metadata": {"title": self.name, "revision": 0, "exportBorder": False, "loadPosition": "default",
                         "libraries": ["com.gliffy.libraries.basic.basic_v1.default"], "lastSerialized": None,
                         "analyticsProduct": "Confluence"},
            "embeddedResources": {"index": 0, "resources": []}}, ensure_ascii=False, indent=1)

    # ---------- preview (SVG, 검수용) ----------
    def to_svg(self):
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
             f'font-family="sans-serif"><rect width="100%" height="100%" fill="#fff"/>'
             '<defs><marker id="a" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto-start-reverse">'
             '<path d="M0,0 L10,4 L0,8 z" fill="context-stroke"/></marker></defs>']

        def tx(x, y, w, h, text, size, color, bold=False, align="center"):
            ls = text.split("\n")
            anchor = {"center": "middle", "left": "start"}.get(align, "middle")
            ax = x + w / 2 if anchor == "middle" else x + 4
            y0 = y + h / 2 - (len(ls) - 1) * (size + 3) / 2 + size / 3
            for i, l in enumerate(ls):
                o.append(f'<text x="{ax}" y="{y0 + i * (size + 3)}" font-size="{size}" fill="{color}" '
                         f'text-anchor="{anchor}" font-weight="{"bold" if bold else "normal"}">{escape(l)}</text>')

        for g in self.groups:
            d = ' stroke-dasharray="6 4"' if g["dashed"] else ""
            o.append(f'<rect x="{g["x"]}" y="{g["y"]}" width="{g["w"]}" height="{g["h"]}" fill="{g["fill"]}" '
                     f'stroke="{g["color"]}" stroke-width="{g["stroke"]}"{d}/>')
            if g["badge"] is not None:
                o.append(f'<rect x="{g["x"]}" y="{g["y"]}" width="26" height="26" fill="{g["color"]}"/>')
                tx(g["x"], g["y"], 26, 26, g["badge"], 11, WHITE, True)
            tx(g["x"] + 30, g["y"] + 2, g["w"], 18 * (g["label"].count("\n") + 1) + 4, g["label"], 13, INK,
               False, "left")
        for e in self.edges:
            d = ' stroke-dasharray="6 4"' if e["dashed"] else ""
            ms = ' marker-start="url(#a)"' if e["both"] else ""
            me = ' marker-end="url(#a)"' if e["arrow"] else ""
            pts = " ".join(f"{x},{y}" for x, y in e["pts"])
            o.append(f'<polyline points="{pts}" fill="none" stroke="{e["color"]}" stroke-width="{e["width"]}"'
                     f'{d}{me}{ms}/>')
        for n in self.nodes:
            if n["kind"] == "icon":
                k = n["icon"]
                x, y, w, h, c = n["x"], n["y"], n["w"], n["h"], n["color"]
                dsh = ' stroke-dasharray="4 3"' if n.get("dashed") else ""
                if k in ("bucket", "bucket_obj"):
                    op = ' fill-opacity="0.35"' if n.get("dashed") else ""
                    o.append(f'<path d="M{x},{y + h * .18} L{x + w},{y + h * .18} L{x + w * .84},{y + h} L{x + w * .16},{y + h} Z" '
                             f'fill="{c}"{op}{dsh} stroke="{c}"/>')
                    o.append(f'<ellipse cx="{x + w / 2}" cy="{y + h * .18}" rx="{w / 2}" ry="{h * .12}" fill="#fff" stroke="{c}" stroke-width="2"/>')
                    if k == "bucket_obj":
                        for i, (dx, dy) in enumerate([(.32, .45), (.52, .5), (.42, .68)]):
                            o.append(f'<rect x="{x + w * dx}" y="{y + h * dy}" width="{w * .16}" height="{h * .14}" fill="#fff"/>')
                    continue
                if k == "users":
                    for dx in (.35, .65):
                        o.append(f'<circle cx="{x + w * dx}" cy="{y + h * .3}" r="{w * .13}" fill="{c}"/>')
                        o.append(f'<path d="M{x + w * (dx - .2)},{y + h * .85} Q{x + w * dx},{y + h * .35} {x + w * (dx + .2)},{y + h * .85} Z" fill="{c}"/>')
                    continue
                if k == "doc":
                    o.append(f'<path d="M{x},{y} L{x + w - 10},{y} L{x + w},{y + 10} L{x + w},{y + h} L{x},{y + h} Z" fill="#fff" '
                             f'stroke="{c}" stroke-width="1.5"{dsh}/>')
                    tx(x, y, w, h, n["glyph"], 10, c, True)
                    continue
                glyph = n["glyph"] or {"s3": "S3", "db": "DB", "user": "USER"}.get(k, "") or RES_GLYPH.get(k, "") or (
                    k[4:] if k.startswith("k8s:") else "")
                o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{c}"{dsh}/>')
                tx(x, y, w, h, glyph, 11, WHITE, True)
            else:
                d = ' stroke-dasharray="6 4"' if n["dashed"] else ""
                o.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" rx="{6 if n["rounded"] else 0}" '
                         f'fill="{n["fill"]}" stroke="{n["stroke"]}"{d}/>')
                tx(n["x"], n["y"], n["w"], n["h"], n["text"], n["size"], n["color"], n["bold"], n["align"])
        for t in self.labels:
            if t["kind"] == "step":
                o.append(f'<circle cx="{t["x"] + t["w"] / 2}" cy="{t["y"] + t["h"] / 2}" r="{t["w"] / 2}" fill="{t["color"]}"/>')
                tx(t["x"], t["y"], t["w"], t["h"], t["text"], 11, WHITE, True)
            else:
                if t["bg"]:
                    o.append(f'<rect x="{t["x"]}" y="{t["y"]}" width="{t["w"]}" height="{t["h"]}" fill="{t["bg"]}"/>')
                tx(t["x"], t["y"], t["w"], t["h"], t["text"], t["size"], t["color"], t["bold"], t["align"])
        o.append("</svg>")
        return "\n".join(o)

    def save(self, outdir, preview_dir=None):
        import os
        os.makedirs(outdir, exist_ok=True)
        with open(os.path.join(outdir, f"{self.name}.drawio"), "w", encoding="utf-8") as f:
            f.write(self.to_drawio())
        with open(os.path.join(outdir, f"{self.name}.gliffy"), "w", encoding="utf-8") as f:
            f.write(self.to_gliffy())
        if preview_dir:
            os.makedirs(preview_dir, exist_ok=True)
            with open(os.path.join(preview_dir, f"{self.name}.svg"), "w", encoding="utf-8") as f:
                f.write(self.to_svg())
