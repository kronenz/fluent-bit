# Prometheus 메트릭 수집과 PromQL

> **TL;DR**: Prometheus는 Pull 기반 시계열 데이터베이스로, 타겟을 주기적으로 스크래핑하여 메트릭을 수집한다.
> Counter/Gauge/Histogram/Summary 4가지 메트릭 타입을 이해하면 대부분의 모니터링 시나리오를 커버할 수 있다.
> PromQL은 시계열 데이터의 필터링, 집계, 연산을 위한 함수형 쿼리 언어이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Prometheus 아키텍처

```
                          ┌─────────────────────┐
                          │   Alertmanager       │
                          │  (알림 라우팅/그룹핑)  │
                          └──────────▲───────────┘
                                     │ alert rules
┌──────────┐  scrape    ┌────────────┴────────────┐    query   ┌──────────┐
│ Exporter │◄───────────│      Prometheus Server   │◄──────────│ Grafana  │
│ (target) │  /metrics  │                          │  PromQL   │          │
└──────────┘            │  ┌─────────┐ ┌────────┐ │           └──────────┘
                        │  │  TSDB   │ │  Rules │ │
┌──────────┐  scrape    │  │(시계열DB)│ │(평가)  │ │
│ App with │◄───────────│  └─────────┘ └────────┘ │
│ /metrics │            └────────────┬────────────┘
└──────────┘                         │
                                     │ remote_write
┌──────────┐  push      ┌───────────▼───────────┐
│ Short-   │───────────►│    Pushgateway         │
│ lived Job│            │  (단기 작업용)          │
└──────────┘            └───────────────────────┘
```

**Pull vs Push 모델**:
- **Pull (Prometheus 기본)**: Prometheus가 주기적으로 타겟의 `/metrics` 엔드포인트를 HTTP GET으로 스크래핑
- **Push (Pushgateway)**: 배치 잡처럼 수명이 짧은 프로세스가 Pushgateway에 메트릭을 푸시
- Pull 모델의 장점: 타겟이 죽으면 `up` 메트릭이 0이 되어 자동 감지, 서비스 디스커버리와 결합 용이

**Service Discovery**:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
```

K8s 환경에서는 Pod annotation(`prometheus.io/scrape: "true"`)을 기반으로 자동 디스커버리한다.

### 4가지 메트릭 타입

| 타입 | 설명 | 특성 | 대표 예시 |
|------|------|------|----------|
| **Counter** | 단조 증가만 하는 누적값 | 리셋 시 0부터 재시작, `rate()` 필수 | `http_requests_total`, `node_cpu_seconds_total` |
| **Gauge** | 올라가거나 내려가는 현재값 | 즉시 사용 가능, 스냅샷 성격 | `node_memory_available_bytes`, `kube_pod_status_ready` |
| **Histogram** | 값을 버킷(bucket)에 분배 | 서버 사이드 백분위 계산, `histogram_quantile()` 사용 | `http_request_duration_seconds_bucket` |
| **Summary** | 클라이언트에서 백분위 계산 | 집계 불가(pre-calculated), phi-quantile | `go_gc_duration_seconds` |

**Histogram vs Summary 선택 기준**:
```
Histogram 선택:                    Summary 선택:
├─ 여러 인스턴스 집계 필요 ✅       ├─ 단일 인스턴스에서만 조회
├─ 버킷 범위 사전 정의 가능         ├─ 정확한 백분위 필요
├─ SLO 기반 버킷 설계              ├─ 버킷 설계 어려움
└─ 권장 (대부분의 경우)             └─ 레거시/특수 경우만
```

### PromQL 핵심 쿼리

**Instant Vector vs Range Vector**:
```promql
# Instant Vector: 현재 시점의 단일 값
http_requests_total{method="GET", status="200"}

# Range Vector: 시간 범위의 값 목록 (rate/increase와 함께 사용)
http_requests_total{method="GET"}[5m]
```

**필수 함수들**:

```promql
# 1. rate(): Counter의 초당 변화율 (range vector → instant vector)
rate(http_requests_total{job="api-server"}[5m])

# 2. increase(): 지정 기간 동안의 증가량
increase(http_requests_total{status="500"}[1h])

