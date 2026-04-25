#!/usr/bin/env python3
"""Generate Grafana dashboard ConfigMap manifests for load-testing scenarios."""
import json
import os
import sys
import textwrap

DS = "${datasource}"  # Grafana template variable

def panel(title, exprs, x, y, w=12, h=7, panel_id=1, unit="short", panel_type="timeseries"):
    """Build a timeseries panel referencing the Prometheus datasource."""
    return {
        "id": panel_id,
        "type": panel_type,
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": {"type": "prometheus", "uid": DS},
        "fieldConfig": {
            "defaults": {"unit": unit, "min": 0},
            "overrides": [],
        },
        "options": {"legend": {"showLegend": True, "displayMode": "list"}, "tooltip": {"mode": "multi"}},
        "targets": [
            {"refId": chr(65 + i), "datasource": {"type": "prometheus", "uid": DS},
             "expr": expr, "legendFormat": leg}
            for i, (expr, leg) in enumerate(exprs)
        ],
    }

def stat(title, expr, x, y, w=6, h=4, panel_id=1, unit="short"):
    return {
        "id": panel_id, "type": "stat", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": {"type": "prometheus", "uid": DS},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"colorMode": "value", "graphMode": "area"},
        "targets": [{"refId": "A", "expr": expr,
                     "datasource": {"type": "prometheus", "uid": DS}}],
    }

