# Section 9: 모니터링 모듈 성능 테스트

## 개요

본 섹션은 모니터링 클러스터(Prometheus, OpenSearch, Fluent Bit, Grafana, Alertmanager)의
성능 한계를 사전에 파악하고, 운영 임계값 기준을 수립하기 위한 성능 테스트 절차 및 결과 기록 양식을 정의한다.
테스트는 단계적 부하 증가 방식(step-load)으로 진행하며, 각 구성 요소별 병목 지점을 식별한다.

---

## 9.1 성능 테스트 목표 및 범위

| 대상 모듈 | 테스트 목적 | 목표 지표 | 허용 기준 |
|----------|-----------|---------|---------|
| Prometheus | 대규모 scrape target 수집 성능 확인 | Scrape duration p99 < 10s, TSDB write 처리량 | 2,000 targets 수집 시 scrape 누락률 < 1% |
| Prometheus | 고카디널리티 메트릭 메모리 영향 평가 | Active series 수 대비 메모리 사용량 | 1M series 시 메모리 < 80GB |
| Prometheus | 쿼리 응답 시간 (range query) | p50 / p99 응답 시간 | 24h range query p99 < 30s |
| Fluent Bit | 고용량 로그 폭증 처리 성능 | records/sec, 메모리 사용량, 버퍼 드롭률 | 100K lines/sec 시 드롭률 < 0.1% |
| Fluent Bit | 멀티라인 파싱 처리 성능 | 멀티라인 병합 처리량 | Stacktrace 혼합 50K lines/sec 처리 가능 |
| OpenSearch | 대용량 인덱싱 처리량 | docs/sec, 인덱싱 지연 | bulk 인덱싱 500K docs/sec 이상 |
| OpenSearch | 검색 쿼리 응답 시간 | query latency p99 | 집계 쿼리 p99 < 5s |
| Alertmanager | Alert storm 처리 성능 | E2E latency, 큐 적체 | 1,000 alerts 수신 후 5분 이내 전체 dispatch |
| NVMe Local PV | I/O 포화 테스트 | Throughput MB/s, IOPS, latency | 동시 쓰기 시 p99 latency < 5ms |
| bond1 Network | 대역폭 포화 테스트 | TX/RX throughput GB/s | Fluent Bit → OpenSearch 전송 시 < 40Gbps |

---

## 9.2 테스트 환경 구성

### 9.2.1 클러스터 사양

| 항목 | 사양 | 비고 |
|------|------|------|
| CPU | 96 Core (Intel Xeon 또는 AMD EPYC) | NUMA 구성 확인 필요 |
| Memory | 1TB DDR5 ECC | NUMA per socket 확인 |
| Storage | NVMe 4TB (Local PV) | 순차 읽기 7GB/s, 순차 쓰기 6GB/s (예상) |
| Network (Public) | bond0: 25G + 25G LACP (50Gbps) | 외부 트래픽 |
| Network (Private) | bond1: 25G + 25G LACP (50Gbps) | 클러스터 내부 트래픽 (모니터링 데이터 전송) |
| OS | Linux 6.8+ (Ubuntu 22.04 / RHEL 9) | kernel I/O scheduler 확인 |
| Kubernetes | v1.29+ | kube-proxy IPVS 모드 권장 |

### 9.2.2 테스트 도구 목록

| 도구명 | 용도 | 버전 | 설치 방법 |
|--------|------|------|----------|
| promtool | Prometheus TSDB 분석, 규칙 검증, 벤치마크 | Prometheus 동봉 | `kubectl exec` 내 직접 실행 |
| opensearch-benchmark | OpenSearch 인덱싱/검색 부하 테스트 | 1.5+ | `pip install opensearch-benchmark` |
| flog | 가상 로그 생성 (Apache, JSON, syslog 형식) | 0.4.3+ | `go install github.com/mingrammer/flog@latest` |
| loggen | 고속 로그 생성 (syslog-ng 제공) | syslog-ng 4.x 포함 | `apt install syslog-ng` |
| k6 | HTTP/gRPC 부하 테스트 (Prometheus API, Grafana API) | 0.50+ | `snap install k6` |
| stress-ng | CPU/Memory/I/O 복합 스트레스 테스트 | 0.17+ | `apt install stress-ng` |
| fio | NVMe I/O 성능 측정 (랜덤/순차 읽쓰기) | 3.35+ | `apt install fio` |
| iperf3 | 네트워크 대역폭 측정 (bond1 포화 테스트) | 3.14+ | `apt install iperf3` |
| kubectl top | Pod/Node 리소스 사용량 실시간 확인 | kubectl 동봉 | - |
| Grafana Dashboard | 테스트 중 실시간 리소스 모니터링 | Grafana 배포 후 | Node Exporter, kube-state-metrics 활용 |

### 9.2.3 부하 시나리오 정의

