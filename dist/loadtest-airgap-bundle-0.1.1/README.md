# loadtest-tools 0.1.1 — Air-gap 배포 번들

`loadtest-tools:0.1.1` 통합 이미지를 폐쇄망 Nexus Docker Repo에 업로드하기 위한 단일 번들입니다.

## 구성

```
loadtest-airgap-bundle-0.1.1/
├── README.md                              ← 본 문서
├── image/
│   ├── loadtest-tools-0.1.1.tar.gz       ← Docker image (257 MB)
│   └── loadtest-tools-0.1.1.tar.gz.sha256 ← 무결성 검증
├── scripts/
│   └── push-to-nexus.sh                   ← 자동 업로드 스크립트
└── docs/
    └── 09-nexus-upload-guide.md           ← 단계별 가이드 (한글)
```

## 빠른 사용법

### 1. 폐쇄망 호스트로 전송
```bash
scp -r loadtest-airgap-bundle-0.1.1/ <airgap-host>:/tmp/
# 또는 단일 tar.gz 형태로 묶어서 전송 (아래 참조)
```

### 2. 무결성 검증
```bash
ssh <airgap-host>
cd /tmp/loadtest-airgap-bundle-0.1.1/image
sha256sum -c loadtest-tools-0.1.1.tar.gz.sha256
```

### 3. Nexus에 업로드
```bash
cd /tmp/loadtest-airgap-bundle-0.1.1
export REGISTRY="nexus.intranet:8082/loadtest"
export NEXUS_USER="<your-user>"
export NEXUS_PASS="<your-pass>"
bash scripts/push-to-nexus.sh image/loadtest-tools-0.1.1.tar.gz
```

스크립트가 수행:
1. SHA256 검증
2. `docker load < tar.gz`
3. `docker tag loadtest-tools:0.1.1 → ${REGISTRY}/loadtest-tools:0.1.1`
4. `docker login ${NEXUS_HOST}` (자격 증명 있을 시)
5. `docker push`

### 4. 검증
```bash
docker pull nexus.intranet:8082/loadtest/loadtest-tools:0.1.1
docker run --rm nexus.intranet:8082/loadtest/loadtest-tools:0.1.1 k6 version
```

## 상세 가이드

`docs/09-nexus-upload-guide.md` 참조 — Nexus repository 생성, 인증서 설정, 매니페스트 업데이트, 트러블슈팅 등 모든 단계 한글로 정리.

## 이미지 명세

| 항목 | 값 |
|---|---|
| 이미지명 | `loadtest-tools:0.1.1` |
| 압축 크기 | 257 MB (gzipped) |
| 압축 해제 크기 | ~1.05 GB |
| Base | `python:3.11-slim` |
| SHA256 (gzipped) | `b02884e2127f2b814d42fd45dbe0ba9ba87124e9454499cad5efd7bf2ebe9d04` |

### 포함된 도구 (모두 오프라인 동작)

| 도구 | 버전 | 용도 |
|---|---|---|
| k6 | 0.55.0 | HTTP 부하 (PromQL/검색) |
| hey | latest | HTTP 간이 부하 |
| kube-burner | v1.13.0 | K8s 오브젝트 대량 생성 |
| flog | 0.4.3 | 합성 로그 생성기 |
| avalanche | v0.7.0 | 합성 메트릭 타깃 |
| elasticsearch_exporter | v1.8.0 | OpenSearch 메트릭 수집 |
| opensearch-benchmark | 1.7.0 (pip) | OS 인덱싱·검색 벤치마크 |
| kubectl | 1.32.0 | K8s 클라이언트 |
| curl, jq, bash, tini, python3 | (apt/system) | 부속 |

### 번들된 추가 자산

| 자산 | 위치 (이미지 안) | 용도 |
|---|---|---|
| OpenSearch benchmark workloads | `/opt/osb-workloads/` | OS-01 시나리오 (geonames, http_logs 등 25개 워크로드 정의) |

`opensearch-benchmark` 워크로드 corpus 데이터(`.json.bz2`)는 크기 때문에 **번들에 포함되지 않습니다**. 두 가지 사용 방법:
- **`OSB_TEST_MODE=true`** (기본): 1k docs로 워크로드 절차 검증 (corpus 불필요)
- **`OSB_TEST_MODE=false`**: 운영 부하 측정 — corpus를 PVC로 사전 마운트 필요 (`docs/09-nexus-upload-guide.md` §8.5.2 참조)

## 검증 — 완전 오프라인 동작

```bash
# 폐쇄망에서도 다음과 같이 격리 모드 동작
docker run --rm --network=none loadtest-tools:0.1.1 bash -c '
  k6 version
  kube-burner version
  opensearch-benchmark --version
  ls /opt/osb-workloads/ | wc -l   # 25
'
```

## 매니페스트 갱신

이미지를 업로드한 후, K8s 매니페스트가 Nexus 경로를 참조하도록:

```bash
cd deploy/load-testing
kustomize edit set image loadtest-tools=nexus.intranet:8082/loadtest/loadtest-tools:0.1.1
kubectl apply -k .
```

## 버전 변경 시

새 버전(예: 0.1.2)이 필요하면 외부망에서:
```bash
cd docker/loadtest-tools
TAG=0.1.2 bash build.sh
TAG=0.1.2 bash save-image.sh
# → 새 번들 패키징 (이 README와 동일한 구조)
```
