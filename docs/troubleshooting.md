# 트러블슈팅 가이드

## 로그가 OpenSearch에 안 보일 때

로그가 OpenSearch에 보이지 않는 경우 다음 체크리스트를 순서대로 따릅니다.

### Step 1: ClusterFluentBitConfig 확인 (가장 먼저!)

**ClusterFluentBitConfig가 없으면 전체 파이프라인이 동작하지 않습니다.**

```bash
# ClusterFluentBitConfig 존재 여부 및 설정 확인
kubectl get clusterfluentbitconfig
kubectl get clusterfluentbitconfig fluent-bit-config -o yaml

# 출력에서 다음을 확인:
# - inputSelector.matchLabels.fluentbit.fluent.io/enabled: "true"
# - filterSelector.matchLabels.fluentbit.fluent.io/enabled: "true"
# - outputSelector.matchLabels.fluentbit.fluent.io/enabled: "true"
# - multilineParserSelector.matchLabels.fluentbit.fluent.io/enabled: "true"
# - service.storage.path: /var/log/flb-storage/ (볼륨 마운트 경로와 일치)
```

**문제:**
- ClusterFluentBitConfig가 없음 → 생성 필요
- inputSelector 등의 라벨 설정 오류 → YAML 수정 후 재적용

### Step 2: 모든 CRD 리소스에 라벨 확인

ClusterFluentBitConfig의 selector와 매칭되도록 모든 CRD 리소스에 라벨이 있어야 합니다.

```bash
# 모든 파이프라인 CRD 리소스 확인
kubectl get clusterinput,clusterfilter,clusteroutput,clustermultilineparser --show-labels

# 출력 예시:
# NAME                                        AGE   LABELS
# clusterinput.fluentbit.fluent.io/hostpath-logs  5m   fluentbit.fluent.io/enabled=true
# clusterfilter.fluentbit.fluent.io/add-metadata  5m   fluentbit.fluent.io/enabled=true
# clusteroutput.fluentbit.fluent.io/opensearch-output  5m   fluentbit.fluent.io/enabled=true
```

**문제:**
- 라벨이 없거나 다름 → 모든 CRD에 `fluentbit.fluent.io/enabled=true` 라벨 추가:
  ```bash
  kubectl label clusterinput hostpath-logs fluentbit.fluent.io/enabled=true --overwrite
  kubectl label clusterfilter add-metadata fluentbit.fluent.io/enabled=true --overwrite
  kubectl label clusteroutput opensearch-output fluentbit.fluent.io/enabled=true --overwrite
  kubectl label clustermultilineparser multiline-java-log4j2-json fluentbit.fluent.io/enabled=true --overwrite
  ```

### Step 3: 로그 파일 존재 여부 확인

Fluent Bit가 읽을 로그 파일이 실제로 노드에 존재하는지 확인합니다.

```bash
# Fluent Bit Pod 확인 (로그를 읽을 노드 선택)
kubectl get pods -n logging -o wide
# NODE 컬럼에서 어느 노드에서 실행 중인지 확인

# 해당 노드에 SSH 접속하여 로그 파일 확인
ssh USER@NODE_IP
ls -la /var/log/YOUR_NAMESPACE/
# app*.log 패턴의 파일이 있는지 확인

cat /var/log/YOUR_NAMESPACE/app.log
# JSON 형식의 로그가 기록되어 있는지 확인
```

**문제:**
- 로그 파일이 없음 → 애플리케이션 Pod이 로그를 기록하지 않음
  - Pod이 Running 상태인지 확인
  - initContainer가 정상적으로 실행되었는지 확인
  - securityContext 확인
- 로그 파일이 있지만 내용이 없음 → 애플리케이션의 Log4j2 설정 확인

### Step 4: Fluent Bit Pod 로그 확인

Fluent Bit이 파일을 감지하고 파싱했는지 확인합니다.

