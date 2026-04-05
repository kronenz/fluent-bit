# GPU 리소스 관리

> **TL;DR**: NVIDIA GPU Operator로 K8s GPU 스택을 자동 관리하고, nvidia-device-plugin으로 GPU를 Pod에 할당한다.
> MIG/Time-Slicing으로 GPU를 분할 공유하여 비용을 절감하고, dcgm-exporter로 GPU 메트릭을 수집한다.
> AI 서비스 운영에서 GPU는 가장 비싸고 희소한 리소스이므로 효율적 관리가 핵심이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 1. Kubernetes GPU 스택 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                   Kubernetes Cluster                 │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │            NVIDIA GPU Operator                │   │
│  │  (모든 GPU 컴포넌트를 자동 배포/관리)           │   │
│  │                                               │   │
│  │  ┌─────────────┐  ┌──────────────────────┐   │   │
│  │  │ NVIDIA      │  │ nvidia-device-plugin │   │   │
│  │  │ Driver      │  │ (GPU를 K8s 리소스로  │   │   │
│  │  │ (컨테이너화) │  │  등록/할당)          │   │   │
│  │  └─────────────┘  └──────────────────────┘   │   │
│  │                                               │   │
│  │  ┌─────────────┐  ┌──────────────────────┐   │   │
│  │  │ NVIDIA      │  │ dcgm-exporter        │   │   │
│  │  │ Container   │  │ (GPU 메트릭 →        │   │   │
│  │  │ Toolkit     │  │  Prometheus 형식)     │   │   │
│  │  └─────────────┘  └──────────────────────┘   │   │
│  │                                               │   │
│  │  ┌─────────────┐  ┌──────────────────────┐   │   │
│  │  │ GPU Feature │  │ MIG Manager          │   │   │
│  │  │ Discovery   │  │ (MIG 파티션 관리)     │   │   │
│  │  └─────────────┘  └──────────────────────┘   │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              GPU Hardware                     │   │
│  │  [GPU 0] [GPU 1] [GPU 2] [GPU 3]            │   │
│  │  A100    A100    A100    A100                │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 2. NVIDIA GPU Operator

GPU Operator는 Helm chart 하나로 전체 GPU 소프트웨어 스택을 배포/관리한다.

```bash
# GPU Operator 설치
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

helm install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator \
  --create-namespace \
  --set driver.enabled=true \
  --set toolkit.enabled=true \
  --set devicePlugin.enabled=true \
  --set dcgmExporter.enabled=true \
  --set migManager.enabled=true \
  --set gfd.enabled=true
```

**GPU Operator가 관리하는 컴포넌트**:

| 컴포넌트 | 역할 | DaemonSet |
|---------|------|-----------|
| NVIDIA Driver | GPU 드라이버 (컨테이너화) | nvidia-driver-daemonset |
| Container Toolkit | 컨테이너 런타임 GPU 연동 | nvidia-container-toolkit |
| Device Plugin | GPU를 K8s 리소스로 등록 | nvidia-device-plugin |
| DCGM Exporter | GPU 메트릭 수집/노출 | dcgm-exporter |
| GPU Feature Discovery | GPU 특성을 Node label로 등록 | gpu-feature-discovery |
| MIG Manager | MIG 파티션 관리 | nvidia-mig-manager |

### 3. nvidia-device-plugin 상세

```
nvidia-device-plugin 동작 흐름

1. 노드의 GPU를 탐지
2. kubelet에 nvidia.com/gpu 리소스 등록
3. Pod 스케줄링 시 GPU 할당

Node Status:
  Capacity:
    nvidia.com/gpu: 4          ← 물리 GPU 4장
  Allocatable:
    nvidia.com/gpu: 4

Pod Spec:
  containers:
  - resources:
      limits:
        nvidia.com/gpu: 1      ← GPU 1장 요청
```

```yaml
# GPU를 사용하는 Pod 예시
apiVersion: v1
kind: Pod
metadata:
  name: llm-inference
spec:
  containers:
  - name: vllm
    image: vllm/vllm-openai:latest
    resources:
      limits:
        nvidia.com/gpu: 2        # A100 2장 할당
    env:
    - name: NVIDIA_VISIBLE_DEVICES
      value: "all"
    - name: CUDA_VISIBLE_DEVICES
      value: "0,1"
    volumeMounts:
    - name: model-storage
      mountPath: /models
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
  nodeSelector:
    nvidia.com/gpu.product: NVIDIA-A100-SXM4-80GB
```

