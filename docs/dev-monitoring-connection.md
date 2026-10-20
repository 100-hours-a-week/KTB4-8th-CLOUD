# 개발 환경 모니터링 연결 작업 기록

작성일: 2026-10-19 (KST). 갱신: 2026-10-21. **10월 20일 적용 검증 완료: 피어링·AI 계측·개발 수집·대시보드, 운영 9개+개발 2개 모두 up, Discord 경보·복구 전송 성공. Cloud PR #112는 미병합 상태를 확인했고, 사용자 결정으로 열어둔다**. 12절에 로그 사용성과 비용 비교 후속 기록을 추가했다.

아래 1~10절의 미확정·미적용 표현은 최초 계획 당시 기록이다. 현재 결정과 적용 결과는 11절을 우선한다.

기존 모니터링 EC2의 Prometheus·Grafana에 개발 환경을 연결한다. 확인한 사실, 사용자 결정, 구현 제안, 적용 결과를 구분해서 갱신한다. 새로운 관측 도구 도입보다 기존 수집·조회·알림 연결을 먼저 완료한다.

## 1. 결정 기록

| ID | 날짜 | 결정 | 근거·결정 주체 |
| --- | --- | --- | --- |
| D-001 | 2026-10-19 | 기존 모니터링 EC2를 재사용한다 | 사용자: 기존 구성부터 연결하고 이후 확장 검토 |
| D-002 | 2026-10-19 | 1차 대상은 V2 개발 BE·AI | 사용자 응답: “BE·AI부터 연결” |
| D-003 | 2026-10-19 | 기존 Discord 채널에 개발 알림을 보내고 `[DEV]`로 표시한다 | 사용자 응답: “기존 Discord 채널에 [DEV]로 구분” |
| D-004 | 2026-10-19 | 단계별로 진행하며 모호한 사항과 선택이 필요한 사항은 질문한다 | 사용자 지시. 결정과 검증 결과를 이 문서에 누적 |
| D-005 | 2026-10-19 | 에이전트가 AI 수정 계획을 먼저 작성한다 | 사용자: “네트워크 설명좀, ai수정도 일단 네가 계획 세워봐”. 이 응답은 피어링 적용이나 AI PR 병합 결정이 아님 |
| D-006 | 2026-10-20 | 기존 구성과 제한된 피어링으로 개발 BE·AI를 실제 연결한다. AI main 계측을 develop에 선별 재사용한다 | 사용자 구현 지시 및 “마저 진행해” |
| D-007 | 2026-10-20 | 현재 V1=운영, V2=개발. 향후 역할을 전환할 예정이므로 인프라 버전과 환경 의미를 분리한다 | 사용자 설명 |

## 2. 실제 확인한 사항

### AWS 읽기 전용 조회

- 기존 사용자 인증으로 서울 리전 AWS 계정 조회 성공. 샌드박스에서는 인증을 찾지 못해 승인된 외부 실행으로 조회했다.
- `keepgo-v1-monitoring`: 실행 중, `t4g.small`, VPC `vpc-028e5c0c4fa690a01`.
- `keepgo-01` 운영 앱 EC2는 모니터링 서버와 같은 VPC에 있다.
- `keepgo-v2-backend` ECS 호스트: 실행 중, `c7i.large`, VPC `vpc-0bfd4e11c520dc5fd`.
- **모니터링 EC2와 개발 ECS는 다른 VPC다.** 운영 VPC는 `172.31.0.0/16`, 개발 VPC는 `10.20.0.0/16`으로 겹치지 않는다. 피어링 목록은 비어 있고 두 VPC의 라우트 테이블에 상호 연결 경로가 없다.
- ECS `keepgo-v2`의 backend, ai-api, frontend는 모두 desired/running=1, pending=0, rollout COMPLETED다. BE·AI task health는 HEALTHY다. FE는 사용자 결정에 따라 이번 연결에서 제외한다.
- 실행 중인 Task Definition은 BE `keepgo-v2-backend:3`, AI `keepgo-v2-ai-api:5`. BE 8081, AI 9464 TCP 포트가 정의돼 있다. 실제 응답은 아래 SSM 점검에서 확인했다.
- 모니터링 SG는 운영 앱 SG로만 8081~9464 송신을 허용한다. 개발 BE 8081 수신은 ALB SG에만 허용되며, 개발 AI SG에는 9464 수신 규칙이 없다.
- 모니터링 EC2와 ECS 호스트의 SSM 상태는 Online이다.

### SSM으로 실행 환경 확인

고정된 읽기 전용 진단만 실행했다. 컨테이너 재시작, 패키지 설치, 앱 설정 변경은 하지 않았다.

