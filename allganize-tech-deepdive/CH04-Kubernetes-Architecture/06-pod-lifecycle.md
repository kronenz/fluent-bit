# Pod Lifecycle

> **TL;DR**: Pod는 Pending → Running → Succeeded/Failed 상태를 거치며, Init Container가 순차 실행된 후 메인 컨테이너가 시작된다.
> Liveness Probe(재시작 판단), Readiness Probe(트래픽 수신 판단), Startup Probe(초기화 완료 판단)로 컨테이너 헬스를 관리한다.
> Graceful Shutdown과 PreStop Hook으로 안전한 종료를 보장하는 것이 프로덕션 운영의 핵심이다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 15min

---

## 핵심 개념

### Pod 상태 전이

```
                    ┌──────────┐
                    │  Pending  │
                    │           │
                    │ - 스케줄링 │
                    │   대기    │
                    │ - 이미지   │
                    │   Pull    │
                    │ - Init    │
                    │  Container│
                    └─────┬────┘
                          │
                          ▼
                    ┌──────────┐
                    │  Running  │
                    │           │
                    │ - 1개 이상 │
                    │  컨테이너  │
                    │  실행 중   │
                    └──┬────┬──┘
                       │    │
              ┌────────┘    └────────┐
              ▼                      ▼
        ┌──────────┐          ┌──────────┐
        │Succeeded │          │  Failed  │
        │          │          │          │
        │ - 모든    │          │ - 1개    │
        │  컨테이너  │         │  이상     │
        │  정상 종료 │          │  비정상   │
        │  (exit 0) │          │  종료     │
        └──────────┘          └──────────┘

        ※ Unknown: 노드 통신 불가 시
```

### Pod 생성 ~ 실행 전체 흐름

```
kubectl apply -f pod.yaml
        │
        ▼
   kube-apiserver
        │ etcd에 Pod 저장 (nodeName 비어있음)
        ▼
   kube-scheduler
        │ Filtering → Scoring → Binding (nodeName 설정)
        ▼
   kubelet (해당 노드)
        │
        ├─ 1. 이미지 Pull (ImagePullPolicy에 따라)
        │
        ├─ 2. Init Container 순차 실행
        │     init-1 ──(성공)──► init-2 ──(성공)──► ...
        │     (하나라도 실패하면 재시도)
        │
        ├─ 3. 메인 Container 동시 시작
        │     ├─ container-1 (+ postStart Hook)
        │     └─ container-2 (+ postStart Hook)
        │
        ├─ 4. Startup Probe 시작 (설정 시)
        │     → 성공까지 다른 Probe 비활성
        │
        ├─ 5. Liveness Probe + Readiness Probe 시작
        │     → Liveness 실패: 컨테이너 재시작
        │     → Readiness 실패: Service endpoints에서 제거
        │
        └─ 6. Pod Running 상태
```

### Init Container

메인 컨테이너보다 **먼저 순차적으로 실행**되는 컨테이너. 초기화 로직을 분리.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: alli-api
spec:
  initContainers:
  # 1번째: DB 마이그레이션 대기
  - name: wait-for-db
    image: busybox:1.36
    command: ['sh', '-c',
      'until nc -z postgres-svc 5432; do echo waiting for db; sleep 2; done']

  # 2번째: 설정 파일 다운로드
  - name: download-config
    image: curlimages/curl:8.0
    command: ['sh', '-c',
      'curl -o /config/app.yaml https://config-server/api/config']
    volumeMounts:
    - name: config-vol
      mountPath: /config

  # 3번째: DB 스키마 마이그레이션
  - name: db-migrate
    image: allganize/alli-migrate:latest
    command: ['./migrate', 'up']
    env:
    - name: DB_URL
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: url

  containers:
  - name: alli-api
    image: allganize/alli-api:latest
    volumeMounts:
    - name: config-vol
      mountPath: /config

  volumes:
  - name: config-vol
    emptyDir: {}
