# 2026-10-01 Grafana가 10초마다 재시작 (Discord Webhook 환경변수 누락)

## 🐞 에러 내용

- 모니터링 EC2(`i-0e2b9ff8599ff8023`)를 처음 설치하면서 `compose.monitoring.yaml`을 올렸다. Prometheus는 `healthy`가 됐지만 Grafana는 `--wait`에서 실패했다.

  ```
  ✔ Container keepgo-monitoring-prometheus-1    Healthy
  container keepgo-monitoring-grafana-1 is unhealthy
  keepgo-monitoring-grafana-1   Restarting (1) Less than a second ago
  ```

- `docker ps`로 보면 `Up 2 seconds` → `Up 12 seconds` → `Restarting` → `Up Less than a second`처럼 약 10초 주기로 재시작을 반복했다. `/api/health`는 응답이 없었다.
- Grafana 로그:

  ```
  level=error msg="Module failed" module=*pushhttp.Gateway err="failed to start *pushhttp.Gateway,
  because it depends on module provisioning, which has failed: ... failure to map file notifications.yml:
  failure parsing contact points: keepgo-discord: could not find webhook url property in settings"
  ```

## 🔍 원인 분석

`monitoring/grafana/provisioning/alerting/notifications.yml`은 Discord 연락처의 URL을 환경변수로 받는다.

```yaml
settings:
  url: $DISCORD_WEBHOOK_URL
```

Grafana는 이 값을 `/opt/keepgo/runtime/monitoring.env`(Compose `env_file`)에서 읽는다. 처음에는 이 파일에 **`DISCORD_WEBHOOK_URL=` 없이 URL만 한 줄** 들어 있었다. Compose는 `=`가 없는 줄을 변수로 만들지 않으므로 `$DISCORD_WEBHOOK_URL`이 빈 값이 됐다. 이후 웹훅을 새로 만들려고 파일을 비운 상태에서도 같은 오류가 났다.

```sh
sudo cat -A /opt/keepgo/runtime/monitoring.env | sed 's#https://[^$]*#URL#'
URL$          # 접두사 없이 URL만 있음
```

Grafana는 provisioning 모듈이 실패하면 **프로세스 전체가 종료**된다. `restart: unless-stopped` 때문에 바로 다시 뜨고 같은 이유로 다시 죽었다.

설치 절차(v1-monitoring.md 5-3절)에는 `DISCORD_WEBHOOK_URL=실제 URL` 한 줄이라고 적혀 있었다. 하지만 `nano`에 값을 붙여 넣는 과정에서 접두사가 빠졌고, 파일 형식을 확인하는 단계가 없어 `up`을 실행하기 전에 잡지 못했다.

**부수 문제:**

- 원인을 찾으려고 값을 가리는 명령(`sed 's#=.*#=<숨김>#'`)을 실행했는데, `=`가 없어서 URL이 그대로 출력됐다. 이 URL이 작업 대화에 노출됐다.
- 같은 확인에서 env 파일 권한이 `0644`로 남아 있었다. 설치 절차의 `chmod 0600`이 적용되지 않은 상태였다.

## ✅ 해결 방법

1. Discord에서 웹훅을 새로 만들고, 노출된 기존 웹훅은 삭제했다(권장 조치로 안내).
2. 값을 화면에 내지 않고 에디터로만 넣었다. 형식은 `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...` 한 줄이며 따옴표와 공백은 넣지 않는다.
3. 값은 보지 않고 형식만 확인한 뒤 권한을 고쳤다.

   ```sh
   F=/opt/keepgo/runtime/monitoring.env
   sudo grep -c '^DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/' $F   # 1이어야 함
   sudo wc -l $F                                                             # 한 줄
   sudo chmod 0600 /opt/keepgo/runtime/monitoring*.env
   ```

4. `env_file`은 컨테이너를 다시 만들어야 반영된다.

   ```sh
   cd /opt/keepgo/observability
   E=/opt/keepgo/runtime/monitoring-host.env
   sudo docker compose --env-file $E -f compose.monitoring.yaml up -d --force-recreate --wait grafana
   ```

이후 Grafana가 `healthy`로 떴고 로그인할 수 있었다.

Webhook이 없을 때 Grafana가 종료되는 동작은 고치지 않았다. 알림이 조용히 꺼진 채 운영되는 것보다 시작 실패로 드러나는 편이 낫다. 설치 문서에도 "비밀번호와 Webhook 없이 운영 모니터링을 시작하지 않는다"고 적혀 있다.

## 회고

- **비밀값 파일은 `up` 전에 형식을 검사한다.** 값을 보지 않고도 `grep -c '^KEY=https://…'`로 형식은 확인할 수 있다. 설치 절차에 이 확인을 넣었어야 했다.
- **값을 가리는 명령도 형식이 맞을 때만 가린다.** `sed 's#=.*#…#'`는 `=`가 있다는 전제가 있다. 형식이 틀린 파일을 볼 때는 `cat -A … | sed 's#https://[^$]*#URL#'`처럼 값 자체를 지우는 방식이 안전하다. 노출된 값은 즉시 교체한다.
- **"재시작 반복"은 바로 로그부터 본다.** `docker logs`에서 `level=info`를 빼고 보니 오류 한 줄로 원인이 나왔다.
