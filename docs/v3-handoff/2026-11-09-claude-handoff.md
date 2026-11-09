# KeepGo V3 — Claude 인수인계 문서

> **기준일:** 2026-11-09 (KST)  
> **대상:** KeepGo V3 EKS 전환 및 구축 / Cloud 담당자 **B (Platform·DevOps)**  
> **용도:** 새 Claude 세션에서 맥락 손실 없이 설계 검토와 실구현을 이어가기 위한 종합 인수인계  
> **중요:** 이 문서는 **V3를 기준**으로 작성한다. V1/V2의 기술·정책을 V3 최종안으로 간주하지 않는다. V2는 **ECS → EKS 운영 전환**에 필요한 맥락에서만 언급한다.

---

## 0. Claude에게 먼저 전달할 핵심 지시

1. KeepGo V3의 **기존 5-2·5-3 설계가 이미 작성된 상태**이다. 이미 결정한 기술을 처음부터 반복 비교하거나 동일한 정책을 재설계하지 말 것.
2. 사용자는 클라우드 담당자 **B**이며, **Helm → Kubernetes 애플리케이션 정책 구현 → Argo CD GitOps → EKS 통합 → HPA/KEDA → 안정성·관측성·검증**을 책임진다. **A는 Terraform·EKS·네트워크·노드·스토리지 기반**을 책임진다.
3. 설계 완료 / 구현 완료 / 검증 완료를 반드시 구분하라. **실제 Helm Chart, RBAC YAML, kind 배포, EKS 통합이 완료됐다는 증거는 현재 제공되지 않았다.**
4. 사용자가 가장 최근에 요청한 실무 작업은 **B 담당 RBAC 설계 문안과 Kubernetes YAML 초안**이다. 어시스턴트가 정책·YAML 예시를 작성했으나, 팀 승인·파일 반영·클러스터 적용·권한 검증은 아직 확인되지 않았다.
5. **현재 우선 과제는 RBAC 확정 및 구현과 공통 Helm Chart 구축**이다. A의 클러스터 완성을 기다리지 말고, A 의존성이 없는 Manifest / Helm / kind / 로컬 Argo CD 작업을 선행한다.
6. 사용자가 상세한 구현을 요구하면 **소스 파일·YAML·Values·검증 명령·완료 기준**까지 구체적으로 제시하라. 확인되지 않은 환경값, 리소스 이름, 서비스 포트, 실제 이미지 URL을 임의로 확정하지 말 것.
7. 외부 최신 버전/호환성 확인이 필요한 구현 선택은 공식 문서로 확인하되, 현재 대화에서 출처 없이 버전을 단정하지 말 것.

---

## 1. 프로젝트 V3 개요와 목적

**KeepGo:** YouTube Shorts 등의 관심 콘텐츠에서 장소·이벤트 정보를 추출·구조화하고, 이를 사용자의 취향·지역·날짜·시간 조건에 맞는 외출 코스 추천으로 연결하는 서비스.

**V3 목표:** ECS 기반 운영 환경을 **Amazon EKS Standard + Karpenter** 기반 Kubernetes 운영 플랫폼으로 전환. 서비스별 독립 배포 및 확장, 비동기 분석 Worker와 사용자 응답 경로의 격리, GitOps, 가용성, 관측성, 장애 대응, 비용 효율성을 강화한다.

**V3 설계상 목표치 (실측값 아님):**

| 구분 | V3 설계 목표 |
|---|---:|
| 평시 Peak | 200 RPS |
| 이벤트 Peak | 1,600 RPS |
| Burst | 3,200 RPS |
| Peak 동시 사용자 | 120,000명 |

트래픽 목표는 아직 서비스별 RPS, SSE 연결 수, 분석 Job 처리량으로 완전히 분해하지 않았다. 실제 수용 능력은 부하 테스트로 검증해야 한다.

### V3 기본 기술과 설계 상태

| 영역 | V3 기준 | 상태/주의 |
|---|---|---|
| 클라우드 | AWS 서울 `ap-northeast-2` | 선정 |
| Kubernetes | EKS Standard | 선정 |
| IaC | Terraform | 선정, A 담당 |
| GitOps | **Argo CD** (Flux 비교 후 선택) | **도구 선정**, 설치 확인 안 됨 |
| Packaging | Helm 공통 Chart + 서비스별 Values | **구현 방향**, Chart 작성 확인 안 됨 |
| Container Registry | Amazon ECR | 선정 |
| Node 자동 확장 | Karpenter | 선정 |
| Karpenter Controller | Fargate | 선정 |
| 기반 시스템 노드 | 소규모 EKS Managed Node Group | 설계 |
| Application 노드 | Karpenter On-Demand NodePool | 설계 |
| 분석 Worker 노드 | Karpenter Spot 우선 + On-Demand Fallback | 설계 |
| Pod 자동 확장 | HPA / KEDA | 정책 초안 작성, 임계값은 추후 검증 |
| 비동기 작업 큐 | Amazon SQS + DLQ | 설계 |
| DB | V3 5-3 문서상 **Amazon RDS MySQL** | **최종 개발팀 DBMS 확인 필요**. 과거 V1의 PostgreSQL을 V3 확정값으로 대체하지 말 것 |
| Redis | V3 설계상 Redis StatefulSet + EBS PVC | 실제 전환 여부·Namespace·Failover 세부값 미확정 |
| 외부 진입 | Gateway API + AWS Load Balancer Controller + ALB(IP target) | **Ingress보다 Gateway API 선택**. Controller/CRD 지원 검증 필요 |
| CNI | Amazon VPC CNI + IPv4 Prefix Delegation | 설계 |
| 네트워크 접근통제 | Amazon VPC CNI NetworkPolicy (eBPF) | 설계, 적용 검증 미확인 |
| Secret | AWS Secrets Manager 또는 SSM + External Secrets Operator | 실제 소유권/저장 경로/SecretStore 미확정 |
| 관측성 | Prometheus / Grafana 중심 | Stack 구성·운영 방법 확정 필요 |
| 데이터 저장 원칙 | RDS 등 영속 데이터는 Node 외부에 유지 | 설계 |
| 외부 AI 처리 | 공통 FastAPI `ai-api`에서 외부 AI 제공자 호출 | 외부 GPU/RunPod 등 모델 인프라는 별도 AI팀 범위 |

