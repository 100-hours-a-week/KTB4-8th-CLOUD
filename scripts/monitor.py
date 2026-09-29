#!/usr/bin/env python3
"""systemd 타이머에서 컨테이너 상태, DB job 적체, 호스트 자원을 검사한다."""
import json
import shutil
import time
from pathlib import Path
from deploy import Engine
from release import aws, load


def collect(engine):
    metrics = {"HostHeartbeat": 1, "ServiceHealthy": 0, "DeploymentStuck": 0,
               "ContainerRestarts": 0, "QueueOldestAge": 0, "QueueFailedCount": 0}
    intent = engine.read("inflight")
    maintenance = bool(intent and time.time() - intent["started"] < 3300)
    metrics["DeploymentStuck"] = int(bool(intent and not maintenance))
    # 제한된 배포 시간 동안 예상되는 로컬 서비스 중단 검사만 유예한다.
    if maintenance:
        metrics["ServiceHealthy"] = 1
    else:
        try:
            current = engine.read("current")
            containers = engine.check_actual(current)
            previous = engine.read("monitor-restarts", {})
            now = {s: {"id": v["Id"], "count": v["RestartCount"]} for s, v in containers.items()}
            metrics["ContainerRestarts"] = sum(max(0, v["count"] - previous.get(s, {}).get("count", 0))
                if previous.get(s, {}).get("id") == v["id"] else v["count"] for s, v in now.items())
            engine.write("monitor-restarts", now)
            queue = json.loads(engine.compose(current, "exec", "-T", "backend", "/app/bin/queue-metrics", timeout=15))
            for key in ("oldest_pending_seconds", "failed_last_5m"):
                if type(queue.get(key)) not in (int, float) or queue[key] < 0:
                    raise ValueError("Invalid queue metric contract")
            metrics["QueueOldestAge"] = queue["oldest_pending_seconds"]
            metrics["QueueFailedCount"] = queue["failed_last_5m"]
            metrics["ServiceHealthy"] = 1
        except Exception:
            metrics["ServiceHealthy"] = 0
    disk = shutil.disk_usage("/var/lib/docker")
    metrics["DiskUsedPercent"] = 100 * disk.used / disk.total
    memory = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
    metrics["MemoryUsedPercent"] = 100 * (1 - memory["MemAvailable"] / memory["MemTotal"])
    return metrics


if __name__ == "__main__":
    config = load("/opt/keepgo/runtime.json")
    instance = Path("/opt/keepgo/instance-id").read_text().strip()
    engine = Engine(Path(__file__).resolve().parents[1], config, "monitor")
    values = collect(engine)
    data = [{"MetricName": name, "Dimensions": [{"Name": "InstanceId", "Value": instance}],
             "Value": value} for name, value in values.items()]
    aws("cloudwatch", "put-metric-data", "--namespace", "KeepGo/V1", "--metric-data", json.dumps(data), timeout=30)
