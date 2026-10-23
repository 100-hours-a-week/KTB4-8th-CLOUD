# KeepGo Cloud — 자동 CD

운영 V1은 단일 EC2의 Docker Compose, 개발 V2는 ECS를 사용한다. 앱 CI가 이미지를 게시하면 ECR push → EventBridge → Cloud 중앙 CD가 검증된 버전의 Manifest PR을 병합하고 환경별 배포를 실행한다. 10분 주기 조회는 보조 경로로 유지한다.

이 브랜치는 최신 실행 코드와 문서를 함께 보관하는 통합 작업 브랜치다. `main`에는 배포·운영 코드, 설정, 검증 파일과 배포 Manifest를 반영하며 상세 문서·검토 기록은 이 브랜치에서 관리한다. [통합 및 반영 상태](docs/branch-integration-status.md)

**처음 읽을 문서: [자동 CD 전체 설명 — 어떻게 동작하고 왜 이렇게 구성했는가](docs/v1-design.md)**

| 알고 싶은 내용 | 문서 |
| --- | --- |
| V2 운영 전환·V1 개발 전환의 순서, 출시 필수 작업, CI/CD·모니터링 변경, 미정 사항 | [V2 운영 전환 계획](docs/v2-prod-cutover-plan.md) |
| 개발 BE·AI 모니터링 설치·자동 대상 발견·로그 확인·복구 | [개발 모니터링 실행 절차](docs/dev-monitoring-runbook.md) |
| 개발 모니터링 연결의 조사·비용·적용 기록 | [개발 모니터링 연결 기록](docs/dev-monitoring-connection.md) |
| 모니터링 전체 흐름·구축 순서, 코드 구현과 운영 적용 구분, V1/V2 차이 | [모니터링 전체 안내](docs/monitoring-overview.md) |
| 옵저빌리티 도입 우선순위, 도구별 트레이드오프, 비용·SLO·단계별 실행안 | [옵저빌리티 도입 검토](docs/observability-adoption-review.md) |
| 관측 도구 선택·로그 조회 비용·대안 비교 | [모니터링 선택 검토](docs/observability-selection-review.md) |
| V2 중앙 CD·프론트 자동배포·ECR 즉시 트리거의 적용 기록 | [V2 개발 CD 작업 정리](docs/v2-dev-cd-work-summary.md) |
| 전체 흐름, 구성 이유, 파일 역할, 실패 시 동작과 한계 | [전체 설명](docs/v1-design.md) |
| CloudWatch 로그·알람, Prometheus·Grafana 구성과 적용 순서 | [모니터링 운영 구성](docs/v1-monitoring.md) |
| BE·AI·FE 전달용 상세 메트릭·bucket·초기 임계치 | [메트릭 계약 v1](docs/monitoring-metrics-contract.md) |
| 앱 대시보드 적용·검증·장애별 대응 | [앱 알림 운영 절차](docs/monitoring-alert-runbook.md) |
| 장애 알림 구축, 감지 기준, Discord 연결·수신 시험 | [장애 알림 시스템](docs/v1-alerting.md) |
| Sentry: AI 에러 수집(SENTRY_DSN), 외부 감시(Uptime) 이전, 인증서, 계정 관리 | [Sentry 사용 정리](docs/v1-sentry.md) |
| 배포 성공 판정, 자동·수동 롤백, 차단·재배포·인수 시험 | [배포 검증 및 롤백](docs/v1-deployment-verification-and-rollback.md) |
| 최초 연결, dry_run, 호스트 조회, Secret 변경 | [운영 절차](docs/v1-operations.md) |
| 대안 비교, 결정 변경 이력, 재검토 조건 | [기술 결정](docs/technical-decisions.md) |
| 앱 팀이 지켜야 할 CI·이미지·health 계약 | [앱 저장소 계약](docs/v1-app-contracts.md) |
| 앱 코드와 Secret 값이 어긋날 때의 위험, 대응 방법과 트레이드오프, 새 환경변수 추가 절차 | [설정·Secret 어긋남](docs/v1-config-secret-gap.md) |
| 검증한 범위와 아직 확인하지 않은 항목 | [구현 및 검증 현황](docs/v1-implementation-status.md) |

운영 목표 SHA는 [production-manifest.json](deployment/production-manifest.json), 조회 대상은 [sources.json](deployment/sources.json)이 기준이다. Git의 목표와 EC2의 실제 버전은 다를 수 있다. 운영 적용 완료 여부는 위 검증 현황에서 확인한다.

배포 없이 후보를 확인하려면 Actions의 Auto release에서 `dry_run`을 선택한다. 자세한 실행 조건과 로컬 검사는 [운영 절차](docs/v1-operations.md#2-배포-전-후보-조회)에 있다.

V2의 실제 적용 상태와 트러블슈팅은 [V2 개발 CD 작업 정리](docs/v2-dev-cd-work-summary.md)를 기준으로 읽는다. 이전 확장 제안은 [V2 설계](docs/V2%20설계.md)와 [V2 CI/CD 검토](docs/v2-cicd-design-review.md)에 둔다. 이전 V1 설계안·인계 기록은 [보관 문서](docs/archive/README.md)에서 찾는다.
