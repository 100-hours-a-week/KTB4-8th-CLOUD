# V2 개발 CD 운영 절차

## 배포 경로

기존 Cloud 중앙 CD를 유지한다. BE·AI 운영 main과 FE 운영 feat/v1은 V1 인스턴스에 배포한다. BE·AI develop은 V2 ECS에 배포한다. 앱 CI는 이미지만 게시하고 ECS를 직접 갱신하지 않는다.

같은 `auto-release.yaml`의 운영 job은 기존 `release.sh` 경로를 사용하고 V2 job은 `RELEASE_TARGET=v2-dev`로 같은 진입점을 호출한다. V2의 digest/출처 형식은 V1 SHA Manifest와 달라 Python 모듈로 처리한다. 저장소와 호출 체계는 공유하며 실제 배포 엔진만 SSM/Compose와 ECS로 나눈다.

| 항목 | V1 운영 | V2 개발 |
| --- | --- | --- |
| 소스 | `deployment/sources.json` | `deployment/v2-dev.json` |
| 목표 버전 | `deployment/production-manifest.json` | `deployment/envs/v2-dev/{backend,ai}.json` |
| 이미지 기준 | 커밋 SHA 태그 | CI commit/run/attempt와 ECR digest |
| GitHub Environment | production | dev |
| 배포 Role | 기존 AWS_DEPLOY_ROLE_ARN | V2_DEPLOY_ROLE_ARN |
| 실제 배포 | deploy-production.yaml → SSM/Compose | deploy-v2-dev.yaml → ECS |
| 자동 조회 스위치 | AUTO_DEPLOY_ENABLED | V2_AUTO_DEPLOY_ENABLED |
| AWS 배포 쓰기 스위치 | 기존 정책 유지 | V2_CD_ENABLED |
| 배포 상태 | 기존 V1 상태 | SSM `/keepgo/v2-dev/deployments/{backend,ai}` |

실제 V2 Manifest는 성공한 개발 CI 이미지가 발견된 뒤 생성한다. 현재 실행 중인 임의의 이미지를 개발 CI에서 검증된 것처럼 미리 기록하지 않는다.

## CI 변경

CI 파일이 없어서 새로 만드는 작업이 아니다. 기존 CI의 브랜치 필터와 게시 job 조건을 실제 브랜치에 맞춘다.

- BE `.github/workflows/ci.yml`: 삭제된 dev 대신 develop을 대상으로 한다. develop 게시 job 이름은 `Dev - Build and Push Image`, main은 기존 `Main - Build and Push Image`를 유지한다.
- AI `.github/workflows/ci.yml`: develop push 이미지 게시와 develop 대상 PR 검사를 추가한다. 운영 main 게시 조건과 이름은 유지한다. 기존 Ruff/Pytest 주석은 그대로이므로 이 변경이 앱 단위 테스트를 새로 활성화하는 것은 아니다.
- FE `.github/workflows/frontend-ci.yml`: V2 개발 브랜치는 develop으로 확정했다. develop 기준 기존 CI에 develop push 조건만 추가해 품질 검사를 실행한다. 앱 소스나 lockfile이 없으면 개발 CI는 실패한다. 해당 workflow의 이미지 게시는 기존처럼 main만 허용하며 별도 운영 feat/v1의 CI는 변경하지 않는다. V2 S3 게시 job은 아직 없다.
- CI 변경은 각 앱 저장소의 develop 대상 PR로 반영한다. 처음 FE `ci/v2-development`는 feat/v1 기반이었으므로 병합 대상에서 제외하고, develop에서 CI 변경만 담은 `ci/v2-develop-trigger`를 새로 만들었다. V1 앱 코드 87개 파일이 develop에 섞이는 것을 방지했다.

BE는 기존처럼 bootJar 빌드이며 앱 테스트를 실행하지 않는다. AI도 현재 의존성 설치와 Docker 빌드 중심이다. 중앙의 "CI 성공"은 이 실제 검사 범위만 의미한다.

## IAM 연결

조회 당시 V2 Role은 앱 3개 저장소의 일반 형식 `environment:dev` subject만 신뢰했다. 반면 실제 V1 Role과 앱 게시 Role은 소유자·저장소 ID가 포함된 subject를 사용한다. 새 Cloud/dev와 앱/develop 조건도 조회된 ID 형식으로 맞춘다.

- Cloud: `repo:100-hours-a-week@167328634/KTB4-8th-CLOUD@1344688950:environment:dev`
- BE: `repo:100-hours-a-week@167328634/KTB4-8th-BE@1344686243:ref:refs/heads/develop`
- AI: `repo:100-hours-a-week@167328634/KTB4-8th-AI@1344686800:ref:refs/heads/develop`

