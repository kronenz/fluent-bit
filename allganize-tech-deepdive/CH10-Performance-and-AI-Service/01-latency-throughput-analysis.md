# Latency & Throughput 계층별 성능 분석

> **TL;DR**: 성능 분석은 네트워크 → 애플리케이션 → DB → 인프라 계층별로 병목을 분리해야 한다.
> Percentile(p50/p95/p99)은 평균보다 훨씬 정확한 사용자 경험 지표이다.
> AI 서비스에서는 TTFT(Time To First Token)와 TPS(Tokens Per Second)가 핵심 latency 지표가 된다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 1. Latency vs Throughput 기본 정의

| 지표 | 정의 | 단위 | AI 서비스 예시 |
|------|------|------|---------------|
| **Latency** | 요청~응답 소요 시간 | ms, s | 사용자 질문 → 첫 토큰 출력까지 |
| **Throughput** | 단위 시간당 처리량 | req/s, tokens/s | 초당 처리 가능한 추론 요청 수 |
| **Bandwidth** | 전송 가능 데이터량 | Mbps, Gbps | GPU ↔ CPU 간 데이터 전송률 |

**핵심 관계**: Latency와 Throughput은 독립적이지 않다. 부하가 증가하면 큐잉이 발생하여 Latency가 급증한다.

```
Throughput vs Latency 곡선 (Little's Law)

Latency │                          ╱
  (ms)  │                        ╱
        │                      ╱
        │                   ╱
        │              ╱╱╱╱
        │         ╱╱╱╱
        │    ╱╱╱╱
        │╱╱╱
        └────────────────────────── Throughput (req/s)
              ↑                 ↑
           정상 구간          포화 구간
                          (큐잉 시작)
```

### 2. 계층별 성능 분석 프레임워크 (Layer-by-Layer)

```
┌─────────────────────────────────────────────────┐
│              Client (Browser/SDK)                │
│  측정: Navigation Timing API, TTFB              │
├─────────────────────────────────────────────────┤
│            ① Network Layer                       │
│  DNS → TCP → TLS → HTTP                         │
│  도구: tcpdump, mtr, curl -w, ping              │
├─────────────────────────────────────────────────┤
│            ② Load Balancer / Ingress             │
│  Connection Pooling, SSL Termination            │
│  도구: ALB metrics, Nginx access log            │
├─────────────────────────────────────────────────┤
│            ③ Application Layer                   │
│  API 처리, 비즈니스 로직, 직렬화                  │
│  도구: APM(Datadog/Jaeger), pprof, async-profiler│
├─────────────────────────────────────────────────┤
│            ④ AI/ML Inference Layer               │
│  모델 로딩, 토큰화, GPU 연산, 디코딩              │
│  도구: nvidia-smi, dcgm-exporter, vLLM metrics  │
├─────────────────────────────────────────────────┤
│            ⑤ Database / Storage Layer            │
│  쿼리 실행, 인덱스, 커넥션 풀                     │
│  도구: slow query log, EXPLAIN, pg_stat          │
├─────────────────────────────────────────────────┤
│            ⑥ Infrastructure Layer                │
│  CPU, Memory, Disk I/O, Network I/O             │
│  도구: node_exporter, vmstat, iostat, sar        │
└─────────────────────────────────────────────────┘
```

### 3. Percentile 이해 (p50 / p95 / p99)

**평균(Average)의 함정**: 평균 latency 100ms라 해도, p99가 5초면 100명 중 1명은 5초를 기다린다.

```
요청 수
  │  ▓▓
  │  ▓▓▓▓
  │  ▓▓▓▓▓▓
  │  ▓▓▓▓▓▓▓▓
  │  ▓▓▓▓▓▓▓▓▓▓
  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░▒▒▒
  └──────────────────────────────────────── Latency (ms)
     ↑p50          ↑p95              ↑p99
    (50ms)        (200ms)          (2000ms)
     중앙값      대부분 사용자      최악 경험
```

| Percentile | 의미 | 활용 |
|-----------|------|------|
| **p50** | 중앙값, 일반적 경험 | 기본 성능 지표 |
| **p95** | 상위 5% 느린 요청 | SLO 목표 설정 |
| **p99** | 상위 1% 느린 요청 | 테일 레이턴시 모니터링 |
| **p99.9** | 1000명 중 1명 | 대규모 서비스에서 중요 |

### 4. 네트워크 계층 분석

