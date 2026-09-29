# 3. 향후 구성 대응

| 순서 | 문서 | 내용 | 조건 | 그림 |
|---|---|---|---|---|
| 0 | [00-owner-concerns](./00-owner-concerns.md) | **담당자 우려사항 확인** OC-1~OC-13 → Replication 모드 · 아카이브 방식 결정 | 항상 (가장 먼저) | 03-replication-mode-decision |
| 1 | [01-yongin-network-checklist](./01-yongin-network-checklist.md) | 용인 → 이천 Warm 접근: 경로 A/B, 체크포인트 ①~⑨, 포트, 검증 Runbook | 모드 ① 또는 용인 복구 접근 필요 시 | 08-yongin-network-checkpoints |
| 2 | [02-hms-oracle-split-todo](./02-hms-oracle-split-todo.md) | HMS-Hot / HMS-Warm(Oracle) 구성 To-do H-01~H-54 | 모드 ① | 09-hot-warm-catalog-split, 10-verify-and-register |
| 3 | [03-open-items-polaris-hot-warm-schema](./03-open-items-polaris-hot-warm-schema.md) | Polaris federation 확인 P-01~P-08, Hot/Warm 스키마 S-1 | 모드 ① | 09-hot-warm-catalog-split |

## 전체 진행 체크 요약

| 순서 | 영역 | 항목 ID | 선행 |
|---|---|---|---|
| 0 | 담당자 우려 확인 | OC-1 ~ OC-13 | — |
| 1 | Replication 근거 · 테스트 | E1 · E2(=C1~C5) · E3(Scanner) · T-B1~T-B7 · R-01~R-24 | OC |
| 2 | ILM / Archive 협의 | E4 · AR-1 ~ AR-5 | Replication 모드 결정 |
| 3 | 네트워크 (조건부) | ① ~ ⑨, N-1 ~ N-4 | 모드 ① |
| 4 | HMS (조건부) | H-01 ~ H-54 | 네트워크 |
| 5 | Polaris / 스키마 (조건부) | P-01 ~ P-08, S-01 ~ S-07 | HMS |
