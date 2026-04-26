# 테스트 결과서 양식

[20-scenario-spec.md](20-scenario-spec.md) 의 15개 시나리오 + 종합 결과서를
기록하는 템플릿. 각 양식을 Day 별로 채우면 그대로 운영 보고용 문서로 사용 가능.

---

## 0. 표지 / 메타정보

| 항목 | 내용 |
|------|------|
| 테스트 명 | 모니터링 모듈 부하/장애 테스트 (190대 cluster 운영 전 검증) |
| 테스트 기간 | 2026-MM-DD ~ 2026-MM-DD (4일) |
| 환경 | Kubernetes (helm: kube-prometheus-stack {{ver}}, opensearch {{ver}}, fluent-bit {{ver}}) |
| 노드 사양 | _{{노드 수}} × {{CPU}}c / {{Memory}}GB_ |
| OS 클러스터 구성 | _{{혼합노드 N}} (data {{n}} / master {{n}})_ |
| Image | `{{registry}}/loadtest-tools:0.1.1` |
| 테스트 수행자 | _{{이름}}_ |
| 종합 판정 | ☐ PASS / ☐ WARN / ☐ FAIL |

---

## 1. 시나리오 결과 (각 시나리오 마다 채워서 입력)

### 1.1 OS-01 — Bulk Indexing 처리량/지연

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM |
| 실행자 | _{{이름}}_ |
| 조작변수 | `OSB_WORKLOAD={{}}, OSB_TEST_MODE={{}}, OSB_BULK_SIZE={{}}, OSB_CLIENTS={{}}` |
| 통제변수 | OS heap={{ }}GB, shard={{ }}, replica={{ }}, refresh_interval=1s, 동시 ingest=없음 |
| Job 상태 | ☐ Complete (1/1) / ☐ Failed |
| 측정값 - throughput | ___ docs/s |
| 측정값 - p95 | ___ ms |
| 측정값 - p99 | ___ ms |
| 측정값 - error rate | ___ % |
| **임계값** | TPS ≥ 30k (운영) / ≥ 200 (test-mode), p95 < 500ms (운영) / < 50ms (test) |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 / 이슈 | _{{}}_ |
| 결과 파일 | `~/loadtest-results/dayX/opensearch-benchmark.log` |
| Grafana 스냅샷 | _{{URL 또는 파일명}}_ |

### 1.2 OS-08 — 190대 Sustainable TPS

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (1시간 sustained) |
| 조작변수 | `flog replicas={{}}, target-throughput={{}}, OSB_BULK_SIZE={{}}` |
| 통제변수 | OS shard / replica / heap, refresh_interval=1s, 검색 부하 없음 |
| 측정값 - sustained TPS | ___ docs/s (1시간 평균) |
| 측정값 - heap drift | 시작 ___% → 종료 ___% (변화 ___%p) |
| 측정값 - segment count | 시작 ___ → 종료 ___ (마지막 10분 변화율 ___%) |
| 측정값 - reject rate | ___ % |
| **임계값** | sustained TPS ≥ 30k × 1h, heap drift < 10%p, segment 안정 (< 5%/10m) |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{}}_ |

### 1.3 OS-09 — Spark/Airflow Wave (Spike)

| 항목 | 값 |
|------|-----|
| 실행 일시 | T0=___ T1=___ duration=___s |
| 조작변수 | flog `replicas: {{baseline}} → {{burst}}` |
| 통제변수 | fluent-bit Mem_Buf_Limit, Storage 설정, OS reject queue size |
| 측정값 - burst peak rate | ___ lines/s |
| 측정값 - filesystem buffer 최대 사용 | ___ % |
| 측정값 - OS reject 발생 | ___ events/s |
| 측정값 - 정상화 시간 | ___ s (burst 종료 후 baseline 회복) |
| **임계값** | buffer < 80%, reject < 1%, 정상화 < 5분 |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{}}_ |

