# CoreDNS 설정과 트러블슈팅 (CoreDNS)

> **TL;DR**: CoreDNS는 Kubernetes 클러스터의 DNS 서버로, Service와 Pod의 이름을 IP로 해석한다. Corefile로 플러그인 체인을 구성하며, stub domain과 custom domain 설정으로 외부 DNS와 통합한다. DNS 장애는 전체 서비스 통신에 영향을 미치므로 빠른 진단 능력이 필수다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 20min

---

## 핵심 개념

### CoreDNS의 역할

```
┌──────────────────────────────────────────────────────┐
│  Kubernetes DNS 해석 흐름                              │
│                                                        │
│  Pod (app)                                             │
│    │ DNS query: alli-api.alli-prod.svc.cluster.local  │
│    │                                                   │
│    ▼ /etc/resolv.conf                                 │
│    nameserver 10.96.0.10  ← CoreDNS Service ClusterIP│
│    search alli-prod.svc.cluster.local                 │
│           svc.cluster.local                           │
│           cluster.local                               │
│    ndots: 5                                            │
│    │                                                   │
│    ▼ CoreDNS Pod (kube-system)                        │
│    │                                                   │
│    ├─ cluster.local zone → K8s API 조회              │
│    │   Service: alli-api → 10.96.45.12               │
│    │   Pod: 10-244-1-10 → 10.244.1.10               │
│    │                                                   │
│    ├─ 외부 도메인 → upstream DNS (forward .)          │
│    │   google.com → 8.8.8.8                          │
│    │                                                   │
│    └─ stub domain → 커스텀 DNS 서버                   │
│        corp.internal → 10.0.0.53                      │
└──────────────────────────────────────────────────────┘
```

### Kubernetes DNS 레코드 형식

| 리소스 | DNS 형식 | 예시 |
|--------|---------|------|
| **Service (ClusterIP)** | `<svc>.<ns>.svc.cluster.local` | `alli-api.alli-prod.svc.cluster.local` → 10.96.45.12 |
| **Service (Headless)** | `<svc>.<ns>.svc.cluster.local` | → 모든 Pod IP (A 레코드 여러 개) |
| **StatefulSet Pod** | `<pod>.<svc>.<ns>.svc.cluster.local` | `alli-db-0.alli-db-headless.alli-prod.svc.cluster.local` |
| **Pod (IP 기반)** | `<ip-dashed>.<ns>.pod.cluster.local` | `10-244-1-10.alli-prod.pod.cluster.local` |
| **SRV 레코드** | `_<port>._<proto>.<svc>.<ns>.svc.cluster.local` | `_http._tcp.alli-api.alli-prod.svc.cluster.local` |

### Corefile 구조

CoreDNS는 Corefile로 설정하며, ConfigMap `coredns`(kube-system namespace)에 저장된다.

```
# Corefile 기본 구조
.:53 {                          # 모든 도메인, 53 포트
    errors                      # 에러 로그
    health {                    # /health 헬스체크
        lameduck 5s
    }
    ready                       # /ready readiness 체크
    kubernetes cluster.local in-addr.arpa ip6.arpa {
        pods insecure           # Pod DNS 레코드 활성화
        fallthrough in-addr.arpa ip6.arpa
        ttl 30                  # 캐시 TTL 30초
    }
    prometheus :9153            # 메트릭 노출
    forward . /etc/resolv.conf {  # 외부 DNS forward
        max_concurrent 1000
    }
    cache 30                    # 응답 캐시 30초
    loop                        # 루프 감지
    reload                      # Corefile 변경 시 자동 리로드
    loadbalance                 # A 레코드 round-robin
}
```

### ndots 옵션과 DNS 질의 최적화

Pod의 `/etc/resolv.conf`에 `ndots: 5`가 기본 설정된다. 이는 쿼리 이름에 점(.)이 5개 미만이면 search domain을 먼저 시도한다는 의미이다.

```
ndots: 5 일 때 "api.openai.com" 조회 과정:
  점이 2개 (< 5) → search domain 먼저 시도

  1. api.openai.com.alli-prod.svc.cluster.local   → NXDOMAIN
  2. api.openai.com.svc.cluster.local             → NXDOMAIN
  3. api.openai.com.cluster.local                  → NXDOMAIN
  4. api.openai.com.                               → 성공!

  → 외부 도메인 하나 조회에 DNS 쿼리 4회 발생!
```

**최적화 방법**:

```yaml
# 방법 1: Pod의 dnsConfig로 ndots 조정
apiVersion: v1
kind: Pod
spec:
  dnsConfig:
    options:
      - name: ndots
        value: "2"     # 점이 2개 미만일 때만 search domain 시도

# 방법 2: FQDN 사용 (마지막에 점 추가)
# 코드에서 "api.openai.com." 으로 호출 → search domain 무시

# 방법 3: CoreDNS autopath 플러그인
# Corefile에 autopath 추가 → 서버 사이드에서 search 최적화
```

