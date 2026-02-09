# 서비스팀을 위한 로그 수집 설정 가이드

> 이 가이드는 **Kubernetes를 잘 모르는 개발자**도 따라할 수 있도록 작성되었습니다.
> 복사-붙여넣기만으로 로그 수집을 설정할 수 있습니다.

---

## 한 줄 요약

여러분의 앱이 **정해진 경로에 로그 파일을 쓰면**, 나머지는 자동으로 OpenSearch에 수집됩니다.

```
여러분의 앱 → /var/log/{네임스페이스}/app.log 파일에 로그 작성
                    ↓ (자동)
              Fluent Bit가 파일을 읽어감
                    ↓ (자동)
              OpenSearch에 저장 → Dashboards에서 검색
```

---

## 이해해야 할 개념 (최소한만)

### "볼륨(Volume)"이 뭔가요?

Kubernetes에서 컨테이너는 **임시 공간**에서 실행됩니다. 컨테이너가 재시작되면 파일이 다 사라집니다.

**볼륨**은 컨테이너 외부의 저장소를 컨테이너 안에 연결하는 것입니다.

비유하면:
- 컨테이너 = 호텔 방 (체크아웃하면 짐이 사라짐)
- 볼륨 = USB 메모리 (방을 바꿔도 데이터 유지)

우리가 사용하는 **HostPath 볼륨**은 서버(노드) 디스크의 폴더를 컨테이너 안에 그대로 연결하는 방식입니다.

```
서버 디스크: /var/log/my-service/app.log  ←── 실제 파일이 여기 저장됨
                    ↕ (HostPath로 연결)
컨테이너 안: /var/log/my-service/app.log  ←── 앱은 여기에 쓰면 됨 (같은 파일)
```

### "Deployment YAML"이 뭔가요?

Kubernetes에서 앱을 배포하려면 **YAML 파일**에 "이 앱을 이렇게 실행해줘"라고 설정을 적어야 합니다.
이 YAML 파일을 **Deployment**라고 부릅니다.

아래에서 **복사-붙여넣기 할 수 있는 템플릿**을 제공합니다.

---

## 설정 방법 (3단계)

### Step 1: 네임스페이스 이름 확인

네임스페이스는 팀/서비스별로 분리된 공간입니다. 인프라팀에서 알려준 네임스페이스 이름을 사용하세요.

```bash
# 예시: payment-service, user-service, order-service 등
# 모르겠으면 인프라팀에 문의하세요
```

### Step 2: Deployment YAML 작성

아래 템플릿을 복사한 후, **`YOUR_NAMESPACE`와 `YOUR_SERVICE_NAME`만 바꾸면** 됩니다.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: YOUR_SERVICE_NAME          # ← 서비스 이름 (예: payment-api)
  namespace: YOUR_NAMESPACE         # ← 네임스페이스 (예: payment-service)
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
      containers:
        - name: YOUR_SERVICE_NAME
          image: YOUR_IMAGE:TAG     # ← 도커 이미지 (예: myapp:1.0.0)
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8080
              name: http

          # ──────────────────────────────────────
          # [필수] 환경 변수 - 로그 경로를 앱에 전달
          # ──────────────────────────────────────
          env:
            - name: LOG_PATH
              value: "/var/log/YOUR_NAMESPACE"

          # ──────────────────────────────────────
          # [필수] 리소스 제한
          # ──────────────────────────────────────
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi

          # ──────────────────────────────────────
          # [필수] 보안 설정 - root로 실행
          # 서버마다 별도 권한 설정 없이 바로 로그 쓰기 가능
          # ──────────────────────────────────────
          securityContext:
            runAsUser: 0
            runAsGroup: 0

          # ──────────────────────────────────────
          # [필수] 볼륨 마운트 - 로그 폴더를 컨테이너에 연결
          # ──────────────────────────────────────
          volumeMounts:
            - name: hostpath-logs
              mountPath: /var/log/YOUR_NAMESPACE

      # ──────────────────────────────────────
      # [필수] 볼륨 정의 - 서버 디스크 폴더를 지정
      # ──────────────────────────────────────
      volumes:
        - name: hostpath-logs
          hostPath:
            path: /var/log/YOUR_NAMESPACE   # 서버 디스크의 실제 경로
            type: DirectoryOrCreate          # 폴더 없으면 자동 생성
