# 기한 삭제 검증 — Hot 1일 → Warm 4일 → 삭제 (2026-10-26, 실시간 확인점 진행 중)

> 질문: "Hot 1d · Warm 4d 로 두면 Warm 에서 기한 지난 데이터가 제대로 지워지는지" — 5일을 기다리지 않고 지금 확인하는 방법과 결과
> 환경: corp ns `ilm-test` · MinIO RELEASE.2024-10-13 (hot/warm) · Iceberg 1.9.0 · 같은 `warehouse` 버킷 (Versioning ON)
> 재현: `scripts/perf/run-expiry.sh` · 원시 증적: `exp-20261026/` (수동 1차) · `exp-validate2-20261026/` (스크립트 재현 — 같은 결과)
> Warm `exp/` · `expi/` 객체 수는 여러 실행이 같은 prefix 를 써서 **누적값**이다. 판정은 테이블 · 키별 버전 상태로 한다.
> 가정: "Warm 4일" = Warm 에 4일 둔 뒤 삭제 → S3 일수는 **생성 시점부터** 세므로 `Transition 1` + `Expiration 5` (Warm 체류 4일). 4일 총보존이면 `EXPIRE_DAYS=4` 로 바꾼다.

## 1. 어떻게 확인하나 — 세 가지 방법

| 방법 | 내용 | 무엇을 증명하나 | 소요 |
|---|---|---|---|
| **A. mtime 소급** (이번에 사용) | MinIO 사이트 복제 내부 헤더 `X-Minio-Source-Mtime` 으로 객체를 **N일 전 생성**으로 써서 일수 경과를 즉시 만든다 (`scripts/perf/s3_backdate.py`, 관리자 키) | 규칙의 **일수 계산 · 전이 · 만료 · Warm 실데이터 삭제 · Iceberg 영향**을 실제 규칙 그대로 | 수 분 |
| B. 실시간 확인점 | 만료 예정 시각(`mc stat` 의 `Expiration`)을 미리 계산해 두고 그 시각 이후 상태를 매시 기록 (CronJob `ilmtest-exp-status`) | A 로 못 만드는 **delete marker 이후의 비현행 일수**(마커는 소급 불가) · 실제 Scanner 지연 | 1~2일 |
| C. 운영 축소 시험 | 실제 AIStor 에서 `Transition 1 · Expiration 2 · Noncurrent 1` 처럼 일수를 줄여 3~4일 관찰 | 운영 버전 · 운영 Scanner 사이클에서의 최종 확인 | 3~4일 |

- **ILM 실행 시각 = `mtime + Days` 를 다음 00:00 UTC 로 올린 시각 이후, Scanner 가 그 객체를 방문할 때** (또는 그 시각이 이미 지난 상태로 PUT 되면 PUT 즉시). 예: 10-21 13:49 생성 + 5일 → 10-27 00:00 UTC.
- 소급 PUT 은 **버전 순서도 mtime 으로 정해진다** — 기존 객체를 과거 mtime 으로 다시 쓰면 '이전 버전'으로 들어간다. 그래서 `rewrite` 는 원본 버전을 지워 소급 버전을 최신으로 만든다 (시험 데이터 전용).
- A 는 MinIO 기능이다. AIStor 에서 같은 헤더를 받는지 **E-0 단계가 먼저 확인**하고, 안 되면 B · C 로 간다 (`14-ilm-config-guide/03-agent-runbook.md` §6).

## 2. 결과 요약

| # | 시험 | 결과 | 판정 |
|---|---|---|---|
| E-0 | mtime 소급 | 6일 전으로 PUT → `mc stat` 6.0일 | ✅ 사용 가능 |
| E-1 | 객체 · Versioning ON | 0.5일: Hot 유지 · 2/4.5일: Warm · **6일: delete marker 생성 + Warm 원본 즉시 삭제** · 3일 전부터 비현행인 버전: 비현행 만료로 **Warm 객체 삭제** | ✅ 기한대로 동작 (⚠️ 아래 F-1) |
| E-2 | 객체 · Versioning OFF | 6일: 객체와 Warm 원본 **즉시 영구 삭제** · 나머지 위와 같음 | ✅ |
| E-3 | Iceberg + ILM current Expiration 5d (금지 규칙) | 6일 파티션 파일 만료 → **해당 파티션 · 전체 스캔 · 가장 오래된 스냅샷 time travel 모두 실패** (`NotFoundException: Location does not exist`) — 메타데이터는 여전히 그 파일을 참조 | ❌ 금지 규칙이 테이블을 깬다는 것을 확인 |
| E-4 | Iceberg 보존 작업 + ILM 비현행 만료 (권장) | `DELETE WHERE event_ts < now-5d` (파일 4개 메타데이터 삭제) → `expire_snapshots` (파일 4개 삭제) → 테이블 정상 (200,000행 · time travel OK) · 지운 파일은 **비현행 Warm 버전으로 남고 읽힘** · 만료 예정 **2026-10-28 00:00 UTC** | ✅ (최종 Warm 삭제는 E-5 확인점) |
| E-5 | 실시간 확인점 | ① 2026-10-27 00:00 UTC: `age-4.5` 만료 ② 2026-10-28 00:00 UTC: E-4 `ilmexp2` age6 파티션의 비현행 Warm 버전 4 → 0 · E-1 `age-6` 비현행 기록 정리 | ⏳ 매시 45분 기록 중 |

