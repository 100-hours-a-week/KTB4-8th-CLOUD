# main 정상 운영 이후 남은 작업

2026-09-30 기준. **사용자 확인: main 기준 서비스는 정상 동작 중이다.** 기존 EC2·DB·ECR·TLS·런타임을 새로 구축하는 작업은 남은 일로 분류하지 않는다. 아래는 현재 작업 브랜치의 추가 기능을 반영하는 데 필요한 설정과 검증이다.

origin/main은 2f17f80(PR #18, Backend c2dab78)이다. 이번 재점검에서는 workflow·스크립트·Compose와 로컬 앱 저장소(BE·FE·AI)를 대조했다. GitHub 설정 조회와 AWS/EC2 접속은 하지 않았다. main 정상 운영과 새 자동 CD·모니터링의 적용 완료는 구분한다.

## 0. main 반영 전에 먼저 고칠 것

| 문제 | 원인 | 조치 |
| --- | --- | --- |
| Validate의 Check compose 실패: `env file /opt/keepgo/runtime/backend.env not found` | 러너의 Compose v2는 `--no-env-resolution`이어도 `required: true`인 env_file 존재를 확인한다. 로컬 Compose v5는 건너뛰어 로컬 검사에서는 드러나지 않았다 | validate.yaml에 빈 런타임 파일을 만드는 단계 추가(수정 완료). 값은 읽지 않는다 |
| JSON Manifest의 backend가 15b54fe | main의 PR #18(c2dab78)이 YAML Manifest에만 반영됐다 | production-manifest.json backend를 c2dab78378e3e0758dae739c7664f038bccd0c10으로 수정(수정 완료). 그대로 병합했다면 Backend가 이전 버전으로 되돌아간다 |

- [ ] 위 두 수정과 TD-017·018 반영분을 PR 브랜치(feat/v1-central-cd)에도 반영하고 Validate 통과 확인.
- [ ] 병합 직전 `git show origin/main:deployment/production-manifest.yaml`과 JSON의 네 SHA를 다시 대조. 그사이 main에 수동 배포 PR이 더 들어오면 같은 문제가 반복된다.
- [ ] 병합 시점에 AUTO_DEPLOY_ENABLED가 `true`가 아니어야 한다. 병합 push가 compose.yaml·deploy.sh 등을 바꾸므로 `true`면 병합 즉시 운영 배포가 실행된다.

## 1. 이미 있는 것과 추가되는 것

| 항목 | main 기준 | 현재 브랜치에서 추가/변경 |
| --- | --- | --- |
| 앱 4개·DB·TLS·이미지 SHA | 정상 운영의 기존 기반 | 기존 환경 재사용 |
| Deploy production | execute 입력을 사용하는 수동 배포 | main 변경·자동 릴리스 연계, 수동 실행의 execute 입력 제거 |
| 이미지 목록 | production-manifest.yaml | production-manifest.json과 sources.json |
| 앱 새 버전 조회 | Auto release 없음 | 10분 주기 조회 → Manifest PR 생성·병합 → 배포 호출 |
| 배포 실패 처리 | 새 브랜치의 롤백·차단 로직 없음 | 서비스별 변경 감지·순차 교체·이미지 롤백·실패 SHA 차단 |
| Backend health | 8080 포트 연결 확인 | /actuator/health의 UP 응답 확인 |
| Secret 반영 | deploy.sh가 prepare-runtime.py 실행 | 자동 조회 유지. 실패 시 교체 중단·env/JWT 변경 감지 추가(TD-016), 운영 적용 대기 |
| 배포 전 파일 검사 | TLS 인증서·uploads 디렉터리·NAVER 키 존재 확인 | 재작성 때 빠졌다가 복원(TD-018). acme 디렉터리 추가, NAVER 필수는 prepare-runtime.py 한 곳에서 판단 |
| 외부 감시 | Health check workflow 없음 | PUBLIC_ORIGIN 감시와 Discord 장애·복구 알림 |
| CloudWatch·PG | 구성 파일 없음 | CloudWatch, Prometheus·Grafana 설정 추가 |

## 2. GitHub 설정 — 무엇을 어디서 찾아 어디에 넣나

모든 위치는 Cloud 저장소(100-hours-a-week/KTB4-8th-CLOUD) 기준이다.

| 이름 | 종류·넣는 곳 | 값과 찾는 곳 | 쓰는 workflow |
| --- | --- | --- | --- |
| AWS_DEPLOY_ROLE_ARN | 기존 값 확인만. Settings → Environments → production 또는 Secrets and variables → Actions → Variables | 이미 main 배포에서 사용 중. 새로 넣지 않는다 | Deploy production |
| PRODUCTION_EC2_INSTANCE_ID | 위와 같음 | `i-`로 시작하는 기존 값. EC2 콘솔 → 인스턴스 ID와 같은지만 확인 | Deploy production |
| AUTO_DEPLOY_ENABLED | **Repository variable** (Settings → Secrets and variables → Actions → Variables → Repository variables) | 적용·검증 중 `false`, 인수 시험 후 `true`. 소문자 문자열 그대로 | Auto release, Deploy production(push) |
| PUBLIC_ORIGIN | **Repository variable** | `https://운영도메인` 형태. 경로·끝 슬래시 없이. 실제 서비스 접속 주소(브라우저 주소창)를 그대로 쓴다 | Health check |
| DISCORD_WEBHOOK_URL | **Repository secret** (같은 화면 Secrets 탭) | Discord 알림 채널 → 채널 편집 → 연동 → 웹후크 → 새 웹후크 → 웹후크 URL 복사 | 세 workflow 모두 |

**production Environment에만 두면 안 되는 값:** AUTO_DEPLOY_ENABLED, PUBLIC_ORIGIN, DISCORD_WEBHOOK_URL. Auto release·Health check job은 environment를 쓰지 않아 읽지 못한다. AWS_DEPLOY_ROLE_ARN·PRODUCTION_EC2_INSTANCE_ID는 Deploy job이 production Environment를 쓰므로 어느 쪽에 있어도 된다.

| 설정 위치 | 확인·변경할 것 | 이유 |
| --- | --- | --- |
| Settings → Actions → General → Workflow permissions | "Allow GitHub Actions to create and approve pull requests" 체크 | 없으면 release.sh의 `gh pr create`가 실패한다. 조직 설정에서 막혀 있으면 조직 관리자에게 요청 |
| Settings → Branches(또는 Rules) → main | **보호 규칙을 설정하지 않는다(TD-017).** 필수 status check·필수 리뷰가 없는지 확인 | GITHUB_TOKEN이 만든 release PR에는 Validate가 실행되지 않아 필수 check가 있으면 병합이 실패한다. 형식 검사는 release.sh가 check-manifest.jq로 대신한다. 사람의 main 변경은 Validate 결과를 보고 병합하는 팀 규칙으로 관리한다 |
| Settings → Environments → production | **Required reviewers 제거(2026-09-30 완료, TD-020).** Deployment branches를 제한했다면 `main`이 허용돼야 한다 | 승인자가 있으면 자동 배포가 매번 승인 대기에서 멈춘다. 설정 변경 전에 대기 중이던 실행은 Cancel 후 다시 실행한다 |
| AWS IAM의 배포 역할 신뢰 정책 | 변경 없음 | 새 workflow도 production Environment를 쓰므로 OIDC sub(`repo:…:environment:production`)가 main과 같다 |

동작 참고:

- PUBLIC_ORIGIN이 없으면 Health check job이 skip된다.
- DISCORD_WEBHOOK_URL이 없으면 알림 대신 경고만 남고 실패로 처리하지 않는다.
- AUTO_DEPLOY_ENABLED와 무관하게 수동 Deploy production은 실제 배포한다. execute 확인 입력은 없다.
- Run workflow의 "Use workflow from"은 기본값 main 그대로 둔다. 다른 브랜치를 고르면 job이 skip된다(TD-018). EC2가 `origin main`만 fetch하기 때문이다.
- schedule(10분·5분)은 main에 병합된 뒤부터 동작한다.

## 3. Secrets Manager — 필수 키와 형식

찾는 곳: AWS 콘솔 → Secrets Manager(ap-northeast-2) → `Secret-v1-BE`, `Secret-v1-AI` → 보안 암호 값 검색. 이름은 prepare-runtime.py의 기본값이며 EC2 instance role이 두 Secret을 읽을 수 있어야 한다(main과 동일).

| Secret | 키 | prepare-runtime.py 처리 | 확인할 것 |
| --- | --- | --- | --- |
| Secret-v1-BE | DB_USERNAME, DB_PASSWORD | 필수. 없으면 배포 중단 | Compose가 DB_USERNAME=keepgo_app을 고정한다 |
| Secret-v1-BE | JWT_PUBLIC_KEY | 필수. `-----BEGIN PUBLIC KEY-----`로 시작, 줄바꿈 유지 | |
| Secret-v1-BE | JWT_PRIVATE_KEY | 필수. **`-----BEGIN PRIVATE KEY-----`(PKCS#8)**. `BEGIN RSA PRIVATE KEY`면 거부 | |
| Secret-v1-BE | GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, VWORLD_API_KEY | 선택. 없으면 경고만 | Google 로그인·redirect URI, 위치 기능 |
| Secret-v1-AI | GOOGLE_API_KEY | 필수 | 실제 AI 요청 성공, 모델(gemini-3.8-flash)·할당량 |
| Secret-v1-AI | NAVER_MAP_CLIENT_ID, NAVER_MAP_CLIENT_SECRET | 필수(TD-018). 없으면 배포 중단 | 지도·주소 기능. main 배포가 같은 검사를 통과해 왔으므로 운영 Secret에는 있다 |
| Secret-v1-AI | SENTRY_DSN | 선택(TD-019). 있으면 ai.env로 전달 | AI main(8bd3c32~)의 Sentry. 운영 Secret에 있음(2026-09-30 확인) |
| Secret-v1-AI | GOOGLE_MODEL, LANGSMITH_API_KEY | 전달하지 않음 | 모델은 compose.yaml이 결정. LangSmith는 v2에서 AI 팀과 결정. GOOGLE_MODEL은 Secret에서 제거 권장 |

값은 줄바꿈(PEM 제외)이 없어야 하고 JSON 키 이름에 공백·`=`가 없어야 한다. 이미 main 배포가 이 Secret으로 성공하고 있으므로 새로 등록할 필요는 없고, 선택 키(BE의 Google·VWorld)가 빠진 기능만 확인한다.

Secret 변경 절차:

1. 자동 배포를 멈추고 실행 중 배포 종료 확인.
2. Secrets Manager 값 변경.
3. Deploy production 수동 실행. 자동 조회 후 변경된 서비스만 반영하며 JWT만 바뀌어도 Backend를 재생성한다.
4. health와 실제 기능을 확인하고 자동 배포 재개. 잘못된 Secret은 이미지 롤백으로 복구되지 않으므로 값을 수정/복원한 뒤 재배포한다. 상세는 [운영 절차](v1-operations.md) 8절을 따른다.

## 4. EC2·앱 저장소 전제 조건

| 대상 | 확인할 것 | 확인 방법 |
| --- | --- | --- |
| EC2 Docker Compose | **2.30.0 이상** (`env_file.format: raw`, compose.cloudwatch.yaml의 `!override`) | SSM 세션에서 `docker compose version` |
| EC2 도구 | bash, python3, flock, curl, aws CLI, git | `command -v flock python3 aws git`. PyYAML은 더 이상 필요 없다 |
| EC2 Cloud checkout | `/opt/keepgo/cloud`가 Cloud 저장소 clone이고 `git fetch origin main`이 인증 없이 된다 | main 배포가 쓰던 것과 같다 |
| EC2 기존 파일 | /opt/keepgo/tls/fullchain.pem·privkey.pem, /opt/keepgo/acme, /opt/keepgo/data/uploads(10001 소유) | deploy.sh가 교체 전에 확인하고 없으면 `host_files_missing`으로 멈춘다(TD-018). uploads 소유자는 검사하지 않으므로 `ls -ld`로 확인 |
| EC2 state | /opt/keepgo/state (자동 생성) | 처음 배포 후 history.log·failed-images 생성 확인 |
| 앱 CI (로컬 저장소로 대조 완료) | BE `ci.yml`/`Main - Build and Push Image`/main, FE `frontend-ci.yml`/`Build and push frontend images`/feat/v1, AI `ci.yml`/`Main - Build and Push Image`/main — sources.json과 일치. 태그는 모두 push 커밋 SHA | 앱 저장소를 바꾸면 다시 대조 |
| 앱 저장소 Variables | BE `ECR_REPOSITORY=keepgo-backend`, FE `ECR_REPOSITORY=keepgo-web`·`ECR_NGINX_REPOSITORY=keepgo-nginx`, AI `ECR_REPOSITORY=keepgo-ai` | 각 앱 저장소 Settings → Variables. compose.yaml 이미지 이름과 같아야 한다. 조회하지 못했다 |
| 앱 저장소 공개 여부 | BE·FE·AI가 공개 저장소 | 비공개면 Cloud의 GITHUB_TOKEN으로 조회할 수 없다 |
| Backend health | /actuator/health 인증 없이 허용 | 로컬 BE(f20f4fc)의 SecurityConfig가 HealthEndpoint를 permitAll. 운영 이미지 c2dab78에서 실제 응답 확인 필요 |

## 5. 모니터링을 켤 때 필요한 값

| 값 | 찾는 곳 | 넣는 곳 |
| --- | --- | --- |
| InstanceId | EC2 콘솔 → 인스턴스 ID (= PRODUCTION_EC2_INSTANCE_ID) | `aws cloudformation deploy --parameter-overrides InstanceId=` |
| InstanceRoleName | EC2 콘솔 → 인스턴스 → 보안 탭 → **IAM 역할** 링크의 역할 이름. 인스턴스 프로파일 이름과 다를 수 있으니 IAM → 역할에서 이름 확인 | `InstanceRoleName=`. 비우면 두 정책을 직접 연결 |
| AlarmEmail | 팀이 정하는 수신 주소 | `AlarmEmail=`. 생성 후 수신 메일에서 Confirm |
| DBInstanceIdentifier | RDS 콘솔 → DB 식별자. compose.yaml의 DB_HOST가 `keepgo-db-v1.…`이므로 기본값과 일치할 가능성이 높다 | 다를 때만 `DBInstanceIdentifier=` |
| Grafana 관리자 비밀번호 | 새로 생성 (`openssl rand -base64 24`) | EC2 `/opt/keepgo/runtime/grafana_admin_password` 한 줄, `472:0`, `0400` |
| Grafana용 Discord Webhook | GitHub Secret과 같은 URL 또는 별도 채널의 새 Webhook | EC2 `/opt/keepgo/runtime/monitoring.env`에 `DISCORD_WEBHOOK_URL=URL`, `root:root`, `0600` |
| observability COMMIT | main 병합 후 `git rev-parse origin/main` | [모니터링 문서](v1-monitoring.md)의 `checkout --detach COMMIT` |
| 문서 예시의 치환값 | i-REPLACE, REPLACE_EC2_ROLE, REPLACE_EMAIL, COMMIT | 위 값으로 치환 |

**모니터링 전용 IAM role은 만들지 않는다.** EC2에는 role을 하나만 붙일 수 있고 CloudWatch Agent·awslogs는 그 role을 쓴다. 템플릿이 기존 role에 로그 쓰기(`/keepgo/v1/application`의 CreateLogStream·PutLogEvents)와 지표 쓰기(`CWAgent` 네임스페이스의 PutMetricData) 정책 두 개만 붙인다. 스택 배포는 관리자 계정으로 1회 실행하고 GitHub 배포 role에는 권한을 추가하지 않는다. Grafana 터널 사용자는 해당 인스턴스의 `ssm:StartSession`만 있으면 된다.

**GitHub Secret의 Webhook은 Grafana에 자동 전달되지 않는다.** 비밀번호와 Webhook 값 자체는 Git/문서에 넣지 않는다. CloudFormation은 `CAPABILITY_NAMED_IAM`이 필요하므로 IAM 정책 생성 권한이 있는 계정으로 실행한다.

기본값(필요할 때 조정): 로그 보관 14일, EC2 디스크 80%·메모리 90%, RDS 남은 공간 3 GiB·CPU 85%, Prometheus 보관 7일 또는 2GB.

## 6. 모니터링 적용 작업

- [ ] 기존 동명 로그 그룹(/keepgo/v1/application)·SNS·알람과 소유 스택 확인 후 infrastructure/monitoring.yaml 배포.
- [ ] SNS 구독 확인 이메일에서 승인.
- [ ] EC2 역할에 로그 그룹의 CreateLogStream·PutLogEvents, CWAgent 지표 전송 권한 연결(InstanceRoleName 입력 시 자동).
- [ ] CloudWatch Agent 설치 및 monitoring/cloudwatch-agent.json 적용. 실제 CWAgent 지표 확인.
- [ ] 임시 컨테이너 로그가 /keepgo/v1/application에 도착하는지 확인.
- [ ] 성공 후 /opt/keepgo/runtime/cloudwatch-logs.enabled 생성 및 수동 배포. 앱 네 개가 로그 설정 변경으로 재생성되므로 점검 시간에 적용.
- [ ] observability checkout·Grafana 비밀번호·monitoring.env 준비.
- [ ] 앱 네트워크 keepgo-v1_web, keepgo-v1_service가 있는 상태에서 compose.monitoring.yaml 실행.
- [ ] SSM 터널로 Grafana 3001, Prometheus 9090 접근. 관리 포트는 외부 공개하지 않음.
- [ ] 기본 scrape target 7개 UP, 서비스 probe_success 4개 정상 확인.
- [ ] Grafana Discord 및 CloudWatch SNS 이메일 실제 수신 확인.
- [ ] 앱 재배포 후에도 모니터링과 로그 수집 유지 확인.

모니터링 컨테이너 메모리 상한은 합계 960 MiB다. 기존 앱 상한 2,432 MiB에 OS·Docker·Agent가 더해지므로 실제 여유를 확인한다. Prometheus 추가 디스크 여유 기준은 최소 5 GiB다. 앱 자동 CD는 observability checkout을 갱신하지 않는다.

## 7. 실제로 빈 설정: 앱 상세 메트릭

monitoring/prometheus/targets/application.json은 현재 []다. 앱의 요청률·오류율·p95·JVM·DB pool 지표는 아직 연결되지 않았다.

- [ ] BE 팀: /actuator/prometheus 계측·접근 설정 확인. 현재 SecurityConfig는 health 외 actuator를 denyAll로 막는다.
- [ ] AI 팀: /metrics와 요청 수·오류·지연 지표 확인.
- [ ] Nginx 공개 경로에서 metrics가 노출되지 않는지 확인.
- [ ] 준비 후 application.json에 backend:8080, ai-api:8000과 각각의 metrics path 등록.
- [ ] 실제 지표 수집을 확인하고 앱 대시보드·임계치 확정.

## 8. 새 배포 흐름 적용 순서와 검증

- [ ] 0절 두 수정 반영, Validate 통과 후 main 병합(AUTO_DEPLOY_ENABLED=false 상태).
- [ ] 2절 GitHub 설정 확인(변수 3개, PR 생성 허용, main 보호 규칙, production Environment).
- [ ] 4절 EC2 전제 조건 확인(Compose 2.30+, flock, TLS·uploads).
- [x] 배포 시 Secret 자동 조회 복원, 오류 시 중단 및 JWT 적용 상태 추적 구현·결정 기록.
- [ ] Auto release를 main에서 dry_run=true로 실행해 후보·무변경 처리 확인. 현재 Manifest가 최신이면 세 저장소 모두 "최신"이어야 한다.
- [ ] 점검 시간에 수동 Deploy production(main). **첫 실행은 Secret 적용 기록이 없어 backend·ai-api를, healthcheck 변경으로 backend를 재생성한다.** 교체 대상·health·공개 HTTPS·실제 기능 확인.
- [ ] EC2에서 Secret 조회 실패 시 교체 없음, JWT만 변경 시 Backend만 재생성 확인.
- [ ] **같은 커밋으로 두 번 연속 배포 → 두 번째는 `result=unchanged services=none`** (TD-021, [사례](troubleshooting/2026-09-30-env-file-services-recreated-every-deploy.md)). 수정 반영 후 첫 배포는 backend·ai-api를 한 번 더 재생성한다.
- [ ] 외부 Health check 정상 검사와 장애·복구 알림 확인.
- [ ] 합의한 점검 시간/시험 환경에서 이미지 pull 실패, health 실패 롤백, 실패 SHA 차단, 복구 실패 알림 확인.
- [ ] AUTO_DEPLOY_ENABLED=true. 실제 앱 커밋 → Manifest PR → 병합 → 배포까지 확인.
- [ ] 날짜·Cloud SHA·Actions/SSM 실행 링크·결과 기록.

dry_run은 후보 조회 시험이다. 실제 PR 생성·병합 권한, ECR pull, EC2 교체·롤백은 별도 시험한다.

## 9. 결정하거나 후속으로 진행할 항목

| 항목 | 현재 상태 | 다음 작업 |
| --- | --- | --- |
| main 필수 check와 자동 병합 | 보호 규칙 없이 운영, release.sh에서 형식 검사(TD-017) | 조직 App 발급이 가능해지면 App 토큰 + 필수 check로 전환 |
| FE 배포 브랜치 | feat/v1 | 유지 또는 main 전환 결정. FE main의 CI에도 같은 job 이름이 있어 sources.json의 branch만 바꾸면 된다 |
| 앱 CI 검사 | Cloud는 게시 job 성공을 확인 | BE 등 실제 단위/기능 테스트 수행 범위를 앱 팀과 확인 |
| 서비스별 조회 실패 | 후속 서비스 조회에 영향 가능 | 오류 격리 개선 여부 결정 |
| FE 묶음 실패 처리 | 두 서비스 원자적 교체·전체 차단 보장 안 됨 | 강화 여부 결정 |
| **Secret 값 형식 검사 — SENTRY_DSN** (TODO) | 2026-09-30 17:13 KST 배포(#15)에서 Secret-v1-AI의 SENTRY_DSN이 공개 키 없는 값이라 AI `4bd2efc`가 `sentry_sdk.utils.BadDsn: Missing public key`로 기동 실패 → 자동 롤백·차단. 이전에는 전달하지 않던 키라 드러나지 않았고, TD-019에서 전달을 시작하며 처음 사용됨. prepare-runtime.py는 키 존재만 확인 | prepare-runtime.py에서 `https://<공개키>@<호스트>/<프로젝트번호>` 형식을 검사해 틀리면 전달하지 않고 경고만 남김(AI는 Sentry 없이 기동). 새 선택 키를 전달 목록에 추가할 때 운영 Secret 값의 형식을 먼저 확인 |
| **차단된 서비스가 있어도 결과가 `unchanged`** (TODO) | 2026-09-30 17:21 KST 배포(#17)에서 ai-api가 차단돼 LangSmith 설정이 반영되지 않았는데 `result=unchanged`, 알림 없음. 약 1시간 20분 미반영 | 차단 때문에 건너뛴 서비스가 있으면 `result=blocked`(종료 코드 2)로 기록하고 Discord 알림. `history.log`에 건너뛴 서비스도 남김 |
| Manifest 병합 후 배포 실패 | 다음 조회만으로 재배포 안 됨 | 수동 재배포 절차 유지 또는 자동 재처리 추가 |
| Grafana 단독 장애 | 별도 외부 감시 없음 | 필요 시 추가 |
| **외부 감시 이전** (TD-023, [Sentry 정리](v1-sentry.md)) | Actions Health check를 EventBridge가 5분마다 실행. 개인 PAT 의존, 하루 288건 기록 | Sentry Uptime으로 이전. ① Sentry Uptime에 `/healthz` 1분 주기 등록, Discord 알림 연결(바로 가능) ② `https://expired.badssl.com/` 등록으로 인증서 검증 여부 시험, 안 잡히면 blackbox 인증서 만료 알림 추가 ③ 모니터링 스택 설치, Grafana 서비스별 알림 시험 ④ `health-check.yaml`과 EventBridge의 Health check 규칙 제거. ③ 전에 ④를 하면 Backend 장애가 알림 없이 지나간다. 등록 설정(URL·주기·실패 기준·알림 대상)과 계정 관리자를 기록 |
| 백업/복원 | main 서비스 동작만으로 검증되지 않음 | RDS 백업·복원 시험, 업로드 파일 백업 담당/주기 확인 |
| DB/설정 복구 | 이미지 롤백으로 복구 안 됨 | migration 호환성과 설정·Secret 복구 절차 확인 |
| V2 ECS/ASG·Worker | 설계 문서 영역 | V1 적용과 별도로 채택 범위·일정 결정 |

## 참고

- [자동 CD 운영 절차](v1-operations.md)
- [모니터링 운영 절차](v1-monitoring.md)
- [배포 검증·롤백](v1-deployment-verification-and-rollback.md)
- [앱 계약](v1-app-contracts.md)
- [구현 현황](v1-implementation-status.md)
