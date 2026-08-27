# 02. AIStor 내부 동작 — 무엇이 실제로 일어나는가

> 이 챕터는 "왜 그렇게 동작하는가"를 다룹니다. 명령 실행은 [03장](../03-cluster-setup/)에서 합니다.
> 🔍 표시 항목은 사용 중인 AIStor/mc 버전에서 실제 확인이 필요합니다.

## 1. 객체 저장 구조

AIStor(MinIO 계열)는 객체 하나를 **디렉터리 + 메타데이터 파일 + 데이터 파트**로 저장합니다.

```
<drive>/<bucket>/<object-key>/
    ├── xl.meta                      ← 객체 메타데이터 (버전 목록, ETag, 전이 정보, 복제 상태)
    ├── <version-uuid>/part.1        ← 실제 데이터 (Erasure Coding 샤드)
    └── <version-uuid>/part.2
```

### xl.meta 가 담는 정보 (이 문서의 맥락에서 중요한 것만)

| 항목 | 의미 | 어느 챕터에서 쓰이나 |
|---|---|---|
| 버전 리스트 | 각 버전의 VersionID, 생성시각, current 여부, delete marker 여부 | Versioning, noncurrent 정책 |
| ETag / 체크섬 | 무결성 검증 | 08장 정합성 검증 |
| **Transition 정보** | 전이 여부, tier 이름, 원격 객체 식별자 | 전이 상태 판별의 핵심 |
| **Replication 상태** | PENDING / COMPLETED / FAILED / REPLICA | 복제 진단 |
| 사용자 메타데이터/태그 | ILM 필터 조건으로 사용 가능 | 04장 태그 기반 규칙 |

### 여기서 나오는 핵심 성질

> **전이(transition)가 일어나도 `xl.meta`는 hot에 남는다.**

따라서:

| 관찰 | 전이 전 | 전이 후 |
|---|---|---|
| `mc ls` 결과 | 보임 | **보임 (동일)** |
| 객체 크기 표기 | 실제 크기 | **실제 크기 (동일)** |
| hot 디스크 사용량 | 실제 크기 | 거의 0 |
| `mc stat` | tier 표기 없음 | **tier 이름 표기됨** ← 판별 지점 |
| `mc cat` / GET | hot 로컬에서 즉시 | hot이 warm에서 가져와 응답 (지연↑) |

⚠️ **`mc ls`로는 전이 여부를 알 수 없습니다.** 전이 검증은 반드시 `mc stat` 또는 메트릭/스토리지 사용량으로 판단하십시오. 이걸 몰라서 "전이가 안 됐다"고 오판하는 경우가 흔합니다.

## 2. Versioning

### 2.1 동작

| 작업 | Versioning OFF | Versioning ON |
|---|---|---|
| 같은 키에 PUT | 덮어씀 (이전 소멸) | 새 버전 생성, 이전은 **noncurrent**로 보존 |
| DELETE (버전 미지정) | 실제 삭제 | **delete marker** 생성. 실데이터는 noncurrent로 잔존 |
| DELETE (버전 지정) | - | 해당 버전 실제 삭제 (영구) |
| GET | 유일 객체 | current 버전 |
| GET (VersionId 지정) | 불가 | 해당 버전 |

### 2.2 Iceberg 관점에서의 함의

Iceberg는 **데이터 파일을 절대 덮어쓰지 않습니다** (immutable). 그래서 언뜻 versioning과 무관해 보입니다.
그러나 실제로는 다음 경로로 noncurrent 버전이 대량 발생합니다.

| 발생 경로 | 무엇이 생기나 | 규모 |
|---|---|---|
| `expire_snapshots` 로 오래된 데이터/매니페스트 삭제 | delete marker + noncurrent 버전 | **큼** (유지보수 1회당 수천~수만) |
| `rewrite_data_files` (compaction) 후 구 파일 삭제 | delete marker + noncurrent | 큼 |
| `remove_orphan_files` | delete marker + noncurrent | 중 |
| 실패한 커밋의 잔여 파일 정리 | 소량 | 소 |
| HMS 카탈로그의 metadata.json 정리 (`write.metadata.delete-after-commit.enabled`) | delete marker + noncurrent | 중 |