**주의:** 5-2 초기 초안에는 Ingress 대 Gateway API 비교 등이 있었지만 문서의 최종 선택은 Gateway API였다. 5-3에는 ALB/Ingress 표현이 일부 섞여 있다. 구현 시 **최종 Gateway API 선택을 우선**하되 API 버전·Controller의 실제 지원 범위를 확인한다.

---

## 2. V3 애플리케이션 실행 단위 (9개)

| Namespace | Deployment/워크로드 | 스택 | 책임 | Pod 확장 |
|---|---|---|---|---|
| `account` | `auth-api` | Spring Boot | OAuth 인증·토큰 관리 | HPA CPU |
| `account` | `member-api` | Spring Boot | 회원 관리 | HPA CPU |
| `ingest` | `youtube-api` | Spring Boot | YouTube 연동·동기화 요청·큐 적재 | HPA CPU |
| `ingest` | `youtube-analysis-worker` | Spring Boot | SQS Job 소비·AI 분석 호출·결과 전달 | KEDA SQS, 0까지 축소 |
| `content` | `wishlist-api` | Spring Boot | 장소·이벤트·코스 보관 및 분석 결과 반영 | HPA CPU |
| `recommend` | `chat-api` | Spring Boot / SSE | 채팅·슬롯 상태·SSE | KEDA 활성 SSE 연결 수 |
| `recommend` | `recommend-api` | Spring Boot / SSE | 코스 추천·SSE·중단 요청 | KEDA 활성 SSE 연결 수 |
| `ai` | `ai-api` | FastAPI | 영상 분석·슬롯 추출·코스 추천·외부 AI 호출 | KEDA 처리 중 요청 수 |
| `frontend` | `web` | Next.js | 프런트엔드 | 구체적 방식 미확정 |

**핵심 주의:** 이 9개는 V3의 *목표 Deployment* 구조다. Backend 소스코드가 이미 도메인별로 완전 분리되었다는 뜻이 아니다. 동일 Backend 이미지로 여러 Deployment를 시험할 수 있으며, 코드/데이터 책임의 분리 완료라고 기재하면 안 된다. Dockerfile, docker-compose.yml, 이미지 목록, 포트, Health Endpoint는 아직 제공받지 못했다.

**데이터/호출 흐름(개략):**

```text
사용자 / Web
  └─ ALB ← AWS Load Balancer Controller ← Gateway API / HTTPRoute
       ├─ auth/member/youtube/wishlist/chat/recommend API
       └─ (ai-api는 외부 직접 노출 금지)

youtube-api ── SQS (+DLQ) ── youtube-analysis-worker ── 내부 ai-api ── 외부 AI
                                               └─ 결과 저장 / 관계 업데이트 (RDS 등)
chat-api / recommend-api ── 내부 ai-api ── 외부 AI
             ├─ RDS
             └─ Redis (SSE·진행 상태/캐시 목적)
```

특히 분석 Worker가 AI API를 점유해 사용자 채팅/추천이 느려질 수 있다. 처음에는 AI API 내부 **사용자/배치 동시성 분리 + Worker 최대 동시 처리 제한**, 부하가 커지면 사용자용 `ai-api`와 배치용 Deployment 분리를 검토한다. 외부 AI 제공자 전역 Rate Limit도 고려한다.

---

## 3. A/B 최종 업무 분담 — 채택한 안

**A = Infrastructure / AWS·EKS 기반 책임**

- Terraform: VPC, Subnet, Route Table, EKS Cluster, Access Entry, MNG, Fargate, AWS IAM 등
- Karpenter 설치 기반, EC2NodeClass / NodePool 및 Spot·Consolidation·Interruption 운영
- Amazon VPC CNI, NetworkPolicy, GatewayClass/Gateway, AWS Load Balancer Controller/ALB
- RDS, SQS/DLQ, EBS CSI, Redis StatefulSet/PVC/장애 조치
- Prometheus/Grafana 설치 및 **인프라 수집 기반**
- Node/AZ/Spot/FIS 장애 실험, 노드 비용 최적화

**B = Platform / Kubernetes 애플리케이션·DevOps 책임 (사용자)**

- Helm Chart, 서비스별 Values, dev/prod 배포 매니페스트
- Namespace, Kubernetes RBAC, ResourceQuota, LimitRange
- Deployment, Service, ServiceAccount, ConfigMap, ExternalSecret 연동
- 서비스별 HTTPRoute (공통 Gateway는 A 소유)
- Argo CD, AppProject, Application, GitOps, CI/CD 연결, 배포 및 복구
- HPA, KEDA ScaledObject, Pod Resource Requests/Limits, Scheduling, PDB, Probe, RollingUpdate/Graceful Shutdown
- App 메트릭, ServiceMonitor, Grafana 앱 대시보드·알림
- Pod/SSE/Worker 장애 및 부하 테스트, 개선 측정

### 주요 경계 계약

| 항목 | A 제공/결정 | B 구현/검증 |
|---|---|---|
| EKS | Cluster·Access Entry·Node | 클러스터에 앱 배포 |
| Karpenter | NodePool Label/Taint/AZ/노드 제약 | Pod nodeSelector/affinity/toleration/spread |
| Gateway | Controller·GatewayClass·Gateway·Listener | HTTPRoute, 앱 서비스 라우팅 |
| SQS | 큐·DLQ·IAM·주소 | Worker ScaledObject, 앱 환경설정 |
| DB/Redis | 기반 인프라·접속 정책·스토리지 | 앱 연결 값, 외부 비밀 주입/상태 복구 검증 |
| Secret | Secrets Manager·인증 기반/ESO 설치 주체 협의 | 앱용 ExternalSecret·env 참조 |
| 관측성 | Prometheus/Grafana 설치·노드 메트릭 | 서비스 계측·ServiceMonitor·대시보드·알림 |
| IaC/GitOps | AWS/Cluster 기반 리소스 (Terraform) | 앱 리소스 (Argo CD) |

**특별한 미정 계약:** `metrics-server`, **KEDA Operator**, **External Secrets Operator**, Prometheus Operator/CRD, Argo CD Bootstrap 각각의 설치·업그레이드·장애 대응 소유권을 꼭 합의한다. Redis는 A 소유로 수정되었고 B는 Redis 연결 및 사용자 서비스 복구 측을 담당한다.

