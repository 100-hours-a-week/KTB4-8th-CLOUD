# JSON Manifest가 main보다 이전 backend를 가리킴

| 항목 | 내용 |
| --- | --- |
| 발생 | 2026-09-30, 새 CD 브랜치 병합 전 점검 |
| 영향 | 그대로 병합했다면 main의 목표 backend가 이전 버전으로 되돌아감 |
| 원인 | Manifest 형식을 YAML → JSON으로 바꾸는 동안 main에 들어온 배포 PR이 YAML에만 반영됨 |
| 해결 | JSON Manifest를 main과 맞춘 뒤 병합. 이후 BE main 최신 `f20f4fc`로 교체 |
| 상태 | 해결 (병합 전 발견) |

## 증상

| 위치 | backend |
| --- | --- |
| main의 `production-manifest.yaml` (PR #18) | `c2dab78` |
| 작업 브랜치의 `production-manifest.json` | `15b54fe` (그 이전 값) |

두 브랜치 모두 충돌 없이 병합돼서 Git이 알려 주지 않았다. YAML 파일은 삭제되고 JSON이 새로 생기는 변경이라 같은 줄을 고친 것으로 인식되지 않는다.

## 확인 과정

```bash
git show origin/main:deployment/production-manifest.yaml
git show origin/feat/v1-central-cd:deployment/production-manifest.json
```

추가로 확인한 것:

- EC2 checkout은 `af4975a`(PR #17), 실행 중인 backend는 `15b54fe`였다. PR #18은 main에 병합만 되고 **배포되지 않은 상태**였다.
- `c2dab78`은 BE **dev** 브랜치 커밋이었다. 새 흐름은 BE `main`만 조회하므로 자동 배포를 켜면 어차피 main 최신으로 덮어쓴다.

## 해결

- 병합 전 JSON을 main과 맞췄다.
- 이후 BE main 최신 `f20f4fc`로 바꿨다. CI의 `Main - Build and Push Image` 성공과, 운영 중인 `15b54fe`와 운영 코드가 같음(테스트 파일만 다름)을 확인했다.

## 재발 방지

- 파일 형식·경로를 바꾸는 PR은 병합 직전에 main의 값과 **내용을 직접 대조**한다. 충돌이 없다고 안전한 것이 아니다.
- 이제 Manifest는 Auto release가 앱 main을 기준으로 갱신한다. 사람이 Manifest를 직접 고칠 때는 해당 SHA가 `sources.json`의 브랜치에 있는지 확인한다.
- Git의 목표 버전과 EC2 실제 버전은 다를 수 있다. 판단은 EC2의 `docker ps`와 `history.log`로 한다.
