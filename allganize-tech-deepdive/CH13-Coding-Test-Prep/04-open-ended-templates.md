# 04. Open-ended 답안 템플릿 — 구조화 전략과 5대 주제 템플릿

> **TL;DR**
> - Coderbyte Open-ended는 코드보다 **설계 사고력과 커뮤니케이션 능력**을 본다. 구조화된 답안이 핵심이다.
> - 모든 답안은 **STAR-T 프레임워크**(Situation → Task → Action → Result → Trade-off)로 작성하면 일관성 있게 높은 점수를 받는다.
> - Observability, CI/CD, IaC, Performance, Security 5개 주제 템플릿을 미리 준비하면 어떤 변형 문제에도 대응 가능하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### Open-ended 문제란?

Coderbyte의 Open-ended 파트는 **자유 서술형 또는 시스템 설계형** 문제다:
- "How would you design a monitoring system for a microservices architecture?"
- "Describe your CI/CD pipeline and explain your design decisions."
- "How would you handle a production incident where response times increased 10x?"

**채점 기준** (일반적):
1. **문제 이해도** — 핵심을 정확히 파악했는가
2. **구조화 능력** — 논리적 흐름이 있는가
3. **기술적 깊이** — 구체적 도구/방법론을 제시하는가
4. **Trade-off 인식** — 장단점을 고려하는가
5. **실무 경험 반영** — 경험에서 우러나온 답인가

### STAR-T 프레임워크

```
┌─────────────────────────────────────────────┐
│  S — Situation (상황/맥락)                    │
│      "마이크로서비스 30개가 K8s에서 운영되는   │
│       환경에서..."                            │
├─────────────────────────────────────────────┤
│  T — Task (해결해야 할 과제)                   │
│      "장애 감지 시간을 5분 이내로 줄이고,      │
│       근본 원인 분석을 자동화해야 한다."        │
├─────────────────────────────────────────────┤
│  A — Action (구체적 행동/설계)                 │
│      "Prometheus + Grafana + PagerDuty를     │
│       구성하고, 3-tier alerting을 설계했다."   │
├─────────────────────────────────────────────┤
│  R — Result (결과/효과)                       │
│      "MTTD 15분 → 3분, MTTR 2시간 → 30분으로 │
│       개선되었다."                            │
├─────────────────────────────────────────────┤
│  T — Trade-off (한계/대안)                    │
│      "Prometheus는 장기 저장에 약하므로        │
│       Thanos/Mimir를 고려할 수 있다."          │
└─────────────────────────────────────────────┘
```

### 답안 작성 공통 규칙

1. **첫 문장에 결론을 쓴다** — "I would implement a three-tier observability stack using..."
2. **번호를 매긴다** — 채점자가 빠르게 스캔할 수 있도록
3. **구체적 도구 이름을 쓴다** — "모니터링 도구" (X) → "Prometheus + Grafana" (O)
4. **코드 스니펫을 포함한다** — 짧은 설정 파일이나 스크립트 조각으로 실력을 증명
5. **Trade-off로 마무리한다** — "This approach has limitations when..." → 시니어 사고력을 보여줌

---

## 템플릿 1: Observability (모니터링/관측성)

### 예상 문제

> "How would you design a monitoring and alerting system for a microservices application?"

### 답안 템플릿

