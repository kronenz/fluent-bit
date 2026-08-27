# 06. Spark on Kubernetes + Iceberg + AIStor S3 구성

> 🔍 버전 조합은 반드시 실환경에서 확인하십시오. Iceberg/Spark/Hadoop/AWS SDK는 서로 강하게 결합되어 있어, 잘못된 조합의 대표 증상이 `NoClassDefFoundError` / `NoSuchMethodError` 입니다.

## 1. 구성 요소 및 버전 매트릭스

### 1.1 호환 조합 (대표 예시)

| Spark | Scala | Iceberg runtime | AWS 연동 | 비고 |
|---|---|---|---|---|
| 3.4.x | 2.12 | `iceberg-spark-runtime-3.4_2.12` | `iceberg-aws-bundle` (SDK v2) | 안정 |
| 3.5.x | 2.12 | `iceberg-spark-runtime-3.5_2.12` | `iceberg-aws-bundle` | **권장** |
| 3.5.x | 2.13 | `iceberg-spark-runtime-3.5_2.13` | `iceberg-aws-bundle` | Scala 2.13 이미지 사용 시 |
| 4.0.x | 2.13 | `iceberg-spark-runtime-4.0_2.13` 🔍 | `iceberg-aws-bundle` | 최신, 사전 검증 필요 |

| 항목 | 확인 방법 |
|---|---|
| Spark 버전 | `spark-submit --version` |
| Scala 버전 | Spark 배포판 이름 또는 `spark-shell` 배너 |
| Hadoop 버전 | `ls $SPARK_HOME/jars \| grep hadoop-common` |
| Iceberg 버전 | `ls $SPARK_HOME/jars \| grep iceberg` |

### 1.2 두 가지 S3 접근 방식 — 무엇을 쓸 것인가

| | **S3FileIO** (권장) | **S3AFileSystem** (Hadoop) |
|---|---|---|
| 구현 | Iceberg 자체, AWS SDK v2 | Hadoop `hadoop-aws` + SDK v1/v2 |
| 필요 jar | `iceberg-aws-bundle` | `hadoop-aws` + `aws-java-sdk-bundle` (버전 정합 까다로움) |
| 경로 스킴 | `s3://` | `s3a://` |
| 성능 | 병렬/멀티파트 최적화 | 커밋터 설정 필요 |
| 설정 위치 | `spark.sql.catalog.<cat>.s3.*` | `spark.hadoop.fs.s3a.*` |
| Iceberg 기능 지원 | 최신 기능 우선 지원 | 일부 지연 |
| 이 환경 권고 | ✅ | 기존 자산 호환 필요 시 |

⚠️ **혼용 주의**: 카탈로그는 S3FileIO(`s3://`)인데 기존 테이블 경로가 `s3a://`이면 접근 실패할 수 있습니다. HMS에 등록된 `metadata_location`의 스킴을 먼저 확인하십시오.

```sql
-- HMS에 저장된 실제 스킴 확인
DESCRIBE EXTENDED hive_prod.db.tbl;
-- 또는 HMS 백엔드 DB에서
--   SELECT PARAM_VALUE FROM TABLE_PARAMS WHERE PARAM_KEY='metadata_location';
```

| HMS에 저장된 스킴 | 권장 설정 |
|---|---|
| `s3a://...` | S3AFileSystem 사용하거나, Iceberg에 `s3a` 스킴 매핑 설정 🔍 |
| `s3://...` | S3FileIO ✅ |
| 혼재 | 통일 작업 필요 → 07장 §4 경로 재작성 |

## 2. Spark 설정 전량 (S3FileIO 기준)