### Stub Domain과 Custom Domain 설정

```yaml
# ConfigMap: coredns (kube-system)
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
        prometheus :9153
        forward . /etc/resolv.conf
        cache 30
        loop
        reload
        loadbalance
    }
    # Stub domain: corp.internal → 사내 DNS 서버로 포워드
    corp.internal:53 {
        errors
        cache 30
        forward . 10.0.0.53 10.0.0.54 {
            max_concurrent 500
        }
    }
    # Custom domain: 특정 외부 도메인을 다른 DNS로 해석
    allganize.ai:53 {
        errors
        cache 60
        forward . 8.8.8.8 8.8.4.4
    }
```

```
┌──────────────────────────────────────────────┐
│  DNS 라우팅 맵                                │
│                                               │
│  Query Domain           Forward To            │
│  ─────────────────────────────────────────    │
│  *.cluster.local    →  Kubernetes API         │
│  *.corp.internal    →  10.0.0.53 (사내 DNS)   │
│  *.allganize.ai     →  8.8.8.8 (Google DNS)  │
│  기타 모든 도메인    →  /etc/resolv.conf       │
│                        (Node의 DNS 설정)      │
└──────────────────────────────────────────────┘
```

### CoreDNS 고가용성

```
┌──────────────────────────────────────────────────┐
│  CoreDNS HA 구성                                   │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ← Deployment         │
│  │ CoreDNS  │  │ CoreDNS  │     replicas: 2+      │
│  │ Pod A    │  │ Pod B    │                        │
│  │ (Node 1) │  │ (Node 2) │  ← PDB: minAvailable 1│
│  └────┬─────┘  └────┬─────┘                        │
│       │              │                              │
│       └──────┬───────┘                              │
│              ▼                                      │
│     Service: kube-dns                               │
│     ClusterIP: 10.96.0.10                          │
│                                                    │
│  Node DNS Cache (선택적):                           │
│  ┌──────────┐  ┌──────────┐  ← DaemonSet          │
│  │ NodeLocal│  │ NodeLocal│     (node-local-dns)   │
│  │ DNSCache │  │ DNSCache │                        │
│  │ (Node 1) │  │ (Node 2) │  ← 169.254.20.10      │
│  └──────────┘  └──────────┘                        │
└──────────────────────────────────────────────────┘
```

**NodeLocal DNSCache**는 각 Node에 DNS 캐시를 두어 CoreDNS Pod로의 네트워크 hop을 줄이고, 캐시 히트율을 높인다.

---

## 실전 예시

### CoreDNS 상태 확인

```bash
# CoreDNS Pod 상태
kubectl get pods -n kube-system -l k8s-app=kube-dns

# CoreDNS 로그 확인 (DNS 질의 실패 원인)
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=100

# Corefile 확인
kubectl get configmap coredns -n kube-system -o yaml

# CoreDNS 메트릭 확인
kubectl port-forward -n kube-system svc/kube-dns 9153:9153
curl http://localhost:9153/metrics | grep coredns_dns_requests_total
```

### DNS 트러블슈팅

```bash
# 1. 기본 DNS 해석 테스트
kubectl run dnsutils --image=gcr.io/kubernetes-e2e-test-images/dnsutils:1.3 --rm -it -- bash

# Pod 내부에서:
nslookup kubernetes.default.svc.cluster.local
nslookup alli-api.alli-prod.svc.cluster.local
nslookup google.com

# 2. DNS 응답 시간 측정
dig @10.96.0.10 alli-api.alli-prod.svc.cluster.local +stats

# 3. resolv.conf 확인
cat /etc/resolv.conf

# 4. DNS 쿼리 상세 (쿼리 체인 확인)
dig +trace +ndots=5 api.openai.com

# 5. CoreDNS에 직접 쿼리
kubectl exec -n kube-system coredns-xxxxx -- dig @127.0.0.1 alli-api.alli-prod.svc.cluster.local

# 6. CoreDNS 로그에서 에러 확인
kubectl logs -n kube-system -l k8s-app=kube-dns | grep -E "SERVFAIL|REFUSED|ERROR"
```

### DNS 관련 일반적인 문제와 해결

