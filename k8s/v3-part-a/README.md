# KeepGo V3 — A안 EKS YAML

2026-11-10 기준 A 담당자의 실습 설정과 서비스 NetworkPolicy 초안을 보관합니다.

## 설계 기준

- [KeepGo Cloud Wiki](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki)
- 대상: dev3 EKS / ap-northeast-2 / VPC 10.47.0.0/16 / Service CIDR 10.96.0.0/16
- A 설정의 보관·리뷰용 디렉터리이며 B의 gitops 자동 동기화 대상에 포함하지 않습니다.

## 구성

| 경로 | 내용 | 구분 |
|---|---|---|
| karpenter/ | Helm values, Application/Worker EC2NodeClass·NodePool | 실습 작성 설정. 실제 클러스터와 대조 필요 |
| aws-load-balancer-controller/ | LBC values, IAM 정책·출처, GatewayClass·Namespace·ALB 설정·Gateway | dev3 실습 설정 |
| aws-load-balancer-controller/crds/ | Gateway API v1.6.0 및 LBC v3.6.2 공식 CRD·출처 해시 | 버전 고정 원본 |
| network-policy/service-drafts/ | 수신 격리, AI·ALB·내부 호출·DNS·DB·Redis·AWS 접근 정책 및 문서 | 서비스 배포 전 조율할 초안 |
| network-policy/test-*.yaml | 정책 기능 확인용 임시 테스트 리소스 | 검증 보조 파일 |
| tests/ | Karpenter Application/Worker 배치 확인용 Pod | 검증 보조 파일 |

## 사용 기준

각 values.yaml은 해당 Helm 차트의 입력값이며 kubectl apply 대상이 아닙니다. CRD 원본·Namespace별 정책·설치 values·테스트 파일이 함께 있으므로 전체 디렉터리를 재귀적으로 적용하지 않습니다. 필요한 구성요소를 선택하고 의존 순서를 확인한 뒤 사용합니다.

NetworkPolicy의 서비스 식별 기준은 app.kubernetes.io/name 라벨이며 HTTP 포트 이름은 http입니다. RDS는 Data 서브넷과 TCP 3306 사용을 가정했습니다. Redis Namespace·라벨·포트와 SQS/Kafka 방향은 실제 구성과 맞춰야 합니다. 자세한 내용은 network-policy/service-drafts/의 내부 통신·송신 정책 문서를 참고합니다.

B 담당자의 차트와 NetworkPolicy를 통합할 때 최종 관리 경로를 하나로 정합니다. 같은 Pod를 선택하는 정책의 허용 규칙은 합쳐지므로 중복 적용으로 접근 범위가 넓어지지 않도록 대조합니다.

## 관련 B 브랜치

- feat/v3-helm-app-chart: gitops 차트·서비스 values·플랫폼·Argo CD
- feat/v3-k8s-local: kind 및 로컬 검증 도구
- feat/v1-central-cd-prep: 구현 기록·인수인계 문서

B 구현은 main 반영 전 검토 중이며 CD 구성도 변경될 수 있습니다. 이 스냅샷은 B 변경사항을 병합하거나 덮어쓰지 않습니다.

비밀값·AWS 자격 증명·Terraform state·로컬 백업 파일은 포함하지 않습니다. 리소스 ID와 IAM ARN은 설정 재현을 위해 유지했습니다. 공식 CRD·IAM 정책의 출처 기록은 다운로드 시점 메타데이터이며 현재 AWS 상태를 나타내지 않습니다.
