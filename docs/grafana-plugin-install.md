# kube-prometheus-stack 73.1.0 — Bitbucket(SSH) 기반 Grafana 커스텀 플러그인 설치 가이드

## 1. 개요

이 가이드는 사내 Bitbucket 저장소에 Grafana 플러그인 zip 파일을 push해 두고, kube-prometheus-stack(73.1.0)에 포함된 Grafana 서브차트의 **initContainer**가 Pod 기동 시 **SSH key 인증으로 git clone** 하여 zip을 가져온 뒤 플러그인 디렉터리(`/var/lib/grafana/plugins`)에 압축 해제하는 방식으로 플러그인을 설치하는 절차를 설명합니다.

전체 흐름은 다음과 같습니다.

```
[플러그인 zip] → git push (SSH) → [Bitbucket 저장소]
                                        │  git clone (SSH key)
                                        ▼
    Grafana Pod 기동 시 initContainer(alpine/git)가 저장소 clone
                                        │  unzip
                                        ▼
         emptyDir 볼륨 (/var/lib/grafana/plugins) 에 압축 해제
                                        │
                                        ▼
         Grafana 컨테이너가 같은 볼륨을 마운트하여 플러그인 로드
```

HTTP raw URL 대신 SSH 방식을 쓰므로, Bitbucket 접근 정책이 SSH key 전용인 환경(HTTP Access 비활성)에서도 동작하며 플러그인 버전이 git으로 형상관리됩니다.

## 2. 사전 준비

- kube-prometheus-stack 73.1.0 이 설치되어 있거나 설치 예정 (Grafana 서브차트 포함, `grafana.enabled: true`)
- **본인 Bitbucket 계정에 등록된 SSH 공개키** (개인 SSH key 인증 방식 — username/password/token 미사용)
- 클러스터에서 Bitbucket SSH 포트로 아웃바운드 통신 가능
  - Bitbucket Server / Data Center: 기본 **7999/tcp**
  - Bitbucket Cloud: **22/tcp** (`bitbucket.org`)
- 설치할 플러그인 zip 파일 (예: `my-custom-panel-1.0.0.zip`)

zip 내부 구조는 최상위에 플러그인 ID 이름의 디렉터리가 오도록 구성하는 것이 안전합니다.

```
my-custom-panel-1.0.0.zip
└── my-custom-panel/
    ├── plugin.json
    ├── module.js
    └── ...
```

### SSH 공개키 Bitbucket 계정 등록

이 방식은 저장소별 토큰/Deploy Key가 아니라, **사용자 계정에 SSH 공개키를 등록**해 두면 해당 계정이 접근 가능한 저장소를 SSH로 clone/push 할 수 있는 구조입니다. 이미 등록되어 있다면 이 단계는 건너뜁니다.

key가 없다면 생성:

```bash
ssh-keygen -t ed25519 -C "your-email@example.com"
# 기본 경로 ~/.ssh/id_ed25519 (개인키) / ~/.ssh/id_ed25519.pub (공개키)
```

공개키(`~/.ssh/id_ed25519.pub`) 내용을 Bitbucket 계정에 등록:

- Bitbucket Server / Data Center: 우측 상단 프로필 → **Manage account → SSH keys → Add key**
- Bitbucket Cloud: 프로필 → **Personal settings → SSH keys → Add key**

등록 후 접속 테스트:

```bash
# Bitbucket Server (포트 7999)
ssh -T -p 7999 git@bitbucket.example.com
# Bitbucket Cloud
# ssh -T git@bitbucket.org
```

> initContainer는 이 계정의 **개인키**를 Secret으로 마운트해 clone 합니다. 개인키가 계정 전체 저장소 접근 권한을 가지므로, 보안상 가능하다면 Grafana 전용 서비스 계정을 만들어 그 계정에 별도 key를 등록해 사용하는 것을 권장합니다.

## 3. Bitbucket 에 플러그인 zip Push

플러그인 파일 전용 저장소(또는 기존 저장소의 디렉터리)를 사용합니다. SSH remote로 push 합니다.

```bash
# Bitbucket Server / Data Center
git clone ssh://git@bitbucket.example.com:7999/infra/grafana-plugins.git
# Bitbucket Cloud
# git clone git@bitbucket.org:<workspace>/grafana-plugins.git

cd grafana-plugins
mkdir -p plugins
cp ~/my-custom-panel-1.0.0.zip plugins/

git add plugins/my-custom-panel-1.0.0.zip
git commit -m "Add my-custom-panel 1.0.0"
git push origin main
```

