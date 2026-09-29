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
GROUPS = {"backend": ("backend",)}  # 이번 단계의 자동 배포 대상
REPOSITORIES = {"web": "keepgo-nginx", "frontend": "keepgo-web",
                "backend": "keepgo-backend", "ai-api": "keepgo-ai"}
SERVICES = set(REPOSITORIES)
ORDER = ["ai-api", "backend", "frontend", "web"]
IMAGE_ENV = {"web": "NGINX_IMAGE_TAG", "frontend": "WEB_IMAGE_TAG",
             "backend": "BACKEND_IMAGE_TAG", "ai-api": "AI_IMAGE_TAG"}
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(value):
    return json.loads(value, object_pairs_hook=unique_object)


def load(path):
    return loads(Path(path).read_text(encoding="utf-8"))


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
    if not isinstance(m, dict) or set(m) != {"schema_version", "environment", "region", "images", "digests", "sources"}:
        raise ValueError("Unexpected manifest keys")
    if type(m["schema_version"]) is not int or m["schema_version"] != 1:
        raise ValueError("Unsupported schema_version")
    if m["environment"] != "production" or m["region"] != "ap-northeast-2":
        raise ValueError("Only production / ap-northeast-2 is supported")
    if (not all(isinstance(m[k], dict) for k in ("images", "digests", "sources")) or
            set(m["images"]) != SERVICES or set(m["digests"]) != SERVICES or set(m["sources"]) != set(GROUPS)):
        raise ValueError("Unexpected services or source groups")
    for service in SERVICES:
        sha, digest = m["images"][service], m["digests"][service]
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ValueError(f"{service}: lowercase 40 character commit SHA required")
        if not (structure_only and digest is None) and (not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
            raise ValueError(f"{service}: verified ECR digest required; run pin-manifest.py during setup")
    if m["images"]["web"] != m["images"]["frontend"]:
        raise ValueError("Nginx and frontend must use the same FE commit SHA")
    for group, services in GROUPS.items():
        source = m["sources"][group]
        if not isinstance(source, dict) or set(source) != {"sha", "run_id"}:
            raise ValueError("Each source requires sha and run_id")
        sha = source["sha"]
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ValueError(f"{group}: lowercase 40 character commit SHA required")
        if not (structure_only and source["run_id"] is None) and (type(source["run_id"]) is not int or source["run_id"] < 1):
            raise ValueError(f"{group}: successful CI run_id required")
        if any(m["images"][s] != sha for s in services):
            raise ValueError(f"{group}: image tags must match the source SHA")


def render_compose(root, manifest, account):
    env = {**os.environ, "AWS_ACCOUNT_ID": account,
           **{IMAGE_ENV[s]: sha for s, sha in manifest["images"].items()}}
    result = subprocess.run(["docker", "compose", "-f", str(Path(root) / "compose.yaml"),
                             "config", "--no-env-resolution", "--format", "json"], env=env, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError("docker compose config failed")
    config = json.loads(result.stdout)
    if set(config["services"]) != SERVICES:
        raise ValueError("Compose services must match the release contract")
    return config


def lookup_digest(service, sha):
    info = aws_json("ecr", "describe-images", "--repository-name", REPOSITORIES[service],
                    "--image-ids", "imageTag=" + sha)["imageDetails"]
    if len(info) != 1 or not DIGEST.fullmatch(info[0]["imageDigest"]):
        raise ValueError(f"No unique ECR digest for {service}")
    return info[0]["imageDigest"]


def resolve_images(manifest, policy, account):
    images = {}
    for service, repo in REPOSITORIES.items():
        digest = lookup_digest(service, manifest["images"][service])
        if digest != manifest["digests"][service]:
            raise ValueError(f"ECR digest differs from the reviewed manifest: {service}")
        images[service] = f"{account}.dkr.ecr.ap-northeast-2.amazonaws.com/{repo}@{digest}"
    return images


def require_backend_only(before, after):
    for service in SERVICES - {"backend"}:
        if any(before[k][service] != after[k][service] for k in ("images", "digests")):
            raise ValueError("Only Backend versions may change in this CD phase")


def changed_services(old, new):
    if old is None:
        return list(ORDER)
    changed = {s for s in SERVICES if old["compose"]["services"][s] != new["compose"]["services"][s]}
    if any(old["compose"].get(k) != new["compose"].get(k) for k in ("networks", "volumes", "secrets", "configs")):
        raise ValueError("Shared network/volume/secret/config changes require a platform maintenance migration")
    if changed - {"backend"}:
        raise ValueError("Only Backend may be replaced; other services require a separate maintenance change")
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
    if group not in GROUPS or type(source.get("run_id")) is not int or source["run_id"] < 1:
        raise ValueError("Only Backend with a real successful CI run_id is accepted")
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
