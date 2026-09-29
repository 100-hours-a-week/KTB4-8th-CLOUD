#!/usr/bin/env python3
"""초기 연결용: 기존 SHA를 유지하며 ECR digest와 성공한 Backend main CI를 기록한다."""
import copy
import os
from release import ROOT, github, load, lookup_digest, save, validate_manifest, verify_source


def pin(manifest, policy, token):
    validate_manifest(manifest, structure_only=True)
    result = copy.deepcopy(manifest)
    source = result["sources"]["backend"]
    p = policy["backend"]
    if source["run_id"] is None:
        runs = github(f"repos/{p['repository']}/actions/runs?branch=main&event=push&status=success&head_sha={source['sha']}&per_page=100", token)["workflow_runs"]
        matching = [r for r in runs if r["path"] == p["workflow"] and r["head_sha"] == source["sha"]]
        if not matching:
            raise ValueError("No matching successful main CI; do not invent a run_id")
        source["run_id"] = max(matching, key=lambda r: r["id"])["id"]
    verify_source("backend", source, policy, token, latest=False)
    for service, sha in result["images"].items():
        digest = lookup_digest(service, sha)
        if result["digests"][service] not in (None, digest):
            raise ValueError(f"Existing pinned digest changed: {service}")
        result["digests"][service] = digest
    validate_manifest(result)
    return result


if __name__ == "__main__":
    path = ROOT / "deployment/production-manifest.json"
    result = pin(load(path), load(ROOT / "deployment/source-policy.json"), os.environ["SOURCE_READ_TOKEN"])
    save(path, result)
    print("Pinned existing image SHAs. Review and commit the manifest before adoption.")
