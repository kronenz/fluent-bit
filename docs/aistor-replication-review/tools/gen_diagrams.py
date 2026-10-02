"""aistor-replication-review 다이어그램 생성기.

실행: python3 tools/gen_diagrams.py   (aistor-replication-review/ 에서)
산출: 각 카테고리 diagrams/ 아래 *.drawio, *.gliffy, *.svg(미리보기)
"""
import os

from diagram_lib import (AISTOR, BLUE, GREEN, GREY, INK, MUTED, ORANGE, PURPLE, RED, TEAL, WHITE, Diagram)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARK, TRINO, ORACLE, POLARIS = "#E25A1C", "#DD00A1", "#C74634", "#1F6FEB"
TIER, WARMC = "#5A6B86", "#8A1C2E"


def chips(d, y, items, w=225, gap=12, x0=40, color=RED, h=46):
    for i, t in enumerate(items):
        d.box(f"chip{y}_{i}", x0 + i * (w + gap), y, w, h, t, stroke=color, fill=WARN_FILL, color=color, size=12, bold=True)
WARN_FILL = "#FFF1F0"


def legend(d, y, items):
    x = 40
    for text, color, dashed in items:
        d.edge([(x, y), (x + 40, y)], dashed=dashed, color=color, arrow=True)
        d.text(x + 44, y - 10, 230, 20, text, size=11, color=MUTED, align="left")
        x += 280


# ---------------------------------------------------------------- 01
def d01():
    d = Diagram("01-hot-warm-icheon-dataops",
                "이천 Hot/Warm AIStor ↔ 이천 dataops 클러스터 연결 아키텍처",
                width=1560, height=920,
                subtitle="AIStor(상용 S3)와 dataops는 같은 이천 베어메탈 k8s 환경 · Private=Cilium ClusterMesh+BGP · Public=Ingress 또는 L4 스위치 VIP")

    d.icon("raw", 110, 230, "RAW 원천\n(설비·로그·파일)", glyph="RAW", color=ORANGE)
    d.icon("eng", 110, 420, "데이터 엔지니어\n(Spark/Trino 사용자)", kind="k8s:user", color=BLUE)
    d.icon("adm", 110, 700, "플랫폼 관리자\n(k8s·AIStor admin)", kind="k8s:user", color=BLUE)

    d.group("idc", 220, 90, 1130, 760, "이천 IDC · 베어메탈 Kubernetes (Private 대역)", INK, badge="IDC")

    d.group("dataops", 250, 140, 320, 680, "이천 dataops 클러스터", PURPLE, badge="k8s")
    d.icon("spark", 330, 230, "Spark on K8s\n(적재·ETL·유지보수)", glyph="Spark", color=SPARK)
    d.icon("trino", 330, 420, "Trino\n(조회)", glyph="Trino", color=TRINO)
    d.icon("hms", 490, 330, "Hive Metastore\n(Hot 카탈로그)", glyph="HMS", color=TEAL, label_w=130)
    d.icon("ora", 490, 560, "HMS DB\n(Oracle)", kind="db", glyph="Oracle", color=ORACLE)
    d.edge([(356, 222), (410, 222), (410, 322), (464, 322)])
    d.edge([(356, 420), (430, 420), (430, 342), (464, 342)], "Thrift :9083", at=(430, 460), label_w=90)
    d.edge([(490, 402), (490, 532)], "JDBC", at=(490, 470), label_w=50)

    d.group("net", 600, 140, 210, 680, "Private 네트워크\n(Cilium)", GREEN, badge="⇄")
    d.icon("mesh", 705, 260, "Cilium ClusterMesh\n(global service)", glyph="Mesh", color=GREEN)
    d.icon("bgp", 705, 600, "BGP 피어링 (ToR)\nLB-IP·PodCIDR 광고", glyph="BGP", color=GREEN, label_w=180)
    d.edge([(570, 260), (679, 260)])
    d.edge([(731, 260), (930, 260)], "S3 API · Private", at=(800, 260), label_w=110)
    d.edge([(570, 600), (679, 600)])
    d.edge([(731, 600), (930, 600)], "S3 API · Private", at=(800, 600), label_w=110)

    d.group("aistor", 840, 140, 320, 680, "AIStor 클러스터 (베어메탈 k8s · 상용)", AISTOR, badge="S3")
    d.icon("hot", 960, 260, "Hot 클러스터 · 2026-02-07\n(raw/ · iceberg/)", kind="s3", color=AISTOR, size=60, label_w=180)
    d.icon("warm", 960, 600, "Warm 클러스터 · 2026-06-06\n(replica · tier · 용인 버킷)", kind="s3", color="#8A1C2E", size=60, label_w=180)
    d.edge([(960, 340), (960, 568)], "① Bucket Replication\n(비동기 · Versioning 필수)",
           at=(960, 450), label_w=170, width=2.5)
    d.edge([(990, 275), (1100, 275), (1100, 585), (990, 585)], "② ILM Transition\n(Remote Tier · Scanner)",
           at=(1100, 430), dashed=True, color=ORANGE, label_w=140)
    d.box("warn1", 860, 740, 280, 64, "🚨 ① 동일 버전 필수 (현재 불일치)",
          stroke=RED, fill=WARN_FILL, size=11, color=RED)

    d.group("pub", 1190, 140, 140, 680, "Public 경로", GREEN, badge="P")
    d.icon("ing", 1260, 245, "Ingress\n(L7 · 호스트)", kind="k8s:ing", color=BLUE, label_w=120)
    d.icon("vip", 1260, 615, "L4 스위치 VIP\n(스위치 LB)", glyph="VIP", color=GREEN, label_w=120)
    d.edge([(1234, 245), (992, 245)], "S3 API · Public", at=(1160, 225), label_w=100)
    d.edge([(1234, 615), (992, 615)], "S3 API · Public", at=(1160, 640), label_w=100)

    d.icon("ext", 1490, 430, "외부 클라이언트\n(용인 dataops ·\n사무망 · 협력사)", kind="k8s:user", color=BLUE,
           label_w=120)
    d.edge([(1464, 430), (1400, 430), (1400, 245), (1286, 245)])
    d.edge([(1400, 430), (1400, 615), (1286, 615)], "Public 접근\n(DNS→VIP/Ingress)", at=(1400, 520), label_w=120)

    d.edge([(136, 230), (304, 230)], "원천 적재", at=(190, 210), label_w=70)
    d.edge([(136, 420), (304, 420)], "SQL · Job 제출", at=(190, 400), label_w=90)
    d.edge([(136, 700), (250, 700)], "kubectl · GitOps\nmc admin", at=(190, 670), label_w=100)

    legend(d, 885, [("데이터 경로(S3 API)", INK, False), ("ILM Transition(비동기)", ORANGE, True)])
    d.text(620, 875, 900, 20, "보라=k8s 클러스터 · 초록=네트워크 · 레드=AIStor 스토리지 · 빨강 박스=확인 필요",
           size=11, color=MUTED, align="left")
    return d