| 시나리오명 | 대상 | 부하 유형 | 규모 | 지속 시간 |
|----------|------|----------|------|----------|
| SCN-01 | Prometheus | ServiceMonitor 수집 대규모화 | 500 → 1,000 → 2,000 targets (단계적) | 단계당 15분 |
| SCN-02 | Prometheus | 고카디널리티 메트릭 주입 | 100K → 500K → 1M active series | 단계당 30분 |
| SCN-03 | Prometheus | 동시 range query 발생 | 10 → 50 → 100 concurrent queries | 단계당 10분 |
| SCN-04 | Fluent Bit | 로그 폭증 (flog 사용) | 10K → 50K → 100K lines/sec | 단계당 10분 |
| SCN-05 | Fluent Bit | 멀티라인 파싱 (stacktrace) | 50% 멀티라인 혼합, 50K lines/sec | 20분 |
| SCN-06 | OpenSearch | Bulk 인덱싱 포화 | 100K → 300K → 500K docs/sec | 단계당 15분 |
| SCN-07 | OpenSearch | 검색 집계 쿼리 동시 발생 | 10 → 50 → 100 concurrent queries | 단계당 10분 |
| SCN-08 | Alertmanager | Alert storm 발생 | 100 → 500 → 1,000 concurrent alerts | 5분 |
| SCN-09 | NVMe Local PV | Prometheus + OpenSearch 동시 쓰기 | 최대 throughput 유지 | 30분 |
| SCN-10 | bond1 Network | Fluent Bit → OpenSearch bulk 전송 | 점진적 증가 (5Gbps → 40Gbps) | 단계당 10분 |

---

## 9.3 Metric 파이프라인 성능 테스트

### 9.3.1 테스트 시나리오 상세 (SCN-01 ~ SCN-03)

| 시나리오 | 세부 내용 | 부하 생성 방법 | 측정 시작 조건 |
|---------|----------|--------------|--------------|
| SCN-01-A | ServiceMonitor 500 targets 수집 | PodMonitor 500개 + stub exporter (blackbox 또는 mock) 배포 | 모든 target UP 확인 후 |
| SCN-01-B | ServiceMonitor 1,000 targets 수집 | 추가 500 stub exporter 배포 | 이전 단계 안정화 후 |
| SCN-01-C | ServiceMonitor 2,000 targets 수집 | 추가 1,000 stub exporter 배포 | 이전 단계 안정화 후 |
| SCN-02-A | 100K active series | high-cardinality-exporter (label 조합 확장) 배포 | scrape 2회 이상 완료 후 |
| SCN-02-B | 500K active series | 추가 exporter 또는 label 조합 확장 | 이전 단계 안정화 후 |
| SCN-02-C | 1M active series | 전체 확장 | 이전 단계 안정화 후 |
| SCN-03-A | 10 concurrent range query (1h 범위) | k6 스크립트로 동시 요청 발생 | TSDB 데이터 충분한 시점 |
| SCN-03-B | 50 concurrent range query (6h 범위) | k6 VU 50 설정 | - |
| SCN-03-C | 100 concurrent range query (24h 범위) | k6 VU 100 설정 | - |

**SCN-01 stub exporter 배포 예시:**

```bash
# mock-exporter Deployment (Prometheus 형식 메트릭 노출)
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mock-exporter
  namespace: monitoring-test
spec:
  replicas: 500
  selector:
    matchLabels:
      app: mock-exporter
  template:
    metadata:
      labels:
        app: mock-exporter
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
    spec:
      containers:
      - name: mock-exporter
        image: prom/statsd-exporter:latest
        ports:
        - containerPort: 8080
EOF
```

**SCN-03 k6 스크립트 예시:**

