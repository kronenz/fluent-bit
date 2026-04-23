# SLI, SLO, Error Budget 설계

> **TL;DR**: SLI(Service Level Indicator)는 서비스 품질의 정량적 측정값이고, SLO(Service Level Objective)는 그 목표치이다.
> Error Budget은 SLO에서 허용하는 실패 예산으로, 개발 속도와 안정성의 균형을 수학적으로 관리한다.
> SLO를 99.9%로 설정하면 월 43분의 다운타임이 허용되며, 이 예산 소진 속도로 릴리스 결정을 내린다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### SLI / SLO / SLA 계층 구조

```
┌─────────────────────────────────────────────────┐
│ SLA (Service Level Agreement)                    │
│   "99.9% 가용성 미달 시 크레딧 보상"              │
│   ← 비즈니스/계약 (외부 고객과의 약속)             │
├─────────────────────────────────────────────────┤
│ SLO (Service Level Objective)                    │
│   "99.95% 가용성을 목표로 한다"                   │
│   ← 엔지니어링 목표 (SLA보다 엄격하게 설정)       │
├─────────────────────────────────────────────────┤
│ SLI (Service Level Indicator)                    │
│   "성공한 요청 수 / 전체 요청 수 × 100"           │
│   ← 측정 지표 (실제 데이터)                       │
└─────────────────────────────────────────────────┘

관계: SLI를 측정하여 SLO 달성 여부를 판단하고,
      SLO를 기반으로 SLA를 계약한다.
      SLO는 항상 SLA보다 엄격해야 한다 (buffer).
```

### SLI 유형과 정의

| SLI 유형 | 정의 | 계산식 | 적합한 서비스 |
|----------|------|--------|--------------|
| **Availability** | 성공 요청 비율 | `(전체 요청 - 5xx) / 전체 요청` | API, 웹서비스 |
| **Latency** | 기준 이내 응답 비율 | `(응답 < 500ms인 요청) / 전체 요청` | API, 실시간 서비스 |
| **Throughput** | 처리량 | `초당 처리 요청 수` | 배치, 데이터 파이프라인 |
| **Correctness** | 정확한 결과 비율 | `(올바른 응답) / 전체 응답` | AI 추론, 검색 |
| **Freshness** | 데이터 최신성 | `(최신 데이터 요청) / 전체 요청` | 대시보드, 캐시 |

**LLM 서비스(Alli) SLI 예시**:
```
SLI 1: Availability
  = (200 응답 수) / (전체 추론 요청 수)
  제외: 클라이언트 에러(4xx)는 SLI에서 제외

SLI 2: Latency (p99)
  = (응답시간 < 2s인 추론 요청) / (전체 추론 요청)
  모델별로 다른 기준 적용 가능

SLI 3: Correctness (AI 특화)
  = (유효한 추론 결과) / (전체 추론 요청)
  할루시네이션, 빈 응답, 형식 에러 제외
```

### SLO 설정 방법론

```
Step 1: 현재 성능 측정 (Baseline)
  └─ 지난 28일간 SLI 데이터 수집
  └─ 현재 Availability: 99.97%, Latency p99: 1.8s

Step 2: 비즈니스 요구사항 확인
  └─ 고객 기대: 응답 2초 이내
  └─ 계약 SLA: 99.9%
  └─ 내부 SLO는 SLA보다 엄격하게

Step 3: SLO 설정
  └─ Availability SLO: 99.95% (28일 rolling)
  └─ Latency SLO: 99% of requests < 2s (28일 rolling)

Step 4: Error Budget 계산
  └─ 100% - 99.95% = 0.05% = Error Budget
  └─ 28일 × 24h × 60m = 40,320분
  └─ 40,320 × 0.0005 = 20.16분의 다운타임 허용

Step 5: 모니터링/알림 설정
  └─ Error Budget 50% 소진 시 Warning
  └─ Error Budget 80% 소진 시 Critical (릴리스 중단)
```

### Error Budget 계산

