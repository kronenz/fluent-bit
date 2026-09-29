# [향후 7] 확인 필수 사항 — Lake 의 Polaris 조회 방식 · Hot/Warm 스키마 구성

> 요청 7 · 카테고리: 향후 구성 대응
> 관련: [장표 2](../01-architecture/02-warm-standalone-yongin.md) · [HMS To-do](./02-hms-oracle-split-todo.md) · 다이어그램 `diagrams/09-hot-warm-catalog-split.*`


> ⚠️ **전제 (피드백 반영)**: `lake_warm` 조회와 Warm 스키마 구성은 **Warm MinIO 데이터를 HMS 로 조회하는 케이스가 있을 때(모드 ①)** 만 필요합니다. 케이스가 없으면 실시간 Replication · HMS-Warm · 등록 자동화는 불필요하며, 백업 용도(모드 ②)는 [근거 1](../02-evidence/01-replication-necessity-backup.md) 의 백업 시점 테스트로 대체합니다. 판단은 [담당자 우려 확인 OC-1](../03-future/00-owner-concerns.md) 이후 확정.

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

## 2. Hot ↔ Warm 스키마(카탈로그) 구성 — HMS 를 따로 둘 때

### 2.1 선택지 비교

| 안 | 구성 | 장점 | 단점 | 권고 |
|---|---|---|---|---|
| **S-1** | HMS-Hot / HMS-Warm 에 **동일 DB·테이블명**, 카탈로그 이름으로 구분 (`lake_hot.sales.orders` / `lake_warm.sales.orders`) | SQL 이식 쉬움, 등록 자동화 단순 (이름 1:1) | 사용자가 카탈로그를 골라야 함 | **1순위** |
| S-2 | HMS-Warm 에 접미사 DB (`sales_warm.orders`) | 한 화면에서 구분 명확 | 이름 매핑 테이블 관리, SQL 수정 필요 | 비권장 |
| S-3 | 단일 HMS 에 Hot/Warm 테이블 공존 | HMS 하나 | 요청 전제(HMS 분리)와 불일치, 용인이 이천 HMS 의존 | 제외 |

### 2.2 S-1 세부 규칙 (안)

| 규칙 | 내용 |
|---|---|
| 네임스페이스 | DB·테이블명은 Hot 과 동일. HMS-Warm 에 `CREATE DATABASE` 는 등록 Job 이 Hot 목록 기준으로 자동 생성 |
| location | 버킷명 동일 시 location 동일 문자열 (엔드포인트만 다름) |
| 스키마 변경(DDL) | Hot 에서만 수행 → 새 metadata.json 이 복제·검증된 뒤 Warm 재등록으로 반영 (Warm 에서 DDL 금지) |
| 파티션/스키마 진화 | Iceberg 메타데이터에 포함 → 별도 HMS 동기화 불필요 (HMS 는 포인터만 보관) |
| 권한 | Hot: 쓰기 역할 / Warm: 읽기 역할만 (Trino 접근 제어 + Polaris RBAC + S3 정책) |
| Trino 카탈로그명 | 이천: `iceberg` (Hot), 용인: `iceberg_warm` (Warm) — Polaris 는 `lake_hot` / `lake_warm` |

### 2.3 확인 필수 사항

| # | 확인 항목 | 결정자 | 상태 |
|---|---|---|---|
| S-01 | Warm 에 올릴 **테이블 범위** (전체/일부) | 데이터 오너 | ☐ |
| S-02 | Warm 조회 **신선도 SLA** (예: T+1h, T+1d) | 서비스 | ☐ |
| S-03 | 버킷명 동일 유지 가능 여부 | 플랫폼 · AIStor 관리자 | ☐ |
| S-04 | Hot/Warm 동시 조회(union view) 필요 여부 — 필요 시 Trino view 로 제공 | 서비스 | ☐ |
| S-05 | Hive(비 Iceberg) 테이블 존재 여부 — Polaris federation 대상 외 | 데이터엔지니어링 | ☐ |
| S-06 | HMS-Hot 이 Iceberg 외 Hive 테이블도 관리한다면 Warm 등록 대상에서 제외 규칙 | 데이터엔지니어링 | ☐ |
| S-07 | 사용자 안내: "용인/Lake 에서는 `lake_warm`/`iceberg_warm` 카탈로그를 사용" 가이드 배포 | 플랫폼 | ☐ |

## 3. 진행 순서 (제안 — 전체 순서는 [INDEX §5](../INDEX.md))

| 단계 | 작업 | 선행 조건 |
|---|---|---|
| 0 | 담당자 우려 확인 (OC-1~OC-13) → 모드 결정 | — |
| 1 | Replication 근거 확인 (R-01~R-24) + 버킷명 · 복제 방향 결정 | 0 |
| 2 | Replication 테스트 (충돌 C1~C5 · 복제 지연) | 1 |
| 3 | (모드 ①) 네트워크 A 경로 개통 (① ~ ⑦) | 2 |
| 4 | (모드 ①) HMS-Warm + Oracle 스키마 구축 (H-10 ~ H-26) | 3 |
| 5 | (모드 ①) 등록 자동화 Job PoC (H-30 ~ H-35) — 테이블 1~2 개 | 4 |
| 6 | (모드 ①) 용인 Trino 연결 · 검증 (H-50 ~ H-54) | 5 |
| 7 | (모드 ①) Polaris `lake_warm` federation PoC (P-01 ~ P-08) | 4 |
| 8 | 대상 테이블 확대 + 모니터링 · 운영 이관 | 6, 7 |
