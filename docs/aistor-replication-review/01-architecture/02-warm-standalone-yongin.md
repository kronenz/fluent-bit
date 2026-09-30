# [장표 2] 용인 dataops — Warm 클러스터 전용 적재 · 조회 (Trino / Spark → HMS-Warm(Oracle) ← Polaris)

> 요청 2 · 카테고리: 아키텍처 대응 장표 · v3 반영
> 관련: [장표 1](./01-hot-warm-icheon-dataops.md) · [근거 1 두 케이스 공존](../02-evidence/01-warm-coexistence-replication-ilm.md) · [HMS To-do](../03-future/02-hms-oracle-split-todo.md) · [Polaris/스키마](../03-future/03-open-items-polaris-hot-warm-schema.md)

> **v3 확정**: 용인 데이터는 **Warm 클러스터의 용인 전용 버킷에만 적재하고 조회**합니다. 이천 Hot 의 복제본을 조회하는 구조가 아닙니다. 이천 서비스의 Hot → Warm Replication · ILM 은 별개로 운영되며, 두 케이스가 Warm 을 공유합니다.

![용인 Warm 전용](../diagrams/02-warm-standalone-yongin.svg)

> Confluence: Gliffy 매크로 → Import → `diagrams/02-warm-standalone-yongin.gliffy`

---

## 1. 구성 원칙