| 항목 | 확인 결과 | 해석·한계 |
| --- | --- | --- |
| 모니터링 호스트 | 메모리 총 1,840MiB, 가용 983~991MiB. 루트 디스크 20GB 중 31% 사용, 약 14GB 여유 | 점검 시점의 순간값. 추가 수집 후 추세를 재측정해야 함 |
| Prometheus | 약 77~78MiB / 512MiB 제한, 컨테이너 healthy | 현재 운영 수집 부하의 기준값 |
| Grafana | 약 318MiB / 512MiB 제한, 컨테이너 healthy | 기존 메모리 제한 유지 가능성은 추가 수집 후 검증 |
| 기존 수집 | 활성 대상 9개 전부 scrape health=up | blackbox의 scrape 성공은 probe 대상의 업무 정상 여부와 다름. probe_success는 아직 별도 검증하지 않음 |
| 운영 환경 라벨 | 활성 대상 labels에 environment 없음 | 실제 수집에도 환경 분리가 아직 없음 |
| 개발 BE | task 네트워크 내부에서 `/actuator/prometheus` HTTP 200, 151개 고유 metric 이름 확인 | JVM·Hikari·HTTP histogram·keepgo_observability_info 존재. 계약 label 값과 외부 수집 경로는 추가 검증 |
| 개발 AI | task 내부 9464 연결 거부. 실제 TCP listener는 `0.0.0.0:8000` 하나 | 보안 그룹만 열어 해결되지 않음 |
| 개발 AI 계측 | 실행 컨테이너에 prometheus_client 미설치. `/app/app` Python 소스 37개에 prometheus_client/start_http_server/9464/keepgo_observability_info 참조 없음 | 현재 개발 이미지에 기존 Prometheus 계측을 추가하는 앱 변경이 필요 |

모니터링 설정 bind mount는 `/opt/keepgo/observability/monitoring/` 아래다. 기존 데이터 volume은 유지하는 방향으로 변경안을 작성한다. 비밀 파일의 경로만 확인했으며 내용은 읽지 않았다.

조회 원본은 Git에서 제외된 `.artifacts/dev-monitoring/`에 보관한다. Secret·Webhook 값·앱 환경변수·사용자 로그 본문은 수집하지 않는다.

### 저장소에서 확인한 사항

- 현재 작업 브랜치는 `feat/v1-central-cd-prep`. 기존 README 수정과 관측 검토 문서 등 사용자 작업이 있다.
- 확인한 로컬 `origin/main`은 `92adfbc`(2026-10-15). 원격 최신 상태 확인 전까지 최신 코드라고 간주하지 않는다.
- `monitoring/prometheus/targets/application.json`은 운영 `app-host`의 BE 8081, AI 9464만 등록한다.
- 현재 Prometheus 외부 라벨은 production/keepgo-v1로 고정돼 있다. 외부 라벨만으로 로컬 조회 데이터의 환경 분리를 대신하지 않는다.
- recording rule과 앱 알림은 여러 곳에서 `service`만으로 집계한다. 개발 수집 전에 환경·클러스터 경계를 유지하도록 수정해야 한다.
- Grafana 알림 그룹에는 환경 구분이 없다. 개발 알림이 운영 알림과 같은 그룹으로 묶이지 않도록 수정해야 한다.
- V2 Terraform의 포트 정의와 실제 앱 listener는 별개다. SSM 점검 결과 BE는 응답하지만 AI는 메트릭 listener가 없다.

## 3. 작업 순서와 통과 기준

| 단계 | 작업 | 완료 기준 | 상태 |
| --- | --- | --- | --- |
| 1 | 실제 네트워크·서비스·모니터링 서버 상태 확인 | VPC 경로, task IP/포트, 메트릭 응답, 서버 여유 확인 | 1차 점검 완료. AI 계측 부재 발견 |
| 2 | 연결 방식 결정 및 AI 변경안 작성 | 필요한 네트워크·IAM·앱 변경과 영향 범위 기록 | 네트워크 설명·AI 계획 작성 완료, 피어링 선택 대기 |
| 3 | 수집·환경 분리 구현 | ECS 대상 자동 갱신, dev/prod 집계 분리, 관련 검증 통과 | 대기 |
| 4 | 대시보드·Discord 구성 | 환경 선택, `[DEV]` 표시, 환경별 알림 그룹 분리 | 대기 |
| 5 | 적용 및 인수 | 운영 수집 유지, 개발 수집 성공, task 교체 추적, 장애·복구 수신 | 대기 |

## 4. 구현 제안 — 아직 적용되지 않음

- 모니터링 EC2에서 ECS API로 대상 서비스의 실행 task를 조회하고 Prometheus `file_sd` 파일을 갱신한다. 조회 권한은 필요한 범위로 제한한다.
- 갱신 파일은 원자적으로 교체한다. 조회 실패를 정상적인 task 0개로 해석하지 않는다. 갱신 프로세스 실패·지연도 감지한다.
- 수집 시 `environment`, `cluster`, `service`를 부여한다. recording rule·대시보드·알림에도 동일한 경계를 유지한다.
- `up == 0` 외에 서비스의 수집 대상 자체가 사라진 상태를 감지한다. 예상 대상은 사용자가 확정한 BE·AI로 제한한다.
- 실제로 존재하는 기본 지표부터 표시한다. 계약에 없는 앱 지표를 존재한다고 가정하거나 미계측 상태를 정상값 0으로 표시하지 않는다.
- 기존 Discord contact point를 재사용한다. 개발 알림 제목에 `[DEV]`를 넣고 그룹에 environment/cluster를 포함한다.
- 적용 전에 모니터링 서버의 현재 설정과 자원 사용량을 확인하고 복구할 이전 설정을 보관한다.