> zip 파일이 크거나 자주 갱신된다면 Git LFS 사용을 권장합니다. (`git lfs track "*.zip"`) 단, LFS 사용 시 initContainer 이미지에도 git-lfs가 필요하므로 아래 5장의 참고사항을 확인하세요.

### 사전 접속 확인

계정에 등록한 key로 clone이 되는지 로컬에서 먼저 검증합니다.

```bash
GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes" \
  git clone --depth 1 ssh://git@bitbucket.example.com:7999/infra/grafana-plugins.git /tmp/test-clone
unzip -l /tmp/test-clone/plugins/my-custom-panel-1.0.0.zip
```

## 4. SSH key Secret 생성

Bitbucket 계정에 등록해 둔 공개키와 쌍을 이루는 **개인키**(`~/.ssh/id_ed25519`)와 known_hosts를 Kubernetes Secret으로 만들어 initContainer에 마운트합니다. username/token 은 사용하지 않으며 이 key 파일만으로 인증됩니다. Grafana가 설치된 네임스페이스(예: `monitoring`)에 생성합니다.

먼저 Bitbucket 호스트의 known_hosts 항목을 수집합니다.

```bash
# Bitbucket Server (포트 7999)
ssh-keyscan -p 7999 bitbucket.example.com > known_hosts
# Bitbucket Cloud
# ssh-keyscan bitbucket.org > known_hosts
```

Secret 생성:

```bash
kubectl -n monitoring create secret generic bitbucket-ssh-key \
  --from-file=id_ed25519=$HOME/.ssh/id_ed25519 \
  --from-file=known_hosts=./known_hosts
```

> ssh-keyscan 결과는 Bitbucket 공식 문서/관리자가 공지한 호스트키 지문과 대조하여 검증한 뒤 사용하는 것이 안전합니다. known_hosts를 쓰면 `StrictHostKeyChecking` 을 끄지 않아도 되어 MITM 위험을 줄일 수 있습니다.

## 5. kube-prometheus-stack values 설정

`values.yaml` 의 `grafana:` 하위에 다음을 추가합니다. 핵심은 네 가지입니다: 플러그인용 `emptyDir` 볼륨, SSH key Secret 볼륨, Grafana 컨테이너와 initContainer 양쪽의 볼륨 마운트, 그리고 clone + unzip 을 수행하는 initContainer 입니다.

```yaml
grafana:
  enabled: true

  # 1) 볼륨 정의: 플러그인 공유용 emptyDir + SSH key Secret
  extraVolumes:
    - name: custom-plugins
      emptyDir: {}
    - name: bitbucket-ssh
      secret:
        secretName: bitbucket-ssh-key
        defaultMode: 0400        # 개인키 권한 (필수)

  # 2) Grafana 컨테이너에 플러그인 디렉터리로 마운트
  extraVolumeMounts:
    - name: custom-plugins
      mountPath: /var/lib/grafana/plugins

  # 3) SSH 로 git clone 후 zip 압축 해제하는 initContainer
  extraInitContainers:
    - name: download-custom-plugins
      image: alpine/git:2.45.2
      securityContext:
        runAsNonRoot: true
        runAsUser: 472        # grafana 기본 UID와 맞춤
        runAsGroup: 472
      env:
        - name: GIT_REPO
          value: "ssh://git@bitbucket.example.com:7999/infra/grafana-plugins.git"
          # Bitbucket Cloud 예: "git@bitbucket.org:<workspace>/grafana-plugins.git"
        - name: GIT_BRANCH
          value: "main"
        - name: PLUGIN_ZIPS
          # 설치할 zip 목록 (공백 구분). 플러그인 추가 시 여기에 한 줄 추가
          value: >-
            plugins/my-custom-panel-1.0.0.zip
            plugins/sample-datasource-2.3.1.zip
            plugins/company-app-0.9.0.zip
        - name: PLUGINS_REVISION
          # zip 파일명 변경 없이 저장소 내용만 바뀐 경우, 이 값을 올려 Pod 롤아웃 강제
          value: "1"
        - name: GIT_SSH_COMMAND
          value: "ssh -i /ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/ssh/known_hosts -o StrictHostKeyChecking=yes"
        - name: HOME
          value: /tmp          # 비root 실행 시 ssh/git 이 참조할 HOME
      command: ["sh", "-c"]
      args:
        - |
          set -e
          echo "Cloning plugin repo via SSH..."
          git clone --depth 1 --branch "${GIT_BRANCH}" "${GIT_REPO}" /tmp/repo

          for z in ${PLUGIN_ZIPS}; do
            echo "Extracting ${z} ..."
            busybox unzip -o "/tmp/repo/${z}" -d /var/lib/grafana/plugins
          done

          ls -al /var/lib/grafana/plugins
          echo "Done."
      volumeMounts:
        - name: custom-plugins
          mountPath: /var/lib/grafana/plugins
        - name: bitbucket-ssh
          mountPath: /ssh
          readOnly: true

  # 4) 서명되지 않은(unsigned) 사내 플러그인인 경우 로딩 허용 (plugin ID 를 콤마로 나열)
  grafana.ini:
    plugins:
      allow_loading_unsigned_plugins: "my-custom-panel,sample-datasource,company-app"
```