# ---------------------------------------------------------------- 02
def d02():
    d = Diagram("02-warm-standalone-yongin",
                "용인 dataops — Warm 클러스터 전용 적재 · 조회 (Trino / Spark → HMS-Warm(Oracle) ← Polaris)",
                width=1560, height=920,
                subtitle="용인 데이터는 Warm 의 용인 전용 버킷에만 적재·조회 · 이천 replica · tier 버킷과 분리 · Hot 과 복제 관계 없음")
    d.icon("ana", 110, 300, "분석가·서비스\n(용인)", kind="k8s:user", color=BLUE)
    d.icon("src", 110, 470, "용인 원천 데이터", glyph="RAW", color=ORANGE)
    d.icon("lu", 110, 700, "Lake 사용자\n(Notebook·BI)", kind="k8s:user", color=BLUE)

    d.group("yi", 220, 100, 560, 460, "용인 IDC · dataops 클러스터 (신규)", PURPLE, badge="k8s")
    d.icon("trino", 330, 300, "Trino (용인)\ncatalog.type=hive_metastore", glyph="Trino", color=TRINO, label_w=200)
    d.icon("spark", 330, 470, "Spark / 수집 (용인)\n적재 · 유지보수", glyph="Spark", color=SPARK, label_w=160)
    d.icon("hms", 580, 300, "HMS-Warm (용인 원본)\nThrift :9083", glyph="HMS", color=TEAL, label_w=170)
    d.icon("ora", 580, 470, "HMS DB (Oracle)\n용인용 스키마", kind="db", glyph="Oracle", color=ORACLE)
    d.edge([(136, 300), (304, 300)], "SQL", at=(200, 280), label_w=40)
    d.edge([(136, 470), (304, 470)], "적재", at=(200, 450), label_w=40)
    d.edge([(356, 300), (554, 300)], "① 메타 조회·커밋", at=(455, 280), label_w=120)
    d.edge([(356, 460), (450, 460), (450, 320), (554, 320)])
    d.edge([(580, 370), (580, 442)], "JDBC", at=(620, 405), label_w=50)

    d.group("lake", 220, 590, 560, 260, "Lake 플랫폼", BLUE, badge="L")
    d.icon("leng", 330, 700, "Lake 엔진\n(Spark / Trino-Lake)", glyph="Engine", color=SPARK)
    d.icon("pol", 580, 700, "Apache Polaris\n(Iceberg REST Catalog)", glyph="Polaris", color=POLARIS, label_w=170)
    d.edge([(136, 700), (304, 700)])
    d.edge([(356, 700), (554, 700)], "② REST API", at=(455, 680), label_w=90)
    d.edge([(606, 700), (720, 700), (720, 300), (606, 300)],
           "③ Catalog Federation\n(lake_warm → HMS-Warm)", at=(720, 610), label_w=160, color=POLARIS)

    d.group("net", 820, 100, 260, 750, "DC 간 연결 (용인 → 이천)", GREEN, badge="⇄")
    d.icon("fw", 950, 210, "방화벽 (용인·이천)\nTCP 443 (또는 9000)", glyph="FW", color=RED, label_w=170)
    d.icon("vip", 950, 360, "이천 L4 VIP / Ingress\n(Public 경로)", glyph="VIP", color=GREEN, label_w=170)
    d.icon("dns", 950, 510, "사내 DNS\nwarm-s3.<domain> → VIP", glyph="DNS", color=GREEN, label_w=190)
    d.edge([(330, 274), (330, 150), (950, 150), (950, 182)], "④ 데이터 read / write (S3 API · HTTPS)",
           at=(640, 150), label_w=250, width=2.5, both=True)
    d.edge([(950, 280), (950, 332)], both=True)
    d.edge([(780, 510), (924, 510)], "⑤ 이름 해석", at=(850, 490), label_w=80, dashed=True)

    d.group("ic", 1120, 100, 400, 750, "이천 IDC · AIStor", AISTOR, badge="S3")
    d.group("wb", 1140, 150, 360, 450, "Warm · 2026-06-06", WARMC, badge="W")
    d.icon("by", 1230, 230, "yongin-*\nread / write", kind="bucket", color=PURPLE, size=64)
    d.icon("br", 1230, 400, "이천 replica", kind="bucket", color=ORANGE, size=60)
    d.icon("bt", 1410, 400, "ILM tier", kind="res:glacier", color=TIER, size=60)
    d.step(1268, 372, "✕", color=RED)
    d.step(1448, 372, "✕", color=RED)
    d.text(1160, 530, 330, 40, "✕ = 용인 접근 차단\n(replica · tier)", size=12, color=RED, bold=True)
    d.edge([(976, 360), (1060, 360), (1060, 222), (1196, 222)], "HTTPS :443", at=(1060, 300), label_w=80, width=2.5, both=True)
    d.icon("hot", 1320, 740, "Hot · 2026-02-07 (이천)", kind="bucket_obj", dim=True, size=56, label_w=190)
    d.edge([(1300, 710), (1300, 650), (1230, 650), (1230, 470)], "Replication", at=(1265, 650), label_w=80, dashed=True, color=GREY)
    d.edge([(1340, 710), (1340, 650), (1410, 650), (1410, 470)], "ILM", at=(1375, 650), label_w=40, dashed=True, color=GREY)
    d.edge([(780, 800), (1100, 800), (1100, 242), (1196, 242)],
           "⑥ Lake 엔진 read (확인 필요)", at=(940, 800), label_w=200, dashed=True, color=RED)
    legend(d, 885, [("데이터/메타 경로", INK, False), ("카탈로그 federation", POLARIS, False),
                    ("이천 내부 (용인 무관)", GREY, True)])
    return d

def d03():
    d = Diagram("03-iceberg-snapshot-vs-replication",
                "Iceberg 스냅샷 커밋 vs AIStor Bucket Replication — 충돌 지점 (시간 순)",
                width=1560, height=900,
                subtitle="S3 복제는 '객체(버전) 단위 비동기'이고 Iceberg 커밋은 '카탈로그 포인터 원자 교체' — 두 단위가 맞지 않아 C1~C4 충돌이 발생")
    lanes = [("writer", 150, "Writer\n(Spark · 이천)", SPARK, "Spark"),
             ("hhms", 390, "Hot HMS\n(카탈로그 포인터)", TEAL, "HMS"),
             ("hot", 640, "Hot 버킷", AISTOR, None),
             ("q", 880, "Replication 큐\n(비동기 · 객체 단위)", ORANGE, "Queue"),
             ("warm", 1120, "Warm 버킷", "#8A1C2E", None),
             ("wq", 1370, "복구 시 HMS / 조회 엔진\n(평시 미사용)", TEAL, "HMS")]
    for lid, cx, label, color, glyph in lanes:
        d.icon(lid, cx, 115, label, kind="s3" if glyph is None else "app", glyph=glyph or "", color=color,
               size=44, label_w=180)
        d.edge([(cx, 180), (cx, 870)], dashed=True, color="#C1C7D0", arrow=False, width=1)
    X = {lid: cx for lid, cx, *_ in lanes}

    def msg(y, a, b, text, color=INK, dashed=False, off=0):
        d.edge([(X[a] + off, y), (X[b] - off, y)] if X[a] < X[b] else [(X[a] - off, y), (X[b] + off, y)],
               text, at=((X[a] + X[b]) / 2, y - 12), label_w=abs(X[a] - X[b]) - 20, dashed=dashed, color=color)

    msg(215, "writer", "hot", "t1  data/*.parquet PUT")
    msg(260, "writer", "hot", "t2  metadata/*-m0.avro (manifest) PUT")
    msg(305, "writer", "hot", "t3  metadata/v3.metadata.json PUT")
    msg(350, "writer", "hhms", "t4  commit: metadata_location → v3 (원자 교체)", color=TEAL)
    msg(395, "hot", "q", "t5  버전별 큐잉 (PUT 응답 후)", color=ORANGE)
    msg(440, "q", "warm", "t6  v3.metadata.json 먼저 도착 가능", color=ORANGE)
    d.box("pend", 1010, 470, 220, 44, "일부 data/manifest\nPENDING · FAILED", stroke=RED, fill=WARN_FILL,
          size=11, color=RED, dashed=True)
    msg(545, "wq", "warm", "t7  v3 읽기 → 누락 파일 → FileNotFound / 불완전 스냅샷", color=RED)
    d.step(40, 545, "C1", color=RED, r=14)

    d.edge([(X["hhms"], 600), (X["wq"], 600)], "✕ HMS 포인터(Oracle 행)는 S3 복제 대상이 아님 → Warm HMS 는 v2 이하 또는 미등록",
           at=((X["hhms"] + X["wq"]) / 2, 588), label_w=700, dashed=True, color=RED)
    d.step(40, 600, "C2", color=RED, r=14)

    msg(665, "writer", "hot", "t8  expire_snapshots / remove_orphan_files → DELETE", color=INK)
    msg(705, "hot", "warm", "t9  delete / delete-marker 복제는 --replicate 플래그에 따라 다름 → Warm 잔존 또는 삭제",
        color=ORANGE)
    d.step(40, 685, "C3", color=RED, r=14)

    d.box("c4", 520, 760, 720, 56,
          "ILM Transition/Expiration 은 객체 나이만 보고 동작 — Iceberg 가 참조 중인 파일인지 모름\n"
          "(ILM Expiration 으로 삭제된 객체는 복제되지 않음 → Hot/Warm 불일치)",
          stroke=RED, fill=WARN_FILL, size=11, color=RED)
    d.step(40, 788, "C4", color=RED, r=14)
    d.text(66, 530, 90, 30, "부분 복제", size=11, color=RED, align="left")
    d.text(66, 585, 90, 30, "카탈로그 미복제", size=11, color=RED, align="left")
    d.text(66, 670, 90, 30, "삭제 전파", size=11, color=RED, align="left")
    d.text(66, 773, 90, 30, "ILM 비인지", size=11, color=RED, align="left")
    return d


