#!/usr/bin/env python3
"""Generate Grafana dashboard ConfigMap manifests for load-testing scenarios.

The dashboards are *data-driven*. For each component (OpenSearch, Fluent-bit,
Prometheus, node-exporter, kube-state-metrics) we declare every scenario from
the corresponding guide with its description and a small set of graph panels;
the helpers below lay them out in a grid with auto-computed y-coordinates.

Each scenario block contains:
  - a Grafana `row` separator with the scenario ID + title
  - a Markdown text panel that explains the scenario in Korean
  - 2-4 graph panels for the scenario's key metrics

Run:
    python3 gen.py > dashboards.yaml
"""
import json
import textwrap
from itertools import count

DS = "${datasource}"

# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------

_id = count(1)

def nid():
    return next(_id)

def panel(title, exprs, x, y, w=12, h=7, unit="short",
          panel_type="timeseries", description=""):
    return {
        "id": nid(),
        "type": panel_type,
        "title": title,
        "description": description,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": {"type": "prometheus", "uid": DS},
        "fieldConfig": {"defaults": {"unit": unit, "min": 0}, "overrides": []},
        "options": {"legend": {"showLegend": True, "displayMode": "list"},
                    "tooltip": {"mode": "multi"}},
        "targets": [
            {"refId": chr(65 + i), "datasource": {"type": "prometheus", "uid": DS},
             "expr": expr, "legendFormat": leg}
            for i, (expr, leg) in enumerate(exprs)
        ],
    }

def stat(title, expr, x, y, w=6, h=4, unit="short", description=""):
    return {
        "id": nid(), "type": "stat", "title": title, "description": description,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": {"type": "prometheus", "uid": DS},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"colorMode": "value", "graphMode": "area"},
        "targets": [{"refId": "A", "expr": expr,
                     "datasource": {"type": "prometheus", "uid": DS}}],
    }

def text_panel(content, x, y, w=24, h=10, title=""):
    return {
        "id": nid(), "type": "text", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": content},
    }

def row(title, y, collapsed=False):
    return {
        "id": nid(), "type": "row", "title": title, "collapsed": collapsed,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
    }

# ---------------------------------------------------------------------------
# Scenario layout helper
# ---------------------------------------------------------------------------

def scenario_block(y, scenario_id, title, desc, panels_2d, text_height=10):
    """Lay out one scenario as a list of panel dicts:
        - row separator
        - description text (full width, height=text_height)
        - 2D grid of panels [(title, exprs, w, h, unit, description, type), ...]

    Returns (panels, next_y).
    """
    out = [row(f"{scenario_id} — {title}", y)]
    out.append(text_panel(desc, 0, y + 1, w=24, h=text_height))
    cur_y = y + 1 + text_height
    cur_x = 0
    row_h = 0
    for spec in panels_2d:
        kind = spec[-1] if isinstance(spec[-1], str) and spec[-1] in ("stat", "timeseries") else "timeseries"
        if kind == "stat":
            t, expr, w, h, unit, desc_p = spec[:6]
            if cur_x + w > 24:
                cur_y += row_h
                cur_x = 0
                row_h = 0
            out.append(stat(t, expr, cur_x, cur_y, w=w, h=h, unit=unit, description=desc_p))
        else:
            t, exprs, w, h, unit, desc_p = spec[:6]
            if cur_x + w > 24:
                cur_y += row_h
                cur_x = 0
                row_h = 0
            out.append(panel(t, exprs, cur_x, cur_y, w=w, h=h, unit=unit, description=desc_p))
        cur_x += w
        row_h = max(row_h, h)
    cur_y += row_h
    return out, cur_y

# ---------------------------------------------------------------------------
# Scenario data — OpenSearch
# ---------------------------------------------------------------------------

OS_OVERVIEW = textwrap.dedent("""\
    ## 🔍 OpenSearch 부하 테스트 — 전 시나리오 대시보드

    **운영 워크로드 가정**: 200대 cluster (Spark/Trino/Airflow) 로그 ingest가 주, 검색은 6팀 간헐적.
    따라서 **인덱싱 폭격 패턴**과 **운영 작업 충돌**이 핵심이며, 검색 부하는 가벼운 통합 시나리오로 흡수합니다.

    | 시나리오 | 유형 | 매니페스트 / 도구 |
    |----------|------|-------------------|
    | OS-01 Bulk Indexing (baseline) | Load | `04-test-jobs/opensearch-benchmark.yaml` |
    | OS-03 Heavy Aggregation | Stress | k6 + agg query |
    | OS-04 Shard/Replica Scaling | Stress | dynamic settings 변경 |
    | OS-05 Soak 24h | Soak | OS-01 24h 유지 |
    | OS-07 Node Failure | Chaos | `kubectl delete pod` |
    | **OS-08** Sustained high ingest (200대 모사) | Load (new) | flog 다수 → FB → OS, 1h |
    | **OS-09** Spark startup burst (×30) | Spike (new) | `kubectl scale`로 flog replicas 급증 |
    | **OS-12** Refresh interval 튜닝 | Tuning (new) | `_settings.refresh_interval` 변경 비교 |
    | **OS-14** High-cardinality field | Stress (new) | loggen-spark Pod (task_attempt_id 주입) |
    | **OS-16** Heavy ingest + light search | Integration (new) | flog + k6 6 VUs 동시 |

    > 메트릭 출처: `prometheus-community/elasticsearch_exporter` (Job: `opensearch-exporter`).
""")

