> **위키 사본(스냅샷)** — 원본: [5단계.-Kubernetes-기반-운영-플랫폼-설계](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%EB%8B%A8%EA%B3%84.-Kubernetes-%EA%B8%B0%EB%B0%98-%EC%9A%B4%EC%98%81-%ED%94%8C%EB%9E%AB%ED%8F%BC-%EC%84%A4%EA%B3%84)  
> 기준: 위키 커밋 `addfeea`(2026-11-04), 복사 2026-11-09. **수정은 위키에서 하고, 바뀌면 이 사본을 다시 복사한다.**

<aside>
💡

### 5단계의 목적

#### 1. 서비스와 조직이 얼마나 성장했는지 가정하기

트래픽이 늘었다는 설명에 더해, 운영 방식이 어떻게 복잡해졌는지 정합니다.

- 팀이 몇 개로 늘었는가?
- 각 팀이 관리하는 애플리케이션과 레포지토리는 몇 개인가?
- 팀마다 배포 주기가 얼마나 다른가?
- API 서버, 비동기 작업 등 워크로드별 자원 요구가 어떻게 다른가?

이 가정이 이후 선택의 근거가 됩니다. 단순히 “규모가 커졌다”에서 끝내지 않는 것이 중요합니다.

#### 2. 기존 플랫폼으로 해결하기 어려운 문제 찾기

예를 들어 팀별 독립 배포, 자원 분리, 워크로드별 확장, 배포 방식 표준화 등이 필요한지 살펴봅니다.

여기서 해야 할 일은 “필요한 기능 나열”과 함께 “현재 ECS에서도 해결할 수 있는지 비교”하는 것입니다. 트래픽 증가만으로 Kubernetes 도입을 결정하면 근거가 부족합니다.

#### 3. ECS 유지 또는 Kubernetes 도입 결정하기

kubernetes를 도입했을 때 얻는 이점이 학습·관리·장애 대응 비용보다 큰지 판단합니다.

- ECS로 요구사항을 충분히 해결할 수 있다면 → ECS 유지
- Kubernetes 기능을 실제로 활용하고 운영 부담도 감당할 수 있다면 → 도입

ECS 유지도 정당한 결론입니다. 이 경우에는 요구사항을 ECS에서 어떻게 충족할지 설명하면 됩니다.

#### 4. 도입한다면, 도구와 아키텍처 정하기

EKS와 kubeadm 등을 비교하고 우리 팀에 맞게 선택을 합니다. 비교할 핵심은 “누가 무엇을 운영하고 책임지는 가?”입니다.

이후 다음 질문에 답할 정도로 아키텍처를 구체화합니다.

| Cluster / Node | 애플리케이션을 어떤 실행 환경에 배치할 것인가? |
| --- | --- |
| Namespace | 팀이나 서비스의 운영 범위를 어떻게 구분할 것인가? |
| Deployment / Replica | 각 애플리케이션을 몇 개 실행하고 어떻게 교체할 것인가? |
| Service / Gatewya / Ingress | 사용자 요청이 어떤 경로로 애플리케이션에 도달하는가? |
| ConfigMap / Secret / Storage | 설정, 비밀정보, 영속 데이터를 어떻게 관리할 것인가? |
| Requests / Limit / Scheduling | 자원을 얼마나 배정하고 어떤 노드에서 실행할 것인가? |
| Probe | 애플리케이션이 정상이며 요청을 받을 준비가 됐는지 어떻게 확인할것인가? |

#### 5. 배포 과정과 실패했을 때의 동작 정하기

코드 변경부터 운영 반영까지의 흐름을 설명합니다.

예 : GitHub Actions → ECR → Helm Values 변경 → Argo CD → EKS

도구 이름만 연결하지 말고, 배포 승인·환경별 설정·배포 성공 확인·롤백 방법까지 정합니다.

장애 시나리오는 아래 세 질문으로 정리하면 이해하기 쉽습니다.

- 무엇으로 감지하는가?
- 시스템이 자동으로 무엇을 하는가?
- 자동 복구가 안 되면 운영자가 무엇을 하는가?

이를 Pod 장애, Node 장애, 배포 실패, Readiness 실패, Image Pull 실패, 자원 부족과 Pending 상황에 적용하면 됩니다.

#### 6. 도입으로 추가되는 비용과 복잡성까지 설명하기

인프라 비용뿐 아니라 업그레이드, 보안 설정, 모니터링, 배포 도구 관리, 팀의 학습과 장애 대응 부담도 함께 검토합니다.

