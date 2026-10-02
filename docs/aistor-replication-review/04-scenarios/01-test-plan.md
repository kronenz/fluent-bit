# 시나리오 테스트 계획 · 일정 (안)

## 1. 테스트 범위

| 시나리오 | 대상 | 테스트 ID | 선행 조건 | 그림 |
|---|---|---|---|---|
| 공통 | Hot · Warm · 이천/용인 dataops · 모니터링 | TC-00-01 ~ 08 | — | 01, 03 |
| 1. Tiering | 비정형 RAW · Archive → Warm Tier (ILM) | TC-S1-01 ~ 12 | TC-00 | 17 |
| 2. Replication (DR) | 정형 Iceberg → Warm replica (실시간 · 주기) · 복구 | TC-S2-01 ~ 16 | TC-00 · **G1 버전 일치** (Bucket Replication 항목) | 18 |
| 3. 용인 데이터 | Warm 임시 적재 → 신규 S3 일괄 이관 | TC-S3-01 ~ 12 | TC-00 · 용인 네트워크 · (이관 항목) 신규 S3 준비 | 19 |

## 2. 판정 기준 공통

| 구분 | 기준 |
|---|---|
| 합격 (P) | 기대 결과 충족 · 측정값 기록 |
| 조건부 (C) | 기대 결과 일부 충족 · 우회 방안 확인 |
| 불합격 (F) | 기대 결과 미충족 · 이슈 등록 |
| 보류 (H) | 선행 조건 미충족 (게이트 대기) |

## 3. 테스트 시나리오

### 3.1 공통 준비 (TC-00)

| ID | 항목 | 사전 조건 | 절차 | 기대 결과 · 판정 | 관련 | 우선 | 담당 | 결과 |
|---|---|---|---|---|---|---|---|---|
| TC-00-01 | 클러스터 버전 · 상태 | — | `mc admin info HOT` · `WARM` | Hot 2026-02-07 · Warm 2026-06-06 확인, 정상 | No 36 | 상 | | |
| TC-00-02 | 대상 버킷 Versioning 상태 | — | `mc version info HOT/ic-fdc` 등 | 현재 상태 기록 (OFF / Enabled / Suspended) | V-1, E1-9 | 상 | | |
| TC-00-03 | 테스트 버킷 · prefix 생성 | G0 역할 분리안 | 테스트 전용 버킷 (Hot · Warm · 용인) | 운영 버킷과 분리 | E1-5 | 상 | | |
| TC-00-04 | 역할별 access key | — | replica · tier · 용인 · batch(admin) 키 발급 | 정책대로 허용 · 차단 | B-2, PX-6 | 상 | | |
| TC-00-05 | Scanner · 복제 기준선 | — | `mc admin scanner info` · 메트릭 수집 | 사이클 시간 · 지표 기준선 기록 | E3-1 | 중 | | |
| TC-00-06 | 테스트 데이터 | — | Iceberg 테이블(소형 · 대형 · MERGE 多) · RAW 소형 파일 다수 | 데이터 세트 준비 · 건수 · 용량 기록 | T-B 6.1 | 상 | | |
| TC-00-07 | Airflow 테스트 DAG 환경 | — | mc 이미지 · KubernetesPodOperator · 알림 채널 | DAG 실행 가능 | No 40 | 중 | | |
| TC-00-08 | 모니터링 대시보드 | — | Hot/Warm 지연 · 처리량 · 용량 · 복제 백로그 패널 | 테스트 중 지표 관측 가능 | E2-7 | 중 | | |

### 3.2 시나리오 1 — Tiering (TC-S1)

