# 폐쇄망 환경 repository-s3 플러그인 설치 가이드

## 1. 개요

폐쇄망(Air-gapped) 환경에서는 OpenSearch Pod가 인터넷에 접근할 수 없으므로 `repository-s3` 플러그인을 사전에 준비하여 설치해야 합니다. 본 문서에서는 3가지 설치 방법을 제시하며, Kubernetes Helm 기반 배포 환경에 맞는 구성을 안내합니다.

### 설치 방법 비교

| 방법 | 설명 | 난이도 | 권장 환경 |
|------|------|--------|----------|
| **방법 A: 커스텀 Docker 이미지** | Dockerfile에서 플러그인 포함 이미지 빌드 | 쉬움 | **운영환경 권장** |
| **방법 B: initContainer** | Pod 시작 시 로컬 저장소에서 플러그인 설치 | 중간 | 이미지 빌드 불가 시 |
| **방법 C: PV 마운트** | 플러그인 디렉토리를 PV로 마운트 | 중간 | 기존 PV 활용 가능 시 |

### 사전 확인: 기본 이미지에 포함 여부

`repository-s3` 플러그인은 OpenSearch **공식 Docker 이미지에 기본 포함**되어 있습니다.

```bash
# 인터넷 환경 또는 이미 배포된 환경에서 확인
kubectl exec -n logging opensearch-cluster-master-0 -- \
  /usr/share/opensearch/bin/opensearch-plugin list
```

출력에 `repository-s3`이 있으면 별도 설치가 불필요합니다:
```
opensearch-alerting
opensearch-anomaly-detection
...
repository-s3            ← 포함되어 있으면 설치 불필요
...
```

> **공식 이미지 `opensearchproject/opensearch:2.x`에는 repository-s3가 기본 포함**되어 있습니다. 커스텀/경량 이미지를 사용하는 경우에만 아래 설치 절차가 필요합니다.

---

## 2. 인터넷 환경에서 패키지 사전 준비

폐쇄망에 반입하기 전, 인터넷이 되는 PC에서 필요한 파일들을 다운로드합니다.

### 2-1. 사용 중인 OpenSearch 버전 확인

```bash
# 현재 배포된 버전 확인 (접근 가능한 경우)
kubectl exec -n logging opensearch-cluster-master-0 -- \
  curl -s localhost:9200 | grep number

# 또는 Helm 차트 버전으로 확인
# opensearch Helm chart 2.28.0 → OpenSearch 2.19.0
```

> **중요:** 플러그인 버전은 반드시 OpenSearch 버전과 **정확히 일치**해야 합니다.

### 2-2. repository-s3 플러그인 다운로드

인터넷이 되는 PC에서 다운로드:

```bash
# OpenSearch 버전에 맞는 플러그인 다운로드
# 형식: https://artifacts.opensearch.org/releases/plugins/repository-s3/{VERSION}/repository-s3-{VERSION}.zip

OPENSEARCH_VERSION="2.19.0"

# 플러그인 zip 다운로드
curl -L -O "https://artifacts.opensearch.org/releases/plugins/repository-s3/${OPENSEARCH_VERSION}/repository-s3-${OPENSEARCH_VERSION}.zip"

# 다운로드 확인
ls -lh repository-s3-${OPENSEARCH_VERSION}.zip
# 약 30~50MB 크기
```

### 2-3. Docker 이미지 저장 (방법 A용)

```bash
OPENSEARCH_VERSION="2.19.0"

# 공식 이미지 pull
docker pull opensearchproject/opensearch:${OPENSEARCH_VERSION}

# tar 파일로 저장
docker save opensearchproject/opensearch:${OPENSEARCH_VERSION} \
  -o opensearch-${OPENSEARCH_VERSION}.tar

# 크기 확인 (약 1~2GB)
ls -lh opensearch-${OPENSEARCH_VERSION}.tar
```

### 2-4. MinIO 이미지 저장 (MinIO도 폐쇄망에 배포하는 경우)

```bash
docker pull minio/minio:latest
docker save minio/minio:latest -o minio-latest.tar
```

