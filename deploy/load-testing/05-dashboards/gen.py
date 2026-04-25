#!/usr/bin/env python3
"""Generate Grafana dashboard ConfigMap manifests for load-testing scenarios.

Each dashboard starts with a Korean Markdown description panel that explains
the scenario, the tool, the load profile, the SLO/pass criteria, and the
tuning entry points. Individual graph panels also carry a `description` that
appears as the ⓘ tooltip in Grafana.
"""
import json
import textwrap

DS = "${datasource}"  # Grafana template variable

def panel(title, exprs, x, y, w=12, h=7, panel_id=1, unit="short",
          panel_type="timeseries", description=""):
    return {
        "id": panel_id,
        "type": panel_type,
        "title": title,
        "description": description,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": {"type": "prometheus", "uid": DS},
        "fieldConfig": {
            "defaults": {"unit": unit, "min": 0},
            "overrides": [],
        },
        "options": {"legend": {"showLegend": True, "displayMode": "list"},
                    "tooltip": {"mode": "multi"}},
        "targets": [
            {"refId": chr(65 + i), "datasource": {"type": "prometheus", "uid": DS},
             "expr": expr, "legendFormat": leg}
            for i, (expr, leg) in enumerate(exprs)
        ],
    }

def stat(title, expr, x, y, w=6, h=4, panel_id=1, unit="short", description=""):
    return {
        "id": panel_id, "type": "stat", "title": title,
        "description": description,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": {"type": "prometheus", "uid": DS},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"colorMode": "value", "graphMode": "area"},
        "targets": [{"refId": "A", "expr": expr,
                     "datasource": {"type": "prometheus", "uid": DS}}],
    }

def text(content, x, y, w=24, h=10, panel_id=1, title=""):
    return {
        "id": panel_id, "type": "text", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": content},
    }

def row(title, panel_id, y, collapsed=False):
    return {
        "id": panel_id, "type": "row",
        "title": title, "collapsed": collapsed,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
    }

def make_dashboard(uid, title, panels, tags=None):
    return {
        "uid": uid, "title": title,
        "schemaVersion": 39, "version": 1, "editable": True,
        "tags": tags or ["load-test"],
        "time": {"from": "now-30m", "to": "now"},
        "refresh": "30s",
        "templating": {"list": [{
            "name": "datasource", "type": "datasource", "query": "prometheus",
            "current": {"text": "Prometheus", "value": "Prometheus"},
            "label": "Datasource",
        }]},
        "panels": panels,
    }

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

# ============================================================================
# OpenSearch (OS-01/02)
# ============================================================================

OS_DESC = textwrap.dedent("""\
    ## 🔍 OpenSearch 부하 테스트 (OS-01 / OS-02)

    **목적**: Kubernetes에 배포된 OpenSearch 클러스터의 인덱싱 처리량과 검색 지연을 검증합니다.

    ### 시나리오
    | ID | 시나리오 | 도구 | 매니페스트 |
    |----|----------|------|------------|
    | **OS-01** | Bulk Indexing (30분) | opensearch-benchmark `geonames` 워크로드 | `04-test-jobs/opensearch-benchmark.yaml` |
    | **OS-02** | Mixed Read/Write (7분) | k6로 검색 쿼리 동시 실행 | `04-test-jobs/k6-opensearch-search.yaml` |

    ### 부하 프로파일
    - **OS-01**: bulk_size=5000, clients=16. 사전 다운로드된 geonames 데이터를 연속 인덱싱.
    - **OS-02**: 1m → 50 VUs ramp-up → 5m × 50 VUs → 1m ramp-down. 각 VU는 `match: error` 쿼리 반복.

    ### SLO (운영 기준 — minikube 단일 노드에서는 도달 불가, 도구 동작 검증용)
    | 지표 | 목표 |
    |------|------|
    | Bulk Indexing TPS | ≥ 30,000 docs/s |
    | Search p95 latency | ≤ 500 ms |
    | Search p99 latency | ≤ 1500 ms |
    | Write thread pool reject | < 0.1% |
    | Heap usage | ≤ 75% |
    | Cluster Status | green 유지 |

    ### 핵심 지표 해설
    - **Indexing Rate**: `rate(elasticsearch_indices_indexing_index_total[1m])` — 노드 단위 초당 인덱싱 문서 수.
    - **Bulk Reject**: 쓰기 thread pool 큐가 가득 차서 거부된 요청 수. **0 근접 유지**가 정상.
    - **Heap Used %**: JVM 힙 사용률. 75%↑ 지속이면 GC 시간 급증, 응답 지연으로 이어짐.
    - **Search Latency**: 평균(`time_total/total`)으로 표시. p95/p99는 클라이언트(k6) 결과 참조.

    ### 튜닝 의사결정
    | 증상 | 1차 조치 | 2차 조치 |
    |------|----------|----------|
    | Heap 75%↑ | `bulk_size`↓, `refresh_interval`↑ | data node 증설 |
    | reject ↑ | `clients`↓, `queue_size`↑ | coordinator 분리 |
    | disk IO 80%↑ | `translog.durability=async` | NVMe 전환, shard 재배치 |
    | search p99 spike | slow query log 분석 | query cache 상향 |

    > 데이터 출처: standalone `prometheus-community/elasticsearch_exporter` (Job: `opensearch-exporter`)
""")

