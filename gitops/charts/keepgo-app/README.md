# keepgo-app — KeepGo V3 공통 애플리케이션 차트

9개 실행 단위(API·Worker·AI·Web)를 이 차트 하나로 배포한다(위키 5-4 7장). 서비스마다 다른 점은 values 파일로만 표현하고, 새 서비스를 추가할 때 차트는 고치지 않는다.

> `keepgo-gitops` 저장소가 아직 없어서 이 레포의 `gitops/`를 그 저장소의 루트로 두고 5-4 3.2 구조를 따른다. 저장소가 생기면 `gitops/` 아래를 그대로 옮긴다.

## 만드는 리소스

| 리소스 | 조건 | 역할 |
|---|---|---|
| Deployment | 항상 | Pod 실행, 헬스체크, 롤링 배포, 종료 처리 |
| Service | `service.enabled: true` | 클러스터 안 고정 주소. worker는 끈다 |
| ServiceAccount | 항상 | Pod 신원. EKS Pod Identity로 서비스별 IAM 역할을 연결한다 |
| 테스트 Pod | `helm test` 실행 시 | Service 이름으로 HTTP 통신이 되는지 확인 |

5-4 7.2의 나머지(HPA, KEDA ScaledObject, PDB, ExternalSecret, NetworkPolicy, HTTPRoute)는 다음 단계에서 추가한다.

## 차트가 강제하는 규칙

values에 아래가 빠지거나 규칙을 어기면 렌더링이 실패한다. GitOps CI(5-4 4.6)에서 걸린다.

| 규칙 | 근거 |
|---|---|
| `image.repository`, `image.tag` 필수, `latest` 금지 | 5-4 4.3 |
| `resources.requests.cpu`, `requests.memory`, `limits.memory` 필수 | 5-4 7.3 |
| 메모리 `requests` = `limits` | 5-3 3.2 |
| `probes.preset`은 `spring`, `fastapi`, `nextjs` 중 하나 | 5-4 7.3 |

## 기본값

기본값은 핵심 Spring API 기준이다.

| 항목 | 기본값 | 근거 |
|---|---|---|
| 포트 | `http` 8080, `management` 8081(Actuator, 외부 비노출) | 5-3 4.3 |
| Service | 80 → `http` | |
| Probe | `spring` 프리셋 (아래 표) | 5-3 4.3 |
| 종료 | preStop 10초 → SIGTERM → Spring graceful 25초, 상한 40초 | 5-3 4.5·4.6 |
| 배포 | `maxSurge: 1`, `maxUnavailable: 0`, `progressDeadlineSeconds: 600` | 5-3 5.3, 5-4 9.1 |
| JVM | `MaxRAMPercentage=70` | 5-3 3.2 |
| 우선순위 | `keepgo-default` | 5-3 6.6 |
| 분산 | 노드 기준 Soft 켬, AZ 기준 Hard 끔(핵심 API만 켬) | 5-3 6.6 |
| 보안 | UID 10001, 읽기 전용 루트 파일시스템(`/tmp`만 쓰기), 권한 상승 금지, ServiceAccount 토큰 미부착 | |

### Probe 프리셋

| 프리셋 | startup (최대 대기) | readiness | liveness | 포트 |
|---|---|---|---|---|
| `spring` | `/actuator/health/liveness` (150초) | `/actuator/health/readiness` | `/actuator/health/liveness` | management |
| `fastapi` | `/health/live` (60초) | `/health/ready` | `/health/live` | http |
| `nextjs` | `/` (60초) | `/` | `/` | http |

프리셋 값 중 일부만 바꾸려면 그 항목만 적는다.

```yaml
probes:
  preset: spring
  startup:
    failureThreshold: 40   # 기동이 느린 서비스
  readiness:
    enabled: false         # worker: Service가 없으므로 readiness를 쓰지 않는다
```

## 서비스별로 바꿀 값

