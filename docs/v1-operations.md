# v1 설치·배포·장애·롤백 Runbook

> **2026-09-28 현재 상태:** Worker 이미지는 미게시, 앱 검사 계약은 미확정, S3는 미사용이다. 검사 주석 처리와 준비 확인에 따른 실행 보류가 적용되어 있다. 기존 EC2는 팀원이 운영 중이다. [최신 인계·추가 정보](v1-handoff-2026-09-28.md)와 [파일별 사용법·푸시 지침](v1-files-and-push-guide.md)을 먼저 읽는다. 아래 기존 S3 설치·검사 활성화·최초 스택 교체 절차는 현재 그대로 실행하지 않는다.

운영 값과 App 구현은 아직 확인되지 않았다. 아래 설치·실환경 인수 시험을 완료한 뒤 운영 구축 완료로 판정한다.

## 1. 설치

### App 및 이미지

1. [App 계약](v1-app-contracts.md)의 healthcheck/smokecheck/queue-metrics, Worker graceful shutdown을 구현한다.
2. 후보 Backend+현재 Worker, 현재 Backend+후보 Worker 조합과 schema/payload 호환성을 검사한다.
3. Frontend의 실제 TLS 경로, proxy upstream, Node port, JSON log를 확인한다.
4. ECR SHA tag IMMUTABLE을 설정하고 현재/이전 성공 이미지를 보존한다.
5. source-policy.json에 실제 저장소·workflow 경로·필수 job 표시 이름·ECR 이름을 입력한다.
6. production-manifest.json의 모든 SHA/run_id를 성공한 main push CI 값으로 채운다. 첫 전체 Manifest는 사람이 검토한다.

Frontend CI만으로는 ECR 변수의 실제 값과 health 구현까지 확인할 수 없다. AI 모델/Secret 설정도 실제 이미지에서 지원하는지 확인한다.

### AWS

기존 EC2/RDS/VPC/ECR를 재생성하지 않는다. 리전은 ap-northeast-2다.

1. infrastructure/monitoring.yaml에 InstanceId, DBInstanceIdentifier, AlarmEmail을 입력해 change set을 검토·적용한다. 동일 이름 기존 log group/SNS는 삭제하지 않고 import 또는 기존 자원 참조로 조정한다.
2. SNS 이메일 구독 확인과 실제 알람 수신 시험을 수행한다.
3. infrastructure/cd-access.yaml에 OIDC provider ARN, EC2 ID/role 이름, SNS ARN, 정확한 App Secret ARN 목록을 입력해 IAM change set을 검토·적용한다.
4. role/bucket 출력값을 GitHub variables에 등록한다.
5. EC2 role에는 AmazonSSMManagedInstanceCore도 필요하다. Secret에 고객 관리 KMS key를 쓰면 제한된 decrypt 권한도 부여한다.
6. ECR 이름이 keepgo-*가 아니면 IAM resource 범위를 실제 repository ARN으로 수정한다.

```sh
aws cloudformation validate-template --template-body file://infrastructure/monitoring.yaml --region ap-northeast-2
aws cloudformation validate-template --template-body file://infrastructure/cd-access.yaml --region ap-northeast-2
```

EC2 일반 inbound는 80/443, 관리 접속은 SSM을 사용한다. RDS 3306은 EC2 보안그룹에서만 허용하며 public accessibility를 끈다. EC2에서 ECR/S3/SSM/Logs/Secrets/CloudWatch와 외부 API로 접근 가능해야 한다.

컨테이너 SDK가 EC2 role로 Secret을 읽으면 IMDSv2 required와 hop limit 2가 필요할 수 있다. 단일 EC2 App이 instance role을 공유한다는 v1 권한 경계를 인지한다. [AWS 설명](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html).

### EC2

Linux Docker Engine, Compose v2 이상, AWS CLI v2, Python 3.10 이상, SSM Agent, systemd, curl이 필요하다. Docker 부팅 시작과 EBS 암호화, state 디렉터리 백업을 설정한다.

```sh
sudo install -d -m 0700 /opt/keepgo
sudo cp deployment/runtime.example.json /opt/keepgo/runtime.json
# account, SNS ARN, HTTPS origin, deployment_alarm_names를 실제 값으로 편집
sudo bash scripts/bootstrap-host.sh
sudo systemctl status keepgo-monitor.timer
sudo journalctl -u keepgo-monitor.service --since '10 minutes ago'
```

deployment_alarm_names는 monitoring stack의 DeploymentAlarmNames 출력을 배열로 입력한다. public_origin은 경로 없는 운영 HTTPS origin이다. 기본 health timeout 180초, bake 60초이며 허용 범위는 각각 30~300초다. log group과 /opt/keepgo/tls 인증서를 컨테이너 시작 전에 준비한다. monitor 코드 변경 후 bootstrap을 재실행해 설치된 ops 파일을 갱신한다.

