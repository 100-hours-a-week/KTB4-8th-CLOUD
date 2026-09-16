import argparse
import os
import re
import subprocess
from pathlib import Path

import yaml
# production-manifest.yaml과 compose.yaml이 서로 일치하는 지, 같은 방향을 보는지 검사
# 주로 이미지 태그, 환경변수 등을 확인

def require(condition, message):
    if not condition:
        raise SystemExit(f"검증 실패: {message}")


parser = argparse.ArgumentParser()
parser.add_argument(
    "--structure-only",
    action="store_true",
    help="정해진 이미지 자리표시자를 허용하고 설정 구조를 검사합니다.",
)
args = parser.parse_args()
# 아직 실제 배포 이미지가 없어서 파일 구조 검사용 
# 다음주에 --structure-only 제거하고 실제 배포 이미지가 있는지 확인할 예정

root = Path(__file__).resolve().parents[1]
manifest_path = root / "deployment" / "production-manifest.yaml"
# 위치 고정 - KTB4-8th-CLOUD/deployment/production-manifest.yaml

with manifest_path.open(encoding="utf-8") as file:
    manifest = yaml.safe_load(file)
# Manifest를 1차적으로 가져온다.
require(isinstance(manifest, dict), "Manifest는 YAML 객체여야 합니다.")
require(
    set(manifest) == {"environment", "region", "images"},
    "최상위 항목은 environment, region, images여야 합니다.",
# 최상위 키 3개 검사 - environment, region, images
)
require(
    manifest["environment"] == "production",
    "환경은 production이어야 합니다.",
)
require(
    manifest["region"] == "ap-northeast-2",
    "리전은 ap-northeast-2여야 합니다.",
)

# 여기서 Manifest와 Compose 연결 즉, 이미지
variables = {
    "web": "WEB_IMAGE_TAG",
    "backend": "BACKEND_IMAGE_TAG",
    "worker": "WORKER_IMAGE_TAG",
    "ai": "AI_IMAGE_TAG",
}

# --structure-only 용 자리표시자
placeholders = {
    "web": "<FRONTEND_COMMIT_SHA>",
    "backend": "<BACKEND_COMMIT_SHA>",
    "worker": "<WORKER_COMMIT_SHA>",
    "ai": "<AI_COMMIT_SHA>",
}

images = manifest["images"]
require(isinstance(images, dict), "images는 YAML 객체여야 합니다.")
require(
    set(images) == set(variables),
    "이미지 항목은 web, backend, worker, ai여야 합니다.",
)

env = os.environ.copy()
#Compose에 전달해줄 환경변수 복사

for service, variable in variables.items():
    tag = images[service]

    if args.structure_only and tag == placeholders[service]:
        # 설정 검사에만 사용한다. Manifest 파일은 변경하지 않는다.
        env[variable] = "0" * 40
        continue

    require(
        isinstance(tag, str) and re.fullmatch(r"[0-9a-f]{40}", tag),
        f"images.{service}에는 소문자 40자리 Commit SHA가 필요합니다.",
    )
    env[variable] = tag
# 하나씩 For문으로 이미지 태그 검사
# 0~9 또는 a~f로 이루어진 "정확한" 40글자

# 기본뼈대용 검사... 가짜 AWS
env["AWS_ACCOUNT_ID"] = "000000000000"

subprocess.run(
    ["docker", "compose", "-f", str(root / "compose.yaml"), "config", "--quiet"],
    env=env,
    check=True,
)
# 컨테이너를 실행하지 않고 파이썬으로 이 Compose파일이 인식할 수 있는 구조인지만 확인

if args.structure_only:
    print("설정 구조 검증 성공 — 실제 이미지 존재 여부는 확인하지 않았습니다.")
else:
    print("설정 검증 실패")