### 1.4 OS-16 — 인덱싱+검색 동시 (★ 핵심 SLO)

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (30분) |
| 조작변수 | `LIGHT_SEARCH_VUS={{}}, query 패턴={{range/bool/match}}` |
| 통제변수 | OS heap, shard/replica, **thread pool 분리 설정**, 동시 ingest 강도 |
| 측정값 - search p95 | ___ ms (★ 핵심) |
| 측정값 - search p99 | ___ ms |
| 측정값 - fail rate | ___ % |
| 측정값 - total reqs | ___ |
| 측정값 - ingest 영향 | flog drop ___ events/s |
| **임계값 (★)** | **p95 < 5,000 ms**, p99 < 10,000 ms, fail < 1%, ingest drop = 0 |
| 판정 | ☐ PASS / ☐ FAIL |
| **운영 적용 가능 여부** | ☐ YES / ☐ NO (FAIL 시 NO) |
| 비고 / 운영 액션 | _{{thread pool 분리 / replica 증설 / query cache 등 권장}}_ |

### 1.5 CHAOS-OS-07 — Node 장애 회복

| 항목 | 값 |
|------|-----|
| 실행 일시 | T0=___ |
| Target | _{{어떤 OS pod 죽였나}}_ |
| 조작변수 | TARGET_POD_LABEL, 동시 장애 수 (1) |
| 통제변수 | replica ≥ 1 필수, 부하 진행 중 (50% baseline) |
| 측정값 - RED 진입 | ___ s |
| 측정값 - YELLOW 진입 | ___ s |
| 측정값 - GREEN 회복 | ___ s |
| 측정값 - 데이터 손실 | ___ docs (재실행 가능 인덱스에서 사전/사후 doc count 차이) |
| **임계값** | RED < 30s, YELLOW→GREEN < 600s, 손실 = 0 |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{testbed=의도 FAIL / 운영=PASS 기대}}_ |

### 1.6 OS-PV — PV 장애

| 항목 | 값 |
|------|-----|
| 실행 일시 | T0=___ T1=___ |
| PV 종류 | ☐ EBS / ☐ GCEPD / ☐ NFS / ☐ hostPath / ☐ {{기타}} |
| 장애 방식 | ☐ detach / ☐ readonly / ☐ delete / ☐ {{기타}} |
| 측정값 - GREEN 회복 | ___ s |
| 측정값 - 손실 doc | ___ |
| 측정값 - recovery throughput | ___ MB/s (`indices.recovery.max_bytes_per_sec`) |
| **임계값** | 회복 < 30분, 손실 = 0 (replica ≥ 1 시) |
| 판정 | ☐ PASS / ☐ FAIL / ☐ N/A (testbed) |
| 비고 | _{{snapshot 사전 구성 여부 등}}_ |

### 1.7 FB-OOM — 단일 Pod Throughput Ceiling

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (~18m 자동 ramp) |
| Stage 별 측정값 | |
| - baseline (1 replica) | RSS ___ MB |
| - normal (3 replica) | RSS ___ MB |
| - high (10 replica) | RSS ___ MB |
| - peak (30 replica) | RSS ___ MB / OOMKilled? ☐ |
| **운영 limit 권장** | max(high RSS × 1.5, peak RSS × 1.2) = ___ MB → ___ MB (반올림) |
| 현재 helm 설정 | limit = ___ MB |
| 운영 적용 액션 | helm values 의 `resources.limits.memory: ___MB` |
| 판정 | ☐ PASS (peak 까지 안정) / ☐ FAIL (OOMKilled 발생) |
| 비고 | _{{Mem_Buf_Limit 등 추가 튜닝 필요 여부}}_ |

### 1.8 FB-PROD — 190대 운영 성능 (1시간 sustained)

| 항목 | 값 |
|------|-----|
| 실행 일시 | T0=___ T1=___ duration=___s |
| 조작변수 | flog `replicas=10`, FLOG_DELAY=100us |
| 통제변수 | FB limit (FB-OOM 결과 기반), filesystem buffer hostPath |
| 측정값 - input rate | ___ lines/s (1h 평균) |
| 측정값 - output rate | ___ lines/s |
| 측정값 - drop rate | ___ events/s |
| 측정값 - buffer 사용 | min ___% / max ___% |
| 측정값 - DaemonSet OOMKilled | ___ 회 |
| **임계값** | input ≈ output, drop = 0, buffer 안정, OOM = 0 |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{}}_ |

