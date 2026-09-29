# 파일별 역할·사용 상황·실행 방법·푸시 지침

현재 환경 기준은 [9월 28일 인계 문서](v1-handoff-2026-09-28.md)다. 아래에서 **실행 보류**는 Git에 소스를 보관하지 말라는 뜻이 아니라, 아직 실제 운영에 적용할 조건이 갖춰지지 않았다는 뜻이다.

## 1. 지금 가능한 작업과 보류할 작업

| 구분 | 지금 할 일 |
| --- | --- |
| 가능 | 문서 검토, 실제 저장소 정보 반영, Compose 구조 검사, Python 테스트, 코드 리뷰와 소스 푸시 |
| 실행 보류 | 실제 배포/롤백, EC2 초기 관리 상태 편입, 앱 검사 의존 모니터 설치, S3 포함 template 적용 |
| 현재 스위치 | CD_SETUP_READY=false, CD_ENABLED=false, MONITOR_ENABLED=false; 미등록도 활성화로 보지 않음 |
| 호스트 설정 | app_checks_confirmed=false. 앱 계약을 확인하기 전 true로 바꾸지 않음 |

Worker 이미지는 미게시이며 앱 검사도 미확정이다. 상태 검사 없이 성공을 반환하도록 배포 코드를 수정하지 않는다. 기존 EC2는 팀원이 운영 중이므로 bootstrap이나 compose up을 지금 바로 실행하지 않는다.

## 2. 전체 실행 관계

```text
앱 CI가 이미지를 게시함
  → 앱 저장소의 notify-cloud 예시를 설정해 완료 알림
  → candidate.yaml → candidate.py → 검증된 Manifest PR 생성
  → validate.yaml + release-policy.yaml → 검사와 자동 병합
  → deploy-production.yaml → ssm-deploy.py → EC2에 실행 지시
  → EC2의 deploy.py → release.py → 변경 서비스 교체·검증·복구

EC2의 keepgo-monitor.timer → keepgo-monitor.service → monitor.py
GitHub의 external-health.yaml → external-probe.py
  → CloudWatch 지표/알람 → SNS 알림
```

현재 ssm-deploy.py의 코드 전달 부분은 S3 기반 초안이라 위 배포 흐름을 아직 운영에서 실행하면 안 된다. S3 없는 전달 방식으로 교체할 예정이다.

## 3. 설정 파일

| 파일 | 역할 | 언제·어떻게 사용하는가 | 푸시 |
| --- | --- | --- | --- |
| compose.yaml | 서비스, 이미지, 포트, 네트워크, 환경변수, 로그, 종료 유예 | 구조 검사는 지금 가능. 실제 적용은 EC2 현재 구성/Worker 게시 확인 후 CD가 수행. 현재 healthcheck 계약은 주석 상태 | 소스 푸시 가능, 적용 보류 |
| deployment/source-policy.json | 허용 앱 repo·CI 경로·필수 job·ECR 매핑 | 앱 repo/CI 확인 후 실제 이름 입력. 후보 접수와 배포 출처 검사에서 읽음. Worker 항목은 미확정 | 푸시 가능 |
| deployment/production-manifest.json | 목표 이미지 SHA와 성공 CI run ID | 최초 유효 목록은 검토 후 작성. 이후 후보 PR이 해당 단위만 변경. 실제 실행 상태 파일은 아님 | 푸시 가능. 자리표시자는 배포 불가 |
| deployment/runtime.example.json | EC2 실제 설정을 작성하는 예시 | 호스트 준비 시 복사하여 /opt/keepgo/runtime.json 작성. 계정 외 미확정 값은 추후 입력 | 예시만 푸시 |
| .gitignore | 비밀·운영 상태·IDE·생성 파일 제외 | git add 전에 확인. 이미 추적 중인 파일에는 소급 적용되지 않음 | 푸시 |
| .gitattributes | 스크립트·문서 줄바꿈 규칙 | Windows에서 작성한 스크립트가 Linux에서 실행되도록 LF 유지 | 푸시 |

