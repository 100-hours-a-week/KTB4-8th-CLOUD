#!/usr/bin/env python3
"""Reuse the existing HTTP/JVM dashboards and rules with an isolated job per V2 ECS cluster.

The production job, file and rule names still say "dev"; V2 became production on 2026-10-23, so labels and
titles say production while the names stay until the V1 instance is relabeled as development. The new V2
development cluster (keepgo-v2-dev) gets its own "v2-dev" names so neither environment mixes into the other.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[1]

PROFILES = (
    {"job": "application-dev", "record": "keepgo_dev:", "group": "keepgo-development-", "alert": "KeepGoDev",
     "scope": "development", "stem": "dev", "rules": "development", "uid": "-dev", "relay": "development", "relay_uid": "keepgo-development",
     "title": "[PROD V2]", "environment": "production", "cluster": "keepgo-v2", "targets": "development.json",
     "description": " V2 ECS production (keepgo-v2) only; V1 queries remain unchanged.",
     "summary": "[PROD V2] Production ECS monitoring signal. Check service/signal labels and the alert runbook.",
     "name": "V2", "long": "V2 production"},
    {"job": "application-v2-dev", "record": "keepgo_v2dev:", "group": "keepgo-v2-dev-", "alert": "KeepGoV2Dev",
     "scope": "v2-dev", "stem": "v2-dev", "rules": "v2-dev", "uid": "-v2-dev", "relay": "v2-dev", "relay_uid": "keepgo-v2-dev",
     "title": "[DEV]", "environment": "development", "cluster": "keepgo-v2-dev", "targets": "v2-dev.json",
     "description": " V2 ECS development (keepgo-v2-dev) only; production queries remain unchanged.",
     "summary": "[DEV] Development ECS monitoring signal. Check service/signal labels and the alert runbook.",
     "name": "V2 dev", "long": "V2 development"},
)


def expr_for(p, text):
    text = text.replace('job="application"', f'job="{p["job"]}"')
    text = text.replace("keepgo:", p["record"])
    return re.sub(r"\b(by|on)\s*\(", r"\1 (environment, cluster, ", text)


def render(p, original):
    result = {}
    for filename in ("application-http", "backend-runtime"):
        board = copy.deepcopy(original[f"monitoring/grafana/dashboards/{filename}.json"])
        board["uid"] += p["uid"]
        board["title"] = f'{p["title"]} {board["title"]}'
        board["tags"] += [p["environment"], p["cluster"]]
        board["description"] += p["description"]
        for panel in board["panels"]:
            for target in panel["targets"]:
                target["expr"] = expr_for(p, target["expr"])
        result[f'monitoring/grafana/dashboards/{p["stem"]}-{filename}.json'] = json.dumps(board, indent=2) + "\n"
    relay = copy.deepcopy(original["monitoring/grafana/provisioning/alerting/application.json"])
    group = relay["groups"][0]
    group["name"] = f'{p["group"]}relay'
    rule = group["rules"][0]
    rule.update(uid=p["relay_uid"], title=f'{p["title"]} KeepGo application signal')
    rule["labels"].update(environment=p["environment"], cluster=p["cluster"])
    rule["annotations"]["summary"] = p["summary"]
    rule["data"][0]["model"]["expr"] = expr_for(p, rule["data"][0]["model"]["expr"]).replace(
        'scope="application"', f'scope="{p["scope"]}"')
    result[f'monitoring/grafana/provisioning/alerting/{p["relay"]}.json'] = json.dumps(relay, indent=2) + "\n"
    selector = f'job="{p["job"]}",environment="{p["environment"]}",cluster="{p["cluster"]}"'
    targets = f'/etc/prometheus/targets/{p["targets"]}'
    for kind in ("recording", "alerts"):
        text = (ROOT / f"monitoring/prometheus/rules/application-{kind}.yml").read_text(encoding="utf-8")
        text = expr_for(p, text).replace("keepgo-application-", p["group"])
        if kind == "alerts":
            text = text.replace("alert: KeepGo", f'alert: {p["alert"]}').replace(
                "scope: application", f'scope: {p["scope"]}')
            # Idle development traffic has no HTTP counters yet; capability is sufficient.
            start = text.index('        expr: |')
            end = text.index('        for: 10m', start)
            text = text[:start] + f'''        expr: |
          (up{{job="{p["job"]}",metrics_contract="v1"}} == 1)
          unless on (environment, cluster, service, instance)
          (keepgo_observability_info{{job="{p["job"]}",contract="1",capability="http"}} == 1)
''' + text[end:]
            text = text.replace("Registered HTTP metrics contract is incomplete; check capability, traffic_class, count and histogram.", f'{p["name"]} HTTP capability is missing. Counters may be absent before the first request.')
            text += f'''
      - alert: {p["alert"]}ScrapeDown
        expr: up{{job="{p["job"]}"}} == 0
        for: 3m
        labels: {{scope: {p["scope"]}, severity: warning, signal: scrape_down}}
        annotations:
          summary: {p["long"]} metrics endpoint is unreachable for 3 minutes.
      - alert: {p["alert"]}TargetMissing
        expr: |
          absent(up{{{selector},service="backend"}})
          or absent(up{{{selector},service="ai-api"}})
        for: 5m
        labels: {{scope: {p["scope"]}, severity: warning, signal: target_missing}}
        annotations:
          summary: Expected {p["long"]} service has no running scrape target.
      - alert: {p["alert"]}DiscoveryStale
        expr: |
          (time() - prometheus_sd_file_mtime_seconds{{filename="{targets}"}} > 180)
          or absent(prometheus_sd_file_mtime_seconds{{filename="{targets}"}})
        for: 2m
        labels: {{scope: {p["scope"]}, environment: {p["environment"]}, cluster: {p["cluster"]}, severity: warning, signal: discovery_stale}}
        annotations:
          summary: {p["name"]} discovery file has not refreshed; inspect keepgo-dev-metrics.timer.
'''
        result[f'monitoring/prometheus/rules/{p["rules"]}-{kind}.yml'] = text
    return result


def artifacts():
    original = runpy.run_path(str(ROOT / "scripts/render-app-monitoring.py"))["artifacts"]()
    result = {}
    for profile in PROFILES:
        result.update(render(profile, original))
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