> 🔴 **결과: "삭제했는데 용량이 안 줄어든다"** 는 이 환경의 기본 증상입니다.
> 버저닝 버킷에서 DELETE는 논리 삭제일 뿐이며, **noncurrent 버전 만료 규칙이 없으면 용량은 영원히 증가**합니다.
> 대응: [04장 §5](../04-ilm-policy-design/)

### 2.3 버전 수가 늘면 생기는 2차 효과

```
noncurrent 버전 증가
   → 스캐너가 순회해야 할 "버전 엔트리" 수 증가
      → 스캐너 1사이클 소요 시간 증가
         → ILM 적용 지연 증가
            → 만료가 더 늦어짐 → noncurrent 더 축적  (악순환)
```

이것이 "규모에 따라 24~48시간이 달라진다"는 관찰의 주요 원인 중 하나입니다.

## 3. ILM (Lifecycle Management)

### 3.1 규칙 구성 요소

| 요소 | 설명 | Iceberg 환경 권고 |
|---|---|---|
| **필터: prefix** | 대상 키 프리픽스 | ✅ `data/` 만 지정 (필수) |
| **필터: tags** | 객체 태그 매칭 | 세밀 제어 시 |
| **필터: size** | 객체 크기 범위 🔍 | 소형 파일 제외에 유용 |
| **Transition (days / date)** | N일 후 tier로 전이 | ✅ 사용 |
| **Noncurrent transition** | noncurrent 버전 전이 | 선택 |
| **Expiration (days)** | N일 후 current 버전 삭제 | 🔴 **Iceberg data에 금지** |
| **Noncurrent expiration** | noncurrent 버전 N일 후 삭제 | ✅ **필수** |
| **Expire delete markers** | 고아 delete marker 정리 | ✅ 권장 |
| **AbortIncompleteMultipartUpload** | 미완료 멀티파트 정리 | ✅ 권장 (숨은 용량 누수) |

### 3.2 "days" 의 기준 시각

| 대상 | 나이 계산 기준 |
|---|---|
| current 버전 | 객체(버전) 생성 시각 |
| noncurrent 버전 | **해당 버전이 noncurrent가 된 시각** (= 다음 버전이 만들어진 시각) |
| delete marker | 생성 시각 |

⚠️ `days: 1`은 "24시간 후"가 아니라 **S3 규약상 "생성일 기준 다음 날 자정(UTC) 이후"** 로 해석되는 것이 일반적입니다 🔍. 즉 실제 경과는 24~48시간이 될 수 있습니다. 여기에 스캐너 대기까지 더해지면 **최대 3일 가까이** 걸릴 수 있습니다. 테스트 판정 기준을 세울 때 반드시 감안하십시오.

### 3.3 Transition 시 실제 동작 순서

```
1. Scanner가 객체 방문
2. ILM 규칙 매칭 평가 (prefix/tag/size/age)
3. 매칭 시 transition 작업 큐에 등록
4. 워커가 tier로 데이터 업로드 (원격에 새 객체 생성)
5. 업로드 성공 확인 후 로컬 데이터 파트 삭제
6. xl.meta 에 transition 정보 기록
```

| 단계 실패 시 | 결과 |
|---|---|
| 4 실패 (네트워크/권한) | 로컬 데이터 유지, 재시도 대상. **데이터 안전** |
| 5 실패 | 원격·로컬 양쪽 존재 (용량 낭비), 재시도 |
| 큐 적체 | 전이 지연. `minio_node_ilm_transition_pending_tasks` 로 확인 🔍 |

> 설계 원칙상 **전이 실패가 데이터 유실로 이어지지는 않습니다.** 유실은 expiration 계열에서만 발생합니다.

### 3.4 전이된 객체 읽기 경로

```
Spark ─GET(range)─► hot
                     ├─ xl.meta 확인 → "transitioned to WARM-TIER"
                     ├─ tier 자격증명으로 warm에 GET (range 전달 🔍)
                     └─ 응답 스트리밍 → Spark
```

| 항목 | 영향 |
|---|---|
| 지연 | hot 로컬 대비 (warm RTT + warm 처리시간) 만큼 증가 |
| hot 자원 | 프록시 트래픽으로 hot의 네트워크/CPU 소모 |
| Range GET | Parquet은 footer/컬럼청크 단위 range 요청 → **요청 수 × RTT** 로 증폭 |
| 캐시 | 🔍 전이 객체 읽기 캐시 동작 여부는 버전 의존. 있으면 반복 쿼리 개선 |

