# 모니터링 모듈 성능 테스트 시나리오 명세서

`docs/load-testing/list.md` 의 13개 항목을 기반으로 작성한 시나리오 명세서.
각 시나리오를 **시나리오 ID / 주제 / 유형 / 목적 / 수행방법 (절차 + 명령) /
설정값 구성 방법 / 비고** 7가지 관점으로 정리.

---

## 0. list.md 평가 + 보강 사항

### 0.1 list.md 충족도

| 영역 | list 항목 수 | 합리성 |
|------|---------------|---------|
| OpenSearch | 6 | ✅ 충분 — 처리량/검색/burst/scaling/장애 2종 모두 포함 |
| Fluent-bit | 3 | ⚠ ceiling/운영/spike 만 → drop/buffer 시나리오는 "운영 성능" 에 포함 가능 |
| Prometheus | 2 | ⚠ HA + scrape — query 부하 (PromQL) 추가 권장 |
| Node-exporter | 2 | ✅ scrape 비용/빈도 핵심 |
| **kube-state-metrics** | **0** | **❌ 누락** — concept 에 있던 컴포넌트, 반드시 1~2개 추가 권장 |

### 0.2 4일 일정 적합성

13개 시나리오 × 평균 1~2시간 = **20~30시간** → 4일 (32시간) 안에 가능. 단:
- OS 시나리오 (6개) 는 인덱스 셋업 + 워크로드 다운로드 시간 누적 → Day 1 OS 집중 권장
- FB log burst 는 spark/airflow wave 와 본질 동일 → 통합 가능 (1개 시나리오)
- PR HA 는 helm replicaCount 변경 + restart 만으로 30분 가능

### 0.3 권장 보강

| # | ID | 시나리오 | 추가 이유 | 예상 소요 |
|---|----|----------|-----------|-----------|
| A | KSM-OOM | kube-state-metrics OOM 한계 | concept 명시. user list 누락 | 30m |
| B | PR-QUERY | PromQL 쿼리 부하 | scrape 만으로는 query path 검증 불가 | 30m |

위 2개를 더하면 **15개**. 4일 일정 여전히 가능. 시간 부족 시 KSM/PR-QUERY skip OK.

### 0.4 시나리오 ID 와 list 항목 매핑

| list 항목 | 시나리오 ID | 매핑 |
|-----------|-------------|------|
| OS bulk indexing 처리량/지연 | OS-01 | 기존 |
| OS 인덱싱 + 검색 동시 | OS-16 | 기존 |
| OS spark/airflow 동시 wave | OS-09 | 기존 (catalog) |
| OS 190대 sustainable TPS | OS-08 | 기존 (catalog) |
| OS node 장애 | CHAOS-OS-07 | 기존 |
| OS **PV 장애** | **OS-PV** | **NEW** |
| FB 단일 pod throughput ceiling | FB-OOM | 기존 (FB-OOM-tuning) |
| FB 190대 클러스터 운영 성능 | FB-PROD | 기존 (FB-flog-pipeline 확장) |
| FB log burst (spike) | **FB-BURST** | **NEW (분리 강화)** |
| PR HA | **PR-HA** | **NEW** |
| PR scrape 부하 | PR-SCRAPE | 기존 (PR-01-02-05) |
| NE scrape 비용 | NE-COST | 기존 (NE-02) |
| NE 고빈도 scrape | NE-FREQ | 기존 (NE-OOM-tuning 변형) |
| **KSM OOM 한계 (보강)** | **KSM-OOM** | **NEW** |
| **PR query 부하 (보강)** | **PR-QUERY** | **NEW (PR-03-04)** |

총 **15개 시나리오**.

---

## 1. 시나리오 한눈에 보기 (요약 표)

