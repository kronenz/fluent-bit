# Pod Security Standards & SecurityContext

> **TL;DR**: Pod Security Standards(PSS)는 Privileged/Baseline/Restricted 3단계로 Pod의 보안 수준을 정의하며, Pod Security Admission(PSA)이 이를 강제한다.
> SecurityContext는 Pod/Container 수준에서 runAsNonRoot, readOnlyRootFilesystem, capabilities 등 세부 보안 설정을 제어한다.
> PSP(PodSecurityPolicy)는 1.25에서 제거되었으며, PSA + OPA/Kyverno 조합이 현재 표준이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Pod Security Standards (PSS) 3단계

```
  ┌─────────────────────────────────────────────────┐
  │                  Privileged                       │
  │  제한 없음. 시스템 컴포넌트, CNI, 스토리지 드라이버용   │
  │  (kube-system namespace 등)                       │
  ├─────────────────────────────────────────────────┤
  │                  Baseline                         │
  │  알려진 권한 상승 차단. 대부분의 워크로드에 적합        │
  │  hostNetwork=false, privileged=false 등            │
  ├─────────────────────────────────────────────────┤
  │                  Restricted                       │
  │  최대 보안 강화. 보안 민감 워크로드에 적용             │
  │  runAsNonRoot=true, drop ALL capabilities 등       │
  └─────────────────────────────────────────────────┘
         ▲ 보안 수준 증가 / 허용 범위 감소
```

### Baseline vs Restricted 상세 비교

| 항목 | Baseline | Restricted |
|------|----------|------------|
| `hostNetwork` | false 강제 | false 강제 |
| `hostPID/hostIPC` | false 강제 | false 강제 |
| `privileged` | false 강제 | false 강제 |
| `capabilities` | NET_RAW 허용 | **ALL drop 필수** |
| `runAsNonRoot` | 제한 없음 | **true 필수** |
| `runAsUser` | 제한 없음 | **0(root) 금지** |
| `seccompProfile` | 제한 없음 | **RuntimeDefault 또는 Localhost** |
| `readOnlyRootFilesystem` | 제한 없음 | 권장 (필수 아님) |
| `allowPrivilegeEscalation` | 제한 없음 | **false 필수** |
| Volume 타입 | hostPath 금지 | hostPath 금지 + 허용 목록 제한 |

### Pod Security Admission (PSA)

```
  Pod 생성 요청
       │
       ▼
  ┌──────────────────────────────────────┐
  │  kube-apiserver                       │
  │        │                              │
  │        ▼                              │
  │  Pod Security Admission Controller    │
  │        │                              │
  │        ├── Namespace Label 확인        │
  │        │   pod-security.kubernetes.io/ │
  │        │     enforce: restricted       │
  │        │     warn: restricted          │
  │        │     audit: restricted         │
  │        │                              │
  │        ├── enforce → 위반 시 거부(403) │
  │        ├── warn → 위반 시 경고 표시    │
  │        └── audit → 위반 시 감사 로그   │
  └──────────────────────────────────────┘
```

**적용 방법 (Namespace Label)**:
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ai-serving
  labels:
    # enforce: 위반 시 Pod 생성 거부
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: v1.28
    # warn: 위반 시 kubectl에 경고 표시 (생성은 허용)
    pod-security.kubernetes.io/warn: restricted
    # audit: 위반 시 audit log에 기록
    pod-security.kubernetes.io/audit: restricted
