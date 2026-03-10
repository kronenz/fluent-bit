# Section 7: Alert 파이프라인 구성 및 점검

## 개요

본 섹션은 PrometheusRule CR 기반 Alert 파이프라인의 구성, Alertmanager 라우팅/억제/그룹핑 설정, k8sAlert 커스텀 프로젝트 연동, 파이프라인 점검 절차, 장애 패턴 및 조치 방법을 다룹니다.

**Alert 파이프라인 흐름:**

```
PrometheusRule CR
      ↓ (ruleSelector 매칭)
  Prometheus
  (룰 평가 / firing 판단)
      ↓ (AlertManager Webhook)
  Alertmanager
  (그룹핑 / 억제 / 라우팅)
      ↓ (webhook_configs)
   k8sAlert
  (수신 / 파싱 / 포맷 변환 / 채널 분기)
      ↓
  Slack / Email / 기타 채널
```

---

## 7.1 PrometheusRule CR 구성

### 7.1.1 PrometheusRule 전체 목록

| CR명 | 그룹명 | 룰 수 | 대상 | 주요 severity |
|------|--------|-------|------|--------------|
| `kubernetes-apps-rules` | `kubernetes-apps` | 12 | Deployment, DaemonSet, StatefulSet, Pod | critical, warning |
| `kubernetes-resources-rules` | `kubernetes-resources` | 8 | CPU, Memory, 네임스페이스 쿼터 | critical, warning |
| `kubernetes-system-rules` | `kubernetes-system` | 6 | kubelet, kube-proxy, CoreDNS | critical, warning |
| `node-rules` | `node` | 14 | 노드 CPU/Memory/Disk/Network, NTP | critical, warning, info |
| `alertmanager-rules` | `alertmanager` | 5 | Alertmanager 자체 상태 | critical, warning |
| `prometheus-rules` | `prometheus` | 8 | Prometheus 자체 상태, TSDB | critical, warning |
| `custom-rules` | `custom` | N | 서비스별 커스텀 룰 | critical, warning, info, none |

### 7.1.2 룰 네이밍 규칙

| 항목 | 규칙 | 예시 |
|------|------|------|
| CR명 | `{대상}-rules` (소문자, 하이픈) | `kubernetes-apps-rules`, `node-rules` |
| 그룹명 | `{대상}` (소문자, 하이픈) | `kubernetes-apps`, `node` |
| Alert 이름 | `{대상}{상태}` (PascalCase) | `KubePodCrashLooping`, `NodeMemoryHigh` |
| 접두사 (Kube) | `Kube` | `KubeDeploymentReplicasMismatch` |
| 접두사 (Node) | `Node` | `NodeDiskPressure` |
| 접두사 (Custom) | 서비스명 PascalCase | `AppDatabaseConnectionHigh` |
| 접미사 (상태) | `High`, `Low`, `Missing`, `Failed`, `NotReady` | `KubePodNotReady` |

### 7.1.3 severity 등급 정의

| severity | 정의 | 대응 시간 | 알림 채널 | 비고 |
|----------|------|-----------|-----------|------|
| `critical` | 서비스 중단 또는 즉각적인 인프라 위협 | 5분 이내 | Slack #critical + Email (온콜 담당) | 24/7 즉시 대응 |
| `warning` | 잠재적 문제, 성능 저하 | 업무 시간 내 | Slack #warning | 업무 시간(09-18시) 대응 |
| `info` | 정보성, 일반 이상 징후 | 다음 점검 시 | Slack #info | 배치 알림 가능 |
| `none` | 내부 계산용, 알림 미발송 | 해당 없음 | 없음 (recording rule 등) | Alertmanager 라우팅 제외 |

### 7.1.4 PrometheusRule CR YAML 예시

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kubernetes-apps-rules
  namespace: monitoring
  labels:
    # Prometheus CR의 ruleSelector와 반드시 일치해야 함
    prometheus: kube-prometheus
    role: alert-rules
