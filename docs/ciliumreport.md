근거로 쓸 수 있는 이슈/PR 링크를 검증해서 정리하겠습니다. 먼저 핵심 이슈 #39429를 확인합니다.

API rate limit에 걸렸으니 웹 검색으로 각 링크를 검증하겠습니다.

upstream PR 번호까지 특정하기 위해 커밋 이력에서 backport PR을 확인하겠습니다.

모든 근거가 검증됐습니다. 특히 중요한 사실 하나가 추가로 확인됐습니다: **이 버그는 1.18.0에서 유입된 회귀(regression)** 입니다. 근거 링크를 정리합니다.

## 핵심 근거 — writeHeaderFile lock 누수 (1.18.0~1.18.5 영향, 1.18.4 해당)

**버그 유입 PR (v1.18.0에 포함):**
- https://github.com/cilium/cilium/pull/39429 — "endpoint: execute Endpoint.writeHeaderFile under lockAlive" (@ti-mo). v1.18.0 CHANGELOG에 명시. 이 PR이 writeHeaderFile을 lockAlive 아래로 옮기면서 에러 경로에 unlock 누락을 만들었습니다.

**수정 PR (v1.18.6에 포함 — 1.18.4는 미포함):**
- Upstream: https://github.com/cilium/cilium/pull/43242 — "Fixes a deadlock that was causing endpoint to be stuck without progressing with any updates" (@marseel). v1.18.6 CHANGELOG의 Bugfixes 항목에 기재
- v1.18 Backport: https://github.com/cilium/cilium/pull/43290
- 수정 커밋(v1.18 브랜치): https://github.com/cilium/cilium/commit/1583627c15 — 커밋 메시지에 "In cases when writeHeaderfile fails with any error, we were not releasing endpoint lock. Fixes: #39429" 명시, diff는 `e.unlock()` 한 줄 추가
- 릴리스 노트: https://github.com/cilium/cilium/releases/tag/v1.18.6

## v1.18.5에 포함된 관련 deadlock 수정들 (역시 1.18.4 미포함)

v1.18.5 CHANGELOG에서 확인된 항목:
- **waiting-to-regenerate 고착**: upstream https://github.com/cilium/cilium/pull/42856, backport https://github.com/cilium/cilium/pull/42948 — "Fix issue where endpoints got stuck in waiting-to-regenerate"
- **Selector Policy deadlock**: upstream https://github.com/cilium/cilium/pull/42306, backport https://github.com/cilium/cilium/pull/42864
- **identity 변경 시 policy deadlock**: upstream https://github.com/cilium/cilium/pull/42420, backport https://github.com/cilium/cilium/pull/42617
- 릴리스 노트: https://github.com/cilium/cilium/releases/tag/v1.18.5

## 동일 증상 참고 이슈 (근거 보강용)

- https://github.com/cilium/cilium/issues/39846 — "endpoint regeneration deadlock": `cilium endpoint list`가 "Cilium API client timeout exceeded"로 실패하고, 모든 goroutine이 동일 Endpoint의 RWMutex에서 대기하는 스택 분석 포함 [GitHub](https://github.com/cilium/cilium/issues/39846) . 지금 증상과 동일한 패턴의 대표 사례
- https://github.com/cilium/cilium/issues/37790 — "sync-address-identity-mapping" 실패 시 Endpoint mutex를 unlock하지 않아 모든 endpoint 작업이 영구 hang, agent가 복구 불가 상태가 되는 [GitHub](https://github.com/cilium/cilium/issues/37790) 같은 계열(lock 누수) 버그. 1.18.4엔 수정돼 있음을 코드로 확인했으나, 이 클래스의 버그가 반복돼 왔다는 근거
- https://github.com/cilium/cilium/issues/38056, https://github.com/cilium/cilium/issues/38210, https://github.com/cilium/cilium/issues/40219 — 1.17.x 계열의 endpoint/policy lock deadlock 이력

## 보고서에 쓸 요약 문장 (제안)

"cilium v1.18.0의 PR #39429로 유입된 회귀로, endpoint 재생성 중 writeHeaderFile이 실패하면 endpoint write lock이 해제되지 않아(v1.18.4 `pkg/endpoint/bpf.go` regenerateBPF의 에러 경로에 unlock 부재), 해당 endpoint에 RLock이 필요한 `cilium endpoint list` 등 모든 endpoint API가 영구 대기(futex_wait)합니다. `cilium status`는 endpoint lock을 사용하지 않아 정상으로 표시됩니다. 수정은 upstream PR #43242 / backport PR #43290으로 v1.18.6에 포함되었으며, v1.18.4는 영향 버전입니다. 조치: v1.18.6 이상(권장 최신 1.18.x)으로 업그레이드."

추가로 확정 도장을 찍으려면 SIGQUIT 스택에서 lock 홀더 goroutine이 부재한 채 전부 같은 endpoint 주소에서 대기하는 패턴, 그리고 과거 로그의 "write endpoint header file" 에러 라인을 증거로 첨부하면 완벽합니다.