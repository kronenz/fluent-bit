# LLM 서빙 인프라스트럭처

> **TL;DR**: vLLM, TGI, Triton은 LLM 추론 서빙의 3대 프레임워크이며, 각각 PagedAttention, Continuous Batching 등 최적화 기법을 사용한다.
> TTFT(Time To First Token)와 TPS(Tokens Per Second)가 핵심 서빙 성능 지표이다.
> DevOps 관점에서는 모델 로딩 전략, 헬스체크, 오토스케일링, GPU 메모리 관리가 운영의 핵심이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### 1. LLM 추론 파이프라인

```
사용자 요청 → Tokenization → Prefill → Decode → Detokenization → 응답

┌──────────┐    ┌───────────┐    ┌──────────────────────────┐    ┌──────────┐
│Tokenizer │    │  Prefill  │    │       Decode Loop        │    │Detokenize│
│          │───▶│ (한번에    │───▶│ Token₁→Token₂→...→EOS   │───▶│          │
│"안녕하세요"│   │  KV-cache │    │ (auto-regressive)       │    │ 텍스트    │
│→ [토큰들] │   │  생성)    │    │ 각 스텝마다 GPU 연산     │    │ 변환     │
└──────────┘    └───────────┘    └──────────────────────────┘    └──────────┘
     │               │                      │
     │          ┌────┴────┐           ┌─────┴─────┐
     │          │ TTFT    │           │    TPS    │
     │          │ 결정 구간│           │  결정 구간 │
     │          └─────────┘           └───────────┘
```

### 2. 핵심 성능 지표

| 지표 | 정의 | 목표값 (일반적) | 영향 요소 |
|------|------|---------------|----------|
| **TTFT** | 첫 토큰까지 시간 | < 1초 | 입력 길이, Prefill 속도, 큐잉 |
| **TPS** | 초당 생성 토큰 수 | 30~80 tokens/s | 모델 크기, GPU 성능, 배치 |
| **ITL** | 토큰 간 지연시간 | < 50ms | Decode 스텝 시간 |
| **Throughput** | 초당 총 처리 토큰 | 높을수록 좋음 | Batching 효율 |
| **TPOT** | 출력 토큰당 시간 | 1/TPS | Decode 효율 |

### 3. 주요 서빙 프레임워크 비교

```
┌─────────────────────────────────────────────────────────┐
│                  LLM Serving Frameworks                  │
├──────────────┬──────────────┬───────────────────────────┤
│     vLLM     │     TGI      │    Triton Inference       │
│              │ (Text Gen    │    Server                 │
│  UC Berkeley │  Inference)  │    NVIDIA                 │
│              │  HuggingFace │                           │
├──────────────┼──────────────┼───────────────────────────┤
│ PagedAttention│ Continuous  │ Multi-model               │
│ Continuous   │  Batching    │ Multi-framework           │
│  Batching    │ FlashAttention│ (PyTorch, TensorRT,      │
│ OpenAI API   │ Watermark   │  ONNX, vLLM backend)     │
│ 호환         │ Structured  │ Dynamic Batching          │
│              │  Output     │ Model Ensemble            │
│              │              │ gRPC + HTTP               │
├──────────────┼──────────────┼───────────────────────────┤
│ 가장 쉬운    │ HF 생태계    │ 엔터프라이즈급             │
│ 배포, 활발한 │ 통합 우수    │ 멀티모델 서빙              │
│ 커뮤니티     │              │ 최고 성능                  │
└──────────────┴──────────────┴───────────────────────────┘
```

### 4. vLLM 상세

**PagedAttention**: OS의 가상 메모리 페이징 기법을 KV-cache 관리에 적용.

