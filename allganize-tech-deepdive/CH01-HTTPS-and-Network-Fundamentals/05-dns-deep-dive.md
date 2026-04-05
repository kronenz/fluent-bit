# 05. DNS 심화 — Recursive/Iterative 쿼리, TTL, CoreDNS, ExternalDNS

> **TL;DR**
> - DNS는 **재귀(Recursive)** 리졸버가 **반복(Iterative)** 쿼리로 Root → TLD → Authoritative 네임서버를 순회하여 도메인을 IP로 변환한다.
> - **TTL(Time To Live)**은 DNS 캐시 유효 시간으로, 짧으면 빠른 변경이 가능하지만 쿼리 부하 증가, 길면 반대의 트레이드오프가 있다.
> - Kubernetes에서 **CoreDNS**가 클러스터 내부 DNS를 담당하고, **ExternalDNS**가 Ingress/Service를 외부 DNS(Route53 등)에 자동 등록한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### DNS 계층 구조

```
                        . (Root)
                       / | \
                      /  |  \
                   .com .net .kr   ← TLD (Top-Level Domain)
                   /       \
              google.com  allganize.ai
              /    \           \
          www   api          api.allganize.ai
                                    │
                              A Record: 52.78.xxx.xxx
```

### DNS 쿼리 과정 (Recursive + Iterative)

```
사용자                 Recursive          Root NS        .ai TLD NS    allganize.ai
(Stub Resolver)       Resolver           (13개)                        Auth NS
    │                    │                  │               │              │
    │─ "api.allganize.ai │                  │               │              │
    │   의 IP는?" ──────→│                  │               │              │
    │   (재귀 쿼리)       │                  │               │              │
    │                    │─ "allganize.ai   │               │              │
    │                    │   의 NS는?" ────→│               │              │
    │                    │   (반복 쿼리)     │               │              │
    │                    │←── ".ai NS:      │               │              │
    │                    │    ns1.nic.ai" ──│               │              │
    │                    │                  │               │              │
    │                    │─ "allganize.ai   │               │              │
    │                    │   의 NS는?" ─────────────────→  │              │
    │                    │←── "allganize.ai │               │              │
    │                    │    NS: ns-xxx.   │               │              │
    │                    │    awsdns-xx" ───────────────── │              │
    │                    │                  │               │              │
    │                    │─ "api.allganize. │               │              │
    │                    │   ai의 A?" ──────────────────────────────────→│
    │                    │←── "52.78.xxx.   │               │              │
    │                    │    xxx" ─────────────────────────────────────│
    │                    │                  │               │              │
    │←── "52.78.xxx.xxx" │                  │               │              │
    │   (+ TTL 캐시)     │                  │               │              │

Recursive Resolver: 클라이언트 대신 전체 과정을 수행 (ISP DNS, 8.8.8.8)
Iterative Query: Resolver가 각 NS에 "다음 단계를 알려줘"라고 물어봄
Stub Resolver: OS의 DNS 클라이언트 (/etc/resolv.conf)
```

### DNS 레코드 유형

| 레코드 | 용도 | 예시 |
|--------|------|------|
| **A** | 도메인 → IPv4 | api.allganize.ai → 52.78.1.1 |
| **AAAA** | 도메인 → IPv6 | api.allganize.ai → 2001:db8::1 |
| **CNAME** | 도메인 → 다른 도메인 (별칭) | www.allganize.ai → allganize.ai |
| **NS** | 네임서버 지정 | allganize.ai NS ns-xxx.awsdns-xx.com |
| **MX** | 메일 서버 | allganize.ai MX 10 mail.allganize.ai |
| **TXT** | 텍스트 정보 (SPF, DKIM 등) | allganize.ai TXT "v=spf1 ..." |
| **SRV** | 서비스 위치 (포트 포함) | _http._tcp.api SRV 0 5 8080 api.allganize.ai |
| **SOA** | 영역 권한 정보 | 시리얼, 갱신 간격, TTL 기본값 |
| **PTR** | IP → 도메인 (역방향) | 1.1.78.52.in-addr.arpa → api.allganize.ai |

### TTL 전략