삭제된 deployment/production-manifest.yaml은 JSON 형식으로 교체한 이전 파일이다. JSON 추가와 YAML 삭제를 함께 반영한다. 두 형식을 동시에 운영 기준으로 유지하지 않는다.

계정 ID, ECR URI, repo 이름, 이미지 SHA, role ARN은 인증 비밀값이 아니다. 다만 저장소 공개 범위에 대한 팀 정책은 따른다. 비밀번호/API key를 Compose environment나 예시 JSON에 직접 넣지 않는다.

## 4. GitHub workflow

| 파일 | 동작 시점 | 실행하는 일 | 현재 조건 |
| --- | --- | --- | --- |
| .github/workflows/validate.yaml | main 대상 PR/main push | Python/Bash 문법, Manifest/Compose 구조, 테스트, actionlint | 지금 소스 검사 용도로 사용 가능. AWS 배포 없음 |
| .github/workflows/candidate.yaml | 앱 dispatch 또는 10분 schedule | candidate.py로 출처 검사·후보 PR 생성·누락 후보 확인 | CD_SETUP_READY와 CD_ENABLED 모두 true 필요 |
| .github/workflows/release-policy.yaml | main 대상 PR 생성/변경 | main의 신뢰된 코드로 PR 범위·출처·승인을 검사하고 봇 PR 자동 병합 설정 | CD_SETUP_READY=true 필요 |
| .github/workflows/deploy-production.yaml | 배포 관련 main 변경 또는 수동 실행 | 운영 AWS role 획득, 검증, SSM 실행, 실패 알림/결과 보관 | CD_SETUP_READY=true 필요. S3 전제 수정 전 실행 보류 |
| .github/workflows/external-health.yaml | 5분 schedule 또는 수동 실행 | 외부 HTTPS를 확인하고 CloudWatch 지표 전송 | MONITOR_ENABLED=true 및 실제 경로/권한 필요 |
| examples/app-notify-cloud.yaml | 현재 폴더에서는 자동 실행되지 않음 | 앱 CI 완료 후 Cloud에 후보 알림을 보내는 예시 | 각 앱 repo의 .github/workflows/notify-cloud.yaml로 복사해 이름·단위·인증 설정 |

workflow 파일을 push하는 것과 AWS에 배포하는 것은 별개다. 현재 스위치를 false로 두면 운영 관련 job은 실행하지 않는다. 설정된 외부 감시 스위치가 있으면 해당 job은 별도로 실행될 수 있으므로 업로드 전에 값을 확인한다.

release-policy를 보류한 동안 새로 필수 status로 등록하면 PR이 그 결과를 기다릴 수 있다. 새 보호 규칙은 설치 순서에 맞춰 켜고, 이미 적용된 보호 규칙은 저장소 담당자와 조정한다. 검사를 임의 성공 처리해 우회하지 않는다.

## 5. 스크립트별 사용법

### scripts/validate-manifest.py — 배포 설정 검사

로컬 PC 또는 GitHub Actions에서 설정을 수정한 뒤 사용한다. Python과 Docker Compose CLI가 필요하며 구조 검사에 Docker daemon이나 AWS 인증은 필요하지 않다.

```sh
# 현재처럼 실제 이미지 SHA가 아직 없어도 설정 구조를 검사한다.
python scripts/validate-manifest.py --structure-only

# 실제 SHA와 CI run ID를 채운 뒤 형식을 엄격하게 검사한다.
python scripts/validate-manifest.py

# 별도로 준비한 배포 목록을 검사한다.
python scripts/validate-manifest.py --manifest deployment/production-manifest.json
```

엄격 검사가 통과해도 ECR 이미지 존재나 CI 성공을 조회한 것은 아니다. 출처와 ECR 검증은 후보/배포 단계가 별도로 수행한다. 이 스크립트는 컨테이너를 시작하거나 교체하지 않는다.

