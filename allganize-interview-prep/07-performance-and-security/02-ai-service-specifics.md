# AI 서비스 성능 특화 (AI Service Performance) - Allganize 면접 준비

---

> **TL;DR**
> 1. GPU 리소스는 **nvidia-device-plugin**으로 K8s에 노출하고, **MIG/Time-Slicing**으로 공유한다
> 2. 모델 서빙 핵심 지표는 **TTFT**(첫 토큰 시간)와 **TPS**(초당 토큰 수)다
> 3. **Cold Start**는 모델 로딩 시간이 원인이며, vLLM/TGI + GPU 기반 HPA로 해결한다

---

## 1. GPU 리소스 관리

### nvidia-device-plugin 동작 원리

```
[Node]
  NVIDIA Driver + Container Toolkit
        |
  nvidia-device-plugin (DaemonSet)
        |
  kubelet에 nvidia.com/gpu 리소스 등록
        |
  Pod가 resources.limits로 GPU 요청
```

#### 설치 및 설정

```bash
# NVIDIA Device Plugin 배포
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.0/nvidia-device-plugin.yml

# GPU 노드 확인
kubectl describe node gpu-node-01 | grep nvidia.com/gpu
#  nvidia.com/gpu: 4
#  nvidia.com/gpu: 4
```

#### Pod에서 GPU 사용

```yaml
# gpu-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: ai-inference
spec:
  containers:
    - name: model-server
      image: vllm/vllm-openai:latest
      resources:
        limits:
          nvidia.com/gpu: 1    # GPU 1장 할당 (정수 단위)
        requests:
          nvidia.com/gpu: 1
```

### GPU 공유 전략

| 방식 | 설명 | 장점 | 단점 |
|------|------|------|------|
| **MIG** (Multi-Instance GPU) | A100/H100을 물리적으로 분할 | 완전 격리, QoS 보장 | A100 이상만 지원 |
| **Time-Slicing** | 시간 분할로 GPU 공유 | 모든 GPU 지원 | 메모리 격리 없음 |
| **MPS** (Multi-Process Service) | CUDA 컨텍스트 공유 | 낮은 오버헤드 | 장애 격리 부족 |
| **vGPU** (NVIDIA vGPU) | 하이퍼바이저 레벨 가상화 | 엔터프라이즈 격리 | 라이선스 비용 |

#### Time-Slicing 설정 예시

```yaml
# time-slicing-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nvidia-device-plugin
  namespace: kube-system
data:
  config: |
    version: v1
    sharing:
      timeSlicing:
        renameByDefault: false
        resources:
          - name: nvidia.com/gpu
            replicas: 4    # 물리 GPU 1장을 4개로 분할
```

### GPU 모니터링 (DCGM Exporter)

```bash
# DCGM Exporter 배포
helm install dcgm-exporter gpu-helm-charts/dcgm-exporter \
  --namespace monitoring

# 주요 메트릭
# DCGM_FI_DEV_GPU_UTIL      - GPU 사용률 (%)
# DCGM_FI_DEV_FB_USED       - GPU 메모리 사용량 (MB)
# DCGM_FI_DEV_SM_CLOCK      - SM 클럭 속도
# DCGM_FI_DEV_POWER_USAGE   - 전력 소비 (W)
```

```bash
# CLI로 빠른 확인
nvidia-smi dmon -s pucvmet -d 1
# GPU  Pwr  Temp  SM  Mem  FB   Bar1
#   0  150W  65C  85%  60%  32000  256
```

---

## 2. 모델 서빙 지표

### 핵심 지표 정의

| 지표 | 정의 | 목표치 (예시) |
|------|------|--------------|
| **TTFT** (Time To First Token) | 요청 후 첫 번째 토큰이 생성되기까지 시간 | < 500ms |
| **TPS** (Tokens Per Second) | 초당 생성되는 토큰 수 | > 30 tokens/s |
| **TPOT** (Time Per Output Token) | 출력 토큰 하나 생성 시간 | < 33ms |
| **E2E Latency** | 전체 요청-응답 완료 시간 | < 10s (256 tokens) |
| **Throughput** | 동시 요청 처리량 | > 20 req/s |