“좋아지는 점”과 “그 대가로 새롭게 책임져야 하는 일”을 함께 설명해야 설득력이 있습니다.

문서는 1 - 성장 가정, 2- 운영 문제, 3 - 플랫폼 비교와 결정, 4-아키텍처, 5-배포·장애 대응, 6-비용과 복잡성

</aside>

### 1. Kubernetes 도입 조건: 조직과 운영 문제가 얼마나 커졌는가?

> 현재 KeepGo는 MAU 300만 규모로 성장했다. 기능별 서비스가 각각 조직 단위로 커지면서 서비스마다 담당 팀이 생겼고, 팀별 인원도 늘었습니다. 이에 따라 서비스를 팀 단위로 나눠 독립적으로 개발·배포하는 MSA 구조로 전환하기로 했습니다.
>

<h4>1.1 트래픽 성장 [가정]</h4>

변수 | 평시 | 이벤트 발생
-- | -- | --
MAU | 3,000,000 | 3,000,000
DAU/MAU | 15% | 30%
DAU | 450,000 | 900,000
일일 트래픽 배수 | 1배 | 2배
일일 세션 수 | 450,000 | 1,800,000
Peak Hour 비율 | 20% | 40%
Peak Hour 세션 수 | 90,000 | 720,000
평균 이용시간 | 10분 | 10분
Peak Hour 평균 동시 사용자 | 15,000 | 120,000
순간 집중계수 | 2배 | 2배
Burst 동시 사용자 | 30,000 | 240,000
세션당 Backend 요청 | 8회 | 8회
일일 평균 RPS | 42 | 167
Peak Hour 평균 RPS | 200 | 1,600
Burst RPS | 400 | 3,200

### 1.2. 조직 및 애플리케이션 구조 변화 [가정]

서비스별 전담 조직이 구성되면서 개발팀 4개와 플랫폼 운영팀 1개로 조직이 확대되었다고 가정합니다.

| 담당 팀 | 주요 서비스 | 워크로드 특성 |
| --- | --- | --- |
| 계정·연동 | 인증 API, YouTube Sync API | HTTP 요청 중심 |
| 콘텐츠·보관함 | 콘텐츠 API, 장소·이벤트 API | DB 조회 및 저장 중심 |
| 추천·AI | 추천 API, AI FastAPI | 외부 AI 호출 및 응답 지연 |
| 비동기 처리 | 분석 Worker, 알림 Worker | Queue 기반 비동기 처리 |
| 플랫폼 운영 | 공통 인프라 및 배포 플랫폼 | 인프라·보안·배포 관리 |
- 애플리케이션별 Repository를 분리하여 총 8개 내외의 서비스 Repository 운영
- 팀별로 주 1~5회 등 서로 다른 배포 주기 운영
- 각 팀이 담당 서비스를 독립적으로 개발·배포
- API와 Worker의 부하 특성에 따라 개별적인 자원 할당 및 확장 필요

### 1.3. 운영 환경에서 발생하는 문제

기존 ECS 기반 구조에서도 서비스별 독립 배포와 Auto Scaling이 가능하지만, 조직과 서비스가 증가하면서 다음과 같은 운영 요구사항이 발생하였습니다.

1. **운영 표준화:** 팀마다 다른 배포 설정과 운영 정책을 통일할 필요
2. **Resource 관리:** API, AI, Worker별 자원 할당과 실행 위치를 세밀하게 제어할 필요
3. **독립적 확장:** API는 요청량, Worker는 Queue 적체량을 기준으로 각각 확장할 필요
4. **배포 관리:** 다수 Repository의 배포 설정을 GitOps 기반으로 일관되게 관리할 필요
5. **권한 분리:** 팀별 운영 권한과 리소스 접근 범위를 구분할 필요

### 1.4. ECS 유지와 Kubernetes 도입 검토

ECS에서도 독립 배포, 자원 할당, Auto Scaling 등의 핵심 기능을 제공하므로 MSA 전환 자체가 Kubernetes 도입의 필수 조건은 아닙니다.

그러나 KeepGo는 팀별 운영 범위를 Namespace와 RBAC으로 구분하고, Helm과 GitOps를 통해 여러 서비스의 배포 및 운영 정책을 표준화하는 방향을 선택하였습니다.

따라서 단순한 처리량 증가보다 **다수의 팀과 서비스를 일관된 방식으로 운영하기 위한 공통 플랫폼 구축**을 주요 도입 근거로 판단하였습니다.

---

## 2. Kubernetes 도구 비교 및 선택