```

### SecurityContext 상세

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-model-serving
  namespace: ai-serving
spec:
  template:
    spec:
      # ── Pod 수준 SecurityContext ──
      securityContext:
        runAsNonRoot: true           # root 실행 금지
        runAsUser: 1000              # UID 지정
        runAsGroup: 1000             # GID 지정
        fsGroup: 2000               # 볼륨 마운트 시 GID
        seccompProfile:
          type: RuntimeDefault       # seccomp 프로파일
        supplementalGroups: [3000]   # 추가 그룹

      containers:
      - name: model-server
        image: company/ai-model:v1

        # ── Container 수준 SecurityContext ──
        securityContext:
          allowPrivilegeEscalation: false   # setuid 비트 무시
          readOnlyRootFilesystem: true      # 루트 FS 읽기 전용
          capabilities:
            drop: ["ALL"]                   # 모든 Linux capability 제거
            add: ["NET_BIND_SERVICE"]       # 필요한 것만 추가

        # readOnlyRootFilesystem 사용 시 쓰기 필요한 경로
        volumeMounts:
        - name: tmp
          mountPath: /tmp
        - name: cache
          mountPath: /var/cache/model

      volumes:
      - name: tmp
        emptyDir: {}
      - name: cache
        emptyDir:
          sizeLimit: 1Gi
```

### Linux Capabilities 주요 항목

```
  ┌──────────────────────────────────────────┐
  │  Container Capabilities (drop ALL 후)     │
  │                                           │
  │  필요 시 개별 추가:                         │
  │  ├── NET_BIND_SERVICE  1024 미만 포트 바인딩│
  │  ├── SYS_PTRACE        디버깅 (distroless) │
  │  ├── NET_RAW           ping, raw socket   │
  │  └── CHOWN             파일 소유자 변경     │
  │                                           │
  │  절대 추가 금지:                            │
  │  ├── SYS_ADMIN         mount, namespace 등 │
  │  ├── NET_ADMIN         네트워크 설정 변경   │
  │  └── SYS_RAWIO         하드웨어 직접 접근   │
  └──────────────────────────────────────────┘
```

### Seccomp Profile

```yaml
# RuntimeDefault: 컨테이너 런타임의 기본 seccomp 프로파일
# (Docker/containerd 기본 차단: reboot, mount, ptrace 등)
securityContext:
  seccompProfile:
    type: RuntimeDefault

# 커스텀 프로파일: /var/lib/kubelet/seccomp/ 아래에 배치
securityContext:
  seccompProfile:
    type: Localhost
    localhostProfile: profiles/ai-model.json
```

### AppArmor / SELinux

```yaml
# AppArmor (annotation 기반, 1.30부터 field 지원)
metadata:
  annotations:
    container.apparmor.security.beta.kubernetes.io/model-server: runtime/default

# SELinux (SecurityContext field)
securityContext:
  seLinuxOptions:
    level: "s0:c123,c456"
    type: "container_t"
```

---

## 실전 예시

### PSA 단계적 적용 전략

```bash
# 1단계: dry-run으로 영향도 확인
kubectl label ns ai-serving \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted \
  --dry-run=server -o yaml

# 2단계: warn 모드로 경고만 표시
kubectl label ns ai-serving \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted

# 3단계: 모든 Pod가 호환되면 enforce 적용
kubectl label ns ai-serving \
  pod-security.kubernetes.io/enforce=restricted

# 기존 위반 Pod 확인
kubectl get pods -n ai-serving -o json | \
  jq '.items[] | select(.spec.securityContext.runAsNonRoot != true) | .metadata.name'
```

### Restricted 호환 Dockerfile 패턴

```dockerfile
# 멀티 스테이지 빌드 + Non-root
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
# non-root 사용자 생성
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 8080
CMD ["python", "serve.py"]
```

### Kyverno로 PSA 보완

```yaml
# Pod에 SecurityContext 자동 주입 (Mutating)
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-default-security-context
spec:
  rules:
  - name: add-security-context
    match:
      any:
      - resources:
          kinds: ["Pod"]
    mutate:
      patchStrategicMerge:
        spec:
          securityContext:
            runAsNonRoot: true
            seccompProfile:
              type: RuntimeDefault
          containers:
          - (name): "*"
            securityContext:
              allowPrivilegeEscalation: false
              capabilities:
                drop: ["ALL"]
```

---

## 면접 Q&A

