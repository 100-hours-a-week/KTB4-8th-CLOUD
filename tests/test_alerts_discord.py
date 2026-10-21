import json
import os
from pathlib import Path
import re
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "infrastructure/alerts-discord.yaml").read_text(encoding="utf-8")
V1, V2 = "arn:aws:sns:ap-northeast-2:1:keepgo-v1-alerts", "arn:aws:sns:ap-northeast-2:1:keepgo-v2-alerts"


def load_relay():
    """Run the inline Lambda code from the template, so tests cover what CloudFormation deploys."""
    block = re.search(r"ZipFile: \|\n((?: {10}.*\n|\n)+)", TEMPLATE).group(1)
    code = "\n".join(line[10:] for line in block.splitlines())
    module = types.ModuleType("relay")
    with mock.patch.dict(sys.modules, {"boto3": types.ModuleType("boto3")}), \
            mock.patch.dict(os.environ, {"LABELS": json.dumps({V1: "PROD", V2: "DEV"}), "AWS_REGION": "ap-northeast-2"}):
        exec(compile(code, "alerts-discord-inline", "exec"), module.__dict__)
    return module, code


relay, CODE = load_relay()


def record(topic, message, subject=None):
    return {"Sns": {"TopicArn": topic, "Subject": subject,
                    "Message": message if isinstance(message, str) else json.dumps(message)}}


def alarm(new, old, name="keepgo-v2-rds-storage"):
    return {"AlarmName": name, "NewStateValue": new, "OldStateValue": old, "NewStateReason": "Threshold Crossed",
            "StateChangeTime": "2026-10-21T08:00:00.000+0000", "Region": "Asia Pacific (Seoul)"}


class AlertsDiscordTest(unittest.TestCase):
    def test_inline_code_fits_cloudformation_zipfile_limit(self):
        self.assertLess(len(CODE), 4096)

    def test_alarm_and_recovery_are_labeled_by_topic(self):
        fired = relay.embed(record(V2, alarm("ALARM", "OK")))
        self.assertEqual(fired["title"], "[DEV] 🚨 경보 keepgo-v2-rds-storage")
        self.assertEqual(fired["color"], relay.COLORS["ALARM"])
        self.assertIn("#alarmsV2:alarm/keepgo-v2-rds-storage", fired["url"])
        recovered = relay.embed(record(V1, alarm("OK", "ALARM", "keepgo-v1-ec2-disk")))
        self.assertEqual(recovered["title"], "[PROD] ✅ 복구 keepgo-v1-ec2-disk")

    def test_insufficient_data_noise_is_dropped(self):
        self.assertIsNone(relay.embed(record(V2, alarm("INSUFFICIENT_DATA", "OK"))))
        self.assertIsNone(relay.embed(record(V2, alarm("OK", "INSUFFICIENT_DATA"))))
        self.assertIsNotNone(relay.embed(record(V2, alarm("INSUFFICIENT_DATA", "ALARM"))))

    def test_ecs_deployment_failure_names_service(self):
        event = {"source": "aws.ecs", "time": "2026-10-21T08:00:00Z",
                 "resources": ["arn:aws:ecs:ap-northeast-2:1:service/keepgo-v2/keepgo-v2-backend"],
                 "detail": {"eventName": "SERVICE_DEPLOYMENT_FAILED", "deploymentId": "ecs-svc/1", "reason": "circuit breaker"}}
        result = relay.embed(record(V2, event))
        self.assertEqual(result["title"], "[DEV] 🚨 배포 실패·롤백 keepgo-v2-backend")
        self.assertEqual(result["description"], "circuit breaker")

    def test_unknown_message_is_forwarded_truncated(self):
        result = relay.embed(record(V1, "x" * 3000, subject="hello"))
        self.assertEqual(result["title"], "[PROD] hello")
        self.assertEqual(len(result["description"]), 1500)

    def test_handler_posts_once_and_skips_empty(self):
        with mock.patch.object(relay, "post") as post:
            self.assertEqual(relay.handler({"Records": [record(V2, alarm("OK", "INSUFFICIENT_DATA"))]}, None), {"sent": 0})
            post.assert_not_called()
            relay.handler({"Records": [record(V2, alarm("ALARM", "OK"))]}, None)
            body = post.call_args.args[0]
            self.assertEqual(body["username"], "CloudWatch")
            self.assertEqual(len(body["embeds"]), 1)


if __name__ == "__main__":
    unittest.main()
