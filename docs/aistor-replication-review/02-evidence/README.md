# 2. 근거 정리

| 문서 | 요청 | 내용 |
|---|---|---|
| [01-iceberg-snapshot-vs-replication](./01-iceberg-snapshot-vs-replication.md) | 3 | Iceberg 스냅샷 ↔ S3 Replication 충돌 C1~C5, 버킷 경로 문제, "복제 → 검증 → 등록" 권고 |
| [02-raw-archive-ilm-limitation](./02-raw-archive-ilm-limitation.md) | 4 | ILM 에 압축·병합·zip·rollover 액션이 없는 근거, 서비스 구현 범위 |
| [03-internal-pdf-evidence-map](./03-internal-pdf-evidence-map.md) | 공통 | 사내 보안 PDF 6종 — 주장별로 "어느 문서에서 무엇을 찾을지" 체크리스트 (R-01~R-20) |
| [04-official-reference-links](./04-official-reference-links.md) | 공통 | 공개 공식 문서 링크 + 영어 원문 인용 (M·A·I·P·T·C ID) |

## 근거 등급 규칙

| 등급 | 의미 | 장표 표기 |
|---|---|---|
| ✅ 직접 | 공식 문서 원문이 주장을 직접 기술 | 인용 + 링크 |
| ◐ 부분 | 원문이 일부만 기술하거나 특정 조건(예: resync)에 한정 | "~ 한정" 명시 |
| ∅ 부재 | 공식 문서에 해당 보장 문구가 **없음** — "보장하지 않는다"가 아니라 "보장 문구가 없다"로 표현 | 벤더 확인 필요 표시 |
| 🔒 사내 | 사내 PDF 로 상용 버전 기준 교차 확인 | 문서명 + 페이지만 기재 |

> 원칙: 장표에는 **공개 근거(링크)** 를 1차로 싣고, 사내 PDF 는 "상용 AIStor 버전에서도 동일함"을 확인한 **페이지 번호만** 덧붙입니다.
