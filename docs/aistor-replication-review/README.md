# AIStor(S3) Bucket Replication 도입 검토 — 근거 정리 및 진행 확인 사항 (v3)

> 작성: 빅데이터 플랫폼 데이터 엔지니어링 · 최초 2026-09-29 · v2 피드백 반영 · v3 두 케이스 병행 확정 (2026-09-30)
> 대상: AIStor(상용 MinIO) **Hot / Warm 2-Tier** 클러스터(이천) + 이천 dataops + 용인 dataops(신규) + Lake(Polaris)
> 선행 문서: [AIStor Hot/Warm + ILM/Replication 환경의 Iceberg-Spark 운영 가이드](../aistor-iceberg-ilm-guide/README.md)
> 진행 관리 표: [INDEX.md](./INDEX.md)

---

## 0. 한 장 요약 (v3 — 두 케이스 병행)

| 케이스 | 내용 |
|---|---|
| **Y. 용인** | 용인 데이터는 **Warm 클러스터의 용인 전용 버킷에만 적재·조회** · 카탈로그는 HMS-Warm(용인 원본) |
| **I. 이천 서비스** | Hot 원본 → **Warm 으로 Bucket Replication(백업)** + **ILM Transition(용량 관리)** 둘 다 사용 |

| # | 분류 | 결론 | 근거 위치 |
|---|---|---|---|
| 0 | 선행 | 담당자 우려(복제 목적 · RPO · Transition/복제 범위 겹침 · Warm 공유 부하 · 용인 백업)를 먼저 확인 | [03-future/00](./03-future/00-owner-concerns.md) |
| 1 | 공존 | 두 케이스는 한 Warm 에서 **공존 가능(조건부)** — Warm 이 ① 이천 replica ② ILM tier ③ 용인 원본 3개 역할 → **버킷 역할 분리 · 권한 분리** 필수 | [02-evidence/01](./02-evidence/01-warm-coexistence-replication-ilm.md) |
| 2-0 | Replication | 🚨 **Hot(2026-02-07) · Warm(2026-06-06) 버전 불일치** — Bucket Replication 은 원본·대상 동일 Object Store 버전 필수 → 복제 구성 전 버전 일치 선행 | [02-evidence/01 §1-1](./02-evidence/01-warm-coexistence-replication-ilm.md) |
| 2 | Replication | 이천 복제는 **Bucket Replication 만** 가능 — Site Replication 은 Bucket Replication 과 상호 배타이고 다른 사이트가 비어 있어야 함(Warm 에 용인 데이터 존재) | [02-evidence/01 P-6](./02-evidence/01-warm-coexistence-replication-ilm.md) |
| 3 | Replication · ILM | 이천의 Replication(백업) + Transition(용량) 병행은 **역할이 달라 문제없음**. 단 같은 객체면 Warm **이중 저장** · ILM 삭제 **미복제** → replica 측 ILM 별도 · resync 시 **Tier 단절** 주의 | [02-evidence/01 §4](./02-evidence/01-warm-coexistence-replication-ilm.md) |
| 4 | Replication | 이천 replica 는 Iceberg 스냅샷 일관성 없음(C1~C5) → 백업이므로 **백업 시점 테스트(T-B)** · 복구 시 검증 후 등록 | [02-evidence/02](./02-evidence/02-iceberg-snapshot-vs-replication.md) |
| 5 | Replication · ILM | Scanner 가 복제 재큐잉 · Transition · 버전 정리를 함께 처리 → 지연 시 함께 악화 | [02-evidence/03](./02-evidence/03-scanner-impact.md) |
| 6 | ILM | ILM Tier 는 AIStor **독점 영역**(직접 접근 · ILM 금지). 아카이브는 A. zip 미사용 / B. 하이브리드 / C. 전면 Rollover 중 **협의** | [02-evidence/01 P-5](./02-evidence/01-warm-coexistence-replication-ilm.md), [02-evidence/04](./02-evidence/04-ilm-archive-options.md) |
| 7 | 용인 | 용인 Trino·Spark → HMS-Warm(Oracle) ← Polaris(`lake_warm`), Warm 은 read/write — **등록 Job 불필요** | [01-architecture/02](./01-architecture/02-warm-standalone-yongin.md) |
| 8 | 용인 | 용인 → Warm read/write 경로는 **필수** 개통 — Public(VIP/Ingress) 경로 우선 | [03-future/01](./03-future/01-yongin-network-checklist.md) |
| 9 | 아키텍처 | 이천 dataops ↔ AIStor: Private = ClusterMesh + BGP / Public = Ingress · L4 VIP | [01-architecture/01](./01-architecture/01-hot-warm-icheon-dataops.md) |