| # | ID | 시나리오 | 유형 | 우선순위 | 소요 | Day |
|---|----|----------|------|----------|------|-----|
| 1 | OS-01 | OS bulk indexing | Load | High | 30~60m | 1 |
| 2 | OS-08 | OS 190대 sustainable TPS | Load | High | 60m | 1 |
| 3 | OS-09 | OS spark/airflow wave | Spike | High | 30m | 1 |
| 4 | OS-16 | OS 인덱싱+검색 동시 | Integration | **Critical** | 30m | 1 |
| 5 | CHAOS-OS-07 | OS node 장애 | Chaos | High | 30m | 2 |
| 6 | OS-PV | OS PV 장애 | Chaos | Medium | 60m | 2 |
| 7 | FB-OOM | FB 단일 pod ceiling | Tuning | High | 20m | 2 |
| 8 | FB-PROD | FB 190대 운영 | Load | High | 60m | 2 |
| 9 | FB-BURST | FB log burst spike | Spike | Medium | 30m | 3 |
| 10 | PR-HA | PR HA | Chaos | High | 30m | 3 |
| 11 | PR-SCRAPE | PR scrape 부하 | Load | High | 30m | 3 |
| 12 | PR-QUERY | PR query 부하 (보강) | Load | Medium | 30m | 3 |
| 13 | NE-COST | NE scrape 비용 | Load | High | 20m | 4 |
| 14 | NE-FREQ | NE 고빈도 scrape | Stress | High | 20m | 4 |
| 15 | KSM-OOM | KSM OOM 한계 (보강) | Tuning | Medium | 30m | 4 |

---

## 2. OpenSearch 시나리오 명세

### 2.1 OS-01 — Bulk Indexing 처리량/지연

| 항목 | 내용 |
|------|------|
| **주제** | opensearch-benchmark 표준 워크로드 (geonames) 로 인덱싱 처리량과 지연 측정 |
| **유형** | Load |
| **목적** | OS 클러스터의 baseline indexing 성능 + 폐쇄망 도구 동작 검증. 다른 시나리오의 비교 기준선이 되는 baseline. |
| **수행방법** | ① pre-flight 스크립트가 OS 연결성/workload/디스크 검증 → ② OSB execute-test 실행 → ③ result.json 출력 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/` <br> `kubectl -n load-test logs -f job/opensearch-benchmark` |
| **설정값** | `OSB_WORKLOAD=geonames`, `OSB_TEST_MODE=true` (1k docs) 또는 `false` (전체 corpus, PVC 필요) <br> `OSB_BULK_SIZE=5000`, `OSB_CLIENTS=16` |
| **워크로드 사이즈** | test-mode: 1k docs (1~2분) / full-mode: geonames 11.4M docs (~15분) |
| **비고** | 다른 시나리오와 **동시 실행 금지** (단독). single-node 에서 hang 시 모든 인덱스 replica=0 적용 필요 |

### 2.2 OS-08 — 190대 클러스터 Sustainable TPS

| 항목 | 내용 |
|------|------|
| **주제** | 190대 cluster 의 매일 정상 부하를 장시간 흡수 가능한지 |
| **유형** | Load (sustained) |
| **목적** | 운영 capacity planning 의 1차 근거. 매일 들어오는 정상 부하 흡수 능력 측정 |
| **수행방법** | ① flog × 30 replica 가동 → ② OSB `append` 1시간 sustained → ③ TPS / segment / heap 안정성 확인 |
| **명령** | `kubectl scale deploy/flog-loader -n load-test --replicas=30` <br> `kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/` (test-mode false 로 변경) <br> 1시간 모니터링 |
| **설정값** | flog `replicas=30`, `FLOG_DELAY=100us` <br> OSB `OSB_TEST_MODE=false`, target-throughput 30k docs/s <br> 인덱스 `refresh_interval=1s`, `number_of_shards=3`, `number_of_replicas=1` |
| **워크로드 사이즈** | 30k docs/s × 3,600s = **108M docs** 인덱싱 (≈ 200 GB) |
| **비고** | 1시간 sustained 가 핵심 — 짧으면 segment/GC 누적 문제 못 봄. 검색 부하 = 없어야 (단독 측정) |

### 2.3 OS-09 — Spark/Airflow Startup Wave (Spike)

| 항목 | 내용 |
|------|------|
| **주제** | 200대 가까운 Spark/Airflow worker 가 일제히 시작되는 시점의 burst 부하 |
| **유형** | Spike |
| **목적** | burst 흡수 + fluent-bit back-pressure 검증. 운영 사고 1순위 시점 (배치 시작) |
| **수행방법** | ① OS-08 baseline 가동 중 (sustained) → ② flog `replicas: 0 → 30` 일시 가동 (15분) → ③ FB filesystem buffer / OS reject 모니터링 |
| **명령** | `kubectl scale deploy/flog-loader -n load-test --replicas=0` <br> 15분 후: `kubectl scale deploy/flog-loader -n load-test --replicas=30` <br> Grafana FB / OS 패널 watch |
| **설정값** | flog `replicas: 0 → 30` 변화 (즉시 ramp 또는 1분 ramp) <br> fluent-bit `Mem_Buf_Limit=64MB`, `Storage.path` hostPath 필수 <br> OS 인덱스 reject queue 측정 |
| **워크로드 사이즈** | 15분 burst = 30 replicas × 10k lines/s × 900s ≈ **27M lines** burst |
| **비고** | OS-08 의 baseline 위에 burst 추가하는 게 실제 운영 패턴. 단독 실행은 의미 약함 |

### 2.4 OS-16 — 인덱싱 + 검색 동시 (Integration, ★ 핵심)

| 항목 | 내용 |
|------|------|
| **주제** | heavy ingest 진행 중 6개 서비스 팀이 light search 를 동시에 수행 (운영 패턴) |
| **유형** | Integration |
| **목적** | ★ 운영 SLO 검증 — 6 팀 동시 검색 시 search p95 < 5,000 ms 유지 가능한지 |
| **수행방법** | ① flog + loggen-spark + (선택) OSB heavy ingest 가동 → ② 6 VU × 30분 light search (range/bool/match) → ③ k6 thresholds 통과 확인 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/10-load-generators/` <br> `kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-16-k6-light-search/` <br> `kubectl -n load-test logs -f job/k6-opensearch-light-search` |
| **설정값** | k6 `LIGHT_SEARCH_VUS=6`, `LIGHT_SEARCH_DURATION=30m` <br> 쿼리 패턴: `range[1h]`, `bool[range+match]`, `match{level}` <br> 사전: flog × 3, loggen-spark × 3 가동 중 |
| **워크로드 사이즈** | 6 VU × 30m × (1 query / 5~15s) ≈ **720~2,160 검색 요청** + 100k+ lines/s 동시 ingest |
| **비고** | ★ 핵심 시나리오 — 운영 적용 가능 여부의 1차 판단 기준. 단독 실행 무의미 |

