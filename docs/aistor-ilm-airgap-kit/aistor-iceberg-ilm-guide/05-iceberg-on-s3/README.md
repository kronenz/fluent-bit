# 05. Iceberg on S3 — 물리 구조와 ILM/Replication 충돌 지점 ★

> 이 문서의 **핵심 챕터**입니다. 여기를 이해하면 04·08·10·11장이 전부 따라옵니다.

## 1. Iceberg 테이블의 물리 구조

### 1.1 4계층 참조 체인

```
 [Hive Metastore]
   TABLE db.tbl
     └─ TBLPROPERTIES: metadata_location = s3://warehouse/db.db/tbl/metadata/00042-<uuid>.metadata.json
                                                                  │
                                        ┌─────────────────────────┘
                                        ▼
 ① metadata.json  (테이블 루트 문서)
     ├─ schema, partition-spec, sort-order, properties
     ├─ current-snapshot-id: 8234...
     ├─ snapshots: [ {id, timestamp, manifest-list: "s3://.../snap-8234-1-<uuid>.avro"}, ... ]
     └─ metadata-log: [이전 metadata.json 경로들]
                                        │
                                        ▼
 ② manifest list  (snap-*.avro) — 스냅샷 1개당 1개
     └─ [ {manifest_path: "s3://.../<uuid>-m0.avro", partition 범위 요약, 통계}, ... ]
                                        │
                                        ▼
 ③ manifest  (*-m0.avro) — 데이터 파일 목록
     └─ [ {file_path: "s3://.../data/dt=2026-08-26/00000-0-<uuid>.parquet",
           record_count, file_size, 컬럼별 min/max/null count, status(ADDED/EXISTING/DELETED)}, ... ]
                                        │
                                        ▼
 ④ data file  (Parquet) + delete file (v2: position/equality delete)
```

### 1.2 각 계층의 특성표

| 계층 | 파일 형식 | 개수(1테이블) | 평균 크기 | 읽기 빈도 | 전이 시 영향 |
|---|---|---|---|---|---|
| ① metadata.json | JSON | 커밋 수만큼 누적 (수십~수천) | 수 KB~수 MB | **매 쿼리 1회** | 🔴 전 쿼리 지연 |
| ② manifest list | Avro | 스냅샷 수만큼 | 수 KB~수백 KB | **매 쿼리 1회** | 🔴 전 쿼리 지연 |
| ③ manifest | Avro | 수십~수천 | 수십 KB~수 MB | **매 쿼리 N회** | 🔴🔴 가장 치명적 |
| ④ data (Parquet) | Parquet | 수천~수백만 | 수 MB~1 GB | 스캔 대상만 | 🟡 스캔 시에만 |
| ④ delete file | Parquet/Avro | 수백~수만 | 작음 | 해당 파일 읽을 때 | 🟠 작고 많음 |

> **핵심: ①②③은 "쿼리 플래닝" 단계에서 읽고, ④는 "실행" 단계에서 읽습니다.**
> ①②③이 warm에 있으면 **모든 쿼리가**, 심지어 결과가 0건인 쿼리조차 느려집니다.

### 1.3 쿼리 1회에 실제로 일어나는 S3 요청

```
SELECT count(*) FROM db.tbl WHERE dt = '2026-08-26';

1. HMS 조회         → metadata_location 획득                      (Thrift)
2. GET  metadata.json                                             (S3 ×1)
3. GET  snap-<current>.avro (manifest list)                       (S3 ×1)
4. GET  <uuid>-m*.avro (관련 manifest들)                            (S3 ×N, N=partition pruning 후)
   → 여기까지가 플래닝. 여기서 파일 목록과 통계로 pruning 수행
5. GET  data/*.parquet footer  (파일당 2~3회 range GET)             (S3 ×2~3×F)
6. GET  data/*.parquet column chunks                              (S3 ×C×F)
```

| 단계 | 요청 수 | 전이 시 warm 왕복 |
|---|---|---|
| 2~4 (플래닝) | 2 + N | **모든 쿼리** |
| 5~6 (실행) | (2~3 + C) × F | 스캔 대상 파일만 |

여기서 F = 스캔 파일 수, C = 읽는 컬럼 청크 수.

> **결론적으로 성능 관점에서: metadata 전이는 "상수 비용을 모든 쿼리에 부과", data 전이는 "스캔량에 비례하는 비용"입니다.** 전자는 절대 하면 안 되고, 후자는 관리 가능한 트레이드오프입니다.

