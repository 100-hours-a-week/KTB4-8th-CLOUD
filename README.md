# KeepGo Cloud — 자동 CD

단일 EC2의 Docker Compose로 Nginx, Frontend, Backend, AI API를 운영한다. 앱 CI가 이미지를 게시하면 Cloud가 새 버전을 조회해 Manifest PR을 병합하고 SSM으로 배포한다.

**처음 읽을 문서: [자동 CD 전체 설명 — 어떻게 동작하고 왜 이렇게 구성했는가](docs/v1-design.md)**

| 알고 싶은 내용 | 문서 |
| --- | --- |
| 전체 흐름, 구성 이유, 파일 역할, 실패 시 동작과 한계 | [전체 설명](docs/v1-design.md) |
| 장애 알림 구축, 감지 기준, Discord 연결·수신 시험 | [장애 알림 시스템](docs/v1-alerting.md) |
| 배포 성공 판정, 자동·수동 롤백, 차단·재배포·인수 시험 | [배포 검증 및 롤백](docs/v1-deployment-verification-and-rollback.md) |
| 최초 연결, dry_run, 호스트 조회, Secret 변경 | [운영 절차](docs/v1-operations.md) |
| 대안 비교, 결정 변경 이력, 재검토 조건 | [기술 결정](docs/technical-decisions.md) |
| 앱 팀이 지켜야 할 CI·이미지·health 계약 | [앱 저장소 계약](docs/v1-app-contracts.md) |
| 검증한 범위와 아직 확인하지 않은 항목 | [구현 및 검증 현황](docs/v1-implementation-status.md) |

운영 목표 SHA는 [production-manifest.json](deployment/production-manifest.json), 조회 대상은 [sources.json](deployment/sources.json)이 기준이다. Git의 목표와 EC2의 실제 버전은 다를 수 있다. 운영 적용 완료 여부는 위 검증 현황에서 확인한다.

배포 없이 후보를 확인하려면 Actions의 Auto release에서 `dry_run`을 선택한다. 자세한 실행 조건과 로컬 검사는 [운영 절차](docs/v1-operations.md#2-배포-전-후보-조회)에 있다.

V2 확장 제안은 [V2 설계](docs/V2%20설계.md)와 [V2 CI/CD 검토](docs/v2-cicd-design-review.md)에 둔다. 이전 V1 설계안·인계 기록은 [보관 문서](docs/archive/README.md)에서 찾는다.