```
전통 방식: 연속 메모리 할당 (메모리 낭비)
┌──────────────────────────────────────────┐
│ Req1 KV-cache [████████░░░░░░░░░░░░]     │  ← 최대 길이만큼 예약
│ Req2 KV-cache [██████░░░░░░░░░░░░░░]     │  ← 실제 사용 < 예약
│ 낭비:         [░░░░░░░░░░░░░░░░░░░░]     │  ← 60~80% 메모리 낭비
└──────────────────────────────────────────┘

PagedAttention: 페이지 단위 동적 할당 (효율적)
┌──────────────────────────────────────────┐
│ 물리 GPU 메모리:                          │
│ [P1][P2][P3][P4][P5][P6][P7][P8][P9]    │
│                                          │
│ Req1: 논리 블록 [0→P1] [1→P3] [2→P7]    │  ← 비연속 할당 OK
│ Req2: 논리 블록 [0→P2] [1→P5]            │  ← 필요한 만큼만
│ Req3: 논리 블록 [0→P4] [1→P6] [2→P8]    │
│                                          │
│ 활용률: 90%+ (낭비 최소화)                 │
└──────────────────────────────────────────┘
```

```yaml
# vLLM Kubernetes 배포
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-server
  namespace: alli-inference
spec:
  replicas: 2
  selector:
    matchLabels:
      app: vllm-server
  template:
    metadata:
      labels:
        app: vllm-server
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:v0.4.0
        command:
        - python3
        - -m
        - vllm.entrypoints.openai.api_server
        args:
        - --model=/models/llama-3-70b
        - --tensor-parallel-size=2         # 2 GPU에 모델 분산
        - --gpu-memory-utilization=0.90    # GPU 메모리 90% 사용
        - --max-model-len=4096
        - --max-num-seqs=256               # 최대 동시 요청
        - --enable-prefix-caching          # 프롬프트 캐싱
        - --block-size=16
        ports:
        - containerPort: 8000
        resources:
          limits:
            nvidia.com/gpu: 2
            memory: 64Gi
          requests:
            cpu: "8"
            memory: 32Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 120         # 모델 로딩 대기
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 120
          periodSeconds: 5
        volumeMounts:
        - name: model-storage
          mountPath: /models
        - name: shm
          mountPath: /dev/shm
      volumes:
      - name: model-storage
        persistentVolumeClaim:
          claimName: model-pvc
      - name: shm
        emptyDir:
          medium: Memory
          sizeLimit: 16Gi                  # 공유 메모리 (tensor parallel)
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
```

### 5. TGI (Text Generation Inference)

```yaml
# TGI 배포
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tgi-server
spec:
  template:
    spec:
      containers:
      - name: tgi
        image: ghcr.io/huggingface/text-generation-inference:2.0
        args:
        - --model-id=meta-llama/Llama-3-70B-Instruct
        - --num-shard=2                    # GPU 분산
        - --max-input-tokens=2048
        - --max-total-tokens=4096
        - --max-batch-prefill-tokens=4096
        - --max-concurrent-requests=128
        - --quantize=awq                   # 양자화 (메모리 절감)
        env:
        - name: HUGGING_FACE_HUB_TOKEN
          valueFrom:
            secretKeyRef:
              name: hf-secret
              key: token
        resources:
          limits:
            nvidia.com/gpu: 2
```

### 6. Triton Inference Server

```
Triton 아키텍처

┌─────────────────────────────────────────────────┐
│              Triton Inference Server              │
│                                                   │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────┐  │
│  │ HTTP/   │  │ gRPC    │  │ Metrics         │  │
│  │ REST    │  │ endpoint│  │ (Prometheus)    │  │
│  │ :8000   │  │ :8001   │  │ :8002           │  │
│  └────┬────┘  └────┬────┘  └─────────────────┘  │
│       └──────┬─────┘                             │
│       ┌──────▼──────┐                            │
│       │   Scheduler  │                            │
│       │  (Dynamic    │                            │
│       │   Batching)  │                            │
│       └──────┬──────┘                            │
│       ┌──────▼──────────────────────────┐        │
│       │      Model Repository            │        │
│       │  ┌────────┐ ┌────────┐ ┌──────┐ │        │
│       │  │PyTorch │ │TensorRT│ │ vLLM │ │        │
│       │  │Backend │ │Backend │ │Back. │ │        │
│       │  └────────┘ └────────┘ └──────┘ │        │
│       └─────────────────────────────────┘        │
└─────────────────────────────────────────────────┘
```