```
SLO: 99.95% Availability (28-day rolling window)

Error Budget = 1 - SLO = 0.05%

시간 환산:
┌──────────┬──────────┬──────────┬──────────┐
│ SLO      │ 월 예산  │ 주 예산  │ 일 예산  │
├──────────┼──────────┼──────────┼──────────┤
│ 99%      │ 7.3h     │ 1.68h   │ 14.4m   │
│ 99.5%    │ 3.65h    │ 50.4m   │ 7.2m    │
│ 99.9%    │ 43.8m    │ 10.1m   │ 1.44m   │
│ 99.95%   │ 21.9m    │ 5.04m   │ 43.2s   │
│ 99.99%   │ 4.38m    │ 1.01m   │ 8.64s   │
└──────────┴──────────┴──────────┴──────────┘

요청 기반 환산 (100만 req/day 기준):
  SLO 99.95% → 하루 500건의 에러 허용
  SLO 99.9%  → 하루 1,000건의 에러 허용
```

### Error Budget Policy

```
Error Budget 소진율에 따른 대응:

100% ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 정상 운영
                                        ↓ 기능 개발 + 릴리스 진행
 75% ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░ 주의
                                        ↓ 릴리스 속도 조절, 안정성 작업 우선
 50% ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░ 경고
                                        ↓ 신규 릴리스 중단, 안정화 집중
 25% ▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░ 위험
                                        ↓ 전원 안정화 투입, 근본 원인 해결
  0% ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 예산 소진
                                        ↓ SLO 재협상 또는 아키텍처 변경
```

**Error Budget Policy 문서 예시**:
```markdown
## Error Budget Policy: alli-api

### 기본 원칙
- Error Budget은 28일 rolling window로 계산
- 매주 월요일 Error Budget 리뷰 미팅
- Product Owner와 Engineering Lead가 공동 의사결정

### 대응 기준
| Budget 잔여 | 조치 |
|-------------|------|
| > 75% | 정상 릴리스 진행 |
| 50~75% | 릴리스 전 추가 테스트 필수, 카나리 배포 확대 |
| 25~50% | 신규 기능 릴리스 중단, 안정화 작업만 |
| < 25% | 전원 안정화 투입, 포스트모템 필수 |
| 0% | SLO 재검토, 아키텍처 변경 논의 |

### 예외
- 보안 패치는 Error Budget 상관없이 즉시 릴리스
- 법적/규제 요구사항도 예외
```

### Burn Rate Alert

```
전통적 알림: "에러율 > 1%" → 임계값 기반, 컨텍스트 부족
Burn Rate: "현재 속도로 Error Budget을 소진하면 N시간 내 고갈" → 긴급도 반영

Burn Rate = 실제 에러율 / 허용 에러율

예시: SLO 99.9% (허용 에러율 0.1%)
  현재 에러율 0.1% → Burn Rate = 1x (정확히 예산에 맞음)
  현재 에러율 1.0% → Burn Rate = 10x (10배 빠르게 소진)
  현재 에러율 5.0% → Burn Rate = 50x (2시간 내 월 예산 소진)

Multi-window Burn Rate Alert (Google SRE 권장):
┌─────────────────────────────────────────────┐
│ Page-level (즉각 대응):                      │
│   1h burn rate > 14.4x AND 5m burn > 14.4x │
│   → 30일 예산이 1시간 내 2% 소진             │
│                                              │
│ Ticket-level (계획적 대응):                  │
│   6h burn rate > 6x AND 30m burn > 6x       │
│   → 30일 예산이 6시간 내 5% 소진             │
└─────────────────────────────────────────────┘
```

PromQL로 구현:
```promql
# 1시간 burn rate
(
  1 - (
    sum(rate(http_requests_total{status!~"5.."}[1h]))
    / sum(rate(http_requests_total[1h]))
  )
) / (1 - 0.999)   # SLO 99.9%
```

---

## 실전 예시

### Prometheus + Grafana SLO 대시보드

```promql
# SLI: Availability
sum(rate(http_requests_total{service="alli-api",status!~"5.."}[28d]))
/ sum(rate(http_requests_total{service="alli-api"}[28d]))

# SLI: Latency (p99 < 2s)
sum(rate(http_request_duration_seconds_bucket{service="alli-api",le="2.0"}[28d]))
/ sum(rate(http_request_duration_seconds_count{service="alli-api"}[28d]))

# Error Budget 남은 비율 (%)
(
  (1 - 0.9995) -  # 허용 에러 예산
  (1 - (
    sum(increase(http_requests_total{status!~"5.."}[28d]))
    / sum(increase(http_requests_total[28d]))
  ))
) / (1 - 0.9995) * 100

# Burn Rate (1시간 윈도우)
(
  1 - sum(rate(http_requests_total{status!~"5.."}[1h]))
      / sum(rate(http_requests_total[1h]))
) / (1 - 0.9995)
```

