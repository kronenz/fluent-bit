#!/usr/bin/env bash
# run-spark.sh <job.py> — CronJob 컨테이너에서 spark-submit(local 모드) 실행
# Hot 엔드포인트만 지정한다. warm 은 어디에도 넣지 않는다 (06장 §2).
# SPARK_JARS(쉼표 구분 경로)가 있으면 --jars 로 쓰고 --packages 는 생략한다 (폐쇄망·공유 볼륨 jar).
set -euo pipefail
JOB=${1:?job.py}
ICEBERG_VER=${ICEBERG_VER:-1.9.0}
if [[ -n "${SPARK_JARS:-}" ]]; then SPARK_PACKAGES=""; fi
SPARK_PACKAGES=${SPARK_PACKAGES-org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:${ICEBERG_VER},org.apache.iceberg:iceberg-aws-bundle:${ICEBERG_VER}}
C=${CATALOG:-hive_prod}

exec /opt/spark/bin/spark-submit \
  --master "local[${SPARK_CORES:-2}]" \
  --driver-memory "${SPARK_DRIVER_MEMORY:-3g}" \
  ${SPARK_PACKAGES:+--packages "$SPARK_PACKAGES"} \
  ${SPARK_JARS:+--jars "$SPARK_JARS"} \
  --conf spark.jars.ivy=/tmp/.ivy2 \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
  --conf spark.sql.catalog.$C=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.$C.type=hive \
  --conf spark.sql.catalog.$C.uri="$HMS_URI" \
  --conf spark.sql.catalog.$C.warehouse="s3://${BUCKET}/" \
  --conf spark.sql.catalog.$C.io-impl=org.apache.iceberg.aws.s3.S3FileIO \
  --conf spark.sql.catalog.$C.s3.endpoint="$HOT_ENDPOINT" \
  --conf spark.sql.catalog.$C.s3.path-style-access=true \
  --conf spark.sql.catalog.$C.client.region=us-east-1 \
  --conf spark.sql.session.timeZone=UTC \
  --py-files /jobs/common.py \
  "/jobs/$JOB"
# 자격증명은 Secret 의 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 환경변수로 S3FileIO 가 읽는다
