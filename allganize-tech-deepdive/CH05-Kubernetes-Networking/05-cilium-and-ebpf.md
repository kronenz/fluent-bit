# Cilium & eBPF 심화 (Cilium & eBPF Deep Dive)

> **TL;DR**: Cilium은 eBPF를 데이터플레인으로 사용하는 CNI 플러그인으로, iptables 없이 커널 수준에서 패킷을 처리하여 최고 성능을 제공한다. kube-proxy 완전 대체, L7 네트워크 정책, Hubble 기반 관측성이 핵심 차별점이며, CNCF Graduated 프로젝트로 Kubernetes 네트워킹의 미래 표준으로 자리잡고 있다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 25min

---

## 핵심 개념

### eBPF란?

eBPF(extended Berkeley Packet Filter)는 Linux 커널에서 커스텀 프로그램을 안전하게 실행하는 기술이다. 커널을 수정하거나 모듈을 로드하지 않고도 네트워킹, 보안, 관측성을 커널 수준에서 처리할 수 있다.

```
┌──────────────────────────────────────────────────┐
│  User Space                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Cilium   │  │ Hubble   │  │ kubectl  │       │
│  │ Agent    │  │ Observer │  │          │       │
│  └────┬─────┘  └────┬─────┘  └──────────┘       │
│       │              │                            │
├───────┼──────────────┼────────────────────────────┤
│  Kernel Space        │                            │
│       │              │                            │
│       ▼              │                            │
│  ┌─────────────────────────────────────────┐     │
│  │           eBPF Virtual Machine           │     │
│  │                                          │     │
│  │  ┌─────┐  ┌─────┐  ┌─────┐  ┌──────┐  │     │
│  │  │ XDP │  │ TC  │  │Socket│  │kprobe│  │     │
│  │  │     │  │     │  │ LB  │  │      │  │     │
│  │  └──┬──┘  └──┬──┘  └──┬──┘  └──┬───┘  │     │
│  │     │        │        │        │       │     │
│  └─────┼────────┼────────┼────────┼───────┘     │
│        │        │        │        │              │
│  ──────┴────────┴────────┴────────┴──────────    │
│              Network Stack / Syscalls             │
└──────────────────────────────────────────────────┘
```

**eBPF 훅 포인트(Hook Points)**:

| 훅 | 위치 | 용도 |
|----|------|------|
| **XDP** (eXpress Data Path) | NIC 드라이버 직후 | 초고속 패킷 필터링, DDoS 방어 |
| **TC** (Traffic Control) | 네트워크 스택 입구/출구 | 패킷 변환, 라우팅, 정책 적용 |
| **Socket** | 소켓 레이어 | Service LB (connect-time), 소켓 레벨 정책 |
| **kprobe/tracepoint** | 커널 함수 진입/반환 | 관측성, 디버깅 |

### Cilium 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│  Cilium Cluster Architecture                              │
│                                                           │
│  ┌─── Control Plane ────────────────────────────────┐    │
│  │  ┌──────────────┐  ┌───────────────────────┐    │    │
│  │  │ Cilium       │  │ Cilium Operator       │    │    │
│  │  │ Agent        │  │ - IPAM 관리            │    │    │
│  │  │ (DaemonSet)  │  │ - CRD 동기화          │    │    │
│  │  │              │  │ - GC (garbage collect) │    │    │
│  │  │ 역할:        │  └───────────────────────┘    │    │
│  │  │ - eBPF 로드  │                                │    │
│  │  │ - Policy 적용│  ┌───────────────────────┐    │    │
│  │  │ - IPAM       │  │ Hubble                │    │    │
│  │  │ - Health     │  │ - Relay (집계)        │    │    │
│  │  └──────────────┘  │ - UI (시각화)         │    │    │
│  │                     │ - CLI                 │    │    │
│  │                     └───────────────────────┘    │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌─── Data Plane (per Node) ────────────────────────┐    │
│  │                                                    │    │
│  │  NIC → [XDP] → [TC ingress] → Pod                │    │
│  │                                                    │    │
│  │  Pod → [TC egress] → [Socket LB] → NIC/Pod       │    │
│  │                                                    │    │
│  │  iptables: 없음 (완전 대체)                        │    │
│  │  kube-proxy: 없음 (eBPF Socket LB로 대체)         │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### kube-proxy 대체 (eBPF-based kube-proxy replacement)

