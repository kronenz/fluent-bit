# 컨테이너 런타임 (Container Runtime)

> **TL;DR**
> - 컨테이너 런타임은 **High-Level(containerd, CRI-O)**과 **Low-Level(runc, crun)**로 나뉘며, OCI 표준으로 호환된다.
> - Kubernetes 1.24부터 **dockershim 제거** -- containerd 또는 CRI-O가 사실상 표준이다.
> - runc는 OCI Runtime Spec을 구현한 **레퍼런스 런타임**으로, 실제 namespace/cgroup을 생성한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### 1. 런타임 계층 구조

컨테이너 런타임은 두 계층으로 분리된다. High-Level Runtime은 이미지 관리, 네트워크 설정, CRI 인터페이스를 담당하고, Low-Level Runtime은 실제 커널 수준의 격리(namespace, cgroup)를 수행한다.

```
┌──────────────────────────────────────────────────────┐
│                   kubelet (K8s Node)                  │
│                        │                             │
│                   CRI (gRPC)                         │
│                        │                             │
├────────────┬───────────┴───────────┬─────────────────┤
│ containerd │                       │     CRI-O       │
│ (High-Lv)  │                       │    (High-Lv)    │
├────────────┴───────────────────────┴─────────────────┤
│              OCI Runtime Spec (config.json)           │
├──────────────────────────────────────────────────────┤
│         runc / crun / kata-runtime (Low-Level)       │
│         → namespace, cgroup, seccomp, pivot_root     │
└──────────────────────────────────────────────────────┘
```

### 2. CRI (Container Runtime Interface)

CRI는 kubelet과 컨테이너 런타임 사이의 **gRPC 프로토콜**이다. 두 개의 서비스로 구성된다.

```
CRI = RuntimeService + ImageService

RuntimeService:
  - RunPodSandbox()    → Pod 네트워크 네임스페이스 생성
  - CreateContainer()  → 컨테이너 생성
  - StartContainer()   → 컨테이너 시작
  - StopContainer()    → 컨테이너 정지
  - RemoveContainer()  → 컨테이너 삭제

ImageService:
  - PullImage()        → 이미지 다운로드
  - ListImages()       → 이미지 목록
  - RemoveImage()      → 이미지 삭제
```

### 3. OCI (Open Container Initiative) 표준

OCI는 컨테이너 생태계의 **호환성 표준**이다. 두 가지 스펙을 정의한다.

| 스펙 | 역할 | 핵심 산출물 |
|------|------|------------|
| **OCI Image Spec** | 이미지 포맷 정의 | manifest.json, layer tar |
| **OCI Runtime Spec** | 컨테이너 실행 방법 정의 | config.json (namespace, cgroup 등) |
| **OCI Distribution Spec** | 레지스트리 API 표준 | Push/Pull HTTP API |

OCI 덕분에 Docker로 빌드한 이미지를 containerd나 CRI-O에서 그대로 실행할 수 있다.

### 4. containerd vs CRI-O vs Docker 비교

```
┌──────────────────────────────────────────────────────────┐
│                        Docker                            │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ docker  │→│ dockerd  │→│containerd│→│  runc    │  │
│  │  CLI    │  │ (daemon) │  │          │  │          │  │
│  └─────────┘  └──────────┘  └──────────┘  └──────────┘  │
│   빌드+관리      API서버       런타임관리      실제실행    │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────┐
│         containerd (독립)         │
│  ┌──────────┐    ┌──────────┐   │
│  │containerd│ →  │  runc    │   │
│  │ + CRI    │    │          │   │
│  └──────────┘    └──────────┘   │
│  kubelet에서 직접 gRPC 연결      │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│           CRI-O                  │
│  ┌──────────┐    ┌──────────┐   │
│  │  CRI-O   │ →  │  runc    │   │
│  │ (K8s전용) │    │          │   │
│  └──────────┘    └──────────┘   │
│  K8s만을 위해 설계, 최소 기능     │
└──────────────────────────────────┘
```

