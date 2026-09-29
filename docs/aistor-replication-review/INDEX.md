# AIStor Bucket Replication 검토 — 인덱스 (v2)

## 1. 요약 (담당자 확인 → Replication → ILM → 향후 구성)

| 구분 | 내용 |
|---|---|
| 대상 | AIStor(상용 S3) Hot/Warm 2-Tier(이천) · 이천 dataops · 용인 dataops(신규) · Lake(Polaris) |
| 작성 | 최초 2026-09-29 · v2 피드백 반영 |
| 결론 0 (선행) | 담당자 우려사항(조회 케이스 · 복제 목적 · RPO · 운영 부담 · zip 필요성) 확인 후 모드 결정 |
| 결론 1 (Replication) | Warm MinIO 데이터를 HMS 로 조회하는 케이스가 없으면 **실시간 Replication 불필요** → 모드 ① 조회용 / ② 백업용 / ③ 불필요 |
| 결론 2 (Replication) | 백업 용도면 **테이블 특성별 백업 시점**(merge · 스냅샷 정리 후 복제) 테스트로 결정 |
| 결론 3 (Replication) | S3 Replication(객체 단위 비동기) ≠ Iceberg 커밋(포인터 원자 교체) → 충돌 C1~C5 |
| 결론 4 (Replication · ILM) | Scanner 가 복제 재큐잉 · Transition · 버전 정리를 함께 처리 → Scanner 지연 시 함께 지연 |
| 결론 5 (ILM) | ILM 은 Transition · Expiration 뿐 → 아카이브 **A. zip 미사용 / B. 하이브리드(서비스 zip + ILM 이관) / C. 전면 Rollover** 협의 |
| 결론 6 (아키텍처) | 이천 dataops ↔ AIStor: Private = ClusterMesh + BGP / Public = Ingress · L4 VIP |
| 결론 7 (모드 ①) | 용인 Trino + HMS-Warm(Oracle), Lake 는 Polaris federation, Warm 은 검증 후 register_table |
| 결론 8 (모드 ①) | 용인 → Warm 접근은 Public(VIP/Ingress) 경로 우선 |
| 전제(가정) | Replication 방향 Hot → Warm 단방향 · Hot/Warm 버킷명 동일 유지 권고 |

## 1-1. 결론 개념도

| 결론 | 개념도 | draw.io | Gliffy |
|---|---|---|---|
| 결론 1·2 — 복제 모드 판단 · 백업 시점 | ![03](./diagrams/03-replication-mode-decision.svg) | [03 .drawio](./diagrams/03-replication-mode-decision.drawio) | [03 .gliffy](./diagrams/03-replication-mode-decision.gliffy) |
| 결론 3 — 커밋 단위 불일치 | ![04](./diagrams/04-commit-unit-mismatch.svg) | [04 .drawio](./diagrams/04-commit-unit-mismatch.drawio) | [04 .gliffy](./diagrams/04-commit-unit-mismatch.gliffy) |
| 결론 4 — Scanner 지연 영향 | ![06](./diagrams/06-scanner-impact.svg) | [06 .drawio](./diagrams/06-scanner-impact.drawio) | [06 .gliffy](./diagrams/06-scanner-impact.gliffy) |
| 결론 5 — 아카이브 A/B/C | ![07](./diagrams/07-ilm-archive-options.svg) | [07 .drawio](./diagrams/07-ilm-archive-options.drawio) | [07 .gliffy](./diagrams/07-ilm-archive-options.gliffy) |
| 결론 6 — 이천 연결 경로 | ![01](./diagrams/01-icheon-hot-warm-dataops.svg) | [01 .drawio](./diagrams/01-icheon-hot-warm-dataops.drawio) | [01 .gliffy](./diagrams/01-icheon-hot-warm-dataops.gliffy) |
| 결론 7 — 검증 후 등록 (모드 ①) | ![10](./diagrams/10-verify-and-register.svg) | [10 .drawio](./diagrams/10-verify-and-register.drawio) | [10 .gliffy](./diagrams/10-verify-and-register.gliffy) |