**원칙:** 리소스마다 **실제 관리 도구 단일화**. 동일한 Helm Release/CRD/Namespace 등을 Terraform과 Argo CD가 동시에 수정하지 않는다. A가 책임지는 NodePool도 리소스 배포 도구는 Argo CD일 수 있으므로 *업무 소유자*와 *리소스 적용 도구*를 구분한다.

---

## 4. A 담당자의 최근 결정 사항 (사용자가 직접 제공한 최신안)

### 4.1 개발·운영 전환 전략

- 첫 EKS는 **신규 dev VPC**에 구축한다.
- V2 ECS에서 부하 및 AWS FIS 장애 실험을 완료한 후 **기존 V2 prod VPC**에 별도 EKS Cluster를 추가한다.
- 일정 기간 ECS와 EKS를 병행 운영하며 기존 RDS 접속, 합산 DB 커넥션 수, 스키마 버전 호환성을 검증한다.
- dev에서 검증한 Terraform 모듈 / Helm Chart를 prod에서도 재사용하고, 환경별 입력값만 다르게 한다.
- 전환·복귀 가능 기간 종료 후 기존 ECS 정리.
- **Redis:** V2에서는 ElastiCache, V3 목표 설계는 Redis StatefulSet + EBS PVC. 상태 전환·복구 위험과 실구현 여부 검토 필요.

### 4.2 dev VPC 설계

| 항목 | 값 |
|---|---|
| Region | `ap-northeast-2` |
| VPC CIDR | `10.47.0.0/16` |
| AZ | `ap-northeast-2a`, `ap-northeast-2c` |
| Public Subnet | 2개, AZ별 /24 |
| EKS Private Subnet | 2개, AZ별 /20 |
| Data Subnet | 2개, AZ별 /24 |
| dev NAT Gateway | AZ-a에 Zonal NAT 1개 (비용 우선, AZ-a 장애시 단일 실패점) |
| IGW | 1개 |
| VPC DNS | `enable_dns_support=true`, `enable_dns_hostnames=true` |
| DHCP DNS | AmazonProvidedDNS |
| EC2 public IP auto assign | `map_public_ip_on_launch=false` 정책 (Subnet별 실제 적용 확인) |

| 서브넷 | CIDR | AZ | 용도 |
|---|---|---|---|
| `dev3-public-a` | `10.47.0.0/24` | a | ALB / NAT |
| `dev3-public-c` | `10.47.1.0/24` | c | ALB |
| `dev3-data-a` | `10.47.20.0/24` | a | RDS |
| `dev3-data-c` | `10.47.21.0/24` | c | RDS |
| `dev3-eks-private-a` | `10.47.32.0/20` | a | EKS Node/Pod |
| `dev3-eks-private-c` | `10.47.48.0/20` | c | EKS Node/Pod |

각 `/24`에서 AWS 예약 주소 제외 사용 가능 251개, `/20`에서 4091개. EKS Private 합계 8182개 주소는 **서브넷의 이론적 사용 가능 수치**이며, Prefix Delegation에 필요한 연속 /28 할당과 ENI/노드 제약 등을 함께 확인해야 한다.

**Route Tables:** Public 공통 1개, Private AZ별 1개씩, Data 1개. Private a/c는 비용 절감을 위해 같은 AZ-a NAT로 외부 Egress하는 설계. 실제 각 테이블의 0.0.0.0/0 경로와 RDS Data Subnet 격리 검증 필요.

### 4.3 Pod IP / 서비스 IP

- IPv4 / Amazon VPC CNI / Nitro 계열 EC2
- Pod IP는 VPC 사설 주소, Service ClusterIP는 별도 Service CIDR
- Prefix Delegation `/28`, `WARM_PREFIX_TARGET=1`
- **미확정:** 구체적 Service CIDR, Prefix Delegation이 Karpenter 생성 노드에도 동일하게 적용되는지, Pod IP 가용성 및 연속 prefix 확보.
- 문서 표의 Node에 MNG가 적혀 있어도 V3에는 Karpenter NodePool이 함께 존재한다. 이를 단일 MNG로 오해하지 말 것.

### 4.4 아직 미정인 A 제공 계약

- EKS API Endpoint의 Public/Private 접근 및 B가 접근할 네트워크 경로
- 사용자 IAM Role / EKS Access Entry / Kubernetes Group / Bootstrap 권한
- NodePool별 Label·Taint·AZ·인스턴스 Capacity Type과 Worker Fallback 동작
- Gateway 이름·Namespace·Listener, HTTPRoute AllowedRoutes 정책, TLS/도메인
- 관리형 Add-on 버전, Gateway API CRD와 AWS Load Balancer Controller 실제 호환
- KEDA/ESO/metrics-server/Argo CD 등 설치 소유권

### 4.5 A 문서의 미해결 질문 — 세션 내 답변

**Q. HPA도 Pod 수를 제한할 수 있는가?** 가능. HPA의 `minReplicas`, `maxReplicas`, `behavior.scaleUp/scaleDown`으로 범위와 속도를 제어한다. KEDA의 핵심 차이는 SQS 같은 이벤트 기반 Scaler, 0까지 축소되는 운영 경험 및 HPA 객체 생성/관리다. 같은 Deployment에 독립된 HPA와 KEDA 생성 HPA를 중복 생성하지 않는다. HPA 자체의 Scale-to-Zero 지원 여부는 *대상 EKS Kubernetes 버전과 Feature Gate* 기준으로 확인한다.

**Q. EKS의 etcd 선거는?** EKS 관리형 Control Plane의 etcd는 Raft 합의 프로토콜로 Leader를 선출하고 과반수가 필요하다. AWS가 Control Plane/etcd 인스턴스의 배치·복구를 관리한다. 사용자가 Worker Node를 몇 AZ에 둘지와 별개다. etcd 데이터에 사용자 접근/수동 백업 작업을 전제로 구축하지 말고 GitOps/IaC를 통해 클러스터 설정의 재현성을 확보한다.

---

## 5. V3 리소스·가용성·확장 정책 (5-3 설계 내용)

### 5.1 Storage

- 사용자 정보·OAuth 토큰·장소·추천 기록 등 핵심 영속 데이터 → RDS; OAuth 등 민감 데이터는 저장 시 암호화.
- 애플리케이션 API/Worker에는 영속 PVC를 생성하지 않음.
- Worker 임시 파일이 필요한 경우 `emptyDir`, `ephemeral-storage requests/limits`, Node 루트 디스크 용량 고려.
- Redis → **StatefulSet + EBS gp3**, `WaitForFirstConsumer`, `Retain`, AZ별 Primary/Replica, 복구·Failover 체계 필요. **실제 Sentinel/승격·가용성은 단순 Replica만으로 보장되지 않음.**
- Redis는 캐시·SSE 진행 상태·Rate Limit 등에 사용; 영구 원본은 RDS. Redis Namespace 및 서비스 실제 사용 범위는 미정.

