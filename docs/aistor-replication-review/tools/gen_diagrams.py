"""aistor-replication-review 다이어그램 생성기.

실행: python3 tools/gen_diagrams.py   (aistor-replication-review/ 에서)
산출: 각 카테고리 diagrams/ 아래 *.drawio, *.gliffy, *.svg(미리보기)
"""
import os

from diagram_lib import (AISTOR, BLUE, GREEN, GREY, INK, MUTED, ORANGE, PURPLE, RED, TEAL, Diagram)

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
    d.icon("hot", 960, 260, "Hot 클러스터\n(raw/ · iceberg/)", kind="s3", color=AISTOR, size=60)
    d.icon("warm", 960, 600, "Warm 클러스터\n(replica · archive/)", kind="s3", color="#8A1C2E", size=60)
    d.edge([(960, 340), (960, 568)], "① Bucket Replication\n(비동기 · Versioning 필수)",
           at=(960, 450), label_w=170, width=2.5)
    d.edge([(990, 275), (1100, 275), (1100, 585), (990, 585)], "② ILM Transition\n(Remote Tier · Scanner)",
           at=(1100, 430), dashed=True, color=ORANGE, label_w=140)
    d.box("warn1", 860, 740, 280, 64, "⚠ ①·② 동시 적용 대상·순서 검증 필요\n근거: Global Reference PDF · Replication.pdf",
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
                "Warm 단독 사용 — 용인 dataops Trino → HMS(Oracle) ← Polaris(Lake) federation",
                width=1560, height=920,
                subtitle="데이터는 이천 Warm 클러스터에만 존재 · 용인은 카탈로그(HMS)와 조회 엔진(Trino)만 보유 · Lake는 Polaris가 HMS를 federation 하여 조회")

    d.icon("ana", 110, 300, "분석가·서비스\n(용인)", kind="k8s:user", color=BLUE)
    d.icon("lu", 110, 700, "Lake 사용자\n(Notebook·BI)", kind="k8s:user", color=BLUE)

    d.group("yi", 220, 100, 560, 460, "용인 IDC · dataops 클러스터 (신규)", PURPLE, badge="k8s")
    d.icon("trino", 330, 300, "Trino (용인)\nIceberg connector\ncatalog.type=hive_metastore",
           glyph="Trino", color=TRINO, label_w=200)
    d.icon("hms", 560, 300, "HMS (Warm 전용)\nThrift :9083", glyph="HMS", color=TEAL)
    d.icon("ora", 560, 470, "HMS DB (Oracle)\n용인용 스키마", kind="db", glyph="Oracle", color=ORACLE)
    d.edge([(136, 300), (304, 300)], "SQL", at=(200, 280), label_w=40)
    d.edge([(356, 300), (534, 300)], "① 메타데이터 조회", at=(445, 280), label_w=120)
    d.edge([(560, 370), (560, 442)], "JDBC", at=(600, 405), label_w=50)

    d.group("lake", 220, 590, 560, 260, "Lake 플랫폼", BLUE, badge="L")
    d.icon("leng", 330, 700, "Lake 엔진\n(Spark / Trino-Lake)", glyph="Engine", color=SPARK)
    d.icon("pol", 560, 700, "Apache Polaris\n(Iceberg REST Catalog)", glyph="Polaris", color=POLARIS, label_w=170)
    d.edge([(136, 700), (304, 700)])
    d.edge([(356, 700), (534, 700)], "② REST API", at=(445, 680), label_w=90)
    d.edge([(586, 700), (700, 700), (700, 300), (586, 300)],
           "③ Catalog Federation\n(HMS를 외부 카탈로그로)", at=(700, 610), label_w=160, color=POLARIS)

    d.group("net", 820, 100, 260, 750, "DC 간 연결 (용인 → 이천)", GREEN, badge="⇄")
    d.icon("fw", 950, 210, "방화벽 (용인·이천)\nTCP 443 (또는 9000)", glyph="FW", color=RED, label_w=170)
    d.icon("vip", 950, 360, "이천 L4 VIP / Ingress\n(Public 경로)", glyph="VIP", color=GREEN, label_w=170)
    d.icon("dns", 950, 510, "사내 DNS\nwarm-s3.<domain> → VIP", glyph="DNS", color=GREEN, label_w=190)
    d.edge([(330, 274), (330, 150), (950, 150), (950, 182)], "④ 데이터 파일 read (S3 API · HTTPS)",
           at=(640, 150), label_w=230, width=2.5)
    d.edge([(950, 280), (950, 332)])
    d.edge([(780, 510), (924, 510)], "⑤ 이름 해석", at=(850, 490), label_w=80, dashed=True)

    d.group("ic", 1120, 100, 400, 750, "이천 IDC · AIStor", AISTOR, badge="S3")
    d.icon("warm", 1320, 360, "Warm 클러스터\n(용인 조회 대상)", kind="s3", color="#8A1C2E", size=60)
    d.icon("hot", 1320, 650, "Hot 클러스터\n(용인 직접 접근 없음)", kind="s3", dim=True, size=60)
    d.edge([(976, 360), (1288, 360)], "HTTPS :443", at=(1060, 340), label_w=80, width=2.5)
    d.edge([(1320, 618), (1320, 432)], "Replication / ILM\n(이천 내부)", at=(1320, 525), label_w=120,
           dashed=True, color=GREY)
    d.edge([(780, 800), (1200, 800), (1200, 380), (1288, 380)],
           "⑥ Lake 엔진 데이터 read\n경로·자격증명 확인 필요", at=(1000, 800), label_w=170, dashed=True, color=RED)

    legend(d, 885, [("데이터/메타 경로", INK, False), ("카탈로그 federation", POLARIS, False),
                    ("확인 필요 경로", RED, True)])
    return d


