# V3 B파트 — 직접 해야 할 일 (2026-11-10)

코드·문서로 할 수 있는 것은 [구현 기록](2026-11-10-partB-k8s-implementation.md)에 끝냈다. 아래는 **외부 계정·권한, 다른 팀 합의, 실제 AWS 클러스터 접근**이 필요해서 사람이 해야 하는 일이다. 위에서부터 순서대로 하면 된다.

## 0. 브랜치 올리기

로컬 커밋만 있고 push하지 않았다.

```bash
git -C .worktrees/v3-helm-chart push -u origin feat/v3-helm-app-chart   # gitops
git -C .worktrees/v3-k8s-local  push -u origin feat/v3-k8s-local        # kind·검증 도구
git push origin feat/v1-central-cd-prep                                  # 이 문서들
```

- [ ] 세 브랜치 push
- [ ] (선택) 로컬 검증을 직접 다시 보려면 `feat/v3-k8s-local`의 `k8s/v3-local/README.md` 실행 순서대로

## 1. A와 맞출 값

가정으로 넣은 값이다. A의 실제 값이 다르면 "바꿀 곳"만 고치고 `bash gitops/scripts/validate.sh`로 확인한다.

| # | 맞출 것 | 지금 가정 | 바꿀 곳 |
|---:|---|---|---|
| 1 | EKS Access Entry `kubernetesGroups` | 클라우드 `keepgo:platform-operators`, 풀스택 `keepgo:fullstack-observers`, AI `keepgo:ai-observers` | `platform/rbac/platform-operator.yaml`, `platform/tenancy/values-*.yaml` |
| 2 | Access Entry에 Access Policy(예: ClusterAdmin)를 붙이지 않기 | 5-2 결정대로 RBAC만 | (A 작업) 붙어 있으면 RBAC 제한이 무의미 |
| 3 | worker NodePool Taint | `workload=worker:NoSchedule` | `apps/ingest/youtube-analysis-worker/values.yaml` |
| 4 | Gateway allowedRoutes에 쓸 Namespace | account·ingest·content·recommend·frontend(partA 그대로, ai 제외) | 변경 없음 |
| 5 | ALB idle timeout(LoadBalancerConfiguration `idle_timeout.timeout_seconds`) | SSE 때문에 **200초 이상** 요청(서버 SSE 타임아웃 180초, 5-3 4.5) | A의 `keepgo-dev3-alb-config` |
| 6 | KEDA·ESO·Argo CD 설치 소유권 | B가 Argo CD로 설치 | 다르면 `argocd/platform/<env>/keda.yaml`·`external-secrets.yaml` 제거 |
| 7 | ai-api NetworkPolicy | 차트가 관리(partA 초안과 같은 규칙) | A가 손으로 적용한 `allow-ai-api-*`는 지우기로 합의 |
| 8 | Redis 주소·Namespace | `redis.data.svc.cluster.local:6379`, TLS 없음 | `apps/_shared/spring-<env>.yaml` |
| 9 | dev RDS 주소·인스턴스 | placeholder, db.t4g.micro | `spring-dev.yaml` DB_HOST, `scripts/budget.yaml` |
| 10 | prod RDS 상향 | 전환 전 db.t4g.small 이상 | 구현 기록 §7 |
| 11 | Prometheus 스택 | kube-prometheus-stack, `monitoring`, `release: kube-prometheus-stack` | `spring-<env>.yaml` metrics, SSE·AI 트리거 serverAddress |
| 12a | Alertmanager `alertmanagerConfigMatcherStrategy.type: None` | B의 AlertmanagerConfig 하나가 모든 팀 Namespace 알림을 받도록(구현 기록 D18) | A의 kube-prometheus-stack values |
| 12 | prod Gateway·도메인 | `keepgo-prod-gateway`, `keepgo.kr`·`api.keepgo.kr` | `spring-prod.yaml`, web `values-prod.yaml` |

### A가 만들 IAM(Pod Identity association 포함)

