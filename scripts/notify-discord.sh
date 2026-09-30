#!/usr/bin/env bash
# 사람이 확인해야 하는 장애를 Discord로 보낸다. GitHub Actions에서 실행한다.
# 사용: DISCORD_WEBHOOK_URL=... scripts/notify-discord.sh "🚨 제목" "내용"
set -euo pipefail
if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "::warning::DISCORD_WEBHOOK_URL Secret이 없어 Discord 알림을 보내지 못했다: $1"
  exit 0
fi
run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
jq -n --arg title "$1" --arg body "${2:-}" --arg url "${run_url}" \
  '{content: ("**[KeepGo] " + $title + "**\n" + $body + "\n" + $url)}' |
  curl -fsS --max-time 10 -H 'Content-Type: application/json' -d @- "${DISCORD_WEBHOOK_URL}" >/dev/null