### 2.1. EKS vs kubeadm 비교

| 비교 항목 | Amazon EKS | kubeadm |
| --- | --- | --- |
| Control Plane | AWS 관리 | 직접 구축·관리 |
| Cluster Upgrade | AWS 관리형 업그레이드 지원 | 직접 수행 |
| Node 관리 | Managed Node Group 지원 | 직접 구축·관리 |
| IAM 연동 | AWS 통합 기능 제공 | 별도 구성 필요 |
| Load Balancer / Storage | AWS Controller·CSI Driver 활용 | 별도 연동 및 관리 필요 |
| 장애 대응 | Control Plane 관리 AWS 담당 | 전체 Cluster 운영팀 담당 |
| 비용 | Cluster 요금 + 인프라 비용 | 인프라 비용 + 직접 운영 부담 |
| 운영 난이도 | 상대적으로 낮음 | 상대적으로 높음 |

※ EKS를 사용하더라도 Kubernetes 버전 업그레이드 계획, Worker Node, Add-on, 네트워크 및 보안 정책은 운영팀의 관리가 필요합니다.

### 2.2. 최종 선택: Amazon EKS

KeepGo는 **Amazon EKS + Managed Node Group**을 선택하였습니다.

**선택 근거**

- **운영 부담 감소:** Control Plane의 가용성 및 기반 인프라 관리를 AWS에 위임
- **기존 AWS 환경 활용:** ECR, IAM, ALB, RDS 등 기존 서비스와 연동
- **운영 표준화:** Kubernetes 표준 리소스를 기반으로 팀별 운영 정책 통일
- **확장성:** API와 Worker를 독립적으로 배치하고 워크로드 특성에 따라 확장
- **배포 자동화:** Helm과 Argo CD를 활용한 GitOps 운영 환경 구축

**Trade-off**

- EKS Cluster 운영에 따른 추가 비용 발생
- Kubernetes 및 관련 Add-on의 학습·운영 부담 증가
- Node 관리, 네트워크, 보안 설정, 모니터링 등 추가 운영 책임 발생

**최종 판단**

kubeadm은 직접적인 Cluster 제어와 비용 구성의 유연성이 있지만, Control Plane과 etcd의 고가용성 및 장애 복구까지 직접 관리해야 합니다.

KeepGo는 다수의 서비스와 개발 조직을 지원하는 운영 플랫폼 구축이 우선이므로, Control Plane 관리 부담을 줄이고 애플리케이션 운영 자동화에 집중할 수 있는 Amazon EKS가 적합하다고 판단하였습니다.

## 3. Kubernetes Architecture 설계

### 3.1. 아키텍처 설계 방향

KeepGo는 MSA 전환으로 서비스별 개발·배포 주기가 달라졌으며, API 서버와 비동기 Worker의 부하 특성도 서로 다릅니다.

따라서 단순히 기존 ECS 서비스를 EKS로 이전하는 것이 아니라, **팀별 독립적인 운영과 워크로드별 자원 관리가 가능한 Kubernetes 플랫폼**을 설계합니다.

주요 설계 방향은 다음과 같습니다.

- **서비스 독립성:** Namespace를 이용한 팀별 운영 범위 및 권한 분리
- **자원 격리:** API와 Worker의 실행 환경을 분리하여 자원 경합 최소화
- **독립적 확장:** 서비스별 부하 특성에 맞는 Auto Scaling 적용
- **가용성:** 여러 AZ에 Pod를 분산하고 장애 시 자동 복구
- **운영 표준화:** 공통 Kubernetes 리소스와 Helm 기반 배포 구성

### 3.2. Cluster 및 Node 구성

**Amazon EKS 단일 Production Cluster**를 구성하고, Managed Node Group을 워크로드 특성에 따라 분리합니다.

| 구성 | 설계 | 선택 근거 |
| --- | --- | --- |
| Cluster | EKS 단일 Cluster | 공통 운영 정책과 관리 지점 통합 |
| AZ | 2개 AZ | 단일 AZ 장애 영향 최소화 |
| API Node Group | 일반 API 및 AI FastAPI | 사용자 요청 처리 용량 확보 |
| Worker Node Group | 콘텐츠 분석 및 비동기 Worker | 작업 부하로 인한 API 자원 경합 방지 |
| Node Scaling | Cluster Autoscaler | Pod 배치에 필요한 Node 용량 자동 조절 |

두 Node Group은 Private Subnet에 배치하며, Node Label과 Taint/Toleration을 통해 워크로드 배치를 제어합니다.