```

#### 바꿔야 할 부분 정리

| 플레이스홀더 | 설명 | 예시 |
|---|---|---|
| `YOUR_SERVICE_NAME` | 서비스 이름 | `payment-api` |
| `YOUR_NAMESPACE` | 네임스페이스 | `payment-service` |
| `YOUR_IMAGE:TAG` | 도커 이미지 | `mycompany/payment-api:1.2.3` |

#### 왜 root(runAsUser: 0)인가요?

- root로 실행하면 **서버마다 일일히 `/var/log/` 폴더 권한을 설정할 필요가 없습니다**
- HostPath 볼륨은 서버 디스크에 직접 쓰기 때문에, 일반 사용자(1000)로 실행하면 서버마다 `chown`으로 소유권을 바꿔줘야 합니다
- root로 실행하면 어떤 서버에서든 바로 파일을 생성하고 쓸 수 있습니다
- 이 설정은 **로그 수집 용도로만** 사용되며, 네트워크 권한과는 무관합니다

### Step 3: 로그 파일 경로 규칙

앱에서 로그를 쓸 때 아래 규칙을 지켜주세요:

```
/var/log/{네임스페이스}/app-{서비스이름}.log
```

**예시:**
```
/var/log/payment-service/app-payment.log    ← payment 팀
/var/log/user-service/app-user.log          ← user 팀
/var/log/order-service/app-order.log        ← order 팀
```

**규칙:**
- 경로: `/var/log/{네임스페이스}/` 아래
- 파일명: `app`으로 시작, `.log`로 끝남 (예: `app.log`, `app-payment.log`)
- Fluent Bit이 `/var/log/*/app*.log` 패턴으로 자동 수집합니다

---

## Log4j2 JSON 포맷 설정

로그는 반드시 **JSON 형식**으로 작성해야 합니다. 일반 텍스트 로그는 수집되지 않습니다.

### Spring Boot (log4j2.xml) 설정

`src/main/resources/log4j2.xml` 파일에 다음을 추가하세요:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Configuration>
  <Appenders>
    <!-- 파일에 JSON 형식으로 로그 기록 -->
    <File name="JsonFile" fileName="/var/log/YOUR_NAMESPACE/app.log">
      <JsonLayout compact="true" eventEol="true">
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

### 로그 출력 예시

설정 후 생성되는 로그 파일은 이렇게 생겼습니다:

```json
{"timeMillis":1707460800000,"thread":"main","level":"INFO","loggerName":"com.example.PaymentService","message":"결제 요청 처리 시작"}
{"timeMillis":1707460801000,"thread":"main","level":"ERROR","loggerName":"com.example.PaymentService","message":"결제 실패\njava.lang.RuntimeException: 잔액 부족\n\tat com.example.PaymentService.process(PaymentService.java:45)"}
```

- 한 줄에 하나의 JSON 객체
- 에러의 스택트레이스(여러 줄)는 Fluent Bit이 자동으로 합쳐줍니다

---

## 실제 적용 예시: payment-service

바로 복사해서 사용할 수 있는 실제 예시입니다.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-api
  namespace: payment-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: payment-api
  template:
    metadata:
      labels:
        app: payment-api
    spec:
      containers:
        - name: payment-api
          image: mycompany/payment-api:1.2.3
          ports:
            - containerPort: 8080
          env:
            - name: LOG_PATH
              value: "/var/log/payment-service"
          resources:
            requests:
              cpu: 200m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          securityContext:
            runAsUser: 0
            runAsGroup: 0
          volumeMounts:
            - name: hostpath-logs
              mountPath: /var/log/payment-service
      volumes:
        - name: hostpath-logs
          hostPath:
            path: /var/log/payment-service
            type: DirectoryOrCreate
```

배포:
```bash
kubectl apply -f deployment.yaml
```

확인:
```bash
# Pod이 잘 떴는지 확인
kubectl get pods -n payment-service

# 로그 파일이 생겼는지 확인 (Pod 안에서)
kubectl exec -n payment-service deploy/payment-api -- ls -la /var/log/payment-service/

# 로그 내용 확인
kubectl exec -n payment-service deploy/payment-api -- tail -5 /var/log/payment-service/app.log
```

---

## 자주 묻는 질문 (FAQ)

### Q1: "로그 파일이 안 만들어져요"

**확인 순서:**

1. Pod이 정상 실행 중인지 확인:
   ```bash
   kubectl get pods -n YOUR_NAMESPACE
   # STATUS가 Running인지 확인
   ```

2. 앱의 로그 경로 설정이 맞는지 확인:
   ```bash
   # log4j2.xml의 fileName이 /var/log/YOUR_NAMESPACE/app.log 인지 확인
   ```

3. 볼륨 마운트가 되어 있는지 확인:
   ```bash
   kubectl describe pod -n YOUR_NAMESPACE POD_NAME | grep -A5 "Mounts"
   ```

### Q2: "OpenSearch에서 우리 팀 로그가 안 보여요"

**확인 순서:**

1. 로그 파일이 서버에 존재하는지 확인:
   ```bash
   kubectl exec -n YOUR_NAMESPACE deploy/YOUR_SERVICE -- ls -la /var/log/YOUR_NAMESPACE/
   ```

2. 파일명이 규칙에 맞는지 확인:
   - `app*.log` 패턴이어야 합니다 (예: `app.log`, `app-payment.log`)
   - `service.log`, `output.log` 같은 이름은 수집되지 않습니다

3. 로그가 JSON 형식인지 확인:
   ```bash
   kubectl exec -n YOUR_NAMESPACE deploy/YOUR_SERVICE -- head -1 /var/log/YOUR_NAMESPACE/app.log
   # {"timeMillis":..., "level":"INFO", ...} 형식이어야 합니다
   ```

4. 인프라팀에 Fluent Bit 상태 확인 요청:
   ```bash
   kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=20
   ```

### Q3: "volumes, volumeMounts가 뭔지 모르겠어요"

간단히 설명하면:

- **volumes**: "이런 저장소를 사용하겠다"는 **선언** (= USB 메모리를 준비)
- **volumeMounts**: "그 저장소를 컨테이너의 이 경로에 연결하겠다"는 **연결** (= USB를 꽂는 위치)

```yaml
# 1단계: 볼륨 선언 ("hostpath-logs"라는 이름으로 서버 디스크 폴더 사용)
volumes:
  - name: hostpath-logs              # 이름 (자유롭게 지정)
    hostPath:
      path: /var/log/my-service      # 서버 디스크의 어떤 폴더를 쓸 건지

# 2단계: 볼륨 연결 ("hostpath-logs"를 컨테이너 안의 특정 경로에 연결)
volumeMounts:
  - name: hostpath-logs              # 위에서 선언한 이름과 동일해야 함!
    mountPath: /var/log/my-service   # 컨테이너 안에서 보이는 경로
```

**핵심:** `volumes.name`과 `volumeMounts.name`이 **반드시 같아야** 합니다.

### Q4: "hostPath.type의 DirectoryOrCreate가 뭔가요?"

| type | 의미 | 언제 사용 |
|---|---|---|
| `DirectoryOrCreate` | 폴더가 없으면 자동으로 만들어줌 | **이걸 쓰세요** (권장) |
| `Directory` | 폴더가 반드시 미리 존재해야 함 | 이미 폴더가 있을 때만 |

### Q5: "다른 팀 로그가 보여요 / 우리 로그만 보고 싶어요"

OpenSearch Dashboards에서 검색할 때 `namespace` 필드로 필터링하세요:

```
namespace: "payment-service"
```

각 팀의 로그는 네임스페이스별로 자동 태깅됩니다.

---

## YAML 설정 요소 정리

Deployment YAML에서 각 부분이 하는 역할:

```yaml
spec:
  template:
    spec:
      containers:
        - name: ...
          image: ...          # 어떤 앱을 실행할지
          ports: ...          # 앱이 사용하는 포트
          env: ...            # 환경변수 (로그 경로 등)
          resources: ...      # CPU/메모리 제한
          securityContext:     # 실행 권한 설정
            runAsUser: 0      #   → root로 실행 (권한 문제 없음)
            runAsGroup: 0     #   → root 그룹으로 실행
          volumeMounts: ...   # 볼륨을 컨테이너에 연결

      volumes: ...            # 사용할 볼륨 선언
```

**건드리지 않아도 되는 부분:** `apiVersion`, `kind`, `metadata`, `spec.selector`, `spec.template.metadata.labels`
(템플릿에서 서비스 이름/네임스페이스만 바꾸면 됩니다)

---

## 체크리스트 (배포 전 확인)

배포하기 전에 아래를 확인하세요:

- [ ] YAML에서 `YOUR_NAMESPACE`, `YOUR_SERVICE_NAME`, `YOUR_IMAGE:TAG`를 모두 바꿨는가?
- [ ] `volumes` 섹션에 `hostPath`가 있는가?
- [ ] `volumeMounts` 섹션에 마운트가 있는가?
- [ ] `volumes.name`과 `volumeMounts.name`이 같은가? (둘 다 `hostpath-logs`)
- [ ] `securityContext`에 `runAsUser: 0`이 있는가?
- [ ] 로그 파일 경로가 `/var/log/{네임스페이스}/app*.log` 규칙을 따르는가?
- [ ] 로그 형식이 JSON인가? (Log4j2 JsonLayout 등)

모든 항목을 확인했으면 `kubectl apply -f deployment.yaml`로 배포하세요.

---

## 도움이 필요할 때

| 상황 | 참고 문서 |
|---|---|
| 로그가 안 나와요 / 에러가 나요 | [troubleshooting.md](./troubleshooting.md) |
| 로그가 너무 많아서 메모리가 부족해요 | [oom-tuning-guide.md](./oom-tuning-guide.md) |
| 그래도 모르겠어요 | 인프라팀에 문의 (Slack: #infra-support) |
