# 02. TLS Handshake 심화 — TLS 1.2 vs 1.3, Cipher Suite, PFS

> **TL;DR**
> - TLS 1.2는 **2-RTT** 핸드셰이크, TLS 1.3은 **1-RTT**(재연결 시 0-RTT)로 지연을 절반으로 줄였다.
> - Cipher Suite는 **키 교환 + 인증 + 대칭 암호 + 해시** 4요소 조합이며, TLS 1.3에서 안전하지 않은 조합이 대거 제거되었다.
> - **PFS(Perfect Forward Secrecy)**는 서버 개인키가 유출되어도 과거 세션을 복호화할 수 없게 보장하는 핵심 속성이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### TLS 1.2 핸드셰이크 (2-RTT)

```
클라이언트                                        서버
    │                                              │
    │──── ClientHello ────────────────────────────→│  RTT 1
    │     (TLS 버전, Cipher Suites, Random,        │
    │      SNI, 지원 확장)                          │
    │                                              │
    │←─── ServerHello ────────────────────────────│
    │     (선택된 Cipher Suite, Random)             │
    │←─── Certificate ────────────────────────────│
    │     (서버 인증서 체인)                         │
    │←─── ServerKeyExchange ──────────────────────│
    │     (DHE/ECDHE 파라미터 + 서명)               │
    │←─── ServerHelloDone ────────────────────────│
    │                                              │
    │──── ClientKeyExchange ──────────────────────→│  RTT 2
    │     (클라이언트 DH 공개값)                     │
    │──── ChangeCipherSpec ───────────────────────→│
    │──── Finished (encrypted) ───────────────────→│
    │                                              │
    │←─── ChangeCipherSpec ───────────────────────│
    │←─── Finished (encrypted) ───────────────────│
    │                                              │
    │════ Application Data (encrypted) ═══════════│
```

**각 단계의 의미:**
1. **ClientHello**: 클라이언트가 지원하는 암호화 옵션을 서버에 제안
2. **ServerHello**: 서버가 가장 강력한 공통 옵션을 선택
3. **Certificate**: 서버가 자신의 인증서(공개키 포함)를 제시
4. **ServerKeyExchange**: ECDHE 파라미터 교환 (PFS를 위해)
5. **ClientKeyExchange**: 양측이 **Pre-Master Secret**을 독립적으로 계산
6. **Finished**: 핸드셰이크 무결성 검증 + 암호화 시작

### TLS 1.3 핸드셰이크 (1-RTT)

```
클라이언트                                        서버
    │                                              │
    │──── ClientHello ────────────────────────────→│  RTT 1
    │     (TLS 1.3, Cipher Suites, Random,         │
    │      key_share(ECDHE 공개값),                 │
    │      supported_groups, SNI)                   │
    │                                              │
    │←─── ServerHello ────────────────────────────│
    │     (선택된 Cipher Suite,                     │
    │      key_share(서버 ECDHE 공개값))             │
    │←─── {EncryptedExtensions} ──────────────────│  ← 이미 암호화됨!
    │←─── {Certificate} ──────────────────────────│
    │←─── {CertificateVerify} ────────────────────│
    │←─── {Finished} ─────────────────────────────│
    │                                              │
    │──── {Finished} ─────────────────────────────→│
    │                                              │
    │══════ Application Data (encrypted) ═════════│

    { } = 암호화된 메시지
```

**TLS 1.3이 빠른 이유:**
- ClientHello에 **key_share를 포함**하여 키 교환을 첫 메시지부터 시작
- 서버의 Certificate부터 이미 암호화 → **핸드셰이크 자체도 기밀성 확보**
- 불필요한 메시지(ChangeCipherSpec, ServerHelloDone) 제거

### 0-RTT 재연결 (TLS 1.3 PSK)

```
이전 세션                              재연결 시
┌──────────────┐                  클라이언트              서버
│ Session에서   │                      │                    │
│ PSK 저장      │──→               │── ClientHello ──────→│
└──────────────┘                      │   + early_data      │
                                      │   + PSK identity    │
                                      │   + key_share       │
                                      │   + Application Data│ ← 0-RTT!
                                      │                    │
                                      │←── ServerHello ───│
                                      │    + 나머지 핸드셰이크│
```

