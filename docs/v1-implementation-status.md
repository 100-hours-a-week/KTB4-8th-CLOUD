# 자동 CD 구현 및 검증 현황

2026-09-29 작업 기록 기준. **구현과 기존 로컬 검사 기록이 있으며 GitHub Actions·AWS·EC2 인수 완료 증거는 아직 없다.** 아래 기존 시험 기록과 이번 문서 정리에서 확인한 범위를 구분한다. 전체 동작은 [전체 설명](v1-design.md), 실제 수행 방법은 [운영 절차](v1-operations.md)에 둔다.

## 구현 범위

현재 파일·기능 목록은 [전체 설명의 파일 역할](v1-design.md#9-파일과-상태의-위치)이 기준이다. 조회·병합은 release.sh로 분리됐고 Actions 수동 dry_run 입력이 구현돼 있다. dry_run은 자동 배포 OFF에서도 실행하며 실패 Discord를 생략한다.

## 기존 작업에서 남긴 로컬 검증 기록

- Manifest·sources `jq` 검사 통과. web·frontend SHA가 다르면 거부되는 것도 확인했다.
- `docker compose config --no-env-resolution` 통과. Backend healthcheck 명령이 의도대로 렌더링된다.
- `shellcheck 0.10.0`: `release.sh`, `deploy.sh`, `notify-discord.sh` 경고 없음. `actionlint 1.7.7`: workflow 4개 오류 없음.
- 로컬 Docker Compose v5에서 `config --hash '*'` 출력 형식(`서비스 해시`)을 확인했다.
- **가짜 docker로 `deploy.sh` 시나리오 9개를 확인했다:**

| # | 시나리오 | 결과 |
| --- | --- | --- |
| 1 | Backend 새 버전 정상 | Backend만 교체, `success`(0) |
| 2 | Backend health 실패 | 이전 이미지로 복구, 차단 기록, `rolled_back`(1) |
| 3 | 차단된 이미지 | 건너뛰고 `unchanged`(0) |
| 4 | FE 배포 중 web 실패 | web→frontend 역순 복구, 둘 다 차단, `rolled_back`(1) |
| 5 | 롤백도 실패 | `rollback_failed`(2) |
| 6 | pull 실패 | 아무것도 바꾸지 않음, `pull_failed`(2) |
| 7 | 변경 없음 | `unchanged`(0) |
| 8 | 설정만 바뀐 서비스 실패 | 차단하지 않음, `rollback_failed`(2) |
| 9 | 원인 불명 연결 실패 | 바꾼 이미지 모두 차단, 롤백 시도 |

- **가짜 `gh`로 `release.sh` 시나리오를 확인했다:** 새 이미지는 배포 대상, 이미 최신은 건너뜀, CI 진행 중·게시 job skip은 대기, 같은 커밋의 CI 재실행은 가장 최근 것 사용, API 오류는 멈춤(종료 코드 1), 로컬에서 `DRY_RUN` 없이 실행하면 거부. 로컬 bare 저장소를 origin으로 두고 실제 병합 경로도 확인했다. Manifest diff가 해당 서비스 한 줄이고, PR 생성 → squash 병합 → `released=true` 순서로 동작했다.

위 시나리오는 기존 작업에서 남긴 기록이며 이번 문서 정리에서 재실행하지 않았다. 이 문서에는 재현용 시험 코드·실행 링크가 남아 있지 않아 현재 코드 전체에 대한 반복 검증 근거로 사용하지 않는다. 당시 실제 문제와 해결 과정은 [구현·로컬 검증 기록](archive/v1-implementation-notes-2026-09-29.md)에 보존했다. 실제 AWS·EC2·GitHub Actions 경로는 별도 확인이 필요하다. 가짜 gh와 로컬 bare 저장소 시험은 GitHub 서버의 실제 PR 생성·병합 권한을 검증한 것이 아니다.

## 이번 문서 정리에서 확인한 범위

- workflow 4개, release.sh·deploy.sh·notify-discord.sh·prepare-runtime.py와 Compose·배포 JSON을 읽고 문서를 대조했다.
- release.sh 분리와 수동 dry_run, main checkout 고정, 스위치 예외·알림 생략을 반영했다.
- 배포 재시도 범위, FE 실패 위치별 차단 차이, 이미지 복구의 한계를 실제 코드 기준으로 명시했다.
- README와 현재·보관 문서의 상대 링크·섹션 링크가 모두 연결되는지 검사했고, 오래된 실행 지침과 diff의 공백 오류를 점검했다. 문서 정리는 운영 배포 성공 증거를 추가하지 않는다.

알림 구축·수신 시험은 [장애 알림 시스템](./v1-alerting.md), 검증 기준·복구·실패 시나리오는 [배포 검증 및 롤백 프로세스](./v1-deployment-verification-and-rollback.md)에 전용 문서로 분리했다. 문서 분리는 실제 환경의 추가 시험 완료를 뜻하지 않는다.

## 남은 검증과 적용

- [ ] GitHub 변수·Secret·PR 생성 권한·production 승인 정책·main 보호 정책을 운영 설정과 대조한다.
- [ ] main 반영 후 실제 Actions dry_run에서 후보 조회·무변경·실패 알림 생략을 확인한다.
- [ ] EC2 요구사항과 실제 이미지·설정 차이를 확인하고 최초 수동 배포를 수행한다.
- [ ] Health check의 정상 검사와 실제 장애·복구 Webhook 전달을 각각 확인한다.
- [ ] 후보를 확인한 뒤 자동 배포를 켜고 [배포 검증·롤백](./v1-deployment-verification-and-rollback.md) 7절과 [알림 수신](./v1-alerting.md) 7절의 시험 결과를 기록한다.
- [ ] 후속 요구: FE main 전환, 서비스별 오류 격리, FE 묶음 차단, 배포 호출 실패 재처리 여부를 결정한다.

완료 표시에는 날짜, Cloud 커밋, Actions/SSM 실행 링크, 결과를 남긴다. 과거 문서의 특정 SHA를 앞으로 배포될 버전으로 예고하지 않는다.