## 2. 문서 목록 · 핵심 내용

| 순서 | 카테고리 | 문서 | 핵심 내용 | 조건 | 그림 |
|---|---|---|---|---|---|
| 0 | 개요 | [README](./README.md) | 한 장 요약 · 트리 · 그림 목록 · 보안 PDF · 전제/용어 | — | — |
| 1 | 향후 (선행) | [03-future/00-owner-concerns](./03-future/00-owner-concerns.md) | 담당자 우려 확인 OC-1~OC-13, 답변 → 모드·아카이브 결정 매핑 | 항상 | 03 |
| 2 | 근거 · Replication | [02-evidence/01-replication-necessity-backup](./02-evidence/01-replication-necessity-backup.md) | 모드 ①②③ 판단, 테이블 유형별 백업 시점 가설, 테스트 T-B1~T-B7 | 항상 | 03 |
| 3 | 근거 · Replication | [02-evidence/02-iceberg-snapshot-vs-replication](./02-evidence/02-iceberg-snapshot-vs-replication.md) | 충돌 C1~C5, 절대경로, 복제 → 검증 → 등록, 확인 E2-1~E2-7 | 모드 ①② | 04, 05 |
| 4 | 근거 · Replication/ILM | [02-evidence/03-scanner-impact](./02-evidence/03-scanner-impact.md) | Scanner 작업·주기, 3회 실패 후 재큐잉, 영향 매트릭스, 대응 S-A~S-G, 확인 E3-1~E3-6 | 항상 | 06 |
| 5 | 근거 · ILM | [02-evidence/04-ilm-archive-options](./02-evidence/04-ilm-archive-options.md) | ILM 한계 근거, 아카이브 A/B/C 비교, 하이브리드 상세, 협의 안건 AR-1~AR-5, 확인 E4-1~E4-6 | 항상 | 07 |
| 6 | 근거 · 공통 | [02-evidence/05-internal-pdf-evidence-map](./02-evidence/05-internal-pdf-evidence-map.md) | 보안 PDF 6종 확인 매핑 R-01~R-24 | 항상 | — |
| 7 | 근거 · 공통 | [02-evidence/06-official-reference-links](./02-evidence/06-official-reference-links.md) | 공개 공식 문서 링크 + 원문 인용 M1~M13 · A · I · P · T · C | 항상 | — |
| 8 | 아키텍처 | [01-architecture/01-hot-warm-icheon-dataops](./01-architecture/01-hot-warm-icheon-dataops.md) | 접근 경로 매트릭스, Replication(사본) → ILM(이동) 순 비교, 확인 A-1~A-6 | 항상 | 01 |
| 9 | 아키텍처 | [01-architecture/02-warm-standalone-yongin](./01-architecture/02-warm-standalone-yongin.md) | 용인 Warm 단독 조회 구성, 흐름 ①~⑥, 설정 초안, 확인 B-1~B-5 | 모드 ① | 02 |
| 10 | 향후 | [03-future/01-yongin-network-checklist](./03-future/01-yongin-network-checklist.md) | 경로 A/B, 체크포인트 ①~⑨, 포트, Runbook, 결정 N-1~N-4 | 모드 ① / 복구 접근 | 08 |
| 11 | 향후 | [03-future/02-hms-oracle-split-todo](./03-future/02-hms-oracle-split-todo.md) | HMS-Hot/Warm 목표 구성, To-do H-01~H-54 | 모드 ① | 09, 10 |
| 12 | 향후 | [03-future/03-open-items-polaris-hot-warm-schema](./03-future/03-open-items-polaris-hot-warm-schema.md) | Polaris 조회 흐름·확인 P-01~P-08, 스키마 S-1 · S-01~S-07 | 모드 ① | 09 |
| 13 | 도구 | [tools/gen_diagrams.py](./tools/gen_diagrams.py) | 그림 11종 → .gliffy / .drawio / .svg 재생성 | — | 전체 |