참고사항:

- **이미지 구성**: `alpine/git` 은 Docker Hub의 alpine 조직이 공식 배포하는 이미지로, alpine 베이스에 **git + openssh 클라이언트**가 포함되어 있습니다. **unzip 은 별도 패키지 없이 alpine 기본 busybox 에 내장된 unzip 애플릿**(`busybox unzip`)을 사용하므로, 이 이미지 하나로 git(SSH clone)과 zip 압축 해제가 모두 처리됩니다. 추가 패키지 설치(`apk add`)가 필요 없어 폐쇄망에서도 동작합니다. 사내 레지스트리 미러 사용 시 `image` 를 미러 경로로 교체하세요.
- 저장소가 크다면 `--depth 1` shallow clone 만으로도 충분하며, 필요 시 sparse checkout(`git clone --filter=blob:none --sparse` 후 `git sparse-checkout set plugins`)으로 전송량을 더 줄일 수 있습니다.
- **Git LFS 로 zip을 관리하는 경우** `alpine/git` 에는 git-lfs가 없으므로 clone 결과가 포인터 파일이 됩니다. 이 경우 git-lfs가 포함된 이미지(예: `bitnami/git`)를 사용하고 clone 후 `git lfs pull` 을 수행하세요.
- Secret 의 `defaultMode: 0400` 이 없으면 ssh가 "permissions are too open" 오류로 key를 거부합니다.

## 6. 배포 및 적용

신규 설치:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 73.1.0 \
  -n monitoring --create-namespace \
  -f values.yaml
```

기존 릴리스 업그레이드:

```bash
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 73.1.0 \
  -n monitoring \
  -f values.yaml
```

values 변경으로 Grafana Deployment 스펙이 바뀌면 Pod가 재생성되면서 initContainer가 저장소를 다시 clone 하여 플러그인을 설치합니다.

## 7. 설치 검증

initContainer 로그로 clone / 압축 해제 성공 여부를 확인합니다.

```bash
kubectl -n monitoring logs deploy/kube-prometheus-stack-grafana \
  -c download-custom-plugins
```

Grafana 컨테이너 로그에서 플러그인 로드를 확인합니다.

```bash
kubectl -n monitoring logs deploy/kube-prometheus-stack-grafana -c grafana \
  | grep -i "my-custom-panel"
```

정상이라면 `Plugin registered` 류의 메시지가 보이고, unsigned 허용 설정 시 `Permitting unsigned plugin. This is not recommended` 경고가 함께 출력됩니다. 마지막으로 Grafana UI → Administration → Plugins 에서 플러그인이 Installed 상태인지 확인합니다.

## 8. 플러그인 여러 개 관리 및 향후 추가 가이드

### 저장소 디렉터리 규칙

향후 추가를 고려해 저장소를 다음 규칙으로 운영하는 것을 권장합니다.

```
grafana-plugins/
└── plugins/
    ├── my-custom-panel-1.0.0.zip
    ├── sample-datasource-2.3.1.zip
    └── company-app-0.9.0.zip
