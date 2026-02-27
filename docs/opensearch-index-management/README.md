# OpenSearch 인덱스 관리 및 ISM 정책 가이드

## 개요

Kubernetes 기반 빅데이터 서비스팀 클러스터에서 Fluent Bit으로 수집되는 로그를 OpenSearch에서 체계적으로 관리하기 위한 인덱스 전략 및 ISM(Index State Management) 정책 문서입니다.

> **참고:** OpenSearch는 Elasticsearch의 ILM(Index Lifecycle Management) 대신 **ISM(Index State Management)** 을 사용합니다. 본 문서에서는 ISM 기반으로 정책을 수립합니다.

## 대상 로그 유형

| 로그 유형 | 설명 | 수집 방식 |
|-----------|------|-----------|
| **Container Log** | 애플리케이션 컨테이너 stdout/stderr 로그 | Fluent Bit tail 플러그인 |
| **Kubernetes Event Log** | K8s 클러스터 이벤트 (Pod 스케줄링, 에러 등) | Fluent Bit kubernetes_events 플러그인 |
| **Systemd Log** | 노드 레벨 systemd 서비스 로그 (kubelet, containerd 등) | Fluent Bit systemd 플러그인 |

## 클러스터 구성

```
┌─────────────────────────────────────────────────────────────────────┐
│                    중앙 OpenSearch 클러스터                           │
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│  │ Cluster-A   │  │ Cluster-B   │  │ Cluster-C   │   ...          │
│  │ 인덱스 그룹  │  │ 인덱스 그룹  │  │ 인덱스 그룹  │                │
│  │             │  │             │  │             │                │
│  │ - container │  │ - container │  │ - container │                │
│  │ - k8sevent  │  │ - k8sevent  │  │ - k8sevent  │                │
│  │ - systemd   │  │ - systemd   │  │ - systemd   │                │
│  └─────────────┘  └─────────────┘  └─────────────┘                │
│                                                                     │
│  ISM 정책 → 자동 rollover / retention / delete                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 문서 구조

| 문서 | 설명 |
|------|------|
| [01-index-naming-strategy.md](./01-index-naming-strategy.md) | 인덱스 네이밍 컨벤션 및 전략 |
| [02-index-templates.md](./02-index-templates.md) | 인덱스 템플릿 설정 (매핑, 설정, 별칭) |
| [03-ism-policies.md](./03-ism-policies.md) | ISM 정책 설계 및 적용 방법 |
| [04-fluent-bit-output-config.md](./04-fluent-bit-output-config.md) | Fluent Bit 멀티 인덱스 출력 설정 |
| [05-operations-guide.md](./05-operations-guide.md) | 운영 가이드 (모니터링, 트러블슈팅, 백업) |
| [06-s3-cold-storage.md](./06-s3-cold-storage.md) | S3 기반 Cold 데이터 저장 가이드 |
| [07-snapshot-guide.md](./07-snapshot-guide.md) | OpenSearch 스냅샷 적용 가이드 (SM 자동화 포함) |
| [08-dashboards-ui-guide.md](./08-dashboards-ui-guide.md) | **Dashboards UI 기반 ISM + Snapshot (MinIO S3) 설정 가이드** |
| [09-airgapped-plugin-install.md](./09-airgapped-plugin-install.md) | **폐쇄망 환경 repository-s3 플러그인 설치 가이드** |

## 적용 템플릿 파일

`templates/` 디렉토리에 바로 적용 가능한 설정 파일이 포함되어 있습니다.

```
templates/
├── ism-policy-container-logs.json       # Container 로그 ISM 정책 (로컬 전용)
├── ism-policy-container-logs-s3.json    # Container 로그 ISM 정책 (S3 Cold tier)
├── ism-policy-k8s-events.json           # K8s Event 로그 ISM 정책
├── ism-policy-systemd-logs.json         # Systemd 로그 ISM 정책 (로컬 전용)
├── ism-policy-systemd-logs-s3.json      # Systemd 로그 ISM 정책 (S3 archive)
├── index-template-container-logs.json   # Container 로그 인덱스 템플릿
├── index-template-k8s-events.json       # K8s Event 로그 인덱스 템플릿
├── index-template-systemd-logs.json     # Systemd 로그 인덱스 템플릿
├── sm-policy-daily-snapshots.json       # SM 자동 스냅샷 정책
└── fluent-bit-outputs.yaml              # Fluent Bit CRD 출력 설정
```

## 빠른 시작

### 1단계: ISM 정책 생성

```bash
# Container 로그 ISM 정책
curl -X PUT "https://opensearch:9200/_plugins/_ism/policies/container-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-container-logs.json

# K8s Event 로그 ISM 정책
curl -X PUT "https://opensearch:9200/_plugins/_ism/policies/k8s-events-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-k8s-events.json

# Systemd 로그 ISM 정책
curl -X PUT "https://opensearch:9200/_plugins/_ism/policies/systemd-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-systemd-logs.json
```

### 2단계: 인덱스 템플릿 생성

```bash
# Container 로그 인덱스 템플릿
curl -X PUT "https://opensearch:9200/_index_template/container-logs-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-container-logs.json

# K8s Event 로그 인덱스 템플릿
curl -X PUT "https://opensearch:9200/_index_template/k8s-events-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-k8s-events.json

# Systemd 로그 인덱스 템플릿
curl -X PUT "https://opensearch:9200/_index_template/systemd-logs-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-systemd-logs.json
```

### 3단계: Fluent Bit 출력 설정 적용

```bash
kubectl apply -f templates/fluent-bit-outputs.yaml
```

자세한 내용은 각 문서를 참고하세요.