### 7. 모델 서빙 아키텍처 패턴

```
패턴 1: 단일 모델 서빙 (Simple)
Client → LB → vLLM Pod (GPU) → Response

패턴 2: 모델 라우터 (Multi-Model)
Client → API GW → Model Router → ┬→ vLLM (Model A) →
                                  ├→ vLLM (Model B) →
                                  └→ TGI  (Model C) →

패턴 3: RAG + LLM 파이프라인 (Allganize Alli)
Client → API GW → ┬→ Embedding Svc → Vector DB → Context
                   └→ LLM Svc (vLLM) ←───────────────┘
                        │
                        ▼
                   Streaming Response

패턴 4: Ensemble (Triton)
Client → Triton → Preprocessing → Model A → Postprocessing → Response
                       │              │            │
                    (tokenize)    (inference)   (detokenize)
```

---

## 실전 예시

### vLLM 메트릭 기반 HPA

```yaml
# vLLM이 노출하는 Prometheus 메트릭
# vllm:num_requests_running     - 현재 처리 중인 요청 수
# vllm:num_requests_waiting     - 큐에서 대기 중인 요청 수
# vllm:gpu_cache_usage_perc     - KV-cache 사용률
# vllm:avg_prompt_throughput_toks_per_s  - 입력 처리 속도
# vllm:avg_generation_throughput_toks_per_s - 출력 생성 속도

# KEDA ScaledObject로 vLLM 오토스케일링
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-scaler
  namespace: alli-inference
spec:
  scaleTargetRef:
    name: vllm-server
  minReplicaCount: 2
  maxReplicaCount: 8
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus:9090
      metricName: vllm_waiting_requests
      query: |
        sum(vllm:num_requests_waiting{namespace="alli-inference"})
        / count(vllm:num_requests_waiting{namespace="alli-inference"})
      threshold: "10"                      # Pod당 대기 10건 초과 시 스케일업
  cooldownPeriod: 300                      # 모델 로딩 시간 고려
```

### 모델 로딩 최적화 전략

```
문제: LLM 모델 로딩에 수 분 소요 → Pod 시작 느림 → 스케일업 지연

해결 방법:
1. 모델 캐시 PVC (ReadWriteMany)
   - 모델 파일을 EFS/Azure Files에 저장
   - 모든 Pod가 공유 마운트 → 다운로드 불필요

2. initContainer로 모델 프리로딩
   - S3/Blob → 로컬 SSD로 복사 후 서빙

3. 모델 Warmup
   - readinessProbe + startup probe 활용
   - 모델 로딩 완료 후에만 트래픽 수신

4. Buffer Pod (Over-provisioning)
   - 예비 Pod를 미리 띄워두고 대기
   - PriorityClass로 구현 (placeholder Pod)
```

```yaml
# Buffer Pod 전략 (Placeholder)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-buffer
spec:
  replicas: 2
  template:
    spec:
      priorityClassName: buffer-low        # 낮은 우선순위
      terminationGracePeriodSeconds: 0
      containers:
      - name: pause
        image: registry.k8s.io/pause:3.9
        resources:
          limits:
            nvidia.com/gpu: 1              # GPU 슬롯 확보
          requests:
            nvidia.com/gpu: 1
---
# 실제 inference Pod가 스케줄링되면 buffer Pod를 preempt
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: buffer-low
value: -1                                  # 최저 우선순위
preemptionPolicy: Never
```

---

## 면접 Q&A

### Q1: vLLM의 PagedAttention이 무엇이고, 왜 LLM 서빙에서 중요합니까?

