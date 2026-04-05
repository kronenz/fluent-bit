# Elasticsearch on Kubernetes

> **TL;DR**: Elasticsearch는 분산 검색/분석 엔진으로, Master-Data-Ingest 등 노드 역할 분리와 Shard/Replica 구조로 확장성과 가용성을 확보한다.
> Kubernetes에서는 ECK(Elastic Cloud on Kubernetes) Operator가 클러스터 라이프사이클, 노드 스케일링, 롤링 업그레이드를 자동화한다.
> Allganize의 AI 서비스에서 RAG(Retrieval-Augmented Generation) 파이프라인의 벡터/텍스트 검색 엔진으로 Elasticsearch가 핵심 역할을 한다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 20min

---

## 핵심 개념

### Elasticsearch 클러스터 아키텍처

```
┌─────────────────────────────────────────────────────┐
│               Elasticsearch Cluster                  │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │         Master-eligible Nodes (3)            │    │
│  │  ┌────────┐  ┌────────┐  ┌────────┐        │    │
│  │  │Master  │  │Master  │  │Master  │        │    │
│  │  │(active)│  │(standby)│ │(standby)│        │    │
│  │  └────────┘  └────────┘  └────────┘        │    │
│  │  - 클러스터 메타데이터 관리                    │    │
│  │  - 인덱스 생성/삭제, 샤드 할당 결정           │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │         Data Nodes (N)                       │    │
│  │  ┌────────┐  ┌────────┐  ┌────────┐ ...    │    │
│  │  │Data-0  │  │Data-1  │  │Data-2  │        │    │
│  │  │Shard P0│  │Shard P1│  │Shard P2│        │    │
│  │  │Shard R1│  │Shard R2│  │Shard R0│        │    │
│  │  └────────┘  └────────┘  └────────┘        │    │
│  │  - 실제 데이터 저장 및 검색/집계 수행          │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  ┌──────────────────┐  ┌───────────────────┐        │
│  │ Ingest Nodes (2) │  │Coordinating Nodes │        │
│  │ - 문서 전처리     │  │ - 요청 라우팅      │        │
│  │ - Pipeline 실행   │  │ - 결과 취합/정렬   │        │
│  └──────────────────┘  └───────────────────┘        │
└─────────────────────────────────────────────────────┘
```

### 노드 역할 (Node Roles)

| 역할 | 설정 | 리소스 특성 | 권장 수 |
|---|---|---|---|
| **Master** | `node.roles: [master]` | 낮은 CPU/Memory, 안정성 중요 | 3 (홀수) |
| **Data** | `node.roles: [data]` | 높은 CPU/Memory/Disk | 워크로드에 따라 |
| **Data Hot** | `node.roles: [data_hot]` | 고성능 SSD, 최신 데이터 | N |
| **Data Warm** | `node.roles: [data_warm]` | 대용량 HDD, 오래된 데이터 | N |
| **Ingest** | `node.roles: [ingest]` | 중간 CPU, 문서 전처리 | 2+ |
| **Coordinating** | `node.roles: []` | 중간 CPU/Memory, 쿼리 라우팅 | 2+ |
| **ML** | `node.roles: [ml]` | GPU/높은 CPU, ML inference | 워크로드에 따라 |

### Index, Shard, Replica 구조

```
  Index: "conversations" (number_of_shards: 3, number_of_replicas: 1)

  Data Node 0          Data Node 1          Data Node 2
  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │ Primary S0   │    │ Primary S1   │    │ Primary S2   │
  │ Replica S1   │    │ Replica S2   │    │ Replica S0   │
  └──────────────┘    └──────────────┘    └──────────────┘

  - Primary Shard: 쓰기를 처리하는 원본 샤드
  - Replica Shard: 가용성 + 읽기 처리량 확장
  - Primary와 Replica는 반드시 다른 노드에 배치
```

**Shard 설계 원칙:**
- Shard 크기: **10-50GB** 권장 (너무 크면 복구 느림, 너무 작으면 오버헤드)
- Shard 수 = 데이터 총 용량 / 목표 shard 크기
- Shard 수는 인덱스 생성 후 변경 불가 (`_split`/`_shrink` API 제외)
- **over-sharding 주의**: shard 하나당 ~메모리 오버헤드 존재, 수천 개 shard는 Master에 부담

