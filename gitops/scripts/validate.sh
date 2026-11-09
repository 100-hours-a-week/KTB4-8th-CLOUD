#!/usr/bin/env bash
# GitOps 저장소 검증(5-4 4.6). PR마다 CI에서 돌리고, 로컬에서도 같은 명령으로 확인한다.
#   1) 차트 lint
#   2) 서비스 x 환경 전부 helm template (Argo CD ApplicationSet과 같은 values 순서)
#   3) kubeconform으로 쿠버네티스·CRD 스키마 검사(EKS 버전)
#   4) 차트 규칙을 어긴 값이 실제로 거부되는지(negative)
#   5) DB 커넥션 예산·ResourceQuota 충분성(check-budget.py)
# 필요한 도구: helm 3.14+ 또는 4, kubeconform, python3 + PyYAML
# 사용: bash scripts/validate.sh   (gitops 저장소 루트 어디서든)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/.rendered}"
K8S_VERSION="${K8S_VERSION:-1.37.0}"   # partA: keepgo-dev3-eks 1.37
PYTHON="${PYTHON:-python3}"
export PYTHONIOENCODING=utf-8
CHART="$ROOT/charts/keepgo-app"
SPRING_NAMESPACES="account ingest content recommend"
ENVS="dev prod"

cd "$ROOT"
rm -rf "$OUT"
mkdir -p "$OUT"
fail=0

step() { printf '\n== %s\n' "$*"; }
# 여러 YAML 파일을 문서 구분자(---)를 넣어 하나로 잇는다
join() { for f in "$@"; do printf -- '---\n'; cat "$f"; printf '\n'; done; }

step "1. helm lint"
for f in "$CHART"/ci/*-values.yaml; do
  helm lint "$CHART" -f "$f" --quiet >/dev/null || { echo "lint 실패: $f"; fail=1; }
done
for env in $ENVS; do
  helm lint platform/tenancy -f "platform/tenancy/values-$env.yaml" --quiet >/dev/null || { echo "lint 실패: tenancy $env"; fail=1; }
done

step "2. 렌더링(서비스 x 환경)"
for env in $ENVS; do
  mkdir -p "$OUT/$env"
  for dir in apps/*/*/; do
    dir="${dir%/}"
    ns="$(basename "$(dirname "$dir")")"
    svc="$(basename "$dir")"
    [ "$ns" = "_shared" ] && continue
    files=()
    case " $SPRING_NAMESPACES " in
      *" $ns "*) files+=(-f apps/_shared/spring.yaml -f "apps/_shared/spring-$env.yaml") ;;
    esac
    files+=(-f "$dir/values.yaml")
    [ -f "$dir/values-$env.yaml" ] && files+=(-f "$dir/values-$env.yaml")
    if ! helm template "$svc" "$CHART" -n "$ns" "${files[@]}" > "$OUT/$env/app-$ns-$svc.yaml" 2> "$OUT/$env/app-$ns-$svc.err"; then
      echo "렌더링 실패: $env $ns/$svc"; cat "$OUT/$env/app-$ns-$svc.err"; fail=1
    else
      rm -f "$OUT/$env/app-$ns-$svc.err"
      echo "ok  $env $ns/$svc"
    fi
  done
  helm template keepgo-tenancy platform/tenancy -f "platform/tenancy/values-$env.yaml" > "$OUT/$env/platform-tenancy.yaml"
  join platform/rbac/*.yaml > "$OUT/$env/platform-rbac.yaml"
  join platform/priority-classes/*.yaml > "$OUT/$env/platform-priority-classes.yaml"
  join platform/monitoring/*.yaml > "$OUT/$env/platform-monitoring.yaml"
  for f in argocd/projects/*.yaml argocd/platform/"$env"/*.yaml argocd/applicationsets/apps-"$env".yaml argocd/bootstrap/root-"$env".yaml; do
    printf -- '---\n'; cat "$f"
  done > "$OUT/$env/argocd.yaml"
done

step "3. kubeconform (Kubernetes $K8S_VERSION + CRD 스키마)"
kubeconform -strict -summary -output text \
  -kubernetes-version "$K8S_VERSION" \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  "$OUT" || fail=1

step "4. 규칙 위반이 거부되는지(모두 실패해야 정상)"
base=(--set image.repository=r --set image.tag=t --set resources.requests.cpu=100m --set resources.requests.memory=1Gi --set resources.limits.memory=1Gi)
expect_fail() {
  local name="$1"; shift
  if helm template x "$CHART" "$@" >/dev/null 2>&1; then
    echo "통과하면 안 되는데 통과함: $name"; fail=1
  else
    echo "ok  거부됨: $name"
  fi
}
expect_fail "image.tag 없음" --set image.repository=r --set resources.requests.cpu=1 --set resources.requests.memory=1Gi --set resources.limits.memory=1Gi
expect_fail "latest 태그" "${base[@]}" --set image.tag=latest
expect_fail "resources 없음" --set image.repository=r --set image.tag=t
expect_fail "메모리 requests != limits" "${base[@]}" --set resources.limits.memory=2Gi
expect_fail "모르는 probe 프리셋" "${base[@]}" --set probes.preset=django
expect_fail "모르는 최상위 키(오타)" "${base[@]}" --set autoscalling.type=hpa
expect_fail "모르는 autoscaling.type" "${base[@]}" --set autoscaling.type=vpa
expect_fail "HPA 최소 0" "${base[@]}" --set autoscaling.type=hpa --set autoscaling.minReplicas=0
expect_fail "min > max" "${base[@]}" --set autoscaling.type=hpa --set autoscaling.minReplicas=5 --set autoscaling.maxReplicas=2
expect_fail "KEDA 트리거 없음" "${base[@]}" --set autoscaling.type=keda
expect_fail "KEDA 인증 역할 없음" "${base[@]}" --set autoscaling.type=keda --set autoscaling.keda.authentication.enabled=true \
  --set-json 'autoscaling.keda.triggers=[{"type":"aws-sqs-queue","useAuthentication":true,"metadata":{"queueURL":"q"}}]'
expect_fail "HTTPRoute Gateway 없음" "${base[@]}" --set httpRoute.enabled=true --set-json 'httpRoute.pathPrefixes=["/api"]'
expect_fail "HTTPRoute 경로가 /로 시작 안 함" "${base[@]}" --set httpRoute.enabled=true --set-json 'httpRoute.parentRefs=[{"name":"g"}]' --set-json 'httpRoute.pathPrefixes=["api"]'
expect_fail "알 수 없는 PriorityClass" "${base[@]}" --set priorityClassName=keepgo-urgent

step "5. DB 커넥션 예산·ResourceQuota"
"$PYTHON" scripts/check-budget.py "$OUT" scripts/budget.yaml || fail=1

if [ "$fail" -ne 0 ]; then
  printf '\n검증 실패\n'; exit 1
fi
printf '\n모든 검증 통과\n'