## 2. Hive Metastore 카탈로그의 동작

### 2.1 커밋 프로토콜

```
1. Spark: 새 데이터 파일 write (S3 PUT)
2. Spark: 새 manifest / manifest list / metadata.json 생성 (S3 PUT)
3. Spark: HMS에 락 획득 요청
4. Spark: HMS의 TBLPROPERTIES.metadata_location 을
          (기존값 == 내가 읽은 값) 인 경우에만 새 값으로 교체   ← 원자적 CAS
5. 실패 시(다른 커밋이 먼저) → 재시도 (파일은 그대로 두고 3번부터)
6. 락 해제
```

| 특성 | 설명 | 이 환경에서의 의미 |
|---|---|---|
| 원자성 담당 | **HMS** (S3가 아님) | S3의 일관성 모델에 의존하지 않음 ✅ |
| S3에 요구하는 것 | read-after-write (PUT 후 GET 가능) | AIStor는 강한 일관성 제공 ✅ |
| 동시 커밋 | HMS 락 + CAS로 직렬화 | 충돌 시 재시도 |
| HMS 장애 시 | **읽기·쓰기 모두 불가** | HMS는 SPOF |
| metadata_location | HMS DB의 문자열 | ⚠️ 이 문자열이 S3 절대경로 |

### 2.2 🔴 metadata_location 이 절대경로라는 사실의 중요성

```sql
-- HMS 내부
TBLPROPERTIES('metadata_location'='s3://warehouse/db.db/tbl/metadata/00042-uuid.metadata.json')
```

이 값이 **버킷명과 경로를 포함한 절대경로**이기 때문에:

| 상황 | 결과 |
|---|---|
| 다른 버킷으로 객체를 복사 | HMS는 여전히 옛 버킷을 가리킴 → 테이블 못 읽음 |
| 엔드포인트만 바꿈 (버킷명 동일) | ✅ 동작 (스킴+버킷이 같으므로) |
| 스킴 변경 (`s3a://` ↔ `s3://`) | ⚠️ 카탈로그/FileIO 설정에 따라 실패 가능 |
| warm에서 직접 읽기 시도 | 경로가 hot 기준이라 무의미 |

> **이것이 07장(운영 데이터 반입)에서 가장 큰 함정입니다.** 단순 `mc mirror`로는 테이블이 열리지 않습니다.

### 2.3 metadata.json 내부에도 절대경로가 있다

metadata.json 안의 `manifest-list` 경로, manifest 안의 `file_path` 도 **전부 절대경로**입니다.

```json
{
  "current-snapshot-id": 8234567890123,
  "snapshots": [{
    "snapshot-id": 8234567890123,
    "manifest-list": "s3://warehouse/db.db/tbl/metadata/snap-8234567890123-1-abc.avro"
  }],
  "metadata-log": [
    {"metadata-file": "s3://warehouse/db.db/tbl/metadata/00041-xyz.metadata.json"}
  ]
}
```

따라서 **버킷명이 바뀌면 4계층 전부를 재작성**해야 합니다. → [07장 §4](../07-test-data/)

## 3. 파일이 "삭제되는" 시점

Iceberg에서 S3 객체가 실제로 지워지는 경로는 다음뿐입니다.

| 트리거 | 삭제 대상 | 안전성 | 명령 |
|---|---|---|---|
| `expire_snapshots` | 만료 스냅샷만 참조하던 data/manifest/manifest-list | ✅ 참조 검증함 | `CALL sys.expire_snapshots(...)` |
| `rewrite_data_files` + expire | compaction 전 구 파일 | ✅ | `CALL sys.rewrite_data_files(...)` |
| `remove_orphan_files` | 어떤 메타데이터도 참조 안 하는 고아 파일 | ⚠️ **listing 기반, 위험** | `CALL sys.remove_orphan_files(...)` |
| `DROP TABLE PURGE` | 테이블 전체 | ⚠️ 되돌릴 수 없음 | `DROP TABLE ... PURGE` |
| metadata 자동 정리 | 오래된 metadata.json | ✅ | `write.metadata.delete-after-commit.enabled=true` |
| **ILM expiration** | 나이 기준 무차별 | 🔴 **참조 검증 안 함** | (사용 금지) |

### 3.1 왜 `remove_orphan_files`가 위험한가

```
동작: S3를 LIST → 메타데이터가 참조하는 파일 집합과 비교 → 차집합 삭제
```

