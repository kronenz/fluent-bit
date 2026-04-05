# Grafana 시각화와 대시보드 설계

> **TL;DR**: Grafana는 다중 데이터소스를 통합하는 시각화 플랫폼으로, 대시보드/패널/변수 시스템이 핵심이다.
> 좋은 대시보드는 USE/RED 메서드 기반으로 계층적으로 설계하며, 변수(Variables)로 동적 필터링을 구현한다.
> Alert Rules를 Grafana 내에서 정의하고, Contact Points로 다양한 알림 채널에 라우팅할 수 있다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### Grafana 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                   Grafana Server                     │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │Dashboard │  │Alerting  │  │ User/Team/Org    │  │
│  │  Engine  │  │  Engine  │  │   Management     │  │
│  └────┬─────┘  └────┬─────┘  └──────────────────┘  │
│       │              │                               │
│  ┌────▼──────────────▼──────────────────────────┐   │
│  │         Unified Data Source Layer             │   │
│  └──┬──────┬──────┬──────┬──────┬──────┬───────┘   │
│     │      │      │      │      │      │            │
└─────┼──────┼──────┼──────┼──────┼──────┼────────────┘
      │      │      │      │      │      │
      ▼      ▼      ▼      ▼      ▼      ▼
  Prometheus Loki   ES   Datadog Tempo  CloudWatch
```

Grafana 자체는 데이터를 저장하지 않는다. 데이터소스 플러그인을 통해 다양한 백엔드에 쿼리를 보내고 결과를 시각화한다.

### 대시보드 설계 원칙

**계층적 대시보드 구조 (Drill-Down Pattern)**:
```
Level 0: Executive Overview
├── 전체 서비스 SLO 달성률
├── 주요 에러율 트렌드
└── 인프라 비용 요약

Level 1: Service Overview
├── 서비스별 RED 메트릭
├── Pod 상태 (Ready/NotReady)
└── 리소스 사용률 요약

Level 2: Service Detail
├── 엔드포인트별 레이턴시 분포
├── 에러 코드 분석
└── 개별 Pod CPU/Memory

Level 3: Debug
├── 로그 연동 (Loki/ES)
├── 트레이스 연동 (Tempo/Jaeger)
└── 프로파일링 데이터
```

**Golden Signals 대시보드 레이아웃**:
```
┌─────────────────────────────────────────────────┐
│  [Namespace ▼] [Service ▼] [Time Range ▼]       │  ← Variables
├─────────────────────────────────────────────────┤
│  ┌─ Stat ──┐ ┌─ Stat ──┐ ┌─ Stat ──┐ ┌─ Stat ┐│
│  │ RPS     │ │ Error%  │ │ P99 Lat │ │ Satur.││  ← 핵심 지표
│  │ 1,234/s │ │ 0.12%   │ │ 245ms   │ │ 72%   ││
│  └─────────┘ └─────────┘ └─────────┘ └───────┘│
├─────────────────────────────────────────────────┤
│  ┌── Time Series ──────────────────────────────┐│
│  │  Request Rate by Endpoint                   ││  ← 추세
│  │  ▁▂▃▄▅▆▇ ...                               ││
│  └─────────────────────────────────────────────┘│
│  ┌── Time Series ──────┐ ┌── Heatmap ─────────┐│
│  │  Error Rate         │ │  Latency Distrib.  ││  ← 상세
│  │  ▁▂▁▁▃▁▁           │ │  ░▒▓█▓▒░          ││
│  └─────────────────────┘ └─────────────────────┘│
│  ┌── Table ────────────────────────────────────┐│
│  │  Top 10 Slowest Endpoints                   ││  ← 디테일
│  │  /api/inference  │ p99: 1.2s │ count: 500   ││
│  └─────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
```

### 패널 타입별 용도

| 패널 타입 | 용도 | 적합한 데이터 |
|-----------|------|---------------|
| **Time Series** | 시간에 따른 추세 | rate(), 리소스 사용률 |
| **Stat** | 단일 핵심 수치 | 현재 RPS, 에러율, SLO 달성률 |
| **Gauge** | 현재값의 범위 표시 | CPU/Memory 사용률 (0~100%) |
| **Bar Gauge** | 여러 항목 비교 | Pod별 메모리 사용량 |
| **Heatmap** | 분포와 밀도 | 레이턴시 분포 (Histogram) |
| **Table** | 상세 데이터 목록 | Top-N 목록, 로그 요약 |
| **Logs** | 로그 스트림 | Loki/ES 로그 |
| **Node Graph** | 서비스 관계 | 서비스 토폴로지 맵 |

### Variables (템플릿 변수)

```
변수 체이닝 예시:
┌─ $cluster ─┐   ┌── $namespace ──┐   ┌── $service ──┐
│ prod-aws   │──►│ alli-prod      │──►│ alli-api     │
│ prod-azure │   │ alli-staging   │   │ alli-worker  │
│ staging    │   │ monitoring     │   │ alli-gateway │
└────────────┘   └────────────────┘   └──────────────┘
```

```
# Variable 정의 (Prometheus data source)
# $namespace 변수
Type: Query
Query: label_values(kube_pod_info{cluster="$cluster"}, namespace)
Refresh: On time range change