### 2.5 CHAOS-OS-07 — Node 장애 회복

| 항목 | 내용 |
|------|------|
| **주제** | OS data/master 노드 강제 종료 시 cluster red→yellow→green 회복 시간 |
| **유형** | Chaos |
| **목적** | HA 검증 — 운영 노드 장애 시 데이터 손실 없이 회복하는지, 회복 시간이 SLO (10분) 내인지 |
| **수행방법** | ① pre-kill green 확인 → ② `kubectl delete pod` data 노드 1개 → ③ 5초 간격 `_cluster/health` 폴링 → ④ red/yellow/green 진입 시간 출력 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/CHAOS-OS-07-node-failure/` <br> `kubectl -n load-test logs -f job/chaos-os-07-node-failure` |
| **설정값** | `TARGET_POD_LABEL`: data 또는 master role <br> `POST_KILL_WAIT=600s` (10분 한도) <br> 사전: 모든 인덱스 `number_of_replicas ≥ 1` |
| **워크로드 사이즈** | 부하 진행 중 (50% baseline TPS) chaos. 무부하 chaos 는 의미 약함 |
| **비고** | testbed (single node) = 의도된 FAIL. 멀티노드에서 본질적 의미 |

### 2.6 OS-PV — PV 장애 회복 (NEW)

| 항목 | 내용 |
|------|------|
| **주제** | OS data 노드의 PV (PersistentVolume) 장애 — 디스크 corrupt / readonly / detach |
| **유형** | Chaos |
| **목적** | 디스크 단위 장애 회복 — replica 가 보존되는지, recovery 가 정상 트리거되는지 |
| **수행방법** | ① PV 의 underlying storage 강제 readonly 또는 PV detach → ② OS pod restart → ③ green 회복 + 데이터 정합성 확인 |
| **명령** | (csi-driver 마운트 포인트 강제 readonly) <br> `kubectl patch pv <pv-name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'` <br> `kubectl -n monitoring delete pod -l app.kubernetes.io/name=opensearch` <br> `_cluster/health` polling |
| **설정값** | OS `repository-fs` 또는 snapshot 사전 구성 권장 <br> 인덱스 `number_of_replicas ≥ 1` 필수 <br> recovery throttle: `indices.recovery.max_bytes_per_sec=100mb` |
| **워크로드 사이즈** | PV detach 시 affected shards = primary 수 (3~5개 per index) |
| **비고** | testbed = NFS / hostPath 기반이면 PV detach 어려움 — 본 시나리오는 운영 환경에서 검증 권장. 사전 백업 / snapshot 필수 |

