# Control Plane Components

> **TL;DR**: Control Plane은 클러스터의 "두뇌"로, kube-apiserver가 모든 요청의 관문 역할을 하고, etcd가 상태를 저장하며, scheduler가 Pod 배치를 결정하고, controller-manager가 desired state를 유지한다.
> 모든 컴포넌트는 kube-apiserver를 통해서만 통신하며, 직접 etcd에 접근하는 것은 kube-apiserver뿐이다.
> HA 구성 시 apiserver는 Active-Active, controller-manager/scheduler는 leader election 기반 Active-Standby로 동작한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Control Plane 전체 아키텍처

```
                    ┌─────────────────────────────────────┐
                    │         Control Plane Node(s)        │
                    │                                     │
  kubectl ─────────►│  ┌──────────────┐                   │
  API clients ─────►│  │ kube-apiserver│◄──── 유일한 etcd  │
  kubelet ─────────►│  │  (REST API)   │      접근 컴포넌트 │
                    │  └──────┬───────┘                   │
                    │         │ watch/list                 │
                    │    ┌────┴────┬──────────┐           │
                    │    │         │          │           │
                    │    ▼         ▼          ▼           │
                    │ ┌──────┐ ┌────────┐ ┌──────────┐   │
                    │ │ etcd │ │scheduler│ │controller │   │
                    │ │      │ │        │ │ -manager  │   │
                    │ └──────┘ └────────┘ └──────────┘   │
                    └─────────────────────────────────────┘
```

### 1. kube-apiserver

Kubernetes의 **유일한 진입점(Single Point of Entry)**. 모든 컴포넌트 간 통신은 반드시 apiserver를 경유한다.

**핵심 역할:**
- RESTful API 제공 (`/api/v1`, `/apis/apps/v1` 등)
- **Authentication** (인증) → **Authorization** (인가, RBAC) → **Admission Control** (정책 적용) 파이프라인
- etcd에 대한 유일한 읽기/쓰기 인터페이스
- Watch 메커니즘으로 변경사항 실시간 전파

**요청 처리 흐름:**
```
Client Request
    │
    ▼
┌─────────────┐
│ Authentication│  ─── X.509 cert, Bearer token, OIDC
└──────┬──────┘
       ▼
┌─────────────┐
│ Authorization │  ─── RBAC, ABAC, Webhook
└──────┬──────┘
       ▼
┌─────────────────┐
│ Admission Control│  ─── Mutating → Validating webhooks
└──────┬──────────┘
       ▼
┌─────────────┐
│  etcd Write  │  ─── 최종 상태 저장
└─────────────┘
```

### 2. etcd

분산 Key-Value 스토어. 클러스터의 **모든 상태(desired + actual)**를 저장한다.

**특성:**
- Raft consensus 알고리즘 기반 (quorum = N/2 + 1)
- 강한 일관성(Strong Consistency) 보장
- Watch API로 변경 이벤트 스트리밍
- `/registry/` prefix 아래에 모든 K8s 리소스 저장

**키 구조 예시:**
```
/registry/pods/default/my-pod
/registry/deployments/production/my-app
/registry/secrets/kube-system/admin-token
/registry/services/specs/default/my-service
```

### 3. kube-scheduler

**바인딩되지 않은(unscheduled) Pod**를 감시하고, 최적의 노드에 배치한다.

**스케줄링 2단계:**
```
Unscheduled Pod 감시 (watch)
        │
        ▼
┌──────────────┐
│  1. Filtering │  ─── 조건 불충족 노드 제거
│  (Predicates) │      (리소스 부족, taint, affinity 위반 등)
└──────┬───────┘
       ▼
┌──────────────┐
│  2. Scoring   │  ─── 남은 노드에 점수 부여
│  (Priorities) │      (리소스 균형, affinity 선호도 등)
└──────┬───────┘
       ▼
  최고 점수 노드에 Binding
```

### 4. kube-controller-manager

**Desired State ↔ Current State** 차이를 감지하고 조정하는 **컨트롤 루프** 모음.

**주요 내장 컨트롤러:**

| Controller | 역할 |
|---|---|
| Deployment Controller | ReplicaSet 생성/업데이트, 롤링 업데이트 관리 |
| ReplicaSet Controller | Pod 수를 desired count로 유지 |
| Node Controller | 노드 상태 모니터링, NotReady 시 Pod eviction |
| Job Controller | 배치 작업 실행 및 완료 관리 |
| ServiceAccount Controller | 네임스페이스별 기본 SA 생성 |
| Endpoint Controller | Service ↔ Pod 매핑 관리 |

**컨트롤 루프 패턴:**
```
  ┌──────────────────────────────────────┐
  │         Controller Loop              │
  │                                      │
  │   Observe ──► Diff ──► Act           │
  │      │                   │           │
  │      │    desired state  │           │
  │      │    vs current     │           │
  │      │    state          │           │
  │      └───────────────────┘           │
  │         (반복, reconciliation)        │
  └──────────────────────────────────────┘
```