```javascript
// k6 range query 부하 테스트
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 50,
  duration: '10m',
};

export default function () {
  const end = Math.floor(Date.now() / 1000);
  const start = end - 6 * 3600; // 6h range

  const res = http.get(
    `http://prometheus-operated.monitoring.svc.cluster.local:9090/api/v1/query_range` +
    `?query=rate(container_cpu_usage_seconds_total[5m])` +
    `&start=${start}&end=${end}&step=60`
  );

  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 30s': (r) => r.timings.duration < 30000,
  });
  sleep(1);
}
```

### 9.3.2 측정 지표

| 측정 지표 | 측정 방법 | 기준 쿼리 (PromQL) | 허용 기준 |
|----------|----------|------------------|---------|
| Scrape duration p99 | Prometheus 자체 메트릭 | `histogram_quantile(0.99, rate(prometheus_target_interval_length_seconds_bucket[5m]))` | < 10s |
| Scrape 누락률 | up 메트릭 비율 | `(count(up == 0) / count(up)) * 100` | < 1% |
| CPU 사용률 | cAdvisor | `rate(container_cpu_usage_seconds_total{pod=~"prometheus-.*"}[5m])` | < 85% (81.6 cores) |
| Memory 사용량 | cAdvisor | `container_memory_working_set_bytes{pod=~"prometheus-.*"}` | < 200GB |
| TSDB write samples/sec | Prometheus 메트릭 | `rate(prometheus_tsdb_head_samples_appended_total[5m])` | > 500K samples/sec |
| NVMe 쓰기 처리량 | node-exporter | `rate(node_disk_written_bytes_total{device="nvme0n1"}[5m])` | < 5GB/s (여유 유지) |
| 쿼리 응답 시간 p99 | Prometheus 자체 메트릭 | `histogram_quantile(0.99, rate(prometheus_http_request_duration_seconds_bucket{handler="/api/v1/query_range"}[5m]))` | < 30s |
| TSDB 블록 압축 지연 | Prometheus 메트릭 | `prometheus_tsdb_compactions_failed_total` | 0 (실패 없음) |
| WAL 동기화 지연 | Prometheus 메트릭 | `prometheus_tsdb_wal_fsync_duration_seconds` | p99 < 100ms |

### 9.3.3 테스트 결과 기록표 (Metric 파이프라인)

| 시나리오 | 측정 지표 | 측정값 | 허용 기준 | Pass/Fail | 비고 |
|---------|----------|--------|---------|-----------|------|
| SCN-01-A (500 targets) | Scrape duration p99 | - | < 10s | - | |
| SCN-01-A (500 targets) | Scrape 누락률 | - | < 1% | - | |
| SCN-01-B (1,000 targets) | Scrape duration p99 | - | < 10s | - | |
| SCN-01-B (1,000 targets) | CPU 사용률 | - | < 85% | - | |
| SCN-01-C (2,000 targets) | Scrape duration p99 | - | < 10s | - | |
| SCN-01-C (2,000 targets) | Scrape 누락률 | - | < 1% | - | |
| SCN-01-C (2,000 targets) | Memory 사용량 | - | < 200GB | - | |
| SCN-02-A (100K series) | Memory 사용량 | - | < 50GB | - | |
| SCN-02-B (500K series) | Memory 사용량 | - | < 80GB | - | |
| SCN-02-C (1M series) | Memory 사용량 | - | < 150GB | - | |
| SCN-02-C (1M series) | TSDB write samples/sec | - | > 500K/s | - | |
| SCN-03-A (10 VU, 1h) | Query p99 응답시간 | - | < 10s | - | |
| SCN-03-B (50 VU, 6h) | Query p99 응답시간 | - | < 20s | - | |
| SCN-03-C (100 VU, 24h) | Query p99 응답시간 | - | < 30s | - | |
| SCN-03-C (100 VU, 24h) | CPU 사용률 | - | < 85% | - | |

---

## 9.4 Log 파이프라인 성능 테스트

### 9.4.1 테스트 시나리오 상세 (SCN-04 ~ SCN-06)

| 시나리오 | 세부 내용 | 부하 생성 방법 | 측정 시작 조건 |
|---------|----------|--------------|--------------|
| SCN-04-A | 10K lines/sec 로그 폭증 | flog -t json -r 10000 파이프 → Pod stdout | Fluent Bit 안정 수집 확인 후 |
| SCN-04-B | 50K lines/sec 로그 폭증 | flog -t json -r 50000 | 이전 단계 버퍼 드레인 후 |
| SCN-04-C | 100K lines/sec 로그 폭증 | flog -t json -r 100000 | 이전 단계 안정화 후 |
| SCN-05 | 멀티라인 파싱 (50K lines/sec, 50% stacktrace) | Java/Python 예외 로그 생성기 + flog 혼합 | Multiline 파서 설정 확인 후 |
| SCN-06-A | OpenSearch bulk 100K docs/sec | opensearch-benchmark workload: logging | 클러스터 그린 상태 확인 후 |
| SCN-06-B | OpenSearch bulk 300K docs/sec | 병렬 bulk worker 증가 | 이전 단계 안정화 후 |
| SCN-06-C | OpenSearch bulk 500K docs/sec | 최대 병렬화 | 이전 단계 안정화 후 |

**SCN-04 flog 기반 로그 폭증 테스트:**

```bash
# 테스트용 로그 생성 Pod 배포
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: log-generator
  namespace: monitoring-test
spec:
  containers:
  - name: flog
    image: mingrammer/flog:latest
    args:
      - "-t"
      - "json"
      - "-r"
      - "100000"
      - "-l"
    resources:
      requests:
        cpu: "4"
        memory: "2Gi"
      limits:
        cpu: "8"
        memory: "4Gi"
EOF
```

**SCN-05 멀티라인 stacktrace 생성:**

```python
#!/usr/bin/env python3
# stacktrace_generator.py - 멀티라인 예외 로그 생성
import time, random, json
from datetime import datetime

