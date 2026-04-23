# 07. TCP/UDP와 연결 관리 — 3-Way Handshake, TIME_WAIT, Keep-Alive, Connection Pooling

> **TL;DR**
> - TCP는 **3-Way Handshake**(SYN→SYN-ACK→ACK)로 연결을 수립하고, **4-Way Handshake**(FIN→ACK→FIN→ACK)로 종료하며, **TIME_WAIT** 상태로 지연 패킷을 처리한다.
> - **Keep-Alive**는 TCP 연결을 재사용하여 핸드셰이크 오버헤드를 줄이고, **Connection Pooling**은 미리 연결을 확보하여 latency를 최소화한다.
> - 고성능 서비스에서 TIME_WAIT 누적, 연결 고갈, FD 부족 등은 흔한 장애 원인이며, 커널 파라미터 튜닝이 필요하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### TCP 3-Way Handshake (연결 수립)

```
클라이언트                                     서버
 (CLOSED)                                   (LISTEN)
    │                                          │
    │─── SYN (seq=x) ────────────────────────→│   1단계: 연결 요청
    │    (SYN_SENT)                            │   (SYN_RECEIVED)
    │                                          │
    │←── SYN-ACK (seq=y, ack=x+1) ───────────│   2단계: 요청 수락 + 역요청
    │                                          │
    │─── ACK (ack=y+1) ──────────────────────→│   3단계: 역요청 확인
    │    (ESTABLISHED)                         │   (ESTABLISHED)
    │                                          │
    │═══════ 데이터 전송 시작 ═════════════════│

각 단계의 의미:
1. SYN: "연결하고 싶습니다. 내 시작 시퀀스 번호는 x입니다."
2. SYN-ACK: "수락합니다. 내 시작 시퀀스는 y이고, 당신의 x를 받았습니다(ack=x+1)."
3. ACK: "당신의 y를 확인했습니다(ack=y+1). 데이터를 보내겠습니다."

왜 3단계인가?
- 2단계(SYN→SYN-ACK)만으로는 클라이언트가 서버의 SYN-ACK을 받았는지 서버가 모름
- 3단계를 통해 양방향 통신 가능 여부를 모두 확인
- ISN(Initial Sequence Number) 교환으로 패킷 순서 보장의 기반 마련
```

### TCP 4-Way Handshake (연결 종료)

```
클라이언트                                     서버
 (ESTABLISHED)                              (ESTABLISHED)
    │                                          │
    │─── FIN (seq=u) ───────────────────────→│   1: "보낼 데이터 없음"
    │    (FIN_WAIT_1)                          │   (CLOSE_WAIT)
    │                                          │
    │←── ACK (ack=u+1) ─────────────────────│   2: "FIN 받았음"
    │    (FIN_WAIT_2)                          │   서버는 아직 보낼 데이터 있을 수 있음
    │                                          │
    │    ...서버가 남은 데이터 전송 완료...      │
    │                                          │
    │←── FIN (seq=v) ───────────────────────│   3: "나도 보낼 데이터 없음"
    │    (TIME_WAIT)                           │   (LAST_ACK)
    │                                          │
    │─── ACK (ack=v+1) ─────────────────────→│   4: "종료 확인"
    │                                          │   (CLOSED)
    │                                          │
    │    === 2MSL 대기 ===                     │
    │    (TIME_WAIT → CLOSED)                  │

왜 4단계인가?
- TCP는 양방향(Full-Duplex) → 각 방향을 독립적으로 종료
- 서버가 FIN을 받아도 아직 보내야 할 데이터가 있을 수 있음
- 따라서 ACK(수신 종료 확인)과 FIN(송신 종료)이 별도
```

### TIME_WAIT 상태

