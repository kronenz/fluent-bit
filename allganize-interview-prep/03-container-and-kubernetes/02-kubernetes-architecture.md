# 02. 쿠버네티스 아키텍처 (Kubernetes Architecture)

> **TL;DR**
> - K8s는 **Control Plane**(뇌)과 **Worker Node**(손발)로 구성된 분산 시스템이다.
> - 모든 상태는 **etcd**에 저장되고, 모든 통신은 **kube-apiserver**를 경유한다.
> - `kubectl apply` 한 줄이 실제 컨테이너가 되기까지 **6단계의 API 요청 흐름**을 거친다.

---

## 1. 전체 아키텍처 개요

```
┌─────────────────────── Control Plane ───────────────────────┐
│                                                              │
│  ┌──────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │   etcd   │  │ kube-apiserver │  │ controller-manager   │ │
│  │ (상태저장) │  │  (API 게이트웨이) │  │ (선언 상태 유지)     │ │
│  └──────────┘  └────────────────┘  └──────────────────────┘ │
│                                    ┌──────────────────────┐ │
│                                    │   kube-scheduler     │ │
│                                    │ (Pod 배치 결정)       │ │
│                                    └──────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                          │ API 통신
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌──── Worker Node 1 ────┐ ┌── Worker Node 2 ──┐ ┌── Worker Node N ──┐
│ kubelet               │ │ kubelet            │ │ kubelet            │
│ kube-proxy            │ │ kube-proxy         │ │ kube-proxy         │
│ container runtime     │ │ container runtime  │ │ container runtime  │
│ [Pod] [Pod] [Pod]     │ │ [Pod] [Pod]        │ │ [Pod] [Pod]        │
└───────────────────────┘ └────────────────────┘ └────────────────────┘
```

---

## 2. Control Plane 구성요소

### 2-1. etcd

**분산 키-값 저장소**로, 클러스터의 모든 상태를 저장한다.

| 특성 | 설명 |
|------|------|
| **합의 알고리즘** | Raft (과반수 노드 동의 필요) |
| **고가용성** | 홀수 개 노드 권장 (3, 5, 7) |
| **데이터** | Pod, Service, ConfigMap, Secret 등 모든 리소스 |
| **접근** | kube-apiserver만 직접 접근 |

```bash
# etcd 클러스터 상태 확인
ETCDCTL_API=3 etcdctl endpoint status \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  --write-out=table

# etcd 백업 (운영 필수)
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 백업 검증
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-20260403.db --write-out=table
```

**폐쇄망 운영 경험 연결:**
온프레미스 환경에서 etcd 백업은 **장애 복구의 핵심**이다. 정기적 스냅샷을 별도 스토리지에 보관하는 정책이 필수다.

### 2-2. kube-apiserver

클러스터의 **유일한 진입점**이다. 모든 구성요소는 apiserver를 통해서만 통신한다.

- **RESTful API** 제공 (`kubectl`도 HTTP 요청을 보내는 클라이언트)
- **인증(Authentication)** → **인가(Authorization, RBAC)** → **어드미션 컨트롤(Admission Control)** 순서로 요청 처리
- etcd와 직접 통신하는 **유일한 컴포넌트**

```bash
# apiserver에 직접 요청 (kubectl이 내부적으로 하는 일)
kubectl get --raw /api/v1/namespaces/default/pods | jq .

# apiserver 헬스체크
kubectl get --raw /healthz

# API 리소스 목록 확인
kubectl api-resources --sort-by=name

# 특정 리소스의 API 버전 확인
kubectl explain deployment.spec.strategy
```

### 2-3. kube-scheduler

**Pod를 어느 노드에 배치할지** 결정한다. 실제 Pod를 실행하지는 않는다.

**스케줄링 과정:**

1. **Filtering:** 조건에 맞지 않는 노드 제거 (리소스 부족, taint, affinity 불일치)
2. **Scoring:** 남은 노드에 점수를 매겨 최적 노드 선택
3. **Binding:** 선택된 노드를 Pod의 `spec.nodeName`에 기록

```yaml
# 스케줄링에 영향을 주는 설정 예시
apiVersion: v1
kind: Pod
metadata:
  name: gpu-pod
spec:
  containers:
  - name: ml-training
    image: pytorch/pytorch:latest
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
        nvidia.com/gpu: "1"     # GPU 리소스 요청
      limits:
        cpu: "4"
        memory: "8Gi"
        nvidia.com/gpu: "1"
  nodeSelector:
    disktype: ssd               # 라벨 기반 노드 선택
  tolerations:
  - key: "gpu"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"        # GPU 노드의 taint 허용
```

