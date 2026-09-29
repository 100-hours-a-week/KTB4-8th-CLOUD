# V2 CI/CD 설계 검토 — 중앙 자동 CD와 서비스별 자동 CD

> V2 미래 설계 문서다. 현재 v1의 구현·운영 기준은 [v1 설계](v1-design.md)와 [운영 절차](v1-operations.md)이며, 이 문서의 ECS/rolling/별도 큐 요구는 v1에 적용하지 않는다.

## 1. 결론

배포마다 사람이 승인하는 `중앙 CD + 수동` 안은 기각한다. Application PR의 코드 리뷰는 유지하며, Main 병합 이후 일반 애플리케이션 배포에는 별도의 사람 승인을 두지 않는다.

남은 선택지는 `중앙 CD + 자동`과 `독립 CD + 자동`이다. 이 문서에서는 제안된 Manifest 검증·공유 DB Migration·서비스 간 배포 순서 관리 요구에 맞춰 `중앙 CD + 자동`을 V2 기준 제안안으로 권장한다. 독립 CD는 8장에서 비교하는 대안이며, 아직 구현이 완료되거나 최종 채택된 것으로 간주하지 않는다.

권장 방향은 다음과 같다.

- 일반 애플리케이션 배포에서 Application PR 코드 리뷰를 마지막 사람 승인 지점으로 사용한다.
- `main` 최종 Commit에서 이미지를 한 번만 Build한다.
- 이미지는 Commit SHA Tag와 Image Digest로 추적한다.
- 이후 검증과 배포에서는 같은 Digest를 사용한다.
- Cloud Repository Manifest로 운영 목표 상태를 관리한다.
- ECS Service Rolling Update와 Circuit Breaker를 사용한다.
- DB는 Expand/Contract 방식으로 변경한다.
- Worker는 재전달과 멱등 처리를 기본으로 한다.

Cloud의 Workflow, IAM, IaC, Task Definition Template 등 배포 플랫폼 코드 변경에는 코드 리뷰를 유지한다. 이는 매 애플리케이션 배포마다 Cloud 담당자의 승인을 받는 절차와 구분한다.

자동 배포 적용 전에는 실패 이미지 재배포 차단, 실제 운영 상태 기준의 호환성 검증, Smoke Test 실패 복구, Manifest 정합화까지 구현해야 한다. 문서에 안전장치를 나열하는 것만으로 운영 준비가 완료되는 것은 아니다.

## 2. 이 구조의 정확한 성격

배포 코드의 보관 위치, CD 실행 주체, 배포 승인 방식은 서로 다른 선택이다. Cloud Repository에 공용 배포 코드를 보관하면서 각 Application Repository가 그 코드를 호출해 자신의 CD를 실행할 수도 있다.

아래 제안은 Cloud Repository의 Workflow가 운영 배포를 시작하고 전체 실행 순서를 관리하므로 `중앙 CD + 자동`이다.

```text
각 Application Repository
  독립적으로 검증 및 Image Build/Push
                  ↓
Cloud Repository Manifest PR
                  ↓
Cloud Repository에서 조합 검증 및 배포 직렬화
                  ↓
ECS 운영 배포
```

따라서 V2의 성격은 다음과 같다.

| 영역 | 방식 |
| --- | --- |
| Application CI | Repository별 독립 실행 |
| 배포 후보 Image 생성 | Repository별 독립 실행 |
| 운영 배포 조건 | App Main CI 성공 + Cloud 배포 전 검사 성공 |
| 운영 목표 상태 | Cloud Manifest가 관리 |
| 운영 CD 실행 | Cloud Repository에서 중앙 직렬화 |
| 배포 방식 | ECS Service별 Rolling Update |

이 문서에서 사용하는 정의는 다음과 같다.

> V2는 각 서비스가 독립적으로 배포 후보 이미지를 생성하되, 운영 반영은 Cloud Repository의 Manifest와 공용 검증 Pipeline을 통해 자동으로 직렬화한다.

중앙 CD도 변경된 서비스만 배포할 수 있다. 중앙에서 실행한다는 것이 모든 서비스를 매번 함께 배포한다는 뜻은 아니다. 다만 이 제안에서는 운영 배포 큐를 공유하므로 다른 서비스의 배포·관찰 시간을 기다릴 수 있다.

GitHub Actions가 Manifest 변경에 반응해 ECS를 갱신하는 구성이다. 지속적으로 실제 상태를 감시하고 복구하는 Controller는 별도 구현 사항이므로, Manifest를 사용한다는 이유만으로 상시 상태 정합화가 제공된다고 가정하지 않는다.

## 3. 유지해도 좋은 설계

다음 내용은 현재 설계를 유지한다.

- Application PR 코드 리뷰
- `main` Direct Push 및 Force Push 금지
- `main` 최종 Commit 기준 Image Build
- Commit SHA Tag와 Image Digest 기록
- Manifest에 Digest 고정
- 지원 환경에서 Merge Queue와 `merge_group` 검사, 미지원 시 5.4절의 자동 병합 대안
- Application 기동 시 자동 Migration 중지
- Migration을 일회성 ECS Task로 실행
- ECS Circuit Breaker와 자동 Rollback
- `services-stable` 외에 목표 Task Definition Revision 확인
- 서비스별 Smoke Test
- DB Expand/Contract
- 메시지 계약 변경 시 구·신 형식 모두 지원하는 Consumer 우선 배포
- Readiness와 Graceful Shutdown
- Worker 재전달과 멱등 처리
- SSE 재연결과 상태 복구
- ECR 운영 Image 보존

