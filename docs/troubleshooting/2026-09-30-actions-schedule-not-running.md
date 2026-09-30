# 2026-09-30 GitHub Actions schedule이 한 번도 실행되지 않음

## 🐞 에러 내용

- 새 자동 CD를 main에 병합(07:12 UTC)한 뒤 **Auto release(10분마다)와 Health check(5분마다)가 schedule로 한 번도 실행되지 않았다.** 에러 메시지도, "skipped" 기록도 없이 실행 목록 자체가 비어 있었다.
- 수동 실행(Run workflow)과 push 트리거는 정상이었다. 수동으로 돌린 Auto release #2는 FE·AI 릴리스 PR(#20·#21)을 만들고 배포까지 호출했다.
- 영향: 앱 파트가 main(FE는 `feat/v1`)에 병합해도 운영에 자동 반영되지 않았다. 외부 감시도 돌지 않아 장애가 나도 알림이 오지 않는 상태였다.

## 🔍 원인 분석

바깥에서 볼 수 있는 설정을 하나씩 확인했다. 모두 GitHub API(비로그인)로 조회했다.

| 확인 항목 | 방법 | 결과 |
| --- | --- | --- |
| 기본 브랜치에 workflow가 있나 | `repos/{r}` → `default_branch`, `git ls-tree origin/main .github/workflows` | `main`, 파일 4개 모두 있음 ✅ |
| workflow가 비활성화됐나 | `actions/workflows` → `state` | 모두 `active` ✅ |
| 파일 문법 오류 | push 실행 목록에서 "Invalid workflow file" 실패 확인 | 없음 ✅ |
| cron을 바꾼 커밋 계정 | `commits?path=...` → `author.login` | `gaamjaaa`로 연결됨 ✅ |
| GitHub 장애 | githubstatus.com API | Actions operational ✅ |
| `AUTO_DEPLOY_ENABLED` 등 변수 문제 | 변수 문제라면 "skipped" 실행이라도 남음 | 기록 자체가 0건이라 해당 없음 |
| 레포 전체 schedule 실행 | `actions/runs?event=schedule` | **처음부터 0건** |

재등록도 두 번 시도했지만 둘 다 효과가 없었다.

1. Actions에서 Disable → Enable workflow (08:42)
2. cron 값을 `*/10` → `7-59/10`, `*/5` → `2-59/5`로 바꿔 main에 병합 (#24, 09:02). 74분 동안 0건.

마지막으로 **원인을 가르는 실험**을 했다. 권한·변수·조건·동시성을 모두 뺀 최소 workflow(`schedule-probe.yaml`, 5분마다 날짜만 출력)를 main에 넣었다(#25, 10:20).

| 실험 | 결과 |
| --- | --- |
| probe 수동 실행 (대조군) | ✅ 10:21 성공 |
| probe schedule (10:25·10:30·10:35·10:40) | ❌ 0건 |

**결론:** 우리 workflow 코드 문제가 아니다. **이 레포 또는 `100-hours-a-week` 조직 차원에서 schedule 이벤트가 발생하지 않는다.** 정확한 원인(조직 정책, GitHub 내부 사정 등)은 조직 관리 권한이 있어야 확인할 수 있어 밝히지 못했다. 운영진에게 문의가 필요하다.

## ✅ 해결 방법

GitHub schedule에 의존하지 않고 **AWS EventBridge가 주기적으로 workflow를 실행**하게 했다([TD-022](../technical-decisions.md#td-022--github-schedule-대신-eventbridge로-주기-실행)).

- `infrastructure/github-dispatch.yaml` → 스택 `keepgo-v1-github-dispatch`
  - EventBridge 연결: GitHub 토큰을 `Authorization: Bearer` 헤더로 암호화 저장
  - API destination 2개: 각 workflow의 `workflow_dispatch` API
  - 예약 규칙 2개: `rate(10 minutes)` Auto release, `rate(5 minutes)` Health check
  - IAM 역할: 위 두 API destination 호출만 허용
  - 실패 알람(선택): 토큰 만료 등으로 호출이 실패하면 SNS
- 토큰: fine-grained PAT, 대상 레포 KTB4-8th-CLOUD 하나, 권한 **Actions Read and write만**. 대화·Git·GitHub Secrets에 넣지 않고 CloudShell에서 `read -rs`로 입력해 NoEcho 파라미터로만 전달했다.
- workflow 로직은 바꾸지 않았다. 배포 여부는 여전히 `AUTO_DEPLOY_ENABLED`가 결정한다.

적용 절차 (관리자 권한 CloudShell. EC2 SSM 세션은 `sh`이고 권한이 없어 실패했다):

```bash
read -rs TOKEN
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/100-hours-a-week/KTB4-8th-CLOUD/actions/workflows/auto-release.yaml/dispatches \
  -d '{"ref":"main","inputs":{"dry_run":"true"}}'      # → 204
curl -sO https://raw.githubusercontent.com/100-hours-a-week/KTB4-8th-CLOUD/feat/eventbridge-dispatch/infrastructure/github-dispatch.yaml
aws cloudformation deploy --region ap-northeast-2 --stack-name keepgo-v1-github-dispatch \
  --template-file github-dispatch.yaml --capabilities CAPABILITY_IAM --parameter-overrides GitHubToken="$TOKEN"
unset TOKEN
```

검증:

- 토큰 확인 dry_run → `204`, Auto release #3 실행
- 스택 생성 직후 Health check #1이 EventBridge로 실행돼 성공(13초)
- 목록에는 "Manually run by gaamjaaa"로 보인다. EventBridge가 토큰 소유자 이름으로 API를 호출하기 때문이며 정상이다.

## 회고

- **"당연히 동작한다"고 가정한 부분을 먼저 검증했어야 했다.** schedule이 도는지는 병합 직후 확인할 수 있었는데, 한 시간 넘게 "GitHub 지연"으로 보고 기다렸다. 설정을 모두 뺀 최소 재현(probe)을 처음부터 만들었다면 원인 범위를 훨씬 빨리 좁혔을 것이다.
- **재등록을 반복하는 것보다 대조 실험이 결정적이었다.** "우리 코드냐, 플랫폼이냐"를 한 번에 가를 수 있는 실험을 먼저 설계한다.
- **바깥에서 GitHub을 움직이려면 결국 토큰이 필요하다.** 조직 제약(App 발급 불가)이 있는 환경에서는 개인 PAT의 권한을 최소로 좁히고, 보관 위치(AWS)와 만료 대응(알람·교체 절차)을 함께 설계해야 한다.
- 주기 실행 방식은 기록이 많이 쌓인다(하루 약 430건). 의미 있는 기록(배포·릴리스·장애)을 어디서 보는지 정해 두는 것이 중요하다.

**남은 일**

- 운영진에게 조직 schedule 제한 여부 문의
- EventBridge 템플릿 PR(`feat/eventbridge-dispatch`) main 병합
- probe workflow 삭제
- 모니터링 스택을 만든 뒤 `AlertsTopicArn`을 채워 토큰 실패 알람 연결
- 토큰 만료일 기록, 만료 전 교체([운영 절차](../v1-operations.md) 11절)
