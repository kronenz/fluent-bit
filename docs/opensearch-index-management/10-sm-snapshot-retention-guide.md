# S3 스냅샷 보관기간 관리 (SM 삭제 전용 정책)

## 1. 개요

ISM과 SM은 서로 다른 대상을 관리합니다.

| 관리 대상 | 담당 기능 | API 경로 |
|-----------|----------|----------|
| **로컬 인덱스** 수명주기 (hot → delete) | **ISM** (Index State Management) | `_plugins/_ism/policies/` |
| **S3 스냅샷** 보관기간/자동 삭제 | **SM** (Snapshot Management) | `_plugins/_sm/policies/` |

### 동작 흐름

```
ISM 정책                              SM 정책
─────────                            ─────────
hot(7d) → snapshot_and_delete         (ISM과 무관하게 독립 동작)
            │
            ├─ snapshot 생성 ──→ S3에 저장됨
            │                         │
            └─ delete (로컬 삭제)      │ SM이 보관기간 관리
                                      │
                                      ├─ max_age: 365d  → 365일 지난 스냅샷 자동 삭제
                                      ├─ min_count: 7   → 최소 7개는 항상 유지
                                      └─ max_count: 400 → 최대 400개 초과 시 오래된 것부터 삭제
```

> **핵심:** ISM의 `delete` 액션은 **로컬 인덱스만 삭제**합니다. S3에 저장된 스냅샷은 그대로 남아있으며, SM 정책이 없으면 영구적으로 쌓입니다.

## 2. 아키텍처 선택

### 방법 A — ISM이 스냅샷 생성, SM은 삭제만 담당 (권장)

```
ISM:  hot → snapshot(개별 인덱스) → delete
SM:   creation 없이, deletion만 설정 (보관기간 관리)
```

- ISM이 인덱스별로 스냅샷을 생성하고 로컬 인덱스를 삭제
- SM은 repository 내 오래된 스냅샷만 정리
- `indices` 설정 불필요 (SM이 스냅샷을 만들지 않으므로)

### 방법 B — SM이 스냅샷 생성+삭제 모두 담당

```
ISM:  hot → delete (스냅샷 안 찍고 로컬만 삭제)
SM:   creation(indices: "container-logs-*") + deletion(max_age: 365d)
```

- SM이 cron 스케줄로 주기적으로 스냅샷 생성 및 삭제
- `indices`에 인덱스 패턴을 지정

## 3. SM `indices` 필드 설명

SM 정책의 `snapshot_config.indices`는 **인덱스 패턴**입니다 (스냅샷 이름 패턴이 아님).

```
indices: "container-logs-*"   ← 인덱스 패턴 (O)
indices: "snapshot-*"         ← 스냅샷 이름 패턴 (X)
```

| 항목 | ISM `snapshot` 액션 | SM `creation` |
|------|---------------------|---------------|
| 대상 | 해당 인덱스 **1개**를 스냅샷 | `indices` 패턴에 매칭되는 **여러 인덱스**를 한 스냅샷에 묶음 |
| 트리거 | 인덱스가 특정 상태에 진입할 때 | cron 스케줄에 따라 주기적으로 |
| 스냅샷 이름 | ISM 정책에서 지정 | SM 정책에서 지정 |

> **삭제 전용 SM 정책에서는 `indices` 설정이 불필요합니다.** SM의 deletion은 `indices`가 아니라 **repository 단위**로 스냅샷을 찾아 삭제합니다.

## 4. Container Log SM 삭제 전용 정책

ISM이 이미 스냅샷을 생성하는 환경에서, SM은 보관기간 관리(삭제)만 담당합니다.

### 4-1. DevTools 등록 쿼리

```
PUT _plugins/_sm/policies/container-log-snapshot-retention
{
  "description": "Container log 스냅샷 보관기간 관리 (삭제 전용)",
  "enabled": true,
  "snapshot_config": {
    "repository": "<your-s3-repository-name>",
    "ignore_unavailable": true,
    "partial": true
  },
  "deletion": {
    "schedule": {
      "cron": {
        "expression": "0 4 * * *",
        "timezone": "Asia/Seoul"
      }
    },
    "condition": {
      "max_age": "365d",
      "min_count": 7,
      "max_count": 400
    }
  }
}
```

### 4-2. 필드 설명

| 필드 | 값 | 설명 |
|------|---|------|
| `repository` | S3 repo 이름 | ISM snapshot 액션에서 사용한 것과 **동일한 repository** |
| `max_age` | `365d` | 365일 지난 스냅샷 삭제 |
| `min_count` | `7` | 아무리 오래돼도 최소 7개 유지 (안전 장치) |
| `max_count` | `400` | 400개 초과 시 오래된 것부터 삭제 |
| `cron expression` | `0 4 * * *` | 매일 새벽 4시(KST)에 삭제 점검 |

### 4-3. 삭제 조건 동작 방식

| 조건 | 설명 | 우선순위 |
|------|------|----------|
| `max_age` | 이 기간보다 오래된 스냅샷 삭제 대상 | - |
| `max_count` | 최대 스냅샷 수 초과 시 오래된 것부터 삭제 대상 | - |
| `min_count` | **max_age/max_count에 의해 삭제되더라도** 최소 N개는 유지 | 최우선 |

> **안전장치:** `min_count`가 설정되면 다른 삭제 조건에 해당하더라도 최소 N개의 스냅샷은 반드시 유지됩니다.

## 5. SM 정책 관리 명령어

### 정책 조회

```
# 정책 목록
GET _plugins/_sm/policies

# 특정 정책 상세
GET _plugins/_sm/policies/container-log-snapshot-retention

# 실행 상태 확인
GET _plugins/_sm/policies/container-log-snapshot-retention/_explain
```

### 정책 제어

```
# 일시 중지
POST _plugins/_sm/policies/container-log-snapshot-retention/_stop

# 재시작
POST _plugins/_sm/policies/container-log-snapshot-retention/_start

# 정책 삭제
DELETE _plugins/_sm/policies/container-log-snapshot-retention
```

### 정책 수정

```
PUT _plugins/_sm/policies/container-log-snapshot-retention
{
  "description": "Container log 스냅샷 보관기간 관리 (삭제 전용) - 보관기간 변경",
  "enabled": true,
  "snapshot_config": {
    "repository": "<your-s3-repository-name>",
    "ignore_unavailable": true,
    "partial": true
  },
  "deletion": {
    "schedule": {
      "cron": {
        "expression": "0 4 * * *",
        "timezone": "Asia/Seoul"
      }
    },
    "condition": {
      "max_age": "180d",
      "min_count": 7,
      "max_count": 200
    }
  }
}
```

## 6. 주의사항

1. **repository 이름 일치:** SM 정책의 `repository`는 ISM의 `snapshot` 액션에서 지정한 repository와 **반드시 동일**해야 합니다.
2. **SM 정책 미설정 시:** S3 스냅샷이 **영구적으로 쌓여** 디스크(MinIO) 또는 S3 비용이 지속 증가합니다.
3. **삭제 대상 범위:** SM deletion은 해당 repository 안의 **모든 스냅샷**을 대상으로 합니다. Container log 전용 repository를 분리하면 더 정밀한 관리가 가능합니다.
4. **S3 직접 삭제 금지:** S3에서 파일을 직접 삭제하면 리포지토리가 손상됩니다. 반드시 OpenSearch SM 정책 또는 API를 사용하세요.
