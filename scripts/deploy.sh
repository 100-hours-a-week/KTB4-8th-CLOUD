#!/usr/bin/env bash
#EC2 안에서 실제로 어떻게 배포할지를 담당하는 파일
# 주의 - deploy-production.yaml은 EC2에게 배포를 명령하는 입장이고, deploy.sh는 EC2 내부에서 실제로 배포를 수행하는 일꾼
set -euo pipefail
# 배포 중 오류를 최대한 빨리 잡기 위한 설정
# 명령어 실패시(-e), 정의되지 않은 변수(-u), 파이프라인 실패시(-o)

# 1. Production Manifest 검증
# 2. Manifest의 Commit SHA를 Compose 환경변수로 변환
# 3. AWS ECR 로그인
# 4. 배포 대상 이미지 사전 Pull
# 5. Docker Compose를 통해 컨테이너 반영
# 6. 헬스 체크 및 스모크 테스트는 따로 구성

# 일단 현재 파일 위치 찾기
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# 어느 위치에서 deploy.sh를 실행하더라도 같은 파일을 찾기 위해서 

MANIFEST_PATH="${ROOT_DIR}/deployment/production-manifest.yaml"
COMPOSE_PATH="${ROOT_DIR}/compose.yaml"
# 앞에서 상위 폴더 경로를 받은걸로 앞에다가 변수느낌으로 붙이기
# COMPOSE_PATH=/opt/keepgo/cloud/compose.yaml

# 현재 클라우드 레포에서 사용하는 프로그램 3개 
required_commands=(
  aws
  docker
  python3
)
# 위에 3개 하나씩 확인하는 for문
for command in "${required_commands[@]}"; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "[Deploy] 실패: '${command}' 명령어가 필요합니다." >&2
    exit 1
  fi
done


AWS_REGION="${AWS_REGION:-ap-northeast-2}"
: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"
# AWS ID를 넣지 않으면 실패 처리

echo "=========================================================="
echo " KeepGo Production Deployment"
echo "=========================================================="
echo "Region : ${AWS_REGION}"
echo "Root   : ${ROOT_DIR}"
# 현직자 분의 말씀대로 로그 중요성 - SSM 로그 확인

echo "[1/5] Production Manifest 검증"
python3 "${ROOT_DIR}/scripts/validate-manifest.py"
# 실제 SHA가 들어있는지 확인

echo "Manifest 검증 성공"

echo "[2/5] 배포 이미지 버전 확인"

eval "$(
python3 - "${MANIFEST_PATH}" <<'PY'
import shlex
import sys

import yaml


manifest_path = sys.argv[1]

with open(manifest_path, encoding="utf-8") as file:
    manifest = yaml.safe_load(file)

images = manifest["images"]
# 여기서 production-manifest.yaml에 있는 이미지 태그를 가져와서 컴포즈 용 환경변수로 적용

variables = {
    "web": "WEB_IMAGE_TAG",
    "backend": "BACKEND_IMAGE_TAG",
    "worker": "WORKER_IMAGE_TAG",
    "ai": "AI_IMAGE_TAG",
}

for service, variable in variables.items():
    value = images[service]
    print(f"export {variable}={shlex.quote(value)}")
PY
)"
# 만든 문자열로 Shell에 적용

echo "  web     : ${WEB_IMAGE_TAG}"
echo "  backend : ${BACKEND_IMAGE_TAG}"
echo "  worker  : ${WORKER_IMAGE_TAG}"
echo "  ai      : ${AI_IMAGE_TAG}"
echo
# 결국 compose.yaml이 실제 Image 주소 구성

echo "[3/5] AWS ECR 로그인"

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
# ECR Registry 주소 연결
aws ecr get-login-password \
  --region "${AWS_REGION}" \
  | docker login \
      --username AWS \
      --password-stdin "${ECR_REGISTRY}"
# 중요! 일부러 ECR 로그인을 할 수 있는 임시 Password를 발급받고 그 토큰으로 도커 로그인
# IAM Instance Role을 이용하는 구조

echo "[Deploy] ECR 로그인 성공"
echo


echo "[4/5] Production 이미지 Pull"

docker compose \
  -f "${COMPOSE_PATH}" \
  pull

echo "[Deploy] 이미지 Pull 성공"
#ECR에 로그인하고 실제 Image를 다운로드 - 아까 만든 컴포즈용 환경변수를 보고 가져온다!


echo "[5/5] Docker Compose 배포"

docker compose \
  -f "${COMPOSE_PATH}" \
  up \
  -d \
  --remove-orphans
# 현재 compose.yaml에 더이상 정의되지 않은 레거시 컨테이너는 제거한다.
# -d를 사용하여 터미널을 점령하지 않고 백그라운드에서 실행한다.
echo
echo "=========================================================="
echo " Container 반영 완료"
echo "=========================================================="
# 컨테이너 배포

docker compose \
  -f "${COMPOSE_PATH}" \
  ps

echo
echo "※ 아직 Health / Smoke Check는 수행하지 않았습니다."
echo "※ 최종 배포 성공 판정은 이후 검증 단계에서 수행합니다."