```bash
# Fluent Bit Pod 로그 확인
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=100

# 로그에서 다음을 확인:
# 1. Input 플러그인이 파일을 감지했는가?
#    "[input] tail: /var/log/YOUR_NAMESPACE/app.log" 메시지 확인
#
# 2. multiline 파서 오류가 없는가?
#    "Error" 또는 "multiline" 관련 메시지 확인
#
# 3. Lua 스크립트 오류가 없는가?
#    "Lua" 또는 "script" 관련 오류 확인
#
# 4. OpenSearch 연결에 문제가 없는가?
#    "output_opensearch" 또는 "failed to send" 메시지 확인

# 특정 Pod의 로그를 더 자세히 확인
kubectl logs -n logging POD_NAME -f
```

**문제:**
- "[input] tail: /var/log/... 파일을 찾을 수 없음" → Step 3 다시 확인
- "multiline parser error" → ClusterMultilineParser의 regex 문법 확인
- "Lua script error" → Lua ConfigMap 존재 여부 및 스크립트 문법 확인
- "Connection refused" → OpenSearch Pod이 Running인지 확인

### Step 5: OpenSearch 인덱스 확인

OpenSearch에 데이터가 실제로 저장되었는지 확인합니다.

```bash
# OpenSearch Pod 접속
kubectl exec -n logging opensearch-cluster-master-0 -- bash

# 인덱스 목록 확인 (curl 사용, 인증 불필요)
curl -s http://localhost:9200/_cat/indices?v
# app-logs-YYYY.MM.DD 형식의 인덱스가 있는지 확인

# 특정 인덱스의 문서 수 확인
curl -s http://localhost:9200/app-logs-*/_count | jq

# 실제 문서 조회
curl -s 'http://localhost:9200/app-logs-*/_search?pretty&size=5'
# 로그 문서가 보이는지, 필드 구조가 올바른지 확인
```

**문제:**
- app-logs-* 인덱스가 없음 → Step 1~4를 다시 확인
- 인덱스는 있지만 문서가 없음→ Fluent Bit의 output 설정 확인
- 문서는 있지만 필드가 이상함 → multiline 파서 또는 Lua 스크립트 확인

### Step 6: 네트워크 연결 확인

Fluent Bit Pod에서 OpenSearch로의 네트워크 연결을 테스트합니다.

```bash
# Fluent Bit Pod 접속
kubectl exec -n logging -it POD_NAME -- bash

# OpenSearch 연결 테스트
curl -v http://opensearch-cluster-master.logging.svc.cluster.local:9200/_cluster/health
# Connected와 HTTP 200 응답 확인

# DNS 해석 확인
nslookup opensearch-cluster-master.logging.svc.cluster.local
# NXDOMAIN이 아닌 IP가 반환되는지 확인
```

**문제:**
- "Connection refused" → OpenSearch Pod이 Running인지 확인, 포트 확인
- "Name resolution failed" → DNS 설정 확인, Service 이름 확인
- "HTTP 5xx" → OpenSearch 상태 확인

---

## Fluent Bit Pod OOM 재시작 시

Fluent Bit Pod이 OOMKilled로 반복해서 재시작되는 경우 대응 방법입니다.

### 증상 확인

```bash
# Pod 상태 확인
kubectl get pods -n logging -l app.kubernetes.io/name=fluent-bit
# Status가 OOMKilled 또는 CrashLoopBackOff

# 상세 정보 확인
kubectl describe pod -n logging POD_NAME
# Events에서 "OOMKilled" 메시지 확인
# Container State의 "Last State: Terminated (OOMKilled)" 확인

# Pod 로그 마지막 부분 확인
kubectl logs -n logging POD_NAME --tail=50
```

### 해결 방법

#### 1단계: ClusterFluentBitConfig의 storage 설정 확인

```bash
kubectl get clusterfluentbitconfig fluent-bit-config -o yaml
```

다음 설정을 확인하세요:

```yaml
spec:
  service:
    storage:
      path: /var/log/flb-storage/                  # 반드시 설정
      sync: normal
      maxChunksUp: 128                             # 메모리에 올릴 최대 청크 수
      backlogMemLimit: "5M"                        # 백로그 메모리 제한
      deleteIrrecoverableChunks: "on"
    emitterMemBufLimit: "50M"
    emitterStorageType: filesystem                 # memory 대신 filesystem 사용
```

**문제:**
- storage.path가 설정되지 않음 → 추가 필요
- emitterStorageType이 memory → filesystem으로 변경

