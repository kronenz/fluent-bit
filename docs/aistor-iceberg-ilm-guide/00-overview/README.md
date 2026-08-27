# 00. 문서 개요

## 1. 문서 목적

사내 AIStor S3 hot/warm 2단 클러스터에 **ILM(1d→1d)** 과 **Replication(Versioning ON)** 을 적용한 상태에서,
**운영 Iceberg 테이블**을 Spark(on Kubernetes)로 저장·조회할 때
무엇이 정상이고 무엇이 위험인지를 판단할 수 있도록 하는 것.

구체적으로 이 문서를 다 읽고 나면 다음을 스스로 할 수 있어야 합니다.

| 능력 | 확인 질문 | 해당 챕터 |
|---|---|---|
| 구조 이해 | hot에서 GET한 객체가 실제로 어디서 읽히는지 설명할 수 있는가 | 02 |
| 정책 설계 | 왜 `data/`에는 transition을 걸고 `metadata/`에는 걸면 안 되는지 설명할 수 있는가 | 04, 05 |
| 진단 | "ILM이 안 도는 것 같다"를 스캐너 대기/설정 오류/장애 중 무엇인지 30분 안에 판별할 수 있는가 | 09 |
| 위험 판단 | `remove_orphan_files`를 이 환경에서 언제 실행하면 안 되는지 말할 수 있는가 | 11 |
| 성능 해석 | 전이 후 쿼리가 3배 느려졌을 때 원인을 3가지로 좁힐 수 있는가 | 10 |
| 복구 | warm 클러스터가 4시간 다운됐을 때 어떤 쿼리가 실패하고 어떤 쿼리는 되는지 아는가 | 11 |

## 2. 적용 범위

### 범위 내 (In scope)

- AIStor(MinIO 계열) 오브젝트 스토리지의 ILM / Tiering / Replication / Versioning / Scanner 동작
- Iceberg 테이블 포맷 v2 (Hive Metastore 카탈로그) 의 물리 구조와 위 정책들과의 상호작용
- Spark on Kubernetes 에서의 Iceberg + S3 설정, 읽기/쓰기/유지보수 작업
- 기능 검증 · 성능 측정 · 장애 시나리오 · 운영 점검 절차

### 범위 밖 (Out of scope)

| 항목 | 사유 |
|---|---|
| AIStor 클러스터 최초 설치·하드웨어 사이징 | 이미 구성 완료된 것으로 전제 |
| Kubernetes 클러스터 구축 | 별도 문서 |
| Hive Metastore 설치·HA 구성 | 별도 문서. 단, Iceberg 커밋 관점의 요건은 05장에서 다룸 |
| Trino/Flink 등 Spark 외 엔진 | 필요 시 별도 확장 |
| 운영 데이터 반출 승인 절차 | 사내 거버넌스 정책을 따름 (07장에서 체크포인트만 제시) |

## 3. 전제 조건 (Prerequisites)

### 3.1 환경 전제

| 항목 | 값 / 상태 | 확인 명령 |
|---|---|---|
| hot 클러스터 | 구성 완료, 서비스 엔드포인트 | `mc admin info HOT` |
| warm 클러스터 | 구성 완료, hot에서 네트워크 도달 가능 | `mc admin info WARM` |
| Versioning | 대상 버킷에서 Enabled | `mc version info HOT/BUCKET` |
| Replication | hot → warm 설정됨 | `mc replicate ls HOT/BUCKET` |
| ILM | hot 1d → warm 1d 규칙 존재 | `mc ilm rule ls HOT/BUCKET` |
| Hive Metastore | Thrift 접근 가능 | `nc -z hms-host 9083` |
| Spark | K8s 상에서 실행 가능, 이미지에 Iceberg jar 포함 | 06장 |
| 운영 Iceberg 데이터 | 읽기 권한 확보 | 07장 |

### 3.2 필요한 사전 지식

| 지식 | 최소 수준 | 부족 시 참고 |
|---|---|---|
| S3 API | GET/PUT/LIST, 멀티파트, 버전 개념 | 02장 §1 |
| Parquet | 컬럼 포맷, footer 개념 | 10장 §3 |
| Iceberg | 스냅샷/매니페스트 개념 | 05장 §1~3 |
| Spark | DataFrame/SQL, executor 개념 | - |
| Kubernetes | Pod/Secret/ConfigMap | 06장 |

