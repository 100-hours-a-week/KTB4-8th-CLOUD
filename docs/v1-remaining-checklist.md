# main 정상 운영 이후 남은 작업

2026-09-30 기준. **사용자 확인: main 기준 서비스는 정상 동작 중이다.** 기존 EC2·DB·ECR·TLS·런타임을 새로 구축하는 작업은 남은 일로 분류하지 않는다. 아래는 현재 작업 브랜치의 추가 기능을 반영하는 데 필요한 설정과 검증이다.

비교한 로컬 main과 origin/main은 af4975a다. 이번 정리에서 원격 fetch, GitHub 설정 조회, AWS/EC2 접속은 하지 않았다. main 정상 운영과 새 자동 CD·모니터링의 적용 완료는 구분한다.

## 1. 이미 있는 것과 추가되는 것

| 항목 | main 기준 | 현재 브랜치에서 추가/변경 |
| --- | --- | --- |
| 앱 4개·DB·TLS·이미지 SHA | 정상 운영의 기존 기반 | 기존 환경 재사용 |
| Deploy production | execute 입력을 사용하는 수동 배포 | main 변경·자동 릴리스 연계, 수동 실행의 execute 입력 제거 |
| 이미지 목록 | production-manifest.yaml | production-manifest.json과 sources.json |
| 앱 새 버전 조회 | Auto release 없음 | 10분 주기 조회 → Manifest PR 생성·병합 → 배포 호출 |
| 배포 실패 처리 | 새 브랜치의 롤백·차단 로직 없음 | 서비스별 변경 감지·순차 교체·이미지 롤백·실패 SHA 차단 |
| Backend health | 8080 포트 연결 확인 | /actuator/health의 UP 응답 확인 |
| Secret 반영 | deploy.sh가 prepare-runtime.py 실행 | 자동 조회 유지로 수정 완료. 실패 시 교체 중단·env/JWT 변경 감지 추가(TD-016), 운영 적용 대기 |
| 외부 감시 | Health check workflow 없음 | PUBLIC_ORIGIN 감시와 Discord 장애·복구 알림 |
| CloudWatch·PG | 이번 비교의 main에는 구성 파일 없음 | CloudWatch, Prometheus·Grafana 설정 추가 |

기존 AWS_DEPLOY_ROLE_ARN, PRODUCTION_EC2_INSTANCE_ID, OIDC/SSM, DB/JWT/AI 필수 Secret을 새로 등록해야 한다고 단정하지 않는다. 기존 main 배포에서 사용하던 값과 권한을 재사용한다.

## 2. 새 자동 CD·외부 알림에 필요한 설정

| 위치 | 이름/항목 | 할 일 |
| --- | --- | --- |
| GitHub Repository Variable | AUTO_DEPLOY_ENABLED | 반영·검증 중 false, 준비 완료 후 true |
| GitHub Repository Variable | PUBLIC_ORIGIN | 운영 HTTPS origin 등록/확인. 경로 없이 입력 |
| GitHub Repository Secret | DISCORD_WEBHOOK_URL | 운영 알림 채널의 Webhook 등록/확인 |
| GitHub Actions 설정 | PR 생성·승인 허용 | Auto release가 Manifest PR을 만들 수 있도록 확인 |
| main 보호 규칙 | 필수 검사·리뷰·merge queue | 현재 즉시 병합 흐름과 호환되는지 확인 |
| production Environment | required reviewers·배포 브랜치 | 무승인 자동 배포 의도와 맞는지 확인 |

GitHub의 실제 등록 여부는 이번에 조회하지 않았다. 이미 등록했다면 추가 입력 없이 검증만 한다. 공통 변수·Webhook을 production Environment에만 두면 Auto release/Health check에서는 읽지 못한다.

- PUBLIC_ORIGIN이 없으면 외부 감시가 실행되지 않는다.
- DISCORD_WEBHOOK_URL이 없으면 알림 대신 경고만 남는다.
- AUTO_DEPLOY_ENABLED=false여도 새 workflow의 수동 Deploy production은 실제 배포한다. 기존 execute 확인 입력은 사라진다.
- 외부 Health check는 자동 배포 스위치와 별개로 동작한다.
- validate.yaml이 존재하는 것만으로 병합 전 통과가 강제되지는 않는다. 보호 규칙을 무조건 풀기보다 검사와 자동 병합 흐름을 맞춘다.

