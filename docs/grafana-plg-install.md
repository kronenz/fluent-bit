# Grafana 커스텀 플러그인 설치 구성 — Bitbucket SSH-key 단독 환경

> 대상: kube-prometheus-stack **73.1.0** Grafana에 사내 Bitbucket 저장소의 플러그인 zip을
> SSH-key 인증 git clone initContainer로 설치하는 구성.
> 이 문서는 **사내 환경 전제**(아래 표)에 맞춘 최종본이다 — obs 랩 검증 구성에서
> known_hosts·git-passwd 를 제거하고 시크릿 키 이름을 실환경에 맞췄다.

## 1. 환경 전제

| 항목 | 값 | 비고 |
|---|---|---|
| 시크릿 | `bitbucket-ssh-key` (Opaque) | 키 이름 **`gitSshKey`** 단독 |
| known_hosts | **사용 안 함** | 호스트키 검증 비활성 (§5 트레이드오프) |
| git-passwd ConfigMap | **사용 안 함** | initContainer를 root로 실행하므로 불필요 (§4-③) |
| Bitbucket | SSH 포트 7999 (Server/DC) | Cloud면 22 |
| 이미지 | `alpine/git:2.45.2`, `busybox:1.36` | 사내 미러 레지스트리 경유 |
| 플러그인 | unsigned zip (최상위 `<plugin-id>/plugin.json`) | `allow_loading_unsigned_plugins` 필요 |

## 2. values 구성 (전문)

```yaml
grafana:
  securityContext:                 # pod 레벨
    runAsNonRoot: true
    runAsUser: 472
    runAsGroup: 472
    fsGroup: 472
    fsGroupChangePolicy: OnRootMismatch

  extraVolumes:                    # grafana 컨테이너에도 마운트되는 볼륨만
    - name: custom-plugins
      emptyDir: {}

  # ⚠ extraVolumes 는 secret 을 지원하지 않는다(조용히 emptyDir 로 렌더).
  #   initContainer 전용 볼륨은 반드시 extraContainerVolumes 로.
  extraContainerVolumes:
    - name: bitbucket-ssh
      secret:
        secretName: bitbucket-ssh-key
        defaultMode: 256           # 0o400 — root 실행이므로 소유자(root) 전용으로 최소화
        items:
          - key: gitSshKey         # 실제 시크릿의 키 이름
            path: id_ed25519       # 컨테이너에 보일 파일명 (/ssh/id_ed25519)

  extraVolumeMounts:
    - name: custom-plugins
      mountPath: /var/lib/grafana/plugins

  extraInitContainers:
    - name: download-custom-plugins
      image: <<registry.example.com>>/alpine/git:2.45.2
      securityContext:
        runAsUser: 0
        runAsNonRoot: false        # pod 의 runAsNonRoot: true 상속을 명시적으로 끊는다 (§4-①)
      env:
        - name: GIT_REPO
          value: "ssh://git@<<bitbucket.example.com>>:7999/infra/grafana-plugins.git"
        - name: GIT_BRANCH
          value: "main"
        - name: PLUGIN_ZIPS
          value: "plugins/my-custom-panel-1.0.0.zip"
        - name: GIT_SSH_COMMAND
          value: "ssh -i /ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
      command: ["sh", "-c"]
      args:
        - |
          set -e
          git clone --depth 1 --branch "${GIT_BRANCH}" "${GIT_REPO}" /tmp/repo
          for z in ${PLUGIN_ZIPS}; do
            busybox unzip -o "/tmp/repo/${z}" -d /var/lib/grafana/plugins
          done
          chown -R 472:472 /var/lib/grafana/plugins   # root 가 풀었으므로 소유권 정리
          ls -al /var/lib/grafana/plugins
      volumeMounts:
        - name: custom-plugins
          mountPath: /var/lib/grafana/plugins
        - name: bitbucket-ssh
          mountPath: /ssh
          readOnly: true

  grafana.ini:
    plugins:
      allow_loading_unsigned_plugins: "<<my-custom-panel>>"
```

## 3. obs 랩 검증본과의 차이

| 항목 | obs 랩 검증본 | 이 문서 (사내) | 변경 이유 |
|---|---|---|---|
| 시크릿 키 | `id_ed25519` + `known_hosts` | `gitSshKey` 단독 → `items:`로 리매핑 | 실환경 시크릿 형태 |
| 호스트키 검증 | `StrictHostKeyChecking=yes` + known_hosts | `no` + `/dev/null` | known_hosts 미사용 방침 |
| 실행 계정 | uid 472 (비root) | **root** | git-passwd 제거의 전제 (§4-③) |
| git-passwd CM | `/etc/passwd` subPath 마운트 | 없음 | root 는 passwd 엔트리 보유 |
| defaultMode | 288 (0440, fsGroup 그룹읽기) | 256 (0400) | root 는 소유자 권한으로 충분 |
| 키 복사 (`install -m 400`) | 필요 (0440→0400) | 불필요 | 0400 마운트를 ssh 가 그대로 수용 |
| chown 후처리 | 불필요 (472 가 직접 씀) | `chown -R 472:472` 추가 | root 가 푼 파일 소유권 정리 |

## 4. 왜 이렇게 구성하는가 (함정별 근거)

