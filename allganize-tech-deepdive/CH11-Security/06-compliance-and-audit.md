# Compliance & Audit: Audit Logs, Falco, CIS Benchmark, ISMS

> **TL;DR**: Kubernetes Audit Log는 "누가, 언제, 무엇을, 어떻게" API를 호출했는지 기록하며, 보안 사고 조사와 컴플라이언스의 기본이다.
> Falco는 런타임에서 컨테이너의 비정상 행위(shell 실행, 파일 변조, 네트워크 이상)를 eBPF/커널 모듈 기반으로 실시간 탐지한다.
> CIS Kubernetes Benchmark는 클러스터 보안 설정의 체크리스트이며, ISMS(정보보호관리체계) 인증은 한국 기업의 보안 컴플라이언스 필수 요건이다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Kubernetes Audit Log 아키텍처

```
  API 요청
     │
     ▼
  ┌──────────────────────────────────────────────┐
  │  kube-apiserver                               │
  │                                               │
  │  Authentication → Authorization → Admission   │
  │       │              │              │          │
  │       ▼              ▼              ▼          │
  │  ┌──────────────────────────────────────┐     │
  │  │         Audit Policy Engine          │     │
  │  │                                      │     │
  │  │  Stage:                              │     │
  │  │  ├ RequestReceived  (요청 수신)      │     │
  │  │  ├ ResponseStarted  (응답 시작)      │     │
  │  │  ├ ResponseComplete (응답 완료)      │     │
  │  │  └ Panic           (서버 오류)      │     │
  │  │                                      │     │
  │  │  Level:                              │     │
  │  │  ├ None           (기록 안 함)       │     │
  │  │  ├ Metadata       (메타데이터만)     │     │
  │  │  ├ Request        (요청 본문 포함)   │     │
  │  │  └ RequestResponse(요청+응답 본문)   │     │
  │  └──────────────────────────────────────┘     │
  │       │                                       │
  │       ▼                                       │
  │  Audit Backend:                               │
  │  ├ Log (파일)                                  │
  │  ├ Webhook (외부 시스템)                       │
  │  └ Dynamic (AuditSink API)                    │
  └──────────────────────────────────────────────┘
```

### Audit Policy 설정

```yaml
# /etc/kubernetes/audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  # 1. Secret 접근은 메타데이터만 기록 (값 노출 방지)
  - level: Metadata
    resources:
    - group: ""
      resources: ["secrets"]

  # 2. ConfigMap 변경은 요청 본문까지 기록
  - level: Request
    resources:
    - group: ""
      resources: ["configmaps"]
    verbs: ["create", "update", "patch", "delete"]

  # 3. Pod 생성/삭제는 요청+응답 모두 기록
  - level: RequestResponse
    resources:
    - group: ""
      resources: ["pods"]
    verbs: ["create", "delete"]
    namespaces: ["ai-serving", "production"]

  # 4. RBAC 변경은 모두 기록 (보안 감사 핵심)
  - level: RequestResponse
    resources:
    - group: "rbac.authorization.k8s.io"
      resources: ["roles", "rolebindings", "clusterroles", "clusterrolebindings"]

  # 5. 읽기 전용 엔드포인트는 기록하지 않음 (로그 볼륨 관리)
  - level: None
    resources:
    - group: ""
      resources: ["events", "endpoints"]
  - level: None
    users: ["system:kube-proxy"]
    verbs: ["watch"]

  # 6. 기본: 메타데이터 수준으로 기록
  - level: Metadata
    omitStages:
    - "RequestReceived"
```

```bash
# apiserver 플래그 (kubeadm 환경)
# --audit-policy-file=/etc/kubernetes/audit-policy.yaml
# --audit-log-path=/var/log/kubernetes/audit.log
# --audit-log-maxage=30        # 30일 보관
# --audit-log-maxbackup=10     # 10개 백업 파일
# --audit-log-maxsize=100      # 100MB 당 로테이션

# EKS: CloudWatch Logs로 자동 전송 (Control Plane Logging 활성화)
aws eks update-cluster-config \
  --name my-cluster \
  --logging '{"clusterLogging":[{"types":["audit"],"enabled":true}]}'
```

