# OOM 방지 튜닝 가이드

## OOM이 발생하는 이유

Fluent Bit에서 Out-of-Memory (OOM) 문제는 **Input 속도가 Output 속도보다 빠를 때** 발생합니다.

### 문제 시나리오

```
시간흐름 →

Input 속도  ════════════════════════════════════════════
             ↓ ↓ ↓ (로그 수신 속도: 빠름)

Memory      ┌────────────────────────────────────────┐
Buffer      │  청크 1: 10MB                           │
            │  청크 2: 10MB                           │
            │  청크 3: 10MB                           │
            │  청크 4: 10MB                           │
            │  청크 5: 10MB  ← 버퍼 계속 증가...      │
            │  ...                                    │
            └────────────────────────────────────────┘
                 256MB limit 도달 → OOM Killed!

Output 속도  ═════ (로그 전송 속도: 느림)
             ↓ ↓ ↓
```

**원인:**
- 네트워크 지연으로 OpenSearch 전송 느림
- 대량 로그 burst 발생
- Output buffer size가 너무 작음

**결과:**
- Fluent Bit Pod이 메모리 부족으로 종료 (OOMKilled)
- 로그 손실 발생
- 서비스 불안정

## 4계층 방어 전략

OOM을 방지하기 위해 4가지 레이어에서 방어합니다:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: ClusterInput memBufLimit (Backpressure)          │
│  ├─ Input에서 메모리 사용량이 10MB를 초과하면              │
│  └─ 로그 수신을 일시 중단 (Input은 느려지지만 메모리 보호) │
│                                                             │
│  ↓ (버퍼에서 전송 대기)                                    │
│                                                             │
│  Layer 2: ClusterFluentBitConfig storage (파일시스템)      │
│  ├─ 메모리 한계 도달 시 디스크 파일에 저장                │
│  ├─ maxChunksUp: 128 (메모리에 올릴 최대 청크 수)          │
│  ├─ backlogMemLimit: 5M (백로그 메모리 제한)              │
│  └─ 디스크는 메모리보다 훨씬 크므로 안정성 향상           │
│                                                             │
│  ↓ (처리 대기)                                              │
│                                                             │
│  Layer 3: ClusterFilter Throttle (속도 제한)               │
│  ├─ 초당 처리량을 1000건으로 제한                          │
│  ├─ OpenSearch 부하 분산                                   │
│  └─ 버퍼 증가 속도 자체를 낮춤                            │
│                                                             │
│  ↓ (출력)                                                   │
│                                                             │
│  Layer 4: Pod resource limits (최후의 방어선)              │
│  ├─ limits.memory: 256Mi                                    │
│  └─ 모든 방어가 실패했을 때 Pod을 강제 종료               │
│     (로그 손실이 발생하지만 노드 영향 최소화)              │
└─────────────────────────────────────────────────────────────┘
```

## ClusterFluentBitConfig service.storage 상세 설명

ClusterFluentBitConfig는 **서비스 레벨의 버퍼 설정**을 정의하며, OOM 방지의 핵심입니다.

### storage.path와 flb-storage 볼륨의 관계

```yaml
# infra/fluent-bit-operator/values.yaml (Helm)
fluentbit:
  volumes:
    - name: flb-storage
      hostPath:
        path: /var/log/flb-storage/        # ← 노드의 실제 경로
        type: DirectoryOrCreate
  volumeMounts:
    - name: flb-storage
      mountPath: /var/log/flb-storage/     # ← Pod 내부 경로

---

# pipeline/cluster-fluentbit-config.yaml (CRD)
spec:
  service:
    storage:
      path: /var/log/flb-storage/          # ← 반드시 일치해야 함!
      sync: normal
      maxChunksUp: 128
      backlogMemLimit: "5M"
      deleteIrrecoverableChunks: "on"
```

**중요:**
- Helm의 volumeMounts.mountPath와 ClusterFluentBitConfig의 storage.path는 반드시 일치
- 이 경로에 실제 파일이 저장되어 메모리 부하 완화

### maxChunksUp 조정 가이드

`maxChunksUp`은 메모리에 올릴 최대 청크 수를 제한합니다.

```yaml
spec:
  service:
    storage:
      maxChunksUp: 128  # ← 조정 포인트
