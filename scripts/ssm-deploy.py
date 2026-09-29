#!/usr/bin/env python3
"""적용 보류: S3 기반 전달 초안이며 현재 S3를 쓰지 않는 환경에 맞지 않는다.

EC2 저장소 경로와 읽기 권한을 확인한 뒤 전달 방식을 바꾼다.
이 초안을 실행하기 위해 S3를 새로 만들지 않는다. 인계 문서를 참고한다.
관련 문서: docs/v1-handoff-2026-09-28.md.
"""
import hashlib
import os
from pathlib import Path
import re
import sys
import tarfile
import time
from release import ROOT, aws, aws_json, load, run, save, verify_source


def wait_command(command_id, instance, deadline_seconds=5700, sleep=time.sleep):
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        # SSM 상태 전파 지연으로 InvocationDoesNotExist가 일시적으로 반환될 수 있다.
        import subprocess
        result = subprocess.run(["aws", "ssm", "get-command-invocation", "--region", "ap-northeast-2",
            "--command-id", command_id, "--instance-id", instance, "--output", "json"],
            capture_output=True, text=True, timeout=30)
        if result.returncode:
            if "InvocationDoesNotExist" in result.stderr:
                sleep(10)
                continue
            raise RuntimeError("SSM result query failed; inspect remote transaction before retry")
        import json
        invocation = json.loads(result.stdout)
        status = invocation["Status"]
        if status in ("Pending", "InProgress", "Delayed", "Cancelling"):
            sleep(10)
            continue
        save(ROOT / ".artifacts/ssm-result.json", invocation)
        if status != "Success" or invocation.get("ResponseCode") != 0:
            raise RuntimeError(f"SSM invocation failed: {status}; inspect host current/inflight state")
        return invocation
    raise TimeoutError("SSM observation timed out; remote work may still run. Do not submit a competing deployment")


def main():
    bucket, instance, mode = (os.environ[k] for k in ("DEPLOY_BUCKET", "PRODUCTION_EC2_INSTANCE_ID", "MODE"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or not re.fullmatch(r"i-[0-9a-f]{8,17}", instance):
        raise ValueError("Valid bundle bucket and EC2 instance ID required")
    if mode not in ("deploy", "rollback", "recover", "freeze", "resume"):
        raise ValueError("Unsupported operation")
    revision = run("git", "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid Cloud revision")
    if mode == "deploy":
        manifest = load(ROOT / "deployment/production-manifest.json")
        policy = load(ROOT / "deployment/source-policy.json")
        for group, source in manifest["sources"].items():
            verify_source(group, source, policy, os.environ["SOURCE_READ_TOKEN"], latest=False)
    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    bundle = artifacts / "release.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        for relative in ["compose.yaml", *[str(p.relative_to(ROOT)) for p in (ROOT / "scripts").glob("*.py")],
                         "scripts/deploy.sh", "deployment/production-manifest.json", "deployment/source-policy.json"]:
            archive.add(ROOT / relative, arcname=relative, recursive=False)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    key = f"releases/{revision}/{digest}.tar.gz"
    aws("s3", "cp", str(bundle), f"s3://{bucket}/{key}", "--only-show-errors")
    # 묶음 해시와 명령에 넣는 값은 형식을 검사하거나 이 코드에서 직접 생성한다.
    directory = f"/opt/keepgo/releases/{revision}-{digest}"
    command = f"""set -eu
umask 077
mkdir -p '{directory}'
aws s3 cp 's3://{bucket}/{key}' '{directory}/bundle.tar.gz' --region ap-northeast-2 --only-show-errors
printf '%s  %s\\n' '{digest}' '{directory}/bundle.tar.gz' | sha256sum -c -
tar -xzf '{directory}/bundle.tar.gz' -C '{directory}'
python3 '{directory}/scripts/deploy.py' --revision '{revision}' --mode '{mode}'
"""
    request = {"InstanceIds": [instance], "DocumentName": "AWS-RunShellScript",
        "Comment": f"KeepGo {mode} {revision}", "TimeoutSeconds": 120,
        "Parameters": {"commands": [command], "executionTimeout": ["5400"]},
        "CloudWatchOutputConfig": {"CloudWatchOutputEnabled": True, "CloudWatchLogGroupName": "/keepgo/v1/ssm"}}
    save(artifacts / "ssm-request.json", request)
    response = aws_json("ssm", "send-command", "--cli-input-json", "file://" + str(artifacts / "ssm-request.json"))
    command_id = response["Command"]["CommandId"]
    save(artifacts / "deployment.json", {"revision": revision, "command_id": command_id, "mode": mode})
    print(f"Cloud revision: {revision}; SSM command: {command_id}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"Cloud commit: `{revision}`\n\nSSM command: `{command_id}`\n\nMode: `{mode}`\n")
    wait_command(command_id, instance)


if __name__ == "__main__":
    main()