| 항목 | Docker | containerd | CRI-O |
|------|--------|-----------|-------|
| **목적** | 개발자 도구 (빌드+실행) | 범용 컨테이너 런타임 | K8s 전용 경량 런타임 |
| **CRI 지원** | dockershim (1.24 제거) | CRI 플러그인 내장 | 네이티브 CRI |
| **이미지 빌드** | `docker build` | BuildKit 별도 | Buildah/Podman 별도 |
| **대표 사용처** | 개발 환경, CI | EKS, AKS, GKE 기본 | OpenShift (Red Hat) |
| **프로세스 수** | 3개 (cli+dockerd+containerd) | 1개 (containerd) | 1개 (crio) |
| **메모리 오버헤드** | 높음 | 중간 | 낮음 |

### 5. runc -- OCI 레퍼런스 런타임

runc는 Docker에서 분리되어 OCI에 기증된 **Low-Level 런타임**이다. 실제로 Linux 커널의 clone(), unshare(), pivot_root() 등 시스템콜을 호출하여 컨테이너를 생성한다.

```
runc create → clone(CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWNET ...)
            → pivot_root(new_root, put_old)
            → cgroup에 프로세스 등록
            → seccomp 필터 적용
            → execve(entrypoint)
```

| Low-Level 런타임 | 특징 |
|------------------|------|
| **runc** | OCI 레퍼런스 구현, Go 언어, 가장 널리 사용 |
| **crun** | C 언어 구현, runc 대비 ~50% 빠른 시작 시간 |
| **kata-runtime** | 경량 VM 내부에서 실행, 커널 격리 제공 |
| **gVisor (runsc)** | 사용자 공간 커널로 시스템콜 인터셉트 |

---

## 실전 예시

### 런타임 확인 및 관리

```bash
# 노드의 컨테이너 런타임 확인
kubectl get nodes -o wide
# CONTAINER-RUNTIME 컬럼에 containerd://1.7.x 또는 cri-o://1.28.x 표시

# containerd 상태 확인
sudo systemctl status containerd
sudo journalctl -u containerd --since "10 minutes ago"

# containerd 설정 파일 확인
cat /etc/containerd/config.toml

# CRI-O 상태 확인
sudo systemctl status crio
sudo crictl --runtime-endpoint unix:///var/run/crio/crio.sock info
```

### crictl -- CRI 디버깅 CLI

```bash
# crictl 설정 (containerd 기준)
cat <<EOF | sudo tee /etc/crictl.yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
timeout: 10
debug: false
EOF

# 컨테이너 목록
sudo crictl ps

# 파드 샌드박스 목록
sudo crictl pods

# 이미지 목록
sudo crictl images

# 컨테이너 로그
sudo crictl logs <container-id>

# 컨테이너 내부 실행
sudo crictl exec -it <container-id> /bin/sh

# 이미지 Pull (폐쇄망에서 내부 레지스트리 사용)
sudo crictl pull harbor.internal.corp/base/alpine:3.19
```

### runc 직접 사용 (디버깅/학습)

```bash
# OCI 번들 준비
mkdir -p mycontainer/rootfs
cd mycontainer

# 루트 파일시스템 준비 (Alpine 기반)
docker export $(docker create alpine:3.19) | tar -C rootfs -xf -

# OCI config.json 생성
runc spec

# config.json 편집 후 실행
runc create test-container
runc start test-container
runc list
runc delete test-container
```

### containerd에서 런타임 클래스 설정 (Kata/gVisor)

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata]
  runtime_type = "io.containerd.kata.v2"

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.gvisor]
  runtime_type = "io.containerd.runsc.v1"
```

```yaml
# Kubernetes RuntimeClass 정의
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
---
# Pod에서 사용
apiVersion: v1
kind: Pod
metadata:
  name: secure-pod
spec:
  runtimeClassName: kata    # Kata Containers로 실행
  containers:
  - name: app
    image: harbor.internal.corp/myapp/backend:v1.0.0
