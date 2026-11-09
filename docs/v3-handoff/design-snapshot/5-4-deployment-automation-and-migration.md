> **위키 사본(스냅샷)** — 원본: [5‐4.-배포-자동화-및-전환-전략](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%904.-%EB%B0%B0%ED%8F%AC-%EC%9E%90%EB%8F%99%ED%99%94-%EB%B0%8F-%EC%A0%84%ED%99%98-%EC%A0%84%EB%9E%B5)  
> 기준: 위키 커밋 `addfeea`(2026-11-04), 복사 2026-11-09. **수정은 위키에서 하고, 바뀌면 이 사본을 다시 복사한다.**

## 1. 문서 목적

본 문서는 코드 변경이 운영 환경에 반영되는 배포 과정과,
기존 ECS 환경에서 EKS로 전환하는 절차를 정의한다.

GitHub Actions, ECR, Helm 및 Argo CD를 연결하여 이미지 빌드부터
배포 설정 변경, 승인, 클러스터 반영 및 배포 결과 확인까지의
책임과 처리 순서를 명확히 한다.

운영 배포는 새 Pod의 실행 여부뿐 아니라 요청 처리 상태와
주요 기능의 정상 동작을 기준으로 성공 여부를 판단한다.
문제가 발생한 경우에는 이전 이미지와 설정으로 복구하는 절차를 정의한다.

ECS에서 EKS로의 전환은 신규 환경 검증, 트래픽 전환,
데이터 호환성 확인 및 복귀 절차를 포함하여 계획한다.

### 이 문서에서 결정할 사항

- 서비스 소스와 배포 설정의 Repository 관리 방식
- CI와 GitOps 기반 CD의 역할 분담
- 환경별 설정, 배포 승인 및 성공 판정 기준
- 배포 실패 시 롤백과 데이터 변경 처리
- ECS에서 EKS로의 전환 순서 및 복귀 조건

## 1. 개발서버

#### 1차 주장 : k3s - 개발서버로 운용

`기능테스트만 가능하면 되는데 왜 쿠버네티스 환경인가요?`

아닌거 같음…

# 5-4. 배포 전략 설계

## 1. 목적과 전제

코드 변경이 EKS에 반영되는 경로와, 배포가 실패했을 때 되돌리는 방법을 정한다.

**5-1에서 정한 GitOps 방향**

- Argo CD가 Git의 설정과 클러스터 상태를 비교해 맞춘다.
- 변경은 Git에서 검토하고 이력을 남긴다.
- 각 팀은 허용된 범위에서 이미지 버전과 워크로드 설정을 바꾼다.
- 플랫폼팀은 공통 배포 템플릿과 기본 정책을 관리한다.

**전제**

| 항목 | 기준 |
| --- | --- |
| 환경 | dev, prod |
| backend 저장소 | 모노레포. auth-api, member-api, youtube-api, youtube-analysis-worker, wishlist-api, chat-api, recommend-api (Spring Boot) |
| ai 저장소 | ai-api (FastAPI) |
| frontend 저장소 | web (Next.js) |
| CI | GitHub Actions |
| 이미지 저장소 | Amazon ECR |
| CD | Argo CD + Helm |
| 롤아웃 | RollingUpdate (5-3 5.3) |

## 2. 전체 배포 흐름

1. 개발자가 앱 저장소에 PR을 올리면 GitHub Actions가 테스트를 돌린다.
2. main에 merge되면 변경된 서비스만 이미지를 빌드해 ECR에 푸시한다. 태그는 커밋 SHA다.
3. GitHub Actions가 GitOps 저장소의 dev values에 새 태그를 커밋한다.
4. dev의 Argo CD가 변경을 감지해 dev 클러스터에 반영한다.
5. dev에서 확인한 뒤, 같은 태그를 prod values로 올리는 PR을 만든다.
6. PR이 승인·merge되면 prod의 Argo CD가 prod 클러스터에 반영한다.

**원칙**

- 클러스터에 변경을 넣는 것은 Argo CD 하나다. CI는 클러스터 접근 권한이 없다.
- prod에는 dev에서 검증한 이미지를 다시 빌드하지 않고 그대로 올린다.
- 롤백도 Git 변경(revert)으로 한다.
- 클러스터에서 직접 `kubectl apply`로 바꾼 내용은 Argo CD가 Git 기준으로 되돌린다 (selfHeal).