`scripts/configure_v2_iam.py`는 기본적으로 현재 정책을 읽고 `infrastructure/v2-cd/`에 검토할 JSON만 쓴다. `--apply`는 기존 조건을 보존한 채 위 subject를 정확히 추가하고, V2 Role에 `cloud-v2-dev-cd` 보조 정책을 추가한다. 이 정책은 ECR 출처 조회, ECS Task/태그 조회·태그 보존, ALB target health 조회, 두 그룹의 SSM 배포 상태 읽기/쓰기를 허용한다. 기존 V2 `deploy` 정책의 서비스 갱신/Task Definition 등록/PassRole 권한을 함께 사용한다.

기존 앱 저장소의 V2 Role 신뢰 조건은 이번 추가 작업에서 삭제하지 않는다. 자동 CD 활성화 전에 App workflow나 Terraform이 동시에 ECS 서비스 revision을 갱신하지 않는지 확인한다. 중앙 CD가 배포하는 동안 동일 서비스의 변경 주체는 Cloud 하나여야 한다.

2026-10-13 위 IAM 추가 사항을 AWS에 적용하고 세 Role의 신뢰 정책 및 보조 정책을 재조회해 일치를 확인했다. 기존 production/main 조건과 기존 inline policy는 유지했다. 이는 OIDC 실인증 성공 기록이 아니라 정책 반영 확인이다.

Terraform 원본에도 동일한 IAM 변경과 ECS Task Definition 관리 범위를 반영해야 한다. 코드가 없는 상태에서 CLI로 반영한 변경은 다음 apply로 덮어써질 수 있다.

## GitHub 설정과 활성화 순서

1. Cloud 저장소 Environment `dev`를 생성/확인하고 배포 브랜치를 Cloud `main`만 허용한다. Environment를 사용하는 OIDC subject에는 브랜치가 들어가지 않으므로 이 제한을 따로 설정한다.
2. Environment variable `V2_DEPLOY_ROLE_ARN=arn:aws:iam::602601433533:role/keepgo-v2-github-deploy`를 설정한다. 알림용 `DISCORD_WEBHOOK_URL`은 기존 조직/저장소/Environment 설정을 사용한다.
3. Cloud **repository variables** `V2_CD_ENABLED=false`, `V2_AUTO_DEPLOY_ENABLED=false`로 시작한다. job의 실행 조건에서 읽으므로 자동 스위치는 Environment 전용 변수로 두지 않는다.
4. 앱 CI 변경을 develop에 반영하고 성공한 `Dev - Build and Push Image` 및 커밋 SHA 이미지 게시를 확인한다. AWS_ECR_PUSH_ROLE_ARN과 ECR_REPOSITORY 등 기존 앱 변수는 재사용한다.
5. Cloud 코드가 main에 반영되면 `Auto release`를 `target=v2-dev`, `dry_run=true`로 실행한다. 이는 조회만 하며 PR·배포를 만들지 않는다.
6. 수동 최초 후보 생성은 `V2_AUTO_DEPLOY_ENABLED=true`로 하고 `Auto release`의 `target=v2-dev`, `dry_run=false`로 실행한다. 이 스위치를 켜면 기존 주기 호출도 후보를 조회한다. `V2_CD_ENABLED=false`인 동안 ECS 변경은 거부되므로 Manifest·출처를 먼저 확인할 수 있다. 초기 확인 후 자동 조회를 잠시 끌 수 있다.
7. `Deploy V2 development`에서 그룹을 선택하고 `execute=false`로 사전 검사한다. provenance, 현재 revision, 실행 digest, container/ALB health를 확인한다.
8. 수동 실제 시험 시 `V2_CD_ENABLED=true`, `V2_AUTO_DEPLOY_ENABLED=false`로 두고 `execute=true`를 선택한다. 정상 배포와 복구를 확인한 뒤 두 스위치를 모두 true로 하여 자동 연결한다.

기존 EventBridge가 입력 없이 Auto release를 호출하면 기본 target=all로 각 환경 스위치를 따른다. schedule도 두 환경을 조회한다. `feat/ecr-push-trigger`에 남아 있던 ECR push 규칙과 CI 대기 코드를 재사용했다. V1/V2 모두 진행 중 CI를 최대 180초 기다리고 이후에는 다음 조회가 처리한다. CloudFormation 템플릿을 작업 브랜치에 반영한 것과 실제 AWS 규칙 적용 여부는 별개이며, 실제 이벤트 규칙은 재조회/배포 확인해야 한다. 기존 주기 조회만으로도 동작한다.

## 성공·실패 판정

배포 전 latest CI run/attempt 및 게시 job 성공을 다시 확인하고 SHA 태그의 digest가 Manifest와 같은지 확인한다. 멀티 아키텍처 이미지라면 linux/amd64 child digest를 고정한다.

