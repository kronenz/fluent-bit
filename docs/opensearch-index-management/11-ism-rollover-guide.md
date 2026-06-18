# ISM Rollover 기반 Date + Size Rolling 가이드

## 1. 개요

### 왜 Rollover가 필요한가?

기존 Fluent Bit의 `Logstash_Format`은 날짜 기반으로만 인덱스를 생성합니다 (`container-logs-bigdata-prod-2026.03.27`). 하루에 수십 GB의 로그가 유입되는 환경에서는 **단일 인덱스가 비대해져** 검색 성능 저하와 샤드 불균형이 발생합니다.

**Date Rolling + Size Rolling을 동시에 적용**하면, 시간 조건과 크기 조건 중 하나라도 충족되면 새 인덱스가 생성되어 안정적인 인덱스 크기를 유지할 수 있습니다.

### 핵심 원칙

> Fluent Bit은 **인덱스 라우팅만** 담당하고, **Date + Size 기반 Rolling은 전적으로 OpenSearch ISM 정책이 처리**합니다.

### 기존 방식 vs Rollover 방식 비교

```
기존 방식 (Logstash_Format)              Rollover 방식 (ISM)
─────────────────────────                ─────────────────────────
Fluent Bit이 날짜별 인덱스 직접 생성       Fluent Bit은 Alias로만 전송
인덱스 크기 제어 불가                      크기 + 날짜 조건으로 자동 분할
하루 50GB → 단일 거대 인덱스               하루 50GB → 여러 적정 크기 인덱스
ISM rollover와 충돌 가능                  ISM이 전체 수명주기 관리
```

## 2. 아키텍처

### 전체 데이터 흐름

```
┌─────────────┐     ┌──────────────────────────────────────────────────────────┐
│  Fluent Bit  │     │                    OpenSearch Cluster                    │
│              │     │                                                          │
│  [OUTPUT]    │     │  ┌─────────────────────────────────────────────────┐    │
│  Index:      │────▶│  │          fluent-bit-write  (Alias)              │    │
│  fluent-bit- │     │  │  ┌─── is_write_index: true ───┐                │    │
│  write       │     │  │  │                             │                │    │
│              │     │  │  ▼                             │                │    │
│              │     │  │  fluent-bit-000003  (현재 쓰기) │                │    │
│              │     │  └─────────────────────────────────────────────────┘    │
│              │     │                                                          │
│              │     │  ┌─────────────────────────────────────────────────┐    │
│              │     │  │          fluent-bit-read  (Alias)               │    │
│              │     │  │                                                  │    │
│              │     │  │  fluent-bit-000001  (Hot/Warm/Cold)             │    │
│              │     │  │  fluent-bit-000002  (Hot/Warm)                  │    │
│              │     │  │  fluent-bit-000003  (Hot - 현재 쓰기)           │    │
│              │     │  └─────────────────────────────────────────────────┘    │
│              │     │                                                          │
│              │     │  ┌─────────────────────────────────────────────────┐    │
│              │     │  │              ISM 정책 엔진                       │    │
│              │     │  │                                                  │    │
│              │     │  │  5분마다 조건 확인:                               │    │
│              │     │  │  • min_size: 30gb  → 초과 시 rollover            │    │
│              │     │  │  • min_index_age: 1d → 초과 시 rollover          │    │
│              │     │  │  (OR 조건 — 하나만 충족해도 트리거)               │    │
│              │     │  └─────────────────────────────────────────────────┘    │
└─────────────┘     └──────────────────────────────────────────────────────────┘
```

### Rollover 동작 시나리오

```
시나리오 1: 크기 먼저 도달
─────────────────────────
  00:00  fluent-bit-000001 생성 (0 GB)
  06:00  fluent-bit-000001 → 15 GB
  12:00  fluent-bit-000001 → 30 GB ← min_size 충족!
  12:05  ISM이 rollover 실행 → fluent-bit-000002 생성
         fluent-bit-write alias → 000002로 이동

시나리오 2: 시간 먼저 도달
─────────────────────────
  Day 1  fluent-bit-000001 생성 (0 GB)
  Day 1  fluent-bit-000001 → 5 GB (트래픽 적은 날)
  Day 2  min_index_age: 1d 충족! ← 30GB 미만이지만 rollover
  Day 2  ISM이 rollover 실행 → fluent-bit-000002 생성

시나리오 3: 대량 트래픽
─────────────────────────
  Day 1  fluent-bit-000001 → 30GB (rollover) → 000002
  Day 1  fluent-bit-000002 → 30GB (rollover) → 000003
  Day 1  fluent-bit-000003 → 10GB
  Day 2  min_index_age 충족 → 000004
  → 하루에 인덱스 3개 생성, 각각 적정 크기 유지
```

