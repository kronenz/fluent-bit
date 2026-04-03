# 성능 분석 (Performance Analysis) - Allganize 면접 준비

---

> **TL;DR**
> 1. 성능 분석은 **Latency(지연)**와 **Throughput(처리량)** 두 축으로 시작한다
> 2. 계층별 병목 분석은 **Application -> Runtime -> OS -> Hardware** 순서로 좁혀간다
> 3. USE/RED Method는 인프라/서비스 각각의 표준 분석 프레임워크다

---

## 1. Latency vs Throughput 개념

### 핵심 정의

| 지표 | 정의 | 단위 | 비유 |
|------|------|------|------|
| **Latency (지연)** | 요청 하나가 처리되는 데 걸리는 시간 | ms, s | 고속도로에서 서울->부산 소요 시간 |
| **Throughput (처리량)** | 단위 시간당 처리할 수 있는 요청 수 | req/s, TPS | 고속도로에서 1시간에 통과하는 차량 수 |

### 둘의 관계

```
Throughput = Concurrency / Latency
(Little's Law)
```

- Latency가 낮아도 동시성(Concurrency)이 낮으면 Throughput이 낮다
- Throughput을 높이려고 동시성을 과도하게 올리면 Latency가 급증한다 (Hockey Stick 패턴)

### Percentile의 중요성

```bash
# wrk로 Latency 분포 확인
wrk -t4 -c100 -d30s --latency http://api.example.com/v1/predict

# 출력 예시
# Latency Distribution
#   50%    12.34ms    <- 중앙값
#   75%    18.56ms
#   90%    45.23ms    <- 여기서부터 주목
#   99%   312.45ms    <- Tail Latency (실제 사용자 경험)
```

- **P50**: 중앙값, 일반적 응답 시간
- **P99**: 상위 1% 최악의 응답 시간 -> **SLO(Service Level Objective) 기준으로 사용**
- AI 서비스에서는 P95/P99가 특히 중요 (모델 추론 시간 편차가 크므로)

---

## 2. 병목 분석 계층별 접근

### 분석 순서: Top-Down

```
[Application Layer]
   코드 로직, 쿼리, 알고리즘
        |
[Runtime Layer]
   Python GIL, JVM GC, Node Event Loop
        |
[OS Layer]
   CPU 스케줄링, 메모리, 디스크 I/O, 네트워크
        |
[Hardware Layer]
   CPU, RAM, NVMe/SSD, NIC, GPU
```

### 각 계층별 점검 포인트

#### Application Layer

```bash
# 슬로우 쿼리 확인 (MongoDB)
db.setProfilingLevel(1, { slowms: 100 })
db.system.profile.find().sort({ ts: -1 }).limit(5)

# Python 프로파일링
python -m cProfile -s cumulative app.py
```

#### Runtime Layer

```bash
# JVM GC 로그 확인 (Elasticsearch)
-XX:+PrintGCDetails -XX:+PrintGCTimeStamps -Xloggc:/var/log/es-gc.log

# Python GIL 영향 확인
py-spy top --pid <PID>
```

#### OS Layer

```bash
# CPU 사용률 및 대기 시간
mpstat -P ALL 1 5

# 메모리 (사용량, 캐시, 스왑)
vmstat 1 10
free -h

# 디스크 I/O (await가 높으면 디스크 병목)
iostat -xz 1 5

# 네트워크 (패킷 드롭, 재전송)
ss -s
netstat -i
```

#### Hardware Layer

```bash
# GPU 모니터링
nvidia-smi --query-gpu=utilization.gpu,utilization.memory,temperature.gpu \
  --format=csv -l 1

# CPU 온도/스로틀링 확인
turbostat --Summary --quiet sleep 5
```

---

## 3. USE Method (Utilization, Saturation, Errors)

**Brendan Gregg**가 제안한 **인프라 리소스 중심** 분석 방법론

### 프레임워크