AWS CLI의 `services-stable`은 배포 Revision의 성공 여부가 아니라 Deployment 수와 `runningCount == desiredCount`를 확인한다. 따라서 목표 Revision과 `rolloutState`를 별도로 확인하는 설계가 필요하다.

- [AWS CLI services-stable](https://docs.aws.amazon.com/cli/latest/reference/ecs/wait/services-stable.html)

## 4. 필수 보완 사항

### 4.1 CloudWatch Deployment Alarm을 V2 필수 범위로 이동

ECS Circuit Breaker가 주로 감지하는 것은 다음과 같다.

- Task 기동 실패
- Container 또는 Target Group Health Check 실패
- Service가 Steady State에 도달하지 못함

다음과 같은 Application 이상은 Health Check만으로 감지하지 못할 수 있다.

- HTTP 5xx 증가
- 응답 지연 급증
- RabbitMQ 적체
- Worker 처리량 감소
- AI API Timeout 증가
- HTTP 200을 반환하지만 잘못된 결과를 생성하는 경우

따라서 아래 항목을 무승인 자동 배포의 선행 조건으로 구성한다.

| 대상 | 초기 Alarm 후보 |
| --- | --- |
| ALB | 5xx, Target Response Time, Unhealthy Host |
| Backend | 오류율, 지연, Task 반복 종료 |
| Worker | Queue 적체, 처리 실패, 재시도 증가 |
| AI API | 오류율, Timeout, 비정상 응답 |

AWS ECS는 Circuit Breaker와 CloudWatch Deployment Alarm을 함께 사용할 수 있으며, 둘 중 하나가 실패를 감지하면 이전 완료 Deployment로 Rollback할 수 있다. 두 감지 방식 각각에 Rollback을 설정하고, 배포 전 Alarm 상태도 확인한다. 시작 시 이미 `ALARM`이면 ECS가 해당 배포에서 Alarm 감시를 생략할 수 있으므로 정상 배포와 장애 복구 실행을 구분해야 한다.

- [ECS Rolling Deployment 실패 감지](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html)
- [CloudWatch Deployment Alarm](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-alarm-failure.html)

### 4.2 Bake Time과 최종 성공 판정

Smoke Test 직후 성공으로 확정하면 지연성 장애를 놓칠 수 있다.

ECS의 `COMPLETED`와 단순히 신규 Task가 정상 기동한 상태를 구분한다. ECS Deployment Alarm의 Bake Time은 ECS의 배포 완료 판정에 포함된다.

권장 절차는 다음과 같다.

```text
목표 Task Definition Revision으로 Service 갱신
→ 신규 Task 기동 및 Readiness 통과
→ 교체 상태·Alarm 감시, ECS Bake Time 경과
→ 목표 Revision의 rolloutState=COMPLETED 확인
→ 서비스별 Smoke Test 및 필요 시 추가 관찰
→ 목표 Revision·실행 Digest·Alarm 최종 확인
→ 서비스별 성공 및 Last Known Good 기록
```

초기값 예시는 다음과 같다.

| 서비스 | 초기 Bake Time |
| --- | ---: |
| Frontend | 3분 |
| Backend | 5분 |
| Worker | 10분 |
| AI API | 5~10분 |

위 값은 ECS Bake Time의 초기 설정 후보이며, GitHub Actions에서 무조건 같은 시간만큼 추가로 대기하라는 뜻은 아니다. 실제 값은 트래픽과 Metric 집계 주기에 맞춰 조정한다. 트래픽이 적으면 Alarm이 조용하다는 사실만으로 정상이라고 판단하지 않고 Synthetic 요청이나 테스트 Job으로 동작을 확인한다.

복구 주체는 다음과 같이 구분한다.

| 실패 시점 | 복구 주체와 조건 |
| --- | --- |
| ECS 배포 진행 중 기동·Health·Deployment Alarm 실패 | ECS Circuit Breaker/Deployment Alarm의 Rollback 사용, CD는 복구 완료까지 확인 |
| ECS 완료 후 Smoke Test 또는 추가 관찰 실패 | CD가 배포 전에 저장한 Last Known Good Task Definition으로 Service를 갱신하고 Health/Smoke 재검증 |
| 복구 자체 실패 또는 정상 이전 버전이 없는 최초 배포 | 후속 배포 차단 및 장애 알림, 성공으로 기록하지 않음 |

GitHub Actions의 Smoke Test 실패는 ECS에 자동 전달되지 않는다. ECS 배포 완료 후 추가 관찰 구간도 ECS의 자동 Rollback이 계속 보호한다고 가정하지 않는다. CD Timeout이나 Runner 중단 시에는 실행 기록을 이용해 진행 중인 ECS 배포를 조회·정리한 뒤 다음 배포를 허용한다.

- [ECS Deployment Alarm과 Bake Time](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-alarm-failure.html)
- [ECS Deployment 실패 감지와 Rollback 범위](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-failure-detection.html)

### 4.3 RDS Snapshot의 역할 수정

RDS Snapshot은 기존 DB를 즉시 되감는 자동 Rollback 수단이 아니다. Snapshot을 복원하면 새로운 DB Instance가 생성되므로 Endpoint 전환과 복구 시간, Snapshot 이후 데이터 처리 방안이 필요하다.

- [RDS Snapshot 복원](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_RestoreFromSnapshot.html)

DB Migration 안전장치는 다음과 같이 정의한다.

1. 운영 RDS에서 Automated Backup과 PITR을 활성화한다.
2. 일반적인 Additive Migration에는 매번 Snapshot을 생성하지 않는다.
3. Migration은 이전 Application 버전과 호환되어야 한다.
4. 파괴적인 Migration은 일반 이미지 배포에서 제외하고, 구버전 사용 종료와 데이터 이관을 검증하는 별도의 단계적 Schema 변경 절차로 관리한다.
5. 고위험 Migration에서만 사전 Snapshot을 생성한다.
6. Snapshot은 최후의 복구 수단으로 취급한다.

Migration Task에는 다음 기능이 필요하다.

- 중복 실행 방지
- Migration Lock
- Timeout
- 종료 코드 확인
- 적용 Schema Version 기록
- 실패 시 Application 배포 중단
- 재실행 안전성

이미지 Rollback 시 DB Schema를 자동으로 되돌리지 않는다. Expand Migration 이후에도 이전 애플리케이션이 동작해야 하며, Contract는 Rollback 지원 기간과 구버전 사용 종료를 확인한 뒤 수행한다. 파괴적인 변경을 일반 배포에서 제외하는 것이 일상 배포에 수동 승인 단계를 다시 추가한다는 뜻은 아니다.

### 4.4 ECS 가용성 전제 명시

`minimumHealthyPercent=100`, `maximumPercent=200`만으로 가용성이 자동 보장되지는 않는다.

다음 전제가 필요하다.

- API Service `desiredCount >= 2`
- 최소 2개 Availability Zone 배치
- ALB Target Group Health Check
- Container Health Check
- 배포 중 Task가 최대 두 배로 증가할 수 있는 CPU/Memory 여유
- 시작 시간이 긴 서비스의 `healthCheckGracePeriodSeconds`
- Service Auto Scaling 범위
- Load Balancer가 없는 Worker의 Container Health Check

초기 운영 기준 예시는 다음과 같다.

| 서비스 | 최소 Task | Health 기준 | 배포 중 최대 Task |
| --- | ---: | --- | ---: |
| Frontend | 2 | ALB `/` 또는 `/health` | 4 |
| Backend | 2 | ALB + Actuator Readiness | 4 |
| Worker | 2 또는 처리량 기준 | Container Health Check | 4 |
| AI API | 2 | ALB `/health` | 4 |

실제 Task 수는 MAU만으로 정하지 않고 RPS, 동시 연결, Job 처리량 및 응답시간 SLO를 기준으로 산정한다.

- [ECS Deployment Configuration](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_DeploymentConfiguration.html)

### 4.5 다중 서비스 부분 성공 정책 보완

앞선 서비스는 유지하고 실패한 서비스만 Rollback하려면 배포 중간 조합도 호환되어야 한다.

Backend와 Worker가 함께 변경되는 예시는 다음과 같다.

```text
운영 Backend + 운영 Worker
운영 Backend + 신규 Worker
신규 Backend + 신규 Worker
신규 Backend + 구 Worker
```

#### PR 범위와 실제 배포 범위를 구분

- Frontend PR은 Frontend Digest만 변경한다.
- AI PR은 AI Digest만 변경한다.
- Backend와 Worker의 변경을 함께 추적해야 한다면 하나의 Release ID로 묶는다.
- 이 방식은 변경의 책임과 추적 단위를 작게 유지하기 위한 권장안이다.

Release ID는 원자적 배포를 보장하지 않는다. ECS Service는 각각 갱신되며, 단일 Service 내부에서도 Rolling Update 중 구버전과 신버전 Task가 함께 실행된다.

PR을 서비스별로 나누더라도 Pending 배포가 생략되면 여러 PR의 변경이 한 번의 배포에 포함될 수 있다. 따라서 PR Diff만 보고 배포 대상을 정하지 않고, 실행 시작 시 실제 운영 상태와 고정한 목표 Manifest를 비교한다.

#### 조건부 롤링 호환성 검사의 의미

- 모든 변경에 기본 Contract·Schema 호환성 검사를 적용한다.
- API, DB Schema, 메시지 형식, 공용 설정 또는 서비스 간 의존성이 바뀌면 배포·Rollback 중 발생 가능한 조합을 추가 검증한다.
- 조건은 변경 파일과 계약 정의로 판정하고, 영향 범위를 판단할 수 없으면 검사를 실행한다. PR 작성자가 임의로 생략하는 옵션으로 두지 않는다.
- 순서는 의존 관계에 따라 정한다. 새 메시지를 발행하는 Producer 변경이라면 새 형식과 기존 형식을 모두 처리하는 Consumer를 먼저 배포한다.
- 호환되지 않는 변경은 Expand/Contract, 메시지 버전 분리, Feature Flag 등으로 단계화한다. Release ID로 묶었다는 이유로 통과시키지 않는다.

#### 부분 성공과 Rollback

기본 정책은 `성공한 서비스 유지 → 실패한 서비스 복구 → 미실행 서비스 중단`이다. 이 정책은 그 결과로 남는 조합까지 호환성이 검증된 경우에만 허용한다. 모든 서비스를 되돌리는 정책을 선택해도 Rollback은 순차적으로 일어나므로 중간 호환성 검증은 필요하다.

후보 조합 E2E가 통과했더라도 그 기준이 Cloud main이고 실제 운영 상태가 Rollback으로 달라졌다면 검증 결과를 그대로 사용하지 않는다. CD 시작 시 Actual State를 다시 읽고, 검증한 기준과 다르면 변경된 조합을 재검증하거나 배포를 중단한다.

### 4.6 Manifest 자동 PR 보안 검증

사람 리뷰 없이 자동으로 병합하므로 Manifest PR은 일반 PR보다 변경 범위를 강하게 제한한다.

필수 검사는 다음과 같다.

- 허용된 Manifest 파일만 변경됐는지 확인
- 요청한 서비스 또는 사전에 정의한 Release Group의 허용 항목만 변경됐는지 확인
- 변경값이 ECR Digest 형식인지 확인
- Digest가 예상 ECR Repository에 존재하는지 확인
- Digest가 해당 Application Repository의 `main` Commit에서 생성됐는지 확인
- Task Role, CPU, Memory, Secret, Command가 함께 변경되지 않았는지 확인
- PR 작성자가 허용된 GitHub App인지 확인

AWS OIDC는 AWS 접근 인증이다. Application Repository가 Cloud Repository에 PR을 만드는 인증은 별도 GitHub App 또는 제한된 Token으로 구성해야 한다.

자동 병합은 위 범위를 통과한 이미지 갱신·상태 정합화 PR에만 허용한다. Workflow, 검증 Script, IAM 및 Task Definition Template을 바꾸는 PR은 플랫폼 코드 리뷰 경로를 사용한다. Bot이 검증 규칙 자체를 바꿔 자동 병합할 수 없어야 한다.

### 4.7 Build 결과와 Image Digest 연결

Manifest에는 최소한 다음 정보를 기록한다.

```yaml
service: backend
source_repository: organization/backend
source_commit: 0123456789abcdef0123456789abcdef01234567
image: 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/keepgo-backend@sha256:...
build_run_id: 123456789
```

Cloud 검증 단계에서는 다음을 확인한다.

1. Source Commit이 Application `main`에 포함돼 있는지 확인한다.
2. 허용된 Repository·Main Build Workflow의 Run이 성공했고, 그 Run의 Source Commit이 Manifest와 같은지 확인한다.
3. Build Run이 기록한 Digest와 Manifest Digest가 같은지 확인한다.
4. ECR에 해당 Digest가 존재하는지 확인한다.

필요하면 Container Image Attestation을 추가해 Build Provenance를 강화할 수 있다. Private Repository의 지원 범위는 GitHub 요금제를 확인해야 한다.

- [GitHub Artifact Attestation](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)

## 5. GitHub Actions 관련 수정

### 5.1 Concurrency 정책

GitHub Actions는 기본 설정에서 같은 Concurrency Group에 하나의 실행 중 Run과 하나의 Pending Run만 유지한다. 새로운 Pending Run이 들어오면 기존 Pending Run이 취소된다.

현재 GitHub Actions는 `queue: max`를 사용해 여러 Pending Run을 순차 대기시키는 방식도 지원한다.

- [GitHub Actions Concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)

#### 최신 목표 상태만 배포

```yaml
concurrency:
  group: production-deployment
  cancel-in-progress: false
```

- 실행 중인 배포는 유지한다.
- 기존 Pending 배포는 최신 Pending 배포로 교체된다.
- Manifest 전체와 ECS 실제 상태를 비교해야 한다.
- 중간 배포 생략을 지원하는 Desired State 방식에 사용할 수 있다.

#### 여러 배포 Run을 대기열에 보존

```yaml
concurrency:
  group: production-deployment
  queue: max
```

- 최대 100개의 Pending Run을 유지하며, 큐가 가득 차면 추가 Run은 취소된다.
- 대기열 진입 순으로 처리하므로 Main Commit 순서와 동일하다고 가정하지 않는다.
- 중간 Version도 배포하므로 전체 반영이 느릴 수 있다.

V2 기준 제안안은 최신 목표 상태 우선 방식을 유지하되, 다음 조건을 구현한 뒤 사용한다.

1. 배포 잠금을 획득한 뒤 목표 Manifest Commit을 한 번 선택하고 실행 전체에서 고정한다. 실행 중 main을 다시 읽어 목표를 바꾸지 않는다.
2. 최신 main을 선택했다면 그 Commit과 정확히 같은 이미지 조합의 필수 검사가 통과했는지 확인한다. 없으면 재검증한다.
3. PR Diff가 아닌 `Actual State → 목표 Manifest 전체`로 계획을 만들고, 누적 변경·Migration·중간 호환성을 검증한다.
4. 빌드 완료 순서를 소스 최신성으로 해석하지 않는다. 서비스별 Source Commit의 선후 관계를 검사해 늦게 끝난 과거 Build가 새 버전을 덮어쓰지 못하게 한다. Rollback은 별도 복구 경로로 식별한다.
5. 중간 이미지를 건너뛰더라도 필요한 Migration과 데이터 이관을 빠짐없이 실행할 수 있어야 한다. 중간 단계가 필수인 변경은 명시적인 단계별 Release로 처리한다.
6. 실패 또는 미정리 배포가 있으면 뒤의 Run이 자동으로 계속 진행하지 못하게 한다. Concurrency Lock과 별도로 실패 차단 상태를 확인한다.

중간 배포 생략을 지원하기 어렵다면 `queue: max`와 명시적인 Release 순서 검사를 사용한다. 이 설정만으로 Commit 순서나 모든 배포의 실행이 보장되지는 않는다. 복구·재실행을 포함해 같은 운영 환경을 바꾸는 모든 Workflow가 동일한 배포 잠금 정책을 사용해야 한다.

### 5.2 `ci-gate`의 Skip 처리

GitHub Actions의 Skip 처리는 원인에 따라 다르다.

- 조건문으로 Skip된 Job은 Success로 처리될 수 있다.
- Path 또는 Branch Filter로 Workflow 전체가 실행되지 않으면 Check가 Pending으로 남을 수 있다.
- 실패한 Job에 의존하는 Gate Job은 `always()`가 없으면 Skip될 수 있다.

- [GitHub Required Status Check 문제 해결](https://docs.github.com/en/enterprise-cloud%40latest/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)

권장 규칙은 다음과 같다.

```text
- ci-gate 자체에는 Path Filter를 사용하지 않는다.
- 모든 필수 Job을 needs에 선언한다.
- if: always()로 ci-gate를 실행한다.
- needs의 결과가 모두 success인지 직접 확인한다.
- failure, cancelled, skipped를 모두 실패시킨다.
```

조건부 롤링 검사는 필수 판정 Job 안에서 적용 여부를 결정하고, 대상이 아니면 근거를 기록한 뒤 성공으로 종료한다. 필수 Job 자체를 Skip한 결과와 검증된 비대상 판정을 구분한다.

Merge Queue에서 필수 검사를 실행하려면 Workflow가 `merge_group` Event를 처리해야 한다.

- [GitHub merge_group Event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

### 5.3 새 Manifest PR 경쟁 조건

같은 서비스에 새로운 Manifest PR이 생겼을 때 기존 PR을 닫는 것만으로는 부족하다. 기존 PR이 Merge Queue에 들어갔거나 자동 병합 직전일 수 있기 때문이다.

권장 절차는 다음과 같다.

```text
서비스별 Manifest 생성 Lock
→ 기존 PR을 Merge Queue에서 제거
→ 기존 Workflow 취소
→ 기존 PR 닫기
→ 새 PR 생성
→ 새 PR Head가 최신 후보인지 확인
→ 자동 병합 직전에 최신 후보 여부 재확인
```

여기서 취소하는 Workflow는 아직 운영 변경을 시작하지 않은 후보 생성·검증 Run이다. 실행 중인 운영 배포를 새 PR 때문에 취소하지 않는다. `main에 포함된 Commit`인지만 확인하면 오래된 Commit도 통과하므로, 서비스별 최신 후보 검사도 수행한다.

### 5.4 Merge Queue 지원 조건

Merge Queue는 조직 소유 Public Repository 또는 GitHub Enterprise Cloud 조직의 Private Repository에서 사용할 수 있다. 현재 저장소의 공개 범위와 요금제에서 지원되는지 구현 전에 확인한다.

지원되지 않는 경우에는 최신 Base 반영을 필수로 하는 검사와 자동 병합을 사용하고, 병합된 목표 Commit의 조합을 CD 전에 다시 검증한다. 수동 배포 승인으로 대체하지 않는다. 지원 여부와 관계없이 Merge Queue는 운영 배포 잠금이나 실제 상태 확인을 대신하지 않는다.

- [GitHub Merge Queue 지원 조건](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)

## 6. Desired State와 Actual State

다음 상태를 구분한다.

| 상태 | 의미 | 저장 위치 |
| --- | --- | --- |
| Desired State | 운영에 반영하려는 목표 Version | Cloud `main` Manifest |
| Candidate State | 검증 중인 Version | Manifest PR |
| Actual State | ECS에서 실제 실행 중인 Version | ECS Describe API 및 배포 기록 |
| Last Known Good | ECS 완료와 Smoke/관찰 검증을 모두 통과한 서비스별 Version | Task Definition Revision·Digest·설정 참조를 SSM Parameter/DynamoDB에 기록 |
| Deployment History | 누가 언제 무엇을 배포했는지 | GitHub Deployment, CloudWatch/EventBridge |
| 실패 차단 상태 | 재시도 금지 대상과 미정리 배포 | SSM Parameter/DynamoDB의 배포 기록 |

### 6.1 실패 후 상태 정합화는 필수

예를 들어 Backend v2 배포가 실패해 ECS는 v1으로 돌아갔지만 Manifest에 v2가 남아 있으면, 다음 Frontend 배포가 전체 목표 상태를 맞추면서 Backend v2를 다시 배포할 수 있다.

실패 시 다음 절차를 반드시 수행한다.

1. 실패한 Manifest Commit, 서비스, Digest, Task Definition 및 원인을 기록하고 후속 일반 배포를 차단한다.
2. 실패한 서비스를 배포 전에 저장한 Last Known Good으로 복구하고 실제 Revision·Health·Smoke 결과를 확인한다. 성공한 서비스와 미실행 서비스의 상태도 각각 기록한다.
3. 성공한 서비스는 유지하고, 실패·중단으로 반영되지 않은 목표 항목을 검증된 실제 상태에 맞추는 Manifest 정합화 PR을 생성한다. 실제 상태를 확인하지 못했다면 추정값으로 정합화하지 않는다.
4. 정합화 PR은 당시 목표 값과 현재 main의 값을 비교해, 여전히 실패·중단된 목표가 남아 있는 항목만 수정한다. 이후 들어온 새 후보를 덮어쓰거나 Manifest 전체를 과거 버전으로 되돌리지 않는다.
5. 정합화 PR은 자동 검사를 거쳐 병합한다. 이후 새 후보가 이미 존재한다면 그 후보를 복구된 Actual State 기준으로 재검증한다.
6. 실패 후보의 무한 재시도를 차단한 상태에서 정합화 또는 검증된 수정 Release 경로만 허용한다. 복구 상태와 목표의 검증이 끝나야 일반 배포를 재개한다.

일반 배포 차단 중에도 정합화 PR의 검증·병합과 복구 Workflow는 동작해야 한다. 같은 Digest의 재시도는 실패 원인 해소와 재검증 근거를 가진 복구 실행으로 구분하며, 단순한 다음 main push가 재시도 사유가 되지 않는다.

정합화 후 Desired State와 Actual State의 이미지·Task Definition 설정이 일치하고 미적용 Migration이나 미정리 배포가 없다면 ECS 변경 없이 No-op으로 종료한다. 복구 검증과 실패 차단 해제 여부는 별도로 확인한다.

Actual State를 매 배포마다 Git에 직접 기록하면 PR과 CD가 순환할 수 있으므로 분리하는 것이 좋다.

### 6.2 `prod-<sha>` 태그의 의미

- 서비스별 최종 성공 후 이미 검증·배포한 동일 Digest에 `prod-<source-commit-sha>` 태그를 추가할 수 있다. 이미지를 다시 Build하지 않는다.
- 이 태그는 운영 배포 성공 이력을 나타내는 보조 표식이다. 현재 운영 중인 이미지의 기준은 Actual State이며, 이후 Rollback되면 태그와 현재 상태는 다를 수 있다.
- Manifest와 Task Definition은 계속 Digest를 참조한다. 태그를 운영 버전 판정이나 Rollback의 기준으로 사용하지 않는다.
- 같은 태그가 다른 Digest를 가리키면 덮어쓰지 않고 오류로 처리한다. 태그 기록만 실패한 경우에는 배포 성공과 기록 실패를 구분해 알리고 멱등하게 재시도한다.
- 여러 서비스 중 일부만 성공했다면 서비스별 성공만 기록한다. 전체 Release는 부분 실패로 남긴다.

## 7. 상시 Staging 판단

상시 Staging 없이 V2를 시작하려면 최소한 다음 조건이 필요하다.

- IaC로 ECS 설정 재현 가능
- Cloud Manifest PR에서 후보 이미지 조합 검증
- 운영과 동일한 주요 DB/Queue Version
- Readiness와 Graceful Shutdown
- ECS Circuit Breaker
- CloudWatch Deployment Alarm
- Bake Time
- 자동 Rollback
- 외부 API 실패 Mock Test
- 실제 외부 API의 주기적 Synthetic Test
- 배포 동결 Switch
- 담당자 호출 알림

작은 Staging 환경을 둘 수 있다면 다음 영역만 검증해도 가치가 있다.

```text
Task Role
Secrets Manager 접근
Security Group
ALB Routing
Service Discovery
RDS/Redis/RabbitMQ 연결
외부 API 실제 인증
```

이는 CI Compose 환경이 검증하지 못하는 부분과 일치한다.

## 8. 세 가지 CD 방식과 Cloud의 역할

### 8.1 선택지 비교 및 결정 상태

아래 표의 승인은 Application PR 코드 리뷰 이후의 운영 배포 승인을 뜻한다. 코드 리뷰는 세 방식 모두 유지할 수 있다. 중앙/독립 여부와 EC2/ECS, Recreate/Rolling 같은 실행 환경·교체 방식은 별개다.

| 방식 | CD 실행 주체 | 배포 시작 조건 | 상태·순서·복구 관리 | 검토 상태 |
| --- | --- | --- | --- | --- |
| 중앙 CD + 수동 | Cloud Repository | 이미지 준비 후 사람의 배포 승인 | 중앙 관리 | 기각 |
| 중앙 CD + 자동 | Cloud Repository | App Main CI 성공 후 Manifest 검증·자동 병합 | 중앙 관리 | 현재 요구에 맞는 V2 권장안 |
| 독립 CD + 자동 | 각 Application Repository | 해당 App Main CI와 배포 검증 성공 | 서비스별 관리, 공유 자원은 별도 조정 | 대안 |

`App CI 성공 시 자동`은 테스트가 끝나면 추가 검증 없이 운영에 올린다는 뜻이 아니다. Main CI 성공 이후 배포 전 검사와 운영 반영까지 사람 승인 없이 이어진다는 뜻이다.

### 8.2 중앙 CD + 자동을 권장하는 이유와 비용

현재 제안은 후보 이미지 조합 E2E, Backend/Worker의 공유 DB Migration, 배포 순서, 부분 실패 후 Manifest 정합화를 요구한다. 이런 판단을 한 Pipeline에서 수행하면 실제 운영 조합과 실패 처리를 일관되게 관리하기 쉽다.

Application 팀은 이미지·계약·Migration·서비스별 Smoke Test를 제공하고, Cloud 팀은 공용 배포 엔진·권한·관측·복구 정책을 관리한다. 일상 배포에서 Cloud 담당자의 응답을 기다리는 단계는 없다.

비용도 있다. 공용 검증이 실패하면 관련 배포가 막히고, 중앙 큐에서는 다른 서비스의 배포와 Bake Time을 기다릴 수 있다. GitHub App, Manifest 검증, 상태 기록, 복구 정합화도 구현해야 한다. 따라서 중앙 CD를 선택하는 근거는 단순히 Repository가 여러 개라는 사실이 아니라, 함께 조정해야 하는 운영 의존성이 있다는 점이다.

### 8.3 Cloud는 배포 소스만 관리하고 CD는 각 App에서 실행하는 대안

이 대안에서 Cloud가 관리하는 소스는 공용 Workflow·배포 Script·Task Definition Template·IaC다. Frontend/Backend/AI의 애플리케이션 소스를 Cloud에 모으는 의미는 아니다.

```text
Cloud Repository
  공용 Reusable Workflow / Script / Task Definition Template / IaC
                       ↓ 버전을 고정해 재사용
각 Application Repository
  Main CI → ECR 게시 → 공용 배포 Workflow 호출
          → 자기 ECS Service 배포 → 검증 → 성공 기록 또는 복구
```

공용 Workflow 파일이 Cloud에 있어도 각 App의 Workflow Run이 배포를 시작하고 관리하면 `독립 CD + 자동`이다. Cloud에 Manifest 갱신 PR을 보내 중앙 Workflow의 실행을 기다리는 제안과는 다르다.

이 대안을 선택할 때의 조건은 다음과 같다.

- 공용 배포 Workflow와 Template은 검증된 Commit SHA 또는 불변 버전으로 고정한다. Cloud main의 변경이 모든 App 배포에 즉시 반영되지 않게 한다.
- App별 OIDC Role과 대상 ECS Service를 제한하고, 각 서비스의 Last Known Good·배포 기록·실패 복구를 관리한다.
- 서비스별 Concurrency를 적용한다. 서로 다른 Repository의 Concurrency Group은 공유 잠금이 아니므로, 공유 DB Migration이나 서비스 간 순서가 필요하면 외부 잠금·조정 수단을 별도로 둔다.
- 서비스 간 계약과 Schema가 하위 호환되어야 하고, 다른 팀의 배포 성공을 기다리지 않아도 안전하게 배포·복구할 수 있어야 한다.
- 운영 현황을 모아 보는 중앙 Dashboard나 배포 이력 저장소는 유지할 수 있다. 이를 운영 목표 상태를 쓰는 두 번째 Controller로 만들지 않는다.

서비스들이 이 조건을 갖추고 중앙 큐의 대기 시간이 실제 문제가 될 때 독립 CD가 유리하다. 지금의 공유 Migration·조합 검증·순차 배포 요구를 그대로 유지하면서 실행 위치만 App으로 옮기면 조정 로직이 여러 곳으로 분산된다. 현재 V2에서는 중앙 자동 CD를 먼저 권장하고, 배포 의존성이 줄어든 서비스를 대상으로 독립 실행을 검토한다.

- [GitHub Reusable Workflow](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)

### 8.4 운영 상태의 변경 주체는 하나로 유지

같은 ECS Service를 App CD와 Cloud CD가 각각 직접 갱신하지 않는다. 중앙 자동 CD를 적용하는 서비스는 Cloud가 운영 배포를 실행하고 App은 이미지 게시·후보 요청을 담당한다. 독립 CD로 전환하는 서비스는 실행 주체와 상태 기록을 명시적으로 이관한다.

중앙 방식에서는 App CI의 AWS 권한을 자기 ECR 게시 등에 제한하고, 운영 ECS 갱신 권한은 Cloud CD에 둔다. 독립 방식에서는 App별 배포 Role이 자신의 Service만 갱신하도록 제한한다.

IaC도 같은 규칙을 따른다. 예를 들어 IaC가 서비스의 Task Definition 참조를 과거 값으로 되돌리지 않도록, 인프라 설정과 애플리케이션 Revision을 누가 갱신할지 정의한다. 복구 Workflow 역시 동일한 소유권·배포 잠금 정책에 포함한다.

## 9. V2 운영 적용 조건

다음 조건을 충족하면 V2 설계를 운영에 적용할 수 있다.

1. CloudWatch Deployment Alarm과 Bake Time을 V2 필수 범위에 포함한다.
2. RDS Snapshot을 즉시 자동 Rollback 수단으로 표현하지 않는다.
3. ECS 최소 Task 수, Multi-AZ, ALB Health Check 및 여유 Capacity를 명시한다.
4. Manifest PR 변경 범위와 Bot 신원을 검증한다.
5. 실제 운영 상태에서 시작하는 배포·Rollback 중간 조합의 호환성과 부분 성공 정책을 검증한다.
6. Build Run, Source Commit 및 Image Digest의 연결을 검증한다.
7. Desired State, Actual State 및 Last Known Good의 저장 위치를 분리한다.
8. 이 구조를 `독립 이미지 Build + 중앙 자동 운영 CD`로 명확히 정의한다.
9. 실패 후보 재배포 차단과 Manifest 정합화를 필수로 구현하고, 후속 변경을 덮어쓰지 않도록 한다.
10. ECS Bake Time과 CD의 추가 관찰을 구분하고, Smoke Test 실패 시 CD가 복구를 실행하도록 한다.
11. 중간 배포 생략·실행 순서 역전·Runner 중단에 대한 처리와 운영 상태 변경 주체를 명시한다.
12. Merge Queue 지원 여부를 확인하고, 지원되지 않으면 최신 Base 검사·자동 병합·배포 전 재검증을 구성한다.

## 10. V2 기준 제안 흐름

아래 흐름은 `중앙 CD + 자동`이다. Main 이후 별도의 사람 배포 승인은 두지 않으며, 실패하면 자동 검사가 반영을 막고 알린다.

```text
[Application Repository — Frontend / Backend / AI]

feature/* push
  → 빠른 검사: 정적·타입 검사, 단위 테스트
feature/* → main PR
  → PR CI → ci-gate 통과 + 코드 리뷰 → main 병합
main push
  → Main CI: 필수 테스트 → 이미지 Build·실행 검증 → ECR 게시
  → 기록: Source Commit SHA, Image Digest, Build Run, 테스트 결과
  → Main CI 성공을 확인한 자동화가 Manifest 갱신 PR 생성
                         ↓
[Cloud Repository]

Manifest PR
  → 변경 범위·Bot 신원·Build 출처 검증
  → 이미지·Task Definition 검증, 후보 조합 E2E
  → 기본 호환성 검사 + 변경 영향에 따른 롤링 조합 추가 검사
  ├ 통과: Merge Queue로 자동 병합
  └ 실패: 병합하지 않고 알림
                         ↓ 자동
CD — 운영 환경별 한 번에 하나씩 실행
  → 사전 확인: 배포 잠금, 실패 차단 상태, 고정한 목표 Commit의 검사 결과
  → Actual State와 목표 전체 비교, 기준 변경 시 조합 재검증
  → 서비스별 Last Known Good 및 배포 계획 저장
  → DB Migration이 있을 때만 일회성 Task 실행·종료 코드 확인
  → 변경된 서비스만 의존 순서대로 Rolling Update
      서비스마다:
        Digest가 고정된 Task Definition Revision 등록 → Service 갱신
        → Readiness·Alarm 감시 및 ECS Bake Time
        → 목표 Revision의 완료 판정 → Smoke Test·필요 시 추가 관찰
        ├ 성공: Actual Digest·Revision·Last Known Good 기록
        │       동일 Digest에 prod-<source-commit-sha> 보조 태그 부여
        └ 실패: 후속 배포 차단 → 해당 서비스 자동 복구·복구 검증
                → 남은 서비스 중단 → 부분 실패 기록·알림
                → Manifest 정합화 PR → 자동 검증·병합
                → 복구 상태와 새 목표 검증 후 배포 재개
```

Migration이 실패하면 Service 갱신으로 넘어가지 않고 배포를 중단한다. Schema는 자동으로 되돌리지 않으며, 이미 적용된 변경과 기존 서비스의 상태를 확인한다. 검증된 이전 배포가 없는 최초 배포는 자동 Rollback 대상이 없으므로 별도의 초기 배포·복구 절차가 필요하다.

배포의 최종 성공은 단순히 `Service 안정화` 또는 `태그 생성`으로 판단하지 않는다. 목표 Revision, 실제 실행 Digest, Smoke Test, 관찰 결과가 모두 기준을 충족해야 한다.

### 10.1 Repository별 책임

| 영역 | Application Repository | Cloud Repository |
| --- | --- | --- |
| 코드 품질과 이미지 | PR/Main CI, 이미지 Build·실행 검증, ECR 게시, 출처 기록 | Build 출처·Digest 검증 |
| 배포 요청 | 자신의 서비스 또는 허용된 Release Group의 Manifest PR 생성 | 변경 범위 검사·후보 조합 검증·자동 병합 |
| Task Definition | 실행 방법, 자원·Secret·Health 요구사항 제공 | Template·Role·설정 검증 및 Revision 등록 |
| DB Migration | Migration 코드와 하위 호환성 Test | 잠금·실행·Timeout·종료 코드 검사 |
| 운영 검증 | 서비스별 Smoke·Contract Test 제공 | 공용 Pipeline에서 실행하고 Alarm과 함께 판정 |
| 배포·복구 | 실패 원인 분석과 수정 이미지 제공 | ECS 갱신, 직렬화, 상태 기록, 자동 복구, Manifest 정합화 |

### 10.2 단계별 도입

1. 각 App의 Main CI에서 실행 검증된 이미지를 한 번 생성하고 Digest와 출처를 기록한다.
2. Cloud에서 이미지 갱신 PR 검증·자동 병합과 단일 서비스 배포를 연결한다. 첫 운영 자동 배포 전부터 Health/Smoke·Alarm·복구·실패 차단을 함께 갖춘다.
3. Migration과 Backend/Worker의 중간 조합 검증, 부분 실패 정합화를 확인한 뒤 복수 서비스 변경을 허용한다.
4. 최신 상태로 중간 배포를 건너뛰는 경우와 장애·Timeout 시나리오를 검증한다. 독립 CD 전환은 운영 의존성과 실제 배포 대기 시간을 근거로 판단한다.

## 11. 기존 문서·현재 구현과의 관계

검토 시점의 저장소에는 서로 다른 단계의 내용이 함께 있다.

| 자료 | 현재 의미 | V2와의 관계 |
| --- | --- | --- |
| `docs/ci-cd-repository-responsibilities.md` | App이 SSM으로 EC2의 공용 Script를 호출하는 서비스별 CD 설계 | EC2·Compose 기반 대안으로 읽어야 하며, V2 중앙 실행 책임표와 혼용하지 않음 |
| `.github/workflows/deploy-production.yaml` | 수동 실행으로 EC2에 SSM 배포 요청 | V2 자동 ECS Workflow가 아직 구현된 상태가 아님 |
| `scripts/deploy.sh` | 전체 Compose 반영, Health/Smoke는 미구현이라고 명시 | 서비스별 ECS 배포·자동 복구를 제공하지 않음 |
| `deployment/production-manifest.yaml` | Commit SHA Tag 자리표시자 기반 형식 | V2의 Digest·출처·검증 정보 계약으로 확장 필요 |

기존 책임 문서의 `Cloud main 병합으로 앱을 배포하지 않는다`, `운영 버전은 EC2 Runtime 파일에 둔다`는 규칙은 해당 EC2 독립 CD 안의 규칙이다. V2 중앙 자동 CD에서는 Cloud main Manifest가 목표 상태이고 Cloud Workflow가 운영 배포를 실행한다.

이 문서는 설계 제안과 검토 결과를 기록한다. 실제 Workflow·IAM·ECS 설정을 구현하거나 AWS에서 배포·Rollback 동작을 검증한 완료 보고서가 아니다. V2 채택 시 기존 책임 문서에도 적용 버전과 상태를 명시해 운영 지침이 충돌하지 않도록 정리해야 한다.
