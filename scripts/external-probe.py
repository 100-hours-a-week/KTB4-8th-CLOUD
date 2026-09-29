#!/usr/bin/env python3
import json
import os
import urllib.request
from release import aws

origin = os.environ["PUBLIC_ORIGIN"].rstrip("/")
healthy = 1
try:
    if not origin.startswith("https://"):
        raise ValueError("HTTPS required")
    for path in ("/", "/healthz"):
        with urllib.request.urlopen(origin + path, timeout=10) as response:
            if response.status != 200 or not response.url.startswith(origin + "/"):
                raise RuntimeError("Probe failed")
except Exception:
    healthy = 0
aws("cloudwatch", "put-metric-data", "--namespace", "KeepGo/V1", "--metric-data", json.dumps([{
    "MetricName": "ExternalHealthy", "Value": healthy,
    "Dimensions": [{"Name": "InstanceId", "Value": os.environ["PRODUCTION_EC2_INSTANCE_ID"]}]}]))
if not healthy:
    raise SystemExit("External HTTPS probe failed")
