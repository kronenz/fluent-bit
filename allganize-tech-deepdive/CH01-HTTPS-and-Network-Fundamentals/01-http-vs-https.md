# 01. HTTP vs HTTPS — HTTP/1.1, HTTP/2, HTTP/3(QUIC) 비교

> **TL;DR**
> - HTTP/1.1은 요청당 TCP 연결(또는 Keep-Alive), HTTP/2는 **하나의 TCP 위에 멀티플렉싱**, HTTP/3는 **UDP 기반 QUIC**으로 HOL Blocking을 해결한다.
> - HTTPS = HTTP + **TLS 암호화**. 평문 전송의 도청/변조/위장 문제를 해결하며, 현대 웹에서는 사실상 필수이다.
> - Allganize Alli 서비스처럼 LLM API를 외부에 노출하는 경우, **HTTP/2 + TLS 1.3** 조합이 latency와 보안 모두에 최적이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### HTTP의 진화 흐름

```
HTTP/0.9 (1991)     GET만 존재, HTML만 전송
    │
HTTP/1.0 (1996)     헤더 추가, POST/HEAD, 요청마다 새 TCP 연결
    │
HTTP/1.1 (1997)     Keep-Alive 기본, Pipelining, Host 헤더, Chunked
    │
HTTP/2   (2015)     바이너리 프레이밍, 멀티플렉싱, 헤더 압축, Server Push
    │
HTTP/3   (2022)     UDP 기반 QUIC, 0-RTT, 연결 마이그레이션
```

### HTTP/1.1의 구조적 한계

```
클라이언트                          서버
    │── GET /index.html ──────────→│
    │←── 200 OK (HTML) ───────────│
    │── GET /style.css ───────────→│   ← 앞 응답 완료 후에야 다음 요청 처리
    │←── 200 OK (CSS) ────────────│      (Head-of-Line Blocking)
    │── GET /app.js ──────────────→│
    │←── 200 OK (JS) ─────────────│

    * Pipelining은 스펙에 있으나 실제 구현/사용이 거의 없음
    * 브라우저는 보통 도메인당 6개 TCP 연결을 열어 우회
```

**왜 문제인가?**
- 연결당 직렬 처리 → 리소스가 많은 페이지에서 latency 누적
- 도메인 샤딩(domain sharding)으로 우회 → DNS 조회, TCP 핸드셰이크 비용 증가
- 텍스트 기반 헤더 → 매 요청마다 중복 전송 (Cookie 등)

### HTTP/2 — 멀티플렉싱

```
┌──────────────── 하나의 TCP 연결 ────────────────┐
│                                                   │
│  Stream 1: GET /index.html   ──→  ←── 200 OK     │
│  Stream 3: GET /style.css    ──→  ←── 200 OK     │
│  Stream 5: GET /app.js       ──→  ←── 200 OK     │
│                                                   │
│  * 바이너리 프레임으로 인터리빙 전송                │
│  * 각 스트림은 독립적 요청/응답                     │
│  * HPACK으로 헤더 압축 (정적/동적 테이블)           │
└───────────────────────────────────────────────────┘
```

**핵심 특징:**
- **바이너리 프레이밍(Binary Framing)**: 텍스트가 아닌 바이너리로 파싱 효율 향상
- **멀티플렉싱**: 하나의 TCP에서 여러 스트림 병렬 전송, 응답 순서 무관
- **HPACK 헤더 압축**: 중복 헤더 제거, Huffman 인코딩
- **Server Push**: 서버가 클라이언트 요청 전에 리소스를 미리 전송 (실무에서는 잘 안 쓰임)

**남은 문제**: TCP 레벨의 HOL Blocking — TCP 패킷 하나 유실 시 **모든 스트림**이 대기

### HTTP/3 — QUIC 프로토콜

```
┌───────── HTTP/2 스택 ─────────┐  ┌───────── HTTP/3 스택 ─────────┐
│  HTTP/2                       │  │  HTTP/3                       │
│  TLS 1.2/1.3                  │  │  QUIC (TLS 1.3 내장)          │
│  TCP                          │  │  UDP                          │
│  IP                           │  │  IP                           │
└───────────────────────────────┘  └───────────────────────────────┘

QUIC의 스트림 독립성:
  Stream A: [패킷1][패킷2][패킷3]    ← 패킷2 유실 → Stream A만 대기
  Stream B: [패킷1][패킷2]           ← 영향 없음, 계속 진행
  Stream C: [패킷1][패킷2][패킷3]    ← 영향 없음, 계속 진행
```