```
TIME_WAIT의 존재 이유:

시나리오 1: 마지막 ACK 유실
  클라이언트           서버
      │←── FIN ──────│
      │─── ACK ──────→│ ← 이 ACK가 유실되면?
      │ (CLOSED)       │ (LAST_ACK)
                       │ FIN 재전송... 하지만 클라이언트가 이미 CLOSED
                       │ → RST 응답 → 비정상 종료!

  해결: TIME_WAIT 동안 대기하면 FIN 재전송에 ACK 응답 가능

시나리오 2: 지연 패킷 (Wandering Duplicate)
  이전 연결의 패킷이 네트워크에서 지연되다가
  같은 소스/목적지 포트로 새 연결이 열리면
  지연 패킷이 새 연결에 잘못 전달될 수 있음

  해결: TIME_WAIT(2MSL=60초) 동안 같은 포트 조합 재사용 방지

TIME_WAIT 문제:
┌──────────────────────────────────────────────┐
│  고 트래픽 서버에서 TIME_WAIT 소켓 폭증        │
│                                              │
│  $ ss -s                                     │
│  TCP: 65000 (estab 5000, closed 50000,       │
│       orphaned 100, timewait 48000)          │
│                                              │
│  → 포트 고갈 (ephemeral port 부족)            │
│  → 새 연결 실패 (EADDRNOTAVAIL)               │
└──────────────────────────────────────────────┘
```

### TIME_WAIT 최적화 (커널 파라미터)

```bash
# 현재 TIME_WAIT 소켓 수 확인
ss -s | grep timewait
ss -tan state time-wait | wc -l

# 커널 파라미터 튜닝
cat >> /etc/sysctl.conf << 'EOF'
# Ephemeral 포트 범위 확대 (기본: 32768-60999)
net.ipv4.ip_local_port_range = 1024 65535

# TIME_WAIT 소켓 재사용 (클라이언트 측)
net.ipv4.tcp_tw_reuse = 1          # 타임스탬프가 증가하는 경우 재사용 허용

# TCP 타임스탬프 (tcp_tw_reuse의 전제조건)
net.ipv4.tcp_timestamps = 1

# SYN Backlog (3-Way Handshake 대기 큐)
net.ipv4.tcp_max_syn_backlog = 65535
net.core.somaxconn = 65535

# FIN_WAIT_2 타임아웃 (기본 60초)
net.ipv4.tcp_fin_timeout = 30

# TCP keepalive 설정
net.ipv4.tcp_keepalive_time = 600    # 유휴 후 keepalive 시작 (초)
net.ipv4.tcp_keepalive_intvl = 60    # keepalive 간격
net.ipv4.tcp_keepalive_probes = 3    # 실패 허용 횟수
EOF

sysctl -p
```

### TCP vs UDP

```
TCP (Transmission Control Protocol):
┌──────────────────────────────────────┐
│ ✓ 신뢰성: 순서 보장, 재전송, 흐름제어 │
│ ✓ 연결 지향: 3-Way Handshake         │
│ ✓ 혼잡 제어: 네트워크 상태에 적응      │
│ ✗ 오버헤드: 헤더 20바이트+, 핸드셰이크 │
│                                      │
│ 사용처: HTTP, HTTPS, SSH, DB, SMTP    │
└──────────────────────────────────────┘

UDP (User Datagram Protocol):
┌──────────────────────────────────────┐
│ ✓ 빠름: 핸드셰이크 없음, 헤더 8바이트 │
│ ✓ 경량: 상태 유지 불필요               │
│ ✓ 멀티캐스트/브로드캐스트 지원          │
│ ✗ 비신뢰성: 순서/재전송 보장 없음       │
│                                      │
│ 사용처: DNS, QUIC, 스트리밍, 게임, VoIP│
└──────────────────────────────────────┘
```

| 특성 | TCP | UDP |
|------|-----|-----|
| 연결 | 연결 지향 | 비연결 |
| 신뢰성 | 순서 보장, 재전송 | 보장 없음 |
| 헤더 크기 | 20~60 바이트 | 8 바이트 |
| 흐름 제어 | Sliding Window | 없음 |
| 혼잡 제어 | Slow Start, AIMD 등 | 없음 |
| 속도 | 상대적으로 느림 | 빠름 |
| 1:N 통신 | 불가 | 멀티캐스트 가능 |

### HTTP Keep-Alive

