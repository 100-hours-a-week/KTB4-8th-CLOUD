#!/usr/bin/env bash
# NetworkPolicy 확인: ai-api는 채팅·추천 API와 분석 Worker만 부를 수 있다(5-2 3.4, partA ai-api 정책).
#   허용: recommend/chat-api → ai-api:8000/health
#   차단: account/auth-api   → ai-api:8000/health  (Namespace 기본 차단 + ai-api 허용 목록 밖)
# Mock 이미지(busybox)의 wget으로 확인한다. 실제 이미지로 하려면 같은 위치에서 curl을 쓴다.
set -uo pipefail

URL="http://ai-api.ai.svc.cluster.local:8000/health"
fail=0

probe() {
  local ns="$1" deploy="$2"
  kubectl -n "$ns" exec "deploy/$deploy" -- wget -q -T 5 -O - "$URL" >/dev/null 2>&1
}

if probe recommend chat-api; then
  echo "ok    허용: recommend/chat-api → ai-api"
else
  echo "FAIL  허용돼야 하는데 막힘: recommend/chat-api → ai-api"; fail=1
fi

if probe account auth-api; then
  echo "FAIL  막혀야 하는데 통과: account/auth-api → ai-api"; fail=1
else
  echo "ok    차단: account/auth-api → ai-api"
fi

[ "$fail" -eq 0 ]
