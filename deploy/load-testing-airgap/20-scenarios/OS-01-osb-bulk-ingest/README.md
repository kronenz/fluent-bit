# OS-01 — opensearch-benchmark bulk-ingest

OpenSearch 공식 부하 도구 (rally fork) 로 표준 워크로드를 실행해 인덱싱
처리량/지연/에러율을 측정.

## 사전 조건

| 항목 | 확인 명령 | 정상값 |
|------|-----------|--------|
| OpenSearch 가동 | `kubectl -n monitoring get pods -l app.kubernetes.io/name=opensearch` | Running |
| OS REST API 도달 | `kubectl -n monitoring exec opensearch-lt-node-0 -- curl -s localhost:9200/_cluster/health` | `"status":"green"` 또는 `"yellow"` |
| lt-config 적용 | `kubectl -n load-test get cm lt-config` | exists |
| security 활성 시 | lt-config 의 `OS_BASIC_AUTH_USER/PASS` 채움 | (admin/admin 등) |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/
```

## 진행 상황

```bash
kubectl -n load-test get pods -l scenario=OS-01 -w
kubectl -n load-test logs -f -l scenario=OS-01
```

진행 단계 (정상):
1. `OSB pre-flight diagnostic` 출력
2. `[1/4] opensearch-benchmark version` → `2.x.y`
3. `[2/4] Workload directory` → 파일 목록
4. `[3/4] OpenSearch reachability` → `_cluster/health` JSON
5. `[4/4] Disk + memory`
6. `OSB execution` → 진행률 막대
7. `OSB SUCCESS` → result.json 첫 200 줄

## 결과 확인

| 방법 | 명령 / 위치 |
|------|-------------|
| Job 종료 코드 | `kubectl -n load-test get job opensearch-benchmark -o jsonpath='{.status.succeeded}'` (`1` = 성공) |
| 로그 (전문)    | `kubectl -n load-test logs job/opensearch-benchmark` |
| result.json   | 위 로그의 마지막 섹션 (Job 종료 시 출력) |
| 인덱스 생성   | `kubectl -n monitoring exec opensearch-lt-node-0 -- curl -s localhost:9200/_cat/indices/geonames` |
| Grafana       | `http://<grafana>/d/lt-opensearch` → "OS-01 OSB" 패널 |

## 기대 결과

| 지표 | TEST_MODE=true (smoke) | TEST_MODE=false (운영) |
|------|------------------------|------------------------|
| Job 종료 시간 | 30 초 ~ 2 분 | 워크로드별 (geonames: 5~15분) |
| 인덱싱 docs | 1,000 | geonames: 11.4M |
| Throughput | 200 ~ 1,000 docs/s | 5,000 ~ 50,000 docs/s |
| p95 latency | < 50 ms | < 500 ms |
| Job exit code | 0 | 0 |

## 실패 신호 / 흔한 원인

| 증상 | 원인 | 해결 |
|------|------|------|
| `FATAL: cannot reach ${OPENSEARCH_URL}` | DNS / Service 미존재 | `OPENSEARCH_URL` 의 service 이름이 실제 helm release 와 일치하는지 확인 |
| `FATAL: workload not found` | 이미지 손상 또는 잘못된 OSB_WORKLOAD | `kubectl exec` 로 `/opt/osb-workloads` 확인 |
| `OOMKilled` (Job pod) | 메모리 한도 초과 | `limits.memory: 4Gi` → `8Gi` 추가 상향 |
| `mapper_parsing_exception` | 기존 인덱스 mapping 충돌 | `curl -X DELETE $OPENSEARCH_URL/geonames` 후 재실행 |
| `unauthorized` | security plugin 인증 누락 | lt-config 의 `OS_BASIC_AUTH_USER/PASS` 설정 |
| 진행률 후 stuck (5분 이상) | OS 노드가 헐떡임 | `kubectl -n monitoring top pod`, OS heap 확인 |

자세한 트러블슈팅 → [docs/02-troubleshooting.md](../../docs/02-troubleshooting.md)

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/

# 인덱스도 정리 (다음 실행에서 mapping 충돌 방지)
kubectl -n monitoring exec opensearch-lt-node-0 -- \
  curl -X DELETE http://localhost:9200/geonames
```

## 운영 부하 측정 (TEST_MODE=false)

1. corpus PVC 사전 적재 (geonames 280MB ~ http_logs 80GB)
2. `lt-config` 의 `OSB_TEST_MODE: "false"` 변경
3. `job.yaml` 의 volume `emptyDir` 을 PVC 로 교체:
   ```yaml
   volumes:
     - name: osb-data
       persistentVolumeClaim:
         claimName: osb-corpus-pvc
   ```
4. `limits.memory` 를 `8Gi` 로 상향 권장