### Q: Pod Security Standards의 3단계를 설명하고, 운영 환경에서의 적용 전략을 말씀해주세요.
**30초 답변**:
Privileged는 제한 없음(시스템 컴포넌트용), Baseline은 알려진 권한 상승을 차단(일반 워크로드), Restricted는 최대 보안 강화(runAsNonRoot, drop ALL 등)입니다. 운영에서는 warn/audit 모드로 시작하여 호환성을 확인한 후 enforce로 전환하는 단계적 접근이 안전합니다.

**2분 답변**:
Pod Security Standards는 PodSecurityPolicy(1.25 제거)를 대체하는 표준입니다. Privileged 레벨은 kube-system, CNI, CSI 드라이버 등 시스템 컴포넌트에 사용하며 제한이 없습니다. Baseline은 hostNetwork, privileged container, hostPath 같은 명확한 위험 요소를 차단하여 대부분의 워크로드에 적합합니다. Restricted는 추가로 runAsNonRoot, drop ALL capabilities, seccomp RuntimeDefault를 강제하여 최소 권한 원칙을 구현합니다. 적용 전략은 3단계입니다. 먼저 audit 모드로 기존 워크로드의 위반 사항을 수집합니다. 그다음 warn 모드로 전환하여 개발자에게 kubectl 경고를 노출합니다. 마지막으로 모든 워크로드가 호환되면 enforce로 전환합니다. 서드파티 차트(Prometheus, Grafana 등)는 Baseline까지만 적용하고, 자체 워크로드는 Restricted를 목표로 합니다. PSA만으로 부족한 세밀한 정책(이미지 레지스트리 제한, 라벨 필수 등)은 Kyverno나 OPA/Gatekeeper로 보완합니다.

**💡 경험 연결**:
폐쇄망 온프레미스 환경에서 PodSecurityPolicy를 운영했는데, PSP의 복잡한 우선순위 로직 때문에 예기치 않은 Pod 생성 실패가 빈번했습니다. PSA로 마이그레이션하면서 Namespace 라벨 기반의 단순한 모델로 전환했고, 운영 부담이 크게 줄었습니다.

**⚠️ 주의**:
PSA의 enforce 모드는 **기존 Running Pod에는 영향을 주지 않고 새로 생성되는 Pod에만 적용**된다. 기존 위반 Pod를 정리하려면 별도 스캔이 필요하다.

### Q: SecurityContext에서 반드시 설정해야 하는 항목들은 무엇인가요?
**30초 답변**:
핵심 4가지는 `runAsNonRoot: true`로 root 실행 금지, `readOnlyRootFilesystem: true`로 파일시스템 변조 방지, `allowPrivilegeEscalation: false`로 권한 상승 차단, `capabilities.drop: ["ALL"]`로 불필요한 Linux capability 제거입니다.

**2분 답변**:
SecurityContext는 Pod 수준과 Container 수준 두 곳에서 설정됩니다. Pod 수준에서는 `runAsNonRoot: true`, `runAsUser`(0 이외 UID), `fsGroup`(볼륨 파일 권한)을 설정합니다. Container 수준에서는 `allowPrivilegeEscalation: false`(setuid 비트 무효화), `readOnlyRootFilesystem: true`(악성코드 쓰기 방지, /tmp 등은 emptyDir 마운트), `capabilities.drop: ["ALL"]`후 필요한 것만 add합니다. 추가로 `seccompProfile: RuntimeDefault`를 설정하면 위험한 시스템콜(reboot, mount 등)을 차단합니다. AI 모델 서빙 컨테이너의 경우 모델 파일 캐시 경로에 emptyDir을 마운트하고, GPU 접근이 필요하면 device plugin을 통해 안전하게 노출합니다. Distroless 이미지를 사용하면 shell이 없어 컨테이너 침입 시 lateral movement를 원천 차단할 수 있습니다.

**💡 경험 연결**:
`readOnlyRootFilesystem: true` 적용 시 애플리케이션이 /tmp에 세션 파일을 쓰지 못해 장애가 발생한 경험이 있습니다. 이후 Dockerfile 분석과 emptyDir 마운트 목록을 사전에 확인하는 프로세스를 도입했습니다.

