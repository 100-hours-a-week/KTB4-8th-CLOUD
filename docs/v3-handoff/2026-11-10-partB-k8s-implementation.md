# V3 B파트 쿠버네티스 구현 기록 (2026-11-10)

- 담당: Cloud B(Helm·RBAC·Argo CD·HPA/KEDA·관측성)
- 근거: `design-snapshot/`(위키 5-0~5-5, 개발기록 `addfeea`), `partA.md`(A 구축 기록), [11-09 인수인계](2026-11-09-claude-handoff.md), 앱 레포(KTB4-8th-BE·AI·FE), V2 Terraform(`infrastructure/terraform-v2`)
- 원칙: 위키에 없는 값은 멈추지 않고 **가정해서 구현**하고, 가정과 그 트레이드오프를 이 문서에 남긴다. 실제 값이 나오면 "바꿀 곳"의 키만 고친다.
- 사람이 직접 해야 할 일은 [사용자 할 일](2026-11-10-partB-user-todo.md)에 따로 정리했다.

## 1. 한눈에 보기

| 구분 | 상태 |
|---|---|
| 설계 | 위키 5-2·5-3·5-4를 그대로 코드로 옮김. 위키에 없는 선택 21건은 §5 결정 기록 |
| 구현 | WBS 21개 중 코드·문서로 할 수 있는 것 전부(§3) |
| 검증 | 정적 검증 전부 통과, kind(Kubernetes 1.37.0)에서 Argo CD 전체 동기화·RBAC·NetworkPolicy 확인(§6) |
| 미검증 | AWS가 있어야 하는 것(ALB·Pod Identity·ExternalSecret·SQS KEDA·Karpenter 배치·부하·장애): dev EKS에서 [사용자 할 일](2026-11-10-partB-user-todo.md) §4 |

인수인계(11-09)는 "Chart 구현 확인 안 됨"이라고 적혀 있었지만, 실제로는 11-04에 `feat/v3-helm-app-chart`에 차트 0.1.0이 있었다. 이번 작업은 그 위에 이어서 했다.

## 2. 브랜치와 파일

| 브랜치 | 내용 | 나중 |
|---|---|---|
| `feat/v3-helm-app-chart` | `gitops/` = KTB4-8th-CLOUD-GITOPS 저장소 루트가 될 내용 전부 | `git subtree split --prefix=gitops`로 이력째 새 저장소로 이동 |
| `feat/v3-k8s-local` | Argo CD가 동기화하지 않는 파일: kind 구성, 로컬 override, 검증·장애·부하 스크립트 | Cloud 레포에 남김 |
| `feat/v1-central-cd-prep` | 이 문서들(`docs/v3-handoff/`) | 기존 문서 브랜치 관례 |

`gitops/` 구조(5-4 3.2를 따름)

```text
gitops/
├── charts/keepgo-app/         공통 앱 차트 0.3.0
├── apps/
│   ├── _shared/spring*.yaml   Spring 7개 공통 값(이미지 태그는 여기 한 곳)
│   └── <namespace>/<서비스>/values.yaml, values-dev.yaml, values-prod.yaml
├── platform/
│   ├── rbac/                  ClusterRole 3개 + 플랫폼팀 바인딩
│   ├── tenancy/               팀 Namespace 6개 묶음 차트(Quota·LimitRange·RoleBinding·SecretStore·기본 차단)
│   ├── priority-classes/
│   ├── keda/, external-secrets/   설치 값(차트 버전은 argocd/platform에서 고정)
│   └── monitoring/            앱 대시보드(생성 스크립트 결과)
├── argocd/
│   ├── bootstrap/             Argo CD 설치 값, root-dev·root-prod
│   ├── projects/              platform + 팀 6개
│   ├── platform/<env>/        플랫폼 Application(sync-wave 순서)
│   └── applicationsets/       apps-dev·apps-prod
├── scripts/                   validate.sh, check-budget.py, set-image-tag.sh, gen-dashboards.py
├── docs/ci-callers/           앱 저장소에 넣을 호출 workflow 예시
└── .github/                   validate, build-and-bump, promote-prod, chart-release, CODEOWNERS
```

## 3. WBS 대응