## 3. 저장소 구성

| 저장소 | 내용 | 관리 주체 |
| --- | --- | --- |
| keepgo-backend | Spring Boot 서비스 7개, 공통 모듈 | 계정·회원, 콘텐츠·보관함, 채팅·추천, AI·영상 분석 팀 |
| keepgo-ai | ai-api | AI·영상 분석 팀 |
| keepgo-frontend | web | 프론트엔드 팀 |
| keepgo-gitops | Helm 차트, 환경별 values, Argo CD 설정, 클러스터 공통 컴포넌트 | 플랫폼팀 (서비스 values는 각 팀) |

### 3.1 GitOps 저장소를 따로 두는 이유

- 앱 코드 이력과 배포 이력을 나눈다.
    - 언제 어떤 버전이 prod에 올라갔는지 GitOps 저장소 커밋만 보면 알 수 있다.
- CI는 GitOps 저장소에 태그만 커밋하고, 클러스터 권한은 갖지 않는다.
- 앱 저장소가 3개라서, 배포 설정을 한곳에 모아야 공통 템플릿을 같이 관리할 수 있다.
- 감수하는 점: 배포 한 번에 커밋이 두 번(앱 저장소, GitOps 저장소) 생긴다.

### 3.2 GitOps 저장소 구조

```
keepgo-gitops/
├── charts/
│   └── keepgo-app/              # 공통 애플리케이션 차트 (플랫폼팀)
├── apps/                        # Namespace별 디렉토리 (5-2 기준)
│   ├── account/
│   │   ├── auth-api/
│   │   │   ├── values.yaml      # 환경 공통 값
│   │   │   ├── values-dev.yaml  # dev 값, 이미지 태그 포함
│   │   │   └── values-prod.yaml # prod 값, 이미지 태그 포함
│   │   └── member-api/
│   ├── ingest/                  # youtube-api, youtube-analysis-worker
│   ├── content/                 # wishlist-api
│   ├── recommend/               # chat-api, recommend-api
│   ├── ai/                      # ai-api
│   └── frontend/                # web
├── platform/                    # 클러스터 공통 컴포넌트 (플랫폼팀)
│   ├── karpenter/
│   ├── keda/
│   ├── aws-load-balancer-controller/
│   ├── external-secrets/
│   ├── monitoring/
│   └── redis/                   # Namespace 확정 후 위치 조정
└── argocd/
    ├── projects/                # 팀별 AppProject
    └── applicationsets/         # apps/ 디렉토리 기준 Application 생성
```

### 3.3 변경 권한 (CODEOWNERS)

- `charts/`, `platform/`, `argocd/` → 플랫폼팀만 승인
- `apps/<namespace>/` → 해당 팀이 승인
- `apps/**/values-prod.yaml` → 해당 팀 + 플랫폼팀 공동 승인
    - prod의 Replica·Resources 변경은 Node 용량과 DB 커넥션 예산(5-3 3.4)에 영향을 주기 때문이다.

## 4. CI (GitHub Actions)

### 4.1 워크플로우

| 이벤트 | 동작 |
| --- | --- |
| 앱 저장소 PR 생성·갱신 | 테스트, 정적 분석, 이미지 빌드 확인 (푸시 안 함) |
| 앱 저장소 main merge | 변경된 서비스 이미지 빌드 → ECR 푸시 → dev values 태그 커밋 |
| prod 승격 (수동 실행) | 지정한 태그로 prod values 변경 PR 생성 |
| GitOps 저장소 PR | Helm 렌더링·스키마 검증 (4.6) |

### 4.2 모노레포 빌드 범위

- 서비스 디렉토리별 경로 필터로, 변경된 서비스만 빌드한다.
- 공통 모듈이 바뀌면 그 모듈을 쓰는 서비스를 모두 빌드한다.
- 서비스마다 워크플로우를 따로 만들지 않고, 한 워크플로우에서 matrix로 처리한다.

### 4.3 이미지 태그와 ECR

