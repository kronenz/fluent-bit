# OpenSearch 테스트 시나리오 매트릭스 (실험 설계 관점)

각 OS-* 시나리오를 실험 설계 (시나리오 / 주제 / 목적 / 수행방법 /
기대결과 / 조작변수 / 통제변수 / 비고) 관점으로 정리. 결과의 비교
가능성과 재현성을 보장하기 위해 통제변수를 명시.

| 시나리오 | 주제 | 목적 | 수행방법 | 기대결과 | 조작변수 (independent) | 통제변수 (controlled) | 비고 |
|----------|------|------|----------|-----------|------------------------|------------------------|------|
| **OS-01**<br/>OSB bulk-ingest | 표준 워크로드 벌크 인덱싱 처리량/지연 | OS 클러스터의 baseline indexing 성능 + 폐쇄망 도구 동작 검증 | `kubectl apply -f 20-scenarios/OS-01-osb-bulk-ingest/`<br/>OSB 가 geonames 워크로드를 `--test-mode` (1k docs) 또는 corpus PVC 로 실행 | exit 0, throughput 200~1k docs/s (test) / 5k~50k (운영), p95 < 50ms (test) / < 500ms (운영), index doc count 일치 | `OSB_WORKLOAD` (geonames/pmc/http_logs/nyc_taxis), `OSB_TEST_PROCEDURE`, `OSB_BULK_SIZE`, `OSB_CLIENTS`, `OSB_TEST_MODE` (true/false) | OS heap (≥ 8 GB), shard 수, replica 수 (≥ 1), `refresh_interval` (1s 기본), merge policy, 네트워크 RTT, **다른 ingest 부하 = 없음** | 다른 부하 미가동 상태에서 **단독 실행** 권장. 운영 부하 측정 시 corpus PVC 사전 적재 + memory 8Gi. mapping 충돌 시 인덱스 삭제 후 재실행. |
| **OS-02**<br/>k6 heavy search (50 VU stress) | 동시 검색 saturation | OS 검색 capacity ceiling 발견 (search thread pool, JVM heap pressure, GC pause) | 인덱스 사전 채움 (flog 10분+) → `kubectl apply -f 20-scenarios/OS-02-k6-heavy-search/`<br/>50 VU × 5분 동시 `_search` (1m ramp-up + 5m sustained + 1m ramp-down) | p95 < 500ms, p99 < 1,500ms, fail < 0.5%, search thread pool reject = 0 | `K6_SEARCH_VU_TARGET` (25/50/100/200), `K6_SEARCH_DURATION`, query 패턴 (match/range/bool), `OS_INDEX_PATTERN` | 인덱스 doc count (≥ 100,000), shard 수, OS heap, **동시 ingest 부하 = 없음** (단독 stress) | **stress 용** — 운영 패턴은 OS-16. 쿼리는 단일 `match` (단순). 복합 aggregation 추가 시 별도 시나리오. ramp-up 중 과부하면 ramp 조정. |
| **OS-14**<br/>high-cardinality 로그 인덱싱 | unbounded keyword field 로 인한 mapping / cluster_state 폭증 | 운영 1순위 사고 (UUID/task_attempt_id 가 dynamic mapping 으로 인덱싱 → cluster_state 비대화 → master OOM) 의 **임계점 사전 발견** | `kubectl apply -f 10-load-generators/loggen-spark.yaml`<br/>UUID per record 무한 발행 → fluent-bit → OS. 30분~2시간 누적 모니터링 | mapping field count, cluster_state size, master heap 추세 그래프. 임계 도달 직전 인지 — field < 10,000, cluster_state < 50MB, master heap < 90% | `replicas` (1/3/10), `LOGGEN_DELAY` (1ms/0.5ms/0.1ms), OS `index_template` 의 `dynamic` 설정 (true/false/strict), keyword field 종류 | OS master node 수 + heap, fluent-bit DaemonSet 동작 (drop = 0), index template 의 `mapping.total_fields.limit` (1,000 기본) | dynamic mapping 이 막혀 있으면 효과 없음 → template 검증 선행. 시나리오의 **성공 = "OS 가 깨지지 않으면서 임계 한도를 알아냈다"**. 결과 기반 운영 액션: total_fields.limit 강제, 문제 필드 → runtime field, fluent-bit `[FILTER] modify` 로 UUID hash. |
| **OS-16**<br/>k6 light search + heavy ingest 동시 | **운영 패턴 SLO 검증** | 6 서비스 팀이 동시에 대시보드를 열어도 (heavy ingest 진행 중) search p95 < 5s 가 깨지지 않는지 검증 | flog + loggen-spark + (선택) OSB 동시 가동 (heavy ingest 풀스로틀) → `kubectl apply -f 20-scenarios/OS-16-k6-light-search/`<br/>6 VU × 30분, VU 당 5~15s 간격 range/bool/match 쿼리 | ★ **p95 < 5,000ms**, p99 < 10,000ms, fail < 1%, total reqs ~ 720~2,160 | `LIGHT_SEARCH_VUS` (3/6/12), `LIGHT_SEARCH_DURATION` (30m/1h/2h), query 패턴 (range/bool/match), 동시 ingest 강도 (flog replicas 3/10) | OS heap, shard/replica 수, **indexing/search thread pool 분리** 설정, OS-01/OS-14 동시 가동 여부 | ★ **핵심 시나리오** — 운영 적용 가능 여부의 1차 판단 기준. 단독 실행은 무의미 (heavy ingest 가 동시여야 운영 패턴 재현). 실패 시: thread pool 분리, replica 증설, query cache 튜닝. |