**0-RTT 주의사항:**
- **Replay Attack 위험**: 공격자가 0-RTT 데이터를 캡처 후 재전송 가능
- **멱등 요청에만 사용**: GET은 OK, POST(결제 등)는 위험
- 서버 측에서 anti-replay 메커니즘 구현 필요

### Cipher Suite 구조

```
TLS 1.2 Cipher Suite 예시:
TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
 │    │     │        │    │    │
 │    │     │        │    │    └─ MAC/PRF 해시: SHA-384
 │    │     │        │    └────── 운영 모드: GCM (AEAD)
 │    │     │        └─────────── 대칭 암호: AES-256
 │    │     └──────────────────── 인증: RSA 서명
 │    └────────────────────────── 키 교환: ECDHE (PFS)
 └─────────────────────────────── 프로토콜: TLS

TLS 1.3 Cipher Suite 예시 (간소화됨):
TLS_AES_256_GCM_SHA384
 │    │    │    │
 │    │    │    └─ 해시: SHA-384
 │    │    └────── 운영 모드: GCM
 │    └─────────── 대칭 암호: AES-256
 └──────────────── 프로토콜: TLS

 * TLS 1.3에서 키 교환은 항상 (EC)DHE, 인증은 별도 설정
 * RSA 키 교환, CBC 모드, RC4, 3DES, MD5, SHA-1 모두 제거됨
```

### TLS 1.3에서 허용되는 Cipher Suite (단 5개)

| Cipher Suite | 대칭 암호 | 해시 | 비고 |
|---|---|---|---|
| TLS_AES_128_GCM_SHA256 | AES-128-GCM | SHA-256 | 가장 보편적 |
| TLS_AES_256_GCM_SHA384 | AES-256-GCM | SHA-384 | 높은 보안 |
| TLS_CHACHA20_POLY1305_SHA256 | ChaCha20-Poly1305 | SHA-256 | 모바일 최적화 |
| TLS_AES_128_CCM_SHA256 | AES-128-CCM | SHA-256 | IoT 환경 |
| TLS_AES_128_CCM_8_SHA256 | AES-128-CCM-8 | SHA-256 | IoT 경량 |

### PFS (Perfect Forward Secrecy)

```
PFS 없는 경우 (RSA 키 교환):
┌──────────────────────────────────────────────────────────┐
│ 1. 클라이언트가 Pre-Master Secret을 서버 공개키로 암호화  │
│ 2. 서버가 개인키로 복호화                                 │
│ 3. 양측이 동일한 세션 키 생성                              │
│                                                          │
│ ⚠ 서버 개인키 유출 시 → 과거 모든 세션 복호화 가능!       │
└──────────────────────────────────────────────────────────┘

PFS 있는 경우 (ECDHE 키 교환):
┌──────────────────────────────────────────────────────────┐
│ 1. 양측이 임시(Ephemeral) DH 키 쌍을 매 세션 생성        │
│ 2. 공개값 교환 → 각자 동일한 세션 키 계산                  │
│ 3. 임시 개인키는 세션 종료 후 폐기                         │
│                                                          │
│ ✓ 서버 개인키 유출되어도 과거 세션 복호화 불가!            │
│   (서버 개인키는 인증용으로만 사용)                        │
└──────────────────────────────────────────────────────────┘

ECDHE 키 교환 과정:
 클라이언트                              서버
 a = random (임시 개인키)               b = random (임시 개인키)
 A = a * G  (임시 공개키)               B = b * G  (임시 공개키)
     │                                     │
     │────── A (공개값) ──────────────→    │
     │←───── B (공개값) ──────────────     │
     │                                     │
 Shared = a * B                    Shared = b * A
        = a * b * G                       = b * a * G
        (동일!)                            (동일!)
```

### TLS 1.2 vs 1.3 비교

