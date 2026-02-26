# ISM(Index State Management) 정책 설계

## 1. 개요

### ISM이란?

OpenSearch의 **ISM(Index State Management)** 은 인덱스 수명주기를 자동으로 관리하는 기능입니다. Elasticsearch의 ILM(Index Lifecycle Management)에 해당합니다.

### ISM으로 해결하는 문제

```
ISM 없이 운영                              ISM 적용 후
─────────────────                         ─────────────────
인덱스 무한 증가                            자동 보관/삭제
수동 인덱스 삭제                            정책 기반 자동화
디스크 공간 부족                            디스크 사용량 예측 가능
일관성 없는 관리                            표준화된 수명주기
장애 시 데이터 유실                         단계별 보호 전략
```

### ISM 정책 실행 주기

ISM 정책은 기본적으로 **5분 간격**으로 조건을 확인합니다.

```bash
# ISM 실행 주기 변경 (선택사항)
curl -X PUT "http://opensearch:9200/_cluster/settings" \
  -H 'Content-Type: application/json' \
  -d '{"persistent": {"plugins.index_state_management.job_interval": 5}}'
```

## 2. 수명주기 단계 설계

### 로그 유형별 수명주기

```
Container Log:
 ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐
 │  Hot     │───▶│  Warm    │───▶│  Cold    │───▶│ Delete  │
 │ 0~7일   │    │ 7~30일   │    │ 30~90일  │    │ 90일+   │
 │ 활성쓰기 │    │ 읽기전용  │    │ 압축보관  │    │ 자동삭제 │
 └─────────┘    └──────────┘    └──────────┘    └─────────┘

K8s Event Log:
 ┌─────────┐    ┌──────────┐    ┌─────────┐
 │  Hot     │───▶│  Warm    │───▶│ Delete  │
 │ 0~7일   │    │ 7~30일   │    │ 30일+   │
 │ 활성쓰기 │    │ 읽기전용  │    │ 자동삭제 │
 └─────────┘    └──────────┘    └─────────┘

Systemd Log:
 ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐
 │  Hot     │───▶│  Warm    │───▶│  Cold    │───▶│ Delete  │
 │ 0~7일   │    │ 7~14일   │    │ 14~60일  │    │ 60일+   │
 │ 활성쓰기 │    │ 읽기전용  │    │ 압축보관  │    │ 자동삭제 │
 └─────────┘    └──────────┘    └──────────┘    └─────────┘
```

### 보관 기간 요약

| 로그 유형 | Hot | Warm | Cold | 총 보관기간 |
|-----------|-----|------|------|-----------|
| Container Log | 7일 | 23일 | 60일 | **90일** |
| K8s Event Log | 7일 | 23일 | - | **30일** |
| Systemd Log | 7일 | 7일 | 46일 | **60일** |

> **보관기간 산정 근거:**
> - Container Log (90일): 애플리케이션 장애 분석, 감사 로그 요건
> - K8s Event (30일): 클러스터 이벤트는 단기 분석 목적
> - Systemd Log (60일): 인프라 문제 추적, 보안 감사

## 3. Container Log ISM 정책

### 정책 생성

```bash
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/container-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-container-logs.json
```

### 정책 내용

```json
{
  "policy": {
    "description": "Container log index lifecycle policy - 90일 보관",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["container-logs-*"],
        "priority": 100
      }
    ],
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
            "allocation": {
              "require": {},
              "include": {},
              "exclude": {},
              "wait_for": false
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
              "number_of_replicas": 1
            }
          },
          {
            "index_priority": {
              "priority": 50
            }
          }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": {
              "min_index_age": "30d"
            }
          }
        ]
      },
      {
        "name": "cold",
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
          },
          {
            "index_priority": {
              "priority": 0
            }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "90d"
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
                "source": "인덱스 {{ctx.index}} 이(가) 삭제됩니다. (보관기간 90일 만료)"
              }
            }
          },
          {
            "delete": {}
          }
        ],
        "transitions": []
      }
    ]
  }
}
```

### 단계별 동작 설명

| 단계 | 기간 | 동작 | 목적 |
|------|------|------|------|
| **Hot** | 0~7일 | 읽기/쓰기 가능 | 활성 로그 수집 및 실시간 검색 |
| **Warm** | 7~30일 | 읽기 전용, replica 유지 | 검색 가능하되 쓰기 차단 |
| **Cold** | 30~90일 | 읽기 전용, replica 0 | 디스크 절약, 필요시만 검색 |
| **Delete** | 90일+ | 알림 후 삭제 | 디스크 공간 회수 |

## 4. K8s Event Log ISM 정책

### 정책 생성

```bash
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/k8s-events-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-k8s-events.json
```

### 정책 내용

```json
{
  "policy": {
    "description": "Kubernetes event log lifecycle policy - 30일 보관",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["k8s-events-*"],
        "priority": 100
      }
    ],
    "states": [
      {
        "name": "hot",
        "actions": [],
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
          },
          {
            "index_priority": {
              "priority": 25
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
            "delete": {}
          }
        ],
        "transitions": []
      }
    ]
  }
}
```

### K8s Event 정책 특징

- **Cold 단계 생략:** 이벤트 로그는 30일이면 충분하므로 Cold 단계 불필요
- **Warm에서 replica 0:** 단기 보관이므로 디스크 절약 우선
- **삭제 시 알림 생략:** 빈번한 삭제이므로 알림 불필요

## 5. Systemd Log ISM 정책

### 정책 생성

```bash
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/systemd-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-systemd-logs.json
```

### 정책 내용

