# 자동 CD 구현 및 검증 현황

2026-09-30 사용자 확인상 **기존 main 서비스는 정상 운영 중이다.** 아래의 미확인 범위는 작업 브랜치에서 추가한 자동 릴리스·롤백·감시·Secret 적용 추적의 운영 인수다. 기존 시험 기록과 새 변경 검증을 구분한다. 전체 동작은 [전체 설명](v1-design.md), 실제 수행 방법은 [운영 절차](v1-operations.md)에 둔다.

## 구현 범위

현재 파일·기능 목록은 [전체 설명의 파일 역할](v1-design.md#9-파일과-상태의-위치)이 기준이다. 조회·병합은 release.sh로 분리됐고 Actions 수동 dry_run 입력이 구현돼 있다. dry_run은 자동 배포 OFF에서도 실행하며 실패 Discord를 생략한다.

## 기존 작업에서 남긴 로컬 검증 기록

- Manifest·sources `jq` 검사 통과. web·frontend SHA가 다르면 거부되는 것도 확인했다.
- `docker compose config --no-env-resolution` 통과. Backend healthcheck 명령이 의도대로 렌더링된다.
- `shellcheck 0.10.0`: `release.sh`, `deploy.sh`, `notify-discord.sh` 경고 없음. `actionlint 1.7.7`: workflow 4개 오류 없음.
- 로컬 Docker Compose v5에서 `config --hash '*'` 출력 형식(`서비스 해시`)을 확인했다.
- **가짜 docker로 `deploy.sh` 시나리오 9개를 확인했다:**

| # | 시나리오 | 결과 |
| --- | --- | --- |
| 1 | Backend 새 버전 정상 | Backend만 교체, `success`(0) |
| 2 | Backend health 실패 | 이전 이미지로 복구, 차단 기록, `rolled_back`(1) |
| 3 | 차단된 이미지 | 건너뛰고 `unchanged`(0) |
| 4 | FE 배포 중 web 실패 | web→frontend 역순 복구, 둘 다 차단, `rolled_back`(1) |
| 5 | 롤백도 실패 | `rollback_failed`(2) |
| 6 | pull 실패 | 아무것도 바꾸지 않음, `pull_failed`(2) |
| 7 | 변경 없음 | `unchanged`(0) |
| 8 | 설정만 바뀐 서비스 실패 | 차단하지 않음, `rollback_failed`(2) |
| 9 | 원인 불명 연결 실패 | 바꾼 이미지 모두 차단, 롤백 시도 |

- **가짜 `gh`로 `release.sh` 시나리오를 확인했다:** 새 이미지는 배포 대상, 이미 최신은 건너뜀, CI 진행 중·게시 job skip은 대기, 같은 커밋의 CI 재실행은 가장 최근 것 사용, API 오류는 멈춤(종료 코드 1), 로컬에서 `DRY_RUN` 없이 실행하면 거부. 로컬 bare 저장소를 origin으로 두고 실제 병합 경로도 확인했다. Manifest diff가 해당 서비스 한 줄이고, PR 생성 → squash 병합 → `released=true` 순서로 동작했다.

위 시나리오는 기존 작업에서 남긴 기록이며 이번 문서 정리에서 재실행하지 않았다. 이 문서에는 재현용 시험 코드·실행 링크가 남아 있지 않아 현재 코드 전체에 대한 반복 검증 근거로 사용하지 않는다. 당시 실제 문제와 해결 과정은 [구현·로컬 검증 기록](archive/v1-implementation-notes-2026-09-29.md)에 보존했다. 실제 AWS·EC2·GitHub Actions 경로는 별도 확인이 필요하다. 가짜 gh와 로컬 bare 저장소 시험은 GitHub 서버의 실제 PR 생성·병합 권한을 검증한 것이 아니다.

## 이번 문서 정리에서 확인한 범위

- workflow 4개, release.sh·deploy.sh·notify-discord.sh·prepare-runtime.py와 Compose·배포 JSON을 읽고 문서를 대조했다.
- release.sh 분리와 수동 dry_run, main checkout 고정, 스위치 예외·알림 생략을 반영했다.
- 배포 재시도 범위, FE 실패 위치별 차단 차이, 이미지 복구의 한계를 실제 코드 기준으로 명시했다.
- README와 현재·보관 문서의 상대 링크·섹션 링크가 모두 연결되는지 검사했고, 오래된 실행 지침과 diff의 공백 오류를 점검했다. 문서 정리는 운영 배포 성공 증거를 추가하지 않는다.

알림 구축·수신 시험은 [장애 알림 시스템](./v1-alerting.md), 검증 기준·복구·실패 시나리오는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md)에 전용 문서로 분리했다. 문서 분리는 실제 환경의 추가 시험 완료를 뜻하지 않는다.

## 2026-09-30 모니터링 확장