| WBS | 내용 | 결과물 | 상태 |
|---:|---|---|---|
| 01 | 배포 계약 | §4 계약·가정 표, 사용자 할 일 §1 | 구현 |
| 02 | 저장소 구조 | `gitops/` | 구현 |
| 03·04 | 차트·Deployment·Service·ConfigMap | `charts/keepgo-app` | 구현·kind 검증 |
| 05 | Namespace·RBAC·Quota·LimitRange | `platform/rbac`, `platform/tenancy` | 구현·kind 검증 |
| 06 | ServiceAccount·비밀 | 차트 ExternalSecret, tenancy SecretStore | 구현·정적 검증(AWS 미검증) |
| 07 | Probe·Resources·RollingUpdate·종료 | 차트 기본값 + 서비스 values | 구현·kind 검증(Mock) |
| 08 | kind 배포 | `feat/v3-k8s-local` | 검증 완료 |
| 09 | Argo CD·AppProject·Application | `argocd/` | 구현·kind 검증 |
| 10 | GitHub Actions → GitOps | `.github/workflows/*`, `docs/ci-callers/` | 구현(실행 미검증) |
| 11·12 | dev EKS 배포·HTTPRoute | dev values, HTTPRoute·TargetGroupConfiguration | 구현·정적 검증(EKS 미검증) |
| 13 | Affinity·TopologySpread·PDB | 차트 | 구현·kind 검증(배치) |
| 14 | HPA | 차트 `autoscaling.type: hpa` | 구현·kind 검증(생성) |
| 15 | KEDA SQS | worker values | 구현(SQS 미검증, 앱에 SQS 코드 없음) |
| 16 | KEDA SSE·AI 지표 | chat·recommend·ai values(가정 지표 + CPU) | 구현(지표 계측 대기) |
| 17 | Graceful·SSE 재연결 | 종료 시간·deregistration delay | 구현(앱 쪽은 개발팀) |
| 18 | 지표·대시보드·알림 | PodMonitor·PrometheusRule·Discord 전달(AlertmanagerConfig)·대시보드·Argo CD 알림 | 구현(수집·전송 미검증) |
| 19 | 부하·장애·롤백 | `tests/v3/load/*.js`, `chaos.sh` | 도구만(실행은 사용자) |
| 20 | prod values·전환 | values-prod, 전환 Runbook(§8) | 구현(실행은 사용자) |
| 21 | 문서·Runbook | 이 문서, [Runbook](2026-11-10-partB-runbook.md), 사용자 할 일 | 구현 |

## 4. 계약·가정 표

A·개발팀 확정값이 없어서 정한 값이다. 틀리면 "바꿀 곳"만 고친다.

