# Datadog 통합 모니터링과 비용 관리

> **TL;DR**: Datadog은 Metrics/APM/Logs/Traces를 통합하는 SaaS 모니터링 플랫폼으로, Agent 기반 데이터 수집이 핵심이다.
> APM은 서비스 맵과 트레이스 분석, Log Management는 인덱싱 없는 로그도 검색 가능한 Flex Logs를 제공한다.
> 커스텀 메트릭과 인덱싱 볼륨이 비용의 핵심 변수이므로, 태그 설계와 샘플링 전략이 중요하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### Datadog 아키텍처

```
┌─────────────── Kubernetes Cluster ──────────────────┐
│                                                      │
│  ┌──────────┐   ┌──────────┐    ┌──────────────┐   │
│  │ App Pod  │   │ App Pod  │    │ App Pod      │   │
│  │ + OTel   │   │ + dd-    │    │ + StatsD     │   │
│  │   SDK    │   │   trace  │    │   client     │   │
│  └────┬─────┘   └────┬─────┘    └──────┬───────┘   │
│       │               │                 │            │
│       ▼               ▼                 ▼            │
│  ┌──────────────────────────────────────────────┐   │
│  │           Datadog Agent (DaemonSet)           │   │
│  │  ┌────────┐ ┌──────┐ ┌───────┐ ┌──────────┐ │   │
│  │  │Metrics │ │ APM  │ │ Logs  │ │ Process  │ │   │
│  │  │Collect │ │Trace │ │Collect│ │ Agent    │ │   │
│  │  └────────┘ └──────┘ └───────┘ └──────────┘ │   │
│  └──────────────────────┬───────────────────────┘   │
│                         │ HTTPS                      │
└─────────────────────────┼────────────────────────────┘
                          ▼
                ┌──────────────────┐
                │   Datadog SaaS   │
                │  ┌────────────┐  │
                │  │ Metrics    │  │ ← 시계열 저장/쿼리
                │  │ APM        │  │ ← 서비스 맵/트레이스
                │  │ Logs       │  │ ← 로그 인덱싱/아카이브
                │  │ Dashboards │  │ ← 통합 시각화
                │  │ Monitors   │  │ ← 알림/이상감지
                │  └────────────┘  │
                └──────────────────┘
```

### Datadog Agent (K8s DaemonSet)

```yaml
# Helm으로 Datadog Agent 배포
# helm install datadog datadog/datadog -f values.yaml
# values.yaml
datadog:
  apiKey: <DATADOG_API_KEY>
  appKey: <DATADOG_APP_KEY>
  site: datadoghq.com        # 또는 us5.datadoghq.com, datadoghq.eu

  # Logs 수집
  logs:
    enabled: true
    containerCollectAll: true  # 모든 컨테이너 로그 수집

  # APM 트레이스 수집
  apm:
    portEnabled: true          # 8126 포트

  # Process 모니터링
  processAgent:
    enabled: true
    processCollection: true

  # Kubernetes 통합
  kubeStateMetricsEnabled: true
  kubeStateMetricsCore:
    enabled: true

  # Prometheus 메트릭 수집 (OpenMetrics)
  prometheusScrape:
    enabled: true
    serviceEndpoints: true

agents:
  containers:
    agent:
      resources:
        requests:
          memory: 256Mi
          cpu: 200m
        limits:
          memory: 512Mi
          cpu: 500m
```

### Datadog APM

```
서비스 맵 (Service Map):
┌──────────┐     ┌──────────┐     ┌─────────────┐
│  nginx   │────►│ alli-api │────►│ model-svc   │
│ (web)    │     │ (python) │     │ (python)    │
│ 1.2K/s   │     │ 800/s    │     │ 200/s       │
│ p99:20ms │     │ p99:150ms│     │ p99:800ms   │
└──────────┘     │          │     └─────────────┘
                 │          │
                 │          ├────►┌─────────────┐
                 │          │     │ redis       │
                 │          │     │ (cache)     │
                 │          │     │ hit:95%     │
                 │          │     └─────────────┘
                 │          │
                 │          └────►┌─────────────┐
                 └───────────────►│ mongodb     │
                                  │ (datastore) │
                                  │ p99:15ms    │
                                  └─────────────┘
```