⚠️ Parquet 읽기는 파일당 최소 2~3회의 range GET을 발생시킵니다(footer length → footer → column chunks). 전이 후 이 요청들이 전부 warm까지 왕복하므로, **작은 파일이 많을수록 성능 저하가 기하급수적**입니다. → [10장 §3](../10-performance/)

## 4. Replication

### 4.1 전제와 동작

| 항목 | 내용 |
|---|---|
| 전제 | 원본·대상 버킷 **모두 Versioning Enabled** |
| 단위 | 버킷 (프리픽스 필터 지정 가능) |
| 방식 | 비동기. PUT 응답은 로컬 커밋 시점에 반환 |
| 상태 표기 | 객체 헤더 `X-Amz-Replication-Status`: `PENDING` → `COMPLETED` / `FAILED`, 대상 측은 `REPLICA` |
| 재시도 | 실패 시 자동 재시도. 지속 실패는 별도 조치 필요 |

### 4.2 복제 옵션별 의미

| 옵션 | 의미 | Iceberg 환경 권고 |
|---|---|---|
| `existing-objects` | 규칙 설정 이전에 이미 있던 객체도 복제 | ✅ 초기 동기화에 필요 |
| `delete` | 버전 삭제를 대상에도 전파 | 신중 (아래 참조) |
| `delete-marker` | delete marker를 대상에도 생성 | 신중 |
| `replica-metadata-sync` | 메타데이터 변경 동기화 (양방향 구성 시) | active-active 시 ✅ |

#### `delete` / `delete-marker` 전파의 딜레마

| 설정 | 장점 | 위험 |
|---|---|---|
| 전파 ON | 양쪽 상태 일치, 용량 일치 | ⚠️ hot에서의 **잘못된 삭제가 warm까지 전파** → DR 사본 소실 |
| 전파 OFF | warm이 삭제로부터 보호됨 (사실상 백업) | warm 용량 무한 증가, 상태 불일치 |

> 이 환경(Iceberg 유지보수가 대량 삭제를 발생시킴)에서는 **전파 OFF + warm 자체 보존 정책**이 DR 관점에서 안전하고, **전파 ON**은 용량 관점에서 유리합니다. 어느 쪽이든 [11장 F-13](../11-failure-and-risk/)의 시나리오를 검토하고 결정하십시오.

### 4.3 Replication과 Proxy Read

복제가 구성된 버킷에서 **로컬에 없는 객체를 요청**하면, 원격에 있는지 확인해 프록시 조회하는 동작이 있습니다 🔍
(메트릭: `minio_bucket_replication_proxied_get_requests_total` 계열)

| 의미 | 영향 |
|---|---|
| 만료로 hot에서 사라진 객체가 warm에는 있으면, 조회가 "성공"할 수 있음 | 테스트 시 **만료가 안 된 것처럼 보이는 착시** |
| 지연이 크게 증가 | 성능 이상으로 오인 |

⚠️ 방식 B(복제+만료) 테스트 시 이 동작 때문에 "만료됐는데 왜 읽히지?" 라는 혼선이 생깁니다. 판정은 `mc stat`/`mc ls --versions` 로 하십시오.

### 4.4 "active / ready" 상태의 해석

구성 시 표기되는 상태는 대체로 다음을 뜻합니다 🔍.

| 표기 | 통상적 의미 | 확인 명령 |
|---|---|---|
| `Active` | 복제 규칙이 활성화되어 동작 중 | `mc replicate ls HOT/BUCKET` |
| `Ready` | 대상 사이트가 수신 가능 상태 | `mc replicate status HOT/BUCKET` |
| `Disabled` | 규칙 존재하나 중지 | 동상 |

사이트 복제(`mc admin replicate`)를 쓰는 경우와 버킷 복제(`mc replicate`)를 쓰는 경우가 다르므로, 어느 쪽인지 03장 §7에서 먼저 확정하십시오.

