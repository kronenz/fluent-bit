# 서비스팀 개발자를 위한 HostPath 기반 로그 수집 가이드

## 개요

본 가이드는 Kubernetes 환경에서 애플리케이션 로그를 수집하는 방법을 설명합니다. 로그는 컨테이너의 stdout/stderr 대신 **HostPath를 통해 노드의 파일시스템에 직접 기록**되며, Fluent Bit이 이를 수집하여 OpenSearch에 전송합니다.

### 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                        Kubernetes Node                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Your Service Pod (namespace: your-service)              │  │
│  │  ┌──────────────────────────────────────────────────────┐│  │
│  │  │ Container                                            ││  │
│  │  │                                                      ││  │
│  │  │  Log4j2 JSON 로그 작성                              ││  │
│  │  │  ↓                                                   ││  │
│  │  │  /var/log/your-service/app.log                      ││  │
│  │  └──────────────────────────────────────────────────────┘│  │
│  │          ↑ (HostPath Volume)                            │  │
│  │          │                                              │  │
│  │  hostPath: /var/log/your-service                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│          ↓ (Node의 실제 파일)                                 │
│          │                                                     │
│  /var/log/your-service/app.log (Node 파일시스템)            │
│          ↓                                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Fluent Bit DaemonSet (namespace: logging)               │  │
│  │  - ClusterFluentBitConfig: 전체 파이프라인 설정          │  │
│  │  - ClusterInput: /var/log/*/app*.log 감시               │  │
│  │  - ClusterFilter: 메타데이터 추가 + 속도 제한           │  │
│  │  - ClusterOutput: OpenSearch 전송                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│          ↓                                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  OpenSearch Cluster (namespace: logging)                 │  │
│  │  Index: app-logs-YYYY.MM.DD                             │  │
│  │  Document: { "log": "...", "namespace": "...", ... }    │  │
│  └──────────────────────────────────────────────────────────┘  │
│          ↓                                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  OpenSearch Dashboards (UI)                              │  │
│  │  검색 및 시각화                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 핵심 개념

- **HostPath 볼륨**: 노드의 파일시스템을 컨테이너에 마운트하여 파일 기반 로그를 저장
- **ClusterFluentBitConfig**: Fluent Bit Operator의 설정 허브로, 모든 파이프라인 리소스를 label selector로 연결
- **Multiline 파서**: JSON 로그가 여러 줄에 걸칠 때 (예: stacktrace) 자동으로 합치기
- **메타데이터 추가**: Lua 스크립트로 파일 경로에서 네임스페이스 정보 자동 추출

---

## 내 서비스에 로그 수집 적용하기

### Step 1: 네임스페이스 확인 및 요청

먼저 서비스가 배포될 네임스페이스를 확인합니다.

```bash
# 현재 네임스페이스 확인
kubectl config current-context
kubectl get ns

# 예시: your-service 네임스페이스에 배포하는 경우
# 해당 네임스페이스가 없으면 요청하세요
```

### Step 2: Deployment YAML에 필수 설정 추가

Kubernetes의 Deployment 매니페스트에 다음 설정들을 추가해야 합니다:

#### 2.1 volumes 섹션 (HostPath 볼륨)

```yaml
spec:
  template:
    spec:
      volumes:
        # 로그 파일을 저장할 HostPath 볼륨
        - name: hostpath-logs
          hostPath:
            path: /var/log/YOUR_NAMESPACE  # 네임스페이스별로 분리
            type: DirectoryOrCreate         # 폴더가 없으면 자동 생성
```

**주요 옵션:**
- `path`: 노드의 실제 경로 (예: `/var/log/your-service`)
- `type: DirectoryOrCreate`: 폴더가 없으면 자동으로 생성
  - `Directory`: 폴더가 반드시 존재해야 함
  - `DirectoryOrCreate`: 폴더가 없으면 자동 생성 (권장)
  - `File`: 파일이 반드시 존재해야 함
  - `FileOrCreate`: 파일이 없으면 자동 생성

#### 2.2 volumeMounts 섹션 (컨테이너에 마운트)

```yaml
spec:
  template:
    spec:
      containers:
        - name: your-app
          volumeMounts:
            # HostPath를 컨테이너 내부의 /var/log/{namespace}에 마운트
            - name: hostpath-logs
              mountPath: /var/log/YOUR_NAMESPACE
```

**주요 설정:**
- `name`: volumes 섹션의 name과 일치해야 함
- `mountPath`: 컨테이너 내부 경로 (로그 파일을 이곳에 기록)

#### 2.3 securityContext 섹션 (권한 설정)

```yaml
spec:
  template:
    spec:
      containers:
        - name: your-app
          securityContext:
            runAsUser: 1000          # 일반 사용자 권한으로 실행
            runAsGroup: 1000         # 일반 그룹으로 실행
```

**중요:**
- `runAsUser: 1000`: root가 아닌 일반 사용자로 실행 (보안)
- `runAsGroup: 1000`: 그룹 권한 설정

#### 2.4 initContainers 섹션 (파일 권한 설정)

```yaml
spec:
  template:
    spec:
      initContainers:
        # 로그 디렉토리의 소유권을 1000:1000으로 변경
        # Pod이 로그를 쓸 수 있도록 권한 설정
        - name: fix-log-dir-ownership
          image: busybox:1.36
          command: ['sh', '-c', 'mkdir -p /var/log/YOUR_NAMESPACE && chown 1000:1000 /var/log/YOUR_NAMESPACE']
          securityContext:
            runAsUser: 0  # root 권한으로만 chown 가능
          volumeMounts:
            - name: hostpath-logs
              mountPath: /var/log/YOUR_NAMESPACE
```

**중요:**
- initContainer는 메인 컨테이너 실행 전에 실행됨
- `chown 1000:1000`으로 소유권 변경 (chmod 777은 사용하지 않음!)
- 디렉토리를 생성하고 즉시 소유권을 변경해야 함

### Step 3: 로그 파일 경로 규칙

로그 파일은 다음 규칙을 따라야 합니다:

```
/var/log/{namespace}/app-{service-name}.log
```

**예시:**
```
/var/log/payment-service/app-payment.log
/var/log/user-service/app-user.log
/var/log/order-service/app-order.log
```

**규칙:**
- 모든 로그는 `/var/log/{namespace}/` 디렉토리 아래
- 파일명은 `app*.log` 패턴 (예: `app.log`, `app-service.log`, `app-payment.log`)
- Fluent Bit이 `/var/log/*/app*.log`로 모든 로그를 자동 수집

### Step 4: Log4j2 JSON 포맷 설정

#### 4.1 log4j2.xml 설정 (Spring Boot 또는 Java 앱)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Configuration packages="org.apache.logging.log4j.core,org.apache.logging.log4j.layout.template.json">
  <Appenders>
    <!-- 파일 Appender: /var/log/{namespace}/app.log에 기록 -->
    <File name="JsonFile" fileName="/var/log/YOUR_NAMESPACE/app.log">
      <!-- JSON Layout: 각 로그 레코드를 JSON 형식으로 기록 -->
      <JsonLayout compact="false" eventEol="true">
        <KeyValuePair key="timeMillis" value="$${log4j:timestamp}" />
        <KeyValuePair key="thread" value="$${log4j:thread}" />
        <KeyValuePair key="level" value="$${log4j:level}" />
        <KeyValuePair key="loggerName" value="$${log4j:logger}" />
        <KeyValuePair key="message" value="$${log4j:message}" />
      </JsonLayout>
    </File>
  </Appenders>

  <Loggers>
    <Root level="INFO">
      <AppenderRef ref="JsonFile" />
    </Root>
  </Loggers>
</Configuration>
```