**왜 UDP인가?**
- TCP는 OS 커널에 구현 → 변경/배포가 극도로 느림
- QUIC은 유저스페이스에서 구현 → 빠른 업데이트 가능
- UDP는 "아무것도 안 하는" 프로토콜이므로 그 위에 새 전송 계층을 구축

**QUIC 핵심 장점:**
- **0-RTT 연결 재개**: 이전 연결 정보가 있으면 데이터를 첫 패킷에 포함
- **연결 마이그레이션**: IP가 바뀌어도(Wi-Fi→LTE) Connection ID로 연결 유지
- **스트림 독립성**: 한 스트림의 패킷 유실이 다른 스트림에 영향 없음

### HTTP vs HTTPS 비교

```
HTTP (포트 80)                    HTTPS (포트 443)
┌─────────┐                       ┌─────────┐
│ 평문 전송 │  ← 도청 가능          │ TLS 암호화│  ← 도청 불가
│ 변조 가능 │  ← 중간자 공격        │ 무결성 보장│  ← 변조 탐지
│ 인증 없음 │  ← 피싱 사이트        │ 인증서 검증│  ← 서버 신원 확인
└─────────┘                       └─────────┘
```

### 프로토콜 비교 요약

| 특성 | HTTP/1.1 | HTTP/2 | HTTP/3 |
|------|----------|--------|--------|
| 전송 계층 | TCP | TCP | UDP (QUIC) |
| 멀티플렉싱 | 없음 | 있음 (단일 TCP) | 있음 (독립 스트림) |
| 헤더 형식 | 텍스트 | 바이너리 (HPACK) | 바이너리 (QPACK) |
| HOL Blocking | 요청 레벨 | TCP 레벨 | 없음 |
| TLS | 선택 | 사실상 필수 | 필수 (내장) |
| 연결 수립 | 1-RTT(TCP) + 2-RTT(TLS) | 동일 | 0~1-RTT |
| Server Push | 없음 | 있음 | 있음 |
| 헤더 압축 | 없음 | HPACK | QPACK |

---

## 실전 예시

### HTTP 버전 확인

```bash
# curl로 HTTP/2 지원 확인
curl -I --http2 https://api.allganize.ai/health
# HTTP/2 200 이 보이면 HTTP/2 지원

# HTTP/3 확인 (curl 7.66+ with nghttp3)
curl -I --http3 https://www.google.com

# nginx에서 사용 중인 프로토콜 확인
curl -sI https://example.com | grep -i "http/"

# openssl로 TLS + ALPN 협상 확인
openssl s_client -alpn h2 -connect example.com:443 2>/dev/null | grep "ALPN"
# ALPN protocol: h2  ← HTTP/2 협상 성공
```

### nginx HTTP/2 설정

```nginx
server {
    listen 443 ssl http2;           # HTTP/2 활성화
    server_name api.example.com;

    ssl_certificate     /etc/ssl/certs/server.crt;
    ssl_certificate_key /etc/ssl/private/server.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # HTTP/2 관련 튜닝
    http2_max_concurrent_streams 128;    # 동시 스트림 수
    http2_idle_timeout 300s;             # 유휴 연결 타임아웃

    location /api/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;          # upstream은 보통 HTTP/1.1
        proxy_set_header Connection "";   # Keep-Alive 유지
    }
}
```

### Kubernetes Ingress에서 HTTP/2

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-api-ingress
  annotations:
    # NGINX Ingress Controller — HTTP/2 기본 활성화
    nginx.ingress.kubernetes.io/proxy-http-version: "1.1"
    # ALB Ingress — HTTP/2 지원
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/scheme: internet-facing
spec:
  tls:
  - hosts:
    - api.allganize.ai
    secretName: tls-secret
  rules:
  - host: api.allganize.ai
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: alli-api
            port:
              number: 8080
```

### HTTP/1.1 vs HTTP/2 성능 비교 테스트

```bash
# h2load: HTTP/2 벤치마크 도구
h2load -n 10000 -c 100 -m 10 https://api.example.com/health
# -n: 총 요청 수, -c: 동시 연결 수, -m: 연결당 동시 스트림