```

**Init Container vs 메인 Container:**

| 특성 | Init Container | 메인 Container |
|------|---------------|---------------|
| 실행 순서 | 순차 (하나씩) | 동시 (병렬) |
| Probe | 지원 안 함 | 모두 지원 |
| 리소스 | 각각의 최대값이 Pod 전체에 적용 | requests/limits 합산 |
| 재시작 | restartPolicy에 따름 | restartPolicy에 따름 |
| 실행 횟수 | 성공 시 1회만 | Pod 수명 내 지속 |

### Probes (헬스 체크)

```
┌────────────────────────────────────────────────────────┐
│                    Pod Timeline                         │
│                                                        │
│  Container Start                                       │
│  ├──────────────── Startup Probe ──────────┤           │
│  │  initialDelaySeconds                    │           │
│  │  ├─ Check ─ Check ─ Check ─ ✓ (성공)    │           │
│  │                                         │           │
│  │  ├──────── Liveness Probe ──────────────────────►   │
│  │  │  ├─ ✓ ─ ✓ ─ ✗ ─ ✗ ─ ✗ → 재시작     │           │
│  │  │  │      (failureThreshold=3)         │           │
│  │  │                                      │           │
│  │  ├──────── Readiness Probe ─────────────────────►   │
│  │  │  ├─ ✓ ─ ✓ ─ ✗ ─ ✗ ─ ✓ → 트래픽 복구  │           │
│  │  │         (Service에서 제거/추가)        │           │
│  │                                         │           │
└──┴─────────────────────────────────────────┴───────────┘
```

**3가지 Probe:**

| Probe | 실패 시 동작 | 사용 목적 |
|---|---|---|
| **Startup** | 컨테이너 재시작 | 느린 초기화 보호 (LLM 모델 로딩 등) |
| **Liveness** | 컨테이너 재시작 | Deadlock, 무한 루프 감지 |
| **Readiness** | Service endpoints에서 제거 | 트래픽 수신 준비 확인 |

**Probe 유형:**

| 유형 | 방식 | 사용 예 |
|---|---|---|
| httpGet | HTTP GET 요청, 200-399 성공 | 웹 서버 `/healthz` |
| tcpSocket | TCP 연결 성공 여부 | DB, Redis 포트 확인 |
| exec | 명령어 실행, exit code 0 성공 | 파일 존재 확인, 커스텀 로직 |
| grpc | gRPC Health Check Protocol | gRPC 서버 (1.24+) |

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: alli-llm-serving
spec:
  containers:
  - name: llm-server
    image: allganize/alli-llm:latest
    ports:
    - containerPort: 8080

    # Startup Probe: LLM 모델 로딩에 최대 10분 허용
    startupProbe:
      httpGet:
        path: /health/startup
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 10
      failureThreshold: 60       # 10 * 60 = 600초 = 10분

    # Liveness Probe: 서버 프로세스 생존 확인
    livenessProbe:
      httpGet:
        path: /health/live
        port: 8080
      initialDelaySeconds: 0      # Startup 성공 후 바로 시작
      periodSeconds: 15
      timeoutSeconds: 5
      failureThreshold: 3         # 3회 연속 실패 시 재시작

    # Readiness Probe: 추론 요청 처리 가능 여부
    readinessProbe:
      httpGet:
        path: /health/ready
        port: 8080
      initialDelaySeconds: 0
      periodSeconds: 5
      timeoutSeconds: 3
      successThreshold: 1         # 1회 성공 시 Ready
      failureThreshold: 3         # 3회 실패 시 Not Ready
```

### Graceful Shutdown (안전한 종료)

```
Pod 삭제 요청 (kubectl delete pod / Rolling Update)
        │
        │  동시에 발생:
        ├──────────────────────────────────────┐
        │                                      │
        ▼                                      ▼
  Service endpoints에서                  컨테이너 종료 시작
  Pod IP 제거
  (트래픽 중단)                          1. preStop Hook 실행
                                        2. SIGTERM 전송
                                        3. terminationGracePeriodSeconds
                                           대기 (기본 30초)
                                        4. SIGKILL (강제 종료)
```

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: alli-api
spec:
  terminationGracePeriodSeconds: 60    # SIGTERM 후 최대 60초 대기
  containers:
  - name: alli-api
    image: allganize/alli-api:latest
    lifecycle:
      postStart:
        exec:
          command: ["/bin/sh", "-c", "echo started > /tmp/started"]
      preStop:
        exec:
          # 진행 중인 요청이 완료될 시간 확보
          command: ["/bin/sh", "-c", "sleep 5 && kill -SIGTERM 1"]
        # 또는 HTTP 호출
        # httpGet:
        #   path: /shutdown
        #   port: 8080