```

---

## 면접 Q&A

### Q1: "containerd와 CRI-O의 차이를 설명해주세요."

**30초 답변**:
"containerd는 Docker에서 분리된 범용 런타임으로 EKS, AKS, GKE의 기본 런타임입니다. CRI-O는 Kubernetes만을 위해 설계된 경량 런타임으로 OpenShift에서 기본 사용됩니다. 둘 다 CRI를 구현하고 runc를 Low-Level 런타임으로 사용하므로, 애플리케이션 관점에서 동작 차이는 없습니다."

**2분 답변**:
"containerd는 원래 Docker 내부 컴포넌트였다가 CNCF에 기증되어 독립 프로젝트가 되었습니다. 범용 목적으로 설계되어 Kubernetes 외에도 단독으로 사용할 수 있고, BuildKit과 연동하여 이미지 빌드도 가능합니다. 반면 CRI-O는 Red Hat이 주도하여 Kubernetes CRI만을 구현하는 최소 런타임입니다. K8s 버전과 릴리스 주기를 맞추고, 불필요한 기능을 제거하여 공격 표면을 줄였습니다. 선택 기준은 주로 플랫폼에 따릅니다. 퍼블릭 클라우드 매니지드 K8s는 대부분 containerd, OpenShift는 CRI-O입니다. Allganize처럼 AWS EKS와 Azure AKS를 사용하는 환경이라면 containerd가 기본이며, 별도 런타임 설정 없이 사용하게 됩니다."

**경험 연결**:
"온프레미스 환경에서 Docker 기반 K8s를 운영하다가 1.24 업그레이드 시 containerd로 전환한 경험이 있습니다. `crictl`로 기존 `docker` CLI 워크플로를 대체하고, /etc/containerd/config.toml에서 프라이빗 레지스트리 미러 설정을 추가했습니다."

**주의**:
dockershim 제거는 Docker로 빌드한 이미지를 못 쓴다는 뜻이 아니다. OCI 표준 이미지는 어떤 런타임에서든 실행 가능하다.

### Q2: "OCI 표준이 왜 중요한가요?"

**30초 답변**:
"OCI는 이미지 포맷과 런타임 실행 방식을 표준화하여, Docker로 빌드한 이미지를 containerd, CRI-O, Podman 등 어떤 런타임에서든 실행할 수 있게 합니다. 벤더 종속(vendor lock-in)을 방지하는 핵심 표준입니다."

**2분 답변**:
"OCI에는 세 가지 스펙이 있습니다. Image Spec은 이미지의 레이어 구조와 매니페스트 형식을 정의합니다. Runtime Spec은 config.json을 통해 namespace, cgroup, mount 등 컨테이너 실행 환경을 정의합니다. Distribution Spec은 레지스트리와의 Push/Pull API를 표준화합니다. 이 덕분에 Docker Hub, Harbor, ECR, ACR 등 어떤 레지스트리에서든 동일한 방식으로 이미지를 주고받을 수 있습니다. 폐쇄망 환경에서 skopeo로 레지스트리 간 이미지를 복사하거나, Harbor에서 ECR로 이미지를 복제할 때도 OCI 호환성 덕분에 가능합니다."

**경험 연결**:
"폐쇄망에서 다양한 벤더의 어플라이언스를 운영할 때, OCI 호환 이미지 형식 덕분에 단일 내부 레지스트리(Harbor)에서 모든 이미지를 통합 관리할 수 있었습니다."

**주의**:
Docker 이미지 포맷 v2와 OCI 이미지 포맷은 거의 동일하지만 미디어 타입이 다르다. 대부분의 도구가 둘 다 지원하므로 실무에서 문제가 되는 경우는 드물다.

### Q3: "runc와 Kata Containers의 차이는 무엇이고, 언제 Kata를 쓰나요?"

**30초 답변**:
"runc는 호스트 커널을 공유하는 일반 컨테이너를 만들고, Kata Containers는 경량 VM 안에서 컨테이너를 실행하여 커널 수준 격리를 제공합니다. 멀티테넌트 환경이나 신뢰할 수 없는 코드 실행 시 Kata를 사용합니다."

**2분 답변**:
"runc는 namespace와 cgroup으로 프로세스를 격리하지만, 호스트 커널을 공유합니다. 커널 취약점(예: CVE-2024-21626 runc 탈출)이 곧 컨테이너 탈출로 이어질 수 있습니다. Kata Containers는 QEMU/Cloud Hypervisor로 경량 VM을 만들고 그 안에서 컨테이너를 실행하여 **커널까지 격리**합니다. 시작 시간이 runc보다 200-300ms 정도 느리지만, 보안이 크게 강화됩니다. Allganize처럼 LLM 서비스를 운영하는 환경에서, 사용자 입력을 직접 처리하는 컨테이너(예: 코드 실행 샌드박스)에는 Kata를 적용하고, 내부 마이크로서비스에는 runc를 사용하는 혼합 전략이 적합합니다. Kubernetes의 RuntimeClass를 통해 Pod 단위로 런타임을 선택할 수 있습니다."

**경험 연결**:
"보안등급이 높은 온프레미스 환경에서 컨테이너 도입 시, 커널 공유에 대한 보안 심사 이슈가 있었습니다. gVisor나 Kata 같은 샌드박스 런타임으로 커널 격리를 확보하면 보안 승인이 수월해집니다."

**주의**:
Kata는 중첩 가상화(nested virtualization)가 필요하므로, 클라우드 VM 위에서 실행하려면 베어메탈 인스턴스나 중첩 가상화 지원 인스턴스가 필요하다.

### Q4: "Kubernetes에서 Docker를 못 쓰게 된 이유와 대응 방법은?"

**30초 답변**:
"K8s 1.24에서 dockershim이 제거되어 Docker를 CRI 런타임으로 직접 사용할 수 없게 되었습니다. Docker 내부의 containerd를 직접 CRI로 연결하면 되며, Docker로 빌드한 이미지는 OCI 호환이므로 그대로 사용 가능합니다."

**2분 답변**:
"원래 kubelet은 dockershim이라는 어댑터를 통해 Docker와 통신했습니다. 하지만 이 구조는 kubelet → dockershim → dockerd → containerd → runc로 호출 체인이 길어 오버헤드가 있었습니다. containerd를 직접 연결하면 kubelet → containerd → runc로 단순해집니다. 마이그레이션 시 주의할 점은 세 가지입니다. 첫째, docker CLI 대신 crictl을 사용해야 합니다. 둘째, /etc/containerd/config.toml에서 프라이빗 레지스트리 인증 설정을 별도로 해야 합니다. 셋째, Docker 소켓(/var/run/docker.sock)에 의존하는 CI/CD 파이프라인이나 모니터링 도구를 수정해야 합니다. 이미지 빌드는 Kaniko(클러스터 내)나 BuildKit(CI 서버)으로 대체합니다."

**경험 연결**:
"폐쇄망 K8s 클러스터를 1.23에서 1.24로 업그레이드할 때, Docker에서 containerd로 런타임을 전환한 경험이 있습니다. 사전에 crictl로 기능 검증을 하고, 레지스트리 미러 설정과 인증 설정을 containerd config에 반영하는 것이 핵심이었습니다."

**주의**:
docker build는 여전히 개발 환경에서 유효하다. 제거된 것은 K8s가 Docker를 런타임으로 쓰는 것이지, Docker 자체가 아니다.

---

## Allganize 맥락

- **EKS/AKS 기본 런타임**: Allganize가 사용하는 AWS EKS와 Azure AKS는 containerd가 기본 런타임이다. 별도 런타임 설정 없이 클러스터가 프로비저닝된다.
- **LLM 서비스와 런타임 선택**: Alli AI의 추론(inference) 워크로드는 GPU 노드에서 실행되며, GPU 컨테이너는 NVIDIA Container Runtime이 runc를 감싸는 형태로 동작한다. containerd 설정에서 nvidia-container-runtime을 등록해야 한다.
- **이미지 빌드**: K8s 클러스터에서 Docker 소켓 없이 이미지를 빌드하려면 Kaniko(CI/CD 파이프라인)를 사용한다. GitHub Actions나 Jenkins에서는 BuildKit을 활용한다.
- **보안 강화**: 멀티테넌트 SaaS 환경에서 고객 데이터를 처리하는 Pod에는 RuntimeClass를 통해 gVisor나 Kata를 적용하여 추가 격리를 확보할 수 있다.

---
**핵심 키워드**: `containerd` `CRI-O` `runc` `OCI` `dockershim` `RuntimeClass` `crictl`