# ---------------------------------------------------------------- 04
def d05():
    d = Diagram("05-yongin-network-checkpoints",
                "용인 신규 클러스터 → 이천 Warm(S3) 접근 — 네트워크 블럭 해소 체크포인트",
                width=1560, height=880,
                subtitle="A. Public 경로(기존 VIP/Ingress 재사용, 권장) 와 B. Private 경로(ClusterMesh 확장) 중 선택 · 번호는 확인 사항표 항목")

    d.group("yi", 40, 100, 360, 700, "용인 dataops 클러스터 (신규)", PURPLE, badge="k8s")
    d.icon("trino", 150, 200, "Trino / Spark Pod", glyph="Trino", color=TRINO)
    d.icon("egw", 300, 320, "노드 SNAT /\nEgress Gateway", glyph="Egress", color=GREEN)
    d.icon("cdns", 150, 460, "CoreDNS\n(forward/stub)", glyph="DNS", color=BLUE)
    d.icon("mesh1", 300, 620, "clustermesh-apiserver\n(용인)", glyph="Mesh", color=GREEN, label_w=170)
    d.edge([(176, 200), (300, 200), (300, 292)])
    d.edge([(150, 252), (150, 432)], "이름 해석", at=(150, 340), label_w=70, dashed=True)

    d.group("wan", 440, 100, 560, 700, "DC 간 구간 (용인 ↔ 이천)", GREEN, badge="⇄")
    d.text(460, 250, 520, 20, "A. Public 경로 (권장 · 기존 VIP/Ingress 재사용)", size=13, bold=True, color=INK, align="left")
    d.text(460, 550, 520, 20, "B. Private 경로 (ClusterMesh 확장)", size=13, bold=True, color=INK, align="left")
    d.icon("fw1", 540, 320, "용인 방화벽", glyph="FW", color=RED)
    d.icon("wan1", 700, 320, "DC 간 회선\n라우팅", glyph="WAN", color=GREY)
    d.icon("fw2", 860, 320, "이천 방화벽", glyph="FW", color=RED)
    d.icon("dns", 700, 460, "사내 DNS\nwarm FQDN 등록", glyph="DNS", color=GREEN)
    d.icon("bgp1", 540, 620, "용인 ToR\nBGP", glyph="BGP", color=GREEN)
    d.icon("wan2", 700, 620, "DC 간 회선\nPodCIDR 라우팅", glyph="WAN", color=GREY)
    d.icon("bgp2", 860, 620, "이천 ToR\nBGP", glyph="BGP", color=GREEN)
    d.edge([(176, 460), (674, 460)], "forward", at=(420, 445), label_w=60, dashed=True)

    d.group("ic", 1040, 100, 480, 700, "이천 IDC · AIStor", AISTOR, badge="S3")
    d.icon("ing", 1130, 190, "Ingress (L7)", kind="k8s:ing", color=BLUE)
    d.icon("vip", 1130, 320, "L4 스위치 VIP", glyph="VIP", color=GREEN)
    d.icon("warm", 1400, 320, "AIStor Warm\nS3 :443 / :9000", kind="s3", color="#8A1C2E", size=60)
    d.icon("mesh2", 1130, 620, "clustermesh-apiserver\n(이천)", glyph="Mesh", color=GREEN, label_w=170)

    for a, b in [((326, 320), (514, 320)), ((566, 320), (674, 320)), ((726, 320), (834, 320)),
                 ((886, 320), (1104, 320)), ((1156, 320), (1368, 320))]:
        d.edge([a, b], width=2.5)
    d.edge([(886, 310), (1000, 310), (1000, 190), (1104, 190)], dashed=True)
    d.edge([(1156, 190), (1400, 190), (1400, 288)], dashed=True)
    for a, b in [((326, 620), (514, 620)), ((566, 620), (674, 620)), ((726, 620), (834, 620)),
                 ((886, 620), (1104, 620))]:
        d.edge([a, b], color=GREEN)
    d.edge([(1156, 620), (1480, 620), (1480, 320), (1432, 320)], "global service", at=(1320, 620),
           label_w=100, color=GREEN)

    for n, (cx, cy) in enumerate([(300, 320), (540, 320), (700, 320), (860, 320), (1130, 320),
                                  (1400, 320), (700, 460), (300, 620), (700, 620)], start=1):
        d.step(cx + 30, cy - 32, n, color=RED)
    d.text(40, 830, 1480, 20, "① 소스 IP(SNAT)  ② 용인 FW  ③ 회선·라우팅  ④ 이천 FW  ⑤ VIP/Ingress  ⑥ TLS·엔드포인트·자격증명  "
           "⑦ DNS  ⑧ ClusterMesh 전제(CIDR·cluster-id)  ⑨ BGP 경로 광고", size=12, color=MUTED, align="left")
    return d


# ---------------------------------------------------------------- 06
def d06():
    d = Diagram("09-hot-warm-catalog-split",
                "카탈로그 구성 — HMS-Hot(이천 서비스) · HMS-Warm(용인 원본) · Polaris federation",
                width=1560, height=900,
                subtitle="용인 테이블은 HMS-Warm 이 원본 카탈로그(등록 Job 불필요) · 이천 replica 는 백업 — 복구 시에만 별도 등록")
    d.icon("lu", 100, 430, "Lake 사용자", kind="k8s:user", color=BLUE)
    d.group("lake", 200, 120, 300, 660, "Lake 플랫폼", BLUE, badge="L")
    d.icon("pol", 350, 430, "Apache Polaris\nexternal catalog\n• lake_hot → HMS-Hot\n• lake_warm → HMS-Warm",
           glyph="Polaris", color=POLARIS, label_w=210)
    d.edge([(126, 430), (324, 430)])

    d.group("ic", 560, 100, 420, 330, "이천 dataops (기존)", PURPLE, badge="k8s")
    d.icon("hmsh", 680, 250, "HMS-Hot\n(이천 서비스)", glyph="HMS", color=TEAL)
    d.icon("orah", 860, 250, "Oracle\n(Hot 스키마)", kind="db", glyph="Oracle", color=ORACLE)
    d.icon("trh", 680, 370, "Trino·Spark (이천)", glyph="Trino", color=TRINO, size=40)
    d.edge([(706, 250), (834, 250)], "JDBC", at=(770, 232), label_w=40)
    d.edge([(660, 370), (620, 370), (620, 262), (654, 262)])

    d.group("yi", 560, 460, 420, 380, "용인 dataops (신규)", PURPLE, badge="k8s")
    d.icon("hmsw", 680, 610, "HMS-Warm\n(용인 원본 카탈로그)", glyph="HMS", color=TEAL, label_w=150)
    d.icon("oraw", 860, 610, "Oracle\n(용인 스키마 · 신규)", kind="db", glyph="Oracle", color=ORACLE)
    d.icon("trw", 680, 750, "Trino / Spark (용인)", glyph="Trino", color=TRINO, size=40)
    d.edge([(706, 610), (834, 610)], "JDBC", at=(770, 592), label_w=40)
    d.edge([(660, 750), (620, 750), (620, 622), (654, 622)])

    d.edge([(376, 420), (530, 420), (530, 250), (654, 250)], "① lake_hot", at=(590, 232), label_w=80, color=POLARIS)
    d.edge([(376, 440), (530, 440), (530, 610), (654, 610)], "② lake_warm", at=(590, 592), label_w=80, color=POLARIS)

    d.group("s3", 1040, 100, 470, 740, "이천 AIStor — Hot 2026-02-07 · Warm 2026-06-06", AISTOR, badge="S3")
    d.icon("hot", 1160, 250, "Hot 버킷 (이천 서비스)", kind="s3", color=AISTOR, size=56, label_w=170)
    d.icon("rep", 1140, 480, "replica (백업)", kind="bucket", color=ORANGE, size=56)
    d.icon("tier", 1380, 480, "tier (AIStor 전용)", kind="res:glacier", color=TIER, size=56, label_w=130)
    d.icon("yb", 1250, 655, "yongin-* (용인 원본)", kind="bucket", color=PURPLE, size=60, label_w=160)
    d.edge([(1140, 322), (1140, 450)], "Replication\n🚨 동일 버전", at=(1140, 390), label_w=100, width=2.5, color=ORANGE)
    d.edge([(1190, 300), (1190, 330), (1380, 330), (1380, 450)], "ILM", at=(1290, 330), label_w=40,
           dashed=True, color=ORANGE)
    d.edge([(680, 224), (680, 150), (1160, 150), (1160, 220)], "metadata_location", at=(950, 150), label_w=120,
           dashed=True, color=TEAL)
    d.edge([(706, 750), (1330, 750), (1330, 655), (1282, 655)], "read / write (DC 간)", at=(950, 750), label_w=140, both=True)
    d.edge([(680, 584), (680, 560), (1010, 560), (1010, 655), (1218, 655)], "metadata_location", at=(850, 560),
           label_w=120, dashed=True, color=TEAL)
    d.box("note", 40, 800, 480, 60, "용인: 직접 커밋 (등록 Job 없음)\n이천 replica: 복구 시에만 register",
          stroke=TEAL, fill="#E6F7F4", color=INK, size=12, bold=True)
    return d

def d07():
    d = Diagram("07-scanner-impact", "Scanner 가 느려지면 — 네 작업이 함께 지연",
                width=1500, height=720, subtitle="Scanner 한 사이클 = 사용량 · ILM · 복제 재큐잉 · Healing")
    d.group("a", 40, 100, 360, 460, "Scanner", INK, badge="SCN")
    d.icon("scn", 220, 190, "Scanner 사이클", glyph="SCN", color=INK, size=70)
    for i, t in enumerate(["16회 스캔 = 전체 1회", "버킷 간 30초 대기", "I/O 양보 (작업시간 × 10)"]):
        d.box(f"a{i}", 70, 290 + i * 52, 300, 40, t, stroke=INK, size=12)
    d.box("slow", 70, 460, 300, 70, "느려지는 요인\n드라이브 · 네트워크 · 객체 수", stroke=RED, fill=WARN_FILL, color=RED, size=12, bold=True)

    d.group("b", 460, 100, 340, 460, "담당 작업", ORANGE, badge="4")
    tasks = [(170, "USG", "사용량 계산"), (270, "ILM", "ILM 적용"), (370, "REP", "복제 재큐잉"), (470, "HEAL", "Healing")]
    for y, g, lab in tasks:
        d.icon(f"t{y}", 630, y, lab, glyph=g, color=ORANGE, size=48, label_w=110)
    d.edge([(255, 190), (430, 190), (430, 170), (604, 170)], "매 사이클", at=(345, 190), label_w=70)

    d.group("c", 860, 100, 600, 460, "지연 시 영향", RED, badge="!")
    imp = [(170, 990, "용량 수치 지연"), (270, 990, "Transition 지연"), (270, 1250, "버전 누적"),
           (370, 990, "replica 누락 (C1)"), (370, 1250, "복구 시 불완전"), (470, 990, "복구 지연")]
    for y, x, lab in imp:
        d.icon(f"i{y}{x}", x, y, lab, glyph="!", color=RED, size=40, label_w=130)
    for y in (170, 270, 370, 470):
        d.edge([(654, y), (968, y)], color=RED)
    d.edge([(1010, 270), (1228, 270)], color=RED)
    d.edge([(1010, 370), (1228, 370)], color=RED)
    d.edge([(1270, 270), (1430, 270), (1430, 600), (220, 600), (220, 532)], "악순환: 버전↑ → 스캔 더 느려짐",
           at=(830, 600), label_w=220, dashed=True, color=RED)
    d.box("m", 40, 640, 1420, 50,
          "대응: mc admin scanner info · minio_scanner_* 모니터링 | resync-backlog 수동 재큐잉 | noncurrent 만료로 버전 억제 | SLA 를 ILM·복제 완료 시점에 두지 않기",
          stroke=INK, fill="#F4F5F7", size=12, bold=True)
    return d

