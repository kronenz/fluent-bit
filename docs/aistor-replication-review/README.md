# AIStor(S3) Bucket Replication 도입 검토 — 근거 정리 및 진행 확인 사항

> 작성: 빅데이터 플랫폼 데이터 엔지니어링 · 작성일 2026-09-29
> 대상: AIStor(상용 MinIO) **Hot / Warm 2-Tier** 클러스터(이천) + 이천 dataops + 용인 dataops(신규) + Lake(Polaris)
> 선행 문서: [AIStor Hot/Warm + ILM/Replication 환경의 Iceberg-Spark 운영 가이드](../aistor-iceberg-ilm-guide/README.md)

---

## 0. 한 장 요약

| # | 결론 | 근거 위치 |
|---|---|---|
| 1 | Hot/Warm AIStor와 이천 dataops는 **같은 이천 베어메탈 k8s 대역**에서 Cilium ClusterMesh + BGP(Private)로 연결되며, Public 접근은 **Ingress 또는 L4 스위치 VIP**로만 노출한다 | [01-architecture/01](./01-architecture/01-hot-warm-icheon-dataops.md) |
| 2 | 용인은 **데이터를 갖지 않고** 이천 Warm만 원격 조회한다. 용인에는 Trino + **Warm 전용 HMS(Oracle)** 를 두고, Lake는 **Polaris가 HMS를 federation** 하여 조회한다 | [01-architecture/02](./01-architecture/02-warm-standalone-yongin.md) |
| 3 | S3 Replication은 **객체(버전) 단위 비동기 복제**이고 Iceberg 커밋은 **카탈로그 포인터의 원자 교체**다. 단위가 달라 ① 부분 복제 스냅샷 ② 카탈로그 미복제 ③ 삭제 전파 불일치 ④ ILM 비인지 — 4가지 충돌이 생긴다 | [02-evidence/01](./02-evidence/01-iceberg-snapshot-vs-replication.md) |
| 4 | S3/AIStor Lifecycle 액션은 **Transition·Expiration뿐**이다. RAW→Archive(zip) rollover(병합·압축·검증·원본 정리)는 **서비스가 직접 구현**해야 한다 | [02-evidence/02](./02-evidence/02-raw-archive-ilm-limitation.md) |
| 5 | 용인→이천 Warm 접근은 **A. Public(VIP/Ingress 재사용) 경로를 우선** 검토한다. ClusterMesh 확장(B)은 PodCIDR 비중복·cluster-id·노드 간 L3 도달성이 전제다 | [03-future/01](./03-future/01-yongin-network-checklist.md) |
| 6 | HMS는 **Hot(이천 기존) / Warm(용인용 신규)** 으로 분리하고, Warm HMS에는 복제 완료가 검증된 metadata.json만 `register_table` 한다 | [03-future/02](./03-future/02-hms-oracle-split-todo.md), [03-future/03](./03-future/03-open-items-polaris-hot-warm-schema.md) |

---

## 1. 문서 트리

```text
aistor-replication-review/
├── INDEX.md                                    ← 요약 · 문서별 핵심 · To-do/일정 표 · 개념도
├── diagrams/                                   INDEX 개념도 i1·i3·i4·i6·i7 (.drawio/.gliffy/.svg)
├── README.md                                   ← 지금 문서 (요약·트리·용어·보안문서 목록)
├── 01-architecture/                            ── 1. 아키텍처 대응 장표
│   ├── README.md
│   ├── 01-hot-warm-icheon-dataops.md           (요청 1) Hot/Warm ↔ 이천 dataops (ClusterMesh·BGP·VIP·Ingress)
│   ├── 02-warm-standalone-yongin.md            (요청 2) Warm 단독 사용: 용인 Trino → HMS(Oracle) ← Polaris
│   └── diagrams/  01-*.drawio|.gliffy|.svg, 02-*.drawio|.gliffy|.svg
├── 02-evidence/                                ── 2. 근거 정리
│   ├── README.md
│   ├── 01-iceberg-snapshot-vs-replication.md   (요청 3) Iceberg 스냅샷 ↔ S3 Replication 충돌
│   ├── 02-raw-archive-ilm-limitation.md        (요청 4) RAW→Archive(zip) ILM rollover 불가 근거
│   ├── 03-internal-pdf-evidence-map.md         보안 PDF 6종: 문서별 "무엇을 찾아 확인할지"
│   ├── 04-official-reference-links.md          공개 공식 문서 링크·원문 인용 모음
│   └── diagrams/  03-*, 04-*
├── 03-future/                                  ── 3. 향후 구성 대응
│   ├── README.md
│   ├── 01-yongin-network-checklist.md          (요청 5) 용인 → Warm 방화벽·DNS·ClusterMesh 확인 사항
│   ├── 02-hms-oracle-split-todo.md             (요청 6) 이천/용인 HMS(Oracle) 각자 구성 To-do
│   ├── 03-open-items-polaris-hot-warm-schema.md (요청 7) Polaris 조회 방식 · Hot/Warm 스키마 구성 확인 필요 사항
│   └── diagrams/  05-*, 06-*
└── tools/
    ├── diagram_lib.py                          draw.io / Gliffy / SVG 동시 생성 라이브러리
    └── gen_diagrams.py                         다이어그램 스펙 (수정 후 재생성)
```

