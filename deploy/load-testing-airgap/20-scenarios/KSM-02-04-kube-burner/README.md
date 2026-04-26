# KSM-02 / KSM-03 / KSM-04 — kube-burner pod density

| ID | 이름 | 측정 포인트 |
|----|------|-------------|
| KSM-02 | scrape time growth | `kube_state_metrics_scrape_duration_seconds` |
| KSM-03 | ingest backlog     | `prometheus_tsdb_head_chunks` 이상 누적 |
| KSM-04 | watch event burst  | `apiserver_watch_events_total` rate |

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| 컨트롤플레인 여유 | `kubectl top node` | CPU/MEM < 70% |
| KSM 가동 | `kubectl -n monitoring get pod -l app.kubernetes.io/name=kube-state-metrics` | Running |
| pause 이미지 mirror | `docker pull nexus.intranet:8082/loadtest/pause:3.10` | OK |
| RBAC 부여 가능 | (cluster-admin OK) | — |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/KSM-02-04-kube-burner/
kubectl -n load-test logs -f job/kube-burner-pod-density
```

진행 단계:
1. `time="..." level=info msg="📁 Creating job pod-density"`
2. namespace `kburner-N` 100개 생성
3. 각 namespace 에 burner-pod-N-1 생성 → Ready 대기 → 다음 iter
4. `level=info msg="GC running"` → cleanup
5. `level=info msg="Total elapsed time: ..."`

## 부하 강도 조절

`00-prerequisites/lt-config.yaml` 의 `KSM_BURNER_ITERATIONS` 변경 후
ConfigMap `kube-burner-config` 의 `jobIterations` 도 같이 변경 (kube-burner
는 Go template env() 가 ConfigMap 값을 읽지 못 함 → 직접 편집 필요).

| 환경 | jobIterations |
|------|----------------|
| 단일 노드 minikube | ≤ 200 |
| 4-node 테스트 | ≤ 1,000 |
| 운영 시뮬레이션 | 10,000 |

## 기대 결과

| 지표 | 100 iter 기준 |
|------|----------------|
| Job 종료 시간 | 5 ~ 15 분 |
| 생성/삭제된 pod | 100 |
| KSM scrape p95 (도중) | < 1 s |
| KSM scrape p95 (직후 회복) | < 200 ms |
| apiserver request rate spike | up to 5x baseline |
| etcd write rate | up to 3x baseline |

## 결과 확인

```bash
kubectl -n load-test logs job/kube-burner-pod-density | tail -30

# 진행 중 동시 모니터
kubectl get ns -l kube-burner.io/skip-resource=true

# KSM scrape 시간 추이
curl -s "${PROMETHEUS_URL}/api/v1/query?query=kube_state_metrics_scrape_duration_seconds" | jq
```

대시보드: `http://<grafana>/d/lt-ksm` → "KSM-02/03/04" 패널

## 실패 신호

| 증상 | 원인 | 해결 |
|------|------|------|
| pod 생성 stuck | 노드 자원 부족 / scheduler 지연 | `jobIterations` 낮춤, 다른 부하 정지 |
| `OOMKilled` (kube-burner) | iteration 多 + Go process | `limits.memory: 768Mi` → `1Gi` 상향 |
| KSM 응답 5s+ | KSM 자체 saturation | KSM replica 증설, scrape interval 증가 |
| etcd alarm | etcd disk 부족 / WAL 적체 | `jobIterations` 즉시 낮춤 |

## 정리

cleanup: true 가 활성이라 Job 종료 시 자동 정리되지만, 중간에 죽이면
잔재 namespace 가 남습니다:

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/KSM-02-04-kube-burner/

# 잔재 namespace 강제 삭제
kubectl get ns -o name | grep '^namespace/kburner-' | xargs -r kubectl delete
```
