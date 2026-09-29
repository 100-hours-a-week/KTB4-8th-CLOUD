import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release
from deploy import Engine, main


def manifest():
    return {"environment": "production", "region": "ap-northeast-2",
            "images": {s: "a" * 40 for s in release.SERVICES},
            "sources": {g: {"sha": "a" * 40, "run_id": 1} for g in release.GROUPS}}


def snapshot():
    return {"revision": "a" * 40, "manifest": manifest(), "compose": {
        "services": {s: {"image": s + "@sha256:" + "a" * 64} for s in release.SERVICES},
        "networks": {"service": {"name": "keepgo-service"}}}}


class FakeEngine(Engine):
    def __init__(self, directory):
        super().__init__(directory, {"state_dir": directory}, "b" * 40)
        self.calls = []
        self.target = snapshot()
        self.fail_verify = 0
        self.fail_pull = False
        self.existing = {}

    def compose(self, value, *args, **kwargs):
        self.calls.append(("compose", args))
        if args[0] == "pull" and self.fail_pull:
            raise RuntimeError("pull failed")
        return ""

    def replace(self, old, target, services):
        self.calls.append(("replace", list(services), copy.deepcopy(target)))

    def verify(self, value, check_alarms=True):
        self.calls.append(("verify", value))
        if self.fail_verify:
            self.fail_verify -= 1
            raise RuntimeError("unhealthy")

    def check_actual(self, value, healthy=True):
        self.calls.append(("actual", value))
        return {}

    def prepare(self):
        return self.target

    def check_alarms(self):
        pass

    def login(self):
        self.calls.append(("login",))

    def inspect(self, value):
        return self.existing

    def notify(self, value):
        self.calls.append(("notify", value))