```bash
# 문제 1: DNS timeout (5초 대기 후 실패)
# 원인: CoreDNS Pod가 비정상이거나 NetworkPolicy로 차단
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl describe pod -n kube-system -l k8s-app=kube-dns
# → NetworkPolicy에서 kube-dns Egress 허용 확인

# 문제 2: 외부 도메인 해석 실패
# 원인: forward 설정의 upstream DNS 접근 불가
kubectl exec -n kube-system coredns-xxxxx -- nslookup google.com 8.8.8.8
# → Node에서 외부 DNS 접근 가능한지 확인

# 문제 3: NXDOMAIN (존재하는 Service인데 찾을 수 없음)
# 원인: Namespace 또는 Service 이름 오타, 다른 Namespace
kubectl get svc -A | grep alli-api
# → FQDN으로 정확하게 테스트

# 문제 4: 느린 DNS 해석 (외부 도메인)
# 원인: ndots:5로 인한 불필요한 search domain 시도
# 해결: ndots 조정 또는 FQDN 사용
kubectl exec debug-pod -- time nslookup api.openai.com
kubectl exec debug-pod -- time nslookup api.openai.com.  # FQDN (끝에 점)
```

### Corefile 커스텀 설정

```bash
# Corefile 수정 (ConfigMap 편집)
kubectl edit configmap coredns -n kube-system

# 변경 적용 확인 (CoreDNS가 자동 reload)
kubectl logs -n kube-system -l k8s-app=kube-dns | grep "Reloading"

# CoreDNS 재시작 (설정 변경이 반영 안 될 때)
kubectl rollout restart deployment coredns -n kube-system
```

---

## 면접 Q&A

### Q: Kubernetes에서 Service DNS 해석 과정을 설명해주세요.
**30초 답변**:
Pod가 `alli-api`를 호출하면, `/etc/resolv.conf`의 search domain을 추가하여 `alli-api.alli-prod.svc.cluster.local`로 변환합니다. 이 쿼리가 CoreDNS(10.96.0.10)로 전달되고, CoreDNS의 kubernetes 플러그인이 API Server에서 Service IP를 조회하여 반환합니다.

**2분 답변**:
전체 DNS 해석 과정은 다음과 같습니다.

Pod의 `/etc/resolv.conf`에는 `nameserver 10.96.0.10`(CoreDNS Service ClusterIP), `search <ns>.svc.cluster.local svc.cluster.local cluster.local`, `ndots:5`가 설정됩니다.

앱에서 `alli-api`를 조회하면, 점이 0개(< ndots:5)이므로 search domain을 순서대로 시도합니다. 첫 번째로 `alli-api.alli-prod.svc.cluster.local`을 CoreDNS에 질의합니다.

CoreDNS는 Corefile의 `kubernetes cluster.local` 블록에 의해 이 도메인을 처리합니다. Kubernetes API Server에 Service 정보를 조회하여 ClusterIP(예: 10.96.45.12)를 A 레코드로 반환합니다.

Headless Service인 경우 모든 Pod IP가 A 레코드로 반환됩니다. StatefulSet Pod는 `pod-name.svc-name.ns.svc.cluster.local` 형태의 개별 A 레코드를 가집니다.

외부 도메인(google.com 등)은 kubernetes 플러그인에서 매칭되지 않아 `forward . /etc/resolv.conf`로 Node의 upstream DNS에 전달됩니다.

**경험 연결**:
온프레미스에서 내부 DNS(BIND)를 운영하며 zone 설정, forwarder 설정을 직접 관리한 경험이 있습니다. CoreDNS의 Corefile은 zone 기반 라우팅의 단순화된 버전이며, kubernetes 플러그인이 zone 데이터를 API Server에서 자동으로 가져온다는 점이 차이입니다.

**주의**:
같은 Namespace의 Service는 짧은 이름(`alli-api`)으로 접근 가능하지만, 다른 Namespace의 Service는 `alli-api.other-ns` 또는 FQDN을 사용해야 한다.

### Q: ndots:5 설정이 성능에 미치는 영향과 최적화 방법은?
**30초 답변**:
ndots:5는 점이 5개 미만인 도메인에 대해 search domain을 먼저 시도합니다. 외부 도메인 `api.openai.com`(점 2개)을 조회하면 실패 쿼리 3회 + 성공 쿼리 1회로 총 4회 DNS 질의가 발생합니다. ndots:2로 낮추거나, FQDN(끝에 점)을 사용하거나, NodeLocal DNSCache를 도입하여 최적화합니다.

**2분 답변**:
Kubernetes는 Service 이름만으로 DNS 해석이 가능하도록 ndots:5와 search domain을 설정합니다. `alli-api`(점 0개)를 조회하면 search domain이 추가되어 `alli-api.alli-prod.svc.cluster.local`로 자동 변환됩니다.

문제는 외부 도메인입니다. `api.openai.com`(점 2개)도 search domain이 먼저 시도되어 3번의 불필요한 NXDOMAIN 응답이 발생합니다. AI 서비스처럼 외부 API를 빈번히 호출하는 경우 DNS 쿼리 수가 4배가 되어 CoreDNS 부하와 응답 지연이 증가합니다.