# $service 변수 (namespace에 종속)
Type: Query
Query: label_values(kube_pod_info{namespace="$namespace"}, pod)
Regex: /(.+)-[a-f0-9]+-[a-z0-9]+/   # Pod 이름에서 Deployment 이름 추출
```

패널 쿼리에서 `{namespace="$namespace", service="$service"}`로 참조하면, 드롭다운 변경 시 전체 대시보드가 동적으로 갱신된다.

### Grafana Alerting (Unified Alerting)

```
Alert Rule 평가 흐름:
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌────────────┐
│  Alert   │───►│ Evaluate │───►│  Notification │───►│  Contact   │
│  Rule    │    │ (매 1m)  │    │   Policy      │    │  Point     │
└──────────┘    └──────────┘    │  (라우팅/그룹) │    │(Slack/PD)  │
                    │           └──────────────┘    └────────────┘
                    ▼
              ┌──────────┐
              │ Pending  │ ← For 기간 동안 조건 지속 확인
              │ (5m)     │
              └────┬─────┘
                   ▼
              ┌──────────┐
              │ Firing   │ ← 알림 발송
              └──────────┘
```

```yaml
# Alert Rule 예시 (Grafana UI 또는 Provisioning)
apiVersion: 1
groups:
  - orgId: 1
    name: alli-service-alerts
    folder: Alli Production
    interval: 1m
    rules:
      - uid: high-error-rate
        title: "Alli API Error Rate > 1%"
        condition: C
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: |
                sum(rate(http_requests_total{service="alli-api",status=~"5.."}[5m]))
                / sum(rate(http_requests_total{service="alli-api"}[5m]))
          - refId: B
            datasourceUid: __expr__
            model:
              type: reduce
              reducer: last
              expression: A
          - refId: C
            datasourceUid: __expr__
            model:
              type: threshold
              expression: B
              conditions:
                - evaluator:
                    type: gt
                    params: [0.01]
        for: 5m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Alli API 에러율 {{ $values.B }}% (임계값 1%)"
```

---

## 실전 예시

### Dashboard as Code (Provisioning)

```yaml
# /etc/grafana/provisioning/dashboards/default.yaml
apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: 'Kubernetes'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: true
```

```json
// dashboard JSON 발췌 - 변수 + 패널 정의
{
  "templating": {
    "list": [
      {
        "name": "namespace",
        "type": "query",
        "datasource": "Prometheus",
        "query": "label_values(kube_pod_info, namespace)",
        "refresh": 2,
        "multi": false
      }
    ]
  },
  "panels": [
    {
      "title": "Request Rate",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum(rate(http_requests_total{namespace=\"$namespace\"}[5m])) by (pod)",
          "legendFormat": "{{ pod }}"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "reqps",
          "thresholds": {
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 1000 },
              { "color": "red", "value": 5000 }
            ]
          }
        }
      }
    }
  ]
}
```

### Grafana + Loki 로그 연동

```
# Derived Field 설정으로 로그 → 트레이스 연결
Data Source: Loki
Settings > Derived fields:
  Name: TraceID
  Regex: traceID=(\w+)
  Internal link:
    Data source: Tempo
    Query: ${__value.raw}
