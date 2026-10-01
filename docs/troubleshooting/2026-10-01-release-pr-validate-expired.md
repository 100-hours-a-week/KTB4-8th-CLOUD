# 2026-10-01 release PR의 Validate가 매번 실패로 표시됨 (승인 만료)

## 🐞 에러 내용

- 자동 릴리스가 만든 PR #31(`release: frontend d11c424c0234`)의 Validate deployment #60이 **Failure**로 끝났다.
- Annotations: `This workflow run required approval but was not approved before it expired.`
- job(`Validate manifest and compose`)은 시작하지 않았다. 실행 시간·로그가 없다.
- 같은 시각의 Deploy production은 성공했다. 배포에는 영향이 없었다.

## 🔍 원인 분석

공개 API로 PR과 run 시각을 조회했다.

```bash
curl -s https://api.github.com/repos/100-hours-a-week/KTB4-8th-CLOUD/pulls/31 | jq '{created_at, merged_at}'
curl -s "https://api.github.com/repos/100-hours-a-week/KTB4-8th-CLOUD/actions/workflows/validate.yaml/runs?event=pull_request" \
  | jq -r '.workflow_runs[] | select(.actor.login == "github-actions[bot]") | "\(.run_number) \(.created_at) \(.conclusion) \(.display_title)"'
```

| 시각 (UTC) | 일 |
| --- | --- |
| 01:30:32 | release.sh가 PR #31 생성 |
| 01:30:34 | squash 병합 |
| 01:30:35 | Validate run 생성 → 승인 대기 → 곧바로 만료, Failure |
| 01:30:38 | Deploy production 실행, 성공 |

- `GITHUB_TOKEN`(`github-actions[bot]`)이 만든 PR의 `pull_request` workflow는 run은 생기지만 **사람이 승인해야 시작한다.**
- release.sh는 검사를 기다리지 않고 바로 병합한다([TD-017](../technical-decisions.md#td-017--자동-릴리스-pr-병합과-main-보호-규칙)). 그래서 Validate는 승인을 받지 못한 채 만료되고 Failure로 남는다.
- 처음 생긴 일이 아니다. 봇이 만든 release PR의 Validate **5건(#42·#43·#58·#59·#60)이 모두 같은 이유로 Failure**였다. 첫 자동 릴리스부터 매번 생겼는데 배포가 성공해서 지나쳤다.
- TD-017에는 "GITHUB_TOKEN PR에서는 Validate가 돌지 않는다"고 적혀 있었다. 실제로는 run이 생기고 실패로 기록된다. 이 차이를 처음부터 알았다면 대응했을 것이다.

**영향:** 배포에는 영향이 없다. Validate는 실제로 한 번도 실행되지 않았으니 검사 결과가 아니다. 다만 릴리스마다 빨간 X가 쌓여, 사람 PR의 진짜 Validate 실패와 섞여 보인다.

## ✅ 해결 방법

release.sh의 커밋 메시지에 `[skip ci]`를 넣어 release PR에서 Validate run 자체가 생기지 않게 했다(`scripts/release.sh`, `fix/release-skip-ci` 브랜치).

```bash
git commit --quiet -am "release: ${name} ${sha:0:12}" -m "[skip ci]"
```

- workflow에 `if: github.actor != 'github-actions[bot]'`를 넣는 방법은 쓰지 않았다. 승인 대기는 job 조건을 평가하기 전에 run 단위로 걸리기 때문이다.
- 잃는 검사는 없다. release PR이 바꾸는 것은 Manifest의 SHA 한 줄이다. 그 SHA는 다음 단계에서 검증한다.
  - 앱 CI와 이미지 게시 job의 성공 확인 (release.sh)
  - Validate와 같은 `check-manifest.jq` 형식 검사 (release.sh)
  - 이미지 pull, health 확인, 실패 시 롤백·차단 (deploy.sh)

  sources.json·compose·스크립트는 사람 PR의 Validate가 계속 검사한다.
- 나중에 GitHub App 토큰과 필수 check로 바꾸면 `[skip ci]`도 함께 뺀다. 남겨 두면 그때 살린 검사까지 건너뛴다(TD-017 재검토).

**확인 방법 (적용 대기):** 이 변경이 main에 병합된 뒤 다음 자동 릴리스에서 release PR에 Validate run이 생기지 않고, Deploy production은 그대로 실행되는지 본다.

## 회고

- **"배포는 성공했으니 괜찮다"며 빨간 X를 넘기면 안 됐다.** 실패 표시가 계속 쌓이면 진짜 실패를 알아보지 못한다. 실패가 무해하다면 무해하다고 판단하는 데서 끝내지 말고, 표시가 생기지 않게 정리한다.
- **문서에 적은 플랫폼 동작은 실제 기록과 대조한다.** "Validate가 돌지 않는다"는 설명과 실제(run이 생기고 만료로 실패)가 달랐다. 공식 문서를 읽고 정정까지 했으면서([TD-010](../technical-decisions.md#td-010--조회병합-로직을-어디에-쓸-것인가)) Actions 목록은 열어 보지 않았다.