### 인덱스 수명주기 상태 전이

```
                    ISM 정책에 의한 자동 상태 전이
┌─────────┐
│ Rollover │  min_size: 30gb OR min_index_age: 1d
│ (Hot)    │  새 인덱스 생성, write alias 이동
└────┬─────┘
     │ 7일 경과
     ▼
┌─────────┐
│  Warm   │  replica → 0, 읽기 전용
│         │  검색은 가능, 쓰기 차단
└────┬─────┘
     │ 30일 경과
     ▼
┌─────────┐
│ Delete  │  인덱스 자동 삭제
│         │  디스크 공간 회수
└─────────┘
```

## 3. 설정 단계

### 3-1. ISM 정책 생성

OpenSearch Dev Tools 또는 curl로 실행합니다.

```json
PUT _plugins/_ism/policies/fluentbit-rollover-policy
{
  "policy": {
    "description": "Date + Size rolling for fluent-bit indices",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "retry": {
              "count": 3,
              "backoff": "exponential",
              "delay": "1m"
            },
            "rollover": {
              "min_size": "30gb",
              "min_index_age": "1d"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "warm",
            "conditions": {
              "min_index_age": "7d"
            }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "retry": {
              "count": 3,
              "backoff": "exponential",
              "delay": "1m"
            },
            "read_only": {}
          },
          {
            "replica_count": {
              "number_of_replicas": 0
            }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "30d"
            }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          {
            "retry": {
              "count": 3,
              "backoff": "exponential",
              "delay": "1m"
            },
            "notification": {
              "destination": {
                "custom_webhook": {
                  "url": "http://alertmanager:9093/api/v1/alerts"
                }
              },
              "message_template": {
                "source": "인덱스 {{ctx.index}} 이(가) 삭제됩니다. (보관기간 30일 만료)"
              }
            }
          },
          {
            "delete": {}
          }
        ],
        "transitions": []
      }
    ],
    "ism_template": [
      {
        "index_patterns": ["fluent-bit-*"],
        "priority": 100
      }
    ]
  }
}
```

#### Rollover 조건 설명

| 조건 | 값 | 동작 |
|------|------|------|
| `min_size` | `30gb` | 인덱스 크기가 30GB 초과 시 rollover |
| `min_index_age` | `1d` | 인덱스 생성 후 1일 경과 시 rollover |

> **중요:** `min_size`와 `min_index_age`는 **OR 조건**입니다. 둘 중 하나만 충족되면 rollover가 트리거됩니다.

#### 환경별 권장 rollover 조건

| 환경 | min_size | min_index_age | 근거 |
|------|----------|---------------|------|
| 소규모 (일 5GB 미만) | `50gb` | `1d` | 날짜 기반 rolling 위주 |
| 중규모 (일 5~30GB) | `30gb` | `1d` | 크기 + 날짜 균형 |
| 대규모 (일 30GB 이상) | `20gb` | `12h` | 인덱스 크기 억제 우선 |

### 3-2. Index Template 생성

```json
PUT _index_template/fluent-bit-template
{
  "index_patterns": ["fluent-bit-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "plugins.index_state_management.rollover_alias": "fluent-bit-write"
    },
    "mappings": {
      "properties": {
        "@timestamp": {
          "type": "date"
        }
      }
    }
  }
}
```

> **`rollover_alias` 설정이 핵심입니다.** 이 설정이 있어야 ISM이 해당 인덱스에서 rollover를 수행할 수 있습니다. 템플릿에 포함하면 rollover로 생성되는 모든 새 인덱스에 자동 적용됩니다.

### 3-3. 초기 인덱스 + Alias 생성

```json
PUT fluent-bit-000001
{
  "aliases": {
    "fluent-bit-write": {
      "is_write_index": true
    },
    "fluent-bit-read": {}
  }
}
```

#### Alias 역할