| # | 가정 | 근거 | 바꿀 곳 |
|---:|---|---|---|
| A1 | 사람 그룹: `keepgo:platform-operators`, `keepgo:fullstack-observers`, `keepgo:ai-observers` | 인수인계 §9 초안 이름에 플랫폼 그룹 추가 | `platform/rbac/platform-operator.yaml`, `platform/tenancy/values-*.yaml` |
| A2 | worker NodePool Taint `workload=worker:NoSchedule` | partA는 "NoSchedule"만 적음. system과 같은 키 규칙 | `apps/ingest/youtube-analysis-worker/values.yaml` tolerations |
| A3 | Secrets Manager 경로 dev `keepgo/dev3/{backend,rds,ai,web}`, prod는 V2 `Secret-v1-BE`·`Secret-v1-AI` + `keepgo/prod/{rds,web}` | prod는 ECS와 JWT·OAuth를 같이 써야 토큰이 통함 | `apps/_shared/spring-<env>.yaml`, ai·web `values-<env>.yaml` |
| A4 | ESO는 Namespace별 역할 `keepgo-<env>-eso-<namespace>`를 assume | §5 D4 | `platform/tenancy/values.yaml` roleArnFormat |
| A5 | KEDA SQS 읽기 역할 `keepgo-<env>-keda-youtube-analysis` | §5 D5 | worker `values-<env>.yaml` |
| A6 | SQS: dev `keepgo-dev3-youtube-analysis`, prod V2 `keepgo-v2-analysis` | V2 worker는 꺼져 있어 소비자가 겹치지 않음 | worker values, `spring-<env>.yaml` |
| A7 | Redis `redis.data.svc.cluster.local:6379`, TLS 없음 | Redis는 A 소유, Namespace 미정 | `apps/_shared/spring-<env>.yaml` |
| A8 | RDS 주소 placeholder, dev RDS = db.t4g.micro(max_connections 약 80) | partA에 dev RDS 없음 | `spring-<env>.yaml` DB_HOST, `scripts/budget.yaml` |
| A9 | prod RDS를 전환 전에 db.t4g.small(약 170)로 올림 | 현재 V2(micro)로는 EKS 최대 확장 + ECS 병행이 안 들어감(§7) | `scripts/budget.yaml` |
| A10 | Prometheus: kube-prometheus-stack, `monitoring` Namespace, `release: kube-prometheus-stack` 라벨, 주소 `kube-prometheus-stack-prometheus.monitoring.svc:9090` | A가 설치(인수인계 §3) | `spring-<env>.yaml` metrics, SSE·AI 트리거 |
| A11 | 개발팀 지표 `keepgo_sse_active_connections`, `keepgo_ai_inflight_requests` | 아직 없음(5-3 5.2도 "계측 가능 여부 먼저 확인") | chat·recommend·ai values |
| A12 | KEDA 목표: SQS 5개/Pod, SSE 200연결/Pod, AI 8요청/Pod | 측정 전 시작값 | 각 values triggers |
| A13 | HPA CPU 70%, 확장 60초·축소 300초 1개씩 | 5-3 5.4 "안정화" 방향 | 차트 `autoscaling` |
| A14 | maxReplicas dev 2, prod 2~4(DB 예산 안) | 5-4 5.1 dev 최소 1 | 서비스 values |
| A15 | Gateway: dev `keepgo-dev3-gateway`(partA), prod `keepgo-prod-gateway` + `keepgo.kr`·`api.keepgo.kr` | prod는 V2 API 도메인 유지 | `spring-prod.yaml`, web `values-prod.yaml` |
| A16 | web 자원 100m/256Mi, HPA | 5-3에 없음 | `apps/frontend/web/values.yaml` |
| A17 | KEDA·ESO·Argo CD 설치 소유권 = B(Argo CD 경유) | 인수인계 §3 미정 계약 | `argocd/platform/<env>/` |
| A18 | 알림: Discord webhook | 5-4는 Slack, V2 운영은 Discord | `argocd/bootstrap/values.yaml` notifications |
| A19 | GitHub 팀 `keepgo-cloud`·`keepgo-fullstack`·`keepgo-ai`, 저장소 `100-hours-a-week/KTB4-8th-CLOUD-GITOPS` | 조직 이름만 확정 | `argocd/`, `.github/CODEOWNERS` |
| A20 | 이미지 태그 초기값 = V2 운영 태그(backend `503a236`, ai `6e9c5cf`), web = FE main `b21465f` | 첫 V3 빌드 전 자리값 | `spring-<env>.yaml`, ai·web values |

### 앱 코드에서 확인한 사실(가정 아님)

| 항목 | 사실 | 반영 |
|---|---|---|
| DB | MySQL(사용자 확인, `mysql-connector-j`, V2 RDS MySQL 8.4) | 인수인계의 "DBMS 확인 필요" 해결 |
| Backend | 단일 Spring 앱, 8080 + 관리 8081, UID 10001, probes 그룹·graceful 설정 없음 | 차트가 env로 `MANAGEMENT_ENDPOINT_HEALTH_PROBES_ENABLED`, `SERVER_SHUTDOWN` 지정 |
| API 경로 | auth `/oauth2`·`/login/oauth2`·`/api/v1/user/auth-session`, member `/api/v1/user`·`/public`, youtube `/api/v2/member/youtube-sync`·`external-connections`, wishlist `/api/v2/member/outing-wishlist`, chat·recommend v1·v2(v2는 SSE 180초) | 서비스별 HTTPRoute. 나머지 `/api`는 member-api, 나머지 `/`는 web |
| AI | 8000, UID 10002, `/health` 하나뿐, 지표 없음, 내장 Chroma(`/app/chroma`) | probe 경로 `/health`, emptyDir, 지표 끔 |
| Web | Next.js standalone 3000, `USER node`, 헬스 경로 없음 | nextjs 프리셋(`/`) |

## 5. 결정 기록(위키에 없는 선택)

각 항목: 문제 → 선택지 → 결정 → 감수하는 것 → 다시 볼 조건

### D1. 단일 차트 유지(인수인계 §7의 api/worker/web 3차트 안 대신)
- 문제: 인수인계는 3차트를 추천했지만 위키 5-4 7.1은 "공통 차트 `keepgo-app` 하나"로 정했다.
- 결정: 위키를 따른다. worker·web 차이는 values(`component`, `service.enabled`, 프리셋)로 표현한다.
- 감수: 템플릿에 조건문이 늘고, 차트 하나의 실수가 9개 서비스에 퍼진다 → `values.schema.json` + negative 테스트 + prod 차트 버전 고정(D10)으로 막는다.

