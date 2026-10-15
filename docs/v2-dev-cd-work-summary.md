# V2 개발 환경 중앙 CD 작업 정리

작성: 2026-10-15. 작업·검증: 2026-10-13~14, 시각은 별도 표기가 없으면 한국 시간(KST).

기존 Cloud 중앙 CD에 V2 개발 ECS 배포를 연결했다. AI는 중앙 자동 릴리스가 배포 workflow를 호출해 실제 서비스 교체까지 성공했다. BE는 개발 CI 실패로 후보에서 제외됐고, FE의 V2 배포 연결은 앱 준비 후 진행한다.

이 문서는 `feat/v1-central-cd-prep` 브랜치의 작업 기록이다. 아래 상태는 마지막으로 확인한 실행 결과이며 실시간 대시보드가 아니다. Cloud main에는 실행·설정·검증·배포 대상 파일을 반영했고 이 문서는 main에 병합하지 않았다. 이전 V2 설계 제안과 다른 내용은 이 문서의 실제 적용 결과를 기준으로 읽는다.

## 적용 결과

| 항목 | 마지막 확인 결과 |
| --- | --- |
| V1 운영 | 기존 단일 EC2/Compose 및 중앙 CD 경로 유지. BE·AI `main`, FE `feat/v1` 매핑 유지 |
| V2 BE·AI 소스 | 각 앱 저장소 `develop`. Cloud workflow 자체는 Cloud `main`에서 실행 |
| V2 AI | `keepgo-v2-ai-api:1` → `:2` 교체 성공. desired/running=1, pending=0, rollout `COMPLETED` |
| V2 BE | 자동 경로 구성 완료. 최신 확인 CI 실패로 최초 V2 CD 배포 대상에서는 제외 |
| V2 FE | 개발 브랜치 `develop`의 기존 CI 연결. S3/CloudFront 배포 job은 아직 없음 |
| GitHub 환경 | Cloud `dev`, 배포 허용 branch는 `main` 하나 |
| V2 스위치 | Repository variables `V2_CD_ENABLED=true`, `V2_AUTO_DEPLOY_ENABLED=true` |
| 주기 실행 | 기존 EventBridge가 10분마다 Auto release 호출. GitHub cron은 예비 경로 |
| ECR 즉시 실행 | 템플릿에는 규칙이 있으나 AWS에 즉시 push 규칙은 아직 미설치 |
| Terraform | 이후 원본이 Cloud `infrastructure/terraform-v2/`에 반영됨. Cloud subject·보조 정책·ECS revision 관리 범위 확인 |

## 배포 흐름과 파일 역할

1. 앱 `develop` push → 기존 CI에서 이미지 빌드·ECR 게시.
2. Cloud `auto-release.yaml` → `scripts/release.sh`의 V2 경로 → `v2_release.py` 실행.
3. 개발 브랜치의 최신 커밋, 성공한 push CI run/attempt, `Dev - Build and Push Image` job을 확인한다. 실패한 최신 커밋 대신 이전 성공 커밋을 임의로 선택하지 않는다.
4. ECR 커밋 SHA 태그를 digest로 해석한다. 이미지가 멀티 아키텍처 index라면 linux/amd64 child digest를 고정한다.
5. `deployment/envs/v2-dev/{group}.json`에 이미지와 CI 출처를 기록하고 Manifest PR을 병합한다. 파일은 배포 대상 버전의 기록이며 작업 문서가 아니다.
6. 중앙 릴리스가 `deploy-v2-dev.yaml`을 호출한다. 현재 Task Definition을 복제해 앱 이미지 참조를 교체한다. Role·Secret 참조·포트·health check·sidecar 설정은 보존한다.
7. 목표 revision, 실제 실행 digest, 컨테이너 건강 상태와 해당하는 ALB target health를 확인하고 60초 안정 관찰 후 성공으로 기록한다.