## 2-1. 그림 목록 (diagrams/)

| No | 파일 | 내용 | 분류 |
|---|---|---|---|
| 01 | [01-icheon-hot-warm-dataops](./diagrams/01-icheon-hot-warm-dataops.svg) | 이천 Hot/Warm ↔ dataops 연결 (Private/Public) | 아키텍처 |
| 02 | [02-warm-standalone-yongin](./diagrams/02-warm-standalone-yongin.svg) | 용인 Warm 단독 조회 (모드 ① 전제 배너) | 아키텍처 |
| 03 | [03-replication-mode-decision](./diagrams/03-replication-mode-decision.svg) | 복제 모드 판단 트리 + 백업 시점 테스트 흐름 | Replication |
| 04 | [04-commit-unit-mismatch](./diagrams/04-commit-unit-mismatch.svg) | 스냅샷 묶음 vs 객체 단위 복제, C1~C5 | Replication |
| 05 | [05-iceberg-vs-replication-timeline](./diagrams/05-iceberg-vs-replication-timeline.svg) | 커밋·복제 시간 순 충돌 타임라인 | Replication |
| 06 | [06-scanner-impact](./diagrams/06-scanner-impact.svg) | Scanner 동작 · 담당 작업 · 지연 영향 · 악순환 | Replication · ILM |
| 07 | [07-ilm-archive-options](./diagrams/07-ilm-archive-options.svg) | 아카이브 A/B/C 비교 · 협의 기준 | ILM |
| 08 | [08-yongin-network-checkpoints](./diagrams/08-yongin-network-checkpoints.svg) | 용인 → Warm 네트워크 체크포인트 ①~⑨ | 향후 |
| 09 | [09-hot-warm-catalog-split](./diagrams/09-hot-warm-catalog-split.svg) | HMS-Hot/Warm · Polaris federation (모드 ① 전제) | 향후 |
| 10 | [10-verify-and-register](./diagrams/10-verify-and-register.svg) | 검증 후 등록 Job 흐름 | 향후 |
| 11 | [11-todo-milestones](./diagrams/11-todo-milestones.svg) | 마일스톤 M0~M7 · 게이트 G0~G2 | 진행 관리 |

## 3. 해야 할 일 · 진행 사항 · 일정

