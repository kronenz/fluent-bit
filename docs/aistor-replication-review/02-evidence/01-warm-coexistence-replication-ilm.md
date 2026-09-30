# [근거 1] 두 케이스 공존 검토 — 용인 Warm 전용 + 이천 Replication · ILM

> 카테고리: 근거 정리 (Replication — 1순위)
> v3 반영: "용인 데이터는 Warm 클러스터에만 적재·조회하고, 이와 별개로 이천 서비스는 Hot → Warm 버킷 복제와 ILM 을 **둘 다** 사용한다. 두 케이스를 같이 써도 문제가 없는지"
> 관련: [근거 2 Iceberg vs Replication](./02-iceberg-snapshot-vs-replication.md) · [근거 3 Scanner](./03-scanner-impact.md) · [근거 4 ILM Archive](./04-ilm-archive-options.md) · [담당자 우려 확인](../03-future/00-owner-concerns.md)

![두 케이스 공존](../diagrams/03-warm-coexistence.svg)

> Confluence: Gliffy 매크로 → Import → `diagrams/03-warm-coexistence.gliffy` (draw.io 는 `.drawio`)

---

## 1. 케이스 정의

| 케이스 | 주체 | 데이터 위치 | 쓰기 | 조회 | 카탈로그 | Hot 과의 관계 |
|---|---|---|---|---|---|---|
| **Y. 용인 Warm 전용** | 용인 dataops (Trino · Spark) | Warm 의 **용인 전용 버킷** | 용인이 Warm 에 직접 적재 | 용인이 Warm 에서 직접 조회 | **HMS-Warm (용인 원본)** | 없음 (복제 · Tier 대상 아님) |
| **I. 이천 서비스** | 이천 dataops | Hot (원본) | Hot | Hot 엔드포인트 | HMS-Hot | Hot → Warm **Bucket Replication(백업)** + **ILM Transition(용량)** |

| 구분 | 이전 판(v2) 가정 | 이번(v3) 확정 |
|---|---|---|
| 용인 데이터 | Hot 데이터의 Warm 복제본을 조회 | **용인 자체 데이터**를 Warm 에 적재·조회 |
| HMS-Warm | 복제본을 "검증 후 등록" 하는 읽기 전용 카탈로그 | 용인 테이블의 **원본 카탈로그** (등록 Job 불필요) |
| 이천 Replication | 필요성 판단 대상 (모드 ①②③) | **사용 확정 — 백업/DR 용도** (Warm replica 는 평시 조회 없음) |
| 이천 ILM | Replication 다음 순서 | **사용 확정 — Hot 용량 관리** |

## 1-1. 환경 버전 (v3.1)

| 클러스터 | 제품 | 릴리스 | 역할 |
|---|---|---|---|
| Hot | AIStor (상용) | **2026-02-07** | 이천 서비스 원본 · Replication 원본 · ILM 원본 |
| Warm | AIStor (상용) | **2026-06-06** | 이천 replica 대상 · ILM Tier 대상 · 용인 원본 |