### HA (High Availability) 구성

```
          Load Balancer (L4)
          ┌─────┴─────┐
          ▼           ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │apiserver │ │apiserver │ │apiserver │   ◄── Active-Active
   │scheduler │ │scheduler │ │scheduler │   ◄── Leader Election
   │ctrl-mgr  │ │ctrl-mgr  │ │ctrl-mgr  │   ◄── Leader Election
   │etcd      │ │etcd      │ │etcd      │   ◄── Raft Quorum (3노드)
   └──────────┘ └──────────┘ └──────────┘
    Master-1      Master-2     Master-3
```

- **apiserver**: Stateless → Load Balancer 뒤에서 Active-Active
- **scheduler / controller-manager**: Leader Election으로 1개만 active
- **etcd**: 홀수 노드(3, 5) 권장, quorum 기반 합의

---

## 실전 예시

### 컴포넌트 상태 확인

```bash
# Control Plane 컴포넌트 상태 확인
kubectl get componentstatuses   # deprecated but still works
kubectl get cs

# 더 정확한 방법: 각 컴포넌트의 healthz 엔드포인트
kubectl get --raw /healthz
kubectl get --raw /livez
kubectl get --raw /readyz

# Control Plane Pod 확인 (kubeadm 기반)
kubectl get pods -n kube-system
```

### etcd 직접 조회 (디버깅용)

```bash
# etcd에 저장된 키 목록 확인
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  get /registry/ --prefix --keys-only | head -20

# 특정 Pod의 etcd 데이터 확인
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  get /registry/pods/default/my-pod
```

### Leader Election 확인

```bash
# scheduler leader 확인
kubectl get endpoints kube-scheduler -n kube-system -o yaml

# controller-manager leader 확인
kubectl get lease kube-controller-manager -n kube-system -o yaml

# 또는 Lease 오브젝트로 확인 (1.20+)
kubectl get lease -n kube-system
```

### API Server 감사(Audit) 로그 설정

```yaml
# /etc/kubernetes/audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: Metadata
    resources:
      - group: ""
        resources: ["secrets", "configmaps"]
  - level: RequestResponse
    resources:
      - group: ""
        resources: ["pods"]
    verbs: ["create", "delete"]
  - level: None
    resources:
      - group: ""
        resources: ["events"]
```

---

## 면접 Q&A

### Q: Control Plane의 각 컴포넌트 역할을 설명해주세요.
**30초 답변**:
kube-apiserver는 모든 API 요청의 관문이자 etcd에 접근하는 유일한 컴포넌트입니다. etcd는 클러스터 상태를 저장하는 분산 KV 스토어이고, scheduler는 Pod를 노드에 배치하며, controller-manager는 desired state와 current state의 차이를 조정합니다.

**2분 답변**:
Control Plane은 4가지 핵심 컴포넌트로 구성됩니다. 첫째, kube-apiserver는 RESTful API를 제공하며 인증-인가-Admission Control 파이프라인을 거쳐 요청을 처리합니다. 모든 컴포넌트 간 통신은 apiserver를 경유하며, etcd에 직접 접근하는 유일한 컴포넌트입니다. 둘째, etcd는 Raft consensus 기반의 분산 KV 스토어로, 클러스터의 모든 상태를 저장합니다. 셋째, kube-scheduler는 unscheduled Pod를 감시하여 Filtering(조건 불충족 노드 제거)과 Scoring(점수 기반 우선순위) 2단계로 최적 노드를 결정합니다. 넷째, kube-controller-manager는 Deployment, ReplicaSet, Node 등 다양한 컨트롤러를 하나의 바이너리로 실행하며, "Observe → Diff → Act" 루프로 desired state를 유지합니다. HA 구성 시 apiserver는 Active-Active, scheduler와 controller-manager는 leader election 기반 Active-Standby로 운영합니다.

**경험 연결**:
폐쇄망 온프레미스 환경에서 kubeadm으로 클러스터를 구축할 때, apiserver 인증서 만료로 kubectl이 동작하지 않는 상황을 경험한 적 있습니다. 이때 etcd에 직접 접근하여 상태를 확인하고, 인증서를 갱신한 후 apiserver를 재시작하여 복구했습니다. 이 경험을 통해 각 컴포넌트의 의존 관계를 체감했습니다.

**주의**:
"etcd에 모든 컴포넌트가 직접 접근한다"고 잘못 답변하지 않도록 주의. apiserver만 etcd에 접근하며, 나머지는 apiserver의 watch/list를 통해 상태를 얻는다.

### Q: kube-apiserver가 Single Point of Failure가 되지 않으려면 어떻게 해야 하나요?
**30초 답변**:
apiserver는 stateless이므로 여러 인스턴스를 L4 Load Balancer 뒤에 Active-Active로 배치합니다. 최소 3개 노드를 권장하며, 각 apiserver가 동일한 etcd 클러스터를 바라봅니다.