| No | 마일스톤 | 분류 | 해야 할 일 | 세부 ID | 조건 | 관련 문서 | 담당 | 시작일 | 완료 예정일 | 완료일 | 상태 | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | M0 | 선행 | 담당자 우려 확인 — Replication | OC-1~OC-8 | 항상 | [03-future/00](./03-future/00-owner-concerns.md) | | | | | ☐ 미착수 | |
| 2 | M0 | 선행 | 담당자 우려 확인 — ILM/Archive | OC-9~OC-13 | 항상 | [03-future/00](./03-future/00-owner-concerns.md) | | | | | ☐ 미착수 | |
| 3 | M0 | 선행 | 복제 모드 결정 (G0 · G1) | E1-1, E1-2 | 항상 | [02-evidence/01](./02-evidence/01-replication-necessity-backup.md) | | | | | ☐ 미착수 | |
| 4 | M1 | Replication | 보안 PDF 확인 · 페이지/절 기입 | R-01~R-24 | 항상 | [02-evidence/05](./02-evidence/05-internal-pdf-evidence-map.md) | | | | | ☐ 미착수 | |
| 5 | M1 | Replication | 복제 순서/일관성 보장 여부 벤더 문의 | E2-1 | 모드 ①② | [02-evidence/02](./02-evidence/02-iceberg-snapshot-vs-replication.md) | | | | | ☐ 미착수 | |
| 6 | M1 | Replication | 복제 방향 · 대상 버킷/프리픽스 확정 | A-1 | 모드 ①② | [01-architecture/01](./01-architecture/01-hot-warm-icheon-dataops.md) | | | | | ☐ 미착수 | |
| 7 | M1 | Replication | Hot/Warm 버킷명 동일 유지 여부 | E2-5, B-1, H-03, S-03 | 모드 ①② | [02-evidence/02](./02-evidence/02-iceberg-snapshot-vs-replication.md) | | | | | ☐ 미착수 | |
| 8 | M1 | Replication | delete / delete-marker 복제 플래그 결정 | E2-2, OC-6 | 모드 ①② | [02-evidence/02](./02-evidence/02-iceberg-snapshot-vs-replication.md) | | | | | ☐ 미착수 | |
| 9 | M1 | Replication | Iceberg 버전 · format-version 확인 | E2-6, H-40 | 모드 ①② | [02-evidence/02](./02-evidence/02-iceberg-snapshot-vs-replication.md) | | | | | ☐ 미착수 | |
| 10 | M1 | Replication | 운영 Scanner 사이클 · excess versions · speed 확인 | E3-1~E3-3 | 항상 | [02-evidence/03](./02-evidence/03-scanner-impact.md) | | | | | ☐ 미착수 | |
| 11 | M2 | Replication | 테이블 유형별 백업 시점 테스트 | T-B1~T-B7 | 모드 ② | [02-evidence/01](./02-evidence/01-replication-necessity-backup.md) | | | | | ☐ 미착수 | |
| 12 | M2 | Replication | 시점 지정 복제 방식 확인 (배치 복제 · 규칙 on/off · mirror) | E1-3, T-B4, R-23 | 모드 ② | [02-evidence/01](./02-evidence/01-replication-necessity-backup.md) | | | | | ☐ 미착수 | |
| 13 | M2 | Replication | 충돌 C1~C5 재현 테스트 | E2-3, E2-4 | 모드 ①② | [02-evidence/02](./02-evidence/02-iceberg-snapshot-vs-replication.md) | | | | | ☐ 미착수 | |
| 14 | M2 | Replication | 복제 지연 · 백로그 모니터링 · resync-backlog 절차 | E2-7, E3-4, S-B | 모드 ①② | [02-evidence/03](./02-evidence/03-scanner-impact.md) | | | | | ☐ 미착수 | |
| 15 | M2 | Replication | Hot HEAD 재큐잉 PoC | E3-5, S-C | 모드 ① | [02-evidence/03](./02-evidence/03-scanner-impact.md) | | | | | ☐ 미착수 | |
| 16 | M3 | ILM | RAW 현황 파악 (객체 수 · 크기 · 압축 설정) | E4-2, E4-3 | 항상 | [02-evidence/04](./02-evidence/04-ilm-archive-options.md) | | | | | ☐ 미착수 | |
| 17 | M3 | ILM | 아카이브 방식 협의 A / B / C (G2) | AR-1, E4-6 | 항상 | [02-evidence/04](./02-evidence/04-ilm-archive-options.md) | | | | | ☐ 미착수 | Rollover Job 확정 아님 |
| 18 | M3 | ILM | (B·C) 변환 정책 시점 · Job 소유 | AR-2, AR-3 | 아카이브 B·C | [02-evidence/04](./02-evidence/04-ilm-archive-options.md) | | | | | ☐ 미착수 | |
| 19 | M3 | ILM | 원본 보존 · 아카이브 조회 방식 · S3 Zip 확장 | AR-4, AR-5, E4-4, E4-5 | 아카이브 B·C | [02-evidence/04](./02-evidence/04-ilm-archive-options.md) | | | | | ☐ 미착수 | |
| 20 | M3 | ILM | ILM Transition 규칙 설계 (prefix · 경과일 · metadata 제외) | E4-1 | 항상 | [02-evidence/04](./02-evidence/04-ilm-archive-options.md) | | | | | ☐ 미착수 | |
| 21 | M4 | 네트워크 | 경로 · 진입점 · 소스 IP · 포트 결정 | N-1~N-4 | 모드 ① | [03-future/01](./03-future/01-yongin-network-checklist.md) | | | | | ☐ 미착수 | |
| 22 | M4 | 네트워크 | SNAT 확정 · 용인/이천 방화벽 신청 | ①, ②, ④ | 모드 ① | [03-future/01](./03-future/01-yongin-network-checklist.md) | | | | | ☐ 미착수 | |
| 23 | M4 | 네트워크 | 회선 · 대역폭 · VIP/Ingress 확인 | ③, ⑤, A-4 | 모드 ① | [03-future/01](./03-future/01-yongin-network-checklist.md) | | | | | ☐ 미착수 | |
| 24 | M4 | 네트워크 | TLS · 읽기 전용 키 · DNS | ⑥, ⑦, A-5, B-2 | 모드 ① | [03-future/01](./03-future/01-yongin-network-checklist.md) | | | | | ☐ 미착수 | |
| 25 | M4 | 네트워크 | (B 경로) ClusterMesh · BGP 확인, 연결 Runbook | ⑧, ⑨, A-6 | 모드 ① | [03-future/01](./03-future/01-yongin-network-checklist.md) | | | | | ☐ 미착수 | |
| 26 | M5 | HMS | HMS 버전 · Oracle 배치 · 명명 규칙 | H-01, H-02, H-05 | 모드 ① | [03-future/02](./03-future/02-hms-oracle-split-todo.md) | | | | | ☐ 미착수 | |
| 27 | M5 | HMS | Oracle 용인용 스키마 · 권한 · 네트워크 · 백업 | H-10~H-14 | 모드 ① | [03-future/02](./03-future/02-hms-oracle-split-todo.md) | | | | | ☐ 미착수 | |
| 28 | M5 | HMS | HMS-Warm 이미지 · 초기화 · 배포 · 모니터링 | H-20~H-26 | 모드 ① | [03-future/02](./03-future/02-hms-oracle-split-todo.md) | | | | | ☐ 미착수 | |
| 29 | M5 | HMS | HMS-Hot 현행 파악 · 유지보수 정책 조정 | H-40~H-43 | 모드 ① | [03-future/02](./03-future/02-hms-oracle-split-todo.md) | | | | | ☐ 미착수 | |
| 30 | M5 | HMS | 검증 · register_table 자동화 | H-30~H-35 | 모드 ① | [03-future/02](./03-future/02-hms-oracle-split-todo.md) | | | | | ☐ 미착수 | |
| 31 | M5 | HMS | 용인 Trino 구성 · 조회 · 쓰기 차단 검증 | B-3, H-50~H-54 | 모드 ① | [03-future/02](./03-future/02-hms-oracle-split-todo.md) | | | | | ☐ 미착수 | |
| 32 | M6 | Polaris | 버전 · 빌드 · feature flag · 인증 | P-01~P-03, B-4 | 모드 ① | [03-future/03](./03-future/03-open-items-polaris-hot-warm-schema.md) | | | | | ☐ 미착수 | |
| 33 | M6 | Polaris | lake_hot / lake_warm catalog · RBAC · 스토리지 | P-04~P-06 | 모드 ① | [03-future/03](./03-future/03-open-items-polaris-hot-warm-schema.md) | | | | | ☐ 미착수 | |
| 34 | M6 | Polaris | Lake 엔진 경로 · 비 Iceberg 테이블 · union view | P-07, P-08, B-5, S-04~S-06 | 모드 ① | [03-future/03](./03-future/03-open-items-polaris-hot-warm-schema.md) | | | | | ☐ 미착수 | |
| 35 | M7 | 운영 | 복제 · ILM 정책 적용 · 사용자 가이드 | S-07 | 항상 | [03-future/03](./03-future/03-open-items-polaris-hot-warm-schema.md) | | | | | ☐ 미착수 | |