```bash
# curl 상세 타이밍 분석
curl -w @- -o /dev/null -s "https://api.alli.ai/health" <<'EOF'
    dns_lookup:  %{time_namelookup}s\n
 tcp_connect:   %{time_connect}s\n
 tls_handshake: %{time_appconnect}s\n
 ttfb:          %{time_starttransfer}s\n
 total:         %{time_total}s\n
EOF

# MTR로 네트워크 경로 분석
mtr --report --report-cycles 10 api.alli.ai

# TCP 레벨 패킷 분석
tcpdump -i eth0 -nn port 443 -c 100 -w capture.pcap
```

### 5. 애플리케이션 계층 분석

```bash
# Jaeger/OpenTelemetry Distributed Tracing
# Span 구조 예시
Trace: user-query-12345
├── api-gateway        [0ms ─── 50ms]
│   └── auth-check     [5ms ── 15ms]
├── rag-retrieval      [50ms ──── 200ms]
│   ├── embedding      [55ms ── 80ms]
│   └── vector-search  [80ms ─── 190ms]
├── llm-inference      [200ms ────────── 2500ms]
│   ├── tokenization   [205ms ─ 210ms]
│   ├── gpu-compute    [210ms ──────── 2400ms]
│   └── decode         [2400ms ── 2490ms]
└── response-stream    [2500ms ── 2600ms]
```

### 6. DB 계층 분석

```bash
# MongoDB slow query 분석 (Allganize는 MongoDB 사용)
db.setProfilingLevel(1, { slowms: 100 })
db.system.profile.find().sort({ts: -1}).limit(5)

# Elasticsearch 쿼리 프로파일링
GET /alli-documents/_search
{
  "profile": true,
  "query": {
    "match": { "content": "사용자 질문" }
  }
}
```

### 7. 인프라 계층 분석

```bash
# CPU 사용률 확인 (usr/sys/iowait 구분 중요)
mpstat -P ALL 1 5

# 메모리 상태 (buffer/cache 구분)
free -h && vmstat 1 5

# Disk I/O (IOPS, await, %util)
iostat -xz 1 5

# Network (bandwidth, retransmit)
sar -n DEV 1 5
ss -s  # 소켓 상태 요약
```

---

## 실전 예시

### Prometheus + Grafana 기반 Percentile 모니터링

```yaml
# Prometheus Recording Rule - Histogram에서 Percentile 계산
groups:
- name: api_latency_rules
  rules:
  - record: api:request_duration:p50
    expr: histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))
  - record: api:request_duration:p95
    expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))
  - record: api:request_duration:p99
    expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))

# SLO Alert - p95 latency가 500ms 초과 시
- alert: HighP95Latency
  expr: api:request_duration:p95{service="alli-api"} > 0.5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "p95 latency exceeds 500ms for {{ $labels.service }}"
```

### USE Method (Utilization, Saturation, Errors)

```
┌──────────────┬───────────────┬──────────────┬───────────────┐
│   Resource   │  Utilization  │  Saturation  │    Errors     │
├──────────────┼───────────────┼──────────────┼───────────────┤
│ CPU          │ %usr + %sys   │ Load Average │ machine check │
│ Memory       │ used/total    │ swap usage   │ OOM kills     │
│ Disk I/O     │ %util         │ await (ms)   │ device errors │
│ Network      │ bandwidth %   │ TCP retrans  │ dropped pkts  │
│ GPU          │ gpu_util %    │ fb_mem used  │ xid errors    │
└──────────────┴───────────────┴──────────────┴───────────────┘
```

### RED Method (Request-oriented, 서비스 레벨)

```
Rate    = requests per second
Errors  = failed requests per second
Duration = latency distribution (histogram)

# Prometheus 쿼리 예시
Rate:     sum(rate(http_requests_total[5m])) by (service)
Errors:   sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
Duration: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
```

---

## 면접 Q&A

### Q1: "서비스 응답 시간이 느려졌다"는 보고를 받으면 어떻게 분석하시겠습니까?

**30초 답변**:
계층별로 병목을 분리합니다. 먼저 Grafana에서 p95/p99 latency 추이를 확인하고, distributed tracing으로 어느 서비스/구간에서 지연이 발생하는지 좁힙니다. 네트워크→애플리케이션→DB→인프라 순으로 USE/RED 메트릭을 확인하여 근본 원인을 찾습니다.

