# Elasticsearch 핵심 (Elasticsearch Essentials) - Allganize 면접 준비

---

> **TL;DR**
> 1. ES는 **Lucene** 기반 분산 검색 엔진으로, **샤드(Shard)**와 **레플리카(Replica)**로 확장/가용성을 보장한다
> 2. 노드 역할 분리(**Master, Data, Coordinating, Ingest**)가 대규모 클러스터 안정성의 핵심이다
> 3. 성능 튜닝은 **JVM Heap, 샤드 크기, Bulk API, ILM**을 중심으로 접근한다

---

## 1. Elasticsearch 아키텍처

### 핵심 구조

```
[Cluster]
  └── [Node] (ES 인스턴스)
        └── [Index] (RDBMS의 테이블에 해당)
              └── [Shard] (Lucene 인덱스, 실제 데이터 저장 단위)
                    ├── Primary Shard (원본)
                    └── Replica Shard (복제본)
```

### Shard와 Replica 개념

```
Index: "conversations" (설정: 3 Primary, 1 Replica)

Node 1          Node 2          Node 3
┌──────────┐   ┌──────────┐   ┌──────────┐
│ P0       │   │ P1       │   │ P2       │
│ R2       │   │ R0       │   │ R1       │
└──────────┘   └──────────┘   └──────────┘

P = Primary Shard (쓰기/읽기)
R = Replica Shard (읽기 + 장애 복구)
- Replica는 반드시 Primary와 다른 노드에 배치
- Node 1 장애 시: R0(Node 2)가 P0로 승격
```

### 역 인덱스 (Inverted Index)

```
도큐먼트:
  Doc1: "AI 서비스 성능 최적화"
  Doc2: "서비스 모니터링 자동화"
  Doc3: "AI 모델 성능 분석"

역 인덱스:
  "AI"     -> [Doc1, Doc3]
  "서비스"  -> [Doc1, Doc2]
  "성능"   -> [Doc1, Doc3]
  "최적화"  -> [Doc1]
  "모니터링" -> [Doc2]
  "자동화"  -> [Doc2]
  "모델"   -> [Doc3]
  "분석"   -> [Doc3]

검색: "AI 성능" -> Doc1(2 hit), Doc3(2 hit) -> 관련도 순 반환
```

---

## 2. 클러스터 구성: 노드 역할 분리

### 노드 역할 (Node Roles)

| 역할 | 설정 | 주요 기능 | 리소스 특성 |
|------|------|----------|------------|
| **Master** | `node.roles: [master]` | 클러스터 상태 관리, 인덱스 생성/삭제 | 저사양 OK (CPU/RAM 적음) |
| **Data** | `node.roles: [data]` | 데이터 저장, 검색/집계 수행 | 고사양 (CPU, RAM, SSD) |
| **Coordinating** | `node.roles: []` | 검색 요청 라우팅, 결과 병합 | 중간 (CPU, RAM) |
| **Ingest** | `node.roles: [ingest]` | 인덱싱 전 데이터 전처리 | 중간 (CPU) |
| **ML** | `node.roles: [ml]` | 머신러닝 작업 수행 | GPU/CPU |

### 프로덕션 클러스터 구성 예시

```
[Load Balancer]
       |
[Coordinating x2] ← 검색 요청 분산
       |
  ┌────┼────┐
  |    |    |
[Data Hot x3]  ← 최근 데이터 (NVMe SSD)
  |    |    |
[Data Warm x2] ← 7~30일 데이터 (SSD)
  |    |    |
[Data Cold x2] ← 30일+ 데이터 (HDD)
       |
[Master x3]     ← 항상 홀수 (Split-Brain 방지)
[Ingest x2]     ← 파이프라인 처리
```

### 노드 설정 예시

```yaml
# elasticsearch.yml - Master Node
cluster.name: allganize-es
node.name: master-01
node.roles: [master]
network.host: 0.0.0.0
discovery.seed_hosts: ["master-01", "master-02", "master-03"]
cluster.initial_master_nodes: ["master-01", "master-02", "master-03"]

# Master는 전용 (데이터 처리 안 함)
# 최소 3개 (Split-Brain 방지: quorum = 3/2+1 = 2)
```

