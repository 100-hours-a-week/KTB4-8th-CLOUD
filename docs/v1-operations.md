# Backend 중앙 자동 CD 운영 절차

현재 범위는 Backend 자동 배포이며 기존 Nginx·Frontend·AI는 유지한다. [기술 결정 기록](technical-decisions.md), [설계](v1-design.md)를 함께 본다. AWS/GitHub 활성화와 EC2 실환경 검증은 아직 수행하지 않았다.

## 1. 최초 연결

1. `CD_ENABLED=false`, `CD_SETUP_READY=false`로 두고 변경 코드·CI를 설치한다. 기존 운영 컨테이너를 중지하지 않는다.
2. 기존 EC2 ID, SSM Online, instance role, `/opt/keepgo/cloud`의 origin·fetch 읽기 인증, Compose project `keepgo-v1` 및 서비스 이름을 확인한다. Docker Compose는 `config --no-env-resolution`과 `config --hash`를 지원해야 한다. Python 3.10+, AWS CLI, Bash, flock, Git, tar가 필요하다.
3. main이 사용하던 env/JWT/TLS/ACME/업로드 파일과 권한을 유지한다. `prepare-runtime.py`는 초기 준비·명시적 Secret 갱신용이며 일반 자동 배포에서 실행하지 않는다. 앱은 호스트의 env·JWT 파일을 읽는다.
4. 현재 운영 이미지 SHA와 Manifest가 일치하는지 확인한다. 다르면 실제 상태와 배포 이력을 확인해 먼저 바로잡는다. 최신 로컬 App SHA를 운영 버전으로 추정하지 않는다.
5. ECR 읽기 권한과 `SOURCE_READ_TOKEN`을 가진 환경에서 `python scripts/pin-manifest.py`를 실행한다. 기존 SHA의 digest와 Backend 성공 CI run ID를 조회한다. `python scripts/validate-manifest.py`로 검사하고 변경된 JSON을 검토·main에 반영한다. 조회 실패 시 null을 임의 값으로 채우지 않는다.
6. `deployment/runtime.example.json`을 호스트 `/opt/keepgo/runtime.json`으로 준비한다. 실제 HTTPS origin, state 경로, 선택적인 SNS·알람을 입력한다. health·연결·HTTPS 검사 범위를 확인한 뒤 `app_checks_confirmed=true`로 설정한다. state 디렉터리와 runtime 파일은 root만 접근하도록 관리한다.
7. GitHub 설정을 연결하고 `CD_SETUP_READY=true`, `CD_ENABLED=false` 상태에서 main의 Deploy production을 `mode=adopt`로 한 번 실행한다. digest·Compose config hash·health·연결 검사가 맞아야 current.json을 생성한다. 컨테이너를 재생성하지 않는다. 해시 불일치를 무시해 채택하지 말고 실제 Compose 설정, 런타임 파일, Compose 버전 차이를 조사한다.
8. Backend 배포·실패 복구 검증을 마친 뒤 `CD_ENABLED=true`로 후보 수신과 main 자동 배포를 활성화한다. adopt 전에 intake를 켜면 기준 Manifest가 먼저 바뀔 수 있다.

## 2. GitHub 연결

| 종류 | 이름 | 용도 |
| --- | --- | --- |
| Variable | CD_SETUP_READY, CD_ENABLED | 준비 완료 / 후보 수신·자동 배포 활성화 |
| Variable | CD_APP_ID, CD_BOT_LOGIN | Cloud에 설치한 GitHub App ID와 정확한 bot login |
| Secret | CD_APP_PRIVATE_KEY | Cloud 후보 PR·정책 검사용 App 인증 |
| Secret | SOURCE_READ_TOKEN | Backend Contents/Actions read |
| Variable | AWS_ACCOUNT_ID | 602601433533 |
| Variable | AWS_DEPLOY_ROLE_ARN, AWS_VERIFY_ROLE_ARN | SSM 실행 / ECR 검증 OIDC 역할 |
| Variable | PRODUCTION_EC2_INSTANCE_ID | 기존 호스트 |
| Variable | SNS_TOPIC_ARN | 선택적 실패 알림 |
| Variable | MONITOR_ENABLED, AWS_MONITOR_ROLE_ARN, PUBLIC_ORIGIN | 선택적 외부 감시 |

App에는 Contents/PR/Commit statuses read/write가 필요하다. main은 PR 필수·최신 base 요구·force push 및 bypass 금지로 보호한다. `configuration`과 `release-policy`를 필수 검사로 등록한다. 기존 main의 `Validate manifest and compose` 검사도 호환용으로 유지했다. release-policy 상태의 발행자는 해당 GitHub App으로 제한한다. native auto-merge와 squash merge를 활성화한다.