### D2. gitops를 Cloud 레포 하위 폴더로 두고 나중에 옮김
- 선택지: (a) 지금 새 저장소 생성 (b) 하위 폴더로 개발 후 `git subtree split`
- 결정: (b). 저장소 생성·권한은 사람이 정할 일이고, subtree split은 `gitops/` 이력을 그대로 새 저장소로 옮긴다.
- 감수: workflow·CODEOWNERS가 이동 전에는 동작하지 않는다(경로가 `gitops/.github/`).

### D3. 팀 Namespace 정책을 작은 Helm 차트(tenancy)로
- 선택지: (a) Namespace마다 YAML 7개 × 6 = 42개 파일 (b) 값만 다른 반복이므로 차트
- 결정: (b). 5-1의 "팀별 운영 환경을 반복적으로 제공"과 맞고, 새 팀은 values에 한 블록만 추가한다.
- 감수: 리뷰어가 렌더링 결과를 머리로 그려야 한다 → validate.sh가 렌더링 결과를 `.rendered/`에 남긴다. ClusterRole 3개는 사람이 직접 읽어야 하므로 차트가 아니라 평범한 YAML(`platform/rbac`)로 뒀다.

### D4. ESO: Namespace별 SecretStore + Namespace별 IAM 역할
- 선택지: (a) ClusterSecretStore 하나(컨트롤러 역할이 모든 비밀 읽음) (b) Namespace별 SecretStore가 Namespace별 역할을 assume
- 결정: (b). EKS Pod Identity에서는 ESO가 Namespace의 ServiceAccount로 인증할 수 없어서(IRSA 전용 방식), 컨트롤러 역할이 Namespace별 역할을 assume하는 방식으로 최소 권한을 만든다.
- 감수: A가 만들 IAM 역할이 6개(환경당) 늘고 신뢰 정책 관리가 필요하다. SecretStore는 platform이 만들고 팀 프로젝트는 만들 수 없어서(Blacklist가 아니라 deployer 권한에 없음) 다른 팀 역할을 가져다 쓰지 못한다.

### D5. KEDA AWS 인증: KEDA 운영자가 서비스별 역할을 assume
- 문제: 처음에는 `identityOwner: workload`(서비스 자기 역할)로 했으나, KEDA 문서상 이 방식은 ServiceAccount의 IRSA 주석을 읽는다. Pod Identity는 주석이 없어 동작하지 않는다.
- 결정: `podIdentity.provider: aws` + `roleArn`(큐 길이 읽기 전용 역할). 역할이 비면 렌더링 실패.
- 감수: KEDA 운영자 역할에 `sts:AssumeRole`·`sts:TagSession` 권한이 필요하다.

### D6. Argo CD 쓰기 권한: sync impersonation
- 문제: 5-2는 "Argo CD = application-deployer를 Namespace별 RoleBinding"이라고 했지만, 기본 설치의 컨트롤러는 클러스터 전체 쓰기 권한을 가진다. AppProject 제한만으로는 쿠버네티스 권한이 줄지 않는다(인수인계 §9.5).
- 선택지: (a) 기본 권한 + AppProject만 (b) Argo CD 3.5+ sync impersonation으로 프로젝트별 계정을 빌려 적용
- 결정: (b). 팀 프로젝트는 각 Namespace의 `argocd-deployer`(ClusterRole `keepgo-application-deployer`를 RoleBinding), platform 프로젝트는 `argocd-platform-deployer`(cluster-admin, 설치 때 생성).
- 감수: beta 기능이다. 차트에 새 리소스 종류를 넣으면 deployer ClusterRole에도 추가해야 한다(빠뜨리면 sync가 권한 오류로 멈춤 — 오히려 의도한 안전장치). 컨트롤러 자체 권한(조회·캐시)은 여전히 넓다.
- 다시 볼 조건: impersonation이 GA가 되거나, 문제가 생기면 (a)로 되돌리고 AppProject·CODEOWNERS로만 막는다.

### D7. Spring 공통 values와 이미지 태그 한 곳
- 문제: 5-4는 서비스별 태그를 가정했지만 실제로는 7개 서비스가 같은 이미지다(메모: 코드·레포를 나누지 않음).
- 결정: ApplicationSet git generator의 `values.stack`으로 Spring 서비스에만 `_shared/spring*.yaml`을 먼저 겹친다. 태그는 `spring-<env>.yaml` 한 곳. 코드가 나뉘면 서비스 `values-<env>.yaml`에 `image.tag`를 적어 덮어쓴다.
- 감수: Spring 7개가 한 커밋으로 같이 배포된다(같은 이미지라 원래 그렇다). 7개가 동시에 롤링되므로 DB 커넥션 예산에 surge 7개를 다 넣었다.

