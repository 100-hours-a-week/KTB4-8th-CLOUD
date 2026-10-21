# V2 BE 복구·감지 시험 기록

2026-10-21 개발 V2(`keepgo-v2`)에서 BE가 교체되거나 죽을 때 사용자 요청이 얼마나 실패하는지, 경보가 이를 알아채는지 실측했다. 개발파트에 사전 공지한 뒤 진행했다. 도구와 실행 방법은 [scripts/recovery-test](../scripts/recovery-test/README.md)에 있다.

## 조건

- BE 1개(`keepgo-v2-backend:13`, autoscaling 1~1), c7i.large 호스트 1대. 시험 중 EC2 추가 없음.
- 요청: 1초마다 CloudFront → ALB → BE 경로로 인증 없는 GET. Spring의 401 JSON이 오면 성공으로 판정했다.
- 상태 기록: 약 6초 간격. 경보는 장애가 끝나고 10분이 지난 뒤 CloudWatch 경보 이력과 Prometheus `ALERTS`에서 확인했다.
- 한계: 합성 요청 1건/초, 실제 사용자 트래픽 없음, 각 시험 1회. 1초 미만의 끊김은 보이지 않는다.

## 결과 요약

| 항목 | 시험 A: 정상 재배포 | 시험 B: task 강제 종료 |
|---|---|---|
| 사용자 요청 | 470건 중 실패 0 | 423건 중 실패 35 (503 29건, 502 6건) |
| 끊긴 시간 | 없음 | 35초 (07:52:37 ~ 07:53:12) |
| 성공 지연 p95 / 최대 | 188ms / 610ms | 172ms / 875ms |
| 전체 소요 | 시작 → 배포 완료 2분 19초 | 종료 명령 → 새 task 정상 판정 1분 23초 |
| CloudWatch 경보 상태 변화 | 없음 | **없음** |
| Prometheus 경보 | 없음 | `TargetMissing` pending 15초 후 해제, 발송 없음 |
| Discord 수신 | 없음 | **없음** |
| Prometheus 수집 공백 | 없음 (이전·새 대상 수집 기간이 겹침) | 75초 (마지막 07:52:15 → 첫 07:53:30) |

## 시험 A — 정상 재배포 (`--force-new-deployment`, 같은 이미지)

| 시각 (UTC) | 일어난 일 |
|---|---|
| 07:42:43 | 재배포 시작 |
| 07:43:04 | 새 task가 같은 호스트에 배정됨 |
| 07:43:23 | ALB 대상 등록 (initial) |
| 07:43:26 | 새 task RUNNING |
| 07:43:54 | 새 task 컨테이너 HEALTHY, ALB healthy |
| 07:44:00 | Prometheus 새 대상 첫 수집 |
| 07:44:17 | 이전 대상 draining 시작 (deregistration delay 30초) |
| 07:44:47 | 이전 대상 제거 |
| 07:45:02 | 배포 완료, steady state |

새 task를 먼저 띄우고 이전 task를 내리는 롤링 배포(minimum healthy 100%)가 사용자 영향 없이 동작했다. V1 문서의 한계("배포 중 Backend 최대 약 90초 502", [v1-deployment-verification-and-rollback.md](v1-deployment-verification-and-rollback.md) 12절)는 V2 정상 배포에서는 재현되지 않았다. 오탐 경보도 없었다.

## 시험 B — task 강제 종료 (`stop-task`)

| 시각 (UTC) | 일어난 일 | 사용자 요청 |
|---|---|---|
| 07:52:11 | `stop-task` 실행. 기존 task DEACTIVATING | 성공 |
| 07:52:15 | Prometheus가 기존 대상을 마지막으로 수집 | 성공 |
| 07:52:36 | 기존 대상 등록 해제(draining) + 대체 task 시작. 두 일이 동시에 일어남 | |
| 07:52:37 | | **503 시작** (정상 대상 없음) |
| 07:53:05 | 새 대상 등록 (initial) | 502로 바뀜 (앱 기동 전) |
| 07:53:12 | 새 task RUNNING | **성공 복귀** |
| 07:53:28 | 기존 task STOPPED | 성공 |
| 07:53:30 | Prometheus 새 대상 첫 수집. `TargetMissing` pending | 성공 |
| 07:53:34 | 새 task HEALTHY, ALB healthy | 성공 |
| 07:53:45 | `TargetMissing` 해제 (5분 조건 미달) | 성공 |

