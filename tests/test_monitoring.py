"""Docker daemon/AWS/실제 Secret 없이 배포 경계와 로그 전환 계약을 검사한다."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def compose(*files):
    env = dict(os.environ, AWS_ACCOUNT_ID="000000000000", APP_HOST_PRIVATE_IP="10.0.0.10")
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

    def test_monitoring_host_is_separate_and_management_ports_are_loopback(self):
        app = compose("compose.yaml")
        monitoring = compose("compose.monitoring.yaml")
        exporters = compose("compose.exporters.yaml")
        self.assertEqual(len({app["name"], monitoring["name"], exporters["name"]}), 3)
        self.assertEqual(set(monitoring["services"]), {"prometheus", "grafana"})
        for name, service in monitoring["services"].items():
            self.assertEqual(service["platform"], "linux/arm64", name)
            for port in service.get("ports", []):
                self.assertEqual(port["host_ip"], "127.0.0.1", name)
        # 모니터링 EC2에는 앱 Docker 네트워크가 없다. 앱은 app-host 이름으로만 찾는다.
        self.assertEqual(set(monitoring["networks"]), {"monitoring"})
        # Compose 버전에 따라 "host=ip" 또는 "host:ip"로 출력한다.
        hosts = [entry.replace(":", "=", 1) for entry in monitoring["services"]["prometheus"]["extra_hosts"]]
        self.assertIn("app-host=10.0.0.10", hosts)
        for name, service in {**monitoring["services"], **exporters["services"]}.items():
            self.assertNotIn(":latest", service["image"])
            self.assertIn("mem_limit", service)
            self.assertFalse(service.get("privileged", False))
            for volume in service.get("volumes", []):
                self.assertNotIn("docker.sock", volume.get("source", ""))
        for name in ("web", "service"):
            linked = exporters["networks"][f"app-{name}"]
            self.assertTrue(linked["external"])
            self.assertEqual(linked["name"], app["networks"][name]["name"])

    def test_app_host_publishes_only_scrape_ports(self):
        # 모니터링 SG에만 여는 포트. API 포트(BE 8080, AI 8000)는 게시하지 않는다(TD-024).
        def published(project, service):
            return {port["target"] for port in project["services"][service].get("ports", [])}
        app = compose("compose.yaml")
        exporters = compose("compose.exporters.yaml")
        self.assertEqual(published(app, "backend"), {8081})
        self.assertEqual(published(app, "ai-api"), {9464})
        self.assertEqual(published(exporters, "node-exporter"), {9100})
        self.assertEqual(published(exporters, "blackbox-exporter"), {9115})

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