```

이 설정으로 로그에서 `traceID=abc123`을 클릭하면 Tempo의 해당 트레이스로 바로 이동할 수 있다.

---

## 면접 Q&A

### Q: 좋은 모니터링 대시보드의 설계 원칙은?
**30초 답변**: 계층적 구조(Overview → Detail → Debug)로 설계하고, Golden Signals(Latency/Traffic/Errors/Saturation) 또는 RED/USE 메서드를 기반으로 패널을 구성합니다. Variables로 동적 필터링하고, 중요한 지표는 Stat 패널로 한눈에 보이게 합니다.

**2분 답변**: 대시보드 설계에서 가장 흔한 실수는 "모든 메트릭을 한 화면에 넣는 것"입니다. 좋은 대시보드는 다음 원칙을 따릅니다. 첫째, **목적 중심**: 누가(on-call, 매니저, 개발자) 무엇을(장애 감지, 용량 계획, 디버깅) 위해 보는지 명확히 합니다. 둘째, **계층적 드릴다운**: Level 0(전체 서비스 건강상태) → Level 1(서비스별) → Level 2(Pod/엔드포인트별) → Level 3(로그/트레이스)로 점점 상세해지는 구조입니다. 셋째, **Golden Signals 기반**: 모든 서비스 대시보드는 최소한 Rate, Error, Duration(RED)을 포함합니다. 넷째, **변수 체이닝**: cluster → namespace → service 순으로 변수를 연결하여 하나의 대시보드로 모든 환경을 커버합니다. 다섯째, **알림 임계값 시각화**: 패널에 threshold line을 그려서 현재 값과 알림 기준을 한눈에 비교할 수 있게 합니다. Grafana의 Annotation 기능으로 배포 시점을 표시하면, 배포 전후 메트릭 변화를 즉시 확인할 수 있습니다.

**경험 연결**: 온프레미스 환경에서 Cacti/MRTG로 네트워크 모니터링 대시보드를 만들었는데, 그래프가 수백 개여서 정작 장애 시 어디를 봐야 할지 혼란스러웠습니다. Grafana의 계층적 구조와 Variables를 활용하면 이 문제가 해결됩니다.

**주의**: 대시보드 수가 많아지면 관리가 어렵다. Dashboard as Code(JSON/Jsonnet/Grafonnet)로 Git 관리하고, Provisioning으로 자동 배포하는 운영 방식도 언급할 것.

### Q: Grafana에서 Variables(템플릿 변수)를 활용하는 방법과 장점은?
**30초 답변**: Variables는 대시보드 상단의 드롭다운으로, 선택값에 따라 모든 패널의 쿼리가 동적으로 변경됩니다. Query 타입으로 Prometheus 레이블 값을 자동 추출하고, 변수 간 체이닝으로 namespace → service → pod 순서의 필터링을 구현합니다.

**2분 답변**: Variables에는 여러 타입이 있습니다. Query 타입은 `label_values(metric, label)`로 데이터소스에서 값을 동적으로 가져옵니다. Custom 타입은 고정 목록(dev, staging, prod), Interval 타입은 시간 간격(1m, 5m, 1h)을 선택하게 합니다. 핵심은 변수 체이닝(Chained Variables)으로, `$cluster` 선택에 따라 `$namespace`의 선택지가 달라지고, `$namespace`에 따라 `$service`가 달라지는 종속 관계를 만들 수 있습니다. Multi-value와 Include All 옵션을 활성화하면 `{namespace=~"$namespace"}` 정규식 매칭으로 여러 값을 동시에 볼 수 있습니다. 이를 통해 하나의 대시보드 정의로 수십 개 서비스를 커버하므로, 대시보드 스프롤(sprawl)을 방지합니다. 또한 `$__interval` 내장 변수는 시간 범위에 따라 자동으로 적절한 rate interval을 조정해줍니다.

**경험 연결**: 서버 수백 대를 모니터링할 때 서버별 대시보드를 따로 만들면 관리가 불가능합니다. Variables로 호스트를 선택하는 구조는 온프레미스 환경에서도 적용했던 패턴이고, K8s에서는 namespace/service 단위로 확장됩니다.

**주의**: Variables의 Query가 너무 무거우면 대시보드 로딩이 느려진다. `label_values()`는 가볍지만, 복잡한 PromQL을 변수로 쓰면 성능 문제가 발생할 수 있다.

### Q: Grafana Alerting과 Prometheus Alertmanager의 차이는?
**30초 답변**: Prometheus Alertmanager는 Prometheus에서 평가된 Alert Rule을 받아 라우팅/그룹핑/사일런싱하는 별도 컴포넌트입니다. Grafana Alerting은 Grafana 내장으로, 다중 데이터소스(Prometheus, Loki, CloudWatch 등)에 대한 알림을 통합 관리할 수 있습니다.

**2분 답변**: Prometheus 방식에서는 Alert Rule을 `prometheus.yml`의 rule file에 정의하고, Prometheus가 평가한 후 Alertmanager로 전송합니다. Alertmanager는 그룹핑, 억제(inhibition), 사일런싱, 라우팅을 담당합니다. Grafana Unified Alerting(8.x+)은 이를 대체할 수 있는 통합 방식입니다. 장점으로는 (1) Prometheus 외 Loki, CloudWatch 등 모든 데이터소스에 대한 알림을 한 곳에서 관리, (2) UI에서 알림 규칙 생성/수정이 쉬움, (3) Notification Policy로 레이블 기반 라우팅(severity=critical → PagerDuty, severity=warning → Slack). 단점으로는 (1) 대규모 환경에서 Grafana에 부하 집중, (2) Prometheus Alertmanager의 고급 기능(inhibition rules)이 제한적. 실무에서는 인프라 알림은 Prometheus Alertmanager, 비즈니스/멀티소스 알림은 Grafana Alerting으로 혼합 운영하는 경우가 많습니다.

**경험 연결**: 온프레미스에서 Zabbix의 트리거+액션으로 알림을 관리했는데, 데이터소스가 다양해지면 각각 알림 체계를 따로 운영해야 했습니다. Grafana Alerting은 이를 하나로 통합하는 관점에서 유리합니다.

**주의**: "Grafana Alerting이 Alertmanager를 완전히 대체한다"고 말하지 말 것. 각각의 장단점이 있으며, 혼합 운영이 일반적이다.

---

## Allganize 맥락

- **JD 연결**: "Prometheus/Grafana 기반 모니터링" - Grafana는 통합 시각화 레이어로 핵심 도구
- **멀티클라우드 뷰**: AWS/Azure 클러스터별 Prometheus를 Grafana 데이터소스로 등록하여 단일 대시보드에서 전체 인프라 조회
- **LLM 서비스 대시보드**: Alli 서비스의 추론 지연시간, 토큰 처리량, 모델별 에러율을 RED 패턴으로 시각화
- **팀 협업**: Grafana의 Organization/Team 기능으로 개발팀별 대시보드 접근 권한 분리
- **Dashboard as Code**: GitOps 파이프라인에서 대시보드 JSON을 버전 관리하고, ArgoCD로 Grafana에 자동 프로비저닝

---
**핵심 키워드**: `Grafana` `Dashboard` `Panel` `Variables` `Drill-Down` `Golden-Signals` `Unified-Alerting` `Contact-Point` `Provisioning` `Dashboard-as-Code`
