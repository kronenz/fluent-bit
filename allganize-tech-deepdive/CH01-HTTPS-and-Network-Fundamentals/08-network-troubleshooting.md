# 08. 네트워크 트러블슈팅 — tcpdump, Wireshark, curl, dig, nslookup, traceroute 실전 활용

> **TL;DR**
> - 네트워크 문제는 **DNS → 연결 → TLS → 애플리케이션** 순서로 단계적으로 진단한다.
> - **tcpdump**로 패킷을 캡처하고, **curl**로 HTTP 레벨을 디버깅하고, **dig/nslookup**로 DNS를 확인하고, **traceroute**로 경로를 추적한다.
> - Kubernetes 환경에서는 Pod 내부에서의 디버깅, CoreDNS 로그 확인, conntrack 분석 등 추가적인 도구와 기법이 필요하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 네트워크 트러블슈팅 체계적 접근법

```
문제 발생: "서비스에 접속이 안 됩니다"

단계 1: DNS 확인 ──────────────────────────────────────────
  도메인이 올바른 IP로 해석되는가?
  도구: dig, nslookup, host

단계 2: 네트워크 도달성 확인 ──────────────────────────────
  해당 IP/포트에 도달할 수 있는가?
  도구: ping, telnet, nc, traceroute, mtr

단계 3: TCP 연결 확인 ─────────────────────────────────────
  TCP 3-Way Handshake가 완료되는가?
  도구: tcpdump, ss, netstat

단계 4: TLS 확인 ──────────────────────────────────────────
  TLS Handshake가 성공하는가? 인증서가 유효한가?
  도구: openssl s_client, curl -v

단계 5: 애플리케이션 확인 ─────────────────────────────────
  HTTP 요청/응답이 정상인가?
  도구: curl, wget, httpie

단계 6: 성능 확인 ─────────────────────────────────────────
  응답 시간이 정상인가? 어느 단계에서 지연되는가?
  도구: curl -w, tcpdump 타임스탬프, mtr
```

### 각 도구의 위치

```
┌──────────── OSI 계층별 디버깅 도구 ────────────┐
│                                                 │
│  Layer 7 (Application)                          │
│    curl, wget, httpie, grpcurl                  │
│                                                 │
│  Layer 5-6 (Session/Presentation)               │
│    openssl s_client, ssldump                    │
│                                                 │
│  Layer 4 (Transport)                            │
│    ss, netstat, tcpdump, nc(netcat), telnet     │
│                                                 │
│  Layer 3 (Network)                              │
│    ping, traceroute, mtr, ip route              │
│                                                 │
│  Layer 2 (Data Link)                            │
│    arp, ip neigh, ethtool                       │
│                                                 │
│  DNS (별도):                                    │
│    dig, nslookup, host, resolvectl              │
│                                                 │
│  패킷 분석 (종합):                               │
│    tcpdump (캡처), Wireshark (분석)              │
└─────────────────────────────────────────────────┘
```

---

## 실전 예시

### 1. DNS 디버깅 (dig / nslookup)

```bash
# 기본 DNS 조회
dig api.allganize.ai

# 상세 응답 (각 섹션 확인)
dig api.allganize.ai +noall +answer +authority +additional

# DNS 해석 전체 과정 추적
dig api.allganize.ai +trace
# ;; Received 239 bytes from 198.41.0.4#53(a.root-servers.net) in 36 ms
# ;; Received 631 bytes from 37.209.194.12#53(a.nic.ai) in 215 ms
# ;; Received 89 bytes from 205.251.195.143#53(ns-xxx.awsdns-xx.co.uk) in 8 ms

# 특정 DNS 서버에 질의 (캐시 우회)
dig api.allganize.ai @8.8.8.8
dig api.allganize.ai @1.1.1.1

# TTL 확인 (변경 전파 시간 파악)
dig api.allganize.ai +noall +answer
# api.allganize.ai.  278  IN  A  52.78.xxx.xxx
#                     ^^^ TTL (초)

# 역방향 DNS 조회
dig -x 52.78.xxx.xxx

# CNAME 체인 확인
dig www.allganize.ai +short
# allganize.ai.
# 52.78.xxx.xxx

# nslookup (간단한 확인)
nslookup api.allganize.ai
nslookup -type=MX allganize.ai
nslookup -type=NS allganize.ai

# host (가장 간결)
host api.allganize.ai
host -t AAAA api.allganize.ai

# Kubernetes CoreDNS 디버깅
kubectl run dnsutils --image=tutum/dnsutils --rm -it --restart=Never -- \
  dig alli-api.production.svc.cluster.local

# CoreDNS 로그 활성화
kubectl edit configmap coredns -n kube-system
# Corefile에 'log' 추가:
# .:53 {
#     log          ← 추가
#     errors
#     ...
```

