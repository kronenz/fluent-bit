# Prometheus Alerting Rules Guide

> kube-prometheus-stack v73.1.0 (appVersion: 0.82.2) 기반 운영 가이드

## 문서 구조

| 문서 | 설명 |
|------|------|
| [01-default-rules.md](./01-default-rules.md) | kube-prometheus-stack 기본 내장 Rule Group 전체 설명 |
| [02-additional-rules.md](./02-additional-rules.md) | Production 운영을 위한 추가 권장 Rule 및 PrometheusRule 예시 |
| [03-operations-guide.md](./03-operations-guide.md) | Alert 운영 전략, Severity 체계, 대응 프로세스 가이드 |

## 개요

kube-prometheus-stack은 Kubernetes 클러스터 모니터링을 위한 통합 Helm Chart로, Prometheus Operator / Prometheus / Alertmanager / Grafana / kube-state-metrics / node-exporter를 하나의 패키지로 배포합니다.

v73.1.0 기준 **18개 기본 Rule Group**과 **41개 Rule YAML 파일**이 포함되어 있으며, 이 문서에서는 각 Rule Group의 역할과 포함된 Alert를 상세히 분석하고, Production 환경에서 추가로 챙겨야 할 Alert Rule을 제안합니다.

## 대상 독자

- Kubernetes 클러스터 운영 관리자
- SRE / Platform Engineer
- DevOps 엔지니어

## 참고 자료

- [prometheus-community/helm-charts - kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Prometheus Alerting Rules 공식 문서](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Awesome Prometheus Alerts](https://samber.github.io/awesome-prometheus-alerts/rules.html)
- [Prometheus Operator - Alerting Routes](https://prometheus-operator.dev/docs/developer/alerting/)