### Audit Log 분석 예시

```json
{
  "kind": "Event",
  "apiVersion": "audit.k8s.io/v1",
  "level": "RequestResponse",
  "auditID": "xxx-xxx-xxx",
  "stage": "ResponseComplete",
  "requestURI": "/api/v1/namespaces/ai-serving/secrets",
  "verb": "list",
  "user": {
    "username": "developer@company.com",
    "groups": ["dev-team", "system:authenticated"]
  },
  "sourceIPs": ["10.0.1.50"],
  "userAgent": "kubectl/v1.28.0",
  "objectRef": {
    "resource": "secrets",
    "namespace": "ai-serving",
    "apiVersion": "v1"
  },
  "responseStatus": { "code": 200 },
  "requestReceivedTimestamp": "2024-01-15T09:30:00.000000Z",
  "stageTimestamp": "2024-01-15T09:30:00.050000Z"
}
```

```bash
# 특정 사용자의 Secret 접근 기록 조회
cat /var/log/kubernetes/audit.log | \
  jq 'select(.objectRef.resource == "secrets" and .user.username == "developer@company.com")'

# 비정상 시간대 API 호출 조회
cat /var/log/kubernetes/audit.log | \
  jq 'select(.requestReceivedTimestamp > "2024-01-15T22:00:00" and .requestReceivedTimestamp < "2024-01-16T06:00:00")'

# 403 Forbidden 응답 (권한 부족) 조회
cat /var/log/kubernetes/audit.log | \
  jq 'select(.responseStatus.code == 403)'
```

### Falco 런타임 보안

```
  ┌──────────────────────────────────────────────┐
  │  Falco Runtime Security                       │
  │                                               │
  │  ┌────────────┐                               │
  │  │   Kernel    │                               │
  │  │  Syscalls   │ ◄── eBPF probe / kmod         │
  │  └──────┬─────┘                               │
  │         │ 시스템 콜 이벤트                      │
  │         ▼                                      │
  │  ┌────────────┐                               │
  │  │ Falco       │                               │
  │  │ Engine      │                               │
  │  │  ├ Rules    │ ── YAML 기반 탐지 규칙         │
  │  │  ├ Parser   │ ── 이벤트 필터링/매칭          │
  │  │  └ Outputs  │ ── 알림 채널                   │
  │  └──────┬─────┘                               │
  │         │ 알림                                  │
  │         ▼                                      │
  │  ┌────────────────────────┐                   │
  │  │ Output Channels         │                   │
  │  │ ├ stdout (DaemonSet)    │                   │
  │  │ ├ Slack/PagerDuty       │                   │
  │  │ ├ Elasticsearch/Loki    │                   │
  │  │ └ Falcosidekick         │ ── 50+ 연동       │
  │  └────────────────────────┘                   │
  └──────────────────────────────────────────────┘
```

**Falco 탐지 시나리오**:

```
  ┌─────────────────────────────────────┐
  │  주요 탐지 항목                      │
  │                                      │
  │  컨테이너 내부:                       │
  │  ├ shell 실행 (bash, sh)             │
  │  ├ 민감 파일 읽기 (/etc/shadow 등)    │
  │  ├ 패키지 매니저 실행 (apt, yum)      │
  │  ├ 비정상 프로세스 생성               │
  │  └ /proc, /sys 접근                  │
  │                                      │
  │  네트워크:                            │
  │  ├ 비정상 아웃바운드 연결              │
  │  ├ 알려진 악성 IP 통신               │
  │  └ DNS 터널링 의심 패턴              │
  │                                      │
  │  Kubernetes:                          │
  │  ├ ServiceAccount 토큰 접근           │
  │  ├ Namespace 생성/삭제               │
  │  └ ConfigMap/Secret 비정상 접근       │
  └─────────────────────────────────────┘
```

**Falco Rules 예시**:

```yaml
# 컨테이너 내 shell 실행 탐지
- rule: Shell Spawned in Container
  desc: A shell was spawned in a container
  condition: >
    spawned_process and
    container and
    proc.name in (bash, sh, zsh, csh) and
    not container.image.repository in (allowed_shell_images)
  output: >
    Shell spawned in container
    (user=%user.name container=%container.name
     image=%container.image.repository
     shell=%proc.name parent=%proc.pname
     cmdline=%proc.cmdline)
  priority: WARNING
  tags: [container, shell, mitre_execution]

# 민감 파일 읽기 탐지
- rule: Read Sensitive File in Container
  desc: Sensitive file accessed in container
  condition: >
    open_read and
    container and
    fd.name in (/etc/shadow, /etc/passwd, /etc/pki) and
    not proc.name in (login, passwd, sshd)
  output: >
    Sensitive file read in container
    (file=%fd.name user=%user.name container=%container.name
     image=%container.image.repository)
  priority: WARNING

# Kubernetes Secret 접근 탐지
- rule: K8s Secret Access
  desc: Attempt to read K8s secrets
  condition: >
    open_read and
    fd.name startswith /var/run/secrets/kubernetes.io and
    not ka.user.name in (allowed_sa_list)
  output: >
    K8s secret accessed
    (file=%fd.name user=%user.name proc=%proc.name
     container=%container.name)
  priority: NOTICE

# AI 모델 파일 변조 탐지 (커스텀)
- rule: AI Model File Modified
  desc: Model weight file was modified
  condition: >
    open_write and
    container and
    fd.name glob "/models/*.bin" or
    fd.name glob "/models/*.safetensors"
  output: >
    AI model file modified
    (file=%fd.name user=%user.name container=%container.name
     image=%container.image.repository)
  priority: CRITICAL
  tags: [ai, integrity]
```

### CIS Kubernetes Benchmark

```
  CIS Benchmark 주요 섹션:

  ┌──────────────────────────────────────────┐
  │  1. Control Plane Components              │
  │     ├ 1.1 API Server                      │
  │     │   ├ 익명 인증 비활성화               │
  │     │   ├ RBAC 활성화                      │
  │     │   ├ Audit Logging 활성화             │
  │     │   └ Encryption at Rest 설정          │
  │     ├ 1.2 Scheduler                        │
  │     └ 1.3 Controller Manager               │
  │                                            │
  │  2. etcd                                   │
  │     ├ 클라이언트 인증서 인증                │
  │     ├ 피어 간 TLS                          │
  │     └ 데이터 디렉토리 권한                  │
  │                                            │
  │  3. Worker Nodes                           │
  │     ├ kubelet 인증/인가                     │
  │     ├ 파일 퍼미션                           │
  │     └ 커널 파라미터                         │
  │                                            │
  │  4. Policies                               │
  │     ├ RBAC/PSP 정책                        │
  │     ├ NetworkPolicy                        │
  │     └ Secret 관리                           │
  │                                            │
  │  5. Managed Services (EKS/AKS/GKE)        │
  │     ├ 로깅 활성화                           │
  │     ├ 네트워크 격리                         │
  │     └ 데이터 암호화                         │
  └──────────────────────────────────────────┘
```

```bash
# kube-bench로 CIS Benchmark 자동 검사
# 설치 및 실행
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml

# 또는 직접 실행 (노드에서)
kube-bench run --targets master,node,policies

# 결과 예시:
# [PASS] 1.1.1 Ensure that the API server pod specification file permissions are set to 644
# [FAIL] 1.1.2 Ensure that the API server pod specification file ownership is set to root:root
# [WARN] 1.1.3 Ensure that the proxy kubeconfig file permissions are set to 644
# [INFO] 1.1.4 Ensure that the kubelet kubeconfig file ownership is set to root:root

# EKS용 kube-bench
kube-bench run --benchmark eks-1.2.0

# 결과 요약
# == Summary total ==
# 45 checks PASS
# 12 checks FAIL
# 8 checks WARN
# 5 checks INFO
```

### ISMS (정보보호관리체계) 인증