```

**왜 preStop에서 sleep이 필요한가?**
```
시간 ──────────────────────────────────────────────►

1. Pod 삭제 요청
2. [동시] endpoints 제거 시작 + preStop 실행 시작
3. endpoints 제거가 kube-proxy/ingress에 전파되기까지 시간 소요
4. 이 사이에 이미 라우팅된 요청이 Pod에 도착할 수 있음
5. preStop sleep으로 이 간격을 커버

→ sleep 5 ~ 15초가 일반적
→ 이후 SIGTERM으로 애플리케이션이 graceful shutdown 수행
```

### RestartPolicy

| 값 | 동작 | 사용 사례 |
|---|---|---|
| Always (기본) | 항상 재시작 | Deployment, DaemonSet |
| OnFailure | 실패(exit code != 0) 시만 재시작 | Job |
| Never | 재시작 안 함 | 디버깅, 일회성 작업 |

**재시작 백오프:**
```
1번째 재시작: 즉시
2번째: 10초 대기
3번째: 20초
4번째: 40초
...
최대: 5분 (300초) 대기 → CrashLoopBackOff 상태
```

---

## 실전 예시

### Pod 상태 디버깅

```bash
# Pod 상태 확인
kubectl get pods -o wide
kubectl describe pod <pod-name>

# 상태별 원인 분석:
# Pending: 스케줄링 실패, 이미지 Pull 대기
# ContainerCreating: 이미지 Pull, 볼륨 마운트 중
# Init:0/2: Init Container 실행 중 (0/2 완료)
# Running: 정상 실행
# CrashLoopBackOff: 반복 크래시 (재시작 백오프)
# ImagePullBackOff: 이미지 Pull 실패
# Completed: 정상 종료 (Job)
# Error: 비정상 종료
# OOMKilled: 메모리 초과로 강제 종료

# 이전 컨테이너(크래시 전) 로그 확인
kubectl logs <pod-name> --previous
kubectl logs <pod-name> -c <container-name> --previous

# Init Container 로그 확인
kubectl logs <pod-name> -c <init-container-name>
```

### CrashLoopBackOff 디버깅

```bash
# 1. 이벤트 확인
kubectl describe pod <pod-name>
# → Events에서 원인 파악

# 2. 이전 로그 확인
kubectl logs <pod-name> --previous

# 3. exit code 확인
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState}'
# exit code 137: OOMKilled (SIGKILL)
# exit code 1: 애플리케이션 에러
# exit code 127: 명령어 없음
# exit code 126: 실행 권한 없음

# 4. 디버그 컨테이너로 진입 (1.25+)
kubectl debug -it <pod-name> --image=busybox:1.36 --target=<container-name>

# 5. 임시 디버그 Pod (같은 설정으로)
kubectl run debug-pod --image=allganize/alli-api:latest \
  --restart=Never --command -- sleep infinity
kubectl exec -it debug-pod -- /bin/sh
```

### Probe 설정 베스트 프랙티스

```yaml
# 잘못된 예: Liveness에 무거운 로직
livenessProbe:
  httpGet:
    path: /health/full    # DB 연결, 외부 API 확인 → 느림
    port: 8080
  timeoutSeconds: 1       # 타임아웃이 너무 짧음
  failureThreshold: 1     # 1회 실패로 바로 재시작 → 불안정

# 올바른 예: Liveness는 가볍게, Readiness에서 의존성 확인
livenessProbe:
  httpGet:
    path: /health/live    # 프로세스 생존만 확인 (가벼운 응답)
    port: 8080
  periodSeconds: 15
  timeoutSeconds: 5
  failureThreshold: 3     # 3회 연속 실패 후 재시작

readinessProbe:
  httpGet:
    path: /health/ready   # DB 연결, 캐시 상태 등 확인
    port: 8080
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

