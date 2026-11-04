# 새 V2 개발 서버 모니터링 연결

- 처음 조사: **2026-11-03**. 그때는 아무것도 바꾸지 않고 할 일만 정리했다.
- 완료: **2026-11-04**. main `eb5358e`(PR #230)를 모니터링 EC2에 반영했고 개발 BE·AI 수집을 확인했다.

## 1. 지금 상태 (11-04 조회)

| | 운영 | 개발 |
| --- | --- | --- |
| ECS 클러스터 | `keepgo-v2` | `keepgo-v2-dev` |
| 서비스 | `keepgo-v2-backend`, `keepgo-v2-ai-api` | `keepgo-v2-dev-backend`, `keepgo-v2-dev-ai-api` |
| VPC | `vpc-0bfd4e11c520dc5fd` `10.20.0.0/16` | `vpc-0306fb7cd5d39dc7d` `10.30.0.0/16` |
| app subnet | `10.20.10.0/24`, `10.20.11.0/24` | `10.30.10.0/24`(2a), `10.30.11.0/24`(2c) |
| 모니터링 EC2와 피어링 | `pcx-05cde5410c13d5275` (CloudFormation) | `pcx-0d85abb63fa4bb702` (**Terraform**, 11-03~04 사이 생성) |
| Prometheus job / 대상 파일 | `application-dev` / `targets/development.json` | `application-v2-dev` / `targets/v2-dev.json` |
| Grafana | `[PROD V2]` 대시보드·경보 | `[DEV]` 대시보드·경보 |

## 2. 한 일

### 2.1 네트워크 — 이미 되어 있었다

11-03 문서에는 "CloudFormation 스택을 새로 만든다"고 적었다. 11-04에 다시 조회해 보니 V2 dev Terraform이 이미 다 만들어 두었다. **AWS는 바꿀 것이 없다.**

- 피어링 `pcx-0d85abb63fa4bb702` (태그 `ManagedBy=Terraform`, `Name=keepgo-v2-dev-monitoring`)
- 경로: 개발 app route table `rtb-08a6d1c9c804631a9` → `172.31.34.195/32`, 모니터링 route table `rtb-0b0f52fba7c41ca82` → `10.30.10.0/24`·`10.30.11.0/24`
- 개발 BE SG `sg-0da1e69fc8a2ff3a3` 8081, AI SG `sg-0b2c0f45657488468` 9464 수신: 모니터링 SG `sg-0e6562fdb95325e5a`에서 허용
- 모니터링 SG 송신 8081·9464: 개발 SG 2개로 허용 (설명 `scrape v2-dev ...`)
- 모니터링 EC2 Role에 inline policy `keepgo-v2-dev-metrics-discovery` (ECS 조회)
- 확인: 모니터링 EC2에서 개발 BE `:8081/actuator/prometheus`, AI `:9464/metrics` 둘 다 **200**

> 주의: 모니터링 SG는 CloudFormation 스택 `keepgo-v1-monitoring-host` 소유다. 그런데 개발용 송신 규칙은 Terraform이 넣었다. 이 스택에서 SG 송신 규칙을 바꾸는 업데이트를 하면 CloudFormation이 템플릿에 없는 규칙을 지울 수 있다. 그 스택을 고칠 때는 change set에서 SG 변경 여부를 먼저 본다.

### 2.2 코드 — main PR 브랜치 `feat/v2-dev-monitoring`

| 커밋 | 내용 |
| --- | --- |
| `1783672` | `targets/development.json`을 Git에서 뺀다. `chore/untrack-dev-metrics-targets`와 같은 변경이라 그 브랜치 PR은 따로 낼 필요 없다 |
| `ae4aa67` | `discover-dev-metrics.py`가 클러스터마다 파일을 따로 쓴다. 한쪽 조회가 실패해도 다른 쪽 파일은 갱신된다 |
| `f1f1dcc` | `application-v2-dev` job, `keepgo_v2dev:` 기록 규칙, `KeepGoV2Dev*` 경보, `[DEV]` 대시보드 2개, `[DEV]` Discord relay |

- 운영 쪽 생성 파일(`dev-*.json`, `development-*.yml`, `development.json` relay)은 **한 글자도 안 바뀐다.** 운영 job 이름도 그대로라 운영 지표 이력이 끊기지 않는다.
- 11-03 계획에는 "운영 job을 `application`으로 바꾼다"가 있었다. 이번에는 하지 않았다. 운영 대시보드·경보 이름을 모두 바꿔야 하고 이력도 끊기기 때문이다. 이름 정리는 따로 한다.
- 검사: `promtool check config`, `promtool test rules`(운영·개발 테스트 모두), `render-*.py --check`, `test_dev_monitoring.py` 6개, `test_monitoring.py` 통과.
- prep에도 같은 코드를 넣었다. 그 전에 prep에 빠져 있던 main `852856c`(운영 라벨)를 먼저 가져왔다.

## 3. 남은 일

- [x] `feat/v2-dev-monitoring` → main 병합 (PR #230, `eb5358e`)
- [x] 모니터링 EC2를 `eb5358e`로 옮겼다 (아래 4절). 백업: `/opt/keepgo/development.json.bak-20261104`
- [x] `/api/v1/targets?state=active`: `application-dev` 2개, `application-v2-dev` 2개 모두 `up`
- [x] 반영 직후 pending/firing 경보 0건. 개발 BE `http·jvm·db_pool`, AI `http` capability 수집. `keepgo-v2-dev-*` 규칙 19개 모두 `ok`
- [ ] Grafana `[DEV] KeepGo - Application HTTP` 대시보드에 개발 데이터가 보이는지 눈으로 확인한다
- [ ] (선택) `[DEV]` Prometheus 시험 경보로 Grafana relay → Discord 전달을 확인한다. 운영 relay와 같은 경로라 생략해도 된다
- [ ] [컷오버 계획](v2-prod-cutover-plan.md) 5.4절을 실제 구조(V1 대신 새 V2 개발 환경)에 맞게 고친다

## 4. 모니터링 EC2 반영 (11-04 실행한 순서)

`development.json`을 Git에서 빼는 커밋으로 **처음** 옮기는 것이라, 서버에서 바뀐 이 파일을 먼저 되돌려야 checkout이 된다([구성](v1-monitoring.md) 7절). checkout하면 이 파일이 지워지므로 바로 timer 서비스를 한 번 돌려 다시 만든다.

모니터링 EC2 (SSM, `sudo -i` 후). `ssm-user`로 실행하면 git이 `dubious ownership`으로 멈춘다. `safe.directory`는 추가하지 않는다:

```sh
cd /opt/keepgo/observability;
git fetch origin && C=$(git rev-parse origin/main);
T=monitoring/prometheus/targets/development.json;
E=/opt/keepgo/runtime/monitoring-host.env;
DC="docker compose --env-file $E -f compose.monitoring.yaml";
git checkout -- $T && git checkout --detach $C;
```

checkout이 성공했을 때만:

```sh
systemctl start keepgo-dev-metrics.service;
ls -l monitoring/prometheus/targets/;
$DC config --quiet && $DC restart prometheus grafana;
```

확인:

```sh
U='http://127.0.0.1:9090/api/v1/targets?state=active';
P='"(scrapePool|health)":"[^"]*"';
curl -s $U | grep -oE "$P";
```

## 5. 참고

- 전송비: 모니터링 EC2는 2c에 있다. 개발 task가 2a에 뜨면 AZ 간 전송비가 붙지만 월 몇십 센트 수준이다([runbook](dev-monitoring-runbook.md) 계산 참고).
- `infrastructure/dev-monitoring.json`(CloudFormation)은 운영 VPC 연결용으로만 쓰인다. 개발 VPC 연결은 Terraform 소유라 이 템플릿으로 스택을 새로 만들지 않는다.

## 6. CloudWatch → Discord 중계도 같이 고쳤다

같은 날 "운영 알림이 `[DEV]`로 온다"는 제보로 확인했다. 원인은 Grafana가 아니라 CloudWatch 중계 Lambda `keepgo-alerts-discord`였다.

- 10-21에 만들 때 `keepgo-v2`가 개발이어서 `keepgo-v2-alerts`=`[DEV]`, `keepgo-v1-alerts`=`[PROD]`로 박혀 있었다.
- 새 개발 주제 `keepgo-v2-dev-alerts`에는 구독이 없었다. 그래서 개발 CloudWatch 경보는 Discord에 오지 않았다.
- `infrastructure/alerts-discord.yaml`을 고쳐 change set으로 적용했다(prep `2591375`): V1=`[V1]`, V2=`[PROD]`, V2 dev=`[DEV]` 구독 추가. Lambda·구독 교체 없음.
- 시험 메시지 1건으로 `[DEV]` Discord 수신을 확인했다.
- 이 템플릿은 아직 main에 없고 prep에만 있다.