os_pid = 0
def nid():
    global os_pid; os_pid += 1; return os_pid

opensearch_panels = [
    text(OS_DESC, 0, 0, w=24, h=12, panel_id=nid()),
    row("Cluster", nid(), 12),
    stat("Cluster Status (1=green)",
         'elasticsearch_cluster_health_status{color="green"}',
         0, 13, panel_id=nid(),
         description="OpenSearch 클러스터 상태. 1이면 green, 0이면 yellow/red. 부하 중에도 green 유지가 합격 기준."),
    stat("Active Shards",
         "elasticsearch_cluster_health_active_shards", 6, 13, panel_id=nid(),
         description="현재 active 상태인 shard 수(primary+replica). 단일 노드는 replica가 unassigned이라 yellow일 수 있음."),
    stat("Active Primary",
         "elasticsearch_cluster_health_active_primary_shards", 12, 13, panel_id=nid(),
         description="primary shard 수. 인덱싱이 일어나는 핵심 단위."),
    stat("Unassigned Shards",
         "elasticsearch_cluster_health_unassigned_shards", 18, 13, panel_id=nid(),
         description="할당되지 못한 shard. single-node 환경에서는 replica가 여기 잡힘. 0이면 green."),
    row("Indexing (OS-01)", nid(), 17),
    panel("Indexing Rate (docs/s)",
          [("rate(elasticsearch_indices_indexing_index_total[1m])", "{{name}}")],
          0, 18, panel_id=nid(), unit="ops",
          description="노드별 초당 인덱싱 처리량. opensearch-benchmark 실행 중 `bulk_size × clients × throughput` 만큼 상승."),
    panel("Indexing Latency (avg, s)",
          [("rate(elasticsearch_indices_indexing_index_time_seconds_total[1m]) / "
            "clamp_min(rate(elasticsearch_indices_indexing_index_total[1m]),1)", "{{name}}")],
          12, 18, panel_id=nid(), unit="s",
          description="문서당 평균 인덱싱 시간. clamp_min으로 0 나눗셈 방지. 50ms 이상이면 병목."),
    panel("Bulk Reject Rate",
          [("rate(elasticsearch_thread_pool_rejected_count{type=\"write\"}[1m])", "{{name}}")],
          0, 25, panel_id=nid(), unit="ops",
          description="write thread pool에서 거부된 요청 비율. 증가 시 클라이언트 측 backoff/Retry_Limit 동작 필요."),
    panel("Pending Tasks",
          [("elasticsearch_cluster_health_number_of_pending_tasks", "pending")],
          12, 25, panel_id=nid(),
          description="master에 대기 중인 태스크. 누적 시 master 오버로드 신호."),
    row("Search (OS-02)", nid(), 32),
    panel("Search Rate (qps)",
          [("rate(elasticsearch_indices_search_query_total[1m])", "{{name}}")],
          0, 33, panel_id=nid(), unit="ops",
          description="초당 search 쿼리 처리량. k6 부하 시 ramp-up 곡선이 보여야 함."),
    panel("Search Latency (avg, s)",
          [("rate(elasticsearch_indices_search_query_time_seconds_total[1m]) / "
            "clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)", "{{name}}")],
          12, 33, panel_id=nid(), unit="s",
          description="평균 검색 지연. p95/p99는 k6 stdout 결과를 참조 (서버 측 평균은 꼬리 지연을 가림)."),
    row("Resource", nid(), 40),
    panel("Heap Used (%)",
          [("elasticsearch_jvm_memory_used_bytes{area=\"heap\"} / elasticsearch_jvm_memory_max_bytes{area=\"heap\"} * 100", "{{name}}")],
          0, 41, panel_id=nid(), unit="percent",
          description="JVM heap 사용률. 75%↑ 지속이면 GC 영향으로 응답 지연 발생."),
    panel("GC Time (s/s)",
          [("rate(elasticsearch_jvm_gc_collection_seconds_sum[1m])", "{{name}} {{gc}}")],
          12, 41, panel_id=nid(), unit="s",
          description="초당 GC 누적 시간. young/old gen 별로 표시. old gen이 빈번하면 heap 부족 의심."),
]

