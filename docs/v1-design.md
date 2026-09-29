# v1 설계 및 기술 결정

> **2026-09-28 현재 상태:** Worker 이미지는 미게시, 앱 검사 계약은 미확정, S3는 미사용이다. 검사 주석 처리와 준비 확인에 따른 실행 보류가 적용되어 있다. 기존 EC2는 팀원이 운영 중이다. [최신 인계·추가 정보](v1-handoff-2026-09-28.md)와 [파일별 사용법·푸시 지침](v1-files-and-push-guide.md)을 먼저 읽는다. 아래 기존 S3 설치·검사 활성화·최초 스택 교체 절차는 현재 그대로 실행하지 않는다.

상태: 2026-09-27 저장소 구현. 실서비스 적용 전제는 [운영 절차](v1-operations.md)에서 확인한다. 이 문서가 이전 독립 CD 제안과 v1 작업 계획보다 우선한다.

## 1. 확정 범위

| 항목 | 결정 |
| --- | --- |
| 런타임 | 단일 EC2, Linux amd64, Docker Compose |
| 컨테이너 | nginx:80/443, web:3000, backend:8080, worker, ai-api:8000 |
| 외부 노출 | nginx만 호스트 80/443 바인딩 |
| 데이터베이스와 job 큐 | 외부 MySQL RDS. Worker가 DB polling 및 lease 방식으로 처리 |
| 사용자 결과 수신 | HTTP polling. SSE 없음 |
| 배포 | 중앙 Cloud Repository 자동 실행, 변경 서비스 중단 허용 |
| 제외 | ECS, 별도 메시지 큐, rolling, Blue/Green, 무중단 보장 |

사용자가 제공한 Frontend CI는 `.next/standalone/server.js`를 확인하고 `Dockerfile`, `Dockerfile.nginx`로 두 이미지를 같은 SHA에 게시한다. Node와 Nginx는 별도 컨테이너다. ECR 이름·실제 실행 경로·Nginx proxy 설정은 App 저장소에서 최종 확인한다.

## 2. 배포 단위

| 단위 | 서비스 | 버전과 교체 |
| --- | --- | --- |
| frontend | web, nginx | 같은 Frontend SHA, 한 단위로 중지·교체·복구 |
| backend | backend | Backend만 교체, Worker 유지 |
| worker | worker | Worker만 교체, Backend 유지 |
| ai | ai-api | AI만 교체 |

Backend와 Worker가 같은 Git 저장소에서 빌드되어도 Manifest SHA와 CI run ID는 별개다. 동일 SHA 강제 규칙이 없다. 여러 변경이 누적되면 AI → Backend → Worker → Frontend 순으로 각각 배포·검증·성공 기록한다. Worker 실패는 이미 검증된 Backend 배포를 되돌리지 않는다. 실패 이후 남은 단위는 실행하지 않는다.

변경 판단은 PR diff가 아니라 검증된 실제 Compose와 목표 전체의 차이로 한다. 환경변수·헬스 검사·종료시간 변경도 대상이다. 공통 network/volume/secret/config 정의 변경은 자동 배포에서 거부하고 계획된 플랫폼 점검으로 처리한다.

`stop <변경 단위>` 후 `up -d --no-deps --force-recreate <service>`를 실행한다. 다른 서비스 컨테이너는 재시작하지 않는다. Backend 주소 변경 시 Nginx에 graceful reload를 수행한다. Backend/AI 연결 풀도 서비스명을 재조회해야 한다.

## 3. 중앙 자동 CD

1. App은 테스트와 이미지 게시를 담당하며 운영 SSM 권한을 갖지 않는다.
2. 성공한 main push CI의 별도 `workflow_run` 알림이 Cloud에 dispatch한다. 게시 job 안에서 보내면 원본 CI가 진행 중이므로 거부된다.
3. Cloud는 허용 App 작성자·저장소·workflow·SHA·main push·전체 CI 성공·필수 job별 성공·ECR 이미지를 검증한다. 소스 미준비로 job이 skip된 CI는 받지 않는다.
4. 최신 App main SHA만 새 후보로 허용한다. 10분 polling은 pending run 교체와 알림 누락을 보완한다.
5. 봇 PR은 Manifest 한 파일, 한 배포 단위만 수정한다. Backend와 Worker는 별도 PR이다.
6. `configuration`, `release-policy` 필수 검사와 최신 base 조건을 만족하면 native auto-merge한다.
7. Cloud main이 SSM 배포를 시작한다. production Environment는 main만 허용하며 일상 배포에 추가 사람 승인을 두지 않는다.

사람의 플랫폼 코드/복구 Manifest 변경은 현재 PR head에 다른 write/maintain/admin 권한자의 승인이 필요하다. 승인 후 gate를 재실행한다. 봇에게 보호 규칙 우회 권한을 주지 않는다. branch protection 등록은 필수 설치 단계다.

`pull_request_target`은 main의 신뢰된 코드만 실행한다. PR 내용은 API에서 가져온 JSON 데이터로만 읽으며 후보 코드를 checkout/실행하지 않는다. 검증 결과는 확인한 PR head SHA에 commit status로 기록한다.