### 2. 네트워크 도달성 확인 (ping / traceroute / mtr)

```bash
# ping — ICMP 도달성 확인
ping -c 5 api.allganize.ai
# 주의: 많은 서버가 ICMP를 차단하므로 ping 실패 != 서비스 다운

# traceroute — 경로 추적 (각 홉의 지연 확인)
traceroute api.allganize.ai
# 1  gateway (192.168.1.1)  1.234 ms  1.089 ms  0.987 ms
# 2  10.0.0.1               5.123 ms  4.987 ms  5.234 ms
# 3  * * *                  ← ICMP 차단 또는 타임아웃
# 4  52.78.xxx.xxx           15.345 ms  14.987 ms  15.123 ms

# TCP traceroute (ICMP 차단 시 대안)
traceroute -T -p 443 api.allganize.ai

# mtr — traceroute + ping 결합 (실시간 지속 모니터링)
mtr api.allganize.ai
mtr --report -c 100 api.allganize.ai    # 100번 측정 후 리포트

# mtr 출력 해석:
# HOST                   Loss%  Snt  Last  Avg  Best  Wrst  StDev
# 1. gateway              0.0%  100   1.2  1.3   0.9   3.4   0.5
# 2. isp-router           0.5%  100   5.1  5.3   4.8   8.2   0.8  ← 간헐적 패킷 로스
# 3. ???                   100%  100   ---  ---   ---   ---   ---   ← ICMP 차단 (무시)
# 4. target               0.0%  100  15.2 15.4  14.8  18.1   0.6

# TCP 포트 연결 테스트
nc -zv api.allganize.ai 443              # TCP 연결만 확인
nc -zv -w 5 api.allganize.ai 443        # 5초 타임아웃
telnet api.allganize.ai 443              # 대화형 연결
```

### 3. curl — HTTP 디버깅의 핵심

```bash
# 기본 요청
curl https://api.allganize.ai/health

# 상세 헤더 + TLS 정보
curl -v https://api.allganize.ai/health

# 매우 상세 (TLS 핸드셰이크 전체)
curl -vvv https://api.allganize.ai/health

# 각 단계별 소요 시간 측정 (★ 핵심 명령어)
curl -w "\n\
    DNS Lookup:   %{time_namelookup}s\n\
    TCP Connect:  %{time_connect}s\n\
    TLS Handshake:%{time_appconnect}s\n\
    TTFB:         %{time_starttransfer}s\n\
    Total:        %{time_total}s\n\
    HTTP Code:    %{http_code}\n\
    Size:         %{size_download} bytes\n\
" -o /dev/null -s https://api.allganize.ai/health

# 출력 예시:
#     DNS Lookup:   0.004s        ← DNS 해석
#     TCP Connect:  0.015s        ← TCP 핸드셰이크 완료
#     TLS Handshake:0.045s        ← TLS 핸드셰이크 완료
#     TTFB:         0.065s        ← 첫 바이트 수신
#     Total:        0.070s        ← 전체 완료
#
# 분석:
#   TCP RTT ≈ 0.015 - 0.004 = 0.011s (11ms)
#   TLS 시간 ≈ 0.045 - 0.015 = 0.030s (30ms)
#   서버 처리 ≈ 0.065 - 0.045 = 0.020s (20ms)

# HTTP/2로 요청
curl --http2 -I https://api.allganize.ai/health

# 특정 호스트 헤더로 요청 (DNS 우회)
curl -H "Host: api.allganize.ai" https://52.78.xxx.xxx/health

# DNS 해석 결과 지정 (--resolve)
curl --resolve api.allganize.ai:443:52.78.xxx.xxx \
  https://api.allganize.ai/health

# POST 요청 + JSON
curl -X POST https://api.allganize.ai/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"message": "hello", "model": "alli-turbo"}'

# 인증서 검증 무시 (디버깅용, 프로덕션 금지)
curl -k https://self-signed.example.com/

# 특정 CA 인증서로 검증
curl --cacert /path/to/rootCA.crt https://internal-service/

# 클라이언트 인증서 (mTLS)
curl --cert client.crt --key client.key https://mtls-service/

# 리다이렉트 추적
curl -L -v https://allganize.ai 2>&1 | grep "< HTTP\|< Location"

# 연결 재사용 테스트
curl -v https://api.allganize.ai/health https://api.allganize.ai/status
# "Re-using existing connection" 메시지 확인
```

