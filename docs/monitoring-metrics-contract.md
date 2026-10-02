# 앱 상세 메트릭 계약 v1 — 파트 전달용

2026-09-30. **클라우드 초안과 설정 구현 완료 / 앱 계측·운영 적용 미확인.** PG는 Prometheus + Grafana이며 Loki는 사용하지 않는다. 이 문서는 각 파트가 구현할 수 있는 기본값을 먼저 정한다. 확인이 필요한 항목은 7절에 모았다. 숫자는 초기 운영 가설이며 합의·검증된 SLO가 아니다.

## 0. 이 파일만 읽으면 되는 범위

**BE·AI·FE에 구현을 요청할 때는 이 파일 하나를 전달하면 된다.** 공통 수집 계약, 파트별 구현 범위, 메트릭 이름·타입·label·bucket, 보안 조건, 초기 알림, 완료 기준·회신 항목을 담았다. 담당자는 0·2절과 자기 파트의 3/4/5절, 7·8절을 읽는다. 실제 코드 패치나 구현 완료 보고서는 아니므로 각 레포에 맞춘 구현·시험은 별도로 수행해야 한다.

Cloud 담당자의 AWS 권한·Secret·Agent·Compose 설치는 [기본 구축 문서](v1-monitoring.md), 실제 등록·검사 명령·장애 대응은 [알림 운영 절차](monitoring-alert-runbook.md)를 함께 본다. 이 파일에 서버 비밀번호·Webhook·실제 AWS 연결 값을 복사하지 않는다.

### 최신 배포 기준 코드 확인 결과와 레포별 추가 항목

2026-10-01 각 레포의 **배포 기준 원격 브랜치**를 fetch해 읽었다. 실제 운영 컨테이너 이미지를 조회한 결과는 아니다. 구현 시작 시 커밋이 달라졌으면 변경분을 다시 확인한다.

