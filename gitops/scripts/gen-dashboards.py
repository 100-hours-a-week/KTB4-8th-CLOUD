"""keepgo V3 앱 대시보드를 Grafana sidecar용 ConfigMap으로 만든다.
원칙: 패널 하나에 단위 하나(이중 축 없음), 핵심 수치는 stat, 추세는 선, 상태색은 임계값에만.
"""
import json
import os

OUT = "platform/monitoring"
DS = {"type": "prometheus", "uid": "${datasource}"}
NS_SVC = 'namespace="$namespace", app_kubernetes_io_name="$service"'

_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def ts(title, exprs, unit, x, y, w=12, h=8, desc=""):
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 0, "showPoints": "never"}},
                        "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS} for i, (e, l) in enumerate(exprs)],
    }


def stat(title, expr, unit, x, y, thresholds=None, w=6, h=4, desc=""):
    steps = [{"color": "text", "value": None}]
    if thresholds:
        steps = [{"color": "green", "value": None}] + [{"color": c, "value": v} for v, c in thresholds]
    return {
        "id": nid(), "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value" if thresholds else "none",
                    "graphMode": "area", "textMode": "value"},
        "targets": [{"refId": "A", "expr": expr, "datasource": DS}],
    }


def var_ds():
    return {"name": "datasource", "type": "datasource", "query": "prometheus", "label": "데이터 소스"}


def var_q(name, label, query, multi=False):
    return {"name": name, "label": label, "type": "query", "datasource": DS, "refresh": 2,
            "query": {"query": query, "refId": name}, "definition": query, "multi": multi,
            "includeAll": multi, "sort": 1}


def dashboard(uid, title, panels, variables):
    return {"uid": uid, "title": title, "tags": ["keepgo", "v3"], "timezone": "browser", "schemaVersion": 39,
            "refresh": "30s", "time": {"from": "now-3h", "to": "now"},
            "templating": {"list": variables}, "panels": panels, "editable": True}


# ---------- 1. 서비스 ----------
_id[0] = 0
svc_panels = [
    stat("초당 요청", f'sum(rate(http_server_requests_seconds_count{{{NS_SVC}}}[5m]))', "reqps", 0, 0),
    stat("5xx 비율", f'sum(rate(http_server_requests_seconds_count{{{NS_SVC}, status=~"5.."}}[5m])) / sum(rate(http_server_requests_seconds_count{{{NS_SVC}}}[5m]))',
         "percentunit", 6, 0, [(0.01, "orange"), (0.05, "red")], desc="알림 기준 5%(PrometheusRule)"),
    stat("p95 응답 시간", f'histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{{{NS_SVC}}}[5m])))',
         "s", 12, 0, [(0.5, "orange"), (1, "red")], desc="SSE 서비스는 연결 시간이 섞여 의미가 작다"),
    stat("Ready Pod", 'kube_deployment_status_replicas_available{namespace="$namespace", deployment="$service"}', "short", 18, 0),
    ts("초당 요청(상태별)", [(f'sum by (status) (rate(http_server_requests_seconds_count{{{NS_SVC}}}[5m]))', "{{status}}")], "reqps", 0, 4),
    ts("5xx 비율", [(f'sum(rate(http_server_requests_seconds_count{{{NS_SVC}, status=~"5.."}}[5m])) / sum(rate(http_server_requests_seconds_count{{{NS_SVC}}}[5m]))', "5xx")],
       "percentunit", 12, 4),
    ts("응답 시간 p95·p99", [
        (f'histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{{{NS_SVC}}}[5m])))', "p95"),
        (f'histogram_quantile(0.99, sum by (le) (rate(http_server_requests_seconds_bucket{{{NS_SVC}}}[5m])))', "p99")], "s", 0, 12),
    ts("Pod 수(현재·HPA 목표)", [
        ('kube_deployment_status_replicas{namespace="$namespace", deployment="$service"}', "현재"),
        ('max(kube_horizontalpodautoscaler_status_desired_replicas{namespace="$namespace", horizontalpodautoscaler=~"$service|keda-hpa-$service"})', "목표")],
       "short", 12, 12, desc="KEDA가 만든 HPA 이름은 keda-hpa-<서비스>"),
    ts("CPU 사용량과 requests", [
        ('sum(rate(container_cpu_usage_seconds_total{namespace="$namespace", pod=~"$service-.*", container="app"}[5m]))', "사용량"),
        ('sum(kube_pod_container_resource_requests{namespace="$namespace", pod=~"$service-.*", container="app", resource="cpu"})', "requests 합계")],
       "cores", 0, 20, desc="HPA 사용률 = 사용량 ÷ requests(5-3 3.5)"),
    ts("메모리 사용량과 limits", [
        ('sum by (pod) (container_memory_working_set_bytes{namespace="$namespace", pod=~"$service-.*", container="app"})', "{{pod}}"),
        ('max(kube_pod_container_resource_limits{namespace="$namespace", pod=~"$service-.*", container="app", resource="memory"})', "limit")],
       "bytes", 12, 20, desc="limit에 닿으면 OOMKilled"),
    ts("JVM Heap 사용량", [(f'sum by (pod) (jvm_memory_used_bytes{{{NS_SVC}, area="heap"}})', "{{pod}}")], "bytes", 0, 28,
       desc="MaxRAMPercentage=70(5-3 3.2)"),
    ts("DB 커넥션(사용 중)", [(f'sum by (pod) (hikaricp_connections_active{{{NS_SVC}}})', "{{pod}}")], "short", 12, 28,
       desc="Pod당 상한 = SPRING_DATASOURCE_HIKARI_MAXIMUMPOOLSIZE(3)"),
    ts("컨테이너 재시작(15분)", [('sum by (pod) (increase(kube_pod_container_status_restarts_total{namespace="$namespace", pod=~"$service-.*"}[15m]))', "{{pod}}")],
       "short", 0, 36),
    ts("GC 정지 시간", [(f'sum by (pod) (rate(jvm_gc_pause_seconds_sum{{{NS_SVC}}}[5m]))', "{{pod}}")], "s", 12, 36),
]
svc = dashboard("keepgo-v3-service", "KeepGo V3 / 서비스", svc_panels, [
    var_ds(),
    var_q("namespace", "Namespace", 'label_values(kube_namespace_labels{label_app_kubernetes_io_part_of="keepgo"}, namespace)'),
    var_q("service", "서비스", 'label_values(kube_deployment_labels{namespace="$namespace"}, deployment)'),
])

