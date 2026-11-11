# V3 dev3 검증 시나리오: 스케일링·CI/CD 반복·동시 배포·모니터링 연속성 (2026-11-11)

- 대상: dev3 EKS(`keepgo-dev3-eks`), GitOps 레포 `KTB4-8th-CLOUD-GITOPS`, Argo CD
- 목적: "배포하고 늘리고 줄이는 동안 사용자 요청이 실패하지 않고, 모니터링(지표·로그·트레이스·알림)이 끊기지 않는다"를 숫자로 확인한다.
- 실행: rowan. 결과는 이 문서 §7 표에 채운다.
- 관련: [결정 기록](2026-11-10-partB-msa-review.md) §5, [사용자 할 일](2026-11-10-partB-user-todo.md) §4.2, [Runbook](2026-11-10-partB-runbook.md)

## 1. 지금 dev3 설정 (11-11 확인, 기대값의 근거)

| 항목 | 값 | 시나리오에서 기대하는 것 |
|---|---|---|
| 롤링 업데이트 | `maxSurge: 1`, `maxUnavailable: 0`, 종료 유예 40초, ALB deregistration 30초 | 배포 중 가용 Pod 수가 줄지 않음 → 5xx 0 |
| HPA(auth·member·youtube·wishlist·web) | CPU 70%, min 1 / max 2, 확장 60초 안정화·최대 2개/분, 축소 300초 안정화·1개/분 | 부하 1~2분 뒤 2개, 부하 종료 5~6분 뒤 1개 |
| KEDA(chat·recommend·ai) | 앱 지표 + CPU, min 1 / max 2 | 위와 같음 |
| KEDA(worker) | SQS, min 0 / max 2 | **SQS 큐가 없어 보류**(dice) |
| PDB | 없음(dev는 min 1) | 노드 drain 때 Pod 1개짜리 서비스는 잠깐 0개가 될 수 있음 → §5 S5에서 확인 |
| Karpenter application NodePool | 한도 CPU 16 / 64Gi, `WhenEmpty` 30분 | 노드가 늘고, 빈 노드는 30분 뒤 정리 |
| 수집 | PodMonitor 30초, Prometheus **1개**(PVC 20Gi, application 노드), 보관 7일 | 서비스 Pod 교체 중 공백 없음. Prometheus 자체가 옮겨질 때는 공백이 생김(S6에서 길이 측정) |
| 로그·트레이스 | Fluent Bit(DaemonSet) → CloudWatch Logs, OTel Collector 1개 → X-Ray | 새 Pod 로그가 곧 나타나고, 종료되는 Pod의 마지막 로그도 남음 |
| 자동 CD | EventBridge(ECR push + 10분) → `auto-release-dev` → values-dev PR 자동 병합 → Argo CD(Git 확인 약 3분 주기) | develop merge부터 dev 반영까지 시간을 잰다 |

## 2. 준비

1. **구글 로그인 확인**: dev3 OAuth 리디렉션 URI 등록 후 로그인이 되는지 확인한다. 부하 스크립트에 토큰이 필요하다.
2. **도구**: `winget install k6`. kubeconfig는 `C:\Users\suhyu\.kube\keepgo-dev3.yaml`이다.
3. **팀 공지**: 테스트 시간대에 dev3 배포·알림이 몰린다는 것을 알린다(Discord).
4. **자동 반영 끄기**(통제 시나리오 동안): `gh variable set AUTO_DEPLOY_ENABLED -R 100-hours-a-week/KTB4-8th-CLOUD-GITOPS --body false`. 켜 두면 테스트 중에 개발팀 develop merge가 끼어들고, 롤백한 태그를 10분 안에 다시 최신으로 올린다. S1만 켠 상태로 한다.
5. **번갈아 쓸 태그**(둘 다 정상 기동 확인된 것): backend `0de1a1f…` ↔ `ce18544…`, ai `e355d38…` ↔ `6e9c5cf…`, web `4a399d4…` ↔ `b21465f…`. 태그 변경은 GitOps PR로 한다: `bash scripts/set-image-tag.sh <SHA> <values 파일>` → PR → merge.
   - backend를 옛 태그로 돌려도 DB는 V9 그대로다. 스키마가 확장만 하는 방식(expand)이라 옛 코드도 동작한다고 보지만, 실패하면 그것도 결과로 기록한다.
6. **배경 트래픽**(모든 배포 시나리오에서 켜 둠): 낮은 일정 부하로 "배포 중 실패한 요청"을 센다.
   ```powershell
   k6 run -e BASE_URL=https://dev3.keepgo.kr -e TOKEN=<토큰> -e TARGET_RPS=20 tests/v3/load/api.js
   ```
   스크립트는 `feat/v3-k8s-local` 브랜치에 있다. 램프 3분, 유지 10분 구성이라 배포 시나리오는 유지 구간 안에서 시작한다.
