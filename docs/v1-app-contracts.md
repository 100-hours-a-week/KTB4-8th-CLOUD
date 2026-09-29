# v1 App 팀 계약

> **2026-09-28 현재 상태:** Worker 이미지는 미게시, 앱 검사 계약은 미확정, S3는 미사용이다. 검사 주석 처리와 준비 확인에 따른 실행 보류가 적용되어 있다. 기존 EC2는 팀원이 운영 중이다. [최신 인계·추가 정보](v1-handoff-2026-09-28.md)와 [파일별 사용법·푸시 지침](v1-files-and-push-guide.md)을 먼저 읽는다. 아래 기존 S3 설치·검사 활성화·최초 스택 교체 절차는 현재 그대로 실행하지 않는다.

Cloud 저장소에는 App 소스가 없다. 아래 명령/엔드포인트는 배포 코드가 실제 호출하는 필수 계약이다. App에 구현됐다고 가정해 완료 처리하지 않는다. 미구현 이미지는 health/smoke에서 실패한다.

## 1. 이미지와 CI

| 서비스 | ECR 기본 이름 | 실행 |
| --- | --- | --- |
| web | keepgo-web | Next.js standalone, Node 22, 0.0.0.0:3000 |
| nginx | keepgo-nginx | TLS 80/443, web:3000 및 backend:8080 proxy |
| backend | keepgo-backend | Spring prod, 8080 |
| worker | keepgo-worker | 독립 ENTRYPOINT, Spring worker profile |
| ai-api | keepgo-ai | uvicorn api.main:app, 8000 |

ECR 이름은 App CI 변수와 source-policy를 맞춘다. 제공된 Frontend CI의 ECR_REPOSITORY/ECR_NGINX_REPOSITORY 실제 값은 알려지지 않았다. 기본과 다르면 IAM 범위도 수정한다. 모든 이미지에 linux/amd64와 소문자 40자리 SHA tag를 사용한다. tag 불변성을 켜고 현재/이전 성공 digest를 lifecycle 정책으로 지우지 않는다.

Frontend CI는 소스 미준비 시 quality/publish를 skip할 수 있다. Cloud는 세 필수 job의 개별 success를 확인하므로 이런 run을 거부한다. workflow_dispatch CI 성공도 일반 자동 후보로 받지 않는다. main push가 정상 경로다. App 코드 PR에는 별도 CI 검사를 갖춘다.

알림 예시: `examples/app-notify-cloud.yaml`. 실제 CI 경로와 job 표시 이름을 source-policy에 넣는다. Backend/Worker가 같은 CI를 사용해도 각 이미지의 테스트·게시 성공을 각각 확인하고 dispatch한다. Worker job skip/미게시인 Backend 변경으로 Worker 후보를 만들지 않는다.

## 2. healthcheck

각 이미지에 실행 가능한 `/app/bin/healthcheck`를 넣는다. 5초 이내 성공 시 exit 0, 실패 시 nonzero. 비밀을 출력하지 않고 PID 생존만으로 readiness를 대신하지 않는다.

| 서비스 | 검사 |
| --- | --- |
| nginx | nginx -t 및 로컬 /health/live 200 |
| web | localhost:3000의 /health/ready 또는 전용 Next route |
| backend | readiness, RDS 연결, 필요한 스키마 접근. 공개 /api/health/ready는 민감 정보 없이 200/503 |
| worker | DB 연결 및 실제 polling 루프 heartbeat가 60초 이내 |
| ai-api | localhost:8000 readiness 및 필수 Secret/config 초기화 |

Node/Python 표준 라이브러리로 HTTP probe를 구현할 수 있다. Spring/Nginx에서 curl을 쓰면 이미지에 curl을 포함한다. Cloud Compose는 curl을 가정하지 않고 App 검사 명령을 호출한다. 유료 LLM은 상시 health마다 호출하지 않는다.

Nginx는 backend 교체 뒤 master reload가 가능해야 한다. /api prefix 보존 여부는 실제 Backend 경로에 맞춘다. stdout access log에 숫자 status를 기록한다. TLS 파일 이름/갱신 절차는 Nginx와 /opt/keepgo/tls mount를 맞춘다.

## 3. DB job smoke 및 지표

Backend의 `/app/bin/smokecheck`는 120초 이내 아래를 검증한 후 stdout에 `{"ok":true}`만 출력한다. 실패는 nonzero 또는 ok:false다.

1. 테스트 전용 리소스와 유일한 idempotency key로 실제 job 생성 경로 호출.
2. MySQL 저장 확인.
3. 현재 Worker의 claim 및 내부 FastAPI 호출 확인.
4. 완료 상태와 최소 결과 계약을 polling으로 확인.
5. 테스트가 소유한 데이터만 정리.