## 4. 상태 표기

| 표기 | 의미 |
|---|---|
| ☐ 미착수 | 시작 전 |
| ◐ 진행중 | 작업 중 |
| ☑ 완료 | 완료 · 검증됨 |
| ⛔ 보류 | 선행 조건 · 게이트 결과 대기 (모드 ②③ 이면 모드 ① 항목은 보류) |

## 5. 마일스톤

| 단계 | 포함 No | 선행 | 조건 | 시작일 | 완료 예정일 | 상태 |
|---|---|---|---|---|---|---|
| M0 담당자 우려 · 모드 결정 | 1~3 | — | 항상 | | | ☐ |
| M1 Replication 근거 · 설계 | 4~10 | M0 | 항상 | | | ☐ |
| M2 Replication 테스트 (백업 시점 · 충돌 · 지연) | 11~15 | M1 | 모드 ①② | | | ☐ |
| M3 ILM / Archive 협의 · PoC | 16~20 | M2 (모드 ③ 이면 M0) | 항상 | | | ☐ |
| M4 네트워크 개통 | 21~25 | M2 | 모드 ① | | | ☐ |
| M5 HMS-Warm · 등록 자동화 | 26~31 | M4 | 모드 ① | | | ☐ |
| M6 Polaris federation PoC | 32~34 | M5 | 모드 ① | | | ☐ |
| M7 운영 이관 | 35 | M3 + (모드 ① 이면 M4~M6) | 항상 | | | ☐ |

