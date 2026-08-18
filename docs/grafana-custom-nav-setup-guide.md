# Grafana 좌측 메뉴 커스텀 구성 가이드 — 무빌드 nav app 플러그인 (폐쇄망용)

> 2026-08-18. obs 클러스터(kps, Grafana 12.0.0)에 실제 적용·검증한 절차를 폐쇄망 이식용으로
> 일반화한 문서. 이 가이드만으로 자립적으로 구성 가능하며, **인터넷·npm·webpack 빌드가 전혀
> 필요 없다** — 파일 3개(plugin.json / module.js / logo.svg)를 손으로 만들어 넣는 방식이다.

## 1. 개요와 원리

Grafana 좌측 사이드바에 **최상위 메뉴 섹션 + 대시보드 바로가기 하위 항목**을 추가한다.
설치만 하면 메뉴를 편집해주는 기성 플러그인은 v12에도 없고, **자작 app 플러그인**이 유일한 방법이다.

- app 플러그인의 `plugin.json` → `includes[]` 배열이 곧 메뉴다. 각 항목의 `path` 에
  `/d/<대시보드-uid>` 를 넣으면 React 페이지 없이 대시보드 바로가기가 된다.
- `module.js` 는 로더가 요구하는 형식만 갖추면 된다 — 손으로 쓴 AMD 스텁 1줄이면 충분하다
  (Grafana 의 SystemJS 로더가 AMD `define` 을 지원함을 12.0.0 에서 실측).
- 기본 위치는 "More apps" 밑이라 묻힌다 → `grafana.ini` 의 `[navigation.app_sections]` 로
  최상위로 끌어올린다.
- app 플러그인은 **org 단위로 enable** 해야 메뉴에 뜬다 → provisioning 파일로 자동화.

완성 시 메뉴 (obs 실측):

```
Home / Bookmarks / Starred
운영 대시보드            ← 섹션 클릭 = defaultNav 대시보드로 이동
  클러스터 개요
  인프라 노드 운영
  SLO · 에러버짓
  로그 개요
Dashboards / Explore / ...
```

## 2. 사전 확인 (폐쇄망에서 먼저 실측할 것)

| 확인 항목 | 방법 | 비고 |
|---|---|---|
| Grafana 버전 | `GET /api/health` 또는 로그인 화면 하단 | 이 가이드 실측 기준 12.0.0. 11.x 도 동일 구조 |
| 대시보드 uid | `GET /api/search?limit=100` 에서 `uid` 필드 | **메뉴에 넣을 uid 는 반드시 실측** — 추측 금지 |
| uid 유효성 | `GET /api/dashboards/uid/<uid>` → 200 | 404 인 uid 를 넣으면 메뉴는 뜨되 클릭 시 깨짐 |
| org 구성 | `GET /api/orgs` (server admin) | 다중 org 면 §6 org 격리 참고 |
| plugins 디렉터리 | `grafana.ini` `[paths] plugins` 또는 env `GF_PATHS_PLUGINS` | 기본 `/var/lib/grafana/plugins` |

```bash
# uid 목록 뽑기 (admin 계정)
curl -s -u admin:$GRAFANA_PW "$GRAFANA_URL/api/search?limit=100" \
  | python3 -c "import json,sys; [print(d['uid'],'|',d['title']) for d in json.load(sys.stdin) if d['type']=='dash-db']"
```

## 3. 플러그인 파일 작성 (전체 소스)

디렉터리 구조 — **최상위 디렉터리명 = 플러그인 id** 를 반드시 지킬 것:

```
miribit-nav-app/
├── plugin.json      # 메뉴 정의 정본
├── module.js        # 최소 AMD 스텁
└── img/logo.svg     # 메뉴 아이콘 (전 항목 공통)
```

### 3.1 `plugin.json`

```json
{
  "type": "app",
  "name": "운영 대시보드",
  "id": "miribit-nav-app",
  "info": {
    "description": "운영 대시보드 바로가기 네비게이션 (좌측 메뉴)",
    "author": { "name": "miribit" },
    "keywords": ["navigation", "dashboards"],
    "logos": { "small": "img/logo.svg", "large": "img/logo.svg" },
    "version": "1.0.0",
    "updated": "2026-08-18"
  },
  "includes": [
    {
      "type": "page",
      "name": "관측 포털",
      "path": "/d/dataops-portal",
      "role": "Viewer",
      "addToNav": true,
      "defaultNav": true
    },
    {
      "type": "page",
      "name": "클러스터 개요",
      "path": "/d/team-cluster-overview",
      "role": "Viewer",
      "addToNav": true
    }
  ],
  "dependencies": {
    "grafanaDependency": ">=11.0.0",
    "plugins": []
  }
}
```

