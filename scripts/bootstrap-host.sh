#!/usr/bin/env bash
# Docker, AWS CLI, SSM Agent와 runtime.json을 준비한 뒤 기존 EC2에서 실행한다.
set -euo pipefail
[[ "$(id -u)" == 0 ]] || { echo 'Run as root'; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
for tool in docker aws python3 systemctl curl; do command -v "$tool" >/dev/null; done
docker compose version
test -f /opt/keepgo/runtime.json
install -d -m 0700 /opt/keepgo/state /opt/keepgo/releases /opt/keepgo/ops/scripts
chmod 0600 /opt/keepgo/runtime.json
install -m 0644 "${SCRIPT_DIR}/release.py" "${SCRIPT_DIR}/deploy.py" "${SCRIPT_DIR}/monitor.py" /opt/keepgo/ops/scripts/
IMDS_TOKEN="$(curl --fail --silent --show-error --max-time 5 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token)"
curl --fail --silent --show-error --max-time 5 -H "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" \
  http://169.254.169.254/latest/meta-data/instance-id > /opt/keepgo/instance-id
install -m 0644 "${ROOT_DIR}/monitoring/keepgo-monitor.service" "${ROOT_DIR}/monitoring/keepgo-monitor.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now keepgo-monitor.timer
