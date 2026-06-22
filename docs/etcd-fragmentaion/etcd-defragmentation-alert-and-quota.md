# etcd 조각화 알람 노이즈 · 수식 보완 · 쿼터 16Gi→8Gi 축소 가이드

> 목적: `icdataops-prd` 클러스터에서 상시 발생하는 `etcdDatabaseHighFragmentationRatio`
> 알람 노이즈의 **원인을 규명**하고, ① 알람 수식 보완 ② `in_use` 임계값(size) 조정
> ③ `ETCD_QUOTA_BACKEND_BYTES` 16Gi→8Gi 축소의 **기준과 근거**를 확립합니다.
> 배경: etcd 조각화(fragmentation) 알람은 **쿼터를 전혀 참조하지 않아**, 쿼터를 키울수록
> 구조적으로 상시 발화합니다. 이 문서는 그 메커니즘과 교정안을 정리합니다.
> 다이어그램: 첨부 `etcd-fragmentation-logic.drawio` (구조 + 판정 로직).

---

## 1. 현황 정리 (icdataops-prd)

| 항목 | 메트릭 / 설정 | 현재 값 | 의미 |
|---|---|---|---|
| 쿼터 | `ETCD_QUOTA_BACKEND_BYTES` | **16Gi** | 이 값에 도달하면 NOSPACE alarm → etcd가 **read-only**로 멈춤 |
| 물리 DB | `etcd_mvcc_db_total_size_in_bytes` (DB_SIZE) | **1.5Gi** | backend(boltdb) **파일 전체 크기** — 삭제/compaction으로 생긴 free page 포함 |
| 논리 DB | `etcd_mvcc_db_total_size_in_use_in_bytes` | **786Mi** | **실제 사용 중**인 논리 데이터 크기 |
| 조각 비율 | `in_use / total` | **≈ 0.51** | 0.5 미만이면 "파일의 절반 이상이 빈 공간(조각)" |
| 회수 가능 | `total − in_use` | **≈ 750Mi** | defrag 시 디스크로 돌아오는 양 |
| 쿼터 사용률 | `total / quota` | **≈ 9%** (1.5Gi / 16Gi) | **여유 매우 충분 — 조각은 실제 위험이 아님** |

핵심: **물리 DB 1.5Gi는 쿼터 16Gi의 9%**에 불과합니다. 디스크·쿼터 압박이 전혀 없는데도
조각 알람만 끊임없이 웁니다.

---

## 2. 알람이 노이즈인 이유 (근본 원인)

### 2.1 현행 수식

`etcdDatabaseHighFragmentationRatio` (kube-prometheus-stack / etcd-mixin 정본):

```promql
(  last_over_time(etcd_mvcc_db_total_size_in_use_in_bytes[5m])
 / last_over_time(etcd_mvcc_db_total_size_in_bytes[5m]) ) < 0.5
and etcd_mvcc_db_total_size_in_use_in_bytes > 104857600        # 100Mi
for: 10m
```

발화 조건은 단 두 개입니다.

1. **`in_use / total < 0.5`** — 물리 파일의 절반 이상이 회수 가능한 빈 공간(조각)입니다.
2. **`in_use > 100Mi`** — 소규모 클러스터 노이즈를 막기 위한 **절대 바닥값**입니다.

### 2.2 왜 상시 발화하는가

- **메커니즘**: keyspace에 쓰기·삭제가 잦으면 compaction이 과거 리비전을 비우며 **free page**(조각)를
  남깁니다. 이 free page는 defrag 전까지 물리 파일(`total`)에 그대로 남아 **`total`을 부풀립니다**.
  반면 `in_use`는 실데이터만 반영하므로, **`total`이 커질수록 `in_use / total` 비율은 0.5 아래로 내려갑니다.**
  (현재 ≈0.51로 경계에 있고, churn으로 `total`이 조금만 더 커지면 0.5 미만으로 유지되어 발화합니다.)
- **`in_use`(786Mi)는 100Mi 바닥값을 항상 초과**하므로 두 번째 조건은 사실상 무력합니다.
- **결정적 결함 — 쿼터를 안 봅니다**: 수식 어디에도 `ETCD_QUOTA_BACKEND_BYTES`가 없습니다.
  100Mi 바닥값은 **etcd 기본 쿼터 2Gi**를 가정해 보정된 값(= 쿼터의 5%)입니다. 쿼터를 16Gi로
  8배 키운 환경에서는 이 바닥값이 **무의미**해지고, 조각 비율도 quota-blind라 **물리 DB가 아무리
  작아도(쿼터 대비) 조각률만 높으면 웁니다.**

