# Prometheus & Grafana 심층 가이드

> **TL;DR**
> 1. Prometheus는 Pull 기반 메트릭 수집 + TSDB + AlertManager로 구성된 모니터링 생태계의 핵심이다.
> 2. PromQL의 `rate()`, `histogram_quantile()`, `increase()`는 실무에서 가장 많이 쓰는 3대 함수다.
> 3. Prometheus Operator의 ServiceMonitor/PodMonitor로 Kubernetes 환경에서 자동화된 메트릭 수집을 구현한다.

---

## 1. Prometheus 아키텍처

### 전체 구성도

```
                    +-----------------+
                    |  AlertManager   |
                    |  (알림 라우팅)    |
                    +--------^--------+
                             |
+----------+    scrape    +--+------------+    query    +---------+
| Targets  | <-----------+  Prometheus    +-----------> | Grafana |
| (앱/노드) |   pull 방식  |  Server       |            | (시각화) |
+----------+             |  - TSDB       |            +---------+
                         |  - Rules      |
+----------+             |  - Service    |
| Service  | <-- SD ---->+  Discovery    |
| Discovery|             +--+------------+
+----------+                |
  (K8s API,                 v
   Consul,          +--------------+
   File SD)         | Remote Write |
                    | (Thanos/     |
                    |  Cortex/Mimir)|
                    +--------------+
```

### 핵심 구성 요소

| 구성 요소 | 역할 | 설명 |
|----------|------|------|
| **Prometheus Server** | 메트릭 수집 및 저장 | Pull 방식으로 타겟에서 메트릭을 스크래핑 |
| **TSDB** | 시계열 데이터 저장 | 로컬 디스크, 2시간 블록 단위 압축 |
| **AlertManager** | 알림 라우팅/그룹핑 | 중복 제거, 음소거, 알림 전송 |
| **Pushgateway** | 단기 작업 메트릭 수집 | 배치 잡 등 Pull이 불가한 경우 |
| **Service Discovery** | 타겟 자동 발견 | Kubernetes API, Consul, 파일 기반 |

### Pull vs Push 모델

```yaml
# Pull 모델 (Prometheus 기본)
# 장점: 타겟 상태 파악 가능 (스크래핑 실패 = 타겟 다운)
# 장점: 중앙에서 수집 주기 제어
# 단점: 방화벽 뒤의 타겟 수집 어려움

# Push 모델 (Datadog, InfluxDB)
# 장점: 방화벽 환경에서 유리
# 장점: 단기 작업 메트릭 수집 용이
# 단점: 타겟 상태를 별도 확인 필요
```

---

## 2. Prometheus 설정

### 기본 설정 파일 (prometheus.yml)

```yaml
global:
  scrape_interval: 15s          # 기본 스크래핑 주기
  evaluation_interval: 15s      # Rule 평가 주기
  scrape_timeout: 10s           # 스크래핑 타임아웃

# 알림 규칙 파일
rule_files:
  - "rules/*.yml"

# AlertManager 연결
alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093

# 스크래핑 대상 정의
scrape_configs:
  # Prometheus 자체 메트릭
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # Kubernetes Pod 자동 발견
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      # prometheus.io/scrape 어노테이션이 true인 Pod만 수집
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      # 커스텀 포트 지정
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}:${2}

  # Node Exporter
  - job_name: 'node-exporter'
    kubernetes_sd_configs:
      - role: node
    relabel_configs:
      - action: replace
        target_label: __address__
        replacement: ${1}:9100
```

---

## 3. PromQL 핵심 쿼리 패턴

### 3-1. rate() - 초당 변화율

```promql
# HTTP 요청의 초당 처리율 (최근 5분 기준)
rate(http_requests_total[5m])

# 서비스별, 상태 코드별 요청률
sum by (service, status_code) (
  rate(http_requests_total[5m])
)

# 에러율 (%) 계산 - 가장 많이 쓰는 패턴
sum(rate(http_requests_total{status_code=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))
* 100
```

> **주의**: `rate()`는 반드시 Counter 타입에만 사용한다. Gauge에는 `deriv()`를 사용.

### 3-2. histogram_quantile() - 분위수 계산

```promql
# p99 응답 시간 (99번째 백분위수)
histogram_quantile(0.99,
  sum by (le) (
    rate(http_request_duration_seconds_bucket[5m])
  )
)

# 서비스별 p95 응답 시간
histogram_quantile(0.95,
  sum by (service, le) (
    rate(http_request_duration_seconds_bucket[5m])
  )
)

# p50 (중앙값) - 일반적인 사용자 경험
histogram_quantile(0.50,
  sum by (le) (
    rate(http_request_duration_seconds_bucket[5m])
  )
)
```

> **실무 팁**: 히스토그램 버킷 설계가 중요하다. AI 서비스는 응답 시간이 길므로 버킷을 넓게 설정해야 한다.

```python
# Python 클라이언트 - AI 서비스용 히스토그램 버킷 예시
from prometheus_client import Histogram

llm_request_duration = Histogram(
    'llm_request_duration_seconds',
    'LLM request duration',
    ['model', 'endpoint'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
)
```

