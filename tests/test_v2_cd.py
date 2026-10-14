"""Exercise the real V2 release/deployment logic against in-memory AWS/GitHub APIs."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from v2_common import Error, Pending, candidate, image_uri, load_config, successful_run, task_payload, verify_provenance
from v2_deploy import Deployer
from v2_release import blocked
from configure_v2_iam import add_subject, ADDITIONS

CONFIG = load_config()
COMMIT = "a" * 40
OLD = "sha256:" + "1" * 64
NEW = "sha256:" + "2" * 64
PREVIOUS = "arn:aws:ecs:ap-northeast-2:602601433533:task-definition/keepgo-v2-backend:1"
TARGET = PREVIOUS[:-1] + "2"


class FakeGitHub:
    def __init__(self):
        self.runs = [{"id": 7, "run_attempt": 1, "head_sha": COMMIT, "head_branch": "develop",
                      "event": "push", "status": "completed", "conclusion": "success"}]
        self.published = True

    def get(self, path):
        if "/commits/" in path:
            return {"sha": COMMIT}
        return {"workflow_runs": self.runs}

    def jobs(self, repo, run_id, attempt):
        return [{"name": "Dev - Build and Push Image", "conclusion": "success" if self.published else "skipped"}]


class FakeAWS:
    def __init__(self):
        self.calls = []
        self.record = None
        self.revision = PREVIOUS
        self.digest = OLD
        self.tag_digest = NEW
        self.fail_new = False
        self.fail_rollback = False
        self.unhealthy_target = False
        self.external_writer = False
        self.definition = {
            "taskDefinitionArn": PREVIOUS, "revision": 1, "status": "ACTIVE",
            "family": "keepgo-v2-backend", "networkMode": "awsvpc",
            "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
            "taskRoleArn": "arn:aws:iam::602601433533:role/keepgo-v2-backend-task",
            "executionRoleArn": "arn:aws:iam::602601433533:role/keepgo-v2-backend-exec",
            "volumes": [{"name": "jwt"}],
            "containerDefinitions": [
                {"name": "jwt-files", "image": "busybox:1.37", "essential": False,
                 "secrets": [{"name": "JWT_PRIVATE_KEY", "valueFrom": "secret-arn"}]},
                {"name": "backend", "image": "registry/keepgo-backend:old", "healthCheck": {"command": ["CMD", "health"]},
                 "secrets": [{"name": "DB_PASSWORD", "valueFrom": "db-secret-arn"}],
                 "dependsOn": [{"containerName": "jwt-files", "condition": "SUCCESS"}]}
            ]}
        self.payload = None

    def call(self, api_service, operation, **options):
        self.calls.append((api_service, operation, copy.deepcopy(options)))
        if operation == "get-caller-identity":
            return {"Account": CONFIG["account_id"]}
        if operation == "describe-images":
            return {"imageDetails": [{"imageDigest": self.tag_digest}]}
        if operation == "get-parameter":
            if self.record is None:
                raise Error("ParameterNotFound")
            return {"Parameter": {"Value": json.dumps(self.record)}}
        if operation == "put-parameter":
            self.record = json.loads(options["value"])
            return {}
        if operation == "describe-services":
            failed = self.fail_new and self.revision == TARGET
            return {"services": [{
                "status": "ACTIVE", "desiredCount": 1, "runningCount": 1, "pendingCount": 0,
                "taskDefinition": self.revision, "deploymentController": {"type": "ECS"},
                "deploymentConfiguration": {"deploymentCircuitBreaker": {"enable": True, "rollback": True}},
                "deployments": [{"taskDefinition": self.revision, "rolloutState": "FAILED" if failed else "COMPLETED"}],
                "loadBalancers": [{"containerName": "backend", "containerPort": 8080, "targetGroupArn": "tg"}]
            }]}
        if operation == "describe-task-definition":
            return {"taskDefinition": copy.deepcopy(self.definition), "tags": [{"key": "owner", "value": "terraform"}]}
        if operation == "list-tasks":
            return {"taskArns": ["task-1"]}
        if operation == "describe-tasks":
            return {"tasks": [{"taskDefinitionArn": self.revision, "lastStatus": "RUNNING", "healthStatus": "HEALTHY",
                               "containers": [{"name": "backend", "healthStatus": "HEALTHY", "imageDigest": self.digest}],
                               "attachments": [{"details": [{"name": "privateIPv4Address", "value": "10.0.1.1"}]}]}]}
        if operation == "describe-target-health":
            return {"TargetHealthDescriptions": [
                {"Target": {"Id": "10.0.1.1", "Port": 8080}, "TargetHealth": {"State": "unhealthy" if self.unhealthy_target else "healthy"}},
                {"Target": {"Id": "10.0.2.9", "Port": 8080}, "TargetHealth": {"State": "healthy"}}]}
        if operation == "register-task-definition":
            self.payload = options["payload"]
            if self.external_writer:
                self.revision = PREVIOUS[:-1] + "99"
            return {"taskDefinition": {"taskDefinitionArn": TARGET}}
        if operation == "update-service":
            if self.fail_rollback and options["task_definition"] == PREVIOUS:
                raise Error("Recovery unavailable")
            self.revision = options["task_definition"]
            self.digest = NEW if self.revision == TARGET else OLD
            if self.revision == TARGET:
                self.definition.update(taskDefinitionArn=TARGET, revision=2)
                self.definition["containerDefinitions"][1]["image"] = image_uri(CONFIG, CONFIG["groups"]["backend"], NEW)
            return {}
        raise AssertionError((api_service, operation, options))


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.aws, self.gh = FakeAWS(), FakeGitHub()
        self.manifest = candidate(self.gh, self.aws, CONFIG, "backend")
        self.deployer = Deployer(self.aws, CONFIG, "backend", timeout=1, observe=0, poll=0)

    def writes(self):
        return [c[1] for c in self.aws.calls if c[1] in {"put-parameter", "register-task-definition", "update-service"}]

    def test_latest_failed_run_does_not_fall_back_to_old_success(self):
        self.gh.runs.append(dict(self.gh.runs[0], id=8, conclusion="failure"))
        self.assertIsNone(candidate(self.gh, self.aws, CONFIG, "backend"))

    def test_running_run_does_not_publish(self):
        self.gh.runs[0]["status"] = "in_progress"
        with self.assertRaises(Pending):
            candidate(self.gh, self.aws, CONFIG, "backend")

    def test_skipped_publishing_job_does_not_publish(self):
        self.gh.published = False
        self.assertIsNone(candidate(self.gh, self.aws, CONFIG, "backend"))

    def test_ci_branch_mismatch_rejected(self):
        self.gh.runs[0]["head_branch"] = "main"
        with self.assertRaisesRegex(Error, "provenance"):
            candidate(self.gh, self.aws, CONFIG, "backend")

    def test_retag_after_release_rejected(self):
        self.aws.tag_digest = OLD
        with self.assertRaisesRegex(Error, "tag changed"):
            verify_provenance(self.gh, self.aws, CONFIG, "backend", self.manifest)

    def test_new_run_attempt_requires_new_manifest(self):
        self.gh.runs[0]["run_attempt"] = 2
        with self.assertRaisesRegex(Error, "attempt"):
            verify_provenance(self.gh, self.aws, CONFIG, "backend", self.manifest)

    def test_wrong_repository_image_rejected(self):
        self.manifest["image"] = self.manifest["image"].replace("keepgo-backend", "keepgo-ai")
        with self.assertRaisesRegex(Error, "repository mismatch"):
            verify_provenance(self.gh, self.aws, CONFIG, "backend", self.manifest)

    def test_read_only_preflight_has_no_writes(self):
        self.deployer.deploy(self.manifest)
        self.assertEqual(self.writes(), [])

    def test_success_preserves_sidecar_secrets_and_records_actual_revision(self):
        before = copy.deepcopy(self.aws.definition)
        self.deployer.deploy(self.manifest, execute=True)
        self.assertEqual(self.aws.record["phase"], "succeeded")
        self.assertEqual(self.aws.record["revision"], TARGET)
        self.assertEqual(self.aws.payload["containerDefinitions"][0], before["containerDefinitions"][0])
        self.assertEqual(self.aws.payload["containerDefinitions"][1]["secrets"], before["containerDefinitions"][1]["secrets"])
        self.assertEqual(self.aws.payload["tags"], [{"key": "owner", "value": "terraform"}])
        self.assertNotIn("revision", self.aws.payload)
        self.assertLess(self.writes().index("put-parameter"), self.writes().index("update-service"))

    def test_already_deployed_version_noops(self):
        self.deployer.deploy(self.manifest, execute=True)
        self.aws.calls.clear()
        self.deployer.deploy(self.manifest, execute=True)
        self.assertEqual(self.writes(), [])

    def test_failure_rolls_back_and_blocks_automatic_retry(self):
        self.aws.fail_new = True
        with self.assertRaisesRegex(Error, "previous revision recovered"):
            self.deployer.deploy(self.manifest, execute=True)
        self.assertEqual(self.aws.revision, PREVIOUS)
        self.assertTrue(self.aws.record["recovered"])
        self.aws.calls.clear()
        with self.assertRaisesRegex(Error, "Failed image is blocked"):
            self.deployer.deploy(self.manifest, execute=True)
        self.assertEqual(self.writes(), [])

    def test_rollback_failure_blocks_different_candidate_too(self):
        self.aws.fail_new = self.aws.fail_rollback = True
        with self.assertRaisesRegex(Error, "recovery unverified"):
            self.deployer.deploy(self.manifest, execute=True)
        self.assertFalse(self.aws.record["recovered"])
        self.manifest["image"] = image_uri(CONFIG, CONFIG["groups"]["backend"], OLD)
        with self.assertRaisesRegex(Error, "explicit recovery"):
            self.deployer.deploy(self.manifest, execute=True)

    def test_interruption_blocks_before_any_ecs_update(self):
        self.aws.record = {"phase": "deploying"}
        with self.assertRaisesRegex(Error, "explicit recovery"):
            self.deployer.deploy(self.manifest, execute=True)
        self.assertEqual(self.writes(), [])

    def test_recovery_preserves_failed_image_block(self):
        self.aws.record = {"phase": "deploying", "image": self.manifest["image"],
                           "previous_revision": PREVIOUS, "previous_digest": OLD, "target_revision": TARGET}
        self.aws.revision, self.aws.digest = TARGET, NEW
        self.deployer.recover(True)
        self.assertEqual(self.aws.revision, PREVIOUS)
        self.assertEqual(self.aws.record["phase"], "failed")
        self.assertTrue(self.aws.record["recovered"])

    def test_external_writer_is_not_overwritten_during_failure(self):
        self.aws.external_writer = True
        with self.assertRaisesRegex(Error, "another writer"):
            self.deployer.deploy(self.manifest, execute=True)
        self.assertNotIn("update-service", self.writes())

    def test_unrelated_healthy_alb_target_is_insufficient(self):
        self.aws.unhealthy_target = True
        with self.assertRaisesRegex(Error, "ALB targets"):
            self.deployer.deploy(self.manifest, execute=True)
        self.assertEqual(self.writes(), [])

    def test_unknown_task_field_is_not_silently_dropped(self):
        self.aws.definition["newAwsField"] = True
        with self.assertRaisesRegex(Error, "Unknown task definition"):
            self.deployer.deploy(self.manifest)

    def test_stable_previous_revision_is_not_target_success(self):
        with self.assertRaisesRegex(Error, "rolled back"):
            self.deployer.wait(TARGET, NEW)

    def test_release_does_not_redispatch_failed_or_interrupted_candidate(self):
        self.assertTrue(blocked({"phase": "deploying"}, self.manifest))
        self.assertTrue(blocked({"phase": "failed", "recovered": True, "image": self.manifest["image"]}, self.manifest))
        self.assertTrue(blocked({"phase": "failed", "recovered": False, "image": "older"}, self.manifest))
        self.assertFalse(blocked({"phase": "failed", "recovered": True, "image": "older"}, self.manifest))

    def test_iam_addition_preserves_existing_conditions_and_is_idempotent(self):
        original = {"Sid": "ExistingProduction", "Condition": {"StringEquals": {"subject": "main"}}}
        policy = {"Version": "2012-10-17", "Statement": [copy.deepcopy(original)]}
        for _ in range(2):
            add_subject(policy, ADDITIONS["keepgo-be-ecr-push"])
        self.assertEqual(policy["Statement"][0], original)
        self.assertEqual(len(policy["Statement"]), 2)

    def test_iam_conflicting_statement_is_not_overwritten(self):
        policy = {"Statement": [{"Sid": "DevelopImagePublishing", "Condition": {}}]}
        with self.assertRaisesRegex(Error, "differs"):
            add_subject(policy, ADDITIONS["keepgo-be-ecr-push"])


if __name__ == "__main__":
    unittest.main()
