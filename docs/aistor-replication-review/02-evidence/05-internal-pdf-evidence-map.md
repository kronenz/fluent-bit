# 사내 보안 PDF — 문서별 확인 포인트 매핑

> 카테고리: 근거 정리
> 사내 보안문서이므로 **본문을 인용하지 않습니다**. 문서명과 "어느 주장을 위해 무엇을 찾아야 하는지"만 기록하고, 확인 후 *페이지/절 번호*만 채워 넣습니다.
> 공개 문서로 먼저 근거를 확보한 항목은 [06-official-reference-links.md](./06-official-reference-links.md) 의 ID(M·A·I·P·T·C)로 표시했습니다 — 사내 PDF 는 **동일 내용이 상용 AIStor 버전에서도 유효한지** 교차 확인하는 용도입니다.

## 1. 문서 목록

| ID | 문서명 | 성격 | 주로 뒷받침하는 장표 |
|---|---|---|---|
| PDF-1 | [SK Hynix] AiStor 2-Tier 구성 시 고려사항.pdf | 사내 환경 맞춤 권고 | 장표 1·2, 근거 4, 향후 5 |
| PDF-2 | Global Reference - Versioning, ILM, Replication, Object Locking_May2026.pdf | 기능 간 상호작용 레퍼런스 | 근거 2, 장표 1 |
| PDF-3 | ILM (Information Lifecycle Management).pdf | ILM 기능 레퍼런스 | 근거 4, 근거 2(C4) |
| PDF-4 | Object Locking (Write On Read Merge).pdf | Object Lock 기능 레퍼런스 | 근거 2(C5), 근거 4 |
| PDF-5 | Replication.pdf | Replication 기능 레퍼런스 | 근거 2(C1·C3), 장표 1 |
| PDF-6 | Versioning.pdf | Versioning 기능 레퍼런스 | 근거 2(C3), 근거 4 |

> PDF-4 제목의 "Write On Read Merge" 는 일반적으로 WORM(**W**rite **O**nce **R**ead **M**any)을 뜻합니다. 문서 표지의 정식 명칭을 확인해 장표 인용 시 통일하십시오.

## 2. 주장별 확인 매핑 (체크리스트)