def row(title, panel_id, y):
    return {
        "id": panel_id, "type": "row",
        "title": title, "collapsed": False,
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

# -------- OpenSearch (OS-01/02) --------
os_pid = 0
def nid():
    global os_pid; os_pid += 1; return os_pid

opensearch_panels = [
    row("Cluster", nid(), 0),
    stat("Cluster Status (1=green,2=yellow,3=red)",
         'elasticsearch_cluster_health_status{color="green"}*1+elasticsearch_cluster_health_status{color="yellow"}*2+elasticsearch_cluster_health_status{color="red"}*3',
         0, 1, panel_id=nid()),
    stat("Active Shards", "elasticsearch_cluster_health_active_shards", 6, 1, panel_id=nid()),
    stat("Active Primary", "elasticsearch_cluster_health_active_primary_shards", 12, 1, panel_id=nid()),
    stat("Unassigned Shards", "elasticsearch_cluster_health_unassigned_shards", 18, 1, panel_id=nid()),
    row("Indexing (OS-01)", nid(), 5),
    panel("Indexing Rate (docs/s)",
          [("rate(elasticsearch_indices_indexing_index_total[1m])", "{{name}}")],
          0, 6, panel_id=nid(), unit="ops"),
    panel("Indexing Latency avg (s)",
          [("rate(elasticsearch_indices_indexing_index_time_seconds_total[1m]) / "
            "clamp_min(rate(elasticsearch_indices_indexing_index_total[1m]),1)", "{{name}}")],
          12, 6, panel_id=nid(), unit="s"),
    panel("Bulk Reject Rate (write thread pool)",
          [("rate(elasticsearch_thread_pool_rejected_count{type=\"write\"}[1m])", "{{name}}")],
          0, 13, panel_id=nid(), unit="ops"),
    panel("Pending Tasks",
          [("elasticsearch_cluster_health_number_of_pending_tasks", "pending")],
          12, 13, panel_id=nid()),
    row("Search (OS-02)", nid(), 20),
    panel("Search Rate (qps)",
          [("rate(elasticsearch_indices_search_query_total[1m])", "{{name}}")],
          0, 21, panel_id=nid(), unit="ops"),
    panel("Search Latency avg (s)",
          [("rate(elasticsearch_indices_search_query_time_seconds_total[1m]) / "
            "clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)", "{{name}}")],
          12, 21, panel_id=nid(), unit="s"),
    row("Resource", nid(), 28),
    panel("Heap Used (%)",
          [("elasticsearch_jvm_memory_used_bytes{area=\"heap\"} / elasticsearch_jvm_memory_max_bytes{area=\"heap\"} * 100", "{{name}}")],
          0, 29, panel_id=nid(), unit="percent"),
    panel("GC Time (s/s)",
          [("rate(elasticsearch_jvm_gc_collection_seconds_sum[1m])", "{{name}} {{gc}}")],
          12, 29, panel_id=nid(), unit="s"),
]

# -------- Fluent-bit (FB-01/02) --------
fb_pid = 0
def fid():
    global fb_pid; fb_pid += 1; return fb_pid

fluent_panels = [
    row("Throughput (FB-01)", fid(), 0),
    panel("Input Records Rate",
          [('sum by (pod) (rate(fluentbit_input_records_total[1m]))', "{{pod}}")],
          0, 1, panel_id=fid(), unit="ops"),
    panel("Output Processed Rate",
          [('sum by (pod, name) (rate(fluentbit_output_proc_records_total[1m]))', "{{pod}} {{name}}")],
          12, 1, panel_id=fid(), unit="ops"),
    row("Reliability (FB-03/05)", fid(), 8),
    panel("Output Errors",
          [('sum by (name) (rate(fluentbit_output_errors_total[1m]))', "{{name}}")],
          0, 9, panel_id=fid(), unit="ops"),
    panel("Output Retries",
          [('sum by (name) (rate(fluentbit_output_retries_total[1m]))', "retries {{name}}"),
           ('sum by (name) (rate(fluentbit_output_retries_failed_total[1m]))', "retries-failed {{name}}")],
          12, 9, panel_id=fid(), unit="ops"),
    row("Buffer / Resource (FB-02)", fid(), 16),
    panel("Memory Working Set",
          [('container_memory_working_set_bytes{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}', "{{pod}}")],
          0, 17, panel_id=fid(), unit="bytes"),
    panel("CPU usage",
          [('rate(container_cpu_usage_seconds_total{namespace="monitoring",pod=~"fluent-bit.*",container="fluent-bit"}[1m])', "{{pod}}")],
          12, 17, panel_id=fid(), unit="percentunit"),
    panel("Storage Backlog (filesystem buffer)",
          [('fluentbit_input_storage_chunks_busy_bytes', "{{name}} {{pod}}")],
          0, 24, panel_id=fid(), unit="bytes"),
    panel("Output Throughput (bytes)",
          [('sum by (name) (rate(fluentbit_output_proc_bytes_total[1m]))', "{{name}}")],
          12, 24, panel_id=fid(), unit="Bps"),
]

# -------- Prometheus self (PR-01/02/03) --------
pr_pid = 0
def pid():
    global pr_pid; pr_pid += 1; return pr_pid

prom_panels = [
    row("Series & Cardinality (PR-01/02/05)", pid(), 0),
    stat("Active Head Series", "prometheus_tsdb_head_series", 0, 1, panel_id=pid()),
    stat("Series Created /5m",
         "rate(prometheus_tsdb_head_series_created_total[5m])", 6, 1, panel_id=pid(), unit="ops"),
    stat("Targets UP",
         'count(up==1)', 12, 1, panel_id=pid()),
    stat("Targets DOWN",
         'count(up==0)', 18, 1, panel_id=pid()),
    panel("Head Series Over Time",
          [("prometheus_tsdb_head_series", "series")],
          0, 5, panel_id=pid()),
    panel("Series Churn",
          [("rate(prometheus_tsdb_head_series_created_total[5m])", "created"),
           ("rate(prometheus_tsdb_head_series_removed_total[5m])", "removed")],
          12, 5, panel_id=pid(), unit="ops"),
    row("Scrape (PR-01)", pid(), 12),
    panel("Scrape Duration p95 by job",
          [('histogram_quantile(0.95, sum by (le, job) (rate(prometheus_target_interval_length_seconds_bucket[5m])))', "{{job}}")],
          0, 13, panel_id=pid(), unit="s"),
    panel("Samples Scraped per Target",
          [("scrape_samples_scraped", "{{job}} {{instance}}")],
          12, 13, panel_id=pid()),
    row("Storage (PR-01/06)", pid(), 20),
    panel("WAL fsync sum/s",
          [("rate(prometheus_tsdb_wal_fsync_duration_seconds_sum[1m])", "fsync")],
          0, 21, panel_id=pid(), unit="s"),
    panel("Compactions",
          [("rate(prometheus_tsdb_compactions_total[5m])", "ok"),
           ("rate(prometheus_tsdb_compactions_failed_total[5m])", "failed")],
          12, 21, panel_id=pid(), unit="ops"),
    row("Query (PR-03/04)", pid(), 28),
    panel("Engine Query Duration p95",
          [('histogram_quantile(0.95, sum by (le, slice) (rate(prometheus_engine_query_duration_seconds_bucket[5m])))', "p95 {{slice}}")],
          0, 29, panel_id=pid(), unit="s"),
    panel("HTTP Query Rate",
          [("rate(prometheus_http_requests_total{handler=~\"/api/v1/query.*\"}[1m])", "{{handler}}")],
          12, 29, panel_id=pid(), unit="ops"),
    panel("Resident Memory",
          [('process_resident_memory_bytes{job="kps-prometheus"}', "RSS")],
          0, 36, panel_id=pid(), unit="bytes"),
]

# -------- node-exporter (NE-02) --------
ne_pid = 0
def neid():
    global ne_pid; ne_pid += 1; return ne_pid

node_panels = [
    row("node-exporter Scrape (NE-02)", neid(), 0),
    panel("Scrape Duration p95 (node-exporter only)",
          [('histogram_quantile(0.95, sum by (le, instance) (rate(scrape_samples_scraped_bucket{job="node-exporter"}[5m])) > 0)', "{{instance}}"),
           ('scrape_duration_seconds{job="node-exporter"}', "{{instance}}")],
          0, 1, panel_id=neid(), unit="s"),
    panel("Samples Scraped per Scrape",
          [('scrape_samples_scraped{job="node-exporter"}', "{{instance}}")],
          12, 1, panel_id=neid()),
    panel("Per-collector duration",
          [("node_scrape_collector_duration_seconds", "{{collector}} {{instance}}")],
          0, 8, panel_id=neid(), unit="s", h=10),
    panel("node-exporter RSS",
          [('process_resident_memory_bytes{job="node-exporter"}', "{{instance}}")],
          12, 8, panel_id=neid(), unit="bytes"),
    panel("node-exporter CPU",
          [('rate(process_cpu_seconds_total{job="node-exporter"}[1m])', "{{instance}}")],
          12, 15, panel_id=neid(), unit="percentunit"),
]

# -------- kube-state-metrics (KSM-02) --------
ksm_pid = 0
def kid():
    global ksm_pid; ksm_pid += 1; return ksm_pid

ksm_panels = [
    row("kube-state-metrics (KSM-02)", kid(), 0),
    panel("HTTP Request Duration p95 (KSM)",
          [('histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="kube-state-metrics"}[5m])))', "p95")],
          0, 1, panel_id=kid(), unit="s"),
    panel("Samples per Scrape (KSM)",
          [('scrape_samples_scraped{job="kube-state-metrics"}', "samples")],
          12, 1, panel_id=kid()),
    panel("KSM RSS",
          [('process_resident_memory_bytes{job="kube-state-metrics"}', "RSS")],
          0, 8, panel_id=kid(), unit="bytes"),
    panel("Pods count",
          [('count(kube_pod_info)', "all"),
           ('count(kube_pod_info{namespace="kburner"})', "kburner")],
          12, 8, panel_id=kid()),
    panel("API Server Request Rate (LIST/WATCH from KSM-driven load)",
          [('sum by (verb) (rate(apiserver_request_total[1m]))', "{{verb}}")],
          0, 15, panel_id=kid(), unit="ops"),
]

# -------- Overview --------
ov_pid = 0
def oid():
    global ov_pid; ov_pid += 1; return ov_pid

overview_panels = [
    row("Cluster Health", oid(), 0),
    stat("Targets UP", 'count(up==1)', 0, 1, w=4, panel_id=oid()),
    stat("Targets DOWN", 'count(up==0)', 4, 1, w=4, panel_id=oid()),
    stat("Active Series", 'prometheus_tsdb_head_series', 8, 1, w=4, panel_id=oid()),
    stat("Cluster Status", 'elasticsearch_cluster_health_status{color="green"}', 12, 1, w=4, panel_id=oid()),
    stat("Indexing TPS",
         'sum(rate(elasticsearch_indices_indexing_index_total[1m]))', 16, 1, w=4, panel_id=oid(), unit="ops"),
    stat("FB output rate",
         'sum(rate(fluentbit_output_proc_records_total[1m]))', 20, 1, w=4, panel_id=oid(), unit="ops"),
    row("Latency Summary", oid(), 5),
    panel("Search Latency (avg)",
          [('rate(elasticsearch_indices_search_query_time_seconds_total[1m])/clamp_min(rate(elasticsearch_indices_search_query_total[1m]),1)', "{{name}}")],
          0, 6, panel_id=oid(), unit="s"),
    panel("PromQL p95",
          [('histogram_quantile(0.95, sum by (le) (rate(prometheus_engine_query_duration_seconds_bucket[5m])))', "p95")],
          12, 6, panel_id=oid(), unit="s"),
    row("Saturation", oid(), 13),
    panel("Pod Memory (load-test ns)",
          [('sum by (pod) (container_memory_working_set_bytes{namespace="load-test"})', "{{pod}}")],
          0, 14, panel_id=oid(), unit="bytes"),
    panel("Pod CPU (load-test ns)",
          [('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="load-test"}[1m]))', "{{pod}}")],
          12, 14, panel_id=oid(), unit="percentunit"),
    row("Errors", oid(), 21),
    panel("Output Errors / Bulk Rejects",
          [('sum(rate(fluentbit_output_errors_total[1m]))', "fluent-bit out err"),
           ('sum(rate(fluentbit_output_retries_total[1m]))', "fluent-bit retries"),
           ('sum(rate(elasticsearch_thread_pool_rejected_count{type="write"}[1m]))', "OS write rejects")],
          0, 22, panel_id=oid(), unit="ops"),
]

# Emit YAML
out = "# Auto-generated by gen-dashboards.py — DO NOT EDIT MANUALLY\n---\n"
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