### 2-4. kube-controller-manager

**선언된 상태(Desired State)**와 **실제 상태(Current State)**를 지속적으로 비교하고 일치시키는 **제어 루프(Control Loop)** 모음이다.

| 컨트롤러 | 역할 |
|----------|------|
| **ReplicaSet Controller** | Pod 수를 replicas 값에 맞춤 |
| **Deployment Controller** | 롤링 업데이트, 롤백 관리 |
| **Node Controller** | 노드 상태 모니터링, NotReady 처리 |
| **Job Controller** | 배치 작업 완료 관리 |
| **EndpointSlice Controller** | Service와 Pod 연결 |

```
선언: replicas: 3
현재: Pod 2개 실행 중
→ Controller가 1개 추가 생성 요청
```

---

## 3. Worker Node 구성요소

### 3-1. kubelet

각 노드에서 **Pod의 실제 실행을 관리**하는 에이전트다.

- apiserver로부터 **PodSpec**을 받아 컨테이너 런타임에 전달
- **컨테이너 상태 모니터링** 및 apiserver에 보고
- **Liveness/Readiness Probe** 실행
- **Static Pod** 관리 (`/etc/kubernetes/manifests/`)

```bash
# kubelet 상태 확인
sudo systemctl status kubelet

# kubelet 로그 확인 (문제 진단)
sudo journalctl -u kubelet -f --no-pager | tail -50

# 노드의 kubelet 설정 확인
kubectl get --raw /api/v1/nodes/<node-name>/proxy/configz | jq .
```

### 3-2. kube-proxy

**Service의 네트워크 규칙**을 각 노드에서 구현한다.

| 모드 | 특징 |
|------|------|
| **iptables** (기본) | 규칙 기반, 대규모에서 성능 저하 |
| **IPVS** | 해시 테이블 기반, 대규모 서비스에 적합 |
| **nftables** | 차세대, K8s 1.29+ |

```bash
# kube-proxy 모드 확인
kubectl get configmap kube-proxy -n kube-system -o yaml | grep mode

# iptables 규칙 확인
sudo iptables -t nat -L KUBE-SERVICES | head -20

# IPVS 규칙 확인 (IPVS 모드일 때)
sudo ipvsadm -Ln
```

### 3-3. Container Runtime

kubelet이 **CRI (Container Runtime Interface)**를 통해 호출하는 컨테이너 실행 엔진이다.

```bash
# containerd 소켓으로 런타임 정보 확인
sudo crictl --runtime-endpoint unix:///run/containerd/containerd.sock info

# 실행 중인 컨테이너 목록
sudo crictl ps

# 컨테이너 로그 확인
sudo crictl logs <container-id>
```

---

## 4. API 요청 흐름: kubectl apply부터 Pod 실행까지

`kubectl apply -f deployment.yaml` 하나가 어떤 과정을 거치는지 단계별로 살펴본다.

```
Step 1: kubectl이 YAML을 HTTP POST로 apiserver에 전송
         ↓
Step 2: apiserver가 인증 → 인가(RBAC) → Admission Control 수행
         ↓
Step 3: apiserver가 Deployment 객체를 etcd에 저장
         ↓
Step 4: Deployment Controller가 변경 감지 → ReplicaSet 생성
         ↓
Step 5: Scheduler가 미배정 Pod 감지 → 최적 노드 선택 → nodeName 기록
         ↓
Step 6: 해당 노드의 kubelet이 변경 감지 → containerd로 컨테이너 실행
```

```bash
# 이 과정을 실시간으로 관찰하기
# 터미널 1: 이벤트 모니터링
kubectl get events --watch

# 터미널 2: Deployment 생성
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-demo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx-demo
  template:
    metadata:
      labels:
        app: nginx-demo
    spec:
      containers:
      - name: nginx
        image: nginx:1.25
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "200m"
            memory: "256Mi"
EOF

# 터미널 3: Pod 생성 과정 추적
kubectl get pods -w

# 상세 이벤트 확인
kubectl describe deployment nginx-demo
kubectl describe pod nginx-demo-<hash>
```

**Watch 메커니즘:** 각 컴포넌트는 apiserver에 **Watch 요청**을 보내고, 변경이 생기면 즉시 알림을 받는다. 폴링이 아니라 **이벤트 드리븐**이다.

---

## 5. 고가용성 (High Availability) 구성