| 항목 | TLS 1.2 | TLS 1.3 |
|------|---------|---------|
| 핸드셰이크 | 2-RTT | 1-RTT (0-RTT 재연결) |
| 키 교환 | RSA, DHE, ECDHE | ECDHE, DHE만 허용 |
| PFS | 선택 (ECDHE 선택 시) | **필수** (항상 PFS) |
| Cipher Suite 수 | 수백 개 | 5개 |
| 핸드셰이크 암호화 | 없음 (평문) | ServerHello 이후 암호화 |
| 취약한 알고리즘 | RC4, 3DES, CBC 등 허용 | 모두 제거 |
| 압축 | 지원 (CRIME 공격 원인) | 제거 |
| Renegotiation | 지원 | 제거 (PSK로 대체) |

---

## 실전 예시

### TLS 버전 및 Cipher Suite 확인

```bash
# 서버의 TLS 버전 확인
openssl s_client -connect api.example.com:443 -tls1_3 2>/dev/null | \
  grep -E "Protocol|Cipher"
# Protocol  : TLSv1.3
# Cipher    : TLS_AES_256_GCM_SHA384

# 지원하는 모든 Cipher Suite 나열
nmap --script ssl-enum-ciphers -p 443 api.example.com

# curl로 TLS 상세 정보 확인
curl -vvv https://api.example.com 2>&1 | grep -E "TLS|SSL|cipher"

# 특정 Cipher Suite로 연결 테스트
openssl s_client -connect api.example.com:443 \
  -cipher ECDHE-RSA-AES256-GCM-SHA384

# 인증서 만료일 확인
echo | openssl s_client -connect api.example.com:443 2>/dev/null | \
  openssl x509 -noout -dates
```

### nginx TLS 최적화 설정

```nginx
server {
    listen 443 ssl http2;
    server_name api.allganize.ai;

    # 인증서
    ssl_certificate     /etc/ssl/certs/fullchain.pem;
    ssl_certificate_key /etc/ssl/private/privkey.pem;

    # TLS 버전 — 1.2 이상만 허용
    ssl_protocols TLSv1.2 TLSv1.3;

    # Cipher Suite — PFS 보장, 강력한 순서
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
    ssl_prefer_server_ciphers on;    # 서버가 Cipher 순서 결정

    # TLS 세션 재사용 (성능 최적화)
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;          # PFS를 위해 비활성화 권장

    # OCSP Stapling (인증서 유효성 확인 최적화)
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/ssl/certs/chain.pem;
    resolver 8.8.8.8 8.8.4.4 valid=300s;

    # HSTS (HTTP → HTTPS 강제)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
}
```

### Kubernetes cert-manager TLS 설정

```yaml
# ClusterIssuer — Let's Encrypt
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: devops@allganize.ai
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: nginx
---
# Certificate 요청
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
  namespace: production
spec:
  secretName: api-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - api.allganize.ai
  - "*.allganize.ai"
  renewBefore: 360h    # 만료 15일 전 자동 갱신
```

### TLS 디버깅

```bash
# TLS 핸드셰이크 전체 과정 확인
openssl s_client -connect api.example.com:443 -msg -debug 2>&1 | head -100

# 인증서 체인 확인
openssl s_client -connect api.example.com:443 -showcerts 2>/dev/null

# TLS 1.3 0-RTT 지원 여부 확인
openssl s_client -connect api.example.com:443 -tls1_3 -sess_out /tmp/session.pem
openssl s_client -connect api.example.com:443 -tls1_3 -sess_in /tmp/session.pem -early_data /tmp/request.txt

# tcpdump로 TLS 핸드셰이크 패킷 캡처
sudo tcpdump -i eth0 -w /tmp/tls.pcap 'tcp port 443' -c 50
# Wireshark에서 열어 ClientHello, ServerHello 분석
```

---

## 면접 Q&A

### Q: TLS 1.2와 1.3의 핸드셰이크 차이를 설명해주세요.

**30초 답변**:
TLS 1.2는 2-RTT, TLS 1.3은 1-RTT입니다. 핵심 차이는 TLS 1.3에서 ClientHello에 **key_share(ECDHE 공개값)**를 포함시켜 키 교환을 첫 메시지부터 시작하고, 서버 응답부터 암호화가 적용됩니다. 또한 안전하지 않은 알고리즘이 모두 제거되어 Cipher Suite가 5개로 줄었습니다.