| ID | 항목 | 사전 조건 | 절차 | 기대 결과 · 판정 | 관련 | 우선 | 담당 | 결과 |
|---|---|---|---|---|---|---|---|---|
| TC-S1-01 | Tier 등록 | TC-00 | Warm tier 버킷/prefix 생성 · `mc ilm tier add` | Tier 등록 · 전용 prefix | M14, M18 | 상 | | |
| TC-S1-02 | raw → raw Transition | TC-S1-01 | `raw/` 에 Transition 1일 규칙 · 대기 | Scanner 방문 후 Tier 이동 · 소요 시간 기록 | ③④⑤ · M10 | 상 | | |
| TC-S1-03 | Transition 후 투명 조회 | TC-S1-02 | Hot 엔드포인트로 GET · Trino 조회 | 정상 조회 · 지연(Hot 대비) 측정 | ⑩⑪ | 상 | | |
| TC-S1-04 | 제외 prefix | TC-S1-02 | `metadata/` 등 제외 규칙 확인 | 제외 대상은 Hot 유지 | 선행 가이드 04장 | 중 | | |
| TC-S1-05 | zip 변환 Job (하이브리드 B) | AR-1 협의안 | Airflow → zip Job → `archive/` 저장 + manifest | zip 생성 · checksum 일치 · 멱등 재실행 | ⑥⑦⑧ · AR-2 | 상 | | |
| TC-S1-06 | archive → Tier Transition | TC-S1-05 | `archive/` Transition 규칙 | zip 객체 Tier 이동 | ⑨ | 상 | | |
| TC-S1-07 | 원본 정리 | TC-S1-05 | 원본 태그 → ILM Expiration | 원본 삭제 · noncurrent 처리 확인 | AR-4 · V-2 | 중 | | |
| TC-S1-08 | Tier 직접 접근 차단 | TC-S1-02 | tier 버킷을 용인 · 일반 키로 접근 | 거부 | C-3 · M14 | 상 | | |
| TC-S1-09 | Transition 객체 zip 조회 | TC-S1-06 | S3 Zip 확장(`x-minio-extract`) 조회 | 가능 여부 기록 | E4-4 | 하 | | |
| TC-S1-10 | 용량 절감 측정 | TC-S1-02 ~ 07 | Hot · Warm 용량 전후 비교 · 압축률 | 절감량 산출 (A vs B) | E4-2 | 상 | | |
| TC-S1-11 | Warm 장애 시 Tier 조회 | TC-S1-03 | Warm 일시 차단 후 GET | 실패 형태 · 복구 후 정상화 기록 | — | 중 | | |
| TC-S1-12 | Scanner 부하 | TC-S1-02 | 대량 객체 Transition 중 Scanner 지표 | 사이클 시간 변화 기록 | 근거 3 | 중 | | |

### 3.3 시나리오 2 — Replication · DR (TC-S2)

| ID | 항목 | 사전 조건 | 절차 | 기대 결과 · 판정 | 관련 | 우선 | 담당 | 결과 |
|---|---|---|---|---|---|---|---|---|
| TC-S2-01 | 버전 일치 확인 (게이트) | 업그레이드 완료 | `mc admin info` 양쪽 | 동일 릴리스 — 미충족 시 Bucket Replication 항목 보류(H) | G1 · M17 | 상 | | |
| TC-S2-02 | Versioning ON + seed | TC-S2-01 | Versioning OFF 버킷에 적재 → ON → 규칙 → seed | 기존 파일 미복제 확인 · seed 후 완전 | V-1 · T-B10 | 상 | | |
| TC-S2-03 | 실시간 복제 지연 | TC-S2-02 | Iceberg INSERT 반복 · 백로그 측정 | 지연 p50 · p95 기록 | ② · E2-7 | 상 | | |
| TC-S2-04 | 부분 복제 스냅샷 재현 (C1) | TC-S2-03 | 대량 커밋 직후 Warm 에서 최신 metadata 검증 | 누락 시점 · 지속 시간 기록 | C1 | 상 | | |
| TC-S2-05 | 삭제 전파 | TC-S2-03 | `expire_snapshots` · `remove_orphan_files` → 플래그별 비교 | delete-marker 반영 · noncurrent 보존 확인 | V-4 · T-B2 | 상 | | |
| TC-S2-06 | noncurrent 증가 · 만료 | TC-S2-05 | 유지보수 반복 → 만료 규칙 | 증가량 · 회수량 기록 | V-2 · T-B11 | 중 | | |
| TC-S2-07 | Versioning prefix 제외 | — | `--excluded-prefixes "structured/*"` | 제외 prefix 실삭제 · 복제 제외 | TP-2 · M24 | 상 | | |
| TC-S2-08 | Batch 주기 복제 | TC-S2-07 | 유지보수 후 `mc batch start` (structured/) | 완료 · 복사 건수 · Versioning 없이 동작 여부 | ③ · TP-3 | 상 | | |
| TC-S2-09 | Batch 증분 | TC-S2-08 | `newerThan` · `createdAfter` 반복 | 누락 · 중복 0 | TP-4 | 상 | | |
| TC-S2-10 | Batch 부하 튜닝 | TC-S2-08 | workers · wait 조합별 실행 | Hot 지연 허용치 내 설정 확정 | TP-7 · M26 | 상 | | |
| TC-S2-11 | Batch 중단 · 재시작 | TC-S2-08 | 실행 중 재시작 · 네트워크 단절 | 재개 여부 · DAG 재실행 복구 | TP-8 | 중 | | |
| TC-S2-12 | Airflow DAG 전체 | TC-S2-08 | DAG ①~⑦ · 실패 주입 | 워터마크 · 알림 · 검증 정상 | TP-9 | 중 | | |
| TC-S2-13 | DR 리허설 | TC-S2-03 또는 08 | ⑤ 장애 → ⑥ HEAD 검증 → ⑦ register → ⑧ DNS 전환 → ⑨ 조회 | 복구 성공 · RTO 측정 · RPO 산출 | T-B6 · DR-1~8 | 상 | | |
| TC-S2-14 | 원복 (failback) | TC-S2-13 | 역방향 복제 또는 resync → DNS 원복 | Hot 정상화 · 정방향 재개 | DR-8 | 중 | | |
| TC-S2-15 | 복제 + Transition 병행 | TC-S1-02 · TC-S2-03 | 같은 prefix 에 두 규칙 | 이중 저장 · 순서 · resync 영향 기록 | T-B8 · 제약 ①~⑧ | 중 | | |
| TC-S2-16 | 공존 부하 | TC-S2-03 · TC-S3-04 | 복제 · Tier 유입 중 용인 I/O | Warm 지연 · 처리량 허용치 | T-B9 | 상 | | |