### 1.9 FB-BURST — Log Burst Spike

| 항목 | 값 |
|------|-----|
| 실행 일시 | burst T0=___ T1=___ duration=___s |
| 조작변수 | flog `replicas: 5 → 30 → 5`, burst 30s |
| 측정값 - burst peak input | ___ lines/s |
| 측정값 - buffer 최대 사용 | ___ % |
| 측정값 - drop 발생 | ___ events |
| 측정값 - 정상화 시간 | ___ s (burst 후 buffer 정상) |
| **임계값** | buffer < 80%, drop < 0.01%, 정상화 < 2분 |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{}}_ |

### 1.10 PR-HA — Prometheus High Availability

| 항목 | 값 |
|------|-----|
| 실행 일시 | T0=___ |
| 사전 replica 수 | ___ → 2 (변경) |
| 죽인 pod | _{{pod 이름}}_ |
| 측정값 - 다른 replica 가동 지속 | ☐ Yes / ☐ No |
| 측정값 - alert 도착 끊김 | ___ s |
| 측정값 - 죽은 replica 자동 재시작 | ___ s |
| **임계값** | alert 끊김 < 60s, 자동 재시작 < 5분 |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{Alertmanager cluster mode 활성 여부 등}}_ |

### 1.11 PR-SCRAPE — Active Series 적재

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (정착 30분) |
| 조작변수 | avalanche `replicas=___`, gauge_count=___, series_count=___ |
| 측정값 - active series | ___ |
| 측정값 - prometheus heap 사용 | ___ % |
| 측정값 - scrape p95 | ___ ms |
| 측정값 - WAL replay 시간 | ___ s (재시작 시) |
| **임계값** | series 흡수 가능, heap < 80%, scrape p95 < 0.5s |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{}}_ |

### 1.12 PR-QUERY — k6 PromQL 부하

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (5분) |
| 조작변수 | `K6_PROMQL_VUS=20, K6_PROMQL_DURATION=5m` |
| 측정값 - http_req_duration p95 | ___ ms |
| 측정값 - http_req_failed | ___ % |
| 측정값 - 총 요청 수 | ___ |
| 측정값 - prometheus query rate | ___ req/s |
| **임계값** | p95 < 2,000 ms, fail < 1% |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{}}_ |

### 1.13 NE-COST — Scrape 비용

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (2분) |
| 조작변수 | `HEY_CONCURRENCY=10, HEY_RPS_PER_WORKER=50, HEY_DURATION=2m` (≈ 500 RPS) |
| 측정값 - 200 응답 비율 | ___ % |
| 측정값 - Average 응답 시간 | ___ ms |
| 측정값 - p99 응답 시간 | ___ ms |
| 측정값 - NE CPU 사용 | peak ___ % |
| 측정값 - NE 재시작 | ___ 회 (시나리오 후 - 시나리오 전) |
| **임계값** | 200 = 100%, Average < 50ms, OOM = 0 |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{NE limit 32Mi 면 FAIL}}_ |

### 1.14 NE-FREQ — 고빈도 Scrape Ramp

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (5분 자동 ramp) |
| Stage 별 측정값 | |
| - baseline (500 RPS) | RSS ___ MB |
| - normal (2,500 RPS) | RSS ___ MB |
| - high (5,000 RPS) | RSS ___ MB |
| - peak (10,000 RPS) | RSS ___ MB |
| 측정값 - OOMKilled stage | _{{어느 stage 부터 0 MB?}}_ |
| **운영 limit 권장** | peak RSS × 1.5 = ___ MB |
| 판정 | ☐ PASS (모든 stage > 0) / ☐ FAIL |
| 비고 | _{{}}_ |

### 1.15 KSM-OOM — Kube-state-metrics OOM 한계

