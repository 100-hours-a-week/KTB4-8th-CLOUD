# V2 운영 전환 · V1 개발 전환 작업 계획

> 작성: 2026-10-23. 아직 실행 전인 계획이다. 실제 적용 결과는 작업 후 이 문서와 [V2 개발 CD 작업 정리](v2-dev-cd-work-summary.md)에 기록한다. 방향은 [V2 CD 계획 4.8절](v2-cd-plan.md#48-환경-전환-예정--dev는-v1-인스턴스-그대로)과 같다.

## 1. 요약

- **새 인프라를 만들지 않는다(2026-10-23 맞바꾸기로 결정).** 지금 개발로 쓰는 V2(ECS)를 그대로 운영으로 올리고, 지금 운영인 V1(EC2 한 대)을 개발로 내린다. 두 환경의 역할만 맞바꾼다. Terraform으로 운영을 새로 만드는 안은 시간과 비용 때문에 택하지 않았다. 대신 운영을 코드로 다시 세울 수 없으므로 전환 후 Terraform 코드를 실제 상태에 맞춘다(7절).
- **순서:** 출시 준비 → V2 자동 배포 끄기 → DNS 전환(다른 작업자) → V1 자동 배포 끄기 → 앱 `main` 병합(다른 작업자) → V2를 `main` 기준으로 전환 → V1 정리 후 개발로 사용.
- **가장 큰 위험 두 가지.**
  1. DNS 전환 후 `main` 병합 전까지 V2는 `develop`을 배포한다. 자동 배포를 켜 두면 개발 커밋이 바로 운영에 나간다.
  2. 앱 `main` 병합 때 V1 자동 배포가 켜져 있으면 V2 코드가 V1 EC2에 깔린다. `ddl-auto=update` 때문에 **V1 운영 DB 구조가 바뀌어 V1으로 되돌아갈 길이 사라진다.**
- **도메인만 바꾸면 출시할 수 없다.** CloudFront 도메인·인증서 교체, BE 로그인 주소 변경, 보관함 5xx 수정, 데이터 처리 방침이 먼저다(4절). 인증서는 이미 발급돼 있다.
- **Terraform apply 금지.** 코드가 실제 AWS 상태와 달라 apply하면 사이트가 깨질 수 있다. 이번 전환은 콘솔·CLI로 한다(4.2).

## 2. 무엇을 어디로 바꾸나

| 항목 | 지금 운영 → 전환 후 개발 | 지금 개발 → 전환 후 운영 |
| --- | --- | --- |
| 인프라 | **V1**: EC2 한 대 + Docker Compose, V1 RDS | **V2**: ECS `keepgo-v2` + ALB + RDS `keepgo-v2-dev-db` + Redis·SQS |
| 앱 브랜치 | 지금 BE·AI `main`, FE `feat/v1` → 전환 후 3곳 `develop` | 지금 3곳 `develop` → 전환 후 3곳 `main` |
| 도메인 | `keepgo.kr` → `dev.keepgo.kr` | `dev.keepgo.kr` → `keepgo.kr` (`api.keepgo.kr`은 이미 V2 ALB라 그대로) |
| CD 설정 | `sources.json` → `production-manifest.json` → `deploy-production.yaml` | `v2-dev.json` → `envs/v2-dev/` → `deploy-v2-dev.yaml` |
| 자동 배포 스위치 | `AUTO_DEPLOY_ENABLED` | `V2_AUTO_DEPLOY_ENABLED` (쓰기 차단은 `V2_CD_ENABLED`) |
| 데이터 | 실제 사용자 데이터 → 지운다 | 개발·테스트 데이터 → 정리한다(가져올지는 미정, 6절) |

## 3. 전체 순서

| 단계 | 할 일 | 담당 | 되돌리기 |
| --- | --- | --- | --- |
| 1 | 출시 필수 준비 (4절) | 클라우드 + BE | — |
| 2 | `V2_AUTO_DEPLOY_ENABLED=false` | 클라우드 | 변수만 되돌림 |
| 3a | CloudFront에 `keepgo.kr`·`www` 추가, 인증서 교체. DNS가 아직 V1이라 사용자 영향 없음 | 클라우드 | 이전 설정으로 되돌림 |
| 3b | **DNS 전환** (`keepgo.kr` A → CloudFront Alias) | 다른 작업자 | DNS를 V1 IP `52.78.251.134`로 되돌림 |
| 3c | 직후 BE `FRONTEND_SERVER_ADDRESS`·Google redirect를 `https://keepgo.kr`로 바꾼 revision 배포 | 클라우드 | `keepgo-v2-backend:35`로 되돌림 |
| 4 | `AUTO_DEPLOY_ENABLED=false` (V1) | 클라우드 | 변수만 되돌림 |
| 5 | **앱 3곳 `develop → main` 병합** | 다른 작업자 | — |
| 6 | `feat/v2-prod-swap` PR 병합 → `target: v2-prod` dry_run → `V2_PROD_CD_ENABLED=true` → BE·AI·FE 배포 1회씩 확인 → `V2_PROD_AUTO_DEPLOY_ENABLED=true`. `V2_AUTO_DEPLOY_ENABLED`는 계속 꺼 둔다 | 클라우드 | 이전 revision 복구, PR revert |
| 7 | 안정화 기간(며칠). V1은 손대지 않고 되돌리기용으로 둔다 | — | DNS와 BE 환경변수를 함께 되돌림 |
| 8 | V1 데이터 정리 → 개발 설정 적용 → `dev.keepgo.kr` DNS를 V1으로, CloudFront에서 `dev` 제거 → `AUTO_DEPLOY_ENABLED=true` | 클라우드 + 다른 작업자(DNS) | — |
| 9 | 모니터링·문서 정리 | 클라우드 | — |

- 2·4번은 GitHub 저장소 변수만 바꾸는 작업이라 언제든 되돌릴 수 있다. 두 변수는 자동 조회만 멈춘다. 수동 실행은 막지 못하므로 그동안 `Deploy production`과 `Deploy V2`를 **수동으로도 실행하지 않는다.** V2 배포 자체를 막으려면 `V2_CD_ENABLED=false`를 함께 쓴다.
- 3b 전에 2·3a, 5 전에 4가 끝났는지 다른 작업자와 확인한다.
- 3c의 revision은 사람이 등록·배포한다. 중앙 CD는 배포할 때 실행 중인 revision을 복제하므로, 바꾼 환경변수는 다음 자동 배포에도 유지된다. V2 배포가 진행 중일 때는 하지 않는다.
- 3b 전에 Terraform 담당자에게 apply 금지를 알린다.

## 4. 출시 전 필수 (1단계)

### 4.1 앱·데이터
- [ ] 보관함 5xx 수정과 복구 확인 ([트러블슈팅](troubleshooting/2026-10-23-dev-backend-wishlist-event-discriminator.md)) — BE
- [ ] 데이터 처리 방침 결정: V1 데이터를 가져올지, 새로 시작할지(6절)
- [ ] V2 DB의 테스트 계정·데이터 정리 (새로 시작하는 경우)
- [ ] 사용자 시나리오 점검: 로그인, 보관함, 채팅, Sync, 알림 — 지금까지 한 번도 하지 않았다

### 4.2 도메인에 묶인 설정

2026-10-23에 AWS를 읽기 전용으로 확인한 실제 상태:

| 대상 | 지금 가리키는 곳 | 전환 때 |
| --- | --- | --- |
| `keepgo.kr` (A, TTL 60) | V1 EC2 `52.78.251.134` | CloudFront `d3lx018adwi4jv.cloudfront.net`으로 Alias A 변경 |
| `www.keepgo.kr` (CNAME) | `keepgo.kr` | 그대로 두면 함께 따라간다 |
| `api.keepgo.kr` (CNAME) | **이미 V2 ALB** | 바꾸지 않는다. CloudFront의 API origin이다 |
| `dev.keepgo.kr` (CNAME) | V2 CloudFront | V1을 개발로 내릴 때(8단계) V1 EC2로 변경 |
| CloudFront 인증서 | `dev.keepgo.kr` 전용 | us-east-1 인증서 `3d9dd383…`(`keepgo.kr`·`www`·`dev` 포함, 발급 완료·미사용)으로 교체 |
| BE `FRONTEND_SERVER_ADDRESS`, Google redirect | `https://dev.keepgo.kr` (`keepgo-v2-backend:35`) | `https://keepgo.kr` |

- [ ] CloudFront 대체 도메인에 `keepgo.kr`·`www.keepgo.kr` 추가, 인증서 교체. `dev.keepgo.kr`도 잠시 함께 두면 전환 중에 두 주소가 모두 동작한다
- [ ] Route53 `keepgo.kr`을 CloudFront Alias로 변경 — 다른 작업자
- [ ] DNS 전환 직후 BE 환경변수 두 개를 바꾼 revision을 배포한다. 먼저 바꾸면 로그인 후 아직 V1인 `keepgo.kr`로 돌아간다. 중앙 CD는 실행 중인 revision을 복제하므로 바꾼 값이 유지된다
- [ ] 구글·카카오 콘솔에 `https://keepgo.kr/...` redirect가 있는지 확인(V1이 쓰던 주소라 있을 가능성이 높다)
- [ ] CORS, `auth.keepgo.kr` issuer, 쿠키 도메인, FE 코드에 `dev.keepgo.kr`이 박혀 있는지 확인 — BE·FE

**Terraform apply 금지(코드가 실제와 다름).** `infrastructure/terraform-v2`는 실제 상태와 다르다. CloudFront 기본 경로(코드는 S3, 실제는 ALB), `api-sse` origin, FE target group·ALB 규칙(코드에 없음), SSE 규칙(코드에만 있음), `web_domain_name`(코드는 빈 값, 실제는 `dev.keepgo.kr`)이 다르다. 지금 apply하면 사이트가 깨질 수 있다. 이번 전환은 콘솔·CLI로 하고, 전환 후 Terraform 코드를 실제 상태에 맞춘다. Terraform 담당자에게 그 전까지 apply하지 않도록 알린다.

### 4.3 운영 설정
- [ ] `SPRING_SQL_INIT_MODE=always`와 `SPRING_SQL_INIT_CONTINUE_ON_ERROR=true` 끄기. `data.sql`이 생기면 재시작마다 운영 DB에 실행되고, 실패해도 조용히 넘어간다
- [ ] RDS 자동 백업, 삭제 보호 확인

## 5. 단계별 작업

### 5.1 CI/CD — 6단계 (V2를 `main` 기준으로)

**환경 분리 코드 (2026-10-23 완료, 브랜치 `feat/v2-cd-environments`, main 미반영).** V2 CD가 `v2-dev` 하나만 가정하던 것을 환경 입력(`v2-dev`·`v2-prod`)을 받게 바꿨다. `deployment/v2-prod.json`이 없고 운영 스위치가 꺼져 있으면 지금 개발 배포와 똑같이 동작한다.

| 항목 | 개발 `v2-dev` | 운영 `v2-prod` |
| --- | --- | --- |
| 설정 | `deployment/v2-dev.json` | `deployment/v2-prod.json` (브랜치 `feat/v2-prod-swap`) |
| Manifest | `deployment/envs/v2-dev/` | `deployment/envs/v2-prod/` |
| 배포 상태(SSM) | `/keepgo/v2-dev/deployments/*` | `/keepgo/v2-prod/deployments/*` |
| 추적 브랜치 | `main`·`feat/v1` 금지 | `main`만 허용 |
| ECS 이름 | `<cluster>-backend`·`-ai-api`·`-frontend` | 같은 규칙 |
| GitHub Environment | `dev` | `v2-prod` |
| 배포 쓰기 스위치 | `V2_CD_ENABLED` | `V2_PROD_CD_ENABLED` |
| 자동 조회 스위치 | `V2_AUTO_DEPLOY_ENABLED` | `V2_PROD_AUTO_DEPLOY_ENABLED` |

- 배포 workflow 이름을 `deploy-v2-dev.yaml` → `deploy-v2.yaml`로 바꾸고 `environment` 입력을 추가했다. Auto release에는 `release-v2-prod` job과 `target: v2-prod`를 추가했다.
- 운영 스위치는 개발 스위치를 따르지 않는다. 변수가 비어 있으면 꺼진 것으로 본다.
- 두 환경이 같은 ECS 서비스를 가리키면 설정을 거부한다. 맞바꾸기(같은 클러스터를 운영으로 사용)라면 `v2-prod.json`을 추가하는 PR에서 `v2-dev.json`의 해당 서비스를 함께 빼야 한다.
- GitHub Environment 이름을 `production`이 아니라 `v2-prod`로 했다. `production`은 V1 배포 Role의 OIDC subject라, 같이 쓰면 V1 workflow와 V2 workflow가 서로의 Role을 쓸 수 있게 된다.

**남은 작업**
- [ ] `feat/v2-cd-environments` PR 병합. 동작 변화가 없어 지금 병합해도 된다
- [x] 맞바꾸기 설정 준비(브랜치 `feat/v2-prod-swap`): `v2-dev.json`과 `envs/v2-dev/` 삭제, 같은 클러스터·서비스를 가리키는 `v2-prod.json` 추가(브랜치 `main`, BE·AI job `Main - Build and Push Image`, FE job `Build and push frontend images`). **병합은 5단계 이후.** 먼저 병합하면 `main`에 V2 이미지가 없어 운영 배포 후보가 생기지 않는다
- [ ] 운영 첫 배포 전에 IAM 반영(Terraform 요청): 배포 Role 신뢰 정책에 `environment:v2-prod`, SSM 권한에 `/keepgo/v2-prod/deployments/*`. 전체 apply는 금지이므로 `-target`으로 `aws_iam_role.github_deploy`·`aws_iam_role_policy.cloud_v2_dev_cd`만 반영하고, `plan`에 두 리소스의 변경만 나오는지 먼저 확인한다
- [ ] GitHub Environment `v2-prod` 생성: 배포 브랜치 `main`만, 변수 `V2_DEPLOY_ROLE_ARN`(개발과 같은 `keepgo-v2-github-deploy`)
- [x] 앱 3곳 `develop` CI 파일의 `main` 동작 확인(2026-10-23). 병합하면 CI 파일도 `develop` 것이 된다
  - BE·AI: `main`에서 job `Main - Build and Push Image`로 개발과 같은 방식의 이미지를 만든다. 그대로 쓴다
  - FE: `main`에서 job `Build and push frontend images`로 `keepgo-web` 이미지를 만든다(nginx 이미지도 함께 만들지만 V2는 쓰지 않는다). `v2-prod.json`의 FE `job`에 이 이름을 쓴다
- [ ] **FE 기능 플래그(FE 팀 요청).** `NEXT_PUBLIC_CHAT_V2`·`NEXT_PUBLIC_WISHLIST_V2`가 `develop` 빌드에서만 `on`이다. 그대로 `main`에 병합하면 운영 FE는 V2 채팅·보관함이 꺼진 채 빌드된다. 병합 전에 `main`에서도 켜지도록 바꿔야 한다
- [ ] main CI가 이미지를 다시 빌드하면 digest가 `develop` 때와 달라 운영에 한 번 재배포된다. 배포 직후 상태를 확인한다
- [ ] 운영 첫 배포: `target: v2-prod` dry_run → `deploy-v2.yaml` 읽기 전용 사전 검사 → 실제 배포 1회 → recover 1회 시험

### 5.2 CI/CD — 8단계 (V1을 개발로)
- [ ] `sources.json`: BE·AI `main` → `develop`, FE `feat/v1` → `develop`
- [ ] FE `develop` CI가 V1 Compose용 이미지(nginx 포함)를 만들게 수정. 지금은 nginx 빌드를 건너뛴다
- [ ] `deploy-production.yaml`을 개발 배포로 전환: Environment `production` → `dev`, 인스턴스 변수 교체
- [ ] V1 배포 Role에 `environment:dev` 추가, 끝나면 `production` subject 제거
- [ ] V2 코드가 V1 Compose에서 뜨는지 확인. `services.tf` 주석상 앱이 아직 Redis·SQS를 읽지 않지만, BE·AI 코드로 확인한다

### 5.3 V1 정리 — 8단계
- [ ] 운영 데이터 삭제: V1 DB(비우거나 개발용으로 새로 생성), `/opt/keepgo/data/uploads`
- [ ] Secret을 개발 값으로 교체: JWT, OAuth 앱 키
- [ ] `compose.yaml`의 운영 고정값 분리: `SPRING_PROFILES_ACTIVE: prod`, `FRONTEND_SERVER_ADDRESS: https://keepgo.kr` → `https://dev.keepgo.kr`, 로그 그룹 `/keepgo/v1/application`, 라벨 `environment: production`
- [ ] `dev.keepgo.kr` TLS 인증서(`/opt/keepgo/tls`), 접근 제한

### 5.4 모니터링 — 6단계 전후
- [ ] Prometheus: `application`(V1)과 `application-dev`(V2)의 대상·라벨 맞바꾸기
- [ ] 규칙: V2에 `application-alerts.yml`, V1에 `development-alerts.yml`. 운영 규칙이 V2 지표 이름·라벨(ECS task, cluster)과 맞는지 확인한다. 맞지 않으면 경보가 조용히 울리지 않는다
- [ ] Grafana: `dev-*` 대시보드 이름·변수 정리, `[DEV]` 접두어를 V1 쪽으로 이동
- [ ] CloudWatch: `HTTPCode_ELB_5XX_Count`, `HealthyHostCount < 1`(1~2분 지속) 추가. [복구 시험](v2-recovery-test.md)에서 35초 중단을 아무 경보도 잡지 못했다
- [ ] CloudWatch 운영 기준값 재조정: RDS CPU·저장공간, SQS 대기 시간
- [ ] Discord: `alerts-discord.yaml` Lambda의 `LABELS`를 V1/V2 → 개발/운영으로. 운영·개발 채널 분리 권장
- [ ] `health-check.yaml`의 `PUBLIC_ORIGIN` → 운영 주소, blackbox 대상 교체
- [ ] Sentry environment, LangSmith 프로젝트, 로그 그룹 이름의 개발/운영 표기 교체

## 6. 미정 사항

| 항목 | 선택지 | 판단 기준 |
| --- | --- | --- |
| V1 데이터 이전 | 새로 시작 / 보관함·Sync만 / 전부 | 팀 밖 실사용자 여부, AI 분석 결과를 다시 만드는 비용, 두 DB의 구조 차이 |
| 이전 방식 | 점검 공지 후 dump/restore / DMS 복제 + 짧은 쓰기 중단 | 포트폴리오로 쓸지. 쓴다면 중단 시간·실패 요청 수·행 수 비교·되돌리기 시험을 기록한다 |
| BE task 수 | 1개 유지 / 2개 | 2개면 task가 죽어도 끊기지 않는다(현재 35초 중단). 대신 호스트 비용이 늘어난다 |
| RDS | t4g.micro 단일 AZ 유지 / 크기·Multi-AZ 상향 | 운영 부하와 비용 |
| Discord 채널 | 하나 / 운영·개발 분리 | 개발 알림에 운영 알림이 묻히는지 |

**데이터 이전 전 확인.** V2 DB 구조는 `ddl-auto=update`로 관리된다. 이 방식은 빠진 테이블·컬럼만 추가하고, 컬럼 이름·타입이나 값(예: `EVENT` → `event`)은 바꾸지 않는다. V1 데이터를 옮기려면 두 DB의 테이블·컬럼 목록(`information_schema`)을 먼저 비교한다.

## 7. 출시 후 해도 되는 것

- Terraform 코드를 실제 상태에 맞추기(4.2). `terraform plan`으로 차이가 0이 될 때까지 코드를 고치거나 import한다 — Terraform 담당자와 함께
- BE 2개 운영, RDS 상향
- BE CI 테스트 켜기 (지금은 테스트를 건너뛰고 빌드한다) — BE 요청
- `main`은 다시 빌드하지 않고 `develop` 이미지에 태그만 붙이기([V2 CD 계획 단계 3](v2-cd-plan.md#단계-3--app-ci-클라우드-작성))
- `ddl-auto=update` → Flyway 마이그레이션 전환 — BE와 함께
- 운영 설정으로 [복구 시험](v2-recovery-test.md) B를 다시 실행하고, 경보·Discord 수신 시각 기록
- 문서: 기술 결정(TD) 추가, 운영 절차 갱신, 앱 팀 전달(`main` = 운영, `develop` = 개발, 핫픽스 규칙)
