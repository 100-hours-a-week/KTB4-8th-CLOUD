#!/usr/bin/env bash
# EC2에서 root로 실행한다. Manifest와 실행 중인 컨테이너를 비교해 바뀐 서비스만 교체하고,
# 검증에 실패하면 이번에 바꾼 서비스를 모두 직전 이미지로 되돌린다.
#
# 종료 코드: 0 성공(또는 변경 없음) / 1 실패했지만 이전 버전으로 복구됨 / 2 사람이 확인해야 함
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_DIR="${HOST_DIR:-/opt/keepgo}"          # compose.yaml이 bind하는 호스트 경로의 기준. 시험에서만 바꾼다
COMPOSE=(docker compose -f "${ROOT_DIR}/compose.yaml")
# AWS 로그 그룹·IAM 준비 후 운영자가 활성화한다. 이후 자동 배포에도 같은 설정을 유지한다.
if [[ -f /opt/keepgo/runtime/cloudwatch-logs.enabled ]]; then
  COMPOSE+=(-f "${ROOT_DIR}/compose.cloudwatch.yaml")
fi
STATE_DIR="${STATE_DIR:-/opt/keepgo/state}"
export STATE_DIR
FAILED_LIST="${STATE_DIR}/failed-images"  # 검증에 실패한 "서비스 SHA". 같은 이미지는 다시 배포하지 않는다
HISTORY="${STATE_DIR}/history.log"
ORDER=(ai-api backend frontend web)         # 의존 관계 순서. 복구는 역순
# scripts/release.py의 TAG_VARS와 같아야 한다.
declare -A TAG_VAR=([web]=NGINX_IMAGE_TAG [frontend]=WEB_IMAGE_TAG [backend]=BACKEND_IMAGE_TAG [ai-api]=AI_IMAGE_TAG)
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"      # 새 컨테이너가 healthy가 될 때까지 기다리는 시간(초)
BAKE_SECONDS="${BAKE_SECONDS:-60}"           # 교체 후 재시작 없이 버티는지 지켜보는 시간(초)
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"

log() { echo "[Deploy] $*"; }
finish() {
  echo "$(date -Is) commit=${CLOUD_COMMIT_SHA:-unknown} result=$2 services=${replaced[*]:-none}" >> "${HISTORY}"
  log "결과: $2"
  exit "$1"
}

mkdir -p "${STATE_DIR}" || exit 2
touch "${FAILED_LIST}" || exit 2
exec 9>"${STATE_DIR}/deploy.lock" || exit 2
flock -n 9 || { log "다른 배포가 진행 중이다"; exit 2; }
replaced=()

# 1. Manifest의 SHA를 compose.yaml이 읽는 태그 변수로 내보낸다.
exports="$(python3 - "${ROOT_DIR}/deployment/production-manifest.json" <<'PY'
import json, re, sys
names = {"web": "NGINX_IMAGE_TAG", "frontend": "WEB_IMAGE_TAG", "backend": "BACKEND_IMAGE_TAG", "ai-api": "AI_IMAGE_TAG"}
images = json.load(open(sys.argv[1], encoding="utf-8"))["images"]
for service, name in names.items():
    assert re.fullmatch(r"[0-9a-f]{40}", images[service]), service
    print(f"export {name}={images[service]}")
PY
)" || { log "Manifest를 읽을 수 없다"; finish 2 invalid_manifest; }
eval "${exports}"
# compose.yaml의 bind mount는 create_host_path: false라 경로가 없으면 컨테이너가 생성되지 않고, 롤백도 같은 이유로
# 실패한다. compose config로는 잡히지 않으므로 아무것도 바꾸기 전에 확인한다(TD-018).
for path in "${HOST_DIR}/tls/fullchain.pem" "${HOST_DIR}/tls/privkey.pem"; do
  [[ -s "${path}" ]] || { log "파일이 없거나 비어 있다: ${path}"; finish 2 host_files_missing; }
done
for path in "${HOST_DIR}/acme" "${HOST_DIR}/data/uploads"; do
  [[ -d "${path}" ]] || { log "디렉터리가 없다: ${path}"; finish 2 host_files_missing; }
done
# main과 같이 매 배포에서 Secret을 조회한다. 실패를 명시적으로 처리한다(set -e에 의존하지 않음).
python3 "${ROOT_DIR}/scripts/prepare-runtime.py" \
  || { log "Secret 조회·런타임 준비 실패. 컨테이너는 교체하지 않는다"; finish 2 runtime_prepare_failed; }