# ============================================================================
# Fluent-bit (FB)
# ============================================================================

FB_DESC = textwrap.dedent("""\
    ## 🪵 Fluent-bit 부하 테스트 (FB-01 ~ FB-05)

    **목적**: DaemonSet으로 동작하는 Fluent-bit의 단일 인스턴스 처리량, backpressure 거동, 손실률, 자동 복구를 검증합니다.

    ### 시나리오
    | ID | 시나리오 | 핵심 지표 |
    |----|----------|-----------|
    | **FB-01** | 단일 Pod throughput ceiling (30분, stress) | records/s, drops |
    | **FB-02** | 정상 운영 부하 (1시간, load) | CPU, buffer size |
    | **FB-03** | Output 장애 주입 (chaos) | retries, filesystem buffer |
    | **FB-04** | 멀티라인 스택트레이스 (load) | parse latency |
    | **FB-05** | 로그 버스트 spike | backpressure, drop |

    ### 데이터 흐름
    ```
    flog Pod (load-test ns) ─stdout→ /var/log/containers/*.log
        → Fluent-bit tail input → parser/filter → buffer (mem+filesystem)
        → OpenSearch bulk output
    ```
    - 부하기: `mingrammer/flog` (`-f json -d 100us -l`), replicas로 노드별 부하 조절.
    - 출력: `opensearch-lt-node.monitoring.svc:9200` (logstash-format → `logs-fb-YYYY.MM.DD`).

    ### SLO
    | 지표 | 목표 |
    |------|------|
    | per-pod throughput (FB-01) | ≥ 50,000 lines/s |
    | 손실률 (with `storage.type=filesystem`) | 0% |
    | tail → output p95 지연 | ≤ 5 s |
    | CPU | ≤ pod limit 70% |
    | RSS | ≤ pod limit 70% |

    ### 핵심 지표 해설
    - **Input Records Rate**: `rate(fluentbit_input_records_total[1m])` — tail input이 초당 읽은 라인 수.
    - **Output Processed Rate**: 정상 출력된 레코드. input rate와 차이가 = drops/buffer 누적.
    - **Output Errors / Retries**: 재시도가 누적되면 backpressure 발생. `Retry_Limit=False`면 무제한 재시도로 데이터 보전.
    - **Storage Backlog**: `fluentbit_input_storage_chunks_busy_bytes` — filesystem buffer 누적량. 디스크 여유 모니터링 필수.

    ### 튜닝 의사결정
    | 증상 | 조치 |
    |------|------|
    | drops 발생 | `Mem_Buf_Limit`↑, `storage.type=filesystem` |
    | CPU throttling | `Workers`↑ (output), filter 단순화 |
    | output 에러 지속 | OpenSearch bulk reject 조사, backoff |
    | parser 지연 | 정규식 단순화, multiline 최적화 |

    > 데이터 출처: Fluent-bit `/api/v2/metrics/prometheus` (Job: `fluent-bit-lt`)
""")

fb_pid = 0
def fid():
    global fb_pid; fb_pid += 1; return fb_pid

fluent_panels = [
    text(FB_DESC, 0, 0, w=24, h=14, panel_id=fid()),
    row("Throughput (FB-01)", fid(), 14),
    panel("Input Records Rate",
          [('sum by (pod) (rate(fluentbit_input_records_total[1m]))', "{{pod}}")],
          0, 15, panel_id=fid(), unit="ops",
          description="tail input이 초당 읽은 로그 라인 수. flog replicas와 -d 옵션에 따라 변동."),
    panel("Output Processed Rate",
          [('sum by (pod, name) (rate(fluentbit_output_proc_records_total[1m]))', "{{pod}} {{name}}")],
          12, 15, panel_id=fid(), unit="ops",
          description="output별 정상 처리된 레코드. input rate와 비교해 drops/지연 여부 확인."),
    row("Reliability (FB-03/05)", fid(), 22),
    panel("Output Errors",
          [('sum by (name) (rate(fluentbit_output_errors_total[1m]))', "{{name}}")],
          0, 23, panel_id=fid(), unit="ops",
          description="output 에러율. 0 유지가 정상. 증가 시 OpenSearch 응답 코드/연결 점검."),
    panel("Retries vs Retries Failed",
          [('sum by (name) (rate(fluentbit_output_retries_total[1m]))', "retries {{name}}"),
           ('sum by (name) (rate(fluentbit_output_retries_failed_total[1m]))', "failed {{name}}")],
          12, 23, panel_id=fid(), unit="ops",
          description="재시도 발생률 / 재시도가 결국 실패한 비율. failed > 0이면 데이터 손실 의심."),
    row("Buffer / Resource (FB-02)", fid(), 30),
    panel("Memory Working Set",
          [('container_memory_working_set_bytes{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}', "{{pod}}")],
          0, 31, panel_id=fid(), unit="bytes",
          description="Fluent-bit Pod RSS. limit 70% 이내 유지."),
    panel("CPU Usage (cores)",
          [('rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}[1m])', "{{pod}}")],
          12, 31, panel_id=fid(), unit="percentunit",
          description="CPU 사용률(코어 단위). limit 근접 시 throttling 발생 가능."),
    panel("Storage Backlog (filesystem buffer)",
          [('fluentbit_input_storage_chunks_busy_bytes', "{{name}} {{pod}}")],
          0, 38, panel_id=fid(), unit="bytes",
          description="filesystem buffer에 누적된 미전송 chunk. 출력 장애 시 증가, 복구 시 감소."),
    panel("Output Throughput (Bps)",
          [('sum by (name) (rate(fluentbit_output_proc_bytes_total[1m]))', "{{name}}")],
          12, 38, panel_id=fid(), unit="Bps",
          description="output별 처리 바이트율. 네트워크 포화 진단용."),
]