def i3():
    d = Diagram("i3-conclusion3-unit-mismatch", "커밋 단위 불일치 — 스냅샷 묶음 vs 객체 하나씩",
                width=1400, height=660, subtitle="Hot 에서 한 번에 커밋된 스냅샷이 Warm replica 에는 객체별로 따로 도착")
    d.group("hot", 40, 100, 380, 450, "Hot", AISTOR, badge="S3")
    d.box("snap", 110, 135, 200, 300, "", stroke=PURPLE, fill="#F5F0FF", dashed=True)
    d.text(110, 138, 200, 18, "Snapshot v3", size=12, bold=True, color=PURPLE)
    docs = [(190, "data", "Parquet"), (280, "manifest", "Avro"), (370, "metadata", "v3.json")]
    for y, lab, g in docs:
        d.icon(f"h{y}", 210, y, lab, kind="doc", glyph=g, color=INK, size=46, label_w=90)
    d.icon("hh", 210, 490, "HMS-Hot → v3", glyph="HMS", color=TEAL, size=40, label_w=120)

    d.group("q", 470, 100, 430, 450, "Replication (객체별 · 비동기)", ORANGE, badge="Q")
    d.edge([(236, 190), (1122, 190)], "⏳ 지연 / 실패", at=(685, 172), label_w=110, dashed=True, color=RED, width=2)
    d.edge([(236, 280), (1122, 280)], "✓ t+2s", at=(685, 262), label_w=70, color=ORANGE, width=2)
    d.edge([(236, 370), (1122, 370)], "✓ t+1s (먼저)", at=(685, 352), label_w=100, color=ORANGE, width=2)
    d.edge([(232, 490), (1128, 490)], "✕ 복제 대상 아님", at=(685, 472), label_w=120, dashed=True, color=RED, width=2)

    d.group("warm", 950, 100, 410, 450, "Warm replica", WARMC, badge="S3")
    d.icon("w190", 1150, 190, "data 없음", kind="doc", glyph="✕", color=RED, size=46, label_w=90, dashed=True)
    d.icon("w280", 1150, 280, "manifest", kind="doc", glyph="Avro", color=INK, size=46, label_w=90)
    d.icon("w370", 1150, 370, "metadata", kind="doc", glyph="v3.json", color=INK, size=46, label_w=90)
    d.icon("wh", 1150, 490, "카탈로그 없음", glyph="HMS", color=GREY, size=40, label_w=120, dashed=True)
    chips(d, 585, ["C1 부분 복제", "C2 카탈로그 미복제", "C3 삭제 전파", "C4 ILM 비인지", "C5 Object Lock"], w=255)
    return d

def i6():
    d = Diagram("i6-conclusion6-hms-split-register", "[이천 replica 복구] 검증 후 등록 — 평시 미사용",
                width=1400, height=620, subtitle="Replication 은 데이터만 복제 → 복구 시 파일 완전성 확인 후에만 복구용 HMS 에 등록")
    d.group("cat", 40, 100, 1320, 200, "카탈로그", TEAL, badge="HMS")
    d.icon("hh", 200, 190, "HMS-Hot", glyph="HMS", color=TEAL)
    d.icon("job", 700, 190, "복구 · 검증 Job", kind="k8s:job", color=PURPLE, size=56)
    d.icon("hw", 1100, 190, "복구용 HMS", glyph="HMS", color=TEAL)
    d.icon("ty", 1280, 190, "검증 Trino", glyph="Trino", color=TRINO, size=44)
    d.edge([(226, 190), (670, 190)], "① 최신 metadata", at=(450, 172), label_w=120, color=PURPLE)
    d.edge([(728, 190), (1074, 190)], "③ register (누락 0 일 때)", at=(900, 172), label_w=170, color=PURPLE, width=2.5)
    d.edge([(1126, 190), (1256, 190)])
    d.group("st", 40, 340, 1320, 180, "AIStor (이천)", AISTOR, badge="S3")
    d.icon("hot", 200, 420, "Hot 버킷", kind="bucket_obj", color=AISTOR, size=60)
    d.icon("warm", 1100, 420, "Warm replica (동일 버킷명)", kind="bucket", color=ORANGE, size=60, label_w=200)
    d.edge([(232, 420), (1068, 420)], "Replication (비동기)", at=(640, 402), label_w=140, width=2.5, color=ORANGE)
    d.edge([(700, 220), (700, 380), (1068, 380)], "② 전체 파일 HEAD", at=(700, 320), label_w=120, dashed=True, color=PURPLE)
    d.box("rule", 40, 545, 1320, 44, "⚠ Hot 스냅샷 보존 기간 > 복제 지연 + 백업 주기  ·  replica 는 복구 전까지 쓰기 금지",
          stroke=RED, fill=WARN_FILL, color=RED, size=13, bold=True)
    return d

def i7():
    d = Diagram("11-todo-milestones", "해야 할 일 — 마일스톤 (두 케이스 병행: 용인 Warm 전용 · 이천 Replication + ILM)",
                width=1560, height=700,
                subtitle="박스 안 No = INDEX §3 작업 번호 · 빨간 게이트 = 착수 전 확정할 결정 · 위 줄 = 이천 Replication/ILM · 아래 줄 = 용인 Warm 전용")
    ms = {
        "m0": (40, 270, "M0 담당자 확인\nNo 1–3", RED),
        "m1": (320, 140, "M1 근거 · 설계\nNo 4–11 · 36–37 🚨", INK),
        "m2": (600, 140, "M2 복제 테스트 · DR\nNo 12–16 · 38–40", ORANGE),
        "m3": (880, 140, "M3 ILM · Archive\nNo 17–21", GREEN),
        "m4": (320, 400, "M4 용인 네트워크\nNo 22–26", GREEN),
        "m5": (600, 400, "M5 HMS-Warm\nNo 27–31", TEAL),
        "m6": (880, 400, "M6 Polaris\nNo 32–34", POLARIS),
        "m7": (1220, 270, "M7 운영 이관\nNo 35", INK),
    }
    for k, (x, y, t, c) in ms.items():
        d.box(k, x, y, 240, 120, t, stroke=c, fill=WHITE, size=15, bold=True)
    d.edge([(280, 310), (300, 310), (300, 200), (318, 200)], width=2.5)
    d.edge([(280, 350), (300, 350), (300, 460), (318, 460)], width=2.5)
    for a, b, y in [(560, 598, 200), (840, 878, 200), (560, 598, 460), (840, 878, 460)]:
        d.edge([(a, y), (b, y)], width=2.5)
    d.edge([(1120, 200), (1170, 200), (1170, 310), (1218, 310)], width=2.5)
    d.edge([(1120, 460), (1170, 460), (1170, 350), (1218, 350)], width=2.5)
    d.edge([(720, 260), (720, 398)], "Warm 부하 공유", at=(720, 330), label_w=100, dashed=True, color=RED)
    gates = [(40, 140, "G0 Warm 버킷 역할 분리\n(용인 · replica · tier)", (160, 200), (160, 268)),
             (600, 76, "G1 버전 일치 · 복제 대상 · 삭제 전파", (720, 116), (720, 138)),
             (880, 76, "G2 아카이브 A / B / C", (1000, 116), (1000, 138))]
    for x, y, t, a, b in gates:
        d.box(f"g{x}", x, y, 240, 60 if y > 100 else 40, t, stroke=RED, fill=WARN_FILL, color=RED, size=12, bold=True)
        d.edge([a, b], dashed=True, color=RED)
    d.text(40, 590, 1470, 24, "위 줄 = 이천 (Replication · ILM)     아래 줄 = 용인 (Warm 전용)     점선 = Warm 부하 공유", size=13, color=MUTED, align="left")
    return d

