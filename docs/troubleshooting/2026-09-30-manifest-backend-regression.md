# 2026-09-30 JSON Manifest가 main보다 이전 backend를 가리킴

## 🐞 에러 내용

- 새 CD 브랜치를 병합하기 전에 점검하다 발견했다. 병합했다면 main의 목표 backend가 이전 버전으로 되돌아갈 뻔했다.

| 위치 | backend |
| --- | --- |
| main의 `production-manifest.yaml` (PR #18) | `c2dab78` |
| 작업 브랜치의 `production-manifest.json` | `15b54fe` (그 이전 값) |

- Git은 충돌로 알려 주지 않았다. YAML 파일을 지우고 JSON을 새로 만드는 변경이라 같은 줄을 고친 것으로 인식되지 않는다.

## 🔍 원인 분석

```bash
git show origin/main:deployment/production-manifest.yaml
git show origin/feat/v1-central-cd:deployment/production-manifest.json
```

- Manifest 형식을 YAML에서 JSON으로 바꾸는 작업 도중에 main에 배포 PR(#18)이 들어왔다. 그 PR은 YAML에만 반영됐다.
- 추가로 확인한 것:
  - EC2 checkout은 `af4975a`(PR #17), 실행 중인 backend는 `15b54fe`였다. PR #18은 main에 병합만 되고 **배포되지 않은 상태**였다.
  - `c2dab78`은 BE **dev** 브랜치 커밋이었다. 새 흐름은 BE `main`만 조회하므로, 자동 배포를 켜면 어차피 main 최신으로 덮어쓴다.

## ✅ 해결 방법

- 병합 전 JSON을 main과 맞췄다.
- 이후 BE main 최신 `f20f4fc`로 바꿨다.
  - CI의 `Main - Build and Push Image`가 성공한 것을 확인했다.
  - 운영 중인 `15b54fe`와 운영 코드가 같음(테스트 파일만 다름)을 확인했다.

## 회고

- 파일 형식·경로를 바꾸는 PR은 병합 직전에 main의 값과 **내용을 직접 대조**한다. 충돌이 없다고 안전한 것이 아니다.
- 이제 Manifest는 Auto release가 앱 main 기준으로 갱신한다. 사람이 직접 고칠 때는 그 SHA가 `sources.json`의 브랜치에 있는지 확인한다.
- Git의 목표 버전과 EC2 실제 버전은 다를 수 있다. 판단은 EC2의 `docker ps`와 `history.log`로 한다.
