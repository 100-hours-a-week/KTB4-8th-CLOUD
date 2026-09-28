#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFEST_PATH="${ROOT_DIR}/deployment/production-manifest.yaml"
COMPOSE_PATH="${ROOT_DIR}/compose.yaml"

for command in aws docker python3 curl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "[Deploy] ${command} 명령어가 필요합니다." >&2
    exit 1
  }
done
python3 -c 'import yaml' >/dev/null 2>&1 || {
  echo "[Deploy] EC2에 python3-yaml 패키지가 필요합니다." >&2
  exit 1
}
docker compose version >/dev/null

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"
[[ "${AWS_ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || {
  echo "[Deploy] AWS_ACCOUNT_ID는 12자리 계정 번호여야 합니다." >&2
  exit 1
}

if [[ -n "${CLOUD_COMMIT_SHA:-}" ]]; then
  [[ "$(git -c "safe.directory=${ROOT_DIR}" -C "${ROOT_DIR}" rev-parse HEAD)" == "${CLOUD_COMMIT_SHA}" ]] || {
    echo "[Deploy] 요청한 Cloud Commit과 EC2 Checkout이 다릅니다." >&2
    exit 1
  }
fi

echo "[1/7] 이미지 매니페스트와 Compose 검증"
python3 "${ROOT_DIR}/scripts/validate-manifest.py"

tag_exports="$(python3 - "${MANIFEST_PATH}" <<'PY'
import shlex
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as file:
    images = yaml.safe_load(file)["images"]

for service, variable in {
    "nginx": "NGINX_IMAGE_TAG",
    "frontend": "WEB_IMAGE_TAG",
    "backend": "BACKEND_IMAGE_TAG",
    "ai": "AI_IMAGE_TAG",
}.items():
    print(f"export {variable}={shlex.quote(images[service])}")
PY
)"
eval "${tag_exports}"

echo "[2/7] EC2 런타임 파일 확인"
for file in \
  /opt/keepgo/tls/fullchain.pem \
  /opt/keepgo/tls/privkey.pem \
  /opt/keepgo/runtime/backend.env \
  /opt/keepgo/runtime/ai.env \
  /opt/keepgo/runtime/database-password \
  /opt/keepgo/runtime/database-root-password; do
  [[ -s "${file}" ]] || {
    echo "[Deploy] 파일이 없거나 비어 있습니다: ${file}" >&2
    exit 1
  }
done
[[ -d /opt/keepgo/data/mysql ]] || {
  echo "[Deploy] DB 데이터 디렉터리가 없습니다: /opt/keepgo/data/mysql" >&2
  exit 1
}
for key in DB_PASSWORD GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET VWORLD_API_KEY; do
  grep -q "^${key}=." /opt/keepgo/runtime/backend.env || {
    echo "[Deploy] backend.env에 ${key}가 필요합니다." >&2
    exit 1
  }
done
for key in GOOGLE_API_KEY NAVER_MAP_CLIENT_ID NAVER_MAP_CLIENT_SECRET; do
  grep -q "^${key}=." /opt/keepgo/runtime/ai.env || {
    echo "[Deploy] ai.env에 ${key}가 필요합니다." >&2
    exit 1
  }
done
docker compose -f "${COMPOSE_PATH}" config --quiet

echo "[3/7] AWS ECR 로그인"
registry="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
aws ecr get-login-password --region "${AWS_REGION}" |
  docker login --username AWS --password-stdin "${registry}"

echo "[4/7] 이미지 Pull"
docker compose -f "${COMPOSE_PATH}" pull

echo "[5/7] 컨테이너 기동과 헬스 체크"
if ! docker compose -f "${COMPOSE_PATH}" up -d --wait --wait-timeout 420 --remove-orphans; then
  docker compose -f "${COMPOSE_PATH}" ps || true
  docker compose -f "${COMPOSE_PATH}" logs --tail=80 || true
  exit 1
fi

echo "[6/7] 컨테이너 간 연결 확인"
docker compose -f "${COMPOSE_PATH}" exec -T web \
  wget -q -O /dev/null http://frontend:3000/
docker compose -f "${COMPOSE_PATH}" exec -T backend \
  bash -c 'exec 3<>/dev/tcp/ai-api/8000 && exec 4<>/dev/tcp/db/3306'

echo "[7/7] Nginx HTTP 헬스 경로 확인"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1/healthz
docker compose -f "${COMPOSE_PATH}" ps
echo "[Deploy] 모든 컨테이너 헬스 체크 통과"
