# 장애 대응 프로세스: 감지에서 복구까지

> **TL;DR**: 장애 대응은 Detect(감지) → Classify(분류) → Mitigate(완화) → Recover(복구) → Review(검토) 5단계로 구성된다.
> MTTD(감지 시간)와 MTTR(복구 시간)이 핵심 지표이며, 프로세스 정립이 기술 역량만큼 중요하다.
> Runbook과 자동화된 워크플로우로 장애 대응의 일관성과 속도를 보장한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 25min

---

## 핵심 개념

### 장애 대응 5단계 프로세스

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ DETECT   │───►│ CLASSIFY │───►│ MITIGATE │───►│ RECOVER  │───►│ REVIEW   │
│ 감지     │    │ 분류     │    │ 완화     │    │ 복구     │    │ 검토     │
│          │    │          │    │          │    │          │    │          │
│ • 모니터링│    │ • 심각도 │    │ • 즉각   │    │ • 근본   │    │ • 포스트 │
│ • 알림   │    │   판정   │    │   조치   │    │   원인   │    │   모템   │
│ • 고객   │    │ • 영향   │    │ • 통신   │    │   해결   │    │ • 개선   │
│   리포트 │    │   범위   │    │ • 롤백   │    │ • 재발   │    │   계획   │
│          │    │ • 역할   │    │ • 우회   │    │   방지   │    │ • 문서화│
│          │    │   배정   │    │          │    │          │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                                                               │
     └───────── MTTD ──────── MTTR ──────────────────────────────────┘
```

### 핵심 시간 지표

```
시간 흐름:
──────────────────────────────────────────────────────────────►
│           │           │              │              │
장애 발생    감지         대응 시작       서비스 복구     근본 해결
│           │           │              │              │
├── MTTD ──►├── MTTA ──►├── MTTM ────►├── MTTR ─────►│
   (Mean       (Mean       (Mean          (Mean
    Time to     Time to     Time to        Time to
    Detect)     Ack.)       Mitigate)      Recover)

MTTD: 장애 발생 → 알림 수신까지의 시간
MTTA: 알림 수신 → 담당자가 Acknowledge까지의 시간
MTTM: Acknowledge → 사용자 영향 완화까지의 시간
MTTR: 장애 발생 → 서비스 완전 복구까지의 시간

MTTR = MTTD + MTTA + MTTM + (복구 확인 시간)
```

**개선 전략**:
```
MTTD 줄이기:                    MTTR 줄이기:
├─ SLO 기반 Burn Rate Alert    ├─ Runbook 준비
├─ 합성 모니터링(Synthetic)     ├─ 자동 롤백 파이프라인
├─ 이상 감지(Anomaly Detection)├─ Feature Flag로 기능 단위 비활성화
└─ 실시간 로그/트레이스 분석    ├─ 카나리 배포로 조기 감지
                                └─ 사전 Game Day 훈련
```

### 장애 심각도 분류 (Severity Classification)

```
┌──────┬────────────────────────────────────────────────────────┐
│ SEV1 │ 전면 장애: 핵심 서비스 완전 불가                        │
│      │ 예: Alli API 전체 다운, 데이터 손실                     │
│      │ 대응: 즉시 Incident Commander 지정, 전원 소집           │
│      │ 목표 MTTR: < 1시간                                     │
├──────┼────────────────────────────────────────────────────────┤
│ SEV2 │ 주요 기능 장애: 핵심 기능 일부 불가                     │
│      │ 예: 특정 모델 추론 실패, 특정 리전 접속 불가            │
│      │ 대응: On-call 즉각 대응, 필요 시 추가 인원             │
│      │ 목표 MTTR: < 4시간                                     │
├──────┼────────────────────────────────────────────────────────┤
│ SEV3 │ 부분 장애: 일부 사용자/기능 영향                        │
│      │ 예: 응답 지연 증가, 비핵심 기능 오류                    │
│      │ 대응: 업무 시간 내 대응, 모니터링 강화                  │
│      │ 목표 MTTR: < 1 영업일                                  │
├──────┼────────────────────────────────────────────────────────┤
│ SEV4 │ 경미한 이슈: 사용자 영향 최소                           │
│      │ 예: 로그 수집 지연, 내부 대시보드 오류                  │
│      │ 대응: 백로그에 등록, 일반 업무로 처리                   │
│      │ 목표: 다음 스프린트 내 해결                             │
└──────┴────────────────────────────────────────────────────────┘
```

### Incident Response 역할 (ICS)

```
Incident Command System (ICS):

┌─────────────────────────────────┐
│     Incident Commander (IC)      │
│  ┌───────────────────────────┐  │
│  │ • 전체 상황 관리           │  │
│  │ • 의사결정 (롤백 여부 등)  │  │
│  │ • 커뮤니케이션 총괄        │  │
│  │ • 에스컬레이션 판단        │  │
│  └───────────────────────────┘  │
└─────────┬──────────┬────────────┘
          │          │