opensearch_blocks = [
    ("OS-01", "Bulk Indexing", textwrap.dedent("""\
        **목적**: opensearch-benchmark의 `geonames` 워크로드로 30분간 연속 bulk indexing → 인덱싱 처리량과 안정성 측정.

        **부하 프로파일**: bulk_size=5000, clients=16, 인덱싱 전용 procedure. **SLO**: ≥ 30,000 docs/s, reject < 0.1%, heap ≤ 75%.

        **튜닝**: heap 75%↑ → bulk_size↓ + refresh_interval↑; reject↑ → clients↓ + queue_size↑.
    """), [
        ("Indexing Rate (docs/s)",
         [("rate(elasticsearch_indices_indexing_index_total[1m])", "{{name}}")],
         12, 7, "ops", "노드별 초당 인덱싱. opensearch-benchmark 시작 후 상승 곡선이 보여야 함."),
        ("Indexing Latency avg",
         [("rate(elasticsearch_indices_indexing_index_time_seconds_total[1m]) / "
           "clamp_min(rate(elasticsearch_indices_indexing_index_total[1m]),1)", "{{name}}")],
         12, 7, "s", "문서당 평균 인덱싱 시간. 50ms↑ 지속이면 병목."),
        ("Bulk Reject Rate",
         [("rate(elasticsearch_thread_pool_rejected_count{type=\"write\"}[1m])", "{{name}}")],
         12, 7, "ops", "0 근접 유지가 정상."),
        ("Pending Cluster Tasks",
         [("elasticsearch_cluster_health_number_of_pending_tasks", "pending")],
         12, 7, "short", "master 대기 큐. 누적은 master 오버로드."),
    ]),
    # OS-02 was folded into OS-16 (heavy ingest + light search) since the real
    # workload has only ~6 teams searching intermittently — 50 VU was unrealistic.
    ("OS-03", "Heavy Aggregation", textwrap.dedent("""\
        **목적**: 대용량 집계 쿼리(`terms`, `histogram`)로 서버 측 메모리·연산 부하 측정. 초기 단계 트레이싱이 핵심.

        **부하 프로파일**: 별도 k6 스크립트(`/agg`)로 30분간 집계 부하. **SLO**: heap ≤ 75%, breaker tripped 0, GC count 안정.

        **튜닝**: heap 압박 → bucket 크기 제한 / scroll API 사용; breaker tripped → request limit 상향.
    """), [
        ("Heap Used %",
         [("elasticsearch_jvm_memory_used_bytes{area=\"heap\"} / elasticsearch_jvm_memory_max_bytes{area=\"heap\"} * 100", "{{name}}")],
         12, 7, "percent", "75%↑ 지속이면 GC 영향."),
        ("Circuit Breaker Tripped (cumulative)",
         [("elasticsearch_breakers_tripped", "{{name}} {{breaker}}")],
         12, 7, "short", "0 유지가 정상. 증가 시 쿼리/필드데이터 한계 도달."),
        ("Old GC Count",
         [("elasticsearch_jvm_gc_collection_seconds_count{gc=\"old\"}", "{{name}}")],
         12, 7, "short", "old gen GC가 빈번하면 heap 부족."),
        ("Search Open Contexts",
         [("elasticsearch_indices_search_open_contexts", "{{name}}")],
         12, 7, "short", "scroll 컨텍스트 누적 누수 감지."),
    ]),
    ("OS-04", "Shard / Replica Scaling", textwrap.dedent("""\
        **목적**: `number_of_replicas` 변경 또는 인덱스 추가/삭제로 shard relocation 발생 → 안정성과 처리량 영향 측정.

        **부하 프로파일**: 인덱싱 진행 중 dynamic settings 변경. **SLO**: relocating_shards 일시 증가 후 0 복귀, recovery time < 10분.

        **튜닝**: recovery 느림 → indices.recovery.max_bytes_per_sec↑; throughput 저하 → 동시 변경 회피.
    """), [
        ("Active vs Unassigned Shards",
         [("elasticsearch_cluster_health_active_shards", "active"),
          ("elasticsearch_cluster_health_unassigned_shards", "unassigned")],
         12, 7, "short", "single-node에서 unassigned는 replica 미배치 상태로 정상."),
        ("Relocating / Initializing Shards",
         [("elasticsearch_cluster_health_relocating_shards", "relocating"),
          ("elasticsearch_cluster_health_initializing_shards", "initializing")],
         12, 7, "short", "shard 이동·초기화 진행도. 부하 종료 시 0."),
        ("Indexing Rate (during scaling)",
         [("sum(rate(elasticsearch_indices_indexing_index_total[1m]))", "TPS")],
         12, 7, "ops", "scaling 중에도 인덱싱이 유지되는지."),
        ("Cluster Status (1=green)",
         [("elasticsearch_cluster_health_status{color=\"green\"}", "green")],
         12, 7, "short", "scaling 중 yellow→green 회복 시간."),
    ]),
    ("OS-05", "Soak 24h", textwrap.dedent("""\
        **목적**: OS-01 부하를 24시간 유지하며 메모리 누수, GC 빈도 변화, FD 누수 등 장기 안정성 검증.

        **부하 프로파일**: bulk_size 평균치 고정 24h. **SLO**: heap 패턴 안정, GC frequency monotonic 증가 없음, FD 안정.

        **튜닝**: heap drift → 메모리 누수 의심 → heap dump 분석; FD 증가 → connection pool/scroll 누수.
    """), [
        ("Heap Used % (24h trend)",
         [("elasticsearch_jvm_memory_used_bytes{area=\"heap\"} / elasticsearch_jvm_memory_max_bytes{area=\"heap\"} * 100", "{{name}}")],
         12, 7, "percent", "24h 추세에서 monotonic 상승 없어야 함."),
        ("GC Time s/s (long range)",
         [("rate(elasticsearch_jvm_gc_collection_seconds_sum[5m])", "{{name}} {{gc}}")],
         12, 7, "s", "long-range로 GC 부담 증가 추적."),
        ("Open File Descriptors",
         [("elasticsearch_process_open_files_count", "{{name}}")],
         12, 7, "short", "FD 누수 감지."),
        ("JVM Threads",
         [("elasticsearch_jvm_threads_count", "{{name}}")],
         12, 7, "short", "thread leak 감지."),
    ]),
    # OS-06 (×5 spike) was strengthened into OS-09 (×30 Spark startup wave).
    ("OS-07", "Node Failure (Chaos)", textwrap.dedent("""\
        **목적**: data node 1대 강제 종료 → red→yellow→green 회복 시간과 처리량 영향 측정.

        **부하 프로파일**: `kubectl delete pod opensearch-...-1`. **SLO**: green 회복 < 20분, 데이터 손실 0, 인덱싱 중단 < 1분.

        **튜닝**: 회복 느림 → recovery throttle 상향; 인덱싱 멈춤 → coordinator 노드 분리로 해결.
    """), [
        ("Cluster Status timeline",
         [("elasticsearch_cluster_health_status{color=\"green\"}", "green"),
          ("elasticsearch_cluster_health_status{color=\"yellow\"}", "yellow"),
          ("elasticsearch_cluster_health_status{color=\"red\"}", "red")],
         24, 7, "short", "0/1 timeline. green → yellow → green 패턴이어야 함."),
        ("Number of Nodes",
         [("elasticsearch_cluster_health_number_of_nodes", "nodes"),
          ("elasticsearch_cluster_health_number_of_data_nodes", "data nodes")],
         12, 7, "short", "노드 1대 down → 회복 가시화."),
        ("Unassigned Shards during failure",
         [("elasticsearch_cluster_health_unassigned_shards", "unassigned")],
         12, 7, "short", "spike 후 0 복귀."),
    ]),

    # ---- 신규: 운영 워크로드(200대 cluster log ingest) 맞춤 ----

    ("OS-08", "Sustained High Ingest (200대 모사)", textwrap.dedent("""\
        **목적**: 200대 cluster의 Spark/Trino/Airflow 로그를 흡수할 수 있는 **sustainable** TPS 정량화.

        **부하 프로파일**: flog `replicas` 단계적 증가(5→20→50→100→200) × 1시간 sustain. 운영 FB DS가 처리.
        **SLO**: 1시간 동안 reject 0, FB output_errors 0, OS heap ≤ 75%, segment count 안정.

        **튜닝**: bulk_size↓ + refresh_interval↑(OS-12), data 노드 증설, FB Workers↑.
    """), [
        ("Sustained Indexing TPS",
         [("sum(rate(elasticsearch_indices_indexing_index_total[1m]))", "TPS")],
         12, 7, "ops",
         "1시간 동안 일정 수준 유지되어야 함. 곡선이 점진적 하락이면 sustainable 한계 초과."),
        ("Bulk Reject (sustained)",
         [("sum(rate(elasticsearch_thread_pool_rejected_count{type=\"write\"}[1m]))", "rejects/s")],
         12, 7, "ops",
         "0 유지. 비제로 시점이 sustainable TPS 초과 신호."),
        ("Heap % (long range)",
         [("elasticsearch_jvm_memory_used_bytes{area=\"heap\"} / elasticsearch_jvm_memory_max_bytes{area=\"heap\"} * 100", "{{name}}")],
         12, 7, "percent",
         "75%↑ 지속이면 GC 영향. 곡선 평탄화가 정상."),
        ("Segment Count (merge keep up?)",
         [("elasticsearch_indices_segments_count", "{{name}}")],
         12, 7, "short",
         "segment 수가 무한 증가하면 merge가 못 따라옴 → throughput 저하."),
        ("FB Output Rate vs OS Indexing Rate (cross-check)",
         [("sum(rate(fluentbit_output_proc_records_total[1m]))", "FB out"),
          ("sum(rate(elasticsearch_indices_indexing_index_total[1m]))", "OS indexed")],
         24, 7, "ops",
         "두 곡선이 일치해야 손실 없음. FB가 더 많으면 누락."),
        ("FB Storage Backlog",
         [("sum(fluentbit_input_storage_chunks_busy_bytes)", "backlog bytes")],
         12, 7, "bytes",
         "지속 증가하면 OS가 따라오지 못해 FB filesystem buffer 누적."),
        ("FB Output Retries",
         [("sum(rate(fluentbit_output_retries_total[1m]))", "retries/s")],
         12, 7, "ops",
         "비제로 = OS bulk reject가 발생하고 있음."),
    ]),

    ("OS-09", "Spark Job Startup Burst (×30)", textwrap.dedent("""\
        **목적**: Spark/Airflow 작업 일제 시작 시 평소 대비 ×30 spike → backpressure·복구 검증.

        **부하 프로파일**: 5분 평균(replicas=3) → 4분 × 30배(replicas=90) → 5분 평균.
        **SLO**: spike 동안 drop=0 (FB filesystem buffer 사용), spike 종료 후 1분 내 backlog 소진, OS green 유지.

        **튜닝**: drop 발생 → FB `Mem_Buf_Limit`↑·`storage.type=filesystem` (필수); OS reject burst → coordinator 분리.
    """), [
        ("Indexing TPS (spike profile)",
         [("sum(rate(elasticsearch_indices_indexing_index_total[1m]))", "OS TPS"),
          ("sum(rate(fluentbit_input_records_total[1m]))", "FB input"),
          ("sum(rate(fluentbit_output_proc_records_total[1m]))", "FB output")],
         24, 8, "ops",
         "spike 곡선. FB input은 즉시 ↑, FB output은 OS 한계까지 ↑, 차이는 buffer 누적."),
        ("Bulk Reject during burst",
         [("sum(rate(elasticsearch_thread_pool_rejected_count{type=\"write\"}[1m]))", "rejects/s")],
         12, 7, "ops",
         "spike 중 burst 후 즉시 0 복귀가 정상."),
        ("FB Storage Backlog (spike + drain)",
         [("sum(fluentbit_input_storage_chunks_busy_bytes)", "backlog")],
         12, 7, "bytes",
         "spike 중 누적 → spike 종료 후 단조 감소가 정상."),
        ("Heap % during burst",
         [("elasticsearch_jvm_memory_used_bytes{area=\"heap\"} / elasticsearch_jvm_memory_max_bytes{area=\"heap\"} * 100", "{{name}}")],
         12, 7, "percent",
         "spike 시 일시 상승 후 정상 회복."),
        ("Cluster Status (must stay green)",
         [("elasticsearch_cluster_health_status{color=\"green\"}", "green=1")],
         12, 7, "short",
         "burst 중에도 green 유지가 합격 기준."),
    ]),

    ("OS-12", "Refresh Interval 튜닝 비교", textwrap.dedent("""\
        **목적**: `refresh_interval`을 1s(default) vs 30s vs 60s로 바꾸며 동일 부하에서 throughput·검색 가시성 trade-off 측정.

        **부하 프로파일**: 동일한 OS-08 부하(예: replicas=50, 30분)를 3차례 실행. 각 실행 전 `_settings`로 refresh_interval 변경.
        **SLO**: 30s/60s 설정에서 1s 대비 indexing TPS ≥ +30%, 검색 lag ≤ 60s.

        **튜닝 적용 명령**:
        ```
        kubectl exec opensearch-lt-node-0 -- curl -X PUT $OPENSEARCH_URL/logs-fb-*/_settings \\
          -H 'Content-Type: application/json' -d '{"index": {"refresh_interval": "30s"}}'
        ```
    """), [
        ("Indexing Rate (compare across runs)",
         [("sum(rate(elasticsearch_indices_indexing_index_total[1m]))", "TPS")],
         12, 7, "ops",
         "각 refresh_interval 설정 구간을 시간 범위로 비교."),
        ("Refresh Operations Rate",
         [("rate(elasticsearch_indices_refresh_total[1m])", "{{name}}")],
         12, 7, "ops",
         "refresh_interval ↑ 시 이 곡선이 떨어져야 함."),
        ("Refresh Time spent (s/s)",
         [("rate(elasticsearch_indices_refresh_time_seconds_total[1m])", "{{name}}")],
         12, 7, "s",
         "refresh에 쓰인 시간 비율. 높으면 indexing 시간 잠식."),
        ("Segment Count (interval ↑ → segments↓)",
         [("elasticsearch_indices_segments_count", "{{name}}")],
         12, 7, "short",
         "refresh_interval 키울수록 더 적은 segment로 더 큰 chunk."),
    ]),

    ("OS-14", "High-Cardinality Field (Spark task_attempt_id)", textwrap.dedent("""\
        **목적**: Spark `task_attempt_id`, Airflow `dag_run_id` 같은 고유값 keyword가 매핑·cluster state에 미치는 압박 측정.

        **부하 프로파일**: `loggen-spark` Pod (ConfigMap의 Python 스크립트, UUID를 task_attempt_id로 주입) 30분.
        **SLO**: 매핑 필드 수 < 1000, master heap ≤ 70%, cluster state size 안정.

        **튜닝**: `index.mapping.total_fields.limit` 설정, `dynamic: strict`로 매핑 폭증 방어, 운영 ILM에서 매핑 reset 주기 단축.
    """), [
        ("Indices Memory Usage (proxy for fielddata)",
         [("elasticsearch_indices_fielddata_memory_size_bytes", "{{name}}")],
         12, 7, "bytes",
         "fielddata 메모리. high-card 누적 시 증가."),
        ("Indices Memory: total",
         [("elasticsearch_indices_segments_memory_bytes", "{{name}}")],
         12, 7, "bytes",
         "segment 전체 메모리. high-card term이 누적."),
        ("Active Indices",
         [("count(elasticsearch_index_stats_health) or vector(0)", "active indices")],
         12, 7, "short",
         "필드 수 직접 측정은 어려우나, 인덱스 수 / 누적 사이즈로 영향 추적."),
        ("OS Heap %",
         [("elasticsearch_jvm_memory_used_bytes{area=\"heap\"} / elasticsearch_jvm_memory_max_bytes{area=\"heap\"} * 100", "{{name}}")],
         12, 7, "percent",
         "매핑/state 부담은 heap에 직접 반영."),
        ("Pending Cluster Tasks (master 부담)",
         [("elasticsearch_cluster_health_number_of_pending_tasks", "pending")],
         24, 7, "short",
         "master에 매핑 업데이트 큐가 쌓이면 indexing 멈춤."),
    ]),

    ("OS-16", "Heavy Ingest + Light Search (운영 통합)", textwrap.dedent("""\
        **목적**: 가장 운영 현실적인 시나리오 — 200대 ingest 부하 중 6팀 간헐적 검색이 SLO 만족하는지 검증.

        **부하 프로파일**: OS-08 동등 ingest (sustained) 진행 중 k6 6 VU `last 1h` range query 30분 동시 실행.
        **SLO**: indexing TPS ≥ OS-08 단독 대비 95%, 검색 p95 ≤ 5s, 검색 error rate < 1%.

        **튜닝**: search 영향 시 → coordinator 노드 분리; range query 느림 → recording rule 도입 (Prom 측), shard 적정화.
    """), [
        ("Indexing TPS (during light search)",
         [("sum(rate(elasticsearch_indices_indexing_index_total[1m]))", "TPS")],
         12, 7, "ops",
         "OS-08 단독 실행과 비교 — drop이 5%를 넘으면 search가 ingest에 영향."),
        ("Light Search Rate",
         [("rate(elasticsearch_indices_search_query_total[1m])", "{{name}}")],
         12, 7, "ops",
         "k6 6 VU 부하 곡선 (~6 qps)."),
        ("Search Latency avg",
         [("rate(elasticsearch_indices_search_query_time_seconds_total[1m]) / "
           "clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)", "{{name}}")],
         12, 7, "s",
         "p95/p99는 k6 stdout 결과 참조 (서버 평균은 꼬리 지연 가림)."),
        ("Active Search/Write Threads",
         [("elasticsearch_thread_pool_active_count{type=\"search\"}", "search {{name}}"),
          ("elasticsearch_thread_pool_active_count{type=\"write\"}", "write {{name}}")],
         12, 7, "short",
         "두 thread pool 모두 활성. write가 우선이면 search 지연."),
    ]),
]