# HTTP/1.1 벤치마크 (비교용)
ab -n 10000 -c 100 https://api.example.com/health
```

---

## 면접 Q&A

### Q: HTTP/1.1과 HTTP/2의 핵심 차이를 설명해주세요.

**30초 답변**:
HTTP/1.1은 요청-응답이 직렬 처리되어 Head-of-Line Blocking이 발생합니다. HTTP/2는 하나의 TCP 연결 위에서 **바이너리 프레이밍**과 **멀티플렉싱**으로 여러 요청을 병렬 처리합니다. HPACK 헤더 압축으로 대역폭도 절약됩니다.

**2분 답변**:
HTTP/1.1의 가장 큰 문제는 HOL Blocking입니다. 하나의 연결에서 앞선 응답이 완료되어야 다음 요청을 처리할 수 있습니다. 브라우저는 이를 우회하기 위해 도메인당 6개 연결을 열지만, 각 연결마다 TCP 핸드셰이크와 TLS 협상 비용이 발생합니다.

HTTP/2는 이를 **단일 TCP 연결 위의 멀티플렉싱**으로 해결합니다. 각 요청/응답은 독립적인 스트림으로, 바이너리 프레임 단위로 인터리빙되어 전송됩니다. 하나의 응답이 느려도 다른 스트림은 영향받지 않습니다.

추가로 HPACK 헤더 압축은 정적/동적 테이블을 사용해 중복 헤더(Cookie, User-Agent 등)를 효율적으로 처리합니다. Server Push 기능도 있지만, 캐시 무효화 문제 등으로 실무에서는 거의 사용하지 않습니다.

다만 HTTP/2도 **TCP 레벨의 HOL Blocking**은 여전합니다. TCP 패킷 하나가 유실되면 그 위의 모든 스트림이 재전송을 기다려야 하는데, 이것이 HTTP/3(QUIC)가 UDP를 선택한 이유입니다.

**경험 연결**:
"폐쇄망 환경에서 내부 웹 서비스를 운영할 때 HTTP/1.1 기반이었는데, 다수의 API 호출이 직렬화되어 대시보드 로딩이 느린 문제가 있었습니다. nginx에서 HTTP/2를 활성화하고 도메인 샤딩을 제거한 후 체감 속도가 크게 개선된 경험이 있습니다."

**주의**:
- HTTP/2가 항상 빠른 것은 아님. **패킷 유실률이 높은 환경**에서는 TCP HOL Blocking으로 HTTP/1.1의 다중 연결보다 느려질 수 있음
- HTTP/2는 스펙상 TLS 필수가 아니지만, 모든 주요 브라우저가 TLS 위에서만 지원 (h2 vs h2c)

### Q: HTTP/3과 QUIC가 등장한 이유는 무엇인가요?

**30초 답변**:
HTTP/2는 TCP 위에서 동작하므로 **TCP 레벨의 HOL Blocking** 문제가 남아있습니다. QUIC은 UDP 위에 새로운 전송 계층을 구현하여, 스트림 간 독립성을 보장하고 0-RTT 연결 재개와 연결 마이그레이션을 지원합니다.

**2분 답변**:
HTTP/2의 멀티플렉싱은 HTTP 레벨의 HOL Blocking을 해결했지만, TCP 레벨의 문제는 해결하지 못했습니다. TCP는 순서 보장 프로토콜이라, 하나의 패킷이 유실되면 해당 TCP 연결 위의 **모든** HTTP/2 스트림이 재전송을 기다립니다.

QUIC은 이를 해결하기 위해 UDP 위에 새로운 전송 프로토콜을 구현했습니다. 각 스트림이 독립적인 순서 보장을 가지므로, Stream A의 패킷 유실이 Stream B에 영향을 주지 않습니다.

추가적으로 QUIC은 TLS 1.3을 프로토콜 내부에 통합하여 핸드셰이크를 1-RTT로 줄이고, 이전에 연결했던 서버에는 0-RTT로 데이터를 보낼 수 있습니다. 또한 Connection ID 기반으로 동작하여 IP 주소가 바뀌어도(모바일 환경에서 Wi-Fi→LTE 전환) 연결이 유지됩니다.

TCP는 OS 커널에 구현되어 있어 변경이 매우 어렵지만, QUIC은 유저스페이스에서 동작하므로 빠른 프로토콜 개선이 가능하다는 장점도 있습니다.

**경험 연결**:
"모바일 솔루션 프로젝트에서 네트워크 전환(Wi-Fi↔LTE) 시 세션이 끊기는 문제를 경험했습니다. 당시에는 애플리케이션 레벨에서 재연결 로직을 구현했는데, QUIC의 Connection Migration이 이 문제를 프로토콜 레벨에서 해결하는 것을 알게 되었습니다."

**주의**:
- QUIC이 UDP를 쓴다고 해서 "비신뢰성" 프로토콜이 아님. QUIC **자체적으로** 신뢰성, 흐름제어, 혼잡제어를 구현
- 일부 기업 방화벽이 UDP 443을 차단할 수 있어, HTTP/3은 항상 HTTP/2로 폴백 가능해야 함

### Q: HTTPS가 왜 필수인지, 성능 오버헤드는 어느 정도인지 설명해주세요.

**30초 답변**:
HTTPS는 **기밀성**(도청 방지), **무결성**(변조 탐지), **인증**(서버 신원 확인)을 보장합니다. TLS 1.3 기준 핸드셰이크는 1-RTT이며, 현대 CPU의 AES-NI 하드웨어 가속 덕분에 암호화 오버헤드는 무시할 수 있는 수준입니다.

**2분 답변**:
HTTP 평문 통신의 세 가지 위험이 있습니다. 첫째, **도청** — 같은 네트워크의 공격자가 패킷을 캡처하면 API 키, 사용자 데이터가 그대로 노출됩니다. 둘째, **변조** — 중간자(MITM)가 응답을 수정할 수 있습니다. 셋째, **위장** — DNS 스푸핑으로 가짜 서버에 연결될 수 있습니다.

HTTPS는 TLS 계층을 추가하여 이 세 가지를 모두 해결합니다. 성능 측면에서 과거에는 TLS 1.2의 2-RTT 핸드셰이크가 부담이었지만, TLS 1.3은 1-RTT로 줄었고 0-RTT 재개도 지원합니다.

암호화 자체의 CPU 부하도 현대 하드웨어에서는 미미합니다. Intel AES-NI 명령어 세트가 AES 암호화를 하드웨어 레벨에서 처리하므로, HTTPS로 인한 throughput 감소는 1~2% 미만입니다.

또한 SEO(Google 검색 순위), 브라우저 신뢰 표시, HTTP/2 사용 등 HTTPS가 아니면 이용할 수 없는 기능이 많아 사실상 필수입니다.

**경험 연결**:
"폐쇄망에서도 내부 통신에 자체 CA를 구축하여 HTTPS를 적용했습니다. 초기에는 '내부 네트워크니까 HTTP도 괜찮다'는 의견이 있었지만, 내부자 위협과 감사 요건을 고려하여 전면 HTTPS를 도입한 경험이 있습니다."

**주의**:
- "HTTPS는 느리다"는 더 이상 유효하지 않은 주장. 반드시 TLS 1.3 기준으로 답변할 것
- 0-RTT는 **Replay Attack** 위험이 있으므로 멱등(idempotent) 요청에만 사용해야 함

---

## Allganize 맥락

### Alli 서비스와의 연결

- **LLM API 통신**: Alli의 LLM 추론 API는 대용량 텍스트를 주고받으므로 HTTP/2의 헤더 압축과 멀티플렉싱이 latency 절감에 직접적
- **스트리밍 응답**: ChatGPT 스타일의 토큰 스트리밍에 HTTP/2 Server-Sent Events(SSE)가 적합하며, gRPC(HTTP/2 기반)도 내부 서비스 간 통신에 활용 가능
- **멀티클라우드 통신**: AWS↔Azure 간 서비스 통신에서 HTTPS는 필수. 퍼블릭 인터넷을 거치는 경우 TLS 1.3 적용이 보안 기본선
- **ALB/NLB 선택**: AWS ALB는 HTTP/2를 기본 지원하지만, backend로는 HTTP/1.1로 변환. NLB는 TCP 레벨이므로 end-to-end HTTP/2가 필요하면 NLB + nginx 조합 고려
- **인증서 관리**: cert-manager로 Let's Encrypt 인증서를 자동 갱신하여 HTTPS 운영 부담 최소화

### JD 연결 포인트

```
JD: "안정적인 서비스 운영" → HTTPS 기반 보안 통신 + HTTP/2 최적화
JD: "AWS/Azure 멀티클라우드" → 클라우드 간 HTTPS 통신, ALB HTTP/2 설정
JD: "모니터링/관측가능성" → HTTP 상태 코드 기반 에러율 모니터링
```

---

**핵심 키워드**: `HTTP/2` `멀티플렉싱` `QUIC` `HOL-Blocking` `TLS` `바이너리-프레이밍` `HPACK` `0-RTT`
