# SLI / SLO / SLA 와 Error Budget

> **TL;DR**
> 1. SLI는 측정 지표, SLO는 목표 수준, SLA는 고객과의 계약이다. SLI -> SLO -> SLA 순서로 정의한다.
> 2. Error Budget은 "허용된 실패 예산"으로, 개발 속도와 안정성의 균형을 객관적으로 잡아준다.
> 3. Multi-window, Multi-burn-rate 알림은 알림 피로(alert fatigue)를 줄이면서 실제 문제를 놓치지 않는 핵심 기법이다.

---

## 1. 핵심 개념 정의

### SLI (Service Level Indicator) - 서비스 수준 지표

> 서비스 품질을 **측정**하는 구체적인 지표

```
SLI = (정상 이벤트 수) / (전체 이벤트 수) x 100%

예시:
- 가용성 SLI = (2xx/3xx 응답 수) / (전체 요청 수) x 100%
- 지연 시간 SLI = (500ms 이내 응답 수) / (전체 요청 수) x 100%
- 정확도 SLI = (정확한 응답 수) / (전체 응답 수) x 100%
```

### SLO (Service Level Objective) - 서비스 수준 목표

> SLI에 대한 **목표 범위**

```
SLO = SLI가 특정 기간 동안 달성해야 하는 목표값

예시:
- "30일 동안 가용성 SLI >= 99.9%"
- "30일 동안 지연 시간 SLI (p99 < 500ms) >= 99.5%"
- "분기 동안 정확도 SLI >= 95%"
```

### SLA (Service Level Agreement) - 서비스 수준 협약

> SLO를 기반으로 한 **고객과의 계약** (위반 시 보상 포함)

```
SLA = SLO + 법적 결과 (보상/패널티)

예시:
- "월간 가용성 99.9% 미만 시 서비스 크레딧 10% 지급"
- "월간 가용성 99.0% 미만 시 서비스 크레딧 30% 지급"
```

### 3자 관계

```
                    정의 주체        용도
SLI  ───────>  엔지니어링 팀    ──>  "무엇을 측정하는가?"
  |
  v
SLO  ───────>  엔지니어링 + 비즈니스 ──>  "얼마나 좋아야 하는가?"
  |
  v
SLA  ───────>  비즈니스 + 법무    ──>  "못 지키면 어떻게 되는가?"

주의: SLA >= SLO (SLA는 SLO보다 느슨하게 설정)
예: 내부 SLO = 99.95%, 외부 SLA = 99.9%
```

---

## 2. SLI 선정 가이드

### Google SRE가 권장하는 SLI 유형

| SLI 유형 | 측정 대상 | 적합한 서비스 |
|----------|----------|-------------|
| **가용성 (Availability)** | 성공 요청 비율 | 모든 서비스 |
| **지연 시간 (Latency)** | 응답 시간 분포 | 사용자 대면 API |
| **처리량 (Throughput)** | 단위 시간당 처리량 | 데이터 파이프라인 |
| **정확성 (Correctness)** | 올바른 결과 비율 | 데이터 처리, AI 서비스 |
| **신선도 (Freshness)** | 데이터 최신성 | 검색 인덱스, 캐시 |
| **내구성 (Durability)** | 데이터 보존율 | 스토리지 서비스 |

### 올거나이즈 Alli 서비스 SLI 예시

```yaml
# Alli Chat API SLI 정의
alli_chat_api:
  availability:
    description: "채팅 API 가용성"
    formula: |
      sum(rate(http_requests_total{service="alli-api", status!~"5.."}[30d]))
      /
      sum(rate(http_requests_total{service="alli-api"}[30d]))
    target_slo: 99.9%

  latency:
    description: "채팅 API 응답 시간 (p99 < 5초)"
    formula: |
      sum(rate(http_request_duration_seconds_bucket{
        service="alli-api", le="5.0"
      }[30d]))
      /
      sum(rate(http_request_duration_seconds_count{
        service="alli-api"
      }[30d]))
    target_slo: 99.5%

  llm_success:
    description: "LLM 추론 성공률"
    formula: |
      sum(rate(llm_requests_total{status="success"}[30d]))
      /
      sum(rate(llm_requests_total[30d]))
    target_slo: 99.5%

  rag_quality:
    description: "RAG 검색 정확도 (관련 문서 포함 비율)"
    formula: |
      sum(rate(rag_search_total{relevant="true"}[30d]))
      /
      sum(rate(rag_search_total[30d]))
    target_slo: 95.0%
```