### 4. GPU 공유: MIG (Multi-Instance GPU)

MIG는 A100/H100 GPU를 물리적으로 분할하여 독립된 GPU 인스턴스를 만든다.

```
A100 80GB - MIG 파티션 예시

┌─────────────────────────────────────────────┐
│                  A100 80GB                   │
├─────────────────────────────────────────────┤
│ 프로파일 1: 7개 동일 파티션                    │
│ ┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐│
│ │1g.  ││1g.  ││1g.  ││1g.  ││1g.  ││1g.  ││1g.  ││
│ │10gb ││10gb ││10gb ││10gb ││10gb ││10gb ││10gb ││
│ └─────┘└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘│
├─────────────────────────────────────────────┤
│ 프로파일 2: 혼합 파티션                        │
│ ┌───────────┐┌───────────┐┌─────────────────┐│
│ │ 2g.20gb   ││ 2g.20gb   ││    3g.40gb      ││
│ │           ││           ││                 ││
│ └───────────┘└───────────┘└─────────────────┘│
├─────────────────────────────────────────────┤
│ 프로파일 3: 대형 파티션                        │
│ ┌─────────────────────┐┌────────────────────┐│
│ │     4g.40gb         ││     3g.40gb        ││
│ │                     ││                    ││
│ └─────────────────────┘└────────────────────┘│
└─────────────────────────────────────────────┘
```

**MIG 프로파일 종류 (A100 80GB)**:

| 프로파일 | GPU SM | Memory | 최대 인스턴스 수 |
|---------|--------|--------|---------------|
| 1g.10gb | 1/7 | 10GB | 7 |
| 2g.20gb | 2/7 | 20GB | 3 |
| 3g.40gb | 3/7 | 40GB | 2 |
| 4g.40gb | 4/7 | 40GB | 1 |
| 7g.80gb | 7/7 | 80GB | 1 |

```yaml
# MIG 설정 (ConfigMap으로 관리)
apiVersion: v1
kind: ConfigMap
metadata:
  name: mig-parted-config
  namespace: gpu-operator
data:
  config.yaml: |
    version: v1
    mig-configs:
      all-1g.10gb:
        - device-filter: ["0x20B210DE"]    # A100
          devices: all
          mig-enabled: true
          mig-devices:
            "1g.10gb": 7
      mixed-inference:
        - device-filter: ["0x20B210DE"]
          devices: all
          mig-enabled: true
          mig-devices:
            "3g.40gb": 1                    # 대형 모델용
            "2g.20gb": 2                    # 중형 모델용
```

### 5. GPU 공유: Time-Slicing

Time-Slicing은 시간 분할 방식으로 GPU를 공유한다. MIG와 달리 모든 GPU에서 사용 가능.

```
Time-Slicing 동작 원리

시간 →  ┌────┐┌────┐┌────┐┌────┐┌────┐┌────┐
GPU 0:  │Pod1││Pod2││Pod3││Pod1││Pod2││Pod3│  (라운드 로빈)
        └────┘└────┘└────┘└────┘└────┘└────┘

⚠️ 메모리 격리 없음: 각 Pod가 전체 GPU 메모리에 접근 가능
⚠️ OOM 위험: Pod들의 총 메모리 사용량이 GPU 메모리를 초과하면 crash
```

```yaml
# Time-Slicing 설정
apiVersion: v1
kind: ConfigMap
metadata:
  name: device-plugin-config
  namespace: gpu-operator
data:
  config.yaml: |
    version: v1
    sharing:
      timeSlicing:
        renameByDefault: false
        failRequestsGreaterThanOne: false
        resources:
        - name: nvidia.com/gpu
          replicas: 4                    # GPU 1장을 4개로 분할
```

**MIG vs Time-Slicing 비교**:

| 특성 | MIG | Time-Slicing |
|------|-----|-------------|
| 격리 수준 | 하드웨어 격리 (완전) | 소프트웨어 (시간 분할) |
| 메모리 격리 | 완전 격리 | 없음 (공유) |
| 지원 GPU | A100, H100만 | 모든 NVIDIA GPU |
| 파티션 유연성 | 고정 프로파일 | replicas 수 자유 |
| 성능 예측성 | 높음 (보장됨) | 낮음 (경합 발생) |
| 적합 워크로드 | 프로덕션 추론 | 개발/테스트, 경량 추론 |

### 6. dcgm-exporter (GPU 메트릭 모니터링)

```
dcgm-exporter → Prometheus → Grafana

수집 메트릭:
┌────────────────────────┬──────────────────────────────┐
│ 메트릭                  │ 설명                          │
├────────────────────────┼──────────────────────────────┤
│ DCGM_FI_DEV_GPU_UTIL   │ GPU 연산 유닛 사용률 (%)      │
│ DCGM_FI_DEV_MEM_COPY_UTIL │ 메모리 복사 유닛 사용률    │
│ DCGM_FI_DEV_FB_USED    │ Framebuffer 메모리 사용량     │
│ DCGM_FI_DEV_FB_FREE    │ Framebuffer 메모리 여유량     │
│ DCGM_FI_DEV_GPU_TEMP   │ GPU 온도 (°C)                │
│ DCGM_FI_DEV_POWER_USAGE│ GPU 전력 사용량 (W)           │
│ DCGM_FI_DEV_SM_CLOCK   │ SM 클럭 속도 (MHz)           │
│ DCGM_FI_DEV_PCIE_TX    │ PCIe 전송 바이트             │
│ DCGM_FI_DEV_PCIE_RX    │ PCIe 수신 바이트             │
│ DCGM_FI_DEV_XID_ERRORS │ XID 에러 (하드웨어 오류)      │
└────────────────────────┴──────────────────────────────┘
```

```yaml
# dcgm-exporter ServiceMonitor (Prometheus Operator)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: dcgm-exporter
  namespace: gpu-operator
spec:
  selector:
    matchLabels:
      app: nvidia-dcgm-exporter
  endpoints:
  - port: metrics
    interval: 15s
    path: /metrics
```

```bash
# GPU 상태 확인 명령어
# nvidia-smi 기본 확인
nvidia-smi

# 지속적 모니터링 (1초 간격)
nvidia-smi dmon -s pucvmet -d 1

# GPU 프로세스 확인
nvidia-smi pmon -d 1

# MIG 상태 확인
nvidia-smi mig -lgi     # GPU 인스턴스 목록
nvidia-smi mig -lci     # Compute 인스턴스 목록
```

---

## 실전 예시

### Grafana GPU 대시보드 PromQL

```bash
# GPU Utilization (클러스터 전체)
avg(DCGM_FI_DEV_GPU_UTIL{}) by (gpu, Hostname)

# GPU Memory 사용률
DCGM_FI_DEV_FB_USED / (DCGM_FI_DEV_FB_USED + DCGM_FI_DEV_FB_FREE) * 100

# GPU 온도 알림 (80도 초과)
DCGM_FI_DEV_GPU_TEMP > 80

# XID 에러 발생 감지 (하드웨어 문제)
increase(DCGM_FI_DEV_XID_ERRORS[5m]) > 0

# GPU Utilization이 낮은데 Pod가 할당된 경우 (비효율 탐지)
DCGM_FI_DEV_GPU_UTIL < 10
  and on(gpu, Hostname)
  kube_pod_container_resource_limits{resource="nvidia_com_gpu"} > 0
```

### GPU 노드 Taint/Toleration + Node Affinity

```yaml
# GPU 노드에 Taint 설정 (GPU 워크로드만 스케줄링)
kubectl taint nodes gpu-node-01 nvidia.com/gpu=present:NoSchedule

# GPU Pod에 Toleration + Node Affinity
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-inference
spec:
  template:
    spec:
      tolerations:
      - key: nvidia.com/gpu
        operator: Equal
        value: present
        effect: NoSchedule
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: nvidia.com/gpu.product
                operator: In
                values:
                - NVIDIA-A100-SXM4-80GB
                - NVIDIA-A100-SXM4-40GB
              - key: nvidia.com/mig.strategy
                operator: In
                values:
                - mixed
      containers:
      - name: inference
        resources:
          limits:
            nvidia.com/gpu: 1
```