| 구분 | 버킷 복제 (`mc replicate`) | 사이트 복제 (`mc admin replicate`) |
|---|---|---|
| 범위 | 버킷 단위 | 클러스터 전체 (IAM/정책/버킷 설정 포함) |
| ILM 설정 동기화 | ❌ 안 됨 | ✅ 됨 🔍 |
| 구성 난이도 | 낮음 | 중 |
| 이 문서 기본 가정 | ✅ | 참고만 |

⚠️ **사이트 복제를 쓰는 경우, hot에 만든 ILM 규칙이 warm에도 복제될 수 있습니다.** 그러면 warm의 tier 버킷/복제 버킷에도 동일 만료 규칙이 걸려 **의도치 않은 삭제**가 발생할 수 있습니다. 반드시 실측 확인하십시오. → [11장 F-14](../11-failure-and-risk/)

## 5. Scanner — 이 환경 이해의 핵심 ★

### 5.1 스캐너란

객체를 순회하며 다음을 수행하는 백그라운드 프로세스입니다.

| 역할 | 설명 |
|---|---|
| ILM 평가/실행 | 전이·만료 대상 판별 및 작업 등록 |
| 사용량 통계 집계 | 버킷/프리픽스별 용량 산출 (`mc du`, 콘솔 표시) |
| 힐링 트리거 | 손상/누락 샤드 감지 |
| 복제 재시도 후보 탐지 | 실패한 복제 재처리 🔍 |

### 5.2 "왜 24~48시간인가"

스캐너는 **전체 네임스페이스를 한 바퀴 도는 데 걸리는 시간(사이클)** 만큼 지연을 갖습니다.

```
사이클 시간 ≈ f(총 객체 수, 총 버전 수, 드라이브 수, 스캐너 속도 설정, 클러스터 부하)
```

| 요인 | 사이클 증가 방향 | 이 환경에서의 특징 |
|---|---|---|
| 총 객체 수 | ↑ | Iceberg는 파일 수가 매우 많음 (파티션 × 파일) |
| **총 버전 수** | ↑↑ | Versioning ON + 유지보수 삭제로 폭증 |
| delete marker 수 | ↑ | 위와 동일 |
| 스캐너 속도 설정 | 설정에 따라 | 기본값은 보수적(운영 부하 최소화) |
| 클러스터 I/O 부하 | ↑ | 스캐너는 저우선순위로 양보함 |
| 드라이브/노드 수 | ↓ (병렬화) | |

> **결론: ILM 규칙 `1일`은 "1일 뒤 실행"이 아니라 "1일 경과 + 다음 스캔 방문 시 실행"입니다.**
> 실제 관측 지연 = (S3 days 해석 오차 0~24h) + (스캐너 사이클 대기 0~48h) = **최대 약 72시간**

### 5.3 스캐너 속도 조정

🔍 버전에 따라 키가 다릅니다. 먼저 확인하십시오.

```bash
# 현재 설정 확인
mc admin config get HOT scanner

# 최근 계열: speed 프리셋
mc admin config set HOT scanner speed=fast
#   값 예: slowest | slow | default | fast | fastest

# 구 계열: delay / max_wait / cycle 키
mc admin config set HOT scanner delay=1 max_wait=5s cycle=1m

# 적용 후 반영 확인 (서비스 재시작이 필요할 수 있음 🔍)
mc admin config get HOT scanner
```

| 속도 | 사이클 | 클러스터 부하 | 권장 상황 |
|---|---|---|---|
| `slowest`/`slow` | 매우 김 | 최소 | 대규모 운영, I/O 여유 없음 |
| `default` | 김 | 낮음 | 일반 운영 |
| `fast` | 짧음 | 중 | **테스트 기간** ✅ |
| `fastest` | 최단 | 높음 ⚠️ | 짧은 검증 구간에만. 운영 시간대 금지 |

⚠️ `fastest`는 사용자 I/O 성능에 영향을 줄 수 있습니다. 테스트 종료 후 **반드시 원복**하십시오. 원복을 잊는 것이 흔한 사고 원인입니다.

### 5.4 스캐너 상태 관측

```bash
# Prometheus 메트릭 (이름은 버전 의존 🔍)
mc admin prometheus metrics HOT cluster | grep -i scanner
mc admin prometheus metrics HOT node    | grep -i scanner
```