# ---------------------------------------------------------------- 03
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
             ("wq", 1370, "Warm HMS / 조회 엔진\n(용인 Trino)", TEAL, "HMS")]
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
def d04():
    d = Diagram("04-raw-archive-rollover",
                "RAW → Archive(zip) — S3 ILM 이 해주는 것 vs 서비스가 구현해야 하는 것",
                width=1560, height=840,
                subtitle="S3/AIStor Lifecycle 액션은 Transition·Expiration 뿐 — 병합·압축·zip 패키징·rollover 는 애플리케이션 영역")

    d.group("ilm", 40, 90, 1480, 250, "S3 / AIStor ILM 이 제공하는 것 (객체 단위 1:1)", GREEN, badge="ILM")
    d.icon("raw", 165, 210, "RAW 버킷 (Hot)\n소형 객체 다수", kind="s3", color=AISTOR)
    d.icon("ilmr", 430, 210, "ILM 규칙\n(Scanner 가 비동기 평가)", glyph="ILM", color=ORANGE, label_w=170)
    d.icon("wt", 740, 150, "Warm Tier\n(동일 객체 그대로 이동)", kind="s3", color="#8A1C2E", label_w=170)
    d.icon("del", 740, 270, "삭제\n(delete marker)", glyph="DEL", color=GREY)
    d.edge([(191, 210), (404, 210)], "prefix · tag · 경과일", at=(300, 190), label_w=120)
    d.edge([(456, 200), (600, 200), (600, 150), (714, 150)], "Transition", at=(640, 130), label_w=80)
    d.edge([(456, 220), (600, 220), (600, 270), (714, 270)], "Expiration", at=(640, 290), label_w=80)
    d.box("no", 960, 120, 530, 190,
          "✕ Lifecycle 에 존재하지 않는 액션\n"
          "· 여러 객체를 하나로 병합 (묶기)\n"
          "· zip / tar.gz / zstd 압축 패키지 생성\n"
          "· 기간·크기 기준 rollover (새 아카이브 객체 생성)\n"
          "· 원본 ↔ 아카이브 정합성 검증 후 원본 삭제\n"
          "※ 서버측 압축(compression)은 투명 압축 — GET 시 원본으로 복원, 아카이브 아님",
          stroke=RED, fill=WARN_FILL, size=12, color=RED, align="left")
    d.edge([(430, 184), (430, 108), (900, 108), (900, 215), (958, 215)], "Archive(zip)?",
           at=(660, 108), label_w=90, dashed=True, color=RED)

    d.group("svc", 40, 380, 1480, 420, "서비스(데이터 엔지니어)가 직접 구현해야 하는 Rollover 파이프라인", PURPLE, badge="k8s")
    d.text(70, 420, 1000, 22, "실행 주체: k8s CronJob · Airflow DAG · Spark Job (dataops)  /  상태 저장: 체크포인트 테이블 또는 manifest 객체",
           size=12, color=MUTED, align="left")
    steps = ["① 대상 선정\nListObjectsV2\nprefix·날짜 파티션\n(rollover 기준: 기간·크기)",
             "② 읽기\nGetObject 병렬 스트리밍",
             "③ 패키징·압축\nzip / tar.zst 생성\n+ manifest(목록·checksum)",
             "④ 업로드\nMultipart PutObject\n→ archive/ 버킷 (Warm)",
             "⑤ 검증\n건수·크기·checksum 대조\n실패 시 재시도·보류",
             "⑥ 원본 정리\nDeleteObjects 또는\n태그 → ILM Expiration"]
    xs = [70, 310, 550, 790, 1030, 1270]
    for i, (x, s) in enumerate(zip(xs, steps)):
        d.box(f"s{i}", x, 470, 200, 100, s, stroke=PURPLE, fill="#F5F0FF", size=12)
        if i:
            d.edge([(xs[i - 1] + 200, 520), (x, 520)])
    d.edge([(165, 300), (165, 468)], "서비스가 직접 읽음", at=(165, 360), label_w=120, color=PURPLE)
    d.box("note", 70, 610, 1400, 150,
          "구현 시 필수 고려 사항\n"
          "· 멱등성: 재실행 시 중복 아카이브 방지 (결정적 객체 키: archive/yyyy/mm/dd/part-N.zip)\n"
          "· Versioning ON: 원본 삭제는 delete marker 만 생성 → noncurrent 만료 규칙 별도 필요\n"
          "· Object Lock(WORM) 버킷: 보존 기간 내 원본 삭제 불가 → rollover 대상 버킷 설계 시 제외\n"
          "· Replication: 원본 삭제·아카이브 업로드가 복제 규칙(delete, delete-marker)에 따라 Warm 에 어떻게 반영되는지 확인\n"
          "· 조회: zip 내부 파일은 AIStor S3 Zip 확장(x-minio-extract, 읽기 전용)으로 조회 가능 여부 검토",
          stroke=MUTED, fill="#FAFBFC", size=12, color=INK, align="left")
    return d


