# AIStor Hot→Warm ILM × Iceberg — 폐쇄망 적용 키트 · 엔지니어 방문 자료

> 폐쇄망 안에서 **Hot 1일 → Warm** ILM 정책을 Iceberg 테이블에 적용 · 시험하고 결과서를 내기 위한 묶음 (2026-10-26)
> 원본: [`docs/aistor-iceberg-ilm-guide/`](../aistor-iceberg-ilm-guide/) (핵심은 13장 · 14장) — 이 폴더는 반입용 사본이다. 고칠 때는 원본을 고치고 키트를 다시 만든다 (§5).
> 압축본: [`../aistor-ilm-airgap-kit.zip`](../aistor-ilm-airgap-kit.zip)

## 1. 폐쇄망 시험 기준

| 항목 | 기준 |
|---|---|
| ILM 규칙 | `data/` **Transition 1d** → Warm tier · Noncurrent 만료 1d · 고아 delete marker 정리 · `metadata/` 규칙 없음 · current Expiration 없음 |
| 접근 | 서비스(Spark · HMS)는 **Hot 엔드포인트만**. Warm 은 Hot 의 tier 계정만 |
| 기한 삭제 | Iceberg 보존 작업(DELETE + expire_snapshots) + ILM 비현행 만료 — 예: 보존 5일 = Hot 1일 + Warm 4일 |
| 판정 | 기능 J-1~J-8 (1d 연속) · 성능 P-1~P-4 · 영향도 I-1~I-5 · 기한 삭제 E-0~E-5 |
| 소요 | 1d 연속 3~4일 (첫 전이 = 시작 + 1일 → **다음 00:00 UTC 이후**) · 성능 · 영향도 약 1시간 · 기한 삭제 5분 + 실시간 1~2일 |

## 2. 무엇이 들어 있나

```
aistor-ilm-airgap-kit/
├── README.md                          ← 지금 이 문서 (시작점)
├── aistor-replication-review/         Replication 검토 (15장 05 · 그림 생성기 diagram_lib 이 참조)
└── aistor-iceberg-ilm-guide/          가이드 전체 사본 (00~12장 배경 · 설계 · 운영 · 리스크 포함)
    ├── README.md                      가이드 목차 — 목적별 빠른 진입
    ├── 00-overview/ … 12-appendix/    배경 장 (04 ILM 설계 · 05 Iceberg on S3 · 09 운영 · 11 리스크 등)
    ├── 15-aistor-engineer-briefing/   ★ 엔지니어 방문 사전 학습 (해설 6 · draw.io 그림 9)
    │   ├── 01-scanner-internals.md      Scanner 원리 · ILM 실행 시각(00:00 올림) · PUT 즉시 경로
    │   ├── 02-scanner-load-reduction.md 부하 모델 · 줄이는 손잡이 A/B/C · 시간대 운영
    │   ├── 03-tag-based-tiering.md      태그 기반 즉시 전이 (실측 T-1)
    │   ├── 04-iceberg-soft-delete.md    Iceberg × ILM 만료 충돌 · soft delete 태그 (실측 E-3 · T-2)
    │   ├── 05-iceberg-replication.md    Iceberg × Replication 충돌 · 해결 R-A/R-B
    │   └── 06-question-guide.md         질의 33개 해설 · 현장 메모 틀
    ├── 14-ilm-config-guide/           ★ 가이드 (05 = 엔지니어 질의서)
    │   ├── 01-s3-bucket-setup.md        운영 버킷 · 계정 · tier · ILM 규칙 · 기한 삭제 · Scanner · 모니터링
    │   ├── 02-test-environment.md       폐쇄망 반입 목록 · 레지스트리/스토리지 치환 · 구성 순서
    │   ├── 03-agent-runbook.md          ★ 폐쇄망 에이전트 실행 지시서 (판정 기준 · 결과서 형식)
    │   ├── 04-developer-guide.md        서비스 개발자 안내 · FAQ
    │   ├── diagrams/                    draw.io(.drawio) · 미리보기(.svg) · Confluence Gliffy(.gliffy)
    │   └── tools/gen_diagrams.py        그림 생성기 (원본 저장소의 aistor-replication-review/tools 필요)
    └── 13-ilm-hot-only-test/          ★ 시험 정의 · 스크립트 · 기준 결과
        ├── README.md                    시험 개요 · 판정 기준 · 실행 순서 · 주의사항 · 결과 기록표
        ├── scripts/                     전부 반입 (Python 표준 라이브러리만 사용)
        │   ├── config.env.example         운영 AIStor 용 설정 틀
        │   ├── lib.sh                     IMAGE_REGISTRY · MAVEN_REPO · RWX_SC/RWO_SC 치환
        │   ├── 00-apply-ilm.sh            규칙 백업 · 병합 · 적용 전/후 위험 규칙 검사
        │   ├── 02-deploy.sh · k8s/        CronJob(Writer · Verifier · State · Maintenance) · 수집기
        │   ├── spark/                     Iceberg 적재 · 검증 · 측정 · 스키마 확인 Job
        │   ├── perf/                      성능 · 영향도 · 기한 삭제 일괄 실행
        │   ├── testbed/                   AIStor 없이 K8s 안 MinIO hot/warm + HMS
        │   └── judge.py                   J-1~J-6 자동 판정
        └── results/                     기준 환경(corp 테스트베드) 결과서 · 원시 증적 (audit 원시 로그 제외)
```

## 3. 폐쇄망에서의 순서