기존 kube-proxy는 iptables/IPVS로 Service→Pod DNAT을 수행한다. Cilium은 eBPF Socket-level LB로 이를 완전 대체한다.

```
기존 (kube-proxy + iptables):
  App → connect(svc-ip:port) → TCP SYN
       → iptables PREROUTING → KUBE-SERVICES chain
       → DNAT → pod-ip:port
       → routing → 전달

Cilium eBPF:
  App → connect(svc-ip:port)
       → eBPF socket hook (connect-time LB)
       → 즉시 pod-ip:port로 변환
       → TCP SYN은 이미 pod-ip로 발송
       → iptables 체인 전혀 거치지 않음
```

**성능 이점**:
- iptables 체인 순회 제거 → latency 감소
- conntrack 테이블 부하 감소
- Service 수가 증가해도 성능 일정 (O(1))
- 대규모 클러스터(10,000+ Service)에서 극적 차이

### Cilium Identity 기반 보안

Cilium은 IP 기반이 아닌 **Identity 기반** 보안 모델을 사용한다.

```
전통적 NetworkPolicy:
  "10.244.1.10에서 10.244.2.20으로의 트래픽 허용"
  → Pod IP가 변경되면 규칙 갱신 필요

Cilium Identity:
  "app=frontend identity(12345)에서 app=backend identity(67890)으로 허용"
  → Pod label 기반 identity 할당
  → IP 변경에 무관하게 정책 유지
  → eBPF map에서 identity 조회 (O(1))
```

```
┌─────────────────────────────────────────────────┐
│  Identity 할당 흐름                               │
│                                                   │
│  Pod 생성                                         │
│    │                                              │
│    ▼ Cilium Agent가 label 확인                    │
│    │                                              │
│    ▼ label set → identity 매핑 (hash)            │
│    │  {app:frontend, env:prod} → ID: 12345       │
│    │                                              │
│    ▼ Identity를 eBPF map에 등록                   │
│    │                                              │
│    ▼ 같은 label의 모든 Pod는 같은 Identity 공유   │
└─────────────────────────────────────────────────┘
```

### Hubble: 네트워크 관측성 (Network Observability)

Hubble은 eBPF를 활용하여 모든 네트워크 플로우를 커널 수준에서 수집하는 관측성 도구이다.

```
┌──────────────────────────────────────────────┐
│  Hubble Architecture                          │
│                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Hubble   │  │ Hubble   │  │ Hubble   │   │
│  │ (Node A) │  │ (Node B) │  │ (Node C) │   │
│  │ eBPF     │  │ eBPF     │  │ eBPF     │   │
│  │ events   │  │ events   │  │ events   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │         │
│       └──────────────┼──────────────┘         │
│                      ▼                        │
│              ┌──────────────┐                 │
│              │ Hubble Relay │  ← 집계         │
│              └──────┬───────┘                 │
│                     │                         │
│           ┌─────────┼─────────┐               │
│           ▼                   ▼               │
│    ┌──────────┐        ┌──────────┐          │
│    │ Hubble   │        │ Hubble   │          │
│    │ CLI      │        │ UI       │          │
│    └──────────┘        └──────────┘          │
└──────────────────────────────────────────────┘
```

**Hubble이 제공하는 정보**:
- L3/L4 네트워크 플로우 (src/dst IP, port, protocol)
- L7 프로토콜 상세 (HTTP method/path/status, gRPC method, DNS query)
- 정책 verdict (ALLOWED, DENIED, DROPPED)
- 서비스 의존성 맵 (service-to-service topology)
- 네트워크 메트릭 (latency, throughput, error rate)

### Cilium L7 네트워크 정책