---

## 3. Error Budget (에러 예산)

### 개념

```
Error Budget = 1 - SLO

SLO 99.9%인 경우:
- Error Budget = 0.1%
- 30일 기준: 43.2분의 장애 허용
- 분당 1000 요청 기준: 30일 동안 43,200건의 실패 허용
```

### 가용성별 Error Budget

| SLO | Error Budget | 30일 허용 다운타임 | 연간 허용 다운타임 |
|-----|-------------|------------------|-----------------|
| 99% | 1% | 7시간 12분 | 3일 15시간 |
| 99.5% | 0.5% | 3시간 36분 | 1일 19시간 |
| 99.9% | 0.1% | 43분 12초 | 8시간 46분 |
| 99.95% | 0.05% | 21분 36초 | 4시간 23분 |
| 99.99% | 0.01% | 4분 19초 | 52분 36초 |

### Error Budget 운영 정책

```
Error Budget 상태에 따른 행동 지침:

[정상] Budget 잔여 > 50%
  -> 새 기능 배포 정상 진행
  -> 실험적 변경 허용

[주의] Budget 잔여 20% ~ 50%
  -> 배포 전 추가 검증 강화
  -> 위험한 변경 자제

[경고] Budget 잔여 < 20%
  -> 안정성 작업만 수행
  -> 새 기능 배포 동결

[소진] Budget 잔여 = 0%
  -> 모든 배포 중단
  -> 안정성 개선 집중
  -> 포스트모템 실시
```

### Error Budget 대시보드 PromQL

```promql
# 현재 SLI (가용성) - 최근 30일
(
  sum(rate(http_requests_total{service="alli-api", status!~"5.."}[30d]))
  /
  sum(rate(http_requests_total{service="alli-api"}[30d]))
) * 100

# Error Budget 소비율 (%)
(
  1 - (
    sum(rate(http_requests_total{service="alli-api", status!~"5.."}[30d]))
    /
    sum(rate(http_requests_total{service="alli-api"}[30d]))
  )
) / (1 - 0.999) * 100

# Error Budget 잔여 (%)
100 - (
  (
    1 - (
      sum(rate(http_requests_total{service="alli-api", status!~"5.."}[30d]))
      /
      sum(rate(http_requests_total{service="alli-api"}[30d]))
    )
  ) / (1 - 0.999) * 100
)
```

---

## 4. 알림 임계값 설계

### 기존 방식의 문제

```
# 나쁜 알림: 단순 임계값
ALERT: 에러율 > 1% for 5m

문제점:
1. 순간 스파이크에 과민 반응 -> 알림 피로
2. 느리게 진행되는 장애를 놓침
3. Error Budget과의 연관성 부재
```

### Multi-window, Multi-burn-rate 알림

**Burn Rate**: Error Budget을 소비하는 속도

```
Burn Rate = 1이면: SLO 기간(30일) 동안 정확히 Budget 소진
Burn Rate = 2이면: 15일 만에 Budget 소진
Burn Rate = 10이면: 3일 만에 Budget 소진
Burn Rate = 14.4이면: 약 2일 만에 Budget 소진
```

**Multi-window**: 짧은 창(short window)과 긴 창(long window) 모두에서 확인

```
# 핵심 원리: 두 개의 시간 창을 사용하여 거짓 양성을 줄인다
# Long window: 실제로 Budget이 소비되고 있는지 확인
# Short window: 문제가 현재 진행 중인지 확인 (이미 해결된 문제에 알림 방지)
```

### 실행 가능한 알림 규칙