**2분 답변**:
1단계: 영향 범위 파악 - 전체 서비스인지 특정 엔드포인트인지, 특정 리전/AZ인지 확인합니다.
2단계: 메트릭 대시보드 확인 - Grafana에서 latency percentile 그래프를 보고 언제부터 악화되었는지 타임라인을 잡습니다. 배포/설정 변경과 시간이 일치하면 rollback 우선 고려합니다.
3단계: Distributed Tracing - Jaeger/Datadog APM에서 느린 trace를 샘플링하여 어느 span에서 시간이 소모되는지 확인합니다.
4단계: 계층별 분석
- 네트워크: TCP retransmit, DNS resolution time 확인
- 앱: CPU throttling, GC pause, thread pool 고갈 확인
- DB: slow query, lock contention, connection pool 고갈 확인
- 인프라: node CPU/memory saturation, disk I/O await 확인
5단계: 근본 원인 수정 후 p95/p99가 정상 범위로 복구되었는지 검증합니다.

**💡 경험 연결**:
"현재 AI 데이터센터 컨설팅에서 GPU 서버의 성능 이슈를 분석할 때, 네트워크 bandwidth 포화인지 GPU utilization 부족인지를 계층별로 분리하여 진단하는 방법론을 적용하고 있습니다."

**⚠️ 주의**: "느리다"는 보고에 바로 코드를 보러 가지 말고, 반드시 메트릭 기반으로 가설을 세우고 검증하는 과정을 설명해야 한다.

---

### Q2: 평균 latency 대신 p99를 모니터링해야 하는 이유를 설명해주세요.

**30초 답변**:
평균은 outlier를 숨깁니다. 대부분 요청이 50ms여도 1%가 10초면 평균은 150ms로 보여 심각성을 놓칩니다. p99는 실제 사용자 중 최악의 경험을 대표하며, 특히 MSA에서는 한 서비스의 tail latency가 전체 요청의 latency로 증폭됩니다(fan-out amplification).

**2분 답변**:
평균의 문제점은 분포를 알 수 없다는 것입니다. bimodal distribution(이중 봉우리)에서 평균은 어느 봉우리도 대표하지 못합니다.

p99가 중요한 구체적 이유:
1. **Fan-out amplification**: MSA에서 하나의 API가 5개 백엔드를 호출하면, 전체 p99 ≈ 1-(1-0.01)^5 ≈ 5%의 요청이 느려집니다. 호출 체인이 길수록 tail latency 영향이 기하급수적으로 증가합니다.
2. **사용자 신뢰**: 자주 방문하는 사용자일수록 p99를 경험할 확률이 높습니다. VIP 고객이 가장 나쁜 경험을 하게 됩니다.
3. **SLO 정의**: Google SRE 방법론에서 SLI는 percentile 기반입니다. "p95 latency < 200ms를 99.9% 시간 동안 유지"처럼 정의합니다.

실무 권장사항:
- p50: 일반 사용자 경험 대시보드
- p95: SLO alert 기준
- p99: 성능 회귀 감지용
- p99.9: 대규모 트래픽 서비스에서 추가 모니터링

**💡 경험 연결**:
"인프라 모니터링에서 서버 응답 시간의 평균만 보고 있다가 특정 시간대에 일부 사용자만 극심한 지연을 겪는 문제를 놓친 경험이 있습니다. 이후 percentile 기반 대시보드로 전환하여 tail latency를 사전에 감지하게 되었습니다."

**⚠️ 주의**: Prometheus histogram의 bucket 설정이 부적절하면 percentile 계산이 부정확해진다. bucket 경계를 서비스 SLO에 맞게 설정해야 한다.

---

### Q3: AI/LLM 서비스의 성능 지표는 전통적 웹 서비스와 어떻게 다릅니까?

**30초 답변**:
LLM 서비스는 스트리밍 응답이므로 TTFT(Time To First Token)와 TPS(Tokens Per Second)가 핵심 지표입니다. 전통적 TTFB 대신 TTFT를, RPS 대신 tokens/s를 사용하며, GPU utilization과 KV-cache 사용률이 추가 인프라 지표가 됩니다.

**2분 답변**:
전통 웹 서비스와 LLM 서비스의 성능 지표 차이:

| 관점 | 전통 웹 서비스 | LLM 서비스 |
|------|--------------|-----------|
| 응답 패턴 | 요청-응답 (atomic) | 스트리밍 (token by token) |
| Latency | TTFB, total response time | TTFT, inter-token latency, total generation time |
| Throughput | RPS (requests/sec) | Tokens/sec, concurrent requests |
| 리소스 | CPU, Memory | GPU util, GPU memory, KV-cache |
| 병목 | CPU, DB, Network | GPU compute, GPU memory bandwidth |
| 스케일링 | horizontal (stateless) | 제한적 (모델 로딩 시간, GPU 비용) |