## 통제변수 점검 (실험 시작 전)

| 항목 | 명령 | 정상 |
|------|------|------|
| OS heap | `curl -u admin:admin $OS/_nodes/stats/jvm \| jq '.nodes[].jvm.mem.heap_max_in_bytes'` | 환경 일관 (예: 4 GB) |
| shard 수 | `curl -u admin:admin $OS/_cat/shards/<index>` | 시나리오 간 동일 |
| refresh_interval | `curl -u admin:admin $OS/<index>/_settings \| jq '..refresh_interval'` | `"1s"` (기본) |
| total_fields.limit | `curl -u admin:admin $OS/_index_template/<name> \| jq` | 시나리오 의도와 일치 |
| 동시 가동 부하 | `kubectl -n load-test get deploy,job -l role=load-generator` | 시나리오별 의도와 일치 |
| network RTT | `kubectl -n load-test run --rm -it tmp --image=loadtest-tools:0.1.1 -- ping -c 5 opensearch-lt-node.monitoring.svc` | 일관 (< 1ms in-cluster) |

## 조작변수 변경 시 반영 절차

| 조작변수 | 위치 | 반영 명령 |
|----------|------|-----------|
| `OSB_WORKLOAD`, `OSB_BULK_SIZE`, `OSB_CLIENTS` | `00-prerequisites/lt-config.yaml` | ConfigMap apply → Job 삭제/재생성 |
| `K6_SEARCH_VU_TARGET`, `K6_SEARCH_DURATION` | (위와 동일) | (위와 동일) |
| `LIGHT_SEARCH_VUS`, `LIGHT_SEARCH_DURATION` | `20-scenarios/OS-16-k6-light-search/scenario.yaml` 의 env | manifest edit → Job 재생성 |
| flog `replicas`, `LOGGEN_DELAY` | `10-load-generators/flog-loader.yaml` / `loggen-spark.yaml` | manifest edit → `kubectl apply` |
| OS index template의 `dynamic` / `total_fields.limit` | `curl -X PUT $OS/_index_template/...` | OS API 직접 |

## 시나리오 간 의존성 그래프

```
                ┌──────────────────────────────────────┐
                │  사전: opensearch-creds Secret +     │
                │        kube-prometheus-stack +       │
                │        opensearch + fluent-bit       │
                └────────────────┬─────────────────────┘
                                 │
        ┌────────────────────────┼─────────────────────┐
        │                        │                     │
   ┌────▼────┐            ┌──────▼──────┐       ┌─────▼─────┐
   │ OS-01   │            │ flog        │       │ loggen-   │
   │ (단독)  │            │ (FB ingest) │       │ spark     │
   └─────────┘            └──────┬──────┘       │ (OS-14)   │
                                 │              └─────┬─────┘
                                 │                    │
                                 ▼                    ▼
                          ┌──────────┐         ┌──────────┐
                          │ OS-02    │  ┌──────► OS-16    │
                          │ (단독    │  │      │ (heavy   │
                          │  stress) │  │      │  ingest  │
                          └──────────┘  │      │  동시)   │
                                        │      └──────────┘
                                        │
                                  (OS-01 도 동시 가동 권장)
```

- **OS-01** : 단독 실행. 다른 부하 가동 시 측정 오염.
- **OS-02** : 사전에 인덱스 채움 (flog 10분+) 필요. 그 외 ingest 는 가동 안 함.
- **OS-14** : 부하 발생기 자체가 시나리오. 30분 이상 누적해야 의미 있음.
- **OS-16** : 반드시 heavy ingest (flog + loggen-spark) 가 동시에 흘러야 함. 단독 실행은 무의미.

## 결과 기록 양식

```
실험 일시   : 2026-MM-DD HH:MM
시나리오    : OS-XX
조작변수    : K6_SEARCH_VU_TARGET=50, K6_SEARCH_DURATION=5m
통제변수    : OS heap=4GB, shard=3, replica=1, refresh=1s, ingest=off
결과 측정값 : p95=387ms, p99=974ms, fail=0.21%
판정        : ✅ PASS (모든 임계 충족)
비고        : -
```

## 관련 문서

- [01-test-plan.md](01-test-plan.md) — 시나리오 카탈로그 + 추천 실행 시퀀스
- [02-troubleshooting.md](02-troubleshooting.md) — OSB 실패, OOM, 401 등
- [03-result-verification.md](03-result-verification.md) — Grafana / kubectl / API 결과 확인
- [../../../docs/load-testing/01-opensearch-load-test.md](../../../docs/load-testing/01-opensearch-load-test.md) — OS 시나리오 원본 정의
