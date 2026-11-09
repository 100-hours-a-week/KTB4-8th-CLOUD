> **위키 사본(스냅샷)** — 원본: [5‐3.-리소스·확장·보안-정책](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%903.-%EB%A6%AC%EC%86%8C%EC%8A%A4%C2%B7%ED%99%95%EC%9E%A5%C2%B7%EB%B3%B4%EC%95%88-%EC%A0%95%EC%B1%85)  
> 기준: 위키 커밋 `addfeea`(2026-11-04), 복사 2026-11-09. **수정은 위키에서 하고, 바뀌면 이 사본을 다시 복사한다.**

## 1. 설계 목적 및 전제

KeepGo V3에서 실행되는 Workload의 자원 할당, 상태 검사, Pod 배치, 확장 정책을 정의한다.

- 배경: 서비스·조직 성장으로 Application별 독립 배포·확장, 자원 격리, 장애 대응 요구가 커졌다 (5-1 참고)
- 플랫폼: EKS + Karpenter
- 확장 구조
    - Pod 확장: HPA / KEDA
    - Node 확장: Karpenter

### 1.1 설계 원칙

- 서비스별 부하 특성과 중요도에 따라 자원·가용성 정책을 다르게 적용한다.
- 사용자 요청을 처리하는 API와 비동기 분석 Worker는 확장 정책을 분리한다.
- 영속 데이터는 관리형 저장소에 둬서 Node 수명과 데이터 수명을 분리한다.
- 비용은 줄이되, 핵심 서비스의 가용성이 떨어질 만큼 축소하지 않는다.
- 비동기 작업은 멱등(idempotent)하게 처리한다.
    - SQS는 at-least-once 전달이라 같은 메시지가 두 번 처리될 수 있다.
    - 재시도, Spot 중단, Node 회수로 중복 실행돼도 결과가 틀어지면 안 된다.
- 최대 Replica는 하위 의존성의 한도 안에서 정한다.
    - RDS 커넥션 수
    - 외부 AI API Rate Limit
- 초기 설정값은 가정이며, 부하 테스트와 운영 지표로 검증한다.

### 1.2 선행 아키텍처 결정 사항

| 항목 | 현재 설계 기준 | 상태 |
| --- | --- | --- |
| Kubernetes 플랫폼 | Amazon EKS (Standard 모드) | 5-1 확정 |
| Node Autoscaling | Karpenter | 5-2 확정 |
| Karpenter Controller 실행 위치 | Fargate | 5-2 확정 |
| NodePool 구성 | Application / Worker 분리, Worker는 Spot 우선 | 초기안 확정 |
| 서비스 구성 | 5-2에 정의된 8개 Deployment + web(Next.js) | 현재 설계 |
| Namespace | account, ingest, content, recommend, ai, frontend | 5-2 확정 |
| 기술 스택 | 백엔드 API·Worker: Spring Boot(JVM), ai-api: FastAPI(Python) | 현재 설계 |
| 클러스터 내부 Stateful | Redis StatefulSet (EBS PVC) | 5-2 기준 |
| 동기화 작업 큐 | Amazon SQS (DLQ 포함) | 현재 설계 |
| 관계형 DB | Amazon RDS MySQL | 기존 설계 기반 |
| DB 커넥션 관리 | 애플리케이션 커넥션 풀, RDS Proxy 도입 검토 | 미확정 |
| 외부 AI 처리 | 공통 ai-api를 통한 호출 | 현재 설계 |
| 외부 트래픽 진입 | AWS Load Balancer Controller + ALB (IP Target) | 5-2 기준 |
| NetworkPolicy | Amazon VPC CNI의 eBPF 기반 NetworkPolicy | 5-2 기준 |
| 모니터링·지표 수집 | Prometheus (KEDA 사용자 정의 지표의 전제) | 미확정 |
| 가용 영역 | Control Plane: EKS가 3-AZ로 운영 / Worker Node: 2-AZ 우선 검토 | Worker 미확정 |
| Next.js 배치 | 클러스터 내부 frontend Namespace | 5-2 기준 |
| V3 목표 트래픽 | 평시 Peak 200 RPS, 이벤트 Peak 1,600 RPS, Burst 3,200 RPS, Peak 동시 사용자 120,000 | 5-1 확정 |
| SLO | 응답 지연·가용성 목표 | 미확정 |

**AZ 구분**

- Control Plane: EKS가 3-AZ로 운영하며, 사용자가 바꿀 수 없다.
- Worker Node: 클러스터 Subnet과 Karpenter NodePool·EC2NodeClass 설정으로 정한다.
- 이 문서의 AZ 정책은 Worker Node 기준이다.

## 2. Storage 정책

### 2.1 현재 요구사항

- 주요 영속 데이터: 사용자 정보, YouTube 연동 정보, 장소·이벤트, 채팅·추천 결과
- API와 Worker는 Node나 Pod가 교체돼도 데이터가 유지돼야 한다.
- Karpenter는 사용률에 따라 Node를 추가·제거하므로, 영속 데이터를 Node 로컬 디스크에 두지 않는다.

### 2.2 저장소별 선택지

| 저장소 | 장점 | 단점 및 트레이드오프 | 판단 |
| --- | --- | --- | --- |
| RDS | DB 운영·백업 관리 부담 감소, Pod와 데이터 분리 | 인스턴스 및 스토리지 비용, 외부 DB 의존성, 커넥션 수 한도 | 관계형 데이터에 사용 |
| S3 | 높은 내구성, 객체 저장에 적합, Pod 수명과 독립 | 일반 파일시스템과 사용 방식이 다름 | 객체 저장 시 사용 |
| EBS + PVC | 영속 블록 스토리지, Kubernetes와 연동 가능 | AZ 종속성, 볼륨 관리 필요 | Redis StatefulSet에 사용 |
| EFS + PVC | 여러 Pod 간 공유 파일 접근 가능 | 네트워크 파일시스템 비용 및 지연 | 공유 파일시스템 필요 시 |
| emptyDir | 간단한 임시 저장소, 별도 영속 볼륨 불필요 | Pod 삭제 시 데이터 소멸 | 임시 데이터에 사용 |

### 2.3 서비스별 Storage 구성

| 구성요소 | Namespace | 저장 데이터 | 저장 방식 | PVC |
| --- | --- | --- | --- | --- |
| auth-api | account | 사용자 Refresh Token, 인증 이력 | RDS (토큰은 암호화 저장) | 불필요 |
| member-api | account | 회원 정보 | RDS | 불필요 |
| youtube-api | ingest | 사용자 YouTube OAuth 토큰, 동기화 상태 | RDS (OAuth 토큰은 KMS 등으로 암호화 저장) | 불필요 |
| youtube-analysis-worker | ingest | 분석 작업 메시지 및 결과 | SQS / RDS, 필요시 emptyDir | 불필요 |
| wishlist-api | content | 장소·이벤트·코스 | RDS | 불필요 |
| chat-api | recommend | 대화·슬롯 상태 | RDS + Redis (SSE 재연결 시 상태 복구) | 불필요 |
| recommend-api | recommend | 추천 결과·상태 | RDS + Redis | 불필요 |
| ai-api | ai | AI 분석·추천 데이터 | 외부 AI 서비스 / RDS 등 | 불필요 |
| redis | 미정 | SSE 진행 상태, 전역 Rate Limit 카운터 등 | StatefulSet + EBS gp3 PVC | 필요 |
| web | frontend | 없음 | - | 불필요 |

**토큰과 애플리케이션 비밀 구분**