def r_decision():
    d = Diagram("03-warm-coexistence", "두 케이스 공존 — Warm 클러스터 3개 역할",
                width=1500, height=700, subtitle="이천: Hot → Warm Replication(백업) + ILM(용량) · 용인: Warm 전용 read/write")
    d.group("hot", 40, 100, 330, 420, "Hot · 2026-02-07 (이천)", AISTOR, badge="S3")
    d.icon("hb", 205, 200, "이천 서비스 버킷", kind="bucket_obj", color=AISTOR, size=64)
    d.icon("rep", 120, 390, "Bucket\nReplication", glyph="REP", color=ORANGE, size=48)
    d.icon("ilm", 290, 390, "ILM\nTransition", glyph="ILM", color=ORANGE, size=48)
    d.edge([(190, 262), (190, 300), (120, 300), (120, 364)], color=MUTED, arrow=False, width=1)
    d.edge([(220, 262), (220, 300), (290, 300), (290, 364)], color=MUTED, arrow=False, width=1)

    d.group("warm", 430, 100, 600, 420, "Warm · 2026-06-06", WARMC, badge="W")
    d.icon("wr", 530, 250, "① replica\n(Hot 동일명)", kind="bucket", color=ORANGE, size=64)
    d.icon("wt", 730, 250, "② tier prefix", kind="res:glacier", color=TIER, size=64)
    d.icon("wy", 930, 250, "③ yongin-*", kind="bucket", color=PURPLE, size=64)
    d.text(455, 330, 150, 20, "쓰기 금지 · ILM 별도", size=11, color=RED, bold=True)
    d.text(655, 330, 150, 20, "🔒 AIStor 전용", size=11, color=RED, bold=True)
    d.text(855, 330, 150, 20, "용인 read/write", size=11, color=PURPLE, bold=True)
    d.edge([(120, 460), (120, 490), (395, 490), (395, 250), (496, 250)], "백업", at=(395, 420), label_w=40, width=2.5, color=ORANGE)
    d.edge([(314, 390), (415, 390), (415, 86), (730, 86), (730, 216)], "Transition", at=(570, 86), label_w=80,
           dashed=True, width=2, color=ORANGE)

    d.group("yi", 1090, 100, 370, 420, "용인 dataops", PURPLE, badge="k8s")
    d.icon("yu", 1150, 200, "용인 서비스", kind="users", color=BLUE, size=48, label_w=100)
    d.icon("yt", 1275, 200, "Trino / Spark", glyph="Trino", color=TRINO, size=48, label_w=110)
    d.icon("yh", 1400, 200, "HMS-Warm", glyph="HMS", color=TEAL, size=48, label_w=100)
    d.edge([(1174, 200), (1250, 200)])
    d.edge([(1300, 200), (1375, 200)])
    d.edge([(1275, 250), (1275, 300), (1060, 300), (1060, 250), (964, 250)], "read / write", at=(1170, 300),
           label_w=90, width=2.5, both=True, color=PURPLE)
    d.text(1110, 420, 330, 40, "🔑 용인 키 = yongin-* 만\nreplica · tier 차단", size=12, color=PURPLE, bold=True)

    chips(d, 560, ["🚨 C-1 동일 버전", "C-2 버킷·권한 분리", "C-3 Tier 독점", "C-4 이중 저장 용량",
                   "C-5 공존 부하", "C-6 백업 일관성"], w=227)
    d.text(40, 620, 1420, 20, "공존 조건 상세: 근거 1 §2 ~ §4", size=11, color=MUTED, align="left")
    return d

def archive_options():
    d = Diagram("07-ilm-archive-options", "RAW 아카이브 선택지 — A · B · C (협의 필요)",
                width=1500, height=730, subtitle="ILM = Transition · Expiration 만 (zip 생성 불가) · B 는 '변환은 서비스, 이관은 ILM'")
    for x, t, c, dsh in [(40, "A. zip 미사용", GREEN, False), (520, "B. 하이브리드 (피드백 제안)", ORANGE, False),
                         (1000, "C. 전면 Rollover (기존안)", GREY, True)]:
        d.group(f"g{x}", x, 100, 460, 440, t, c, badge="", dashed=dsh)
    # A
    cx = 270
    d.icon("aR", cx, 180, "RAW 버킷", kind="bucket_obj", color=AISTOR, size=56)
    d.icon("aI", cx, 300, "ILM Transition", glyph="ILM", color=ORANGE, size=50)
    d.icon("aT", cx, 420, "Warm Tier", kind="res:glacier", color=TIER, size=56)
    d.edge([(cx, 236), (cx, 272)])
    d.edge([(cx, 350), (cx, 390)])
    # B
    d.icon("bR", 610, 180, "RAW 버킷", kind="bucket_obj", color=AISTOR, size=56)
    d.icon("bJ", 610, 300, "① 서비스 zip 변환", kind="k8s:job", color=BLUE, size=50, label_w=140)
    d.icon("bZ", 610, 420, "archive/*.zip", kind="doc", glyph="ZIP", color=ORANGE, size=50)
    d.icon("bI", 760, 420, "② ILM Transition", glyph="ILM", color=ORANGE, size=50, label_w=130)
    d.icon("bT", 900, 420, "Warm Tier", kind="res:glacier", color=TIER, size=56)
    d.edge([(610, 236), (610, 272)])
    d.edge([(610, 350), (610, 392)])
    d.edge([(636, 420), (732, 420)])
    d.edge([(786, 420), (870, 420)])
    # C
    cx = 1230
    d.icon("cR", cx, 170, "RAW 버킷", kind="bucket_obj", color=AISTOR, size=50)
    d.icon("cJ", cx, 265, "서비스 Rollover Job", kind="k8s:job", color=GREY, size=46, label_w=150)
    d.icon("cZ", cx, 360, "zip 생성", kind="doc", glyph="ZIP", color=GREY, size=46)
    d.icon("cW", cx, 455, "Warm 직접 업로드", kind="bucket", color=WARMC, size=50, label_w=140)
    d.edge([(cx, 222), (cx, 240)])
    d.edge([(cx, 312), (cx, 335)])
    d.edge([(cx, 406), (cx, 428)])
    notes = [(40, "✓ 구현 없음 · 조회 그대로\n✕ 객체 수 그대로 · 압축 없음", GREEN),
             (520, "✓ 객체 수↓ · 이관·재시도는 ILM\n✕ zip 변환·검증 · 조회 시 해제", ORANGE),
             (1000, "✓ 시점·형식 완전 제어\n✕ 구현·운영 부담 최대", GREY)]
    for x, t, c in notes:
        d.box(f"n{x}", x, 560, 460, 60, t, stroke=c, fill=WHITE, size=12, align="left")
    d.box("dec", 40, 640, 1420, 60,
          "협의 기준: 조회 요구 · 객체 수 · 압축 이득 · 구현 부담 · 보존 정책     |     권고 순서: A → (문제 확인 시) B → C",
          stroke=RED, fill=WARN_FILL, color=RED, size=13, bold=True)
    return d

def rep_ilm_constraints():
    d = Diagram("12-replication-ilm-constraints", "Replication + ILM — 같은 버킷에 그대로 쓰기 어려운 이유",
                width=1500, height=720, subtitle="공개 문서에 병행 금지 문구는 없음 (MinIO 는 병행 권장) · 같은 객체에 두 규칙을 걸 때의 제약 ①~⑧")
    d.group("hot", 40, 100, 360, 440, "Hot · 2026-02-07", AISTOR, badge="S3")
    d.icon("hb", 220, 210, "같은 버킷 · 같은 객체", kind="bucket_obj", color=AISTOR, size=70, label_w=170)
    d.icon("rep", 130, 400, "Replication", glyph="REP", color=ORANGE, size=52)
    d.icon("ilm", 310, 400, "ILM", glyph="ILM", color=ORANGE, size=52)
    d.edge([(205, 280), (205, 320), (130, 320), (130, 372)], color=MUTED, arrow=False, width=1)
    d.edge([(235, 280), (235, 320), (310, 320), (310, 372)], color=MUTED, arrow=False, width=1)

    d.group("warm", 520, 100, 520, 440, "Warm · 2026-06-06", WARMC, badge="W")
    d.icon("wr", 640, 220, "replica", kind="bucket", color=ORANGE, size=64)
    d.icon("wt", 900, 220, "tier (AIStor 전용)", kind="res:glacier", color=TIER, size=64, label_w=140)
    d.icon("wi", 640, 430, "replica 측 ILM\n(별도 설정)", glyph="ILM", color=GREY, size=48, dashed=True, label_w=130)
    d.edge([(640, 406), (640, 290)], color=GREY, dashed=True)

    d.edge([(130, 426), (130, 480), (460, 480), (460, 220), (606, 220)], "복제", at=(460, 350), label_w=40,
           width=2.5, color=ORANGE)
    d.edge([(336, 400), (480, 400), (480, 140), (900, 140), (900, 186)], "Transition", at=(690, 140), label_w=80,
           width=2, dashed=True, color=ORANGE)
    d.edge([(672, 230), (770, 230), (770, 515), (220, 515), (220, 302)], "resync", at=(600, 515),
           label_w=60, dashed=True, color=RED)

    badges = [(770, 400, "1"), (695, 430, "2"), (665, 345, "3"), (590, 180, "4"), (945, 180, "5"),
              (800, 190, "6"), (345, 370, "7"), (165, 370, "8")]
    for x, y, n in badges:
        d.step(x, y, n, color=RED, r=13)

    d.group("lg", 1080, 100, 380, 440, "제약", RED, badge="!")
    items = ["resync → Tier 연결 영구 단절", "Expiration 삭제 미복제", "ILM 설정 비복제 · 비대칭",
             "Transition 된 객체 복제 미기재", "Tier = AIStor 독점", "Warm 이중 저장 (용량)",
             "Scanner 공유 부하", "🚨 동일 버전 필수 (Replication)"]
    for i, t in enumerate(items):
        y = 150 + i * 48
        d.step(1112, y, str(i + 1), color=RED, r=13)
        d.text(1135, y - 12, 315, 24, t, size=13, color=INK, align="left")
    d.box("rec", 40, 570, 1420, 110,
          "권장 패턴\n"
          "P-A 복제 대상 ≠ Transition 대상 (최근=복제 · 오래된=Transition)   P-B 같은 객체면 복제 완료 후 Transition\n"
          "P-C replica 에 같은 Expiration   P-D Tiering 버킷 resync 는 승인 절차   P-E tier 는 복제 대상 제외",
          stroke=GREEN, fill="#F0F7E6", color=INK, size=13, bold=True)
    return d


