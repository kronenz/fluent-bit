# 공개 공식 문서 링크 · 원문 인용 모음

> 카테고리: 근거 정리 · 확인일 2026-09-29 (모든 링크 HTTP 200 확인)
> 인용은 영어 원문 그대로이며, "지원 수준" 열은 인용이 주장을 **직접** 뒷받침하는지(✅), 부분적인지(◐), 문구가 없어 *부재 자체*가 근거인지(∅)를 표시합니다.
> 구 `min.io/docs/minio/linux/...` 링크는 현재 `docs.min.io/enterprise/aistor-object-store/...` 로 리다이렉트되므로 신규 경로를 사용합니다.

## MinIO AIStor

| ID | 주제 | 원문 인용 | 지원 | 링크 |
|---|---|---|---|---|
| <a id="m1"></a>M1 | 비동기 복제 / Versioning 필수 | "MinIO AIStor returns a response to the originating PUT operation before placing the object into a replication queue." (동기 모드: "attempts to replicate the object before returning a response to the client.") / "MinIO AIStor relies on the immutability protections provided by versioning to support replication and resynchronization." | ✅ | [Bucket Replication](https://docs.min.io/enterprise/aistor-object-store/administration/replication/bucket-replication/) · [Requirements](https://docs.min.io/enterprise/aistor-object-store/administration/replication/bucket-replication/bucket-replication-requirements/) · [mc replicate add](https://docs.min.io/enterprise/aistor-object-store/reference/cli/mc-replicate/mc-replicate-add/) |
| <a id="m2"></a>M2 | 다중 객체 순서·시점 일관성 | 공식 문서에 **보장 문구 없음** (Bucket Replication / Requirements 페이지 모두 순서·일관성 의미론 미기술) | ∅ | 위 M1 링크 — "보장하지 않는다"로 인용하지 말고 "보장 문구가 없다"로 표현 |
| <a id="m3"></a>M3 | delete / delete-marker 복제, ILM 삭제 미복제 | `--replicate` 값: `delete`, `delete-marker`, `existing-objects`, `metadata-sync` / "For buckets with replication configured, MinIO AIStor does not replicate objects deleted by a lifecycle management expiration rule." | ✅ | [mc replicate add](https://docs.min.io/enterprise/aistor-object-store/reference/cli/mc-replicate/mc-replicate-add/) · [Object Lifecycle Management](https://docs.min.io/enterprise/aistor-object-store/administration/object-lifecycle-management/) |
| <a id="m4"></a>M4 | 기존 객체 복제 / resync | "MinIO AIStor by default replicates existing objects in the source bucket to the configured remote" / resync 는 모든 객체를 규칙에 대해 재검사하여 재큐잉 | ✅ | [Bucket Replication](https://docs.min.io/enterprise/aistor-object-store/administration/replication/bucket-replication/) · [mc replicate resync](https://docs.min.io/aistor/reference/cli/mc-replicate/mc-replicate-resync/) |
| <a id="m5"></a>M5 | Replication × Tiering | "For buckets with object transition (Tiering) configured, replication resynchronization restores objects in a non-transitioned state with no associated transition metadata. Any data previously transitioned to the remote storage is therefore permanently disconnected from the remote MinIO AIStor deployment." | ◐ (resync 한정) | [Bucket Replication](https://docs.min.io/enterprise/aistor-object-store/administration/replication/bucket-replication/) |
| <a id="m6"></a>M6 | ILM 액션 범위 | Transition(현재/noncurrent) 과 Expiration(`--expire-days`, `--noncurrent-expire-days`, `--expire-delete-marker`, `--purge-all-object-versions-days`) 만 기술 / "Object 'expiration' involves performing a DELETE operation on the object." / "MinIO AIStor adopts S3 behavior for transition rules on versioned buckets." | ◐ (압축·병합 액션 **부재**로 입증) | [Object Lifecycle Management](https://docs.min.io/enterprise/aistor-object-store/administration/object-lifecycle-management/) |
| <a id="m7"></a>M7 | 서버측 압축 = 투명 압축 | "Objects are compressed on PUT before writing to disk, and uncompressed on GET before they are sent to the client." | ✅ | [Data Compression](https://docs.min.io/enterprise/aistor-object-store/administration/objects-and-versioning/data-compression/) |
| <a id="m8"></a>M8 | S3 Zip 확장 (읽기 전용) | "The extension does not support write operations. To update or delete contents of a file inside a ZIP archive, replace the entire ZIP archive." (요청 헤더 `x-minio-extract: true`) | ✅ | [S3 Zip Extension](https://docs.min.io/aistor/developers/s3-zip-extension/) |
| <a id="m9"></a>M9 | Object Lock | "Object Locking requires versioning." / 잠긴 객체 복제는 양쪽 버킷 Object Lock 필요 / "For active-active configuration, MinIO recommends using the same retention rules on both buckets to ensure consistent behavior across sites." | ✅ | [Object Locking and Immutability](https://docs.min.io/enterprise/aistor-object-store/administration/object-locking-and-immutability/) · [Replication Requirements](https://docs.min.io/enterprise/aistor-object-store/administration/replication/bucket-replication/bucket-replication-requirements/) |
| <a id="m10"></a>M10 | Scanner 기반 ILM | "MinIO AIStor uses a built-in scanner to actively check objects against all configured lifecycle management rules. ... The scanner may therefore not detect an object as eligible for a configured transition or expiration lifecycle rule until after the lifecycle rule period has passed." | ✅ | [Object Lifecycle Management](https://docs.min.io/enterprise/aistor-object-store/administration/object-lifecycle-management/) |
| <a id="m11"></a>M11 | Site vs Bucket Replication | Site replication 은 IAM·버킷 설정 등을 동기화, **Bucket Replication 과 상호 배타** / "Site replication does not copy lifecycle management configurations to the other sites by default." | ◐ | [Site Replication](https://docs.min.io/aistor/administration/replication/site-replication/) |

## AWS S3 (S3 API 기준 참고)

| ID | 주제 | 원문 인용 | 지원 | 링크 |
|---|---|---|---|---|
| <a id="a1"></a>A1 | Lifecycle 요소 | Transition, Expiration, NoncurrentVersionTransition, NoncurrentVersionExpiration, AbortIncompleteMultipartUpload, ExpiredObjectDeleteMarker | ◐ (압축 액션 부재) | [Lifecycle configuration elements](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-elements.html) |
| <a id="a2"></a>A2 | 복제 비동기 / 순서 | "You can use replication to enable automatic, asynchronous copying of objects across Amazon S3 buckets." / 순서: 공식 문서 문구 없음, AWS re:Post 답변 "It's a good idea to assume the replication will be out of order." (**커뮤니티 답변 — 공식 스펙 아님**) | ◐ | [S3 Replication](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html) · [re:Post](https://repost.aws/questions/QUt1N-o2kcTbq1Rp3P6nPNZw/does-aws-s3-crr-srr-replication-order-match-the-order-of-object-creation) |
| <a id="a3"></a>A3 | 소형 객체 병합은 사용자 구현 | AWS Storage Blog: 서버리스 애플리케이션(EventBridge + Step Functions + Lambda)으로 prefix 내 소형 객체를 단일 파일로 compaction 하는 예제 | ◐ | [Compacting small objects](https://aws.amazon.com/blogs/storage/optimizing-storage-costs-and-query-performance-by-compacting-small-objects/) · [aws-samples](https://github.com/aws-samples/s3-small-object-compaction) |

## Apache Iceberg

| ID | 주제 | 원문 인용 | 지원 | 링크 |
|---|---|---|---|---|
| <a id="i1"></a>I1 | 절대 경로 | manifest `file_path`: "Full URI for the file with FS scheme" / "Absolute paths are used as-is without modification." / "Prior to v4, all path fields must contain fully-qualified paths. Starting with v4, path fields may contain either absolute or relative paths." | ✅ (v1~v3) | [Table Spec](https://iceberg.apache.org/spec/) |
| <a id="i2"></a>I2 | 원자적 포인터 교체 | "All changes to table state create a new metadata file and replace the old metadata with an atomic swap." / "Commits replace the path of the current table metadata file using an atomic operation." | ✅ | [Table Spec](https://iceberg.apache.org/spec/) · [Reliability](https://iceberg.apache.org/docs/latest/reliability/) |
| <a id="i3"></a>I3 | register_table / rewrite_table_path | register_table: "Creates a catalog entry for a metadata.json file which already exists but does not have a corresponding catalog identifier." / rewrite_table_path: "prepares an Iceberg table for copying to another location." ... "Lastly, the register_table procedure can be used to register the copied table in the target location with a catalog." (Spark 프로시저는 **Iceberg 1.8.0** 부터, partition statistics 파일 보유 테이블 미지원) | ✅ | [Spark Procedures](https://iceberg.apache.org/docs/latest/spark-procedures/) · [1.8.0 release](https://github.com/apache/iceberg/releases/tag/apache-iceberg-1.8.0) |
| <a id="i4"></a>I4 | 유지보수 | expire_snapshots: "will never remove files which are still required by a non-expired snapshot." (older_than 기본 5일) / remove_orphan_files older_than 기본 3일, 짧은 보존 시 진행 중 쓰기 파일 삭제 위험 경고 / "Iceberg can compact data files in parallel using Spark with the rewriteDataFiles action." | ✅ | [Spark Procedures](https://iceberg.apache.org/docs/latest/spark-procedures/) · [Maintenance](https://iceberg.apache.org/docs/latest/maintenance/) |

## Apache Polaris

| ID | 주제 | 원문 인용 | 지원 | 링크 |
|---|---|---|---|---|
| <a id="p1"></a>P1 | HMS federation | "Polaris can federate catalog operations to an existing Hive Metastore (HMS). This lets an external HMS remain the source of truth for table metadata while Polaris brokers access, policies, and multi-engine connectivity." — 기본 빌드 미포함(빌드 플래그), `ENABLE_CATALOG_FEDERATION=true`, `SUPPORTED_CATALOG_CONNECTION_TYPES` 에 HIVE, 인증 IMPLICIT 만, 연결당 HiveCatalog 1개 (1.1.0 부터 지원) | ✅ (read-only 여부는 문서 미기재) | [HMS Federation (1.8.0)](https://polaris.apache.org/releases/1.8.0/federation/hive-metastore-federation/) |
| <a id="p2"></a>P2 | S3 호환 스토리지 | "Polaris can be pointed at S3-compatible object stores (MinIO, Ceph RGW, Apache Ozone S3 gateway)." / `endpoint`, `endpointInternal`, `pathStyleAccess` | ✅ | [S3 storage config](https://polaris.apache.org/in-dev/unreleased/configuration/configuring-polaris-for-production/configuring-aws-s3-cloud-storage-specific/) · [MinIO guide](https://polaris.apache.org/guides/minio/) |

## Trino

| ID | 주제 | 원문 인용 | 지원 | 링크 |
|---|---|---|---|---|
| <a id="t1"></a>T1 | Iceberg 카탈로그 타입 / native S3 | `iceberg.catalog.type` "Possible values are: hive_metastore glue jdbc rest nessie snowflake" / `s3.endpoint` "S3 service endpoint URL to communicate with." / `s3.path-style-access` / `fs.s3.enabled` "Activate the native implementation for S3 storage support." | ✅ | [Iceberg connector](https://trino.io/docs/current/connector/iceberg.html) · [S3 file system](https://trino.io/docs/current/object-storage/file-system-s3.html) |

## Cilium

| ID | 주제 | 원문 인용 | 지원 | 링크 |
|---|---|---|---|---|
| <a id="c1"></a>C1 | ClusterMesh 전제 / global service | "PodCIDR ranges in all clusters and all nodes must be non-conflicting and unique IP addresses." / "Each cluster must be assigned a unique human-readable name as well as a numeric cluster ID (1-255)." / "Nodes in all clusters must have IP connectivity between each other using the configured InternalIP for each node." / global service: annotation `service.cilium.io/global: "true"` | ✅ (apiserver 포트는 Firewall Rules 절에서 확인 🔍) | [ClusterMesh Setup](https://docs.cilium.io/en/stable/network/clustermesh/setup/) · [Global Services](https://docs.cilium.io/en/stable/network/clustermesh/global-services/) |
| <a id="c2"></a>C2 | BGP 로 LB-IP 광고 | "Cilium BGP Control Plane advertises exact routes for the VIPs (/32 or /128 prefixes). To advertise the service virtual IPs, specify the advertisementType field to Service and the service.addresses field to LoadBalancerIP, ClusterIP or ExternalIP." | ✅ | [BGP Control Plane Configuration](https://docs.cilium.io/en/stable/network/bgp-control-plane/bgp-control-plane-configuration/) |