최적화 방법은 세 가지입니다. 첫째, `dnsConfig.options`로 ndots를 2로 낮춥니다. 대부분의 내부 Service 이름에는 점이 없으므로 정상 동작합니다. 둘째, 외부 도메인 호출 시 FQDN(`api.openai.com.`)을 사용하면 search domain을 건너뜁니다. 셋째, NodeLocal DNSCache를 도입하면 Node 로컬에서 NXDOMAIN이 캐싱되어 CoreDNS 부하를 줄입니다.

**경험 연결**:
DNS 서버 운영 시 쿼리 볼륨이 갑자기 증가하는 문제를 경험한 적이 있습니다. 원인이 resolver의 search domain 설정이었는데, Kubernetes의 ndots 문제와 동일한 패턴입니다. DNS는 모든 통신의 시작점이므로 성능 최적화가 전체 시스템에 큰 영향을 미칩니다.

**주의**:
ndots를 너무 낮추면 내부 Service 이름 해석에 문제가 생길 수 있다. 예를 들어 `my.service.name`(점 2개)이라는 Service가 있고 ndots:2이면, search domain이 시도되지 않아 FQDN으로만 접근 가능해진다.

### Q: CoreDNS의 stub domain 설정은 어떤 상황에서 사용하나요?
**30초 답변**:
Stub domain은 특정 도메인의 DNS 질의를 지정된 DNS 서버로 포워드하는 설정입니다. 사내 도메인(`corp.internal`)을 사내 DNS 서버로, 파트너 도메인을 파트너 DNS로 라우팅할 때 사용합니다. Corefile에 별도 server block으로 설정하며, split-horizon DNS나 하이브리드 클라우드 환경에서 필수적입니다.

**2분 답변**:
Stub domain은 세 가지 시나리오에서 사용됩니다.

첫째, 사내(on-premise) DNS 통합입니다. 하이브리드 클라우드에서 온프레미스의 `corp.internal` 도메인을 사내 DNS 서버(10.0.0.53)로 포워드합니다. Kubernetes Pod에서 사내 시스템에 도메인 이름으로 접근할 수 있습니다.

둘째, 멀티클라우드 DNS 통합입니다. AWS와 Azure에 걸친 서비스에서 각 클라우드의 private DNS zone을 해당 클라우드의 DNS 서버로 포워드합니다.

셋째, 외부 서비스 DNS 오버라이드입니다. 특정 도메인을 다른 DNS 서버로 해석하거나, CoreDNS의 rewrite 플러그인으로 도메인을 변환할 수 있습니다.

설정은 CoreDNS ConfigMap의 Corefile에 별도 server block을 추가합니다. `corp.internal:53 { forward . 10.0.0.53 }` 형태로, 해당 도메인만 지정 DNS로 포워드하고 나머지는 기본 설정을 따릅니다.

**경험 연결**:
폐쇄망에서 내부 DNS 서버에 여러 zone을 설정하고, 외부 도메인은 proxy를 통해 포워드했던 경험이 있습니다. CoreDNS의 stub domain은 동일한 split-horizon DNS 개념이며, 하이브리드 클라우드 전환 시 기존 DNS 체계를 유지하면서 Kubernetes를 통합하는 데 필수적입니다.

**주의**:
Stub domain DNS 서버에 접근하려면 CoreDNS Pod에서 해당 서버로의 네트워크가 열려 있어야 한다. VPN 또는 VPC Peering을 통한 연결이 필요하며, NetworkPolicy에서 CoreDNS의 Egress를 허용해야 한다.

---

## Allganize 맥락

- **서비스 디스커버리**: 마이크로서비스 간 통신은 Service DNS 이름으로. Headless Service로 StatefulSet(MongoDB, ES) 개별 Pod 접근
- **외부 API DNS 최적화**: LLM API(OpenAI, Anthropic) 호출 시 ndots:5로 인한 불필요한 DNS 쿼리 최소화. 추론 엔진 Pod에 ndots:2 설정 권장
- **NodeLocal DNSCache 도입**: 대규모 AI 워크로드에서 DNS 쿼리 볼륨이 높으므로 NodeLocal DNSCache로 CoreDNS 부하 분산
- **하이브리드 DNS**: AWS/Azure 멀티클라우드에서 각 클라우드의 Private Hosted Zone/Private DNS Zone을 CoreDNS stub domain으로 통합
- **DNS 모니터링**: CoreDNS의 Prometheus 메트릭(`coredns_dns_requests_total`, `coredns_dns_responses_total`, `coredns_dns_request_duration_seconds`)을 Grafana 대시보드에 추가하여 DNS 성능 상시 모니터링

---
**핵심 키워드**: `CoreDNS` `Corefile` `ndots` `search-domain` `stub-domain` `forward` `NodeLocal-DNSCache` `FQDN` `dns-troubleshooting` `resolv.conf`
