#!/usr/bin/env bash
# testbed/setup.sh — corp 등 K8s 에 MinIO hot/warm + HMS 테스트베드를 구성한다 (재실행 가능)
#   1) Secret 생성 (최초 1회, 값은 무작위 — 출력하지 않는다)
#   2) MinIO hot/warm · PostgreSQL · toolbox 배포
#   3) MinIO: 사용자(app / tier-svc)·버킷·Versioning·tier 등록
#   4) hive-site Secret · 스키마 초기화 · HMS 배포
# 사용: NS=ilm-test ./setup.sh
set -euo pipefail
NS=${NS:-ilm-test}
cd "$(dirname "$0")"
source ../lib.sh   # IMAGE_REGISTRY (폐쇄망 레지스트리) 지원
K="kubectl -n $NS"
rnd() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }   # URL 안전(hex) — MC_HOST_* 에 그대로 들어간다

HOT_EP=http://minio-hot.${NS}.svc:9000
WARM_EP=http://minio-warm.${NS}.svc:9000

echo "== 1) Secret"
if ! $K get secret ilmtest-minio-hot >/dev/null 2>&1; then
  HOT_PW=$(rnd); WARM_PW=$(rnd); APP_SK=$(rnd); TIER_SK=$(rnd); PG_PW=$(rnd)
  $K create secret generic ilmtest-minio-hot  --from-literal=MINIO_ROOT_USER=hotadmin  --from-literal=MINIO_ROOT_PASSWORD="$HOT_PW"  >/dev/null
  $K create secret generic ilmtest-minio-warm --from-literal=MINIO_ROOT_USER=warmadmin --from-literal=MINIO_ROOT_PASSWORD="$WARM_PW" >/dev/null
  $K create secret generic ilmtest-hms-db --from-literal=password="$PG_PW" >/dev/null
  # 앱(Spark·HMS) — Hot 일반 사용자만. Warm 자격증명은 없다.
  $K create secret generic ilmtest-s3 \
    --from-literal=HOT_ENDPOINT="$HOT_EP" \
    --from-literal=AWS_ACCESS_KEY_ID=ilmtest-app --from-literal=AWS_SECRET_ACCESS_KEY="$APP_SK" \
    --from-literal=MC_HOST_HOT="http://hotadmin:${HOT_PW}@minio-hot.${NS}.svc:9000" >/dev/null
  # 관리(toolbox) — 설정·관측용
  $K create secret generic ilmtest-admin \
    --from-literal=MC_HOST_HOT="http://hotadmin:${HOT_PW}@minio-hot.${NS}.svc:9000" \
    --from-literal=MC_HOST_WARM="http://warmadmin:${WARM_PW}@minio-warm.${NS}.svc:9000" >/dev/null
  # tier 계정 — Hot 이 Warm 에 붙을 때만 쓴다
  $K create secret generic ilmtest-tier --from-literal=access_key=tier-svc --from-literal=secret_key="$TIER_SK" >/dev/null
  unset HOT_PW WARM_PW APP_SK TIER_SK PG_PW
  echo "   생성 완료"
else
  echo "   기존 Secret 사용"
fi

echo "== 2) MinIO · PostgreSQL · toolbox"
kapply "$NS" 10-minio.yaml 30-toolbox.yaml
kapply "$NS" 20-metastore.yaml   # HMS 는 hive-site Secret 전까지 ContainerCreating — 정상
for r in sts/minio-hot sts/minio-warm deploy/ilmtest-toolbox deploy/postgres; do $K rollout status "$r" --timeout=300s; done