### scripts/release.py — 공통 함수 모음

JSON 읽기/원자적 저장, Manifest 규칙, Compose 렌더링, ECR digest 조회, 변경 서비스 계산, GitHub CI 조회를 다른 스크립트에 제공한다. 사람이 단독으로 실행할 명령은 없다. 수정 시 전체 단위 테스트를 실행한다.

### scripts/candidate.py — 후보 PR 관리

GitHub Actions에서 호출한다. GITHUB_EVENT_PATH, GITHUB_REPOSITORY, GH_TOKEN, SOURCE_READ_TOKEN, CD_BOT_LOGIN, AWS_ACCOUNT_ID 및 ECR 조회 권한이 필요하다.

| 명령 | 사용하는 상황 | 외부에 미치는 영향 |
| --- | --- | --- |
| python3 scripts/candidate.py create | 앱의 게시 완료 dispatch 수신 | 해당 단위의 Manifest branch/PR 생성, 기존 같은 단위 후보 정리 |
| python3 scripts/candidate.py gate | PR 정책 검사 | 정확한 PR head에 status 기록, 허용된 봇 PR의 auto-merge 설정 |
| python3 scripts/candidate.py refresh | 주기적 누락 알림 보완 | 뒤처진 후보 branch 갱신, 최신 성공 CI로 후보 생성 가능 |

읽기 전용 검사 도구가 아니다. 토큰을 채팅에 붙여 넣거나 로컬에서 임의 이벤트를 만들어 실행하지 말고 workflow의 로그와 실행 기록으로 관리한다.

### scripts/ssm-deploy.py — 원격 실행 지시, 현재 적용 보류

deploy-production.yaml이 GitHub runner에서 호출한다. 로컬 코드를 묶고 SHA256을 계산한 뒤 S3 업로드, EC2의 다운로드/실행을 SSM으로 지시한다. 반환된 command ID를 기록하고 실제 종료 상태까지 기다린다.

**현재 환경에서는 S3를 쓰지 않으므로 실행하지 않는다.** DEPLOY_BUCKET을 채워 우회하지 않는다. EC2 checkout/읽기 인증 인계를 받은 뒤 전달 방식과 IAM을 함께 수정해야 한다. 프로그램 소스는 기록용으로 push할 수 있지만 운영 적용은 보류한다.

### scripts/deploy.sh — EC2 실행 진입점

자신의 위치를 기준으로 scripts/deploy.py를 실행하는 얇은 Bash 래퍼다. 이미지 빌드나 EC2 생성 도구가 아니다. 다음 명령들은 모든 준비와 기존 운영 상태 인계가 끝난 **EC2에서만** 사용한다.

```sh
# CLOUD_SHA에는 실제로 검토한 Cloud 저장소의 40자리 커밋을 넣는다.
# 지금은 준비되지 않았으므로 아래 운영 명령을 실행하지 않는다.
bash scripts/deploy.sh --revision "$CLOUD_SHA" --mode deploy
```

### scripts/deploy.py — 실제 교체와 복구

EC2에서 Docker, AWS CLI, runtime.json, 검증된 Manifest와 이미지, 앱 검사 계약을 사용한다. 직접 실행 형식은 `python3 scripts/deploy.py --revision <Cloud의40자리SHA> --mode <동작>`이다. `--config`를 생략하면 /opt/keepgo/runtime.json을 읽는다.

| mode | 언제 사용하는가 | 동작 |
| --- | --- | --- |
| deploy | 준비된 새 버전을 반영할 때 | 변경 단위만 pull/중지/교체/검증. 실패한 단위 복구 |
| freeze | 후속 자동 변경을 멈출 때 | host 동결 marker 생성. 진행 중 프로세스를 강제 종료하지 않음 |
| rollback | 마지막 성공한 단위의 변경을 되돌릴 때 | previous 상태로 복구하고 되돌린 신규 이미지를 차단 |
| recover | 원격 실행이 중단되어 journal이 남았을 때 | journal의 이전 상태를 복구. 없으면 current 재검증 |
| resume | 실제 상태와 Git 목표를 맞춘 뒤 | 미완료 journal 없음과 검증 성공을 확인하고 동결 해제 |