```
Keep-Alive 없음 (HTTP/1.0 기본):
  요청 1: TCP 연결 → TLS → HTTP 요청 → 응답 → TCP 종료
  요청 2: TCP 연결 → TLS → HTTP 요청 → 응답 → TCP 종료  ← 매번 새 연결!
  요청 3: TCP 연결 → TLS → HTTP 요청 → 응답 → TCP 종료

  각 요청마다 3-Way Handshake + TLS Handshake = 수 RTT 낭비

Keep-Alive 사용 (HTTP/1.1 기본):
  TCP 연결 → TLS
  요청 1: HTTP 요청 → 응답                    ← 연결 유지
  요청 2: HTTP 요청 → 응답                    ← 같은 연결 재사용
  요청 3: HTTP 요청 → 응답                    ← 같은 연결 재사용
  ...유휴 시간 초과 시 연결 종료

  핸드셰이크는 첫 번째만! 이후 요청은 즉시 전송
```

### Connection Pooling

```
Connection Pooling 없음:
┌──────────────┐          ┌──────────────┐
│ Application  │          │   Database    │
│              │─ conn 1 →│              │  요청마다 새 연결 생성
│              │─ conn 2 →│              │  → 연결 생성 비용 높음
│              │─ conn 3 →│              │  → max_connections 도달 위험
│              │─ conn 4 →│              │
└──────────────┘          └──────────────┘

Connection Pooling:
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Application  │   │ Connection   │   │   Database    │
│              │──→│ Pool         │──→│              │
│ Thread 1 ───│──→│ ┌──── conn1 ─│──→│              │
│ Thread 2 ───│──→│ │     conn2 ─│──→│              │  미리 N개 연결 확보
│ Thread 3 ───│──→│ │     conn3 ─│──→│              │  요청 시 대여/반납
│ (대기)       │   │ │     conn4 ─│──→│              │  → 연결 생성 비용 제거
│              │   │ └     conn5 ─│──→│              │  → 안정적 연결 수 관리
└──────────────┘   └──────────────┘   └──────────────┘

Connection Pool 파라미터:
  - minIdle: 최소 유휴 연결 수
  - maxActive: 최대 활성 연결 수
  - maxWait: 연결 대기 최대 시간
  - validationQuery: 연결 유효성 검증
  - maxLifetime: 연결 최대 수명
```

### TCP 상태 전이도 (요약)

```
        ┌─────────┐
        │ CLOSED  │
        └────┬────┘
  클라이언트: │ SYN 전송
        ┌────▼────┐
        │SYN_SENT │
        └────┬────┘
             │ SYN-ACK 수신, ACK 전송
        ┌────▼────────┐                    서버:
        │ESTABLISHED  │◄──────────────── SYN 수신 → SYN-ACK
        └────┬────────┘                  ACK 수신 → ESTABLISHED
  FIN 전송:  │
        ┌────▼────────┐
        │FIN_WAIT_1   │
        └────┬────────┘
  ACK 수신:  │
        ┌────▼────────┐              상대방:
        │FIN_WAIT_2   │              FIN 수신 → CLOSE_WAIT
        └────┬────────┘              FIN 전송 → LAST_ACK
  FIN 수신:  │
        ┌────▼────────┐
        │TIME_WAIT    │── 2MSL 대기 ──→ CLOSED
        └─────────────┘
```

---

## 실전 예시

### TCP 연결 상태 모니터링

```bash
# 전체 TCP 연결 상태 요약
ss -s

# 상태별 TCP 연결 수
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn

# TIME_WAIT 연결 목록
ss -tan state time-wait

# ESTABLISHED 연결 (원격 주소 기준 정렬)
ss -tan state established | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn

# 특정 포트의 연결 상태
ss -tan 'sport = :8080'

# netstat 대안 (구형 시스템)
netstat -an | grep -c TIME_WAIT

# TCP 연결 추적 (실시간)
watch -n 1 'ss -s'
```

### nginx Keep-Alive 설정

