# 개인 운영자 AWS 권한 설정

작성일: 2026-09-28. 공동 관리 계정 602601433533에서 현재 구성 조회와 중앙 CD·알람 구축을 담당할 사람의 권한 안내다. 사용자 생성이나 권한 부여는 아직 수행하지 않았다.

## 1. 용도별 권한

| 용도 | 권한 | 사용 범위 |
| --- | --- | --- |
| 현재 설정 조회만 | ReadOnlyAccess + AWSCloudShellFullAccess | EC2/ECR/SSM/IAM/알람 정보 조회와 CloudShell 사용. SSM으로 서버 명령을 실행하는 권한까지 주는 것은 아님 |
| 초기 구축을 직접 관리 | AdministratorAccess | IAM/OIDC 역할·정책, SSM, CloudWatch, SNS, EventBridge, CloudFormation 등 설정. 계정 전체 리소스 변경/삭제도 가능 |
| GitHub 자동 CD | 작업별 OIDC 역할 | 운영자가 쓰는 관리자 권한을 CI에 전달하지 않음. 대상 EC2 배포 등 필요한 작업만 허용 |
| EC2 실행 환경 | 기존 instance role에 필요한 정책 | ECR pull, SSM 연결, 로그/지표 전송, 필요한 Secret 조회 |

현재 첫 단계인 환경 조회만 수행한다면 관리자 권한은 필요하지 않다. 이후 IAM 역할과 알람까지 직접 구축할 담당자라면 초기 작업 기간에 관리자 권한을 사용하는 선택은 가능하다. 구축 완료 후 실제 운영에 필요한 권한으로 줄인다.

AdministratorAccess는 Action/Resource에 전체 허용을 주는 AWS 관리형 정책이다. 별도 EC2FullAccess·IAMFullAccess·CloudShellFullAccess를 중복으로 붙일 필요는 없다. 단, 조직 SCP, 권한 경계, 명시적 거부 등은 여전히 적용되고 루트 전용 작업을 대신하지는 않는다.

## 2. 개인 IAM 사용자를 만드는 경우

1. 공동 계정 관리자의 권한으로 개인별 IAM 사용자를 만든다. 예: keepgo-본인이름.
2. 콘솔 로그인이 필요하면 콘솔 접근을 켠다.
3. 초기 구축용 관리자 그룹에 AdministratorAccess를 연결하고 본인 사용자를 그룹에 넣는다. 기존 운영자 그룹이 있으면 새 그룹 대신 그 그룹의 정책을 확인한다.
4. 본인 MFA를 등록하고 개인 사용자로 로그인한다. 여러 사람이 하나의 사용자/암호를 공유하지 않는다.
5. 지금은 access key를 새로 만들지 않아도 된다. 콘솔 CloudShell로 필요한 조회부터 진행할 수 있다.

팀에서 IAM Identity Center/SSO를 이미 사용한다면 그 경로로 개인에게 관리자 역할/권한 세트를 부여하는 방식을 우선한다. AWS는 사람의 접근에 임시 자격 증명과 MFA를 권장한다.

이 PC에는 AWS CLI가 설치되어 있지만 2026-09-28 확인 당시 인증 프로필이 없었고 get-caller-identity가 NoCredentials로 실패했다. 콘솔에 로그인하는 것만으로 이 PC의 CLI가 자동 인증되지는 않는다. 로컬 실행이 필요해지면 SSO 등 팀의 로그인 방식에 맞춰 별도로 연결한다. 키/비밀번호를 채팅이나 저장소에 넣지 않는다.

## 3. 계정 생성 후 바로 할 일

새 사용자로 콘솔에 로그인하고 서울 리전의 CloudShell에서 아래 읽기 명령을 실행한다.

```sh
# 현재 로그인한 계정과 사용자/역할을 확인한다.
aws sts get-caller-identity --region ap-northeast-2
```

Account가 602601433533인지 먼저 확인한다. 다음 작업은 기존 EC2 인스턴스, SSM 연결 여부, instance role과 알람을 조회하는 것이다. 관리자 권한이 생겼다고 현재 컨테이너를 중지하거나 보류 중인 S3 template을 적용하지 않는다.

## 공식 근거

- [AdministratorAccess 정책](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AdministratorAccess.html)
- [AWS IAM 권한·임시 인증·MFA 권장 사항](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [CloudShell의 IAM 접근](https://docs.aws.amazon.com/cloudshell/latest/userguide/security-iam.html)
- [AWSCloudShellFullAccess 정책](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSCloudShellFullAccess.html)