# ============================================================================
# Prometheus (PR)
# ============================================================================

PR_DESC = textwrap.dedent("""\
    ## 📊 Prometheus 부하 테스트 (PR-01 ~ PR-07)

    **목적**: Prometheus의 수집(Scrape), 저장(TSDB), 질의(PromQL) 세 축을 분리해 한계 용량과 안정성을 검증합니다.

    ### 시나리오
    | ID | 시나리오 | 도구 | 핵심 지표 |
    |----|----------|------|-----------|
    | **PR-01** | 수집 타깃 수 증가 (stress) | avalanche replicas↑ | scrape duration |
    | **PR-02** | Active series 1M→5M | avalanche `--series-count` | head_series, RSS |
    | **PR-03** | 질의 동시성 (load) | k6 PromQL queries | request duration |
    | **PR-04** | 장기 Range Query (load) | k6 with 30d step | p99 latency |
    | **PR-05** | Cardinality Spike | avalanche label 폭증 | head series churn |
    | **PR-06** | WAL replay 복구 | Pod restart | startup time |
    | **PR-07** | Soak 24h | 평균 부하 유지 | 메모리/디스크 증가율 |

    ### 부하 도구
    - **avalanche** (`quay.io/prometheuscommunity/avalanche:v0.7.0`): 합성 `/metrics` 엔드포인트.
      - `--gauge-metric-count × --series-count` = 단일 Pod active series. 본 환경 기본값 200×200=40k/Pod.
    - **k6** (`grafana/k6:0.55.2`): 7가지 PromQL 쿼리 무작위 실행. 20 VUs × 5분.

    ### SLO
    | 지표 | 목표 |
    |------|------|
    | scrape duration p95 | ≤ 1 s |
    | WAL fsync p99 | ≤ 30 ms |
    | range query p95 (24h) | ≤ 2 s |
    | RSS | ≤ pod limit 80% |
    | `prometheus_tsdb_compactions_failed_total` | 0 |

    ### 핵심 지표 해설
    - **Active Head Series**: 현재 메모리에 보관 중인 시리즈 수. 메모리 사용량과 비례.
    - **Series Churn**: 시리즈 생성/제거 속도. 높으면 카디널리티 폭증 신호.
    - **Scrape Duration p95**: target별 scrape에 걸린 시간 분포 95분위.
    - **WAL fsync sum/s**: write-ahead log 동기화 부담. SSD 권장.
    - **Engine Query Duration p95**: PromQL 평가 시간. recording rule 도입으로 단축 가능.

    ### 튜닝 의사결정
    | 증상 | 조치 |
    |------|------|
    | RSS 지속 증가 | relabel `metric_relabel_configs` drop, allowlist |
    | WAL fsync↑ | SSD/IO class 상향 |
    | compaction 실패 | 디스크 여유 확인, retention↓ |
    | query duration↑ | recording rule, `step`↑, `--query.max-samples` |

    > 용량 산정 참고:
    > 100만 series ≈ 3~5 GiB heap, 일일 디스크 ≈ `series × samples/sec × 2B × 86400`
""")

pr_pid = 0
def pid():
    global pr_pid; pr_pid += 1; return pr_pid

