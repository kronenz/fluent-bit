# Alli 제품 아키텍처 딥다이브 (Deep Dive)

## TL;DR
1. Alli는 RAG (Retrieval-Augmented Generation) 기반 엔터프라이즈 AI 플랫폼으로, 문서 업로드부터 LLM 응답 생성까지 전체 파이프라인을 제공한다
2. DevOps 관점에서 GPU 클러스터 관리, 벡터 DB 운영, 모델 서빙 인프라의 안정성과 스케일링이 핵심 과제다
3. 10년간의 온프렘/폐쇄망 인프라 경험은 엔터프라이즈 고객의 프라이빗 배포 요구사항에 직접적인 강점이 된다

---

## 1. Alli 제품군 개요 (Product Portfolio)

### Alli LLM App Market
- 엔터프라이즈용 LLM 애플리케이션 마켓플레이스 (Marketplace)
- 사전 구축된 AI 워크플로우를 고객이 선택하여 즉시 배포 가능
- DevOps 관점: 멀티테넌트 (Multi-tenant) 환경에서 앱별 격리와 리소스 할당 관리 필요

### Alli Answer Bot
- 고객 문의 자동 응답 챗봇 (Chatbot)
- FAQ 기반 + LLM 기반 하이브리드 응답 구조
- 실시간 응답이 필수이므로 낮은 레이턴시 (Latency) 인프라가 핵심

### Alli Document AI
- 문서 자동 분류, 추출, 요약 서비스
- OCR + NLP + LLM 파이프라인 조합
- 대용량 문서 배치 처리 (Batch Processing) 시 GPU 리소스 스케줄링 중요

### Alli Capture
- 비정형 데이터 캡처 및 구조화
- 다양한 포맷 (PDF, 이미지, 스캔 문서) 지원

---

## 2. RAG 파이프라인 구조 추정 (RAG Pipeline Architecture)

```
[문서 업로드] → [전처리/청킹] → [임베딩 생성] → [벡터 DB 저장]
                                                        ↓
[사용자 질의] → [질의 임베딩] → [유사도 검색] → [컨텍스트 조합] → [LLM 응답 생성]
```

### 단계별 상세

| 단계 | 기술 요소 | DevOps 고려사항 |
|------|-----------|----------------|
| 문서 업로드 | S3/Azure Blob, 파일 파서 (Parser) | 스토리지 용량 모니터링, 업로드 큐 관리 |
| 청킹 (Chunking) | 토큰 기반 분할, 오버랩 (Overlap) 설정 | 워커 (Worker) 스케일링, 메모리 관리 |
| 임베딩 (Embedding) | OpenAI Ada, 자체 임베딩 모델 | GPU 리소스 할당, 배치 처리 최적화 |
| 벡터 DB 저장 | Milvus / Weaviate / Pinecone | 클러스터 안정성, 인덱스 리빌드 (Rebuild) |
| 유사도 검색 (Similarity Search) | ANN (Approximate Nearest Neighbor) | 검색 레이턴시 모니터링, 캐시 (Cache) 전략 |
| LLM 응답 생성 | GPT-4, Claude, 자체 파인튜닝 모델 | API 비용 관리, 폴백 (Fallback) 구성 |

### 청킹 전략 (Chunking Strategy)
- **고정 크기 청킹**: 토큰 수 기준 분할 (예: 512 토큰)
- **시맨틱 청킹 (Semantic Chunking)**: 문맥 단위 분할
- 오버랩 비율이 검색 품질에 직접 영향 → 파라미터 튜닝 필요
- DevOps는 청킹 워커의 오토스케일링 (Auto-scaling) 정책 설계에 관여

---

## 3. LLM 서빙 아키텍처 추정 (LLM Serving Architecture)

### 서빙 프레임워크 (Serving Framework)
- **vLLM**: PagedAttention 기반 고효율 서빙, 높은 처리량 (Throughput)
- **TGI (Text Generation Inference)**: HuggingFace의 프로덕션 서빙 솔루션
- **Triton Inference Server**: NVIDIA의 멀티프레임워크 서빙