```nginx
http {
    # 클라이언트 → nginx (downstream)
    keepalive_timeout 65;              # Keep-Alive 유지 시간 (초)
    keepalive_requests 1000;           # 하나의 연결에서 최대 요청 수

    upstream backend {
        server 10.0.1.10:8080;
        server 10.0.1.11:8080;

        # nginx → backend (upstream) Keep-Alive
        keepalive 32;                  # 유휴 Keep-Alive 연결 풀 크기
        keepalive_requests 1000;       # 연결당 최대 요청 수
        keepalive_timeout 60s;         # 유휴 연결 타임아웃
    }

    server {
        listen 80;

        location / {
            proxy_pass http://backend;
            proxy_http_version 1.1;           # Keep-Alive에 필수!
            proxy_set_header Connection "";    # Connection: close 제거
        }
    }
}
```

### Python Connection Pooling 예시

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Connection Pool이 있는 Session
session = requests.Session()

# Connection Pool 설정
adapter = HTTPAdapter(
    pool_connections=10,      # 호스트당 Connection Pool 수
    pool_maxsize=20,          # Pool당 최대 연결 수
    max_retries=Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504]
    )
)
session.mount("https://", adapter)
session.mount("http://", adapter)

# 여러 요청이 연결을 재사용
for i in range(100):
    response = session.get("https://api.allganize.ai/health")
    # 매번 새 TCP/TLS 연결을 만들지 않음!

session.close()
```

### Go HTTP Client Connection Pooling

```go
package main

import (
    "net"
    "net/http"
    "time"
)

func main() {
    transport := &http.Transport{
        MaxIdleConns:        100,              // 전체 최대 유휴 연결
        MaxIdleConnsPerHost: 10,               // 호스트당 최대 유휴 연결
        MaxConnsPerHost:     50,               // 호스트당 최대 연결
        IdleConnTimeout:     90 * time.Second, // 유휴 연결 타임아웃
        DialContext: (&net.Dialer{
            Timeout:   30 * time.Second,       // 연결 타임아웃
            KeepAlive: 30 * time.Second,       // TCP Keep-Alive
        }).DialContext,
        TLSHandshakeTimeout: 10 * time.Second,
    }

    client := &http.Client{
        Transport: transport,
        Timeout:   60 * time.Second,
    }

    // client를 재사용하면 Connection Pooling 자동 적용
    resp, err := client.Get("https://api.allganize.ai/health")
    // ...
}
```

### Kubernetes에서 Connection 문제 디버깅

```bash
# Pod 내부의 TCP 연결 상태 확인
kubectl exec -it <pod-name> -- ss -s
kubectl exec -it <pod-name> -- ss -tan state time-wait | wc -l

# conntrack 테이블 확인 (kube-proxy 관련)
kubectl exec -it <node-debugger-pod> -- conntrack -S
kubectl exec -it <node-debugger-pod> -- conntrack -L | wc -l
# conntrack 테이블 가득 차면 패킷 드롭!

# conntrack 최대값 확인/조정
sysctl net.netfilter.nf_conntrack_max
sysctl net.netfilter.nf_conntrack_count