### 4. tcpdump — 패킷 캡처

```bash
# 기본 캡처 (특정 호스트)
sudo tcpdump -i eth0 host api.allganize.ai

# TCP 3-Way Handshake 캡처
sudo tcpdump -i eth0 'tcp[tcpflags] & (tcp-syn|tcp-fin) != 0' \
  and host api.allganize.ai

# 특정 포트 캡처
sudo tcpdump -i eth0 port 443 -c 50

# 파일로 저장 (Wireshark에서 분석)
sudo tcpdump -i eth0 -w /tmp/capture.pcap host api.allganize.ai -c 1000

# 패킷 내용 확인 (ASCII)
sudo tcpdump -i eth0 -A port 80 and host api.example.com

# 패킷 내용 확인 (Hex + ASCII)
sudo tcpdump -i eth0 -XX port 80 -c 5

# DNS 쿼리 캡처
sudo tcpdump -i eth0 port 53 -vv

# TLS ClientHello의 SNI 확인
sudo tcpdump -i eth0 port 443 -A 2>/dev/null | grep -A5 "Client Hello"

# SYN 패킷만 캡처 (새 연결 추적)
sudo tcpdump -i eth0 'tcp[tcpflags] == tcp-syn'

# RST 패킷 캡처 (연결 거부/에러)
sudo tcpdump -i eth0 'tcp[tcpflags] & tcp-rst != 0'

# Kubernetes Pod 네트워크 캡처
# (ephemeral 컨테이너 사용)
kubectl debug -it <pod-name> --image=nicolaka/netshoot -- \
  tcpdump -i eth0 port 8080 -c 20

# 또는 노드에서 Pod의 veth 인터페이스 찾기
kubectl get pod <pod-name> -o jsonpath='{.status.podIP}'
# 노드에서:
nsenter -t $(docker inspect -f '{{.State.Pid}}' <container-id>) -n \
  tcpdump -i eth0 -c 20
```

### 5. Wireshark 분석 팁

```
tcpdump로 캡처 → Wireshark로 분석:
  sudo tcpdump -i eth0 -w capture.pcap -s 0 'host api.allganize.ai'

유용한 Wireshark 필터:

  # TLS 핸드셰이크 분석
  tls.handshake.type == 1          # ClientHello
  tls.handshake.type == 2          # ServerHello
  tls.handshake.type == 11         # Certificate

  # HTTP 분석
  http.request.method == "POST"
  http.response.code >= 400        # 에러 응답만

  # TCP 문제 분석
  tcp.analysis.retransmission      # 재전송 패킷
  tcp.analysis.duplicate_ack       # 중복 ACK
  tcp.analysis.zero_window         # 수신 버퍼 가득
  tcp.analysis.reset               # RST 패킷

  # DNS 분석
  dns.qry.name == "api.allganize.ai"
  dns.flags.rcode != 0             # DNS 에러

  # 특정 스트림 추적
  tcp.stream eq 5                  # 5번 TCP 스트림

Wireshark 통계:
  Statistics → Conversations → TCP → 연결별 데이터량/시간
  Statistics → IO Graphs → 시간별 트래픽 추이
  Analyze → Follow → TCP Stream → 단일 연결 전체 데이터
```

### 6. 종합 트러블슈팅 시나리오