---

## 1. 문서 트리

```text
aistor-replication-review/
├── INDEX.md                                     요약 · 문서/그림 목록 · To-do · 일정 · 마일스톤 (표)
├── README.md                                    지금 문서 (요약 · 트리 · 보안 PDF · 전제/용어)
├── diagrams/                                    모든 그림 통합 (01~11 · .drawio/.gliffy/.svg)
├── 01-architecture/                             ── 1. 아키텍처 대응 장표
│   ├── 01-hot-warm-icheon-dataops.md            이천 Hot/Warm ↔ dataops (ClusterMesh·BGP·VIP·Ingress)
│   └── 02-warm-standalone-yongin.md             용인 Warm 전용 적재·조회 (Trino/Spark → HMS-Warm ← Polaris)
├── 02-evidence/                                 ── 2. 근거 정리 (Replication → ILM 순)
│   ├── 01-warm-coexistence-replication-ilm.md   두 케이스 공존 검토 · 백업 시점 테스트
│   ├── 02-iceberg-snapshot-vs-replication.md    Iceberg vs Replication 충돌 C1~C5
│   ├── 03-scanner-impact.md                     Scanner 지연 영향 (복제 재큐잉 · Transition)
│   ├── 04-ilm-archive-options.md                ILM 한계 · 아카이브 A/B/C (협의)
│   ├── 05-internal-pdf-evidence-map.md          보안 PDF 확인 매핑 R-01~R-27
│   └── 06-official-reference-links.md           공개 공식 문서 링크 · 원문 인용
├── 03-future/                                   ── 3. 향후 구성 대응
│   ├── 00-owner-concerns.md                     담당자 우려 확인 (가장 먼저)
│   ├── 01-yongin-network-checklist.md           용인 → Warm read/write 네트워크 (필수)
│   ├── 02-hms-oracle-split-todo.md              HMS-Hot / HMS-Warm(용인) / 복구용 HMS To-do
│   └── 03-open-items-polaris-hot-warm-schema.md Polaris lake_hot/lake_warm · 스키마
└── tools/
    ├── diagram_lib.py                           draw.io / Gliffy / SVG 동시 생성 라이브러리
    └── gen_diagrams.py                          그림 스펙 (수정 후 재실행)
```

## 2. 그림 목록 (diagrams/ 통합)

| No | 그림 | 분류 | 사용 문서 |
|---|---|---|---|
| 01 | icheon-hot-warm-dataops | 아키텍처 | 01-architecture/01 |
| 02 | warm-standalone-yongin | 아키텍처 (용인) | 01-architecture/02 |
| 03 | warm-coexistence | 공존 (Replication · ILM · 용인) | 02-evidence/01, 03-future/00 |
| 04 | commit-unit-mismatch | Replication | 02-evidence/02, INDEX |
| 05 | iceberg-vs-replication-timeline | Replication | 02-evidence/02 |
| 06 | scanner-impact | Replication · ILM | 02-evidence/03 |
| 07 | ilm-archive-options | ILM | 02-evidence/04 |
| 08 | yongin-network-checkpoints | 향후 (조건부) | 03-future/01 |
| 09 | hot-warm-catalog-split | 향후 (카탈로그) | 03-future/02, 03 |
| 10 | verify-and-register | 이천 replica 복구 절차 | 03-future/02, INDEX |
| 11 | todo-milestones | 진행 관리 | INDEX |

| 파일 | 용도 | Confluence 반영 방법 |
|---|---|---|
| `*.gliffy` | Gliffy 네이티브 JSON (`application/gliffy+json` v1.3) | 페이지 편집 → **Gliffy Diagram** 매크로 → **Import** → 파일 업로드 |
| `*.drawio` | draw.io XML | **draw.io Diagram** 매크로 → *Import from* → Device, 또는 app.diagrams.net 에서 열기 |
| `*.svg` | 미리보기 (GitHub/IDE 렌더링용) | 이미지 첨부 용도. 아이콘은 단순 도형으로 표시됨 |

- 스타일: AWS 아키텍처 다이어그램 형식(흰 배경 · 얇은 컬러 그룹 박스 + 좌상단 배지 · 아이콘 하단 라벨 · 검정 직교 화살표).
- 색 규칙: **보라** k8s 클러스터 · **초록** 네트워크 · **레드** AIStor 스토리지 · **주황** Replication/백업 · **파랑** Lake · **빨강 박스** 확인·협의 필요 · **점선 박스** 조건부.
- 수정: `tools/gen_diagrams.py` 를 고친 뒤 `python3 tools/gen_diagrams.py` 로 11종 × 3포맷을 재생성합니다.