# ---------------------------------------------------------------------------
# Scenario data — Fluent-bit
# ---------------------------------------------------------------------------

FB_OVERVIEW = textwrap.dedent("""\
    ## 🪵 Fluent-bit 부하 테스트 — 전 시나리오 대시보드

    DaemonSet 동작 환경에서 단일 인스턴스 처리 한계, 출력 장애 복구, 멀티라인 파싱, 스파이크/소크/대용량 라인을 모두 다룹니다.

    | 시나리오 | 유형 | 도구 |
    |----------|------|------|
    | FB-01 단일 Pod throughput ceiling | Stress | flog 고밀도 |
    | FB-02 정상 운영 부하 | Load | flog 평균값 |
    | FB-03 Output 장애 주입 | Chaos | OpenSearch 일시 다운 |
    | FB-04 멀티라인 스택트레이스 | Load | 멀티라인 generator |
    | FB-05 로그 버스트 spike | Spike | flog rate 급증 |
    | FB-06 Soak 24h | Soak | flog 24h 유지 |
    | FB-07 대용량 로그(line=16KB) | Stress | flog `--byte-size` |

    > 메트릭 출처: Fluent-bit `/api/v2/metrics/prometheus` (Job: `fluent-bit-lt`).
""")

fluent_blocks = [
    ("FB-01", "단일 Pod throughput ceiling", textwrap.dedent("""\
        **목적**: 단일 Fluent-bit Pod가 흘려보낼 수 있는 최대 라인/초 측정.

        **부하 프로파일**: flog `-d 100us` 무한 루프, replicas로 노드별 부하 조절. **SLO**: per-pod ≥ 50,000 lines/s, drop=0.

        **튜닝**: drop → Mem_Buf_Limit↑, storage.type=filesystem; CPU throttling → Workers↑, filter 단순화.
    """), [
        ("Input Records Rate per pod",
         [('sum by (pod) (rate(fluentbit_input_records_total[1m]))', "{{pod}}")],
         12, 7, "ops", "tail input이 초당 읽은 라인 수."),
        ("Output Processed Rate",
         [('sum by (pod, name) (rate(fluentbit_output_proc_records_total[1m]))', "{{pod}} {{name}}")],
         12, 7, "ops", "input과 차이 = drop/buffer 누적."),
        ("CPU Usage",
         [('rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}[1m])', "{{pod}}")],
         12, 7, "percentunit", "limit 근접 시 throttling."),
        ("Memory Working Set",
         [('container_memory_working_set_bytes{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}', "{{pod}}")],
         12, 7, "bytes", "limit 70% 이내 유지."),
    ]),
    ("FB-02", "정상 운영 부하", textwrap.dedent("""\
        **목적**: 1시간 동안 평균 운영 부하를 가해 buffer 거동·자원 안정성 검증.

        **부하 프로파일**: flog `-d 500us`, replicas=3 (or 평균값). **SLO**: CPU/RSS ≤ limit 70%, buffer 누적 없음.

        **튜닝**: buffer 누적 → output Workers↑; output 응답 지연 → backoff/retry 정책.
    """), [
        ("Input/Output Rate Comparison",
         [('sum(rate(fluentbit_input_records_total[1m]))', "input"),
          ('sum(rate(fluentbit_output_proc_records_total[1m]))', "output")],
         12, 7, "ops", "두 곡선이 거의 일치해야 정상."),
        ("Storage Backlog (filesystem buffer)",
         [('fluentbit_input_storage_chunks_busy_bytes', "{{name}} {{pod}}")],
         12, 7, "bytes", "filesystem buffer 누적. 출력 정상 시 0 근처."),
    ]),
    ("FB-03", "Output 장애 주입 (Chaos)", textwrap.dedent("""\
        **목적**: OpenSearch를 일시 다운시킨 뒤 Fluent-bit의 재시도 / filesystem buffer 적재 / 자동 복구 검증.

        **부하 프로파일**: 일정 부하 중 `helm uninstall opensearch-lt`. **SLO**: 데이터 손실 0, 복구 후 backlog 자동 소진.

        **튜닝**: backlog 무한 증가 → storage.total_limit_size 설정; retry 폭주 → backoff 조정.
    """), [
        ("Output Errors",
         [('sum by (name) (rate(fluentbit_output_errors_total[1m]))', "{{name}}")],
         12, 7, "ops", "장애 시 spike, 복구 후 0."),
        ("Retries vs Retries-Failed",
         [('sum by (name) (rate(fluentbit_output_retries_total[1m]))', "retries {{name}}"),
          ('sum by (name) (rate(fluentbit_output_retries_failed_total[1m]))', "failed {{name}}")],
         12, 7, "ops", "failed > 0이면 데이터 손실 의심."),
        ("Filesystem Buffer Growth",
         [('fluentbit_input_storage_chunks_busy_bytes', "{{name}} {{pod}}")],
         24, 7, "bytes", "장애 동안 누적 → 복구 시 감소."),
    ]),
    ("FB-04", "멀티라인 스택트레이스 (Parser Stress)", textwrap.dedent("""\
        **목적**: 자바 스택트레이스 같은 멀티라인 로그 비율 ↑ 시 parser 지연·CPU 사용률 측정.

        **부하 프로파일**: 멀티라인 generator (`tail multiline.parser` 활성). **SLO**: parse 지연 ≤ 평소 ×1.5.

        **튜닝**: 정규식 단순화, multiline.parser 최적화, Mem_Buf_Limit↑.
    """), [
        ("CPU per pod (parser load)",
         [('rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}[1m])', "{{pod}}")],
         12, 7, "percentunit", "정규식 오버헤드를 CPU로 측정."),
        ("Output Throughput (Bps)",
         [('sum by (name) (rate(fluentbit_output_proc_bytes_total[1m]))', "{{name}}")],
         12, 7, "Bps", "처리 바이트율로 throughput 비교."),
    ]),
    ("FB-05", "로그 버스트 (Spike)", textwrap.dedent("""\
        **목적**: 평소 대비 ×30 ~ ×40 spike 시 backpressure·drop 거동 관찰.

        **부하 프로파일**: 5분 평균 → 4분 × 30배 → 5분 평균. **SLO**: drop=0 (filesystem buffer 사용), 회복 후 backlog 소진.

        **튜닝**: drop → Mem_Buf_Limit↑ + storage.type=filesystem; output 한계 → Workers↑ + bulk size↑.
    """), [
        ("Input Rate (spike profile)",
         [('sum(rate(fluentbit_input_records_total[1m]))', "input")],
         24, 7, "ops", "spike 곡선 가시화."),
        ("Output Rate (during spike)",
         [('sum(rate(fluentbit_output_proc_records_total[1m]))', "output")],
         12, 7, "ops", "input과 차이 = buffer."),
        ("Storage Backlog (during spike)",
         [('fluentbit_input_storage_chunks_busy_bytes', "{{name}} {{pod}}")],
         12, 7, "bytes", "spike 중 누적, 평상시 0 복귀."),
    ]),
    ("FB-06", "Soak 24h", textwrap.dedent("""\
        **목적**: 평균 부하 24시간 유지하여 RSS drift, FD 누수, retry 누적 없음 확인.

        **부하 프로파일**: flog 24h. **SLO**: RSS 안정, retry 누적 0 유지.

        **튜닝**: RSS drift → Mem_Buf_Limit 조정; retry 누적 → output 안정성 점검.
    """), [
        ("RSS over time",
         [('container_memory_working_set_bytes{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}', "{{pod}}")],
         12, 7, "bytes", "monotonic 상승은 누수."),
        ("Retries cumulative",
         [('fluentbit_output_retries_total', "{{pod}} {{name}}")],
         12, 7, "short", "장기 누적량. 0 또는 천천히 증가가 정상."),
    ]),
    ("FB-07", "대용량 로그 (1 line = 16 KB)", textwrap.dedent("""\
        **목적**: 라인 크기 ↑ 시 throughput·CPU·네트워크 대역 사용 변화.

        **부하 프로파일**: flog `-b 16K`. **SLO**: bytes/s ≥ 평소 ×n, CPU ≤ limit 70%.

        **튜닝**: 네트워크 포화 → output bulk size 조정; CPU 과부하 → flush 간격 조정.
    """), [
        ("Output Throughput (Bps)",
         [('sum by (name) (rate(fluentbit_output_proc_bytes_total[1m]))', "{{name}}")],
         12, 7, "Bps", "바이트율 — 라인 크기 ↑ 시 핵심 지표."),
        ("Avg Bytes per Record",
         [('sum(rate(fluentbit_input_bytes_total[1m])) / clamp_min(sum(rate(fluentbit_input_records_total[1m])),1)', "avg bytes/line")],
         12, 7, "bytes", "라인 평균 크기 — flog `-b` 효과 검증."),
    ]),
]

