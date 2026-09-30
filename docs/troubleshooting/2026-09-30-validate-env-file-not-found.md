# 2026-09-30 Validate에서 `backend.env not found`

## 🐞 에러 내용

새 CD PR의 Validate deployment → Check compose 단계가 실패해 병합할 수 없었다. 운영 영향은 없었다.

```text
Run eval "$(jq -r '.images | "export NGINX_IMAGE_TAG=…' deployment/production-manifest.json)"
env file /opt/keepgo/runtime/backend.env not found: stat /opt/keepgo/runtime/backend.env: no such file or directory
Error: Process completed with exit code 1.
```

로컬에서는 같은 명령이 통과했다.

## 🔍 원인 분석

로컬(Compose v5.0.2)에서 재현했다.

| 명령 | 결과 |
| --- | --- |
| `docker compose -f compose.yaml config --no-env-resolution --quiet` | 통과 |
| `docker compose -f compose.yaml config --quiet` | `env file … backend.env not found` |

- `compose.yaml`의 backend·ai-api env_file과 Grafana의 `monitoring.env`는 `required: true`이고, EC2에만 있다.
- 로컬 v5는 `--no-env-resolution`일 때 env_file 확인을 건너뛴다. ubuntu-24.04 러너의 Compose v2는 여전히 파일이 있는지 확인한다. **같은 옵션이 버전에 따라 다르게 동작했다.**

## ✅ 해결 방법

- `.github/workflows/validate.yaml`에 "Create placeholder runtime files" 단계를 추가했다.
- `/opt/keepgo/runtime/`에 빈 env·JWT·Grafana 비밀번호 파일을 만든다. 값은 읽지 않고 구조만 검사한다.
- main 병합 후 Validate 성공을 확인했다.

## 회고

- 로컬 통과가 CI 통과를 보장하지 않는다. 특히 Compose처럼 버전별 동작이 다른 도구는 CI 결과로 최종 확인한다.
- EC2에만 있는 경로를 compose에 추가하면 Validate의 placeholder 목록도 함께 갱신한다.
