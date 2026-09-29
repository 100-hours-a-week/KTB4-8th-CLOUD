#!/usr/bin/env python3
"""Secrets Manager 값을 compose가 읽는 런타임 파일로 만든다.

- EC2 인스턴스 Role로 조회하며, 값은 절대 출력하지 않는다.
- 최초 준비·명시적 Secret 갱신 때 운영자가 root로 직접 실행한다.
  자동 배포(deploy.sh)는 실행하지 않는다. 실행 후 Deploy production을 수동으로 돌리면
  env 파일이 바뀐 서비스만 교체·검증된다(docs/v1-operations.md 8절).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REGION = os.environ.get("AWS_REGION", "ap-northeast-2")
BE_SECRET_ID = os.environ.get("BE_SECRET_ID", "Secret-v1-BE")
AI_SECRET_ID = os.environ.get("AI_SECRET_ID", "Secret-v1-AI")

RUNTIME_DIR = Path("/opt/keepgo/runtime")
JWT_DIR = RUNTIME_DIR / "jwt"
BACKEND_UID = 10001  # BE Dockerfile의 app 사용자(uid/gid 10001)

# 없으면 컨테이너가 뜨지 않거나 DB에 붙지 못한다
BACKEND_REQUIRED = ["DB_USERNAME", "DB_PASSWORD"]
# 없으면 뜨기는 하지만 해당 기능이 실패한다 (Google 값이 없으면 yaml 기본값으로 붙는다)
BACKEND_OPTIONAL = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "VWORLD_API_KEY"]
AI_REQUIRED = ["GOOGLE_API_KEY"]
AI_OPTIONAL = ["NAVER_MAP_CLIENT_ID", "NAVER_MAP_CLIENT_SECRET"]
# BE는 RSA 키 쌍을 읽는다. JWT_SECRET(HMAC 문자열)은 코드에서 쓰지 않는다
JWT_FILES = {
    "JWT_PUBLIC_KEY": ("public_key.pem", "-----BEGIN PUBLIC KEY-----"),
    "JWT_PRIVATE_KEY": ("private_key.pem", "-----BEGIN PRIVATE KEY-----"),
}


class RuntimeError_(Exception):
    pass


def read_secret(secret_id):
    result = subprocess.run(
        ["aws", "secretsmanager", "get-secret-value", "--region", REGION,
         "--secret-id", secret_id, "--query", "SecretString", "--output", "text"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # AWS 에러 문구에는 값이 없지만, 혹시 모를 노출을 막기 위해 요약만 남긴다
        kind = "AccessDenied" if "AccessDenied" in result.stderr else (
            "ResourceNotFound" if "ResourceNotFound" in result.stderr else "알 수 없는 오류")
        raise RuntimeError_(f"{secret_id} 조회 실패 ({kind})")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError_(f"{secret_id}가 JSON 형식이 아닙니다")
    if not isinstance(data, dict):
        raise RuntimeError_(f"{secret_id}가 JSON 객체가 아닙니다")
    return data


def env_lines(secret_id, data, required, optional, warnings):
    lines = []
    for key in required + optional:
        value = data.get(key)
        if value is None or value == "":
            if key in required:
                raise RuntimeError_(f"{secret_id}에 필수 키 {key}가 없습니다")
            warnings.append(f"{secret_id}에 {key}가 없습니다 (관련 기능 실패)")
            continue
        value = str(value)
        if any(c in value for c in "\r\n\0"):
            raise RuntimeError_(f"{secret_id}의 {key} 값에 줄바꿈이 있습니다")
        lines.append(f"{key}={value}")  # compose env_file format: raw 기준
    for key in data:
        if key.endswith("=") or key != key.strip():
            warnings.append(f"{secret_id}의 키 이름 '{key}'에 '=' 또는 공백이 섞여 있습니다")
    return "\n".join(lines) + "\n"


def write_file(path, content, mode, uid=0, gid=0):
    fd, tmp = tempfile.mkstemp(prefix=".prepare-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.chown(tmp, uid, gid)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    if os.geteuid() != 0:
        raise RuntimeError_("root로 실행해야 합니다 (sudo)")

    warnings = []
    be = read_secret(BE_SECRET_ID)
    ai = read_secret(AI_SECRET_ID)

    backend_env = env_lines(BE_SECRET_ID, be, BACKEND_REQUIRED, BACKEND_OPTIONAL, warnings)
    ai_env = env_lines(AI_SECRET_ID, ai, AI_REQUIRED, AI_OPTIONAL, warnings)

    pems = {}
    for key, (filename, header) in JWT_FILES.items():
        value = be.get(key)
        if not value:
            raise RuntimeError_(f"{BE_SECRET_ID}에 {key}가 없습니다 (BE가 기동하지 못함)")
        if not value.startswith(header) or "\n" not in value.strip():
            raise RuntimeError_(
                f"{BE_SECRET_ID}의 {key} 형식이 다릅니다: '{header}'로 시작하고 줄바꿈이 살아 있어야 합니다")
        pems[filename] = value if value.endswith("\n") else value + "\n"

    RUNTIME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(RUNTIME_DIR, 0o700)
    JWT_DIR.mkdir(mode=0o700, exist_ok=True)
    os.chmod(JWT_DIR, 0o700)

    # env 파일은 compose(root)만 읽는다
    write_file(RUNTIME_DIR / "backend.env", backend_env, 0o600)
    write_file(RUNTIME_DIR / "ai.env", ai_env, 0o600)
    # pem은 compose secrets로 bind되어 컨테이너의 uid 10001이 직접 읽는다
    for filename, content in pems.items():
        write_file(JWT_DIR / filename, content, 0o440, 0, BACKEND_UID)

    print("런타임 파일 준비 완료 (값은 출력하지 않음)")
    print(f"  backend.env: {', '.join(l.split('=', 1)[0] for l in backend_env.splitlines())}")
    print(f"  ai.env: {', '.join(l.split('=', 1)[0] for l in ai_env.splitlines())}")
    print(f"  jwt: {', '.join(pems)}")
    for w in warnings:
        print(f"  경고: {w}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError_ as e:
        print(f"런타임 파일 준비 실패: {e}", file=sys.stderr)
        sys.exit(1)