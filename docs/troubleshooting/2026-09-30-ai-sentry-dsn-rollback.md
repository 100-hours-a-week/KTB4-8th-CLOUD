# 2026-09-30 SENTRY_DSN 형식 오류로 AI 배포 자동 롤백

## 🐞 에러 내용

- 자동 릴리스가 AI를 `f7476b5`에서 `4bd2efc`로 올리는 배포(Deploy #15, 17:13 KST)에서 **ai-api가 시작하자마자 종료를 반복**했다. deploy.sh가 이전 버전으로 자동 복구하고 `4bd2efc`를 차단했다.

```text
[Deploy] ai-api: 4bd2efcd32d1로 교체
[Deploy] 검증 실패: ai-api가 300초 안에 healthy가 되지 않았다
keepgo-v1-ai-api-1 ... keepgo-ai:4bd2efc...   Restarting (1) Less than a second ago
ai-api-1  |   File "/app/app/main.py", line 16, in <module>
ai-api-1  |     sentry_sdk.init(dsn=settings.SENTRY_DSN, send_default_pii=False)
ai-api-1  | sentry_sdk.utils.BadDsn: Missing public key
[Deploy] ai-api: f7476b557775로 복구
[Deploy] 결과: rolled_back
```

- 서비스는 계속 이전 버전으로 정상 동작했다. 자동 복구에 성공한 경우는 설계상 Discord로 알리지 않아서([TD-013](../technical-decisions.md#td-013--장애-알림-자동-복구되지-않은-경우만-discord)) **아무도 모르게 지나갔다.**
- 그 사이 AI 설정 변경(PR #22, LangSmith)도 ai-api 차단 때문에 반영되지 않았다. 배포 결과는 `unchanged`로만 남았다(17:21).
- Actions 목록에는 실행자가 `github-actions[bot]`으로 보였다. Auto release가 기본 토큰(`GITHUB_TOKEN`)으로 release PR(#20·#21)을 병합하고 배포를 호출했기 때문이다. 외부 봇이 아니다.

## 🔍 원인 분석

**직접 원인:** `Secret-v1-AI`의 `SENTRY_DSN` 값에 공개 키가 없었다. Sentry DSN은 `https://<공개키>@o<숫자>.ingest.sentry.io/<프로젝트번호>` 형식이어야 한다. 새 AI 코드는 `SENTRY_DSN`이 비어 있지 않으면 앱을 불러오는 시점에 `sentry_sdk.init`을 호출하므로, 형식 오류가 곧 기동 실패가 됐다.

**왜 이 시점에 터졌나** — 서로 다른 세 변경이 겹쳤다.

| 시각 (KST) | 일 | 영향 |
| --- | --- | --- |
| 9/28 | AI 레포에 Sentry 적용 커밋(`8bd3c32`). 설정 주석에 "운영에서는 인프라가 환경변수로 주입한다" | 코드가 먼저 준비됨 |
| 오늘 배포 전 | `Secret-v1-AI`에 `SENTRY_DSN` 키가 이미 있음(EC2에서 키 목록 조회로 확인). 이 값이 형식에 맞지 않았음 | 값이 먼저 들어가 있었음 |
| 16:12 | 새 CD 병합(PR #19). prepare-runtime.py가 `SENTRY_DSN`을 선택 키로 **전달하기 시작**([TD-019](../technical-decisions.md#td-019--ai-secret-키-전달-범위와-sentry_dsn)) | 이전 배포 방식은 이 키를 넘기지 않아 문제가 숨어 있었음 |
| 16:42~16:55 | 배포 #13·#14. 잘못된 DSN이 AI 컨테이너에 전달됐지만 문제없음 | 당시 AI(`f7476b5`)에는 Sentry 코드가 없었음 |
| **17:13** | 배포 #15. Sentry를 쓰는 AI `4bd2efc`가 처음 올라감 → **기동 실패, 자동 롤백·차단** | 값 전달과 값을 쓰는 코드가 처음 만남 |
| 17:14~18:40 | `SENTRY_DSN`을 올바른 값으로 고치고 차단 목록(`/opt/keepgo/state/failed-images`)을 비운 것으로 추정 | — |
| 18:40 | zikpoka5-commits가 Deploy #18 수동 실행 → 같은 이미지 `4bd2efc` 배포 성공 | 복구 |

**추정 경위:** AI 파트가 Sentry 코드를 먼저 푸시하면서 Secret에는 임시 값(또는 프로젝트 주소만)을 넣어 두었고, 이후 Cloud 쪽 전달이 시작되자 제대로 된 DSN으로 고친 것으로 보인다. 값이 처음 들어간 시각과 고친 시각은 CloudTrail(`PutSecretValue`·`CreateSecret`)로 확인할 수 있지만 조회하지 않았다. 이 경위는 추정이다.

**우리 쪽 원인:** TD-019에서 전달 키를 추가할 때 **운영 Secret에 키가 있는지만 확인하고 값의 형식은 확인하지 않았다.**

## ✅ 해결 방법

- 운영 복구: `SENTRY_DSN`을 올바른 값으로 고친 뒤 차단을 풀고 재배포(#18, 18:40)한 것으로 보인다. 이후 AI `4bd2efc`가 정상 동작 중이다.
- 확인 방법 (값을 출력하지 않고 형식만 확인):

```bash
sudo grep -cE '^SENTRY_DSN=https://[^@/]+@[^/]+/[0-9]+$' /opt/keepgo/runtime/ai.env   # 1이면 올바른 형식
```

- 원인을 찾은 곳: [Actions #15](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/36688340973)의 **Wait for deployment result** 로그. 교체에 실패하면 deploy.sh가 컨테이너 상태와 로그 60줄을 출력한다. AWS Systems Manager → Run Command 명령 기록(`KeepGo deploy 0992bf0bafe3`)에도 같은 출력이 남는다. 실패한 컨테이너는 롤백 때 지워져 EC2의 `docker logs`로는 볼 수 없다.
- 재발 방지 (TODO, [체크리스트](../v1-remaining-checklist.md) 9절):
  - prepare-runtime.py가 `SENTRY_DSN` 형식을 검사해, 틀리면 전달하지 않고 경고만 남긴다(AI는 Sentry 없이 기동).
  - 차단 때문에 건너뛴 서비스가 있으면 `unchanged` 대신 `blocked`로 기록하고 Discord로 알린다.

## 회고

- **키가 "있다"와 "쓸 수 있다"는 다르다.** 새 Secret 키를 전달 목록에 넣을 때는 운영 값의 형식까지 확인하고, 가능하면 배포 스크립트가 검사하게 한다.
- **앱 코드, Secret 값, 인프라 전달이 각자 따로 준비되면 셋이 처음 만나는 배포에서 터진다.** 새 환경변수가 필요하면 AI(또는 BE·FE) 파트와 Cloud가 "값을 넣는다 → 형식 확인 → 전달 시작 → 코드 배포" 순서를 맞춘다.
- **자동 롤백이 조용히 성공하면 문제가 묻힌다.** 서비스는 지켰지만, 새 버전과 설정 변경이 약 1시간 반 동안 반영되지 않은 사실을 아무도 몰랐다. 롤백·차단도 최소한 알림은 가야 한다.
- **차단을 풀 때는 원인과 조치를 남긴다.** 이번에는 누가 어떤 이유로 풀었는지 기록이 없어 경위를 역추적해야 했다.
- 실패 원인의 유일한 기록이 배포 로그였다. CloudWatch 로그 수집(모니터링 적용)을 켜 두면 컨테이너 로그가 남는다.
