# 스모크 결과 — Hot→Warm ILM(0d) × Iceberg, Hot 단일 접근 (2026-10-25)

> 환경: corp 클러스터 ns `ilm-test` (임시) · MinIO hot/warm RELEASE.2024-10-13 (별도 StatefulSet 2개) · mc RELEASE.2024-10-08
> · HMS 3.1.3 + PostgreSQL 16 · Spark 3.5.3 + Iceberg 1.9.0 (S3FileIO, Hot 엔드포인트만)
> 규칙: `ilmsmoke.db/events/data/` Transition 0d → `WARM-TIER` · noncurrent 만료 3d · 고아 delete marker 정리 · `metadata/` 규칙 없음
> 원시 증적: 같은 디렉터리 `smoke-20261025/` (`*.jsonl`, `judge-smoke.md`, `ilm-rules-smoke.json`, `tier-ls.txt`)
> 실행 구간: 2026-10-25 20:42 ~ 20:53 UTC

## 1. 판정 (`judge.py` 출력)

| # | 판정 | 근거 |
|---|---|---|
| J-1 | ✅ | 첫 전이 20:45:37Z · 최종 전이율 1.0 · overdue 0 |
| J-2 | ✅ | `metadata/` 전이 0건 (현재 11 · 비현행 6, 전부 STANDARD) |
| J-3 | ✅ | verify 4회 중 불일치 0회 |
| J-4 | ✅ | 전이 후 old_read 성공 4 / 실패 0 · time travel 실패 0 |
| J-5 | ✅ | write 5회 · 실패 0 · write_ms p50 전이 전 2457 / 후 2345 |
| J-6 | ✅ | rewrite_data_files · expire_snapshots · 행 수 보존 모두 ok |
| J-7 | ✅ | Warm audit accessKey = `tier-svc` 뿐 (GetObject 25 · PutObject 1 · GetBucketLocation 1), 경보 0건 |
| J-8 | ✅ | `minio_node_ilm_transition_missed_immediate_tasks` 0 · trace 에러 0 |
| 참고 | — | 읽기 p50: 최근 배치(hot) 291 ms · 전이 배치(warm 경유) 590 ms |

## 2. 관찰 사실

| # | 관찰 | 증적 |
|---|---|---|
| O-1 | 0d 규칙이면 전이는 Scanner 를 기다리지 않고 **PUT 직후** 일어난다 (`ilm-src: s3PutObject`) | `trace.jsonl` — `api: ilm:transition`, `ilm-rule-id: r1-data-transition` |
| O-2 | 전이된 파일 읽기는 Hot 이 **tier 계정으로 Warm 에서 GET** 해서 돌려준다. 클라이언트(`ilmtest-app`)는 Warm 에 한 번도 접속하지 않았다 | `audit-minio-warm.jsonl` (remotehost = minio-hot Pod), `audit-minio-hot.jsonl` |
| O-3 | `rewrite_data_files` 가 전이된 파일 3개를 읽어 새 파일 1개를 Hot 에 썼고, 새 파일도 0d 규칙으로 곧바로 전이됐다 | `ilmtest.maintenance.jsonl`, state 2회차 |
| O-4 | `expire_snapshots(retain_last=1)` 가 지운 전이 파일 3개는 **비현행 버전(WARM-TIER) 3개 + delete marker 3개**로 남는다 → 실데이터는 Warm 에 남아 있고 R-3(3d) 이 회수해야 한다 | state 3회차 `data.noncurrent.WARM-TIER = 3`, `delete_markers = 3` |
| O-5 | `minio_cluster_ilm_transitioned_objects{tier="WARM-TIER"}` 는 1 인데 실제 전이는 3 — 클러스터 사용량 메트릭은 Scanner 가 갱신하므로 늦다. 즉시값은 `minio_node_ilm_action_count_transition_action` | `ilmtest.state.jsonl` metrics |
| O-6 | Hot 경유 읽기 지연은 약 2배(291 → 590 ms, 소규모·클러스터 내부망 기준) | `ilmtest.verify.jsonl` |

## 3. 이번에 새로 부딪힌 함정

| # | 함정 | 증상 | 대응 |
|---|---|---|---|
| P-1 | ★ MinIO 커뮤니티 배포물이 전부 내려갔다 | `quay.io/minio/*` 401, `docker.io/minio/*` 저장소 없음, `dl.min.io` **410 Gone** | 노드에 캐시된 이미지(`imagePullPolicy: Never`)에서 `minio`·`mc` 를 꺼내 RWX 볼륨에 두고 실행 (`testbed/00-shared.yaml`) |
| P-2 | ★ Fluent Bit http input 은 URI 로 태그를 만들 때 `-` 를 `_` 로 바꾼다 | `/minio-hot` → 태그 `minio_hot`. `match: minio-hot` 은 **에러 없이 0건** | match 를 `minio_hot` / `minio_*` 로 |
| P-3 | MinIO audit `queue_dir` 을 켜면 여러 건을 한 요청에 묶어 보낸다 | Fluent Bit `invalid JSON message, skipping` → 전부 버려짐 (MinIO 쪽은 400) | `queue_dir` 미사용 + **수신기를 MinIO 보다 먼저** 기동 (기본값은 수신기 부재 시 버림) |
| P-4 | 공유 증적 디렉터리가 sticky(1777) 라 다른 UID(Spark 185 · root) 파일을 옮길 수 없다 | `mv: Operation not permitted` | 실행(run)마다 `EVIDENCE_DIR=/shared/evidence/<RUN_ID>` |
| P-5 | 2024+ `mc` 는 tier 명령이 `mc ilm tier` 로 이동 | `mc admin tier ls` 미동작 | 스크립트에서 `mc ilm tier` 우선, 실패 시 `mc admin tier` |
| P-6 | 멈춰 둔 CronJob 을 다시 켜면 **놓친 마지막 스케줄을 즉시 1회 실행**한다 | 해제 직후 Writer 가 바로 돌았다 (`LAST SCHEDULE` 이 과거 시각) | 설정을 먼저 바꾼 뒤 해제 (`startingDeadlineSeconds` 로 막을 수도 있음) |

## 4. 다음 단계 (1d 연속 실행 — 진행 중)

| 항목 | 값 |
|---|---|
| RUN_ID / 증적 | `run-1d-20261025` / `/shared/evidence/run-1d-20261025` |
| 대상 | `ilmtest.db/events` (Transition 1d · noncurrent 3d) |
| 시작 | 2026-10-25 20:54 UTC (첫 배치 `20261025T2054`) |
| 첫 전이 예상 | 2026-10-26 20:54 UTC 이후 + Scanner 1사이클 |
| 유지보수 | CronJob `ilmtest-maintenance` 2026-10-27 21:00 UTC 1회 자동 |
| 판정 시점 | 2026-10-28 21:00 UTC 이후 `judge.py /shared/evidence/run-1d-20261025` |
| 정리 | `kubectl delete ns ilm-test` (PVC 는 Delete 정책 — Cinder · JuiceFS 볼륨 함께 삭제) |