- `path` 의 uid 는 §2 에서 실측한 값으로 교체. 항목은 필요한 만큼 추가.
- `defaultNav: true` 항목은 **하위 메뉴로 안 뜨고 섹션 제목 클릭의 목적지**가 된다(실측).
  대문 격 대시보드 하나에만 줄 것.
- `role` 은 노출 최소 권한 (`Viewer`/`Editor`/`Admin`).
- `id`(`miribit-nav-app`)를 바꾼다면 디렉터리명·§4 grafana.ini·§5 provisioning 까지 전부 일치시켜야 한다.

### 3.2 `module.js`

```js
/*
 * 무빌드 네비게이션 전용 app 플러그인.
 * 메뉴 항목은 전부 plugin.json includes(= /d/<uid> 링크)라 React 페이지가 없다.
 * Grafana 의 SystemJS 로더는 AMD define 을 지원한다(12.0.0 실측).
 */
define(["@grafana/data"], function (grafanaData) {
  "use strict";
  return { plugin: new grafanaData.AppPlugin() };
});
```

### 3.3 `img/logo.svg`

임의의 SVG 면 된다. 예시:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="6" y="6" width="24" height="16" rx="3" fill="#2a78d6"/>
  <rect x="34" y="6" width="24" height="16" rx="3" fill="#5aa0e6"/>
  <rect x="6" y="26" width="52" height="12" rx="3" fill="#87c1f0"/>
  <rect x="6" y="42" width="16" height="16" rx="3" fill="#5aa0e6"/>
  <rect x="26" y="42" width="32" height="16" rx="3" fill="#2a78d6"/>
</svg>
```

## 4. grafana.ini 설정

```ini
[plugins]
# 자작 플러그인은 서명이 없다 — id 를 명시해야 로드된다 (기존 값이 있으면 콤마로 이어붙임)
allow_loading_unsigned_plugins = miribit-nav-app

[navigation.app_sections]
# <플러그인 id> = <섹션 id> <정렬 가중치>
miribit-nav-app = root -1750
```

env 로 주는 형식(컨테이너)은:

```bash
GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=miribit-nav-app
GF_NAVIGATION_APP_SECTIONS_MIRIBIT_NAV_APP="root -1750"   # 섹션명에 - 가 있으면 ini 파일 방식 권장
```

### ★ 섹션 id 함정 (이번 적용에서 실제로 밟은 것)

**Grafana 12 에 섹션 id `dashboards` 는 존재하지 않는다.** 웹에 돌아다니는 예시
(`myapp = dashboards 100`)를 그대로 쓰면:

- 화면: 앱이 메뉴에서 **통째로, 무증상으로 사라진다** (More apps 에도 안 남는다)
- API: `GET /api/plugins/<id>/settings` 는 `enabled: true` 로 멀쩡해 보인다
- 유일한 단서는 서버 로그:
  `logger="navtree service" level=error msg="Plugin app nav id not found" pluginId=... navId=dashboards`

Grafana 12 유효 값 (navTree 실측 기준):

| 목적 | 섹션 id |
|---|---|
| **최상위 독립 섹션** (권장) | `root` |
| Dashboards 하위 | `dashboards/browse` |
| Alerting 하위 | `alerting` |
| Administration 하위 | `cfg` |

정렬 가중치: 코어 항목이 Home `-2000` / Bookmarks `-1900` / Starred `-1800` /
Dashboards `-1700` / Explore `-1600` 이므로, `-1750` 이면 Starred 와 Dashboards 사이.
양수를 주면 맨 아래쪽에 놓인다.

## 5. app enable — provisioning (org 단위)

app 플러그인은 **설치만으로는 메뉴에 안 뜬다.** org 마다 enable 이 필요하며, GUI 클릭 대신
provisioning 파일로 자동화한다. `<provisioning>/plugins/miribit-nav-app.yaml`:

```yaml
apiVersion: 1
apps:
  - type: miribit-nav-app
    org_id: 1        # enable 할 org 만 나열. 여러 org 면 항목 반복
