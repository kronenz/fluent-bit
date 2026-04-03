# 관측가능성의 3대 축 (Three Pillars of Observability)

> **TL;DR**
> 1. 관측가능성(Observability)은 메트릭(Metrics), 로그(Logs), 트레이스(Traces) 3대 축으로 구성된다.
> 2. 모니터링(Monitoring)은 "알려진 문제"를 감지하고, 관측가능성은 "알 수 없었던 문제"까지 진단할 수 있게 한다.
> 3. AI 서비스는 비결정적(non-deterministic) 특성이 있어 전통적 모니터링만으로는 부족하며, 관측가능성이 필수다.

---

## 1. 핵심 개념: 관측가능성이란?

### 모니터링(Monitoring) vs 관측가능성(Observability)

| 구분 | 모니터링 (Monitoring) | 관측가능성 (Observability) |
|------|----------------------|--------------------------|
| **질문** | "시스템이 정상인가?" | "시스템이 왜 비정상인가?" |
| **접근** | 사전 정의된 지표 확인 | 임의의 질문에 답할 수 있는 능력 |
| **범위** | Known-unknowns | Unknown-unknowns |
| **비유** | 자동차 계기판 | 자동차 OBD-II 진단 포트 |

> 관측가능성은 **외부 출력(external outputs)만으로 시스템 내부 상태(internal state)를 이해할 수 있는 정도**를 의미한다 (제어 이론에서 유래).

---

## 2. 3대 축 상세

### 2-1. 메트릭 (Metrics)

**정의**: 시간에 따라 측정된 숫자 데이터의 집합

**특징**:
- 저장 비용이 낮다 (숫자만 저장)
- 집계(aggregation)에 최적화
- 시계열 데이터베이스(TSDB)에 저장

**주요 유형**:

```
# Counter - 단조 증가하는 값
http_requests_total{method="GET", status="200"} 1027

# Gauge - 증감하는 현재 값
node_memory_available_bytes 4294967296

# Histogram - 분포를 버킷으로 측정
http_request_duration_seconds_bucket{le="0.1"} 24054
http_request_duration_seconds_bucket{le="0.5"} 33444
http_request_duration_seconds_bucket{le="1.0"} 34000

# Summary - 클라이언트 측 분위수 계산
go_gc_duration_seconds{quantile="0.99"} 0.003
```

**도구 매핑**:
- Prometheus + Grafana
- Datadog Metrics
- CloudWatch Metrics
- InfluxDB + Telegraf

---

### 2-2. 로그 (Logs)

**정의**: 이산적인 이벤트의 텍스트 기록

**특징**:
- 가장 풍부한 컨텍스트 제공
- 저장 비용이 높다
- 비정형(unstructured) 또는 구조화(structured) 형태

**구조화 로그 예시 (JSON)**:

```json
{
  "timestamp": "2025-01-15T10:30:00Z",
  "level": "ERROR",
  "service": "alli-api",
  "trace_id": "abc123def456",
  "span_id": "span789",
  "message": "LLM inference timeout",
  "duration_ms": 30000,
  "model": "gpt-4",
  "user_id": "customer-42",
  "error_code": "INFERENCE_TIMEOUT"
}
```

**도구 매핑**:
- ELK Stack (Elasticsearch + Logstash + Kibana)
- EFK Stack (Elasticsearch + Fluentd/Fluent Bit + Kibana)
- Datadog Logs
- Loki + Grafana

---

### 2-3. 트레이스 (Traces)

**정의**: 분산 시스템에서 하나의 요청이 거치는 전체 경로 기록

**특징**:
- 서비스 간 인과관계(causality)를 파악
- Span의 트리 구조로 표현
- Context Propagation 필요

**트레이스 구조 예시**:

```
[Trace ID: abc123]
|
|-- [Span: API Gateway] 0ms ~ 500ms
|   |
|   |-- [Span: Auth Service] 10ms ~ 50ms
|   |
|   |-- [Span: Alli NLU] 60ms ~ 300ms
|   |   |
|   |   |-- [Span: LLM Inference] 70ms ~ 280ms
|   |   |
|   |   |-- [Span: Vector DB Query] 65ms ~ 120ms
|   |
|   |-- [Span: Response Formatting] 310ms ~ 490ms
```

**도구 매핑**:
- Jaeger
- Zipkin
- Datadog APM
- OpenTelemetry + Tempo

---

## 3. 3대 축의 연계 (Correlation)

핵심은 **3개 축을 연결(correlate)하는 것**이다.

```
[알림 발생] 에러율 5% 초과 (Metric)
    |
    v
[대시보드 확인] 어떤 엔드포인트에서 에러가 발생하는가? (Metric Drill-down)
    |
    v
[트레이스 확인] 해당 요청의 호출 경로는? 어디서 느려지는가? (Trace)
    |
    v
[로그 확인] 해당 Span에서 구체적으로 무슨 에러가 발생했는가? (Log)
```

### 연계를 위한 필수 요소

