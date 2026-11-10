# V3 B파트 — MSA 규모 기준 변경 검토 (2026-11-10)

- 대상: [구현 기록](2026-11-10-partB-k8s-implementation.md), [사용자 할 일](2026-11-10-partB-user-todo.md)
- 기준: V3는 쿠버네티스 MSA를 택했으므로, 나머지 인프라도 "2인 운영·레포 3개"가 아니라 **서비스·레포·팀이 여럿인 규모**를 전제로 고른다.
- 상태: **검토만 했다.** 코드(`feat/v3-helm-app-chart`, `feat/v3-k8s-local`)와 기존 문서는 아직 바꾸지 않았다. 항목별로 정해지면 구현하고, 구현 기록의 해당 결정(D 번호)을 고친다.

## 1. 새로 확인된 제약: GitHub 조직 권한

조직 `100-hours-a-week`는 우리 소유가 아니다. 확인된 권한은 **레포 생성, PAT 발급**뿐이다.

지금 설계가 전제한 것 중 조직 권한이 필요한 것

| 지금 설계 | 필요한 권한 | 확인 |
|---|---|---|
| GitHub App을 KTB4-8th-CLOUD-GITOPS에 설치(CI 태그 커밋, Argo CD 레포 읽기) | 조직 Owner 승인 | 미확인 |
| GitHub 팀 `keepgo-cloud`·`keepgo-fullstack`·`keepgo-ai`(CODEOWNERS, AppProject role, Argo CD RBAC) | 팀 생성 권한 | 미확인 |
| Argo CD GitHub 로그인(Dex `orgs`)이 조직·팀 소속을 읽음 | 조직이 OAuth App을 제한하면 Owner 승인 | 미확인 |
| 조직 Secret(키 한 곳 보관) | 조직 Owner | 없음으로 가정 |
| 앱 레포(KTB4-8th-BE·AI·FE)에 Secret·workflow 추가 | 해당 레포 Admin(개발팀 레포) | 미확인 |
| 레포 안 설정: 브랜치 보호, Deploy key, 레포 Secret | KTB4-8th-CLOUD-GITOPS를 우리가 만들면 우리가 Admin | 가능(레포 생성 가능) |

확인할 것

- [ ] GitHub App 설치를 Owner에게 요청할 수 있는지, 걸리는 시간
- [ ] 조직 안에 팀을 만들 수 있는지(Settings → Member privileges → Team creation)
- [ ] OAuth App 접근 제한이 켜져 있는지(켜져 있으면 Dex가 조직·팀을 못 읽음)
- [ ] fine-grained PAT 승인 정책(조직이 승인을 요구하는지)
- [ ] 앱 레포 3개에 Secret·workflow를 누가 넣는지(개발팀 Admin)

## 2. 검토 항목

각 항목: 지금 → 문제(MSA 규모에서) → 추천 → 조직 권한 → 바꿀 곳

### 2.1 CI가 GitOps 레포에 쓰는 방법 (구현 기록 5-4 4.4, 사용자 할 일 §3)
- 지금: 앱 레포의 CI가 GitHub App 토큰으로 KTB4-8th-CLOUD-GITOPS main에 dev 태그를 직접 push. App 키는 앱 레포마다 Secret으로 복사.
- 문제: 레포가 늘수록 키 사본이 늘고(교체 시 N곳 갱신), App 설치에 Owner 승인이 필요하다.
- 추천 **(b) 끌어오는 방식**
  - CI는 ECR에 이미지만 올린다(클러스터·GitOps 권한 모두 없음).
  - dev: Argo CD Image Updater가 ECR 새 태그를 보고 KTB4-8th-CLOUD-GITOPS에 커밋(write-back). 쓰기는 KTB4-8th-CLOUD-GITOPS의 **쓰기용 Deploy key** 하나.
  - prod: KTB4-8th-CLOUD-GITOPS 안의 `promote-prod`가 기본 `GITHUB_TOKEN`으로 PR을 만든다(같은 레포라 App 불필요).
  - 레포끼리 주고받는 자격 증명이 없어, 레포가 늘어도 키를 나눠 줄 일이 없다. 조직 권한 없이 KTB4-8th-CLOUD-GITOPS Admin만으로 된다.