**30초 답변**:
PagedAttention은 OS의 가상 메모리 페이징을 KV-cache 관리에 적용한 기법입니다. 전통적으로 각 요청의 KV-cache는 최대 시퀀스 길이만큼 연속 메모리를 예약하여 60~80%가 낭비됩니다. PagedAttention은 고정 크기 블록으로 비연속 할당하여 메모리 낭비를 거의 없애고, 동시 처리 가능한 요청 수를 2~4배 증가시킵니다.

**2분 답변**:
LLM 추론의 메모리 병목:
- Transformer 모델은 각 요청마다 KV-cache(Key-Value cache)를 유지해야 함
- KV-cache 크기 = 2 x num_layers x num_heads x head_dim x seq_len x batch_size x sizeof(dtype)
- 예: Llama-3 70B, seq_len 4096, batch 1 → KV-cache만 수 GB

전통 방식의 문제:
- 최대 시퀀스 길이(예: 4096 토큰)만큼 메모리를 사전 예약
- 실제 생성은 100~500 토큰인 경우가 대부분 → 80%+ 메모리 낭비
- 연속 메모리 필요 → 외부 단편화 발생

PagedAttention 해결:
- KV-cache를 고정 크기 블록(예: 16 토큰)으로 분할
- 블록 테이블로 논리→물리 블록 매핑 (OS 페이지 테이블과 동일)
- 필요한 만큼만 할당, 비연속 메모리 OK
- Copy-on-Write로 beam search 시 KV-cache 공유 가능

결과:
- GPU 메모리 활용률 90%+ (기존 20~40%)
- 동일 GPU에서 2~4x 더 많은 동시 요청 처리
- Throughput 대폭 향상

**💡 경험 연결**:
"OS의 가상 메모리 관리를 이해하고 있어서 PagedAttention의 원리가 자연스럽게 이해됩니다. 리눅스 커널의 페이지 테이블, Copy-on-Write 개념이 그대로 GPU 메모리 관리에 적용된 것입니다."

**⚠️ 주의**: PagedAttention은 vLLM의 핵심 기술이지만, 최근 TGI도 유사한 기법을 구현했다. 프레임워크별 최신 동향을 파악해야 한다.

---

### Q2: LLM 서빙 서버의 헬스체크와 readiness 전략을 어떻게 설계합니까?

**30초 답변**:
LLM 서버는 모델 로딩에 수 분이 걸리므로 startupProbe로 최대 대기 시간을 넉넉히 설정하고, readinessProbe로 모델이 실제 추론 가능한 상태인지 확인합니다. 단순 HTTP 200이 아니라 dummy inference를 수행하는 엔드포인트를 사용하면 더 정확합니다.

**2분 답변**:
3단계 프로브 전략:

1. **startupProbe**: 모델 로딩 완료 대기
   - 70B 모델은 로딩에 3~5분 소요 (GPU 메모리로 적재)
   - failureThreshold × periodSeconds > 예상 로딩 시간
   - 예: failureThreshold=60, periodSeconds=10 → 최대 10분 대기

2. **readinessProbe**: 추론 가능 상태 확인
   - /health 엔드포인트로 모델 상태 확인
   - 실패 시 Service에서 제거 → 트래픽 차단
   - GPU 메모리 부족(OOM) 시 자동 트래픽 차단

3. **livenessProbe**: 서버 생존 확인
   - readinessProbe보다 관대하게 설정
   - 실패 시 Pod 재시작 → 모델 재로딩 비용이 크므로 주의
   - failureThreshold를 높게 설정 (일시적 GPU 부하 허용)

추가 고려사항:
- **Graceful Shutdown**: terminationGracePeriodSeconds를 충분히 (진행 중인 생성 완료)
- **Preemption 방지**: 모델 로딩 중 Pod가 preempt되면 리소스 낭비. PriorityClass 활용.
- **Connection Draining**: 스트리밍 응답 중인 연결을 안전하게 종료

