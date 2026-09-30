"""aistor-replication-review 다이어그램 생성기.

실행: python3 tools/gen_diagrams.py   (aistor-replication-review/ 에서)
산출: 각 카테고리 diagrams/ 아래 *.drawio, *.gliffy, *.svg(미리보기)
"""
import os

from diagram_lib import (AISTOR, BLUE, GREEN, GREY, INK, MUTED, ORANGE, PURPLE, RED, TEAL, WHITE, Diagram)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARK, TRINO, ORACLE, POLARIS = "#E25A1C", "#DD00A1", "#C74634", "#1F6FEB"
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
    d.box("warn1", 860, 740, 280, 64, "🚨 ① 은 Hot · Warm 동일 버전 필수 (현재 불일치)\n⚠ ①·② 동시 적용 대상 · 순서 검증 필요",
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
    d.group("wb", 1140, 150, 360, 450, "Warm 클러스터 · 2026-06-06", "#8A1C2E", badge="W")
    d.box("by", 1160, 200, 320, 90, "용인 전용 버킷 (yongin-*)\n용인 read/write · 원본\nVersioning 선택 · ILM Expiration 가능",
          stroke=PURPLE, fill="#F5F0FF", size=12, bold=True)
    d.box("br", 1160, 320, 320, 110, "이천 replica 버킷 (Hot 과 동일명)\nReplication 대상 · 백업\n용인 접근 차단 · 직접 쓰기 금지",
          stroke=ORANGE, fill="#FFF4E5", size=12)
    d.box("bt", 1160, 460, 320, 110, "ILM Tier 버킷 (전용 prefix)\nAIStor 독점 접근\n직접 접근 · ILM 규칙 금지",
          stroke=GREY, fill="#F4F5F7", size=12)
    d.edge([(976, 360), (1060, 360), (1060, 245), (1158, 245)], "HTTPS :443", at=(1060, 300), label_w=80, width=2.5, both=True)
    d.icon("hot", 1320, 720, "Hot 클러스터 · 2026-02-07\n(이천 서비스 · 용인 접근 없음)", kind="s3", dim=True, size=56, label_w=210)
    d.edge([(1250, 692), (1250, 432)], "Replication\n(버전 일치 후)", at=(1250, 640), label_w=90, dashed=True, color=GREY)
    d.edge([(1390, 692), (1390, 572)], "ILM", at=(1390, 640), label_w=40, dashed=True, color=GREY)
    d.edge([(780, 800), (1100, 800), (1100, 260), (1158, 260)],
           "⑥ Lake 엔진 데이터 read (경로·자격증명 확인)", at=(940, 800), label_w=260, dashed=True, color=RED)
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
    d.box("rep", 1080, 470, 170, 70, "Warm replica 버킷\n(백업 · 조회 안 함)", stroke=ORANGE, fill="#FFF4E5", size=11)
    d.box("tier", 1270, 470, 170, 70, "Warm tier prefix\n(AIStor 전용)", stroke=GREY, fill="#F4F5F7", size=11)
    d.box("yb", 1080, 620, 360, 70, "Warm 용인 버킷 (yongin-*)\n용인 원본 · read/write", stroke=PURPLE, fill="#F5F0FF", size=12, bold=True)
    d.edge([(1140, 322), (1140, 468)], "Replication\n🚨 동일 버전 필수", at=(1140, 400), label_w=110, width=2.5, color=ORANGE)
    d.edge([(1190, 300), (1190, 330), (1355, 330), (1355, 468)], "ILM Transition", at=(1290, 330), label_w=100,
           dashed=True, color=ORANGE)
    d.edge([(680, 224), (680, 150), (1160, 150), (1160, 220)], "metadata_location", at=(950, 150), label_w=120,
           dashed=True, color=TEAL)
    d.edge([(706, 750), (1260, 750), (1260, 692)], "data read / write (DC 간)", at=(950, 750), label_w=150, both=True)
    d.edge([(680, 584), (680, 520), (1010, 520), (1010, 655), (1078, 655)], "metadata_location", at=(850, 520),
           label_w=120, dashed=True, color=TEAL)
    d.box("note", 40, 800, 480, 60, "용인 테이블: 용인 엔진이 직접 커밋 → HMS-Warm (등록 Job 불필요)\n이천 replica: 복구 시에만 검증 후 register (그림 10)",
          stroke=TEAL, fill="#E6F7F4", color=INK, size=12, bold=True)
    return d

def d07():
    d = Diagram("07-scanner-impact", "Scanner 가 느려지면 — ILM Transition · Replication 재처리 · 버전 정리가 함께 지연",
                width=1500, height=780,
                subtitle="Scanner 는 사용량 계산 · ILM/보존 규칙 · Replication 재큐잉 · Healing 을 한 사이클에서 처리 — 느려지면 네 작업이 모두 밀린다")
    d.group("a", 40, 100, 400, 520, "Scanner 동작 방식", INK, badge="SCN")
    rows = [(150, 60, "버킷 그룹을 순차 처리", INK, WHITE),
            (230, 60, "버킷 스캔 완료 후 30초 대기\n→ 다음 버킷", INK, WHITE),
            (310, 60, "객체명 해시로 대상 선택\n16회 스캔에 걸쳐 전체 객체 1회 확인", INK, WHITE),
            (390, 60, "작업 시간 × 속도 계수(기본 10.0) 대기\n읽기/쓰기 요청에 I/O 양보(일시 정지)", INK, WHITE),
            (480, 70, "느려지는 요인\n드라이브 종류 · 네트워크 처리량\n객체 수·크기 · 기타 부하", RED, WARN_FILL)]
    for i, (y, h, t, c, f) in enumerate(rows):
        d.box(f"a{i}", 60, y, 360, h, t, stroke=c, fill=f, color=c, size=12)
        if i:
            d.edge([(240, rows[i - 1][0] + rows[i - 1][1]), (240, y)])

    d.group("b", 480, 100, 360, 520, "Scanner 가 담당하는 작업", ORANGE, badge="4")
    tasks = [(150, "① 데이터 사용량 계산"), (260, "② ILM · 보존 규칙 평가/적용\n(Transition · Expiration)"),
             (370, "③ Bucket/Site Replication\nPENDING · FAILED 객체 재큐잉"), (480, "④ 누락·손상 데이터 Healing")]
    for i, (y, t) in enumerate(tasks):
        d.box(f"b{i}", 500, y, 320, 80, t, stroke=ORANGE, fill="#FFF4E5", size=12, bold=True)
    d.edge([(440, 360), (478, 360)], "매 사이클", at=(459, 340), label_w=60)

    d.group("c", 880, 100, 580, 520, "Scanner 가 느려질 때 영향", RED, badge="!")
    imp = [(165, 50, "사용량·쿼터 수치 지연 (마지막 완료 스캔 기준)", 190),
           (255, 40, "Transition 지연 → Hot 용량 압박 · 계획보다 늦은 이동", 275),
           (305, 40, "Expiration · noncurrent 정리 지연 → 버전 누적", 325),
           (370, 80, "3회 재시도 후 큐에서 빠진 FAILED 객체의 재큐잉 지연\n→ Warm replica 누락 지속 (C1 장기화)\n→ 백업 시점 품질 저하 · 복구 시 불완전 스냅샷", 410),
           (495, 50, "누락·손상 객체 복구(Healing) 지연", 520)]
    for i, (y, h, t, ey) in enumerate(imp):
        d.box(f"c{i}", 900, y, 540, h, t, stroke=RED, fill=WARN_FILL, color=RED, size=12)
        d.edge([(820, ey), (898, ey)], color=RED)
    d.edge([(1440, 325), (1480, 325), (1480, 650), (240, 650), (240, 552)],
           "악순환: 버전·객체 수 증가 → 스캔 더 느려짐", at=(860, 650), label_w=300, dashed=True, color=RED)
    d.box("m", 40, 680, 1420, 70,
          "대응  ·  mc admin scanner info · minio_scanner_* 지표 모니터링   ·   mc replicate status / resync-backlog 로 FAILED·PENDING 수동 재큐잉\n"
          "·  noncurrent 만료 규칙으로 버전 수 억제 (excess versions 경보)   ·   scanner speed 조정은 읽기/쓰기 I/O 와 트레이드오프   ·   ILM·복제 완료 시점에 SLA 를 의존하지 말 것",
          stroke=INK, fill="#F4F5F7", size=12, bold=True)
    return d


# ================================================================ INDEX 개념도
def i3():
    d = Diagram("i3-conclusion3-unit-mismatch", "Replication 과 Iceberg 커밋 단위 불일치 — '스냅샷 묶음' vs '객체 하나씩'",
                width=1400, height=720,
                subtitle="Hot 에서는 한 번에 커밋된 스냅샷이 Warm 에는 객체별로 따로·늦게 도착 → Warm 에서 일관된 테이블 보장 안 됨")
    d.group("hot", 40, 100, 380, 440, "Hot 버킷 + HMS-Hot", AISTOR, badge="S3")
    d.box("snap", 70, 145, 320, 265, "", stroke=PURPLE, fill="#F5F0FF", dashed=True)
    d.text(80, 150, 300, 20, "Snapshot v3 — 한 번에 커밋", size=12, bold=True, color=PURPLE, align="left")
    d.box("hd", 100, 185, 260, 44, "data/*.parquet", stroke=INK)
    d.box("hm", 100, 260, 260, 44, "manifest (*.avro)", stroke=INK)
    d.box("hj", 100, 335, 260, 44, "v3.metadata.json", stroke=INK)
    d.box("hp", 70, 450, 320, 60, "HMS-Hot 포인터 → v3\n(원자 교체)", stroke=TEAL, fill="#E6F7F4", color=TEAL, bold=True)

    d.group("q", 460, 100, 440, 440, "Replication 큐 — 객체별 · 비동기", ORANGE, badge="Q")
    d.edge([(360, 207), (1000, 207)], "PENDING … (지연 / 실패)", at=(680, 190), label_w=180, dashed=True, color=RED)
    d.edge([(360, 282), (1000, 282)], "t + 2s  ✓", at=(680, 265), label_w=90, color=ORANGE)
    d.edge([(360, 357), (1000, 357)], "t + 1s  ✓ (먼저 도착)", at=(680, 340), label_w=150, color=ORANGE)
    d.edge([(390, 480), (1000, 480)], "✕ 복제 대상 아님 (Oracle 의 행)", at=(680, 463), label_w=220, dashed=True, color=RED)

    d.group("warm", 940, 100, 420, 440, "Warm replica 버킷 (백업)", "#8A1C2E", badge="S3")
    d.box("wd", 1000, 185, 300, 44, "data/*.parquet  ✕ 아직 없음", stroke=RED, fill=WARN_FILL, color=RED, dashed=True)
    d.box("wm", 1000, 260, 300, 44, "manifest  ✓", stroke=INK)
    d.box("wj", 1000, 335, 300, 44, "v3.metadata.json  ✓", stroke=INK)
    d.box("wp", 1000, 450, 300, 60, "Warm 측 카탈로그 없음\n→ 복구 시 등록 필요", stroke=RED, fill=WARN_FILL, color=RED, bold=True)

    chips = [("C1 부분 복제", "metadata 는 왔는데\ndata 가 없음"), ("C2 카탈로그 미복제", "HMS 포인터는\nS3 복제 대상 아님"),
             ("C3 삭제 전파", "expire_snapshots 삭제가\n플래그 따라 다르게 반영"), ("C4 ILM 비인지", "ILM 은 Iceberg 참조를\n모름 · 삭제 미복제"),
             ("C5 Object Lock", "보존 중 삭제 불가\n→ 유지보수 실패")]
    for i, (t, b) in enumerate(chips):
        x = 40 + i * 266
        d.box(f"ch{i}", x, 570, 250, 110, f"{t}\n{b}", stroke=RED, fill=WARN_FILL, color=RED, size=12)
    return d


def i6():
    d = Diagram("i6-conclusion6-hms-split-register", "[이천 replica 복구 절차] 검증 후 등록 — 평시 미사용, 복구·리허설 때만",
                width=1400, height=720,
                subtitle="Replication 은 데이터만 복제 → 복구 시 Warm replica 의 파일 완전성을 확인한 뒤에만 복구용 HMS 에 등록 (용인 HMS-Warm 과 별개)")
    d.group("cat", 40, 100, 1320, 230, "카탈로그 계층", TEAL, badge="HMS")
    d.icon("ic", 130, 210, "이천 Spark / Trino\n(쓰기·조회)", glyph="Trino", color=TRINO, size=48)
    d.icon("hh", 360, 210, "HMS-Hot (이천)\nOracle · 기존", glyph="HMS", color=TEAL)
    d.box("job", 560, 160, 280, 110, "복구 · 검증 Job\n① 최신 metadata_location 조회\n② Warm 에서 전체 파일 HEAD\n③ 누락 0건일 때만 register",
          stroke=PURPLE, fill="#F5F0FF", size=12, bold=True)
    d.icon("hw", 1040, 210, "복구용 HMS\n(임시 · 리허설용)", glyph="HMS", color=TEAL, label_w=180)
    d.icon("ty", 1260, 160, "복구 검증 Trino", glyph="Trino", color=TRINO, size=40)
    d.icon("pl", 1260, 260, "복구 후\n서비스 전환", glyph="DR", color=POLARIS, size=40)
    d.edge([(154, 210), (334, 210)], "커밋", at=(245, 192), label_w=40)
    d.edge([(386, 210), (558, 210)], "①", at=(470, 192), label_w=30, color=PURPLE)
    d.edge([(840, 210), (1014, 210)], "③ register_table", at=(925, 192), label_w=120, color=PURPLE, width=2.5)
    d.edge([(1240, 160), (1066, 200)])
    d.edge([(1240, 260), (1066, 220)])

    d.group("st", 40, 380, 1320, 200, "스토리지 계층 — AIStor (이천)", AISTOR, badge="S3")
    d.icon("hot", 360, 470, "Hot 버킷  s3://<bucket>/…", kind="s3", color=AISTOR, size=56, label_w=200)
    d.icon("warm", 1040, 470, "Warm replica 버킷  s3://<bucket>/… (동일 버킷명 권장)", kind="s3", color="#8A1C2E", size=56,
           label_w=280)
    d.edge([(390, 470), (1010, 470)], "Replication — 데이터 파일만 (비동기)", at=(700, 452), label_w=240, width=2.5)
    d.edge([(360, 262), (360, 440)], "commit 대상", at=(360, 350), label_w=80, dashed=True, color=TEAL)
    d.edge([(700, 270), (700, 430), (1010, 430)], "② HEAD 검증", at=(700, 350), label_w=90, dashed=True, color=PURPLE)
    d.edge([(1040, 262), (1040, 440)], "metadata_location", at=(1040, 350), label_w=120, dashed=True, color=TEAL)
    d.box("rule", 40, 610, 1320, 60,
          "⚠ 조건: Hot 스냅샷 보존 기간 > 복제 지연 + 백업 주기   |   replica 버킷은 복구 전까지 쓰기 금지 · 용인 HMS-Warm 에 섞지 않음",
          stroke=RED, fill=WARN_FILL, color=RED, size=13, bold=True)
    return d


def i7():
    d = Diagram("11-todo-milestones", "해야 할 일 — 마일스톤 (두 케이스 병행: 용인 Warm 전용 · 이천 Replication + ILM)",
                width=1560, height=700,
                subtitle="박스 안 No = INDEX §3 작업 번호 · 빨간 게이트 = 착수 전 확정할 결정 · 위 줄 = 이천 Replication/ILM · 아래 줄 = 용인 Warm 전용")
    ms = {
        "m0": (40, 270, "M0 담당자 우려 · 요구 확인\nNo 1 ~ 3\n두 케이스 범위 · RPO\nWarm 역할 분리", RED),
        "m1": (320, 140, "M1 Replication · ILM 근거 · 설계\nNo 4 ~ 11, 36 (버전 일치)\n보안 PDF · 대상 · 삭제 전파\nTier prefix · 용량", INK),
        "m2": (600, 140, "M2 이천 Replication 테스트\nNo 12 ~ 16\n백업 시점(T-B) · C1~C5\n공존 부하", ORANGE),
        "m3": (880, 140, "M3 ILM / Archive 협의 · PoC\nNo 17 ~ 21\nA · B · C · Transition 규칙", GREEN),
        "m4": (320, 400, "M4 용인 네트워크 개통\nNo 22 ~ 26\nread/write 경로 · FW · DNS", GREEN),
        "m5": (600, 400, "M5 HMS-Warm(용인) 구축\nNo 27 ~ 31\nOracle · 배포 · 권한 분리", TEAL),
        "m6": (880, 400, "M6 Polaris federation PoC\nNo 32 ~ 34\nlake_hot · lake_warm", POLARIS),
        "m7": (1220, 270, "M7 운영 이관\nNo 35\n복제·ILM·용인 운영 · 가이드", INK),
    }
    for k, (x, y, t, c) in ms.items():
        d.box(k, x, y, 240, 120, t, stroke=c, fill=WHITE, size=12)
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
    d.box("lg", 40, 580, 1470, 90,
          "두 줄은 병렬 진행 — 위: 이천 서비스(Hot → Warm replica 백업 + ILM Transition) / 아래: 용인(Warm 전용 적재·조회)\n"
          "공통 선행 = M0 · G0(Warm 버킷 역할 분리) · Warm 은 두 케이스가 공유하므로 M2 에서 공존 부하(복제 + Tier + 용인 I/O) 측정",
          stroke=MUTED, fill="#FAFBFC", size=12, align="left")
    return d

def r_decision():
    d = Diagram("03-warm-coexistence", "두 케이스 공존 — 용인 Warm 전용 + 이천 Replication · ILM (Warm 클러스터 3개 역할)",
                width=1500, height=900,
                subtitle="공존 가능 (조건부) — Warm 버킷 역할 분리 · Bucket Replication 만 사용(Site Replication 불가) · Tier prefix 독점 · replica 측 ILM 별도")
    d.group("hot", 40, 100, 330, 400, "Hot 클러스터 (이천) · 2026-02-07", AISTOR, badge="S3")
    d.icon("hb", 205, 190, "이천 서비스 버킷\n(Iceberg · RAW)", kind="s3", color=AISTOR, size=56, label_w=170)
    d.box("hilm", 60, 300, 290, 80, "ILM 규칙 (Hot)\nTransition → Warm tier\nExpiration (삭제는 복제 안 됨)", stroke=ORANGE,
          fill="#FFF4E5", size=12)
    d.box("hrep", 60, 400, 290, 80, "Bucket Replication 규칙\nHot → Warm replica (단방향)\n목적: 백업 / DR", stroke=ORANGE,
          fill="#FFF4E5", size=12)

    d.group("warm", 430, 100, 560, 400, "Warm 클러스터 · 2026-06-06 — 버킷 역할 분리", "#8A1C2E", badge="W")
    d.box("wr", 450, 150, 250, 100, "① replica 버킷 (Hot 동일명)\nReplication 대상 · Versioning\n직접 쓰기 금지 · 평시 조회 없음",
          stroke=ORANGE, fill="#FFF4E5", size=12)
    d.box("wt", 720, 150, 250, 100, "② tier 버킷 / 전용 prefix\nAIStor 독점 접근\n직접 접근 · ILM 규칙 금지", stroke=GREY,
          fill="#F4F5F7", size=12)
    d.box("wy", 450, 290, 520, 100, "③ 용인 전용 버킷 (yongin-*)\n용인 read/write 원본 · HMS-Warm 카탈로그 · 필요 시 ILM Expiration\nHot 과 복제·Tier 관계 없음",
          stroke=PURPLE, fill="#F5F0FF", size=12, bold=True)
    d.box("wilm", 450, 410, 520, 70, "replica 버킷 ILM 은 별도 설정 (Hot ILM 삭제는 복제 안 됨)\n→ noncurrent · 보존 기간을 Warm 에서 직접 관리",
          stroke=RED, fill=WARN_FILL, color=RED, size=12)
    d.edge([(350, 440), (400, 440), (400, 200), (448, 200)], "Replication", at=(400, 320), label_w=80, width=2.5, color=ORANGE)
    d.edge([(350, 320), (385, 320), (385, 86), (845, 86), (845, 148)], "Transition", at=(620, 86), label_w=80,
           dashed=True, color=ORANGE)

    d.group("yi", 1050, 100, 410, 400, "용인 dataops", PURPLE, badge="k8s")
    d.icon("yt", 1150, 200, "Trino / Spark (용인)", glyph="Trino", color=TRINO, label_w=150)
    d.icon("yh", 1350, 200, "HMS-Warm\n(Oracle)", glyph="HMS", color=TEAL)
    d.edge([(1176, 200), (1324, 200)], "메타", at=(1250, 182), label_w=40)
    d.edge([(972, 340), (1090, 340), (1090, 200), (1124, 200)], "read / write\n(DC 간 · VIP)", at=(1030, 316), label_w=100, width=2.5, both=True)
    d.box("ynote", 1070, 390, 370, 90, "용인 접근 키 = yongin-* 버킷만 허용\nreplica · tier 버킷 접근 차단", stroke=PURPLE,
          fill=WHITE, size=12)

    d.group("chk", 40, 530, 1420, 350, "공존 조건 · 확인 사항", RED, badge="!")
    conds = [("C-1 복제 방식 · 버전 🚨", "Bucket Replication · 원본/대상 동일 버전 필수\n현재 Hot 2026-02-07 ≠ Warm 2026-06-06\n→ 복제 구성 전 버전 일치 (Site Replication 불가)"),
             ("C-2 버킷 분리", "replica · tier · 용인 버킷 분리\n이름 충돌 방지 (Hot 동일명 예약)\n키 권한 분리"),
             ("C-3 Tier 규칙", "tier 버킷/prefix 는 AIStor 전용\n직접 수정 · 삭제 · ILM 금지\n(위반 시 데이터 유실)"),
             ("C-4 용량", "Transition + Replication 대상이\n겹치면 Warm 에 이중 저장\n→ 대상 prefix 설계 · 용량 산정"),
             ("C-5 부하", "Warm = 복제 수신 + Tier 수신 +\n용인 read/write + Scanner\n→ 성능 경합 측정 필요"),
             ("C-6 백업 품질", "replica 는 스냅샷 일관성 없음\n→ 백업 시점 테스트(T-B) ·\n복구 시 검증 후 등록")]
    for i, (t, b) in enumerate(conds):
        x = 60 + (i % 3) * 470
        y = 580 + (i // 3) * 145
        d.box(f"c{i}", x, y, 450, 125, f"{t}\n{b}", stroke=RED, fill=WARN_FILL, color=INK, size=12)
    return d

def archive_options():
    d = Diagram("07-ilm-archive-options", "RAW 아카이브 방식 선택지 — A. zip 미사용 · B. 하이브리드 · C. 전면 Rollover (협의 필요)",
                width=1500, height=800,
                subtitle="ILM 은 Transition · Expiration 만 제공 (zip 생성 불가) · 하이브리드는 '변환은 서비스, 이관은 ILM' 으로 역할 분리")
    cols = [(40, "A. zip 미사용 — RAW 그대로 ILM", GREEN, False,
             ["RAW 객체 (Hot)", "ILM Transition\n(prefix · 경과일)", "Warm Tier\n(객체 1:1 · Hot 엔드포인트로 조회)"],
             "장점: 구현 없음 · 조회 경로 그대로\n고려: 소형 객체 수 유지 → Warm 객체 수·\nScanner 부하 · 압축 이득 없음\n(서버측 투명 압축으로 일부 보완)"),
            (520, "B. 하이브리드 — 서비스 zip + ILM 이관", ORANGE, False,
             ["① 서비스: 정책 시점에 zip 변환\n(예: 파티션 마감 N일 후)\n→ archive/ prefix 에 저장", "② ILM Transition 규칙\n(archive/ prefix 또는 tag)", "Warm Tier\n(zip 객체 이관)"],
             "장점: 객체 수 감소 · 이관·재시도는 ILM 담당\n→ 서비스 구현 범위 축소\n고려: zip 변환·검증·원본 정리는 서비스 ·\n조회 시 zip 해제 필요 (S3 Zip 확장 🔍)"),
            (1000, "C. 전면 Rollover (기존안)", GREY, True,
             ["서비스: 대상 선정 · 읽기", "서비스: zip 생성 · 업로드\n(Warm archive/ 직접)", "서비스: 검증 · 원본 정리"],
             "장점: 시점·형식 완전 제어\n고려: 구현·운영 부담 최대 ·\nWarm 직접 쓰기 시 복제 방향과 충돌 가능")]
    for x, title, c, dashed, flow, note in cols:
        d.group(f"g{x}", x, 100, 460, 540, title, c, badge="", dashed=dashed)
        for i, t in enumerate(flow):
            y = 150 + i * 105
            d.box(f"f{x}{i}", x + 40, y, 380, 75, t, stroke=c, fill=WHITE, size=12)
            if i:
                d.edge([(x + 230, y - 30), (x + 230, y)], color=c)
        d.box(f"n{x}", x + 20, 480, 420, 140, note, stroke=MUTED, fill="#FAFBFC", size=12, align="left")
    d.box("dec", 40, 665, 1420, 105,
          "협의 필요 — 결정 기준: ① 아카이브 데이터 조회 요구(빈도 · 방식)  ② 소형 객체 수 · Scanner 부하  ③ 압축 이득(용량)  ④ 서비스 구현 · 운영 부담  ⑤ 보존 · 삭제 정책\n"
          "권고 순서: A 로 시작 가능한지 확인 → 객체 수·용량 문제가 확인되면 B(하이브리드) → C 는 B 로 해결되지 않는 요구가 있을 때만",
          stroke=RED, fill=WARN_FILL, color=RED, size=13, bold=True, align="left")
    return d


def main():
    order = [("01-icheon-hot-warm-dataops", d01), ("02-warm-standalone-yongin", d02),
             ("03-warm-coexistence", r_decision), ("04-commit-unit-mismatch", i3),
             ("05-iceberg-vs-replication-timeline", d03), ("06-scanner-impact", d07),
             ("07-ilm-archive-options", archive_options), ("08-yongin-network-checkpoints", d05),
             ("09-hot-warm-catalog-split", d06), ("10-verify-and-register", i6), ("11-todo-milestones", i7)]
    out = os.path.join(ROOT, "diagrams")
    for name, fn in order:
        dg = fn()
        dg.name = name
        dg.save(out, out)
        print("wrote", name)


if __name__ == "__main__":
    main()
