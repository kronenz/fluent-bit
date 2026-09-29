# [향후 6] 이천 기존 클러스터 / 용인용 HMS(Oracle) 각자 구성 — To-do List

> 요청 6 · 카테고리: 향후 구성 대응
> 관련: [장표 2](../01-architecture/02-warm-standalone-yongin.md) · [Polaris·스키마 확인 사항](./03-open-items-polaris-hot-warm-schema.md)


> ⚠️ **전제 (피드백 반영)**: HMS-Warm 구축은 **Warm MinIO 데이터를 HMS 로 조회하는 케이스가 있을 때(모드 ①)** 만 필요합니다. 케이스가 없으면 실시간 Replication · HMS-Warm · 등록 자동화는 불필요하며, 백업 용도(모드 ②)는 [근거 1](../02-evidence/01-replication-necessity-backup.md) 의 백업 시점 테스트로 대체합니다. 판단은 [담당자 우려 확인 OC-1](../03-future/00-owner-concerns.md) 이후 확정.

![Hot/Warm 카탈로그 분리](../diagrams/09-hot-warm-catalog-split.svg)

> Confluence: Gliffy 매크로 → Import → `diagrams/09-hot-warm-catalog-split.gliffy`

---

## 1. 목표 구성

| 구분 | HMS-Hot (이천 · 기존) | HMS-Warm (용인용 · 신규) |
|---|---|---|
| 역할 | Hot 테이블의 쓰기·조회 카탈로그 (source of truth) | Warm 복제본의 **읽기 전용** 카탈로그 |
| 배치 | 이천 dataops | 용인 dataops (🔍 구축 전 과도기에는 이천에 임시 배치 가능) |
| DB | Oracle (기존 스키마) | Oracle (**신규 스키마/계정**) — 인스턴스 공유 여부 결정 필요 |
| 테이블 location | `s3://<bucket>/...` (Hot 엔드포인트) | `s3://<bucket>/...` (Warm 엔드포인트 — 버킷명 동일 시) |
| 등록 방식 | Spark/Trino 커밋 | **검증 후 `register_table`** (자동화 Job) |
| 클라이언트 | 이천 Spark/Trino, Polaris(lake_hot) | 용인 Trino, Polaris(lake_warm) |

## 2. To-do List

### 2.1 공통 결정 (착수 전)

| # | 할 일 | 산출물 | 담당 | 기한 | 상태 |
|---|---|---|---|---|---|
| H-01 | HMS 버전 확정 (HMS-Hot 과 **동일 버전** 권장) | 버전 결정서 | 플랫폼 | | ☐ |
| H-02 | Oracle 배치 결정: 기존 인스턴스에 스키마 추가 vs 별도 인스턴스 (DC 간 JDBC 지연 고려) | DB 배치안 | DBA · 플랫폼 | | ☐ |
| H-03 | Hot/Warm **버킷명 동일** 여부 결정 → 경로 재작성 필요 여부 결정 | 설계 결정 | 데이터엔지니어링 | | ☐ |
| H-04 | 등록 대상 범위(전 테이블 vs 용인 사용 테이블 목록) 및 **신선도 SLA** | 대상 테이블 목록 | 데이터 오너 | | ☐ |
| H-05 | DB/스키마 명명 규칙: Hot 과 **동일 DB·테이블명** 유지 (카탈로그 이름으로만 구분) | 명명 규칙 | 데이터엔지니어링 | | ☐ |

### 2.2 Oracle (용인용 스키마)

| # | 할 일 | 세부 | 상태 |
|---|---|---|---|
| H-10 | 스키마/계정 생성 요청 | 예: `HMS_WARM` 계정, 테이블스페이스, 쿼터 | ☐ |
| H-11 | 권한 부여 | CREATE TABLE/SEQUENCE/INDEX 등 schematool 요구 권한 | ☐ |
| H-12 | 문자셋·NLS 확인 | 기존 HMS-Hot 스키마와 동일 (AL32UTF8 등) 🔍 | ☐ |
| H-13 | 네트워크 | HMS-Warm Pod → Oracle 1521(또는 리스너 포트) 방화벽 | ☐ |
| H-14 | 백업·복구 | 스키마 백업 주기 (단, Warm 카탈로그는 **재등록으로 재생성 가능** — RPO 완화 가능) | ☐ |

### 2.3 HMS-Warm 배포 (용인 k8s)