def generate_stacktrace():
    return (
        f"Exception in thread \"main\" java.lang.NullPointerException\n"
        f"\tat com.example.App.method{random.randint(1,10)}(App.java:{random.randint(10,200)})\n"
        f"\tat com.example.App.run(App.java:{random.randint(1,50)})\n"
        f"\tat com.example.Main.main(Main.java:15)"
    )

rate = 25000  # 50K lines/sec の半分がmultiline
while True:
    log = {
        "timestamp": datetime.utcnow().isoformat(),
        "level": "ERROR",
        "message": generate_stacktrace(),
        "app": "test-service"
    }
    print(json.dumps(log), flush=True)
    time.sleep(1 / rate)
```

**SCN-06 opensearch-benchmark 실행:**

```bash
# opensearch-benchmark 설치 및 실행
pip install opensearch-benchmark

# logging workload 실행 (bulk 인덱싱 테스트)
opensearch-benchmark execute-test \
  --target-hosts="https://opensearch.monitoring.svc.cluster.local:9200" \
  --pipeline=benchmark-only \
  --workload=logging \
  --workload-params="number_of_replicas:1,number_of_shards:3,bulk_size:5000,bulk_indexing_clients:8" \
  --client-options="use_ssl:true,verify_certs:false,basic_auth_user:admin,basic_auth_password:<password>" \
  --report-format=markdown \
  --report-file=/tmp/opensearch-benchmark-result.md
```

### 9.4.2 측정 지표

| 측정 지표 | 측정 방법 | 기준 쿼리 / 명령어 | 허용 기준 |
|----------|----------|-----------------|---------|
| Fluent Bit records/sec (처리량) | Fluent Bit 내부 메트릭 | `fluentbit_output_proc_records_total` rate | > 80K records/sec (100K 부하 시) |
| Fluent Bit 메모리 사용량 | cAdvisor | `container_memory_working_set_bytes{pod=~"fluent-bit-.*"}` | < 512Mi per pod |
| Fluent Bit 버퍼 드롭률 | Fluent Bit 메트릭 | `fluentbit_output_dropped_records_total` rate | < 0.1% |
| Fluent Bit 재시도 횟수 | Fluent Bit 메트릭 | `fluentbit_output_retried_records_total` rate | < 1% |
| OOM Kill 발생 여부 | kubectl events | `kubectl get events --field-selector reason=OOMKilling` | 0건 |
| OpenSearch docs/sec | opensearch-benchmark / opensearch 메트릭 | `GET /_nodes/stats/indices` → `indexing.index_total` rate | > 300K docs/sec |
| OpenSearch Heap 사용률 | opensearch 메트릭 | `GET /_cat/nodes?v&h=name,heap.percent` | < 75% |
| OpenSearch 인덱싱 지연 p99 | opensearch 메트릭 | `GET /_nodes/stats/indices` → `indexing.index_time_in_millis` | p99 < 500ms |
| OpenSearch GC 빈도 | opensearch 메트릭 | `GET /_nodes/stats/jvm` → `gc.collectors.old.collection_count` | 분당 < 1회 |
| bond1 TX 처리량 | node-exporter | `rate(node_network_transmit_bytes_total{device="bond1"}[1m])` | < 40Gbps |

### 9.4.3 테스트 결과 기록표 (Log 파이프라인)

| 시나리오 | 측정 지표 | 측정값 | 허용 기준 | Pass/Fail | 비고 |
|---------|----------|--------|---------|-----------|------|
| SCN-04-A (10K lines/sec) | Fluent Bit records/sec | - | > 9,500/s | - | |
| SCN-04-A (10K lines/sec) | 메모리 사용량 | - | < 256Mi | - | |
| SCN-04-B (50K lines/sec) | Fluent Bit records/sec | - | > 47,500/s | - | |
| SCN-04-B (50K lines/sec) | 버퍼 드롭률 | - | < 0.1% | - | |
| SCN-04-C (100K lines/sec) | Fluent Bit records/sec | - | > 80K/s | - | |
| SCN-04-C (100K lines/sec) | 메모리 사용량 | - | < 512Mi | - | |
| SCN-04-C (100K lines/sec) | 버퍼 드롭률 | - | < 0.1% | - | |
| SCN-04-C (100K lines/sec) | OOM Kill 여부 | - | 0건 | - | |
| SCN-05 (멀티라인 50K) | Fluent Bit records/sec | - | > 40K/s | - | 멀티라인 병합 포함 |
| SCN-05 (멀티라인 50K) | 멀티라인 파싱 정확도 | - | > 99% | - | 오파싱 확인 |
| SCN-06-A (100K docs/sec) | OpenSearch docs/sec | - | > 95K/s | - | |
| SCN-06-A (100K docs/sec) | Heap 사용률 | - | < 75% | - | |
| SCN-06-B (300K docs/sec) | OpenSearch docs/sec | - | > 270K/s | - | |
| SCN-06-B (300K docs/sec) | 인덱싱 지연 p99 | - | < 500ms | - | |
| SCN-06-C (500K docs/sec) | OpenSearch docs/sec | - | > 450K/s | - | |
| SCN-06-C (500K docs/sec) | GC 빈도 | - | 분당 < 1회 | - | |
| SCN-06-C (500K docs/sec) | Heap 사용률 | - | < 75% | - | |

---

## 9.5 Alert 파이프라인 성능 테스트

### 9.5.1 테스트 시나리오 상세 (SCN-08)

| 시나리오 | 세부 내용 | 부하 생성 방법 | 측정 시작 조건 |
|---------|----------|--------------|--------------|
| SCN-08-A | 100건 동시 alert 발생 | amtool 또는 직접 Alertmanager API POST | Alertmanager 정상 동작 확인 후 |
| SCN-08-B | 500건 동시 alert 발생 | 스크립트 기반 대량 POST | 이전 단계 큐 비워진 후 |
| SCN-08-C | 1,000건 동시 alert 발생 | 병렬 curl 스크립트 | 이전 단계 큐 비워진 후 |
| SCN-08-D | Alertmanager → k8sAlert Webhook 지연 | webhook receiver 응답 지연 시뮬레이션 | webhook 수신 서버 배포 후 |
| SCN-08-E | 채널별 발송 처리 속도 | Slack / PagerDuty / Webhook 동시 발송 | 채널 설정 확인 후 |

**SCN-08 Alert storm 생성 스크립트:**

```bash
#!/bin/bash
# alert-storm.sh - Alertmanager에 대량 alert 발송
ALERTMANAGER_URL="http://localhost:9093"
ALERT_COUNT=${1:-100}

