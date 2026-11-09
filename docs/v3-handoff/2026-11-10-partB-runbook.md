# V3 배포·롤백·장애 대응 Runbook (B 범위)

- 기준: 위키 5-4 9장(실패와 롤백), 5-3 7.1(장애 시나리오), [구현 기록](2026-11-10-partB-k8s-implementation.md)
- 범위: 앱 배포·Pod·확장·권한. 노드·AZ·Spot·네트워크 기반 장애는 A 담당(FIS 실험 포함)
- 원칙: 사람은 클러스터에 직접 쓰지 않는다. 고칠 때는 Git을 바꾸고 Argo CD가 반영한다(5-4 2장). 직접 바꾼 것은 selfHeal이 되돌린다.
- 상태: 절차는 설계·구현 기준이다. dev EKS에서 검증한 뒤 실제 걸린 시간을 각 항목에 적는다.

## 1. 평소 배포

| 단계 | 하는 일 | 확인 |
|---|---|---|
| dev | 앱 저장소 main merge → CI가 이미지 푸시·dev 태그 커밋 → Argo CD 자동 sync | Argo CD dev 앱 Healthy, Discord에 실패 알림 없음 |
| prod 승격 | GitOps 저장소 Actions → `promote-prod`(스택, 태그) → 생성된 PR을 팀 + 플랫폼팀 승인 → merge | Discord "배포 완료", 아래 §1.1 |
| 차트 변경 | `charts/keepgo-app` 수정 + Chart.yaml 버전 올림 → merge(dev는 즉시) → `keepgo-app-<버전>` 태그 생성 → `apps-prod.yaml` targetRevision을 새 태그로 바꾸는 PR | dev에서 9개 서비스 Healthy 확인 후 prod |

SSE(chat·recommend)는 배포마다 연결이 한 번 끊긴다. 사용자가 몰리는 시간에는 prod 배포를 피한다(5-4 8.2).

### 1.1 배포 후 확인(5-4 9.4, 15분)

Grafana `KeepGo V3 / 서비스`에서 바뀐 서비스를 고르고 다음을 본다.

- 5xx 비율, p95·p99 — 배포 전과 비교
- 컨테이너 재시작, OOMKilled
- SSE 서비스: 재연결 후 연결 수 회복(지표가 생긴 뒤)
- Worker: SQS 대기 메시지, DLQ 증가

이상하면 §2 롤백.

## 2. 롤백(5-4 9.3)

| 방법 | 언제 | 절차 |
|---|---|---|
| **Git revert(기본)** | 대부분 | GitOps 저장소에서 태그 변경 커밋을 `git revert` → PR(prod는 승인) → merge → Argo CD가 이전 태그로 sync. 이전 이미지는 ECR `prod-<SHA>` 태그로 남아 있다 |
| Argo CD UI Rollback(긴급) | revert PR을 기다릴 수 없을 때 | 해당 Application auto-sync 끄기 → History에서 이전 버전 Rollback → **바로** Git revert merge → auto-sync 다시 켜기. 켜 둔 채 Rollback하면 Git 상태로 다시 돌아간다 |
| 쓰지 않음 | — | `kubectl rollout undo`, `kubectl edit`, `kubectl set image`(selfHeal이 되돌림) |

Spring 7개는 태그가 한 곳(`apps/_shared/spring-<env>.yaml`)이라 revert 한 번으로 7개가 함께 돌아간다.
DB 스키마는 되돌리지 않는다. 스키마 변경은 expand → contract 순서라 이전 코드가 그대로 동작해야 한다(5-4 8.3).

## 3. 장애별 대응

각 항목: 감지 → 시스템이 자동으로 하는 것 → 자동 복구가 안 되면 사람이 할 일

### 3.1 새 버전이 Ready가 안 됨(Readiness 실패·CrashLoop)
- 감지: 알림 `KeepgoReplicasUnavailable`(10분), Argo CD Degraded + Discord(`progressDeadlineSeconds` 600초 초과)
- 자동: `maxUnavailable: 0`이라 기존 Pod가 계속 요청을 받는다. 새 Pod만 재시작한다.
- 사람: `kubectl -n <ns> logs deploy/<서비스> --previous`로 원인 확인 → Git revert. 기동 시간이 길어진 것이면 `probes.startup.failureThreshold`를 values에서 늘린다.

### 3.2 ImagePullBackOff
- 감지: Argo CD Degraded, `KeepgoReplicasUnavailable`
- 자동: 기존 Pod 유지
- 사람: 태그가 ECR에 있는지(`aws ecr describe-images`), 노드 역할의 ECR 권한(A) 확인. 잘못된 태그면 Git revert.

### 3.3 Pod가 Pending(자원 부족)
- 감지: 대시보드 `KeepGo V3 / 확장·Worker`의 Pending Pod, `kubectl get events -n <ns>`
- 자동: Karpenter가 노드 생성
- 사람: 이벤트 메시지로 원인 구분
  - `exceeded quota` → `platform/tenancy/values-<env>.yaml` quota 상향(+ `check-budget.py` 통과) PR
  - `untolerated taint`·`node affinity` → values의 nodeSelector·tolerations 확인
  - 노드가 안 생김 → NodePool 한도·Subnet IP·AWS 한도(A)

