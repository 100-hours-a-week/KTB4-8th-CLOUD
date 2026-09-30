#!/usr/bin/env python3
"""앱 대시보드와 Grafana 전달 규칙의 재현 가능한 원본.

임계치·지속 시간은 Prometheus application-alerts.yml에서만 관리한다.
이 파일은 조회/발송 연결만 생성한다. 수정 후 실행하고 생성된 JSON도 함께 커밋한다.
CI의 --check는 파일을 수정하지 않고 생성 결과의 일치 여부만 확인한다.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = {"type": "prometheus", "uid": "keepgo-prometheus"}


def dashboard(uid, title, description, specifications):
    panels = []
    for index, (name, expr, legend, unit) in enumerate(specifications):
        panels.append({
            "id": index + 1, "type": "timeseries", "title": name,
            "datasource": DS,
            "gridPos": {"x": index % 2 * 12, "y": index // 2 * 8, "w": 12, "h": 8},
            "targets": [{"refId": "A", "expr": expr, "legendFormat": legend}],
            "fieldConfig": {"defaults": {"unit": unit, "min": 0}, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        })
    return {
        "id": None, "uid": uid, "title": title, "description": description,
        "schemaVersion": 39, "version": 1, "tags": ["keepgo", "application"],
        "timezone": "browser", "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
        "panels": panels,
    }


def artifacts():
    app = 'job="application",metrics_contract="v1"'
    http = [
        ("Requests / second", 'sum by (service) (keepgo:http_requests:rate5m)', '{{service}}', 'reqps'),
        ("HTTP 5xx ratio", 'keepgo:http_5xx:ratio5m', '{{service}}', 'percentunit'),
        ("HTTP 4xx ratio (diagnostic, not a server error)", '(sum by (service) (keepgo:http_requests:rate5m{status=~"4.."}) or on(service) (0 * sum by(service)(keepgo:http_requests:rate5m))) / sum by(service)(keepgo:http_requests:rate5m)', '{{service}}', 'percentunit'),
        ("Requests in rolling 5 minutes", 'sum by(service,traffic_class)(keepgo:http_requests:increase5m)', '{{service}} / {{traffic_class}}', 'short'),
    ]
    for percentile in (50, 95, 99):
        http.append((f"HTTP p{percentile} by traffic class", f'histogram_quantile({percentile / 100}, sum by(service,traffic_class,le)(keepgo:http_duration_seconds_bucket:rate5m))', '{{service}} / {{traffic_class}}', 's'))
    http += [
        ("Top 10 routes by request rate", 'topk(10, sum by(service,method,route)(keepgo:http_requests:rate5m))', '{{service}} {{method}} {{route}}', 'reqps'),
        ("Application scrape status", f'up{{{app}}}', '{{service}} / {{instance}}', 'short'),
        ("Advertised instrumentation capabilities", f'keepgo_observability_info{{{app}}}', '{{service}} / {{capability}}', 'short'),
    ]
    be = [
        ("JVM heap usage", 'keepgo:jvm_heap:ratio', '{{service}} / {{instance}}', 'percentunit'),
        ("JVM memory used", f'sum by(instance,area)(jvm_memory_used_bytes{{{app}}})', '{{instance}} / {{area}}', 'bytes'),
        ("GC pause seconds / second", f'sum by(instance)(rate(jvm_gc_pause_seconds_sum{{{app}}}[5m]))', '{{instance}}', 's'),
        ("GC collections / second", f'sum by(instance)(rate(jvm_gc_pause_seconds_count{{{app}}}[5m]))', '{{instance}}', 'ops'),
        ("Live JVM threads", f'jvm_threads_live_threads{{{app}}}', '{{instance}}', 'short'),
        ("Hikari active / maximum", 'keepgo:db_pool:ratio', '{{instance}} / {{pool}}', 'percentunit'),
        ("Hikari waiting callers", f'hikaricp_connections_pending{{{app}}}', '{{instance}} / {{pool}}', 'short'),
        ("DB acquisition timeouts in 5 minutes", f'sum by(instance,pool)(increase(hikaricp_connections_timeout_total{{{app}}}[5m]))', '{{instance}} / {{pool}}', 'short'),
    ]
    ai = [
        ("Provider attempts / second", f'sum by(provider,model,outcome)(rate(keepgo_ai_provider_requests_total{{{app}}}[5m]))', '{{provider}} / {{model}} / {{outcome}}', 'reqps'),
        ("Provider failure ratio (cancelled attempts excluded)", 'keepgo:ai_provider_errors:ratio5m', '{{provider}} / {{model}}', 'percentunit'),
        ("Provider attempt p95", f'histogram_quantile(0.95,sum by(provider,model,le)(rate(keepgo_ai_provider_request_duration_seconds_bucket{{{app}}}[5m])))', '{{provider}} / {{model}}', 's'),
        ("Successful streaming first-token p95", f'histogram_quantile(0.95,sum by(provider,model,le)(rate(keepgo_ai_first_token_seconds_bucket{{{app}}}[10m])))', '{{provider}} / {{model}}', 's'),
        ("Extra provider attempts / second", f'sum by(provider,model,reason)(rate(keepgo_ai_retries_total{{{app}}}[5m]))', '{{provider}} / {{model}} / {{reason}}', 'ops'),
        ("In-flight logical AI requests", f'sum by(operation)(keepgo_ai_requests_in_flight{{{app}}})', '{{operation}}', 'short'),
        ("Reported tokens / minute (not a cost estimate)", f'60 * sum by(provider,model,type)(rate(keepgo_ai_tokens_total{{{app}}}[5m]))', '{{provider}} / {{model}} / {{type}}', 'short'),
        ("Provider 429 / timeout / cancellation attempts", f'sum by(provider,model,outcome)(increase(keepgo_ai_provider_requests_total{{{app},outcome=~"rate_limited|timeout|cancelled"}}[5m]))', '{{provider}} / {{model}} / {{outcome}}', 'short'),
    ]
    base = "monitoring/grafana/dashboards/"
    result = {
        base + "application-http.json": dashboard("keepgo-http", "KeepGo - Application HTTP", "Contract v1. Health/metrics routes are excluded. No data means no observations or missing instrumentation, not zero errors. Stream duration is full response lifetime.", http),
        base + "backend-runtime.json": dashboard("keepgo-backend", "KeepGo - Backend JVM and DB Pool", "Micrometer/Hikari contract v1. JVM heap and process/container memory have different denominators. GC pause rate is pause-seconds per second.", be),
        base + "ai-runtime.json": dashboard("keepgo-ai", "KeepGo - AI Providers and Streaming", "Contract v1. Provider attempts include retries; logical requests do not. First-token samples require a delivered token. Token usage is reported usage, not an estimated bill.", ai),
    }
    # ALERTS가 비어 있으면 정상이다. 미등록 서비스에 NoData 장애를 만들지 않는다.
    # Prometheus 단절은 기존 수집 실패 rule과 여기의 execErrState가 감지한다.
    # signal에 원래 종류를 유지한다. Grafana가 예약 label alertname을 덮어쓰기 때문이다.
    expr = 'max by(service,signal,severity,instance,pool,traffic_class,provider,model)(ALERTS{scope="application",alertstate="firing"})'
    result["monitoring/grafana/provisioning/alerting/application.json"] = {
        "apiVersion": 1, "groups": [{
            "orgId": 1, "name": "keepgo-application-relay", "folder": "KeepGo", "interval": "30s",
            "rules": [{
                "uid": "keepgo-application", "title": "KeepGo application signal", "condition": "B",
                "for": "0s", "noDataState": "OK", "execErrState": "Alerting",
                "labels": {"source": "grafana"},
                "annotations": {"summary": "Prometheus application rule is firing. Use signal and service labels; see docs/monitoring-alert-runbook.md."},
                "data": [
                    {"refId": "A", "relativeTimeRange": {"from": 300, "to": 0}, "datasourceUid": DS["uid"],
                     "model": {"refId": "A", "datasource": DS, "expr": expr, "instant": True, "range": False, "intervalMs": 30000, "maxDataPoints": 43200}},
                    {"refId": "B", "relativeTimeRange": {"from": 0, "to": 0}, "datasourceUid": "__expr__",
                     "model": {"refId": "B", "type": "threshold", "expression": "A", "datasource": {"type": "__expr__", "uid": "__expr__"},
                               "conditions": [{"evaluator": {"type": "gt", "params": [0]}, "operator": {"type": "and"}, "query": {"params": ["B"]}, "reducer": {"type": "last", "params": []}, "type": "query"}]}}
                ],
            }],
        }],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for filename, content in artifacts().items():
        path = ROOT / filename
        rendered = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                stale.append(filename)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8", newline="\n")
    if stale:
        raise SystemExit("Run python scripts/render-app-monitoring.py: " + ", ".join(stale))
    print("Application monitoring artifacts are current" if args.check else "Rendered application monitoring artifacts")


if __name__ == "__main__":
    main()
