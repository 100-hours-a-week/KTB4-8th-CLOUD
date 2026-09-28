#!/usr/bin/env python3
"""Validate the image manifest and the Compose model without starting containers."""

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
IMAGE_ENV = {
    "nginx": "NGINX_IMAGE_TAG",
    "frontend": "WEB_IMAGE_TAG",
    "backend": "BACKEND_IMAGE_TAG",
    "ai": "AI_IMAGE_TAG",
}
PLACEHOLDERS = {"backend": "<BACKEND_COMMIT_SHA>"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"검증 실패: {message}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--structure-only",
        action="store_true",
        help="아직 발행되지 않은 BE 이미지의 자리표시자를 허용합니다.",
    )
    args = parser.parse_args()

    with (ROOT / "deployment/production-manifest.yaml").open(encoding="utf-8") as file:
        manifest = yaml.safe_load(file)

    require(isinstance(manifest, dict), "Manifest는 YAML 객체여야 합니다.")
    require(
        set(manifest) == {"environment", "region", "images"},
        "최상위 항목은 environment, region, images여야 합니다.",
    )
    require(manifest["environment"] == "production", "환경은 production이어야 합니다.")
    require(manifest["region"] == "ap-northeast-2", "리전은 ap-northeast-2여야 합니다.")

    images = manifest["images"]
    require(isinstance(images, dict), "images는 YAML 객체여야 합니다.")
    require(set(images) == set(IMAGE_ENV), "이미지는 nginx, frontend, backend, ai가 필요합니다.")

    env = os.environ.copy()
    env["AWS_ACCOUNT_ID"] = env.get("AWS_ACCOUNT_ID") or "000000000000"

    for service, variable in IMAGE_ENV.items():
        tag = images[service]
        if args.structure_only and tag == PLACEHOLDERS.get(service):
            env[variable] = "0" * 40
            continue
        require(
            isinstance(tag, str) and re.fullmatch(r"[0-9a-f]{40}", tag),
            f"images.{service}에는 발행된 이미지의 40자리 Commit SHA가 필요합니다.",
        )
        env[variable] = tag

    require(
        images["nginx"] == images["frontend"],
        "FE와 Nginx는 같은 FE CI 실행의 Commit SHA여야 합니다.",
    )

    # CI runners do not have the EC2-only env and secret files. Validate the
    # same Compose model with temporary stand-ins for those host files.
    with (ROOT / "compose.yaml").open(encoding="utf-8") as file:
        compose = yaml.safe_load(file)
    require(isinstance(compose, dict), "Compose는 YAML 객체여야 합니다.")
    require(
        set(compose.get("services", {})) == {"web", "frontend", "backend", "ai-api", "db"},
        "Compose에는 web, frontend, backend, ai-api, db 서비스가 필요합니다.",
    )

    with tempfile.TemporaryDirectory(prefix="keepgo-compose-check-") as temporary:
        temporary_dir = Path(temporary)
        placeholder = temporary_dir / "placeholder.env"
        placeholder.write_text("# CI validation placeholder\n", encoding="utf-8")
        for service in ("backend", "ai-api"):
            for env_file in compose["services"][service]["env_file"]:
                env_file["path"] = str(placeholder)
        for secret in compose["secrets"].values():
            secret["file"] = str(placeholder)

        compose_path = temporary_dir / "compose.yaml"
        compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
        subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "config", "--quiet"],
            env=env,
            check=True,
        )
    if args.structure_only:
        print("설정 구조 검증 성공 (BE SHA와 이미지 존재 여부는 배포 전 확인)")
    else:
        print("배포 매니페스트와 Compose 구문 검증 성공")


if __name__ == "__main__":
    main()