```

| 값 | 메모리 사용량 | 용도 | 주의사항 |
|----|-------------|------|---------|
| 64 | ~64MB | 메모리 부족 환경 | 처리량 감소 가능 |
| 128 | ~128MB | 기본값 (권장) | 균형잡힌 설정 |
| 256 | ~256MB | 대량 로그 환경 | 메모리 충분 필요 |

**조정:**
- OOM 발생: 64로 축소
- 로그 손실 발생: 128→256으로 증가 (메모리 여유 있을 때)

### backlogMemLimit 조정 가이드

`backlogMemLimit`는 백로그 큐의 메모리 제한입니다.

```yaml
spec:
  service:
    storage:
      backlogMemLimit: "5M"  # ← 조정 포인트
```

| 값 | 설명 |
|----|------|
| 5M | 기본값, 일반적인 환경 |
| 10M | 메모리 여유 있고 대량 로그 처리 필요 시 |
| 2M | 메모리 부족 상황 |

### deleteIrrecoverableChunks 역할

복구 불가능한 청크를 자동으로 삭제하여 디스크 낭비 방지합니다.

```yaml
spec:
  service:
    storage:
      deleteIrrecoverableChunks: "on"  # ← 항상 "on"
```

**역할:**
- 전송 실패한 로그 (재시도 불가)는 자동 삭제
- 디스크 사용량 관리
- 무한 증가 방지

### emitterMemBufLimit과 emitterStorageType

multiline 파서(Emitter)의 메모리 관리:

```yaml
spec:
  service:
    emitterMemBufLimit: "50M"        # multiline 에미터 메모리 제한
    emitterStorageType: filesystem   # memory 대신 filesystem 사용
```

**설정:**
- `emitterMemBufLimit: "50M"`: multiline 에미터의 메모리 제한
- `emitterStorageType: filesystem`: 메모리 부족 시 디스크 사용 (OOM 방지 핵심)

---

## 파라미터 상세 설명 및 권장값

### Service 레벨 (ClusterFluentBitConfig spec.service)

| 파라미터 | 기본값 | 권장값 | 설명 | 조정 시기 |
|---------|--------|--------|------|---------|
| `storage.path` | - | `/var/log/flb-storage/` | 파일시스템 버퍼 저장 경로 (필수) | 한 번만 설정 |
| `storage.sync` | normal | normal | 디스크 동기화 모드 | 거의 변경 불필요 |
| `storage.maxChunksUp` | 128 | 64~256 | 메모리에 올릴 최대 청크 수 | OOM 발생 시 축소 |
| `storage.backlogMemLimit` | 5M | 5M~10M | 백로그 메모리 제한 | 메모리 상황에 따라 조정 |
| `storage.deleteIrrecoverableChunks` | off | on | 복구 불가 청크 삭제 | 항상 "on" 권장 |
| `emitterMemBufLimit` | - | 50M | multiline 에미터 메모리 제한 | 로그 burst 시 증가 |
| `emitterStorageType` | memory | filesystem | 에미터 storage 타입 | filesystem 필수 (OOM 방지) |

### Input 레벨 (ClusterInput spec.tail)

| 파라미터 | 기본값 | 권장값 | 설명 | 조정 시기 |
|---------|--------|--------|------|---------|
| `memBufLimit` | 무제한 | 10MB | Input 버퍼 메모리 제한 | OOM 방지 핵심, 필수 설정 |
| `storageType` | memory | filesystem | 버퍼 저장 타입 | OOM 방지, filesystem 권장 |
| `skipLongLines` | false | true | 비정상 긴 줄 스킵 | boolean 값 |
| `refreshIntervalSeconds` | 60 | 5 | 새 파일 탐색 주기 | 로그 빠른 감지 필요 시 축소 |

**memBufLimit 조정:**
- 기본: 10MB
- 작은 로그: 5MB (메모리 절약)
- 대량 로그: 20MB (손실 방지, 메모리 여유 필요)

### Filter 레벨 (ClusterFilter spec.filters)

| 파라미터 | 기본값 | 권장값 | 설명 | 조정 시기 |
|---------|--------|--------|------|---------|
| Throttle Rate | - | 1000 | 초당 허용 레코드 수 | 로그 과부하 시 축소 |
| Throttle Window | - | 5 | 제한 윈도우 크기 | 거의 변경 불필요 |
| Throttle Interval | - | 1s | 체크 간격 | 거의 변경 불필요 |

**Throttle Rate 조정:**
- 1000건/초: 기본값 (일반 환경)
- 500건/초: 대량 로그 (OOM 위험)
- 2000건/초: 메모리 충분, 빠른 처리 필요

### Output 레벨 (ClusterOutput spec.opensearch)

| 파라미터 | 기본값 | 권장값 | 설명 | 조정 시기 |
|---------|--------|--------|------|---------|
| `bufferSize` | 4KB | 5MB | HTTP 응답 버퍼 | 대량 로그 처리 시 증가 |
| `workers` | 0 (1) | 2 | 병렬 전송 워커 수 | 처리량 증가 필요 시 |
| `Retry_Limit` | 1 | 3 | 재시도 횟수 | 네트워크 불안정 시 증가 |

### Pod 리소스 제한 (infra/fluent-bit-operator/values.yaml)

| 파라미터 | 기본값 | 권장값 | 설명 |
|---------|--------|--------|------|
| `resources.requests.memory` | 128Mi | 128Mi | 최소 메모리 요청 |
| `resources.limits.memory` | 256Mi | 256Mi~512Mi | 최대 메모리 (이를 초과하면 OOMKilled) |

---

## 시나리오별 권장 설정

### 시나리오 1: 소량 로그 (< 100건/초)

일반적인 서비스 로그량입니다.

**설정:**
```yaml
# ClusterFluentBitConfig
spec:
  service:
    storage:
      maxChunksUp: 64
      backlogMemLimit: "5M"
    emitterMemBufLimit: "50M"
    emitterStorageType: filesystem