| 파트 | 기준 | 9/30 확인분 대비 |
| --- | --- | --- |
| BE | `main` `f20f4fc` (Spring Boot 4.1.1, Java 25) | 변경 없음 |
| AI | `main` `6da303d` | `f7476b5` 이후 Sentry, `/v1/recommend-courses`·취소 API 추가 |
| FE | `feat/v1` `d11c424` | [TD-011](technical-decisions.md#td-011--fe-배포-기준-브랜치)에 따라 `main`(9/22 `ea0683c`)이 아니라 `feat/v1`이 배포 기준. `d3ca2ac` 이후 nginx는 주석만 변경 |

**프로세스 구조.** BE는 JVM 1개이고 요청은 Tomcat 스레드 풀이 처리하므로 Micrometer 값이 하나로 모인다. AI Dockerfile CMD에는 `--workers`가 없어 uvicorn worker가 1개다. `app/retrieval/chroma_store.py`가 임베디드 Chroma 때문에 다중 프로세스를 금지한다. Compose에도 `replicas`가 없으므로 지금은 Python multiprocess 수집이나 서비스당 다중 타깃 등록이 필요 없다. worker나 컨테이너 수를 늘리면 4절 multiprocess 조건과 타깃 등록을 다시 본다.

#### BE 추가 항목

| # | 위치 | 추가·변경 | 비고 |
| --- | --- | --- | --- |
| 1 | `build.gradle` | `runtimeOnly 'io.micrometer:micrometer-registry-prometheus'` | Actuator starter는 이미 있음. Boot 4 모듈 구성에서 `/actuator/prometheus`가 실제로 열리는지 scrape로 확인 |
| 2 | `application.yaml` `management` | `exposure.include`를 `health` → `health,prometheus`, 3절 `slo` bucket 추가, **`server.port: 8081`** | `health.show-details: never` 유지. 관리 포트 분리는 모니터링 호스트 분리([TD-024](technical-decisions.md#td-024--모니터링-전용-인스턴스-분리)) 때문에 필수. Actuator 전체가 8081로 옮겨 가므로 `/actuator/health`도 8081에서 응답한다 |
| 3 | `auth/SecurityConfig.java` `fallBackFilterChain` (`@Order(1000)`) | `EndpointRequest.to(PrometheusScrapeEndpoint.class)` 허용 규칙 추가 | 현재 health 외 `anyRequest().denyAll()`이라 추가하지 않으면 scrape가 403. `/api/**` 체인(`@Order(100)`)과 경로가 겹치지 않음 |
| 4 | 새 Bean (`ServerRequestObservationConvention` 확장 등) | `http.server.requests`에 `traffic_class` low-cardinality tag | 아래 route→class 초안 사용 |
| 5 | 새 Bean (Micrometer `Gauge`) | `keepgo_observability_info{contract="1",capability=...} 1`을 `http`·`jvm`·`db_pool` 각각 노출 | 2절. 없으면 타깃 등록 후 `http_metrics_missing` 알림이 난다 |
| 6 | 코드 변경 없음 | JVM·GC·Hikari·Tomcat 지표, BE→AI `http.client.requests` | registry 추가만으로 자동 노출. AI 클라이언트는 Boot가 주입한 `RestClient.Builder`로 만들어 자동 계측 대상이며, `uri` tag가 템플릿인지 확인 |

**관리 포트 8081 분리 이유.** Prometheus가 다른 EC2에서 수집하므로 앱 EC2에 포트를 열어야 한다. 8080을 열면 BE API 전체가 모니터링 호스트에 노출된다. 8081에는 Actuator만 있으므로 이 포트만 모니터링 보안 그룹에 연다. 공개 경로 차단도 FE Nginx 규칙 하나에 의존하지 않게 된다.

**배포 순서 주의.** Cloud `compose.yaml`의 backend healthcheck는 현재 `127.0.0.1:8080/actuator/health`를 호출한다. 8081 이미지가 먼저 배포되면 healthcheck가 실패해 자동 롤백된다. 반대로 healthcheck만 먼저 8081로 바꾸면 현재 이미지가 실패한다. 그래서 Cloud healthcheck는 **8081을 먼저 시도하고 실패하면 8080으로 재시도**하도록 이미 바뀌었다. BE는 8081 이미지를 순서 걱정 없이 배포하면 된다. 8081 이미지가 정착하면 Cloud가 8080 재시도를 제거한다. 포트 8081·9464의 호스트 게시와 보안 그룹은 Cloud가 맡으므로 앱 레포에서 Compose·보안 그룹을 바꾸지 않는다. 3번 보안 규칙은 관리 포트에도 적용되므로 그대로 필요하다.

BE route→class 초안 (BE 확인 필요):

| class | route | 근거 |
| --- | --- | --- |
| `generation` | `POST /api/v1/user/recommendation` | 요청 안에서 AI `recommend-courses`를 동기 호출. AI 내부 제한 15초 |
| `generation` | `POST /api/v1/user/youtube-analyze` | 좋아요 영상마다 AI `analyze-video`를 순차 동기 호출. 영상당 AI 제한 120초 |
| `interactive` | 그 외 전체 | 채팅 `POST /api/v1/user/chat-messages`는 AI `extract`를 `@Async` worker에 넘기고 결과는 `GET /{chatId}/response`로 조회 |

#### AI 추가 항목

| # | 위치 | 추가·변경 | 비고 |
| --- | --- | --- | --- |
| 1 | `pyproject.toml`, `uv.lock` | `prometheus-client` 추가 | worker 1개라 기본 registry 사용 |
| 2 | 새 HTTP 미들웨어 (예: `app/core/metrics.py`) + `app/main.py` 등록 | `keepgo_http_requests_total`, `keepgo_http_request_duration_seconds`, 권장 `keepgo_ai_requests_in_flight` | route는 매칭 후 `request.scope["route"].path` 템플릿. 미매칭은 `unmatched` |
| 3 | `app/main.py` | **별도 포트 9464**에 metrics 노출(`prometheus_client.start_http_server(9464)`), `keepgo_observability_info{contract="1",capability="http"} 1` | AI API는 인증이 없어 8000을 모니터링 호스트에 열면 AI 호출까지 가능해진다. worker가 1개라 같은 프로세스에서 별도 포트를 띄워도 값이 하나로 모인다. worker를 늘리면 multiprocess 방식으로 다시 설계한다. `/health`는 HTTP 집계에서 제외 |
| 4 | `Dockerfile` | `EXPOSE 9464` | 문서용. 실제 포트 게시는 Cloud Compose가 한다 |

구현 시 주의:

- `@app.exception_handler(Exception)`는 Starlette에서 가장 바깥 `ServerErrorMiddleware`가 처리한다. 예상하지 못한 예외는 사용자 미들웨어에 응답이 아니라 예외로 올라온다. 미들웨어에서 `except`로 status `500`을 기록하고 다시 raise하지 않으면 5xx가 지표에서 빠진다. `AIServerError`·`RequestValidationError`는 안쪽 `ExceptionMiddleware`가 응답으로 바꾸므로 정상 status로 보인다. 오류 요청 시험으로 확인한다.
- `POST /v1/recommend-courses/{request_id}/cancel`은 경로에 요청 ID가 있다. 실제 경로를 label로 쓰면 요청마다 시계열이 생기므로 반드시 템플릿으로 기록한다.
- `/v1/recommend-courses`는 BE가 중단한 요청에도 HTTP 200 + `message=cancel_accepted, data=null`을 반환한다. HTTP 지표에서는 성공으로 집계된다. 중단 비율이 필요하면 별도 counter를 계약 확장으로 추가한다.
- Sentry(`sentry-sdk[fastapi]`)가 추가됐다. 오류 상세는 Sentry, 요청량·오류율·지연은 Prometheus가 맡는다. 둘 다 요청 경로에 붙으므로 오류 요청에서 status 기록이 어긋나지 않는지 함께 시험한다.
- `app/models/factory.py`가 SDK 한 층에서 재시도한다(`max_retries`). 시도별 hook을 검증하기 전에는 `ainvoke` 1회를 제공자 시도 1회로 보고하지 않는다.

AI route→class (2026-10-02 AI 확인): `/v1/analyze-video`, `/v1/extract`, `/v1/verify-place`, `/v1/recommend-courses`는 `generation`, `/v1/embed-places`(임베딩 저장 후 결과만 알리는 짧은 호출)와 `/v1/recommend-courses/{request_id}/cancel`은 `interactive`. 초안의 `/v1/analyze-videos`는 코드에 없다. 스트리밍 경로는 없다. 제공자·지도 API 실패는 502/504/500으로 응답하므로 5xx 비율에 잡힌다. 단 제공자 429는 AI도 429로 돌려주므로 5xx 알림에 잡히지 않는다.

#### FE 추가 항목

| # | 위치 | 추가·변경 | 비고 |
| --- | --- | --- | --- |
| 1 | `nginx.conf` | **변경 불필요 가능성이 높음** | `/actuator`, `/metrics`는 `location /`로 `frontend:3000`에 간다. `/api/actuator/...`는 `$request_uri` 그대로 `backend:8080/api/actuator/...`로 가서 Actuator 경로 `/actuator/**`에 닿지 않는다. 8절 외부 요청 검사로 확정 |
| 2 | `nginx.conf` (선택) | 요청 시간·upstream 시간·상태를 담은 `log_format` | 5절. 인증 헤더·쿠키·query 민감값 제외 |
| 3 | `nginx.conf` (확인 필요) | `/api/` proxy의 `proxy_read_timeout` | 미설정이라 기본 60초. `youtube-analyze`처럼 60초를 넘는 동기 요청은 Nginx가 504를 내고 BE는 계속 처리해 BE 지표에는 2xx로 남을 수 있다. 계측 코드가 아니라 BE·FE timeout 결정 사항 |

**AI의 TTFT·개별 제공자 시도·재시도 횟수는 이번 기본 구현의 필수 항목이 아니다.** 아래 4절에는 확장 시 사용할 계약도 함께 남겨 둔다. TTFT를 만들기 위해 스트리밍 기능을 새로 추가하거나, 계측을 위해 재시도 정책을 변경하지 않는다. 기본 구현만 완료해도 Cloud가 HTTP 모니터링을 연결할 수 있다.

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

수집/평가 30초, timeout 10초, 타깃당 sample 10,000개, sample당 label 40개 한도다. 기본 보관은 7일/2GB이며 전체 디스크 한도는 아니다. Prometheus는 별도 모니터링 EC2에 있다([TD-024](technical-decisions.md#td-024--모니터링-전용-인스턴스-분리)). 앱 EC2는 **수집 전용 포트만** 게시하고(BE 관리 포트 8081, AI metrics 9464, node-exporter 9100, blackbox 9115) 보안 그룹에서 모니터링 보안 그룹만 허용한다. 앱 API 포트(BE 8080, AI 8000)는 게시하지 않는다. 공개 Nginx 경로·rewrite 우회 차단 확인을 등록 조건으로 둔다.

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

Micrometer 기본 지표를 재구현하지 않는다. Prometheus registry 의존성과 `/actuator/prometheus` 노출을 추가하고, `traffic_class`만 저카디널리티 tag로 보완한다. Cloud가 `uri`를 `route`로 집계한다. `/actuator/health`의 DB 장애 503 동작은 유지하고, 포트는 관리 포트 8081로 옮긴다(0절 BE 추가 항목의 배포 순서 주의 참고). 보안 설정은 기존 SecurityFilterChain과 조합해 내부 scrape가 가능하도록 구현하되, Actuator 전체 공개를 기본값으로 두지 않는다.

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

기본 구현은 `/metrics`와 HTTP counter/histogram 및 HTTP capability다. 추가 capability와 아래 확장 지표는 실제 측정이 검증된 경우에만 노출한다.

| 원본 메트릭 | 타입 / 주요 label | 측정 내용 | 적용 범위 |
| --- | --- | --- | --- |
| `keepgo_http_requests_total` | counter / `method,route,status,traffic_class` | 서버 HTTP 요청 완료당 한 번 | 필수 |
| `keepgo_http_request_duration_seconds` | classic histogram / `method,route,traffic_class` | 공통 HTTP 경계 사용. `_bucket,_sum,_count` 노출 | 필수 |
| `keepgo_ai_provider_requests_total` | counter / `provider,model,outcome` | **제공자 호출 시도당** 완료 한 번. 재시도 포함 | SDK 시도별 계측 검증 후 확장 |
| `keepgo_ai_provider_request_duration_seconds` | histogram / `provider,model,outcome` | 시도 시작→종료. 내부 재시도 대기 시간 제외 | SDK 시도별 계측 검증 후 확장 |
| `keepgo_ai_first_token_seconds` | histogram / `provider,model` | 논리 스트리밍 요청 수신→첫 내용 토큰 전달 지점. 전처리·대기·실패 후 재시도 포함 | 스트리밍 기능 도입 후 확장 |
| `keepgo_ai_retries_total` | counter / `provider,model,reason` | 첫 시도 이후 **실제로 시작한** 추가 시도 횟수 | SDK 시도별 계측 검증 후 확장 |
| `keepgo_ai_requests_in_flight` | gauge / `operation` | 처리 중 논리 AI 요청. finally에서 감소 | 권장 |
| `keepgo_ai_tokens_total` | counter / `provider,model,type` | 제공자가 보고한 사용량. 재시도에서 보고된 사용량도 포함 | usage 제공 범위 검증 후 선택 |

현재 `ainvoke` 호출 바깥의 timer는 SDK 재시도·대기를 포함한 **논리 호출 전체 시간**이다. 이를 위 provider 시도별 duration 이름으로 내보내면 계약과 다르다. 논리 호출 별도 계측이 필요하면 이름·대시보드·분모를 함께 추가한다. 재시도 상수를 곱해서 실제 시도 횟수를 추정하지 않는다. SDK가 최종 호출의 usage만 제공하면 전체 시도 사용량을 관측했다고 표현하지 않는다.

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
| `ai_provider_errors` | 5분 실패율 >10%, 취소 제외 시도 ≥20, 실패 ≥5 | 5분 | AI, 시도별 계측 확장 후 |
| `ai_first_token` | TTFT p95 >5초, 10분 관측 ≥20 | 10분 | AI, 스트리밍 도입 후 |

Cloud에는 8개 규칙을 준비했지만 마지막 두 AI 확장 규칙은 해당 지표가 없으면 평가 결과가 없으며 알림이 발생하지 않는다. 확장 패널은 No data로 남을 수 있다. 기본 구축 완료를 위해 이를 가짜 0으로 채우거나 해당 기능을 구현할 필요는 없다.

모두 warning으로 시작한다. 비용·토큰 양은 provider 가격·예산·usage 신뢰도가 확인되기 전까지 조회만 한다. HTTP 4xx도 정보성 조회이며 전체를 서비스 장애로 호출하지 않는다. stream 전체 완료 시간에는 일반 API latency 경보를 적용하지 않는다. 인프라 임계치는 기존 CloudWatch가 담당한다.

실제 발송은 Prometheus 규칙 → `ALERTS{scope="application",alertstate="firing"}` → Grafana → Discord다. Grafana가 for 시간을 또 더하지 않는다. 비어 있는 ALERTS는 정상이며 해당 전달 rule의 NoData는 OK다. 수집 실패/Prometheus 단절은 기존 별도 rule과 전달 rule의 실행 오류가 감지한다. 설치·검증·조치는 [알림 운영 절차](monitoring-alert-runbook.md)에 있다.

## 7. 각 파트에서 확인할 것

클라우드가 공통 이름·단위·label·bucket·dashboard·초기 임계치를 먼저 제공한다. 아래는 임의로 확정하면 잘못 측정될 수 있어 구현 담당자의 답이 필요하다.

| 파트 | 필요한 답·증거 | 기본 제안 |
| --- | --- | --- |
| BE | Spring/Micrometer/GC/DB pool 종류, 실측 scrape, route→class, 200 내부 업무 실패 의미 | native Micrometer + class tag, Hikari 계약 |
| AI | 기본 구현의 route→class, HTTP 200 안의 부분 실패 의미, worker 수·취소 처리. 시도별 hook·usage·TTFT는 확장할 때 확인 | 우선 HTTP 계측. SDK 재시도 포함 논리 호출과 개별 시도를 혼동하지 않음 |
| FE | 공개 rewrite와 차단 경로, 생성/스트리밍 route, proxy timeout | 공개 metrics 차단·기존 health 유지 |
| 서비스 담당 + Cloud | API 종류별 사용자 대기 목표, 실제 트래픽·부하 결과, 알림 담당/대응 시간 | 6절 숫자를 검증 전 초안으로 사용 |

회신 형식: **구현 가능 / 변경이 필요한 항목과 이유 / 확인한 image SHA / 마스킹한 scrape 예시 / route→class 표**. 계정·키·Webhook·실제 사용자 데이터는 전달하지 않는다. 이 문서는 전달용 자료이며 이번 작업에서 메시지를 외부 채널로 발송하지 않았다.

## 8. 파트별 완료 기준과 Cloud 인계

| 파트 | 완료 조건 | 전달할 증거 |
| --- | --- | --- |
| BE | `backend:8081/actuator/prometheus`에서 200과 Prometheus 형식 응답. 8080에서는 Actuator가 응답하지 않음. 정상·4xx·5xx 요청의 HTTP counter/class/bucket, JVM/Hikari 지표 확인. 기존 인증·health 회귀 없음 | 이미지 SHA, route→class 표, 마스킹한 scrape, 검사 결과 |
| AI | `ai-api:9464/metrics`에서 200. 실제 business route 요청 후 HTTP counter와 `+Inf` 포함 histogram, `capability=http` 확인. 동시 요청·오류·취소에서 이중 계수 없음 | 이미지 SHA, route→class 표, 마스킹한 scrape, worker 수·수집 방식, 구현한 capability 목록 |
| FE | 외부 `/metrics`, `/actuator`, `/actuator/prometheus` 및 관련 `/api` 우회 경로에서 metrics 내용이 노출되지 않음. 기존 `/api`, 로그인·정적 파일·health 정상 | 적용 이미지 SHA와 외부 요청 경로별 검사 결과 |
| Cloud | 검증된 서비스에 한해 target에 `service`, `metrics_contract=v1`, metrics path 등록. UP뿐 아니라 계약 지표·집계값·기본 대시보드·실제 알림 경로 확인 | 적용 Cloud SHA, 정상 수집·알림/복구 확인 기록 |

200만 확인하고 완료 처리하지 않는다. 건강 검사 전용 요청이 아닌 실제 business route로 meter를 초기화하고, 요청 수와 오류 수·단위가 기대값과 맞는지 확인한다. 예상하지 못한 404·인증 응답·HTML 페이지는 정상 metrics 응답이 아니다. AI 부분 실패의 업무적 판정은 팀이 확인할 때까지 HTTP 상태 지표와 별개로 남긴다.

파트가 계측 코드를 작성하는 동안 Cloud의 기본 로그·서버 지표·health 모니터링은 먼저 설치할 수 있다. 준비된 파트부터 상세 수집을 연결하며, 실제 운영 타깃 등록과 Webhook 수신 시험은 Cloud가 수행한다.

## 근거

집계 전 rate 적용과 histogram bucket 합산은 [Prometheus histogram 설명](https://prometheus.io/docs/practices/histograms/)을 따른다. BE 원본 지표는 [Spring Boot Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html)와 [Micrometer Prometheus](https://docs.micrometer.io/micrometer/reference/implementations/prometheus.html)를 기준으로 했으며 실제 앱 버전의 출력 확인이 필요하다. 테스트 형식은 [Prometheus rule unit test](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)를 사용한다.
