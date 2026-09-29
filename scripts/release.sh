#!/usr/bin/env bash
# 앱 저장소의 새 이미지를 찾아 Manifest를 바꾸는 PR을 만들고 바로 병합한다.
# auto-release.yaml이 10분마다 실행한다. 병합이 있었으면 GITHUB_OUTPUT에 released=true를 남긴다.
#
# 미리 보기(조회만, PR·병합 없음):
#   - Actions → Auto release → Run workflow → dry_run 체크 (권장, 운영과 같은 환경)
#   - WSL·Linux에서 gh auth login 후 DRY_RUN=1 bash scripts/release.sh
# 한 저장소에서 오류가 나면 거기서 멈춘다. 나머지 저장소는 다음 조회(10분 뒤)에서 처리한다.
set -euo pipefail
shopt -s inherit_errexit  # $(...) 안의 API 오류도 무시하지 않고 멈춘다

cd "$(dirname "${BASH_SOURCE[0]}")/.."
MANIFEST=deployment/production-manifest.json
SOURCES=deployment/sources.json
DRY_RUN="${DRY_RUN:-}"

if [[ -z "${DRY_RUN}" && "${GITHUB_ACTIONS:-}" != true ]]; then
  echo "실제 PR 생성·병합은 GitHub Actions에서만 한다. 로컬에서는 DRY_RUN=1로 실행한다." >&2
  exit 2
fi

# sha 커밋의 가장 최근 CI가 성공했고 이미지 게시 job도 성공했으면 그 CI 실행 URL을 출력한다.
published_run() {
  local repo="$1" branch="$2" workflow="$3" job="$4" sha="$5" run published=""
  run="$(gh api "repos/${repo}/actions/workflows/${workflow}/runs?branch=${branch}&event=push&head_sha=${sha}" \
    --jq '.workflow_runs | max_by(.id) | select(.status == "completed" and .conclusion == "success") | .html_url')"
  if [[ -n "${run}" ]]; then
    # workflow가 성공해도 게시 job이 skip됐을 수 있다.
    published="$(gh api "repos/${repo}/actions/runs/${run##*/}/jobs?per_page=100" \
      --jq ".jobs[] | select(.name == \"${job}\" and .conclusion == \"success\") | .name")"
  fi
  if [[ -n "${published}" ]]; then echo "${run}"; fi
}

# 최신 main에서 release 브랜치를 만들어 해당 서비스 SHA만 바꾸고, PR을 만들어 squash 병합한다.
merge_release() {
  local name="$1" services="$2" sha="$3" summary="$4" branch="release/$1-${3:0:12}"
  git fetch --quiet origin main
  git checkout --quiet -B "${branch}" origin/main
  jq --arg sha "${sha}" --argjson s "${services}" 'reduce $s[] as $k (.; .images[$k] = $sha)' "${MANIFEST}" > manifest.tmp
  mv manifest.tmp "${MANIFEST}"
  git commit --quiet -am "release: ${name} ${sha:0:12}"
  git push --quiet --force origin "${branch}"
  # 이전 실행이 병합 전에 멈췄다면 열려 있는 PR을 그대로 쓴다.
  gh pr view "${branch}" >/dev/null 2>&1 || gh pr create --base main --head "${branch}" \
    --title "release: ${name} ${sha:0:12}" --body "${summary}"$'\n\n'"auto-release.yaml이 자동으로 만들고 병합했다."
  gh pr merge "${branch}" --squash --delete-branch
}

if [[ -z "${DRY_RUN}" ]]; then
  git config user.name 'github-actions[bot]'
  git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
fi

for name in $(jq -r 'keys_unsorted[]' "${SOURCES}"); do
  source="$(jq -c --arg n "${name}" '.[$n]' "${SOURCES}")"
  repo="$(jq -r .repository <<<"${source}")"
  branch="$(jq -r .branch <<<"${source}")"
  services="$(jq -c .services <<<"${source}")"

  sha="$(gh api "repos/${repo}/commits/${branch}" --jq .sha)"
  if jq -e --arg sha "${sha}" --argjson s "${services}" '[.images[$s[]]] | all(. == $sha)' "${MANIFEST}" >/dev/null; then
    echo "${name}: 최신 (${sha:0:12})"
    continue
  fi

  run="$(published_run "${repo}" "${branch}" "$(jq -r .workflow <<<"${source}")" "$(jq -r .job <<<"${source}")" "${sha}")"
  if [[ -z "${run}" ]]; then
    echo "${name}: ${sha:0:12}의 이미지가 아직 없다 (CI 진행 중·실패·게시 생략)"
    continue
  fi

  if [[ -n "${DRY_RUN}" ]]; then
    echo "${name}: ${sha:0:12} 배포 대상 (DRY_RUN이라 PR을 만들지 않음) ${run}"
    continue
  fi
  merge_release "${name}" "${services}" "${sha}" "${repo}@${branch} CI 성공: ${run}"
  echo "released=true" >> "${GITHUB_OUTPUT}"
  echo "${name}: ${sha:0:12} 병합"
done