### ECK (Elastic Cloud on Kubernetes) Operator

```
┌───────────────────────────────────────────────────┐
│              Kubernetes Cluster                    │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │  ECK Operator (elastic-system namespace)     │ │
│  │  - CRD: Elasticsearch, Kibana, APM Server   │ │
│  │  - TLS 자동 관리 (자체 CA 발급)              │ │
│  │  - Rolling upgrade orchestration             │ │
│  └──────────────────┬──────────────────────────┘ │
│                     │ reconcile                   │
│         ┌───────────┼───────────┐                │
│         ▼           ▼           ▼                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │StatefulSet│ │StatefulSet│ │StatefulSet│        │
│  │  master   │ │   data   │ │  ingest  │        │
│  │  (3 pods) │ │ (N pods) │ │ (2 pods) │        │
│  └──────────┘ └──────────┘ └──────────┘        │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │  Services                                    │ │
│  │  - {name}-es-http (ClusterIP, 9200)         │ │
│  │  - {name}-es-transport (Headless, 9300)     │ │
│  └─────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

#### ECK CR 예시

```yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: alli-es
  namespace: elasticsearch
spec:
  version: 8.13.0
  nodeSets:
    - name: master
      count: 3
      config:
        node.roles: ["master"]
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              resources:
                requests: { cpu: "1", memory: "2Gi" }
                limits:   { cpu: "2", memory: "4Gi" }
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            storageClassName: gp3-encrypted
            resources:
              requests:
                storage: 10Gi
    - name: data-hot
      count: 5
      config:
        node.roles: ["data_hot", "data_content"]
        node.attr.data: hot
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              env:
                - name: ES_JAVA_OPTS
                  value: "-Xms4g -Xmx4g"    # Heap = 50% of memory, max 31GB
              resources:
                requests: { cpu: "4", memory: "8Gi" }
                limits:   { cpu: "8", memory: "16Gi" }
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            storageClassName: gp3-encrypted
            resources:
              requests:
                storage: 500Gi
    - name: data-warm
      count: 3
      config:
        node.roles: ["data_warm"]
        node.attr.data: warm
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              resources:
                requests: { cpu: "2", memory: "8Gi" }
                limits:   { cpu: "4", memory: "16Gi" }
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            storageClassName: st1-large      # 대용량 HDD
            resources:
              requests:
                storage: 2Ti
```

### 성능 튜닝 핵심

**JVM Heap 설정:**
```
┌────────────────────────────────────────────────┐
│  Rule of Thumb: Heap = min(50% RAM, 31GB)      │
│                                                │
│  Pod Memory: 16Gi                              │
│  → ES_JAVA_OPTS: "-Xms8g -Xmx8g"             │
│  → 나머지 8GB: OS page cache (Lucene 성능 핵심)│
│                                                │
│  31GB 한계: Compressed OOPs 비활성화 방지      │
│  → 32GB 이상 heap은 오히려 성능 저하           │
└────────────────────────────────────────────────┘
```

**인덱스 설계 최적화:**

| 항목 | 권장 설정 | 이유 |
|---|---|---|
| `refresh_interval` | `30s` (대량 색인 시 `-1`) | 기본 1초는 색인 부하 증가 |
| `number_of_replicas` | `1` (프로덕션) | 가용성과 성능의 균형 |
| `translog.durability` | `async` (성능 우선 시) | fsync 빈도 감소 |
| Mapping | Explicit mapping 사용 | Dynamic mapping은 type 불일치 위험 |
| `_source` | 필요한 필드만 저장 | 디스크 절약, 검색 속도 향상 |

**ILM (Index Lifecycle Management):**
```
  Hot (0-7일)          Warm (7-30일)        Cold (30-90일)      Delete
  ┌──────────┐        ┌──────────┐        ┌──────────┐        ┌───────┐
  │ SSD      │ ──────►│ HDD      │ ──────►│ Frozen   │ ──────►│ 삭제  │
  │ 0 replica│        │ shrink   │        │ searchable│       │       │
  │ 빈번 검색│        │ force    │        │ snapshot │        │       │
  │          │        │ merge    │        │          │        │       │
  └──────────┘        └──────────┘        └──────────┘        └───────┘