### D8. ExternalSecret 이름 = `<서비스>-<항목>`
- 문제: account Namespace에 auth·member 두 서비스가 같은 공통 values를 쓰면 같은 이름의 ExternalSecret을 두 Application이 소유하게 된다(Argo CD 충돌).
- 결정: 차트가 이름 앞에 서비스 이름을 붙이고, `asEnv`·`asFiles`로 마운트까지 자동으로 한다.
- 감수: 같은 비밀이 Namespace 안에 서비스 수만큼 복사된다(Secrets Manager 호출도 그만큼).

### D9. NetworkPolicy: Namespace 기본 차단 + 서비스별 허용
- 결정: tenancy가 Namespace마다 `default-deny-ingress`, 차트가 서비스별로 호출자·ALB 서브넷(IP target이라 Pod로 직접 옴)·모니터링만 연다. ai-api는 partA 초안(호출자 제한 + 외부 443만 송신)을 그대로 옮겼다.
- 감수: 새 호출 관계가 생기면 values에 허용을 추가해야 통신된다. partA가 같은 정책을 손으로 적용해 두었다면 이름이 달라 둘 다 적용된다(더하기라 동작은 같지만 관리가 둘) → A와 차트 하나로 합의(사용자 할 일).
- 확인 필요: VPC CNI 정책 엔진이 kubelet Probe를 막지 않는지(kind에서는 막지 않았음, §6).

### D10. prod 차트 버전 고정: git 태그
- 5-4 7.5는 ECR OCI + 버전 고정. OCI 저장소가 아직 없어 prod ApplicationSet은 차트를 git 태그 `keepgo-app-<version>`으로 고정하고, `chart-release` workflow가 Chart.yaml 버전이 바뀌면 태그를 만든다(OCI 푸시는 변수 설정 시).
- 감수: values는 main, 차트는 태그라 두 소스의 버전이 엇갈릴 수 있다 → 차트가 모르는 키는 schema가 거부하므로 새 values 키를 쓰기 전에 prod 차트 태그부터 올린다.

### D11. 메트릭 수집은 PodMonitor
- ServiceMonitor는 Service가 있어야 한다. worker는 Service가 없으므로 PodMonitor 하나로 통일했다. `podTargetLabels`로 서비스 이름을 지표에 붙여 대시보드·알림에서 쓴다.

### D12. HPA 기본값과 PDB 조건
- HPA: CPU 70%, scaleUp 60초 안정화·최대 2개/분, scaleDown 300초 안정화·1개/분(5-3 5.4 방향, 숫자는 가정).
- PDB: 평소 최소 Pod 수가 2 이상일 때만 `maxUnavailable: 1`(5-3 6.9의 `minAvailable` 금지 이유와 같음). dev는 최소 1이라 PDB가 없다.

### D13. ResourceQuota·LimitRange 산정
- Quota = Σ(maxReplicas + maxSurge) × requests에 마이그레이션·여유를 더함(5-2 2.2). `check-budget.py`가 값이 부족하면 CI를 실패시킨다.
- LimitRange는 차트 밖에서 만든 Pod(디버그 Pod 등)의 기본값(100m/128Mi)과 상한(2Gi)만 둔다. 차트는 항상 직접 적는다.
- Pod Security `restricted`를 Namespace에 강제했다(5-2 하드닝). 차트 Pod는 이미 만족한다.

### D14. Argo CD는 자기 자신을 관리하지 않음
- 설치는 사람이 helm으로 한 번, 이후 값 변경도 helm으로. 자기 관리(Argo CD Application으로 Argo CD)는 업그레이드 실패 시 복구 경로가 사라질 수 있어 2인 운영 초기에는 하지 않는다.
- root 앱의 sync-wave가 실제로 앞 단계를 기다리도록 Application Health 계산을 켰다(Argo CD 기본은 꺼져 있음).

### D15. 로컬 검증: 클러스터 안 Git 서버 + Mock
- GitHub에 push하지 않고(외부 공개·권한 문제) kind 안 soft-serve에 push해 Argo CD가 실제와 같은 방식으로 읽게 했다. GitHub 주소만 로컬 주소로 바꾼다.
- 이미지는 busybox Mock으로 포트·Probe 경로만 맞췄다. 앱 동작은 검증 대상이 아니다.

### D16. 알림·대시보드
- Argo CD Notifications: 실패·Degraded는 모든 앱, 배포 완료는 prod만(dev는 merge마다라 소음).
- 대시보드는 패널당 지표 하나(이중 축 없음), 생성 스크립트(`scripts/gen-dashboards.py`)로 만들어 JSON을 손으로 고치지 않는다.