### 5.2 Resource Requests / Limits (초기 가설, 검증 전)

| 워크로드 | CPU request | Memory request = limit |
|---|---:|---:|
| auth-api | 250m | 768Mi |
| member-api | 250m | 768Mi |
| youtube-api | 250m | 768Mi |
| wishlist-api | 300m | 1Gi |
| chat-api | 300m | 1Gi |
| recommend-api | 300m | 1Gi |
| ai-api | 200m | 512Mi |
| youtube-analysis-worker | 500m | 1Gi |
| redis | 200m | 1Gi |
| web | 미정 | 미정 |

- CPU Limit: 처음에는 통일 적용하지 않음 (throttling/JVM 시작 지연을 우려, 추후 관측).
- Memory Request = Limit: 노드 Memory 오버커밋을 억제하려는 선택이며 비용·집적률 트레이드오프가 있음.
- JVM: `-XX:MaxRAMPercentage=70~75` 가정, native memory 고려. 적용 여부 앱 팀과 확인.
- RDS 연결 예산: `Σ(MaxReplica × HikariCP maximumPoolSize) + 롤링 배포 maxSurge와 운영 여유 ≤ RDS max_connections`를 검증한다. 실제 풀 크기·RDS 사양 미정.
- 실제 CPU/Memory/GC/OOM/Throttling·HPA 지표로 조정한다.

### 5.3 Probe와 정상 종료

- Spring Boot API: Startup + Readiness + Liveness; Actuator 경로 `/actuator/health/liveness`, `/actuator/health/readiness` 설계. 실제 포트·헬스 경로 확인 필수.
- FastAPI: `/health/live`, `/health/ready` 설계. 실제 구현 확인 필수.
- Worker: Service로 트래픽을 받지 않으므로 Readiness 일반적으로 불필요, Liveness/Heartbeat와 Startup 필요.
- Liveness는 외부 SQS/RDS/LLM 일시 장애 때문에 실패하도록 만들지 않음; 무한 재시작 방지.
- HTTP 서비스: `preStop` 지연 + 애플리케이션 SIGTERM 정리 + `terminationGracePeriodSeconds`.
- SSE: 재연결 유도, 연결 종료 및 Redis/RDS 상태 복구; ALB idle timeout과 Heartbeat 맞춤.
- Worker: SIGTERM 시 새 SQS 수신 중지 → 완료 Job 저장/삭제 → 미완료 메시지 보존·Visibility Timeout 후 재처리. 멱등성은 백엔드 코드 구현 필요.
- Spot 중단 경고는 짧으므로 긴 작업은 재시도 전략 필수.

### 5.4 Replica / HPA / KEDA

| 서비스 | 설계 minReplica | 스케일러/지표 |
|---|---:|---|
| auth-api | 2 | HPA CPU |
| member-api | 2 | HPA CPU |
| youtube-api | 1~2 | HPA CPU |
| youtube-analysis-worker | 0 | KEDA SQS 큐 메시지 수 |
| wishlist-api | 2 | HPA CPU |
| chat-api | 2 | KEDA SSE 활성 연결 수 |
| recommend-api | 2 | KEDA SSE 활성 연결 수 |
| ai-api | 2 | KEDA In-flight 요청 수 |
| web | 미정 | 미정 |

- 최대 Replica는 RDS 커넥션·외부 AI API Rate Limit·부하 테스트·비용 상한을 보고 확정.
- HPA CPU 목표치, stabilization, KEDA polling/cooldown/queueLength 등 숫자는 미정 또는 가정.
- KEDA 생성 HPA와 별도 HPA 중복 금지.
- Worker 0→N Cold Start는 KEDA polling + Node 생성 + Image Pull + Spring Boot 시작/Startup Probe를 포함.
- SSE Scale-out 후 기존 연결은 자동 이동하지 않음. Scale-in 시 재연결 필요.
- AI API는 CPU보다 In-flight 지표 우선 고려; 공급자 Rate Limit 전역 제한 준수.

### 5.5 RollingUpdate / PDB / Scheduling

- 핵심 API RollingUpdate `maxUnavailable: 0`, `maxSurge: 1`; 새 Pod Ready 후 기존 Pod 종료.
- 핵심 API PDB `maxUnavailable: 1` 설계. PDB는 *자발적 축출*에 적용되며 RollingUpdate 중 무중단 자체를 보장하지 않는다.
- Worker는 PDB 미적용(멱등 재시도), Redis는 Primary/Replica를 고려하여 정책 설계.
- Application NodePool은 On-Demand + 보수적인 Consolidation; Worker NodePool은 Spot 우선 + 공격적 Consolidation.
- Worker NodePool에 Taint; Worker에 **toleration과 nodeSelector/affinity를 함께** 지정해야 Worker가 Application Node에 잘못 배치되지 않는다.
- 핵심 API는 TopologySpreadConstraints/AntiAffinity로 Node·AZ 분산, 고정 Replica 2개에서 엄격한 제약 사용 시 Pending 위험과 Node 증가 검토.
- ResourceQuota는 `maxReplicas`와 `maxSurge`까지 고려하여 확장을 막지 않게 산정.
- 실제 `NodePool`, `EC2NodeClass`, PriorityClass, Taint 값은 A와 계약 필요.

### 5.6 검증할 대표 시나리오

- GitOps 배포·롤백 중 5xx 증가 여부와 복구 시간
- API Pod 종료 / Readiness 실패 / ImagePull 실패 / OOM 및 Pod 재생성
- KEDA SQS 큐 급증 → Worker 0→N, 대기 시간·메시지 유실·중복 반영
- AI API에 배치 처리 집중 → 채팅/추천 p95 유지 여부
- SSE Pod 교체/Scale-in → 클라이언트 재연결·상태 복구
- HPA Burst → Pod 확장 / Karpenter Node 확장 / Pending 해소
- Node Spot 회수, Fallback, Consolidation, AZ 장애(A가 인프라 실험 주도, B가 앱 영향 측정)
- RDS 커넥션 한도, Kubernetes API 권한 거부/허용, ExternalSecret 주입 및 비밀 노출 방지

