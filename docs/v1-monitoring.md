# CloudWatch + Prometheus + Grafana 운영 구성

2026-09-30 구성 기준. PG는 **Prometheus + Grafana**다. Loki·Promtail은 사용하지 않는다. 저장소 설정을 준비한 상태이며 실제 AWS 설치·알림 수신 완료는 [검증 현황](v1-implementation-status.md)에 따로 기록한다.

## 1. 역할과 데이터 흐름

| 대상 | 수집·저장 | 조회·알림 |
| --- | --- | --- |
| 앱 4개 stdout/stderr | Docker awslogs → CloudWatch Logs, 기본 14일 | CloudWatch Logs Insights |
| EC2 상태, RDS CPU·남은 저장 공간 | AWS 기본 CloudWatch 지표 | CloudWatch Alarm → SNS 이메일 |
| EC2 메모리·루트 디스크 | 호스트 CloudWatch Agent, 60초 | CloudWatch Alarm → SNS 이메일; Agent 지표 누락도 감시 |
| 호스트 CPU·메모리·디스크 상세 추이 | node-exporter → Prometheus, 30초 | Grafana 기본 대시보드 |
| Nginx·FE·BE·AI 내부 HTTP health | blackbox-exporter → Prometheus, 30초 | Grafana: 3분 지속 실패 → Discord, 복구 알림 |
| Prometheus·exporter·앱 지표 수집 실패 | Prometheus `up` | Grafana: 3분 지속 실패 또는 NoData/Error → Discord |
| 앱 요청 수·오류율·지연·JVM·DB pool·AI 제공자 | 계약을 구현한 앱을 Prometheus에 등록 | 상세 대시보드 3개·초기 알림 8개 준비. 검증 후 타깃 활성화 |
| 외부 HTTPS 경로·배포 실패 | 기존 GitHub Actions | 기존 Discord 알림 유지 |

CloudWatch는 호스트 밖에서 감시하므로 EC2와 PG가 함께 죽어도 EC2 상태 알림이 남는다. 내부 프로브와 Actions 외부 감시는 관측 경로가 다르다. 동일 장애에서 두 알림이 올 수 있고, Grafana는 지속 장애를 4시간마다 다시 알린다. 서버 자원 임계치 알림은 CloudWatch가 담당해 중복 설정하지 않는다.

Grafana는 Prometheus를 기본 데이터 소스로 쓴다. 로그·RDS 조회는 CloudWatch 콘솔을 이용한다. Grafana 컨테이너에 AWS 키나 EC2 역할 조회 권한을 추가하지 않는다. Agent와 node-exporter의 메모리 지표는 계산 방식이 달라 수치가 완전히 같지는 않다.

## 2. 배포 경계·용량·접근

- 앱: 기존 `/opt/keepgo/cloud`, `keepgo-v1` Compose 프로젝트, 기존 자동 CD.
- PG: 별도 checkout `/opt/keepgo/observability`, `keepgo-monitoring` 프로젝트. 앱 CD의 checkout 변경이 모니터링 마운트 파일까지 바꾸지 않게 한다. 같은 파일을 앱 Compose와 `-f`로 합치지 않는다.
- 앱이 먼저 떠서 `keepgo-v1_web`, `keepgo-v1_service` 네트워크가 있어야 한다. 앱 컨테이너 재생성 후에도 서비스 DNS 이름으로 다시 연결한다. 운영 중 앱 `compose down`은 이 외부 네트워크 사용 때문에 실패할 수 있으므로 서비스별 재배포 절차를 사용한다.
- Grafana `127.0.0.1:3001`, Prometheus `127.0.0.1:9090`만 호스트에 바인딩한다. 보안 그룹에 3001·9090·9100·9115를 열지 않는다. exporter는 호스트 포트를 게시하지 않는다.
- node-exporter는 Linux 호스트 루트를 읽기 전용으로 마운트하고 host PID namespace를 사용한다. CPU·메모리·파일시스템·load만 수집한다. Docker socket, privileged 권한은 사용하지 않는다. 컨테이너별 CPU·메모리·재시작 이력은 이 구성에 포함되지 않는다.
- PG 컨테이너 메모리 상한 합계는 **960 MiB**다. 기존 앱 상한 합계 2,432 MiB에 OS·Docker·Agent·캐시가 더해진다. 4 GiB 호스트는 여유를 측정해야 하며, 부하 테스트를 같이 하면 8 GiB급 또는 모니터링 분리 호스트를 검토한다. 상한은 실제 사용량 보장이 아니다.
- Prometheus는 **7일 또는 2GB 중 먼저 도달하는 보관 한도**를 사용한다. WAL·head·일시 compaction 공간은 별도여서 디스크 전체가 2GB로 제한되는 것은 아니다. 최소 5 GiB 이상의 추가 여유를 확인하고 디스크 알람을 유지한다. 데이터는 named volume에 보관한다.
- 버전은 Compose에 고정했다. 업그레이드는 변경 PR과 검증 후 수행한다. Grafana 관리자 비밀번호 파일은 최초 DB 초기화용이다. 기존 비밀번호 변경은 Grafana UI/CLI에서 처리한다.

