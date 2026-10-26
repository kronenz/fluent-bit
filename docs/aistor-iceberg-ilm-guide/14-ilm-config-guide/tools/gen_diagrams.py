"""14-ilm-config-guide 다이어그램 생성기 — 서비스 개발자 설명용.

실행: python3 tools/gen_diagrams.py   (14-ilm-config-guide/ 에서)
산출: diagrams/*.drawio · *.gliffy · *.svg(미리보기)
그리기 라이브러리는 aistor-replication-review/tools/diagram_lib.py 를 그대로 쓴다 (AWS 아키텍처 스타일).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "..", "..", "aistor-replication-review", "tools"))
from diagram_lib import (AISTOR, BLUE, GREEN, GREY, INK, MUTED, ORANGE, PURPLE, RED, TEAL, WHITE,  # noqa: E402
                         Diagram)

SPARK, TRINO = "#E25A1C", "#DD00A1"
TIER, WARMC = "#5A6B86", "#8A1C2E"
OK_FILL, WARN_FILL, NOTE_FILL = "#F0F7E6", "#FFF1F0", "#F4F6F8"


# ---------------------------------------------------------------- 01
def architecture():
    d = Diagram("01-hot-only-architecture", "Hot→Warm ILM 구성 — 서비스는 Hot 엔드포인트 하나만 쓴다",
                width=1500, height=830,
                subtitle="Replication 없음 · data/ 만 1일 뒤 Warm 으로 전이 · metadata/ 는 항상 Hot · Warm 은 Hot 의 tier 계정만 접근")

    d.group("svc", 40, 100, 380, 540, "서비스 (Kubernetes)", PURPLE, badge="k8s")
    d.icon("spark", 140, 210, "Spark\n(적재 · ETL · 유지보수)", glyph="Spark", color=SPARK)
    d.icon("trino", 140, 400, "Trino / 조회 앱", glyph="Trino", color=TRINO)
    d.icon("hms", 320, 300, "Hive Metastore", glyph="HMS", color=TEAL, label_w=130)
    d.icon("db", 320, 510, "HMS DB", kind="db", glyph="DB", color=GREY)
    d.edge([(166, 200), (240, 200), (240, 292), (294, 292)])
    d.edge([(166, 400), (240, 400), (240, 312), (294, 312)], "Thrift", at=(240, 360), label_w=50)
    d.edge([(320, 372), (320, 484)], "JDBC", at=(320, 430), label_w=46)

    d.group("hot", 480, 100, 500, 540, "Hot S3 (AIStor) — 유일한 접속점", AISTOR, badge="S3")
    d.icon("wh", 580, 215, "warehouse 버킷\nVersioning ON", kind="bucket_obj", color=AISTOR, size=64, label_w=140)
    d.box("meta", 660, 160, 300, 52, "<db>.db/<tbl>/metadata/\n규칙 없음 → 항상 Hot", stroke=TEAL, fill=WHITE, size=12, bold=True)
    d.box("data", 660, 228, 300, 52, "<db>.db/<tbl>/data/\nR-1 1일 뒤 Warm 전이 · R-3 비현행 만료", stroke=ORANGE, fill=WHITE, size=12, bold=True)
    d.icon("ilm", 600, 420, "ILM 규칙\nR-1 · R-3 · R-6", glyph="ILM", color=ORANGE)
    d.icon("scan", 830, 420, "Scanner\n(만료일 도달 후 방문 시 실행)", glyph="Scan", color=GREY, label_w=190)
    d.edge([(626, 420), (804, 420)], color=MUTED, arrow=False, width=1)
    d.box("note1", 500, 530, 460, 90, "경로는 그대로 — 전이 뒤에도 s3://warehouse/…/data/x.parquet\n"
          "Iceberg · HMS · Spark 설정 변경 없음 (영향도 I-1~I-5 통과)", stroke=GREEN, fill=OK_FILL, size=12)

    d.group("warm", 1040, 100, 420, 540, "Warm S3 (AIStor) — tier 저장소", WARMC, badge="W")
    d.icon("wt", 1160, 230, "warm-tier 버킷\n(ILM 규칙 금지)", kind="bucket", color=WARMC, size=64, label_w=150)
    d.icon("tier", 1350, 230, "tier 계정\ntier-svc", kind="k8s:user", color=TIER, label_w=110)
    d.box("wnote", 1070, 380, 360, 110, "접근 계정 = tier-svc 하나 (audit 로 확인, J-7)\n"
          "서비스 자격증명 · 네트워크 경로 없음\n전이 객체 = Hot 이 대신 읽어 돌려준다", stroke=RED, fill=WARN_FILL, size=12)

    d.edge([(166, 220), (450, 220), (450, 190), (548, 190)], "S3 API (Hot 만)", at=(450, 330), label_w=100, width=2)
    d.edge([(166, 410), (450, 410), (450, 240), (548, 240)], width=2)
    d.edge([(960, 254), (1000, 254), (1000, 215), (1128, 215)], "Transition", at=(1040, 180), label_w=80,
           color=ORANGE, width=2)
    d.edge([(1128, 250), (1010, 250), (1010, 330), (640, 330), (640, 300)], "전이 파일 읽기: Hot 이 tier-svc 로 Warm GET",
           at=(820, 330), label_w=260, color=ORANGE, dashed=True)
    d.edge([(1324, 230), (1192, 230)], color=TIER, dashed=True, arrow=False, width=1)

    d.group("obs", 40, 670, 1420, 130, "모니터링 · 증적", GREEN, badge="⌁")
    d.box("o1", 70, 712, 440, 70, "audit webhook → Fluent Bit\nWarm 접근 계정 · 전이 객체 GET", stroke=GREEN, size=12)
    d.box("o2", 530, 712, 440, 70, "/minio/v2/metrics → vmagent\n전이 수 · 대기 작업 · Scanner · tier 요청", stroke=GREEN, size=12)
    d.box("o3", 990, 712, 440, 70, "Job 로그(JSONL) → judge.py · perf_report.py\nJ-1~J-8 · P-1~P-4 · I-1~I-5 · E-1~E-5", stroke=GREEN, size=12)
    return d


# ---------------------------------------------------------------- 02
def lifecycle():
    d = Diagram("02-data-lifecycle", "데이터 수명 — Hot 1일 → Warm → 기한 삭제 (권장 vs 금지)",
                width=1500, height=800,
                subtitle="예: 보존 5일 (Hot 1일 + Warm 4일) · ILM 실행 시각 = mtime + Days 를 다음 00:00 UTC 로 올림 + Scanner 방문")
    xs = [(120, "D0", "적재"), (380, "D1 → 00:00 UTC", "Warm 전이"), (880, "D5", "보존 기한"),
          (1160, "D6 → 00:00 UTC", "Warm 실데이터 삭제")]
    d.edge([(80, 140), (1440, 140)], color=INK, width=2)
    for x, a, b in xs:
        d.step(x, 140, a.split()[0], color=INK, r=16)
        d.text(x - 90, 162, 180, 34, a + "\n" + b, size=12, color=MUTED)

    d.group("ok", 40, 220, 1420, 230, "권장 — 삭제는 Iceberg 가, Warm 공간 회수는 ILM 비현행 만료가", GREEN, badge="✓")
    d.box("o1", 70, 280, 280, 140, "Hot STANDARD\n\n쓰기 · 커밋은 항상 Hot", stroke=AISTOR, size=12)
    d.box("o2", 370, 280, 470, 140, "Warm (WARM-TIER)\n\n경로 그대로 · 읽기는 Hot 경유 (+지연)\n"
          "R-1 Transition 1d", stroke=WARMC, size=12)
    d.box("o3", 860, 280, 280, 140, "Iceberg 보존 작업\nDELETE WHERE event_ts < 기한\n→ expire_snapshots\n"
          "파일 삭제 = delete marker\n(원본은 비현행으로 Warm 에)", stroke=TEAL, size=12)
    d.box("o4", 1160, 280, 270, 140, "R-3 비현행 만료 1d\n→ Warm 객체 삭제\nR-6 고아 delete marker 정리\n\n"
          "테이블은 항상 정상", stroke=GREEN, size=12, bold=True)
    for a, b in ((350, 370), (840, 860), (1140, 1160)):
        d.edge([(a, 350), (b, 350)], color=GREEN, width=2)

    d.group("ng", 40, 480, 1420, 230, "금지 — ILM current Expiration 을 data/ 에 건다", RED, badge="✗")
    d.box("n1", 70, 540, 280, 140, "Hot STANDARD", stroke=AISTOR, size=12)
    d.box("n2", 370, 540, 470, 140, "Warm (WARM-TIER)", stroke=WARMC, size=12)
    d.box("n3", 860, 540, 570, 140, "ILM 이 기한 지난 파일에 delete marker\n+ Warm 원본 즉시 삭제 (MinIO 2024-10 실측)\n\n"
          "스냅샷은 여전히 그 파일을 참조 → 조회 실패\nNotFoundException: Location does not exist", stroke=RED, fill=WARN_FILL,
          color=RED, size=12, bold=True)
    for a, b in ((350, 370), (840, 860)):
        d.edge([(a, 610), (b, 610)], color=RED, width=2)
    d.text(40, 730, 1420, 50, "시험 E-3: age6 파티션 · 전체 스캔 · time travel 모두 실패 / E-4: 같은 데이터를 Iceberg 보존 작업으로 지우면 "
           "전체 스캔 · time travel 정상, 지운 파일은 비현행으로 Warm 에 남았다가 R-3 이 회수", size=12, color=MUTED, align="left")
    return d


# ---------------------------------------------------------------- 03
def read_write_path():
    d = Diagram("03-read-write-path", "읽기 · 쓰기 경로 — 서비스 코드가 보는 것은 Hot 하나",
                width=1500, height=720, subtitle="전이 여부는 Hot 이 처리한다 · 클라이언트 설정 · SQL · 테이블 정의 변경 없음")
    cols = [(170, "Spark / 조회 앱", SPARK), (520, "Hive Metastore", TEAL), (870, "Hot S3", AISTOR), (1250, "Warm S3", WARMC)]
    for x, name, c in cols:
        d.box("h" + name, x - 110, 90, 220, 44, name, stroke=c, fill=WHITE, size=13, bold=True)
        d.edge([(x, 134), (x, 680)], color=GREY, dashed=True, arrow=False, width=1)
    rows = [
        (1, 170, 520, 180, "① 테이블 위치 · metadata_location", INK, False),
        (2, 170, 870, 230, "② metadata.json · manifest 읽기 — 항상 Hot (규칙 없음)", INK, False),
        (3, 170, 870, 290, "③ data 파일 GET — 같은 경로 (전이 여부 몰라도 됨)", INK, False),
        (4, 870, 1250, 340, "④ 전이된 파일이면 Hot 이 tier-svc 로 GET", ORANGE, False),
        (5, 1250, 870, 390, "⑤ 데이터", ORANGE, True),
        (6, 870, 170, 440, "⑥ 응답 — 시험: 파티션 읽기 +26% · 전체 스캔 +40% · 소량 조회 ~2배", ORANGE, True),
        (7, 170, 870, 520, "⑦ 쓰기 · 커밋 — 새 파일은 항상 Hot (STANDARD) · 쓰기 지연 변화 없음", INK, False),
        (8, 170, 520, 580, "⑧ metadata_location 갱신 — 스키마 · 위치 · 속성 그대로", INK, False),
    ]
    for n, a, b, y, label, c, dashed in rows:
        d.edge([(a, y), (b, y)], color=c, dashed=dashed, width=1.8)
        mid = (a + b) / 2
        d.text(min(a, b) + 10, y - 26, abs(b - a) - 20, 20, label, size=12, color=c, bg=WHITE)
    d.box("x", 1080, 600, 380, 70, "✗ 서비스 → Warm 직접 접근 없음\n(엔드포인트 · 자격증명 미배포)", stroke=RED, fill=WARN_FILL,
          color=RED, size=12, bold=True)
    return d


# ---------------------------------------------------------------- 04
def bucket_rules():
    d = Diagram("04-bucket-rules", "버킷 · 규칙 배치 — 무엇을 걸고 무엇을 걸지 않는가",
                width=1500, height=700, subtitle="규칙은 테이블 prefix 단위 · 한 버킷에 여러 테이블이면 규칙 ID 에 테이블 접두사 (mc ilm rule import 는 전체 교체)")
    d.group("tree", 40, 100, 520, 460, "버킷 구조 — Hot warehouse (Versioning ON) · Warm warm-tier", AISTOR, badge="S3")
    tree = [(0, "warehouse/", "", INK),
            (1, "<db>.db/<tbl>/", "R-6 고아 delete marker 정리", GREEN),
            (2, "metadata/", "규칙 없음 — 항상 Hot\n(*.metadata.json · snap-*.avro · manifest)", TEAL),
            (2, "data/<partition>/*.parquet", "R-1 Transition 1d → WARM-TIER\nR-3 Noncurrent 만료 1d", ORANGE)]
    y = 140
    for lvl, name, rule, c in tree:
        x = 60 + lvl * 40
        h = 40 if "\n" not in rule else 56
        d.box("t%d" % y, x, y, 480 - lvl * 40, h, name + ("\n" + rule if rule else ""), stroke=c, size=12,
              align="left", bold=(lvl == 0))
        if lvl:
            d.edge([(x - 20, y - 14), (x - 20, y + h / 2), (x, y + h / 2)], color=GREY, arrow=False, width=1)
        y += h + 20
    d.box("tw", 60, 440, 480, 90, "Warm · warm-tier 버킷\n규칙 없음 · 접근은 tier-svc 만\n(Hot 의 tier 가 객체를 opaque 이름으로 보관)",
          stroke=WARMC, fill=WARN_FILL, size=12, align="left")

    d.group("do", 600, 100, 400, 460, "건다", GREEN, badge="✓")
    cards = [("R-1", "data/ Transition 1d → WARM-TIER", "전이 대상은 데이터 파일만"),
             ("R-3", "data/ NoncurrentVersionExpiration 1d", "Iceberg 가 지운 파일의 Warm 공간 회수 (최소 1)"),
             ("R-6", "<tbl>/ ExpiredObjectDeleteMarker", "남은 delete marker 정리"),
             ("보존", "Iceberg 보존 작업 (Spark 배치)", "DELETE 기한 경과 → expire_snapshots")]
    for i, (k, a, b) in enumerate(cards):
        y = 145 + i * 100
        d.box("c" + k, 620, y, 360, 84, "{}  {}\n{}".format(k, a, b), stroke=GREEN, fill=OK_FILL, size=12, align="left")

    d.group("dont", 1040, 100, 420, 460, "걸지 않는다", RED, badge="✗")
    bans = [("data/ current Expiration", "스냅샷이 참조하는 파일 삭제 → 테이블 깨짐 (E-3)"),
            ("metadata/ Transition", "모든 쿼리 계획이 Warm 왕복"),
            ("Warm tier 버킷 규칙", "Hot 에 stub 만 남고 실데이터 소실"),
            ("버킷 전체(prefix 없음) 규칙", "다른 테이블 · 경로까지 적용")]
    for i, (a, b) in enumerate(bans):
        y = 145 + i * 100
        d.box("b%d" % i, 1060, y, 380, 84, a + "\n" + b, stroke=RED, fill=WARN_FILL, color=INK, size=12, align="left")

    d.box("scan", 40, 590, 1420, 80, "Scanner 속도: 기본(default) 4,000 객체 전이 약 15분 · fastest 25초 — 대신 유휴 CPU 상시 사용, 전이 순간 Warm CPU·메모리 급증 → "
          "기존 대량 버킷에 처음 적용할 때만 한시적으로 올리고 반드시 원복", stroke=ORANGE, fill=NOTE_FILL, size=12, align="left")
    return d


def main():
    out = os.path.join(ROOT, "diagrams")
    for fn in (architecture, lifecycle, read_write_path, bucket_rules):
        dg = fn()
        dg.save(out, out)
        print("wrote", dg.name)


if __name__ == "__main__":
    main()
