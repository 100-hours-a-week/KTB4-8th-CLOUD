#!/usr/bin/env python3
"""Every few seconds, record BE deployment, task and ALB target state as JSON lines."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import time

from common import CLUSTER, SERVICE, aws, iso, run_dir


def ecs(*args):
    return aws("ecs", *args, "--cluster", CLUSTER)


def snapshot(target_groups):
    # AWS CLI start-up is slow on Windows, so independent reads run together.
    with ThreadPoolExecutor(max_workers=6) as pool:
        service = pool.submit(ecs, "describe-services", "--services", SERVICE)
        listed = [pool.submit(ecs, "list-tasks", "--service-name", SERVICE, "--desired-status", status)
                  for status in ("RUNNING", "STOPPED")]
        health = [pool.submit(aws, "elbv2", "describe-target-health", "--target-group-arn", arn) for arn in target_groups]
        hosts = pool.submit(aws, "ecs", "list-container-instances", "--cluster", CLUSTER)
        arns = [arn for future in listed for arn in future.result()["taskArns"]]
        described = pool.submit(ecs, "describe-tasks", "--tasks", *arns[:100]) if arns else None
        service = service.result()["services"][0]
    deployments = [{"id": d["id"][-8:], "status": d["status"], "rollout": d.get("rolloutState"),
                    "revision": d["taskDefinition"].rsplit(":", 1)[-1], "desired": d["desiredCount"],
                    "running": d["runningCount"], "pending": d["pendingCount"]} for d in service["deployments"]]
    tasks = []
    for task in described.result()["tasks"] if described else []:
        ip = next((d["value"] for a in task.get("attachments", []) for d in a.get("details", [])
                   if d["name"] == "privateIPv4Address"), "")
        tasks.append({"id": task["taskArn"].rsplit("/", 1)[-1][:12], "ip": ip,
                      "revision": task["taskDefinitionArn"].rsplit(":", 1)[-1],
                      "last": task["lastStatus"], "desired": task["desiredStatus"],
                      "health": task.get("healthStatus"), "started": task.get("startedAt"),
                      "stopped": task.get("stoppedAt"), "reason": task.get("stoppedReason"),
                      "instance": task.get("containerInstanceArn", "").rsplit("/", 1)[-1][:12]})
    targets = [{"ip": t["Target"]["Id"], "state": t["TargetHealth"]["State"], "reason": t["TargetHealth"].get("Reason")}
               for future in health for t in future.result()["TargetHealthDescriptions"]]
    return {"deployments": deployments, "tasks": tasks, "targets": targets,
            "hosts": len(hosts.result()["containerInstanceArns"])}


def brief(row):
    deps = " ".join(f'{d["status"][:4]}:{d["running"]}/{d["desired"]}' for d in row["deployments"])
    live = " ".join(f'{t["ip"]}={t["last"][:4]}/{t["health"]}' for t in row["tasks"] if t["last"] != "STOPPED")
    tg = " ".join(f'{t["ip"]}={t["state"]}' for t in row["targets"])
    return f'{row["time"]} deploy[{deps}] tasks[{live}] tg[{tg}] hosts={row["hosts"]}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    path = run_dir(args.run) / "recorder.jsonl"
    service = ecs("describe-services", "--services", SERVICE)["services"][0]
    target_groups = [lb["targetGroupArn"] for lb in service.get("loadBalancers", [])]
    with path.open("a", encoding="utf-8") as file:
        try:
            while True:
                started = time.monotonic()
                try:
                    row = {"time": iso(), **snapshot(target_groups)}
                except Exception as error:  # keep recording through a transient API failure
                    row = {"time": iso(), "error": str(error)[:300]}
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                file.flush()
                print(brief(row) if "error" not in row else f'{row["time"]} ERROR {row["error"]}', flush=True)
                if args.once:
                    break
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
        except KeyboardInterrupt:
            pass
    print("saved", path)


if __name__ == "__main__":
    main()
