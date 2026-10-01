# 자동 CD 운영 절차

동작과 구성 이유는 [전체 설명](v1-design.md), 운영 적용·시험 여부는 [구현 현황](v1-implementation-status.md)에 있다. 이 문서는 최초 연결·수동 실행·호스트 조회·Secret 변경을 관리한다. 장애 알림과 배포 복구의 상세는 각각 [장애 알림 시스템](./v1-alerting.md), [배포 검증 및 롤백](./v1-deployment-verification-and-rollback.md)에 둔다.

## 1. 최초 연결

### 1-1. GitHub 설정 (Cloud 저장소 Settings)

| 종류 | 이름 | 값·용도 |
| --- | --- | --- |
| Repository Variable | `AUTO_DEPLOY_ENABLED` | `true`면 일반 Auto release와 main push 배포 실행. 준비 완료 후 켠다 |
| Variable | `AWS_DEPLOY_ROLE_ARN` | OIDC로 사용할 배포 역할. 대상 EC2의 SSM SendCommand·GetCommandInvocation 권한 필요 |
| Variable | `PRODUCTION_EC2_INSTANCE_ID` | 배포 대상 EC2 ID |
| Repository Variable | `PUBLIC_ORIGIN` | 외부 감시 주소. 예: `https://도메인`. 비어 있으면 감시하지 않는다 |
| Repository Secret | `DISCORD_WEBHOOK_URL` | Discord 채널의 Webhook URL |

AWS 역할·인스턴스 변수는 `production` Environment에 두어도 된다. Auto release와 Health check는 그 Environment를 사용하지 않으므로 공통 스위치·공개 주소·Webhook은 저장소 범위로 설정한다.