## 3. CloudWatch를 먼저 준비한다

기존 `/keepgo/v1/application` 로그 그룹·`keepgo-v1-alerts` SNS 토픽·동명 알람이 있으면 소유 스택을 먼저 확인한다. 같은 이름의 자원을 새 스택으로 중복 생성하지 않는다. 아래는 AWS 배포 권한이 있는 운영자 셸에서 실행한다. EC2 런타임 역할과 CloudFormation 배포 역할은 별개다.

```sh
aws cloudformation deploy --region ap-northeast-2 \
  --stack-name keepgo-v1-monitoring \
  --template-file infrastructure/monitoring.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides InstanceId=i-REPLACE \
    InstanceRoleName=REPLACE_EC2_ROLE AlarmEmail=REPLACE_EMAIL
```

SNS 구독 확인 이메일에서 승인한다. EC2 역할에는 `CWAgent` namespace의 PutMetricData와 **해당 로그 그룹 안에서만** CreateLogStream·PutLogEvents가 추가된다. IAM 정책을 별도 관리한다면 InstanceRoleName을 생략하고 템플릿의 두 정책과 같은 권한을 직접 붙인다. 로그 그룹 생성·보관 기간 변경 권한은 앱 역할에 주지 않는다.

호스트 CloudWatch Agent를 OS에 맞춰 설치한 뒤 EC2에서:

```sh
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s \
  -c file:/opt/keepgo/cloud/monitoring/cloudwatch-agent.json
```

Agent는 메트릭만 수집한다. 앱 로그는 Docker daemon이 인스턴스 역할을 이용해 전송하므로 Agent에 root 로그 읽기 권한이나 Docker 로그 glob 수집을 추가하지 않는다. CloudWatch에서 `CWAgent`의 InstanceId 집계 지표가 보이는지 확인한다. Agent 설치 직후 지표가 충분히 쌓이기 전에는 누락 알람이 발생할 수 있다. AWS API와 이미지 레지스트리로 나가는 HTTPS 경로가 필요하다.

## 4. 앱 로그 전송 활성화

기본 앱 Compose는 기존 json-file이다. **로그 그룹·IAM·실제 전송 확인 후** 호스트 marker를 만들면 deploy.sh가 `compose.cloudwatch.yaml`을 추가한다. IAM 준비 전 main 반영만으로 앱 로그 드라이버가 바뀌지 않는다.

1. EC2에서 아래 임시 컨테이너로 Docker daemon의 실제 전송을 확인한다. AWS 키를 컨테이너에 넣지 않는다.

   ```sh
   sudo docker run --rm --entrypoint /bin/sh \
     --log-driver awslogs \
     --log-opt awslogs-region=ap-northeast-2 \
     --log-opt awslogs-group=/keepgo/v1/application \
     prom/prometheus:v3.13.3 -c 'echo keepgo-cloudwatch-smoke'
   ```

2. CloudWatch Logs에서 위 메시지가 도착한 것을 확인한다. 이 검사는 로그 쓰기만 한다. 기존 IAM 전파가 끝나지 않았으면 기다린 뒤 재시도한다.
3. `sudo touch /opt/keepgo/runtime/cloudwatch-logs.enabled` 후 기존 **Deploy production**을 수동 실행한다. 설정 해시가 바뀌므로 앱 네 개가 순차 재생성된다. 짧은 중단이 가능하므로 점검 시간에 적용한다.
4. 서비스 이름/컨테이너 ID별 로그 스트림, `docker logs`, 외부 health를 확인한다. 기존 json-file 로그를 소급 전송하지는 않는다.

전송은 non-blocking, 메모리 버퍼 4MB다. CloudWatch 장애 때 버퍼가 차면 로그가 유실될 수 있다. 원격 로깅 장애를 견디는 영구 재전송 큐가 아니다. Docker 로컬 읽기 캐시(10MB × 3)는 최근 `docker logs`를 위한 것으로 별도 장기 백업이 아니다. **non-blocking도 최초 로그 스트림 생성 실패를 우회하지는 않는다.**

로그 설정 장애 시 marker 파일만 제거하고 동일 Cloud 버전으로 수동 재배포하면 json-file로 돌아간다. 기존 deploy.sh의 이미지 롤백은 로그 설정까지 되돌리지 않으므로 marker 제거와 재배포가 필요하다. 데이터 볼륨·CloudWatch 로그 그룹은 삭제하지 않는다.

