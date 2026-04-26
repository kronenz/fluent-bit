# FB-01 ~ FB-07 — fluent-bit ingest pipeline

flog 가 stdout 으로 합성 JSON 로그를 발행 → kubelet 이 컨테이너 로그
파일로 기록 → fluent-bit DaemonSet 이 tail input 으로 읽어 OpenSearch 로
전송. 이 시나리오 그룹은 *pipeline 자체* 가 부하 대상이며, 별도의 Job 이
없습니다 — `10-load-generators/flog-loader.yaml` 가동만 하면 됩니다.

| ID | 이름 | 측정 포인트 |
|----|------|-------------|
| FB-01 | sustained ingest        | input rate, buffer fill, output retry |
| FB-02 | high rate burst         | DaemonSet CPU spike, output queue depth |
| FB-04 | back-pressure (OS slow) | filesystem buffer 사용량, retry/drop |
| FB-05 | parser failure          | parser_dropped_records_total |
| FB-07 | DaemonSet restart       | offset DB 의 파일 오프셋 보존 검증 |

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| fluent-bit DaemonSet | `kubectl -n kube-system get ds fluent-bit` | DESIRED=NODES |
| OpenSearch 가동 | `kubectl -n monitoring get pod -l app.kubernetes.io/name=opensearch` | Running |
| opensearch-creds Secret | `kubectl -n monitoring get secret opensearch-creds` | exists |
| logs-fb-* index template | `curl ${OPENSEARCH_URL}/_index_template/logs-fb` | (optional) |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/10-load-generators/flog-loader.yaml
```

운영 부하 (10 replicas):
```bash
kubectl -n load-test scale deploy/flog-loader --replicas=10
```

## 결과 확인

| 위치 | 무엇을 보나 |
|------|-------------|
| `http://<grafana>/d/lt-fluent-bit` FB-01 패널 | input rate, output rate, drop rate |
| `kubectl -n kube-system logs ds/fluent-bit \| grep -i 'storage'` | filesystem buffer 사용 |
| `curl ${OPENSEARCH_URL}/_cat/indices/logs-fb-*` | 시간 흐름에 따른 doc count 증가 |
| `kubectl -n kube-system top pod -l app.kubernetes.io/name=fluent-bit` | DaemonSet CPU/MEM |

## 기대 결과

| 지표 | 기본 (3 replicas) | 운영 (10 replicas) |
|------|---------------------|---------------------|
| 발생 line rate | ~ 30,000 lines/s | ~ 100,000 lines/s |
| DaemonSet input rate | ~ 발생 rate 와 일치 | ~ 발생 rate 와 일치 |
| OS doc count 증가 | ~ 30k/s | ~ 100k/s |
| drop rate | 0 | 0 (정상) / >0 (back-pressure) |
| fluent-bit CPU 사용 | < 50% req | < 80% req |

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/10-load-generators/flog-loader.yaml
```