---

## 6. B 담당 전체 WBS (21개, 설계·구현·검증 구분)

**표기:** `독립` = A의 EKS 없어도 설계/로컬 테스트 가능, `일부` = A의 계약값 필요, `필수` = AWS/EKS 실환경 필요. 수행 완료 여부는 **기본적으로 미확인/미착수**로 두고 코드·로그·PR 증빙이 있을 때만 갱신.

| 순서 | B 작업 | A 의존 | 요구 산출물·완료 검증 |
|---:|---|---|---|
| 01 | A·개발팀 배포 계약 정리 | 일부 | Namespace/포트/이미지/헬스/Secret/메트릭·NodePool 계약표 |
| 02 | Cloud Repo 폴더 및 dev/prod 구조 | 독립 | 코드 구조, 환경별 정책 |
| 03 | API/Worker/Web Helm Chart 구조 선정 | 독립 | Chart 구성·Values 스키마 |
| 04 | Deployment / Service / ConfigMap | 독립 | Helm Template 렌더링 |
| 05 | 6개 Namespace / RBAC / Quota / LimitRange | 독립 | YAML 및 `kubectl auth can-i` 테스트 |
| 06 | ServiceAccount / 비밀 연동 설계 | 일부 | 계정·ExternalSecret 템플릿 |
| 07 | Probe / Requests / Limits / RollingUpdate | 독립 | Manifest + 앱 시작/종료 테스트 |
| 08 | kind 로컬 배포 검증 | 독립 | API 2개 Helm 배포 및 통신 |
| 09 | Argo CD / AppProject / Application | 로컬은 독립 | 로컬 Git 변경 Sync 검증 |
| 10 | GitHub Actions → Cloud Repo → Argo CD | 일부 | ECR 태그 PR → 승인 → Argo CD 반영 정책 |
| 11 | dev EKS 최초 통합 배포 | 필수 | Image Pull, Pod Ready, Service 정상 |
| 12 | HTTPRoute / Gateway 연결 및 외부 접근 | 필수 | 외부 HTTPS·SSE 라우팅 |
| 13 | Affinity / TopologySpread / PDB | 일부 | NodePool 배치 및 교체 검증 |
| 14 | HPA 일반 API | 일부 | CPU 부하 → Replica 확장 |
| 15 | KEDA SQS Worker | 필수 | SQS 0→N→0, 재시도·상한 검증 |
| 16 | KEDA SSE / AI 사용자 정의 지표 | 일부 | 실제 메트릭 기반 확장 (개발팀 협업) |
| 17 | Graceful Shutdown / SSE 재연결 | 일부 | 드레인/Scale-in 실측 (개발팀 협업) |
| 18 | Application Metrics / Dashboard / Alert | 일부 | 앱별 Grafana 및 알림 |
| 19 | 부하 / Pod 장애 / 배포 롤백 | 필수 | RPS·p95/p99·5xx·복구 지표 |
| 20 | dev→prod 배포·ECS/EKS 전환 검증 | 필수 | 환경별 Values, DB/세션 호환, Rollback |
| 21 | 운영 문서 / 개선 / 포트폴리오 증빙 | 일부 | Runbook, 실험 전후 수치, PR 링크 |

**중복 제거:** 초기 대화에 있던 '1순위 Helm Chart'와 '2순위 Kubernetes 운영 정책 작성'은 **별도의 정책 재설계가 아니라 하나의 구현 흐름**으로 합쳐야 한다. 5-2·5-3의 정책을 Helm Values 및 YAML로 코드화하고, 아직 빈 값만 선택·검증한다.

### A를 기다리지 않고 가장 먼저 할 수 있는 것

1. 5-2·5-3에 정의된 정책값을 표로 추출하고 `확정/초기 가설/미정`으로 분리.
2. Cloud Repo B 담당 디렉터리(`charts`, `values`, `argocd`, `platform`) 정리.
3. **RBAC 정책 및 YAML 정리, kind에서 권한 허용·거부 테스트.**
4. API/Worker/Web Chart 경계 및 Values 스키마 확정.
5. `helm lint`, `helm template`, `kind`로 Mock API 2개 배포.
6. ConfigMap·Probe·Resources·ServiceAccount, 기본 RollingUpdate/PDB를 Chart에 연결.
7. Argo CD를 kind에 설치하고 Git 변경에 따른 Sync 실습.
8. HPA/KEDA·HTTPRoute/ExternalSecret은 인터페이스를 Mock 처리해 Manifest 초안 작성. 실제 AWS 작동 검증은 dev EKS 준비 후 수행.

---

## 7. Helm 구축 방향 — 현재까지 합의한 실행 전략

### 7.1 Chart 구성

**추천안, 아직 구현·최종 승인 아님:**

- `charts/api`: Spring Boot HTTP API 6개 + FastAPI 1개(+SSE 특성은 서비스별 Values로 분기)에서 공통되는 Deployment, Service, ServiceAccount, Probe, Resources 등 재사용.
- `charts/worker`: SQS Worker용 (기본 HTTP Service/HTTPRoute 불필요, KEDA/종료 처리 특화).
- `charts/web`: Next.js 특화 (포트·Health·리소스·정적 자산/SSR 방식 등 확인).
- `values/dev/`와 `values/prod/`에서 이미지/Tag·Replica·포트·환경설정/스케일링 차이 분리.
- 초기 Chart에는 Deployment, Service, ServiceAccount, Container Port, Config/Secret 참조, Resources, Probe까지만 구현하고 고급 HPA/KEDA/PDB/HTTPRoute/ExternalSecret은 순차 추가. **단, 나중에 해당 기능들을 넣을 Values 스키마는 미리 고려.**

### 7.2 추천 Repository 구조

```text
cloud-repository/
├── terraform/                # A 소유
├── charts/                   # B 소유
│   ├── api/
│   ├── worker/
│   └── web/
├── values/                   # B 소유
│   ├── dev/
│   │   ├── auth-api.yaml
│   │   ├── member-api.yaml
│   │   ├── youtube-api.yaml
│   │   ├── wishlist-api.yaml
│   │   ├── chat-api.yaml
│   │   ├── recommend-api.yaml
│   │   ├── ai-api.yaml
│   │   ├── worker.yaml
│   │   └── web.yaml
│   └── prod/
├── platform/                 # Namespace, RBAC, Quota, LimitRange, 관련 앱 정책
│   ├── namespaces/
│   ├── rbac/
│   └── quotas/
├── argocd/
│   ├── bootstrap/
│   ├── projects/
│   └── applications/
└── .github/workflows/
    ├── infrastructure.yml   # A
    └── deployment.yml       # B
```

