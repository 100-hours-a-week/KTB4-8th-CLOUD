# Argo CD 구성

클러스터마다 Argo CD를 하나씩 둔다(5-4 6.1). 사람이 하는 일은 **설치 1회 + root 앱 1회**뿐이고, 그 뒤로는 Git만 바꾼다.

## 폴더

| 경로 | 내용 |
|---|---|
| `bootstrap/values.yaml` | Argo CD Helm 설치 값(System 노드, impersonation, GitHub 로그인, Discord 알림, platform 배포 계정) |
| `bootstrap/project.yaml`, `bootstrap/root-<env>.yaml` | root 앱 전용 프로젝트와 app-of-apps 시작점. 아래 세 폴더를 읽는다 |
| `projects/` | AppProject: `platform` + 팀 6개(5-4 6.3) |
| `platform/<env>/` | 플랫폼 Application: rbac → priority-classes → KEDA·ESO → tenancy → monitoring |
| `applicationsets/apps-<env>.yaml` | `apps/<namespace>/<서비스>/` 폴더마다 Application 생성(5-4 6.2) |

## 동기화 순서(sync-wave, 5-4 6.5)

| wave | 대상 |
|---|---|
| -30 | AppProject |
| -20 | ClusterRole·PriorityClass |
| -15 | KEDA·ESO(CRD와 컨트롤러) |
| -10 | 팀 Namespace·Quota·LimitRange·RoleBinding·SecretStore·기본 차단 |
| -5 | 앱 대시보드 |
| 0 | 서비스 ApplicationSet |

root 앱이 다음 wave로 넘어가려면 앞 Application이 Healthy여야 한다. Argo CD는 기본으로 Application의 Health를 계산하지 않으므로 `bootstrap/values.yaml`의 `resource.customizations.health.argoproj.io_Application`으로 켠다.

## 권한 구조(5-2 2.3)

- Argo CD 컨트롤러 자체는 차트 기본 권한(클러스터 전체 조회·쓰기)을 갖는다. 대신 **sync impersonation**(Argo CD 3.5+ beta)을 켜서 실제 적용은 프로젝트가 지정한 계정으로 한다.
  - 팀 프로젝트 → 각 Namespace의 `argocd-deployer`(ClusterRole `keepgo-application-deployer`를 RoleBinding)
  - platform 프로젝트 → `argocd/argocd-platform-deployer`(cluster-admin, 설치 때 함께 생성)
- 팀 프로젝트는 클러스터 범위 리소스·Quota·LimitRange·Role·RoleBinding·Secret을 만들 수 없다.
- 화면 권한: 로그인만으로는 아무것도 못 본다. 팀은 AppProject `team` 역할(GitHub 팀), 클라우드 담당팀은 `role:admin`.

## 설치(클러스터마다 1회)

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm upgrade --install argocd argo/argo-cd --version 10.17.1 \
  -n argocd --create-namespace -f argocd/bootstrap/values.yaml --wait
# 비밀값 2개는 Git에 두지 않는다(사용자 할 일 문서 참고)
#   argocd-dex-github        : clientID, clientSecret (GitHub OAuth App)
#   argocd-notifications-secret: discord-webhook-url
kubectl apply -f argocd/bootstrap/project.yaml -f argocd/bootstrap/root-dev.yaml   # prod는 root-prod.yaml
```

저장소가 private이면 repo 자격 증명(GitHub App)을 먼저 등록한다.

## 롤백(5-4 9.3)

- 기본: GitOps 저장소에서 태그 변경 커밋을 `git revert` → Argo CD가 이전 태그로 동기화
- 긴급: Argo CD UI Rollback은 auto-sync를 끈 상태에서만 동작한다. 쓴 뒤 바로 Git revert하고 auto-sync를 다시 켠다.
- `kubectl rollout undo`·`kubectl edit`는 selfHeal이 Git 상태로 되돌린다.
