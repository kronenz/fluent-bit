# CHAOS-OS-07 — OpenSearch 노드 장애 회복 시간 측정

| 항목 | 값 |
|------|----|
| 주제 | OpenSearch data/master 노드 강제 종료 시 cluster 회복 |
| 목적 | red → yellow → green 회복 시간이 운영 SLO (10분 이내) 충족하는지 |
| 수행방법 | 자동 — `kubectl delete pod` + `_cluster/health` 5초 폴링 |
| 기대결과 | red < 30s, yellow → green < 10분, 데이터 손실 = 0 |
| 조작변수 | 어떤 노드 (data/master/coord), 동시 장애 수, replica 수 |
| 통제변수 | replica ≥ 1, 노드 수 ≥ 3, indexing 부하 (50% baseline) |

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| OS 노드 ≥ 2 | `kubectl -n monitoring get pod -l app.kubernetes.io/name=opensearch` | ≥ 2 Running |
| 모든 인덱스 replica ≥ 1 | `curl -u admin:admin $OS/_cat/indices?v` | rep 컬럼 ≥ 1 |
| 사전 health green | `curl -u admin:admin $OS/_cluster/health` | `"status":"green"` |
| opensearch-creds Secret | `kubectl -n load-test get secret opensearch-creds` | exists |

⚠ **단일노드 testbed**: replica=0 이라 green 회복 불가. 시나리오 의도된 실패로 동작 — 시나리오 검증 용도로만 적합. 실제 측정은 멀티노드에서.

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/CHAOS-OS-07-node-failure/
kubectl -n load-test logs -f job/chaos-os-07-node-failure
```

## 출력 예시 (멀티노드 정상 회복)

```
[1] pre-kill cluster health
{ "status": "green", "number_of_nodes": 3, ... }

[2] target pod 선정
    → opensearch-lt-data-1

[3] T0 = 1714123456 — kill

[4] cluster 상태 polling (5s 간격, 최대 600s)
  t+5s  status=red
  t+10s status=red
  t+15s status=yellow
  t+30s status=yellow
  ...
  t+180s status=green

=== 결과 ===
RED 진입       : 5 s
YELLOW 진입    : 15 s
GREEN 회복     : 180 s
```

## 운영 SLO

| 지표 | 임계 | 의미 |
|------|------|------|
| RED 진입 | < 30 s | 장애 감지 |
| RED → YELLOW | < 60 s | replica 활성화 |
| YELLOW → GREEN | < 10 분 | shard recovery |
| 데이터 손실 | 0 | replica 가 보존 |

## 회복 시간 단축

| 방법 | 영향 |
|------|------|
| `indices.recovery.max_bytes_per_sec` 상향 | recovery throughput ↑ |
| replica 수 ↑ | 회복 빠르지만 indexing throughput ↓ |
| `cluster.routing.allocation.node_concurrent_recoveries` ↑ | 동시 recovery 수 |
| network bandwidth | 노드 간 데이터 복사 속도 |

## 다른 chaos 변형

| 변형 | 변경 |
|------|------|
| master node 장애 | TARGET_POD_LABEL 변경 (master role pod) |
| 동시 2 노드 장애 | bash 스크립트 수정 (2개 동시 delete) |
| 부하 진행 중 장애 | OS-08 (sustained ingest) 동시 가동 후 chaos |

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/CHAOS-OS-07-node-failure/
```