실제 기존 Repo 디렉터리·브랜치 규칙은 미확인. **존재하지 않는 파일/디렉터리를 이미 생성됐다고 표현하지 말 것.**

### 7.3 Helm 첫 마일스톤

동일한 `api` Chart로 서로 다른 Values를 가진 HTTP API **2개**를 배포할 것. 실제 도메인 이미지가 미제공이라면 *Mock API 2개*로 시작. 실제 `auth-api`는 OAuth/DB/Secret 복잡도가 있으므로 Mock → 단순 실제 API 순서 권장.

**통과 기준**

- `helm lint`와 `helm template` 성공
- kind에서 Pod Ready
- 서비스별 Service DNS 및 HTTP 내부 연결 성공
- Readiness/Liveness 검사, Pod 삭제 후 재생성 검증
- 서비스별 Values 변경만으로 Chart 재사용

**아직 필요한 입력:** 실제 Backend Dockerfile, Docker Compose, 포트, Health Endpoint, 서비스 분리/이미지 현황, 환경변수·Secret 목록. 첫 Mock 구현 시에는 필수 아님.

---

## 8. Argo CD vs Flux — 이미 내린 결정

**Argo CD 선택**. 이유:

1. 개발팀·AI팀이 Kubernetes CLI 사용 없이 Web UI로 Application별 배포 버전·Health/Sync 상태를 읽기 전용 확인 가능.
2. 여러 Deployment와 플랫폼 컴포넌트를 Application 단위로 나눠 장애 위치 식별에 유리.
3. Git 상태와 실제 클러스터의 Diff·Sync 상태를 확인하면서 단계적 구축·승인 운영에 적합.

Flux는 UI가 기본 제공되지 않고 HelmRelease 컨트롤러를 통해 Helm Release를 관리하는 방식이다. Argo CD의 Helm 소스는 보통 Helm을 **Manifest 템플릿 도구**로 사용하므로 Helm 릴리스 기록이 생성되지 않는 차이가 있다. 이 차이 때문에 `helm rollback`이 GitOps 운영에서 주된 복구 수단은 아니다.

**권장 CD 흐름:**

```text
각 Application Repo:
PR 검증 → Merge → Build/Test → Image Build → ECR Push (SHA/Digest 기반)
                                 ↓
Cloud Repo: image reference 변경 PR → 리뷰·승인 → Merge
                                 ↓
Argo CD: Git 내용 감지 / (운영 정책에 따른 Sync) → EKS 배포
                                 ↓
Readiness 검증, 모니터링, 실패시 Git Revert 및 재Sync
```

결정 필요: Manual vs Automated Sync (초기 Manual 권장), Application vs ApplicationSet (초기 개별 App 권장), AppProject 경계, Image Tag SHA/Digest, 운영 승인 주체, 프로덕션 Rollback 절차. DB Migration은 이미지만 롤백해 해결되지 않으므로 호환성 정책 별도 필요.

---

## 9. RBAC — 이 세션에서 가장 최근 작성한 정책과 YAML 초안

### 9.1 의도와 범위

기존 5-2는 `platform-operator`, `service-observer`, `application-deployer`를 구분하고, 6개 Namespace에 팀 권한을 분리한다고 정의했다. 세션 마지막에 이를 **구현 가능한 수준으로 보완**했다.

- Cloud(A/B): 플랫폼 공통 설정 관리, 클러스터 Access/Bootstrap은 제한적 관리자 경로.
- Fullstack: `account`, `ingest`, `content`, `recommend`, `frontend`의 **읽기 전용** 조회.
- AI: `ai`의 **읽기 전용** 조회.
- Argo CD: 승인된 앱 리소스 배포. **Argo CD UI 사용자 권한, AppProject 정책, Argo CD Controller의 실제 K8s RBAC는 다른 층위**다.
- 앱 Pod: 일반적으로 K8s API Role 불필요, AWS SQS/Secrets 접근은 **EKS Pod Identity/IAM**으로 분리.
- Kubernetes RBAC는 API 작업에 대한 것이며, 네트워크 통신 제약은 NetworkPolicy, AWS 권한은 IAM에서 처리.

**초안으로 사용한 Kubernetes Group 이름(확정 아님):**

- `keepgo:fullstack-observers`
- `keepgo:ai-observers`

A의 EKS Access Entry `kubernetesGroups`와 일치시켜야 한다. 그룹 이름·실제 IAM Role ARN은 A에게 확인.

### 9.2 역할/권한 매트릭스

| 역할 | 대상 | 허용 | 금지/주의 |
|---|---|---|---|
| `service-observer` | 담당 NS Pod/Deployment/Service/Event/HPA/Pod Log | `get/list/watch` (로그 `get`) | Secret 열람, Pod exec/attach, Deployment 수정·삭제, 권한 변경 금지 |
| `platform-operator` | 공통 리소스 | 승인된 변경 | 일상 운영에 `cluster-admin` 광범위 상시 부여 지양 |
| `application-deployer` | 지정 NS 앱 리소스 | 배포 관련 `get/list/watch/create/update/patch/delete` | ClusterRole/Namespace/CRD 등 공통 인프라 임의 변경 금지 |
| `application-runtime` | 특정 Pod | 필요한 것만 | API 호출 없는 앱은 K8s RBAC 미부여 |

**주의:** `ConfigMap` 조회는 민감 정보가 포함되지 않는다는 전제 하에만 허용. Log에도 사용자 토큰·비밀이 찍히지 않게 개발팀과 협의한다. RBAC는 가산적인 권한 모델이므로 EKS Access Policy나 다른 Binding에서 넓은 권한이 추가되면 예상보다 큰 권한을 가질 수 있다.

### 9.3 `service-observer` ClusterRole 초안