| # | 함정 | 증상 | 이 구성의 처리 |
|---|---|---|---|
| ① | pod `runAsNonRoot: true`가 컨테이너에 **필드 단위 상속** | `runAsUser: 0`만 쓰면 `container's runAsUser breaks non-root policy` (CreateContainerConfigError) | 컨테이너에 `runAsNonRoot: false` 명시 |
| ② | 차트 `extraVolumes`는 secret 분기 없음 | 에러 없이 **emptyDir로 렌더** → `/ssh` 가 빈 디렉터리 | `extraContainerVolumes` 사용 |
| ③ | `alpine/git`에 uid 472 passwd 엔트리 없음 | 비root 실행 시 `No user exists for uid 472` | **root 실행으로 원천 회피** (git-passwd 불필요) |
| ④ | ssh 개인키 권한 검사 | group/other 읽기 가능하면 `UNPROTECTED PRIVATE KEY` 거부 | `defaultMode: 256`(0400) + root 실행 조합으로 통과 |
| ⑤ | `defaultMode`의 YAML 8진수 표기 | `0400`/`0o400`은 문자열/오류 | **10진수** 256(=0o400), 288(=0o440) |
| ⑥ | 호스트키 검증 | known_hosts 없으면 `Host key verification failed` | 검증 비활성 (§5) |

## 5. 보안 트레이드오프

| 선택 | 영향 | 완화/대안 |
|---|---|---|
| `StrictHostKeyChecking=no` | 클러스터→Bitbucket 경로의 MITM 미탐지 | 폐쇄망 내부 통신이면 통상 수용. 강화 시: 시크릿에 `known_hosts` 키 추가(`ssh-keyscan -p 7999 <host>`) + `items:` 한 줄 추가 + `yes`로 변경 |
| initContainer root 실행 | 파드 내 root 프로세스 1개(수 초, clone·unzip 한정) | 볼륨 마운트는 시크릿·emptyDir 뿐이라 영향 반경 작음. PSA `restricted` 등으로 root 금지면 부록 A |
| SSH 개인키를 k8s Secret 보관 | etcd 암호화 여부에 의존 | 키는 대시보드/플러그인 저장소 **read-only 권한 계정**으로 한정 |

## 6. 검증 체크리스트

| # | 확인 | 명령 | 기대 |
|---|---|---|---|
| 1 | initContainer 로그 | `kubectl -n <ns> logs <pod> -c download-custom-plugins` | clone·unzip 성공, `Permission denied`/`No user exists` 없음 |
| 2 | 플러그인 소유권 | 〃 로그 말미 `ls -al` | `<plugin-id>/` 이 472 소유 |
| 3 | Grafana 로그 | `kubectl logs <pod> -c grafana \| grep -i plugin` | `Plugin registered pluginId=<id>` (+unsigned 경고는 정상) |
| 4 | Pod 상태 | `kubectl get pod` | Running, restart 0 |
| 5 | API 확인 | `wget -qO- localhost:3000/api/plugins \| grep <id>` (pod 내) | 플러그인 항목 존재 |
| 6 | 멱등성 | `kubectl rollout restart deploy/<grafana>` 후 1~5 재확인 | 동일 결과 |

## 7. 트러블슈팅

| 증상 | 원인 | 조치 |
|---|---|---|
| `Permission denied (publickey)` | 키·계정 불일치 | `ssh-keygen -y -f <키>`로 공개키 재생성 → Bitbucket 등록 키와 대조 |
| `/ssh/id_ed25519: No such file` | 시크릿 키 이름 불일치 | `items.key`가 실제 시크릿 키(`gitSshKey`)와 일치하는지 확인 |
| `/ssh` 가 빈 디렉터리 | secret 을 `extraVolumes`에 넣음 | `extraContainerVolumes`로 이동 (§4-②) |
| `runAsUser breaks non-root policy` | `runAsNonRoot: false` 누락 | 컨테이너 securityContext에 명시 (§4-①) |
| `violates PodSecurity ...` (admission 거부) | 네임스페이스 PSA가 root 금지 | 부록 A 의 비root 구성으로 전환 |
| 플러그인 unzip 됐는데 미로드 | zip 최상위 구조 / unsigned ID 오타 | `<plugin-id>/plugin.json` 구조와 `allow_loading_unsigned_plugins` 값 대조 |

## 부록 A — root 금지 환경(PSA restricted 등)용 비root 변형

root 컨테이너가 admission에서 거부되는 경우에만 사용. 이 경우 git-passwd 가 **다시 필요**해진다
(ssh 가 실행 uid 의 passwd 엔트리를 요구하는데 `alpine/git`엔 472 가 없음).

| 항목 | 변경 |
|---|---|
| securityContext | `runAsNonRoot: true` + `runAsUser/runAsGroup: 472` |
| defaultMode | `288`(0440) — fsGroup 그룹읽기 허용 |
| 키 사용 | `install -m 400 /ssh/id_ed25519 /tmp/id_ed25519` 후 `-i /tmp/id_ed25519` (ssh 의 0400 요구) |
| `HOME=/tmp` env 추가 | ssh 설정 탐색 경로 |
| git-passwd CM | `grafana:x:472:472:grafana:/tmp:/bin/sh` 한 줄 → `/etc/passwd` subPath 마운트 |
| chown 후처리 | 불필요 (472 가 직접 씀) |