> 요약: **이 알람은 "쿼터 대비 위험"이 아니라 "조각 비율 + 100Mi"만 봅니다.**
> 쿼터를 키운 클러스터에서는 구조적으로 상시 발화하는 노이즈입니다. (다이어그램 §B 참조)

---

## 3. 수식 보완 — 쿼터 상대 항 추가

조각 비율만으로는 "지금 defrag가 필요한가"를 판단할 수 없습니다. **물리 DB가 쿼터의 의미 있는
비중을 차지할 때만** 조각이 문제가 됩니다. 따라서 **쿼터 상대 항**을 추가합니다.

etcd는 쿼터를 메트릭으로 노출합니다: **`etcd_server_quota_backend_bytes`**.

### 보완 수식 (제안)

```promql
(  last_over_time(etcd_mvcc_db_total_size_in_use_in_bytes[5m])
 / last_over_time(etcd_mvcc_db_total_size_in_bytes[5m]) ) < 0.5
and ( etcd_mvcc_db_total_size_in_bytes
      / etcd_server_quota_backend_bytes ) > 0.5                # NEW: 물리 DB가 쿼터의 50% 초과
and etcd_mvcc_db_total_size_in_use_in_bytes > 838860800        # 800Mi (바닥값 상향, §4)
for: 30m                                                       # 10m→30m, churn 일시 스파이크 무시
```

- **NEW 항 `total / quota > 0.5`**가 핵심입니다: 물리 DB가 쿼터의 절반을 넘을 때만 발화하므로,
  현재 9%인 상태에서는 **절대 울지 않습니다.** 조각률이 높아도 쿼터 여유가 크면 무시합니다.
- `for`를 30m으로 늘려 churn에 의한 일시적 조각 스파이크를 걸러냅니다.
- (다이어그램 §C 참조)

### 별도 — 진짜 actionable한 "쿼터 압박" 알람 (신규 권장)

조각이 아니라 **쿼터 근접**이 실제 호출 가치가 있는 신호입니다(NOSPACE → etcd 정지 위험).

```promql
# warning
etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes > 0.8
# critical
etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes > 0.95
```

---

## 4. `in_use` 임계값(size) 조정 — 왜 800Mi로도 부족한가

현행 100Mi 바닥값은 **기본 쿼터 2Gi의 5%**로 보정된 값입니다. 쿼터를 키우면 바닥값도
**비례**해서 올려야 노이즈 특성이 유지됩니다.

| 쿼터 | 비례 바닥값 (쿼터의 5%) |
|---|---|
| 2Gi (기본) | 100Mi |
| 8Gi | 400Mi |
| **16Gi (현재)** | **800Mi** |

즉 16Gi 환경에서 **산술적으로는 최소 800Mi**로 올려야 합니다. 그러나 **이것만으로는 부족합니다**.

1. **현재 `in_use`가 이미 786Mi**입니다 — 800Mi 바닥은 지금 겨우 턱걸이로 막을 뿐,
   churn으로 `in_use`가 800Mi를 넘기는 순간 **다시 발화**합니다. 임시방편입니다.
2. **조각 비율(`in_use/total < 0.5`) 자체가 quota-blind**라는 구조적 결함은 바닥값을
   아무리 올려도 해결되지 않습니다. `total`이 커지면 비율은 계속 0.5 아래로 갑니다.

→ 결론: **바닥값 상향(§4)은 단독으로 불충분하며, 반드시 §3의 쿼터 상대 항과 함께** 적용해야 합니다.
바닥값은 "쿼터 상대 항이 주된 게이트, 800Mi는 소규모 노이즈 방지용 보조 게이트" 역할로 둡니다.

---

## 5. `ETCD_QUOTA_BACKEND_BYTES` 16Gi → 8Gi 축소

> **8GiB는 etcd가 공식적으로 권장하는 backend 최대치**입니다. 16Gi는 권장 범위를 벗어나
> 구조적으로 불리한 점이 많습니다.

### 5.1 16Gi가 불리한 이유

