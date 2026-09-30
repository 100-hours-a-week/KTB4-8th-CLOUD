# 앱 상세 메트릭 계약 v1 — 파트 전달용

2026-09-30. **클라우드 초안과 설정 구현 완료 / 앱 계측·운영 적용 미확인.** PG는 Prometheus + Grafana이며 Loki는 사용하지 않는다. 이 문서는 각 파트가 구현할 수 있는 기본값을 먼저 정한다. 확인이 필요한 항목은 7절에 모았다. 숫자는 초기 운영 가설이며 합의·검증된 SLO가 아니다.

## 1. 구현 경계와 파일

| 파일 | 역할 |
| --- | --- |
| `monitoring/prometheus/rules/application-recording.yml` | BE/AI 원본 지표를 공통 HTTP 지표로 집계 |
| `monitoring/prometheus/rules/application-alerts.yml` | 앱 임계치·최소 표본·지속 시간의 유일한 원본 |
| `monitoring/grafana/dashboards/application-http.json` | HTTP 요청률·4xx/5xx·p50/p95/p99·route·수집 상태 |
| `monitoring/grafana/dashboards/backend-runtime.json` | JVM heap·GC·스레드·Hikari 풀 |
| `monitoring/grafana/dashboards/ai-runtime.json` | AI 시도·오류·지연·TTFT·재시도·동시 요청·토큰 |
| `scripts/render-app-monitoring.py` | 위 대시보드와 Grafana 앱 알림 전달 규칙의 생성 원본 |
| `monitoring/examples/application-targets.json` | 등록 예시. 자동 수집되지 않음 |
| `monitoring/prometheus/targets/application.json` | 실제 활성 타깃. 기본 빈 배열 |
| `tests/prometheus/application.test.yml` | Prometheus 가짜 시계열을 사용한 규칙 동작 시험 |

앱 코드는 이 저장소에서 변경하지 않았다. BE/AI 이미지 게시 후 Cloud가 검증한 서비스만 타깃에 등록한다. 한 파트가 준비되지 않았다고 다른 파트까지 기다릴 필요는 없다. 타깃 추가 시 `service`, `metrics_contract=v1`, `__metrics_path__`를 예시대로 사용한다. `service`는 앱이 임의로 붙이는 label이 아니라 Cloud의 scrape 타깃 label이다.

## 2. 공통 수집·label·측정 규칙

수집/평가 30초, timeout 10초, 타깃당 sample 10,000개, sample당 label 40개 한도다. 기본 보관은 7일/2GB이며 전체 디스크 한도는 아니다. 타깃은 내부 Docker DNS로만 접근하고 호스트에 앱 metrics 포트를 게시하지 않는다. 공개 Nginx 경로·rewrite 우회 차단 확인을 등록 조건으로 둔다.

단위는 시간 **초**, 크기 **바이트**, 누적 횟수 **counter**다. counter는 프로세스 재시작 때만 초기화한다. 분당/초당 수치를 앱에서 미리 계산해 counter로 보내지 않는다. JSON 응답이 아니라 Prometheus/OpenMetrics exposition 형식이어야 한다.

| label | 허용 값·의미 |
| --- | --- |
| `method` | 대문자 HTTP method |
| BE `uri`, AI `route` | `/items/{id}`처럼 라우터의 정규화된 템플릿. 미매칭은 `unmatched`, 라우트 판정 불가는 `unknown`. 실제 ID·query string 금지 |
| `status` | HTTP 3자리 상태 코드. 상태를 못 받은 연결 중단은 `unknown`으로 집계하고 5xx로 임의 변환하지 않음 |
| `traffic_class` | `interactive`: 일반 요청, `generation`: 완료를 기다리는 동기 AI 생성, `stream`: 스트리밍. **파트가 route→class 매핑을 제공** |
| `pool`, `id`, `area` | Micrometer/Hikari가 제공하는 제한된 풀·메모리 영역 이름 |
| `provider`, `model` | 설정에 등록된 제공자·모델 allowlist. 사용자 입력을 그대로 사용하지 않음 |
| `operation` | `generation`, `embedding`, `retrieval` 중 하나. 새 동작은 계약 변경으로 추가 |
| `outcome` | `success`, `error`, `timeout`, `rate_limited`, `cancelled` |
| `reason` | 재시도 원인 `error`, `timeout`, `rate_limited` |
| 토큰 `type` | `input`, `output` |