# 3. histogram_quantile(): 백분위 계산
histogram_quantile(0.99,
  rate(http_request_duration_seconds_bucket{job="api"}[5m])
)

# 4. sum by(): 레이블별 집계
sum by (namespace, pod) (
  rate(container_cpu_usage_seconds_total[5m])
)

# 5. topk(): 상위 N개 시계열
topk(10,
  sum by (pod) (rate(container_memory_working_set_bytes[5m]))
)

# 6. absent(): 메트릭 부재 감지 (dead man's switch)
absent(up{job="critical-service"})
```

**실전 패턴 - RED 메서드 (Request/Error/Duration)**:
```promql
# Rate: 초당 요청 수
sum(rate(http_requests_total[5m])) by (service)

# Error: 에러율 (%)
sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
/ sum(rate(http_requests_total[5m])) by (service) * 100

# Duration: 99th 백분위 응답시간
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service)
)
```

**실전 패턴 - USE 메서드 (Utilization/Saturation/Errors)**:
```promql
# CPU Utilization
1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance)

# Memory Saturation (swap 사용)
rate(node_vmstat_pswpin[5m]) + rate(node_vmstat_pswpout[5m])

# Disk Errors
rate(node_disk_io_time_weighted_seconds_total[5m])
```

### TSDB와 데이터 보존

```
Prometheus TSDB 디스크 구조:
data/
├── 01BKGV7JBM69T2G1BGBGM6KB12/   ← Block (2h 기본)
│   ├── chunks/                     ← 실제 시계열 데이터
│   │   └── 000001
│   ├── tombstones                  ← 삭제 마커
│   ├── index                       ← 레이블 인덱스
│   └── meta.json                   ← 블록 메타데이터
├── chunks_head/                    ← 현재 기록 중인 데이터
├── wal/                            ← Write-Ahead Log
└── lock
```

- 기본 보존: 15일 (`--storage.tsdb.retention.time=15d`)
- 장기 보존: Thanos/Cortex/Mimir로 Remote Write → Object Storage(S3)

---

## 실전 예시

### Kubernetes에서 Prometheus 배포 (kube-prometheus-stack)

```bash
# Helm으로 kube-prometheus-stack 설치
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set prometheus.prometheusSpec.retention=30d \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi
```

### 커스텀 메트릭 계측 (Python)

```python
from prometheus_client import Counter, Histogram, start_http_server
import time

# Counter: LLM 추론 요청 수
llm_requests_total = Counter(
    'llm_requests_total',
    'Total LLM inference requests',
    ['model', 'status']
)

# Histogram: LLM 추론 지연시간 (SLO 기반 버킷)
llm_latency_seconds = Histogram(
    'llm_latency_seconds',
    'LLM inference latency in seconds',
    ['model'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

def handle_inference(model_name, prompt):
    with llm_latency_seconds.labels(model=model_name).time():
        try:
            result = run_inference(model_name, prompt)
            llm_requests_total.labels(model=model_name, status="success").inc()
            return result
        except Exception:
            llm_requests_total.labels(model=model_name, status="error").inc()
            raise

if __name__ == '__main__':
    start_http_server(8000)  # /metrics 엔드포인트 노출
```

### Recording Rules로 쿼리 최적화

```yaml
# recording-rules.yaml
groups:
  - name: api_performance
    interval: 30s
    rules:
      - record: job:http_request_duration_seconds:p99
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (job, le)
          )
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)
      - record: job:http_errors:ratio5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
          / sum(rate(http_requests_total[5m])) by (job)