```markdown
## Monitoring & Alerting Architecture

### Overview
I would implement a **three-pillar observability stack** (Metrics, Logs, Traces)
on Kubernetes, using Prometheus + Grafana for metrics, EFK/Loki for logs,
and Jaeger/Tempo for distributed tracing.

### Architecture

1. **Metrics Layer (Prometheus + Grafana)**
   - Each service exposes `/metrics` endpoint (RED method: Rate, Errors, Duration)
   - Prometheus scrapes every 15s via ServiceMonitor CRDs
   - Grafana dashboards per service + SLO dashboard

2. **Logging Layer (Fluent Bit → Elasticsearch/Loki)**
   - Fluent Bit DaemonSet collects stdout/stderr from all pods
   - Structured JSON logging enforced across services
   - Log correlation via trace_id injection

3. **Tracing Layer (OpenTelemetry → Jaeger/Tempo)**
   - OpenTelemetry SDK auto-instruments HTTP/gRPC calls
   - Sampling rate: 1% normal, 100% on errors
   - Trace-to-log correlation via trace_id

4. **Alerting Strategy (3-tier)**
   - P1 (Critical): Service down, error rate > 5% → PagerDuty → on-call
   - P2 (Warning): Latency p99 > 1s, disk > 80% → Slack #alerts
   - P3 (Info): Deployment events, scaling → Slack #deployments

### Example: Prometheus Alert Rule
```

```yaml
# prometheus-rules.yaml
groups:
  - name: api-slo
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum(rate(http_requests_total[5m])) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Error rate exceeds 5% SLO"
```

```markdown
### Trade-offs
- Prometheus is pull-based → not ideal for short-lived jobs (consider Pushgateway)
- Long-term storage requires Thanos/Mimir (Prometheus local retention ~15d)
- Full tracing adds ~3% latency overhead → sampling is necessary
```

---

## 템플릿 2: CI/CD Pipeline

### 예상 문제

> "Describe how you would design a CI/CD pipeline for a Python-based microservices application."

### 답안 템플릿

```markdown
## CI/CD Pipeline Design

### Overview
I would implement a **GitOps-based CI/CD pipeline** using GitHub Actions for CI,
ArgoCD for CD, with automated testing, security scanning, and progressive rollout.

### Pipeline Stages

1. **Code Quality (Pre-commit)**
   - pre-commit hooks: black, ruff, mypy
   - Branch protection: require PR review + CI pass

2. **CI Pipeline (GitHub Actions)**
   - Unit tests: pytest --cov (minimum 80% coverage)
   - Integration tests: docker-compose based
   - Security scan: trivy (container), bandit (SAST)
   - Container build: multi-stage Dockerfile → ECR/GCR push
   - Image tag: git SHA for traceability

3. **CD Pipeline (ArgoCD + GitOps)**
   - ArgoCD watches k8s-manifests repo
   - CI updates image tag in kustomization.yaml
   - ArgoCD auto-syncs to staging, manual approval for production

4. **Progressive Rollout**
   - Canary deployment via Argo Rollouts
   - 10% → metrics check (5min) → 50% → metrics check → 100%
   - Auto-rollback if error rate > 1%
```

```yaml
# .github/workflows/ci.yaml (핵심 부분)
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: |
          pip install -r requirements.txt
          pytest --cov=app --cov-report=xml
      - name: Security scan
        run: trivy image --severity HIGH,CRITICAL $IMAGE

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Update manifest
        run: |
          cd k8s-manifests
          kustomize edit set image app=$IMAGE:${{ github.sha }}
          git commit -am "deploy: ${{ github.sha }}"
          git push
```

```markdown
### Trade-offs
- GitOps adds a manifest repo → increased operational complexity
- Canary requires good metrics coverage to detect regressions
- ArgoCD self-management needs care (who deploys the deployer?)
```

---

## 템플릿 3: Infrastructure as Code (IaC)

### 예상 문제

> "How would you manage infrastructure for multiple environments (dev/staging/prod)?"

### 답안 템플릿

```markdown
## Multi-Environment IaC Strategy

### Overview
I would use **Terraform with a modular structure**, managing state per environment
in remote backends (S3), with Terragrunt for DRY configuration across environments.

### Directory Structure
```

```
infra/
├── modules/                    # 재사용 가능 모듈
│   ├── vpc/
│   ├── eks/
│   ├── rds/
│   └── monitoring/
├── environments/
│   ├── dev/
│   │   ├── terragrunt.hcl     # dev 변수 오버라이드
│   │   └── env.tfvars
│   ├── staging/
│   └── prod/
│       ├── terragrunt.hcl
│       └── env.tfvars
└── terragrunt.hcl             # 공통 설정 (backend, provider)
```