```yaml
# elasticsearch.yml - Data Hot Node
node.name: data-hot-01
node.roles: [data_hot, data_content]
node.attr.data: hot
path.data: /mnt/nvme/elasticsearch   # NVMe SSD
```

---

## 3. 인덱스 관리

### ILM (Index Lifecycle Management)

```
Hot Phase     →    Warm Phase    →    Cold Phase    →    Delete
(0~7일)            (7~30일)           (30~90일)          (90일+)
NVMe SSD          SSD               HDD               삭제
Replica: 1        Replica: 0        Searchable         자동
                  Force Merge       Snapshot

# 데이터가 자동으로 Hot -> Warm -> Cold -> Delete 이동
```

```json
// ILM Policy 생성
PUT _ilm/policy/ai-logs-policy
{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_size": "50gb",
            "max_age": "7d",
            "max_docs": 100000000
          },
          "set_priority": {
            "priority": 100
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "allocate": {
            "require": { "data": "warm" }
          },
          "forcemerge": {
            "max_num_segments": 1
          },
          "shrink": {
            "number_of_shards": 1
          },
          "set_priority": {
            "priority": 50
          }
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "allocate": {
            "require": { "data": "cold" }
          },
          "set_priority": {
            "priority": 0
          }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

### 매핑 (Mapping) 설계

```json
// AI 대화 이력 인덱스 매핑
PUT conversations
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "index.lifecycle.name": "ai-logs-policy"
  },
  "mappings": {
    "properties": {
      "tenant_id": {
        "type": "keyword"           // 정확한 매칭, 집계용
      },
      "user_id": {
        "type": "keyword"
      },
      "query": {
        "type": "text",             // 전문 검색용
        "analyzer": "korean",       // 한국어 분석기
        "fields": {
          "keyword": {
            "type": "keyword"       // 정렬/집계용 서브 필드
          }
        }
      },
      "response": {
        "type": "text",
        "analyzer": "korean"
      },
      "model_name": {
        "type": "keyword"
      },
      "latency_ms": {
        "type": "integer"
      },
      "token_count": {
        "type": "integer"
      },
      "timestamp": {
        "type": "date",
        "format": "strict_date_optional_time||epoch_millis"
      },
      "embedding_vector": {
        "type": "dense_vector",      // 벡터 검색용 (8.x+)
        "dims": 768,
        "index": true,
        "similarity": "cosine"
      }
    }
  }
}
```

### 분석기 (Analyzer) 구조

```
[Character Filters] → [Tokenizer] → [Token Filters]
   HTML 제거 등        단어 분리       소문자화, 불용어 등

예시: "Elasticsearch는 검색 엔진입니다"
  → Tokenizer (nori): ["Elasticsearch", "검색", "엔진"]
  → Lowercase Filter: ["elasticsearch", "검색", "엔진"]
```

```json
// 한국어 분석기 설정
PUT conversations
{
  "settings": {
    "analysis": {
      "analyzer": {
        "korean": {
          "type": "custom",
          "tokenizer": "nori_tokenizer",
          "filter": ["nori_readingform", "lowercase", "nori_part_of_speech"]
        }
      },
      "tokenizer": {
        "nori_tokenizer": {
          "type": "nori_tokenizer",
          "decompound_mode": "mixed"
        }
      }
    }
  }
}

// 분석기 테스트
POST conversations/_analyze
{
  "analyzer": "korean",
  "text": "Allganize의 AI 서비스 성능을 분석합니다"
}
```

---

## 4. 성능 튜닝

### JVM Heap 설정

```
핵심 규칙:
1. Heap은 물리 메모리의 50% 이하 (나머지는 Lucene 파일 캐시용)
2. 최대 31GB 이하 (Compressed OOP 유지)
3. Xms와 Xmx를 동일하게 설정 (리사이징 방지)
```

```bash
# jvm.options
-Xms16g
-Xmx16g

