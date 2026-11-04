#!/usr/bin/env python3
"""Refresh only BE/AI ECS targets per V2 cluster; a failed cluster keeps its last good file."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SERVICES = {"backend": (8081, "/actuator/prometheus"), "ai-api": (9464, "/metrics")}

# File names are kept: development.json still feeds the V2 production job (application-dev).
ENVIRONMENTS = {
    "development.json": {"cluster": "keepgo-v2", "environment": "production",
                         "subnets": ("10.20.10.0/24", "10.20.11.0/24")},
    "v2-dev.json": {"cluster": "keepgo-v2-dev", "environment": "development",
                    "subnets": ("10.30.10.0/24", "10.30.11.0/24")},
}


def aws(*args):
    result = subprocess.run(["aws", "ecs", *args, "--region", "ap-northeast-2",
                             "--output", "json", "--no-cli-pager"],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError("ECS discovery API failed: " + result.stderr[:500])
    return json.loads(result.stdout)


def discover(env, read=aws):
    cluster = env["cluster"]
    targets = []
    for name, (port, path) in SERVICES.items():
        service = f"{cluster}-{name}"
        arns = read("list-tasks", "--cluster", cluster, "--service-name", service,
                    "--desired-status", "RUNNING")["taskArns"]
        tasks = []
        for offset in range(0, len(arns), 100):
            response = read("describe-tasks", "--cluster", cluster, "--tasks", *arns[offset:offset+100])
            if response.get("failures"):
                raise RuntimeError("Task lookup changed or failed; retry next tick")
            tasks.extend(response["tasks"])
        addresses = set()
        for task in tasks:
            if task["lastStatus"] != "RUNNING" or task.get("desiredStatus") != "RUNNING":
                continue
            if task.get("group") != "service:" + service:
                raise RuntimeError("Unexpected ECS service in discovery")
            for container in task["containers"]:
                if container["name"] != name or container["lastStatus"] != "RUNNING":
                    continue
                for interface in container.get("networkInterfaces", []):
                    address = ipaddress.IPv4Address(interface["privateIpv4Address"])
                    if not any(address in ipaddress.IPv4Network(net) for net in env["subnets"]):
                        raise RuntimeError("Task address outside approved app subnets")
                    addresses.add(f"{address}:{port}")
        if addresses:
            targets.append({"targets": sorted(addresses), "labels": {
                "environment": env["environment"], "cluster": cluster, "service": name,
                "metrics_contract": "v1", "__metrics_path__": path}})
    return targets


def write_targets(path, targets):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(targets, indent=2) + "\n"
    # Touch on every successful refresh so Prometheus file_sd mtime detects a stuck timer.
    if path.exists() and path.read_text() == data:
        os.utime(path, None)
        return
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".dev-targets-", delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    try:
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def refresh(output_dir, read=aws):
    """Write each cluster's file independently so one failing cluster does not stall the other."""
    summary, failures = {}, {}
    for filename, env in ENVIRONMENTS.items():
        try:
            targets = discover(env, read)
            write_targets(Path(output_dir) / filename, targets)
            summary[env["cluster"]] = sum(len(t["targets"]) for t in targets)
        except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
            failures[env["cluster"]] = str(error)
    return summary, failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="/opt/keepgo/observability/monitoring/prometheus/targets")
    args = parser.parse_args()
    summary, failures = refresh(args.output_dir)
    print(json.dumps({"targets": summary, "failed": failures}))
    sys.exit(1 if failures else 0)