### 3.4 시나리오 3 — 용인 데이터 (TC-S3)

| ID | 항목 | 사전 조건 | 절차 | 기대 결과 · 판정 | 관련 | 우선 | 담당 | 결과 |
|---|---|---|---|---|---|---|---|---|
| TC-S3-01 | DNS · 방화벽 · VIP 경로 | 방화벽 신청 완료 | `nslookup` · `nc -zv` · `openssl s_client` | 해석 · 연결 · 인증서 정상 | ①~⑦ 체크포인트 | 상 | | |
| TC-S3-02 | 권한 분리 | TC-00-04 | 용인 키로 yongin-* / replica / tier 접근 | yongin-* 허용 · 나머지 거부 | H-52 | 상 | | |
| TC-S3-03 | 대용량 적재 | TC-S3-01 | Spark multipart 적재 (GB 단위) | 성공 · 처리량 · 타임아웃 없음 | ② | 상 | | |
| TC-S3-04 | HMS-Warm 테이블 | HMS-Warm 배포 | CREATE · INSERT · SELECT (Trino · Spark) | 메타 · 데이터 정상 · location = yongin-* | ③ · H-50 | 상 | | |
| TC-S3-05 | Polaris lake_warm | Polaris PoC | external catalog 조회 | 조회 성공 | P-01~P-06 | 중 | | |
| TC-S3-06 | 일괄 이관 (Batch) | 신규 S3(또는 대체 테스트 클러스터) | ④ `mc batch start` (Warm → 신규) | 완료 · 소요 시간 · 처리량 | ④⑤⑥ | 상 | | |
| TC-S3-07 | 이관 검증 | TC-S3-06 | ⑦ 건수 · 용량 · checksum · Iceberg HEAD | 차이 0 | ⑦ | 상 | | |
| TC-S3-08 | 증분 동기화 | TC-S3-06 | 이관 중 신규 적재 → `newerThan` 재실행 | 최종 차이 0 | — | 상 | | |
| TC-S3-09 | 카탈로그 전환 | TC-S3-07 | ⑧ register 또는 location 변경 (버킷명 다르면 `rewrite_table_path`) | 신규 위치로 조회 성공 | ⑧ · I3 | 상 | | |
| TC-S3-10 | 클라이언트 전환 · 롤백 | TC-S3-09 | ⑨ DNS 전환 → 롤백 리허설 | 전환 · 롤백 모두 정상 · 중단 시간 기록 | ⑨ | 상 | | |
| TC-S3-11 | 임시 데이터 정리 | TC-S3-10 | ⑩ yongin-* Expiration / 삭제 | 용량 회수 · 신규 쪽 영향 없음 | ⑩ | 중 | | |
| TC-S3-12 | 이관 시간 산정 | TC-S3-06 | 처리량 × 예상 데이터량 | 실이관 소요 시간 · 창 산정 | — | 중 | | |

## 4. 테스트 일정 (안)

> 기준: 2026-10-05 (개천절 대체공휴일) · 2026-10-09 (한글날) 제외 · 주 단위 · 게이트 미충족 시 해당 항목은 다음 주로 이월

