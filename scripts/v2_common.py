"""V2 release contract per environment and read-only provenance checks (stdlib only)."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class Error(RuntimeError):
    pass


class Pending(Error):
    """The ECR event arrived before the publishing workflow completed."""


def run(args, *, input_text=None):
    try:
        result = subprocess.run(args, input=input_text, text=True, encoding="utf-8",
                                capture_output=True, check=False, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as error:
        raise Error(f"{args[0]} {args[1]}: command unavailable or timed out") from error
    if result.returncode:
        # Never include CLI inputs/task definitions or credentials in exceptions.
        reason = "ParameterNotFound" if "ParameterNotFound" in result.stderr else "command failed"
        raise Error(f"{args[0]} {args[1]}: {reason} (exit {result.returncode})")
    return result.stdout


class AWS:
    def __init__(self, region):
        self.region = region

    def call(self, api_service, operation, *, payload=None, **options):
        args = ["aws", api_service, operation, "--region", self.region,
                "--output", "json", "--no-cli-pager"]
        for key, value in options.items():
            args.append("--" + key.replace("_", "-"))
            if isinstance(value, bool):
                if not value:
                    raise Error("Only positive CLI switches are supported")
            elif isinstance(value, list):
                args.extend(map(str, value))
            else:
                args.append(str(value))
        # Temporary directory is private to the runner; no task definition is committed/logged.
        with tempfile.TemporaryDirectory(prefix="keepgo-v2-") as directory:
            if payload is not None:
                path = Path(directory) / "input.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                args.extend(["--cli-input-json", "file://" + path.as_posix()])
            output = run(args)
        return json.loads(output) if output.strip() else {}


class GitHub:
    def get(self, path):
        return json.loads(run(["gh", "api", path]))

    def jobs(self, repository, run_id, attempt):
        jobs = []
        page = 1
        while True:
            data = self.get(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")
            jobs.extend(data["jobs"])
            if len(data["jobs"]) < 100:
                return jobs
            page += 1


ENVIRONMENTS = ("v2-dev", "v2-prod")
# ECS service/family is always "<cluster>-<suffix>", so a config cannot point at arbitrary services.
SERVICE_SUFFIXES = {"backend": "backend", "ai": "ai-api", "frontend": "frontend"}
PRODUCTION_BRANCHES = {"main", "feat/v1"}


def config_path(environment):
    if environment not in ENVIRONMENTS:
        raise Error("Unknown V2 environment")
    return ROOT / f"deployment/{environment}.json"


def targets(data):
    return {(data.get("cluster"), group.get("service")) for group in data.get("groups", {}).values()}


def load_config(environment="v2-dev", path=None):
    data = json.loads(Path(path or config_path(environment)).read_text(encoding="utf-8"))
    cluster = data.get("cluster", "")
    if (environment not in ENVIRONMENTS or data.get("schema_version") != 1
            or data.get("environment") != environment
            or not re.fullmatch(r"\d{12}", data.get("account_id", ""))
            or not re.fullmatch(r"keepgo-v2(-[a-z0-9]+)?", cluster)
            or data.get("state_prefix") != f"/keepgo/{environment}/deployments"):
        raise Error("Invalid V2 environment configuration")
    if set(data.get("groups", {})) != set(SERVICE_SUFFIXES):
        raise Error("Only the verified backend, ai and frontend services are supported")
    for name, group in data["groups"].items():
        expected = f"{cluster}-{SERVICE_SUFFIXES[name]}"
        if group["service"] != expected or group["family"] != expected:
            raise Error("Unexpected V2 service/family")
        if environment == "v2-prod":
            if group["branch"] != "main":
                raise Error("V2 production must track main")
        elif group["branch"] in PRODUCTION_BRANCHES:
            raise Error("V2 development must not track the production branch")
    if path is None:
        # Two environments deploying different branches to one ECS service would overwrite each other.
        for other in ENVIRONMENTS:
            other_path = config_path(other)
            if other != environment and other_path.exists():
                if targets(data) & targets(json.loads(other_path.read_text(encoding="utf-8"))):
                    raise Error("Another V2 environment targets the same ECS service")
    return data


def check_account(aws, config):
    if aws.call("sts", "get-caller-identity")["Account"] != config["account_id"]:
        raise Error("Unexpected AWS account")


def image_uri(config, group, digest):
    if not DIGEST.fullmatch(digest):
        raise Error("Invalid image digest")
    return f'{config["account_id"]}.dkr.ecr.{config["region"]}.amazonaws.com/{group["ecr_repository"]}@{digest}'


def resolve_image(aws, config, group, commit):
    if not SHA.fullmatch(commit):
        raise Error("Invalid source commit")
    images = aws.call("ecr", "describe-images", repository_name=group["ecr_repository"],
                      image_ids=[f"imageTag={commit}"])["imageDetails"]
    if len(images) != 1:
        raise Error("Commit tag must resolve to exactly one image")
    digest = images[0]["imageDigest"]
    # ECS task imageDigest can be the platform child rather than the index digest.
    media = images[0].get("imageManifestMediaType", "")
    if media in {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}:
        result = aws.call("ecr", "batch-get-image", repository_name=group["ecr_repository"],
                          image_ids=[f"imageDigest={digest}"])
        manifests = json.loads(result["images"][0]["imageManifest"])["manifests"]
        matches = [item["digest"] for item in manifests
                   if item.get("platform", {}).get("os") == "linux"
                   and item.get("platform", {}).get("architecture") == "amd64"]
        if len(matches) != 1:
            raise Error("V2 requires exactly one linux/amd64 image")
        digest = matches[0]
    return image_uri(config, group, digest)


def successful_run(gh, group, commit):
    repo, branch = group["repository"], quote(group["branch"], safe="")
    data = gh.get(f'repos/{repo}/actions/workflows/{group["workflow"]}/runs?branch={branch}&event=push&head_sha={commit}&per_page=100')
    runs = data["workflow_runs"]
    if not runs:
        return None
    latest = max(runs, key=lambda item: item["id"])
    if latest.get("status") != "completed":
        raise Pending("CI is still running")
    if latest.get("conclusion") != "success":
        return None
    if (latest.get("head_sha") != commit or latest.get("head_branch") != group["branch"]
            or latest.get("event") != "push"):
        raise Error("CI provenance mismatch")
    attempt = latest["run_attempt"]
    jobs = gh.jobs(repo, latest["id"], attempt)
    if not any(job["name"] == group["job"] and job.get("conclusion") == "success" for job in jobs):
        return None
    return latest


def candidate(gh, aws, config, name):
    group = config["groups"][name]
    commit = gh.get(f'repos/{group["repository"]}/commits/{quote(group["branch"], safe="")}')["sha"]
    if not SHA.fullmatch(commit):
        raise Error("Invalid branch head")
    ci = successful_run(gh, group, commit)
    if ci is None:
        return None
    return {"schema_version": 1, "environment": config["environment"], "group": name,
            "source": {"repository": group["repository"], "branch": group["branch"],
                       "commit": commit, "run_id": ci["id"], "run_attempt": ci["run_attempt"]},
            "image": resolve_image(aws, config, group, commit)}


def validate_manifest(manifest, config, name):
    group = config["groups"][name]
    if (set(manifest) != {"schema_version", "environment", "group", "source", "image"}
            or manifest["schema_version"] != 1 or manifest["environment"] != config["environment"]
            or manifest["group"] != name):
        raise Error("Invalid V2 manifest")
    source = manifest["source"]
    if (set(source) != {"repository", "branch", "commit", "run_id", "run_attempt"}
            or source["repository"] != group["repository"] or source["branch"] != group["branch"]
            or not SHA.fullmatch(source["commit"])
            or any(type(source[k]) is not int or source[k] < 1 for k in ("run_id", "run_attempt"))):
        raise Error("Invalid manifest source")
    digest = manifest["image"].split("@")[-1]
    if manifest["image"] != image_uri(config, group, digest):
        raise Error("Manifest image repository mismatch")


def verify_provenance(gh, aws, config, name, manifest):
    validate_manifest(manifest, config, name)
    group, source = config["groups"][name], manifest["source"]
    ci = successful_run(gh, group, source["commit"])
    if ci is None or ci["id"] != source["run_id"] or ci["run_attempt"] != source["run_attempt"]:
        raise Error("Manifest CI run is no longer the latest successful attempt")
    if resolve_image(aws, config, group, source["commit"]) != manifest["image"]:
        raise Error("Commit image tag changed after release")


def task_payload(definition, group, image):
    if definition["family"] != group["family"] or definition.get("status") != "ACTIVE":
        raise Error("Unexpected/inactive task definition")
    if definition.get("runtimePlatform", {}).get("cpuArchitecture", "X86_64") != "X86_64":
        raise Error("V2 image platform mismatch")
    # Keep every registerable field; refuse unknown fields instead of silently dropping configuration.
    readonly = {"taskDefinitionArn", "revision", "status", "requiresAttributes", "compatibilities",
                "registeredAt", "registeredBy", "deregisteredAt"}
    allowed = {"family", "taskRoleArn", "executionRoleArn", "networkMode", "containerDefinitions",
               "volumes", "placementConstraints", "requiresCompatibilities", "cpu", "memory",
               "pidMode", "ipcMode", "proxyConfiguration", "inferenceAccelerators",
               "ephemeralStorage", "runtimePlatform", "enableFaultInjection"}
    if set(definition) - readonly - allowed:
        raise Error("Unknown task definition fields; update serializer before deploying")
    result = {key: copy.deepcopy(value) for key, value in definition.items() if key in allowed}
    containers = [c for c in result["containerDefinitions"] if c["name"] == group["container"]]
    if len(containers) != 1 or not containers[0].get("healthCheck"):
        raise Error("Expected one application container with a health check")
    containers[0]["image"] = image
    return result