spec:
  groups:
    - name: kubernetes-apps
      # 룰 평가 주기 (기본 Prometheus global.evaluation_interval 사용)
      interval: 1m
      rules:
        # recording rule (severity: none 계산용)
        - record: job:kube_pod_container_resource_requests:sum
          expr: |
            sum by (namespace, pod, container) (
              kube_pod_container_resource_requests{resource="cpu"}
            )

        # warning: Pod CrashLoopBackOff
        - alert: KubePodCrashLooping
          expr: |
            max_over_time(kube_pod_container_status_waiting_reason{
              reason="CrashLoopBackOff", job="kube-state-metrics"
            }[5m]) >= 1
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} CrashLoopBackOff"
            description: >
              Pod {{ $labels.namespace }}/{{ $labels.pod }}
              컨테이너 {{ $labels.container }} 이(가) CrashLoopBackOff 상태입니다.
              현재 대기 이유: {{ $value }}
            runbook_url: "https://runbooks.example.com/KubePodCrashLooping"

        # critical: Pod 0개 Running (Deployment 장애)
        - alert: KubeDeploymentReplicasMismatch
          expr: |
            (
              kube_deployment_spec_replicas{job="kube-state-metrics"}
              >
              kube_deployment_status_replicas_available{job="kube-state-metrics"}
            ) and (
              changes(kube_deployment_status_replicas_updated{job="kube-state-metrics"}[10m]) == 0
            )
          for: 15m
          labels:
            severity: critical
          annotations:
            summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} 레플리카 불일치"
            description: >
              Deployment {{ $labels.namespace }}/{{ $labels.deployment }} 의
              가용 레플리카({{ $value }})가 목표 레플리카와 불일치합니다.
            runbook_url: "https://runbooks.example.com/KubeDeploymentReplicasMismatch"

        # warning: 노드 메모리 85% 이상
        - alert: NodeMemoryHigh
          expr: |
            (
              node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes
            ) / node_memory_MemTotal_bytes * 100 > 85
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "노드 {{ $labels.instance }} 메모리 사용률 높음"
            description: >
              노드 {{ $labels.instance }} 메모리 사용률이
              {{ $value | humanizePercentage }} 입니다. (임계값: 85%)

        # critical: 노드 메모리 95% 이상
        - alert: NodeMemoryCritical
          expr: |
            (
              node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes
            ) / node_memory_MemTotal_bytes * 100 > 95
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "노드 {{ $labels.instance }} 메모리 임계 상태"
            description: >
              노드 {{ $labels.instance }} 메모리 사용률이
              {{ $value | humanizePercentage }} 입니다. 즉각 조치 필요.
```

### 7.1.5 GitOps를 통한 CR 변경 관리 절차

| 단계 | 작업 | 담당 | 확인 방법 |
|------|------|------|-----------|
| 1 | PrometheusRule CR YAML 수정 | 개발/운영팀 | 로컬 `promtool check rules <file>.yaml` 검증 |
| 2 | Git commit & push (feature branch) | 개발/운영팀 | `git push origin feature/<alert-name>` |
| 3 | Pull Request 생성 및 리뷰 | 팀 리뷰어 | PR 리뷰 승인 |
| 4 | main 브랜치 merge | 리뷰어 | merge 완료 확인 |
| 5 | ArgoCD 동기화 감지 | ArgoCD | ArgoCD UI/CLI에서 Sync 상태 확인 |
| 6 | ArgoCD Sync 실행 (자동 또는 수동) | ArgoCD | `argocd app sync monitoring` |
| 7 | PrometheusRule CR 클러스터 반영 | Kubernetes | `kubectl get prometheusrule -n monitoring` |
| 8 | Prometheus 룰 리로드 감지 | Prometheus Operator | Prometheus Operator가 CR 변경 감지 후 자동 리로드 |
| 9 | Prometheus 룰 활성화 확인 | 운영팀 | `curl prometheus:9090/api/v1/rules` |

```bash
# YAML 문법 사전 검증 (로컬)
promtool check rules kubernetes-apps-rules.yaml

# 클러스터 반영 확인
kubectl get prometheusrule -n monitoring
kubectl describe prometheusrule kubernetes-apps-rules -n monitoring

# Prometheus API로 룰 반영 확인
curl -s http://prometheus:9090/api/v1/rules | \
  jq '.data.groups[] | select(.name=="kubernetes-apps") | .rules[].name'