APM 핵심 기능:
- **Service Map**: 서비스 간 의존성과 각 서비스의 RPS/에러율/레이턴시를 한눈에
- **Trace Explorer**: 개별 트레이스 검색 및 워터폴 뷰
- **Service Page**: 서비스별 상세 성능 메트릭 (엔드포인트별 분석)
- **Error Tracking**: 에러 자동 그룹핑, 스택트레이스, 영향도 분석
- **Continuous Profiler**: 코드 레벨 CPU/메모리 프로파일링

### Log Management

```
Log Pipeline:
Ingest → Process → Index/Archive

┌────────────┐    ┌──────────────┐    ┌─────────────┐
│ Log Ingest │───►│  Pipelines   │───►│   Index     │
│ (수집)     │    │  ┌─────────┐ │    │  (검색가능)  │
│            │    │  │ Parser  │ │    └──────┬──────┘
│            │    │  │ Remap   │ │           │
│            │    │  │ Filter  │ │    ┌──────▼──────┐
│            │    │  │ Enrich  │ │    │  Archive    │
│            │    │  └─────────┘ │    │  (S3, 저비용)│
│            │    └──────────────┘    └─────────────┘
```

**Exclusion Filters**: 인덱싱 전에 불필요한 로그 제외 (비용 절감의 핵심)
```
# 헬스체크 로그 제외
source:nginx status:200 path:/health*

# 디버그 레벨 로그 제외 (프로덕션)
@level:debug
```

**Log-based Metrics**: 인덱싱하지 않은 로그에서도 메트릭 생성 가능
```
# 로그에서 커스텀 메트릭 생성
count:logs{service:alli-api, status:error} by {endpoint}
→ alli.api.error.count (태그: endpoint)
```

### 커스텀 메트릭

```python
# DogStatsD로 커스텀 메트릭 전송
from datadog import statsd

# Gauge: LLM 모델 로딩 상태
statsd.gauge('alli.model.loaded', 1,
             tags=['model:gpt-4', 'env:prod'])

# Counter: 추론 요청 수
statsd.increment('alli.inference.count',
                 tags=['model:gpt-4', 'status:success'])

# Histogram: 추론 지연시간 분포
statsd.histogram('alli.inference.latency',
                 value=latency_ms,
                 tags=['model:gpt-4', 'endpoint:/v1/chat'])

# Distribution: 글로벌 백분위 (서버 간 집계 가능)
statsd.distribution('alli.inference.duration',
                    value=duration_seconds,
                    tags=['model:gpt-4'])
```

### 비용 관리 전략

```
Datadog 비용 구조:
┌───────────────────────────────────────────────────────┐
│ 인프라 호스트: $15~23/host/month                      │
│ APM 호스트: $31~40/host/month                         │
│ 로그 인덱싱: $1.70/GB (15일 보존)                     │
│ 로그 수집(Ingest): $0.10/GB                           │
│ 커스텀 메트릭: $0.05/metric/month (100개 이후)         │
│ Span 수집: $1.70/GB ingested spans                    │
└───────────────────────────────────────────────────────┘

비용 폭발 주요 원인:
1. 커스텀 메트릭 카디널리티 (user_id, request_id 태그 금지!)
2. 로그 전량 인덱싱 (Exclusion Filter 미설정)
3. APM Trace 전수 수집 (샘플링 미설정)
```

**비용 최적화 체크리스트**:
```
☐ 태그 카디널리티 검토: 태그 값이 1,000개 이상이면 재설계
☐ Exclusion Filters: 헬스체크, 디버그 로그 인덱싱 제외
☐ Log Archive: S3로 아카이브하고, 필요 시 Rehydration
☐ APM Ingestion Controls: 서비스별 샘플링률 조정
☐ Metrics without Limits: 불필요한 태그 조합 쿼리 제한
☐ 커밋 기반 요금제: 연간 계약으로 on-demand 대비 30~50% 절감
☐ 팀별 사용량 대시보드: 누가 얼마나 쓰는지 가시화
```

---

## 실전 예시

### Datadog Monitor (알림 규칙) 설정

