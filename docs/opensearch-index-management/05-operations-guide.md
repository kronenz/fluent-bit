# 운영 가이드

## 1. 일상 운영 체크리스트

### 매일

- [ ] 클러스터 상태 확인 (green/yellow/red)
- [ ] 당일 인덱스 정상 생성 확인
- [ ] 디스크 사용량 확인
- [ ] ISM 정책 실행 오류 확인

### 매주

- [ ] 인덱스 수 및 샤드 수 검토
- [ ] ISM 정책에 의한 삭제 이력 확인
- [ ] Fluent Bit 수집 지연 확인
- [ ] 노드별 디스크 밸런스 확인

### 매월

- [ ] 보관 정책 적정성 검토
- [ ] 디스크 용량 트렌드 분석
- [ ] 인덱스 템플릿 업데이트 필요 여부 검토
- [ ] 성능 튜닝 (샤드 크기, refresh_interval 등)

## 2. 모니터링 명령어

### 클러스터 상태

```bash
# 클러스터 헬스 확인
curl -s "http://opensearch:9200/_cluster/health?pretty"

# 결과 예시:
# {
#   "status": "green",          ← green/yellow/red
#   "number_of_nodes": 3,
#   "active_shards": 150,
#   "unassigned_shards": 0      ← 0이어야 정상
# }
```

### 인덱스 상태

```bash
# 전체 인덱스 목록 (크기/문서수/상태)
curl -s "http://opensearch:9200/_cat/indices?v&s=index&h=health,status,index,docs.count,store.size,pri.store.size"

# 특정 패턴 인덱스만 조회
curl -s "http://opensearch:9200/_cat/indices/container-logs-*?v&s=index"
curl -s "http://opensearch:9200/_cat/indices/k8s-events-*?v&s=index"
curl -s "http://opensearch:9200/_cat/indices/systemd-logs-*?v&s=index"
```

### 인덱스 수 확인

```bash
# 로그 유형별 인덱스 수
echo "Container logs:"; curl -s "http://opensearch:9200/_cat/indices/container-logs-*" | wc -l
echo "K8s events:"; curl -s "http://opensearch:9200/_cat/indices/k8s-events-*" | wc -l
echo "Systemd logs:"; curl -s "http://opensearch:9200/_cat/indices/systemd-logs-*" | wc -l
```

### ISM 정책 실행 상태

```bash
# 전체 ISM 관리 인덱스 상태 확인
curl -s "http://opensearch:9200/_plugins/_ism/explain?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for idx,info in data.items():
  if isinstance(info, dict) and 'index.plugins.index_state_management.policy_id' in info:
    state = info.get('state', {}).get('name', 'N/A')
    policy = info.get('index.plugins.index_state_management.policy_id', 'N/A')
    print(f'{idx}: state={state}, policy={policy}')
"

# 특정 인덱스의 ISM 상세 상태
curl -s "http://opensearch:9200/_plugins/_ism/explain/container-logs-bigdata-prod-2026.02.26?pretty"
```

### ISM 실행 오류 확인

```bash
# 실패한 ISM 작업 확인
curl -s "http://opensearch:9200/_plugins/_ism/explain?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for idx,info in data.items():
  if isinstance(info, dict):
    retry = info.get('retry_info', {})
    if retry and retry.get('failed', False):
      print(f'FAILED: {idx} - {retry}')
"
```

### 디스크 사용량

```bash
# 노드별 디스크 사용량
curl -s "http://opensearch:9200/_cat/allocation?v&h=node,disk.used,disk.avail,disk.total,disk.percent"

# 인덱스별 크기 (상위 20개)
curl -s "http://opensearch:9200/_cat/indices?v&s=store.size:desc&h=index,store.size,docs.count" | head -20
```

### 샤드 상태

```bash
# 미할당 샤드 확인 (yellow/red 원인 파악)
curl -s "http://opensearch:9200/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason" | grep UNASSIGNED

# 노드별 샤드 수
curl -s "http://opensearch:9200/_cat/allocation?v&h=node,shards"
```

## 3. 트러블슈팅

### 3-1. 인덱스가 Yellow 상태인 경우

**원인:** Replica 샤드를 할당할 노드가 부족합니다.

