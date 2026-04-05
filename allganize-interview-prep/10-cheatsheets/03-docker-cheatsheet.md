# Docker / 컨테이너 치트시트 (Cheatsheet)

> **TL;DR**
> 1. Docker는 이미지 빌드 + 컨테이너 실행, 프로덕션 K8s에서는 containerd가 런타임
> 2. 멀티스테이지 빌드(Multi-stage Build)로 이미지 크기를 최소화하라
> 3. `crictl`은 K8s 노드에서 containerd를 직접 디버깅하는 도구

---

## 1. Docker 핵심 명령어

### 이미지 관리

```bash
# 빌드
docker build -t myapp:1.0 .
docker build -t myapp:1.0 -f Dockerfile.prod .
docker build --no-cache -t myapp:1.0 .

# 이미지 조회
docker images
docker image ls --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# 태그 / 푸시
docker tag myapp:1.0 registry.io/myapp:1.0
docker push registry.io/myapp:1.0

# 이미지 정보
docker inspect myapp:1.0
docker history myapp:1.0           # 레이어별 크기 확인
```

### 컨테이너 실행

```bash
# 실행
docker run -d --name web -p 8080:80 nginx
docker run -it --rm alpine sh      # 일회성 실행
docker run -d -v /data:/app/data \
  -e DB_HOST=db myapp:1.0

# 관리
docker ps                          # 실행 중 컨테이너
docker ps -a                       # 전체 (종료 포함)
docker stop web && docker rm web
docker rm -f web                   # 강제 삭제

# 디버깅
docker logs web
docker logs -f --tail 100 web     # 최근 100줄 + follow
docker exec -it web /bin/sh
docker stats                       # 리소스 사용량
docker top web                     # 프로세스 목록
```

### 정리 (Cleanup)

```bash
docker system prune                # 미사용 리소스 정리
docker system prune -a --volumes   # 전체 정리 (주의!)
docker image prune -a              # 미사용 이미지 삭제
docker volume prune                # 미사용 볼륨 삭제
```

---

## 2. Dockerfile 작성 패턴

### 멀티스테이지 빌드 (Multi-stage Build)

```dockerfile
# Stage 1: 빌드
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o server .

# Stage 2: 실행 (최소 이미지)
FROM alpine:3.19
RUN apk --no-cache add ca-certificates
COPY --from=builder /app/server /server
EXPOSE 8080
USER 1000
ENTRYPOINT ["/server"]
```

### Dockerfile 모범 사례

```dockerfile
# 1. 경량 베이스 이미지
FROM python:3.12-slim

# 2. 레이어 캐싱 최적화 (변경 적은 것 먼저)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# 3. 비루트 사용자
RUN adduser --disabled-password appuser
USER appuser

# 4. ENTRYPOINT + CMD 조합
ENTRYPOINT ["python"]
CMD ["app.py"]
```

### .dockerignore

```text
.git
.gitignore
node_modules
*.md
.env
.env.*
Dockerfile
docker-compose*.yml
__pycache__
.pytest_cache
```

---

## 3. docker-compose 핵심

```yaml
# docker-compose.yml
version: "3.8"

services:
  web:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8080:80"
    environment:
      - DB_HOST=db
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - app-net

  db:
    image: postgres:16-alpine
    volumes:
      - db-data:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: secret
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - app-net

volumes:
  db-data:

networks:
  app-net:
```

```bash
# compose 명령어
docker compose up -d
docker compose down
docker compose down -v             # 볼륨까지 삭제
docker compose logs -f web
docker compose ps
docker compose exec web sh
docker compose build --no-cache
```

---

## 4. crictl 명령어 (K8s 환경)

K8s 노드에서 containerd 직접 디버깅 시 사용.

```bash
# 파드 조회
crictl pods
crictl pods --name nginx

# 컨테이너 조회
crictl ps
crictl ps -a                       # 종료된 것 포함

# 로그
crictl logs <CONTAINER_ID>
crictl logs --tail 50 <CONTAINER_ID>

# 이미지
crictl images
crictl pull nginx:1.25
crictl rmi <IMAGE_ID>

# 컨테이너 상세 / 디버깅
crictl inspect <CONTAINER_ID>
crictl exec -it <CONTAINER_ID> sh
crictl stats

# 파드 상세
crictl inspectp <POD_ID>
```

| docker 명령어 | crictl 명령어 | 비고 |
|---|---|---|
| `docker ps` | `crictl ps` | 컨테이너 목록 |
| `docker images` | `crictl images` | 이미지 목록 |
| `docker logs` | `crictl logs` | 로그 확인 |
| `docker exec` | `crictl exec` | 컨테이너 진입 |
| `docker inspect` | `crictl inspect` | 상세 정보 |
| (없음) | `crictl pods` | 파드 목록 |

---

## 5. 이미지 최적화 팁

| 전략 | 효과 | 방법 |
|---|---|---|
| 경량 베이스 이미지 | 크기 80%+ 감소 | `alpine`, `slim`, `distroless` 사용 |
| 멀티스테이지 빌드 | 빌드 도구 제외 | `FROM ... AS builder` |
| 레이어 캐싱 | 빌드 속도 향상 | 변경 적은 레이어를 위에 배치 |
| `.dockerignore` | 불필요 파일 제외 | `.git`, `node_modules` 등 |
| `--no-cache-dir` | pip 캐시 제거 | `pip install --no-cache-dir` |
| 단일 RUN 명령 | 레이어 수 감소 | `RUN apt update && apt install -y ... && rm -rf /var/lib/apt/lists/*` |

### 이미지 크기 비교

```text
# 같은 Go 앱 기준
golang:1.22          ~850MB
golang:1.22-alpine   ~260MB
멀티스테이지+alpine    ~15MB
멀티스테이지+scratch    ~8MB
distroless            ~20MB
```

### 보안 모범 사례

```dockerfile
# 비루트 사용자 실행
USER 1000

# 읽기 전용 파일시스템 (docker run 시)
docker run --read-only --tmpfs /tmp myapp

# 이미지 스캔
docker scout cves myapp:1.0
trivy image myapp:1.0
```

---

## 6. 면접 빈출 질문

**Q1. `ENTRYPOINT`와 `CMD`의 차이는?**
> - `ENTRYPOINT`: 컨테이너 시작 시 항상 실행되는 명령 (변경 어려움)
> - `CMD`: 기본 인자, `docker run` 시 덮어쓰기 가능
> - 조합: `ENTRYPOINT ["python"]` + `CMD ["app.py"]` -> `python app.py`
> - `docker run myapp test.py` -> `python test.py` (CMD만 대체)

**Q2. Docker 이미지 레이어(Layer)란 무엇이며 왜 중요한가?**
> - Dockerfile의 각 명령이 하나의 읽기 전용 레이어를 생성
> - 레이어는 Union File System으로 쌓여 하나의 파일시스템처럼 동작
> - 레이어 캐싱: 변경이 없는 레이어는 재빌드하지 않아 빌드 속도 향상
> - 레이어 공유: 같은 베이스 이미지를 쓰는 컨테이너는 레이어를 공유

**Q3. K8s에서 Docker 대신 containerd를 사용하는 이유는?**
> - K8s 1.24부터 dockershim 제거 (Docker 직접 지원 중단)
> - containerd는 CRI(Container Runtime Interface) 직접 지원
> - Docker는 containerd 위에 추가 기능을 얹은 것 (불필요한 오버헤드)
> - 빌드는 Docker/BuildKit, 런타임은 containerd로 역할 분리

---

**핵심 키워드**: `Multi-stage Build`, `Layer Caching`, `containerd`, `crictl`, `distroless`
