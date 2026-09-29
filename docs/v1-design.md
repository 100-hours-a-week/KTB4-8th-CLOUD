# v1 Backend 중앙 자동 CD 설계

현재 실행 기준은 이 문서와 [운영 절차](v1-operations.md)다. 기술 선택의 비교·이유·단점·재검토 조건은 [기술 결정 기록](technical-decisions.md)에 계속 누적한다.

## 서비스와 변경 범위

| Compose 이름 | 역할 | 현재 CD의 교체 범위 |
| --- | --- | --- |
| web | Nginx / TLS / reverse proxy | 유지. Backend 교체 후 설정 reload만 실행 |
| frontend | Next.js | 유지 |
| backend | Spring API | 자동 교체·복구 대상 |
| ai-api | FastAPI | 유지 |

Worker, DB job 큐 검사, 별도 메시지 큐, ECS 전환은 이 단계에 포함하지 않는다. Compose는 병합 대상 main의 설정을 그대로 가져온다. Secret-v1-BE/AI → 호스트 env·JWT 파일을 만드는 `prepare-runtime.py`도 보존한다. 일반 Backend 배포에서는 Secret을 다시 생성하거나 다른 서비스의 런타임 파일을 갱신하지 않는다.

## 목표 버전과 실제 상태

`production-manifest.json`의 schema_version=1은 environment, region, images, digests, sources를 포함한다. images는 네 서비스의 40자리 SHA, digests는 서비스별 ECR digest, sources는 Backend의 SHA와 성공 CI run ID다. Nginx와 Frontend의 소스 SHA는 같아야 하지만 두 이미지의 digest는 각각 다르다.

초기 null은 모르는 값을 표현하며 배포 가능한 값이 아니다. pin-manifest.py가 기존 SHA를 유지하며 실제 ECR/CI를 조회해 채운다. 후보 PR은 Backend의 SHA·digest·CI 정보만 변경한다. 검증과 배포는 기록된 digest가 현재 SHA 태그의 ECR digest와 동일한지 확인한다. 태그가 바뀌면 거부한다.

호스트 current.json은 검증된 실제 구성, previous.json은 직전 성공 Backend 교체 이전 구성이다. inflight.json은 진행/중단된 작업, blocked.json은 실패 이미지·설정, frozen.json은 일반 배포 동결 상태다. 설정 스냅샷에는 env 파일 경로와 변경 감지를 위한 파일 해시를 남기며 비밀값을 펼쳐 넣지 않는다.

## 출처와 전달

Backend의 `.github/workflows/ci.yml` / `Main - Build and Push Image`가 main push에서 성공해야 한다. dev, 실패·skip job, 다른 workflow, 낡은 main 후보를 거부한다. 저장소 main의 코드를 사용하는 release-policy가 후보를 검사한다. 일반 App 후보는 사람 승인 없이 native auto-merge로 반영하고 플랫폼 변경은 현재 head에 대한 다른 maintainer의 승인을 요구한다.

GitHub OIDC → SSM → EC2의 `/opt/keepgo/cloud`에서 fetch → 검증된 main 커밋을 별도 release 디렉터리에 archive한다. 운영 checkout을 checkout/reset하지 않는다. S3는 사용하지 않는다. 소스 준비 잠금과 배포 상태 잠금을 각각 사용한다.

## 교체와 복구

기존 스택은 adopt에서 이미지 ID·Compose 설정 해시·health·연결 검사로 검증한 뒤 관리 상태로 등록한다. 자동 배포가 처음부터 전체 스택을 재생성하지 않는다.

배포는 실제 상태 확인 → Backend 신·구 이미지 사전 pull → inflight 기록 → Backend stop/recreate → Nginx reload → 검증 순서다. 다른 서비스 또는 공유 네트워크/Secret 정의 변경은 이 경로에서 거부한다. 런타임 env·JWT 내용 변경도 별도 점검이 필요하다.

실패하면 Backend만 이전 구성으로 복구한다. 복구가 성공해도 신규 배포는 실패로 기록한다. 복구 실패는 journal과 동결 상태를 유지한다. 정합화는 최신 Manifest에서 실패한 Backend만 실제 current 값으로 맞추며 이후 수정 후보를 덮어쓰지 않는다.

## 검사의 범위

main의 네 컨테이너 healthcheck, Nginx→Frontend HTTP, Backend→AI/RDS TCP, 외부 HTTPS `/`·`/healthz`, 관찰 중 재시작을 검사한다. Backend health는 TCP 수준이며 업무 API·DB 쿼리·AI 결과의 정상 여부를 보장하지 않는다. SNS와 deployment alarm 목록은 선택적으로 연결하며 빈 목록은 알람 기반 배포 차단이 없음을 뜻한다. 실제 readiness·업무 smoke 및 로그 알람 강화는 후속 과제다.