# 포트포워드
kubectl port-forward -n monitoring svc/alertmanager-operated 9093:9093 &
PF_PID=$!
sleep 2

START_TIME=$(date +%s%3N)

# 병렬로 alert 발송
for i in $(seq 1 ${ALERT_COUNT}); do
  curl -s -X POST "${ALERTMANAGER_URL}/api/v2/alerts" \
    -H "Content-Type: application/json" \
    -d "[{
      \"labels\": {
        \"alertname\": \"TestAlert${i}\",
        \"severity\": \"warning\",
        \"instance\": \"node-${i}\",
        \"job\": \"load-test\"
      },
      \"annotations\": {
        \"summary\": \"Test alert ${i} for load testing\"
      },
      \"startsAt\": \"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\"
    }]" &
done
wait

END_TIME=$(date +%s%3N)
echo "Alert storm 발송 완료: ${ALERT_COUNT}건, 소요: $((END_TIME - START_TIME))ms"

kill ${PF_PID}
```

**Webhook 수신 서버 (지연 시뮬레이션):**

```python
#!/usr/bin/env python3
# webhook-server.py - 응답 지연 시뮬레이션
from flask import Flask, request, jsonify
import time, logging

app = Flask(__name__)
DELAY_SECONDS = 0.5  # 500ms 지연