### 2-5. 반입 파일 목록

폐쇄망에 반입할 파일:

```
반입 파일/
├── repository-s3-2.19.0.zip              # 플러그인 (커스텀 이미지 사용 시)
├── opensearch-2.19.0.tar                 # 공식 이미지 (방법 A용 또는 기본 이미지 반입)
├── Dockerfile.opensearch-s3              # 커스텀 이미지 Dockerfile (방법 A용)
└── minio-latest.tar                      # MinIO 이미지 (필요 시)
```

---

## 3. 방법 A: 커스텀 Docker 이미지 빌드 (권장)

플러그인이 포함된 커스텀 이미지를 빌드하여 Private Registry에 push하는 방법입니다.

### 3-1. Dockerfile 작성

```dockerfile
# Dockerfile.opensearch-s3
ARG OPENSEARCH_VERSION=2.19.0
FROM opensearchproject/opensearch:${OPENSEARCH_VERSION}

# repository-s3 플러그인 설치
# 방법 1: 로컬 파일에서 설치 (폐쇄망)
COPY repository-s3-${OPENSEARCH_VERSION}.zip /tmp/
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch \
    file:///tmp/repository-s3-${OPENSEARCH_VERSION}.zip && \
    rm /tmp/repository-s3-${OPENSEARCH_VERSION}.zip

# 방법 2: 인터넷 환경에서 빌드 시 (온라인)
# RUN /usr/share/opensearch/bin/opensearch-plugin install --batch repository-s3
```

### 3-2. 이미지 빌드 (인터넷 환경 또는 폐쇄망)

#### 인터넷 환경에서 빌드 후 이미지 반입

```bash
OPENSEARCH_VERSION="2.19.0"
REGISTRY="my-private-registry.example.com"

# 이미지 빌드
docker build \
  --build-arg OPENSEARCH_VERSION=${OPENSEARCH_VERSION} \
  -f Dockerfile.opensearch-s3 \
  -t ${REGISTRY}/opensearch-with-s3:${OPENSEARCH_VERSION} \
  .

# tar로 저장 (폐쇄망 반입용)
docker save ${REGISTRY}/opensearch-with-s3:${OPENSEARCH_VERSION} \
  -o opensearch-with-s3-${OPENSEARCH_VERSION}.tar
```

#### 폐쇄망에서 빌드 (Private Registry 있는 경우)

```bash
OPENSEARCH_VERSION="2.19.0"
REGISTRY="registry.internal.example.com:5000"

# 1. 기본 이미지 로드
docker load -i opensearch-${OPENSEARCH_VERSION}.tar

# 2. 플러그인 zip과 Dockerfile 준비
ls repository-s3-${OPENSEARCH_VERSION}.zip
ls Dockerfile.opensearch-s3

# 3. 커스텀 이미지 빌드
docker build \
  --build-arg OPENSEARCH_VERSION=${OPENSEARCH_VERSION} \
  -f Dockerfile.opensearch-s3 \
  -t ${REGISTRY}/opensearch-with-s3:${OPENSEARCH_VERSION} \
  .

# 4. Private Registry에 push
docker push ${REGISTRY}/opensearch-with-s3:${OPENSEARCH_VERSION}
```

### 3-3. Helm values.yaml 수정

```yaml
# infra/opensearch/values.yaml
image:
  repository: registry.internal.example.com:5000/opensearch-with-s3
  tag: "2.19.0"
  pullPolicy: IfNotPresent

replicas: 1
singleNode: true

persistence:
  size: 10Gi

resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"

extraEnvs:
  - name: DISABLE_SECURITY_PLUGIN
    value: "true"
  - name: DISABLE_INSTALL_DEMO_CONFIG
    value: "true"

service:
  type: ClusterIP

securityConfig:
  enabled: false

# S3 클라이언트 설정 (MinIO 연동)
config:
  opensearch.yml: |
    s3.client.default.endpoint: "minio.logging.svc.cluster.local:9000"
    s3.client.default.protocol: http
    s3.client.default.path_style_access: true
    s3.client.default.region: us-east-1
```

