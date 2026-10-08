#!/usr/bin/env bash
# 앱 저장소의 새 이미지를 찾아 Manifest를 바꾸는 PR을 만들고 바로 병합한다.
# auto-release.yaml이 ECR push 이벤트마다, 그리고 안전망으로 10분마다 실행한다(EventBridge, github-dispatch.yaml).
# 병합이 있었으면 GITHUB_OUTPUT에 released=true를 남긴다.
#
# ECR push 이벤트는 앱 CI가 끝나기 직전(push step)에 온다. 그래서 CI가 진행 중인 저장소는 다른 저장소를 먼저
# 처리한 뒤 CI_WAIT_SECONDS(실행 전체 공유) 동안 다시 확인한다. 넘기면 다음 이벤트나 10분 조회가 처리한다.
#
# 미리 보기(조회만, PR·병합 없음):
#   - Actions → Auto release → Run workflow → dry_run 체크 (권장, 운영과 같은 환경)
#   - WSL·Linux에서 gh auth login 후 DRY_RUN=1 bash scripts/release.sh
# 한 저장소에서 오류가 나면 거기서 멈춘다. 나머지 저장소는 다음 조회에서 처리한다.
set -euo pipefail
shopt -s inherit_errexit  # $(...) 안의 API 오류도 무시하지 않고 멈춘다

cd "$(dirname "${BASH_SOURCE[0]}")/.."
MANIFEST=deployment/production-manifest.json
SOURCES=deployment/sources.json
DRY_RUN="${DRY_RUN:-}"
CI_WAIT_SECONDS="${CI_WAIT_SECONDS:-180}"
CI_POLL_SECONDS="${CI_POLL_SECONDS:-15}"

if [[ -z "${DRY_RUN}" && "${GITHUB_ACTIONS:-}" != true ]]; then
  echo "실제 PR 생성·병합은 GitHub Actions에서만 한다. 로컬에서는 DRY_RUN=1로 실행한다." >&2
  exit 2
fi

# sha 커밋의 가장 최근 CI 상태를 출력한다.
#   published <CI 실행 URL>  CI가 성공했고 이미지 게시 job도 성공했다
#   pending                  CI가 아직 끝나지 않았다
#   none                     CI가 없거나 실패했거나 게시 job이 skip됐다
ci_status() {
  local repo="$1" branch="$2" workflow="$3" job="$4" sha="$5" run status conclusion url published=""
  # read <<<"$(...)"는 API 오류에도 멈추지 않으므로 변수에 먼저 담는다.
  run="$(gh api "repos/${repo}/actions/workflows/${workflow}/runs?branch=${branch}&event=push&head_sha=${sha}" \
    --jq '.workflow_runs | max_by(.id) | select(. != null) | "\(.status) \(.conclusion) \(.html_url)"')"
  read -r status conclusion url <<<"${run}"
  case "${status}" in
    '') echo none; return ;;
    completed) ;;
    *) echo pending; return ;;
  esac
  if [[ "${conclusion}" == success ]]; then
    # workflow가 성공해도 게시 job이 skip됐을 수 있다.
    published="$(gh api "repos/${repo}/actions/runs/${url##*/}/jobs?per_page=100" \
      --jq ".jobs[] | select(.name == \"${job}\" and .conclusion == \"success\") | .name")"
  fi
  if [[ -n "${published}" ]]; then echo "published ${url}"; else echo none; fi
}