---

## 면접 Q&A

### Q1: MIG와 Time-Slicing의 차이를 설명하고, 어떤 상황에서 각각을 선택합니까?

**30초 답변**:
MIG는 A100/H100에서 GPU를 하드웨어 수준으로 분할하여 완전한 격리를 제공합니다. Time-Slicing은 모든 GPU에서 사용 가능하지만 시간 분할 방식이라 메모리 격리가 없습니다. 프로덕션 추론에는 MIG, 개발/테스트에는 Time-Slicing을 사용합니다.

**2분 답변**:
MIG(Multi-Instance GPU):
- A100/H100 전용. GPU의 SM(Streaming Multiprocessor)과 메모리를 물리적으로 분할.
- 각 파티션이 독립된 GPU처럼 동작 (자체 메모리 컨트롤러, 캐시, SM).
- 장점: 성능 보장(QoS), 완전 격리, OOM이 다른 파티션에 영향 없음.
- 단점: 파티션 크기가 고정 프로파일로 제한, 변경 시 GPU 리셋 필요.

Time-Slicing:
- 모든 NVIDIA GPU 지원. CUDA Time-Slicing으로 컨텍스트 스위칭.
- 장점: 설정 간단, 파티션 수 자유, GPU 기종 제한 없음.
- 단점: 메모리 격리 없음, 성능 보장 없음, GPU 메모리 초과 시 전체 crash.

선택 기준:
- 프로덕션 LLM inference → MIG (3g.40gb or 4g.40gb): 성능 예측성 필수
- 개발/테스트 환경 → Time-Slicing (replicas: 4): 비용 절감 우선
- 소형 모델 다수 서빙 → MIG (1g.10gb x 7): 격리된 소형 인스턴스
- T4/V100 환경 → Time-Slicing (MIG 미지원)

**💡 경험 연결**:
"AI 데이터센터 구축 시 GPU 리소스 효율화가 가장 큰 과제였습니다. 고가의 A100을 한 워크로드가 독점하면 비용 효율이 떨어지므로, MIG로 분할하여 여러 추론 서비스가 공유하는 방안을 검토했습니다."

**⚠️ 주의**: MIG 파티션 변경 시 해당 GPU의 모든 워크로드가 중단된다. 운영 중 변경은 drain 후 진행해야 한다.

---

### Q2: GPU Operator를 사용하는 이점은 무엇이며, 없이 GPU를 관리하면 어떤 문제가 있나요?

**30초 답변**:
GPU Operator 없이는 각 노드에 NVIDIA 드라이버를 수동 설치하고, device-plugin, container toolkit, dcgm-exporter를 개별 배포해야 합니다. 드라이버 버전 불일치, 노드 추가 시 수동 작업, 업그레이드 조율이 운영 부담이 됩니다. GPU Operator는 이 모든 것을 DaemonSet으로 자동 관리합니다.

**2분 답변**:
GPU Operator 도입 전 수동 관리의 문제:
1. 노드마다 NVIDIA 드라이버 버전이 달라질 수 있음 (커널 호환성 문제)
2. 새 노드 추가 시 AMI에 드라이버를 bake하거나 ansible로 설치 필요
3. 드라이버 업그레이드 시 모든 노드를 순차 작업 (수일 소요)
4. device-plugin, toolkit, dcgm-exporter 버전 조합 관리 복잡

GPU Operator 이점:
- **Day-0**: Helm install 한번으로 전체 스택 배포
- **Day-1**: 새 노드가 클러스터에 조인하면 자동으로 드라이버/플러그인 설치
- **Day-2**: Operator 버전 업그레이드로 전체 스택 일괄 업데이트
- **호환성**: NVIDIA가 테스트한 버전 조합을 보장
- **MIG 관리**: MIG Manager가 파티션 설정을 자동화

주의사항:
- GPU Operator 자체가 상당한 리소스를 사용 (DaemonSet 여러 개)
- 커스텀 드라이버가 필요한 경우 driver.enabled=false로 비활성화 가능
- 에어갭(air-gap) 환경에서는 이미지를 private registry에 미러링 필요