```properties
# ── Iceberg 확장 ────────────────────────────────────────────────
spark.sql.extensions                          org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions

# ── 카탈로그 정의 (Hive Metastore) ──────────────────────────────
spark.sql.catalog.hive_prod                   org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.hive_prod.type              hive
spark.sql.catalog.hive_prod.uri               thrift://hms.data.svc.cluster.local:9083
spark.sql.catalog.hive_prod.warehouse         s3://warehouse/

# ── S3 (AIStor hot 클러스터) ────────────────────────────────────
spark.sql.catalog.hive_prod.io-impl                 org.apache.iceberg.aws.s3.S3FileIO
spark.sql.catalog.hive_prod.s3.endpoint             https://hot-s3.example.internal
spark.sql.catalog.hive_prod.s3.path-style-access    true
spark.sql.catalog.hive_prod.s3.access-key-id        ${S3_ACCESS_KEY}
spark.sql.catalog.hive_prod.s3.secret-access-key    ${S3_SECRET_KEY}
spark.sql.catalog.hive_prod.client.region           us-east-1

# ── 카탈로그 캐시 (플래닝 반복 비용 절감) ──────────────────────
spark.sql.catalog.hive_prod.cache-enabled              true
spark.sql.catalog.hive_prod.cache.expiration-interval-ms 60000

# ── 기본 카탈로그 지정 (선택) ──────────────────────────────────
spark.sql.defaultCatalog                      hive_prod

# ── Hive 연동 ──────────────────────────────────────────────────
spark.sql.catalogImplementation               hive
spark.hadoop.hive.metastore.uris              thrift://hms.data.svc.cluster.local:9083
```

| 설정 | 이 환경에서 중요한 이유 |
|---|---|
| `s3.path-style-access=true` | 자체 호스팅 S3는 virtual-host 스타일 DNS가 없는 경우가 많음. **누락 시 접속 실패의 1순위 원인** |
| `s3.endpoint` | hot 엔드포인트 **하나만** 지정. warm은 절대 지정하지 않음 |
| `client.region` | 자체 호스팅이라도 SDK가 요구. 임의값 가능하나 서버 설정과 일치 권장 |
| `cache-enabled` | 반복 쿼리의 플래닝 비용 감소. 단, 외부 커밋 반영 지연 트레이드오프 |

### 2.1 성능 관련 S3FileIO 설정

```properties
# 커넥션 풀 — executor 코어 수 × 2 이상 권장
spark.sql.catalog.hive_prod.http-client.type                       apache
spark.sql.catalog.hive_prod.http-client.apache.max-connections     200
spark.sql.catalog.hive_prod.http-client.apache.connection-timeout-ms 10000
spark.sql.catalog.hive_prod.http-client.apache.socket-timeout-ms   120000

# 멀티파트 업로드
spark.sql.catalog.hive_prod.s3.multipart.threshold                 104857600
spark.sql.catalog.hive_prod.s3.multipart.part-size-bytes           33554432
spark.sql.catalog.hive_prod.s3.multipart.num-threads               8

# 재시도 🔍 (키 이름 버전 확인)
spark.sql.catalog.hive_prod.s3.retry.num-retries                   5
spark.sql.catalog.hive_prod.s3.retry.min-wait-ms                   200
spark.sql.catalog.hive_prod.s3.retry.max-wait-ms                   20000

# 체크섬 / SSL
spark.sql.catalog.hive_prod.s3.checksum-enabled                    false
```

> ⚠️ **전이(warm) 조회를 하는 순간 socket timeout이 중요해집니다.** hot이 warm에서 데이터를 가져오는 동안 응답이 지연되므로, `socket-timeout-ms`가 너무 짧으면 전이 객체 읽기가 타임아웃으로 실패합니다. 10장 §5에서 실측 후 조정하십시오.

### 2.2 Iceberg 읽기/쓰기 튜닝

```properties
# 벡터화 읽기
spark.sql.iceberg.vectorization.enabled        true

# 플래닝 병렬도
spark.sql.iceberg.planning.preserve-data-grouping  false

# 스플릿 크기 — 전이 환경에서는 크게 잡아 요청 수를 줄이는 편이 유리
spark.sql.catalog.hive_prod.read.split.target-size   268435456
spark.sql.catalog.hive_prod.read.split.metadata-target-size 33554432

# AQE
spark.sql.adaptive.enabled                     true
spark.sql.adaptive.coalescePartitions.enabled  true
spark.sql.adaptive.advisoryPartitionSizeInBytes 268435456

# 쓰기 파일 크기 (05장 §5와 연동)
spark.sql.catalog.hive_prod.write.target-file-size-bytes  536870912
```

### 2.3 S3AFileSystem 을 써야 하는 경우