### 3-3. increase() - 구간 내 증가량

```promql
# 최근 1시간 동안의 총 요청 수
increase(http_requests_total[1h])

# 최근 24시간 동안의 에러 수
sum(increase(http_requests_total{status_code=~"5.."}[24h]))

# 일별 토큰 사용량 (AI 서비스)
sum by (model) (
  increase(llm_token_usage_total[24h])
)
```

### 3-4. 실무에서 자주 쓰는 추가 패턴

```promql
# 현재 진행 중인 요청 수 (Gauge)
sum(http_requests_in_flight)

# 메모리 사용률 (%)
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100

# Pod 재시작 감지
increase(kube_pod_container_status_restarts_total[1h]) > 0

# CPU 스로틀링 비율
sum by (pod) (
  rate(container_cpu_cfs_throttled_seconds_total[5m])
)
/
sum by (pod) (
  rate(container_cpu_usage_seconds_total[5m])
)

# 디스크 사용량 예측 - 4시간 후 디스크 풀 예측
predict_linear(node_filesystem_avail_bytes[6h], 4*3600) < 0
```

---

## 4. 알림 규칙 (Alerting Rules)

### 실행 가능한 알림 규칙 예시

```yaml
# rules/alli-service-alerts.yml
groups:
  - name: alli-service
    rules:
      # 높은 에러율 알림
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status_code=~"5..", service="alli-api"}[5m]))
          /
          sum(rate(http_requests_total{service="alli-api"}[5m]))
          > 0.05
        for: 5m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Alli API 에러율 5% 초과"
          description: "현재 에러율: {{ $value | humanizePercentage }}"
          runbook_url: "https://wiki.internal/runbook/high-error-rate"

      # 느린 응답 시간 알림
      - alert: HighLatencyP99
        expr: |
          histogram_quantile(0.99,
            sum by (le) (
              rate(http_request_duration_seconds_bucket{service="alli-api"}[5m])
            )
          ) > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Alli API p99 응답 시간 5초 초과"

      # LLM 토큰 비용 급증 알림
      - alert: TokenUsageSpike
        expr: |
          sum(rate(llm_token_usage_total[1h]))
          > 2 * sum(rate(llm_token_usage_total[1h] offset 1d))
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "LLM 토큰 사용량이 전일 대비 2배 초과"

      # Pod 재시작 반복
      - alert: PodCrashLooping
        expr: |
          increase(kube_pod_container_status_restarts_total{
            namespace="alli-production"
          }[1h]) > 3
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "{{ $labels.pod }} 가 1시간 내 3회 이상 재시작"
```

---

## 5. Grafana 대시보드 설계

### RED Method 대시보드 구성

```
+------------------------------------------+
|           Alli API Overview              |
+------------------------------------------+
| [Rate]        | [Error]      | [Duration] |
| 요청률 그래프  | 에러율 그래프  | p50/p95/p99|
| (req/s)       | (%)          | (seconds)  |
+------------------------------------------+
| [Saturation]                              |
| CPU 사용률 | 메모리 사용률 | Pod 수       |
+------------------------------------------+
| [LLM Specific]                            |
| 토큰 사용량 | 모델별 응답시간 | 비용 추이  |
+------------------------------------------+
```

### Grafana 알림 설정 (Unified Alerting)

```yaml
# Grafana Alerting Rule (JSON Provisioning)
{
  "apiVersion": 1,
  "groups": [
    {
      "orgId": 1,
      "name": "alli-alerts",
      "folder": "Alli Service",
      "interval": "1m",
      "rules": [
        {
          "uid": "alli-error-rate",
          "title": "Alli API High Error Rate",
          "condition": "C",
          "data": [
            {
              "refId": "A",
              "datasourceUid": "prometheus",
              "model": {
                "expr": "sum(rate(http_requests_total{status=~\"5..\",service=\"alli\"}[5m]))",
                "intervalMs": 1000
              }
            }
          ],
          "noDataState": "Alerting",
          "execErrState": "Alerting",
          "for": "5m",
          "labels": {
            "severity": "critical"
          },
          "notifications": [
            { "uid": "slack-oncall" }
          ]
        }
      ]
    }
  ]
}
```

---

## 6. Prometheus Operator (Kubernetes)

### ServiceMonitor - 서비스 메트릭 자동 수집

```yaml
# ServiceMonitor: 특정 Service를 선택하여 메트릭 수집
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: alli-api-monitor
  namespace: monitoring
  labels:
    release: prometheus    # Prometheus Operator가 인식하는 라벨
spec:
  namespaceSelector:
    matchNames:
      - alli-production
  selector:
    matchLabels:
      app: alli-api        # 이 라벨을 가진 Service 대상
  endpoints:
    - port: metrics        # Service의 포트 이름
      interval: 15s
      path: /metrics
      scrapeTimeout: 10s
      # 메트릭 relabeling
      metricRelabelings:
        - sourceLabels: [__name__]
          regex: 'go_.*'   # Go 런타임 메트릭 제외
          action: drop
```