- 대안
  - (a) GitHub App 유지: Owner가 설치해 주면. 키는 레포별 Secret.
  - PAT: 발급은 되지만 사람 계정에 묶인다(그 사람이 빠지면 끊김, 오래 사는 토큰). 임시로만.
- 감수: Image Updater라는 컴포넌트가 하나 늘고(System 노드), 태그 선택 규칙(예: 커밋 SHA 태그 중 최신 push)을 따로 정해야 한다. "어떤 커밋이 dev에 올라갔나"는 Image Updater 커밋으로 남는다.
- 바꿀 곳: `.github/workflows/build-and-bump.yaml`(bump-dev 제거), `docs/ci-callers/*`, `argocd/platform/<env>/`(Image Updater 추가), ApplicationSet dev 템플릿(Image Updater 주석), `promote-prod.yaml`(App 토큰 → `GITHUB_TOKEN`)

### 2.2 Argo CD의 KTB4-8th-CLOUD-GITOPS 읽기 자격 증명 (사용자 할 일 §4.1)
- 지금: `argocd repo add --github-app-*`(GitHub App).
- 추천: 읽기 전용 **Deploy key**(`argocd repo add git@github.com:100-hours-a-week/KTB4-8th-CLOUD-GITOPS.git --ssh-private-key-path <키>`). 조직 권한이 필요 없다.
- 감수: 레포 주소가 SSH로 바뀐다 → AppProject `sourceRepos`, ApplicationSet·root·platform Application의 `repoURL`을 같이 바꾼다.

### 2.3 배포 대상 목록 한 곳 (`build-and-bump`·`promote-prod`)
- 지금: "이미지 → 태그를 바꿀 values 파일" 대응이 앱 레포 호출부(`value-files`)와 `promote-prod`의 `case`문 두 곳에 따로 있다.
- 문제: 서비스·레포가 늘면 두 곳이 어긋나기 쉽다.
- 추천: `release/targets.yaml`(target → ECR 저장소, dev·prod values 파일) 하나로 모은다. 호출부는 target 이름만 넘기고, `validate.sh`가 targets와 `promote-prod` 선택지가 같은지, 파일마다 `image.tag`가 있는지 검사한다.
- 조직 권한: 불필요. 2.1이 (b)면 Image Updater 설정이 이 파일을 대신한다.

### 2.4 push 충돌 재시도 (`build-and-bump`)
- 지금: 겹치면 rebase 후 5번, 대기 없이 재시도.
- 추천: 대기 시간을 점점 늘리고 무작위 대기를 섞어 10번. **2.1을 (a)로 유지할 때만** 해당.

### 2.5 Argo CD 처리량과 HA (`argocd/bootstrap/values.yaml`)
- 지금: `controller.status.processors: 10`, `operation.processors: 5`("서비스 9개 규모에 맞춘 작은 값"). 모든 컴포넌트 1개.
- 추천: 처리 수는 Argo CD 기본값(20/10)으로. prod는 HA(server·repo-server 2개, redis-ha)를 검토.
- 조건: redis-ha는 노드 3대에 나눠 뜬다. partA의 System 노드는 t3.medium 2대 → A와 System 노드 수·사양을 같이 정한다.

### 2.6 Argo CD 자기 관리 (구현 기록 D14)
- 지금: helm으로 사람이 설치·변경. 이유가 "2인 운영 초기에는 하지 않는다".
- 문제: 클러스터가 늘면(dev, prod, 이후 추가) 손으로 맞추는 설치가 클러스터마다 어긋난다.
- 추천: 첫 설치만 helm, 이후는 platform 프로젝트의 Argo CD Application이 같은 values로 관리(Argo CD 공식 "Manage Argo CD Using Argo CD"). 고장 나면 같은 values로 `helm upgrade`해 복구하는 경로를 Runbook에 남긴다.
- 감수: 잘못된 values가 Argo CD 자신을 망가뜨릴 수 있다 → prune 끔, dev에서 먼저 적용, `argocd-platform-deployer`(extraObjects)는 Argo CD가 지우지 못하게 `Prune=false` 주석.