| 역할(가정 이름) | 연결 대상(Namespace/ServiceAccount) | 권한 |
|---|---|---|
| ESO 컨트롤러 역할 | `external-secrets/external-secrets` | `sts:AssumeRole`·`sts:TagSession` → 아래 6개만 |
| `keepgo-dev3-eso-<namespace>` × 6 | (ESO가 assume) | 해당 경로만 `secretsmanager:GetSecretValue`: account·ingest·content·recommend → `keepgo/dev3/backend`·`keepgo/dev3/rds`, ai → `keepgo/dev3/ai`, frontend → `keepgo/dev3/web` |
| KEDA 운영자 역할 | `keda/keda-operator` | `sts:AssumeRole`·`sts:TagSession` → 아래 하나 |
| `keepgo-dev3-keda-youtube-analysis` | (KEDA가 assume) | `sqs:GetQueueAttributes` 분석 큐 하나 |
| 서비스 역할(필요한 것만) | `ingest/youtube-analysis-worker`, `ingest/youtube-api` | SQS 송수신(코드가 생기면), S3 업로드 버킷 |
| | `account/member-api` 등 업로드 쓰는 서비스 | `keepgo-dev3-uploads` 버킷 |

ServiceAccount 이름 = 서비스 이름(차트 규칙). prod는 `dev3` → `prod`.

### Secrets Manager에 넣을 값(dev)

| 이름 | 키 |
|---|---|
| `keepgo/dev3/backend` | GOOGLE_CLIENT_SECRET, GOOGLE_LOGIN_CLIENT_ID, GOOGLE_LOGIN_CLIENT_SECRET, VWORLD_API_KEY, JWT_PUBLIC_KEY, JWT_PRIVATE_KEY |
| `keepgo/dev3/rds` | username, password(RDS 관리 Secret이면 그 이름으로 `spring-dev.yaml` 수정) |
| `keepgo/dev3/ai` | GOOGLE_API_KEY, NAVER_MAP_CLIENT_ID, NAVER_MAP_CLIENT_SECRET, SENTRY_DSN, LANGSMITH_API_KEY |
| `keepgo/dev3/web` | YOUTUBE_API_KEY, KAKAO_REST_API_KEY, NAVER_MAPS_API_KEY_ID, NAVER_MAPS_API_KEY |

## 2. 개발팀·AI팀에 요청

| 대상 | 요청 | 이유 |
|---|---|---|
| Backend | S3 업로드 모드(`FILE_STORAGE_PROVIDER=s3`)가 실제로 동작하는지 | 로컬 디스크 업로드는 Pod가 여러 개면 깨짐 |
| Backend | 경로표 확인(구현 기록 §4) — 특히 `/api/v1/user/youtube-analyze`를 youtube-api로 보낸 것 | HTTPRoute가 서비스 분리 역할 |
| Backend | SSE 연결 수 게이지 `keepgo_sse_active_connections` | KEDA 확장 지표(5-3 5.5) |
| Backend | SIGTERM 때 SSE 재연결 유도 이벤트, Worker의 SQS 소비·멱등 처리 | 5-3 4.5 |
| Backend | `@Scheduled` 폴러를 서비스별로 나눌 프로필 | 지금은 모든 Pod에서 실행 |
| Backend | Flyway 스크립트가 생기면 `migration.enabled`로 옮기기 | 5-4 8.3 |
| AI | `/health/ready`(AI 클라이언트 준비), 처리 중 요청 게이지 `keepgo_ai_inflight_requests`, `/metrics` | Probe·KEDA |
| AI | 내장 Chroma를 Pod 여러 개에서 어떻게 쓸지 | Pod마다 데이터가 다름 |
| Frontend | 헬스 경로(`/api/health` 등), dev·prod에서 달라질 `NEXT_PUBLIC_*` 여부 | Probe, 빌드 시점 값 |

## 3. KTB4-8th-CLOUD-GITOPS 저장소 만들기

```bash
# Cloud 레포 루트에서: gitops/ 이력만 뽑아 새 브랜치로
git subtree split --prefix=gitops -b gitops-export feat/v3-helm-app-chart
# GitHub에 100-hours-a-week/KTB4-8th-CLOUD-GITOPS(빈 저장소)를 만든 뒤
git push https://github.com/100-hours-a-week/KTB4-8th-CLOUD-GITOPS.git gitops-export:main
```