```

- 파일명에 **plugin ID + 버전**을 반드시 포함 (`<plugin-id>-<version>.zip`)
- 플러그인당 zip 은 **한 버전만 유지** (구버전은 커밋 히스토리로 관리) — 두 버전이 공존하면 같은 디렉터리에 중복 압축 해제되어 충돌합니다

### 방식 A — 명시 목록 관리 (기본, 권장)

5장 values 의 `PLUGIN_ZIPS` 에 zip 경로를 나열하는 방식입니다. 새 플러그인 추가 절차:

1. 새 zip 을 저장소에 push (`plugins/new-plugin-1.0.0.zip`)
2. values.yaml 수정 — 두 곳:
   - `PLUGIN_ZIPS` 에 `plugins/new-plugin-1.0.0.zip` 추가
   - unsigned 플러그인이면 `allow_loading_unsigned_plugins` 에 plugin ID 추가
3. `helm upgrade ... -f values.yaml` → env 변경으로 Pod 자동 롤아웃 → initContainer 가 전체 재설치

values 에 설치 목록이 명시되어 있어 **무엇이 설치되는지 형상으로 추적**되고, helm upgrade 만으로 롤아웃이 보장되는 것이 장점입니다. GitOps(ArgoCD 등) 환경과도 잘 맞습니다.

### 방식 B — 자동 검색 (values 수정 없이 추가)

저장소 `plugins/` 아래의 **모든 zip 을 자동으로 설치**하도록 initContainer 스크립트를 바꾸면, 플러그인 추가 시 git push 만으로 끝납니다. 5장의 `args` 를 다음으로 교체하고 `PLUGIN_ZIPS` env 는 제거합니다.

```yaml
      command: ["sh", "-c"]
      args:
        - |
          set -e
          echo "Cloning plugin repo via SSH..."
          git clone --depth 1 --branch "${GIT_BRANCH}" "${GIT_REPO}" /tmp/repo

          for z in /tmp/repo/plugins/*.zip; do
            echo "Extracting ${z} ..."
            busybox unzip -o "${z}" -d /var/lib/grafana/plugins
          done

          ls -al /var/lib/grafana/plugins
          echo "Done."
```

주의점 두 가지:

- values 가 바뀌지 않으므로 push 후 **Pod 롤아웃을 직접 트리거**해야 합니다. `kubectl -n monitoring rollout restart deploy/kube-prometheus-stack-grafana` 를 실행하거나, `PLUGINS_REVISION` env 값을 올려 helm upgrade 하세요.
- unsigned 플러그인은 여전히 `allow_loading_unsigned_plugins` 에 ID 추가가 필요합니다. 이 목록만큼은 values 수정이 불가피하므로, unsigned 플러그인이 많다면 방식 A 로 일원화하는 편이 관리가 단순합니다.

### 버전 업데이트 (공통)

1. 새 버전 zip push + **구버전 zip 은 같은 커밋에서 삭제** (`git rm plugins/my-custom-panel-1.0.0.zip`)
2. 방식 A: `PLUGIN_ZIPS` 파일명 갱신 → helm upgrade / 방식 B: rollout restart
3. emptyDir 은 Pod 재시작 시 초기화되므로 이전 버전 잔재는 자동으로 사라집니다

## 9. 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `Permission denied (publickey)` | Bitbucket 계정에 공개키 미등록, 또는 Secret의 개인키가 등록된 공개키와 쌍이 아님. `ssh-keygen -y -f id_ed25519` 로 공개키를 재생성해 등록본과 대조 |
| `Host key verification failed` | known_hosts 불일치. `ssh-keyscan` 재수집(포트 포함) 후 Secret 갱신 |
| `Load key ... bad permissions` | Secret 볼륨 `defaultMode: 0400` 누락 |
| `Connection timed out` / `Connection refused` | Bitbucket SSH 포트(Server 7999 / Cloud 22) 아웃바운드 차단. NetworkPolicy·방화벽 확인 |
| clone 은 됐는데 zip이 100~200바이트 텍스트 | Git LFS 포인터 파일. git-lfs 포함 이미지 사용 + `git lfs pull` 추가 |
| zip은 풀었는데 플러그인이 안 보임 | zip 내부 구조 확인 — `plugins/<plugin-id>/plugin.json` 경로가 되어야 함 |
| `plugin is unsigned` 로 로드 거부 | `grafana.ini.plugins.allow_loading_unsigned_plugins` 에 정확한 plugin ID 등록 |
| unzip 시 Permission denied | initContainer `runAsUser: 472` 설정 확인 (Grafana와 UID 일치) |

## 10. 참고: HTTP 방식과의 비교

Grafana 차트에는 `plugins: ["<zip URL>;<plugin-id>"]` 형식으로 차트 내장 install-plugins initContainer가 HTTP로 zip을 받게 하는 기능도 있으나, 인증 헤더를 붙일 수 없고 SSH는 지원하지 않습니다. Bitbucket 접근이 SSH key 전용인 환경에서는 본 가이드처럼 git clone 기반 커스텀 initContainer 방식이 표준적인 해법입니다.
