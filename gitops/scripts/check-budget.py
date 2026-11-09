"""렌더링된 매니페스트로 두 가지 예산을 검사한다.

1) DB 커넥션(5-3 3.4)
   합계((maxReplicas + maxSurge) x SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE) + reserved <= rdsMaxConnections
2) ResourceQuota(5-2 2.2)
   Namespace별 합계((maxReplicas + maxSurge) x requests) <= quota hard
   (최대로 늘어난 상태에서 롤링 배포가 겹쳐도 Quota에 막히지 않는지)

사용: python3 scripts/check-budget.py <렌더링 폴더> scripts/budget.yaml
렌더링 폴더 구조는 validate.sh가 만든 <env>/app-<ns>-<svc>.yaml, <env>/platform-tenancy.yaml
"""
import glob
import math
import os
import sys

import yaml


def cpu(q):
    q = str(q)
    return float(q[:-1]) / 1000 if q.endswith("m") else float(q)


UNITS = {"Ki": 2 ** 10, "Mi": 2 ** 20, "Gi": 2 ** 30, "Ti": 2 ** 40, "k": 1e3, "M": 1e6, "G": 1e9}


def mem(q):
    q = str(q)
    for u in sorted(UNITS, key=len, reverse=True):
        if q.endswith(u):
            return float(q[: -len(u)]) * UNITS[u]
    return float(q)


def gib(b):
    return "%.2fGi" % (b / 2 ** 30)


def load(path):
    with open(path, encoding="utf-8") as f:
        return [d for d in yaml.safe_load_all(f) if d]


def workload(docs):
    dep = next((d for d in docs if d["kind"] == "Deployment"), None)
    if dep is None:
        return None
    spec = dep["spec"]
    c = spec["template"]["spec"]["containers"][0]
    maxr = spec.get("replicas", 1)
    for d in docs:
        if d["kind"] == "HorizontalPodAutoscaler":
            maxr = d["spec"]["maxReplicas"]
        if d["kind"] == "ScaledObject":
            maxr = d["spec"]["maxReplicaCount"]
    surge = (spec.get("strategy", {}).get("rollingUpdate") or {}).get("maxSurge", "25%")
    if isinstance(surge, str) and surge.endswith("%"):
        surge = math.ceil(maxr * float(surge[:-1]) / 100)
    pool = None
    for e in c.get("env", []):
        if e["name"] == "SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE":
            pool = int(e["value"])
    req = c["resources"]["requests"]
    return {
        "name": dep["metadata"]["name"],
        "peak": maxr + int(surge),
        "max": maxr,
        "surge": int(surge),
        "pool": pool,
        "cpu": cpu(req["cpu"]),
        "mem": mem(req["memory"]),
    }


def main(out, budget_file):
    budget = yaml.safe_load(open(budget_file, encoding="utf-8"))
    ok = True
    for env in sorted(os.listdir(out)):
        envdir = os.path.join(out, env)
        if not os.path.isdir(envdir) or env not in budget:
            continue
        print("[%s]" % env)
        per_ns = {}
        conns = 0
        for path in sorted(glob.glob(os.path.join(envdir, "app-*.yaml"))):
            ns = os.path.basename(path)[4:].split("-", 1)[0]
            w = workload(load(path))
            if w is None:
                continue
            per_ns.setdefault(ns, []).append(w)
            if w["pool"]:
                c = w["peak"] * w["pool"]
                conns += c
                print("  DB  %-24s (max %d + surge %d) x pool %d = %d" % (w["name"], w["max"], w["surge"], w["pool"], c))
        b = budget[env]
        total = conns + b["reservedConnections"]
        verdict = "ok" if total <= b["rdsMaxConnections"] else "초과"
        if verdict != "ok":
            ok = False
        print("  DB  합계 %d + 예비 %d = %d / 한도 %d  %s" % (conns, b["reservedConnections"], total, b["rdsMaxConnections"], verdict))

        quotas = {}
        for d in load(os.path.join(envdir, "platform-tenancy.yaml")):
            if d["kind"] == "ResourceQuota":
                quotas[d["metadata"]["namespace"]] = d["spec"]["hard"]
        for ns, ws in sorted(per_ns.items()):
            hard = quotas.get(ns)
            if hard is None:
                print("  Quota %-10s 없음  초과" % ns)
                ok = False
                continue
            need_cpu = sum(w["peak"] * w["cpu"] for w in ws)
            need_mem = sum(w["peak"] * w["mem"] for w in ws)
            need_pods = sum(w["peak"] for w in ws)
            checks = [
                ("cpu", need_cpu, cpu(hard["requests.cpu"]), "%.2f"),
                ("mem", need_mem, mem(hard["requests.memory"]), None),
                ("pods", need_pods, int(hard["pods"]), "%d"),
            ]
            parts = []
            for label, need, have, fmt in checks:
                bad = need > have
                if bad:
                    ok = False
                if fmt is None:
                    parts.append("%s %s/%s%s" % (label, gib(need), gib(have), " 초과" if bad else ""))
                else:
                    parts.append(("%s " + fmt + "/" + fmt + "%s") % (label, need, have, " 초과" if bad else ""))
            print("  Quota %-10s %s" % (ns, ", ".join(parts)))
    return ok


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(0 if main(sys.argv[1], sys.argv[2]) else 1)