| 항목 | 값 |
|------|-----|
| 실행 일시 | YYYY-MM-DD HH:MM ~ HH:MM (5분) |
| 조작변수 | `jobIterations=50` (testbed) / `5000` (운영) |
| Stage 별 측정값 | |
| - baseline | RSS ___ MB / scrape ___ s |
| - ramp-1 (30s) | RSS ___ MB / scrape ___ s |
| - ramp-3 (90s) | RSS ___ MB / scrape ___ s |
| - ramp-6 (180s) | RSS ___ MB / scrape ___ s |
| - post (cleanup 후) | RSS ___ MB / scrape ___ s |
| **운영 limit 권장** | peak RSS × 1.5 = ___ MB |
| **임계값** | scrape duration < 5s |
| 판정 | ☐ PASS / ☐ FAIL |
| 비고 | _{{운영 5000 iter 추정 권장}}_ |

---

## 2. SLO 종합 매트릭스

| 컴포넌트 | SLO 목표 | 실측값 | 판정 | 운영 액션 |
|----------|----------|--------|------|-----------|
| OS indexing TPS (sustained) | ≥ 30k docs/s × 1h | ___ docs/s | ☐ | _{{}}_ |
| OS search p95 (★ 핵심) | < 5,000 ms (heavy ingest 동시) | ___ ms | ☐ | _{{}}_ |
| OS green 회복 (node 장애) | < 10분 | ___ s | ☐ | _{{}}_ |
| OS PV 회복 | < 30분 | ___ s | ☐ | _{{}}_ |
| FB drop rate (sustained) | 0 | ___ events/s | ☐ | _{{}}_ |
| FB buffer 안정 (burst) | < 80% | ___ % | ☐ | _{{}}_ |
| FB OOMKilled (운영급 부하) | 0 | ___ 회 | ☐ | _{{}}_ |
| PR alert 끊김 (HA) | < 60s | ___ s | ☐ | _{{}}_ |
| PR scrape p95 (5M series) | < 0.5s | ___ ms | ☐ | _{{}}_ |
| PR query p95 (20 VU) | < 2s | ___ ms | ☐ | _{{}}_ |
| NE 200 비율 (정상 RPS) | 100% | ___ % | ☐ | _{{}}_ |
| NE OOMKilled (정상 부하) | 0 | ___ 회 | ☐ | _{{}}_ |
| KSM scrape duration | < 5s | ___ s | ☐ | _{{}}_ |

---

## 3. 발견된 운영 이슈 및 즉시 적용 필요 사항

| # | 이슈 | 발견 시나리오 | 권장 조치 | 우선순위 | 책임자 |
|---|------|-------------|-----------|----------|--------|
| 1 | _{{node-exporter helm chart limit 32Mi}}_ | NE-COST | helm values: limit=256Mi 이상 | High | _{{}}_ |
| 2 | _{{OS replica=1 default + single-node yellow}}_ | OS-01 | 운영 클러스터 멀티노드 (≥3) 필수 | High | _{{}}_ |
| 3 | _{{kube-burner iter 100 → 4h timeout}}_ | KSM-02-04 | 단일노드 testbed 50 권장, 운영 5000 | Medium | _{{}}_ |
| 4 | _{{}}_ | _{{}}_ | _{{}}_ | _{{}}_ | _{{}}_ |
| 5 | _{{}}_ | _{{}}_ | _{{}}_ | _{{}}_ | _{{}}_ |

---

## 4. 운영 적용 권장 설정

### 4.1 helm values 변경 (kube-prometheus-stack)

```yaml
# kube-prometheus-stack values.yaml
prometheus-node-exporter:
  resources:
    requests: { memory: 64Mi, cpu: 100m }
    limits:   { memory: ___Mi, cpu: 500m }    # NE-FREQ 결과 기반

prometheus:
  prometheusSpec:
    replicas: 2                               # PR-HA 결과 기반
    resources:
      requests: { memory: ___, cpu: ___ }
      limits:   { memory: ___, cpu: ___ }     # PR-SCRAPE 결과 기반
    retention: ___                             # 디스크 사용량 기준

kube-state-metrics:
  resources:
    requests: { memory: ___, cpu: ___ }
    limits:   { memory: ___, cpu: ___ }       # KSM-OOM 결과 기반
```

