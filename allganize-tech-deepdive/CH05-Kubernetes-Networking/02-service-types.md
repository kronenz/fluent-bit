# Kubernetes Service 타입 (Service Types)

> **TL;DR**: Kubernetes Service는 Pod 집합에 안정적인 네트워크 엔드포인트를 제공한다. ClusterIP(내부), NodePort(노드 포트), LoadBalancer(외부 LB), ExternalName(CNAME), Headless(직접 Pod 접근) 다섯 가지 유형이 있으며, 각각 적합한 사용 시나리오가 다르다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### Service가 필요한 이유

Pod는 ephemeral(일시적)하다. ReplicaSet에 의해 재생성되면 IP가 변경된다. Service는 label selector로 Pod 집합을 선택하고 안정적인 DNS 이름과 가상 IP(ClusterIP)를 제공한다.

```
              ┌─────────────────────────────┐
              │     Service (ClusterIP)     │
              │   my-svc.default.svc.       │
              │   cluster.local             │
              │   IP: 10.96.45.12          │
              └──────────┬──────────────────┘
                         │ label selector:
                         │ app=my-app
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         ┌────────┐ ┌────────┐ ┌────────┐
         │ Pod-1  │ │ Pod-2  │ │ Pod-3  │
         │10.244. │ │10.244. │ │10.244. │
         │1.10    │ │1.11    │ │2.20    │
         └────────┘ └────────┘ └────────┘
```

### 1. ClusterIP (기본 타입)

클러스터 내부에서만 접근 가능한 가상 IP를 할당한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alli-backend
spec:
  type: ClusterIP          # 기본값, 생략 가능
  selector:
    app: alli-backend
  ports:
    - port: 80              # Service가 노출하는 포트
      targetPort: 8080      # Pod가 수신하는 포트
      protocol: TCP
```

```
┌─── Cluster 내부 ───────────────────────┐
│                                         │
│  Client Pod ──► 10.96.45.12:80         │
│                      │                  │
│                 iptables/IPVS DNAT     │
│                      │                  │
│                 10.244.x.x:8080        │
│                 (Backend Pod)           │
│                                         │
└─────────────────────────────────────────┘
  ✗ 외부에서 접근 불가
```

**사용 시나리오**: 마이크로서비스 간 내부 통신, DB 접근, 캐시 서비스

### 2. NodePort

ClusterIP를 포함하면서, 모든 Node의 특정 포트(30000-32767)를 열어 외부 접근을 허용한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alli-api-nodeport
spec:
  type: NodePort
  selector:
    app: alli-api
  ports:
    - port: 80
      targetPort: 8080
      nodePort: 30080       # 생략 시 자동 할당
```

```
External Client
    │
    ▼
┌─── Node A ──────┐    ┌─── Node B ──────┐
│   :30080         │    │   :30080         │
│     │            │    │     │            │
│     ▼            │    │     ▼            │
│  ClusterIP:80    │    │  ClusterIP:80    │
│     │            │    │     │            │
│  iptables DNAT   │    │  iptables DNAT   │
│     │            │    │     │            │
│  Pod on any Node │    │  Pod on any Node │
└──────────────────┘    └──────────────────┘
```

**주의사항**:
- `externalTrafficPolicy: Local`을 설정하면 해당 Node에 Pod가 있는 경우에만 트래픽 수신 (추가 hop 제거, source IP 보존)
- `externalTrafficPolicy: Cluster`(기본값)는 모든 Node에서 수신하고 내부 라우팅으로 Pod에 전달 (source IP가 SNAT됨)

### 3. LoadBalancer

NodePort를 포함하면서, 클라우드 프로바이더의 외부 로드밸런서를 자동 프로비저닝한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alli-api-lb
  annotations:
    # AWS NLB 사용
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    # 내부 LB (VPC 내부만 접근)
    service.beta.kubernetes.io/aws-load-balancer-internal: "true"
spec:
  type: LoadBalancer
  selector:
    app: alli-api
  ports:
    - port: 443
      targetPort: 8443
```

```
Internet / VPC
    │
    ▼