모든 변경은 동일 host lock을 사용한다. 복구가 성공해도 자동으로 동결을 풀지 않는다. DB schema를 자동으로 되돌리지 않는다. 현재 app_checks_confirmed=false이므로 배포·복구 검증은 시작하지 않는다. freeze도 필요한 실제 runtime 설정이 준비되어 있어야 한다.

### scripts/bootstrap-host.sh — 운영 도구 설치

**기존 EC2 인계와 앱/모니터 계약 확정 후**, 호스트 관리자 권한으로 한 번 실행하거나 모니터 코드를 갱신할 때 실행한다.

```sh
# 준비가 완료된 EC2에서만 실행한다.
sudo bash scripts/bootstrap-host.sh
```

이 스크립트는 Docker/SSM을 설치하거나 EC2를 생성하지 않는다. 필수 도구와 runtime.json을 확인하고 /opt/keepgo/state·releases·ops 디렉터리, 운영 스크립트, instance ID, systemd unit을 설치한다. 마지막에 monitor timer를 활성화한다. 현재 실행하면 미확정 health/queue 검사로 잘못된 장애 신호가 발생할 수 있어 보류한다.

### scripts/monitor.py — 호스트 내부 감시

설치 후 systemd가 주기적으로 실행한다. current/inflight 상태, 컨테이너 health·재시작, Backend의 queue-metrics, 디스크·메모리를 읽고 CloudWatch에 지표를 보낸다. 별도 웹 서버를 만드는 파일이 아니다. 현재 앱 검사와 운영 state가 없어 아직 설치하지 않는다.

설치 후 상태 확인:

```sh
sudo systemctl status keepgo-monitor.timer
sudo journalctl -u keepgo-monitor.service --since '10 minutes ago'
```

### scripts/external-probe.py — 외부 HTTPS 감시

GitHub runner에서 운영 origin의 `/`와 `/api/health/ready`를 확인하고 ExternalHealthy 지표를 전송한다. PUBLIC_ORIGIN, PRODUCTION_EC2_INSTANCE_ID 및 CloudWatch 쓰기 권한이 필요하다. 경로가 실제 앱에 있는지 확인한 뒤 external-health.yaml을 활성화한다. 단순 출력만 하는 로컬 검사 명령이 아니다.

## 6. 인프라·모니터·테스트 파일

| 파일 | 역할과 사용하는 상황 | 현재 사용 방법 |
| --- | --- | --- |
| infrastructure/monitoring.yaml | CloudWatch 로그/알람, SNS, SSM 실패 EventBridge 정의 | 기존 리소스 유무를 확인한 뒤 change set으로 누락 항목을 설치. EC2/RDS를 새로 만들지 않음 |
| infrastructure/cd-access.yaml | GitHub OIDC role, 기존 EC2 role 정책, S3 배포 bucket 초안 | S3 없는 환경에 맞게 수정 전 적용 금지. 기존 IAM과 중복도 확인 |
| monitoring/keepgo-monitor.service | monitor.py의 실행 사용자·경로·제한시간 | bootstrap이 /etc/systemd/system에 설치. 현재 보류 |
| monitoring/keepgo-monitor.timer | 주기적으로 service 실행 | 설치 후 systemctl로 상태 조회. 현재 보류 |
| tests/test_release.py | 배포 차이·실패·복구·출처 검사 테스트 | 로컬/CI에서 unittest로 실행. 실제 AWS/운영 배포 시험을 대신하지 않음 |

```sh
# 로컬 또는 CI에서 실행 가능한 검사다.
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
# Bash가 설치된 환경에서 스크립트 문법을 확인한다.
bash -n scripts/deploy.sh
bash -n scripts/bootstrap-host.sh
```