| 서비스 | 바꿀 값 |
|---|---|
| 핵심 API (auth, chat, recommend, ai-api) | `priorityClassName: keepgo-high`, 2-AZ 확정 후 `topologySpread.zone.enabled: true` |
| SSE (chat, recommend) | `terminationGracePeriodSeconds`를 재연결 유도 시간만큼 늘림 |
| ai-api | `probes.preset: fastapi`, 포트 8000, `command`(uvicorn), Spring 환경변수 `null` |
| web | `probes.preset: nextjs`, 포트 3000, `component: web`, Spring 환경변수 `null` |
| worker | `component: worker`, `service.enabled: false`, `probes.readiness.enabled: false`, `containerPorts`는 management만, `strategy`는 쿠버네티스 기본값(25%/25%), `priorityClassName: keepgo-low`, `topologySpread.node.enabled: false`, 종료 시간은 SQS Visibility Timeout 기준 |

리소스 초기값은 5-3 3.3 표를 따른다.

## 서비스 values 예시

5-4 3.2 구조에 맞춰 `apps/<namespace>/<서비스>/`에 둔다.

```yaml
# gitops/apps/account/auth-api/values.yaml (환경 공통)
image:
  repository: <계정>.dkr.ecr.ap-northeast-2.amazonaws.com/keepgo-auth-api

priorityClassName: keepgo-high

resources:
  requests:
    cpu: 250m
    memory: 768Mi
  limits:
    memory: 768Mi

envFrom:
  - secretRef:
      name: auth-api-env      # ExternalSecret이 만든 Secret

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

```yaml
# gitops/apps/account/auth-api/values-dev.yaml (CI가 태그를 커밋)
image:
  tag: "f6760bc7b98e"

env:
  SPRING_PROFILES_ACTIVE: dev
  EPHEMERAL_DATABASE: redis
  REDIS_HOST: redis.data.svc.cluster.local
```

## 로컬 검증 (kind)

필요한 도구: Docker Desktop(실행 중), kind, helm, kubectl. 명령은 레포 루트에서 실행한다.
`ci/`의 Mock 두 개는 프리셋(nextjs·fastapi), 포트, 우선순위, 종료 시간이 서로 다르다.

```bash
CHART=gitops/charts/keepgo-app

# 1. 문법·렌더링 확인
helm lint $CHART -f $CHART/ci/mock-a-values.yaml
helm lint $CHART -f $CHART/ci/mock-b-values.yaml
helm template mock-a $CHART -f $CHART/ci/mock-a-values.yaml

# 2. 클러스터 만들기 + 우선순위 등록 (차트보다 먼저 있어야 Pod가 생성된다)
kind create cluster --name keepgo-local
kubectl apply -f gitops/platform/priority-classes/

# 3. 같은 차트로 Mock 두 개 배포
helm install mock-a $CHART -n mock --create-namespace -f $CHART/ci/mock-a-values.yaml
helm install mock-b $CHART -n mock -f $CHART/ci/mock-b-values.yaml
kubectl -n mock get pods -o wide

# 4. Service 통신 확인 (A는 80, B는 8000 포트)
helm test mock-a -n mock
helm test mock-b -n mock

# 5. Pod 삭제 후 다시 생기는지
kubectl -n mock delete pod -l app.kubernetes.io/instance=mock-a
kubectl -n mock get pods -w

# 6. 정리
kind delete cluster --name keepgo-local
```

규칙 위반이 막히는지도 확인한다. 아래는 둘 다 실패해야 정상이다.

```bash
# 메모리 requests ≠ limits
helm template x $CHART -f $CHART/ci/mock-a-values.yaml --set resources.limits.memory=64Mi
# resources 누락
helm template x $CHART --set image.repository=a,image.tag=b
```

readiness 실패 확인은 Mock이 모든 경로에 200을 돌려주므로 probe 포트를 열리지 않은 번호(`--set probes.readiness.port=9999`)로 바꿔 `helm upgrade`한 뒤 Pod가 `0/1 Running`으로 남는지 보면 된다.