# 32GB RAM 서버 기준:
# Heap: 16GB (ES JVM)
# 나머지 16GB: OS 파일 캐시 (Lucene 세그먼트 캐싱)
```

```bash
# Heap 사용량 모니터링
GET _nodes/stats/jvm

# GC 상태 확인
GET _nodes/stats/jvm?filter_path=**.gc
```

### 샤드 크기 최적화

```
권장 샤드 크기: 10~50GB
  - 너무 작으면: 오버헤드 증가 (샤드당 메모리/파일 핸들 소비)
  - 너무 크면: 복구 시간 증가, rebalancing 느림

권장 샤드 수: 노드당 20~25개 이하
  - 1 shard ≈ Heap 50MB 소비
  - 16GB Heap: 최대 ~300 샤드 (이론적)
```

```json
// 인덱스별 샤드 수 계산 예시
// 일일 데이터: 10GB, 보존 기간: 90일
// 총 데이터: 900GB
// 샤드 크기 목표: 30GB -> 30 Primary Shards

// 실제 적용: ILM + Rollover로 자동 관리
PUT _index_template/conversations-template
{
  "index_patterns": ["conversations-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "index.lifecycle.name": "ai-logs-policy",
      "index.lifecycle.rollover_alias": "conversations"
    }
  }
}
```

### Bulk API 최적화

```bash
# 단건 인덱싱 (느림 - 절대 금지)
POST conversations/_doc
{ "query": "test", "timestamp": "2024-01-01" }

# Bulk API (빠름 - 반드시 사용)
POST _bulk
{"index":{"_index":"conversations"}}
{"query":"첫번째 질문","tenant_id":"allganize","timestamp":"2024-01-01T00:00:00Z"}
{"index":{"_index":"conversations"}}
{"query":"두번째 질문","tenant_id":"allganize","timestamp":"2024-01-01T00:01:00Z"}
```

```python
# Python Bulk 인덱싱 예시
from elasticsearch import Elasticsearch, helpers

es = Elasticsearch(["http://es-coordinating:9200"])

def generate_actions():
    for doc in documents:
        yield {
            "_index": "conversations",
            "_source": {
                "query": doc["query"],
                "response": doc["response"],
                "tenant_id": doc["tenant_id"],
                "timestamp": doc["timestamp"],
                "latency_ms": doc["latency_ms"]
            }
        }

# Bulk 인덱싱 (chunk_size 조절이 핵심)
success, errors = helpers.bulk(
    es,
    generate_actions(),
    chunk_size=1000,          # 1000건씩 배치
    request_timeout=60,
    raise_on_error=False
)
print(f"Success: {success}, Errors: {len(errors)}")
```

### 검색 성능 튜닝 체크리스트

```
1. Filter vs Query 구분
   - 점수 계산 불필요 시 filter 사용 (캐시됨)
   - 전문 검색 시에만 query 사용

2. source filtering
   - 필요한 필드만 반환 (_source: ["field1", "field2"])

3. Pagination
   - from/size: 10,000건 이하
   - search_after: 10,000건 이상 (Deep Pagination)
   - scroll: 대량 내보내기

4. 캐시 활용
   - Request Cache: 동일 쿼리 캐시
   - Query Cache: filter 절 캐시
   - Fielddata Cache: 집계용 캐시
```

```json
// 최적화된 검색 쿼리 예시
GET conversations/_search
{
  "_source": ["query", "response", "timestamp"],   // 필요 필드만
  "query": {
    "bool": {
      "filter": [                                    // filter: 캐시됨
        { "term": { "tenant_id": "allganize" } },
        { "range": { "timestamp": { "gte": "2024-01-01" } } }
      ],
      "must": [                                      // must: 점수 계산
        { "match": { "query": "AI 성능 분석" } }
      ]
    }
  },
  "sort": [
    { "timestamp": "desc" },
    { "_score": "desc" }
  ],
  "size": 20
}
```

---

## 5. K8s에서 ES 운영 (ECK Operator)

### ECK (Elastic Cloud on Kubernetes) 설치

```bash
# CRD 및 Operator 설치
kubectl create -f https://download.elastic.co/downloads/eck/2.12.1/crds.yaml
kubectl apply -f https://download.elastic.co/downloads/eck/2.12.1/operator.yaml