```properties
spark.hadoop.fs.s3a.impl                       org.apache.hadoop.fs.s3a.S3AFileSystem
spark.hadoop.fs.s3a.endpoint                   https://hot-s3.example.internal
spark.hadoop.fs.s3a.path.style.access          true
spark.hadoop.fs.s3a.access.key                 ${S3_ACCESS_KEY}
spark.hadoop.fs.s3a.secret.key                 ${S3_SECRET_KEY}
spark.hadoop.fs.s3a.connection.ssl.enabled     true
spark.hadoop.fs.s3a.connection.maximum         200
spark.hadoop.fs.s3a.fast.upload                true
spark.hadoop.fs.s3a.multipart.size             33554432
spark.hadoop.fs.s3a.threads.max                64
spark.hadoop.fs.s3a.attempts.maximum           5
spark.hadoop.fs.s3a.retry.limit                7
spark.hadoop.fs.s3a.experimental.input.fadvise random     # Parquet range 읽기에 유리

# Iceberg 카탈로그가 s3a 스킴을 쓰도록
spark.sql.catalog.hive_prod.warehouse          s3a://warehouse/
# io-impl 은 지정하지 않음 (HadoopFileIO 사용)
```

⚠️ `fadvise=random` 은 Parquet 컬럼 읽기에서 중요합니다. `sequential`이면 불필요한 데이터를 대량 읽어 전이 환경에서 특히 비쌉니다.

## 3. Kubernetes 배포

### 3.1 Secret / ConfigMap

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: s3-hot-creds
  namespace: data
type: Opaque
stringData:
  S3_ACCESS_KEY: "svc-spark"
  S3_SECRET_KEY: "<SECRET>"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: spark-iceberg-conf
  namespace: data
data:
  spark-defaults.conf: |
    spark.sql.extensions                              org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions
    spark.sql.catalog.hive_prod                       org.apache.iceberg.spark.SparkCatalog
    spark.sql.catalog.hive_prod.type                  hive
    spark.sql.catalog.hive_prod.uri                   thrift://hms.data.svc.cluster.local:9083
    spark.sql.catalog.hive_prod.warehouse             s3://warehouse/
    spark.sql.catalog.hive_prod.io-impl               org.apache.iceberg.aws.s3.S3FileIO
    spark.sql.catalog.hive_prod.s3.endpoint           https://hot-s3.example.internal
    spark.sql.catalog.hive_prod.s3.path-style-access  true
    spark.sql.catalog.hive_prod.client.region         us-east-1
    spark.sql.catalog.hive_prod.http-client.apache.max-connections 200
    spark.sql.iceberg.vectorization.enabled           true
```

### 3.2 SparkApplication (Spark Operator)

```yaml
apiVersion: sparkoperator.k8s.io/v1beta2
kind: SparkApplication
metadata:
  name: iceberg-ilm-test
  namespace: data
spec:
  type: Scala                       # 또는 Python
  mode: cluster
  image: registry.example.internal/spark-iceberg:3.5.1-icb1.9.0
  imagePullPolicy: IfNotPresent
  mainClass: org.apache.spark.examples.SparkPi     # 실제 잡으로 치환
  mainApplicationFile: local:///opt/app/job.jar
  sparkVersion: "3.5.1"
  restartPolicy:
    type: OnFailure
    onFailureRetries: 2
    onFailureRetryInterval: 30
  sparkConf:
    spark.sql.extensions: "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions"
    spark.sql.catalog.hive_prod: "org.apache.iceberg.spark.SparkCatalog"
    spark.sql.catalog.hive_prod.type: "hive"
    spark.sql.catalog.hive_prod.uri: "thrift://hms.data.svc.cluster.local:9083"
    spark.sql.catalog.hive_prod.warehouse: "s3://warehouse/"
    spark.sql.catalog.hive_prod.io-impl: "org.apache.iceberg.aws.s3.S3FileIO"
    spark.sql.catalog.hive_prod.s3.endpoint: "https://hot-s3.example.internal"
    spark.sql.catalog.hive_prod.s3.path-style-access: "true"
    spark.sql.catalog.hive_prod.client.region: "us-east-1"
    spark.sql.catalog.hive_prod.http-client.apache.max-connections: "200"
    spark.sql.catalog.hive_prod.http-client.apache.socket-timeout-ms: "120000"
    spark.eventLog.enabled: "true"
    spark.eventLog.dir: "s3://warehouse/_spark-events/"
  driver:
    cores: 2
    memory: "4g"
    serviceAccount: spark
    envFrom:
      - secretRef: { name: s3-hot-creds }
    env:
      - name: AWS_ACCESS_KEY_ID
        valueFrom: { secretKeyRef: { name: s3-hot-creds, key: S3_ACCESS_KEY } }
      - name: AWS_SECRET_ACCESS_KEY
        valueFrom: { secretKeyRef: { name: s3-hot-creds, key: S3_SECRET_KEY } }
    volumeMounts:
      - { name: ca, mountPath: /etc/ssl/custom, readOnly: true }
  executor:
    instances: 8
    cores: 4
    memory: "16g"
    envFrom:
      - secretRef: { name: s3-hot-creds }
    env:
      - name: AWS_ACCESS_KEY_ID
        valueFrom: { secretKeyRef: { name: s3-hot-creds, key: S3_ACCESS_KEY } }
      - name: AWS_SECRET_ACCESS_KEY
        valueFrom: { secretKeyRef: { name: s3-hot-creds, key: S3_SECRET_KEY } }
    volumeMounts:
      - { name: ca, mountPath: /etc/ssl/custom, readOnly: true }
  volumes:
    - name: ca
      configMap: { name: s3-ca-bundle }