### GPU 클러스터 구성 추정
```
[로드밸런서 (Load Balancer)]
        ↓
[API Gateway] → [모델 라우터 (Router)]
                    ↓
    ┌──────────────────────────────┐
    │  GPU Node Pool (A100/H100)   │
    │  ┌─────┐ ┌─────┐ ┌─────┐   │
    │  │vLLM │ │vLLM │ │vLLM │   │
    │  │Pod 1│ │Pod 2│ │Pod 3│   │
    │  └─────┘ └─────┘ └─────┘   │
    └──────────────────────────────┘
```

### 모델 로딩 및 관리
- 모델 아티팩트 (Artifact) 저장: S3 / Azure Blob → 노드 로컬 SSD 캐싱
- 모델 버전 관리: MLflow / 자체 레지스트리 (Registry)
- 핫스왑 (Hot-swap): 다운타임 없는 모델 교체 → 블루-그린 배포 (Blue-Green Deployment)

### 배치 추론 (Batch Inference)
- 동적 배칭 (Dynamic Batching): 요청을 묶어 GPU 활용률 극대화
- 연속 배칭 (Continuous Batching): vLLM의 핵심 기능, 완료된 요청 즉시 교체
- KV 캐시 (KV Cache) 관리: GPU 메모리의 효율적 활용

---

## 4. 벡터 DB 비교 및 운영 (Vector Database)

| 항목 | Milvus | Pinecone | Weaviate |
|------|--------|----------|----------|
| 배포 방식 | 셀프호스팅 / 클라우드 | 완전 관리형 (Managed) | 셀프호스팅 / 클라우드 |
| 스케일링 | 수평 확장 가능 | 자동 스케일링 | 수평 확장 가능 |
| K8s 연동 | Helm 차트 지원 | 불필요 (SaaS) | Helm 차트 지원 |
| 엔터프라이즈 | 온프렘 배포 가능 | 클라우드 전용 | 온프렘 배포 가능 |

**올거나이즈 추정**: 엔터프라이즈 고객의 데이터 주권 (Data Sovereignty) 요구사항을 고려하면 Milvus 또는 Weaviate의 셀프호스팅 가능성이 높음 → **폐쇄망 배포 경험이 직접적 강점**

---

## 5. DevOps 관점 인프라 요구사항

### GPU 노드 관리
- NVIDIA Device Plugin으로 K8s에서 GPU 리소스 스케줄링
- GPU 모니터링: `nvidia-smi`, DCGM Exporter → Prometheus → Grafana
- 노드 어피니티 (Node Affinity)로 GPU 워크로드 격리
- GPU 메모리 OOM (Out of Memory) 대응 전략

### 모델 배포 파이프라인 (Model Deployment Pipeline)
```
[모델 학습 완료] → [모델 레지스트리 등록] → [CI/CD 트리거]
    → [컨테이너 이미지 빌드] → [스테이징 배포/테스트]
    → [카나리 배포 (Canary)] → [프로덕션 전환]
```

### 스케일링 전략
- **HPA (Horizontal Pod Autoscaler)**: GPU 활용률 / 요청 큐 길이 기반
- **KEDA**: 이벤트 기반 스케일링, 큐 메트릭 연동
- **Cluster Autoscaler**: GPU 노드 자동 추가/제거
- 콜드 스타트 (Cold Start) 문제: 모델 로딩 시간이 길어 사전 웜업 (Warm-up) 필수

### 멀티클라우드 (Multi-Cloud) 고려사항
- AWS: EKS + p4d/p5 인스턴스 (A100/H100)
- Azure: AKS + NC/ND 시리즈 VM
- 클라우드 간 일관된 배포를 위한 Terraform / Helm 추상화 레이어

---

## 6. 면접 Q&A

### Q1. "Alli 제품의 아키텍처를 어떻게 이해하고 있나요?"