- 태그는 커밋 SHA를 쓴다. `latest`는 쓰지 않는다.
    - values에 적힌 태그만 보면 어떤 커밋이 배포됐는지 알 수 있다.
- ECR 저장소는 서비스별로 만들고, tag immutability를 켠다.
    - 같은 태그에 다른 이미지가 덮어써지지 않는다.
- Push할 때 이미지 스캔을 돌린다.
    - Critical 취약점이 있는 이미지는 prod 승격을 막는다.
- Lifecycle policy로 오래된 이미지를 정리한다.
    - prod로 승격할 때 같은 이미지에 `prod-<SHA>` 태그를 추가한다.
    - `prod-` 태그 이미지는 최근 N개를 남겨 롤백에 쓴다.
- Helm 차트도 ECR에 OCI 형식으로 올린다 (7장).

### 4.4 인증과 권한

- GitHub Actions는 OIDC로 IAM Role을 받는다. 장기 Access Key를 저장하지 않는다.
- CI용 IAM Role은 ECR push 권한만 가진다. EKS 접근 권한은 없다.
- GitOps 저장소 쓰기는 GitHub App 토큰으로 한다.
    - main 직접 push는 CI 봇의 dev 태그 커밋만 허용한다.
    - prod values는 PR로만 바꾼다.

### 4.5 빌드 방식

- Spring Boot: Gradle 빌드 후 이미지 생성 (Jib 또는 멀티 스테이지 Dockerfile 중 하나로 통일)
- FastAPI, Next.js: 멀티 스테이지 Dockerfile
- Gradle·Docker 레이어 캐시로 빌드 시간을 줄인다.

### 4.6 GitOps 저장소 CI

GitOps 저장소 PR에서 아래를 검증하고, 실패하면 merge를 막는다.

- `helm lint`, `helm template`으로 모든 서비스의 dev·prod 매니페스트를 렌더링
- kubeconform으로 Kubernetes 스키마 검증
- 필수 값 누락 확인 (Resources, Probe, 이미지 태그)
- 클러스터에 반영되기 전에 문법·스키마 오류를 걸러, Argo CD 동기화 실패를 줄인다.

## 5. 환경과 승격

### 5.1 환경 구성

| 항목 | dev | prod |
| --- | --- | --- |
| 클러스터 | 별도 EKS 클러스터 | 별도 EKS 클러스터 |
| 반영 방식 | main merge 시 자동 | PR 승인 후 |
| 규모 | 최소 Replica 1, Spot 위주, 야간·주말 축소 | 5-3 정책 그대로 |
| 데이터 | dev 전용 RDS·SQS·Redis | prod 전용 |
| 용도 | 기능 확인, 장애 주입 실험, 플랫폼 컴포넌트 업그레이드 사전 검증 | 운영 |

**dev를 EKS로 두는 이유**

- 기능 개발과 테스트는 로컬(docker-compose, Testcontainers)에서 한다. dev 클러스터는 merge된 코드만 받는다.
- dev는 prod에 올라갈 배포 구성을 먼저 검증하는 곳이다.
- 아래 정책은 EKS와 AWS에 묶여 있어서 EKS에서만 확인할 수 있다.
    - ExternalSecret + Pod Identity로 Secrets Manager 접근
    - ALB Ingress, SSE idle timeout
    - VPC CNI NetworkPolicy
    - Karpenter NodePool, Spot 중단, Consolidation
    - KEDA SQS 확장
    - Redis EBS PVC와 AZ 종속성
- dev가 EKS가 아니면 위 정책이 prod에서 처음 실행된다.
- 장애 주입 실험과 EKS·Add-on 업그레이드 사전 확인도 dev에서 할 예정이다.

**클러스터를 나누는 이유**

| 방식 | 장점 | 단점 |
| --- | --- | --- |
| 클러스터 분리 | 클러스터 단위 컴포넌트(Karpenter, KEDA, Argo CD, CRD)를 dev에서 먼저 업그레이드해 볼 수 있음, 장애 주입 실험이 prod에 영향 없음, IAM·네트워크 권한이 환경별로 나뉨 | EKS Control Plane 비용 2배, 관리할 클러스터가 둘 |
| 한 클러스터에서 Namespace로 분리 | 비용·관리 대상 감소 | 클러스터 단위 컴포넌트를 따로 시험할 수 없음, dev 실험이 prod Node·Karpenter에 영향 |
- FIS 장애 주입과 노드 교체 실험을 하기로 했으므로, prod와 분리된 클러스터가 필요하다.
- dev는 규모를 작게 유지해 비용을 줄인다.