- 사용자 토큰 (Refresh Token, YouTube OAuth 토큰)
    - RDS에 암호화해서 저장한다.
- 애플리케이션 비밀 (JWT 서명 키, Google OAuth Client Secret, DB 자격 증명, 외부 AI API Key)
    - AWS Secrets Manager 또는 SSM Parameter Store에 둔다.
    - External Secrets Operator로 Pod에 주입한다.
- AI 쪽에서 Vector DB를 직접 호스팅하게 되면 별도 Storage 설계가 필요하다.

### 2.4 선택 정책

- Application Deployment에는 PVC를 만들지 않는다.
- 클러스터 내부 Stateful 구성요소는 Redis StatefulSet 하나이며, 여기에만 EBS PVC를 쓴다.
- 영속 데이터는 RDS 등 외부 저장소에 둔다.
- 분석 중 생기는 임시 데이터는 컨테이너 파일시스템이나 `emptyDir`에 둔다.
- 임시 디스크를 쓰는 Worker
    - `emptyDir.sizeLimit`와 `ephemeral-storage` Requests/Limits를 함께 설정한다.
    - Karpenter는 ephemeral-storage Requests도 보고 Node를 고르므로, EC2NodeClass의 루트 EBS 크기도 같이 정한다.
- chat-api / recommend-api
    - SSE 재연결 시 다른 Pod로 붙을 수 있다.
    - 대화·추천 진행 상태는 Pod 메모리에만 두지 않고, Redis 또는 RDS에서 복구한다.

### 2.5 Redis StatefulSet Storage

5-2 설계에 따라 Redis는 클러스터 내부 StatefulSet으로 운영한다.

- 구성 가정: Primary 1 + Replica
- 용도: 캐시·상태 저장소
- 원본 데이터는 RDS에 둔다.

| 항목 | 설정 | 이유 |
| --- | --- | --- |
| CSI Driver | Amazon EBS CSI Driver (EKS 관리형 Add-on) | EBS 볼륨 생성·연결 |
| StorageClass | gp3, `volumeBindingMode: WaitForFirstConsumer` | Pod가 배치될 AZ가 정해진 뒤 같은 AZ에 볼륨 생성 |
| 볼륨 템플릿 | `volumeClaimTemplates`로 Pod별 PVC | 각 Redis Pod가 고유 볼륨 사용 |
| 영속성 | AOF 또는 RDB 스냅샷 | 재시작 시 캐시 재적재 부담 감소 |
| 삭제 정책 | `reclaimPolicy: Retain`, StatefulSet `persistentVolumeClaimRetentionPolicy` 명시 | 실수로 인한 볼륨 삭제 방지 |
| 백업 | EBS 스냅샷 정기 생성 | 볼륨 장애 시 복구 |
| 볼륨 확장 | `allowVolumeExpansion: true` | 운영 중 용량 증설 |

**AZ 종속성**

- EBS 볼륨은 생성된 AZ에서만 붙일 수 있다.
- 그래서 Redis Pod가 재생성되면 기존 볼륨이 있는 AZ의 Node에만 배치된다.
- 그 AZ에 용량이 없으면 Karpenter가 같은 AZ에 Node를 만들어야 한다.
    - Application NodePool의 Requirements에 두 AZ를 모두 허용한다.
- AZ 장애 시 그 AZ의 Redis Pod는 볼륨과 함께 복구되지 않는다.
    - Primary와 Replica를 서로 다른 AZ에 둔다.
    - Sentinel 등으로 Replica를 승격한다.
- Redis 데이터를 잃어도 RDS 기준으로 복구할 수 있어야 하므로, Redis를 원본 저장소로 쓰지 않는다.

### 2.6 트레이드오프

| 구조 | 장점 | 단점 |
| --- | --- | --- |
| 관리형 저장소 중심 | Pod·Node 교체와 무관하게 데이터 유지, 배치 자유도 증가, 저장소 운영 책임 감소 | 외부 서비스 비용, 네트워크 접근·인증 관리, 관리형 서비스 장애 의존 |
| 클러스터 내부 Storage | 스토리지 수명과 접근 정책을 클러스터에서 함께 관리 | CSI 운영, 볼륨 연결·AZ 제약, 백업·복구 책임 증가 |

**결론**

- 영속 데이터는 RDS 등 관리형 저장소에 둔다.
- 클러스터 내부 Stateful은 Redis StatefulSet만 두고 EBS PVC를 쓴다.
- Redis는 캐시·상태 저장소로만 쓰고, Primary와 Replica를 AZ 간에 나눠 배치한다.
- 사용자 토큰은 RDS에 암호화해 저장하고, 애플리케이션 비밀은 Secrets Manager로 분리한다.

## 3. Resource Requests / Limits

### 3.1 현재 요구사항

- 실행 스택
    - Spring Boot: HTTP API, SSE 서비스, 분석 Worker
    - FastAPI: ai-api
- JVM 서비스 특성
    - 기동할 때 CPU를 많이 쓴다.
    - Heap 외에 Metaspace, Thread Stack, Direct Buffer 메모리도 쓴다.
- 서비스마다 자원 사용 패턴이 다르므로, CPU·Memory를 일괄로 같게 주지 않는다.
- Karpenter와 kube-scheduler는 실제 사용량이 아니라 Pod의 Requests를 보고 Node를 고르고 만든다.
    - Requests와 실제 사용량이 크게 벌어지지 않게 관리한다.

### 3.2 기본 정책

**CPU Requests**

- 정상 처리에 필요한 최소 수준으로 잡는다.
- 실제 사용량과 HPA 확장 기준을 같이 본다.
- 너무 크게 잡아서 Node가 불필요하게 늘지 않게 한다.

**CPU Limits**

- 초기에는 설정하지 않는다.
- 이유
    - Limit을 걸면 Throttling이 생길 수 있다.
    - Spring Boot는 기동 시 JIT 컴파일·클래스 로딩으로 CPU를 순간적으로 많이 쓴다. Limit이 있으면 기동이 크게 느려진다.
- 특정 서비스가 CPU를 독점하는 게 확인되면 그 서비스에만 적용한다.

**Memory Requests / Limits**

- Requests = Limits로 설정한다.
- 이유
    - Requests < Limits인 Pod가 한 Node에 모이면, 스케줄러 기준으로는 여유가 있어도 실제 메모리는 오버커밋된다.
    - 부하가 동시에 몰리면 OOMKilled보다 kubelet의 Node-pressure Eviction이 먼저 일어나, 상관없는 Pod까지 축출될 수 있다.
- 값이 너무 낮으면 OOMKilled가 나므로 부하 테스트로 조정한다.

**JVM 메모리 (Spring Boot)**

- `XX:MaxRAMPercentage=70~75`로 Heap 상한을 컨테이너 메모리에 맞춘다.
- 고정 `Xmx`는 쓰지 않는다. Limit을 바꿀 때마다 같이 고쳐야 하기 때문이다.
- 나머지 25~30%는 Metaspace, Thread Stack, Direct Buffer 등 Native 메모리용으로 남긴다.
- SSE 서비스는 연결 수에 따라 Native 메모리가 늘어나므로, 연결 수별 메모리 추이를 따로 측정한다.

**FastAPI (ai-api)**

- Pod 안의 Uvicorn Worker는 1~2개로 두고, 처리량은 Pod Replica로 늘린다.
- 외부 LLM 응답을 기다리는 동안 CPU를 거의 쓰지 않으므로 CPU Requests는 낮게 시작한다.

### 3.3 서비스별 초기 자원 가정