## 5. 결정 또는 추가 확인이 필요한 사항

- **사용자 답변 대기: VPC 피어링을 이용한 사설 직접 수집 vs 개발 수집기의 외부 전송.** 현재 기존 경로는 없다. 추천안은 기존 Prometheus pull 구조를 유지하는 피어링이다.
  - 피어링 1개. 모니터링 EC2가 사용하는 운영 main route table에서 개발 app 서브넷 2개로 경로 추가.
  - 개발 app route table에 모니터링 EC2 사설 주소 `/32`로 복귀 경로 추가. VPC 전체에 대한 포괄 경로는 필요하지 않다.
  - 모니터링 → 개발 BE 8081, AI 9464만 허용. DB·Redis·앱 API 포트는 이번 연결 대상이 아니다.
  - 운영 main route table은 다른 운영 자원도 공유하므로 영향을 문서화한다. 보안 그룹은 실제 모니터링 서버로 출발지를 제한한다.
  - 기존 CloudFormation/Terraform 관리 자원의 소유권을 확인해 수동 변경이 다음 배포에서 사라지지 않는 방식으로 관리한다.
  - 대안은 개발 측 수집기와 인증된 수신 경로를 추가하는 방식이다. 중앙 수신 설정·인증·개발 수집기 운영 범위가 늘어나므로 설계 확인 후 별도 결정한다.
  - 근거: AWS는 [특정 서브넷 또는 단일 IP 경로](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-routing.html)와 [동일 리전 피어 VPC의 SG 참조](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-security-groups.html)를 지원한다.
- 개발 알림의 범위와 지속 시간: 수집 단절·대상 소실·확인된 앱 오류 신호를 기준으로 구체안을 제시한다.
- AI 수정 계획은 사용자 요청에 따라 에이전트가 작성했다(8절). 구현·PR 생성·병합·배포는 아직 수행하지 않았다.
- 기존 운영 모니터링 설정과 저장소의 차이는 배포 전 비교한다.

## 6. 검증·포트폴리오 증거

완료 전에는 성과로 표시하지 않는다. 측정 시각·실행 버전·방법·한계를 함께 기록한다.

- 연결 전후 구성과 재사용 판단: 모니터링 서버 CPU·메모리·디스크 변화.
- 환경 분리: 개발 요청 또는 오류가 운영 집계에 포함되지 않는 조회 결과.
- ECS 배포 대응: 교체 전후 task와 수집 대상, 자동 갱신 시간, 수집 공백.
- 알림: `[DEV]` 발생·복구 수신, 운영 알림과 그룹 분리, 대상 0개 감지.
- 산출물: 설정 변경 PR, 구성도, 환경별 화면, 검증 기록, 운영·복구 절차.

## 7. 변경 이력

- 2026-10-19: 작업 문서 생성. AWS 인증과 EC2·ECS 목록 조회. BE·AI 범위 및 기존 Discord `[DEV]` 방침 확정. 서버·네트워크·알림 설정 변경 없음.
- 2026-10-19: VPC·라우팅·SG·ECS task 조회 및 SSM 호스트 점검 완료. VPC 간 경로 부재와 개발 AI 계측 부재 확인. 네트워크 방식·AI 변경 담당을 질문함. 운영 메트릭 수집 상태 및 자원 기준값 기록.
- 2026-10-19: GitHub API로 최신 AI main/develop 소스를 조회해 수정 계획 작성. 운영 계측의 개발 브랜치 누락, 새 삭제 API, 상세 422 응답, HTTP 200 업무 실패 경로를 확인. 네트워크 설명과 변경 범위를 9절에 보완.
- 2026-10-19: 사용자가 비용·보안·대안 비교를 요청함. AWS 공식 요금과 AZ를 확인해 10절 추가. 피어링 선택은 계속 미확정이며 조회·문서 갱신만 수행.

## 8. AI 최소 수정 계획

### 기준과 차이

2026-10-19 GitHub에서 직접 확인한 기준이다. 구현 착수 전 develop head 변경 여부를 다시 확인한다.