- [ ] 저장소 생성(private), 위 명령으로 이력째 이동
- [ ] 브랜치 보호: main은 PR + `validate` 체크 필수 + Code Owners 승인. 예외로 GitHub App 봇의 직접 push 허용(dev 태그 커밋)
- [ ] GitHub 팀 `keepgo-cloud`·`keepgo-fullstack`·`keepgo-ai` 만들기(이름이 다르면 `.github/CODEOWNERS`, `argocd/projects/*.yaml`, `argocd/bootstrap/values.yaml` 수정)
- [ ] GitHub App 생성: KTB4-8th-CLOUD-GITOPS에 Contents·Pull requests 쓰기. 앱 ID·키를 앱 저장소 3개와 KTB4-8th-CLOUD-GITOPS의 Secret(`GITOPS_APP_ID`, `GITOPS_APP_PRIVATE_KEY`)에
- [ ] KTB4-8th-CLOUD-GITOPS → Settings → Actions → Access: 조직 저장소에서 재사용 workflow 호출 허용
- [ ] A에 요청: GitHub OIDC 역할 2개 — ECR push(앱 저장소용, `ECR_PUSH_ROLE_ARN`), ECR 조회·태그 추가(promote-prod용, `ECR_PROMOTE_ROLE_ARN`). ECR tag immutability·push 스캔 켜기, lifecycle에서 `prod-*` 최근 N개 보존
- [ ] 프런트 저장소 변수(vars) 확인: `NEXT_PUBLIC_GOOGLE_CLIENT_ID`, `NEXT_PUBLIC_NAVER_MAP_CLIENT_ID`, `NEXT_PUBLIC_CLARITY_PROJECT_ID`, `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_ORG`, `SENTRY_PROJECT`, Secret `SENTRY_AUTH_TOKEN`(V2 CI가 쓰는 것과 같음)
- [ ] 앱 저장소 3개에 `gitops/docs/ci-callers/<스택>.yaml`을 `.github/workflows/deploy-dev.yaml`로 복사(기존 V2 배포와 겹치지 않게 전환 시점에)
- [ ] 첫 차트 태그: `git tag keepgo-app-0.3.0 && git push origin keepgo-app-0.3.0`(이후는 chart-release workflow가 만든다)
- [ ] (선택) ECR `keepgo-charts` 저장소 만들고 변수 `CHART_OCI_REPO`, Secret `CHART_PUSH_ROLE_ARN` 설정

## 4. dev EKS 적용과 실환경 검증

### 4.1 설치

```bash
export KUBECONFIG=~/.kube/keepgo-dev3.yaml   # platform-operator 역할로 접속(부트스트랩은 관리자 권한 필요)
helm repo add argo https://argoproj.github.io/argo-helm && helm repo update
helm upgrade --install argocd argo/argo-cd --version 10.17.1 \
  -n argocd --create-namespace -f argocd/bootstrap/values.yaml --wait
# 비밀값 2개(값은 Git에 두지 않는다)
kubectl -n argocd create secret generic argocd-dex-github \
  --from-literal=clientID=<GitHub OAuth App ID> --from-literal=clientSecret=<secret>
kubectl -n argocd label secret argocd-dex-github app.kubernetes.io/part-of=argocd
kubectl -n argocd patch secret argocd-notifications-secret \
  --type merge -p '{"stringData":{"discord-webhook-url":"<Discord webhook URL>"}}'
# 알림 webhook(Alertmanager → Discord, 구현 기록 D18)
kubectl -n monitoring create secret generic keepgo-alert-discord --from-literal=url=<Discord webhook URL>
# 저장소 자격 증명(private KTB4-8th-CLOUD-GITOPS). GitHub App으로 등록한다
argocd login --port-forward --port-forward-namespace argocd --plaintext --username admin   --password "$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
argocd repo add https://github.com/100-hours-a-week/KTB4-8th-CLOUD-GITOPS.git --port-forward --port-forward-namespace argocd   --github-app-id <App ID> --github-app-installation-id <설치 ID> --github-app-private-key-path <키 파일>
kubectl apply -f argocd/bootstrap/project.yaml -f argocd/bootstrap/root-dev.yaml   # root 전용 프로젝트 먼저
```

- [ ] GitHub OAuth App 생성(callback `https://<argocd 주소>/api/dex/callback`)
- [ ] SSO가 동작하면 admin 계정 끄기(`configs.cm.admin.enabled: "false"`) 또는 비밀번호 교체
- [ ] Argo CD 접속 경로 결정(지금은 port-forward. 외부 노출하려면 Gateway allowedRoutes에 argocd 추가 + HTTPRoute — A와 합의)