```json
{
  "policy": {
    "description": "Systemd log lifecycle policy - 60일 보관",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["systemd-logs-*"],
        "priority": 100
      }
    ],
    "states": [
      {
        "name": "hot",
        "actions": [],
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
              "number_of_replicas": 1
            }
          },
          {
            "index_priority": {
              "priority": 50
            }
          }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": {
              "min_index_age": "14d"
            }
          }
        ]
      },
      {
        "name": "cold",
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
          },
          {
            "index_priority": {
              "priority": 0
            }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "60d"
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
        ],
        "transitions": []
      }
    ]
  }
}
```

## 6. ISM 정책 관리

### 정책 확인

```bash
# 전체 ISM 정책 목록
curl -X GET "http://opensearch:9200/_plugins/_ism/policies?pretty"

# 특정 정책 상세
curl -X GET "http://opensearch:9200/_plugins/_ism/policies/container-logs-policy?pretty"
```

### 인덱스의 ISM 상태 확인

```bash
# 특정 인덱스의 ISM 실행 상태
curl -X POST "http://opensearch:9200/_plugins/_ism/explain/container-logs-bigdata-prod-2026.02.26?pretty"

# 와일드카드로 전체 확인
curl -X POST "http://opensearch:9200/_plugins/_ism/explain/container-logs-*?pretty"
```

### 기존 인덱스에 정책 적용

이미 생성된 인덱스에 ISM 정책을 수동으로 적용합니다.

```bash
# 기존 container-logs 인덱스에 정책 적용
curl -X POST "http://opensearch:9200/_plugins/_ism/add/container-logs-*" \
  -H 'Content-Type: application/json' \
  -d '{"policy_id": "container-logs-policy"}'

# 기존 k8s-events 인덱스에 정책 적용
curl -X POST "http://opensearch:9200/_plugins/_ism/add/k8s-events-*" \
  -H 'Content-Type: application/json' \
  -d '{"policy_id": "k8s-events-policy"}'

# 기존 systemd-logs 인덱스에 정책 적용
curl -X POST "http://opensearch:9200/_plugins/_ism/add/systemd-logs-*" \
  -H 'Content-Type: application/json' \
  -d '{"policy_id": "systemd-logs-policy"}'
```

### 정책 업데이트

정책을 업데이트하면, 이미 관리 중인 인덱스에는 자동 적용되지 않습니다. 수동으로 변경 사항을 반영해야 합니다.

```bash
# 1. 정책 업데이트
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/container-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-container-logs.json

# 2. 기존 인덱스에 업데이트된 정책 반영
curl -X POST "http://opensearch:9200/_plugins/_ism/change_policy/container-logs-*" \
  -H 'Content-Type: application/json' \
  -d '{
    "policy_id": "container-logs-policy",
    "state": "hot"
  }'
```

### 정책 제거

```bash
# 인덱스에서 ISM 정책 분리 (인덱스 삭제 아님)
curl -X POST "http://opensearch:9200/_plugins/_ism/remove/container-logs-*"
```

## 7. 디스크 용량 산정

### 로그 유형별 예상 디스크 사용량

| 항목 | Container Log | K8s Event | Systemd Log |
|------|--------------|-----------|-------------|
| 일일 원본 크기 (클러스터당) | 5~30 GB | 0.5~2 GB | 1~5 GB |
| 압축률 (best_compression) | ~40% | ~50% | ~45% |
| 일일 실제 크기 | 3~18 GB | 0.25~1 GB | 0.55~2.75 GB |
| Hot 기간 (7일) | 21~126 GB | 1.75~7 GB | 3.85~19.25 GB |
| Warm 기간 | 69~414 GB | 5.75~23 GB | 3.85~19.25 GB |
| Cold 기간 | 180~1080 GB | - | 25.3~126.5 GB |
| **총 용량 (클러스터당)** | **270~1620 GB** | **7.5~30 GB** | **33~165 GB** |

### 클러스터 수별 총 용량 예상

| 클러스터 수 | 최소 예상 | 최대 예상 | 권장 용량 |
|------------|----------|----------|----------|
| 3개 | 932 GB | 5,445 GB | 2~6 TB |
| 5개 | 1,553 GB | 9,075 GB | 4~10 TB |
| 10개 | 3,105 GB | 18,150 GB | 8~20 TB |

> **운영 팁:** 전체 디스크의 **80% 이상** 사용 시 경고 알림을 설정하세요.

## 8. 보관기간 조정 가이드

팀 또는 규제 요건에 따라 보관기간을 조정할 수 있습니다.

### 보관기간 변경 시 수정 위치

```
ISM 정책 파일에서 min_index_age 값만 변경:

container-logs-policy:
  hot → warm:  "min_index_age": "7d"    ← Hot 기간
  warm → cold: "min_index_age": "30d"   ← Warm 종료
  cold → delete: "min_index_age": "90d" ← 총 보관기간

k8s-events-policy:
  hot → warm:  "min_index_age": "7d"
  warm → delete: "min_index_age": "30d" ← 총 보관기간

systemd-logs-policy:
  hot → warm:  "min_index_age": "7d"
  warm → cold: "min_index_age": "14d"
  cold → delete: "min_index_age": "60d" ← 총 보관기간
```

### 일반적인 보관기간 기준

| 요건 | Container Log | K8s Event | Systemd Log |
|------|--------------|-----------|-------------|
| 최소 운영 | 30일 | 14일 | 30일 |
| 표준 운영 | 90일 | 30일 | 60일 |
| 감사/컴플라이언스 | 180~365일 | 90일 | 180일 |
| 보안 요건 | 365일+ | 180일 | 365일+ |
