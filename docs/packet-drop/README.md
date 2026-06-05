# Packet Drop 분석 묶음 — 3계층 드릴다운 (single-node)

노드가 많아 전 노드 동시 쿼리는 매우 느리므로 **single-node 기준**(detail 대시보드의 `nodename`은
단일선택, `All`/multi 없음 → 패널이 전 노드로 fan-out 안 함). "어느 노드냐"는 **L0에서만** bounded
`topk`로 찾고, 거기서 노드를 클릭해 단일노드 상세로 **드릴다운**한다. Grafana 폴더 **"Packet Drop"**.

## 토폴로지 (uid)

```
L0  pktdrop-l0-fleet     Fleet Overview — cross-node는 여기뿐(topk). 노드 행 클릭 ▾
L1  pktdrop-l1-node      Node Hub — 단일노드 전 계층 요약 + 🧭자동 원인 추정. 계층 클릭 ▾
      ├ NIC/softnet/socket/cilium/pod/CPU ─▶ pktdrop-l2-layers
      ├ hostNetwork ─────────────────────▶ pktdrop-l2-hostnet
      └ conntrack/csi-nfs/DSR ────────────▶ pktdrop-l2-csi
L3  pktdrop-l3-guide     진단 매트릭스 + 자동 원인 추정 참조
    pktdrop-x-patch      패치 전/후 비교 (Excel 참고용)
```

| uid | 파일 | 출처 |
|---|---|---|
| pktdrop-l0-fleet | l0-fleet.json | 신규 |
| pktdrop-l1-node | l1-node.json | 신규(verdict 패널은 spark-shuffle에서 재사용) |
| pktdrop-l2-layers | l2-layers.json | spark-shuffle-packet-drop 변환(node/cilium/pod/CPU 전 계층) |
| pktdrop-l2-hostnet | l2-hostnet.json | hostnet-pod-node-drop 변환 |
| pktdrop-l2-csi | l2-csi.json | csi-nfs-dsr-drop-trace 변환 |
| pktdrop-l3-guide | l3-guide.json | 신규 |
| pktdrop-x-patch | x-patch.json | spark-drop-patch-compare 변환 |

## 드릴다운 메커니즘 (검증된 Grafana 문법)

- **L0 → L1** (테이블 행 클릭): data link
  `/d/pktdrop-l1-node?${__url_time_range}&var-cluster=${var-cluster}&var-project=${var-project}&var-nodename=${__data.fields.nodename}`
- **L1 → L2** (계층 패널/스탯 클릭): 현재 변수 포워딩
  `/d/<uid>?${__url_time_range}&var-cluster=${var-cluster:queryparam}&var-project=${var-project:queryparam}&var-nodename=${var-nodename:queryparam}`
- **상호 nav**: 모든 대시보드 상단 `Packet Drop ▾`(tag `pktdrop` dropdown, keepTime+includeVars) + `↑ L1` / `↑↑ L0`.

## single-node / 성능

- `nodename` 변수: **multi=false, includeAll=false** (전 대시보드). node-exporter 메트릭은
  `* on(instance) group_left(nodename) node_uname_info{...,nodename=~"$nodename"}` 조인으로 단일노드 한정.
- **L0만 cross-node** — 각 패널 단일 `topk`/`sum` 쿼리(패널 fan-out 없음). 대규모면 recording rule 권장.
- L2는 보조 Row collapsed + maxDataPoints=600.

## 배포 / 검증

```bash
# 배포(provisioning): provider.yml + 이 폴더의 *.json 을 Grafana dashboards 경로에 배치
#   /var/lib/grafana/dashboards/packet-drop/  + provisioning/dashboards/provider.yml
# 검증 게이트(스키마 + nodename-single + 링크무결성):
ops/dashboards/packet-drop/validate.sh
```

> 외부 클러스터(icdataops-prd) 라벨이 다르면(node/nodename, cilium reason) L2의 textbox 정규식 변수와
> 변수 쿼리를 조정. cilium_drop은 node 단위(namespace 귀속은 Hubble). 상세는 각 L2의 가이드 패널 참고.

## 부록 — 메트릭 요건 / 성능 / 라벨 조정

**메트릭 활성 요건**
- Cilium: `prometheus.enabled=true` + `operator.prometheus.enabled=true`. `cilium_bpf_map_pressure`=cilium-agent.
- Hubble(옵션): `hubble.metrics.enabled`에 `drop`,`flow` 포함해야 `hubble_drop_total`. 미활성=빈 패널.
- cAdvisor: kubelet `/metrics/cadvisor`(kube-prometheus-stack 기본). conntrack: node-exporter `conntrack` collector(기본 ON).

**성능 (single-node 외 추가 레버)**
- L2의 device 변수(`^bond\d+$`, 기본 bond0+bond1)로 node_network_* 시리즈 축소. cilium IPv6 의도적 drop은 `cilium_drop_exclude_reason`(textbox)로 제외.
- L2 하위 Row collapsed(펼치기 전 미쿼리), timeseries maxDataPoints=600/interval=30s.
- L0 대규모면 recording rule 권장: `nodename:net_rx_drop:rate5m`, `nodename:softnet_drop:rate5m`, `node_pod_veth_drop:rate5m` → L0 instant.

**라벨 조정(외부 클러스터)**
- node-exporter=`nodename`(+instance), cilium·cAdvisor=`node`, 전역 `cluster`/`project`. 다르면 변수 쿼리/조인 라벨 일괄 치환.
- cilium reason 문자열은 버전차 → L2-csi의 `mtu_reason_regex`/`dsr_reason_regex` textbox 조정. cilium_drop은 node 단위(namespace 귀속=Hubble).
