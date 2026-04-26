# FB-OOM-tuning — fluent-bit memory limit 발견

concept 의 "fluent-bit OOMKilled 한계 튜닝" 시나리오. flog 부하를 단계별로
ramp 하면서 fluent-bit DaemonSet pod 의 메모리 피크를 측정 → 운영 환경에
배포할 안전 limit 도출.

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| flog Deployment 가동 (1 replica 이상) | `kubectl -n load-test get deploy/flog-loader` | exists |
| fluent-bit DaemonSet | `kubectl -n monitoring get ds -A \| grep fluent-bit` | DESIRED=NODES |
| Prometheus 도달 | curl ${PROMETHEUS_URL}/-/ready | OK |
| kube-burner ServiceAccount | (flog scale 권한 재사용) | exists |

## 실행 (자동 ramp)

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/FB-OOM-tuning/
kubectl -n load-test logs -f job/fb-oom-tuning
```

자동 ramp 4단계 (총 18분):

| Stage | flog replicas | 지속 | 의미 |
|-------|---------------|------|------|
| baseline | 1 | 3m | idle 상태 측정 |
| normal | 3 | 5m | 운영 정상 부하 (3 × 10k lines/s = 30k lines/s) |
| high | 10 | 5m | 운영급 부하 (100k lines/s) |
| peak | 30 | 5m | burst 부하 (300k lines/s) |

각 stage 종료 시 fluent-bit pod RSS 피크를 Prometheus 에서 조회해 출력.

## 수동 모니터링 (병렬 권장)

```bash
# 다른 터미널에서 — 1초 간격 fluent-bit 메모리 watch
watch -n 1 'kubectl -n monitoring top pod -l app.kubernetes.io/name=fluent-bit'
```

또는 직접 Prometheus 쿼리:
```bash
curl -s "${PROMETHEUS_URL}/api/v1/query?query=container_memory_working_set_bytes%7Bnamespace%3D%22monitoring%22%2Cpod%3D~%22fluent-bit.*%22%7D" | jq
```

## 기대 결과 (예시)

| Stage | flog repl | 발생 line/s | fluent-bit RSS peak |
|-------|-----------|-------------|---------------------|
| baseline | 1 | 10k | 60 ~ 80 MB |
| normal | 3 | 30k | 120 ~ 200 MB |
| high | 10 | 100k | 300 ~ 500 MB |
| peak | 30 | 300k | 800 ~ 1500 MB (또는 OOMKilled) |

## 결과 해석

- **peak 단계에서 OOMKilled 발생** → 현재 limit 부족. limit = (high RSS) × 1.5.
- **peak 까지 안정** → 현재 limit 충분. 더 높은 burst 시나리오 (60 replicas) 추가.
- **drop 발생 (output_proc_drops_total > 0)** → mem_buf_limit 조정 필요.

## 운영 limit 결정 공식

```
운영 limit = max(
  high stage RSS × 1.5,         # 예상 정상 부하의 1.5배 여유
  peak stage RSS × 1.2          # burst 흡수 (1.2배 마진)
)
```

예) high RSS 400 MB, peak RSS 1200 MB → `max(600, 1440) = 1440 MB`. 1.5GB limit 권장.

## fluent-bit 설정 튜닝 (limit 변경 후 추가)

| 설정 | 영향 | 권장 |
|------|------|------|
| `Mem_Buf_Limit` | input plugin 메모리 cap | limit × 0.7 |
| `Storage.path` | filesystem buffer 위치 | hostPath PVC 사용 |
| `Storage.max_chunks_up` | 메모리에 유지할 chunk 수 | mem_buf_limit / chunk_size |
| `Flush` | output 주기 | 1s 기본 (낮추면 메모리 ↓) |

## 결과 확인

```bash
# Job 출력
kubectl -n load-test logs job/fb-oom-tuning

# fluent-bit OOMKilled history
kubectl -n monitoring describe pod -l app.kubernetes.io/name=fluent-bit | grep -A3 'Last State'

# fluent-bit drop 확인
curl -s "${PROMETHEUS_URL}/api/v1/query?query=fluentbit_output_proc_dropped_records_total" | jq
```

대시보드: `http://<grafana>/d/lt-fluent-bit` → "FB-OOM" 패널 (구현 시)

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/FB-OOM-tuning/
# flog 는 Job 마지막에 replicas=3 으로 자동 복귀
```