### 4.2 dev EKS에서만 확인할 수 있는 것

| # | 확인 | 명령·방법 | 통과 기준 |
|---:|---|---|---|
| 1 | 모든 Application | Argo CD 화면 또는 `kubectl -n argocd get applications` | 전부 Synced·Healthy |
| 2 | Pod 배치 | `kubectl get pods -A -o wide` + 노드 라벨 | 앱 = application 노드, worker = worker 노드, Argo CD·KEDA·ESO = system 노드 |
| 3 | 권한 | `feat/v3-k8s-local`의 `scripts/v3-local/rbac-check.sh`(관리자 컨텍스트) + 실제 팀 IAM으로 `kubectl auth can-i` | 전부 기대값. Access Policy가 붙어 있으면 결과가 넓게 나옴 |
| 4 | ExternalSecret | `kubectl get externalsecrets -A` | 전부 `SecretSynced` |
| 5 | Probe·NetworkPolicy | Pod Ready, `np-check.sh`(실제 이미지면 curl로) | Ready + ai-api 허용·차단. VPC CNI가 kubelet Probe를 막지 않는지 |
| 6 | 외부 경로 | `curl -I https://dev3.keepgo.kr/api/v1/places` 등 경로별 | 서비스별 응답, ALB 대상 그룹 healthy |
| 7 | SSE | 브라우저에서 채팅·추천 | 180초 동안 끊기지 않음(idle timeout), 배포 중 재연결 |
| 8 | HPA | `tests/v3/load/api.js`(k6) | Pod 증가 → 노드 증가(Karpenter) → 축소 |
| 9 | KEDA SQS | 큐에 메시지 넣기 | worker 0→N→0(앱에 SQS 코드가 생긴 뒤) |
| 10 | 장애 | `scripts/v3-local/chaos.sh pod-kill|readiness-fail|image-pull` | 5-4 9.2 표대로 동작, selfHeal로 복구 |
| 11 | 롤백 | GitOps 태그 커밋 revert | 이전 태그로 동기화, Discord 알림 |
| 12 | 대시보드 | Grafana `KeepGo V3` 폴더 | 패널에 값이 나옴(SSE·AI 패널은 지표 생긴 뒤) |
| 13 | 알림 전달 | Pod 하나를 일부러 CrashLoop(`chaos.sh readiness-fail` 등) | 10분 안에 Discord에 `KeepgoReplicasUnavailable`, 복구 후 resolved |
| 14 | Secret 반영 | Secrets Manager 값 변경 → `podAnnotations.secret-rev` 변경 PR | 롤링 재시작 후 새 값(Runbook §3.6) |

- [ ] 결과를 [구현 기록](2026-11-10-partB-k8s-implementation.md) §6에 추가(설계/구현/검증 구분 유지)

## 5. prod 전환

[구현 기록 §8 Runbook](2026-11-10-partB-k8s-implementation.md) 순서대로. 시작 전에 확인:

- [ ] RDS 상향(또는 풀·maxReplicas 축소) 후 `scripts/budget.yaml` 한도 갱신, validate 통과
- [ ] prod RDS 관리 Secret 실제 이름으로 `spring-prod.yaml` 수정
- [ ] Gateway·도메인·인증서(A)
- [ ] prod Argo CD 설치 → `bootstrap/project.yaml` + `root-prod.yaml`

## 6. 측정한 뒤 정할 것(지금은 보류, 구현 기록 D19·D20)

- [ ] dev 야간·주말 축소(5-4 5.1): dev EKS 비용을 본 뒤 KEDA cron(앱) 또는 NodePool 한도(A)
- [ ] Worker `karpenter.sh/do-not-disrupt`·`ephemeral-storage`: SQS 코드가 생긴 뒤 작업 시간·디스크 사용량을 재고
- [ ] HPA·KEDA 목표값, maxReplicas, Hikari 풀 크기: 부하 테스트(§4.2 #8) 결과로 values 조정
- [ ] "빌드는 됐는데 오래 미반영" 알림(배포 충돌 backlog): 필요하면 Argo CD 앱의 이미지 태그와 ECR 최신 태그 비교 알림 추가

## 7. 위키 반영

- [ ] 구현 기록 §10의 제안을 위키에 반영하고 `design-snapshot/`을 다시 복사