**2분 답변**:
TLS 1.2에서는 ClientHello로 지원 암호를 제안하고, 서버가 선택한 후 Certificate와 ServerKeyExchange를 보내고, 클라이언트가 ClientKeyExchange로 응답하는 **2-RTT** 과정을 거칩니다.

TLS 1.3은 이를 **1-RTT**로 줄였습니다. 핵심은 ClientHello에 `key_share` 확장을 포함시키는 것입니다. 클라이언트가 ECDHE 공개값을 미리 보내므로, 서버는 ServerHello와 함께 바로 키를 계산하고 그 이후 메시지(Certificate, CertificateVerify, Finished)를 **암호화하여** 보냅니다.

이는 두 가지 이점이 있습니다. 첫째, 속도 — 핸드셰이크가 1-RTT로 줄어 연결 수립 지연이 절반. 둘째, 보안 — 핸드셰이크 자체가 암호화되어 서버 인증서 정보가 네트워크에 노출되지 않습니다.

또한 TLS 1.3은 RSA 키 교환, CBC 모드, RC4, 3DES 등 취약한 알고리즘을 모두 제거하여 **잘못된 설정의 가능성 자체를 차단**했습니다. PFS가 필수이므로 모든 연결에서 임시 키를 사용합니다.

이전 세션이 있는 경우 PSK(Pre-Shared Key)로 **0-RTT** 재연결이 가능하지만, Replay Attack 위험이 있어 멱등 요청에만 사용해야 합니다.

**경험 연결**:
"폐쇄망 환경에서 내부 서비스 간 TLS를 구축할 때, 초기에 TLS 1.0/1.1을 허용했다가 보안 감사에서 지적을 받았습니다. 이후 TLS 1.2 이상만 허용하고 ECDHE 기반 Cipher Suite만 남기는 정책을 적용했습니다. TLS 1.3 전환 시에는 Cipher Suite 설정이 대폭 간소화되어 관리 부담이 줄었습니다."

**주의**:
- TLS 1.3의 ServerHello가 TLS 1.2처럼 보이도록 위장하는 **Middlebox Compatibility Mode**를 알아두면 좋음 (기업 방화벽 호환성)
- 0-RTT의 Replay Attack 위험을 반드시 언급해야 함

### Q: PFS(Perfect Forward Secrecy)란 무엇이고 왜 중요한가요?

**30초 답변**:
PFS는 서버의 장기 개인키가 유출되어도 **과거 세션의 암호화된 통신을 복호화할 수 없는** 속성입니다. 매 세션마다 임시(Ephemeral) 키를 생성하고 세션 종료 후 폐기하기 때문입니다. ECDHE 키 교환이 이를 제공하며, TLS 1.3에서는 PFS가 필수입니다.

**2분 답변**:
RSA 키 교환 방식에서는 클라이언트가 Pre-Master Secret을 서버 공개키로 암호화하여 전송합니다. 공격자가 과거의 모든 암호화 트래픽을 저장해두었다면, 나중에 서버 개인키를 확보하는 순간 **모든 과거 세션**을 복호화할 수 있습니다. 이것이 "harvest now, decrypt later" 공격입니다.

PFS는 이를 방지합니다. ECDHE 키 교환에서는 매 세션마다 양측이 **임시 키 쌍**을 생성합니다. 이 임시 키로 세션 키를 계산한 후, 임시 개인키는 즉시 폐기됩니다. 서버의 장기 개인키는 **인증 서명에만** 사용됩니다.

따라서 서버 개인키가 유출되어도 공격자가 할 수 있는 것은 향후 서버를 사칭하는 것뿐이며, 이미 기록된 과거 트래픽은 복호화할 수 없습니다.

TLS 1.3에서는 RSA 키 교환이 제거되어 **PFS가 강제**됩니다. 이는 국가 수준의 대규모 감청 프로그램에 대한 방어 측면에서도 의미가 큽니다.

**경험 연결**:
"내부 서비스 간 TLS 설정 시 RSA 키 교환을 기본으로 사용하고 있었는데, 보안 감사에서 PFS 미적용 지적을 받았습니다. ECDHE 기반 Cipher Suite로 전환하고 ssl_prefer_server_ciphers를 설정하여 PFS를 보장한 경험이 있습니다."