```
TTL (Time To Live) = DNS 캐시 유효 시간 (초)

짧은 TTL (60~300초):
┌─────────────────────────────────────────┐
│ ✓ DNS 변경 사항 빠르게 반영              │
│ ✓ 장애 시 빠른 페일오버                  │
│ ✗ DNS 쿼리 증가 → 비용, 지연             │
│                                         │
│ 사용 시나리오:                            │
│ - 블루/그린 배포 전후                     │
│ - CDN 전환                               │
│ - 장애 대응 (DR)                         │
└─────────────────────────────────────────┘

긴 TTL (3600~86400초):
┌─────────────────────────────────────────┐
│ ✓ DNS 쿼리 감소 → 비용/지연 절약         │
│ ✓ DNS 인프라 장애에 강인                  │
│ ✗ DNS 변경 반영이 느림                    │
│                                         │
│ 사용 시나리오:                            │
│ - IP가 변경되지 않는 안정적 서비스         │
│ - CDN Origin                            │
└─────────────────────────────────────────┘

실전 전략:
  평상시: TTL 3600 (1시간)
  변경 예정 시:
    1. 먼저 TTL을 60초로 줄임
    2. 기존 TTL(3600초) 대기
    3. DNS 레코드 변경
    4. 변경 확인 후 TTL을 다시 3600으로 복원
```

### Kubernetes CoreDNS

```
┌──────────────────── Kubernetes Cluster ─────────────────────┐
│                                                              │
│  Pod A                         CoreDNS Pod                   │
│  ┌──────────────────┐         ┌──────────────────────────┐  │
│  │ /etc/resolv.conf  │         │ Corefile:                 │  │
│  │ nameserver        │         │   cluster.local {         │  │
│  │   10.96.0.10      │────────→│     kubernetes cluster.   │  │
│  │ search            │  DNS    │       local in-addr.arpa  │  │
│  │   default.svc.    │  Query  │     pods insecure         │  │
│  │   cluster.local   │         │     fallthrough           │  │
│  │   svc.cluster.    │         │   }                       │  │
│  │   local           │         │   . {                     │  │
│  │   cluster.local   │         │     forward . /etc/       │  │
│  └──────────────────┘         │       resolv.conf         │  │
│                                │     cache 30              │  │
│                                │   }                       │  │
│                                └──────────────────────────┘  │
│                                                              │
│  DNS 이름 해석 규칙:                                          │
│  서비스:  <svc>.<ns>.svc.cluster.local                       │
│  Pod:    <pod-ip-dashed>.<ns>.pod.cluster.local              │
│  Headless: <pod-name>.<svc>.<ns>.svc.cluster.local          │
└──────────────────────────────────────────────────────────────┘

search 도메인에 의한 이름 해석 순서 (default 네임스페이스 Pod 기준):
  "alli-api" 질의 시:
    1. alli-api.default.svc.cluster.local  ← 같은 NS Service
    2. alli-api.svc.cluster.local
    3. alli-api.cluster.local
    4. alli-api                             ← 외부 DNS로 forwarding
```

### CoreDNS ndots 문제

```
기본 /etc/resolv.conf (Pod):
  nameserver 10.96.0.10
  search default.svc.cluster.local svc.cluster.local cluster.local
  options ndots:5

ndots:5의 의미:
  호스트 이름에 점(.)이 5개 미만이면 search 도메인을 먼저 시도

예: "api.allganize.ai" 조회 시 (점 2개 < ndots 5):
  1. api.allganize.ai.default.svc.cluster.local  ← NXDOMAIN
  2. api.allganize.ai.svc.cluster.local           ← NXDOMAIN
  3. api.allganize.ai.cluster.local               ← NXDOMAIN
  4. api.allganize.ai                             ← 성공!

  → 불필요한 DNS 쿼리 3개 발생! (외부 도메인 접근 시 느려짐)

해결 방법:
  1. FQDN 사용: "api.allganize.ai." (끝에 점 추가)
  2. Pod spec에서 ndots 조정:
     spec:
       dnsConfig:
         options:
         - name: ndots
           value: "2"
```

### ExternalDNS

