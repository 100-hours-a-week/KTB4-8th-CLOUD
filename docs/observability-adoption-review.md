# KeepGo 옵저빌리티 도입 검토와 단계별 실행안

작성일: 2026-10-16 · 갱신: 2026-10-21(6절 로그 실측 비용·ECS 기준 스택 비교·Sentry 릴리즈 연결 추가) · 상태: **검토 제안, 운영 적용 전**

## 1. 제안

**지금 가장 효과가 큰 투자는 요청 식별자·구조화 로그·오류 분류를 기존 도구에 일관되게 적용하는 것이다. 이후 V2의 BE → AI → 큐 → Worker 경로에 OpenTelemetry 분산 추적을 도입한다.**

KeepGo에는 이미 CloudWatch Logs, Prometheus·Grafana, AI Sentry와 LangSmith 연동이 있다. 각 도구에서 같은 요청과 배포를 찾아갈 수 있도록 만드는 작업을 먼저 한다. Loki·Tempo·ELK를 한꺼번에 운영하는 안은 현재 단계에서 보류한다. 도구별 비교와 실측 비용은 6절에 있다.

| 우선순위 | 도입·개선 | 얻으려는 결과 | 감수할 비용 |
| --- | --- | --- | --- |
| P0 | 공통 요청 ID, JSON 로그, 환경·버전 식별, 오류 분류 | 오류 하나에서 발생 환경·요청·기능·원인 후보를 바로 찾음 | FE·BE·AI 간 계약과 코드 수정 |
| P0 | 기존 알림의 실제 수신·복구 시험, 관측 기능 실패 격리 | 모니터링은 켜져 있는데 장애를 놓치거나 앱을 죽이는 상황 방지 | 시험·담당자·운영 절차 유지 |
| P1 | AI 제공자·영상별 결과 메트릭, LangSmith 정보 정리 | API 200이어도 영상 분석이 실패한 상황, 재시도·비용 증가 감지 | 의미 있는 계측 구현과 데이터 수집량 증가 |
| P1 | Grafana에서 CloudWatch 로그 조회, 배포·설정 변경 이력 연결 | 지표에서 로그·변경 이력까지 조사 동선 단축 | 조회 권한과 Logs Insights 비용 |
| P2 | OpenTelemetry로 V2 핵심 경로 추적, AWS 관리형 저장소부터 시험 | 큐 대기·처리·외부 호출·결과 전달 중 어디서 지연됐는지 식별 | Collector/SDK 운영, 샘플링·비용·전파 검증 |
| 조건부 | FE·BE Sentry 확대, LLM 품질 평가, 관리형 관측 플랫폼 전환 | 실제 장애·품질 문제에 따라 관측 범위 확대 | 추가 과금, 개인정보 관리, 기존 계측과 중복 |

성공 기준은 도구 수가 아니라 **“이 요청이 어디서, 어떤 버전으로, 무엇 때문에 실패했는지 설명하는 데 걸리는 시간”**이다. 아래 수집률·보존 기간·일정은 시작 제안이며, 현재 트래픽이나 팀의 합의된 SLO로 간주하지 않는다.

## 2. 검토 근거와 현재 상태

Cloud 작업 트리의 기준 커밋은 `11734d4868b9d20e82d4d13f5dc42b23535d3619`다. V2는 [모니터링 전체 안내](monitoring-overview.md)가 고정 커밋으로 연결한 Terraform 정의를 기준으로 검토했다. AI는 10월 13일 배포 manifest에 기록된 `6e9c5cf7b2993238b613804fb1a6fdd7bf04657b`의 코드도 확인했다. manifest의 목표 버전과 당시 실행 컨테이너 버전은 동일하다고 단정하지 않는다.

| 항목 | 확인한 근거 | 아직 확인하지 못한 것 |
| --- | --- | --- |
| V1 로그 | 이번 조사에서 `/keepgo/v1/application` 조회 가능, 보존 14일 확인 | Sentry 오류와 CloudWatch 로그가 항상 일대일로 연결되는지 |
| Prometheus·Grafana | 전용 EC2, BE·AI 기본 HTTP 및 BE JVM/Hikari 수집의 10/01~02 적용 기록 | 현재 전체 타깃 상태, 모든 알림의 firing→resolved 수신 |
| 메트릭 보관 | [Compose](../compose.monitoring.yaml)는 시간 7일·크기 2GB 제한 | 실제 보관 기간. 용량 제한에 먼저 도달하면 7일보다 짧아질 수 있음 |
| AI 상세 지표 | 제공자 오류·TTFT 계약과 대시보드는 존재 | [현황 문서](monitoring-overview.md)상 제공자·토큰·TTFT 계측 완료 근거 없음 |
| Sentry | AI 초기화 코드와 사용자가 제공한 오류 이벤트 | 해당 이벤트의 환경·서버·배포 버전, FE·BE 현재 적용 상태 |
| LangSmith | [compose.yaml](../compose.yaml)에 `LANGSMITH_TRACING=true`; AI 코드에 키가 있을 때 활성화하는 로직 | 실제 수집률, 입력·출력 마스킹, 보존·과금, 실패/취소 run 완결성 |
| V2 | ECS awslogs·Container Insights·CloudWatch 경보 Terraform, 이번 조사에서 V2 로그 그룹 존재 확인 | 각 활성 서비스 지표·로그 유입, SNS 수신, V1 Prometheus와의 연결 |

문서 간 시점 차이가 있다. 예를 들어 과거 체크리스트의 “LangSmith 전달하지 않음”은 현재 Compose·런타임 준비 코드와 다르다. [전체 안내](monitoring-overview.md), [적용 기록](v1-implementation-status.md), 실제 설정을 함께 보고 판단해야 한다. 이번 검토에서 Grafana·Sentry·LangSmith 관리 화면과 청구서는 재검증하지 않았다.

### 이번 영상 분석 오류가 보여준 공백