이 YAML은 **앞선 어시스턴트가 제안한 예시**이다. 승인·적용 완료 상태는 아니다.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: keepgo-service-observer
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "endpoints", "configmaps", "persistentvolumeclaims"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["events.k8s.io"]
    resources: ["events"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["get", "list", "watch"]
```

**개선 검토:** 실무의 서비스 상태 조회에 필요한 `endpointslices.discovery.k8s.io`, KEDA `scaledobjects.keda.sh`, Gateway API `httproutes.gateway.networking.k8s.io` 조회 권한 추가 여부, `configmaps` 및 `persistentvolumeclaims` 조회 필요성 검토. 불필요한 권한은 줄인다.

### 9.4 RoleBinding 초안

```yaml
# 풀스택팀: account Namespace 읽기
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: keepgo-service-observer
  namespace: account
subjects:
  - kind: Group
    name: keepgo:fullstack-observers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: keepgo-service-observer
  apiGroup: rbac.authorization.k8s.io
---
# AI팀: ai Namespace 읽기
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: keepgo-service-observer
  namespace: ai
subjects:
  - kind: Group
    name: keepgo:ai-observers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: keepgo-service-observer
  apiGroup: rbac.authorization.k8s.io
```

Fullstack용 Binding을 `ingest`, `content`, `recommend`, `frontend`에 추가한다. ClusterRole은 전역으로 정의되더라도 **RoleBinding은 바인딩한 Namespace 범위**에 역할을 적용한다. ClusterRoleBinding으로 실수로 전역 읽기 권한을 열지 않는다.

### 9.5 일반 앱 배포용 Role 초안

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: keepgo-application-deployer
  namespace: account
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["services", "configmaps"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["gateway.networking.k8s.io"]
    resources: ["httproutes"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

**반드시 확인할 점:**

- 위 Role은 **배포용 최소 예시**이지 Argo CD 설치/운영에 필요한 완전한 실제 Controller 권한이 아니다.
- Argo CD가 클러스터 관리 권한으로 설치되면 AppProject만 설정해도 Kubernetes API 수준의 권한이 축소되는 것은 아니다. Helm 설치 Chart의 RBAC/Controller ServiceAccount를 확인하고 권한 경계를 설계한다.
- `ServiceAccount`, `Secret`, `ExternalSecret`, `Namespace`, `CRD`, `Role/Binding` 등 관리 소유권 및 Argo CD의 실제 적용 방식을 별도 확정한다.
- Argo CD는 Release별로 기본 서비스 계정 및 권한이 다를 수 있다. RoleBinding이 실제 어떤 ServiceAccount에 붙어야 하는지는 설치 후 검증한다.
- Cloud 팀의 일상 Sync 권한과 관리자 Bootstrap/DR 권한을 나눌지 검토한다.
- Argo CD UI에서 개발팀에 읽기 권한을 주려면 **Argo CD 자체 RBAC `policy.csv`/SSO 등 별도 작업** 필요.

### 9.6 `kubectl auth can-i` 권한 검증 명령

```bash
# 테스트는 Impersonation 권한이 있는 관리자 컨텍스트에서 시행
kubectl auth can-i get pods -n account \
  --as=rbac-test-user --as-group=keepgo:fullstack-observers
# 예상 yes

kubectl auth can-i patch deployments -n account \
  --as=rbac-test-user --as-group=keepgo:fullstack-observers
# 예상 no

kubectl auth can-i get secrets -n account \
  --as=rbac-test-user --as-group=keepgo:fullstack-observers
# 예상 no

kubectl auth can-i get pods -n account \
  --as=rbac-test-user --as-group=keepgo:ai-observers
# 예상 no

kubectl auth can-i get pods -n ai \
  --as=rbac-test-user --as-group=keepgo:ai-observers
# 예상 yes
```

추가 보완 검증: `pods/exec`, `pods/attach`, `secrets list`, `rolebindings create`, `deployments delete`의 거부, `get pods/log` 허용, 권한이 없는 Namespace 교차 접근 거부. `kubectl auth can-i` 결과는 다른 Access Policy/Binding 존재 여부에 따라 달라진다.

### 9.7 RBAC 남은 구현·검증 작업

1. 6개 Namespace 목록과 실제 그룹/주체 확정.
2. `keepgo-service-observer` ClusterRole / RoleBinding 매니페스트 작성.
3. Argo CD UI RBAC / AppProject / Kubernetes Controller RBAC **각각** 구분하여 정의.
4. A에게 `Access Entry IAM Role → Kubernetes Group` 계약 수령.
5. 로컬 kind에서 허용·거부 Impersonation 검증 후 dev EKS에서 실제 주체 테스트.
6. Git 저장/PR 코드 리뷰. RBAC·Secret·NetworkPolicy를 혼동하지 않는다.

---

## 10. 추가로 확인해야 할 모호함/충돌/리스크

### A. V3 문서 간 표현 차이

- **Gateway:** 5-2 최종 선택은 `Gateway API + AWS Load Balancer Controller`, 일부 5-3 표기에는 Ingress/ALB가 남아 있음. 구현용 인터페이스는 GatewayClass / Gateway / HTTPRoute를 우선 확인.
- **DBMS:** V3 5-3에는 `Amazon RDS MySQL`이라고 쓰여 있다. 이전 문서가 다른 DBMS를 사용했더라도 자동으로 수정하지 않는다. Backend 팀의 실제 운영 DBMS와 확정 필요.
- **AI:** ai-api는 외부 AI를 호출하는 FastAPI 서비스. 일부 5-2 설명 중 '모델 적재·CPU 추론' 표현은 실제 실행 방식과 재확인.
- **Pod IP:** Prefix Delegation 이론상 수용 IP 총량과 실제 노드당 Pod 수/Prefix Fragmentation이 같지 않음.
- **Redis:** V3 설계는 StatefulSet이지만 dev/prod 실제 데이터 이전 및 Sentinel/Failover 방식은 구현되지 않았을 수 있음.
- **SSE/KEDA:** 사용자 정의 지표와 앱 코드가 준비되어야 동작. 메트릭 지표가 있다고 가정하지 않는다.

### B. 비용과 장애 트레이드오프

- dev NAT 1개는 비용을 줄이지만 NAT AZ 단일 장애점을 감수.
- NodePool 분리로 비용·노드 자원 파편화 가능.
- Spot 기반 Worker는 재시도·멱등 작업·DLQ 설계 필수.
- Redis EBS 볼륨은 AZ 고정, Failover/복구가 Replica 자동 생성과 동일하지 않음.
- Min Replicas 2와 엄격한 AZ 분산은 비용·스케줄러 제약 증가.
- V3 트래픽 목표를 만족한다고 단정하지 말 것; 실제 부하 측정 필요.

### C. 외부 팀에 의존하는 필수 구현

| 요청 대상 | 확인 사항 |
|---|---|
| Backend | 서비스별 실제 이미지/엔트리포인트/포트, Actuator, SIGTERM/Graceful Shutdown, Worker 멱등성 및 SQS 삭제·재시도, HikariCP 설정, SSE 재연결 |
| AI | FastAPI Health Endpoint, In-flight Metric, 외부 AI Rate Limit, 사용자/배치 격리 |
| Frontend | Next.js 포트/SSR/Health, SSE 클라이언트 재연결, Cookie/OAuth Callback |
| A | 클러스터/NodePool/Gateway/IAM/SQS/Prometheus·CRD 제공 계약 |

---

## 11. 권장 다음 행동 — Claude와 이어서 수행할 구체적인 순서

### 가장 가까운 1~3개 작업

**작업 1. RBAC YAML 확정 및 Git 구성**

- 이 문서 §9의 매니페스트를 최소 권한 관점에서 재검토, 필요 리소스와 실제 조직 접근 매트릭스 확정.
- `platform/rbac/`에 공통 ClusterRole + Namespace RoleBinding을 구성하고 kind에서 `kubectl auth can-i` 테스트.
- A의 EKS Access Entry 그룹 이름·Argo CD ServiceAccount 소유권은 미정으로 분리.

**작업 2. Helm Chart 뼈대와 Values 스키마 정의**

- API/Worker/Web 분리, API 공통 Deployment/Service/ServiceAccount/Probe를 작성.
- 첫 테스트는 Mock API로 수행해 실제 애플리케이션 포트·Secret 부족이 진행을 막지 않게 한다.
- `helm lint`, `helm template`, kind에서 서비스 2개 동시 배포.

**작업 3. Argo CD의 로컬 동기화까지 연결**

- AppProject/Application 구성 및 허용 Repo/Namespace를 좁히고 kind에서 Git 변경으로 Deploy/Sync 검증.
- A가 dev EKS를 준비하면 같은 Chart·Values로 통합 배포하되 Gateway/NodePool/AWS IAM은 실환경에서 다시 검증.

### 완전한 B WBS는 §6 참조

- 첫 실환경 마일스톤: ECR Image Pull → Pod Ready → Service 통신 성공.
- 다음: Gateway 외부 라우팅 → Secret/DB 연결 → Argo CD GitOps → HPA/KEDA → SSE/Worker 장애 복구 → 지표·부하 테스트 → prod 전환.

---

## 12. Claude에게 바로 붙여넣을 후속 프롬프트

> 나는 KeepGo V3의 클라우드 담당자 B다. 첨부한 인수인계 문서를 **V3 최신 기준**으로 삼아라. 5-2/5-3 설계는 이미 있으니 재설계하지 말고, 설계 확정/초안/미정/구현·검증 완료를 구분하라. A는 Terraform·EKS·Karpenter·Network·Storage를, 나는 B로서 Kubernetes RBAC·Helm·Argo CD·HPA/KEDA·애플리케이션 운영을 담당한다. **우선 §9 RBAC 정책과 YAML을 기존 5-2 RBAC 부분에 맞춰 정리하고, kind에서 검증 가능한 파일 구조와 명령을 만들어라.** 실제 Access Entry IAM Role, Application 이미지/포트, Controller ServiceAccount 등 없는 값은 placeholder로 남기고, A에게 필요한 계약은 별도 표시하라. RBAC 작업이 끝나면 §7의 공통 Helm Chart를 구현하자.

---

## 13. 근거 자료와 신뢰 수준

### 사용자가 첨부한 V3 설계 문서

1. `붙여넣은 텍스트(2).txt`: GitHub Wiki **5-2. 서비스 및 클러스터 아키텍처**의 텍스트 사본. 서비스/Namespace/RBAC/Karpenter/네트워킹/Gateway API 최종 선택이 포함됨.
2. `붙여넣은 텍스트(1)(2).txt`: GitHub Wiki **5-3. 리소스·확장·보안 정책**의 텍스트 사본. Storage, Requests/Limits, Probe, PDB, HPA/KEDA, Scheduling, NodePool, 검증 시나리오가 포함됨.
3. 사용자가 이번 세션에 직접 붙여넣은 **A 담당 확정 작업 메모**: Terraform, 신규 dev VPC CIDR·Subnet, NAT, IPv4 Prefix Delegation, dev/prod 전환 계획, Argo CD 선정 근거. 첨부 Wiki 사본보다 최근 결정으로 다룸.
4. 이번 세션에서 합의한 **A/B 역할 분담·21개 WBS·RBAC 초안**: 팀 최종 배포 및 검증 결과가 아닌 *대화상 작업 가이드와 초안*.

### GitHub Wiki 맥락

- 팀 Repository: `100-hours-a-week/KTB4-8th-CLOUD` (Wiki에 5-1~5-5 설계 문서)
- 사용자가 직접 공유한 관련 문서: `https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5‐4.-배포-자동화-및-전환-전략`
- GitHub Wiki 내용은 시점에 따라 바뀔 수 있으므로 실구현 전 업데이트된 문서/Repo가 제공되면 최신 내용을 재확인.

### 현재 완료 상태 — 절대 과장 금지

| 항목 | 현재 인수인계 가능한 사실 |
|---|---|
| 5-2 / 5-3 아키텍처·운영 정책 | 설계 문서 작성됨, 일부 값 미확정 |
| A/B 역할 분담 | 대화에서 채택 |
| A dev VPC / 네트워크 | 주요 설계 선택이 제공됨, 실제 Terraform Apply 완료 미확인 |
| Argo CD 선택 | 도구 선정됨, 설치 완료 미확인 |
| RBAC | 정책 문안·YAML 예시 작성됨, Git 반영·클러스터 적용·테스트 미확인 |
| Helm Chart | 구조 제안됨, Chart 구현 확인 안 됨 |
| kind / EKS 배포 | 수행 증빙 없음 |
| GitOps / HPA / KEDA / 모니터링 | 적용·검증 증빙 없음 |

**최종 메시지:** KeepGo V3의 플랫폼 방향은 이미 설계돼 있다. B가 해야 할 일은 정책을 또 설계하는 것이 아니라 **구체적인 Kubernetes 코드로 구현하고, 로컬 및 dev EKS에서 동작을 증명하며, 운영·확장·장애 복구를 지표로 검증하는 것**이다.