> **면접에서 이렇게 물어보면 →**
>
> **이렇게 대답한다:** "Alli는 RAG 기반의 엔터프라이즈 AI 플랫폼으로 이해하고 있습니다. 문서 업로드부터 청킹, 임베딩, 벡터 DB 저장, 그리고 LLM 응답 생성까지의 파이프라인이 핵심입니다. DevOps 관점에서는 이 파이프라인의 각 단계가 독립적으로 스케일링되어야 하고, 특히 GPU 리소스 관리와 벡터 DB의 안정적 운영이 중요하다고 봅니다. 300개 이상의 엔터프라이즈 고객을 지원하려면 멀티테넌시와 데이터 격리도 핵심 과제일 것입니다."

### Q2. "RAG 시스템에서 DevOps가 신경 써야 할 부분은?"

> **면접에서 이렇게 물어보면 →**
>
> **이렇게 대답한다:** "세 가지 핵심이 있습니다. 첫째, 임베딩 파이프라인의 처리량 관리입니다. 고객이 대량 문서를 업로드할 때 GPU 워커가 자동으로 스케일아웃 되어야 합니다. 둘째, 벡터 DB의 안정성입니다. 인덱스 리빌드 중에도 검색이 가능해야 하므로 롤링 업데이트 전략이 필요합니다. 셋째, LLM 서빙의 레이턴시 모니터링입니다. P95, P99 레이턴시를 추적하고 SLO를 설정하여 자동 알림과 스케일링을 구성해야 합니다."

### Q3. "GPU 클러스터 관리 경험이 있나요?"

> **면접에서 이렇게 물어보면 →**
>
> **이렇게 대답한다:** "AI 데이터센터 컨설팅 회사인 엠키스코어에서 GPU 인프라를 다루고 있습니다. 직접적인 대규모 GPU 클러스터 운영 경험은 아직 쌓아가는 중이지만, K8s 환경에서 NVIDIA Device Plugin을 활용한 GPU 스케줄링, DCGM Exporter를 통한 모니터링 구성에 대해 학습하고 테스트 환경을 구축해본 경험이 있습니다. 무엇보다 10년간의 온프렘 인프라 경험에서 축적한 하드웨어 장애 대응, 리소스 최적화 역량은 GPU 클러스터 관리에도 직접 적용됩니다."

### Q4. "엔터프라이즈 고객에게 온프렘 배포를 해야 한다면 어떻게 접근하나요?"

> **면접에서 이렇게 물어보면 →**
>
> **이렇게 대답한다:** "이것이 제가 가장 자신 있는 영역입니다. 폐쇄망 환경에서의 인프라 구축 경험이 풍부합니다. 먼저 에어갭 환경을 위한 오프라인 패키지 번들링이 필요합니다. 컨테이너 이미지, Helm 차트, 모델 아티팩트를 모두 포함한 배포 패키지를 구성합니다. 프라이빗 레지스트리 (Harbor 등)를 고객 환경에 구축하고, Ansible이나 Terraform으로 일관된 배포를 자동화합니다. 또한 외부 연결 없이도 모니터링과 로깅이 가능한 독립형 관측 스택 (Observability Stack)을 함께 배포합니다."

### Q5. "Alli 플랫폼의 가용성을 어떻게 보장하겠나요?"

> **면접에서 이렇게 물어보면 →**
>
> **이렇게 대답한다:** "엔터프라이즈 SaaS에서 가용성은 곧 신뢰입니다. 먼저 멀티 AZ (Availability Zone) 배포로 단일 장애점을 제거합니다. LLM 서빙은 여러 GPU 노드에 분산하고, 모델 헬스체크를 통해 비정상 파드를 자동 교체합니다. 벡터 DB는 레플리카셋을 구성하고 정기 백업을 자동화합니다. 그리고 카오스 엔지니어링 (Chaos Engineering)을 도입하여 GPU 노드 장애, 네트워크 파티션 등의 시나리오를 주기적으로 테스트합니다. 무엇보다 장애 발생 시 5분 내 감지, 15분 내 1차 대응이라는 구체적 SLO를 설정하고 온콜 체계를 구축하겠습니다."

---

## 핵심 키워드 (Keywords)
`RAG Pipeline` · `LLM Serving (vLLM/TGI)` · `Vector Database` · `GPU Cluster Management` · `Enterprise On-Prem Deployment`