### 지표 간 관계

```
E2E Latency = TTFT + (Output Tokens x TPOT)

예시: TTFT=200ms, 256 tokens, TPOT=30ms
     = 200 + (256 x 30) = 7,880ms (~7.9초)
```

### Prometheus 메트릭 수집

```yaml
# vLLM이 노출하는 주요 메트릭
# vllm:num_requests_running        - 현재 처리 중인 요청 수
# vllm:num_requests_waiting        - 대기 중인 요청 수
# vllm:gpu_cache_usage_perc        - KV 캐시 사용률
# vllm:avg_generation_throughput   - 평균 생성 처리량 (tokens/s)
# vllm:e2e_request_latency         - 전체 지연 시간 히스토그램
```

```yaml
# Grafana 대시보드 쿼리 예시
# TTFT P99
histogram_quantile(0.99,
  sum(rate(vllm:time_to_first_token_seconds_bucket[5m])) by (le))

# 평균 TPS
rate(vllm:generation_tokens_total[5m])
```

---

## 3. Cold Start 문제와 해결책

### Cold Start란?

```
[요청 도착] -> [컨테이너 생성] -> [모델 로딩 (10~120초)] -> [추론 시작]
                                    ^^^^^^^^^^^^^^^^
                                    이 구간이 Cold Start
```

- **원인**: LLM 모델 파일이 수~수백 GB (7B 모델: ~14GB, 70B 모델: ~140GB)
- **영향**: 스케일아웃 시 새 Pod가 수분간 요청을 처리하지 못함

### 해결 전략

| 전략 | 방법 | 효과 |
|------|------|------|
| **모델 캐싱** | PVC에 모델 사전 다운로드, hostPath 마운트 | 로딩 시간 60~80% 감소 |
| **Warm Pool** | 최소 레플리카 유지 (minReplicas > 0) | Cold Start 완전 회피 |
| **모델 양자화** | GPTQ, AWQ, GGUF로 모델 크기 축소 | 로딩 시간 + 메모리 절약 |
| **ReadinessProbe** | 모델 로딩 완료 후에만 트래픽 수신 | 불완전 응답 방지 |
| **Init Container** | 모델 파일 사전 다운로드 | 메인 컨테이너 시작 시간 단축 |

#### 실전 설정 예시

```yaml
# model-serving-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-server
spec:
  replicas: 2                    # 최소 2개로 Warm Pool 유지
  template:
    spec:
      initContainers:
        - name: model-downloader
          image: busybox
          command: ['sh', '-c']
          args:
            - |
              if [ ! -f /models/model.safetensors ]; then
                echo "Downloading model..."
                wget -q -O /models/model.safetensors $MODEL_URL
              else
                echo "Model already cached"
              fi
          volumeMounts:
            - name: model-cache
              mountPath: /models
      containers:
        - name: vllm
          image: vllm/vllm-openai:latest
          args:
            - --model=/models
            - --gpu-memory-utilization=0.9
            - --max-model-len=4096
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 60    # 모델 로딩 대기
            periodSeconds: 10
            failureThreshold: 30       # 최대 5분 대기
          resources:
            limits:
              nvidia.com/gpu: 1
      volumes:
        - name: model-cache
          persistentVolumeClaim:
            claimName: model-cache-pvc  # ReadWriteMany PVC
```

---

## 4. vLLM과 TGI 개요

### vLLM (Virtual LLM)

```
핵심 기술: PagedAttention
- KV 캐시를 페이지 단위로 관리하여 GPU 메모리 효율 극대화
- 기존 대비 2~4배 높은 Throughput
- Continuous Batching으로 동적 배치 처리
```

```bash
# vLLM 서버 실행
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-8B \
  --gpu-memory-utilization 0.9 \
  --max-model-len 4096 \
  --tensor-parallel-size 2 \       # 2 GPU 병렬
  --port 8000

# OpenAI 호환 API로 호출
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3-8B",
    "prompt": "Explain Kubernetes in one sentence:",
    "max_tokens": 64,
    "temperature": 0.7
  }'
```