10월 13일 UTC 01:14의 `GooglePermissionDeniedError`를 조사하면서 시간대, API 키 변경, Terraform 작업, 발생 환경을 각각 확인해야 했다. 사용자가 최종적으로 분석 대상이 비공개 영상이었음을 확인했다. Gemini의 YouTube URL 입력은 공개 영상만 지원한다. [Google 영상 입력 문서](https://ai.google.dev/gemini-api/docs/video-understanding?hl=en)

이 조사에서 확인한 사실은 다음과 같다.

- 오류보다 앞서 V2 인프라 삭제 작업이 있었지만, V1 운영 Secret의 수정 기록과는 별개였다.
- V1 로그에는 UTC 01:03의 Gemini 성공 기록이 있었고, 조회한 01:00~01:30 구간에는 해당 영상 분석 오류가 없었다.
- 따라서 “비공개 영상이었다”는 원인 확인과 별개로, **제공된 오류 이벤트가 어느 실행 환경에서 발생했는지 연결하는 문제는 남았다.**

옵저빌리티가 비공개 여부를 자동으로 알아내 주지는 않는다. 대신 기능명·안전한 영상 식별자·요청 ID·실행 환경·외부 오류 코드를 함께 남겨 원인을 확인할 근거를 제공해야 한다. `403`만 보고 모든 오류를 비공개 영상으로 분류하면 실제 API 권한 장애를 숨기게 된다.

## 3. 먼저 도입할 공통 관측 계약

### 요청과 작업의 식별

초기에는 `request_id`를 공통으로 사용하고, OpenTelemetry를 붙인 구간에는 `trace_id`·`span_id`를 추가한다. 요청 ID를 trace ID인 것처럼 사용하지 않는다.

| 필드 | 용도 | 규칙 |
| --- | --- | --- |
| `timestamp` | 발생 시각 | UTC ISO 8601, `Z` 명시. 화면에서 KST 변환 가능 |
| `service`, `environment` | 발생 서비스·환경 | 허용 목록 사용. V1/V2와 dev/prod를 별도 구분 |
| `release`, `deployment_id` | 실행 버전·배포 | 실제 주입된 이미지 SHA/배포 ID. 브랜치 이름만 기록하지 않음 |
| `request_id` | HTTP 요청 연결 | 신뢰 경계에서 생성·검증하고 BE→AI로 전달, 사용자 오류 화면에도 표시 |
| `trace_id`, `span_id` | 분산 호출 구간 연결 | OTel 컨텍스트에서 추출. 미계측이면 빈 문자열 대신 필드 생략 |
| `job_id`, `attempt` | V2 비동기 작업·재시도 연결 | job은 유지, 처리 시도는 별도 구분 |
| `operation`, `stage` | 업무와 실패 단계 | `video_analysis`, `provider_call`, `parse_result` 등 제한된 값 |
| `error_code`, `provider_status` | 앱 분류·외부 응답 | 원본 403은 보존하되 업무 오류 코드와 분리 |
| `sentry_event_id`, `langsmith_run_id` | 도구 간 이동 | 해당 이벤트가 생성됐을 때만 기록 |

외부에서 받은 식별자는 길이·문자 형식을 검증한다. trace context를 전달하더라도 인증 정보로 신뢰하지 않으며, 외부의 샘플링 요청을 무제한 비용 증가로 연결하지 않는다. 같은 이름의 환경 필드를 Sentry·LangSmith·로그·대시보드에서 일관되게 사용한다.

**로그는 한 이벤트를 한 줄 JSON으로 출력한다.** 스택은 JSON 문자열 안에 넣고, 별도의 request completion 이벤트를 남겨 성공·실패·취소를 검색할 수 있게 한다. 프레임워크 access log와 중복되는 기록은 수집량을 측정한 뒤 줄인다.

```json
{
  "timestamp": "2026-10-16T01:14:00Z",
  "level": "ERROR",
  "event": "provider_call_failed",
  "service": "ai-api",
  "environment": "production",
  "release": "example-image-sha",
  "request_id": "example-request-id",
  "operation": "video_analysis",
  "stage": "provider_call",
  "provider": "google",
  "model": "gemini-3.8-flash",
  "provider_status": 403,
  "error_code": "provider_permission_denied",
  "classification_basis": "provider_response_only",
  "video_ref": "example-opaque-reference",
  "attempt": 1
}
```

위 예시는 이번 사고의 실제 로그가 아니다. 영상의 공개 상태를 확인하지 못한 시점의 기록 예시다. 확인 후에는 별도 조사 기록에 `cause=video_not_public`, `evidence=user_confirmed`를 남길 수 있다. 일반 403 응답에서 이 원인을 자동 추론하지 않는다.

영상 원본 URL 대신 내부 참조 ID를 기본값으로 사용한다. 원본 URL이 꼭 필요하면 접근 제한이 있는 업무 데이터에서 역조회한다. URL 쿼리·토큰·프롬프트·사용자 위치는 기본 로그에서 제외한다. `send_default_pii=False`만으로 사용자 정의 로그와 LLM 입력 전체가 자동 비식별화된다고 보지 않는다.

### 오류 분류와 대응의 분리

아래는 새로운 도메인 코드 제안이며 현재 구현된 API 계약이 아니다. FE·BE·AI가 응답 규약을 맞춘 후 적용한다.

| 분류 | 판정 근거 | 사용자 처리 | 운영 처리 |
| --- | --- | --- | --- |
| `video_not_public` | 공개 상태를 신뢰할 수 있게 확인 | 공개 영상 요청, 자동 재시도 중단 | 건수·비율 추적. 개별 건 긴급 알림 제외 |
| `provider_permission_denied` | 403이지만 원인 불명 | 일반 실패 안내·문의 ID | 오류 상세 유지. 정상 시험 영상·다른 요청에서도 반복되면 조사 |
| `provider_rate_limited` | 제공자 429 | 대기·재시도 안내 | 제공자별 빈도·재시도 증폭·동시성 확인 |
| `provider_timeout` | 외부 호출 제한 시간 초과 | 실패 또는 지연 안내 | 큐 대기와 호출 지연을 분리 |
| `invalid_model_output` | JSON/스키마 파싱 실패 | 안전한 실패 처리 | 프롬프트·모델 버전별 증가 확인 |
| `cancelled` | 사용자 취소·연결 종료 확인 | 취소 상태 | 취소율과 취소 뒤 남은 LLM 비용 추적 |

오류 분류를 위해 YouTube 사전 조회를 매번 추가하면 지연·쿼터·외부 의존성이 늘고, 조회와 분석 사이 상태도 바뀔 수 있다. 초기에는 제공자 오류와 사용자 확인을 보존하고, 사전 검증의 효과는 실패 빈도를 보고 판단한다. 브라우저에서 재생된다는 사실만으로 Gemini 접근 성공을 보장하지 않는다.

## 4. AI 관측은 HTTP 성공률보다 깊게 본다

### 영상별 결과와 제공자 시도를 별도로 계측

확인한 [AI 배치 코드](https://github.com/100-hours-a-week/KTB4-8th-AI/blob/6e9c5cf7b2993238b613804fb1a6fdd7bf04657b/app/services/analyze_video.py)는 한 묶음의 Gemini 호출이 실패하면 묶음의 각 영상을 실패 결과로 반환한다. HTTP 응답만 성공해도 업무 결과는 전부 실패할 수 있고, 한 영상이 문제여도 나머지 영상의 실패 원인까지 같다고 단정할 수 없다.

따라서 측정 단위를 HTTP 요청, 논리 작업, 영상 항목, 제공자 호출 시도로 구분한다. 제공자 재시도 3회를 사용자 실패 3건으로 세지 않는다. V2 중복 전달에서는 최종 업무 결과가 중복 집계되지 않도록 상태 저장·멱등 처리와 계측 위치를 맞춘다.

| 지표 | 답하려는 질문 | 제안 |
| --- | --- | --- |
| 영상 결과 수·비율 | 몇 개가 실제 분석됐나 | `success / rejected / failed / cancelled`, 제한된 원인 분류 |
| 묶음 실패·부분 성공 | 하나의 실패가 얼마나 번졌나 | batch 크기·실패 항목 수, 로그에는 batch 참조 ID |
| 제공자 시도·지연 | Google 호출 자체가 불안정한가 | 기존 `keepgo_ai_provider_requests_total` 등 계약부터 구현·검증 |
| 논리 작업당 시도 수 | 재시도가 비용·부하를 키우는가 | 최초 호출과 retry를 구분 |
| 입력·출력 토큰, 비용 추정 | 성공 한 건에 얼마가 드나 | 사용량 응답 기반, 모델·가격표 버전·추정값 표시 |
| 결과 파싱·품질 | HTTP 200 결과를 사용자가 쓸 수 있나 | 스키마 유효율, 장소 추출 누락, 평가 데이터셋 정확도 |
| 스트리밍 지연 | 사용자가 언제 첫 결과를 보나 | LLM 첫 토큰, 사용자 첫 유효 이벤트, 최종 완료를 구분 |

기존 [메트릭 계약](monitoring-metrics-contract.md)을 확장하고 대시보드·알림을 같이 수정한다. 지표 label에 `request_id`, `job_id`, 사용자 ID, 영상 URL, 전체 오류 문구를 넣지 않는다. 세부 식별자는 로그·trace에 둔다. label 조합마다 시계열이 늘어나기 때문이다. [Prometheus 계측 지침](https://prometheus.io/docs/practices/instrumentation/)

### LangSmith는 유지하되 목적을 명확히 한다

LangSmith는 이미 활성화 경로가 있으므로 신규 도입보다 사용 상태 점검이 먼저다. AI 내부의 프롬프트·모델·도구 호출·파싱 단계 조사와 평가에 사용하고, 인프라·큐·BE까지 연결하는 분산 추적과는 역할을 나눈다. LangSmith의 trace/run 구조는 LLM 실행 과정을 살펴보는 데 유용하다. [LangSmith 관측 개념](https://docs.langchain.com/langsmith/observability-concepts)

초기 개선 범위는 환경·release·request/job ID 메타데이터, 프롬프트 버전, 취소·timeout run 종료 상태, 입력·출력 마스킹이다. 원문 전체를 항상 저장하면 디버깅은 쉬워지지만 비용과 민감 데이터 노출이 커진다. 기본은 내용 숨김 또는 정제된 필드만 수집하고, 재현이 필요한 제한된 시험 데이터에서 상세 내용을 켠다. SDK의 입력·출력 숨김과 마스킹 기능을 검토한다. [LangSmith 민감 정보 제어](https://docs.langchain.com/langsmith/mask-inputs-outputs)

LLM 품질 평가는 먼저 고정 시험셋으로 시작한다. 정상 공개 영상, 비공개 입력의 실패 처리, 장소 없음, 여러 장소, 해외 영상, 구조화 응답 실패를 포함한다. 주관적인 모델 confidence를 실제 정확도로 간주하지 않는다. 모든 운영 요청에 별도 LLM 평가를 붙이는 안은 평가 호출 비용·지연·평가 편향 때문에 보류한다.

## 5. 분산 추적: V2에서 OpenTelemetry 도입

V1은 요청 ID와 구조화 로그만으로도 큰 개선이 가능하다. V2에서 서비스와 비동기 경계가 늘어나면 요청 ID만으로 각 단계의 소요 시간을 재구성하는 비용이 커진다. 이때 OpenTelemetry(OTel)로 호출 구간인 span을 기록한다. **OTel은 계측·전송 표준이며 저장소나 대시보드 자체는 아니다.**

최초 범위는 영상 분석 한 경로로 제한한다. BE 수신, AI 요청, 큐 전송, Worker 처리, Gemini 호출, 결과 저장·통지 중 실제 활성화된 단계만 계측한다. Spring과 Python의 자동 계측을 출발점으로 삼되, 업무 단계와 배치의 결과는 수동 span/이벤트로 보완한다. 기존 Micrometer 지표를 OTel로 동시에 중복 전송하지 않는다.

### 추적 저장소 선택

| 후보 | 장점 | 트레이드오프 | KeepGo 판단 |
| --- | --- | --- | --- |
| OTel → AWS 관리형 추적 | 기존 AWS 권한·로그·운영 경로 활용, 저장소 서버 관리 감소 | AWS 조회 방식·과금에 의존, 계측 경로별 수집·색인 비용 확인 필요 | **첫 PoC 권장** |
| OTel → Grafana Cloud | 기존 Grafana 경험 활용, 관리형 trace·로그·지표 통합 가능 | 외부 SaaS 데이터 전송·쿼터·좌석/플랜 검토, 기존 도구와 비용 중복 | AWS PoC에서 조회 편의·비용이 불리하면 비교 |
| OTel → 자체 Tempo | 저장·보존·구성 통제, Grafana 연계 | 저장소·업그레이드·용량·장애 대응을 팀이 소유 | 운영 담당 여력이 확보되면 재검토 |
| Sentry 중심 추적 확대 | 오류에서 성능 조사로 이어지는 동선 | SDK/OTel 연동·언어별 지원 검증, span 중복·과금, 업무 큐 경계 별도 계측 | FE·BE 오류 도입과 함께 좁게 검증 |
| 통합 상용 APM으로 전환 | 통합 화면과 관리 부담 감소 기대 | 에이전트·기존 대시보드 전환, 호스트/수집량/보존 비용 | 현재는 전환 효과를 입증할 장애·운영 비용 자료 부족 |

AWS PoC에서는 **OTel SDK → Collector → AWS 추적 저장소 한 경로**만 검증한다. OTLP endpoint와 필요한 인증·Transaction Search 설정, 서울 리전 지원, 요금 적용 범위를 확인한다. Application Signals까지 자동으로 전부 활성화하는 것을 전제하지 않는다. [AWS OTLP endpoint](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPEndpoint.html), [AWS OTel 설정 안내](https://docs.aws.amazon.com/en_en/AmazonCloudWatch/latest/monitoring/GettingSetup.html)

X-Ray SDK·daemon을 새로 도입하는 안은 권장하지 않는다. AWS 공식 문서는 2026-02-25부터 해당 SDK·daemon의 유지보수 모드와 OTel 전환을 안내한다. 이는 **X-Ray 저장 서비스 자체의 폐기와는 다른 이야기**다. [AWS 지원 일정](https://docs.aws.amazon.com/xray/latest/devguide/xray-sdk-daemon-timeline.html)

### 비동기·재시도·SSE에서 끊기지 않게 하기

- HTTP에는 W3C `traceparent`를 전파한다. SQS 메시지에는 허용한 추적 메타데이터와 `job_id`를 함께 실어 Worker에서 복원한다. 자동 계측만으로 전파된다고 가정하지 않는다.
- 오래 대기하는 작업은 HTTP span을 계속 열어 두지 않는다. 생산자와 소비자 span을 연결하고, 재시도·다중 입력은 span link와 `job_id`로 추적한다. 어떤 경계를 같은 trace로 묶을지는 실제 처리 시간을 보고 정한다.
- 큐 대기 시간, 처리 시간, 재시도 횟수, 최종 결과 전달 시간을 각각 측정한다. SQS oldest age만으로 개별 작업의 전체 지연을 대신하지 않는다.
- SSE는 연결 수, 첫 유효 이벤트까지의 시간, 완료·끊김·재연결을 측정한다. 토큰마다 span을 만들지 않고, 장시간 연결의 세부 이벤트도 제한한다.
- AI 오류는 한 경계에서 Sentry로 수집하고 BE에서는 같은 `error_id`로 연계한다. 여러 서비스가 같은 예외를 별개 장애처럼 중복 발송하지 않게 한다.

### 샘플링 선택

| 방식 | 장점 | 놓치는 것·운영 부담 |
| --- | --- | --- |
| 시작 시 일정 비율 선택(head sampling) | SDK·전송량부터 줄일 수 있고 운영이 단순 | 완료 후 발생할 오류·지연을 미리 알 수 없어 오류 trace도 누락 |
| 수집 후 오류·지연 중심 선택(tail sampling) | 수집된 trace 중 중요한 실패를 우선 보존 | Collector 메모리·대기 시간·동일 trace 라우팅 필요, 늦게 도착한 span 처리 어려움 |
| 짧은 기간 전수 수집 | 저트래픽 시험에서 가장 설명하기 쉬움 | 트래픽 증가 시 비용·민감 정보·처리량 부담 |

PoC는 개발 환경의 제한된 트래픽을 전수 수집하고, 운영 시험은 우선 10% head sampling을 가설로 삼는다. 저트래픽으로 표본이 부족하면 특정 기능·기간의 수집률을 높인다. **head에서 버린 trace를 tail에서 복구할 수 없으므로 “정상 10%, 오류 100%”를 head sampling만으로 보장하지 않는다.** Sentry 오류 이벤트·업무 실패 로그의 수집 정책은 trace 샘플링과 분리한다. tail sampling도 Collector 용량 초과·전송 실패가 있으면 무손실을 보장하지 못한다. [OTel 샘플링 설명](https://opentelemetry.io/docs/concepts/sampling/)

## 6. 로그 저장소는 유지하고 조사 동선을 줄인다

**CloudWatch Logs를 유지하고 Grafana에 CloudWatch 데이터 소스를 연결하는 것을 우선 권장한다.** 기존 로그를 다시 Loki로 보내지 않아도 지표 화면에서 로그 조회로 이동할 수 있다. 실제 사용하는 Grafana 버전의 지원·권한을 검증한다. CloudWatch 데이터 소스는 로그·지표를 지원하며 trace는 별도 데이터 소스를 사용한다. [Grafana CloudWatch 문서](https://grafana.com/docs/grafana/latest/datasources/aws-cloudwatch/)

### 검토 배경: 개발 측의 로그 조회 불편

2026-10-21 개발 측에서 “로그를 보기 어렵다”는 의견이 나와 Loki·Alloy·Tempo·Pyroscope와 Datadog 같은 통합 상용 APM을 다시 검토했다. 불편에는 원인이 섞여 있으므로 저장소 선택과 분리해서 본다.

| 원인 | 현재 상태 | 저장소 교체로 해결되는가 |
| --- | --- | --- |
| 조회 위치 | 로그는 CloudWatch에만 있고 Grafana 데이터 소스는 [Prometheus 하나](../monitoring/grafana/provisioning/datasources/prometheus.yml) | Loki 도입과 CloudWatch 데이터 소스 연결 모두 해결 |
| 검색·연결 | 비정형 로그, 요청 ID 없음 | 해결되지 않음. 3절 공통 관측 계약 필요 |
| 환경 구분 | V1 `/keepgo/v1/application`, V2 `/keepgo/v2/*`로 나뉘고 dev/prod 식별이 없음([전체 안내](monitoring-overview.md) 5절) | 해결되지 않음. `environment` 필드·label 정리 필요 |

### 로그 사용량과 비용 실측

2026-10-19 서울 리전의 CloudWatch `IncomingBytes`(9/19~10/19 합계), 로그 그룹 `storedBytes`, AWS Pricing API 단가를 조회했다.

| 항목 | 값 |
| --- | --- |
| V1 `/keepgo/v1/application` 30일 유입 | 약 114.9MB. 저장량 12.4MB(보존 14일) |
| V2 `backend`·`ai-api` 30일 유입 | 약 1.6MB. `sse`·`worker` 저장량 0 |
| 로그 수집 단가 (Standard / Infrequent Access) | $0.76/GB / $0.38/GB |
| Logs Insights 스캔 단가 | $0.0076/GB |
| 모니터링 EC2 단가 (t4g.small / t4g.medium) | $0.0208/h / $0.0416/h |

- **CloudWatch:** 월 약 0.12GB × $0.76 ≈ $0.09다. V1 14일분 전체를 한 번 스캔해도 약 $0.0004다. 무료 구간(로그 수집·보관·Insights 스캔 합산 월 5GB)은 계정 단위이므로 같은 계정의 다른 로그와 나눠 쓴다. [CloudWatch 요금](https://aws.amazon.com/cloudwatch/pricing/)
- **Loki 자체 운영:** 모니터링 EC2(t4g.small, 2GiB)에는 Prometheus 512MiB·Grafana 512MiB·Caddy 128MiB 상한이 걸려 있고, [Grafana 메모리 상한 사례](troubleshooting/2026-10-01-grafana-memory-limit.md)가 있다. 같은 호스트에 Loki를 올리려고 medium으로 바꾸면 월 약 $15(730시간 × $0.0208 차액)가 늘어난다.
- **손익분기:** $15 ÷ $0.76/GB ≈ 20GB, 무료 구간을 더하면 월 약 25GB 유입이다. 현재 유입의 약 200배이며 운영 시간은 포함하지 않았다.

“Loki가 CloudWatch보다 싸다”는 월 수십 GB 이상에서 성립하는 비교다. 현재 규모에서 판단 기준은 비용보다 **조회 사용감과 운영 부담**이다. “오픈소스이므로 무료”를 근거로 전환하지 않는다. 유입량이 늘면 위 손익분기를 다시 계산한다.

### ECS 기준 도구별 비교

V2를 기준으로 비교하고, 전환 작업량은 제외해 운영 상태만 본다. V2는 Fargate가 아니라 EC2 capacity provider를 쓰는 ECS다([services.tf](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/blob/92adfbc4fd7361412beb9eb1211e45610516bba0/infrastructure/terraform-v2/services.tf)의 `requires_compatibilities = ["EC2"]`). 따라서 수집기는 task별 사이드카 대신 호스트마다 하나를 띄우는 daemon 서비스로 둘 수 있다.

네 도구는 같은 역할을 두고 경쟁하지 않는다. Prometheus·Grafana는 어느 조합에서나 유지한다.

| 역할 | 답하는 질문 | AWS 기본 | Grafana 계열 |
| --- | --- | --- | --- |
| 로그 저장·검색 | 그때 무슨 일이 있었나 | CloudWatch Logs | Loki |
| 수집기 | 데이터를 어떻게 옮기나 | `awslogs` 드라이버, FireLens(Fluent Bit), ADOT Collector | Alloy |
| 분산 추적 | 요청이 어느 구간에서 느렸나 | OTel → AWS 관리형 추적(5절) | Tempo |
| 프로파일링 | 어느 함수가 CPU·메모리를 쓰나 | 상시 수집 대안 없음. JFR·py-spy 수동 실행 | Pyroscope |

**로그: CloudWatch Logs vs Loki**

| 비교 | CloudWatch Logs | Loki |
| --- | --- | --- |
| ECS 연결 | task 정의의 `awslogs` 설정. 현재 구성 | Alloy가 Loki로 전송. Loki를 ECS 서비스나 별도 EC2에서 실행하고 S3에 저장 |
| 개발자 조회 | AWS 콘솔 또는 Grafana CloudWatch 데이터 소스. Logs Insights 문법 | Grafana Explore에서 label 선택·실시간 tail. **조회가 더 편함** |
| 지표 → 로그 이동 | Grafana에서 링크·변수를 직접 구성 | 같은 label 체계로 연결 |
| 장애 영향 | 관리형 | Loki 장애 동안 조회 불가, 수집기 버퍼 초과분 유실 |
| ECS 연동 | ECS 콘솔·배포 실패 화면에서 바로 로그 확인 | 없음 |
| 운영 | 보존 기간 설정 정도 | 보존·압축·업그레이드·용량 관리 |

**수집기: `awslogs`/FireLens vs Alloy.** Alloy는 로그·지표·추적·프로파일을 한 에이전트로 받아 Loki·Prometheus·Tempo·Pyroscope로 보낸다. CloudWatch만 쓰면 `awslogs`로 충분하다. Loki·Tempo·Pyroscope 중 하나를 채택하면 사실상 함께 들어오므로 **따로 선택하는 도구가 아니다.** OTel을 도입하는 9절 3단계에서 ADOT Collector와 함께 수집기 후보로 비교한다.

**분산 추적: AWS 관리형 vs Tempo.** 두 경우 모두 앱의 OTel 계측이 선행 조건이며, 계측이 없으면 Tempo는 빈 저장소다. 계측이 같으므로 차이는 저장 위치와 조회 화면이다.

| 비교 | AWS 관리형 추적 | Tempo |
| --- | --- | --- |
| 조회 | CloudWatch 콘솔 서비스 맵, Grafana 데이터 소스 | Grafana에서 trace → 로그 → 지표로 이동 |
| 운영 | 관리형, 사용량 과금 | S3·실행 자원·압축을 직접 운영 |
| 맞는 조합 | CloudWatch Logs | Loki |

로그와 추적은 같은 계열로 맞춰야 조사 동선이 짧다.

**프로파일링: Pyroscope.** 함수 단위 CPU·메모리 사용을 상시 저장해 과거 시점도 조회한다. 앱 SDK나 Alloy eBPF(호스트 권한 필요)로 붙인다. 현재 AI 지연의 대부분은 Gemini 응답 대기(I/O)라 CPU 프로파일에 드러나지 않는다. 로그·추적 선택과 독립적이므로 부하 시험에서 CPU 병목이 확인된 뒤 추가한다.

### 조합 비교와 판단

| 비교 | ① AWS 기본 + Grafana 조회 | ② Grafana 계열 자체 운영 | ③ Grafana Cloud 관리형 |
| --- | --- | --- | --- |
| 구성 | CloudWatch Logs + AWS 관리형 추적 + Prometheus, 화면은 Grafana | Loki + Tempo (+ Pyroscope) + Prometheus, 수집은 Alloy | ②와 같은 구성을 SaaS로 사용 |
| 개발자 사용감 | 보통. 저장 쿼리·대시보드로 보완 | 좋음 | 좋음 |
| 안정성 | 관리형 | 모니터링 호스트 장애가 곧 관측 공백 | 관리형 |
| 운영 부담 | 낮음 | 높음 | 낮음 |
| 현재 규모 비용 | 거의 $0 | 실행 자원 고정비 | 무료 구간 확인 필요, 초과 시 사용량 과금 |
| 데이터 위치 | AWS 내부 | AWS 내부 | AWS 외부. 로그 개인정보·마스킹 검토 필요 |
| ECS 연동 | 기본 제공 | 직접 구성 | 수집기 전송 구성 |

**①을 기본으로 한다.** 트래픽이 작고 관측 시스템 전담 운영자가 없으며, ECS가 이미 CloudWatch 기준으로 동작하기 때문이다. Grafana CloudWatch 데이터 소스와 3절 공통 관측 계약을 적용한 뒤 2주간 개발 측 조회 경험을 확인한다. 불편이 남으면 ②가 아니라 ③을 비교한다. ②는 관측 운영 담당과 월 수십 GB 이상의 로그량이 생길 때 재검토한다.

ELK/OpenSearch는 복잡한 전문 검색 요구가 없고 클러스터·인덱스 관리 부담이 커서 제외한다. Datadog 같은 통합 상용 APM은 호스트·로그 수집·색인·APM을 따로 과금해 ECS task 증감에 따라 월 비용을 예측하기 어렵다. 조회 불편의 핵심인 요청 식별·구조화 로그 부재도 해결하지 않으므로 제외한다. 오류와 릴리즈·코드의 연결은 아래 Sentry 구성으로 충족한다.

### 조사 화면과 저장 쿼리

기본 조사 화면에는 환경·서비스·release 필터, 오류율·지연 그래프, request/job ID 로그 조회, Sentry·LangSmith 링크를 둔다. CloudWatch 조회 권한은 관측 전용 역할에 필요한 범위만 준다. Grafana 접속 권한이 원본 로그 열람 권한으로 확대된다는 점을 함께 검토한다.

구조화 로그 도입 후 다음과 같은 Logs Insights 쿼리를 저장할 수 있다. **기존 비정형 로그에서 바로 동작하는 쿼리는 아니다.**

```text
fields @timestamp, service, environment, operation, stage, error_code, provider_status
| filter request_id = "example-request-id"
| sort @timestamp asc
| limit 200
```

### 배포·설정 변경 이력

CD 성공·실패·롤백 이벤트에 서비스, 환경, 이전/새 이미지 SHA, deployment ID, 시작/완료 시각, 결과를 기록하고 Grafana annotation 또는 조회 링크로 연결한다. Git 커밋 시각은 실제 서버 반영 시각을 대체하지 않는다.

Secret은 **값이나 값의 해시를 로그에 남기지 않고**, 승인된 메타데이터인 Secret 이름·Version ID·컨테이너 적용 시각을 기록한다. AWS 수정 시각과 앱 반영 시각을 분리해야 “키는 바뀌었는데 앱이 아직 이전 값을 쓰는 상태”를 설명할 수 있다. Terraform 변경은 CloudTrail 이벤트·배포 실행 기록·대상 환경을 연결하되, 앱 오류와 시간이 가깝다는 이유만으로 원인으로 판단하지 않는다.

### 오류와 릴리즈·코드 연결

Sentry Releases와 GitHub 연동을 쓰면 오류 스택의 코드 줄 링크, 의심 커밋(Suspect Commits), 오류가 처음 나온 릴리즈와 재발, 환경별 배포 시각을 볼 수 있다. 통합 상용 APM에서 기대하는 “오류–릴리즈–코드” 연결과 같은 범위다. Prometheus·Grafana에서는 지표의 `version` label과 배포 annotation으로 “이 배포 이후 5xx 증가”까지 보고, 코드 줄 연결은 Sentry가 맡는다.

| 작업 | 담당 | 내용 |
| --- | --- | --- |
| 릴리즈 값 통일 | Cloud | 실행 이미지의 Git SHA를 `SENTRY_RELEASE`, `dev`/`production`을 `SENTRY_ENVIRONMENT`로 주입. [Sentry 정리](v1-sentry.md)의 AI 제안을 SHA 기준으로 확장하고 이미지 태그와 SHA의 1:1 대응을 확인 |
| 릴리즈 등록 | 각 앱 레포 CI | `sentry-cli releases new` → `set-commits --auto` → `finalize` |
| 배포 기록 | 중앙 CD | 배포 성공 후 `sentry-cli`로 해당 릴리즈의 환경별 deploy 기록 |
| 코드 매핑 | Sentry 관리자 | GitHub 연동, 레포별 stack trace 경로 매핑 |
| 언어별 준비 | AI·BE·FE | Python은 추가 작업 없음, Spring Boot는 SDK 추가, Next.js는 빌드 때 source map 업로드 |

이미 Sentry가 있는 AI부터 적용해 효과를 확인하고, BE·FE는 9절 기준대로 예외 수집 공백이 확인되면 확대한다. 팀 전체가 조회하려면 무료 플랜의 사용자 수 제한을 넘을 수 있으므로 도입 시점의 요금제를 확인한다.

## 7. 알림과 SLO는 사용자 작업 중심으로 설계

현재 health·CPU·5xx 알림은 유지하되, 영상 분석 성공·지연·결과 전달을 별도로 본다. `/health`는 매번 Gemini를 호출하지 않는다. 외부 의존성 문제로 모든 컨테이너를 재시작하는 상황을 피하고, 비용이 드는 기능 검사는 독립된 합성 요청으로 운영한다.

### 측정 지표와 분모

| 관점 | SLI 제안 | 주의점 |
| --- | --- | --- |
| 사용자 전체 경험 | 성공한 영상 수 / 제출 영상 수 | 비공개 입력도 사용자 실패 경험으로 별도 집계. 사라지게 하지 않음 |
| 서비스 신뢰성 | 정상 처리한 적격 작업 / 적격 작업 | 확인된 미지원 입력은 제외할 수 있으나 원인 불명 403을 임의로 제외하지 않음. 유효 입력의 외부 제공자 장애는 포함 |
| 분석 지연 | 접수부터 최종 결과까지의 분포·기한 내 완료율 | 실패·미완료를 빼고 성공 건 p95만 보면 장애 때 수치가 좋아질 수 있음 |
| 스트리밍 경험 | 첫 유효 이벤트·완료 지연, 중단율 | 연결 성공·HTTP 200을 완료로 간주하지 않음 |
| 처리 품질 | 정답이 있는 표본의 장소 추출 정확도·스키마 유효율 | 모델 자기평가와 구분, 인프라 SLO와 별도 관리 |

먼저 2주간 기준선을 수집해 요청량·지연 분포·정상 입력 비율을 본다. 99.9% 같은 목표는 사용자 기대·팀 대응 시간·실제 데이터 없이 확정하지 않는다. 30일 SLO를 채택하려면 현재 Prometheus의 **7일/2GB 보존**으로는 부족할 수 있으므로 장기 집계 저장이나 용량·보존 정책을 먼저 마련한다.

### 알림 정책 제안

| 상황 | 전달 | 조치 |
| --- | --- | --- |
| 확인된 비공개 영상 1건 | 사용자 안내, 대시보드 집계 | 운영자 긴급 호출 없음 |
| 원인 불명 403 반복, 정상 시험 영상도 실패 | AI 담당 경고, 영향이 지속되면 장애 알림 | 환경·release·키 버전·제공자 상태 조사 |
| 정상 입력 작업의 실패율 증가·결과 전달 정지 | 공용 장애 채널, 서비스 담당 | 사용자 영향 확인 후 복구 |
| 큐 지연·DLQ 증가 | Worker 담당 | 처리 속도·독성 메시지·재시도 확인 |
| 수집 끊김·알림 전달 실패 | Cloud 담당 | 앱 장애와 별개로 관측 경로 복구 |

최소 표본을 요구하는 비율 알림은 저트래픽 장애를 놓칠 수 있다. 반복 실패 건수와 제한된 합성 요청을 함께 사용한다. 합성 요청은 팀 소유의 안정적인 공개 시험 영상으로 수행하고, 배포 후 1회부터 시작한다. 주기적 실행은 호출 비용과 데이터 오염을 측정한 뒤 확대하며 `synthetic=true`로 실제 사용자 지표와 분리한다. 성공·실패·복구·NoData를 실제 수신까지 시험한다.

충분한 데이터가 모이면 짧은 구간과 긴 구간의 오류 예산 소모를 함께 보는 알림으로 발전시킨다. 같은 사용자 장애는 한 알림 경로를 주 경로로 정하고, Sentry 예외 알림과 Grafana 증상 알림이 중복 호출되지 않도록 담당·심각도·그룹 기준을 맞춘다.

## 8. 비용·보존·안정성의 트레이드오프

### 비용을 계산하는 방법

로그 유입량은 6절에서 실측했다. trace·SaaS 사용량과 청구서는 확인하지 않았으므로 그 외 확정 월 요금은 제시하지 않는다. 7일 사용량을 측정하고 서울 리전·실제 계약 단가로 계산한다. 로그 수집·보관·검색, trace 수집·색인·조회, SaaS 사용량, Collector 자원과 운영 시간을 별도로 본다. [CloudWatch 요금](https://aws.amazon.com/cloudwatch/pricing/), [Grafana Cloud 요금](https://grafana.com/pricing/), [LangSmith 요금](https://www.langchain.com/pricing/)

| 항목 | 산정에 필요한 값 |
| --- | --- |
| 로그 | 일 요청 수 × 요청당 이벤트 수 × 평균 이벤트 바이트 + health·시스템 로그, 보존 기간, 월 스캔 GB |
| trace | 일 요청 수 × 요청당 평균 span × 평균 span 바이트 × 보존 비율, 별도 색인·조회량 |
| 메트릭 | label 조합 수 × bucket 수 × task 수, scrape 주기, 보존·조회량 |
| LLM 관측 | LangSmith run/trace 수·보존·좌석, 평가용 모델 호출, 중복 저장량 |
| 자체 운영 | Collector/저장소 CPU·메모리·디스크·전송료, 월 유지보수 시간 |

계산 예시로 **일 10,000요청, 요청당 20 span, span당 1,000바이트, 월 30일**이면 전수 trace 원시량은 약 6GB, 10% 보존이면 약 0.6GB다. 이는 실제 트래픽이나 청구 단위가 아니며, 프로토콜·색인·압축·재시도 비용은 별도다. tail sampling으로 10%만 저장해도 Collector까지의 수집·처리량은 전수에 가까울 수 있다.

초기 보존안은 앱 로그 14일, V2의 기존 30일 정책은 별도 검토, 상세 trace 7~14일, 선택한 장애 증거는 정제 후 별도 보관이다. LLM 원문은 기본 수집을 최소화하고 필요한 재현 자료만 제한 보존한다. SaaS 요금제에서 기간 조절이 가능한지 확인한 뒤 적용한다. **수집률을 낮추는 것과 보존 기간을 줄이는 것은 서로 다른 비용 제어다.**

### 관측 시스템이 서비스를 방해하지 않게 한다

- SDK·Collector 전송은 비동기·제한된 큐·유한 timeout을 사용한다. 관측 저장소 장애가 사용자 요청의 동기 의존성이 되지 않게 한다.
- 버퍼가 가득 차면 데이터 유실과 요청 차단 중 선택해야 한다. 일반 진단 데이터는 서비스 지속을 우선하고 유실량을 계측한다. 필수 업무·감사 기록은 일반 telemetry와 별도 보장 경로를 설계한다.
- KeepGo는 과거 [잘못된 Sentry DSN으로 AI 기동 실패](troubleshooting/2026-09-30-ai-sentry-dsn-rollback.md)를 겪었다. 선택 관측 기능 초기화 실패를 격리하되, 조용히 꺼지지 않도록 별도 상태·알림을 남긴다.
- Collector 수신 거부·export 실패·queue 포화, Prometheus 디스크·수집 실패, Grafana 생존을 감시한다. 모니터링 호스트가 죽어도 외부 감시와 AWS 알림 중 검증된 경로가 남아 있어야 한다.
- V2 task 교체에 맞는 수집 대상 발견이 필요하다. V1의 고정 `app-host` 설정을 그대로 복사하지 않는다. task별로 수집하고 서비스 집계에서 중복·누락을 검증한다.

## 9. 실행 순서와 완료 기준

공수는 담당 파트가 병행할 수 있다는 가정의 대략적인 작업일이다. 확정 일정이 아니며 운영 배포·사용량 관찰 기간은 별도다. 새 저장소 계약보다 P0 개선을 먼저 완료한다.

| 단계 | 범위·담당 | 대략 공수 | 완료 기준 |
| --- | --- | --- | --- |
| 0. 현황 인수 | Cloud + 각 파트: 활성 환경·실제 이미지·관측 수신 경로·권한 확인 | 1~2인일 | 정상·실패 요청 1건씩 로그/오류 도구 연결, 알림 발생·복구 수신 증거 |
| 1. 식별·로그 | FE·BE·AI + Cloud: request ID, JSON, 환경·release, 오류 분류, 변경 이력 | 3~5인일 | 문의 ID 하나로 BE→AI 로그 조회. 입력 원문·키 미노출, 동시 요청 간 ID 혼선 없음 |
| 2. AI·조회 | AI + Cloud: 결과/제공자 지표, LangSmith 정리, Grafana CloudWatch 연결 | 3~5인일 | HTTP 200의 배치 실패 감지, 시도/작업 구분, 취소 run 정리, 로그 링크 동작 |
| 3. V2 추적 PoC | BE·AI·Worker + Cloud: 한 경로 OTel, AWS 저장소, 큐 컨텍스트 | 4~7인일 | 정상·지연·실패·재시도·task 교체에서 경로 확인, 수집 장애 시 앱 정상 |
| 4. 운영 평가 | 전 파트: 2주 기준선·비용·조사 시간 측정 | 관찰 2주 | 유지/확대/대안 전환 결정, SLO 초안·월 예산·보존 정책 합의 |

FE Sentry는 브라우저 오류·영상 입력 화면 실패를 서버 로그에서 재현하기 어려운 경우 우선 확대한다. BE Sentry는 예외 수집 공백이 확인되면 추가한다. 처음에는 오류 이벤트부터 검증하고 세션 리플레이·프로파일링·전면 성능 추적은 별도 필요가 생길 때 도입한다.

### 인수 시험 시나리오

| 시험 | 확인할 것 |
| --- | --- |
| 공개 영상 정상 분석 | 요청 ID → 업무 결과 → LLM 호출 연결, 성공 항목 수·지연 일치 |
| 비공개 영상 입력 | 확인된 입력 문제와 원인 불명 403 구분, 민감 URL 미노출 |
| 영상 묶음 일부 문제 | 묶음 호출 실패와 개별 영상 원인 구분, 성공률 중복 집계 없음 |
| 제한 환경의 403·429·timeout 모의 응답 | 분류·알림·재시도 정책 검증. 운영 키를 실제로 망가뜨리지 않음 |
| 큐 재전달·Worker 재시작 | job 연결 유지, attempt 구분, 최종 결과 중복 집계 방지 |
| SSE 취소 | 사용자 취소와 제공자 장애 구분, 남은 처리·비용 확인 |
| Collector·Sentry 전송 실패 | 앱 응답 유지, 유실/비활성 신호 확인 |
| 배포·롤백 | 실제 적용 버전과 annotation 일치, 이전/새 버전 오류 분리 |
| dev/prod 동일 오류 | 환경별 분리 검색·알림, 운영 통계에 개발 요청 미포함 |

초기 목표는 문의 ID를 받은 뒤 **5분 안에 환경·버전·실패 단계를 찾는 것**으로 제안한다. 실제 평균·중앙값 조사 시간을 먼저 기록하고, 기존 대비 개선 여부로 평가한다. 처리량·p95·메모리 변화는 동일 부하의 계측 전후 비교로 확인하고, PoC 시작 전에 허용 범위를 정한다.

## 10. 이번에 결정할 범위

1. P0는 기존 도구를 유지하면서 공통 관측 계약과 알림 인수를 진행한다.
2. AI 메트릭은 HTTP·영상 결과·제공자 시도를 분리한다. 일반 403을 비공개 영상으로 일괄 치환하지 않는다.
3. 로그는 CloudWatch를 유지하고 Grafana 조회 연결부터 검증한다. 2주 뒤에도 개발 측 조회 불편이 남으면 Grafana Cloud 관리형 Loki를 비교한다(6절).
4. V2 추적은 OTel과 AWS 관리형 저장소로 한 경로를 시험한다. 실측 결과가 불리하면 같은 계측을 기반으로 Grafana Cloud를 비교한다. Alloy는 이때 ADOT Collector와 함께 수집기 후보로 비교한다.
5. 오류와 릴리즈·코드 연결은 Sentry Releases로 AI부터 적용한다(6절).
6. Loki·Tempo·Pyroscope 자체 운영, ELK, Datadog 등 통합 상용 APM, 전 요청 LLM 평가, 세션 리플레이는 현재 도입 범위에서 제외하고 필요 조건이 생길 때 재검토한다. Pyroscope는 부하 시험에서 CPU 병목이 확인될 때 검토한다.

운영 반영 시에는 본 제안을 [메트릭 계약](monitoring-metrics-contract.md)·[알림 대응 절차](monitoring-alert-runbook.md)·[Sentry 정리](v1-sentry.md)에 반영하고, [구현·검증 현황](v1-implementation-status.md)에 실제 배포·수신 근거를 남긴다. 이 검토 문서 자체는 운영 적용 완료 기록이 아니다.
