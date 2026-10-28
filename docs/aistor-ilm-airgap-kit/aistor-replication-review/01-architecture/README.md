# 1. 아키텍처 대응 장표

| 장표 | 요청 | 핵심 메시지 | 다이어그램 |
|---|---|---|---|
| [01-hot-warm-icheon-dataops](./01-hot-warm-icheon-dataops.md) | 1 | 이천 Hot/Warm AIStor ↔ 이천 dataops: Private(ClusterMesh+BGP) / Public(Ingress·L4 VIP) 경로 분리, Replication 과 ILM Transition 의 역할 구분 | `diagrams/01-icheon-hot-warm-dataops.{gliffy,drawio,svg}` |
| [02-warm-standalone-yongin](./02-warm-standalone-yongin.md) | 2 | 용인은 **Warm 전용 버킷에 적재·조회**: Trino·Spark(용인) → HMS-Warm(Oracle, 용인 원본) ← Polaris federation, 데이터 경로는 DC 간 S3 API (read/write) | `diagrams/02-warm-standalone-yongin.{gliffy,drawio,svg}` |

- 두 장표 모두 **전제가 확정된 부분(실선)** 과 **확인 필요(빨간 점선/박스)** 를 시각적으로 구분했습니다.
- 확인 필요 항목은 [03-future](../03-future/README.md) 의 체크리스트와 번호로 연결됩니다.
