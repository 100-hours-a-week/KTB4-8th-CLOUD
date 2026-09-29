#!/usr/bin/env python3
"""EC2 배포 트랜잭션. 잠금과 진행 기록으로 CI 실행기 중단 후에도 상태를 추적한다."""
import argparse
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import re
import signal
import sys
import time
import urllib.request

from release import (ROOT, GROUPS, ORDER, SERVICES, aws, aws_json, changed_services, fingerprint,
                     load, render_compose, resolve_images, run, save, validate_manifest)


@contextmanager
def lock(state):
    import fcntl  # 운영 호스트는 Linux이며 단위 테스트에는 이 잠금을 사용하지 않는다.
    state.mkdir(parents=True, exist_ok=True)
    with (state / "deploy.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Engine:
    def __init__(self, root, config, revision):
        self.root, self.config, self.revision = Path(root), config, revision
        self.state = Path(config["state_dir"])
        self.state.mkdir(parents=True, exist_ok=True)
        self.deadline = time.monotonic() + 2400

    def read(self, name, default=None):
        path = self.state / (name + ".json")
        return load(path) if path.exists() else default

    def write(self, name, data):
        save(self.state / (name + ".json"), data)

    def record(self, status, **data):
        result = {"status": status, "revision": self.revision, "time": int(time.time()), **data}
        self.write("result", result)
        with (self.state / "history.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(result) + "\n")
        print(json.dumps(result), flush=True)

    def notify(self, status):
        try:
            aws("sns", "publish", "--topic-arn", self.config["sns_topic_arn"],
                "--subject", "KeepGo v1 " + status,
                "--message", json.dumps({"status": status, "revision": self.revision}), timeout=20)
        except Exception:
            # 이 알림이 실패해도 CloudWatch의 heartbeat 결측과 SSM 실패 알람은 별도로 동작한다.
            print("SNS notification failed; inspect SSM / CloudWatch", file=sys.stderr)

    def compose(self, release, *args, timeout=240):
        path = self.state / (fingerprint(release["compose"]) + ".compose.json")
        if not path.exists():
            save(path, release["compose"])
        return run("docker", "compose", "--project-name", "keepgo-v1", "-f", str(path), *args, timeout=timeout)

    def inspect(self, release):
        ids = self.compose(release, "ps", "--all", "--quiet").split()
        if not ids:
            return {}
        values = json.loads(run("docker", "inspect", *ids))
        return {v["Config"]["Labels"]["com.docker.compose.service"]: v for v in values}

    def check_actual(self, release, healthy=True):
        values = self.inspect(release)
        if set(values) != SERVICES:
            raise RuntimeError("Unexpected or missing containers")
        for service in SERVICES:
            actual = values[service]
            expected = release["compose"]["services"][service]["image"]
            if actual["Config"]["Image"] != expected:
                raise RuntimeError(f"Actual image drift: {service}")
            if healthy and (not actual["State"]["Running"] or
                            actual["State"].get("Health", {}).get("Status") != "healthy"):
                raise RuntimeError(f"Container not healthy: {service}")
        return values

    def wait_healthy(self, release):
        deadline = time.monotonic() + self.config["health_timeout_seconds"]
        while True:
            try:
                return self.check_actual(release)
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(5)

    def smoke(self, release):
        origin = self.config["public_origin"].rstrip("/")
        for path in ("/", "/api/health/ready"):
            with urllib.request.urlopen(origin + path, timeout=10) as response:
                if response.status != 200 or not response.url.startswith(origin + "/"):
                    raise RuntimeError("External HTTPS smoke failed")
        # 앱 담당 검증: 제한 시간 안에 DB job 생성, Worker와 AI 처리, 완료 결과를 확인한다.
        output = self.compose(release, "exec", "-T", "backend", "/app/bin/smokecheck", timeout=120)
        if json.loads(output).get("ok") is not True:
            raise RuntimeError("Application smoke contract failed")

    def verify(self, release, check_alarms=True):
        baseline = self.wait_healthy(release)
        self.smoke(release)
        deadline = time.monotonic() + self.config["bake_seconds"]
        while time.monotonic() < deadline:
            time.sleep(5)
            current = self.check_actual(release)
            if any(current[s]["RestartCount"] != baseline[s]["RestartCount"] or
                   current[s]["Id"] != baseline[s]["Id"] for s in SERVICES):
                raise RuntimeError("Container restarted during observation")
        self.smoke(release)
        if check_alarms:
            self.check_alarms()

    def check_alarms(self):
        names = self.config["deployment_alarm_names"]
        alarms = aws_json("cloudwatch", "describe-alarms", "--alarm-names", *names)["MetricAlarms"]
        if {alarm["AlarmName"] for alarm in alarms} != set(names) or any(a["StateValue"] != "OK" for a in alarms):
            raise RuntimeError("A deployment alarm is missing, not OK, or has insufficient data")

    def replace(self, stop_release, target, services):
        # 교체 대상의 기존 컨테이너를 모두 중지한 뒤 새 컨테이너를 시작한다.
        self.compose(stop_release, "stop", *reversed(services), timeout=180)
        for service in services:
            self.compose(target, "up", "-d", "--no-deps", "--force-recreate", service, timeout=60)
        # Nginx 컨테이너를 재시작하지 않고 교체된 upstream 주소를 다시 읽는다.
        if "nginx" not in services and {"web", "backend"}.intersection(services):
            self.compose(target, "exec", "-T", "nginx", "nginx", "-s", "reload")

    def prepare(self):
        manifest = load(self.root / "deployment/production-manifest.json")
        validate_manifest(manifest)
        config = render_compose(self.root, manifest, self.config["aws_account_id"])
        images = resolve_images(manifest, load(self.root / "deployment/source-policy.json"), self.config["aws_account_id"])
        for service, image in images.items():
            config["services"][service]["image"] = image
        return {"revision": self.revision, "manifest": manifest, "compose": config}

    def login(self):
        token = aws("ecr", "get-login-password").strip()
        run("docker", "login", "--username", "AWS", "--password-stdin",
            self.config["aws_account_id"] + ".dkr.ecr.ap-northeast-2.amazonaws.com", input=token)

    def transact(self, old, target, services):
        intent = {"started": int(time.time()), "services": services, "old": old, "target": target}
        self.write("inflight", intent)
        try:
            self.replace(old or target, target, services)
            self.verify(target)
            if old:
                self.write("previous", old)
            self.write("current", target)
            (self.state / "inflight.json").unlink()
            self.record("success", services=services)
            return 0
        except Exception as error:
            blocked = self.read("blocked", {"images": [], "releases": []})
            # 변경된 실패 이미지와 서비스 설정을 차단하고 실패한 전체 구성의 해시도 기록한다.
            blocked["images"] = sorted(set(blocked["images"]) | {
                target["compose"]["services"][s]["image"] for s in services
                if old is None or target["compose"]["services"][s]["image"] != old["compose"]["services"][s]["image"]})
            blocked["releases"] = sorted(set(blocked["releases"]) | {fingerprint(target["compose"])})
            blocked["configurations"] = sorted(set(blocked.get("configurations", [])) | {
                s + ":" + fingerprint(target["compose"]["services"][s]) for s in services
                if old is None or target["compose"]["services"][s] != old["compose"]["services"][s]})
            self.write("blocked", blocked)
            self.record("deploy_failed", services=services, error=type(error).__name__)
            try:
                if old is None:
                    self.compose(target, "stop", *reversed(services))
                    raise RuntimeError("First deployment has no verified rollback target")
                self.replace(target, old, services)
                self.verify(old, check_alarms=False)
                self.write("current", old)
                (self.state / "inflight.json").unlink()
                self.record("rolled_back", services=services)
                self.notify("deploy_failed_rollback_succeeded")
            except Exception as recovery_error:
                self.write("frozen", {"reason": "rollback_failed_or_first_deploy", "time": int(time.time())})
                self.record("rollback_failed", error=type(recovery_error).__name__)
                self.notify("CRITICAL_rollback_failed")
            return 1

    def deploy(self):
        if self.read("frozen") or self.read("inflight"):
            raise RuntimeError("Deployment frozen or interrupted transaction requires recovery")
        old = self.read("current")
        target = self.prepare()
        blocked = self.read("blocked", {"images": [], "releases": []})
        if fingerprint(target["compose"]) in blocked["releases"] or any(
                target["compose"]["services"][s]["image"] in blocked["images"] or
                s + ":" + fingerprint(target["compose"]["services"][s]) in blocked.get("configurations", [])
                for s in SERVICES):
            raise RuntimeError("Release includes a failed image/configuration; reconcile manifest or publish a fix")
        services = changed_services(old, target)
        self.check_alarms()
        if old:
            self.check_actual(old, healthy=False)
        elif self.inspect(target):
            raise RuntimeError("Existing unmanaged containers; bootstrap/adoption required")
        if not services:
            self.verify(target)
            self.write("current", target)
            self.record("noop")
            return 0
        self.login()
        self.compose(target, "pull", *services, timeout=300)
        # 서비스 중단 전에 이전 이미지도 받아 복구 시 다운로드에 의존하지 않는다.
        if old:
            self.compose(old, "pull", *services, timeout=300)
        if old is None:
            if time.monotonic() > self.deadline:
                raise TimeoutError("Preflight exhausted deployment time budget")
            return self.transact(None, target, services)
        # 각 단위의 성공 상태를 독립적으로 기록한다.
        # 뒤따른 Worker 실패로 이미 검증된 Backend 배포를 되돌리지 않는다.
        current = old
        for group in ("ai", "backend", "worker", "frontend"):
            members = [s for s in ORDER if s in GROUPS[group] and s in services]
            if not members:
                continue
            if time.monotonic() > self.deadline:
                raise TimeoutError("Deployment budget exhausted; earlier verified units remain applied")
            next_release = copy.deepcopy(current)
            next_release["revision"] = target["revision"]
            for service in members:
                next_release["compose"]["services"][service] = target["compose"]["services"][service]
                next_release["manifest"]["images"][service] = target["manifest"]["images"][service]
            next_release["manifest"]["sources"][group] = target["manifest"]["sources"][group]
            if self.transact(current, next_release, members):
                return 1
            current = next_release
        self.record("success", services=services)
        return 0

    def recover(self, mode):
        inflight = self.read("inflight")
        target = inflight["old"] if inflight else self.read("previous" if mode == "rollback" else "current")
        if target is None:
            raise RuntimeError("No verified recovery target. Follow initial deployment runbook")
        actual = inflight["target"] if inflight else self.read("current", target)
        services = inflight["services"] if inflight else changed_services(actual, target)
        self.write("frozen", {"reason": "recovery_in_progress"})
        if not inflight:
            self.write("inflight", {"started": int(time.time()), "old": target,
                                    "target": actual, "services": services})
        if mode == "rollback":
            blocked = self.read("blocked", {"images": [], "releases": []})
            blocked["images"] = sorted(set(blocked["images"]) | {
                actual["compose"]["services"][s]["image"] for s in services
                if actual["compose"]["services"][s]["image"] != target["compose"]["services"][s]["image"]})
            blocked["releases"] = sorted(set(blocked["releases"]) | {fingerprint(actual["compose"])})
            self.write("blocked", blocked)
        if services:
            self.replace(actual, target, services)
        self.verify(target, check_alarms=False)
        self.write("current", target)
        (self.state / "inflight.json").unlink()
        # 배포 목표를 실제 상태와 맞추고 운영자가 재개할 때까지 동결을 유지한다.
        self.write("frozen", {"reason": "recovered_reconcile_before_resume"})
        self.record("recovered", services=services)
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/opt/keepgo/runtime.json")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--mode", choices=["deploy", "rollback", "recover", "resume", "freeze"], default="deploy")
    args = parser.parse_args()
    config = load(args.config)
    if args.mode != "freeze" and config.get("app_checks_confirmed") is not True:
        raise ValueError("App health/smoke/queue contracts are unconfirmed; deployment and recovery verification are not enabled")
    if not re.fullmatch(r"[0-9]{12}", config["aws_account_id"]) or not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ValueError("Valid account and Cloud commit required")
    if not config["public_origin"].startswith("https://") or "CONFIGURE" in json.dumps(config):
        raise ValueError("Complete runtime.json before deploying")
    for key, low, high in [("health_timeout_seconds", 30, 300), ("bake_seconds", 30, 300)]:
        if not low <= config[key] <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    if not 1 <= len(config.get("deployment_alarm_names", [])) <= 20:
        raise ValueError("Configure the deployment alarm names")
    engine = Engine(ROOT, config, args.revision)
    def interrupted(signum, frame):
        raise RuntimeError("Deployment process interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with lock(engine.state):
        try:
            if args.mode == "freeze":
                engine.write("frozen", {"reason": "operator"})
                engine.record("frozen")
                return 0
            if args.mode == "resume":
                if engine.read("inflight"):
                    raise RuntimeError("Recover interrupted deployment first")
                current = engine.read("current")
                target = engine.prepare()
                if current is None or changed_services(current, target):
                    raise RuntimeError("Reconcile desired manifest/config with verified actual state first")
                engine.verify(current)
                (engine.state / "frozen.json").unlink(missing_ok=True)
                engine.record("resumed")
                return 0
            return engine.deploy() if args.mode == "deploy" else engine.recover(args.mode)
        except Exception as error:
            engine.record("rejected", error=str(error))
            engine.notify("deployment_rejected")
            return 1


if __name__ == "__main__":
    sys.exit(main())
