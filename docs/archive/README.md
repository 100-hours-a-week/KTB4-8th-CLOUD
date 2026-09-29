# 이전 V1 기록

아래 문서는 작성 당시의 설계안·환경 확인·작업 기록이다. 현재 운영 명령은 [운영 절차](../v1-operations.md), 전체 구조는 [자동 CD 전체 설명](../v1-design.md)이 기준이다. 아래 파일의 “현재”, “다음 작업”, 미완료 목록은 작성 시점의 표현이다.

| 기록 | 보관 이유 |
| --- | --- |
| [저장소별 독립 CD 대안](ci-cd-repository-responsibilities.md) | 앱 저장소가 직접 SSM 배포를 호출하는 미채택 대안 |
| [초기 중앙 자동 CD 계획](v1-central-auto-cd-action-plan.md) | Worker·GitHub App·digest 등 이전 범위의 계획 |
| [2026-09-28 인계](v1-handoff-2026-09-28.md) | 당시 전달된 EC2·ECR 상태와 보류 작업의 근거 |
| [개인 AWS 접근 안내](v1-human-aws-access.md) | 당시 초기 구축용 권한 검토. 현재 배포 역할·개인 권한 설정 지침으로 사용하지 않음 |
| [2026-09-29 구현·로컬 검증 문제 기록](v1-implementation-notes-2026-09-29.md) | FE 브랜치 조사, Bash·Git Bash·jq·가짜 도구 시험 등 실제 작업 기록 |

대체된 결정의 번호와 변경 이유는 [기술 결정](../technical-decisions.md)에 남겨 두었다. 삭제된 Python CD 엔진·IAM·감시 초안의 소스는 Git 이력에서 확인한다.