```yaml
# Google SRE Workbook 권장 Multi-window, Multi-burn-rate 알림
# SLO: 99.9% (30일), Error Budget: 0.1%

groups:
  - name: slo-alerts-alli-api
    rules:
      # === 심각 (Critical): 빠른 소비 ===
      # Burn rate 14.4x: 2일 만에 Budget 소진
      # Long window: 1h, Short window: 5m
      - alert: AlliAPIHighBurnRate_Critical
        expr: |
          (
            1 - (
              sum(rate(http_requests_total{service="alli-api", status!~"5.."}[1h]))
              /
              sum(rate(http_requests_total{service="alli-api"}[1h]))
            )
          ) > (14.4 * 0.001)
          and
          (
            1 - (
              sum(rate(http_requests_total{service="alli-api", status!~"5.."}[5m]))
              /
              sum(rate(http_requests_total{service="alli-api"}[5m]))
            )
          ) > (14.4 * 0.001)
        for: 2m
        labels:
          severity: critical
          slo: "alli-api-availability"
        annotations:
          summary: "Alli API Error Budget 급속 소진 (Burn Rate 14.4x)"
          description: |
            현재 에러율이 Error Budget을 2일 안에 소진하는 속도입니다.
            즉시 대응이 필요합니다.
          runbook: "https://wiki.internal/runbook/slo-burn-rate"

      # === 경고 (Warning): 중간 속도 소비 ===
      # Burn rate 6x: 5일 만에 Budget 소진
      # Long window: 6h, Short window: 30m
      - alert: AlliAPIHighBurnRate_Warning
        expr: |
          (
            1 - (
              sum(rate(http_requests_total{service="alli-api", status!~"5.."}[6h]))
              /
              sum(rate(http_requests_total{service="alli-api"}[6h]))
            )
          ) > (6 * 0.001)
          and
          (
            1 - (
              sum(rate(http_requests_total{service="alli-api", status!~"5.."}[30m]))
              /
              sum(rate(http_requests_total{service="alli-api"}[30m]))
            )
          ) > (6 * 0.001)
        for: 5m
        labels:
          severity: warning
          slo: "alli-api-availability"
        annotations:
          summary: "Alli API Error Budget 소진 경고 (Burn Rate 6x)"

      # === 정보 (Info): 느린 소비 ===
      # Burn rate 1x: 30일 만에 Budget 소진
      # Long window: 3d, Short window: 6h
      - alert: AlliAPIBurnRate_Info
        expr: |
          (
            1 - (
              sum(rate(http_requests_total{service="alli-api", status!~"5.."}[3d]))
              /
              sum(rate(http_requests_total{service="alli-api"}[3d]))
            )
          ) > (1 * 0.001)
          and
          (
            1 - (
              sum(rate(http_requests_total{service="alli-api", status!~"5.."}[6h]))
              /
              sum(rate(http_requests_total{service="alli-api"}[6h]))
            )
          ) > (1 * 0.001)
        for: 30m
        labels:
          severity: info
          slo: "alli-api-availability"
        annotations:
          summary: "Alli API Error Budget 지속적 소진 중 (Burn Rate 1x)"
```

### 알림 계층 요약표

| 심각도 | Burn Rate | Budget 소진 시점 | Long Window | Short Window | 대응 |
|--------|-----------|-----------------|-------------|-------------|------|
| Critical | 14.4x | 2일 | 1시간 | 5분 | 즉시 대응 |
| Warning | 6x | 5일 | 6시간 | 30분 | 당일 대응 |
| Info | 1x | 30일 | 3일 | 6시간 | 계획적 대응 |

---

## 5. Grafana SLO 대시보드 설계

```
+--------------------------------------------------+
|              Alli API SLO Dashboard               |
+--------------------------------------------------+
| [SLO 현황]                                        |
| 가용성: 99.95% (목표: 99.9%)  [========= ] 녹색   |
| 지연시간: 99.7% (목표: 99.5%) [========  ] 녹색   |
| LLM 성공: 99.3% (목표: 99.5%) [=======  ] 적색   |
+--------------------------------------------------+
| [Error Budget 잔여]                                |
| 가용성 Budget: 72% 남음    [=======---] 30일 중    |
| 지연시간 Budget: 60% 남음  [======----] 30일 중    |
| LLM Budget: -20% 초과!!   [XXXXXXXXXX] 초과 경고  |
+--------------------------------------------------+
| [Burn Rate 추이 (7일)]                             |
| 1x -------- 기준선 --------                        |
| 그래프: 실시간 Burn Rate 추이                       |
+--------------------------------------------------+
| [최근 장애 이벤트]                                  |
| 01/14 03:22 LLM 제공업체 장애 (45분, Budget 5% 소비)|
| 01/10 15:00 배포 롤백 (12분, Budget 1% 소비)       |
+--------------------------------------------------+
```

