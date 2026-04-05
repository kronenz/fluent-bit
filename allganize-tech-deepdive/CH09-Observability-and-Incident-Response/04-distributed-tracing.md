# 분산 트레이싱: OpenTelemetry, Jaeger, Zipkin

> **TL;DR**: 분산 트레이싱은 마이크로서비스 간 요청 흐름을 추적하여 병목과 에러 지점을 식별하는 관측가능성의 세 번째 축이다.
> OpenTelemetry(OTel)은 계측(Instrumentation)의 사실상 표준으로, Traces/Metrics/Logs를 통합하는 벤더 중립 프레임워크이다.
> Trace Context(W3C)가 서비스 간 전파되어야 End-to-End 추적이 가능하며, 샘플링 전략으로 비용과 가시성을 균형잡는다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 분산 트레이싱이 필요한 이유

```
사용자 요청 하나가 여러 서비스를 거치는 마이크로서비스 환경:

User → API Gateway → Auth Service → Alli API → Model Service → GPU Worker
                                         │
                                         ├─→ Cache (Redis)
                                         └─→ DB (MongoDB)

"응답이 느립니다" → 어디서 병목인가?
  - API Gateway? Auth? 모델 로딩? GPU 추론? DB 쿼리?
  - 로그만으로는 서비스 간 인과관계를 파악하기 어려움
  - 트레이싱은 요청의 전체 여정을 하나의 Trace로 시각화
```

### Trace, Span, Context 구조

```
Trace (하나의 요청 전체)
TraceID: abc123
│
├── Span A: API Gateway (root span)
│   SpanID: span-1, ParentID: none
│   Duration: 350ms
│   │
│   ├── Span B: Auth Service
│   │   SpanID: span-2, ParentID: span-1
│   │   Duration: 20ms
│   │
│   └── Span C: Alli API
│       SpanID: span-3, ParentID: span-1
│       Duration: 310ms
│       │
│       ├── Span D: Cache Lookup (Redis)
│       │   SpanID: span-4, ParentID: span-3
│       │   Duration: 2ms (cache miss)
│       │
│       ├── Span E: Model Inference
│       │   SpanID: span-5, ParentID: span-3
│       │   Duration: 280ms  ← 병목!
│       │   Attributes: {model: "gpt-4", tokens: 512}
│       │
│       └── Span F: Save to MongoDB
│           SpanID: span-6, ParentID: span-3
│           Duration: 15ms
```

**핵심 용어**:
- **Trace**: 하나의 요청이 시스템을 통과하는 전체 경로. 고유한 TraceID로 식별
- **Span**: Trace 내의 개별 작업 단위. 시작/종료 시간, 속성(Attributes), 이벤트(Events), 상태(Status) 포함
- **Context Propagation**: TraceID와 SpanID를 서비스 간 전달하는 메커니즘 (HTTP 헤더, gRPC 메타데이터)

### OpenTelemetry 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    Application                           │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Auto-       │  │  Manual      │  │  SDK          │  │
│  │  Instrument  │  │  Instrument  │  │  (TracerProv, │  │
│  │  (라이브러리) │  │  (커스텀코드) │  │   Exporter)  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         └──────────────────┴──────────────────┘          │
│                            │ OTLP (gRPC/HTTP)            │
└────────────────────────────┼─────────────────────────────┘
                             ▼
                 ┌───────────────────────┐
                 │  OTel Collector       │
                 │  ┌─────────────────┐  │
                 │  │ Receivers       │  │  ← OTLP, Jaeger, Zipkin, Prometheus
                 │  ├─────────────────┤  │
                 │  │ Processors      │  │  ← Batch, Filter, Sampling, Attributes
                 │  ├─────────────────┤  │
                 │  │ Exporters       │  │  ← Jaeger, Tempo, Datadog, OTLP
                 │  └─────────────────┘  │
                 └───────────┬───────────┘
                    ┌────────┼────────┐
                    ▼        ▼        ▼
               ┌────────┐┌──────┐┌────────┐
               │ Jaeger ││Tempo ││Datadog │
               └────────┘└──────┘└────────┘
```

### W3C Trace Context 표준

```
HTTP 요청 헤더로 전파:
traceparent: 00-abc123def456789012345678abcdef12-1234567890abcdef-01
             │   │                                │                │
             │   TraceID (32 hex)                  SpanID (16 hex)  Flags
             Version                                               (sampled=01)

