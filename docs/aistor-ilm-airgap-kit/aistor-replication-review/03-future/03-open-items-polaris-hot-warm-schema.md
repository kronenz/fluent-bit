# [향후 7] 확인 필수 사항 — Lake 의 Polaris 조회 방식 · Hot/Warm 스키마 구성

> 요청 7 · 카테고리: 향후 구성 대응
> 관련: [장표 2](../01-architecture/02-warm-standalone-yongin.md) · [HMS To-do](./02-hms-oracle-split-todo.md) · 다이어그램 `diagrams/09-hot-warm-catalog-split.*`


> **v3 확정**: `lake_warm` 은 HMS-Warm(**용인 원본 테이블**)을, `lake_hot` 은 HMS-Hot(이천 서비스 테이블)을 federation 합니다. 두 카탈로그의 테이블은 **서로 다른 데이터**이며 복제 관계가 아닙니다. 이천 replica 는 Polaris 에 노출하지 않습니다(백업).

---

## 1. Lake 에서 Polaris 를 통해 어떻게 조회하나

### 1.1 조회 흐름

| 단계 | 동작 | 비고 |
|---|---|---|
| 1 | Lake 엔진(Spark/Trino/노트북)이 Polaris REST 카탈로그에 접속 (`type=rest`, `warehouse=lake_warm`) | 엔진은 HMS 를 직접 보지 않음 |
| 2 | Polaris 의 **external catalog** `lake_warm` 이 HMS-Warm(Thrift)으로 요청을 **federation** | HMS 가 source of truth |
| 3 | Polaris 가 `loadTable` 응답으로 `metadata_location` 과 (설정 시) **스토리지 자격증명**을 반환 | credential vending 은 STS 지원 여부에 따라 🔍 |
| 4 | 엔진이 Warm 엔드포인트에서 metadata/manifest/data 를 직접 read | 네트워크 경로 = [향후 5](./01-yongin-network-checklist.md) 와 동일 요구 |

### 1.2 확인 필수 사항

| # | 확인 항목 | 왜 필요한가 | 확인 방법 | 상태 |
|---|---|---|---|---|
| P-01 | Polaris 버전과 **HIVE federation 포함 빌드** 여부 | HMS federation 은 기본 빌드 미포함, 1.1.0+ | Polaris 배포 이미지/빌드 옵션 확인 | ☐ |
| P-02 | feature flag: `ENABLE_CATALOG_FEDERATION=true`, `SUPPORTED_CATALOG_CONNECTION_TYPES` 에 `HIVE` | 미설정 시 external catalog 생성 불가 | Polaris 설정 | ☐ |
| P-03 | HMS 인증 방식 | Polaris HMS federation 은 **IMPLICIT** 인증만 지원 — HMS 가 Kerberos 등을 요구하면 불가 | HMS-Warm 보안 설정 | ☐ |
| P-04 | external catalog 하나 = HMS 하나 | 다중 HMS 라우팅 없음 → **Hot/Warm 각각 catalog 생성** (`lake_hot`, `lake_warm`) | 설계 | ☐ |
| P-05 | 쓰기 허용 여부 | 공식 문서에 read-only 명시 없음 → Warm 은 **Polaris 권한(Principal Role)으로 읽기만** 부여 | Polaris RBAC | ☐ |
| P-06 | 스토리지 설정 (`endpoint`, `endpointInternal`, `pathStyleAccess`, STS) | Polaris 와 엔진이 보는 Warm 엔드포인트가 다를 수 있음 | Polaris catalog storageConfigInfo | ☐ |
| P-07 | Lake 엔진의 위치와 Warm 접근 경로 | 장표 2 ⑥ — 방화벽/DNS 추가 필요 여부 | Lake 팀 | ☐ |
| P-08 | Generic table 미지원 | Iceberg 가 아닌 Hive 테이블은 Polaris federation 으로 조회 불가 | 대상 테이블 포맷 목록 | ☐ |