7. **지켜볼 창 4개**
   - `kubectl get pods -A -w`
   - `kubectl get hpa -A -w`
   - Argo CD 화면
   - Grafana(`dev3.keepgo.kr/grafana`)의 KeepGo V3 service·scaling 대시보드

## 3. 측정 항목 (모든 시나리오 공통)

| 지표 | 보는 곳 | 합격 |
|---|---|---|
| 요청 실패율 | k6 결과 `http_req_failed`, ALB `HTTPCode_Target_5XX_Count`·`HTTPCode_ELB_5XX_Count`(CloudWatch, 1분) | 0%(배포·축소 중 5xx 0) |
| 지연 | k6 `p(95)` | 배포 중 p95가 평시의 2배 이하 |
| 반영 시간 | merge 시각 → Argo CD Synced → 모든 새 Pod Ready | 기록만(기준선) |
| 지표 공백 | 아래 PromQL | 서비스 Pod 교체 중 0초 |
| 로그 공백 | CloudWatch Logs Insights | 새 Pod 로그가 1분 안에 보이고, 종료 Pod의 마지막 로그(종료 메시지) 남음 |
| 트레이스 | X-Ray | 배포 전후 트레이스가 이어짐(공백 없음) |
| 알림 | Discord | 정상 롤아웃 중 거짓 알림 없음. 실패 시나리오는 알림 1회 + 해결(resolved) 1회 |

**지표 공백 PromQL** (Grafana Explore, 범위는 시나리오 시작~끝)
```promql
# 서비스별 수집 중인 Pod 수: 롤아웃 중에도 0이 되면 안 됨
count by (namespace, service) (up{namespace=~"account|ai|content|frontend|ingest|recommend"} == 1)

# 서비스별 요청률: 선이 끊기면(no data) 공백
sum by (service) (rate(http_server_requests_seconds_count[1m]))

# Prometheus 자체 공백: 1분 간격 증가량 확인(재시작이 있으면 그만큼 비어 있음)
changes(process_start_time_seconds{job=~".*prometheus.*"}[1h])
```

**로그 공백** (CloudWatch Logs Insights, 앱 로그 그룹)
```text
fields @timestamp, kubernetes.pod_name, @message
| filter kubernetes.namespace_name = "account"
| stats count() by bin(30s), kubernetes.pod_name
```
교체되는 동안 두 Pod의 로그 구간이 겹치거나 맞닿아야 한다(사이에 빈 bin이 없어야 함).

## 4. CI/CD 시나리오

| ID | 시나리오 | 방법 | 반복 | 합격 |
|---|---|---|---:|---|
| **C1** | 자동 반영 전 과정 | `AUTO_DEPLOY_ENABLED=true` 상태에서 개발팀 develop merge(또는 ECR push)를 기다린다 | 2 | EventBridge 실행 → `release(dev)` PR 자동 병합 → Argo CD 반영. 반영 시간 기록. 5xx 0 |
| **C2** | 단일 서비스 반복 배포 | ai 태그를 A↔B로 번갈아 PR·merge(배경 트래픽 켬) | **5** | 매번 5xx 0, 반영 시간 편차 기록, 지표·로그 공백 0 |
| **C3** | 7개 동시 배포(backend 한 번) | backend 태그 변경 → Spring 7개 Deployment가 동시에 롤링 | **3** | 5xx 0, 동시 surge 7개로 DB 커넥션이 한도(170) 안(`max_connections` 대비 Grafana RDS 패널), 노드 부족 시 Karpenter가 노드 추가, Pending 오래 안 감 |
| **C4** | 그룹 3개 동시 배포 | backend·ai·web 태그를 한 PR에 같이 변경 → merge | 2 | 9개 Deployment 동시 롤링에서도 5xx 0, 공백 0 |
| **C5** | 배포 중 다음 배포 | C3 시작 1분 뒤 backend 태그를 다시 바꿔 merge(롤링 도중 덮어쓰기) | 2 | Argo CD가 최신 커밋으로 수렴, 멈춘 ReplicaSet 없음, 최종 태그 = 마지막 커밋 |
| **C6** | 실패 배포와 롤백 | 없는 태그로 변경(`scripts/v3-local/chaos.sh image-pull` 또는 수동) → 관찰 → 커밋 revert | 2 | 기존 Pod 유지(5xx 0), Argo CD Degraded + Discord 알림 1회, revert 후 Healthy + resolved |
| **C7** | 기동 실패 배포 | readiness가 실패하는 설정(`chaos.sh readiness-fail`) → revert | 1 | C6과 같음. 11-11의 실제 사례(Kakao 키·DB 테이블)와 같은 경로 |
| **C8** | selfHeal | `kubectl -n content delete svc wishlist-api`, Deployment에 임의 env 추가 | 각 1 | Argo CD가 수 분 안에 Git 상태로 복구(replicas는 HPA 관리라 대상 아님) |

