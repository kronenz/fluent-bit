# AIStor Hot/Warm 클러스터 + ILM/Replication 환경에서의 Iceberg-Spark 운영 가이드

> 대상 환경: AIStor(MinIO) S3 **hot 클러스터 / warm 클러스터** 2단 구성
> · ILM: hot 1일 → warm 1일 (테스트 값)
> · Replication: Versioning ON, hot → warm
> · **저장·액세스 경로는 hot 클러스터 엔드포인트로 단일화**
> · 데이터: 사내 운영 Iceberg 테이블 (S3 기반)
> · 처리 엔진: Spark on Kubernetes + Iceberg + **Hive Metastore 카탈로그**

---

## 0. 이 문서를 읽기 전에 — 3분 요약

이 환경에서 **가장 먼저 알아야 할 5가지**입니다. 나머지 챕터는 이 5가지를 증명하고 확장하는 내용입니다.

| # | 핵심 사실 | 왜 중요한가 | 상세 |
|---|---|---|---|
| 1 | Iceberg 테이블은 `metadata.json → manifest list → manifest → data file` 의 **절대경로 체인**이다 | 체인 중 하나라도 못 읽으면 테이블 전체가 안 열린다. 객체 스토리지 정책(ILM/복제)이 이 체인을 건드리는 순간 "스토리지 문제"가 아니라 "테이블 장애"가 된다 | [05장](./05-iceberg-on-s3/) |
| 2 | **ILM `expiration`을 Iceberg 데이터 경로에 걸면 100% 데이터 유실**이다 | S3 ILM은 "이 객체가 살아있는 스냅샷에서 참조 중인지" 모른다. 1일 뒤 삭제하면 live snapshot이 참조하는 Parquet이 사라진다 | [04장](./04-ilm-policy-design/), [11장](./11-failure-and-risk/) |
| 3 | `metadata/` 프리픽스는 **transition 대상에서 제외**해야 한다 | 쿼리 플래닝은 매 쿼리마다 metadata를 읽는다. 이게 warm으로 내려가면 모든 쿼리의 시작 지연이 warm RTT만큼 늘어난다 | [04장](./04-ilm-policy-design/), [10장](./10-performance/) |
| 4 | Scanner가 24~48시간 주기라는 것은 **"1일 규칙 = 1일 뒤 실행"이 아니라 "1일 경과 + 다음 스캔 방문 시 실행"** 을 뜻한다 | 테스트 시 "정책이 안 도는 것 같다"의 90%는 장애가 아니라 스캐너 사이클 대기다. 판별 절차가 필요하다 | [02장](./02-aistor-internals/), [09장](./09-operations/) |
| 5 | Versioning ON + Iceberg 유지보수(`expire_snapshots`)는 **noncurrent 버전을 무한 축적**시킨다 | 삭제해도 용량이 안 줄고, 버전 수가 늘수록 scanner 사이클이 더 느려져 4번 문제가 악화되는 악순환에 빠진다 | [04장](./04-ilm-policy-design/), [11장](./11-failure-and-risk/) |

---

## 1. 챕터 구성 및 학습 순서

