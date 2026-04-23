# 로깅 스택 완전 정복 (Logging Stack)

> **TL;DR**
> 1. ELK(Elasticsearch+Logstash+Kibana)는 강력하지만 리소스가 무겁고, EFK(Fluentd/Fluent Bit)는 경량화된 대안이다.
> 2. 구조화 로그(Structured Logging)와 Correlation ID는 관측가능성의 핵심 연결고리다.
> 3. Datadog Logs는 SaaS형으로 운영 부담을 줄이되, 비용 관리가 핵심이다.

---

## 1. 로깅 아키텍처 비교

### ELK Stack vs EFK Stack

```
[ELK Stack]
App --> Logstash --> Elasticsearch --> Kibana
        (수집/변환)    (저장/검색)       (시각화)

[EFK Stack]
App --> Fluentd/Fluent Bit --> Elasticsearch --> Kibana
        (경량 수집)             (저장/검색)       (시각화)

[Grafana Loki Stack]
App --> Promtail/Fluent Bit --> Loki --> Grafana
        (경량 수집)              (저장)   (시각화)

[Datadog Logs]
App --> Datadog Agent --> Datadog Cloud --> Datadog UI
        (수집/전송)       (저장/분석)       (시각화)
```

### 상세 비교표

| 구분 | ELK | EFK | Loki | Datadog |
|------|-----|-----|------|---------|
| **수집기** | Logstash | Fluentd/Fluent Bit | Promtail | Datadog Agent |
| **저장소** | Elasticsearch | Elasticsearch | Object Storage | Datadog Cloud |
| **메모리 사용** | 높음 (JVM) | 낮음 (C/Ruby) | 매우 낮음 | Agent만 |
| **전문 검색** | 강력 (Full-text) | Elasticsearch 의존 | 라벨 기반 | 강력 |
| **비용** | 인프라 비용 | 인프라 비용 | 저렴 (인덱싱 최소화) | 볼륨 과금 |
| **운영 부담** | 높음 | 중간 | 낮음 | 매우 낮음 |
| **적합 환경** | 대규모 로그 분석 | K8s 환경 | 비용 민감 환경 | 빠른 도입 필요 |

---

## 2. Fluentd vs Fluent Bit

### 핵심 차이

| 구분 | Fluentd | Fluent Bit |
|------|---------|------------|
| **언어** | C + Ruby | C |
| **메모리** | ~60MB | ~1MB |
| **플러그인** | 1000+ (Ruby gem) | 100+ (내장) |
| **역할** | Aggregator (집계기) | Forwarder (전송기) |
| **K8s 배포** | DaemonSet 또는 Deployment | DaemonSet |

### 일반적인 조합 패턴

```
[권장 아키텍처: Fluent Bit + Fluentd]

Node 1: Fluent Bit (DaemonSet) --+
Node 2: Fluent Bit (DaemonSet) --+--> Fluentd (Aggregator)
Node 3: Fluent Bit (DaemonSet) --+         |
                                           v
                                    Elasticsearch / S3 / Datadog
```

### Fluent Bit 설정 예시 (Kubernetes DaemonSet)

```yaml
# fluent-bit-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: logging
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush         5
        Daemon        Off
        Log_Level     info
        Parsers_File  parsers.conf

    # Kubernetes 컨테이너 로그 수집
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            cri
        DB                /var/log/flb_kube.db
        Mem_Buf_Limit     5MB
        Skip_Long_Lines   On
        Refresh_Interval  10

    # Kubernetes 메타데이터 추가
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Merge_Log           On
        K8S-Logging.Parser  On
        K8S-Logging.Exclude On

    # JSON 파싱 (구조화 로그)
    [FILTER]
        Name          parser
        Match         kube.*
        Key_Name      log
        Parser        json
        Reserve_Data  On

    # Elasticsearch 출력
    [OUTPUT]
        Name            es
        Match           kube.*
        Host            elasticsearch.logging.svc
        Port            9200
        Logstash_Format On
        Logstash_Prefix alli-logs
        Retry_Limit     3
        tls             On
        tls.verify      Off

    # 동시에 Datadog으로도 전송 (멀티 출력)
    [OUTPUT]
        Name        datadog
        Match       kube.*
        Host        http-intake.logs.datadoghq.com
        TLS         on
        compress    gzip
        apikey      ${DD_API_KEY}
        dd_service  alli-api
        dd_source   kubernetes
        dd_tags     env:production,team:platform

  parsers.conf: |
    [PARSER]
        Name        json
        Format      json
        Time_Key    timestamp
        Time_Format %Y-%m-%dT%H:%M:%S.%LZ

    [PARSER]
        Name        cri
        Format      regex
        Regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L%z
```

---

## 3. 구조화 로그 (Structured Logging)

### 왜 구조화 로그인가?