```
fluent-bit-write (쓰기 전용)          fluent-bit-read (읽기 전용)
─────────────────────────            ─────────────────────────
• Fluent Bit이 데이터를 보내는 대상    • 검색/조회 시 사용
• 항상 최신 인덱스 1개만 가리킴        • 모든 rollover된 인덱스 포함
• rollover 시 자동으로 이동           • 전체 기간 데이터 검색 가능

  fluent-bit-000001  ←                fluent-bit-000001  ←
  fluent-bit-000002                   fluent-bit-000002  ←
  fluent-bit-000003  ← write          fluent-bit-000003  ←
```

### 3-4. Fluent Bit 설정 변경

기존 `Logstash_Format` 날짜 기반에서 **Alias 기반으로 전환**합니다.

#### 변경 전 (기존 날짜 기반)

```ini
[OUTPUT]
    Name              opensearch
    Match             *
    Host              opensearch-cluster-master
    Port              9200
    Index             fluent-bit
    Logstash_Format   On
    Logstash_Prefix   fluent-bit
    Logstash_DateFormat %Y.%m.%d
    Suppress_Type_Name On
    HTTP_User         admin
    HTTP_Passwd       admin
    tls               On
    tls.verify        Off
```

#### 변경 후 (Rollover Alias 기반)

```ini
[OUTPUT]
    Name              opensearch
    Match             *
    Host              opensearch-cluster-master
    Port              9200
    Index             fluent-bit-write
    Suppress_Type_Name On
    HTTP_User         admin
    HTTP_Passwd       admin
    tls               On
    tls.verify        Off
```

#### CRD 방식 (Fluent Bit Operator)

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterOutput
metadata:
  name: opensearch-rollover
  labels:
    fluentbit.fluent.io/enabled: "true"
spec:
  match: "*"
  opensearch:
    host: opensearch-cluster-master.logging.svc.cluster.local
    port: 9200
    index: "fluent-bit-write"
    # logstashFormat 제거 — Alias 기반이므로 날짜별 인덱스 불필요
    replaceDots: true
    suppressTypeName: true
    traceError: true
    bufferSize: "5MB"
    httpUser:
      valueFrom:
        secretKeyRef:
          name: opensearch-credentials
          key: username
    httpPassword:
      valueFrom:
        secretKeyRef:
          name: opensearch-credentials
          key: password
    tls:
      verify: false
```

> **핵심 변경사항:**
> - `Logstash_Format` 제거 (또는 Off)
> - `Index`에 rollover alias 이름(`fluent-bit-write`) 지정
> - Fluent Bit은 항상 alias로만 데이터를 전송, 실제 인덱스 관리는 ISM이 담당

## 4. 멀티 클러스터 환경 적용

클러스터별로 별도의 rollover alias 체인을 구성합니다.

### 클러스터별 설정 매트릭스

| 항목 | Cluster A (bigdata-prod) | Cluster B (bigdata-dev) |
|------|--------------------------|-------------------------|
| ISM 정책 | `fluentbit-rollover-policy` (공유) | `fluentbit-rollover-policy` (공유) |
| Index Template 패턴 | `container-logs-bigdata-prod-*` | `container-logs-bigdata-dev-*` |
| rollover_alias | `container-logs-bigdata-prod-write` | `container-logs-bigdata-dev-write` |
| 초기 인덱스 | `container-logs-bigdata-prod-000001` | `container-logs-bigdata-dev-000001` |
| Fluent Bit Index | `container-logs-bigdata-prod-write` | `container-logs-bigdata-dev-write` |
| 검색 alias | `container-logs-bigdata-prod-read` | `container-logs-bigdata-dev-read` |

### 클러스터별 초기 인덱스 생성 예시

```json
// Cluster A: bigdata-prod
PUT container-logs-bigdata-prod-000001
{
  "aliases": {
    "container-logs-bigdata-prod-write": { "is_write_index": true },
    "container-logs-bigdata-prod-read": {}
  }
}

// Cluster B: bigdata-dev
PUT container-logs-bigdata-dev-000001
{
  "aliases": {
    "container-logs-bigdata-dev-write": { "is_write_index": true },
    "container-logs-bigdata-dev-read": {}
  }
}
```

## 5. 검증 및 모니터링

### 5-1. Rollover 상태 확인

```bash
# ISM 정책 실행 상태 확인
curl -X POST "https://opensearch:9200/_plugins/_ism/explain/fluent-bit-*?pretty" \
  -H 'Content-Type: application/json' \
  -k -u admin:admin