```bash
# 원인 확인
curl -s "http://opensearch:9200/_cluster/allocation/explain?pretty"

# 해결: 단일 노드 환경에서는 replica를 0으로 변경
curl -X PUT "http://opensearch:9200/container-logs-*/_settings" \
  -H 'Content-Type: application/json' \
  -d '{"index.number_of_replicas": 0}'
```

### 3-2. ISM 정책이 적용되지 않는 경우

**확인 순서:**

```bash
# 1. 정책 존재 확인
curl -s "http://opensearch:9200/_plugins/_ism/policies/container-logs-policy?pretty"

# 2. 인덱스에 정책이 연결되었는지 확인
curl -s "http://opensearch:9200/_plugins/_ism/explain/container-logs-*?pretty"

# 3. 정책이 없으면 수동 적용
curl -X POST "http://opensearch:9200/_plugins/_ism/add/container-logs-*" \
  -H 'Content-Type: application/json' \
  -d '{"policy_id": "container-logs-policy"}'

# 4. 인덱스 템플릿에 ISM 정책 연결 확인
curl -s "http://opensearch:9200/_index_template/container-logs-template?pretty" | \
  python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2))"
```

### 3-3. 인덱스가 생성되지 않는 경우

```bash
# 1. Fluent Bit Pod 상태 확인
kubectl get pods -n logging -l app.kubernetes.io/name=fluent-bit

# 2. Fluent Bit 로그 확인
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=50

# 3. OpenSearch 연결 테스트 (Fluent Bit Pod 내에서)
kubectl exec -n logging -it $(kubectl get pod -n logging -l app.kubernetes.io/name=fluent-bit -o jsonpath='{.items[0].metadata.name}') -- \
  curl -s "http://opensearch-cluster-master.logging.svc.cluster.local:9200/_cluster/health"

# 4. Output 플러그인 오류 확인
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=100 | grep -i "error\|warn\|retry"
```

### 3-4. 디스크 공간 부족

**긴급 조치:**

```bash
# 1. 가장 오래된 인덱스 확인
curl -s "http://opensearch:9200/_cat/indices?v&s=index&h=index,store.size,creation.date.string" | head -20

# 2. 오래된 인덱스 수동 삭제 (주의: 복구 불가)
curl -X DELETE "http://opensearch:9200/container-logs-bigdata-prod-2026.01.01"

# 3. 날짜 범위로 일괄 삭제 (예: 60일 이전)
# 먼저 삭제 대상 확인
curl -s "http://opensearch:9200/_cat/indices/container-logs-*?v&s=index" | head -30

# 확인 후 삭제
curl -X DELETE "http://opensearch:9200/container-logs-*-2025.12.*"
```

**근본 해결:**

```bash
# ISM 정책의 보관기간 단축
# 03-ism-policies.md의 "보관기간 조정 가이드" 참조
```

### 3-5. ISM 정책 전환 실패 (stuck in transition)

```bash
# 1. 실패 원인 확인
curl -s "http://opensearch:9200/_plugins/_ism/explain/container-logs-bigdata-prod-2026.01.15?pretty"

# 2. 수동으로 재시도
curl -X POST "http://opensearch:9200/_plugins/_ism/retry/container-logs-bigdata-prod-2026.01.15" \
  -H 'Content-Type: application/json' \
  -d '{"state": "warm"}'

# 3. 전체 실패 인덱스 일괄 재시도
for idx in $(curl -s "http://opensearch:9200/_plugins/_ism/explain?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for idx,info in data.items():
  if isinstance(info, dict):
    retry = info.get('retry_info', {})
    if retry and retry.get('failed', False):
      print(idx)
"); do
  echo "Retrying: $idx"
  curl -X POST "http://opensearch:9200/_plugins/_ism/retry/$idx"
done
```

### 3-6. 매핑 충돌 (mapping conflict)

동일 필드에 다른 타입이 들어올 때 발생합니다.

```bash
# 1. 현재 매핑 확인
curl -s "http://opensearch:9200/container-logs-bigdata-prod-2026.02.26/_mapping?pretty"

# 2. 충돌 필드 식별
# 에러 메시지 예: "mapper [field_name] cannot be changed from type [keyword] to [text]"

# 3. 해결: 인덱스 템플릿에 해당 필드의 타입을 명시적으로 정의
# 02-index-templates.md 참조
```

