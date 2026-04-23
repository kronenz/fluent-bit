# 올거나이즈코리아 DevOps Engineer 1차 기술 면접 대비 학습 자료

> **지원 포지션:** 올거나이즈코리아 (Allganize Korea) DevOps Engineer  
> **면접 형태:** 1차 비대면(Remote) 기술 면접  
> **지원자 배경:** IT 인프라 10년+ (폐쇄망, 온프레미스, 연구망, 모바일), AI 데이터센터 컨설팅 기업 재직 중  
> **학습 목표:** 순수 DevOps 경력이 짧은 약점을 보완하고, 폭넓은 인프라 경험을 강점으로 전환하여 합격하기

---

## 자료 사용법

1. 아래 **D-7 ~ D-1 학습 플랜**을 따라 일자별로 학습합니다.
2. 각 문서를 읽은 뒤 **전체 체크리스트**에서 해당 항목을 체크(`[x]`)합니다.
3. 🎤 표시가 있는 항목은 **반드시 입으로 소리내어 연습**합니다. 머릿속으로만 정리하면 면접에서 막힙니다.
4. D-1에는 치트시트를 복습하고, 가능하면 누군가에게 모의 면접을 부탁합니다.
5. 면접 당일에는 맨 아래 **면접 당일 체크리스트**를 따릅니다.

---

## D-7 ~ D-1 일자별 학습 플랜

### D-7 | 회사 조사 + 자기소개 준비 (2~3시간)

| 순서 | 내용 | 비고 |
|------|------|------|
| 1 | 올거나이즈 회사/제품/기술 스택 조사 | `01-company-research/01-allganize-overview.md` |
| 2 | 채용 공고(JD) 키워드 분석 및 내 경험 매핑 | JD를 프린트해서 형광펜으로 표시 |
| 3 | 🎤 1분 / 3분 자기소개 작성 및 발화 연습 | 타이머 켜고 3회 이상 반복 |
| 4 | 🎤 "왜 올거나이즈인가" 답변 준비 | AI + DevOps 관심사 연결 |

**핵심:** 회사를 잘 아는 것만으로도 좋은 첫인상을 줄 수 있습니다.

---

### D-6 | Linux 기초 + 컨테이너 내부구조 (2~3시간)

| 순서 | 내용 | 비고 |
|------|------|------|
| 1 | 프로세스 관리(Process Management) 복습 | `02-linux-fundamentals/01-process-management.md` |
| 2 | 컨테이너 내부구조(Container Internals) 학습 | `03-container-and-kubernetes/01-container-internals.md` |
| 3 | namespace, cgroup, overlay FS 개념 정리 | 면접 빈출 토픽 |
| 4 | 🎤 "컨테이너가 VM과 다른 점을 설명해주세요" 답변 연습 | 30초~1분 분량 |
| 5 | 🎤 "리눅스 서버 트러블슈팅 경험" 사례 1개 준비 | STAR 프레임워크 활용 |

**핵심:** 10년 인프라 경험에서 Linux 실력은 가장 확실한 무기입니다.

---

### D-5 | Kubernetes 아키텍처 + 워크로드 + 네트워킹 (3시간)

| 순서 | 내용 | 비고 |
|------|------|------|
| 1 | Kubernetes 아키텍처(Architecture) 학습 | `03-container-and-kubernetes/02-kubernetes-architecture.md` |
| 2 | Control Plane 구성요소 정리 (API Server, etcd, Scheduler, Controller Manager) | 각각의 역할을 한 문장으로 |
| 3 | Pod, Deployment, Service, Ingress 개념 정리 | 워크로드(Workload) 핵심 |
| 4 | 네트워킹 모델(CNI, kube-proxy, Service 유형) 이해 | 면접 중급 난이도 |
| 5 | 🎤 "Kubernetes에서 Pod가 생성되는 과정을 설명해주세요" 답변 연습 | API Server -> Scheduler -> Kubelet 흐름 |
| 6 | 🎤 "Kubernetes를 실무에서 어떻게 사용했는지" 경험 정리 | 없으면 학습/실습 경험이라도 |