| 전제 | 이 환경에서 깨지는가 | 결과 |
|---|---|---|
| LIST 결과가 완전하다 | ⚠️ 전이·복제 중 상태에서 불완전할 수 있음 🔍 | 살아있는 파일을 "없는 것"으로 오인하진 않음 (반대 방향) |
| 동시에 커밋이 없다 | ❌ 스트리밍/동시 잡이 있으면 깨짐 | **커밋 진행 중인 신규 파일을 고아로 오판 → 삭제** 🔴 |
| 시계가 동기화되어 있다 | ⚠️ 클러스터 간 시계 차이 | `older_than` 판정 오류 |
| 메타데이터를 전부 읽을 수 있다 | ⚠️ metadata 전이 시 느림/실패 | 참조 집합 누락 → **live 파일 삭제** 🔴 |

> 🔴 **이 환경에서의 기본 방침: `remove_orphan_files` 실행 금지.**
> 필요 시 [11장 F-06](../11-failure-and-risk/)의 안전 절차를 따르십시오 (`older_than` 대폭 확대 + 모든 쓰기 중지 + dry-run 선행).

### 3.2 삭제가 만드는 것 (Versioning ON)

```
Iceberg가 DELETE 호출
  → AIStor: delete marker 생성 + 기존 버전을 noncurrent 로 전환
     → 용량 감소 없음 ❌
     → noncurrent expiration 규칙이 있어야만 실제 회수 ✅
     → 복제에 delete 전파 설정 시 warm에서도 동일 동작
```

| 잘못된 기대 | 실제 |
|---|---|
| "expire_snapshots 하면 용량이 줄겠지" | 안 줄어듦. 논리 삭제만 발생 |
| "compaction 하면 파일 수가 줄겠지" | S3 객체 수는 **오히려 증가** (신규 + noncurrent 구파일) |
| "삭제했으니 스캐너가 빨라지겠지" | 버전 엔트리는 남아 **더 느려짐** |

## 4. Iceberg v2 delete file

| 종류 | 설명 | 크기/개수 | ILM 영향 |
|---|---|---|---|
| Position delete | (파일경로, row 위치) 목록 | 작고 많음 | 전이 시 소파일 다수 왕복 → 지연 |
| Equality delete | (컬럼값) 조건 | 작고 많음 | 동상 |

⚠️ delete file은 대상 데이터 파일을 읽을 때 **반드시 함께 읽어야** 합니다. 작은 파일이 warm에 있으면 RTT가 그대로 비용이 됩니다. MERGE/UPDATE/DELETE를 많이 쓰는 테이블일수록 전이 성능 영향이 큽니다.

> 대응: `rewrite_position_delete_files` 로 주기적으로 병합하거나, copy-on-write 모드 검토.

```sql
CALL hive_prod.system.rewrite_position_delete_files(table => 'db.tbl');
```

## 5. 파일 개수가 지배하는 것들

이 환경에서 **파일 개수는 거의 모든 지표를 지배**합니다.

| 지표 | 파일 수와의 관계 |
|---|---|
| 쿼리 플래닝 시간 | manifest 수에 비례 |
| S3 요청 수 | 파일 수 × (2~3 + 컬럼수) |
| **전이 후 쿼리 지연** | 파일 수 × warm RTT ← 증폭 지점 |
| 스캐너 사이클 | 객체 수 × 버전 수 |
| ILM 전이 작업 수 | 객체 수 |
| 복제 작업 수 | 객체 수 |
| HMS 부하 | 무관 (파일 수와 독립) |

> ✅ **따라서 이 환경의 최우선 튜닝은 "파일 크기를 키워 파일 수를 줄이는 것"입니다.**

```sql
ALTER TABLE hive_prod.db.tbl SET TBLPROPERTIES (
  'write.target-file-size-bytes' = '536870912',   -- 512MB
  'write.parquet.row-group-size-bytes' = '134217728',
  'commit.manifest.target-size-bytes' = '16777216',
  'commit.manifest-merge.enabled' = 'true'
);
```

| 속성 | 기본 | 권장(이 환경) | 효과 |
|---|---|---|---|
| `write.target-file-size-bytes` | 512MB | 512MB~1GB | 파일 수 감소 |
| `write.parquet.row-group-size-bytes` | 128MB | 128MB | range GET 효율 |
| `commit.manifest.target-size-bytes` | 8MB | 16MB | manifest 수 감소 |
| `commit.manifest-merge.enabled` | true | true | manifest 폭증 방지 |
| `write.metadata.delete-after-commit.enabled` | false | **true** | metadata.json 누적 방지 |
| `write.metadata.previous-versions-max` | 100 | 20~50 | 동상 |
| `write.distribution-mode` | none/hash | `hash` 또는 `range` | 작은 파일 방지 |