---

## 3. Fluent-bit 시나리오 명세

### 3.1 FB-OOM — 단일 Pod Throughput Ceiling

| 항목 | 내용 |
|------|------|
| **주제** | 단일 fluent-bit pod 가 흡수 가능한 최대 lines/s 와 그 시점의 메모리 사용량 |
| **유형** | Tuning (capacity discovery) |
| **목적** | 운영 환경 fluent-bit DaemonSet limit 결정 + OOMKilled 한계 발견 |
| **수행방법** | ① flog 단계별 ramp (3→10→30→60 replicas) → ② 각 stage 에서 fluent-bit pod RSS 측정 → ③ peak / OOM 시점 기록 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/FB-OOM-tuning/` <br> `kubectl -n load-test logs -f job/fb-oom-tuning` <br> (병렬) `watch -n 1 'kubectl -n monitoring top pod -l app.kubernetes.io/name=fluent-bit'` |
| **설정값** | flog stages: 1 / 3 / 10 / 30 replicas <br> 각 stage 5분 sustained <br> fluent-bit `Mem_Buf_Limit` (현재값 기록) |
| **워크로드 사이즈** | peak stage = 30 × 10k lines/s = **300k lines/s** (90% 운영급) |
| **비고** | 결과 = "load X 에서 RSS Y MB" 곡선 → 운영 limit = peak RSS × 1.5 |

### 3.2 FB-PROD — 190대 클러스터 운영 성능

| 항목 | 내용 |
|------|------|
| **주제** | 190대 worker 의 정상 운영 부하를 fluent-bit DaemonSet 이 1시간 안정 처리 |
| **유형** | Load (sustained) |
| **목적** | 운영급 부하에서 input vs output rate 일치 (drop = 0), DaemonSet 안정성 |
| **수행방법** | ① flog × 10 replicas (운영급) sustained 1시간 → ② fluent-bit input/output rate / drop / buffer 사용량 모니터링 |
| **명령** | `kubectl scale deploy/flog-loader -n load-test --replicas=10` <br> Grafana `lt-fluent-bit` 대시보드 watch <br> `curl ${PROMETHEUS_URL}/api/v1/query?query=sum(rate(fluentbit_output_proc_records_total[1m]))` |
| **설정값** | flog `replicas=10`, `FLOG_DELAY=100us` → 100k lines/s 발생 <br> fluent-bit limit 운영값 (FB-OOM 결과 기반) <br> filesystem buffer hostPath 필수 |
| **워크로드 사이즈** | 100k lines/s × 3600s = **360M lines / 1시간** (≈ 700 GB) |
| **비고** | drop > 0 시 mem_buf_limit / Storage 설정 재튜닝 필요 |

### 3.3 FB-BURST — Log Burst Spike (NEW 분리)

| 항목 | 내용 |
|------|------|
| **주제** | 짧은 시간 (10~30초) 동안 평소 5~10배 burst 부하 |
| **유형** | Spike |
| **목적** | filesystem buffer 흡수성 검증, OS reject 발생 시 fluent-bit 의 retry/back-pressure 동작 |
| **수행방법** | ① flog × 5 replicas baseline → ② 30초 동안 flog × 30 replicas burst → ③ buffer 사용량 / drop 측정 |
| **명령** | `kubectl scale deploy/flog-loader --replicas=5 -n load-test` (baseline) <br> 5분 후: `kubectl scale deploy/flog-loader --replicas=30 -n load-test` (burst 30초) <br> 다시: `kubectl scale deploy/flog-loader --replicas=5 -n load-test` |
| **설정값** | flog `replicas: 5 → 30 → 5` (30초 spike) <br> fluent-bit `Storage.max_chunks_up=512` (burst 흡수) <br> OS reject queue 사전 측정 |
| **워크로드 사이즈** | spike 30초 = 30 × 10k × 30 = **9M lines burst** |
| **비고** | OS-09 와 본질 비슷 — OS-09 가 OS 측 검증, FB-BURST 가 FB 측 검증으로 분리 |

---

## 4. Prometheus 시나리오 명세

### 4.1 PR-HA — High Availability (NEW)

| 항목 | 내용 |
|------|------|
| **주제** | Prometheus replica 1개 장애 시 alerting/scrape 연속성 |
| **유형** | Chaos |
| **목적** | HA 검증 — replica 죽어도 alerting 끊기지 않고, 다른 replica 가 데이터 보존 |
| **수행방법** | ① helm `replicaCount=2` 적용 (이미 2 면 skip) → ② replica 1개 강제 종료 → ③ alerting 도착 / target up 연속성 확인 |
| **명령** | `kubectl -n monitoring patch prometheus kps-prometheus -p '{"spec":{"replicas":2}}' --type=merge` <br> `kubectl -n monitoring delete pod prometheus-kps-prometheus-0 --grace-period=0 --force` <br> `curl ${ALERTMANAGER_URL}/api/v2/alerts` (alerts 가 끊기지 않음 확인) |
| **설정값** | `prometheus.spec.replicas=2` <br> Alertmanager cluster mode 활성 <br> ServiceMonitor selector 동일 (양쪽 replica 가 같은 target scrape) |
| **워크로드 사이즈** | replica 1개 60초 동안 다운 → 다른 replica 가 처리 |
| **비고** | testbed = single instance 라 우선 replica=2 변경 필요. 변경 후 30분 정착 대기 |

### 4.2 PR-SCRAPE — Scrape 부하 (active series 적재)

| 항목 | 내용 |
|------|------|
| **주제** | 합성 /metrics endpoint 가 노출하는 active series 를 prometheus 가 scrape/저장/쿼리 |
| **유형** | Load |
| **목적** | active series 임계점 발견 — heap 폭증 / scrape budget 초과 발생 시점 |
| **수행방법** | ① avalanche 단계별 ramp (200×200×2 → 500×500×20) → ② prometheus heap / scrape duration 모니터링 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/10-load-generators/avalanche.yaml` <br> 5분 후 패널 확인 <br> `kubectl scale deploy/avalanche -n load-test --replicas=20` (운영급) |
| **설정값** | avalanche: `gauge-metric-count=200/500`, `series-count=200/500`, `replicas=2/20` <br> prometheus heap limit 4Gi 이상 권장 (운영급) |
| **워크로드 사이즈** | 기본: 200×200×2 = **80k active series** <br> 운영급: 500×500×20 = **5M active series** |
| **비고** | series 5M 이상은 prometheus WAL replay 시 OOM 위험 — 단계 ramp 필수 |