### 3-4. Helm 배포 또는 업그레이드

```bash
# 신규 배포
helm install opensearch opensearch/opensearch \
  --version 2.28.0 \
  -n logging \
  -f infra/opensearch/values.yaml

# 기존 배포 업그레이드 (이미지 변경 시)
helm upgrade opensearch opensearch/opensearch \
  --version 2.28.0 \
  -n logging \
  -f infra/opensearch/values.yaml
```

### 3-5. 플러그인 설치 확인

```bash
kubectl exec -n logging opensearch-cluster-master-0 -- \
  /usr/share/opensearch/bin/opensearch-plugin list | grep repository-s3
```

---

## 4. 방법 B: initContainer로 플러그인 설치

이미지 빌드가 어려운 환경에서, initContainer를 사용하여 Pod 시작 시 플러그인을 설치하는 방법입니다.

### 4-1. 플러그인 zip을 ConfigMap 또는 PV로 준비

#### 방법 B-1: httpd/nginx로 내부 파일 서빙

폐쇄망 내부에 간단한 파일 서버를 운영합니다:

```yaml
# infra/opensearch/plugin-server.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: plugin-server-files
  namespace: logging
data: {}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: plugin-server
  namespace: logging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: plugin-server
  template:
    metadata:
      labels:
        app: plugin-server
    spec:
      containers:
        - name: nginx
          image: nginx:alpine
          ports:
            - containerPort: 80
          volumeMounts:
            - name: plugins
              mountPath: /usr/share/nginx/html/plugins
      volumes:
        - name: plugins
          hostPath:
            path: /data/opensearch-plugins
            type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: plugin-server
  namespace: logging
spec:
  selector:
    app: plugin-server
  ports:
    - port: 80
      targetPort: 80
```

플러그인 파일을 노드에 복사:

```bash
# 플러그인 zip을 노드의 /data/opensearch-plugins/에 복사
scp repository-s3-2.19.0.zip user@node:/data/opensearch-plugins/
```

#### 방법 B-2: PV에 플러그인 저장

```yaml
# infra/opensearch/plugin-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: opensearch-plugins-pv
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadOnlyMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: manual
  hostPath:
    path: /data/opensearch-plugins
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: opensearch-plugins-pvc
  namespace: logging
spec:
  accessModes:
    - ReadOnlyMany
  storageClassName: manual
  resources:
    requests:
      storage: 1Gi
```

### 4-2. Helm values.yaml에 initContainer 추가

```yaml
# infra/opensearch/values.yaml
replicas: 1
singleNode: true

persistence:
  size: 10Gi

resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"

extraEnvs:
  - name: DISABLE_SECURITY_PLUGIN
    value: "true"
  - name: DISABLE_INSTALL_DEMO_CONFIG
    value: "true"

service:
  type: ClusterIP

securityConfig:
  enabled: false

# --- initContainer로 플러그인 설치 ---
extraInitContainers:
  - name: install-repository-s3
    image: opensearchproject/opensearch:2.19.0
    command:
      - sh
      - -c
      - |
        # 플러그인이 이미 설치되어 있는지 확인
        if /usr/share/opensearch/bin/opensearch-plugin list | grep -q repository-s3; then
          echo "repository-s3 plugin already installed, skipping."
        else
          echo "Installing repository-s3 plugin from local source..."
          /usr/share/opensearch/bin/opensearch-plugin install --batch \
            file:///tmp/plugins/repository-s3-2.19.0.zip
          echo "repository-s3 plugin installed successfully."
        fi
        # 설치된 플러그인을 공유 볼륨에 복사
        cp -r /usr/share/opensearch/plugins/repository-s3 /shared-plugins/
    volumeMounts:
      - name: plugin-source
        mountPath: /tmp/plugins
        readOnly: true
      - name: shared-plugins
        mountPath: /shared-plugins

extraVolumes:
  - name: plugin-source
    persistentVolumeClaim:
      claimName: opensearch-plugins-pvc
  - name: shared-plugins
    emptyDir: {}

extraVolumeMounts:
  - name: shared-plugins
    mountPath: /usr/share/opensearch/plugins/repository-s3
    subPath: repository-s3

# S3 클라이언트 설정
config:
  opensearch.yml: |
    s3.client.default.endpoint: "minio.logging.svc.cluster.local:9000"
    s3.client.default.protocol: http
    s3.client.default.path_style_access: true
    s3.client.default.region: us-east-1
```