| 메트릭(예시) | 의미 | 활용 |
|---|---|---|
| `minio_node_scanner_bucket_scans_started` | 시작된 버킷 스캔 수 | 사이클 진행 판단 |
| `minio_node_scanner_bucket_scans_finished` | 완료된 버킷 스캔 수 | **started - finished = 진행 중** |
| `minio_node_scanner_objects_scanned` | 스캔된 객체 수 | 진행률 |
| `minio_node_scanner_versions_scanned` | 스캔된 버전 수 | 버전 폭증 감지 |
| `minio_node_scanner_directories_scanned` | 스캔된 디렉터리 수 | |
| `minio_node_ilm_transition_pending_tasks` | 전이 대기 작업 | **적체 판단 핵심** |
| `minio_node_ilm_transition_active_tasks` | 전이 진행 중 | |
| `minio_node_ilm_versions_scanned` | ILM 평가된 버전 수 | 규칙 평가 진행 |

> 사이클 완료 시간 추정: `bucket_scans_finished` 증가분을 시간축으로 관찰하면 1사이클 소요를 역산할 수 있습니다. 실측 절차는 [09장 §3](../09-operations/)에 있습니다.

### 5.5 스캐너를 "즉시 돌릴" 수 있는가

| 방법 | 가능 여부 | 비고 |
|---|---|---|
| 강제 즉시 전체 스캔 명령 | 일반적으로 **없음** | 사용자 트리거형 API 미제공 🔍 |
| 속도 프리셋 상향 | ✅ | 가장 현실적 |
| 대상 데이터셋 축소 | ✅ | 전용 테스트 버킷으로 분리 → 사이클 단축 |
| 서비스 재시작 | 부분적 | 사이클이 재시작되나 처음부터 다시 돌 수 있어 오히려 손해 ⚠️ |
| 객체 접근(GET) 트리거 | 🔍 | 접근 시 ILM 평가가 일어나는 구현이 있으나 보장 아님 |

> ✅ **테스트 설계 권고**: 소규모 전용 버킷(객체 수천 개 수준)을 별도로 만들어 정책 동작을 먼저 검증하고, 그 다음 실 데이터 규모로 확장하십시오. 대규모 버킷에서 바로 검증하면 사이클 대기로 며칠이 소요되어 원인 분리가 불가능해집니다. → [08장 §2](../08-test-scenarios/)

## 6. 세 기능의 상호작용 요약

| 조합 | 상호작용 | 위험도 |
|---|---|---|
| Versioning × ILM transition | noncurrent 버전도 별도 규칙 필요. 미설정 시 hot에 계속 잔존 | 중 |
| Versioning × Replication | 복제의 전제 조건. 버전 단위로 복제됨 | - |
| Versioning × Scanner | 버전 수가 사이클 시간을 지배 | **높음** |
| ILM × Replication | 전이 객체의 복제 동작이 버전 의존 🔍. 규칙 동기화 안 됨(버킷 복제) | **높음** |
| ILM expiration × Iceberg | 🔴 참조 중 파일 삭제 → 테이블 손상 | **치명** |
| Scanner × Iceberg 유지보수 | 유지보수가 만든 대량 삭제가 사이클을 늘림 | 중 |
| Replication delete 전파 × Iceberg 유지보수 | 유지보수 삭제가 DR 사본까지 제거 | 높음 |

## 7. 이 챕터 요약 및 체크

- [ ] 전이 후에도 `mc ls`에는 그대로 보인다는 것을 이해했다
- [ ] 전이 판별은 `mc stat`으로 한다는 것을 안다
- [ ] Versioning ON에서 DELETE는 용량을 줄이지 않는다는 것을 안다
- [ ] noncurrent expiration 규칙이 없으면 용량이 무한 증가함을 안다
- [ ] ILM `1일`의 실제 적용 지연이 최대 ~72시간일 수 있음을 안다
- [ ] 스캐너 속도 조정 방법과 원복 필요성을 안다
- [ ] 전이 실패는 데이터 유실이 아니지만, 만료 오설정은 유실임을 구분한다
- [ ] warm 직접 조작 금지 이유를 설명할 수 있다

→ 다음: [03. 클러스터 구성 및 검증](../03-cluster-setup/)