현재 서비스의 Task Definition을 복제하며 앱 컨테이너의 이미지만 바꾼다. JWT 초기화 sidecar, Secret 참조, Role, CPU/메모리, 로그·포트·볼륨·health check와 사용자 태그를 보존한다. 새 AWS 필드를 모르면 누락시켜 등록하지 않고 실패한다.

서비스의 목표 revision이 COMPLETED이고 실행 중 Task의 revision·실제 digest·health가 모두 일치해야 한다. BE는 현재 Task IP의 ALB target health도 검사한다. 이 상태를 60초 유지한 뒤 성공 기록을 쓴다. 이 관찰은 ECS bake time 설정 변경과 다르며, 로그인·채팅 등의 사용자 시나리오 검증을 대체하지 않는다.

등록/갱신 전에 이전 revision·digest와 `deploying`을 SSM에 기록한다. 실패하면 이전 revision으로 복구하고 같은 방식으로 확인한다. 복구 완료여도 해당 실패 이미지는 자동 재배포하지 않는다. Manifest는 실패 후보를 유지하고 SSM이 차단하므로 이 단계에서는 자동 정합화 PR을 만들지 않는다. 다음 검증된 새 후보 또는 명시적 재시도로 진행한다.

실행 중 runner가 종료되거나 복구가 확인되지 않으면 이후 후보도 차단한다. `Deploy V2 development`에서 `recover=true`, `execute=true`로 복구한다. 원인을 해결한 동일 이미지 재시도는 복구 완료 후 `retry_failed=true`로 실행한다. 복구는 V2_CD_ENABLED가 false여도 가능하다. 다른 주체가 revision을 바꿨으면 덮어쓰지 않고 사람이 실제 상태를 확인하도록 실패한다.

## 검증 명령

```powershell
python scripts/check_v2.py
python -m unittest discover -s tests -p 'test_v2*.py'
python -m unittest discover -s tests -p 'test_runtime*.py'
python scripts/v2_deploy.py --group backend --inspect
python scripts/v2_deploy.py --group ai --inspect
```

`--inspect`는 AWS 쓰기 없이 현재 인프라만 검사한다. 후보 CI 출처, 새 배포, 롤백, 사용자 시나리오를 검증한 것으로 표시하지 않는다. 실제 자동화 성공은 GitHub OIDC 인증부터 develop 이미지 게시·Manifest 병합·ECS 교체까지 연결한 실행 기록으로 판단한다.

2026-10-13 BE·AI 모두 `--inspect` 통과. 조회한 실제 digest는 BE `sha256:038ebf6cd65a1b761adb725ba15fdd5a60148e1286559c7f3fa18fd81d1c9de8`, AI `sha256:f0e01e92f7fa0a60dee2dc8ea6699c910a8b69a69a0c19bf3bb6894c6301c42f`다. 두 서비스 모두 revision 1이며 실제 서비스 갱신은 실행하지 않았다.

로컬 회귀 검사는 V2 21개와 기존 V1 22개가 통과했다. 변경 workflow의 actionlint 검사 및 release.sh 문법 검사도 통과했다. Cloud 변경은 `feat/v2-dev-cd` → main, BE·AI는 `ci/v2-development` → develop, FE는 `ci/v2-develop-trigger` → develop으로 반영한다. GitHub Environment/변수 설정, GitHub OIDC 실인증·수동 배포/롤백 검증과 자동 스위치 활성화는 아직 수행하지 않았다.

2026-10-14 병합 전 GitHub 변수 조회 결과 V1 `AUTO_DEPLOY_ENABLED=true`였고 V2 스위치 두 개는 설정되어 있지 않았다. 따라서 Cloud 코드 병합만으로 V2 자동 배포는 시작되지 않는다. AI develop은 `f5ed5e3`으로 갱신됐지만 CI 파일에는 충돌이 없었고, FE develop에는 아직 애플리케이션 소스 디렉터리가 없었다. FE CI 반영 후 source_check 실패는 이 미준비 상태를 알리는 것이며 FE 배포가 완료됐다는 의미가 아니다.

## 남은 앱·인프라 작업

- FE 개발 브랜치의 실제 앱 코드, Next.js 정적 export 가능 여부, API/OAuth/public 파일 라우팅을 확정한다. standalone 서버 산출물을 S3로 업로드하는 구현은 하지 않는다.
- 현재 별도 Worker/SSE 서비스가 없으므로 이번 배포 그룹에 추가하지 않는다.
- 개발 DB·Secret의 운영 분리, migration 하위 호환성, 주요 API/로그인/채팅 동작은 앱 담당자와 실증한다.
- Terraform 재적용이 CD revision과 추가 IAM 정책을 되돌리지 않도록 원본에 반영한다.

참고: [ECS Task Definition 등록](https://docs.aws.amazon.com/cli/latest/reference/ecs/register-task-definition.html), [GitHub OIDC subject](https://docs.github.com/en/actions/reference/security/oidc), [Terraform ignore_changes](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle#ignore_changes).