---

## 6. 올거나이즈 Alli에 적용 가능한 SLI 종합

```yaml
# alli-sli-definitions.yaml
service: alli-chat-platform

slis:
  # 1. 채팅 API 가용성
  - name: chat_api_availability
    type: availability
    description: "사용자 채팅 API의 비오류(non-5xx) 응답 비율"
    slo_target: 99.9%
    slo_window: 30d
    promql: |
      sum(rate(http_requests_total{service="alli-api",status!~"5.."}[{{window}}]))
      / sum(rate(http_requests_total{service="alli-api"}[{{window}}]))

  # 2. 채팅 응답 지연 시간
  - name: chat_api_latency
    type: latency
    description: "채팅 API p99 응답 시간 5초 이내 비율"
    slo_target: 99.5%
    slo_window: 30d
    promql: |
      sum(rate(http_request_duration_seconds_bucket{
        service="alli-api",le="5.0"}[{{window}}]))
      / sum(rate(http_request_duration_seconds_count{
        service="alli-api"}[{{window}}]))

  # 3. LLM 추론 성공률
  - name: llm_inference_success
    type: availability
    description: "LLM 추론 요청의 성공 비율 (타임아웃, 에러 제외)"
    slo_target: 99.5%
    slo_window: 30d
    promql: |
      sum(rate(llm_requests_total{status="success"}[{{window}}]))
      / sum(rate(llm_requests_total[{{window}}]))

  # 4. RAG 검색 품질
  - name: rag_retrieval_quality
    type: correctness
    description: "벡터 검색에서 관련 문서가 top-5에 포함된 비율"
    slo_target: 95.0%
    slo_window: 30d
    note: "오프라인 평가와 온라인 피드백 조합 측정"

  # 5. 챗봇 세션 완료율
  - name: session_completion_rate
    type: quality
    description: "사용자가 원하는 답을 얻고 세션을 정상 종료한 비율"
    slo_target: 90.0%
    slo_window: 30d
    note: "사용자 피드백 기반 측정 (thumbs up/down)"

  # 6. 데이터 파이프라인 신선도
  - name: knowledge_base_freshness
    type: freshness
    description: "지식 베이스 업데이트가 1시간 이내에 반영된 비율"
    slo_target: 99.0%
    slo_window: 30d
    promql: |
      sum(rate(kb_update_total{within_sla="true"}[{{window}}]))
      / sum(rate(kb_update_total[{{window}}]))
```

---

## 7. SLO 도입 실무 가이드

### 단계별 도입 전략

```
[1단계: 측정 시작] (2주)
- RED 메트릭 수집 (Rate, Error, Duration)
- 현재 서비스 수준 파악 (baseline 측정)
- "SLO를 정하기 전에 먼저 측정하라"

[2단계: SLO 설정] (1주)
- 비즈니스 팀과 협의하여 목표 설정
- 너무 높지도, 너무 낮지도 않게 (현재 수준 기반)
- Error Budget 계산

[3단계: 대시보드 구축] (1주)
- SLI 현황, Error Budget 잔여량, Burn Rate 시각화
- 주간 SLO 리뷰 미팅 시작

[4단계: 알림 설정] (1주)
- Multi-window, Multi-burn-rate 알림 적용
- 기존 임계값 기반 알림 점진적 대체

[5단계: 문화 정착] (지속)
- Error Budget 기반 배포 결정
- 포스트모템에 SLO 영향도 포함
- 분기별 SLO 재검토
```

---

## 8. 10년 경력 연결 포인트