### 5.2 승격 절차

1. main merge → dev 자동 배포
2. dev 확인: Argo CD 상태 Healthy, 스모크 테스트(헬스체크, 주요 API) 통과
3. prod 승격 워크플로우 실행 (서비스와 태그 지정)
4. CI가 values-prod.yaml 태그 변경 PR을 만들고, 이미지에 `prod-<SHA>` 태그를 추가
5. 해당 팀 + 플랫폼팀 승인 후 merge
6. prod Argo CD 동기화, RollingUpdate 진행
- 이미지를 다시 빌드하지 않으므로 dev에서 확인한 이미지와 prod 이미지가 같다 (digest 동일).
- 환경 간 차이는 values-dev/prod, ConfigMap, Secret으로만 둔다.
- API 호환성이 바뀌는 변경은 관련 서비스를 한 PR로 묶어 승격한다.
    - 순서가 필요하면 호출받는 서비스를 먼저 올린다.

## 6. Argo CD 구성

### 6.1 배치

클러스터마다 Argo CD를 하나씩 둔다.

| 방식 | 장점 | 단점 |
| --- | --- | --- |
| 클러스터별 Argo CD | 클러스터 간 자격 증명 불필요, Argo CD 업그레이드를 dev에서 먼저 검증, 한쪽 장애가 다른 쪽 배포에 영향 없음 | 관리할 Argo CD가 2개 |
| 허브 1개가 두 클러스터 관리 | 화면 하나에서 전체 확인 | 허브에 다른 클러스터 관리자 권한이 몰림, 허브 장애 시 두 환경 모두 배포 불가 |
- Argo CD는 System용 Managed Node Group에 둔다 (5-3 6.3).

### 6.2 Application 생성 (ApplicationSet)

- `apps/<namespace>/<service>/` 디렉토리마다 Application을 자동으로 하나씩 만든다.
- 서비스를 추가할 때 디렉토리만 만들면 된다.
- 각 Application은 아래를 조합한다.
    - 공통 차트 (ECR OCI)
    - 서비스의 `values.yaml` + `values-<env>.yaml`

### 6.3 AppProject와 권한

- 팀(Namespace)별로 AppProject를 만든다.
    - sourceRepos: GitOps 저장소, ECR 차트 저장소만 허용
    - destinations: 자기 Namespace만 허용
    - 클러스터 범위 리소스(ClusterRole, CRD, Namespace 등) 생성 금지
- platform AppProject만 클러스터 범위 리소스를 만들 수 있다.
- Argo CD 로그인은 GitHub SSO로 하고, 권한은 팀 단위로 준다.
    - 각 팀: 자기 Project의 조회, 수동 sync, 로그 확인
    - 플랫폼팀: 전체 관리

### 6.4 동기화 정책

| 설정 | dev | prod |
| --- | --- | --- |
| automated sync | 켬 | 켬 (승인은 PR merge 단계에서 함) |
| selfHeal | 켬 | 켬 |
| prune | 켬 | 켬 (삭제 보호 리소스 제외) |
| 실패 시 재시도 | backoff 재시도 | backoff 재시도 |
- prune을 켜면 Git에서 지운 리소스가 클러스터에서도 지워진다.
    - Redis PVC처럼 지워지면 안 되는 리소스에는 `argocd.argoproj.io/sync-options: Prune=false,Delete=false`를 단다.
- HPA/KEDA를 쓰는 서비스는 차트에서 `spec.replicas`를 렌더링하지 않는다.
    - Git 값과 오토스케일러가 정한 값이 서로 덮어쓰지 않게 하기 위해서다.

### 6.5 동기화 순서 (Sync Wave)