### 4.2 helm values 변경 (fluent-bit)

```yaml
# fluent-bit values.yaml
resources:
  requests: { memory: ___, cpu: ___ }
  limits:   { memory: ___, cpu: ___ }         # FB-OOM 결과 기반

config:
  service: |
    [SERVICE]
        Mem_Buf_Limit  ___MB                  # limit × 0.7
        Storage.path   /var/log/flb-storage/  # hostPath
        Storage.max_chunks_up ___              # FB-BURST 결과 기반
```

### 4.3 OpenSearch 운영 설정

```yaml
# opensearch values.yaml
replicaCount: ___                              # CHAOS-OS-07 결과 기반 (≥ 3)
opensearchJavaOpts: "-Xms___g -Xmx___g"        # OS-08 결과 기반
config:
  opensearch.yml:
    indices.recovery.max_bytes_per_sec: 100mb  # OS-PV 회복 시간 기반
```

---

## 5. 폐쇄망 이전 전 체크리스트

| # | 항목 | 확인 |
|---|------|------|
| 1 | testbed 에서 13개 (또는 15개) 시나리오 모두 PASS | ☐ |
| 2 | 발견된 운영 이슈 모두 helm values 에 반영 | ☐ |
| 3 | loadtest-tools image Nexus push 완료 | ☐ |
| 4 | pause:3.10 image Nexus push 완료 | ☐ |
| 5 | helm chart 의 모든 의존 image Nexus mirror | ☐ |
| 6 | imagePullSecret (인증 필요 시) 생성 | ☐ |
| 7 | OS security plugin 자격증명 → opensearch-creds Secret | ☐ |
| 8 | sed 로 nexus.intranet 주소 일괄 변경 | ☐ |
| 9 | helm values 운영 사양 적용 | ☐ |
| 10 | 운영급 부하 (FLOG_REPLICAS=10, AVALANCHE_REPLICAS=20, KSM_BURNER_ITERATIONS=5000) 로 시나리오 재실행 | ☐ |

---

## 6. 종합 판정 / 결론

### 6.1 종합 판정

| 판정 | 기준 |
|------|------|
| ☐ PASS  | 모든 시나리오 PASS + 발견된 운영 이슈 모두 해결 가능 |
| ☐ WARN | 1~2개 시나리오 SLO 임계 근접 (90~100%) — 운영 적용 가능하나 모니터링 필요 |
| ☐ FAIL | OOMKilled / 인덱스 손상 / SLO 30%+ 초과 — 운영 적용 보류 |

### 6.2 결론 / 운영 적용 권고 (자유 기술)

```
{{ 4일간의 시험 결과 종합 / 발견된 핵심 이슈 / 운영 적용 시 즉시 해야 할 것 / 추가 검증 필요 사항 }}
```

### 6.3 향후 보강 시나리오 제안 (시간 부족으로 skip 한 것)

- ☐ OS-12 refresh_interval 튜닝 비교 (1s vs 30s vs 60s)
- ☐ OS-05 24시간 soak (heap leak 검증)
- ☐ KSM-02 / KSM-03 (scrape time growth, ingest backlog)
- ☐ Alertmanager cluster mode 검증
- ☐ Grafana 다중 동시 쿼리 부하

### 6.4 첨부 파일

- `~/loadtest-results/day1/` ~ `~/loadtest-results/day4/` — 각 Job logs
- Grafana 대시보드 스크린샷 (시나리오별)
- OSB result.json
- k6 summary 출력
- 발견된 이슈에 대한 helm values diff

---

## 부록 A — 결과 빠른 입력 템플릿 (복사용)

각 시나리오 종료 직후 1분 안에 입력하기 위한 minimal 양식:

```
시나리오 ID  : ___
실행 일시    : YYYY-MM-DD HH:MM
조작변수     : ___
측정값       : ___ (가장 중요한 1~2개 metric)
판정         : ☐ PASS / ☐ FAIL
한 줄 비고   : ___
```

이 minimal 양식을 시나리오 별로 시간 순으로 누적 → Day 종료 시 위 §1 의 상세 양식으로 옮김.