- Actions 설정의 **Allow GitHub Actions to create and approve pull requests**를 허용한다.
- 무승인 자동 배포를 운영하려면 `production` Environment의 승인 정책과 맞춰야 한다. required reviewers가 있으면 Deploy production은 승인 대기한다.
- 필수 검사·리뷰·merge queue가 있는 저장소에서는 현재의 즉시 병합 경로를 그대로 켜지 않는다. 필요한 검사가 자동 실행되고 실제 병합이 끝난 뒤 배포하도록 토큰과 흐름을 맞춘다. 정책 변경 시 검토 사항은 [TD-010](technical-decisions.md#td-010--조회병합-로직을-어디에-쓸-것인가)에 있다.
- `validate.yaml` 존재만으로 병합·배포 전에 검사 통과가 강제되는 것은 아니다.

### 1-2. EC2 확인

기존 EC2·SSM Agent·배포 역할·Cloud checkout을 재사용한다. 다음 조건을 확인한다.

- SSM Agent가 Online이고 배포 역할이 대상 EC2에 명령을 보낼 수 있다.
- `/opt/keepgo/cloud`에 Cloud 저장소가 있고 SSM 실행 사용자로 `git fetch`가 된다. 작업 파일 변경 때문에 checkout이 막히지 않아야 한다.
- Docker Compose **2.30.0 이상**이며 `up --wait`, `config --hash`, `config --no-env-resolution`이 동작한다. 현재 Compose의 `env_file.format: raw`는 2.30.0부터 지원된다. [Docker 문서](https://docs.docker.com/reference/compose-file/services/#format)
- Bash, `python3`, `flock`, `curl`, AWS CLI와 Docker가 있다. EC2 instance role에 ECR pull 권한이 있다.
- TLS, ACME webroot, 업로드 경로가 준비돼 있다. runtime env·JWT는 매 배포 시 자동 갱신한다. 경로는 [전체 설명의 파일 위치](v1-design.md#9-파일과-상태의-위치)를 따른다. 이 배포는 비어 있는 호스트를 설치하는 bootstrap 절차가 아니다.
- instance role에 BE·AI Secret 읽기 권한이 있어야 한다. 실패 시 기존 파일을 대신 사용하지 않고 배포를 중단한다. Secret 변경은 8절을 따른다.
- 모니터링은 [CloudWatch + PG 적용 순서](v1-monitoring.md)를 따른다. 로그 그룹·IAM·전송 확인 후 `cloudwatch-logs.enabled`를 만들며, PG는 별도 checkout과 Compose 프로젝트로 운영한다. 로그 활성화 후 수동 앱 `up`에는 `compose.cloudwatch.yaml`도 함께 지정한다.
- 배포 workflow가 확인하는 AWS 계정은 `602601433533`, 리전은 `ap-northeast-2`다.

### 1-3. 켜는 순서

1. workflow·스크립트를 main에 반영하되 `AUTO_DEPLOY_ENABLED`는 비워 두거나 `false`로 둔다. `PUBLIC_ORIGIN`이 이미 있으면 Health check는 이 스위치와 별개로 실행된다.
2. 아래 dry_run으로 현재 후보를 확인한다. 문서에 적힌 과거 SHA 대신 실행 로그와 Manifest를 기준으로 판단한다.
3. Manifest 목표 SHA와 실제 EC2 버전, 초기 교체 대상을 확인한 뒤 **Deploy production → Run workflow → main**으로 수동 배포한다. Backend healthcheck 변경이 아직 적용되지 않았다면 같은 이미지라도 Backend가 재생성될 수 있다. 다른 대상이 나오면 이미지·env·설정·Compose 버전 차이를 확인한다.
4. [장애 알림 시스템](./v1-alerting.md) 6절에 따라 PUBLIC_ORIGIN·Webhook을 연결하고 정상 검사와 실제 수신을 확인한다.
5. `AUTO_DEPLOY_ENABLED=true`로 켠다. 다음 정상 조회에서 당시 최신 SHA의 CI·게시 job이 성공한 서비스가 후보가 된다. 배포 완료까지 걸리는 시간은 고정돼 있지 않다.
6. 9절 인수 시험 결과를 구현 현황에 기록한다.

## 2. 배포 전 후보 조회

**권장: Actions → Auto release → Run workflow → `dry_run` 체크 → 실행.** 기본값은 `false`이므로 조회만 할 때 반드시 체크한다. 자동 배포 스위치가 꺼져 있어도 dry_run은 실행된다.

| 로그 | 의미 |
| --- | --- |
| `최신` | 소스 최신 SHA와 Manifest가 같음. EC2 반영 성공을 뜻하지 않음 |
| `배포 대상` | Manifest와 다르고 해당 CI·게시 job이 성공함 |
| `이미지가 아직 없다` | 현재 CI·게시 job 조건을 충족하지 못함. ECR을 직접 조회한 결과는 아님 |
| API 오류로 실패 | 토큰·API·조회 설정 등을 확인해야 함 |

dry_run은 PR·병합·배포를 하지 않고 실패 Discord도 보내지 않는다. Actions 실행 로그와 상태를 직접 확인한다. checkout이 `main`으로 고정돼 있어 다른 실행 브랜치를 선택해도 release.sh·sources·Manifest는 main의 파일을 사용한다.

### 로컬 확인

WSL·Linux에서 Bash, GitHub CLI, jq를 준비하고 `gh auth login`으로 인증한다. 저장소 루트에서:

```sh
DRY_RUN=1 bash scripts/release.sh
```

로컬 checkout의 코드·설정을 확인하는 방법이다. `DRY_RUN` 없이 로컬에서 실행하면 스크립트가 거부한다. 현재 구현은 DRY_RUN이 비어 있지 않으면 조회 모드이므로 `DRY_RUN=0`도 실제 실행 전환을 의미하지 않는다.

빠른 정적 검사(각 도구 설치 필요):

```sh
for script in scripts/*.sh; do bash -n "$script"; done
shellcheck scripts/*.sh
actionlint
```

이는 CI 전체 검사의 일부다. JSON의 키·SHA·서비스 매핑과 Compose 구조를 확인하는 정확한 필터·명령은 [validate.yaml](../.github/workflows/validate.yaml)에 둔다. 같은 필터를 문서에 복사해 별도로 관리하지 않는다.

## 3. 자동 배포 멈추기·다시 켜기

`AUTO_DEPLOY_ENABLED=false`로 바꾸면 이후 일반 조회와 main push 배포가 멈춘다. 이미 실행 중인 작업을 중단하지 않는다. 수동 Deploy production과 Auto release dry_run은 계속 가능하며, 외부 감시는 `PUBLIC_ORIGIN`으로 별도 제어한다.

재개할 때는 후보 조회와 실행 중인 작업을 확인하고 `true`로 바꾼다. **이미 Manifest에 병합된 SHA의 배포 실패는 다음 조회만으로 재시도되지 않는다.** 그 경우 원인을 고친 뒤 Deploy production을 main에서 수동 실행한다.

## 4. Discord 알림별 대응

메시지의 Actions 링크에서 실패 단계를 확인한다. 알림 종류별 확인 순서는 [장애 알림 시스템](./v1-alerting.md) 5절, SSM/deploy.sh 결과별 복구 조치는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 6절에 모았다.

workflow 요약의 needs_action은 공통 분류다. 세부 원인은 SSM 출력의 deploy.sh 결과와 history.log에서 확인하고, 호스트 조회에는 다음 절을 사용한다.

## 5. 직접 확인 (EC2)

SSM Session Manager 등으로 접속한다. 아래 조회는 Compose 이미지 환경변수 없이 실행할 수 있다.

```sh
sudo tail -n 20 /opt/keepgo/state/history.log
sudo cat /opt/keepgo/state/failed-images
sudo docker ps -a --filter label=com.docker.compose.project=keepgo-v1 \
  --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'
```

표에서 조사할 컨테이너 ID를 골라 제한된 정보와 로그를 확인한다.

```sh
CONTAINER_ID='위에서 확인한 ID'
sudo docker inspect --format '{{.Config.Image}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$CONTAINER_ID"
sudo docker logs --tail 100 "$CONTAINER_ID"
```

로그가 민감한 값을 포함할 수 있으므로 공유 전 확인한다. 조사 기록에는 시간, Cloud 커밋, 실제 서비스별 이미지, Actions/SSM 실행 ID, 배포 결과를 남긴다. history.log만으로 중단된 프로세스가 끝났다고 단정하지 않는다.

수동 Compose 명령에는 AWS 계정과 네 이미지 태그 환경변수가 필요하다. 전체 설정을 출력해 비밀값을 공유하지 않는다. 8절의 직접 재생성도 현재 운영 이미지를 유지하도록 변수를 먼저 준비해야 한다.

## 6. 수동 롤백

자동 배포 중지 → 정상 버전 선택 → Manifest·필요한 설정 복구 → main 수동 배포 → 검증 → 자동화 재개의 절차를 따른다. 단계별 확인 사항과 FE·DB 예외는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 6절에 둔다.

## 7. 차단 목록 (`/opt/keepgo/state/failed-images`)

차단 기록의 의미, FE 두 서비스의 예외와 같은 이미지 재시도 방법은 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 5절을 따른다. 수동 변경 전 진행 중인 배포가 없는지 확인하고 파일을 백업한다.

## 8. Secret 변경

자동·수동 Deploy production 모두 배포 시작 시 `prepare-runtime.py`로 Secrets Manager의 값을 조회·검증하고 runtime env·JWT를 갱신한다. 기본 Secret ID는 `Secret-v1-BE`, `Secret-v1-AI`다. 별도의 EC2 갱신 명령은 필요 없다. Secret만 바꿔서는 Auto release가 배포를 호출하지 않으므로 즉시 반영하려면 수동 배포한다.

1. 변경 시점을 통제하려면 자동 배포를 끄고 진행 중인 배포 종료를 확인한다.
2. Secrets Manager에서 값을 수정한다. JWT 키 쌍은 함께 변경하고 기존 토큰에 미칠 영향은 앱 팀과 조율한다.
3. Manifest 목표와 실제 버전을 확인하고 Deploy production을 main에서 수동 실행한다.
4. 변경된 서비스의 health와 실제 인증·AI/지도 기능을 확인한 뒤 자동 배포를 재개한다.

env·JWT 파일 변경은 마지막 정상 적용 컨테이너 ID·파일 지문으로 감지한다. JWT만 바뀌면 Backend, AI env만 바뀌면 AI만 강제 재생성된다. 최초 도입 또는 `/opt/keepgo/state/runtime-applied-backend.json`·`runtime-applied-ai-api.json` 기록이 없으면 해당 서비스를 한 번 재생성하므로 적용 시간을 조율한다. 파일 내용이 같으면 그대로 유지한다. 이미지 pull 실패 후 재배포해도 미적용 파일 변경을 다시 감지한다. 차단된 이미지를 건너뛴 경우에는 새 Secret도 적용 완료로 기록되지 않으므로 차단 상태를 먼저 해결한다.

조회·검증 실패는 runtime 파일 변경 전에, 파일 저장 실패는 컨테이너 교체 전에 `runtime_prepare_failed`로 중단하고 Discord로 알린다. 저장 도중 실패하면 일부 호스트 파일만 갱신될 수 있으므로 권한·디스크 문제 해결 후 전체 배포를 다시 실행한다. `runtime_state_failed`는 runtime 파일/적용 기록 접근·저장 문제다. 이 경우 컨테이너 교체가 이미 완료됐을 수도 있으므로 실제 상태를 확인하고 재배포한다. 적용 기록에 있는 지문도 외부에 공유하지 않는다.

자동 롤백은 이미지만 복구하며 **Secret은 최신 조회값을 유지한다.** 잘못된 비밀번호/API 키로 실패했다면 Secrets Manager의 값을 유효한 값으로 수정/복원한 뒤 다시 배포한다. 폐기된 외부 자격 증명은 파일을 되돌린다고 다시 유효해지지 않는다. 새 이미지까지 함께 변경해 차단됐다면 차단 해제/목표 이미지도 확인한다. 기본 형식 검사는 자격 증명의 실제 유효성이나 RSA 키 쌍 일치를 보장하지 않는다.

EC2에서 `sudo python3 /opt/keepgo/cloud/scripts/prepare-runtime.py`를 직접 실행하는 것은 파일 준비만 수행한다. 컨테이너에는 반영하지 않으며 배포와 동시에 실행하지 않는다. 일반적인 Secret 변경에는 위 수동 Deploy production 절차를 사용한다.

## 9. 실환경 인수 시험

최초 연결 후 Auto release dry_run에서 후보만 출력되고 PR·배포·실패 Discord가 없는지 확인한다. 이어서 아래 문서의 시험을 수행한다.

- [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md) 7절: 정상 교체, 실패·복구·차단, 수동 재배포와 중단 처리.
- [장애 알림 시스템](./v1-alerting.md) 7절: 실제 장애 수신, 반복 억제, 복구 통지.

시험 날짜·커밋·실행 링크·결과는 [구현 현황](./v1-implementation-status.md)에 기록한다.

## 10. 증상별 빠른 확인

| 증상 | 확인할 곳 |
| --- | --- |
| 일반 Auto release 또는 push Deploy가 skipped | 자동 배포 스위치. dry_run과 수동 Deploy의 예외는 2·3절 |
| 계속 `이미지가 아직 없다` | 소스 브랜치·workflow·게시 job 이름과 최신 run. FE 기준은 현재 sources.json 확인 |
| PR 생성 권한 오류 | 1-1절의 Actions PR 생성 허용 설정 |
| 필수 검사·리뷰 때문에 PR 병합 실패 | 정책 변경 여부와 검사 승인 대기. [TD-010](technical-decisions.md#td-010--조회병합-로직을-어디에-쓸-것인가) |
| Deploy가 승인 대기 | production Environment 정책 |
| Manifest는 최신인데 운영 버전이 다름 | 배포 호출 누락·실제 배포 실패·차단 목록. 3·4·7절 |
| 예상보다 많은 서비스가 대상 | 실제 이미지, Compose 설정·env 값, Compose 버전과 해시 차이 |
| 다른 배포가 진행 중이라는 로그 | 이전 SSM 명령·호스트 프로세스 확인. 강제로 잠금 파일을 지우지 않는다 |
| Backend unhealthy | Actuator 응답과 앱 로그, DB 연결·env·JWT 확인 |
| 사이트는 열리지만 외부 검사 실패 | 세 URL의 개별 응답 코드 확인 |
| 로컬 DRY_RUN에서 repos/null 오류 | Windows jq와 Git Bash의 CRLF 차이를 확인한다. WSL·Linux 또는 Actions dry_run을 사용한다 |
| 로컬 API rate limit 오류 | gh 인증 상태와 API 응답의 한도·초기화 시각을 확인한다. 반복 호출을 멈추고 Actions dry_run 사용 여부를 판단한다 |
| Discord가 오지 않음 | dry_run 여부, 롤백 성공, Webhook Secret 누락·전송 오류, 외부 검사 상태 비교 |
| 주기 실행이 멈춤 | Actions 스케줄 활성 상태와 기본 브랜치 확인. 공개 저장소의 60일 무활동 시 자동 비활성화 정책도 확인 |

스케줄 정책은 [GitHub 공식 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)를 따른다.

## 11. 주기 실행(EventBridge)과 GitHub 토큰 교체

이 레포에서 GitHub `on.schedule`이 실행되지 않아 EventBridge가 Auto release(10분)·Health check(5분)를 실행한다([TD-022](technical-decisions.md#td-022--github-schedule-대신-eventbridge로-주기-실행)). Actions 목록에는 "Manually run by (토큰 소유자)"로 보인다.

- 상태 확인: AWS 콘솔 → EventBridge → 규칙 → `keepgo-v1-auto-release-every-10m`, `keepgo-v1-health-check-every-5m` → 모니터링 탭(Invocations·FailedInvocations).
- 일시 중지: 규칙을 "비활성화"한다. 자동 배포만 멈추려면 `AUTO_DEPLOY_ENABLED=false`가 더 간단하다.
- **토큰 교체**(만료 전, 또는 FailedInvocations 발생 시): 새 fine-grained PAT(대상 레포 KTB4-8th-CLOUD, 권한 Actions Read and write)을 만든 뒤 관리자 권한 CloudShell에서 실행한다. EC2 SSM 세션은 권한이 없다.

```bash
read -rs TOKEN   # 새 토큰 입력 (화면·기록에 남지 않음)
curl -s -o /dev/null -w "%{http_code}
" -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json"   https://api.github.com/repos/100-hours-a-week/KTB4-8th-CLOUD/actions/workflows/auto-release.yaml/dispatches   -d '{"ref":"main","inputs":{"dry_run":"true"}}'          # 204면 정상
curl -sO https://raw.githubusercontent.com/100-hours-a-week/KTB4-8th-CLOUD/main/infrastructure/github-dispatch.yaml
aws cloudformation deploy --region ap-northeast-2 --stack-name keepgo-v1-github-dispatch   --template-file github-dispatch.yaml --capabilities CAPABILITY_IAM   --parameter-overrides GitHubToken="$TOKEN"   # 알람 연결 시 AlertsTopicArn=<SNS ARN> 추가
unset TOKEN
```

교체 후 5분 안에 Health check 실행이 새로 생기는지 확인하고, 이전 토큰은 GitHub에서 폐기한다.

