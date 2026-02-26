# 인덱스 템플릿 설정

## 1. 개요

인덱스 템플릿은 새 인덱스가 생성될 때 자동으로 적용되는 설정(매핑, 샤드, ISM 정책 등)을 정의합니다. Fluent Bit이 날짜별 인덱스를 자동 생성할 때 템플릿이 매칭되어 일관된 설정이 적용됩니다.

### 템플릿 적용 흐름

```
Fluent Bit → OpenSearch에 문서 전송
                ↓
           인덱스 존재 여부 확인
                ↓
           없으면 자동 생성
                ↓
           인덱스 패턴 매칭 → 템플릿 적용
                ↓
           매핑 + 설정 + ISM 정책 자동 적용
```

## 2. Container Log 인덱스 템플릿

### API 호출

```bash
curl -X PUT "http://opensearch:9200/_index_template/container-logs-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-container-logs.json
```

### 템플릿 내용

```json
{
  "index_patterns": ["container-logs-*"],
  "priority": 100,
  "template": {
    "settings": {
      "index": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "refresh_interval": "10s",
        "codec": "best_compression",
        "plugins": {
          "index_state_management": {
            "policy_id": "container-logs-policy"
          }
        }
      }
    },
    "mappings": {
      "properties": {
        "@timestamp": {
          "type": "date"
        },
        "cluster_name": {
          "type": "keyword"
        },
        "namespace": {
          "type": "keyword"
        },
        "pod_name": {
          "type": "keyword"
        },
        "container_name": {
          "type": "keyword"
        },
        "node_name": {
          "type": "keyword"
        },
        "level": {
          "type": "keyword"
        },
        "message": {
          "type": "text",
          "fields": {
            "keyword": {
              "type": "keyword",
              "ignore_above": 256
            }
          }
        },
        "source_file": {
          "type": "keyword"
        },
        "stream": {
          "type": "keyword"
        },
        "loggerName": {
          "type": "keyword"
        },
        "thread": {
          "type": "keyword"
        },
        "contextMap": {
          "type": "object",
          "properties": {
            "traceId": {
              "type": "keyword"
            },
            "spanId": {
              "type": "keyword"
            }
          }
        }
      },
      "dynamic_templates": [
        {
          "strings_as_keywords": {
            "match_mapping_type": "string",
            "mapping": {
              "type": "keyword",
              "ignore_above": 512
            }
          }
        }
      ]
    }
  }
}
```

### 주요 설정 설명

| 설정 | 값 | 설명 |
|------|-----|------|
| `index_patterns` | `container-logs-*` | 패턴 매칭 대상 |
| `priority` | 100 | 템플릿 우선순위 (높을수록 우선) |
| `number_of_shards` | 2 | 로그량이 많으므로 2개 샤드 |
| `number_of_replicas` | 1 | HA를 위한 복제본 (단일노드: 0으로 변경) |
| `refresh_interval` | 10s | 검색 반영 주기 (기본 1s → 10s로 쓰기 성능 향상) |
| `codec` | best_compression | zstd 압축으로 디스크 절약 |
| `policy_id` | container-logs-policy | ISM 정책 자동 연결 |
| `dynamic_templates` | strings_as_keywords | 미지정 문자열 필드를 keyword로 매핑 |

## 3. K8s Event Log 인덱스 템플릿

### API 호출

```bash
curl -X PUT "http://opensearch:9200/_index_template/k8s-events-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-k8s-events.json
```

### 템플릿 내용

```json
{
  "index_patterns": ["k8s-events-*"],
  "priority": 100,
  "template": {
    "settings": {
      "index": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "refresh_interval": "30s",
        "codec": "best_compression",
        "plugins": {
          "index_state_management": {
            "policy_id": "k8s-events-policy"
          }
        }
      }
    },
    "mappings": {
      "properties": {
        "@timestamp": {
          "type": "date"
        },
        "cluster_name": {
          "type": "keyword"
        },
        "namespace": {
          "type": "keyword"
        },
        "kind": {
          "type": "keyword"
        },
        "name": {
          "type": "keyword"
        },
        "reason": {
          "type": "keyword"
        },
        "type": {
          "type": "keyword"
        },
        "message": {
          "type": "text",
          "fields": {
            "keyword": {
              "type": "keyword",
              "ignore_above": 512
            }
          }
        },
        "count": {
          "type": "integer"
        },
        "source_component": {
          "type": "keyword"
        },
        "source_host": {
          "type": "keyword"
        },
        "first_timestamp": {
          "type": "date"
        },
        "last_timestamp": {
          "type": "date"
        },
        "involved_object": {
          "type": "object",
          "properties": {
            "kind": { "type": "keyword" },
            "name": { "type": "keyword" },
            "namespace": { "type": "keyword" },
            "uid": { "type": "keyword" }
          }
        }
      },
      "dynamic_templates": [
        {
          "strings_as_keywords": {
            "match_mapping_type": "string",
            "mapping": {
              "type": "keyword",
              "ignore_above": 512
            }
          }
        }
      ]
    }
  }
}
```

