# 분산 추적 (Distributed Tracing)

> **TL;DR**
> 1. 분산 추적은 Trace > Span > Event 계층으로 구성되며, Context Propagation이 핵심 메커니즘이다.
> 2. OpenTelemetry(OTel)가 사실상 표준(de facto standard)이며, SDK + Collector + Exporter 아키텍처다.
> 3. AI 서비스(LLM, RAG)에서는 추론 파이프라인 각 단계의 지연 시간과 토큰 소비를 추적하는 것이 핵심이다.

---

## 1. 분산 추적의 핵심 개념

### 왜 분산 추적이 필요한가?

```
[사용자 요청: "회의록 요약해줘"]
    |
    v
API Gateway --> Auth Service --> Alli NLU Service --> Vector DB
                                      |                  |
                                      v                  v
                                 LLM Service        Embedding Service
                                      |
                                      v
                                Response Builder --> API Gateway --> 사용자

문제: 응답이 5초 걸렸다. 어디서 느린가?
- 로그만으로는 각 서비스의 개별 시간만 알 수 있다
- 분산 추적은 전체 호출 체인과 각 구간의 시간을 한눈에 보여준다
```

### 핵심 용어

| 용어 | 정의 | 비유 |
|------|------|------|
| **Trace** | 하나의 요청이 시스템을 관통하는 전체 경로 | 택배 추적 번호 |
| **Span** | Trace 내 하나의 작업 단위 | 택배가 거치는 각 중간 거점 |
| **Root Span** | Trace의 시작점 (가장 상위 Span) | 발송지 |
| **Child Span** | 다른 Span에 의해 호출된 Span | 중간 경유지 |
| **Context** | Trace ID + Span ID + 메타데이터 | 택배 송장 |
| **Baggage** | Trace 전체에 전파되는 키-값 쌍 | 택배에 붙은 추가 스티커 |

### Span 구조

```json
{
  "trace_id": "abc123def456ghi789",
  "span_id": "span001",
  "parent_span_id": null,
  "operation_name": "POST /api/v1/chat",
  "service_name": "alli-api-gateway",
  "start_time": "2025-01-15T10:30:00.000Z",
  "duration_ms": 4500,
  "status": "OK",
  "attributes": {
    "http.method": "POST",
    "http.url": "/api/v1/chat",
    "http.status_code": 200,
    "user.id": "customer-42"
  },
  "events": [
    {
      "name": "request_validated",
      "timestamp": "2025-01-15T10:30:00.050Z"
    }
  ],
  "links": []
}
```

---

## 2. Context Propagation (컨텍스트 전파)

### 동작 원리

```
Service A                    Service B                    Service C
+----------+                +----------+                +----------+
| Span A   |  HTTP Header   | Span B   |  gRPC Metadata | Span C   |
| trace=abc| -------------> | trace=abc| -------------> | trace=abc|
| span=001 |  traceparent:  | span=002 |  traceparent:  | span=003 |
+----------+  00-abc-001-01 +----------+  00-abc-002-01 +----------+
```

### W3C Trace Context 표준

```
# HTTP 헤더 형식
traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
             |   |                                |                |
           version  trace-id (32 hex)          parent-id (16 hex)  flags
                                                                    01 = sampled

# 예시 HTTP 요청
GET /api/v1/chat HTTP/1.1
Host: alli-api.allganize.ai
traceparent: 00-abc123def456ghi789jkl012mno345-span001parent00-01
tracestate: dd=s:1;o:rum
baggage: user.id=customer-42,session.id=sess-789
```

### Python 코드에서 컨텍스트 전파

```python
# OpenTelemetry 자동 계측 (Auto-instrumentation)
# 대부분의 HTTP 클라이언트/서버 프레임워크를 자동 지원

# pip install opentelemetry-instrumentation-fastapi
# pip install opentelemetry-instrumentation-requests
# pip install opentelemetry-instrumentation-grpc

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# 자동 계측 활성화
FastAPIInstrumentor.instrument_app(app)    # 서버 측: 자동으로 Span 생성
RequestsInstrumentor().instrument()         # 클라이언트 측: 자동으로 헤더 전파
```

---

## 3. OpenTelemetry (OTel) 아키텍처

### 전체 구조