**2분 답변**:
apiserver의 HA를 위해서는 여러 층위의 전략이 필요합니다. 먼저 apiserver 자체는 stateless이므로 다수 인스턴스를 실행하고 앞단에 L4 Load Balancer(HAProxy, AWS NLB 등)를 둡니다. etcd는 반드시 홀수(3 또는 5) 노드로 구성하여 Raft quorum을 보장합니다. 3노드면 1노드 장애 허용, 5노드면 2노드 장애를 허용합니다. scheduler와 controller-manager는 `--leader-elect=true`로 실행하여 하나만 active로 동작하게 합니다. leader가 죽으면 Lease 오브젝트 기반으로 다른 인스턴스가 leader를 인수합니다. 추가로 etcd 백업을 주기적으로 수행하고, apiserver 앞단 LB의 health check를 `/readyz` 엔드포인트로 설정해야 합니다. Allganize처럼 AWS EKS를 사용하면 Control Plane HA는 AWS가 관리하므로, Worker Node의 Multi-AZ 배치와 PodDisruptionBudget에 집중하면 됩니다.

**경험 연결**:
온프레미스에서 3-master 구성을 운영할 때, etcd 노드 하나가 디스크 I/O 병목으로 느려지면서 전체 클러스터가 불안정해진 경험이 있습니다. etcd는 SSD를 사용하고 별도 디스크를 할당하는 것이 중요함을 배웠습니다.

**주의**:
EKS/AKS 같은 managed K8s에서는 Control Plane이 클라우드 제공자가 관리하므로, 직접 etcd를 관리할 필요가 없다. 면접에서 이 차이를 명확히 구분해야 한다.

### Q: Controller의 Reconciliation Loop란 무엇인가요?
**30초 답변**:
Reconciliation Loop는 현재 상태(Current State)를 관찰하고, 원하는 상태(Desired State)와 비교하여, 차이가 있으면 이를 해소하는 동작을 반복하는 패턴입니다. 선언적 관리(Declarative Management)의 핵심 메커니즘입니다.

**2분 답변**:
Kubernetes의 모든 컨트롤러는 "Observe → Diff → Act" 루프를 따릅니다. 예를 들어 Deployment에서 replicas를 3으로 선언하면, ReplicaSet Controller는 현재 Running 중인 Pod 수를 apiserver의 watch를 통해 관찰합니다. Pod가 2개뿐이라면 1개를 추가 생성하고, 4개라면 1개를 삭제합니다. 이 루프는 level-triggered 방식으로, 이벤트를 놓쳐도 현재 상태를 확인하여 수렴하기 때문에 edge-triggered 방식보다 안정적입니다. Informer 패턴을 사용하여 apiserver의 watch 이벤트를 로컬 캐시에 저장하고, work queue를 통해 처리합니다. 이 패턴은 Kubernetes Operator의 기반이기도 하며, CRD와 Custom Controller를 만들 때도 동일한 패턴을 따릅니다. Allganize에서 AI 모델 서빙 파이프라인을 Operator로 관리한다면, 이 Reconciliation Loop 패턴을 활용하게 됩니다.

**경험 연결**:
Node 장애 발생 시 Node Controller가 5분(기본 pod-eviction-timeout) 후에 해당 노드의 Pod를 다른 노드로 재스케줄링하는 것을 관찰한 경험이 있습니다. 이 타이밍을 조절하여 장애 복구 시간을 단축한 적이 있습니다.

**주의**:
"이벤트 기반"이라고만 답하면 부정확하다. Kubernetes 컨트롤러는 이벤트 + 주기적 재동기화(resync)를 결합한 level-triggered 방식이다.

---

## Allganize 맥락

- **EKS/AKS 환경**: Allganize는 AWS EKS와 Azure AKS를 사용하므로 Control Plane은 클라우드가 관리한다. 면접에서는 "관리형 서비스에서 Control Plane을 직접 운영하지 않지만, 내부 동작 원리를 이해하면 트러블슈팅에 큰 도움이 된다"는 관점을 보여주는 것이 중요하다.
- **AI 워크로드 특성**: LLM 서빙 Pod는 GPU 노드에 배치되어야 하므로, scheduler의 nodeSelector/affinity와 controller-manager의 reconciliation이 핵심이다. GPU 노드 장애 시 Node Controller의 eviction 동작과 scheduler의 재배치 로직을 이해해야 한다.
- **멀티 클러스터**: 여러 고객사에 서비스를 제공하는 SaaS 구조에서는 클러스터 간 apiserver 연동(Federation 또는 Cluster API)이 필요할 수 있다.
- **폐쇄망 경험 활용**: 온프레미스 폐쇄망에서의 Control Plane 운영 경험은 클라우드 환경에서도 장애 분석 시 큰 장점이 된다. "apiserver 로그에서 etcd timeout이 보이면 etcd 성능을 먼저 확인한다"는 수준의 트러블슈팅 역량을 어필할 수 있다.

---
**핵심 키워드**: `kube-apiserver` `etcd` `kube-scheduler` `kube-controller-manager` `leader-election` `reconciliation-loop` `HA-control-plane`
