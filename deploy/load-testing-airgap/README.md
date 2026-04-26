# load-testing-airgap

폐쇄망(Air-gap) 환경에서 **시나리오를 선택적으로 실행**할 수 있도록 분리한
부하 테스트 매니페스트와 운영 문서.

기존 `deploy/load-testing/airgap-integration-test.yaml` (단일 파일,
전부 한꺼번에 적용) 의 후속이며, 사내망 테스트에서 발견된 다음 문제를
해결합니다:

- ❌ **선택 실행 불가** — `kubectl apply -f` 한 번에 모든 Job 이 동시에 시작
- ❌ **OOMKilled** — opensearch-benchmark, k6 heavy-search, opensearch-exporter
- ❌ **opensearch-benchmark 비정상 종료** — 메모리 + 진단 로그 부재

## 폴더 구조

```
deploy/load-testing-airgap/
├── README.md                              ← 이 파일
├── 00-prerequisites/                      ← 모든 시나리오의 공통 의존
│   ├── namespaces.yaml
│   └── lt-config.yaml                     ← 중앙 설정 ConfigMap
├── 10-load-generators/                    ← 백그라운드 부하 생성기 (선택 가동)
│   ├── flog-loader.yaml                   ← 합성 로그 (FB)
│   ├── avalanche.yaml                     ← 합성 메트릭 (PR)
│   ├── loggen-spark.yaml                  ← 고-cardinality 로그 (OS-14)
│   └── opensearch-exporter.yaml           ← OS 메트릭 노출
├── 20-scenarios/                          ← 시간 한정 테스트 (선택 실행)
│   ├── OS-01-osb-bulk-ingest/             ← opensearch-benchmark
│   ├── OS-02-k6-heavy-search/             ← 50 VU 검색 부하
│   ├── OS-14-high-cardinality/            ← (loggen-spark 가동만 필요)
│   ├── OS-16-k6-light-search/             ← 6 VU × 30분
│   ├── FB-flog-pipeline/                  ← (flog 가동만 필요)
│   ├── PR-01-02-05-avalanche/             ← (avalanche 가동만 필요)
│   ├── PR-03-04-k6-promql/                ← PromQL 쿼리 부하
│   ├── NE-02-hey-node-exporter/           ← node-exporter HTTP 부하
│   └── KSM-02-04-kube-burner/             ← pod density
└── docs/
    ├── 01-test-plan.md                    ← 시나리오별 실행 절차/기대치 (표)
    ├── 02-troubleshooting.md              ← OOM, OSB 실패 등 해결법
    └── 03-result-verification.md          ← Grafana, kubectl, 로그 확인법
```

## 빠른 시작

```bash
# 1) 사전 준비 (1회)
kubectl apply -f deploy/load-testing-airgap/00-prerequisites/

# 2) 백그라운드 부하 발생기 (필요한 것만 가동)
kubectl apply -f deploy/load-testing-airgap/10-load-generators/flog-loader.yaml
kubectl apply -f deploy/load-testing-airgap/10-load-generators/avalanche.yaml

# 3) 특정 시나리오 실행
kubectl apply -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/

# 4) 결과 확인 (시나리오 README 의 "결과 확인" 섹션 또는 docs/03-...)
kubectl -n load-test logs job/opensearch-benchmark -f

# 5) 시나리오만 정리 (다른 시나리오/생성기는 영향 없음)
kubectl delete -f deploy/load-testing-airgap/20-scenarios/OS-01-osb-bulk-ingest/
```

## Nexus 주소 변경

기본 이미지 경로: `nexus.intranet:8082/loadtest/loadtest-tools:0.1.1`

```bash
sed -i 's|nexus.intranet:8082/loadtest|<your-host:port>/<project>|g' \
  deploy/load-testing-airgap/00-prerequisites/lt-config.yaml \
  deploy/load-testing-airgap/10-load-generators/*.yaml \
  deploy/load-testing-airgap/20-scenarios/*/*.yaml
```

## 운영 시뮬레이션 (운영급 부하)

`00-prerequisites/lt-config.yaml` 에서 `# 운영:` 주석값으로 교체 후
대응 시나리오 재시작.

## 주요 변경 (이전 single-yaml 대비)

| 항목 | 이전 | 변경 |
|------|------|------|
| opensearch-benchmark memory limit | 1.5Gi | **4Gi** |
| opensearch-benchmark 사전 진단 | 없음 | OS 연결, workload 경로, OS 응답 print |
| k6-opensearch-search memory | 512Mi | **1Gi** |
| k6-promql memory | 512Mi | **1Gi** |
| opensearch-exporter memory | 128Mi | **512Mi** (실제 cluster: 인덱스 多) |
| avalanche memory | 256Mi | **512Mi** |
| kube-burner memory | 512Mi | **768Mi** |
| 시나리오 선택 실행 | 불가 (전부 한꺼번에) | **가능** (폴더 단위) |
| 시나리오 별 README | 없음 | 모든 시나리오 |
| 통합 테스트 계획서 | 없음 (산발 docs) | docs/01-test-plan.md (표) |
| 트러블슈팅 가이드 | 없음 | docs/02-troubleshooting.md |

## 시나리오 ↔ 의존성 매트릭스

| 시나리오 | 사전: 부하 발생기 | 사전: ConfigMap | RBAC |
|----------|-------------------|-----------------|------|
| OS-01 (OSB bulk-ingest)    | — | lt-config | — |
| OS-02 (k6 heavy search)    | flog 또는 OSB 로 인덱스 생성 후 | lt-config + script-cm | — |
| OS-14 (high-cardinality)   | loggen-spark | lt-config | — |
| OS-16 (k6 light search)    | flog + loggen-spark 가동 중 | lt-config + script-cm | — |
| FB (fluent-bit pipeline)   | flog | lt-config | (사전 fluent-bit DaemonSet 필요) |
| PR-01/02/05 (avalanche)    | avalanche | lt-config | — |
| PR-03/04 (k6 PromQL)       | (avalanche 권장) | lt-config + script-cm | — |
| NE-02 (hey)                | — | lt-config | — |
| KSM-02/03/04 (kube-burner) | — | lt-config + burner-cm | cluster-admin |

## 관련 문서

- [docs/01-test-plan.md](docs/01-test-plan.md) — 시나리오별 실행 절차 + 기대 결과 (표)
- [docs/02-troubleshooting.md](docs/02-troubleshooting.md) — OOM, OSB 실패, ImagePullBackOff
- [docs/03-result-verification.md](docs/03-result-verification.md) — Grafana / kubectl / API 검증
- [../../docs/load-testing/15-nexus-push-quick.md](../../docs/load-testing/15-nexus-push-quick.md) — 이미지 업로드
- [../../docs/load-testing/08-scenario-catalog.md](../../docs/load-testing/08-scenario-catalog.md) — 전체 시나리오 카탈로그