### PodMonitor - Service 없이 Pod 직접 수집

```yaml
# PodMonitor: Service가 없는 Pod에서 직접 메트릭 수집
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: alli-worker-monitor
  namespace: monitoring
spec:
  namespaceSelector:
    matchNames:
      - alli-production
  selector:
    matchLabels:
      app: alli-worker     # 이 라벨을 가진 Pod 대상
  podMetricsEndpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

### PrometheusRule - 알림 규칙을 CRD로 관리

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: alli-alerts
  namespace: monitoring
  labels:
    release: prometheus
spec:
  groups:
    - name: alli.rules
      rules:
        - alert: AlliAPIDown
          expr: up{job="alli-api"} == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Alli API 인스턴스 다운"
```

---

## 7. 장기 저장 (Long-term Storage)

```
Prometheus (단기: 15일)
    |
    | remote_write
    v
+---+---+
| Thanos | 또는 | Mimir | 또는 | Cortex |
+---+---+
    |
    v
Object Storage (S3/GCS) - 장기 보관 (수개월~수년)
```

```yaml
# Prometheus remote_write 설정
remote_write:
  - url: "http://mimir-distributor:9009/api/v1/push"
    queue_config:
      max_samples_per_send: 1000
      batch_send_deadline: 5s
```

---

## 8. 10년 경력 연결 포인트

> **경력자의 강점**: Nagios/Zabbix에서 Prometheus로의 전환 경험이 있다면, 왜 Pull 모델이 클라우드 네이티브 환경에 적합한지, Service Discovery가 왜 필수인지를 실무 경험으로 설명할 수 있다. 또한 PromQL의 `rate()`와 `irate()`의 차이, 히스토그램 버킷 설계의 실수 사례 등을 공유하면 깊이를 보여줄 수 있다.

---

## 9. 면접 Q&A

### Q1. Prometheus의 Pull 방식이 Push 방식보다 좋은 이유는?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "Pull 방식의 핵심 장점은 세 가지입니다. 첫째, 스크래핑 실패 자체가 타겟 다운을 의미하므로 별도의 헬스체크 없이 장애를 감지할 수 있습니다. 둘째, 수집 주기를 중앙에서 통제하므로 메트릭 폭주(metric flood)를 방지할 수 있습니다. 셋째, 디버깅 시 타겟의 /metrics 엔드포인트에 직접 접근해서 현재 메트릭을 확인할 수 있어 문제 해결이 빠릅니다. 다만 NAT/방화벽 환경이나 서버리스 함수처럼 수명이 짧은 워크로드에서는 Pushgateway나 Push 기반 솔루션이 더 적합합니다."

### Q2. rate()와 irate()의 차이는?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "`rate()`는 지정한 시간 범위 전체의 평균 변화율을 계산합니다. `rate(http_requests_total[5m])`은 5분 동안의 평균 초당 요청 수입니다. `irate()`는 마지막 두 데이터 포인트만으로 순간 변화율을 계산합니다. rate()는 알림 규칙에 적합하고, irate()는 대시보드에서 순간적인 스파이크를 시각화할 때 적합합니다. 실무에서 알림에 irate()를 사용하면 순간 스파이크에 과민 반응하여 알림 피로(alert fatigue)가 발생합니다."

### Q3. Prometheus의 확장 한계와 해결 방안은?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "Prometheus는 단일 인스턴스 아키텍처라 수평 확장이 어렵습니다. 메트릭 카디널리티가 높아지면 메모리와 디스크가 부족해지고, 로컬 TSDB는 장기 보관에 적합하지 않습니다. 해결책으로 세 가지를 조합합니다. 첫째, Thanos나 Mimir로 장기 저장과 글로벌 쿼리를 구현합니다. 둘째, 수집 대상을 샤딩하여 여러 Prometheus 인스턴스로 분산합니다. 셋째, 불필요한 라벨과 메트릭을 relabeling으로 제거하여 카디널리티를 관리합니다."

### Q4. Grafana 대시보드를 설계할 때 가장 중요한 원칙은?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "USE Method(Utilization, Saturation, Errors)와 RED Method(Rate, Errors, Duration)를 기본 프레임워크로 사용합니다. 가장 중요한 원칙은 '액션 가능한 대시보드'를 만드는 것입니다. 대시보드를 보고 즉시 행동을 결정할 수 있어야 합니다. 실무에서 저는 3단계 계층으로 구성합니다. 1단계는 비즈니스 KPI 개요, 2단계는 서비스별 RED 메트릭, 3단계는 인프라 리소스 상세입니다. 또한 모든 대시보드를 JSON으로 코드화하여 GitOps로 관리합니다."

---

## 핵심 키워드 5선

`Prometheus Pull Model` `PromQL (rate/histogram_quantile)` `Grafana RED Dashboard` `ServiceMonitor/PodMonitor` `Thanos/Mimir (Long-term Storage)`