```bash
# 시나리오: "api.allganize.ai에 접속이 안 됩니다"

# Step 1: DNS 확인
dig api.allganize.ai +short
# 결과 없음? → DNS 문제
# IP가 나옴? → Step 2로

# Step 2: 네트워크 도달성
nc -zv api.allganize.ai 443
# Connection refused? → 서버 포트가 닫혀있음
# Connection timed out? → 방화벽/네트워크 문제
# Connection succeeded? → Step 3로

# Step 3: TLS 확인
openssl s_client -connect api.allganize.ai:443 -servername api.allganize.ai \
  2>/dev/null | head -20
# Verify return code: 0 (ok) → TLS 정상
# certificate verify failed → 인증서 문제

# Step 4: HTTP 확인
curl -v https://api.allganize.ai/health
# HTTP 200? → 정상
# HTTP 5xx? → 서버 측 문제
# timeout? → Step 5로

# Step 5: 상세 시간 분석
curl -w "@/tmp/curl-format.txt" -o /dev/null -s \
  https://api.allganize.ai/health
# DNS가 느림? → DNS 서버 문제
# TCP 연결이 느림? → 네트워크 지연/혼잡
# TLS가 느림? → 서버 부하 또는 인증서 체인 문제
# TTFB가 느림? → 서버 처리 지연

# Step 6: 패킷 레벨 분석 (필요 시)
sudo tcpdump -i eth0 -w /tmp/debug.pcap host api.allganize.ai -c 100
# Wireshark에서 분석
```

### Kubernetes 환경 트러블슈팅

```bash
# Pod에서 서비스 접근 불가 시

# 1. DNS 확인
kubectl exec -it <pod> -- nslookup alli-api.production.svc.cluster.local
# 실패 시: CoreDNS 상태 확인
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50

# 2. Service → Endpoint 확인
kubectl get endpoints alli-api -n production
# Endpoint가 비어있으면 → selector 불일치 또는 Pod 미실행

# 3. Pod 네트워크 확인
kubectl exec -it <pod> -- curl -v http://alli-api.production:8080/health
# Pod 간 직접 통신 테스트
kubectl exec -it <pod> -- curl -v http://<target-pod-ip>:8080/health

# 4. NetworkPolicy 확인
kubectl get networkpolicy -n production
kubectl describe networkpolicy <policy-name> -n production

# 5. kube-proxy / iptables 확인
# (노드에서)
iptables -t nat -L KUBE-SERVICES | grep alli-api
# IPVS 모드:
ipvsadm -Ln | grep <cluster-ip>

# 6. conntrack 확인
conntrack -L -d <service-cluster-ip> 2>/dev/null | head
conntrack -S  # 통계 (drop 확인)

# 7. 네트워크 디버깅용 Pod 배포
kubectl run netshoot --image=nicolaka/netshoot --rm -it --restart=Never -- bash
# 이 Pod 안에서 tcpdump, dig, curl, ss 등 모든 도구 사용 가능
```

---

## 면접 Q&A

### Q: 서비스에 접속이 안 될 때 어떤 순서로 디버깅하시나요?

**30초 답변**:
**DNS → 네트워크 → TCP → TLS → HTTP** 순서로 하위 계층부터 확인합니다. `dig`으로 DNS 해석을 확인하고, `nc -zv`로 포트 도달성을 테스트하고, `curl -v`로 TLS와 HTTP를 한 번에 확인합니다. 필요시 `tcpdump`로 패킷 레벨 분석을 수행합니다.

**2분 답변**:
네트워크 문제는 하위 계층부터 단계적으로 확인하는 것이 원칙입니다.

**1단계 DNS**: `dig api.allganize.ai +short`로 도메인이 올바른 IP로 해석되는지 확인합니다. DNS 실패 시 `/etc/resolv.conf` 확인, 특정 DNS 서버(`@8.8.8.8`)로 교차 검증합니다.

**2단계 네트워크 도달성**: `nc -zv api.allganize.ai 443`으로 TCP 포트에 도달 가능한지 확인합니다. Connection timeout이면 방화벽이나 라우팅 문제를 의심하고, `traceroute -T -p 443`으로 경로를 추적합니다.