#### 4.2 Spring Boot application.yml 설정

```yaml
logging:
  file:
    name: /var/log/YOUR_NAMESPACE/app.log
  pattern:
    file: "%d{ISO8601} %level %logger{36} - %msg%n"
  level:
    root: INFO
    com.example: DEBUG

# 또는 logback-spring.xml 사용 (Spring Boot 기본)
# logback-spring.xml에서 appender로 /var/log/{namespace}/app.log 설정
```

#### 4.3 Log4j2 JSON Layout 예시

설정 후 생성되는 로그 파일 형식:

```json
{"timeMillis":1707460800000,"thread":"main","level":"INFO","loggerName":"com.example.PaymentService","message":"Processing payment request","contextMap":{"traceId":"abc-123","spanId":"def-456"}}
{"timeMillis":1707460801000,"thread":"main","level":"ERROR","loggerName":"com.example.PaymentService","message":"Payment failed","exception":"java.lang.RuntimeException: Insufficient balance\n\tat com.example.PaymentService.processPayment(PaymentService.java:45)\n\tat com.example.PaymentController.pay(PaymentController.java:20)"}
```

**중요:**
- 각 JSON 객체는 한 줄이지만, 예외(stacktrace)는 여러 줄에 걸칠 수 있음
- Fluent Bit의 multiline 파서가 자동으로 합쳐줌