# 응답 예시
{
  "fluent-bit-000003": {
    "index.plugins.index_state_management.policy_id": "fluentbit-rollover-policy",
    "index.opendistro.index_state_management.policy_id": "fluentbit-rollover-policy",
    "index": "fluent-bit-000003",
    "index_uuid": "abc123...",
    "policy_id": "fluentbit-rollover-policy",
    "enabled": true,
    "state": { "name": "hot" },
    "action": { "name": "rollover" },
    "info": { "message": "Attempting to rollover index" }
  }
}
```

### 5-2. Alias 상태 확인

```bash
# write alias가 가리키는 인덱스 확인
curl -X GET "https://opensearch:9200/_alias/fluent-bit-write?pretty" \
  -k -u admin:admin

# 전체 alias 매핑 확인
curl -X GET "https://opensearch:9200/_cat/aliases/fluent-bit-*?v" \
  -k -u admin:admin

# 예상 출력
# alias                index               filter routing.index routing.search is_write_index
# fluent-bit-write     fluent-bit-000003   -      -             -              true
# fluent-bit-read      fluent-bit-000001   -      -             -              -
# fluent-bit-read      fluent-bit-000002   -      -             -              -
# fluent-bit-read      fluent-bit-000003   -      -             -              -
```

### 5-3. 인덱스 크기 모니터링

```bash
# 인덱스별 크기 확인
curl -X GET "https://opensearch:9200/_cat/indices/fluent-bit-*?v&s=index&h=index,health,status,pri,rep,docs.count,store.size" \
  -k -u admin:admin

# 예상 출력
# index               health status pri rep docs.count store.size
# fluent-bit-000001   green  open     3   0    5234120     28.5gb
# fluent-bit-000002   green  open     3   0    4891003     26.2gb
# fluent-bit-000003   green  open     3   1    1203445      6.8gb
```

### 5-4. 검색 테스트

```json
// fluent-bit-read alias로 전체 데이터 검색
GET fluent-bit-read/_search
{
  "query": {
    "bool": {
      "filter": [
        {
          "range": {
            "@timestamp": {
              "gte": "now-1h",
              "lte": "now"
            }
          }
        }
      ]
    }
  },
  "size": 10,
  "sort": [
    { "@timestamp": { "order": "desc" } }
  ]
}
```

## 6. Data Stream 방식 (대안)

OpenSearch 2.6+ 환경에서는 Data Stream을 사용할 수 있습니다. Alias를 수동으로 관리하지 않아도 되어 더 간결합니다.

### Data Stream vs Alias 비교

```
Alias 기반 Rollover                   Data Stream
─────────────────────────             ─────────────────────────
Index Template 필요                    Index Template 필요
초기 인덱스 수동 생성 필요              자동 생성 (backing index)
write/read alias 수동 관리             alias 불필요
rollover_alias 설정 필수               ISM에서 직접 rollover
OpenSearch 1.x+ 호환                  OpenSearch 2.6+ 필요
```

### Data Stream 설정 예시

```json
// 1. Index Template (data_stream 활성화)
PUT _index_template/fluent-bit-ds-template
{
  "index_patterns": ["fluent-bit-ds"],
  "data_stream": {},
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1
    },
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" }
      }
    }
  }
}

// 2. ISM 정책 (동일 rollover 조건)
PUT _plugins/_ism/policies/fluentbit-ds-rollover-policy
{
  "policy": {
    "description": "Data Stream rollover policy",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_size": "30gb",
              "min_index_age": "1d"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": { "min_index_age": "30d" }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [ { "delete": {} } ],
        "transitions": []
      }
    ],
    "ism_template": [
      {
        "index_patterns": ["fluent-bit-ds"],
        "priority": 100
      }
    ]
  }
}
```

```ini
# Fluent Bit 설정 (Data Stream용)
[OUTPUT]
    Name              opensearch
    Match             *
    Host              opensearch-cluster-master
    Port              9200
    Index             fluent-bit-ds
    Suppress_Type_Name On
    HTTP_User         admin
    HTTP_Passwd       admin
    tls               On
    tls.verify        Off
