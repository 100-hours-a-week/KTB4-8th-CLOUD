#!/usr/bin/env bash
# gitops 폴더(+ 로컬 override)를 kind 안 Git 서버에 push한다. Argo CD는 이 저장소를 GitHub 대신 읽는다.
#   GITOPS_DIR : feat/v3-helm-app-chart 워크트리의 gitops 폴더(필수)
#   WORK       : 키·임시 저장소를 둘 폴더(up.sh가 정한다)
# 값을 바꿔 다시 동기화를 보려면 이 스크립트만 다시 실행한다(새 커밋으로 push).
set -euo pipefail

HERE="$(cd "$(dirname "$0")/../.." && pwd)"
LOCAL="$HERE/k8s/v3-local"
: "${GITOPS_DIR:?GITOPS_DIR=<gitops 폴더 경로>가 필요합니다}"
: "${WORK:?WORK=<작업 폴더>가 필요합니다}"
GITHUB_URL="https://github.com/100-hours-a-week/keepgo-gitops.git"
LOCAL_URL="http://git-server.git-server.svc.cluster.local:23232/gitops.git"
PORT="${GIT_SSH_PORT:-23231}"

repo="$WORK/repo"
rm -rf "$repo"
mkdir -p "$repo"
# 렌더링 결과 등 Git에 없는 파일은 빼고 복사
(cd "$GITOPS_DIR" && tar --exclude=.rendered -cf - .) | (cd "$repo" && tar -xf -)
mkdir -p "$repo/local"
cp -r "$LOCAL/overlay/." "$repo/local/"

# GitHub 주소 → 클러스터 안 Git 서버 주소
grep -rl --include='*.yaml' "$GITHUB_URL" "$repo" | while read -r f; do
  sed -i "s#${GITHUB_URL}#${LOCAL_URL}#g" "$f"
done

cd "$repo"
git init -q -b main
git config core.autocrlf false
git -c user.name=local -c user.email=local@keepgo add -A
git -c user.name=local -c user.email=local@keepgo commit -q -m "local snapshot $(date +%Y%m%d-%H%M%S)"

kubectl -n git-server port-forward svc/git-server "$PORT:23231" >/dev/null 2>&1 &
pf=$!
trap 'kill $pf 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
  sleep 1
done

export GIT_SSH_COMMAND="ssh -i $WORK/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
git push -q -f "ssh://localhost:$PORT/gitops.git" main
echo "push 완료: $LOCAL_URL ($(git rev-parse --short HEAD))"