| # | 항목 | 설명 |
|---|---|---|
| 1 | **공식 권장 상한 초과** | etcd 문서는 backend 최대 권장치를 **8GiB**로 명시합니다. 그 이상은 검증/튜닝 영역 밖이며 etcd 자체도 경고합니다. |
| 2 | **defrag 정지시간 증가** | defrag는 해당 멤버를 **stop-the-world**로 블로킹하며, 소요 시간이 **DB 크기에 비례**합니다. 16Gi DB는 수십 초~분 단위 블로킹이 가능 → **200대 규모 고 QPS에서 위험**합니다. 8Gi면 절반입니다. |
| 3 | **메모리 압박** | etcd는 boltdb 파일을 **mmap**하므로 DB 전체가 페이지 캐시/RSS를 점유합니다. 16Gi DB는 그만큼 노드 RAM을 점유합니다. |
| 4 | **복구·재시작 지연** | 멤버 재시작, 스냅샷 전송, **신규 멤버 catch-up**, WAL replay 시간이 DB 크기에 비례 → **RTO가 악화**되고, 리더 변경 시 영향이 커집니다. |
| 5 | **성능 저하** | boltdb B+tree가 커질수록 조회·트랜잭션 latency가 증가합니다. etcd는 작게 유지하는 것이 성능에 유리합니다. |
| 6 | **보호 기능 약화** | 쿼터가 클수록 **런어웨이(runaway) write**를 늦게 차단합니다. 16Gi를 다 채우는 동안 디스크·메모리·성능을 모두 갉아먹습니다. 작은 쿼터가 **조기 NOSPACE**로 클러스터를 보호합니다. |
| 7 | **백업 비용 증가** | 스냅샷/백업 크기·소요 시간·전송·보관 비용이 모두 증가합니다. |

### 5.2 축소 안전성 / 절차

- **안전성**: 쿼터를 현재 물리 DB(`total`)보다 작게 줄이면 **즉시 NOSPACE**가 됩니다.
  현재 1.5Gi ≪ 8Gi이므로 **8Gi로의 축소는 안전**합니다.
- **적용**: 각 멤버의 `--quota-backend-bytes=8589934592` (= 8 × 1024³) 변경 후 **롤링 재시작**합니다.
  (per-member 플래그이므로 멤버별로 순차 적용 + 사이 health 확인이 필요합니다.)
- **권장 동반 작업**: 축소와 함께 **1회 defrag**를 수행하면 물리 DB가 `in_use` 수준(≈786Mi)으로
  줄어 즉시 깨끗한 베이스라인을 확보합니다. (defrag는 멤버 1개씩, follower 먼저·leader 마지막으로 진행합니다.)

### 5.3 축소 후 임계값 재보정

8Gi 기준으로 §4 표를 다시 적용하면 비례 바닥값은 **400Mi**입니다. 그러나 현재 `in_use`(786Mi)가
이미 그보다 크므로 **바닥값 단독으로는 여전히 노이즈가 남습니다** — 이는 §3의 **쿼터 상대 항이
필수**임을 다시 보여줍니다. 축소 후에도 보완 수식(§3)을 그대로 사용하되, `total / quota > 0.5`는
8Gi 기준 **물리 DB > 4Gi일 때만** 발화하므로 실질적으로 actionable한 상태에서만 웁니다.

---

## 6. 적용 체크리스트

- [ ] **알람**: 조각 룰을 §3 보완 수식으로 교체합니다(`kps`의 `defaultRules.disabled.etcdDatabaseHighFragmentationRatio: true` + 커스텀 `PrometheusRule`), `for` 30m, `in_use` 바닥 800Mi.
- [ ] **알람**: §3 "쿼터 압박" 알람(`total/quota > 0.8/0.95`)을 신규 추가합니다 — 이것이 진짜 page 대상입니다.
- [ ] **조각 알람은 page에서 제외**합니다 — 정보성(ticket/Slack)으로 강등합니다.
- [ ] **쿼터**: 멤버별 `--quota-backend-bytes=8589934592`(8Gi)를 롤링 적용하고 사이에 `etcdctl endpoint health`를 확인합니다.
- [ ] **defrag**: 축소 시 1회 defrag(멤버 순차, leader 마지막)로 베이스라인을 확보합니다. 정기 defrag는 고정 주기 대신 **쿼터/회수량 조건부**로 진행합니다(별도 가이드 참조).

---

## 부록 — 메트릭 용어 정리

| 메트릭 | 뜻 | 비고 |
|---|---|---|
| `etcd_mvcc_db_total_size_in_bytes` | 물리 DB 파일 크기 (free page 포함) | defrag로 줄어듦 |
| `etcd_mvcc_db_total_size_in_use_in_bytes` | 논리적 실사용 크기 | 실데이터 |
| `etcd_server_quota_backend_bytes` | 설정된 쿼터 | `--quota-backend-bytes` 노출 |
| 조각(fragmentation) | `total − in_use` (회수 가능 free page) | defrag로만 디스크 회수 |
| NOSPACE alarm | `total ≥ quota` 시 발생 | etcd가 read-only로 전환 |
