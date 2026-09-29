# V1 구현·로컬 검증 문제 기록 — 2026-09-29

> 당시 작업에서 남긴 기록이다. 현재 실행 방법은 [운영 절차](../v1-operations.md), 변경된 판단은 [기술 결정](../technical-decisions.md)을 따른다. 코드·원격 저장소·도구 상태와 수치는 작성 당시의 관찰이다.

형식: 증상 → 원인 → 해결 → 재발 방지. 운영 장애가 아니라 설계·구현·로컬 검증 중에 겪은 문제다.

### 설계 단계에서 발견한 문제

**2-1. FE 운영 이미지가 FE `main`에 없는 커밋이었다**
- 증상: FE도 BE처럼 "main CI 성공"을 기준으로 삼으려 했다. 그런데 운영 Manifest의 FE SHA `d3ca2ac`가 FE `main` 이력에 없었다.
- 원인: FE 팀은 `feat/v1`에서 이미지를 게시해 운영에 올렸다. FE `main`은 9/22 커밋 `ea0683c`에 멈춰 있다.
- 해결: `git branch -r --contains d3ca2ac`로 `origin/feat/v1`에만 있음을 확인했다. FE 기준 브랜치를 `feat/v1`로 정했다([TD-011](../technical-decisions.md#td-011--fe-배포-기준-브랜치)).
- 재발 방지: 자동 CD 대상을 추가할 때는 **운영 SHA가 기준 브랜치 이력에 있는지 먼저 확인한다.** 그러지 않으면 켜는 순간 옛 버전으로 돌아갈 수 있다.

**2-2. `GITHUB_TOKEN`으로 병합하면 배포 workflow가 실행되지 않는다**
- 증상(설계 검토): 자동 PR을 병합하면 main push로 Deploy production이 돌 것으로 가정했다.
- 원인: GITHUB_TOKEN 병합으로 발생한 push는 후속 workflow를 실행하지 않는다. 당시에는 PR 검사도 실행되지 않는다고 기록했으나, 현재 공식 문서는 PR 생성·갱신 검사가 승인 대기 상태로 생성된다고 설명한다. 최신 판단은 [TD-010](../technical-decisions.md#td-010--조회병합-로직을-어디에-쓸-것인가)을 따른다.
- 해결: `auto-release.yaml`이 병합 뒤 `gh workflow run deploy-production.yaml`로 배포를 직접 실행한다. 공개 API로 Cloud main에 보호 규칙·ruleset이 없음을 확인했다.
- 재발 방지: main에 필수 검사를 추가하려면 GitHub App 토큰으로 바꾼다([TD-010](../technical-decisions.md#td-010--조회병합-로직을-어디에-쓸-것인가)). Settings의 "Allow GitHub Actions to create and approve pull requests"가 꺼져 있으면 PR 생성부터 실패한다.

**2-3. 설정만 바뀐 서비스가 실패하면 되돌린 뒤에도 영원히 차단될 뻔했다**
- 증상(코드 검토): 실패한 서비스의 "서비스 SHA"를 차단 목록에 넣는 규칙대로면, compose 설정만 바뀌고 이미지는 그대로인 서비스가 실패해도 **운영 중인 정상 이미지가 차단된다.** 설정을 revert해도 그 서비스는 계속 건너뛰게 된다.
- 해결: 교체 전후 이미지 태그가 같은 서비스는 차단 목록에 넣지 않는다. 가짜 docker 시나리오 8로 확인했다.
- 재발 방지: 차단은 "이미지가 원인일 때"만 한다. 설정 문제는 Discord 알림 후 revert PR로 푼다.

**2-4. 배포 중 Backend 재기동을 외부 감시가 장애로 오인할 수 있었다**
- 증상(설계 검토): 처음에는 외부 감시가 30초 간격 3번(약 60초)만 재시도했다. Backend healthcheck의 `start_period`는 90초다.
- 원인: Backend를 교체하는 동안 `/api`가 502를 준다. Spring 기동 시간이 재시도 시간보다 길다.
- 해결: 30초 간격 5번(약 2분)으로 늘렸다.
- 재발 방지: 서비스 기동 시간이 늘면 `health-check.yaml` 재시도 횟수도 함께 조정한다.

**2-5. Backend 헬스 체크를 바꿔도 안전한지 확인이 필요했다**
- 증상: BE 팀이 `/actuator/health`를 추가했다는 소식을 받았다. 그런데 운영 이미지에 이 경로가 없는 상태에서 healthcheck만 바꾸면, 롤백까지 실패한다(롤백은 이미지만 되돌리고 설정은 새 것을 쓴다).
- 해결: BE 저장소에서 `git merge-base --is-ancestor`로 health 커밋 `8a44f98`이 운영 SHA `15b54fe`에 포함됨을 확인했다. `SecurityConfig`의 permitAll, `show-details: never`도 확인했다. 이미지에 curl이 있는지 불확실해서 bash `/dev/tcp`로 요청한다.
- 재발 방지: healthcheck·compose 설정을 바꿀 때는 **현재 운영 이미지로도 통과하는지** 먼저 확인한다.

### 로컬 검증 단계에서 겪은 문제

**2-6. GitHub API 호출이 막혔다 (rate limit)**
- 증상: `curl https://api.github.com/...`가 `API rate limit exceeded for 211.244.225.164`를 반환했다.
- 원인: 로컬에 `gh`가 없어 토큰 없이 호출했다. 토큰 없는 호출은 **IP당 시간당 60회**다. 직접 호출은 10여 회였으므로, 같은 공인 IP를 쓰는 다른 사람이나 프로그램과 한도를 나눠 쓴 것으로 보인다(원인은 확정하지 못했다). 한도는 1시간 뒤 초기화된다(`/rate_limit`의 `reset`).
- 해결: 운영에는 영향이 없다. Actions는 `GITHUB_TOKEN`으로 저장소당 시간당 1,000회까지 쓸 수 있고, 조회는 시간당 약 36회다. 로컬 확인은 가짜 `gh`로 대신했고, 실제 응답 확인은 Actions `dry_run`으로 미뤘다.
- 재발 방지: 로컬에서 GitHub API를 부를 때는 `gh auth login` 후 호출한다(시간당 5,000회). 미리 보기는 Actions `dry_run`을 기본으로 쓴다.

**2-7. Windows용 jq가 줄 끝에 CR을 붙여 서비스 이름이 깨졌다**
- 증상: Git Bash에서 `DRY_RUN=1 bash scripts/release.sh`를 실행하자 `unexpected path repos/null/commits/null`가 났다.
- 원인: Windows용 `jq` 1.6은 출력 줄 끝을 CRLF로 쓴다. `keys_unsorted[]` 결과가 `backend\r`가 되어 `.["backend\r"]` 조회가 `null`이 됐다. 이 버전은 CRLF를 끄는 `-b` 옵션도 지원하지 않는다(`Unknown option -b`).
- 해결: **운영 스크립트에는 우회 코드를 넣지 않았다.** 운영 환경(Ubuntu runner)에서는 생기지 않는 로컬 문제이기 때문이다. 로컬 테스트용 가짜 도구 폴더에만 `jq` 출력의 CR을 지우는 shim을 두었다.
- 재발 방지: 로컬 실행은 WSL·Linux로 안내한다. 스크립트가 Windows에서만 이상하면 먼저 CRLF를 의심한다(`od -c`로 `\r` 확인).

**2-8. 테스트 shim이 실패를 숨겨 모든 서비스가 "최신"으로 나왔다**
- 증상: CR을 지우는 shim을 넣자 새 SHA가 있는 Backend까지 `최신`으로 나왔다.
- 원인: shim이 `jq … | tr -d '\r'`인데 `pipefail`이 없었다. 그래서 `jq -e`가 false(종료 코드 1)를 반환해도 파이프 전체의 결과는 `tr`의 0이 됐다.
- 해결: shim에 `set -o pipefail`을 넣었다. 다시 돌려 BE는 배포 대상, FE는 최신, AI는 CI 진행 중으로 기대한 결과가 나오는 것을 확인했다.
- 재발 방지: 파이프로 감싸는 wrapper에는 `pipefail`을 넣는다. **테스트가 전부 통과처럼 보이면 실패해야 하는 경우가 실제로 실패하는지 확인한다.**

**2-9. `$(...)` 안의 API 오류가 "이미지 없음"으로 조용히 바뀔 뻔했다**
- 증상(코드 검토): `run="$(published_run …)"` 안에서 `gh api`가 실패해도 스크립트가 멈추지 않을 수 있었다.
- 원인: Bash의 `set -e`는 기본적으로 명령 치환 `$(...)` 안까지 이어지지 않는다. 치환 안의 함수에서 API가 실패해도 빈 문자열이 반환되고, 그러면 "CI 진행 중"과 구분되지 않는다. 같은 이유로 `if`·`||`로 호출한 함수 안에서도 `set -e`가 꺼진다.
- 해결: `shopt -s inherit_errexit`를 추가했다. 가짜 `gh`로 BE CI 조회에 502를 주면 종료 코드 1로 멈추는 것을 확인했다. 저장소별로 오류를 격리하려면 `||`로 감싸야 하는데, 그러면 `set -e`가 꺼지므로 "첫 오류에서 멈추고 나머지는 다음 조회로 미룬다"는 단순한 동작을 택했다.
- 재발 방지: 치환 결과가 비어 있는 것을 "없음"으로 해석하는 코드에는 `inherit_errexit`를 켠다.

**2-10. Git Bash가 `git show` 인자를 경로로 바꿔 버렸다**
- 증상: `git show origin/main:.github/workflows/ci.yml`이 `fatal: ambiguous argument 'origin\main;.github\workflows\ci.yml'`로 실패했다.
- 원인: Git Bash(MSYS)가 `/`와 `:`가 섞인 인자를 Windows 경로 목록으로 자동 변환했다.
- 해결: `MSYS_NO_PATHCONV=1`을 설정하고 실행했다.
- 재발 방지: Git Bash에서 `ref:path` 형식 인자가 이상하게 실패하면 경로 변환을 의심한다.

**2-11. Git Bash의 `python3`가 아무 일도 하지 않았다**
- 증상: `python3 - <<EOF`로 workflow 파일을 고쳤는데 `Python`만 출력되고 파일은 그대로였다. 뒤이은 `grep`에서 변경이 없는 것을 보고 알았다.
- 원인: Windows의 `python3`는 Microsoft Store 설치 안내용 별칭이다. 실제 Python은 `python`(C:\Python312)이다.
- 해결: 파일 수정은 편집 도구로 했다. 로컬 테스트에서는 `python3`를 `python`으로 넘기는 shim을 썼다. EC2의 `deploy.sh`는 Linux의 `python3`를 쓰므로 해당 없다.
- 재발 방지: 수정 명령 뒤에는 결과를 `grep`·`git diff`로 확인한다.

**2-12. Docker 데몬이 꺼져 있어 lint 컨테이너를 못 띄웠다**
- 증상: `validate.yaml`처럼 `docker run rhysd/actionlint`를 실행하려 했으나 `failed to connect to the docker API`가 났다.
- 원인: 로컬 Docker Desktop이 꺼져 있었다. `docker compose config`는 데몬 없이도 동작해서 compose 검사는 가능했다.
- 해결: actionlint 1.7.7과 shellcheck 0.10.0의 Windows 바이너리를 임시 폴더에 내려받아 실행했다. `deploy.sh`의 컨테이너 동작은 가짜 `docker`로 시나리오 9개를 돌려 확인했다.
- 재발 방지: 실제 Docker 동작은 EC2 인수 시험([운영 절차 9절](../v1-operations.md#9-실환경-인수-시험))에서 확인한다. 가짜 docker 결과를 운영 성공 증거로 쓰지 않는다.

**2-13. shellcheck SC2016 경고 (의도한 작은따옴표)**
- 증상: `deploy.sh`의 `bash -c '… /dev/tcp/$DB_HOST/$DB_PORT'`에서 "작은따옴표 안의 변수는 풀리지 않는다" 경고가 났다.
- 원인: `DB_HOST`·`DB_PORT`는 EC2가 아니라 **Backend 컨테이너 안의** 환경변수라서, 일부러 컨테이너 안에서 풀리게 했다.
- 해결: 이유를 적은 `# shellcheck disable=SC2016` 주석을 달았다.

**2-14. 셸 `printf`로 만든 파일에서 `\r` 이스케이프가 사라졌다**
- 증상: 테스트 shim을 `printf '…tr -d '"'"'\r'"'"'…'`로 만들었더니 결과 파일이 `tr -d ''`가 됐다.
- 원인: 따옴표 중첩 속에서 `printf`가 이스케이프를 한 번 더 해석했다.
- 해결: 따옴표를 쓴 heredoc(`<<'EOF'`)으로 파일을 썼다.
- 재발 방지: 특수문자가 들어간 파일은 따옴표 heredoc으로 쓴다.