LLM 특화 지표:
- **TTFT**: Prefill 단계 소요 시간. 입력 토큰 수에 비례. 사용자 체감 반응성의 핵심.
- **TPS (Tokens Per Second)**: Decode 단계의 토큰 생성 속도. 30~50 TPS가 사람 읽기 속도.
- **ITL (Inter-Token Latency)**: 토큰 간 지연. 일관성이 중요(jitter가 크면 UX 저하).
- **Time Per Output Token (TPOT)**: 출력 토큰당 평균 시간.

```
LLM 추론 타임라인
─────────────────────────────────────────────────
│← Prefill (TTFT) →│← Decode (token by token) →│
│  입력 토큰 처리    │  T1  T2  T3  T4 ... Tn   │
│  KV-cache 생성    │  ↑ITL↑                     │
─────────────────────────────────────────────────
0ms              500ms                       3000ms
```

**💡 경험 연결**:
"AI 데이터센터 GPU 서버 구축 프로젝트에서 nvidia-smi로 GPU utilization이 낮은데 throughput도 낮은 현상을 경험했습니다. 분석 결과 CPU→GPU 데이터 전송 병목이었고, 이런 경험이 LLM 서비스 성능 분석에도 직접 적용됩니다."

**⚠️ 주의**: LLM 성능 지표를 말할 때 TTFT/TPS를 정확히 설명하지 못하면 AI 서비스 운영 경험이 부족해 보인다. Allganize의 Alli 서비스 특성상 반드시 숙지해야 한다.

---

### Q4: Little's Law를 설명하고 용량 계획에 어떻게 활용할 수 있나요?

**30초 답변**:
Little's Law는 L = λ × W (동시 요청 수 = 도착률 × 평균 처리 시간)입니다. 예를 들어 초당 100건 요청이 오고 평균 처리 시간이 200ms면 동시에 20건이 처리 중입니다. 이를 역으로 활용하면 서버 1대의 동시 처리 능력으로부터 필요한 서버 수를 계산할 수 있습니다.

**2분 답변**:
**L = λ × W** (시스템 내 평균 요청 수 = 평균 도착률 × 평균 체류 시간)

실무 활용 예시:
- Alli API가 peak 시간에 500 req/s를 받고, 평균 응답 시간이 2초라면
- 동시에 시스템 내에 1,000개 요청이 존재
- Pod 1개가 동시 50개 요청을 처리할 수 있다면 → 최소 20개 Pod 필요
- 여유율 30% 고려 시 → 26개 Pod으로 HPA max 설정

GPU 추론 서버 용량 계획:
- LLM 추론 요청이 200 req/s, 평균 추론 시간 3초
- 동시 600개 요청 처리 필요
- GPU 1장당 batch size 8로 동시 8개 처리 가능
- 필요 GPU 수: 600 / 8 = 75장 (최소)

**💡 경험 연결**:
"서버 증설 용량 산정 시 단순 CPU 사용률뿐 아니라 동시 요청 수 기반으로 계산하는 방법을 적용해왔습니다. Little's Law를 명시적으로 활용하면 보다 정확한 용량 계획이 가능합니다."

**⚠️ 주의**: Little's Law는 안정 상태(steady state)에서만 유효하다. 트래픽 급증 시에는 큐잉 이론(M/M/c 등)을 추가로 고려해야 한다.

---

## Allganize 맥락

- **Alli 챗봇 서비스**: 사용자 질문 → RAG 검색 → LLM 추론의 전체 파이프라인에서 각 단계별 latency를 분리 측정해야 함
- **TTFT SLO**: Alli 사용자 경험을 위해 TTFT를 1초 이내로 유지하는 것이 중요
- **멀티 클라우드(AWS/Azure)**: 클라우드별 네트워크 latency 차이를 고려한 성능 기준 필요
- **JD "성능 분석(latency/throughput)"**: 이 파일의 내용이 JD 요구사항에 직접 매핑됨
- **MongoDB/Elasticsearch**: Alli의 데이터 저장소 성능 분석은 slow query + 인덱스 최적화가 핵심
- **K8s 기반 운영**: Pod 레벨 리소스 제한이 latency에 직접 영향 (CPU throttling → p99 급증)

---

**핵심 키워드**: `p50/p95/p99` `USE-Method` `RED-Method` `TTFT` `TPS` `Little's-Law` `distributed-tracing` `tail-latency` `fan-out-amplification`
