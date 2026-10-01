# 앱 메트릭 적용·알림 대응 절차

이 문서는 [메트릭 계약 v1](monitoring-metrics-contract.md)의 운영 절차다. AWS/PG 최초 설치·SSM 접근·Secret·로그 활성화는 [기본 모니터링 구성](v1-monitoring.md)을 따른다. 계약을 코드로 준비한 상태이며 **앱 계측·AWS 적용·Discord 실제 수신을 완료한 기록은 아니다.**

## 적용 순서

1. BE/AI/FE에 [계약 문서](monitoring-metrics-contract.md)를 전달하고 7절 확인 항목만 회신받는다. Cloud가 공통 설정을 먼저 제시하므로 모든 항목을 다시 설계할 필요는 없다.
2. 앱 팀은 image SHA, 정상화된 route→class 표, 민감값을 제거한 `/metrics` 또는 `/actuator/prometheus` 출력, worker/registry 버전, 공개 metrics 차단 시험 결과를 남긴다.
3. 준비된 앱에서 정상 요청·4xx·5xx·timeout·stream 취소·retry를 제한된 시험 환경으로 재현한다. counter를 요청/시도당 한 번 기록하는지, 초 단위인지, `+Inf`를 포함한 classic histogram인지, DB pool/JVM/AI 지표가 실제 설정과 맞는지 확인한다. 운영 사용자 요청에 오류를 주입하지 않는다.
4. Cloud는 현재 적용할 PG 커밋을 모니터링 EC2(필요하면 앱 EC2의 exporter용도)의 별도 `/opt/keepgo/observability` checkout에 준비하고 아래 설정 검사를 실행한다. Prometheus recording/alert rule, Grafana 새 대시보드와 전달 rule을 먼저 반영한다.
5. `monitoring/examples/application-targets.json`에서 **검증된 서비스 항목만** 실제 `monitoring/prometheus/targets/application.json`으로 옮긴다. 이 변경도 Git에 기록해 다른 checkout·재배포에서 유실되지 않게 한다. `metrics_contract=v1`을 빠뜨리면 이번 상세 규칙에서 제외되므로 수집 UP만 보고 완료 처리하지 않는다.
6. file discovery가 최대 약 30초 간격으로 반영되고 두 번 이상 scrape된 뒤 rate가 계산된다. 의미 있는 5분/10분 창이 쌓일 때까지 관찰한다. 첫 등록 전 실제 business route를 한 번 호출해 lazy HTTP meter와 histogram을 초기화한다. 새 인스턴스의 정상 startup만으로 요청 지표가 없으면 10분 후 계약 누락 알림이 발생할 수 있다.
7. Prometheus Targets에서 UP, Rules에서 두 application group 로드·평가 정상, Grafana 세 앱 대시보드에서 기대 값, 앱 타깃의 `keepgo_observability_info`를 확인한다. 아직 구현하지 않은 AI capability의 패널은 No data일 수 있다. 이를 0으로 숨기거나 성공으로 판정하지 않는다.
8. 운영자가 Grafana contact point의 Test를 실행해 Discord 수신을 확인하고, 합의한 시험 시간에 최소 한 앱 알림의 firing→resolved 전달을 검증한다. 이 저장소의 자동 검사는 실제 Webhook을 호출하지 않는다.

원본 앱 수집 metric에 `service`, `metrics_contract` 같은 Cloud 소유 label을 중복 넣지 않는다. Prometheus의 기본 honor_labels=false가 충돌 label을 export 처리하더라도 앱 구현을 정리한다. 한 타깃으로 여러 worker 지표가 중복 노출되면 합계가 잘못되므로 worker 집계도 인수 범위다.

## 로컬·CI 검사

대시보드나 전달 rule을 바꾸면 Python 원본을 수정하고 생성한다. 알림 숫자는 Prometheus YAML에서만 변경한다.

```sh
python3 scripts/render-app-monitoring.py
python3 scripts/render-app-monitoring.py --check
python3 -m unittest discover -s tests -p test_monitoring.py
```

Docker 없이 같은 버전의 native promtool을 사용할 수 있다.

```sh
promtool check rules monitoring/prometheus/rules/application-recording.yml monitoring/prometheus/rules/application-alerts.yml
promtool test rules tests/prometheus/application.test.yml
```

Docker 환경에서 전체 config 경로·rule glob까지 검사한다. 이 명령은 실제 앱/Secret에 접근하지 않는다.

```sh
docker run --rm -v "$PWD/monitoring/prometheus:/etc/prometheus:ro" \
  --entrypoint /bin/promtool prom/prometheus:v3.13.3 check config /etc/prometheus/prometheus.yml
docker run --rm -v "$PWD:/repo:ro" -w /repo \
  --entrypoint /bin/promtool prom/prometheus:v3.13.3 test rules tests/prometheus/application.test.yml
```