일상 App 배포에 별도 사람 승인을 추가하지 않도록 전역 최소 승인 수는 0으로 두며 플랫폼 PR 승인은 release-policy가 강제한다. production Environment는 main만 허용하고 일상 배포 required reviewer는 두지 않는다. 최초 설치·설정은 담당자가 검토한다. 준비 전 release-policy가 skip되므로 필수 검사 등록 시점을 설치 순서에 맞춘다.

Backend에 `examples/app-notify-cloud.yaml`을 설치하면 성공 CI 직후 dispatch한다. 설치하지 않아도 Cloud의 10분 polling이 최신 Backend main의 성공 CI를 조회한다. 현재 BE CI는 dev도 게시하지만 Cloud는 dev를 거부한다. CI job 성공은 현재 구성상 빌드·게시 성공이며 테스트 통과를 뜻하지 않는다.

S3와 DEPLOY_BUCKET은 필요 없다. `infrastructure/cd-access.yaml`은 기존 역할·권한과 비교해 change set으로 적용한다. EC2의 ECR read, SSM, 선택적 CloudWatch/SNS 권한과 Git 읽기 인증을 확인한다. 이 작업에서 AWS 리소스를 생성하지 않았다.

## 3. 정상 배포

Backend CI → 후보 PR → configuration/release-policy → 자동 병합 → Deploy production → SSM 결과를 확인한다. SSM command ID와 Cloud commit은 Actions summary에 기록된다. 성공은 SSM `Success`와 `ResponseCode=0`, 호스트 결과로 판단한다.

호스트는 신·구 Backend 이미지를 서비스 중지 전에 pull한다. 다른 세 컨테이너는 재생성하지 않으며 Nginx 프로세스에 reload만 요청한다. 이미지/설정 차이가 없으면 실제 상태를 재검증하고 noop으로 기록한다. Secret·env·JWT 변경은 자동 이미지 배포와 별도 점검으로 처리한다.

## 4. 실패와 복구

| mode | 역할 |
| --- | --- |
| deploy | 현재 main의 검증된 목표로 Backend 배포 |
| adopt | 기존 네 서비스 검증 후 최초 current 생성 |
| freeze | 후속 일반 배포 동결 |
| rollback | 마지막 성공 Backend 교체의 이전 구성으로 복구 |
| recover | 남은 inflight의 이전 구성 복구, 없으면 current 재검증 |
| resume | journal 없음·목표/현재 일치·검증 성공 후 동결 해제 |

1. 필요하면 CD_ENABLED=false로 intake·자동 배포를 멈춘다. 감시가 연결되어 있다면 유지한다.
2. SSM invocation, current/inflight/result/history와 실제 컨테이너를 확인한다. timeout만 보고 원격 작업이 끝났다고 판단하지 않는다. 진행 중인 작업과 경쟁 배포를 시작하지 않는다.
3. 자동 복구 성공인 rolled_back과 신규 배포 성공을 구분한다. 복구 실패·중단은 frozen/journal을 유지하고 recover를 사용한다.
4. 실패한 Backend의 SHA·digest·sources만 검증된 current 값으로 맞추는 정합화 PR을 작성한다. 이후 들어온 수정 후보를 덮어쓰지 않는다.
5. recover/rollback 뒤에는 검증·정합화 후 resume하고 intake를 재개한다. blocked.json은 임의 삭제하지 않는다. 같은 실패 digest는 Cloud commit이나 CI run ID만 바꿔도 다시 배포되지 않는다.

current가 없는 최초 상태는 자동 배포가 거부된다. 강제로 빈 상태를 정상 버전으로 기록하지 않는다. DB schema는 이미지 롤백으로 되돌리지 않으며 구버전 호환성은 App 변경 단계에서 확인한다.

## 5. 모니터링과 인수

main의 json-file 로그와 회전 설정을 유지한다. 현재 CloudWatch 앱 로그 전송기는 설치하지 않았으므로 HTTP 오류 로그 알람이 수집된다고 가정하지 않는다. `bootstrap-host.sh`는 runtime·adopt 후 선택적으로 host monitor를 설치한다. 외부 감시는 HTTPS `/`와 `/healthz`를 본다. Worker·큐 지표는 없다.

runtime의 SNS ARN과 deployment_alarm_names는 기본적으로 비어 있다. 이 경우 알람 기반 배포 차단은 없으며 Actions/SSM과 컨테이너·연결·HTTPS 검사를 사용한다. 실제 알람을 연결하면 등록한 알람 전부가 OK여야 배포한다. 모니터링 template의 DeploymentAlarmNames는 컨테이너 재시작 알람이다.

실환경 인수: adopt 성공/불일치 거부, Backend만 변경, digest 불일치 거부, pull 실패 시 서비스 유지, health 실패 후 복구, 복구 실패 동결, SSM 중단 후 recover, Secret 변경 거부, 선택적 알람 수신을 확인한다. App/Cloud SHA·digest·CI/SSM ID·실제 상태·시간을 증거로 남긴다.