# 조정
sysctl -w net.netfilter.nf_conntrack_max=262144
```

---

## 면접 Q&A

### Q: TCP 3-Way Handshake의 각 단계를 설명해주세요.

**30초 답변**:
클라이언트가 **SYN**(시퀀스 번호 포함)을 보내고, 서버가 **SYN-ACK**(자신의 시퀀스 + 클라이언트 확인)으로 응답하고, 클라이언트가 **ACK**로 확인합니다. 이 3단계로 양방향 통신 가능 여부를 확인하고 초기 시퀀스 번호를 교환합니다.

**2분 답변**:
TCP 3-Way Handshake는 신뢰할 수 있는 연결을 수립하기 위한 과정입니다.

1단계 **SYN**: 클라이언트가 서버에 연결 요청을 보냅니다. 이때 ISN(Initial Sequence Number)을 함께 전송합니다. ISN은 보안을 위해 랜덤으로 생성되며, 이후 데이터 순서 추적에 사용됩니다.

2단계 **SYN-ACK**: 서버가 연결을 수락하며, 두 가지를 동시에 합니다. 클라이언트의 SYN에 대한 확인(ACK=클라이언트 ISN+1)과, 서버 자신의 SYN(서버 ISN)을 함께 보냅니다.

3단계 **ACK**: 클라이언트가 서버의 SYN을 확인합니다(ACK=서버 ISN+1). 이 단계부터 데이터를 포함할 수 있습니다.

3단계가 필요한 이유는 **양방향 연결 확인** 때문입니다. 2단계만으로는 서버가 보낸 SYN-ACK을 클라이언트가 수신했는지 서버가 알 수 없습니다. 또한 네트워크 지연으로 인한 **오래된 SYN 패킷**이 새 연결로 오인되는 것도 방지합니다.

SYN Flood 공격은 1단계에서 대량의 SYN을 보내고 3단계 ACK를 보내지 않아 서버의 SYN 큐를 고갈시키는 공격이며, **SYN Cookie**로 방어합니다.

**경험 연결**:
"서버에 SYN Flood 공격이 의심되는 상황에서 `ss -s`로 SYN_RECV 상태가 비정상적으로 많은 것을 확인하고, `net.ipv4.tcp_syncookies=1`을 활성화하여 방어한 경험이 있습니다."

**주의**:
- ISN은 0부터 시작하지 않고 랜덤 → TCP Session Hijacking 방지
- TFO(TCP Fast Open)는 SYN에 데이터를 포함하여 1-RTT 절약 (HTTP/1.1에서 유용)

### Q: TIME_WAIT가 왜 존재하고, 이것이 문제가 되는 경우는?

**30초 답변**:
TIME_WAIT는 **2MSL(보통 60초)** 동안 유지되며, 두 가지를 보장합니다. 마지막 ACK 유실 시 FIN 재전송에 응답할 수 있게 하고, 이전 연결의 지연 패킷이 새 연결에 혼입되는 것을 방지합니다. 고 트래픽 서버에서 TIME_WAIT 소켓이 수만 개 누적되면 **포트 고갈** 문제가 발생합니다.

**2분 답변**:
TIME_WAIT는 TCP 연결 종료 시 **능동적으로 종료를 시작한 측**(보통 클라이언트)에 발생합니다.

존재 이유는 두 가지입니다. 첫째, 마지막 ACK가 유실된 경우 상대방이 FIN을 재전송하면 이에 응답할 수 있어야 합니다. 즉시 CLOSED로 전환하면 상대방의 FIN 재전송에 RST로 응답하여 비정상 종료가 됩니다.

둘째, **지연 패킷(wandering duplicate) 보호**입니다. 이전 연결의 패킷이 네트워크에서 지연되다가, 같은 소스/목적지 포트 조합의 새 연결에 잘못 전달될 수 있습니다. 2MSL 대기로 이를 방지합니다.

**문제가 되는 경우**: 고 트래픽 프록시(nginx, HAProxy)나 대량의 외부 API를 호출하는 서비스에서 TIME_WAIT 소켓이 수만 개 누적되면 ephemeral port가 고갈됩니다. 65535 - 1024 = 약 64,000개의 포트만 사용 가능하므로, 대상 IP가 동일한 경우 금방 소진됩니다.

해결 방법:
1. `tcp_tw_reuse=1`: 타임스탬프 조건 하에 TIME_WAIT 소켓 재사용 (클라이언트 측)
2. `ip_local_port_range` 확대
3. **Connection Pooling**: 연결을 재사용하여 TIME_WAIT 자체를 줄임 (근본 해결)
4. `tcp_fin_timeout` 단축: FIN_WAIT_2 대기 시간 감소

**경험 연결**:
"프록시 서버에서 외부 API 호출이 증가했을 때 `EADDRNOTAVAIL` 오류가 발생한 적이 있습니다. `ss -s`로 TIME_WAIT가 5만 개 이상인 것을 확인하고, tcp_tw_reuse 활성화와 Connection Pooling 도입으로 해결했습니다."

**주의**:
- `tcp_tw_recycle`은 NAT 환경에서 심각한 문제를 일으키므로 **절대 사용하지 말 것** (Linux 4.12에서 제거됨)
- TIME_WAIT는 **서버 측보다 클라이언트 측**에서 더 문제 (서버가 close를 먼저 하면 서버에 TIME_WAIT 누적)

### Q: Connection Pooling이 왜 중요한가요?

**30초 답변**:
매 요청마다 TCP + TLS 연결을 새로 만들면 **핸드셰이크 비용**(수 RTT)이 발생하고, TIME_WAIT 소켓이 누적됩니다. Connection Pooling은 미리 연결을 확보하고 재사용하여 **latency 절감**, **리소스 절약**, **안정적 연결 수 관리**를 달성합니다.

**2분 답변**:
Connection Pooling이 없으면 매 요청마다:
1. TCP 3-Way Handshake: 1 RTT
2. TLS Handshake: 1~2 RTT
3. 데이터 전송
4. TCP 4-Way Handshake + TIME_WAIT

이 과정에서 **3~4 RTT의 오버헤드**가 매번 발생합니다. 서울↔도쿄 RTT가 30ms라면, 매 요청마다 90~120ms가 핸드셰이크에 소비됩니다.

Connection Pooling의 이점:
- **Latency 감소**: 핸드셰이크 비용 제거, 첫 요청 이후 즉시 데이터 전송
- **TIME_WAIT 감소**: 연결을 종료하지 않고 재사용하므로 TIME_WAIT 누적 방지
- **리소스 절약**: 서버 측의 동시 연결 수를 제어 가능 (DB의 max_connections 보호)
- **안정성**: 연결 유효성 검증, 자동 재연결 등 복원력 기능

주의할 점은 Pool 크기 설정입니다. 너무 작으면 연결 대기(starvation), 너무 크면 유휴 연결이 서버 리소스를 낭비합니다. maxLifetime을 설정하여 오래된 연결을 주기적으로 갱신하는 것도 중요합니다.

Kubernetes 환경에서 Service(ClusterIP)를 통해 접근할 때, kube-proxy의 iptables 규칙은 **새 연결**에만 적용됩니다. Connection Pool을 사용하면 기존 연결이 특정 Pod에 고정되어 로드 밸런싱이 편향될 수 있으므로, maxLifetime이나 maxRequests로 주기적 갱신이 필요합니다.

**경험 연결**:
"DB 커넥션 풀 설정이 너무 커서 MongoDB의 max_connections에 도달하여 장애가 발생한 적이 있습니다. 각 Pod의 Pool 크기 x Pod 수가 DB의 max_connections를 초과하지 않도록 계산하여 조정했습니다."

**주의**:
- Kubernetes Service를 통한 Connection Pooling에서 Pod 스케일링 시 기존 연결이 종료된 Pod를 가리킬 수 있음 → Graceful Shutdown + Connection Drain 필수
- HTTP/2는 프로토콜 레벨에서 멀티플렉싱을 지원하므로, HTTP/1.1의 Connection Pool과 다른 전략 필요

---

## Allganize 맥락

### Alli 서비스와의 연결

- **LLM 추론 지연**: LLM API 호출 시 TCP+TLS 핸드셰이크 시간이 추론 시간에 추가 → Connection Pooling 필수
- **외부 AI API 호출**: OpenAI/Claude API 등 외부 서비스 호출 시 Connection Pool로 latency 최소화
- **DB Connection Pool**: MongoDB/Elasticsearch에 대한 Connection Pool 크기를 Pod 수 x Pool 크기 < DB max_connections로 관리
- **conntrack 관리**: 대규모 K8s 클러스터에서 conntrack 테이블 고갈은 흔한 장애 원인 → nf_conntrack_max 튜닝
- **Graceful Shutdown**: Pod 종료 시 기존 TCP 연결을 정상 종료하여 클라이언트 에러 방지

### JD 연결 포인트

```
JD: "안정적 서비스 운영"   → TCP 튜닝, Connection Pool, Graceful Shutdown
JD: "성능 분석"           → TIME_WAIT 분석, 연결 수 모니터링
JD: "Kubernetes"         → conntrack 관리, kube-proxy 이해
JD: "복원력"              → Connection Pool 복원력, 자동 재연결
```

---

**핵심 키워드**: `3-Way-Handshake` `TIME_WAIT` `Keep-Alive` `Connection-Pooling` `tcp_tw_reuse` `conntrack` `FIN_WAIT` `SYN-Flood` `Graceful-Shutdown`