### 3.4 OOMKilled·재시작 반복
- 감지: `KeepgoPodOOMKilled`, `KeepgoPodRestarting`
- 자동: 컨테이너 재시작
- 사람: 메모리 패널(사용량 vs limit), JVM Heap 패널 확인 → `resources`(requests = limits 유지) 상향 PR. Quota·노드 비용 영향은 `check-budget.py`로 확인. prod는 공동 승인(5-4 3.3).

### 3.5 5xx 증가·지연 증가(배포와 무관)
- 감지: `KeepgoHighErrorRate`(5%), `KeepgoHighLatencyP95`(1초)
- 자동: HPA·KEDA 확장(CPU·지표 기준)
- 사람: DB 커넥션 패널(Hikari 사용 중 = 풀 크기면 DB 병목), ai-api 처리 중 요청, 외부 AI 한도 확인. 최근 배포가 있으면 §2.

### 3.6 ExternalSecret 동기화 실패
- 감지: `kubectl get externalsecrets -A`의 `SecretSyncedError`, 새 Pod가 `CreateContainerConfigError`
- 자동: 기존 Pod는 이미 받은 Secret으로 계속 동작
- 사람: SecretStore 상태(`kubectl -n <ns> describe secretstore aws-secrets-manager`) → ESO 역할·Namespace 역할 신뢰 관계·경로 권한(A) 확인
- Secret 값을 바꾼 뒤 Pod 반영: ESO가 1시간 안에 Secret을 갱신하지만 Pod는 재시작해야 읽는다. Git으로 재시작한다: 서비스 values에 `podAnnotations: { secret-rev: "<날짜>" }`를 바꾸는 PR(구현 기록 D21).

### 3.7 SSE 연결 대량 끊김
- 감지: SSE 연결 수 급감(지표 생긴 뒤), 사용자 문의
- 원인 후보: 배포·Scale-in(정상, 재연결로 복구), ALB idle timeout(A 설정, 200초 이상이어야 함), Pod 종료 시간 부족
- 사람: 배포 시간과 겹치는지 먼저 본다. 겹치지 않으면 ALB idle timeout과 `terminationGracePeriodSeconds`(60초)·deregistration delay(50초) 확인.

### 3.8 Worker 작업 적체
- 감지: 대시보드 KEDA 지표(SQS 대기 메시지), DLQ 증가
- 자동: KEDA가 0→N 확장(최대 2, DB 예산), Spot이 없으면 On-Demand(A NodePool)
- 사람: `KEDA 스케일러 오류` 패널이 0이 아니면 KEDA 역할 assume 실패(A IAM) 확인. 최대값을 올리려면 DB 커넥션 예산·ai-api 배치 상한(5-3 5.6) 먼저.

### 3.9 Argo CD 동기화 실패
- 감지: Discord "동기화 실패"
- 원인 후보와 조치

| 메시지 | 원인 | 조치 |
|---|---|---|
| `... is forbidden: User "system:serviceaccount:<ns>:argocd-deployer"` | 차트에 새 리소스 종류를 넣었는데 deployer 권한에 없음 | `platform/rbac/application-deployer.yaml`에 추가 PR |
| `no matching service account found` | 프로젝트에 배포 계정이 없음(impersonation) | `argocd/projects/*.yaml`의 destinationServiceAccounts |
| `resource ... is not permitted in project` | 팀 프로젝트가 금지된 종류(Secret·Role·Quota 등) 생성 | 그 리소스는 platform에서 만든다 |
| helm 렌더링 오류 | values 오류 | CI(validate)가 막았어야 함 → 로컬에서 `bash scripts/validate.sh` |

### 3.10 누가 클러스터를 직접 바꿈
- 감지: Argo CD OutOfSync가 잠깐 보였다가 selfHeal로 사라짐(이력에 남음)
- 자동: selfHeal이 Git 상태로 되돌림
- 사람: 바꾼 내용이 맞는 변경이면 Git에 반영한다. 긴급 직접 변경이 필요하면 해당 Application auto-sync를 끄고, 작업 후 Git 반영 → auto-sync 켜기(V2 배포 충돌 사례, `docs/backlog/v3-deployment-conflict-recovery.md`).

## 4. 권한 문제

| 증상 | 확인 |
|---|---|
| 팀원이 Pod·로그를 못 봄 | `kubectl auth can-i get pods -n <ns> --as=<사용자> --as-group=<그룹>` → Access Entry의 그룹 이름(A)과 tenancy observerGroups가 같은지 |
| 팀원이 예상보다 많이 할 수 있음 | Access Entry에 Access Policy가 붙어 있는지(A). RBAC는 더하기만 된다 |
| 전체 점검 | `feat/v3-k8s-local`의 `scripts/v3-local/rbac-check.sh`(관리자 컨텍스트) |