### 4-3. 내부 파일 서버 방식 (initContainer + curl)

PV 대신 내부 파일 서버에서 다운로드하는 방식:

```yaml
extraInitContainers:
  - name: install-repository-s3
    image: opensearchproject/opensearch:2.19.0
    command:
      - sh
      - -c
      - |
        if /usr/share/opensearch/bin/opensearch-plugin list | grep -q repository-s3; then
          echo "repository-s3 already installed."
        else
          echo "Downloading plugin from internal server..."
          curl -f -o /tmp/repository-s3.zip \
            http://plugin-server.logging.svc.cluster.local/plugins/repository-s3-2.19.0.zip
          /usr/share/opensearch/bin/opensearch-plugin install --batch \
            file:///tmp/repository-s3.zip
          echo "Installation complete."
        fi
```

---

## 5. 방법 C: hostPath로 플러그인 디렉토리 마운트

노드에 직접 플러그인을 배치하고 hostPath로 마운트하는 방법입니다.

### 5-1. 노드에 플러그인 설치

```bash
# 1. 플러그인 zip을 노드에 복사
scp repository-s3-2.19.0.zip user@node:/tmp/

# 2. 노드에서 임시 컨테이너로 플러그인 추출
ssh user@node

# 3. 플러그인 설치 디렉토리 생성
sudo mkdir -p /data/opensearch-plugins/repository-s3

# 4. zip 추출
cd /data/opensearch-plugins/repository-s3
sudo unzip /tmp/repository-s3-2.19.0.zip

# 5. 권한 설정 (OpenSearch는 UID 1000으로 실행)
sudo chown -R 1000:1000 /data/opensearch-plugins/
```

### 5-2. Helm values.yaml 수정

```yaml
# infra/opensearch/values.yaml
extraVolumes:
  - name: repository-s3-plugin
    hostPath:
      path: /data/opensearch-plugins/repository-s3
      type: Directory

extraVolumeMounts:
  - name: repository-s3-plugin
    mountPath: /usr/share/opensearch/plugins/repository-s3
    readOnly: true
```

> **주의:** 멀티 노드 클러스터에서는 모든 노드에 동일하게 플러그인 파일을 배치해야 합니다.

---

## 6. 폐쇄망 이미지 관리

### 6-1. Private Registry로 이미지 반입

폐쇄망에 Private Registry(Harbor, Docker Registry 등)가 있는 경우:

```bash
# 인터넷 환경에서 저장한 tar 파일을 폐쇄망으로 이동 후:

# 1. Docker 이미지 로드
docker load -i opensearch-with-s3-2.19.0.tar

# 2. Private Registry로 태그 변경
docker tag opensearch-with-s3:2.19.0 \
  registry.internal.example.com:5000/opensearch-with-s3:2.19.0

# 3. Push
docker push registry.internal.example.com:5000/opensearch-with-s3:2.19.0
```

### 6-2. containerd 직접 Import (Registry 없는 경우)

Private Registry가 없는 경우 각 노드에서 직접 이미지를 로드합니다:

```bash
# containerd 환경 (K8s 1.24+)
# 각 OpenSearch가 실행될 노드에서:
sudo ctr -n k8s.io images import opensearch-with-s3-2.19.0.tar

# 또는 nerdctl 사용
sudo nerdctl -n k8s.io load -i opensearch-with-s3-2.19.0.tar
```

```bash
# crictl로 이미지 확인
sudo crictl images | grep opensearch
```

> **주의:** Registry 없이 직접 로드하는 경우, Helm values에서 `imagePullPolicy: Never` 또는 `IfNotPresent`로 설정해야 합니다.