tracestate: vendor1=value1,vendor2=value2
            (벤더별 추가 컨텍스트)
```

서비스가 요청을 받으면:
1. `traceparent` 헤더에서 TraceID와 Parent SpanID를 추출
2. 새로운 SpanID를 생성하여 자식 Span 시작
3. 다음 서비스 호출 시 업데이트된 `traceparent` 헤더를 전달

### 샘플링 전략

```
모든 요청을 트레이싱하면:
  - 100,000 RPS × 평균 10 Spans/Trace × 1KB/Span = ~1GB/s 데이터
  - 스토리지 비용 폭발, 네트워크 부하

샘플링으로 해결:
┌──────────────────────────────────────────────────────┐
│ Head-based Sampling (요청 시작 시 결정)               │
│  ├─ Probability: 전체의 10%만 수집                    │
│  ├─ Rate Limiting: 초당 최대 100 traces              │
│  └─ 장점: 간단, 단점: 에러 트레이스를 놓칠 수 있음    │
├──────────────────────────────────────────────────────┤
│ Tail-based Sampling (요청 완료 후 결정)               │
│  ├─ 에러가 발생한 트레이스는 100% 수집               │
│  ├─ 느린 트레이스(p99 초과)는 100% 수집              │
│  ├─ 정상 트레이스는 5%만 수집                        │
│  └─ 장점: 중요 트레이스 보존, 단점: OTel Collector에 │
│     버퍼링 필요 (메모리/지연)                         │
└──────────────────────────────────────────────────────┘
```

### Jaeger vs Tempo

| 항목 | Jaeger | Grafana Tempo |
|------|--------|---------------|
| **아키텍처** | Collector + Storage + Query + UI | 분산 저장소 (S3 기반) |
| **스토리지** | Elasticsearch, Cassandra, Kafka | Object Storage (S3, GCS) |
| **인덱싱** | Span 속성 인덱싱 | TraceID만 인덱싱 |
| **검색** | 서비스명, 태그, 시간 기반 | TraceID 직접 조회 (메트릭/로그에서 연결) |
| **비용** | 인덱싱으로 스토리지 비용 높음 | Object Storage로 저비용 |
| **생태계** | 독립적 | Grafana (Loki→Tempo, Mimir→Tempo) |

---

## 실전 예시

### Python OpenTelemetry 계측

```python
# pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
# pip install opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-requests

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# 1. TracerProvider 설정
resource = Resource.create({
    "service.name": "alli-api",
    "service.version": "1.2.3",
    "deployment.environment": "production",
})
provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint="otel-collector:4317")
)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

# 2. Auto-instrumentation (HTTP 프레임워크/클라이언트 자동 계측)
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()

# 3. Manual instrumentation (비즈니스 로직)
tracer = trace.get_tracer("alli-api")

@app.post("/inference")
async def inference(request: InferenceRequest):
    with tracer.start_as_current_span("model_inference") as span:
        span.set_attribute("model.name", request.model)
        span.set_attribute("prompt.length", len(request.prompt))

        # 모델 로딩
        with tracer.start_as_current_span("load_model"):
            model = load_model(request.model)

        # 추론 실행
        with tracer.start_as_current_span("run_inference") as inf_span:
            result = model.predict(request.prompt)
            inf_span.set_attribute("tokens.output", result.token_count)
            inf_span.set_attribute("inference.latency_ms", result.latency_ms)

        # 에러 발생 시 Span에 기록
        # span.set_status(StatusCode.ERROR, "Model timeout")
        # span.record_exception(exception)

        return result
```

### OTel Collector 설정 (K8s)

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
  batch:
    send_batch_size: 1024
    timeout: 5s

  # Tail-based sampling
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: errors
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: slow-traces
        type: latency
        latency: {threshold_ms: 1000}
      - name: normal-sampling
        type: probabilistic
        probabilistic: {sampling_percentage: 10}

  # 민감정보 제거
  attributes:
    actions:
      - key: user.email
        action: delete
      - key: http.request.body
        action: delete

exporters:
  otlp/tempo:
    endpoint: tempo.monitoring:4317
    tls:
      insecure: true
  otlp/datadog:
    endpoint: "https://trace.agent.datadoghq.com"
    headers:
      "DD-API-KEY": "${DATADOG_API_KEY}"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [tail_sampling, attributes, batch]
      exporters: [otlp/tempo, otlp/datadog]
```