### 2.7 알림 받는 곳 (구현 기록 D18, Argo CD Notifications)
- 지금: Alertmanager·Argo CD 알림 모두 Discord 채널 하나.
- 문제: 팀이 여럿이면 남의 알림이 섞여 놓치기 쉽다.
- 추천: `keepgo.io/team`(Namespace) 라벨로 라우팅. AlertmanagerConfig는 route를 팀별로, Argo CD는 ApplicationSet 템플릿에서 팀별 구독 주석. webhook Secret은 팀별 키(`url-<team>`), 없으면 공용 채널로.
- 조직 권한: 불필요(Discord).

### 2.8 Secret 변경을 Pod에 반영 (구현 기록 D21)
- 지금: 비밀을 바꾼 뒤 사람이 `podAnnotations.secret-rev` PR로 재시작. "비밀 교체가 잦아지면 다시 본다".
- 문제: 같은 비밀이 서비스 수만큼 복사되어(D8) 서비스가 늘면 PR도 서비스 수만큼 늘어난다.
- 추천: Reloader(Secret 변경 감지 → 롤링 재시작). 차트가 Deployment에 Reloader 주석을 기본으로 단다. 추적은 ESO 이벤트·Reloader 로그로.
- 감수: 컨트롤러가 하나 는다. Git 이력에 재시작이 남지 않는다(backlog "Secret 변경 추적"은 ESO 이벤트로 대신).

### 2.9 새 Namespace를 추가할 때 고치는 곳 (`argocd/applicationsets/*`, `scripts/validate.sh`)
- 지금: Spring/standalone 구분 때문에 ApplicationSet 2개와 `validate.sh`의 `SPRING_NAMESPACES`에 Namespace 이름을 직접 나열.
- 문제: 팀이 늘면 tenancy·project 외에 3곳을 더 고쳐야 하고, 빠뜨리면 조용히 배포되지 않는다.
- 추천: 서비스 폴더마다 `app.yaml`(`stack: spring|standalone`)을 두고 ApplicationSet은 git **files** generator(`apps/*/*/app.yaml`)로 읽는다. `validate.sh`도 같은 파일을 읽는다.
- 감수: kind에서 ApplicationSet을 다시 검증해야 한다.

### 2.10 팀 단위 승인·권한 (CODEOWNERS, AppProject role, Argo CD RBAC)
- 지금: GitHub 팀 3개를 가정(A19).
- 추천: 팀을 만들 수 있으면 그대로. 못 만들면
  - CODEOWNERS: 개인 계정(`@<사용자>`)으로 적는다.
  - Argo CD: Dex `orgs` 제한을 빼고 GitHub 사용자 단위로 RBAC(`g, <GitHub 사용자>, proj:<ns>:team`). 로그인 허용도 사용자 목록으로.
- 감수: 사람이 바뀔 때마다 두 곳을 고친다.

## 3. 바꾸지 않는 것

| 항목 | 이유 |
|---|---|
| GitOps 레포 분리(5-4 §3.1) | 규모가 커질수록 더 맞는 선택 |
| sync impersonation(D6), tenancy 차트(D3), Namespace별 ESO 역할(D4) | 팀·Namespace가 늘어도 그대로 늘어난다 |
| prod 승격은 PR + CODEOWNERS 승인 | 규모와 무관하게 유지 |
| Spring 7개 같은 이미지·태그 한 곳(D7) | 규모가 아니라 개발팀 코드가 안 나뉜 사실 때문. 나뉘면 서비스별 태그로 |
| dev 야간 축소 보류(D19), Worker 측정 후(D20) | 규모가 아니라 측정 전이라서 |
| Kargo(승격 전용 도구) | 승격 단계가 dev→prod 둘뿐. stage가 생기면 다시 본다 |

## 4. 정할 순서

1. §1 조직 권한 확인 → 2.1·2.2·2.10의 방향이 정해진다.
2. 조직 권한과 무관한 것(2.3·2.5 처리 수·2.7·2.9)부터 구현할지 결정.
3. 컴포넌트가 늘어나는 것(2.1 Image Updater, 2.6 자기 관리, 2.8 Reloader)은 dev EKS 적용(사용자 할 일 §4) 전에 할지 후에 할지 결정.
