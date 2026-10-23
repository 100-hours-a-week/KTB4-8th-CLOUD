#!/usr/bin/env python3
"""Reuse the existing HTTP/JVM dashboards and rules with an isolated job for the V2 ECS cluster.

The job, file and rule names still say "dev"; V2 became production on 2026-10-23, so labels and titles say
production while the names stay until the V1 instance is relabeled as development.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[1]


def expr_dev(text):
    text = text.replace('job="application"', 'job="application-dev"')
    text = text.replace("keepgo:", "keepgo_dev:")
    return re.sub(r"\b(by|on)\s*\(", r"\1 (environment, cluster, ", text)


def artifacts():
    original = runpy.run_path(str(ROOT / "scripts/render-app-monitoring.py"))["artifacts"]()
    result = {}
    for filename in ("application-http", "backend-runtime"):
        board = copy.deepcopy(original[f"monitoring/grafana/dashboards/{filename}.json"])
        board["uid"] += "-dev"
        board["title"] = "[PROD V2] " + board["title"]
        board["tags"] += ["production", "keepgo-v2"]
        board["description"] += " V2 ECS production (keepgo-v2) only; V1 queries remain unchanged."
        for panel in board["panels"]:
            for target in panel["targets"]:
                target["expr"] = expr_dev(target["expr"])
        result[f"monitoring/grafana/dashboards/dev-{filename}.json"] = json.dumps(board, indent=2) + "\n"
    relay = copy.deepcopy(original["monitoring/grafana/provisioning/alerting/application.json"])
    group = relay["groups"][0]
    group["name"] = "keepgo-development-relay"
    rule = group["rules"][0]
    rule.update(uid="keepgo-development", title="[PROD V2] KeepGo application signal")
    rule["labels"].update(environment="production", cluster="keepgo-v2")
    rule["annotations"]["summary"] = "[PROD V2] Production ECS monitoring signal. Check service/signal labels and the alert runbook."
    rule["data"][0]["model"]["expr"] = expr_dev(rule["data"][0]["model"]["expr"]).replace('scope="application"','scope="development"')
    result["monitoring/grafana/provisioning/alerting/development.json"] = json.dumps(relay, indent=2) + "\n"
    for kind in ("recording", "alerts"):
        text = (ROOT / f"monitoring/prometheus/rules/application-{kind}.yml").read_text(encoding="utf-8")
        text = expr_dev(text).replace("keepgo-application-", "keepgo-development-")
        if kind == "alerts":
            text = text.replace("alert: KeepGo", "alert: KeepGoDev").replace("scope: application", "scope: development")
            # Idle development traffic has no HTTP counters yet; capability is sufficient.
            start = text.index('        expr: |')
            end = text.index('        for: 10m', start)
            text = text[:start] + '''        expr: |
          (up{job="application-dev",metrics_contract="v1"} == 1)
          unless on (environment, cluster, service, instance)
          (keepgo_observability_info{job="application-dev",contract="1",capability="http"} == 1)
''' + text[end:]
            text = text.replace("Registered HTTP metrics contract is incomplete; check capability, traffic_class, count and histogram.", "V2 HTTP capability is missing. Counters may be absent before the first request.")
            text += '''
      - alert: KeepGoDevScrapeDown
        expr: up{job="application-dev"} == 0
        for: 3m
        labels: {scope: development, severity: warning, signal: scrape_down}
        annotations:
          summary: V2 production metrics endpoint is unreachable for 3 minutes.
      - alert: KeepGoDevTargetMissing
        expr: |
          absent(up{job="application-dev",environment="production",cluster="keepgo-v2",service="backend"})
          or absent(up{job="application-dev",environment="production",cluster="keepgo-v2",service="ai-api"})
        for: 5m
        labels: {scope: development, severity: warning, signal: target_missing}
        annotations:
          summary: Expected V2 production service has no running scrape target.
      - alert: KeepGoDevDiscoveryStale
        expr: |
          (time() - prometheus_sd_file_mtime_seconds{filename="/etc/prometheus/targets/development.json"} > 180)
          or absent(prometheus_sd_file_mtime_seconds{filename="/etc/prometheus/targets/development.json"})
        for: 2m
        labels: {scope: development, environment: production, cluster: keepgo-v2, severity: warning, signal: discovery_stale}
        annotations:
          summary: V2 discovery file has not refreshed; inspect keepgo-dev-metrics.timer.
'''
        result[f"monitoring/prometheus/rules/development-{kind}.yml"] = text
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for name, text in artifacts().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
    if stale:
        raise SystemExit("Regenerate development monitoring: " + ", ".join(stale))
    print("Development monitoring artifacts are current")
