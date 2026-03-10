# Section 6: Log 파이프라인 구성 및 점검

## 개요

본 섹션은 Fluent Bit Operator 기반 Log 파이프라인의 CR 구성, OpenSearch 인덱스/템플릿 설정, 파이프라인 점검 절차, 장애 패턴 및 조치 방법을 다룹니다.

**인프라 환경:**

| 항목 | 사양 |
|------|------|
| CPU | 96 Core |
| Memory | 1 TB |
| Storage | NVMe 4TB (Local PV) |
| Network (Public) | bond0 – 25G + 25G LACP |
| Network (Private) | bond1 – 25G + 25G LACP |
| Log 수집 방식 | HostPath 기반 파일 로그 수집 (stdout 미사용) |
| Log 저장소 | OpenSearch |
| 수집 에이전트 | Fluent Bit Operator |

---

## 6.1 Fluent Bit Operator CR 파이프라인 구성

### 6.1.1 CR 전체 목록

Fluent Bit Operator는 다음 CRD를 사용하여 파이프라인을 선언적으로 관리합니다.

| CR명 | 종류 | 역할 | 연결 대상 |
|------|------|------|-----------|
| `fluent-bit` | FluentBit | DaemonSet 인스턴스 정의, 전역 설정 | FluentBitConfig |
| `app-log-input` | ClusterInput | HostPath 애플리케이션 로그 수집 (tail) | FluentBitConfig |
| `systemd-input` | ClusterInput | systemd 저널 로그 수집 | FluentBitConfig |
| `cri-parser-filter` | ClusterFilter | CRI 포맷 파싱 (멀티라인 JSON/Log4j2) | ClusterInput → ClusterOutput |
| `field-modify-filter` | ClusterFilter | 필드 추가 및 변환 | ClusterInput → ClusterOutput |
| `lua-metadata-filter` | ClusterFilter | Lua 스크립트 기반 메타데이터 추출 | ClusterInput → ClusterOutput |
| `opensearch-app-output` | ClusterOutput | app-logs 인덱스로 OpenSearch 전송 | ClusterFilter → OpenSearch |
| `opensearch-k8sevt-output` | ClusterOutput | k8s-events 인덱스로 OpenSearch 전송 | ClusterFilter → OpenSearch |
| `opensearch-systemd-output` | ClusterOutput | systemd-logs 인덱스로 OpenSearch 전송 | ClusterFilter → OpenSearch |
| `app-pipeline-config` | FluentBitConfig | 파이프라인 바인딩 (label selector) | FluentBit ↔ CR 전체 |

### 6.1.2 ClusterInput 구성

#### tail 입력 (애플리케이션 로그)

HostPath 마운트된 `/var/log/` 하위 애플리케이션 로그 파일을 tail 방식으로 수집합니다.
오프셋 추적을 위한 DB 파일을 사용하여 재시작 시에도 중복 수집을 방지합니다.

| 파라미터 | 값 | 설명 |
|----------|----|------|
| `path` | `/var/log/*/app*.log` | 수집 대상 파일 경로 패턴 |
| `tag` | `app.*` | 이후 Filter/Output 라우팅에 사용되는 태그 |
| `db` | `/var/log/fluent-bit/app-tail.db` | 오프셋 추적 DB 파일 경로 |
| `db.sync` | `normal` | DB 동기화 모드 |
| `mem_buf_limit` | `64MB` | 메모리 버퍼 상한 (OOM 방어 1계층) |
| `storage.type` | `filesystem` | 백프레셔 발생 시 파일시스템 버퍼 사용 |
| `skip_long_lines` | `On` | 설정 길이 초과 라인 건너뜀 |
| `refresh_interval` | `10` | 파일 목록 갱신 주기 (초) |
| `read_from_head` | `False` | 신규 파일만 처음부터 읽음 (기존 파일은 tail) |
| `multiline.parser` | `cri` | CRI 멀티라인 파서 지정 |

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterInput
metadata:
  name: app-log-input
  labels:
    fluentbit.fluent.io/enabled: "true"
    fluentbit.fluent.io/component: logging