```
+------------------+     +-------------------+     +------------------+
|   Application    |     |   OTel Collector  |     |    Backend       |
|                  |     |                   |     |                  |
| +- OTel SDK ---+ |     | +- Receiver ---+ |     | +- Jaeger ----+ |
| | Tracer       | | --> | | OTLP         | | --> | | UI + Storage| |
| | Meter        | |     | | Prometheus   | |     | +-------------+ |
| | Logger       | |     | | Zipkin       | |     |                  |
| +- Exporter --+ |     | +- Processor -+ |     | +- Datadog ---+ |
| | OTLP        | |     | | Batch       | |     | | APM         | |
| | Console     | |     | | Filter      | |     | +-------------+ |
| +-----------+ |     | | Sampling    | |     |                  |
|                  |     | +- Exporter -+ |     | +- Tempo -----+ |
|                  |     | | OTLP       | |     | | + Grafana   | |
|                  |     | | Jaeger     | |     | +-------------+ |
|                  |     | | Datadog    | |     |                  |
|                  |     | +------------+ |     |                  |
+------------------+     +-------------------+     +------------------+
```

### OTel SDK 설정 (Python)

```python
# otel_setup.py - OpenTelemetry 초기화
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

# 리소스 정의 (서비스 메타데이터)
resource = Resource.create({
    SERVICE_NAME: "alli-api",
    "service.version": "2.3.1",
    "deployment.environment": "production",
    "service.namespace": "allganize",
})

# TracerProvider 설정
provider = TracerProvider(resource=resource)

# OTLP Exporter -> Collector로 전송
otlp_exporter = OTLPSpanExporter(
    endpoint="http://otel-collector:4317",
    insecure=True
)

# BatchSpanProcessor: 성능을 위해 배치로 전송
provider.add_span_processor(
    BatchSpanProcessor(
        otlp_exporter,
        max_queue_size=2048,
        max_export_batch_size=512,
        schedule_delay_millis=5000
    )
)

trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)
```

### OTel Collector 설정

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  # 배치 처리
  batch:
    timeout: 5s
    send_batch_size: 1024
    send_batch_max_size: 2048

  # 메모리 제한
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128

  # 샘플링 (트래픽이 많을 때 비용 절감)
  tail_sampling:
    decision_wait: 10s
    policies:
      # 에러가 있는 트레이스는 100% 수집
      - name: error-policy
        type: status_code
        status_code:
          status_codes: [ERROR]
      # 느린 요청은 100% 수집
      - name: latency-policy
        type: latency
        latency:
          threshold_ms: 3000
      # 나머지는 10% 샘플링
      - name: probabilistic-policy
        type: probabilistic
        probabilistic:
          sampling_percentage: 10

  # 속성 추가/수정
  attributes:
    actions:
      - key: environment
        value: production
        action: upsert

exporters:
  # Jaeger로 내보내기
  jaeger:
    endpoint: jaeger-collector:14250
    tls:
      insecure: true

  # Datadog으로 내보내기
  datadog:
    api:
      key: ${DD_API_KEY}
    traces:
      endpoint: https://trace.agent.datadoghq.com

  # 디버깅용 콘솔 출력
  logging:
    loglevel: debug

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, tail_sampling, batch]
      exporters: [jaeger, datadog]
```

---

## 4. Jaeger & Zipkin 비교

| 구분 | Jaeger | Zipkin |
|------|--------|--------|
| **출처** | Uber (CNCF 졸업) | Twitter |
| **언어** | Go | Java |
| **저장소** | Elasticsearch, Cassandra, Kafka | Elasticsearch, MySQL, Cassandra |
| **UI** | 강력한 비교/분석 기능 | 심플하고 직관적 |
| **아키텍처** | Agent -> Collector -> DB | Reporter -> Collector -> DB |
| **적합 환경** | 대규모, CNCF 생태계 | 소규모, 빠른 시작 |

### Jaeger Kubernetes 배포 (Operator)

```yaml
# Jaeger Operator CRD
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: alli-jaeger
  namespace: observability
spec:
  strategy: production      # all-in-one / production / streaming
  collector:
    replicas: 2
    resources:
      limits:
        cpu: 500m
        memory: 512Mi
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: https://elasticsearch:9200
        index-prefix: alli-traces
    esIndexCleaner:
      enabled: true
      numberOfDays: 14       # 14일 보관
      schedule: "55 23 * * *"
  query:
    replicas: 1
  ingress:
    enabled: true
```

---

## 5. AI 서비스에서의 분산 추적

### LLM 요청 추적 패턴

```python
from opentelemetry import trace

tracer = trace.get_tracer("alli-ai-service")