┌─────────────────────┐
│  Cloud Load Balancer │  ← 자동 프로비저닝
│  (AWS NLB/ALB)      │
│  (Azure LB)         │
└─────────┬───────────┘
          │
    ┌─────┼─────┐
    ▼     ▼     ▼
 Node A  Node B  Node C    ← NodePort로 수신
  :30080 :30080  :30080
    │     │      │
    └─────┼──────┘
          ▼
    Backend Pods
```

**AWS 환경에서의 LB 유형 선택**:

| 유형 | 어노테이션 | 레이어 | 적합한 워크로드 |
|------|-----------|--------|---------------|
| Classic LB | (기본) | L4/L7 | 레거시, 비권장 |
| NLB | `aws-load-balancer-type: nlb` | L4 | 고성능 TCP, gRPC |
| ALB | Ingress Controller 사용 | L7 | HTTP/HTTPS, path 라우팅 |

### 4. ExternalName

CNAME 레코드를 반환하여 외부 서비스를 클러스터 내부 DNS 이름으로 매핑한다. 프록시나 IP 할당 없이 DNS 수준에서만 작동한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-db
spec:
  type: ExternalName
  externalName: mydb.rds.amazonaws.com   # CNAME 대상
```

```
Pod → DNS query: external-db.default.svc.cluster.local
                         │
                    CoreDNS CNAME
                         │
                         ▼
                 mydb.rds.amazonaws.com
                         │
                    실제 DNS 해석
                         ▼
                   52.xx.xx.xx (RDS IP)
```

**사용 시나리오**: 외부 RDS, ElastiCache, 외부 API를 클러스터 내부에서 일관된 DNS 이름으로 접근

### 5. Headless Service (ClusterIP: None)

ClusterIP를 할당하지 않고, DNS 조회 시 개별 Pod IP를 직접 반환한다.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alli-db-headless
spec:
  clusterIP: None            # Headless 선언
  selector:
    app: alli-db
  ports:
    - port: 27017
```

```
DNS query: alli-db-headless.default.svc.cluster.local

일반 Service 응답:      Headless Service 응답:
  10.96.45.12           10.244.1.10
  (ClusterIP 1개)       10.244.1.11
                        10.244.2.20
                        (모든 Pod IP)
```

**StatefulSet과 함께 사용 시**:
```
# 개별 Pod에 고유 DNS 이름 부여
alli-db-0.alli-db-headless.default.svc.cluster.local → 10.244.1.10
alli-db-1.alli-db-headless.default.svc.cluster.local → 10.244.1.11
alli-db-2.alli-db-headless.default.svc.cluster.local → 10.244.2.20
```

**사용 시나리오**: StatefulSet(MongoDB, Elasticsearch), 클라이언트 사이드 로드밸런싱, gRPC 서비스

### Service 타입 비교 요약

```
                    접근 범위
                    │
 ExternalName ──────┤  DNS만 (CNAME)
                    │
 Headless ──────────┤  Pod IP 직접 반환
                    │
 ClusterIP ─────────┤  클러스터 내부
                    │
 NodePort ──────────┤  + Node IP:Port
                    │
 LoadBalancer ──────┤  + 외부 LB
                    │
```

---

## 실전 예시

### Service 생성 및 확인

```bash
# Service 목록 확인
kubectl get svc -A

# Service 상세 정보 (Endpoints 확인)
kubectl describe svc alli-backend

# Endpoints 직접 확인 (어떤 Pod가 연결되어 있는지)
kubectl get endpoints alli-backend

# EndpointSlice 확인 (K8s 1.21+, 대규모 클러스터에서 효율적)
kubectl get endpointslices -l kubernetes.io/service-name=alli-backend

# Service DNS 해석 테스트
kubectl run dnstest --image=busybox --rm -it -- nslookup alli-backend.default.svc.cluster.local

# Headless Service DNS 해석 (모든 Pod IP 반환)
kubectl run dnstest --image=busybox --rm -it -- nslookup alli-db-headless.default.svc.cluster.local
```

### externalTrafficPolicy 설정

```bash
# Source IP 보존이 필요한 경우
kubectl patch svc alli-api-lb -p '{"spec":{"externalTrafficPolicy":"Local"}}'