# ---------------------------------------------------------------------------
# Scenario data — Prometheus
# ---------------------------------------------------------------------------

PR_OVERVIEW = textwrap.dedent("""\
    ## 📊 Prometheus 부하 테스트 — 전 시나리오 대시보드

    Prometheus의 수집(Scrape), 저장(TSDB), 질의(PromQL) 세 축을 분리해 한계 용량과 안정성을 측정합니다.

    | 시나리오 | 유형 | 도구 |
    |----------|------|------|
    | PR-01 수집 타깃 수 증가 | Stress | avalanche replicas↑ |
    | PR-02 Active series 1M→5M | Stress | avalanche `--series-count` |
    | PR-03 질의 동시성 | Load | k6 PromQL |
    | PR-04 장기 Range Query | Load | k6 with 30d step |
    | PR-05 Cardinality Spike | Spike | avalanche label 폭증 |
    | PR-06 WAL replay 복구 | Chaos | Pod restart |
    | PR-07 Soak 24h | Soak | 평균 부하 유지 |

    > 100만 series ≈ 3~5 GiB heap. 일일 디스크 ≈ `series × samples/sec × 2B × 86400`.
""")

prom_blocks = [
    ("PR-01", "수집 타깃 수 증가", textwrap.dedent("""\
        **목적**: 합성 endpoint(avalanche) 수를 늘리며 scrape 단계 병목 측정.

        **부하 프로파일**: avalanche replicas 점진 증가. **SLO**: scrape duration p95 ≤ 1s, scrape timeout 0.

        **튜닝**: scrape timeout → scrape_timeout↑ 또는 target relabel 분산.
    """), [
        ("Targets UP", "count(up==1)", 6, 4, "short",
         "현재 health=up target 수.", "stat"),
        ("Targets DOWN", "count(up==0)", 6, 4, "short",
         "0 유지가 정상.", "stat"),
        ("Total Scrapes /s", "sum(rate(prometheus_target_scrape_pool_targets[1m]))", 12, 4, "ops",
         "전체 scrape 부담.", "stat"),
        ("Scrape Duration p95 by job",
         [('histogram_quantile(0.95, sum by (le, job) (rate(prometheus_target_interval_length_seconds_bucket[5m])))', "{{job}}")],
         12, 7, "s", "interval 분포 p95."),
        ("Samples Scraped per Target",
         [("scrape_samples_scraped", "{{job}} {{instance}}")],
         12, 7, "short", "1회 scrape의 샘플 수."),
    ]),
    ("PR-02", "Active Series 확장", textwrap.dedent("""\
        **목적**: avalanche `--series-count`/`replicas` 증가로 active series 폭증 → 메모리/저장 압박 측정.

        **부하 프로파일**: 0.5M → 5M series 단계 ramp. **SLO**: RSS ≤ pod limit 80%, compactions_failed 0.

        **튜닝**: RSS ↑ → relabel drop / allowlist; cardinality 폭증 → metric_relabel_configs.
    """), [
        ("Active Head Series", "prometheus_tsdb_head_series", 8, 4, "short",
         "현재 active series.", "stat"),
        ("Series Created /5m", "rate(prometheus_tsdb_head_series_created_total[5m])", 8, 4, "ops",
         "시리즈 생성률.", "stat"),
        ("Process RSS", 'process_resident_memory_bytes{job="kps-prometheus"}', 8, 4, "bytes",
         "프로세스 메모리.", "stat"),
        ("Head Series over time",
         [("prometheus_tsdb_head_series", "head series")],
         12, 7, "short", "시간 경과에 따른 series 곡선."),
        ("Series Churn",
         [("rate(prometheus_tsdb_head_series_created_total[5m])", "created"),
          ("rate(prometheus_tsdb_head_series_removed_total[5m])", "removed")],
         12, 7, "ops", "created > removed 지속이면 누적."),
    ]),
    ("PR-03", "PromQL 동시성", textwrap.dedent("""\
        **목적**: k6로 동시 PromQL 쿼리 부하 → query engine·HTTP handler 거동 측정.

        **부하 프로파일**: k6 20 VUs × 5분, 7가지 쿼리 무작위. **SLO**: http_req_duration p95 ≤ 2s, error rate < 1%.

        **튜닝**: query_max_concurrency↑, query_max_samples 제한, recording rule 도입.
    """), [
        ("Query HTTP Rate",
         [("rate(prometheus_http_requests_total{handler=~\"/api/v1/query.*\"}[1m])", "{{handler}}")],
         12, 7, "ops", "QPS 트렌드."),
        ("Engine Query Duration p95 by slice",
         [('histogram_quantile(0.95, sum by (le, slice) (rate(prometheus_engine_query_duration_seconds_bucket[5m])))', "p95 {{slice}}")],
         12, 7, "s", "PromQL 단계별 분해."),
        ("Concurrent Queries",
         [("prometheus_engine_queries", "active"),
          ("prometheus_engine_queries_concurrent_max", "max")],
         12, 7, "short", "동시 쿼리 수 / 한계."),
    ]),
    ("PR-04", "장기 Range Query (30d)", textwrap.dedent("""\
        **목적**: 30일 range 쿼리 시 IO·메모리·완료 시간 측정.

        **부하 프로파일**: k6 step=`30d` range query. **SLO**: p95 ≤ 5s, OOM 없음.

        **튜닝**: 너무 넓은 range → step↑ 또는 recording rule; 메모리 → query_max_samples↓.
    """), [
        ("Range Query Duration",
         [('histogram_quantile(0.95, sum by (le) (rate(prometheus_http_request_duration_seconds_bucket{handler="/api/v1/query_range"}[5m])))', "p95"),
          ('histogram_quantile(0.99, sum by (le) (rate(prometheus_http_request_duration_seconds_bucket{handler="/api/v1/query_range"}[5m])))', "p99")],
         12, 7, "s", "range query 응답 분포."),
        ("Engine Samples Touched",
         [("rate(prometheus_engine_query_samples_total[1m])", "samples/s")],
         12, 7, "ops", "쿼리당 샘플 처리량."),
    ]),
    ("PR-05", "Cardinality Spike", textwrap.dedent("""\
        **목적**: 라벨 폭증 시 head_series·메모리 충격 관찰.

        **부하 프로파일**: avalanche `--label-count`↑ + `--series-interval` 짧게 → churn 발생. **SLO**: RSS ≤ limit 80%, churn 안정 회복.

        **튜닝**: relabel drop, allowlist, metric_relabel_configs.
    """), [
        ("Series Created vs Removed (churn)",
         [("rate(prometheus_tsdb_head_series_created_total[5m])", "created"),
          ("rate(prometheus_tsdb_head_series_removed_total[5m])", "removed")],
         12, 7, "ops", "created spike → 감소 패턴."),
        ("Process RSS (during spike)",
         [('process_resident_memory_bytes{job="kps-prometheus"}', "RSS")],
         12, 7, "bytes", "spike 시 일시적 상승."),
    ]),
    ("PR-06", "WAL Replay 복구 (Chaos)", textwrap.dedent("""\
        **목적**: Prometheus Pod 재시작 시 WAL replay 시간·메모리·startup 안정성 측정.

        **부하 프로파일**: `kubectl delete pod prometheus-...-0`. **SLO**: replay 시간 < 5분, replay 중 메모리 spike 정상 회복.

        **튜닝**: replay 느림 → SSD/IO class 상향; replay 중 OOM → memory limit 상향.
    """), [
        ("Process Start Time (Restart 감지)",
         [("process_start_time_seconds{job=\"kps-prometheus\"}", "start_time")],
         12, 7, "short", "재시작 시점 타임스탬프 변화."),
        ("WAL Truncate Duration",
         [("rate(prometheus_tsdb_wal_truncate_duration_seconds_sum[1m])", "truncate"),
          ("rate(prometheus_tsdb_wal_truncate_duration_seconds_count[1m])", "events")],
         12, 7, "s", "WAL 정리 비용."),
        ("RSS during replay",
         [('process_resident_memory_bytes{job="kps-prometheus"}', "RSS")],
         12, 7, "bytes", "replay 중 메모리 사용."),
    ]),
    ("PR-07", "Soak 24h", textwrap.dedent("""\
        **목적**: 평균 부하 24h 유지하며 메모리/디스크 monotonic 증가 없음 확인.

        **부하 프로파일**: 평소 부하 24h. **SLO**: 메모리/디스크 증가율 ≤ 일평균.

        **튜닝**: retention↓, compaction 실패 시 디스크 여유 확보.
    """), [
        ("RSS 24h Trend",
         [('process_resident_memory_bytes{job="kps-prometheus"}', "RSS")],
         12, 7, "bytes", "24h monotonic 상승은 누수."),
        ("Disk Usage (TSDB)",
         [("prometheus_tsdb_storage_blocks_bytes", "block bytes")],
         12, 7, "bytes", "block 디스크 사용."),
        ("Compactions ok / failed",
         [("rate(prometheus_tsdb_compactions_total[5m])", "ok"),
          ("rate(prometheus_tsdb_compactions_failed_total[5m])", "failed")],
         24, 7, "ops", "failed > 0이면 디스크 부족 등."),
    ]),
]