**핵심:** K8s는 DevOps 면접의 핵심입니다. 아키텍처 전체 흐름을 반드시 그림으로 그릴 수 있어야 합니다.

---

### D-4 | CI/CD + GitOps + IaC (2~3시간)

| 순서 | 내용 | 비고 |
|------|------|------|
| 1 | CI/CD 파이프라인 설계(Pipeline Design) | `04-cicd-and-gitops/01-cicd-pipeline-design.md` |
| 2 | GitOps 개념 및 ArgoCD / Flux 비교 | Push vs Pull 배포 모델 |
| 3 | Terraform 기초(Fundamentals) | `05-iac-and-cloud/01-terraform-fundamentals.md` |
| 4 | IaC(Infrastructure as Code) 장점과 실무 적용 패턴 | state 관리, 모듈화 |
| 5 | 🎤 "CI/CD 파이프라인을 설계한다면 어떻게 구성하시겠습니까?" 답변 연습 | Build -> Test -> Deploy 흐름 |
| 6 | 🎤 "IaC를 도입한 경험 또는 도입한다면?" 답변 연습 | 폐쇄망 환경 연계 가능 |

**핵심:** 올거나이즈는 SaaS 제품을 운영하므로 배포 자동화와 GitOps에 대한 이해를 중시할 가능성이 높습니다.

---

### D-3 | 클라우드(AWS/Azure) + 모니터링/관측 가능성 (2~3시간)

| 순서 | 내용 | 비고 |
|------|------|------|
| 1 | 클라우드 핵심 서비스 정리 (VPC, EC2/VM, IAM, S3/Blob) | 올거나이즈는 AWS + Azure 혼합 사용 추정 |
| 2 | 관측 가능성(Observability) 3대 축 학습 | `06-observability-and-monitoring/01-three-pillars.md` |
| 3 | Metrics, Logs, Traces 각각의 도구 정리 | Prometheus, Grafana, ELK, Jaeger 등 |
| 4 | 🎤 "장애가 발생했을 때 어떻게 원인을 추적하시겠습니까?" 답변 연습 | Dashboard -> Logs -> Traces 순서 |
| 5 | 🎤 "클라우드 환경 설계 경험" 또는 "온프레미스 vs 클라우드 비교" 답변 연습 | 온프레미스 경험을 강점으로 전환 |

**핵심:** 모니터링은 DevOps의 핵심 역량입니다. "만들고 끝"이 아니라 "운영하고 개선"하는 사람임을 보여주세요.

---

### D-2 | 성능/보안 + DB(MongoDB/ES) + 기술 질문 연습 (3시간)

| 순서 | 내용 | 비고 |
|------|------|------|
| 1 | 성능 분석(Performance Analysis) | `07-performance-and-security/01-performance-analysis.md` |
| 2 | 보안 기초: TLS, Secret 관리, RBAC, 네트워크 정책(Network Policy) | DevOps 보안 필수 지식 |
| 3 | MongoDB 운영 기초 (Replica Set, Sharding, 백업) | 올거나이즈 사용 추정 DB |
| 4 | Elasticsearch 운영 기초 (Cluster, Index, 성능 튜닝) | AI/NLP 기업 특성상 높은 확률 |
| 5 | 🎤 기술 질문 30개 빠르게 답변 연습 (문서별 핵심 Q&A) | 각 답변 1분 이내 |
| 6 | 🎤 "가장 어려웠던 장애 대응 경험" STAR 기법으로 준비 | Situation-Task-Action-Result |

**핵심:** 답변은 "핵심 먼저, 부연 나중에" 구조로. 장황하게 말하지 않는 연습이 중요합니다.

---

### D-1 | 시나리오/행동 질문 연습 + 치트시트 복습 + 모의 면접 (2~3시간)