```sh
sudo rm /opt/keepgo/runtime/cloudwatch-logs.enabled
# 이후 Actions에서 Deploy production 수동 실행
```

활성화 후 수동 앱 `up`에도 `-f compose.yaml -f compose.cloudwatch.yaml`을 함께 사용한다. 기본 Compose만으로 `up`하면 로그 드라이버를 다시 json-file로 바꿀 수 있다. `ps`·`logs` 같은 조회는 기존 명령으로 가능하다.

## 5. PG 설치와 접근

SSM 세션의 EC2에서 운영 앱이 정상인 것을 확인하고, 별도 checkout을 준비한다. 아래 COMMIT은 검토한 Cloud 커밋 SHA로 바꾼다.

```sh
sudo git clone "$(git -C /opt/keepgo/cloud remote get-url origin)" /opt/keepgo/observability
sudo git -C /opt/keepgo/observability checkout --detach COMMIT
```

EC2에 다음 파일을 준비한다. 값은 저장소·명령 이력·SSM 명령 출력에 남기지 않는다. SSM의 대화형 셸에서 `sudoedit`를 사용하거나 기존 비밀값 관리 절차로 배치한다.

| 파일 | 내용 | 권한 |
| --- | --- | --- |
| `/opt/keepgo/runtime/grafana_admin_password` | 무작위 관리자 비밀번호 한 줄 | 472:0, 0400 (Grafana UID 472가 읽음) |
| `/opt/keepgo/runtime/monitoring.env` | `DISCORD_WEBHOOK_URL=실제 URL` 한 줄 | root:root, 0600 |

상위 runtime 디렉터리는 기존 root:root 0700을 유지한다. Compose 파일 기반 secret은 호스트 파일 권한을 그대로 사용한다. GitHub Secret을 EC2가 자동으로 읽지는 않으므로 같은 Discord 채널용 값을 별도로 배치해야 한다. contact point는 파일 provisioning으로 주입하고, Grafana는 Webhook을 런타임 환경변수로 받는다. 관리자 권한의 `docker inspect`에서는 보일 수 있다. 비밀번호와 Webhook 없이 운영 모니터링을 시작하지 않는다.

```sh
cd /opt/keepgo/observability
sudo docker compose -f compose.monitoring.yaml config --quiet
sudo docker compose -f compose.monitoring.yaml pull
sudo docker compose -f compose.monitoring.yaml up -d --wait --wait-timeout 120
sudo docker compose -f compose.monitoring.yaml ps
```

운영자 PC에 AWS CLI와 Session Manager plugin을 준비하고:

```sh
aws ssm start-session --region ap-northeast-2 --target i-REPLACE \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["3001"],"localPortNumber":["3001"]}'
```

브라우저에서 `http://localhost:3001` → admin으로 로그인한다. Prometheus Targets 화면은 별도 터미널에서 동일 명령의 두 포트를 9090으로 바꿔 터널링한다. SSM의 대상 인스턴스 및 port forwarding document 사용 권한이 필요하며 SSH 인바운드는 필요 없다.

기본 대시보드는 `KeepGo / KeepGo V1 - Infrastructure and Health`다. 7개 기본 scrape target(prometheus, node, blackbox, 서비스 probe 4개)이 UP인지 확인한다. **probe의 `up=1`은 exporter 호출 성공일 뿐**이므로 `probe_success=1`도 서비스 4개 각각 확인한다. HTTP 프로브는 2xx 기준이며 Backend의 기존 `/actuator/health`가 DB 장애 때 503을 내는 계약을 따른다. AI health 응답이 실제 외부 AI 제공자까지 검사하는지는 앱 구현에 달려 있다.

## 6. BE·AI 지표를 연결할 때

Cloud가 [상세 메트릭 계약 v1](monitoring-metrics-contract.md), HTTP/BE/AI 대시보드와 초기 알림 규칙을 먼저 준비했다. 앱 코드는 이 저장소에 없으므로 endpoint 구현 완료로 간주하지 않는다. 기본 `monitoring/prometheus/targets/application.json`은 빈 배열이며 구현·공개 차단 검증을 통과한 항목만 등록한다. 아래 예시의 `metrics_contract=v1`은 상세 집계·알림 적용 조건이다.

```json
[
  {"targets":["backend:8080"],"labels":{"service":"backend","metrics_contract":"v1","__metrics_path__":"/actuator/prometheus"}},
  {"targets":["ai-api:8000"],"labels":{"service":"ai-api","metrics_contract":"v1","__metrics_path__":"/metrics"}}
]
```

