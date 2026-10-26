# lib.sh — 배포 스크립트 공통 (source 해서 쓴다)
# 폐쇄망: IMAGE_REGISTRY=registry.local/mirror 이면 매니페스트의 image: 를 사내 레지스트리로 바꿔 적용한다.
#         quay.io/ · docker.io/ 접두사는 떼고 붙인다 (예: apache/spark:3.5.3-python3 → registry.local/mirror/apache/spark:3.5.3-python3)
#         이때 corp 전용 설정(캐시 이미지가 있는 노드 고정 nodeName · imagePullPolicy: Never)은 지운다.
#         MAVEN_REPO=https://nexus.local/repository/maven-public 이면 Iceberg jar 를 거기서 받는다.
#         RWX_SC / RWO_SC 로 StorageClass 를 바꾼다 (기본: corp 의 juicefs / csi-cinder-sc-delete).
render() {
  sed -E -e "" \
    ${IMAGE_REGISTRY:+-e "s#(image:[[:space:]]*)(quay\.io/|docker\.io/)?([a-z0-9./_-]+:[A-Za-z0-9._-]+)#\1${IMAGE_REGISTRY}/\3#"} \
    ${IMAGE_REGISTRY:+-e "/^[[:space:]]*nodeName:/d" -e "/imagePullPolicy:[[:space:]]*Never/d"} \
    ${MAVEN_REPO:+-e "s#https://repo1\.maven\.org/maven2#${MAVEN_REPO}#"} \
    ${RWX_SC:+-e "s#storageClassName: juicefs#storageClassName: ${RWX_SC}#"} \
    ${RWO_SC:+-e "s#storageClassName: csi-cinder-sc-delete#storageClassName: ${RWO_SC}#"} \
    "$@"
}
# kapply <ns> <file...> — render 후 kubectl apply (PodSecurity 경고는 숨김)
kapply() {
  local ns=$1 f; shift
  for f in "$@"; do render "$f" | kubectl -n "$ns" apply -f - 2>&1 | grep -v '^Warning' || true; done
}
# wait_job <ns> <job> [timeout_s] — 성공 0, 실패/시간초과 1
wait_job() {
  local ns=$1 job=$2 t=${3:-1800} s
  for ((i = 0; i < t; i += 5)); do
    s=$(kubectl -n "$ns" get job "$job" -o jsonpath='{.status.succeeded}{.status.failed}' 2>/dev/null || true)
    [[ "$s" == 1 ]] && { kubectl -n "$ns" get job "$job" -o jsonpath='{.status.succeeded}' | grep -q 1 && return 0 || return 1; }
    sleep 5
  done
  return 1
}
# sync_jobs <ns> — Spark Job 스크립트 ConfigMap(ilmtest-jobs)만 갱신 (ilmtest-config 는 건드리지 않는다)
sync_jobs() {
  local d; d=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  kubectl -n "$1" create configmap ilmtest-jobs --dry-run=client -o yaml \
    $(for f in "$d"/spark/*.py "$d"/spark/run-spark.sh "$d"/state_snapshot.py; do printf -- '--from-file=%s ' "$f"; done) \
    | kubectl -n "$1" apply -f - >/dev/null
}
