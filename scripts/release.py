"""Python 표준 라이브러리만 사용하는 공통 배포 규칙과 유틸리티."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {"frontend": ("web", "nginx"), "backend": ("backend",), "worker": ("worker",), "ai": ("ai-api",)}
SERVICES = {s for values in GROUPS.values() for s in values}
ORDER = ["ai-api", "backend", "worker", "web", "nginx"]
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
        temporary = out.name
    os.replace(temporary, path)


def run(*args, timeout=120, input=None):
    result = subprocess.run(list(args), input=input, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed ({result.returncode})")
    return result.stdout


def aws(*args, **kwargs):
    return run("aws", *args, "--region", "ap-northeast-2", **kwargs)


def aws_json(*args):
    return json.loads(aws(*args, "--output", "json"))


def validate_manifest(m, structure_only=False):
    if not isinstance(m, dict) or set(m) != {"environment", "region", "images", "sources"}:
        raise ValueError("Manifest keys must be environment, region, images, sources")
    if m["environment"] != "production" or m["region"] != "ap-northeast-2":
        raise ValueError("Only production / ap-northeast-2 is supported")
    if set(m["images"]) != SERVICES or set(m["sources"]) != set(GROUPS):
        raise ValueError("Unexpected services or source groups")
    for group, services in GROUPS.items():
        source = m["sources"][group]
        if set(source) != {"sha", "run_id"}:
            raise ValueError("Each source requires sha and run_id")
        sha = source["sha"]
        placeholder = f"<{group.upper()}_COMMIT_SHA>"
        if not isinstance(sha, str) or not (SHA.fullmatch(sha) or (structure_only and sha == placeholder)):
            raise ValueError(f"{group}: lowercase 40 character commit SHA required")
        if type(source["run_id"]) is not int or source["run_id"] < (0 if structure_only else 1):
            raise ValueError(f"{group}: successful CI run_id required")
        if any(m["images"][s] != sha for s in services):
            raise ValueError(f"{group}: image tags must match the source SHA")


def render_compose(root, manifest, account):
    env = {**os.environ, "AWS_ACCOUNT_ID": account,
           **{s.upper().replace("-", "_") + "_IMAGE_TAG": sha for s, sha in manifest["images"].items()}}
    result = subprocess.run(["docker", "compose", "-f", str(Path(root) / "compose.yaml"),
                             "config", "--format", "json"], env=env, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError("docker compose config failed")
    config = json.loads(result.stdout)
    if set(config["services"]) != SERVICES:
        raise ValueError("Compose services must match the release contract")
    return config


def resolve_images(manifest, policy, account):
    images = {}
    for group, services in GROUPS.items():
        for service in services:
            repo = policy[group]["services"][service]
            info = aws_json("ecr", "describe-images", "--repository-name", repo,
                            "--image-ids", "imageTag=" + manifest["images"][service])["imageDetails"]
            if len(info) != 1 or not DIGEST.fullmatch(info[0]["imageDigest"]):
                raise ValueError(f"No unique ECR digest for {service}")
            images[service] = f"{account}.dkr.ecr.ap-northeast-2.amazonaws.com/{repo}@{info[0]['imageDigest']}"
    return images


def changed_services(old, new):
    if old is None:
        return list(ORDER)
    changed = {s for s in SERVICES if old["compose"]["services"][s] != new["compose"]["services"][s]}
    if any(old["compose"].get(k) != new["compose"].get(k) for k in ("networks", "volumes", "secrets", "configs")):
        raise ValueError("Shared network/volume/secret/config changes require a platform maintenance migration")
    # 프런트엔드의 Node와 Nginx는 함께 게시하며 Backend와 Worker는 독립 배포한다.
    if changed.intersection(GROUPS["frontend"]):
        changed.update(GROUPS["frontend"])
    return [s for s in ORDER if s in changed]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def github(path, token, method="GET", data=None):
    request = urllib.request.Request("https://api.github.com/" + path,
        data=None if data is None else json.dumps(data).encode(), method=method,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


def verify_source(group, source, policy, token, latest=True):
    p = policy[group]
    if "CONFIGURE" in json.dumps(p):
        raise ValueError(f"Configure source-policy.json for {group} before enabling CD")
    repo = p["repository"]
    sha, run_id = source["sha"], source["run_id"]
    ci = github(f"repos/{repo}/actions/runs/{run_id}", token)
    if (ci["head_sha"] != sha or ci["head_branch"] != "main" or ci["event"] != "push"
            or ci["status"] != "completed" or ci["conclusion"] != "success"
            or ci["path"] != p["workflow"] or ci["head_repository"]["full_name"] != repo):
        raise ValueError("Only successful, allowlisted main push CI may publish a release")
    if latest and github(f"repos/{repo}/commits/main", token)["sha"] != sha:
        raise ValueError("Stale candidate: source main has advanced")
    jobs = []
    page = 1
    while True:
        batch = github(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}", token)["jobs"]
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    for name in p["required_jobs"]:
        matching = [j for j in jobs if j["name"] == name]
        if len(matching) != 1 or matching[0]["conclusion"] != "success":
            raise ValueError(f"Required CI job not successful: {name}")