---

## 완전한 Deployment YAML 템플릿

다음 예시를 복사-붙여넣기 하여 사용할 수 있습니다. `YOUR_NAMESPACE`, `YOUR_SERVICE_NAME` 등의 플레이스홀더를 교체하세요.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: YOUR_SERVICE_NAME
  namespace: YOUR_NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: YOUR_SERVICE_NAME
  template:
    metadata:
      labels:
        app: YOUR_SERVICE_NAME
    spec:
      # initContainer: 로그 디렉토리 권한 설정
      initContainers:
        - name: fix-log-dir-ownership
          image: busybox:1.36
          command:
            - 'sh'
            - '-c'
            - 'mkdir -p /var/log/YOUR_NAMESPACE && chown 1000:1000 /var/log/YOUR_NAMESPACE'
          securityContext:
            runAsUser: 0  # root 권한
          volumeMounts:
            - name: hostpath-logs
              mountPath: /var/log/YOUR_NAMESPACE

      containers:
        - name: YOUR_SERVICE_NAME
          image: YOUR_IMAGE:TAG
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8080
              name: http

          # 환경 변수 (로그 경로)
          env:
            - name: LOG_PATH
              value: "/var/log/YOUR_NAMESPACE"

          # 리소스 요청 및 제한
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi

          # 헬스체크
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10

          # 보안: 일반 사용자 권한으로 실행
          securityContext:
            runAsUser: 1000
            runAsGroup: 1000
            allowPrivilegeEscalation: false

          # 볼륨 마운트
          volumeMounts:
            - name: hostpath-logs
              mountPath: /var/log/YOUR_NAMESPACE

      # 볼륨 정의
      volumes:
        - name: hostpath-logs
          hostPath:
            path: /var/log/YOUR_NAMESPACE
            type: DirectoryOrCreate
```

---

## Volume / VolumeMount 상세 설명

### hostPath vs emptyDir vs PVC

세 가지 볼륨 타입의 차이를 이해하는 것이 중요합니다:

| 항목 | hostPath | emptyDir | PVC |
|------|----------|----------|-----|
| **저장 위치** | 노드의 파일시스템 | 노드의 임시 디렉토리 | Kubernetes PersistentVolume |
| **데이터 지속성** | Pod 삭제 후에도 유지 | Pod 삭제 시 함께 삭제 | 영구적 저장 (별도 설정 필요) |
| **노드 이동** | Pod이 다른 노드로 이동하면 데이터 액세스 불가 | 각 노드마다 별도의 디렉토리 | 클러스터 어디서든 액세스 가능 |
| **로그 수집 용도** | ✓ (권장) | ✗ (로그 유실 위험) | ✓ (고비용) |
| **사용 사례** | 노드 로그, 설정 파일 | 임시 캐시, 작업 디렉토리 | 데이터베이스, 상태저장 앱 |

**로그 수집을 위해서는 hostPath를 사용합니다** (Pod 삭제 후에도 로그 데이터 유지).

### hostPath.type 옵션

hostPath 볼륨의 type 옵션:

| type | 설명 | 사용 사례 |
|------|------|---------|
| `Directory` | 폴더가 반드시 존재해야 함 | 이미 존재하는 폴더 마운트 |
| `DirectoryOrCreate` | 폴더가 없으면 자동 생성 | **권장** (로그 수집용) |
| `File` | 파일이 반드시 존재해야 함 | 특정 파일 마운트 |
| `FileOrCreate` | 파일이 없으면 자동 생성 | 로그 파일 초기화 |

**로그 수집을 위해서는 `DirectoryOrCreate`를 사용합니다** (폴더가 없을 때 자동 생성).

### mountPath와 hostPath.path의 관계

```yaml
volumes:
  - name: hostpath-logs
    hostPath:
      path: /var/log/payment-service      # ← 노드의 실제 경로
      type: DirectoryOrCreate

containers:
  - name: payment-app
    volumeMounts:
      - name: hostpath-logs
        mountPath: /var/log/payment-service  # ← 컨테이너 내부 경로
```

**비유:**
- `hostPath.path`: 노드의 실제 주소
- `mountPath`: 컨테이너가 그 폴더를 어디서 보는가

```
노드: /var/log/payment-service/app.log
      ↓ (HostPath 마운트)
