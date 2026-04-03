# kubectl 치트시트 (Cheatsheet)

> **TL;DR**
> 1. `kubectl`은 K8s 클러스터와 소통하는 유일한 CLI 도구
> 2. 조회(`get`), 생성(`apply`), 디버깅(`describe/logs`)이 핵심 3대 동작
> 3. `--dry-run=client -o yaml` 조합으로 매니페스트를 빠르게 생성할 수 있다

---

## 1. 조회 (Get / List)

| 명령어 | 설명 |
|---|---|
| `kubectl get pods` | 파드 목록 |
| `kubectl get pods -o wide` | IP, 노드 포함 상세 |
| `kubectl get pods -o yaml` | YAML 전체 출력 |
| `kubectl get pods -w` | 실시간 변경 감시 (watch) |
| `kubectl get all -n <ns>` | 네임스페이스 전체 리소스 |
| `kubectl get nodes` | 노드 상태 확인 |
| `kubectl get svc,ing` | 복수 리소스 동시 조회 |
| `kubectl get pods -l app=web` | 레이블 셀렉터 조회 |
| `kubectl get pods --field-selector status.phase=Running` | 필드 셀렉터 |
| `kubectl top pods` | CPU/메모리 사용량 |

---

## 2. 생성 / 수정 (Create / Apply)

```bash
# 매니페스트 적용
kubectl apply -f deploy.yaml

# 디렉토리 전체 적용
kubectl apply -f ./manifests/ --recursive

# Dry-run으로 YAML 생성 (면접 필수!)
kubectl run nginx --image=nginx \
  --dry-run=client -o yaml > pod.yaml

kubectl create deploy web --image=nginx \
  --replicas=3 --dry-run=client -o yaml

kubectl expose deploy web --port=80 \
  --type=ClusterIP --dry-run=client -o yaml

# 리소스 직접 수정
kubectl edit deploy web
kubectl scale deploy web --replicas=5
kubectl set image deploy/web nginx=nginx:1.25

# 롤아웃 관리
kubectl rollout status deploy/web
kubectl rollout history deploy/web
kubectl rollout undo deploy/web
kubectl rollout undo deploy/web --to-revision=2
```

---

## 3. 삭제 (Delete)

```bash
kubectl delete pod nginx
kubectl delete pod nginx --grace-period=0 --force
kubectl delete -f deploy.yaml
kubectl delete pods -l app=test
kubectl delete ns dev          # 네임스페이스 전체 삭제
```

---

## 4. 디버깅 (Debug / Troubleshoot)

```bash
# 파드 상세 정보 (이벤트 포함)
kubectl describe pod <pod>

# 로그
kubectl logs <pod>
kubectl logs <pod> -c <container>   # 멀티컨테이너
kubectl logs <pod> --previous       # 이전 컨테이너
kubectl logs <pod> -f               # 실시간 (follow)
kubectl logs -l app=web --all-containers

# 파드 내부 진입
kubectl exec -it <pod> -- /bin/sh
kubectl exec -it <pod> -c <container> -- bash

# 디버그 컨테이너 (ephemeral)
kubectl debug <pod> -it --image=busybox

# 포트 포워딩
kubectl port-forward svc/web 8080:80
kubectl port-forward pod/web 8080:80

# 리소스 상태 확인
kubectl get events --sort-by='.lastTimestamp'
kubectl api-resources          # 사용 가능한 리소스 타입
kubectl explain pod.spec       # 스펙 문서 확인
```

---

## 5. 컨텍스트 / 네임스페이스 (Context / Namespace)

```bash
# 컨텍스트 관리
kubectl config get-contexts
kubectl config current-context
kubectl config use-context <ctx>

# 네임스페이스 전환
kubectl config set-context --current --namespace=dev

# kubeconfig 파일 지정
KUBECONFIG=~/.kube/config-prod kubectl get pods
```

---

## 6. 자주 쓰는 옵션 정리

| 옵션 | 설명 | 예시 |
|---|---|---|
| `-o wide` | 추가 정보 (IP, Node) | `get pods -o wide` |
| `-o yaml` | YAML 출력 | `get pod nginx -o yaml` |
| `-o json` | JSON 출력 | `get pod nginx -o json` |
| `-o jsonpath` | 특정 필드 추출 | `get pods -o jsonpath='{.items[*].metadata.name}'` |
| `--dry-run=client` | 실제 생성 없이 테스트 | `run nginx --image=nginx --dry-run=client -o yaml` |
| `-w` | Watch 모드 | `get pods -w` |
| `-l` | 레이블 필터 | `get pods -l app=web` |
| `-n` | 네임스페이스 지정 | `get pods -n kube-system` |
| `-A` | 전체 네임스페이스 | `get pods -A` |

---

## 7. 유용한 Alias 설정

```bash
# ~/.bashrc 또는 ~/.zshrc
alias k='kubectl'
alias kgp='kubectl get pods'
alias kgpa='kubectl get pods -A'
alias kgs='kubectl get svc'
alias kgn='kubectl get nodes'
alias kd='kubectl describe'
alias kl='kubectl logs'
alias kaf='kubectl apply -f'
alias kdf='kubectl delete -f'
alias kctx='kubectl config use-context'
alias kns='kubectl config set-context --current --namespace'

# bash 자동완성
source <(kubectl completion bash)
complete -o default -F __start_kubectl k
```

---

## 8. 면접 빈출 질문

**Q1. `kubectl apply`와 `kubectl create`의 차이는?**
> - `create`: 리소스가 없을 때만 생성 (명령형, Imperative)
> - `apply`: 없으면 생성, 있으면 업데이트 (선언형, Declarative)
> - 프로덕션에서는 GitOps와 함께 `apply`를 사용하는 것이 표준

**Q2. 파드가 `CrashLoopBackOff` 상태일 때 디버깅 순서는?**
> 1. `kubectl describe pod <pod>` - 이벤트 확인
> 2. `kubectl logs <pod> --previous` - 이전 컨테이너 로그
> 3. `kubectl get pod <pod> -o yaml` - 컨테이너 설정 확인
> 4. `kubectl debug <pod> -it --image=busybox` - 디버그 컨테이너

**Q3. `kubectl`이 API 서버와 통신하는 과정을 설명하라**
> 1. `~/.kube/config`에서 클러스터, 사용자, 컨텍스트 정보 로드
> 2. 인증 정보(certificate, token 등)로 API 서버에 HTTPS 요청
> 3. API 서버는 Authentication -> Authorization(RBAC) -> Admission Control 순서로 처리
> 4. etcd에 저장 후 결과 반환

---

**핵심 키워드**: `kubectl`, `Imperative vs Declarative`, `kubeconfig`, `--dry-run`, `CrashLoopBackOff`