**주의**:
- PFS의 "Perfect"은 수학적 의미가 아니라 "Forward Secrecy"를 강조하는 표현
- ssl_session_tickets를 활성화하면 PFS가 약화될 수 있음 (티켓 키 관리 필요)

### Q: Cipher Suite 선택 시 고려사항은 무엇인가요?

**30초 답변**:
**보안성**(취약 알고리즘 제외), **PFS 보장**(ECDHE), **성능**(AES-GCM은 AES-NI 하드웨어 가속, ChaCha20은 모바일에 유리), **호환성**(구형 클라이언트 지원 범위)을 균형 있게 고려해야 합니다. TLS 1.3에서는 5개만 허용되어 선택이 단순합니다.

**2분 답변**:
TLS 1.2 환경에서 Cipher Suite 선택은 네 가지를 고려합니다.

첫째, **키 교환**: ECDHE를 최우선으로 사용하여 PFS를 보장합니다. RSA 키 교환은 PFS가 없으므로 피합니다.

둘째, **대칭 암호**: AES-GCM이 표준입니다. AES-NI가 있는 서버(대부분의 현대 CPU)에서 하드웨어 가속을 받습니다. AES-NI가 없는 환경(일부 ARM)에서는 ChaCha20-Poly1305가 더 빠릅니다.

셋째, **해시 알고리즘**: SHA-256 이상을 사용합니다. SHA-1, MD5는 충돌 공격에 취약하여 절대 사용하면 안 됩니다.

넷째, **호환성**: 구형 클라이언트를 지원해야 한다면 TLS 1.2 Cipher Suite를 일부 유지하되, `ssl_prefer_server_ciphers on`으로 서버가 강력한 Cipher를 우선 선택하도록 합니다.

TLS 1.3 환경에서는 5개의 Cipher Suite만 허용되므로, 사실상 AES-256-GCM-SHA384 또는 AES-128-GCM-SHA256를 기본으로 사용하면 됩니다.

**경험 연결**:
"내부 보안 정책에 따라 Cipher Suite 화이트리스트를 관리한 경험이 있습니다. 취약점 스캐너(nmap ssl-enum-ciphers)로 정기적으로 점검하고, 취약한 Cipher가 발견되면 nginx 설정을 업데이트하는 프로세스를 운영했습니다."

**주의**:
- CBC 모드는 패딩 오라클 공격에 취약 (POODLE, Lucky13) → GCM이나 ChaCha20 사용
- ECDHE-ECDSA가 ECDHE-RSA보다 빠르지만, ECDSA 인증서가 필요

---

## Allganize 맥락

### Alli 서비스와의 연결

- **API 게이트웨이 TLS 종단**: ALB 또는 nginx Ingress Controller에서 TLS를 종단(terminate)하고, 내부 통신은 mTLS 또는 평문(Service Mesh 내부)으로 처리
- **인증서 자동화**: cert-manager + Let's Encrypt로 TLS 인증서 자동 발급/갱신, 수동 관리 제거
- **보안 컴플라이언스**: AI 서비스는 고객 데이터를 처리하므로 TLS 1.2 이상, PFS 필수 등의 보안 기준 충족 필요
- **성능 최적화**: LLM 추론 API의 첫 바이트 지연(TTFB)에 TLS 핸드셰이크 시간이 직접 영향 → TLS 1.3 + 세션 재사용으로 최소화
- **멀티클라우드 간 통신**: AWS↔Azure 간 VPN 없이 퍼블릭 통신 시 TLS 1.3 필수

### JD 연결 포인트

```
JD: "보안 정책"     → TLS 버전/Cipher Suite 관리, PFS 보장
JD: "안정적 운영"   → cert-manager 자동 갱신, TLS 설정 자동화
JD: "AWS/Azure"    → ALB/AGW의 TLS 정책 설정, 멀티클라우드 TLS 통신
```

---

**핵심 키워드**: `TLS-1.3` `1-RTT` `0-RTT` `ECDHE` `PFS` `Cipher-Suite` `HSTS` `cert-manager` `AEAD`