사용자/세션/요청 ID, prompt·응답, 토큰·키, 전체 URL·오류 메시지를 label로 넣지 않는다. 필요하면 마스킹한 로그의 request ID로 조사한다. 초기 label 조합을 제한해 **타깃당 활성 시계열 8,000개 이하**를 목표로 두고 10,000 한도를 넘기기 전에 Cloud와 조정한다. sample 한도 초과는 해당 scrape 실패로 드러난다. 무작정 한도를 올리지 않는다.

HTTP duration은 서버 요청 수신부터 응답 완료/연결 종료까지의 wall time이다. 스트리밍은 전체 연결 수명이다. timeout·오류도 완료 counter와 duration에 한 번 기록하고, 취소도 중복 기록하지 않는다. health·metrics 경로는 앱에서 분리하고 공통 집계에서도 제외한다. 정규화된 일반 route를 `unknown`으로 계속 보고하면 전달 검증 실패다.

앱은 `keepgo_observability_info{contract="1",capability="http"} 1`을 노출한다. backend는 `jvm`, `db_pool`, AI는 `ai_provider`, `ai_streaming`, `ai_usage` 중 실제 구현한 capability도 같은 gauge에 각각 1로 표시한다. 구현되지 않은 capability를 1로 광고하지 않는다. capability는 readiness 표시이지 정상 동작을 보장하는 health 값이 아니다.

## 3. BE 구현 요청

| 원본 메트릭 | 타입 / 주요 label | 측정 내용 |
| --- | --- | --- |
| `http_server_requests_seconds_count` | counter / `uri,method,status,traffic_class` | 완료된 HTTP 요청 |
| `http_server_requests_seconds_sum`, `_bucket` | classic histogram / 위 label + `le` | 같은 HTTP 요청의 처리 시간 |
| `jvm_memory_used_bytes`, `jvm_memory_max_bytes` | gauge / `area,id` | JVM 메모리. heap 경보는 `area=heap` 기준 |
| `jvm_gc_pause_seconds_sum`, `_count` | timer 누적값 | GC pause 시간·횟수 |
| `jvm_threads_live_threads` | gauge | 살아 있는 JVM 스레드 |
| `hikaricp_connections_active`, `_max`, `_pending` | gauge / `pool` | 사용/최대/대기 connection 수 |
| `hikaricp_connections_timeout_total` | counter / `pool` | connection 획득 timeout |

Micrometer 기본 지표를 재구현하지 않는다. Prometheus registry 의존성과 `/actuator/prometheus` 노출을 추가하고, `traffic_class`만 저카디널리티 tag로 보완한다. Cloud가 `uri`를 `route`로 집계한다. 현재 `/actuator/health`의 포트 8080·DB 장애 503 동작은 유지한다. 보안 설정은 기존 SecurityFilterChain과 조합해 내부 scrape가 가능하도록 구현하되, Actuator 전체 공개를 기본값으로 두지 않는다.

HTTP histogram의 유한 bucket 경계는 **0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300초**, 그리고 `+Inf`다. Spring Boot 설정 예시는 아래와 같다. registry 버전에 따른 실제 노출 이름·경계를 scrape로 확인해야 한다.

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,prometheus
  metrics:
    distribution:
      # 자동 대량 bucket 대신 명시한 SLO 경계만 사용한다. 이름이 SLO인 설정일 뿐 합의된 SLO는 아니다.
      percentiles-histogram:
        http.server.requests: false
      slo:
        http.server.requests: 50ms,100ms,250ms,500ms,1s,2s,5s,10s,30s,60s,120s,300s