# ClusterInput
spec:
  tail:
    memBufLimit: "5MB"
    storageType: filesystem

# ClusterFilter
spec:
  filters:
    - throttle:
        rate: 1000
```

**Pod 리소스:**
```yaml
resources:
  requests:
    memory: 64Mi
  limits:
    memory: 128Mi
```

### 시나리오 2: 중량 로그 (100~1000건/초)

여러 서비스가 함께 로그를 발생하는 경우입니다.

**설정:**
```yaml
# ClusterFluentBitConfig
spec:
  service:
    storage:
      maxChunksUp: 128
      backlogMemLimit: "10M"
    emitterMemBufLimit: "100M"
    emitterStorageType: filesystem

# ClusterInput
spec:
  tail:
    memBufLimit: "10MB"
    storageType: filesystem
    refreshIntervalSeconds: 5

# ClusterFilter
spec:
  filters:
    - throttle:
        rate: 1000
        window: 5
        interval: "1s"
```

**Pod 리소스:**
```yaml
resources:
  requests:
    memory: 128Mi
  limits:
    memory: 256Mi
```

### 시나리오 3: 대량 로그 (> 1000건/초)

실시간 트랜잭션 로그, 분석 로그 등 대량 처리입니다.

**설정:**
```yaml
# ClusterFluentBitConfig
spec:
  service:
    storage:
      maxChunksUp: 256
      backlogMemLimit: "20M"
    emitterMemBufLimit: "200M"
    emitterStorageType: filesystem
    storage:
      path: /var/log/flb-storage/
      deleteIrrecoverableChunks: "on"
      sync: normal

# ClusterInput
spec:
  tail:
    memBufLimit: "20MB"
    storageType: filesystem
    refreshIntervalSeconds: 3
    skipLongLines: true

# ClusterFilter (Throttle 없음 또는 높은 rate)
spec:
  filters:
    - throttle:
        rate: 5000
        window: 5
        interval: "1s"

# ClusterOutput
spec:
  opensearch:
    bufferSize: "10MB"
    workers: 4
    Retry_Limit: 5
```

**Pod 리소스:**
```yaml
resources:
  requests:
    memory: 256Mi
  limits:
    memory: 512Mi
```

---

## 튜닝 프로세스

### 1단계: 현재 상태 파악

```bash
# Pod 메모리 사용량 모니터링
kubectl top pods -n logging -l app.kubernetes.io/name=fluent-bit

# Fluent Bit 메트릭 확인
kubectl port-forward -n logging POD_NAME 2020:2020
# 브라우저: http://localhost:2020/api/v1/metrics/prometheus
```

### 2단계: 문제 확인

```bash
# OOM 발생 확인
kubectl describe pod -n logging POD_NAME | grep -i "OOMKilled"

# 로그 손실 확인
kubectl logs -n logging POD_NAME | grep -i "failed\|error"
```

### 3단계: 튜닝 적용

**ClusterFluentBitConfig 수정:**
```bash
kubectl edit clusterfluentbitconfig fluent-bit-config
```

변경 사항:
```yaml
spec:
  service:
    storage:
      maxChunksUp: 64      # 기존 128에서 축소
      backlogMemLimit: "10M"  # 기존 5M에서 증가
