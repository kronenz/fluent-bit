# loadtest-tools 0.1.2 — Air-gap 배포 번들

`loadtest-tools:0.1.2` 통합 이미지를 폐쇄망 Nexus Docker Repo 에 업로드하기
위한 단일 번들.

## 0.1.1 → 0.1.2 변경 (왜 새 버전?)

| 항목 | 0.1.1 | 0.1.2 |
|------|-------|-------|
| OSB workload corpus | 정의만 (workload.json) | **14개 워크로드 test-mode corpus baked** (geonames / nyc_taxis / pmc / nested / noaa / http_logs / eventdata / geopoint / geopointshape / geoshape / percolator / so / ...) |
| OSB offline `.offset` | ❌ FAIL: SystemSetupError | ✅ loader.py monkey-patch + 로컬 `.offset` 사전 생성 |
| k6 telemetry phone-home | default ON (silent fail) | `K6_NO_USAGE_REPORT=true` ENV 적용 |
| 이미지 크기 | 257 MB (gz) | **300 MB (gz)** (corpus +93 MB) |

폐쇄망 (iptables FORWARD egress 차단) 환경에서 OS-01 OSB Job 정상 종료
검증 완료 (testbed: 15초, p50 137 ms, 1k docs SUCCESS).

## 구성

```
loadtest-airgap-bundle-0.1.2/
├── README.md                              ← 본 문서
├── image/
│   ├── loadtest-tools-0.1.2.tar.gz        ← Docker image (300 MB)
│   └── loadtest-tools-0.1.2.tar.gz.sha256 ← 무결성 검증
├── scripts/
│   └── push-to-nexus.sh                   ← 자동 업로드 스크립트
└── docs/
    └── 09-nexus-upload-guide.md           ← 단계별 가이드 (한글)
```

## 빠른 사용법

### 1. 폐쇄망 호스트로 전송

```bash
# tar.gz 단일 파일 전송 (권장)
scp dist/loadtest-airgap-bundle-0.1.2.tar.gz <airgap-host>:/tmp/

# 또는 디렉터리 통째로
scp -r loadtest-airgap-bundle-0.1.2/ <airgap-host>:/tmp/
```

### 2. 무결성 검증

```bash
ssh <airgap-host>
cd /tmp
tar xzf loadtest-airgap-bundle-0.1.2.tar.gz
cd loadtest-airgap-bundle-0.1.2/image
sha256sum -c loadtest-tools-0.1.2.tar.gz.sha256
# loadtest-tools-0.1.2.tar.gz: OK
```

### 3. 자동 업로드 (권장)

```bash
export REGISTRY=nexus.intranet:8082/loadtest
export NEXUS_USER=deployer
export NEXUS_PASS='your-password'
export TAG=0.1.2

bash ../scripts/push-to-nexus.sh ./loadtest-tools-0.1.2.tar.gz
```

### 4. 수동 업로드 (참고)

```bash
gunzip -c loadtest-tools-0.1.2.tar.gz | docker load
# Loaded image: loadtest-tools:0.1.2

docker tag loadtest-tools:0.1.2 nexus.intranet:8082/loadtest/loadtest-tools:0.1.2
docker login nexus.intranet:8082
docker push nexus.intranet:8082/loadtest/loadtest-tools:0.1.2
```

## 검증 (다른 노드에서 pull)

```bash
docker pull nexus.intranet:8082/loadtest/loadtest-tools:0.1.2
docker run --rm nexus.intranet:8082/loadtest/loadtest-tools:0.1.2 k6 version
docker run --rm nexus.intranet:8082/loadtest/loadtest-tools:0.1.2 opensearch-benchmark --version

# OSB workload corpus 보유 확인
docker run --rm --network=none nexus.intranet:8082/loadtest/loadtest-tools:0.1.2 \
  bash -c 'for d in /root/.benchmark/benchmarks/data/*/; do W=$(basename $d); N=$(ls $d 2>/dev/null | wc -l); echo "$W: $N files"; done'
# geonames: 3 files
# nyc_taxis: 3 files
# ...
```

## K8s 매니페스트 갱신

```bash
cd deploy/load-testing-airgap

# kustomize image override
kustomize edit set image loadtest-tools=nexus.intranet:8082/loadtest/loadtest-tools:0.1.2

# 또는 sed 일괄 변경 (이미 0.1.2 가 default)
grep -rl 'loadtest-tools:0.1.1' . | xargs sed -i 's|loadtest-tools:0.1.1|loadtest-tools:0.1.2|g'

kubectl apply -f 00-prerequisites/
kubectl apply -f 10-load-generators/
```

## 추가 의존 (별도 mirror 필요)

이 번들은 `loadtest-tools:0.1.2` 만 포함합니다. 매니페스트는 `pause:3.10` 도
사용 (kube-burner 의 burner-pod 템플릿) — Nexus 에 별도 mirror 필요:

```bash
docker pull registry.k8s.io/pause:3.10
docker tag registry.k8s.io/pause:3.10 nexus.intranet:8082/loadtest/pause:3.10
docker push nexus.intranet:8082/loadtest/pause:3.10
```

## 관련 문서

- [09-nexus-upload-guide.md](docs/09-nexus-upload-guide.md) — 단계별 가이드
- [docs/load-testing/15-nexus-push-quick.md](../../docs/load-testing/15-nexus-push-quick.md) — 빠른 명령어 버전
- [deploy/load-testing-airgap/README.md](../../deploy/load-testing-airgap/README.md) — 매니페스트 사용법