@app.route('/webhook', methods=['POST'])
def receive_alert():
    recv_time = time.time()
    payload = request.json
    time.sleep(DELAY_SECONDS)
    proc_time = time.time()
    logging.info(f"Alert received: {len(payload.get('alerts', []))} alerts, "
                 f"processing time: {(proc_time - recv_time)*1000:.1f}ms")
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9095)
```

### 9.5.2 측정 지표

| 측정 지표 | 측정 방법 | 기준 쿼리 / 명령어 | 허용 기준 |
|----------|----------|-----------------|---------|
| E2E Latency (alert 발생 → 채널 발송) | 수동 측정 (타임스탬프 비교) | Alertmanager 로그 분석 | < 60s (정상 상태) |
| Alertmanager 큐 적체 | Alertmanager 메트릭 | `alertmanager_notifications_in_flight` | < 100건 (steady state) |
| 채널 발송 성공률 | Alertmanager 메트릭 | `rate(alertmanager_notifications_total[5m])` vs `rate(alertmanager_notifications_failed_total[5m])` | > 99% |
| Alert 처리 처리량 | Alertmanager 메트릭 | `rate(alertmanager_alerts_received_total[1m])` | > 100 alerts/sec |
| Inhibition / Silence 처리 시간 | Alertmanager 메트릭 | `alertmanager_inhibitions_total` 변화량 | < 1s 내 적용 |
| CPU 사용률 | cAdvisor | `rate(container_cpu_usage_seconds_total{pod=~"alertmanager-.*"}[5m])` | < 4 cores |
| Memory 사용량 | cAdvisor | `container_memory_working_set_bytes{pod=~"alertmanager-.*"}` | < 4Gi |
| Webhook 응답 대기 시간 | Alertmanager 메트릭 | `alertmanager_notification_latency_seconds` p99 | < 5s |

### 9.5.3 테스트 결과 기록표 (Alert 파이프라인)

| 시나리오 | 측정 지표 | 측정값 | 허용 기준 | Pass/Fail | 비고 |
|---------|----------|--------|---------|-----------|------|
| SCN-08-A (100 alerts) | E2E Latency | - | < 60s | - | |
| SCN-08-A (100 alerts) | 채널 발송 성공률 | - | > 99% | - | |
| SCN-08-B (500 alerts) | E2E Latency | - | < 120s | - | |
| SCN-08-B (500 alerts) | 큐 적체 | - | < 100건 | - | |
| SCN-08-C (1,000 alerts) | E2E Latency | - | < 300s (5분) | - | |
| SCN-08-C (1,000 alerts) | 채널 발송 성공률 | - | > 99% | - | |
| SCN-08-C (1,000 alerts) | CPU 사용률 | - | < 4 cores | - | |
| SCN-08-C (1,000 alerts) | Memory 사용량 | - | < 4Gi | - | |
| SCN-08-D (Webhook 500ms 지연) | 큐 적체 | - | < 100건 | - | |
| SCN-08-D (Webhook 500ms 지연) | 채널 발송 성공률 | - | > 99% | - | |
| SCN-08-E (멀티채널 동시 발송) | 채널별 발송 성공률 | - | > 99% | - | Slack/PagerDuty/Webhook 개별 확인 |

---

## 9.6 인프라 자원 한계 테스트

### 9.6.1 NVMe Local PV I/O 포화 테스트

**테스트 목적**: Prometheus TSDB + OpenSearch 동시 대용량 쓰기 시 NVMe I/O 경합 여부 확인

**fio를 사용한 NVMe 기준 성능 측정 (테스트 전 단독 측정):**

```bash
# NVMe 단독 순차 쓰기 성능 (기준치)
fio --name=seq-write-baseline \
    --filename=/mnt/nvme/fio-test \
    --rw=write \
    --bs=1M \
    --size=50G \
    --numjobs=4 \
    --runtime=60 \
    --time_based \
    --iodepth=32 \
    --ioengine=libaio \
    --direct=1 \
    --output=/tmp/fio-seq-write.json \
    --output-format=json

# NVMe 랜덤 쓰기 성능 (기준치)
fio --name=rand-write-baseline \
    --filename=/mnt/nvme/fio-test \
    --rw=randwrite \
    --bs=4K \
    --size=50G \
    --numjobs=4 \
    --runtime=60 \
    --time_based \
    --iodepth=64 \
    --ioengine=libaio \
    --direct=1 \
    --output=/tmp/fio-rand-write.json \
    --output-format=json
```

**동시 쓰기 부하 실행 절차:**

```bash
# Step 1: Prometheus 최대 수집 부하 발생 (SCN-01-C 실행 중 상태 유지)

# Step 2: OpenSearch 최대 인덱싱 부하 발생 (SCN-06-C 실행)

# Step 3: 동시 실행 중 NVMe I/O 상태 모니터링
iostat -x 1 -d nvme0n1 | tee /tmp/iostat-combined.log

# Step 4: NVMe 응답 시간 (latency) 모니터링
while true; do
  cat /sys/block/nvme0n1/stat | awk '{print strftime("%Y-%m-%d %H:%M:%S"), "read_ms:", $6, "write_ms:", $10}'
  sleep 1
done | tee /tmp/nvme-latency.log
```

**NVMe I/O 기준 성능표 (측정값 기록):**

| 테스트 유형 | 블록 크기 | Queue Depth | 예상 처리량 | 측정값 | 비고 |
|-----------|---------|------------|-----------|--------|------|
| 순차 쓰기 (단독) | 1MB | 32 | ~6 GB/s | - | NVMe 스펙 기준 |
| 랜덤 쓰기 (단독) | 4KB | 64 | ~500K IOPS | - | NVMe 스펙 기준 |
| 순차 쓰기 (동시 부하) | 1MB | 32 | > 3 GB/s | - | 허용 기준: 단독 대비 50% 이상 |
| 랜덤 쓰기 (동시 부하) | 4KB | 64 | > 250K IOPS | - | 허용 기준: 단독 대비 50% 이상 |
| 쓰기 latency p99 (동시) | 4KB | 64 | < 5ms | - | 허용 기준 |

### 9.6.2 bond1 (Private) 네트워크 대역폭 포화 테스트

**테스트 목적**: Fluent Bit → OpenSearch bulk 전송이 최대 40Gbps에 근접할 때의 네트워크 안정성 확인

**iperf3 기준 대역폭 측정:**

```bash
# bond1 경유 서버 측 (OpenSearch 노드)
iperf3 -s -B <bond1-ip-opensearch-node> -p 5201