# ---------------------------------------------------------------------------
# Scenario data — node-exporter
# ---------------------------------------------------------------------------

NE_OVERVIEW = textwrap.dedent("""\
    ## 🖥️ node-exporter 부하 테스트 — 전 시나리오 대시보드

    DaemonSet 동작 환경에서 collector 비용·고빈도 scrape·textfile 메트릭·디스크/CPU 포화 영향을 측정합니다.

    | 시나리오 | 유형 | 도구 |
    |----------|------|------|
    | NE-01 기본 collector scrape 비용 | Baseline | self |
    | NE-02 고빈도 scrape (5s) | Stress | hey 50c × 50qps × 2분 |
    | NE-03 textfile 메트릭 1만 개 | Load | textfile collector |
    | NE-04 마운트 포인트 50+ | Load | mock mounts |
    | NE-05 노드 CPU 90% 포화 | Stress | stress-ng |
    | NE-06 Disk IO 포화 | Stress | fio |
    | NE-07 Soak 24h | Soak | 평소 부하 24h |
""")

node_blocks = [
    ("NE-01", "기본 collector scrape 비용 (Baseline)", textwrap.dedent("""\
        **목적**: 부하 없는 상태에서 단일 scrape의 자원 비용·시리즈 수 베이스라인 캡처.

        **부하 프로파일**: 부하 없음. **SLO**: CPU ≤ 100m, RSS ≤ 50 MiB, 시리즈 ≤ 2,000.

        **튜닝**: 시리즈 과다 → 불필요 collector 비활성화 (`--no-collector.*`).
    """), [
        ("Scrape Duration",
         [('scrape_duration_seconds{job="node-exporter"}', "{{instance}}")],
         12, 7, "s", "Prometheus가 측정한 scrape 시간."),
        ("Samples Scraped",
         [('scrape_samples_scraped{job="node-exporter"}', "{{instance}}")],
         12, 7, "short", "1회 scrape의 샘플 수."),
        ("Per-collector Duration",
         [("node_scrape_collector_duration_seconds", "{{collector}}")],
         24, 8, "s", "collector별 비용 분해."),
    ]),
    ("NE-02", "고빈도 scrape (5s)", textwrap.dedent("""\
        **목적**: scrape interval을 짧게(5s) 또는 외부 hey 부하 → CPU·응답시간 영향.

        **부하 프로파일**: hey 50c × 50qps × 2분 (`/metrics` HTTP). **SLO**: p95 ≤ 300 ms, scrape timeout 0.

        **튜닝**: 응답 지연 → `--web.max-requests`↑; CPU throttling → 불필요 collector off.
    """), [
        ("node-exporter CPU",
         [('rate(process_cpu_seconds_total{job="node-exporter"}[1m])', "{{instance}}")],
         12, 7, "percentunit", "CPU 사용률(코어 단위)."),
        ("Scrape Duration (high-freq)",
         [('scrape_duration_seconds{job="node-exporter"}', "{{instance}}")],
         12, 7, "s", "interval 단축 시 영향."),
    ]),
    ("NE-03", "textfile 메트릭 1만 개", textwrap.dedent("""\
        **목적**: textfile collector를 통해 외부 메트릭 1만 개 주입 → scrape 시간·시리즈 수 증가 측정.

        **부하 프로파일**: hostPath에 1만 라인 .prom 파일. **SLO**: scrape duration ≤ 평소 ×2.

        **튜닝**: 텍스트파일 축소/삭제, 더 적은 라벨로 재구성.
    """), [
        ("Samples Scraped (with textfile)",
         [('scrape_samples_scraped{job="node-exporter"}', "{{instance}}")],
         12, 7, "short", "주입 후 곡선이 점프해야 함."),
        ("Scrape Duration",
         [('scrape_duration_seconds{job="node-exporter"}', "{{instance}}")],
         12, 7, "s", "duration 증가 정도 확인."),
        ("textfile collector duration",
         [("node_scrape_collector_duration_seconds{collector=\"textfile\"}", "{{instance}}")],
         24, 7, "s", "textfile collector 단독 비용."),
    ]),
    ("NE-04", "마운트 포인트 50+", textwrap.dedent("""\
        **목적**: filesystem collector가 처리해야 할 마운트 수 ↑ → collector 시간·시리즈 수 영향.

        **부하 프로파일**: bind mount 50+ 추가. **SLO**: filesystem collector ≤ 500 ms.

        **튜닝**: `--collector.filesystem.mount-points-exclude`로 NFS 등 제외.
    """), [
        ("filesystem collector duration",
         [("node_scrape_collector_duration_seconds{collector=\"filesystem\"}", "{{instance}}")],
         12, 7, "s", "마운트 수 ↑ 효과."),
        ("Samples Scraped",
         [('scrape_samples_scraped{job="node-exporter"}', "{{instance}}")],
         12, 7, "short", "filesystem 시리즈 증가."),
    ]),
    ("NE-05", "노드 CPU 90% 포화", textwrap.dedent("""\
        **목적**: 노드 자체 CPU 포화 시 node-exporter scrape 영향과 timeout 발생률 관찰.

        **부하 프로파일**: stress-ng로 노드 CPU 90%. **SLO**: scrape timeout 0건.

        **튜닝**: scrape_timeout↑, exporter Pod에 CPU request 보장.
    """), [
        ("Node CPU Usage",
         [('1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m]))', "{{instance}}")],
         12, 7, "percentunit", "노드 전체 CPU 사용률."),
        ("Scrape Duration during saturation",
         [('scrape_duration_seconds{job="node-exporter"}', "{{instance}}")],
         12, 7, "s", "CPU 포화 시 영향."),
    ]),
    ("NE-06", "Disk IO 포화 (fio)", textwrap.dedent("""\
        **목적**: 디스크 IO 포화 시 diskstats / filesystem collector 영향 측정.

        **부하 프로파일**: fio 100% util. **SLO**: diskstats collector duration 평소 ×2 이내.

        **튜닝**: `--no-collector.diskstats` 옵션 (운영에선 비권장).
    """), [
        ("Disk Reads/Writes",
         [("rate(node_disk_reads_completed_total[1m])", "reads {{device}}"),
          ("rate(node_disk_writes_completed_total[1m])", "writes {{device}}")],
         12, 7, "ops", "디스크 IO 곡선."),
        ("diskstats collector duration",
         [("node_scrape_collector_duration_seconds{collector=\"diskstats\"}", "{{instance}}")],
         12, 7, "s", "포화 시 영향."),
    ]),
    ("NE-07", "Soak 24h", textwrap.dedent("""\
        **목적**: 24시간 평균 부하에서 goroutine·FD·RSS 누수 없음 확인.

        **부하 프로파일**: 평소 scrape 24h. **SLO**: goroutine/FD 안정.

        **튜닝**: goroutine leak → 프로파일 분석.
    """), [
        ("Goroutines",
         [('go_goroutines{job="node-exporter"}', "{{instance}}")],
         12, 7, "short", "goroutine 누수 감지."),
        ("Open FDs",
         [('process_open_fds{job="node-exporter"}', "{{instance}}")],
         12, 7, "short", "FD 누수 감지."),
        ("RSS",
         [('process_resident_memory_bytes{job="node-exporter"}', "{{instance}}")],
         24, 7, "bytes", "메모리 누수 감지."),
    ]),
]