```

**ClusterInput 수정:**
```bash
kubectl edit clusterinput hostpath-logs
```

변경 사항:
```yaml
spec:
  tail:
    memBufLimit: "5MB"    # 기존 10MB에서 축소
```

### 4단계: 검증

```bash
# Pod 자동 재시작 확인 (몇 초 소요)
kubectl get pods -n logging -w

# 메모리 사용량 모니터링
kubectl top pods -n logging -l app.kubernetes.io/name=fluent-bit --watch

# 로그 확인
kubectl logs -n logging POD_NAME -f
```

### 5단계: 최적화

```bash
# 1주일 이상 모니터링
# - OOM 발생 여부
# - 메모리 사용량 패턴
# - 로그 손실 여부

# 필요시 재조정
```

---

## 모니터링

### Fluent Bit 내장 메트릭

Fluent Bit은 포트 2020에서 메트릭을 제공합니다:

```bash
# Port Forward
kubectl port-forward -n logging POD_NAME 2020:2020

# 메트릭 조회
curl http://localhost:2020/api/v1/metrics/prometheus
```

**주요 메트릭:**
```
# Input 버퍼
fluentbit_input_records_total
fluentbit_input_bytes_total

# Output 버퍼
fluentbit_output_records_total
fluentbit_output_errors_total

# Storage
fluentbit_storage_chunks_count
fluentbit_storage_read_bytes_total
```

### Prometheus 연동 (선택사항)

```yaml
# ClusterFluentBitConfig
spec:
  service:
    httpServer: true
    httpPort: 2020
```

Prometheus scrape config:
```yaml
scrape_configs:
  - job_name: 'fluent-bit'
    static_configs:
      - targets: ['localhost:2020']
    metrics_path: '/api/v1/metrics/prometheus'
```

### kubectl 명령어로 모니터링

```bash
# CPU/Memory 사용량
kubectl top pods -n logging -l app.kubernetes.io/name=fluent-bit

# Pod 상태 및 재시작 횟수
kubectl get pods -n logging -o wide

# 리소스 사용률
kubectl describe node NODE_NAME | grep -A 10 "Allocated resources"
```

---

## 트러블슈팅

### "OOMKilled" 발생 시

1. 메모리 제한 확인:
   ```bash
   kubectl get daemonset -n logging fluent-operator-fluent-bit -o yaml | grep -A 5 "limits:"
   ```

2. storage.path 확인:
   ```bash
   kubectl get clusterfluentbitconfig -o yaml | grep "path:"
   ```

3. maxChunksUp 축소:
   ```bash
   kubectl edit clusterfluentbitconfig fluent-bit-config
   # maxChunksUp: 128 → 64
   ```

4. 디스크 공간 확인:
   ```bash
   df -h /var/log/flb-storage/
   ```

### "로그 손실" 발생 시

1. memBufLimit 확인:
   ```bash
   kubectl get clusterinput hostpath-logs -o yaml | grep "memBufLimit:"
   ```

2. Throttle Rate 확인:
   ```bash
   kubectl get clusterfilter -o yaml | grep "rate:"
   ```

3. Input storageType 확인:
   ```bash
   kubectl get clusterinput hostpath-logs -o yaml | grep "storageType:"
   # filesystem이어야 함
   ```

### "디스크 부족" 발생 시

```bash
# 오래된 인덱스 삭제
kubectl exec -n logging opensearch-cluster-master-0 -- \
  curl -X DELETE http://localhost:9200/app-logs-2025.01.*

# flb-storage 파일 정리
rm -rf /var/log/flb-storage/*
```

---

## 체크리스트

Fluent Bit 배포 전 다음을 확인하세요:

- [ ] ClusterFluentBitConfig.spec.service.storage.path 설정 확인
- [ ] Fluent Bit Helm values에 flb-storage 볼륨 마운트 확인
- [ ] ClusterFluentBitConfig.spec.service.emitterStorageType = filesystem
- [ ] ClusterInput.spec.tail.storageType = filesystem
- [ ] ClusterInput.spec.tail.memBufLimit 설정 (10MB 권장)
- [ ] ClusterFilter의 Throttle 설정 확인
- [ ] Pod resources.limits.memory 설정 (256Mi 이상)
- [ ] 디스크 여유 공간 확인 (/var/log/flb-storage/)

모든 4개 계층이 제대로 구성되어야 OOM을 효과적으로 방지할 수 있습니다.