```
┌────── Kubernetes Cluster ──────┐          ┌──── Route53 ────┐
│                                 │          │                  │
│  Ingress:                       │          │  allganize.ai    │
│    host: api.allganize.ai       │          │  Zone            │
│    → Service: alli-api          │          │                  │
│                                 │          │  A api.allganize │
│  ExternalDNS Controller ────────│────────→│    .ai            │
│    * Ingress/Service 감시       │  Route53 │    52.78.xxx.xxx │
│    * DNS 레코드 자동 생성/삭제   │  API     │                  │
│    * 소유권 관리 (TXT 레코드)    │          │  TXT api.allgani│
│                                 │          │    ze.ai          │
└─────────────────────────────────┘          │    "heritage=    │
                                              │     external-dns"│
                                              └──────────────────┘
```

---

## 실전 예시

### DNS 디버깅 명령어

```bash
# dig — DNS 쿼리 상세 확인 (가장 권장)
dig api.allganize.ai
dig api.allganize.ai +trace           # 전체 해석 과정 추적
dig api.allganize.ai @8.8.8.8         # 특정 DNS 서버에 질의
dig api.allganize.ai +short           # IP만 출력
dig -t MX allganize.ai                # MX 레코드 조회
dig -t NS allganize.ai                # 네임서버 조회
dig -t ANY allganize.ai               # 모든 레코드 (일부 서버 거부)

# nslookup — 간단한 DNS 조회
nslookup api.allganize.ai
nslookup -type=CNAME www.allganize.ai
nslookup api.allganize.ai 8.8.8.8

# host — 간결한 출력
host api.allganize.ai
host -t MX allganize.ai

# DNS 캐시 확인 (systemd-resolved)
resolvectl query api.allganize.ai
resolvectl statistics

# DNS 전파 확인 (여러 DNS 서버에서)
for ns in 8.8.8.8 1.1.1.1 168.126.63.1; do
  echo "=== $ns ==="; dig @$ns api.allganize.ai +short
done
```

### CoreDNS 설정 및 디버깅

```yaml
# CoreDNS ConfigMap 커스터마이징
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        errors
        health {
            lameduck 5s
        }
        ready
        kubernetes cluster.local in-addr.arpa ip6.arpa {
            pods insecure
            fallthrough in-addr.arpa ip6.arpa
            ttl 30
        }
        prometheus :9153           # 메트릭 노출
        forward . /etc/resolv.conf {
            max_concurrent 1000
        }
        cache 30                   # 내부 캐시 30초
        loop                       # 루프 감지
        reload                     # 설정 변경 자동 리로드
        loadbalance                # 라운드 로빈
    }
    # 내부 도메인 커스텀 포워딩
    internal.allganize.ai:53 {
        forward . 10.0.0.53        # 내부 DNS 서버로 포워딩
        cache 60
    }
```

```bash
# CoreDNS Pod 상태 확인
kubectl get pods -n kube-system -l k8s-app=kube-dns

# CoreDNS 로그 확인
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=100

# 클러스터 내부에서 DNS 테스트
kubectl run dnsutils --image=tutum/dnsutils --rm -it --restart=Never -- \
  nslookup alli-api.production.svc.cluster.local

# CoreDNS 메트릭 확인
kubectl port-forward -n kube-system svc/kube-dns-metrics 9153:9153
curl http://localhost:9153/metrics | grep coredns_dns_request_count_total
```

### ExternalDNS 설정

