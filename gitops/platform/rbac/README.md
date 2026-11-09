# 클러스터 공통 역할(5-2 2.3 RBAC)

| ClusterRole | 누가 | 어떻게 연결 | 허용 | 막는 것 |
|---|---|---|---|---|
| `keepgo-service-observer` | 풀스택·AI팀 그룹 | tenancy 차트가 담당 Namespace에만 RoleBinding | Pod·로그·이벤트·배포·확장·라우트 상태 조회 | Secret, exec/attach/port-forward, 모든 쓰기 |
| `keepgo-application-deployer` | Argo CD(위임 계정 `argocd-deployer`) | tenancy 차트가 Namespace마다 RoleBinding | keepgo-app 차트가 만드는 종류만 생성·변경·삭제 | Role·Binding·Quota·LimitRange·Secret·Namespace |
| `keepgo-platform-operator` | 클라우드 담당팀 그룹 | ClusterRoleBinding(이 폴더) | 공통 인프라 관리 + Secret 빼고 전체 조회(`view`) | 앱 Deployment 직접 수정, Secret 조회, exec |

- 그룹 이름은 A의 EKS Access Entry `kubernetesGroups`와 같아야 한다. **[가정]** `keepgo:platform-operators`, `keepgo:fullstack-observers`, `keepgo:ai-observers`
- RBAC는 더하기만 된다. Access Entry에 Access Policy(예: AmazonEKSClusterAdminPolicy)가 따로 붙어 있으면 여기 제한이 의미 없어진다(partA는 초기 관리자 정책을 나중에 해제한다고 적음).
- `keepgo-platform-operator`는 Role·Binding을 만들 수 있어(`bind`·`escalate`) 사실상 관리자에 가깝다. 일상 작업은 Argo CD로 하고, 사람이 직접 쓰는 것은 장애·초기 구축 때만 한다(5-4 10장).