def versioning_iceberg():
    d = Diagram("13-versioning-iceberg-backup", "Iceberg 스냅샷 × 버킷 Versioning — 백업 용도에서의 충돌",
                width=1500, height=740, subtitle="Replication 은 Versioning 필수 (Replication.pdf 4.2) · Iceberg 는 동작하지만 이력이 이중화되고 정리가 무력화됨")
    d.group("ice", 40, 100, 420, 440, "Iceberg 스냅샷 (테이블 이력)", PURPLE, badge="ICE")
    for i, x in enumerate((110, 230, 350)):
        d.icon(f"s{i}", x, 190, "", kind="doc", glyph=f"snap {i + 1}", color=PURPLE, size=50)
        if i:
            d.edge([(x - 94, 190), (x - 27, 190)], color=PURPLE)
    d.text(60, 225, 380, 20, "이력 = 스냅샷 · 롤백 = 카탈로그 포인터", size=12, color=PURPLE, bold=True)
    d.icon("job", 230, 350, "expire_snapshots\ncompaction", kind="k8s:job", color=PURPLE, size=54, label_w=150)

    d.group("hot", 520, 100, 440, 440, "Hot · Versioning ON", AISTOR, badge="S3")
    d.icon("hb", 740, 180, "Hot Iceberg 버킷", kind="bucket_obj", color=AISTOR, size=62)
    d.icon("cur", 610, 360, "현재", kind="doc", glyph="current", color=INK, size=50)
    d.icon("dm", 740, 360, "delete marker", kind="doc", glyph="DM", color=RED, size=50, label_w=110)
    d.icon("nc", 870, 360, "noncurrent 보관", kind="doc", glyph="v1 v2", color=GREY, size=50, dashed=True, label_w=120)
    d.icon("nul", 610, 470, "Versioning 전 파일", kind="doc", glyph="null", color=GREY, size=46, label_w=130)
    d.edge([(257, 350), (540, 350), (540, 300), (740, 300), (740, 333)], "DELETE", at=(400, 350), label_w=60, color=PURPLE)
    d.edge([(766, 360), (843, 360)], color=GREY, dashed=True)

    d.group("wr", 1010, 100, 450, 440, "Warm replica", WARMC, badge="W")
    d.icon("rb", 1230, 180, "replica 버킷", kind="bucket", color=ORANGE, size=62)
    d.icon("rc", 1110, 360, "현재", kind="doc", glyph="current", color=INK, size=50)
    d.icon("rdm", 1250, 360, "삭제 전파 ON / OFF ?", kind="doc", glyph="DM ?", color=RED, size=50, label_w=150)
    d.icon("rnul", 1110, 470, "미복제", kind="doc", glyph="✕", color=RED, size=46, dashed=True)
    d.edge([(774, 180), (1196, 180)], "Replication", at=(985, 162), label_w=90, width=2.5, color=ORANGE)
    d.edge([(636, 470), (1084, 470)], "✕ version ID 없음 → 제외", at=(860, 452), label_w=170, dashed=True, color=RED)

    for x, y, t in [(895, 330, "S1"), (640, 445, "V1"), (1280, 330, "V4"), (930, 128, "V6")]:
        d.step(x, y, t, color=RED, r=14)
    chips(d, 570, ["S1 정리 무력화 (용량↑)", "S2 이력 이중 보관", "S3 버전 복원 ≠ 테이블 복원",
                   "V1 켜기 전 파일 미복제", "V4 삭제 전파 딜레마", "V6 Versioning 끌 수 없음"], w=227)
    d.box("rec", 40, 640, 1420, 70,
          "대응: ① Versioning 상태 확인 → ② 기존 파일 seed (mirror · rewrite_table_path) → ③ Hot · replica 에 noncurrent 만료\n"
          "④ 삭제 전파 결정 (delete-marker ON + replica 보존 기간) → ⑤ 복구는 스냅샷 · register 기준",
          stroke=GREEN, fill="#F0F7E6", color=INK, size=13, bold=True)
    return d


def dr_flow():
    d = Diagram("14-dr-failover-failback", "DR 전용 모드 — 버킷 Replication 만으로 Warm 을 복구 용도로 (Iceberg)",
                width=1500, height=760, subtitle="복제 = 파일 사본 · 테이블 복구 = 카탈로그 기록 + 검증 후 register · DR 대상 버킷은 Transition 금지")
    d.group("p1", 40, 100, 440, 440, "① 평시", GREEN, badge="1")
    d.icon("h1", 150, 200, "Hot 버킷", kind="bucket_obj", color=AISTOR, size=60)
    d.icon("r1", 370, 200, "Warm replica", kind="bucket", color=ORANGE, size=60)
    d.icon("hm1", 150, 360, "HMS-Hot", glyph="HMS", color=TEAL, size=48)
    d.icon("lg1", 370, 360, "metadata_location\n기록 · HMS 백업", kind="doc", glyph="LOG", color=TEAL, size=48, label_w=150)
    d.edge([(182, 200), (338, 200)], "Replication", at=(260, 182), label_w=90, width=2.5, color=ORANGE)
    d.edge([(176, 360), (344, 360)], "주기 기록", at=(260, 342), label_w=70, dashed=True, color=TEAL)

    d.group("p2", 530, 100, 440, 440, "② 장애 → 전환", RED, badge="2")
    d.icon("h2", 640, 190, "Hot 장애", kind="bucket_obj", dim=True, size=56)
    d.step(672, 162, "✕", color=RED, r=13)
    d.icon("r2", 860, 190, "Warm replica", kind="bucket", color=ORANGE, size=60)
    d.icon("jb", 860, 320, "검증 Job", kind="k8s:job", color=PURPLE, size=48)
    d.icon("hm2", 860, 450, "복구용 HMS", glyph="HMS", color=TEAL, size=44)
    d.icon("dns", 640, 320, "DNS · VIP 전환", kind="res:route_53", color=GREEN, size=48, label_w=120)
    d.icon("tr", 640, 450, "Trino · Spark", glyph="Trino", color=TRINO, size=44)
    d.edge([(860, 296), (860, 244)], "③ HEAD", at=(900, 268), label_w=60, dashed=True, color=PURPLE)
    d.edge([(860, 364), (860, 426)], "③ register", at=(912, 395), label_w=80, color=PURPLE)
    d.edge([(640, 426), (640, 374)])
    d.edge([(664, 320), (760, 320), (760, 200), (828, 200)], "④ 서비스 전환", at=(760, 260), label_w=100, width=2.5, color=RED)
    d.edge([(662, 450), (836, 450)], color=MUTED, dashed=True)

    d.group("p3", 1020, 100, 440, 440, "③ 원복", BLUE, badge="3")
    d.icon("h3", 1130, 200, "Hot 복구", kind="bucket_obj", color=AISTOR, size=60)
    d.icon("r3", 1350, 200, "Warm replica", kind="bucket", color=ORANGE, size=60)
    d.edge([(1318, 185), (1162, 185)], "⑤ 역방향 복제 / resync", at=(1240, 167), label_w=150, width=2, color=BLUE)
    d.edge([(1162, 222), (1318, 222)], "⑥ 정방향 복제 재개", at=(1240, 240), label_w=130, dashed=True, color=ORANGE)
    d.icon("dns3", 1130, 380, "DNS 원복", kind="res:route_53", color=GREEN, size=48)
    d.icon("cl3", 1350, 380, "복구용 HMS 정리", glyph="HMS", color=GREY, size=44, dashed=True, label_w=120)
    d.edge([(476, 320), (528, 320)], width=3, color=MUTED)
    d.edge([(966, 320), (1018, 320)], width=3, color=MUTED)

    chips(d, 570, ["🚨 버전 일치", "Versioning + seed", "버킷명 동일", "카탈로그 기록 · HMS 백업",
                   "삭제 전파 · 보존 기간", "DR 버킷 Transition 금지"], w=227)
    d.box("rpo", 40, 640, 1420, 80,
          "RPO = 복제 지연 + 마지막 완전 스냅샷까지 간격 (Scanner 지연 시 증가)     RTO = 장애 판단 + 검증 · register + 엔드포인트 전환\n"
          "범위 밖: 용인 데이터 (Warm 에만 존재 — 별도 백업 필요)",
          stroke=INK, fill="#F4F5F7", color=INK, size=13, bold=True)
    return d