```

---

## 실전 예시

### 클러스터 상태 확인

```bash
# 클러스터 health 확인
curl -k -u elastic:$PASSWORD https://alli-es-es-http:9200/_cluster/health?pretty

# 노드 역할 및 리소스 확인
curl -k -u elastic:$PASSWORD https://alli-es-es-http:9200/_cat/nodes?v&h=name,role,heap.percent,disk.used_percent,cpu

# Shard 배치 확인
curl -k -u elastic:$PASSWORD https://alli-es-es-http:9200/_cat/shards?v&s=index

# ECK Operator 상태 확인
kubectl get elasticsearch -n elasticsearch
kubectl describe elasticsearch alli-es -n elasticsearch
```

### 인덱스 템플릿 설정

```json
PUT _index_template/conversations
{
  "index_patterns": ["conversations-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "refresh_interval": "5s",
      "index.lifecycle.name": "conversations-policy",
      "index.lifecycle.rollover_alias": "conversations"
    },
    "mappings": {
      "properties": {
        "tenant_id":    { "type": "keyword" },
        "user_id":      { "type": "keyword" },
        "message":      { "type": "text", "analyzer": "korean" },
        "embedding":    { "type": "dense_vector", "dims": 1536 },
        "timestamp":    { "type": "date" },
        "metadata":     { "type": "object", "enabled": false }
      }
    }
  }
}
```

### 느린 쿼리 진단

```bash
# Slow log 설정
PUT /conversations/_settings
{
  "index.search.slowlog.threshold.query.warn": "5s",
  "index.search.slowlog.threshold.query.info": "2s",
  "index.search.slowlog.threshold.fetch.warn": "1s"
}

# Hot threads 확인 (CPU 병목 진단)
curl -k -u elastic:$PASSWORD https://alli-es-es-http:9200/_nodes/hot_threads

