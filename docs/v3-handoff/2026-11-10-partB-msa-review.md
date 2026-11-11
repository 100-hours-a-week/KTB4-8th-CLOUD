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

## 5. 결정 사항 (2026-11-10, dice·rowan)

dice = A파트, rowan = B파트. 이 절은 위 검토와 별개로 실제로 정한 것과 이미 한 일을 적는다. 구현 기록·사용자 할 일의 해당 가정은 아직 고치지 않았다(아래 "바뀌는 가정" 열).

### 5.1 레포

| 결정 | 내용 | 바뀌는 가정 |
|---|---|---|
| GitOps 레포 이름 | `100-hours-a-week/KTB4-8th-CLOUD-GITOPS`(조직 규칙 `KTB4-8th-<이름>`). gitops·k8s-local·문서의 `keepgo-gitops`를 모두 바꿨다(`c2c8892`, `8d73cd1`, `e8d4a41`) | A19 |
| Cloud 레포와 분리 유지 | 이유: 변경 주체·빈도가 다르고(Terraform은 플랫폼팀이 가끔, values는 여러 팀·봇이 수시로), GitHub 권한·브랜치 보호는 레포 단위라 같은 레포에 두면 팀 쓰기 권한·main 보호·봇 예외가 인프라 코드까지 걸린다. Cloud main은 V2 auto-release가 자동 병합하므로 GitOps 수준의 보호를 걸 수 없다. "CI가 클러스터 권한을 갖지 않는다"는 GitOps 원칙이지 분리 이유가 아니다(5-4 §3.1·§11 정정 제안) | — |
| 레포 공개 여부·권한(확인) | Cloud·BE·AI·FE 모두 public, rowan은 4개 레포 Admin. GitOps 레포도 public으로 만들면 Argo CD 읽기 자격 증명이 필요 없다(§2.2) | §1 |
| gitops 원본 | **GitOps 레포가 원본**. Cloud `feat/v3-helm-app-chart`의 `gitops/`는 11-10 split(`7ada382`) 이후 동결한다. 다시 split해서 push하지 않는다(GitOps 레포가 앞서 있어 거부되고, 강제 push하면 다른 사람 작업이 지워진다). 변경은 GitOps 레포 clone → 브랜치 → PR | — |

### 5.2 클러스터 구성요소 담당

기준: 쿠버네티스 기본 API를 채우고 EKS 버전과 함께 올리는 것, AWS 리소스와 한 묶음인 것 = dice. 그 위에서 팀들이 쓰는 플랫폼 서비스 = rowan(Argo CD platform 앱).

