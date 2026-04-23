# systemd와 init 시스템 (systemd & Init)

> **TL;DR**
> 1. **systemd**는 PID 1로서 서비스 관리, 의존성 해결, 로깅(journald), cgroup 통합을 담당하는 현대 Linux의 init 시스템이다.
> 2. **Unit 파일**(.service, .timer, .socket 등)의 구조를 이해하면 서비스 배포, 트러블슈팅, 자동화를 효율적으로 수행할 수 있다.
> 3. **journalctl**은 구조화된 로그 검색 도구로, 장애 분석 시 시간/서비스/우선순위별 필터링이 핵심이다.

> **면접 빈출도**: ★★☆
> **예상 소요 시간**: 20min

---

## 핵심 개념

### init 시스템의 진화

```
SysVinit (전통)              Upstart (Ubuntu)           systemd (현대)
┌──────────────┐            ┌──────────────┐           ┌──────────────┐
│ /etc/init.d/ │            │ /etc/init/   │           │ /etc/systemd/ │
│ 순차 실행     │            │ 이벤트 기반   │           │ 병렬 실행     │
│ 런레벨(0-6)  │            │ 의존성 해결   │           │ 의존성 그래프  │
│ 쉘 스크립트   │            │ .conf 파일   │           │ .service 유닛 │
│ 느린 부팅     │            │ 부분 병렬화   │           │ 빠른 부팅     │
└──────────────┘            └──────────────┘           └──────────────┘
   RHEL 5 이하                Ubuntu 10~14               RHEL 7+, Ubuntu 16+
                                                         모든 현대 배포판
```

### systemd 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    systemd (PID 1)                       │
├─────────────┬──────────────┬──────────────┬─────────────┤
│  systemd-   │  systemd-    │  systemd-    │  systemd-   │
│  journald   │  logind      │  networkd    │  resolved   │
│  (로깅)     │  (세션관리)   │  (네트워크)   │  (DNS)      │
├─────────────┴──────────────┴──────────────┴─────────────┤
│                     Unit 관리                            │
│  .service │ .socket │ .timer │ .mount │ .target │ .path │
├─────────────────────────────────────────────────────────┤
│                   cgroup 통합                            │
│  system.slice │ user.slice │ machine.slice              │
├─────────────────────────────────────────────────────────┤
│                   D-Bus IPC                              │
└─────────────────────────────────────────────────────────┘
```

### Unit 파일 구조

Unit 파일 위치 (우선순위 순):
1. `/etc/systemd/system/` - 관리자 설정 (최우선)
2. `/run/systemd/system/` - 런타임 생성
3. `/usr/lib/systemd/system/` - 패키지 기본값

```ini
# /etc/systemd/system/my-app.service
[Unit]
Description=My Application Service
Documentation=https://docs.example.com
After=network-online.target postgresql.service    # 이후에 시작
Wants=network-online.target                       # 약한 의존 (없어도 시작)
Requires=postgresql.service                       # 강한 의존 (없으면 실패)

[Service]
Type=notify                          # 서비스 타입 (아래 표 참조)
User=appuser                         # 실행 사용자
Group=appgroup                       # 실행 그룹
WorkingDirectory=/opt/my-app
Environment=NODE_ENV=production      # 환경변수
EnvironmentFile=/etc/my-app/env      # 환경변수 파일

ExecStartPre=/opt/my-app/pre-start.sh   # 시작 전 실행
ExecStart=/opt/my-app/bin/server         # 메인 프로세스
ExecReload=/bin/kill -HUP $MAINPID       # reload 명령
ExecStop=/bin/kill -TERM $MAINPID        # 종료 명령

Restart=on-failure                   # 재시작 조건
RestartSec=5                         # 재시작 대기 시간
StartLimitIntervalSec=60             # 재시작 제한 기간
StartLimitBurst=3                    # 기간 내 최대 재시작 횟수

# 리소스 제한 (cgroup)
MemoryMax=512M                       # memory.max
CPUQuota=50%                         # cpu.max
TasksMax=100                         # pids.max