## 3. 사내 보안 PDF 목록 (본문 미인용 · 제목 기준 참조)

상세 매핑: [02-evidence/05-internal-pdf-evidence-map.md](./02-evidence/05-internal-pdf-evidence-map.md)

| ID | 문서명 | 주 용도 |
|---|---|---|
| **PDF-1** | [SK Hynix] AiStor 2-Tier 구성 시 고려사항.pdf | Hot/Warm 2-Tier 구성 방식·네트워크·접근 엔드포인트 권고 |
| **PDF-2** | Global Reference - Versioning, ILM, Replication, Object Locking_May2026.pdf | 4개 기능 간 상호작용(조합 제약) 매트릭스 |
| **PDF-3** | ILM (Information Lifecycle Management).pdf | Lifecycle 액션·필터·Scanner·Tier 동작 |
| **PDF-4** | Object Locking (Write On Read Merge).pdf | WORM/보존 정책, ILM·Replication 과의 제약 |
| **PDF-5** | Replication.pdf | 비동기/동기, 복제 대상, delete/delete-marker, resync, 시점 지정 복제 |
| **PDF-6** | Versioning.pdf | Versioning 필수 조건, delete marker, noncurrent 축적 |

## 4. 전제 및 용어

| 항목 | 이 문서의 전제 | 상태 |
|---|---|---|
| Hot / Warm 위치 | **둘 다 이천**, AIStor는 베어메탈 k8s 위에 구성 | 확정 |
| AIStor 릴리스 | Hot **2026-02-07** · Warm **2026-06-06** (상용) | 확정 — 🚨 Bucket Replication 은 동일 버전 필수 ([M17](./02-evidence/06-official-reference-links.md#m17)) |
| 이천 네트워크 | dataops ↔ AIStor: Cilium **ClusterMesh + BGP** (Private 대역) | 확정 |
| Public 노출 | **Ingress 주소** 또는 **LB VIP(스위치에 등록, 스위치가 로드밸런싱)** | 확정 |
| 용인 | Warm **접근만** (데이터 미보유) | 확정 |
| Lake 조회 | **Apache Polaris 가 HMS 를 federation** | 확정 |
| 용인 데이터 | **Warm 용인 전용 버킷에만 적재·조회** (HMS-Warm 원본) | 확정 (v3) |
| 이천 Replication · ILM | Hot → Warm Bucket Replication(백업) + ILM Transition 둘 다 사용 | 확정 (v3) |
| 복제 방식 | Bucket Replication (Site Replication 불가) | 근거 확정 |
| Replication 방향 | Hot → Warm **단방향**, Versioning ON | 🔍 가정 |
| RAW 아카이브 방식 | A / B / C 중 선택 — Rollover Job 은 확정 아님 | 🔍 협의 (AR-1) |
| Iceberg 테이블 버킷명 | Hot/Warm 동일 버킷명 유지 | 🔍 권고 ([02-evidence/02 §4](./02-evidence/02-iceberg-snapshot-vs-replication.md)) |

| 용어 | 의미 |
|---|---|
| Hot / Warm | AIStor 클러스터(티어) |
| 케이스 Y / I | 용인 Warm 전용 / 이천 Replication + ILM ([근거 1](./02-evidence/01-warm-coexistence-replication-ilm.md)) |
| Warm 버킷 역할 | ① 이천 replica ② ILM tier ③ 용인 원본 ([근거 1 §3](./02-evidence/01-warm-coexistence-replication-ilm.md)) |
| 아카이브 A / B / C | zip 미사용 / 하이브리드(서비스 zip + ILM 이관) / 전면 Rollover ([근거 4](./02-evidence/04-ilm-archive-options.md)) |
| ILM Transition | Lifecycle 규칙으로 객체를 **Remote Tier**(Warm)로 이동. 조회는 Hot 엔드포인트 경유. 백업 효과 없음 |
| Bucket Replication | 버킷 단위 객체 **버전 복제**. 이천은 **백업** 용도 (평시 replica 조회 없음) |
| HMS-Hot / HMS-Warm | 이천 서비스 원본 카탈로그 / **용인 원본** 카탈로그 (Oracle 백엔드) |
| 🔍 · ⚠️ | 확인 필요 · 데이터 유실/서비스 영향 가능 |