| 구성요소 | 담당·방식 | 상태 | 이유·감수 | 바뀌는 가정 |
|---|---|---|---|---|
| Prometheus Operator CRD | dice | **설치됨**(kubectl 적용, operator 0.95.1, PodMonitor·PrometheusRule·AlertmanagerConfig 포함) | 관측 스택을 Argo CD로 넘길 때 같은 버전의 CRD 앱(ServerSideApply)으로 이어받는다. helm 릴리스가 아니라 `helm uninstall` 위험은 없다 | — |
| 관측 스택(Prometheus·Alertmanager·Grafana·로그·트레이싱) | Argo CD platform 앱(GitOps 레포) | **구현됨**(11-10~11-11, dice가 GitOps 레포 PR #3~#21로 구현): kube-prometheus-stack 93.1.1(Prometheus PVC 20Gi `keepgo-monitoring-gp3`, application 노드), CloudWatch 데이터 소스와 ALB·RDS·SQS 대시보드, Fluent Bit→CloudWatch Logs, OTel Collector→X-Ray(Spring에 OTel Java agent), Grafana `dev3.keepgo.kr/grafana`(GitHub 로그인), Discord 알림 | 11-10에는 "rowan, 비용 때문에 보류"로 정했으나 dice가 Argo CD platform 앱으로 바로 구현했다(관리 방식은 합의와 같음). 차트의 PodMonitor·PrometheusRule·대시보드가 그대로 연결됐다(11-11 확인). 담당이 바뀌었으니 관측 스택 변경은 dice와 함께 본다 | A10(설치 주체=A는 결과적으로 맞음), A17, 사용자 할 일 §1 #11·#12a 해결 |
| metrics-server | **dice, EKS 애드온** | **설치됨**(System 노드 2개, `kubectl top` 동작) | CoreDNS처럼 기본 API(`metrics.k8s.io`)를 채우고 EKS 버전과 함께 올린다. 버전 호환을 AWS가 맞추고, 업그레이드 담당자가 하나이며, Argo CD보다 먼저 있어 첫 sync부터 HPA가 동작한다. 감수: Git 이력·selfHeal 없음(설정을 바꿀 일이 거의 없음). 기본 애드온 전체를 IaC로 옮길 때 같이 옮긴다 | 사용자 할 일 §1에 계약 한 줄 추가 필요 |
| EBS CSI 드라이버 | dice | 11-10 확인 때는 없었으나 이후 Prometheus PVC(`keepgo-monitoring-gp3`)가 Bound됨 → 사용 가능 | Redis 등 다른 PVC도 이 StorageClass 기준으로 | — |
| KEDA·ESO | rowan, Argo CD platform 앱 | 기존 계획 그대로 | — | A17 유지 |

### 5.3 dice 설정과 맞춘 것

| 항목 | 결정·조치 | 상태 |
|---|---|---|
| rowan 클러스터 접근 | `user/ktb8-rowan` Access Entry, 그룹 `keepgo:platform-operators` + 임시 `AmazonEKSClusterAdminPolicy`(cluster) | **완료**(dice). Argo CD platform-rbac이 Synced되면 정책을 뗀다 |
| ALB idle timeout | `keepgo-dev3-alb-config`에 `idle_timeout.timeout_seconds: 200`(SSE 서버 타임아웃 180초보다 길게) | **적용 완료**(rowan, ALB 속성 200 확인). dice 브랜치 `EKS/keepgo-v3-part-a-yaml`에 커밋 `20a1c0c`, push 전 |
| NetworkPolicy 수신 규칙 | 차트(tenancy 기본 차단 + 서비스별 허용)로 통일하고 dice 초안(`default-deny-ingress`·`ai-ingress`·`allow-alb`·`allow-wishlist`)은 클러스터에 직접 적용하지 않는다. dice 초안의 ALB 허용은 Spring 헬스체크 포트 8081이 빠져 있다 | 제안(dice README의 "관리 경로 하나로"와 같은 방향) |
| NetworkPolicy 송신 제한 | dice 송신 허용표를 서비스 values `networkPolicy.egress`로 옮겨 dev가 뜬 뒤 한 PR로 켠다 | 제안 |
| 그대로 맞은 것 | Gateway(`gateway-system/keepgo-dev3-gateway`, 리스너 `https`, `dev3.keepgo.kr`), 허용 Namespace(ai 제외), ALB 서브넷 CIDR, 노드 라벨·worker Taint(A2), TargetGroupConfiguration `v1`, 라벨 `app.kubernetes.io/name`·포트 이름 `http` | 확인 |
| 둘이 정할 것 | Redis Namespace(`data` + `keepgo.kr/network-zone: data` 제안), web→member-api 직접 호출(FE 확인), worker·recommend→wishlist 호출(코드에 없음, 생기면 추가), worker 노드 통합과 `do-not-disrupt`(D20) | 미정 |
| dev RDS | `keepgo-dev3-mysql`(db.t4g.small, MySQL 8.4, DB `keepgo`). `spring-dev.yaml` DB_HOST 반영, 커넥션 한도 170 | **완료**. 스키마는 §5.6 |

### 5.4 dev 자동 CD (2026-11-11)

| 결정 | 내용 | 상태 |
|---|---|---|
| 방식 | **V2 auto-release를 그대로 이관**(§2.1의 Image Updater 추천에서 바뀜). 앱 레포 CI는 그대로 두고, GitOps 레포가 앱 레포 `develop` head의 CI 게시 job 성공 + ECR SHA 태그를 확인해 values-dev 태그 PR을 `GITHUB_TOKEN`으로 바로 병합한다. 반영은 Argo CD | GitOps PR #22(`release/dev.json`, `scripts/release.py`, `auto-release-dev.yaml`), 로컬 미리 보기 통과 |
| 트리거 | GitOps 레포에서 `on.schedule`이 돌지 않아 V2처럼 EventBridge(ECR push + 10분 주기)가 `workflow_dispatch` API를 부른다. 토큰은 GITOPS 레포 하나·Actions RW만 가진 fine-grained PAT | Cloud PR #256(`infrastructure/v3-gitops-dispatch.yaml`), 스택 배포는 rowan |
| ECR 조회 권한 | OIDC 역할 `keepgo-v3-gitops-release`(GITOPS main만, `ecr:DescribeImages` 3개 저장소) | 생성 완료, GITOPS 변수 `RELEASE_ROLE_ARN` 설정 |
| 제거 | GitHub App 전제의 `build-and-bump.yaml`·`docs/ci-callers/` | PR #22에 포함 |
| 감수 | PAT가 rowan 계정에 묶인다(만료·퇴장 시 자동 반영이 멈춤 → 실패 알람에 SNS 토픽 연결 권장). 같은 develop 이미지를 V2 dev와 함께 쓴다(web의 빌드 시점 값 `NEXT_PUBLIC_*`가 V2 dev 기준이면 dev3에서 다르게 동작할 수 있어 첫 반영 때 확인) | — |
| 가동(11-11) | EventBridge 스택 `keepgo-v3-gitops-dispatch` 배포(Connection AUTHORIZED, 10분 rule 호출 성공·실패 0), `AUTO_DEPLOY_ENABLED=true`. 첫 실행이 backend `ce18544`·ai `e355d38`·frontend `4a399d4`를 GitOps PR #24~#26으로 자동 병합 → Argo CD 반영. ai·web은 새 이미지로 정상, Spring은 §5.5·§5.6 문제로 새 Pod가 기동 실패(기존 Pod가 `maxUnavailable: 0`이라 서비스는 계속됨) | 동작 확인 |


### 5.5 backend Secret 전달 방식 (2026-11-11)

| 결정 | 내용 | 상태 |
|---|---|---|
| 통째로 넣기 | Spring env Secret을 키 하나씩 고르던 방식에서 **backend Secret 통째로**(`dataFrom: extract`, dev `keepgo/dev3/backend`, prod `Secret-v1-BE`)로 바꿨다. V2 ECS와 같은 방식이다. DB 계정만 RDS 관리 Secret에서 골라 넣는다(키 이름 `username`·`password`가 달라서). JWT 파일 마운트는 그대로 | GitOps PR #27 병합 |
| 계기 | 자동 CD로 들어온 develop 코드(`KakaoPlaceSearch`)가 기동 때 `KAKAO_REST_API_KEY`를 필수로 요구했다. 값은 Secret에 있었지만 고르는 목록에 없어 새 Pod가 CrashLoop. 키를 고르는 방식은 개발팀이 키를 추가할 때마다 values를 고쳐야 한다 | 해결(Secret에 키 9개 확인) |
| 감수 | Spring 7개가 backend Secret의 모든 키를 받는다(같은 이미지라 지금도 거의 같음). 새 키는 ESO 갱신 주기(1h) 뒤에 들어간다. prod `Secret-v1-BE`에도 `DB_*` 키가 있는데, ESO는 `data`를 `dataFrom` 다음에 적용하므로 RDS Secret 값이 우선한다고 보고 있다(prod 전환 때 확인). prod `Secret-v1-BE`에는 `GOOGLE_LOGIN_CLIENT_ID`가 없어 prod 전환 전에 키를 추가해야 한다 | — |

### 5.6 DB 스키마 마이그레이션 (미정, 2026-11-11)

| 항목 | 내용 |
|---|---|
| 증상 | Kakao 키 해결 뒤에도 Spring 새 Pod가 `Table 'keepgo.ai_call_slot' doesn't exist`로 기동 실패 |
| 원인 | backend는 Flyway를 기본으로 꺼 두고(`spring.flyway.enabled: false`), 스키마 변경은 `migration` 프로필로 따로 적용한다(BE `docs/database-migrations.md`). 마이그레이션은 V1~V7이 있고 `V6__ai_call_slot.sql`이 이 테이블을 만든다. dev3 DB에는 V6가 적용되지 않았다. 이전 이미지(`503a236`)는 이 테이블을 쓰지 않아 문제가 없었다 |
| 정할 것 | (1) 누가 dev3 DB에 마이그레이션을 적용하나(DB는 dice, 앱 스키마는 개발팀) (2) 방식: 차트의 `migration` PreSync Job(같은 이미지, `SPRING_PROFILES_ACTIVE=migration`, 5-4 8.3)으로 자동화할지, 사람이 한 번 적용할지 (3) dev3 DB의 현재 상태(초기 스키마를 어떻게 만들었는지, `flyway_schema_history`가 있는지). BE 문서상 기존 DB에는 자동 baseline을 하지 않으므로 상태에 따라 baseline 또는 DB 재생성이 필요 |
| 영향 | 그동안 Spring 7개는 이전 이미지 Pod 1개씩으로 서비스되고, 자동 CD가 올린 새 버전은 뜨지 않는다 |