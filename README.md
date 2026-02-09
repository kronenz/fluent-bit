# Fluent Bit Operator + OpenSearch 로그 파이프라인

Kubernetes 환경에서 HostPath 기반 애플리케이션 로그를 수집하여 OpenSearch에 저장하고 분석하는 완전한 파이프라인입니다.

**개발 언어:** Bash, YAML
**대상 환경:** Kubernetes 1.19+
**로그 포맷:** Java Log4j2 JSON (multiline)

---

## 개요

본 프로젝트는 다음과 같은 문제를 해결합니다:

- **Kubernetes를 모르는 개발자도 로그 수집을 쉽게 설정할 수 있도록 상세 가이드 제공**
- **HostPath를 통한 안정적인 파일 기반 로그 수집** (컨테이너 stdout이 아님)
- **대량 로그 처리 시 OOM 방지** (4계층 방어 전략)
- **multiline JSON 로그 자동 파싱** (stacktrace 포함)
- **클러스터 전체의 통합 로그 관리**

### 핵심 특징

1. **ClusterFluentBitConfig 기반 선언적 파이프라인**
   - Fluent Bit Operator의 CRD를 활용한 쉬운 설정 관리
   - label selector로 모든 파이프라인 리소스 자동 연결

2. **HostPath 볼륨 기반 파일 로그**
   - Pod 삭제 후에도 로그 데이터 유지
   - 노드의 `/var/log/{namespace}/` 경로에 저장

3. **4계층 OOM 방어**
   - Layer 1: Input memBufLimit (Backpressure)
   - Layer 2: ClusterFluentBitConfig storage (파일시스템 버퍼)
   - Layer 3: Throttle Filter (속도 제한)
   - Layer 4: Pod resource limits (최후의 방어선)

4. **Lua 스크립트로 메타데이터 자동 추가**
   - 파일 경로에서 네임스페이스 자동 추출
   - 클러스터 식별 정보 추가

---

## 아키텍처

```
┌────────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                         │
├────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Your Service Pods (your-service namespace)              │  │
│  │  ├─ /var/log/your-service/app.log (HostPath)           │  │
│  │  └─ Log4j2 JSON 로그 기록                               │  │
│  └──────────────────────────────────────────────────────────┘  │
│          ↓ (HostPath Volume)                                   │
│          │                                                     │
│  /var/log/your-service/app.log (Node Filesystem)             │
│          ↓                                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Fluent Bit DaemonSet (logging namespace)                │  │
│  │  ├─ ClusterFluentBitConfig: 파이프라인 허브              │  │
│  │  ├─ ClusterInput: tail로 /var/log/*/app*.log 감시       │  │
│  │  ├─ ClusterFilter: Lua로 메타데이터 추가 + Throttle     │  │
│  │  ├─ ClusterMultilineParser: JSON multiline 파싱         │  │
│  │  └─ ClusterOutput: OpenSearch 전송                      │  │
│  └──────────────────────────────────────────────────────────┘  │
│          ↓ (HTTP)                                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  OpenSearch Cluster (logging namespace)                  │  │
│  │  ├─ Index: app-logs-YYYY.MM.DD                          │  │
│  │  └─ Document: { "log": "...", "namespace": "...", ... } │  │
│  └──────────────────────────────────────────────────────────┘  │
│          ↓                                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  OpenSearch Dashboards (UI)                              │  │
│  │  └─ 로그 검색 및 시각화                                  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└────────────────────────────────────────────────────────────────┘
```

---

## 디렉토리 구조

```
/home/bsh/develop/fluent-bit/
├── README.md                                    # 이 파일
├── connection.md                                # 클러스터 접속 정보
├── goal.md                                      # 프로젝트 목표
│
├── docs/                                        # 개발자 가이드
│   ├── service-team-guide.md                   # 서비스팀 개발자 YAML 작성 가이드
│   ├── troubleshooting.md                      # 트러블슈팅 가이드
│   └── oom-tuning-guide.md                     # OOM 방지 튜닝 가이드
│
├── infra/                                       # 인프라 배포 (Helm)
│   ├── namespace.yaml                          # logging, sample-app 네임스페이스
│   ├── opensearch/
│   │   └── values.yaml                         # OpenSearch Helm values
│   ├── opensearch-dashboards/
│   │   └── values.yaml                         # OpenSearch Dashboards Helm values
│   └── fluent-bit-operator/
│       └── values.yaml                         # Fluent Bit Operator Helm values
│
├── pipeline/                                    # Fluent Bit CRD 파이프라인
│   ├── cluster-fluentbit-config.yaml           # 파이프라인 연결 허브 (필수!)
│   ├── cluster-multiline-parser.yaml           # multiline JSON 파서
│   ├── cluster-input-hostpath.yaml             # tail input: /var/log/*/app*.log
│   ├── cluster-filter-modify.yaml              # Lua + Throttle + 메타데이터
│   ├── cluster-output-opensearch.yaml          # OpenSearch output
│   └── lua-scripts-configmap.yaml              # Lua 스크립트
│
├── sample-app/                                  # 검증용 샘플 애플리케이션
│   ├── deployment.yaml                         # HostPath 설정 포함 Deployment
│   ├── configmap.yaml                          # 로그 생성 스크립트
│   └── Dockerfile                              # 로그 생성기 이미지 (선택)
│
└── scripts/                                     # 배포 및 검증 스크립트
    ├── .env.example                            # SSH 접속 정보 템플릿
    ├── 00-prereq.sh                            # 사전 준비 (Helm repo, sshpass)
    ├── 01-deploy-opensearch.sh                 # OpenSearch 배포
    ├── 02-deploy-fluent-bit-operator.sh        # Fluent Bit Operator 배포
    ├── 03-apply-pipeline.sh                    # Pipeline CRD 적용
    ├── 04-deploy-sample-app.sh                 # 샘플 앱 배포
    ├── 05-verify.sh                            # E2E 검증
    └── teardown.sh                             # 전체 정리
```