# 최신 main에서 release 브랜치를 만들어 해당 서비스 SHA만 바꾸고, PR을 만들어 squash 병합한다.
merge_release() {
  local name="$1" services="$2" sha="$3" summary="$4" branch="release/$1-${3:0:12}"
  git fetch --quiet origin main
  git checkout --quiet -B "${branch}" origin/main
  jq --arg sha "${sha}" --argjson s "${services}" 'reduce $s[] as $k (.; .images[$k] = $sha)' "${MANIFEST}" > manifest.tmp
  mv manifest.tmp "${MANIFEST}"
  # main 보호 규칙 없이 병합하므로 Validate와 같은 검사를 여기서 한다(TD-017).
  jq -e -f scripts/check-manifest.jq "${MANIFEST}" >/dev/null \
    || { echo "${name}: 바뀐 Manifest가 형식 검사를 통과하지 못했다" >&2; return 1; }
  # GITHUB_TOKEN PR의 Validate는 승인 대기 후 만료돼 실패로만 남으므로 run을 만들지 않는다(TD-017).
  git commit --quiet -am "release: ${name} ${sha:0:12}" -m "[skip ci]"
  git push --quiet --force origin "${branch}"
  # 이전 실행이 병합 전에 멈췄다면 열려 있는 PR을 그대로 쓴다.
  gh pr view "${branch}" >/dev/null 2>&1 || gh pr create --base main --head "${branch}" \
    --title "release: ${name} ${sha:0:12}" --body "${summary}"$'\n\n'"auto-release.yaml이 자동으로 만들고 병합했다."
  gh pr merge "${branch}" --squash --delete-branch
}

# 저장소 하나를 조회해 새 이미지가 있으면 병합한다. CI가 진행 중이면 waiting에 넣는다.
# 조건문 안에서 부르면 set -e가 꺼지므로 반환값 대신 waiting 배열로 결과를 넘긴다.
release_one() {
  local name="$1" source repo branch services sha status run
  source="$(jq -c --arg n "${name}" '.[$n]' "${SOURCES}")"
  repo="$(jq -r .repository <<<"${source}")"
  branch="$(jq -r .branch <<<"${source}")"
  services="$(jq -c .services <<<"${source}")"

  sha="$(gh api "repos/${repo}/commits/${branch}" --jq .sha)"
  if jq -e --arg sha "${sha}" --argjson s "${services}" '[.images[$s[]]] | all(. == $sha)' "${MANIFEST}" >/dev/null; then
    echo "${name}: 최신 (${sha:0:12})"
    return
  fi

  status="$(ci_status "${repo}" "${branch}" "$(jq -r .workflow <<<"${source}")" "$(jq -r .job <<<"${source}")" "${sha}")"
  read -r status run <<<"${status}"
  case "${status}" in
    pending)
      echo "${name}: ${sha:0:12}의 CI가 진행 중이다. 다른 저장소를 처리한 뒤 다시 확인한다"
      waiting+=("${name}")
      return ;;
    none)
      echo "${name}: ${sha:0:12}의 이미지가 없다 (CI 시작 전·실패·게시 생략)"
      return ;;
  esac

  if [[ -n "${DRY_RUN}" ]]; then
    echo "${name}: ${sha:0:12} 배포 대상 (DRY_RUN이라 PR을 만들지 않음) ${run}"
    return
  fi
  merge_release "${name}" "${services}" "${sha}" "${repo}@${branch} CI 성공: ${run}"
  echo "released=true" >> "${GITHUB_OUTPUT}"
  echo "${name}: ${sha:0:12} 병합"
}

if [[ -z "${DRY_RUN}" ]]; then
  git config user.name 'github-actions[bot]'
  git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
fi

waiting=()
for name in $(jq -r 'keys_unsorted[]' "${SOURCES}"); do
  release_one "${name}"
done

deadline=$((SECONDS + CI_WAIT_SECONDS))
while ((${#waiting[@]} > 0)); do
  if ((SECONDS >= deadline)); then
    echo "CI 대기 상한 ${CI_WAIT_SECONDS}초를 넘겼다. 다음 조회에서 처리한다: ${waiting[*]}"
    break
  fi
  sleep "${CI_POLL_SECONDS}"
  pending=("${waiting[@]}")
  waiting=()
  for name in "${pending[@]}"; do
    release_one "${name}"
  done
done
