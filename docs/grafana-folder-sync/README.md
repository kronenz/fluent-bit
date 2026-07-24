# Grafana 폴더 기준 org 동기화 (grafana-folder-sync)

> 문서: [구현 방안](docs/folder-sync-design.md) · [k8s Job 반영 가이드](docs/folder-sync-deploy-guide.md) (각각 drawio 구성도 포함)
> 인증: Secret `grafana-sync-auth` (id/password basic auth, server-admin)

> org 1(Main Org/Platform)의 **특정 폴더** 하위 대시보드를 Kubernetes CronJob이 주기적으로
> 대상 org들에 동일하게 복제한다. 일상 수작업은 "그 폴더에 대시보드를 넣는 것" 하나뿐.
> 검증: 2026-07-24 obs 클러스터 (org 6개 구조) e2e 통과.

## 1. 방안 개요

| 항목 | 내용 |
|---|---|
| 동기화 단위 | **폴더 트리** — org1의 `SYNC_FOLDER` 폴더와 **모든 중첩 하위폴더**(nested folders, Grafana 11+)의 대시보드 전부 (태그·uid 나열 불필요) |
| 폴더 계층 전파 | 대상 org에 같은 uid·제목·부모관계로 트리 재현. 폴더 이름변경·이동도 다음 주기에 반영 |
| 선택 방법 | GUI에서 대시보드를 그 폴더로 이동/저장하면 자동 편입, 빼면 대상 제외 |
| 전파 방식 | Grafana HTTP API upsert (`overwrite: true`) — provisioning/재기동 개입 없음 |
| uid 정책 | 원본 uid 그대로 (uid는 org 단위 유일이라 충돌 없음 → 멱등 upsert) |
| 폴더 정책 | 대상 org에 같은 uid·제목의 폴더를 자동 생성 |
| 멱등성 | 내용 동일하면 skip — Grafana version 불필요 증가 없음 |
| 변수 치환 | `VAR_DEFAULTS`(선택) — org별 templating 변수 `current`만 치환. 비우면 완전 동일 복제 |
| 실행 주기 | CronJob 10분 (+ 수동 즉시 실행 가능) |

## 2. 구성 요소

| 리소스 | 이름 (ns: monitoring) | 역할 |
|---|---|---|
| ConfigMap | `grafana-folder-sync-script` | 동기화 스크립트 (python, 표준 라이브러리만) |
| CronJob | `grafana-folder-sync` | 10분 주기 실행 |
| Secret 참조 | `kps-grafana` (`admin-user`/`admin-password`) | server-admin basic auth — SA 토큰은 org 종속이라 사용 불가 |

## 3. 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GRAFANA_URL` | `http://kps-grafana.monitoring.svc` | 대상 Grafana |
| `SYNC_FOLDER` | `platform` | org1에서 동기화할 폴더 **제목** |
| `TARGET_ORGS` | `2,3,4,5,6` | 대상 org id 목록 (콤마) |
| `VAR_DEFAULTS` | `{}` | org별 변수 기본값 치환. 예: `{"2":{"namespace":["dataops","spark-operator"]},"5":{"namespace":["hr"]}}` |

## 4. 배포·운영

| 작업 | 명령 |
|---|---|
| 배포 | `kubectl apply -f folder-sync-cronjob.yaml` |
| 즉시 실행 | `kubectl -n monitoring create job folder-sync-now --from=cronjob/grafana-folder-sync` |
| 로그 확인 | `kubectl -n monitoring logs job/folder-sync-now` |
| 폴더 변경 | CronJob env `SYNC_FOLDER` 수정 후 재적용 |
| 일시 중지 | `kubectl -n monitoring patch cronjob grafana-folder-sync -p '{"spec":{"suspend":true}}'` |

## 5. 동작 규칙 (알아둘 것)

| 상황 | 동작 |
|---|---|
| 대상 org에 같은 uid가 이미 있음 | 덮어씀 (`overwrite: true`) — org1이 정본 |
| 대상 org의 같은 uid가 **provisioned**(파일 관리) | 덮을 수 없어 skip + 실패 카운트 (로그에 표시) |
| org1에서 폴더 밖으로 이동/삭제한 대시보드 | 대상 org에 **남는다** (prune 없음 — 의도적. 삭제 전파가 필요하면 대상 org에서 수동 삭제) |
| 팀이 대상 org에서 대시보드를 수정 | 다음 주기에 org1 내용으로 **되돌아감** (내용이 달라졌으므로) |
| 대시보드가 참조하는 datasource | 대상 org에 **같은 uid**의 datasource가 있어야 동작 |

## 6. 사내 이관 치환표

| 항목 | obs 랩 값 | 사내 치환 |
|---|---|---|
| `GRAFANA_URL` | `http://kps-grafana.monitoring.svc` | 사내 Grafana 서비스/URL |
| admin Secret | `kps-grafana` | 사내 admin 자격 Secret (server-admin 필수) |
| `SYNC_FOLDER` | `platform` | Main Org에서 관리하는 실제 폴더 제목 |
| `TARGET_ORGS` | `2,3,4,5,6` | 사내 org id |
| `VAR_DEFAULTS` | `{}` (동일 복제) | org별 namespace 기본값이 다르면 JSON 매핑 입력 |
| 이미지 | `python:3.12-alpine` (docker.io) | 미러 레지스트리 경로 |
| 폴더가 여러 개면 | — | CronJob을 폴더별로 복제하거나 `SYNC_FOLDER`를 콤마 목록으로 확장(스크립트 filter 한 줄) |

## 7. obs 검증 결과 (2026-07-24)

| 검증 | 결과 |
|---|---|
| org1 `platform` 폴더 2개 → org 2~6 동기화 | ✅ synced=10 |
| 대상 org 폴더 자동 생성 (제목 `platform`) | ✅ |
| 재실행 멱등성 | ✅ 2회째 synced=0 skipped=10 |
| org1 수정 후 재실행 → 변경분만 전파 | ✅ synced=5 skipped=5 |
| 신규 대시보드 추가 → 그것만 전파 | ✅ synced=5 skipped=10 |
| **중첩 폴더**: `platform/category-a/category-a-sub`의 대시보드 동기화 | ✅ 트리(폴더 3개) 인식, 대상 org에 동일 계층(parentUid 일치) 재현 |
| 중첩 포함 멱등성 | ✅ 재실행 synced=0 skipped=15 |
| 태그·uid 수작업 없음 (폴더 이동만으로 편입) | ✅ |

관련: 더 큰 설계(멀티클러스터 타겟·git 이력·롤백)는 `.omc/plans/grafana-dash-sync-plan.md`
(보류 중), org provisioning 파이프라인은 `ops/obs-grafana-orgs/` 참고.
