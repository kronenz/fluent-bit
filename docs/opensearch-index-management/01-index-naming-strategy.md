# 인덱스 네이밍 컨벤션 및 전략

## 1. 네이밍 규칙

### 기본 패턴

```
{로그유형}-{클러스터명}-{날짜}
```

### 로그 유형별 인덱스 네이밍

| 로그 유형 | 인덱스 패턴 | 예시 |
|-----------|------------|------|
| Container Log | `container-logs-{cluster}-YYYY.MM.DD` | `container-logs-bigdata-prod-2026.02.26` |
| K8s Event Log | `k8s-events-{cluster}-YYYY.MM.DD` | `k8s-events-bigdata-prod-2026.02.26` |
| Systemd Log | `systemd-logs-{cluster}-YYYY.MM.DD` | `systemd-logs-bigdata-prod-2026.02.26` |

### 클러스터명 규칙

클러스터명은 환경과 용도를 포함하도록 명명합니다.

```
{팀/서비스}-{환경}
```

| 클러스터 | 클러스터명 | 설명 |
|----------|-----------|------|
| 빅데이터 운영 | `bigdata-prod` | 빅데이터팀 운영 클러스터 |
| 빅데이터 개발 | `bigdata-dev` | 빅데이터팀 개발 클러스터 |
| ML 플랫폼 운영 | `ml-platform-prod` | ML 플랫폼 운영 클러스터 |
| 데이터파이프라인 | `datapipe-prod` | 데이터 파이프라인 클러스터 |

## 2. 인덱스 구조 설계

### 전체 인덱스 맵

```
OpenSearch
├── container-logs-bigdata-prod-2026.02.26
├── container-logs-bigdata-prod-2026.02.25
├── container-logs-bigdata-prod-2026.02.24
├── container-logs-bigdata-dev-2026.02.26
├── container-logs-ml-platform-prod-2026.02.26
│
├── k8s-events-bigdata-prod-2026.02.26
├── k8s-events-bigdata-prod-2026.02.25
├── k8s-events-bigdata-dev-2026.02.26
│
├── systemd-logs-bigdata-prod-2026.02.26
├── systemd-logs-bigdata-prod-2026.02.25
├── systemd-logs-bigdata-dev-2026.02.26
│
└── ... (클러스터 수 × 로그유형 3 × 보관일수)
```

### 일일 인덱스 수 산정

```
일일 인덱스 수 = 클러스터 수 × 3 (로그 유형)
```

| 클러스터 수 | 일일 인덱스 | 30일 총 인덱스 | 90일 총 인덱스 |
|------------|-----------|-------------|-------------|
| 3개 | 9개 | 270개 | 810개 |
| 5개 | 15개 | 450개 | 1,350개 |
| 10개 | 30개 | 900개 | 2,700개 |

> **주의:** OpenSearch 클러스터의 인덱스 수가 증가하면 클러스터 상태 관리 오버헤드가 커집니다. 노드당 인덱스 수는 **1,000개 이하**를 권장합니다.

## 3. Rollover 기반 인덱스 관리 (권장)

일자별 인덱스 대신 **Rollover** 방식을 사용하면 인덱스 크기를 균일하게 관리할 수 있습니다.

### Rollover 인덱스 패턴

```
{로그유형}-{클러스터}-000001
{로그유형}-{클러스터}-000002
{로그유형}-{클러스터}-000003
...
```

### Rollover 조건

| 조건 | Container Log | K8s Event | Systemd Log |
|------|--------------|-----------|-------------|
| 최대 크기 | 30GB | 10GB | 20GB |
| 최대 문서 수 | - | - | - |
| 최대 기간 | 1일 | 1일 | 1일 |

### Alias 구성

각 로그 유형별로 write alias를 생성하여 Fluent Bit이 alias로 데이터를 전송합니다.

```
container-logs-bigdata-prod  (alias) → container-logs-bigdata-prod-000003 (최신, write)
                                     → container-logs-bigdata-prod-000002 (읽기 전용)
                                     → container-logs-bigdata-prod-000001 (읽기 전용)
```

## 4. 날짜 기반 vs Rollover 비교