근거: [P1 HMS federation](../02-evidence/06-official-reference-links.md#p1), [P2 S3 호환 스토리지](../02-evidence/06-official-reference-links.md#p2)

## 2. 이천(Hot) · 용인(Warm) 스키마 구성 — HMS 를 따로 둘 때

### 2.1 원칙

| 규칙 | 내용 |
|---|---|
| 데이터 관계 | HMS-Hot 테이블(이천)과 HMS-Warm 테이블(용인)은 **독립 데이터** — 같은 이름일 필요 없음 |
| 네임스페이스 | 용인 DB 는 이천 DB 와 **겹치지 않는 이름** (예: `yi_*` 접두) — Polaris · Trino 에서 혼동 방지 |
| location | 이천: Hot 버킷 / 용인: Warm `yongin-*` 버킷 |
| 이천 replica | Polaris · 용인 Trino 에 **노출하지 않음** (백업, 복구 시에만 복구용 HMS) |
| DDL | 각자 원본 카탈로그에서 수행 (이천 → HMS-Hot, 용인 → HMS-Warm) |
| 권한 | 이천·용인 쓰기 역할 분리, Lake 는 Polaris RBAC 로 카탈로그별 권한 |
| Trino 카탈로그명 | 이천: `iceberg` (Hot), 용인: `iceberg_warm` · Polaris: `lake_hot` / `lake_warm` |

### 2.2 선택지 비교 (Lake 에서 이천 + 용인 데이터를 함께 보는 방법)

| 안 | 구성 | 장점 | 단점 | 권고 |
|---|---|---|---|---|
| **S-1** | Polaris 카탈로그 2개 (`lake_hot`, `lake_warm`) — 사용자가 카탈로그 선택 | 단순 · 권한 분리 명확 | 교차 조인 시 두 카탈로그 참조 | **1순위** |
| S-2 | Trino view 로 이천 + 용인 통합 뷰 제공 | 사용자 편의 | 뷰 관리 · 권한 복잡 | 요구 시 추가 |
| S-3 | 단일 HMS 에 이천 · 용인 테이블 공존 | HMS 하나 | 요청 전제(HMS 분리)와 불일치 · 용인이 이천 HMS 의존 | 제외 |

### 2.3 확인 필수 사항

| # | 확인 항목 | 결정자 | 상태 |
|---|---|---|---|
| S-01 | 용인 DB · 테이블 목록과 명명 규칙 | 용인 서비스 | ☐ |
| S-02 | Lake 에서 이천 · 용인 데이터를 **교차 조회**하는 요구 유무 | 서비스 | ☐ |
| S-03 | 이천 replica 버킷명 = Hot 버킷명 유지 (용인 버킷명과 충돌 금지) | 플랫폼 | ☐ |
| S-04 | 통합 뷰(S-2) 필요 여부 | 서비스 | ☐ |
| S-05 | Hive(비 Iceberg) 테이블 존재 여부 — Polaris federation 대상 외 | 데이터엔지니어링 | ☐ |
| S-06 | Polaris `lake_warm` 쓰기 허용 여부 (용인 외 Lake 엔진이 쓰는가) | 담당자 | ☐ |
| S-07 | 사용자 안내: 이천 = `lake_hot`/`iceberg`, 용인 = `lake_warm`/`iceberg_warm` 가이드 배포 | 플랫폼 | ☐ |

## 3. 진행 순서 (제안 — 전체 순서는 [INDEX §5](../INDEX.md))

| 단계 | 작업 | 선행 조건 |
|---|---|---|
| 0 | 담당자 우려 확인 (OC-1~OC-13) → 모드 결정 | — |
| 1 | Replication · ILM 근거 확인 (R-01~R-26) + Warm 버킷 역할 분리 결정 | 0 |
| 2 | 이천 Replication 테스트 (T-B · 공존 부하) | 1 |
| 3 | 용인 네트워크 A 경로 개통 (read/write) (① ~ ⑦) | 2 |
| 4 | HMS-Warm(용인 원본) + Oracle 스키마 구축 (H-10 ~ H-26) | 3 |
| 5 | 이천 replica 복구 절차 · 리허설 (H-30 ~ H-35) | 2 |
| 6 | 용인 Trino 연결 · 검증 (H-50 ~ H-54) | 5 |
| 7 | Polaris `lake_warm` federation PoC (P-01 ~ P-08) | 4 |
| 8 | 대상 테이블 확대 + 모니터링 · 운영 이관 | 6, 7 |