# Operator 상태 확인
kubectl -n elastic-system logs -f statefulset.apps/elastic-operator
```

### 프로덕션 클러스터 배포

```yaml
# elasticsearch-cluster.yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: allganize-es
  namespace: elastic
spec:
  version: 8.13.0
  nodeSets:
    # Master Nodes
    - name: master
      count: 3
      config:
        node.roles: ["master"]
        cluster.routing.allocation.awareness.attributes: zone
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              resources:
                requests:
                  cpu: "1"
                  memory: "4Gi"
                limits:
                  cpu: "2"
                  memory: "4Gi"
              env:
                - name: ES_JAVA_OPTS
                  value: "-Xms2g -Xmx2g"
          affinity:
            podAntiAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
                - labelSelector:
                    matchLabels:
                      elasticsearch.k8s.elastic.co/statefulset-name: allganize-es-es-master
                  topologyKey: kubernetes.io/hostname
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            accessModes: ["ReadWriteOnce"]
            storageClassName: fast-ssd
            resources:
              requests:
                storage: 10Gi

    # Data Hot Nodes
    - name: data-hot
      count: 3
      config:
        node.roles: ["data_hot", "data_content", "ingest"]
        node.attr.data: hot
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              resources:
                requests:
                  cpu: "4"
                  memory: "32Gi"
                limits:
                  cpu: "8"
                  memory: "32Gi"
              env:
                - name: ES_JAVA_OPTS
                  value: "-Xms16g -Xmx16g"
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            accessModes: ["ReadWriteOnce"]
            storageClassName: nvme-ssd
            resources:
              requests:
                storage: 500Gi

    # Data Warm Nodes
    - name: data-warm
      count: 2
      config:
        node.roles: ["data_warm"]
        node.attr.data: warm
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              resources:
                requests:
                  cpu: "2"
                  memory: "16Gi"
                limits:
                  cpu: "4"
                  memory: "16Gi"
              env:
                - name: ES_JAVA_OPTS
                  value: "-Xms8g -Xmx8g"
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            accessModes: ["ReadWriteOnce"]
            storageClassName: standard-ssd
            resources:
              requests:
                storage: 1Ti

    # Coordinating Nodes
    - name: coordinating
      count: 2
      config:
        node.roles: []
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              resources:
                requests:
                  cpu: "2"
                  memory: "8Gi"
                limits:
                  cpu: "4"
                  memory: "8Gi"
              env:
                - name: ES_JAVA_OPTS
                  value: "-Xms4g -Xmx4g"
  http:
    tls:
      selfSignedCertificate:
        disabled: false
```

### 클러스터 상태 모니터링

```bash
# 클러스터 Health 확인
GET _cluster/health
# green: 모든 샤드 정상
# yellow: 레플리카 미할당 (단일 노드에서 정상)
# red: Primary 샤드 미할당 (데이터 유실 위험)

# 노드 상태
GET _cat/nodes?v&h=name,role,heap.percent,disk.used_percent,cpu

# 샤드 할당 상태
GET _cat/shards?v&h=index,shard,prirep,state,docs,store,node

# 미할당 샤드 원인 분석
GET _cluster/allocation/explain
```

```yaml
# Prometheus + Elasticsearch Exporter
# helm install es-exporter prometheus-community/prometheus-elasticsearch-exporter \
#   --set es.uri=https://allganize-es-es-http:9200