```

> ✅ 자격증명은 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` 환경변수로 주는 것이 안전합니다. `sparkConf`에 평문으로 넣으면 **Spark UI와 이벤트 로그에 노출**됩니다.

### 3.3 spark-submit 직접 실행

```bash
spark-submit \
  --master k8s://https://k8s-api.example.internal:6443 \
  --deploy-mode cluster \
  --name iceberg-ilm-test \
  --packages org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.9.0,org.apache.iceberg:iceberg-aws-bundle:1.9.0 \
  --conf spark.kubernetes.container.image=registry.example.internal/spark-iceberg:3.5.1 \
  --conf spark.kubernetes.namespace=data \
  --conf spark.kubernetes.authenticate.driver.serviceAccountName=spark \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
  --conf spark.sql.catalog.hive_prod=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.hive_prod.type=hive \
  --conf spark.sql.catalog.hive_prod.uri=thrift://hms.data.svc.cluster.local:9083 \
  --conf spark.sql.catalog.hive_prod.warehouse=s3://warehouse/ \
  --conf spark.sql.catalog.hive_prod.io-impl=org.apache.iceberg.aws.s3.S3FileIO \
  --conf spark.sql.catalog.hive_prod.s3.endpoint=https://hot-s3.example.internal \
  --conf spark.sql.catalog.hive_prod.s3.path-style-access=true \
  --conf spark.kubernetes.driver.secretKeyRef.AWS_ACCESS_KEY_ID=s3-hot-creds:S3_ACCESS_KEY \
  --conf spark.kubernetes.driver.secretKeyRef.AWS_SECRET_ACCESS_KEY=s3-hot-creds:S3_SECRET_KEY \
  --conf spark.kubernetes.executor.secretKeyRef.AWS_ACCESS_KEY_ID=s3-hot-creds:S3_ACCESS_KEY \
  --conf spark.kubernetes.executor.secretKeyRef.AWS_SECRET_ACCESS_KEY=s3-hot-creds:S3_SECRET_KEY \
  local:///opt/app/job.jar
```

⚠️ 운영 환경에서 `--packages`는 **매 실행마다 Maven 다운로드**를 시도합니다. 폐쇄망이면 실패하고, 아니어도 기동이 느려집니다. **jar를 이미지에 굽는 것**이 정답입니다.

### 3.4 이미지 빌드

```dockerfile
FROM apache/spark:3.5.1-scala2.12-java11-ubuntu

USER root
ARG ICEBERG_VERSION=1.9.0
ARG SCALA_BINARY=2.12
ARG SPARK_MINOR=3.5

RUN set -eux; \
    cd /opt/spark/jars; \
    curl -fsSLO https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-${SPARK_MINOR}_${SCALA_BINARY}/${ICEBERG_VERSION}/iceberg-spark-runtime-${SPARK_MINOR}_${SCALA_BINARY}-${ICEBERG_VERSION}.jar; \
    curl -fsSLO https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/${ICEBERG_VERSION}/iceberg-aws-bundle-${ICEBERG_VERSION}.jar

# 사설 CA 신뢰 (자체 서명 인증서 사용 시)
COPY ca-bundle.crt /usr/local/share/ca-certificates/aistor-ca.crt
RUN update-ca-certificates && \
    keytool -importcert -noprompt -trustcacerts \
      -alias aistor -file /usr/local/share/ca-certificates/aistor-ca.crt \
      -keystore "$JAVA_HOME/lib/security/cacerts" -storepass changeit

USER 185
```

