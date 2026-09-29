# Backend 중앙 CD 파일별 역할

현재 설계와 선택 이유는 [설계](v1-design.md) 및 [기술 결정 기록](technical-decisions.md), 연결 순서는 [운영 절차](v1-operations.md)를 따른다.

| 파일 | 역할 |
| --- | --- |
| compose.yaml | main의 네 서비스 실행 설정. web=Nginx, frontend=Next.js |
| deployment/production-manifest.json | 단일 목표 버전. SHA·digest·Backend CI 출처 |
| deployment/source-policy.json | 허용 Backend repo·workflow·필수 job |
| deployment/runtime.example.json | EC2 runtime 설정 예시. 실제 값은 Git에 넣지 않음 |
| scripts/pin-manifest.py | 최초 기존 SHA의 digest·성공 CI를 조회해 JSON 갱신 |
| scripts/validate-manifest.py | Manifest 형식·Compose 구조 검증 |
| scripts/candidate.py | Backend 후보 PR 생성·polling·정책 검사·auto-merge 설정 |
| scripts/release.py | JSON 검증·ECR digest·CI 출처·Backend 변경 범위 |
| scripts/ssm-deploy.py | 고정 Git 커밋을 SSM으로 전달·종료 상태 관찰. S3 없음 |
| scripts/deploy.sh | Python 배포 엔진 진입점 |
| scripts/deploy.py | 최초 adopt·Backend 교체·검증·롤백·동결·복구 |
| scripts/prepare-runtime.py | main에서 가져온 Secrets Manager → env/JWT 준비. 명시적 초기 준비용 |
| scripts/monitor.py, external-probe.py | 선택적 호스트·외부 감시. Worker·큐 검사 없음 |
| infrastructure/ | S3 없는 IAM 초안과 호스트·외부/RDS 알람 정의. 적용 전 기존 리소스 확인 |
| tests/ | 상태 전이·출처·범위·digest·SSM 검증 |

candidate는 CD_SETUP_READY와 CD_ENABLED 모두 true일 때 실행한다. release-policy는 CD_SETUP_READY, 자동 배포는 두 스위치, 수동 adopt/recover 등은 CD_SETUP_READY를 요구한다. MONITOR_ENABLED는 외부 감시용 별도 스위치다.

예시·코드·문서는 커밋한다. 실제 `.env`, runtime.json, 인증 키, AWS/GitHub credentials, current/previous/inflight/blocked/frozen/result 및 실제 배포 artifacts는 커밋하지 않는다. production-manifest.json의 초기 null은 구조 검사를 위한 미확인 상태다. 실제 배포 전에 pin 결과를 검토해 반영해야 한다.