echo "== 3) MinIO 설정"
APP_SK=$($K get secret ilmtest-s3 -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d)
TIER_SK=$($K get secret ilmtest-tier -o jsonpath='{.data.secret_key}' | base64 -d)
# 비밀값은 인자가 아니라 stdin 으로 넘긴다 (프로세스 목록·로그 노출 방지)
printf 'APP_SK=%s\nTIER_SK=%s\nWARM_EP=%s\n' "$APP_SK" "$TIER_SK" "$WARM_EP" | $K exec -i deploy/ilmtest-toolbox -- sh -c '
set -e
. /dev/stdin
cat > /tmp/app-policy.json <<J
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:*"],"Resource":["arn:aws:s3:::warehouse","arn:aws:s3:::warehouse/*"]}]}
J
cat > /tmp/tier-policy.json <<J
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:*"],"Resource":["arn:aws:s3:::warm-tier","arn:aws:s3:::warm-tier/*"]}]}
J
# Hot: warehouse 버킷(Versioning ON) + 앱 사용자
mc mb --ignore-existing HOT/warehouse
mc version enable HOT/warehouse
mc admin policy create HOT ilmtest-app /tmp/app-policy.json 2>/dev/null || true
mc admin user add HOT ilmtest-app "$APP_SK"
mc admin policy attach HOT ilmtest-app --user ilmtest-app 2>/dev/null || true
# Warm: tier 전용 버킷(규칙 없음) + tier 계정
mc mb --ignore-existing WARM/warm-tier
mc admin policy create WARM ilmtest-tier /tmp/tier-policy.json 2>/dev/null || true
mc admin user add WARM tier-svc "$TIER_SK"
mc admin policy attach WARM ilmtest-tier --user tier-svc 2>/dev/null || true
# Hot 에 remote tier 등록
mc ilm tier ls HOT 2>/dev/null | grep -q WARM-TIER || \
  mc ilm tier add minio HOT WARM-TIER --endpoint "$WARM_EP" --access-key tier-svc --secret-key "$TIER_SK" --bucket warm-tier
mc ilm tier ls HOT
mc version info HOT/warehouse
'

echo "== 4) hive-site · 스키마 · HMS"
PG_PW=$($K get secret ilmtest-hms-db -o jsonpath='{.data.password}' | base64 -d)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT; chmod 700 "$tmp"
cat > "$tmp/hive-site.xml" <<XML
<?xml version="1.0"?>
<configuration>
  <property><name>javax.jdo.option.ConnectionDriverName</name><value>org.postgresql.Driver</value></property>
  <property><name>javax.jdo.option.ConnectionURL</name><value>jdbc:postgresql://postgres:5432/metastore</value></property>
  <property><name>javax.jdo.option.ConnectionUserName</name><value>hive</value></property>
  <property><name>javax.jdo.option.ConnectionPassword</name><value>${PG_PW}</value></property>
  <property><name>metastore.warehouse.dir</name><value>file:/tmp/warehouse</value></property>
  <property><name>hive.metastore.warehouse.dir</name><value>file:/tmp/warehouse</value></property>
  <property><name>metastore.thrift.port</name><value>9083</value></property>
  <property><name>metastore.expression.proxy</name><value>org.apache.hadoop.hive.metastore.DefaultPartitionExpressionProxy</value></property>
  <property><name>metastore.schema.verification</name><value>false</value></property>
  <property><name>hive.metastore.schema.verification</name><value>false</value></property>
  <property><name>fs.s3.impl</name><value>org.apache.hadoop.fs.s3a.S3AFileSystem</value></property>
  <property><name>fs.AbstractFileSystem.s3.impl</name><value>org.apache.hadoop.fs.s3a.S3A</value></property>
  <property><name>fs.s3a.endpoint</name><value>${HOT_EP}</value></property>
  <property><name>fs.s3a.path.style.access</name><value>true</value></property>
  <property><name>fs.s3a.connection.ssl.enabled</name><value>false</value></property>
  <property><name>fs.s3a.access.key</name><value>ilmtest-app</value></property>
  <property><name>fs.s3a.secret.key</name><value>${APP_SK}</value></property>
</configuration>
XML
$K create secret generic ilmtest-hive-site --from-file=hive-site.xml="$tmp/hive-site.xml" --dry-run=client -o yaml | $K apply -f - >/dev/null
unset PG_PW APP_SK TIER_SK

if ! $K get job ilmtest-schema-init >/dev/null 2>&1; then
cat <<YAML | render | $K apply -f - 2>&1 | grep -v '^Warning'
apiVersion: batch/v1
kind: Job
metadata: {name: ilmtest-schema-init, labels: {app.kubernetes.io/part-of: ilmtest}}
spec:
  backoffLimit: 0
  template:
    metadata: {labels: {app.kubernetes.io/part-of: ilmtest}}
    spec:
      restartPolicy: Never
      initContainers:
        - name: jdbc
          image: curlimages/curl:8.10.1
          command: [sh, -c, 'curl -fsSL -o /pg/postgresql.jar https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar']
          volumeMounts: [{name: pgdriver, mountPath: /pg}]
      containers:
        - name: schematool
          image: apache/hive:3.1.3
          # 엔트리포인트를 덮어쓰면 HIVE_CUSTOM_CONF_DIR 복사가 안 돼 Derby 로 폴백한다 → 직접 복사
          command: [sh, -c, 'set -e; cp -r /opt/hive/conf /tmp/conf; cp /hive_custom_conf/hive-site.xml /tmp/conf/; export HIVE_CONF_DIR=/tmp/conf; exec /opt/hive/bin/schematool -dbType postgres -initSchema']
          volumeMounts:
            - {name: conf, mountPath: /hive_custom_conf, readOnly: true}
            - {name: pgdriver, mountPath: /opt/hive/lib/postgresql-9.4.1208.jre7.jar, subPath: postgresql.jar}
      volumes:
        - {name: conf, secret: {secretName: ilmtest-hive-site}}
        - {name: pgdriver, emptyDir: {}}
YAML
  $K wait --for=condition=complete job/ilmtest-schema-init --timeout=300s
fi
$K rollout restart deploy/hive-metastore >/dev/null
$K rollout status deploy/hive-metastore --timeout=300s
$K get pods -o wide