# 확인
kubectl get svc alli-api-lb -o jsonpath='{.spec.externalTrafficPolicy}'

# 주의: Local 모드에서는 Pod가 없는 Node로의 트래픽이 드롭됨
# Health check 설정이 중요
kubectl get svc alli-api-lb -o jsonpath='{.spec.healthCheckNodePort}'
```

### Session Affinity 설정

```yaml
apiVersion: v1
kind: Service
metadata:
  name: alli-api
spec:
  selector:
    app: alli-api
  sessionAffinity: ClientIP      # 같은 클라이언트 → 같은 Pod
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 10800      # 3시간
  ports:
    - port: 80
      targetPort: 8080
```

---

## 면접 Q&A

### Q: ClusterIP, NodePort, LoadBalancer의 관계를 설명해주세요.
**30초 답변**:
이 세 타입은 포함 관계입니다. LoadBalancer는 NodePort를 포함하고, NodePort는 ClusterIP를 포함합니다. ClusterIP는 내부 가상 IP, NodePort는 모든 Node의 특정 포트를 추가로 개방, LoadBalancer는 여기에 클라우드 외부 LB를 프로비저닝합니다.

**2분 답변**:
ClusterIP가 가장 기본 타입으로, 클러스터 내부에서만 접근 가능한 가상 IP를 생성합니다. kube-proxy가 iptables/IPVS 규칙으로 이 IP에 대한 트래픽을 실제 Pod로 분산합니다.

NodePort는 ClusterIP를 포함하면서 모든 Node의 30000-32767 범위 포트를 열어 외부에서 `NodeIP:NodePort`로 접근할 수 있게 합니다. 어떤 Node에 요청하든 kube-proxy가 실제 Pod로 라우팅합니다.

LoadBalancer는 NodePort를 포함하면서 클라우드 프로바이더의 API를 호출하여 외부 LB(AWS NLB/ALB, Azure LB)를 자동 프로비저닝합니다. LB가 각 Node의 NodePort로 트래픽을 분산하고, Node에서 다시 Pod로 전달됩니다.

실무에서 프로덕션 외부 노출은 LoadBalancer 또는 Ingress를 사용하고, 내부 서비스 간 통신은 ClusterIP를 사용합니다. NodePort는 개발/테스트 환경이나 on-premise에서 외부 LB 없이 서비스를 노출할 때 사용합니다.

**경험 연결**:
온프레미스 환경에서는 클라우드 LB가 없으므로 MetalLB나 외부 HAProxy를 NodePort와 조합하여 LoadBalancer 타입을 시뮬레이션했습니다. 클라우드 환경에서는 annotation으로 NLB/ALB를 세밀하게 제어할 수 있어 훨씬 편리합니다.

**주의**:
LoadBalancer Service 하나당 LB 하나가 생성되므로 비용이 증가한다. 여러 서비스를 노출할 때는 Ingress Controller를 LB 하나로 묶어 사용하는 것이 비용 효율적이다.

### Q: Headless Service는 언제 사용하나요?
**30초 답변**:
Headless Service는 ClusterIP를 None으로 설정하여 로드밸런싱 없이 개별 Pod IP를 DNS로 직접 반환합니다. StatefulSet과 함께 사용하면 각 Pod에 고유 DNS 이름을 부여할 수 있어 MongoDB, Elasticsearch 같은 stateful 워크로드에 필수적입니다.

**2분 답변**:
Headless Service는 세 가지 주요 시나리오에서 사용됩니다.

첫째, StatefulSet과 조합하여 `pod-0.svc-name.namespace.svc.cluster.local` 형태의 고유 DNS를 제공합니다. MongoDB replica set이나 Elasticsearch 클러스터에서 각 노드가 서로를 식별해야 하므로 필수입니다.

둘째, 클라이언트 사이드 로드밸런싱이 필요한 경우입니다. gRPC는 HTTP/2 기반으로 long-lived connection을 유지하므로, kube-proxy의 L4 로드밸런싱이 효과적이지 않습니다. Headless Service로 모든 Pod IP를 받아 클라이언트가 직접 분산하거나, Service Mesh의 사이드카가 L7 로드밸런싱을 수행합니다.

셋째, Pod discovery 용도로 사용됩니다. DNS SRV 레코드를 통해 모든 백엔드 Pod를 자동 발견하는 패턴에 활용됩니다.

**경험 연결**:
온프레미스에서 MongoDB 클러스터를 운영할 때 각 노드에 고정 IP를 할당하고 DNS를 수동 관리했는데, Kubernetes에서는 StatefulSet + Headless Service로 이 과정이 완전히 자동화됩니다. Allganize에서 Elasticsearch나 MongoDB를 K8s 위에서 운영한다면 이 패턴이 핵심입니다.

**주의**:
Headless Service에 selector가 없으면 Endpoints 객체도 자동 생성되지 않는다. 이 경우 직접 Endpoints를 생성해야 한다.

### Q: externalTrafficPolicy의 Local과 Cluster 차이는 무엇인가요?
**30초 답변**:
Cluster(기본값)는 트래픽을 모든 Node에서 받아 내부 라우팅으로 Pod에 전달하므로 균등 분산이 가능하지만, 추가 hop과 SNAT으로 source IP가 손실됩니다. Local은 해당 Node의 Pod에만 트래픽을 전달하여 source IP를 보존하지만, Pod가 없는 Node로의 트래픽은 드롭됩니다.

**2분 답변**:
`externalTrafficPolicy: Cluster`는 모든 Node의 NodePort에서 트래픽을 수신합니다. 해당 Node에 Pod가 없어도 다른 Node의 Pod로 전달합니다. 이때 SNAT이 발생하여 source IP가 Node IP로 변환됩니다. 장점은 균등 분산이고, 단점은 추가 network hop과 source IP 손실입니다.

`externalTrafficPolicy: Local`은 해당 Node에 실행 중인 Pod에만 트래픽을 전달합니다. Pod가 없는 Node의 health check는 실패하여 LB가 해당 Node를 제외합니다. source IP가 보존되고 추가 hop이 없어 latency가 줄지만, Pod 분포가 불균등하면 트래픽도 불균등해질 수 있습니다.

AI 서비스에서 source IP 기반 rate limiting이나 감사 로그가 필요하면 Local이 적합하고, 고가용성과 균등 분산이 우선이면 Cluster가 적합합니다. 실무에서는 Ingress Controller의 Service에 Local을 설정하여 source IP를 보존하면서 Ingress 수준에서 로드밸런싱하는 패턴이 일반적입니다.

**경험 연결**:
온프레미스 L4 로드밸런서에서 source IP 보존 여부를 DSR(Direct Server Return) 모드로 제어했던 경험과 유사한 개념입니다. 클라우드에서는 annotation 하나로 제어할 수 있어 운영이 훨씬 간편합니다.

**주의**:
Local 모드에서 Node 간 Pod 수가 다르면 트래픽이 불균등하게 분산된다. 예를 들어 Node A에 Pod 1개, Node B에 Pod 3개면, Node A의 Pod이 Node B의 각 Pod보다 3배 많은 트래픽을 받는다.

---

## Allganize 맥락

- **내부 마이크로서비스**: Alli AI 엔진의 내부 서비스 간 통신(API → 추론엔진 → 벡터DB)은 ClusterIP로 구성. gRPC 사용 시 Headless Service + 클라이언트 사이드 LB 또는 Service Mesh 고려
- **외부 API 노출**: 고객 대면 API는 LoadBalancer(NLB) + Ingress Controller 조합. NLB는 L4에서 TLS passthrough 또는 Ingress에서 TLS termination
- **비용 최적화**: Service마다 LB를 생성하지 않고 Ingress Controller 1개의 LB로 통합. AWS에서 NLB 하나의 월 비용은 약 $16+ 데이터 처리비
- **MongoDB/Elasticsearch**: StatefulSet + Headless Service로 운영하여 각 인스턴스가 고유 DNS로 서로를 인식

---
**핵심 키워드**: `ClusterIP` `NodePort` `LoadBalancer` `ExternalName` `Headless` `externalTrafficPolicy` `EndpointSlice` `SessionAffinity`
