"""Docker daemon/AWS/실제 Secret 없이 배포 경계와 로그 전환 계약을 검사한다."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def compose(*files):
    env = dict(os.environ, AWS_ACCOUNT_ID="000000000000")
    env.update({key: "a" * 40 for key in (
        "NGINX_IMAGE_TAG", "WEB_IMAGE_TAG", "BACKEND_IMAGE_TAG", "AI_IMAGE_TAG")})
    command = ["docker", "compose"]
    for file in files:
        command.extend(["-f", file])
    command.extend(["config", "--no-env-resolution", "--format", "json"])
    result = subprocess.run(command, cwd=ROOT, env=env, check=True,
                            capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


class MonitoringContractTest(unittest.TestCase):
    def test_log_opt_in_changes_only_logging_and_removes_incompatible_options(self):
        base = compose("compose.yaml")
        enabled = compose("compose.yaml", "compose.cloudwatch.yaml")
        self.assertEqual(set(base["services"]), set(enabled["services"]))
        for name, service in base["services"].items():
            updated = enabled["services"][name]
            self.assertEqual(service.pop("logging")["driver"], "json-file")
            log = updated.pop("logging")
            self.assertEqual(log["driver"], "awslogs")
            self.assertNotIn("max-size", log["options"])
            self.assertNotIn("max-file", log["options"])
            self.assertEqual(log["options"]["mode"], "non-blocking")
            self.assertEqual(log["options"]["awslogs-create-group"], "false")
            self.assertEqual(service, updated, name)

    def test_monitoring_is_separate_and_management_ports_are_loopback(self):
        app = compose("compose.yaml")
        monitoring = compose("compose.monitoring.yaml")
        self.assertNotEqual(app["name"], monitoring["name"])
        for name, service in monitoring["services"].items():
            for port in service.get("ports", []):
                self.assertEqual(port["host_ip"], "127.0.0.1", name)
            self.assertNotIn(":latest", service["image"])
            self.assertIn("mem_limit", service)
            self.assertFalse(service.get("privileged", False))
            for volume in service.get("volumes", []):
                self.assertNotIn("docker.sock", volume.get("source", ""))
        for name in ("web", "service"):
            linked = monitoring["networks"][f"app-{name}"]
            self.assertTrue(linked["external"])
            self.assertEqual(linked["name"], app["networks"][name]["name"])

    def test_dashboards_and_alerts_use_the_provisioned_datasource(self):
        base = ROOT / "monitoring/grafana"
        dashboard_ids = []
        for path in (base / "dashboards").glob("*.json"):
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            dashboard_ids.append(dashboard["uid"])
            self.assertEqual(len({panel["id"] for panel in dashboard["panels"]}), len(dashboard["panels"]))
            for panel in dashboard["panels"]:
                self.assertEqual(panel["datasource"]["uid"], "keepgo-prometheus")
        self.assertEqual(len(dashboard_ids), len(set(dashboard_ids)))
        rule_ids = []
        for path in (base / "provisioning/alerting").glob("*.json"):
            rules = json.loads(path.read_text(encoding="utf-8"))
            for group in rules["groups"]:
                for rule in group["rules"]:
                    rule_ids.append(rule["uid"])
                    refs = {query["refId"] for query in rule["data"]}
                    self.assertIn(rule["condition"], refs)
                    # No firing application alert is normal; an unreachable monitoring backend is not.
                    expected = "OK" if rule["uid"] == "keepgo-application" else "Alerting"
                    self.assertEqual(rule["noDataState"], expected)
                    self.assertEqual(rule["execErrState"], "Alerting")
                    self.assertEqual(rule["data"][0]["datasourceUid"], "keepgo-prometheus")
        self.assertEqual(len(rule_ids), len(set(rule_ids)))


if __name__ == "__main__":
    unittest.main()