### D17. root 앱 전용 bootstrap 프로젝트(kind에서 발견)
- 문제: impersonation을 켜면 **모든** 프로젝트에 배포 계정이 있어야 한다. root 앱을 `default` 프로젝트에 두자 "no matching service account" 오류로 동기화가 멈췄다.
- 결정: `argocd/bootstrap/project.yaml`(argocd Namespace의 AppProject·Application·ApplicationSet만 허용, `argocd-platform-deployer`로 적용)을 root와 함께 사람이 한 번 적용한다.

### D18. 알림 전달: monitoring Namespace의 AlertmanagerConfig 하나
- 선택지: (a) 팀 Namespace마다 AlertmanagerConfig(웹훅 Secret 6벌, ESO 경로 추가) (b) monitoring에 하나 + A의 Alertmanager를 `alertmanagerConfigMatcherStrategy: None`으로
- 결정: (b). B가 만든 `Keepgo*` 알림만 골라 서비스별로 묶어 Discord로 보낸다. 웹훅 주소는 한 곳에만 있다.
- 감수: A의 Alertmanager 설정 하나에 의존한다. A가 바꾸지 않으면 팀 Namespace 알림이 전달되지 않는다(사용자 할 일 §1).

### D19. dev 야간·주말 축소는 보류
- 5-4 5.1은 dev를 "야간·주말 축소"한다고 했지만 방법이 없다. 선택지: KEDA cron 트리거(HPA 서비스를 모두 KEDA로 바꿔야 함), 외부 스케줄러가 replicas를 바꿈(GitOps·selfHeal과 충돌), A가 NodePool 한도를 시간대별로 조절.
- 결정: 지금은 하지 않는다. dev는 이미 최소 1개이고, Pod가 줄면 Karpenter가 노드를 정리한다. dev EKS 비용을 실제로 본 뒤 KEDA cron(앱 쪽) 또는 노드 측(A) 중에서 정한다.

### D20. Worker do-not-disrupt·임시 디스크는 측정 후
- 5-3 6.5(긴 작업이 Consolidation으로 자주 끊기면 `karpenter.sh/do-not-disrupt`)와 5-3 2.4(임시 디스크를 쓰면 `ephemeral-storage`)는 "검토"·"쓰는 경우" 조건부다. 지금 Worker에는 SQS 코드가 없어 작업 시간·디스크 사용을 잴 수 없다.
- 결정: 넣지 않는다. 필요해지면 worker values에 `podAnnotations`와 `resources`의 `ephemeral-storage`만 추가하면 된다(차트 수정 불필요). Worker 종료 상한 110초 < Worker NodePool 종료 유예 5분(partA)이라 Pod 종료가 노드 종료보다 먼저 끝난다.

### D21. Secret 값이 바뀌었을 때 Pod 반영(5-4 7.6 "따로 정한다")
- 선택지: (a) Reloader 같은 컨트롤러가 Secret 변경을 감지해 자동 재시작 (b) Git에서 `podAnnotations` 값을 바꿔 롤링 재시작
- 결정: (b). 재시작이 Git 이력에 남고(배포 충돌 backlog의 "Secret 변경도 추적" 요구), 컨트롤러가 하나 줄어든다.
- 감수: 비밀을 바꾼 뒤 사람이 PR을 하나 더 올려야 한다(Runbook §3.6). 비밀 교체가 잦아지면 (a)를 다시 본다.

### V2 배포 충돌 backlog(`docs/backlog/v3-deployment-conflict-recovery.md`) 대응

| backlog 요구 | 이번 구현 | 남은 것 |
|---|---|---|
| 앱 변경 경로를 GitOps 하나로 | 클러스터에 쓰는 것은 Argo CD뿐, CI는 ECR push + Git 커밋만(클러스터 권한 없음) | 실클러스터에서 CI 역할에 EKS 권한이 없는지 확인 |
| Terraform과 Argo CD가 같은 리소스를 동시에 관리하지 않기 | 앱·팀 Namespace·KEDA·ESO = Argo CD, 노드·Gateway·LBC·Prometheus = A | A와 소유 범위 합의(사용자 할 일 §1) |
| 사람·CI의 직접 변경 차단 | 팀 그룹은 조회만, 플랫폼 그룹도 앱 Deployment 쓰기 없음(rbac-check 52/52) | Access Policy 제거(A) |
| HPA·KEDA·ESO 관리 범위 구분 | autoscaler가 있으면 replicas를 Git에 두지 않음, Secret은 ESO가 만들고 Argo CD는 ExternalSecret만 | — |
| 외부 변경 감지·되돌림·재개 | selfHeal + OutOfSync 이력, 긴급 변경 절차(Runbook §3.10) | dev에서 실제 시연 |
| 미반영·실패 상태 드러내기 | Argo CD 실패·Degraded·prod 배포 완료 Discord 알림(서비스·환경·이미지·커밋 링크) | "빌드 성공 후 오래 미반영" 감지(지속 시간 알림)는 미구현 |
| Secret 변경 추적 | D21(Git annotation으로 재시작) | — |

