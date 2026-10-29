# 2026-10-29 V1 중지 후에도 V1 수집 실패 알림이 계속 옴

## 🐞 에러 내용

2026-10-27 V1 앱 EC2(keepgo-01)를 중지하고, 같은 날 V1 수집 대상을 빼는 변경을 main에 넣었다(main `cde9e57`, prep `c1e48bc`). 그런데 10-29까지 Grafana가 V1 대상 수집 실패 알림을 Discord로 계속 보냈다.

모니터링 EC2에서 checkout을 옮기려 하자 git이 멈췄다.

```
error: Your local changes to the following files would be overwritten by checkout:
        monitoring/grafana/provisioning/alerting/notifications.yml
        monitoring/grafana/provisioning/alerting/rules.json
        monitoring/prometheus/prometheus.yml
error: The following untracked working tree files would be overwritten by checkout:
        monitoring/grafana/dashboards/dev-application-http.json
        ...
        scripts/discover-dev-metrics.py
Aborting
```

## 🔍 원인 분석

- **모니터링 EC2 반영이 빠졌다.** 모니터링 EC2 설정은 사람이 checkout하고 재시작해야 바뀐다([구성](../v1-monitoring.md) 7절). main 병합만 하고 서버 반영을 하지 않아, 서버는 예전 커밋 `9a67f5e`로 꺼진 V1을 계속 수집했다.
- **서버 checkout에 Git 밖에서 놓은 파일이 있었다.** 10-20 dev 모니터링을 연결할 때 파일을 checkout에 직접 배치했다([개발 모니터링 절차](../dev-monitoring-runbook.md)). 그래서 tracked 파일 3개는 수정 상태, dev 파일 9개는 untracked 상태였고 git이 덮어쓰기를 거부했다.
  - 파일별로 비교해 보니 서버에서만 고친 내용은 없었다. `rules.json`·`prometheus.yml`은 V1 제거 직전 커밋과 같았고, 나머지는 새 커밋과 같았다.
  - 다른 것은 `targets/development.json` 하나였다. 이 파일은 timer가 30초마다 다시 쓰는 runtime 파일인데 Git에도 올라가 있었다. 그래서 커밋 사이에 내용이 다르면 매번 checkout을 막을 수 있는 구조였다.
- **checkout이 실패했는데 재시작이 그대로 실행됐다.** 명령을 `;`로만 이어서 실패해도 다음 줄이 돌았다. 재시작 결과 `Started`만 보고 성공으로 오해하기 쉬웠다.
- **재시작 직후 `up` 조회에 V1 대상이 남아 보였다.** 재시작하면 stale 표시가 남지 않는다. 그래서 최근 5분 조회 범위 안의 마지막 값이 보였다. [2026-10-02 사례](2026-10-02-backend-8081-health-false-alert.md)와 같은 현상이다. 실제 수집 대상은 `/api/v1/targets?state=active`로 확인한다.

## ✅ 해결 방법

1. 서버에서 checkout을 막는 파일만 `/opt/keepgo/obs-local-1029.tgz`로 백업했다.
2. 파일마다 `git show <커밋>:<파일> | cmp`로 새 커밋과 비교해 서버에서만 고친 내용이 없는 것을 확인했다.
3. `git stash push -u -m "before c1e48bc 1029"`로 보관한 뒤 checkout했다. 처음에는 prep 커밋으로 옮겼다가, 서버 기준인 main 최신 `b71f94c`로 다시 맞췄다. main에는 같은 V1 제거와 V2 라벨 변경(`852856c`)이 이미 들어 있었다.
4. `systemctl start keepgo-dev-metrics.service`로 `development.json`을 다시 만들고 Prometheus·Grafana를 재시작했다.
5. `targets/development.json`을 Git 관리에서 뺐다(`.gitignore`). 이 변경으로 처음 옮길 때만 이 파일이 checkout을 막을 수 있다. 그때 처리 방법은 [구성](../v1-monitoring.md) 7절에 적었다.

## 회고

- 인프라를 끄는 일은 저장소 변경으로 끝나지 않는다. **main 병합 → 모니터링 EC2 checkout·재시작 → 실제 수집 대상 확인**까지 해야 끝난다.
- 모니터링 EC2 checkout은 항상 main 커밋으로 맞춘다. prep 같은 작업 브랜치 커밋을 서버에 올리지 않는다.
- checkout 뒤 명령은 `&&`로 이어서, checkout이 실패하면 재시작이 돌지 않게 한다.
- 10-02에도 `application.json`을 직접 고쳐서 같은 이유로 checkout이 멈췄다. 두 번째다. 서버 파일은 Git으로만 바꾸고, runtime 파일은 Git에 두지 않는다. 같은 일이 또 생기면 SSM Run Command로 반영을 자동화하는 방안을 검토한다.