# ---------------------------------------------------------------- 05
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
    d = Diagram("06-hot-warm-catalog-split",
                "Hot/Warm 카탈로그 분리 — HMS-Hot(이천) · HMS-Warm(용인용) · Polaris federation",
                width=1560, height=900,
                subtitle="S3 Replication 은 데이터 파일만 복제 · 카탈로그(HMS)는 사이트별로 따로 등록/동기화해야 함")

    d.icon("lu", 100, 430, "Lake 사용자", kind="k8s:user", color=BLUE)
    d.group("lake", 200, 120, 300, 660, "Lake 플랫폼", BLUE, badge="L")
    d.icon("pol", 350, 430, "Apache Polaris\nexternal catalog\n• lake_hot → HMS-Hot\n• lake_warm → HMS-Warm",
           glyph="Polaris", color=POLARIS, label_w=210)
    d.edge([(126, 430), (324, 430)])

    d.group("ic", 560, 100, 420, 330, "이천 dataops (기존)", PURPLE, badge="k8s")
    d.icon("hmsh", 680, 250, "HMS-Hot\n(기존)", glyph="HMS", color=TEAL)
    d.icon("orah", 860, 250, "Oracle\n(Hot 스키마)", kind="db", glyph="Oracle", color=ORACLE)
    d.icon("trh", 680, 370, "Trino·Spark (이천)", glyph="Trino", color=TRINO, size=40)
    d.edge([(706, 250), (834, 250)], "JDBC", at=(770, 232), label_w=40)
    d.edge([(660, 370), (620, 370), (620, 262), (654, 262)])

    d.group("yi", 560, 460, 420, 380, "용인 dataops (신규)", PURPLE, badge="k8s")
    d.icon("hmsw", 680, 610, "HMS-Warm\n(신규)", glyph="HMS", color=TEAL)
    d.icon("oraw", 860, 610, "Oracle\n(Warm 스키마 · 신규)", kind="db", glyph="Oracle", color=ORACLE)
    d.icon("trw", 680, 750, "Trino (용인)", glyph="Trino", color=TRINO, size=40)
    d.edge([(706, 610), (834, 610)], "JDBC", at=(770, 592), label_w=40)
    d.edge([(660, 750), (620, 750), (620, 622), (654, 622)])

    d.edge([(376, 420), (530, 420), (530, 250), (654, 250)], "① lake_hot", at=(590, 232), label_w=80,
           color=POLARIS)
    d.edge([(376, 440), (530, 440), (530, 610), (654, 610)], "② lake_warm", at=(590, 592), label_w=80,
           color=POLARIS)

    d.group("s3", 1040, 100, 470, 740, "이천 AIStor", AISTOR, badge="S3")
    d.icon("hot", 1200, 250, "Hot 버킷\ns3://lake/… (hot endpoint)", kind="s3", color=AISTOR, size=60, label_w=190)
    d.icon("warm", 1200, 610, "Warm 버킷\ns3://lake/… (warm endpoint)", kind="s3", color="#8A1C2E", size=60, label_w=190)
    d.edge([(1200, 330), (1200, 578)], "Replication\n(데이터 파일만)", at=(1200, 450), label_w=110, width=2.5)
    d.box("w", 1300, 380, 200, 150,
          "⚠ 카탈로그 동기화\nHMS-Warm 에\nregister_table 필요\n버킷명 동일 유지 권장\n(다르면\nrewrite_table_path)",
          stroke=RED, fill=WARN_FILL, size=11, color=RED)
    d.edge([(680, 224), (680, 150), (1200, 150), (1200, 218)], "metadata_location", at=(950, 150), label_w=120,
           dashed=True, color=TEAL)
    d.edge([(706, 750), (1200, 750), (1200, 685)], "data read (DC 간)", at=(950, 750), label_w=120)
    d.edge([(680, 584), (680, 520), (1130, 520), (1130, 610), (1168, 610)], "metadata_location", at=(900, 520),
           label_w=120, dashed=True, color=TEAL)
    return d


def main():
    targets = {"01-architecture": [d01, d02], "02-evidence": [d03, d04], "03-future": [d05, d06]}
    for folder, fns in targets.items():
        out = os.path.join(ROOT, folder, "diagrams")
        for fn in fns:
            dg = fn()
            dg.save(out, out)
            print("wrote", folder, dg.name)


if __name__ == "__main__":
    main()