# ---------------------------------------------------------------------------
# Scenario data — kube-state-metrics
# ---------------------------------------------------------------------------

KSM_OVERVIEW = textwrap.dedent("""\
    ## 🧱 kube-state-metrics 부하 테스트 — 전 시나리오 대시보드

    K8s API 서버에 informer를 붙여 오브젝트 상태를 메트릭으로 노출하는 KSM이 대규모 클러스터에서 어떻게 확장되는지 측정합니다.

    | 시나리오 | 유형 | 도구 |
    |----------|------|------|
    | KSM-01 Baseline | Baseline | 현행 |
    | KSM-02 Pod 1만 개 (single-node 100) | Stress | kube-burner |
    | KSM-03 ConfigMap 5만 개 | Stress | kube-burner |
    | KSM-04 Namespace churn | Load | kube-burner |
    | KSM-05 Shard(`--total-shards`) | Load | StatefulSet |
    | KSM-06 Soak 24h | Soak | 유지 |
    | KSM-07 allowlist/denylist | Tuning | KSM 옵션 |

    > 오브젝트 1개당 시리즈 수는 리소스 종류별로 다름 (Pod가 가장 큼).
""")

ksm_blocks = [
    ("KSM-01", "Baseline", textwrap.dedent("""\
        **목적**: 부하 없이 클러스터 현행 오브젝트 수 / KSM RSS / 응답 시간 베이스라인 캡처.

        **부하 프로파일**: 부하 없음. **SLO**: /metrics p95 ≤ 2s, RSS ≤ pod limit 70%.
    """), [
        ("Pods total", "count(kube_pod_info)", 6, 4, "short",
         "전체 Pod 수.", "stat"),
        ("Deployments total", "count(kube_deployment_labels)", 6, 4, "short",
         "전체 Deployment 수.", "stat"),
        ("ConfigMaps total", "count(kube_configmap_info)", 6, 4, "short",
         "전체 ConfigMap 수.", "stat"),
        ("Services total", "count(kube_service_info)", 6, 4, "short",
         "전체 Service 수.", "stat"),
        ("KSM /metrics duration p95",
         [('histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="kube-state-metrics"}[5m])))', "p95")],
         12, 7, "s", "응답 시간 분포 p95."),
        ("KSM RSS",
         [('sum by (pod) (container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"})', "RSS")],
         12, 7, "bytes", "informer cache 메모리."),
    ]),
    ("KSM-02", "Pod 대량 생성", textwrap.dedent("""\
        **목적**: Pod 1만 개(또는 minikube 100) 생성 → KSM informer cache·응답 영향 관찰.

        **부하 프로파일**: kube-burner `jobIterations=10000` (minikube=100). **SLO**: /metrics p95 ≤ 2s, RSS ≤ limit 70%.

        **튜닝**: shard 도입, denylist로 불필요 메트릭 제거.
    """), [
        ("KSM /metrics p95",
         [('histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="kube-state-metrics"}[5m])))', "p95")],
         12, 7, "s", "Pod 증가에 따른 응답 시간 증가."),
        ("KSM RSS",
         [('sum by (pod) (container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"})', "RSS")],
         12, 7, "bytes", "오브젝트 수에 거의 선형 증가."),
        ("Total Pods vs kburner Pods",
         [("count(kube_pod_info)", "all"),
          ("count(kube_pod_info{namespace=~\"kburner.*\"})", "kburner")],
         12, 7, "short", "kube-burner 진행률."),
        ("API Server Request Rate",
         [('sum by (verb) (rate(apiserver_request_total[1m]))', "{{verb}}")],
         12, 7, "ops", "CREATE 폭증 가시화."),
    ]),
    ("KSM-03", "ConfigMap 대량 생성", textwrap.dedent("""\
        **목적**: ConfigMap 5만 개 생성 → KSM 메모리 / etcd 압박 관찰.

        **부하 프로파일**: kube-burner ConfigMap 생성. **SLO**: KSM RSS ≤ pod limit 70%, etcd 디스크 여유.

        **튜닝**: ConfigMap allowlist 제외, KSM `--resources` 한정.
    """), [
        ("ConfigMaps total",
         [("count(kube_configmap_info)", "configmaps")],
         12, 7, "short", "kube-burner 진행률."),
        ("KSM RSS",
         [('sum by (pod) (container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"})', "RSS")],
         12, 7, "bytes", "informer cache 영향."),
        ("etcd request latency p95",
         [('histogram_quantile(0.95, sum by (le, operation) (rate(etcd_request_duration_seconds_bucket[5m])))', "{{operation}}")],
         24, 7, "s", "etcd 응답 압박 (kps에서 etcd 활성화 필요)."),
    ]),
    ("KSM-04", "Namespace churn", textwrap.dedent("""\
        **목적**: namespace 생성/삭제 반복 → API 서버 LIST/WATCH 부담 측정.

        **부하 프로파일**: kube-burner namespace churn. **SLO**: API 서버 LIST 실패율 ≈ 0.

        **튜닝**: kube-burner `qps`/`burst`↓.
    """), [
        ("Namespaces total",
         [("count(kube_namespace_status_phase)", "namespaces")],
         12, 7, "short", "namespace 수 진동."),
        ("API Server LIST/WATCH rate",
         [('sum by (verb) (rate(apiserver_request_total{verb=~"LIST|WATCH"}[1m]))', "{{verb}}")],
         12, 7, "ops", "LIST/WATCH 부담."),
        ("API Server Errors (non-2xx)",
         [('sum by (code) (rate(apiserver_request_total{code!~"2.."}[1m]))', "{{code}}")],
         24, 7, "ops", "에러율."),
    ]),
    ("KSM-05", "Shard 구성", textwrap.dedent("""\
        **목적**: KSM `--total-shards`로 수평 분할 → 단일 인스턴스 부담 분산 검증.

        **부하 프로파일**: KSM StatefulSet replicas=N. **SLO**: 각 shard RSS 거의 동등, 누락 메트릭 없음.

        **튜닝**: shard 분배 불균형 → label/selector 점검.
    """), [
        ("KSM Pods (shards)",
         [("count(kube_pod_info{namespace=\"monitoring\",pod=~\"kps-kube-state-metrics.*\"})", "shards")],
         12, 4, "short", "현재 shard 인스턴스 수.", "stat"),
        ("Per-shard RSS",
         [('sum by (pod) (container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"})', "{{instance}}")],
         12, 7, "bytes", "shard별 메모리 분산."),
        ("Per-shard /metrics duration",
         [('histogram_quantile(0.95, sum by (le, instance) (rate(http_request_duration_seconds_bucket{job="kube-state-metrics"}[5m])))', "{{instance}}")],
         12, 7, "s", "shard별 응답 시간."),
    ]),
    ("KSM-06", "Soak 24h", textwrap.dedent("""\
        **목적**: 24시간 평균 부하에서 KSM RSS / API 서버 부담 안정성 검증.

        **부하 프로파일**: 클러스터 평소 부하 24h. **SLO**: RSS 안정, API 서버 응답 정상.
    """), [
        ("KSM RSS 24h",
         [('sum by (pod) (container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"})', "RSS")],
         12, 7, "bytes", "monotonic 상승 = 누수."),
        ("KSM goroutines",
         [('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"}[1m]))', "goroutines")],
         12, 7, "short", "goroutine leak 감지."),
    ]),
    ("KSM-07", "allowlist/denylist 튜닝", textwrap.dedent("""\
        **목적**: high-cardinality 메트릭을 제거 → 시리즈 수 / 메모리 감소 효과 측정.

        **부하 프로파일**: 동일 부하에서 allowlist/denylist 적용 전후 비교. **SLO**: series ≥ 30% 감소.

        **튜닝**: `kube_pod_labels` 등 라벨 폭증 메트릭 우선 제거.
    """), [
        ("Samples per Scrape (with allowlist)",
         [('scrape_samples_scraped{job="kube-state-metrics"}', "samples")],
         12, 7, "short", "튜닝 전후 비교."),
        ("KSM RSS (with allowlist)",
         [('sum by (pod) (container_memory_working_set_bytes{namespace="monitoring",pod=~".*kube-state-metrics.*",container="kube-state-metrics"})', "RSS")],
         12, 7, "bytes", "메모리 감소 효과."),
    ]),
]

