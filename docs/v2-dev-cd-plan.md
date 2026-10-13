# V2 개발 환경 CD 연결

2026-10-13. 기존 Cloud 중앙 CD를 확장한다. 운영은 V1에 유지하고 개발 버전만 V2에 배포한다. 이 문서는 예전 `dev → V1, main → V2` 전환안보다 우선한다.

## 확인한 최신 상태

- Cloud `origin/main`: `5d79e9e` (2026-10-13). 이 커밋에서 구현 브랜치를 만들었다. 기존 작업 폴더의 수정 파일은 유지한다.
- 운영 소스: BE·AI `main`, FE `feat/v1`. FE를 main으로 임의 변경하지 않는다.
- BE 개발 브랜치: `develop` (`503a236`). `dev`는 원격에서 삭제됐으나 CI는 여전히 `main, dev`를 대상으로 한다.
- AI 개발 브랜치: `develop` (`4847603`). 현재 CI는 develop 이미지를 게시하지 않는다. main은 `6e9c5cf`로 서로 다르다.
- FE `main`, `develop`, `feat/v2`는 조회 시 모두 `ea0683c`다. `feat/v2`는 새 브랜치 이름일 뿐 최신 애플리케이션 코드가 들어온 상태가 아니다. 운영 `feat/v1`은 `ed05936`이다.
- AWS 계정 `602601433533`, 리전 `ap-northeast-2`, ECS 클러스터 `keepgo-v2`.
- 서비스는 `keepgo-v2-backend`, `keepgo-v2-ai-api` 두 개. 각각 desired/running 1, 현재 배포 COMPLETED. Worker/SSE 서비스는 없다.
- BE 이미지: `keepgo-backend:503a23686080485cae89c0cae152a33e3aac8528`, AI 이미지: `keepgo-ai:6e9c5cf7b2993238b613804fb1a6fdd7bf04657b`. 생성된 인프라가 이미 서로 다른 브랜치의 이미지를 실행 중이다.
- 두 서비스는 rolling/circuit breaker rollback을 사용하며 bake time은 0이다. BE에는 ALB, AI에는 컨테이너 health check가 있다.
- FE 인프라: S3 `keepgo-v2-web-602601433533`, CloudFront `E39SIXDYF1OH7R`. 현재 FE 개발 브랜치에는 완성된 정적 배포 산출물 계약이 없다.
- 새 Role `keepgo-v2-github-deploy`는 App 3개 저장소의 `environment:dev`만 신뢰한다. Cloud 중앙 CD용 신뢰 조건을 추가해야 한다. 기존 V1 중앙 CD의 권한과는 별개다.

## 구현 순서

1. V1의 소스 매핑·Manifest·SSM 배포 경로를 유지한다.
2. 같은 Auto release workflow에 V2 조회를 추가한다. 별도 스위치로 켜고 V1과 실행 잠금을 분리한다.
3. 개발 브랜치 CI 성공과 게시 job 성공을 확인하고 ECR의 커밋 SHA 태그를 digest로 해석한다. V2 Manifest에 출처와 digest를 기록한다.
4. 중앙 Cloud에서 V2 그룹별 ECS 배포 workflow를 실행한다. 서비스가 사용하는 Task Definition을 복제하고 지정 앱 컨테이너의 이미지만 변경한다. JWT 초기화 컨테이너, Secret 참조, Role, 포트, health check를 보존한다.
5. 목표 revision·실제 digest·컨테이너 health·ALB target health를 확인한다. 실패 후보와 진행 중 배포를 SSM에 기록한다. 실패 시 이전 정상 revision 복구를 확인하고 같은 후보의 자동 재배포를 차단한다.
6. BE·AI develop CI에서 이미지 게시가 되도록 각 앱 저장소의 기존 파일을 직접 수정한다. 기존 main 게시 job과 운영 CI 이름은 유지한다.
7. 로컬 회귀 테스트·workflow 검사·AWS 읽기 전용 사전 검사를 수행한다. 이후 역할·GitHub Environment 설정을 반영하고 수동 배포·롤백을 검증한 후 V2 자동 스위치를 켠다.

## 이번 연결의 범위

환경 이름은 `v2-dev`, GitHub Environment는 `dev`다. 개발 브랜치는 현재 원격에 존재하는 BE·AI `develop`을 기본 매핑으로 두되 활성화 전에 팀 확인한다. Cloud workflow 자체는 Cloud `main`에서 실행한다. 앱 브랜치와 Cloud 브랜치를 혼동하지 않는다.