```
  ┌──────────────────────────────────────────────────┐
  │  ISMS-P (정보보호 및 개인정보보호 관리체계)         │
  │                                                   │
  │  Kubernetes 관련 항목:                              │
  │                                                   │
  │  1. 접근 통제 (2.6)                                │
  │     ├ RBAC 기반 최소 권한 원칙                     │
  │     ├ 관리자 계정 분리 (admin vs operator)         │
  │     └ 접근 기록 관리 (Audit Log)                   │
  │                                                   │
  │  2. 암호화 (2.7)                                   │
  │     ├ 전송 중 암호화 (TLS/mTLS)                    │
  │     ├ 저장 중 암호화 (etcd Encryption at Rest)     │
  │     └ 키 관리 (Vault, KMS)                         │
  │                                                   │
  │  3. 로그 관리 및 모니터링 (2.11)                   │
  │     ├ Audit Log 6개월 이상 보관                    │
  │     ├ 비정상 행위 탐지 (Falco)                     │
  │     └ 보안 이벤트 대시보드                         │
  │                                                   │
  │  4. 취약점 관리 (2.9)                              │
  │     ├ 정기 취약점 스캔 (분기 1회 이상)              │
  │     ├ 패치 관리 프로세스                            │
  │     └ 취약점 조치 기한 준수                         │
  │                                                   │
  │  5. 사고 대응 (2.12)                               │
  │     ├ 침해 사고 대응 절차                          │
  │     ├ 증거 보전 (Forensics)                        │
  │     └ 사고 보고 체계                               │
  └──────────────────────────────────────────────────┘
```

---

## 실전 예시

### 통합 보안 모니터링 아키텍처

```
  ┌────────────────────────────────────────────────┐
  │  Security Monitoring Architecture               │
  │                                                 │
  │  K8s Audit Log ──┐                              │
  │  Falco Alerts ───┤                              │
  │  WAF Logs ───────┤                              │
  │  VPC Flow Logs ──┤    ┌──────────────┐         │
  │  CloudTrail ─────┼───►│ Log Pipeline │         │
  │                  │    │ (FluentBit/  │         │
  │                  │    │  Vector)     │         │
  │                  │    └──────┬───────┘         │
  │                  │           │                  │
  │                  │     ┌─────┴─────┐           │
  │                  │     ▼           ▼           │
  │                  │  ┌──────┐  ┌────────┐      │
  │                  │  │ Loki │  │  SIEM   │      │
  │                  │  │/ES   │  │(Splunk/ │      │
  │                  │  │      │  │ Elastic)│      │
  │                  │  └──┬───┘  └────┬───┘      │
  │                  │     │           │           │
  │                  │     ▼           ▼           │
  │                  │  ┌──────┐  ┌────────┐      │
  │                  │  │Grafana│  │Alert   │      │
  │                  │  │Dash  │  │(Slack/ │      │
  │                  │  │board │  │PagerD) │      │
  │                  │  └──────┘  └────────┘      │
  └────────────────────────────────────────────────┘
```

### Falco + Falcosidekick 배포

```yaml
# Helm으로 Falco 설치
# helm repo add falcosecurity https://falcosecurity.github.io/charts
# helm install falco falcosecurity/falco -n falco-system --create-namespace \
#   --set driver.kind=ebpf \
#   --set falcosidekick.enabled=true \
#   --set falcosidekick.config.slack.webhookurl=https://hooks.slack.com/xxx

# Falcosidekick 설정 (알림 채널)
config:
  slack:
    webhookurl: "https://hooks.slack.com/services/xxx"
    minimumpriority: "warning"
  elasticsearch:
    hostport: "http://elasticsearch:9200"
    index: "falco-alerts"
  alertmanager:
    hostport: "http://alertmanager:9093"
    minimumpriority: "critical"
```

### kube-bench CronJob 자동 검사

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kube-bench-scan
  namespace: security-system