- CloudWatch 로그 그룹·제한된 쓰기 IAM·Agent 지표 누락 알람, 선택 활성화하는 앱 awslogs override를 추가했다. 기존 EC2·RDS 알람 초안을 유지했다.
- 별도 PG Compose, node/blackbox exporter, Grafana 대시보드·Discord contact point·서비스/수집 실패 rule을 준비했다. 앱 계측 타깃은 구현 확인 전까지 비활성이다.
- 로컬 Docker Compose 구조 검사(기본/로그 활성화/모니터링), 로그 override가 다른 앱 설정을 바꾸지 않는지 등 Python 계약 검사 3개, deploy.sh Bash 구문 검사 통과.
- CI에 promtool·blackbox 설정 검사를 추가했다. 초기 작업에서는 Docker daemon이 없어 실행 검사하지 못했으며, 아래 상세 메트릭 작업에서 native promtool로 앱 규칙 검증을 추가했다. 컨테이너 기동·Grafana provisioning·blackbox 실행, AWS 스택 생성·로그 전송·SNS/Discord 실제 수신은 아직 수행하지 않았다.
- 적용·복구·앱 팀 계약·인수 시험은 [모니터링 운영 구성](v1-monitoring.md)에 있다.

## 2026-09-30 Secret 자동 조회 복원

