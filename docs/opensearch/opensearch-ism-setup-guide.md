# OpenSearch ISM 설정 가이드

> JSON Template, Kustomization, Helm values.yaml, Dashboards UI/DevTools를 활용한 ISM 구성 방법

## 목차

1. [개요](#1-개요)
2. [ISM 정책 JSON 템플릿 구성](#2-ism-정책-json-템플릿-구성)
3. [인덱스 템플릿 JSON 구성](#3-인덱스-템플릿-json-구성)
4. [Helm values.yaml 설정](#4-helm-valuesyaml-설정)
5. [Kustomization.yaml 설정](#5-kustomizationyaml-설정)
6. [OpenSearch Dashboards UI에서 ISM 설정](#6-opensearch-dashboards-ui에서-ism-설정)
7. [DevTools를 활용한 ISM 설정 및 관리](#7-devtools를-활용한-ism-설정-및-관리)
8. [운영 환경별 설정 가이드](#8-운영-환경별-설정-가이드)
9. [트러블슈팅](#9-트러블슈팅)

---

## 1. 개요

### ISM(Index State Management)이란?

OpenSearch의 **ISM**은 인덱스 수명주기를 자동으로 관리하는 기능입니다. Elasticsearch의 ILM(Index Lifecycle Management)에 대응하며, 인덱스의 생성부터 삭제까지 정책 기반으로 자동화합니다.

### ISM 수명주기 흐름

```
Hot (활성 쓰기)  →  Warm (읽기 전용)  →  Cold (압축 보관)  →  Delete (자동 삭제)
    0~7일              7~30일              30~90일              90일+
```

### 설정 방법 비교

| 방법 | 장점 | 적합한 환경 |
|------|------|------------|
| **JSON 템플릿 + curl** | 버전 관리 가능, CI/CD 연동 | 운영 환경, GitOps |
| **Helm values.yaml** | 선언적 배포, 재현 가능 | Kubernetes Helm 기반 배포 |
| **Kustomization.yaml** | 환경별 오버레이, 패치 유연 | Kubernetes Kustomize 기반 배포 |
| **Dashboards UI** | 시각적 관리, 학습 용이 | 초기 설정, 검증 환경 |
| **DevTools** | 빠른 실행, 실시간 확인 | 디버깅, 임시 작업 |

### 관련 문서

본 가이드는 기존 문서의 설정 내용을 기반으로 다양한 배포 방식을 설명합니다.

- [opensearch-index-management/03-ism-policies.md](../opensearch-index-management/03-ism-policies.md) — ISM 정책 상세 설계
- [opensearch-index-management/02-index-templates.md](../opensearch-index-management/02-index-templates.md) — 인덱스 템플릿 매핑 상세
- [opensearch-index-management/08-dashboards-ui-guide.md](../opensearch-index-management/08-dashboards-ui-guide.md) — Dashboards UI 전체 가이드

---

## 2. ISM 정책 JSON 템플릿 구성

ISM 정책은 인덱스의 수명주기 단계(state)와 각 단계에서 수행할 액션(action), 다음 단계로 전환하는 조건(transition)으로 구성됩니다.

### 2-1. ISM 정책 JSON 기본 구조

```json
{
  "policy": {
    "description": "정책 설명",
    "default_state": "hot",
    "ism_template": [
      {
        "index_patterns": ["인덱스패턴-*"],
        "priority": 100
      }
    ],
    "states": [
      {
        "name": "상태명",
        "actions": [],
        "transitions": [
          {
            "state_name": "다음_상태명",
            "conditions": {
              "min_index_age": "7d"
            }
          }
        ]
      }
    ]
  }
}
```

**주요 필드 설명:**

| 필드 | 설명 |
|------|------|
| `description` | 정책에 대한 설명 |
| `default_state` | 인덱스가 처음 생성될 때 배치되는 상태 |
| `ism_template.index_patterns` | 이 정책이 자동 적용될 인덱스 패턴 |
| `ism_template.priority` | 여러 정책이 매칭될 때 우선순위 (높을수록 우선) |
| `states` | 수명주기 단계 배열 |
| `actions` | 해당 단계에서 실행할 액션 목록 |
| `transitions` | 다음 단계로 전환하는 조건 |

### 2-2. Container Log ISM 정책 (90일 보관)

파일: `templates/ism-policy-container-logs.json`

```json
{
  "policy": {
    "description": "Container log lifecycle - Hot(7d) → Warm(30d) → Cold(90d) → Delete",
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
            "retry": { "count": 3, "backoff": "exponential", "delay": "1m" },
            "read_only": {}
          },
          { "replica_count": { "number_of_replicas": 1 } },
          { "index_priority": { "priority": 50 } }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": { "min_index_age": "30d" }
          }
        ]
      },
      {
        "name": "cold",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "1m" },
            "read_only": {}
          },
          { "replica_count": { "number_of_replicas": 0 } },
          { "index_priority": { "priority": 0 } }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": { "min_index_age": "90d" }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          { "delete": {} }
        ],
        "transitions": []
      }
    ]
  }
}
```

### 2-3. K8s Event Log ISM 정책 (30일 보관)

파일: `templates/ism-policy-k8s-events.json`

```json
{
  "policy": {
    "description": "K8s event log lifecycle - Hot(7d) → Warm(30d) → Delete",
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
            "conditions": { "min_index_age": "7d" }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "1m" },
            "read_only": {}
          },
          { "replica_count": { "number_of_replicas": 0 } },
          { "index_priority": { "priority": 25 } }
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
        "actions": [
          { "delete": {} }
        ],
        "transitions": []
      }
    ]
  }
}
```

### 2-4. Systemd Log ISM 정책 (60일 보관)

파일: `templates/ism-policy-systemd-logs.json`

```json
{
  "policy": {
    "description": "Systemd log lifecycle - Hot(7d) → Warm(14d) → Cold(60d) → Delete",
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
            "conditions": { "min_index_age": "7d" }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "1m" },
            "read_only": {}
          },
          { "replica_count": { "number_of_replicas": 1 } },
          { "index_priority": { "priority": 50 } }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": { "min_index_age": "14d" }
          }
        ]
      },
      {
        "name": "cold",
        "actions": [
          {
            "retry": { "count": 3, "backoff": "exponential", "delay": "1m" },
            "read_only": {}
          },
          { "replica_count": { "number_of_replicas": 0 } },
          { "index_priority": { "priority": 0 } }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": { "min_index_age": "60d" }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          { "delete": {} }
        ],
        "transitions": []
      }
    ]
  }
}
```

### 2-5. ISM 정책에서 사용 가능한 주요 액션

| 액션 | 설명 | 예시 |
|------|------|------|
| `read_only` | 인덱스를 읽기 전용으로 설정 | `{"read_only": {}}` |
| `replica_count` | 레플리카 수 변경 | `{"replica_count": {"number_of_replicas": 0}}` |
| `index_priority` | 인덱스 복구 우선순위 | `{"index_priority": {"priority": 50}}` |
| `force_merge` | 세그먼트 병합 (검색 성능 향상) | `{"force_merge": {"max_num_segments": 1}}` |
| `snapshot` | 스냅샷 생성 (S3 백업) | `{"snapshot": {"repository": "repo", "snapshot": "name"}}` |
| `delete` | 인덱스 삭제 | `{"delete": {}}` |
| `rollover` | 인덱스 롤오버 | `{"rollover": {"min_doc_count": 10000000}}` |
| `notification` | 알림 발송 | `{"notification": {"destination": {...}}}` |

### 2-6. ISM 정책에서 사용 가능한 전환 조건

| 조건 | 설명 | 예시 |
|------|------|------|
| `min_index_age` | 인덱스 생성 후 경과 시간 | `"min_index_age": "7d"` |
| `min_doc_count` | 최소 문서 수 | `"min_doc_count": 10000000` |
| `min_size` | 최소 인덱스 크기 | `"min_size": "50gb"` |
| `cron` | 크론 스케줄 | `"cron": {"expression": "0 0 * * *"}` |

### 2-7. JSON 파일을 활용한 ISM 정책 적용 (curl)

```bash
# 1. ISM 정책 생성
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/container-logs-policy" \
  -H 'Content-Type: application/json' \
  -d @templates/ism-policy-container-logs.json

# 2. 정책 확인
curl -X GET "http://opensearch:9200/_plugins/_ism/policies/container-logs-policy?pretty"

# 3. 기존 인덱스에 정책 수동 적용
curl -X POST "http://opensearch:9200/_plugins/_ism/add/container-logs-*" \
  -H 'Content-Type: application/json' \
  -d '{"policy_id": "container-logs-policy"}'

# 4. 정책 업데이트 후 기존 인덱스에 반영
curl -X POST "http://opensearch:9200/_plugins/_ism/change_policy/container-logs-*" \
  -H 'Content-Type: application/json' \
  -d '{"policy_id": "container-logs-policy", "state": "hot"}'
```

---

## 3. 인덱스 템플릿 JSON 구성

인덱스 템플릿은 새 인덱스가 생성될 때 자동으로 매핑, 설정, ISM 정책을 적용합니다.

### 3-1. 인덱스 템플릿 기본 구조

```json
{
  "index_patterns": ["패턴-*"],
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
            "policy_id": "정책-이름"
          }
        }
      }
    },
    "mappings": {
      "properties": {
        "필드명": { "type": "타입" }
      }
    }
  }
}
```

### 3-2. Container Log 인덱스 템플릿

파일: `templates/index-template-container-logs.json`

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
        "@timestamp": { "type": "date" },
        "cluster_name": { "type": "keyword" },
        "namespace": { "type": "keyword" },
        "pod_name": { "type": "keyword" },
        "container_name": { "type": "keyword" },
        "node_name": { "type": "keyword" },
        "level": { "type": "keyword" },
        "message": {
          "type": "text",
          "fields": {
            "keyword": { "type": "keyword", "ignore_above": 256 }
          }
        },
        "source_file": { "type": "keyword" },
        "stream": { "type": "keyword" }
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

### 3-3. 인덱스 템플릿 적용 (curl)

```bash
# 인덱스 템플릿 생성
curl -X PUT "http://opensearch:9200/_index_template/container-logs-template" \
  -H 'Content-Type: application/json' \
  -d @templates/index-template-container-logs.json

# 생성 확인
curl -X GET "http://opensearch:9200/_index_template/container-logs-template?pretty"
```

### 3-4. 설정 항목별 권장값

| 설정 | Container Log | K8s Event | Systemd Log | 설명 |
|------|:---:|:---:|:---:|------|
| `number_of_shards` | 2 | 1 | 1 | 로그량에 비례하여 설정 |
| `number_of_replicas` | 1 | 1 | 1 | 단일 노드 환경은 0으로 설정 |
| `refresh_interval` | 10s | 30s | 15s | 쓰기 부하에 따라 조절 |
| `codec` | best_compression | best_compression | best_compression | 디스크 절약 |
| `policy_id` | container-logs-policy | k8s-events-policy | systemd-logs-policy | ISM 정책 자동 연결 |

---

## 4. Helm values.yaml 설정

Helm Chart를 사용하여 OpenSearch와 ISM 정책을 선언적으로 배포하는 방법입니다.

### 4-1. OpenSearch Helm values.yaml

파일: `infra/opensearch/values.yaml`

```yaml
# ============================================================
# OpenSearch Helm Chart values
# Chart: opensearch/opensearch
# ============================================================

replicas: 1
singleNode: true

persistence:
  size: 10Gi

resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"

extraEnvs:
  - name: DISABLE_SECURITY_PLUGIN
    value: "true"
  - name: DISABLE_INSTALL_DEMO_CONFIG
    value: "true"

service:
  type: ClusterIP

securityConfig:
  enabled: false

# ============================================================
# ISM 관련 OpenSearch 설정
# ============================================================
config:
  opensearch.yml: |
    # ISM 정책 실행 주기 (기본값: 5분)
    plugins.index_state_management.job_interval: 5

    # ISM 히스토리 설정
    plugins.index_state_management.history.enabled: true
    plugins.index_state_management.history.max_docs: 2500000
    plugins.index_state_management.history.max_age: "24h"
    plugins.index_state_management.history.rollover_check_period: "8h"
    plugins.index_state_management.history.rollover_retention_period: "30d"

    # S3 스냅샷을 사용하는 경우 (MinIO)
    # s3.client.default.endpoint: "minio.logging.svc.cluster.local:9000"
    # s3.client.default.protocol: http
    # s3.client.default.path_style_access: true
    # s3.client.default.region: us-east-1
```

### 4-2. OpenSearch Dashboards Helm values.yaml

파일: `infra/opensearch-dashboards/values.yaml`

```yaml
# ============================================================
# OpenSearch Dashboards Helm Chart values
# Chart: opensearch/opensearch-dashboards
# ============================================================

opensearchHosts: "http://opensearch-cluster-master:9200"

service:
  type: NodePort
  nodePort: 30561

resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "250m"

extraEnvs:
  - name: DISABLE_SECURITY_DASHBOARDS_PLUGIN
    value: "true"

config:
  server.ssl.enabled: "false"
```

### 4-3. Helm 배포를 통한 ISM 초기화 Job (values.yaml)

ISM 정책과 인덱스 템플릿을 Helm 배포 시 자동으로 설정하려면 `lifecycle` 또는 `extraInitContainers`를 활용합니다.

```yaml
# infra/opensearch/values.yaml (ISM 자동 초기화 추가)

# ConfigMap으로 ISM 정책 JSON 마운트
extraVolumes:
  - name: ism-policies
    configMap:
      name: opensearch-ism-policies

extraVolumeMounts:
  - name: ism-policies
    mountPath: /usr/share/opensearch/ism-policies
    readOnly: true

# ISM 초기화를 위한 lifecycle hook
lifecycle:
  postStart:
    exec:
      command:
        - /bin/bash
        - -c
        - |
          # OpenSearch가 준비될 때까지 대기
          until curl -sf http://localhost:9200/_cluster/health; do
            sleep 5
          done

          # ISM 정책 적용
          for policy_file in /usr/share/opensearch/ism-policies/ism-*.json; do
            policy_name=$(basename "$policy_file" .json)
            curl -sf -X PUT "http://localhost:9200/_plugins/_ism/policies/${policy_name}" \
              -H 'Content-Type: application/json' \
              -d @"$policy_file" || true
          done

          # 인덱스 템플릿 적용
          for template_file in /usr/share/opensearch/ism-policies/index-template-*.json; do
            template_name=$(basename "$template_file" .json)
            curl -sf -X PUT "http://localhost:9200/_index_template/${template_name}" \
              -H 'Content-Type: application/json' \
              -d @"$template_file" || true
          done
```

### 4-4. ISM 정책 ConfigMap 생성

```yaml
# infra/opensearch/configmap-ism-policies.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-ism-policies
  namespace: logging
data:
  ism-container-logs-policy.json: |
    {
      "policy": {
        "description": "Container log lifecycle - 90일 보관",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["container-logs-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "warm", "conditions": { "min_index_age": "7d" } }
            ]
          },
          {
            "name": "warm",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 1 } },
              { "index_priority": { "priority": 50 } }
            ],
            "transitions": [
              { "state_name": "cold", "conditions": { "min_index_age": "30d" } }
            ]
          },
          {
            "name": "cold",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 0 } },
              { "index_priority": { "priority": 0 } }
            ],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "90d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
  index-template-container-logs.json: |
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
                "policy_id": "ism-container-logs-policy"
              }
            }
          }
        },
        "mappings": {
          "properties": {
            "@timestamp": { "type": "date" },
            "cluster_name": { "type": "keyword" },
            "namespace": { "type": "keyword" },
            "pod_name": { "type": "keyword" },
            "container_name": { "type": "keyword" },
            "message": { "type": "text" }
          }
        }
      }
    }
```

### 4-5. Helm 배포 명령어

```bash
# OpenSearch 배포
helm upgrade --install opensearch opensearch/opensearch \
  -n logging --create-namespace \
  -f infra/opensearch/values.yaml

# ConfigMap 생성
kubectl apply -f infra/opensearch/configmap-ism-policies.yaml

# OpenSearch Dashboards 배포
helm upgrade --install opensearch-dashboards opensearch/opensearch-dashboards \
  -n logging \
  -f infra/opensearch-dashboards/values.yaml

# Fluent Bit Operator 배포
helm upgrade --install fluent-operator fluent/fluent-operator \
  -n logging \
  -f infra/fluent-bit-operator/values.yaml
```

---

## 5. Kustomization.yaml 설정

Kustomize를 사용하여 환경별로 ISM 설정을 관리하는 방법입니다.

### 5-1. 디렉토리 구조

```
infra/opensearch-ism/
├── base/
│   ├── kustomization.yaml
│   ├── configmap-ism-policies.yaml
│   ├── configmap-index-templates.yaml
│   └── job-ism-init.yaml
├── overlays/
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   └── patches/
│   │       └── ism-retention-patch.yaml
│   ├── staging/
│   │   ├── kustomization.yaml
│   │   └── patches/
│   │       └── ism-retention-patch.yaml
│   └── production/
│       ├── kustomization.yaml
│       └── patches/
│           └── ism-retention-patch.yaml
```

### 5-2. Base kustomization.yaml

```yaml
# infra/opensearch-ism/base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: logging

resources:
  - configmap-ism-policies.yaml
  - configmap-index-templates.yaml
  - job-ism-init.yaml

commonLabels:
  app.kubernetes.io/component: opensearch-ism
  app.kubernetes.io/managed-by: kustomize
```

### 5-3. Base ISM 정책 ConfigMap

```yaml
# infra/opensearch-ism/base/configmap-ism-policies.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-ism-policies
data:
  container-logs-policy.json: |
    {
      "policy": {
        "description": "Container log lifecycle - Hot → Warm → Cold → Delete",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["container-logs-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "warm", "conditions": { "min_index_age": "7d" } }
            ]
          },
          {
            "name": "warm",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 1 } },
              { "index_priority": { "priority": 50 } }
            ],
            "transitions": [
              { "state_name": "cold", "conditions": { "min_index_age": "30d" } }
            ]
          },
          {
            "name": "cold",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 0 } },
              { "index_priority": { "priority": 0 } }
            ],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "90d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
  k8s-events-policy.json: |
    {
      "policy": {
        "description": "K8s event log lifecycle - Hot → Warm → Delete",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["k8s-events-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "warm", "conditions": { "min_index_age": "7d" } }
            ]
          },
          {
            "name": "warm",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 0 } },
              { "index_priority": { "priority": 25 } }
            ],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "30d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
  systemd-logs-policy.json: |
    {
      "policy": {
        "description": "Systemd log lifecycle - Hot → Warm → Cold → Delete",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["systemd-logs-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "warm", "conditions": { "min_index_age": "7d" } }
            ]
          },
          {
            "name": "warm",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 1 } },
              { "index_priority": { "priority": 50 } }
            ],
            "transitions": [
              { "state_name": "cold", "conditions": { "min_index_age": "14d" } }
            ]
          },
          {
            "name": "cold",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 0 } },
              { "index_priority": { "priority": 0 } }
            ],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "60d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
```

### 5-4. Base 인덱스 템플릿 ConfigMap

```yaml
# infra/opensearch-ism/base/configmap-index-templates.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-index-templates
data:
  container-logs-template.json: |
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
            "@timestamp": { "type": "date" },
            "cluster_name": { "type": "keyword" },
            "namespace": { "type": "keyword" },
            "pod_name": { "type": "keyword" },
            "container_name": { "type": "keyword" },
            "node_name": { "type": "keyword" },
            "level": { "type": "keyword" },
            "message": {
              "type": "text",
              "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } }
            }
          },
          "dynamic_templates": [
            {
              "strings_as_keywords": {
                "match_mapping_type": "string",
                "mapping": { "type": "keyword", "ignore_above": 512 }
              }
            }
          ]
        }
      }
    }
  k8s-events-template.json: |
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
        }
      }
    }
  systemd-logs-template.json: |
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
        }
      }
    }
```

### 5-5. ISM 초기화 Job

```yaml
# infra/opensearch-ism/base/job-ism-init.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: opensearch-ism-init
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-weight: "10"
    helm.sh/hook-delete-policy: before-hook-creation
spec:
  backoffLimit: 5
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: ism-init
          image: curlimages/curl:8.5.0
          command:
            - /bin/sh
            - -c
            - |
              OPENSEARCH_URL="http://opensearch-cluster-master.logging.svc.cluster.local:9200"

              echo "=== OpenSearch 준비 대기 ==="
              until curl -sf "${OPENSEARCH_URL}/_cluster/health" > /dev/null 2>&1; do
                echo "OpenSearch 대기 중..."
                sleep 10
              done
              echo "OpenSearch 준비 완료"

              echo "=== ISM 정책 적용 ==="
              for f in /config/ism-policies/*.json; do
                name=$(basename "$f" .json)
                echo "ISM 정책 적용: ${name}"
                curl -sf -X PUT "${OPENSEARCH_URL}/_plugins/_ism/policies/${name}" \
                  -H 'Content-Type: application/json' \
                  -d @"$f"
                echo ""
              done

              echo "=== 인덱스 템플릿 적용 ==="
              for f in /config/index-templates/*.json; do
                name=$(basename "$f" .json)
                echo "인덱스 템플릿 적용: ${name}"
                curl -sf -X PUT "${OPENSEARCH_URL}/_index_template/${name}" \
                  -H 'Content-Type: application/json' \
                  -d @"$f"
                echo ""
              done

              echo "=== 설정 완료 ==="
          volumeMounts:
            - name: ism-policies
              mountPath: /config/ism-policies
            - name: index-templates
              mountPath: /config/index-templates
      volumes:
        - name: ism-policies
          configMap:
            name: opensearch-ism-policies
        - name: index-templates
          configMap:
            name: opensearch-index-templates
```

### 5-6. 환경별 오버레이 (dev)

```yaml
# infra/opensearch-ism/overlays/dev/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

namePrefix: dev-

patches:
  - path: patches/ism-retention-patch.yaml
    target:
      kind: ConfigMap
      name: opensearch-ism-policies

commonAnnotations:
  environment: dev
```

```yaml
# infra/opensearch-ism/overlays/dev/patches/ism-retention-patch.yaml
# Dev 환경: 보관기간 단축 (Container: 30일, K8s Event: 7일, Systemd: 14일)
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-ism-policies
data:
  container-logs-policy.json: |
    {
      "policy": {
        "description": "Container log lifecycle - DEV (30일 보관)",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["container-logs-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "warm", "conditions": { "min_index_age": "3d" } }
            ]
          },
          {
            "name": "warm",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 0 } }
            ],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "30d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
  k8s-events-policy.json: |
    {
      "policy": {
        "description": "K8s event log lifecycle - DEV (7일 보관)",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["k8s-events-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "7d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
  systemd-logs-policy.json: |
    {
      "policy": {
        "description": "Systemd log lifecycle - DEV (14일 보관)",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["systemd-logs-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "14d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
```

### 5-7. 환경별 오버레이 (production)

```yaml
# infra/opensearch-ism/overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

namePrefix: prod-

patches:
  - path: patches/ism-retention-patch.yaml
    target:
      kind: ConfigMap
      name: opensearch-ism-policies

commonAnnotations:
  environment: production
```

```yaml
# infra/opensearch-ism/overlays/production/patches/ism-retention-patch.yaml
# Production 환경: 보관기간 확장 (Container: 180일, K8s Event: 60일, Systemd: 120일)
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-ism-policies
data:
  container-logs-policy.json: |
    {
      "policy": {
        "description": "Container log lifecycle - PRODUCTION (180일 보관)",
        "default_state": "hot",
        "ism_template": [
          { "index_patterns": ["container-logs-*"], "priority": 100 }
        ],
        "states": [
          {
            "name": "hot",
            "actions": [],
            "transitions": [
              { "state_name": "warm", "conditions": { "min_index_age": "7d" } }
            ]
          },
          {
            "name": "warm",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 1 } },
              { "force_merge": { "max_num_segments": 1 } },
              { "index_priority": { "priority": 50 } }
            ],
            "transitions": [
              { "state_name": "cold", "conditions": { "min_index_age": "30d" } }
            ]
          },
          {
            "name": "cold",
            "actions": [
              { "read_only": {} },
              { "replica_count": { "number_of_replicas": 0 } },
              { "index_priority": { "priority": 0 } }
            ],
            "transitions": [
              { "state_name": "delete", "conditions": { "min_index_age": "180d" } }
            ]
          },
          {
            "name": "delete",
            "actions": [ { "delete": {} } ],
            "transitions": []
          }
        ]
      }
    }
```

### 5-8. Kustomize 배포 명령어

```bash
# Dev 환경 배포
kubectl apply -k infra/opensearch-ism/overlays/dev/

# Staging 환경 배포
kubectl apply -k infra/opensearch-ism/overlays/staging/

# Production 환경 배포
kubectl apply -k infra/opensearch-ism/overlays/production/

# 배포 전 매니페스트 확인 (dry-run)
kubectl kustomize infra/opensearch-ism/overlays/dev/

# 적용된 리소스 확인
kubectl get configmap -n logging -l app.kubernetes.io/component=opensearch-ism
```

### 5-9. 환경별 보관기간 비교

| 환경 | Container Log | K8s Event | Systemd Log |
|------|:---:|:---:|:---:|
| **Dev** | 30일 | 7일 | 14일 |
| **Staging** | 60일 | 14일 | 30일 |
| **Production** | 180일 | 60일 | 120일 |

---

## 6. OpenSearch Dashboards UI에서 ISM 설정

Dashboards 웹 UI를 통해 시각적으로 ISM 정책을 관리하는 방법입니다.

### 6-1. Dashboards 접속

```
URL: http://<노드IP>:30561
```

### 6-2. ISM 정책 생성 (JSON Editor)

**경로:** 좌측 메뉴(☰) → **OpenSearch Plugins** → **Index Management** → **Policies** → **[Create policy]**

1. **Policy ID** 입력: `container-logs-policy`
2. **Configuration method**: **JSON editor** 선택
3. JSON 편집기에 §2-2의 ISM 정책 JSON을 붙여넣기
4. **[Create]** 클릭

### 6-3. ISM 정책 생성 (Visual Editor)

JSON 대신 드래그앤드롭 방식으로 구성하는 방법입니다.

1. **[Create policy]** → **Visual editor** 선택
2. 상태(State) 추가:

| State | Actions | Transition 조건 | 다음 State |
|-------|---------|----------------|-----------|
| hot | (없음) | min_index_age: 7d | warm |
| warm | Read only, Set replicas: 1, Set priority: 50 | min_index_age: 30d | cold |
| cold | Read only, Set replicas: 0, Set priority: 0 | min_index_age: 90d | delete |
| delete | Delete | (없음) | - |

3. **ISM templates** 섹션에서:
   - Index patterns: `container-logs-*`
   - Priority: `100`
4. **[Create]** 클릭

### 6-4. 인덱스 템플릿 생성 (UI)

**경로:** **Index Management** → **Templates** → **[Create template]**

1. **Template name**: `container-logs-template`
2. **Index patterns**: `container-logs-*`
3. **Priority**: `100`
4. **Index settings** 탭에서 JSON 입력:

```json
{
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
}
```

5. **Mappings** 탭에서 필드 매핑 입력
6. **[Create template]** 클릭

### 6-5. 기존 인덱스에 정책 적용 (UI)

1. **Index Management** → **Indices**
2. 대상 인덱스를 체크박스로 선택
3. **[Actions]** → **Apply policy**
4. 드롭다운에서 정책 선택 → **[Apply]**

### 6-6. ISM 상태 모니터링 (UI)

**경로:** **Index Management** → **Policy managed indices**

| 컬럼 | 설명 |
|------|------|
| **Index** | 인덱스 이름 |
| **Policy** | 적용된 ISM 정책 |
| **State** | 현재 단계 (hot/warm/cold/delete) |
| **Action** | 현재 실행 중인 액션 |
| **Info** | 상세 정보/오류 메시지 |

---

## 7. DevTools를 활용한 ISM 설정 및 관리

**경로:** 좌측 메뉴 → **Management** → **Dev Tools**

DevTools는 OpenSearch REST API를 직접 실행할 수 있는 콘솔입니다. ISM 정책의 생성, 조회, 수정, 삭제와 실시간 모니터링에 활용합니다.

### 7-1. ISM 정책 CRUD

```
# === 정책 생성 ===
PUT _plugins/_ism/policies/container-logs-policy
{
  "policy": {
    "description": "Container log lifecycle - 90일 보관",
    "default_state": "hot",
    "ism_template": [
      { "index_patterns": ["container-logs-*"], "priority": 100 }
    ],
    "states": [
      {
        "name": "hot",
        "actions": [],
        "transitions": [
          { "state_name": "warm", "conditions": { "min_index_age": "7d" } }
        ]
      },
      {
        "name": "warm",
        "actions": [
          { "read_only": {} },
          { "replica_count": { "number_of_replicas": 1 } },
          { "index_priority": { "priority": 50 } }
        ],
        "transitions": [
          { "state_name": "cold", "conditions": { "min_index_age": "30d" } }
        ]
      },
      {
        "name": "cold",
        "actions": [
          { "read_only": {} },
          { "replica_count": { "number_of_replicas": 0 } },
          { "index_priority": { "priority": 0 } }
        ],
        "transitions": [
          { "state_name": "delete", "conditions": { "min_index_age": "90d" } }
        ]
      },
      {
        "name": "delete",
        "actions": [ { "delete": {} } ],
        "transitions": []
      }
    ]
  }
}

# === 정책 조회 ===
GET _plugins/_ism/policies/container-logs-policy

# === 전체 정책 목록 ===
GET _plugins/_ism/policies?pretty

# === 정책 삭제 ===
DELETE _plugins/_ism/policies/container-logs-policy
```

### 7-2. 인덱스 템플릿 CRUD

```
# === 인덱스 템플릿 생성 ===
PUT _index_template/container-logs-template
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
        "@timestamp": { "type": "date" },
        "cluster_name": { "type": "keyword" },
        "namespace": { "type": "keyword" },
        "pod_name": { "type": "keyword" },
        "container_name": { "type": "keyword" },
        "message": {
          "type": "text",
          "fields": {
            "keyword": { "type": "keyword", "ignore_above": 256 }
          }
        }
      }
    }
  }
}

# === 인덱스 템플릿 조회 ===
GET _index_template/container-logs-template

# === 인덱스 템플릿 삭제 ===
DELETE _index_template/container-logs-template
```

### 7-3. ISM 정책 적용 및 관리

```
# === 기존 인덱스에 정책 수동 적용 ===
POST _plugins/_ism/add/container-logs-*
{
  "policy_id": "container-logs-policy"
}

# === 인덱스에서 정책 제거 ===
POST _plugins/_ism/remove/container-logs-*

# === 인덱스의 ISM 상태 확인 ===
POST _plugins/_ism/explain/container-logs-*

# === 특정 인덱스 ISM 상태 확인 ===
POST _plugins/_ism/explain/container-logs-bigdata-prod-2026.03.01

# === 정책 업데이트 후 기존 인덱스에 반영 ===
POST _plugins/_ism/change_policy/container-logs-*
{
  "policy_id": "container-logs-policy",
  "state": "hot"
}

# === 실패한 인덱스 재시도 ===
POST _plugins/_ism/retry/container-logs-bigdata-prod-2026.01.15
{
  "state": "warm"
}
```

### 7-4. 모니터링 쿼리 모음

```
# === 클러스터 헬스 ===
GET _cluster/health

# === 인덱스별 크기 및 문서 수 ===
GET _cat/indices/container-logs-*?v&s=index&h=index,health,docs.count,store.size

# === 디스크 사용량 ===
GET _cat/allocation?v&h=node,disk.used,disk.avail,disk.percent

# === ISM 정책 실행 주기 확인 ===
GET _cluster/settings?include_defaults=true&filter_path=**.index_state_management

# === ISM 실행 주기 변경 ===
PUT _cluster/settings
{
  "persistent": {
    "plugins.index_state_management.job_interval": 5
  }
}

# === 노드별 샤드 분배 ===
GET _cat/shards?v&h=index,shard,prirep,state,node&s=index
```

### 7-5. DevTools 활용 팁

- 쿼리 선택 후 **Ctrl+Enter** (또는 ▶ 버튼)로 실행
- 여러 쿼리를 줄바꿈으로 구분하여 작성 가능, 커서가 위치한 쿼리만 실행됨
- **Ctrl+Space**로 자동완성 지원
- 응답의 JSON을 **Copy as cURL** 버튼으로 curl 명령어로 변환 가능
- 자주 사용하는 쿼리는 **History** 탭에서 재사용 가능

---

## 8. 운영 환경별 설정 가이드

### 8-1. 단일 노드 (개발/검증 환경)

```
# 모든 인덱스의 replica를 0으로 변경 (DevTools)
PUT container-logs-*,k8s-events-*,systemd-logs-*/_settings
{
  "index.number_of_replicas": 0
}
```

Helm values.yaml:
```yaml
replicas: 1
singleNode: true

config:
  opensearch.yml: |
    plugins.index_state_management.job_interval: 5
```

### 8-2. 멀티 노드 (운영 환경)

```yaml
# infra/opensearch/values.yaml (운영 환경)
replicas: 3
singleNode: false

persistence:
  size: 100Gi

resources:
  requests:
    memory: "4Gi"
    cpu: "2"
  limits:
    memory: "8Gi"
    cpu: "4"

config:
  opensearch.yml: |
    plugins.index_state_management.job_interval: 5
    plugins.index_state_management.history.enabled: true
```

### 8-3. ISM 적용 순서 체크리스트

1. **ISM 정책 생성** — 정책이 먼저 존재해야 인덱스 템플릿에서 참조 가능
2. **인덱스 템플릿 생성** — 새 인덱스 생성 시 자동으로 정책 연결
3. **Fluent Bit 출력 설정 적용** — 로그 수집 시작, 인덱스 자동 생성
4. **기존 인덱스에 정책 수동 적용** — 이미 존재하는 인덱스에 정책 부여

```bash
# 전체 적용 스크립트
OPENSEARCH_URL="http://opensearch-cluster-master.logging.svc.cluster.local:9200"

# Step 1: ISM 정책
for policy in container-logs-policy k8s-events-policy systemd-logs-policy; do
  curl -sf -X PUT "${OPENSEARCH_URL}/_plugins/_ism/policies/${policy}" \
    -H 'Content-Type: application/json' \
    -d @"templates/ism-policy-${policy%-policy}.json"
done

# Step 2: 인덱스 템플릿
for tpl in container-logs k8s-events systemd-logs; do
  curl -sf -X PUT "${OPENSEARCH_URL}/_index_template/${tpl}-template" \
    -H 'Content-Type: application/json' \
    -d @"templates/index-template-${tpl}.json"
done

# Step 3: Fluent Bit CRD 적용
kubectl apply -f templates/fluent-bit-outputs.yaml

# Step 4: 기존 인덱스에 정책 적용
curl -sf -X POST "${OPENSEARCH_URL}/_plugins/_ism/add/container-logs-*" \
  -H 'Content-Type: application/json' -d '{"policy_id":"container-logs-policy"}'
curl -sf -X POST "${OPENSEARCH_URL}/_plugins/_ism/add/k8s-events-*" \
  -H 'Content-Type: application/json' -d '{"policy_id":"k8s-events-policy"}'
curl -sf -X POST "${OPENSEARCH_URL}/_plugins/_ism/add/systemd-logs-*" \
  -H 'Content-Type: application/json' -d '{"policy_id":"systemd-logs-policy"}'
```

---

## 9. 트러블슈팅

### 9-1. ISM 정책이 적용되지 않는 경우

**확인 방법 (DevTools):**
```
POST _plugins/_ism/explain/container-logs-*
```

**일반적인 원인:**

| 증상 | 원인 | 해결 |
|------|------|------|
| `"policies":[]` 응답 | ISM 정책 미적용 | `POST _plugins/_ism/add/인덱스명` 실행 |
| `ism_template` 미매칭 | index_patterns 불일치 | 정책의 `ism_template.index_patterns` 확인 |
| 정책 업데이트 반영 안됨 | 기존 인덱스 자동 반영 안됨 | `change_policy` API 사용 |

### 9-2. 인덱스가 Yellow 상태인 경우

**원인:** Replica 샤드를 할당할 노드가 부족 (단일 노드)

```
# DevTools에서 replica를 0으로 변경
PUT container-logs-*/_settings
{
  "index.number_of_replicas": 0
}
```

### 9-3. ISM 액션이 실패하는 경우

```
# 실패 상세 정보 확인
POST _plugins/_ism/explain/container-logs-bigdata-prod-2026.01.15

# 재시도 실행
POST _plugins/_ism/retry/container-logs-bigdata-prod-2026.01.15
{
  "state": "warm"
}
```

### 9-4. ConfigMap 업데이트 후 ISM이 반영되지 않는 경우

ConfigMap을 수정해도 기존 ISM 정책은 자동으로 업데이트되지 않습니다. ISM 초기화 Job을 재실행하세요.

```bash
# Job 재실행 (Kustomize)
kubectl delete job -n logging opensearch-ism-init
kubectl apply -k infra/opensearch-ism/overlays/production/

# 또는 수동으로 정책 업데이트 (DevTools)
# PUT _plugins/_ism/policies/container-logs-policy
# { ... 업데이트된 정책 JSON ... }
```

### 9-5. 자주 사용하는 디버깅 명령어

```
# 전체 ISM 정책 목록
GET _plugins/_ism/policies?pretty

# 특정 인덱스의 ISM 실행 이력
POST _plugins/_ism/explain/container-logs-bigdata-prod-2026.03.01

# ISM 히스토리 인덱스 확인
GET _cat/indices/.opendistro-ism-*?v

# 클러스터 설정 중 ISM 관련 설정만 조회
GET _cluster/settings?include_defaults=true&filter_path=**.index_state_management
```