### 발견

1. **task가 사라지면 대체 task가 준비될 때까지 BE 전체가 끊긴다.** 정상 배포와 달리 ECS가 새 task를 먼저 준비하지 않는다. 기존 대상의 등록 해제와 대체 task 시작이 같은 시각(07:52:36)에 일어났다. 이번에는 Spring 기동이 빨라서 35초였다. 기동이 느리거나 새 task도 실패하면 더 길어진다.
2. **이 장애를 잡는 경보 조건이 없다.**
   - 실패 응답 35건은 모두 ALB가 직접 만든 응답이었다. ALB 지표 `HTTPCode_ELB_5XX_Count`가 07:52에 23, 07:53에 12였다.
   - 기존 CloudWatch 경보는 BE가 만든 5xx(`HTTPCode_Target_5XX_Count`)만 본다. 이 값은 0이었다.
   - `UnHealthyHostCount`도 0이었다. 기존 대상은 unhealthy가 아니라 draining을 거쳐 제거됐다.
   - Prometheus 경보는 3분·5분 지속 조건이라 35초 장애에 반응하지 않았다.
3. **경보가 울려도 전달되지 않는다.** CloudWatch 경보를 보내는 SNS `keepgo-v2-alerts`에 구독자가 0명이다. Grafana에는 Prometheus 데이터소스만 있어서, CloudWatch 경보는 Discord로 오는 경로가 없다.
4. **Prometheus는 사용자보다 늦게 안다.** `TargetMissing`이 pending이 된 시각(07:53:30)은 사용자 요청이 이미 복구된 뒤(07:53:12)였다. 앱 내부 지표와 수집 대상 존재 여부로는 사용자 경로의 실패를 직접 볼 수 없다.
5. 추정 정정: 시험 전에는 ALB health 설정(30초 간격, healthy 5회)을 근거로 "새 대상이 트래픽을 받기까지 2~2.5분, 장애 3~4분"으로 추정했다. 실제로는 healthy 판정 전(initial)인 대상도 07:53:12부터 요청을 처리했다. 정상 대상이 하나도 없을 때의 ALB 동작으로 보인다. 또 `stop-task`부터 등록 해제까지 25초가 걸린 이유는 확인하지 못했다.

## 결정과 다음 작업

| 결과 | 결정 |
|---|---|
| CloudWatch 경보 상태가 바뀌지 않음 | 사용자 경로 경보 추가: `HTTPCode_ELB_5XX_Count`, `HealthyHostCount < 1`. 35초짜리 단발 장애는 무시하고 1~2분 이상 이어질 때 울리도록 기간을 정한다 |
| 전달 경로 없음 | 위 경보를 Discord로 연결. SNS 구독 추가 또는 Grafana CloudWatch 데이터소스 중 선택 |
| Prometheus가 사용자 실패를 보지 못함 | 외부에서 실제 경로를 요청하는 검사는 위 ALB 경보로 대부분 대체되는지 먼저 확인한 뒤 판단 |
| 끊긴 시간 35초 | 개발 환경에서는 health check 조정이나 BE 2개 운영이 불필요. 운영 전환 시 BE min=2(호스트 추가 비용)와 비교 |

개선을 적용한 뒤 같은 도구로 시험 B를 다시 실행해, 경보 발생·Discord 수신 시각을 이 문서와 비교한다.

원본 기록: `.artifacts/recovery-test/20261021-a-redeploy/`, `20261021-b-stop-task/` (git 제외, 내부 IP·task ID 포함).