┌─────────▼──┐  ┌────▼─────────┐  ┌────────────────┐
│ Operations │  │Communication │  │  Subject Matter │
│ Lead       │  │ Lead         │  │  Expert (SME)   │
│            │  │              │  │                 │
│ • 기술적   │  │ • 고객 공지  │  │ • 해당 서비스   │
│   조사/복구│  │ • 내부 상황  │  │   전문가        │
│ • 롤백 실행│  │   공유       │  │ • 근본 원인    │
│ • 로그/    │  │ • 타임라인   │  │   분석          │
│   메트릭   │  │   기록       │  │                 │
│   분석     │  │              │  │                 │
└────────────┘  └──────────────┘  └────────────────┘
```

### 장애 대응 워크플로우 (Slack 기반)

```
1. 알림 수신 (PagerDuty → On-call)
   │
2. Incident 선언 (/incident create "Alli API 에러율 급증")
   │  ← Slack에 #inc-2024-0115-alli-api 채널 자동 생성
   │  ← JIRA 티켓 자동 생성
   │  ← 관련자 자동 초대
   │
3. 역할 배정
   │  IC: @alice, Ops: @bob, Comms: @charlie
   │
4. 상황 파악 (MTTD → MTTA)
   │  ├─ 대시보드 확인: 에러율, 레이턴시, Pod 상태
   │  ├─ 로그 확인: 에러 패턴, 스택트레이스
   │  ├─ 트레이스 확인: 병목 서비스 식별
   │  └─ 최근 변경사항: 배포, 설정 변경, 인프라 변경
   │
5. 즉각 완화 (Mitigate)
   │  ├─ Option A: 직전 버전으로 롤백
   │  ├─ Option B: Feature Flag로 문제 기능 비활성화
   │  ├─ Option C: 트래픽 다른 리전으로 전환
   │  └─ Option D: 수평 스케일아웃
   │
6. 상태 업데이트 (15분 간격)
   │  "현재 상황: 롤백 진행 중, 예상 복구 시간 15분"
   │  → 내부 Slack + 고객 Status Page
   │
7. 서비스 복구 확인
   │  ├─ SLI 지표 정상 범위 확인
   │  ├─ 고객 접근 테스트
   │  └─ 알림 해제 확인
   │
8. Incident 종료 (/incident resolve)
   │  ← 자동으로 타임라인 요약 생성
   │  ← 포스트모템 일정 자동 등록 (72시간 이내)
```

### Runbook 작성 가이드

```markdown
# Runbook: Alli API High Error Rate

## 개요
- **알림**: AlliAPIHighErrorBurnRate
- **심각도**: SEV2
- **영향**: 사용자 추론 요청 실패
- **On-call 팀**: Platform Team

## 즉각 확인 (2분 이내)
1. Grafana 대시보드 확인: [링크]
   - 에러율 추이 (갑자기? 점진적?)
   - 영향받는 엔드포인트
2. 최근 배포 확인:
   ```
   kubectl -n alli-prod rollout history deploy/alli-api
   ```
3. Pod 상태 확인:
   ```
   kubectl -n alli-prod get pods -l app=alli-api
   kubectl -n alli-prod top pods -l app=alli-api
   ```

## 진단 분기

### 특정 Pod만 에러 → Pod 문제
```
kubectl -n alli-prod logs <pod> --tail=100
kubectl -n alli-prod describe pod <pod>
# OOMKill이면 → 메모리 limit 증가
# CrashLoop이면 → 로그 확인 후 롤백
```

### 전체 Pod 에러 → 외부 의존성 문제
```
# MongoDB 상태 확인
kubectl -n alli-prod exec -it mongo-0 -- mongo --eval "rs.status()"
# Redis 상태 확인
kubectl -n alli-prod exec -it redis-0 -- redis-cli ping
# GPU 노드 상태 확인
kubectl get nodes -l gpu=true -o wide
```

### 최근 배포 후 에러 → 롤백
```
kubectl -n alli-prod rollout undo deploy/alli-api
kubectl -n alli-prod rollout status deploy/alli-api
```

## 에스컬레이션 기준
- 15분 내 원인 파악 불가 → IC에게 SEV1 승격 요청
- 데이터 손실 의심 → 즉시 SEV1, DB 팀 소집
- GPU 노드 이슈 → ML 팀 호출

## 복구 확인
- [ ] 에러율 < 0.1% (5분 유지)
- [ ] p99 레이턴시 < 2s
- [ ] 고객 접근 테스트 성공
- [ ] 알림 해제(Resolved) 확인
```

---

## 실전 예시

### Synthetic Monitoring (합성 모니터링)

```python
# 실제 사용자 요청을 시뮬레이션하여 MTTD를 줄이는 방법
# Datadog Synthetic Test 또는 자체 구현