- main의 배포 시 Secret 조회를 유지하고, 새 deploy.sh에서 실패를 명시적으로 처리한다. 결정과 기존 main의 실패 처리 범위는 [TD-016](technical-decisions.md#td-016--배포-시-secret-자동-조회와-실패-처리)에 기록했다.
- env_file의 변경을 Compose 해시만으로 감지할 수 없는 로컬 CLI 동작을 확인해, BE·AI별 마지막 적용 컨테이너 ID와 env/JWT 파일 지문을 별도 기록한다. pull 실패 후 재시도에서도 변경을 놓치지 않는다.
- `tests/test_runtime.py`, `tests/test_runtime_deploy.py`에 조회·검증 오류, 파일 보존, env/JWT 변경, 무변경, 차단·재시도·이미지 복구를 확인하는 15개 회귀 시험을 추가했다. AWS와 Docker 동작은 대체하며 Compose config 검사는 실제 CLI를 사용한다. Windows 시험에서는 소유권·파일 mode와 flock을 대체하므로 실제 Linux 권한·잠금 검증은 아니다.
- 실제 AWS 조회·EC2 컨테이너 교체·서비스 인증은 이번 작업에서 실행하지 않았다. GitHub CI의 ShellCheck/actionlint와 운영 인수는 별도로 확인한다.

## 2026-09-30 상세 메트릭 계약·설정

- [파트 전달용 계약](monitoring-metrics-contract.md)에 공통 HTTP, BE JVM/Hikari, AI 제공자·TTFT·재시도·토큰 지표의 이름·단위·label·bucket·측정 경계와 파트별 확인 항목을 정의했다.
- Prometheus recording rule 8개·초기 alert rule 8개, Grafana 상세 대시보드 3개·앱 알림 전달 rule을 추가했다. 타깃이 비어 있는 현재 상태에서 앱 알림은 발생하지 않는다. 임계치/for는 Prometheus가 판정하고 Grafana는 Discord 전달을 담당한다.
- 공식 Prometheus 3.13.3 Windows 배포물의 SHA256을 확인하고 native promtool로 16개 규칙 문법, 무트래픽·저트래픽·counter reset·장애/복구·계측 누락·취소 제외 등을 포함한 **19개 시나리오**를 통과했다. 이 안에서 **대시보드/전달 PromQL 27개**의 미등록 상태 평가도 확인했다.
- CI에 생성 JSON 일치 검사와 promtool 동작 시험을 추가했다. 적용/회신/알림별 대응은 [운영 절차](monitoring-alert-runbook.md)에 기록했다. 실제 BE·AI 코드 구현과 Grafana 컨테이너 provisioning·운영 알림 수신 검증은 별도로 남아 있다.

## 2026-10-01 운영 확인 (앱 EC2·CloudWatch 로그)

"CloudWatch 로그가 안 보인다"는 문의로 앱 EC2를 확인했다.

- **원인:** 스위치 파일 `/opt/keepgo/runtime/cloudwatch-logs.enabled`가 없어 앱 컨테이너 4개가 모두 로컬 `json-file` 로그만 쓰고 있었다. CloudWatch로는 처음부터 보낸 적이 없었다.
- **전송 시험:** 앱 EC2에서 awslogs 드라이버로 임시 컨테이너를 실행해 `/keepgo/v1/application`에 쓰기가 성공했다. 로그 그룹 존재와 EC2 역할(`keepgoEC2logRole`)의 쓰기 권한을 함께 확인한 것이다.
- **적용:** 스위치를 만들고 재배포한 뒤 `keepgo-v1-web·frontend·backend·ai-api`가 모두 `awslogs`로 바뀐 것을 확인했다. exporter 2개는 설계대로 `json-file`이다.
- **함께 확인된 것:** 앱 EC2에 `keepgo-exporters` 프로젝트(node-exporter·blackbox)가 실행 중이고, 모니터링 EC2와 그 IAM 역할(`keepgo-v1-monitoring-host` 스택)이 존재한다. TD-024의 호스트 분리는 AWS에 적용된 상태다. `keepgo-v1-monitoring` 스택도 존재한다.
- **참고:** CloudWatch에 `ai/logs`·`backend/logs`·`web/logs` 로그 그룹(보존 2주)이 따로 있다. 이 레포 코드가 만든 이름이 아니며 현재 컨테이너는 이 그룹에 쓰지 않는다. 앞으로 앱 로그는 `/keepgo/v1/application` 한 그룹에 서비스별 스트림으로 쌓인다. 옛 그룹 정리 여부는 팀이 정한다.
- **아직 확인하지 않은 것:** CloudWatch Agent 지표, 알람 상태, SNS 구독 승인, Grafana Discord 수신 시험.

## 2026-10-02 앱 상세 메트릭 연결 (BE·AI)

계약 v1의 BE·AI 기본 구현을 연결하고 수집을 시작했다. 구성은 [모니터링 구성](v1-monitoring.md) 6절.

- **BE:** BE #64(`d883506`)가 Actuator를 관리 포트 8081로 옮기고 `traffic_class` tag와 `keepgo_observability_info`를 추가했다. 15:10 KST 배포 직후 blackbox가 8080 health를 계속 호출해 오탐 경고가 왔다. Cloud #58(`1b5731a`)로 probe를 8081로 바꾸고 compose healthcheck의 8080 재시도를 지웠다([사례](troubleshooting/2026-10-02-backend-8081-health-false-alert.md)).
- **AI:** AI #37(`9edfd29`)에서 `prometheus-client` 0.26.0, ASGI 미들웨어(`app/core/metrics.py`), 지표 포트 9464를 추가했다. 테스트 7개(`tests/test_metrics.py`)가 통과했고, 로컬 uvicorn에서 9464 응답·템플릿 route·422/404 기록·8000 `/metrics` 404를 확인했다. AI 팀원 확인에 따라 AI #38(`b37154c`)에서 `embed-places`를 interactive로 옮겼다.
- **등록:** Cloud #67(`77a7e44`)로 `application.json`에 backend·ai-api를 등록했다. 앱 EC2에서 9464·8081 응답과 cancel 호출 후 AI 요청 지표 생성을, 모니터링 EC2에서 두 대상 `health=up`·`lastError` 없음·`up=1`을 확인했다.
- **확인하지 않은 것:** Nginx 공개 경로의 metrics 차단, 앱 알림의 firing→resolved Discord 전달, 실측 기반 임계치. AI Providers and Streaming 대시보드는 확장 지표 미구현으로 No data다.

## 남은 검증과 적용

- [ ] TD-016의 Secret 자동 조회·실패 시 교체 중단과 env/JWT 변경 감지를 EC2에서 확인한다. 첫 적용에서는 기록이 없는 BE·AI를 한 번 재생성한다.

- [ ] GitHub 변수·Secret·PR 생성 권한·production 승인 정책·main 보호 정책을 운영 설정과 대조한다.
- [x] CloudWatch 로그 smoke 확인과 앱 로그 전송 활성화 (2026-10-01, 위 절).
- [ ] CloudWatch Agent 지표·알람 상태·SNS 구독 승인을 확인한다.
- [ ] PG 용량·런타임 비밀값 준비 후 설치하고 Grafana 대시보드·Discord·NoData/Error·복구 알림을 시험한다.
- [ ] BE·AI 계측과 Nginx 공개 차단을 확인하고 앱 Prometheus 타깃을 활성화한다.
- [ ] main 반영 후 실제 Actions dry_run에서 후보 조회·무변경·실패 알림 생략을 확인한다.
- [ ] EC2 요구사항과 실제 이미지·설정 차이를 확인하고 최초 수동 배포를 수행한다.
- [ ] Health check의 정상 검사와 실제 장애·복구 Webhook 전달을 각각 확인한다.
- [ ] 후보를 확인한 뒤 자동 배포를 켜고 [배포 검증·롤백](./v1-deployment-verification-and-rollback.md) 7절과 [알림 수신](./v1-alerting.md) 7절의 시험 결과를 기록한다.
- [ ] 후속 요구: FE main 전환, 서비스별 오류 격리, FE 묶음 차단, 배포 호출 실패 재처리 여부를 결정한다.

완료 표시에는 날짜, Cloud 커밋, Actions/SSM 실행 링크, 결과를 남긴다. 과거 문서의 특정 SHA를 앞으로 배포될 버전으로 예고하지 않는다.
