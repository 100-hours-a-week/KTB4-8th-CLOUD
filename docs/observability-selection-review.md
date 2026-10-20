# KeepGo 모니터링·옵저빌리티 선택 검토

작성일: 2026-10-20 KST. 상태: **검토 문서 완성. 검토 이후 기존 구성의 개발 BE·AI 연결 적용 완료, 추가 도구 도입은 후속 검토**.

2026-10-21 갱신: **15절에 개발 로그 조회·실시간 확인·피어링 비용 비교**를 추가했다. 현재 적용 상태, 월 사용량별 산식, 개발팀 사용 동선, 추가 구성의 권한·비용을 구분한다. 로그 조회 기능 추가는 제안이며 이번 갱신은 문서 작업이다.

후속 갱신(2026-10-20): 이후 사용자가 기존 구성의 실제 연결을 승인해 기본 개발 모니터링을 적용했다. 본문의 미결정 상태는 검토 당시 기록이며, 최신 적용 결과는 [연결 작업 기록](dev-monitoring-connection.md)의 11절과 [Cloud PR #112](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/pull/112)을 따른다. OTel·관리형 전환은 여전히 후속 검토다.

실행 환경의 근거는 2026-10-19 읽기 전용 점검이며, 가격은 2026-10-20 KST에 확인했다. MAU 80만은 미래 설계 시나리오다. 실제 이용자 수·실제 관측 비용·부하 검증 결과로 표현하지 않는다.

## 1. 추천과 결정 범위

**지금은 기존 Prometheus·Grafana EC2에 개발 BE·AI를 연결하고, CloudWatch 로그·AWS 지표와 요청 식별자를 연결하는 방식을 추천한다. 이후 분산 추적은 OpenTelemetry로 핵심 경로 하나를 계측하고 AWS 관리형 저장소에서 먼저 검증한다.**

이 선택의 이유는 기존 자산을 재사용하면서 개발팀이 실제로 겪는 요청 추적·배포 후 장애 확인의 공백을 먼저 메울 수 있기 때문이다. 팀 인원이 함께 늘어나지 않는 V2 설계에서는 새로운 저장소 여러 개를 직접 운영하는 부담도 비용에 포함해야 한다. 단일 모니터링 EC2를 MAU 80만 운영의 최종 구조로 확정하는 것은 별개다.

| 구분 | 내용 | 상태 |
| --- | --- | --- |
| 사용자 확정 | 기존 모니터링 EC2 재사용, 개발 BE·AI 우선, 기존 Discord 채널에 `[DEV]` 구분 | 확정 |
| 사용자 요청 | AI 수정 계획, 네트워크·비용·보안·대안 비교, 결정 기록 작성 | 본 문서와 연결 계획에서 작성 |
| 이번 추천 | 제한된 VPC Peering을 통한 직접 수집, 환경 분리, CloudWatch 연결, 공통 관측 계약 | 제안. 네트워크 선택은 미확정 |
| 다음 추천 | OTel → Collector → CloudWatch OTLP/Transaction Search의 제한된 추적 PoC | 제안. 유료 도입·계정 설정 변경 미승인 |
| 조건부 전환 | Prometheus 관리 부담이 커지면 AMP 또는 Grafana Cloud 비교 후 저장소 이전 | 측정·예산 확인 후 결정 |
| 보류 | Loki·Tempo·Elasticsearch 동시 자체 운영, 모든 요청·프롬프트 무제한 저장 | 현재 요구 대비 운영 부담이 큼 |

기존 [옵저빌리티 도입 검토](observability-adoption-review.md)는 관측 계약과 기능별 개선을 설명한다. 본 문서는 **도구 선택 이유, 현재와의 차이, 비용, ECS 구조에 따른 판단 기준**을 보완한다. 상세 연결 작업은 [개발 모니터링 연결 기록](dev-monitoring-connection.md)을 따른다.

## 2. 팀 상황과 근거의 확실성

### 확인된 상황

- 전용 모니터링 EC2에서 Prometheus·Grafana·Blackbox exporter를 운영하고 있다.
- 운영 V1은 EC2/Compose, 개발 V2는 ECS on EC2다. 현재 개발 BE·AI·FE가 실행 중이지만 첫 연결 범위는 BE·AI다.
- 기존 기록에 CloudWatch Logs, AI Sentry, LangSmith 연동이 있다. 각각의 최신 이용 요금제·좌석·실제 수집량·마스킹 상태는 재확인하지 않았다.
- 개발 BE의 `/actuator/prometheus`는 task 내부에서 응답한다. 개발 AI는 앱 8000 포트만 열려 있고 9464 메트릭 listener와 관련 패키지가 없다.
- 운영·개발 VPC 사이에 통신 경로가 없다. 포트가 Task Definition에 존재하는 것만으로 계측과 통신이 완성되지는 않는다.
- [V2 설계](<V2 설계.md>)는 인원·비용 여력이 크게 늘지 않는 상황에서 ECS/ASG와 자동화를 선택한다.

### 아직 검증되지 않은 가정

| 항목 | 문서에서 쓰는 가정 | 결정에 미치는 영향 |
| --- | --- | --- |
| 개발팀 우선순위 | 배포 후 이상 탐지, BE→AI 원인 추적, AI 실패·비용 확인이 우선 | 실제 가장 오래 걸리는 조사 사례로 순서를 조정 |
| 운영 인력 | 별도 관측 플랫폼 전담자를 두기 어렵다고 가정 | 자체 저장소 증설보다 관리형을 우선 검토 |
| 예산 | 월 허용액·개발/운영 배분 미정 | 절대 금액의 최종 구매 결정은 하지 않음 |
| 장애 대응 | 24시간 당직·응답시간 약속 미정 | `[DEV]` 알림을 운영 긴급 호출과 동일 취급하지 않음 |
| 도구 사용 | AWS·기존 Grafana 활용이 신규 플랫폼 학습보다 유리하다고 가정 | 실제 팀 사용성 시험으로 검증 |
| MAU 80만 | 요구 용량 산정을 위한 가정 | 현재 비용이나 수용 가능 규모로 인용하지 않음 |

팀의 정확한 인원수, 개인별 숙련도, 합의된 SLO는 확인되지 않았다. 비교 점수를 임의로 부여해 객관적인 순위처럼 제시하지 않는다.

## 3. 지금 구성과 달라지는 점

| 영역 | 현재 확인된 구성 | 1차 연결·정리 후 제안 | 규모 확장 시 추가 검토 |
| --- | --- | --- | --- |
| 수집 대상 | 기존 운영 대상 9개 scrape up. 개발 미연결 | 운영 유지 + 개발 BE·AI 등록 | SSE·Worker·RDS·Redis·SQS 관측 확대 |
| BE | 개발 task 내부 메트릭 응답, 고유 이름 151개 | 메트릭 코드보다 네트워크·발견·라벨·대시보드 연결 중심 | 업무 SLI·분산 추적 보강 |
| AI | 개발 이미지에 Prometheus 계측 없음 | 기존 main 계측을 선별 이식하고 실제 listener·테스트 추가 | 업무 결과·제공자 지연·토큰·비동기 추적 |
| 네트워크 | VPC 분리, 상호 경로 없음 | 선택 승인 시 제한된 Peering 경로·SG 추가 | 환경별 collector의 outbound 전송 또는 관측 전용 VPC |
| ECS 대상 발견 | 현재 수집 파일은 운영 호스트 중심 | 실행 task IP/포트를 자동 갱신하고 종료 task 제거 | 여러 AZ·다수 task·배포 중 교체 검증 |
| 환경 구분 | 운영 target에 environment 없음. 일부 규칙은 service만 집계 | 실제 시계열에 environment/cluster 부여, 쿼리·알림 경계 유지 | dev/prod 저장소·계정 분리 필요성 판단 |
| 메트릭 보관 | 7일 및 2GB 제한, 먼저 도달한 제한 적용 | 우선 유지 후 실제 보관일·증가율 측정 | 장기 보관·가용성 필요 시 관리형 저장소 |
| 로그 | CloudWatch 사용 기록, 도구 간 연결 검증 부족 | JSON·request_id·environment·release 계약 및 Grafana 조회 연결 | 보존·검색 비용 최적화, 필요한 필드 색인 |
| 분산 추적 | BE→AI→작업 전 구간의 연결 검증 없음 | 1차 연결의 필수 범위에 포함하지 않음 | OTel 핵심 경로 PoC 후 확장 |
| AI 오류 분석 | AI Sentry·LangSmith 연동 기록 | 환경·버전·요청 ID와 오류/실행 ID 연결 | 팀 권한·요금제·품질 평가 확대 여부 결정 |
| 알림 | 운영 중심, 환경별 그룹 분리 부족 | 기존 Discord에 `[DEV]`, 환경별 그룹·복구 메시지 | 업무 SLO·운영 호출 정책·오탐 관리 |
| 모니터링 장애 | 단일 EC2 장애가 관측에 영향 | EC2 외부의 독립 생존 확인 경로 검증·보강 | 저장소·알림·collector 장애 도메인 분리 |

첫 단계에서도 **대상 주소만 추가하는 것 이상**이 필요하다. AI 계측 부재와 환경을 섞는 집계 규칙을 해결하지 않으면, 연결 후에도 데이터가 없거나 개발 장애가 운영 지표에 섞인다. 위의 미래 항목은 적용 완료 목록이 아니다.

### 기존 EC2를 우선 재사용할 수 있는 근거와 한계

10월 19일 순간 측정에서 t4g.small의 가용 메모리는 약 983~991MiB, 디스크는 20GB 중 31% 사용이었다. Prometheus 약 77~78MiB, Grafana 약 318MiB이며 두 컨테이너의 메모리 제한은 각각 512MiB다. 소규모 연결을 시험할 근거는 있으나, 장시간 조회·카디널리티 증가·대량 배포를 포함한 여유는 증명되지 않았다.

메트릭 이름 151개는 시계열 151개가 아니다. 라우트·상태·task·histogram bucket 조합으로 증가한다. 호스트 여유가 있어도 컨테이너 제한에 먼저 걸릴 수 있다. 상세 근거와 한계는 [실행 환경 점검](dev-monitoring-connection.md)에 기록돼 있다.

## 4. 개발팀이 해결해야 하는 질문과 필요한 신호

| 담당 영역 | 답해야 하는 질문 | 필요한 신호·동선 |
| --- | --- | --- |
| BE | 배포 이후 느려졌는가? DB 풀인가, AI 응답 대기인가? | route별 요청률·오류·지연, JVM/Hikari, release, BE→AI trace |
| AI | HTTP 200인데 추천이 실패했는가? 제공자 제한인가, 파싱 문제인가? | 업무 outcome, provider status, 단계별 지연, retry, 토큰, Sentry/LangSmith 링크 |
| Cloud | task 부족인가, EC2 수용량 부족인가, 배포가 막혔는가? | desired/running/pending, task 종료 이유, ASG 용량, 호스트 자원, target health |
| 비동기 처리 | 요청은 받았는데 결과가 왜 안 오는가? | job_id, queue age, 처리 시도, DLQ, 완료 결과, SSE 전달 경로 |
| FE·QA | 사용자가 겪은 오류를 어떤 요청으로 찾는가? | 화면의 안전한 request_id, 버전, 재현 조건. FE 계측 확대는 후속 범위 |
| 팀 공통 | 누구에게 알려야 하고 복구됐는가? | 환경·서비스·영향·조사 링크·담당·복구 메시지 |

예를 들어 “추천 결과가 오지 않는다”는 신고에서는 요청 ID로 BE 로그를 찾고, AI 업무 outcome을 확인한 뒤, trace로 외부 호출·큐 대기를 나누고 LangSmith 실행으로 모델 응답을 조사한다. 전 과정이 단일 화면일 필요는 없지만 ID와 시간이 이어져야 한다.

**모니터링**은 알려진 장애를 지표·조건으로 발견한다. **옵저빌리티**는 예상하지 못한 문제도 환경·버전·요청·의존 관계를 연결해 설명할 수 있게 한다. 도구를 추가해도 이 연결 계약이 없으면 조사 동선은 개선되지 않는다.

## 5. MAU 80만과 ECS on EC2가 선택에 주는 제약

### 요청 규모를 관측 데이터 규모로 바꾸기

V2 설계의 세션·요청 가정으로부터 계산한 값이다.

| 항목 | 평시 | 이벤트일 |
| --- | ---: | ---: |
| 일일 세션 | 120,000 | 480,000 |
| 세션당 BE 요청 | 8 | 8 |
| BE 요청/일 | 960,000 | 3,840,000 |
| 일평균 RPS | 11.11 | 44.44 |
| 피크 시간 평균 RPS, 반올림 | 53 | 427 |
| 순간 RPS, 반올림 | 107 | 853 |
| 순간 동시 사용자 가정 | 8,000 | 64,000 |

모든 BE 요청이 AI를 호출하지 않으며, 동시 사용자가 모두 SSE 연결을 유지하지 않는다. AI 호출 비율, Sync당 생성 job 수, 재시도율, 활성 SSE 비율은 따로 측정해야 한다. 특히 하나의 Sync가 여러 작업을 만들면 BE RPS만으로 Worker 비용·trace량을 계산할 수 없다.

메트릭 저장량은 주로 **시계열 수 × 수집 빈도 × 보존 기간**, 로그는 **이벤트 수 × 이벤트 크기**, trace는 **요청/작업 수 × span 수 × span 크기 × 수집률**에 좌우된다. MAU 하나로 “월 몇 달러”라고 결론 내리지 않는다.

### ECS on EC2에서 놓치면 안 되는 계층

| 계층 | 관측 대상 | 판단 |
| --- | --- | --- |
| 사용자·업무 | 성공률, 완료시간, 최초 결과 도착, 취소 | 서버가 정상이어도 기능 실패 가능 |
| 서비스·task | 요청 지연, 활성 요청, 메모리, task 수·재시작 | task 확장 필요성 판단 |
| EC2·ASG | 호스트 CPU/메모리/디스크, 배치 여유, 용량 확장 지연 | task를 늘려도 배치할 호스트가 없을 수 있음 |
| 관리형 의존성 | ALB, RDS, Redis, SQS, 외부 AI 제공자 | 서비스 외부 병목·할당량 식별 |
| 관측 파이프라인 | scrape 실패, 수집 지연, queue/drop, 디스크·조회 지연 | 데이터 없음과 정상 상태 구분 |

ECS Container Insights enhanced는 task·container 관측을 제공하지만, EC2 호스트의 추가 지표는 별도 CloudWatch agent 구성이 필요하다. ECS 기능을 켰다는 사실만으로 호스트 디스크·메모리 관측 완료라고 판정하지 않는다. [AWS ECS 지표 문서](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-enhanced-observability-metrics-ECS.html)

AI API는 외부 응답을 기다리는 동안 CPU가 낮아도 포화될 수 있다. Worker는 큐 길이뿐 아니라 가장 오래된 작업의 대기시간, 처리율, retry/DLQ를 봐야 한다. SSE는 일반 HTTP 응답시간과 별도로 활성 연결·최초 이벤트 지연·전송 실패·재연결을 봐야 한다.

**자동 확장 판단이 단일 Grafana/Prometheus EC2 생존에 종속되지 않게 한다.** AWS 기본 지표를 우선 사용하고, AI 활성 요청·SSE 연결·정규화한 backlog처럼 필요한 사용자 정의 지표만 확장 제어 경로에 게시한다. EC2 시작은 순간 부하보다 느릴 수 있으므로 관측과 별개로 최소 여유 용량·사전 확장 정책이 필요하다.

## 6. 도구별 역할과 선택 비교

### 기존 도구의 역할을 먼저 명확히 한다

| 도구 | 맡길 역할 | 한계·주의 | 판단 |
| --- | --- | --- | --- |
| Prometheus | 앱·런타임 시계열, PromQL, 서비스 SLI | 요청 본문·개별 오류 검색용 아님. 저장소·용량·장애 운영 책임 | 우선 유지 |
| Grafana | 지표·로그·배포 정보로 이동하는 조사 시작점 | 자체가 모든 데이터의 저장소는 아님. 데이터소스 권한·조회 비용 존재 | 우선 유지 |
| CloudWatch | ECS/ALB/RDS/SQS 등 AWS 지표와 앱 로그 | 수집·보관·검색·사용자 정의 지표 비용, AWS 의존 | 기존 AWS 수집을 활용 |
| Sentry | 예외 묶음, 스택·릴리스 중심 원인 분석 | HTTP 200 업무 실패는 별도 계측 필요. trace 기능과 중복 주의 | AI 기존 사용 정리, FE/BE 확대는 필요성 확인 |
| LangSmith | LLM 호출 흐름·모델 결과·평가·토큰 분석 | 전체 시스템·큐·EC2 관측을 대체하지 않음. 입력·출력 민감정보와 사용량 관리 | AI 전용 역할 유지·정리 |
| OpenTelemetry | trace 등 표준 계측과 컨텍스트 전달·전송 | 저장소·대시보드가 아님. Collector 운영과 backend 선택 필요 | 분산 추적의 계측 표준으로 추천 |

역할 분담은 중복 청구를 줄인다. 앱 메트릭은 우선 Prometheus, 앱 로그는 CloudWatch, LLM 상세 실행은 LangSmith를 기준으로 삼고, OTel 첫 PoC는 trace에 집중한다. 동일 앱 메트릭을 모든 도구에 복제하거나 모든 span을 Sentry·LangSmith·AWS에 중복 전송하지 않는다. 서로 다른 목적의 기록은 공통 ID로 연결한다.

### 개발자가 실제로 비교할 기준

같은 재현 사례를 A/B/C 구성에서 조사해 본다. 예를 들어 “배포 이후 AI 응답은 200이지만 추천 실패가 증가하고, 일부 요청은 제공자 429로 재시도한다”는 상황을 사용한다. 비교할 값은 최초 탐지까지의 시간, 문제 버전·요청·실패 단계 확인까지의 시간, 필요한 화면 이동 수, 누락된 정보, 월 예상 비용, 주간 운영시간이다. 통합 화면이 더 보기 좋다는 인상만으로 저장소를 이전하지 않는다.

### 현실적인 구성 대안

| 안 | 장점 | 비용·운영·보안의 대가 | 우리 팀 판단 |
| --- | --- | --- | --- |
| A. 기존 EC2 Prometheus/Grafana + CloudWatch + 기존 AI 도구 | 즉시 활용 가능, 수정 범위 작음, 기존 대시보드 재사용 | 단일 장애점, 짧은 보존, 서버 패치·백업·용량 관리 | **현재 추천**. 개발 연결과 측정 기반 마련 |
| B. AWS 관리형: AMP + CloudWatch 로그/trace, Grafana 유지 또는 별도 관리형 선택 | AWS IAM·기존 리소스와 연결, 시계열 저장소 운영 감소 | samples·조회·보관·collector 비용, AWS 의존. Grafana까지 자동으로 관리형이 되는 것은 아님 | **확장 시 1차 검토**. 우선 trace만 제한 PoC |
| C. Grafana Cloud + AWS 지표 연계 | PromQL 경험 활용, metrics/logs/traces 조사 통합, backend 운영 감소 | series뿐 아니라 DPM·전송량·보존 과금, 외부 반출·리전·권한 검토 | B와 비교할 유력 대안. 개발자 조사 동선이 더 좋으면 선택 가능 |
| D. Loki·Tempo 등 자체 운영 / Elasticsearch 중심 로그 검색 | 보관·설정 통제, 기술 학습, 용도별 최적화 가능 | 저장소·백업·업그레이드·고가용성·쿼리 성능을 팀이 운영 | 당장은 보류. 기존 작은 EC2에 전부 추가하지 않음 |
| E. Datadog 등 통합 SaaS | 통합된 인프라·APM 조사 흐름, 도구 간 이동 감소 가능 | EC2 host·container·custom metrics·APM·logs 등 SKU와 계약 확인, 플랫폼 의존 | 운영시간 절감 가치가 구독료보다 클 때 실측 견적 비교 |

관리형은 앱 계측·오류 의미 정의·권한·비용 관리까지 대신하지 않는다. 자체 운영도 라이선스 비용이 없다는 이유만으로 무료가 되지 않는다. 비교 기준은 월 청구액뿐 아니라 **문제 하나를 찾는 시간, 운영 작업 시간, 데이터 손실 위험, 팀이 유지할 수 있는 복잡도**다.

Datadog 비교 시 이 설계는 ECS on EC2이므로 Fargate task 단가를 그대로 적용하지 않는다. 계약·SKU별 사용량을 구분한다. [Datadog 사용량 설명](https://docs.datadoghq.com/account_management/plan_and_usage/usage_details/), [가격 목록](https://www.datadoghq.com/pricing/list/)

## 7. 네트워크 선택: 비용·보안·운영 트레이드오프

현재 모니터링/운영 VPC는 `172.31.0.0/16`, 개발 VPC는 `10.20.0.0/16`이며 CIDR이 겹치지 않는다. 현재 task와 모니터링 EC2는 같은 AZ지만 개발 서비스는 다른 AZ에도 배치될 수 있다.

| 방식 | 통신 형태 | 장점 | 비용·보안·제약 | 적합성 |
| --- | --- | --- | --- | --- |
| VPC Peering + pull | 모니터링 서버가 개발 task로 scrape | 기존 방식 유지, 별도 collector/유료 endpoint 불필요 | 라우트·SG 관리, 신뢰 범위 확대, cross-AZ 전송비 | **현 단계 추천 후보**, 선택 미확정 |
| 개발 collector → HTTPS remote_write/OTLP | 개발에서 수집 후 외부 저장소로 전송 | 중앙에서 개발 task로 접근할 경로 축소 | collector·인증·버퍼·중복·전송비 관리. egress/NAT/endpoint 확인 | 관리형 전환과 함께 적합 |
| CloudWatch datasource만 연결 | Grafana가 AWS API 조회 | VPC 간 앱 접근 없이 기존 AWS 데이터 표시 | 앱 Prometheus 지표가 자동 생성되지 않음. API/IAM/조회 비용 | 즉시 보완 가능하나 AI 계측 대체 불가 |
| PrivateLink | 서비스 endpoint로 제한된 서비스 제공 | VPC 전체 라우팅 공유 없이 서비스 접근 | endpoint AZ별 시간·GB 비용, 서비스 측 NLB 등 구성. LB 뒤 task 임의 분산은 task별 scrape와 다름 | 현재 2개 서비스 수집에는 복잡도 큼 |
| Transit Gateway | 중앙 라우팅 허브 | 여러 VPC로 확대할 때 관리 장점 | attachment 시간·데이터 처리 비용과 경로 관리 | 현재 두 VPC에는 우선순위 낮음 |
| 관측 전용 VPC/계정 | 운영 앱과 관측 자원을 별도 격리 | 장기 권한·장애 경계 정리 | 이전·연결·관리 비용. 네트워크 연결 방식은 별도 필요 | 장기 운영 구조 검토 |

Peering 자체에는 연결 시간 요금이 없으며 같은 AZ의 peering 데이터 전송은 무료다. cross-AZ는 양쪽에 각각 $0.01/GB가 적용되는 경우 합계 약 $0.02/GB다. 따라서 계량한 양방향 합계가 100GB라면 전송비 예시는 약 $2다. 인터넷·다른 서비스 처리 요금까지 포함한 총액이 아니다. [AWS Peering](https://docs.aws.amazon.com/vpc/latest/peering/what-is-vpc-peering.html), [VPC 가격](https://aws.amazon.com/vpc/pricing/)

Peering을 선택한다면 개발 앱 subnet 목적지와 모니터링 IP의 반환 경로를 좁히고, BE 8081/AI 9464를 모니터링 출발지에만 허용한다. 단, 라우팅은 응답 경로까지 필요하며 **일방향 보안 경계를 만드는 장치가 아니다**. 현재 공유 main route table과 모니터링 서버의 기존 443 허용 규칙까지 영향 분석해야 한다. SG는 `/actuator/prometheus` 같은 HTTP 경로를 구분하지 않으므로 BE 8081 접근은 애플리케이션 포트 접근 권한이다. [SG 참조 제약](https://docs.aws.amazon.com/vpc/latest/peering/vpc-peering-security-groups.html)

private IP 사용은 앱 계층 TLS·인증을 대신하지 않는다. 공유 모니터링 서버 침해는 운영·개발 양쪽 관측에 영향을 줄 수 있고, `environment` 라벨은 접근 통제가 아니다. 더 강한 경계가 요구되면 환경별 collector·workspace·계정·자격증명 분리를 선택해야 한다.

관련 공식 근거: [PrivateLink 서비스 공유](https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-share-your-services.html), [PrivateLink 가격](https://aws.amazon.com/privatelink/pricing/), [Transit Gateway 가격](https://aws.amazon.com/transit-gateway/pricing/), [Grafana CloudWatch 설정](https://grafana.com/docs/grafana/latest/datasources/aws-cloudwatch/configure/).

## 8. ECS 수집·추적 설계 제안

### task 변경을 자동 추적한다

초기 확인에 사용한 task IP를 영구 등록하지 않는다. ECS API 기반 발견 작업이 지정 cluster/service의 실행 task와 ENI·포트를 조회하고 Prometheus file_sd를 원자적으로 갱신하는 방식을 후보로 삼는다. EC2 instance profile에 필요한 조회 권한만 부여하고 실패·마지막 성공 시각을 관측한다. IAM API 중 resource 단위 제한을 지원하지 않는 항목은 별도로 문서화한다.

정상 배포에서는 새 task가 수집 대상에 들어오고 종료 task가 제거돼야 한다. 발견 실패 시 빈 파일로 전체 대상을 지우지 않고 마지막 성공 목록을 유지하되 stale 경보를 낸다. ALB 주소만 scrape하면 여러 task 중 일부만 보일 수 있으므로 task별 endpoint를 수집한다. dev/prod 서비스 이름이 같아도 환경·cluster가 보존돼야 한다.

### Collector 배치 선택

| 배치 | 이점 | 부담·주의 | 추천 사용 |
| --- | --- | --- | --- |
| EC2당 daemon task | 호스트당 한 번 배치, 앱별 sidecar 중복 감소 | 호스트 교체·drain 시 버퍼 유실, 앱에서 endpoint 접근 구성 | 노드 수집·전송이 필요할 때 |
| 앱 task sidecar | 앱과 설정·수명 관리, localhost 전송 | task 수만큼 자원·배포·버퍼 중복 | 특정 앱 격리 요구가 있을 때 |
| 별도 ECS gateway service | 중앙 필터·sampling·인증 정책 | 자체 용량·가용성·네트워크·queue 운영 필요 | trace PoC는 작은 전용 service, 이후 측정해 확장 |

OTel Collector의 agent/gateway 패턴은 조합 가능하다. 모든 계층을 처음부터 배치하지 않는다. 첫 trace PoC에서는 BE·AI SDK에서 별도 gateway로 보내고, 앱 응답과 telemetry export 실패를 분리한다. 운영 확대 전에는 collector replica·배치 AZ·drain·재시도·bounded queue·메모리 제한·드롭 경보를 검증한다. [OTel 배치 패턴](https://opentelemetry.io/docs/collector/deploy/)

### 추적 저장소의 첫 후보

AWS 권한·로그를 이미 사용하는 점을 고려해 CloudWatch OTLP endpoint와 Transaction Search를 먼저 시험한다. span 수집·로그 저장과 trace summary indexing은 서로 다른 단계이며 과금도 구분한다. **index 비율을 낮추는 것만으로 이미 수집한 span의 ingest 비용이 줄어들지는 않는다.** 정확한 endpoint·서울 리전 지원·exporter 인증·log group 보존·계정 설정 영향은 PoC 구성 전 확인한다. [OTLP endpoint](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPEndpoint.html), [Transaction Search](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Transaction-Search.html)

신규 앱에는 기존 X-Ray SDK/daemon 대신 OTel 계측을 사용한다. AWS 문서상 해당 SDK/daemon은 2026-02-25부터 유지보수 모드다. 이는 X-Ray 서비스 자체 종료를 의미하지 않는다. [지원 일정](https://docs.aws.amazon.com/xray/latest/devguide/xray-sdk-daemon-timeline.html)

PoC는 BE→AI의 실제 요청 하나부터 시작하고, V2 큐·Worker 구현 후 producer/consumer 컨텍스트를 검증한다. `job_id`는 유지하고 처리 시도별 span을 분리하며 재전달·중복·fan-out을 표현한다. 장시간 작업·SSE를 하나의 무한히 긴 trace로 묶기보다 완료 가능한 구간과 span link를 사용한다.

### 샘플링의 선택

저트래픽 개발 PoC는 짧은 기간 100% 수집으로 누락을 먼저 검증한다. 운영 비용 계산에서는 10% head sampling을 예시로 사용하지만 확정 정책은 아니다. head에서 버린 요청의 오류 trace를 뒤의 tail sampler가 되살릴 수는 없다. 오류 메트릭·완료 로그는 trace 샘플링과 독립적으로 남긴다.

tail sampling으로 오류·느린 요청을 보존하려면 판단 전까지 span이 collector에 도착해야 하므로 collector 처리량·메모리·trace별 routing·긴 작업 대기시간 부담이 생긴다. “오류는 전부 저장하면서 비용은 10%”라고 단정하지 않는다. [OTel sampling](https://opentelemetry.io/docs/concepts/sampling/)

## 9. 데이터 계약·보안·알림

### 공통 계약

| 데이터 | 필수 연결 정보 | 제한 |
| --- | --- | --- |
| 메트릭 | environment, cluster, service, 제한된 route/operation/outcome | user_id·request_id·job_id·원문 URL·오류 메시지를 label로 넣지 않음 |
| 로그 | UTC timestamp, environment, service, release, request_id, operation, outcome/error_code | 토큰·쿠키·비밀키·프롬프트 원문 기본 제외 |
| trace | service.name, 환경·버전 resource 속성, trace/span context | SDK 속성명을 내부 계약으로 정규화, 본문 수집 제한 |
| 비동기 로그·trace | job_id, attempt, enqueue/start/end, dependency status | 중복 처리와 실패 재시도를 구분 |
| 도구 연결 | sentry_event_id, langsmith_run_id 등 실제 생성된 ID | 없는 값을 성공적으로 연동된 것처럼 기록하지 않음 |

task 식별자는 per-task 진단용 시계열과 로그·trace에 필요할 수 있으나 모든 업무 지표에 중복 부여하지 않는다. 종료 task가 만드는 churn도 비용으로 측정한다. 배포 SHA는 로그·trace와 제한된 info metric/annotation에 두고 모든 metric의 label로 확장하지 않는다. [Prometheus 계측 원칙](https://prometheus.io/docs/practices/instrumentation/)

개발 endpoint가 임의 label로 운영 데이터를 가장하지 못하도록 수집기에서 환경·cluster를 신뢰 가능한 발견 정보로 지정한다. Prometheus·exporter·관리 endpoint를 공개하지 않고 Grafana 조회 권한과 AWS 데이터소스 권한도 분리해 검토한다. Sentry의 과거 공유 로그인 기록은 현재 팀 권한 설계의 근거로 사용하지 않는다. 개인별 계정·최소 권한·접근 회수 방법을 확인한다. [Prometheus 보안 모델](https://prometheus.io/docs/operating/security/)

LangSmith/Sentry 등 외부 전송은 API 키뿐 아니라 사용자 입력·영상 URL·모델 출력에 포함될 수 있는 개인정보를 검토한다. 수집 전 필터링·마스킹을 기본으로 하고 상세 원문은 승인된 재현 데이터에서만 사용한다. Discord에는 원문 스택·본문·비밀값 대신 제한된 요약과 권한이 필요한 조사 링크를 보낸다.

### HTTP 성공과 업무 성공을 분리한다

AI `/v1/recommend-courses`는 HTTP 200에서도 `recommend_failed` 등 업무 결과가 나올 수 있다. HTTP 5xx 비율만으로는 실패를 찾지 못한다. `success`, `failed`, `cancelled`, `not_found` 등을 제한된 outcome으로 나누고, 취소·입력 부적합을 장애 SLI에 포함할지는 제품 의미에 따라 합의한다. 제공자 403을 모두 비공개 영상으로 단정하지 않는다.

### 알림과 SLO의 시작점

| 대상 | 초기 관측·알림 | 주의 |
| --- | --- | --- |
| 수집 | target down, 예상 서비스 target 없음, discovery stale | `up=0`만으로 사라진 target을 전부 탐지하지 못함 |
| BE | 트래픽·5xx·p95, DB pool, 배포 상태 | 최소 요청 수·지속시간을 함께 적용 |
| AI | 업무 실패·provider429/5xx·timeout·활성 요청 | CPU만으로 포화 판단하지 않음 |
| Worker·SSE | oldest age·DLQ·완료율, 최초 이벤트·연결 실패 | 서비스 구현 이후 적용 |
| 관측 서버 | 메모리·디스크·보존일·scrape 지연, 외부 생존 확인 | 자기 자신에서만 평가하는 down 경보는 서버 중단 때 작동하지 못함 |

숫자로 된 SLO는 아직 합의하지 않았다. BE는 적격 요청의 성공률/지연, AI는 작업 접수율과 최종 성공률/완료시간, SSE는 최초 결과 전달시간을 따로 정의한다. 기준 기간·제외 대상·목표·담당을 정한 뒤 error budget과 burn-rate 경보를 설계한다.

개발은 요청이 드물므로 “최근 요청 없음”을 정상 또는 장애로 자동 판단하지 않는다. 계획된 중지·배포를 구분하고, 사용자 정의 synthetic에는 실제 유료 모델 호출이 필요한지 따로 결정한다. Blackbox exporter scrape up과 실제 `probe_success`도 별개다.

Discord는 `[DEV][service][severity]`와 환경별 group key, firing/resolved를 갖추고 대시보드·로그·runbook을 연결한다. 개발과 운영 경보는 같은 채널에서도 그룹·severity·조치 기대를 분리한다. 적용 시험은 수신과 복구를 모두 확인하되 실제 전송은 후속 실행 단계에서 수행한다.

## 10. 비용 산정: 현재 증분과 미래 규모를 분리한다

### 계산 원칙

아래는 USD, 세금·환율·약정 할인 제외다. 관측 계정의 실제 청구서나 최종 견적이 아니다. 현재 EC2/EBS 비용은 계속 존재하며 “새 EC2 없음”은 “총비용 0”이 아니다. 무료 제공량의 계정 적용·공유 사용량은 확인되지 않았으므로 CloudWatch 예시는 무료 공제 전, AMP는 명시한 가격표 구간을 적용한다.

`월 총비용 = 기존 EC2/EBS/백업 + 증설 + 수집/보관/검색 + 네트워크 + collector + SaaS/좌석 + 운영시간`

운영시간은 서버 패치·복구·데이터 손실 조사·권한·계측 유지·알림 튜닝까지 포함한다. V2 설계의 앱 인프라 예산에 관측 로그·전송·AI 모델 비용이 빠져 있으므로 그 총액을 그대로 전체 서비스 비용으로 인용하지 않는다.

### 서울 리전 기준 단가와 과금 단위

AWS 공개 Price List의 CloudWatch 게시일은 2026-10-07, AMP는 2026-10-14이며 아래 rate의 적용 시작일은 2026-10-01이다. 링크의 `current` 값은 이후 바뀔 수 있으므로 조회일·usage type을 함께 남긴다.

| 항목 | 확인 단가 | 식별자·계산 주의 |
| --- | --- | --- |
| CloudWatch Standard 앱 로그 ingest | $0.76/GB | `APN2-DataProcessing-Bytes`, PutLogEvents |
| 로그 저장 | $0.0314/GB-month | `APN2-TimedStorage-ByteHrs`, 압축·실제 보관량 기준 |
| Logs Insights 기존 StartQuery 스캔 | $0.0076/GB | `APN2-DataScanned-Bytes`. 다른 query mode 가격과 혼용 금지 |
| 사용자 정의 지표 첫 10,000개 | $0.30/metric-month | `APN2-CW:MetricMonitorUsage`, dimension 조합 주의 |
| ECS Container Insights enhanced | $0.07/metric-month | `APN2-CW:MetricsUsage`, `MetricStorage:CI-ECS` |
| OTLP span ingest 관련 표준 요율 | $0.76/GB | `APN2-DataProcessingOtel-Bytes`. 실제 선택 mode 확인 |
| X-Ray indexed spans | $0.75/100만 span | `APN2-XRay-Spans-Indexed`, ingest와 별도 |
| AMP ingest | 첫 4천만 samples $0, 이후 20억까지 $0.90/1천만, 이후 2,520억까지 $0.35/1천만 | `APN2-AMP:MetricSampleCount`, 월 사용량 구간 |
| AMP 저장 | 첫 10GB $0, 이후 $0.03/GB-month | ingest와 별도. 조회·전송·collector도 별도 |

**ECS enhanced에 EKS의 observation당 요금을 적용하지 않는다.** CloudWatch에는 OTLP/Signals/검색의 여러 요금 경로가 있으므로 실제 활성화 기능의 SKU를 확인해야 한다. Application Signals를 자동으로 추가하거나 서로 대안인 과금 모드를 중복 계산하지 않는다.

근거: [CloudWatch 서울 공개 가격표 JSON](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/ap-northeast-2/index.json), [CloudWatch 가격](https://aws.amazon.com/cloudwatch/pricing/), [AMP 서울 공개 가격표 JSON](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonPrometheus/current/ap-northeast-2/index.json), [AMP 가격](https://aws.amazon.com/prometheus/pricing/).

### 로그: 요청당 기록량이 비용을 바꾼다

30일을 가정한다. 혼합 월은 평시 26일+이벤트 4일이며, 모든 날이 이벤트인 열은 상한 민감도 비교용이다. 예시는 BE 요청 한 건에 연결된 서비스 전체의 **유효 과금 로그량 합계**를 2kB 또는 10kB로 가정한다. 서비스마다 이 값을 추가하는 계산이 아니며, 독립 Worker 작업·호스트 로그는 별도로 더해야 한다.

비교 모델은 1kB=1,000 bytes, 1GB=10억 bytes로 계산한다. 실제 AWS 계량값·직렬화·이벤트 overhead와 차이가 있을 수 있어 운영 견적에서는 청구 usage GB로 보정한다.

| 30일 시나리오 | BE 요청 수 | 2kB/요청 로그량 | ingest만 $0.76/GB | 10kB/요청 ingest만 |
| --- | ---: | ---: | ---: | ---: |
| 평시 30일 | 28,800,000 | 57.60GB | $43.78 | $218.88 |
| 평시 26일 + 이벤트 4일 | 40,320,000 | 80.64GB | $61.29 | $306.43 |
| 이벤트 30일 | 115,200,000 | 230.40GB | $175.10 | $875.52 |

보존 비용은 월 ingest GB를 그대로 GB-month로 대입하지 않는다. 보존일, 압축률, 시간별 저장량을 반영한다. 검색도 저장량이 아니라 매번 스캔한 양을 합산한다. 예를 들어 해당 StartQuery 모드에서 월 1,000GB를 스캔하면 조회 부분만 $7.60이다. 시간·환경·서비스로 조회 범위를 줄이고 잦은 대시보드 새로고침의 비용도 측정한다.

### 메트릭: Prometheus 자체 운영과 관리형 비교

30초 주기, 30일, 시계열 수 일정, 복제 수집 없음이면 월 samples는 `시계열 수 × 86,400`이다. histogram·task 교체·recording rule·HA 중복이 생기면 별도 반영한다.

| 활성 시계열 가정 | 월 samples | AMP ingest 예시 |
| --- | ---: | ---: |
| 10,000 | 864,000,000 | $74.16 |
| 20,000 | 1,728,000,000 | $151.92 |
| 100,000 | 8,640,000,000 | $408.80 |

표는 첫 4천만 무료 구간이 전부 남아 있고 다른 workspace 사용량이 없다는 가정이다. 100,000개 예시는 `(20억−4천만)/1천만×$0.90 + (86.4억−20억)/1천만×$0.35`다. 저장·조회·collector·전송·Grafana는 포함하지 않는다. 무료 구간이나 가격 tier의 계정별 합산 적용은 실제 청구 설정으로 확인한다.

Grafana Cloud Pro는 확인 시점 플랫폼 기본료 $19/월, 10k 포함 후 시작 단가 $6.50/1k billable series다. 기본 1DPM 조건에서는 30초 수집의 20k active series가 40k billable series에 해당할 수 있다. 이 경우 단순 시작 단가 예시는 `$19 + (40k−10k)/1k×$6.50 = $214/월`, 60초 수집이면 `$84/월`이다. 실제는 청구 기간의 p95 active series와 p95 DPM, volume discount·계약을 적용한다. AMP와 보존·조회 포함 범위가 달라 이 숫자만으로 우열을 정하지 않는다. [Grafana 가격](https://grafana.com/pricing/), [metrics 과금 정의](https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/metrics/)

자체 Prometheus에는 samples당 청구가 없지만 메모리·디스크·CPU·복구 비용이 있다. 현재 2GB 제한으로 얼마 동안 보관되는지 실제 측정해야 한다. `$151.92`와 기존 EC2 가격 하나만 비교하면 관리형의 장기 보관과 자체 운영시간을 빠뜨린다.

### Trace·AI 상세 관측

혼합 월 40.32M 요청에서 요청당 20 spans, 유효 span당 1kB, 10% source sampling을 가정하면 **80.64M spans, 80.64GB**다. 100%면 806.4M spans, 806.4GB다. 비동기 fan-out과 retry는 추가된다. 단순 예시일 뿐 실제 평균 span 수·크기는 PoC에서 측정해야 한다.

AWS 표준 OTLP ingest $0.76/GB를 적용하는 경우 위 10% 예시의 ingest 부분은 $61.29다. 이후 수신 span의 1%를 indexed summary로 처리한다고 가정하면 index 부분은 `80.64M×1%×$0.75/M = $0.60`이다. **source sampling 10%와 backend indexing 1%는 다른 값**이다. 저장·검색·Signals·collector 비용과 해당 기능의 실제 구성 가능 범위는 별도 확인한다. 앞의 앱 로그 예시와 trace span 저장은 서로 다른 데이터이므로 둘 다 수집하면 둘 다 청구될 수 있다.

Grafana Cloud의 logs/traces는 확인 시점 시작 단가가 Process $0.05/GB, Write $0.40/GB, Retain $0.10/GB로 나뉜다. 각 단계의 과금량·포함량·보존 조건을 확인해 합산해야 하며 단일 ingest 가격처럼 비교하지 않는다. 무료 플랜은 metrics 10k, logs/traces 각각 50GB, 보존 14일 제한이 있어 PoC 후보이지 MAU 80만 운영비 보장은 아니다. [Grafana 가격](https://grafana.com/pricing/)

LangSmith 비용은 AI 요청 비율, 실제 청구 trace 정의, 보존·좌석·평가 사용량에 좌우된다. BE HTTP 요청 수를 그대로 LangSmith 청구 건수로 쓰지 않는다. LLM 평가를 실행하면 관측 도구 요금 외 모델 호출 비용도 발생한다. Sentry도 오류·span 등 실제 요금제와 좌석을 확인해야 하므로 확인되지 않은 월 금액을 넣지 않는다. [LangSmith 가격](https://www.langchain.com/pricing), [Sentry 견적 안내](https://www.sentry.help/en/articles/13965054-can-i-get-a-quote-for-sentry)

### 지금 개발 연결의 증분 비용

| 항목 | 초기 판단 | 측정/결정 필요 |
| --- | --- | --- |
| 추가 EC2 | 우선 새 서버 없이 시작하는 제안 | 7일 이상 수집·조회 부하 측정 후 증설 판단 |
| 네트워크 | 10월 20일 최종 BE·AI는 모니터링 호스트와 다른 AZ. 메트릭 응답 본문 기준 약 $0.06/월 추정 | 15절의 계산 조건과 실제 전송량으로 보정 |
| 로그 | 개발 요청량·보존에 비례해 증가 | 로그 그룹별 IncomingBytes·보존·query scan |
| collector | 직접 pull 1차 연결에는 새 OTel collector 불필요 | trace PoC 때 ECS 자원 추가 |
| SaaS | 기존 연동을 연결하더라도 사용량 증가 가능 | 현재 플랜·포함량·알림/사용량 상한 |
| 운영 | 초기 계측·자동 발견·환경 분리·알림 시험 필요 | 이후 주간 유지시간과 조사시간 변화 |

월 예산을 B로 정한 뒤 예상 월말 비용의 50/80/100%에서 검토·주의·조치하도록 제안한다. 예산 알림은 자동 지출 차단이 아니다. 초과 시 debug 로그·불필요한 label·trace 수집률부터 조정하고 오류/보안 기록을 무조건 버리지 않는다. 예산 B 자체는 사용자 미결정 사항이다.

### 보존 기간의 시작 제안

| 데이터 | 시작 제안 | 결정 전 확인 |
| --- | --- | --- |
| 기존 로컬 메트릭 | 현재 7일/2GB 유지 후 실제 보존일 측정 | 7일 목표보다 먼저 크기 제한에 도달하는지 |
| 개발 앱 로그 | 7일 후보 | 배포·재현 조사 주기, 기존 보존 정책 |
| 운영 앱 로그 | 기존 기록의 14일을 우선 기준으로 검토 | 현재 실제 설정, 장애 조사·제품 요구 |
| Trace PoC | 7일 후보, 시험 종료 후 비용·효용 평가 | backend에서 지원하는 보존 단위·최소 기간 |
| 장기 성능 비교 | 관리형에서 필요한 집계 지표부터 기간 확대 | 월간 회귀·용량 계획에 필요한 범위 |

위 기간은 승인된 정책이 아니다. 감사·보안 이벤트는 앱 debug 로그와 별도 요구를 확인하며, SaaS의 고정 보존 플랜을 임의로 단축할 수 있다고 가정하지 않는다. 실사용량이 확인되면 수집률·보존·조회 비용을 함께 조정한다.

## 11. 단계별 실행안과 통과 기준

| 단계 | 작업 | 통과 기준·증거 | 상태 |
| --- | --- | --- | --- |
| 0. 기준 확인 | 실제 VPC·task·메트릭·모니터링 자원 점검 | 조회 시점·근거·미확인점 기록 | 완료 |
| 1. 연결안 구체화 | 네트워크 diff, AI 선별 수정안, 환경 라벨·쿼리·발견 설계 | 변경 파일·영향·롤백·포트·권한이 검토 가능 | 계획 작성, 구현 미실시 |
| 2. BE·AI 연결 | 선택된 네트워크, AI 배포, target 발견, dev 대시보드 | 두 서비스의 실제 sample 유입, 운영 쿼리 분리, task 교체 후 자동 복구 | 미적용 |
| 3. 조사 동선 연결 | JSON/ID/release 계약, CloudWatch 링크, AI outcome, Discord 시험 | 한 오류를 요청·버전·원인까지 추적, firing/resolved 확인 | 미적용 |
| 4. 비용·용량 관찰 | 최소 7일, 가능하면 배포·부하 시험 포함 | active series·samples/s·로그 GB/일·query GB·보관일·운영시간 기록 | 미실시 |
| 5. Trace PoC | BE→AI 경로, 이후 큐·Worker·SSE | context 누락·재시도·취소·sample/drop·export 장애를 검증 | 후속 제안 |
| 6. 규모 확대 판단 | event 부하·노드 교체·관측 장애 시험, B/C 비교 | SLO·복구 목표·예산·조사시간 기준 충족 | 후속 제안 |

AI는 main 전체를 develop에 합치지 않고 기존 메트릭 모듈을 선별 이식한다. develop의 422 응답 처리와 새 라우트 동작을 보존하고 listener 시작·정상/오류/취소 outcome·metric label을 검증한다. 현재 CI의 주석 처리된 pytest 실행 상태를 고려해 필요한 계측 테스트가 실제 CI에서 실행되게 하는 변경안을 포함한다. 상세 파일·커밋 기준은 [AI 수정 계획](dev-monitoring-connection.md)에 있다.

각 적용은 설정 검증→제한된 대상 배포→관측 확인→확대로 진행한다. 앱 계측 장애가 앱 기동·요청 처리를 막지 않도록 하고, 실패 시 앱 이미지·수집 설정·라우트/SG를 이전 상태로 되돌릴 수 있게 변경 전 값을 기록한다. 기존 운영 TSDB volume은 보존한다.

### 관리형 이전 또는 분리 검토를 시작할 조건

- 필요한 보존 기간을 현 디스크/메모리 한도로 충족하지 못하거나, 지표 수집·조회 지연이 서비스 대응을 방해한다.
- 관측 서버 재기동·AZ 장애 때 허용 가능한 관측 공백/데이터 손실 목표를 충족하지 못한다.
- patch·증설·복구 등 반복 운영시간이 팀의 합의된 한도를 넘는다.
- dev 부하가 prod 수집·알림을 방해하거나, 팀 권한 요구를 하나의 저장소로 충족하기 어렵다.
- 로그/trace 유입량과 월말 예상 비용이 예산 B에 접근해 보존·수집 정책 재설계가 필요하다.

전환 여부는 MAU 숫자 하나가 아니라 이 조건과 실제 장애·부하 시험으로 정한다. 관리형 전환 시에도 일정 기간 제한된 이중 수집으로 쿼리·규칙·알림의 동등성을 확인하고, 검증 후 중복 전송을 종료한다. 이 기간의 중복 비용도 예산에 넣는다.

## 12. 사용자·개발팀과 에이전트의 역할

| 항목 | 에이전트가 할 수 있는 작업 | 사용자·팀이 정할 사항 |
| --- | --- | --- |
| 현황·선택 문서 | 읽기 전용 점검, 공식 자료 조사, 비용 모델, 결정 기록 | 사실 오류·팀 우선순위 정정 |
| 네트워크 | 실제 route/SG 기반 최소 변경안·IaC diff·롤백 작성 | Peering 등 방식, 공유 신뢰 범위 수용 |
| AI/BE 코드 | 계측 변경안·테스트·PR 초안, 기존 동작 보존 확인 | 업무 outcome 의미, 코드 리뷰·배포 시점 |
| Prometheus/Grafana | 발견·라벨·쿼리·대시보드·경보 변경안과 검증 | 관측 범위·알림 담당·중요도 |
| 로그·trace | ID 전파·마스킹·collector PoC 구현안 | 보존 기간, 원문 수집 정책, SaaS 반출·계정 권한 |
| 비용 | 실제 수집량 기반 재계산, 비용 경보안 | 월 예산 B, 과금 도입·좌석 구매 |
| 운영 검증 | 부하·실패 시나리오와 측정 기록 작성, 승인 범위 내 실행 | 장애 시험 시간·운영 SLO·복구 목표 |

문서 작성과 읽기 전용 조사는 완료 범위다. 인프라 적용·앱 배포·외부 채널 시험 전송·유료 서비스 활성화는 이 문서의 제안과 구분한다. 이후에는 구체적인 diff와 시험안을 만든 뒤 실제 결정이 필요한 항목만 확인한다.

### 남은 결정 기록

| ID | 사안 | 현재 추천 | 상태 |
| --- | --- | --- | --- |
| O-01 | 최초 수집 네트워크 | 제한된 Peering + task별 pull | 미결정 |
| O-02 | 관측 플랫폼 기본 선택 | 기존 Prometheus/Grafana + CloudWatch 유지 | 기존 재사용 확정, 세부 확장은 제안 |
| O-03 | trace 계측/첫 backend | OTel + AWS 관리형 제한 PoC | 미결정 |
| O-04 | 개발팀의 가장 중요한 조사 문제 | 배포 이상·BE→AI 지연·업무 실패 순으로 검증 | 사용자 우선순위 미확인 |
| O-05 | 예산·보존·데이터 반출 | 실측 후 dev/prod 별 예산·보존·접근 정책 확정 | 미결정 |
| O-06 | 운영 책임·SLO | 서비스별 담당, 알림 조치, 복구 목표 명시 | 미결정 |

이 미결정 항목은 문서 작성의 장애물이 아니며, 잠정 추천을 채택 완료로 표시하지 않는다.

## 13. 포트폴리오에 남길 근거

가치 있는 결과는 “도구를 여러 개 설치했다”보다 **제약을 설명하고, 실패를 재현하고, 개선을 수치로 입증한 기록**이다.

| 남길 자료 | 보여주는 판단·역량 | 정직한 표현 |
| --- | --- | --- |
| 현재/변경 후 구성과 선택 기록 | 기존 자산·팀 운영 부담·보안 경계를 고려한 선택 | 선택 이유와 보류한 대안까지 제시 |
| task 교체 전후 자동 발견 결과 | ECS의 동적 실행 환경 대응 | 실제 시험한 task 수·AZ·배포 조건 명시 |
| HTTP 200 업무 실패 재현과 감지 | 사용자 결과 중심 계측 | 오류 분류·알림·로그 연결의 전후 비교 |
| BE→AI→작업 추적 사례 | 분산·비동기 원인 분석 | 계측한 경로만 표시, 미구현 경로 분리 |
| 비용 모델과 실제 사용량 차이 | 단위·카디널리티·샘플링 이해 | 예측치와 청구/계량값의 오차 설명 |
| 모니터링/collector 장애·복구 시험 | 관측 시스템 자체의 신뢰성 설계 | 데이터 손실·복구 시간·한계 공개 |
| 조사 소요시간·오탐·누락 변화 | 개발팀 생산성 개선 | 동일 시나리오 전후 측정, 표본 수 명시 |

예시 제목은 “ECS on EC2 개발 환경에 기존 관측 자산을 확장하고 업무 실패 추적을 개선한 설계”가 적절하다. “MAU 80만 실제 운영”이나 검증하지 않은 “무중단·완전한 추적”으로 포장하지 않는다. 공개 자료에서는 계정·리소스 식별자, 내부 주소, 사용자 데이터, 토큰·웹훅을 제거한다.

## 14. 근거와 후속 갱신

| 근거 | 시점·용도 | 한계 |
| --- | --- | --- |
| [개발 모니터링 점검 기록](dev-monitoring-connection.md) | 2026-10-19 AWS/SSM 읽기 전용 점검 | 이후 배포·구성 변경 미반영 가능 |
| [V2 설계](<V2 설계.md>) | MAU·트래픽·ECS/ASG·SSE/Worker 설계 | 목표 시나리오, 현재 구현/부하 검증과 다름 |
| [기존 옵저빌리티 검토](observability-adoption-review.md) | 2026-10-16 도구 연동·오류 사례·관측 계약 | SaaS 현재 플랜·수집량 미검증 |
| [모니터링 전체 안내](monitoring-overview.md) | 기존 지표·규칙·구성 탐색 | 선언된 설정과 실제 실행 상태 구분 필요 |
| [Sentry 기록](v1-sentry.md) | 과거 AI 도입 상황 | 현재 요금제·팀 접근 정책으로 간주하지 않음 |
| 본문 공식 문서·가격표 | 2026-10-20 조회 | 가격·제품 기능은 도입 시 재확인 |

로컬 읽기 전용 조회 원본은 Git 제외 경로 `.artifacts/dev-monitoring/`, 가격 원본에서 추린 rate는 `.artifacts/observability-selection/aws-seoul-rates.json`에 보관한다. 공개 문서는 이 파일 없이도 본문의 가정·공식 링크·산식으로 검토할 수 있다. 다음 갱신에는 실제 결정, 적용 diff, 검증 결과, 측정 사용량을 추가한다.

## 15. 개발 로그 조회·실시간 확인과 피어링 비용 비교

갱신·가격 재확인: **2026-10-21 KST**. 구성 근거는 10월 20일 AWS/Grafana 점검이며 이번 문서 갱신에서 인프라를 다시 변경하지 않았다. 금액은 USD, 세금·환율·계약 할인·프로모션 크레딧 제외다. 사용량 표는 실제 청구액이 아닌 가정별 비교다.

### 현재 되는 것과 추가할 것

| 항목 | 현재 상태 | 개발팀 동선 |
| --- | --- | --- |
| 개발 메트릭 | BE·AI 수집과 `[DEV]` Discord 경보·복구 검증 완료 | Grafana 개발 HTTP/JVM 대시보드 |
| 개발 앱 로그 | CloudWatch에 수집 중, BE·AI 로그 보존 각각 30일 | 서울 리전 `/keepgo/v2/backend`, `/keepgo/v2/ai-api` |
| Grafana 로그 조회 | 미구성. 실제 datasource는 Prometheus 하나 | CloudWatch datasource·조회 IAM·개발 로그 화면 추가 필요 |
| 실시간 로그 | CloudWatch Live Tail 기능 사용 가능 | AWS 접근 및 `logs:StartLiveTail` 등 필요한 권한 확인 후 이용. 팀별 권한·실사용 시험은 미실시 |
| 향후 역할 전환 | 현재 V1=운영, V2=개발 | 역할 전환 시 라벨·로그 화면·IAM·알림을 함께 변경 |

로그 그룹은 서비스 단위이고 ECS 스트림은 `접두사/컨테이너/task ID` 단위다. 개발 BE에는 `backend/backend/...`와 준비 컨테이너 `jwt-files/jwt-files/...`가 함께 있다. 배포·task 교체 뒤 과거 스트림이 남는 구조이므로 팀 공용 화면은 그룹 전체를 시간 범위로 조회하고 기본적으로 앱 컨테이너만 표시하도록 제안한다. 오류 원문·배포 직후 원인 조사에는 필요한 경우 준비 컨테이너도 별도로 조회한다.

### 방식별 기능·비용·트레이드오프

| 방식 | 얻는 것 | 추가 비용 구조 | 한계·현재 판단 |
| --- | --- | --- | --- |
| CloudWatch Logs Insights 공통 쿼리 | task를 몰라도 BE·AI 전체 검색, 저장 쿼리 공유 | 쿼리마다 스캔한 GB | 가장 작은 변경. 개발자 AWS 접근 권한과 콘솔 사용 필요 |
| 기존 Grafana + CloudWatch | 메트릭과 같은 화면에서 서비스·시간·키워드로 로그 조회 | 동일 Logs Insights 스캔 비용 + 기존 Grafana 처리 자원 | 우선 추천. 새 로그 저장소·복제 불필요. 데이터소스 및 IAM 구성 필요 |
| Grafana 주기적 재조회 | 일정 간격으로 최신 로그를 갱신 | 반복 조회의 누적 스캔량 | 제안 화면의 갱신 방식이며 스트리밍 Live Tail과 다름. 기본 자동 갱신은 끄고 필요 시 30~60초 후보 |
| CloudWatch Live Tail | 새로 유입되는 로그를 스트리밍으로 확인 | 세션 사용 분 | 배포·재현 중 짧게 사용 추천. 수집 지연이 있고 과거 검색을 대체하지 않음 |
| Loki 등 별도 로그 저장소 | 별도 검색·tail 구성과 보존 정책 제어 | 수집기, 저장소, 컴퓨팅, 전송, 백업, 운영시간 | 현 단계 보류. 무료 소프트웨어가 운영비 0을 뜻하지 않으며 관측량·보존·HA가 미정이라 정액 견적을 만들지 않음 |

Grafana는 CloudWatch Logs Insights 조회를 지원한다. 여기서 제안한 자동 갱신 화면을 CloudWatch `StartLiveTail`과 동일한 기능·요금으로 표현하지 않는다. 설치 버전에서 별도 live 연동을 원하면 지원·권한·과금 경로를 먼저 검증한다. [Grafana 조회 문서](https://grafana.com/docs/grafana/latest/datasources/aws-cloudwatch/query-editor/)

Live Tail은 Standard 로그 그룹을 대상으로 하며 현재 개발 그룹이 해당한다. 초당 일치 이벤트가 500개를 넘으면 표시 결과가 샘플링될 수 있고, 세션은 최대 3시간이다. 전체 오류 건수나 로그 완전성을 검증할 때는 저장 로그 검색을 사용한다. [AWS Live Tail](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CloudWatchLogs_LiveTail.html)

### 과금 경로를 구분한다

| 경로 | 청구 항목 | 이번 피어링과의 관계 |
| --- | --- | --- |
| 개발 BE·AI → 기존 Prometheus 메트릭 응답 | AZ 간 피어링 데이터 전송 | 이번 연결의 직접 비용 |
| 앱 → CloudWatch 로그 수집·보관 | ingest, 저장량 | 이미 운영 중인 로그 경로. 메트릭 연결비에 포함하지 않음 |
| Grafana → CloudWatch API → 조회 결과 | Logs Insights 스캔, 실제 API 접근 경로의 네트워크 비용 | 개발 VPC 피어링 불필요. NAT/PrivateLink를 별도로 사용하는 설계라면 해당 비용은 추가 |
| 개발자 → CloudWatch Live Tail | Live Tail 세션 분 | 개발 VPC 피어링 불필요 |

로그를 Grafana에서 읽는 것만으로 같은 로그를 다시 ingest하거나 저장소를 복제하지 않는다. 또한 Grafana 화면의 새로고침은 Prometheus의 30초 메트릭 수집 주기를 바꾸지 않으므로 그 자체로 피어링 수집량이 늘지는 않는다.

### 서울 리전 로그 단가와 산식

공개 가격표 게시일 `2026-10-07T11:55:40Z`, 재조회 `2026-10-21 KST`. 기존 CloudWatch Logs Insights `StartQuery` 요율을 기준으로 한다. 가격표에 함께 있는 Omni 등 별도 모드의 단가를 이 계산에 섞지 않는다.

| 항목 | 단가·무료 구간 | 월 계산 |
| --- | --- | --- |
| Standard 앱 로그 ingest | $0.76/GB, `APN2-DataProcessing-Bytes` | 유효 과금 ingest GB × 0.76 |
| 로그 보관 | $0.0314/GB-month, `APN2-TimedStorage-ByteHrs` | 압축·시간가중 저장량 × 0.0314 |
| Logs Insights 검색 | $0.0076/GB, `APN2-DataScanned-Bytes` | 모든 실행의 과금 스캔 GB 합계 × 0.0076 |
| Live Tail | 무료 1,800분/월, 초과 $0.01/분. `Global-Logs-LiveTail`, `APN2-Logs-LiveTail` | max(합산 세션 분 − 적용 가능한 무료 분, 0) × 0.01 |

무료 사용량은 개인별로 1,800분씩 있다고 가정하지 않는다. 같은 계정의 다른 사용량·청구 합산 범위·잔여 무료 구간을 확인한다. Logs Insights 예시는 무료 구간을 차감하지 않은 보수적 금액이고, Live Tail 표는 월 1,800분이 전부 남아 있다는 조건을 명시한다. 기존 로그 ingest·보관료는 조회 방식과 별도로 계속 발생한다. [서울 공개 가격표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/ap-northeast-2/index.json), [CloudWatch 요금](https://aws.amazon.com/cloudwatch/pricing/)

#### Logs Insights/Grafana 조회 예시

한 번의 검색이 스캔하는 양은 **선택한 모든 그룹과 시간 범위의 합계**다. 예시 MB/GB는 10진 단위로 단순 계산하며 실제 운영에서는 응답의 `statistics.bytesScanned`와 청구 사용량으로 보정한다.

| 가정 | 월 조회 수 | 월 스캔량 | 조회료 |
| --- | ---: | ---: | ---: |
| 개발자 5명 × 하루 20회 × 22일, 1회 100MB | 2,200 | 220GB | $1.67 |
| 같은 횟수, 1회 1GB로 조회 범위 확대 | 2,200 | 2,200GB | $16.72 |
| 화면 1개, 하루 8시간 × 22일, 30초 갱신, 매번 100MB | 21,120 | 2,112GB | $16.05 |
| 같은 화면을 5명이 각각 조회, 캐시 공유 없음 | 105,600 | 10,560GB | $80.26 |

자동 갱신 예시는 **화면당 쿼리 하나**, 최초 로딩·재시도 제외다. 독립 쿼리 패널이 여러 개면 실행 수를 더하고 실제 캐시 효과는 측정 전 절감액에 넣지 않는다. 30초마다 최근 15분을 조회하면 겹치는 구간도 반복 스캔될 수 있다. 일반적인 `limit 100`은 반환 건수 제한이므로 스캔 비용 상한으로 간주하지 않는다. 조회 그룹·시간 범위를 줄이고 상시 자동 갱신을 피하는 것을 기본값으로 한다. [AWS 쿼리 비용 지침](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)

#### Live Tail 예시

각 사람이 별도 세션 하나를 연다는 가정이다. 한 세션에서 BE·AI 두 그룹을 선택했다는 이유만으로 세션 분을 두 배로 계산하지 않는다. 여러 세션을 열면 각 세션의 실행 시간을 합산한다.

| 사용 패턴 | 월 합산 세션 분 | 무료 1,800분 적용 시 | 무료 구간을 이미 소진했다면 |
| --- | ---: | ---: | ---: |
| 1명 × 하루 30분 × 22일 | 660 | $0.00 | $6.60 |
| 5명 × 하루 15분 × 22일 | 1,650 | $0.00 | $16.50 |
| 5명 × 하루 30분 × 22일 | 3,300 | $15.00 | $33.00 |
| 5명 × 하루 합계 8시간 × 22일 | 52,800 | $510.00 | $528.00 |

마지막 행은 3시간 세션 종료 후 다시 연결해 하루 합계 8시간 사용하는 비용 민감도 예시다. 실제로 한 세션을 8시간 유지할 수 있다는 뜻이 아니다. 짧은 배포 확인과 상시 표시의 비용 차이가 크므로 작업 종료 시 세션도 종료한다. [Live Tail 요금](https://aws.amazon.com/cloudwatch/pricing/)

### 피어링: 실제 메트릭 크기 기반 추정

연결 자체의 시간당 고정비는 없으며 같은 AZ 내 전송은 무료다. 동일 리전의 서로 다른 AZ 간 전송은 양 끝에 각각 $0.01/GB가 적용돼, 한 방향으로 1GB를 전송할 때 합계 약 $0.02다. 요청과 응답의 바이트를 모두 합산하되 같은 전송을 다시 왕복 두 배로 계산하지 않는다. [AWS VPC 요금](https://aws.amazon.com/vpc/pricing/), [AWS Peering 안내](https://docs.aws.amazon.com/vpc/latest/peering/what-is-vpc-peering.html)

10월 20일 최종 확인에서 BE·AI는 2a, 모니터링 EC2는 2c였다. BE 응답 32,142 bytes + AI 응답 2,348 bytes = 합계 34,490 bytes/회라는 순간 측정을 사용한다.

```text
30일 수집 횟수 = 30 × 24 × 60 × 60 / 30초 = 86,400회
응답 본문 = 34,490 × 86,400 / 1,000,000,000 = 2.979936GB
전송료 추정 = 2.979936 × $0.02 = $0.05959872 ≈ $0.06/월
```

| 월 cross-AZ 전송량 가정 | 피어링 전송료 |
| --- | ---: |
| 약 2.98GB, 위 응답 본문 모델 | 약 $0.06 |
| 10GB | $0.20 |
| 100GB | $2.00 |
| 1,000GB | $20.00 |

현재 추정은 task가 BE·AI 각 1개이고 응답 크기와 주기가 유지된다는 조건이다. HTTP 요청·헤더·TCP overhead, 지표 증가, 재시도, task 증가·AZ 변경은 별도다. 실제 청구 단위와 측정도 보정해야 한다. 기존 모니터링 EC2/EBS 비용, 로그 ingest·보관·검색료를 포함한 전체 모니터링 비용으로 `$0.06`을 인용하지 않는다.

### 팀 권고와 이후 결정

1. **지금:** CloudWatch 그룹 단위 검색과 Live Tail로 개발 로그를 확인한다. 스트림을 매번 고르지 않도록 BE·AI 검색 경로를 공용 안내에 둔다.
2. **다음 구성 제안:** 기존 Grafana에 CloudWatch datasource와 `[DEV] 로그` 화면을 추가한다. 서비스 선택, 기본 최근 15분, 키워드·에러 검색, 앱 컨테이너 필터, 관련 메트릭 화면 이동을 준비한다. 기본 자동 갱신은 끈다.
3. **배포·재현 중:** 필요한 시간에 Live Tail을 사용하고 종료한다. Grafana 재조회와 Live Tail을 모두 상시 켜두지 않는다.
4. **권한:** Grafana 호스트의 IAM role에 개발 그룹 조회 권한을 부여한다. 그룹별 제한을 지원하지 않는 API는 필요한 범위만 예외로 기록한다. AWS 키를 개발자나 설정 파일에 배포하지 않는다. 대시보드의 DEV 필터는 보안 경계가 아니므로 실제 IAM·Grafana 조직/데이터소스 접근 범위를 검증한다. [Grafana CloudWatch 설정](https://grafana.com/docs/grafana/latest/datasources/aws-cloudwatch/configure/)
5. **측정:** 1주간 그룹별 ingest, query bytes scanned, 세션 사용 분, 동시 조회자, Grafana 자원, 조사 소요시간을 기록해 월 예상액을 다시 계산한다. 로그 보존은 현재 30일을 그대로 두며 7일 단축은 별도 결정이다.
6. **V1/V2 전환:** 로그 그룹 이름의 버전과 환경을 혼동하지 않는다. V2가 운영이 되면 화면·IAM·경보의 환경 의미를 함께 바꾼다. 개발만 CloudWatch로 단순화해도 기존 운영 관측을 대체하기 전에는 공유 모니터링 EC2 전체를 제거할 수 없다.

문서에 기록한 권고는 Grafana 로그 연동이나 새 유료 서비스의 적용 완료를 의미하지 않는다. 추가 구현 범위, 팀 접근 권한, 월 예산은 구현 전에 확정할 사항이다.