## 7. 문서별 읽는 순서

| 문서 | 목적 |
| --- | --- |
| README.md | 진입점과 현재 적용 상태 |
| docs/v1-handoff-2026-09-28.md | **현재 확인된 환경, 미확정 정보, 팀원에게 요청할 내용, 다음 순서** |
| 이 문서 | 파일 역할·실행 상황·명령·푸시 구분 |
| docs/v1-design.md | 중앙 CD, 독립 배포, 상태 저장, 롤백의 설계 근거. 9월 28일 보류 사항 우선 |
| docs/v1-app-contracts.md | health/job/schema/log 계약 제안. 앱이 이미 구현했다는 확인서가 아님 |
| docs/v1-operations.md | 준비 완료 후 설치·배포·복구 Runbook. S3 관련 기존 절차는 현재 보류 |
| docs/v1-implementation-status.md | 코드와 로컬 검사 내역, 실제 운영 미검증 범위 |
| docs/v1-central-auto-cd-action-plan.md | 초기 계획 보관본 |
| docs/ci-cd-repository-responsibilities.md | 채택하지 않은 독립 CD 제안 보관본 |
| docs/v2-cicd-design-review.md, docs/V2 설계.md | V2 참고 자료. 현재 v1 실행 지침으로 사용하지 않음 |

## 8. 무엇을 푸시하고 무엇을 제외할지

| 분류 | 대상 | 처리 |
| --- | --- | --- |
| 푸시 | .github/workflows, scripts, tests, monitoring, infrastructure, examples, compose.yaml, deployment의 예시/정책/목표 파일, 문서, .gitignore/.gitattributes | 준비용 소스로 검토·버전 관리. 자동화 스위치는 false 유지 |
| 소스 푸시 가능·적용 보류 | S3 전달/IAM 초안, runtime 예시, 앱 검사 계약, monitor 설치 파일 | 보류 주석·문서와 함께 기록. 운영 실행/CloudFormation 적용하지 않음 |
| 푸시 금지 | 실제 .env, runtime.json, private key/인증서 키, AWS credentials, GitHub token/App key, Secret 내용 | 호스트 또는 GitHub Secrets/Secrets Manager에만 보관 |
| 푸시 제외 | .idea, .tools, __pycache__, .artifacts, 실행 로그, DB backup, 운영 state/release 디렉터리 | .gitignore로 제외 |
| 검토 후 포함 | 기존 작성 중인 docs/V2 설계.md 등 별도 작업 파일 | git diff/작성자를 확인해 이번 변경과 함께 올릴지 결정. 자동 일괄 추가하지 않음 |

실제 current/previous/inflight/blocked/frozen/result 상태는 운영 호스트의 /opt/keepgo/state에 저장하며 Git 목표와 다르다. 상태 파일을 배포 설정처럼 commit하지 않는다. 공유가 필요한 인계 자료는 민감 정보를 제거하고, 원본은 로컬 handoff-private/ 등에 둔다.

```sh
# 올릴 파일과 변경 내용을 먼저 확인한다.
git status --short
git diff --stat
git diff --check
# 제외 규칙이 적용되는지 확인한다.
git check-ignore -v .env deployment/runtime.json .artifacts/ssm-result.json
# 추가할 소스 경로를 검토해 지정한다. 이 문서 작성 중 실제 git add/commit/push는 하지 않았다.
# 스테이징 후 내용을 다시 확인한다.
git diff --cached --name-status
git diff --cached
```

gitignore는 이미 추적 중인 비밀 파일을 삭제하거나 노출을 취소하지 않는다. 그런 파일이 있으면 먼저 노출 여부와 키 교체 필요성을 확인한다. 소스 전체를 올리면서 비밀값만 제외하고, 실행 보류 파일을 실수로 EC2에서 실행하지 않도록 상태를 함께 전달한다.
