## E-1 / E-2 객체 단위 (최신 → 이전 버전)

기준 시각 2026-10-26T02:08:34Z (after-iceberg)

| 키 | Versioning ON (`ilm-age-test3`) | 기대 | Versioning OFF (`ilm-age-nv3`) | 기대 |
|---|---|---|---|---|
| `age-0.5` | STANDARD | STANDARD | STANDARD | STANDARD |
| `age-2` | WARM-EXP | WARM | WARM-EXP | WARM |
| `age-4.5` | WARM-EXP | WARM | WARM-EXP | WARM |
| `age-6` | DM → WARM-EXP | DM(+비현행) | (없음) | 삭제 |
| `nc` | WARM-EXP | WARM(v1 삭제) | (없음) | - |
| `ow` | STANDARD → WARM-EXP | STANDARD(+비현행 WARM) | (없음) | - |

| 시각 | 단계 | Warm `exp/` 객체 | Warm `expi/` 객체 |
|---|---|---|---|
| 2026-10-26T02:05:18Z | setup | 12 | 36 |
| 2026-10-26T02:05:30Z | newver | 21 | 36 |
| 2026-10-26T02:05:31Z | expire-applied | 18 | 36 |
| 2026-10-26T02:05:32Z | after-expire | 18 | 36 |
| 2026-10-26T02:08:34Z | after-iceberg | 18 | 48 |

### 전이된 비현행 버전 읽기

| 키 | 사유 | storageClass | 읽기 |
|---|---|---|---|
| `obj/age-6` | ILM current Expiration 으로 비현행이 된 전이 버전 | WARM-EXP | ❌ mc: <ERROR> Unable to read from `HOT/ilm-age-test3/obj/age-6`. Object does not exist. |
| `obj/ow` | 일반 덮어쓰기로 비현행이 된 전이 버전 | WARM-EXP | ✅ |

## E-3 / E-4 Iceberg

| 시각 | 테이블 | 단계 | age0 | age2 | age6 | 전체 스캔 | 가장 오래된 스냅샷 | 비고 |
|---|---|---|---|---|---|---|---|---|
| 2026-10-26T02:06:51Z | ilmexp5.events | after-transition | ✅ 100000 | ✅ 100000 | ✅ 100000 | ✅ 300000 | ✅  | data 파일 12 |
| 2026-10-26T02:07:11Z | ilmexp6.events | after-transition | ✅ 100000 | ✅ 100000 | ✅ 100000 | ✅ 300000 | ✅  | data 파일 12 |
| 2026-10-26T02:07:43Z | ilmexp5.events | after-ilm-expiration | ✅ 100000 | ✅ 100000 | ❌ | ❌ | ❌ | data 파일 12 · Caused by: software.amazon.awssdk.services.s3.model.NoSuchKeyException: The spec |
| 2026-10-26T02:08:09Z | ilmexp6.events | retention | — | — | — | — | — | DELETE {'deleted-data-files': '4', 'deleted-records': '100000', 'added-data-files': None, 'added-delete-files': None} · expire_snapshots 삭제 파일 4 |
| 2026-10-26T02:08:29Z | ilmexp6.events | after-iceberg-retention | ✅ 100000 | ✅ 100000 | - | ✅ 200000 | ✅  | data 파일 8 |

| 시각 | 단계 | warehouse/ilmexp5.db/events/data/ | warehouse/ilmexp6.db/events/data/ |
|---|---|---|---|
| 2026-10-26T02:05:18Z | setup |  |  |
| 2026-10-26T02:08:34Z | after-iceberg | 2026-10-20-02: 4 DM,4 WARM-EXPI · 2026-10-24-02: 4 WARM-EXPI · 2026-10-26-02: 4 STANDARD | 2026-10-20-02: 4 DM,4 WARM-EXPI · 2026-10-24-02: 4 WARM-EXPI · 2026-10-26-02: 4 STANDARD |

## 만료 예정 시각 (`mc stat`, Versioning ON 버킷)

```
age-0.5 -
age-2 Expiration: 2026-10-30 00:00:00 UTC (lifecycle-rule-id: e1-transition) 
age-4.5 Expiration: 2026-10-27 00:00:00 UTC (lifecycle-rule-id: e1-transition) 
nc Expiration: 2026-10-29 00:00:00 UTC (lifecycle-rule-id: e1-transition) 
ow -
```
