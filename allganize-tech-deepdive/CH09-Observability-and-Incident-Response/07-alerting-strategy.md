# 알림 전략: Alert Fatigue 방지와 에스컬레이션

> **TL;DR**: 효과적인 알림은 "조치 가능한(Actionable)" 알림만 보내는 것이 핵심이며, Alert Fatigue는 장애 대응 실패의 주요 원인이다.
> 알림을 Severity(Critical/Warning/Info)로 분류하고, 라우팅 규칙으로 적절한 채널과 담당자에게 전달한다.
> Escalation Policy는 1차 대응자 미응답 시 자동으로 상위 레벨로 전달하여 장애가 방치되지 않도록 보장한다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 20min

---

## 핵심 개념

### Alert Fatigue란?

```
Alert Fatigue 악순환:

  알림 과다 발생 ──────► 알림 무시 습관 형성
       ▲                        │
       │                        ▼
  임계값을 더 낮춤 ◄──── 실제 장애를 놓침
  (보상 심리)                    │
       ▲                        ▼
       └───── 포스트모템: "왜 알림을 놓쳤나?"
```

**Alert Fatigue의 원인**:
- 조치 불필요한 알림 (정보성 알림이 Critical과 같은 채널로 전송)
- 짧은 스파이크에 반복 트리거 (flapping)
- 중복 알림 (같은 문제에 대해 여러 모니터에서 동시 발생)
- 너무 낮은 임계값 (모든 경미한 이상에 반응)
- 해결 방법이 불명확한 알림 (뭘 해야 하는지 모르겠는 알림)

**건강한 알림의 원칙**:
```
모든 알림은 다음 질문에 "예"여야 한다:
├─ 1. 이 알림에 즉각 대응해야 하는가?
│     NO → Info/Dashboard로 격하
├─ 2. 이 알림은 사용자에게 영향을 주는가?
│     NO → Warning으로 격하, 자동 복구 검토
├─ 3. 대응 방법이 명확한가?
│     NO → Runbook 작성 후 알림에 링크 추가
└─ 4. 이 알림은 자동화할 수 없는가?
      NO → 자동 복구 구현 후 알림 제거
```

### Severity 분류 체계

```
┌─────────────────────────────────────────────────────────┐
│ P1 / Critical (즉각 대응)                                │
│   ├─ SLO 위반 진행 중 (Burn Rate > 14.4x)               │
│   ├─ 서비스 전면 장애                                    │
│   ├─ 데이터 손실 위험                                    │
│   └─ 라우팅: PagerDuty → On-call 엔지니어 (24/7)        │
│              + Slack #incident 자동 생성                  │
│              + 5분 내 미응답 시 에스컬레이션              │
├─────────────────────────────────────────────────────────┤
│ P2 / Warning (업무 시간 내 대응)                         │
│   ├─ Error Budget 빠르게 소진 (Burn Rate > 6x)          │
│   ├─ 부분 장애 (degraded but functional)                │
│   ├─ 리소스 고갈 임박 (디스크 85%, 메모리 90%)           │
│   └─ 라우팅: Slack #alerts → 담당 팀 멘션               │
│              JIRA 티켓 자동 생성                         │
├─────────────────────────────────────────────────────────┤
│ P3 / Info (참고)                                        │
│   ├─ 비정상적이나 즉각 영향 없음                         │
│   ├─ 용량 계획 참고 (디스크 70%, 트래픽 증가 추세)       │
│   └─ 라우팅: Slack #monitoring (알림 없음)              │
│              대시보드에 표시                              │
└─────────────────────────────────────────────────────────┘
```

### 알림 라우팅 아키텍처

```
┌──────────────┐     ┌──────────────┐     ┌───────────────────┐
│  Prometheus  │────►│ Alertmanager │────►│  Routing Rules    │
│  Alert Rules │     │              │     │                   │
└──────────────┘     │  ┌────────┐  │     │  severity=critical│
                     │  │Group   │  │     │  ├─► PagerDuty    │
┌──────────────┐     │  │Silence │  │     │  └─► Slack #inc   │
│  Grafana     │────►│  │Inhibit │  │     │                   │
│  Alerting    │     │  └────────┘  │     │  severity=warning │
└──────────────┘     └──────────────┘     │  ├─► Slack #alert │
                                          │  └─► JIRA ticket  │
┌──────────────┐     ┌──────────────┐     │                   │
│  Datadog     │────►│  Datadog     │     │  severity=info    │
│  Monitors    │     │  Notification│     │  └─► Slack #mon   │
└──────────────┘     └──────────────┘     └───────────────────┘
```

### Alertmanager 설정 상세

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m
  slack_api_url: 'https://hooks.slack.com/services/xxx'