| 리소스 | Utilization (사용률) | Saturation (포화도) | Errors (오류) |
|--------|---------------------|---------------------|---------------|
| **CPU** | `mpstat` (%usr+%sys) | Run queue length (`vmstat` r열) | MCE 로그 |
| **Memory** | `free -h` (used/total) | Swap 사용량, OOM 발생 | `dmesg` OOM |
| **Disk** | `iostat` (%util) | `iostat` avgqu-sz (큐 깊이) | `/sys/devices/.../errors` |
| **Network** | `sar -n DEV` (rx/tx) | `ifconfig` overruns, drops | `netstat -s` retransmits |
| **GPU** | `nvidia-smi` (GPU %) | GPU memory 사용률 | Xid errors |

### 실전 스크립트

```bash
#!/bin/bash
# use-method-check.sh - USE Method 빠른 점검 스크립트

echo "=== CPU Utilization ==="
mpstat 1 1 | tail -1

echo "=== CPU Saturation (Run Queue) ==="
vmstat 1 1 | tail -1 | awk '{print "run queue:", $1}'

echo "=== Memory Utilization ==="
free -h | grep Mem

echo "=== Memory Saturation (Swap) ==="
swapon --show

echo "=== Disk Utilization ==="
iostat -xz 1 1 | grep -v "^$" | tail -5

echo "=== Network Errors ==="
netstat -s | grep -i retransmit
```

---

## 4. RED Method (Rate, Errors, Duration)

**Tom Wilkie**가 제안한 **서비스(마이크로서비스) 중심** 분석 방법론

### 프레임워크

| 지표 | 의미 | 도구 |
|------|------|------|
| **Rate** | 초당 요청 수 (req/s) | Prometheus `rate(http_requests_total[5m])` |
| **Errors** | 실패한 요청 비율 | `rate(http_requests_total{status=~"5.."}[5m])` |
| **Duration** | 요청 처리 시간 분포 | `histogram_quantile(0.99, ...)` |

### USE vs RED 사용 기준

```
인프라 리소스 문제 의심 -> USE Method
서비스 레벨 문제 의심  -> RED Method
보통은 RED로 시작 -> 이상 발견 시 USE로 원인 추적
```

### Prometheus + Grafana 대시보드 예시

```yaml
# prometheus-rules.yaml
groups:
  - name: red-method
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)

      - record: job:http_errors:rate5m
        expr: sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)

      - record: job:http_duration:p99
        expr: histogram_quantile(0.99,
          sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))
```

---

## 5. 부하 테스트 도구 비교

### 도구별 특성

| 도구 | 언어 | 특징 | 적합한 상황 |
|------|------|------|------------|
| **k6** | JavaScript | CLI 기반, 코드로 시나리오 작성, CI/CD 통합 용이 | API 부하 테스트, 자동화 |
| **wrk** | Lua | 초경량, 높은 성능 | 단순 HTTP 벤치마크 |
| **Locust** | Python | 웹 UI, 분산 테스트 | 복잡한 사용자 시나리오 |

### k6 예제: AI API 부하 테스트

```javascript
// k6-ai-load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 10 },   // Ramp-up
    { duration: '3m', target: 50 },   // Sustained load
    { duration: '1m', target: 0 },    // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'],  // P95 < 3초
    http_req_failed: ['rate<0.01'],     // 에러율 < 1%
  },
};

export default function () {
  const payload = JSON.stringify({
    prompt: "Summarize the following document...",
    max_tokens: 256,
  });

  const params = {
    headers: { 'Content-Type': 'application/json' },
    timeout: '10s',
  };

  const res = http.post('http://ai-service:8080/v1/predict', payload, params);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'latency < 3s': (r) => r.timings.duration < 3000,
    'has result': (r) => JSON.parse(r.body).result !== undefined,
  });

  sleep(1);
}
```

```bash
# 실행
k6 run k6-ai-load-test.js

# 결과를 Prometheus로 전송
k6 run --out experimental-prometheus-rw k6-ai-load-test.js
```

### wrk 예제: 간단한 벤치마크

```bash
# 4 threads, 100 connections, 30초간 테스트
wrk -t4 -c100 -d30s --latency http://api.example.com/health

# Lua 스크립트로 POST 요청
wrk -t2 -c50 -d30s -s post.lua http://api.example.com/v1/predict
```

### Locust 예제: 분산 테스트

```python
# locustfile.py
from locust import HttpUser, task, between

class AIServiceUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def predict(self):
        self.client.post("/v1/predict", json={
            "prompt": "Test prompt",
            "max_tokens": 128
        })

    @task(1)
    def health_check(self):
        self.client.get("/health")
```

