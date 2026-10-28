# 14. Hot→Warm ILM × Iceberg 구성 가이드

> 13장 시험(2026-10-25 ~ 26, corp 테스트베드) 결과를 운영 구성 · 재현 · 개발자 안내로 정리한다.
> 정책: Replication 없이 **Hot 1일 → Warm**, 보존 기한이 지나면 삭제 (예: 5일 = Hot 1일 + Warm 4일), 서비스는 Hot 엔드포인트만.

## 문서

| 문서 | 독자 | 내용 |
|---|---|---|
| [01-s3-bucket-setup.md](./01-s3-bucket-setup.md) | 플랫폼 · AIStor 관리자 | 버킷 · 계정 · tier · ILM 규칙 · 기한 삭제 · Scanner · 모니터링 · 체크리스트 |
| [02-test-environment.md](./02-test-environment.md) | 시험 담당 | 폐쇄망 반입 목록 · 레지스트리/스토리지 치환 · 구성 순서 (운영 AIStor / 테스트베드) |
| [03-agent-runbook.md](./03-agent-runbook.md) | **폐쇄망 에이전트** · 시험 담당 | 시험 재실행 지시서 — 금지 사항 · 단계별 명령 · 판정 기준 · 결과서 형식 |
| [04-developer-guide.md](./04-developer-guide.md) | 서비스 개발자 | 무엇이 바뀌고 무엇이 그대로인가 · 읽기 지연 · 보존 삭제 방법 · FAQ (그림 4개) |
| [05-aistor-engineer-qna.md](./05-aistor-engineer-qna.md) | AIStor 엔지니어 · 플랫폼 | Scanner 최적화 제안(태그 기반 즉시 전이 실측) · Iceberg × ILM/Replication 충돌 해결 · 질의 30여 항목 |
| [diagrams/](./diagrams/) | — | `.drawio` (편집) · `.svg` (미리보기) · `.gliffy` (Confluence Gliffy) — `tools/gen_diagrams.py` 로 생성 |

## 시험 결과 요약 (근거)

| 구분 | 결과 | 결과서 |
|---|---|---|
| ① 기능 | 0d 스모크 J-1 ~ J-8 ✅ · 1d 연속 J-1 ~ J-8 ✅ (첫 전이 10-27 00:15 UTC) | [smoke](../13-ilm-hot-only-test/results/REPORT-smoke-20261025.md) |
| ② 성능 · 부하 | 기존 4,000 객체 전이 914초(기본) / 25초(fastest) · 전이 중 쓰기 영향 없음 · 읽기 +22~40% · 오류 0 | [perf-impact](../13-ilm-hot-only-test/results/REPORT-perf-impact-20261026.md) |
| ③ 영향도 | HMS · Iceberg 스키마 · 파티션 · 속성 · 위치 · 파일 경로 전후 동일 · 전이 파일 위 스키마 변경 정상 | 같음 |
| 기한 삭제 | mtime 소급으로 즉시 검증: 객체 만료 · Warm 삭제 ✅ · ILM 만료를 Iceberg 에 걸면 테이블 깨짐 ❌ · Iceberg 보존 작업 + 비현행 만료 ✅ (10-28 00:00 UTC Warm 최종 삭제 확인) | [expiry](../13-ilm-hot-only-test/results/REPORT-expiry-20261026.md) |

## 핵심 결정

1. 규칙은 `data/` 에만: Transition 1d · Noncurrent 1d · delete marker 정리. `metadata/` · Warm 버킷에는 규칙 없음.
2. **기한 삭제는 Iceberg 보존 작업**(DELETE + expire_snapshots)이 하고, ILM 은 남은 비현행 버전으로 Warm 공간만 회수한다. Iceberg `data/` 에 current Expiration 금지.
3. 규칙 적용은 `00-apply-ilm.sh MERGE=1` — `mc ilm rule import` 는 버킷 규칙 전체를 교체한다.
4. ILM 시각은 `mtime + Days` → 다음 00:00 UTC 올림 + Scanner 방문. 대량 기존 버킷은 Scanner 를 한시적으로만 올린다.