> **경력자의 강점**: 10년간 인프라를 운영하면서 "알림 피로(alert fatigue)"를 반드시 경험했을 것이다. 새벽에 울린 알림이 거짓 양성이었던 경험, 반대로 임계값이 너무 느슨해서 장애를 늦게 감지한 경험을 SLO 기반 알림의 필요성과 연결하면 매우 설득력 있다. 또한 비즈니스 팀과 SLA를 협의한 경험이 있다면 "엔지니어링 목표와 비즈니스 목표를 정량적으로 정렬"하는 SLO의 가치를 실감하고 있다는 것을 어필할 수 있다.

---

## 9. 면접 Q&A

### Q1. SLI, SLO, SLA의 차이를 설명해주세요.

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "SLI는 서비스 품질을 측정하는 지표입니다. 예를 들어 '성공한 요청 비율'이나 'p99 응답 시간이 500ms 이내인 요청 비율'입니다. SLO는 이 SLI가 달성해야 하는 목표로, '30일간 가용성 99.9% 이상'과 같습니다. SLA는 SLO를 기반으로 고객과 맺는 계약으로, 위반 시 서비스 크레딧 등의 보상이 포함됩니다. 중요한 점은 SLO를 SLA보다 엄격하게 설정하는 것입니다. 내부 목표를 99.95%로 잡고 고객 SLA를 99.9%로 설정하면, SLO 위반 시에도 SLA를 지킬 수 있는 여유가 생깁니다."

### Q2. Error Budget이 소진되면 어떻게 하나요?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "Error Budget이 소진되면 새 기능 배포를 동결하고 안정성 개선에 집중합니다. 이것이 Error Budget의 핵심 가치입니다. 개발팀에게 '안정성이 중요하니까 배포를 멈추세요'라고 말하면 갈등이 생기지만, '이번 달 Error Budget을 다 써서 정책에 따라 배포를 동결합니다'라고 하면 객관적인 기준이 됩니다. 구체적으로는 포스트모템을 실시하여 Budget을 소진시킨 원인을 분석하고, 재발 방지 액션 아이템을 도출합니다. Budget이 회복되면 배포를 재개하되, 카나리 배포 비율을 더 보수적으로 설정합니다."

### Q3. Multi-burn-rate 알림이 기존 임계값 알림보다 좋은 이유는?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "기존 임계값 알림은 두 가지 문제가 있습니다. 첫째, 순간 스파이크에 알림이 울리지만 자동 복구되는 거짓 양성이 많습니다. 둘째, 느리게 진행되는 장애를 놓칩니다. 에러율이 0.5%로 임계값 1% 미만이지만, 이 상태가 2주 지속되면 Error Budget은 소진됩니다. Multi-burn-rate 알림은 이 두 문제를 모두 해결합니다. 빠른 소비(Burn Rate 14.4x)는 1시간+5분 이중 창으로 심각한 장애를 즉시 감지하고, 느린 소비(Burn Rate 1x)는 3일+6시간 이중 창으로 천천히 진행되는 문제도 잡아냅니다. 짧은 창(Short Window)은 이미 해결된 문제에 알림이 울리는 것을 방지합니다."

### Q4. 올거나이즈 Alli 서비스에 SLI를 정의한다면?

> **면접에서 이렇게 물어보면 -> 이렇게 대답한다**
>
> "Alli는 AI 채팅 서비스이므로 전통적 SLI와 AI 특화 SLI를 함께 정의합니다. 전통적 SLI로는 API 가용성(99.9%), 응답 지연 시간 p99(5초 이내, 99.5%)을 설정합니다. AI 서비스는 응답 시간이 길 수 있으므로 임계값을 5초로 넉넉하게 잡습니다. AI 특화 SLI로는 LLM 추론 성공률(99.5%), RAG 검색 품질(관련 문서 top-5 포함률 95%)을 추가합니다. 비즈니스 SLI로는 세션 완료율(사용자가 만족스러운 답을 얻은 비율 90%)을 정의합니다. 이렇게 기술 지표와 비즈니스 지표를 연결하면 QoE(Quality of Experience) 유지라는 올거나이즈의 미션에 직접 기여할 수 있습니다."

---

## 핵심 키워드 5선

`SLI/SLO/SLA` `Error Budget` `Multi-window Multi-burn-rate` `Burn Rate` `QoE (Quality of Experience)`