prom_panels = [
    text(PR_DESC, 0, 0, w=24, h=15, panel_id=pid()),
    row("Series & Cardinality (PR-01/02/05)", pid(), 15),
    stat("Active Head Series", "prometheus_tsdb_head_series", 0, 16, panel_id=pid(),
         description="현재 메모리에 있는 시리즈 수. 메모리/디스크의 1차 결정 변수."),
    stat("Series Created /5m",
         "rate(prometheus_tsdb_head_series_created_total[5m])", 6, 16, panel_id=pid(), unit="ops",
         description="시리즈 생성률. 카디널리티 폭증 또는 series_interval에 따른 churn 측정."),
    stat("Targets UP", 'count(up==1)', 12, 16, panel_id=pid(),
         description="health=up 상태 target 수."),
    stat("Targets DOWN", 'count(up==0)', 18, 16, panel_id=pid(),
         description="health=down 상태 target 수. 0 유지가 정상."),
    panel("Head Series Over Time",
          [("prometheus_tsdb_head_series", "series")],
          0, 20, panel_id=pid(),
          description="시간 경과에 따른 active series. avalanche replica/series-count 조정 시 곡선 변화."),
    panel("Series Churn (created vs removed)",
          [("rate(prometheus_tsdb_head_series_created_total[5m])", "created"),
           ("rate(prometheus_tsdb_head_series_removed_total[5m])", "removed")],
          12, 20, panel_id=pid(), unit="ops",
          description="created가 지속적으로 removed보다 크면 카디널리티 누적 → 메모리 압박."),
    row("Scrape (PR-01)", pid(), 27),
    panel("Scrape Duration p95 by job",
          [('histogram_quantile(0.95, sum by (le, job) (rate(prometheus_target_interval_length_seconds_bucket[5m])))', "{{job}}")],
          0, 28, panel_id=pid(), unit="s",
          description="job별 scrape 간격 분포 p95. interval 짧을수록 spike 가능."),
    panel("Samples Scraped per Target",
          [("scrape_samples_scraped", "{{job}} {{instance}}")],
          12, 28, panel_id=pid(),
          description="target별 1회 scrape에서 수집된 샘플 수. textfile/exporter 추가 시 증가."),
    row("Storage (PR-01/06)", pid(), 35),
    panel("WAL fsync time (s/s)",
          [("rate(prometheus_tsdb_wal_fsync_duration_seconds_sum[1m])", "fsync")],
          0, 36, panel_id=pid(), unit="s",
          description="WAL 동기화 누적 시간. 0.05↑이면 디스크 IO 병목."),
    panel("Compactions (ok vs failed)",
          [("rate(prometheus_tsdb_compactions_total[5m])", "ok"),
           ("rate(prometheus_tsdb_compactions_failed_total[5m])", "failed")],
          12, 36, panel_id=pid(), unit="ops",
          description="block 압축. failed > 0이면 디스크 부족/권한 문제."),
    row("Query (PR-03/04)", pid(), 43),
    panel("Engine Query Duration p95 by slice",
          [('histogram_quantile(0.95, sum by (le, slice) (rate(prometheus_engine_query_duration_seconds_bucket[5m])))', "p95 {{slice}}")],
          0, 44, panel_id=pid(), unit="s",
          description="PromQL 평가 단계(slice)별 p95: prepare, inner_eval, exec_total."),
    panel("HTTP Query Rate",
          [("rate(prometheus_http_requests_total{handler=~\"/api/v1/query.*\"}[1m])", "{{handler}}")],
          12, 44, panel_id=pid(), unit="ops",
          description="API 핸들러별 QPS. range query는 instant보다 비싸므로 분리 모니터링."),
    panel("Process RSS",
          [('process_resident_memory_bytes{job="kps-prometheus"}', "RSS")],
          0, 51, panel_id=pid(), unit="bytes",
          description="Prometheus 프로세스 메모리. pod limit 80% 이내 유지."),
]

# ============================================================================
# node-exporter (NE)
# ============================================================================