# 보안 강화
NoNewPrivileges=true
ProtectSystem=strict                 # / 읽기 전용
ProtectHome=true                     # /home 접근 불가
PrivateTmp=true                      # 독립 /tmp

[Install]
WantedBy=multi-user.target           # enable 시 심볼릭 링크 위치
```

### Service Type 비교

| Type | 동작 | 용도 |
|------|------|------|
| **simple** (기본) | ExecStart 프로세스가 메인 | 대부분의 서비스 |
| **forking** | 부모가 fork 후 종료, 자식이 메인 | 전통적 데몬 (PIDFile 필요) |
| **notify** | sd_notify()로 준비 완료 알림 | 초기화가 긴 서비스 |
| **oneshot** | 실행 후 종료, RemainAfterExit=yes | 초기화 스크립트 |
| **exec** | execve 성공 시 시작 완료 | simple보다 정확한 시작 감지 |

### Target (런레벨 대체)

```
SysVinit 런레벨          systemd Target
────────────────        ───────────────────────────
0 (halt)           →    poweroff.target
1 (single user)    →    rescue.target
3 (multi-user)     →    multi-user.target
5 (graphical)      →    graphical.target
6 (reboot)         →    reboot.target
```

### journald 로깅

```
┌─────────────────────────────────────────────┐
│              로그 수집 경로                    │
│                                              │
│  서비스 stdout/stderr ──→ journald           │
│  syslog() 호출 ─────────→ journald           │
│  커널 메시지 (kmsg) ─────→ journald           │
│  audit 로그 ────────────→ journald           │
│                              │               │
│                     ┌────────▼────────┐      │
│                     │ /run/log/journal │ 휘발 │
│                     │ /var/log/journal │ 영구 │
│                     └────────┬────────┘      │
│                              │               │
│                     rsyslog/syslog-ng        │
│                     (선택적 전달)              │
└─────────────────────────────────────────────┘
```

---

## 실전 예시

```bash
# === 서비스 관리 ===
systemctl start my-app.service       # 시작
systemctl stop my-app.service        # 중지
systemctl restart my-app.service     # 재시작
systemctl reload my-app.service      # 설정 리로드 (프로세스 유지)
systemctl status my-app.service      # 상태 확인

systemctl enable my-app.service      # 부팅 시 자동 시작
systemctl disable my-app.service     # 자동 시작 해제
systemctl is-enabled my-app.service  # 활성화 여부

# 서비스 실패 원인 확인
systemctl --failed                   # 실패한 서비스 목록
systemctl status my-app -l           # 상세 로그 포함

# Unit 파일 수정 후 반영
systemctl daemon-reload              # Unit 파일 재로드 (필수!)
systemctl restart my-app.service

# 의존성 확인
systemctl list-dependencies my-app.service
systemctl list-dependencies --reverse my-app.service  # 역방향

# === Unit 파일 관리 ===
# Unit 파일 위치 확인
systemctl show -p FragmentPath my-app.service

# override 파일로 기존 서비스 수정 (패키지 업데이트에도 안전)
systemctl edit my-app.service        # /etc/systemd/system/my-app.service.d/override.conf 생성
# 또는 직접 생성
mkdir -p /etc/systemd/system/my-app.service.d/
cat > /etc/systemd/system/my-app.service.d/override.conf << 'EOF'
[Service]
MemoryMax=1G
Environment=LOG_LEVEL=debug
EOF
systemctl daemon-reload

# === journalctl 로그 검색 ===
# 특정 서비스 로그
journalctl -u my-app.service                # 전체 로그
journalctl -u my-app.service -f             # 실시간 tail
journalctl -u my-app.service --since "1h ago"  # 최근 1시간
journalctl -u my-app.service --since "2024-01-01" --until "2024-01-02"

# 우선순위별 필터
journalctl -p err                           # error 이상만
journalctl -p warning -u my-app.service     # warning 이상

# 부팅별 로그
journalctl -b 0                             # 현재 부팅
journalctl -b -1                            # 이전 부팅
journalctl --list-boots                     # 부팅 목록

