"""Deploy one verified V2 image to one environment, with durable interruption/rollback state."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from v2_common import AWS, DIGEST, ENVIRONMENTS, Error, GitHub, ROOT, check_account, load_config, task_payload, verify_provenance


class Deployer:
    def __init__(self, aws, config, name, *, timeout=1200, observe=60, poll=15):
        self.aws, self.config, self.name = aws, config, name
        self.group = config["groups"][name]
        self.timeout, self.observe, self.poll = timeout, observe, poll
        self.parameter = f'{config["state_prefix"]}/{name}'

    def state(self):
        try:
            data = self.aws.call("ssm", "get-parameter", name=self.parameter)
        except Error as error:
            if "ParameterNotFound" in str(error):
                return None
            raise
        return json.loads(data["Parameter"]["Value"])

    def save(self, data):
        self.aws.call("ssm", "put-parameter", name=self.parameter, type="String", overwrite=True,
                      value=json.dumps(data, separators=(",", ":")))

    def service(self):
        data = self.aws.call("ecs", "describe-services", cluster=self.config["cluster"],
                             services=[self.group["service"]])
        if data.get("failures") or len(data["services"]) != 1:
            raise Error("ECS service lookup failed")
        service = data["services"][0]
        if service["status"] != "ACTIVE" or service["desiredCount"] < 1:
            raise Error("V2 service must be ACTIVE with desiredCount >= 1")
        if service.get("deploymentController", {}).get("type", "ECS") != "ECS":
            raise Error("Only ECS rolling deployments are supported")
        settings = service["deploymentConfiguration"]
        if settings.get("strategy", "ROLLING") != "ROLLING":
            raise Error("Only rolling deployments are supported")
        breaker = settings.get("deploymentCircuitBreaker", {})
        if not breaker.get("enable") or not breaker.get("rollback"):
            raise Error("Circuit breaker with rollback must be enabled")
        return service

    def task_definition(self, arn):
        return self.aws.call("ecs", "describe-task-definition", task_definition=arn, include=["TAGS"])

    def running_digest(self, service, revision):
        arns = self.aws.call("ecs", "list-tasks", cluster=self.config["cluster"],
                             service_name=self.group["service"], desired_status="RUNNING")["taskArns"]
        if not arns:
            raise Error("No running tasks")
        tasks = []
        for offset in range(0, len(arns), 100):
            response = self.aws.call("ecs", "describe-tasks", cluster=self.config["cluster"], tasks=arns[offset:offset + 100])
            if response.get("failures"):
                raise Error("Task lookup failed")
            tasks.extend(response["tasks"])
        if len(tasks) != service["desiredCount"]:
            raise Error("Running task count differs from desired count")
        digests = set()
        for task in tasks:
            if (task["taskDefinitionArn"] != revision or task["lastStatus"] != "RUNNING"
                    or task.get("healthStatus") != "HEALTHY"):
                raise Error("Task revision/status/health mismatch")
            containers = [c for c in task["containers"] if c["name"] == self.group["container"]]
            if len(containers) != 1 or containers[0].get("healthStatus") != "HEALTHY":
                raise Error("Application container is not healthy")
            digest = containers[0].get("imageDigest", "")
            if not DIGEST.fullmatch(digest):
                raise Error("Missing actual running image digest")
            digests.add(digest)
        if len(digests) != 1:
            raise Error("Running tasks have mixed image digests")
        # Check the targets belonging to the current tasks, not unrelated healthy targets.
        ips = {detail["value"] for task in tasks for attachment in task.get("attachments", [])
               for detail in attachment.get("details", []) if detail["name"] == "privateIPv4Address"}
        for load_balancer in service.get("loadBalancers", []):
            if load_balancer["containerName"] != self.group["container"]:
                continue
            if not ips:
                raise Error("Cannot identify current task ALB targets")
            health = self.aws.call("elbv2", "describe-target-health", target_group_arn=load_balancer["targetGroupArn"])
            healthy = {item["Target"]["Id"] for item in health["TargetHealthDescriptions"]
                       if item["TargetHealth"]["State"] == "healthy"
                       and item["Target"]["Port"] == load_balancer["containerPort"]}
            if not ips.issubset(healthy):
                raise Error("Current task ALB targets are not all healthy")
        return digests.pop()

    @staticmethod
    def stable(service, revision):
        deployments = service["deployments"]
        return (service["taskDefinition"] == revision and len(deployments) == 1
                and deployments[0]["taskDefinition"] == revision
                and deployments[0].get("rolloutState") == "COMPLETED"
                and service["runningCount"] == service["desiredCount"]
                and service.get("pendingCount", 0) == 0)

    def wait(self, revision, digest):
        deadline, healthy_since = time.monotonic() + self.timeout, None
        last_error = "Service has not reached the target revision"
        while time.monotonic() < deadline:
            service = self.service()
            if service["taskDefinition"] != revision:
                raise Error("ECS rolled back or another writer changed the service revision")
            if any(d["taskDefinition"] == revision and d.get("rolloutState") == "FAILED" for d in service["deployments"]):
                raise Error("Target ECS deployment failed")
            if self.stable(service, revision):
                try:
                    if self.running_digest(service, revision) != digest:
                        raise Error("Actual digest differs from deployment target")
                    healthy_since = healthy_since if healthy_since is not None else time.monotonic()
                    if time.monotonic() - healthy_since >= self.observe:
                        return
                except Error as error:
                    last_error, healthy_since = str(error), None
            else:
                healthy_since = None
            time.sleep(self.poll)
        raise Error("Deployment/observation timeout: " + last_error)

    def update(self, revision):
        self.aws.call("ecs", "update-service", cluster=self.config["cluster"],
                      service=self.group["service"], task_definition=revision)

    def rollback(self, state):
        current = self.service()["taskDefinition"]
        allowed = {state["previous_revision"], state.get("target_revision")}
        if current not in allowed:
            raise Error("Unknown service revision: refusing to overwrite another writer")
        if current != state["previous_revision"]:
            self.update(state["previous_revision"])
        self.wait(state["previous_revision"], state["previous_digest"])

    def recover(self, execute):
        state = self.state()
        if not state or state.get("phase") not in {"deploying", "failed"}:
            raise Error("No interrupted/failed deployment to recover")
        print(f'Recovery target: {state["previous_revision"]}')
        if not execute:
            return
        self.rollback(state)
        state.update(phase="failed", recovered=True)
        self.save(state)
        print("Recovery verified; failed image remains blocked")

    def deploy(self, manifest, *, execute=False, retry_failed=False):
        state = self.state()
        digest = manifest["image"].split("@", 1)[1]
        if state and (state.get("phase") == "deploying"
                      or (state.get("phase") == "failed" and not state.get("recovered"))):
            raise Error("Unfinished deployment requires explicit recovery first")
        if state and state.get("phase") == "failed" and state.get("image") == manifest["image"] and not retry_failed:
            raise Error("Failed image is blocked; explicit retry is required after fixing the cause")
        service = self.service()
        previous = service["taskDefinition"]
        if not self.stable(service, previous):
            raise Error("Existing ECS deployment is not stable; refusing concurrent update")
        definition = self.task_definition(previous)
        payload = task_payload(definition["taskDefinition"], self.group, manifest["image"])
        tags = [tag for tag in definition.get("tags", []) if not tag["key"].startswith("aws:")]
        if tags:
            payload["tags"] = tags
        baseline_digest = self.running_digest(service, previous)
        container = next(c for c in definition["taskDefinition"]["containerDefinitions"] if c["name"] == self.group["container"])
        if (baseline_digest == digest and container["image"] == manifest["image"]
                and state and state.get("phase") == "succeeded" and state.get("revision") == previous):
            print("Already deployed and verified; no changes")
            return
        print(f'{self.group["service"]}: {previous} → {manifest["image"]}')
        if not execute:
            print("Read-only preflight complete; no AWS writes")
            return
        # Save before registering/updating so runner cancellation cannot silently unblock the next run.
        record = {"phase": "deploying", "image": manifest["image"], "source": manifest["source"],
                  "previous_revision": previous, "previous_digest": baseline_digest,
                  "target_revision": None, "recovered": False,
                  "run_id": os.environ.get("GITHUB_RUN_ID", "local")}
        self.save(record)
        try:
            target = self.aws.call("ecs", "register-task-definition", payload=payload)["taskDefinition"]["taskDefinitionArn"]
            record["target_revision"] = target
            self.save(record)
            # Guard against an external deployment between preflight and mutation.
            if self.service()["taskDefinition"] != previous:
                raise Error("Service changed after preflight")
            self.update(target)
            self.wait(target, digest)
            self.save({"phase": "succeeded", "image": manifest["image"], "source": manifest["source"],
                       "revision": target, "digest": digest, "run_id": record["run_id"]})
            print(f"Verified deployment: {target}")
        except (Error, TimeoutError) as error:
            record.update(phase="failed", recovered=False)
            # Persistent 'deploying' from the previous write still blocks if SSM is unavailable.
            self.save(record)
            try:
                self.rollback(record)
            except Error as rollback_error:
                raise Error(f"Deployment failed; recovery unverified: {rollback_error}") from error
            record["recovered"] = True
            self.save(record)
            raise Error(f"Deployment failed; previous revision recovered; candidate blocked: {error}") from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="v2-dev")
    parser.add_argument("--group", required=True, choices=["backend", "ai", "frontend"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--inspect", action="store_true", help="Read-only infrastructure check, without a candidate manifest")
    args = parser.parse_args()
    if args.execute and (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != "refs/heads/main"):
        raise Error("AWS writes are restricted to Cloud main in GitHub Actions")
    config = load_config(args.environment)
    aws = AWS(config["region"])
    check_account(aws, config)
    deployer = Deployer(aws, config, args.group)
    if args.inspect:
        if args.execute or args.recover or args.retry_failed:
            raise Error("--inspect cannot be combined with mutation/recovery flags")
        service = deployer.service()
        revision = service["taskDefinition"]
        if not deployer.stable(service, revision):
            raise Error("Current service deployment is not stable")
        digest = deployer.running_digest(service, revision)
        definition = deployer.task_definition(revision)
        task_payload(definition["taskDefinition"], deployer.group,
                     f'{config["account_id"]}.dkr.ecr.{config["region"]}.amazonaws.com/{deployer.group["ecr_repository"]}@{digest}')
        print(f'Infrastructure check passed: {deployer.group["service"]}, revision={revision}, digest={digest}')
        print("CI provenance, application-level smoke tests, and deployment writes were not exercised")
        return 0
    if args.recover:
        deployer.recover(args.execute)
        return 0
    path = ROOT / f"deployment/envs/{args.environment}/{args.group}.json"
    if not path.exists():
        raise Error("No verified V2 manifest yet; run V2 image discovery after CI succeeds")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    verify_provenance(GitHub(), aws, config, args.group, manifest)
    deployer.deploy(manifest, execute=args.execute, retry_failed=args.retry_failed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Error as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