```yaml
# HTTP 메서드 + 경로 기반 정책
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: alli-api-l7-policy
spec:
  endpointSelector:
    matchLabels:
      app: alli-api
  ingress:
    - fromEndpoints:
        - matchLabels:
            app: alli-frontend
      toPorts:
        - ports:
            - port: "8080"
              protocol: TCP
          rules:
            http:
              - method: "GET"
                path: "/api/v1/.*"
              - method: "POST"
                path: "/api/v1/chat"
                headers:
                  - 'Content-Type: application/json'
```

```yaml
# FQDN 기반 Egress 정책
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-external-api
spec:
  endpointSelector:
    matchLabels:
      app: alli-engine
  egress:
    - toFQDNs:
        - matchPattern: "*.openai.com"
        - matchName: "api.anthropic.com"
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
    - toEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: kube-system
            k8s-app: kube-dns
      toPorts:
        - ports:
            - port: "53"
              protocol: UDP
          rules:
            dns:
              - matchPattern: "*"
```

---

## 실전 예시

### Cilium 설치 및 상태 확인

```bash
# Helm으로 Cilium 설치 (kube-proxy 대체 모드)
helm repo add cilium https://helm.cilium.io/
helm install cilium cilium/cilium \
  --namespace kube-system \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=<API-SERVER-IP> \
  --set k8sServicePort=6443 \
  --set hubble.enabled=true \
  --set hubble.relay.enabled=true \
  --set hubble.ui.enabled=true

# Cilium 상태 확인
cilium status --wait

# 전체 연결성 테스트 (Pod-to-Pod, Service, External 등)
cilium connectivity test

# eBPF 프로그램 확인
cilium bpf endpoint list
cilium bpf ct list global    # conntrack 테이블
cilium bpf lb list           # Service LB 맵

# kube-proxy 대체 확인
cilium status | grep KubeProxyReplacement
# 출력: KubeProxyReplacement:   True
```

### Hubble 사용

```bash
# Hubble CLI로 실시간 플로우 관찰
hubble observe --namespace alli-prod

# 특정 Pod의 플로우만 필터
hubble observe --pod alli-api-xxxxx --protocol http

# 드롭된 패킷만 확인 (정책 위반 트래픽)
hubble observe --verdict DROPPED

# L7 HTTP 플로우 (메서드, 경로, 상태코드)
hubble observe --protocol http -o json | jq '.flow.l7.http'

# 서비스 맵 (의존성 시각화용 데이터)
hubble observe --namespace alli-prod -o json | jq '{src: .flow.source.labels, dst: .flow.destination.labels}'

# Hubble UI 포트포워드
kubectl port-forward -n kube-system svc/hubble-ui 12000:80
# 브라우저에서 http://localhost:12000 접속
```

### Cilium 정책 디버깅

```bash
# 정책 상태 확인
cilium policy get

# 특정 엔드포인트의 정책 확인
cilium endpoint list
cilium endpoint get <endpoint-id> -o jsonpath='{.status.policy}'

# Identity 확인
cilium identity list
cilium identity get <identity-id>

# 정책 적용 전후 트래픽 테스트
kubectl exec -it debug-pod -- curl -v http://alli-api:8080/api/v1/chat
hubble observe --pod debug-pod --verdict DROPPED  # 드롭 확인
```

---

## 면접 Q&A

### Q: eBPF가 Kubernetes 네트워킹에서 왜 중요한가요?
**30초 답변**:
eBPF는 커널 수준에서 패킷을 직접 처리하여 iptables의 성능 한계를 극복합니다. kube-proxy를 대체하여 Service 라우팅을 O(1)로 처리하고, L7 프로토콜 인식 정책, 커널 수준 관측성을 제공합니다. 이는 대규모 Kubernetes 클러스터의 네트워크 성능과 보안을 근본적으로 개선합니다.