# 커널 로그 (dmesg 대체)
journalctl -k                               # 현재 부팅의 커널 메시지
journalctl -k -b -1                         # 이전 부팅의 커널 메시지

# JSON 출력 (파싱용)
journalctl -u my-app.service -o json-pretty

# 디스크 사용량 관리
journalctl --disk-usage                     # 로그 디스크 사용량
journalctl --vacuum-size=500M               # 500MB 이하로 축소
journalctl --vacuum-time=7d                 # 7일 이전 삭제

# === Timer (cron 대체) ===
# /etc/systemd/system/backup.timer
# [Timer]
# OnCalendar=*-*-* 02:00:00     # 매일 새벽 2시
# Persistent=true                # 놓친 실행 보완
systemctl list-timers --all                 # 타이머 목록

# === 부팅 분석 ===
systemd-analyze                              # 전체 부팅 시간
systemd-analyze blame                        # 서비스별 시간
systemd-analyze critical-chain               # 크리티컬 경로
systemd-analyze plot > boot.svg              # 시각화
```

---

## 면접 Q&A

### Q: systemd Unit 파일의 주요 섹션과 Type의 차이를 설명해주세요.

**30초 답변**:
Unit 파일은 [Unit](의존성, 설명), [Service](실행 방법, 재시작 정책), [Install](활성화 타겟) 세 섹션으로 구성됩니다. Type은 서비스의 시작 완료 감지 방식으로, simple은 ExecStart 실행 즉시, notify는 sd_notify() 호출 시, forking은 메인 프로세스가 fork 후 부모 종료 시 시작 완료로 판단합니다.

**2분 답변**:
[Unit] 섹션에서는 `After`/`Before`로 시작 순서, `Requires`(강한 의존)와 `Wants`(약한 의존)로 의존성을 정의합니다. [Service]에서 가장 중요한 것은 `Type`입니다. `simple`은 ExecStart 프로세스 자체가 메인이라 fork하지 않는 현대적 서비스에 적합합니다. `forking`은 전통적 데몬(apache httpd 등)이 fork 후 부모가 종료하는 패턴에 사용하며 `PIDFile`이 필요합니다. `notify`는 서비스가 초기화 완료 시 `sd_notify("READY=1")`을 호출하는 방식으로, PostgreSQL 등 초기화가 긴 서비스에 적합합니다. `Restart=on-failure`와 `RestartSec`, `StartLimitBurst`로 재시작 정책을 세밀히 제어합니다. [Install]의 `WantedBy=multi-user.target`은 `systemctl enable` 시 해당 target의 wants 디렉토리에 심볼릭 링크를 생성합니다. `systemctl edit`으로 override 파일을 만들면 패키지 업데이트 시에도 커스텀 설정이 보존됩니다.

**경험 연결**:
온프레미스에서 SysVinit 기반 RHEL 5에서 systemd 기반 RHEL 7로 마이그레이션하며 init.d 스크립트를 Unit 파일로 전환한 경험이 있습니다. 특히 의존성 관리와 재시작 정책이 크게 개선되어 장애 복구 시간이 단축되었습니다.

**주의**:
`systemctl daemon-reload`를 빠뜨리는 것은 실무에서도 흔한 실수입니다. Unit 파일 수정 후 반드시 실행해야 하며, 면접에서도 이 점을 언급하세요.

### Q: journalctl로 장애 원인을 분석하는 과정을 설명해주세요.

**30초 답변**:
장애 발생 시 `journalctl -u <service> --since "시각"` 으로 해당 시간대 로그를 확인하고, `-p err`로 에러 이상만 필터링합니다. 이전 부팅 로그가 필요하면 `-b -1`을 사용합니다.

**2분 답변**:
체계적 접근 방법입니다. 1단계: `systemctl --failed`로 실패한 서비스 식별. 2단계: `systemctl status <service> -l`로 최근 로그와 상태 확인. 3단계: `journalctl -u <service> --since "10min ago" -p warning`으로 시간대와 우선순위로 범위를 좁힙니다. 4단계: 서비스 간 연관이 있으면 `journalctl --since "10min ago" -p err`로 시스템 전체 에러를 봅니다. 5단계: 갑작스런 재부팅이었다면 `journalctl -b -1 -p emerg..err`로 이전 부팅의 치명적 에러를 확인합니다. 6단계: 커널 이슈(OOM, 하드웨어)가 의심되면 `journalctl -k`로 커널 메시지를 분석합니다. journald의 장점은 구조화된 데이터로 저장되어 `_SYSTEMD_UNIT`, `_PID`, `PRIORITY` 등 필드로 정밀 검색이 가능하다는 것입니다. `journalctl -o json-pretty`로 JSON 출력하여 외부 도구로 분석할 수도 있습니다.

**경험 연결**:
폐쇄망 환경에서는 중앙 로그 수집 시스템이 없는 경우가 많아, 각 서버에서 직접 journalctl로 장애를 분석해야 했습니다. 부팅 실패 시 rescue 모드에서 `journalctl -D /var/log/journal --list-boots`로 과거 부팅 로그를 복구하여 원인을 파악한 경험이 있습니다.

**주의**:
journalctl의 로그 영구 저장은 `/var/log/journal` 디렉토리가 존재해야 합니다. 기본적으로 일부 배포판에서는 휘발성(`/run/log/journal`)이므로, 영구 저장이 필요하면 `Storage=persistent` 설정을 확인하세요.

### Q: systemd의 cgroup 통합은 어떻게 동작하나요?

**30초 답변**:
systemd는 모든 서비스를 자동으로 cgroup에 배치합니다. system.slice(시스템 서비스), user.slice(사용자 세션), machine.slice(VM/컨테이너)로 구분하며, Unit 파일에서 MemoryMax, CPUQuota 등으로 리소스를 제한합니다.

**2분 답변**:
systemd는 부팅 시 cgroup 계층을 생성하고, 모든 프로세스를 slice → scope/service 구조로 배치합니다. `systemd-cgls`로 트리를 확인할 수 있습니다. Unit 파일의 [Service] 섹션에서 `MemoryMax=512M`은 cgroup의 `memory.max`, `CPUQuota=200%`은 `cpu.max`(2코어 분량), `TasksMax=100`은 `pids.max`에 매핑됩니다. `systemd-cgtop`으로 slice별 리소스 사용량을 실시간 모니터링할 수 있습니다. Docker를 systemd가 관리하면, 컨테이너는 `system.slice/docker-<id>.scope`에 배치됩니다. Kubernetes kubelet은 자체적으로 `kubepods.slice` 아래에 Pod를 배치하며, QoS 클래스별로 하위 slice를 구성합니다. 이 통합 덕분에 한 서비스의 리소스 폭주가 시스템 전체에 영향을 주는 것을 방지할 수 있습니다.

**경험 연결**:
온프레미스 서버에서 특정 배치 작업이 전체 CPU를 독점하여 SSH 접속이 불가능해진 경험이 있습니다. 이후 systemd Unit 파일에 CPUQuota와 MemoryMax를 설정하여 리소스 격리를 적용했습니다.

**주의**:
systemd의 `Slice=` 옵션으로 커스텀 slice에 서비스를 배치할 수 있습니다. 단순히 리소스 제한뿐 아니라 계층적 그룹 관리에 대해서도 언급하면 좋습니다.

---

## Allganize 맥락

- **서비스 관리**: AI 모델 서빙 데몬, 전처리 파이프라인 등을 systemd Unit으로 관리하여 자동 재시작과 의존성 해결
- **journalctl + 중앙 로깅**: journald 로그를 Fluent Bit/Fluentd로 수집하여 Elasticsearch/CloudWatch로 전송하는 파이프라인
- **리소스 보호**: systemd의 cgroup 통합으로 GPU 서버의 시스템 서비스(kubelet, containerd)에 최소 리소스를 보장
- **보안 강화**: Unit 파일의 ProtectSystem, NoNewPrivileges 등 보안 옵션으로 서비스 하드닝

---
**핵심 키워드**: `systemd` `unit-file` `journalctl` `systemctl` `service-type` `cgroup-slice` `daemon-reload` `timer`
