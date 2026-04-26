# OS-02 — k6 heavy search

50 VU 동시 _search 로 OpenSearch 의 thread_pool/search saturation 와
JVM heap pressure 를 강제로 발생시켜 stress 시나리오 측정.

## 사전 조건

| 항목 | 명령 | 정상값 |
|------|------|--------|
| 인덱스에 데이터 존재 | `curl ${OPENSEARCH_URL}/${OS_INDEX_PATTERN}/_count` | `count > 100,000` 이상 권장 |
| flog 또는 OSB 로 사전 채움 | `10-load-generators/flog-loader.yaml` 가동 후 5~10분 대기 | 인덱스 자동 생성 |
| lt-config 적용 | `kubectl -n load-test get cm lt-config` | exists |

## 실행

```bash
# 데이터 사전 적재 (10분 대기)
kubectl apply -f deploy/load-testing-airgap/10-load-generators/flog-loader.yaml
sleep 600

# 본 시나리오 실행 (7분: ramp-up 1m + 5m + ramp-down 1m)
kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-02-k6-heavy-search/
kubectl -n load-test logs -f job/k6-opensearch-search
```

## 부하 패턴

| Stage | 시간 | VU |
|-------|------|----|
| Ramp-up   | 1m | 0 → 25 |
| Sustained | 5m | 50     |
| Ramp-down | 1m | 50 → 0 |

## 기대 결과 (k6 threshold)

| 지표 | 임계 | 의미 |
|------|------|------|
| `http_req_duration p95` | < 500 ms | 95% 응답 0.5초 내 |
| `http_req_duration p99` | < 1,500 ms | 99% 응답 1.5초 내 |
| `http_req_failed`        | < 0.5% | 거의 모든 요청 성공 |

threshold 위반 시 k6 process exit code != 0 → Job 실패 처리.

## 결과 확인

```bash
kubectl -n load-test logs job/k6-opensearch-search | tail -50
```

마지막 summary 표 예:
```
http_req_duration..............: avg=124ms  min=15ms med=89ms max=2.1s
                                  p(95)=386ms p(99)=974ms
http_req_failed................: 0.21% ✓ 24    ✗ 11354
```

대시보드: `http://<grafana>/d/lt-opensearch` → "OS-02 Heavy Search" 패널.

## 실패 신호

| 증상 | 원인 | 해결 |
|------|------|------|
| `p(95) > 500ms` threshold 실패 | OS 노드 saturation | OS heap/CPU 확인, replicas 증설 |
| 모든 요청 0 result | 인덱스 비어있음 | flog 가동 후 5~10분 대기 |
| `connection refused` | OS 미가동 / 잘못된 URL | `OPENSEARCH_URL` 확인 |
| OOMKilled | k6 프로세스 메모리 초과 | `limits.memory: 1Gi` → `2Gi` 상향 |

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/OS-02-k6-heavy-search/
```