| 근거 ID | 주장 (장표에 쓰는 문장) | 확인할 문서 | 찾아야 할 내용 (키워드) | 공개 근거 | 페이지/절 | 확인 |
|---|---|---|---|---|---|---|
| R-01 | 복제는 기본 **비동기**, 동기 모드는 옵션 | PDF-5 | "asynchronous", "synchronous", "--sync", PUT 응답 시점 | M1 | | ☐ |
| R-02 | 복제는 양쪽 **Versioning ON** 필수 | PDF-5, PDF-6 | "versioning", "requirement", "prerequisite" | M1 | | ☐ |
| R-03 | 여러 객체 간 **순서/시점 일관성 보장 없음** | PDF-5, PDF-2 | "order", "consistency", "guarantee" — *문구 부재 자체*가 근거이므로 목차 전체 확인 | M2 | | ☐ |
| R-04 | delete / delete-marker 복제는 **플래그로 선택** | PDF-5, PDF-2 | "delete marker replication", "versioned delete", "--replicate" | M3 | | ☐ |
| R-05 | **ILM Expiration 으로 삭제된 객체는 복제되지 않음** | PDF-2, PDF-3 | "lifecycle expiration" × "replication" 상호작용 표 | M3 | | ☐ |
| R-06 | 기존 객체 복제 기본 동작, resync 절차 | PDF-5 | "existing objects", "resync" | M4 | | ☐ |
| R-07 | Replication + Transition(Tier) 병행 제약, **resync 시 Tier 연결 단절** | PDF-2, PDF-1 | "tier", "transition", "resync", "permanently disconnected" | M5 | | ☐ |
| R-08 | ILM 액션은 Transition·Expiration 계열뿐 (압축/병합 없음) | PDF-3 | 액션 목록 표, "compress", "archive", "merge" 검색 결과 없음 | M6, A1 | | ☐ |
| R-09 | Transition 은 **객체 1:1**, 조회는 Hot 엔드포인트 경유 | PDF-3, PDF-1 | "remote tier", "transparent", "GET", "restore" | M6 | | ☐ |
| R-10 | ILM 은 **Scanner** 가 비동기로 실행 | PDF-3 | "scanner", "cycle", "delay" | M10 | | ☐ |
| R-11 | 서버측 압축은 **투명 압축** (zip 아님) | PDF-1, PDF-3 | "compression", "transparent" | M7 | | ☐ |
| R-12 | Object Lock 은 Versioning 필수, 보존 중 삭제 불가 | PDF-4, PDF-6 | "retention", "governance", "compliance", "legal hold" | M9 | | ☐ |
| R-13 | 잠긴 객체 복제는 **양쪽 버킷 Object Lock** 필요 | PDF-4, PDF-5, PDF-2 | "object lock" × "replication" | M9 | | ☐ |
| R-14 | 잠긴 객체에 대한 ILM Expiration 동작 (delete marker 만 생성 등) | PDF-4, PDF-3 | "expiration" × "locked" | M9 | | ☐ |
| R-15 | Versioning 시 삭제 = delete marker, noncurrent 축적 → 별도 만료 규칙 필요 | PDF-6, PDF-3 | "delete marker", "noncurrent", "excess versions" | M6 | | ☐ |
| R-16 | Site Replication 과 Bucket Replication 의 차이 (**상호 배타**) | PDF-2, PDF-5 | "site replication", "IAM", "mutually exclusive" | M11 | | ☐ |
| R-17 | 2-Tier 구성의 권장 접근 엔드포인트(Hot 단일화 vs Warm 직접) | PDF-1 | "endpoint", "access", "client" | — | | ☐ |
| R-18 | 2-Tier 간 네트워크 요구(대역폭·포트·전용망) | PDF-1 | "network", "bandwidth", "port", "latency" | — | | ☐ |
| R-19 | 복제 지연/실패 모니터링 지표와 명령 | PDF-5 | "metrics", "status", "backlog", "failed" | — | | ☐ |
| R-20 | 복제 대역폭 제한 설정 | PDF-5, PDF-1 | "bandwidth", "limit" | — | | ☐ |
| R-21 | Scanner 가 ILM·Replication·Healing 을 함께 처리, 사이클·속도 설정·느려지는 요인 | PDF-3, PDF-2, PDF-1 | "scanner", "cycle", "speed", "excess versions" | M12 | | ☐ |
| R-22 | 3회 재시도 후 큐에서 빠진 FAILED 복제는 Scanner 가 재큐잉 · GET/HEAD 시 자동 재큐잉 | PDF-5 | "retry", "three", "requeue", "resync-backlog" | M13 | | ☐ |
| R-23 | 시점 지정 복제 방법 (배치 복제 · 규칙 disable/enable 후 누락분 처리) | PDF-5, PDF-2 | "batch", "schedule", "disable", "enable", "resync" | — (T-B3, T-B4) | | ☐ |
| R-24 | Transition 은 백업/DR 효과가 없음 · Transition 된 객체의 조회 방식 | PDF-3, PDF-1 | "business continuity", "disaster recovery", "tier" | M5 | | ☐ |

## 3. 문서별 요약 체크 (읽는 순서 권장)

| 순서 | 문서 | 이 문서에서 반드시 답을 얻어야 할 질문 |
|---|---|---|
| 1 | PDF-1 2-Tier 고려사항 | ① 우리 환경의 Hot/Warm 은 Replication 인가 Tier 인가, 둘 다인가? ② Warm 직접 접근을 허용하는 구성인가? ③ 네트워크·엔드포인트 권고는? |
| 2 | PDF-2 Global Reference | ④ Versioning·ILM·Replication·Lock 조합 중 **금지/주의 조합**은? ⑤ ILM 삭제·delete marker 가 복제에 어떻게 반영되는가? |
| 3 | PDF-5 Replication | ⑥ 비동기 모드의 보장 범위(순서/일관성)는? ⑦ 상태 확인·재처리 방법은? |
| 4 | PDF-3 ILM | ⑧ 액션 목록과 필터 · Scanner 동작 ⑨ Tier 객체 조회 방식 |
| 4-1 | PDF-3 / PDF-5 Scanner 관련 절 | ⑧-1 Scanner 사이클이 느려질 때 Transition·복제 재처리 지연을 벤더가 어떻게 안내하는가? 권장 speed 설정은? |
| 5 | PDF-6 Versioning | ⑩ noncurrent 버전 정리 방법, 버전 수 한도 |
| 6 | PDF-4 Object Locking | ⑪ 우리 버킷에 Lock 이 필요한가? 필요 시 Iceberg 유지보수와의 충돌 해소 방법 |
