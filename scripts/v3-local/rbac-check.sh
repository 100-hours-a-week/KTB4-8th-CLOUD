#!/usr/bin/env bash
# 5-2 2.3 RBAC 권한표를 kubectl auth can-i로 확인한다. 기대값과 하나라도 다르면 실패한다.
# 관리자 컨텍스트(가장 권한, impersonate 가능)에서 실행한다. kind에서는 기본 컨텍스트가 관리자다.
# dev EKS에서도 같은 명령으로 쓴다. 단, Access Entry에 Access Policy가 따로 붙어 있으면 결과가 더 넓게 나온다.
set -uo pipefail

fail=0
pass=0
# check <기대 yes|no> <설명> <can-i 인자...>
check() {
  local want="$1" desc="$2"; shift 2
  local got
  got="$(kubectl auth can-i "$@" 2>/dev/null | tr -d '\r')"
  [ -z "$got" ] && got="no"
  if [ "$got" = "$want" ]; then
    pass=$((pass + 1)); printf 'ok    %-3s %s\n' "$got" "$desc"
  else
    fail=$((fail + 1)); printf 'FAIL  %-3s (기대 %s) %s\n' "$got" "$want" "$desc"
  fi
}

FS=(--as=test-fullstack --as-group=keepgo:fullstack-observers)
AI=(--as=test-ai --as-group=keepgo:ai-observers)
OP=(--as=test-operator --as-group=keepgo:platform-operators)
DEP=(--as=system:serviceaccount:account:argocd-deployer)
ANY=(--as=test-nobody)

echo "[풀스택 조회 그룹] 담당 Namespace 조회만"
check yes "account Pod 조회"                     get pods -n account "${FS[@]}"
check yes "recommend Pod 로그"                   get pods/log -n recommend "${FS[@]}"
check yes "ingest Deployment 조회"               get deployments.apps -n ingest "${FS[@]}"
check yes "recommend ScaledObject 조회"           list scaledobjects.keda.sh -n recommend "${FS[@]}"
check yes "account HTTPRoute 조회"               get httproutes.gateway.networking.k8s.io -n account "${FS[@]}"
check yes "frontend 이벤트 조회"                   list events -n frontend "${FS[@]}"
check no  "ai Namespace 조회(AI팀 담당)"          get pods -n ai "${FS[@]}"
check no  "Secret 조회"                          get secrets -n account "${FS[@]}"
check no  "Pod exec"                             create pods/exec -n account "${FS[@]}"
check no  "Pod port-forward"                     create pods/portforward -n account "${FS[@]}"
check no  "Deployment 수정"                       patch deployments.apps -n account "${FS[@]}"
check no  "Deployment 삭제"                       delete deployments.apps -n account "${FS[@]}"
check no  "RoleBinding 생성"                      create rolebindings.rbac.authorization.k8s.io -n account "${FS[@]}"
check no  "클러스터 전체 Pod 조회"                  list pods -A "${FS[@]}"

echo "[AI 조회 그룹] ai만"
check yes "ai Pod 조회"                          get pods -n ai "${AI[@]}"
check yes "ai Pod 로그"                          get pods/log -n ai "${AI[@]}"
check no  "account Pod 조회"                     get pods -n account "${AI[@]}"
check no  "ai Secret 조회"                       get secrets -n ai "${AI[@]}"
check no  "ai Deployment 수정"                    patch deployments.apps -n ai "${AI[@]}"

echo "[플랫폼 운영 그룹] 공통 인프라 관리 + Secret 제외 조회"
check yes "Namespace 생성"                        create namespaces "${OP[@]}"
check yes "ResourceQuota 수정"                    patch resourcequotas -n account "${OP[@]}"
check yes "ClusterRole 생성"                      create clusterroles.rbac.authorization.k8s.io "${OP[@]}"
check yes "NetworkPolicy 생성"                    create networkpolicies.networking.k8s.io -n ai "${OP[@]}"
check yes "PriorityClass 생성"                    create priorityclasses.scheduling.k8s.io "${OP[@]}"
check yes "NodePool 생성"                         create nodepools.karpenter.sh "${OP[@]}"
check yes "Gateway 수정"                          patch gateways.gateway.networking.k8s.io -n gateway-system "${OP[@]}"
check yes "노드 조회"                             list nodes "${OP[@]}"
check yes "모든 Namespace Pod 조회(view)"          list pods -A "${OP[@]}"
check no  "Secret 조회"                          get secrets -n account "${OP[@]}"
check no  "앱 Deployment 직접 수정(쓰기는 Argo CD)"  patch deployments.apps -n account "${OP[@]}"
check no  "Pod exec"                             create pods/exec -n account "${OP[@]}"
check no  "CRD 수정(Argo CD platform 프로젝트로만)"  create customresourcedefinitions.apiextensions.k8s.io "${OP[@]}"

echo "[Argo CD 배포 계정 account/argocd-deployer] 자기 Namespace의 차트 리소스만"
check yes "Deployment 생성"                       create deployments.apps -n account "${DEP[@]}"
check yes "Service 수정"                          patch services -n account "${DEP[@]}"
check yes "HPA 생성"                              create horizontalpodautoscalers.autoscaling -n account "${DEP[@]}"
check yes "ScaledObject 생성"                     create scaledobjects.keda.sh -n account "${DEP[@]}"
check yes "ExternalSecret 생성"                   create externalsecrets.external-secrets.io -n account "${DEP[@]}"
check yes "HTTPRoute 생성"                        create httproutes.gateway.networking.k8s.io -n account "${DEP[@]}"
check yes "NetworkPolicy 생성"                    create networkpolicies.networking.k8s.io -n account "${DEP[@]}"
check yes "PodMonitor 생성"                       create podmonitors.monitoring.coreos.com -n account "${DEP[@]}"
check yes "마이그레이션 Job 생성"                    create jobs.batch -n account "${DEP[@]}"
check no  "다른 Namespace(ai)에 생성"              create deployments.apps -n ai "${DEP[@]}"
check no  "Secret 생성"                          create secrets -n account "${DEP[@]}"
check no  "Secret 조회"                          get secrets -n account "${DEP[@]}"
check no  "RoleBinding 생성"                      create rolebindings.rbac.authorization.k8s.io -n account "${DEP[@]}"
check no  "ResourceQuota 수정"                    patch resourcequotas -n account "${DEP[@]}"
check no  "Namespace 생성"                        create namespaces "${DEP[@]}"
check no  "ClusterRole 생성"                      create clusterroles.rbac.authorization.k8s.io "${DEP[@]}"

echo "[그룹 없는 사용자]"
check no  "account Pod 조회"                     get pods -n account "${ANY[@]}"

printf '\n통과 %d, 실패 %d\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
