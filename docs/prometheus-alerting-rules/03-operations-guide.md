# Prometheus Alert 운영 전략 가이드

> Production 환경에서의 Alert 관리, Severity 체계, 대응 프로세스, 튜닝 가이드

---

## 목차

- [1. Severity 체계 설계](#1-severity-체계-설계)
- [2. Alert Routing 전략](#2-alert-routing-전략)
- [3. On-Call 대응 프로세스](#3-on-call-대응-프로세스)
- [4. Alert 튜닝 가이드](#4-alert-튜닝-가이드)
- [5. 자주 발생하는 Alert Top 10 대응 매뉴얼](#5-자주-발생하는-alert-top-10-대응-매뉴얼)
- [6. Silence / Inhibition 정책](#6-silence--inhibition-정책)
- [7. Managed Kubernetes 환경 고려사항](#7-managed-kubernetes-환경-고려사항)
- [8. Alert 성숙도 모델](#8-alert-성숙도-모델)
- [9. 정기 점검 체크리스트](#9-정기-점검-체크리스트)

---

## 1. Severity 체계 설계

### 4단계 Severity 정의

```
┌──────────┬────────────────────┬──────────────┬─────────────────────┐
│ Severity │ 정의               │ 대응 시간     │ 알림 채널            │
├──────────┼────────────────────┼──────────────┼─────────────────────┤
│ critical │ 서비스 장애 중      │ 5분 이내     │ PagerDuty + 전화     │
│ warning  │ 장애 가능성 높음    │ 업무 시간 내  │ Slack #alerts-warn  │
│ info     │ 인지 필요           │ 다음 점검 시  │ Slack #alerts-info  │
│ none     │ 시스템 내부용       │ -            │ 알림 없음            │
└──────────┴────────────────────┴──────────────┴─────────────────────┘
```

### Severity 판단 기준

| 질문 | Yes → 상향 | No → 유지/하향 |
|------|-----------|---------------|
| 사용자가 현재 영향을 받고 있는가? | critical | warning 이하 |
| 1시간 이내 장애로 전이될 수 있는가? | warning | info |
| 자동 복구(self-healing)가 기대되는가? | info | warning |
| 즉각적인 인적 개입 없이는 해결 불가한가? | critical | warning |

### 팀별 Severity 커스터마이징 예시

```yaml
# values.yaml - defaultRules.additionalRuleLabels
defaultRules:
  additionalRuleLabels:
    team: platform
    environment: production

# 개별 alert severity 오버라이드
defaultRules:
  additionalRuleGroupLabels:
    kubernetes-apps:
      team: app-team
  # CPUThrottlingHigh를 info → warning으로 상향
  disabled:
    CPUThrottlingHigh: true  # 기본 비활성화 후 커스텀으로 재정의
```

---

## 2. Alert Routing 전략

### Alertmanager 라우팅 아키텍처

```
                         ┌─────────────────────┐
                         │    Alertmanager      │
                         │    (HA Cluster)      │
                         └──────┬──────────────┘
                                │
          ┌─────────────────────┼──────────────────────┐
          │                     │                      │
   ┌──────▼──────┐    ┌────────▼────────┐    ┌────────▼────────┐
   │  critical    │    │   warning       │    │    info         │
   │              │    │                 │    │                 │
   │ PagerDuty   │    │ Slack           │    │ Slack           │
   │ + Slack      │    │ #alerts-warn    │    │ #alerts-info    │
   │ #alerts-crit │    │                 │    │ (low noise)     │
   └──────────────┘    └─────────────────┘    └─────────────────┘
```

### Alertmanager 설정 예시

```yaml
alertmanager:
  config:
    global:
      resolve_timeout: 5m
      slack_api_url: "https://hooks.slack.com/services/xxx"

    # Inhibition: critical이 firing이면 같은 alertname의 warning 억제
    inhibit_rules:
      - source_matchers:
          - severity = critical
        target_matchers:
          - severity = warning
        equal: ['alertname', 'namespace']

      - source_matchers:
          - severity = warning
        target_matchers:
          - severity = info
        equal: ['alertname', 'namespace']

    route:
      receiver: 'default-slack'
      group_by: ['alertname', 'namespace', 'job']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h

      routes:
        # Critical → PagerDuty + Slack
        - receiver: 'pagerduty-critical'
          matchers:
            - severity = critical
          repeat_interval: 1h
          continue: true  # Slack에도 전송

        - receiver: 'slack-critical'
          matchers:
            - severity = critical
          repeat_interval: 1h

        # Warning → Slack warning 채널
        - receiver: 'slack-warning'
          matchers:
            - severity = warning
          repeat_interval: 4h

        # Info → Slack info 채널 (8시간 반복)
        - receiver: 'slack-info'
          matchers:
            - severity = info
          repeat_interval: 8h

        # Watchdog → Heartbeat 전용
        - receiver: 'heartbeat'
          matchers:
            - alertname = Watchdog
          repeat_interval: 1m
          group_wait: 0s

    receivers:
      - name: 'default-slack'
        slack_configs:
          - channel: '#alerts-default'

      - name: 'pagerduty-critical'
        pagerduty_configs:
          - service_key: '<PD_SERVICE_KEY>'

      - name: 'slack-critical'
        slack_configs:
          - channel: '#alerts-critical'
            color: '#FF0000'

      - name: 'slack-warning'
        slack_configs:
          - channel: '#alerts-warning'
            color: '#FFA500'

      - name: 'slack-info'
        slack_configs:
          - channel: '#alerts-info'
            color: '#36A64F'

      - name: 'heartbeat'
        webhook_configs:
          - url: 'https://heartbeat.pagerduty.com/xxx'
```

---

## 3. On-Call 대응 프로세스

### Critical Alert 대응 플로우

```
Alert 수신 (PagerDuty)
    │
    ▼
1. ACK (5분 이내)
    │
    ▼
2. 초기 진단 (15분)
    ├── kubectl get pods -A | grep -v Running
    ├── kubectl get nodes
    ├── kubectl top nodes
    └── Grafana 대시보드 확인
    │
    ▼
3. 영향 범위 파악
    ├── 사용자 영향 여부 확인
    ├── 관련 서비스 목록 확인
    └── 필요 시 Incident 선언
    │
    ▼
4. 조치
    ├── 긴급 조치 (롤백, 스케일아웃, 노드 교체)
    └── 근본 원인 분석은 Incident 종료 후
    │
    ▼
5. 해결 확인
    ├── Alert resolved 확인
    ├── 관련 메트릭 정상화 확인
    └── Postmortem 문서 작성
```

### 핵심 진단 명령어

```bash
# 클러스터 전체 상태 빠른 확인
kubectl get nodes -o wide
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl top nodes
kubectl top pods -A --sort-by=memory | head -20

# 특정 노드 문제 진단
kubectl describe node <NODE_NAME>
kubectl get events --sort-by=.metadata.creationTimestamp -A | tail -30

# 특정 Pod 문제 진단
kubectl describe pod <POD> -n <NS>
kubectl logs <POD> -n <NS> --previous  # OOMKilled 등으로 이전 컨테이너 로그
kubectl logs <POD> -n <NS> --tail=100

# PV/PVC 상태 확인
kubectl get pv,pvc -A
kubectl describe pvc <PVC_NAME> -n <NS>

# 인증서 상태 확인 (cert-manager)
kubectl get certificates -A
kubectl describe certificate <CERT_NAME> -n <NS>

# CoreDNS 상태 확인
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
```

---

## 4. Alert 튜닝 가이드

### Alert Fatigue 방지 원칙

1. **Actionable**: 수신자가 즉시 취할 수 있는 행동이 있는 alert만 유지
2. **Relevant**: 대상 팀이 해결할 수 있는 alert만 라우팅
3. **Unique**: 같은 문제에 대해 중복 alert 제거
4. **Timely**: `for` 기간을 적절히 설정하여 일시적 스파이크에 반응하지 않도록

### 흔한 False Positive와 튜닝 방법

| Alert | 흔한 False Positive 원인 | 튜닝 방법 |
|-------|--------------------------|-----------|
| `CPUThrottlingHigh` | CPU limit이 너무 보수적 | 임계값 25% → 50%로 조정 또는 CPU limit 제거 |
| `KubePodNotReady` | 롤링 업데이트 중 일시적 발생 | namespace/label 필터로 CI/CD 네임스페이스 제외 |
| `KubeDeploymentReplicasMismatch` | HPA 스케일링 중 일시적 발생 | `for` 기간 15m → 30m으로 연장 |
| `TargetDown` | 배포 중 Pod 교체 | 임계값 10% → 30% 조정 또는 Job 필터 |
| `KubeHpaMaxedOut` | 피크 타임 정상 동작 | 업무 시간 외 silence 적용 또는 `for` 연장 |
| `NodeFilesystemSpaceFillingUp` | tmpfs, emptyDir의 일시적 사용 | 마운트 포인트 필터 (`mountpoint!~"/run/.*"`) |
| `KubeControllerManagerDown` | managed K8s에서 메트릭 미노출 | `disabled.KubeControllerManagerDown: true` |

### 커스텀 임계값 오버라이드

```yaml
# values.yaml
defaultRules:
  # 개별 alert 비활성화
  disabled:
    CPUThrottlingHigh: true
    KubeProxyDown: true  # EKS/GKE에서 미노출

# 커스텀 임계값으로 재정의
additionalPrometheusRulesMap:
  custom-overrides:
    groups:
      - name: custom-overrides
        rules:
          # CPUThrottlingHigh를 50% 임계값으로 재정의
          - alert: CPUThrottlingHigh
            expr: |
              sum(increase(container_cpu_cfs_throttled_periods_total[5m])) by (namespace, pod, container)
              /
              sum(increase(container_cpu_cfs_periods_total[5m])) by (namespace, pod, container)
              > 0.5
            for: 15m
            labels:
              severity: warning
            annotations:
              summary: "컨테이너 CPU Throttling 50% 초과"
```

---

## 5. 자주 발생하는 Alert Top 10 대응 매뉴얼

### 1. KubePodCrashLooping

```
원인 분석:
  1. 애플리케이션 코드 오류 → kubectl logs <pod> --previous
  2. 리소스 부족 (OOMKilled) → kubectl describe pod → 마지막 상태 확인
  3. 설정 오류 (ConfigMap/Secret) → 환경변수, 마운트 확인
  4. 의존 서비스 미기동 → initContainer/readiness probe 확인
  5. liveness probe 설정 과도 → 임계값/주기 완화

조치:
  - OOMKilled: memory limits 상향
  - 코드 오류: 이전 버전으로 롤백 (kubectl rollout undo)
  - 설정 오류: ConfigMap/Secret 수정 후 Pod 재시작
```

### 2. KubePersistentVolumeFillingUp

```
원인 분석:
  1. 로그 파일 과도 축적
  2. DB 데이터 자연 증가
  3. 임시 파일 미정리
  4. 백업 파일 로컬 저장

조치:
  - 긴급: 불필요 파일 삭제 (kubectl exec로 접근)
  - 중기: PVC 용량 확장 (StorageClass allowVolumeExpansion: true)
  - 장기: 로그 로테이션 설정, 데이터 보존 정책 수립
```

### 3. KubeNodeNotReady

```
원인 분석:
  1. kubelet 프로세스 중단
  2. 노드 리소스 고갈 (메모리, 디스크)
  3. 네트워크 단절
  4. 커널 패닉 / 하드웨어 장애

조치:
  - kubectl describe node → Conditions 확인
  - ssh로 노드 접근하여 systemctl status kubelet
  - 노드 복구 불가 시: kubectl drain → 노드 교체
```

### 4. NodeFilesystemAlmostOutOfSpace

```
원인 분석:
  1. /var/lib/containerd 또는 /var/lib/docker 이미지 캐시 과다
  2. /var/log 로그 파일 축적
  3. /tmp 임시 파일 미정리
  4. 사용하지 않는 컨테이너 이미지

조치:
  - crictl rmi --prune (미사용 이미지 정리)
  - journalctl --vacuum-size=500M (systemd 로그 정리)
  - logrotate 설정 확인
  - kubelet GC 설정 확인 (imageGCHighThresholdPercent)
```

### 5. NodeMemoryHighUtilization

```
원인 분석:
  1. Pod memory request/limit 미설정으로 노드 리소스 독점
  2. 메모리 리크가 있는 애플리케이션
  3. 노드에 Pod가 과도하게 배치

조치:
  - kubectl top pods --sort-by=memory 로 상위 Pod 확인
  - Pod eviction 전에 워크로드 이동 검토
  - LimitRange 설정으로 기본 메모리 제한 강제
```

### 6. etcdDatabaseQuotaLowSpace

```
원인 분석:
  1. 대규모 오브젝트(ConfigMap, Secret) 증가
  2. 히스토리 compaction 미수행
  3. Watch 이벤트 누적

조치:
  - etcdctl endpoint status (현재 DB 크기 확인)
  - etcdctl defrag (디프래그먼테이션)
  - etcdctl compact (히스토리 정리)
  - etcd quota 상향 검토 (--quota-backend-bytes)
```

### 7. KubeDeploymentRolloutStuck

```
원인 분석:
  1. 이미지 Pull 실패 (잘못된 태그, 인증 실패)
  2. Readiness Probe 실패
  3. 리소스 부족으로 스케줄링 불가
  4. PDB 제약으로 업데이트 불가

조치:
  - kubectl rollout status deployment/<name>
  - kubectl describe pod (Events 섹션 확인)
  - 필요 시 kubectl rollout undo deployment/<name>
```

### 8. KubeHpaMaxedOut

```
원인 분석:
  1. 트래픽 급증
  2. HPA maxReplicas 설정이 부족
  3. 개별 Pod 성능 저하로 더 많은 Pod 필요
  4. 메트릭 수집 지연으로 스케일링 늦음

조치:
  - 트래픽 패턴 분석 (정상 피크 vs 이상 트래픽)
  - maxReplicas 상향 검토
  - Pod 자체의 성능 최적화
  - HPA behavior 튜닝 (scaleUp/scaleDown 정책)
```

### 9. PrometheusBadConfig

```
원인 분석:
  1. PrometheusRule YAML 문법 오류
  2. 잘못된 PromQL 표현식
  3. 중복된 rule name

조치:
  - promtool check rules <file> 로 문법 검증
  - Prometheus UI → Status → Configuration 에서 에러 확인
  - 최근 변경된 PrometheusRule 리소스 확인
```

### 10. KubeClientCertificateExpiration

```
원인 분석:
  1. 자동 인증서 갱신(rotation) 미설정
  2. kubeadm 클러스터의 인증서 1년 만료
  3. 인증서 갱신 프로세스 실패

조치:
  - kubeadm certs check-expiration (만료 상태 확인)
  - kubeadm certs renew all (수동 갱신)
  - kubelet 인증서 자동 갱신 설정 확인
    (--rotate-certificates, --rotate-server-certificates)
```

---

## 6. Silence / Inhibition 정책

### Silence 사용 기준

| 상황 | Silence 허용 | 기간 |
|------|-------------|------|
| 계획된 유지보수 (노드 패치) | O | 유지보수 윈도우 + 30분 |
| 알려진 이슈 처리 중 | O | 최대 24시간, 연장 시 리뷰 |
| Alert 튜닝 전까지 임시 | O | 최대 7일, 티켓 연동 필수 |
| 원인 불명으로 귀찮아서 | X | - |
| 항상 firing이라 무시 | X | 근본 원인 해결 또는 Rule 비활성화 |

### Silence 운영 규칙

1. **모든 Silence에는 사유와 담당자를 기록**
2. **Silence 기간은 최소로 설정** (자동 만료 필수)
3. **주간 Silence 리뷰 수행** — 불필요한 Silence 정리
4. **Watchdog alert는 절대 Silence 금지**

### Inhibition 활용

```yaml
# 동일 alertname에 대해 critical이 firing이면 warning 억제
inhibit_rules:
  - source_matchers: [severity = critical]
    target_matchers: [severity = warning]
    equal: [alertname, namespace]

  # 노드 다운 시 해당 노드의 모든 Pod alert 억제
  - source_matchers: [alertname = KubeNodeNotReady]
    target_matchers: [severity =~ "warning|info"]
    equal: [node]
```

---

## 7. Managed Kubernetes 환경 고려사항

### EKS / GKE / AKS 공통

Managed Kubernetes에서는 컨트롤 플레인(etcd, apiserver, controller-manager, scheduler)이 클라우드 프로바이더에 의해 관리됩니다. 이에 따라 일부 Rule을 조정해야 합니다.

### 비활성화 권장 Rule

```yaml
defaultRules:
  disabled:
    # 컨트롤 플레인 메트릭이 노출되지 않는 경우
    etcd: false                          # etcd 전체 비활성화
    KubeControllerManagerDown: true
    KubeSchedulerDown: true
    KubeProxyDown: true                  # EKS VPC CNI에서는 불필요

    # 아래는 환경에 따라 선택적
    KubeAPIDown: false                   # managed에서도 apiserver 모니터링은 가능한 경우 유지
```

### 클라우드 프로바이더별 참고

| 프로바이더 | etcd 모니터링 | apiserver 메트릭 | 컨트롤 플레인 alert |
|-----------|-------------|------------------|-------------------|
| **EKS** | X (미노출) | O (제한적) | 대부분 비활성화 |
| **GKE** | X (미노출) | O | 대부분 비활성화 |
| **AKS** | X (미노출) | O | 대부분 비활성화 |
| **자체 관리 (kubeadm)** | O | O | 전체 활성화 |
| **Rancher/RKE2** | O | O | 전체 활성화 |

---

## 8. Alert 성숙도 모델

조직의 Alert 운영 성숙도를 단계별로 향상시키세요.

### Level 1: 기본 (Reactive)

- [x] kube-prometheus-stack 기본 Rule 활성화
- [x] Slack으로 모든 alert 수신
- [x] 수동 대응

### Level 2: 구조화 (Structured)

- [x] Severity별 라우팅 분리 (critical → PagerDuty)
- [x] Inhibition Rule 적용
- [x] Runbook URL 연동
- [x] 추가 Rule 적용 (CoreDNS, cert-manager, Ingress)

### Level 3: 최적화 (Optimized)

- [x] False Positive 비율 < 5%
- [x] Alert → Incident → Postmortem 프로세스 정립
- [x] SLO 기반 Alerting (Error Budget Burn Rate)
- [x] 주간 Alert 품질 리뷰

### Level 4: 자동화 (Automated)

- [x] Auto-remediation (자동 복구) 연동
- [x] Alert 기반 자동 스케일링
- [x] ChatOps 통합 (Slack에서 직접 조치)
- [x] Alert 메트릭 기반 대시보드 (MTTA, MTTR 추적)

---

## 9. 정기 점검 체크리스트

### 일간 점검

- [ ] Alertmanager UI에서 현재 firing alert 확인
- [ ] Silence 목록 검토 (불필요한 silence 해제)
- [ ] Watchdog alert가 정상 firing 상태인지 확인

### 주간 점검

- [ ] 지난 7일간 발생한 alert 요약 리뷰
- [ ] 반복 발생 alert 패턴 분석 및 튜닝 계획
- [ ] False Positive alert 목록 정리 및 임계값 조정
- [ ] 신규 배포된 서비스의 alert 커버리지 확인
- [ ] Prometheus TSDB 용량 및 성능 확인

### 월간 점검

- [ ] Alert Rule 전체 리뷰 (불필요한 Rule 비활성화)
- [ ] Runbook 최신화 상태 확인
- [ ] Notification 채널 동작 테스트
- [ ] On-Call 로테이션 및 에스컬레이션 정책 리뷰
- [ ] Prometheus/Alertmanager 버전 업데이트 검토

### 분기별 점검

- [ ] Alert 성숙도 모델 기준 현재 레벨 자가 진단
- [ ] SLO/SLI 정의 및 Error Budget 정책 리뷰
- [ ] DR(재해 복구) 시나리오 테스트 (Velero 백업 복구 등)
- [ ] 팀 간 Alert 책임 매트릭스(RACI) 업데이트
- [ ] 지난 분기 Incident Postmortem 회고

---

## 부록: 유용한 PromQL 진단 쿼리

```promql
# 현재 Firing 중인 Alert 목록
ALERTS{alertstate="firing"}

# 지난 24시간 가장 많이 발생한 Alert Top 10
topk(10, sum by (alertname)(increase(ALERTS_FOR_STATE[24h])))

# Prometheus 자체 메모리 사용량
process_resident_memory_bytes{job="prometheus"}

# Prometheus Rule 평가 지연
prometheus_rule_group_last_duration_seconds

# 스크랩 실패 타겟 목록
up == 0

# Alertmanager 알림 전송 성공률
rate(alertmanager_notifications_total{integration="slack"}[5m])
-
rate(alertmanager_notifications_failed_total{integration="slack"}[5m])
```

---

## 참고 자료

- [Google SRE Book - Alerting](https://sre.google/sre-book/monitoring-distributed-systems/)
- [Prometheus Alerting Best Practices](https://prometheus.io/docs/practices/alerting/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Kubernetes Monitoring Best Practices](https://trilio.io/kubernetes-best-practices/kubernetes-monitoring-best-practices/)
- [Alibaba Cloud - Prometheus Alert Rule Best Practices](https://www.alibabacloud.com/help/en/ack/ack-managed-and-ack-dedicated/user-guide/best-practices-for-configuring-alert-rules-in-prometheus)
