# 앱 대시보드

- `dashboard-*.yaml`은 `scripts/gen-dashboards.py`로 만든다. 패널을 바꾸려면 스크립트를 고치고 `python scripts/gen-dashboards.py`(gitops 루트에서)를 다시 실행한다.
- Grafana·Prometheus 설치는 A 담당(partA 4장 System 노드 컴포넌트). 여기는 B 담당인 앱 대시보드만 둔다.
- [가정] kube-prometheus-stack의 Grafana sidecar가 `grafana_dashboard: "1"` 라벨 ConfigMap을 읽는다.
- 서비스별 알림 규칙은 keepgo-app 차트의 PrometheusRule(`alerts`)이 서비스마다 만든다.
- `alertmanager-config.yaml`: 차트 알림(`Keepgo*`)을 Discord로 보낸다. A의 Alertmanager에 `alertmanagerConfigMatcherStrategy.type: None`이 필요하고, webhook Secret `keepgo-alert-discord`(키 `url`)는 사람이 만든다.