```yaml
# values.yaml
image:
  repository: opensearch-with-s3
  tag: "2.19.0"
  pullPolicy: IfNotPresent    # Never도 가능
```

### 6-3. 필요한 이미지 전체 목록

폐쇄망에 반입해야 하는 전체 이미지 목록:

```bash
# 이미지 목록 추출 (인터넷 환경에서)
OPENSEARCH_VERSION="2.19.0"

# 필수 이미지
docker pull opensearchproject/opensearch:${OPENSEARCH_VERSION}
docker pull opensearchproject/opensearch-dashboards:${OPENSEARCH_VERSION}
docker pull minio/minio:latest
docker pull curlimages/curl:latest          # CronJob용 (스냅샷 자동화)
docker pull nginx:alpine                    # 플러그인 파일 서버용 (방법 B)

# 일괄 저장
docker save \
  opensearchproject/opensearch:${OPENSEARCH_VERSION} \
  opensearchproject/opensearch-dashboards:${OPENSEARCH_VERSION} \
  minio/minio:latest \
  curlimages/curl:latest \
  nginx:alpine \
  -o all-images-${OPENSEARCH_VERSION}.tar

# 크기 확인
ls -lh all-images-${OPENSEARCH_VERSION}.tar
```

---

## 7. 설치 후 자격증명 등록

플러그인 설치 후 MinIO 자격증명을 Keystore에 등록합니다.

### 7-1. Keystore 설정

```bash
# OpenSearch Pod에 접속
kubectl exec -it -n logging opensearch-cluster-master-0 -- bash

# Keystore에 MinIO 자격증명 추가
echo "minioadmin" | /usr/share/opensearch/bin/opensearch-keystore add \
  --stdin s3.client.default.access_key

echo "YOUR_MINIO_SECRET_KEY" | /usr/share/opensearch/bin/opensearch-keystore add \
  --stdin s3.client.default.secret_key

exit
```

### 7-2. 자격증명 리로드

```bash
curl -X POST "http://opensearch-cluster-master.logging.svc.cluster.local:9200/_nodes/reload_secure_settings"
```

### 7-3. Kubernetes Secret 기반 Keystore 초기화 (권장)

Pod 재시작 시에도 자격증명이 유지되도록 initContainer로 자동화합니다:

```yaml
# infra/opensearch/minio-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: opensearch-s3-credentials
  namespace: logging
type: Opaque
stringData:
  s3.client.default.access_key: "minioadmin"
  s3.client.default.secret_key: "YOUR_MINIO_SECRET_KEY"
```

```yaml
# values.yaml에 keystore initContainer 추가
extraInitContainers:
  - name: keystore-init
    image: opensearchproject/opensearch:2.19.0
    command:
      - sh
      - -c
      - |
        #!/bin/bash
        set -e
        # Keystore 파일이 없으면 생성
        KEYSTORE=/usr/share/opensearch/config/opensearch.keystore
        if [ ! -f "$KEYSTORE" ]; then
          /usr/share/opensearch/bin/opensearch-keystore create
        fi

        # S3 자격증명 등록
        echo "$S3_ACCESS_KEY" | /usr/share/opensearch/bin/opensearch-keystore add \
          --stdin --force s3.client.default.access_key
        echo "$S3_SECRET_KEY" | /usr/share/opensearch/bin/opensearch-keystore add \
          --stdin --force s3.client.default.secret_key

        # Keystore를 공유 볼륨으로 복사
        cp $KEYSTORE /keystore/opensearch.keystore
        echo "Keystore initialized with S3 credentials."
    env:
      - name: S3_ACCESS_KEY
        valueFrom:
          secretKeyRef:
            name: opensearch-s3-credentials
            key: s3.client.default.access_key
      - name: S3_SECRET_KEY
        valueFrom:
          secretKeyRef:
            name: opensearch-s3-credentials
            key: s3.client.default.secret_key
    volumeMounts:
      - name: keystore
        mountPath: /keystore

extraVolumes:
  - name: keystore
    emptyDir: {}

extraVolumeMounts:
  - name: keystore
    mountPath: /usr/share/opensearch/config/opensearch.keystore
    subPath: opensearch.keystore
```