아래 값은 기술 스택을 반영한 예시 초기값이다. 측정 기반의 최종값은 아니다.

| Deployment / StatefulSet | 스택 | CPU Request | Memory Request = Limit |
| --- | --- | --- | --- |
| auth-api | Spring Boot | 250m | 768Mi |
| member-api | Spring Boot | 250m | 768Mi |
| youtube-api | Spring Boot | 250m | 768Mi |
| wishlist-api | Spring Boot | 300m | 1Gi |
| chat-api | Spring Boot (SSE) | 300m | 1Gi |
| recommend-api | Spring Boot (SSE) | 300m | 1Gi |
| ai-api | FastAPI | 200m | 512Mi |
| youtube-analysis-worker | Spring Boot | 500m | 1Gi |
| redis | Redis | 200m | 1Gi (`maxmemory`는 Limit의 70~75%) |
- CPU Limit은 일괄 적용하지 않는다.
- Redis는 `maxmemory`를 Limit보다 낮게 둔다. AOF 재작성, 복제 버퍼 등으로 메모리를 더 쓸 때 OOMKilled를 막기 위해서다.
- youtube-analysis-worker는 임시 디스크 사용량에 맞춰 `ephemeral-storage` Requests/Limits를 추가한다.
- web(Next.js)은 자원 프로파일을 따로 정한다.

### 3.4 DB 커넥션 예산

Pod가 늘면 RDS 커넥션도 같이 는다. 최대 Replica는 아래 조건을 만족해야 한다.

```latex
\sum_{\text{service}} (\text{MaxReplica} \times \text{HikariCP maximumPoolSize}) + \text{운영 여유분} \le \text{RDS max\_connections}
```

- HikariCP `maximumPoolSize`는 서비스별로 직접 정한다. 기본값 10을 그대로 쓰지 않는다.
- youtube-analysis-worker는 0에서 N으로 급증하므로 커넥션 급증의 주 원인이 될 수 있다.
    - Worker의 최대 Replica와 풀 크기를 먼저 제한한다.
- 롤링 배포 중에는 maxSurge만큼 Pod가 일시적으로 늘어나므로 그만큼 여유분을 둔다.
- 합계가 한도에 가까워지면 RDS Proxy 도입을 검토한다.

### 3.5 자원 산정 및 검증

**측정 지표**

- CPU 평균 사용량, 높은 백분위 사용량
- Memory Working Set·Peak, JVM Heap / Non-Heap 사용량
- CPU Throttling
- OOMKilled, Eviction 발생 여부
- Pod Restart 횟수
- 응답 시간, JVM GC 일시정지 시간
- Node Allocatable 대비 Requests 합계
- 임시 디스크 사용량
- RDS 활성 커넥션 수, HikariCP 대기 시간

**조정 기준**

- 실제 사용량을 확인한 뒤 Requests를 조정한다.
- HPA의 CPU Utilization은 Requests 대비 비율이다.
    - CPU Limit이 없으면 200~300%처럼 100%를 넘게 표시될 수 있다.
    - Requests를 바꾸면 같은 부하에서도 확장 시점이 달라진다.
- JVM 기동 직후 CPU가 튀는 구간이 HPA 과잉 확장으로 이어지지 않게 HPA 안정화 설정을 같이 둔다 (5.4 참고).

### 3.6 Karpenter와의 연계

- 기존 Node에 배치할 자원이 없으면, Karpenter가 NodePool 조건에 맞는 새 Node를 만든다.
- Requests를 크게 잡은 경우
    - 실제로는 자원이 남아도 Node가 추가돼 비용이 는다.
- Requests를 작게 잡은 경우
    - Pod가 한 Node에 몰려, 부하 시 CPU 경합과 메모리 압박이 생긴다.
- Requests는 Node 수와 비용에 직접 영향을 주므로, 측정값을 근거로 관리한다.

### 3.7 트레이드오프

| 선택 | 장점 | 감수하는 한계 |
| --- | --- | --- |
| Requests 보수적 상향 | Pod 자원 확보 및 부하 안정성에 유리 | Node 증가, 비용 및 자원 낭비 가능 |
| Requests 낮게 설정 | 높은 자원 집적률 | 자원 경합 및 성능 저하 위험 |
| CPU Limit 적용 | CPU 사용량 상한 제어 | Throttling, JVM 기동 지연 |
| CPU Limit 미설정 | 여유 CPU 활용, 빠른 기동 | 다른 워크로드와 경합 가능 |
| Memory Request = Limit | 오버커밋 없음, Eviction 위험 감소 | 유휴 메모리 회수 불가, 단가 상승 |
| Memory Request < Limit | 높은 집적률 | Node 메모리 오버커밋, Node-pressure Eviction 위험 |

**결론**

- 서비스별로 Requests를 정한다.
- Memory는 Requests = Limits로 둔다.
- JVM은 `MaxRAMPercentage`로 Heap을 컨테이너 크기에 맞춘다.
- CPU Limit은 처음에는 걸지 않고, 운영 결과를 보고 서비스별로 적용한다.
- 최대 Replica는 DB 커넥션 예산 안에서 정한다.

## 4. Probe 및 정상 종료 정책

### 4.1 현재 요구사항

- 서비스별로 배포·재시작이 따로 일어나므로, 프로세스가 떠 있는 것만으로 정상이라고 판단할 수 없다.
- Pod가 종료되는 경우
    - 롤링 배포
    - Karpenter Consolidation, Node 교체
    - Spot 회수
- 상태 검사와 정상 종료 정책을 함께 정한다.

### 4.2 Probe 종류 및 역할

| Probe | 목적 | 실패 시 동작 |
| --- | --- | --- |
| Startup | 애플리케이션 초기화 완료 확인 | 연속 실패 시 컨테이너 재시작 |
| Readiness | 요청을 처리할 준비가 되었는지 확인 | Service의 요청 전달 대상에서 제외 |
| Liveness | 프로세스가 정상적으로 동작하는지 확인 | 연속 실패 시 컨테이너 재시작 |

### 4.3 서비스별 적용 정책

| 서비스 | 스택 | Readiness | Liveness | Startup |
| --- | --- | --- | --- | --- |
| auth-api | Spring Boot | 적용 | 적용 | 적용 |
| member-api | Spring Boot | 적용 | 적용 | 적용 |
| youtube-api | Spring Boot | 적용 | 적용 | 적용 |
| wishlist-api | Spring Boot | 적용 | 적용 | 적용 |
| chat-api | Spring Boot | 적용 | 적용 | 적용 |
| recommend-api | Spring Boot | 적용 | 적용 | 적용 |
| ai-api | FastAPI | 적용 | 적용 | 초기화 특성에 따라 |
| youtube-analysis-worker | Spring Boot | 미적용 (Service 미노출) | 적용 | 적용 |

**Spring Boot**

- Startup Probe를 기본 적용한다.
    - 기동에 수십 초가 걸려, Liveness 실패로 재시작이 반복될 수 있기 때문이다.
- Actuator의 Probe 그룹을 쓴다.
    - Liveness: `/actuator/health/liveness`
    - Readiness: `/actuator/health/readiness`
    - `management.endpoint.health.probes.enabled=true`로 활성화한다.
- Actuator 포트는 외부 Ingress에 노출하지 않는다.
- DB 등 외부 의존성 Health Indicator는 Liveness 그룹에 넣지 않는다.

**FastAPI (ai-api)**

- `/health/live`, `/health/ready` 엔드포인트를 둔다.
- ready는 앱 초기화와 외부 AI 클라이언트 생성 여부만 확인한다.

**Worker**