```

## 7. 기존 날짜 기반 인덱스에서 마이그레이션

기존 `Logstash_Format` 환경에서 Rollover 방식으로 전환하는 절차입니다.

### 마이그레이션 흐름

```
Phase 1: 준비                  Phase 2: 전환                Phase 3: 정리
─────────────────             ─────────────────            ─────────────────
ISM 정책 생성                  Fluent Bit 설정 변경          기존 날짜 인덱스에
Index Template 생성            → alias 기반으로 전환           ISM 정책 적용
초기 인덱스 + alias 생성       데이터 유입 확인               (자동 보관/삭제)
                              rollover 동작 확인
```

### 단계별 절차

```bash
# Phase 1: 준비 (서비스 중단 없음)
# 1-1. ISM 정책 생성
curl -X PUT "https://opensearch:9200/_plugins/_ism/policies/fluentbit-rollover-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-rollover-policy.json \
  -k -u admin:admin

# 1-2. Index Template 생성
curl -X PUT "https://opensearch:9200/_index_template/fluent-bit-rollover-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-rollover.json \
  -k -u admin:admin

# 1-3. 초기 인덱스 생성
curl -X PUT "https://opensearch:9200/fluent-bit-000001" \
  -H 'Content-Type: application/json' \
  -d '{
    "aliases": {
      "fluent-bit-write": { "is_write_index": true },
      "fluent-bit-read": {}
    }
  }' \
  -k -u admin:admin

# Phase 2: Fluent Bit 설정 전환
# ConfigMap 또는 CRD에서 Output 설정 변경 후 재시작
kubectl rollout restart daemonset/fluent-bit -n logging

# Phase 3: 기존 인덱스 정리
# 기존 날짜 인덱스를 read alias에 추가 (검색 연속성 유지)
curl -X POST "https://opensearch:9200/_aliases" \
  -H 'Content-Type: application/json' \
  -d '{
    "actions": [
      { "add": { "index": "fluent-bit-2026.03.*", "alias": "fluent-bit-read" } }
    ]
  }' \
  -k -u admin:admin
```

## 8. 트러블슈팅

### 자주 발생하는 문제

| 증상 | 원인 | 해결 방법 |
|------|------|-----------|
| Rollover가 실행되지 않음 | `rollover_alias` 설정 누락 | Index Template에 `plugins.index_state_management.rollover_alias` 확인 |
| `index_not_found_exception` | 초기 인덱스 미생성 | `fluent-bit-000001` 수동 생성 |
| `illegal_argument_exception: index not write index` | write alias가 올바른 인덱스를 가리키지 않음 | `_alias` API로 write 인덱스 확인 및 수정 |
| ISM 정책이 적용되지 않음 | `ism_template` 패턴 불일치 | 인덱스 이름이 `index_patterns`와 매칭되는지 확인 |
| Fluent Bit 400 에러 | Alias가 아닌 실제 인덱스로 전송 | Output의 `Index` 값이 alias 이름인지 확인 |

### ISM 실행 재시도

```bash
# ISM 정책 실행이 실패한 경우 수동 재시도
curl -X POST "https://opensearch:9200/_plugins/_ism/retry/fluent-bit-000001" \
  -H 'Content-Type: application/json' \
  -d '{ "state": "hot" }' \
  -k -u admin:admin
```

### Rollover 수동 실행 (테스트용)

```bash
# 조건과 무관하게 즉시 rollover 실행
curl -X POST "https://opensearch:9200/fluent-bit-write/_rollover" \
  -H 'Content-Type: application/json' \
  -k -u admin:admin

# 조건부 rollover (dry_run으로 먼저 확인)
curl -X POST "https://opensearch:9200/fluent-bit-write/_rollover?dry_run" \
  -H 'Content-Type: application/json' \
  -d '{
    "conditions": {
      "max_size": "30gb",
      "max_age": "1d"
    }
  }' \
  -k -u admin:admin
```

## 9. 관련 문서

| 문서 | 설명 |
|------|------|
| [03-ism-policies.md](./03-ism-policies.md) | ISM 정책 상세 설계 (날짜 기반) |
| [04-fluent-bit-output-config.md](./04-fluent-bit-output-config.md) | Fluent Bit 멀티 인덱스 출력 설정 |
| [02-index-templates.md](./02-index-templates.md) | 인덱스 템플릿 매핑 상세 |
| [05-operations-guide.md](./05-operations-guide.md) | 운영 가이드 (모니터링, 트러블슈팅) |
