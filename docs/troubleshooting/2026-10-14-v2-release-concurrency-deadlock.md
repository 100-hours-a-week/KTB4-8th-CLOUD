# 2026-10-14 Auto release의 workflow와 job이 같은 잠금을 사용해 실행 취소

작성: 2026-10-15. 상태: [Cloud #100](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/pull/100) 병합 및 같은 입력으로 실행 성공 확인.

## 🐞 에러 내용

Auto release를 `target=v2-dev`, `dry_run=true`로 실행했으나 약 3초 만에 실패했다. V1 release job은 skipped였고 V2 job은 실행 단계가 하나도 생성되지 않았다. AWS 인증 단계에도 도달하지 않았다.

[실패 실행](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38512797252) 페이지에는 다음 오류가 표시됐다.

```text
Canceling since a deadlock was detected for concurrency group: 'auto-release-v2-dev' between a top level workflow and 'Find V2 development images'
```

## 🔍 원인 분석

추가한 workflow-level concurrency와 V2 job-level concurrency가 같은 문자열이 됐다.

```yaml
# 변경 전: workflow 수준
concurrency:
  group: auto-release-${{ inputs.target || 'scheduled' }}

# V2 job 수준
concurrency:
  group: auto-release-v2-dev
```

`target=v2-dev` 입력 시 전체 workflow가 `auto-release-v2-dev`를 잡고, 내부 job도 같은 잠금을 요청했다. GitHub가 상위 workflow와 하위 job 사이의 교착 상태를 감지해 실행을 취소했다.

같은 구성에서 `target=production`도 workflow group과 production job group이 같아지는 것을 코드 검토로 확인했다. 실제 실패 재현은 V2 입력으로 수행했다. 기존 입력 없는 주기 호출은 workflow group이 scheduled/all 계열이어서 수동 특정 대상 입력과 동작이 달랐다.

진단 과정에서 REST job의 steps와 check-run annotations는 비어 있었고 로그 다운로드도 404였다. 재시도에서도 실패했다. 실행 요약 웹페이지의 annotation을 확인한 뒤 원인을 특정했다. 로그가 없다는 사실만으로 IAM이나 Environment 정책 오류로 단정할 수 없었다.

## ✅ 해결 방법

workflow 잠금의 이름을 분리하고, 환경별 job 잠금은 그대로 유지했다.

```yaml
concurrency:
  group: auto-release-workflow-${{ inputs.target || 'scheduled' }}
  cancel-in-progress: false
```

V1 job의 `auto-release-production`, V2 job의 `auto-release-v2-dev`는 유지한다. workflow와 job의 이름이 겹치지 않으면서 같은 환경의 릴리스 작업은 계속 직렬화된다.

검증:

- actionlint 및 V2 회귀 검사 21개 통과.
- [PR #100 Validate](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38513314819) 통과 후 병합.
- 동일한 `target=v2-dev`, `dry_run=true`로 [재실행 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38513768263).
- 이후 Terraform 반영 후에도 [dry-run 성공](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38577506120).
- 실제 [자동 릴리스](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/actions/runs/38579862163)가 AI 배포 workflow를 호출하고 배포까지 성공.

## 회고

workflow 문법 검사는 실행 시 입력으로 확장되는 잠금 이름의 충돌까지 검증하지 못했다. workflow와 job에 동시 실행 제한을 함께 둘 때는 각 입력값을 대입해 서로의 이름이 같아지는지 확인해야 한다.

초기 연결 때는 `all`이나 주기 호출만 확인하지 말고 `production`, `v2-dev`처럼 수동 선택 가능한 각 대상의 실행 경로도 검증해야 한다. 러너가 뜨기 전 실패라면 단계 로그에 더해 실행 요약의 workflow annotation을 확인한다.
