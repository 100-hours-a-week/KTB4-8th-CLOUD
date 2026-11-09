#!/usr/bin/env bash
# 모든 Argo CD Application이 Synced·Healthy가 될 때까지 기다린다. 시간을 넘기면 상태표를 보여 주고 실패한다.
# 사용: bash scripts/v3-local/wait-apps.sh [제한 초, 기본 900]
set -uo pipefail

limit="${1:-900}"
expected="${EXPECTED_APPS:-16}"   # root 1 + platform 6(rbac·priority·keda·eso·tenancy·monitoring) + 서비스 9
start=$(date +%s)
table() {
  kubectl -n argocd get applications.argoproj.io \
    -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,MESSAGE:.status.conditions[0].message' 2>/dev/null
}
while :; do
  rows="$(kubectl -n argocd get applications.argoproj.io -o jsonpath='{range .items[*]}{.metadata.name} {.status.sync.status} {.status.health.status}{"\n"}{end}' 2>/dev/null)"
  total=$(printf '%s\n' "$rows" | sed '/^$/d' | wc -l)
  good=$(printf '%s\n' "$rows" | awk '$2=="Synced" && $3=="Healthy"' | wc -l)
  now=$(date +%s)
  printf '\r%4ds  Synced+Healthy %d / %d   ' "$((now - start))" "$good" "$total"
  if [ "$total" -ge "$expected" ] && [ "$good" -eq "$total" ]; then
    printf '\n'; table; echo "모든 Application 정상"; exit 0
  fi
  if [ $((now - start)) -ge "$limit" ]; then
    printf '\n'; table; echo "시간 초과"; exit 1
  fi
  sleep 10
done
