#!/usr/bin/env python3
"""Send one safe GET per second through CloudFront and record whether Spring itself answered.

An unknown /api path without a token reaches the BE and returns its 401 JSON. Anything else
(ALB 502/503 HTML, CloudFront 504, timeout) means the user path to the BE is broken.
"""
import argparse
import csv
import json
import time
import urllib.error
import urllib.request

from common import iso, run_dir

URL = "https://d3lx018adwi4jv.cloudfront.net/api/v1/__recovery_probe"


def judge(status, body):
    try:
        return "ok" if status == 401 and json.loads(body).get("type") == "/invalid-token" else "fail"
    except (ValueError, AttributeError):
        return "fail"


def probe(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "keepgo-recovery-test"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, headers, body = response.status, response.headers, response.read(2048)
    except urllib.error.HTTPError as error:
        status, headers, body = error.code, error.headers, error.read(2048)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"status": "", "ms": round((time.monotonic() - started) * 1000), "result": "timeout"
                if "timed out" in str(error) else "error", "x_cache": "", "pop": "", "body": str(error)[:120]}
    text = body.decode("utf-8", "replace")
    return {"status": status, "ms": round((time.monotonic() - started) * 1000), "result": judge(status, text),
            "x_cache": headers.get("x-cache", ""), "pop": headers.get("x-amz-cf-pop", ""),
            "body": " ".join(text.split())[:120]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", help="run name, e.g. 20261022-a-redeploy")
    parser.add_argument("--duration", type=int, default=0, help="seconds; 0 = until Ctrl+C")
    parser.add_argument("--url", default=URL)
    parser.add_argument("--timeout", type=float, default=3)
    args = parser.parse_args()

    path = run_dir(args.run) / "probe.csv"
    fields = ["time", "status", "ms", "result", "x_cache", "pop", "body"]
    start = time.monotonic()
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fields)
        if file.tell() == 0:
            writer.writeheader()
        tick = 0
        try:
            while not args.duration or time.monotonic() - start < args.duration:
                row = {"time": iso(), **probe(args.url, args.timeout)}
                writer.writerow(row)
                file.flush()
                print(row["time"], row["status"], f'{row["ms"]}ms', row["result"], flush=True)
                tick += 1
                # Fixed 1-second schedule; a slow response skips ahead instead of drifting.
                delay = start + tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    tick = int(time.monotonic() - start) + 1
        except KeyboardInterrupt:
            pass
    print("saved", path)


if __name__ == "__main__":
    main()