특히 KeepGo의 콘텐츠 분석 작업은 외부 AI API 응답 지연과 다량의 분석 요청이 발생할 수 있으므로, 일반 API와 Worker의 자원을 분리합니다.

### 3.3. Kubernetes 리소스 구성

| 리소스 | 적용 방식 | 설계 근거 |
| --- | --- | --- |
| Namespace | account, content, recommend, jobs, platform | 팀별 운영 범위와 권한 분리 |
| Deployment | 서비스별 독립 Deployment | 독립 배포 및 롤링 업데이트 |
| Replica | 주요 API 기본 2개 이상 | Pod 장애 및 배포 중 처리 용량 유지 |
| Service | ClusterIP | 내부 서비스 간 통신 |
| Ingress | ALB + AWS Load Balancer Controller | 외부 요청을 API별로 라우팅 |
| ConfigMap | 서비스별 일반 환경설정 | 환경별 설정 관리 |
| Secret | AWS Secrets Manager 연동 | 인증정보 및 API Key 보호 |
| Storage | RDS PostgreSQL, S3 | 영속 데이터를 Pod 외부에 보관 |
| Requests / Limits | 서비스별 CPU·Memory 설정 | 자원 경합 및 과도한 사용 방지 |
| Probe | Startup / Readiness / Liveness | Health Check로 비정상 Pod의 트래픽 차단 및 재시작 |
| Scheduling | Node Affinity, Taint/Toleration, Topology Spread | 워크로드 분리 및 AZ 분산 |

Namespace별 RBAC과 ResourceQuota를 적용하여 팀별 접근 권한과 자원 사용 범위를 관리합니다.

단, Namespace만으로 네트워크가 격리되는 것은 아니므로 필요한 서비스 간 통신만 허용하도록 NetworkPolicy도 검토합니다.

### 3.4. Workload별 배치 및 확장 전략

KeepGo는 워크로드별 병목 원인이 다르므로 동일한 확장 정책을 적용하지 않습니다.

| Workload | 배치 | 확장 기준 |
| --- | --- | --- |
| 계정·연동 API | API Node | CPU 및 요청량 |
| 콘텐츠·보관함 API | API Node | CPU 및 요청량 |
| 추천 API | API Node | 요청량 및 응답 지연 |
| AI FastAPI | API Node | 동시 요청 및 자원 사용량 |
| 분석 Worker | Worker Node | Queue 적체량 |
| 알림 Worker | Worker Node | Queue 적체량 |
- **API:** HPA를 이용하여 트래픽에 따라 Pod 수 조절
- **Worker:** KEDA를 이용하여 Queue 적체량에 따라 Pod 수 조절
- **Node:** Cluster Autoscaler로 Pod가 요구하는 Node 용량 확보

AI 모델 추론은 외부 AI 서비스에서 수행하고, EKS에서는 AI 요청을 처리하는 FastAPI와 비동기 작업을 운영합니다.

Worker의 경우 Pod 수가 증가하더라도 외부 AI API의 Rate Limit을 초과하지 않도록 동시 처리량에 상한을 설정합니다.

## 설계 상세 문서(하위 페이지)

1. [도입 배경 및 플랫폼 선정](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%901.-%EB%8F%84%EC%9E%85-%EB%B0%B0%EA%B2%BD-%EB%B0%8F-%ED%94%8C%EB%9E%AB%ED%8F%BC-%EC%84%A0%EC%A0%95)
2. [서비스 및 클러스터 아키텍처](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%902.-%EC%84%9C%EB%B9%84%EC%8A%A4-%EB%B0%8F-%ED%81%B4%EB%9F%AC%EC%8A%A4%ED%84%B0-%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98)
3. [리소스·확장·보안 정책](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%903.-%EB%A6%AC%EC%86%8C%EC%8A%A4%C2%B7%ED%99%95%EC%9E%A5%C2%B7%EB%B3%B4%EC%95%88-%EC%A0%95%EC%B1%85)
4. [배포 자동화 및 전환 전략](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%904.-%EB%B0%B0%ED%8F%AC-%EC%9E%90%EB%8F%99%ED%99%94-%EB%B0%8F-%EC%A0%84%ED%99%98-%EC%A0%84%EB%9E%B5)
5. [관측·장애 대응 및 운영 비용](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%905.-%EA%B4%80%EC%B8%A1%C2%B7%EC%9E%A5%EC%95%A0-%EB%8C%80%EC%9D%91-%EB%B0%8F-%EC%9A%B4%EC%98%81-%EB%B9%84%EC%9A%A9)