> 🚨 **블로커**: Bucket Replication 요구사항 — *"Both the source and destination deployments must run Object Store with matching versions."* / *"server-side bucket replication requires the source and destination bucket be two separate MinIO AIStor clusters running the same Object Store version."* ([M17](./06-official-reference-links.md#m17)). 현재 Hot 과 Warm 의 릴리스가 달라 **복제 구성 전 버전 일치(업그레이드 계획) 가 선행**되어야 합니다. ILM Tier 는 공식 문서에 버전 요구가 없고 "원격 Tier 는 다른 클러스터여야 함" 만 명시 ([M18](./06-official-reference-links.md#m18)).

## 2. 결론 — 공존 가능 (조건부)

| # | 결론 | 근거 |
|---|---|---|
| 0 | **Hot(2026-02-07) · Warm(2026-06-06) 버전 불일치는 Bucket Replication 요구사항 위반** — 복제 구성 전에 두 클러스터 릴리스를 맞춰야 한다 (업그레이드 대상 · 순서 · 호환성은 벤더 확인) | [M17](./06-official-reference-links.md#m17) |
| 1 | 두 케이스는 **한 Warm 클러스터에서 공존 가능**하다. 단 Warm 이 **3개 역할**(용인 원본 · 이천 replica · ILM tier)을 동시에 하므로 **버킷 단위로 역할을 분리**해야 한다 | 아래 §3, §4 |
| 2 | 이천의 Hot → Warm 복제는 **Bucket Replication** 으로만 구성한다. **Site Replication 은 쓸 수 없다** | Site Replication 은 Bucket Replication 과 상호 배타이고, 구성 시 다른 사이트가 비어 있어야 함 — Warm 에는 용인 데이터가 있음 ([M16](./06-official-reference-links.md#m16)) |
| 3 | 이천에서 Replication 과 ILM 을 **같이 쓰는 것 자체는 문제없다**. 역할이 다르다 — **Replication = 백업, Transition = 용량 관리** | "Using object transition does not provide any additional business continuity or disaster recovery benefits." · 백업은 Replication 사용 권고 ([M15](./06-official-reference-links.md#m15)) |
| 4 | 다만 같은 객체에 둘을 걸면 **Warm 에 이중 저장**(replica + tier)되고, **ILM 삭제는 복제되지 않으며**, **resync 시 Tier 연결이 끊어진다** → 대상 prefix · replica 측 ILM · resync 절차를 설계해야 한다 | [M3](./06-official-reference-links.md#m3), [M5](./06-official-reference-links.md#m5) |
| 5 | ILM Tier 버킷/prefix 는 **AIStor 독점 영역**이다. 용인이나 사람이 직접 접근·수정하거나 ILM 을 걸면 데이터가 유실될 수 있다 | [M14](./06-official-reference-links.md#m14) |
| 6 | 이천 replica 는 평시 조회하지 않으므로 Iceberg 충돌 C1·C2 는 **복구 시점 문제**가 된다 → 백업 시점 테스트(T-B)와 복구 시 검증 후 등록으로 관리 | [근거 2](./02-iceberg-snapshot-vs-replication.md) |
| 7 | Warm 은 복제 수신 + Tier 수신 + 용인 read/write + Scanner 를 동시에 처리한다. **공존 부하와 용량은 측정·산정이 필요**하다 (공식 가이드 없음) | [근거 3](./03-scanner-impact.md), 공식 문서 부재 |

## 3. Warm 클러스터 버킷 역할 분리

| 역할 | 버킷 / prefix | 쓰기 주체 | Versioning | ILM | 접근 허용 | 금지 |
|---|---|---|---|---|---|---|
| ① 이천 replica | Hot 과 **동일 버킷명** (예: `lake`, `raw`) | Replication 만 | **필수** (양쪽) | **별도 설정** — noncurrent 만료 · 보존 기간 | 복제 서비스 계정 · 복구 담당 (읽기) | 용인 · 사용자 직접 쓰기 |
| ② ILM tier | 전용 버킷 또는 **전용 prefix** (예: `hot-tier/`) | Hot 의 Transition 만 | Tier 요구 사항 따름 🔍 | **금지** | Hot 에 등록된 tier 계정만 | 직접 조회 · 수정 · 삭제 · ILM |
| ③ 용인 원본 | `yongin-*` (용인 명명 규칙) | 용인 Trino · Spark | 선택 (Iceberg 유지보수 고려) | 필요 시 Expiration (Transition 없음 — Warm 이 최종 계층) | 용인 access key | Hot 복제 · Tier 대상 지정 |

| 분리 규칙 | 이유 |
|---|---|
| Hot 버킷명은 Warm 에서 **예약** — 용인 버킷명과 겹치지 않게 | replica 버킷명이 Hot 과 같아야 Iceberg 절대경로를 복구 시 그대로 쓸 수 있음 ([근거 2 §4](./02-iceberg-snapshot-vs-replication.md)) |
| access key 를 역할별로 분리 (replica · tier · 용인) | 용인 작업이 replica/tier 를 건드리면 백업 오염 · Tier 유실 |
| tier 는 전용 버킷 권장, 공유 시 prefix 로 격리 | "If the remote bucket contains existing data, use the prefix feature to isolate transitioned objects" ([M14](./06-official-reference-links.md#m14)) |

## 4. 이천 — Replication + ILM 동시 사용 검토

| # | 검토 항목 | 문제 여부 | 설명 | 대응 | 근거 |
|---|---|---|---|---|---|
| P-0 | **버전 일치** | **블로커** | Hot 2026-02-07 ≠ Warm 2026-06-06 — Bucket Replication 은 동일 Object Store 버전 필수 | 업그레이드 계획(대상 · 순서 · 롤백) 벤더 확인 후 버전 일치 → 이후 복제 구성 · 이후 업그레이드도 양쪽 동시 계획 | [M17](./06-official-reference-links.md#m17) |
| P-1 | 역할 충돌 | 없음 | Replication = 백업 사본, Transition = 용량 이동. 목적이 다름 | 목적을 문서화 | [M15](./06-official-reference-links.md#m15) |
| P-2 | Warm 이중 저장 | **주의** | 같은 객체가 replica 버킷과 tier 에 모두 저장됨 | Transition 대상 prefix 와 복제 대상 prefix 를 설계 · Warm 용량 = replica + tier + 용인 | 설계 판단 |
| P-3 | ILM Expiration 삭제 미복제 | **주의** | Hot 에서 ILM 으로 지운 객체는 replica 에 남음 | replica 버킷에 **별도 ILM**(보존 기간 · noncurrent 만료) 설정 | [M3](./06-official-reference-links.md#m3) |
| P-4 | resync 시 Tier 단절 | **주의** | resync 하면 Tiering 된 객체가 non-transitioned 상태로 복원되고 remote 데이터와 영구 단절 | resync 는 절차 승인 후에만 · Tier 용량 회수 계획 포함 | [M5](./06-official-reference-links.md#m5) |
| P-5 | Tier 버킷 규칙 | **필수 준수** | tier 데이터는 AIStor 전용, 외부 변경·ILM 금지 | 역할 분리(§3), 권한 차단 | [M14](./06-official-reference-links.md#m14) |
| P-6 | Site Replication | **사용 불가** | Bucket Replication 과 상호 배타 · 다른 사이트는 비어 있어야 함 | Bucket Replication 으로 버킷별 규칙 구성 | [M16](./06-official-reference-links.md#m16) |
| P-7 | ILM 설정 복제 | 해당 없음 | Bucket Replication 은 ILM 설정을 복제하지 않음(Site Replication 도 기본 미복제) | Hot · Warm ILM 을 각각 관리 | [M16](./06-official-reference-links.md#m16) |
| P-8 | Iceberg 일관성 | 복구 시 | replica 는 스냅샷 단위 일관성 없음(C1) · 카탈로그 없음(C2) | T-B 백업 시점 테스트 · 복구 시 검증 후 등록 (그림 10) | [근거 2](./02-iceberg-snapshot-vs-replication.md) |
| P-9 | Scanner | **주의** | Hot Scanner 가 Transition · 복제 재큐잉을 함께 처리, Warm Scanner 는 용인 · replica 버킷 ILM 처리 | 양쪽 Scanner 사이클 모니터링 | [근거 3](./03-scanner-impact.md) |
| P-11 | ILM Tier 버전 | 확인 | Tier 는 버전 요구 문구 없음 · 원격은 다른 클러스터여야 함 (Hot ≠ Warm ✓) | 상용 버전 호환 매트릭스 벤더 확인 | [M18](./06-official-reference-links.md#m18) |
| P-10 | Transition 순서 | 🔍 | 복제가 끝나기 전에 Transition 되는 경우의 동작은 공식 문서 미기재 | Transition 경과일 ≫ 복제 지연 · 테스트로 확인 | 문서 부재 |

## 5. 용인 — Warm 전용 사용 검토

| # | 검토 항목 | 문제 여부 | 설명 | 대응 |
|---|---|---|---|---|
| Y-1 | 복제·Tier 와 무관 | 없음 | 용인 버킷은 Hot 과 관계가 없으므로 C1~C5 충돌 대상 아님 | 용인 버킷을 복제·Tier 대상에서 제외 |
| Y-2 | 카탈로그 | 없음 | HMS-Warm 이 원본 카탈로그 — 용인 엔진이 직접 커밋 | 검증·등록 Job 불필요 |
| Y-3 | 네트워크 | **필수** | 용인 → 이천 Warm read/**write** (대용량 적재 포함) | 방화벽 · VIP · 대역폭 · multipart 타임아웃 ([향후 1](../03-future/01-yongin-network-checklist.md)) |
| Y-4 | 성능 경합 | **주의** | Warm 에 복제 · Tier 유입과 용인 I/O 가 겹침 | 피크 시간대 측정 · 복제 대역폭 제한 검토 |
| Y-5 | 권한 | **필수** | 용인 키가 replica · tier 버킷에 접근하면 안 됨 | 버킷 정책으로 `yongin-*` 만 허용 |
| Y-6 | Iceberg 유지보수 | 일반 | 용인 테이블의 compaction · expire_snapshots 는 용인이 수행 | Versioning 사용 시 noncurrent 만료 규칙 |
| Y-7 | 백업 | **결정 필요** | 용인 데이터는 Warm 에만 있음 → 별도 백업이 없음 | 용인 데이터 백업 요구(RPO) 확인 — 필요 시 별도 대상 검토 |

## 6. 이천 replica — 백업 시점 테스트 (T-B)

### 6.1 테이블 특성별 백업 시점 가설

| 테이블 유형 | 예 | 변경 패턴 | 백업 시점 가설 | 확인할 것 |
|---|---|---|---|---|
| Append-only | RAW · 로그 · 이벤트 | 파티션 단위 추가만 | 실시간 복제로 충분 (파티션 마감 후 검증) | 마감 판정 기준 |
| MERGE/UPDATE 많음 | CDC · 팩트 | 파일 재작성 빈번 | `rewrite_data_files` 직후 일관 시점 확보 | compaction 주기와 RPO |
| 소형 디멘전 | 코드 · 마스터 | 전체 교체 | 전체 스냅샷 주기 확인 | 크기 · 주기 |
| 대형 이력 파티션 | 월/연 단위 이력 | 마감 후 거의 불변 | 마감 파티션 1회 복제 확인 | 재처리 시 재복제 |

### 6.2 테스트 항목

| ID | 테스트 | 절차 | 측정 · 판정 |
|---|---|---|---|
| T-B1 | compaction 후 복제 | `rewrite_data_files` → 복제 완료 대기 | 복제 객체 수 · 용량 · 소요 시간 |
| T-B2 | 스냅샷 정리 후 복제 | `expire_snapshots` · `remove_orphan_files` → 복제 | delete / delete-marker 반영 (`--replicate` 플래그별) |
| T-B3 | 복제 규칙 일시 중지 → 재개 | disable → 쓰기·유지보수 → enable | 중지 중 쓰인 객체 복제 여부 · 누락분 처리 🔍 |
| T-B4 | 시점 지정 방식 비교 | (a) 실시간 + 검증 시점 기록 (b) 규칙 on/off (c) `mc mirror` (d) `rewrite_table_path` + 복사 | 지원 여부 · 일관성 · 운영 난이도 🔍 |
| T-B5 | 복사 순서 제어 | data → manifest → metadata.json 순 | 복사 중 register 해도 일관된 스냅샷인지 |
| T-B6 | 복구 리허설 | Warm replica → 복구용 HMS 에 `register_table` → Trino 조회 | 행 수 · 체크섬 · 스냅샷 ID 일치 |
| T-B7 | 유형별 RPO 산정 | 6.1 의 4개 유형 대표 테이블 | 백업 시점 ≤ 허용 RPO |
| T-B8 | **Replication + Transition 병행** | 같은 prefix 에 복제 규칙 + Transition 규칙 → 경과일 도달 | replica 존재 · Tier 이동 · Warm 용량 증가량 · Hot 조회 정상 |
| T-B9 | **공존 부하** | 복제 · Tier 유입 중 용인 적재/조회 부하 | Warm 지연 · 처리량 · Scanner 사이클 변화 |

## 7. 확인 필요 사항 (진행 체크)

| # | 확인 항목 | 확인처 | 상태 |
|---|---|---|---|
| E1-1 | 이천 복제 대상 버킷/prefix 와 Transition 대상 prefix 목록 (중복 범위) | 이천 서비스 · 플랫폼 | ☐ |
| E1-2 | 이천 백업 RPO · RTO, 용인 데이터 백업 요구 여부 (Y-7) | 담당자 | ☐ |
| E1-3 | 시점 지정 복제 방식 지원 여부 · Transition-복제 순서 동작 (P-10) | PDF-5, PDF-2, 벤더 | ☐ |
| E1-4 | Warm 용량 산정 = replica + tier + 용인 (+ 버전) | 플랫폼 | ☐ |
| E1-5 | 역할별 버킷 · 명명 규칙 · access key 정책 확정 | 플랫폼 · 보안 | ☐ |
| E1-6 | T-B1 ~ T-B9 수행 | 데이터엔지니어링 | ☐ |
| E1-7 | **Hot/Warm 버전 일치 계획** — 업그레이드 대상(Hot → 2026-06-06 또는 동일 릴리스), 순서, 복제 중단 여부, 롤백 | 벤더 · 플랫폼 (PDF-5, PDF-1) | ☐ |
| E1-8 | 버전 일치 후 운영 규칙 — 향후 업그레이드는 Hot · Warm 동시(같은 창) 수행 | 플랫폼 | ☐ |
