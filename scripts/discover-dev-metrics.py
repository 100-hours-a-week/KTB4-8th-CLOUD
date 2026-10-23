#!/usr/bin/env python3
"""Refresh only BE/AI ECS targets; failed API calls preserve the last good file."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile

SERVICES = {"keepgo-v2-backend": ("backend", 8081, "/actuator/prometheus"),
            "keepgo-v2-ai-api": ("ai-api", 9464, "/metrics")}


def aws(*args):
    result = subprocess.run(["aws", "ecs", *args, "--region", "ap-northeast-2",
                             "--output", "json", "--no-cli-pager"],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError("ECS discovery API failed: " + result.stderr[:500])
    return json.loads(result.stdout)


def discover(read=aws):
    targets = []
    for service, (name, port, path) in SERVICES.items():
        arns = read("list-tasks", "--cluster", "keepgo-v2", "--service-name", service,
                    "--desired-status", "RUNNING")["taskArns"]
        tasks = []
        for offset in range(0, len(arns), 100):
            response = read("describe-tasks", "--cluster", "keepgo-v2", "--tasks", *arns[offset:offset+100])
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
                    if not any(address in ipaddress.IPv4Network(net) for net in ("10.20.10.0/24", "10.20.11.0/24")):
                        raise RuntimeError("Task address outside approved app subnets")
                    addresses.add(f"{address}:{port}")
        if addresses:
            targets.append({"targets": sorted(addresses), "labels": {
                "environment": "production", "cluster": "keepgo-v2", "service": name,
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="/opt/keepgo/observability/monitoring/prometheus/targets/development.json")
    args = parser.parse_args()
    targets = discover()
    write_targets(args.output, targets)
    print(json.dumps({"services": len(targets), "targets": sum(len(t["targets"]) for t in targets)}))