## 3. 기능용 키는 별도로 확인

main 정상 기동만으로 로그인·지도 등 모든 기능용 키의 등록까지 확인되는 것은 아니다. main 배포 코드에는 Google OAuth·VWorld 키 관련 TODO가 남아 있다. **현재도 미등록이라고 확정할 수는 없으므로 해당 기능이 이미 정상이라면 완료 처리한다.**

| Secret | 확인할 키 | 확인할 기능 |
| --- | --- | --- |
| Secret-v1-BE | GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET | 운영 도메인의 Google 로그인·redirect URI |
| Secret-v1-BE | VWORLD_API_KEY | 관련 위치/지도 기능 |
| Secret-v1-AI | NAVER_MAP_CLIENT_ID, NAVER_MAP_CLIENT_SECRET | 관련 지도 기능. main 배포 코드에 존재 검사는 있음 |
| Secret-v1-AI | GOOGLE_API_KEY | 실제 AI 요청 성공, 사용 모델·할당량 |

DB_USERNAME/DB_PASSWORD와 JWT_PUBLIC_KEY/JWT_PRIVATE_KEY는 기존 값을 재사용한다. Compose의 DB_USERNAME은 keepgo_app으로 고정돼 있으므로 이후 DB 사용자 변경 시 Secret만 바꾸지 않는다.

