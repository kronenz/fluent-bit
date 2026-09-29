# 3. 향후 구성 대응

| 문서 | 요청 | 내용 | 다이어그램 |
|---|---|---|---|
| [01-yongin-network-checklist](./01-yongin-network-checklist.md) | 5 | 용인 → 이천 Warm 접근: 경로 A(VIP/Ingress) vs B(ClusterMesh), 체크포인트 ①~⑨, 포트 매트릭스, 검증 Runbook | `diagrams/05-yongin-network-checkpoints.*` |
| [02-hms-oracle-split-todo](./02-hms-oracle-split-todo.md) | 6 | HMS-Hot(이천) / HMS-Warm(용인용) Oracle 각자 구성 To-do (H-01 ~ H-54) | `diagrams/06-hot-warm-catalog-split.*` |
| [03-open-items-polaris-hot-warm-schema](./03-open-items-polaris-hot-warm-schema.md) | 7 | Polaris federation 조회 방식 확인 사항(P-01 ~ P-08), Hot/Warm 스키마 구성안(S-1 권고) 및 결정 사항 | `diagrams/06-hot-warm-catalog-split.*` |

## 전체 진행 체크 요약

| 영역 | 항목 ID | 선행 |
|---|---|---|
| 사내 PDF 근거 확인 | R-01 ~ R-20 ([02-evidence/03](../02-evidence/03-internal-pdf-evidence-map.md)) | — |
| 아키텍처 확인 | A-1 ~ A-6, B-1 ~ B-5 ([01-architecture](../01-architecture/README.md)) | R |
| 네트워크 | ① ~ ⑨, N-1 ~ N-4 | A |
| HMS | H-01 ~ H-54 | 네트워크 |
| Polaris / 스키마 | P-01 ~ P-08, S-01 ~ S-07 | HMS |