| # | 할 일 | 문서 |
|---|---|---|
| 1 | 이미지 · jar 를 사내 레지스트리 · Nexus 로 미러, RWX StorageClass 확인 | 14장 `02-test-environment.md` §2 |
| 2 | (운영 AIStor) 시험 전용 Hot 버킷 · Warm tier 버킷 · 계정 · tier 등록 | 14장 `01-s3-bucket-setup.md` §2~§3 |
| 3 | ns · 공유 볼륨 · Secret · toolbox · (필요 시) 시험용 HMS | 14장 `02-test-environment.md` §4 |
| 4 | 시험: 스모크(선택) → 성능 · 영향도 → 기한 삭제 → **1d 연속** | 14장 `03-agent-runbook.md` §4 |
| 5 | 결과서 `13-ilm-hot-only-test/results/REPORT-<환경>-<날짜>.md` | 14장 `03-agent-runbook.md` §7 |
| 6 | 정리 (ns · 시험 버킷 · 시험 tier · Scanner 원복) | 14장 `02-test-environment.md` §6 |

## 4. 폐쇄망 에이전트에게 줄 지시 (복사해서 사용)

```text
aistor-ilm-airgap-kit/aistor-iceberg-ilm-guide/14-ilm-config-guide/03-agent-runbook.md 를 처음부터 끝까지 따라
Hot→Warm ILM(Transition 1d) × Iceberg 시험을 이 환경에서 실행하고 결과서를 작성해.
- 모드: <A: 운영 AIStor 시험 버킷 | B: 테스트베드>
- kubeconfig / 네임스페이스: <…> / ilm-test
- 레지스트리 · Maven 미러 · StorageClass: IMAGE_REGISTRY=<…> MAVEN_REPO=<…> RWX_SC=<…> RWO_SC=<…>
- (모드 A) Hot · Warm 엔드포인트 <…> · 시험 버킷 <…> · tier 이름 <…> · Secret(ilmtest-s3 · ilmtest-admin · ilmtest-tier)은 이미 만들어 둠
- 보존 기한: EXPIRE_DAYS=5 (Hot 1일 + Warm 4일)
runbook §2 의 금지 사항(자격증명 출력 금지, 시험 버킷만, MERGE=1, Scanner 원복)을 지키고,
기준 결과(13-ilm-hot-only-test/results/REPORT-*.md)와 비교한 표를 결과서에 넣어.
1d 연속은 시작 후 다음 00:00 UTC 를 두 번 넘긴 뒤 판정하고, 그 전까지는 중간 결과서를 남겨.
정리(ns 삭제 등)는 실행 전에 나에게 물어봐.
```

## 5. 기준 결과 요약 (corp 테스트베드, MinIO RELEASE.2024-10-13 단일 노드)

| 구분 | 결과 |
|---|---|
| 기능 (0d 스모크) | J-1~J-8 ✅ — data 만 전이 · metadata 제외 · 정합성 · 전이 파일 조회 · time travel · compaction · Warm 접근 = tier 계정만 |
| 기능 (1d 연속) | J-1~J-8 ✅ — 첫 전이 10-27 00:15 UTC (00:00 올림) · 전이 배치 읽기 p50 417 → 642 ms |
| 성능 · 부하 | 기존 4,000 객체 전이 914초(Scanner 기본) / 25초(fastest) · 쓰기 영향 없음 · 읽기 +22~40% · 오류 0 |
| 영향도 | HMS · Iceberg 스키마 · 파티션 · 속성 · 위치 · 파일 경로 전후 동일 · 전이 파일 위 스키마 변경 정상 |
| 기한 삭제 | 객체 만료 · Warm 삭제 ✅ · Iceberg 에 ILM 만료를 걸면 테이블 깨짐 ❌(금지 근거) · Iceberg 보존 작업 방식 ✅ · 10-28 00:00 Warm 최종 삭제 ✅ |
| 태그 기반 (T-1 · T-2) | 태그 붙여 쓴 파일 PUT 순간 Warm 전이 ✅ · soft delete 태그 + 태그 필터 만료로 Iceberg 가 지운 파일만 만료 ✅ |
| 주의 | ILM 시각은 다음 00:00 UTC 로 올림 · `mc ilm rule import` 는 전체 교체(MERGE=1) · 전이된 버전이 만료되면 Warm 원본 즉시 삭제(버전 복구 불가, 운영 버전 재확인) |

## 6. AIStor 엔지니어 방문 준비

1. `15-aistor-engineer-briefing/README.md` 의 5분 요약 → 01 ~ 06 순서로 읽기 (약 2시간)
2. `14-ilm-config-guide/05-aistor-engineer-qna.md` 질의서 출력 · Q-S2 의 규모 숫자(객체 · 버전 · 노드 · 드라이브) 채우기
3. 현장에서 `06-question-guide.md` 의 메모 칸 · 결정 틀 채우기
4. 그림: `diagrams/*.drawio` (Confluence draw.io 매크로 Import) · `*.svg` (미리보기)

## 7. 키트 다시 만들기

```bash
cd docs
rm -rf aistor-ilm-airgap-kit/aistor-iceberg-ilm-guide aistor-ilm-airgap-kit/aistor-replication-review
cp -r aistor-iceberg-ilm-guide aistor-replication-review aistor-ilm-airgap-kit/
find aistor-ilm-airgap-kit -name 'audit-minio-*.jsonl' -delete      # 서명 헤더 · 내부 IP
python3 -c "import shutil; shutil.make_archive('aistor-ilm-airgap-kit', 'zip', '.', 'aistor-ilm-airgap-kit')"
```
