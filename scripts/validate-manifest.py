import argparse
import os
import re
import subprocess
from pathlib import Path

import yaml


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

root = Path(__file__).resolve().parents[1]
manifest_path = root / "deployment" / "production-manifest.yaml"

with manifest_path.open(encoding="utf-8") as file:
    manifest = yaml.safe_load(file)

# 1. Manifest 기본 구조 검사
require(isinstance(manifest, dict), "Manifest는 YAML 객체여야 합니다.")
require(
    set(manifest) == {"environment", "region", "images"},
    "최상위 항목은 environment, region, images여야 합니다.",
)
require(
    manifest["environment"] == "production",
    "환경은 production이어야 합니다.",
)
require(
    manifest["region"] == "ap-northeast-2",
    "리전은 ap-northeast-2여야 합니다.",
)

# 2. 이미지 4개와 환경변수 연결
variables = {
    "web": "WEB_IMAGE_TAG",
    "backend": "BACKEND_IMAGE_TAG",
    "worker": "WORKER_IMAGE_TAG",
    "ai": "AI_IMAGE_TAG",
}

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

# 3. 태그 검사 및 Compose 환경변수 구성
env = os.environ.copy()

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

# 설정 검증 전용 계정 번호. AWS에 접속하지 않는다.
env["AWS_ACCOUNT_ID"] = "000000000000"

# 4. Compose 설정 검사
subprocess.run(
    ["docker", "compose", "-f", str(root / "compose.yaml"), "config", "--quiet"],
    env=env,
    check=True,
)

if args.structure_only:
    print("설정 구조 검증 성공 — 실제 이미지 존재 여부는 확인하지 않았습니다.")
else:
    print("SHA 형식 및 Compose 설정 검증 성공 — ECR 존재 검사는 별도입니다.")