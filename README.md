# KeepGo Cloud — v1 중앙 자동 CD

> **2026-09-28 현재 상태:** Worker 이미지는 미게시, 앱 검사 계약은 미확정, S3는 미사용이다. 검사 주석 처리와 준비 확인에 따른 실행 보류가 적용되어 있다. 기존 EC2는 팀원이 운영 중이다. [최신 인계·추가 정보](docs/v1-handoff-2026-09-28.md)와 [파일별 사용법·푸시 지침](docs/v1-files-and-push-guide.md)을 먼저 읽는다. 아래 기존 S3 설치·검사 활성화·최초 스택 교체 절차는 현재 그대로 실행하지 않는다.

단일 EC2에서 Nginx, Next.js(Node), Spring Backend, Worker, FastAPI를 Docker Compose로 실행한다. 데이터와 job 큐는 MySQL RDS에 둔다.

**변경된 배포 단위만 중지 후 교체한다.** Backend와 Worker는 서로 다른 이미지·버전을 사용하며 배포와 롤백도 독립적이다. Frontend CI에서 함께 게시하는 Web·Nginx는 한 단위다. SSE, ECS, 별도 메시지 큐, 롤링 배포는 v1에 포함하지 않는다.

```text
App main CI 성공 / SHA 이미지 게시
  → Cloud 후보 요청 + 주기적 누락 요청 보완
  → Manifest PR의 출처·필수 job·ECR 검사 → 자동 병합
  → Cloud main → SSM → EC2 잠금 → 변경 대상만 stop / recreate
  → Health + HTTPS + DB job smoke + 관찰 + 장애 알람 검사
  → 성공 기록 / 실패한 단위만 이전 구성 복구·검증·알림
```

- [설계와 기술 결정](docs/v1-design.md)
- [설치·배포·장애·롤백 운영 절차](docs/v1-operations.md)
- [v1 중앙 CD 트러블슈팅](docs/v1-troubleshooting.md)
- [App 팀 계약: 헬스 검사·DB job 큐·마이그레이션](docs/v1-app-contracts.md)
- [구현 및 검증 현황](docs/v1-implementation-status.md)

현재는 **저장소 구현 단계**다. 운영 값은 예시/자리표시자로 남겨 두었고 `CD_ENABLED=true` 설정 전에는 운영 CD와 후보 수신을 실행하지 않는다. 앱 이미지의 검사 명령 구현, GitHub 보호 규칙, AWS 리소스 설치와 실환경 복구 훈련까지 마쳐야 운영 구축 완료다.

로컬 검사(외부 Python 패키지 불필요):

```sh
python3 scripts/validate-manifest.py --structure-only
python3 -m unittest discover -s tests -v
bash -n scripts/deploy.sh scripts/bootstrap-host.sh
```

Compose 구조 검사는 Docker Compose CLI가 필요하며 Docker daemon 없이 실행 가능하다. 컨테이너 통합 검증은 실제 Linux Docker host와 계약을 구현한 App 이미지가 필요하다.