| 항목 | 이유 |
|---|---|
| jar 사전 포함 | 폐쇄망/기동속도 |
| CA 신뢰 등록 | 자체 서명 인증서 사용 시 필수. **Java truststore에도 넣어야 함** (OS만으론 부족) |
| 비루트 실행 | 보안 |

## 4. 연결 검증 절차

### 4.1 단계별 격리 검증

문제가 생겼을 때 어느 계층인지 빠르게 가르기 위해 **아래 순서대로** 검증하십시오.

| # | 검증 | 방법 | 실패 시 원인 |
|---|---|---|---|
| 1 | 네트워크 | `curl -v https://hot-s3.example.internal/minio/health/live` | DNS/방화벽/인증서 |
| 2 | 인증서 | `openssl s_client -connect hot-s3:443 -showcerts` | CA 미신뢰 |
| 3 | S3 인증 | `mc ls HOT/warehouse` (같은 자격증명) | 키/정책 |
| 4 | HMS | `nc -zv hms.data.svc 9083` | 서비스/네트워크폴리시 |
| 5 | Spark→HMS | `spark.sql("SHOW DATABASES IN hive_prod").show()` | thrift uri, HMS 권한 |
| 6 | Spark→S3 읽기 | `spark.sql("SELECT * FROM hive_prod.db.tbl LIMIT 1")` | path-style, endpoint |
| 7 | Spark→S3 쓰기 | 임시 테이블 생성/삽입 | 쓰기 권한 |
| 8 | 커밋 | 재조회로 반영 확인 | HMS 쓰기 권한 |

### 4.2 검증 스크립트 (PySpark)

```python
# verify-spark-iceberg.py
from pyspark.sql import SparkSession
import time, sys

spark = SparkSession.builder.appName("verify-iceberg-aistor").getOrCreate()
CAT = "hive_prod"
DB  = "ilm_test"
TBL = f"{CAT}.{DB}.verify_tbl"
ok = lambda m: print(f"[OK]   {m}")
ng = lambda m, e: (print(f"[FAIL] {m}: {e}"), sys.exit(1))

try:
    spark.sql(f"SHOW DATABASES IN {CAT}").show(truncate=False); ok("HMS 연결")
except Exception as e: ng("HMS 연결", e)

try:
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {CAT}.{DB}"); ok("DB 생성")
except Exception as e: ng("DB 생성", e)

try:
    spark.sql(f"""
      CREATE TABLE IF NOT EXISTS {TBL} (id BIGINT, ts TIMESTAMP, payload STRING)
      USING iceberg PARTITIONED BY (days(ts))
      TBLPROPERTIES (
        'write.target-file-size-bytes'='536870912',
        'write.metadata.delete-after-commit.enabled'='true',
        'write.metadata.previous-versions-max'='20'
      )""")
    ok("테이블 생성")
except Exception as e: ng("테이블 생성", e)

try:
    spark.sql(f"INSERT INTO {TBL} VALUES (1, current_timestamp(), 'hello')"); ok("쓰기/커밋")
except Exception as e: ng("쓰기/커밋", e)

try:
    n = spark.sql(f"SELECT count(*) c FROM {TBL}").collect()[0]["c"]; ok(f"읽기 (rows={n})")
except Exception as e: ng("읽기", e)

try:
    spark.sql(f"SELECT * FROM {TBL}.snapshots").show(truncate=False)
    spark.sql(f"SELECT file_path, file_size_in_bytes FROM {TBL}.files").show(truncate=False)
    ok("시스템 테이블")
except Exception as e: ng("시스템 테이블", e)

# 실제 물리 경로 출력 — ILM 규칙 프리픽스 결정에 사용
paths = [r["file_path"] for r in spark.sql(f"SELECT file_path FROM {TBL}.files").collect()]
print("=== 데이터 파일 경로 (ILM 프리픽스 설계에 사용) ===")
for p in paths[:5]: print("  ", p)

print("=== metadata 경로 ===")
spark.sql(f"SELECT file FROM {TBL}.metadata_log_entries ORDER BY timestamp DESC LIMIT 3").show(truncate=False)

spark.stop()
```

> ✅ 이 스크립트의 마지막 출력(실제 경로)이 [04장 ILM 프리픽스 설계](../04-ilm-policy-design/)의 입력값입니다. 추측하지 말고 여기서 확인한 값을 쓰십시오.

## 5. 자주 발생하는 오류와 원인

