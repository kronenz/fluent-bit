# 03. 워크로드 리소스 (Workload Resources)

> **TL;DR**
> - K8s 워크로드는 **Pod**를 기본 단위로, 용도에 따라 Deployment/StatefulSet/DaemonSet/Job/CronJob으로 나뉜다.
> - **Deployment**는 무상태(Stateless), **StatefulSet**은 유상태(Stateful) 워크로드의 표준이다.
> - Pod의 **라이프사이클, Probe, Init Container**를 이해하면 안정적인 서비스 운영이 가능하다.

---

## 1. Pod: 최소 배포 단위

**Pod**는 하나 이상의 컨테이너를 묶은 K8s의 **최소 스케줄링 단위**다.

같은 Pod 내 컨테이너는:
- **네트워크 namespace 공유** (localhost로 통신)
- **스토리지 볼륨 공유** 가능
- 항상 **같은 노드**에 배치

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-container-pod
spec:
  containers:
  - name: app
    image: myapp:1.0
    ports:
    - containerPort: 8080
    volumeMounts:
    - name: shared-data
      mountPath: /app/data
  - name: sidecar-logger
    image: fluentbit:latest
    volumeMounts:
    - name: shared-data
      mountPath: /var/log/app
      readOnly: true
  volumes:
  - name: shared-data
    emptyDir: {}
```

> **실무 팁:** Pod를 직접 만들지 않는다. 항상 Deployment 등 **상위 컨트롤러**를 통해 관리한다.

---

## 2. 워크로드 리소스 비교

| 리소스 | 용도 | Pod 이름 | 스케일링 | 대표 사용처 |
|--------|------|----------|----------|-------------|
| **Deployment** | 무상태 앱 | 랜덤 해시 | 자유롭게 | 웹서버, API 서버 |
| **StatefulSet** | 유상태 앱 | 순서 번호 (0,1,2...) | 순차적 | DB, 메시지 큐 |
| **DaemonSet** | 노드당 1개 | 노드명 포함 | 노드 수 = Pod 수 | 모니터링, 로그 수집 |
| **Job** | 일회성 작업 | 랜덤 해시 | parallelism | 배치 처리, 마이그레이션 |
| **CronJob** | 주기적 작업 | 타임스탬프 포함 | schedule | 백업, 리포트 |

---

## 3. Deployment

### 3-1. 기본 구조

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-api
  labels:
    app: web-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-api
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # 최대 추가 Pod 수
      maxUnavailable: 0     # 최소 가용 Pod 보장
  template:
    metadata:
      labels:
        app: web-api
    spec:
      containers:
      - name: api
        image: web-api:2.1.0
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: "250m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
```

### 3-2. 롤링 업데이트와 롤백

```bash
# 이미지 업데이트 (롤링 업데이트 트리거)
kubectl set image deployment/web-api api=web-api:2.2.0

# 업데이트 상태 확인
kubectl rollout status deployment/web-api

# 롤아웃 히스토리 확인
kubectl rollout history deployment/web-api

# 이전 버전으로 롤백
kubectl rollout undo deployment/web-api

# 특정 리비전으로 롤백
kubectl rollout undo deployment/web-api --to-revision=2
```

---

## 4. StatefulSet

**순서와 고유 ID가 필요한 유상태 워크로드**에 사용한다.

### 특징:
- Pod 이름이 **순서 번호** (app-0, app-1, app-2)
- **순차적 생성/삭제** (0번부터 생성, 역순으로 삭제)
- 각 Pod에 **고유 PVC** 자동 생성 (volumeClaimTemplates)
- **Headless Service**로 개별 Pod DNS 제공

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: "postgres-headless"    # Headless Service 이름
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:              # Pod별 고유 PVC
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: local-storage
      resources:
        requests:
          storage: 50Gi
---
# Headless Service (clusterIP: None)
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
spec:
  clusterIP: None
  selector:
    app: postgres
  ports:
  - port: 5432
```

```bash
# 개별 Pod DNS로 접근 가능
# postgres-0.postgres-headless.default.svc.cluster.local
# postgres-1.postgres-headless.default.svc.cluster.local

nslookup postgres-0.postgres-headless.default.svc.cluster.local
```

---

## 5. DaemonSet

**모든 (또는 특정) 노드에 Pod 1개씩** 배치한다.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: logging
spec:
  selector:
    matchLabels:
      app: fluent-bit
  template:
    metadata:
      labels:
        app: fluent-bit
    spec:
      tolerations:
      - key: node-role.kubernetes.io/control-plane
        effect: NoSchedule          # 마스터 노드에서도 실행
      containers:
      - name: fluent-bit
        image: fluent/fluent-bit:latest
        volumeMounts:
        - name: varlog
          mountPath: /var/log
          readOnly: true
        - name: containers-log
          mountPath: /var/lib/docker/containers
          readOnly: true
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: containers-log
        hostPath:
          path: /var/lib/docker/containers
```