| 항목 | 날짜 기반 | Rollover 기반 |
|------|----------|--------------|
| 인덱스 크기 | 불균일 (로그량에 따라 변동) | 균일 (조건에 따라 rollover) |
| 설정 복잡도 | 낮음 | 중간 |
| 삭제 관리 | 날짜 기반 삭제 용이 | ISM 정책으로 자동화 |
| Fluent Bit 설정 | logstashFormat 사용 | index alias 사용 |
| 대시보드 검색 | 날짜 범위로 인덱스 필터링 | alias로 통합 검색 |
| **권장 환경** | **소규모, 단순 구성** | **운영환경, 대규모 로그** |

> **본 문서에서는 두 가지 방식 모두의 설정을 제공합니다.**
> - 날짜 기반: 간단한 구성, 빠른 적용
> - Rollover 기반: 운영환경 권장, ISM과 연동

## 5. 인덱스별 샤드 및 레플리카 전략

### 샤드 설계 원칙

- **샤드당 권장 크기:** 10GB ~ 50GB
- **노드당 샤드 수:** 최대 1,000개 이하
- **Primary 샤드 수:** 인덱스 생성 후 변경 불가 (재인덱싱 필요)

### 로그 유형별 샤드 설정

| 로그 유형 | 일일 예상 크기 | Primary 샤드 | Replica | 비고 |
|-----------|-------------|-------------|---------|------|
| Container Log | 5~30GB/일 | 2 | 1 | 로그량이 가장 많음 |
| K8s Event | 0.5~2GB/일 | 1 | 1 | 이벤트량 상대적으로 적음 |
| Systemd Log | 1~5GB/일 | 1 | 1 | 노드 수에 비례 |

> **단일 노드 환경에서는 replica를 0으로 설정합니다.** (현재 검증 환경)

### 환경별 설정 가이드

```
개발/검증 환경:
  primary_shards: 1
  replica_shards: 0

운영 환경 (3노드):
  primary_shards: 위 표 참조
  replica_shards: 1

운영 환경 (5노드 이상):
  primary_shards: 위 표 참조
  replica_shards: 2
```

## 6. 필드 매핑 설계

### Container Log 공통 필드

| 필드명 | 타입 | 설명 | 인덱싱 |
|--------|------|------|--------|
| `@timestamp` | date | 로그 타임스탬프 | O |
| `cluster_name` | keyword | 클러스터 식별자 | O |
| `namespace` | keyword | K8s 네임스페이스 | O |
| `pod_name` | keyword | Pod 이름 | O |
| `container_name` | keyword | 컨테이너 이름 | O |
| `node_name` | keyword | 노드 이름 | O |
| `level` | keyword | 로그 레벨 (INFO, ERROR 등) | O |
| `message` | text | 로그 메시지 본문 | O (full-text) |
| `source_file` | keyword | 원본 로그 파일 경로 | O |
| `stream` | keyword | stdout / stderr | O |

### K8s Event Log 공통 필드

| 필드명 | 타입 | 설명 | 인덱싱 |
|--------|------|------|--------|
| `@timestamp` | date | 이벤트 발생 시간 | O |
| `cluster_name` | keyword | 클러스터 식별자 | O |
| `namespace` | keyword | 이벤트 네임스페이스 | O |
| `kind` | keyword | 리소스 종류 (Pod, Node 등) | O |
| `name` | keyword | 리소스 이름 | O |
| `reason` | keyword | 이벤트 사유 (Scheduled, Failed 등) | O |
| `type` | keyword | Normal / Warning | O |
| `message` | text | 이벤트 메시지 | O (full-text) |
| `count` | integer | 발생 횟수 | O |
| `source_component` | keyword | 보고 컴포넌트 | O |

### Systemd Log 공통 필드

| 필드명 | 타입 | 설명 | 인덱싱 |
|--------|------|------|--------|
| `@timestamp` | date | 로그 타임스탬프 | O |
| `cluster_name` | keyword | 클러스터 식별자 | O |
| `node_name` | keyword | 노드 이름 | O |
| `systemd_unit` | keyword | systemd 유닛 (kubelet, containerd 등) | O |
| `priority` | integer | syslog 우선순위 (0-7) | O |
| `message` | text | 로그 메시지 | O (full-text) |
| `hostname` | keyword | 호스트 이름 | O |
| `pid` | integer | 프로세스 ID | X |
| `uid` | keyword | 사용자 ID | X |
