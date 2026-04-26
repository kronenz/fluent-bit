# NE-OOM-tuning — node-exporter memory limit 발견

concept 의 "node-exporter OOMKilled 한계 튜닝". testbed 에서 실제로
node-exporter 가 **17번 OOMKilled** 된 사례를 재현하고 안전 limit 도출.

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| node-exporter DaemonSet | `kubectl -n monitoring get ds -l app.kubernetes.io/name=prometheus-node-exporter` | DESIRED=NODES |
| Prometheus 도달 | curl ${PROMETHEUS_URL}/-/ready | OK |
| Service Endpoint | `kubectl -n monitoring get svc kps-prometheus-node-exporter` | exists |

## 실행 (자동 ramp)

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/NE-OOM-tuning/
kubectl -n load-test logs -f job/ne-oom-tuning
```

자동 ramp 4 단계:

| Stage | concurrency | RPS/worker | total RPS | 지속 |
|-------|-------------|------------|-----------|------|
| baseline | 10  | 50 | 500    | 30s |
| normal   | 50  | 50 | 2,500  | 60s |
| high     | 100 | 50 | 5,000  | 60s |
| peak     | 200 | 50 | 10,000 | 60s |

각 stage 후 node-exporter RSS 피크를 Prometheus 에서 조회.

## 수동 모니터링 (병렬 권장)

```bash
# OOMKilled 즉시 감지
kubectl -n monitoring get pod -l app.kubernetes.io/name=prometheus-node-exporter -w
# RESTARTS 컬럼이 증가하면 OOM 발생

# 메모리 watch (1초 간격)
watch -n 1 'kubectl -n monitoring top pod -l app.kubernetes.io/name=prometheus-node-exporter'

# OOM history
kubectl -n monitoring describe pod -l app.kubernetes.io/name=prometheus-node-exporter | grep -B2 -A3 OOMKilled
```

## 기대 결과 (testbed 기준)

| Stage | total RPS | node-exporter RSS peak | OOM ? |
|-------|-----------|--------------------------|-------|
| baseline | 500    | 30 ~ 50 MB    | No |
| normal   | 2,500  | 50 ~ 100 MB   | No |
| high     | 5,000  | 100 ~ 200 MB  | (limit 따라) |
| peak     | 10,000 | 200 ~ 400 MB  | (limit 80MB 인 경우 OOMKilled) |

testbed 의 17번 OOMKilled 는 helm chart 기본 limit 이 작은 상황에서 발생한 것으로 추정.

## 운영 limit 결정 공식

```
운영 limit = peak stage RSS × 1.5
         또는
         normal stage RSS × 3 (burst 흡수)
```

실측치가 peak=300MB 면 → 450MB ~ 900MB limit. 권장 512MB.

## OOMKilled 발생 시 즉시 조치

```bash
# 현재 limit 확인
kubectl -n monitoring get pod -l app.kubernetes.io/name=prometheus-node-exporter \
  -o jsonpath='{.items[0].spec.containers[0].resources}' | jq

# 임시 상향 (helm 재배포 전)
kubectl -n monitoring patch ds kps-prometheus-node-exporter --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"512Mi"}
]'

# 영구 적용은 helm values:
# resources:
#   limits: { memory: 512Mi, cpu: 500m }
#   requests: { memory: 128Mi, cpu: 100m }
```

## 결과 확인

```bash
kubectl -n load-test logs job/ne-oom-tuning

# OOM 발생 횟수
kubectl -n monitoring get pod -l app.kubernetes.io/name=prometheus-node-exporter \
  -o jsonpath='{.items[*].status.containerStatuses[*].restartCount}'

# Prometheus 에서 메모리 추세
curl -s "${PROMETHEUS_URL}/api/v1/query_range?query=container_memory_working_set_bytes%7Bnamespace%3D%22monitoring%22%2Cpod%3D~%22kps-prometheus-node-exporter.*%22%7D&start=$(date -d -10min +%s)&end=$(date +%s)&step=15" | jq
```

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/NE-OOM-tuning/
```