NE_DESC = textwrap.dedent("""\
    ## 🖥️ node-exporter 부하 테스트 (NE-01 ~ NE-07)

    **목적**: 노드마다 DaemonSet으로 동작하는 node-exporter의 단일 인스턴스 scrape 비용과 노드 수에 따른 스케일 영향을 측정합니다.

    ### 시나리오
    | ID | 시나리오 | 도구 |
    |----|----------|------|
    | **NE-01** | 기본 collector scrape 비용 (baseline) | curl/Prometheus self |
    | **NE-02** | 고빈도 scrape (5s, 30분) | hey 50c × 50qps × 2분 |
    | **NE-03** | textfile 메트릭 1만 개 (load) | textfile collector |
    | **NE-04** | 마운트 포인트 50+ (load) | mock mounts |
    | **NE-05** | 노드 CPU 90% 포화 (stress) | stress-ng |
    | **NE-06** | Disk IO 포화 (stress) | fio |

    ### 부하 도구
    - **hey** (`williamyeh/hey:latest`): `/metrics` 엔드포인트에 50c × 50qps × 2분 HTTP 부하.
    - 매니페스트: `04-test-jobs/hey-node-exporter.yaml`.

    ### SLO
    | 지표 | 목표 |
    |------|------|
    | `/metrics` 응답 p95 | ≤ 300 ms |
    | scrape timeout | 0건 |
    | 시리즈 수 | 노드당 ≤ 2,000 (선택 collector 기준) |
    | CPU | ≤ 100m (idle 노드) |
    | RSS | ≤ 50 MiB |

    ### 핵심 지표 해설
    - **Scrape Duration**: Prometheus 측에서 측정한 단일 scrape 소요 시간.
    - **Samples Scraped**: 1회 scrape에서 수집된 샘플 수. textfile 추가 시 증가.
    - **Per-collector duration**: `node_scrape_collector_duration_seconds` — collector(filesystem, diskstats, netdev 등)별 분해.
    - 노드 단위 부하는 `stress-ng`/`fio` 등으로 별도 주입하여 collector 영향 비교.

    ### 튜닝 의사결정
    | 증상 | 조치 |
    |------|------|
    | filesystem collector 지연 | `--collector.filesystem.mount-points-exclude` 적용 |
    | 동시 요청 한계 | `--web.max-requests`↑ |
    | CPU throttling | 불필요 collector `--no-collector.*` 비활성화 |
    | textfile 시리즈 과다 | 텍스트파일 축소/삭제 |
""")

ne_pid = 0
def neid():
    global ne_pid; ne_pid += 1; return ne_pid

node_panels = [
    text(NE_DESC, 0, 0, w=24, h=12, panel_id=neid()),
    row("node-exporter Scrape (NE-02)", neid(), 12),
    panel("Scrape Duration",
          [('scrape_duration_seconds{job="node-exporter"}', "{{instance}}")],
          0, 13, panel_id=neid(), unit="s",
          description="Prometheus가 측정한 node-exporter 한 번의 scrape 소요 시간."),
    panel("Samples Scraped per Scrape",
          [('scrape_samples_scraped{job="node-exporter"}', "{{instance}}")],
          12, 13, panel_id=neid(),
          description="1회 scrape에서 수집된 샘플 수. collector 추가/textfile 주입으로 증가."),
    panel("Per-collector duration",
          [("node_scrape_collector_duration_seconds", "{{collector}} {{instance}}")],
          0, 20, panel_id=neid(), unit="s", h=10,
          description="collector별 소요 시간. filesystem/diskstats가 자주 1위."),
    panel("node-exporter RSS",
          [('process_resident_memory_bytes{job="node-exporter"}', "{{instance}}")],
          12, 20, panel_id=neid(), unit="bytes",
          description="node-exporter 프로세스 메모리. 50 MiB 이내 정상."),
    panel("node-exporter CPU",
          [('rate(process_cpu_seconds_total{job="node-exporter"}[1m])', "{{instance}}")],
          12, 27, panel_id=neid(), unit="percentunit",
          description="CPU 사용률. idle 노드에서 100m 이내가 정상."),
]

# ============================================================================
# kube-state-metrics (KSM)
# ============================================================================

KSM_DESC = textwrap.dedent("""\
    ## 🧱 kube-state-metrics 부하 테스트 (KSM-01 ~ KSM-07)

    **목적**: K8s API 서버에 informer를 붙여 오브젝트 상태를 메트릭으로 노출하는 KSM이 대규모 클러스터에서 어떻게 확장되는지 측정합니다.

    ### 시나리오
    | ID | 시나리오 | 도구 |
    |----|----------|------|
    | **KSM-01** | Baseline | 현행 |
    | **KSM-02** | Pod 1만 개 (single-node는 100) | kube-burner |
    | **KSM-03** | ConfigMap 5만 개 | kube-burner |
    | **KSM-04** | Namespace churn | kube-burner |
    | **KSM-05** | Shard(`--total-shards`) 구성 | StatefulSet |
    | **KSM-06** | Soak 24h | 유지 |
    | **KSM-07** | allowlist/denylist 적용 | KSM 옵션 |

    ### 부하 도구
    - **kube-burner** (`quay.io/kube-burner/kube-burner:v1.18.1`): Pod 대량 생성/삭제.
    - 본 환경 기본값: `jobIterations=100` (single-node 보호). 운영은 10000으로 상향.
    - 매니페스트: `04-test-jobs/kube-burner-pod-density.yaml`.

    ### SLO
    | 지표 | 목표 |
    |------|------|
    | `/metrics` 응답 p95 | ≤ 2 s |
    | scrape timeout | 0건 |
    | RSS | ≤ pod limit 70% |
    | API 서버 LIST/WATCH 실패율 | ≈ 0 |
    | 메트릭 업데이트 지연 | ≤ 30 s |

    ### 핵심 지표 해설
    - **HTTP Request Duration p95**: KSM /metrics 응답 분포 95분위.
    - **Samples per Scrape**: scrape당 샘플 수 (오브젝트 수에 비례).
    - **KSM RSS**: informer 캐시 메모리. 오브젝트 수에 거의 선형으로 증가.
    - **Pods count**: 총 Pod 수, kburner-* ns 분포.
    - **API Server Request Rate by verb**: kube-burner가 만든 LIST/WATCH/CREATE 부담.

    ### 튜닝 의사결정
    | 증상 | 조치 |
    |------|------|
    | RSS 한계 근접 | `--total-shards`로 수평 샤딩, `--metric-denylist` |
    | /metrics 느림 | `--resources` 한정, `--metric-denylist` |
    | API 서버 throttle | kube-burner `qps`/`burst`↓ |
    | label cardinality 폭증 | Prometheus 측 `metric_relabel_configs` drop |
""")

