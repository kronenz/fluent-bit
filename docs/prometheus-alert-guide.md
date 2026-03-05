# PrometheusRule 알람 설정 가이드

> 이 가이드는 **Kubernetes 빅데이터 플랫폼의 각 서비스팀**이 PrometheusRule Custom Resource를 통해
> 자체적으로 알람을 설정하고 배포할 수 있도록 작성되었습니다.
> 복사-붙여넣기와 값 수정만으로 알람을 설정할 수 있습니다.

---

## 한 줄 요약

여러분의 팀이 **PrometheusRule YAML을 작성해서 Git에 Push하면**, ArgoCD가 자동으로 배포하고 Alertmanager가 알람을 발송합니다.

```
서비스팀이 PrometheusRule YAML 작성
         ↓ (Git Push)
ArgoCD가 변경 감지 → 클러스터에 자동 배포
         ↓ (자동)
Prometheus가 Rule 로딩 → 조건 충족 시 Alert 발생
         ↓ (자동)
Alertmanager가 라우팅 → Slack / Email / PagerDuty 등으로 알람 수신
```

---

## 목차

1. [알람 파이프라인 아키텍처](#1-알람-파이프라인-아키텍처)
2. [PrometheusRule CR 이해하기](#2-prometheusrule-cr-이해하기)
3. [필수 라벨 규칙](#3-필수-라벨-규칙)
4. [PrometheusRule YAML 템플릿](#4-prometheusrule-yaml-템플릿)
5. [실전 알람 예시](#5-실전-알람-예시)
6. [Kustomize를 이용한 구성 관리](#6-kustomize를-이용한-구성-관리)
7. [ArgoCD Application 배포 설정](#7-argocd-application-배포-설정)
8. [디렉토리 구조 및 Git 워크플로우](#8-디렉토리-구조-및-git-워크플로우)
9. [배포 및 검증 방법](#9-배포-및-검증-방법)
10. [PromQL 기본 문법](#10-promql-기본-문법)
11. [자주 묻는 질문 (FAQ)](#11-자주-묻는-질문-faq)
12. [체크리스트](#12-체크리스트)

---

## 1. 알람 파이프라인 아키텍처

### 전체 흐름

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                               │
│                                                                         │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────────────┐  │
│  │  Application  │───▶│    Prometheus     │───▶│    Alertmanager       │  │
│  │  (metrics)    │    │  (rule 평가)      │    │  (라우팅 & 발송)      │  │
│  └──────────────┘    └──────────────────┘    └───────────┬───────────┘  │
│                             ▲                             │              │
│                             │                             │              │
│                    ┌────────┴─────────┐                   │              │
│                    │  PrometheusRule   │                   │              │
│                    │  (Custom Resource)│                   │              │
│                    └──────────────────┘                   │              │
│                             ▲                             │              │
└─────────────────────────────┼─────────────────────────────┼──────────────┘
                              │                             │
                     ┌────────┴─────────┐          ┌───────▼──────────┐
                     │  ArgoCD          │          │  Slack / Email   │
                     │  (GitOps 배포)   │          │  PagerDuty 등    │
                     └────────┬─────────┘          └──────────────────┘
                              │
                     ┌────────┴─────────┐
                     │  Git Repository  │
                     │  (YAML 관리)     │
                     └──────────────────┘
```

### 각 구성 요소의 역할

| 구성 요소 | 역할 | 설명 |
|---|---|---|
| **Prometheus** | 메트릭 수집 & Rule 평가 | 클러스터 내 모든 메트릭을 수집하고 PrometheusRule에 정의된 조건을 주기적으로 평가합니다 |
| **PrometheusRule** | 알람 조건 정의 (CR) | "이 조건이 N분 동안 지속되면 알람을 발생시켜라"라는 규칙을 Kubernetes Custom Resource로 정의합니다 |
| **Alertmanager** | 알람 라우팅 & 발송 | 발생한 알람을 라벨 기반으로 라우팅하여 적절한 채널(Slack, Email 등)로 발송합니다 |
| **ArgoCD** | GitOps 자동 배포 | Git 저장소의 YAML 변경을 감지하여 클러스터에 자동으로 적용합니다 |
| **Kustomize** | YAML 구성 관리 | 환경별(dev/stg/prod) YAML 구성을 효율적으로 관리합니다 |

### 알람 상태 전이

```
INACTIVE ──(조건 충족)──▶ PENDING ──(for 시간 경과)──▶ FIRING ──(조건 해소)──▶ RESOLVED
   │                                                      │
   │         조건이 for 시간 내에 해소되면                   │
   ◀──────────────────────────────────────────────────────◀
```

- **INACTIVE**: 조건이 충족되지 않은 정상 상태
- **PENDING**: 조건이 충족되었지만 `for` 시간이 아직 경과하지 않은 상태
- **FIRING**: 조건이 `for` 시간 이상 지속되어 실제 알람이 발송되는 상태
- **RESOLVED**: 알람이 발생했다가 조건이 해소된 상태 (해소 알람 발송)

---

## 2. PrometheusRule CR 이해하기

### PrometheusRule이란?

PrometheusRule은 **Prometheus Operator**가 관리하는 Kubernetes Custom Resource(CR)입니다.
이 CR을 생성하면 Prometheus가 자동으로 해당 규칙을 로딩하여 주기적으로 평가합니다.

각 서비스팀은 자신만의 PrometheusRule CR을 작성하여 **독립적으로 알람을 관리**할 수 있습니다.

### CR 구조 개요

```yaml
apiVersion: monitoring.coreos.com/v1    # Prometheus Operator API 그룹 (고정값)
kind: PrometheusRule                     # 리소스 종류 (고정값)
metadata:                                # 리소스 메타데이터
  name: ...                              #   → PrometheusRule 리소스 이름
  namespace: ...                         #   → 배포할 네임스페이스
  labels: ...                            #   → Prometheus가 이 Rule을 찾기 위한 라벨
spec:                                    # 실제 알람 규칙 정의
  groups:                                #   → 알람 규칙 그룹 목록
    - name: ...                          #     → 그룹 이름
      rules:                             #     → 이 그룹에 속한 알람 규칙들
        - alert: ...                     #       → 개별 알람 규칙
```

---

## 3. 필수 라벨 규칙

모든 PrometheusRule의 각 alert rule에는 **반드시 아래 3개 라벨**을 포함해야 합니다.
이 라벨들은 Alertmanager가 알람을 올바른 팀/채널로 라우팅하는 데 사용됩니다.

### 필수 라벨 목록

| 라벨 | 값 | 설명 | 예시 |
|---|---|---|---|
| `severity` | `info` \| `warn` \| `error` | 알람 심각도. Alertmanager 라우팅 및 알람 우선순위 결정에 사용 | `severity: error` |
| `service` | `{팀이름}` | 서비스/팀 식별자. 알람을 해당 팀 채널로 라우팅하는 데 사용 | `service: data-pipeline` |
| `app` | `{애플리케이션이름}` | 어떤 애플리케이션에서 발생한 알람인지 식별 | `app: spark-batch-job` |

### severity 상세 설명

| severity | 의미 | 사용 시나리오 | 알림 채널(예시) |
|---|---|---|---|
| `info` | 참고 정보 | 리소스 사용량 증가 추세, 배포 완료 알림 등 | Slack 채널 (일반) |
| `warn` | 경고 | 디스크 80% 초과, 응답 지연 증가, Pod 재시작 반복 등 | Slack 채널 (긴급) + Email |
| `error` | 장애 | 서비스 다운, 에러율 급증, 데이터 유실 위험 등 | Slack 채널 (긴급) + Email + PagerDuty |

### 필수 라벨이 누락되면?

- Alertmanager가 **어느 팀으로 라우팅해야 할지 알 수 없어** 알람이 누락될 수 있습니다
- `severity`가 없으면 알람 우선순위를 판단할 수 없습니다
- 인프라팀에서 라벨 누락 검증 Webhook을 운영할 예정이며, 누락 시 배포가 거부될 수 있습니다

---

## 4. PrometheusRule YAML 템플릿

아래 템플릿을 복사한 후 `TODO`로 표시된 부분만 수정하면 됩니다.

```yaml
# ============================================================================
# PrometheusRule: 서비스팀 알람 규칙
# ============================================================================
# 이 파일은 Prometheus Operator가 관리하는 Custom Resource입니다.
# Prometheus가 이 CR을 감지하면 자동으로 알람 규칙을 로딩합니다.
#
# 작성 후 Git에 Push하면 ArgoCD가 자동으로 클러스터에 배포합니다.
# ============================================================================
apiVersion: monitoring.coreos.com/v1     # Prometheus Operator CRD API 버전 (고정값, 수정 불필요)
kind: PrometheusRule                     # 리소스 종류 (고정값, 수정 불필요)

metadata:
  # ---------------------------------------------------------------------------
  # name: PrometheusRule 리소스의 고유 이름
  # ---------------------------------------------------------------------------
  # 규칙: {팀이름}-{용도}-rules (예: data-pipeline-alert-rules)
  # 같은 네임스페이스 내에서 중복되면 안 됩니다.
  name: TODO-TEAM-NAME-alert-rules       # TODO: 팀이름-용도-rules 형식으로 수정

  # ---------------------------------------------------------------------------
  # namespace: 이 리소스가 배포될 Kubernetes 네임스페이스
  # ---------------------------------------------------------------------------
  # 보통 팀 전용 네임스페이스를 사용합니다.
  # 모르겠으면 인프라팀에 문의하세요.
  namespace: TODO-NAMESPACE              # TODO: 팀 네임스페이스로 수정 (예: data-pipeline)

  # ---------------------------------------------------------------------------
  # labels: Prometheus가 이 Rule을 발견하기 위한 라벨
  # ---------------------------------------------------------------------------
  # 아래 라벨은 Prometheus의 ruleSelector와 매칭되어야 합니다.
  # "release: kube-prometheus-stack"은 대부분의 환경에서 필수입니다.
  # 인프라팀에서 별도로 안내한 라벨이 있으면 추가하세요.
  labels:
    release: kube-prometheus-stack        # Prometheus가 이 Rule을 인식하기 위한 라벨 (고정값)
    # prometheus: kube-prometheus          # (선택) 일부 환경에서 필요할 수 있음. 인프라팀 확인.

spec:
  # ===========================================================================
  # groups: 알람 규칙 그룹 목록
  # ===========================================================================
  # 하나의 PrometheusRule에 여러 그룹을 정의할 수 있습니다.
  # 그룹은 관련 알람을 논리적으로 묶는 단위입니다.
  # 예: "리소스 알람", "애플리케이션 알람", "SLA 알람" 등
  groups:

    # =========================================================================
    # 그룹 1: 알람 규칙 그룹
    # =========================================================================
    - name: TODO-team-name.alert-rules   # TODO: 그룹 이름 (예: data-pipeline.resource-alerts)
      # -----------------------------------------------------------------------
      # interval: 이 그룹의 규칙을 평가하는 주기 (선택사항)
      # -----------------------------------------------------------------------
      # 생략하면 Prometheus의 글로벌 evaluation_interval (기본 30s)을 사용합니다.
      # 특별한 이유가 없으면 생략을 권장합니다.
      # interval: 30s

      rules:
        # =====================================================================
        # Rule 1: 알람 규칙 예시
        # =====================================================================
        - alert: TODO_AlertName          # TODO: 알람 이름 (PascalCase 권장, 예: HighCpuUsage)
          # -------------------------------------------------------------------
          # expr: PromQL 표현식 (알람 조건)
          # -------------------------------------------------------------------
          # 이 표현식의 결과가 0보다 크면(= 결과가 존재하면) 알람 조건이 충족됩니다.
          # PromQL 문법은 아래 "PromQL 기본 문법" 섹션을 참고하세요.
          #
          # 주의: expr의 결과가 비어있으면(= 조건 불충족) 알람이 발생하지 않습니다.
          #       결과가 존재하면(= 조건 충족) 알람이 발생합니다.
          expr: |
            TODO_PROMQL_EXPRESSION       # TODO: PromQL 알람 조건식 작성
          # -------------------------------------------------------------------
          # for: 알람 조건이 지속되어야 하는 최소 시간
          # -------------------------------------------------------------------
          # 이 시간 동안 조건이 계속 충족되어야만 실제 알람(FIRING)이 발생합니다.
          # 일시적인 스파이크에 의한 오탐(false positive)을 방지합니다.
          #
          # 권장값:
          #   - info:  5m (5분)   → 추세 확인용이므로 넉넉하게
          #   - warn:  3m~5m     → 어느 정도 지속성 확인
          #   - error: 1m~3m     → 빠르게 감지해야 하므로 짧게
          #
          # 주의: 너무 짧으면 오탐이 많아지고, 너무 길면 알람이 늦게 옵니다.
          for: 5m                         # TODO: 알람 지속 시간 조정

          # -------------------------------------------------------------------
          # labels: 알람에 부착할 라벨
          # -------------------------------------------------------------------
          # Alertmanager가 이 라벨을 기반으로 알람을 라우팅합니다.
          # ⚠️ severity, service, app 3개 라벨은 필수입니다!
          labels:
            severity: warn               # [필수] 알람 심각도: info | warn | error
            service: TODO-TEAM-NAME      # [필수] 팀/서비스 이름 (예: data-pipeline)
            app: TODO-APP-NAME           # [필수] 애플리케이션 이름 (예: spark-batch-job)
            # tier: backend              # (선택) 추가 라벨: tier (frontend/backend/infra)
            # component: worker          # (선택) 추가 라벨: 컴포넌트 구분

          # -------------------------------------------------------------------
          # annotations: 알람 메시지에 포함할 추가 정보
          # -------------------------------------------------------------------
          # 알람을 수신했을 때 상황을 빠르게 파악할 수 있도록 상세 정보를 기입합니다.
          # 템플릿 변수를 사용하여 동적 값을 포함할 수 있습니다.
          #
          # 사용 가능한 템플릿 변수:
          #   {{ $labels }}       → 알람의 모든 라벨 (map)
          #   {{ $labels.pod }}   → 특정 라벨 값 (예: pod 이름)
          #   {{ $value }}        → expr의 결과 값 (숫자)
          #   {{ $labels.namespace }} → 네임스페이스 이름
          annotations:
            summary: "TODO: 알람 요약 (1줄)"
            # summary 예시: "{{ $labels.pod }} CPU 사용률 {{ $value | humanizePercentage }} 초과"

            description: "TODO: 알람 상세 설명"
            # description 예시: |
            #   Pod {{ $labels.pod }}의 CPU 사용률이 {{ $value | humanizePercentage }}입니다.
            #   네임스페이스: {{ $labels.namespace }}
            #   지속 시간: 5분 이상

            # runbook_url: "https://wiki.example.com/runbook/high-cpu"
            # (선택) 장애 대응 매뉴얼 URL. error 등급 알람에는 반드시 작성을 권장합니다.

        # =====================================================================
        # Rule 2: 추가 알람 규칙 (필요한 만큼 추가)
        # =====================================================================
        # - alert: AnotherAlertName
        #   expr: |
        #     another_promql_expression > threshold
        #   for: 3m
        #   labels:
        #     severity: error
        #     service: TODO-TEAM-NAME
        #     app: TODO-APP-NAME
        #   annotations:
        #     summary: "알람 요약"
        #     description: "알람 상세 설명"
```

---

## 5. 실전 알람 예시

### 예시 1: data-pipeline 팀의 Spark 배치 잡 알람

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: data-pipeline-alert-rules
  namespace: data-pipeline
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: data-pipeline.spark-alerts
      rules:
        # ----- Spark 잡 실패율 알람 (error) -----
        - alert: SparkJobFailureRateHigh
          expr: |
            (
              sum(rate(spark_job_failures_total{namespace="data-pipeline"}[5m]))
              /
              sum(rate(spark_job_submissions_total{namespace="data-pipeline"}[5m]))
            ) > 0.1
          for: 3m
          labels:
            severity: error              # 실패율 10% 초과 → 장애 등급
            service: data-pipeline       # 알람 수신 팀
            app: spark-batch-job         # 애플리케이션 식별
          annotations:
            summary: "Spark 배치 잡 실패율 {{ $value | humanizePercentage }} 초과"
            description: |
              data-pipeline 네임스페이스의 Spark 배치 잡 실패율이 10%를 초과했습니다.
              현재 실패율: {{ $value | humanizePercentage }}
              즉시 확인이 필요합니다.
            runbook_url: "https://wiki.example.com/runbook/spark-job-failure"

        # ----- Executor 메모리 사용량 알람 (warn) -----
        - alert: SparkExecutorMemoryHigh
          expr: |
            (
              container_memory_usage_bytes{namespace="data-pipeline", container="spark-executor"}
              /
              container_spec_memory_limit_bytes{namespace="data-pipeline", container="spark-executor"}
            ) > 0.85
          for: 5m
          labels:
            severity: warn               # 85% 초과 → 경고 등급
            service: data-pipeline
            app: spark-batch-job
          annotations:
            summary: "Spark Executor {{ $labels.pod }} 메모리 사용률 85% 초과"
            description: |
              Pod: {{ $labels.pod }}
              메모리 사용률: {{ $value | humanizePercentage }}
              OOM Kill 위험이 있으므로 리소스 조정을 검토하세요.

        # ----- 처리량 감소 알람 (info) -----
        - alert: SparkThroughputDecreased
          expr: |
            sum(rate(spark_records_processed_total{namespace="data-pipeline"}[10m]))
            < 1000
          for: 10m
          labels:
            severity: info               # 처리량 감소 추세 → 정보 등급
            service: data-pipeline
            app: spark-batch-job
          annotations:
            summary: "Spark 레코드 처리량이 분당 1000건 미만으로 감소"
            description: |
              최근 10분간 Spark 레코드 처리량이 분당 1000건 미만입니다.
              현재 처리량: {{ $value }} records/sec
              데이터 소스 또는 파이프라인 상태를 확인하세요.
```

### 예시 2: ml-serving 팀의 모델 서빙 알람

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ml-serving-alert-rules
  namespace: ml-serving
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: ml-serving.inference-alerts
      rules:
        # ----- 모델 추론 지연 알람 -----
        - alert: InferenceLatencyHigh
          expr: |
            histogram_quantile(0.95,
              sum(rate(inference_request_duration_seconds_bucket{namespace="ml-serving"}[5m])) by (le, pod)
            ) > 2
          for: 3m
          labels:
            severity: warn
            service: ml-serving
            app: model-serving-api
          annotations:
            summary: "모델 추론 P95 지연이 2초를 초과했습니다"
            description: |
              Pod: {{ $labels.pod }}
              P95 추론 지연: {{ $value | humanizeDuration }}
              모델 또는 인프라 리소스를 점검하세요.

        # ----- Pod 재시작 반복 알람 -----
        - alert: PodRestartingTooOften
          expr: |
            increase(kube_pod_container_status_restarts_total{namespace="ml-serving"}[1h]) > 3
          for: 5m
          labels:
            severity: error
            service: ml-serving
            app: model-serving-api
          annotations:
            summary: "{{ $labels.pod }} Pod이 1시간 내 {{ $value }}회 재시작"
            description: |
              Pod: {{ $labels.pod }}
              컨테이너: {{ $labels.container }}
              최근 1시간 재시작 횟수: {{ $value }}회
              OOMKilled 또는 CrashLoopBackOff 상태를 확인하세요.
```

### 예시 3: 범용 리소스 알람 (어떤 팀이든 활용 가능)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: TODO-TEAM-NAME-resource-rules    # TODO: 팀이름 수정
  namespace: TODO-NAMESPACE              # TODO: 네임스페이스 수정
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: TODO-team-name.resource-alerts
      rules:
        # ----- CPU 사용률 80% 초과 알람 -----
        - alert: HighCpuUsage
          expr: |
            (
              sum(rate(container_cpu_usage_seconds_total{namespace="TODO-NAMESPACE"}[5m])) by (pod)
              /
              sum(kube_pod_container_resource_limits{namespace="TODO-NAMESPACE", resource="cpu"}) by (pod)
            ) > 0.8
          for: 5m
          labels:
            severity: warn
            service: TODO-TEAM-NAME      # TODO: 팀이름
            app: TODO-APP-NAME           # TODO: 앱이름
          annotations:
            summary: "{{ $labels.pod }} CPU 사용률 80% 초과"
            description: |
              Pod {{ $labels.pod }}의 CPU 사용률이 80%를 초과했습니다.
              현재 사용률: {{ $value | humanizePercentage }}

        # ----- 메모리 사용률 85% 초과 알람 -----
        - alert: HighMemoryUsage
          expr: |
            (
              container_memory_usage_bytes{namespace="TODO-NAMESPACE"}
              /
              container_spec_memory_limit_bytes{namespace="TODO-NAMESPACE"}
            ) > 0.85
          for: 5m
          labels:
            severity: warn
            service: TODO-TEAM-NAME      # TODO: 팀이름
            app: TODO-APP-NAME           # TODO: 앱이름
          annotations:
            summary: "{{ $labels.pod }} 메모리 사용률 85% 초과"
            description: |
              Pod: {{ $labels.pod }}
              메모리 사용률: {{ $value | humanizePercentage }}
              OOM Kill 위험이 있습니다.

        # ----- PVC 디스크 사용률 90% 초과 알람 -----
        - alert: PvcDiskUsageHigh
          expr: |
            (
              kubelet_volume_stats_used_bytes{namespace="TODO-NAMESPACE"}
              /
              kubelet_volume_stats_capacity_bytes{namespace="TODO-NAMESPACE"}
            ) > 0.9
          for: 10m
          labels:
            severity: error
            service: TODO-TEAM-NAME      # TODO: 팀이름
            app: TODO-APP-NAME           # TODO: 앱이름
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} 디스크 사용률 90% 초과"
            description: |
              PVC: {{ $labels.persistentvolumeclaim }}
              사용률: {{ $value | humanizePercentage }}
              디스크 정리 또는 확장이 필요합니다.
```

---

## 6. Kustomize를 이용한 구성 관리

### 팀별 디렉토리 구조

각 서비스팀은 자신의 디렉토리에서 알람을 관리합니다.

```
alerting/
├── base/                              # 공통 설정 (인프라팀 관리)
│   ├── kustomization.yaml
│   └── common-rules.yaml              # 전체 공통 알람 (노드 다운 등)
│
├── teams/                             # 팀별 알람 설정
│   ├── data-pipeline/                 # data-pipeline 팀
│   │   ├── kustomization.yaml
│   │   └── prometheusrule.yaml        # 팀 알람 규칙
│   │
│   ├── ml-serving/                    # ml-serving 팀
│   │   ├── kustomization.yaml
│   │   └── prometheusrule.yaml
│   │
│   └── user-service/                  # user-service 팀
│       ├── kustomization.yaml
│       └── prometheusrule.yaml
│
└── overlays/                          # 환경별 오버레이 (선택)
    ├── dev/
    │   └── kustomization.yaml
    ├── stg/
    │   └── kustomization.yaml
    └── prod/
        └── kustomization.yaml
```

### 팀 kustomization.yaml 작성

```yaml
# alerting/teams/data-pipeline/kustomization.yaml
# ============================================================================
# Kustomization: data-pipeline 팀 알람 규칙
# ============================================================================
# 이 파일은 Kustomize가 이 디렉토리의 리소스를 인식하기 위해 필요합니다.
# resources에 팀의 PrometheusRule YAML 파일을 나열하세요.
# ============================================================================
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# namespace: 모든 리소스에 적용할 네임스페이스 (선택사항)
# PrometheusRule YAML에 이미 namespace를 지정했다면 생략 가능합니다.
# namespace: data-pipeline

# ---------------------------------------------------------------------------
# resources: 이 디렉토리에서 관리하는 리소스 파일 목록
# ---------------------------------------------------------------------------
# 새 알람 파일을 추가하면 여기에도 추가해야 합니다.
resources:
  - prometheusrule.yaml
  # - additional-rules.yaml           # 알람 파일이 추가되면 여기에 나열

# ---------------------------------------------------------------------------
# commonLabels: 모든 리소스에 공통으로 추가할 라벨 (선택사항)
# ---------------------------------------------------------------------------
# 팀 식별을 위해 추가하면 유용합니다.
commonLabels:
  managed-by: data-pipeline-team
```

### 환경별 오버레이 (선택사항)

dev/stg/prod 환경에서 알람 임계값을 다르게 설정하고 싶을 때 사용합니다.

```yaml
# alerting/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# 베이스 디렉토리 참조
resources:
  - ../../teams/data-pipeline
  - ../../teams/ml-serving
  - ../../teams/user-service

# (선택) prod 환경 전용 패치
# patchesStrategicMerge:
#   - prod-threshold-patch.yaml
```

---

## 7. ArgoCD Application 배포 설정

### ArgoCD Application YAML

각 팀별로 ArgoCD Application을 생성하여 **GitOps 기반 자동 배포**를 설정합니다.

```yaml
# argocd/applications/data-pipeline-alerts.yaml
# ============================================================================
# ArgoCD Application: data-pipeline 팀 알람 자동 배포
# ============================================================================
# 이 Application은 Git 저장소의 알람 설정을 자동으로 클러스터에 배포합니다.
# Git에 변경사항이 Push되면 ArgoCD가 자동으로 감지하여 적용합니다.
# ============================================================================
apiVersion: argoproj.io/v1alpha1          # ArgoCD API 버전 (고정값)
kind: Application                         # ArgoCD Application 리소스 (고정값)

metadata:
  # ---------------------------------------------------------------------------
  # name: ArgoCD Application 이름
  # ---------------------------------------------------------------------------
  # ArgoCD UI에서 이 이름으로 표시됩니다.
  name: data-pipeline-alert-rules         # TODO: {팀이름}-alert-rules 형식으로 수정

  # ---------------------------------------------------------------------------
  # namespace: ArgoCD가 설치된 네임스페이스 (보통 argocd)
  # ---------------------------------------------------------------------------
  namespace: argocd                       # ArgoCD 네임스페이스 (보통 고정)

  # ---------------------------------------------------------------------------
  # labels: ArgoCD Application에 부착할 라벨
  # ---------------------------------------------------------------------------
  labels:
    team: data-pipeline                   # TODO: 팀 이름
    type: alerting                        # 용도: 알람 설정

  # ---------------------------------------------------------------------------
  # finalizers: Application 삭제 시 클러스터 리소스도 함께 정리
  # ---------------------------------------------------------------------------
  # 이 설정이 있으면 ArgoCD Application을 삭제할 때
  # 클러스터에 배포된 PrometheusRule도 함께 삭제됩니다.
  finalizers:
    - resources-finalizer.argocd.argoproj.io

spec:
  # ---------------------------------------------------------------------------
  # project: ArgoCD 프로젝트 (접근 권한 관리 단위)
  # ---------------------------------------------------------------------------
  # 인프라팀에서 안내한 프로젝트 이름을 사용하세요.
  # 모르면 "default"를 사용하거나 인프라팀에 문의하세요.
  project: default                        # TODO: ArgoCD 프로젝트명 (인프라팀 확인)

  # ---------------------------------------------------------------------------
  # source: Git 저장소 설정 (어디서 YAML을 가져올지)
  # ---------------------------------------------------------------------------
  source:
    repoURL: https://github.com/YOUR_ORG/YOUR_REPO.git  # TODO: Git 저장소 URL
    targetRevision: main                                  # TODO: 브랜치 (main, master 등)
    path: alerting/teams/data-pipeline                    # TODO: 팀 알람 디렉토리 경로

    # Kustomize 옵션 (kustomization.yaml이 있는 경우 자동 인식)
    # kustomize:
    #   namePrefix: prod-                # (선택) 리소스 이름에 접두사 추가

  # ---------------------------------------------------------------------------
  # destination: 배포 대상 클러스터 및 네임스페이스
  # ---------------------------------------------------------------------------
  destination:
    server: https://kubernetes.default.svc  # 클러스터 API 서버 (같은 클러스터면 이 값 고정)
    namespace: data-pipeline                # TODO: 팀 네임스페이스

  # ---------------------------------------------------------------------------
  # syncPolicy: 동기화(배포) 정책
  # ---------------------------------------------------------------------------
  syncPolicy:
    # automated: Git 변경 시 자동으로 배포 (수동 Sync 불필요)
    automated:
      prune: true                         # Git에서 삭제된 리소스를 클러스터에서도 삭제
      selfHeal: true                      # 클러스터에서 수동 변경된 리소스를 Git 상태로 복원
      # allowEmpty: false                 # (기본값) 빈 디렉토리는 동기화하지 않음

    # syncOptions: 동기화 옵션
    syncOptions:
      - CreateNamespace=true              # 네임스페이스가 없으면 자동 생성
      - PrunePropagationPolicy=foreground # 삭제 시 의존 리소스 순서대로 정리
      - PruneLast=true                    # 새 리소스 생성 후 마지막에 불필요 리소스 삭제

    # retry: 동기화 실패 시 재시도 설정
    retry:
      limit: 3                            # 최대 3회 재시도
      backoff:
        duration: 10s                     # 첫 재시도 대기 시간
        factor: 2                         # 대기 시간 증가 배수 (10s → 20s → 40s)
        maxDuration: 3m                   # 최대 대기 시간
```

### ArgoCD 자동 배포 흐름

```
1. 서비스팀이 prometheusrule.yaml 수정 후 Git Push
           ↓
2. ArgoCD가 Git 변경 감지 (기본 3분 간격 polling 또는 Webhook)
           ↓
3. ArgoCD가 Kustomize로 YAML 빌드
           ↓
4. 클러스터에 PrometheusRule CR 적용 (kubectl apply 와 동일)
           ↓
5. Prometheus Operator가 CR 변경 감지 → Prometheus에 Rule 로딩
           ↓
6. 알람 규칙 활성화 완료!
```

---

## 8. 디렉토리 구조 및 Git 워크플로우

### 전체 저장소 구조 예시

```
repo-root/
├── alerting/
│   ├── teams/
│   │   └── {your-team}/               # 서비스팀이 관리하는 디렉토리
│   │       ├── kustomization.yaml
│   │       └── prometheusrule.yaml
│   └── overlays/
│       └── prod/
│           └── kustomization.yaml
│
├── argocd/
│   └── applications/
│       └── {your-team}-alert-rules.yaml  # ArgoCD Application (인프라팀과 협의)
│
└── ...
```

### Git 워크플로우

```bash
# 1. 저장소 clone
git clone https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO

# 2. 팀 브랜치 생성
git checkout -b feature/add-data-pipeline-alerts

# 3. 팀 디렉토리 생성 (처음 한 번만)
mkdir -p alerting/teams/data-pipeline

# 4. PrometheusRule YAML 작성 (위 템플릿 참고)
vim alerting/teams/data-pipeline/prometheusrule.yaml

# 5. kustomization.yaml 작성
vim alerting/teams/data-pipeline/kustomization.yaml

# 6. 로컬 검증 (Kustomize 빌드 테스트)
kubectl kustomize alerting/teams/data-pipeline/

# 7. YAML 문법 검증
kubectl apply --dry-run=client -f alerting/teams/data-pipeline/prometheusrule.yaml

# 8. Git 커밋 & Push
git add alerting/teams/data-pipeline/
git commit -m "feat: add alert rules for data-pipeline team"
git push origin feature/add-data-pipeline-alerts

# 9. Pull Request 생성 → 코드 리뷰 → Merge
# 10. ArgoCD가 자동으로 클러스터에 배포
```

---

## 9. 배포 및 검증 방법

### 배포 전 로컬 검증

```bash
# YAML 문법 검증 (dry-run)
kubectl apply --dry-run=client -f alerting/teams/data-pipeline/prometheusrule.yaml

# Kustomize 빌드 결과 확인
kubectl kustomize alerting/teams/data-pipeline/

# yamllint로 문법 검사 (선택)
yamllint alerting/teams/data-pipeline/prometheusrule.yaml
```

### 배포 후 확인

```bash
# 1. PrometheusRule CR이 생성되었는지 확인
kubectl get prometheusrules -n data-pipeline
# 출력 예시:
# NAME                        AGE
# data-pipeline-alert-rules   2m

# 2. PrometheusRule 상세 확인
kubectl describe prometheusrule data-pipeline-alert-rules -n data-pipeline

# 3. ArgoCD 동기화 상태 확인
argocd app get data-pipeline-alert-rules
# 또는 ArgoCD UI에서 확인: https://argocd.example.com

# 4. Prometheus UI에서 Rule이 로딩되었는지 확인
#    Prometheus UI → Status → Rules 메뉴에서 검색
#    URL: https://prometheus.example.com/rules

# 5. 알람 테스트 (선택) - Prometheus UI → Alerts에서 알람 상태 확인
#    URL: https://prometheus.example.com/alerts
```

### ArgoCD CLI로 확인

```bash
# ArgoCD 로그인
argocd login argocd.example.com

# Application 목록 확인
argocd app list | grep alert

# 특정 Application 상태 확인
argocd app get data-pipeline-alert-rules

# 수동 동기화 (자동 동기화가 안 될 때)
argocd app sync data-pipeline-alert-rules

# 동기화 이력 확인
argocd app history data-pipeline-alert-rules
```

---

## 10. PromQL 기본 문법

알람 조건(`expr`)에 사용하는 PromQL의 기본 문법입니다.

### 자주 사용하는 패턴

```promql
# ----- 비율(Rate) 계산: Counter 메트릭의 초당 변화율 -----
rate(http_requests_total{namespace="my-ns"}[5m])
# → 최근 5분간 초당 요청 수

# ----- 합계: 여러 시계열의 합 -----
sum(rate(http_requests_total{namespace="my-ns"}[5m])) by (pod)
# → Pod별 초당 총 요청 수

# ----- 비율(Ratio) 계산: 에러율 -----
sum(rate(http_requests_total{status=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))
# → 전체 요청 대비 5xx 에러 비율

# ----- 증가량: 특정 기간 동안의 증가량 -----
increase(kube_pod_container_status_restarts_total{namespace="my-ns"}[1h])
# → 최근 1시간 동안의 재시작 횟수 증가

# ----- 퍼센타일: 히스토그램에서 95번째 백분위 -----
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)
# → P95 응답 시간

# ----- 임계값 비교: 특정 값 초과/미만 -----
container_memory_usage_bytes{namespace="my-ns"} > 1073741824
# → 메모리 사용량 1GB 초과

# ----- 부재 감지: 메트릭이 사라졌는지 -----
absent(up{job="my-service"})
# → my-service의 up 메트릭이 없으면 (= 서비스 다운)
```

### 유용한 템플릿 함수 (annotations에서 사용)

| 함수 | 설명 | 예시 입력 → 출력 |
|---|---|---|
| `{{ $value }}` | expr 결과 원본 값 | `0.8523` |
| `{{ $value \| humanizePercentage }}` | 퍼센트 형식 | `0.8523` → `85.23%` |
| `{{ $value \| humanize }}` | 읽기 쉬운 숫자 | `1234567` → `1.235M` |
| `{{ $value \| humanize1024 }}` | 바이트 단위 | `1073741824` → `1Gi` |
| `{{ $value \| humanizeDuration }}` | 시간 단위 | `3723` → `1h 2m 3s` |
| `{{ $labels.pod }}` | 특정 라벨 값 | `my-app-7d8f9-abc12` |

---

## 11. 자주 묻는 질문 (FAQ)

### Q1: "PrometheusRule을 배포했는데 Prometheus에서 안 보여요"

**확인 순서:**

1. CR이 생성되었는지 확인:
   ```bash
   kubectl get prometheusrules -n YOUR_NAMESPACE
   ```

2. `metadata.labels`에 `release: kube-prometheus-stack`이 있는지 확인:
   ```bash
   kubectl get prometheusrule YOUR_RULE_NAME -n YOUR_NAMESPACE -o yaml | grep -A5 labels
   ```
   Prometheus의 `ruleSelector`와 매칭되지 않으면 Rule이 로딩되지 않습니다.

3. Prometheus Operator 로그 확인:
   ```bash
   kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=50
   ```

### Q2: "알람이 PENDING 상태에서 FIRING으로 안 넘어가요"

- `for` 시간이 아직 경과하지 않았을 수 있습니다
- `for: 5m`이면 조건이 5분 이상 **연속으로** 충족되어야 FIRING 됩니다
- 중간에 잠깐이라도 조건이 해소되면 다시 INACTIVE로 돌아갑니다

### Q3: "알람이 FIRING인데 Slack 알림이 안 와요"

- Alertmanager의 라우팅 설정을 확인하세요 (인프라팀에 문의)
- `labels.service` 값이 Alertmanager의 `routes` 설정과 매칭되는지 확인
- Alertmanager UI에서 알람 상태 확인:
  ```
  https://alertmanager.example.com/#/alerts
  ```

### Q4: "severity를 어떤 걸로 설정해야 할지 모르겠어요"

판단 기준:

| 질문 | Yes → | No → |
|---|---|---|
| 서비스가 완전히 중단되었나요? | `error` | 아래로 |
| 조치 안 하면 장애로 이어지나요? | `warn` | 아래로 |
| 참고용 정보인가요? | `info` | `warn` |

### Q5: "하나의 PrometheusRule에 알람을 몇 개까지 넣을 수 있나요?"

- 기술적 제한은 없지만, **관리 편의성**을 위해 하나의 파일에 10~20개 이하를 권장합니다
- 알람이 많아지면 용도별로 파일을 분리하세요:
  ```
  teams/data-pipeline/
  ├── kustomization.yaml
  ├── resource-rules.yaml        # 리소스(CPU/메모리) 알람
  ├── application-rules.yaml     # 애플리케이션 비즈니스 알람
  └── sla-rules.yaml             # SLA/SLO 알람
  ```

### Q6: "다른 팀의 알람 설정을 참고하고 싶어요"

- Git 저장소의 `alerting/teams/` 디렉토리에서 다른 팀의 설정을 참고할 수 있습니다
- 본 가이드의 [실전 알람 예시](#5-실전-알람-예시) 섹션을 참고하세요

---

## 12. 체크리스트

### PrometheusRule YAML 작성 체크리스트

- [ ] `apiVersion: monitoring.coreos.com/v1` 인가?
- [ ] `kind: PrometheusRule` 인가?
- [ ] `metadata.name`이 `{팀이름}-alert-rules` 형식인가?
- [ ] `metadata.namespace`가 팀 네임스페이스인가?
- [ ] `metadata.labels`에 `release: kube-prometheus-stack`이 있는가?
- [ ] 모든 알람 rule에 **필수 라벨 3개**가 있는가?
  - [ ] `severity: info | warn | error`
  - [ ] `service: {팀이름}`
  - [ ] `app: {애플리케이션이름}`
- [ ] `for` 값이 적절한가? (너무 짧으면 오탐, 너무 길면 늦은 알람)
- [ ] `annotations.summary`와 `annotations.description`이 명확한가?
- [ ] `expr`의 PromQL이 올바른가? (Prometheus UI에서 미리 테스트)

### 배포 체크리스트

- [ ] `kubectl apply --dry-run=client`로 YAML 문법 검증 완료?
- [ ] `kubectl kustomize`로 빌드 테스트 완료?
- [ ] Git에 커밋하고 Push 완료?
- [ ] ArgoCD에서 Sync 상태가 `Synced` / `Healthy` 인가?
- [ ] Prometheus UI → Rules에서 규칙이 보이는가?
- [ ] 테스트 알람이 정상적으로 FIRING → Slack/Email 수신되는가?

---

## 도움이 필요할 때

| 상황 | 연락처 |
|---|---|
| PrometheusRule 작성 방법 | 이 가이드 참고 또는 Slack: #monitoring-support |
| Alertmanager 라우팅 설정 | 인프라팀 (Slack: #infra-support) |
| ArgoCD 배포 문제 | 인프라팀 (Slack: #infra-support) |
| PromQL 작성 도움 | Slack: #monitoring-support |
| 새 팀 네임스페이스 생성 | 인프라팀 (Slack: #infra-support) |