## 4. 이미지와 상태

Manifest는 SHA tag와 성공 CI run ID를 보관한다. EC2는 ECR digest를 조회해 고정된 digest Compose로 실행한다. ECR의 SHA tag는 IMMUTABLE이어야 한다. App CI와 ECR 게시 권한을 신뢰하는 v1 모델이며, 서명된 공급망 attestation 검증까지 구현한 것은 아니다.

Manifest를 JSON으로 바꿔 EC2 도구의 외부 Python 패키지 의존성을 없앴다. Compose와 CloudFormation은 YAML이다.

| 상태 | 저장 위치 | 의미 |
| --- | --- | --- |
| 목표 | main의 production-manifest.json | 다음에 적용할 이미지/출처 |
| 실제 검증 상태 | /opt/keepgo/state/current.json | 마지막 검증된 전체 조합과 digest Compose |
| 이전 성공 상태 | previous.json | 직전 성공 단위 적용 전 조합 |
| 진행 중 | inflight.json | 변경 단위와 전/후 스냅샷 |
| 실패 금지 | blocked.json | 실패 신규 digest와 구성 fingerprint |
| 동결 | frozen.json | 수동 동결 또는 불확실한 복구 |
| 감사 | history.jsonl, SSM logs, Actions artifacts | 실행 ID, Cloud SHA, 결과 |

이미지뿐 아니라 렌더링한 Compose 설정도 보관한다. 파일 교체는 임시 파일+fsync+rename을 사용한다. 배포 전 컨테이너의 실제 digest/개수도 검사한다. 수동 변경을 검증된 상태로 자동 인정하지 않는다. 상태 디렉터리를 잃으면 EC2 재구축 절차가 필요하다.

GitHub concurrency와 Linux flock을 함께 사용한다. Runner가 사라져도 SSM은 계속 실행될 수 있다. 다음 배포는 잠금/미완료 journal이 있으면 거부한다. 잠금 해제만으로 성공을 추정하지 않는다.

## 5. 검증과 복구

중단 전에 Manifest·출처·알람·실제 digest 검사 및 새 이미지/이전 이미지 pull을 완료한다. 롤백 이미지가 ECR에서 사라졌으면 기존 컨테이너를 내리지 않는다. 자동 image prune은 하지 않는다.

각 단위의 성공 조건:

1. 전체 컨테이너가 예상 digest로 실행되며 healthy.
2. 외부 HTTPS `/`, `/api/health/ready` 200 및 동일 origin.
3. DB → job → Worker → AI → 완료 결과 App smoke 성공.
4. 기본 60초 관찰 중 container ID/재시작 횟수 변화 없음.
5. 마지막 smoke와 지정 배포 알람 OK. 알람 누락/INSUFFICIENT_DATA는 거부.

60초 관찰은 긴 지연 장애까지 보장하지 않는다. 5분 집계 알람은 배포 이후 전환될 수 있어 상시 감시와 수동 복구도 필요하다. 배포와 무관한 시간에 알람만으로 무조건 자동 롤백하지 않는다.

실패한 단위만 직전 검증 상태로 복구하고 health/HTTPS/job/재시작 검사를 반복한다. 복구 판정에는 과거 오류가 남아 있는 집계 알람을 제외한다. 일반 새 배포는 알람이 다시 OK가 될 때까지 차단한다.

복구 성공이어도 원래 배포는 실패다. 실패 digest가 목표에 남아 있으면 다음 배포도 거부된다. 현재 실제 상태와 최신 main을 비교해 실패 단위만 정합화하거나 수정 SHA를 게시한다. 정합화 PR은 사람 검토를 받으며 이후 후보를 덮어쓰지 않는다.

복구 실패/첫 배포 실패는 동결하고 journal을 남긴다. 첫 배포에는 이전 성공 버전이 없다. 스키마와 외부 부수효과는 컨테이너 롤백으로 되돌리지 않는다.

## 6. 관측

CloudWatch Logs/metrics/alarms → SNS 이메일을 사용한다. SNS는 운영 알림용이며 업무 job 큐가 아니다. S3는 배포 묶음과 감사 보관용이다.

EC2 timer는 health, 재시작, DB backlog/실패, 메모리·디스크를 감시한다. 외부 HTTPS는 별도 GitHub runner에서 확인한다. GitHub schedule은 지연될 수 있어 5분 탐지 SLA를 보장하지 않는다. HostHeartbeat와 AWS 기본 EC2/RDS 지표가 별도 감시 경로다.

## 7. 공식 근거

- [Docker Compose healthcheck와 종료 유예](https://docs.docker.com/reference/compose-file/services/)
- [GitHub auto-merge 조건](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request)
- [GitHub 이벤트와 권한 경계](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [SSM 제한 및 상태](https://docs.aws.amazon.com/systems-manager/latest/userguide/monitor-commands.html)
- [SSM invocation 조회](https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_GetCommandInvocation.html)
- [CloudWatch missing data 처리](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarms-and-missing-data.html)
