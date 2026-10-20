# 개발 BE·AI 모니터링 연결

2026-10-20. 현재 역할: **V1 인프라=운영, V2 인프라=개발**. 이 대응은 영구 규칙이 아니며 향후 역할 전환 시 수집·알림도 함께 전환한다.

## 범위와 변경

기존 모니터링 EC2·Prometheus·Grafana·Discord를 재사용한다. 개발 BE·AI만 연결한다. FE, 새 관측 저장소, OTel, AI provider/token/업무 outcome 계측은 후속 범위다.

- BE는 기존 `/actuator/prometheus`를 수집한다.
- AI는 main의 HTTP counter/histogram과 capability 계측을 develop에 선별 이식한다. 상세 422 응답과 개발 API 경로를 유지한다. [AI PR #49](https://github.com/100-hours-a-week/KTB4-8th-AI/pull/49)
- `application-dev` job과 `keepgo_dev:*` recording rule을 사용한다. 기존 운영 `application`·`keepgo:*` 집계와 분리한다.
- 개발 시계열은 `environment=development`, `cluster=keepgo-v2`를 가진다. 환경은 용도, cluster는 배포 인프라 식별자다.
- `[DEV] KeepGo - Application HTTP`, `[DEV] KeepGo - Backend JVM and DB Pool` 대시보드를 제공한다. AI 기본 HTTP 지표는 첫 대시보드에서 확인한다.
- 개발 경보는 별도 Grafana relay `[DEV] KeepGo application signal`로 기존 Discord에 전달한다. 그룹에 environment/cluster를 포함한다.

HTTP 200 업무 실패는 기본 HTTP 지표만으로 구분되지 않는다. 요청이 없으면 rate/지연이 No data일 수 있으며, 정상 0으로 대체하지 않는다. 개발 계측 누락은 capability로 판단해 무트래픽만으로 잘못 경보하지 않는다.

## 네트워크와 소유권

| 관리 주체 | 소유 리소스 |
| --- | --- |
| `keepgo-dev-monitoring` CloudFormation, [템플릿](../infrastructure/dev-monitoring.json) | Peering, 개발 app subnet 2개로의 경로, 모니터링 `/32` 반환 경로, BE 8081·AI 9464 수신, ECS 읽기 전용 IAM policy |
| 기존 `keepgo-v1-monitoring-host`, [템플릿](../infrastructure/monitoring-host.yaml) | 기존 SG의 개발 BE/AI 대상 송신 규칙. 선택 parameter 2개로 관리 |
| V2 Terraform | 기존 VPC·SG·route table 소유. 위 추가 개별 경로·수신 규칙을 중복 선언하지 않음 |

메트릭 포트를 공인 노출하지 않는다. BE 8081은 포트 단위 접근이며 URL 경로 제한은 아니다. 공유 모니터링 443의 기존 접근 정책은 유지된다. Peering은 양방향 라우팅이며 dev/prod 권한 격리를 완성하는 장치가 아니다.

기존 모니터링 SG는 egress를 inline으로 관리하므로 새 스택의 별도 Egress 리소스와 섞지 않는다. host 스택 갱신은 기존 ImageId·parameter를 유지하고 **인스턴스 교체가 없는 change set**인지 확인한다. CLI로 읽은 템플릿의 한글이 손실된 문제가 있어 저장소의 UTF-8 원본으로 다시 검증했으며, 최종 change set은 SG 송신 규칙만 수정한다.

피어링 자체 고정비는 없고 같은 AZ 전송은 무료다. 10월 20일 확인 시 BE는 2a, AI와 모니터링은 2c이므로 BE 경로에는 양쪽 합계 약 $0.02/GB 전송비가 적용된다. 예를 들어 응답 100KB를 30초마다 수집하면 30일 8.64GB, 약 $0.17이다. 실제 크기·task 수·프로토콜 overhead에 따라 달라진다. [AWS 요금](https://aws.amazon.com/vpc/pricing/)

## 자동 대상 발견

[발견 스크립트](../scripts/discover-dev-metrics.py)를 모니터링 호스트에서 30초마다 실행한다. 기존 host instance profile의 ECS API 권한을 쓰며 별도 키를 저장하지 않는다.

```bash
sudo systemctl status keepgo-dev-metrics.timer
sudo journalctl -u keepgo-dev-metrics.service --since '-15 min' --no-pager
sudo python3 /opt/keepgo/observability/scripts/discover-dev-metrics.py
```

서비스별 RUNNING task의 실행 중인 앱 container만 선택한다. 종료된 jwt-files sidecar는 제외한다. task 주소는 승인한 app subnet 안인지 확인한다. API 오류·조회 중 교체는 마지막 성공 파일을 보존하고 다음 tick에 재시도한다. 정상적으로 task가 0개면 이전 주소를 제거한다.

`development.json`은 runtime 생성 파일이다. 저장소의 빈 초기 파일로 덮어쓰지 않는다. 성공 시 mtime을 갱신하며 Prometheus의 `prometheus_sd_file_mtime_seconds`로 discovery 지연을 감시한다. 서비스가 없어지는 경우에는 `absent(up{...})` 경보가 별도로 발생한다.

## 검증과 적용 절차

**Git push/PR merge는 IaC 적용이 아니다.** Cloud 저장소 CI는 검증을 수행하며 아래 스택 명령과 모니터링 파일 배치는 별도다. AI develop은 기존 CI/CD가 자동 배포한다. 현재 배포/개발 역할 전환까지 자동으로 수행하는 워크플로는 추가하지 않았다.

현재 계정·서울 리전에서 재현하는 스택 명령은 다음과 같다. 먼저 계획만 만들고 출력된 change set을 검토한다. 인프라 재생성·역할 전환 후에는 아래 ID를 새 실제 값으로 갱신한다.

```bash
aws cloudformation deploy --region ap-northeast-2 \
  --stack-name keepgo-dev-monitoring \
  --template-file infrastructure/dev-monitoring.json \
  --capabilities CAPABILITY_IAM --no-execute-changeset \
  --parameter-overrides \
    MonitoringVpcId=vpc-028e5c0c4fa690a01 DevelopmentVpcId=vpc-0bfd4e11c520dc5fd \
    MonitoringRouteTableId=rtb-0b0f52fba7c41ca82 DevelopmentRouteTableId=rtb-05fb8bcbd1b458f6f \
    MonitoringSecurityGroupId=sg-0e6562fdb95325e5a BackendSecurityGroupId=sg-0dd66b4b150b00bcd \
    AiSecurityGroupId=sg-01f3a77725d2bf7d5 MonitoringPrivateCidr=172.31.34.195/32 \
    MonitoringRoleName=keepgo-v1-monitoring-host-MonitoringRole-aPO7SRtnPXMR

# 출력된 change-set ARN을 아래에 넣는다. 최초 생성은 연결 관련 7개 리소스만 Add여야 한다.
aws cloudformation execute-change-set --region ap-northeast-2 --change-set-name CHANGE_SET_ARN
# 최초 생성은 stack-create-complete, 이후 갱신은 stack-update-complete로 기다린다.
aws cloudformation wait stack-create-complete --region ap-northeast-2 --stack-name keepgo-dev-monitoring

aws cloudformation deploy --region ap-northeast-2 \
  --stack-name keepgo-v1-monitoring-host \
  --template-file infrastructure/monitoring-host.yaml \
  --capabilities CAPABILITY_IAM --no-execute-changeset \
  --parameter-overrides \
    DevBackendSecurityGroupId=sg-0dd66b4b150b00bcd DevAiSecurityGroupId=sg-01f3a77725d2bf7d5
# 기존 스택에서 생략한 parameter는 이전 값을 사용한다. EC2/LaunchTemplate 교체는 중단한다.
aws cloudformation execute-change-set --region ap-northeast-2 --change-set-name CHANGE_SET_ARN
aws cloudformation wait stack-update-complete --region ap-northeast-2 --stack-name keepgo-v1-monitoring-host
```

두 명령의 `CHANGE_SET_ARN`은 서로 다른 출력값이다. 변경 없음 메시지가 나오면 execute를 다시 실행하지 않는다. 네트워크 적용 후에도 아래 앱·수집기·Grafana 적용을 끝내야 모니터링이 연결된다.

1. AI PR에서 고정 dependency 설치·계측 테스트·Docker build를 통과시킨다. develop 반영 후 기존 V2 CD의 실제 task image digest를 확인한다.
2. 네트워크 change set에서 새 연결 리소스만 추가되는지 확인하고 적용한다. host egress는 SG만 수정되는지 확인한다.
3. 기존 모니터링 파일의 내용이 점검 시점과 같은지 확인하고 백업한다. 기존 TSDB/Grafana volume을 유지한다.
4. 발견 스크립트·systemd unit을 설치하고 첫 조회를 실행한다. 모니터링 호스트에서 실제 BE/AI endpoint 응답을 확인한다.
5. `promtool check config`와 규칙 테스트를 통과한 설정을 배치하고 Prometheus에 SIGHUP을 보낸다. Grafana alerting provisioning을 reload한다. 대시보드는 기존 file provider가 갱신한다.
6. 기존 target 9개와 개발 target의 up, capability, 환경 구분, 실제 scrape 응답 크기, discovery mtime을 확인한다.
7. 개발용 시험 경보를 별도 signal로 발생·해제하고 Discord 전송 성공을 검증한다. 실제 서비스 장애를 만들지 않으며 시험 규칙을 제거한다.

로컬/CI 검증:

```bash
python scripts/render-app-monitoring.py --check
python scripts/render-dev-monitoring.py --check
python -m unittest discover -s tests -p test_dev_monitoring.py
promtool test rules tests/prometheus/application.test.yml tests/prometheus/development.test.yml
```

개발 산출물은 [생성 스크립트](../scripts/render-dev-monitoring.py)를 수정한 뒤 재생성한다. 생성 JSON/YAML만 직접 수정하지 않는다.

## 장애 대응과 복구

- `scrape_down`: 실제 task 상태·endpoint listener·SG·route를 확인한다. AI 8000 정상이어도 9464가 실패할 수 있다.
- `target_missing`: task 0개인지 discovery 실패인지 구분한다. 의도한 개발 중지라면 해당 환경만 알림을 일시 중지한다.
- `discovery_stale`: timer/service 로그와 instance profile의 ECS 권한을 확인한다. timestamp label을 매번 바꿔 시계열을 만들지 않는다.
- `http_metrics_missing`: capability 계측 버전과 실제 image를 확인한다. provider/token 지표 미제공은 이번 연결의 장애가 아니다.

롤백은 개발 relay를 중지하고 이전 모니터링 파일을 복원·검증·reload한 뒤 timer를 중지한다. host 스택의 Dev SG parameter를 빈 값으로 돌려 송신 규칙을 제거하고 마지막에 개발 연결 스택만 삭제한다. 운영 수집·데이터 volume·V2 VPC/앱 리소스는 삭제하지 않는다. 변경 전 파일과 적용 결과는 실행 기록에 보관한다.

## V1/V2 역할을 바꿀 때

V2를 운영으로 전환할 때 단순히 기존 dev 시계열의 이름을 운영으로 해석하지 않는다.

1. 전환 시각과 각 서비스의 역할을 결정하고 새로운 운영 수집·경보를 준비한다.
2. discovery의 서비스/cluster/env, job·recording rule·대시보드·relay를 함께 전환한다. `keepgo_dev:*` 집계에 새 운영 데이터를 계속 넣지 않는다.
3. 환경 라벨이 달라진 데이터는 새 시계열이 된다. 과거 개발 이력은 당시 라벨 그대로 보존하고 전환 annotation을 남긴다.
4. V1을 개발로 남길지 종료할지에 따라 기존 운영 경보·접근 권한을 정리한다. Grafana 데이터 보존과 주소 변경은 별도로 검증한다.
5. 이 시점에 개발을 CloudWatch만으로 줄이거나 관리형으로 이전할지 다시 비교한다. 모니터링 EC2를 없애려면 현재 담당하는 운영 관측도 대체해야 한다.

## 실행 기록

- 2026-10-20: 기존 도구 우선 연결 및 main AI 계측 재사용을 사용자 승인. 역할 전환 계획 확인.
- AI PR #49: 테스트·컨테이너 빌드 통과 후 develop에 병합, commit `54cc4581f40af9d3b936447644c880ec4e63df3d`.
- 개발 연결 스택 생성 완료. host 송신 설정·앱 rollout·수집·알림 검증은 후속 실행 결과로 갱신한다.