### 4.3 PR-QUERY — PromQL 쿼리 부하 (보강)

| 항목 | 내용 |
|------|------|
| **주제** | 운영 Grafana 대시보드 쿼리 패턴 (rate, topk, histogram_quantile) 동시 실행 |
| **유형** | Load |
| **목적** | query path 검증 — query thread saturation / engine eval timeout |
| **수행방법** | ① avalanche scrape 정착 (5분) → ② k6 PromQL random query 5분 (20 VU) → ③ thresholds 확인 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/PR-03-04-k6-promql/` <br> `kubectl -n load-test logs -f job/k6-promql` |
| **설정값** | k6 `K6_PROMQL_VUS=20`, `K6_PROMQL_DURATION=5m` <br> 7가지 쿼리 라운드 로빈 <br> sleep 0.1s/req → ~ 200 req/s |
| **워크로드 사이즈** | 20 VU × 300s × 10 req/s = **60,000 PromQL queries** |
| **비고** | scrape 부하 (PR-SCRAPE) 와 동시 실행 시 운영 패턴 재현 |

---

## 5. Node-exporter 시나리오 명세

### 5.1 NE-COST — Scrape 비용

| 항목 | 내용 |
|------|------|
| **주제** | 정상 scrape 1회당 node-exporter 가 소비하는 CPU / 메모리 / 응답 시간 |
| **유형** | Load |
| **목적** | scrape interval 적정값 결정. interval 낮추면 부하 비례 증가 |
| **수행방법** | ① hey 정상 RPS (500) × 2분 → ② node-exporter CPU / RSS / 응답 시간 측정 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/NE-02-hey-node-exporter/` <br> `kubectl -n load-test logs -f job/hey-node-exporter` |
| **설정값** | `HEY_CONCURRENCY=10`, `HEY_RPS_PER_WORKER=50`, `HEY_DURATION=2m` <br> → 500 RPS (정상 scrape × 100 노드 / 5초) 시뮬레이션 |
| **워크로드 사이즈** | 500 RPS × 120s = **60,000 requests** |
| **비고** | testbed 의 NE limit (32Mi) 부족 시 즉시 saturation. 측정 전 limit ≥ 256Mi 확인 |

