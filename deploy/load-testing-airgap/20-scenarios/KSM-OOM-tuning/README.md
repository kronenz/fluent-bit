# KSM-OOM-tuning — kube-state-metrics memory limit 발견

concept 의 "kube-state-metric OOMKilled 한계 튜닝". K8s 객체 (pods,
configmaps, services) 를 단계적으로 늘려 KSM 의 메트릭 export 메모리
사용량을 측정.

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| KSM 가동 | `kubectl -n monitoring get pod -l app.kubernetes.io/name=kube-state-metrics` | Running |
| Prometheus 도달 | curl ${PROMETHEUS_URL}/-/ready | OK |
| 클러스터 여유 | `kubectl top node` | CPU/MEM < 70% |
| pause 이미지 | Nexus mirror 존재 | OK |
| RBAC | `kubectl -n load-test get sa kube-burner` | exists (KSM-02-04 시나리오 적용 후 자동) |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/KSM-OOM-tuning/
kubectl -n load-test logs -f job/ksm-oom-tuning
```

부하 패턴 (단일노드 testbed 안전치):
- 50 iter × (3 pod + 3 cm + 3 svc) = **450 K8s 객체** 빠른 생성
- 30초 간격으로 KSM RSS + scrape duration 측정

멀티노드 (운영급): `jobIterations: 500~5000` 으로 변경 후 재apply.

## 수동 모니터링 (병렬 권장)

```bash
# KSM 메모리 watch
watch -n 2 'kubectl -n monitoring top pod -l app.kubernetes.io/name=kube-state-metrics'

# 객체 생성 진행 확인
watch -n 5 'kubectl get ns | grep ksm-oom | wc -l'
```

## 기대 결과 (testbed 50 iter 기준)

| Stage | 시점 | KSM RSS | scrape duration |
|-------|------|---------|-----------------|
| baseline | 부하 전 | 30 ~ 60 MB | < 0.1 s |
| ramp-1 | 30s | 50 ~ 100 MB | 0.2 ~ 0.5 s |
| ramp-3 | 90s | 100 ~ 200 MB | 0.5 ~ 1.0 s |
| ramp-6 | 180s | 150 ~ 300 MB | 1.0 ~ 2.0 s |
| post | cleanup 후 30s | 60 ~ 100 MB | 0.1 ~ 0.3 s |

**운영급 5000 iter** 추정:
- KSM RSS 500 MB ~ 2 GB
- scrape duration 5 ~ 30 s (위험 — Prometheus scrape_timeout 초과 가능)

## 운영 limit 결정 공식

```
운영 limit = max(
  운영 환경 정상 객체수 기준 RSS × 2,
  burst (예: rolling update 다수 진행 중) RSS × 1.3
)
```

KSM scrape duration 이 prometheus `scrape_timeout` (기본 10s) 의 50% 이상이면 별도 알람 필요.

## OOMKilled 발생 시

```bash
# limit 임시 상향
kubectl -n monitoring patch deploy/kps-kube-state-metrics --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"1Gi"}
]'

# 영구 적용 — helm values:
# kube-state-metrics:
#   resources:
#     limits: { memory: 1Gi, cpu: 1 }
#     requests: { memory: 256Mi, cpu: 100m }
```

## scrape duration 개선

| 방법 | 설명 |
|------|------|
| `--metric-allowlist` | 필요한 메트릭만 export (큰 효과) |
| `--metric-denylist`  | 무거운 메트릭 제외 |
| sharding | KSM replica 증설 + sharding (1000+ pods 환경) |
| scrape interval ↑ | 30s → 60s 로 빈도 낮춤 |

## 결과 확인

```bash
kubectl -n load-test logs job/ksm-oom-tuning

# 잔재 namespace 강제 정리 (Job 중간 종료 시)
kubectl get ns -o name | grep '^namespace/ksm-oom-' | xargs -r kubectl delete --wait=false
```

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/KSM-OOM-tuning/
kubectl get ns -o name | grep '^namespace/ksm-oom-' | xargs -r kubectl delete --wait=false
```