# 주요 알림 규칙
# - cluster_health_status != "green"
# - jvm_memory_used_bytes / jvm_memory_max_bytes > 0.85
# - es_unassigned_shards > 0
# - es_pending_tasks > 10
```

---

## 면접 Q&A

### Q1. "ES의 샤드와 레플리카 개념을 설명해주세요"

> **이렇게 대답한다:**
> "샤드(Shard)는 Lucene 인덱스 하나에 해당하는 실제 데이터 저장 단위입니다. Primary Shard는 원본이고, Replica Shard는 복제본입니다. Replica는 읽기 부하 분산과 장애 복구 두 가지 역할을 합니다. Primary와 Replica는 반드시 서로 다른 노드에 배치되어, 노드 장애 시 Replica가 Primary로 승격됩니다. 샤드 수는 인덱스 생성 시 결정되며, 샤드당 권장 크기는 10~50GB입니다."

### Q2. "노드 역할 분리가 왜 중요한가요?"

> **이렇게 대답한다:**
> "Master 노드가 데이터 처리까지 담당하면, 무거운 검색/집계 작업이 클러스터 상태 관리를 방해하여 전체 클러스터가 불안정해집니다. Master는 전용으로 분리하고, Data 노드는 데이터 특성에 따라 Hot/Warm/Cold 티어로 나누어 비용을 최적화합니다. Coordinating 노드는 검색 요청을 분산하고 결과를 병합하는 역할로, Data 노드의 부하를 줄입니다. AI 서비스에서 대량 로그와 실시간 검색이 공존할 때, 이 분리가 특히 중요합니다."

### Q3. "ILM은 무엇이고 왜 필요한가요?"

> **이렇게 대답한다:**
> "ILM(Index Lifecycle Management)은 인덱스의 생성부터 삭제까지 생명주기를 자동 관리합니다. Hot Phase에서 쓰기/검색을 처리하고, 시간이 지나면 Warm으로 이동하여 Force Merge와 shrink를 수행하고, Cold로 이동한 뒤 최종 삭제합니다. 로그/대화 이력처럼 시간 기반 데이터에서 스토리지 비용을 최대 70%까지 절약할 수 있습니다. Rollover와 결합하면 샤드 크기도 자동으로 최적 범위(10~50GB)에 맞출 수 있습니다."

### Q4. "ES 성능 튜닝의 핵심 포인트 3가지를 말해주세요"

> **이렇게 대답한다:**
> "첫째, JVM Heap을 물리 메모리 50%, 최대 31GB 이하로 설정합니다. 나머지 메모리는 Lucene이 파일 시스템 캐시로 사용하여 검색 성능이 향상됩니다. 둘째, Bulk API를 반드시 사용하고 단건 인덱싱은 금지합니다. chunk_size를 1000~5000으로 조절하여 최적 배치 크기를 찾습니다. 셋째, 검색 쿼리에서 점수 계산이 불필요한 조건은 filter 절에 배치하여 캐시를 활용합니다. 이 세 가지만 지켜도 대부분의 성능 문제를 예방할 수 있습니다."

### Q5. "ECK Operator를 사용하는 이유와 장점은?"

> **이렇게 대답한다:**
> "ECK는 Elastic 공식 K8s Operator로, CRD를 통해 ES 클러스터를 선언적으로 관리합니다. 노드 역할 분리, 버전 롤링 업그레이드, TLS 인증서 자동 발급, 볼륨 관리를 자동화합니다. Helm으로 직접 StatefulSet을 관리하는 것보다 운영 부담이 크게 줄어듭니다. 폐쇄망 환경에서는 ECK Operator 이미지를 내부 레지스트리에 미러링하고, 오프라인 설치 스크립트를 준비해야 합니다. 이런 폐쇄망 배포 경험이 Allganize의 온프레미스 고객 지원에 직접적으로 활용될 수 있습니다."

---

## 핵심 키워드 5선

`Inverted Index (역 인덱스)` `Node Role 분리 (Master/Data/Coordinating)` `ILM (Hot-Warm-Cold)` `JVM Heap 31GB Rule` `ECK Operator`
