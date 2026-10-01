# 트러블슈팅

실제로 겪은 문제를 사례별 문서 하나씩으로 모은다. 새 문제는 `YYYY-MM-DD-짧은-설명.md`로 추가하고 아래 표에 한 줄을 넣는다. 각 문서는 다음 양식을 따른다.

```markdown
# YYYY-MM-DD 오류명

## 🐞 에러 내용
## 🔍 원인 분석
## ✅ 해결 방법
## 회고
```

## 사례 목록

| 날짜 | 문제 | 영향 | 상태 |
| --- | --- | --- | --- |
| 2026-10-01 | [Grafana 접속 중 "Failed to fetch" (메모리 상한 256 MiB 근접)](2026-10-01-grafana-memory-limit.md) | 대시보드 접속이 끊김. 알림 평가도 재시작 동안 멈춤 | 수정 (512 MiB), EC2 반영·확인 대기 |
| 2026-10-01 | [Grafana가 10초마다 재시작 (Discord Webhook 환경변수 누락)](2026-10-01-grafana-webhook-env-missing.md) | 모니터링 최초 설치 지연. Webhook URL 노출 | 해결 (형식 수정, 웹훅 교체 권장) |
| 2026-10-01 | [release PR의 Validate가 매번 실패로 표시됨 (승인 만료)](2026-10-01-release-pr-validate-expired.md) | 배포 영향 없음. 릴리스마다 빨간 X가 쌓여 진짜 실패를 가림 | 수정 (`[skip ci]`), 다음 릴리스에서 확인 대기 |
| 2026-09-30 | [SENTRY_DSN 형식 오류로 AI 배포 자동 롤백](2026-09-30-ai-sentry-dsn-rollback.md) | 새 AI 버전·설정이 약 1시간 반 미반영, 알림 없음 | 복구됨, 재발 방지 TODO |
| 2026-09-30 | [GitHub Actions schedule이 한 번도 실행되지 않음](2026-09-30-actions-schedule-not-running.md) | 자동 배포·외부 감시가 돌지 않음 | 우회 해결 (EventBridge), 조직 원인 문의 중 |
| 2026-09-30 | [변경 없는 배포가 backend·ai-api를 매번 재생성](2026-09-30-env-file-services-recreated-every-deploy.md) | 배포마다 두 서비스 재시작·순단, 배포 시간 약 2분 증가 | 해결 (#23, 운영 `unchanged` 확인) |
| 2026-09-30 | [첫 수동 배포가 13분 걸림 (승인 대기)](2026-09-30-deploy-approval-wait.md) | 배포가 승인자 확인 전까지 멈춤 | 해결 (승인자 제거) |
| 2026-09-30 | [JSON Manifest가 main보다 이전 backend를 가리킴](2026-09-30-manifest-backend-regression.md) | 병합 시 backend가 이전 버전으로 되돌아갈 뻔함 | 해결 (병합 전 발견) |
| 2026-09-30 | [Validate에서 `backend.env not found`](2026-09-30-validate-env-file-not-found.md) | PR 검사 실패로 병합 불가 | 해결 |
| 2026-09-29 | [구현·로컬 검증 중 겪은 문제 모음](../archive/v1-implementation-notes-2026-09-29.md) | — | 보관 |

## 증상으로 찾기

| 증상 | 먼저 볼 곳 |
| --- | --- |
| Auto release·Health check가 주기적으로 안 돎, Actions에 `schedule` 실행이 없음 | [schedule 미실행](2026-09-30-actions-schedule-not-running.md), [운영 절차](../v1-operations.md) 11절 |
| 배포 결과가 `rolled_back`, 컨테이너가 `Restarting` 반복 | [SENTRY_DSN 롤백](2026-09-30-ai-sentry-dsn-rollback.md) — Actions의 Wait for deployment result 로그에서 컨테이너 로그 확인 |
| 바뀐 게 없는데 배포가 서비스를 교체함 | [배포마다 재생성](2026-09-30-env-file-services-recreated-every-deploy.md) |
| release PR의 Validate가 `required approval but was not approved before it expired`로 실패 | [release PR Validate 만료](2026-10-01-release-pr-validate-expired.md) — 배포 영향 없음 |
| Deploy production이 시작하지 않고 "Review needed" | [승인 대기](2026-09-30-deploy-approval-wait.md) |
| CI의 `docker compose config`가 로컬에서는 되는데 러너에서 실패 | [Validate 실패](2026-09-30-validate-env-file-not-found.md) |
| 배포 결과 코드(`rolled_back`, `pull_failed` 등)의 뜻과 조치 | [배포 검증 및 롤백](../v1-deployment-verification-and-rollback.md) |
| Discord 알림이 오거나 안 옴 | [장애 알림 시스템](../v1-alerting.md) |
| Grafana가 `Restarting` 반복, 로그에 `could not find webhook url property` | [Webhook 환경변수 누락](2026-10-01-grafana-webhook-env-missing.md) |
| Grafana 터널에서 "Failed to fetch" 또는 `Connection to destination port failed` | [Grafana 메모리 상한](2026-10-01-grafana-memory-limit.md) — 먼저 `docker ps`로 Grafana 재시작 여부 확인 |
| EC2에서 직접 상태를 확인하는 방법 | [운영 절차](../v1-operations.md) 5절 「직접 확인」, 10절 「증상별 빠른 확인」 |

## EC2에서 자주 쓰는 확인 명령

SSM 접속 후 `sudo -i`로 root가 되어 실행한다. `ssm-user`로 docker를 실행하면 `permission denied`가 난다.

```bash
tail -5 /opt/keepgo/state/history.log                       # 배포마다 한 줄: 시각, Cloud 커밋, 결과, 교체한 서비스
cat /opt/keepgo/state/failed-images                         # 차단된 이미지
docker ps --format '{{.Names}} | {{.Image}} | {{.Status}}'  # 실제 실행 중인 버전
```