**3단계 TLS/HTTP**: `curl -v https://api.allganize.ai/health`로 TLS 핸드셰이크와 HTTP 응답을 확인합니다. 인증서 오류면 `openssl s_client`로 인증서 체인을 상세히 확인합니다.

**4단계 성능 문제**: `curl -w` 포맷으로 DNS, TCP, TLS, TTFB 각 단계의 소요 시간을 측정합니다. 특정 단계에서 지연이 발견되면 해당 계층을 집중 분석합니다.

**5단계 패킷 분석**: 위 단계에서 원인이 불명확하면 `tcpdump`로 패킷을 캡처하고 Wireshark에서 TCP 재전송, RST, Zero Window 등을 분석합니다.

Kubernetes 환경에서는 추가로 Service → Endpoint 매핑, NetworkPolicy, CoreDNS 상태, conntrack 테이블을 확인합니다.

**경험 연결**:
"폐쇄망에서 내부 서비스 간 간헐적 연결 실패가 발생했을 때, tcpdump로 패킷을 캡처하여 방화벽에서 특정 포트의 ESTABLISHED 패킷이 DROP되는 것을 발견했습니다. 방화벽의 conntrack 타임아웃이 서버의 Keep-Alive 타임아웃보다 짧아서 발생한 문제였고, 양쪽 타임아웃을 맞추어 해결했습니다."

**주의**:
- `ping` 실패가 서비스 다운을 의미하지는 않음 (ICMP 차단일 수 있음)
- `telnet`은 구형 도구이므로 `nc`(netcat)을 권장
- 프로덕션에서 tcpdump 사용 시 `-c`(패킷 수 제한)과 `-w`(파일 저장)을 반드시 사용

### Q: curl의 -w 옵션으로 성능을 분석하는 방법을 설명해주세요.

**30초 답변**:
`curl -w` 옵션으로 **DNS 조회(time_namelookup)**, **TCP 연결(time_connect)**, **TLS 핸드셰이크(time_appconnect)**, **첫 바이트(time_starttransfer)**, **전체 완료(time_total)** 각 단계의 소요 시간을 측정합니다. 인접 단계 간 차이를 계산하면 병목 구간을 정확히 파악할 수 있습니다.

**2분 답변**:
`curl -w` 포맷 문자열로 HTTP 트랜잭션의 각 단계 타이밍을 측정합니다.

주요 변수:
- `%{time_namelookup}`: DNS 해석 완료 시점
- `%{time_connect}`: TCP 3-Way Handshake 완료 시점
- `%{time_appconnect}`: TLS 핸드셰이크 완료 시점 (HTTPS)
- `%{time_starttransfer}`: 첫 바이트 수신 시점 (TTFB)
- `%{time_total}`: 전체 요청 완료 시점

각 구간의 소요 시간을 계산하면:
- TCP RTT ≈ time_connect - time_namelookup
- TLS 시간 ≈ time_appconnect - time_connect
- 서버 처리 시간 ≈ time_starttransfer - time_appconnect
- 데이터 전송 시간 ≈ time_total - time_starttransfer

예를 들어 TTFB가 2초인데, 서버 처리 시간이 1.9초라면 백엔드 성능 문제이고, TLS 시간이 1.5초라면 인증서 체인이 길거나 OCSP 조회 지연입니다.

이를 반복 측정하여 Prometheus에 push하면 외부 사용자 관점의 성능 모니터링이 가능합니다. Blackbox Exporter가 이와 동일한 방식으로 동작합니다.

**경험 연결**:
"서비스 응답이 느리다는 보고를 받았을 때, curl -w로 각 단계를 측정하여 DNS 해석에 비정상적으로 오래 걸리는 것을 발견했습니다. 로컬 DNS 캐시(systemd-resolved)가 정상 동작하지 않아 매 요청마다 외부 DNS를 조회하고 있었고, 캐시를 재시작하여 해결했습니다."

**주의**:
- `time_starttransfer`는 서버가 첫 바이트를 보낸 시점이므로 "서버 응답 시작"을 의미하며 전체 응답 완료가 아님
- 연결 재사용 시 DNS/TCP/TLS 시간이 0에 가까워짐 → 첫 요청과 이후 요청을 구분하여 측정

