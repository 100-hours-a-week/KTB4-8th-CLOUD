# V2 CD 계획 — 중앙 CD 유지, 이벤트 트리거, dev/prod 승격

> 2026-10-08 결정안. V2(ECS) 배포 방식을 정하고 V1에서 옮겨 가는 순서를 적는다. 배포 안전장치의 상세 요구는 [V2 CI/CD 검토](v2-cicd-design-review.md), 인프라 전체는 [V2 설계](V2%20설계.md), 현재 운영은 [V1 설계](v1-design.md)와 [기술 결정](technical-decisions.md)이 기준이다.

## 1. 결정 요약

| 항목 | 결정 |
| --- | --- |
| CD 방식 | **중앙 CD 유지.** Cloud 저장소가 운영 목표 상태(Manifest)를 관리하고 ECS 배포를 실행한다 |
| 트리거 | 지금의 EventBridge 10분 조회를 유지하고, **ECR push 이벤트를 추가**해 즉시 조회를 시작한다. 이벤트 규칙이 없어도 조회만으로 동작한다. **V1에 먼저 적용했다([10절](#10-v1-선적용--ecr-push-이벤트로-즉시-조회))** |
| 토큰 | V1의 fine-grained PAT(Cloud 저장소 하나, Actions Read and write)와 EventBridge 연결을 **그대로 재사용**한다. 새 자격 증명을 만들지 않는다 |
| 환경 | dev·prod. App 저장소의 `dev` 브랜치는 개발서버, `dev → main` PR 병합이 운영 반영 결정이다 |
| 승격 | main에서 이미지를 다시 빌드하지 않는다. **dev에서 성공한 digest만 prod에 배포**한다 |
| 실행 단위 | 환경·서비스 그룹별 레인. DB Migration이 있을 때만 공유 잠금 |
| 저장소 | V2에서는 분리하지 않는다. `deployment/envs/{dev,prod}`를 V3 GitOps 구조로 만들고 V3에서 떼어 낸다 |
| FE | S3+CloudFront. FE CI가 산출물을 올리고 중앙이 index.html을 교체한다 |
| V3 | GitOps 저장소 분리 후 적용 부분만 ArgoCD로 교체한다 |

**설계 근거.** V1·V2·V3 모두 운영 목표 상태를 한 곳에서 관리한다. 바뀌는 것은 실행 수단(SSM → ECS API → ArgoCD)과 트리거(주기 → 이벤트)뿐이다. V2의 즉시 반영은 V1에서 이미 쓰는 Actions 전용 토큰과 EventBridge 연결로 해결하므로 보안 범위가 늘지 않는다.

## 2. 전제

- ECS로 운영하며 실제 사용자 트래픽을 가정한다.
- 배포 반영 지연을 없애고 싶다.
- GitHub App은 조직 owner 권한이 필요해 쓸 수 없다. 저장소 간 호출은 PAT만 가능하다(TD-017).
- 팀 5명 중 클라우드 2명이 App CI 작성과 배포 장애 대응을 맡는다. 클라우드는 App 저장소에 쓸 수 있다.
- Backend·Worker·SSE는 같은 저장소(KTB4-8th-BE)다. 이미지를 나눌지는 미정이다.
- DB Migration은 드물다.
- FE는 S3+CloudFront로 확정이다.
- V3에서 K8s와 ArgoCD 전환은 확정이다.
- Cloud 저장소 main에는 보호 규칙이 없다(TD-017). IaC는 작성자가 직접 검토하고 올린다.

## 3. 검토한 대안

### 3.1 중앙 CD vs 독립 CD

| 기준 | 중앙 + 이벤트 트리거 — 채택 | 독립 CD (Cloud의 공용 workflow를 App이 호출) |
| --- | --- | --- |
| 보안 | 기존 Actions 전용 PAT 재사용. 이 토큰은 workflow 실행·취소만 가능하고 코드를 바꿀 수 없다. 배포 Role은 Cloud 저장소만 신뢰 | 배포 경로에 PAT가 없다. 대신 공개 App 저장소 3곳이 배포 Role을 쓰므로 공용 workflow로만 Role을 쓰도록 제한해야 한다 |
| 지연 | 수십 초 | 수십 초 |
| 운영 | 목표 상태·이력·승격 조건·장애 확인이 한 곳 | 상태가 3개 저장소의 Actions 기록과 SSM에 흩어진다 |
| 장애 범위 | Cloud 저장소·EventBridge가 멈추면 전체 배포가 멈춘다. 10분 조회가 안전망 | 서비스별로 격리 |
| V1 → V2 전환 | 저장소·토큰·연결 재사용. 규칙 추가, 스키마 확장, 배포 대상만 교체 | 공용 workflow·App CI 3곳·IAM Role 3개·상태 저장소 신설, V1 구조 폐기 |
| V2 → V3 전환 | Manifest 경로를 GitOps 저장소로 분리, 적용 부분을 ArgoCD로 교체 | GitOps 저장소 신설, App CI 3곳 재수정 |
| 일관성 | V1~V3 모두 중앙 목표 상태 | 중앙 → 독립 → 중앙으로 두 번 바뀐다 |

**판단.** 즉시 반영과 PAT 제약을 지금의 토큰과 인프라로 해결할 수 있으므로 중앙을 유지한다. 팀 규모가 그대로라 독립 CD의 주된 이점인 팀별 소유권이 없다. V2 배포 workflow는 어느 방식이든 V3에서 버리므로, 독립 CD가 V3 준비에 주는 이점도 없다.

### 3.2 트리거 방식

| 대안 | 판단 |
| --- | --- |
| EventBridge 10분 조회만 (현재) | 동작한다. 최대 10분 지연. 안전망으로 유지 |
| **ECR push 이벤트 → 기존 API destination → `workflow_dispatch`** — 채택 | 기존 토큰·연결을 재사용한다. 이벤트는 "조회하라"는 신호로만 쓰고, 판단은 기존 조회 로직이 한다. 중복·누락에 강하다 |
| App CI가 `repository_dispatch` 호출 | `repository_dispatch`는 Contents 쓰기 권한이 필요하고, 토큰이 App 저장소 3곳에 퍼진다. 기각 |
| App CI가 Cloud에 Manifest PR 생성 | Contents·Pull requests 쓰기 토큰이 App 저장소 3곳에 필요하다. 기각(TD-022 비교와 같다) |

### 3.3 저장소 분리 시점

| 기준 | V2에서 분리 | V3에서 분리 — 채택 |
| --- | --- | --- |
| 작업량 | 1~2일 | 1~2일(`filter-repo`, 연결 변경). 총량은 같다 |
| 보안 | 토큰이 Actions 전용이라 분리 이득이 작다 | 같다 |
| 경로별 보호 규칙 | 필요 없음 | main 보호가 없고 구조 변경이 드물어 필요 없다 |
| 이력 | 깔끔 | dev 배포 커밋이 쌓인다. 경로로 걸러 본다 |
| 시점 | V2 시작 때 | K8s 전환과 겹친다 |

**판단.** 작업량이 같고 보안 이득이 작으므로 V2 일정을 우선한다. 대신 V3에서 경로째 떼어 낼 수 있게 처음부터 GitOps 구조로 둔다.

## 4. V2 구성

### 4.1 전체 흐름

```text
[App 저장소 — 클라우드가 CI 작성]
feature/* ─PR→ dev ─push→ test → build → ECR push (tag = commit SHA)
dev ─PR→ main ─push→ 트리 해시 확인 → 재빌드 없이 retag (tag = main SHA)
hotfix/* ─PR→ main (병합 후 main → dev 역병합)
                │
                ▼ ECR push 이벤트 (규칙이 없으면 10분 조회가 대신)
[AWS EventBridge] 기존 API destination → Cloud workflow_dispatch (Actions 전용 PAT)
                │
                ▼
[Cloud 저장소]
조회: sources.json의 저장소별 dev·main head와 CI 성공·digest 확인
  → envs/dev 또는 envs/prod 갱신 (GITHUB_TOKEN PR 즉시 병합, 기존 release.sh 방식)
  → prod는 dev 성공 기록이 있는 digest만 허용
  → 환경·서비스 그룹별 레인에서 ECS 배포
       Migration(있을 때만, 공유 잠금) → Task Definition 등록 → Service 갱신
       → ECS Circuit Breaker·Deployment Alarm·Bake Time → Smoke
  → 성공: last-good 기록 / 실패: ECS 롤백 확인, 후속 배포 차단, Discord 알림
```

### 4.2 브랜치와 환경

| App 브랜치 | 환경 | 규칙 |
| --- | --- | --- |
| `dev` | dev | push마다 빌드·배포. 개발 측의 기능 시험 공간 |
| `main` | prod | `dev`와 `hotfix/*`에서 온 PR만 병합. 병합이 운영 반영 결정이다. 클라우드 승인 단계는 없다 |
| `feature/*` | (선택) dev 임시 배포 | `workflow_dispatch`로 dev에 임시 배포. 다음 dev push 때 dev 기준으로 돌아온다 |
| `hotfix/*` | (선택) dev 임시 배포 후 prod | 병합 후 main → dev 역병합 필수 |

- **재빌드 금지.** main이 dev만 병합받으면 병합 커밋의 트리는 dev head와 같다. main CI는 트리 해시가 같은 dev 이미지를 찾아 retag만 한다. 찾지 못하면 실패로 끝내고 빌드하지 않는다.
- **미완성 기능.** `dev → main`은 dev 전체를 옮긴다. 운영 반영을 작고 자주 하고, 긴 기능은 feature flag로 숨긴다. 급하면 dev에서 revert 후 PR을 올린다.

### 4.3 Manifest와 소스 매핑

`deployment/sources.json`에 환경별 브랜치와 서비스를 추가한다.

```json
"backend": {
  "repository": "100-hours-a-week/KTB4-8th-BE",
  "branches": { "dev": "dev", "prod": "main" },
  "workflow": "ci.yml",
  "services": ["backend", "worker", "sse"],
  "order": ["migration", "worker", "backend", "sse"]
}
```

`deployment/envs/{dev,prod}/<group>.json`에 그룹 단위로 기록한다. 이미지가 하나면 세 서비스에 같은 digest가 들어간다.

```json
{
  "source_commit": "<40자리 SHA>",
  "build_run_id": 123456789,
  "services": {
    "backend": "<account>.dkr.ecr.ap-northeast-2.amazonaws.com/keepgo-backend@sha256:...",
    "worker":  "...@sha256:...",
    "sse":     "...@sha256:..."
  }
}
```

- Task Definition의 Role·CPU·메모리·Secret 참조는 Manifest가 아니라 IaC 템플릿에 둔다. 봇은 digest와 출처만 바꾼다.
- 성공 기록(last-good)은 Git이 아니라 SSM Parameter `/keepgo/{env}/{service}/last-good`에 둔다. Git에 쓰면 PR과 CD가 순환한다.

### 4.4 실행 레인

| 레인 (`concurrency.group`) | 대상 |
| --- | --- |
| `deploy-{env}-backend` | migration → worker → backend → sse |
| `deploy-{env}-ai` | ai-api |
| `deploy-{env}-fe` | S3·CloudFront |
| `deploy-{env}-db` (공유 잠금) | Migration이 있는 배포만 추가로 획득 |

레인끼리는 서로 기다리지 않는다. Bake Time이 긴 Backend 배포 중에도 AI·FE는 바로 배포된다.

### 4.5 배포 workflow는 얇게

V2 배포 workflow는 V3에서 ArgoCD로 대체된다. 직접 구현하는 양을 줄인다.

| ECS에 맡김 | workflow가 직접 함 |
| --- | --- |
| Rolling Update, Circuit Breaker 롤백, Deployment Alarm 롤백, Bake Time | 출처·digest 검증, prod 승격 조건, 레인·잠금, Migration Task 실행·종료 코드 확인, Smoke, last-good 기록, 실패 차단·알림 |

출처 검증과 승격 조건 스크립트는 V3에서 GitOps 저장소의 PR 검사로 다시 쓴다.

### 4.6 FE (S3+CloudFront)

```text
FE CI → s3://<artifact-bucket>/releases/<sha>/ 업로드 → 마지막에 _complete 업로드
Cloud fe 레인:
  1. releases/<sha>/assets/* → 배포 버킷 /assets/ (immutable, 1년 캐시, 이전 파일 유지)
  2. index.html을 마지막에 교체 (no-cache)
  3. CloudFront invalidation: /index.html
  4. Smoke(HTML, 주요 asset 200) → envs/{env}/frontend.json 갱신
롤백: 이전 <sha>의 index.html 재업로드
```

- API 주소는 빌드에 넣지 않고 환경별 `/config.json`에서 읽는다. 같은 산출물을 dev·prod에 쓴다. 어려우면 FE CI가 환경별로 두 벌 빌드한다.
- `_complete` 업로드를 S3 → EventBridge 이벤트로 받아 같은 dispatch 경로로 조회를 시작한다.

### 4.7 권한

| 주체 | 권한 |
| --- | --- |
| EventBridge 연결의 PAT | Cloud 저장소 하나, Actions Read and write (V1과 같다) |
| App CI (OIDC) | 자기 ECR 저장소 push·retag, FE는 artifact 버킷의 `releases/*` 쓰기 |
| Cloud 배포 Role (OIDC) | Cloud 저장소 main과 `dev`·`production` environment에서만 assume. ECS·Task Definition 등록·iam:PassRole(지정 Role만)·SSM last-good·S3 배포 버킷·CloudFront invalidation |
| Cloud 저장소 main (선택) | Ruleset: PR 필수, 승인 0명, force push·삭제 금지. release.sh 자동 병합과 함께 동작한다 |

### 4.8 환경 전환 예정 — dev는 V1 인스턴스 그대로

V2 인프라를 다 올린 뒤 운영을 ECS로 옮기고, **지금의 V1 인스턴스(Compose 한 대)는 구성을 그대로 둔 채 개발서버로 쓴다.** dev에 ECS를 함께 들일 필요는 없다. 목표 상태·조회·승격은 배포 수단과 분리돼 있어서 환경마다 배포 대상만 다르게 두면 된다.

| 환경 | 배포 대상 | 배포 workflow |
| --- | --- | --- |
| dev | V1 인스턴스, SSM + `deploy.sh`(Compose) | 지금의 `deploy-production.yaml`을 환경 입력을 받게 바꿔 재사용 |
| prod | ECS | `deploy-ecs.yaml` |

- 전환 전까지는 V1 인스턴스 하나뿐이므로 지금 구조(`production-manifest.json`, `deploy-production.yaml`)를 바꾸지 않는다. 환경 분리는 V2 인프라를 올릴 때 한다.
- 앱 저장소 dev 브랜치는 BE `dev`, FE `develop`, AI `dev`(예정)로 저장소마다 이름이 다르다. `sources.json`의 `branches`에 저장소별로 적는다.
- **dev와 prod가 다른 점.** dev에서는 ECS 고유 문제(Task Definition, ALB Health Check, Service Connect, Task Role)를 잡지 못한다. prod ECS는 트래픽을 옮기기 전에 따로 시험한다. FE는 dev가 컨테이너, prod가 S3라 digest가 아닌 같은 source commit으로 승격을 판단한다.
- 같은 digest를 dev·prod에 쓰려면 V1 인스턴스와 ECS 인스턴스의 CPU 아키텍처가 같아야 한다. 전환 전에 확인한다.
- dev DB·Secret은 미정이다. `prepare-runtime.py`는 `BE_SECRET_ID`·`AI_SECRET_ID` 환경변수를 이미 받는다.

## 5. ECR 이벤트 없이 동작하는가

동작한다. ECR 이벤트는 지연을 줄이는 장치일 뿐이고, 배포 판단은 조회 로직이 한다. V1처럼 10분 조회만으로 dev·prod 배포가 모두 된다.

| 단계 | ECR 이벤트 없음 | ECR 이벤트 있음 |
| --- | --- | --- |
| dev 반영 | 최대 10분 | 수십 초 |
| prod 반영 (main retag) | 최대 10분 | 수십 초. retag가 이벤트를 만드는지는 구현 때 확인하며, 안 되면 10분 조회가 잡는다 |
| 이벤트 유실 | 해당 없음 | 다음 10분 조회가 잡는다 |

따라서 이벤트 규칙은 마지막에 붙여도 된다. 다만 V1에도 바로 적용할 수 있어 먼저 하면 현재 운영의 지연도 함께 줄어든다. **2026-10-08 V1에 먼저 적용했다([10절](#10-v1-선적용--ecr-push-이벤트로-즉시-조회)).** V2에서는 규칙의 `EcrRepositories`에 새 이미지 저장소를 더하고 S3 규칙만 붙인다.

## 6. 진행 순서

담당 표시: **(설정)** 사람이 콘솔·GitHub 화면에서 한다. **(팀)** 앱 팀 결정이나 확인이 먼저 필요하다. 표시가 없으면 Cloud 저장소·앱 CI 코드로 처리한다.

### 단계 0 — 지금 (V1, 2026-10-08 작업 마무리)
- [ ] `feat/ecr-push-trigger` PR 병합
- [ ] (설정) CloudShell에서 `keepgo-v1-github-dispatch` 스택 갱신, 변경 세트에 `Add AutoReleaseOnEcrPush` 하나만 있는지 확인(10.6)
- [ ] 다음 앱 main 병합 때 Auto release가 수십 초 안에 시작·병합·배포되는지 확인
- [ ] (팀) 지금 개발서버가 계속 운영 브랜치(BE `main`, FE `feat/v1`, AI `main`)를 받을지, 개발 브랜치로 바꿀지 결정. 바꾸면 `sources.json` 브랜치와 FE CI(`develop` 빌드)를 고친다

### 단계 1 — 기반 (V1 영향 없음)
- [ ] `infrastructure/`에 V2 ECS 클러스터·서비스·ALB·ECR·IAM Role(dev·prod) 템플릿
- [ ] App별 ECR push 전용 OIDC Role
- [ ] Cloud 배포 Role (main·environment 조건)
- [ ] dev 환경 리소스(RDS·Secret 분리). 방식 미정(7장)
- [ ] (설정) 기존 배포 Role 신뢰 정책에 `environment:dev` 추가. 승격 기록용 `ssm:PutParameter`(`/keepgo/dev/*`) 권한 추가
- [ ] (설정) GitHub Environment `dev` 생성, Variable `DEV_EC2_INSTANCE_ID`(V1 인스턴스). dev Secret을 나누면 `BE_SECRET_ID`·`AI_SECRET_ID`
- [ ] (설정) dev 도메인: DNS 레코드, V1 인스턴스의 TLS 인증서(`/opt/keepgo/tls`), 접근 제한(공개 또는 IP 제한)

### 단계 2 — 스키마와 조회
- [ ] `sources.json`에 `branches`·`services`·`order` 추가
- [ ] `deployment/envs/{dev,prod}` 스키마와 검사 jq(`check-manifest.jq` 확장)
- [ ] release.sh를 환경별 조회로 확장. dev head → envs/dev, main head → envs/prod
- [ ] prod 승격 조건: SSM last-good(dev)과 digest 일치 확인. Auto release에 AWS OIDC 인증 추가
- [ ] 배포 workflow가 환경을 입력받고, `deploy.sh`가 환경별 Manifest를 읽게 수정(4.8). prod 대상은 ECS로 분기
- [ ] `compose.yaml`에서 운영 값으로 고정된 것을 환경별로 분리: `SPRING_PROFILES_ACTIVE: prod`, LangSmith 프로젝트 `keepgo`, CloudWatch 로그 그룹 `/keepgo/v1/application`, Prometheus 라벨 `environment: production`

### 단계 3 — App CI (클라우드 작성)

현재 상태(2026-10-08): BE는 `dev`·`main` push 모두 빌드한다. AI는 `main`만 빌드하고 `dev` 브랜치가 없다. FE는 `main`·`feat/v1`에서 컨테이너 이미지 2개(amd64)를 빌드한다.

- [ ] BE: main push는 다시 빌드하지 않고, 트리 해시가 같은 dev 이미지를 찾아 main SHA 태그만 붙인다. 못 찾으면 실패. dev 빌드 때 트리 해시 태그도 붙인다
- [ ] (팀) AI: `dev` 브랜치 생성 → dev push 빌드 추가 → main은 BE와 같이 태그만 붙이기
- [ ] FE: `develop` push 때 컨테이너 이미지 빌드(dev는 V1 Compose라 컨테이너가 필요). prod용 `releases/<sha>/` S3 업로드와 `_complete`도 함께 만든다
- [ ] (팀) FE: API 주소를 런타임 `config.json`으로 읽을 수 있는지. 안 되면 환경별 두 벌 빌드
- [ ] (팀) BE: worker·sse 이미지를 나눌지. 나누면 빌드와 ECR 저장소 추가, `EcrRepositories`에 추가
- [ ] main 출발 브랜치 검사 workflow: PR의 head가 `dev` 또는 `hotfix/*`가 아니면 실패. GitHub 규칙에는 출발 브랜치 제한 옵션이 없어 필수 check로 대신한다
- [ ] (설정) 앱 저장소 3곳 main Ruleset: PR 필수, 위 check 필수, 직접 push·force push 금지. 저장소 관리자 권한 필요
- [ ] `feature/*` dev 임시 배포용 `workflow_dispatch`

**순서 주의.** main을 "태그만 붙이기"로 바꾸는 것은 dev 배포가 실제로 돈 뒤에 한다. 먼저 바꾸면 main에서 붙일 dev 이미지가 없어 운영 배포가 막힌다.
1. dev 빌드 추가 (지금 해도 무해)
2. Cloud dev 환경 활성화
3. 승격 1회 성공 확인
4. main을 태그만 붙이기로 전환

**dev와 prod를 나누는 세 겹.**
1. 앱 main 규칙: dev를 거치지 않은 코드를 막는다.
2. main CI 태그 붙이기: dev와 다른 코드의 이미지를 막는다. hotfix를 dev로 역병합하지 않으면 트리가 달라져 여기서 실패한다.
3. Cloud 승격 조건: dev에서 배포·검증하지 않은 이미지를 막는다.

### 단계 4 — 배포 workflow
- [ ] `deploy-ecs.yaml`: 레인별 concurrency, Migration Task, Service 갱신, 목표 Revision·rolloutState 확인, Smoke, last-good 기록
- [ ] `deploy-fe.yaml`: assets 복사 → index.html 교체 → invalidation → Smoke
- [ ] 실패 차단 상태와 Discord 알림

### 단계 5 — 트리거
- [x] `github-dispatch.yaml`에 ECR Image Action(PUSH·SUCCESS) 규칙 추가, 대상은 기존 Auto release API destination (V1 선적용, 10절)
- [x] release.sh가 진행 중인 앱 CI를 기다림 (이벤트가 CI 완료 직전에 오므로 필요, 10절)
- [ ] S3 `_complete` 이벤트 규칙 추가
- [ ] `EcrRepositories`에 V2 이미지 저장소(worker·sse 등) 추가
- [ ] PAT 호출 실패 알람(`AlertsTopicArn`) 연결 여부 확인
- [ ] retag가 ECR 이벤트를 만드는지 확인

### 단계 6 — 전환
- [ ] V1 인스턴스를 dev로 넘기기 전 정리
  - [ ] (설정) `/opt/keepgo/data/uploads`의 운영 사용자 업로드 파일을 운영 저장소로 옮기고 지운다
  - [ ] Secret을 운영 값에서 dev 값으로 교체
  - [ ] V1 인스턴스와 ECS 인스턴스(c7i·t3, x86)의 아키텍처가 같은지, BE·AI 이미지 빌드 플랫폼도 확인(FE는 amd64 확인함)
- [ ] dev 감시·알림: Health check 대상(`PUBLIC_ORIGIN`은 지금 하나뿐), dev Discord 알림, Sentry·Grafana 환경 구분
- [ ] dev에서 승격 흐름 시험. dev는 V1 인스턴스 Compose라 ECS 동작은 시험하지 못한다(4.8)
- [ ] prod ECS를 트래픽 전환 전에 무트래픽으로 배포·롤백 시험
- [ ] prod 전환: 트래픽을 EC2 → ALB/ECS로 옮기고, EC2 SSM 배포를 끈다(`AUTO_DEPLOY_ENABLED=false`)
- [ ] V1 `deploy-production.yaml`·`deploy.sh` 보관 처리

### 단계 7 — 문서
- [ ] technical-decisions에 TD 추가: V2 CD 방식, 이벤트 트리거, 저장소 분리 시점
- [ ] [V2 CI/CD 검토](v2-cicd-design-review.md) 8장 결정 상태 갱신
- [ ] 운영 절차: dev/prod 승격, feature 임시 배포, 핫픽스, PAT 교체

## 7. 확인할 것

| 항목 | 누구 | 영향 |
| --- | --- | --- |
| Backend·Worker·SSE 이미지를 나눌 수 있는지, 최소한 SSE 분리 | BE | 이미지가 하나면 Backend 배포마다 SSE 연결이 모두 끊긴다 |
| FE API 주소를 런타임 `config.json`으로 바꿀 수 있는지 | FE | 안 되면 환경별 두 벌 빌드 |
| DB 스키마를 바꾸는 저장소가 BE뿐인지 | BE·AI | AI도 바꾸면 저장소 간 Migration 잠금 필요 |
| ECR retag가 PUSH 이벤트를 만드는지 | 클라우드 | 안 되면 prod 반영이 최대 10분 |
| PAT 호출 실패 알람 연결 상태 | 클라우드 | 만료 시 조용히 멈춘다 |
| 지금 개발서버가 개발 브랜치를 받을지 | 클라우드·팀 | 바꾸면 `sources.json`과 FE CI 수정 |
| dev DB·Secret 분리 방식(전용 RDS, 같은 RDS에 DB만 분리) | 클라우드 | 비용과 운영 데이터 보호 |
| dev 도메인과 접근 제한 | 클라우드 | DNS·TLS·보안 그룹 |
| dev 알림·감시 범위 | 클라우드 | Discord 소음, Health check 대상 |
| AI `dev` 브랜치를 만들 시점 | AI | 그 전에는 AI가 dev 환경에서 빠진다 |

## 8. 감수하는 것과 재검토

| 감수하는 것 | 대응 |
| --- | --- |
| Cloud 저장소·EventBridge가 단일 장애 지점 | 10분 조회 안전망, 호출 실패 알람 |
| PAT가 개인 계정에 묶이고 만료됨 | 소유자·만료일 기록, 만료 전 교체([운영 절차 11절](v1-operations.md)) |
| dev 배포 커밋으로 이력이 늘어남 | 경로로 걸러 보고 V3에서 분리 |
| main 보호 없음 | 4.7의 Ruleset 선택 적용 |
| dev 전체를 main으로 옮기는 브랜치 모델 | 작고 잦은 반영, feature flag |

**재검토 조건**

- GitHub App 발급이 가능해지면 App 토큰과 필수 check로 바꾼다(TD-017 재검토와 같다).
- 레인을 나눠도 배포 대기나 Cloud 저장소 장애가 실제 문제가 되면 의존이 적은 FE부터 독립 CD로 뗀다.
- 브랜치 어긋남이나 미완성 기능 반영이 반복되면 트렁크 방식(main → dev 자동, 승격 버튼)을 검토한다.

## 9. V3 전환 시

- `deployment/envs/`를 `git filter-repo`로 GitOps 저장소에 옮긴다.
- 형식을 Helm values 또는 Kustomize로 바꾸고, ArgoCD Application을 환경 디렉터리에 연결한다.
- 트리거는 ArgoCD Image Updater(ECR 조회 → GitOps 저장소 커밋, 저장소 하나에만 쓰는 deploy key)를 우선 검토한다. 맞지 않으면 App CI가 deploy key로 digest를 커밋한다.
- V2 배포 workflow는 폐기한다. 출처 검증·승격 조건은 GitOps 저장소의 PR 검사로 옮긴다.
- App CI(ECR push·retag)와 브랜치 규칙은 그대로 쓴다.

## 10. V1 선적용 — ECR push 이벤트로 즉시 조회

> 2026-10-08 적용. V2 인프라 전에 지금의 V1 인스턴스에서 새 이미지 반영 지연(최대 10분)만 없앤다. 환경 분리(4.8)는 하지 않는다.

### 10.1 동작

```text
앱 CI ── 이미지 push ──▶ ECR
                          │ ECR Image Action (PUSH·SUCCESS), AWS 기본 이벤트 버스로 자동 발행
                          ▼
EventBridge 규칙 keepgo-v1-auto-release-on-ecr-push   (+ 안전망: 10분 주기 규칙)
                          │ 기존 API destination·PAT 연결 (Actions 전용)
                          ▼
Cloud Auto release (workflow_dispatch) ── concurrency: 실행 1 + 대기 1
  release.sh
    1차: 저장소마다 main head ↔ Manifest 비교
         CI 성공·이미지 게시 job 성공 → Manifest PR 병합
         CI 진행 중 → 대기 목록
         CI 없음·실패·게시 생략 → 건너뜀
    2차: 대기 목록만 15초마다 다시 확인, 실행 전체 합쳐 최대 180초
         (넘기면 다음 이벤트나 10분 조회가 처리)
  병합이 있으면 → Deploy production → SSM → EC2 deploy.sh (지금과 같음)
```

- 이벤트는 "지금 조회하라"는 신호다. 무엇을 배포할지는 지금과 같이 `release.sh`가 판단한다. `AUTO_DEPLOY_ENABLED`도 그대로 적용된다.
- 앱 CI와 앱 저장소 설정은 바꾸지 않는다. 모든 앱 CI가 이미 ECR에 push하고, 이벤트는 AWS가 만든다.
- **CI 완료를 기다리는 이유.** push는 CI job 중간(push step)에서 일어나므로 이벤트가 CI 완료보다 몇 초~수십 초 먼저 온다. `release.sh`는 CI 성공과 게시 job 성공을 모두 확인한 이미지만 배포하므로(TD-009 조건 유지), 기다리지 않으면 이벤트로 시작한 조회가 대부분 "아직 없음"으로 끝난다. FE는 이미지 두 개를 차례로 push한다.
- 다른 저장소를 먼저 처리한 뒤 기다리므로, CI가 진행 중인 저장소가 다른 저장소의 반영을 막지 않는다.
- 다른 브랜치 push(예: BE `dev`)도 이벤트를 만든다. main head가 그대로라 조회만 하고 끝난다.

### 10.2 이전 결정과의 관계

**10분 지연이 있었던 이유.** 즉시 반영하려면 Cloud workflow를 실행할 자격 증명(개인 PAT)을 앱 저장소나 AWS 어딘가에 둬야 했다. 10분 조회는 기본 `GITHUB_TOKEN`만으로 돌아간다. 9/29에는 "PAT을 만들지 않는 대신 지연을 감수한다"가 실질적인 이유였다. 9/30에 schedule 장애로 PAT을 AWS에 넣으면서 이 이유는 사라졌다. 그 뒤 지연이 남은 것은 다시 검토하지 않았기 때문이다.

| 시점 | 내용 |
| --- | --- |
| TD-009 (2026-09-29) | "누가 새 이미지를 판단하나"를 정했다. **Cloud 조회**를 택했다. 즉시 반영 대안은 앱 CI가 Cloud에 PR을 만드는 방식뿐이었는데, 앱 CI 3곳 수정, 저장소마다 Cloud 쓰기 토큰, 동시 PR 충돌, 누락 재처리가 필요했다. 당시 전제는 개인 PAT 없이 `GITHUB_TOKEN`만 쓰는 것이었다 |
| TD-022 (2026-09-30) | 이 조직에서 GitHub schedule이 돌지 않아, EventBridge가 Actions 전용 PAT로 workflow를 호출하게 했다. 범위를 "실행 수단만 교체"로 좁혀 즉시 반영은 다시 보지 않았다 |
| 이번 (2026-10-08) | TD-022의 연결이 생긴 뒤에는 **ECR 이벤트 → 같은 연결**로 앱 CI 수정 없이 조회를 바로 시작할 수 있다. 규칙 하나와 CI 완료 대기만 추가했다 |

- **TD-009의 판단은 유지된다.** 판단 주체는 여전히 Cloud 조회다. 그래서 TD-009가 피한 앱 CI 수정, 앱 저장소 토큰, 동시 PR 충돌, 누락 재처리를 이번에도 피한다. 바뀐 것은 조회를 시작하는 시점뿐이다.
- **놓친 점.** 9/29 비교표에는 GitHub 안의 방법만 있었고 "조회는 그대로, 시작 신호만 AWS 이벤트로" 하는 조합이 없었다. 이 조합은 PAT 하나가 필요했는데, 당시는 PAT을 쓰지 않는 것이 전제였다. 9/30 PAT을 받아들인 뒤에도 다시 보지 않아 지연이 8일 더 남았다. **교훈:** 전제(여기서는 "PAT 없음")가 바뀌면 그 전제로 기각했던 대안을 다시 본다.

### 10.3 결정

| 항목 | 결정 | 이유 |
| --- | --- | --- |
| 트리거 | ECR push 이벤트 + 10분 조회 유지 | 이벤트로 지연을 없애고, 조회로 유실·대기 초과를 다시 잡는다 |
| 토큰 | 기존 Actions 전용 PAT·연결 재사용 | 새 자격 증명과 권한 범위가 늘지 않는다 |
| 앱 CI | 바꾸지 않음 | push가 이미 있고 이벤트는 AWS가 만든다 |
| CI 대기 | 2단계 처리, 실행 전체 공유 상한 180초, 15초 간격 | push step은 CI 끝부분이라 보통 수 초~수십 초면 끝난다. 상한을 공유해 한 실행이 길게 붙잡히지 않게 한다 |
| 대상 ECR 저장소 | 템플릿 파라미터 `EcrRepositories` | V2에서 이미지가 늘면 파라미터만 바꾼다 |
| Auto release 제한 시간 | 10분 → 15분 | 대기 상한 3분을 더한다 |
| `on.schedule` | 예비용으로 남기고 주석 표시 | 조직에서 schedule이 복구되면 되돌릴 자리(TD-022) |

**10분 조회를 남기는 이유와 비용.** 하루 144회 실행, 회당 GitHub API 3~6회다. `GITHUB_TOKEN` 한도(저장소당 시간당 1,000회)에 비해 작다. 공개 저장소라 Actions 분 사용료가 없고, EventBridge 호출 비용도 무시할 수준이다. 반면 조회가 없으면 다음 두 경우의 버전은 같은 저장소에 다음 push가 올 때까지 배포되지 않는다.
1. 대기 상한(180초)을 넘긴 CI
2. 유실된 이벤트(GitHub API 장애, EventBridge 재시도 실패)

Actions 목록이 번잡하면 간격을 30분으로 늘릴 수 있다. `AutoReleaseSchedule`의 `rate`만 바꾸면 되고, 대신 놓친 버전의 반영이 최대 30분으로 늦어진다.

### 10.4 트레이드오프

| 얻는 것 | 감수하는 것 |
| --- | --- |
| 반영 지연: 최대 10분 → 수십 초 (CI 완료 + runner 시작) | `release.sh` 대기 로직이 늘었다. 상한을 넘기면 10분 조회로 넘어간다 |
| 앱 저장소·토큰 변경 없음 | PAT 의존이 더 커진다. 만료되면 이벤트와 조회가 함께 멈춘다. 기존 `DispatchFailureAlarm`과 교체 절차(운영 절차 11절)로 대응한다 |
| V2에서 그대로 쓴다(저장소 목록만 추가) | Auto release 실행 수가 push 수만큼 는다. concurrency로 쌓이지 않는다 |

### 10.5 동시 실행

| 상황 | 동작 |
| --- | --- |
| push가 연달아 와서 Auto release가 여러 번 호출됨 | `concurrency: auto-release`(cancel false)라 실행 1개와 대기 1개만 남는다. 매 실행이 전 저장소를 다시 보므로 대기 run이 교체돼도 빠지는 것이 없다 |
| 한 실행에서 여러 저장소를 병합 | `merge_release`가 매번 최신 origin/main에서 분기하므로 순서대로 병합된다. 배포는 실행 끝에 한 번 부른다 |
| 배포 중에 다음 배포 요청 | `keepgo-production-deployment`(cancel false)라 대기 1개만 남는다. 마지막 대기 run이 최신 main을 배포하므로 그 사이 병합분이 모두 들어간다. EC2 `deploy.sh`의 flock도 이중 실행을 막는다 |
| 2차 대기 중 다른 저장소 push | 다음 run이 대기했다가 이어서 처리한다. 추가 지연은 최대 180초다 |

### 10.6 적용과 확인

1. 코드(`release.sh`, `auto-release.yaml`, `github-dispatch.yaml`)를 main에 병합한다.
2. CloudShell(관리자 권한)에서 `keepgo-v1-github-dispatch` 스택을 갱신한다.
   - 기존 파라미터(`GitHubToken`·`AlertsTopicArn`)는 이전 값을 그대로 쓰고, `EcrRepositories`는 기본값을 쓴다.
   - 변경 세트에서 `AutoReleaseOnEcrPush` **Add** 하나만 있는지 확인한 뒤 실행한다.
   - 순서가 바뀌어 규칙이 먼저 켜져도 해는 없다. 이벤트로 시작한 조회가 CI 진행 중이면 건너뛰고, 10분 조회가 처리한다.
3. 앱 main에 병합하면 다음을 확인한다.
   - EventBridge → 규칙 `keepgo-v1-auto-release-on-ecr-push` → 모니터링의 `MatchedEvents`·`Invocations`
   - Actions의 Auto release가 수십 초 안에 시작되는지, 로그에 "CI가 진행 중이다 → 병합"이 남는지, Deploy production이 이어지는지