| 순서 | 내용 | 비고 |
|------|------|------|
| 1 | 치트시트(Cheatsheets) 전체 빠르게 복습 | `10-cheatsheets/` 폴더 |
| 2 | 🎤 시나리오 질문 연습: "서비스가 갑자기 느려졌습니다. 어떻게 대응하시겠습니까?" | 체계적 접근법 |
| 3 | 🎤 행동 질문 연습: "팀원과 의견 충돌 시 어떻게 해결했습니까?" | 협업 경험 |
| 4 | 🎤 역질문 3~5개 준비 | "팀 구성은?", "배포 주기는?", "현재 기술 스택 고민은?" |
| 5 | 🎤 전체 모의 면접 1회 (자기소개 -> 기술질문 5개 -> 역질문) | 타이머 30분 세팅 |
| 6 | 취침 전 자기소개 + 핵심 답변 3개만 마지막 복습 | 과도한 벼락치기 금지 |

**핵심:** D-1은 새로운 것을 배우는 날이 아닙니다. 아는 것을 **입으로** 정리하는 날입니다.

---

## 전체 체크리스트

읽고 학습한 항목에 체크하세요.

### 01. 회사 조사 (Company Research)

- [ ] `01-company-research/01-allganize-overview.md` — 올거나이즈 회사/제품/기술 스택 | ⭐ | 🔴 필수

### 02. Linux 기초 (Linux Fundamentals)

- [ ] `02-linux-fundamentals/01-process-management.md` — 프로세스 관리 | ⭐⭐ | 🔴 필수

### 03. 컨테이너 & Kubernetes (Container & Kubernetes)

- [ ] `03-container-and-kubernetes/01-container-internals.md` — 컨테이너 내부구조 | ⭐⭐ | 🔴 필수
- [ ] `03-container-and-kubernetes/02-kubernetes-architecture.md` — K8s 아키텍처 | ⭐⭐⭐ | 🔴 필수

### 04. CI/CD & GitOps

- [ ] `04-cicd-and-gitops/01-cicd-pipeline-design.md` — CI/CD 파이프라인 설계 | ⭐⭐ | 🔴 필수

### 05. IaC & 클라우드 (IaC & Cloud)

- [ ] `05-iac-and-cloud/01-terraform-fundamentals.md` — Terraform 기초 | ⭐⭐ | 🟡 권장

### 06. 관측 가능성 & 모니터링 (Observability & Monitoring)

- [ ] `06-observability-and-monitoring/01-three-pillars.md` — 관측 가능성 3대 축 | ⭐⭐ | 🔴 필수

### 07. 성능 & 보안 (Performance & Security)

- [ ] `07-performance-and-security/01-performance-analysis.md` — 성능 분석 | ⭐⭐ | 🟡 권장

### 08. 데이터베이스 (Databases)

- [ ] `08-databases/` — MongoDB, Elasticsearch 운영 기초 (문서 작성 예정) | ⭐⭐ | 🟢 선택

### 09. 면접 Q&A (Interview Q&A)

- [ ] `09-interview-qa/` — 기술/행동/시나리오 질문 모음 (문서 작성 예정) | ⭐ | 🔴 필수

### 10. 치트시트 (Cheatsheets)

- [ ] `10-cheatsheets/` — 핵심 명령어 및 개념 요약 (문서 작성 예정) | ⭐ | 🟡 권장

> **난이도 범례:** ⭐ 쉬움 / ⭐⭐ 보통 / ⭐⭐⭐ 어려움  
> **중요도 범례:** 🔴 필수 — 반드시 학습 / 🟡 권장 — 시간이 허락하면 / 🟢 선택 — 여유가 있을 때

---

## 핵심 전략 요약

### "순수 DevOps 경력이 짧다"는 약점 전환 전략

DevOps는 단일 기술이 아니라 **문화이자 실천 방법론(Practice)**입니다. 10년 넘는 IT 인프라 경험은 DevOps의 근간을 이미 갖추고 있다는 뜻입니다. 면접에서는 다음과 같이 프레이밍(Framing)을 전환하세요:

| 약점으로 들릴 수 있는 표현 | 강점으로 전환한 표현 |
|---|---|
| "DevOps 경력이 짧습니다" | "10년간 인프라 운영을 해오면서 DevOps 방법론을 자연스럽게 체득했고, 최근에는 이를 체계화하는 데 집중하고 있습니다" |
| "클라우드 경험이 적습니다" | "폐쇄망/온프레미스 환경에서 밑바닥부터 인프라를 구축한 경험이 있어, 클라우드 서비스의 내부 동작 원리를 깊이 이해하고 있습니다" |
| "쿠버네티스 실무 경험이 부족합니다" | "컨테이너의 근간인 Linux 커널(namespace, cgroup)을 깊이 이해하고 있어 K8s 학습과 트러블슈팅에 강점이 있습니다" |

### 면접에서 반드시 어필할 3가지 포인트

1. **깊은 인프라 이해력 (Deep Infrastructure Understanding)**
   - "저는 관리형 서비스(Managed Service) 뒤에서 무슨 일이 일어나는지 아는 사람입니다."
   - 폐쇄망 환경에서 네트워크, 보안, 스토리지를 직접 설계하고 운영한 경험을 구체적으로 어필하세요.

2. **다양한 환경에서의 적응력 (Adaptability Across Environments)**
   - 온프레미스, 연구망, 모바일, AI 데이터센터 등 다양한 환경을 경험했다는 것은 **어떤 환경에서든 빠르게 적응할 수 있다**는 증거입니다.
   - 올거나이즈의 멀티클라우드/하이브리드 환경에서도 이 적응력이 빛을 발할 것임을 강조하세요.

3. **AI 도메인에 대한 이해와 열정 (AI Domain Understanding)**
   - 현재 AI 데이터센터 컨설팅 기업에 재직 중이라는 점을 활용하세요.
   - AI/ML 워크로드의 특수성(GPU 리소스 관리, 대용량 데이터 처리, 모델 서빙)에 대한 이해를 보여주세요.
   - 올거나이즈의 LLM 기반 제품에 기여하고 싶은 구체적 동기를 이야기하세요.

### 주의할 점 (하지 말아야 할 것들)

| 번호 | 하지 말 것 | 대신 할 것 |
|------|-----------|-----------|
| 1 | "잘 모르겠습니다"로 끝내기 | "직접 해본 적은 없지만, 원리는 이렇게 이해하고 있습니다. 제가 이해한 게 맞는지 확인 부탁드립니다." |
| 2 | 경력의 짧음을 먼저 언급하기 | 질문에 대해 아는 것부터 답변하고, 부족한 부분은 학습 의지로 마무리 |
| 3 | 기술 용어 나열만 하기 | 반드시 **경험 기반 사례**와 함께 설명 ("X를 도입해서 Y 문제를 Z처럼 해결했습니다") |
| 4 | 이전 회사/팀을 부정적으로 언급하기 | 환경의 어려움을 성장의 기회로 표현 |
| 5 | 질문 의도를 파악하지 않고 바로 답변하기 | "혹시 ~ 관점에서 여쭤보시는 건가요?" 확인 후 답변 |
| 6 | 역질문 없이 면접 마무리 | 반드시 2~3개 역질문 준비 (팀, 기술 스택, 성장 기회) |

---

## 폴더 구조

