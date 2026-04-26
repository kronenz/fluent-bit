# CHAOS-FB-restart — fluent-bit DaemonSet 재시작 시 offset 보존 검증

fluent-bit pod 가 OOMKilled 되거나 재배포되었을 때:
- ✅ 이미 읽어 보낸 로그를 다시 보내지 말 것 (중복 ingest)
- ✅ 미수집 로그를 누락하지 말 것 (ingest gap)

위 두 가지 모두 만족하려면 **offset DB 가 hostPath 또는 PVC 에 영구 저장**
되어야 합니다. 본 시나리오는 그 보존성을 검증.

## 사전 조건

| 항목 | 명령 | 정상 |
|------|------|------|
| flog Deployment 가동 | `kubectl -n load-test get deploy/flog-loader` | ≥ 1 replica |
| fluent-bit DaemonSet | `kubectl -n monitoring get ds -l app.kubernetes.io/name=fluent-bit` | DESIRED=NODES |
| fluent-bit storage path 영구 | `kubectl -n monitoring get ds fluent-bit-... -o yaml \| grep -A3 storage` | hostPath 또는 PVC |
| OS 인덱스 logs-fb-* 존재 | `curl -u admin:admin $OS/_cat/indices/logs-fb-*` | exists |

## 실행

```bash
kubectl apply -f deploy/load-testing-airgap/20-scenarios/CHAOS-FB-restart/
kubectl -n load-test logs -f job/chaos-fb-restart
```

## 절차 (자동)

1. **T0 안정화 60s** — pre-restart doc count C0
2. **fluent-bit rollout restart**
3. **회복 대기** (rollout status timeout 120s)
4. **T1 안정화 60s** — post-restart doc count C1
5. **결과 판정**: Δ = C1 - C0
   - PASS: Δ ≥ expected (60s × 1k/s = 60k docs)
   - FAIL: Δ < expected → gap 의심

## 기대 결과

| 지표 | 임계 | 의미 |
|------|------|------|
| pod restart 시간 | < 60s | rollout 정상 |
| Δ count | ≥ 60,000 | ingest 끊김 없음 |
| 중복 doc 발생 | 0 (검증은 별도 — `_id` unique) | offset 보존 |

## 실패 시 디버깅

```bash
# fluent-bit storage 설정 확인
kubectl -n monitoring get cm -l app.kubernetes.io/name=fluent-bit -o yaml | grep -A5 'storage'

# 실제 hostPath / PVC 마운트
kubectl -n monitoring describe ds -l app.kubernetes.io/name=fluent-bit | grep -A3 'Mounts\|Volumes'

# offset DB 파일 확인 (호스트 노드 진입 후)
ssh <node>
ls -la /var/log/fluent-bit-storage/
```

| 증상 | 원인 | 해결 |
|------|------|------|
| restart 후 즉시 재전송 (중복) | offset DB 가 emptyDir / 컨테이너 내부 경로 | hostPath / PVC 로 변경 |
| restart 후 ingest 재개 안 됨 | `Storage.path` 권한 문제 | hostPath 권한 0755 + uid 매칭 |
| Δ << expected | rollout timeout 또는 OOMKilled 반복 | memory limit 상향 (FB-OOM-tuning 시나리오 참조) |

## 변형 시나리오

| 변형 | 명령 |
|------|------|
| 단일 pod 만 kill | `kubectl -n monitoring delete pod -l app.kubernetes.io/name=fluent-bit --field-selector=spec.nodeName=<node>` |
| 강제 종료 (SIGKILL) | `kubectl delete pod ... --force --grace-period=0` |
| OOMKilled 재현 | memory limit 을 일시 낮춤 후 부하 증가 |

## 정리

```bash
kubectl delete -f deploy/load-testing-airgap/20-scenarios/CHAOS-FB-restart/
```