# 클라이언트 측 (Fluent Bit DaemonSet 노드)
iperf3 -c <bond1-ip-opensearch-node> \
    -B <bond1-ip-fluentbit-node> \
    -p 5201 \
    -P 8 \
    -t 60 \
    -b 40G \
    --json | tee /tmp/iperf3-bond1-result.json
```

**단계별 대역폭 테스트:**

```bash
# 5Gbps 부하 테스트
iperf3 -c <opensearch-node> -P 8 -t 60 -b 5G

# 20Gbps 부하 테스트
iperf3 -c <opensearch-node> -P 8 -t 60 -b 20G

# 40Gbps 부하 테스트 (최대 목표)
iperf3 -c <opensearch-node> -P 16 -t 60 -b 40G
```

**Fluent Bit → OpenSearch 실제 전송량 모니터링:**

```bash
# bond1 TX 처리량 실시간 확인
watch -n 1 "cat /proc/net/dev | grep bond1 | awk '{printf \"TX: %.2f Gbps\n\", \$10*8/1e9}'"

# node-exporter 메트릭으로 확인
curl -s http://localhost:9100/metrics | grep 'node_network_transmit_bytes_total{device="bond1"}'
```

### 9.6.3 전체 리소스 사용률 한계 기록표

| 리소스 항목 | 테스트 조건 | 최대 사용률 (측정값) | 허용 기준 | Pass/Fail | 비고 |
|-----------|-----------|-------------------|---------|-----------|------|
| CPU (전체 노드) | SCN-01-C + SCN-06-C 동시 | - | < 85% (81.6 cores) | - | |
| CPU (Prometheus Pod) | SCN-01-C + SCN-02-C | - | < 32 cores | - | |
| CPU (OpenSearch Hot 노드) | SCN-06-C | - | < 32 cores per node | - | |
| CPU (Fluent Bit DaemonSet) | SCN-04-C | - | < 4 cores per pod | - | |
| Memory (전체 노드) | 전체 부하 동시 | - | < 900GB | - | OS/kernel 여유분 확보 |
| Memory (Prometheus) | SCN-02-C (1M series) | - | < 200GB | - | |
| Memory (OpenSearch Hot) | SCN-06-C | - | Heap < 75% (노드당) | - | |
| Memory (Fluent Bit) | SCN-04-C | - | < 512Mi per pod | - | |
| NVMe 쓰기 처리량 | SCN-09 (동시 쓰기) | - | < 5 GB/s | - | 최대 6GB/s 대비 83% |
| NVMe IOPS | SCN-09 (동시 쓰기) | - | < 400K IOPS | - | 최대 500K IOPS 대비 80% |
| NVMe 쓰기 latency p99 | SCN-09 (동시 쓰기) | - | < 5ms | - | |
| bond1 TX 처리량 | SCN-10 (최대 전송) | - | < 40Gbps | - | LACP 50Gbps 대비 80% |
| bond1 TX 패킷 드롭률 | SCN-10 (최대 전송) | - | 0건 | - | |

---

## 9.7 성능 테스트 종합 결과 및 튜닝 권고사항

### 9.7.1 종합 결과표

| 항목 | 테스트 결과 (측정값) | 허용 기준 충족 여부 | 튜닝 권고사항 |
|------|-------------------|-------------------|-------------|
| Prometheus scrape 처리 (2,000 targets) | - | - | 허용 기준 미충족 시: scrape_timeout 단축, scrape_interval 30s로 확대 검토 |
| Prometheus 고카디널리티 (1M series) | - | - | 허용 기준 미충족 시: recording rule 적용, 불필요 label 제거, limits 설정 |
| Prometheus range query (100 VU, 24h) | - | - | 허용 기준 미충족 시: query cache 활성화, step 값 증가, recording rule 사전 집계 |
| Fluent Bit 로그 처리 (100K lines/sec) | - | - | 허용 기준 미충족 시: Workers 수 증가, storage.type filesystem으로 버퍼 확장 |
| Fluent Bit 멀티라인 파싱 (50K lines/sec) | - | - | 허용 기준 미충족 시: multiline.parser timeout 축소, flush 간격 조정 |
| OpenSearch 인덱싱 (500K docs/sec) | - | - | 허용 기준 미충족 시: bulk_size 증가, refresh_interval 30s 설정, replica 0 → 1 조정 |
| OpenSearch 검색 쿼리 응답 (100 VU) | - | - | 허용 기준 미충족 시: search queue size 증가, circuit breaker 조정 |
| Alertmanager alert storm (1,000건) | - | - | 허용 기준 미충족 시: group_wait 단축, repeat_interval 조정, inhibition rule 검토 |
| NVMe I/O (동시 쓰기) | - | - | 허용 기준 미충족 시: I/O scheduler 변경 (none → mq-deadline), NUMA 바인딩 확인 |
| bond1 대역폭 (최대 전송) | - | - | 허용 기준 미충족 시: Fluent Bit compress gzip 활성화, bulk batch size 최적화 |

### 9.7.2 튜닝 파라미터 참고표

| 구성 요소 | 튜닝 파라미터 | 기본값 | 권장값 | 적용 위치 |
|----------|------------|--------|--------|----------|
| Prometheus | `scrape_interval` | 15s | 30s (대규모 환경) | prometheus.yaml |
| Prometheus | `query.max-concurrency` | 20 | 50 | prometheus args |
| Prometheus | `query.timeout` | 2m | 5m | prometheus args |
| Prometheus | `storage.tsdb.head-chunks-write-queue-size` | 0 (auto) | 4000000 | prometheus args |
| Fluent Bit | `Workers` | 1 | 4~8 | output 섹션 |
| Fluent Bit | `storage.type` | memory | filesystem | service 섹션 |
| Fluent Bit | `storage.max_chunks_up` | 128 | 1024 | service 섹션 |
| Fluent Bit | `Mem_Buf_Limit` | 5MB | 50MB | input 섹션 |
| OpenSearch | `indices.memory.index_buffer_size` | 10% | 20% | opensearch.yml |
| OpenSearch | `thread_pool.write.queue_size` | 200 | 1000 | opensearch.yml |
| OpenSearch | `indices.fielddata.cache.size` | unbounded | 20% | opensearch.yml |
| OpenSearch | `refresh_interval` | 1s | 30s (인덱싱 집중 시) | index template |
| Alertmanager | `group_wait` | 30s | 10s | alertmanager.yaml |
| Alertmanager | `group_interval` | 5m | 2m | alertmanager.yaml |

### 9.7.3 테스트 수행 체크리스트

| 단계 | 확인 항목 | 완료 여부 | 완료 일시 | 담당자 |
|------|----------|---------|---------|--------|
| 사전 준비 | 테스트 네임스페이스 생성 (`monitoring-test`) | - | - | - |
| 사전 준비 | 테스트 도구 설치 및 버전 확인 | - | - | - |
| 사전 준비 | 기준 NVMe I/O 성능 측정 (단독) | - | - | - |
| 사전 준비 | 기준 bond1 대역폭 측정 (단독) | - | - | - |
| 사전 준비 | Grafana 모니터링 대시보드 준비 | - | - | - |
| 테스트 수행 | SCN-01 (Prometheus scrape) | - | - | - |
| 테스트 수행 | SCN-02 (카디널리티) | - | - | - |
| 테스트 수행 | SCN-03 (range query) | - | - | - |
| 테스트 수행 | SCN-04 (로그 폭증) | - | - | - |
| 테스트 수행 | SCN-05 (멀티라인 파싱) | - | - | - |
| 테스트 수행 | SCN-06 (OpenSearch 인덱싱) | - | - | - |
| 테스트 수행 | SCN-07 (OpenSearch 검색) | - | - | - |
| 테스트 수행 | SCN-08 (Alert storm) | - | - | - |
| 테스트 수행 | SCN-09 (NVMe 동시 쓰기) | - | - | - |
| 테스트 수행 | SCN-10 (bond1 대역폭) | - | - | - |
| 사후 처리 | 테스트 리소스 정리 (`kubectl delete ns monitoring-test`) | - | - | - |
| 사후 처리 | 결과표 작성 및 리뷰 | - | - | - |
| 사후 처리 | 튜닝 적용 및 재검증 (필요 시) | - | - | - |
| 사후 처리 | 최종 보고서 작성 | - | - | - |

---

## 참고사항

- 모든 성능 테스트는 운영 환경과 동일한 스펙의 클러스터에서 수행해야 의미 있는 결과를 얻을 수 있다.
- 단계적 부하 증가(step-load) 방식으로 진행하며, 각 단계에서 최소 10분 이상 안정적인 상태를 유지한 후 측정값을 기록한다.
- 테스트 중 허용 기준을 초과하는 이상 징후 발생 시 즉시 해당 시나리오를 중단하고 클러스터 상태를 복구한다.
- NVMe Local PV 특성상 랜덤 쓰기 성능은 순차 쓰기 대비 낮을 수 있으며, NUMA 아키텍처 영향을 받을 수 있다.
  NUMA 바인딩(`numactl --cpunodebind=0 --membind=0`) 적용 여부를 사전에 확인한다.
- bond1 LACP 구성에서 실제 단일 스트림 처리량은 25Gbps로 제한될 수 있으며, 다중 스트림(multi-stream)으로
  최대 50Gbps 활용이 가능하다. iperf3 `-P` 옵션으로 병렬 스트림을 사용한다.