```

---

## 면접 Q&A

### Q: Prometheus의 Pull 모델이 Push 모델 대비 갖는 장단점은?
**30초 답변**: Pull 모델은 Prometheus가 타겟을 주기적으로 스크래핑하므로, 타겟이 다운되면 `up==0`으로 즉시 감지됩니다. Service Discovery와 결합하면 새 타겟을 자동 등록할 수 있고, 메트릭 수집 주기를 중앙에서 제어합니다.

**2분 답변**: Pull 모델의 핵심 장점은 세 가지입니다. 첫째, 모니터링 대상의 생존 여부를 스크래핑 실패로 자동 감지합니다. Push 모델은 에이전트가 보내지 않는 것이 장애인지 정상 종료인지 구분하기 어렵습니다. 둘째, 서비스 디스커버리와 결합하면 K8s Pod가 스케일아웃될 때 annotation만 있으면 자동으로 수집 대상에 추가됩니다. 셋째, 스크래핑 간격과 타임아웃을 Prometheus 설정에서 중앙 관리할 수 있습니다. 반면 단점으로는, 방화벽이나 NAT 뒤에 있는 타겟은 접근이 어려울 수 있고(Pushgateway나 Federation으로 해결), 단기 배치 잡은 스크래핑 전에 종료될 수 있어 Pushgateway가 필요합니다. 또한 대규모 환경에서는 수천 개 타겟 스크래핑의 부하를 고려해야 합니다.

**경험 연결**: 폐쇄망 환경에서 Zabbix Agent(Push 방식)를 운영했는데, 에이전트가 죽어도 "데이터 없음"과 "서버 다운"을 구분하기 어려워 별도 헬스체크를 만들었습니다. Prometheus의 Pull 모델은 이 문제를 구조적으로 해결합니다.

**주의**: "Prometheus는 항상 Pull이다"라고 단정하지 말 것. Pushgateway, Remote Write, OpenTelemetry Collector를 통한 Push 경로도 존재한다.

### Q: Counter와 Gauge의 차이, 그리고 Counter에 rate()를 써야 하는 이유는?
**30초 답변**: Counter는 단조 증가하는 누적값(요청 수, 에러 수), Gauge는 증감 가능한 현재값(메모리, 온도)입니다. Counter의 원시값은 계속 증가하므로 의미 없고, `rate()`로 초당 변화율을 구해야 실제 처리량을 알 수 있습니다.

**2분 답변**: Counter는 프로세스 시작부터 누적된 값이므로, 원시값 자체는 "총 100만 요청"처럼 절대량만 보여줍니다. `rate(counter[5m])`는 5분간의 데이터 포인트를 기반으로 초당 평균 변화율을 계산합니다. 중요한 점은 `rate()`가 Counter 리셋(프로세스 재시작)을 자동 처리한다는 것입니다. 값이 갑자기 0으로 떨어지면 리셋으로 인식하고, 새로운 값을 이전 값에 더해서 계산합니다. `irate()`는 마지막 두 데이터 포인트만 사용하므로 더 민감하지만 노이즈가 많고, `increase()`는 `rate() * 시간`으로 기간 내 총 증가량을 반환합니다. Gauge는 현재값 자체가 의미있으므로 `rate()` 없이 바로 사용하거나, `deriv()`로 변화 추세를 볼 수 있습니다.

**경험 연결**: 네트워크 장비 모니터링에서 인터페이스 트래픽(ifInOctets)이 Counter 타입이라 MRTG/Cacti에서도 delta 계산을 했습니다. 같은 원리를 Prometheus에서 `rate()`로 적용하는 것입니다.

**주의**: `rate()`의 range window(`[5m]`)는 최소 스크래핑 간격의 4배 이상을 권장. 15초 간격이면 `[1m]` 이상.

### Q: Histogram의 bucket 설계 시 고려사항과 SLO 연계 방법은?
**30초 답변**: Histogram 버킷은 SLO 경계값을 포함하도록 설계합니다. 예를 들어 "99% 요청이 500ms 이내" SLO라면 `{le="0.5"}` 버킷이 반드시 있어야 합니다. 버킷이 너무 적으면 정밀도가 떨어지고, 너무 많으면 카디널리티가 폭증합니다.

**2분 답변**: Histogram은 `_bucket`, `_sum`, `_count` 세 가지 시계열을 생성합니다. `_bucket`은 `le`(less than or equal) 레이블로 구분되며, 각 버킷은 해당 값 이하인 관측값의 누적 개수입니다. `histogram_quantile(0.99, rate(my_histogram_bucket[5m]))`로 p99를 계산하는데, 이때 버킷 사이의 값은 선형 보간(linear interpolation)으로 추정합니다. 따라서 버킷 경계가 실제 분포와 맞지 않으면 오차가 큽니다. 설계 원칙: (1) SLO 임계값을 버킷에 포함 - 500ms SLO면 `0.5` 버킷 필수, (2) 예상 분포의 범위를 커버 - 너무 크거나 작은 버킷은 낭비, (3) 지수적 간격(0.1, 0.25, 0.5, 1, 2.5, 5, 10)이 대부분의 레이턴시 분포에 적합, (4) 레이블 카디널리티 주의 - 버킷 10개 x 메서드 5개 x 엔드포인트 20개 = 시계열 1,000개. Native Histogram(Prometheus 2.40+)은 버킷을 동적으로 조정하여 이 문제를 개선합니다.

**경험 연결**: LLM 추론 서비스는 모델 크기에 따라 응답 시간 분포가 크게 다릅니다. 작은 모델은 100ms~1s, 큰 모델은 1s~30s 범위이므로, 모델별로 다른 버킷 설계가 필요합니다. Allganize의 Alli 서비스도 유사할 것입니다.

**주의**: `histogram_quantile()`의 결과는 추정값이다. 정확한 백분위가 필요하면 Summary를 쓰되, Summary는 인스턴스 간 집계가 불가능하다는 트레이드오프를 설명할 것.

### Q: Prometheus의 High Availability와 장기 보존 전략은?
**30초 답변**: Prometheus HA는 동일 설정의 두 인스턴스를 독립 운영하고, Alertmanager의 deduplication으로 중복 알림을 방지합니다. 장기 보존은 Remote Write로 Thanos나 Cortex/Mimir에 데이터를 보내 S3 같은 Object Storage에 저장합니다.

**2분 답변**: Prometheus 단일 인스턴스는 SPOF입니다. HA 구성은 두 가지 수준으로 나뉩니다. 첫째, **수집 HA**: 동일한 설정의 Prometheus 2대가 같은 타겟을 독립적으로 스크래핑합니다. 데이터가 약간 다를 수 있지만(타이밍 차이), Alertmanager가 `--cluster` 모드로 중복 알림을 제거합니다. 둘째, **장기 보존**: Prometheus의 로컬 TSDB는 15~30일 보존이 일반적입니다. Thanos 아키텍처에서는 Sidecar가 2시간 블록을 S3에 업로드하고, Querier가 로컬+S3 데이터를 통합 조회합니다. Compactor가 오래된 블록을 다운샘플링(5m→1h 해상도)하여 스토리지 비용을 줄입니다. 대안으로 Grafana Mimir는 수평 확장이 가능한 TSDB로, 멀티테넌시와 장기 보존을 한번에 해결합니다. Allganize처럼 멀티클라우드(AWS/Azure) 환경에서는 각 클러스터의 Prometheus가 중앙 Thanos/Mimir로 Remote Write하는 구조가 효과적입니다.

**경험 연결**: 온프레미스에서는 스토리지 용량이 제한적이라 보존 기간을 짧게 잡아야 했습니다. 클라우드 환경에서 S3 기반 장기 보존은 비용 대비 효율이 높아, Allganize의 멀티클라우드 모니터링 통합에 적합한 전략입니다.

**주의**: Thanos와 Cortex/Mimir의 차이를 물어볼 수 있음. Thanos는 Sidecar 방식(기존 Prometheus에 붙임), Mimir는 완전한 Remote Write 수신자(Prometheus를 가벼운 수집기로 전환).

---

## Allganize 맥락

- **JD 키워드**: "Prometheus/Grafana/Datadog 기반 모니터링" - Prometheus가 기본 메트릭 수집 레이어
- **LLM 서비스 메트릭**: Alli의 추론 지연시간, 토큰 처리량, GPU 사용률, 모델 로딩 시간이 핵심 메트릭
- **멀티클라우드**: AWS EKS + Azure AKS 각각에 Prometheus를 배포하고, 중앙 집계(Thanos/Mimir 또는 Datadog)로 통합 뷰 구성
- **카디널리티 관리**: 사용자별/세션별 메트릭 레이블은 카디널리티 폭발을 일으키므로, 집계 레벨 설계가 중요
- **비용**: Prometheus 자체는 오픈소스이지만, 장기 보존 스토리지와 Grafana Cloud/Datadog 연동 시 비용 최적화 필요

---
**핵심 키워드**: `Prometheus` `PromQL` `Counter` `Gauge` `Histogram` `rate()` `Service-Discovery` `TSDB` `Remote-Write` `Thanos` `RED-Method` `Recording-Rules`