- HTTP 요청을 받지 않으므로 Readiness는 쓰지 않는다.
- Liveness는 아래 중 하나로 확인한다.
    - 내부 포트로 연 Actuator 엔드포인트
    - 처리 루프가 주기적으로 갱신하는 Heartbeat

### 4.4 Probe 설계 원칙

**Liveness**

- 애플리케이션 자체가 비정상인지만 본다.
- 외부 Gemini API, SQS, RDS의 일시 장애로는 실패하지 않게 한다.
    - 외부 장애 하나로 전체 Pod가 반복 재시작되는 것을 막기 위해서다.

**Readiness**

- 새 요청을 받을 수 있는지 본다.
- 초기화 전이거나 종료 절차에 들어간 Pod는 요청 대상에서 뺀다.
- 외부 의존성 장애는 Readiness로 처리하지 않는다.
    - 모든 Pod가 동시에 NotReady가 되면 서비스 전체가 503을 반환한다.
    - 외부 장애는 애플리케이션의 오류 응답과 Circuit Breaker로 처리한다.

**Startup**

- 초기화가 오래 걸리는 서비스에 적용한다.
- `failureThreshold × periodSeconds`를 측정된 최대 기동 시간보다 넉넉하게 잡는다.

### 4.5 Graceful Shutdown

- Pod 종료와 Endpoint·ALB Target 제거는 동시에 일어나지 않는다.
- SIGTERM을 받은 뒤에도 몇 초 동안 새 요청이 들어올 수 있다.
- 그래서 모든 HTTP 서비스에 `preStop` 지연을 둔다.

**공통 설정**

- `preStop`: `sleep 10` 내외. Endpoint 제거와 ALB Target 등록 해제가 반영될 시간을 확보한다.
- Spring Boot: `server.shutdown=graceful`, `spring.lifecycle.timeout-per-shutdown-phase` 설정
- FastAPI(Uvicorn): `-timeout-graceful-shutdown` 설정
- ALB Target Group의 `deregistration_delay`를 기본값(300초)에서 서비스에 맞게 줄인다.

**일반 HTTP API**

1. 종료 신호 수신 (preStop 지연 동안 트래픽 유입이 멈춤)
2. 새로운 요청 수신 중단
3. 진행 중인 요청 정리
4. DB 연결 등 리소스 정리
5. 정상 종료

**SSE 서비스**

1. 종료 신호 수신
2. 신규 SSE 연결 수락 중단
3. 기존 연결에 재연결 유도 이벤트 전송 후 연결 종료
4. 유예 시간 내 정상 종료
5. 클라이언트가 다른 Pod로 재연결하고 공유 저장소에서 상태 복구
- 모든 연결이 자연 종료될 때까지 기다리지 않는다.
- 클라이언트는 `Last-Event-ID` 등으로 재연결하고, 대화·추천 상태는 Redis 또는 RDS에서 복구한다.
- ALB idle timeout(기본 60초)보다 짧은 주기로 Heartbeat를 보내거나, idle timeout을 조정한다.

**Worker**

1. 종료 신호 수신
2. 신규 SQS 메시지 수신 중단
3. 진행 중인 작업을 가능한 범위에서 완료
4. 완료한 작업의 결과 저장 및 메시지 삭제
5. 미완료 작업은 메시지를 삭제하지 않아 Visibility Timeout 이후 재처리되도록 유지
6. 정상 종료
- 메시지는 처리 완료와 결과 저장을 확인한 뒤 삭제한다.
- 결과 저장은 작업 ID 기준으로 멱등하게 수행한다. 같은 메시지가 두 번 처리돼도 결과가 중복되지 않게 한다.

**SQS 설정 기준**

- Visibility Timeout은 작업 처리 시간 p99보다 길게 잡는다.
    - 처리 시간이 길고 편차가 크면, 처리 중에 `ChangeMessageVisibility`로 주기적으로 연장한다.
- DLQ와 `maxReceiveCount`를 설정해서 반복 실패 작업을 따로 모으고 경보를 보낸다.

### 4.6 종료 유예 시간

- `terminationGracePeriodSeconds`에는 preStop 지연과 애플리케이션 종료 시간이 모두 들어가야 한다.
    - 일반 API: preStop + 진행 중 요청 정리 시간 (예: 30초)
    - SSE API: preStop + 재연결 유도 및 연결 종료 시간
    - Worker: 작업 처리 시간과 SQS Visibility Timeout을 고려한 시간
- Spot 회수는 2분 전 경고만 온다.
    - 유예 시간을 길게 잡아도 Spot 위 Worker에는 2분 이상 보장되지 않는다.
    - 2분 안에 끝나지 않는 작업은 재처리로 복구한다.
- 정확한 값은 실제 종료 시간을 측정한 뒤 정한다.
- Karpenter NodePool의 `terminationGracePeriod`(Node 강제 종료 상한)와 충돌하지 않는지 확인한다.

### 4.7 트레이드오프

| 정책 | 장점 | 한계 |
| --- | --- | --- |
| 적극적인 Liveness 검사 | 비정상 프로세스 빠른 복구 | 오탐 시 재시작 증가 |
| 보수적인 Liveness 검사 | 불필요한 재시작 감소 | 장애 감지 지연 |
| 긴 종료 유예 시간 | 진행 중인 요청 및 Job 정리 가능성 증가 | 배포·노드 축소 지연, Spot에는 효과 없음 |
| 짧은 종료 유예 시간 | Pod 교체 및 Node 회수 속도 향상 | 진행 중인 작업 중단 위험 |
| 긴 preStop 지연 | 종료 중 요청 유실 방지 | 배포·축소 시간 증가 |

**결론**

- Probe로 요청을 받을 수 있는 상태인지 판단한다.
- 외부 의존성 장애와 애플리케이션 자체 장애를 구분한다.
- Spring 서비스는 Startup Probe를 기본 적용한다.
- 모든 HTTP 서비스는 preStop 지연을 ALB 등록 해제 시간에 맞춘다.
- Worker는 Spot 2분 제약을 감안해 멱등한 재처리 구조로 만든다.

## 5. Pod Replica 및 확장 정책

### 5.1 현재 요구사항

- 서비스마다 필요한 가용성과 확장성이 다르다.
    - 인증·추천 등 사용자 요청을 직접 처리하는 서비스: 상시 가용성이 중요하다.
    - YouTube 분석 Worker: 즉시 응답보다 최종 완료와 복구 가능성이 중요하다.
- 서비스별로 최소 Replica와 확장 지표를 다르게 정한다.

### 5.2 서비스별 Replica 기본 방향

- 아래 최소 Replica는 2-AZ와 핵심 사용자 경로의 상시 가용성을 전제로 한 초기 제안이다.
- 최대 Replica는 아래를 함께 보고 정한다.
    - 5-1 목표 트래픽: 이벤트 시 Peak 1,600 RPS, Burst 3,200 RPS, Peak 동시 사용자 120,000
    - 부하 테스트 결과
    - 3.4의 DB 커넥션 예산
    - 외부 AI Rate Limit

