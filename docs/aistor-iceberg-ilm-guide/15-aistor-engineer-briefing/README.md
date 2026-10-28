# 15. AIStor 엔지니어 방문 사전 학습 — Scanner · 태그 기반 ILM · Iceberg 충돌

> 목적: [14장 05 질의서](../14-ilm-config-guide/05-aistor-engineer-qna.md)의 각 주제를 **질의 전에 스스로 설명할 수 있을 만큼** 풀어 쓴 해설과 그림.
> 근거: 13장 시험(2026-10-25 ~ 28, corp 테스트베드 MinIO RELEASE.2024-10-13) · Iceberg 1.9.0 · MinIO/Iceberg 공개 문서
> 표기: ✅ 실측 · 📘 공개 문서 · 소스 기준 일반 동작 · 💡 제안 · ❓ 엔지니어 확인 · 🔍 운영 버전 재확인

## 읽는 순서

| # | 문서 | 이해하게 되는 것 | 그림 | 분량 |
|---|---|---|---|---|
| 1 | [01-scanner-internals.md](./01-scanner-internals.md) | Scanner 가 무엇을 · 어떻게 순회하나, ILM 이 **언제** 실행되나 (00:00 올림 · PUT 즉시 경로), 속도 설정의 의미 | 01 · 02 | 20분 |
| 2 | [02-scanner-load-reduction.md](./02-scanner-load-reduction.md) | 부하를 만드는 변수와 줄이는 손잡이 3갈래 (대상 축소 · Scanner 밖으로 · 시간대) · 자정 쏠림 | 03 · 08 | 20분 |
| 3 | [03-tag-based-tiering.md](./03-tag-based-tiering.md) | 💡 태그 붙여 다시 쓰면 PUT 순간 Warm — 원리 · 설정 · 실측 T-1 · 한계 · 도입 순서 | 04 | 20분 |
| 4 | [04-iceberg-soft-delete.md](./04-iceberg-soft-delete.md) | ILM 만료가 Iceberg 를 깨는 이유 · soft delete 태그로 해결 · 실측 E-3/T-2 · 세 방식 비교 | 05 | 20분 |
| 5 | [05-iceberg-replication.md](./05-iceberg-replication.md) | 커밋 vs 객체 복제 불일치 · 해결 R-A(검증 후 등록) · R-B(`rewrite_table_path`) · ILM/태그와의 상호작용 | 06 · 07 | 20분 |
| 6 | [06-question-guide.md](./06-question-guide.md) | 질의 33개 각각의 배경 · 답에 따른 결정 · 현장 메모 틀 | 09 | 30분 |

## 그림 (draw.io)

| 그림 | draw.io | 미리보기 |
|---|---|---|
| 01 Scanner 순회와 한 객체에서 하는 일 | [01-scanner-cycle.drawio](./diagrams/01-scanner-cycle.drawio) | [svg](./diagrams/01-scanner-cycle.svg) |
| 02 ILM 실행 시각 (mtime + Days → 00:00 → 방문, PUT 즉시) | [02-ilm-timing.drawio](./diagrams/02-ilm-timing.drawio) | [svg](./diagrams/02-ilm-timing.svg) |
| 03 Scanner 부하 모델과 손잡이 | [03-scanner-load-levers.drawio](./diagrams/03-scanner-load-levers.drawio) | [svg](./diagrams/03-scanner-load-levers.svg) |
| 04 태그 기반 즉시 전이 흐름 | [04-tag-tiering-flow.drawio](./diagrams/04-tag-tiering-flow.drawio) | [svg](./diagrams/04-tag-tiering-flow.svg) |
| 05 Soft delete vs 나이 기반 만료 | [05-soft-delete-flow.drawio](./diagrams/05-soft-delete-flow.drawio) | [svg](./diagrams/05-soft-delete-flow.svg) |
| 06 복제 불일치 (커밋 vs 객체) | [06-replication-inconsistency.drawio](./diagrams/06-replication-inconsistency.drawio) | [svg](./diagrams/06-replication-inconsistency.svg) |
| 07 복제 해결안 R-A · R-B | [07-replication-solutions.drawio](./diagrams/07-replication-solutions.drawio) | [svg](./diagrams/07-replication-solutions.svg) |
| 08 하루 운영 시간표 (Scanner 속도 · tiering 작업) | [08-speed-window.drawio](./diagrams/08-speed-window.drawio) | [svg](./diagrams/08-speed-window.svg) |
| 09 질의 지도 (결정 ↔ 질문) | [09-question-map.drawio](./diagrams/09-question-map.drawio) | [svg](./diagrams/09-question-map.svg) |

`.gliffy` (Confluence Gliffy) 도 같은 이름으로 있다. 그림 수정: `python3 tools/gen_diagrams.py` (15장 폴더에서, `aistor-replication-review/tools/diagram_lib.py` 사용).

## 5분 요약

1. **ILM 은 Scanner 가 방문할 때 실행된다.** 실행 시각 = mtime + Days → 다음 00:00 UTC → 첫 방문. 1d 규칙의 첫 전이가 10-27 00:15 UTC 에 일어난 이유 (✅).
2. Scanner 속도를 올리면 ILM 만이 아니라 사용량 · healing · 복제 점검까지 같이 빨라진다 → 대규모에서 상시 가속은 비싸다 (✅ `fastest` 유휴 CPU 6배).
3. 부하를 줄이는 순서: **셀 대상 줄이기(compaction · 버전 정리) → ILM 을 Scanner 밖으로 → 시간대별 속도**.
4. **PUT 순간 이미 만기인 객체는 Scanner 없이 처리된다.** 태그 + 0d 규칙 + 태그 붙여 다시 쓰는 compaction = Scanner 를 기다리지 않는 전이 (✅ T-1).
5. ILM 나이 기반 만료는 Iceberg 를 깬다 (✅ E-3). **Iceberg 가 지울 파일에 태그만 달고, ILM 이 그 태그만 만료** 하면 안전하다 (✅ T-2).
6. 객체 복제는 커밋 단위를 모른다 → replica 는 **검증 후 등록**하거나 Iceberg `rewrite_table_path` 로 스냅샷 단위 복사.
7. 엔지니어에게 꼭 물을 것: Q-S1(Scanner 일 분리) · Q-S2(우리 규모 사이클 시간) · Q-I1(태그 즉시 전이 보장) · Q-I8(전이 버전 만료 시 복구 불가) · Q-R1(복제 대기 객체와 전이 순서).