## 2. 다이어그램 사용법

| 파일 | 용도 | Confluence 반영 방법 |
|---|---|---|
| `*.gliffy` | Gliffy 네이티브 JSON (`application/gliffy+json` v1.3) | 페이지 편집 → **Gliffy Diagram** 매크로 → **Import** → 파일 업로드 |
| `*.drawio` | draw.io XML | **draw.io Diagram** 매크로 → *Import from* → Device, 또는 app.diagrams.net 에서 열기 |
| `*.svg` | 미리보기 (GitHub/IDE 렌더링용) | 이미지 첨부 용도. 아이콘은 단순 도형으로 표시됨 |

- 스타일: AWS 아키텍처 다이어그램 형식(흰 배경 · 얇은 컬러 그룹 박스 + 좌상단 배지 · 아이콘 하단 라벨 · 검정 직교 화살표). draw.io 파일은 AWS4 S3 아이콘과 Kubernetes 아이콘 라이브러리를 사용하고, Gliffy 파일은 기본 도형(둥근 사각 + 글리프)으로 같은 배치를 재현합니다.
- 색 규칙: **보라** k8s 클러스터 · **초록** 네트워크 · **레드** AIStor 스토리지 · **파랑** Lake/Kubernetes · **빨강 박스** 확인 필요 항목.
- 수정: `tools/gen_diagrams.py` 의 좌표/라벨을 고친 뒤 `python3 tools/gen_diagrams.py` 로 세 포맷을 한 번에 재생성합니다.

## 3. 사내 보안 PDF 목록 (본문 미인용 · 제목 기준 참조)

사내 보안문서이므로 본 문서에는 **내용을 옮기지 않고**, 각 근거 항목에 "어느 문서에서 무엇을 찾아 확인해야 하는지"만 기록합니다. 상세 매핑은 [02-evidence/03-internal-pdf-evidence-map.md](./02-evidence/03-internal-pdf-evidence-map.md).

| ID | 문서명 | 주 용도 |
|---|---|---|
| **PDF-1** | [SK Hynix] AiStor 2-Tier 구성 시 고려사항.pdf | Hot/Warm 2-Tier 구성 방식·네트워크·접근 엔드포인트 권고 |
| **PDF-2** | Global Reference - Versioning, ILM, Replication, Object Locking_May2026.pdf | 4개 기능 간 상호작용(조합 제약) 매트릭스 |
| **PDF-3** | ILM (Information Lifecycle Management).pdf | Lifecycle 액션·필터·Scanner·Tier 동작 |
| **PDF-4** | Object Locking (Write On Read Merge).pdf | WORM/보존 정책, ILM·Replication 과의 제약 |
| **PDF-5** | Replication.pdf | 비동기/동기, 복제 대상, delete/delete-marker, resync, 상태 확인 |
| **PDF-6** | Versioning.pdf | Versioning 필수 조건, delete marker, noncurrent 축적 |

## 4. 전제 및 용어

| 항목 | 이 문서의 전제 | 상태 |
|---|---|---|
| Hot / Warm 위치 | **둘 다 이천**, AIStor는 베어메탈 k8s 위에 구성 | 확정 (요청자 확인) |
| 이천 네트워크 | dataops ↔ AIStor: Cilium **ClusterMesh + BGP** (Private 대역) | 확정 |
| Public 노출 | **Ingress 주소** 또는 **LB VIP(스위치에 등록, 스위치가 로드밸런싱)** | 확정 |
| 용인 | Warm **접근만** (데이터 미보유) | 확정 |
| Lake 조회 | **Apache Polaris 가 HMS 를 federation** | 확정 |
| Replication 방향 | Hot → Warm **단방향**, Versioning ON | 🔍 가정 (선행 가이드 기준, 확인 필요) |
| Iceberg 테이블 버킷명 | Hot/Warm 동일 버킷명 유지 | 🔍 권고 (결정 필요, [02-evidence/01 §5](./02-evidence/01-iceberg-snapshot-vs-replication.md)) |

| 용어 | 의미 |
|---|---|
| Hot / Warm | AIStor 클러스터(티어). 본 문서의 "Warm 버킷"은 Hot 버킷의 **Replication 대상 버킷**을 뜻함 |
| ILM Transition | Lifecycle 규칙에 따라 객체를 **Remote Tier**(Warm)로 이동. 조회는 원 버킷(Hot 엔드포인트) 경유 |
| Bucket Replication | 버킷 단위 객체 **버전 복제**. Warm 에 **독립적으로 조회 가능한 사본**이 생김 |
| HMS-Hot / HMS-Warm | 이천 기존 Hive Metastore / 용인용 신규 Hive Metastore (둘 다 Oracle 백엔드) |
| 🔍 | 버전·환경 의존 — 실제 환경 또는 사내 PDF로 확인 필요 |
| ⚠️ | 데이터 유실·서비스 영향 가능 |