## 5. 스케일링 시나리오

| ID | 시나리오 | 방법 | 합격 |
|---|---|---|---|
| **S1** | HPA 확장·축소 | k6 `TARGET_RPS` 50 → 100 → 200(각 단계 유지 10분) | CPU 70% 넘으면 1~2분 안에 2개, 부하 종료 5~6분 뒤 1개. 늘고 줄 때 5xx 0 |
| **S2** | 축소 중 요청 안전 | S1 끝의 축소 구간에 배경 트래픽 유지 | 종료되는 Pod로 간 요청 실패 0(preStop·deregistration 동작) |
| **S3** | KEDA 앱 지표 확장 | chat·recommend: SSE 연결을 늘린다(`tests/v3/load/sse.js`). ai: 동시 요청 | 지표가 목표값을 넘으면 2개. 지표가 없으면 CPU로 확장되는지 |
| **S4** | Karpenter 노드 추가·정리 | S1 200 RPS + C3를 겹쳐 Pod 요청량을 키운다. 부족하면 임시 테스트 Deployment(요청 CPU를 크게)로 강제 | 새 노드가 몇 분 안에 Ready, Pending 해소. 부하 후 빈 노드가 30분 뒤 정리 |
| **S5** | 노드 교체(Pod 1개짜리 서비스) | 앱 Pod가 있는 application 노드 하나를 `kubectl drain` | **알려진 위험**: dev는 PDB가 없고 min 1이라 그 서비스가 잠깐 0개가 될 수 있다. 공백 시간과 5xx를 기록한다. 길면 dev에도 핵심 API min 2를 검토 |
| **S6** | 관측 스택 이동 | Prometheus Pod가 있는 노드 drain(또는 Pod 삭제) | **알려진 위험**: Prometheus가 1개 + EBS PVC(AZ 고정)라 공백이 생긴다. 공백 길이를 재고, 다른 AZ로 옮겨질 때 PVC 붙는 시간을 확인한다. 그 사이 알림 평가도 멈추므로 결과에 따라 "Prometheus가 죽었는지 감시하는 장치"(Discord로 Watchdog 끊김 알림)를 검토 |

## 6. 진행 순서 (약 반나절)

| 순서 | 묶음 | 이유 |
|---:|---|---|
| 1 | 기준선: 배경 트래픽만 10분(지연·오류·지표 정상 값) | 비교 기준 |
| 2 | C8 → C2 → C6·C7 | 영향이 작은 것부터, 실패 경로 확인 |
| 3 | C3 → C4 → C5 | 동시·연속 배포 |
| 4 | S1 → S2 → S3 → S4 | 부하(토큰 필요) |
| 5 | S5 → S6 | 노드·관측 스택 교체(공백이 생길 수 있는 것은 마지막) |
| 6 | C1 | 자동 반영 다시 켜고 실제 개발팀 merge로 마무리 |
| 7 | 정리 | `AUTO_DEPLOY_ENABLED=true` 확인, 테스트용 리소스 삭제, 결과 기록 |

## 7. 결과 기록

| ID | 회차 | 시각 | 반영 시간 | 5xx(k6 / ALB) | p95 | 지표 공백 | 로그 공백 | 알림 | 결과·메모 |
|---|---:|---|---|---|---|---|---|---|---|
| 기준선 | 1 | | — | | | | | | |
| C2 | 1 | | | | | | | | |
| … | | | | | | | | | |

시나리오가 실패하면 원인 분석이 필요한 것만 `docs/troubleshooting/`에 사례로 남긴다. 결정이 바뀌면 결정 기록 §5에 추가한다.

## 8. 이 시나리오로 확인되지 않는 것

- worker SQS 확장: SQS 큐와 앱의 SQS 소비 코드가 생긴 뒤에 한다.
- prod 규모 숫자(1,600 RPS 등): dev는 max 2라 반응만 본다. 규모는 prod 전환 전 별도 부하 테스트로 한다.
- DB 마이그레이션이 들어간 배포: [backlog](../backlog/v3-db-schema-migration-job.md) 구현 뒤 C3에 "새 마이그레이션 포함" 회차를 추가한다.