## 6. 검증 결과

검증은 "실제로 적용 가능한가"를 보는 것만 했다(사용자 지시). 시연성 검증(selfHeal·revert 데모, HPA 부하, 장애 재현, k6)은 스크립트만 남기고 실행하지 않았다.

| # | 검증 | 방법 | 결과 |
|---:|---|---|---|
| 1 | 정적: 모든 YAML이 스키마상 적용 가능한지 | `gitops/scripts/validate.sh` — 서비스 9 × 환경 2 렌더링, kubeconform(Kubernetes 1.37.0 + CRD 스키마) | **통과**: 339개 리소스 유효, 오류 0 |
| 1-2 | 차트 규칙이 실제로 막는지 | 규칙 위반 값 14가지(태그 없음·latest·resources 없음·메모리 불일치·오타 키·HPA 0·min>max·KEDA 인증 역할 없음·HTTPRoute 경로 오류 등) | **통과**: 14건 모두 거부 |
| 1-3 | DB 커넥션·Quota 예산 | `check-budget.py` | **통과**: dev 73/80, prod 92/170(가정 A9), Namespace 12개 모두 Quota 안 |
| 2 | Argo CD로 전체 적용 | kind(노드 이미지 **v1.37.0**, EKS와 같은 버전) + 클러스터 안 Git 서버 + root 앱, impersonation 켬 | **통과**: Application 16개 전부 Synced·Healthy, 서비스 Pod 9개 Ready |
| 2-2 | 배치 | 노드 라벨·Taint를 partA와 같게 | Argo CD·KEDA·ESO → system 노드, API·AI·Web 8개 → application 노드(a·c에 분산), worker → worker 노드 |
| 2-3 | 보안 기준 | Namespace `pod-security.kubernetes.io/enforce: restricted` + 기본 차단 | 모든 Pod가 restricted 통과, 기본 차단 상태에서 kubelet Probe 정상 |
| 3 | RBAC 권한표(5-2 2.3) | `rbac-check.sh` — 풀스택·AI·플랫폼 그룹, Argo CD 배포 계정(exec·attach·port-forward·Secret 거부 포함) | **통과**: 52/52 |
| 4 | NetworkPolicy | `np-check.sh` + 수동 | **통과**: recommend/chat-api → ai-api 허용, account/auth-api → ai-api 차단, frontend/web → member-api 허용, ai-api → member-api 차단 |

검증 중 발견해 고친 것

| 발견 | 원인 | 조치 |
|---|---|---|
| root 앱 동기화 멈춤 | impersonation은 모든 프로젝트에 배포 계정 필요 | D17 bootstrap 프로젝트 |
| RBAC 4건 `no`(HTTPRoute·Gateway·NodePool) | CRD가 없는 클러스터에서는 `kubectl auth can-i`가 판정하지 못함(권한 문제 아님) | 로컬에 Gateway API·Karpenter CRD 설치 후 전부 통과. dev EKS는 A가 CRD를 설치해 두었으므로 해당 없음 |
| KEDA `identityOwner: workload` | Pod Identity에서는 동작하지 않음(KEDA 문서) | D5 roleArn 방식 |
| 같은 Namespace 두 서비스의 ExternalSecret 이름 충돌 | 공통 values | D8 이름 접두어 |
| HPA 앱이 처음 1~2분 Degraded | metrics-server가 첫 지표를 모으기 전(정상) | 조치 없음. dev EKS 첫 배포 때도 같은 현상이 보일 수 있음 |

검증하지 않은 것(AWS 필요): ExternalSecret 실제 동기화, Pod Identity, HTTPRoute·ALB·TargetGroupConfiguration, SQS·Prometheus KEDA 트리거, Karpenter 노드 생성, PodMonitor 수집, 알림 전송, workflow 실행 → [사용자 할 일](2026-11-10-partB-user-todo.md) §4.2