```

---

## 7.2 Alertmanager 구성

### 7.2.1 라우팅 트리 구성

| severity | 매칭 조건 | receiver | group_wait | group_interval | repeat_interval |
|----------|-----------|----------|------------|----------------|-----------------|
| `critical` | `severity=critical` | `k8salert-critical` | 10s | 5m | 1h |
| `warning` | `severity=warning` | `k8salert-warning` | 30s | 10m | 4h |
| `info` | `severity=info` | `k8salert-info` | 5m | 30m | 12h |
| 기본 (unmatched) | 그 외 | `k8salert-default` | 5m | 30m | 24h |

### 7.2.2 억제(Inhibit) 규칙 구성

| 억제명 | source (억제 유발) | target (억제 대상) | equal labels | 목적 |
|--------|-------------------|-------------------|--------------|------|
| critical-inhibits-warning | `severity=critical` | `severity=warning` | `alertname`, `namespace` | critical 발생 시 동일 대상의 warning 중복 발송 방지 |
| critical-inhibits-info | `severity=critical` | `severity=info` | `alertname`, `namespace` | critical 발생 시 info 알림 억제 |
| warning-inhibits-info | `severity=warning` | `severity=info` | `alertname`, `namespace` | warning 발생 시 info 알림 억제 |
| node-down-inhibits-pod | `alertname=NodeDown` | `alertname=KubePodNotReady` | `node` | 노드 장애 시 해당 노드 Pod 알람 억제 |

### 7.2.3 그룹핑 정책

| 그룹 범위 | group_by 레이블 | 목적 |
|-----------|----------------|------|
| 전역 기본 | `alertname`, `cluster`, `namespace` | 동일 알람의 다수 발생을 하나의 알림으로 집약 |
| critical 그룹 | `alertname`, `cluster`, `namespace`, `severity` | 긴급 알람 구분 발송 |
| 노드 관련 | `alertname`, `instance`, `node` | 노드별 알람 집약 |
| 워크로드 관련 | `alertname`, `namespace`, `deployment` | 배포 단위 알람 집약 |

### 7.2.4 Alertmanager config YAML 예시

```yaml
# alertmanager.yaml (Secret으로 관리)
global:
  resolve_timeout: 5m
  smtp_smarthost: "smtp.example.com:587"
  smtp_from: "alertmanager@example.com"
  smtp_auth_username: "alertmanager@example.com"
  smtp_auth_password: "<SMTP_PASSWORD>"
  smtp_require_tls: true
  http_config:
    follow_redirects: true

templates:
  - "/etc/alertmanager/templates/*.tmpl"