# ---------- 2. 확장·Worker ----------
_id[0] = 0
scale_panels = [
    stat("Pending Pod", 'sum(kube_pod_status_phase{namespace=~"account|ingest|content|recommend|ai|frontend", phase="Pending"})', "short", 0, 0, [(1, "orange"), (5, "red")],
         desc="오래 Pending이면 NodePool 한도·Quota·IP 부족 확인(5-3 6.7)"),
    stat("KEDA 스케일러 오류(15분)", 'sum(increase(keda_scaler_errors_total[15m]))', "short", 6, 0, [(1, "orange")]),
    stat("Worker Pod", 'kube_deployment_status_replicas{namespace="ingest", deployment="youtube-analysis-worker"}', "short", 12, 0),
    stat("SSE 연결 합계", 'sum(keepgo_sse_active_connections)', "short", 18, 0, desc="[가정] 개발팀 계측 지표"),
    ts("서비스별 Pod 수", [('sum by (namespace, deployment) (kube_deployment_status_replicas{namespace=~"account|ingest|content|recommend|ai|frontend"})', "{{deployment}}")],
       "short", 0, 4, w=24),
    ts("KEDA 지표 값(ScaledObject별)", [('sum by (scaledObject, metric) (keda_scaler_metrics_value)', "{{scaledObject}} {{metric}}")], "short", 0, 12,
       desc="SQS 대기 메시지, SSE 연결 수, AI 처리 중 요청"),
    ts("ai-api 처리 중 요청", [('sum(keepgo_ai_inflight_requests{namespace="ai"})', "in-flight")], "short", 12, 12, desc="[가정] AI팀 계측 지표"),
    ts("Namespace CPU requests 대비 Quota", [
        ('sum by (namespace) (kube_resourcequota{resource="requests.cpu", type="used"})', "{{namespace}} 사용"),
    ], "cores", 0, 20, desc="Quota 한도 근처면 확장이 막힌다(5-2 2.2)"),
    ts("Namespace 메모리 requests 사용", [
        ('sum by (namespace) (kube_resourcequota{resource="requests.memory", type="used"})', "{{namespace}} 사용"),
    ], "bytes", 12, 20),
]
scale = dashboard("keepgo-v3-scaling", "KeepGo V3 / 확장·Worker", scale_panels, [var_ds()])

os.makedirs(OUT, exist_ok=True)
for name, d in [("service", svc), ("scaling", scale)]:
    body = json.dumps(d, ensure_ascii=False, indent=2)
    indented = "\n".join("    " + line for line in body.splitlines())
    open(f"{OUT}/dashboard-{name}.yaml", "w", encoding="utf-8", newline="\n").write(
        f"""# 자동 생성: scripts/gen-dashboards.py 를 고친 뒤 다시 만든다(이 파일을 직접 고치지 않는다).
# Grafana sidecar가 grafana_dashboard 라벨이 붙은 ConfigMap을 대시보드로 읽는다(kube-prometheus-stack 기본).
apiVersion: v1
kind: ConfigMap
metadata:
  name: keepgo-v3-dashboard-{name}
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
    app.kubernetes.io/part-of: keepgo
  annotations:
    grafana_folder: KeepGo V3
data:
  keepgo-v3-{name}.json: |
{indented}
""")
print("ok")