BE는 Micrometer Prometheus registry와 Actuator 노출·접근 설정이 필요하다. 현재 healthcheck 포트·경로는 유지한다. AI는 Prometheus 형식의 요청 수·오류·지연 histogram을 노출한다. 사용자 ID·요청 원문·토큰·전체 URL을 label로 쓰지 않고 정규화된 route·method·status로 제한한다. Nginx의 모든 공개 우회 경로에서 metrics가 차단되는지 앱 팀과 확인한 뒤 등록한다. 공개 `/api` rewrite로 actuator가 노출되지 않는지도 점검한다. 관리 포트를 별도로 바꾸면 healthcheck·probe와 네트워크 계약도 함께 수정해야 한다.

file discovery는 약 30초 주기로 반영된다. `up{job="application"}=1`, 계약의 capability·class·count·bucket을 확인한 뒤 이미 준비된 대시보드와 초기 임계치를 실측으로 조정한다. 적용·검증·알림별 대응은 [앱 알림 운영 절차](monitoring-alert-runbook.md)를 따른다. 내부 health 지연 그래프는 실제 사용자 요청의 p95가 아니며, 없는 메트릭은 0으로 표현하지 않는다.

## 7. 변경·복구·인수 시험

PG 변경은 별도 checkout의 검토한 커밋으로 이동한 후 설정 검사 → `up -d --wait` → Prometheus·Grafana `restart` 순서로 반영한다. 파일 내용만 변경되면 Compose가 자동 재생성하지 않기 때문에 재시작으로 Prometheus 설정과 Grafana provisioning을 다시 읽는다. blackbox 설정 변경 시 blackbox-exporter도 재시작한다. 앱 자동 배포는 PG를 갱신하지 않는다.

PG 복구는 같은 checkout을 이전 검토 커밋으로 돌리고 동일 과정을 수행한다. Grafana 메이저 버전 업그레이드는 SQLite DB migration을 수반할 수 있어 사전에 볼륨 백업이 필요하고, 바이너리 downgrade만으로 복구를 보장하지 않는다. `down -v`는 데이터를 삭제하므로 일반 재배포에 사용하지 않는다.

| 시험 | 기대 결과 |
| --- | --- |
| Grafana contact point의 Test를 운영자가 실행 | Discord 수신. Webhook·네트워크 확인 |
| 합의한 점검 시간에 AI를 3분 이상 중지 후 시작 | 내부 service unhealthy 알림 → 복구 알림. 짧은 자동 재시작은 알리지 않음 |
| node-exporter를 3분 이상 중지 후 시작 | metrics collection 알림 → 복구 |
| Prometheus를 중지 후 시작 | Grafana NoData/Error 알림 → 정상 재개 |
| CloudWatch Agent를 15분 이상 중지 후 시작 | SNS 지표 누락 알람·복구 이메일 |
| 앱 로그 smoke + 실제 앱 요청 | 서비스별 CloudWatch 스트림에 새 로그 표시 |
| 앱 하나 재배포 | PG 컨테이너·볼륨 유지, DNS 재해석 후 probe 회복 |
| 관리 포트 외부 접속·공개 metrics 경로 확인 | 3001/9090 접근 불가, 앱 metrics 본문 노출 없음 |

Grafana 자체가 죽으면 Grafana 알림도 멈춘다. EC2 상태·외부 HTTPS 장애는 CloudWatch/Actions가 잡지만 **앱이 정상인 상태의 Grafana 단독 장애는 별도 외부 감시를 추가하기 전까지 자동 통보하지 못한다.** 재배포 후 `ps`·`api/health` 확인을 필수로 한다. PG 분리 시에는 사설망·SG·TLS/인증을 다시 설계하며 공개 scrape 포트를 열어 연결하지 않는다.

CloudWatch Logs 수집·보관·조회, custom metric·alarm, SNS 및 EC2/EBS 용량은 과금 대상이다. 무비용 구성으로 표현하지 않는다. 애플리케이션은 비밀번호·JWT·개인정보를 로그에 남기지 않고, 운영 DEBUG 로그와 고빈도 health access log를 제한한다. 월 비용은 실제 수집 GB·조회 범위·AWS 요금표로 산정한다.

근거: [Docker awslogs](https://docs.docker.com/engine/logging/drivers/awslogs/), [원격 로그의 로컬 캐시](https://docs.docker.com/engine/logging/dual-logging/), [CloudWatch Agent 설정](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Agent-Configuration-File-Details.html), [Prometheus 보관 한도](https://prometheus.io/docs/prometheus/latest/storage/), [Grafana 파일 알림 설정](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/), [Prometheus 배포 버전](https://prometheus.io/download/), [Grafana 배포 버전](https://grafana.com/grafana/download).