## 5-1. 마일스톤 의존 관계도 · 게이트

| 개념도 | draw.io | Gliffy |
|---|---|---|
| ![11](./diagrams/11-todo-milestones.svg) | [11 .drawio](./diagrams/11-todo-milestones.drawio) | [11 .gliffy](./diagrams/11-todo-milestones.gliffy) |

| 게이트 | 확정할 결정 | 관련 No | 결과에 따른 분기 |
|---|---|---|---|
| G0 | Warm 을 HMS 로 조회하는 케이스 유무 | 1, 3 | 예 → 모드 ① (M4~M6 진행) / 아니오 → G1 |
| G1 | 복제 목적(백업 여부) · 버킷명 동일 여부 | 3, 7 | 백업 → 모드 ② (M2 백업 시점 테스트) / 아님 → 모드 ③ (M3 만) |
| G2 | 아카이브 방식 A / B / C | 17 | A → Transition 규칙만 / B → 변환 Job(서비스) + Transition / C → 전면 Rollover Job |

## 6. v2 피드백 반영 이력

| 피드백 | 반영 내용 | 위치 |
|---|---|---|
| RAW → zip rollover Job 은 협의 필요 | "확정 아님 · 협의 안건"으로 변경, AR-1~AR-5 | 02-evidence/04 · No 17 |
| zip 자체를 안 써도 될 수 있음 | 아카이브 A (zip 미사용) 선택지 추가 | 02-evidence/04 · 그림 07 |
| 서비스 zip 변환 + ILM 으로 Warm 이관 하이브리드 | 아카이브 B 상세 · 역할 분리 | 02-evidence/04 §4 · 그림 07 |
| HMS 로 Warm 조회 케이스가 없으면 실시간 복제 불필요 | 모드 ①②③ 판단 · 조건 열 · 모드 ① 전제 배너 | 02-evidence/01 · 그림 03·02·09 · 01-architecture/02 · 03-future/01~03 |
| 백업 용도면 테이블 특성별 백업 시점 테스트 | T-B1~T-B7 · 테이블 유형별 가설 | 02-evidence/01 §3 · 그림 03 · No 11~12 |
| 담당자 우려 확인 필요 | 확인표 OC-1~OC-13 · M0 · G0 | 03-future/00 · No 1~3 |
| Replication 우선 → ILM 다음 | 근거 문서 번호 · INDEX 결론 · To-do · 마일스톤 순서 재정렬 | 02-evidence/01~04 · §3 · 그림 11 |
| 문서 · 그림 통합 | 그림 `diagrams/` 단일 폴더 01~11, 중복 개념도 제거 | diagrams/ · README §2 |