```
allganize-interview-prep/
├── README.md                          # 이 파일 (마스터 학습 가이드)
│
├── 01-company-research/               # 회사 조사
│   └── 01-allganize-overview.md       #   올거나이즈 회사/제품/기술 스택
│
├── 02-linux-fundamentals/             # Linux 기초
│   └── 01-process-management.md       #   프로세스 관리
│
├── 03-container-and-kubernetes/       # 컨테이너 & Kubernetes
│   ├── 01-container-internals.md      #   컨테이너 내부구조
│   └── 02-kubernetes-architecture.md  #   Kubernetes 아키텍처
│
├── 04-cicd-and-gitops/                # CI/CD & GitOps
│   └── 01-cicd-pipeline-design.md     #   CI/CD 파이프라인 설계
│
├── 05-iac-and-cloud/                  # IaC & 클라우드
│   └── 01-terraform-fundamentals.md   #   Terraform 기초
│
├── 06-observability-and-monitoring/   # 관측 가능성 & 모니터링
│   └── 01-three-pillars.md            #   관측 가능성 3대 축 (Metrics, Logs, Traces)
│
├── 07-performance-and-security/       # 성능 & 보안
│   └── 01-performance-analysis.md     #   성능 분석
│
├── 08-databases/                      # 데이터베이스 (MongoDB, Elasticsearch)
│   └── (문서 작성 예정)
│
├── 09-interview-qa/                   # 면접 질문 & 답변
│   └── (문서 작성 예정)
│
└── 10-cheatsheets/                    # 치트시트 (핵심 요약)
    └── (문서 작성 예정)
```

---

## 면접 당일 체크리스트

### 면접 60분 전

- [ ] 충분한 수면을 취했는지 확인 (최소 6시간)
- [ ] 자기소개 1분 버전 마지막 1회 발화 연습
- [ ] 핵심 어필 포인트 3가지 머릿속 정리

### 면접 30분 전 — 비대면 환경 세팅

- [ ] **인터넷 연결** 확인 (유선 LAN 권장, WiFi라면 5GHz 대역 사용)
- [ ] **카메라** 작동 확인 — 눈높이에 맞게 위치 조정
- [ ] **마이크** 작동 확인 — 이어폰/헤드셋 마이크 권장 (에코 방지)
- [ ] **조명** 확인 — 얼굴이 밝게 보이도록 정면 또는 45도 각도에서 조명
- [ ] **배경** 정리 — 깔끔한 벽면 또는 블러(Blur) 배경 설정
- [ ] **화상 회의 앱** 최신 버전 업데이트 확인 (Zoom, Google Meet, Teams 등)
- [ ] 불필요한 프로그램 종료 (알림, 메신저, 슬랙 등 모두 Off)
- [ ] 스마트폰 무음 모드 설정

### 면접 10분 전 — 준비물 세팅

- [ ] **물** 한 잔 (목이 마를 때 자연스럽게 마실 수 있도록)
- [ ] **메모장 + 펜** (질문 메모용, 화면에 보이지 않는 위치에)
- [ ] **이력서 출력본** 또는 화면 한쪽에 띄워두기
- [ ] **역질문 목록** 메모해두기 (아래 예시 참고)
- [ ] 면접 링크 미리 접속하여 대기

### 역질문 예시 (2~3개 선택)

1. "DevOps 팀의 현재 규모와 구성은 어떻게 되나요?"
2. "현재 배포 주기(Deployment Frequency)는 어떻게 되시나요?"
3. "팀에서 현재 가장 크게 느끼시는 기술적 과제(Technical Challenge)는 무엇인가요?"
4. "신규 입사자의 온보딩(Onboarding) 프로세스는 어떻게 진행되나요?"
5. "올거나이즈의 기술 스택에서 향후 변화가 예상되는 부분이 있나요?"

---

## 마지막 한마디

> 면접은 **시험이 아니라 대화**입니다.  
> 모든 것을 완벽하게 알 필요는 없습니다.  
> 모르는 것은 솔직하게, 아는 것은 자신있게,  
> 그리고 배우고 싶은 것은 열정적으로 이야기하세요.  
>  
> 10년의 인프라 경험은 절대 가볍지 않습니다.  
> 그 경험 위에 DevOps를 얹으면 **다른 후보자가 따라올 수 없는 깊이**가 됩니다.  
> 자신감을 가지세요. 화이팅!