### GitHub

| 종류 | 이름 | 값 |
| --- | --- | --- |
| Variable | CD_ENABLED | 설치 중 false, 인수 후 true |
| Variable | MONITOR_ENABLED | 외부 감시 설치 후 true; CD 동결과 독립 |
| Variable | CD_APP_ID, CD_BOT_LOGIN | App ID와 정확한 slug[bot] |
| Secret | CD_APP_PRIVATE_KEY | Cloud에 설치한 GitHub App private key |
| Secret | SOURCE_READ_TOKEN | App 저장소 Contents/Actions read 전용 token |
| Variable | AWS_ACCOUNT_ID | 12자리 account |
| Variable | AWS_DEPLOY_ROLE_ARN, AWS_VERIFY_ROLE_ARN, AWS_MONITOR_ROLE_ARN | stack 출력 |
| Variable | PRODUCTION_EC2_INSTANCE_ID, DEPLOY_BUCKET, SNS_TOPIC_ARN | 실제 운영 리소스 |
| Variable | PUBLIC_ORIGIN | https://운영호스트 |

GitHub App은 Cloud의 Contents/PR/Commit statuses read/write, Metadata read 권한이 필요하다. source token은 App 조회만 허용한다. 각 App에 examples/app-notify-cloud.yaml과 Cloud dispatch용 App 인증을 설치한다. App ECR role은 운영 SSM을 호출할 수 없어야 한다.

main 보호 규칙:

- PR 필수, 직접 push/force push 금지, 관리자/봇 bypass 없음.
- 필수 검사 configuration, release-policy와 최신 base 요구.
- release-policy의 예상 작성자를 CD GitHub App으로 제한.
- 전역 최소 사람 승인 수 0. 사람 PR 승인은 신뢰된 release-policy가 현재 head에 대해 강제한다. 전역 승인 1건은 자동 Manifest PR도 막는다.
- native auto-merge와 squash merge 활성화. 저장소 요금제/공개 범위에서 지원되는지 확인한다. 미지원이면 대체 경로 구현 전에 CD_ENABLED를 켜지 않는다.
- production Environment는 main만 허용하며 일상 배포의 required reviewer는 두지 않는다.

초기 설치 PR은 main에 gate 코드가 없으므로 담당자 검토로 설치하고 보호 규칙을 활성화한다. 이후 사람 PR은 다른 maintainer의 현재-head 승인 후 Release policy 실행을 재실행한다. PR review 이벤트를 이용해 임의 branch workflow에 secret을 제공하지 않는다.

### 최초 이전

기존 컨테이너가 있고 current.json이 없으면 자동 채택하지 않고 거부한다. 점검 시간을 잡고 기존 Compose·digest·설정·DB backup/복구 경로를 확보한다. 미검증 상태를 LKG로 임의 기록하지 않는다.

담당자가 기존 스택을 정리한 후 새 5개 컨테이너 구성으로 첫 배포한다. 볼륨/RDS 데이터 삭제는 필요하지 않다. 기존 project/network/service 명칭 충돌을 확인한다. 최초 이전은 일반 App 교체와 별도 점검이다.

workflow_dispatch의 deploy는 CD_ENABLED=false여도 명시적으로 실행 가능하다. 최초 성공 시 current.json이 생성된다. 실패 시 이전 LKG가 없으므로 동결하고 기존 백업 구성으로 수동 복구한다. 초기 실패 journal 정리는 실제 상태를 확인하고 파일을 보존한 뒤 담당자가 수행한다.

## 2. 정상 배포

App main CI → 후보 PR → 자동 병합 → Deploy production을 확인한다. SSM command ID는 Actions summary/artifact에 남긴다. Cloud commit 묶음을 SHA256으로 확인하고 EC2에서 실행한다. EC2가 git main을 다시 pull하지 않는다.

SSM 전달 timeout 120초, 실행 5400초, 관찰 5700초, workflow 100분이다. 엔진은 2400초 이후 새 단위 시작을 거부해 복구 시간을 남긴다. 일반 배포가 최대 시간까지 걸리면 SSM/health 상태를 조사한다.

SSM Success와 ResponseCode=0을 모두 확인한다. send-command 성공이나 컨테이너 Up만으로 성공 처리하지 않는다. 상세 App 로그는 CloudWatch, 실제 상태는 current/inflight/result를 확인한다.

## 3. 알람과 초기 대응