# ---------------------------------------------------------------------------
# Build dashboards
# ---------------------------------------------------------------------------

def build_dashboard(uid, title, overview_md, blocks, overview_height=14):
    panels = [text_panel(overview_md, 0, 0, w=24, h=overview_height)]
    y = overview_height
    for sid, st, desc, panels_2d in blocks:
        block, y = scenario_block(y, sid, st, desc, panels_2d, text_height=8)
        panels.extend(block)
    return {
        "uid": uid, "title": title,
        "schemaVersion": 39, "version": 1, "editable": True,
        "tags": ["load-test"],
        "time": {"from": "now-1h", "to": "now"},
        "refresh": "30s",
        "templating": {"list": [{
            "name": "datasource", "type": "datasource", "query": "prometheus",
            "current": {"text": "Prometheus", "value": "Prometheus"},
            "label": "Datasource",
        }]},
        "panels": panels,
    }

# ---- Overview dashboard (lightweight) ----

OV_DESC = textwrap.dedent("""\
    ## 🧭 Load Test Overview — 부하 테스트 종합 헬스체크

    각 부하 테스트 시나리오 진행 중 한 화면에서 **전체 컴포넌트의 핵심 지표**를 확인하는 종합 대시보드입니다.

    | 컴포넌트 | 대시보드 | 시나리오 |
    |----------|----------|----------|
    | OpenSearch | [OpenSearch](/d/lt-opensearch) | OS-01 ~ OS-07 |
    | Fluent-bit | [Fluent-bit](/d/lt-fluent-bit) | FB-01 ~ FB-07 |
    | Prometheus | [Prometheus](/d/lt-prometheus) | PR-01 ~ PR-07 |
    | node-exporter | [node-exporter](/d/lt-node-exporter) | NE-01 ~ NE-07 |
    | kube-state-metrics | [kube-state-metrics](/d/lt-ksm) | KSM-01 ~ KSM-07 |

    > 자세한 운영 절차는 `docs/load-testing/06-test-execution-plan.md` 참조.
""")