**2분 답변**:
전통적 Kubernetes 네트워킹은 kube-proxy의 iptables 규칙에 의존합니다. Service가 수천 개 이상이면 iptables 규칙이 수만 개로 늘어나 순차 매칭으로 인한 latency가 발생합니다. 규칙 업데이트도 전체 테이블을 재작성하므로 CPU 부하가 높습니다.

eBPF는 이 문제를 근본적으로 해결합니다. 첫째, eBPF 해시 맵으로 Service→Pod 매핑을 O(1)으로 조회합니다. 둘째, Socket 레벨 훅에서 connect 시점에 바로 Pod IP로 변환하여 iptables 체인을 전혀 거치지 않습니다. 셋째, XDP 훅에서 NIC 드라이버 직후에 패킷을 처리하여 DDoS 방어 등 초고속 필터링이 가능합니다.

관측성 측면에서도 eBPF는 커널 이벤트를 직접 수집하므로 사이드카 프록시 없이 L7 플로우(HTTP method/path, gRPC method)를 관찰할 수 있습니다. Cilium의 Hubble이 이를 활용하여 서비스 메시 없이도 높은 수준의 네트워크 가시성을 제공합니다.

**경험 연결**:
대규모 인프라에서 iptables 규칙 수가 늘어나며 패킷 처리 지연이 발생한 경험이 있습니다. eBPF는 커널을 프로그래밍할 수 있게 해주어 이런 한계를 근본적으로 해결하며, 마치 네트워크 장비의 ASIC 처리를 소프트웨어로 구현한 것과 유사합니다.

**주의**:
eBPF는 커널 버전에 의존한다. Cilium의 전체 기능을 사용하려면 Linux 5.4+ 커널이 권장된다. AWS EKS의 Amazon Linux 2는 5.10 커널이므로 호환되지만, 오래된 CentOS 7(3.10 커널)에서는 사용 불가하다.

### Q: Cilium의 Hubble과 기존 모니터링 도구(Prometheus, Datadog)의 차이는?
**30초 답변**:
Hubble은 eBPF 기반으로 커널 수준에서 모든 네트워크 플로우를 실시간으로 수집하는 관측성 도구입니다. Prometheus나 Datadog은 메트릭/로그 기반이라 "무엇이 느린가"는 알 수 있지만, "어떤 패킷이 어디서 드롭되었는가"는 Hubble만 알 수 있습니다. 상호 보완적으로 사용합니다.

**2분 답변**:
Hubble은 eBPF를 통해 커널 네트워크 스택의 모든 이벤트를 가로채므로 패킷 수준의 관측성을 제공합니다. 구체적으로 L3/L4 플로우(src/dst IP, port), L7 프로토콜 상세(HTTP request/response, DNS query/answer), 정책 verdict(ALLOWED/DENIED/DROPPED), 그리고 서비스 간 의존성 토폴로지를 실시간으로 보여줍니다.

Prometheus는 시계열 메트릭을 수집합니다. CPU, 메모리, 요청 수, 에러율 같은 집계 데이터에 강합니다. Datadog은 메트릭 + 로그 + APM을 통합하여 애플리케이션 수준의 가시성을 제공합니다.

이 도구들은 상호 보완적입니다. Hubble은 네트워크 장애의 근본 원인을 파악하는 데 사용하고(예: "Pod A에서 Pod B로의 TCP SYN이 NetworkPolicy에 의해 드롭됨"), Prometheus/Datadog은 서비스 수준의 SLI/SLO 모니터링에 사용합니다. Hubble은 Prometheus 메트릭을 export할 수 있어 Grafana 대시보드에 통합할 수 있습니다.

**경험 연결**:
네트워크 장비의 flow log(NetFlow, sFlow)를 분석하여 트래픽 패턴을 파악한 경험이 있습니다. Hubble은 이 개념을 Kubernetes 환경에 적용한 것으로, Pod 수준의 flow 분석이 가능하여 마이크로서비스 간 통신 문제를 빠르게 진단할 수 있습니다.

**주의**:
Hubble은 eBPF 이벤트를 메모리 링 버퍼에 저장하므로 기본적으로 일시적이다. 장기 보존이 필요하면 Hubble의 메트릭을 Prometheus로 export하거나, 외부 저장소로 export하는 설정이 필요하다.