```bash
# 단일 노드 실행
locust -f locustfile.py --host=http://ai-service:8080

# 분산 실행 (master + workers)
locust -f locustfile.py --master
locust -f locustfile.py --worker --master-host=<MASTER_IP>
```

---

## 면접 Q&A

### Q1. "Latency와 Throughput의 관계를 설명해주세요"

> **이렇게 대답한다:**
> "Little's Law에 따라 Throughput = Concurrency / Latency 관계입니다. 실무에서는 동시 사용자를 늘려 Throughput을 높이려 하면, 특정 지점 이후 리소스 경합으로 Latency가 급증하는 Hockey Stick 패턴이 나타납니다. 따라서 부하 테스트로 시스템의 최적 동시성 수준을 찾는 것이 중요합니다. AI 서비스의 경우 GPU 메모리 제약으로 이 임계점이 더 빨리 오는 경향이 있어, 배치 크기와 동시 요청 수를 신중하게 조절해야 합니다."

### Q2. "성능 병목을 분석하는 본인만의 프로세스가 있나요?"

> **이렇게 대답한다:**
> "먼저 RED Method로 서비스 레벨에서 Rate, Errors, Duration을 확인합니다. 이상이 발견되면 USE Method로 전환하여 CPU, Memory, Disk, Network 각 리소스의 Utilization, Saturation, Errors를 계층적으로 점검합니다. 폐쇄망 환경에서 10년간 운영하면서, 외부 APM 도구 없이도 mpstat, iostat, vmstat 같은 OS 내장 도구만으로 체계적으로 병목을 찾아내는 역량을 쌓았습니다. 이런 경험이 관측 도구가 제한된 환경에서도 빠르게 원인을 파악하는 데 강점이 됩니다."

### Q3. "P50과 P99의 차이가 큰 경우 어떻게 접근하나요?"

> **이렇게 대답한다:**
> "P99 Tail Latency가 높다는 것은 일부 요청이 특정 조건에서 느려진다는 의미입니다. 주요 원인으로는 GC Pause, 캐시 미스, 특정 샤드로의 쏠림, Cold Start 등이 있습니다. 트레이싱(Jaeger, Tempo)으로 느린 요청의 Span을 분석하고, 해당 시점의 리소스 상태를 USE Method로 대조합니다. MongoDB에서는 특정 쿼리가 인덱스를 타지 않아 COLLSCAN이 발생하는 경우, Elasticsearch에서는 특정 샤드에 핫 데이터가 몰리는 경우가 대표적입니다."

### Q4. "부하 테스트 도구를 선택하는 기준은?"

> **이렇게 대답한다:**
> "CI/CD 파이프라인에 통합하여 자동화할 때는 k6를 선호합니다. 코드 기반으로 시나리오를 작성할 수 있고 threshold 기반 pass/fail 판정이 가능해서입니다. 빠른 벤치마크가 필요할 때는 wrk를, 비개발자와 협업하거나 웹 UI가 필요할 때는 Locust를 사용합니다. 폐쇄망 환경에서는 외부 SaaS 도구를 쓸 수 없으므로, 이 세 가지 오픈소스 도구를 상황에 맞게 활용하는 것이 중요합니다."

### Q5. "Allganize의 AI 서비스 성능을 어떻게 모니터링하겠습니까?"

> **이렇게 대답한다:**
> "RED Method 기반으로 Prometheus + Grafana 대시보드를 구성합니다. Rate(req/s), Errors(5xx 비율), Duration(P50/P95/P99)을 실시간 모니터링하고, AI 서비스 특화 지표로 TTFT(Time To First Token), TPS(Tokens Per Second)를 추가합니다. GPU 리소스는 DCGM Exporter로 수집하고, 인프라 레벨에서는 USE Method 기반 대시보드를 별도로 구성하여 병목 발생 시 빠르게 계층을 좁혀갈 수 있도록 설계합니다."

---

## 핵심 키워드 5선

`Latency vs Throughput` `USE Method` `RED Method` `P99 Tail Latency` `부하 테스트 자동화 (k6)`