```

provisioning 루트는 `grafana.ini` `[paths] provisioning` (기본 `/etc/grafana/provisioning`,
env `GF_PATHS_PROVISIONING`).

## 6. 배치 방법 (환경별)

### 6-A. VM / bare-metal / docker 단일 인스턴스

```bash
# 1. 플러그인 디렉터리 복사
cp -r miribit-nav-app /var/lib/grafana/plugins/
# 2. grafana.ini 에 §4 두 블록 추가
# 3. provisioning 파일 배치 (§5)
install -D -m 644 miribit-nav-app.yaml /etc/grafana/provisioning/plugins/miribit-nav-app.yaml
# 4. 재시작
systemctl restart grafana-server      # 또는 docker restart <container>
```

docker 면 볼륨 마운트로도 된다:

```yaml
volumes:
  - ./miribit-nav-app:/var/lib/grafana/plugins/miribit-nav-app:ro
  - ./provisioning/plugins:/etc/grafana/provisioning/plugins:ro
environment:
  GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS: miribit-nav-app
```

### 6-B. k8s + grafana helm 차트 — ConfigMap 방식 (가장 간단, 권장)

플러그인이 파일 3개뿐이라 ConfigMap 으로 통째로 배포 가능하다.

```bash
kubectl -n <ns> create configmap grafana-nav-app \
  --from-file=plugin.json=miribit-nav-app/plugin.json \
  --from-file=module.js=miribit-nav-app/module.js \
  --from-file=logo.svg=miribit-nav-app/img/logo.svg \
  --dry-run=client -o yaml > nav-app-cm.yaml     # 정본 파일로 보관 후 apply

kubectl -n <ns> create configmap grafana-nav-app-provisioning \
  --from-file=miribit-nav-app.yaml \
  --dry-run=client -o yaml > nav-app-prov-cm.yaml
```

helm values (grafana 차트 / kube-prometheus-stack 의 `grafana:` 하위):

```yaml
grafana:
  extraConfigmapMounts:
    # 플러그인 본체 — plugins 디렉터리의 "하위 디렉터리"로 마운트 (읽기전용이어도 로드됨)
    - name: nav-app-plugin-json
      configMap: grafana-nav-app
      mountPath: /var/lib/grafana/plugins/miribit-nav-app/plugin.json
      subPath: plugin.json
      readOnly: true
    - name: nav-app-module
      configMap: grafana-nav-app
      mountPath: /var/lib/grafana/plugins/miribit-nav-app/module.js
      subPath: module.js
      readOnly: true
    - name: nav-app-logo
      configMap: grafana-nav-app
      mountPath: /var/lib/grafana/plugins/miribit-nav-app/img/logo.svg
      subPath: logo.svg
      readOnly: true
    # org enable provisioning
    - name: nav-app-provisioning
      configMap: grafana-nav-app-provisioning
      mountPath: /etc/grafana/provisioning/plugins/miribit-nav-app.yaml
      subPath: miribit-nav-app.yaml
      readOnly: true
  grafana.ini:
    plugins:
      allow_loading_unsigned_plugins: miribit-nav-app   # 기존 값 있으면 콤마로 병합
    navigation.app_sections:
      miribit-nav-app: root -1750
```

주의: `subPath` 마운트는 ConfigMap 을 나중에 수정해도 **파드에 자동 반영되지 않는다** —
메뉴 변경 시 `kubectl apply` 후 `rollout restart` 필요 (어차피 grafana.ini 변경도 재시작 필요).

### 6-C. k8s — zip + initContainer 방식 (obs 에서 쓰는 형태)

플러그인 zip 을 사내 git/저장소에 두고 initContainer 가 clone·unzip 해 emptyDir 에 넣는
방식. 커스텀 플러그인이 여러 개고 이미 이런 파이프라인이 있다면 거기 편입하는 게 낫다.
zip 규격: **최상위 디렉터리 = 플러그인 id** (`miribit-nav-app/plugin.json ...`).
구현 예시는 `ops/obs-grafana-orgs/values-plugin-install.yaml` 참고.

## 7. 검증 (완료 선언 전 필수 — 브라우저 없이 가능)

```bash
# 1. 플러그인 로드 확인 — 로그에 이 3줄이 떠야 한다
#    "Plugin is unsigned" (warn) / "Permitting unsigned plugin" / "Plugin registered"
grep -iE "miribit-nav-app|nav id" <grafana-log> | head
# ★ "Plugin app nav id not found" 가 보이면 §4 섹션 id 오기 — 메뉴에서 무증상 소실 중