**💡 경험 연결**:
"폐쇄망 환경에서 서버 소프트웨어를 일일이 수동 설치하던 경험이 있어, GPU Operator처럼 선언적으로 전체 스택을 관리하는 도구의 가치를 체감합니다. 특히 에어갭 환경에서의 이미지 미러링 경험이 직접 적용됩니다."

**⚠️ 주의**: GPU Operator가 관리하는 드라이버와 호스트 OS에 직접 설치된 드라이버가 충돌할 수 있다. 반드시 하나만 사용해야 한다.

---

### Q3: dcgm-exporter로 어떤 GPU 메트릭을 모니터링해야 하며, 각 메트릭이 의미하는 바는?

**30초 답변**:
핵심 메트릭은 GPU Utilization(연산 사용률), Memory Utilization(메모리 사용률), Temperature(온도), Power Usage(전력), XID Errors(하드웨어 오류)입니다. GPU Util이 낮은데 응답이 느리면 CPU→GPU 데이터 전송 병목이고, Memory가 꽉 차면 OOM이나 배치 사이즈 제한이 필요합니다.

**2분 답변**:
계층별 모니터링 전략:

**성능 메트릭**:
- `DCGM_FI_DEV_GPU_UTIL`: SM 활용률. 추론 중 70~90%가 정상. 너무 낮으면 데이터 공급 병목.
- `DCGM_FI_DEV_MEM_COPY_UTIL`: 메모리 대역폭 사용률. LLM에서 높을수록 memory-bound 상태.
- `DCGM_FI_DEV_SM_CLOCK`: SM 클럭. Thermal throttling 시 클럭이 낮아짐.

**리소스 메트릭**:
- `DCGM_FI_DEV_FB_USED/FREE`: GPU 메모리. LLM에서 KV-cache가 메모리 대부분 차지.
- `DCGM_FI_DEV_PCIE_TX/RX`: PCIe 대역폭. 멀티 GPU 통신량 확인.

**건강 메트릭**:
- `DCGM_FI_DEV_GPU_TEMP`: 온도. 83도 이상이면 thermal throttling 발생.
- `DCGM_FI_DEV_POWER_USAGE`: 전력. TDP 근처면 power throttling 가능.
- `DCGM_FI_DEV_XID_ERRORS`: XID 에러. 48(Double Bit ECC), 79(Fallen off the bus) 등 하드웨어 장애 신호.

Alert 설정 예시:
- GPU Temp > 83°C → warning (throttling 시작)
- GPU Memory > 95% → warning (OOM 임박)
- XID Error 발생 → critical (하드웨어 점검 필요)
- GPU Util < 10% for 30min → info (리소스 낭비)

**💡 경험 연결**:
"데이터센터에서 서버 하드웨어 모니터링 경험이 있어, GPU의 온도/전력/에러 모니터링이 서버 BMC/IPMI 모니터링과 유사한 패턴임을 이해합니다. XID 에러는 서버의 MCE(Machine Check Exception)와 같은 하드웨어 장애 신호입니다."

**⚠️ 주의**: dcgm-exporter의 수집 주기를 너무 짧게 설정하면 GPU 성능에 영향을 줄 수 있다. 15초 이상 권장.

---

## Allganize 맥락

- **Alli LLM 서빙**: GPU 리소스가 가장 비싼 비용 항목. MIG/Time-Slicing으로 효율화 필수
- **AWS EKS**: p4d/p5 인스턴스 (A100/H100) + EKS GPU AMI + GPU Operator 조합
- **Azure AKS**: NC/ND 시리즈 VM + AKS GPU node pool
- **모델 크기별 GPU 할당**: 소형 모델(1g.10gb MIG), 중형(3g.40gb MIG), 대형(전체 GPU 또는 멀티 GPU)
- **비용 최적화**: GPU idle 시간 최소화가 FinOps의 핵심. dcgm-exporter 메트릭으로 활용률 추적
- **GPU 장애 대응**: XID 에러 감지 → 자동 노드 drain → 교체 노드 프로비저닝 자동화

---

**핵심 키워드**: `GPU-Operator` `nvidia-device-plugin` `MIG` `Time-Slicing` `dcgm-exporter` `XID-errors` `GPU-Util` `KV-cache` `Taint-Toleration` `GPU-sharing`
