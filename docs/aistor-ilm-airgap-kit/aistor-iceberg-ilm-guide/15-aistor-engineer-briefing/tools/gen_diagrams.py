"""15-aistor-engineer-briefing 다이어그램 생성기 — 엔지니어 방문 사전 학습용.

실행: python3 tools/gen_diagrams.py   (15-aistor-engineer-briefing/ 에서)
산출: diagrams/*.drawio · *.gliffy · *.svg(미리보기)
그리기 라이브러리는 aistor-replication-review/tools/diagram_lib.py 를 그대로 쓴다 (14장 그림과 같은 스타일).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "..", "..", "aistor-replication-review", "tools"))
from diagram_lib import (AISTOR, BLUE, GREEN, GREY, INK, MUTED, ORANGE, PURPLE, RED, TEAL, WHITE,  # noqa: E402
                         Diagram)

SPARK = "#E25A1C"
TIER, WARMC = "#5A6B86", "#8A1C2E"
OK_FILL, WARN_FILL, NOTE_FILL, ORANGE_FILL = "#F0F7E6", "#FFF1F0", "#F4F6F8", "#FFF4E8"


def arrow(d, a, b, label=None, color=INK, dashed=False, at=None, label_w=150, width=1.5):
    d.edge([a, b], label, at=at, dashed=dashed, color=color, label_w=label_w, width=width)


# ---------------------------------------------------------------- 01
def scanner_cycle():
    d = Diagram("01-scanner-cycle", "Scanner — 모든 버킷 · 폴더 · 객체 · 버전을 쉬지 않고 한 바퀴씩",
                width=1500, height=820,
                subtitle="ILM 규칙은 판단 기준일 뿐 · 실행은 Scanner 가 그 객체를 방문할 때 · 한 번의 방문에서 ILM 외 일도 같이 한다")
    d.group("cl", 40, 100, 560, 560, "Hot 클러스터 — 순회 대상", AISTOR, badge="S3")
    d.box("b1", 70, 145, 240, 40, "버킷 warehouse", stroke=AISTOR, bold=True)
    folders = ["db.db/tbl/data/p=10-24/", "db.db/tbl/data/p=10-25/", "db.db/tbl/data/p=10-26/", "db.db/tbl/metadata/"]
    for i, f in enumerate(folders):
        y = 205 + i * 62
        d.box("f%d" % i, 110, y, 260, 44, f, stroke=GREY, size=12, align="left")
        d.step(400, y + 22, str(i + 1), color=ORANGE, r=13)
        d.edge([(90, 185), (90, y + 22), (110, y + 22)], color=GREY, arrow=False, width=1)
        d.icon("o%d" % i, 470, y + 22, "", kind="doc", color=GREY, size=34)
        d.text(495, y + 8, 100, 28, "객체 × 버전", size=11, color=MUTED, align="left")
    d.box("b2", 70, 470, 240, 40, "버킷 raw · 기타 …", stroke=AISTOR, bold=True)
    d.box("loop", 70, 540, 500, 96, "폴더 하나씩 처리 → 다음 폴더 (사이 사이 '쉬는 시간' = speed)\n"
          "모든 버킷을 다 돌면 1 사이클 → 잠시 쉬고 다음 사이클\n"
          "실측 4,000 객체: 100개(폴더 1개)씩 계단 · 기본 914초 / fastest 25초", stroke=ORANGE, fill=ORANGE_FILL, size=12, align="left")
    d.edge([(570, 290), (630, 290)], color=INK, width=2)

    d.group("visit", 640, 100, 440, 560, "한 객체 방문 때 하는 일", GREY, badge="⟳")
    jobs = [("① 사용량 집계", "버킷 · prefix 크기 · 객체 수 · 버전 수", GREY),
            ("② ILM 평가", "Transition · Expiration · Noncurrent · DM 정리\n만기면 작업 큐로", ORANGE),
            ("③ Healing 점검", "일정 확률로 조각 무결성 확인 · 복구", GREY),
            ("④ 복제 점검", "실패 · 대기 객체 재큐잉 (Replication 사용 시)", GREY),
            ("⑤ 경보", "버전 과다(100) · 폴더 과다(50,000)", GREY)]
    for i, (a, b, c) in enumerate(jobs):
        y = 145 + i * 100
        d.box("j%d" % i, 670, y, 380, 80, a + "\n" + b, stroke=c, fill=ORANGE_FILL if c == ORANGE else WHITE,
              size=12, align="left", bold=(c == ORANGE))
    d.edge([(1050, 285), (1140, 285)], color=ORANGE, width=2)

    d.group("q", 1140, 100, 320, 560, "ILM 작업", ORANGE, badge="ILM")
    d.box("tq", 1165, 160, 270, 70, "전이 작업 큐\n→ tier 계정으로 Warm 에 PUT", stroke=ORANGE, size=12)
    d.box("eq", 1165, 250, 270, 70, "만료 작업\n→ delete marker / 삭제 · tier journal", stroke=ORANGE, size=12)
    d.box("put", 1165, 420, 270, 110, "PUT 순간 이미 만기?\n(0d 규칙 · 태그 + 0d · 소급)\n→ Scanner 없이 즉시 큐로", stroke=GREEN,
          fill=OK_FILL, size=12, bold=True)
    d.edge([(1300, 400), (1300, 420)], color=GREEN, arrow=False)
    d.text(1165, 380, 270, 22, "PUT 요청", size=12, color=GREEN, bold=True)
    d.edge([(1300, 420), (1300, 330)], color=GREEN, dashed=True)
    d.box("miss", 1165, 560, 270, 70, "큐가 넘치면\nmissed_immediate_tasks ↑ (질의 Q-I1)", stroke=RED, fill=WARN_FILL, size=12)

    d.box("note", 40, 690, 1420, 100, "speed 를 올리면 ①~⑤ 가 모두 빨라진다 → ILM 만 빠르게 할 수 없다 (질의 Q-S1) · fastest 는 할 일이 없어도 Hot CPU 14m → 82m (실측)\n"
          "규칙의 만기가 지나도 Scanner 가 그 폴더에 오기 전까지는 아무 일도 없다 → ILM 반응 시간 = Days + 00:00 올림 + 사이클 길이",
          stroke=INK, fill=NOTE_FILL, size=13, align="left")
    return d


# ---------------------------------------------------------------- 02
def ilm_timing():
    d = Diagram("02-ilm-timing", "ILM 실행 시각 — mtime + Days → 다음 00:00 UTC → Scanner 방문",
                width=1500, height=760, subtitle="1d 규칙의 실제 지연 = 1일 + (0~24시간 올림) + Scanner 대기 · 실측 1d 연속: 10-25 20:54 적재 → 10-27 00:15 전이")
    y = 190
    d.edge([(80, y), (1440, y)], color=INK, width=2)
    pts = [(140, "10-25 20:54", "① 객체 생성 (mtime)", AISTOR),
           (560, "10-26 20:54", "② mtime + Days(1)", ORANGE),
           (900, "10-27 00:00 UTC", "③ 다음 00:00 으로 올림 = 만기", ORANGE),
           (1200, "10-27 00:15", "④ Scanner 방문 → 전이 ✓", GREEN)]
    for x, t, lab, c in pts:
        d.step(x, y, lab[0], color=c, r=16)
        d.text(x - 110, y - 62, 220, 22, t, size=13, color=c, bold=True)
        d.text(x - 110, y + 24, 220, 22, lab[2:], size=12, color=INK)
    for a, b, lab, c in ((140, 560, "Days = 1일", ORANGE), (560, 900, "올림: 0 ~ 24시간 (3시간 6분)", ORANGE),
                         (900, 1200, "Scanner 대기: 사이클 위치에 따라 (15분)", GREY)):
        d.edge([(a + 18, 262), (b - 18, 262)], lab, at=((a + b) / 2, 262), label_w=260, color=c, both=True)

    d.group("put", 40, 330, 1420, 210, "Scanner 를 거치지 않는 길 — PUT 순간 이미 만기", GREEN, badge="⚡")
    steps = [("PUT 요청", "새 파일 · 소급 PUT · 태그 붙인 PUT"), ("규칙 평가 (PUT 시)", "만기 ≤ 지금 ?"),
             ("즉시 작업 큐", "Scanner 무관"), ("Warm 전이 / 만료", "같은 초 (실측 T-1)")]
    for i, (a, b) in enumerate(steps):
        x = 80 + i * 345
        d.box("p%d" % i, x, 390, 290, 110, a + "\n\n" + b, stroke=GREEN, fill=OK_FILL if i == 3 else WHITE, size=13, bold=(i == 3))
        if i:
            arrow(d, (x - 55, 445), (x, 445), color=GREEN, width=2)

    d.group("ex", 40, 570, 1420, 160, "실측 예", INK, badge="실측")
    rows = ["1d 연속 첫 배치    10-25 20:54 + 1d = 10-26 20:54 → 10-27 00:00 → 10-27 00:15 전이",
            "기한 삭제 age-4.5   10-21 13:49 + 5d = 10-26 13:49 → 10-27 00:00 → 10-27 00:07 delete marker",
            "비현행 만료         DM 10-26 01:50 + 1d = 10-27 01:50 → 10-28 00:00 → 이후 첫 방문에 소멸",
            "하루치 객체가 모두 같은 00:00 UTC (= KST 09:00) 에 만기 → 업무 시작 시각에 쏠림"]
    for i, r in enumerate(rows):
        d.text(70, 610 + i * 28, 1370, 24, r, size=13, color=RED if i == 3 else INK, align="left", bold=(i == 3))
    return d


# ---------------------------------------------------------------- 03
def load_levers():
    d = Diagram("03-scanner-load-levers", "Scanner 부하 모델 — 무엇이 비용을 만들고, 어떤 손잡이로 줄이나",
                width=1500, height=760, subtitle="권장 순서: A 셀 대상 줄이기 → B ILM 을 Scanner 밖으로 → C 시간대별 속도")
    d.box("f1", 250, 100, 1000, 56, "사이클 비용 ∝ (객체 수 × 평균 버전 수 + 폴더 수) × 객체당 처리(ILM · 사용량 · healing · 복제)",
          stroke=INK, fill=NOTE_FILL, size=14, bold=True)
    d.box("f2", 250, 170, 1000, 44, "ILM 반응 시간 ≈ Days + 00:00 올림(0~24h) + 사이클 길이(= 비용 ÷ 속도)", stroke=INK, fill=NOTE_FILL, size=14, bold=True)

    d.group("a", 40, 260, 450, 400, "A. 셀 대상 줄이기", GREEN, badge="A")
    for i, t in enumerate(["파일 수 — compaction 256~512 MB\n10 MB × 1만 → 512 MB × 200 (1/50)",
                           "버전 수 — Noncurrent 1d · NewerNoncurrent 질의\nIceberg 삭제 = 비현행 + DM",
                           "delete marker — ExpiredObjectDeleteMarker",
                           "폴더 — 파티션 너무 잘게 X · 폴더당 객체 경보"]):
        d.box("a%d" % i, 65, 305 + i * 85, 400, 70, t, stroke=GREEN, fill=OK_FILL, size=12, align="left")
    d.group("b", 525, 260, 450, 400, "B. ILM 을 Scanner 밖으로", ORANGE, badge="B")
    for i, t in enumerate(["태그 기반 즉시 전이 (03 문서)\ncompaction 이 태그 붙여 쓰면 PUT 순간 Warm",
                           "Soft delete 태그 (04 문서)\nILM 은 Iceberg 가 지운 파일만 만료",
                           "Batch 전이 작업 질의 Q-I7",
                           "효과: 전이가 사이클과 무관 → Scanner 를 낮춰도 됨"]):
        d.box("b%d" % i, 550, 305 + i * 85, 400, 70, t, stroke=ORANGE, fill=ORANGE_FILL if i < 2 else WHITE, size=12, align="left")
    d.group("c", 1010, 260, 450, 400, "C. 시간대별 속도", BLUE, badge="C")
    for i, t in enumerate(["업무 시간 slow · 야간 default/fast\nCronJob 으로 speed 변경",
                           "전제: 즉시 반영 질의 Q-S4",
                           "자정(KST 09:00) 쏠림 — B 로 제거가 확실",
                           "주의: 반응 시간은 오히려 늘 수 있다"]):
        d.box("c%d" % i, 1035, 305 + i * 85, 400, 70, t, stroke=BLUE, size=12, align="left")
    for x in (265, 750, 1235):
        d.edge([(x, 260), (x, 214)], color=GREY, dashed=True)
    d.box("n", 40, 680, 1420, 56, "실측: fastest 유휴 Hot CPU 14m → 82m · 기본 4.5 객체/s (단일 노드) · 전이 후 읽기 지연은 파일 수에 비례 (파티션 +26% · 전체 스캔 +40%)",
          stroke=INK, fill=NOTE_FILL, size=13, align="left")
    return d


# ---------------------------------------------------------------- 04
def tag_tiering():
    d = Diagram("04-tag-tiering-flow", "태그 기반 즉시 전이 — compaction 이 태그 붙여 쓰면 PUT 순간 Warm",
                width=1500, height=800, subtitle="규칙 Transition 0d · And{Prefix <tbl>/data/, Tag ilm-tier=warm} · 안전망 Transition 3d (태그 없음) · 실측 T-1 실측")
    d.group("sp", 40, 100, 380, 520, "Spark (Kubernetes)", PURPLE, badge="k8s")
    d.icon("w", 140, 200, "평소 적재\n카탈로그 hive_prod (태그 없음)", glyph="Spark", color=SPARK, label_w=220)
    d.icon("c", 140, 420, "tiering compaction (매일 02:00)\n카탈로그 hive_tier\ns3.write.tags.ilm-tier=warm",
           glyph="Job", color=ORANGE, label_w=240)
    d.box("cw", 240, 380, 160, 80, "rewrite_data_files\nwhere: < 오늘-1일\n4 파일 → 1 파일", stroke=ORANGE, size=11)

    d.group("hot", 480, 100, 520, 520, "Hot · warehouse 버킷", AISTOR, badge="S3")
    d.box("h1", 510, 160, 460, 60, "data/p=오늘/  새 파일 (태그 없음) → STANDARD", stroke=AISTOR, size=12)
    d.box("h2", 510, 250, 460, 60, "data/p=옛날/  작은 파일들 (태그 없음) → STANDARD\n다음 expire_snapshots 에서 정리", stroke=GREY, size=12)
    d.box("h3", 510, 340, 460, 70, "data/p=옛날/  compaction 결과 (태그 ilm-tier=warm)\n→ 규칙 만족 → PUT 순간 Warm 전이 ⚡", stroke=ORANGE,
          fill=ORANGE_FILL, size=12, bold=True)
    d.box("h4", 510, 440, 460, 70, "metadata/  같은 커밋 파일 — 태그는 붙지만\nprefix 조건(data/) 때문에 STANDARD 유지 ✓", stroke=TEAL, size=12)
    d.box("rule", 510, 535, 460, 70, "R-T  0d · And{data/, ilm-tier=warm}  (가속 경로)\nR-1  3d · data/  (안전망 — Scanner)", stroke=INK,
          fill=NOTE_FILL, size=12, align="left")

    d.group("warm", 1060, 100, 400, 520, "Warm · tier", WARMC, badge="W")
    d.icon("wt", 1260, 250, "warm-tier 버킷", kind="bucket", color=WARMC, size=64)
    d.box("wn", 1090, 420, 340, 90, "compaction 된 큰 파일만 도착\n→ Warm 파일 수 ↓ · Warm 경유 읽기 ↓", stroke=WARMC, size=12)

    arrow(d, (166, 200), (510, 190), "PUT", color=INK, at=(330, 182), label_w=40)
    d.edge([(400, 420), (450, 420), (450, 375), (510, 375)], color=ORANGE, width=2)
    d.edge([(970, 375), (1020, 375), (1020, 250), (1228, 250)], "즉시 전이 (같은 초)", at=(1110, 235), label_w=140, color=ORANGE, width=2)

    d.group("res", 40, 650, 1420, 130, "T-1 실측 · 한계", INK, badge="실측")
    lines = ["새 파일 00:34:15 PUT → 00:34:15 WARM-TIER · metadata 4개 STANDARD · old/new 조회 checksum 일치",
             "이미 있는 객체에 나중에 태그(PutObjectTagging) → 즉시 전이 안 됨 (Scanner 대기) → 태그는 쓸 때 붙인다",
             "질의 Q-I1 즉시 전이 큐 보장 · 넘칠 때 동작 — 안전망 규칙과 missed_immediate_tasks 감시 필수"]
    for i, t in enumerate(lines):
        d.text(70, 690 + i * 28, 1370, 24, t, size=13, color=RED if i == 2 else INK, align="left")
    return d


# ---------------------------------------------------------------- 05
def soft_delete():
    d = Diagram("05-soft-delete-flow", "Iceberg × ILM 만료 — 나이 기반은 테이블을 깨고, soft delete 태그는 안전하다",
                width=1500, height=800, subtitle="Iceberg 의 살아 있는 파일 = 남은 스냅샷이 참조하는 파일 · S3 수명주기는 객체 나이만 본다")
    d.group("ng", 40, 100, 1420, 280, "✗ 나이 기반 Expiration (data/ · 5일) — E-3", RED, badge="✗")
    xs = [70, 400, 730, 1060]
    ng = [("Iceberg 스냅샷", "age6 · age2 · age0 파티션\n모두 참조 중", PURPLE),
          ("ILM (나이만 봄)", "age6 파일 나이 > 5일\n→ 만료", ORANGE),
          ("S3", "delete marker\n+ Warm 원본 삭제", AISTOR),
          ("조회", "age6 · 전체 스캔 · time travel\n✗ NotFoundException", RED)]
    for i, (a, b, c) in enumerate(ng):
        d.box("n%d" % i, xs[i], 160, 300, 160, a + "\n\n" + b, stroke=c, fill=WARN_FILL if i == 3 else WHITE, size=13,
              bold=(i == 3), color=RED if i == 3 else INK)
        if i:
            arrow(d, (xs[i] - 30, 240), (xs[i], 240), color=RED, width=2)

    d.group("ok", 40, 410, 1420, 280, "✓ Soft delete 태그 + 태그 필터 Expiration — T-2", GREEN, badge="✓")
    ok = [("Iceberg 보존 작업", "DELETE · expire_snapshots\n카탈로그: s3.delete-enabled=false", TEAL),
          ("S3 (지우지 않음)", "태그만\niceberg-deleted=true", AISTOR),
          ("ILM (태그만 봄)", "Expiration 1d\nAnd{data/, iceberg-deleted}", ORANGE),
          ("결과", "태그 4개만 delete marker\n같은 나이 살아 있는 4개 그대로\n테이블 정상 ✓", GREEN)]
    for i, (a, b, c) in enumerate(ok):
        d.box("o%d" % i, xs[i], 470, 300, 160, a + "\n\n" + b, stroke=c, fill=OK_FILL if i == 3 else WHITE, size=13, bold=(i == 3))
        if i:
            arrow(d, (xs[i] - 30, 550), (xs[i], 550), color=GREEN, width=2)
    d.box("tail", 40, 715, 1420, 66, "이어서 (Versioning ON): 비현행 1d → 00:00 올림 → Warm 공간 회수 · 고아 delete marker 정리 (실측 E-5 10-28 00:00 UTC)\n"
          "Expiration Days 는 객체 생성 시점부터 센다 → 보존 작업이 지운 오래된 파일은 다음 Scanner 방문에 바로 처리",
          stroke=INK, fill=NOTE_FILL, size=12, align="left")
    return d


# ---------------------------------------------------------------- 06
def repl_inconsistency():
    d = Diagram("06-replication-inconsistency", "Iceberg 커밋 vs 객체 복제 — replica 가 깨진 스냅샷을 보는 순간",
                width=1500, height=760, subtitle="Iceberg: 파일을 다 쓰고 마지막에 포인터를 바꾼다 · 복제: 객체마다 독립 · 비동기 · 재시도 → 도착 순서 보장 없음")
    d.group("hot", 40, 100, 420, 480, "Hot — 커밋 순서", AISTOR, badge="S3")
    seq = ["① data 파일 a · b · c", "② manifest (a · b · c 목록)", "③ manifest list (snap)", "④ metadata.json v5", "⑤ HMS 포인터 → v5 (커밋)"]
    for i, t in enumerate(seq):
        d.box("s%d" % i, 70, 150 + i * 80, 360, 56, t, stroke=TEAL if i == 4 else AISTOR, size=13, bold=(i == 4))
        if i:
            arrow(d, (250, 150 + i * 80 - 24), (250, 150 + i * 80), color=GREY)

    d.group("q", 520, 100, 420, 480, "복제 큐 — 객체 단위", ORANGE, badge="⇄")
    arr = [("metadata.json v5", "도착 ✓", GREEN), ("manifest · manifest list", "도착 ✓", GREEN),
           ("data a · b", "도착 ✓", GREEN), ("data c", "대기 / 실패 → 재큐 (Scanner)", RED)]
    for i, (a, b, c) in enumerate(arr):
        d.box("q%d" % i, 550, 150 + i * 95, 360, 70, a + "\n" + b, stroke=c, size=13, fill=WARN_FILL if c == RED else WHITE)

    d.group("rep", 1000, 100, 460, 480, "Replica", WARMC, badge="W")
    d.box("r1", 1030, 160, 400, 120, "metadata.json v5 · manifest 있음\ndata c 없음", stroke=WARMC, size=13)
    d.box("r2", 1030, 310, 400, 110, "이 시점에 v5 를 등록 · 조회하면\n✗ NotFoundException (C1)", stroke=RED, fill=WARN_FILL, color=RED, size=13, bold=True)
    d.box("r3", 1030, 450, 400, 100, "HMS 는 복제되지 않음 (C2)\n→ 어느 metadata.json 을 등록할지 판단 필요", stroke=TEAL, size=12)
    arrow(d, (430, 330), (550, 330), color=ORANGE, width=2)
    arrow(d, (910, 220), (1030, 220), color=ORANGE, width=2)

    d.group("c", 40, 610, 1420, 120, "충돌 C1~C4 (aistor-replication-review 근거 2)", RED, badge="!")
    chips = ["C1 부분 복제 스냅샷", "C2 카탈로그 미복제", "C3 삭제 전파 불일치 (백업 vs 미러)", "C4 replica ILM 이 참조를 모름"]
    for i, t in enumerate(chips):
        d.box("c%d" % i, 70 + i * 345, 650, 320, 56, t, stroke=RED, fill=WARN_FILL, color=RED, size=13, bold=True)
    return d


# ---------------------------------------------------------------- 07
def repl_solutions():
    d = Diagram("07-replication-solutions", "복제 해결안 — R-A 파일 복제 + 검증 후 등록 · R-B Iceberg rewrite_table_path",
                width=1500, height=800, subtitle="공통 원칙: replica 카탈로그는 '모든 파일이 도착한 스냅샷' 만 가리킨다")
    d.group("ra", 40, 100, 1420, 300, "R-A  버킷 Replication 그대로 + replica 쪽 검증 작업 → register_table", GREEN, badge="A")
    xa = [70, 360, 650, 940, 1230]
    ra = [("Hot", "평소 쓰기", AISTOR), ("버킷 Replication", "data/ · metadata/\n객체 단위 비동기", ORANGE),
          ("Replica 버킷", "도착 순서 무작위", WARMC), ("검증 작업 (15분)", "최신 metadata.json →\nmanifest → data HEAD\n전부 있으면 통과", TEAL),
          ("Replica 카탈로그", "register_table\n(실패 시 이전 스냅샷 유지)", GREEN)]
    for i, (a, b, c) in enumerate(ra):
        d.box("a%d" % i, xa[i], 160, 210, 180, a + "\n\n" + b, stroke=c, size=12, bold=(i == 4), fill=OK_FILL if i == 4 else WHITE)
        if i:
            arrow(d, (xa[i] - 80, 250), (xa[i], 250), color=GREEN, width=2)
    d.group("rb", 40, 430, 1420, 300, "R-B  Iceberg 수준 복사 (1.8+) — 스냅샷 단위 일관성", BLUE, badge="B")
    rb = [("Hot", "rewrite_table_path\nsource → target prefix\n증분: start/end version", AISTOR),
          ("복사 목록", "file_list_location\n(원본 → 대상 경로)", TEAL),
          ("복사", "Batch Replication 질의\n· distcp · mc mirror", ORANGE),
          ("대상 버킷", "경로 재작성된 metadata\n+ data", WARMC),
          ("대상 카탈로그", "register_table\n(latest_version)", GREEN)]
    for i, (a, b, c) in enumerate(rb):
        d.box("b%d" % i, xa[i], 490, 210, 180, a + "\n\n" + b, stroke=c, size=12, bold=(i == 4), fill=OK_FILL if i == 4 else WHITE)
        if i:
            arrow(d, (xa[i] - 80, 580), (xa[i], 580), color=BLUE, width=2)
    d.text(40, 745, 1420, 40, "R-A: 기존 기능 그대로 · 같은 경로 · RPO = 복제 지연 + 검증 주기   |   R-B: 경로 달라도 됨 · 정확한 시점 · 복사 오케스트레이션 필요 · partition statistics 테이블 미지원",
           size=13, color=MUTED, align="left")
    return d


# ---------------------------------------------------------------- 08
def speed_window():
    d = Diagram("08-speed-window", "하루 운영 시간표 (예) — Scanner 속도 · tiering 작업 · 자정 만기",
                width=1500, height=600, subtitle="KST 기준 · 00:00 UTC = 09:00 KST · 시간대 속도 변경은 즉시 반영이 전제 (질의 Q-S4)")
    x0, x1 = 160, 1440
    w = (x1 - x0) / 24.0

    def X(h):
        return x0 + h * w
    for h in range(0, 25, 2):
        d.text(X(h) - 20, 96, 40, 20, "%02d" % h, size=11, color=MUTED)
        d.edge([(X(h), 118), (X(h), 520)], color="#E5E8EC", arrow=False, width=1)
    lanes = [(140, "Scanner speed"), (240, "배치 작업"), (340, "ILM 만기"), (440, "사용자 I/O")]
    for y, name in lanes:
        d.text(40, y + 15, 115, 30, name, size=13, bold=True, align="left")
    blocks = [(140, 0, 2, "default", BLUE, WHITE), (140, 2, 5, "slow (배치와 겹침 회피)", BLUE, NOTE_FILL),
              (140, 5, 8, "fast (사이클 따라잡기)", BLUE, NOTE_FILL),
              (140, 8, 20, "slow (업무 시간)", BLUE, NOTE_FILL), (140, 20, 24, "default", BLUE, WHITE),
              (240, 2, 4, "tiering compaction\n태그 → 즉시 전이", ORANGE, ORANGE_FILL), (240, 4, 5.5, "보존 작업\nsoft delete", TEAL, WHITE),
              (340, 8.5, 11, "00:00 UTC = 09:00 KST\nScanner 만 쓰면 1d 만기 쏠림", RED, WARN_FILL),
              (440, 8, 20, "업무 피크", GREY, NOTE_FILL)]
    for y, a, b, t, c, f in blocks:
        d.box("blk%d_%d" % (y, int(a * 10)), X(a) + 2, y, X(b) - X(a) - 4, 60, t, stroke=c, fill=f, size=11, bold=(c == RED))
    d.box("note", 40, 530, 1420, 50, "Scanner 만으로 1d 를 처리하면 하루치가 09:00 KST 에 만기 → 업무 피크와 겹침. 태그 기반 전이를 02~04 시에 돌리면 만기 쏠림이 사라진다.",
          stroke=INK, fill=NOTE_FILL, size=13, align="left")
    return d


# ---------------------------------------------------------------- 09
def question_map():
    d = Diagram("09-question-map", "질의 지도 — 어떤 결정을 위해 무엇을 묻나",
                width=1500, height=760, subtitle="왼쪽 결정을 내리려면 오른쪽 질문의 답이 필요하다 · 먼저 물을 것: Q-S1 · Q-S2 · Q-I1 → Q-I8 · Q-R1")
    dec = [("D1 1d 규칙 유지 vs 태그 기반 전이", ORANGE), ("D2 Scanner 시간대 운영", BLUE), ("D3 기한 삭제 방식 (soft delete)", GREEN),
           ("D4 Replication 방식 (R-A / R-B)", WARMC), ("D5 운영 버전 재시험 범위", GREY)]
    qs = [("Scanner  Q-S1 일 분리 · Q-S2 우리 규모 사이클 · Q-S3 건너뛰기 · Q-S8 증설", BLUE),
          ("Scanner  Q-S4 speed 즉시 반영 · Q-S5 버킷 제외 · Q-S6 지표 · Q-S7 경보", BLUE),
          ("ILM  Q-I1 태그 즉시 전이 보장 ★ · Q-I2 나중 태그 · Q-I7 Batch 전이", ORANGE),
          ("ILM  Q-I3 태그 규칙 비용 · Q-I8 전이 버전 만료 = 복구 불가 ★ · Q-I4 · I5 · I6", ORANGE),
          ("Tier  Q-T1 ~ T6 (Versioning · 장애 · 자격증명 · 읽기 · restore · journal)", WARMC),
          ("Replication  Q-R1 PENDING 과 전이 ★ · Q-R3 태그 복제 · Q-R5 Batch · Q-R2 · R4 · R6", WARMC),
          ("운영  Q-O1 버전 차이 · Q-O2 소급 PUT · Q-O3 metrics v3 · Q-O4 · O5", GREY)]
    for i, (t, c) in enumerate(dec):
        d.box("d%d" % i, 40, 120 + i * 120, 420, 80, t, stroke=c, size=14, bold=True)
    for i, (t, c) in enumerate(qs):
        d.box("q%d" % i, 760, 110 + i * 88, 700, 66, t, stroke=c, size=12, align="left")
    links = [(0, 0), (0, 2), (1, 1), (2, 3), (3, 5), (4, 6), (0, 4), (2, 4)]
    colors = [ORANGE, BLUE, GREEN, WARMC, GREY]
    for n, (di, qi) in enumerate(links):
        dy = 160 + di * 120 + (n % 2) * 8 - 4
        qy = 143 + qi * 88 + (di - 2) * 6
        bx = 520 + di * 45
        d.edge([(460, dy), (bx, dy), (bx, qy), (760, qy)], color=colors[di], width=1.4)
    return d


def main():
    out = os.path.join(ROOT, "diagrams")
    for fn in (scanner_cycle, ilm_timing, load_levers, tag_tiering, soft_delete, repl_inconsistency, repl_solutions,
               speed_window, question_map):
        dg = fn()
        dg.save(out, out)
        print("wrote", dg.name)


if __name__ == "__main__":
    main()
