# 로깅 아키텍처: 수집, 저장, 시각화

> **TL;DR**: 로그 파이프라인은 수집(Fluent Bit/Fluentd) → 저장(Elasticsearch/Loki) → 시각화(Kibana/Grafana) 3단계로 구성된다.
> 구조화 로깅(Structured Logging)은 JSON 포맷으로 파싱 없이 검색/집계가 가능하게 하며, 관측가능성의 기초이다.
> Fluent Bit은 경량 수집기, Fluentd는 유연한 라우팅/변환기로, 조합하여 사용하는 것이 일반적이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 로깅 파이프라인 아키텍처

```
                    Kubernetes Cluster
┌──────────────────────────────────────────────────────┐
│  Node 1                   Node 2                      │
│  ┌─────────┐              ┌─────────┐                │
│  │ App Pod │ stdout/err   │ App Pod │ stdout/err     │
│  └────┬────┘              └────┬────┘                │
│       ▼                        ▼                      │
│  /var/log/containers/*.log                            │
│       │                        │                      │
│  ┌────▼────┐              ┌────▼────┐                │
│  │Fluent   │              │Fluent   │  ← DaemonSet   │
│  │Bit      │              │Bit      │                │
│  └────┬────┘              └────┬────┘                │
└───────┼───────────────────────┼──────────────────────┘
        │                       │
        ▼                       ▼
   ┌─────────────────────────────────┐
   │        Fluentd (Aggregator)      │  ← Deployment (선택)
   │  ┌──────┐ ┌──────┐ ┌────────┐  │
   │  │Filter│ │Parser│ │ Buffer │  │
   │  └──────┘ └──────┘ └────────┘  │
   └──────────────┬──────────────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   ┌────────┐ ┌──────┐ ┌────────┐
   │Elastic │ │ Loki │ │  S3    │
   │search  │ │      │ │(Archive│
   └───┬────┘ └──┬───┘ └────────┘
       │         │
       ▼         ▼
   ┌────────┐ ┌────────┐
   │Kibana  │ │Grafana │
   └────────┘ └────────┘
```

### Fluent Bit vs Fluentd

| 항목 | Fluent Bit | Fluentd |
|------|-----------|---------|
| **언어** | C | Ruby + C |
| **메모리** | ~450KB | ~40MB |
| **플러그인** | 내장 위주, 경량 | 1,000+ 커뮤니티 플러그인 |
| **역할** | 에지 수집기 (DaemonSet) | 집계/라우팅 (Deployment) |
| **버퍼링** | 메모리 + 파일시스템 | 메모리 + 파일시스템 (더 유연) |
| **배포 위치** | 각 노드 | 중앙 집계 레이어 |

**권장 패턴**: Fluent Bit(DaemonSet, 노드별 수집) → Fluentd(Deployment, 중앙 집계/변환/라우팅)

### Fluent Bit 파이프라인 상세

```
Input → Parser → Filter → Buffer → Output

[INPUT]           [PARSER]          [FILTER]           [OUTPUT]
├─ tail           ├─ json           ├─ kubernetes      ├─ forward (→Fluentd)
│  (로그파일)      ├─ regex          │  (K8s 메타 추가) ├─ es (Elasticsearch)
├─ systemd        ├─ logfmt         ├─ grep            ├─ loki
├─ forward        └─ docker         │  (필터링)         ├─ s3
└─ tcp/udp                          ├─ modify          ├─ kafka
                                    │  (필드 변환)      └─ stdout
                                    └─ lua
                                       (커스텀 로직)
```

