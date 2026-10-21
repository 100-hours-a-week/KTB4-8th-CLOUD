#!/usr/bin/env python3
"""After a run, pull what each alerting path saw: ECS events, CloudWatch alarm history, ALB metrics,
and Prometheus up/ALERTS from the monitoring host (read-only curl over SSM)."""
import argparse
import csv
import json
import time
from datetime import timedelta

from common import CLUSTER, SERVICE, aws, iso, now, parse, run_dir

MONITORING_INSTANCE = "i-0e2b9ff8599ff8023"
PROMETHEUS_QUERIES = {"up": 'up{job="application-dev",service="backend"}',
                      "alerts": 'ALERTS{scope="development"}'}


def window(path, before, after):
    rows = list(csv.DictReader((path / "probe.csv").open(encoding="utf-8")))
    return parse(rows[0]["time"]) - before, parse(rows[-1]["time"]) + after


def ecs_events(start, end):
    service = aws("ecs", "describe-services", "--cluster", CLUSTER, "--services", SERVICE)["services"][0]
    return sorted(({"time": iso(parse(e["createdAt"])), "message": e["message"]} for e in service["events"]
                   if start <= parse(e["createdAt"]) <= end), key=lambda e: e["time"])


def alarm_history(start, end):
    items = aws("cloudwatch", "describe-alarm-history", "--history-item-type", "StateUpdate",
                "--start-date", iso(start), "--end-date", iso(end))["AlarmHistoryItems"]
    return sorted(({"time": iso(parse(i["Timestamp"])), "alarm": i["AlarmName"], "summary": i["HistorySummary"]}
                   for i in items if i["AlarmName"].startswith("keepgo-v2-")), key=lambda i: i["time"])


def alb_metrics(start, end):
    lb = aws("elbv2", "describe-load-balancers", "--names", CLUSTER)["LoadBalancers"][0]["LoadBalancerArn"]
    tg = aws("elbv2", "describe-target-groups", "--names", SERVICE)["TargetGroups"][0]["TargetGroupArn"]
    lb, tg = lb.split("loadbalancer/", 1)[1], tg.split(":", 5)[5]
    specs = {"requests": ("RequestCount", "Sum", False), "elb_5xx": ("HTTPCode_ELB_5XX_Count", "Sum", False),
             "target_5xx": ("HTTPCode_Target_5XX_Count", "Sum", False),
             "healthy": ("HealthyHostCount", "Minimum", True), "unhealthy": ("UnHealthyHostCount", "Maximum", True)}
    queries = [{"Id": key, "ReturnData": True, "MetricStat": {"Period": 60, "Stat": stat, "Metric": {
        "Namespace": "AWS/ApplicationELB", "MetricName": metric,
        "Dimensions": [{"Name": "LoadBalancer", "Value": lb}] + ([{"Name": "TargetGroup", "Value": tg}] if per_tg else [])}}}
        for key, (metric, stat, per_tg) in specs.items()]
    result = aws("cloudwatch", "get-metric-data", "--start-time", iso(start), "--end-time", iso(end),
                 "--metric-data-queries", json.dumps(queries))["MetricDataResults"]
    return {r["Id"]: sorted((iso(parse(t)), v) for t, v in zip(r["Timestamps"], r["Values"])) for r in result}


def prometheus(path, start, end):
    url = "http://127.0.0.1:9090/api/v1/query_range"
    commands = []
    span = f"--data-urlencode start={start.timestamp():.0f} --data-urlencode end={end.timestamp():.0f}"
    for key, query in PROMETHEUS_QUERIES.items():
        commands += [f"echo '=== {key}'", f"curl -s {url} --data-urlencode 'query={query}' {span} --data-urlencode step=15",
                     "echo"]
    params = path / "ssm-params.json"
    params.write_text(json.dumps({"commands": commands}), encoding="utf-8")
    command = aws("ssm", "send-command", "--instance-ids", MONITORING_INSTANCE, "--document-name",
                  "AWS-RunShellScript", "--comment", "recovery-test read-only Prometheus query",
                  "--parameters", "file://" + params.as_posix())["Command"]["CommandId"]
    for _ in range(30):
        time.sleep(2)
        try:
            result = aws("ssm", "get-command-invocation", "--command-id", command, "--instance-id", MONITORING_INSTANCE)
        except RuntimeError:
            continue
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            break
    output, parsed = result.get("StandardOutputContent", ""), {}
    for block in output.split("=== ")[1:]:
        key, _, body = block.partition("\n")
        try:
            parsed[key.strip()] = json.loads(body)["data"]["result"]
        except (ValueError, KeyError):
            parsed[key.strip()] = {"raw": body[:500]}
    return {"status": result["Status"], **parsed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--end", help="cut the window here, e.g. when the next test started (UTC ISO)")
    args = parser.parse_args()

    path = run_dir(args.run)
    # Alarms evaluate 3 x 60s and Prometheus rules use for: 3~5m, so look a bit past the run.
    start, end = window(path, timedelta(minutes=5), timedelta(minutes=10))
    if args.end and parse(args.end) < end:
        end = parse(args.end)
    if end > now():
        print(f"warning: alarms may still be evaluating; rerun after {iso(end)} for the full window")
        end = now()
    data = {"window": [iso(start), iso(end)], "ecs_events": ecs_events(start, end),
            "alarms": alarm_history(start, end), "alb": alb_metrics(start, end),
            "prometheus": prometheus(path, start, end)}
    (path / "collect.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("saved", path / "collect.json")


if __name__ == "__main__":
    main()
