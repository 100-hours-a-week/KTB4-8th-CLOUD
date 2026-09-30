# 변경 없는 배포가 backend·ai-api를 매번 재생성

| 항목 | 내용 |
| --- | --- |
| 발생 | 2026-09-30, 새 자동 CD 도입 후 첫 운영 배포(Deploy production #13·#14) |
| 영향 | 바뀐 것이 없어도 배포할 때마다 backend·ai-api 재생성. Spring 기동 동안 Backend 순단, 배포 시간 약 2분 증가. 기능·버전 오류는 없음 |
| 원인 | env_file을 쓰는 서비스는 Compose의 `config-hash` 라벨과 `docker compose config --hash` 값이 항상 달라, deploy.sh가 매번 "설정 변경"으로 판단 |
| 해결 | 마지막 배포가 적용한 `config --hash`를 state에 기록해 비교 ([TD-021](../technical-decisions.md#td-021--배포-변경-감지를-적용-기록-기준으로)) |
| 상태 | 코드 수정·회귀 시험 완료. 운영 반영 후 "두 번 연속 배포 → 두 번째 unchanged" 확인 필요 |

## 증상

같은 Cloud 커밋(`8ce9f99`)으로 두 번 배포했다. Manifest·Secret·compose 모두 바뀌지 않았다.

```text
2026-09-30T07:44:28+00:00 commit=8ce9f999… result=success services=ai-api backend   ← #13 첫 배포 (예상대로)
2026-09-30T07:55:45+00:00 commit=8ce9f999… result=success services=ai-api backend   ← #14 변경 없음인데 또 교체
```

- #14는 `unchanged`로 수십 초 안에 끝나야 했지만, EC2 단계만 1분 54초가 걸렸다(#13과 거의 같음).
- web·frontend는 교체되지 않았다(`Up 37 hours`).
- 결과가 `success`라 알림도 없고, Actions 화면만으로는 알아채기 어렵다. **`history.log`의 `services=`를 봐야 드러난다.**

## 확인 과정

deploy.sh는 서비스마다 두 조건 중 하나라도 다르면 교체한다.

1. 컨테이너 라벨 `com.docker.compose.config-hash` ≠ `docker compose config --hash` (이미지·compose 설정 변경)
2. Secret 적용 기록(`runtime-applied-*.json`) ≠ 현재 env·JWT 파일 (Secret 변경, [TD-016](../technical-decisions.md#td-016--배포-시-secret-자동-조회와-실패-처리))

어느 쪽인지 EC2에서 조회만 해서 확인했다(root, `/opt/keepgo/cloud`에서 Manifest 태그를 export한 뒤).

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

- Secret 적용 기록은 backend·ai-api 모두 `check=0`(적용됨) → 2번 조건은 원인이 아니다.
- 라벨이 다른 서비스가 **정확히 env_file을 쓰는 두 서비스**다. 방금 deploy.sh가 `up`으로 만든 컨테이너인데도 라벨이 `config --hash`와 다르다.

## 원인

**관찰한 사실:** Compose 2.40.3(EC2)에서 env_file을 쓰는 서비스는 `up`으로 막 만든 컨테이너의 `config-hash` 라벨이 같은 설정의 `config --hash`와 다르다. env_file이 없는 서비스는 같다.

**해석:** `up`은 env_file 값을 서비스 환경변수로 합친 설정으로 라벨 해시를 만들고, `config --hash`는 env_file 값을 넣지 않고 계산한다. 로컬 실험(TD-016)에서 env_file 내용만 바꿔도 `config --hash`가 그대로였던 결과와도 맞는다. Compose 소스까지 확인하지는 않았으므로 내부 구현은 해석이다. 어느 쪽이든 **두 값은 비교할 수 없는 값**이라는 점이 핵심이다.

deploy.sh(TD-012)는 라벨과 `config --hash`를 직접 비교했기 때문에 env_file 서비스는 항상 "바뀜"으로 판정됐다.

**왜 미리 못 잡았나**

- 로컬에는 Docker 데몬이 없어 실제 컨테이너 라벨을 만들 수 없었다. TD-016 실험은 `config --hash` 쪽만 확인했다.
- 회귀 시험의 가짜 Docker는 `up` 때 라벨을 `config --hash`와 **같은 값**으로 넣어, 실제 Compose와 다르게 동작했다.
- 첫 배포는 원래 두 서비스를 재생성하는 게 정상(Secret 적용 기록 최초 생성)이라, 두 번째 배포를 해 보기 전에는 구분되지 않았다.

## 해결

Compose 라벨에 의존하지 않고, **마지막 배포가 그 컨테이너에 적용한 `config --hash`를 직접 기록**해 비교한다. Secret 적용 기록과 같은 방식이다.

- 배포 성공 또는 복구 성공 후, 교체한 서비스마다 `/opt/keepgo/state/applied-config-<서비스>`에 `컨테이너ID 설정해시`를 저장한다. 해시는 그 시점에 내보낸 태그 기준이다(성공이면 새 태그, 복구면 이전 태그).
- 다음 배포에서 기록의 컨테이너 ID가 지금 컨테이너와 같으면 기록한 해시와 비교한다.
- 기록이 없거나 컨테이너가 바뀌었으면(도입 직후, 누가 직접 재생성) 이전처럼 라벨과 비교한다. env_file 서비스는 이때 한 번 재생성되고 기록이 생긴다.
- env·JWT 내용 변경은 여전히 Secret 적용 기록이 잡는다. `config --hash`가 env_file 내용을 보지 않으므로 두 기록이 서로를 보완한다.

변경 파일: `scripts/deploy.sh`(`applied_hash`, `record_applied`), `tests/test_runtime_deploy.py`.

## 검증

- 가짜 Docker가 실제처럼 backend·ai-api 라벨을 `config --hash`와 다르게 만들도록 고쳤다.
- 추가한 회귀 시험:
  - 변경 없는 두 번째 배포 → `unchanged`, 재생성 없음 (이번 증상)
  - backend 설정만 바뀜 → backend만 한 번 재생성, 그다음 배포는 `unchanged`
  - 기록과 다른 컨테이너(직접 재생성) → 라벨로 판단해 한 번 재생성, 그다음 `unchanged`
  - 복구 후 `applied-config-backend`에 실제 컨테이너 ID 기록
- 수정 전 deploy.sh로 같은 시험을 돌려 실패하는 것(버그 재현)을 확인했다.

## 운영 반영 시 예상 동작과 확인

1. 수정이 main에 반영된 뒤 **첫 배포**: 기록이 아직 없어 backend·ai-api가 라벨 비교로 **한 번 더 재생성**된다. 정상이다.
2. **바로 한 번 더 배포**해서 확인한다.

```bash
tail -2 /opt/keepgo/state/history.log      # 두 번째 줄이 result=unchanged services=none 이어야 함
cat /opt/keepgo/state/applied-config-*     # 컨테이너ID 해시
```

## 재발 방지

- 도구 내부 값(Compose 라벨 등)의 의미를 가정해 비교하지 않는다. 비교가 필요하면 우리가 직접 기록한 값과 비교한다.
- 가짜 도구로 만든 시험은 실제 동작과 다를 수 있다. 운영 인수 시험에 **"같은 커밋으로 두 번 연속 배포 → 두 번째는 `unchanged`"**를 넣었다([남은 작업 체크리스트](../v1-remaining-checklist.md) 8절).
- 배포 결과는 `success`만 보지 말고 `history.log`의 `services=`로 무엇을 교체했는지 확인한다.