### 주요 설정 설명

| 설정 | 값 | 설명 |
|------|-----|------|
| `number_of_shards` | 1 | 이벤트 로그는 상대적으로 적음 |
| `refresh_interval` | 30s | 실시간 검색 빈도가 낮으므로 성능 우선 |
| `policy_id` | k8s-events-policy | K8s 이벤트 전용 ISM 정책 |

## 4. Systemd Log 인덱스 템플릿

### API 호출

```bash
curl -X PUT "http://opensearch:9200/_index_template/systemd-logs-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-systemd-logs.json
```

### 템플릿 내용

```json
{
  "index_patterns": ["systemd-logs-*"],
  "priority": 100,
  "template": {
    "settings": {
      "index": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "refresh_interval": "15s",
        "codec": "best_compression",
        "plugins": {
          "index_state_management": {
            "policy_id": "systemd-logs-policy"
          }
        }
      }
    },
    "mappings": {
      "properties": {
        "@timestamp": {
          "type": "date"
        },
        "cluster_name": {
          "type": "keyword"
        },
        "node_name": {
          "type": "keyword"
        },
        "hostname": {
          "type": "keyword"
        },
        "systemd_unit": {
          "type": "keyword"
        },
        "priority": {
          "type": "integer"
        },
        "message": {
          "type": "text",
          "fields": {
            "keyword": {
              "type": "keyword",
              "ignore_above": 512
            }
          }
        },
        "pid": {
          "type": "integer"
        },
        "uid": {
          "type": "keyword"
        },
        "exe": {
          "type": "keyword"
        },
        "cmdline": {
          "type": "text"
        },
        "boot_id": {
          "type": "keyword"
        },
        "transport": {
          "type": "keyword"
        }
      },
      "dynamic_templates": [
        {
          "strings_as_keywords": {
            "match_mapping_type": "string",
            "mapping": {
              "type": "keyword",
              "ignore_above": 512
            }
          }
        }
      ]
    }
  }
}
```

## 5. 환경별 설정 오버라이드

### 단일 노드 (개발/검증)

인덱스 템플릿의 replica를 0으로 변경해야 합니다. 그렇지 않으면 인덱스가 yellow 상태가 됩니다.

```bash
# 모든 템플릿을 단일 노드용으로 수정
for template in container-logs-template k8s-events-template systemd-logs-template; do
  curl -X PUT "http://opensearch:9200/_index_template/${template}" \
    -H 'Content-Type: application/json' \
    -d '{
      "index_patterns": ["'${template%-template}'*"],
      "priority": 100,
      "template": {
        "settings": {
          "index.number_of_replicas": 0
        }
      }
    }'
done
```

### 기존 인덱스 replica 일괄 변경

```bash
# 이미 생성된 인덱스도 replica를 0으로 변경
curl -X PUT "http://opensearch:9200/container-logs-*,k8s-events-*,systemd-logs-*/_settings" \
  -H 'Content-Type: application/json' \
  -d '{"index.number_of_replicas": 0}'
```

## 6. 템플릿 관리 명령어

### 생성된 템플릿 확인

```bash
# 전체 인덱스 템플릿 목록
curl -X GET "http://opensearch:9200/_index_template?pretty"

# 특정 템플릿 상세 조회
curl -X GET "http://opensearch:9200/_index_template/container-logs-template?pretty"
```

### 템플릿 삭제

```bash
curl -X DELETE "http://opensearch:9200/_index_template/container-logs-template"
```

### 인덱스에 적용된 매핑 확인

```bash
# 특정 인덱스의 매핑 확인
curl -X GET "http://opensearch:9200/container-logs-bigdata-prod-2026.02.26/_mapping?pretty"
```

## 7. 주의사항

1. **템플릿은 새 인덱스에만 적용됩니다.** 이미 존재하는 인덱스의 매핑은 변경되지 않습니다.
2. **매핑 충돌 주의:** 같은 필드명에 다른 타입을 지정하면 인덱스 생성이 실패합니다.
3. **priority 관리:** 여러 템플릿이 같은 패턴에 매칭될 수 있으므로, priority 값으로 우선순위를 제어합니다.
4. **ISM 정책 선행 생성:** 템플릿에서 참조하는 ISM 정책이 먼저 생성되어 있어야 합니다.
5. **dynamic_templates:** 정의되지 않은 새 필드가 들어올 때 기본 매핑 규칙을 지정합니다. `keyword` 타입으로 설정하여 불필요한 full-text 인덱싱을 방지합니다.