온프레미스에서 프로덕션 클러스터는 **HA 구성이 필수**다.

```
              ┌─── Load Balancer (HAProxy/keepalived) ───┐
              │                                           │
     ┌────────┴────────┐  ┌──────────────┐  ┌───────────┴──────┐
     │ Master 1        │  │ Master 2     │  │ Master 3         │
     │ apiserver       │  │ apiserver    │  │ apiserver        │
     │ controller-mgr  │  │ (standby)    │  │ (standby)        │
     │ scheduler       │  │ controller   │  │ controller       │
     │ etcd            │  │ etcd         │  │ etcd             │
     └─────────────────┘  └──────────────┘  └──────────────────┘
```

```bash
# kubeadm으로 HA 클러스터 초기화 (첫 번째 마스터)
sudo kubeadm init \
  --control-plane-endpoint "lb.example.com:6443" \
  --upload-certs \
  --pod-network-cidr=10.244.0.0/16

# 추가 마스터 노드 조인
sudo kubeadm join lb.example.com:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <cert-key>
```

**폐쇄망 HA 경험 연결:**
인터넷이 없으므로 **모든 컨테이너 이미지를 사전에 내부 레지스트리에 적재**해야 한다. `kubeadm config images list`로 필요한 이미지 목록을 확인하고, `kubeadm init --config`에서 `imageRepository`를 내부 레지스트리로 지정한다.

---

## 면접 Q&A

### Q1. "Kubernetes의 전체 아키텍처를 설명해주세요."

> **이렇게 대답한다:**
> "K8s는 **Control Plane과 Worker Node**로 구성됩니다. Control Plane에는 유일한 저장소인 **etcd**, 모든 통신의 관문인 **kube-apiserver**, Pod 배치를 결정하는 **scheduler**, 선언 상태를 유지하는 **controller-manager**가 있습니다. Worker Node에는 컨테이너 실행을 담당하는 **kubelet**, 서비스 네트워킹을 구현하는 **kube-proxy**, 그리고 **container runtime**이 있습니다. 핵심은 **선언적(Declarative) 모델**로, 원하는 상태를 정의하면 컨트롤러가 지속적으로 실제 상태를 맞춰줍니다."

### Q2. "etcd가 죽으면 어떻게 되나요?"

> **이렇게 대답한다:**
> "etcd는 클러스터의 **모든 상태를 저장**하는 유일한 저장소이므로, etcd가 죽으면 새로운 리소스 생성이나 변경이 불가능합니다. 다만 이미 실행 중인 Pod는 **kubelet이 독립적으로 관리**하므로 즉시 죽지는 않습니다. 프로덕션에서는 반드시 **홀수 개(3 또는 5)의 etcd 노드**로 HA를 구성하고, **정기적 스냅샷 백업**을 수행합니다. 온프레미스에서는 etcd 전용 SSD 디스크를 할당하여 I/O 지연을 최소화하는 것도 중요합니다."

### Q3. "kubectl apply를 하면 내부적으로 어떤 일이 벌어지나요?"

> **이렇게 대답한다:**
> "크게 6단계입니다. kubectl이 YAML을 HTTP 요청으로 **apiserver에 전송**하면, apiserver가 **인증-인가-어드미션 컨트롤**을 거쳐 etcd에 저장합니다. **Deployment Controller**가 변경을 감지하여 ReplicaSet을 생성하고, **Scheduler**가 미배정 Pod를 감지하여 최적 노드를 선택합니다. 최종적으로 해당 노드의 **kubelet**이 containerd를 통해 컨테이너를 실행합니다. 이 모든 통신은 Watch 메커니즘으로 **이벤트 드리븐**하게 동작합니다."

### Q4. "온프레미스에서 K8s 클러스터를 구축한 경험이 있나요?"

> **이렇게 대답한다:**
> "폐쇄망 환경에서 **kubeadm으로 HA 클러스터를 구축**한 경험이 있습니다. 인터넷이 안 되므로 필요한 이미지를 사전에 내부 레지스트리에 적재하고, HAProxy+keepalived로 **apiserver 로드밸런서**를 구성했습니다. etcd는 전용 SSD에 배치하고, **정기 백업 스크립트를 cron으로 자동화**했습니다. 클라우드와 달리 네트워크, 스토리지, 인증서 관리를 모두 직접 해야 하므로 **인프라 전반에 대한 이해**가 중요했습니다."

---

`#ControlPlane` `#etcd` `#kube-apiserver` `#kubelet` `#API요청흐름`
