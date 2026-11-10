# KTB4-8th-CLOUD-GITOPS

KeepGo V3(EKS) 배포 설정 저장소. Argo CD가 이 저장소를 기준으로 클러스터를 맞춘다(위키 5-4).
지금은 Cloud 레포의 `gitops/` 폴더이고, `KTB4-8th-CLOUD-GITOPS` 저장소를 만들면 이 폴더를 이력째 옮긴다.

| 폴더 | 내용 | 승인 |
|---|---|---|
| `charts/keepgo-app` | 9개 서비스 공통 차트 | 플랫폼팀 |
| `apps/<namespace>/<서비스>` | 서비스 values(공통·dev·prod). Spring 공통은 `apps/_shared` | 해당 팀(prod는 + 플랫폼팀) |
| `platform/` | ClusterRole, 팀 Namespace(tenancy), PriorityClass, KEDA·ESO 설치 값, 앱 대시보드 | 플랫폼팀 |
| `argocd/` | Argo CD 설치 값, AppProject, ApplicationSet, 플랫폼 Application, root | 플랫폼팀 |
| `scripts/` | 검증(validate.sh), 예산 검사, 태그 변경, 대시보드 생성 | 플랫폼팀 |
| `.github/` | PR 검증, 빌드·dev 태그 커밋(재사용), prod 승격, 차트 태그 | 플랫폼팀 |

## 자주 하는 일

| 하고 싶은 것 | 방법 |
|---|---|
| 서비스 설정 바꾸기 | `apps/<ns>/<서비스>/values*.yaml` 수정 PR → merge되면 Argo CD가 반영 |
| dev 배포 | 앱 저장소 main merge → CI가 `values-dev`(Spring은 `_shared/spring-dev.yaml`) 태그 커밋 |
| prod 배포 | Actions → `promote-prod` 실행(스택·태그) → 생성된 PR 승인·merge |
| 롤백 | 태그 변경 커밋 `git revert` |
| 새 서비스 | `apps/<ns>/<새 서비스>/` 폴더와 values 추가(ApplicationSet이 Application 생성) |
| 새 팀 Namespace | `platform/tenancy/values-<env>.yaml`에 블록 추가 + `argocd/projects/<ns>.yaml` + ApplicationSet 경로 |
| 검증 | `bash scripts/validate.sh`(helm, kubeconform, python3 + PyYAML 필요) |

설계 결정과 가정은 Cloud 레포 `docs/v3-handoff/2026-11-10-partB-k8s-implementation.md`에 있다.