**⚠️ 주의**:
Container 수준 SecurityContext가 Pod 수준보다 우선한다. 둘 다 설정된 경우 Container 수준이 override하므로, Pod 수준의 보안 설정이 무력화될 수 있다.

### Q: PodSecurityPolicy에서 Pod Security Admission으로의 마이그레이션 경험을 설명해주세요.
**30초 답변**:
PSP는 정책 우선순위가 복잡하고 디버깅이 어려워 1.25에서 제거되었습니다. PSA는 Namespace 라벨 기반으로 단순하며, enforce/warn/audit 3가지 모드로 단계적 적용이 가능합니다.

**2분 답변**:
PSP의 주요 문제점은 세 가지였습니다. 첫째, 여러 PSP가 존재할 때 어떤 PSP가 적용되는지 예측하기 어려웠습니다(알파벳 순 + mutating 여부 기반). 둘째, RBAC과 별도로 PSP에 대한 `use` 권한을 관리해야 했습니다. 셋째, 정책 위반 원인을 디버깅하기 매우 어려웠습니다. 마이그레이션 절차는 다음과 같습니다. 먼저 기존 PSP 정책을 분석하여 각 Namespace에 맞는 PSS 레벨을 결정합니다. 그다음 PSA를 audit 모드로 활성화하여 위반 현황을 파악합니다. 위반 워크로드를 수정한 후 enforce로 전환합니다. 마지막으로 PSP를 비활성화합니다. PSA가 커버하지 못하는 세밀한 정책(특정 이미지 레지스트리 강제, 라벨 필수 등)은 Kyverno나 OPA/Gatekeeper를 병행합니다. 이 조합이 현재 Kubernetes 보안 정책의 모범 사례입니다.

**💡 경험 연결**:
실제로 PSP에서 PSA 마이그레이션을 진행할 때, 가장 어려웠던 부분은 서드파티 Helm 차트가 root 권한을 요구하는 경우였습니다. 해당 Namespace만 Baseline으로 설정하고, 나머지는 Restricted로 적용하는 차등 전략을 사용했습니다.

**⚠️ 주의**:
PSA는 Pod 컨트롤러(Deployment, StatefulSet) 수준이 아닌 **Pod 수준**에서만 검증한다. Deployment를 생성해도 에러가 나지 않고, ReplicaSet이 Pod를 생성할 때 비로소 거부된다.

---

## Allganize 맥락

- **AI 모델 서빙 보안**: LLM 서빙 Pod는 모델 가중치 로딩과 GPU 접근이 필요하지만, privileged 모드 없이 device plugin과 emptyDir로 안전하게 구성할 수 있다. Restricted PSS를 기본 적용하고, 필요한 capability만 추가하는 것이 모범 사례.
- **멀티테넌시 격리**: 고객별 Namespace에 Restricted PSS를 enforce하면, 한 테넌트의 컨테이너가 호스트에 탈출하는 것을 방지할 수 있다. 이는 SaaS 보안의 기본 요건.
- **CI/CD 파이프라인**: 빌드 Pod(Kaniko 등)는 Privileged가 필요할 수 있으므로 별도 Namespace에 Baseline을 적용하고, 나머지는 Restricted로 분리.
- **폐쇄망 경험 활용**: 온프레미스에서 SecurityContext를 엄격하게 적용한 경험은 클라우드 환경에서도 동일하게 적용 가능. "보안 정책 수립 및 운영" JD에 직접 매핑되는 역량.
- **컴플라이언스**: CIS Kubernetes Benchmark 5.2 섹션이 Pod Security를 다루며, Restricted PSS 적용은 대부분의 항목을 자동 충족.

---
**핵심 키워드**: `Pod-Security-Standards` `PSA` `SecurityContext` `runAsNonRoot` `readOnlyRootFilesystem` `capabilities` `seccomp` `Restricted` `Baseline`