### 5.2 NE-FREQ — 고빈도 Scrape

| 항목 | 내용 |
|------|------|
| **주제** | 정상보다 5~20배 높은 RPS 에서 node-exporter 의 한계 |
| **유형** | Stress |
| **목적** | 고빈도 scrape (잘못된 외부 monitor 동시 scrape) 사고 시뮬레이션 + OOMKilled 한계 발견 |
| **수행방법** | ① RPS 4단계 ramp (500/2,500/5,000/10,000) → ② 각 stage RSS 기록 → ③ OOMKilled 발생 stage 식별 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/NE-OOM-tuning/` <br> `kubectl -n load-test logs -f job/ne-oom-tuning` |
| **설정값** | hey stages: `concurrency × rps = 10×50 / 50×50 / 100×50 / 200×50` <br> stage 60s sustained, 다음 stage 전 10s 회복 |
| **워크로드 사이즈** | 4 stages × 60s. peak = 10,000 RPS × 60s = **600k requests** |
| **비고** | 결과 = "RPS X 에서 RSS Y MB" 곡선. RSS=0 stage 가 OOMKilled 시점 |

---

## 6. Kube-state-metrics 시나리오 명세 (보강)

### 6.1 KSM-OOM — Kube-state-metrics OOM 한계 (보강)

| 항목 | 내용 |
|------|------|
| **주제** | K8s 객체 수가 늘어남에 따른 KSM 메모리 사용량 / scrape duration |
| **유형** | Tuning |
| **목적** | KSM limit 결정 + scrape budget 초과 시점 발견 |
| **수행방법** | ① kube-burner 50 iter × (3 pod + 3 cm + 3 svc) = 450 객체 → ② 30초 간격 KSM RSS / scrape_duration 기록 |
| **명령** | `kubectl apply -f deploy/load-testing-airgap/20-scenarios/KSM-OOM-tuning/` <br> `kubectl -n load-test logs -f job/ksm-oom-tuning` |
| **설정값** | kube-burner `jobIterations=50` (testbed) / `5000` (운영) <br> 객체 종류: pod/configmap/service 각 3개 per iter |
| **워크로드 사이즈** | testbed: 450 객체 / 운영급: 45,000 객체 |
| **비고** | concept 명시이지만 user list 누락 — 보강. KSM scrape duration > 5s 면 prometheus scrape_timeout 위험 |

---

## 7. 종합 표 — 컴포넌트별 SLO

| 컴포넌트 | 핵심 SLO | 위반 시 운영 영향 |
|----------|----------|-------------------|
| OpenSearch indexing | TPS ≥ 30k docs/s, reject < 0.1% | 로그 누락 |
| OpenSearch search | p95 < 5s (운영 패턴) | 대시보드 timeout |
| OpenSearch availability | green 회복 < 10분 | 인덱스 unavailable |
| Fluent-bit | input = output rate, drop = 0 | 로그 누락 |
| Prometheus scrape | scrape_duration p95 < 0.5s | 메트릭 누락 |
| Prometheus query | p95 < 2s | Grafana 느림 |
| Prometheus HA | replica 1개 장애 시 alerting 끊김 < 60s | 알람 누락 |
| Node-exporter | 2,500 RPS 흡수, OOMKilled = 0 | 노드 메트릭 누락 |
| KSM | scrape_duration < 5s | K8s 객체 메트릭 누락 |

---

## 8. 다음 문서

- [21-test-plan-4day.md](21-test-plan-4day.md) — 4일 step-by-step 핸즈온 계획
- [22-test-result-form.md](22-test-result-form.md) — 결과서 양식 / 보고 양식