1. platform: CRD와 컨트롤러 (Karpenter, KEDA, External Secrets Operator, AWS LB Controller)
2. Namespace 단위 정책: ResourceQuota, LimitRange, NetworkPolicy
3. ExternalSecret, ConfigMap
4. DB 마이그레이션 Job (PreSync, 8.3)
5. Deployment, Service, HPA/ScaledObject, PDB
- CRD가 없는 상태에서 ScaledObject를 만들면 실패하므로 platform을 먼저 반영한다.

### 6.6 알림

- Argo CD Notifications로 Slack에 보낸다.
    - sync 실패
    - Health가 Degraded로 바뀜
    - prod sync 완료
- 알림에는 서비스, 환경, 이미지 태그, 커밋 링크를 넣는다.

## 7. Helm 차트 설계

### 7.1 공통 차트 하나로 관리

- 서비스별 차트를 따로 만들지 않고, 공통 차트 `keepgo-app` 하나를 values로 나눠 쓴다.
- 이유
    - 9개 서비스의 Deployment 구조가 거의 같다.
    - 5-3 정책(Probe, preStop, RollingUpdate, Topology Spread)을 한곳에서 기본값으로 강제할 수 있다.
    - 팀이 늘어도 values 파일만 추가하면 된다 (5-1 운영 표준화 요구).
- Redis는 구조가 달라서 별도 차트로 관리한다.

### 7.2 차트가 만드는 리소스

| 리소스 | 생성 조건 | 비고 |
| --- | --- | --- |
| Deployment | 항상 | 5-3 기본값 내장 |
| Service | HTTP 서비스 | 세부 설계는 네트워크 문서를 따름 |
| Ingress / HTTPRoute | 외부 노출 서비스 | 네트워크 문서 확정 후 추가 |
| HPA | `autoscaling.type: hpa` | auth, member, youtube, wishlist |
| KEDA ScaledObject | `autoscaling.type: keda` | chat, recommend, ai-api, worker |
| PDB | 최소 Replica 2 이상 | `maxUnavailable: 1` (5-3 6.9) |
| ServiceAccount | 항상 | EKS Pod Identity로 서비스별 IAM Role 연결 |
| ConfigMap | 설정이 있을 때 |  |
| ExternalSecret | 비밀이 있을 때 | Secrets Manager에서 가져옴 |
| NetworkPolicy | 항상 | 규칙은 네트워크 문서를 따름 |

### 7.3 차트에 넣는 기본값 (5-3 정책)

- RollingUpdate `maxUnavailable: 0`, `maxSurge: 1`
- `preStop` 지연, `terminationGracePeriodSeconds`
- Probe 프리셋: spring(Actuator 경로), fastapi, nextjs
- Topology Spread: Node 기준 Soft, 핵심 API는 AZ 기준 Hard 옵션
- PriorityClass
- `progressDeadlineSeconds` (9장)
- Resources는 기본값을 두지 않고 `required`로 강제한다.
    - values에 없으면 렌더링이 실패해 4.6 CI에서 걸린다.

### 7.4 값의 소유

| 구분 | 값 |
| --- | --- |
| 각 팀 (자기 values) | 이미지 태그, 환경 변수·설정, Resources, 최소·최대 Replica, 확장 임계값 |
| 플랫폼팀 (차트) | Probe·종료 절차 기본값, 배포 전략, securityContext, 공통 라벨, NodePool 배치 규칙 |
- prod values의 Resources·Replica 변경은 공동 승인한다 (3.3).
- 팀이 차트 기본값을 바꿔야 하면 차트 PR로 요청한다.

### 7.5 차트 버전 관리

- 차트는 바꿀 때마다 버전을 올려 ECR에 OCI로 올린다.
- 환경별로 사용할 차트 버전을 고정한다.
    - 새 차트는 dev에 먼저 적용하고, 문제가 없으면 prod 버전을 올린다.
- 이유: 9개 서비스가 차트 하나를 같이 쓰므로, 버전 고정 없이 바꾸면 실수 하나가 모든 서비스에 바로 퍼진다.

### 7.6 설정 변경 반영

- ConfigMap·Secret이 바뀌어도 Pod는 자동으로 재시작되지 않는다.
- 차트에서 ConfigMap 내용의 checksum을 Pod annotation에 넣어, 값이 바뀌면 롤링 재시작되게 한다.
- ExternalSecret으로 받는 Secret은 갱신 시점이 Git 변경과 무관하므로, Reloader 같은 도구를 쓸지 따로 정한다 (12장).

