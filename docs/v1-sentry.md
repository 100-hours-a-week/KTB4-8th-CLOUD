# Sentry 사용 정리

KeepGo V1에서 Sentry를 쓰는 곳은 두 가지다. **AI 서버의 에러 수집**과, 앞으로 Actions Health check를 대신할 **외부 감시(Uptime Monitoring)**다. 이 문서는 둘의 동작·설정·한계·남은 작업을 한곳에 모은다. 결정의 근거는 [TD-019](technical-decisions.md#td-019--ai-secret-키-전달-범위와-sentry_dsn)(DSN 전달)와 [TD-023](technical-decisions.md#td-023--외부-감시-유지-sentry-uptime으로-이전)(외부 감시)에 있다.

## 한 줄 요약

| 용도 | 상태 | 핵심 |
| --- | --- | --- |
| AI 에러 수집 | 운영 중 | `SENTRY_DSN`이 형식에 맞지 않으면 **AI가 기동하지 못한다.** 형식 검사·기동 견딤은 아직 TODO |
| 외부 감시 (Uptime) | 결정, 설정 전 | 무료 1개로 `/healthz`만 본다. **혼자서는 지금 Health check를 다 대신하지 못하고 Grafana와 합쳐야 한다** |
| 계정 | 무료 Developer, 팀 공유 | 사용자 1명, Uptime 감시 1개 포함 |

## 1. 현재 사용 현황 (2026-10-01 확인)

| 서비스 | Sentry | 근거 |
| --- | --- | --- |
| AI (FastAPI) | 사용 | AI `main`의 의존성 `sentry-sdk[fastapi]`, `app/main.py`에서 초기화 |
| Backend (Spring Boot) | 없음 | BE `main`의 `build.gradle`에 Sentry 의존성 없음 |
| Frontend (Next.js) | 없음 | FE `feat/v1`의 `package.json`에 Sentry 의존성 없음 |
| 외부 감시 | 미설정 | TD-023 적용 대기 |

## 2. AI 에러 수집

### 값이 컨테이너까지 가는 경로

```text
Secrets Manager (Secret-v1-AI의 SENTRY_DSN)
  → 배포 때 prepare-runtime.py가 조회 (AI_OPTIONAL 목록에 있는 키만 옮긴다)
  → /opt/keepgo/runtime/ai.env
  → ai-api 컨테이너의 환경변수 (compose의 env_file)
  → 앱 시작 시 sentry_sdk.init(dsn=..., send_default_pii=False)
```

- Secret 값을 바꿔도 **다음 배포 때만** 컨테이너에 들어간다. 바꾼 사람이 Deploy production을 수동 실행하고 결과를 확인한다([설정·Secret 어긋남](v1-config-secret-gap.md)).
- `send_default_pii=False`라 IP·헤더·쿠키는 보내지 않는다.

### 값에 따른 동작

| `SENTRY_DSN` | 배포 | AI 앱 |
| --- | --- | --- |
| 없음 | 경고만 남기고 계속 (선택 키) | Sentry 없이 정상 기동. 에러 수집이 조용히 꺼짐 |
| **형식이 틀림** | 그대로 전달됨 (형식 검사 없음) | **시작하자마자 `BadDsn`으로 종료 → health 실패 → 이전 버전으로 롤백·차단.** 알림 없음 |
| 올바름 | 전달 | 에러를 Sentry로 보냄 |

형식이 틀린 경우는 2026-09-30에 실제로 겪었다. 새 AI 버전이 약 1시간 반 동안 반영되지 않았고 아무도 몰랐다([트러블슈팅](troubleshooting/2026-09-30-ai-sentry-dsn-rollback.md)).

**올바른 형식:** `https://<공개키>@<호스트>/<프로젝트번호>`. EC2에서 값을 출력하지 않고 형식만 확인하는 방법:

```bash
sudo grep -cE '^SENTRY_DSN=https://[^@/]+@[^/]+/[0-9]+$' /opt/keepgo/runtime/ai.env   # 1이면 올바른 형식
```

### Sentry와 Prometheus의 역할

| 도구 | 맡는 것 |
| --- | --- |
| Sentry | 오류 **상세**: 예외 종류, 스택, 발생 위치 |
| Prometheus | 요청량·오류율·지연 같은 **수치** ([지표 계약](monitoring-metrics-contract.md)) |

### 개선 과제

| 과제 | 막는 문제 | 담당 | 상태 |
| --- | --- | --- | --- |
| **형식 검사:** prepare-runtime.py가 DSN 형식을 검사하고, 틀리면 전달하지 않고 경고만 남김 | 형식 오류로 인한 기동 실패 | Cloud | TODO ([체크리스트](v1-remaining-checklist.md) 9절) |
| **롤백·차단 알림:** `rolled_back`과 차단으로 건너뛴 경우를 Discord로 알림 | 조용히 안 나간 배포 | Cloud | TODO |
| **앱이 초기화 실패를 견딤:** `sentry_sdk.init` 실패 시 경고 로그만 남기고 계속 기동 | 부가 기능 때문에 AI 전체가 죽는 것 | AI 파트 | 요청 필요. 2026-10-01 AI `main`은 아직 예외 처리 없이 초기화 |
| **환경·버전 표시:** compose에 `SENTRY_ENVIRONMENT=production`, `SENTRY_RELEASE=${AI_IMAGE_TAG}` 추가 | Sentry에서 어느 배포 버전의 오류인지 구분이 안 됨 | Cloud | 제안. AI 코드는 바꾸지 않아도 된다(SDK가 두 환경변수를 읽음). 적용 시 ai-api가 한 번 재생성됨 |
| **Backend 도입:** BE에 Sentry 추가 | 사이트는 열리는데 특정 API에서 계속 오류가 나는 기능 장애 | BE 파트 | 검토. 외부 감시·health가 못 보는 영역 |

## 3. 외부 감시 (Uptime Monitoring)

### 왜 Sentry인가

배포 시 health 확인과 내부 모니터링(CloudWatch·Grafana)만으로는 DNS·인증서·보안 그룹·Nginx 공개 설정 장애와 EC2 전체 정지를 밖에서 보지 못한다. 그래서 외부 감시는 유지한다. 지금은 GitHub Actions가 이 일을 하는데, schedule 장애 때문에 EventBridge와 개인 PAT로 돌고 하루 288건의 기록이 쌓인다. Route 53과 비교한 끝에, 팀이 이미 쓰는 Sentry로 옮기기로 했다. 비교와 판단은 [TD-023](technical-decisions.md#td-023--외부-감시-유지-sentry-uptime으로-이전)에 있다.

### Sentry Uptime 동작 (2026-10-01 공식 문서·요금표 확인)

| 항목 | 내용 |
| --- | --- |
| 확인 주기 | 1분·5분·10분·20분·30분·1시간 |
| 정상 기준 | 2xx만 정상. 3xx는 따라가서 최종 응답이 2xx여야 함. 10초 안에 응답이 없거나 DNS 오류면 실패 |
| 장애 판정 | 기본 3번 연속 실패 시 이슈 생성 (조정 가능) |
| 복구 | 기본 1번 성공하면 이슈 자동 해결 |
| 요청 | 메서드·헤더 지정 가능. 응답 상태 코드·본문 조건(Verification)은 얼리 어답터 전용 |
| 확인 위치 | 여러 지역에서 돌아가며 확인 |
| 알림 | 알림 규칙에서 이메일·Slack·Discord 등 연동으로 보냄 |
| 비용 | 모든 요금제에 1개 포함, 추가는 1개당 월 $1 (Team·Business 기준) |

출처: [Uptime Monitoring 문서](https://docs.sentry.io/product/monitors-and-alerts/monitors/uptime-monitoring/), [요금표](https://sentry.io/pricing/), [Discord 연동](https://docs.sentry.io/organization/integrations/notification-incidents/discord/)

### 지금 Health check와 비교

| 지금 Health check가 하는 일 | Sentry Uptime | 대신하는 것 |
| --- | --- | --- |
| 밖에서 접속 (DNS·보안 그룹·Nginx) | ✅ | Sentry |
| Nginx 응답 `/healthz` | ✅ | Sentry |
| Frontend 응답 `/` | △ 감시가 하나 더 필요. 무료 요금제에서 추가할 수 있는지 확인 안 됨 | Grafana 내부 프로브 |
| Backend 응답 `/api` | ❌ 401을 돌려줘서 2xx 기준에 걸림 | Grafana 내부 프로브 |
| 인증서 만료 | ❓ 문서에 없음 | 4절 |
| 장애 알림 (Discord) | △ 연동은 지원. 무료 요금제에서 되는지 확인 안 됨 | — |
| 복구 알림 | ❓ 자동 해결은 되지만 알림이 가는지 문서에 없음 | — |
| 배포 중 오탐 방지 | ✅ 1분 주기 × 3번 연속이면 약 3분이라 Backend 재기동(약 90초)을 견딤 | Sentry |
| 원인 구간 표시 (`nginx=… backend=…`) | ❌ 정상·장애만 | Grafana 서비스별 알림 |

**Sentry 단독으로는 "사이트 입구가 열리나"만 확실하다.** Frontend·Backend 장애는 Grafana 내부 알림(`rules.json`의 `KeepGo internal service unhealthy`, 3분 지속)이 운영에서 동작해야 잡힌다.

### 설정값 (등록 후 채운다)

설정이 코드에 남지 않으므로 여기 기록하고, 바꿀 때 팀에 공유한다.

| 항목 | 값 |
| --- | --- |
| 감시 URL | `https://<운영 도메인>/healthz` |
| 확인 주기 | 1분 |
| 실패 기준 / 복구 기준 | 3번 연속 실패 / 1번 성공 (기본값) |
| 알림 대상 | 기존 Discord 채널 |
| 등록한 사람·날짜 | (기록) |
| 계정 관리자 | (기록) |

### 적용 순서

- [ ] **1. 등록:** Sentry Uptime에 `/healthz`를 1분 주기로 등록하고 Discord 알림을 연결한다. Actions Health check와 겹쳐도 문제없어 바로 해도 된다.
- [ ] **2. 확인 안 된 항목 시험:**
  - [ ] 무료 요금제에서 Discord 알림이 오는가
  - [ ] 복구 알림도 오는가 (Nginx를 잠깐 멈췄다 켜는 시험은 팀과 시간을 합의하고 한다)
  - [ ] 인증서 검증: `https://expired.badssl.com/`을 잠깐 등록해 실패로 잡히는지 보고 지운다
  - [ ] 무료 요금제에서 감시를 추가할 수 있는가 (Frontend `/`용)
- [ ] **3. 모니터링 스택 설치:** Grafana 서비스별 알림을 시험한다([모니터링 운영 구성](v1-monitoring.md)).
- [ ] **4. Health check 삭제:** 아래 "삭제할 때 고칠 것"을 코드 PR 하나로 반영한다.

**3단계 전에 4단계를 하면 안 된다.** Backend가 죽어도 Nginx는 응답하므로 아무 알림이 오지 않는다.

### Health check를 삭제할 때 고칠 것

| 대상 | 수정 |
| --- | --- |
| `.github/workflows/health-check.yaml` | 삭제 |
| `infrastructure/github-dispatch.yaml` | Health check용 호출 대상·5분 규칙·IAM 정책 항목·Output 삭제, 설명 주석 수정 |
| 〃 `DispatchFailureAlarm` | **토큰 만료 알람이 지금 Health check 규칙 기준(`RuleName: HealthCheckSchedule`)으로 걸려 있다.** Auto release 규칙 기준으로 옮긴다. 그냥 지우면 토큰이 만료돼도 알람이 오지 않는다 |
| 스택 재배포 | `aws cloudformation deploy`는 지정하지 않은 파라미터에 기존 값을 쓴다. 토큰을 다시 넣지 않아도 되는지 change set으로 먼저 확인한다 |
| GitHub Variable `PUBLIC_ORIGIN` | Health check에서만 쓰므로 삭제 |
| 문서 | [장애 알림](v1-alerting.md) 3·6·7·8절, [운영 절차](v1-operations.md), [설계](v1-design.md) 파일 목록, TD-018의 "만료는 외부 Health check로 드러난다" |

바꾸지 않아도 되는 것: deploy.sh의 배포 시 health 확인, compose의 컨테이너 healthcheck, blackbox 내부 프로브, Grafana 알림 규칙.

### 선택: 무료 감시 1개로 더 많이 보기

| 감시 URL | 범위 | 필요한 작업 |
| --- | --- | --- |
| `/healthz` (현재 계획) | DNS·TLS·보안 그룹·Nginx | 없음 |
| Nginx가 Backend health로 넘기는 전용 경로 (예: `/healthz/backend` → `backend:8080/actuator/health`) | 위 범위 + Backend + DB | Nginx 설정은 FE 레포의 web 이미지에 있어 **FE 파트 작업**이다. `/actuator`를 외부에 막아 둔 결정(TD-014)을 그 경로 하나만큼 바꾸는 일이라 정확히 한 경로만 여는지 확인한다. 응답은 `show-details: never`라 `{"status":"UP"}`뿐이다 |

## 4. 인증서

### ACM을 쓰지 않는 이유

V1은 EC2 안의 Nginx가 TLS를 처리한다. compose가 EC2의 `/opt/keepgo/tls`(인증서 파일)와 `/opt/keepgo/acme`(certbot webroot)를 Nginx 컨테이너에 bind mount한다. 일반 ACM 인증서는 ALB·CloudFront 같은 AWS 서비스에만 붙일 수 있고 파일로 꺼내 Nginx에 넣을 수 없다. V1에는 ALB·CloudFront가 없다.

| ACM으로 가는 방법 | 판단 |
| --- | --- |
| ALB를 앞에 둠 | 갱신은 완전 자동이지만 고정비가 붙는다. V1에는 과하다 |
| CloudFront를 앞에 둠 | 무료 한도는 넉넉하지만 캐시·업로드·실제 IP·EC2 직접 접근 차단을 새로 설계해야 한다 |
| 내보내기 가능한 ACM 인증서 | 도메인당 발급·갱신마다 $7. 갱신된 인증서를 EC2에 다시 넣고 Nginx를 reload하는 일은 그대로 남는다([문서](https://docs.aws.amazon.com/acm/latest/userguide/acm-exportable-certificates.html)) |
| V2 (ECS + ALB) | 설계상 ALB + ACM으로 넘어가며 이 문제가 사라진다 |

### 지금 확인할 것

**certbot 자동 갱신과 갱신 후 Nginx reload가 걸려 있는지 레포 어디에도 기록이 없다.** 갱신이 안 되거나, 갱신돼도 Nginx가 옛 인증서를 계속 쓰면 만료 순간 전면 장애가 된다. Let's Encrypt라면 2025년 6월부터 만료 안내 메일도 보내지 않는다. EC2에서 한 번 확인하고 결과를 이 절에 기록한다.

```bash
# SSM 접속 후 sudo -i
systemctl list-timers | grep -i certbot; crontab -l; ls /etc/cron.d    # 자동 갱신 예약
ls -l /opt/keepgo/tls/                                                   # 실제 인증서 링크인지, 복사본인지
ls /etc/letsencrypt/renewal-hooks/deploy/ 2>/dev/null                    # 갱신 후 nginx reload 훅
openssl x509 -issuer -enddate -noout -in /opt/keepgo/tls/fullchain.pem   # 발급자와 만료일
certbot renew --dry-run                                                  # 갱신이 실제로 되는지 (실제 발급 안 함)
```

### 인증서 감시 선택지

| 방법 | 알게 되는 시점 | 작업 |
| --- | --- | --- |
| EC2 자동 갱신 확인 (위) | 사고 전 (예방) | 명령 몇 줄 |
| Sentry가 인증서를 검증하는지 시험 | **만료 후** (장애 약 3분 뒤) | 3절 2단계 |
| blackbox로 만료 14일 전 알림 (`probe_ssl_earliest_cert_expiry`) | 사고 전 | 코드 PR: blackbox HTTPS 모듈, Prometheus 대상(Nginx 443에 실제 도메인 이름으로 접속), Grafana 규칙, 테스트 |

자동 갱신과 reload가 확인되면 Sentry 시험만으로 충분하다. 없거나 애매하면 blackbox 알림을 넣는다.

## 5. 계정 관리

- 요금제: **무료 Developer.** 사용자 1명이라 팀이 로그인 정보를 공유한다. Uptime 감시는 1개 포함이다.
- 비밀번호·2단계 인증을 관리할 사람을 정하고 위 설정값 표에 적는다. 담당이 바뀌면 계정과 감시를 함께 넘긴다.
- 계정 접근을 잃으면 AI 에러 수집과 외부 감시를 함께 잃는다.
- 알림 규칙·감시 설정을 바꾸면 팀 채널에 공유하고 이 문서를 고친다.
- DSN은 Secrets Manager에서만 관리한다. 코드·채팅·문서에 붙여 넣지 않는다.

## 관련 문서

- [TD-019 — AI Secret 키 전달 범위와 SENTRY_DSN](technical-decisions.md#td-019--ai-secret-키-전달-범위와-sentry_dsn)
- [TD-023 — 외부 감시: 유지, Sentry Uptime으로 이전](technical-decisions.md#td-023--외부-감시-유지-sentry-uptime으로-이전)
- [트러블슈팅: SENTRY_DSN 형식 오류로 AI 배포 자동 롤백](troubleshooting/2026-09-30-ai-sentry-dsn-rollback.md)
- [설정·Secret 어긋남의 위험과 대응](v1-config-secret-gap.md)
- [장애 알림 시스템](v1-alerting.md), [모니터링 운영 구성](v1-monitoring.md)
- [남은 작업 체크리스트](v1-remaining-checklist.md) 9절
