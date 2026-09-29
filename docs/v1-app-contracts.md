# Backend 중앙 CD의 App 계약

## 현재 사용하는 계약

- Backend repo: `100-hours-a-week/KTB4-8th-BE`.
- CI: `.github/workflows/ci.yml`, job 표시 이름 `Main - Build and Push Image`.
- `main` push의 성공한 CI만 후보로 수용한다. 같은 workflow의 dev 빌드는 거부한다.
- Backend ECR: `keepgo-backend`, 소스 40자리 SHA 태그, Manifest에 ECR digest 고정.
- Compose 이름: web=Nginx, frontend=Next.js, backend=Spring, ai-api=FastAPI. Worker 없음.
- Runtime: main의 Secret-v1-BE/Secret-v1-AI와 env/JWT 파일, TLS·업로드 mount를 유지한다.

## 검사와 한계

main의 healthcheck를 사용한다. Backend는 8080 TCP, AI는 `/health`, Nginx는 `/healthz`, Frontend는 Node fetch다. 배포 엔진은 Nginx→Frontend HTTP와 Backend→AI/RDS TCP, 외부 HTTPS `/`·`/healthz`, 재시작 관찰을 추가한다.

`/app/bin/healthcheck`, `/app/bin/smokecheck`, `/app/bin/queue-metrics`, `/api/health/ready`를 기존 앱에 요구하거나 호출하지 않는다. Worker·DB job 계약은 이번 범위에서 제외한다.

최신화된 로컬 BE CI는 `bootjar`로 빌드하며 테스트를 생략한다. 따라서 성공 job 검증은 빌드·게시 출처를 확인할 뿐 테스트 통과를 의미하지 않는다. TCP 연결도 DB 쿼리 성공이나 업무 API 정상 응답을 보장하지 않는다. Backend readiness·업무 smoke를 실제 이미지와 Nginx 경로에 맞춰 확정하면 그 계약을 검사에 추가한다.

## App 변경 시 지킬 것

이미지 롤백 기간에는 이전 Backend와 호환되는 DB schema를 유지한다. 비호환 schema 변경과 Secret 변경은 자동 이미지 교체에 섞지 않는다. SHA 태그는 덮어쓰지 않으며 현재·직전 정상 이미지는 복구 기간 동안 보존한다. Cloud 알림에는 group=backend, sha, run_id만 보내고 비밀값은 포함하지 않는다.

선택·대안·사유는 [기술 결정 기록](technical-decisions.md)에 누적한다.