### TGI (Text Generation Inference) by Hugging Face

```bash
# TGI Docker 실행
docker run --gpus all -p 8080:80 \
  -v /data/models:/data \
  ghcr.io/huggingface/text-generation-inference:latest \
  --model-id meta-llama/Llama-3-8B \
  --quantize gptq \
  --max-input-length 2048 \
  --max-total-tokens 4096
```

### vLLM vs TGI 비교

| 항목 | vLLM | TGI |
|------|------|-----|
| **핵심 기술** | PagedAttention | Flash Attention, Continuous Batching |
| **API** | OpenAI 호환 | 자체 API + OpenAI 호환 |
| **모델 지원** | 넓음 (HF 모델 대부분) | HF 모델 + 자체 최적화 모델 |
| **양자화** | AWQ, GPTQ, SqueezeLLM | GPTQ, bitsandbytes, EETQ |
| **Multi-GPU** | Tensor Parallel, Pipeline Parallel | Tensor Parallel |
| **프로덕션 안정성** | 빠르게 성장 중 | 검증된 안정성 |
| **적합 상황** | 높은 Throughput 필요 시 | 안정적 서빙 우선 시 |

---

## 5. 오토스케일링 전략 (GPU 기반 HPA)

### 기본 HPA는 GPU를 모른다

```
기본 HPA: CPU/Memory 기반 스케일링
    -> GPU 사용률 기반 스케일링 불가
    -> Custom Metrics 필요
```

### 아키텍처

```
DCGM Exporter -> Prometheus -> Prometheus Adapter -> HPA
                                                      |
                                                   Scale Up/Down
```

### 구현 단계

#### Step 1: Prometheus Adapter 설정

```yaml
# prometheus-adapter-config.yaml
rules:
  - seriesQuery: 'DCGM_FI_DEV_GPU_UTIL{namespace!=""}'
    resources:
      overrides:
        namespace: {resource: "namespace"}
        pod: {resource: "pod"}
    name:
      matches: "DCGM_FI_DEV_GPU_UTIL"
      as: "gpu_utilization"
    metricsQuery: 'avg(DCGM_FI_DEV_GPU_UTIL{<<.LabelMatchers>>}) by (<<.GroupBy>>)'

  - seriesQuery: 'vllm:num_requests_waiting{namespace!=""}'
    resources:
      overrides:
        namespace: {resource: "namespace"}
        pod: {resource: "pod"}
    name:
      matches: "vllm:num_requests_waiting"
      as: "inference_queue_length"
    metricsQuery: 'avg(vllm:num_requests_waiting{<<.LabelMatchers>>}) by (<<.GroupBy>>)'
```

#### Step 2: GPU 기반 HPA

```yaml
# gpu-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: vllm-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vllm-server
  minReplicas: 2                   # Warm Pool (Cold Start 방지)
  maxReplicas: 8
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2                  # 한 번에 최대 2개 증가
          periodSeconds: 120
    scaleDown:
      stabilizationWindowSeconds: 300  # 5분 안정화 (급격한 축소 방지)
      policies:
        - type: Pods
          value: 1
          periodSeconds: 300
  metrics:
    - type: Pods
      pods:
        metric:
          name: gpu_utilization
        target:
          type: AverageValue
          averageValue: "70"        # GPU 사용률 70% 기준
    - type: Pods
      pods:
        metric:
          name: inference_queue_length
        target:
          type: AverageValue
          averageValue: "5"         # 대기 큐 5개 초과 시 스케일업
```

### KEDA 기반 고급 스케일링

```yaml
# keda-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-keda
spec:
  scaleTargetRef:
    name: vllm-server
  minReplicaCount: 2
  maxReplicaCount: 8
  cooldownPeriod: 300
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: gpu_utilization
        query: |
          avg(DCGM_FI_DEV_GPU_UTIL{namespace="ai-serving"})
        threshold: "70"
    - type: prometheus
      metadata:
        serverAddress: http://prometheus:9090
        metricName: request_queue
        query: |
          sum(vllm:num_requests_waiting{namespace="ai-serving"})
        threshold: "10"
```