```yaml
# 공통 식별자 (Correlation ID)
trace_id: "abc123def456"  # 모든 로그, 메트릭, 트레이스에 포함

# Exemplar - 메트릭에 트레이스 ID를 연결
# Prometheus에서 Exemplar 활성화
http_request_duration_seconds_bucket{le="0.5"} 1000 # {trace_id="abc123"}
```

---

## 4. 올거나이즈(Allganize) AI 서비스에서의 관측가능성

### AI 서비스가 전통적 서비스와 다른 점

| 특성 | 전통적 서비스 | AI 서비스 (Alli 등) |
|------|-------------|-------------------|
| **응답 결정성** | 결정적 (deterministic) | 비결정적 (non-deterministic) |
| **지연 시간** | ms 단위 예측 가능 | LLM 호출로 수초~수십초 |
| **비용 구조** | 컴퓨팅 리소스 | 토큰 기반 과금 추가 |
| **품질 측정** | 정확한 정답 비교 가능 | 주관적 품질 평가 필요 |

### AI 서비스를 위한 관측가능성 확장

```
전통적 3대 축 + AI 특화 관측
|
|-- Metrics: 토큰 사용량, 모델 응답 시간, hallucination 비율
|-- Logs: 프롬프트/응답 쌍, 모델 버전, temperature 설정
|-- Traces: LLM 호출 체인, RAG 파이프라인 각 단계 시간
|-- [추가] Evaluation: 응답 품질 점수, 사용자 피드백
```

---

## 5. 10년 경력 연결 포인트

> **경력자의 강점**: 10년간 인프라를 운영하며 모니터링 시스템의 진화를 경험했다.
> Nagios/Zabbix 시대의 상태 기반 모니터링 -> Prometheus 시대의 메트릭 중심 모니터링 -> OpenTelemetry 시대의 통합 관측가능성까지, 각 단계의 한계를 체감하고 왜 관측가능성이 필요한지 **실무 경험으로 설명**할 수 있다.

---

## 6. 면접 Q&A

### Q1. 모니터링과 관측가능성의 차이를 설명해주세요.

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "모니터링은 '시스템이 정상인가?'라는 질문에 답합니다. CPU, 메모리, 에러율 같은 사전에 정의한 지표를 대시보드에 띄우고 임계치를 넘으면 알림을 보내는 것이죠. 반면 관측가능성은 '왜 비정상인가?'에 답하는 능력입니다. 메트릭, 로그, 트레이스를 연계해서 사전에 예상하지 못한 문제도 추적할 수 있습니다. 예를 들어 AI 서비스에서 특정 고객의 응답 품질이 떨어지는 문제는, 에러율 메트릭에는 잡히지 않지만, 트레이스로 RAG 파이프라인을 추적하고 로그에서 검색 결과를 확인하면 원인을 찾을 수 있습니다."

### Q2. 관측가능성 3대 축 중 가장 중요한 것은?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "상황에 따라 다르지만, 운영 관점에서는 메트릭이 가장 먼저 필요합니다. 문제를 가장 빨리 감지할 수 있기 때문입니다. 하지만 원인 분석에는 트레이스와 로그가 필수입니다. 제가 10년간 인프라를 운영하면서 느낀 것은, 메트릭만으로는 '어디서 느린지'는 알 수 있지만 '왜 느린지'는 알 수 없다는 것입니다. 결국 3개 축이 모두 필요하고, 핵심은 이들을 trace_id 같은 공통 식별자로 연결하는 것입니다."

### Q3. AI 서비스의 관측가능성은 기존 서비스와 어떻게 다른가요?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "AI 서비스는 세 가지 측면에서 다릅니다. 첫째, 응답이 비결정적이라 같은 입력에도 다른 출력이 나올 수 있어 기존의 정답 비교 방식이 통하지 않습니다. 둘째, LLM 호출로 인한 지연 시간이 기존 마이크로서비스보다 훨씬 길고 가변적입니다. 셋째, 토큰 사용량이 직접 비용으로 연결되어 비용 관측가능성도 필요합니다. 올거나이즈의 Alli 같은 AI 서비스에서는 전통적인 RED 메트릭에 더해 토큰 사용량, 모델 응답 시간 분포, RAG 검색 정확도 같은 AI 특화 지표를 추가로 수집해야 합니다."

### Q4. 올거나이즈에서 관측가능성을 구축한다면 어떻게 시작하겠는가?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "우선 가장 비즈니스 임팩트가 큰 API 엔드포인트부터 시작합니다. Alli 서비스라면 사용자 질의 API가 될 것입니다. 1단계로 Prometheus + Grafana로 RED 메트릭(Rate, Error, Duration)을 수집하고, 2단계로 OpenTelemetry SDK를 적용해 LLM 호출과 벡터 DB 검색 구간의 분산 추적을 구현합니다. 3단계로 구조화 로그에 trace_id를 포함시켜 3대 축을 연계합니다. 동시에 SLI/SLO를 정의해서 에러 버짓 기반으로 알림을 운영합니다."

---

## 핵심 키워드 5선

`Observability` `Three Pillars (Metrics/Logs/Traces)` `Correlation ID` `Unknown-Unknowns` `OpenTelemetry`