| # | 원칙 | 이유 |
|---|---|---|
| 1 | 용인은 자체 스토리지 없이 **이천 Warm 의 용인 전용 버킷(`yongin-*`)** 에 적재·조회한다 | 요청 전제 (용인은 Warm 만 사용) |
| 2 | 용인 테이블의 카탈로그는 **HMS-Warm(용인 원본)** — 용인 엔진이 직접 커밋한다 | 복제본이 아니므로 검증·등록 Job 불필요 |
| 3 | 용인 버킷은 **Hot 복제 · ILM Tier 대상이 아니다** | Iceberg-Replication 충돌(C1~C5) 대상에서 제외 |
| 4 | 용인 access key 는 `yongin-*` 버킷만 허용, **이천 replica · tier 버킷 접근 차단** | replica 오염 · Tier 데이터 유실 방지 ([M14](../02-evidence/06-official-reference-links.md#m14)) |
| 5 | Lake 는 Polaris 의 **HMS federation**(`lake_warm` → HMS-Warm)으로 용인 테이블을 조회한다 | Polaris 가 HMS 를 source of truth 로 두고 접근 중개 |
| 6 | 용인 데이터의 **백업 요구**는 별도로 확인한다 | Warm 에만 존재 — 현재 백업 사본 없음 (Y-7) |

## 2. 흐름 설명 (장표 번호)

| 번호 | 흐름 | 프로토콜/포트 | 설정 포인트 |
|---|---|---|---|
| ① | Trino · Spark(용인) → HMS-Warm: 메타 조회 · **커밋** | Thrift :9083 | `iceberg.catalog.type=hive_metastore`, `hive.metastore.uri=thrift://hms-warm:9083` |
| ② | Lake 엔진 → Polaris: REST 카탈로그 API | HTTPS | 엔진 측 `type=rest` |
| ③ | Polaris → HMS-Warm: Catalog Federation | Thrift :9083 | external catalog `connectionType=HIVE` ([확인 사항](../03-future/03-open-items-polaris-hot-warm-schema.md)) |
| ④ | 용인 엔진 → 이천 Warm: 데이터 **read / write** | HTTPS :443 (또는 :9000) | `s3.endpoint=https://warm-s3.<domain>`, `s3.path-style-access=true`, multipart 설정 |
| ⑤ | 용인 CoreDNS → 사내 DNS: Warm FQDN 해석 | DNS :53 | stub/forward zone |
| ⑥ | Lake 엔진 → Warm: 데이터 read | 🔍 | Lake 엔진 위치 · 경로 · 자격증명 확인 |

## 3. Warm 클러스터 버킷 역할 (용인 관점)

| 버킷 | 용인 접근 | 설명 |
|---|---|---|
| `yongin-*` (용인 전용) | **read / write** | 용인 원본 데이터 · HMS-Warm location |
| 이천 replica (Hot 동일명) | **차단** | 이천 백업 사본 — 복구 전까지 쓰기 금지 |
| ILM tier 버킷 / prefix | **차단** | AIStor 독점 영역 — 직접 접근 시 데이터 유실 가능 |

## 4. 컴포넌트별 설정 초안

### 4.1 Trino (용인) — Iceberg 카탈로그

```properties
# etc/catalog/iceberg_warm.properties
connector.name=iceberg
iceberg.catalog.type=hive_metastore
hive.metastore.uri=thrift://hms-warm.<ns>.svc:9083

fs.s3.enabled=true
s3.endpoint=https://warm-s3.<domain>
s3.path-style-access=true
s3.region=us-east-1
# s3.aws-access-key / s3.aws-secret-key 는 Secret 으로 주입 (yongin-* 버킷 read/write 정책 사용자)
```

### 4.2 HMS-Warm (용인 원본)

| 설정 | 값(예시) | 비고 |
|---|---|---|
| `javax.jdo.option.ConnectionURL` | `jdbc:oracle:thin:@//<oracle-host>:1521/<SERVICE>` | 용인용 스키마 |
| `fs.s3a.endpoint` | `https://warm-s3.<domain>` | location 검증 시 S3 접근 |
| `fs.s3a.path.style.access` | `true` | |
| `hive.metastore.warehouse.dir` | `s3a://yongin-warehouse/` | **용인 전용 버킷** |

상세 구성 To-do → [03-future/02](../03-future/02-hms-oracle-split-todo.md)

### 4.3 Polaris — `lake_warm` external catalog 개념 예시

```json
{
  "catalog": {
    "name": "lake_warm",
    "type": "EXTERNAL",
    "connectionConfigInfo": {
      "connectionType": "HIVE",
      "uri": "thrift://hms-warm.<domain>:9083",
      "warehouse": "s3://yongin-warehouse/",
      "authenticationParameters": { "authenticationType": "IMPLICIT" }
    },
    "storageConfigInfo": {
      "storageType": "S3",
      "endpoint": "https://warm-s3.<domain>",
      "pathStyleAccess": true,
      "allowedLocations": ["s3://yongin-"]
    }
  }
}
```

> 🔍 필드명은 Polaris 버전별로 다를 수 있음. HMS federation 은 별도 빌드 옵션 · `ENABLE_CATALOG_FEDERATION=true` · `SUPPORTED_CATALOG_CONNECTION_TYPES` 에 `HIVE` 필요, 인증은 `IMPLICIT` 만, 연결 하나당 HiveCatalog 하나 ([P1](../02-evidence/06-official-reference-links.md#p1))

## 5. 리스크와 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| Warm 공유 부하 (이천 복제 · Tier 유입 + 용인 I/O) | 용인 적재·조회 지연 | 피크 측정(T-B9) · 복제 대역폭 제한 검토 |
| DC 간 대역폭 · 지연 (쓰기 포함) | 대용량 적재 실패 · 느린 스캔 | multipart 크기 · 타임아웃 · 파일 크기(compaction) 관리 |
| 권한 오설정 | replica 오염 · Tier 유실 | 버킷 정책으로 `yongin-*` 만 허용, 정기 점검 |
| 용인 데이터 백업 부재 | Warm 장애 시 용인 데이터 손실 | 백업 요구(RPO) 확인 후 대상 결정 (Y-7) |
| Polaris federation 제약 | Lake 조회 제한 | PoC 로 버전 · 기능 검증 |

## 6. 확인 필요 사항

| # | 항목 | 근거/문서 |
|---|---|---|
| B-1 | 용인 버킷 명명 규칙 · Hot 버킷명(= replica 버킷명) 예약 목록 | 근거 1 §3 |
| B-2 | 용인 access key 정책 (`yongin-*` read/write, replica · tier 차단) | PDF-1, 보안 |
| B-3 | 용인 Trino · Spark 버전 (native S3 FS 지원) | Trino 문서 |
| B-4 | Polaris 버전 · 빌드(HIVE federation 포함 여부) | Polaris 문서 |
| B-5 | Lake 엔진 위치 및 Warm 접근 경로 ⑥ | Lake 팀 |
| B-6 | 용인 데이터 백업 요구 (RPO · 대상) | 담당자 |