### Sloth로 SLO 자동 생성

```yaml
# sloth.yaml - SLO 정의를 Prometheus recording/alerting rules로 변환
version: "prometheus/v1"
service: "alli-api"
labels:
  owner: "platform-team"
  tier: "tier-1"
slos:
  - name: "requests-availability"
    objective: 99.95
    description: "Alli API 가용성"
    sli:
      events:
        error_query: sum(rate(http_requests_total{service="alli-api",status=~"5.."}[{{.window}}]))
        total_query: sum(rate(http_requests_total{service="alli-api"}[{{.window}}]))
    alerting:
      name: AlliAPIHighErrorRate
      labels:
        severity: critical
        team: platform
      annotations:
        summary: "Alli API Error Budget burn rate is too high"
      page_alert:
        labels:
          severity: critical
      ticket_alert:
        labels:
          severity: warning
```

```bash
# Sloth로 Prometheus rules 생성
sloth generate -i sloth.yaml -o prometheus-slo-rules.yaml
```

---

## 면접 Q&A

### Q: SLI, SLO, SLA의 차이와 관계를 설명해주세요.
**30초 답변**: SLI는 서비스 품질의 측정값(예: 성공률 99.97%), SLO는 그 목표(예: 99.95% 이상 유지), SLA는 고객과의 계약(예: 99.9% 미달 시 크레딧 보상)입니다. SLI로 측정 → SLO로 관리 → SLA로 약속하는 계층 구조입니다.

**2분 답변**: SLI는 "우리 서비스가 얼마나 잘 동작하는가"를 숫자로 표현합니다. 좋은 SLI는 사용자 경험과 직결되어야 합니다. 예를 들어 CPU 사용률은 나쁜 SLI(사용자 영향 불명확)이고, 성공 응답 비율은 좋은 SLI입니다. SLO는 "SLI가 이 수준 이상이어야 한다"는 내부 엔지니어링 목표입니다. 핵심은 SLO를 100%로 설정하지 않는 것입니다. 100%는 달성 불가능하고, 모든 변경이 위험으로 간주되어 개발이 멈춥니다. SLA는 SLO를 기반으로 고객에게 약속하는 계약입니다. SLA는 반드시 SLO보다 느슨해야 합니다. SLO 99.95%라면 SLA는 99.9%로 설정하여, SLO를 약간 못 맞춰도 SLA 위반은 아닌 버퍼를 둡니다. 이 세 가지를 잘 설계하면, 개발팀은 "Error Budget이 충분하니 새 기능을 배포하자" 또는 "Error Budget이 부족하니 안정화에 집중하자"라는 데이터 기반 의사결정을 할 수 있습니다.

**경험 연결**: 온프레미스 인프라에서 "가용률 99.9% 유지"가 SLA로 있었지만, 실제 측정 방법(SLI)이 명확하지 않아 "5분 핑 실패 = 장애?"같은 논쟁이 있었습니다. SLI를 먼저 명확히 정의하면 이런 모호함이 사라집니다.

**주의**: SLO는 "달성 목표"가 아니라 "달성해야 할 최소 기준"이다. SLO를 크게 초과하면 오히려 SLO를 낮추거나 더 공격적인 실험을 해야 한다.

### Q: Error Budget은 무엇이며, 개발 프로세스에 어떻게 활용하나?
**30초 답변**: Error Budget은 SLO에서 허용하는 실패 예산입니다. SLO 99.95%면 0.05%가 Error Budget이고, 월 21.9분의 다운타임이 허용됩니다. 이 예산이 남아있으면 릴리스를 진행하고, 소진되면 안정화에 집중하여 개발 속도와 안정성을 균형잡습니다.