### Rolling Update와 Pod Lifecycle

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alli-api
spec:
  replicas: 4
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1            # 최대 5개까지 동시 실행
      maxUnavailable: 0      # 항상 4개 이상 유지
  template:
    spec:
      terminationGracePeriodSeconds: 60
      containers:
      - name: alli-api
        image: allganize/alli-api:v2
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 10"]
```

---

## 면접 Q&A

### Q: Liveness Probe와 Readiness Probe의 차이를 설명해주세요.
**30초 답변**:
Liveness Probe는 컨테이너가 살아있는지 확인하며, 실패 시 컨테이너를 재시작합니다. Readiness Probe는 트래픽을 받을 준비가 되었는지 확인하며, 실패 시 Service endpoints에서 제거하여 트래픽을 차단합니다.

**2분 답변**:
Liveness Probe는 컨테이너가 정상 동작하는지를 확인합니다. Deadlock이나 무한 루프 같은 복구 불가능한 상태를 감지하기 위한 것으로, failureThreshold 횟수만큼 연속 실패하면 kubelet이 컨테이너를 재시작합니다. 따라서 Liveness 체크는 가볍게 구현해야 합니다. 외부 의존성(DB, 캐시)을 확인하면 안 되는데, 의존성 장애 시 불필요한 재시작이 발생하기 때문입니다. Readiness Probe는 트래픽을 처리할 준비가 되었는지를 확인합니다. 실패하면 Service의 endpoints에서 해당 Pod IP가 제거되어 트래픽이 다른 Pod로 라우팅됩니다. 성공하면 다시 endpoints에 추가됩니다. DB 연결 풀이 가득 찼거나 캐시 워밍업 중일 때 Not Ready로 표시하여 에러 응답을 방지합니다. Startup Probe는 1.20에서 GA가 된 기능으로, 초기화가 오래 걸리는 컨테이너(LLM 모델 로딩 등)를 보호합니다. Startup Probe가 성공할 때까지 Liveness/Readiness가 시작되지 않으므로, 초기화 중 불필요한 재시작을 방지합니다.

**경험 연결**:
Liveness Probe에 DB health check를 포함했다가, DB 일시 장애 시 모든 Pod가 동시에 재시작되는 cascading failure를 경험했습니다. Liveness는 프로세스 자체의 생존만 확인하고, 외부 의존성은 Readiness에서 확인하도록 분리하여 해결했습니다.

**주의**:
Liveness Probe가 없으면 컨테이너가 Deadlock 상태에서도 재시작되지 않는다. 반면 Liveness를 너무 공격적으로 설정하면 정상 부하 시에도 재시작될 수 있다. periodSeconds, timeoutSeconds, failureThreshold를 적절히 조합해야 한다.

### Q: Pod가 삭제될 때 진행 중인 요청은 어떻게 처리되나요?
**30초 답변**:
Pod 삭제 시 Service endpoints 제거와 SIGTERM 전송이 동시에 발생합니다. endpoints 전파에 시간이 걸리므로, preStop Hook에서 수 초간 sleep하여 이미 라우팅된 요청이 완료되도록 하고, 애플리케이션은 SIGTERM을 받으면 새 요청 거부 + 진행 중 요청 완료 후 종료합니다.

**2분 답변**:
Pod 종료 과정에서 발생할 수 있는 문제는 "endpoints 제거 전파 지연"입니다. Pod 삭제가 시작되면 apiserver가 endpoints에서 Pod를 제거하지만, 이 변경이 kube-proxy와 Ingress Controller에 전파되기까지 수 초가 걸립니다. 동시에 kubelet은 preStop Hook을 실행하고 SIGTERM을 보냅니다. 이 사이 시간 동안 트래픽이 종료 중인 Pod에 도달할 수 있습니다. 해결 전략은: (1) preStop에서 sleep 5~15초를 실행하여 endpoints 전파 시간을 확보합니다. (2) 애플리케이션은 SIGTERM 시그널 핸들러에서 새 연결을 거부하되, 기존 연결의 요청이 완료될 때까지 대기합니다. (3) terminationGracePeriodSeconds를 preStop sleep + 예상 최대 요청 처리 시간보다 크게 설정합니다. (4) 이 시간이 초과되면 SIGKILL로 강제 종료됩니다. Rolling Update 시에도 같은 메커니즘이 적용되므로, maxUnavailable=0으로 설정하고 Readiness Probe가 성공한 새 Pod가 준비된 후에만 구 Pod를 종료하도록 합니다.

**경험 연결**:
Rolling Update 중 간헐적 502 에러가 발생했던 경험이 있습니다. 원인은 preStop Hook 없이 SIGTERM을 바로 보내서, endpoints 전파 전에 Pod가 종료된 것이었습니다. preStop에 `sleep 10`을 추가하고, 애플리케이션에 graceful shutdown 로직을 구현하여 0-downtime 배포를 달성했습니다.

**주의**:
terminationGracePeriodSeconds는 preStop Hook 시간을 포함한다. preStop에서 25초 sleep하고 terminationGracePeriodSeconds가 30초이면, SIGTERM 후 앱이 graceful shutdown할 시간은 5초뿐이다.

### Q: Init Container는 어떤 상황에서 사용하나요?
**30초 답변**:
의존성 서비스 대기(DB, 캐시), 설정 파일 준비, DB 스키마 마이그레이션 등 메인 컨테이너 실행 전에 완료되어야 하는 초기화 작업에 사용합니다. 순차 실행이 보장되며, 하나라도 실패하면 Pod가 시작되지 않습니다.

**2분 답변**:
Init Container는 세 가지 주요 시나리오에서 사용합니다. 첫째, 의존성 대기입니다. DB, Redis, 다른 마이크로서비스가 준비될 때까지 대기하는 로직을 Init Container에 격리합니다. 메인 이미지에 curl이나 nc 같은 도구를 포함할 필요가 없어집니다. 둘째, 데이터 준비입니다. S3에서 ML 모델 다운로드, 설정 파일 생성, 인증서 변환 등을 수행합니다. emptyDir 볼륨을 통해 메인 컨테이너와 데이터를 공유합니다. 셋째, 보안 관련 초기화입니다. 메인 컨테이너보다 높은 권한으로 실행할 수 있어, 네트워크 규칙 설정이나 sysctl 변경 등에 사용합니다. Istio의 istio-init이 iptables 규칙을 설정하는 것이 대표적 예입니다. Init Container의 리소스 계산 방식도 중요합니다. Init Container의 각 리소스 요청 최대값과 메인 컨테이너의 합산 요청 중 더 큰 값이 Pod의 실제 리소스 요청이 됩니다. 이는 Init Container가 순차 실행이기 때문입니다.

**경험 연결**:
DB 마이그레이션을 Init Container로 실행하여, 배포 시 자동으로 스키마 변경이 적용되도록 구성했습니다. Helm chart에서 migration 이미지 태그를 별도 관리하여, 마이그레이션과 애플리케이션 버전을 독립적으로 제어할 수 있었습니다.

**주의**:
Init Container가 실패하면 Pod 전체가 시작되지 않으므로, Init Container의 에러 핸들링과 로깅이 중요하다. `kubectl logs <pod> -c <init-container>`로 Init Container 로그를 확인할 수 있다.

---

## Allganize 맥락

- **LLM 모델 로딩과 Startup Probe**: Allganize의 LLM 서빙 Pod는 대용량 모델을 메모리에 로딩하는 데 수 분이 걸릴 수 있다. Startup Probe로 로딩 완료를 확인하고, 그 전까지 Liveness Probe가 동작하지 않도록 보호해야 한다. failureThreshold를 충분히 크게 설정하는 것이 핵심이다.
- **Graceful Shutdown과 추론 요청**: LLM 추론은 응답 생성에 수 초~수십 초가 걸릴 수 있다. terminationGracePeriodSeconds를 넉넉하게(120초 이상) 설정하고, preStop Hook + SIGTERM 핸들링으로 진행 중인 추론이 완료되도록 해야 한다.
- **Init Container로 모델 다운로드**: S3에서 모델 파일을 다운로드하는 Init Container를 사용하여, 모델 파일을 PVC에 캐싱하고 메인 컨테이너에서 마운트하는 패턴이 일반적이다.
- **Rolling Update 전략**: AI 서비스의 무중단 배포를 위해 maxSurge=1, maxUnavailable=0 전략과 Readiness Probe를 조합한다. GPU Pod는 시작 시간이 길므로 maxSurge를 크게 잡으면 GPU 리소스가 일시적으로 2배 필요할 수 있다.
- **CrashLoopBackOff 대응**: OOM이나 GPU 드라이버 호환성 문제로 LLM Pod가 CrashLoopBackOff에 빠질 수 있다. 메모리 limits 조정, NVIDIA 드라이버 버전 확인이 1차 디버깅 포인트이다.

---
**핵심 키워드**: `Pod-lifecycle` `Pending` `Running` `CrashLoopBackOff` `Init-Container` `Liveness-Probe` `Readiness-Probe` `Startup-Probe` `preStop-Hook` `graceful-shutdown` `terminationGracePeriodSeconds`