| Deployment | Namespace | 초기 최소 Replica 제안 | 확장 방식 | 확장 지표 |
| --- | --- | --- | --- | --- |
| auth-api | account | 2 | HPA | CPU |
| member-api | account | 2 | HPA | CPU |
| youtube-api | ingest | 1~2 | HPA | CPU |
| youtube-analysis-worker | ingest | 0 | KEDA | SQS 메시지 수 |
| wishlist-api | content | 2 | HPA | CPU |
| chat-api | recommend | 2 | KEDA | 활성 SSE 연결 수 |
| recommend-api | recommend | 2 | KEDA | 활성 SSE 연결 수 |
| ai-api | ai | 2 | KEDA | 처리 중 요청 수 |
- web(Next.js)은 frontend Namespace에 두고, 자원·확장 정책은 따로 정한다.
- Redis는 StatefulSet이며 확장 대상이 아니다. Primary 1 + Replica 구성으로 고정 운영한다.
- SSE와 ai-api의 확장 지표는 애플리케이션 계측(Micrometer / Prometheus Client)이 가능한지 먼저 확인한다.
- KEDA는 내부적으로 HPA 객체를 만들므로, KEDA를 쓰는 Deployment에는 HPA를 따로 정의하지 않는다.

### 5.3 배포 전략 (RollingUpdate)

- PDB는 배포 중 가용성을 보장하지 않는다. 배포 중 가용성은 RollingUpdate 설정으로 보장한다.
- 핵심 API: `maxUnavailable: 0`, `maxSurge: 1`
    - 새 Pod가 Ready가 된 뒤에 기존 Pod를 종료한다.
- Worker: 기본값 사용
    - 종료된 Pod의 작업은 재처리로 복구한다.
- maxSurge로 일시적으로 늘어나는 Pod 수를 DB 커넥션 여유분(3.4)과 Node 용량에 반영한다.

### 5.4 HPA 적용 정책

- 일반 API는 CPU Utilization 기반 HPA로 시작한다.
- 요청량, 응답 지연, DB 처리 시간을 함께 모니터링한다.
- JVM 기동 직후 CPU 급증과 JIT 워밍업 구간이 불필요한 Scale-out으로 이어지지 않게 한다.
    - `behavior.scaleUp`에 안정화 구간을 둔다.
    - Scale-down은 보수적으로 설정한다 (`stabilizationWindowSeconds` 300초 내외).
- CPU 사용률과 실제 처리 성능이 잘 맞지 않는 서비스는 사용자 정의 지표로 보완한다.

### 5.5 KEDA 적용 정책

**youtube-analysis-worker**

- SQS 메시지 수에 따라 Pod 수를 조절한다.
    - 메시지가 없으면 0개까지 축소
    - 메시지가 늘면 처리 용량에 맞춰 증가
- 최대 Replica는 DB 커넥션 예산과 ai-api 배치 경로의 동시 처리 상한을 넘지 않게 한다.
- 작업 완료 시간과 가장 오래 대기한 메시지의 대기 시간을 모니터링한다.
- In-flight 메시지 포함 여부(`scaleOnInFlight`)를 검토한다.
    - SQS에는 대기 중 메시지와 처리 중 메시지가 따로 있다.
    - 처리 중 메시지를 빼고 계산하면, 작업 중인 Worker가 축소 대상이 될 수 있다.

**Scale-to-Zero의 Cold Start**

0개에서 시작하면 첫 작업 처리까지 아래 지연이 쌓인다.

1. KEDA 폴링 주기 (기본 30초)
2. Karpenter Node 생성 및 Ready (Worker NodePool에 빈 Node가 없을 때)
3. 컨테이너 이미지 Pull
4. Spring Boot 기동 및 Startup Probe 통과
- 이 지연이 동기화 완료 목표 시간을 넘으면 최소 Replica를 1로 바꾼다.

**chat-api / recommend-api**

- 활성 SSE 연결 수를 Prometheus로 수집해 KEDA 확장 지표로 쓰는 방향을 검토한다.
- SSE 확장 시 고려할 점
    - Scale-out을 해도 기존 연결은 새 Pod로 옮겨가지 않는다. 새 Pod는 새 연결만 받으므로, 이미 부하가 걸린 Pod의 부담은 바로 줄지 않는다.
    - Scale-in 시 그 Pod의 연결은 모두 끊긴다. Scale-down 안정화 구간을 길게 두고, 한 번에 줄이는 Pod 수를 제한한다.
    - 연결당 메모리 사용량을 측정해서 Pod당 목표 연결 수를 정한다.
- 장시간 연결을 처리하므로 Scale-to-Zero는 적용하지 않는다.

**ai-api**

- 동시에 처리 중인 요청 수를 주요 확장 지표로 검토한다.
- CPU만으로 판단하지 않는다.
    - 외부 LLM 호출이 느려지면 CPU 사용률이 낮아도 처리 중 요청은 늘어난다.
- 외부 AI API Rate Limit에 걸린 상태라면 Pod를 늘려도 처리량이 늘지 않는다.

### 5.6 ai-api 경로 분리와 전역 호출 제한

- ai-api는 두 경로가 같이 쓴다.
    - 사용자 요청 경로: chat-api, recommend-api
    - 배치 경로: youtube-analysis-worker
- YouTube 동기화가 몰리면 Worker가 ai-api의 처리 용량과 외부 AI Rate Limit을 차지해서, 사용자 응답이 늦어질 수 있다.

| 방안 | 방식 | 장점 | 한계 |
| --- | --- | --- | --- |
| A. 동시성 풀 분리 | ai-api 내부에서 사용자·배치 요청의 동시 처리 한도를 별도로 관리 | 구성 단순, Deployment 유지 | 같은 Pod 자원 공유 |
| B. Deployment 분리 | ai-api(사용자)와 ai-api-batch를 별도 배포·확장 | 자원·확장 정책 완전 격리 | 운영 대상 증가 |
| C. Worker 측 제한 | Worker 최대 Replica와 작업당 호출 수로 배치 경로 상한 제어 | 추가 구현 최소 | 사용자 경로 보호가 간접적 |
- 초기에는 A + C를 적용하고, 배치 부하가 커지면 B로 바꾼다.
- Rate Limit은 외부 AI 제공자 기준의 전역 한도다.
    - Pod별 동시 호출 제한만 두면 `Pod당 제한 × Replica`만큼 전체 호출량이 늘어난다.
    - 전역 관리가 필요하면 Redis 기반 Token Bucket 등 공유 Rate Limiter를 검토한다.
    - 최대 Replica는 `전역 한도 ÷ Pod당 동시 호출 수`를 넘지 않게 한다.

### 5.7 Pod Replica와 Karpenter의 관계

1. 트래픽 또는 분석 작업 증가
2. HPA/KEDA가 목표 Replica 증가
3. 기존 Node에 배치 가능한지 확인
4. 배치할 수 없는 Pod가 생기면 Karpenter가 해당 NodePool에서 Node 증설
5. Node 준비 후 Pod 실행
6. 부하 감소에 따라 Pod 축소
7. 필요 없는 Node를 Karpenter가 제거하거나 통합
- Karpenter는 Pod Replica 수를 정하지 않는다.
- Pod 확장 정책 없이 Node Autoscaling만으로는 트래픽 증가에 대응할 수 없다.

### 5.8 Replica 및 확장 트레이드오프

| 선택 | 장점 | 한계 |
| --- | --- | --- |
| Min Replica 1 | 상시 비용 감소 | Pod 장애·교체 시 일시 중단 가능 |
| Min Replica 2 이상 | Pod 장애·배포 중 가용성 확보에 유리 | 상시 비용 증가 |
| Worker Scale-to-Zero | 유휴 자원 비용 절감 | Pod·Node 시작에 따른 처리 지연 |
| 높은 Max Replica | 순간적인 부하 대응 여력 증가 | 인프라·외부 API 비용 급증, DB 커넥션 고갈 |
| 낮은 Max Replica | 비용과 동시 처리량 통제 | 요청 대기·응답 지연 증가 가능 |