```python
# Terraform으로 Datadog Monitor 정의
resource "datadog_monitor" "alli_error_rate" {
  name    = "Alli API Error Rate > 1%"
  type    = "query alert"
  message = <<-EOT
    Alli API 에러율이 {{threshold}}%를 초과했습니다.
    현재값: {{value}}%
    서비스: {{service.name}}

    @slack-alli-alerts @pagerduty-alli-oncall
  EOT

  query = <<-EOQ
    sum(last_5m):
      sum:trace.http.request.errors{service:alli-api,env:prod}.as_rate()
      / sum:trace.http.request.hits{service:alli-api,env:prod}.as_rate()
      * 100 > 1
  EOQ

  monitor_thresholds {
    critical = 1
    warning  = 0.5
  }

  notify_no_data    = true
  no_data_timeframe = 10
  renotify_interval = 30

  tags = ["service:alli-api", "env:prod", "team:platform"]
}
```

### Unified Tagging 전략

```yaml
# 모든 리소스에 일관된 태그 적용
# env, service, version 은 Datadog의 Unified Service Tagging 표준

# K8s Pod Labels (→ Datadog 태그로 자동 변환)
metadata:
  labels:
    tags.datadoghq.com/env: "production"
    tags.datadoghq.com/service: "alli-api"
    tags.datadoghq.com/version: "1.2.3"
  annotations:
    ad.datadoghq.com/alli-api.logs: |
      [{
        "source": "python",
        "service": "alli-api",
        "log_processing_rules": [{
          "type": "exclude_at_match",
          "name": "exclude_healthcheck",
          "pattern": "GET /health"
        }]
      }]
```

---

## 면접 Q&A

### Q: Datadog의 장단점과 Prometheus/Grafana 대비 선택 기준은?
**30초 답변**: Datadog은 Metrics/APM/Logs/Traces를 하나의 SaaS에서 통합 제공하여 운영 부담이 낮고 상관 분석이 쉽습니다. 반면 비용이 높고 벤더 락인이 있습니다. Prometheus/Grafana는 오픈소스로 비용이 낮지만 운영/통합 부담이 있습니다.

**2분 답변**: Datadog의 핵심 강점은 **통합(Unified Experience)**입니다. 메트릭 그래프에서 이상 구간을 선택하면 해당 시간의 트레이스와 로그로 바로 전환(Pivot)할 수 있습니다. 이것이 개별 도구(Prometheus+Jaeger+ELK)를 조합하면 달성하기 어려운 가치입니다. 또한 700개 이상의 통합(AWS, K8s, MongoDB, Redis 등)이 즉시 사용 가능하고, AI 기반 이상 감지(Anomaly Detection), Watchdog이 자동으로 이상을 탐지합니다. 단점으로는, 첫째 **비용**: 호스트당 월 $40~60(APM+Logs), 50대 클러스터면 월 $3,000+. 둘째 **벤더 락인**: Datadog 전용 쿼리 언어, 대시보드, 알림을 다른 시스템으로 이전하기 어려움. 셋째 **데이터 주권**: SaaS이므로 모든 데이터가 외부로 전송됨(규제 환경에서 제한). 실무에서는 하이브리드 접근이 효과적입니다: 인프라 메트릭은 Prometheus(비용 효율), APM/트레이스는 Datadog(통합 분석), 로그는 Loki(비용)+Datadog(중요 로그만).

**경험 연결**: 폐쇄망에서는 SaaS 도구 사용이 불가능하여 오픈소스만 사용했습니다. 클라우드 환경에서는 운영 부담과 엔지니어 시간 비용을 고려하면 Datadog 같은 SaaS가 합리적인 선택이 될 수 있습니다.

**주의**: "Datadog이 비싸다"로만 끝내지 말 것. 엔지니어가 모니터링 인프라 운영에 쓰는 시간의 기회비용도 계산해야 한다.

### Q: Datadog 비용 최적화 전략은?
**30초 답변**: 비용의 핵심은 커스텀 메트릭 카디널리티, 로그 인덱싱 볼륨, APM Span 수집량입니다. Exclusion Filters로 불필요한 로그 인덱싱을 막고, 태그 카디널리티를 1,000 미만으로 관리하며, APM 샘플링률을 조정합니다.

