# 2026-10-14 Terraform apply가 V2 중앙 CD의 OIDC 신뢰 조건을 덮어씀

작성: 2026-10-15. 상태: Terraform 원본 반영과 후속 GitHub OIDC·실배포 성공 확인. 시각은 KST.

## 🐞 에러 내용

V2 배포 Role `keepgo-v2-github-deploy`에 Cloud 저장소 신뢰 조건을 추가했는데, 다음 조회에서 해당 조건이 사라지거나 다른 값으로 바뀌었다. BE·AI 이미지 게시가 성공하는 것과 별개로 Cloud 중앙 CD가 배포 Role을 사용하는 조건이 맞지 않았다.

초기에는 앱 세 저장소만 허용했다. 후속 변경에서는 Cloud 저장소도 목록에 들어왔으나 `:environment:dev`가 빠져 있었다. 이 상태에서는 Cloud의 `environment: dev` job이 발급받는 subject와 일치하지 않는다. 최초 dry-run의 로그 없는 실패는 별도의 [concurrency 충돌](2026-10-14-v2-release-concurrency-deadlock.md)이었으며 이 IAM 문제와 구분한다.

## 🔍 원인 분석

현재 정책만 보고 Terraform을 원인으로 단정하지 않고 CloudTrail의 `UpdateAssumeRolePolicy` 이벤트를 확인했다. IAM 변경 기록은 `us-east-1`에서 발견했고 같은 조회의 서울 리전 결과는 없었다.

| 시각 | API 호출 주체 | 요청 도구 | 결과 |
| --- | --- | --- | --- |
| 10/13 16:50:40 | `ktb8-rowan` | AWS CLI | Cloud의 `environment:dev` 조건 추가 |
| 10/13 17:13:30 | `dice_terraform` | Terraform | 정책을 앱 세 저장소 조건으로 교체, Cloud 조건 제거 |
| 10/14 13:42:14 | `ktb8-rowan` | AWS CLI | 기존 조건을 보존해 Cloud 조건 복구 |
| 10/14 14:24:52 | `dice_terraform` | Terraform | Cloud는 포함했지만 Environment가 빠진 subject로 정책 교체 |

Terraform 요청의 userAgent에는 `Terraform/1.16.4`, `terraform-provider-aws/6.68.0`이 있었다. 위 기록은 사용한 AWS 계정과 도구를 입증하며 실제 키보드를 조작한 개인을 별도로 추정하지 않는다.

주요 CloudTrail event ID:

- 10/13 제거: `965dcd88-2975-44f5-9d88-b5d84b6d7c42`
- 10/14 CLI 복구: `ece94364-9410-4dac-a371-d3137ddd0199`
- 10/14 Terraform 교체: `e534e88c-d649-4199-8b1c-a99f51cc606f`

문제 값과 필요한 값은 다음과 같다. `StringLike`를 사용하더라도 와일드카드가 없는 문자열은 필요한 접미사를 대신 허용하지 않는다.

```text
# 잘못 반영된 값
repo:100-hours-a-week@167328634/KTB4-8th-CLOUD@1344688950

# Cloud dev Environment에서 사용하는 값
repo:100-hours-a-week@167328634/KTB4-8th-CLOUD@1344688950:environment:dev
```

직접 수정한 AWS 정책과 Terraform 원본이 달랐다. 다음 apply가 원본에 정의한 전체 신뢰 정책을 다시 적용하면서 CLI 변경이 유지되지 않았다.

## ✅ 해결 방법

1. 변경 주체를 확인한 이후 원인을 해결할 때까지 IAM을 반복해서 덮어쓰지 않았다.
2. 담당자가 Terraform의 Cloud subject를 정확한 Environment 형식으로 수정했다. 기존 앱 subject와 audience `sts.amazonaws.com`은 유지했다.
3. Terraform `cicd.tf`에 이미 존재하던 `cloud-v2-dev-cd` 보조 inline policy의 관리/import를 반영했다. 기존 `deploy` 정책도 유지했다.
4. ECS 서비스에 `ignore_changes = [task_definition, desired_count]`를 반영해 CD·Auto Scaling이 변경하는 속성과 Terraform의 관리 범위를 맞췄다.
5. Cloud Environment `dev`는 Cloud `main` branch만 허용하도록 설정했다. Environment subject에 branch가 포함되지 않으므로 별도의 branch 제한을 유지한다.
6. 사용자로부터 반영 완료를 전달받은 후 Terraform 원본과 실제 AWS 정책을 다시 읽고 GitHub 실행으로 검증했다.

원본은 이후 Cloud main의 [infrastructure/terraform-v2](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/tree/3368ee552ed0537f6578c0fb38bc69a314fb6636/infrastructure/terraform-v2)에 공유됐다. 최초 조회 시점에는 해당 파일·브랜치가 없었으며, 원본이 처음부터 없었다는 설명을 현재 상태에 적용하면 안 된다.

검증 근거:

- [Terraform 반영 후 OIDC·이미지 조회 dry-run 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38577506120)
- [GitHub 배포 Role의 읽기 전용 사전 검사 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38579680494)
- [AI 실제 ECS 배포 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38579911433)

정책 변경자를 다시 확인할 때 사용할 읽기 전용 명령:

```bash
aws iam get-role --role-name keepgo-v2-github-deploy \
  --query 'Role.AssumeRolePolicyDocument'
aws cloudtrail lookup-events --region us-east-1 \
  --lookup-attributes AttributeKey=EventName,AttributeValue=UpdateAssumeRolePolicy
```

CloudTrail에서는 requestParameters.roleName을 대상 Role로 필터링해 eventTime, userIdentity, userAgent, policyDocument를 비교한다. 전체 감사 로그나 인증 정보를 그대로 공유하지 않는다.

## 회고

CLI 복구는 Terraform 원본 반영까지 끝나야 유지된다. 같은 설정이 다시 바뀌면 먼저 감사 로그로 실제 변경 주체와 요청 내용을 확인해야 한다. 이번에는 첫 복구 후 원본 동기화가 끝나지 않은 상태에서 다음 검증을 진행해 반복 확인이 발생했다.

또한 IAM의 실행 권한 정책과 Role 신뢰 정책을 구분해야 한다. ECS 권한이 충분해도 호출자의 subject가 신뢰 조건과 다르면 Role을 사용할 수 없다. Terraform apply의 성공만으로 OIDC 연동이 검증되는 것도 아니므로 실제 workflow 인증까지 확인했다.