```markdown
### Key Principles
1. **Module Reuse**: 동일 모듈을 env별 다른 변수로 호출
2. **State Isolation**: 환경별 별도 state file → blast radius 제한
3. **Policy as Code**: OPA/Sentinel로 prod에 위험한 변경 차단
4. **Drift Detection**: 주기적 `terraform plan` → Slack 알림

### Example: Environment Variable Override
```

```hcl
# environments/prod/env.tfvars
environment    = "prod"
instance_type  = "m5.xlarge"    # dev는 t3.medium
min_replicas   = 3              # dev는 1
enable_backups = true           # dev는 false
multi_az       = true           # dev는 false
```

```markdown
### Trade-offs
- Terragrunt adds tooling complexity (learning curve for team)
- Module versioning needs discipline (breaking changes in shared modules)
- State locking requires DynamoDB → additional cost (minimal)
```

---

## 템플릿 4: Performance Optimization

### 예상 문제

> "Your API response times increased from 200ms to 2s. How would you diagnose and fix this?"

### 답안 템플릿

```markdown
## Performance Incident Response

### Immediate Diagnosis (First 15 minutes)

1. **Scope Identification**
   - Which endpoints? All or specific ones?
   - When did it start? Correlate with deployments/changes
   - Affected users: all regions or specific?

2. **Quick Metrics Check**
   ```bash
   # Grafana에서 확인할 대시보드
   - Request latency p50/p95/p99 by endpoint
   - CPU/Memory per pod
   - DB connection pool usage
   - External dependency latency
   ```

3. **Common Root Causes Checklist**
   - [ ] Recent deployment? → rollback candidate
   - [ ] DB slow queries? → `EXPLAIN ANALYZE` on top queries
   - [ ] Connection pool exhaustion? → pool size vs active connections
   - [ ] External API timeout? → circuit breaker status
   - [ ] Memory pressure → GC pause? OOM?
   - [ ] Network: DNS resolution delay? MTU issues?

### Systematic Investigation
```

```python
# 빠른 진단 스크립트
import requests
import time

def measure_endpoint(url, n=10):
    """엔드포인트 응답 시간을 n회 측정하여 통계를 출력한다."""
    times = []
    for _ in range(n):
        start = time.time()
        resp = requests.get(url, timeout=10)
        elapsed = (time.time() - start) * 1000
        times.append(elapsed)
        print(f"  {resp.status_code} — {elapsed:.0f}ms")

    times.sort()
    print(f"\nMin: {times[0]:.0f}ms | Median: {times[len(times)//2]:.0f}ms | "
          f"P95: {times[int(len(times)*0.95)]:.0f}ms | Max: {times[-1]:.0f}ms")
```

```markdown
### Resolution Strategy
1. **Short-term**: Rollback if deployment-related, add caching if DB-bound
2. **Medium-term**: Add DB index, optimize N+1 queries, tune connection pool
3. **Long-term**: Implement caching layer (Redis), async processing for heavy ops

### Trade-offs
- Caching introduces consistency challenges (TTL strategy needed)
- Rollback may lose new features → feature flags preferred
- Adding replicas treats symptoms, not root cause
```

---

## 템플릿 5: Security

### 예상 문제

> "How would you secure a Kubernetes cluster running customer-facing applications?"

### 답안 템플릿

```markdown
## Kubernetes Security Architecture

### Defense in Depth (4 Layers)

1. **Cluster Level**
   - RBAC with least-privilege roles
   - Network Policies: default-deny, explicit allow per namespace
   - Pod Security Standards: restricted profile enforced
   - API server: private endpoint, OIDC authentication

2. **Container Level**
   - Non-root containers (runAsNonRoot: true)
   - Read-only root filesystem
   - No privilege escalation (allowPrivilegeEscalation: false)
   - Image scanning in CI (Trivy) + admission control (Kyverno/OPA)

3. **Secret Management**
   - External Secrets Operator → AWS Secrets Manager / Vault
   - Never store secrets in Git (even encrypted → use sealed-secrets as minimum)
   - Auto-rotation for DB credentials

4. **Runtime Security**
   - Falco for runtime anomaly detection
   - Audit logging enabled → forwarded to SIEM
   - Network traffic monitoring (Cilium + Hubble)
```

