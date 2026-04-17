# Grafana SQLite → PostgreSQL 마이그레이션 Job

Kubernetes 환경에서 pgloader를 이용해 Grafana 내장 SQLite DB를 PostgreSQL로 이관하는 Job 매니페스트와 사용법입니다.

---

## 📌 개요

- **Namespace:** `monitor`
- **전략:** `data only` + `truncate` (스키마 충돌 방지)
- **전제:** Grafana가 이미 PostgreSQL로 연결되어 스키마 자동 생성 완료 상태
- **파일 위치:** `/data/grafana.db` (PVC 등으로 주입됨)

---

## 📋 목차

1. [사전 준비](#1-사전-준비)
2. [Job YAML 전문](#2-job-yaml-전문)
3. [실행 방법](#3-실행-방법)
4. [검증](#4-검증)
5. [롤백](#5-롤백)
6. [트러블슈팅](#6-트러블슈팅)

---

## 1. 사전 준비

### 1-1. PostgreSQL 스키마 생성 확인

Grafana가 PostgreSQL에 연결되어 스키마를 자동 생성했는지 확인합니다.

```bash
psql -h <PG_HOST> -U grafana -d grafana -c "\dt" | head -20
```

`dashboard`, `data_source`, `user` 등 Grafana 테이블이 보여야 합니다.

### 1-2. PVC 확인

```bash
kubectl get pvc -n monitor | grep grafana
```

### 1-3. PostgreSQL 현재 상태 백업

```bash
kubectl port-forward -n db svc/postgres 5432:5432 &

pg_dump -h localhost -U grafana -d grafana -Fc \
  -f grafana-pre-migration-$(date +%Y%m%d).dump

kill %1
```

### 1-4. Grafana 중지

```bash
# 현재 replicas 기록
REPLICAS=$(kubectl get deployment kube-prometheus-stack-grafana \
  -n monitor -o jsonpath='{.spec.replicas}')

# 중지
kubectl scale deployment/kube-prometheus-stack-grafana \
  -n monitor --replicas=0

# Pod 종료 대기
kubectl wait --for=delete pod -n monitor \
  -l app.kubernetes.io/name=grafana --timeout=60s
```

---

## 2. Job YAML 전문

아래 YAML을 `grafana-pg-migration-job.yaml` 파일로 저장하여 사용합니다.

**수정이 필요한 부분:**

- `PG_HOST` — 실제 PostgreSQL 호스트
- `PG_PASSWORD` — 실제 비밀번호
- `claimName` — 실제 Grafana PVC 이름 (`kubectl get pvc -n monitor` 로 확인)

```yaml
# ═══════════════════════════════════════════════════════════════
# Grafana SQLite → PostgreSQL 마이그레이션 Job
# ═══════════════════════════════════════════════════════════════

---
# ──────────────────────────────────────────────────────────────
# Secret: PostgreSQL 접속 정보
# ──────────────────────────────────────────────────────────────
apiVersion: v1
kind: Secret
metadata:
  name: grafana-pg-migration-secret
  namespace: monitor
type: Opaque
stringData:
  PG_HOST: "pg-cluster.db.svc.cluster.local"
  PG_PORT: "5432"
  PG_DB: "grafana"
  PG_USER: "grafana"
  PG_PASSWORD: "your-secure-password"

---
# ──────────────────────────────────────────────────────────────
# ConfigMap: pgloader 설정 파일 + 실행 스크립트
# ──────────────────────────────────────────────────────────────
apiVersion: v1
kind: ConfigMap
metadata:
  name: pgloader-config
  namespace: monitor
data:
  grafana.load: |
    LOAD DATABASE
      FROM sqlite:///data/grafana.db
      INTO {{PG_CONN_STRING}}

    WITH
      data only,
      truncate,
      reset sequences,
      workers = 4,
      concurrency = 1,
      batch rows = 1000,
      prefetch rows = 1000

    SET
      work_mem to '128MB',
      maintenance_work_mem to '512MB',
      search_path to 'public'

    CAST
      type datetime  to timestamptz using zero-dates-to-null,
      type timestamp to timestamptz using zero-dates-to-null,
      type date      to date        drop default drop not null using zero-dates-to-null,
      type tinyint   to smallint,
      type bigint    to bigint,
      type text      to text,
      type blob      to bytea,
      type real      to double precision

    EXCLUDING TABLE NAMES MATCHING
      'migration_log',
      ~/^sqlite_/

    BEFORE LOAD DO
      $$ SET session_replication_role = 'replica'; $$

    AFTER LOAD DO
      $$ SET session_replication_role = 'origin'; $$,
      $$ ANALYZE; $$
    ;

  run-migration.sh: |
    #!/bin/bash
    set -euo pipefail

    echo "=========================================="
    echo "Grafana SQLite → PostgreSQL 마이그레이션"
    echo "시작 시각: $(date)"
    echo "=========================================="

    # 1) SQLite 파일 확인
    if [ ! -f /data/grafana.db ]; then
      echo "[ERROR] /data/grafana.db 파일이 없습니다."
      exit 1
    fi

    SQLITE_SIZE=$(du -sh /data/grafana.db | awk '{print $1}')
    echo "[INFO] SQLite 파일 크기: ${SQLITE_SIZE}"

    # 2) PostgreSQL 접속 테스트
    echo ""
    echo "[1/5] PostgreSQL 접속 테스트..."
    export PGPASSWORD="${PG_PASSWORD}"

    if ! psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
         -c "SELECT version();" > /dev/null 2>&1; then
      echo "[ERROR] PostgreSQL 접속 실패"
      exit 1
    fi
    echo "      ✓ 접속 성공"

    # 3) 마이그레이션 전 데이터 상태 확인
    echo ""
    echo "[2/5] 현재 PostgreSQL 데이터 상태..."
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" <<'SQL'
    SELECT
      'dashboard'     AS tbl, COUNT(*) AS cnt FROM dashboard
      UNION ALL SELECT 'data_source',   COUNT(*) FROM data_source
      UNION ALL SELECT '"user"',        COUNT(*) FROM "user"
      UNION ALL SELECT 'org',           COUNT(*) FROM org
      UNION ALL SELECT 'alert_rule',    COUNT(*) FROM alert_rule
      ORDER BY tbl;
    SQL

    # 4) pgloader 설정 파일 생성
    echo ""
    echo "[3/5] pgloader 설정 파일 준비..."
    PG_CONN="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}"

    sed "s|{{PG_CONN_STRING}}|${PG_CONN}|g" \
      /config/grafana.load > /tmp/grafana.load

    echo "      ✓ 설정 파일 생성 완료"

    # 5) pgloader 실행
    echo ""
    echo "[4/5] pgloader 실행..."
    echo "----------------------------------------"
    pgloader --verbose /tmp/grafana.load 2>&1 | tee /tmp/pgloader.log
    PGLOADER_EXIT=${PIPESTATUS[0]}
    echo "----------------------------------------"

    if [ ${PGLOADER_EXIT} -ne 0 ]; then
      echo "[ERROR] pgloader 실행 실패 (exit code: ${PGLOADER_EXIT})"
      exit ${PGLOADER_EXIT}
    fi

    # 6) 마이그레이션 후 검증
    echo ""
    echo "[5/5] 마이그레이션 후 데이터 검증..."
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" <<'SQL'
    SELECT
      'dashboard'     AS tbl, COUNT(*) AS cnt FROM dashboard
      UNION ALL SELECT 'data_source',   COUNT(*) FROM data_source
      UNION ALL SELECT '"user"',        COUNT(*) FROM "user"
      UNION ALL SELECT 'org',           COUNT(*) FROM org
      UNION ALL SELECT 'alert_rule',    COUNT(*) FROM alert_rule
      UNION ALL SELECT 'dashboard_acl', COUNT(*) FROM dashboard_acl
      UNION ALL SELECT 'api_key',       COUNT(*) FROM api_key
      ORDER BY tbl;
    SQL

    echo ""
    echo "=========================================="
    echo "마이그레이션 완료"
    echo "종료 시각: $(date)"
    echo "=========================================="

---
# ──────────────────────────────────────────────────────────────
# Job: 실제 마이그레이션 실행
# ──────────────────────────────────────────────────────────────
apiVersion: batch/v1
kind: Job
metadata:
  name: grafana-pg-migration
  namespace: monitor
  labels:
    app: grafana-pg-migration
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  activeDeadlineSeconds: 3600

  template:
    metadata:
      labels:
        app: grafana-pg-migration
    spec:
      restartPolicy: Never

      # ═══════════════════════════════════════════════════
      # initContainer: SQLite 파일 사전 검증
      # ═══════════════════════════════════════════════════
      initContainers:
        - name: sqlite-verify
          image: keinos/sqlite3:latest
          command:
            - /bin/sh
            - -c
            - |
              set -e
              echo "[InitContainer] SQLite 파일 검증 시작"

              if [ ! -f /data/grafana.db ]; then
                echo "[ERROR] /data/grafana.db 파일이 존재하지 않습니다."
                exit 1
              fi

              echo "[INFO] 파일 크기: $(du -sh /data/grafana.db | awk '{print $1}')"

              INTEGRITY=$(sqlite3 /data/grafana.db "PRAGMA integrity_check;")
              if [ "${INTEGRITY}" != "ok" ]; then
                echo "[ERROR] SQLite 무결성 검사 실패: ${INTEGRITY}"
                exit 1
              fi
              echo "[INFO] 무결성 검사: ok"

              echo ""
              echo "[INFO] 마이그레이션 대상 데이터 건수:"
              sqlite3 /data/grafana.db <<'EOF'
              .headers on
              .mode column
              SELECT 'dashboard'     AS tbl, COUNT(*) AS cnt FROM dashboard
              UNION ALL SELECT 'data_source',   COUNT(*) FROM data_source
              UNION ALL SELECT 'user',          COUNT(*) FROM user
              UNION ALL SELECT 'org',           COUNT(*) FROM org
              UNION ALL SELECT 'alert_rule',    COUNT(*) FROM alert_rule
              UNION ALL SELECT 'dashboard_acl', COUNT(*) FROM dashboard_acl
              UNION ALL SELECT 'api_key',       COUNT(*) FROM api_key;
              EOF

              echo "[InitContainer] 검증 완료"
          volumeMounts:
            - name: sqlite-data
              mountPath: /data
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi

      # ═══════════════════════════════════════════════════
      # 메인 마이그레이션 컨테이너
      # ═══════════════════════════════════════════════════
      containers:
        - name: pgloader
          image: dimitri/pgloader:ccl.latest
          command:
            - /bin/bash
            - /config/run-migration.sh
          envFrom:
            - secretRef:
                name: grafana-pg-migration-secret
          volumeMounts:
            - name: sqlite-data
              mountPath: /data
            - name: pgloader-config
              mountPath: /config
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: "2"
              memory: 2Gi

      # ═══════════════════════════════════════════════════
      # 볼륨 설정
      # ═══════════════════════════════════════════════════
      volumes:
        - name: sqlite-data
          persistentVolumeClaim:
            claimName: kube-prometheus-stack-grafana   # ⚠️ 실제 PVC 이름으로 교체
        - name: pgloader-config
          configMap:
            name: pgloader-config
            defaultMode: 0755
```

---

## 3. 실행 방법

### 3-1. YAML 파일 생성

위 YAML 코드블록 내용을 복사해서 파일로 저장합니다.

```bash
# 파일 생성 (위 YAML 내용을 붙여넣기)
vi grafana-pg-migration-job.yaml

# 또는 여러 줄 붙여넣기
cat > grafana-pg-migration-job.yaml <<'EOF'
# (위 YAML 내용 전체 붙여넣기)
EOF
```

### 3-2. 값 수정

```bash
# Secret 값 수정 (PG_HOST, PG_PASSWORD)
vi grafana-pg-migration-job.yaml

# PVC 이름 확인 및 수정
kubectl get pvc -n monitor | grep grafana
# → claimName 부분 수정
```

### 3-3. Job 실행

```bash
kubectl apply -f grafana-pg-migration-job.yaml
```

### 3-4. 실행 모니터링

```bash
# Job 상태
kubectl get jobs -n monitor grafana-pg-migration

# Pod 찾기
POD=$(kubectl get pods -n monitor -l app=grafana-pg-migration \
  -o jsonpath='{.items[0].metadata.name}')

# initContainer 로그
kubectl logs -n monitor ${POD} -c sqlite-verify

# 메인 컨테이너 로그 (실시간)
kubectl logs -n monitor ${POD} -c pgloader -f
```

### 3-5. Grafana 재기동

```bash
kubectl scale deployment/kube-prometheus-stack-grafana \
  -n monitor --replicas=${REPLICAS}

# 시작 로그 확인
kubectl logs -n monitor -l app.kubernetes.io/name=grafana -f | \
  grep -iE "migrat|ready|error"
```

---

## 4. 검증

### 4-1. pgloader 결과 확인

로그 마지막의 요약 테이블에서 `errors` 컬럼이 모두 `0`인지 확인합니다.

```
             table name     errors       rows      bytes      total time
-----------------------  ---------  ---------  ---------  --------------
              dashboard          0         42    128.0 kB          0.050s
            data_source          0          5     12.2 kB          0.010s
                   user          0          3      4.1 kB          0.008s
```

### 4-2. Grafana Health Check

```bash
GRAFANA_POD=$(kubectl get pods -n monitor \
  -l app.kubernetes.io/name=grafana \
  -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n monitor ${GRAFANA_POD} -- \
  curl -s http://localhost:3000/api/health | jq .
```

`"database": "ok"` 이면 정상.

### 4-3. UI 검증 체크리스트

- [ ] Grafana 로그인 가능
- [ ] 대시보드 목록 및 개별 렌더링 정상
- [ ] 데이터소스 Test 정상
- [ ] Alert Rule 목록 정상
- [ ] 유저/권한 정상
- [ ] 새 대시보드 저장 → 재조회 정상

---

## 5. 롤백

문제 발생 시 1-3에서 만든 백업으로 원복합니다.

```bash
# Grafana 중지
kubectl scale deployment/kube-prometheus-stack-grafana \
  -n monitor --replicas=0

# 포트포워딩
kubectl port-forward -n db svc/postgres 5432:5432 &

# 스키마 초기화 + 복원
psql -h localhost -U grafana -d grafana -c "
  DROP SCHEMA public CASCADE;
  CREATE SCHEMA public;
  GRANT ALL ON SCHEMA public TO grafana;
"

pg_restore -h localhost -U grafana -d grafana \
  grafana-pre-migration-YYYYMMDD.dump

# 재기동
kubectl scale deployment/kube-prometheus-stack-grafana \
  -n monitor --replicas=1

kill %1
```

---

## 6. 트러블슈팅

### Job이 Pending 상태에서 진행 안 됨

PVC를 Grafana Pod가 아직 점유 중일 가능성이 있습니다.

```bash
kubectl describe pod -n monitor -l app=grafana-pg-migration
kubectl get pods -n monitor | grep grafana
```

Grafana Pod 완전 종료를 확인 후 재시도합니다.

### "grafana.db 파일이 없습니다"

PVC 내 파일 경로를 확인합니다.

```bash
kubectl run debug --rm -it --image=busybox -n monitor \
  --overrides='{"spec":{"containers":[{"name":"debug","image":"busybox","command":["sh"],"stdin":true,"tty":true,"volumeMounts":[{"name":"data","mountPath":"/data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"<YOUR_PVC>"}}]}}'

# Pod 내부에서
find /data -name "grafana.db"
```

파일이 하위 경로에 있다면 initContainer의 경로를 조정합니다.

### "type cast error"

특정 컬럼의 타입 변환 실패입니다.

```bash
kubectl logs -n monitor ${POD} -c pgloader | grep -B2 -A5 "cast error"
```

ConfigMap의 `grafana.load` CAST 섹션에 규칙을 추가합니다.

### "permission denied for schema public" (PG 15+)

```sql
\c grafana
GRANT ALL ON SCHEMA public TO grafana;
```

### Foreign Key 위반

Job에 `session_replication_role = 'replica'` 설정이 포함되어 있습니다. ConfigMap의 `BEFORE LOAD DO`에 해당 설정이 있는지 확인합니다.

### Grafana 재시작 후 "user token not found" 로그

정상 동작입니다. 브라우저에 남은 이전 세션 쿠키 때문이며, 재로그인하면 사라집니다.

```sql
-- 모든 세션 강제 초기화 시
TRUNCATE user_auth_token;
```

### Job 재실행

```bash
kubectl delete job grafana-pg-migration -n monitor
kubectl apply -f grafana-pg-migration-job.yaml
```

`truncate` 옵션으로 데이터 중복 없이 안전하게 재실행 가능합니다.

---

## 📌 실행 순서 요약

```bash
# 1. PostgreSQL 백업
pg_dump -h localhost -U grafana -d grafana -Fc -f backup.dump

# 2. Grafana 중지
kubectl scale deployment/kube-prometheus-stack-grafana \
  -n monitor --replicas=0

# 3. YAML 수정 후 적용
kubectl apply -f grafana-pg-migration-job.yaml

# 4. 로그 모니터링
kubectl logs -n monitor -l app=grafana-pg-migration -f

# 5. 완료 후 Grafana 재기동
kubectl scale deployment/kube-prometheus-stack-grafana \
  -n monitor --replicas=1

# 6. UI 검증
```


```
LOAD DATABASE
  FROM sqlite:///data/grafana.db
  INTO {{PG_CONN_STRING}}

WITH
  data only,
  truncate,
  reset sequences,
  workers = 1,
  concurrency = 1,
  batch rows = 100,
  prefetch rows = 100

SET
  work_mem to '32MB',
  maintenance_work_mem to '64MB',
  search_path to 'public'

CAST
  type datetime  to timestamptz using zero-dates-to-null,
  type timestamp to timestamptz using zero-dates-to-null,
  type date      to date        drop default drop not null using zero-dates-to-null,
  type tinyint   to smallint,
  type bigint    to bigint,
  type text      to text,
  type blob      to bytea

INCLUDING ONLY TABLE NAMES MATCHING
  'dashboard',
  'dashboard_acl',
  'dashboard_provisioning',
  'dashboard_tag',
  'dashboard_version',
  'data_source',
  'org',
  'org_user',
  'user',
  'user_auth',
  'user_auth_token',
  'user_role',
  'team',
  'team_member',
  'team_role',
  'folder',
  'alert_rule',
  'alert_rule_tag',
  'alert_rule_version',
  'alert_configuration',
  'alert_notification',
  'alert_notification_state',
  'annotation',
  'annotation_tag',
  'api_key',
  'preferences',
  'star',
  'playlist',
  'playlist_item',
  'plugin_setting',
  'quota',
  'temp_user',
  'kv_store',
  'permission',
  'role',
  'builtin_role',
  'ngalert_configuration',
  'provenance_type',
  'library_element',
  'library_element_connection',
  'secrets',
  'seed_assignment',
  'query_history',
  'query_history_star',
  'correlation',
  'tag'
;
```