def ic_fdc_prefix():
    d = Diagram("15-ic-fdc-prefix-replication", "ic-fdc 버킷 — prefix 단위 Replication (권장 방안 B)",
                width=1500, height=760, subtitle="unstructure/(Archive) = prefix 규칙 상시 복제 · structured/(Iceberg) = Versioning 제외 + 유지보수 후 Batch Replication")
    d.group("hot", 40, 100, 360, 470, "Hot · ic-fdc", AISTOR, badge="S3")
    d.icon("hb", 110, 385, "ic-fdc", kind="bucket_obj", color=AISTOR, size=60)
    d.icon("hu", 300, 260, "unstructure/\nArchive", kind="doc", glyph="ZIP", color=ORANGE, size=50, label_w=120)
    d.icon("hs", 300, 470, "structured/\nIceberg", kind="doc", glyph="ICE", color=PURPLE, size=50, label_w=120)
    d.text(240, 320, 120, 18, "Versioning ON", size=11, color=ORANGE, bold=True)
    d.text(225, 530, 150, 18, "Versioning 제외", size=11, color=PURPLE, bold=True)
    d.edge([(140, 370), (200, 370), (200, 260), (274, 260)], color=MUTED, arrow=False, width=1)
    d.edge([(140, 400), (200, 400), (200, 470), (274, 470)], color=MUTED, arrow=False, width=1)

    d.group("mid", 440, 100, 440, 470, "복제 수단", INK, badge="⇄")
    d.icon("rep", 660, 260, "Bucket Replication\nprefix 규칙 (상시)", glyph="REP", color=ORANGE, size=52, label_w=160)
    d.icon("mt", 530, 470, "① 유지보수\nmerge · expire", kind="k8s:job", color=PURPLE, size=50, label_w=120)
    d.icon("bt", 780, 470, "② Batch Replication\n(1회성 · 주기 실행)", kind="k8s:job", color=ORANGE, size=50, label_w=160)

    d.group("warm", 920, 100, 540, 470, "Warm · ic-fdc (replica)", WARMC, badge="W")
    d.icon("wu", 1100, 260, "unstructure/", kind="doc", glyph="ZIP", color=ORANGE, size=50)
    d.icon("ws", 1100, 470, "structured/", kind="doc", glyph="ICE", color=PURPLE, size=50)
    d.icon("wb", 1340, 365, "replica 버킷", kind="bucket", color=ORANGE, size=60)
    d.icon("wh", 1340, 500, "③ 복구 시\n검증 후 register", glyph="HMS", color=TEAL, size=44, dashed=True, label_w=130)
    d.edge([(1126, 260), (1300, 260), (1300, 335)], color=MUTED, arrow=False, width=1)
    d.edge([(1126, 470), (1300, 470), (1300, 395)], color=MUTED, arrow=False, width=1)

    d.edge([(326, 260), (634, 260)], "상시", at=(480, 242), label_w=40, width=2.5, color=ORANGE)
    d.edge([(686, 260), (1074, 260)], "ALIAS/ic-fdc/unstructure", at=(880, 242), label_w=170, width=2.5, color=ORANGE)
    d.edge([(326, 470), (504, 470)], color=PURPLE)
    d.edge([(556, 470), (754, 470)], color=PURPLE)
    d.edge([(806, 470), (1074, 470)], "prefix: structured/ · newerThan", at=(940, 452), label_w=200, width=2.5,
           dashed=True, color=ORANGE)

    chips(d, 600, ["포함 prefix 만 (제외 규칙 없음)", "--excluded-prefixes 최대 10", "resync = 버킷 단위",
                   "Batch = 1회성 · 스케줄러", "🚨 버전 일치 (Bucket Repl.)", "unstructure Transition 겹침 주의"], w=227)
    d.box("opt", 40, 665, 1420, 60,
          "A  prefix 규칙만 (structured 백업 없음)      B  ★ 권장: + structured Versioning 제외 + Batch      C  버킷 분리 (Iceberg 경로 재작성 필요)",
          stroke=INK, fill="#F4F5F7", color=INK, size=13, bold=True)
    return d


def bucket_vs_batch():
    d = Diagram("16-bucket-vs-batch-operation", "운영 모델 — Bucket Replication (AIStor 상시) vs Batch Replication (AIStor 실행 + 외부 오케스트레이션)",
                width=1500, height=760, subtitle="Batch 는 서버에서 복사하지만 1회성 — 스케줄 · 상태 확인 · 검증은 Airflow / CronJob 이 담당")
    d.group("a", 40, 100, 680, 240, "Bucket Replication — AIStor 가 상시 관리", ORANGE, badge="A")
    d.icon("ah", 130, 200, "Hot · unstructure/", kind="bucket_obj", color=AISTOR, size=56, label_w=140)
    d.icon("ae", 380, 200, "복제 엔진 (상시)", glyph="REP", color=ORANGE, size=52, label_w=130)
    d.icon("as", 380, 300, "", glyph="SCN", color=INK, size=34)
    d.text(400, 290, 180, 20, "실패 → Scanner 재큐잉", size=11, color=MUTED, align="left")
    d.icon("aw", 630, 200, "Warm", kind="bucket", color=ORANGE, size=56)
    d.edge([(162, 200), (354, 200)], "PUT 즉시", at=(258, 182), label_w=70, width=2.5, color=ORANGE)
    d.edge([(406, 200), (598, 200)], width=2.5, color=ORANGE)

    d.group("b", 760, 100, 700, 240, "Batch Replication — 복사는 AIStor 서버 (Job 단위)", PURPLE, badge="B")
    d.icon("bh", 850, 200, "Hot · structured/", kind="bucket_obj", color=AISTOR, size=56, label_w=140)
    d.icon("be", 1110, 200, "batch 워커\n(server-side)", kind="k8s:job", color=PURPLE, size=52, label_w=130)
    d.icon("bw", 1370, 200, "Warm", kind="bucket", color=ORANGE, size=56)
    d.edge([(882, 200), (1084, 200)], "1회성 Job", at=(983, 182), label_w=70, width=2.5, color=PURPLE)
    d.edge([(1136, 200), (1338, 200)], width=2.5, color=PURPLE)

    d.group("c", 40, 380, 1420, 220, "Airflow DAG / CronJob — 외부 오케스트레이션 (스케줄 · 상태 · 검증)", BLUE, badge="DAG")
    tasks = [("t1", "① 유지보수\n완료 대기", "WAIT", BLUE), ("t2", "② Job YAML\n(워터마크)", "YAML", BLUE),
             ("t3", "③ mc batch\nstart", "START", PURPLE), ("t4", "④ status\n폴링", "POLL", PURPLE),
             ("t5", "⑤ 검증\n(3단계)", "✓", GREEN), ("t6", "⑥ 워터마크 ·\nmetadata 기록", "LOG", TEAL),
             ("t7", "⑦ 알림", "!", RED)]
    xs = [140, 340, 540, 740, 940, 1140, 1340]
    for (tid, lab, g, c), x in zip(tasks, xs):
        if g in ("YAML", "LOG"):
            d.icon(tid, x, 470, lab, kind="doc", glyph=g, color=c, size=48, label_w=130)
        else:
            d.icon(tid, x, 470, lab, glyph=g, color=c, size=48, label_w=130)
    for a, b in zip(xs, xs[1:]):
        d.edge([(a + 26, 470), (b - 26, 470)], color=BLUE)
    d.edge([(540, 444), (540, 360), (1040, 360), (1040, 214), (1082, 214)], "admin API", at=(800, 360), label_w=80,
           dashed=True, color=PURPLE)
    d.edge([(1138, 214), (1190, 214), (1190, 380), (760, 380), (760, 444)], "status · notify", at=(980, 380), label_w=100,
           dashed=True, color=PURPLE)

    chips(d, 625, ["workers 기본 = CPU 절반", "workers_wait 기본 = 0ms", "list_quorum = strict",
                   "실행 창: 피크 · compaction 회피", "Warm 공유 (용인 I/O)", "재시작 재개 문구 없음 🔍"], w=227, color=ORANGE)
    d.text(40, 690, 1420, 40, "검증 3단계: Job (실패 0) → 객체 (prefix 건수 · 용량) → Iceberg (최신 스냅샷 파일 Warm HEAD 전수)",
           size=13, color=INK, bold=True, align="left")
    return d


def sc1_tiering():
    d = Diagram("17-scenario1-tiering", "시나리오 1 — Tiering (비정형 RAW · Archive → Warm, ILM 비용 절감)", width=1600, height=880)
    d.group("src", 40, 100, 170, 700, "원천", GREY, badge="SRC")
    d.icon("raw", 125, 300, "비정형 원천", glyph="RAW", color=ORANGE, size=52, label_w=110)
    d.group("ic", 250, 100, 380, 700, "이천 dataops", PURPLE, badge="k8s")
    d.icon("sp", 360, 300, "Spark 수집", glyph="Spark", color=SPARK, size=52)
    d.icon("af", 360, 540, "Airflow", glyph="DAG", color=BLUE, size=52)
    d.icon("zj", 540, 540, "zip 변환 Job", kind="k8s:job", color=BLUE, size=52, label_w=120)
    d.icon("us", 360, 720, "사용자 · Trino", kind="users", color=BLUE, size=52, label_w=120)
    d.group("hot", 670, 100, 400, 700, "Hot AIStor · 2026-02-07", AISTOR, badge="S3")
    d.icon("ilm", 780, 175, "ILM 규칙", glyph="ILM", color=ORANGE, size=44)
    d.icon("scn", 950, 175, "Scanner", glyph="SCN", color=INK, size=44)
    d.icon("rb", 780, 330, "raw/", kind="bucket_obj", color=AISTOR, size=64)
    d.icon("ab", 960, 540, "archive/", kind="bucket", color=ORANGE, size=60)
    d.group("warm", 1110, 100, 450, 700, "Warm AIStor · 2026-06-06", WARMC, badge="W")
    d.icon("tier", 1340, 430, "Warm Tier", kind="res:glacier", color=TIER, size=96)

    d.edge([(151, 300), (334, 300)], "① 수집", at=(240, 282), label_w=60, width=2)
    d.edge([(386, 300), (746, 300)], "② 적재", at=(560, 282), label_w=60, width=2)
    d.edge([(780, 215), (780, 296)], "③ 규칙", at=(820, 255), label_w=50, dashed=True, color=ORANGE)
    d.edge([(950, 215), (950, 320), (814, 320)], "④ 평가", at=(950, 270), label_w=50, dashed=True, color=INK)
    d.edge([(814, 345), (1080, 345), (1080, 410), (1290, 410)], "⑤ Transition", at=(1180, 410), label_w=90,
           width=2.5, color=ORANGE)
    d.edge([(386, 540), (514, 540)], "⑥ 트리거", at=(450, 522), label_w=60, color=BLUE)
    d.edge([(780, 380), (780, 450), (540, 450), (540, 514)], "⑦ 읽기", at=(660, 450), label_w=50, color=BLUE)
    d.edge([(566, 540), (928, 540)], "⑧ zip 저장", at=(750, 522), label_w=70, color=BLUE)
    d.edge([(990, 540), (1080, 540), (1080, 450), (1290, 450)], "⑨ Transition", at=(1180, 450), label_w=90,
           width=2.5, color=ORANGE)
    d.edge([(386, 720), (720, 720), (720, 360), (746, 360)], "⑩ GET", at=(560, 702), label_w=50, width=2, color=INK)
    d.edge([(1340, 480), (1340, 760), (740, 760), (740, 720)], "⑪ 투명 조회", at=(1040, 760), label_w=80,
           dashed=True, color=TIER)
    return d