spec:
  schedule: "0 2 * * 0"    # 매주 일요일 02:00
  jobTemplate:
    spec:
      template:
        spec:
          hostPID: true
          containers:
          - name: kube-bench
            image: aquasec/kube-bench:latest
            command: ["kube-bench", "run", "--json"]
            volumeMounts:
            - name: var-lib-kubelet
              mountPath: /var/lib/kubelet
              readOnly: true
            - name: etc-kubernetes
              mountPath: /etc/kubernetes
              readOnly: true
          volumes:
          - name: var-lib-kubelet
            hostPath:
              path: /var/lib/kubelet
          - name: etc-kubernetes
            hostPath:
              path: /etc/kubernetes
          restartPolicy: Never
```

### 보안 사고 대응 Runbook

```
  보안 사고 탐지 → 대응 흐름:

  1. 탐지 (Detection)
     ├ Falco Alert: "Shell spawned in container"
     ├ Audit Log: 비정상 Secret 접근
     └ 네트워크: 알 수 없는 외부 IP 통신

  2. 격리 (Containment)
     ├ NetworkPolicy로 해당 Pod 격리
     │   kubectl annotate pod <pod> quarantine=true
     │   → NetworkPolicy가 quarantine Pod 차단
     ├ ServiceAccount 토큰 무효화
     └ Node cordoning (필요시)

  3. 조사 (Investigation)
     ├ Audit Log에서 해당 Pod/SA의 API 호출 추적
     ├ Falco 이벤트에서 프로세스 트리 확인
     ├ Container 파일시스템 스냅샷 (forensics)
     │   kubectl cp <pod>:/suspicious/file ./evidence/
     └ 네트워크 로그 분석 (VPC Flow Logs)

  4. 제거 (Eradication)
     ├ 감염된 Pod 삭제
     ├ 이미지 취약점 패치 후 재배포
     └ Credential 로테이션

  5. 복구 (Recovery)
     ├ 정상 이미지로 재배포
     ├ 모니터링 강화 (추가 Falco 규칙)
     └ NetworkPolicy 정상화

  6. 사후 분석 (Post-Incident)
     ├ 타임라인 문서화
     ├ 근본 원인 분석 (RCA)
     └ 재발 방지 대책 수립