첫 AI Manifest는 검토 가능한 [Cloud #105](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/pull/105)로 등록했다. 병합 자체는 ECS를 변경하지 않았다. GitHub에서 읽기 전용 사전 검사를 통과한 뒤 V2 스위치를 켜고 Auto release를 한 번 직접 호출했다. 실제 ECS 변경은 이 자동 릴리스가 호출한 배포 workflow에서 수행했다. 이후에는 같은 경로를 10분 주기 호출이 실행한다.

| 경로 | 역할 |
| --- | --- |
| `deployment/v2-dev.json` | 저장소·브랜치·게시 job·ECR·ECS 서비스 매핑 |
| `deployment/envs/v2-dev/ai.json` | 최초 검증된 AI 배포 대상. 이후 자동 릴리스가 갱신 |
| `scripts/v2_common.py` | CI 출처·digest·설정 검증과 AWS/GitHub 호출 |
| `scripts/v2_release.py` | 후보 조회, Manifest PR 생성·병합, 배포 호출 |
| `scripts/v2_deploy.py` | 사전 검사, Task Definition 등록·서비스 교체, 실패 복구 |
| `scripts/check_v2.py`, `tests/test_v2_cd.py` | 오프라인 구성 검사와 회귀 검사 |
| `infrastructure/terraform-v2/` | 이후 공유된 Terraform 원본. IAM/ECS 관리 기준 |
| `.tools/`, `.artifacts/` | 로컬 작업 도구·전달 자료. Git/배포 PR에 포함하지 않음 |

현재 코드 확인은 [Cloud main](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/tree/main)을 사용한다. 이 문서가 있는 작업 브랜치의 코드가 main과 같다고 가정하지 않는다.

## GitHub·AWS·Terraform 설정

- 계정 `602601433533`, 리전 `ap-northeast-2`, 클러스터 `keepgo-v2`.
- Cloud Environment `dev`의 `V2_DEPLOY_ROLE_ARN`: `arn:aws:iam::602601433533:role/keepgo-v2-github-deploy`.
- 자동 조회 스위치와 AWS 배포 쓰기 스위치는 repository variable로 관리한다. 초기에는 둘 다 false로 두고 dry-run·사전 검사 후 true로 변경했다.
- Cloud Role의 정확한 subject: `repo:100-hours-a-week@167328634/KTB4-8th-CLOUD@1344688950:environment:dev`. Environment subject에는 branch가 없으므로 GitHub의 main-only 배포 제한을 함께 유지한다.
- 기존 inline policy `deploy`는 ECS 등록·갱신과 PassRole 등 실제 배포 권한이다. `cloud-v2-dev-cd`는 ECR 조회, Task/ALB 상태 검사, Task Definition 태그 보존, SSM 배포 상태 기록 권한을 추가한다.
- SSM `/keepgo/v2-dev/deployments/{backend,ai}`는 배포·실패·복구 상태용이다. 앱 Secret은 기존 Secrets Manager에서 받는다.
- Terraform의 `cicd.tf`에 보조 정책 resource/import가 반영됐고, `variables.tf`에 Cloud subject가 포함됐다. `services.tf`의 기존 ECS service는 `ignore_changes = [task_definition, desired_count]`를 사용한다.
- Terraform은 인프라 구성을, 중앙 CD는 서비스의 배포 revision을 관리한다. 이후 Task Definition의 Secret·CPU·sidecar 등을 Terraform에서 변경하면 새 revision을 서비스에 반영하는 절차도 별도로 맞춰야 한다. 현재 CD는 실행 중인 Task Definition을 복제한다.

최초 구현 때는 원격 브랜치·커밋에서 Terraform 원본을 찾지 못했다. 이후 `terraform` 브랜치와 main에 원본이 올라와 변경 사항을 확인했다. Terraform apply는 담당자가 수행했으며 이번 작업에서 별도의 Terraform apply는 실행하지 않았다.

BE DB Secret은 RDS `keepgo-v2-dev-db`의 Secret과 일치했다. JWT·외부 API 키는 `Secret-v1-BE`, `Secret-v1-AI` 참조가 확인됐으며 공용 사용 의도·애플리케이션 수준의 격리 검증은 별도 확인 사항이다. 비밀 값은 읽거나 문서에 저장하지 않았다.

## 반영 PR

| 저장소 | PR | 대상 및 내용 |
| --- | --- | --- |
| Cloud | [#99](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/pull/99) | `main`: 중앙 V2 CD. 문서·README·gitignore 변경 제외, 실행·설정·검증 파일 16개 |
| BE | [#171](https://github.com/100-hours-a-week/KTB4-8th-BE/pull/171) | `develop`: 기존 CI의 개발 브랜치와 게시 job 조건 수정 |
| AI | [#45](https://github.com/100-hours-a-week/KTB4-8th-AI/pull/45) | `develop`: 기존 CI의 개발 이미지 게시·PR 검사 연결 |
| FE | [#9](https://github.com/100-hours-a-week/KTB4-8th-FE/pull/9) | `develop`: CI 파일 하나만 반영. V1 앱 코드 미포함 |
| Cloud | [#100](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/pull/100) | `main`: workflow/job concurrency 충돌 수정, IAM 예시의 현재 subject 형식 반영 |
| Cloud | [#105](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/pull/105) | `main`: 검증된 AI Manifest 한 파일 |

위 PR들은 병합 완료했다. FE의 첫 작업 브랜치는 `feat/v1` 기반이어서 develop과 비교 시 CI 외 앱 코드 87개 파일이 포함됐다. 그 브랜치는 병합하지 않고 develop 기준 CI 변경만 다시 구성했다.

## 검증 근거

| 검증 | 결과·근거 |
| --- | --- |
| 로컬 회귀 | V2 21개, 기존 V1 runtime/deploy 22개 통과 |
| 정적 검사 | actionlint 1.7.7, Bash 문법, Python 컴파일, V2 구성 검사, diff 검사 통과 |
| Cloud PR CI | #99·#100·#105 Validate 통과. 로컬 Docker 엔진 부재로 못 한 Compose/컨테이너 검사는 GitHub Validate에서 실행 |
| Terraform 반영 후 OIDC·후보 조회 | [dry-run 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38577506120) |
| GitHub 배포 Role 사전 검사 | [AI execute=false 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38579680494) |
| 중앙 릴리스 | [V2 릴리스 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38579862163) |
| 실제 ECS 교체 | [AI 배포 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38579911433), revision 2·health·digest·안정 관찰 검증 |

실제 배포한 AI 출처는 `develop@7c9e71ef8b2dbd718102cd7c0d1f8fd7a59d60c0`, [push CI run 38529938419](https://github.com/100-hours-a-week/KTB4-8th-AI/actions/runs/38529938419), attempt 1이다. digest는 `sha256:23ce4c19c64171773cdf868673dd733514c118ae1bb4a7f02369f371e9ac88eb`다.

초기에 사전 검사한 다른 AI 후보 `71960e3`와 실제 배포 후보를 구분한다. 또한 CI 성공은 기존 CI 검사 범위 안에서의 성공이다. BE는 기존처럼 앱 테스트를 건너뛴 빌드이며, AI의 기존 Ruff/Pytest 비활성 상태를 이번 변경에서 바꾸지 않았다.

## 실패 처리와 운영 시 확인

배포 전에 이전 revision/digest와 진행 상태를 SSM에 기록한다. 배포가 실패하면 이전 revision 복구를 시도하고, 복구 여부 및 실패 이미지를 기록해 같은 후보의 무한 재배포를 막는다. 중단된 실행이나 복구 미확인 상태는 명시적인 recovery가 필요하다. 다른 주체가 알 수 없는 revision으로 서비스를 변경했다면 덮어쓰지 않는다.

자동 조회를 멈출 때는 `V2_AUTO_DEPLOY_ENABLED=false`, 일반 배포 쓰기를 차단할 때는 `V2_CD_ENABLED=false`로 설정한다. 이미 실행 중인 배포를 이 변수 변경만으로 즉시 중단하는 것은 아니다. 복구 실행은 별도 경로이며 쓰기 스위치가 false여도 허용하도록 구현했다.

실제 장애를 유발한 롤백 훈련, 로그인·채팅 등 사용자 시나리오 검증은 수행하지 않았다. 코드의 복구 회귀 검사 통과와 정상 배포 성공을 실제 장애 복구 완료로 표시하지 않는다.

## 남은 작업

| 항목 | 다음 작업 |
| --- | --- |
| BE | 개발 CI 빌드 수정 후 새 이미지 게시 확인. 성공 후보가 생기면 이미 활성화된 중앙 경로가 배포하므로 migration·Secret 준비를 함께 확인 |
| FE | develop 앱 준비 상태와 정적 export/API·OAuth 라우팅 확정, 이후 S3/CloudFront 게시 연결 |
| 검증 | 사용자 시나리오, 앱 설정 공용 사용 의도, 별도 장애 복구 훈련 |
| 즉시 트리거 | 필요하면 기존 CloudFormation 관리 경로로 ECR push 규칙 적용. 현재 10분 주기 조회는 사용 가능 |
| 문서 | 이후 상태는 해당 CI/CD 실행 근거와 함께 갱신. 이 문서의 이전 실패 SHA를 현재 최신 SHA로 오해하지 않기 |

## 트러블슈팅

- [Terraform apply가 Cloud OIDC 신뢰 조건을 덮어씀](troubleshooting/2026-10-14-v2-oidc-trust-overwrite.md)
- [Auto release workflow/job 잠금 충돌](troubleshooting/2026-10-14-v2-release-concurrency-deadlock.md)
- [개발 CI 실패로 배포 후보가 생성되지 않음](troubleshooting/2026-10-14-v2-develop-ci-not-deployable.md)
