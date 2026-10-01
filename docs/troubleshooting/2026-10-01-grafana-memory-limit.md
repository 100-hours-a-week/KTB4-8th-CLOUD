# 2026-10-01 Grafana 접속 중 "Failed to fetch" (메모리 상한 256 MiB 근접)

## 🐞 에러 내용

- 모니터링 EC2의 Grafana에 SSM 포트 포워딩(`localhost:3001`)으로 로그인한 뒤 화면을 이동하다가 브라우저에 **Failed to fetch**가 떴다.
- 터널 창(PowerShell)에는 연결은 받지만 대상 포트에 붙지 못한다는 메시지가 반복됐다.

  ```
  Connection accepted for session [keepgo-grafana-tunnel-…]
  Connection to destination port failed, check SSM Agent logs.
  ```

- 직후 모니터링 EC2에서 확인한 상태:

  ```
  keepgo-monitoring-grafana-1     Up 2 minutes (healthy)
  keepgo-monitoring-prometheus-1  Up 22 minutes (healthy)
  OOMKilled=false exit=0 restarts=1
  keepgo-monitoring-grafana-1     242.9MiB / 256MiB
  keepgo-monitoring-prometheus-1  50.4MiB / 512MiB
  ```

## 🔍 원인 분석

- 터널(SSM)은 정상이었다. "Connection to destination port failed"는 **EC2 안의 `127.0.0.1:3001`이 응답하지 않을 때** 나온다. 브라우저의 "Failed to fetch"도 Grafana가 보낸 오류가 아니라 연결 자체가 실패했다는 뜻이다.
- Grafana는 `restarts=1`로 한 번 재시작한 직후였다. 터널 실패는 그 재시작 구간과 겹친다.
- 재시작 뒤 2분 만에 메모리가 **상한 256 MiB의 95%(242.9 MiB)**였다. Grafana 13은 대시보드 4개와 알림 규칙을 불러오고 로그인 세션을 처리하면서 이 정도를 쓴다. 상한을 넘으면 커널이 프로세스를 종료한다.
- `OOMKilled=false`는 재시작 후 현재 실행분의 상태라서, 이전 종료가 메모리 때문이었다고 기록으로 확정하지는 못했다. 다만 상한 바로 밑에서 도는 상태라 **같은 문제가 반복될 가능성이 높다**고 판단했다.
- 상한 256 MiB는 [TD-024](../technical-decisions.md#td-024--모니터링-전용-인스턴스-분리) 이전, 앱과 같은 4 GiB 호스트에 둘 때 정한 값이다. 실제 Grafana를 띄워 본 적 없이 추정으로 정했다.

## ✅ 해결 방법

`compose.monitoring.yaml`에서 Grafana의 `mem_limit`을 256m → **512m**로 올렸다(prep `a1e60ea`, PR 브랜치 `7bd11b7`). 모니터링 EC2(t4g.small, 2 GiB)는 Prometheus 512m + Grafana 512m를 합쳐도 1 GiB라 OS와 Agent를 더해도 여유가 있다. Prometheus는 실측 50 MiB라 상한을 그대로 뒀다.

모니터링 EC2에 반영하는 명령:

```sh
cd /opt/keepgo/observability
sudo git fetch -q origin feat/monitoring-host-split
sudo git checkout -q --detach 7bd11b7
E=/opt/keepgo/runtime/monitoring-host.env
sudo docker compose --env-file $E -f compose.monitoring.yaml up -d --wait grafana
sudo docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'   # grafana … / 512MiB
```

Grafana 데이터(비밀번호, 설정)는 named volume에 있어 재생성해도 유지된다.

**확인 방법 (적용 확인 대기):** 반영 후 대시보드를 몇 분 사용한 뒤 메모리 사용량과 재시작 횟수가 늘지 않는지 본다.

```sh
F='{{.State.OOMKilled}} exit={{.State.ExitCode}} restarts={{.RestartCount}}'
sudo docker inspect -f "$F" keepgo-monitoring-grafana-1
```

터널에서 같은 메시지가 다시 나오면 먼저 위 명령으로 Grafana가 재시작했는지 확인한다. 터널이 그냥 끊긴 경우(유휴 20분, PC 절전)에는 터널 창이 프롬프트로 돌아와 있으므로 명령을 다시 실행하면 된다.

## 회고

- **처음 띄우는 컨테이너의 메모리 상한은 추정값이다.** 설치 직후 `docker stats`로 실측하고 상한과의 거리를 확인했어야 했다. 상한 바로 밑에서 도는 컨테이너는 사용량이 잠깐만 튀어도 죽는다.
- **"Failed to fetch"와 터널 메시지는 서로 다른 층의 증상이다.** 브라우저 → 터널 → EC2 포트 순서로 어디서 끊겼는지 보면 원인을 빨리 좁힐 수 있다. 이번에는 터널 창의 "destination port failed"가 EC2 쪽 문제임을 바로 알려 줬다.