"${COMPOSE[@]}" config --quiet || { log "compose.yaml 검증 실패"; finish 2 invalid_compose; }

container_of() { "${COMPOSE[@]}" ps -aq "$1" 2>/dev/null | head -n1; }
tag_of() { local var="${TAG_VAR[$1]}"; echo "${!var}"; }

# env_file·PEM 파일 내용 변경을 Compose 설정 해시에만 의존하지 않는다. pull 실패/중단 뒤에도
# 마지막으로 적용된 컨테이너와 비교해야 하므로 '조회 직전 파일'을 기준으로 삼지 않는다.
declare -A runtime_changed
for service in backend ai-api; do
  id="$(container_of "${service}")"
  python3 "${ROOT_DIR}/scripts/prepare-runtime.py" --check-applied "${service}" "${id:-missing}"
  status=$?
  case "${status}" in
    0|1) runtime_changed["${service}"]="${status}" ;;
    *) log "${service}: runtime 적용 상태를 읽을 수 없다"; finish 2 runtime_state_failed ;;
  esac
done

record_runtime() {
  # 차단으로 건너뛴 서비스에 새 파일을 적용했다고 기록하지 않는다.
  local service id
  for service in "${replaced[@]}"; do
    [[ "${service}" == backend || "${service}" == ai-api ]] || continue
    id="$(container_of "${service}")"
    [[ -n "${id}" ]] || return 1
    python3 "${ROOT_DIR}/scripts/prepare-runtime.py" --record-applied "${service}" "${id}" || return 1
  done
  return 0
}