```ini
# fluent-bit.conf (K8s DaemonSet 기본 설정)
[SERVICE]
    Flush         5
    Log_Level     info
    Parsers_File  parsers.conf
    HTTP_Server   On
    HTTP_Listen   0.0.0.0
    HTTP_Port     2020       # /api/v1/metrics (Prometheus 형식)

[INPUT]
    Name              tail
    Tag               kube.*
    Path              /var/log/containers/*.log
    Parser            cri                # containerd CRI 로그 포맷
    DB                /var/log/flb_kube.db  # 오프셋 추적
    Mem_Buf_Limit     5MB
    Skip_Long_Lines   On
    Refresh_Interval  10

[FILTER]
    Name                kubernetes
    Match               kube.*
    Kube_URL            https://kubernetes.default.svc:443
    Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
    Merge_Log           On       # JSON 로그를 상위 레벨로 머지
    K8S-Logging.Parser  On       # Pod annotation으로 파서 지정 가능
    K8S-Logging.Exclude On       # Pod annotation으로 수집 제외 가능

[FILTER]
    Name    grep
    Match   kube.*
    Exclude log ^(health check|readiness probe)

[OUTPUT]
    Name            es
    Match           kube.*
    Host            elasticsearch.logging.svc
    Port            9200
    Index           k8s-logs
    Type            _doc
    Logstash_Format On
    Logstash_Prefix k8s
    Retry_Limit     3
```

### 구조화 로깅 (Structured Logging)

```
비구조화 로그 (BAD):
2024-01-15 10:23:45 ERROR Failed to process request from user 12345, model gpt-4, latency 2.3s

구조화 로그 (GOOD):
{
  "timestamp": "2024-01-15T10:23:45.123Z",
  "level": "ERROR",
  "message": "Failed to process request",
  "service": "alli-api",
  "user_id": "12345",
  "model": "gpt-4",
  "latency_ms": 2300,
  "trace_id": "abc123def456",
  "error_type": "ModelTimeout",
  "k8s": {
    "namespace": "alli-prod",
    "pod": "alli-api-7b9f5c6d8-x2k4m",
    "node": "ip-10-0-1-42"
  }
}
```

구조화 로깅의 장점:
- **파싱 불필요**: JSON 필드로 바로 검색/필터링/집계
- **Trace 연동**: `trace_id` 필드로 분산 트레이싱과 연결
- **메트릭 추출**: 로그에서 `latency_ms` 같은 수치를 메트릭으로 변환 가능
- **일관성**: 모든 서비스가 같은 스키마로 로그를 생성하면 통합 분석 용이

### Elasticsearch vs Loki

```
Elasticsearch (ELK/EFK):
┌──────────────────────────────┐
│ 전문 검색(Full-text Search)    │  ← 장점: 강력한 검색/분석
│ 역인덱스(Inverted Index)      │  ← 단점: 리소스 많이 소비
│ 모든 필드 인덱싱              │
│ 복잡한 집계(Aggregation)      │
│ 운영 복잡도 높음              │
└──────────────────────────────┘

Loki (Grafana 생태계):
┌──────────────────────────────┐
│ 레이블 기반 인덱싱만           │  ← 장점: 저비용, 운영 간단
│ 로그 내용은 청크로 압축 저장   │  ← 단점: 전문 검색 느림
│ 스토리지: Object Storage(S3)  │
│ LogQL (PromQL과 유사)         │
│ Grafana 네이티브 연동          │
└──────────────────────────────┘
```

| 기준 | Elasticsearch | Loki |
|------|--------------|------|
| **검색 속도** | 매우 빠름 (역인덱스) | 레이블 매칭 후 grep |
| **스토리지 비용** | 높음 (인덱스 오버헤드) | 낮음 (S3 + 압축) |
| **운영 복잡도** | 높음 (샤드/레플리카 관리) | 낮음 (스테이트리스) |
| **학습 곡선** | KQL/Lucene | LogQL (PromQL 유사) |
| **적합 시나리오** | 로그 분석/검색 중심 | 비용 최적화, Grafana 환경 |

---

## 실전 예시

### LogQL 쿼리 예시 (Loki)

```logql
# 네임스페이스별 에러 로그 필터링
{namespace="alli-prod"} |= "ERROR"

# JSON 파싱 후 필드 기반 필터
{namespace="alli-prod"} | json | latency_ms > 1000

# 에러 로그 발생률 (메트릭 변환)
sum(rate({namespace="alli-prod"} |= "ERROR" [5m])) by (pod)

# 특정 trace_id로 연관 로그 검색
{namespace="alli-prod"} | json | trace_id = "abc123def456"
```

### Elasticsearch Index Lifecycle Management (ILM)