## 6. ★ ILM/Replication과의 충돌 지점 정리

### 6.1 충돌 매트릭스

| Iceberg 요소 | ILM Transition | ILM Expiration | Replication | 조치 |
|---|---|---|---|---|
| metadata.json | 🟠 전 쿼리 지연 | 🔴 테이블 즉시 손상 | ✅ 필수 복제 | 전이·만료 **제외** |
| manifest list (snap-*.avro) | 🟠 전 쿼리 지연 | 🔴 스냅샷 접근 불가 | ✅ 필수 | 제외 |
| manifest (*-m*.avro) | 🔴 플래닝 심각 지연 | 🔴 테이블 손상 | ✅ 필수 | 제외 |
| data (Parquet) | ✅ 허용 (설계 의도) | 🔴 **데이터 유실** | ✅ 필수 | transition만 |
| delete file | 🟠 소파일 지연 | 🔴 삭제 반영 소실 → **잘못된 결과** | ✅ 필수 | 가급적 제외 |
| noncurrent 버전 | ✅ 허용 | ✅ **권장** (정리 목적) | 정책에 따라 | noncurrent expiration 사용 |
| delete marker | - | ✅ 고아만 정리 | 정책에 따라 | ExpiredObjectDeleteMarker |

### 6.2 delete file 만료가 만드는 최악의 시나리오

```
1. 사용자가 DELETE FROM tbl WHERE id=100 실행
   → data 파일은 그대로, position delete 파일이 "id=100은 삭제됨"을 기록
2. ILM expiration이 delete 파일을 삭제 (작고 오래됐다는 이유로)
3. Iceberg는 delete 파일이 없으니 삭제를 적용하지 않음
4. 🔴 삭제한 줄이 다시 조회됨 — 오류 없이, 조용히, 잘못된 결과
```

> **에러가 나지 않고 결과만 틀리는 유형**이라 발견이 극히 어렵습니다. 규정 준수(삭제 요청 이행)와 직결될 수 있어 리스크 등급이 높습니다. → [11장 F-08](../11-failure-and-risk/)

### 6.3 프리픽스 분리가 유일한 실용적 통제인 이유

| 대안 | 실현 가능성 | 평가 |
|---|---|---|
| 프리픽스 필터 (`data/`만) | ✅ 쉬움 | **권장** |
| 객체 태그 기반 필터 | 가능하나 Iceberg가 태그를 붙여주지 않음 | ✖ 별도 배치 필요 |
| 객체 크기 필터 (`size-gt`) | 부분적 (metadata는 작으니 큰 것만 전이) | 🟡 보조 수단 |
| 버킷 분리 (data/metadata 다른 버킷) | Iceberg 설정으로 가능하나 복잡 | 🟡 대규모 시 고려 |
| ILM 미사용 + 수동 관리 | 규모상 불가 | ✖ |

### 크기 필터 보조 규칙 (선택)

```json
{
  "ID": "data-transition-large-only",
  "Filter": { "And": { "Prefix": "db.db/tbl/", "ObjectSizeGreaterThan": 8388608 } },
  "Transition": { "Days": 1, "StorageClass": "WARM-TIER" }
}
```

8MB 초과 객체만 전이 → metadata/manifest/delete file(대개 작음)이 자연스럽게 제외됩니다. 🔍 `ObjectSizeGreaterThan` 지원 여부는 버전 확인 필요.

> ⚠️ 크기 필터는 **보조 수단**입니다. 큰 manifest(수 MB)가 있을 수 있으므로 프리픽스 필터와 **함께** 쓰십시오.

## 7. 시간여행(Time Travel)과 ILM

```sql
SELECT * FROM db.tbl VERSION AS OF 8234567890123;
SELECT * FROM db.tbl TIMESTAMP AS OF '2026-08-20 00:00:00';
SELECT * FROM db.tbl.snapshots;
```

| 상황 | 결과 |
|---|---|
| 과거 스냅샷의 data가 전이됨 | ✅ 조회 가능 (느림) |
| 과거 스냅샷의 manifest가 전이됨 | ✅ 가능 (더 느림) |
| 과거 스냅샷 파일이 ILM 만료됨 | 🔴 `NotFoundException` — 시간여행 불가 |
| `expire_snapshots` 로 정리됨 | 정상 (의도된 동작). 스냅샷 자체가 사라짐 |

