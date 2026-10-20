"""Discover verified development images, update only V2 manifests, dispatch ECS CD."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from v2_common import AWS, Error, Pending, GitHub, ROOT, candidate, check_account, load_config, run, validate_manifest
from v2_deploy import Deployer


def blocked(state, manifest):
    if not state:
        return False
    if state.get("phase") == "deploying":
        return True
    return state.get("phase") == "failed" and (not state.get("recovered") or state.get("image") == manifest["image"])


def publish(name, manifest):
    """Called only in an Actions checkout; each PR starts from fresh Cloud main."""
    commit = manifest["source"]["commit"]
    branch = f'release/v2-dev/{name}-{commit[:12]}-{os.environ["GITHUB_RUN_ID"]}-{os.environ.get("GITHUB_RUN_ATTEMPT", "1")}'
    run(["git", "fetch", "--quiet", "origin", "main"])
    run(["git", "checkout", "--quiet", "-B", branch, "origin/main"])
    relative = f"deployment/envs/v2-dev/{name}.json"
    path = ROOT / relative
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) == manifest:
        return False
    # Configuration may have changed while CI/release was running. Never publish using stale mappings.
    validate_manifest(manifest, load_config(), name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run(["git", "add", "--", relative])
    run(["git", "commit", "--quiet", "-m", f"release: v2-dev {name} {commit[:12]}", "-m", "[skip ci]"])
    head = run(["git", "rev-parse", "HEAD"]).strip()
    run(["git", "push", "--quiet", "origin", branch])
    body = (f'V2 development only. Source: {manifest["source"]["repository"]}@{commit}\n'
            f'CI: https://github.com/{manifest["source"]["repository"]}/actions/runs/{manifest["source"]["run_id"]}\n'
            f'Image: `{manifest["image"]}`\n\n'
            'V1 production manifest and deployment are unchanged. Provenance is rechecked before ECS update.\n')
    with tempfile.TemporaryDirectory() as directory:
        body_file = Path(directory) / "body.md"
        body_file.write_text(body, encoding="utf-8")
        pr_url = run(["gh", "pr", "create", "--base", "main", "--head", branch,
                      "--title", f"release: v2-dev {name} {commit[:12]}", "--body-file", str(body_file)]).strip()
    run(["gh", "pr", "merge", pr_url, "--squash", "--delete-branch", "--match-head-commit", head])
    pr = json.loads(run(["gh", "pr", "view", pr_url, "--json", "state"]))
    if pr["state"] != "MERGED":
        raise Error("Manifest PR did not finish merging; deployment was not dispatched")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Create/merge PRs and dispatch deployment")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.execute and (os.environ.get("GITHUB_ACTIONS") != "true"
                         or os.environ.get("GITHUB_REF") != "refs/heads/main"):
        raise Error("Mutating releases are restricted to Cloud main in GitHub Actions")
    config = load_config()
    aws, gh = AWS(config["region"]), GitHub()
    check_account(aws, config)
    if args.execute:
        run(["git", "config", "user.name", "github-actions[bot]"])
        run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    errors = []

    def release_one(name):
        try:
            manifest = candidate(gh, aws, config, name)
            if manifest is None:
                print(f"{name}: no successful development image publishing run")
                return False
            validate_manifest(manifest, config, name)
            print(f'{name}: {manifest["source"]["commit"]} → {manifest["image"]}')
            if blocked(Deployer(aws, config, name).state(), manifest):
                print(f"{name}: deployment is blocked/in progress; no automatic PR or dispatch")
                return False
            if not args.execute:
                return False
            publish(name, manifest)
            # Also reconcile an unchanged manifest: a previous dispatch may have failed.
            # The deployer no-ops successful versions and blocks failed/interrupted ones.
            run(["gh", "workflow", "run", "deploy-v2-dev.yaml", "--repo", os.environ["GITHUB_REPOSITORY"],
                 "--ref", "main", "-f", f"group={name}", "-f", "execute=true"])
        except Pending:
            print(f"{name}: CI still running; retry within the shared wait budget")
            return True
        except Error as error:
            errors.append(name)
            print(f"{name}: {error}", file=sys.stderr)
        return False

    waiting = [name for name in config["groups"] if release_one(name)]
    deadline = time.monotonic() + int(os.environ.get("CI_WAIT_SECONDS", "180"))
    while waiting and time.monotonic() < deadline:
        time.sleep(min(15, max(0, deadline - time.monotonic())))
        waiting = [name for name in waiting if release_one(name)]
    if waiting:
        print("CI wait budget expired; the next trigger will retry: " + ", ".join(waiting))
    if errors:
        raise Error("V2 release failed for: " + ", ".join(errors))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Error as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