```

---

## 면접 Q&A

### Q: Kubernetes Audit Log의 구성 요소와 운영 시 주의사항을 설명해주세요.
**30초 답변**:
Audit Log는 Stage(RequestReceived, ResponseComplete 등)와 Level(None, Metadata, Request, RequestResponse)로 구성됩니다. Secret은 Metadata 수준으로만 기록하여 값 노출을 방지하고, 읽기 전용 이벤트는 None으로 설정하여 로그 볼륨을 관리해야 합니다.

**2분 답변**:
Audit Log는 apiserver의 모든 API 호출을 기록합니다. Policy에서 리소스별, 사용자별, Verb별로 로깅 수준을 차등 적용합니다. Secret은 Metadata만 기록하여 실제 값이 로그에 남지 않게 하고, RBAC 변경(Role, RoleBinding)은 RequestResponse로 전체 기록합니다. events나 endpoints 같은 빈번한 읽기 리소스는 None으로 제외하여 로그 볼륨을 관리합니다. Backend는 Log(파일)와 Webhook(외부 시스템) 두 가지가 있으며, 프로덕션에서는 Webhook으로 SIEM이나 Elasticsearch에 실시간 전송하는 것이 좋습니다. EKS에서는 Control Plane Logging을 활성화하면 CloudWatch Logs로 자동 전송됩니다. 주의사항으로는 로그 로테이션(maxage, maxsize)을 반드시 설정해야 디스크 고갈을 방지하고, ISMS 등 컴플라이언스에서는 최소 6개월 이상 보관을 요구합니다.

**💡 경험 연결**:
폐쇄망 온프레미스 환경에서 Audit Log를 파일로 저장하다가 디스크 풀로 apiserver가 중단된 경험이 있습니다. 이후 maxsize와 maxbackup을 설정하고, Fluentd로 중앙 로그 시스템에 전송하는 구조로 변경했습니다.

**⚠️ 주의**:
Audit Log의 RequestResponse 레벨을 무분별하게 적용하면 **로그 볼륨이 수십 GB/일**로 급증할 수 있다. 반드시 리소스별로 적절한 레벨을 차등 적용해야 한다.

### Q: Falco의 런타임 보안 탐지 원리와 주요 활용 사례를 설명해주세요.
**30초 답변**:
Falco는 eBPF 또는 커널 모듈을 통해 시스템 콜을 실시간 모니터링하고, YAML 기반 규칙으로 비정상 행위를 탐지합니다. 컨테이너 내 shell 실행, 민감 파일 접근, 비정상 네트워크 연결 등을 탐지하여 알림합니다.

**2분 답변**:
Falco는 CNCF 프로젝트로, 커널 수준에서 시스템 콜을 가로채어 컨테이너의 런타임 행위를 분석합니다. eBPF probe(권장) 또는 커널 모듈을 통해 파일 열기, 프로세스 생성, 네트워크 연결 등의 이벤트를 수집합니다. YAML 규칙에 condition(조건), output(알림 내용), priority(심각도)를 정의하여 비정상 행위를 탐지합니다. 주요 활용 사례는 세 가지입니다. 첫째, 컨테이너 탈출 탐지입니다. shell 실행, /proc이나 /sys 접근, 권한 상승 시도를 실시간 감지합니다. 둘째, 내부자 위협 탐지입니다. ServiceAccount 토큰 파일 접근, 비정상 시간대 활동을 감지합니다. 셋째, 컴플라이언스 모니터링입니다. 패키지 설치, 설정 파일 변경 등 불변 인프라(Immutable Infrastructure) 원칙 위반을 감지합니다. Falcosidekick을 통해 Slack, PagerDuty, Elasticsearch 등 50개 이상의 채널로 알림을 전달할 수 있어 기존 모니터링 시스템과 쉽게 통합됩니다.

**💡 경험 연결**:
온프레미스에서 auditd로 호스트 보안 모니터링을 한 경험이 있습니다. Falco는 auditd의 컨테이너 확장판으로 볼 수 있으며, 컨테이너 컨텍스트(이미지 이름, Pod 이름 등)가 포함되어 K8s 환경에서 훨씬 유용합니다.

**⚠️ 주의**:
Falco의 eBPF 드라이버는 커널 버전 호환성에 주의해야 한다. EKS Bottlerocket이나 최신 Ubuntu에서는 잘 동작하지만, 오래된 커널에서는 커널 모듈 방식을 사용해야 한다.

### Q: CIS Kubernetes Benchmark란 무엇이고, 어떻게 활용하나요?
**30초 답변**:
CIS Benchmark는 Center for Internet Security에서 제공하는 Kubernetes 보안 설정 가이드라인입니다. kube-bench 도구로 자동 검사할 수 있으며, Control Plane, Worker Node, 정책 관련 수백 개의 체크 항목으로 구성됩니다.

**2분 답변**:
CIS Kubernetes Benchmark는 apiserver, etcd, scheduler, kubelet 등 각 컴포넌트의 보안 설정을 체계적으로 검증하는 체크리스트입니다. kube-bench(Aqua Security)로 자동 검사가 가능하며, PASS/FAIL/WARN으로 결과를 제공합니다. 주요 검사 항목으로는 apiserver의 익명 인증 비활성화, RBAC 활성화, Audit Logging 설정, etcd의 TLS 통신, kubelet의 인증 설정 등이 있습니다. EKS/AKS 같은 관리형 서비스에서는 전용 Benchmark(eks-1.2.0 등)가 별도로 존재하며, Control Plane 항목은 클라우드 제공자가 관리하므로 Worker Node와 Policy 항목에 집중합니다. 실무에서는 CronJob으로 주기적 스캔을 자동화하고, FAIL 항목을 지속적으로 개선하는 프로세스를 운영합니다. ISMS 인증 시에도 CIS Benchmark 준수 현황을 증적 자료로 활용할 수 있습니다.

**💡 경험 연결**:
온프레미스 환경에서 CIS Benchmark를 처음 적용했을 때 FAIL 항목이 40% 이상이었습니다. 우선순위를 정해 3개월에 걸쳐 90% PASS까지 개선한 경험이 있으며, 이 과정에서 각 설정의 보안적 의미를 깊이 이해하게 되었습니다.

**⚠️ 주의**:
CIS Benchmark 100% PASS가 목표가 되어서는 안 된다. 일부 항목은 운영 환경 특성에 맞지 않을 수 있으며, **위험 수용(Risk Acceptance)과 보완 통제(Compensating Control)**를 문서화하는 것이 중요하다.

### Q: ISMS 인증에서 Kubernetes 보안 관련 준비사항은 무엇인가요?
**30초 답변**:
ISMS에서 K8s 관련 핵심 항목은 접근 통제(RBAC), 암호화(TLS/etcd encryption), 로그 관리(Audit Log 6개월 보관), 취약점 관리(정기 스캔), 사고 대응 절차입니다. 기술적 구현뿐 아니라 정책 문서화와 증적 관리가 중요합니다.

**2분 답변**:
ISMS-P 인증에서 Kubernetes 관련 주요 준비사항은 5개 영역입니다. 첫째, 접근 통제입니다. RBAC 기반 최소 권한 원칙을 적용하고, 관리자/운영자/개발자 권한을 분리하며, 접근 이력(Audit Log)을 관리합니다. 둘째, 암호화입니다. 전송 중(TLS/mTLS) 및 저장 중(etcd Encryption at Rest, EBS 암호화) 암호화를 적용하고, 키 관리 체계(KMS)를 수립합니다. 셋째, 로그 관리입니다. Audit Log를 최소 6개월 이상 보관하고, 비정상 접근 탐지를 위한 모니터링(Falco)을 운영합니다. 넷째, 취약점 관리입니다. 분기 1회 이상 취약점 스캔(kube-bench, Trivy)을 수행하고, 발견된 취약점의 조치 기한을 준수합니다. 다섯째, 사고 대응 절차입니다. 침해 사고 대응 매뉴얼, 증거 보전 절차, 사고 보고 체계를 문서화합니다. ISMS는 기술적 구현만이 아니라 **정책 → 구현 → 운영 → 증적**의 전체 사이클을 증명해야 합니다.

**💡 경험 연결**:
ISMS 인증 심사를 지원한 경험이 있으며, 특히 접근 통제와 로그 관리 영역에서 인프라 증적을 준비했습니다. Kubernetes 환경에서는 RBAC 정책 문서, Audit Log 보관 증빙, 취약점 스캔 리포트가 핵심 증적 자료입니다.

**⚠️ 주의**:
ISMS 심사에서는 "기술적으로 구현되어 있는가"뿐만 아니라 "정책 문서가 있는가", "정기적으로 검토하는가", "담당자가 지정되어 있는가"를 함께 확인한다. 기술만으로는 통과할 수 없다.

---

## Allganize 맥락

- **AI SaaS 컴플라이언스**: Allganize는 기업 고객에게 AI 서비스를 제공하므로, 고객사의 ISMS/ISO 27001 요구사항을 충족해야 한다. Audit Log와 접근 통제는 기본 요건.
- **LLM 서비스 런타임 보안**: AI 모델 서빙 Pod에서 비정상 행위(모델 파일 변조, 예상외 외부 통신)를 Falco로 탐지하면 AI 서비스의 신뢰성을 보장할 수 있다.
- **멀티테넌트 감사**: 고객별 Namespace의 API 접근 기록을 분리하여, 특정 고객의 데이터에 누가 접근했는지 추적 가능한 체계가 필요하다.
- **폐쇄망 경험 활용**: 보안 감사, 접근 통제, 로그 관리 경험은 환경(온프레미스/클라우드)에 관계없이 직접 적용 가능. ISMS 대응 경험은 매우 강력한 어필 포인트.
- **JD 연관**: "보안 정책 수립 및 운영", "인프라 취약점 관리"에 직접 대응. Audit Log + Falco + CIS Benchmark는 보안 운영의 3대 축.

---
**핵심 키워드**: `Audit-Log` `Audit-Policy` `Falco` `eBPF` `Runtime-Security` `CIS-Benchmark` `kube-bench` `ISMS` `Compliance` `Incident-Response` `Falcosidekick`
