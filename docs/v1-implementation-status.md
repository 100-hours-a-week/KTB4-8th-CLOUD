# Backend 중앙 자동 CD 구현 및 검증 현황

2026-09-29 병합 기준. 선택·비교·사유는 [단일 기술 결정 기록](technical-decisions.md), 현재 실행 절차는 [운영 문서](v1-operations.md)에 둔다.

**저장소 구현·로컬 검증과 실제 운영 활성화는 구분한다.** AWS/GitHub 설정 변경, EC2 adopt·배포·복구 시험은 수행하지 않았다. Manifest의 digest·Backend CI run ID는 미확인이라 null이며 실제 배포가 거부된다.

## 적용한 변경

| 영역 | 구현 |
| --- | --- |
| Compose | incoming main과 동일한 네 서비스, 실제 앱 환경변수·Secret/JWT·RDS·볼륨·메모리·로그 설정 유지 |
| 버전 | JSON 단일 Manifest. main SHA 보존, digest·CI run ID는 초기 pin 필요 |
| 후보 | Backend main 성공 CI만 수용, digest 고정, 다른 서비스 변경 거부, 후보 PR 자동 병합 |
| 전달 | OIDC·SSM, 고정 main 커밋을 별도 디렉터리에 archive. S3 없음 |
| 초기 연결 | 실제 이미지 ID·Compose config hash·health 검증 후 adopt. 기존 컨테이너 재생성 없음 |
| 교체·복구 | 호스트 잠금, 신·구 이미지 사전 pull, Backend만 교체/롤백, 실패 후보 차단·journal·동결 |
| 검사 | main health, AI/RDS TCP·Frontend HTTP, 외부 HTTPS, 재시작 관찰. Worker/큐 검사 없음 |
| 모니터링 | 선택적 host timer·외부 probe·CloudWatch metrics·SNS. 앱 로그 전송은 미설치 |
| 문서 | 기술 결정 통합 기록, 설계·운영·계약·트러블슈팅 갱신, 과거 인계 문서 표시 |

## 로컬 검사

- Python 단위/실패 시나리오 **48개 통과**: Backend 범위·digest 고정·dev 거부·CI 출처·초기 pin·adopt 성공/실패·상태 보존·롤백·중단·Secret 변경·SSM 전달/종료 코드.
- `python scripts/validate-manifest.py --structure-only` 통과. 실제 배포용 strict 검사는 초기 null 때문에 의도적으로 거부된다.
- 실제 Docker Compose CLI로 원본 YAML → 비밀값을 펼치지 않은 JSON의 네 서비스 config hash가 동일함을 확인했다. synthetic env 값을 사용했다.
- actionlint 1.7.7 통과, Python compile·두 Bash 스크립트 syntax·Git whitespace 검사 수행.
- 로컬 Python 외부 패키지 설치 없이 표준 라이브러리로 실행한다.

## 실제 환경에서 남은 작업

1. 기존 SHA의 ECR digest·Backend main 성공 CI 조회 및 pin 결과 반영.
2. GitHub App/token·보호 규칙·auto-merge·OIDC/Environment, 실제 호스트 Git 읽기 인증 확인.
3. 기존 파일과 runtime 설정 확인 후 adopt. Backend 정상 배포·실패 복구·SSM 중단 시험.
4. 필요한 IAM/모니터링 CloudFormation 서버 검증·change set 검토, 선택적 알람 수신 시험.
5. Backend readiness·업무 smoke와 CI 테스트를 강화한다. 현재 TCP/빌드 성공의 한계를 유지 기록한다.

actionlint 컨테이너는 실행했지만 App 컨테이너나 AWS 리소스는 실행·변경하지 않았다. CloudFormation API와 GitHub/AWS 운영 권한·실환경 복구 검증은 미완료다.

## 경계와 운영 결정

- DB migration은 실제 App schema에 맞게 검토·선적용하는 계약이며 임의의 migration SQL을 실행하지 않는다.
- 롤백 후 목표 Manifest 정합화는 검토된 사람 PR로 수행한다. 자동 정합화 봇까지 구현하지 않았다.
- GitHub scheduled polling/probe는 지연 가능하다. 외부 장애 탐지의 엄격한 시간 SLA는 없다.
- current가 없는 상태는 자동 배포를 거부하며 기존 운영 스택 adopt가 먼저다.
- AWS 리소스 생성·실제 배포·원격 push는 이 병합 작업에 포함하지 않는다.

자세한 설치·인수 순서는 [운영 Runbook](v1-operations.md)을 따른다.