### Q: Kubernetes에서 Pod 간 통신 문제를 어떻게 디버깅하나요?

**30초 답변**:
먼저 `kubectl get endpoints`로 Service-Endpoint 매핑을 확인하고, Pod 내부에서 `curl`로 직접 통신을 테스트합니다. DNS 문제는 `nslookup`으로 CoreDNS를 확인하고, 네트워크 정책은 `NetworkPolicy`를 점검합니다. 필요시 `nicolaka/netshoot` 이미지로 디버깅 Pod를 띄워 `tcpdump`, `ss` 등을 사용합니다.

**2분 답변**:
Kubernetes 네트워크 디버깅은 일반적인 네트워크 디버깅에 K8s 고유의 레이어가 추가됩니다.

**Service 레벨**:
1. `kubectl get endpoints <svc> -n <ns>`로 Endpoint가 존재하는지 확인. 비어있으면 selector 불일치 또는 readinessProbe 실패
2. `kubectl describe svc <svc>`로 Service 설정 확인

**DNS 레벨**:
3. Pod 내에서 `nslookup <svc>.<ns>.svc.cluster.local`로 CoreDNS 동작 확인
4. CoreDNS Pod 로그 확인: `kubectl logs -n kube-system -l k8s-app=kube-dns`

**네트워크 레벨**:
5. Pod에서 직접 target Pod IP로 `curl` — 성공하면 Service 레벨 문제, 실패하면 네트워크 레벨 문제
6. NetworkPolicy 확인: `kubectl get networkpolicy -n <ns>` — 의도치 않은 차단 확인
7. CNI(Calico/Cilium) 로그 확인

**커널 레벨** (노드에서):
8. conntrack 테이블 확인: `conntrack -S`에서 drop이 증가하면 nf_conntrack_max 확대
9. iptables/IPVS 규칙 확인

디버깅 도구가 없는 경량 컨테이너에서는 `kubectl debug` 또는 `nicolaka/netshoot` 이미지가 필수적입니다.

**경험 연결**:
"Kubernetes 환경에서 특정 서비스 간 간헐적 타임아웃이 발생했을 때, conntrack 테이블이 가득 차서 새 연결이 DROP되는 것이 원인이었습니다. `conntrack -S`로 drop 카운터가 증가하는 것을 확인하고, nf_conntrack_max를 늘려 해결했습니다."

**주의**:
- 프로덕션 Pod에 exec로 들어가서 도구를 설치하지 말 것 → ephemeral container 또는 별도 디버깅 Pod 사용
- CoreDNS에 log 플러그인을 활성화하면 모든 DNS 쿼리가 기록되어 부하가 증가할 수 있으므로 임시로만 사용

---

## Allganize 맥락

### Alli 서비스와의 연결

- **LLM API 지연 분석**: curl -w로 API 게이트웨이 → LLM 엔진 간 각 단계의 latency를 측정하여 병목 파악
- **멀티클라우드 디버깅**: AWS↔Azure 간 통신 문제 시 traceroute/mtr로 경로를 확인하고 tcpdump로 패킷 분석
- **인증서 문제 대응**: cert-manager 인증서 갱신 실패 시 openssl s_client로 인증서 상태 확인
- **CoreDNS 모니터링**: CoreDNS 메트릭(coredns_dns_request_duration_seconds)을 Prometheus로 수집하여 DNS 지연 알림
- **사고 대응**: 장애 발생 시 tcpdump로 캡처한 pcap 파일을 근거로 RCA(Root Cause Analysis) 수행

### JD 연결 포인트

```
JD: "안정적 서비스 운영"   → 체계적 트러블슈팅 능력
JD: "모니터링/관측가능성" → curl -w 기반 외부 모니터링, Blackbox Exporter
JD: "Kubernetes"         → Pod/Service/CoreDNS 디버깅
JD: "복원력"              → 장애 원인 분석(RCA), 재발 방지
```

---

**핵심 키워드**: `tcpdump` `curl-timing` `dig` `traceroute` `mtr` `Wireshark` `netshoot` `conntrack` `CoreDNS-디버깅` `체계적-트러블슈팅`