- 운영 브랜치 [main@6e9c5cf](https://github.com/100-hours-a-week/KTB4-8th-AI/tree/6e9c5cf7b2993238b613804fb1a6fdd7bf04657b): `app/core/metrics.py`, `tests/test_metrics.py`, prometheus-client 의존성, METRICS_PORT 설정, lifespan 연동이 있다.
- 개발 브랜치 [develop@d60552f](https://github.com/100-hours-a-week/KTB4-8th-AI/tree/d60552fb4bde5bcb77881eeab5b018b464c3fc8d): 위 계측이 없다. 실행 컨테이너 점검에서도 라이브러리와 listener가 없었다. 브랜치 head와 실행 이미지 SHA가 동일한지는 별도 확인 사항이다.
- develop에는 `/v1/embed-places/delete`가 추가됐다. 운영 route 분류 테스트를 그대로 복사하면 빠진 경로 때문에 실패한다.
- develop의 422 응답은 오류 필드·사유를 제공한다. 운영 main.py 전체 복사는 이 동작을 되돌리므로 필요한 import/lifespan/middleware 연결만 반영한다.
- develop의 `/v1/recommend-courses`는 `recommend_failed`도 HTTP 200으로 반환한다. HTTP 오류율과 업무 성공률은 다르다.

### 변경 파일과 순서

| 순서 | 파일 | 변경 계획 |
| --- | --- | --- |
| 1 | `pyproject.toml`, `uv.lock` | prometheus-client 추가. 개발 lock을 기준으로 해당 의존성 변경만 반영하고 불필요한 전체 업그레이드를 피한다 |
| 2 | `app/core/metrics.py` | 운영 구현을 출발점으로 요청 수·응답 시간 histogram·capability 지표를 이식한다. 기존 Cloud 계약의 이름과 bucket을 유지한다 |
| 3 | `app/core/config.py` | METRICS_PORT 추가. 컨테이너 기본 9464, 테스트에서 0으로 비활성화할 수 있도록 한다 |
| 4 | `app/main.py` | 기존 오류 처리와 LangSmith/Sentry 초기화를 유지하면서 lifespan에서 메트릭 서버 시작·정리, ASGI middleware 연결 |
| 5 | `Dockerfile` | API 8000에 더해 metrics 9464를 EXPOSE로 문서화. 실제 listener와 접근 제어는 앱·ECS·SG가 담당 |
| 6 | `tests/test_metrics.py` | 운영 테스트를 개발 API에 맞춰 이식하고 새 삭제 API 분류, 상세 422 응답 보존, 중복 계측·민감 label 방지 등을 검증 |
| 7 | `.github/workflows/ci.yml` | 현재 pytest 실행이 주석 처리돼 있으므로 외부 API 호출이 없는 계측 테스트를 실제 실행하는 좁은 검증 단계 추가. CI 성공을 테스트 성공으로 오인하지 않게 한다 |

route label은 실제 URL/ID 대신 라우터 템플릿을 사용한다. `/health`는 요청량에서 제외한다. 기존 생성 API는 generation, 취소·임베딩·새 삭제 API는 interactive로 분류하는 초안이며 실제 지연 특성을 나중에 측정한다. 404는 unmatched로 모은다.

초기 수집은 HTTP 요청량, 상태 코드, 응답 지연, 기본 Python/process 지표, `keepgo_observability_info{contract="1",capability="http"}`다. 제공자 호출별 실패·재시도·토큰·비용·TTFT 지표는 이번 기본 연결로 제공되지 않는다. Grafana AI 상세 패널에서 미제공 항목은 정상값으로 채우지 않는다.

### 구현 시 확인할 경계와 테스트

- 현재 단일 uvicorn worker 전제를 실행 설정까지 확인한다. 멀티 worker가 필요하면 registry/수집 구조를 별도 설계한다.
- 서버 생명주기는 lifespan에서 관리하고 종료 시 shutdown과 socket 정리를 보장한다. 재시작·반복 테스트에서 포트 점유가 남지 않아야 한다.
- **실패 정책 제안, 미확정:** 선택 계측의 listener 초기화 실패는 명시적으로 로그를 남기고 앱 서비스는 유지하며, 중앙 수집 단절 알림으로 감지한다. 설정 오류와 일반 코드 버그를 무분별하게 삼키지 않는다. 구현 전에 사용자에게 정책을 설명한다.
- 정상 요청·검증 실패 422·예상하지 못한 500 각각 정확히 1회 기록, histogram count와 요청 수의 관계 확인.
- 여러 request_id 요청이 동일 템플릿으로 집계되는지, health가 제외되는지, 포트 9464의 Prometheus 형식 응답과 실제 capability 확인.
- monkeypatch/가짜 응답으로 LLM·지도 API·실제 데이터 변경 없이 검증한다. 422 응답의 `data.errors`와 기존 업무 응답도 보존한다.
- HTTP 200으로 반환되는 `recommend_failed`는 HTTP 성공 상태로 집계되는 것을 명시적으로 검증한다. 이를 업무 성공률이라고 표시하지 않는다.
- 새 업무 실패 지표는 다음 관측 확장 후보로 기록한다. 기존 HTTP 응답 계약을 모니터링 편의를 위해 변경하지 않는다.

### 반영 순서와 완료 기준

1. 최신 develop 기반 격리 작업 공간에서 계측 변경을 준비하고 테스트·컨테이너 기동을 검증한다.
2. AI develop 대상 PR에 변경 파일·계측 범위·검증 결과·HTTP 200 한계를 기록한다.
3. 병합 이후 기존 개발 CI/CD로 생성된 이미지와 실제 실행 digest를 확인한다. 자동 CD가 있으므로 병합이 배포로 이어질 수 있음을 변경안에 명시한다.
4. 앱 내부 9464 응답 → 모니터링 EC2에서 접근 → Prometheus target up → 개발 대시보드 표시 순서로 검증한다.
5. 메트릭 계약 검증이 끝난 AI만 수집 계약 타깃으로 활성화한다. BE 준비 완료와 AI 계측 준비 상태는 별도로 추적한다.

이 절은 계획이며 앱 코드 수정·테스트 실행·PR 생성 결과가 아니다.

## 9. 네트워크 설명 및 추천안의 구체 범위

현재 Prometheus는 운영 VPC `172.31.0.0/16`의 모니터링 EC2에 있고, 개발 BE·AI task는 개발 VPC `10.20.0.0/16`의 사설 주소를 쓴다. Grafana가 앱을 직접 조회하는 구조가 아니라 Prometheus가 앱의 메트릭 HTTP endpoint를 주기적으로 조회하고 Grafana가 그 결과를 읽는 구조다.

현재 빠진 것은 **두 네트워크 사이의 경로**와 **개발 메트릭 포트 접근 허용**이다. 피어링은 두 VPC 간 사설 IP 통신 경로를 만들고, route table은 그 경로로 보낼 목적지를 지정하며, SG는 실제로 허용할 출발지·목적지·포트를 제한한다. 세 부분이 함께 맞아야 수집된다.

| 구성 | 제안 |
| --- | --- |
| 피어링 | 동일 계정·서울 리전의 현재 두 VPC 사이 연결 1개 |
| 모니터링 측 route | 운영 main `rtb-0b0f52fba7c41ca82`에서 개발 app `10.20.10.0/24`, `10.20.11.0/24`로 피어링 경로. describe-subnets로 CIDR 확인 완료 |
| 개발 측 route | app `rtb-05fb8bcbd1b458f6f`에서 모니터링 `172.31.34.195/32`로 피어링 경로 |
| BE 접근 | 모니터링 SG → 개발 BE SG TCP 8081 |
| AI 접근 | 모니터링 SG → 개발 AI SG TCP 9464 |
| 주소 변경 대응 | ECS task IP는 자동 discovery로 갱신. 모니터링 EC2 교체로 사설 IP가 달라지면 `/32` 경로도 IaC로 함께 갱신 |

피어링 자체는 메트릭 전용 단방향 연결이 아니다. 응답이 돌아올 왕복 경로가 필요하고 실제 접근 경계는 SG·NACL까지 포함해 검증한다. 현재 모니터링의 443은 이미 전체 IPv4에 공개돼 있으므로 이 기존 규칙도 함께 고려한다. 개발 → 운영 앱/DB 전체 접근을 허용하는 경로를 추가하는 계획은 아니다.

추천 이유는 기존 Prometheus 직접 수집 방식을 유지하면서 별도의 개발 수집기·중앙 수신 인증을 추가할 필요가 없기 때문이다. VPC 분리 정책상 사설 연결 자체를 허용하지 않는다면 개발 측 수집기에서 인증된 중앙 수신점으로 전송하는 대안을 설계한다.

변경은 기존 CloudFormation/Terraform 원본과 실제 관리 범위를 대조한 뒤 관리 주체별로 반영한다. 수동 SG 규칙을 임시 추가한 상태로 완료하지 않는다. 운영 main route table 공유 영향, NACL, 대상 SG에 부착된 자원 범위, 기존 연결 유지 여부를 검증 항목에 포함한다. 복구는 새 수집 대상 중지 후 이번에 추가한 규칙·경로·피어링만 역순으로 회수한다.

참고: [AWS 양방향 route 설정](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-routing.html), [AWS 피어 VPC의 SG 참조](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-security-groups.html). 비용 조건과 예시는 10절에 기록했다. 실제 월 청구액은 적용 후 수집량으로 검증한다.

## 10. 비용·보안·대안 비교 — 결정 전 검토

### 비용: 현재 배치와 확장 시 차이

2026-10-19 AWS describe-subnets 결과:

| 대상 | CIDR | AZ | AZ ID |
| --- | --- | --- | --- |
| 모니터링 EC2 서브넷 | 172.31.32.0/20 | ap-northeast-2c | apne2-az3 |
| 현재 BE·AI task가 있는 개발 app 서브넷 | 10.20.11.0/24 | ap-northeast-2c | apne2-az3 |
| ECS 서비스의 다른 배치 가능 app 서브넷 | 10.20.10.0/24 | ap-northeast-2a | apne2-az1 |

피어링 연결 생성 비용은 없으며 같은 AZ 내 피어링 전송은 무료다. 따라서 앞서 확인한 task 배치가 유지되면 BE·AI → 모니터링 수집 경로의 피어링 전송료는 0이다. 이는 기존 EC2/EBS 비용이나 다른 통신 비용이 없어짐을 뜻하지 않는다. [AWS 피어링 과금 조건](https://docs.aws.amazon.com/vpc/latest/peering/what-is-vpc-peering.html)

같은 리전의 다른 AZ를 건너는 피어링 트래픽은 송신·수신 각각 USD 0.01/GB다. 같은 계정의 두 EC2 측 비용을 합치면 AZ를 건넌 요청·응답 데이터 합계 GB × USD 0.02로 계산할 수 있다. 10GB면 약 USD 0.20, 100GB면 약 USD 2.00의 전송료 예시다. 이 GB는 요청과 응답을 합산하되 송수신 양끝에서 동일 바이트를 중복 합산하지 않은 값이다. 실측 사용량, 세금, 할인은 반영하지 않았다. [AWS VPC 요금](https://aws.amazon.com/vpc/pricing/)

- ECS task 교체·확장으로 2a에 배치되면 해당 task의 수집 트래픽에 AZ 간 요금이 발생한다. 소액 전송료 절약만을 위해 ECS 배치·가용성을 2c로 제한하지 않는다.
- 제안된 피어링 메트릭 경로는 NAT Gateway를 통과하지 않는다. 기존 NAT의 다른 용도와 비용은 유지된다.
- 추가 EC2/NLB/NAT는 이 피어링 안에 필요하지 않다. 수집량 증가로 기존 Prometheus의 CPU·메모리·디스크 또는 EBS 용량을 늘려야 하는지는 별도 검증한다.
- 현재 데이터 보존량 한도도 운영·개발이 공유한다. 개발 시계열이 늘면 메모리 사용량과 운영 데이터의 실질 보존 기간에 영향을 줄 수 있다.

### 보안: 얻는 것과 받아들이는 위험

피어링의 장점은 앱 메트릭 포트에 공인 노출을 추가하지 않고 사설 IP로 수집할 수 있다는 점이다. 같은 리전의 피어 SG를 참조해 모니터링 SG에서 오는 트래픽만 허용할 수 있다. [AWS 피어 SG 참조](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-security-groups.html)

다만 다음 경계는 명확히 한다.

1. VPC 간 연결이 추가되므로 완전한 네트워크 분리는 아니다. 운영 main route table은 공유되며, 최종 접근 허용은 SG·NACL 검증까지 포함한다. SG 소속 자원을 이후 늘리면 접근 주체도 늘어날 수 있다.
2. 모니터링 EC2가 운영·개발 양쪽의 신뢰 대상이 된다. 해당 서버가 침해되면 허용된 양쪽 관리 포트가 공격 경로가 될 수 있다. Grafana 공개 접속·권한과 호스트 패치도 계속 관리해야 한다.
3. 기존 모니터링 443 수신은 전체 IPv4에 허용돼 있다. 개발 측 `/32` 경로가 생기면 이 기존 규칙에 따른 사설 주소 접근도 가능하다. '개발에서 모니터링으로 어떤 신규 연결도 불가능하다'고 표현하지 않는다.
4. SG는 포트를 제한하며 URL 경로를 제한하지 않는다. BE 8081 허용은 해당 포트에 노출된 관리 endpoint 범위에 적용된다. `/actuator/prometheus`만 허용해야 한다면 애플리케이션 접근 제어나 프록시 등 추가 설계가 필요하다.
5. 현재 메트릭 endpoint는 HTTP다. 사설 경로를 만든다고 앱 계층 TLS·클라이언트 인증이 생기는 것은 아니다. 전송 암호화와 상호 인증을 명시적으로 요구하는 경우 TLS/mTLS와 인증서 관리 범위를 추가한다.
6. dev/prod 라벨은 조회·집계 구분이다. 단일 Prometheus의 데이터 접근 권한, 자원, 장애를 격리하는 보안 경계가 아니다. 개발 지표 폭증이 운영 관측을 방해할 수 있으므로 표본·label·응답 크기 한도, 보존량, scrape 실패를 관리한다. [Prometheus 보안 모델](https://prometheus.io/docs/operating/security/)

VPC 피어링은 전이 라우팅을 제공하지 않는다. VPC가 많아지면 연결·경로 관리가 복잡해질 수 있으므로 중앙 네트워크 설계는 별도 검토한다. [AWS Peering/TGW 비교](https://docs.aws.amazon.com/prescriptive-guidance/latest/secure-outbound-network-traffic/vpc-region-communication.html)

### 대안 비교

아래 적합성은 현재 VPC 2개·BE/AI·기존 Grafana 재사용 요구에 대한 판단이다. 모든 대안의 총 월비용을 산정한 결과는 아니다.

| 방식 | 비용 구조 | 보안·운영 트레이드오프 | 현재 적합성 |
| --- | --- | --- | --- |
| 제한된 VPC 피어링 + 기존 Prometheus pull | 추가 네트워크 장비 고정비 없음. AZ 간 전송 및 기존 호스트 자원 증가분 | 사설 수집, 대상마다 직접 scrape 가능. VPC 간 경로와 공유 모니터링 신뢰 범위가 늘어남 | 앱 메트릭까지 기존 구조로 연결할 때 우선안 |
| 기존 Grafana에 CloudWatch datasource 연결 | AWS API 조회·로그 검색과 기존 수집 서비스 요금. 신규 custom metrics/Container Insights 확대 비용은 별도 | VPC 간 사설 경로 없이 IAM으로 조회. 이미 CloudWatch에 있는 데이터만 보임 | ECS CPU·메모리·로그부터 빠르게 보는 대안. HTTP/JVM/AI 계약 전체의 대체가 아님 |
| 개발 수집기 → HTTPS remote_write 수신점 | 수집기 CPU/RAM, 기존 NAT의 추가 처리량·전송, 수신점 운영 | VPC 간 사설 경로 불필요. 수신 인증/TLS·전송 큐·재시도·환경별 쓰기 권한 관리 필요 | 네트워크 분리 정책을 유지하면서 앱 메트릭을 모을 때 대안 |
| PrivateLink의 NLB 기반 서비스 연결 | interface endpoint의 AZ별 시간·처리량 요금 + NLB·수집기/수신 서비스 비용 | 특정 서비스 연결로 범위를 좁힐 수 있지만 구성 요소 증가. 앱별 모든 task 수집은 별도 설계 | 여러 계정 또는 엄격한 서비스 경계가 필요할 때 검토 |
| Transit Gateway | VPC attachment 시간 요금 + 처리량·해당 전송 요금 | 다수 VPC의 중앙 라우팅·분리 관리에 유리. 두 VPC의 메트릭 연결만으로는 복잡도·고정비 증가 | 현재 범위에는 우선순위 낮음 |

대안 근거:

- [Grafana CloudWatch 설정](https://grafana.com/docs/grafana/latest/datasources/aws-cloudwatch/configure/), [CloudWatch 요금](https://aws.amazon.com/cloudwatch/pricing/): IAM 기반 metrics/logs 조회를 지원한다. 이미 저장된 데이터 재조회도 API/검색 사용량 과금 여부를 확인해야 한다.
- [Prometheus remote storage](https://prometheus.io/docs/prometheus/latest/storage/): 기존 Prometheus에 remote_write 수신 기능이 있다고 해서 다중 환경의 안전한 수신 서비스가 완성되는 것은 아니다. 중앙에서 환경/tenant를 검증하고 유입량을 제한해야 한다. 엄격한 격리는 개발 저장소/receiver 분리도 고려한다.
- [PrivateLink 서비스 공유](https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-share-your-services.html), [PrivateLink 요금](https://aws.amazon.com/privatelink/pricing/): 표의 방식은 NLB 기반 endpoint service다. 단순히 NLB 뒤 여러 task의 `/metrics`를 번갈아 조회하면 task별 counter를 올바르게 수집할 수 없다. 개발에서 각 task를 수집하고 중앙 수신 서비스를 PrivateLink로 제공하는 등의 구성이 필요하다. Resource endpoint 등 다른 PrivateLink 방식은 이번 상세 설계 대상이 아니다.
- [Transit Gateway 요금](https://aws.amazon.com/transit-gateway/pricing/): 서울 단가를 따로 검증하지 않았으므로 다른 리전의 예시 금액을 서울 월 견적으로 제시하지 않는다.

### 현재 권고와 다음 결정

- HTTP·JVM·AI 앱 지표까지 기존 Prometheus에 연결하려면 제한된 피어링을 우선 권고한다. 이유는 현재 같은 AZ 배치와 추가 수집기 없는 구성이며, 보안 격리보다 비용·단순성을 우선한다는 트레이드오프를 명시한다.
- 당장 ECS 자원 상태·로그를 한 화면에서 보고 VPC 간 경로는 보류하려면 CloudWatch datasource 연결을 먼저 할 수 있다. 이는 사용자가 요청한 앱 메트릭 연결의 단계적 대안이며 동일한 완료 범위는 아니다.
- 운영·개발 VPC 사이에 사설 경로를 두지 않는 것이 우선이면 개발 수집기 + 인증된 HTTPS 전송을 선택한다. 공용 단일 수신기를 열어두는 것만으로 보안 격리가 달성되지는 않는다.
- 더 엄격한 환경 격리 또는 관측량 확대 시에는 별도 관측 VPC·환경별 저장소·관리형 저장소를 검토한다. 이번에 모니터링 서버를 옮기는 작업은 포함하지 않는다.
- 네트워크 선택은 아직 미확정이다. 사용자의 비용/격리/운영 복잡도 우선순위를 확인한 뒤 구현한다.

## 11. 2026-10-20 실제 적용 결과

사용자가 기존 구성으로 실제 연결을 승인했으며, 이후 “마저 진행해”로 재확인했다. 현재 V1 인프라는 운영, V2는 개발이고 향후 역할을 전환할 예정이다. 버전과 환경 라벨을 같은 의미로 취급하지 않는다.

| 항목 | 결과 |
| --- | --- |
| AI 계측 | main에서 metrics 모듈·테스트·의존성을 선별 이식. develop의 상세 422·삭제 API 보존, develop에 없는 verify-place 경로는 분류에서 제외 |
| AI PR | [#49](https://github.com/100-hours-a-week/KTB4-8th-AI/pull/49), 테스트·컨테이너 빌드 통과 후 병합. develop commit `54cc4581f40af9d3b936447644c880ec4e63df3d` |
| AI 배포 | ECS `keepgo-v2-ai-api:6`, running=1, rollout COMPLETED |
| 네트워크 | `keepgo-dev-monitoring` CloudFormation CREATE_COMPLETE, Peering `pcx-05cde5410c13d5275` active |
| 기존 호스트 | `keepgo-v1-monitoring-host` UPDATE_COMPLETE. change set은 SG egress만 Modify, EC2·기존 경보 교체/변경 없음 |
| 메트릭 접근 | 모니터링 EC2→BE `10.20.10.81:8081`, AI `10.20.10.115:9464` 모두 200 |
| 수집 | 운영 기존 9개 + 개발 2개 = 11개 모두 up, scrape 오류 없음 |
| 환경 분리 | 개발 `application-dev` job, `keepgo_dev:*` 집계, development/keepgo-v2 라벨. 기존 운영 집계는 유지 |
| 자동 발견 | systemd timer active, 30초마다 ECS 조회. 파일 mtime 갱신과 실제 최신 task IP 등록 확인 |
| 대시보드 | `[DEV] KeepGo - Application HTTP`, `[DEV] KeepGo - Backend JVM and DB Pool` 등록 |
| 변경 PR | [Cloud #112](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/pull/112), 전체 CI 통과. 10월 21일 문서를 제외한 19개 파일로 정리했으며 사용자 결정으로 main 병합 보류 |
| Discord | `[DEV]` 시험 경보 12:09:40 UTC, 복구 12:14:40 UTC 수신점 전송 성공 확인. 임시 시험 규칙 삭제·설정 검증·reload 완료 |

AI는 배포 중 2c에서 2a로 이동했다. 최종 점검의 BE·AI 둘 다 모니터링 EC2와 다른 AZ다. 순간 메트릭 응답 본문은 BE 32,142 bytes, AI 2,348 bytes로, 이 크기가 30초 간격·30일 유지된다는 가정에서 본문 전송료는 합계 약 **$0.06/월**이다. 요청·프로토콜 overhead, 지표 증가, task 수 변화는 별도이며 청구 실측값이 아니다. 배치가 변경될 수 있으므로 “영구 무료”라고 표현하지 않는다.

호스트는 적용 후 가용 메모리 약 995~1,015MiB, Prometheus 약 86~87MiB, Grafana 약 347~355MiB였다. 순간값이며 장기 용량 보장은 아니다.

적용 방법은 Git push가 아니라 CloudFormation change set 실행과 SSM 설정 배치다. 기존 파일은 `/opt/keepgo/dev-monitoring-backup-20261020`에 보관하고 Prometheus SIGHUP·Grafana provisioning reload를 사용했다. TSDB/Grafana volume과 운영 앱은 교체하지 않았다.

재현 가능한 스택 명령, 파일 배치 절차, 롤백, V1/V2 역할 전환 체크는 [실행 runbook](dev-monitoring-runbook.md)에 있다. 이 문서는 통합 작업 브랜치에서 보존하며 main PR에는 포함하지 않는다. 실제 ECS task 교체 중의 연속 수집 공백 시험은 아직 수행하지 않았으며, 주소 교체/0개/조회 실패 처리는 단위 테스트와 현재 task 발견으로 검증했다.

## 12. 2026-10-21 개발 로그 사용성과 비용 후속 정리

사용자가 개발팀의 로그 접근, 실시간 조회 가능 여부, 피어링 비용의 비교 기록을 요청했다. 상세 산식·공식 근거·사용량별 표는 [모니터링 선택 검토](observability-selection-review.md)의 **15절**에 모았다.

| 항목 | 확인·권고 |
| --- | --- |
| 현재 로그 | CloudWatch 서울 `/keepgo/v2/backend`, `/keepgo/v2/ai-api`, 각각 30일 보존 |
| 현재 Grafana | Prometheus만 연결됨. 로그 본문 조회는 아직 미구성 |
| 과거 로그 검색 개선 | Grafana + CloudWatch datasource 제안. 그룹 전체 검색으로 task별 스트림 선택을 줄임 |
| 실시간 확인 | CloudWatch Live Tail. 권한 확인 필요, 새 로그 유입 지연·고부하 샘플링 가능 |
| 조회 비용 | 기존 Logs Insights 서울 $0.0076/스캔 GB. 자동 갱신과 여러 조회자의 실행 수를 합산 |
| Live Tail 비용 | 월 1,800분 무료 구간 이후 $0.01/세션 분. 개인별 무료 구간으로 계산하지 않음 |
| 피어링 | 메트릭 수집의 응답 본문 기준 약 $0.06/월 추정. 로그 조회료·기존 EC2 비용 제외 |
| 트래픽 구분 | Grafana의 CloudWatch 조회와 Live Tail은 이번 개발 VPC 피어링이 필요하지 않음 |
| 팀 사용 방식 | 평소 그룹 단위 검색, 다음 단계로 Grafana 화면 통합, 배포·재현 중 Live Tail 단기 사용 |

이번 갱신은 문서화다. Grafana 로그 datasource·조회 IAM·자동 새로고침·보존 변경은 적용하지 않았다. Cloud PR #112는 10월 21일 미병합 상태를 확인했으며 사용자 결정으로 열어둔다. 코드와 문서는 통합 작업 브랜치에 보존하며 [통합 상태](branch-integration-status.md)에 main 반영 범위를 기록했다.