# 억제 규칙: Critical이 발생하면 동일 서비스의 Warning 억제
inhibit_rules:
  - source_matchers:
      - severity = critical
    target_matchers:
      - severity = warning
    equal: ['service', 'namespace']

# 라우팅 트리
route:
  receiver: 'default-slack'
  group_by: ['namespace', 'service', 'alertname']
  group_wait: 30s        # 그룹 내 첫 알림 후 대기 (관련 알림 모으기)
  group_interval: 5m     # 같은 그룹의 새 알림 전송 간격
  repeat_interval: 4h    # 해결 안 된 알림 재전송 간격
  routes:
    # Critical → PagerDuty + Slack
    - matchers:
        - severity = critical
      receiver: 'pagerduty-critical'
      continue: true      # 다음 라우트도 평가
    - matchers:
        - severity = critical
      receiver: 'slack-incidents'

    # Warning → Slack + JIRA
    - matchers:
        - severity = warning
      receiver: 'slack-warnings'

    # 팀별 라우팅
    - matchers:
        - team = platform
      receiver: 'slack-platform'
    - matchers:
        - team = ml
      receiver: 'slack-ml-team'

receivers:
  - name: 'default-slack'
    slack_configs:
      - channel: '#monitoring'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'

  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '<PD_SERVICE_KEY>'
        severity: 'critical'
        description: '{{ .GroupLabels.alertname }}: {{ .CommonAnnotations.summary }}'
        details:
          namespace: '{{ .GroupLabels.namespace }}'
          service: '{{ .GroupLabels.service }}'
          runbook: '{{ .CommonAnnotations.runbook_url }}'

  - name: 'slack-incidents'
    slack_configs:
      - channel: '#incidents'
        title: '[CRITICAL] {{ .GroupLabels.alertname }}'
        text: |
          *서비스*: {{ .GroupLabels.service }}
          *요약*: {{ .CommonAnnotations.summary }}
          *Runbook*: {{ .CommonAnnotations.runbook_url }}
          *대시보드*: {{ .CommonAnnotations.dashboard_url }}
        actions:
          - type: button
            text: 'Runbook 열기'
            url: '{{ .CommonAnnotations.runbook_url }}'
          - type: button
            text: 'Dashboard'
            url: '{{ .CommonAnnotations.dashboard_url }}'
```

### Escalation Policy (PagerDuty/OpsGenie)

```
Escalation Flow:
┌─────────┐  0min   ┌──────────────┐  5min   ┌──────────────┐
│ Alert   │────────►│ L1: On-call  │────────►│ L2: On-call  │
│ Trigger │         │ Primary      │ (미응답) │ Secondary    │
└─────────┘         │ Push + SMS   │         │ Push + Phone │
                    └──────────────┘         └──────┬───────┘
                                                     │ 15min (미응답)
                                              ┌──────▼───────┐
                                              │ L3: Team Lead│
                                              │ Phone + SMS  │
                                              └──────┬───────┘
                                                     │ 30min (미응답)
                                              ┌──────▼───────┐
                                              │ L4: VP/Eng   │
                                              │ Manager      │
                                              │ Phone        │
                                              └──────────────┘
```

```yaml
# PagerDuty Escalation Policy (Terraform)
resource "pagerduty_escalation_policy" "alli_production" {
  name      = "Alli Production Escalation"
  num_loops = 2   # 전체 순서를 2번 반복

  rule {
    escalation_delay_in_minutes = 5
    target {
      type = "schedule_reference"
      id   = pagerduty_schedule.primary_oncall.id
    }
  }

  rule {
    escalation_delay_in_minutes = 15
    target {
      type = "schedule_reference"
      id   = pagerduty_schedule.secondary_oncall.id
    }
  }

  rule {
    escalation_delay_in_minutes = 30
    target {
      type = "user_reference"
      id   = pagerduty_user.engineering_lead.id
    }
  }
}
```

### On-call 로테이션

```
주간 로테이션 예시:
┌────────┬───────────┬───────────┬───────────┬───────────┐
│  주차  │ Primary   │ Secondary │  백업     │ 비고      │
├────────┼───────────┼───────────┼───────────┼───────────┤
│ Week 1 │ 엔지니어A │ 엔지니어B │ 팀리드   │           │
│ Week 2 │ 엔지니어B │ 엔지니어C │ 팀리드   │           │
│ Week 3 │ 엔지니어C │ 엔지니어A │ 팀리드   │           │
│ Week 4 │ 엔지니어A │ 엔지니어B │ 팀리드   │ 반복      │
└────────┴───────────┴───────────┴───────────┴───────────┘