| 알람 | 초기값 | 확인 |
| --- | --- | --- |
| EC2 status | 2회 실패 | AWS/호스트 |
| HostHeartbeat | 3분 결측 | probe·네트워크·EC2 |
| ServiceHealthy | 2분 실패 | health·DB 접근 |
| ExternalHealthy | 5분 구간 3개 중 2개 실패/결측 | DNS/TLS/Nginx/API, GitHub schedule |
| journal 잔류 | 3300초 | SSM 실제 상태 |
| 재시작 | 5분 3회 | OOM/로그 |
| DB job 대기 | 300초 초과 3회 | Worker·lease·AI |
| DB 최종 실패 | 5분 5건 | 오류별 원인 |
| 디스크/메모리 | 85%/90% 3분 | 이미지·로그·메모리 |
| RDS storage/CPU | 5GiB 미만/85% 5분 | DB 용량·쿼리 |
| HTTP5xx/AI timeout/Worker error | 5분 5/3/5건 | request/job ID |
| SSM 실패/timeout/cancel | EventBridge | host journal |

담당자와 보조 담당자 이메일을 실제 구독한다. 초기 목표는 알림 확인 5분, 판별/동결 10분이며 온콜 여건에 맞게 조정한다. 전체 장애·롤백 실패·장기 미완료 배포를 긴급으로 처리한다.

3300초 미만 진행 journal은 로컬 health/queue 검사를 잠시 억제한다. HostHeartbeat, EC2/RDS, 외부 HTTPS, 5xx, SSM 알림은 유지한다. 중단 배포의 일시 502는 가능하다. 전체 알람을 끄지 않는다.

## 4. 자동 롤백 후 정합화

1. rolled_back과 SSM 실패 확인. 이전 버전 복구와 신규 배포 성공은 다르다.
2. 필요 시 CD_ENABLED=false로 신규 intake/자동 배포 중단. MONITOR_ENABLED 유지.
3. current.json의 현재 조합과 최신 main 비교. 이전 Manifest 전체 복사는 금지한다.
4. 실패 단위만 current의 SHA/sources로 정합화하는 사람 PR을 작성한다. 이후 들어온 새 수정 후보는 덮어쓰지 않는다.
5. 현재-head 리뷰, Release policy 재실행, 병합. 수정된 App main CI 성공 후 intake 재개.

blocked.json은 자동 삭제하지 않는다. 실패 digest는 Cloud commit/run ID만 바꿔도 거부된다. polling이 최신 App main을 후보로 삼으므로 실패한 App main 그대로 intake를 재개하지 않는다.

## 5. 수동 복구와 동결

main의 Deploy production workflow_dispatch에서 mode를 선택한다. CD_ENABLED=false여도 명시적 복구가 가능하며 동일 host lock을 사용한다.

| mode | 동작 |
| --- | --- |
| freeze | 후속 일반 배포 거부 marker 생성 |
| rollback | 마지막 성공 단위의 이전 조합 복구, 되돌린 신규 이미지 차단 |
| recover | 미완료 journal의 old 복구; journal 없으면 current 재검증 |
| resume | journal 없음, Git 목표=current, 검증/알람 성공 후 동결 해제 |
| deploy | 최신 main 목표에서 변경 단위만 실행 |

복구 성공 뒤에도 frozen을 유지한다. 정합화 PR → resume → 자동 CD 재개 순서를 따른다. SSM/Runner timeout 뒤에는 새 배포를 반복하지 않는다. invocation 상태·실제 digest/health·journal을 확인한다. 다른 작업의 lock이 있으면 기다리고 프로세스가 끝난 미완료 journal은 recover한다.

복구 재실패는 동결을 유지하고 EC2/RDS/Secret/TLS를 조사한다. 배포 코드 자체가 문제면 EC2의 이전 알려진 release 스크립트를 SSM으로 실행하되 같은 state lock을 사용한다. journal/blocked를 무작정 지우지 않는다.

DB 파괴적 변경은 이미지 복구로 해결하지 않는다. DB 책임자가 쓰기 중단·복원 시점·손실 범위·PITR/새 RDS 연결을 판단한다. snapshot을 즉시 자동 롤백으로 사용하지 않는다.

## 6. 운영 인수 시험

- 각 단위 정상 배포, Backend/Worker 서로 다른 SHA 유지.
- Frontend 쌍 교체, HTTPS/정적 asset 확인.
- 실패 CI·skip job·없는 이미지·낡은 SHA·허용 밖 변경 거부.
- 동시 후보 직렬화, 이미지 pull 실패 시 기존 컨테이너 유지.
- Backend health 실패 후 Backend만 복구.
- Backend 성공/Worker 실패 시 새 Backend 유지, Worker만 복구.
- 롤백 실패 시 frozen/journal과 SNS 수신.
- Worker 강제 종료 후 DB lease 회수 및 사용자 효과 중복 방지.
- SSM/Runner 중단 후 상태 확인과 recover/resume.
- probe 정지·HTTPS 실패·오류 로그·RDS 임계 알람 수신.

시험마다 App/Cloud SHA, digest, CI/SSM ID, 시간, 실제 상태, 알림 수신 증거를 보관한다. 실환경 시험 전에는 운영 구축 완료로 표시하지 않는다.