---

## 빠른 시작

### 전제 조건

- Kubernetes 1.19 이상
- kubectl 설치 및 클러스터 접근 권한
- Helm 3.0 이상
- SSH 클라이언트 (원격 클러스터의 경우)

### Step 1: 리포지토리 준비

```bash
cd /home/bsh/develop/fluent-bit

# .env 파일 생성 (SSH 접속 정보)
cp scripts/.env.example scripts/.env

# .env 파일 편집 - 실제 접속 정보 입력
vi scripts/.env
```

### Step 2: 순차 배포

각 스크립트를 순서대로 실행합니다:

```bash
# 사전 준비 (Helm repo, sshpass)
bash scripts/00-prereq.sh

# OpenSearch 배포 (5~10분)
bash scripts/01-deploy-opensearch.sh

# Fluent Bit Operator 배포 (2~3분)
bash scripts/02-deploy-fluent-bit-operator.sh

# Pipeline CRD 적용
bash scripts/03-apply-pipeline.sh

# 샘플 앱 배포 (로그 생성)
bash scripts/04-deploy-sample-app.sh

# E2E 검증
bash scripts/05-verify.sh
```

### Step 3: OpenSearch Dashboards 접근

```bash
# Port Forward
kubectl port-forward -n logging svc/dashboards 5601:5601

# 브라우저: http://localhost:5601
```

---

## 주요 구성요소

### 1. ClusterFluentBitConfig (필수!)

전체 파이프라인을 연결하는 허브입니다. **이 리소스가 없으면 파이프라인이 동작하지 않습니다.**

```bash
kubectl get clusterfluentbitconfig
kubectl get clusterfluentbitconfig fluent-bit-config -o yaml
```

**역할:**
- label selector로 ClusterInput, ClusterFilter, ClusterOutput 연결
- Service 레벨 버퍼 및 storage 설정
- OOM 방지를 위한 메모리/파일시스템 튜닝

### 2. Fluent Bit DaemonSet

각 노드에서 실행되는 로그 수집 에이전트입니다.

```bash
kubectl get daemonset -n logging
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit
```

### 3. OpenSearch

로그 데이터를 저장하고 검색할 수 있는 저장소입니다.

```bash
kubectl exec -n logging opensearch-cluster-master-0 -- curl -s http://localhost:9200/_cluster/health
```

### 4. Lua ConfigMap

파일 경로에서 네임스페이스를 추출하는 스크립트입니다.

```bash
kubectl get configmap -n logging fluent-bit-lua-scripts -o yaml
```

---

## 서비스 로그 수집 설정

### 기존 서비스에 로그 수집 적용하기

1. **가이드 문서 읽기**
   ```bash
   cat docs/service-team-guide.md
   ```

2. **Deployment YAML에 다음 추가:**
   - `volumes` 섹션 (hostPath)
   - `volumeMounts` 섹션
   - `securityContext` (runAsUser: 1000)
   - `initContainers` (chown 1000:1000)

3. **Log4j2 설정**
   - JSON Layout 활성화
   - 로그 경로: `/var/log/{namespace}/app*.log`

4. **배포 및 검증**
   ```bash
   kubectl apply -f your-service/deployment.yaml
   kubectl logs -n your-service POD_NAME
   ```

자세한 내용은 [docs/service-team-guide.md](./docs/service-team-guide.md)를 참조하세요.

---

## 문제 해결

### 로그가 OpenSearch에 안 보여요

[docs/troubleshooting.md](./docs/troubleshooting.md)의 "로그가 OpenSearch에 안 보일 때" 섹션을 따르세요.

**빠른 체크리스트:**
1. ClusterFluentBitConfig 존재? → `kubectl get clusterfluentbitconfig`
2. 로그 파일이 노드에 존재? → `ls -la /var/log/YOUR_NAMESPACE/`
3. Fluent Bit 로그 확인 → `kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit`
4. OpenSearch에 인덱스 생성? → `curl http://localhost:9200/_cat/indices?v`

### OOM 또는 대량 로그 처리