## 3. 관찰 사실

| # | 관찰 | 증적 |
|---|---|---|
| F-1 | ★ Versioning ON 버킷에서 **이미 Warm 으로 전이된 current 버전**이 ILM Expiration 으로 만료되면, delete marker 가 생기고 원래 버전은 비현행으로 **목록에 남지만 Warm 원본은 즉시 삭제**된다 → 그 버전은 `stat` 은 되고 `GET` 은 `NoSuchKey`. 일반 덮어쓰기로 비현행이 된 전이 버전은 정상적으로 읽힌다 | `exp-*/ilmtest.expread.jsonl` (`obj/age-6` ❌ · `obj/ow` ✅) · Warm `exp/` 객체 수 8 → 5 |
| F-2 | 따라서 "Warm 에서 기한 지난 데이터 삭제"는 **만료 시점에 바로** 일어난다 (비현행 일수를 기다리지 않음). 대신 Versioning 의 버전 복구 안전망은 이 경로에서 **동작하지 않는다** — 버전 이력은 보이지만 데이터가 없다 | 같음 |
| F-3 | ILM 이 만든 delete marker 의 비현행 만료는 마커 생성 + 1일 → 다음 00:00 UTC (예: 10-26 01:50 → **10-28 00:00**). 즉 "비현행 1일" 은 실제로 **최대 2일** | `mc stat` `Expiration: 2026-10-28 00:00:00 UTC (lifecycle-rule-id: e3-noncurrent)` |
| F-4 | 만료일이 이미 지난 객체는 PUT 즉시 처리된다 (Scanner 를 기다리지 않음) — 0d 전이와 같은 경로 | 소급 PUT 직후 `WARM-EXP` |
| F-5 | E-3 에서 Spark 는 메타데이터 단계는 통과하고 **파일을 열 때** 실패한다 → 해당 파티션을 건드리지 않는 쿼리는 계속 성공한다 (age0 · age2 ✅). 장애가 늦게 · 부분적으로 드러난다 | `exp-*/ilmtest.exp.jsonl` |
| F-6 | E-4 의 Iceberg `DELETE` 는 파티션 전체 삭제라 **데이터 파일을 읽지 않고** 메타데이터만 바꿨다 (`deleted-data-files: 4`, 새 파일 0) → Warm 읽기 비용 없음. 파티션 경계와 보존 기준이 맞지 않으면 Warm 파일을 읽어 다시 쓴다 | 같음 |

## 4. 운영 권장 (보존 5일 = Hot 1일 + Warm 4일)

```
Hot warehouse (Versioning ON)
  <db>.db/<tbl>/data/   R-1 Transition 1d → WARM-TIER
                        R-3 NoncurrentVersionExpiration 1d   (Iceberg 가 지운 파일의 Warm 공간 회수)
  <db>.db/<tbl>/        R-6 ExpiredObjectDeleteMarker
  current Expiration    ✗ 걸지 않는다
Iceberg 보존 작업 (매일)  DELETE FROM t WHERE <파티션 컬럼> < now - 5d
                        CALL system.expire_snapshots(older_than => now - <스냅샷 보존>, retain_last => N)
```

- 실제 Warm 데이터가 사라지는 시각 ≈ **보존 기한 + 보존 작업 주기 + 스냅샷 보존 + 비현행 1d(→ 00:00 올림) + Scanner**. 법적 삭제 기한이 있으면 이 합으로 맞춘다.
- Iceberg 를 쓰지 않는 prefix(원천 파일 등)에는 E-1/E-2 처럼 `Expiration` 을 직접 걸어도 된다. 다만 Versioning ON 이면 F-1 때문에 만료와 동시에 데이터가 사라지고 버전 복구는 되지 않는다.

## 5. 남은 확인 (실시간)

| 시각 (UTC) | 확인 | 기대 |
|---|---|---|
| 2026-10-27 00:00 이후 첫 기록 | `ilm-age-test` · `ilm-age-nv` `age-4.5` | VB: delete marker + (F-1 이면) Warm 원본 삭제 · NB: 삭제 · Warm `exp/` 감소 |
| 2026-10-28 00:00 이후 첫 기록 | `ilmexp2` age6 파티션(`event_ts_hour=2026-10-20-01`) 비현행 4개 | `WARM-EXPI: 4` → 0 (Warm 객체 삭제) · 이어서 R-6 이 delete marker 4개 정리. 재현 실행(`ilmexp6` · `ilm-age-test3`)도 같은 시각에 같은 변화 (단, 재현 실행은 CronJob 추적 대상이 아니므로 `exp-object-test.sh status` 를 수동 실행) |
| 같음 | `ilm-age-test` `age-6` 비현행 기록 | 소멸 (데이터는 이미 F-1 로 삭제) |

기록 위치: `/shared/evidence/exp-20261026/ilmtest.expobj.jsonl` (CronJob `ilmtest-exp-status`) → `python3 scripts/perf/exp_report.py <dir>`