class ContractTests(unittest.TestCase):
    def test_unconfirmed_checks_reject_before_runtime_changes(self):
        for config in ({}, {"app_checks_confirmed": False}):
            with self.subTest(config=config), \
                 patch.object(sys, "argv", ["deploy.py", "--revision", "a" * 40]), \
                 patch("deploy.load", return_value=config), \
                 patch("deploy.Engine") as engine:
                with self.assertRaisesRegex(ValueError, "unconfirmed"):
                    main()
                engine.assert_not_called()

    def test_backend_and_worker_can_use_different_shas(self):
        m = manifest()
        m["images"]["worker"] = "b" * 40
        m["sources"]["worker"]["sha"] = "b" * 40
        release.validate_manifest(m)

    def test_frontend_mixed_pair_rejected(self):
        m = manifest()
        m["images"]["nginx"] = "b" * 40
        with self.assertRaises(ValueError):
            release.validate_manifest(m)

    def test_placeholder_is_not_deployable(self):
        m = manifest()
        for group, services in release.GROUPS.items():
            m["sources"][group] = {"sha": f"<{group.upper()}_COMMIT_SHA>", "run_id": 0}
            for service in services:
                m["images"][service] = m["sources"][group]["sha"]
        release.validate_manifest(m, structure_only=True)
        with self.assertRaises(ValueError):
            release.validate_manifest(m)

    def test_unexpected_service_rejected(self):
        m = manifest()
        m["images"]["queue"] = "a" * 40
        with self.assertRaises(ValueError):
            release.validate_manifest(m)

    def test_backend_only_plan(self):
        old, new = snapshot(), snapshot()
        new["compose"]["services"]["backend"]["image"] = "new"
        self.assertEqual(["backend"], release.changed_services(old, new))

    def test_worker_only_plan(self):
        old, new = snapshot(), snapshot()
        new["compose"]["services"]["worker"]["image"] = "new"
        self.assertEqual(["worker"], release.changed_services(old, new))

    def test_frontend_plan(self):
        old, new = snapshot(), snapshot()
        new["compose"]["services"]["web"]["image"] = "new"
        self.assertEqual(["web", "nginx"], release.changed_services(old, new))

    def test_config_change_is_deployed(self):
        old, new = snapshot(), snapshot()
        new["compose"]["services"]["ai-api"]["environment"] = {"NEW": "value"}
        self.assertEqual(["ai-api"], release.changed_services(old, new))

    def test_shared_network_change_requires_maintenance(self):
        old, new = snapshot(), snapshot()
        new["compose"]["networks"]["service"]["name"] = "changed"
        with self.assertRaises(ValueError):
            release.changed_services(old, new)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = FakeEngine(self.tmp.name)
        self.old = snapshot()
        self.engine.write("current", self.old)
        self.engine.target["compose"]["services"]["backend"]["image"] = "backend@sha256:" + "b" * 64

    def test_success_commits_verified_state(self):
        self.assertEqual(0, self.engine.deploy())
        self.assertEqual(self.old, self.engine.read("previous"))
        self.assertEqual(self.engine.target, self.engine.read("current"))
        self.assertIsNone(self.engine.read("inflight"))
        replacements = [c for c in self.engine.calls if c[0] == "replace"]
        self.assertEqual(["backend"], replacements[0][1])

    def test_failure_restores_and_blocks_only_failed_image(self):
        self.engine.fail_verify = 1
        self.assertEqual(1, self.engine.deploy())
        self.assertEqual(self.old, self.engine.read("current"))
        self.assertEqual("rolled_back", self.engine.read("result")["status"])
        self.assertEqual([self.engine.target["compose"]["services"]["backend"]["image"]], self.engine.read("blocked")["images"])
        with self.assertRaises(RuntimeError):
            self.engine.deploy()

    def test_rollback_failure_freezes_and_preserves_intent(self):
        self.engine.fail_verify = 2
        self.assertEqual(1, self.engine.deploy())
        self.assertIsNotNone(self.engine.read("frozen"))
        self.assertIsNotNone(self.engine.read("inflight"))
        with self.assertRaises(RuntimeError):
            self.engine.deploy()

    def test_pull_failure_does_not_stop_containers(self):
        self.engine.fail_pull = True
        with self.assertRaises(RuntimeError):
            self.engine.deploy()
        self.assertFalse(any(c[0] == "replace" for c in self.engine.calls))
        self.assertIsNone(self.engine.read("inflight"))

    def test_noop_still_checks_health(self):
        self.engine.target = self.old
        self.assertEqual(0, self.engine.deploy())
        self.assertTrue(any(c[0] == "verify" for c in self.engine.calls))
        self.assertFalse(any(c[0] == "replace" for c in self.engine.calls))

    def test_abandoned_transaction_blocks_next_deploy(self):
        self.engine.write("inflight", {"old": self.old})
        with self.assertRaises(RuntimeError):
            self.engine.deploy()

    def test_first_deploy_failure_has_no_invented_rollback(self):
        (self.engine.state / "current.json").unlink()
        self.engine.fail_verify = 1
        self.assertEqual(1, self.engine.deploy())
        self.assertIsNone(self.engine.read("current"))
        self.assertIsNotNone(self.engine.read("frozen"))

    def test_unmanaged_existing_containers_refused(self):
        (self.engine.state / "current.json").unlink()
        self.engine.existing = {"backend": {}}
        with self.assertRaises(RuntimeError):
            self.engine.deploy()

    def test_recovery_uses_old_snapshot_after_interruption(self):
        self.engine.write("inflight", {"old": self.old, "target": self.engine.target, "services": ["backend"]})
        self.assertEqual(0, self.engine.recover("recover"))
        self.assertEqual(self.old, self.engine.read("current"))
        self.assertIsNone(self.engine.read("inflight"))
        self.assertIsNotNone(self.engine.read("frozen"))

    def test_stop_precedes_start_and_backend_does_not_restart_worker(self):
        self.engine.replace = Engine.replace.__get__(self.engine)
        self.engine.replace(self.old, self.engine.target, ["backend"])
        calls = [c[1] for c in self.engine.calls if c[0] == "compose"]
        self.assertEqual(("stop", "backend"), calls[0])
        self.assertEqual(("up", "-d", "--no-deps", "--force-recreate", "backend"), calls[1])
        self.assertEqual(("exec", "-T", "nginx", "nginx", "-s", "reload"), calls[2])

    def test_new_fixed_image_can_deploy_after_failed_candidate(self):
        self.engine.fail_verify = 1
        self.engine.deploy()
        self.engine.target["compose"]["services"]["backend"]["image"] = "backend@sha256:" + "c" * 64
        self.assertEqual(0, self.engine.deploy())

    def test_worker_failure_preserves_successful_backend(self):
        self.engine.target["compose"]["services"]["worker"]["image"] = "worker-new"
        original_verify = self.engine.verify
        def verify(value, **kwargs):
            if value["compose"]["services"]["worker"]["image"] == "worker-new":
                raise RuntimeError("new worker unhealthy")
            original_verify(value)
        self.engine.verify = verify
        self.assertEqual(1, self.engine.deploy())
        current = self.engine.read("current")
        self.assertEqual(self.engine.target["compose"]["services"]["backend"], current["compose"]["services"]["backend"])
        self.assertEqual(self.old["compose"]["services"]["worker"], current["compose"]["services"]["worker"])

    def test_failed_config_not_retried_when_another_service_changes(self):
        self.engine.target = copy.deepcopy(self.old)
        self.engine.target["compose"]["services"]["backend"]["environment"] = {"BAD": "setting"}
        self.engine.fail_verify = 1
        self.assertEqual(1, self.engine.deploy())
        self.engine.target["compose"]["services"]["worker"]["image"] = "worker-new"
        with self.assertRaises(RuntimeError):
            self.engine.deploy()

    def test_frontend_config_failure_does_not_block_unchanged_nginx(self):
        self.engine.target = copy.deepcopy(self.old)
        self.engine.target["compose"]["services"]["web"]["environment"] = {"SETTING": "bad"}
        self.engine.fail_verify = 1
        self.assertEqual(1, self.engine.deploy())
        self.engine.target["compose"]["services"]["web"]["environment"] = {"SETTING": "fixed"}
        self.assertEqual(0, self.engine.deploy())

    def test_alarm_must_exist_and_be_ok(self):
        self.engine.config["deployment_alarm_names"] = ["errors"]
        with patch("deploy.aws_json", return_value={"MetricAlarms": []}):
            with self.assertRaises(RuntimeError):
                Engine.check_alarms(self.engine)
        with patch("deploy.aws_json", return_value={"MetricAlarms": [{"AlarmName": "errors", "StateValue": "ALARM"}]}):
            with self.assertRaises(RuntimeError):
                Engine.check_alarms(self.engine)

    def test_observation_detects_restarts(self):
        baseline = {s: {"Id": s, "RestartCount": 0} for s in release.SERVICES}
        current = copy.deepcopy(baseline)
        current["backend"]["RestartCount"] = 1
        self.engine.config["bake_seconds"] = 30
        with patch.object(self.engine, "wait_healthy", return_value=baseline), \
             patch.object(self.engine, "smoke"), \
             patch.object(self.engine, "check_actual", return_value=current), \
             patch("deploy.time.sleep"):
            with self.assertRaises(RuntimeError):
                Engine.verify(self.engine, self.old)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.policy = {"frontend": {"repository": "owner/frontend", "workflow": ".github/workflows/ci.yaml",
                                   "required_jobs": ["build", "test"]}}
        self.ci = {"head_sha": "a" * 40, "head_branch": "main", "event": "push", "status": "completed",
                   "conclusion": "success", "path": ".github/workflows/ci.yaml",
                   "head_repository": {"full_name": "owner/frontend"}}

    def test_skipped_job_rejected_even_if_workflow_successful(self):
        with patch("release.github", side_effect=[self.ci, {"sha": "a" * 40}, {"jobs": [
                {"name": "build", "conclusion": "success"}, {"name": "test", "conclusion": "skipped"}]}]):
            with self.assertRaises(ValueError):
                release.verify_source("frontend", {"sha": "a" * 40, "run_id": 1}, self.policy, "token")

    def test_outdated_source_sha_rejected(self):
        with patch("release.github", side_effect=[self.ci, {"sha": "b" * 40}]):
            with self.assertRaises(ValueError):
                release.verify_source("frontend", {"sha": "a" * 40, "run_id": 1}, self.policy, "token")

    def test_wrong_workflow_rejected(self):
        self.ci["path"] = ".github/workflows/untrusted.yaml"
        with patch("release.github", return_value=self.ci):
            with self.assertRaises(ValueError):
                release.verify_source("frontend", {"sha": "a" * 40, "run_id": 1}, self.policy, "token")


if __name__ == "__main__":
    unittest.main()
