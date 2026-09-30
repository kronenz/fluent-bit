# 2. 근거 정리 — Replication 우선 → ILM 다음

| 순서 | 문서 | 분류 | 내용 | 그림 |
|---|---|---|---|---|
| 1 | [01-warm-coexistence-replication-ilm](./01-warm-coexistence-replication-ilm.md) | Replication · ILM · 공존 | **두 케이스 공존 검토** — 용인 Warm 전용 + 이천 Replication(백업)·ILM, Warm 버킷 역할 분리, P-1~P-10 · Y-1~Y-7, 백업 시점 테스트 T-B1~T-B9 | 03-warm-coexistence |
| 2 | [02-iceberg-snapshot-vs-replication](./02-iceberg-snapshot-vs-replication.md) | Replication | Iceberg 스냅샷 ↔ Replication 충돌 C1~C5, 버킷 경로, "복제 → 검증 → 등록" | 04-commit-unit-mismatch, 05-iceberg-vs-replication-timeline |
| 3 | [03-scanner-impact](./03-scanner-impact.md) | Replication · ILM 공통 | Scanner 지연이 복제 재큐잉 · Transition · 버전 정리에 주는 영향, 대응 S-A~S-G | 06-scanner-impact |
| 4 | [04-ilm-archive-options](./04-ilm-archive-options.md) | ILM | ILM 한계 근거, 아카이브 선택지 A(zip 미사용) · B(하이브리드) · C(전면 Rollover · 협의 필요), 협의 안건 AR-1~AR-5 | 07-ilm-archive-options |
| 5 | [05-internal-pdf-evidence-map](./05-internal-pdf-evidence-map.md) | 공통 | 사내 보안 PDF 6종 — 주장별 확인 체크리스트 R-01~R-26 | — |
| 6 | [06-official-reference-links](./06-official-reference-links.md) | 공통 | 공개 공식 문서 링크 + 영어 원문 인용 (M·A·I·P·T·C ID) | — |

## 근거 등급 규칙

| 등급 | 의미 | 장표 표기 |
|---|---|---|
| ✅ 직접 | 공식 문서 원문이 주장을 직접 기술 | 인용 + 링크 |
| ◐ 부분 | 원문이 일부만 기술하거나 특정 조건(예: resync)에 한정 | "~ 한정" 명시 |
| ∅ 부재 | 공식 문서에 해당 보장 문구가 **없음** — "보장하지 않는다"가 아니라 "보장 문구가 없다"로 표현 | 벤더 확인 필요 표시 |
| 🔒 사내 | 사내 PDF 로 상용 버전 기준 교차 확인 | 문서명 + 페이지만 기재 |
| 🔍 확인 | 버전·환경 의존 또는 원문 재확인 필요 | 테스트 · 벤더 확인 |
