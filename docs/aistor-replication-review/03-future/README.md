# 3. 향후 구성 대응 (v3 — 용인 Warm 전용 + 이천 Replication · ILM)

| 순서 | 문서 | 내용 | 대상 케이스 | 그림 |
|---|---|---|---|---|
| 0 | [00-owner-concerns](./00-owner-concerns.md) | **담당자 우려사항 확인** OC-1~OC-16 → 복제 · ILM · Warm 공유 설계 우선순위 | 공통 (가장 먼저) | 03-warm-coexistence |
| 1 | [01-yongin-network-checklist](./01-yongin-network-checklist.md) | 용인 → 이천 Warm **read/write** 경로 A/B, 체크포인트 ①~⑨, 포트, 검증 Runbook | 용인 (필수) | 08-yongin-network-checkpoints |
| 2 | [02-hms-oracle-split-todo](./02-hms-oracle-split-todo.md) | HMS-Hot(이천) / HMS-Warm(용인 원본) / 복구용 HMS To-do H-01~H-54 | 용인 · 이천 복구 | 09-hot-warm-catalog-split, 10-verify-and-register |
| 3 | [03-open-items-polaris-hot-warm-schema](./03-open-items-polaris-hot-warm-schema.md) | Polaris `lake_hot` / `lake_warm` 확인 P-01~P-08, 이천·용인 스키마 S-01~S-07 | 용인 · Lake | 09-hot-warm-catalog-split |

## 전체 진행 체크 요약

| 순서 | 영역 | 항목 ID | 선행 |
|---|---|---|---|
| 0 | 담당자 우려 확인 · Warm 버킷 역할 분리 | OC-1 ~ OC-16, E1-5 | — |
| 1 | 이천 Replication · ILM 근거 · 테스트 | E1 · E2(C1~C5) · E3(Scanner) · T-B1~T-B9 · R-01~R-26 | OC |
| 2 | 이천 ILM / Archive 협의 | E4 · AR-1 ~ AR-5 | Replication 설계 |
| 3 | 용인 네트워크 | ① ~ ⑨, N-1 ~ N-4 | Warm 버킷 역할 분리 |
| 4 | 용인 HMS-Warm · 이천 복구 절차 | H-01 ~ H-54 | 네트워크 |
| 5 | Polaris / 스키마 | P-01 ~ P-08, S-01 ~ S-07 | HMS |