# 모든 컨테이너 healthy + 컨테이너 간 연결 + Nginx 응답을 확인한다.
check_stack() {
  local service id
  for service in "${ORDER[@]}"; do
    id="$(container_of "${service}")"
    if [[ -z "${id}" || "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${id}")" != healthy ]]; then
      log "${service}: healthy 아님"
      return 1
    fi
  done
  "${COMPOSE[@]}" exec -T web wget -q -O /dev/null http://frontend:3000/ || { log "Nginx → Frontend 연결 실패"; return 1; }
  # shellcheck disable=SC2016  # DB_HOST·DB_PORT는 Backend 컨테이너 안의 환경변수로 풀려야 한다.
  "${COMPOSE[@]}" exec -T backend bash -c 'exec 3<>/dev/tcp/ai-api/8000 && exec 4<>/dev/tcp/$DB_HOST/$DB_PORT' \
    || { log "Backend → AI/RDS 연결 실패"; return 1; }
  curl -fsS --max-time 5 -o /dev/null http://127.0.0.1/healthz || { log "Nginx /healthz 실패"; return 1; }
}

# 2. 설정 해시(이미지 포함)가 실행 중인 컨테이너와 다른 서비스를 찾는다.
declare -A desired_hash old_tag
hashes="$("${COMPOSE[@]}" config --hash '*')" || { log "설정 해시 계산 실패"; finish 2 invalid_compose; }
while read -r service hash; do desired_hash["${service}"]="${hash}"; done <<<"${hashes}"
targets=()
for service in "${ORDER[@]}"; do
  id="$(container_of "${service}")"
  if [[ -n "${id}" ]]; then
    [[ -n "${desired_hash[${service}]:-}" ]] || { log "${service}: 설정 해시 없음"; finish 2 invalid_compose; }
    if [[ "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' "${id}")" == "${desired_hash[${service}]}" ]]; then
      [[ "${runtime_changed[${service}]:-0}" == 1 ]] || continue
    fi
    image="$(docker inspect --format '{{.Config.Image}}' "${id}")"
    old_tag["${service}"]="${image##*:}"
  fi
  if grep -qxF "${service} $(tag_of "${service}")" "${FAILED_LIST}"; then
    log "${service}: $(tag_of "${service}")는 이전에 검증 실패한 이미지라 건너뛴다 (새 커밋이 필요)"
    continue
  fi
  targets+=("${service}")
done

if ((${#targets[@]} == 0)); then
  log "바뀐 서비스가 없다. 현재 상태만 확인한다"
  check_stack && finish 0 unchanged
  finish 2 unchanged_but_unhealthy
fi
log "교체 대상: ${targets[*]}"

# 3. 서비스를 멈추기 전에 새 이미지를 받는다. 실패하면 아무것도 바꾸지 않고 끝낸다.
aws ecr get-login-password --region "${AWS_REGION}" |
  docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" >/dev/null \
  || { log "ECR 로그인 실패"; finish 2 ecr_login_failed; }
"${COMPOSE[@]}" pull --quiet "${targets[@]}" || { log "이미지 pull 실패. 운영 컨테이너는 그대로다"; finish 2 pull_failed; }

rollback() {
  local i service var
  for ((i = ${#replaced[@]} - 1; i >= 0; i--)); do
    service="${replaced[i]}"
    if [[ -z "${old_tag[${service}]:-}" ]]; then
      log "${service}: 되돌릴 이전 이미지가 없다"
      return 1
    fi
    var="${TAG_VAR[${service}]}"
    export "${var}=${old_tag[${service}]}"
    log "${service}: ${old_tag[${service}]:0:12}로 복구"
    "${COMPOSE[@]}" up -d --force-recreate --no-deps --wait --wait-timeout "${HEALTH_TIMEOUT}" "${service}" || return 1
  done
  check_stack
}

fail() {
  local service
  log "검증 실패: $1"
  "${COMPOSE[@]}" ps || true
  for service in "${replaced[@]}"; do "${COMPOSE[@]}" logs --tail=60 "${service}" || true; done
  # 실패한 이미지와 같은 커밋에서 나온 짝(web·frontend)을 차단한다. 원인 서비스를 모르면($2 비움)
  # 이번에 바꾼 이미지를 모두 차단한다. 이미지는 그대로이고 설정만 바뀐 서비스는 차단하지 않는다.
  for service in "${replaced[@]}"; do
    [[ "${old_tag[${service}]:-}" == "$(tag_of "${service}")" ]] && continue
    if [[ -z "$2" || "$(tag_of "${service}")" == "$(tag_of "$2")" ]]; then
      echo "${service} $(tag_of "${service}")" >> "${FAILED_LIST}"
    fi
  done
  if rollback; then
    record_runtime || { log "복구 후 runtime 적용 기록 실패"; finish 2 runtime_state_failed; }
    finish 1 rolled_back
  fi
  log "복구도 실패했다. 사람이 확인해야 한다"
  finish 2 rollback_failed
}

# 4. 순서대로 한 서비스씩 교체하고 healthy를 기다린다.
for service in "${targets[@]}"; do
  log "${service}: $(tag_of "${service}" | cut -c1-12)로 교체"
  replaced+=("${service}")
  "${COMPOSE[@]}" up -d --force-recreate --no-deps --wait --wait-timeout "${HEALTH_TIMEOUT}" "${service}" \
    || fail "${service}가 ${HEALTH_TIMEOUT}초 안에 healthy가 되지 않았다" "${service}"
done
# nginx.conf는 10초마다 upstream 주소를 다시 찾지만, 교체 직후 바로 반영되도록 reload한다.
if [[ ! " ${replaced[*]} " =~ " web " ]]; then
  "${COMPOSE[@]}" exec -T web nginx -s reload >/dev/null || true
fi

# 5. 전체 연결을 확인하고, 일정 시간 재시작 없이 버티는지 지켜본다.
check_stack || fail "전체 연결 확인 실패" ""
declare -A restarts
for service in "${replaced[@]}"; do restarts["${service}"]="$(docker inspect --format '{{.RestartCount}}' "$(container_of "${service}")")"; done
log "${BAKE_SECONDS}초 동안 재시작 여부 관찰"
sleep "${BAKE_SECONDS}"
for service in "${replaced[@]}"; do
  [[ "$(docker inspect --format '{{.RestartCount}}' "$(container_of "${service}")")" == "${restarts[${service}]}" ]] \
    || fail "${service}가 관찰 중 재시작했다" "${service}"
done
check_stack || fail "관찰 후 연결 확인 실패" ""
record_runtime || { log "runtime 적용 기록 실패. 다음 배포에서 다시 확인한다"; finish 2 runtime_state_failed; }

# 6. 현재·직전 이미지만 남기고 오래된 이미지를 지운다(직전 이미지는 다음 복구용).
for service in "${replaced[@]}"; do
  repository="$(docker inspect --format '{{.Config.Image}}' "$(container_of "${service}")")"
  repository="${repository%:*}"
  docker image ls "${repository}" --format '{{.Tag}}' |
    grep -vxF -e "$(tag_of "${service}")" -e "${old_tag[${service}]:-none}" |
    while read -r tag; do docker image rm "${repository}:${tag}" >/dev/null 2>&1 || true; done
done
docker image prune -f >/dev/null 2>&1 || true
finish 0 success
