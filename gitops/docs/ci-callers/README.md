# 앱 저장소에 넣을 호출 workflow 예시

각 앱 저장소(KTB4-8th-BE·AI·FE)의 `.github/workflows/`에 복사해 쓴다. 빌드·태그 커밋은 GitOps 저장소의 재사용 workflow(`build-and-bump.yaml`)가 한다.

앱 저장소에 필요한 설정(사용자 할 일 문서에도 있음)

| 종류 | 이름 | 내용 |
|---|---|---|
| Secret | `ECR_PUSH_ROLE_ARN` | GitHub OIDC로 받는 ECR push 전용 IAM 역할 |
| Secret | `GITOPS_APP_ID`, `GITOPS_APP_PRIVATE_KEY` | KTB4-8th-CLOUD-GITOPS에 쓰기 권한이 있는 GitHub App |
| 설정 | KTB4-8th-CLOUD-GITOPS → Settings → Actions → Access | 조직 안 저장소에서 재사용 workflow 호출 허용 |