---

## 8. 전체 배포 절차 (통합)

### 8-1. 방법 A 기준 전체 절차

```
[인터넷 환경]
    │
    ├── 1. OpenSearch 이미지 pull
    ├── 2. repository-s3 플러그인 zip 다운로드
    ├── 3. 커스텀 이미지 빌드 (Dockerfile)
    ├── 4. docker save로 tar 저장
    ├── 5. 파일 반입 (USB/SCP 등)
    │
    ↓
[폐쇄망 환경]
    │
    ├── 6. docker load로 이미지 로드
    ├── 7. Private Registry에 push (있는 경우)
    ├── 8. values.yaml 수정 (image 변경)
    ├── 9. MinIO Secret 생성
    ├── 10. Helm install/upgrade
    ├── 11. 플러그인 설치 확인
    ├── 12. Keystore에 자격증명 등록
    └── 13. 스냅샷 리포지토리 등록 (Dev Tools)
```

### 8-2. 단계별 실행 스크립트

```bash
#!/bin/bash
# scripts/setup-s3-plugin.sh
# 폐쇄망 환경에서 실행하는 통합 설정 스크립트
set -euo pipefail

NAMESPACE="logging"
OPENSEARCH_POD="opensearch-cluster-master-0"
OPENSEARCH_URL="http://opensearch-cluster-master.logging.svc.cluster.local:9200"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== OpenSearch S3 Plugin Setup (Air-gapped) ===${NC}"

# 1. 플러그인 설치 확인
echo -e "${YELLOW}1. Checking repository-s3 plugin...${NC}"
PLUGIN_CHECK=$(kubectl exec -n ${NAMESPACE} ${OPENSEARCH_POD} -- \
  /usr/share/opensearch/bin/opensearch-plugin list 2>/dev/null | grep repository-s3 || true)

if [ -n "$PLUGIN_CHECK" ]; then
  echo -e "${GREEN}   ✓ repository-s3 plugin is installed${NC}"
else
  echo -e "${RED}   ✗ repository-s3 plugin NOT found. Please install using Method A, B, or C.${NC}"
  exit 1
fi

# 2. MinIO Secret 생성
echo -e "${YELLOW}2. Creating MinIO credentials secret...${NC}"
kubectl create secret generic opensearch-s3-credentials \
  -n ${NAMESPACE} \
  --from-literal=s3.client.default.access_key=minioadmin \
  --from-literal=s3.client.default.secret_key=changeme \
  --dry-run=client -o yaml | kubectl apply -f -
echo -e "${GREEN}   ✓ Secret created${NC}"

# 3. Keystore에 자격증명 등록
echo -e "${YELLOW}3. Registering S3 credentials in keystore...${NC}"
kubectl exec -n ${NAMESPACE} ${OPENSEARCH_POD} -- bash -c '
  echo "minioadmin" | /usr/share/opensearch/bin/opensearch-keystore add --stdin --force s3.client.default.access_key
  echo "changeme" | /usr/share/opensearch/bin/opensearch-keystore add --stdin --force s3.client.default.secret_key
'
echo -e "${GREEN}   ✓ Credentials registered${NC}"

# 4. Secure settings 리로드
echo -e "${YELLOW}4. Reloading secure settings...${NC}"
kubectl exec -n ${NAMESPACE} ${OPENSEARCH_POD} -- \
  curl -sf -X POST "${OPENSEARCH_URL}/_nodes/reload_secure_settings" > /dev/null
echo -e "${GREEN}   ✓ Settings reloaded${NC}"

# 5. 스냅샷 리포지토리 등록
echo -e "${YELLOW}5. Registering snapshot repository...${NC}"
kubectl exec -n ${NAMESPACE} ${OPENSEARCH_POD} -- \
  curl -sf -X PUT "${OPENSEARCH_URL}/_snapshot/minio-s3-repo" \
    -H 'Content-Type: application/json' \
    -d '{
      "type": "s3",
      "settings": {
        "bucket": "opensearch-snapshots",
        "base_path": "snapshots",
        "path_style_access": true,
        "compress": true
      }
    }' > /dev/null
echo -e "${GREEN}   ✓ Repository registered${NC}"

# 6. 리포지토리 검증
echo -e "${YELLOW}6. Verifying repository connection...${NC}"
VERIFY=$(kubectl exec -n ${NAMESPACE} ${OPENSEARCH_POD} -- \
  curl -sf -X POST "${OPENSEARCH_URL}/_snapshot/minio-s3-repo/_verify" 2>/dev/null)
if echo "$VERIFY" | grep -q "nodes"; then
  echo -e "${GREEN}   ✓ Repository verified successfully${NC}"
else
  echo -e "${RED}   ✗ Repository verification failed${NC}"
  echo "$VERIFY"
  exit 1
fi

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo -e "스냅샷 리포지토리: minio-s3-repo"
echo -e "다음 단계: ISM 정책 및 SM 정책 생성 (08-dashboards-ui-guide.md 참고)"
```