## 8. 롤아웃 방식

### 8.1 롤아웃 방식 선택

| 방식 | 막을 수 있는 장애 | 필요한 것 |
| --- | --- | --- |
| RollingUpdate | 새 버전 기동 실패, Readiness 실패 | 추가 구성 없음 |
| Blue/Green (Argo Rollouts) | 위 + 전환 직후 문제 시 즉시 복귀 | 배포 중 Pod 2배, Service 전환 |
| Canary (Argo Rollouts) | 위 + 일부 트래픽에서 먼저 오류 발견 | 트래픽 비율 제어(ALB 가중치 등), 자동 분석 지표 |

**KeepGo 워크로드별로 보면**

| 워크로드 | Blue/Green | Canary | 판단 |
| --- | --- | --- | --- |
| 일반 HTTP API (auth, member, youtube, wishlist) | 적용 가능 | ALB 가중치로 적용 가능 | 효과는 있으나, 기동 실패는 RollingUpdate로도 막힘 |
| SSE (chat, recommend) | 전환 순간 모든 연결이 동시에 끊겨 재연결이 한꺼번에 몰림 | 가중치가 새 연결에만 적용돼, 비율이 기존 연결이 끝날 때까지 늦게 반영됨 | RollingUpdate가 재연결을 나눠 받아 더 유리함 |
| ai-api | Service 전환으로 적용 가능 | 내부 서비스라 ALB 가중치를 쓸 수 없음, Replica 비율로만 나눌 수 있어 정밀하지 않음 | 효과 낮음 |
| youtube-analysis-worker | SQS 소비자라 트래픽 전환 개념이 없음 | 동일 | 적용 대상 아님 |

**근거**

- 기동 실패는 RollingUpdate로 이미 막는다.
    - `maxUnavailable: 0` + Readiness + `progressDeadlineSeconds`로, 새 버전이 Ready가 안 되면 기존 버전이 그대로 처리한다 (9.2).
- Blue/Green·Canary가 추가로 잡는 것은 "기동은 됐지만 실제 트래픽에서 문제가 나는 경우"다.
    - KeepGo에서 이 위험이 큰 변경은 추천 로직, 프롬프트, AI 모델 변경이다.
    - 이런 문제는 응답 품질 저하로 나타나서 HTTP 오류율·지연 지표에 잘 드러나지 않는다. Canary 자동 분석으로 잡기 어렵다.
    - 해당 서비스(recommend-api, ai-api)는 SSE이거나 내부 서비스라 트래픽 비율을 정확히 나누기 어렵다.
- SSE 서비스에는 Blue/Green이 오히려 불리하다.
    - 전환 순간 재연결이 몰리면 KEDA 연결 수 지표가 급변하고, Redis·RDS 상태 조회가 한꺼번에 늘어난다.
- 따라서 RollingUpdate를 쓰고, 배포 후 문제는 9.4 확인과 Git revert로 대응한다.

**AI 응답 변경은 배포 전략 대신 기능 플래그로 다룬다**

- 프롬프트·모델 변경은 ai-api 설정값으로 켜고 끌 수 있게 만든다.
- 일부 사용자에게만 새 설정을 적용해 비교하고, 문제가 있으면 설정만 되돌린다.
- 이미지 재배포 없이 되돌릴 수 있어서, 같은 목적을 Canary보다 정확하게 달성한다.

**재검토 조건**

- 외부 HTTP API에서 Readiness는 통과했지만 배포 직후 오류율이 오르는 일이 반복될 때
    - 해당 서비스에만 ALB 가중치 Canary를 적용한다.

### 8.2 워크로드별 배포 시 동작