async def process_user_query(query: str, user_id: str):
    # Root Span: 전체 요청
    with tracer.start_as_current_span("process_query") as root_span:
        root_span.set_attribute("user.id", user_id)
        root_span.set_attribute("query.length", len(query))

        # Child Span 1: 의도 분석
        with tracer.start_as_current_span("intent_classification") as span:
            intent = await classify_intent(query)
            span.set_attribute("intent.type", intent.type)
            span.set_attribute("intent.confidence", intent.confidence)

        # Child Span 2: RAG - 문서 검색
        with tracer.start_as_current_span("rag_retrieval") as span:
            # Child Span 2-1: 임베딩 생성
            with tracer.start_as_current_span("embedding_generation") as embed_span:
                embedding = await generate_embedding(query)
                embed_span.set_attribute("embedding.model", "text-embedding-ada-002")
                embed_span.set_attribute("embedding.dimensions", len(embedding))

            # Child Span 2-2: 벡터 DB 검색
            with tracer.start_as_current_span("vector_search") as search_span:
                docs = await vector_db.search(embedding, top_k=5)
                search_span.set_attribute("search.results_count", len(docs))
                search_span.set_attribute("search.top_score", docs[0].score)

        # Child Span 3: LLM 추론
        with tracer.start_as_current_span("llm_inference") as span:
            span.set_attribute("llm.model", "gpt-4")
            span.set_attribute("llm.temperature", 0.7)
            span.set_attribute("llm.max_tokens", 2000)

            response = await call_llm(
                model="gpt-4",
                messages=build_prompt(query, docs),
                temperature=0.7
            )

            span.set_attribute("llm.prompt_tokens", response.usage.prompt_tokens)
            span.set_attribute("llm.completion_tokens", response.usage.completion_tokens)
            span.set_attribute("llm.total_tokens", response.usage.total_tokens)
            span.set_attribute("llm.finish_reason", response.finish_reason)

            # 토큰 비용 계산
            cost = calculate_cost(response.usage, model="gpt-4")
            span.set_attribute("llm.cost_usd", cost)

        # Child Span 4: 응답 후처리
        with tracer.start_as_current_span("post_processing") as span:
            final_response = await format_response(response)
            span.set_attribute("response.length", len(final_response))

        root_span.set_attribute("total.tokens", response.usage.total_tokens)
        root_span.set_attribute("total.cost_usd", cost)
        return final_response
```

### Jaeger UI에서 보이는 결과

```
[Trace: abc123] - 총 4.5초
|
|-- [process_query] 0ms ~ 4500ms ========================
|   |
|   |-- [intent_classification] 10ms ~ 150ms ===
|   |
|   |-- [rag_retrieval] 160ms ~ 900ms ========
|   |   |
|   |   |-- [embedding_generation] 170ms ~ 350ms ===
|   |   |
|   |   |-- [vector_search] 360ms ~ 890ms ======
|   |
|   |-- [llm_inference] 910ms ~ 4200ms ==================  <-- 병목!
|   |   attributes:
|   |     llm.model = gpt-4
|   |     llm.total_tokens = 3500
|   |     llm.cost_usd = 0.105
|   |
|   |-- [post_processing] 4210ms ~ 4490ms ===
```

> 이 트레이스를 통해 LLM 추론이 전체 시간의 73%를 차지한다는 것을 즉시 파악할 수 있다.

---

## 6. 샘플링 전략 (Sampling)

### Head-based vs Tail-based Sampling

```
[Head-based Sampling] - 요청 시작 시 결정
장점: 구현이 간단, 리소스 부담 적음
단점: 에러 요청을 놓칠 수 있음

Client --> 10% 확률로 샘플링 결정 --> 수집 or 버림

[Tail-based Sampling] - 요청 완료 후 결정
장점: 에러/느린 요청을 100% 수집 가능
단점: Collector에서 메모리 사용, 복잡성 증가

Client --> 전부 전송 --> Collector에서 판단 --> 중요한 것만 저장
```

### 실무 권장 샘플링 정책

```yaml
# Tail-based Sampling 정책
policies:
  # 1순위: 에러는 무조건 수집
  - name: errors-always
    type: status_code
    status_code:
      status_codes: [ERROR]

  # 2순위: 3초 이상 느린 요청 수집
  - name: slow-requests
    type: latency
    latency:
      threshold_ms: 3000

  # 3순위: 특정 서비스의 요청 수집 (디버깅 중인 서비스)
  - name: debug-service
    type: string_attribute
    string_attribute:
      key: service.name
      values: [alli-nlu-service]

  # 4순위: 나머지는 5% 샘플링
  - name: default
    type: probabilistic
    probabilistic:
      sampling_percentage: 5