**2분 답변**: Datadog 비용 최적화는 네 가지 축으로 접근합니다. 첫째, **로그**: 모든 로그를 인덱싱하지 않습니다. Ingestion Pipeline에서 Exclusion Filter로 헬스체크, 디버그 로그를 제외하고, Log-based Metrics로 인덱싱 없이 메트릭만 추출합니다. 나머지는 S3로 Archive하고 필요 시 Rehydration합니다. 둘째, **커스텀 메트릭**: user_id, request_id 같은 고카디널리티 태그를 절대 사용하지 않습니다. Metrics without Limits 기능으로 쿼리에 사용하지 않는 태그 조합을 제거합니다. 셋째, **APM**: Ingestion Controls에서 서비스별 샘플링률을 설정합니다. 헬스체크 엔드포인트는 0%, 핵심 API는 100%, 나머지는 20%. 넷째, **요금제**: on-demand보다 committed use 계약이 30~50% 저렴합니다. 팀별 사용량 대시보드를 만들어 비용 인식을 높이는 것도 중요합니다.

**경험 연결**: IT 인프라 비용 관리 경험에서, 모니터링 비용은 전체 인프라 비용의 10~20%까지 올라갈 수 있습니다. "무엇을 모니터링할 것인가"의 설계가 비용의 핵심입니다.

**주의**: 비용 절감을 위해 샘플링을 너무 공격적으로 하면 장애 분석 시 데이터가 부족할 수 있다. 비용과 가시성의 균형을 강조할 것.

### Q: Datadog의 Unified Service Tagging이란?
**30초 답변**: 모든 텔레메트리 데이터(Metrics, Traces, Logs)에 `env`, `service`, `version` 세 가지 태그를 일관되게 적용하는 Datadog의 표준입니다. 이를 통해 메트릭에서 트레이스로, 트레이스에서 로그로 원클릭 전환이 가능합니다.

**2분 답변**: Unified Service Tagging은 Datadog의 상관 분석(Correlation)을 가능하게 하는 핵심 메커니즘입니다. K8s 환경에서는 Pod 레이블(`tags.datadoghq.com/env`, `tags.datadoghq.com/service`, `tags.datadoghq.com/version`)을 설정하면, Datadog Agent가 자동으로 해당 Pod의 모든 메트릭, 트레이스, 로그에 이 태그를 붙입니다. 이점은 세 가지입니다. 첫째, **서비스 카탈로그**: 모든 서비스를 `service` 태그로 자동 등록하여 소유자, 의존성, SLO를 관리합니다. 둘째, **배포 추적**: `version` 태그로 특정 배포 후 에러율 증가를 감지하고, 해당 버전의 트레이스만 필터링합니다. 셋째, **환경 분리**: `env` 태그로 prod/staging 데이터를 명확히 구분하여 알림 노이즈를 줄입니다. 구현 시에는 CI/CD 파이프라인에서 이미지 빌드 시 `DD_VERSION` 환경변수를 설정하고, Helm values에서 Pod 레이블을 템플릿화합니다.

**경험 연결**: 여러 환경의 서버를 관리할 때 네이밍 규칙(hostname, 태그)의 일관성이 없으면 운영이 혼란스러웠습니다. Unified Tagging은 이를 표준화하는 좋은 접근입니다.

**주의**: version 태그는 Git SHA보다 Semantic Versioning이 대시보드 가독성에 유리하다.

---

## Allganize 맥락

- **JD 키워드**: "Prometheus/Grafana/Datadog" - Datadog은 명시적으로 언급된 필수 도구
- **SaaS vs 오픈소스**: Allganize 규모에서 Datadog의 통합 기능은 소수 DevOps 팀의 운영 부담을 크게 줄여줌
- **APM for LLM**: Alli 서비스의 추론 파이프라인을 APM으로 트레이싱하여 병목 구간(모델 로딩, GPU 대기) 식별
- **비용 의식**: 스타트업에서 모니터링 비용 최적화는 중요한 운영 과제. 면접에서 비용 관리 경험/전략을 보여주면 좋은 인상
- **멀티클라우드 통합**: AWS/Azure 양쪽의 K8s 클러스터를 Datadog 하나로 통합 모니터링

---
**핵심 키워드**: `Datadog` `Agent` `APM` `Service-Map` `Log-Management` `Exclusion-Filter` `Custom-Metrics` `DogStatsD` `Unified-Tagging` `Cost-Optimization` `Ingestion-Controls`