import requests
import time
from prometheus_client import Gauge, Histogram, start_http_server

probe_success = Gauge('probe_success', 'Whether probe succeeded', ['target'])
probe_duration = Histogram('probe_duration_seconds', 'Probe duration',
                          ['target'], buckets=[0.1, 0.5, 1, 2, 5, 10])

def probe_alli_api():
    """Alli API 헬스 프로브 - 실제 추론 요청까지 테스트"""
    targets = {
        "health": "https://api.allganize.ai/health",
        "inference": "https://api.allganize.ai/v1/inference",
    }

    for name, url in targets.items():
        try:
            start = time.time()
            if name == "inference":
                resp = requests.post(url, json={
                    "model": "test-model",
                    "prompt": "ping",
                    "max_tokens": 1
                }, timeout=10)
            else:
                resp = requests.get(url, timeout=5)

            duration = time.time() - start
            probe_duration.labels(target=name).observe(duration)

            if resp.status_code == 200:
                probe_success.labels(target=name).set(1)
            else:
                probe_success.labels(target=name).set(0)
        except Exception:
            probe_success.labels(target=name).set(0)
            probe_duration.labels(target=name).observe(10)

# 1분 간격으로 프로브 실행
```

### 자동 롤백 파이프라인 (ArgoCD + Prometheus)

```yaml
# ArgoCD Rollout with automated rollback
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: alli-api
  namespace: alli-prod
spec:
  strategy:
    canary:
      canaryService: alli-api-canary
      stableService: alli-api-stable
      steps:
        - setWeight: 10
        - pause: {duration: 5m}
        - setWeight: 30
        - pause: {duration: 5m}
        - setWeight: 60
        - pause: {duration: 5m}
        - setWeight: 100
      analysis:
        templates:
          - templateName: error-rate-check
        startingStep: 1   # 첫 pause부터 분석 시작
        args:
          - name: service
            value: alli-api
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: error-rate-check
spec:
  metrics:
    - name: error-rate
      interval: 1m
      failureLimit: 3
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            sum(rate(http_requests_total{service="{{args.service}}",status=~"5.."}[2m]))
            / sum(rate(http_requests_total{service="{{args.service}}"}[2m]))
      successCondition: result[0] < 0.01   # 에러율 1% 미만
      # 3번 연속 실패 시 자동 롤백
```

---

## 면접 Q&A

### Q: MTTD와 MTTR을 줄이기 위한 전략은?
**30초 답변**: MTTD는 SLO 기반 Burn Rate Alert, Synthetic Monitoring, 이상 감지로 줄입니다. MTTR은 Runbook 정비, 자동 롤백 파이프라인, Feature Flag, Game Day 훈련으로 줄입니다. 두 지표 모두 프로세스와 자동화의 문제입니다.

**2분 답변**: MTTD 개선 전략: (1) **Burn Rate Alert**: 전통적 임계값 알림 대신 Error Budget 소진 속도 기반 알림으로, 비즈니스 영향이 큰 장애를 빠르게 감지합니다. (2) **Synthetic Monitoring**: 실제 사용자 요청을 시뮬레이션하여, 모니터링 지표로는 보이지 않는 문제(DNS 장애, CDN 캐시 오류)를 감지합니다. (3) **Anomaly Detection**: Datadog Watchdog이나 ML 기반 이상 감지로 패턴 변화를 자동 탐지합니다. MTTR 개선 전략: (1) **Runbook**: 모든 Critical 알림에 단계별 대응 절차를 연결하여, 새벽 On-call에서도 체계적 대응이 가능합니다. (2) **자동 롤백**: ArgoCD Rollout의 Analysis로 카나리 배포 중 에러 감지 시 자동 롤백합니다. (3) **Feature Flag**: 코드 배포와 기능 활성화를 분리하여, 문제 기능만 비활성화할 수 있습니다. 전체 롤백보다 영향 범위가 작습니다. (4) **Game Day**: 의도적으로 장애를 유발(Chaos Engineering)하여 대응 프로세스를 사전 검증합니다.

**경험 연결**: 온프레미스에서 장애 대응 시 "누가 어디를 봐야 하는지" 혼란으로 MTTR이 길어지는 경우가 많았습니다. Runbook과 명확한 역할 배정이 가장 큰 개선 효과를 줬습니다.

**주의**: MTTR을 0으로 만들 수는 없다. 목표는 "충분히 짧게"이며, SLO의 Error Budget 내에서 관리하는 것.

### Q: 장애 상황에서의 커뮤니케이션 전략은?
**30초 답변**: Incident Commander가 커뮤니케이션을 총괄하고, 15분 간격으로 상태를 업데이트합니다. 내부(Slack Incident Channel)와 외부(Status Page)를 분리하며, "무엇을 모르는지"도 투명하게 공유합니다.

**2분 답변**: 장애 커뮤니케이션의 핵심 원칙은 네 가지입니다. 첫째, **단일 채널**: 전용 Incident 채널에서만 소통하여 정보 분산을 방지합니다. Slack Bot이 자동으로 `#inc-YYYY-MMDD-title` 채널을 생성하고 관련자를 초대합니다. 둘째, **주기적 업데이트**: 15분 간격으로 현재 상황, 진행 중인 조치, 예상 복구 시간을 공유합니다. 새로운 정보가 없어도 "변경 없음, 계속 조사 중"이라고 알려야 합니다. 셋째, **내외부 분리**: 내부 채널에서는 기술 상세를 논의하고, 고객용 Status Page에는 영향과 예상 복구 시간만 공유합니다. 넷째, **타임라인 기록**: Communication Lead가 모든 이벤트(알림 수신, 원인 파악, 조치 실행, 복구 확인)의 시각을 기록합니다. 이는 포스트모템의 핵심 자료가 됩니다. 가장 중요한 것은 **투명성**입니다. "원인을 모르겠다"고 솔직하게 말하는 것이, 추측으로 잘못된 정보를 전파하는 것보다 낫습니다.

