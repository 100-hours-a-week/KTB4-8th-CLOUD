import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("discovery", ROOT / "scripts/discover-dev-metrics.py")
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)
PROD = discovery.ENVIRONMENTS["development.json"]
DEV = discovery.ENVIRONMENTS["v2-dev.json"]


class DiscoveryTest(unittest.TestCase):
    def reader(self, ip="10.20.10.81", failed=False, cluster="keepgo-v2"):
        service = cluster + "-backend"
        def read(operation, *args):
            if operation == "list-tasks":
                return {"taskArns": ["task"] if service in args else []}
            return {"failures": [{"reason": "MISSING"}] if failed else [], "tasks": [{
                "group": "service:" + service, "lastStatus": "RUNNING", "desiredStatus": "RUNNING",
                "containers": [{"name": "jwt-files", "lastStatus": "STOPPED"}, {
                    "name": "backend", "lastStatus": "RUNNING", "networkInterfaces": [{"privateIpv4Address": ip}]}]}]}
        return read

    def test_only_running_application_container_is_targeted(self):
        targets = discovery.discover(PROD, self.reader())
        self.assertEqual(targets[0]["targets"], ["10.20.10.81:8081"])
        self.assertEqual(targets[0]["labels"]["environment"], "production")
        self.assertEqual(targets[0]["labels"]["__metrics_path__"], "/actuator/prometheus")
        self.assertEqual(len(targets), 1)

    def test_development_cluster_is_labeled_separately(self):
        targets = discovery.discover(DEV, self.reader(ip="10.30.11.77", cluster="keepgo-v2-dev"))
        self.assertEqual(targets[0]["targets"], ["10.30.11.77:8081"])
        self.assertEqual(targets[0]["labels"]["environment"], "development")
        self.assertEqual(targets[0]["labels"]["cluster"], "keepgo-v2-dev")

    def test_task_lookup_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            discovery.write_targets(path, [{"targets": ["old:8081"]}])
            before = path.read_bytes()
            with self.assertRaises(RuntimeError):
                discovery.write_targets(path, discovery.discover(PROD, self.reader(failed=True)))
            self.assertEqual(path.read_bytes(), before)

    def test_replacement_and_real_zero_tasks_remove_stale_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            discovery.write_targets(path, discovery.discover(PROD, self.reader()))
            discovery.write_targets(path, discovery.discover(PROD, self.reader(ip="10.20.11.150")))
            self.assertEqual(json.loads(path.read_text())[0]["targets"], ["10.20.11.150:8081"])
            discovery.write_targets(path, discovery.discover(PROD, lambda *args: {"taskArns": []}))
            self.assertEqual(json.loads(path.read_text()), [])

    def test_unapproved_network_is_rejected(self):
        with self.assertRaises(RuntimeError):
            discovery.discover(PROD, self.reader(ip="172.31.46.161"))
        # A production subnet must not be accepted for the development cluster.
        with self.assertRaises(RuntimeError):
            discovery.discover(DEV, self.reader(ip="10.20.10.81", cluster="keepgo-v2-dev"))

    def test_one_failing_cluster_keeps_its_file_and_refreshes_the_other(self):
        prod, dev = self.reader(), self.reader(failed=True, cluster="keepgo-v2-dev")
        def read(operation, *args):
            return (dev if "keepgo-v2-dev" in args else prod)(operation, *args)
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "v2-dev.json"
            discovery.write_targets(stale, [{"targets": ["old:8081"]}])
            before = stale.read_bytes()
            summary, failures = discovery.refresh(tmp, read)
            self.assertEqual(summary, {"keepgo-v2": 1})
            self.assertEqual(list(failures), ["keepgo-v2-dev"])
            self.assertEqual(stale.read_bytes(), before)
            self.assertEqual(json.loads((Path(tmp) / "development.json").read_text())[0]["targets"],
                             ["10.20.10.81:8081"])


if __name__ == "__main__":
    unittest.main()