```yaml
# ExternalDNS Deployment (AWS Route53)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: external-dns
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: external-dns
  template:
    metadata:
      labels:
        app: external-dns
    spec:
      serviceAccountName: external-dns    # IRSA로 Route53 권한
      containers:
      - name: external-dns
        image: registry.k8s.io/external-dns/external-dns:v0.14.0
        args:
        - --source=ingress
        - --source=service
        - --domain-filter=allganize.ai     # 이 도메인만 관리
        - --provider=aws
        - --aws-zone-type=public
        - --registry=txt
        - --txt-owner-id=alli-cluster-1    # 소유권 식별자
        - --policy=upsert-only             # 삭제 방지 (안전)
        - --interval=1m                     # 동기화 간격
---
# ExternalDNS가 관리할 Ingress 예시
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: alli-api
  annotations:
    external-dns.alpha.kubernetes.io/hostname: api.allganize.ai
    external-dns.alpha.kubernetes.io/ttl: "300"
spec:
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

---

## 면접 Q&A

### Q: DNS의 Recursive Query와 Iterative Query의 차이를 설명해주세요.

**30초 답변**:
**Recursive Query**는 클라이언트가 DNS 리졸버에게 "최종 답을 달라"고 요청하는 것이고, **Iterative Query**는 리졸버가 각 네임서버에 "다음 단계를 알려줘"라고 물어보는 것입니다. 일반적으로 클라이언트→리졸버는 Recursive, 리졸버→각 NS는 Iterative입니다.

**2분 답변**:
DNS 쿼리에는 두 가지 방식이 있습니다.

**Recursive Query**: 클라이언트(Stub Resolver)가 Recursive Resolver(보통 ISP DNS나 8.8.8.8)에게 "api.allganize.ai의 IP를 알려달라"고 요청합니다. Resolver는 최종 답을 찾을 때까지 **모든 과정을 대신 수행**합니다. 클라이언트는 기다리기만 하면 됩니다.

**Iterative Query**: Recursive Resolver가 최종 답을 찾기 위해 여러 네임서버를 **순서대로 조회**하는 방식입니다:
1. Root NS에 물어봄 → ".ai 담당은 TLD NS이다" (Referral)
2. TLD NS에 물어봄 → "allganize.ai 담당은 Authoritative NS이다" (Referral)
3. Authoritative NS에 물어봄 → "api.allganize.ai = 52.78.xxx.xxx" (Answer)

각 단계에서 NS는 직접 답을 주거나, 다음 단계를 알려줍니다(Referral). 이렇게 Resolver가 여러 번 왕복하는 것이 Iterative입니다.

**캐싱**이 중요한 이유: Resolver는 각 단계의 결과를 TTL 동안 캐시합니다. Root NS나 TLD NS 결과는 TTL이 길어서(수일) 실제로는 Authoritative NS에만 직접 쿼리하는 경우가 대부분입니다.

**경험 연결**:
"폐쇄망 환경에서 Unbound를 Recursive Resolver로 구축한 경험이 있습니다. 외부 DNS에 접근할 수 없는 환경이라 내부 Authoritative NS(BIND)와 Recursive Resolver(Unbound)를 분리하여 운영했습니다."

**주의**:
- "Recursive"는 재귀라는 단어 때문에 혼동하기 쉬운데, 실제로 Resolver가 재귀적으로 동작하는 것이 아니라 클라이언트 **대신** 전체 과정을 수행한다는 의미
- Root NS는 전 세계 13개 (a~m.root-servers.net)이지만, Anycast로 수백 개의 물리 서버가 분산

### Q: Kubernetes에서 DNS는 어떻게 동작하나요?

**30초 답변**:
Kubernetes는 **CoreDNS**를 클러스터 내부 DNS로 사용합니다. Pod의 `/etc/resolv.conf`에 CoreDNS의 ClusterIP가 등록되어, `<service>.<namespace>.svc.cluster.local` 형식으로 서비스를 검색합니다. 외부 도메인은 CoreDNS가 upstream DNS로 포워딩합니다.

**2분 답변**:
Kubernetes DNS는 세 가지 구성 요소로 동작합니다.

첫째, **CoreDNS**: kube-system 네임스페이스의 Deployment로 배포됩니다. Kubernetes API를 watch하여 Service/Pod 정보를 실시간으로 반영합니다.

둘째, **Pod의 resolv.conf**: kubelet이 Pod 생성 시 `/etc/resolv.conf`에 CoreDNS의 ClusterIP(보통 10.96.0.10)를 nameserver로, `<ns>.svc.cluster.local` 등을 search 도메인으로 설정합니다.

셋째, **이름 해석 규칙**:
- ClusterIP Service: `alli-api.production.svc.cluster.local` → ClusterIP
- Headless Service: 각 Pod의 IP를 직접 반환 (StatefulSet에서 중요)
- 같은 네임스페이스: `alli-api`만으로 접근 가능 (search 도메인 덕분)

주의할 점은 **ndots:5** 기본 설정입니다. 외부 도메인(api.openai.com 등) 조회 시 점이 5개 미만이면 search 도메인을 먼저 시도하여 불필요한 쿼리가 4개나 발생합니다. 외부 API 호출이 많은 서비스에서는 ndots를 2로 줄이거나 FQDN(끝에 점)을 사용하는 것이 좋습니다.

**경험 연결**:
"Kubernetes 클러스터에서 외부 API 호출 시 간헐적 지연이 발생한 적이 있는데, CoreDNS 로그를 확인하니 ndots:5로 인한 불필요한 DNS 쿼리가 원인이었습니다. ndots를 조정하여 해결한 경험이 있습니다."

**주의**:
- CoreDNS가 다운되면 클러스터 내부 서비스 디스커버리가 전부 중단 → CoreDNS는 최소 2개 Pod로 HA 구성
- Headless Service와 ClusterIP Service의 DNS 동작 차이를 명확히 알아야 함

### Q: ExternalDNS는 무엇이고 왜 필요한가요?

**30초 답변**:
ExternalDNS는 Kubernetes의 Ingress/Service 리소스를 감시하여 **외부 DNS(Route53, Cloud DNS 등)에 자동으로 레코드를 생성/삭제**하는 컨트롤러입니다. Ingress에 호스트를 설정하면 수동으로 DNS를 등록할 필요 없이 자동으로 반영됩니다.

**2분 답변**:
전통적으로 새 서비스를 배포하면 DNS 레코드를 수동으로 등록해야 합니다. Route53 콘솔에 접속하거나 Terraform으로 관리하는데, 이는 배포 파이프라인과 분리되어 있어 누락이나 지연이 발생합니다.

ExternalDNS는 이를 자동화합니다:
1. Kubernetes API를 watch하여 Ingress/Service 변경을 감지
2. 어노테이션이나 호스트 필드에서 도메인 이름 추출
3. 외부 DNS 프로바이더(Route53, Azure DNS, CloudFlare 등)에 API로 레코드 생성
4. 리소스 삭제 시 DNS 레코드도 자동 삭제

안전장치로 **TXT 레코드 기반 소유권 관리**를 합니다. ExternalDNS가 생성한 레코드에만 heritage TXT 레코드를 함께 생성하여, 수동으로 만든 레코드를 실수로 삭제하지 않습니다.

`--policy=upsert-only`로 설정하면 레코드 삭제를 방지할 수 있어 더 안전합니다.

**경험 연결**:
"DNS 레코드 수동 관리 시 배포 후 DNS 등록을 잊어서 서비스 접근이 안 되는 사례가 있었습니다. ExternalDNS를 도입하면 Ingress 생성만으로 DNS까지 자동 반영되어 이런 휴먼 에러를 방지할 수 있습니다."

**주의**:
- ExternalDNS에 과도한 DNS 권한을 부여하면 위험 → `--domain-filter`로 관리 도메인을 제한
- DNS 전파 시간(TTL)을 고려하여 배포 직후 바로 접근 가능하다고 가정하면 안 됨

---

## Allganize 맥락

### Alli 서비스와의 연결

- **서비스 디스커버리**: Alli 마이크로서비스 간 CoreDNS 기반 서비스 디스커버리 (Service 이름으로 통신)
- **외부 DNS 자동화**: ExternalDNS로 api.allganize.ai, dashboard.allganize.ai 등을 Ingress와 자동 동기화
- **멀티클라우드 DNS**: Route53(AWS) + Azure DNS에서 ExternalDNS를 각각 운영하거나, Route53으로 통합
- **DNS 기반 페일오버**: Route53 Health Check + Failover Routing으로 멀티리전/멀티클라우드 DR
- **ndots 최적화**: LLM 서비스가 외부 AI API(OpenAI 등)를 호출할 때 ndots로 인한 DNS 지연 방지
- **CoreDNS 모니터링**: Prometheus + coredns_dns_request_duration_seconds 메트릭으로 DNS 지연 모니터링

### JD 연결 포인트

```
JD: "안정적 서비스 운영"   → CoreDNS HA, DNS 모니터링
JD: "자동화"              → ExternalDNS 자동 DNS 관리
JD: "AWS/Azure"          → Route53/Azure DNS + ExternalDNS
JD: "복원력"              → DNS 기반 페일오버, TTL 전략
```

---

**핵심 키워드**: `Recursive-Query` `Iterative-Query` `TTL` `CoreDNS` `ExternalDNS` `ndots` `FQDN` `Route53` `서비스-디스커버리`