#### 2단계: Fluent Bit Operator의 flb-storage 볼륨 확인

Fluent Bit DaemonSet이 flb-storage 볼륨을 마운트하고 있는지 확인합니다.

```bash
kubectl get daemonset -n logging -o yaml | grep -A 20 "flb-storage"
# volumeMounts에 /var/log/flb-storage/ 마운트가 있는지 확인

# 또는 Pod 상세 정보
kubectl exec -n logging POD_NAME -- df -h /var/log/flb-storage/
# 디스크 사용량이 정상 범위인지 확인
```

**문제:**
- flb-storage 볼륨이 마운트되지 않음 → Helm values에서 설정 추가 필요
  ```yaml
  fluentbit:
    volumes:
      - name: flb-storage
        hostPath:
          path: /var/log/flb-storage/
          type: DirectoryOrCreate
    volumeMounts:
      - name: flb-storage
        mountPath: /var/log/flb-storage/
  ```

#### 3단계: ClusterInput의 memBufLimit 조정

```bash
kubectl get clusterinput hostpath-logs -o yaml
```

다음 설정을 확인하고 필요하면 조정합니다:

```yaml
spec:
  tail:
    memBufLimit: "10MB"                      # Input 버퍼 제한
    storageType: filesystem                  # memory 대신 filesystem
    skipLongLines: true
```

**조정 방법:**
- 현재 값: 10MB
- 메모리 부족 시: 5MB로 축소
- 로그 손실 시: 20MB로 증가

#### 4단계: Pod의 리소스 제한 조정

Fluent Bit Pod의 메모리 제한을 확인하고 필요하면 증가시킵니다.

```bash
# 현재 설정 확인
kubectl get daemonset -n logging fluent-operator-fluent-bit -o yaml | grep -A 10 "resources:"
```

**조정:**
```yaml
resources:
  requests:
    memory: 128Mi
  limits:
    memory: 256Mi  # 512Mi로 증가하거나 필요에 따라 조정
```

Helm values에서 수정 후 업그레이드:
```bash
helm upgrade fluent-bit-operator fluent/fluent-operator \
  -n logging \
  -f infra/fluent-bit-operator/values.yaml
```

#### 5단계: Throttle Filter 적용

ClusterFilter에서 로그 처리 속도를 제한합니다.

```yaml
spec:
  filters:
    - throttle:
        rate: 500                  # 초당 500건으로 제한 (기본: 1000)
        window: 5
        interval: "1s"
        printStatus: true
```

조정 후 적용:
```bash
kubectl apply -f pipeline/cluster-filter-modify.yaml
```

---

## 권한 문제 진단

로그 파일 쓰기 권한 문제를 진단하는 방법입니다.

### 1단계: Pod의 securityContext 확인

```bash
kubectl get deployment -n YOUR_NAMESPACE YOUR_SERVICE_NAME -o yaml | grep -A 5 "securityContext"
```

확인 사항:
```yaml
securityContext:
  runAsUser: 1000        # 반드시 설정 (root가 아님)
  runAsGroup: 1000       # 권장
  allowPrivilegeEscalation: false
```

**문제:**
- runAsUser가 설정되지 않음 → 추가 필요
- runAsUser: 0 (root) → 1000으로 변경

### 2단계: 로그 디렉토리 소유자 확인

```bash
# 노드에 SSH 접속
ssh USER@NODE_IP

# 디렉토리 소유자 확인
ls -la /var/log/YOUR_NAMESPACE/
# Uid=1000, Gid=1000 확인
```

**문제:**
- 소유자가 root → initContainer에서 chown 1000:1000 실행하도록 설정

### 3단계: initContainer 실행 확인

```bash
kubectl logs -n YOUR_NAMESPACE POD_NAME -c fix-log-dir-ownership
```

**출력 예시:**
```
# 성공: 출력 없음 (정상)

# 실패: 오류 메시지
chown: /var/log/YOUR_NAMESPACE: Permission denied
```

**문제:**
- initContainer가 runAsUser: 0이 아님 → securityContext 추가 필요

### 4단계: Pod에서 파일 쓰기 테스트

