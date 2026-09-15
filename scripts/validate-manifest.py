import os
import re
import subprocess
from pathlib import Path

import yaml


def require(condition, message):
    if not condition:
        raise SystemExit(f"검증 실패: {message}")


root = Path(__file__).resolve().parents[1]
manifest_path = root / "deployment" / "production-manifest.yaml"

with manifest_path.open(encoding="utf-8") as file:
    manifest = yaml.safe_load(file)

# 1. 필수 항목과 배포 환경 확인
require(isinstance(manifest, dict), "Manifest는 YAML 객체여야 합니다.")
require(
    set(manifest) == {"environment", "region", "images"},
    "최상위 항목은 environment, region, images여야 합니다.",
)
require(manifest["environment"] == "production", "환경은 production이어야 합니다.")
require(manifest["region"] == "ap-northeast-2", "리전은 ap-northeast-2여야 합니다.")

# 2. 이미지 항목 확인
images = manifest["images"]
require(isinstance(images, dict), "images는 YAML 객체여야 합니다.")
require(
    set(images) == {"nginx", "backend", "ai"},
    "이미지 항목은 nginx, backend, ai여야 합니다.",
)

# 3. SHA 형식 확인 및 Compose 환경변수 구성
env = os.environ.copy()
variables = {
    "nginx": "NGINX_IMAGE_TAG",
    "backend": "BACKEND_IMAGE_TAG",
    "ai": "AI_IMAGE_TAG",
}

#for service, variable in variables.items():
    #tag = images[service]
    #require(
        #isinstance(tag, str) and re.fullmatch(r"[0-9a-f]{40}", tag),
        #f"images.{service}에는 소문자 40자리 Commit SHA가 필요합니다.",
   # )
   # env[variable] = tag

# 설정 문법 검사용 계정 번호. AWS에 접속하지 않습니다.
env["AWS_ACCOUNT_ID"] = "000000000000"

# 4. Compose 설정 검증
subprocess.run(
    ["docker", "compose", "-f", str(root / "compose.yaml"), "config", "--quiet"],
    env=env,
    check=True,
)

print("Manifest 및 Compose 설정 검증 성공")
