#!/usr/bin/env bash
# 로컬 검증 클러스터와 임시 파일을 지운다.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
kind delete cluster --name keepgo-v3
rm -rf "${WORK:-$HERE/.v3-local}"