spec:
  tail:
    tag: app.*
    path: /var/log/*/app*.log
    db: /var/log/fluent-bit/app-tail.db
    dbSync: normal
    memBufLimit: 64MB
    storageType: filesystem
    skipLongLines: true
    refreshIntervalSeconds: 10
    readFromHead: false
    multilineParser: cri
```

#### systemd 입력 (저널 로그)

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterInput
metadata:
  name: systemd-input
  labels:
    fluentbit.fluent.io/enabled: "true"
    fluentbit.fluent.io/component: logging
spec:
  systemd:
    tag: systemd.*
    path: /var/log/journal
    db: /var/log/fluent-bit/systemd.db
    dbSync: normal
    systemdFilter:
      - _SYSTEMD_UNIT=kubelet.service
      - _SYSTEMD_UNIT=docker.service
      - _SYSTEMD_UNIT=containerd.service
      - _SYSTEMD_UNIT=etcd.service
    readFromTail: true
    stripUnderscores: true
    memBufLimit: 32MB
```

| 파라미터 | 값 | 설명 |
|----------|----|------|
| `tag` | `systemd.*` | systemd 로그 라우팅 태그 |
| `path` | `/var/log/journal` | 저널 로그 경로 |
| `db` | `/var/log/fluent-bit/systemd.db` | 오프셋 추적 DB |
| `systemdFilter` | kubelet, docker, containerd, etcd | 수집 대상 유닛 필터 |
| `readFromTail` | `true` | 기존 저널 로그 제외, 신규분부터 수집 |
| `stripUnderscores` | `true` | `_SYSTEMD_UNIT` → `SYSTEMD_UNIT` 필드명 정규화 |
| `memBufLimit` | `32MB` | 메모리 버퍼 상한 |

### 6.1.3 ClusterFilter 구성

#### parser 필터 (CRI 포맷 / 멀티라인 JSON)

Kubernetes CRI(Containerd) 로그 형식 `<timestamp> <stream> <flags> <log>` 을 파싱하고,
Log4j2 기반 멀티라인 JSON 스택 트레이스를 단일 이벤트로 병합합니다.

| 파라미터 | 값 | 설명 |
|----------|----|------|
| `match` | `app.*` | 적용 대상 태그 |
| `keyName` | `log` | 파싱할 필드명 |
| `parser` | `cri` | CRI 기본 파서 |
| `multilineParser` | `multiline-log4j2` | Log4j2 멀티라인 파서 |
| `reserveData` | `true` | 원본 필드 보존 |
| `preserveKey` | `true` | 파싱 후 원본 키 보존 |

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterFilter
metadata:
  name: cri-parser-filter
  labels:
    fluentbit.fluent.io/enabled: "true"
    fluentbit.fluent.io/component: logging
spec:
  match: app.*
  filters:
    - parser:
        keyName: log
        parser: cri
        reserveData: true
        preserveKey: true
    - multilineParser:
        keyContent: log
        multilineParser: multiline-log4j2
        flushTimeout: 2000
```

#### modify 필터 (필드 추가 및 변환)

| 파라미터 | 값 | 설명 |
|----------|----|------|
| `match` | `app.*` | 적용 대상 태그 |
| `add` | `log_type = application` | 로그 유형 필드 추가 |
| `add` | `env = prod` | 환경 구분 필드 추가 |
| `rename` | `log → message` | 필드명 정규화 |
| `remove` | `stream` | 불필요한 CRI 필드 제거 |

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterFilter
metadata:
  name: field-modify-filter
  labels:
    fluentbit.fluent.io/enabled: "true"
    fluentbit.fluent.io/component: logging
spec:
  match: app.*
  filters:
    - modify:
        rules:
          - add:
              log_type: application
          - add:
              env: prod
          - rename:
              log: message
          - remove: stream
          - remove: _p
```

#### lua 필터 (커스텀 메타데이터 추출)

파일 경로(`/var/log/<namespace>/app*.log`)에서 namespace를 추출하고
클러스터 식별자를 주입합니다.

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterFilter
metadata:
  name: lua-metadata-filter
  labels:
    fluentbit.fluent.io/enabled: "true"
    fluentbit.fluent.io/component: logging
spec:
  match: app.*
  filters:
    - lua:
        script:
          key: lua_script
          name: extract_metadata.lua
        call: extract_metadata
        timeAsTable: true
```

`extract_metadata.lua` 스크립트 예시:

```lua
-- /etc/fluent-bit/scripts/extract_metadata.lua
function extract_metadata(tag, timestamp, record)
    -- 태그에서 네임스페이스 추출: app.<namespace>.<podname>
    local parts = {}
    for part in string.gmatch(tag, "[^.]+") do
        table.insert(parts, part)
    end

    if #parts >= 2 then
        record["kubernetes_namespace"] = parts[2]
    end

    -- 파일 경로에서 네임스페이스 추출
    if record["source"] then
        local ns = string.match(record["source"], "/var/log/([^/]+)/")
        if ns then
            record["namespace"] = ns
        end
    end

    -- 클러스터 식별자 주입
    record["cluster"] = "prod"
    record["cluster_id"] = "k8s-prod-01"

    -- 인덱스 날짜 접미사 생성 (YYYY.MM.DD)
    local date = os.date("*t", timestamp["sec"])
    record["index_date"] = string.format("%04d.%02d.%02d",
        date.year, date.month, date.day)

    return 1, timestamp, record
end
```

### 6.1.4 ClusterOutput 구성

#### OpenSearch 연결 파라미터

| 파라미터 | 값 | 설명 |
|----------|----|------|
| `host` | `opensearch.logging.svc.cluster.local` | OpenSearch 서비스 주소 |
| `port` | `9200` | OpenSearch HTTP 포트 |
| `httpUser` | Secret 참조 | 인증 사용자명 |
| `httpPassword` | Secret 참조 | 인증 패스워드 |
| `tls` | `false` | 내부 클러스터 통신 (클러스터 내부망) |
| `tlsVerify` | `false` | TLS 인증서 검증 여부 |
| `index` | `app-logs-prod` | 기본 인덱스 이름 |
| `logstashFormat` | `true` | `app-logs-prod-YYYY.MM.DD` 패턴 사용 |
| `logstashPrefix` | `app-logs-prod` | 인덱스 접두사 |
| `logstashDateFormat` | `%Y.%m.%d` | 날짜 포맷 |
| `bulkSize` | `5242880` (5MB) | 벌크 전송 최대 크기 |
| `retryLimit` | `5` | 전송 실패 시 재시도 횟수 |
| `bufferSize` | `64MB` | 응답 버퍼 크기 |

#### 멀티 인덱스 출력 전략

| 출력 CR명 | 태그 매치 | 인덱스 패턴 | 용도 |
|-----------|-----------|-------------|------|
| `opensearch-app-output` | `app.*` | `app-logs-{cluster}-YYYY.MM.DD` | 애플리케이션 로그 |
| `opensearch-k8sevt-output` | `kube.*` | `k8s-events-{cluster}-YYYY.MM.DD` | Kubernetes 이벤트 |
| `opensearch-systemd-output` | `systemd.*` | `systemd-logs-{cluster}-YYYY.MM.DD` | systemd 저널 로그 |

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterOutput
metadata:
  name: opensearch-app-output
  labels:
    fluentbit.fluent.io/enabled: "true"
    fluentbit.fluent.io/component: logging
spec:
  match: app.*
  opensearch:
    host: opensearch.logging.svc.cluster.local
    port: 9200
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
    index: app-logs-prod
    logstashFormat: true
    logstashPrefix: app-logs-prod
    logstashDateFormat: "%Y.%m.%d"
    tls:
      verify: false
    bulkSize: 5242880
    retryLimit: 5
    bufferSize: 64MB
---
apiVersion: fluentbit.fluent.io/v1alpha2
kind: ClusterOutput
metadata:
  name: opensearch-systemd-output
  labels:
    fluentbit.fluent.io/enabled: "true"
    fluentbit.fluent.io/component: logging
spec:
  match: systemd.*
  opensearch:
    host: opensearch.logging.svc.cluster.local
    port: 9200
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
    index: systemd-logs-prod
    logstashFormat: true
    logstashPrefix: systemd-logs-prod
    logstashDateFormat: "%Y.%m.%d"
    tls:
      verify: false
    bulkSize: 2097152
    retryLimit: 3
    bufferSize: 32MB
```

### 6.1.5 FluentBitConfig 파이프라인 바인딩

FluentBitConfig CR은 label selector를 통해 어떤 FluentBit 인스턴스에 어떤 Input/Filter/Output CR을 연결할지 바인딩합니다.

```yaml
apiVersion: fluentbit.fluent.io/v1alpha2
kind: FluentBitConfig
metadata:
  name: app-pipeline-config
  namespace: logging
spec:
  filterSelector:
    matchLabels:
      fluentbit.fluent.io/enabled: "true"
      fluentbit.fluent.io/component: logging
  inputSelector:
    matchLabels:
      fluentbit.fluent.io/enabled: "true"
      fluentbit.fluent.io/component: logging
  outputSelector:
    matchLabels:
      fluentbit.fluent.io/enabled: "true"
      fluentbit.fluent.io/component: logging
  service:
    daemon: false
    flushSeconds: 1
    graceSeconds: 30
    logLevel: info
    parsersFile: parsers.conf
    storage:
      backlogMemLimit: 128MB
      checksum: false
      maxChunksUp: 128
      path: /var/log/fluent-bit/storage
      sync: normal
```

#### 파이프라인 바인딩 매핑 표

| 레이블 키 | 레이블 값 | 바인딩되는 CR 유형 | 설명 |
|-----------|-----------|-------------------|------|
| `fluentbit.fluent.io/enabled` | `"true"` | ClusterInput, ClusterFilter, ClusterOutput | 파이프라인 활성화 필수 레이블 |
| `fluentbit.fluent.io/component` | `logging` | ClusterInput, ClusterFilter, ClusterOutput | 컴포넌트 구분 레이블 |
| `fluentbit.fluent.io/namespace` | `production` | ClusterInput | 특정 네임스페이스 범위 제한 (선택) |

#### 네임스페이스 셀렉터 / 파이프라인 연결 매핑 표

| 파이프라인 | ClusterInput | ClusterFilter (순서) | ClusterOutput | 대상 인덱스 |
|-----------|-------------|---------------------|--------------|-------------|
| 애플리케이션 로그 | `app-log-input` | cri-parser → field-modify → lua-metadata | `opensearch-app-output` | `app-logs-prod-YYYY.MM.DD` |
| systemd 저널 | `systemd-input` | field-modify | `opensearch-systemd-output` | `systemd-logs-prod-YYYY.MM.DD` |
| Kubernetes 이벤트 | (kube-state-events) | field-modify → lua-metadata | `opensearch-k8sevt-output` | `k8s-events-prod-YYYY.MM.DD` |

> **주의:** ClusterFilter는 `spec.match` 태그 패턴으로 자동 연결됩니다. 동일 태그에 복수의 Filter가 있을 경우 CR 생성 순서(creationTimestamp)에 따라 적용 순서가 결정됩니다.

---

## 6.2 OpenSearch 인덱스 및 템플릿 구성

### 6.2.1 인덱스 템플릿 구성

| 템플릿명 | 인덱스 패턴 | 샤드 수 | 레플리카 | 주요 매핑 |
|----------|-------------|---------|----------|-----------|
| `app-logs-template` | `app-logs-*` | 3 | 1 | `@timestamp` (date), `message` (text), `level` (keyword), `namespace` (keyword), `cluster` (keyword) |
| `k8s-events-template` | `k8s-events-*` | 2 | 1 | `@timestamp` (date), `reason` (keyword), `message` (text), `involvedObject.name` (keyword), `type` (keyword) |
| `systemd-logs-template` | `systemd-logs-*` | 2 | 1 | `@timestamp` (date), `SYSTEMD_UNIT` (keyword), `MESSAGE` (text), `PRIORITY` (keyword), `hostname` (keyword) |

인덱스 템플릿 생성 예시 (app-logs):

```bash
curl -X PUT "http://opensearch:9200/_index_template/app-logs-template" \
  -H "Content-Type: application/json" \
  -u admin:${OPENSEARCH_PASSWORD} \
  -d '{
    "index_patterns": ["app-logs-*"],
    "priority": 100,
    "template": {
      "settings": {
        "number_of_shards": 3,
        "number_of_replicas": 1,
        "index.refresh_interval": "5s",
        "index.translog.durability": "async",
        "index.translog.sync_interval": "30s"
      },
      "mappings": {
        "dynamic": false,
        "properties": {
          "@timestamp":      { "type": "date" },
          "message":         { "type": "text", "analyzer": "standard" },
          "level":           { "type": "keyword" },
          "namespace":       { "type": "keyword" },
          "kubernetes_namespace": { "type": "keyword" },
          "cluster":         { "type": "keyword" },
          "cluster_id":      { "type": "keyword" },
          "log_type":        { "type": "keyword" },
          "env":             { "type": "keyword" },
          "hostname":        { "type": "keyword" },
          "container_name":  { "type": "keyword" },
          "pod_name":        { "type": "keyword" },
          "index_date":      { "type": "keyword" }
        }
      }
    }
  }'
```

### 6.2.2 ISM Policy 구성

#### ISM 라이프사이클 개요

```
Hot(0-7d) → Warm(7-30d) → Cold(30-90d) → Delete(90d+)
           ↑ 리플리카 1   ↑ 리플리카 0   ↑ 읽기 전용
           검색 최적화    비용 절감      아카이브
```

#### ISM Policy 상세 구성 표

| 정책명 | Hot 보존 | Warm 이전 조건 | Cold 이전 조건 | 삭제 조건 | 대상 패턴 |
|--------|----------|----------------|----------------|-----------|-----------|
| `container-log-policy` | 7일 | 7일 경과 또는 50GB 초과 | 30일 경과 또는 100GB 초과 | 90일 경과 | `app-logs-*` |
| `k8s-event-policy` | 7일 | 7일 경과 또는 20GB 초과 | 없음 (Warm → Delete) | 30일 경과 | `k8s-events-*` |
| `systemd-log-policy` | 7일 | 7일 경과 또는 30GB 초과 | 14일 경과 또는 60GB 초과 | 60일 경과 | `systemd-logs-*` |

#### ISM 단계별 설정 내용

| 단계 | 설정 내용 | 목적 |
|------|-----------|------|
| **Hot** | `number_of_replicas: 1`, refresh 5s | 실시간 검색 성능 |
| **Warm** | `number_of_replicas: 0`, force merge (max_segments: 1), read-only | 스토리지 절약, 검색 비용 절감 |
| **Cold** | `number_of_replicas: 0`, read-only, snapshot 트리거 | 장기 보관, 스냅샷 백업 |
| **Delete** | 인덱스 삭제 | 디스크 공간 확보 |

container-log-policy ISM 생성 예시:

```bash
curl -X PUT "http://opensearch:9200/_plugins/_ism/policies/container-log-policy" \
  -H "Content-Type: application/json" \
  -u admin:${OPENSEARCH_PASSWORD} \
  -d '{
    "policy": {
      "description": "Container application log lifecycle policy",
      "default_state": "hot",
      "states": [
        {
          "name": "hot",
          "actions": [
            { "replica_count": { "number_of_replicas": 1 } }
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
            { "replica_count": { "number_of_replicas": 0 } },
            { "force_merge": { "max_num_segments": 1 } },
            { "read_only": {} }
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
            { "snapshot": {
                "repository": "minio-snapshot",
                "snapshot": "{{ctx.index}}"
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
            { "delete": {} }
          ],
          "transitions": []
        }
      ],
      "ism_template": [
        {
          "index_patterns": ["app-logs-*"],
          "priority": 100
        }
      ]
    }
  }'
```

### 6.2.3 스냅샷 저장소 구성 (MinIO/S3)

| 항목 | 값 | 설명 |
|------|----|------|
| 저장소명 | `minio-snapshot` | OpenSearch 내 참조명 |
| 타입 | `s3` | S3 호환 (MinIO 사용) |
| 버킷명 | `opensearch-snapshots` | MinIO 버킷 이름 |
| endpoint | `http://minio.storage.svc.cluster.local:9000` | MinIO 서비스 주소 |
| region | `us-east-1` | MinIO 더미 리전 (필수 파라미터) |
| path_style_access | `true` | MinIO 경로 방식 접근 |
| 자격증명 | Secret `minio-credentials` 참조 | access_key / secret_key |
| 스냅샷 주기 | ISM cold 단계 진입 시 자동 트리거 | 보존 기간 무제한 (버킷 정책으로 관리) |

스냅샷 저장소 등록:

```bash
curl -X PUT "http://opensearch:9200/_snapshot/minio-snapshot" \
  -H "Content-Type: application/json" \
  -u admin:${OPENSEARCH_PASSWORD} \
  -d '{
    "type": "s3",
    "settings": {
      "bucket": "opensearch-snapshots",
      "endpoint": "http://minio.storage.svc.cluster.local:9000",
      "protocol": "http",
      "path_style_access": "true",
      "region": "us-east-1",
      "access_key": "<MINIO_ACCESS_KEY>",
      "secret_key": "<MINIO_SECRET_KEY>"
    }
  }'
```

---

## 6.3 Log 파이프라인 점검

### 6.3.1 점검 항목 표

| # | 항목 | 점검 방법 | 정상 기준 | 결과 |
|---|------|-----------|-----------|------|
| 1 | Fluent Bit DaemonSet 전 노드 Running | `kubectl get pods -n logging -o wide` | 전체 노드 수 = Running Pod 수, Restarts 0 | ☐ |
| 2 | FluentBit CR 상태 | `kubectl get fluentbit -n logging` | READY=true | ☐ |
| 3 | FluentBitConfig 파이프라인 바인딩 | `kubectl get fluentbitconfig -n logging -o yaml` | inputSelector/filterSelector/outputSelector 정상 매핑 | ☐ |
| 4 | ClusterInput CR 상태 | `kubectl get clusterinput` | 전체 CR Active 상태 | ☐ |
| 5 | ClusterFilter CR 상태 | `kubectl get clusterfilter` | 전체 CR Active 상태 | ☐ |
| 6 | ClusterOutput CR 상태 | `kubectl get clusteroutput` | 전체 CR Active 상태 | ☐ |
| 7 | OpenSearch 인덱스 문서 유입 | `curl opensearch:9200/_cat/indices?v` | 오늘자 인덱스 존재, docs.count 증가 | ☐ |
| 8 | 멀티라인 파싱 검증 | 샘플 스택 트레이스 로그 검색 | 단일 document로 병합 확인 | ☐ |
| 9 | ISM Policy 적용 상태 | `curl opensearch:9200/_plugins/_ism/explain/app-logs-*` | 각 인덱스 ISM state 정상 | ☐ |
| 10 | OpenSearch Dashboards 조회 | 인덱스 패턴 생성 후 Discover 검색 | 로그 데이터 정상 조회 | ☐ |

### 6.3.2 Fluent Bit DaemonSet 상태 확인

```bash
# 전체 노드 Pod 상태 확인
kubectl get pods -n logging -o wide

# 예상 출력:
# NAME                 READY   STATUS    RESTARTS   AGE   IP             NODE
# fluent-bit-abcde     1/1     Running   0          2d    10.244.1.10    node-01
# fluent-bit-bcdef     1/1     Running   0          2d    10.244.2.11    node-02
# ...

# DaemonSet 롤아웃 상태 확인
kubectl rollout status daemonset/fluent-bit -n logging

# Fluent Bit 로그에서 에러 확인
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=100 | grep -E "error|Error|ERROR|warn|Warn"
```

### 6.3.3 FluentBitConfig 파이프라인 바인딩 상태

```bash
# FluentBitConfig CR 상세 확인
kubectl get fluentbitconfig -n logging -o yaml

# FluentBit CR 상태 확인
kubectl describe fluentbit fluent-bit -n logging

# 생성된 ConfigMap 확인 (Operator가 CR로부터 생성)
kubectl get configmap -n logging | grep fluent-bit
kubectl describe configmap fluent-bit-config -n logging
```

### 6.3.4 CR별 파이프라인 처리 상태 표

```bash
# 각 노드의 Fluent Bit 내부 메트릭 확인
kubectl exec -n logging <fluent-bit-pod> -- curl -s http://localhost:2020/api/v1/metrics/prometheus
```

| CR명 | 유형 | 처리건수 (예시) | 에러건수 (기준) | 상태 |
|------|------|----------------|----------------|------|
| `app-log-input` | ClusterInput | >0 (신규 로그 시) | 0 | ☐ |
| `systemd-input` | ClusterInput | >0 (저널 이벤트 시) | 0 | ☐ |
| `cri-parser-filter` | ClusterFilter | ≥ input 건수 | 0 | ☐ |
| `field-modify-filter` | ClusterFilter | ≥ input 건수 | 0 | ☐ |
| `lua-metadata-filter` | ClusterFilter | ≥ input 건수 | 0 | ☐ |
| `opensearch-app-output` | ClusterOutput | ≥ filter 건수 | 0 | ☐ |
| `opensearch-systemd-output` | ClusterOutput | ≥ filter 건수 | 0 | ☐ |

### 6.3.5 OpenSearch 인덱스 문서 유입 확인

```bash
# 전체 인덱스 목록 및 문서 수 확인
curl -s -u admin:${OPENSEARCH_PASSWORD} \
  "http://opensearch:9200/_cat/indices?v&s=index" | grep -E "app-logs|k8s-events|systemd-logs"

# 예상 출력:
# health status index                        uuid  pri rep docs.count docs.deleted store.size
# green  open   app-logs-prod-2026.03.10     xxxx  3   1  1523847    0             4.2gb
# green  open   systemd-logs-prod-2026.03.10 xxxx  2   1  89203      0             512mb

# 최근 10건 로그 조회
curl -s -u admin:${OPENSEARCH_PASSWORD} \
  "http://opensearch:9200/app-logs-prod-$(date +%Y.%m.%d)/_search?size=10&sort=@timestamp:desc&pretty"
```

### 6.3.6 멀티라인/CRI 포맷 파싱 검증

테스트용 멀티라인 스택 트레이스 로그 예시:

```
2026-03-10T10:00:00.123456789Z stdout F 2026-03-10 10:00:00,123 ERROR [main] com.example.App - Database connection failed
2026-03-10T10:00:00.123456790Z stdout P java.sql.SQLException: Connection refused
2026-03-10T10:00:00.123456791Z stdout P     at com.example.db.ConnectionPool.getConnection(ConnectionPool.java:42)
2026-03-10T10:00:00.123456792Z stdout P     at com.example.service.UserService.findUser(UserService.java:88)
2026-03-10T10:00:00.123456793Z stdout F     at com.example.App.main(App.java:15)
```

검증 방법:

```bash
# OpenSearch에서 멀티라인 병합 결과 확인
curl -s -u admin:${OPENSEARCH_PASSWORD} \
  "http://opensearch:9200/app-logs-prod-$(date +%Y.%m.%d)/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "match": { "level": "ERROR" }
    },
    "size": 1,
    "sort": [{ "@timestamp": "desc" }]
  }'

# 정상 파싱 확인 기준:
# - 하나의 document에 전체 스택 트레이스 포함
# - "level": "ERROR" 필드 추출 완료
# - "@timestamp" 정상 파싱
# - "namespace", "cluster", "cluster_id" 메타데이터 필드 존재
```

### 6.3.7 OpenSearch Dashboards 로그 조회

```
1. OpenSearch Dashboards 접속: http://opensearch-dashboards:5601
2. Management > Index Patterns > Create index pattern
3. Index pattern: app-logs-prod-*
4. Time field: @timestamp
5. Discover 탭에서 time range 설정 후 검색
6. 필터 추가: level=ERROR, namespace=<대상 네임스페이스>
```

---

## 6.4 Log 파이프라인 장애 패턴 및 조치

| # | 증상 | 원인 | 확인 명령 | 조치 방법 |
|---|------|------|-----------|-----------|
| 1 | Fluent Bit Pod OOMKilled | `memBufLimit` 초과 또는 Lua 스크립트 메모리 누수 | `kubectl describe pod <fluent-bit-pod> -n logging` → `OOMKilled` | memBufLimit 감소 (예: 64MB → 32MB), `storage.type: filesystem` 확인, Pod resource limits 상향, Lua 스크립트 메모리 누수 디버깅 |
| 2 | ClusterOutput OpenSearch 연결 실패 | TLS 설정 오류, 네트워크 정책, 인증 실패 | `kubectl logs <fluent-bit-pod> -n logging \| grep -i "opensearch\|output\|error"` | TLS 설정 확인 (`tls.verify: false`), NetworkPolicy 허용 여부 확인, Secret 자격증명 확인, `curl -v opensearch:9200` 테스트 |
| 3 | CRI 멀티라인 파싱 오류 | 파서 미스매치, `multilineParser` 미설정, CRI 플래그 (`P`/`F`) 누락 | Fluent Bit 로그에서 `parser` 에러 확인, OpenSearch에서 단일 라인으로 저장된 스택 트레이스 검색 | ClusterFilter의 `multilineParser` 설정 확인, `flushTimeout` 증가 (기본 2000ms → 5000ms), Containerd 로그 드라이버 설정 재확인 |
| 4 | 인덱스 매핑 충돌 | 동일 필드에 다른 타입 데이터 유입, 인덱스 템플릿 미적용 | `curl opensearch:9200/app-logs-*/_mapping` 확인, Fluent Bit 로그에서 `400 Bad Request` 확인 | 인덱스 템플릿 우선순위 (`priority`) 상향, 신규 인덱스 생성 후 템플릿 재적용, 문제 필드를 `keyword` → `text` 또는 별도 필드로 분리, `dynamic: false` 설정으로 예상치 못한 필드 차단 |
| 5 | Fluent Bit 백프레셔 / 로그 손실 | OpenSearch 수신 지연으로 인한 버퍼 초과 | `kubectl exec <fluent-bit-pod> -- curl localhost:2020/api/v1/metrics/prometheus \| grep storage` | `storage.max_chunks_up` 증가, `storage.backlog_mem_limit` 상향, OpenSearch 벌크 크기 및 재시도 튜닝, Throttle 플러그인 추가: `Throttle: Rate 1000 Window 3 Print true` |
| 6 | OpenSearch 디스크 워터마크 도달 | Hot 인덱스 과도 축적, ISM Policy 미적용 | `curl opensearch:9200/_cluster/settings`, `curl opensearch:9200/_cat/allocation?v` | ISM Policy 적용 여부 확인, 오래된 인덱스 수동 삭제, `cluster.routing.allocation.disk.watermark.low/high/flood_stage` 임계값 조정, 긴급 시 read_only_allow_delete 해제: `PUT /_all/_settings {"index.blocks.read_only_allow_delete": null}` |

### 6.4.1 OOM 방어 4계층 구성

| 계층 | 설정 위치 | 파라미터 | 권장값 | 역할 |
|------|-----------|----------|--------|------|
| 1계층 | ClusterInput | `memBufLimit` | `64MB` (app), `32MB` (systemd) | 입력 플러그인 메모리 버퍼 상한 |
| 2계층 | FluentBitConfig | `storage.type: filesystem` | `filesystem` | 버퍼 초과 시 디스크로 오버플로우 |
| 3계층 | ClusterFilter | `Throttle` 플러그인 | `Rate 1000, Window 3` | 처리량 상한 제어 |
| 4계층 | FluentBit CR | `resources.limits.memory` | `512Mi` | Pod 레벨 메모리 하드 리밋 |

```yaml
# FluentBit CR의 Pod resource limits 예시
apiVersion: fluentbit.fluent.io/v1alpha2
kind: FluentBit
metadata:
  name: fluent-bit
  namespace: logging
spec:
  image: fluent/fluent-bit:2.2.2
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi
  tolerations:
    - operator: Exists
  volumes:
    - name: varlog
      hostPath:
        path: /var/log
    - name: fluent-bit-storage
      hostPath:
        path: /var/log/fluent-bit
  volumeMounts:
    - name: varlog
      mountPath: /var/log
      readOnly: true
    - name: fluent-bit-storage
      mountPath: /var/log/fluent-bit
```
