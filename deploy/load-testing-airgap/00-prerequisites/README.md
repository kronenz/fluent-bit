# 00-prerequisites

모든 시나리오가 의존하는 공통 객체.

## 적용

```bash
kubectl apply -f deploy/load-testing-airgap/00-prerequisites/
# namespace/monitoring created
# namespace/load-test created
# configmap/lt-config created
```

## 객체

| 파일 | 객체 | 설명 |
|------|------|------|
| `namespaces.yaml` | Namespace × 2 | `monitoring`, `load-test` |
| `lt-config.yaml`  | ConfigMap     | 모든 테스트가 envFrom 으로 참조하는 튜닝 변수 |

## 변수 카테고리 (lt-config)

| 카테고리 | 키 | 변경 시 영향 |
|---------|----|------|
| 엔드포인트 | `*_URL`, `*_SVC` | 모든 시나리오 |
| 인증     | `OS_BASIC_AUTH_USER/PASS` | OS-01, OS-02, OS-16 |
| flog     | `FLOG_*` | FB, OS-* (간접) |
| avalanche| `AVALANCHE_*` | PR-01/02/05 |
| k6       | `K6_*` | OS-02, OS-16, PR-03/04 |
| kube-burner | `KSM_BURNER_*` | KSM-02/03/04 |
| hey      | `HEY_*` | NE-02 |
| OSB      | `OSB_*` | OS-01 |

## 변경 후 적용 순서

```bash
# ConfigMap 만 변경
kubectl apply -f deploy/load-testing-airgap/00-prerequisites/lt-config.yaml

# 변경된 변수를 사용하는 Deployment 재시작
kubectl -n load-test rollout restart deployment/<name>

# Job 의 경우 삭제 후 재생성 (envFrom 은 Job 시작 시점에만 lock)
kubectl -n load-test delete job <name>
kubectl apply -f deploy/load-testing-airgap/20-scenarios/<scenario>/
```