| 순서 | 챕터 | 내용 | 성격 | 예상 학습시간 |
|---|---|---|---|---|
| 1 | [00-overview](./00-overview/) | 문서 목적·범위·용어, 테스트 목표와 합격 기준, 전제조건 | 개요 | 20분 |
| 2 | [01-architecture](./01-architecture/) | hot/warm 토폴로지, 데이터 흐름, ILM×Replication 상호작용 매트릭스 | 기술 이해 | 40분 |
| 3 | [02-aistor-internals](./02-aistor-internals/) | 객체 레이아웃, Versioning, ILM, Remote Tier, Replication, **Scanner 동작 원리** | 기술 이해 | 60분 |
| 4 | [03-cluster-setup](./03-cluster-setup/) | hot/warm 구성, tier 등록, replication 설정, 검증 명령 | 절차 | 60분 |
| 5 | [04-ilm-policy-design](./04-ilm-policy-design/) | 1d→1d 규칙 설계, 프리픽스 분리, noncurrent 정책, 스캐너 가속 | 절차·설계 | 60분 |
| 6 | [05-iceberg-on-s3](./05-iceberg-on-s3/) | Iceberg 물리구조, HMS 카탈로그, commit 프로토콜, **ILM/복제 충돌 지점** | 기술 이해 (**핵심**) | 90분 |
| 7 | [06-spark-setup](./06-spark-setup/) | Spark on K8s + Iceberg + S3 설정 전량, jar 버전 매트릭스 | 절차 | 60분 |
| 8 | [07-test-data](./07-test-data/) | **운영 Iceberg 테이블을 hot으로 안전 반입**하는 절차, 경로 재작성 | 절차 (**주의**) | 60분 |
| 9 | [08-test-scenarios](./08-test-scenarios/) | 시나리오별 테스트 절차·판정 기준 (T-01 ~ T-24) | 절차 | 90분 |
| 10 | [09-operations](./09-operations/) | 일일 점검, 모니터링 지표, 상태 확인 명령, 운영 일정표 | 관리 | 40분 |
| 11 | [10-performance](./10-performance/) | 성능 측정 항목·방법·기준선, 튜닝 포인트 | 성능 | 60분 |
| 12 | [11-failure-and-risk](./11-failure-and-risk/) | 장애 시나리오 F-01~F-18, 리스크 레지스터, 복구 절차 | 리스크 (**핵심**) | 90분 |
| 13 | [12-appendix](./12-appendix/) | 명령어 레퍼런스, 트러블슈팅 FAQ, 설정 템플릿 | 참조 | 수시 |

### 목적별 빠른 진입

| 지금 하려는 일 | 읽을 순서 |
|---|---|
| 환경을 처음 이해하고 싶다 | 01 → 02 → 05 |
| 지금 당장 클러스터를 구성해야 한다 | 03 → 04 → 06 |
| 테스트를 설계/실행해야 한다 | 08 → 04 → 10 |
| 운영 데이터를 반입해야 한다 | **07 (필독)** → 05 |
| "정책이 안 도는 것 같다" | 02 §5(Scanner) → 09 §3(진단) → 11 F-09 |
| 쿼리가 갑자기 느려졌다 | 10 §5 → 05 §6 → 04 §3 |
| 장애가 났다 | 11 → 12 (FAQ) |
| 리스크 보고서를 써야 한다 | 11 §9(리스크 레지스터) → 00 §5 |

---

## 2. 문서 표기 규칙

| 표기 | 의미 |
|---|---|
| `HOT`, `WARM` | mc alias 이름. 실제 환경 alias로 치환해 사용 |
| `WARM-TIER` | ILM remote tier 이름 (예약어 아님, 대문자 관례) |
| ⚠️ | 데이터 유실 또는 서비스 영향 가능 — 실행 전 반드시 확인 |
| 🔍 | 버전 의존적 — 사용 중인 AIStor/mc/Iceberg 버전에서 실제 확인 필요 |
| ✅ | 판정 기준 (테스트 합격 조건) |

### 버전 확인이 선행되어야 하는 이유

AIStor(MinIO) · `mc` · Iceberg는 릴리스마다 명령 플래그와 메트릭 이름이 바뀝니다. 본 문서의 명령은 **최근 계열 기준**으로 작성되었으며, 🔍 표시가 붙은 항목은 아래 명령으로 먼저 확인하십시오.

```bash
mc --version
mc admin info HOT
mc admin config get HOT scanner          # scanner 튜닝 키 존재 여부
mc ilm rule add --help                   # 플래그 이름 확인
mc replicate add --help
```

```sql
-- Spark 세션에서
SELECT * FROM hive_prod.system.iceberg_version;   -- 미지원 시 spark-shell 에서 org.apache.iceberg.util.* 확인
```

---

## 3. 문서 이력

| 버전 | 일자 | 작성자 | 변경 내용 |
|---|---|---|---|
| 1.0 | 2026-08-27 | - | 최초 작성 (13개 챕터) |