도구 버전: helm 4.3.1, kind 0.33.0, kubeconform 0.8.0, argocd CLI 3.6.1(winget 설치), Argo CD 차트 10.17.1(v3.6.1), KEDA 2.21.0, ESO 2.14.0, metrics-server 3.14.0, prometheus-operator-crds 33.0.1, Gateway API 1.4.0 CRD, karpenter-crd 1.15.1

## 7. DB 커넥션 예산(5-3 3.4)

`check-budget.py` 결과(가정 A8·A9·A14 기준)

| 환경 | 합계(서비스별 (max + surge) × 풀 3) | 예비 | 계 | 한도 |
|---|---:|---:|---:|---:|
| dev | 63 | 10 | 73 | 80 (db.t4g.micro) |
| prod | 72 | 20(ECS 병행 10 포함) | 92 | 170 (db.t4g.small 가정) |

prod를 지금 V2 RDS(db.t4g.micro, 약 80)로 두면 92 > 80이라 최대 확장 + Spring 7개 동시 롤링 때 커넥션이 모자란다. 전환 전에 RDS를 올리거나, 풀 크기·maxReplicas를 줄이거나, RDS Proxy를 검토한다(5-3 3.4).

## 8. dev→prod 전환 Runbook(요약, 5-4·partA 4.1)

1. dev EKS에서 [사용자 할 일](2026-11-10-partB-user-todo.md) §4 검증 통과
2. A: V2 VPC에 prod EKS·System MNG·NodePool·Gateway(`keepgo-prod-gateway`) 생성, RDS 상향(A9)
3. prod 클러스터에 Argo CD 설치 → `bootstrap/project.yaml`, `root-prod.yaml` 적용 → 플랫폼·서비스 Healthy 확인(이 시점에는 DNS가 아직 ECS)
4. ECS와 병행: prod EKS ALB 주소로 스모크 테스트, DB 커넥션 합계(ECS + EKS) 확인
5. 트래픽 전환: Route 53에서 `keepgo.kr`·`api.keepgo.kr`을 prod EKS ALB로(가중치로 단계 전환 권장)
6. 복귀 조건: 5xx·p95 알림 지속, DB 커넥션 한도 근접 → DNS를 ECS로 되돌림(ECS는 정한 기간 동안 유지)
7. 기간 종료 후 ECS 정리(A)

## 9. 남은 위험

| 위험 | 영향 | 대응 |
|---|---|---|
| backend 업로드가 로컬 디스크(`/public`) | Pod가 여러 개면 파일이 흩어짐 | values에서 `FILE_STORAGE_PROVIDER=s3`로 지정. S3 모드가 실제로 동작하는지 개발팀 확인 |
| backend `@Scheduled`가 모든 Pod에서 돎 | 같은 이미지 7개 Deployment × Pod 수만큼 폴러 실행 | 개발팀에 서비스별 프로필·스케줄 분리 요청 |
| ai-api 내장 Chroma | Pod마다 데이터가 다름(replica 2 이상) | AI팀 확인. 공유 저장소 또는 읽기 전용 사전 적재 필요 |
| SQS 소비 코드 없음 | KEDA worker는 떠도 일을 안 함 | 개발팀 구현 후 동작 |
| SSE·AI 지표 없음 | KEDA가 CPU로만 확장 | 개발팀 계측 |
| NEXT_PUBLIC_* 빌드 시점 값 | dev 이미지를 prod로 그대로 올리면 dev 값이 남음 | 지금은 두 환경 값이 같음. 달라지면 런타임 설정으로 옮기거나 prod 빌드 분리 |
| impersonation beta | Argo CD 업그레이드 때 동작 변화 | dev 클러스터에서 먼저 업그레이드(5-4 6.1) |

## 10. 위키 수정 제안(위키는 직접 고치지 않음)

| 위키 | 제안 |
|---|---|
| 5-0 3.2·3.3 | Namespace(`jobs`, `platform`), PostgreSQL, Cluster Autoscaler는 5-2·5-3과 다르다. 5-2·5-3 기준으로 맞추거나 "초기안" 표시 |
| 5-2 2.3 | Argo CD application-deployer를 sync impersonation으로 구현했다는 점, 그룹 이름 |
| 5-3 1.2 | DB: MySQL 확정 |
| 5-4 3.2 | `apps/_shared/` 추가, 이미지 태그 한 곳 |
| 5-4 6.4 | dev·prod 모두 automated(현재와 같음), Application Health 계산 설정 추가 |
| 5-4 6.6 | 알림 채널 Discord |
