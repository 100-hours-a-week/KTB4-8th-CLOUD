# 2026-09-30 변경 없는 배포가 backend·ai-api를 매번 재생성

## 🐞 에러 내용

- 같은 Cloud 커밋(`8ce9f99`)으로 두 번 배포했다. Manifest·Secret·compose 모두 바뀌지 않았는데 **두 번째 배포도 backend·ai-api를 다시 교체했다.**

```text
2026-09-30T07:44:28+00:00 commit=8ce9f999… result=success services=ai-api backend   ← #13 첫 배포 (예상대로)
2026-09-30T07:55:45+00:00 commit=8ce9f999… result=success services=ai-api backend   ← #14 변경 없음인데 또 교체
```

- #14는 `unchanged`로 수십 초 안에 끝나야 했지만 EC2 단계만 1분 54초가 걸렸다. web·frontend는 교체되지 않았다(`Up 37 hours`).
- 영향: 배포할 때마다 두 서비스가 재시작돼 Spring 기동 동안 Backend 순단이 생긴다. 배포 시간도 약 2분 늘어난다. 버전·기능 오류는 없다.
- 결과가 `success`라 알림이 없다. **`history.log`의 `services=`를 봐야 드러난다.**

## 🔍 원인 분석

deploy.sh는 서비스마다 두 조건 중 하나라도 다르면 교체한다.

1. 컨테이너 라벨 `com.docker.compose.config-hash` ≠ `docker compose config --hash` (이미지·compose 설정 변경)
2. Secret 적용 기록(`runtime-applied-*.json`) ≠ 현재 env·JWT 파일 ([TD-016](../technical-decisions.md#td-016--배포-시-secret-자동-조회와-실패-처리))

EC2에서 조회만 해서 어느 조건인지 확인했다(root, `/opt/keepgo/cloud`, Manifest 태그를 export한 뒤).

```bash
docker compose -f compose.yaml config --hash '*'
for s in web frontend backend ai-api; do id=$(docker compose -f compose.yaml ps -aq $s | head -n1); \
  echo "$s $(docker inspect --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' $id)"; done
for s in backend ai-api; do id=$(docker compose -f compose.yaml ps -aq $s | head -n1); \
  python3 scripts/prepare-runtime.py --check-applied $s $id; echo "$s check=$?"; done
```

| 서비스 | env_file | `config --hash` | 컨테이너 라벨 | 일치 |
| --- | --- | --- | --- | --- |
| web | 없음 | `2c3bdff0…` | `2c3bdff0…` | ✅ |
| frontend | 없음 | `e558ca30…` | `e558ca30…` | ✅ |
| backend | `backend.env` | `5d595221…` | `3055fe1e…` | ❌ |
| ai-api | `ai.env` | `8fd59fcd…` | `f6d49fdf…` | ❌ |

- Secret 적용 기록은 두 서비스 모두 `check=0`(적용됨)이라 2번 조건은 원인이 아니다.
- 라벨이 다른 서비스가 **정확히 env_file을 쓰는 두 서비스**다. deploy.sh가 방금 `up`으로 만든 컨테이너인데도 다르다.

**원인:** Compose 2.40.3(EC2)에서 env_file을 쓰는 서비스는 `up`이 붙인 `config-hash` 라벨이 같은 설정의 `config --hash`와 다르다. `up`은 env_file 값을 환경변수에 합친 설정으로 해시를 만들고, `config --hash`는 env_file 값을 넣지 않고 계산하는 것으로 해석된다(TD-016의 로컬 실험에서 env_file 내용을 바꿔도 `config --hash`가 그대로였던 결과와 일치). Compose 소스까지 확인하지는 않았다. 어느 쪽이든 **두 값은 비교할 수 없는 값**이고, deploy.sh(TD-012)는 이 둘을 직접 비교해서 env_file 서비스를 매번 "바뀜"으로 판정했다.

**왜 미리 못 잡았나**

- 로컬에는 Docker 데몬이 없어 실제 컨테이너 라벨을 만들 수 없었다. TD-016 실험은 `config --hash` 쪽만 확인했다.
- 회귀 시험의 가짜 Docker는 `up` 때 라벨을 `config --hash`와 **같은 값**으로 넣어 실제 Compose와 다르게 동작했다.
- 첫 배포는 원래 두 서비스를 재생성하는 게 정상이라(Secret 적용 기록 최초 생성), 두 번째 배포 전에는 구분되지 않았다.

## ✅ 해결 방법

Compose 라벨에 의존하지 않고 **마지막 배포가 그 컨테이너에 적용한 `config --hash`를 직접 기록해 비교**한다([TD-021](../technical-decisions.md#td-021--배포-변경-감지를-적용-기록-기준으로)). PR #23으로 main에 반영했다.

- 배포·복구 성공 후 교체한 서비스마다 `/opt/keepgo/state/applied-config-<서비스>`에 `컨테이너ID 설정해시`를 저장한다. 해시는 그 시점에 내보낸 태그 기준이다(성공이면 새 태그, 복구면 이전 태그).
- 다음 배포에서 기록의 컨테이너 ID가 지금과 같으면 기록한 해시와 비교한다. 기록이 없거나 컨테이너가 바뀌었을 때(도입 직후, 직접 재생성)만 라벨과 비교한다.
- env·JWT 내용 변경은 계속 Secret 적용 기록이 잡는다.
- 변경 파일: `scripts/deploy.sh`(`applied_hash`, `record_applied`), `tests/test_runtime_deploy.py`

검증:

- 가짜 Docker가 실제처럼 backend·ai-api 라벨을 `config --hash`와 다르게 만들도록 고쳤다.
- 회귀 시험 3개를 추가했다.
  - 변경 없는 두 번째 배포 → `unchanged`
  - backend 설정만 변경 → backend만 한 번 재생성
  - 직접 재생성된 컨테이너 → 라벨로 판단해 한 번 재생성
- **수정 전 deploy.sh로 돌리면 새 시험 2개가 운영과 똑같이 실패**(`['ai-api', 'backend'] != ['backend']`, `unchanged` 없음)한다. 시험이 버그를 재현하는 것을 확인했다.
- 운영 반영 후 첫 배포는 기록을 만들며 backend·ai-api를 한 번 더 재생성한다. **이후 같은 커밋으로 한 번 더 배포해 `result=unchanged services=none`을 확인한다**(미확인, 체크리스트 8절).

## 회고

- **도구 내부 값(Compose 라벨)의 의미를 가정하고 비교했다.** 비교가 필요하면 우리가 직접 기록한 값끼리 비교한다.
- **가짜 도구로 만든 시험은 가짜의 가정만 검증한다.** 가짜 Docker가 실제 Compose와 같게 동작한다는 근거가 없었다. 운영 인수 시험에 "같은 커밋으로 두 번 연속 배포 → 두 번째는 `unchanged`"를 넣었다.
- 배포 결과는 `success`만 보지 말고 `history.log`의 `services=`로 무엇을 교체했는지 확인한다. 1분 54초라는 "이상하게 긴 시간"을 그냥 넘기지 않은 덕분에 발견했다.