**💡 경험 연결**:
"서비스 배포 시 헬스체크 설계는 가장 기본적이면서도 중요한 부분입니다. LLM 서빙은 기존 웹 서비스보다 시작 시간이 훨씬 길어서, probe 설정을 잘못하면 무한 재시작 루프에 빠질 수 있습니다."

**⚠️ 주의**: livenessProbe를 너무 공격적으로 설정하면 GPU 부하가 높을 때 불필요한 Pod 재시작이 발생한다. 모델 재로딩 비용을 고려해야 한다.

---

### Q3: vLLM, TGI, Triton 중 어떤 프레임워크를 추천하며, 그 이유는?

**30초 답변**:
용도에 따라 다릅니다. 단일 LLM 서빙에는 vLLM이 배포 편의성과 성능 모두 뛰어납니다. HuggingFace 모델 생태계 활용이 중요하면 TGI, 멀티모델 서빙이나 전처리/후처리 파이프라인이 필요하면 Triton을 선택합니다. Allganize 환경에서는 vLLM + Triton 조합을 추천합니다.

**2분 답변**:

| 시나리오 | 추천 | 이유 |
|---------|------|------|
| 단일 LLM API 서빙 | vLLM | OpenAI 호환 API, PagedAttention, 활발한 개발 |
| HF 모델 빠른 배포 | TGI | HuggingFace Hub 직접 연동, 양자화 내장 |
| 멀티모델 서빙 | Triton | 하나의 서버에서 embedding + LLM + reranker |
| 최고 성능 (TensorRT) | Triton + TRT-LLM | NVIDIA 최적화, 최저 latency |
| 프로토타입/개발 | vLLM | 설치 간단, 문서 풍부 |

Allganize Alli 아키텍처 추천:
```
Alli 서비스 아키텍처

API Gateway
    ├── Embedding Service (Triton + ONNX)
    │     └── 벡터 생성 → Vector DB 검색
    ├── Reranker Service (Triton + PyTorch)
    │     └── 검색 결과 재순위화
    └── LLM Service (vLLM)
          └── RAG 컨텍스트 + 프롬프트 → 생성
```

- vLLM: Alli의 메인 LLM 추론 (PagedAttention으로 높은 동시성)
- Triton: Embedding, Reranker 등 보조 모델 (멀티모델 효율)

**💡 경험 연결**:
"인프라 선택 시 단순 성능뿐 아니라 운영 복잡도, 팀의 기술 스택, 커뮤니티 지원을 종합적으로 고려합니다. vLLM은 빠르게 발전하는 오픈소스 생태계와 OpenAI API 호환이 운영 편의성 측면에서 큰 장점입니다."

**⚠️ 주의**: LLM 서빙 프레임워크는 매우 빠르게 발전하므로 면접 시점의 최신 버전과 기능을 확인해야 한다. 6개월 전 정보가 이미 구식일 수 있다.

---

## Allganize 맥락

- **Alli 챗봇**: RAG 파이프라인(Embedding → 검색 → LLM 생성)에서 각 단계의 서빙 인프라 필요
- **TTFT SLO**: 사용자 체감 응답성에 직결. Alli의 TTFT를 1초 이내로 유지하는 것이 목표
- **멀티 모델**: Alli는 Embedding, Reranker, LLM 등 여러 모델을 서빙해야 함
- **GPU 비용**: vLLM의 PagedAttention으로 동일 GPU에서 더 많은 동시 요청 처리 → 비용 절감
- **스트리밍**: Alli 챗봇의 실시간 응답을 위해 SSE/WebSocket 스트리밍 지원 필수
- **모델 업데이트**: 새 모델 배포 시 무중단 전환 전략 (rolling update with readiness probe)

---

**핵심 키워드**: `vLLM` `TGI` `Triton` `PagedAttention` `Continuous-Batching` `TTFT` `TPS` `KV-cache` `tensor-parallel` `model-serving` `KEDA`
