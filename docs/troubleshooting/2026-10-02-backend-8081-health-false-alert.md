# 2026-10-02 BE 관리 포트 전환 후 Backend health 오탐

## 🐞 에러 내용

2026-10-02 15:10(KST) BE 이미지 `d88350649240`(BE #64, Prometheus 지표)이 자동 배포된 뒤 Grafana 알림이 Discord로 왔다.

```
[FIRING:1] KeepGo internal service unhealthy KeepGo backend
instance = http://backend:8080/actuator/health
job = service-health  severity = warning
summary = Internal HTTP health probe failed for 3 minutes.
```

Backend는 정상이었다. 수정 후 확인한 `probe_success`는 8081 대상이 `1`, 이전 8080 대상이 `0`이었다.

## 🔍 원인 분석

- BE #64가 `management.server.port: 8081`을 넣어 Actuator 전체(`/actuator/health` 포함)가 8081로 옮겨 갔다. 8080에서는 health가 응답하지 않는다.
- 전환은 [계약](../monitoring-metrics-contract.md) 0절과 [구성](../v1-monitoring.md) 2-1절에 계획돼 있었다. 앱 EC2의 compose healthcheck는 미리 "8081 먼저, 실패하면 8080"으로 바꿔 두어 배포가 롤백되지 않았다.
- 모니터링 EC2의 blackbox 대상(`prometheus.yml`의 `service-health`)은 "8081 이미지가 배포되면 바꾼다"는 주석만 있고 8080 그대로였다. 대체 경로가 없어 배포 직후부터 실패했고, 3분 뒤 알림이 울렸다.
- 앱 자동 배포는 Prometheus 설정을 갱신하지 않는다. 앱 이미지가 바뀌는 시점(Auto release가 10분마다 결정)과 모니터링 설정이 바뀌는 시점(사람이 checkout)이 따로 움직인다. BE PR 병합 시점에 Cloud 쪽 후속 작업이 준비돼 있지 않았다.

## ✅ 해결 방법

1. Cloud #58(`1b5731a`, 15:27 KST 병합): `prometheus.yml`의 backend 대상을 `http://backend:8081/actuator/health`로 바꾸고, 같은 PR에서 compose healthcheck의 8080 재시도도 지웠다(backend·ai-api 재생성 감수).
2. 모니터링 EC2에서 checkout을 `origin/main`으로 옮기고 `docker compose … restart prometheus`를 실행했다. 처음에는 `sudo -i` 없이 실행해 `dubious ownership`, `permission denied`로 멈췄고, root 셸에서 다시 실행했다.
3. `probe_success{service="backend"}`가 8081 대상 `1`로 나오는 것을 확인했다. 8080 대상의 `0`은 재시작 때문에 stale 표시가 남지 않은 마지막 값이고, 5분 조회 범위가 지나면 사라진다.

## 회고

- 다른 저장소 변경에 맞춰 Cloud 설정을 바꿔야 하는 경우, "배포되면 바꾼다" 주석만으로는 놓친다. 앱 PR을 병합하기 전에 Cloud PR을 같이 준비해 두고, 병합 직후 함께 반영한다.
- 모니터링 EC2 설정은 수동 반영이라 앱 배포와 시점이 어긋날 수 있다. 반영 절차(root 셸, `cd`, checkout, 필요 시 재시작)는 [구성](../v1-monitoring.md) 7절에 표로 정리했다. 반복되면 SSM Run Command로 자동 반영하는 workflow를 검토한다.
- 같은 날 대상 등록(Cloud #67) 때는 모니터링 EC2 checkout의 `application.json`이 수동으로 고쳐져 있어 checkout이 멈췄다. 서버 checkout은 Git으로만 바꾼다.