```
# 비구조화 로그 (Bad)
2025-01-15 10:30:00 ERROR Failed to process request for user 42, timeout after 30s

# 구조화 로그 (Good)
{
  "timestamp": "2025-01-15T10:30:00.000Z",
  "level": "ERROR",
  "service": "alli-api",
  "version": "2.3.1",
  "trace_id": "abc123def456",
  "span_id": "span789",
  "message": "Failed to process request",
  "context": {
    "user_id": "42",
    "timeout_ms": 30000,
    "endpoint": "/api/v1/chat",
    "model": "gpt-4",
    "token_count": 1500
  },
  "error": {
    "type": "TimeoutError",
    "message": "LLM inference exceeded timeout",
    "stack_trace": "..."
  }
}
```

### 구조화 로그 구현 (Python)

```python
import structlog
import logging

# structlog 설정
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

# 사용 예시
def process_chat_request(user_id: str, message: str):
    # 컨텍스트 바인딩 - 이후 모든 로그에 자동 포함
    log = logger.bind(
        user_id=user_id,
        trace_id=get_current_trace_id(),
        service="alli-api"
    )

    log.info("chat_request_received", message_length=len(message))

    try:
        response = call_llm(message)
        log.info("llm_response_success",
                 model=response.model,
                 token_count=response.usage.total_tokens,
                 duration_ms=response.duration_ms)
        return response
    except TimeoutError as e:
        log.error("llm_timeout",
                  error_type="TimeoutError",
                  timeout_ms=30000)
        raise
```

### Correlation ID 전파

```python
# FastAPI 미들웨어로 Correlation ID 자동 주입
from fastapi import FastAPI, Request
from uuid import uuid4
import structlog
from contextvars import ContextVar

trace_id_var: ContextVar[str] = ContextVar('trace_id', default='')

app = FastAPI()

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    # 헤더에서 trace_id를 받거나 새로 생성
    trace_id = request.headers.get("X-Trace-ID", str(uuid4()))
    trace_id_var.set(trace_id)

    # structlog 컨텍스트에 바인딩
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        method=request.method,
        path=request.url.path
    )

    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response
```

---

## 4. 로그 레벨 전략

### 레벨별 사용 가이드

| 레벨 | 용도 | 예시 | 프로덕션 |
|------|------|------|---------|
| **FATAL** | 시스템 종료 수준 | DB 연결 완전 실패 | 항상 |
| **ERROR** | 요청 실패, 즉시 대응 필요 | API 500 에러, LLM 타임아웃 | 항상 |
| **WARN** | 잠재적 문제, 모니터링 필요 | 재시도 성공, 캐시 미스 급증 | 항상 |
| **INFO** | 정상 동작 기록 | 요청 처리 완료, 배포 시작 | 항상 |
| **DEBUG** | 디버깅용 상세 정보 | 쿼리 파라미터, 중간 계산값 | 비활성화 |
| **TRACE** | 매우 상세한 추적 | 함수 진입/퇴출, 루프 반복 | 비활성화 |

### 동적 로그 레벨 변경 (운영 중)

```yaml
# Kubernetes ConfigMap으로 로그 레벨 동적 변경
apiVersion: v1
kind: ConfigMap
metadata:
  name: alli-api-config
data:
  LOG_LEVEL: "INFO"  # 장애 시 DEBUG로 변경 후 재배포 없이 반영

---
# 환경 변수로 주입
env:
  - name: LOG_LEVEL
    valueFrom:
      configMapKeyRef:
        name: alli-api-config
        key: LOG_LEVEL
```

---

## 5. 로그 로테이션 및 보관

### 컨테이너 환경 로그 관리

```yaml
# Docker 로그 드라이버 설정
# /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",    # 파일당 최대 100MB
    "max-file": "3",       # 최대 3개 파일 유지
    "compress": "true"     # 압축 활성화
  }
}
```

### 로그 보관 정책 (Elasticsearch ILM)

```json
// Elasticsearch Index Lifecycle Management
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_size": "50gb",
            "max_age": "1d"
          },
          "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "searchable_snapshot": {
            "snapshot_repository": "s3-repository"
          },
          "set_priority": { "priority": 0 }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

---

## 6. Datadog Logs

### Datadog 로그 수집 아키텍처

```
App (JSON stdout) --> Datadog Agent --> Datadog Cloud
                      (DaemonSet)       |
                                        +--> Log Explorer (검색)
                                        +--> Log Analytics (분석)
                                        +--> Log Pipelines (파싱)
                                        +--> Log Archives (장기 보관 -> S3)
```

### Datadog Agent 설정 (Kubernetes)

```yaml
# datadog-values.yaml (Helm)
datadog:
  apiKey: <DATADOG_API_KEY>
  logs:
    enabled: true
    containerCollectAll: true    # 모든 컨테이너 로그 수집
  apm:
    enabled: true                # APM (트레이스) 연계
  processAgent:
    enabled: true

agents:
  containers:
    agent:
      resources:
        requests:
          cpu: 200m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 512Mi
