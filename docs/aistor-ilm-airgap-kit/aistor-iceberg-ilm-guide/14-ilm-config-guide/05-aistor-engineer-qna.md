# 05. AIStor 엔지니어 방문 질의 — Scanner 최적화 · Iceberg 충돌 해결 · 확인 사항

> 목적: 대규모 클러스터에서 Hot→Warm ILM 을 운영할 때 **Scanner 부하를 줄이는 방안**을 제안하고, AIStor 엔지니어에게 확인받을 항목을 정리한다.
> 근거: corp 테스트베드 실측 (MinIO RELEASE.2024-10-13 단일 노드, 2026-10-25 ~ 28) — [13장 결과](../13-ilm-hot-only-test/README.md#10-결과-기록표) · 이 문서의 T-1/T-2 는 2026-10-28 추가 실측
> 상세 해설 · 그림: [15장 사전 학습](../15-aistor-engineer-briefing/) — 질의 전에 읽기
> 표기: ✅ 실측 확인 · 💡 제안(설계) · ❓ 엔지니어에게 질의 · 🔍 운영 버전에서 재확인

## 0. 한 장 요약

| 주제 | 제안 | 근거 |
|---|---|---|
| Scanner 부하 | ① 객체 · 버전 수 자체를 줄인다 (compaction · 스냅샷 만료 · 비현행 정리) ② **전이를 Scanner 에서 떼어 낸다 — 태그 기반 즉시 전이** ③ Scanner 속도는 시간대별로만 조절 | ✅ T-1: 태그 붙여 쓴 파일이 **PUT 순간 Warm 전이** (Scanner 대기 0) |
| Iceberg × ILM 만료 충돌 | **Iceberg soft delete 태그 + 태그 필터 Expiration** — ILM 은 Iceberg 가 지운 파일만 만료 | ✅ T-2: 같은 나이(2일)의 파일 중 Iceberg 가 지운 4개만 만료, 살아 있는 4개 · 테이블 정상 |
| Iceberg × Replication 충돌 | 객체 복제만으로는 스냅샷 일관성 불가 → **"파일 복제 + 검증 후 등록"** 또는 **Iceberg `rewrite_table_path` 기반 복사** | 설계 (기존 검토 문서 연계) |
| 질의 | Scanner 내부 동작 · 규모별 사이클 · 태그 규칙 · 즉시 전이 큐 · 복제와 전이 순서 등 30여 항목 | §4 |

---

## 1. 문제 정의 — Scanner 가 하는 일과 비용

| 사실 | 의미 | 근거 |
|---|---|---|
| ILM 의 "Days" 규칙은 **Scanner 가 객체를 방문할 때** 실행된다 (예정 시각 = `mtime + Days` → 다음 00:00 UTC 올림) | 전이 · 만료 지연 = 올림 + Scanner 사이클 | ✅ 1d 연속: 첫 전이 10-27 **00:15** UTC · `mc stat` 예정 시각 |
| 예정 시각이 이미 지난 객체는 **PUT 즉시** 처리된다 | Scanner 를 거치지 않는 경로가 있다 | ✅ 0d 전이 · 소급 PUT · T-1 |
| Scanner 는 폴더 단위로 순회하며 사이클마다 일부만 본다 | 기존 객체 대량 적용 시 오래 걸림 | ✅ 4,000 객체 914초 (기본, 4.5개/s) — 100개 폴더 단위 계단 |
| 속도를 올리면 **할 일이 없어도** CPU 를 쓴다 | 상시 가속은 비용 | ✅ `fastest` 유휴 Hot CPU 14m → 82m, 전이 순간 Warm 380m · 990 Mi |
| Scanner 는 ILM 외에 사용량 집계 · healing 점검 · 복제 상태 점검도 같은 루프에서 한다 (❓ AIStor 확인) | ILM 만 끄거나 늦출 수 없다 | MinIO 동작 기준 — §4 Q-S1 |
| 모든 1d 대상이 같은 00:00 UTC 에 만기 | 자정 직후 사이클에 전이가 몰린다 | ✅ 올림 규칙 |

**비용 ≈ (객체 수 × 버전 수) / 사이클 속도**, **ILM 반응 시간 ≈ 00:00 올림 + 사이클 길이**.
대규모 클러스터에서 Scanner 를 자주 돌리기 어렵다면 남는 방법은 ⓐ 셀 대상을 줄이거나 ⓑ ILM 을 Scanner 밖으로 빼는 것이다.

---

## 2. Scanner 최적화 제안

### 💡 S-1. 셀 대상 줄이기 — 객체 · 버전 수 관리 (효과 큼, 위험 낮음)

| 대상 | 방법 | 비고 |
|---|---|---|
| 작은 파일 | Iceberg `rewrite_data_files` (목표 256~512 MB) — 매일 지난 파티션 | Warm 경유 읽기도 파일 수에 비례해 느려진다 (P-3) |
| 옛 스냅샷 파일 | `expire_snapshots` + `remove_orphan_files` 정례화 | 지운 파일은 Versioning 때문에 비현행으로 남는다 |
| 비현행 버전 | `NoncurrentVersionExpiration` 1일 (+ ❓ `NewerNoncurrentVersions` 병행) | Versioning ON 이면 Iceberg 삭제 = 버전 증가 |
| delete marker | `ExpiredObjectDeleteMarker` | ✅ E-5: 비현행 소멸 후 DM 정리 확인 |
| 감시 | `scanner alert_excess_versions=100 · alert_excess_folders=50000` (현재 기본값) 경보 수집 | ❓ 경보가 어디로 나오는지 (로그 · 메트릭 · 웹훅) |

### 💡 S-2. 전이를 Scanner 에서 떼어 내기 — 태그 기반 즉시 전이 (✅ T-1 실측)

```
평소 쓰기 (태그 없음) ──────────────► Hot STANDARD
매일 tiering compaction (Spark, 별도 카탈로그 s3.write.tags.ilm-tier=warm)
  rewrite_data_files(where: 파티션 < 오늘-1일)
     └─ 새 파일 PUT (태그 ilm-tier=warm) ──► 규칙 Transition 0d · And{Prefix <tbl>/data/, Tag ilm-tier=warm}
                                            → PUT 순간 Warm 전이 (Scanner 대기 없음)
안전망: Transition N일(예: 3d) · Prefix <tbl>/data/ (태그 없음) — 작업이 빠진 파일은 Scanner 가 처리
```

| 실측 (T-1) | 결과 |
|---|---|
| tiering 카탈로그로 old 배치 rewrite (4 → 1 파일) | 새 파일 태그 `ilm-tier=warm` · **같은 초(00:34:15)에 WARM-TIER** |
| 같은 커밋의 metadata 파일 | 태그는 붙지만 규칙이 `data/` prefix 로 묶여 있어 **STANDARD 유지** |
| 이후 조회 | old · new 배치 count · checksum 일치, 전체 스캔 정상 |
| 이미 있는 객체에 나중에 태그 (`PutObjectTagging`) | **즉시 전이 안 됨** — Scanner 방문까지 STANDARD (2분 이상 관찰) |

| 장점 | 단점 · 확인 필요 |
|---|---|
| 전이 시점을 **작업 스케줄로 통제** (자정 쏠림 · Scanner 사이클과 무관) | 파일을 한 번 다시 써야 한다 (Hot 쓰기 + 즉시 Warm 복사 = I/O 2회) → compaction 과 합쳐야 이득 |
| compaction + 전이를 한 번에 → Warm 파일 수 감소 | 태그는 **PUT 시점**에만 즉시 전이를 일으킨다 — 나중에 태그를 다는 방식은 Scanner 의존 |
| Scanner 는 안전망만 맡으므로 속도를 낮춰도 된다 | ❓ 즉시 전이 큐 용량 · 대량 PUT 시 `transition_missed_immediate_tasks` 로 밀리면 Scanner 로 넘어가는지 |
| 규칙 · 태그로 테이블별 정책 차등 가능 | 모든 쓰기 엔진(Spark · Trino)이 태그 설정을 지켜야 한다 (안전망 규칙으로 보완) |

### 💡 S-3. Scanner 속도는 "시간대별로만"

| 시간대 | speed | 방법 |
|---|---|---|
| 업무 시간 | `slow` 또는 `default` | K8s CronJob 이 `mc admin config set <alias> scanner speed=…` |
| 야간 · 주말 | `default` 또는 `fast` | 같은 방식 |
| 대량 기존 버킷 첫 적용 | `fast`/`fastest` 한시 → 원복 | `run-perf-impact.sh` 의 trap 처럼 원복 보장 |

❓ 설정 변경이 재시작 없이 즉시 반영되는지 · 진행 중 사이클에 바로 적용되는지 · 노드별로 다르게 줄 수 있는지 (Q-S4)

### 💡 S-4. 자정 쏠림 완화

- 1d 대상이 모두 00:00 UTC 에 만기 → S-2 로 tiering 작업을 다른 시간대에 돌리면 쏠림이 사라진다.
- S-2 를 못 쓰면 테이블별로 Days 를 다르게 두는 것(1d · 2d)도 분산 효과가 있다 (요일별 부하 분산 정도).

### 💡 S-5. 모니터링 (판단 근거)

| 지표 | 쓰임 |
|---|---|
| `minio_node_scanner_objects_scanned` · `bucket_scans_finished` · (❓ 사이클 소요 시간 지표) | 사이클 길이 추정 → ILM 반응 시간 |
| `minio_node_ilm_transition_pending_tasks` · `active_tasks` · `missed_immediate_tasks` | 즉시 전이 큐 포화 여부 (S-2) |
| `minio_node_tier_requests_failure` | Warm 연결 |
| `minio_node_process_cpu_total_seconds` (Hot · Warm) | Scanner 속도 변경 효과 |

---

## 3. Iceberg × ILM · Replication 충돌 해결

### ✅ C-1. ILM 만료 × Iceberg → Soft delete 태그 + 태그 필터 Expiration (T-2 실측)

문제: `data/` 에 나이 기반 Expiration 을 걸면 **스냅샷이 참조하는 파일**도 지워져 테이블이 깨진다 (✅ E-3: `NotFoundException`).
해결: 삭제 판단은 Iceberg 가 하고, ILM 은 **Iceberg 가 지운다고 표시한 파일만** 만료한다.

```
Spark 카탈로그 (보존 작업 · 유지보수용)
  s3.delete-enabled = false                ← 파일을 지우지 않고
  s3.delete.tags.iceberg-deleted = true    ← 태그만 단다
ILM 규칙
  Expiration Days 1 · And{Prefix <tbl>/data/, Tag iceberg-deleted=true}
  (Versioning ON 이면 + NoncurrentVersionExpiration 1d · ExpiredObjectDeleteMarker)
```

| 실측 (T-2) | 결과 |
|---|---|
| 모든 data 파일 나이 2일 → old 배치 DELETE + expire_snapshots | 파일 4개가 **지워지지 않고 태그 `iceberg-deleted=true`** |
| 태그 필터 Expiration 1d 적용 | 약 10초 뒤 태그 붙은 4개만 delete marker, **같은 나이의 살아 있는 4개는 그대로** |
| 테이블 조회 | 남은 배치 100,000행 · 전체 스캔 정상 |
| 이미 Warm 으로 전이된 객체에 태그 | 붙는다 · 읽기 정상 (Warm 파일도 soft delete 가능) |

- 장점: ILM 이 실수로 살아 있는 파일을 지울 수 없다. 대량 삭제 I/O 를 Spark 에서 S3 백그라운드로 넘긴다. "Hot 1일 + Warm 4일 보존" 을 Iceberg 보존 작업과 자연스럽게 연결.
- 주의: 태그 설정을 안 쓴 엔진이 지우면 그냥 삭제된다 (안전 쪽 실패). `remove_orphan_files` 도 같은 FileIO 삭제 경로인지 🔍. 태그를 단 순간 즉시 만료되지는 않는다 — 이미 기한 지난 객체도 Scanner 방문 시 처리 (T-2 는 마침 10초).
- 기존 위험 규칙 검사(`00-apply-ilm.sh`)는 이 규칙을 "current Expiration" 으로 막는다 → 태그 필터가 `iceberg-deleted` 인 규칙은 허용하도록 고쳐야 한다 (후속).

### ✅ C-2. ILM 전이 × Iceberg → 충돌 없음

경로가 그대로라 Iceberg · HMS · Spark 변경이 없다 (✅ I-1~I-5, 1d 연속 J-1~J-8). 비용은 Warm 경유 읽기 지연뿐 (1d 연속 p50 417 → 642 ms).

### 💡 C-3. Replication × Iceberg

객체 단위 비동기 복제는 **커밋 단위(스냅샷) 일관성을 보장하지 않는다** — metadata.json 이 먼저 도착하고 참조 파일이 아직 없으면 replica 쪽 테이블은 깨진 상태다 ([aistor-replication-review](../../aistor-replication-review/) C1~C5).

| 해결안 | 방법 | 장단점 |
|---|---|---|
| R-A 파일 복제 + **검증 후 등록** | 버킷 복제는 그대로 두고, replica 측은 카탈로그에 바로 연결하지 않는다. 주기 작업이 최신 `metadata.json` → manifest list → manifest → data 파일 존재를 확인한 스냅샷만 replica 카탈로그에 `register_table` | 기존 복제 기능 그대로 · 검증 작업 필요 · RPO = 복제 지연 + 검증 주기 |
| R-B **Iceberg 수준 복사** | Iceberg `rewrite_table_path` (1.8+) 로 스냅샷 단위 복사 목록 생성 → Batch Replication · distcp 로 복사 → 대상에서 등록 | 스냅샷 일관성 보장 · 증분 가능 · Versioning 불필요 (🔍 버전 확인) |
| R-C 복제 순서 보장 | metadata/ 를 data/ 보다 늦게 복제 (별도 규칙 · 지연) | ❓ 복제 우선순위 · 지연 설정 지원 여부 — 보장은 어려움 |

추가 충돌 지점

| 지점 | 해결안 |
|---|---|
| 복제 + 전이 (같은 객체) | 복제 완료 후 전이 — Days ≥ 복제 지연, ❓ 복제 미완료(PENDING) 객체는 전이를 건너뛰는지 |
| 태그 기반 정책(S-2 · C-1)과 복제 | 태그가 복제되면 replica 쪽 ILM 이 같은 태그로 동작 — replica 에 같은 규칙을 둘지 결정 · ❓ 태그 변경(PutObjectTagging) 복제 여부 · 설정 |
| 삭제 복제 | soft delete(C-1)면 원본은 태그 → ILM 만료(DM) → DM 복제 설정에 따라 replica 반영. replica 를 백업으로 쓰면 DM 복제를 끄고 replica 측 정리 정책을 따로 |
| resync | Tier 연결된 버킷 resync 시 전이 객체 처리 ❓ (기존 검토: Tier 연결 단절 위험) |

---

## 4. 엔지니어 질의 목록

### Scanner

| # | 질의 | 왜 |
|---|---|---|
| Q-S1 | Scanner 한 루프에서 하는 일 (ILM · 사용량 · healing · 복제 점검 · 쿼터) 과 각각 끄거나 주기를 따로 줄 수 있는지 | ILM 만 빠르게 · 나머지는 느리게 하고 싶다 |
| Q-S2 | 우리 규모(객체 <N>억 · 버전 <M> · 노드 <K> · 드라이브 <D>)에서 `default` 사이클 소요 예상 · 실측 사례 | ILM 반응 시간 산정 (테스트: 단일 노드 4.5 객체/s) |
| Q-S3 | 바뀌지 않은 폴더를 건너뛰는 방식(변경 추적 · bloom filter) 과 몇 사이클마다 전체를 보는지 | 정적 데이터가 많은 버킷의 비용 |
| Q-S4 | `scanner speed` 변경의 즉시 반영 · 노드별 설정 · 시간대 스케줄 공식 기능 여부 | S-3 |
| Q-S5 | 버킷 · prefix 단위로 Scanner 대상 제외 · 우선순위 지정 가능 여부 (예: ILM 없는 버킷 제외) | 대상 축소 |
| Q-S6 | 사이클 진행률 · 소요 시간 지표 (v3 metrics 이름) · `mc admin scanner status` 같은 진단 명령 | S-5 |
| Q-S7 | `alert_excess_versions` · `alert_excess_folders` 경보가 어디로 나오는지 · 권장값 | 버전 폭증 조기 감지 |
| Q-S8 | Erasure set · pool 수가 늘면 Scanner 가 병렬로 도는지 (노드 추가 = 처리율 증가?) | 증설 효과 |

### ILM · 태그 (S-2 · C-1)

| # | 질의 |
|---|---|
| Q-I1 | 태그 필터(And{Prefix, Tag}) + Transition 0d 가 PUT 즉시 전이되는 것이 **공식 동작**인지 · 대량 PUT 시 즉시 전이 큐(작업자 수 · 대기열 한도) 와 넘칠 때 동작 (`missed_immediate` → Scanner 로 넘어가는지) |
| Q-I2 | `PutObjectTagging` 이 lifecycle 재평가를 일으키지 않는 것이 의도된 동작인지 · 즉시 평가 옵션 |
| Q-I3 | 태그 필터 Expiration(soft delete 패턴)을 대규모로 쓸 때 주의점 · 태그 수 · 태그 조회 비용 |
| Q-I4 | ILM 실행 시각의 00:00 UTC 올림 — 시간대 변경 · 분산 옵션 |
| Q-I5 | 버킷당 규칙 수 한도 · 규칙이 많을 때 Scanner 비용 (테이블별 규칙 수백 개) |
| Q-I6 | `NewerNoncurrentVersions` 지원 · `NoncurrentDays` 와 함께 쓸 때 동작 |
| Q-I7 | Batch 프레임워크(`mc batch`)에 expire 외 **transition 작업**이 있는지 (Scanner 없이 일괄 전이) |
| Q-I8 | 🔍 Versioning ON 에서 **전이된 current 버전이 만료되면 Warm 원본이 즉시 삭제되고 비현행 기록만 남는 동작**(테스트 F-1) 이 AIStor 에서도 같은지 · 의도인지 |

### Tier (Warm)

| # | 질의 |
|---|---|
| Q-T1 | Warm tier 버킷 Versioning 권장 여부 · tier 버킷에 Object Lock · 복제를 걸 수 있는지 |
| Q-T2 | Warm 장애 시 Hot 동작 — 전이 객체 GET 오류 형태 · 타임아웃 · 전이 작업 재시도/적체 |
| Q-T3 | tier 자격증명 교체 절차 (`mc ilm tier edit`) · 무중단 여부 |
| Q-T4 | 전이 객체 Hot 읽기 경로 최적화 (캐시 · 범위 읽기 · 병렬) — Parquet footer · column chunk 범위 읽기 지연 |
| Q-T5 | 전이 객체를 Hot 으로 되돌리기 (restore · 규칙 삭제 후 재기록) 권장 방법 |
| Q-T6 | Warm 용량 회수 시점 — 만료 후 tier 삭제 작업(journal)의 지연 · 실패 재시도 · 확인 지표 |

### Replication

| # | 질의 |
|---|---|
| Q-R1 | 복제 미완료(PENDING) 객체를 전이 · 만료가 건너뛰는지 (C-3) |
| Q-R2 | 전이된 객체를 복제할 때 Warm 에서 읽어 보내는지 · replica 쪽 저장 형태 |
| Q-R3 | 태그 변경 · delete marker 복제 설정과 기본값 |
| Q-R4 | 복제 우선순위 · prefix 별 지연 (metadata/ 를 늦게) 가능 여부 |
| Q-R5 | Batch Replication 에 Versioning 이 필요한지 · `rewrite_table_path` 산출 목록으로 복제 작업을 만들 수 있는지 |
| Q-R6 | Tier 연결된 버킷의 resync 시 동작 |

### 버전 · 운영

| # | 질의 |
|---|---|
| Q-O1 | 운영 버전(Hot 2026-02-07 · Warm 2026-06-06)에서 위 동작 차이 · 업그레이드 권장 버전 |
| Q-O2 | `X-Minio-Source-Mtime` 소급 PUT 이 AIStor 에서 동작하는지 — 시험용 (폐쇄망 runbook E-0) |
| Q-O3 | metrics v2 → v3 이름 대응 · 인증 토큰 · 권장 대시보드 |
| Q-O4 | 사용량 집계에서 전이 객체 표시 (Hot 사용량 · Warm 사용량 · 논리 크기) |
| Q-O5 | 감사 로그에서 tier 계정 요청 식별 · Warm 접근 통제 권장 구성 |

---

## 5. 시험 근거 위치

| 항목 | 증적 |
|---|---|
| T-1 · T-2 (태그) | `13-ilm-hot-only-test/results/tag-20261028/` (`ilmtest.tag.jsonl` · 규칙 export) · 스크립트 `scripts/spark/tag_tiering.py` |
| Scanner 속도 · 처리율 | `results/REPORT-perf-impact-20261026.md` |
| 기한 삭제 · F-1 · 00:00 올림 | `results/REPORT-expiry-20261026.md` |
| 1d 연속 | `README.md` §10 (J-1~J-8 ✅, 첫 전이 10-27 00:15 UTC, 전이 배치 읽기 p50 642 ms) |
