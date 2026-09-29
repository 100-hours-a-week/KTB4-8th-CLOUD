# v1 구현 및 검증 현황

> **2026-09-28 현재 상태:** Worker 이미지는 미게시, 앱 검사 계약은 미확정, S3는 미사용이다. 검사 주석 처리와 준비 확인에 따른 실행 보류가 적용되어 있다. 기존 EC2는 팀원이 운영 중이다. [최신 인계·추가 정보](v1-handoff-2026-09-28.md)와 [파일별 사용법·푸시 지침](v1-files-and-push-guide.md)을 먼저 읽는다. 아래 기존 S3 설치·검사 활성화·최초 스택 교체 절차는 현재 그대로 실행하지 않는다.

작성일: 2026-09-27. 저장소 구현과 로컬 검사 완료. **AWS/GitHub 운영 활성화 및 실환경 인수는 미완료**다.

## 적용한 변경

| 영역 | 구현 |
| --- | --- |
| Compose | Node Web과 Nginx 분리, 5개 컨테이너, 이미지별 healthcheck, Worker 종료 유예 및 DB queue 설정 |
| 배포 단위 | Backend와 Worker 독립 버전·교체·복구. Frontend는 CI의 Web/Nginx 쌍 |
| 후보 수신 | 성공 App main CI 알림, 출처/필수 job/ECR 검증, Manifest PR, 자동 병합, 누락 요청 polling |
| 보호 | 봇 변경 범위 제한, 사람 변경의 현재-head maintainer 승인, 신뢰된 main 코드로 정책 검사 |
| 중앙 CD | main 자동 실행, OIDC, S3의 검증된 코드 묶음, SSM 상태/종료 코드 확인 |
| EC2 | flock, 진행 journal, digest Compose, 변경 단위 stop/recreate, 이미지 사전 pull |
| 검증 | 컨테이너 health/digest, HTTPS, App DB job smoke, 재시작 관찰, 배포 알람 상태 |
| 복구 | 실패 단위만 이전 구성 복구, 성공한 다른 단위 보존, 실패 digest/config 차단, 복구 실패 동결 |
| 수동 운영 | freeze/rollback/recover/resume, Manifest 정합화, 최초 이전 및 DB 복구 절차 |
| 모니터링 | EC2 timer, 외부 HTTPS, CloudWatch logs/metrics/alarms, SSM EventBridge, SNS email |
| AWS 정의 | monitoring 및 CD IAM/OIDC/S3 CloudFormation template |
| 문서 | 설계, App 계약, 운영 절차, 기존 제안의 보관 상태 표시 |

## 로컬 검사

- Python 단위/실패 시나리오 **28개 통과**: 서비스별 차이 계산, Backend/Worker 독립 SHA, 부분 성공 보존, pull 실패, rollback 성공/실패, 최초 배포 실패, journal 복구, 실패 config 재진입 차단, alarm 및 재시작 판정, CI 출처/skip 검사.
- `python scripts/validate-manifest.py --structure-only` 통과: Docker Compose config 렌더링 및 Manifest 구조.
- Python compile 검사, 두 Bash 스크립트 개별 syntax 검사, Git whitespace 검사 수행.
- 로컬 Python 외부 패키지 설치 없이 표준 라이브러리로 실행한다.

## 실제 환경에서 남은 작업

1. source-policy의 실제 App 저장소/workflow/job/ECR 이름과 Manifest SHA/run_id 입력.
2. App 이미지에 healthcheck/smokecheck/queue-metrics 구현 및 DB lease/멱등성 검증.
3. GitHub App/token, branch protection, auto-merge 제공 조건, Environment/OIDC 설정.
4. CloudFormation 서버 검증/change set 검토 및 리소스 설치, runtime.json과 EC2 monitor 설치.
5. 실제 Nginx 라우팅/TLS, RDS/Secret 접근, 이미지 digest 실행 검증.
6. 정상 배포·부분 실패·롤백 실패·SSM 중단·DB job 회수·알람 수신 인수 시험.

Docker daemon이 실행되지 않아 컨테이너 통합 시험과 actionlint 컨테이너를 로컬에서 실행하지 못했다. Workflow에는 actionlint 검사를 추가했다. CloudFormation API 및 GitHub/AWS 실환경 권한도 확인하지 않았으므로 해당 검증이 통과했다고 주장하지 않는다.

## 경계와 운영 결정

- DB migration은 실제 App schema에 맞게 검토·선적용하는 계약이며 임의의 migration SQL을 실행하지 않는다.
- 롤백 후 목표 Manifest 정합화는 검토된 사람 PR로 수행한다. 자동 정합화 봇까지 구현하지 않았다.
- GitHub scheduled polling/probe는 지연 가능하다. 외부 장애 탐지의 엄격한 시간 SLA는 없다.
- 최초 배포는 검증된 이전 상태가 없어 자동 복구할 수 없다. 기존 운영 스택 이전은 별도 점검이다.
- AWS 리소스 생성, 실제 배포, git commit/push는 이번 로컬 작업에서 수행하지 않았다.

자세한 설치·인수 순서는 [운영 Runbook](v1-operations.md)을 따른다.