## 4. 백업 및 복구

### 스냅샷 리포지토리 등록

```bash
# 공유 파일시스템 기반 스냅샷 리포지토리
curl -X PUT "http://opensearch:9200/_snapshot/log-backup" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "fs",
    "settings": {
      "location": "/mnt/opensearch-backup/log-backup",
      "compress": true
    }
  }'
```

> **주의:** `path.repo` 설정이 opensearch.yml에 등록되어 있어야 합니다.

### 스냅샷 생성

```bash
# 전체 로그 인덱스 스냅샷
curl -X PUT "http://opensearch:9200/_snapshot/log-backup/snapshot-$(date +%Y%m%d)?wait_for_completion=true" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "container-logs-*,k8s-events-*,systemd-logs-*",
    "ignore_unavailable": true,
    "include_global_state": false
  }'
```

### 자동 스냅샷 (CronJob)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: opensearch-snapshot
  namespace: logging
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: snapshot
              image: curlimages/curl:latest
              command:
                - /bin/sh
                - -c
                - |
                  DATE=$(date +%Y%m%d)
                  curl -X PUT "http://opensearch-cluster-master:9200/_snapshot/log-backup/snapshot-${DATE}?wait_for_completion=true" \
                    -H 'Content-Type: application/json' \
                    -d '{
                      "indices": "container-logs-*,k8s-events-*,systemd-logs-*",
                      "ignore_unavailable": true,
                      "include_global_state": false
                    }'
          restartPolicy: OnFailure
```

### 스냅샷 복구

```bash
# 스냅샷 목록 확인
curl -s "http://opensearch:9200/_snapshot/log-backup/_all?pretty"

# 특정 스냅샷에서 인덱스 복구
curl -X POST "http://opensearch:9200/_snapshot/log-backup/snapshot-20260226/_restore" \
  -H 'Content-Type: application/json' \
  -d '{
    "indices": "container-logs-bigdata-prod-2026.02.25",
    "ignore_unavailable": true,
    "include_global_state": false
  }'
```

## 5. 알림 설정

### OpenSearch Alerting을 통한 디스크 경고

```bash
# 디스크 사용률 80% 초과 시 알림
curl -X POST "http://opensearch:9200/_plugins/_alerting/monitors" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "monitor",
    "name": "Disk Usage Alert",
    "enabled": true,
    "schedule": {
      "period": {
        "interval": 5,
        "unit": "MINUTES"
      }
    },
    "inputs": [
      {
        "uri": {
          "api_type": "CLUSTER_HEALTH",
          "path": "_cat/allocation?format=json",
          "path_params": "",
          "url": ""
        }
      }
    ],
    "triggers": [
      {
        "name": "High Disk Usage",
        "severity": "2",
        "condition": {
          "script": {
            "source": "for (item in ctx.results[0]) { if (item.disk_percent != null && Integer.parseInt(item.disk_percent) > 80) return true; } return false;",
            "lang": "painless"
          }
        },
        "actions": []
      }
    ]
  }'
```

### ISM 삭제 알림

ISM 정책의 delete 단계에 알림을 설정하여 인덱스 삭제를 추적합니다. `03-ism-policies.md`의 Container Log 정책에 notification 액션이 포함되어 있습니다.

## 6. 성능 튜닝

### refresh_interval 최적화

```bash
# 로그 인덱스는 실시간 검색이 덜 중요하므로 interval 증가
# 쓰기 성능 10~30% 향상

# Container logs: 10초
curl -X PUT "http://opensearch:9200/container-logs-*/_settings" \
  -H 'Content-Type: application/json' \
  -d '{"index.refresh_interval": "10s"}'

# K8s events: 30초
curl -X PUT "http://opensearch:9200/k8s-events-*/_settings" \
  -H 'Content-Type: application/json' \
  -d '{"index.refresh_interval": "30s"}'
```

### Bulk 크기 조정 (Fluent Bit)

Fluent Bit의 flush 설정으로 OpenSearch에 전송하는 bulk 크기를 조절합니다.

```yaml
# ClusterFluentBitConfig에서 조정
spec:
  service:
    flushSeconds: 3    # 1초 → 3초로 변경하면 bulk 크기 증가, 쓰기 효율 향상