> ✅ 시간여행 요건이 있다면, **Iceberg 스냅샷 보존 기간**과 **ILM noncurrent 보존 기간**을 함께 설계해야 합니다.

```sql
ALTER TABLE hive_prod.db.tbl SET TBLPROPERTIES (
  'history.expire.max-snapshot-age-ms' = '604800000',   -- 7일
  'history.expire.min-snapshots-to-keep' = '10'
);
```

## 8. 진단용 시스템 테이블

문제 분석 시 가장 먼저 보는 것들입니다.

```sql
-- 현재 스냅샷 목록
SELECT * FROM hive_prod.db.tbl.snapshots ORDER BY committed_at DESC LIMIT 10;

-- 현재 참조 중인 데이터 파일 (경로/크기/레코드수)
SELECT file_path, file_size_in_bytes, record_count, partition
FROM hive_prod.db.tbl.files LIMIT 20;

-- 파일 수/총 크기 요약 — ILM 대상 규모 산정
SELECT count(*) AS files,
       sum(file_size_in_bytes)/1024/1024/1024 AS gb,
       avg(file_size_in_bytes)/1024/1024 AS avg_mb
FROM hive_prod.db.tbl.files;

-- manifest 현황 — 플래닝 비용 지표
SELECT path, length, added_data_files_count, existing_data_files_count
FROM hive_prod.db.tbl.manifests;

-- metadata.json 누적 이력
SELECT * FROM hive_prod.db.tbl.metadata_log_entries ORDER BY timestamp DESC LIMIT 20;

-- 삭제 파일(v2) 현황
SELECT count(*) FROM hive_prod.db.tbl.delete_files;

-- 파티션별 파일 분포 — 작은 파일 탐지
SELECT partition, file_count, total_data_file_size_in_bytes
FROM hive_prod.db.tbl.partitions ORDER BY file_count DESC LIMIT 20;

-- 모든 참조 파일(고아 판정용) — remove_orphan_files 전 대조에 사용
SELECT file_path FROM hive_prod.db.tbl.all_data_files;
SELECT file_path FROM hive_prod.db.tbl.all_manifests;
```

### 이 환경 전용 점검 쿼리

```sql
-- 1) 작은 파일 비율 (전이 시 성능 위험 지표)
SELECT
  sum(CASE WHEN file_size_in_bytes < 8*1024*1024 THEN 1 ELSE 0 END) AS small_files,
  count(*) AS total_files,
  round(100.0*sum(CASE WHEN file_size_in_bytes < 8*1024*1024 THEN 1 ELSE 0 END)/count(*),2) AS small_pct
FROM hive_prod.db.tbl.files;
-- small_pct 가 높을수록 전이 후 지연이 크게 증가 → 10장 §3

-- 2) 파티션별 최신성 (어떤 파티션이 전이 대상이 되는지 예측)
SELECT partition, max(record_count) FROM hive_prod.db.tbl.files GROUP BY partition;
```

| 지표 | 안전 | 주의 | 위험 |
|---|---|---|---|
| 평균 파일 크기 | > 128MB | 32~128MB | < 32MB |
| 소파일 비율 (<8MB) | < 5% | 5~20% | > 20% |
| manifest 수 | < 100 | 100~1,000 | > 1,000 |
| 스냅샷 수 | < 100 | 100~500 | > 500 |
| delete file 수 | < 1,000 | 1,000~10,000 | > 10,000 |

## 9. 이 챕터 요약

1. Iceberg는 **4계층 절대경로 체인**이며, 어느 하나라도 못 읽으면 테이블이 안 열린다.
2. ①②③(metadata/manifest)은 **매 쿼리 경로**, ④(data)만 스캔량 비례 → 전이 대상은 ④뿐.
3. HMS의 `metadata_location`이 절대경로라서 **버킷을 옮기면 테이블이 깨진다** (07장).
4. 파일 삭제는 Iceberg 프로시저만 안전하다. ILM expiration은 참조를 모른다.
5. `remove_orphan_files`는 이 환경에서 **기본 금지**.
6. delete file 만료는 **에러 없이 결과만 틀리는** 최악의 유형.
7. **파일 수가 모든 것을 지배**한다 — 파일 크기 튜닝이 최우선 대응이다.

→ 다음: [06. Spark 환경 구성](../06-spark-setup/)