```json
// ILM 정책: 7일 Hot → 30일 Warm → 90일 Cold → 삭제
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_size": "50gb",
            "max_age": "7d"
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 }
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "freeze": {}
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

### Python Structured Logging 예시

```python
import structlog
import logging

# structlog 설정
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

logger = structlog.get_logger()

# 요청 처리 시 컨텍스트 바인딩
def handle_request(request):
    log = logger.bind(
        trace_id=request.headers.get("X-Trace-ID"),
        user_id=request.user_id,
        model=request.model_name
    )
    log.info("inference_started", prompt_length=len(request.prompt))

    try:
        result = run_inference(request)
        log.info("inference_completed",
                 latency_ms=result.latency_ms,
                 token_count=result.token_count)
    except Exception as e:
        log.error("inference_failed",
                  error_type=type(e).__name__,
                  error_message=str(e))
        raise
```

---

## 면접 Q&A

### Q: Fluent Bit과 Fluentd의 차이와 함께 사용하는 이유는?
**30초 답변**: Fluent Bit은 C로 작성된 경량 수집기(~450KB)로 DaemonSet으로 각 노드에 배치합니다. Fluentd는 Ruby 기반으로 1,000개 이상의 플러그인과 유연한 라우팅을 제공합니다. Fluent Bit이 노드에서 수집하고, Fluentd가 중앙에서 집계/변환/멀티 출력하는 패턴이 일반적입니다.

**2분 답변**: 두 프로젝트 모두 CNCF 소속이며 상호보완적입니다. Fluent Bit은 노드별 DaemonSet으로 배포되어 `/var/log/containers/*.log`를 tail하고, K8s 메타데이터(namespace, pod name, labels)를 enrichment합니다. 메모리 사용량이 극히 낮아 노드 리소스를 거의 소비하지 않습니다. Fluentd는 중앙 Deployment로 배포되어 여러 노드의 Fluent Bit에서 `forward` 프로토콜로 받은 로그를 집계하고, 복잡한 변환(레코드 변환, 라우팅 분기, 외부 룩업)을 수행한 후 Elasticsearch, Loki, S3 등 다중 목적지로 라우팅합니다. Fluentd의 버퍼링 시스템은 목적지 장애 시 파일 버퍼로 자동 전환하여 데이터 손실을 방지합니다. 물론 규모가 작다면 Fluent Bit만으로 직접 Elasticsearch/Loki에 출력하는 것도 가능합니다. 선택 기준은 라우팅 복잡도와 플러그인 필요성입니다.

**경험 연결**: 온프레미스에서 syslog-ng로 중앙 로그 수집 시스템을 구축한 경험이 있습니다. "에지 수집기 + 중앙 집계기" 패턴은 동일하며, Fluent Bit/Fluentd는 K8s 네이티브로 이 패턴을 구현합니다.

**주의**: Fluent Bit만으로도 ES/Loki 직접 출력이 가능하다. "반드시 둘 다 써야 한다"고 말하지 말 것.

### Q: 구조화 로깅(Structured Logging)이 왜 중요한가?
**30초 답변**: 구조화 로깅은 로그를 JSON 등 기계가 파싱 가능한 형식으로 생성하여, 정규식 파싱 없이 필드 기반 검색/필터링/집계를 가능하게 합니다. trace_id 필드를 포함하면 분산 트레이싱과 연결되어 관측가능성의 세 축(Metrics-Logs-Traces)을 통합합니다.

**2분 답변**: 비구조화 로그(`ERROR: failed to process...`)는 사람이 읽기엔 편하지만, 기계 처리에는 정규식 파싱이 필요하고 포맷 변경 시 파서가 깨집니다. 구조화 로깅의 핵심 가치는 네 가지입니다. 첫째, **검색 효율**: `{"error_type": "ModelTimeout"}`은 Elasticsearch에서 필드 쿼리로 즉시 검색 가능합니다. 둘째, **집계/분석**: `latency_ms` 같은 수치 필드로 평균/p99 통계를 직접 계산합니다. 셋째, **Observability 통합**: `trace_id` 필드로 Jaeger 트레이스를 연결하고, `user_id`로 특정 사용자 경험을 추적합니다. 넷째, **일관된 스키마**: 팀 전체가 같은 필드 이름(level, message, trace_id, service)을 사용하면 통합 대시보드와 알림 규칙을 범용적으로 만들 수 있습니다. 구현 시에는 Python의 structlog, Go의 zerolog/zap, Java의 SLF4J+Logback JSON Encoder 등 언어별 라이브러리를 사용합니다.

**경험 연결**: 폐쇄망 서버에서 다양한 포맷의 syslog를 통합 분석할 때, 정규식 파서 유지보수가 큰 부담이었습니다. 구조화 로깅은 이 문제를 근본적으로 해결합니다.

**주의**: 모든 로그를 구조화할 수는 없다(서드파티 소프트웨어 등). Fluent Bit/Fluentd의 Parser로 비구조화 로그를 변환하는 방법도 언급할 것.

### Q: Elasticsearch와 Loki의 선택 기준은?
**30초 답변**: Elasticsearch는 전문 검색(full-text search)과 복잡한 집계가 강점이지만 리소스와 운영 비용이 높습니다. Loki는 레이블 기반 인덱싱으로 비용이 낮고 운영이 간단하며, Grafana 생태계와 네이티브 연동됩니다. 로그 분석이 핵심이면 ES, 비용 최적화와 Grafana 통합이 우선이면 Loki입니다.

**2분 답변**: 가장 큰 차이는 인덱싱 전략입니다. Elasticsearch는 모든 필드를 역인덱스로 만들어 어떤 검색이든 빠르지만, 인덱스 저장에 원본 대비 2~3배 스토리지를 사용합니다. 샤드/레플리카 관리, JVM 힙 튜닝 등 운영 복잡도도 높습니다. Loki는 "로그의 Prometheus"를 표방하며, 레이블(namespace, pod, container)만 인덱싱하고 로그 내용은 청크로 압축하여 S3에 저장합니다. 검색 시 레이블로 청크를 선택한 후 grep처럼 스캔하므로, 대량 전문 검색은 느리지만 일반적인 "특정 Pod의 에러 로그 조회" 시나리오에는 충분합니다. 비용 면에서 Loki는 Object Storage 기반이라 Elasticsearch 대비 10~50% 수준으로 절감 가능합니다. Allganize처럼 Grafana를 이미 사용한다면, Loki + LogQL로 메트릭-로그-트레이스 통합 조회가 자연스럽습니다. 반면 보안 SIEM, 복잡한 로그 분석이 필요하면 Elasticsearch가 적합합니다.

**경험 연결**: 온프레미스에서 ELK 스택을 운영했는데, Elasticsearch 클러스터의 샤드 관리와 디스크 용량 이슈가 빈번했습니다. 클라우드 환경에서 비용 효율을 중시한다면 Loki로의 전환을 고려할 것입니다.

**주의**: "Loki가 무조건 낫다"거나 "ES가 무조건 낫다"는 이분법 피하기. 둘 다 사용하는 하이브리드 구성(중요 로그는 ES, 일반 로그는 Loki)도 실무에서 흔하다.

---

## Allganize 맥락

- **JD 연결**: 로그 기반 모니터링과 트러블슈팅은 DevOps의 일상적 업무. 특히 LLM 서비스의 추론 로그 분석이 핵심
- **Fluent Bit + K8s**: EKS/AKS 클러스터에서 Fluent Bit DaemonSet으로 모든 Pod 로그를 수집
- **LLM 로그 특수성**: 추론 요청/응답 로그에는 프롬프트, 토큰 수, 모델 버전, 지연시간 등 AI 서비스 고유 필드가 포함
- **비용 최적화**: 대량의 추론 로그를 모두 인덱싱하면 비용이 폭증. 샘플링이나 Hot/Cold 티어링 전략 필요
- **규정 준수**: AI 서비스 로그에 개인정보가 포함될 수 있으므로, PII 마스킹 필터를 Fluent Bit/Fluentd에서 적용

---
**핵심 키워드**: `Fluent-Bit` `Fluentd` `Elasticsearch` `Loki` `Structured-Logging` `JSON` `DaemonSet` `LogQL` `ILM` `PII-Masking` `Log-Pipeline`
