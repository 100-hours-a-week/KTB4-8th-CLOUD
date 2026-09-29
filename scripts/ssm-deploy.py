#!/usr/bin/env python3
"""SSM에서 main의 고정 커밋을 별도 release 디렉터리에 풀고 배포한다. S3는 사용하지 않는다."""
import os
from pathlib import Path
import re
import sys
import time
from release import ROOT, aws_json, load, run, save, validate_manifest, verify_source


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


def remote_command(revision, mode):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid Cloud revision")
    if mode not in ("deploy", "rollback", "recover", "freeze", "resume", "adopt"):
        raise ValueError("Unsupported operation")
    # 읽기 인증은 기존 호스트 checkout을 사용한다. checkout/reset 없이 커밋의 별도 사본을 만든다.
    return f"""bash -se <<'KEEPGO_DEPLOY'
set -euo pipefail
umask 077
test -d /opt/keepgo/cloud/.git
install -d -m 0700 /opt/keepgo/releases
exec 9>/opt/keepgo/source.lock
flock -w 120 9
git -c safe.directory=/opt/keepgo/cloud -C /opt/keepgo/cloud fetch origin main
git -c safe.directory=/opt/keepgo/cloud -C /opt/keepgo/cloud merge-base --is-ancestor '{revision}' FETCH_HEAD
release_dir="$(mktemp -d /opt/keepgo/releases/{revision}.XXXXXX)"
git -c safe.directory=/opt/keepgo/cloud -C /opt/keepgo/cloud archive '{revision}' | tar -x -C "$release_dir"
flock -u 9
exec bash "$release_dir/scripts/deploy.sh" --revision '{revision}' --mode '{mode}'
KEEPGO_DEPLOY
"""


def main():
    instance, mode = (os.environ[k] for k in ("PRODUCTION_EC2_INSTANCE_ID", "MODE"))
    if not re.fullmatch(r"i-[0-9a-f]{8,17}", instance):
        raise ValueError("Valid EC2 instance ID required")
    revision = run("git", "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid Cloud revision")
    command = remote_command(revision, mode)
    if mode in ("deploy", "adopt"):
        manifest = load(ROOT / "deployment/production-manifest.json")
        validate_manifest(manifest)
        policy = load(ROOT / "deployment/source-policy.json")
        for group, source in manifest["sources"].items():
            verify_source(group, source, policy, os.environ["SOURCE_READ_TOKEN"], latest=False)
    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    request = {"InstanceIds": [instance], "DocumentName": "AWS-RunShellScript",
        "Comment": f"KeepGo {mode} {revision}", "TimeoutSeconds": 120,
        "Parameters": {"commands": [command], "executionTimeout": ["5400"]}}
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
