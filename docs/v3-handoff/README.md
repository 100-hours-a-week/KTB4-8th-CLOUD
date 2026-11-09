# V3 인수인계

V3(EKS 전환) 개발 문서와 인수인계 사항을 모은다. 새 세션이나 새 담당자가 이 폴더만 읽고 이어서 작업할 수 있게 한다.

## 넣는 것

- 인수인계 문서: 지금까지 결정한 것, 진행 상태, 다음 할 일
- 설계 결정의 근거와 바뀐 이력(V1·V2와 다른 점 포함)
- 담당 범위와 의존 관계(A: Terraform·EKS·네트워크·노드·스토리지, B: Helm·RBAC·Argo CD·HPA/KEDA·관측성)

진행 상태는 **설계 완료 / 구현 완료 / 검증 완료**를 나눠 적는다. 확인하지 않은 것을 완료로 적지 않는다.

## 문서 목록

| 날짜 | 문서 | 내용 |
| --- | --- | --- |
| 2026-11-09 | [Claude 인수인계](2026-11-09-claude-handoff.md) | V3 EKS 전환 B 담당 범위, 결정 사항, 진행 상태, 다음 할 일(RBAC·공통 Helm Chart) |
| 2026-11-09 | [A파트 구축 기록](partA.md) | A 담당(Terraform·EKS·노드·Karpenter·LBC·Gateway·NetworkPolicy) 실제 구축 내용 |
| 2026-11-10 | [B파트 구현 기록](2026-11-10-partB-k8s-implementation.md) | B 담당 WBS 21개 구현 결과, 가정 20개·결정 17개(트레이드오프), kind 검증 결과, 전환 Runbook. 인수인계 §7의 "Chart 미구현"·"DBMS 확인 필요"는 여기서 갱신 |
| 2026-11-10 | [B파트 사용자 할 일](2026-11-10-partB-user-todo.md) | 사람이 해야 하는 일: A와 맞출 값, IAM·Secret, 개발팀 요청, gitops 저장소 이동, dev EKS 적용·검증, prod 전환 |

## 설계 사본(위키 스냅샷)

V3 설계의 원본은 [Cloud 위키](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki)다. 레포에서 바로 읽을 수 있게 `design-snapshot/`에 사본을 둔다.

- 기준: 위키 커밋 `addfeea`(2026-11-04), 복사 2026-11-09
- **수정은 위키에서 한다.** 위키가 바뀌면 사본을 다시 복사하고 위 기준을 고친다. 사본을 직접 고치지 않는다.
- 각 파일 첫 줄에 원본 위키 링크가 있다.

| 사본 | 위키 원본 |
| --- | --- |
| [5-0-overview.md](design-snapshot/5-0-overview.md) | 5단계. Kubernetes 기반 운영 플랫폼 설계 |
| [5-1-background-and-platform.md](design-snapshot/5-1-background-and-platform.md) | 5-1. 도입 배경 및 플랫폼 선정 |
| [5-2-service-and-cluster-architecture.md](design-snapshot/5-2-service-and-cluster-architecture.md) | 5-2. 서비스 및 클러스터 아키텍처 |
| [5-3-resource-scaling-security-policy.md](design-snapshot/5-3-resource-scaling-security-policy.md) | 5-3. 리소스·확장·보안 정책 |
| [5-4-deployment-automation-and-migration.md](design-snapshot/5-4-deployment-automation-and-migration.md) | 5-4. 배포 자동화 및 전환 전략 |
| [5-5-observability-incident-cost.md](design-snapshot/5-5-observability-incident-cost.md) | 5-5. 관측·장애 대응 및 운영 비용 |
| [kubernetes-dev-log.md](design-snapshot/kubernetes-dev-log.md) | 쿠버네티스 개발기록 |

다시 복사하는 방법(로컬):

```bash
git clone --depth 1 https://github.com/100-hours-a-week/KTB4-8th-CLOUD.wiki.git /tmp/cloud-wiki
git -C /tmp/cloud-wiki log -1 --format='%h %ci'   # 새 기준 커밋
# 각 파일의 첫 두 줄(원본 링크·기준)은 남기고 본문만 교체한다
```
