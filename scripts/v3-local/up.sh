#!/usr/bin/env bash
# V3 로컬 검증 환경을 처음부터 만든다(kind + A 대신 깔아 두는 기반 + Argo CD + root 앱).
#   GITOPS_DIR=<feat/v3-helm-app-chart 워크트리>/gitops bash scripts/v3-local/up.sh
# 필요한 도구: docker(실행 중), kind, kubectl, helm, git, ssh-keygen
set -euo pipefail

HERE="$(cd "$(dirname "$0")/../.." && pwd)"
LOCAL="$HERE/k8s/v3-local"
: "${GITOPS_DIR:?GITOPS_DIR=<gitops 폴더 경로>가 필요합니다}"
GITOPS_DIR="$(cd "$GITOPS_DIR" && pwd)"
CLUSTER=keepgo-v3
export WORK="${WORK:-$HERE/.v3-local}"
mkdir -p "$WORK"
export GITOPS_DIR

step() { printf '\n== %s\n' "$*"; }

step "1. kind 클러스터"
if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  kind create cluster --config "$LOCAL/kind-config.yaml" --wait 5m
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null
kubectl get nodes -L workload,topology.kubernetes.io/zone

step "2. A가 EKS에 두는 것을 흉내: metrics-server(애드온), Prometheus Operator·Gateway API·Karpenter CRD"
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null 2>&1 || true
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install metrics-server metrics-server/metrics-server --version 3.14.0 -n kube-system \
  --set 'args={--kubelet-insecure-tls}' --wait >/dev/null
helm upgrade --install prometheus-operator-crds prometheus-community/prometheus-operator-crds \
  --version 33.0.1 -n kube-system --wait >/dev/null
# A가 설치한 CRD(LBC Gateway API, Karpenter 1.15.1). RBAC 검사(can-i)는 CRD가 있어야 판정된다.
kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/standard-install.yaml >/dev/null
helm upgrade --install karpenter-crd oci://public.ecr.aws/karpenter/karpenter-crd   --version 1.15.1 -n kube-system --wait >/dev/null
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f - >/dev/null

step "3. 클러스터 안 Git 서버"
[ -f "$WORK/id_ed25519" ] || ssh-keygen -q -t ed25519 -N "" -f "$WORK/id_ed25519"
kubectl create namespace git-server --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n git-server create secret generic git-server-admin \
  --from-file=authorized_key="$WORK/id_ed25519.pub" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl apply -f "$LOCAL/git-server.yaml" >/dev/null
kubectl -n git-server rollout status deploy/git-server --timeout=180s

step "4. gitops push"
bash "$HERE/scripts/v3-local/push-gitops.sh"

step "5. Argo CD 설치(gitops/argocd/bootstrap/values.yaml + 로컬 override)"
helm upgrade --install argocd argo/argo-cd --version 10.17.1 -n argocd --create-namespace \
  -f "$GITOPS_DIR/argocd/bootstrap/values.yaml" -f "$LOCAL/argocd-values.yaml" --wait --timeout 10m >/dev/null
kubectl -n argocd get pods -o wide

step "6. root 앱(전용 bootstrap 프로젝트 먼저)"
kubectl apply -f "$WORK/repo/argocd/bootstrap/project.yaml" -f "$WORK/repo/local/argocd/root-local.yaml"

step "7. 동기화 대기(최대 20분)"
bash "$HERE/scripts/v3-local/wait-apps.sh" 1200