ksm_pid = 0
def kid():
    global ksm_pid; ksm_pid += 1; return ksm_pid

ksm_panels = [
    text(KSM_DESC, 0, 0, w=24, h=12, panel_id=kid()),
    row("kube-state-metrics (KSM-02)", kid(), 12),
    panel("HTTP Request Duration p95",
          [('histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="kube-state-metrics"}[5m])))', "p95")],
          0, 13, panel_id=kid(), unit="s",
          description="KSM /metrics 핸들러 응답 시간 p95. 2s 이내 유지."),
    panel("Samples per Scrape",
          [('scrape_samples_scraped{job="kube-state-metrics"}', "samples")],
          12, 13, panel_id=kid(),
          description="1회 scrape에서 수집된 샘플 수. 오브젝트 수에 비례 증가."),
    panel("KSM RSS",
          [('process_resident_memory_bytes{job="kube-state-metrics"}', "RSS")],
          0, 20, panel_id=kid(), unit="bytes",
          description="KSM 메모리. informer 캐시 비용. limit 70% 이내."),
    panel("Pods count",
          [('count(kube_pod_info)', "all"),
           ('count(kube_pod_info{namespace="kburner"})', "kburner")],
          12, 20, panel_id=kid(),
          description="전체 Pod 수와 kburner 부하 ns의 Pod 수. KSM-02 진행 중 후자 곡선이 상승."),
    panel("API Server Request Rate by verb",
          [('sum by (verb) (rate(apiserver_request_total[1m]))', "{{verb}}")],
          0, 27, panel_id=kid(), unit="ops",
          description="API 서버 verb별 RPS. CREATE/LIST/WATCH 분포로 kube-burner 부담 가시화."),
]

# ============================================================================
# Overview
# ============================================================================

OV_DESC = textwrap.dedent("""\
    ## 🧭 Load Test Overview — 부하 테스트 종합 헬스체크

    각 부하 테스트 시나리오 진행 중 한 화면에서 **전체 컴포넌트의 핵심 지표**를 확인하는 종합 대시보드입니다. 상세 분석은 시나리오별 대시보드 사용:

    | 컴포넌트 | 대시보드 | 시나리오 |
    |----------|----------|----------|
    | OpenSearch | [Load Test • OpenSearch](/d/lt-opensearch) | OS-01, OS-02 |
    | Fluent-bit | [Load Test • Fluent-bit](/d/lt-fluent-bit) | FB-01 ~ FB-07 |
    | Prometheus | [Load Test • Prometheus](/d/lt-prometheus) | PR-01 ~ PR-07 |
    | node-exporter | [Load Test • node-exporter](/d/lt-node-exporter) | NE-01 ~ NE-07 |
    | kube-state-metrics | [Load Test • kube-state-metrics](/d/lt-ksm) | KSM-01 ~ KSM-07 |

    ### 진행 절차 (요약)
    1. **사전 점검**: 클러스터 health, 디스크 여유, 알람 silence
    2. **베이스라인**: 부하 없이 5분 캡처 (이 대시보드 스냅샷)
    3. **부하 주입**: `kubectl apply -f deploy/load-testing/04-test-jobs/<job>.yaml`
    4. **측정**: 시나리오별 대시보드 + 도구 stdout
    5. **합격 판정**: 가이드 SLO 표 대비 비교
    6. **정리**: `kubectl delete` + `99-cleanup.sh`

    ### 한 화면 요약 지표
    - **Targets UP/DOWN**: 모든 scrape target health
    - **Active Series**: Prometheus 메모리 압박 1차 지표
    - **Cluster Status**: OpenSearch green 유지 여부
    - **Indexing TPS / Output Rate**: 데이터 파이프라인 처리량
    - **Search Latency / PromQL p95**: 사용자 경험 지표
    - **Pod CPU/Memory (load-test ns)**: 부하기 자체 자원 사용량
    - **Errors / Rejects**: 데이터 손실 1차 신호

    > 자세한 운영 절차는 `docs/load-testing/06-test-execution-plan.md` 참조.
""")

