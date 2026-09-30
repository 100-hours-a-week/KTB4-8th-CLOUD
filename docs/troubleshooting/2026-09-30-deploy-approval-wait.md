# 2026-09-30 첫 수동 배포가 13분 걸림 (승인 대기)

## 🐞 에러 내용

- main 병합 후 첫 Deploy production(#13)을 실행하자 "View pending deployments — production — Review needed from (팀원)"이 뜨고 배포가 시작되지 않았다.
- Actions 화면의 전체 시간이 13분으로 표시돼 배포가 느린 것처럼 보였다.

## 🔍 원인 분석

GitHub API로 job·step 시각을 조회했다(공개 레포라 인증 없이 가능).

```bash
curl -s "https://api.github.com/repos/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/<run_id>/jobs" \
  | jq -r '.jobs[] | "\(.created_at) \(.started_at) \(.completed_at)", (.steps[] | "  \(.name): \(.started_at) → \(.completed_at)")'
```

| 구간 (UTC) | 시간 |
| --- | --- |
| 요청 07:31:46 → job 시작 07:42:31 | **약 10분 45초 (승인 대기)** |
| 준비 (checkout·AWS 인증·SSM 전송) | 10초 |
| EC2 deploy.sh | 1분 52초 |

- 실제 배포는 약 2분이었다. EC2 시간도 대부분 healthy 대기와 재시작 관찰(`BAKE_SECONDS=60`)로, 의도한 대기다.
- 승인 요청은 Settings → Environments → production의 **Required reviewers** 설정 때문이었다. 기존 main의 수동 배포도 같은 Environment를 써서 예전부터 있던 설정이다. 새 workflow가 추가한 것이 아니다.
- 이 설정이 있으면 Auto release가 Manifest를 병합해도 배포가 매번 승인에서 멈춰 자동 배포가 반자동이 된다.

## ✅ 해결 방법

- 팀 결정으로 승인자를 제거했다([TD-020](../technical-decisions.md#td-020--production-environment-승인-제거)).
- 설정을 바꾸기 전에 대기 중이던 실행은 자동으로 풀리지 않을 수 있다. Cancel 후 다시 실행한다.

## 회고

- Actions 화면의 전체 시간에는 승인 대기가 포함된다. 느리다고 판단하기 전에 step별 시각을 본다.
- Environment 승인·보호 규칙·Actions 권한 같은 **GitHub 설정은 코드에 없다.** 체크리스트에 적어만 두고 실제 값을 확인하지 않은 채 첫 배포를 했다. 코드 밖 설정은 적용 전에 직접 열어 확인한다([체크리스트](../v1-remaining-checklist.md) 2절).