On-call 핸드오프 체크리스트:
☐ 진행 중인 이슈 인계
☐ 이번 주 배포 예정 목록 확인
☐ Runbook 업데이트 사항 공유
☐ 알림 채널/앱 알림 설정 확인
☐ 에스컬레이션 연락처 확인
```

---

## 실전 예시

### 효과적인 Alert Rule 작성

```yaml
# GOOD: Actionable한 알림
- alert: AlliAPIHighErrorBurnRate
  expr: |
    (
      sum(rate(http_requests_total{service="alli-api",status=~"5.."}[1h]))
      / sum(rate(http_requests_total{service="alli-api"}[1h]))
    ) / (1 - 0.999) > 14.4
    and
    (
      sum(rate(http_requests_total{service="alli-api",status=~"5.."}[5m]))
      / sum(rate(http_requests_total{service="alli-api"}[5m]))
    ) / (1 - 0.999) > 14.4
  for: 2m
  labels:
    severity: critical
    team: platform
    service: alli-api
  annotations:
    summary: "Alli API Error Budget 빠르게 소진 중 (burn rate {{ $value | printf \"%.1f\" }}x)"
    description: "현재 burn rate로 {{ $value | printf \"%.0f\" }}시간 내 월간 Error Budget 소진"
    runbook_url: "https://wiki.allganize.ai/runbooks/alli-api-high-error-rate"
    dashboard_url: "https://grafana.allganize.ai/d/alli-api-slo"

# BAD: Actionable하지 않은 알림
- alert: HighCPU
  expr: node_cpu_usage > 80    # 80%가 왜 문제인지 불명확
  for: 5m
  labels:
    severity: critical          # CPU 80%로 Critical?
  annotations:
    summary: "CPU high"         # 무엇을 해야 하는지 모름
```

### Silence(음소거)와 Maintenance Window

```bash
# Alertmanager에서 계획된 유지보수 시 알림 음소거
# amtool로 Silence 생성
amtool silence add \
  --alertmanager.url=http://alertmanager:9093 \
  --author="operator" \
  --comment="Scheduled maintenance: DB migration" \
  --duration=2h \
  namespace="alli-prod" \
  service="alli-api"

# 활성 Silence 목록 확인
amtool silence query --alertmanager.url=http://alertmanager:9093