| 증상 | 원인 | 조치 |
|---|---|---|
| `UnknownHostException: bucket.hot-s3...` | virtual-host 스타일 시도 | `s3.path-style-access=true` |
| `SSLHandshakeException: PKIX path building failed` | 사설 CA 미신뢰 | 이미지의 Java truststore에 CA 등록 (§3.4) |
| `NoSuchMethodError: software.amazon.awssdk...` | SDK v1/v2 jar 충돌 | `aws-java-sdk-bundle` 제거, `iceberg-aws-bundle`만 사용 |
| `ClassNotFoundException: org.apache.iceberg.spark.SparkCatalog` | runtime jar 누락/Scala 버전 불일치 | jar 버전·Scala 접미사 확인 |
| `MetaException: Could not connect to meta store` | HMS 미도달 | NetworkPolicy, thrift uri |
| `Table does not exist` (mc에는 파일이 보임) | HMS 등록 누락 또는 경로 불일치 | 07장 §5 `register_table` |
| `NotFoundException: ... .parquet` | 파일 실제 부재 | 🔴 ILM 만료 의심 → 11장 F-02 |
| `SocketTimeoutException` (구 파티션만) | 전이 객체 읽기 지연 | `socket-timeout-ms` 상향, 10장 §5 |
| `Timeout waiting for connection from pool` | 커넥션 풀 부족 | `max-connections` 상향 |
| `CommitFailedException: metadata location has changed` | 동시 커밋 충돌 | 재시도 설정, 잡 스케줄 분리 |
| `AccessDenied` (쓰기만) | 정책에 PutObject 누락 | 03장 §3.2 |
| 쓰기는 되는데 조회 시 빈 결과 | 카탈로그 캐시 | `cache.expiration-interval-ms` 축소 또는 세션 재시작 |

### 커밋 충돌 대응 설정

```properties
spark.sql.catalog.hive_prod.commit.retry.num-retries        10
spark.sql.catalog.hive_prod.commit.retry.min-wait-ms        500
spark.sql.catalog.hive_prod.commit.retry.max-wait-ms        60000
spark.sql.catalog.hive_prod.commit.retry.total-timeout-ms   1800000
```

## 6. 로깅·관측 설정 (문제 분석용)

```properties
# S3 요청 로그 — 전이 지연 분석 시 필수
spark.driver.extraJavaOptions   -Dlog4j2.configurationFile=log4j2-debug.properties
spark.executor.extraJavaOptions -Dlog4j2.configurationFile=log4j2-debug.properties

# 이벤트 로그 (History Server)
spark.eventLog.enabled          true
spark.eventLog.dir              s3://warehouse/_spark-events/
```

```properties
# log4j2-debug.properties (필요 시에만)
logger.iceberg.name  = org.apache.iceberg
logger.iceberg.level = INFO
logger.awssdk.name   = software.amazon.awssdk.request
logger.awssdk.level  = DEBUG      # ⚠️ 매우 verbose. 짧은 재현 구간에만
```

⚠️ `_spark-events/` 는 Iceberg 테이블 경로가 아니지만 **같은 버킷에 있으면 ILM 규칙 프리픽스에 걸릴 수 있습니다.** `Prefix: ""` 규칙을 만들면 안 되는 이유 중 하나입니다.

## 7. 설정 체크리스트

| # | 항목 | 확인 | ✅ |
|---|---|---|---|
| S-1 | Spark/Scala/Iceberg 버전 조합 검증 | jar 목록 | |
| S-2 | `path-style-access=true` | 설정값 | |
| S-3 | endpoint가 **hot만** 지정 | 설정값 | |
| S-4 | 자격증명이 환경변수 (평문 conf 아님) | manifest | |
| S-5 | 사설 CA가 Java truststore에 등록 | 이미지 검증 | |
| S-6 | jar가 이미지에 포함 (`--packages` 미사용) | Dockerfile | |
| S-7 | `socket-timeout-ms` ≥ 120s (전이 대비) | 설정값 | |
| S-8 | `max-connections` ≥ executor 총 코어 × 2 | 설정값 | |
| S-9 | 테이블 속성: target-file-size, metadata 정리 | `DESCRIBE` | |
| S-10 | HMS 스킴(`s3://` vs `s3a://`) 일치 | HMS 조회 | |
| S-11 | 이벤트 로그 경로가 ILM 규칙에 안 걸림 | ILM 규칙 | |
| S-12 | 검증 스크립트 전 항목 통과 | §4.2 | |

→ 다음: [07. 운영 데이터 반입](../07-test-data/)
