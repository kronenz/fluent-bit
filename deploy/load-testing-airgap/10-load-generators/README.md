# 10-load-generators

백그라운드에서 지속적으로 동작하는 부하 발생기 (Deployment) 와 메트릭
소스 (Exporter). 시나리오별로 필요한 것만 가동합니다.

## 매니페스트

| 파일 | 역할 | 의존 시나리오 | 메모리 limit |
|------|------|---------------|--------------|
| `flog-loader.yaml`      | 합성 JSON 로그 → fluent-bit → OS  | FB-01/02/04/05, OS-02, OS-16 | 128Mi |
| `avalanche.yaml`        | 합성 Prometheus /metrics          | PR-01/02/05, PR-03/04        | **512Mi** ↑ |
| `loggen-spark.yaml`     | 고-cardinality 로그               | OS-14                        | 128Mi |
| `opensearch-exporter.yaml` | OS 클러스터 메트릭 → Prometheus | (모든 OS 시나리오의 측정 소스) | **512Mi** ↑ |

## 가동/중지

```bash
# 가동 (필요한 것만)
kubectl apply -f deploy/load-testing-airgap/10-load-generators/flog-loader.yaml
kubectl apply -f deploy/load-testing-airgap/10-load-generators/avalanche.yaml

# 중지 (replicas 0)
kubectl -n load-test scale deploy/flog-loader --replicas=0
kubectl -n load-test scale deploy/avalanche  --replicas=0

# 완전 제거
kubectl delete -f deploy/load-testing-airgap/10-load-generators/avalanche.yaml
```

## 가동 상태 확인

```bash
kubectl -n load-test get deploy -l role=load-generator
# NAME           READY   UP-TO-DATE   AVAILABLE
# flog-loader    3/3     3            3
# avalanche      2/2     2            2
# loggen-spark   3/3     3            3

kubectl -n monitoring get deploy/opensearch-exporter
```

## 로그 파이프라인 검증 (flog → fluent-bit → OS)

```bash
# 1) flog 출력 확인
kubectl -n load-test logs deploy/flog-loader --tail=3
# {"host":"...","level":"info","msg":"...",...}

# 2) fluent-bit 가 읽고 있는지 (DaemonSet 이름은 환경 따라 다름)
kubectl -n kube-system logs ds/fluent-bit --tail=20 | grep -i 'logs-fb-'

# 3) OS 인덱스 생성 확인
kubectl -n monitoring exec opensearch-lt-node-0 -- \
  curl -s http://localhost:9200/_cat/indices/logs-fb-* | head
```

## 운영급 부하로 스케일

```bash
# lt-config 에서 운영값으로 변경 후
kubectl apply -f deploy/load-testing-airgap/00-prerequisites/lt-config.yaml

# Deployment replicas 증가 (lt-config 의 *_REPLICAS 는 표시용; 실제는
# Deployment.spec.replicas 가 영향력 있음)
kubectl -n load-test scale deploy/flog-loader --replicas=10
kubectl -n load-test scale deploy/avalanche  --replicas=20
```