```yaml
# Pod Security 예시 — Restricted Profile
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: app:latest
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      resources:
        limits:
          memory: "256Mi"
          cpu: "500m"
```

```markdown
### Trade-offs
- Strict Network Policies require careful service dependency mapping
- Read-only filesystem needs writable tmpfs for apps that write temp files
- Image scanning adds CI time (~2-3 min) → worth it for security assurance
- External secret management adds infrastructure complexity (Vault HA setup)
```

---

## 면접 Q&A / 연습 문제

### Q1. Open-ended 답안을 작성할 때 가장 중요한 원칙은?

**A:** **첫 문장에 결론(방향성)을 명확히 제시**하고, 나머지에서 구조화된 근거를 보여주는 것이다. 채점자는 수십 개의 답안을 읽으므로 30초 안에 "이 사람은 알고 있다"는 인상을 줘야 한다. STAR-T 프레임워크를 따르되, Action 파트에서 **구체적 도구명과 설정 예시**를 포함하면 기술적 깊이를 증명할 수 있다.

### Q2. Trade-off를 쓰는 이유는 무엇인가?

**A:** Trade-off를 언급하면 세 가지를 동시에 보여줄 수 있다:
1. **기술적 성숙도** — 완벽한 솔루션은 없다는 것을 안다
2. **실무 경험** — 실제로 운영해본 사람만 한계를 알 수 있다
3. **의사결정 능력** — 왜 이 선택을 했는지 설명할 수 있다

"Silver bullet은 없다. 우리 상황에서 이것이 최선인 이유는..."이라는 뉘앙스가 핵심이다.

### Q3. 시간이 부족할 때 Open-ended 답안을 빠르게 작성하는 전략은?

**A:**
1. **1분**: 핵심 키워드 3~5개를 메모한다 (예: Prometheus, Grafana, 3-tier alerting)
2. **2분**: Overview 1문장 + 번호 매긴 3~4개 포인트를 작성한다
3. **2분**: 각 포인트에 1줄씩 구체적 도구/설정을 추가한다
4. **1분**: Trade-off 1~2줄로 마무리한다

총 6분에 "구조화되고 기술적 깊이가 있는" 답안을 완성할 수 있다. **불완전해도 구조화된 답이 길지만 산만한 답보다 점수가 높다.**

---

## Allganize 맥락

- **Alli 서비스 운영**: Allganize는 AI SaaS 서비스를 K8s 위에서 운영한다. 위 5개 주제는 모두 Allganize DevOps 팀의 실제 업무 영역이다.
- **LLM 서비스 특성**: GPU 노드 관리, 모델 서빙 레이턴시, 토큰 처리량 모니터링 등 AI 서비스 특유의 요소를 답안에 녹이면 Allganize에 대한 이해를 어필할 수 있다.
- **10년차 강점 활용**: Open-ended 파트는 코딩 실력보다 **설계 경험과 의사결정 능력**을 평가한다. 인프라 경력이 긴 지원자에게 유리한 파트이므로, 여기서 점수를 최대화해야 한다.
- **영어 답안 준비**: Coderbyte는 영어 플랫폼이므로, 핵심 답안은 영어로 작성한다. 단, 한국어 메모로 구조를 잡은 뒤 영어로 옮기면 시간이 절약된다.

---

**핵심 키워드**: `STAR-T` `Open-ended` `Trade-off` `Observability` `CI/CD` `IaC` `Performance` `Security` `구조화답안` `Coderbyte`