첫 배포 대상은 실제 존재하는 BE·AI 서비스다. FE는 브랜치의 앱 코드 및 정적 export/API 라우팅 계약이 정해지기 전까지 자동 배포를 활성화하지 않는다. Worker/SSE, 별도 migration task는 실제 앱·인프라 계약 없이 만들지 않는다. 현재 앱이 시작할 때 수행하는 DB migration은 DB 하위 호환성을 확인해야 하며 이미지 롤백이 스키마를 되돌리지는 않는다.

main 재빌드 금지·dev 이미지의 운영 승격 정책은 이번 변경에서 적용하지 않는다. V1 운영 CI를 유지한다. 운영 트래픽과 DNS도 이번 구현에서 변경하지 않는다.

## Terraform 담당자와 맞출 사항

Terraform 코드가 없어도 기존 AWS 설정으로 CD를 작성할 수 있다. 다만 ECS 서비스의 `task_definition`은 CD가 갱신하므로 다음 apply가 예전 revision으로 되돌리지 않도록 관리 주체를 정해야 한다. `ignore_changes = [task_definition]`을 쓰는 경우에도 Role·환경변수·자원 설정 변경을 새 revision에 반영하는 절차를 유지한다. Auto Scaling이 desired_count를 관리한다면 해당 속성도 같은 방식으로 검토한다.

V2 Role의 OIDC 신뢰 조건에 `repo:100-hours-a-week/KTB4-8th-CLOUD:environment:dev`를 반영하고, GitHub Environment `dev`의 배포 브랜치는 Cloud `main`만 허용한다. 앱 이미지 게시 Role은 실제 개발 브랜치를 허용해야 한다. IAM 변경은 제공한 최소 정책과 현재 정책을 비교해 Terraform 원본에도 반영한다.

## 완료 판정

- [x] 원격 4개 저장소 fetch 및 실제 AWS 서비스 조회
- [x] 최신 Cloud main에서 격리된 구현 브랜치 생성
- [x] V2 조회·Manifest·배포·복구 코드와 회귀 테스트 21개
- [x] 각 앱 저장소 CI 파일 직접 수정, actionlint 검사 통과
- [x] Cloud/dev 및 BE·AI/develop IAM subject 추가·재조회 확인, V2 조회/상태 기록 보조 정책 반영
- [ ] GitHub Environment/변수 설정 및 Terraform 관리 범위 합의
- [ ] 수동 정상 배포와 실패 복구 실증
- [ ] V2 자동 배포 활성화

코드 검증과 AWS 실배포 검증은 별도로 기록한다. 읽기 전용 조회 성공을 실제 CD 성공으로 취급하지 않는다.

검증 결과: V2 회귀 테스트 21개, 기존 V1 runtime/deploy 회귀 테스트 22개 모두 통과. Cloud와 앱 3곳의 변경 workflow는 actionlint 1.7.7 검사 통과. release.sh Bash 문법, Python 컴파일, V2 설정 검사, git diff --check 통과. 실제 BE·AI 인프라 읽기 전용 검사도 통과했다. Docker 엔진이 실행 중이지 않아 전체 Compose/컨테이너 기반 검사는 실행하지 못했으며 Compose 파일은 이번 변경에서 수정하지 않았다.

## 기존 브랜치 재사용

원격을 fetch한 뒤 모든 원격 브랜치의 workflow/scripts/infrastructure/deployment 파일 목록과 CD 이력을 대조했다.

| 브랜치 | 확인 결과 | 이번 반영 |
| --- | --- | --- |
| `feat/v1-central-cd-prep` (`fa06f30`) | 기존 V2 설계·운영 문서와 ECR 이벤트 변경이 남아 있다 | 새 환경 배치를 이 문서에 기록. 기존 작업 폴더와 사용자 문서는 보존 |
| `feat/ecr-push-trigger` (`847111f`) | ECR push 이벤트, 진행 중 CI 최대 180초 대기, schedule 예비 안내가 main에 미반영 | 기존 release.sh 대기 구현과 github-dispatch.yaml의 이벤트 규칙 재사용. V2에도 같은 제한 시간의 CI 대기 적용 |
| `feat/v1-central-cd`, `dice/cd-setup` | main에 없는 별도 커밋 없음 | 기존 중앙 CD 기반 그대로 사용 |

조회한 원격 브랜치에는 V2 ECS 배포 스크립트/workflow나 Terraform 파일이 없었다. 따라서 ECS revision·digest 검증과 복구 엔진은 이번에 추가했다. 브랜치 전체를 합쳐 최신 운영 이미지나 앱 설정을 과거 값으로 되돌리지 않고 필요한 CD 변경만 재사용했다.