| 워크로드 | 배포 시 동작 | 관련 정책 |
| --- | --- | --- |
| 일반 API | 새 Pod Ready → 기존 Pod preStop 후 종료 | 5-3 4.5 |
| SSE (chat, recommend) | 기존 연결에 재연결 유도 후 종료, 클라이언트가 새 Pod로 재연결 | 5-3 4.5 |
| ai-api | 진행 중 요청 정리 후 종료 | 5-3 4.5 |
| Worker | 진행 중 작업 완료 시도, 미완료 메시지는 재처리 | 5-3 4.5 |
| Redis | 차트 변경 시에만 재배포, Replica 먼저 갱신 후 Primary 전환 | 5-3 6.5 |
- SSE 서비스는 배포할 때마다 연결이 한 번 끊긴다.
    - 사용자가 몰리는 시간대에는 prod 배포를 피한다.

### 8.3 DB 스키마 마이그레이션

- RollingUpdate 중에는 이전 버전과 새 버전이 같은 DB를 동시에 쓴다.
- 그래서 스키마는 이전 버전도 동작하는 방식으로만 바꾼다 (expand → contract).
    1. expand: 컬럼·테이블 추가 (기존 코드에 영향 없음)
    2. 새 코드 배포
    3. contract: 더 이상 안 쓰는 컬럼 제거는 다음 배포에서
- 도구: Flyway
    - 스크립트는 backend 모노레포의 서비스별 `db/migration` 디렉토리에 둔다.
    - 서비스마다 이력 테이블을 따로 둔다 (`flyway.table` 설정). 서비스별로 마이그레이션을 독립적으로 배포하기 위해서다.
    - 이미 적용된 스크립트는 고치지 않고, 변경은 새 버전 스크립트로 추가한다. 고치면 Flyway가 checksum 불일치로 실패시킨다.
- 실행 방식
    - Argo CD PreSync Hook Job으로 실행한다.
    - CI가 서비스 이미지를 빌드할 때, 같은 커밋의 스크립트로 마이그레이션 이미지도 같은 태그로 만들어 ECR에 올린다.
    - 앱 Pod는 `spring.flyway.enabled=false`로 기동 시 마이그레이션을 하지 않는다.
        - Replica 여러 개가 동시에 마이그레이션을 시도하고, 실패하면 모든 Pod가 기동에 실패하기 때문이다.
    - Job이 실패하면 sync가 멈추고 새 버전은 배포되지 않는다.
- 권한 분리
    - DDL 권한이 있는 DB 계정은 마이그레이션 Job에만 준다.
    - 앱 계정은 DML 권한만 갖는다.

## 9. 배포 실패와 롤백

### 9.1 실패 감지

- Deployment에 `progressDeadlineSeconds`를 둔다.
    - 기본값 600초에서 시작하고, Spring 서비스 기동 시간을 측정해 조정한다.
- 이 시간 안에 새 Pod가 Ready가 되지 않으면 Deployment 상태가 `Progressing=False`가 된다.
- Argo CD는 이를 Degraded로 표시하고 Slack 알림을 보낸다 (6.6).

### 9.2 상황별 동작

| 상황 | 시스템 동작 | 서비스 영향 | 대응 |
| --- | --- | --- | --- |
| 새 버전 Readiness 실패 | `maxUnavailable: 0`이라 기존 Pod 유지, 롤아웃 멈춤, deadline 초과 시 Degraded | 없음 (기존 버전이 처리) | Git revert |
| 새 버전 기동 직후 크래시 | CrashLoopBackOff, 기존 Pod 유지 | 없음 | Git revert, 로그 확인 |
| Image Pull 실패 | 새 Pod ErrImagePull·ImagePullBackOff, 기존 Pod 유지 | 없음 | 태그·ECR 권한 확인 |
| 리소스 부족으로 새 Pod Pending | maxSurge Pod가 Pending, 기존 Pod 유지, Karpenter가 Node 생성 시도 | 없음, 배포 지연 | NodePool Limits·ResourceQuota 확인 |
| Helm 렌더링 오류 | Argo CD sync 실패, 클러스터 변경 없음 | 없음 | 4.6 CI에서 대부분 사전 차단 |
| 마이그레이션 Job 실패 | PreSync 실패로 sync 중단, 새 버전 미배포 | 없음 (일부 적용된 스키마 확인 필요) | 마이그레이션 수정 후 재배포 |
| ExternalSecret 동기화 실패 | 새 Pod가 Secret을 못 받아 기동 실패, 기존 Pod 유지 | 없음 | Secrets Manager 권한·키 확인 |
| 배포 성공 후 오류율 증가 | Readiness는 통과해 롤아웃 완료 | 있음 | Git revert로 이전 태그 배포 |
- Image Pull 실패는 드물다. CI가 ECR 푸시가 끝난 뒤에만 태그를 커밋하기 때문이다.
- 마지막 경우가 가장 위험하다. Readiness는 비즈니스 오류를 잡지 못하므로 9.4의 배포 후 확인이 필요하다.

