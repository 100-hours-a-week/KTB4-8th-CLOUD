#!/usr/bin/env python3
"""Secrets Manager 값을 compose가 읽는 런타임 파일로 만든다.

- EC2 인스턴스 Role로 조회하며, 값은 절대 출력하지 않는다.
- deploy.sh가 잠금을 잡은 뒤 교체 대상을 계산하기 전에 실행한다.
- runtime 적용 기록은 실제 컨테이너 ID와 파일 지문만 저장한다. 값/지문은 출력하지 않는다.
"""
import argparse
import hashlib
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
STATE_DIR = Path(os.environ.get("STATE_DIR", "/opt/keepgo/state"))
BACKEND_UID = 10001  # BE Dockerfile의 app 사용자(uid/gid 10001)

# 없으면 컨테이너가 뜨지 않거나 DB에 붙지 못한다
BACKEND_REQUIRED = ["DB_USERNAME", "DB_PASSWORD"]
# 없으면 뜨기는 하지만 해당 기능이 실패한다 (Google 값이 없으면 yaml 기본값으로 붙는다)
BACKEND_OPTIONAL = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "VWORLD_API_KEY"]
# NAVER 키가 없으면 AI는 뜨지만 지도·주소 요청이 모두 실패한다. main의 deploy.sh도 필수로 검사했다(TD-018)
AI_REQUIRED = ["GOOGLE_API_KEY", "NAVER_MAP_CLIENT_ID", "NAVER_MAP_CLIENT_SECRET"]
# AI main(8bd3c32~)은 SENTRY_DSN이 있을 때만 Sentry를 켜고, 운영 값은 인프라가 주입하기로 했다(TD-019)
AI_OPTIONAL = ["SENTRY_DSN"]
# BE는 RSA 키 쌍을 읽는다. JWT_SECRET(HMAC 문자열)은 코드에서 쓰지 않는다
JWT_FILES = {
    "JWT_PUBLIC_KEY": ("public_key.pem", "-----BEGIN PUBLIC KEY-----"),
    "JWT_PRIVATE_KEY": ("private_key.pem", "-----BEGIN PRIVATE KEY-----"),
}
RUNTIME_FILES = {
    "backend": ("backend.env", "jwt/public_key.pem", "jwt/private_key.pem"),
    "ai-api": ("ai.env",),
}


class RuntimeError_(Exception):
    pass


def read_secret(secret_id):
    result = subprocess.run(
        ["aws", "secretsmanager", "get-secret-value", "--region", REGION,
         "--secret-id", secret_id, "--query", "SecretString", "--output", "text"],
        capture_output=True, text=True, timeout=60,
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
        if not isinstance(value, str):
            raise RuntimeError_(f"{secret_id}의 {key}는 문자열이어야 합니다")
        if any(c in value for c in "\r\n\0"):
            raise RuntimeError_(f"{secret_id}의 {key} 값에 줄바꿈이 있습니다")
        lines.append(f"{key}={value}")  # compose env_file format: raw 기준
    for key in data:
        if key.endswith("=") or key != key.strip():
            warnings.append(f"{secret_id}의 키 이름 '{key}'에 '=' 또는 공백이 섞여 있습니다")
    return "\n".join(lines) + "\n"


def write_file(path, content, mode, uid=0, gid=0):
    # 매 배포마다 같은 PEM의 inode를 교체하지 않는다. 기존 bind mount도 유지한다.
    if path.exists() and path.read_bytes() == content.encode("utf-8"):
        os.chmod(path, mode)
        os.chown(path, uid, gid)
        return
    fd, tmp = tempfile.mkstemp(prefix=".prepare-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.chown(tmp, uid, gid)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def prepare():
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
        if (not isinstance(value, str) or not value.startswith(header)
                or "\n" not in value.strip() or "\0" in value
                or not value.rstrip().endswith(header.replace("BEGIN", "END"))):
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


def runtime_state(service, container_id):
    if service not in RUNTIME_FILES:
        raise RuntimeError_("지원하지 않는 runtime 서비스입니다")
    digest = hashlib.sha256()
    for filename in RUNTIME_FILES[service]:
        content = (RUNTIME_DIR / filename).read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return {"container_id": container_id, "sha256": digest.hexdigest()}


def check_applied(service, container_id):
    """0=적용됨, 1=미적용/기록 없음. I/O 오류는 호출자가 실패로 처리한다."""
    current = runtime_state(service, container_id)
    try:
        applied = json.loads((STATE_DIR / f"runtime-applied-{service}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return 1
    return 0 if current == applied else 1


def record_applied(service, container_id):
    current = runtime_state(service, container_id)
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_file(STATE_DIR / f"runtime-applied-{service}.json", json.dumps(current) + "\n", 0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-applied", nargs=2, metavar=("SERVICE", "CONTAINER_ID"))
    mode.add_argument("--record-applied", nargs=2, metavar=("SERVICE", "CONTAINER_ID"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError_("root로 실행해야 합니다 (sudo)")
    if args.check_applied:
        return check_applied(*args.check_applied)
    if args.record_applied:
        record_applied(*args.record_applied)
    else:
        prepare()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError_ as e:
        print(f"런타임 파일 준비 실패: {e}", file=sys.stderr)
        sys.exit(2)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        # AWS 명령 출력·파일 내용·Secret이 예외 문자열에 포함될 수 있어 출력하지 않는다.
        print("런타임 파일 조회·저장 실패. AWS 통신과 파일 권한·디스크를 확인하세요.", file=sys.stderr)
        sys.exit(2)
