# V1 중앙 자동 CD 전환 작업 목록

> **보관 기록 — 현재 실행 지침 아님.** 아래 내용은 당시의 제안·관찰·미완료 작업을 보존한 것이다. 현재 전 서비스 자동 CD의 [전체 설명](../v1-design.md)과 [운영 절차](../v1-operations.md)를 우선한다. 대체 이유는 [TD-008](../technical-decisions.md#td-008--최소-구성으로-재작성-전-서비스-자동-cd)에 있다.


> 범위: 현재 `EC2 + Docker Compose + ECR + SSM`을 유지하면서, App 이미지 게시 후 **Cloud Repo가 운영 배포를 자동 실행**하게 한다. ECS, Task Definition, Capacity Provider, S3/CloudFront 정적 Frontend는 V2 범위다.

## 1. 목표 흐름과 책임

```text
Frontend / Backend / AI Repo
  코드 PR: CI 통과 + 사람 코드 리뷰 → main 병합
  main CI: 테스트 → V1 linux/amd64 이미지 Build → 자기 ECR에 SHA Tag로 Push
           → Cloud Repo의 Manifest 갱신 PR 생성
                         ↓
Cloud Repo
  Manifest PR: 변경 범위·이미지 출처 검사 → 통과 시 자동 머지
  main 변경: 배포 잠금 → 바뀐 Compose 서비스만 SSM으로 EC2에 반영
             → Health/Smoke 확인 → 성공 기록 또는 이전 이미지 복구·알림
```

| 소유자 | V1에서 하는 일 | 하지 않는 일 |
| --- | --- | --- |
| 각 App Repo | 소스 검증, 이미지 Build/ECR Push, Cloud Manifest PR 생성 | 운영 EC2에 직접 SSM 배포 요청하지 않음 |
| Cloud Repo | `compose.yaml`, 목표 이미지 버전 Manifest, PR 검증·자동 머지, SSM/Compose 배포·복구 | App 소스나 이미지를 복사해 보관하지 않음 |

이 안은 **V1 중앙 자동 CD 제안**이다. [기존 책임 문서](ci-cd-repository-responsibilities.md)는 App Repo가 SSM 배포를 시작하는 **V1 독립 CD 대안**이고, [V2 CI/CD 검토 문서](../v2-cicd-design-review.md)는 **ECS 기반 미래 설계**다. 세 문서의 실행 주체를 섞지 않는다.

## 2. 먼저 확정할 결정

- [ ] V1에서는 `web`, `backend`, `worker`, `ai-api` 네 Compose 서비스를 그대로 사용한다. Backend Repo가 `backend`와 `worker` 이미지를 모두 게시하는지 확정한다. 두 이미지가 같은 Commit에서 함께 나가야 한다면 Manifest PR에서도 함께 변경한다.
- [ ] Cloud Repo 공개/비공개 여부와 GitHub 요금제를 확인한다. GitHub 기본 auto-merge는 공개 Repo의 Free, 비공개 Repo의 Pro/Team/Enterprise 등에서 제공된다. 미지원 시 요금제 변경 또는 필수 검사 후 API 머지 구현을 선택한다. **Merge Queue는 V1 필수가 아니다.**
- [ ] Cloud `main` 보호 규칙을 결정한다. 모든 PR에 사람 승인 1건을 필수로 걸면 Manifest PR도 무승인 자동 머지할 수 없다. Manifest-only PR의 자동 검증/머지와 `compose.yaml`·Workflow·배포 Script 변경의 사람 리뷰를 어떻게 구분해 강제할지 정한다. 봇에게 보호 규칙 우회 권한을 주지 않는다.
- [ ] `production` GitHub Environment의 필수 승인자가 일반 배포를 막고 있지 않은지 확인한다. 사람 리뷰는 App 코드 PR과 Cloud 플랫폼 코드 PR에 유지하고, 일상 이미지 배포에는 추가 승인을 두지 않는다.

## 3. Cloud Repo·AWS 작업

### 3.1 App Repo에서 Cloud Repo로 배포 후보 전달

- [ ] GitHub App을 등록해 Cloud Repo에 설치하고 브랜치 Push·PR 생성/머지에 필요한 최소 권한만 부여한다. App CI의 기본 `GITHUB_TOKEN`은 다른 Repo 수정 권한이 없다. App 키는 보호된 `main` CI에서만 사용한다. App Repo가 비공개라면 Cloud의 출처 검증에 필요한 App Repo/Actions 실행 결과 읽기 권한도 별도로 정한다.
- [ ] 서비스 매핑을 고정한다: `web → keepgo-web → images.web`, `backend → keepgo-backend → images.backend`, `worker → keepgo-worker → images.worker`, `ai-api → keepgo-ai → images.ai`.
- [ ] 각 App 팀에 `main` CI가 테스트 후 **40자리 Commit SHA Tag** 이미지를 자기 ECR에 게시하고 성공 Build Run·소스 SHA·ECR Repository를 남기도록 요청한다. PR CI나 실패 Build는 Manifest PR을 만들지 않는다. ECR Tag가 다른 이미지로 덮어쓰이지 않도록 불변성 설정도 확인한다.
- [ ] 성공한 App CI가 Cloud Repo에서 자기 서비스의 `deployment/production-manifest.yaml` 항목만 바꾸는 PR을 열도록 연결한다. 늦게 끝난 오래된 Build가 최신 후보를 덮어쓰지 않게 한다.

### 3.2 Manifest PR의 자동 머지 조건

- [ ] `.github/workflows/validate.yaml`을 모든 Cloud `main` PR에서 결과가 나오는 필수 `manifest-gate`로 확장한다. 실패·취소·검사 누락을 성공으로 취급하지 않는다.
- [ ] `manifest-gate`에서 허용된 PR 작성 App, 변경 파일·서비스 키, SHA 형식, App `main`의 성공 Build Run/Commit, 기대 ECR Repository의 이미지 존재, `docker compose config --quiet`를 검사한다. Workflow·Script·`compose.yaml` 등이 함께 바뀐 PR은 자동 머지 대상에서 제외한다.
- [ ] Cloud `main` 보호 규칙에 `manifest-gate`를 필수 Status Check로 등록하고 auto-merge를 켠다. GitHub App 권한으로 허용 PR에 `gh pr merge <PR번호> --auto --squash`를 실행한다. 검사가 실패하면 머지하지 않고 알린다.
- [ ] GitHub App이 머지한 Cloud `main` 변경으로 후속 CD Workflow가 실제 실행되는지 검증한다. Repo 기본 `GITHUB_TOKEN`이 만든 변경은 후속 Workflow 트리거가 제한될 수 있다.

### 3.3 수동 SSM/Compose를 중앙 자동 CD로 전환

- [ ] `.github/workflows/deploy-production.yaml`의 `workflow_dispatch`·`execute` 입력은 비상 복구용으로 분리하고, 일반 배포는 **검증된 Cloud `main` Manifest 변경**에서 자동 시작한다.
- [ ] Cloud Workflow의 AWS OIDC Role에 필요한 SSM 실행/조회 권한을 부여한다. App CI의 AWS Role은 자기 ECR Push만 허용하고 운영 EC2 SSM 권한은 제거한다. EC2 Instance Role에는 ECR Pull과 필요한 로그/비밀 조회 권한을 둔다.
- [ ] 운영 환경별 배포 잠금을 둔다. 목표 Cloud Commit/Manifest를 실행 시작 시 고정하고, EC2의 실제 운영 Tag와 비교해 변경 서비스만 계산한다. 이미 반영된 상태면 No-op으로 끝낸다. Pending Run이 생략될 수 있으므로 PR Diff만으로 대상 서비스를 정하지 않는다.
- [ ] 현재 `scripts/deploy.sh`는 모든 이미지를 Pull하고 `docker compose up -d --remove-orphans`를 수행한다. 일상 App 배포는 대상 이미지만 Pull한 뒤 `docker compose up -d --no-deps <service>`로 **변경 서비스만** 교체하도록 바꾼다. Compose/Script 변경은 별도 플랫폼 배포 경로로 처리한다.
- [ ] EC2 Runtime 경로에 적용된 SHA Tag와 이전 버전, 배포 이력을 보관한다. EC2 측 파일 잠금으로 Cloud CD·재시도·비상 복구의 동시 실행을 막는다. 비밀은 Runtime 버전 파일이나 Git Manifest에 기록하지 않는다.
- [ ] SSM 명령 성공 코드뿐 아니라 Container 기동·Health와 서비스별 외부 Smoke Test를 확인한다. 현재 `scripts/deploy.sh`의 안내문처럼 Health/Smoke가 없는 상태를 성공으로 처리하지 않는다.
- [ ] 실패하면 대상 서비스를 이전 SHA로 복구하고 Health/Smoke로 확인한다. 실패 SHA가 다음 CD에서 다시 배포되지 않게 차단하고, 실제 운영 버전과 Cloud Manifest가 달라졌다면 정합화 PR/검증·머지 또는 동등한 복구 절차를 수행한다. 복구 실패는 후속 자동 배포를 멈추고 알린다.
- [ ] SSM Timeout·GitHub Runner 중단 후에는 EC2의 실제 Container Tag와 상태를 다시 조회한다. Workflow 상태나 Manifest만 보고 운영 버전을 추정하지 않는다.

### 3.4 운영 안전장치와 App 팀 계약

- [ ] `web`, `backend`, `worker`, `ai-api` 각각의 Health/Smoke 기준과 종료 대기 시간을 App 팀과 합의한다. Web→Backend 외부 경로와 Backend→AI 내부 호출도 최소 한 번 확인한다.
- [ ] 배포 실패·Container 반복 종료·HTTP 5xx·AI Timeout·Worker 오류의 로그/알림 경로, 자동 배포 동결 스위치, 수동 복구 Runbook을 만든다.
- [ ] 이미지 배포와 DB Schema 변경의 순서를 Backend 팀과 합의한다. V1에는 ECS Migration Task가 없으므로 V2 절차를 그대로 가져오지 않는다. 이전 Backend/Worker 이미지로 돌아갈 수 있도록 Schema 하위 호환성을 유지한다.

## 4. 완료 판정 실험

| 실험 | 기대 결과 |
| --- | --- |
| App `main`의 정상 Build | ECR Push → Cloud PR → 검사 → 자동 머지 → 해당 Compose 서비스만 배포. 사람의 배포 승인 없음 |
| 실패 Build·없는 이미지·허용 외 파일 변경 | Cloud PR 미머지, EC2 변경 없음 |
| Cloud 플랫폼 코드 PR | Manifest 자동 머지 경로로 우회되지 않고 사람 리뷰 필요 |
| 거의 동시에 도착한 두 App 후보 | EC2 배포가 겹치지 않고 최종 Manifest와 실제 Tag가 일치 |
| 새 Container Health/Smoke 실패 | 이전 SHA로 복구, 실패 후보 재배포 차단, Manifest 정합화 |
| SSM 실패/Timeout·Runner 중단 | 성공으로 오인하지 않고 실제 상태 조회 후 재시도/복구 |

이미지 게시, 자동 PR, 자동 머지, 자동 SSM 배포, 실패 복구를 각각 실제로 검증해야 V1 중앙 자동 CD 완료로 판정한다.

## 5. V2와 섞지 않을 것

- V1 Frontend는 `compose.yaml`의 **Nginx Web 이미지**다. V2의 `S3 + CloudFront` 정적 웹이 아니다.
- V1은 **EC2 + Compose + SSM + SHA 이미지 Tag**다. V2의 ECS Service/Task Definition/Capacity Provider/롤링 배포·digest Manifest는 V1 완료 조건이 아니다.
- 이 문서는 [V1 독립 CD 책임 문서](ci-cd-repository-responsibilities.md)의 **대안**이며, 현재 실제 Workflow는 여전히 수동 실행이다. 한 방식을 채택하면 README와 책임 문서에 채택·폐기 상태를 표시한다.

### 기능·요금 확인

- [다른 Repo에 접근하는 GitHub App 토큰](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow)
- [GitHub auto-merge의 제공 요금제와 필수 조건](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request)
- [기본 `GITHUB_TOKEN`의 후속 Workflow 트리거 제한](https://docs.github.com/en/actions/concepts/security/github_token)
- [GitHub Actions 실행 시간 과금](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
