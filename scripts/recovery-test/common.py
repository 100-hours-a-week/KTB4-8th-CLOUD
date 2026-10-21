"""Shared helpers for the V2 BE recovery test. Read-only AWS CLI calls only."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

REGION = "ap-northeast-2"
CLUSTER = "keepgo-v2"
SERVICE = "keepgo-v2-backend"
ROOT = Path(__file__).resolve().parents[2] / ".artifacts" / "recovery-test"


def aws(service, *args, timeout=30):
    result = subprocess.run(["aws", service, *args, "--region", REGION, "--output", "json", "--no-cli-pager"],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"aws {service} {args[0]} failed: {result.stderr[:300]}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def now():
    return datetime.now(timezone.utc)


def iso(value=None):
    return (value or now()).astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_dir(name):
    path = ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path
