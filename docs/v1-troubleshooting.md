# v1 중앙 CD 트러블슈팅

> 2026-09-29 기준 준비 단계의 점검 문서다. 아래 항목은 저장소의 코드와 인계 내용에서 확인한 **예상 증상과 대응 절차**이며, 실제 운영 장애가 발생했다는 기록은 아니다. 현재 Worker 이미지는 미게시, 앱 검사 계약은 미확정, S3는 미사용이다. 기존 EC2는 팀원이 운영 중이므로 상태 확인 없이 배포하거나 컨테이너를 교체하지 않는다.

실제 배포·복구는 [운영 Runbook](v1-operations.md)과 [현재 환경 인계](v1-handoff-2026-09-28.md)를 따른다. 조사 기록에는 시각, Cloud/App commit SHA, 이미지 digest, GitHub Actions run ID, SSM command ID, 현재 실행 이미지와 확인 결과를 남긴다. Secret·토큰·전체 환경변수는 기록에 넣지 않는다.

## 1. 후보 PR이나 배포 Job이 실행되지 않음

**증상:** App 이미지 게시 뒤 Cloud Manifest PR이 생기지 않거나 `Receive image candidate` / `Deploy production` Job이 `skipped`로 표시된다.

**확인:** 먼저 Actions의 실행 조건을 본다. 후보 수신은 `CD_SETUP_READY=true`와 `CD_ENABLED=true`가 모두 필요하다. 배포는 `CD_SETUP_READY=true`에 더해 자동 실행 시 `CD_ENABLED=true`가 필요하고, `main` 변경 또는 수동 실행이어야 한다. 두 스위치를 꺼 두었다면 `skipped`는 준비 보류에 따른 정상 결과다. 스위치가 켜져 있다면 App의 성공한 `main` CI, SHA 이미지 게시, dispatch 수신, `source-policy.json`의 저장소·workflow·필수 job 이름을 순서대로 대조한다.

**조치:** 누락된 설정이나 App CI 계약을 먼저 맞춘다. Worker 이미지와 검사 계약, 전달 방식이 준비되기 전에는 실행을 위해 스위치만 켜지 않는다. 자세한 활성화 조건은 [파일별 사용법](v1-files-and-push-guide.md)을 본다.

## 2. SSM 배포 전에 S3 전달 단계에서 멈춤

**증상:** `DEPLOY_BUCKET` 입력 오류, `aws s3 cp` 실패, 묶음 다운로드 실패가 발생한다.

**원인:** 현재 `.github/workflows/deploy-production.yaml`과 `scripts/ssm-deploy.py`는 S3로 release 묶음을 전달하는 초안이다. 인계된 운영 환경은 S3를 사용하지 않는다. 따라서 이 오류를 단순한 권한 누락으로 보고 S3 버킷을 생성하거나 권한을 늘리는 것은 현재 계획과 맞지 않는다.

**조치:** 실행을 보류한다. EC2의 기존 Cloud checkout 경로, 읽기 인증 방식, SSM Online 상태를 확인한 뒤 [인계 문서의 S3 없는 전달 절차](v1-handoff-2026-09-28.md)를 구현·검증한다. 전달 코드와 workflow의 `DEPLOY_BUCKET` 의존성도 함께 제거해야 한다.

## 3. 이미지 pull 또는 최초 Compose 기동 실패

**증상:** ECR에 이미지가 없다는 오류가 나거나 Worker 컨테이너를 시작하지 못한다.

**확인:** ECR 저장소의 존재와 목표 SHA 태그의 게시 여부를 구분한다. 현재 전달된 목록에는 `keepgo-ai`, `keepgo-backend`, `keepgo-nginx`, `keepgo-web`만 있고 Worker 이미지는 미게시다. Manifest의 각 SHA·CI run ID, 실제 ECR 이미지, Worker의 소스·Dockerfile·실행 명령을 확인한다. 기존 EC2의 Compose project 이름과 실행 컨테이너도 확인한다.

**조치:** 담당 App 팀이 이미지를 게시하고 계약을 확정할 때까지 최초 5개 서비스 배포를 보류한다. 기존 EC2의 실행 상태를 검증하지 않은 채 새 Compose 구성을 적용하지 않는다. 최초 이전 절차는 [운영 Runbook의 ‘최초 이전’](v1-operations.md)을 따른다.

## 4. Health/Smoke 실패 또는 배포가 검사 단계에서 거부됨

**증상:** `App health/smoke/queue contracts are unconfirmed`, `Container not healthy`, `Application smoke contract failed`, `A deployment alarm is missing, not OK, or has insufficient data`가 나온다.

**확인:** `app_checks_confirmed`가 `false`이면 `freeze`를 제외한 배포·복구 검증은 의도적으로 시작되지 않는다. `true`인 환경에서 실패했다면 실제 이미지의 healthcheck, Backend smokecheck, Worker queue 검사, `/api/health/ready` 응답과 `deployment_alarm_names`의 CloudWatch 상태를 확인한다. 현재 Compose의 healthcheck는 주석 상태이고 앱 검사는 제안 계약이므로, 이 명령들이 이미지에 있다고 가정하지 않는다.

**조치:** App 담당자가 실제 검사 방법과 성공 기준을 확인한 뒤 코드·Compose·runtime을 함께 맞춘다. 알람이 없거나 `INSUFFICIENT_DATA`이면 지표 수집과 알람 설정을 점검한다. 검사를 무조건 성공하도록 바꾸거나 계약 확인 전 `app_checks_confirmed`만 `true`로 변경하지 않는다.

## 5. SSM timeout, 롤백 또는 동결 상태

**증상:** Actions의 SSM 관찰이 timeout이거나 `rolled_back`, `rollback_failed`, `Deployment frozen or interrupted transaction requires recovery`가 기록된다.

**확인:** Actions 실패만으로 원격 명령의 종료를 판단하지 않는다. SSM invocation의 최종 상태와 종료 코드, 호스트의 `/opt/keepgo/state/current.json`, `inflight.json`, `result.json`, `frozen.json`, 실제 컨테이너 이미지·health를 함께 대조한다. `rolled_back`은 이전 구성 복구 성공이지 새 배포 성공이 아니다. `rollback_failed`나 최초 배포 실패에는 검증된 자동 복구 목표가 없을 수 있다.

**조치:** 원격 작업이 진행 중이면 경쟁 배포를 시작하지 않는다. 미완료 작업은 상태 확인 후 Runbook의 `recover`, 실패 단위의 복구와 Manifest 정합화, 검증 후 `resume` 순서를 따른다. `blocked.json`이나 journal을 임의로 삭제하지 않는다. 복구가 다시 실패하면 동결을 유지하고 EC2·RDS·Secret·TLS 원인을 조사한다.