**결론**

- 핵심 API는 상시 실행한다.
- Worker는 KEDA Scale-to-Zero를 쓰되, Cold Start가 목표를 넘으면 최소 1개로 바꾼다.
- ai-api는 배치 부하로부터 사용자 경로를 보호한다.
- 최대 Replica는 성능 목표, 비용 상한, DB 커넥션 예산, 외부 AI 전역 한도를 함께 보고 정한다.

## 6. Scheduling 및 Karpenter Node 정책

### 6.1 현재 요구사항

- API, SSE, AI API, Worker처럼 부하 특성이 다른 서비스가 같은 클러스터에서 돈다.
- YouTube 분석 Worker는 동기화 요청이 몰리면 Pod 수가 빠르게 늘어난다.
    - Worker가 자원을 많이 써도 일반 API에 영향이 가지 않게 배치와 Node 확장을 나눈다.
- Karpenter는 Node를 동적으로 만들고 지운다.
    - Node가 줄어드는 과정에서 핵심 서비스가 불필요하게 끊기지 않게 한다.

### 6.2 Node 운영 선택지

| 구성 | 장점 | 단점 |
| --- | --- | --- |
| 단일 공용 NodePool | 단순한 운영, 자원 활용률 개선 | 워크로드 간 자원 경합, Spot 사용 시 API Pod가 Spot에 배치될 위험 |
| API / Worker 분리 | 부하 격리, 독립적인 비용·확장·회수 정책 | Node 파편화 및 비용 증가 가능 |
| 서비스별 NodePool | 강한 격리, 세밀한 정책 설정 | 운영 복잡도·유휴 용량 증가 |

### 6.3 초기 구성: Application / Worker NodePool 분리

- Application NodePool과 Worker NodePool을 나누고, Worker NodePool은 Spot을 우선 쓴다.
- 분리하는 이유
    - 공용 NodePool 하나에 On-Demand와 Spot을 섞으면 핵심 API Pod가 Spot Node에 올라갈 수 있다.
    - Worker와 API의 Node 회수 정책을 다르게 가져갈 수 없다.

**System Capacity (Fargate + 소규모 Managed Node Group)**

- Karpenter Controller는 Fargate에서 실행한다 (5-2 결정).
    - Karpenter가 자기가 관리하는 Node 위에서 도는 순환 의존을 피한다.
    - system 노드그룹 고정비를 줄인다.
- Fargate Profile은 Karpenter Namespace에만 적용한다.
- 나머지 클러스터 컴포넌트는 소규모 Managed Node Group에 둔다.
    - 대상: CoreDNS, KEDA Operator, AWS Load Balancer Controller, Prometheus, External Secrets Operator 등
    - Karpenter가 동작하지 않을 때도 이 컴포넌트들이 유지되도록, Karpenter가 회수하지 않는 Node에 둔다.
- DaemonSet(VPC CNI, EBS CSI Node, Pod Identity Agent, 수집 Agent)은 Fargate에서 돌지 않으므로 각 Node에 그대로 배치된다.
- 2-AZ 확정 시 Managed Node Group은 AZ별 최소 1 Node를 유지한다.

**Application NodePool**

- 대상: auth, member, youtube, wishlist, chat, recommend, ai-api, redis
- On-Demand 인스턴스
- 인스턴스 유형은 Pod Requests에 맞춰 Karpenter가 고른다.
    - JVM 서비스는 메모리 비중이 크므로 메모리 비율이 높은 계열을 Requirements에 넣는다.
- 보수적인 Consolidation

**Worker NodePool**

- 대상: youtube-analysis-worker
- Spot 우선, Taint로 다른 Pod 배치를 막는다.
- SQS 작업량에 따라 늘리고, 작업이 줄면 적극적으로 회수한다.
- 여러 인스턴스 계열·크기를 허용해서 Spot 확보 실패 가능성을 낮춘다.
- Spot 확보에 실패하면 On-Demand로 넘어간다.
    - Worker NodePool의 `capacity-type`에 On-Demand를 같이 허용하거나
    - Weight가 낮은 On-Demand 대체 NodePool을 둔다.

### 6.4 Karpenter 설정 요소

| 설정 | 역할 | KeepGo 적용 방향 |
| --- | --- | --- |
| NodePool | Node 생성 조건 및 동작 정책 | Application / Worker 분리 |
| EC2NodeClass | AMI·Subnet·Security Group·루트 볼륨 등 AWS 설정 | 환경별 인프라 설정, Worker는 임시 디스크 용량 반영 |
| Requirements | AZ·Instance Family·Capacity Type 제한 | Application: on-demand / Worker: spot(+on-demand fallback) |
| Limits | NodePool 최대 CPU·Memory 등 | Worker NodePool에 비용 상한으로 적용 |
| Weight | 여러 NodePool이 해당될 때 우선순위 | Spot NodePool 우선, On-Demand 대체 NodePool 후순위 |
| Taints / Tolerations | 특정 NodePool의 Pod 실행 제한 | Worker NodePool에 Taint, Worker에 Toleration |
| Node Affinity / nodeSelector | 조건에 맞는 Node 선택 | Pod가 자기 NodePool로 가도록 지정 |
| Consolidation | 불필요한 Node 제거·통합 | Application: WhenEmpty 중심 / Worker: WhenEmptyOrUnderutilized |
| Disruption Budgets | Karpenter의 자발적 Node 중단 속도·시간대 제한 | Application은 동시 1 Node, 사용 집중 시간대 제한 |
| expireAfter | Node 최대 수명 이후 자동 교체 | 교체 주기를 명시하고 Disruption Budget 안에서 진행 |
| terminationGracePeriod | Node 비우기 강제 종료 상한 | PDB나 do-not-disrupt 때문에 Node 교체가 무기한 막히지 않도록 설정 |
| Interruption Queue | Spot 중단·리밸런스·EC2 상태 이벤트 수신 | Worker Spot 사용 시 필수 (EventBridge + SQS) |
- NodePool은 Managed Node Group 같은 EC2 묶음이 아니다.
    - 어떤 조건의 Node를 만들지 정하는 정책이다.
    - 실제 EC2는 Pod 요구량에 따라 그때그때 만들어진다.
- Interruption Queue가 없으면 Karpenter가 Spot 중단 경고를 받지 못한다.
    - 대체 Node를 미리 띄우거나 Pod를 먼저 옮길 수 없다.
- Node가 교체되는 경우는 Consolidation 말고도 있다.
    - `expireAfter` 만료
    - Drift (AMI·NodeClass 변경)
    - 모두 같은 Disruption Budget과 PDB를 적용받는다.

### 6.5 Application과 Worker 격리 방식

- Worker NodePool에 Taint를 건다.
- Worker에는 Toleration과 nodeSelector를 같이 설정한다.
    - Toleration만 있으면 Worker가 Application Node에도 올라갈 수 있다.
- 감수하는 비용: Application Node에 자원이 남아도 Worker가 쓸 수 없다.
- 운영 후 Worker 부하가 작고 자원 경합이 없으면 공용 On-Demand 구성으로 합치는 것을 다시 검토한다.

**실행 중인 작업 보호**

- 짧은 작업은 Consolidation으로 끊겨도 재처리로 복구한다.
- 긴 작업이 Consolidation으로 자주 끊기면, 처리 중인 Pod에 `karpenter.sh/do-not-disrupt`를 다는 방안을 검토한다.
- do-not-disrupt는 Spot 회수를 막지 못한다. NodePool `terminationGracePeriod`가 상한이다.

**Redis StatefulSet 배치**

