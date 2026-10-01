# 자동 CD 전체 설명 — 동작과 구성 이유

이 문서 하나로 현재 V1의 배포 흐름, 각 파일의 역할, 선택 이유와 한계를 이해할 수 있도록 정리했다. 기준은 2026-09-29 작업 트리의 코드이며, 파일 역할(9절)과 검사 위치(10절)는 2026-10-01에 갱신했다. 알림 구축의 상세는 [장애 알림 시스템](./v1-alerting.md), 성공 판정과 복구 상세는 [배포 검증 및 롤백](./v1-deployment-verification-and-rollback.md)에 둔다. 최초 연결·호스트 조회는 [운영 절차](v1-operations.md), 실제 시험 결과는 [구현 현황](v1-implementation-status.md), 대안 비교는 [기술 결정](technical-decisions.md)을 따른다.

2026-09-30 모니터링 확장: [CloudWatch + Prometheus + Grafana](v1-monitoring.md)를 추가했다. 앱 자동 CD는 네 서비스만 관리하고 PG는 별도 checkout·Compose 프로젝트로 운영한다. 호스트의 `cloudwatch-logs.enabled`가 있으면 deploy.sh가 `compose.cloudwatch.yaml`을 병합해 앱 로그를 CloudWatch로 전송한다. marker 활성화·해제도 설정 변경이므로 앱 재생성이 필요하다. 2026-10-01에는 Prometheus·Grafana를 별도 모니터링 EC2로 분리하기로 했다([TD-024](technical-decisions.md#td-024--모니터링-전용-인스턴스-분리), 2026-10-01 운영 확인). 앱 EC2에는 exporter와 수집 포트만 남는다.

## 1. 무엇을 자동화하는가

앱 팀은 소스를 수정하고 CI로 이미지를 만든다. Cloud는 배포할 버전을 Git에 기록하고, 단일 EC2에서 바뀐 서비스를 교체·검증한다. 검증에 실패하면 이번에 교체를 시도한 서비스를 이전 이미지로 복구한다.

| Compose 서비스 | 역할 | ECR 저장소 |
| --- | --- | --- |
| web | Nginx, TLS 종료, reverse proxy | keepgo-nginx |
| frontend | Next.js | keepgo-web |
| backend | Spring Boot | keepgo-backend |
| ai-api | FastAPI | keepgo-ai |

현재 조회 브랜치는 BE·AI의 `main`, FE의 `feat/v1`이다. 저장소·브랜치·workflow·게시 job·서비스 묶음의 실제 값은 [sources.json](../deployment/sources.json)에서 관리한다. FE는 한 커밋에서 frontend와 web 이미지를 함께 게시한다. Worker는 현재 Compose에 없다.

Cloud가 조회하므로 앱 저장소에 Cloud PR 생성·배포 호출 단계를 추가할 필요가 없다. 단일 호스트의 기존 Compose·SSM·ECR 구성을 활용하는 것이 현재 범위이며, 다중 호스트와 무중단 배포는 V2의 검토 대상이다.

## 2. 전체 흐름

```text
앱 저장소 (BE / FE / AI)
  기준 브랜치 push → CI → ECR에 소스 전체 SHA 태그로 이미지 게시
        │ GitHub API 조회
        ▼
GitHub runner: Auto release (EventBridge가 10분마다 실행, TD-022)
  release.sh → 최신 SHA와 Manifest 비교 → 해당 SHA의 CI·게시 job 확인
  → 서비스 묶음별 Manifest PR 생성 → squash 병합
  → 병합이 하나라도 있으면 Deploy production을 한 번 호출
        │ AWS OIDC 인증 + SSM SendCommand
        ▼
EC2: /opt/keepgo/cloud
  Cloud 커밋 checkout → deploy.sh
  → 잠금 → 변경 대상 계산 → 대상 이미지 전부 pull
  → 서비스별 교체·healthy 대기 → 연결 확인 → 60초 관찰
  → 성공 / 이전 이미지로 복구 / 수동 확인 필요

별도 GitHub runner: Health check (EventBridge가 5분마다 실행, Sentry Uptime으로 이전 예정)
  공개 URL 응답 확인 → 장애·복구 상태 변화 시 Discord
```

10분·5분은 조회 간격이며 배포·감지 완료 시간의 보장이 아니다. CI 실행, 배포 대기, 이미지 다운로드와 검증 시간이 추가된다. 이 레포에서는 GitHub schedule이 실행되지 않아 AWS EventBridge가 workflow를 호출한다([TD-022](technical-decisions.md#td-022--github-schedule-대신-eventbridge로-주기-실행)).

## 3. 새 이미지 선택과 dry_run

[auto-release.yaml](../.github/workflows/auto-release.yaml)이 [release.sh](../scripts/release.sh)를 실행한다.

1. `sources.json` 순서대로 기준 브랜치 최신 SHA를 조회한다.
2. 해당 서비스들의 Manifest SHA가 모두 같으면 건너뛴다.
3. 그 SHA·브랜치의 `push` CI 중 가장 최근 run이 완료·성공했는지 확인한다. 지정한 이미지 게시 job도 성공해야 후보로 삼는다.
4. 최신 Cloud `origin/main`에서 `release/<묶음 이름>-<SHA 앞 12자리>` 브랜치를 만들고 해당 서비스 SHA만 수정한다. PR 본문에 소스와 CI 링크를 남기고 squash 병합한다.
5. 하나라도 병합하면 `released=true`를 남긴다. 뒤 저장소 처리에서 실패해도 workflow는 앞에서 병합한 변경의 배포 호출을 시도한다.

CI 진행 중·실패·게시 job 생략은 다음 조회로 미룬다. API·Git·PR 명령 자체가 실패하면 스크립트가 종료된다. 다음 조회도 첫 저장소부터 시작하므로 같은 오류가 지속되면 뒤 저장소도 처리되지 않는다.

| 실행 방식 | 자동 배포 스위치 | 결과 |
| --- | --- | --- |
| 정기 실행 / 수동 `dry_run=false`(기본값) | `AUTO_DEPLOY_ENABLED=true` 필요 | 후보가 있으면 PR 생성·병합·배포 호출 |
| 수동 `dry_run=true` | 꺼져 있어도 실행 | 실제 API 조회와 후보 출력만. PR·병합·배포·실패 Discord 없음 |
| WSL·Linux의 `DRY_RUN=1 bash scripts/release.sh` | GitHub Variable을 읽지 않음 | 로컬 파일 기준 API 조회만. DRY_RUN 없는 로컬 실행은 거부 |

Actions의 checkout은 `ref: main`으로 고정돼 있다. Run workflow에서 다른 브랜치를 선택해도 실행할 release.sh·Manifest·sources는 main에서 가져온다. 아직 병합하지 않은 스크립트를 확인하려면 해당 로컬 checkout에서 DRY_RUN을 사용한다. dry_run은 API·후보 판단을 확인하며 Git 쓰기·PR 권한·실제 병합·ECR pull은 검증하지 않는다.

**구성 이유:** `gh`와 `jq`로 현재의 GitHub 호출·JSON 수정을 처리한다. 로직을 release.sh로 분리하면 YAML은 실행 순서가 되고 로컬에서도 확인할 수 있다. Actions dry_run은 자동 배포를 켜기 전에 runner 환경에서 후보를 볼 수 있게 한다. [TD-009](technical-decisions.md#td-009--새-이미지-감지-cloud-조회-vs-앱-저장소가-pr-생성), [TD-010](technical-decisions.md#td-010--조회병합-로직을-어디에-쓸-것인가)

## 4. Manifest PR과 배포 연결

[production-manifest.json](../deployment/production-manifest.json)은 네 서비스의 **목표 이미지 SHA**만 기록한다. PR은 무엇을 배포하려 했는지 Git 이력에 남긴다. 이미지 digest와 실제 실행 상태는 이 파일에 저장하지 않는다.

`GITHUB_TOKEN`으로 병합한 push는 후속 push workflow를 실행하지 않으므로 Auto release가 `workflow_dispatch`로 Deploy production을 직접 호출한다. 현재 GitHub 문서상 이 토큰으로 만든 PR의 `opened/synchronize/reopened` 검사 실행은 승인 대기 상태로 생성된다. 현재 스크립트는 Cloud PR 검사를 기다리지 않고 병합을 요청한다. 필수 검사·리뷰 도입 시 토큰, 검사 실행, 병합 대기와 배포 호출 시점을 함께 바꿔야 한다. [GitHub 토큰과 workflow 실행](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)

사람이 `main`의 Manifest·`compose.yaml`·`compose.cloudwatch.yaml`·`scripts/deploy.sh`·`scripts/prepare-runtime.py`를 바꾸면 자동 배포 스위치가 켜져 있을 때 push로 배포한다. 수동 Deploy production은 스위치가 꺼져 있어도 실행된다. 그 외 파일만 바꾸는 push는 배포 트리거가 아니다.

**구성 이유:** 앱별 버전 변경을 추적 가능한 Git 이력으로 남기고 실행 주체를 Cloud로 모은다. PR 병합은 목표 변경이며 운영 반영 성공을 뜻하지 않는다.

## 5. EC2에서의 교체 과정

[deploy-production.yaml](../.github/workflows/deploy-production.yaml)은 production Environment의 AWS 역할을 OIDC로 사용한다. 계정을 확인한 뒤 SSM으로 기존 EC2에 명령을 보내고, workflow의 Cloud SHA를 `/opt/keepgo/cloud`에 checkout해 [deploy.sh](../scripts/deploy.sh)를 실행한다.

Auto release는 `main`을 지정해 배포를 호출한다. 그 배포가 선택한 커밋에는 여러 서비스의 병합 결과가 들어갈 수 있다. 배포 대상은 PR diff가 아닌 EC2 실제 상태와 해당 커밋의 설정 차이로 계산한다.

EC2에서는 잠금을 잡고 Secret을 자동 조회·검증한 후 runtime 파일을 갱신한다. 조회·검증·저장에 실패하면 컨테이너 교체 전에 중단한다. Compose 설정 해시와 env·JWT 적용 기록으로 변경 대상을 정하고, 이미지를 모두 받은 뒤 서비스별로 교체·검증한다. 실패하면 이전 이미지 복구를 시도한다. 정확한 검사 순서·기준·종료 결과는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md)에 둔다.

**구성 이유:** 사전 pull로 이미지 누락 때문에 정상 컨테이너를 먼저 중지하는 일을 줄이고, 서비스별 교체로 실패 지점을 확인한다. Compose 해시를 활용해 별도 현재 버전 JSON을 유지하지 않는다. `--no-deps`는 의존 서비스의 추가 기동을 막는다. [TD-008](technical-decisions.md#td-008--최소-구성으로-재작성-전-서비스-자동-cd), [TD-012](technical-decisions.md#td-012--배포-검증과-롤백-방식)

GitHub 배포 workflow의 concurrency와 호스트 잠금은 서로 다른 범위다. 호스트 잠금은 deploy.sh 내부에 있고 앞서 수행하는 Git checkout까지 보호하지 않는다. SSM 시간 초과·수동 작업 후에는 기존 원격 명령 종료를 확인해야 한다.

## 6. 정상 판정의 범위

기동 후 healthy, 서비스 간 연결, 짧은 재시작 관찰을 통과해야 성공으로 처리한다. 외부 HTTP 감시는 별도 workflow다. 각 검사의 정상 기준과 확인하지 못하는 범위는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 3절에 둔다.

## 7. 실패 복구와 차단

교체·검증 실패 시 교체를 시도한 서비스를 역순으로 이전 이미지에 되돌리고 실패 SHA를 차단한다. 이미지 복구는 설정·Secret·DB 복구와 다르며 FE 묶음의 원자적 복구도 보장하지 않는다.

종료 코드, 실제 차단 범위, 수동 롤백과 재배포 절차는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 4~6절을 따른다. 정상 버전 유지와 반복 실패 억제를 위한 선택이다.

## 8. 알림과 외부 감시

배포가 자동 복구되면 배포 실패 알림을 생략하고, 복구되지 않은 실패와 공개 URL의 장애·복구 변화를 팀 Discord로 알린다. 외부 감시는 자동 배포 스위치와 별개로 동작하며 복구 명령을 실행하지 않는다.

설정·구축 순서, 검사 기준, 알림 조건, 중복 제어와 수신 시험은 [장애 알림 시스템 구축](./v1-alerting.md)에 둔다.

## 9. 파일과 상태의 위치

2026-10-01 `feat/v1-central-cd-prep` 기준이다. main에 아직 들어가지 않은 파일은 따로 표시했다. 각 검사가 무엇을 확인하는지는 [10절](#10-무엇을-어디서-확인하나)에 모았다.

### 9.1 배포 자동화 (GitHub Actions·스크립트)

| 파일 | 실행 위치·시점 | 역할 |
| --- | --- | --- |
| [auto-release.yaml](../.github/workflows/auto-release.yaml) | runner. EventBridge가 10분마다 호출(TD-022), 수동 실행·dry_run 가능 | `AUTO_DEPLOY_ENABLED` 확인 → release.sh 실행 → 병합이 있으면 Deploy production 호출 → 실패 시 Discord |
| [release.sh](../scripts/release.sh) | runner (로컬은 `DRY_RUN=1`만) | 저장소별 최신 SHA 조회, 그 SHA의 CI·게시 job 성공 확인, Manifest 수정·형식 검사, release PR 생성·squash 병합. 커밋에 `[skip ci]`를 넣어 release PR의 Validate run을 만들지 않는다 |
| [deploy-production.yaml](../.github/workflows/deploy-production.yaml) | runner. main push 중 배포 관련 파일이 바뀔 때, 또는 workflow_dispatch(Auto release 호출·수동) | 변수·AWS 계정 확인 → OIDC 인증 → SSM으로 앱 EC2에서 Cloud 커밋 checkout과 deploy.sh 실행 → 종료 코드 판정 → 자동 복구되지 않은 실패만 Discord |
| [deploy.sh](../scripts/deploy.sh) | 앱 EC2, root (SSM) | 사전 검사 → Secret 준비 → 바뀐 서비스 계산 → pull → 순서대로 교체 → 연결 확인·60초 관찰 → 실패 시 롤백·차단 → 오래된 이미지 정리. 종료 코드 0 성공 / 1 복구됨 / 2 사람 확인 |
| [prepare-runtime.py](../scripts/prepare-runtime.py) | 앱 EC2 (deploy.sh가 호출) | Secrets Manager → `backend.env`·`ai.env`·JWT PEM. 필수 키·PEM 형식 검사, 목록에 있는 키만 전달. 서비스별 적용 기록(`--check-applied`·`--record-applied`)으로 env·JWT 변경을 감지 |
| [check-manifest.jq](../scripts/check-manifest.jq) | release.sh, Validate | Manifest 형식의 단일 기준 |
| [notify-discord.sh](../scripts/notify-discord.sh) | runner | 제목·내용·Actions 실행 링크를 Discord Webhook으로 보낸다. Webhook이 없으면 경고만 남긴다 |
| [health-check.yaml](../.github/workflows/health-check.yaml) | runner. EventBridge가 5분마다 호출 | 공개 주소 외부 감시, 상태가 바뀔 때만 Discord. Sentry Uptime으로 이전 예정([TD-023](technical-decisions.md#td-023--외부-감시-유지-sentry-uptime으로-이전)) |
| [validate.yaml](../.github/workflows/validate.yaml) | runner. main 대상 PR, main push | 설정·스크립트·모니터링 정적 검사와 단위 테스트 |

### 9.2 배포 대상과 서버 구성 (Compose)

| 파일 | 실행 위치 | 역할 |
| --- | --- | --- |
| [production-manifest.json](../deployment/production-manifest.json) | — | Git에 기록한 서비스 4개의 목표 이미지 SHA. release.sh가 바꾸고 deploy.sh가 읽는다 |
| [sources.json](../deployment/sources.json) | — | 앱 저장소별 조회 브랜치·workflow·게시 job·서비스 묶음(FE는 frontend·web 함께) |
| [compose.yaml](../compose.yaml) | 앱 EC2 (deploy.sh) | web(Nginx)·frontend·backend·ai-api의 이미지 태그, healthcheck, 메모리 상한, bind mount(TLS·ACME·uploads·JWT), env_file, 수집 포트(backend 8081, ai-api 9464) |
| [compose.cloudwatch.yaml](../compose.cloudwatch.yaml) | 앱 EC2 | `/opt/keepgo/runtime/cloudwatch-logs.enabled`가 있을 때 deploy.sh가 병합. 로그 드라이버를 awslogs로 바꾼다 |
| [compose.exporters.yaml](../compose.exporters.yaml) | 앱 EC2, 수동 (`keepgo-exporters` 프로젝트) | node-exporter(9100)·blackbox-exporter(9115). 앱 보안 그룹에서 모니터링 SG만 허용 |
| [compose.monitoring.yaml](../compose.monitoring.yaml) | 모니터링 EC2, 수동 (`keepgo-monitoring` 프로젝트) | Prometheus(127.0.0.1:9090), Grafana(127.0.0.1:3001), Caddy(443, Grafana HTTPS) |

### 9.3 AWS 인프라 (CloudFormation, 수동 배포)

| 파일 | 만드는 것 |
| --- | --- |
| [github-dispatch.yaml](../infrastructure/github-dispatch.yaml) | EventBridge 예약 규칙 2개(Auto release 10분, Health check 5분), GitHub API 호출 대상, 토큰 연결, IAM 역할, 호출 실패 알람(SNS 연결 시) |
| [monitoring.yaml](../infrastructure/monitoring.yaml) | 앱 로그 그룹, SNS 알림 토픽(이메일), 앱 EC2의 로그·지표 전송 권한, CloudWatch 알람 6개 |
| [monitoring-host.yaml](../infrastructure/monitoring-host.yaml) | 모니터링 EC2(t4g.small), 보안 그룹, 앱 SG의 수집 포트 허용 4개, IAM, Grafana용 고정 IP, 상태·디스크 알람 |

### 9.4 모니터링 설정 (`monitoring/`)

| 파일 | 역할 |
| --- | --- |
| [prometheus/prometheus.yml](../monitoring/prometheus/prometheus.yml) | 수집 대상: Prometheus 자신, node, blackbox, 서비스 4개 내부 health(blackbox 경유), 앱 지표(file_sd) |
| [prometheus/rules/application-alerts.yml](../monitoring/prometheus/rules/application-alerts.yml) | 앱 경고 8개의 임계치·지속 시간 원본 |
| [prometheus/rules/application-recording.yml](../monitoring/prometheus/rules/application-recording.yml) | 앱 지표 기록 규칙 8개 |
| [prometheus/targets/application.json](../monitoring/prometheus/targets/application.json) | 앱 지표 수집 대상. 앱 계측 확인 후 채운다. 예시는 [examples/application-targets.json](../monitoring/examples/application-targets.json) |
| [blackbox/blackbox.yml](../monitoring/blackbox/blackbox.yml) | HTTP 2xx 검사 모듈 |
| [grafana/provisioning/datasources/prometheus.yml](../monitoring/grafana/provisioning/datasources/prometheus.yml) | Grafana의 Prometheus 연결 |
| [grafana/provisioning/alerting/rules.json](../monitoring/grafana/provisioning/alerting/rules.json) | 내부 서비스 비정상·수집 불가 알림 (3분 지속) |
| [grafana/provisioning/alerting/application.json](../monitoring/grafana/provisioning/alerting/application.json) | Prometheus 앱 경고를 Discord로 전달하는 규칙 (render 스크립트가 생성) |
| [grafana/provisioning/alerting/notifications.yml](../monitoring/grafana/provisioning/alerting/notifications.yml) | Discord 연락처, 알림 묶음, 지속 장애 4시간마다 재알림 |
| [grafana/dashboards/](../monitoring/grafana/dashboards/) | 대시보드 4개: 인프라·health 개요, 앱 HTTP, Backend JVM·DB 풀, AI 제공자·스트리밍 |
| [caddy/Caddyfile](../monitoring/caddy/Caddyfile) | Grafana를 Let's Encrypt 인증서로 HTTPS 공개([TD-025](technical-decisions.md#td-025--grafana를-https-서브도메인으로-공개)). **main 미반영** |
| [cloudwatch-agent.json](../monitoring/cloudwatch-agent.json) | 앱 EC2의 메모리·루트 디스크 사용률을 CloudWatch로 |
| [render-app-monitoring.py](../scripts/render-app-monitoring.py) | 앱 대시보드 3개와 application.json의 생성 원본. Validate가 `--check`로 커밋된 결과와 같은지 확인 |

### 9.5 테스트 (`tests/`, Validate에서 실행)

| 파일 | 확인하는 것 |
| --- | --- |
| [test_runtime.py](../tests/test_runtime.py) | prepare-runtime.py: 조회·검증 실패 시 기존 파일 보존, 필수 키 누락 중단, 선택 키 전달 범위, env·JWT 변경 감지, 오류 메시지의 값 노출 차단 |
| [test_runtime_deploy.py](../tests/test_runtime_deploy.py) | 실제 deploy.sh를 가짜 Docker·AWS로 실행: 호스트 파일 누락, pull 실패 후 재시도, 롤백 후 기록, 변경 없는 배포의 재생성 방지, 차단 서비스 처리 |
| [test_monitoring.py](../tests/test_monitoring.py) | 로그 옵션 병합, 모니터링 호스트 분리와 관리 포트 loopback, 앱 EC2는 수집 포트만 게시, 대시보드·알림의 데이터소스 일치 |
| [prometheus/application.test.yml](../tests/prometheus/application.test.yml) | 앱 경고 규칙을 실제 PromQL 엔진으로 시험 (무트래픽·계측 누락·오류·지연·counter reset) |

### 9.6 서버의 상태·호스트 파일

앱 EC2 `/opt/keepgo/state/`에는 `deploy.lock`(잠금), `failed-images`(차단 서비스·SHA), `history.log`(시간·Cloud 커밋·결과·교체 서비스), `applied-config-<서비스>`(마지막 배포가 적용한 컨테이너 ID·설정 해시), `runtime-applied-backend.json`·`runtime-applied-ai-api.json`(정상 적용한 컨테이너 ID·파일 지문, 0600)이 생긴다. 적용 기록은 재시도 시 env·JWT 변경을 놓치지 않고, 변경 없는 배포에서 재생성하지 않기 위한 것이다. 이전 이미지 태그는 실행 중 메모리에 보관하므로 프로세스 중단 후 자동 복구를 재개할 상태 파일은 없다.

Secret·JWT는 `/opt/keepgo/runtime/`, TLS는 `/opt/keepgo/tls/`, ACME는 `/opt/keepgo/acme/`, 업로드는 `/opt/keepgo/data/uploads/`를 사용한다. CloudWatch 로그 전송 스위치는 `/opt/keepgo/runtime/cloudwatch-logs.enabled`다. 모니터링 EC2는 `/opt/keepgo/runtime/monitoring-host.env`(앱 EC2 private IP, Grafana 도메인)를 쓴다. 인증 값과 호스트 상태는 Git에 넣지 않는다. 결정 이유는 [TD-016](technical-decisions.md#td-016--배포-시-secret-자동-조회와-실패-처리)에 있다.

## 10. 무엇을 어디서 확인하나

검사가 단계마다 흩어져 있어 한곳에 모은다. 실패 시 결과 이름은 deploy.sh의 `결과:` 값이다.

### 10.1 변경을 병합할 때 — Validate

사람이 올린 main 대상 PR과 main push에서 실행한다. release PR은 `[skip ci]`로 실행하지 않는다(TD-017). main에 보호 규칙이 없어 실패해도 병합은 막히지 않으며, 결과를 보고 병합하는 팀 규칙에 의존한다.

| 검사 | 확인하는 것 |
| --- | --- |
| Manifest·sources | 서비스 4개의 40자리 SHA, web·frontend SHA 일치, sources.json이 4개 서비스를 정확히 한 번씩 담당 |
| Compose | compose.yaml(+cloudwatch), compose.monitoring.yaml, compose.exporters.yaml 구조. env 값은 읽지 않는다 |
| 모니터링 | render 결과 일치, `promtool check config`, 앱 경고 규칙 시험, blackbox 설정, Caddyfile 문법, test_monitoring |
| 스크립트·workflow | test_runtime·test_runtime_deploy, `bash -n`, shellcheck, actionlint |

### 10.2 새 버전을 고를 때 — release.sh

| 확인 | 통과하지 못하면 |
| --- | --- |
| 기준 브랜치의 최신 SHA가 Manifest와 다른가 | "최신", 다음 저장소로 |
| 그 SHA의 가장 최근 CI가 성공했고 이미지 게시 job도 성공했나 | "이미지가 아직 없다", 다음 조회에서 다시 확인 |
| 바꾼 Manifest가 형식 검사를 통과하나 | 병합하지 않고 멈춤, 🚨 자동 릴리스 실패 |
| GitHub API·Git 호출 | 오류면 멈춤, 🚨 자동 릴리스 실패 |

### 10.3 배포를 시작할 때 — deploy-production.yaml

| 확인 | 통과하지 못하면 |
| --- | --- |
| main 브랜치인가, push면 `AUTO_DEPLOY_ENABLED=true`인가 | skip |
| 배포 변수가 있고 인스턴스 ID 형식이 맞나, 기대한 AWS 계정인가 | 실패, 🚨 운영 배포 실패 |
| SSM 결과: 성공+0 / 실패+1 / 그 외 | 0 성공, 1 자동 복구로 보고 알림 없음, 그 외 🚨 운영 배포 실패 |

### 10.4 앱 EC2에서 배포할 때 — deploy.sh

| 순서 | 확인 | 실패 결과 | 운영 영향 |
| --- | --- | --- | --- |
| 1 | 다른 배포가 진행 중인가 (flock) | 종료 코드 2 | 없음 |
| 2 | Manifest SHA가 40자리인가 | `invalid_manifest` | 없음 |
| 3 | TLS 두 파일(비어 있지 않음), ACME·uploads 디렉터리 | `host_files_missing` | 없음 |
| 4 | Secret 조회, 필수 키(BE DB 계정, AI Google·NAVER 키), JWT PEM 형식 | `runtime_prepare_failed` | 없음. 파일도 바꾸지 않는다 |
| 5 | `compose config`, 설정 해시 계산 | `invalid_compose` | 없음 |
| 6 | 서비스별 적용 기록과 비교해 바뀐 서비스 계산, 차단 목록이면 건너뜀 | 바뀐 게 없으면 상태만 확인 → `unchanged` / `unchanged_but_unhealthy` | 없음. 차단으로 건너뛰어도 `unchanged`로만 남는다(TODO) |
| 7 | ECR 로그인, 대상 이미지 전부 pull | `ecr_login_failed` / `pull_failed` | 없음. 교체 전에 끝낸다 |
| 8 | 서비스를 하나씩 교체하고 300초 안에 healthy | 롤백 + 차단 → `rolled_back` (실패 시 `rollback_failed`) | 롤백 성공 시 이전 버전 유지 |
| 9 | 전체 연결: 4개 healthy, Nginx→Frontend, Backend→AI·RDS TCP, `127.0.0.1/healthz` | 〃 | 〃 |
| 10 | 60초 동안 교체한 컨테이너가 재시작하지 않는가, 다시 연결 확인 | 〃 | 〃 |
| 11 | 적용 기록 저장 | `runtime_state_failed` | 새 버전은 떠 있음. 다음 배포에서 다시 확인 |

상세 판정과 복구는 [배포 검증 및 롤백](v1-deployment-verification-and-rollback.md)에 있다.

### 10.5 운영 중 상시 감시

| 감시 | 위치·주기 | 확인하는 것 | 알림 |
| --- | --- | --- | --- |
| 컨테이너 healthcheck | 앱 EC2 Docker | web `/healthz`, frontend `/`가 500 미만, backend `/actuator/health`가 UP(DB 포함, 8081 → 8080 순서), ai-api `/health` | 없음. 종료된 컨테이너만 Docker가 재시작하고 unhealthy는 그대로 둔다 |
| 내부 서비스 health | blackbox → Prometheus (30초) → Grafana | 서비스 4개를 Docker 내부 주소로 호출 | 3분 지속 실패 → Discord, 복구 알림, 4시간마다 재알림 |
| 수집 상태 | Prometheus → Grafana | 수집 대상의 `up` | 3분 지속 → Discord |
| 앱 경고 8개 | Prometheus 규칙 → Grafana | HTTP 지표 누락·5xx·지연, JVM heap, DB 풀 포화·연결 대기, AI 제공자 오류·첫 토큰 지연 | Discord. 앱 계측 확인 후 대상 등록 시 동작 |
| 앱 EC2·RDS | CloudWatch | 앱 EC2 상태 검사·디스크·메모리, Agent 지표 누락, RDS 저장 공간·CPU | SNS 이메일 |
| 모니터링 EC2 | CloudWatch | 상태 검사·디스크 | SNS 이메일 |
| 주기 실행 토큰 | CloudWatch | EventBridge의 GitHub 호출 실패 | SNS 이메일 (SNS 연결 시) |
| 외부 감시 | GitHub Actions (5분) | 공개 주소 `/healthz` 200, `/`·`/api` 200~499, 30초 간격 5회 재시도 | 장애 시작·복구 때 Discord. Sentry Uptime으로 이전 예정 |
| AI 에러 | Sentry | AI 앱의 예외 | Sentry 설정에 따름 ([Sentry 정리](v1-sentry.md)) |

알림 경로·대응은 [장애 알림](v1-alerting.md)과 [모니터링 운영 구성](v1-monitoring.md)에 있다.

## 11. 현재 선택에 따라 남는 한계

- **재조회와 재배포는 다르다.** CI 대기·Manifest 병합 전 오류는 다음 조회에서 다시 판단한다. 병합 후 배포 호출·실제 배포가 실패해도 Manifest가 최신 SHA와 같으면 다음 조회는 건너뛴다. 원인 해결 후 Deploy production을 수동 실행해야 한다.
- **병합 전에 ECR을 조회하지 않는다.** 게시 job 성공을 근거로 삼고 실제 이미지는 EC2 pull에서 확인한다. 없는 이미지는 교체를 막지만 잘못된 Manifest는 남는다. 그 대상이 포함된 후속 배포도 pull에서 함께 실패할 수 있다.
- **태그를 신뢰한다.** digest를 고정하지 않아 같은 SHA 태그 덮어쓰기를 검출하지 않는다. 앱 CI의 불변 태그 계약이 필요하다.
- **Cloud 검사는 배포의 필수 선행 단계로 연결되어 있지 않다.** validate와 deploy는 독립 workflow다. 현재 릴리스는 Cloud PR 검사 통과를 기다리는 gate가 없다.
- **모든 중간 버전을 배포하지 않는다.** 브랜치 최신 SHA만 조회한다. 최신 CI가 진행 중이면 더 오래된 성공 커밋으로 후퇴하지 않는다.
- **일부 실패가 다른 서비스를 지연시킨다.** 조회 루프 앞 저장소의 오류나 대상 중 하나의 pull 실패가 뒤 작업을 막는다.
- **복구 범위가 제한된다.** 이미지 복구는 설정·Secret·DB를 복구하지 않는다. FE의 원자적 전환, 모든 서비스 버전 조합의 호환성, 실행 중단 후 자동 복구도 보장하지 않는다.
- **서비스 중단을 수용한다.** 교체 중 해당 서비스가 잠시 끊긴다. 호스트 지표·로그 집계·업무 E2E 감시는 구현 범위 밖이다.

한계를 수용한 이유와 재검토 조건은 [기술 결정](technical-decisions.md), 실제 조치는 [운영 절차](v1-operations.md)에 기록한다.