**대표 사용 사례:**
- **로그 수집** (Fluent Bit, Fluentd, Filebeat)
- **모니터링 에이전트** (Node Exporter, Datadog Agent)
- **네트워크 플러그인** (Calico, Cilium)
- **스토리지 데몬** (Ceph, GlusterFS)

---

## 6. Job과 CronJob

### 6-1. Job (일회성 배치 작업)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration
spec:
  backoffLimit: 3              # 실패 시 최대 재시도 횟수
  activeDeadlineSeconds: 600   # 최대 실행 시간 (10분)
  template:
    spec:
      restartPolicy: Never     # Job에서는 Never 또는 OnFailure
      containers:
      - name: migrate
        image: myapp-migration:1.0
        command: ["python", "manage.py", "migrate"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
```

### 6-2. 병렬 Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: parallel-processing
spec:
  completions: 10      # 총 완료해야 할 작업 수
  parallelism: 3       # 동시 실행 Pod 수
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: worker
        image: batch-worker:1.0
```

### 6-3. CronJob (주기적 작업)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-backup
spec:
  schedule: "0 2 * * *"                 # 매일 새벽 2시
  concurrencyPolicy: Forbid             # 이전 작업 미완료 시 건너뜀
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: backup
            image: backup-tool:1.0
            command:
            - /bin/sh
            - -c
            - |
              pg_dump $DATABASE_URL > /backup/db-$(date +%Y%m%d).sql
              echo "Backup completed"
            volumeMounts:
            - name: backup-vol
              mountPath: /backup
          volumes:
          - name: backup-vol
            persistentVolumeClaim:
              claimName: backup-pvc
```

---

## 7. Pod 라이프사이클

```
Pending → Running → Succeeded/Failed
   │         │
   │         ├→ CrashLoopBackOff (재시작 반복)
   │
   └→ Unschedulable (노드 부족, 리소스 부족)
```

| 단계 | 설명 |
|------|------|
| **Pending** | 스케줄링 대기 또는 이미지 다운로드 중 |
| **Running** | 최소 1개 컨테이너 실행 중 |
| **Succeeded** | 모든 컨테이너 정상 종료 (exit 0) |
| **Failed** | 최소 1개 컨테이너 비정상 종료 |
| **Unknown** | 노드와 통신 불가 |

---

## 8. Probe (헬스체크)

### 세 가지 Probe

| Probe | 역할 | 실패 시 동작 |
|-------|------|-------------|
| **livenessProbe** | 컨테이너가 살아있는가? | 컨테이너 **재시작** |
| **readinessProbe** | 트래픽 받을 준비 됐는가? | Service 엔드포인트에서 **제거** |
| **startupProbe** | 초기 구동 완료했는가? | 완료 전까지 다른 Probe **비활성화** |

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      containers:
      - name: app
        image: web-app:1.0
        ports:
        - containerPort: 8080
        # 시작이 느린 앱 (AI 모델 로딩 등)
        startupProbe:
          httpGet:
            path: /healthz
            port: 8080
          failureThreshold: 30       # 30 * 10s = 최대 5분 대기
          periodSeconds: 10
        # 살아있는지 확인
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 0
          periodSeconds: 15
          timeoutSeconds: 3
          failureThreshold: 3
        # 트래픽 받을 준비 확인
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 2
```

**Probe 방식:**

```yaml
# 1. HTTP GET
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080

# 2. TCP Socket
livenessProbe:
  tcpSocket:
    port: 5432

# 3. Exec (명령어 실행)
livenessProbe:
  exec:
    command:
    - cat
    - /tmp/healthy

# 4. gRPC (K8s 1.24+)
livenessProbe:
  grpc:
    port: 50051
```

---

## 9. Init Container

**메인 컨테이너 실행 전에 선행 작업**을 수행하는 컨테이너다.

- 순서대로 실행되며, **모두 성공해야** 메인 컨테이너가 시작됨
- 메인 컨테이너와 **다른 이미지** 사용 가능

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-init
spec:
  initContainers:
  # 1단계: DB가 준비될 때까지 대기
  - name: wait-for-db
    image: busybox:1.36
    command:
    - sh
    - -c
    - |
      until nc -z postgres-headless 5432; do
        echo "Waiting for DB..."
        sleep 2
      done
      echo "DB is ready"
  # 2단계: 설정 파일 다운로드
  - name: download-config
    image: curlimages/curl:latest
    command:
    - sh
    - -c
    - |
      curl -o /config/app.conf http://config-server:8080/config
    volumeMounts:
    - name: config-vol
      mountPath: /config
  containers:
  - name: app
    image: myapp:1.0
    volumeMounts:
    - name: config-vol
      mountPath: /app/config
      readOnly: true
  volumes:
  - name: config-vol
    emptyDir: {}
```

**폐쇄망 활용 사례:**
Init Container로 내부 인증서 서버에서 TLS 인증서를 받아오거나, 내부 패키지 저장소에서 런타임 의존성을 다운로드하는 패턴이 유용하다.

---

## 10. Graceful Shutdown

Pod가 종료될 때 **트래픽 유실 없이 안전하게 종료**하는 설정이다.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: graceful-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: graceful-app
  template:
    metadata:
      labels:
        app: graceful-app
    spec:
      terminationGracePeriodSeconds: 60   # 종료 유예 시간
      containers:
      - name: app
        image: myapp:1.0
        lifecycle:
          preStop:
            exec:
              command:
              - /bin/sh
              - -c
              - |
                echo "Draining connections..."
                sleep 10
                kill -SIGTERM 1
```

```
종료 과정:
1. Pod가 Terminating 상태로 변경
2. Service 엔드포인트에서 제거 (새 트래픽 차단)
3. preStop 훅 실행
4. SIGTERM 전송
5. terminationGracePeriodSeconds 대기
6. SIGKILL 강제 종료
```

---

## 면접 Q&A

### Q1. "Deployment와 StatefulSet의 차이를 설명해주세요."

> **이렇게 대답한다:**
> "**Deployment**는 무상태 앱용으로 Pod 이름이 랜덤이고 어떤 순서로든 생성/삭제할 수 있습니다. **StatefulSet**은 유상태 앱용으로 Pod마다 **고유한 순서 번호**(0, 1, 2)와 **고유 PVC**를 가지며, 순차적으로 생성/삭제됩니다. Headless Service를 통해 `pod-0.service-name`처럼 **개별 Pod에 DNS로 접근**할 수 있어 DB 클러스터의 마스터/슬레이브 구분에 유용합니다."

### Q2. "livenessProbe와 readinessProbe의 차이는?"

> **이렇게 대답한다:**
> "**livenessProbe**가 실패하면 kubelet이 컨테이너를 **재시작**합니다. 데드락 등 복구 불가능한 상태를 감지합니다. **readinessProbe**가 실패하면 Service 엔드포인트에서 **제외**되어 트래픽을 받지 않습니다. DB 연결 끊김 등 일시적 장애 시 유용합니다. 시작이 오래 걸리는 앱은 **startupProbe**를 추가하여 초기화 완료 전에 livenessProbe가 실패하지 않도록 합니다."

### Q3. "Pod가 CrashLoopBackOff 상태인데 어떻게 디버깅하나요?"

> **이렇게 대답한다:**
> "순서대로 확인합니다. 먼저 `kubectl describe pod`로 **이벤트와 상태**를 봅니다. `kubectl logs --previous`로 **이전 크래시의 로그**를 확인합니다. OOMKilled면 **메모리 limit 증가**, ImagePullBackOff면 **이미지 경로나 레지스트리 인증** 확인, CrashLoopBackOff면 **애플리케이션 자체 오류**를 로그에서 찾습니다. 폐쇄망이라면 이미지가 내부 레지스트리에 제대로 적재되었는지도 확인합니다."

```bash
# 디버깅 명령어 모음
kubectl describe pod <pod-name>
kubectl logs <pod-name> --previous
kubectl logs <pod-name> -c <container-name>   # 멀티 컨테이너
kubectl get events --sort-by='.lastTimestamp'
kubectl exec -it <pod-name> -- /bin/sh         # 컨테이너 진입
```

### Q4. "DaemonSet은 언제 사용하나요?"

> **이렇게 대답한다:**
> "**모든 노드에 1개씩 Pod를 배치**해야 할 때 사용합니다. 대표적으로 **로그 수집**(Fluent Bit), **모니터링 에이전트**(Node Exporter), **네트워크 플러그인**(Calico) 등입니다. 로그 수집 파이프라인 구축 시 Fluent Bit를 DaemonSet으로 배포하여 각 노드의 `/var/log`를 수집하고 중앙 로그 시스템으로 전송하는 패턴을 자주 사용합니다."

---

`#Pod라이프사이클` `#Deployment` `#StatefulSet` `#Probe` `#InitContainer`