```bash
kubectl exec -n YOUR_NAMESPACE POD_NAME -- sh
$ touch /var/log/YOUR_NAMESPACE/test.txt
$ ls -la /var/log/YOUR_NAMESPACE/test.txt
```

**문제:**
- "Permission denied" 오류 → 소유권 다시 확인

---

## 디버깅 명령어 모음

### Kubernetes 기본 명령어

```bash
# 모든 네임스페이스 확인
kubectl get ns

# logging 네임스페이스의 Pod 확인
kubectl get pods -n logging -o wide
kubectl get pods -n logging -o yaml | less

# Fluent Bit Pod 상세 정보
kubectl describe pod -n logging POD_NAME
kubectl logs -n logging POD_NAME
kubectl logs -n logging POD_NAME -f                  # 실시간 로그
kubectl logs -n logging POD_NAME --tail=200          # 마지막 200줄
kubectl logs -n logging POD_NAME --previous          # 재시작 전 로그

# Pod 접속
kubectl exec -n logging -it POD_NAME -- bash
kubectl exec -n logging POD_NAME -- ls -la /var/log

# 리소스 확인
kubectl top pods -n logging                          # CPU/Memory 사용량
kubectl top nodes                                    # 노드 리소스
```

### Fluent Bit 관련 명령어

```bash
# Fluent Bit HTTP API (내부 메트릭)
# Pod에서 2020 포트로 접속
kubectl port-forward -n logging POD_NAME 2020:2020
# 로컬 브라우저: http://localhost:2020/api/v1/metrics
# 또는 curl: curl http://localhost:2020/api/v1/metrics/prometheus

# Fluent Bit 설정 확인
kubectl exec -n logging POD_NAME -- cat /fluent-bit/etc/fluent-bit.conf
```

### OpenSearch 관련 명령어

```bash
# OpenSearch Pod 접속
kubectl exec -n logging -it opensearch-cluster-master-0 -- bash

# 클러스터 상태 확인
curl -s http://localhost:9200/_cluster/health | jq

# 노드 정보
curl -s http://localhost:9200/_nodes | jq '.nodes | keys'

# 인덱스 목록
curl -s http://localhost:9200/_cat/indices?v

# 인덱스 매핑 확인
curl -s http://localhost:9200/app-logs-*/_mapping | jq

# 문서 조회
curl -s 'http://localhost:9200/app-logs-*/_search?size=10&pretty'

# 특정 필드로 검색
curl -s 'http://localhost:9200/app-logs-*/_search' -H 'Content-Type: application/json' -d '{
  "query": {
    "term": {
      "namespace": "your-service"
    }
  }
}' | jq

# 인덱스 삭제 (테스트용)
curl -X DELETE http://localhost:9200/app-logs-*
```

### 노드 로그 확인

```bash
# 노드에 SSH 접속
ssh USER@NODE_IP

# 로그 파일 확인
ls -la /var/log/YOUR_NAMESPACE/
cat /var/log/YOUR_NAMESPACE/app.log | head -20
tail -f /var/log/YOUR_NAMESPACE/app.log                # 실시간 모니터링

# Fluent Bit storage 폴더 확인
ls -la /var/log/flb-storage/
du -sh /var/log/flb-storage/                          # 용량 확인

# 권한 확인
stat /var/log/YOUR_NAMESPACE/
```

---

## 빠른 체크리스트

1. ClusterFluentBitConfig 존재? → `kubectl get clusterfluentbitconfig`
2. 모든 CRD 리소스에 `fluentbit.fluent.io/enabled=true` 라벨? → `kubectl get clusterinput --show-labels`
3. 로그 파일이 노드에 존재? → `ls -la /var/log/YOUR_NAMESPACE/`
4. Fluent Bit Pod이 Running? → `kubectl get pods -n logging`
5. Fluent Bit 로그에 오류? → `kubectl logs -n logging POD_NAME`
6. OpenSearch에 인덱스 생성됨? → `curl http://localhost:9200/_cat/indices?v`
7. OpenSearch에 문서 존재? → `curl http://localhost:9200/app-logs-*/_count`

문제를 찾지 못하면 위의 명령어들을 차례대로 실행하며 디버깅하세요.
