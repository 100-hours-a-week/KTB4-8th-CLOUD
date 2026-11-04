# app — KeepGo V3 공통 애플리케이션 차트

9개 실행 단위(API·Worker·AI·Web)를 이 차트 하나로 배포한다. 서비스마다 다른 점은 values 파일로만 표현하고, 새 서비스를 추가할 때 차트는 고치지 않는다.

## 만드는 리소스

| 리소스 | 조건 | 역할 |
|---|---|---|
| Deployment | 항상 | Pod 실행, 헬스체크, 롤링 배포, 종료 처리 |
| Service | `service.enabled: true` | 클러스터 안 고정 주소. worker는 끈다 |
| ServiceAccount | `serviceAccount.create: true` | Pod 신원. AWS 권한(IRSA·Pod Identity)을 여기에 연결한다 |
| 테스트 Pod | `helm test` 실행 시 | Service 이름으로 HTTP 통신이 되는지 확인 |

HPA·KEDA·PDB·HTTPRoute·ExternalSecret은 다음 단계에서 추가한다.

## 기본값 기준

기본값은 Spring Boot API 기준이다(9개 중 7개).

| 항목 | 기본값 |
|---|---|
| 포트 | `http` 8080(앱), `management` 8081(Actuator 헬스·지표) |
| Service | 80 → `http` |
| startup | `management /actuator/health/liveness`, 최대 150초 대기 |
| readiness | `management /actuator/health/readiness` (Redis·DB 순간 장애로 전체 Pod가 빠지지 않게 전체 health는 보지 않음) |
| liveness | `management /actuator/health/liveness` |
| 종료 | preStop 10초 대기 → SIGTERM → 최대 40초 |
| 배포 | `maxUnavailable: 0`, `maxSurge: 25%` |
| 보안 | UID 10001, 읽기 전용 루트 파일시스템(`/tmp`만 쓰기 가능), 권한 상승 금지 |
| 리소스 | requests 250m / 768Mi, limits 메모리 1Gi (CPU limit 없음) |

ai-api(FastAPI 8000·9464), web(Next.js 3000), worker(Service 없음)는 서비스별 values에서 덮어쓴다.

## 서비스별 values 예시

```yaml
# values/dev/auth-api.yaml
image:
  repository: <계정>.dkr.ecr.ap-northeast-2.amazonaws.com/keepgo-backend
  tag: "f6760bc7b98e"

env:
  SPRING_PROFILES_ACTIVE: dev
  EPHEMERAL_DATABASE: redis
  REDIS_HOST: redis.data.svc.cluster.local

# ExternalSecret이 만든 Secret을 환경변수로
envFrom:
  - secretRef:
      name: auth-api-env

# JWT PEM은 파일로
secretFiles:
  - name: jwt
    secretName: backend-jwt
    mountPath: /run/secrets
    items:
      - key: JWT_PUBLIC_KEY
        path: jwt_public_key.pem
      - key: JWT_PRIVATE_KEY
        path: jwt_private_key.pem
```

기본값에 있는 환경변수를 빼려면 값을 `null`로 둔다(`env.JAVA_TOOL_OPTIONS: null`).

## 로컬 검증 (kind)

필요한 도구: Docker Desktop(실행 중), kind, helm, kubectl. 명령은 레포 루트에서 실행한다.

```bash
# 1. 문법·렌더링 확인
helm lint charts/app -f values/local/mock-a.yaml
helm template mock-a charts/app -n mock -f values/local/mock-a.yaml

# 2. 클러스터 만들기
kind create cluster --name keepgo-local

# 3. 같은 차트로 Mock API 두 개 배포
helm install mock-a charts/app -n mock --create-namespace -f values/local/mock-a.yaml
helm install mock-b charts/app -n mock -f values/local/mock-b.yaml
kubectl -n mock get pods -o wide

# 4. Service 통신 확인 (A는 80, B는 8080 포트)
helm test mock-a -n mock
helm test mock-b -n mock
kubectl -n mock run curl --rm -it --restart=Never --image=busybox:1.37 -- \
  sh -c 'wget -qO- http://mock-a; wget -qO- http://mock-b:8080'

# 5. Pod 삭제 후 다시 생기는지
kubectl -n mock delete pod -l app.kubernetes.io/instance=mock-a
kubectl -n mock get pods -w

# 6. 정리
kind delete cluster --name keepgo-local
```

readiness 실패 확인은 Mock이 모든 경로에 200을 돌려주므로 probe 포트를 열리지 않은 번호(예: `probes.readiness.port: 9999`)로 바꿔 `helm upgrade`한 뒤 Pod가 `0/1 Running`으로 남는지 보면 된다.