ov_pid = 0
def oid():
    global ov_pid; ov_pid += 1; return ov_pid

overview_panels = [
    text(OV_DESC, 0, 0, w=24, h=14, panel_id=oid()),
    row("Cluster Health", oid(), 14),
    stat("Targets UP", 'count(up==1)', 0, 15, w=4, panel_id=oid(),
         description="health=up target 수"),
    stat("Targets DOWN", 'count(up==0)', 4, 15, w=4, panel_id=oid(),
         description="health=down target 수, 0 유지가 정상"),
    stat("Active Series", 'prometheus_tsdb_head_series', 8, 15, w=4, panel_id=oid(),
         description="현재 Prometheus head series"),
    stat("Cluster Status (green=1)",
         'elasticsearch_cluster_health_status{color="green"}', 12, 15, w=4, panel_id=oid(),
         description="OpenSearch green=1, otherwise=0"),
    stat("Indexing TPS",
         'sum(rate(elasticsearch_indices_indexing_index_total[1m]))', 16, 15, w=4, panel_id=oid(), unit="ops",
         description="클러스터 합계 인덱싱 처리량"),
    stat("FB output rate",
         'sum(rate(fluentbit_output_proc_records_total[1m]))', 20, 15, w=4, panel_id=oid(), unit="ops",
         description="Fluent-bit 합계 출력률"),
    row("Latency Summary", oid(), 19),
    panel("Search Latency (avg)",
          [('rate(elasticsearch_indices_search_query_time_seconds_total[1m])/clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)', "{{name}}")],
          0, 20, panel_id=oid(), unit="s",
          description="평균 검색 지연 (서버 측)"),
    panel("PromQL p95",
          [('histogram_quantile(0.95, sum by (le) (rate(prometheus_engine_query_duration_seconds_bucket[5m])))', "p95")],
          12, 20, panel_id=oid(), unit="s",
          description="PromQL 평가 시간 p95"),
    row("Saturation (load-test ns)", oid(), 27),
    panel("Pod Memory",
          [('sum by (pod) (container_memory_working_set_bytes{namespace="load-test"})', "{{pod}}")],
          0, 28, panel_id=oid(), unit="bytes",
          description="load-test ns Pod 메모리 (부하기 자체 점유량)"),
    panel("Pod CPU",
          [('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="load-test"}[1m]))', "{{pod}}")],
          12, 28, panel_id=oid(), unit="percentunit",
          description="load-test ns Pod CPU"),
    row("Errors", oid(), 35),
    panel("Output Errors / Bulk Rejects",
          [('sum(rate(fluentbit_output_errors_total[1m]))', "fluent-bit out err"),
           ('sum(rate(fluentbit_output_retries_total[1m]))', "fluent-bit retries"),
           ('sum(rate(elasticsearch_thread_pool_rejected_count{type="write"}[1m]))', "OS write rejects")],
          0, 36, panel_id=oid(), unit="ops",
          description="데이터 손실 1차 신호 — 모두 0 근접 유지"),
]

# Emit YAML
out = "# Auto-generated by gen.py — DO NOT EDIT MANUALLY (run 'python3 gen.py > dashboards.yaml')\n---\n"
out += configmap("dash-load-test-overview",
                 make_dashboard("lt-overview", "Load Test • Overview", overview_panels)) + "\n---\n"
out += configmap("dash-load-test-opensearch",
                 make_dashboard("lt-opensearch", "Load Test • OpenSearch (OS-01/02)", opensearch_panels)) + "\n---\n"
out += configmap("dash-load-test-fluent-bit",
                 make_dashboard("lt-fluent-bit", "Load Test • Fluent-bit (FB)", fluent_panels)) + "\n---\n"
out += configmap("dash-load-test-prometheus",
                 make_dashboard("lt-prometheus", "Load Test • Prometheus (PR)", prom_panels)) + "\n---\n"
out += configmap("dash-load-test-node-exporter",
                 make_dashboard("lt-node-exporter", "Load Test • node-exporter (NE)", node_panels)) + "\n---\n"
out += configmap("dash-load-test-ksm",
                 make_dashboard("lt-ksm", "Load Test • kube-state-metrics (KSM)", ksm_panels))

print(out)
