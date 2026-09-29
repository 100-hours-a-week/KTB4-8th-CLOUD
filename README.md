# KeepGo Cloud — Backend 중앙 자동 CD

단일 EC2의 `web`(Nginx), `frontend`(Next.js), `backend`, `ai-api` 구성을 유지하며 **Backend만 중앙에서 자동 배포**한다. Worker는 이번 단계에서 제외한다.

```text
Backend main CI 성공 / SHA 이미지 게시
  → Cloud dispatch 또는 10분 polling
  → JSON Manifest 후보 PR (Backend SHA + digest + CI run ID)
  → 출처·변경 범위·ECR 검증 → 자동 병합
  → Cloud main → SSM → 고정 커밋의 별도 release 디렉터리
  → 호스트 잠금 → Backend만 교체 → health·연결·HTTPS·재시작 관찰
  → 성공 기록 / Backend 복구·실패 이미지 차단
```

버전의 기준은 `deployment/production-manifest.json` 하나다. Compose와 GitHub Workflow는 YAML을 사용한다. main의 실제 이미지 SHA와 Secret·JWT·RDS·업로드·TLS·메모리·로그 설정을 보존했다.

**현재는 병합 및 로컬 검증 단계다.** ECR digest와 Backend CI run ID는 외부에서 확인하지 않아 `null`로 남겼다. 구조 검사는 허용하지만 실제 배포는 거부한다. pin → Manifest 반영 → 기존 스택 adopt → 자동 CD 활성화 순서가 필요하다. Backend CI는 현재 `main`과 `dev` 이미지를 게시하지만 Cloud는 `main` 성공만 받는다. 현재 BE CI의 `bootjar`는 테스트 성공을 보장하지 않는다.

- [기술 결정·대안 비교·판단 이유 — 한 문서에 누적](docs/technical-decisions.md)
- [현재 설계](docs/v1-design.md)
- [초기 연결·자동 배포·복구 절차](docs/v1-operations.md)
- [App 계약과 검사의 한계](docs/v1-app-contracts.md)
- [파일별 역할](docs/v1-files-and-push-guide.md)
- [트러블슈팅](docs/v1-troubleshooting.md)
- [구현 및 검증 현황](docs/v1-implementation-status.md)

```sh
python scripts/validate-manifest.py --structure-only
python -m unittest discover -s tests -v
bash -n scripts/deploy.sh
bash -n scripts/bootstrap-host.sh
```

Python 검사에는 외부 패키지가 필요 없다. Compose 구조 검사에는 `config --no-env-resolution`을 지원하는 Docker Compose CLI가 필요하며 daemon은 필요 없다. 실제 EC2 통합 검증은 별도다.