[docs/oom-tuning-guide.md](./docs/oom-tuning-guide.md)를 참조하세요.

**4계층 방어 전략:**
- Layer 1: ClusterInput memBufLimit
- Layer 2: ClusterFluentBitConfig storage (파일시스템)
- Layer 3: Throttle Filter
- Layer 4: Pod resource limits

---

## 배포 해제

전체 파이프라인을 제거합니다:

```bash
bash scripts/teardown.sh
```

---

## 문서

| 문서 | 대상 | 내용 |
|------|------|------|
| [service-team-guide.md](./docs/service-team-guide.md) | 서비스팀 개발자 | YAML 작성 방법, Volume/VolumeMount, 권한 설정 |
| [troubleshooting.md](./docs/troubleshooting.md) | 운영/개발팀 | 문제 진단, 체크리스트, 디버깅 명령어 |
| [oom-tuning-guide.md](./docs/oom-tuning-guide.md) | 운영팀 | OOM 방지, 4계층 방어, 파라미터 튜닝 |

---

## 기술 스택

| 컴포넌트 | 버전 | 역할 |
|---------|------|------|
| Kubernetes | 1.19+ | 컨테이너 오케스트레이션 |
| Fluent Bit Operator | 0.20.0+ | CRD 기반 파이프라인 관리 |
| Fluent Bit | 1.9.0+ | 로그 수집 에이전트 |
| OpenSearch | 2.x | 로그 저장 및 검색 |
| OpenSearch Dashboards | 2.x | 로그 시각화 |

---

## 주요 설정 포인트

### ClusterFluentBitConfig (CRD)
- **storage.path**: 파일시스템 버퍼 저장 경로
- **maxChunksUp**: 메모리에 올릴 최대 청크 수 (OOM 튜닝)
- **emitterStorageType**: filesystem (OOM 방지)

### ClusterInput (CRD)
- **memBufLimit**: 입력 버퍼 메모리 제한 (필수)
- **storageType**: filesystem (OOM 방지)
- **path**: `/var/log/*/app*.log` 패턴

### Deployment (서비스)
- **volumes**: hostPath with DirectoryOrCreate
- **volumeMounts**: /var/log/{namespace}
- **securityContext**: runAsUser: 1000, runAsGroup: 1000
- **initContainers**: chown 1000:1000

---

## 성능 특성

### 로그 처리량

| 시나리오 | 로그 속도 | 메모리 | 설정 |
|---------|----------|--------|------|
| 일반 | < 100건/초 | 128Mi | 기본값 |
| 중량 | 100~1000건/초 | 256Mi | memBufLimit 10MB, throttle 1000 |
| 대량 | > 1000건/초 | 512Mi | filesystem storage, maxChunksUp 256 |

### 지연시간

- **Input 지연**: < 5초 (refreshIntervalSeconds: 5)
- **Parsing 지연**: < 1초 (multiline flushTimeout: 5000ms)
- **Output 지연**: < 10초 (OpenSearch 응답 시간)

---

## 보안

### 현재 설정 (검증 환경)

```yaml
OpenSearch:
  DISABLE_SECURITY_PLUGIN: "true"   # 인증 없음

Fluent Bit:
  httpServer: true                   # 메트릭 포트 2020 (내부만 접근)
```

### 프로덕션 환경 변경

1. **OpenSearch 보안 플러그인 활성화**
   ```yaml
   DISABLE_SECURITY_PLUGIN: "false"
   OPENSEARCH_JAVA_OPTS: "-Xms512m -Xmx512m"
   ```

2. **Fluent Bit 인증 추가**
   ```yaml
   httpUser: fluent
   httpPassword: $(kubectl get secret -n logging fluent-bit-auth -o jsonpath='{.data.password}')
   ```

3. **TLS 활성화**
   ```yaml
   tls:
     enabled: true
     verify: true
     ca_file: /etc/ssl/certs/ca-certificates.crt
   ```

---

## 제한사항

### 현재 설정

- **싱글 노드 OpenSearch** (검증용)
- **인증 없음** (DISABLE_SECURITY_PLUGIN=true)
- **TLS 미사용**
- **Kafka/Logstash 없음** (직접 전송)

### 향후 개선 방향

1. OpenSearch 클러스터 HA 구성
2. 보안 플러그인 및 RBAC 활성화
3. TLS/mTLS 적용
4. Prometheus 메트릭 수집
5. 로그 보존 정책 설정

---

## 지원 및 문의

문제가 발생하면:

1. [troubleshooting.md](./docs/troubleshooting.md)의 체크리스트 확인
2. Fluent Bit 로그 확인: `kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit`
3. OpenSearch 상태 확인: `curl http://localhost:9200/_cluster/health`
4. Pod 상세 정보: `kubectl describe pod -n logging POD_NAME`

---

## 라이선스

이 프로젝트는 교육 및 검증 목적으로 제공됩니다.

---

**생성일**: 2025년 2월 9일
**마지막 수정**: 2025년 2월 9일
**상태**: 검증 환경 구성 완료