- Application NodePool(On-Demand)에 둔다. Spot Node에는 두지 않는다.
- Primary와 Replica는 `topologySpreadConstraints`(AZ 기준, `DoNotSchedule`)로 서로 다른 AZ에 둔다.
- EBS 볼륨이 AZ에 묶여 있어서 재생성된 Pod는 원래 AZ에만 올라간다.
    - Application NodePool이 두 AZ 모두에서 Node를 만들 수 있어야 한다.
- Node 교체(Consolidation, expireAfter) 때 Primary 전환이 생길 수 있다.
    - Redis Pod에 `karpenter.sh/do-not-disrupt`를 단다.
    - 교체는 트래픽이 적은 시간에 계획해서 한다 (5-2 R3).

### 6.6 Pod 분산 정책

- 핵심 API는 Node 하나가 죽어도 Replica가 같이 내려가지 않게 분산한다.
- 사용할 수 있는 설정
    - `TopologySpreadConstraints`: Node 또는 AZ 간 Replica 분산
    - `PodAntiAffinity`: 같은 서비스 Replica가 한곳에 몰리지 않게 함
    - `NodeAffinity`: 특정 NodePool에 Pod 배치
    - `PriorityClass`: 자원이 부족할 때 핵심 서비스 우선

**PriorityClass 초기안**

| 등급 | 대상 |
| --- | --- |
| 최상위 | System 컴포넌트 (Karpenter, CoreDNS, KEDA 등) |
| 높음 | auth-api, chat-api, recommend-api, ai-api, redis |
| 기본 | member-api, youtube-api, wishlist-api |
| 낮음 | youtube-analysis-worker |

**초기 선택 방향**

- 핵심 API는 Node 간 분산을 우선한다.
- 2-AZ가 확정되면 핵심 API(auth, chat, recommend, ai-api)는 AZ 분산을 Hard Constraint(`DoNotSchedule`)로 건다.
    - Soft로만 두면 Replica 2개가 같은 AZ에 올라가 2-AZ를 쓰는 의미가 없어질 수 있다.
- 나머지 API는 Soft Constraint로 시작한다.
- Worker는 가용성보다 자원 효율과 처리량을 우선한다.

### 6.7 Hard / Soft Scheduling 비교

| 방식 | 특징 | 트레이드오프 |
| --- | --- | --- |
| Hard Constraint | 조건을 반드시 만족해야 Pod 배치 | 배치 보장 수준은 높지만 Pending 위험 |
| Soft Constraint | 조건 만족을 선호하되 필수는 아님 | 배치 유연성은 높지만 분산 보장 불가 |
- Hard Constraint는 꼭 필요한 서비스에만 건다.
- Karpenter가 Node를 만들 수 있어도 Pod가 Pending될 수 있는 경우
    - AZ 용량 부족
    - NodePool 제약
    - AWS Quota
    - Subnet IP 부족
- VPC CNI는 Pod마다 VPC IP를 하나씩 주므로, Subnet 크기와 Prefix Delegation 적용 여부를 같이 정한다.

### 6.8 Karpenter Consolidation

**Application NodePool**

- `consolidationPolicy: WhenEmpty`로 시작해 비어 있는 Node만 먼저 정리한다.
- `consolidateAfter`를 길게 잡아 짧은 부하 변동마다 Node가 바뀌지 않게 한다.
- Disruption Budget
    - 동시에 중단하는 Node는 1개로 제한한다.
    - 사용자가 몰리는 시간대에는 schedule로 중단을 막는 것을 검토한다.
- 비용 지표를 보고 `WhenEmptyOrUnderutilized`로 바꿀지 판단한다.

**Worker NodePool**

- `consolidationPolicy: WhenEmptyOrUnderutilized`로 적극적으로 줄인다.
- SQS 재처리, 멱등 처리, 정상 종료 정책과 함께 적용한다.

### 6.9 PDB 적용

- 핵심 API: `maxUnavailable: 1`
- Redis StatefulSet: `maxUnavailable: 1` (Primary와 Replica가 동시에 축출되지 않게 함)
- Worker: PDB 미적용 (중단되면 재처리로 복구)

**`minAvailable: 1`을 쓰지 않는 이유**

- Replica가 1개일 때 축출을 영구히 막는다.
- youtube-api처럼 최소 Replica가 1일 수 있는 서비스에 걸면, 그 Node의 Consolidation과 expireAfter 교체가 멈춘다.

**PDB가 못 하는 것**

- Node 비자발적 장애(Spot 회수 포함)는 막지 못한다.
- 배포 중 가용성은 보장하지 않는다. 이건 5.3의 RollingUpdate 설정으로 보장한다.
- PDB를 너무 엄격하게 걸면 Consolidation과 Node 교체가 오래 지연된다.
- PDB, Pod Replica, Karpenter Disruption Budget, NodePool terminationGracePeriod는 함께 정한다.

### 6.10 Scheduling 트레이드오프

| 정책 | 장점 | 감수하는 한계 |
| --- | --- | --- |
| 공용 NodePool | 높은 자원 활용률, 단순한 운영 | 워크로드 경합, Spot 혼용 불가 |
| Worker 별도 NodePool | 비동기 부하 격리, Spot 적용 가능 | 운영 비용 및 파편화 증가 |
| Multi-AZ 분산 | AZ 장애 영향 감소 | 비용·Cross-AZ 데이터 전송 및 배치 제약 증가 |
| 엄격한 Pod 분산 | 특정 장애 도메인에 집중되는 위험 감소 | Pending 및 Node 증가 가능 |
| 적극적 Consolidation | 비용 절감 | Pod 재배치와 연결 중단 가능 |
| 보수적 Consolidation | 실행 안정성 개선 | 유휴 자원 비용 증가 |
| Spot Worker | 컴퓨팅 비용 절감 | 2분 경고 후 회수, 재처리 필요 |

**결론**

- Application NodePool: On-Demand, 보수적 Consolidation
- Worker NodePool: Spot, 적극적 Consolidation
- Spot을 쓰기 위해 Interruption Queue와 On-Demand Fallback을 같이 구성한다.
- Redis는 Application NodePool에 두고 AZ 간 분산, do-not-disrupt를 적용한다.
- PDB는 `maxUnavailable` 기준으로 걸어 Node 교체를 막지 않게 한다.

## 7. 정책 간 종속성 및 통합 검증

아래 설정들은 서로 영향을 주므로 함께 확인한다.

| 설계 요소 | 연결되는 정책 | 확인해야 할 내용 |
| --- | --- | --- |
| Requests | Karpenter / Scheduling | Node 프로비저닝 및 비용 |
| CPU Requests | HPA | CPU Utilization 계산 기준 |
| Memory Request : Limit 비율 | Node 메모리 | 오버커밋 및 Node-pressure Eviction |
| Replica | Node Capacity | 최소 운영 및 최대 확장에 필요한 자원 |
| Max Replica · maxSurge | RDS 커넥션 | 커넥션 합계가 max_connections 이내인지 |
| Max Replica | 외부 AI Rate Limit | 전역 한도 초과 시 확장 효과 없음 |
| Worker 확장 | ai-api 사용자 경로 | 배치 부하가 사용자 응답을 지연시키지 않는지 |
| Readiness | Service / Deployment | 트래픽 수신과 RollingUpdate |
| preStop · Graceful Shutdown | ALB / Karpenter | 종료 중 요청 유실 여부, Node 축소 시 요청·작업 정리 |
| SSE Heartbeat | ALB idle timeout | 유휴 연결 강제 종료 여부 |
| PDB | Karpenter Consolidation · expireAfter | 자발적 Node 중단 가능 여부 |
| SQS Worker | KEDA / Spot | Visibility Timeout, 재시도·중복 처리·작업 유실 방지 |
| Spot | Interruption Queue | 중단 경고 수신 및 사전 대응 |
| PVC | Scheduling / AZ | 볼륨을 사용할 수 있는 Node 위치 |