### Q: Cilium으로 kube-proxy를 대체하면 어떤 이점이 있나요?
**30초 답변**:
iptables 규칙 체인이 완전히 제거되어 Service 라우팅 성능이 O(1)이 됩니다. Socket 레벨에서 connect 시점에 바로 Pod IP로 변환하므로 불필요한 패킷 변환이 없고, conntrack 부하가 줄어듭니다. DSR(Direct Server Return) 모드로 응답 패킷이 원래 경로를 거치지 않아 latency가 추가로 감소합니다.

**2분 답변**:
kube-proxy 대체의 이점은 네 가지입니다.

첫째, 성능 개선입니다. iptables의 O(n) 규칙 매칭이 eBPF 해시 맵의 O(1) 조회로 대체됩니다. 10,000개 Service 환경에서 첫 패킷 latency가 수 ms에서 수십 us로 줄어듭니다.

둘째, 리소스 절약입니다. iptables 규칙 갱신 시 전체 테이블을 재작성하는 CPU 오버헤드가 사라집니다. conntrack 테이블 크기도 감소합니다.

셋째, DSR(Direct Server Return) 모드입니다. 클라이언트 → Node A → Pod(Node B)의 응답이 Node A를 거치지 않고 Pod에서 직접 클라이언트로 반환됩니다. Source IP가 보존되고 응답 경로가 단축됩니다.

넷째, 운영 단순화입니다. kube-proxy DaemonSet이 불필요해지고, iptables 규칙 디버깅이 필요 없어집니다. Hubble로 Service 라우팅을 직접 관찰할 수 있습니다.

단, kube-proxy 대체 시 Cilium이 단일 장애점(SPOF)이 될 수 있으므로 Cilium Agent의 안정성과 모니터링이 중요합니다.

**경험 연결**:
L4 스위치에서 DSR 모드를 구성하여 응답 트래픽이 LB를 우회하도록 설정한 경험이 있습니다. Cilium의 DSR도 동일한 개념이며, 특히 AI 추론 서비스처럼 응답이 큰 워크로드에서 효과적입니다.

**주의**:
kube-proxy 대체 모드에서는 NodePort 범위의 모든 트래픽이 Cilium에 의해 처리된다. Cilium Agent가 비정상이면 Service 라우팅이 중단될 수 있으므로 반드시 모니터링과 알림을 설정해야 한다.

---

## Allganize 맥락

- **EKS에서 Cilium 도입**: EKS에서 VPC CNI를 유지하면서 Cilium을 overlay로 추가하거나, Cilium을 기본 CNI로 교체하여 kube-proxy 대체 + Hubble 관측성 확보 가능
- **AI 서비스 네트워크 성능**: LLM 추론의 long-tail latency를 줄이기 위해 eBPF 기반 Service 라우팅이 유리. 특히 Streaming 응답(SSE/WebSocket)에서 connection 수가 많은 경우 iptables 부하 제거 효과가 크다
- **FQDN 기반 Egress 정책**: AI 엔진이 외부 LLM API(OpenAI, Anthropic 등)를 호출할 때 FQDN 기반 Egress 정책으로 허용 도메인만 통신 가능하도록 제어. IP가 동적으로 변하는 SaaS API에 IP 기반 정책은 부적합
- **Hubble로 서비스 토폴로지**: 마이크로서비스 간 의존성을 Hubble UI로 시각화하여 장애 영향 범위를 빠르게 파악. Datadog APM과 상호 보완적으로 활용
- **Zero Trust 네트워크**: Cilium의 Identity 기반 보안으로 "default deny + explicit allow" 정책을 구현하여 멀티테넌트 AI 서비스의 네트워크 격리 보장

---
**핵심 키워드**: `eBPF` `Cilium` `XDP` `kube-proxy-replacement` `Hubble` `Identity` `L7-policy` `FQDN-policy` `DSR` `Socket-LB`