# Silence 만료 전 수동 해제
amtool silence expire <silence-id>
```

---

## 면접 Q&A

### Q: Alert Fatigue를 어떻게 방지하나?
**30초 답변**: 세 가지 원칙입니다. 첫째, 모든 알림은 Actionable해야 합니다(조치 불가능하면 대시보드로 격하). 둘째, Severity를 명확히 분류하여 Critical만 즉각 호출합니다. 셋째, Burn Rate Alert처럼 비즈니스 영향 기반 알림으로 노이즈를 줄입니다.

**2분 답변**: Alert Fatigue 방지는 다섯 가지 전략으로 접근합니다. 첫째, **Actionability 필터**: 모든 알림을 주기적으로(분기별) 리뷰하여, 지난 3개월간 한 번도 조치가 필요 없었던 알림은 제거하거나 Info로 격하합니다. 둘째, **Symptom 기반 알림**: CPU 80% 같은 Cause가 아니라, "응답시간 SLO 위반 임박" 같은 Symptom에 알림을 걸습니다. CPU가 100%여도 사용자 영향이 없으면 알림이 불필요합니다. 셋째, **그룹핑과 억제(Inhibition)**: Alertmanager에서 관련 알림을 그룹으로 묶고, Critical 발생 시 같은 서비스의 Warning을 억제합니다. 넷째, **Runbook 연결**: 모든 알림에 Runbook URL을 포함하여 대응 방법을 즉시 확인할 수 있게 합니다. 다섯째, **자동 복구**: 알림 대신 자동화로 해결할 수 있는 것(Pod 재시작, 스케일아웃)은 자동화하고 알림을 제거합니다. 메트릭으로 관리하려면, 월간 "알림 대비 실제 조치 비율(Signal-to-Noise Ratio)"을 추적합니다. 이 비율이 50% 미만이면 알림 정책을 재검토해야 합니다.

**경험 연결**: Zabbix에서 수백 개의 트리거를 설정했을 때, 새벽에 불필요한 SMS가 반복 도착하여 정작 진짜 장애 알림을 무시하게 되었습니다. 이후 Severity를 재정의하고 Action을 분리한 경험이 있습니다.

**주의**: "알림을 줄이자"가 "알림을 안 보내자"가 되면 안 됨. 진짜 중요한 알림의 신뢰도를 높이는 것이 목표.

### Q: PagerDuty/OpsGenie 같은 On-call 도구의 역할과 에스컬레이션 정책 설계 방법은?
**30초 답변**: On-call 도구는 알림을 담당자에게 전달하고, 미응답 시 자동으로 다음 레벨로 에스컬레이션합니다. Primary(5분) → Secondary(15분) → Team Lead(30분) 순서로 설계하며, 로테이션 스케줄과 함께 운영합니다.

**2분 답변**: PagerDuty/OpsGenie의 핵심 기능은 세 가지입니다. 첫째, **On-call 스케줄**: 주간/야간 로테이션으로 담당자를 자동 지정하여, "누가 대응해야 하는지"의 모호함을 제거합니다. 둘째, **에스컬레이션**: 5분 내 Acknowledge가 없으면 Secondary → Team Lead → Engineering Manager 순으로 자동 전달합니다. 어떤 장애도 방치되지 않습니다. 셋째, **알림 채널 다양화**: 모바일 Push → SMS → 전화 순서로 점점 강한 수단을 사용합니다. 설계 시 고려사항: (1) 팀 규모에 따라 로테이션 주기 조정(3명이면 주간, 5명 이상이면 격주), (2) 야간 알림은 진짜 Critical만(P1), Warning은 다음 업무일, (3) On-call 핸드오프 시 진행 중인 이슈와 예정된 배포를 반드시 인계, (4) On-call 보상(수당, 대휴)으로 지속 가능성 확보. Override 기능으로 휴가/개인 사정 시 임시 교대가 가능합니다.

**경험 연결**: 온프레미스 인프라 운영에서 비공식 on-call(전화 돌려막기)을 했는데, 담당자 불명확, 에스컬레이션 지연 등 문제가 빈번했습니다. 공식 on-call 도구는 이 과정을 자동화하고 투명하게 만듭니다.

**주의**: On-call은 엔지니어의 번아웃 요인이 될 수 있다. "기술"뿐 아니라 "사람 관리" 측면(보상, 로테이션 공정성, 알림 품질)도 언급할 것.

### Q: 알림과 Runbook을 어떻게 연결하나?
**30초 답변**: 모든 Critical/Warning 알림의 annotation에 Runbook URL을 포함합니다. Runbook에는 증상 확인, 원인 진단, 복구 절차가 단계별로 기술되어 있어, 새벽 On-call 시에도 체계적으로 대응할 수 있습니다.

**2분 답변**: Runbook은 알림과 대응 사이의 다리입니다. 구조는 다음과 같습니다: (1) **증상**: 이 알림이 발생하면 사용자에게 어떤 영향이 있는가, (2) **진단 절차**: 어떤 대시보드/로그/명령어를 확인해야 하는가, (3) **즉각 완화**: 가장 빠른 복구 방법(롤백, 스케일아웃, 트래픽 전환), (4) **근본 원인 해결**: 임시 조치 후 근본적 수정 방법, (5) **에스컬레이션 기준**: 언제 다음 레벨로 올려야 하는가. Prometheus Alert Rule의 annotation에 `runbook_url`을 추가하면, Alertmanager → Slack/PagerDuty 알림에 Runbook 링크가 자동 포함됩니다. Runbook은 Wiki나 Git에서 관리하고, 포스트모템 후 반드시 업데이트합니다. 궁극적으로 Runbook의 자동화 가능한 부분은 스크립트로 전환하여, 자동 복구(Self-healing)를 구현합니다.

**경험 연결**: 인프라 운영 시 장애 대응 절차서를 작성했으나, 시간이 지나면서 업데이트되지 않아 실제 장애 시 무용지물이 된 경험이 있습니다. Runbook을 코드처럼 버전 관리하고 정기 리뷰하는 것이 핵심입니다.

**주의**: Runbook이 너무 길거나 복잡하면 긴급 상황에서 사용 불가. 핵심 조치는 첫 화면에 나와야 한다.

---

## Allganize 맥락

- **소규모 팀**: DevOps 팀 규모가 작을수록 Alert Fatigue 방지가 중요. 불필요한 알림을 줄여 핵심에 집중
- **On-call 구축**: 서비스 규모 성장 시 공식 On-call 로테이션 도입 필요
- **멀티클라우드 알림 통합**: AWS/Azure 양쪽 클러스터의 알림을 PagerDuty/OpsGenie 하나로 통합 라우팅
- **LLM 서비스 특화 알림**: 모델 추론 실패, GPU 메모리 OOM, 토큰 제한 초과 등 AI 서비스 고유 알림 설계
- **Slack 통합**: 개발 문화에서 Slack이 중심이므로, 알림 → Slack → Incident Channel 자동 생성 워크플로우

---
**핵심 키워드**: `Alert-Fatigue` `Severity` `Actionable` `PagerDuty` `OpsGenie` `Escalation-Policy` `On-call` `Rotation` `Inhibition` `Silence` `Runbook` `Signal-to-Noise`