### 9.3 롤백 방법

- 기본: GitOps 저장소에서 태그 변경 커밋을 revert
    - Argo CD가 이전 태그로 동기화한다.
    - 롤백도 Git 이력에 남는다.
    - 이전 이미지는 `prod-` 태그로 ECR에 남아 있다 (4.3).
- 긴급: Argo CD UI의 Rollback
    - auto-sync를 꺼야 동작한다. 켜 두면 Git 상태로 다시 돌아간다.
    - 쓴 뒤에는 바로 Git에 revert를 반영하고 auto-sync를 다시 켠다.
- `kubectl rollout undo`는 쓰지 않는다. selfHeal이 Git 상태로 되돌린다.
- DB 스키마는 되돌리지 않는다.
    - expand 단계 변경은 이전 버전과 호환되므로 코드만 되돌리면 된다.

### 9.4 배포 후 확인

prod sync가 끝나면 아래 지표를 일정 시간 확인한다.

- HTTP 오류율, 응답 지연 p95/p99 (5-3 7.2)
- Pod Restart, OOMKilled
- SSE 재연결 성공률 (chat, recommend)
- Worker 처리 실패, DLQ 메시지 증가

이상이 있으면 9.3의 기본 방법으로 롤백한다.

## 10. 보안

- 비밀 값은 Git에 두지 않는다.
    - Git에는 ExternalSecret 정의만 있고, 값은 Secrets Manager에 있다.
- CI는 OIDC로 인증하고 ECR push 권한만 가진다. 클러스터 접근 권한은 없다 (4.4).
- 이미지는 tag immutability, push 시 스캔, prod 승격 시 Critical 취약점 차단을 적용한다 (4.3).
- GitOps 저장소는 main을 보호하고 CODEOWNERS 승인을 거친다 (3.3).
- Argo CD는 SSO로 로그인하고, 팀별 AppProject로 배포 가능한 Namespace를 제한한다 (6.3).
- 사람은 클러스터에 직접 쓰지 않는다.
    - 팀의 Kubernetes 권한은 조회·로그 확인 위주로 두고, 쓰기는 Argo CD만 한다.
    - 세부 권한은 5-2 2.3 RBAC에서 확정한다.

## 11. 트레이드오프와 운영 비용

| 선택 | 얻는 것 | 감수하는 것 |
| --- | --- | --- |
| GitOps 저장소 분리 | 배포 이력이 명확함, CI에서 클러스터 권한 제거 | 배포마다 커밋 2번, 관리할 저장소 증가 |
| dev·prod 클러스터 분리 | 플랫폼 변경·장애 실험을 prod와 분리 | Control Plane 비용 2배, 클러스터 2개 업그레이드 |
| 클러스터별 Argo CD | 장애·권한 격리 | Argo CD 2개 운영·업그레이드 |
| 공통 Helm 차트 | 정책 표준화, 서비스 추가가 쉬움 | 차트 변경 영향 범위가 큼, 버전 고정 필요 |
| RollingUpdate | 단순함, 추가 컨트롤러 없음 | 일부 트래픽으로 먼저 검증할 수 없음 |
| PR 기반 prod 승격 | 리뷰와 이력 확보 | 긴급 수정도 PR 절차를 거쳐야 함 |

**새로 생기는 운영 작업**

- Argo CD, ApplicationSet, AppProject 설정과 업그레이드
- 공통 차트 유지보수와 버전 관리
- GitOps 저장소 CI 검증 규칙 관리
- ECR lifecycle 정책 관리, 이미지 스캔 결과 확인
- 클러스터 2개의 EKS·Add-on·플랫폼 컴포넌트 업그레이드 (dev 먼저)