### 3.3 필요 권한

| 대상 | 권한 | 용도 |
|---|---|---|
| hot 클러스터 | `admin` 또는 ILM/replication 설정 권한 | 정책 설정·조회 |
| hot 버킷 | `s3:GetObject, PutObject, DeleteObject, ListBucket, GetObjectVersion, ListBucketVersions` | Spark 읽기/쓰기 |
| warm 클러스터 | tier 전용 계정 (해당 버킷 RW) | ILM transition 대상 |
| warm 클러스터 | replication 전용 계정 (해당 버킷 RW + 복제 관련) | Replication 대상 |
| Prometheus | AIStor 메트릭 스크레이프 | 09장 모니터링 |
| 운영 S3 | 원본 테이블 **읽기 전용** | 07장 반입 ⚠️ 쓰기 권한 부여 금지 |

## 4. 테스트 목표 및 합격 기준

이 환경 테스트의 목표는 "ILM이 도는지 확인"이 아니라
**"정책이 도는 상태에서도 Iceberg 테이블이 정상 동작하고, 성능·복구 특성을 수치로 안다"** 입니다.

| ID | 목표 | 합격 기준 (✅) | 측정 방법 | 챕터 |
|---|---|---|---|---|
| G-01 | 쓰기 정상성 | Spark write 후 테이블 스캔 결과 행수 == 기대 행수, 커밋 실패 0건 | 08 T-01 | 08 |
| G-02 | 전이 발생 | 1일 경과 객체가 warm tier로 전이되고 `mc stat` 에 tier 표기 | 08 T-05 | 04, 08 |
| G-03 | 전이 후 조회 | 전이된 데이터 파일을 포함한 쿼리가 **결과 동일**하게 성공 | 08 T-06 | 08 |
| G-04 | 메타데이터 보호 | `metadata/` 프리픽스 객체는 전이/만료되지 않음 | 08 T-07 | 04 |
| G-05 | 복제 정합성 | hot의 객체 수/체크섬 == warm의 객체 수/체크섬 (지연 감안) | 08 T-10 | 08 |
| G-06 | 복제 지연 | 복제 backlog가 정상 상태에서 목표치 이내 | 09 §4 | 09 |
| G-07 | 성능 영향 | 전이 후 동일 쿼리 지연 증가율이 기준선 이내 (기준은 10장에서 설정) | 10 §4 | 10 |
| G-08 | 유지보수 안전성 | `expire_snapshots` / `rewrite_data_files` 실행 후 테이블 정상, 유실 0 | 08 T-15~17 | 08, 11 |
| G-09 | 용량 예측 | Versioning + 복제 환경의 실효 사용량 배수를 산출 | 10 §6 | 10 |
| G-10 | 장애 내성 | warm 다운 시 실패하는 쿼리 유형이 문서화된 대로 재현 | 08 T-20, 11 F-05 | 11 |

## 5. 리스크 요약 (경영/관리 보고용)

상세는 [11장 §9 리스크 레지스터](../11-failure-and-risk/)에 있습니다. 여기서는 요약만 제시합니다.

| 등급 | 리스크 | 영향 | 1차 통제 |
|---|---|---|---|
| 🔴 치명 | Iceberg 데이터 프리픽스에 ILM **expiration** 적용 | 테이블 영구 손상, 복구 불가 가능 | 규칙에서 expiration 금지, 규칙 리뷰 절차 |
| 🔴 치명 | `remove_orphan_files` 를 복제 지연/전이 상태에서 실행 | live 데이터 파일 삭제 | 실행 금지 기본값, 예외 시 `older_than` 대폭 확대 + dry-run |
| 🟠 높음 | `metadata/` 전이로 쿼리 플래닝 지연 급증 | 전체 쿼리 SLA 위반 | 프리픽스 분리 규칙 |
| 🟠 높음 | Versioning noncurrent 버전 무한 축적 | 용량 폭증, 스캐너 사이클 악화 | noncurrent expiration 규칙 |
| 🟠 높음 | warm 클러스터 장애 시 전이 데이터 조회 실패 | 과거 파티션 쿼리 실패 | warm 가용성 확보, 실패 범위 사전 파악 |
| 🟡 중간 | Scanner 사이클 지연으로 정책 적용 시점 예측 불가 | 테스트 판정 혼선, 만료 지연 | 스캐너 상태 모니터링, 판정 절차 |
| 🟡 중간 | tier 자격증명 만료/변경 | 전이 객체 전체 조회 불가 | 자격증명 수명 관리 |
| 🟡 중간 | 복제 backlog 누적 | RPO 목표 미달 | backlog 메트릭 알람 |

