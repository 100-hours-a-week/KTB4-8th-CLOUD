# V3 로컬 검증(kind)

GitOps 저장소(`feat/v3-helm-app-chart` 브랜치의 `gitops/`)를 **실제와 같은 방식(Argo CD)**으로 kind에 적용해, AWS 없이 확인할 수 있는 것만 검증한다. 이 폴더는 Argo CD가 동기화하지 않는 파일이라 GitOps 저장소가 아니라 Cloud 레포에 둔다.

## 무엇을 흉내 내는가

| 실제(dev EKS, A 담당) | 로컬 |
|---|---|
| System MNG `workload=system` + Taint | system 노드 1대(라벨·Taint 같음) |
| Application NodePool `workload=application`, AZ a·c | application 노드 2대(zone 라벨 a·c) |
| Worker NodePool `workload=worker` + Taint([가정] 키) | worker 노드 1대 |
| Metrics Server 애드온 | metrics-server 차트 |
| kube-prometheus-stack(CRD) | prometheus-operator-crds 차트 |
| GitHub keepgo-gitops | 클러스터 안 Git 서버(soft-serve) |
| ECR 이미지 | busybox Mock(`overlay/values/`) |

로컬에서 끄는 것(AWS가 있어야 동작): SecretStore·ExternalSecret, HTTPRoute·TargetGroupConfiguration, SQS·Prometheus KEDA 트리거(→ CPU 트리거), GitHub 로그인·Discord 알림.

## 실행

```bash
# 레포 루트에서. gitops 워크트리 경로를 넘긴다.
export GITOPS_DIR=../v3-helm-chart/gitops     # .worktrees 안에서 실행할 때 예시
bash scripts/v3-local/up.sh          # kind → 기반 → Git 서버 → push → Argo CD → root 앱 → 동기화 대기
bash scripts/v3-local/rbac-check.sh  # 5-2 권한표
bash scripts/v3-local/np-check.sh    # ai-api 허용·차단
bash scripts/v3-local/down.sh        # 정리
```

값을 바꿔 다시 동기화하려면 `bash scripts/v3-local/push-gitops.sh`만 다시 실행한다(`WORK`, `GITOPS_DIR` 필요).

Argo CD 화면: `kubectl -n argocd port-forward svc/argocd-server 8080:80` → http://localhost:8080, 계정 `admin`, 비밀번호 `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`

## 실행하지 않고 남겨 둔 도구(dev EKS에서 사용)

| 파일 | 용도 |
|---|---|
| `scripts/v3-local/chaos.sh` | Pod 삭제·readiness 실패·ImagePull 실패·drain 재현(5-3 7.1, 5-4 9.2) |
| `tests/v3/load/api.js` | k6 일반 API 부하(HPA·Karpenter 반응) |
| `tests/v3/load/sse.js` | k6 SSE 동시 연결(KEDA·재연결) |