```

### Datadog Log Pipeline 설정

```
[Pipeline: Alli API Logs]
|
|-- [Grok Parser] 비구조화 로그 파싱
|   Pattern: %{date("yyyy-MM-dd HH:mm:ss"):timestamp} %{word:level} %{data:message}
|
|-- [JSON Mapper] 구조화 로그 필드 매핑
|   trace_id -> dd.trace_id (APM 연계)
|
|-- [Category Processor] 로그 분류
|   - status_code >= 500 -> severity:error
|   - status_code >= 400 -> severity:warning
|
|-- [Sensitive Data Scanner] 민감 정보 마스킹
|   - 이메일 주소 -> [REDACTED_EMAIL]
|   - API 키 -> [REDACTED_KEY]
```

### Datadog 비용 관리

```
# 로그 볼륨 최적화 전략
1. Exclusion Filter: 불필요한 로그 제외 (헬스체크, 디버그)
2. Log Sampling: 정상 로그는 샘플링, 에러 로그는 100% 수집
3. Log Archives: 30일 이후 S3로 아카이빙
4. Custom Metrics from Logs: 로그에서 메트릭 추출 -> 로그 원본 저장 최소화
```

---

## 7. 10년 경력 연결 포인트

> **경력자의 강점**: 10년간 로그 시스템의 진화를 경험했다면, syslog/logrotate -> ELK -> 클라우드 네이티브 로깅 스택의 변화를 체감하고 있다. 특히 "로그를 어떻게 잘 남기느냐"보다 "로그를 어떻게 잘 찾고 연결하느냐"가 핵심이라는 점, 그리고 로그 볼륨과 비용의 트레이드오프를 관리한 경험은 시니어 엔지니어의 가치를 보여준다.

---

## 8. 면접 Q&A

### Q1. ELK와 EFK의 차이, 어떤 상황에서 무엇을 선택하는가?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "핵심 차이는 수집기입니다. Logstash는 JVM 기반으로 메모리를 많이 사용하지만 풍부한 필터 플러그인이 있고, Fluent Bit은 C로 작성되어 1MB 수준의 메모리만 사용합니다. Kubernetes 환경에서는 DaemonSet으로 모든 노드에 배포해야 하므로 경량인 Fluent Bit이 적합합니다. 실무에서는 Fluent Bit을 각 노드의 Forwarder로, Fluentd를 중앙 Aggregator로 사용하는 2계층 구조를 권장합니다. 최근에는 Loki도 좋은 대안입니다. 전문 검색이 필요 없고 라벨 기반 필터링으로 충분하다면 Loki가 훨씬 비용 효율적입니다."

### Q2. 구조화 로그가 왜 중요한가?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "구조화 로그는 관측가능성의 3대 축을 연결하는 핵심입니다. JSON 형태로 trace_id, span_id를 필드에 포함하면 로그에서 바로 해당 트레이스로 점프할 수 있습니다. 또한 필드 기반 검색이 가능해서 '특정 사용자의 에러 로그'를 찾는 쿼리가 정규식 없이도 가능합니다. 올거나이즈 Alli 서비스라면 model, token_count, response_quality 같은 AI 특화 필드를 구조화 로그에 포함시켜 LLM 호출 패턴을 분석할 수 있습니다."

### Q3. 로그 볼륨이 폭증할 때 어떻게 대처하는가?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "세 단계로 접근합니다. 첫째, 즉각 대응으로 샘플링을 적용합니다. 정상 요청 로그는 10%만 수집하고, 에러 로그는 100% 수집합니다. 둘째, 불필요한 로그를 식별합니다. 헬스체크 로그, 디버그 로그가 프로덕션에서 과도하게 남는 경우가 많습니다. 셋째, 로그에서 메트릭을 추출하는 전략을 씁니다. 예를 들어 '에러 발생 횟수'를 매번 로그로 남기는 대신 카운터 메트릭으로 집계하면 로그 볼륨을 줄이면서 같은 정보를 얻을 수 있습니다. Datadog의 Generate Metrics from Logs 기능이 이 용도에 적합합니다."

### Q4. Correlation ID가 없는 레거시 시스템을 어떻게 개선하겠는가?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "점진적으로 접근합니다. 1단계로 API Gateway나 Ingress Controller에서 X-Request-ID 헤더를 생성하여 모든 요청에 주입합니다. 이것만으로도 단일 요청의 로그를 추적할 수 있습니다. 2단계로 서비스 간 호출에서 이 헤더를 전파하도록 미들웨어를 추가합니다. 3단계로 OpenTelemetry를 도입하여 W3C Trace Context 표준으로 전환합니다. 핵심은 애플리케이션 코드를 최소한으로 수정하면서 미들웨어/라이브러리 수준에서 자동화하는 것입니다."

---

## 핵심 키워드 5선

`EFK Stack (Fluent Bit)` `Structured Logging` `Correlation ID` `Datadog Log Pipeline` `Index Lifecycle Management (ILM)`