# 2. enable 확인
curl -s -u admin:$PW "$URL/api/plugins/miribit-nav-app/settings" | python3 -m json.tool | head -8
#    → "enabled": true, "pinned": true

# 3. 메뉴 실측 — index.html 의 bootdata 에서 navTree 파싱 (헤드리스 최종 검증)
curl -s -u admin:$PW "$URL/" -o /tmp/idx.html
python3 - << 'EOF'
import json
html = open('/tmp/idx.html').read()
s = html[html.find('navTree: ') + len('navTree: '):]
depth=0; instr=False; esc=False; end=0
for j,c in enumerate(s):
    if esc: esc=False; continue
    if c=='\\': esc=True; continue
    if c=='"': instr=not instr; continue
    if instr: continue
    if c=='[': depth+=1
    elif c==']':
        depth-=1
        if depth==0: end=j+1; break
def walk(nodes,d=0):
    for n in nodes:
        print('  '*d+f"{n.get('id','?')} | {n.get('text','')} | {n.get('url','')}")
        walk(n.get('children',[]),d+1)
walk(json.loads(s[:end]))
EOF
#    → plugin-page-miribit-nav-app | 운영 대시보드 | /d/... + 하위 항목들이 보여야 한다

# 4. 링크 전수 확인 — includes 의 uid 전부
for uid in dataops-portal team-cluster-overview; do
  echo "$uid -> $(curl -s -o /dev/null -w '%{http_code}' -u admin:$PW $URL/api/dashboards/uid/$uid)"
done   # 전부 200
```

다중 org 검증: `POST /api/user/using/<orgId>` 로 admin 의 현재 org 를 바꾼 뒤 3번을 반복하면
org 별 노출 여부를 실측할 수 있다 (basic auth 의 `X-Grafana-Org-Id` 헤더는 API 응답에만 먹고
bootdata 는 현재 org 를 따른다).

## 8. 함정 모음 (전부 실측)

| 함정 | 증상 | 대처 |
|---|---|---|
| 섹션 id `dashboards` (12 에 없음) | 메뉴에서 앱 무증상 소실, settings API 는 정상 | `root` 또는 `dashboards/browse`. 로그의 `Plugin app nav id not found` 확인 |
| app enable 누락 | 설치·로드 정상인데 메뉴 없음 | §5 provisioning (org 단위) |
| `defaultNav` 오해 | 대문 항목이 하위 메뉴에 안 보임 | 정상 동작 — 섹션 제목 클릭의 목적지가 된 것 |
| 다중 org + uid 불일치 | 다른 org 에서 링크 404 | enable 을 해당 org 만; org 별 uid 가 다르면 org 별 앱 분리 또는 uid 통일 |
| unsigned 미허용 | 로그 `plugin ... is unsigned` 후 미로드 | `allow_loading_unsigned_plugins` 에 id (기존 값에 콤마 병합) |
| zip 최상위 디렉터리 누락 | 플러그인 미인식 | zip 루트가 `<플러그인-id>/` 여야 함 |
| ConfigMap subPath 수정 미반영 | 메뉴 바꿨는데 그대로 | apply 후 rollout restart |
| 존재하지 않는 uid | 메뉴는 뜨나 클릭 시 Not found | §2 에서 uid 전수 실측 후 작성 |

## 9. 한계 (구조적 — 우회 불가)

- 메뉴 항목별 개별 아이콘 불가 — 앱 로고 1개가 공통 적용
- 코어 항목(Dashboards, Alerting 등)의 이름·순서 변경 불가
- org 별로 **다른 메뉴 구성** 불가 — `navigation.*` 는 인스턴스 전역, org 단위는 enable 여부만
- `role` 로 Viewer/Editor/Admin 노출 제어는 가능

## 10. 메뉴 변경 운영 절차 (요약)

1. `plugin.json` 의 `includes[]` 수정 (uid 는 `/api/dashboards/uid/` 200 실측 후)
2. 배치 방식대로 재배포 (6-A: 파일 교체 / 6-B: CM apply / 6-C: zip 재푸시)
3. Grafana 재시작 (k8s: `rollout restart`)
4. §7 의 navTree 파싱으로 반영 확인