인증 오류·AI timeout·Worker 정지·job stuck을 성공 처리하지 않는다. 재실행에도 중복 업무가 발생하지 않아야 한다. 결제·사용자 알림 같은 외부 부수효과가 없는 테스트 경로를 사용한다. 유료 AI 실제 호출은 이 제한된 smoke에서 확인한다. stderr 로그에 request/job ID만 남기고 비밀과 개인정보를 제외한다.

`/app/bin/queue-metrics`는 15초 이내 인덱스를 이용해 아래 JSON을 출력한다. DB 오류는 nonzero다.

```json
{"oldest_pending_seconds": 0, "failed_last_5m": 0}
```

oldest는 실행 가능한 PENDING/RETRY 및 lease 만료 RUNNING의 최초 대기 시각 기준 최대 지연이다. 미래 예약 job은 제외한다. failed는 최근 5분에 최종 FAILED가 된 job 수다.

## 4. MySQL job 큐

기존 schema를 확인하지 않았으므로 자동 DDL을 적용하지 않는다. 다음 계약을 Backend migration에 반영한다.

- 권장 기준: RDS MySQL 8.0 이상, InnoDB. 실제 엔진 버전 확인 필요.
- 상태: PENDING → RUNNING → SUCCEEDED; 재시도 RETRY; 한도 초과 FAILED.
- 필드: id, type, payload_version, payload, idempotency_key(unique), status, available_at, attempts, max_attempts, lease_owner, lease_token, lease_expires_at, heartbeat_at, created_at, updated_at, last_error_code.
- 인덱스: (status, available_at, id), (status, lease_expires_at, id), idempotency unique.
- claim: 짧은 transaction에서 SELECT FOR UPDATE SKIP LOCKED 후 owner/token/lease/attempts 갱신, 즉시 commit. AI 호출 동안 row lock을 유지하지 않음.
- concurrency 1, batch 10은 상한. 즉시 실행하지 못할 job을 대량 claim하지 않음.
- lease 120초, heartbeat 30초. 장기 작업은 lease 갱신이 성공할 때만 계속 처리.
- 완료/재시도: WHERE id=? AND lease_token=? AND status='RUNNING', affected rows=1로 fencing. 이전 Worker의 늦은 결과 거부.
- 만료 lease는 Worker가 RETRY/FAILED로 회수. 프로세스가 꺼져도 job은 DB에 보존.
- 기본 최대 3회, 지수 backoff+jitter. 최종 FAILED 수동 재처리는 원인 해결 후 수행.
- at least once 처리. 외부 호출 중복 가능. unique/upsert와 idempotency key로 사용자 효과 중복 제어. 정확히 한 번 실행을 보장한다고 표현하지 않음.

SIGTERM을 받으면 새 claim을 중단하고 진행 작업을 최대 60초 기다린다. 끝내지 못하면 lease 반납 또는 만료 후 회수한다. 종료 신호만으로 성공 처리하지 않는다. Compose init 및 stop grace는 이 App 동작을 보조한다.

독립 배포를 위해 새 Backend의 payload를 이전 Worker도 처리할 수 있어야 한다. payload_version 변경은 소비자의 구/신 parser 지원을 먼저 배포하고 생산자 변경을 나중에 배포한다. 현재 Worker+후보 Backend, 현재 Backend+후보 Worker 조합을 App CI에서 확인한다.

[MySQL SKIP LOCKED의 queue 용도 설명](https://dev.mysql.com/worklog/task/?id=8919).

## 5. DB migration

Cloud는 migration 명령을 추측해 실행하지 않는다. 이미지 rollout 전 Backend 팀의 검토된 migration을 적용하고 schema 호환성을 readiness에서 확인한다.

1. 추가 테이블/nullable 컬럼/인덱스 등 구버전 호환 확장 먼저 적용.
2. 구버전 Backend/Worker가 계속 동작하는지 확인.
3. 백필 및 새 읽기/쓰기 전환.
4. 컬럼 삭제/rename/type 축소/필수값 강제는 롤백 보존기간 후 별도 점검.

Worker가 migration을 동시에 실행하지 않게 한다. Backend startup migration을 쓰면 DB migration lock과 이전 Worker 호환성을 검증한다. 이미지 롤백 시 SQL을 자동 downgrade하지 않는다. RDS snapshot/PITR은 데이터 재해복구 수단이다.

## 6. 로그 계약

timestamp, level, service, event, request_id, job_id, duration_ms, error_code를 권장한다. Nginx는 숫자 status, AI timeout은 event=ai_timeout, Worker 최종 실패는 event=job_failed를 기록해야 제공한 metric filter가 작동한다. Authorization/Cookie/Secret/사용자 원문 payload를 기록하지 않는다.