# 샤드별 세그먼트 수 확인 (force merge 필요 여부)
curl -k -u elastic:$PASSWORD https://alli-es-es-http:9200/_cat/segments/conversations-*?v&h=index,shard,segment,size
```

---

## 면접 Q&A

### Q: Elasticsearch 클러스터의 노드 역할 분리가 왜 중요한가요?

**30초 답변**:
Master, Data, Ingest, Coordinating 노드를 분리하면 각 역할에 맞는 리소스를 할당할 수 있고, 한 역할의 부하가 다른 역할에 영향을 주지 않습니다. 특히 Master 노드의 안정성이 전체 클러스터의 안정성을 결정하므로 반드시 분리해야 합니다.

**2분 답변**:
노드 역할 분리는 안정성과 효율성 두 가지 측면에서 중요합니다. 안정성 측면에서, Master 노드는 클러스터 상태(인덱스 메타데이터, 샤드 할당)를 관리하는데, Data 노드와 같이 실행하면 heavy query나 GC pause가 Master 기능에 영향을 줄 수 있습니다. Master 노드가 불안정하면 split-brain이나 shard 재할당 폭풍이 발생할 수 있습니다. 효율성 측면에서, Data 노드는 CPU/Memory/Disk가 많이 필요하지만 Master는 소량으로 충분합니다. Hot-Warm-Cold 아키텍처를 적용하면 자주 접근하는 데이터는 SSD(Hot)에, 오래된 데이터는 HDD(Warm/Cold)에 배치하여 비용을 최적화할 수 있습니다. Coordinating-only 노드는 scatter-gather 쿼리의 결과 취합을 담당하므로, 대규모 aggregation 쿼리가 많은 경우 Data 노드의 부하를 줄여줍니다. ECK Operator를 사용하면 각 역할을 별도 `nodeSet`으로 정의하여 독립적으로 스케일링할 수 있습니다.

**💡 경험 연결**:
초기에 모든 노드가 Master+Data 역할을 겸하는 구성으로 운영하다가, 대량 인덱싱 작업 중 Master election이 반복되는 문제를 경험했습니다. 전용 Master 3노드를 분리한 후 클러스터 안정성이 크게 개선되었습니다.

**⚠️ 주의**:
"모든 역할을 분리해야 한다"고 단정하지 말 것. 소규모 클러스터(3-5노드)에서는 Master+Data 겸용이 합리적일 수 있다. 규모와 워크로드에 따른 판단이 중요하다.

### Q: Elasticsearch의 Shard 수를 어떻게 결정하나요?

**30초 답변**:
Shard 크기 10-50GB를 기준으로, 예상 데이터 총 용량을 나누어 Shard 수를 결정합니다. Shard가 너무 많으면 Master 오버헤드가 증가하고, 너무 적으면 단일 shard 병목이 발생합니다.

**2분 답변**:
Shard 수 결정은 여러 요소를 고려해야 합니다. 첫째, **shard 크기**: Lucene 세그먼트 특성상 10-50GB가 최적입니다. 예를 들어 100GB 인덱스라면 3-5개 primary shard가 적절합니다. 둘째, **노드 수**: shard가 노드 수보다 많아야 균등 분산이 되지만, 노드당 shard 수가 너무 많으면(600-1000개 이상) heap 압박이 발생합니다. 셋째, **검색 병렬성**: shard 수만큼 병렬 검색이 가능하므로, 검색 latency가 중요하면 shard를 늘릴 수 있습니다. 넷째, **시계열 데이터**: 날짜별 인덱스(conversations-2024.03.01)를 사용하면 일별 데이터 크기로 shard 수를 결정합니다. ILM의 rollover를 사용하면 크기 기반으로 자동 분할할 수 있습니다. over-sharding은 흔한 실수인데, 1000개 이상의 작은 shard는 cluster state가 비대해지고 Master 노드에 심각한 부담을 줍니다. `_cat/shards`로 현재 shard 크기를 모니터링하고, `_shrink` API로 과도한 shard를 병합할 수 있습니다.

**💡 경험 연결**:
로그 인덱스를 일별로 생성하면서 shard 5개씩 설정하여, 1년 후 shard가 1800개를 넘기면서 Master 노드 heap이 포화된 경험이 있습니다. ILM rollover로 전환하고 오래된 인덱스를 shrink하여 해결했습니다.

**⚠️ 주의**:
Shard 수는 인덱스 생성 후 변경이 불가하다(reindex 또는 split/shrink 필요). 초기 설계 시 충분히 검토해야 하며, 시계열 데이터는 rollover 기반이 안전하다.

### Q: Elasticsearch를 Kubernetes에서 운영할 때 주의할 점은?

**30초 답변**:
JVM Heap을 Pod 메모리의 50% 이하로 설정하고, 나머지를 OS page cache에 할당해야 합니다. PVC로 데이터를 영속화하고, Pod Anti-affinity로 shard replica가 같은 노드에 배치되지 않도록 해야 합니다.

**2분 답변**:
K8s에서 ES 운영 시 5가지 핵심 주의사항이 있습니다. 첫째, **메모리 설정**: ES_JAVA_OPTS의 heap은 Pod memory limit의 50%로 설정합니다. 나머지 50%는 Lucene이 사용하는 OS page cache에 필수적입니다. heap이 31GB를 넘으면 Compressed OOPs가 비활성화되어 오히려 성능이 저하됩니다. 둘째, **스토리지**: 반드시 PVC를 사용하고, Data 노드는 `volumeClaimTemplates`로 개별 볼륨을 할당합니다. `emptyDir`은 Pod 재시작 시 데이터 유실입니다. 셋째, **Pod Anti-affinity**: Primary shard와 Replica shard가 같은 노드에 있으면 노드 장애 시 데이터 유실이 발생합니다. `kubernetes.io/hostname` 기반 anti-affinity를 설정합니다. 넷째, **롤링 업그레이드**: ECK Operator는 `maxUnavailable` 설정에 따라 순차적으로 Pod를 재시작합니다. 업그레이드 전 `_cluster/settings`에서 `cluster.routing.allocation.enable: "primaries"`로 shard 재할당을 비활성화하면 불필요한 shard migration을 방지합니다. 다섯째, **리소스 격리**: `vm.max_map_count=262144` 커널 파라미터가 필요한데, initContainer나 DaemonSet으로 설정합니다.

**💡 경험 연결**:
K8s에서 ES 운영 시 Pod memory limit을 8Gi로 설정하고 heap도 8Gi로 설정하여 OOM Kill이 빈번하게 발생한 경험이 있습니다. heap을 4Gi로 줄이고 page cache에 여유를 준 후 검색 성능도 함께 개선되었습니다.

**⚠️ 주의**:
ECK Operator가 자동으로 TLS를 설정하므로, 애플리케이션에서 ES에 접속할 때 CA 인증서를 Secret에서 마운트하여 사용해야 한다. `curl -k`로 테스트하되 프로덕션에서는 반드시 TLS 검증을 활성화할 것.

### Q: RAG 파이프라인에서 Elasticsearch의 역할과 벡터 검색 구현 방법은?

**30초 답변**:
RAG에서 ES는 사용자 질문과 유사한 문서를 검색하는 retriever 역할을 합니다. `dense_vector` 필드와 kNN search로 벡터 유사도 검색을 수행하고, 텍스트 검색과 결합한 hybrid search로 검색 품질을 높입니다.

**2분 답변**:
Allganize의 Alli와 같은 AI 서비스에서 RAG 파이프라인은 "검색 → 컨텍스트 주입 → LLM 생성" 3단계입니다. ES는 첫 번째 검색 단계를 담당합니다. 문서를 임베딩 모델(예: OpenAI text-embedding-3-small, 1536차원)로 벡터화하여 `dense_vector` 필드에 저장합니다. 검색 시 질문을 같은 모델로 벡터화한 후 kNN(k-Nearest Neighbors) search로 유사 문서를 찾습니다. ES 8.x부터 HNSW(Hierarchical Navigable Small World) 알고리즘 기반 ANN(Approximate Nearest Neighbor) 검색을 네이티브로 지원합니다. 실무에서는 벡터 검색만으로는 키워드 매칭이 부족하므로, BM25 텍스트 검색과 벡터 검색을 결합한 **hybrid search**를 사용합니다. ES의 `sub_searches`와 RRF(Reciprocal Rank Fusion)로 두 검색 결과를 결합하면 단일 방식보다 높은 검색 품질을 얻을 수 있습니다.

**💡 경험 연결**:
기존 BM25 기반 검색 시스템에 벡터 검색을 추가할 때, 별도 벡터 DB를 도입하는 대신 ES의 dense_vector를 활용하여 인프라 복잡도를 줄인 경험이 있습니다.

**⚠️ 주의**:
벡터 검색은 Data 노드의 메모리를 많이 사용한다. 벡터 차원 수와 문서 수에 따라 메모리 요구량을 사전에 산정해야 하며, `index.codec: best_compression` 설정으로 디스크 사용을 최적화할 수 있다.

---

## Allganize 맥락

- **RAG 핵심 인프라**: Allganize의 Alli는 고객 문서를 기반으로 AI 답변을 생성하는 서비스이므로, Elasticsearch는 문서 인덱싱과 검색의 핵심 엔진이다. 벡터 검색과 텍스트 검색의 hybrid 방식이 필수적이다.
- **멀티 테넌트 인덱스 설계**: SaaS 구조에서 tenant별 인덱스를 분리할지, 단일 인덱스에 `tenant_id` 필드로 필터링할지 결정해야 한다. tenant 수가 많으면(수백 이상) index-per-tenant는 shard 폭발을 유발하므로 routing 기반 단일 인덱스가 유리하다.
- **ILM과 비용 최적화**: AI 서비스의 대화 로그, 검색 로그는 시간이 지나면 접근 빈도가 줄어든다. Hot-Warm-Cold 아키텍처와 ILM으로 스토리지 비용을 최적화해야 한다.
- **ECK on EKS/AKS**: 관리형 서비스(Amazon OpenSearch, Azure Cognitive Search)와 자체 운영(ECK) 중 선택 근거를 설명할 수 있어야 한다. ECK는 ES 원본과 100% 호환이며, OpenSearch는 fork 이후 일부 API가 다르다.

---
**핵심 키워드**: `ECK-Operator` `Node-Roles` `Shard-Design` `ILM` `Hot-Warm-Cold` `dense_vector` `kNN-search` `Hybrid-Search` `JVM-Heap` `Page-Cache`