### K8s Deployment (OTel Collector)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-collector
  namespace: monitoring
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: otel-collector
          image: otel/opentelemetry-collector-contrib:0.96.0
          args: ["--config=/conf/otel-collector-config.yaml"]
          ports:
            - containerPort: 4317  # OTLP gRPC
            - containerPort: 4318  # OTLP HTTP
          volumeMounts:
            - name: config
              mountPath: /conf
          resources:
            requests:
              memory: 512Mi
              cpu: 250m
            limits:
              memory: 1Gi
              cpu: 500m
      volumes:
        - name: config
          configMap:
            name: otel-collector-config
```

---

## 면접 Q&A

### Q: OpenTelemetry란 무엇이며, 왜 중요한가?
**30초 답변**: OpenTelemetry는 CNCF의 관측가능성 표준 프레임워크로, Traces/Metrics/Logs의 계측(Instrumentation)과 수집을 벤더 중립적으로 통합합니다. 한번 계측하면 Jaeger, Datadog, Tempo 등 어떤 백엔드로든 데이터를 보낼 수 있어 벤더 락인을 방지합니다.

**2분 답변**: OpenTelemetry는 OpenTracing과 OpenCensus가 합쳐진 프로젝트로, 현재 CNCF에서 Kubernetes 다음으로 활발한 프로젝트입니다. 세 가지 핵심 구성요소가 있습니다. 첫째, **API/SDK**: 언어별(Python, Go, Java, JS 등) 계측 라이브러리. Auto-instrumentation으로 HTTP, DB, gRPC 라이브러리를 자동 계측하고, Manual instrumentation으로 비즈니스 로직 내 커스텀 Span을 생성합니다. 둘째, **OTLP(OpenTelemetry Protocol)**: Traces, Metrics, Logs를 전송하는 표준 프로토콜. gRPC와 HTTP를 지원합니다. 셋째, **OTel Collector**: 벤더 중립 데이터 파이프라인. Receiver(수신) → Processor(처리: 배치, 샘플링, 속성 변환) → Exporter(전송)의 파이프라인 구조입니다. 중요한 이유는, 관측가능성 백엔드를 Jaeger에서 Tempo로, 또는 Datadog으로 교체하더라도 애플리케이션 코드를 변경할 필요가 없다는 것입니다. OTel Collector의 Exporter만 변경하면 됩니다.

**경험 연결**: 온프레미스 환경에서 모니터링 도구(Zabbix, Nagios)를 교체할 때마다 에이전트를 전면 재설치해야 했습니다. OpenTelemetry는 계측 레이어와 백엔드를 분리하여 이런 문제를 구조적으로 해결합니다.

**주의**: OTel의 Logs 신호는 아직 Stable이 아닌 부분이 있다(2024 기준). Traces와 Metrics는 안정적.

### Q: Trace Context Propagation이 끊기면 어떤 문제가 발생하고, 어떻게 해결하나?
**30초 답변**: 컨텍스트 전파가 끊기면 하나의 요청이 여러 개의 독립 트레이스로 분리되어 End-to-End 추적이 불가능합니다. 주로 비동기 메시지 큐, 커스텀 HTTP 클라이언트, 프록시에서 헤더가 누락될 때 발생하며, 모든 통신 경로에서 W3C traceparent 헤더가 전달되는지 확인해야 합니다.

**2분 답변**: Context Propagation이 끊기는 주요 원인과 해결책입니다. 첫째, **메시지 큐(Kafka, RabbitMQ)**: 메시지 발행 시 Span Context를 메시지 헤더에 직렬화하고, 소비 시 역직렬화하여 연결합니다. OTel의 Kafka instrumentation이 이를 자동 처리합니다. 둘째, **커스텀 HTTP 클라이언트**: OTel의 Auto-instrumentation은 표준 라이브러리(requests, urllib)만 지원하므로, 커스텀 클라이언트는 수동으로 `inject()`를 호출해야 합니다. 셋째, **리버스 프록시/로드밸런서**: Nginx, Envoy 등에서 `traceparent` 헤더를 다음 홉으로 전달(proxy_pass_header)하도록 설정해야 합니다. 넷째, **서로 다른 전파 포맷**: B3(Zipkin)과 W3C TraceContext가 혼재하면 끊깁니다. OTel Collector의 `propagators` 설정으로 포맷 변환이 가능합니다. 디버깅 시에는 각 서비스의 로그에 `trace_id`를 출력하여, 동일한 TraceID가 모든 서비스에서 나타나는지 확인합니다.

**경험 연결**: 네트워크 장비 간 패킷 추적에서 NAT/방화벽을 거치면 원본 IP가 변경되어 추적이 끊기는 것과 유사합니다. X-Forwarded-For 헤더처럼, traceparent 헤더도 모든 경로에서 보존되어야 합니다.

**주의**: "Auto-instrumentation만 하면 된다"고 단순화하지 말 것. 비동기 처리, 배치 작업, 이벤트 드리븐 아키텍처에서는 수동 전파가 필수.

### Q: 트레이싱 데이터의 샘플링 전략을 설계한다면?
**30초 답변**: Head-based sampling은 요청 시작 시 확률적으로 결정하여 간단하지만 에러 트레이스를 놓칠 수 있습니다. Tail-based sampling은 요청 완료 후 에러/지연 기준으로 결정하여 중요 트레이스를 보존합니다. 에러와 느린 요청은 100%, 정상은 5~10%가 일반적입니다.

**2분 답변**: 샘플링 전략은 비용과 가시성의 트레이드오프입니다. **Head-based**는 OTel SDK에서 TraceID의 해시값으로 확률적 결정을 내립니다. 장점은 구현이 간단하고 오버헤드가 낮지만, 10% 샘플링이면 에러 트레이스의 90%를 놓칩니다. **Tail-based**는 OTel Collector에서 전체 Trace가 모일 때까지 대기한 후(`decision_wait: 10s`) 판단합니다. 정책 예시: (1) status=ERROR인 트레이스는 100%, (2) 전체 지연이 1초를 초과하면 100%, (3) 특정 서비스(결제, 인증)는 50%, (4) 나머지는 5%. 단점은 Collector에 모든 Span을 버퍼링해야 하므로 메모리 사용량이 높고, 분산 환경에서 같은 Trace의 Span이 다른 Collector로 가면 불완전한 판단이 됩니다. 이를 해결하기 위해 TraceID 기반 로드밸런싱(Consistent Hashing)을 Collector 앞에 둡니다. Allganize의 LLM 서비스에서는 추론 실패, 타임아웃, 비정상 토큰 수 등을 tail-sampling 조건에 추가할 수 있습니다.

**경험 연결**: 네트워크 패킷 캡처에서 전수 조사가 불가능할 때 샘플링하는 것과 같은 원리입니다. sFlow/NetFlow에서 1:1000 샘플링을 하되, 비정상 트래픽은 별도 캡처하는 방식과 유사합니다.

**주의**: Tail-based sampling은 OTel Collector의 메모리와 CPU 리소스를 상당히 소비한다. 리소스 산정 없이 도입하면 Collector 자체가 병목이 될 수 있다.

---

## Allganize 맥락

- **JD 연결**: 마이크로서비스 기반 AI 서비스(Alli)에서 추론 요청의 E2E 추적은 필수
- **LLM 추론 트레이싱**: 프롬프트 전처리 → 모델 로딩 → GPU 추론 → 후처리 각 단계의 Span으로 병목 식별
- **멀티모델 호출**: 하나의 사용자 요청이 여러 모델(NLU, Generative, Embedding)을 호출할 때 전체 흐름 추적
- **OpenTelemetry + Datadog**: OTel로 계측하고 Datadog APM으로 분석하는 하이브리드 구성 가능
- **비용 관리**: 대량 트레이싱 데이터의 샘플링 전략이 Datadog/Tempo 비용에 직결

---
**핵심 키워드**: `OpenTelemetry` `Trace` `Span` `Context-Propagation` `W3C-TraceContext` `OTLP` `OTel-Collector` `Jaeger` `Tempo` `Tail-Sampling` `Auto-Instrumentation`