def build_overview():
    panels = [text_panel(OV_DESC, 0, 0, w=24, h=14)]
    y = 14
    panels.extend([
        row("Cluster Health", y),
        stat("Targets UP",      'count(up==1)',        0,  y+1, w=4, unit="short", description="health=up"),
        stat("Targets DOWN",    'count(up==0)',        4,  y+1, w=4, unit="short", description="health=down"),
        stat("Active Series",   'prometheus_tsdb_head_series', 8, y+1, w=4, unit="short", description="현재 head series"),
        stat("Cluster Status",  'elasticsearch_cluster_health_status{color="green"}', 12, y+1, w=4, description="OS green=1"),
        stat("Indexing TPS",    'sum(rate(elasticsearch_indices_indexing_index_total[1m]))', 16, y+1, w=4, unit="ops"),
        stat("FB output rate",  'sum(rate(fluentbit_output_proc_records_total[1m]))', 20, y+1, w=4, unit="ops"),
    ])
    y += 5
    panels.append(row("Latency Summary", y))
    panels.append(panel("Search Latency (avg)",
                        [('rate(elasticsearch_indices_search_query_time_seconds_total[1m])/clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)', "{{name}}")],
                        0, y+1, unit="s"))
    panels.append(panel("PromQL p95",
                        [('histogram_quantile(0.95, sum by (le) (rate(prometheus_engine_query_duration_seconds_bucket[5m])))', "p95")],
                        12, y+1, unit="s"))
    y += 8
    panels.append(row("Saturation (load-test ns)", y))
    panels.append(panel("Pod Memory",
                        [('sum by (pod) (container_memory_working_set_bytes{namespace="load-test"})', "{{pod}}")],
                        0, y+1, unit="bytes"))
    panels.append(panel("Pod CPU",
                        [('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="load-test"}[1m]))', "{{pod}}")],
                        12, y+1, unit="percentunit"))
    y += 8
    panels.append(row("Errors", y))
    panels.append(panel("Output Errors / Bulk Rejects",
                        [('sum(rate(fluentbit_output_errors_total[1m]))', "fluent-bit out err"),
                         ('sum(rate(fluentbit_output_retries_total[1m]))', "fluent-bit retries"),
                         ('sum(rate(elasticsearch_thread_pool_rejected_count{type="write"}[1m]))', "OS write rejects")],
                        0, y+1, w=24, unit="ops"))
    return {
        "uid": "lt-overview", "title": "Load Test • Overview",
        "schemaVersion": 39, "version": 1, "editable": True,
        "tags": ["load-test"],
        "time": {"from": "now-30m", "to": "now"},
        "refresh": "30s",
        "templating": {"list": [{
            "name": "datasource", "type": "datasource", "query": "prometheus",
            "current": {"text": "Prometheus", "value": "Prometheus"},
            "label": "Datasource",
        }]},
        "panels": panels,
    }

# ---- ConfigMap wrapper ----

def configmap(name, dashboard, ns="monitoring"):
    return textwrap.dedent(f"""\
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: {name}
          namespace: {ns}
          labels:
            grafana_dashboard: "1"
        data:
          {name}.json: |-
        """) + textwrap.indent(json.dumps(dashboard, indent=2), "    ")

# ---- Emit ----

def main():
    out = "# Auto-generated by gen.py — DO NOT EDIT MANUALLY (run 'python3 gen.py > dashboards.yaml')\n---\n"
    out += configmap("dash-load-test-overview", build_overview()) + "\n---\n"
    out += configmap("dash-load-test-opensearch",
                     build_dashboard("lt-opensearch", "Load Test • OpenSearch (OS — log-ingest workload, 10 scenarios)",
                                     OS_OVERVIEW, opensearch_blocks)) + "\n---\n"
    out += configmap("dash-load-test-fluent-bit",
                     build_dashboard("lt-fluent-bit", "Load Test • Fluent-bit (FB-01~07)",
                                     FB_OVERVIEW, fluent_blocks)) + "\n---\n"
    out += configmap("dash-load-test-prometheus",
                     build_dashboard("lt-prometheus", "Load Test • Prometheus (PR-01~07)",
                                     PR_OVERVIEW, prom_blocks)) + "\n---\n"
    out += configmap("dash-load-test-node-exporter",
                     build_dashboard("lt-node-exporter", "Load Test • node-exporter (NE-01~07)",
                                     NE_OVERVIEW, node_blocks)) + "\n---\n"
    out += configmap("dash-load-test-ksm",
                     build_dashboard("lt-ksm", "Load Test • kube-state-metrics (KSM-01~07)",
                                     KSM_OVERVIEW, ksm_blocks))
    print(out)

if __name__ == "__main__":
    main()