**경험 연결**: 인프라 장애 시 여러 사람이 동시에 다른 채널에서 소통하여 혼란이 가중된 경험이 있습니다. 단일 Incident 채널과 IC 역할 지정이 이 문제를 해결합니다.

**주의**: 고객 커뮤니케이션에서 과도한 기술 용어 사용 금지. "etcd quorum loss"가 아니라 "서비스 접속 장애"로 표현.

### Q: 실제 장애 대응 시나리오를 설명해보세요.
**30초 답변**: 월요일 오전 배포 후 에러율 급증 시나리오입니다. Burn Rate Alert 발생 → On-call 확인 → 최근 배포 확인 → 카나리 분석 실패 확인 → 즉시 롤백 → 에러율 정상화 → 포스트모템 진행의 순서로 대응합니다.

**2분 답변**: 시나리오: "Alli API 추론 에러율 급증". 10:15 배포 완료(ArgoCD), 10:20 Burn Rate Alert 발생(14.4x, 5분 내 에러율 2%). On-call 엔지니어가 5분 내 Acknowledge. Grafana 대시보드에서 에러율이 10:15부터 급증 확인 → 배포와 상관관계 의심. 로그 확인: `ModuleNotFoundError: No module named 'transformers.v4'` → 새 버전에서 라이브러리 호환성 문제. 즉각 조치: `kubectl rollout undo deploy/alli-api` 실행, 3분 내 이전 버전으로 롤백 완료. 10:30 에러율 0.1% 미만으로 복귀, SLI 정상 확인. 전체 MTTD: 5분, MTTR: 15분. 포스트모템: (1) CI에 라이브러리 호환성 테스트 추가, (2) 카나리 배포 비율을 5%로 시작하도록 조정, (3) 자동 롤백 Analysis Template에 라이브러리 import 체크 추가. 이 시나리오에서 핵심은 "배포 직후 문제 → 롤백이 가장 빠른 완화"라는 판단을 빠르게 내린 것입니다.

**경험 연결**: 온프레미스에서도 패치 적용 후 서비스 장애가 발생하면 즉시 롤백하는 것이 원칙이었습니다. 클라우드 환경에서는 `rollout undo`로 수 분 내 롤백이 가능하여 MTTR이 획기적으로 줄어듭니다.

**주의**: 롤백이 항상 답은 아님. 데이터 마이그레이션이 포함된 배포는 롤백이 불가능할 수 있으며, 이 경우 Forward Fix가 필요.

---

## Allganize 맥락

- **JD 연결**: DevOps 엔지니어의 핵심 역량 중 하나가 장애 대응. 면접에서 실제 시나리오 기반 질문이 빈출
- **LLM 서비스 장애 유형**: 모델 로딩 실패, GPU OOM, 추론 타임아웃, 프롬프트 사이즈 초과 등 AI 서비스 고유 장애
- **멀티클라우드 장애**: AWS 리전 장애 시 Azure로 트래픽 전환하는 DR(Disaster Recovery) 전략
- **작은 팀의 Incident 관리**: 3~5명 팀에서는 IC와 Ops를 한 사람이 겸하는 것이 현실적
- **GitOps 롤백**: ArgoCD에서 Git commit revert → 자동 롤백으로 MTTR 최소화

---
**핵심 키워드**: `MTTD` `MTTR` `MTTA` `Incident-Commander` `Severity` `Runbook` `Rollback` `Synthetic-Monitoring` `Game-Day` `Status-Page` `Feature-Flag` `Canary-Analysis`
