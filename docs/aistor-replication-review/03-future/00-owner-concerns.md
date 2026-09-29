# [향후 0] 담당자 우려사항 확인 — 가장 먼저 진행

> 카테고리: 향후 구성 대응 (선행 단계 M0)
> 피드백 반영: "담당자가 어떤 걸 우려하는지 확인 필요"
> 목적: 우려사항에 따라 Replication 모드(① 조회용 / ② 백업용 / ③ 불필요)와 ILM 아카이브 방식(A/B/C)이 달라지므로, 설계·테스트 착수 전에 확인한다.

---

## 1. 확인 질문 — Replication (우선)

| # | 질문 | 답에 따라 달라지는 것 | 관련 문서 | 답변 | 확인일 |
|---|---|---|---|---|---|
| OC-1 | Warm MinIO 데이터를 HMS(Trino·Polaris)로 **직접 조회**할 계획/사용자가 있는가? 누가, 얼마나 자주? | 모드 ① 여부 → 장표 2 · HMS-Warm · 용인 네트워크 전체 필요 여부 | [근거 1](../02-evidence/01-replication-necessity-backup.md) | | |
| OC-2 | Replication 을 원하는 이유는? (백업·DR / 원격 조회 / 용량 분산 / 규정) | 모드 ② ③ 판단 | [근거 1](../02-evidence/01-replication-necessity-backup.md) | | |
| OC-3 | 허용 RPO · RTO 는? (테이블 등급별) | 백업 시점·주기 (T-B) | [근거 1 §3](../02-evidence/01-replication-necessity-backup.md) | | |
| OC-4 | Iceberg 테이블 **일관성**(부분 복제 스냅샷)에 대한 우려가 있는가? | 검증 후 등록 · 유지보수 후 복제 필요성 | [근거 2](../02-evidence/02-iceberg-snapshot-vs-replication.md) | | |
| OC-5 | 복제로 인한 **용량(2배)·대역폭·비용** 우려는? | 복제 대상 범위 (버킷·프리픽스·테이블 선별) | [장표 1](../01-architecture/01-hot-warm-icheon-dataops.md) | | |
| OC-6 | Hot 에서 삭제(expire_snapshots · RAW 정리)한 데이터가 Warm 에서도 **지워져야 하는가, 남아야 하는가**? | `--replicate delete,delete-marker` 설정 | [근거 2 C3](../02-evidence/02-iceberg-snapshot-vs-replication.md) | | |
| OC-7 | 복제 검증·등록 Job 같은 **운영 부담**을 누가 맡는가? | 모드 ① 채택 가능성 | [HMS To-do](./02-hms-oracle-split-todo.md) | | |
| OC-8 | Scanner 부하 · 복제 지연에 대한 경험/우려가 있는가? | 모니터링 · speed 설정 | [근거 3](../02-evidence/03-scanner-impact.md) | | |

## 2. 확인 질문 — ILM / Archive (다음)

| # | 질문 | 답에 따라 달라지는 것 | 관련 문서 | 답변 | 확인일 |
|---|---|---|---|---|---|
| OC-9 | RAW 를 zip 으로 묶어야 하는 **이유**가 있는가? (용량 · 객체 수 · 규정 · 이관 편의) | A(미사용) vs B/C | [근거 4](../02-evidence/04-ilm-archive-options.md) | | |
| OC-10 | 아카이브된 RAW 를 **다시 조회**하는 경우가 있는가? 빈도·방식은? | zip 사용 시 조회 방법 | [근거 4 §5](../02-evidence/04-ilm-archive-options.md) | | |
| OC-11 | zip 변환 Job 을 서비스가 맡을 수 있는가? (하이브리드 B 의 전제) | B vs C · Job 소유 | [근거 4 §4](../02-evidence/04-ilm-archive-options.md) | | |
| OC-12 | Transition 된 데이터 조회 **성능 저하**(Warm 경유) 우려는? | Transition 대상 prefix · 경과일 | [장표 1 §3](../01-architecture/01-hot-warm-icheon-dataops.md) | | |
| OC-13 | 보존 기간 · Object Lock(WORM) · 규정 요구가 있는가? | 삭제 · 정리 정책, Lock 적용 버킷 | [근거 2 C5](../02-evidence/02-iceberg-snapshot-vs-replication.md) | | |

## 3. 답변 → 결정 매핑

| 답변 조합 | 결정 | 다음 단계 |
|---|---|---|
| OC-1 = 예 | 모드 ① 조회용 실시간 복제 | M2 테스트 + M4 네트워크 · M5 HMS-Warm · M6 Polaris |
| OC-1 = 아니오, OC-2 = 백업 | 모드 ② 백업용 복제 | M2 의 백업 시점 테스트(T-B) → 테이블별 주기 확정, M4~M6 보류 |
| OC-1 = 아니오, OC-2 = 백업 아님 | 모드 ③ 복제 불필요 | ILM(M3)만 진행 |
| OC-9 = 이유 없음 | 아카이브 A (zip 미사용) | ILM Transition 규칙만 설계 |
| OC-9 = 있음, OC-11 = 가능 | 아카이브 B (하이브리드) | 변환 Job 범위 협의 (AR-2~AR-5) |
| OC-9 = 있음, OC-11 = 불가 | 아카이브 C 또는 플랫폼 제공 검토 | 소유 주체 재협의 |