**결정·구현 완료:** main의 배포 시 자동 조회를 유지한다. 조회·검증 실패 시 파일 갱신 전에, 저장 실패 시 컨테이너 교체 전에 중단한다. env·JWT 모두 마지막 정상 적용 컨테이너 ID·지문으로 변경을 감지한다. 최초 도입·기록 유실 시 BE·AI 중 기록이 없는 서비스를 한 번 재생성한다. 실제 EC2 검증은 남아 있다. [TD-016](technical-decisions.md#td-016--배포-시-secret-자동-조회와-실패-처리)

Secret 변경 절차:

1. 자동 배포를 멈추고 실행 중 배포 종료 확인.
2. Secrets Manager 값 변경.
3. Deploy production 수동 실행. 자동 조회 후 변경된 서비스만 반영하며 JWT만 바뀌어도 Backend를 재생성한다.
4. health와 실제 기능을 확인하고 자동 배포 재개. 잘못된 Secret은 이미지 롤백으로 복구되지 않으므로 Secrets Manager 값 수정/복원 후 재배포한다. 상세는 [운영 절차](v1-operations.md) 8절을 따른다.

## 4. 모니터링을 켤 때 새로 필요한 값

| 대상 | 값/파일 | 할 일 |
| --- | --- | --- |
| CloudFormation | InstanceId | 기존 운영 EC2 ID 사용 |
| CloudFormation | InstanceRoleName | 기존 EC2 instance role 이름 입력. 생략 시 필요한 로그·지표 권한을 직접 연결 |
| CloudFormation | AlarmEmail | 알림 수신 이메일 지정 |
| CloudFormation | DBInstanceIdentifier | 기본 keepgo-db-v1과 실제 RDS 식별자 대조 |
| EC2 | /opt/keepgo/runtime/grafana_admin_password | 관리자 비밀번호 한 줄; 472:0, 0400 |
| EC2 | /opt/keepgo/runtime/monitoring.env | DISCORD_WEBHOOK_URL=실제 URL; root:root, 0600 |
| EC2 별도 checkout | /opt/keepgo/observability | 검토 완료한 Cloud 커밋으로 준비 |
| 모니터링 문서 실행 예시 | i-REPLACE, REPLACE_EC2_ROLE, REPLACE_EMAIL, COMMIT | 실행할 때 실제 값으로 치환 |

**GitHub Secret의 Webhook은 Grafana에 자동 전달되지 않는다.** monitoring.env에 별도로 넣어야 한다. 비밀번호와 Webhook 값 자체는 Git/문서에 넣지 않는다.

다음 값은 기본값이 이미 있다. 필요할 때 조정한다.

- 로그 보관 14일.
- EC2 디스크 80%, 메모리 90% 알람.
- RDS 남은 공간 3 GiB, CPU 85% 알람.
- Prometheus 보관 7일 또는 2GB 한도.

구체적인 명령은 [모니터링 운영 문서](v1-monitoring.md)를 따른다.

## 5. 모니터링 적용 작업

- [ ] 기존 동명 로그 그룹·SNS·알람과 소유 스택 확인 후 infrastructure/monitoring.yaml 배포.
- [ ] SNS 구독 확인 이메일에서 승인.
- [ ] EC2 역할에 해당 로그 그룹의 CreateLogStream·PutLogEvents, CWAgent 지표 전송 권한 연결.
- [ ] CloudWatch Agent 설치 및 monitoring/cloudwatch-agent.json 적용. 실제 CWAgent 지표 확인.
- [ ] 임시 컨테이너 로그가 /keepgo/v1/application에 도착하는지 확인.
- [ ] 성공 후 /opt/keepgo/runtime/cloudwatch-logs.enabled 생성 및 수동 배포. 앱 네 개가 로그 설정 변경으로 재생성될 수 있으므로 점검 시간에 적용.
- [ ] observability checkout·Grafana 비밀번호·monitoring.env 준비.
- [ ] 앱 네트워크 keepgo-v1_web, keepgo-v1_service가 있는 상태에서 compose.monitoring.yaml 실행.
- [ ] SSM 터널로 Grafana 3001, Prometheus 9090 접근. 관리 포트는 외부 공개하지 않음.
- [ ] 기본 scrape target 7개 UP, 서비스 probe_success 4개 정상 확인.
- [ ] Grafana Discord 및 CloudWatch SNS 이메일 실제 수신 확인.
- [ ] 앱 재배포 후에도 모니터링과 로그 수집 유지 확인.

모니터링 컨테이너 메모리 상한은 합계 960 MiB다. 기존 앱 상한 2,432 MiB에 OS·Docker·Agent가 더해지므로 실제 여유를 확인한다. 문서상 Prometheus 추가 디스크 여유 기준은 최소 5 GiB다.

앱 자동 CD는 별도 observability checkout을 갱신하지 않는다. 모니터링 파일 변경은 해당 checkout 갱신과 필요한 서비스 재시작으로 별도 반영한다.

## 6. 실제로 빈 설정: 앱 상세 메트릭

monitoring/prometheus/targets/application.json은 현재 []다. 호스트 자원·내부 health 수집과 별개로, 앱의 요청률·오류율·p95·JVM·DB pool 지표는 아직 연결되지 않았다.

- [ ] BE 팀: /actuator/prometheus 계측·접근 설정 확인.
- [ ] AI 팀: /metrics와 요청 수·오류·지연 지표 확인.
- [ ] Nginx 공개 경로에서 metrics가 노출되지 않는지 확인.
- [ ] 준비 후 application.json에 backend:8080, ai-api:8000과 각각의 metrics path 등록.
- [ ] 실제 지표 수집을 확인하고 앱 대시보드·임계치 확정.

앱 구현을 확인하기 전에 대상 주소만 넣어 완료 처리하지 않는다.

## 7. 새 배포 흐름 적용 전 검증

- [ ] 현재 브랜치의 변경/신규 파일 전체를 검토·검증하고 함께 main에 반영. 모니터링 Compose·설정·테스트 누락 없이 포함.
- [ ] YAML Manifest에서 JSON Manifest로의 전환이 deploy.sh·workflow와 함께 반영되는지 확인.
- [ ] Backend 이미지에서 /actuator/health가 인증 없이 UP을 반환하는지 확인. 기존 포트 검사 통과와 다름.
- [ ] 같은 이미지라도 healthcheck 설정 변경 때문에 Backend가 재생성될 수 있음을 반영.
- [x] 배포 시 Secret 자동 조회 복원, 오류 시 중단 및 JWT 적용 상태 추적 구현·결정 기록.
- [ ] EC2에서 Secret 조회 실패 시 교체 없음, JWT만 변경 및 실패 후 재시도 확인.
- [ ] 기존 EC2에서 새 스크립트가 쓰는 flock 및 Compose config --hash 동작 확인.
- [ ] sources.json의 실제 앱 브랜치·workflow·게시 job 이름 확인.
- [ ] Auto release를 dry_run=true로 실행해 후보·무변경 처리 확인.
- [ ] 자동 배포 OFF 상태에서 새 Deploy production을 수동 실행해 교체 대상·health·공개 HTTPS·실제 기능 확인.
- [ ] 외부 Health check 정상 검사와 장애·복구 알림 확인.
- [ ] 합의한 점검 시간/시험 환경에서 이미지 pull 실패, health 실패 롤백, 실패 SHA 차단, 복구 실패 알림 확인.
- [ ] 준비 후 AUTO_DEPLOY_ENABLED=true. 실제 앱 커밋 → Manifest PR → 병합 → 배포까지 확인.
- [ ] 날짜·Cloud SHA·Actions/SSM 실행 링크·결과 기록.

dry_run은 후보 조회 시험이다. 실제 PR 생성·병합 권한, ECR pull, EC2 교체·롤백은 별도 시험한다.

## 8. 결정하거나 후속으로 진행할 항목

| 항목 | 현재 상태 | 다음 작업 |
| --- | --- | --- |
| FE 배포 브랜치 | feat/v1 | 유지 또는 main 전환 결정. 전환 전 main의 frontend/Nginx 두 이미지 게시 확인 |
| 앱 CI 검사 | Cloud는 게시 job 성공을 확인 | BE 등 실제 단위/기능 테스트 수행 범위를 앱 팀과 확인 |
| 서비스별 조회 실패 | 후속 서비스 조회에 영향 가능 | 오류 격리 개선 여부 결정 |
| FE 묶음 실패 처리 | 두 서비스 원자적 교체·전체 차단 보장 안 됨 | 강화 여부 결정 |
| Manifest 병합 후 배포 실패 | 다음 조회만으로 재배포 안 됨 | 수동 재배포 절차 유지 또는 자동 재처리 추가 |
| Grafana 단독 장애 | 별도 외부 감시 없음 | 필요 시 추가 |
| 백업/복원 | main 서비스 동작만으로 검증되지 않음 | RDS 백업·복원 시험, 업로드 파일 백업 담당/주기 확인 |
| DB/설정 복구 | 이미지 롤백으로 복구 안 됨 | migration 호환성과 설정·Secret 복구 절차 확인 |
| V2 ECS/ASG·Worker | 설계 문서 영역 | V1 적용과 별도로 채택 범위·일정 결정 |

## 9. 진행 순서

1. 새 GitHub 변수 2개와 Webhook 등록 여부, PR/Environment 정책 확인.
2. Backend 강화된 healthcheck와 Secret 자동 조회/JWT 변경 감지를 EC2에서 확인.
3. 변경 파일 검증·main 반영 → dry_run → 수동 배포·롤백/알림 시험 → 자동 배포 ON.
4. 모니터링 입력값 준비 → CloudWatch/SNS/Agent → 로그 전송 → Prometheus·Grafana → 수신 시험.
5. BE·AI 상세 메트릭 연결, FE main 전환 및 후속 개선 진행.

## 참고

- [자동 CD 운영 절차](v1-operations.md)
- [모니터링 운영 절차](v1-monitoring.md)
- [배포 검증·롤백](v1-deployment-verification-and-rollback.md)
- [앱 계약](v1-app-contracts.md)
- [구현 현황](v1-implementation-status.md)

기존 구현 현황의 운영 미확인 문구와 알림 문서의 모니터링 추가 전 설명은 사용자의 main 정상 운영 확인 및 새 기능 적용 결과에 맞춰 갱신할 필요가 있다. 이번 체크리스트는 main 정상 운영을 미완료로 다시 분류하지 않는다.