---

## 면접 Q&A

### Q1. "GPU 리소스를 K8s에서 어떻게 관리하나요?"

> **이렇게 대답한다:**
> "nvidia-device-plugin을 DaemonSet으로 배포하면 kubelet이 nvidia.com/gpu를 스케줄링 가능한 리소스로 인식합니다. GPU 공유가 필요하면 A100 이상에서는 MIG로 물리 분할하고, 그 이하 GPU에서는 Time-Slicing을 적용합니다. 모니터링은 DCGM Exporter로 GPU 사용률, 메모리, 온도 등을 Prometheus에 수집합니다. 폐쇄망 환경에서 GPU 서버를 운영한 경험이 있어, 드라이버 호환성이나 CUDA 버전 관리의 중요성을 잘 알고 있습니다."

### Q2. "TTFT와 TPS는 무엇이고 왜 중요한가요?"

> **이렇게 대답한다:**
> "TTFT는 사용자가 요청 후 첫 토큰을 받기까지의 시간으로, 체감 응답 속도를 결정합니다. TPS는 초당 생성 토큰 수로, 전체 응답 완료 시간을 결정합니다. 채팅형 서비스에서는 TTFT가, 배치 처리에서는 TPS가 더 중요합니다. E2E Latency = TTFT + (Output Tokens x TPOT) 관계이므로, 두 지표를 분리해서 모니터링하고 각각에 맞는 최적화를 적용해야 합니다."

### Q3. "Cold Start 문제를 어떻게 해결하겠습니까?"

> **이렇게 대답한다:**
> "세 가지 계층으로 접근합니다. 첫째, 모델 파일을 PVC에 캐싱하여 다운로드 시간을 제거합니다. 둘째, minReplicas를 1 이상으로 유지하여 Warm Pool을 확보합니다. 셋째, 모델 양자화(AWQ, GPTQ)로 모델 크기 자체를 줄입니다. ReadinessProbe를 적절히 설정하여 모델이 완전히 로딩되기 전에 트래픽이 유입되는 것도 방지합니다. 폐쇄망 환경에서는 외부 모델 레지스트리 접근이 불가능하므로, 내부 스토리지에 모델을 사전 배포하는 파이프라인을 별도로 구축해야 합니다."

### Q4. "vLLM과 TGI 중 어떤 것을 선택하겠습니까?"

> **이렇게 대답한다:**
> "Allganize처럼 높은 동시 요청 처리가 필요한 AI 서비스에는 vLLM을 우선 고려합니다. PagedAttention으로 GPU 메모리를 효율적으로 사용하여 동일 GPU에서 더 많은 동시 요청을 처리할 수 있기 때문입니다. 다만 TGI는 Hugging Face 생태계와의 통합이 좋고 프로덕션 안정성이 검증되어 있으므로, 모델 종류와 SLA 요구사항에 따라 선택합니다. 두 도구 모두 OpenAI 호환 API를 제공하므로, 추후 교체도 용이합니다."

### Q5. "GPU 기반 오토스케일링은 어떻게 구현하나요?"

> **이렇게 대답한다:**
> "DCGM Exporter -> Prometheus -> Prometheus Adapter (또는 KEDA) -> HPA 파이프라인을 구성합니다. GPU 사용률과 추론 대기 큐 길이를 Custom Metric으로 등록하고, 이를 기준으로 스케일링합니다. 중요한 것은 scaleDown의 stabilizationWindow를 충분히 길게(5분 이상) 설정하는 것입니다. GPU Pod는 시작 비용이 크므로 급격한 축소를 방지해야 합니다. 또한 minReplicas를 항상 1 이상으로 유지하여 Cold Start를 최소화합니다."

---

## 핵심 키워드 5선

`TTFT / TPS` `PagedAttention (vLLM)` `GPU Time-Slicing / MIG` `Cold Start 최적화` `GPU 기반 HPA (KEDA)`