```

---

## 7. 10년 경력 연결 포인트

> **경력자의 강점**: 분산 추적이 없던 시대에 "로그 grep"으로 장애 원인을 찾던 경험이 있다면, 분산 추적의 가치를 가장 잘 설명할 수 있다. 또한 다양한 프로토콜(HTTP, gRPC, 메시지 큐)을 다뤄본 경험은 Context Propagation의 난이도를 이해하는 데 직결된다. OpenTelemetry 도입 시 기존 시스템에 어떻게 점진적으로 적용할지, 샘플링 비율을 어떻게 결정할지 등 실무적 판단력이 시니어의 차별점이다.

---

## 8. 면접 Q&A

### Q1. 분산 추적의 동작 원리를 설명해주세요.

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "분산 추적은 세 가지 핵심 요소로 동작합니다. 첫째, Trace ID는 하나의 요청을 고유하게 식별하는 ID로, 최초 진입점에서 생성됩니다. 둘째, 각 서비스에서 수행하는 작업 단위를 Span으로 기록하고, 부모-자식 관계를 통해 호출 트리를 형성합니다. 셋째, Context Propagation으로 서비스 간 호출 시 HTTP 헤더(W3C traceparent)나 gRPC 메타데이터를 통해 Trace ID와 Span ID를 전달합니다. 이를 통해 여러 서비스에 흩어진 Span들을 하나의 Trace로 조합하여 전체 요청 경로와 각 구간의 소요 시간을 시각화할 수 있습니다."

### Q2. OpenTelemetry를 기존 서비스에 도입하는 전략은?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "점진적 도입 전략을 사용합니다. 1단계로 OTel Collector를 먼저 배포하고 기존 메트릭(Prometheus)을 Collector를 통해 수집하도록 전환합니다. 코드 변경 없이 인프라만 변경하는 것이죠. 2단계로 자동 계측(Auto-instrumentation)을 적용합니다. Python이라면 `opentelemetry-instrument` 명령어로 코드 수정 없이 HTTP, DB 호출의 기본 트레이스를 수집합니다. 3단계로 비즈니스 로직에 중요한 구간에 수동 Span을 추가합니다. AI 서비스라면 LLM 호출, RAG 검색 같은 핵심 구간입니다. 이렇게 하면 리스크를 최소화하면서 점진적으로 관측가능성을 확보할 수 있습니다."

### Q3. AI 서비스에서 분산 추적이 특히 중요한 이유는?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "AI 서비스는 파이프라인이 복잡하고 각 단계의 지연 시간 편차가 큽니다. 올거나이즈의 Alli를 예로 들면, 사용자 질의가 의도 분석 -> 문서 검색(RAG) -> 임베딩 생성 -> 벡터 DB 검색 -> LLM 추론 -> 후처리 순서로 처리됩니다. LLM 추론 단계만 수백 밀리초에서 수십 초까지 변동하기 때문에, 분산 추적 없이는 병목 지점을 특정할 수 없습니다. 또한 토큰 사용량을 Span 속성으로 기록하면 비용 추적도 가능합니다. 특정 고객의 요청이 비정상적으로 많은 토큰을 소비하는 패턴을 트레이스에서 바로 발견할 수 있습니다."

### Q4. Tail-based Sampling과 Head-based Sampling의 차이는?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "Head-based는 요청 시작 시점에 수집 여부를 확률적으로 결정합니다. 구현이 간단하고 리소스 부담이 적지만, 에러 요청이 샘플링에서 제외될 수 있습니다. Tail-based는 요청 완료 후 결과를 보고 결정합니다. 에러가 발생했거나 지연 시간이 긴 요청은 100% 수집하고, 정상 요청은 낮은 비율로 샘플링할 수 있습니다. 실무에서는 Tail-based를 권장하되, Collector의 메모리 사용량을 모니터링해야 합니다. OTel Collector의 tail_sampling 프로세서에서 decision_wait을 적절히 설정하는 것이 핵심입니다."

---

## 핵심 키워드 5선

`Span/Trace/Context Propagation` `OpenTelemetry (OTel)` `W3C Trace Context` `Tail-based Sampling` `LLM Request Tracing`