| 주차 | 기간 | 시나리오 | 테스트 | 게이트 · 산출물 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| W1 | 10/06 – 10/08 | 공통 | TC-00-01 ~ 08 | **G0 Warm 버킷 역할 분리 확정** · 테스트 환경 준비 완료 | | ☐ |
| W2 | 10/12 – 10/16 | S1 · S3 | TC-S1-01 ~ 04 · TC-S3-01 ~ 03 | Tiering 기본 동작 · 용인 경로 개통 확인 | | ☐ |
| W3 | 10/19 – 10/23 | S1 · S3 · S2(Batch) | TC-S1-05 ~ 12 · TC-S3-04 ~ 05 · TC-S2-07 ~ 10 | **G2 아카이브 A/B/C 협의 자료** · Batch 설정값 초안 | | ☐ |
| W4 | 10/26 – 10/30 | S2(준비) | Hot · Warm **버전 일치 작업** (벤더 · 변경 창) · TC-S2-11 ~ 12 | **G1 버전 일치** (미충족 시 W5 S2 Bucket 항목 이월) | | ☐ |
| W5 | 11/02 – 11/06 | S2 | TC-S2-01 ~ 06 · TC-S2-15 ~ 16 | 복제 지연 · 삭제 전파 · 공존 부하 결과 | | ☐ |
| W6 | 11/09 – 11/13 | S2 · S3 | TC-S2-13 ~ 14 (DR 리허설) · TC-S3-06 ~ 09 | **RPO/RTO 측정치** · 이관 처리량 (신규 S3 미준비 시 대체 클러스터) | | ☐ |
| W7 | 11/16 – 11/20 | S3 · 종합 | TC-S3-10 ~ 12 · 회귀 · 미결 재시험 | 결과 보고서 · 운영 이관 판단 | | ☐ |

## 5. 게이트 · 의존성

| 게이트 | 내용 | 필요 시점 | 미충족 시 영향 | 담당 | 상태 |
|---|---|---|---|---|---|
| G0 | Warm 버킷 역할 분리 (용인 · replica · tier) · 키 정책 | W1 종료 | 전 시나리오 테스트 버킷 구성 불가 | | ☐ |
| G1 | Hot · Warm 버전 일치 | W4 종료 | TC-S2-01 ~ 06 · 13 ~ 16 보류 (Batch 항목은 진행) | | ☐ |
| G2 | 아카이브 방식 A/B/C 협의 | W3 종료 | TC-S1-05 ~ 07 범위 축소 | | ☐ |
| 네트워크 | 용인 방화벽 · DNS · VIP | W2 시작 | TC-S3 전체 지연 | | ☐ |
| HMS-Warm | 용인 HMS · Oracle 스키마 | W3 시작 | TC-S3-04 ~ 05 지연 | | ☐ |
| 신규 S3 | 이관 대상 클러스터 (또는 대체 테스트 클러스터) | W6 시작 | TC-S3-06 ~ 12 지연 | | ☐ |
| 변경 창 | 버전 업그레이드 작업 승인 | W4 | G1 지연 | | ☐ |

## 6. 결과 요약 (기입용)

| 시나리오 | 전체 | 합격 (P) | 조건부 (C) | 불합격 (F) | 보류 (H) | 주요 이슈 | 판정 |
|---|---|---|---|---|---|---|---|
| 공통 | 8 | | | | | | |
| 1. Tiering | 12 | | | | | | |
| 2. Replication · DR | 16 | | | | | | |
| 3. 용인 데이터 | 12 | | | | | | |
| 합계 | 48 | | | | | | |

## 7. 측정 지표 (기입용)

| 지표 | 시나리오 | 측정 위치 | 목표 | 측정값 |
|---|---|---|---|---|
| Transition 소요 시간 (규칙 기간 대비) | 1 | Scanner · `mc ls` | | |
| Tier 조회 지연 (Hot 대비) | 1 | Trino · GET | | |
| 용량 절감률 (A / B) | 1 | `mc du` | | |
| 실시간 복제 지연 p95 | 2 | 복제 메트릭 | | |
| Batch 처리량 · Hot 지연 영향 | 2 | Batch status · Hot 지표 | | |
| RPO · RTO | 2 | DR 리허설 | | |
| 용인 적재 처리량 | 3 | Spark | | |
| 일괄 이관 처리량 · 총 소요 시간 | 3 | Batch status | | |
| 전환 중단 시간 | 3 | DNS 전환 | | |
| Warm 공존 부하 (지연 · 처리량) | 2 · 3 | Warm 지표 | | |