### 7.1 장애 검증 시나리오

| 상황 | 예상 동작 | 검증 기준 |
| --- | --- | --- |
| API Pod 비정상 종료 | Deployment가 Pod 재생성 | 복구 시간, 오류율 |
| Readiness 실패 | 해당 Pod가 요청 대상에서 제외 | 정상 Pod로 트래픽 전달 |
| 롤링 배포 | preStop 이후 기존 Pod 종료 | 배포 중 5xx 발생 여부 |
| Node 장애 | 다른 Node에 Pod 재배치 또는 신규 Node 생성 | 서비스 중단 시간 |
| AZ 장애 | 남은 AZ로 트래픽 집중, Redis Replica 승격 | 남은 AZ의 처리 여력, 장애 조치 시간 |
| Redis Primary Node 교체 | Replica 승격 후 기존 Pod가 같은 AZ에서 볼륨과 함께 재기동 | 상태 유실 여부, SSE 재연결 성공률 |
| Worker Spot 중단 | Interruption 이벤트 수신, 메시지 재처리 및 대체 Worker 실행 | Job 유실·중복 반영 여부 |
| Spot 용량 부족 | On-Demand Fallback으로 Worker 실행 | Fallback 소요 시간 |
| SQS 작업 급증 | KEDA가 Replica 확장 | 대기 시간, 처리량, RDS 커넥션 수 |
| 배치 급증 중 사용자 채팅 | ai-api 사용자 경로 응답 유지 | 사용자 경로 p95 지연 변화 |
| Worker 0 → 1 Cold Start | KEDA 감지 → Node 생성 → Pod 기동 | 첫 작업 처리까지 소요 시간 |
| SSE Pod Scale-in | 재연결 유도 후 다른 Pod로 재연결 | 재연결 성공률, 상태 복구 여부 |
| 이벤트 트래픽 (Peak 1,600 RPS) | HPA/KEDA 확장 및 Karpenter Node 증설 | 확장 완료까지 시간, 그 사이 오류율 |
| Node 자원 부족 | Karpenter가 Node 프로비저닝 | Pending 해소 시간 |
| NodePool 용량 제한 도달 | 신규 Pod Pending 가능 | 경보·처리량 제한 동작 |
| Karpenter Controller(Fargate) 재시작 | 기존 Node·Pod는 영향 없음, 확장만 일시 중단 | 재기동 시간, Pending 누적 |
| Karpenter Consolidation | Pod 정상 종료 후 Node 회수 | 서비스 오류율 및 Job 재처리 |
| Image Pull 실패 | Pod가 실행되지 못함 | 감지·롤백 및 복구 시간 |
| OOMKilled / Eviction | 컨테이너 재시작 또는 Pod 축출 | 메모리 설정 및 오류 원인 분석 |
- Node·AZ·Spot 관련 시나리오는 AWS FIS로 장애를 주입해 검증한다 (5-2 R1).

### 7.2 추가 측정 지표

**Application**

- RPS, 응답 지연 p95/p99 (ai-api는 사용자 경로와 배치 경로 분리)
- HTTP 오류율
- SSE 활성 연결 수, 재연결 횟수
- 처리 중 AI 요청 수
- Pod CPU·Memory, JVM Heap·GC 일시정지 시간
- Pod Restart / OOMKilled / Eviction
- RDS 활성 커넥션 수, HikariCP 커넥션 대기 시간

**Worker**

- SQS 대기 메시지 수
- 가장 오래 대기한 메시지의 경과 시간
- Job 처리 시간 및 성공률
- 재시도·DLQ 메시지 수, 중복 처리 감지 건수
- 외부 AI API Rate Limit 발생 횟수
- Cold Start 소요 시간

**Cluster / Karpenter**

- Pending Pod 수 및 지속 시간
- Node 생성·준비 소요 시간
- NodePool별 CPU·Memory 예약량
- Consolidation·Expiration·Drift·Interruption 발생
- Node별 자원 사용률
- On-Demand / Spot 비용, Spot Fallback 발생 횟수
- NodePool Limits 및 EC2 용량 부족 이벤트
- Subnet 가용 IP 수

## 8. 미확정 사항 및 후속 작업

### 반드시 확정해야 할 사항

1. **Capacity:** 5-1 목표 트래픽을 서비스별 RPS·동시 SSE 연결·일일/순간 분석 Job 수로 분해
2. **가용성:** SLO, 핵심 API의 허용 중단 시간, Worker 동기화 완료 목표 시간
3. **Node:** Worker Node 2-AZ 여부, System 컴포넌트용 Managed Node Group 크기
4. **Redis:** 사용 범위(SSE 상태·Rate Limit 등), Namespace, Primary/Replica 및 장애 조치 방식, 영속성(AOF/RDB) 설정
5. **Resource:** 실제 측정 기반 Requests/Limits 및 JVM 메모리 설정
6. **DB:** RDS 인스턴스 클래스와 max_connections, 서비스별 커넥션 풀 크기, RDS Proxy 도입 여부
7. **Scaling:** 최대 Replica, 확장 임계값, 외부 AI 전역 Rate Limit 수치와 ai-api 경로 분리 방식
8. **Disruption:** PDB, Consolidation, expireAfter, Graceful Shutdown 및 SQS Visibility Timeout
9. **Observability:** 모니터링 스택 확정 (KEDA 사용자 정의 지표의 전제)
10. **Ingress:** ALB idle timeout, deregistration_delay, SSE 경로 설정

## 9. 최종 설계 방향

KeepGo V3는 서비스마다 다른 배포·확장·자원·가용성 정책을 Kubernetes 하나로 관리한다.

**데이터**

- 영속 데이터는 RDS 등 외부 저장소에 둬서 Node 수명과 분리한다.
- 클러스터 내부 Stateful은 Redis StatefulSet만 두고, 캐시·상태 저장소로 쓴다.

**자원과 Probe**

- Spring Boot와 FastAPI 특성에 맞춰 Requests/Limits와 Probe를 정한다.
- Memory는 Requests = Limits로 오버커밋을 피한다.
- 모든 HTTP 서비스는 preStop 지연을 포함한 정상 종료 절차를 갖춘다.

**확장**

- 일반 API: HPA (CPU)
- SSE·ai-api: KEDA (사용자 정의 지표)
- 분석 Worker: KEDA (SQS)
- 최대 Replica는 RDS 커넥션과 외부 AI Rate Limit 한도 안에서 정한다.
- ai-api는 배치 부하로부터 사용자 경로를 보호한다.

**Node**

- Karpenter로 Node를 운영하고, Controller는 Fargate에서 실행한다.
- Application NodePool: On-Demand, 보수적 회수
- Worker NodePool: Spot, 적극적 회수
- Worker는 멱등한 재처리 구조로 Spot의 2분 회수 제약을 감수한다.

**주의할 점**

- Replica를 많이 두거나, Scheduling을 엄격하게 걸거나, Requests를 크게 잡으면 비용이 는다.
- Node를 공격적으로 줄이면 실행 중인 서비스가 불안정해진다.
- 초기값은 가정이며, 부하 테스트·장애 실험·운영 지표를 보고 조정한다.