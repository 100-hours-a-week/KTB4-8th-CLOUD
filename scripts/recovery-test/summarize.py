#!/usr/bin/env python3
"""Turn one run's raw records into summary.md: user impact, state-change timeline, and alert reactions."""
import argparse
import csv
from datetime import datetime, timezone
import json
import statistics

from common import parse, run_dir


def outages(rows):
    """Consecutive non-ok probes as (first, last, count). Gaps between probes are not counted as failures."""
    windows, current = [], None
    for row in rows:
        if row["result"] != "ok":
            current = [row["time"], row["time"], 1] if current is None else [current[0], row["time"], current[2] + 1]
        elif current:
            windows.append((*current[:2], current[2], row["time"]))
            current = None
    if current:
        windows.append((*current[:2], current[2], None))
    return windows


def probe_section(rows):
    ok = [int(r["ms"]) for r in rows if r["result"] == "ok"]
    counts = {k: sum(r["result"] == k for r in rows) for k in ("ok", "fail", "timeout", "error")}
    lines = ["## 사용자 영향 (probe)", "",
             f"- 기간: {rows[0]['time']} ~ {rows[-1]['time']}, 요청 {len(rows)}건",
             f"- 성공 {counts['ok']} / 실패 {counts['fail']} / timeout {counts['timeout']} / 연결 오류 {counts['error']}"]
    if ok:
        ok.sort()
        lines.append(f"- 성공 지연: p50 {statistics.median(ok):.0f}ms, p95 {ok[int(len(ok) * .95) - 1]}ms, 최대 {ok[-1]}ms")
    windows = outages(rows)
    lines += ["", "| 첫 실패 | 마지막 실패 | 실패 수 | 복구(다음 성공) | 길이 |", "|---|---|---|---|---|"]
    for first, last, count, recovered in windows:
        length = f"{(parse(recovered) - parse(first)).total_seconds():.0f}초" if recovered else "미복구"
        lines.append(f"| {first} | {last} | {count} | {recovered or '-'} | {length} |")
    if not windows:
        lines.append("| - | - | 0 | - | - |")
    statuses = sorted({(r["status"], r["body"][:60]) for r in rows if r["result"] != "ok"})
    if statuses:
        lines += ["", "실패 응답 종류:"] + [f"- `{s or '(없음)'}` {b}" for s, b in statuses]
    return lines


def recorder_section(rows):
    lines, seen = ["", "## 상태 변화 (recorder, 약 6초 간격)", "", "| 시각 | 변화 |", "|---|---|"], {}
    # Tasks already stopped before the run are history, not part of this test.
    first = next((r for r in rows if "error" not in r), {"tasks": []})
    old = {t["id"] for t in first["tasks"] if t["last"] == "STOPPED"}
    for row in rows:
        if "error" in row:
            lines.append(f"| {row['time']} | 조회 실패: {row['error'][:80]} |")
            continue
        state = {("deploy", d["id"]): f"{d['status']} rev{d['revision']} {d['running']}/{d['desired']} {d['rollout']}"
                 for d in row["deployments"]}
        state |= {("task", t["id"]): f"{t['ip']} {t['last']}/{t['health']}"
                  + (f" ({t['reason']})" if t["last"] == "STOPPED" else "") for t in row["tasks"] if t["id"] not in old}
        state |= {("target", t["ip"]): t["state"] for t in row["targets"]}
        state[("hosts", "")] = str(row["hosts"])
        for key, value in state.items():
            if seen.get(key) != value:
                lines.append(f"| {row['time']} | {key[0]} {key[1]} → {value} |")
        for key in seen.keys() - state.keys():
            if key[0] == "target":
                lines.append(f"| {row['time']} | target {key[1]} → 제거됨 |")
        seen = state
    return lines


def collect_section(data):
    lines = ["", "## 경보·감시 반응 (collect)", "", f"조회 구간: {data['window'][0]} ~ {data['window'][1]}", "",
             "### CloudWatch 경보 상태 변화 (SNS 수신자와 무관하게 기록됨)"]
    lines += [f"- {a['time']} `{a['alarm']}` {a['summary']}" for a in data["alarms"]] or ["- 없음"]
    lines += ["", "### ALB 1분 지표 (0이 아닌 값)"]
    for key, points in data["alb"].items():
        shown = [f"{t[11:16]}={v:g}" for t, v in points if v or key == "healthy"]
        lines.append(f"- {key}: {', '.join(shown) or '모두 0'}")
    prom = data["prometheus"]
    lines += ["", f"### Prometheus (SSM 상태 {prom.get('status')})"]
    for series in prom.get("up", []) if isinstance(prom.get("up"), list) else []:
        values = series["values"]
        down = [v for v in values if v[1] != "1"]
        lines.append(f"- up {series['metric'].get('instance')}: 첫 샘플 {stamp(values[0][0])}, 마지막 {stamp(values[-1][0])}"
                     + (f", 0인 샘플 {len(down)}개({stamp(down[0][0])}~)" if down else ""))
    alerts = prom.get("alerts", [])
    lines += [f"- ALERTS {s['metric'].get('alertname')} {s['metric'].get('alertstate')}: {stamp(s['values'][0][0])} ~ "
              f"{stamp(s['values'][-1][0])}" for s in alerts] if isinstance(alerts, list) and alerts else ["- ALERTS 없음"]
    lines += ["", "### ECS 서비스 이벤트"] + [f"- {e['time']} {e['message']}" for e in data["ecs_events"]]
    lines += ["", "Discord 수신 여부와 시각은 채널에서 직접 확인해 적는다."]
    return lines


def stamp(seconds):
    return datetime.fromtimestamp(float(seconds), timezone.utc).strftime("%H:%M:%SZ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()

    path = run_dir(args.run)
    lines = [f"# {args.run}", ""] + probe_section(list(csv.DictReader((path / "probe.csv").open(encoding="utf-8"))))
    if (path / "recorder.jsonl").exists():
        lines += recorder_section([json.loads(l) for l in (path / "recorder.jsonl").open(encoding="utf-8")])
    if (path / "collect.json").exists():
        lines += collect_section(json.loads((path / "collect.json").read_text(encoding="utf-8")))
    (path / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("saved", path / "summary.md")


if __name__ == "__main__":
    main()