route:
  # 전역 기본 그룹핑 레이블
  group_by: ["alertname", "cluster", "namespace"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 12h
  receiver: k8salert-default

  routes:
    # critical: 즉시 알림, 짧은 대기
    - matchers:
        - severity = critical
      receiver: k8salert-critical
      group_wait: 10s
      group_interval: 5m
      repeat_interval: 1h
      continue: false

    # warning: 업무 시간대 알림
    - matchers:
        - severity = warning
      receiver: k8salert-warning
      group_wait: 30s
      group_interval: 10m
      repeat_interval: 4h
      # 업무 시간 외 알림 억제 (선택적 적용)
      # active_time_intervals:
      #   - business_hours
      continue: false

    # info: 배치성 알림
    - matchers:
        - severity = info
      receiver: k8salert-info
      group_wait: 5m
      group_interval: 30m
      repeat_interval: 12h
      continue: false

inhibit_rules:
  # critical이 발생하면 동일 namespace의 warning/info 억제
  - source_matchers:
      - severity = critical
    target_matchers:
      - severity = warning
    equal: ["alertname", "namespace"]

  - source_matchers:
      - severity = critical
    target_matchers:
      - severity = info
    equal: ["alertname", "namespace"]

  - source_matchers:
      - severity = warning
    target_matchers:
      - severity = info
    equal: ["alertname", "namespace"]

  # 노드 다운 시 해당 노드 Pod 알람 억제
  - source_matchers:
      - alertname = "NodeDown"
    target_matchers:
      - alertname = "KubePodNotReady"
    equal: ["node"]

receivers:
  - name: k8salert-default
    webhook_configs:
      - url: "http://k8salert.k8salert.svc.cluster.local:8080/webhook"
        send_resolved: true
        http_config:
          bearer_token: "<K8SALERT_TOKEN>"

  - name: k8salert-critical
    webhook_configs:
      - url: "http://k8salert.k8salert.svc.cluster.local:8080/webhook/critical"
        send_resolved: true
        http_config:
          bearer_token: "<K8SALERT_TOKEN>"

  - name: k8salert-warning
    webhook_configs:
      - url: "http://k8salert.k8salert.svc.cluster.local:8080/webhook/warning"
        send_resolved: true
        http_config:
          bearer_token: "<K8SALERT_TOKEN>"

  - name: k8salert-info
    webhook_configs:
      - url: "http://k8salert.k8salert.svc.cluster.local:8080/webhook/info"
        send_resolved: true
        http_config:
          bearer_token: "<K8SALERT_TOKEN>"

time_intervals:
  - name: business_hours
    time_intervals:
      - weekdays: ["monday:friday"]
        times:
          - start_time: "09:00"
            end_time: "18:00"
```

---

## 7.3 k8sAlert 커스텀 프로젝트 구성

### 7.3.1 프로젝트 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Alertmanager                                  │
│  webhook_configs → http://k8salert:8080/webhook/{severity}          │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP POST (Alertmanager webhook payload)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         k8sAlert                                     │
│                                                                      │
│  ┌──────────────────┐    ┌──────────────────┐                       │
│  │  HTTP Receiver   │───▶│  Message Parser  │                       │
│  │  (Gin/Echo)      │    │  (JSON decode,   │                       │
│  │  /webhook        │    │   alert 추출)    │                       │
│  └──────────────────┘    └────────┬─────────┘                       │
│                                   │                                  │
│                          ┌────────▼─────────┐                       │
│                          │ Format Transformer│                       │
│                          │ (Slack/Email      │                       │
│                          │  메시지 포맷 변환)│                       │
│                          └────────┬─────────┘                       │
│                                   │                                  │
│                          ┌────────▼─────────┐                       │
│                          │ Channel Dispatcher│                       │
│                          │ (severity/label   │                       │
│                          │  기반 채널 분기)  │                       │
│                          └──┬──────────┬────┘                       │
└─────────────────────────────┼──────────┼────────────────────────────┘
                              │          │
               ┌──────────────▼──┐  ┌───▼──────────────┐
               │   Slack API     │  │   SMTP (Email)   │
               │  (Webhook URL)  │  │                  │
               └─────────────────┘  └──────────────────┘
```

### 7.3.2 발송 채널 구성

| 채널명 | 발송 방식 | Secret 관리 | 담당자 | 비고 |
|--------|-----------|-------------|--------|------|
| `slack-critical` | Slack Incoming Webhook | `k8salert-secrets` (`slack-critical-webhook-url`) | 온콜 담당자 | #alert-critical 채널, 24/7 |
| `slack-warning` | Slack Incoming Webhook | `k8salert-secrets` (`slack-warning-webhook-url`) | 운영팀 | #alert-warning 채널, 업무시간 |
| `slack-info` | Slack Incoming Webhook | `k8salert-secrets` (`slack-info-webhook-url`) | 운영팀 | #alert-info 채널 |
| `email-critical` | SMTP | `k8salert-secrets` (`smtp-password`) | 팀장, 온콜 | critical 병행 이메일 발송 |
| `email-daily` | SMTP (배치) | `k8salert-secrets` (`smtp-password`) | 운영팀 전체 | 일별 요약 리포트 (선택) |

```yaml
# k8sAlert Secret 구성
apiVersion: v1
kind: Secret
metadata:
  name: k8salert-secrets
  namespace: k8salert
type: Opaque
stringData:
  slack-critical-webhook-url: "https://hooks.slack.com/services/T.../B.../..."
  slack-warning-webhook-url: "https://hooks.slack.com/services/T.../B.../..."
  slack-info-webhook-url: "https://hooks.slack.com/services/T.../B.../..."
  smtp-host: "smtp.example.com:587"
  smtp-username: "alertmanager@example.com"
  smtp-password: "<SMTP_PASSWORD>"
  smtp-from: "k8salert@example.com"
  smtp-to-critical: "oncall@example.com,manager@example.com"
  k8salert-token: "<BEARER_TOKEN_FOR_ALERTMANAGER>"
```

### 7.3.3 Alertmanager → k8sAlert Webhook 연동 설정

```yaml
# Alertmanager Secret (alertmanager-main) 내 webhook 설정 발췌
receivers:
  - name: k8salert-critical
    webhook_configs:
      - url: "http://k8salert.k8salert.svc.cluster.local:8080/webhook/critical"
        send_resolved: true
        max_alerts: 50
        http_config:
          bearer_token_file: /etc/alertmanager/secrets/k8salert-token
          # 또는 직접 지정
          # bearer_token: "<K8SALERT_TOKEN>"
        # Alertmanager가 k8sAlert로 전송하는 페이로드 형식 (Alertmanager webhook v2)
        # {
        #   "version": "4",
        #   "groupKey": "...",
        #   "status": "firing|resolved",
        #   "receiver": "k8salert-critical",
        #   "groupLabels": { "alertname": "...", "namespace": "..." },
        #   "commonLabels": { "severity": "critical", ... },
        #   "commonAnnotations": { "summary": "...", "description": "..." },
        #   "externalURL": "http://alertmanager:9093",
        #   "alerts": [ { "status": "firing", "labels": {...}, "annotations": {...}, ... } ]
        # }
```

### 7.3.4 k8sAlert 컨테이너 이미지 빌드 및 Nexus 배포 절차

| 단계 | 작업 | 명령 예시 |
|------|------|-----------|
| 1 | 소스 코드 변경 후 Git push | `git push origin main` |
| 2 | 로컬 이미지 빌드 | `docker build -t k8salert:v1.2.0 .` |
| 3 | Nexus Registry 태깅 | `docker tag k8salert:v1.2.0 nexus.example.com/k8s/k8salert:v1.2.0` |
| 4 | Nexus 로그인 | `docker login nexus.example.com -u <user> -p <password>` |
| 5 | Nexus Push | `docker push nexus.example.com/k8s/k8salert:v1.2.0` |
| 6 | Kubernetes Deployment 이미지 태그 업데이트 | `kubectl set image deployment/k8salert k8salert=nexus.example.com/k8s/k8salert:v1.2.0 -n k8salert` |
| 7 | 롤아웃 상태 확인 | `kubectl rollout status deployment/k8salert -n k8salert` |
| 8 | 배포 후 헬스 체크 | `curl http://k8salert.k8salert.svc.cluster.local:8080/health` |

```bash
# 빌드 및 배포 스크립트 예시
VERSION="v1.2.0"
REGISTRY="nexus.example.com/k8s"
IMAGE="k8salert"

docker build -t ${IMAGE}:${VERSION} .
docker tag ${IMAGE}:${VERSION} ${REGISTRY}/${IMAGE}:${VERSION}
docker push ${REGISTRY}/${IMAGE}:${VERSION}

kubectl set image deployment/${IMAGE} \
  ${IMAGE}=${REGISTRY}/${IMAGE}:${VERSION} \
  -n k8salert

kubectl rollout status deployment/${IMAGE} -n k8salert --timeout=120s
```

---

## 7.4 Alert 파이프라인 점검

### 7.4.1 점검 항목 표

| # | 항목 | 점검 방법 | 정상 기준 | 결과 |
|---|------|-----------|-----------|------|
| 1 | PrometheusRule CR 등록 확인 | `kubectl get prometheusrule -n monitoring` | 모든 CR 목록 정상 조회 | ☐ |
| 2 | Prometheus 룰 반영 확인 | `curl prometheus:9090/api/v1/rules` | 모든 그룹/룰 LOADED 상태 | ☐ |
| 3 | Prometheus 타겟 스크레이프 상태 | `curl prometheus:9090/api/v1/targets` | 모든 타겟 UP 상태 | ☐ |
| 4 | Alertmanager 설정 로드 확인 | `amtool config show --alertmanager.url=http://alertmanager:9093` | 설정 오류 없음 | ☐ |
| 5 | Alertmanager 라우팅 동작 확인 | `amtool config routes show` | 라우팅 트리 정상 출력 | ☐ |
| 6 | k8sAlert Pod 상태 | `kubectl get pods -n k8salert` | Running, Restarts 0 | ☐ |
| 7 | k8sAlert 헬스 체크 | `curl http://k8salert:8080/health` | HTTP 200 응답 | ☐ |
| 8 | 테스트 Alert 발송 | 임시 PrometheusRule 적용 → 채널 수신 확인 | 전 채널 알림 수신 | ☐ |
| 9 | Alert 억제 동작 확인 | `amtool alert query --alertmanager.url=...` | 억제 규칙 정상 동작 | ☐ |
| 10 | Alert 해소(resolved) 알림 확인 | 임시 룰 제거 후 채널 resolved 수신 확인 | resolved 알림 정상 수신 | ☐ |

### 7.4.2 PrometheusRule CR 등록 및 반영 확인

```bash
# PrometheusRule CR 목록 확인
kubectl get prometheusrule -n monitoring

# 예상 출력:
# NAME                       AGE
# kubernetes-apps-rules      5d
# kubernetes-resources-rules 5d
# kubernetes-system-rules    5d
# node-rules                 5d
# alertmanager-rules         5d
# prometheus-rules           5d
# custom-rules               2d

# Prometheus API로 룰 반영 확인
curl -s http://prometheus:9090/api/v1/rules | \
  jq '.data.groups[] | {group: .name, rules: [.rules[].name]}'

# 특정 그룹 룰 상세 확인
curl -s http://prometheus:9090/api/v1/rules | \
  jq '.data.groups[] | select(.name=="kubernetes-apps")'

# 현재 Firing 중인 Alert 확인
curl -s http://prometheus:9090/api/v1/alerts | \
  jq '.data.alerts[] | {alert: .labels.alertname, severity: .labels.severity, state: .state}'
```

### 7.4.3 Alertmanager 라우팅 동작 확인

```bash
# Alertmanager 설정 전체 확인
amtool config show --alertmanager.url=http://alertmanager:9093

# 라우팅 트리 확인
amtool config routes show --alertmanager.url=http://alertmanager:9093

# 특정 레이블에 대한 라우팅 경로 테스트
amtool config routes test \
  --alertmanager.url=http://alertmanager:9093 \
  severity=critical alertname=KubePodCrashLooping namespace=production

# 현재 활성 Alert 목록
amtool alert query --alertmanager.url=http://alertmanager:9093

# 현재 활성 Silence 목록
amtool silence query --alertmanager.url=http://alertmanager:9093
```

### 7.4.4 테스트 Alert 발송 절차

#### 1단계: 임시 PrometheusRule 적용 (항상 firing 테스트 룰)

```yaml
# test-alert-rule.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: test-alert-rule
  namespace: monitoring
  labels:
    prometheus: kube-prometheus
    role: alert-rules
spec:
  groups:
    - name: test
      rules:
        - alert: TestAlertCritical
          # 항상 1을 반환하므로 즉시 firing
          expr: vector(1)
          for: 0m
          labels:
            severity: critical
            alertname: TestAlertCritical
          annotations:
            summary: "테스트 Critical Alert"
            description: "Alert 파이프라인 점검용 임시 테스트 룰입니다. 확인 후 즉시 삭제하세요."

        - alert: TestAlertWarning
          expr: vector(1)
          for: 0m
          labels:
            severity: warning
          annotations:
            summary: "테스트 Warning Alert"
            description: "Alert 파이프라인 점검용 임시 테스트 룰입니다."
```

```bash
# 테스트 룰 적용
kubectl apply -f test-alert-rule.yaml

# 반영 확인 (약 30초 ~ 1분 소요)
watch -n 5 'curl -s http://prometheus:9090/api/v1/alerts | \
  jq ".data.alerts[] | select(.labels.alertname==\"TestAlertCritical\")"'
```

#### 2단계: Alertmanager 수신 확인

```bash
# Alertmanager에서 활성 Alert 확인
curl -s http://alertmanager:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname | startswith("TestAlert")) |
    {alert: .labels.alertname, status: .status.state, receiver: .receivers}'

# 또는 amtool 사용
amtool alert query alertname=~TestAlert.* \
  --alertmanager.url=http://alertmanager:9093
```

#### 3단계: k8sAlert Webhook 전달 확인

```bash
# k8sAlert 수신 로그 확인
kubectl logs -n k8salert deployment/k8salert --tail=50 | \
  grep -E "TestAlert|webhook|dispatch|error"

# k8sAlert 헬스 및 통계 (구현에 따라 다름)
curl -s http://k8salert.k8salert.svc.cluster.local:8080/metrics
```

#### 4단계: 수신 채널별 알림 수신 확인 표

| 채널 | 테스트 Alert명 | 예상 수신 채널 | 테스트 결과 | 담당자 확인 |
|------|--------------|--------------|------------|------------|
| Slack #alert-critical | `TestAlertCritical` | #alert-critical | ☐ 수신 / ☐ 미수신 | 담당자: |
| Slack #alert-warning | `TestAlertWarning` | #alert-warning | ☐ 수신 / ☐ 미수신 | 담당자: |
| Email (oncall) | `TestAlertCritical` | oncall@example.com | ☐ 수신 / ☐ 미수신 | 담당자: |
| resolved 알림 | (룰 삭제 후) | 각 채널 | ☐ 수신 / ☐ 미수신 | 담당자: |

```bash
# 테스트 완료 후 임시 룰 즉시 삭제
kubectl delete -f test-alert-rule.yaml

# 삭제 후 Alertmanager에서 resolved 처리 확인 (5분 이내)
curl -s http://alertmanager:9093/api/v2/alerts | \
  jq '.[] | select(.labels.alertname | startswith("TestAlert"))'
# 빈 배열 [] 반환 시 정상 해소
```

### 7.4.5 Alert 억제/그룹핑 동작 확인

```bash
# 억제 규칙 동작 테스트
# critical이 firing 상태일 때 동일 namespace의 warning이 억제되는지 확인

# 1. critical + warning 동시 firing 테스트 룰 적용
cat <<EOF | kubectl apply -f -
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: test-inhibit-rule
  namespace: monitoring
  labels:
    prometheus: kube-prometheus
    role: alert-rules
spec:
  groups:
    - name: test-inhibit
      rules:
        - alert: TestInhibitSource
          expr: vector(1)
          for: 0m
          labels:
            severity: critical
            namespace: test-ns
        - alert: TestInhibitTarget
          expr: vector(1)
          for: 0m
          labels:
            severity: warning
            namespace: test-ns
            alertname: TestInhibitSource
EOF

# 2. Alertmanager에서 warning이 억제되었는지 확인
# inhibited=true 인 alert는 발송되지 않음
curl -s "http://alertmanager:9093/api/v2/alerts?active=true&inhibited=true" | \
  jq '.[] | select(.labels.alertname=="TestInhibitTarget") | .status'

# 3. 그룹핑 동작 확인 - 같은 그룹의 알람이 하나의 메시지로 묶이는지 확인
curl -s http://alertmanager:9093/api/v2/alerts/groups | jq '.'

# 4. 테스트 룰 정리
kubectl delete prometheusrule test-inhibit-rule -n monitoring
```

---

## 7.5 Alert 파이프라인 장애 패턴 및 조치

| # | 증상 | 원인 | 확인 명령 | 조치 방법 |
|---|------|------|-----------|-----------|
| 1 | PrometheusRule 미반영 (Prometheus 룰 목록에 없음) | `ruleSelector` 레이블 불일치, YAML 문법 오류, Prometheus Operator 이슈 | `kubectl describe prometheusrule <name> -n monitoring` / `kubectl logs -n monitoring deployment/prometheus-operator` | PrometheusRule CR의 `labels` 확인 (Prometheus CR의 `ruleSelector.matchLabels`와 일치 여부), `promtool check rules` 로 문법 사전 검증, Prometheus Operator 재시작 |
| 2 | Alertmanager → k8sAlert Webhook 실패 | 네트워크 정책, 타임아웃, 잘못된 webhook URL, 인증 토큰 오류 | `kubectl logs -n monitoring alertmanager-main-0 \| grep -E "error\|webhook\|dispatch"` / `curl -v http://k8salert:8080/webhook` | NetworkPolicy 허용 여부 확인, webhook URL 및 포트 재확인, Bearer token Secret 내용 확인, k8sAlert Pod 상태 확인 및 재시작 |
| 3 | 채널 발송 실패 (Slack) | Slack Webhook URL 만료 또는 잘못됨, 네트워크 외부 통신 차단 | `kubectl logs -n k8salert deployment/k8salert \| grep -E "slack\|error\|4[0-9]{2}"` | Slack App Webhook URL 재발급 후 Secret 업데이트, 클러스터 외부 통신 허용 여부 확인 (Egress 정책), curl로 Slack Webhook 직접 테스트 |
| 4 | 채널 발송 실패 (Email) | SMTP 인증 실패, 포트 차단 (25/465/587), TLS 오류 | `kubectl logs -n k8salert deployment/k8salert \| grep -E "smtp\|email\|error"` | SMTP 자격증명 Secret 재확인, 포트 587 Egress NetworkPolicy 확인, `telnet smtp.example.com 587` 연결 테스트 |
| 5 | Alert storm (다수 알람 폭주, 채널 스팸) | 그룹핑 미흡, 억제 규칙 미설정, 일시적 인프라 이상 | Alertmanager UI 확인, 발송 채널 수신량 확인 | `group_interval` 및 `repeat_interval` 증가, 억제 규칙 추가 (critical → warning), Silence 임시 적용: `amtool silence add --duration=1h alertname=~<pattern>`, 근본 원인(인프라 이상) 해소 |
| 6 | Alertmanager CrashLoop | alertmanager.yaml 설정 오류 (YAML 문법, 잘못된 receiver) | `kubectl describe pod alertmanager-main-0 -n monitoring` / `kubectl logs alertmanager-main-0 -n monitoring` | `amtool check-config alertmanager.yaml` 로 설정 검증, 이전 버전 Secret으로 롤백: `kubectl rollout undo statefulset/alertmanager-main -n monitoring`, 설정 수정 후 재적용 |

### 7.5.1 Alert Storm 긴급 대응 절차

```bash
# 1. 특정 패턴의 알람 임시 Silence 적용 (1시간)
amtool silence add \
  --alertmanager.url=http://alertmanager:9093 \
  --duration=1h \
  --comment="Alert storm 긴급 억제 - 원인 조사 중" \
  alertname=~"KubePod.*"

# 2. 전체 Silence 목록 확인
amtool silence query --alertmanager.url=http://alertmanager:9093

# 3. Silence 해제 (ID로)
amtool silence expire --alertmanager.url=http://alertmanager:9093 <silence-id>
```

### 7.5.2 Alertmanager 설정 긴급 롤백

```bash
# 현재 Alertmanager Secret 백업
kubectl get secret alertmanager-main -n monitoring -o yaml > alertmanager-secret-backup.yaml

# 이전 설정 확인 (git history 또는 백업)
# git log --oneline -- alertmanager.yaml
# git show <commit>:alertmanager.yaml

# 설정 검증 후 재적용
amtool check-config alertmanager-new.yaml

# Secret 업데이트 (base64 인코딩)
kubectl create secret generic alertmanager-main \
  --from-file=alertmanager.yaml=alertmanager-new.yaml \
  --namespace=monitoring \
  --dry-run=client -o yaml | kubectl apply -f -

# Alertmanager 설정 리로드 (SIGHUP)
kubectl exec -n monitoring alertmanager-main-0 -- \
  wget -q --post-data='' http://localhost:9093/-/reload -O -
```

### 7.5.3 PrometheusRule ruleSelector 확인 절차

```bash
# Prometheus CR에서 ruleSelector 확인
kubectl get prometheus -n monitoring -o jsonpath='{.items[0].spec.ruleSelector}' | jq '.'
# 예상 출력: {"matchLabels": {"prometheus": "kube-prometheus", "role": "alert-rules"}}

# PrometheusRule CR의 레이블 확인
kubectl get prometheusrule -n monitoring --show-labels

# 레이블 불일치 시 수정
kubectl label prometheusrule <name> -n monitoring \
  prometheus=kube-prometheus \
  role=alert-rules

# 수정 후 Prometheus 룰 반영 확인 (약 30초 ~ 1분 소요)
watch -n 10 'curl -s http://prometheus:9090/api/v1/rules | \
  jq ".data.groups | length"'
```
