#!/usr/bin/env bash
# Pod·배포 장애 재현(WBS 19, 5-3 7.1, 5-4 9.2). kind 또는 dev EKS에서 시나리오 하나씩 실행하고 결과를 기록한다.
# 노드·AZ·Spot 장애는 A가 AWS FIS로 주입한다(5-2 R1). 여기서는 B 범위(Pod·배포)만 다룬다.
#   bash scripts/v3-local/chaos.sh <시나리오> [namespace] [서비스]
# 시나리오
#   pod-kill        Pod 하나 삭제 → 재생성 시간, 그동안 Ready Pod 수
#   readiness-fail  readiness 포트를 잘못 바꾼 이미지·값을 가정: Pod를 Service에서 빼는지(직접 patch → selfHeal로 되돌아오는 것도 확인)
#   image-pull      없는 태그로 patch → 기존 Pod 유지·새 Pod ImagePullBackOff → selfHeal 복구
#   drain           노드 비우기(PDB 준수 확인). kind 전용
# 직접 patch는 Argo CD selfHeal이 Git 상태로 되돌린다(5-4 2장 원칙). 되돌아오는 시간도 결과로 남긴다.
set -euo pipefail

scenario="${1:?시나리오 필요: pod-kill|readiness-fail|image-pull|drain}"
ns="${2:-account}"
svc="${3:-auth-api}"
ts() { date +%H:%M:%S; }
ready() { kubectl -n "$ns" get deploy "$svc" -o jsonpath='{.status.readyReplicas}/{.spec.replicas}'; }
watch_ready() {
  local until="$1"
  for _ in $(seq 1 "$until"); do
    printf '%s ready=%s\n' "$(ts)" "$(ready)"
    sleep 5
  done
}

case "$scenario" in
  pod-kill)
    pod="$(kubectl -n "$ns" get pod -l "app.kubernetes.io/name=$svc" -o jsonpath='{.items[0].metadata.name}')"
    echo "$(ts) 삭제: $pod"
    kubectl -n "$ns" delete pod "$pod" --wait=false
    watch_ready 12
    ;;
  readiness-fail)
    echo "$(ts) readiness 포트를 9999로 patch(Argo CD selfHeal이 되돌리는지 함께 확인)"
    kubectl -n "$ns" patch deploy "$svc" --type=json \
      -p='[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":9999}]'
    watch_ready 24
    kubectl -n "$ns" get endpointslices -l "kubernetes.io/service-name=$svc" -o wide
    ;;
  image-pull)
    echo "$(ts) 없는 이미지 태그로 patch"
    img="$(kubectl -n "$ns" get deploy "$svc" -o jsonpath='{.spec.template.spec.containers[0].image}')"
    kubectl -n "$ns" set image "deploy/$svc" "app=${img%:*}:does-not-exist"
    watch_ready 24
    kubectl -n "$ns" get pods -l "app.kubernetes.io/name=$svc"
    ;;
  drain)
    node="$(kubectl -n "$ns" get pod -l "app.kubernetes.io/name=$svc" -o jsonpath='{.items[0].spec.nodeName}')"
    echo "$(ts) drain: $node (PDB maxUnavailable 1을 지키는지)"
    kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data --timeout=5m || true
    watch_ready 12
    kubectl uncordon "$node"
    ;;
  *)
    echo "모르는 시나리오: $scenario"; exit 2 ;;
esac
