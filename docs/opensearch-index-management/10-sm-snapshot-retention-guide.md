# S3 스냅샷 보관기간 관리 (SM 정책 가이드)

## 1. 개요

ISM과 SM은 서로 다른 대상을 관리합니다.

| 관리 대상 | 담당 기능 | API 경로 |
|-----------|----------|----------|
| **로컬 인덱스** 수명주기 (hot → delete) | **ISM** (Index State Management) | `_plugins/_ism/policies/` |
| **S3 스냅샷** 생성/보관기간/자동 삭제 | **SM** (Snapshot Management) | `_plugins/_sm/policies/` |

> **핵심:** ISM의 `delete` 액션은 **로컬 인덱스만 삭제**합니다. S3에 저장된 스냅샷은 그대로 남아있으며, SM 정책이 없으면 영구적으로 쌓입니다.

### SM 정책 제약사항

**SM 정책은 `creation` 블록이 필수입니다.** `deletion`만 설정하면 다음 오류가 발생합니다:

```
illegal_argument_exception: must provide the creation configuration
```

따라서 "삭제만 하는 SM 정책"은 만들 수 없으며, 반드시 `creation` + `deletion`을 함께 설정해야 합니다.

## 2. 아키텍처 선택

### 방법 A — SM이 스냅샷 생성+삭제 모두 담당 (권장)

```
ISM:  hot(7d) → delete (로컬 인덱스만 삭제, 스냅샷 X)
SM:   creation(매일 스냅샷) + deletion(보관기간 관리)
```

- SM이 cron 스케줄로 주기적으로 스냅샷 생성 및 삭제를 모두 관리
- ISM에서는 `snapshot` 액션을 제거하고 `delete`만 수행
- **가장 깔끔한 구조** — 스냅샷 생명주기를 SM 한 곳에서 관리

### 방법 B — ISM + SM 병행 (스냅샷 중복 생성됨)

```
ISM:  hot(7d) → snapshot(개별 인덱스) → delete
SM:   creation(주기적 전체 스냅샷) + deletion(보관기간 관리)
```

- ISM이 인덱스별 스냅샷을 생성하고, SM도 별도로 스냅샷을 생성
- **스냅샷이 중복 생성**되어 S3 용량을 더 사용함
- SM deletion은 repository 내 **모든 스냅샷**(ISM이 만든 것 포함)을 대상으로 삭제

### 방법 C — SM 미사용, CronJob으로 삭제

```
ISM:  hot(7d) → snapshot(개별 인덱스) → delete
K8s CronJob: 오래된 스냅샷을 API로 삭제
```

- SM을 사용하지 않고 Kubernetes CronJob이 직접 삭제 API 호출
- 07-snapshot-guide.md §7 참조

> **권장:** 방법 A를 사용하여 SM이 스냅샷 생명주기를 전담하고, ISM은 로컬 인덱스 관리만 담당하게 하는 것이 가장 깔끔합니다.

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

## 4. Container Log SM 정책 (creation + deletion)

### 4-1. DevTools 등록 쿼리

```
PUT _plugins/_sm/policies/container-log-snapshot-retention
{
  "description": "Container log S3 스냅샷 자동 생성 및 보관기간 관리",
  "enabled": true,
  "snapshot_config": {
    "date_format": "yyyy-MM-dd-HH:mm",
    "timezone": "Asia/Seoul",
    "indices": "container-logs-*",
    "repository": "<your-s3-repository-name>",
    "ignore_unavailable": true,
    "include_global_state": false,
    "partial": true
  },
  "creation": {
    "schedule": {
      "cron": {
        "expression": "0 2 * * *",
        "timezone": "Asia/Seoul"
      }
    }
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
| `indices` | `container-logs-*` | 스냅샷에 포함할 **인덱스 패턴** |
| `repository` | S3 repo 이름 | 스냅샷 저장 대상 repository |
| `date_format` | `yyyy-MM-dd-HH:mm` | 스냅샷 이름에 붙는 날짜 형식 |
| `creation cron` | `0 2 * * *` | 매일 새벽 2시(KST)에 스냅샷 생성 |
| `deletion cron` | `0 4 * * *` | 매일 새벽 4시(KST)에 삭제 점검 |
| `max_age` | `365d` | 365일 지난 스냅샷 삭제 |
| `min_count` | `7` | 아무리 오래돼도 최소 7개 유지 (안전 장치) |
| `max_count` | `400` | 400개 초과 시 오래된 것부터 삭제 |

### 4-3. 삭제 조건 동작 방식

| 조건 | 설명 | 우선순위 |
|------|------|----------|
| `max_age` | 이 기간보다 오래된 스냅샷 삭제 대상 | - |
| `max_count` | 최대 스냅샷 수 초과 시 오래된 것부터 삭제 대상 | - |
| `min_count` | **max_age/max_count에 의해 삭제되더라도** 최소 N개는 유지 | 최우선 |

> **안전장치:** `min_count`가 설정되면 다른 삭제 조건에 해당하더라도 최소 N개의 스냅샷은 반드시 유지됩니다.

### 4-4. 방법 A 적용 시 ISM 정책 변경

SM이 스냅샷을 담당하므로, ISM에서는 `snapshot` 액션을 제거하고 `delete`만 남깁니다.

```
// ISM 정책 (snapshot 액션 제거)
// hot 상태에서 7일 경과 후 바로 delete
{
  "policy": {
    "policy_id": "container-logs-lifecycle",
    "description": "Container log 인덱스 수명주기 (SM이 스냅샷 담당)",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_index_age": "1d"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "7d"
            }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          {
            "delete": {}
          }
        ]
      }
    ],
    "ism_template": [
      {
        "index_patterns": ["container-logs-*"],
        "priority": 100
      }
    ]
  }
}
```

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

### 정책 수정 (보관기간 변경 예시)

```
PUT _plugins/_sm/policies/container-log-snapshot-retention
{
  "description": "Container log S3 스냅샷 자동 생성 및 보관기간 관리 - 180일로 변경",
  "enabled": true,
  "snapshot_config": {
    "date_format": "yyyy-MM-dd-HH:mm",
    "timezone": "Asia/Seoul",
    "indices": "container-logs-*",
    "repository": "<your-s3-repository-name>",
    "ignore_unavailable": true,
    "include_global_state": false,
    "partial": true
  },
  "creation": {
    "schedule": {
      "cron": {
        "expression": "0 2 * * *",
        "timezone": "Asia/Seoul"
      }
    }
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

1. **`creation` 필수:** SM 정책은 `creation` 블록 없이 생성할 수 없습니다. 삭제만 원해도 반드시 `creation`을 포함해야 합니다.
2. **ISM snapshot 중복 주의:** ISM에 `snapshot` 액션이 있고 SM에도 `creation`이 있으면 스냅샷이 중복 생성됩니다. 방법 A(SM 전담)를 사용하여 ISM에서 `snapshot` 액션을 제거하는 것을 권장합니다.
3. **repository 이름 일치:** SM 정책의 `repository`는 기존에 등록된 snapshot repository와 **반드시 동일**해야 합니다.
4. **삭제 대상 범위:** SM deletion은 해당 repository 안의 **모든 스냅샷**을 대상으로 합니다. Container log 전용 repository를 분리하면 더 정밀한 관리가 가능합니다.
5. **S3 직접 삭제 금지:** S3에서 파일을 직접 삭제하면 리포지토리가 손상됩니다. 반드시 OpenSearch SM 정책 또는 API를 사용하세요.