| # | 할 일 | 세부 | 상태 |
|---|---|---|---|
| H-20 | 이미지 준비 | HMS 이미지 + **Oracle JDBC(ojdbc8/11)** + hadoop-aws / aws SDK 번들 · 사내 레지스트리 반입 | ☐ |
| H-21 | 스키마 초기화 | `schematool -dbType oracle -initSchema` (Job 1회) → `-info` 로 버전 확인 | ☐ |
| H-22 | hive-site 설정 | `javax.jdo.option.ConnectionURL=jdbc:oracle:thin:@//<host>:1521/<svc>`, Driver `oracle.jdbc.OracleDriver`, `hive.metastore.warehouse.dir`, `fs.s3a.endpoint=https://warm-s3.<domain>`, `fs.s3a.path.style.access=true` | ☐ |
| H-23 | 비밀 관리 | Oracle 계정·S3 읽기 전용 키를 Secret(또는 사내 Vault)으로 주입 | ☐ |
| H-24 | 가용성 | replicas ≥ 2, PDB, readiness(9083 TCP), 리소스(JVM heap) | ☐ |
| H-25 | 서비스 노출 | 클러스터 내부 `hms-warm:9083`, Polaris 가 외부에 있으면 LB/VIP 노출 + 방화벽 | ☐ |
| H-26 | 모니터링 | JVM/Thrift 메트릭, Oracle 커넥션 풀, 로그 수집(fluent-bit) | ☐ |

### 2.4 Warm 테이블 등록·동기화 자동화

![검증 후 등록](../diagrams/10-verify-and-register.svg)

| # | 할 일 | 세부 | 상태 |
|---|---|---|---|
| H-30 | 초기 등록 | 대상 테이블별 최신 **검증 완료** metadata.json 을 HMS-Warm 에 등록 — Spark `CALL <cat>.system.register_table('db.tbl', 's3://.../vN.metadata.json')` 또는 Trino `CALL iceberg.system.register_table(...)` (`iceberg.register-table-procedure.enabled=true`) | ☐ |
| H-31 | 완전성 검증 Job | metadata → manifest list → manifest → data file 전체를 **Warm 에서 HEAD** 확인 후에만 등록/갱신 ([근거 2 §5](../02-evidence/02-iceberg-snapshot-vs-replication.md)) | ☐ |
| H-32 | 포인터 갱신 방식 결정 | 재등록(unregister + register) vs HMS 테이블 파라미터 `metadata_location` 갱신 — 조회 중 쿼리 영향 확인 🔍 | ☐ |
| H-33 | 주기·SLA | 등록 주기 ≤ 신선도 SLA, **Hot `expire_snapshots` 보존 기간 > 복제 지연 + 등록 주기** | ☐ |
| H-34 | 쓰기 차단 | 용인 Trino 카탈로그 read-only 운영, S3 키 읽기 전용 정책 | ☐ |
| H-35 | 지연 모니터링 | HMS-Hot vs HMS-Warm 스냅샷 ID 차이, 복제 백로그 알림 | ☐ |

### 2.5 이천 기존 클러스터 (HMS-Hot) 측 작업

| # | 할 일 | 세부 | 상태 |
|---|---|---|---|
| H-40 | 현행 파악 | HMS-Hot 버전, Oracle 스키마, 등록 테이블 수, Iceberg format-version | ☐ |
| H-41 | 유지보수 정책 조정 | `expire_snapshots` / `remove_orphan_files` 보존 기간을 Warm 등록 지연 이상으로 | ☐ |
| H-42 | 메타 조회 경로 제공 | Warm 동기화 Job 이 HMS-Hot 의 최신 `metadata_location` 을 읽을 수 있도록 접근(Thrift 또는 Oracle 읽기 뷰) | ☐ |
| H-43 | Polaris 연동 | Polaris external catalog `lake_hot` → HMS-Hot 연결 (Lake 가 Hot 도 조회하는 경우) | ☐ |

### 2.6 검증 (완료 기준)

| # | 테스트 | 합격 기준 | 상태 |
|---|---|---|---|
| H-50 | 용인 Trino `SHOW TABLES FROM iceberg_warm.<db>` | 대상 테이블 전부 조회 | ☐ |
| H-51 | Hot 에서 INSERT → 등록 주기 후 용인 조회 | SLA 내 신규 데이터 조회 | ☐ |
| H-52 | 복제 지연 인위 발생 후 등록 Job | 누락 감지 → **등록 보류**, 알림 | ☐ |
| H-53 | Hot `expire_snapshots` 후 Warm 조회 | 실패 없음 | ☐ |
| H-54 | 용인에서 INSERT 시도 | 거부 | ☐ |