---

## 9. 트러블슈팅

### 9-1. 플러그인 설치 오류

| 오류 | 원인 | 해결 |
|------|------|------|
| `Plugin version mismatch` | 플러그인과 OpenSearch 버전 불일치 | 정확히 같은 버전의 zip 다운로드 |
| `java.lang.SecurityException` | 플러그인 서명 검증 실패 | `--batch` 플래그 사용 |
| `Plugin already exists` | 이미 설치됨 | `opensearch-plugin list`로 확인 |
| `AccessDeniedException` | 파일 권한 문제 | `chown -R 1000:1000` 실행 |

### 9-2. 이미지 관련 오류

| 오류 | 원인 | 해결 |
|------|------|------|
| `ImagePullBackOff` | 이미지를 찾을 수 없음 | `imagePullPolicy: IfNotPresent` 확인, 이미지 로드 확인 |
| `ErrImageNeverPull` | `pullPolicy: Never`인데 이미지 없음 | 해당 노드에서 `ctr images import` 실행 |
| `unauthorized` | Registry 인증 실패 | `imagePullSecrets` 설정 |

### 9-3. initContainer 실패

```bash
# initContainer 로그 확인
kubectl logs -n logging opensearch-cluster-master-0 -c install-repository-s3
kubectl logs -n logging opensearch-cluster-master-0 -c keystore-init

# Pod 이벤트 확인
kubectl describe pod -n logging opensearch-cluster-master-0
```

### 9-4. 플러그인 버전 확인 방법

```bash
# 현재 OpenSearch 버전
kubectl exec -n logging opensearch-cluster-master-0 -- \
  curl -s localhost:9200 | python3 -c "import json,sys; print(json.load(sys.stdin)['version']['number'])"

# 설치된 플러그인 및 버전
kubectl exec -n logging opensearch-cluster-master-0 -- \
  /usr/share/opensearch/bin/opensearch-plugin list
```

---

## 10. 체크리스트

### 인터넷 환경에서 준비

- [ ] OpenSearch 버전 확인 (예: 2.19.0)
- [ ] `repository-s3-{VERSION}.zip` 다운로드
- [ ] 기본 이미지 docker save (또는 커스텀 이미지 빌드)
- [ ] MinIO 이미지 docker save
- [ ] 기타 필요 이미지 docker save (nginx, curl 등)
- [ ] 모든 파일을 USB/이동매체에 저장

### 폐쇄망에서 설치

- [ ] 이미지 docker load / ctr import
- [ ] Private Registry push (Registry 있는 경우)
- [ ] MinIO 배포 및 버킷 생성
- [ ] `values.yaml` 수정 (image, config, initContainers)
- [ ] MinIO Secret 생성
- [ ] Helm install/upgrade
- [ ] Pod 정상 기동 확인
- [ ] `opensearch-plugin list`로 repository-s3 확인
- [ ] Keystore 자격증명 등록
- [ ] 스냅샷 리포지토리 등록 및 검증
- [ ] 테스트 스냅샷 생성/삭제 확인