def sc2_dr():
    d = Diagram("18-scenario2-replication-dr", "시나리오 2 — Replication (정형 Iceberg 백업 · DR, 실시간 / 주기)", width=1600, height=880)
    d.group("ic", 40, 100, 440, 700, "이천 dataops", PURPLE, badge="k8s")
    d.icon("sp", 140, 230, "Spark", glyph="Spark", color=SPARK, size=50)
    d.icon("tr", 340, 230, "Trino", glyph="Trino", color=TRINO, size=50)
    d.icon("hh", 240, 410, "HMS-Hot", glyph="HMS", color=TEAL, size=50)
    d.icon("or", 240, 580, "Oracle", kind="db", glyph="Oracle", color=ORACLE, size=50)
    d.icon("af", 140, 730, "Airflow", glyph="DAG", color=BLUE, size=50)
    d.icon("lg", 340, 730, "metadata 기록", kind="doc", glyph="LOG", color=TEAL, size=48, label_w=110)
    d.group("hot", 520, 100, 380, 700, "Hot AIStor · 2026-02-07", AISTOR, badge="S3")
    d.icon("hb", 710, 230, "structured/ (Iceberg)", kind="bucket_obj", color=AISTOR, size=64, label_w=160)
    d.icon("rep", 610, 450, "Bucket Repl.", glyph="REP", color=ORANGE, size=50)
    d.icon("bat", 810, 600, "Batch Repl.", kind="k8s:job", color=ORANGE, size=50)
    d.step(742, 196, "✕", color=RED, r=13)
    d.group("warm", 940, 100, 300, 700, "Warm AIStor · 2026-06-06", WARMC, badge="W")
    d.icon("rb", 1090, 450, "replica", kind="bucket", color=ORANGE, size=72)
    d.group("dr", 1280, 100, 280, 700, "복구 (DR)", RED, badge="DR")
    d.icon("vj", 1420, 230, "검증 Job", kind="k8s:job", color=PURPLE, size=50)
    d.icon("rh", 1420, 410, "복구용 HMS", glyph="HMS", color=TEAL, size=50)
    d.icon("dns", 1420, 580, "DNS · VIP", kind="res:route_53", color=GREEN, size=50)
    d.icon("dt", 1420, 730, "Trino · Spark", glyph="Trino", color=TRINO, size=50)

    d.edge([(165, 230), (200, 230), (200, 170), (690, 170), (690, 196)], "① 커밋", at=(440, 170), label_w=60, width=2)
    d.edge([(140, 256), (140, 410), (214, 410)], "① 포인터", at=(140, 330), label_w=60, color=TEAL)
    d.edge([(240, 436), (240, 554)], color=TEAL)
    d.edge([(690, 290), (690, 330), (610, 330), (610, 424)], color=ORANGE)
    d.edge([(636, 450), (1052, 450)], "② 실시간", at=(720, 432), label_w=70, width=2.5, color=ORANGE)
    d.edge([(730, 290), (730, 330), (810, 330), (810, 574)], color=ORANGE, dashed=True)
    d.edge([(166, 730), (240, 730), (240, 790), (810, 790), (810, 626)], "③ start", at=(520, 790), label_w=60, color=BLUE)
    d.edge([(836, 600), (1010, 600), (1010, 475), (1054, 475)], "③ 주기", at=(920, 600), label_w=60, width=2.5, dashed=True, color=ORANGE)
    d.edge([(166, 712), (314, 712)], "④ 기록", at=(240, 694), label_w=50, color=TEAL)
    d.text(680, 120, 200, 20, "⑤ 장애", size=13, color=RED, bold=True)
    d.edge([(1395, 230), (1200, 230), (1200, 430), (1128, 430)], "⑥ HEAD", at=(1290, 230), label_w=60, dashed=True, color=PURPLE)
    d.edge([(1420, 278), (1420, 384)], "⑦ register", at=(1480, 320), label_w=70, color=PURPLE)
    d.edge([(1395, 580), (1200, 580), (1200, 470), (1128, 470)], "⑧ 전환", at=(1290, 580), label_w=50, width=2.5, color=RED)
    d.edge([(1420, 704), (1420, 626)], "⑨ 재개", at=(1470, 655), label_w=50, color=RED)
    return d


def sc3_yongin():
    d = Diagram("19-scenario3-yongin-migration", "시나리오 3 — 용인 데이터 (Warm 임시 적재 → 신규 S3 일괄 이관)", width=1600, height=880)
    d.group("yi", 40, 100, 420, 700, "용인 dataops", PURPLE, badge="k8s")
    d.icon("src", 110, 250, "용인 원천", glyph="RAW", color=ORANGE, size=50)
    d.icon("sp", 300, 250, "Spark 적재", glyph="Spark", color=SPARK, size=50)
    d.icon("tr", 110, 450, "Trino", glyph="Trino", color=TRINO, size=50)
    d.icon("hw", 270, 450, "HMS-Warm", glyph="HMS", color=TEAL, size=50)
    d.icon("or", 400, 450, "Oracle", kind="db", glyph="Oracle", color=ORACLE, size=44)
    d.icon("af", 110, 650, "Airflow", glyph="DAG", color=BLUE, size=50)
    d.group("net", 500, 100, 170, 700, "네트워크", GREEN, badge="⇄")
    d.icon("fw", 545, 250, "방화벽", kind="res:network_firewall", color=RED, size=40, label_w=70)
    d.icon("vip", 625, 250, "L4 VIP", kind="res:elastic_load_balancing", color=GREEN, size=40, label_w=70)
    d.icon("dns", 585, 760, "DNS", kind="res:route_53", color=GREEN, size=44)
    d.group("warm", 710, 100, 330, 700, "Warm AIStor · 2026-06-06 (이천)", WARMC, badge="W")
    d.icon("yb", 830, 250, "yongin-* (임시)", kind="bucket", color=PURPLE, size=64, label_w=130)
    d.icon("cl", 980, 250, "임시 정리", glyph="DEL", color=GREY, size=42)
    d.icon("bat", 830, 650, "Batch Repl.", kind="k8s:job", color=ORANGE, size=52)
    d.group("new", 1080, 100, 480, 700, "신규 S3 클러스터 (향후)", BLUE, badge="NEW")
    d.icon("nb", 1320, 450, "신규 버킷", kind="bucket", color=BLUE, size=72)
    d.icon("vj", 1180, 650, "검증 Job", kind="k8s:job", color=PURPLE, size=50)
    d.icon("nh", 1460, 250, "HMS (신규 위치)", glyph="HMS", color=TEAL, size=50, label_w=120)

    d.edge([(136, 250), (274, 250)], "① 수집", at=(205, 232), label_w=50, width=2)
    d.edge([(326, 250), (524, 250)], "② 적재", at=(430, 232), label_w=50, width=2, color=PURPLE)
    d.edge([(566, 250), (604, 250)], width=2, color=PURPLE)
    d.edge([(646, 250), (797, 250)], width=2, color=PURPLE)
    d.edge([(136, 450), (244, 450)], "③ 조회", at=(190, 432), label_w=50, color=TEAL)
    d.edge([(296, 450), (378, 450)], color=TEAL)
    d.edge([(136, 650), (804, 650)], "④ mc batch start", at=(470, 632), label_w=110, color=BLUE)
    d.edge([(830, 310), (830, 624)], "⑤ 읽기", at=(870, 470), label_w=50, color=ORANGE)
    d.edge([(856, 650), (1000, 650), (1000, 450), (1283, 450)], "⑥ 일괄 이관", at=(1140, 450), label_w=80,
           width=2.5, color=ORANGE)
    d.edge([(1180, 624), (1180, 475), (1284, 475)], "⑦ 검증", at=(1180, 560), label_w=50, dashed=True, color=PURPLE)
    d.edge([(1357, 430), (1460, 430), (1460, 300)], "⑧ register", at=(1460, 365), label_w=70, color=TEAL)
    d.edge([(610, 760), (1320, 760), (1320, 512)], "⑨ 전환", at=(960, 760), label_w=50, width=2.5, color=RED)
    d.edge([(959, 250), (864, 250)], "⑩ 정리", at=(912, 210), label_w=50, dashed=True, color=GREY)
    return d

def main():
    order = [("01-icheon-hot-warm-dataops", d01), ("02-warm-standalone-yongin", d02),
             ("03-warm-coexistence", r_decision), ("04-commit-unit-mismatch", i3),
             ("05-iceberg-vs-replication-timeline", d03), ("06-scanner-impact", d07),
             ("07-ilm-archive-options", archive_options), ("08-yongin-network-checkpoints", d05),
             ("09-hot-warm-catalog-split", d06), ("10-verify-and-register", i6), ("11-todo-milestones", i7), ("12-replication-ilm-constraints", rep_ilm_constraints),
             ("13-versioning-iceberg-backup", versioning_iceberg),
             ("14-dr-failover-failback", dr_flow),
             ("15-ic-fdc-prefix-replication", ic_fdc_prefix),
             ("16-bucket-vs-batch-operation", bucket_vs_batch),
             ("17-scenario1-tiering", sc1_tiering), ("18-scenario2-replication-dr", sc2_dr),
             ("19-scenario3-yongin-migration", sc3_yongin)]
    out = os.path.join(ROOT, "diagrams")
    for name, fn in order:
        dg = fn()
        dg.name = name
        dg.save(out, out)
        print("wrote", name)


if __name__ == "__main__":
    main()