```

JVM GC 종류에 따라 일부 지표가 없거나 이름이 달라질 수 있다. Hikari가 아닌 풀을 사용하면 동등한 지표와 adapter를 Cloud와 확인한다. heap max가 음수(미정)인 pool은 분모에서 제외하므로 사용하는 GC의 메모리 풀 구성을 검증한다. heap 비율은 컨테이너 메모리 사용률과 다르다.

## 4. AI 구현 요청

| 원본 메트릭 | 타입 / 주요 label | 측정 내용 |
| --- | --- | --- |
| `keepgo_http_requests_total` | counter / `method,route,status,traffic_class` | 서버 HTTP 요청 완료당 한 번 |
| `keepgo_http_request_duration_seconds` | classic histogram / `method,route,traffic_class` | 공통 HTTP 경계 사용. `_bucket,_sum,_count` 노출 |
| `keepgo_ai_provider_requests_total` | counter / `provider,model,outcome` | **제공자 호출 시도당** 완료 한 번. 재시도 포함 |
| `keepgo_ai_provider_request_duration_seconds` | histogram / `provider,model,outcome` | 시도 시작→종료. 내부 재시도 대기 시간 제외 |
| `keepgo_ai_first_token_seconds` | histogram / `provider,model` | 논리 스트리밍 요청 수신→클라이언트에 처음 전달한 내용 토큰. 전처리·대기·실패 후 재시도 포함 |
| `keepgo_ai_retries_total` | counter / `provider,model,reason` | 첫 시도 이후 **실제로 시작한** 추가 시도 횟수 |
| `keepgo_ai_requests_in_flight` | gauge / `operation` | 처리 중 논리 AI 요청. finally에서 감소 |
| `keepgo_ai_tokens_total` | counter / `provider,model,type` | 제공자가 보고한 사용량. 재시도에서 보고된 사용량도 포함 |

Provider duration bucket은 **0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120초 +Inf**, TTFT는 **0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30초 +Inf**다. quantile은 근사치이고 마지막 유한 bucket보다 긴 요청은 꼬리 추정이 제한된다. HTTP stream 전체 시간과 TTFT는 별개다.

TTFT는 첫 내용을 전달한 경우에만 요청당 한 번 기록한다. heartbeat·SSE 연결 수립·빈 chunk는 첫 토큰으로 세지 않는다. 첫 토큰 전 실패/취소는 TTFT에 0초로 넣지 않고 outcome으로 남긴다. 토큰을 제공자가 보고하지 않으면 임의로 0을 더해 정상 계측처럼 표현하지 않는다. 사용량을 최종 응답과 stream 이벤트에서 중복 더하지 않는다. 캐시 적중은 provider 시도가 아니므로 요청은 HTTP에서, provider 호출·토큰은 실제 발생분만 기록한다.

제공자의 429는 `rate_limited`, 시간 제한은 `timeout`, 클라이언트 연결 취소는 `cancelled`, 그 외 호출 실패는 `error`다. 제공자 호출 오류율 분모에서 cancelled를 제외하며 대시보드에는 따로 표시한다. HTTP 200 응답 안의 업무 실패는 5xx 오류율로 잡히지 않는다. 업무 실패를 별도 지표로 추가할지는 팀이 실패 의미를 확인한 후 계약을 확장한다.

Uvicorn worker가 여러 개면 worker 하나의 `/metrics`만 노출해 전체 값으로 오인하지 않는다. Python client의 multiprocess 수집·디렉터리 초기화·죽은 worker 정리와 gauge mode를 구현하거나, 현재 단일 worker 계약을 유지한다. AI 앱 팀이 배포 worker 수와 집계 방식을 전달해야 한다.

## 5. FE/Nginx 구현 요청

브라우저 RUM SDK나 사용자 행동 추적은 이번 범위가 아니다. FE는 route와 backend proxy 경로를 검토하고 다음을 보장한다.

- 공개 `/metrics`, `/actuator`, `/actuator/*`와 `/api` rewrite를 통한 해당 경로 우회를 차단한다. 정규식 location 우선순위·rewrite 결과를 포함해 실제 요청으로 검증한다. 단순 예제 location 복사만으로 완료 처리하지 않는다.
- 일반 웹 요청/장시간 생성/스트리밍의 route 구분, 스트림 proxy buffering·timeout 설정을 BE/AI와 공유한다.
- Nginx stdout/stderr 로그에 요청 시간·upstream 시간·상태·마스킹된 request ID를 남기되 인증 헤더·쿠키·query의 민감값을 제외한다. 이 변경은 CloudWatch 로그 분석용이며 Nginx Prometheus exporter 추가와는 별개다.
- `/healthz`와 기존 서비스 proxy 계약을 유지한다.

## 6. 초기 알림 기준

평가 간격 30초. 아래 지속 시간은 **이동 창 조건이 연속으로 유지되는 시간**이며 장애 발생부터의 보장 시간이 아니다. 최소 표본은 `increase`의 외삽 추정값이다. 낮은 트래픽에서는 HTTP health·수집 장애 알림이 보완한다.

| signal | 조건 | 지속 | 담당 |
| --- | --- | --- | --- |
| `http_metrics_missing` | 등록한 타깃은 UP인데 HTTP capability/count/histogram 계약 누락 | 10분 | Cloud + 해당 앱 |
| `http_5xx` | 5분 창 5xx 비율 >5%, 요청 ≥20, 5xx ≥5 | 5분 | BE/AI |
| `http_latency` | class별 p95 interactive >2초 또는 generation >30초, 해당 class 5분 요청 ≥100 | 10분 | BE/AI |
| `jvm_heap` | heap 사용률 >85% | 15분 | BE |
| `db_pool` | active/max >90%이면서 pending >0 | 5분 | BE + Cloud |
| `db_timeout` | 5분 창 connection timeout ≥3 | 2분 | BE + Cloud |
| `ai_provider_errors` | 5분 실패율 >10%, 취소 제외 시도 ≥20, 실패 ≥5 | 5분 | AI |
| `ai_first_token` | TTFT p95 >5초, 10분 관측 ≥20 | 10분 | AI |

모두 warning으로 시작한다. 비용·토큰 양은 provider 가격·예산·usage 신뢰도가 확인되기 전까지 조회만 한다. HTTP 4xx도 정보성 조회이며 전체를 서비스 장애로 호출하지 않는다. stream 전체 완료 시간에는 일반 API latency 경보를 적용하지 않는다. 인프라 임계치는 기존 CloudWatch가 담당한다.

실제 발송은 Prometheus 규칙 → `ALERTS{scope="application",alertstate="firing"}` → Grafana → Discord다. Grafana가 for 시간을 또 더하지 않는다. 비어 있는 ALERTS는 정상이며 해당 전달 rule의 NoData는 OK다. 수집 실패/Prometheus 단절은 기존 별도 rule과 전달 rule의 실행 오류가 감지한다. 설치·검증·조치는 [알림 운영 절차](monitoring-alert-runbook.md)에 있다.

## 7. 각 파트에서 확인할 것

클라우드가 공통 이름·단위·label·bucket·dashboard·초기 임계치를 먼저 제공한다. 아래는 임의로 확정하면 잘못 측정될 수 있어 구현 담당자의 답이 필요하다.

| 파트 | 필요한 답·증거 | 기본 제안 |
| --- | --- | --- |
| BE | Spring/Micrometer/GC/DB pool 종류, 실측 scrape, route→class, 200 내부 업무 실패 의미 | native Micrometer + class tag, Hikari 계약 |
| AI | 논리 요청 vs 제공자 시도 경계, TTFT 전달 위치, 취소·retry·cache 처리, worker 수, 토큰 사용량 신뢰도 | 4절 정의 적용, 변경점만 회신 |
| FE | 공개 rewrite와 차단 경로, 생성/스트리밍 route, proxy timeout | 공개 metrics 차단·기존 health 유지 |
| 서비스 담당 + Cloud | API 종류별 사용자 대기 목표, 실제 트래픽·부하 결과, 알림 담당/대응 시간 | 6절 숫자를 검증 전 초안으로 사용 |

회신 형식: **구현 가능 / 변경이 필요한 항목과 이유 / 확인한 image SHA / 마스킹한 scrape 예시 / route→class 표**. 계정·키·Webhook·실제 사용자 데이터는 전달하지 않는다. 이 문서는 전달용 자료이며 이번 작업에서 메시지를 외부 채널로 발송하지 않았다.

## 근거

집계 전 rate 적용과 histogram bucket 합산은 [Prometheus histogram 설명](https://prometheus.io/docs/practices/histograms/)을 따른다. BE 원본 지표는 [Spring Boot Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html)와 [Micrometer Prometheus](https://docs.micrometer.io/micrometer/reference/implementations/prometheus.html)를 기준으로 했으며 실제 앱 버전의 출력 확인이 필요하다. 테스트 형식은 [Prometheus rule unit test](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)를 사용한다.