**2분 답변**: Error Budget의 핵심 가치는 "개발과 운영의 갈등을 수학으로 해결한다"는 것입니다. 전통적으로 개발팀은 "빨리 배포하자", 운영팀은 "안정성이 먼저"로 충돌합니다. Error Budget은 이를 "예산이 남았으니 배포하자" vs "예산이 부족하니 안정화하자"로 전환합니다. 운영 방식: (1) 매주 Error Budget 소진율을 리뷰합니다. (2) 75% 이상 남아있으면 정상 릴리스 진행. (3) 50% 미만이면 신규 기능 중단, 안정화 작업만. (4) 0%에 도달하면 포스트모템 후 SLO 재검토 또는 아키텍처 변경. Burn Rate Alert을 사용하면 "현재 속도로 N시간 내 예산 고갈"을 사전에 감지하여, 실제로 0%에 도달하기 전에 대응할 수 있습니다. Error Budget Policy를 문서화하여 Product Owner와 합의하면, "릴리스 중단"이 개인 판단이 아닌 정책적 결정이 됩니다.

**경험 연결**: 인프라 운영에서 변경 관리(Change Management)를 통해 배포 횟수를 제한했는데, Error Budget은 이를 데이터 기반으로 자동화하는 진화된 방식입니다.

**주의**: Error Budget이 항상 많이 남는다면 SLO가 너무 느슨한 것이다. Google SRE는 "Error Budget을 전부 사용하는 것이 이상적"이라고 말한다.

### Q: Burn Rate Alert은 전통적 임계값 알림과 어떻게 다른가?
**30초 답변**: 전통적 알림은 "에러율 > 1%"처럼 절대값 기준이라 비즈니스 영향도를 반영하지 못합니다. Burn Rate Alert은 "현재 속도로 Error Budget을 소진하면 N시간 내 고갈"이라는 비즈니스 영향 기반으로, 진짜 중요한 상황에만 알림을 보냅니다.

**2분 답변**: 전통적 임계값 알림의 문제는 두 가지입니다. 첫째, 짧은 스파이크에 반응하여 노이즈가 많습니다(5분간 에러 급증 후 회복 → 대응 불필요한데 알림 발생). 둘째, 비즈니스 영향도와 연결되지 않습니다(에러율 0.5%가 문제인지 아닌지 컨텍스트 없음). Burn Rate Alert은 이를 해결합니다. Google SRE가 제안한 Multi-window 방식에서는, 긴 윈도우(1h)와 짧은 윈도우(5m) 모두에서 Burn Rate가 임계값을 초과할 때만 알림을 보냅니다. 긴 윈도우는 지속적 문제를 감지하고, 짧은 윈도우는 문제가 현재도 진행 중인지 확인합니다. 예를 들어 Burn Rate 14.4x가 1시간 동안 지속되면, 30일 Error Budget의 2%가 1시간에 소진된 것이므로 즉각 대응(Page)이 필요합니다. 반면 Burn Rate 6x가 6시간 지속이면 5%가 소진된 것이므로 계획적 대응(Ticket)으로 충분합니다. 이 방식은 Alert Fatigue를 크게 줄이면서 실제 비즈니스 영향이 있는 상황을 놓치지 않습니다.

**경험 연결**: 모니터링 시스템에서 짧은 스파이크마다 SMS 알림이 와서 무시하게 되는 경험이 있었습니다. Burn Rate Alert은 "이 문제가 계속되면 SLO를 위반한다"는 비즈니스 의미를 담아 진짜 중요한 알림만 전달합니다.

**주의**: Burn Rate Alert의 수학적 근거를 이해하고 설명할 수 있어야 한다. "왜 14.4x인가?" → 30일 예산의 2%를 1시간에 소진하는 속도 = (0.02 × 30 × 24) / 1 = 14.4.

---

## Allganize 맥락

- **AI 서비스 SLO**: Alli의 추론 API에 Availability + Latency SLO를 설정하여 품질 관리
- **모델별 SLO**: 작은 모델(빠른 응답)과 큰 모델(느린 응답)에 다른 Latency SLO 적용
- **Error Budget과 배포**: GitOps(ArgoCD) 파이프라인에서 Error Budget 확인 후 자동/수동 배포 결정
- **고객 신뢰**: B2B SaaS에서 SLO 대시보드를 고객에게 공유하면 신뢰도 향상
- **스타트업 현실**: 초기에는 SLO를 느슨하게(99.5%) 설정하고 점진적으로 높여가는 것이 실용적

---
**핵심 키워드**: `SLI` `SLO` `SLA` `Error-Budget` `Burn-Rate` `Multi-Window` `Rolling-Window` `Error-Budget-Policy` `Sloth` `Google-SRE`