```

### 인덱스 설정 최적화 요약

| 설정 | 로그 수집 최적화 값 | 기본값 | 효과 |
|------|-------------------|--------|------|
| `refresh_interval` | 10~30s | 1s | 쓰기 성능 향상 |
| `codec` | best_compression | default | 디스크 30~50% 절약 |
| `number_of_replicas` | 0~1 | 1 | 디스크/성능 절약 |
| `translog.durability` | async | request | 쓰기 성능 향상 (데이터 손실 위험) |
| `merge.policy.max_merged_segment` | 5gb | 5gb | 기본값 유지 |

## 7. 유용한 스크립트

### 인덱스 상태 종합 리포트

```bash
#!/bin/bash
# opensearch-report.sh
OPENSEARCH_URL="${OPENSEARCH_URL:-http://opensearch-cluster-master.logging.svc.cluster.local:9200}"

echo "=== OpenSearch 클러스터 상태 ==="
curl -s "$OPENSEARCH_URL/_cluster/health?pretty"

echo ""
echo "=== 로그 유형별 인덱스 현황 ==="
for type in container-logs k8s-events systemd-logs; do
  count=$(curl -s "$OPENSEARCH_URL/_cat/indices/${type}-*" 2>/dev/null | wc -l)
  size=$(curl -s "$OPENSEARCH_URL/_cat/indices/${type}-*?h=store.size" 2>/dev/null | \
    awk '{s+=$1} END {print s}')
  echo "${type}: ${count}개 인덱스, 총 ${size:-0}"
done

echo ""
echo "=== 디스크 사용량 ==="
curl -s "$OPENSEARCH_URL/_cat/allocation?v&h=node,disk.used,disk.avail,disk.percent"

echo ""
echo "=== ISM 정책 실행 오류 ==="
curl -s "$OPENSEARCH_URL/_plugins/_ism/explain?pretty" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
errors=[]
for idx,info in data.items():
  if isinstance(info, dict):
    retry = info.get('retry_info', {})
    if retry and retry.get('failed', False):
      errors.append(f'  - {idx}: {retry}')
if errors:
  print('\n'.join(errors))
else:
  print('  오류 없음')
" 2>/dev/null || echo "  확인 불가"

echo ""
echo "=== 최근 생성된 인덱스 (최근 5개) ==="
curl -s "$OPENSEARCH_URL/_cat/indices?v&s=creation.date:desc&h=index,creation.date.string,store.size,docs.count" | head -6
```

### ISM 정책 일괄 적용 스크립트

```bash
#!/bin/bash
# apply-ism-policies.sh
OPENSEARCH_URL="${OPENSEARCH_URL:-http://opensearch-cluster-master.logging.svc.cluster.local:9200}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="${SCRIPT_DIR}/templates"

echo "=== ISM 정책 적용 ==="

# 1. ISM 정책 생성
for policy in container-logs k8s-events systemd-logs; do
  echo "정책 생성: ${policy}-policy"
  curl -s -X PUT "$OPENSEARCH_URL/_plugins/_ism/policies/${policy}-policy" \
    -H 'Content-Type: application/json' \
    -d @"${TEMPLATE_DIR}/ism-policy-${policy}.json"
  echo ""
done

# 2. 인덱스 템플릿 생성
for template in container-logs k8s-events systemd-logs; do
  echo "템플릿 생성: ${template}-template"
  curl -s -X PUT "$OPENSEARCH_URL/_index_template/${template}-template" \
    -H 'Content-Type: application/json' \
    -d @"${TEMPLATE_DIR}/index-template-${template}.json"
  echo ""
done

# 3. 기존 인덱스에 정책 적용
echo "기존 인덱스에 정책 연결..."
curl -s -X POST "$OPENSEARCH_URL/_plugins/_ism/add/container-logs-*" \
  -H 'Content-Type: application/json' -d '{"policy_id": "container-logs-policy"}'
curl -s -X POST "$OPENSEARCH_URL/_plugins/_ism/add/k8s-events-*" \
  -H 'Content-Type: application/json' -d '{"policy_id": "k8s-events-policy"}'
curl -s -X POST "$OPENSEARCH_URL/_plugins/_ism/add/systemd-logs-*" \
  -H 'Content-Type: application/json' -d '{"policy_id": "systemd-logs-policy"}'

echo ""
echo "=== 완료 ==="
```
