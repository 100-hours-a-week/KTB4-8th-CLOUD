# 자동 CD 전체 설명 — 동작과 구성 이유

이 문서 하나로 현재 V1의 배포 흐름, 각 파일의 역할, 선택 이유와 한계를 이해할 수 있도록 정리했다. 기준은 2026-09-29 작업 트리의 코드다. 알림 구축의 상세는 [장애 알림 시스템](./v1-alerting.md), 성공 판정과 복구 상세는 [배포 검증 및 롤백](./v1-deployment-verification-and-rollback.md)에 둔다. 최초 연결·호스트 조회는 [운영 절차](v1-operations.md), 실제 시험 결과는 [구현 현황](v1-implementation-status.md), 대안 비교는 [기술 결정](technical-decisions.md)을 따른다.

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
GitHub runner: Auto release (10분 주기 설정)
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

별도 GitHub runner: Health check (5분 주기 설정)
  공개 URL 응답 확인 → 장애·복구 상태 변화 시 Discord
```

10분·5분은 조회 스케줄이며 배포·감지 완료 시간의 보장이 아니다. CI 실행, 배포 대기, 이미지 다운로드와 검증 시간이 추가된다. GitHub schedule도 지연되거나 실행이 누락될 수 있다. [GitHub schedule 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

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

사람이 `main`의 Manifest·`compose.yaml`·`scripts/deploy.sh`를 바꾸면 자동 배포 스위치가 켜져 있을 때 push로 배포한다. 수동 Deploy production은 스위치가 꺼져 있어도 실행된다. 이 세 경로 외 파일만 바꾸는 push는 배포 트리거가 아니다.

**구성 이유:** 앱별 버전 변경을 추적 가능한 Git 이력으로 남기고 실행 주체를 Cloud로 모은다. PR 병합은 목표 변경이며 운영 반영 성공을 뜻하지 않는다.

## 5. EC2에서의 교체 과정

[deploy-production.yaml](../.github/workflows/deploy-production.yaml)은 production Environment의 AWS 역할을 OIDC로 사용한다. 계정을 확인한 뒤 SSM으로 기존 EC2에 명령을 보내고, workflow의 Cloud SHA를 `/opt/keepgo/cloud`에 checkout해 [deploy.sh](../scripts/deploy.sh)를 실행한다.

Auto release는 `main`을 지정해 배포를 호출한다. 그 배포가 선택한 커밋에는 여러 서비스의 병합 결과가 들어갈 수 있다. 배포 대상은 PR diff가 아닌 EC2 실제 상태와 해당 커밋의 설정 차이로 계산한다.

EC2에서는 잠금과 설정 검사 후 변경 대상을 정하고, 이미지를 모두 받은 뒤 서비스별로 교체·검증한다. 실패하면 이전 이미지 복구를 시도한다. 정확한 검사 순서·기준·종료 결과는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 3~4절에 둔다.

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

| 파일 | 실행 위치 또는 역할 |
| --- | --- |
| [compose.yaml](../compose.yaml) | EC2 서비스·네트워크·healthcheck·마운트 설정 |
| [production-manifest.json](../deployment/production-manifest.json) | Git의 목표 이미지 SHA |
| [sources.json](../deployment/sources.json) | 앱 CI 조회 대상과 서비스 묶음 |
| [auto-release.yaml](../.github/workflows/auto-release.yaml) | 조회 스케줄·dry_run 입력·권한·배포 호출 |
| [release.sh](../scripts/release.sh) | runner의 후보 조회·PR 생성·병합, 로컬 DRY_RUN |
| [deploy-production.yaml](../.github/workflows/deploy-production.yaml) | runner의 OIDC·SSM 호출·결과 판정 |
| [deploy.sh](../scripts/deploy.sh) | EC2의 변경 계산·pull·교체·검증·복구 |
| [health-check.yaml](../.github/workflows/health-check.yaml) | runner의 주기적 외부 검사 |
| [notify-discord.sh](../scripts/notify-discord.sh) | runner의 Discord 알림 |
| [validate.yaml](../.github/workflows/validate.yaml) | JSON·Compose·Shell·workflow 정적 검사 |
| [prepare-runtime.py](../scripts/prepare-runtime.py) | 운영자가 EC2에서 Secrets Manager → env·JWT 파일 준비 |

EC2 `/opt/keepgo/state/`에는 `deploy.lock`(잠금), `failed-images`(차단 서비스·SHA), `history.log`(시간·Cloud 커밋·결과·교체 서비스)가 생긴다. 이전 이미지 태그는 실행 중 메모리에 보관하므로 프로세스 중단 후 자동 복구를 재개할 상태 파일은 없다.

Secret·JWT는 `/opt/keepgo/runtime/`, TLS는 `/opt/keepgo/tls/`, ACME는 `/opt/keepgo/acme/`, 업로드는 `/opt/keepgo/data/uploads/`를 사용한다. 인증 값과 호스트 상태는 Git에 넣지 않는다. 자동 배포는 prepare-runtime.py를 실행하지 않는다.

## 10. 현재 선택에 따라 남는 한계

- **재조회와 재배포는 다르다.** CI 대기·Manifest 병합 전 오류는 다음 조회에서 다시 판단한다. 병합 후 배포 호출·실제 배포가 실패해도 Manifest가 최신 SHA와 같으면 다음 조회는 건너뛴다. 원인 해결 후 Deploy production을 수동 실행해야 한다.
- **병합 전에 ECR을 조회하지 않는다.** 게시 job 성공을 근거로 삼고 실제 이미지는 EC2 pull에서 확인한다. 없는 이미지는 교체를 막지만 잘못된 Manifest는 남는다. 그 대상이 포함된 후속 배포도 pull에서 함께 실패할 수 있다.
- **태그를 신뢰한다.** digest를 고정하지 않아 같은 SHA 태그 덮어쓰기를 검출하지 않는다. 앱 CI의 불변 태그 계약이 필요하다.
- **Cloud 검사는 배포의 필수 선행 단계로 연결되어 있지 않다.** validate와 deploy는 독립 workflow다. 현재 릴리스는 Cloud PR 검사 통과를 기다리는 gate가 없다.
- **모든 중간 버전을 배포하지 않는다.** 브랜치 최신 SHA만 조회한다. 최신 CI가 진행 중이면 더 오래된 성공 커밋으로 후퇴하지 않는다.
- **일부 실패가 다른 서비스를 지연시킨다.** 조회 루프 앞 저장소의 오류나 대상 중 하나의 pull 실패가 뒤 작업을 막는다.
- **복구 범위가 제한된다.** 이미지 복구는 설정·Secret·DB를 복구하지 않는다. FE의 원자적 전환, 모든 서비스 버전 조합의 호환성, 실행 중단 후 자동 복구도 보장하지 않는다.
- **서비스 중단을 수용한다.** 교체 중 해당 서비스가 잠시 끊긴다. 호스트 지표·로그 집계·업무 E2E 감시는 구현 범위 밖이다.

한계를 수용한 이유와 재검토 조건은 [기술 결정](technical-decisions.md), 실제 조치는 [운영 절차](v1-operations.md)에 기록한다.