CI는 생성 파일 일치, 전체 Prometheus/blackbox 설정, promtool 동작 시나리오, Compose/대시보드 연결 검사를 실행한다. 가짜 시계열 시험은 앱의 실제 계측 정확도나 Grafana provisioning 성공·Webhook 도착을 증명하지 않는다.

## 발송·복구 동작

Prometheus가 임계치·지속 시간을 평가한다. `ALERTS{scope="application",alertstate="firing"}`를 Grafana의 `KeepGo application signal` rule이 읽어 Discord contact point로 보낸다. 알림의 **service + signal**로 아래 대응표를 찾는다. instance/pool/class/provider/model이 있으면 함께 확인한다. 값 자체는 해당 대시보드·Prometheus Rules에서 조회한다.

Grafana 예약 label인 alertname은 전달 rule의 이름이 되므로 원래 장애 종류를 `signal`로 보존한다. notification grouping도 signal을 포함한다. Grafana 평가 30초와 group wait 30초가 추가될 수 있다. 지속 장애 재알림은 4시간이다. `for=0s`는 Prometheus에서 이미 지속 시간을 확인했기 때문이다.

조건이 회복되면 Prometheus firing series가 사라진다. 전달 rule의 NoData는 정상으로 처리하고 Grafana의 사라진 series 처리/평가 지연 후 resolved가 전달된다. 앱 타깃 제거도 이를 회복처럼 보이게 할 수 있으므로 **타깃 삭제로 알림을 끄지 않는다.** 필요한 점검은 service/signal을 지정한 Grafana silence로 시작·종료 시간과 담당자를 기록한다.

기존 수집 실패 rule은 Prometheus 접근 실패와 `up=0`을 별도로 감지한다. 다만 수집은 정상인데 application rule 파일 자체가 빠진 상황을 전달 rule의 NoData로 구분할 수는 없다. 변경 후 Rules 목록·CI 검사를 필수로 확인한다. Grafana 자체가 멈추면 Discord 발송도 멈추므로 CloudWatch/Actions 외부 감시와 PG health 확인을 유지한다.

## 신호별 대응

| signal | 먼저 확인할 것 | 조치 |
| --- | --- | --- |
| `http_metrics_missing` | UP인데 capability/count/bucket/class가 빠졌는지, 실제 앱 registry 버전, business route 초기 요청 | 잘못된 계측·target label을 수정. 실제 트래픽 0을 서버 장애로 오인하지 않음 |
| `http_5xx` | 오류 route·최근 배포·BE→AI/DB 연결·CloudWatch 오류 로그 | 원인 파트와 새 이미지 수정/기존 복구 절차 검토. 4xx나 업무 실패를 무조건 5xx로 재분류하지 않음 |
| `http_latency` | traffic_class, 요청량, route별 지연, DB pool/AI 제공자 응답 | 먼저 class 오분류 여부 확인 후 병목 조사. 단순 임계치 상향으로 해소하지 않음 |
| `jvm_heap` | heap max/GC 종류·pause·최근 배포·컨테이너 메모리 | heap 누수·메모리 부하 조사. JVM heap을 무작정 늘려 컨테이너 OOM을 만들지 않음 |
| `db_pool` | pending·active·DB CPU/연결·slow query·긴 transaction | 쿼리/transaction 및 DB 한도를 확인한 뒤 pool 변경 판단 |
| `db_timeout` | 획득 timeout·pool 대기·RDS 연결성·배포 시간 | timeout 값을 늘리기 전에 자원/쿼리 문제 조사 |
| `ai_provider_errors` | outcome별 429/timeout/error, 재시도 폭증·제공자 상태 | backoff·동시성·quota·fallback 정책 점검. 무한 retry 금지 |
| `ai_first_token` | 성공 stream 표본 수·제공자 지연·queue/전처리·proxy buffering | 사용자에게 첫 내용이 전달되는 지점을 확인하고 구간별 지연 조사 |

원인 확정 전 자동 rollback/restart와 연결하지 않는다. 상세 알림은 운영자 판단용이며 기존 앱 CD 성공 판정 정책을 바꾸지 않는다.

## 숫자 변경과 남길 기록

초기 3~7일 정상 트래픽과 대표 부하 테스트로 표본 수·오탐·놓친 장애를 확인한다. interactive 2초, generation 30초, TTFT 5초는 이 단계에서 서비스 목표와 조정한다. 저트래픽 서비스의 최소 표본을 바꾸면 비율 경보가 소수 요청에 흔들리는지 시험을 함께 수정한다.

변경 기록에는 날짜, Cloud/앱 SHA, workload·동시성·기간, 변경 전후 임계치, 근거 그래프/쿼리, 담당자, 다음 검토일을 남긴다. 제안된 숫자를 곧바로 SLA/SLO 달성치로 보고하지 않는다. 원본 rule YAML과 테스트 fixture를 변경하고 CI 후 반영한다.

현재 검증 상태와 실제 적용 증거는 [구현·검증 현황](v1-implementation-status.md)에 분리해 기록한다.