## 6. 용어 정의

| 용어 | 정의 | 비고 |
|---|---|---|
| **hot 클러스터** | 애플리케이션(Spark)이 직접 접속하는 AIStor 클러스터. 유일한 진입점 | |
| **warm 클러스터** | ILM 전이 대상 및/또는 복제 대상 AIStor 클러스터 | 앱이 직접 접속하지 않음 |
| **ILM** | Information Lifecycle Management. 객체 나이 기반 자동 전이/만료 | S3 Lifecycle 호환 |
| **Transition (전이)** | 객체 데이터를 원격 tier로 이동하고, 로컬에는 메타데이터 stub만 남기는 것 | 객체는 여전히 hot에서 조회됨 |
| **Expiration (만료)** | 객체(또는 버전)를 삭제하는 것 | ⚠️ Iceberg 데이터에 적용 금지 |
| **Remote Tier** | 전이 대상 원격 스토리지 등록 단위 | `mc ilm tier` |
| **Stub** | 전이 후 로컬에 남는 메타데이터 전용 객체 엔트리 | 실 데이터 없음 |
| **Replication** | 버킷 단위 객체 비동기 복제 | Versioning 필수 |
| **Versioning** | 객체 덮어쓰기/삭제 시 이전 버전 보존 | 복제 전제 조건 |
| **Noncurrent version** | 최신이 아닌 이전 버전 객체 | 별도 만료 정책 필요 |
| **Delete marker** | 버저닝 버킷에서 DELETE 시 생성되는 논리 삭제 표식 | 복제 대상 여부 설정 가능 |
| **Scanner** | 객체를 순회하며 ILM·힐링·통계를 처리하는 백그라운드 프로세스 | 사이클 = 전체 1회 순회 |
| **Iceberg** | 테이블 포맷. 스냅샷 기반 ACID | v2 전제 |
| **Snapshot** | 특정 시점 테이블 상태. manifest list 하나로 표현 | |
| **Manifest list** | 스냅샷이 참조하는 manifest 목록 (`snap-*.avro`) | |
| **Manifest** | 데이터 파일 목록 + 통계 (`*-m0.avro`) | |
| **metadata.json** | 테이블 현재 상태 루트 문서 | HMS가 이 경로를 가리킴 |
| **HMS** | Hive Metastore. 여기서는 Iceberg 카탈로그 역할 | 커밋 원자성 담당 |
| **RPO / RTO** | 복구 시점 목표 / 복구 시간 목표 | 11장 |

## 7. 이 문서가 전제하는 "테스트 값"과 운영값의 차이

⚠️ 본 구성의 **1일/1일은 테스트용 가속 값**입니다. 운영 전환 시 반드시 재산정하십시오.

| 항목 | 테스트 값 | 운영 시 고려 | 근거 |
|---|---|---|---|
| hot 보존 | 1일 | 30~90일 (최근 파티션 쿼리 빈도 기반) | 10장 §4 지연 측정 결과 |
| warm 보존 | 1일 | 180일~수년 (규정/감사 요건) | 사내 보존 정책 |
| Scanner 속도 | 가속(fast 계열) | default | 가속은 클러스터 부하 증가 |
| Noncurrent 보존 | 1~7일 | 유지보수 주기의 2배 이상 | 11장 F-11 |
| 대상 프리픽스 | `data/` 만 | 동일 | 05장 §6 |