컨테이너: /var/log/payment-service/app.log (동일한 파일)
```

### 읽기/쓰기 권한 설정

```yaml
volumeMounts:
  - name: hostpath-logs
    mountPath: /var/log/payment-service
    readOnly: false  # 기본값: false (읽기+쓰기)

# readOnly: true는 읽기만 허용 (로그는 쓰기 필요하므로 false)
```

---

## 자주 하는 실수와 해결 방법

### 문제 1: "로그 파일이 안 써져요"

**원인:**
- securityContext의 runAsUser/runAsGroup 설정 누락
- initContainer에서 디렉토리 권한 미설정

**해결:**
1. Deployment의 securityContext 확인:
   ```yaml
   securityContext:
     runAsUser: 1000
     runAsGroup: 1000
   ```

2. initContainer의 chown 실행 확인:
   ```bash
   kubectl logs -n YOUR_NAMESPACE POD_NAME -c fix-log-dir-ownership
   ```

3. 노드에서 디렉토리 권한 확인:
   ```bash
   ls -la /var/log/YOUR_NAMESPACE/
   # 소유자가 1000:1000인지 확인
   ```

### 문제 2: "Permission denied 오류"

**원인:**
- 디렉토리의 소유자가 root이거나 다른 사용자
- securityContext.runAsUser가 해당 사용자와 맞지 않음

**해결:**
1. initContainer에서 chown으로 소유권 변경:
   ```yaml
   initContainers:
     - name: fix-log-dir-ownership
       command: ['sh', '-c', 'chown 1000:1000 /var/log/YOUR_NAMESPACE']
   ```

2. chmod 777은 사용하지 않기 (보안 위험):
   ```bash
   # 잘못된 방법:
   chmod 777 /var/log/YOUR_NAMESPACE  # ❌ 금지!

   # 올바른 방법:
   chown 1000:1000 /var/log/YOUR_NAMESPACE  # ✓
   ```

### 문제 3: "폴더가 없어요"

**원인:**
- hostPath.type이 `Directory`로 설정되어 있음
- 또는 initContainer에서 mkdir을 실행하지 않음

**해결:**
1. hostPath.type을 DirectoryOrCreate로 변경:
   ```yaml
   hostPath:
     path: /var/log/YOUR_NAMESPACE
     type: DirectoryOrCreate  # Directory 대신 DirectoryOrCreate
   ```

2. 또는 initContainer에서 mkdir 실행:
   ```yaml
   command: ['sh', '-c', 'mkdir -p /var/log/YOUR_NAMESPACE && chown 1000:1000 /var/log/YOUR_NAMESPACE']
   ```

### 문제 4: "로그가 OpenSearch에 안 보여요"

**원인:**
- 파일명 패턴 불일치 (app*.log이 아님)
- ClusterFluentBitConfig의 라벨 매칭 실패

**해결:**
1. 로그 파일명 확인:
   ```bash
   ls -la /var/log/YOUR_NAMESPACE/
   # app*.log 패턴과 일치하는지 확인 (예: app.log, app-payment.log)
   ```

2. ClusterFluentBitConfig 라벨 확인:
   ```bash
   kubectl get clusterfluentbitconfig -o yaml
   # inputSelector.matchLabels.fluentbit.fluent.io/enabled: "true" 확인

   kubectl get clusterinput --show-labels
   # 모든 CRD 리소스에 fluentbit.fluent.io/enabled=true 라벨 확인
   ```

3. Fluent Bit 로그 확인:
   ```bash
   kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit
   # "Input" 플러그인이 파일을 감지했는지 확인
   ```

---

## 체크리스트

Deployment 설정 후 다음을 확인하세요:

- [ ] volumes 섹션에 hostPath 설정 추가 (path, type: DirectoryOrCreate)
- [ ] volumeMounts 섹션에 마운트 설정 추가
- [ ] securityContext.runAsUser/runAsGroup = 1000
- [ ] initContainers에서 chown 1000:1000 실행
- [ ] 로그 파일 경로: /var/log/{namespace}/app*.log 규칙 준수
- [ ] Log4j2 JSON Layout 또는 동등한 JSON 포맷 설정
- [ ] Deployment 배포 후 Pod 로그 파일 생성 확인
- [ ] Fluent Bit이 해당 파일을 감지하고 OpenSearch에 전송 확인

---

## 추가 도움

문제가 발생하면 [troubleshooting.md](./troubleshooting.md)를 참조하세요.

OOM 또는 대량 로그 처리 관련 튜닝이 필요하면 [oom-tuning-guide.md](./oom-tuning-guide.md)를 참조하세요.
