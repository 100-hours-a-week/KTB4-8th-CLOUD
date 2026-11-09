> **위키 사본(스냅샷)** — 원본: [5‐2.-서비스-및-클러스터-아키텍처](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%902.-%EC%84%9C%EB%B9%84%EC%8A%A4-%EB%B0%8F-%ED%81%B4%EB%9F%AC%EC%8A%A4%ED%84%B0-%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98)  
> 기준: 위키 커밋 `addfeea`(2026-11-04), 복사 2026-11-09. **수정은 위키에서 하고, 바뀌면 이 사본을 다시 복사한다.**

## 1. 문서 목적 및 설계 범위

본 문서는 플랫폼 선정 결과를 바탕으로 KeepGo V3의 서비스 구성과
Kubernetes 클러스터 배치 구조를 정의한다.

인증·회원·유튜브 영상 분석·개인 보관함·채팅·추천 도메인을 기준으로
애플리케이션의 책임을 구분하고, Next.js 프런트엔드와 공통 AI API,
비동기 분석 Worker를 포함하여 실행 단위를 설계한다.

도메인, Deployment, Namespace, Node는 서로 다른 기준으로 구분한다.
Deployment는 배포와 확장 단위, Namespace는 권한과 정책의 적용 범위,
Node는 Pod가 실행되는 컴퓨팅 자원으로 사용한다.

이를 바탕으로 외부 요청의 유입 경로, 내부 서비스 간 호출,
비동기 작업 흐름 및 영속 데이터의 저장 위치를 구체화한다.

이 문서는 플랫폼 선정 결과를 바탕으로 KeepGo V3의 서비스 구성과 

### 이 문서에서 결정할 사항

- 서비스별 책임과 Deployment 구성
- Namespace 구분 및 팀별 운영 범위
- Cluster·Node Group·AZ 배치 구조
- 외부 진입 경로와 내부 서비스 간 통신
- 데이터 저장 위치 및 서비스별 데이터 접근 책임

## 2. 서비스 구성

### 2.1 분리 기준과 이유(Namespace)

- 서비스는 업무 책임, 배포 변경 주기, 부하 특정 및 장애 영향 범위를 기준으로 구분합니다.
    - 다른 확장 정책이나 배포 주기가 필요한 워크로드는 별도 Deployment로 구성하겠습니다.
    - 동일한 담당 팀과 운영 정책을 공유하는 워크로드는 같은 Namespace에 배치하겠습니다.
    - 도메인이 다르다는 이유만으로 실행 단위를 분리하지 않고, 분리로 얻는 운영상 이점과 서비스 간 리로스 관리 부담을 함께 고려합니다.

> 🔥 현재 네임스페이스 구성은 V3의 목표 서비스 구조입니다. 기존 Backend 이미지를 여러 Deployment에 배치하여 운영 정책을 검증하는 경우, 이를 애플리케이션 코드와 데이터 책임의 분리 완료로 간주하지 않습니다. 실제 기능 분리 여부와 검증용 배치 여부는 구현 현황에 별도로 표시하겠습니다.
> 

| 서비스 이름(라벨) | 서비스 단위 | Namespace | 주요 책임 | 실행 형태 | 스케일링 |
| --- | --- | --- | --- | --- | --- |
| auth-api | 인증/인가 | account | 구글 OAuth 로그인, 로그아웃, AT 재발급, RT 관리 | Deployment | HPA (CPU) |
| member-api | 회원 | account | 회원 정보 조회 및 관리 | Deployment | HPA (CPU) |
| youtube-api | 유튜브 영상 분석 | ingest | YouTube 연동·해제·연동 정보 조회, 동기화 요청 접수, 분석 큐 적재, 동기화 상태 조회 | Deployment | HPA (CPU) |
| youtube-analysis-worker | 유튜브 영상 분석 | ingest | 분석 큐 소비, ai-api 영상 분석 호출, 분석 결과를 개인 보관함에 전달 | Deployment | KEDA (SQS 큐 길이, 0개까지 축소) |
| wishlist-api | 개인 보관함 | content | 장소·이벤트·코스 보관 조회, 삭제, 코스 추가, 분석 결과 반영, 추천 후보 제공 | Deployment | HPA (CPU) |
| chat-api | 채팅 | recommend | 채팅 SSE 처리, ai-api 슬롯 추출 호출, 슬롯 상태 관리 | Deployment | KEDA (동시 SSE 연결 수) |
| recommend-api | 추천 | recommend | 코스 추천 SSE 처리, 추천 중단, 보관함 후보 조회, ai-api 코스 추천 호출 | Deployment | KEDA (동시 SSE 연결 수) |
| ai-api | AI | ai | 영상 분석, 슬롯 추출, 코스 추천 (외부 AI 호출, 프롬프트 구성, 응답 검증) | Deployment | KEDA (처리 중 요청 수) |
| web | 프론트엔드 | frontend |  |  |  |

`가정을 라벨이 아닌 네임스페이스로 나누는 이유`

> Namespace는 팀별 리소스 관리 범위 및 사용하는 자원 특성을 구분합니다. 실제 접근 권한과 자원 사용 제한은 RBAC·ResourceQuota·LimitRange로 적용하며, 통신 제한은 NetworkPolicy와 이를 지원하는 네트워크 구성으로 별도 정의할 예정입니다. d
> 

#### 현재 부족한 점

주요 분리 결정과 이유에 대해서 설명 추가 - 특히 ai-api

### 2.2 ResourceQuota

- Namespace 안에서 생성할 수 있는 리소스의 총량을 제한하는 Kubernetes 리소스입니다.

```hcl
KeepGo V3에서는 여러 팀이 공통 클러스터를 사용하므로, 
특정 Namespace의 과도한 확장이나 배포 설정 오류가 다른 팀의 자원 확보에 영향을 주지 않도록 
ResourceQuota를 적용합니다.
```

`적용 항복`

| 항목 | 제한 대상 | KeepGo 적용 방향 |
| --- | --- | --- |
| requests.cpu | Pod에 선언된 CPU requests의 합계 | Namespace별 CPU 요청 총량 관리 |
| requests.memory | Poddp 선언된 메모리 requests의 합계 | Namespace별 메모리 요청 총량 관리 |
| limits.memory | Pod에 선언된 메모리 limits의 합계 | 메모리 상한 총량 관리 |
| pods | 종료되지 않은 Pod 수 | 과도한 복제본 생성 제한 |

`중요하게 생각해야할 것`

> 하나의 워크로드의 최대 자원이 A이고 다른 워크로드의 최대 자원이 B라면, Quota는 A와 B를 합친 배포 여유를 더해 정하겠습니다. 
여기서 워크로드가 워커라면 최대 자원이 B를 넘어 확장하지 않도록 KEDA 상한을 맞추겠습니다.
> 

| Namespace | 워크로드 특성 | 적용 기준 |
| --- | --- | --- |
| account | 로그인·회원 조회 등 일반 API 요청 | 로그인 집중 시 필요한 확장 여유 확보 |
| ingest | 사용자 API와 대량 분석 Worker가 함께 실행 | Worker 확장이 API 운영 자원을 소진하지 않도록 상한 설정(유튜브API) |
| content | 보관함 조회·저장 등 DB 접근 중심 | DB 처리 여력에 맞춰 확장 가능한 자원 배정 |
| recommend | 채팅·추천의 SSE 장기 연결 유지 | 동시 연결 수에 따른 메모리와 연결 종료 대기 여유 반영 |
| ai | 모델 적재와 CPU 추론 수행 | 모델 메모리와 동시 추론에 필요한 CPU 기준으로 배정 |
| frontend | Next.js 웹요청 및 렌더링 처리 | 렌더링 방식과 접속량에 맞춰 자원 배정 |

`공통 산정 기준`

> Namespace별 ResourceQuota는 소속 워크로드의 최대 확장에 필요한 자원 합계와 롤링 배포·종료 대기 중 추가되는 자원을 기준으로 산정하겠습니다. 

각 Namespace에는 동일한 산정 원칙을 적용하되, 비동기 작업 증가, SSE 연결 유지, AI 추론 및 웹 렌더링 등 실제 부하 특성에 따라 여유분을 조정하겠습니다.
> 

### 2.3 RBAC

Role-Based Access Control - 사용자·그룹·ServiceAccount가 Kubernetes 리소스에 수행할 수 있는 작업을 역할별로 정의하는 권한 방식

`권한 구성 방식`

| 구성요소 | 역할 |
| --- | --- |
| Role | 특정 Namespace에서 허용할 리소스와 작업 정의 |
| RoleBinding | Role을 사용자·그룹·ServiceAccount에 연결 |
| ClusterRole | 클러스터 범위 권한 또는 여러 Namespace에서 재사용할 권한 정의 |
| ClusterRoleBinding | ClusterRole을 클러스터 전체 범위로 부여 |

`운영 주체별 적용 기준`

하드닝을 기준으로 RBAC 구성을 하겠습니다.

IAM - AWS 리소스에 대한 접근 권한 관리

RBAC - Kubernetes API 리소스에 대한 접근 권한 관리

하드닝(Hardening) : 시스템의 불필요한 기능과 권한을 제거하고, 보안 설정을 강화하여 공격자가 침입할 수 있는 경로를 최소화하는 작업

| 운영 주체 | 허용 범위 | 적용 기준 |
| --- | --- | --- |
| 클라우드 담당팀 | 담당 Namespace의 상태 조회, Namespace·RBAC·Quota·클러스터 등 공통 인프라 설정 관리 | 공통 인프라와 운영 정책의 변경 책임을 가짐 |
| 풀스텍 · AI 담당팀 | 담당 Namespace의 Pod 등의 이벤트/로그 조회 | 서비스 상태 확인과 장애 분석 담당 |
| 배포 접근 도구
(ArgoCD) | 배포 대상으로 지정된 Namespace에서 승인된 애플리케이션 리소스 생성/변경/삭제 | Git의 배포 설정을 클러스터에 반영 |
| 애플리케이션 | 실행이 필요한 k8s API만 허용 | k8s API 사용이 없으면 추가적인 권한 부여하지 않음
IAM 권한과 구분해서 관리 |

`EKS Access Policy vs IAM + RBAC`

```hcl
IAM을 EKS에서 제공하는 Access Policy로 바로 정책을 선택할 수 있지만,
IAM과 RBAC의 정책이 일치하는 지를 확인해야햐하고 HTTPRoute와 KEDA, NodePool을 사용하기 때문에,
RBAC를 조합하는 방식을 선택했습니다.
```

#### Role

| 사용 주체 | 대상 리소스 | 허용작업 |
| --- | --- | --- |
| 인프라 관리
platform-operator | Namespace·RBAC·Qouta·네트워크 정책, Gateway·NodePool 등 공통 인프라 | get, list, watch, create, update, patch, delete |
| 서비스 조회
service-observer | 담당 Namespace의 서비스 상태·로그 | get, list, watch |
| 배포
application-deployer | 지정된 Namespace의 애플리케이션 배포 리소스 | get, list, watch, create, update, patch, delete |
| 애플리케이션 실행 | 실행에 필요한 KubernetesAPI | 필요 시 별도 정의 |

#### RoleBinding

| 연결 대상 | Role | 적용 범위(Namespace) | 연결 방식 |
| --- | --- | --- | --- |
| 클라우드 담당팀 | platform-operator | 클러스터 전체의 지정된 관리 리소스 | ClusterRoleBinding |
| 풀스텍 담당팀 | service-observer | `account`, `ingest`, `content`, `recommand`, `frontend` | Namespace별 RoleBinding |
| AI 담당팀 | service-observer | `ai` | RoleBinding |
| ArgoCD | application-deployer | 지정된 배포 대상 Namespace | Namespace별 RoleBinding |

## 3. 클러스터

### 3.1 EKS의 기본 기능

> EKS에서 기본적으로 제공하는 기능을 나열하겠습니다
> 
1. **Control Plane 운영**
    - `kube-apiserver` - Kubernetes API 요청을 받는 진입점
    - `kube-scheduler` - 새 Pod를 어느 Node에 배치할지 결정
    - `kube-controller-manager` - Deployment, Node 등의 상태를 감시하고 원하는 상태를 유지
    - `etcd` - Kubernetes 오브젝트와 클러스터 상태를 저장
    
    EKS에서는 AWS가 Control Plane의 설치와 운영, 고가용성 유지, 패치를 지속적으로 관리
    
    → 대신, 사용자는 Deployment, Service, RBAC, 애플리케이션 설정 등을 관리
    
2. **3개의 AZ에 걸친 고가용성**
    
    EKS는 Control Plane을 3개의 AZ에 분산해서 운영
    
    → 최소 2개의 API Server 인스턴스와 3개의 etcd 인스턴스를 배치(가용성 유지)
    
3. **etcd 백업**
    
    클러스터의 상태를 저장하는 key-Value 데이터베이스를 관리
    
    → 관리형 클러스터에 대한 정기 백업 및 복구 메커니즘을 운영
    
    > 🔥 그렇다고 따로 백업 기능이 필요없는 것은 아닙니다. 따로 운영팀에서 Terraform, GitOps, etcd 스냅샷을 이용할 예정입니다.
    > 
    
    > → AWS가 제공하는 etcd 백업은 주로 EKS Control Plane의 서비스 복원력을 위한 관리형 기능이기 때문입니다.
    > 
4. **인증 및 접근 제어** 
    
    EKS는 Kubernetes API에 접근할 사용자의 신원 확인을 AWS IAM과 연동할 수 있습니다.
    
    → 즉, 담당부서에게 특정한 권한만 부여할 수 있습니다.
    
    KeepGo에서는 EKS Access Policy와 Kubernetes RBAC를 이용하여서 강한 격리성을 유지할 예정입니다.
    
5. **IAM 연동**
    
    이 IAM 연동은 바로 Pod가 AWS 서비스에 접근할 때 사용하는 IAM 권한입니다.
    
    → 즉, EKS Pod Identity를 사용하면 Pod의 ServiceAccount와 IAM Role을 연결해 필요한 AWS 권한을 제공할 수 있습니다.
    
    모든 Pod에 같은 IAM Role을 부여하기보다는 서비스별로 최소 권한을 자세하게 설정하겠습니다.
    
6. **관리형 Add-on 제공**
    
    Kubernetes에서 추가적으로 운영할 수 있는 소프트웨어를 뜻합니다.
    
    - Amazon VPC CNI - Pod IP 할당 및 AWS VPC 네트워크 구성
    - CoreDNS - Service 이름 등을 DNS로 해석
    - Amazon EBS CSI Driver - Pod가 EBS 스토리지를 사용할 수 있도록 지원
    - EKS Pod Identity Agent - Pod에 IAM 자격 증명을 제공하는 기능 지원

> 🗣️ 이렇게 Control Plane을 EKS로 효과적으로 관리할 예정입니다. 버전과 호환성 관리까지 대신하기 때문에 안정적인 운영이 가능합니다.
> 

### 3.2 Worker Node 방식 선택

```hcl
3가지의 노드 운영 방식이 있습니다.
3가지 모두 클러스터가 효과적으로 운영하는데 있어서 관리형 서비스를 제공합니다. 
```

1. **EKS Auto Mode**
    - EKS Auto Mode는 컨트롤 플레인뿐 아니라 데이터 플레인(노드)과 핵심 에드온까지 AWS가 운영하는 EKS 클러스터 모드입니다.
        - 사용자는 워크로드와 정책에 집중하고, 노드의 생성, 확장, 패치, 교체는 AWS가 담당합니다.
    
    `특징`
    
    - 노드 오토스케일링이 내장되어 있으며, Karpenter 기반으로 동작합니다.
    - 기본적으로 Pod 네트워크, 서비스 네트워크, 클러스터 DNS, 블록 스토리지(EBS), 로드밸런서 등 내장기능으로 제공합니다.
    - EC2 요금에 더해 인스턴스별 관리 수수료가 부과됩니다.
2. **EKS - Karpenter**
    - Karpenter는 오픈소스 노드 오토스케일러입니다.
        - 대기 중인 Pod의 요구사항을 보고 가장 적합한 인스턴스를 직접 골라 생성합니다. Standard 모드 EKS에 사용자가 설치하고 운영합니다.
    
    `특징`
    
    - 노드그룹 없이 Pod 단위 요구사항(CPU, 메모리, 아키텍처, AZ, taint/toleration)에 맞춰 인스턴스를 선택합니다.
    - AMI와 노드 설정을 사용자가 결정합니다.
    - Karpenter 컨트롤러, IAM 권한, 스팟 회수 알림 큐, 그리고 VPC CNI 등 애드온의 운영은 사용자 책임입니다.
3. **Managed Node Group + CA**
    - 관리형 노드그룹은 AWS가 ASG를 사용하여 노드를 생성하고 업데이트 절차를 제공하는 방식입니다.
        - 노드 수 자동 조절은 기본 기능이 아니므로, 오픈소스 Cluster Autoscaler를 함께 사용합니다.
    
    `특징`
    
    - 노드그룹마다 인스턴스 타입과 최소·최대 노드 수를 미리 정합니다.
    - CA는 노드그룹 단위로 노드 수를 늘리거나 줄입니다. 그룹 안의 노드는 같은 크기라고 가정합니다.
    - 구조가 단순하고 오래 쓰여 학습비용이 낮지만(ECS), 인스턴스 선택이 유연하지 않고 노드 통합 기능이 없습니다.
- `용어 정리`
    
    `AMI - EC2 인스턴스를 만드는 이미지(도커 이미지와 유사)`
    
    | 비교 | AMI | Docker Image |
    | --- | --- | --- |
    | 목적 | EC2 서버 생성 | 컨테이너 생성 |
    | 포함 내용 | OS와 서버 실행 환경 | 애플리케이션과 실행에 필요한 파일 |
    | 실행 결과 | ECS 인스턴스 | 컨테이너 |
    | 사용 위치  | Worker Node | Node 안의 Pod |
    - 일반적인 EC2와 달리 EKS의 Worker Node는 Kubernetes 클러스터에 참여해야 합니다.
    - 그래서 운영체제만 있다고 바로 Kubernetes Node로 사용할 수 있는 것은 아니고 추가적인 구성요소가 필요합니다.
    
    | 구성요소 | 역할 |
    | --- | --- |
    | Linux OS | 서버 운영체제 |
    | containerd | 컨테이너 실행을 담당하는 런타임 |
    | kubelet | Node에서 Pod 실행과 상태를 관리하는 에이전트 |
    | Node 초기화 설정 | EKS API Server와 연결하고 클러스터에 등록 |
    
    → AWS는 이런 준비 작업을 쉽게 하도록 EKS Optimized AMI를 제공
    
    도커파일처럼 재사용이 가능하고 EC2 Image Builder, HashiCorp Packer처럼 자동화가 가능합니다.
    
    `Kubernetes의 노드 통합(Node Consolidation)이란?`
    
    - 노드 통합은 여러 EC2에 흩어져 있는 Pod를 더 적은 수의 EC2에 배치해서, 불필요한 EC2를 종료하는 비용 최적화 기술
        
        → 주로 Karpenter와 EKS Auto Mode에서 사용
        
    
    **노드를 통합하는 과정**
    
    1. 자원 낭비 감지 : Karpenter가 노드에 예약된 자원과 Pod 배치 상태를 분석
    2. 통합 가능성 판단 : 특정 노드의 Pod를 다른 노드로 옮기거나, 더 저렴한 EC2로 대체할 수 있는지 확인
    3. Pod 종료 및 재생성 : 기존 Pod를 안전하게 종료하고 다른 Node에서 대체 Pod가 실행되도록 합니다.
    4. EC2 종료 : 더 이상 필요하지 않은 노드를 종료해 비용을 절감
    
    **노드 통합의 세 가지 대표 정책**
    
    | 정책 | 설명 |
    | --- | --- |
    | WhenEmpty | 실행할 워크로드가 없는 노드만 통합 |
    | WhenEmptyOrUnderutilized | 비어 있거나 통합으로 비용을 절감할 수 있는 노드를 적극적으로 통합 |
    | Balanced | 비용 절감 효과와 Pod 중단 위험을 함께 고려 |
    
    **HPA와 노드 통합의 차이**
    
    | 기술 | 역할 |
    | --- | --- |
    | HPA | Pod의 개수를 늘리거나 줄임 |
    | KEDA | SQS 메시지 수 등 이벤트에 따라 Pod 수를 조절 |
    | Karpenter Node Consolidation | Pod들을 효율적으로 재배치하고 불필요한 Node를 종료 |
    
    **NodePool(노드풀)이란?**
    
    - NodePool은 Karpenter나 EKS Auto Mode에서 어떤 조건의 EC2 Worker Node를 생성하고 운영할지 정의하는 설정
        - NodePool은 실제 EC2 묶음 자체가 아니라 EC2를 생성하는 정책
    
    **NodePool에는 어떤 설정이 들어갈까?**
    
    | 설정 | 의미 | 예시 |
    | --- | --- | --- |
    | Instance Type | 사용할 EC2 종류 | m, c, r 계열 |
    | Capacity Type | EC2 구매 방식 | Spot, On-Demand |
    | AZ | 실행할 가용 영역 | ap-northeast-2a, 2c |
    | Architecture | CPU 아키텍처 | amd64, arm64 |
    | Limits | 생성 가능한 총 자원 상한 | CPU 100개 |
    | Disruption | Node 통합·교체 정책 | 비어 있거나 비효율적인 노드 통합 |
    
    **노드풀 YAML 설정의 의미**
    
    - worker-pool : NodePool 이름
    - spot : Spot 인스턴스만 사용
    - c, m : 컴퓨팅 최적화 또는 범용 EC2 계열 사용
    - amd64 : x86-64 아키텍처 사용
    - cpu: “100” : NodePool 전체의 CPU 용량 상한을 100 vCPU로 설정
    
    EC2NodeClass는 AMI, 서브넷, 보안 그룹 등 AWS 전용 설정을 정의하는 별도 리소스입니다. 
    
    - consolidationPolicy : 어떤 Node를 통합 대상으로 고려할 것인가?
    - consolidateAfter : Pod 배치 상태가 변경된 후 얼마나 기다릴 것인가?
    - buhgets : 동시에 몇 개의 Node까지 중단할 수 있는가?
    
     
    

### 3.3 Karpenter

```hcl
KeepGo서비스는 V3에서 EKS의 Karpenter을 사용하기로 하였습니다.
```

#### Starndard EKS

1. EC2 수준 장애 주입 가능
- FIS 등의 장애 주입 테스트로 병목지점을 찾고 인프라 아키텍처를 개선하는 데 있어서 서비스와 어울린다고 생각했습니다.

→ Auto Mode 미지원

1. 스팟사용
- 오토모드에서는 관리 수수료가 인스턴스 종류와는 무관하게 부과돼서 스팟에도 온디맨드 기준의 수수료가 붙습니다.

→ 따라서 워커에는 스팟을 그대로 사용하여서 EC2 할인을 받을 수 있습니다.

1. AMI버전을 고정 및 교체 시점
- 버전을 고정하며 교체 시점을 저희가 정할 수 있으며 무엇보다 수명주기도 따로 자유롭게 설정할 수 있습니다.
1. 노드에 SSM으로 접속해 진단 가능
- 가정과는 다르게 현재 저희는 k8s 환경을 EKS로 보완했지만 직접 운영을 2명이서 해야하기 때문에 SSM 접속이 필요했습니다.

→ 라우팅, eBPF 정책 등을 확인

1. Auto Mode로의 유동적인 변환
- Auto Mdoe로 노드풀의 API가 같아 마이그레이션 중 병행 구성을 공식 문서에서 안내하고 있습니다.

#### 근거

`R1. 장애 대응 실험을 V3에서도 유지`

- 노드가 사라질 때 Pod가 어떻게 되는 지 확인함으로써 가용성 정책을 실험으로 검증
    - 노드 종료 시 PDB와 Topology Spread가 SSE(chat, recommend)와 Redis StatefulSet을 지키는지
    - 스팟 회수 시 분석 워커가 작업을 잃지 않는지 (멱등 처리, 재큐잉)
    - 노드 통합이 Pod를 옮길 때 서비스 영향이 허용 범위 안인지

`R2 스팟 우선 분석 워커`

- 현재 저희 서비스에서는 분석 워커의 역할이 확실히 존재하고 큐 기반이며, 멱등하고, 중단돼도 다시 처리할 수 있기 때문에 Spot에 잘 어울리는 워크로드라고 할 수 있습니다.

`R3. 노드 교체 시점 통제`

- 저희 서비스에는 노드 교체에 민감한 워크로드가 존재합니다. 바로 Redis와 SSE 연결입니다.  또한, 트래픽 특성항 버스트가 발생합니다.
    - Karpenter는 AMI버전을 고정해두며, 트래픽이 적은 시간에 따로 반영할 수 있습니다.
        
        → 즉, 노드 교체가 저희의 정책으로 만들 수 있습니다.
        

`R4. 노드 수준 장애 분석`

- NetworkPolicy(eBPF 기반)와 장시간 SSE 연결을 함께 사용하므로, 연결 끊김이나 정책 오적용이 발생하면 노드의 라우팅·conntrack·정책 상태를 직접 확인해야 원인을 특정할 수 있습니다.

#### 트레이드오프

- **Karpenter 컨트롤러 운영**
    
    → 컨트롤러를 Fargate에서 실행해서 system 노드그룹 고정비를 절감
    
- **스팟 회수 알림 큐**
    
    → Terrafrom 모듈로 구성
    
- **VPC CNI, CoreDNS 등의 운영**
    
    → EKS 관리형 에드온으로 두고, 업그레이드 절차를 명시
    
- **노드 AMI 갱신 책임**
    
    → AWS 버전 고정 + 정기 갱신 PR + drill               
    

### 3.4 네트워크

- 용어설명
    1. **AWS 네트워크 - EC2와 Pod가 어느 네트워크에 존재하는가?**
    2. **Pod 네트워크 - Pod에 IP를 어떻게 할당하고 서로 연결할까?**
    3. **Service / DNS - IP가 바뀌는 Pod를 어떻게 찾아갈까?**
    4. **외부 트래픽 - 인터넷 사용자가 Pod에 어떻게 접근할까?**
    5. **네트워크 보안 - 어떤 통신을 허용하고 차단할까?**
    6. **운영 및 고급 기술 - 트래픽을 어떻게 추적하고 성능을 최적화할까?**
    
    | 용어 | 의미 |
    | --- | --- |
    | CNI | 컨테이너 네트워크를 설정하는 표준 인터페이스 및 플러그인 체계 |
    | Amazon VPC CNI | EKS에서 기본적으로 사용하는 Pod 네트워킹 플러그인 |
    | Pod IP | 개별 Pod에 할당된 네트워크 IP |
    | Node IP | Worker Node가 사용하는 IP |
    | Network Namespace | IP, 네트워크 인터페이스, 라우팅 테이블 등을 격리하는 LInux 네트워크 공간 |
    | veth Pair | 서로 연결된 가상 네트워크 인터페이스 한 쌍 |
    | IPAM | IP Address Management. IP 주소를 할당하고 회수하는 기능 |
    | ENI | EC2에 연결되는 AWS 가상  네트워크 인터페이스 |
    | Secondary IP | ENI에 추가로 할당하는 IP 주소 |
    | Prefix Delegation | ENI에 개별 IP 대신 IP 주소 블록을 할당해 Pod용 IP를 관리하는 방식 |
    | maxPods | Node 하나에서 실행 가능한 Pod 수의 상한 설정 |
    
    **Amazon VPC CNI 순서**
    
    ```hcl
    EKS Worker Node
    ->
    Amazon VPC CNI
    -> 
    ENI의 IP 주소 자원 관리
    -> 
    Pod에 VPC IP 할당
    ->
    Pod 간 통신
    ```
    
    **패킷 전달 기술**
    
    | 용어 | 의미 |
    | --- | --- |
    | Overlay Network | 기존 네트워크 위에 가상 네트워크를 구성하는 방식 |
    | Underlay / Native Routing | 기존 물리 · 가상 네트워크의 라우팅을 활용하는 방식 |
    | VXLAN | 원래 패킷을 UDP 기반 패킷으로 감싸 전달하는 터널링 기술 |
    | IP-in-IP | IP 패킷을 다른 IP 패킷 안에 감싸는 캡슐화 방식 |
    | Geneve | 확장 가능한 메타데이터를 지원하는 터널링 프로토콜 |
    | BGP | 라우터나 노드 사이에서 네트워크 경로 정보를 교환하는 프로토콜 |
    | eBPF | Linux 커널에서 네트워크 처리 · 보안 · 관측 프로그램을 실행하는 기술 |
    | iptables | Linux에서 패킷 필터링과 NAT 등을 설정하는 기능 |
    | SNAT / DNAT | 각각의 패킷의 출발지 / 목적지 IP를 변환하는 NAT 방식 |
    | Amazon VPC CNI | ENI, IPAM, VPC Native Routing |
    
    **Service 관련**
    
    | 용어 |  의미 |
    | --- | --- |
    | Service | 변경되는 Pod IP 대신 안정적인 접근 경로를 제공하는 Kubernetes 리소스 |
    | ClusterIP | 클러스터 내부에서 Service에 접근할 때 사용하는 가상 IP |
    | Service CIDR | ClusterIP를 할당하기 위한 별도의 IP 주소 범위 |
    | NodePort | Node IP의 지정된 포트를 통해 Service에 접근하는 방식 |
    | LoadBalancer | 외부 로드밸런서를 통해 Service에 접근하도록 하는 Service 유형 |
    | ExternalName | 외부 DNS 이름에 연결하는 Service 유형 |
    | Headless Service | ClusterIP 없이 개별 엔드포인트를 DNS로 검색하게 하는 Service |
    | EndpointSlice | Service와 연결된 실제 Pod IP 및 포트 등의 정보를 관리하는 리소스 |
    | kube-proxy | Service 트래픽을 Pod로 전달하기 위한 네트워크 규칙을 관리하는 기본 구현체 |
    | Service Discovery | 애플리케이션이 다른 서비스의 위치를 찾아가는 기능 |
    | Label Selector | Service가 트래픽 대상으로 사용할 Pod를 선택하는 조건 |
    
    **DNS 관련 용어**
    
    | 용어 | 의미 |
    | --- | --- |
    | CoreDNS | Kubernetes Service 이름을 IP로 해석하는 클러스터 DNS 서버 |
    | NodeLocal DNSCache | Node별 DNS 캐시로 반복 조회를 줄이는 기능 |
    | DNS Resolver | 도메인 이름의 IP를 알아내기 위해 DNS 질의를 수행하는 구성요소 |
    | FQDN | 전체 도메인 이름 |
    | cluster.local | Kubernetes에서 기본적으로 사용하는 클러스터 DNS 도메인 |
    | TTL | DNS 조회 결과 등을 얼마나 오래 캐싱할지 나타내는 시간 |
    | Route 53 Resolver | VPC에서 DNS 질의를 해석하거나 전달하는 AWS DNS 기능 |
    
    **외부 접근 및 로드 밸런싱**
    
    | Ingress | 외부 HTTP/HTTPS 요청을 어떤 Service로 전달할지 정의하는 kubernetes 리소스 |
    | --- | --- |
    | Ingress Controller | Ingress에 정의된 규칙을 실제로 구현하는 컨트롤러 |
    | IngressClass | 어떤 Ingress Controller가 Ingress를 담당할지 지정하는 리소스 |
    | Gateway API | Ingress보다 확장된 트래픽 라우팅 API 집합 |
    | AWS Load Balancer Controller | Kubernetes 리소스를 감시해서 AWS ALB/NLB 등을 생성·관리하는 컨트롤러 |
    | ALB | HTTP/HTTPS 등 L7 요청을 분석하고 분산하는 AWS 로드밸런서 |
    | NLB | TCP/UDP 등 L4 네트워크 연결을 전달하는 AWS 로드밸런서 |
    | Target Group | 로드밸런서가 트래픽을 전달할 Node 또는 Pod IP 등의 대상 집합 |
    | Listener | 로드밸런서가 수신할 프로토콜과 포트를 정의하는 설정 |
    | Health Check | 대상 애플리케이션이 정상적으로 요청을 받을 수 있는지 검사 |
    | IP Target | ALB/NLB가 Pod IP 같은 IP 엔트포인트를 대상으로 트래픽 전달 |
    | Instance Target | EC2 Node를 대상으로 트래픽 전달. 일반적으로 NodePort 경유 |
    | Internal Load Balancer | 사설 네트워크에서 접근하도록 구성한 로드밸런서 |
    | Internet-facing Load Balancer | 인터넷에서 접근할 수 있도록 구성한 로드밸런서 |

> V3는 EKS 기반 서비스 구성과 노드 운영 방식에 이어, 서비스 간 통신과 외부 요청 처리 경로를 설계하는 단계입니다.
→ 이후 서비스별 통신 요구사항에 맞춰 접근 제어 정책을 구체화할 예정입니다.
> 

#### CNI 선택과 Pod IP 할당

| 선택할 항목 | 선택지 | 판단할 기준 |
| --- | --- | --- |
| CNI | Amazon VPC CNI / 다른 CNI 검토 | AWS 연동, 필요한 기능, 운영 부담 |
| IP 체계 | IPv4 / IPv6 | 기존 인프라 호환성, 주소 부족 가능성 |
| Node·Pod 서브넷 | 같은 서브넷 / Custom Networking으로 분리 | Pod 주소 공간을 별도로 확보해야 하는지 |
| IPv4 할당 방식 | 개별 Secondary IP / Prefix Delegation | 노드당 Pod 수, 확장 속도, 주소 여유 |

#### 로컬 DNS (VPC Resolver) VS CoreDNS

`로컬 DNS` 

AWS가 VPC에 제공하는 DNS 리졸버로, 도메인 이름에 해당하는 IP주소를 조회합니다.

즉, 도메인의 IP를 구할 때 리졸버는 캐시를 확인하고, 필요하면 다른 DNS 서버에 질의해서 답을 구합니다.

`CoreDNS` 

같은 DNS이지만 Kubernetes 내부의 DNS 처리를 담당 

→ 내부의 Service 이름 등을 IP주소로 해석하여, Pod가 다른 서비스를 이름으로 찾아갈 수 있도록 합니다.

#### 쿠버네티스의 로컬 DNS

→ NodeLocal DNSCache

- 노드마다 DNS 캐시 에이전트를 데몬셋으로 실행하는 선택적 애드온
- Pod의 DNS 질의를 같은 노드에서 먼저 처리하고, 캐시된 결과가 있으면 즉시 응답합니다. 캐시에 없는 클러스터 내부 이름은 CoreDNS에 질의하여, 반복적인 DNS 요청과 조회 지연을 줄입니다.

DaemonSet : Kubernetes에서 각 Node마다 특정 Pod가 하나씩 실행되도록 관리하는 리소스

#### 구성방안(KeepGo)

내부 서비스 조회 : Pod → CoreDNS → 내부 서비스 IP 응답

외부 도메인 조회 : Pod → CoreDNS → VPC Resolver → 조회 결과 응답

#### CNI란?

Container Network Interface - Kubernetes에서는 Pod가 생성되거나 삭제될 때 이 인터페이스를 통해 네트워크를 연결하고 정리합니다.

즉, Pod가 애플리케이션을 실행하려면 IP 주소와 네트워크 인터페이스가 필요하여, 다른 Noded의 Pod에도 패킷을 전달할 수 있어야 합니다.

`공통된 역할`

네트워크 인터페이스 - Pod의 네트워크 공간을 Node의 네트워크와 연결

IP 주소 관리 - Pod에 사용할 IP 주소 · 할당 · 회수

패킷 전달 경로 - 같은 Node 또는 다른 Node의 Pod와 통신할 경로 구성

네트워크 정리 - Pod 삭제 시 연결과 관련 자원 정리

`Flannel - Pod 간 연결에 집중한 네트워크 구성`

- VXLAN 기반 Overlay Network이기에 Pod의 패킷을 Node 사에에서 전달할 수 있는 패킷으로 감싸서 보개고, 도착한 Node에서 원래 패킷을 꺼내 목적지 Pod에 전달합니다.
- Pod 연결을 중심으로 동작하며, 노드 간 통신 구조를 학습하기에 접근하기 쉽습니다.
- Overlay 구성에서는 캡슐화에 따른 MTU와 네트워크 조건을 확인이 필요합니다.

`Calico - 네트워크 연결과 접근 제어를 함께 제공`

- 구성에 따라 직접 라우팅 또는 VXLAN이나 IP-in-IP 기반 Overlay를 사용할 수 있습니다.
- 네트워크 연결과 정책을 모두 담당하거나, 호환되는 다른 네트워크 구현과 함께 정책을 담당할 수 있습니다.

`Cilium - eBPF 기반 네트워크/보안/관측`

- Linux 커널의 eBPF를 기반으로 Pod 통신, 보안정책, 네트워크 관측 기능을 제공하는 솔루션
- Hubble을 활성화하면 서비스 간 통신 관계와 정책에 따른 차단 등을 확인할 수 있습니다.
- AWS ENI로 세팅한다면 kube-proxy를 대체 가능

`Amazon VPC CNI - AWS VPC와 직접 연결되는 Pod 네트워크` 

- Pod에 VPC의 IP 주소를 직접 할당하여 통신하도록 하는 CNI
- EC2의 ENI와 IP주소 자원을 관리하며 별도의 기술없이 Pod간 패킷 전달이 가능합니다.
- 대신 Pod가 VPC의 주소 공간을 사용하므로, 서브넷의 가용 IP와 인스턴스별 ENI·IP를 고려해야합니다.

#### 선택 근거 - Amazon VPC CNI

#### NetworkPolicy

Kubernetes에서 Pod 간 또는 Pod와 외부 시스템 사이의 네트워크 통신을 허용하거나 제한하는 보안 리소스 → Pod에 적용하는 방화벽 규칙

`keepgo에서는?`

```hcl
현재 MSA구조를 가정하고 네임스페이스를 나누었고 서비스 특성상 구조가
AI는 백엔드를 무조건 거치는 구조입니다. 
즉, 네트워크정책을 사용하여서 네임스페이스를 기준으로 통신을 제어하고 포트와 프로토콜을 정의합니다.
Backend -> AI API -> Gemini API
web -> AI API = 제한
```

→ 3장에서 YAML로 Ingress와 Egress를 YAML로 작성 필요

`미리 적용해보기`

NetworkPolicy는 어떤 통신을 허용할지 정의하는 규칙이고, CNI의 정책 엔진은 그 규칙을 실제 네트워크에 적용하는 역할

즉, 네트워크정책 YAML을 작성하고 API 서버에 저장합니다. 그 후에 지원하는 CNI라면 실제 네트워크에 규칙을 적용합니다. 

→ NetworkPolicy를 적용가능한 CNI 필요

`Prefix Delegation`

Amazon VPC CNI가 Pod에 IP 주소를 하나씩 할당받는 대신, 여러 IP주소를 하나의 묶음(prefix)으로 할당받아 관리하는 기능

`왜 custom으로 안하고 Prefix를 했나요?`

```hcl
일단 커스텀으로 하면 노드 인터페이스의 개수에 맞게 저희가 직접 설정해야하고, 
이때 각 IP별로 할당 가능한 Private Ip도 다르기 때문입니다.
```

#### eBPF

Linux 커널 내부에서 특정 이벤트가 발생했을 때 미리 등록한 프로그램을 실행할 수 있는 기술

→ Linux 커널의 코드를 직접 수정하지 않아도 네트워크 패킷을 검사하거나, 차단하거나, 시스템 동작을 관측할 수 있는 기술입니다.

- **Hook** : 네트워크 패킷 도착, 시스템 호출 등 특정 이벤트가 발생했을 때 프로그램을 실행하는 연결 지점
- **Verifier** : eBPF 프로그램이 커널에서 안전하게 실행될 수 있는지 검사하는 기능
- **Map** : eBPF 프로그램이 정책 정보나 연결 상태 등을 저장하고 조회하는 자료구조

`keepgo에서는?`

```hcl
기본적으로 사용되는 iptabels를 사용하지 않고,
 eBPF를 사용하여 네트워크 정책을 컨트롤할 예정입니다.
```

`왜 iptabels를 사용하지 않고 eBPF를 사용하나요?`

```hcl
기본적인 이유는 더 빠르고 Hook등을 이용하여서 
패킷을 더 빠르게 가져와 디도스등 회사 입장에서 취약한 공격들을 더 잘 대응할 수 있다고 판단했습니다.
```

→ 현재 필요한 것은 Pod·Namespace 기준의 접근 제어입니다. 

`그럼 Cilium이랑 Calico도 eBPF 기반으로 설정할 수 있는 걸로 아는데 왜 안쓰나요?`

Cilium과 Calico도 eBPF 기반 네트워크 기능을 제공하지만, 현재 KeepGo의 주요 요구사항은 Namespace·Pod·포트 기준의 통신 제어입니다. 이 요구사항은 Amazon VPC CNI의 NetworkPolicy 기능으로 구현할 수 있습니다.

또한, EC2 기반 EKS에서 에드온의 이점을 가져가고 추가 네트워크 구성요소의 운영·업그레이드 부담을 줄이는 방향을 선택했습니다. 추가로 Default인 아마존 VPC를 안쓰고 다른 CNI를 사용하려면 추가적인 외부 프로그램이 필요한 것으로 알고있습니다.

#### kube-proxy

- Kube-proxy는 Service로 들어온 트래픽이 실제 Pod에 전달되도록 각 Node의 네트워크 규칙을 관리하는 구성요소

`연결해보기`

- CoreDNS : 서비스 이름에 해당하는 IP를 알려줍니다.
- Kube-proxy : Service IP로 보낸 트래픽이 실제 Pod에 도달하도록 규칙을 만듭니다.
- CNI : Pod의 IP와 네트워크 연결을 구성합니다.

`비교해보기`

네트워크 규칙을 만드는 과정 ↔ 커널이 그 규칙으로 패킷을 전달하는 과정

**kube-proxy에서 중요하게 생각하는 것**

- Service : ClousterIP, 서비스 포트, 프로토콜, 트래픽 정책
- EndpointSlice : 실제 목적지 IP/포트, 준비 상태, Node랑 AZ 정보
- netfilter : 리눅스 커널에서 네트워크 패킷을 처리하는 프레임워크
    
    (iptables는 여기에 규칙을 설정하는 인터페이스)
    

```hcl
리눅스 커널에서 작동하는 iptables, IPVS, ntfables의 3가지 동작 방식이 있지만,
EKS 환경에서 기본적으로 제공되어 이미 호환성이 검증된 iptabels를 사용합니다.
```

`iptabels`

Service와 엔드포인트마다 규칙을 만들고, 패킷이 해당 규칙을 따라 목적지 Pod에 도달하도록 구성합니다.

`내부 동작`

1. API Server에서 Service, EndpointSlice가 변경
2. Informer가 변경 소식을 전달
3. Proxier에 기록
4. Node의 커널 네트워크 규칙 갱신

`커널에 만들어지는 규칙`

- 체인 : 순서대로 평가할 규칙을 모아둔 목록
- KUBE-SVC : 특정 Service의 목적지를 선택하는 체인
- KUBE-SEP : 선택한 엔드포인트로 목적지 주소를 바꾸는 체인
- DNAT : 패킷의 목적지 IP·포트를 변경하는 작업

> Amazon VPC CNI와 kube-proxy의 기본 iptables 모드는 EKS에서 검증된
> 

#### Ingress Controller

Kubernetes 외부(사용자)에서 들어오는 HTTP/HTTPS 요청을 Ingress 규칙에 따라 적절한 Service로 전달하도록 실제 네트워크 설정을 구성하고 관리하는 컨트롤러

`그래서 무엇을 수행하나요?`

- **규칙 감시** : Ingress와 관련 리소스의 생성·변경·삭제를 감시합니다.
- **HTTP 라우팅 구성** : 도메인과 URL 경로를 기준으로 요청의 목적지를 설정합니다.
- **HTTPS 설정 반영** : 인증서와 TLS 종료 등 HTTPS 처리 설정을 반영합니다.
- **상태 동기화** : Kubernetes에 선언한 규칙과 실제 네트워크 구성이 일치하도록 유지합니다.

`사전설정 : Ingress vs Gateway`

→ 규칙을 어떤 API로 명시할지에 대해 결정하겠습니다.

#### Ingress

클러스터 외부의 HTTP·HTTPS 요청을 도메인과 경로에 따라 내부 Service로 연결하는 Kubernetes 리소스

- ingress - 도메인·경로와 목적지 Service를 정의
- ingressClass - 어떤 컨트롤러가 Ingress를 처리할지 지정
- ingress Controller - 규칙을 읽고 로드밸런서·프록시 설정에 반영

`장점`

- 기본 구성이 단순함
- 여러 서비스를 공통 주소로 제공 가능
- Pod 변경과 라우팅 설정을 분리 - Pod IP 대신 Service를 참조하므로 Pod 교체마다 Ingress를 수정할 필요가 없음
- Kubernetes 기본 API 사용 - 별도 CRD 설치 필요없음
- Namespace별 RBAC 적용 가능 - 담당 Namespace의 Ingress 생성·수정 권한을 구분할 수 있음
- 컨트롤러의 추가 기능 활용 가능

`단점`

- 표준 라우팅 기능이 제한적
- 컨트롤러별 설정 차이
- 공통 진입점과 경로 책임 분리가 덜 명확함
- 여러 Namespace의 진입점 공유가 구현체에 의존
- TCP·UDP 라우팅은 표준 범위 밖
- API 신규 기능 개발 동결

#### Gateway API

외부 요청을 받는 진입점과 서비스별 라우팅 규칙을 나누어 정의하는 Kubernetes API 집합

- GatewayClass - 어떤 컨트롤러가 Gateway를 구현할지 지정
- Gateway - 요청을 받을 포트·프로토콜·TLS와 Route 연결 허용 범위 정의
- HTTPRoute - 도메인·경로에 따라 연결할 Service 정의

`장점`

- 관리 책임 분리가 명확함 - Gateway와 HTTPRoute를 관리하도록 RBAC 구성 가능
- 여러 Namespace의 진입점 공유를 표준으로 지원 - 각 Namespace의 Route를 공통 Gateway에 연결하고, 연결 허용 범위를 지정
- 풍부한 라우팅 규칙 표현 - 경로뿐 아니라 헤더 조건·가중치 분산 등도 표준 필드로 표현 가능
- 프로토콜별 리소스 제공 - HTTPRoute·GRPCRoute·UDPRoute 등으로 통신 특성을 구분
- 구현체 변경 시 설정 재사용 가능성 - 공통으로 지원하는 표준 기능은 컨트롤러 변경 시에도 재사용하기 쉬움

`단점`

- 학습·설정 항목 증가
- CRD와 버전 관리 필요
- 구현체마다 기능 지원이 다름
- 구현체 전요 설정이 남음
- 공유 진입점의 영향 범위는 유지됨

1. `사용자용 API와 내부 전용 서비스 구분`

우선 각 사전에 설정한 네임스페이스 별로 구분하겠습니다.

| 서비스
(네임스페이스 격리 기준) | 사용자 접근 | 통신 형태(가정) | 네트워크 특징(클라우드 기준) |
| --- | --- | --- | --- |
| web | 허용 | HTTPS | 웹페이지와 정적 자원 제공. API와 동일한 도메인을 사용할지 결정 필요 |
| auth-api | 허용 | HTTPS , OAuth | 로그인 시작과 OAuth 콜백 처리. 콜백 URL, 쿠키와 토큰 전달 방식 고려 |
| member-api | 인증 후 허용 | HTTPS | 회원 정보 조회·수정. 사용자 인증고 본인 정보 접근 권한 확인 |
| youtube-api | 인증 후 허용 | HTTPS, SSE(고려) | 동기화 완료까지 HTTP 요청을 유지, 장시간 요청에 대한 타임아웃 고려, SSE 연결 예정 |
| wishlist-api | 인증 후 허용 | HTTPS | 개인 보관함 조회/변경. 사용자용 API와 내부 분석 결과 반영 API의 공개 범위 구분 |
| chat-api | 인증 후 허용 | HTTPS, SSE 응답 | 채팅 처리 결과를 순차 전송. 스트리밍 전달과 연결 유지 필요 |
| recommend-api | 인증 후 허용 | HTTPS, SSE 응답 | 추천 결과를 순차 전송. 연결 유지와 추천 중단 요청 처리 필요 |
| ai-api | 공개하지 않음 | 내부 API 호출 | 백엔드·Worker에서 호출. 외부 사용자가 AI 처리 기능에 직접 접근하지 않도록 구성 |
| youtube-analysis-worker | 공개하지 않음 | SQS 소비, 내부 API 호출 | 큐에서 작업을 가져오는 방식이므로 사용자 요청을 받는 외부 진입 경로가 필요하지 않음 |

`SSE 고려사항`

- **스트리밍 전달** : 중간 프록시가 응답을 모아두지 않고 전달할 것
- **연결 유지** : 유휴 시간 제한과 heartbeat 주기를 맞출 것
- **연결 종료** : 배포·Pod 축소·노드 교체 시 종료와 재연결을 처리할 것
- **인증** : SSE 연결 시작 시에도 사용자 인증과 접근 권한을 확인할 것

> KeepGo V3의 외부 통신은 HTTPS 기반 API와 SSE로 구성되며, TCP·UDP 전용 외부 라우팅은 현재 요구사항에 포함하지 않습니다. 따라서 관리 방식은 HTTP 라우팅 기능, 공통 진입점의 공유 방식, 관리 권한 분리 및 컨트롤러의 지원 범위를 기준으로 선정하겠습니다.
> 

| 비교 항목 | Ingress | Gateway API |
| --- | --- | --- |
| HTTPS API 라우팅 | 도메인·경로를 기준으로 Service 연결 | Gateway와 HTTPRoute로 진입점·전달 규칙 정의 |
| SSE 제공 | 구현체의 스트리밍·타임아웃 설정 확인 필요 | 동일하게 구현체 설정 확인 필요 |
| 여러 Namespace의 진입점 공유 | 컨트롤러별 공유 기능 사용 | Gateway에 여러 Namespace의 Route를 연결하는 표준 구조 제공 |
| 관리 권한 분리 | Namespace별 Ingress에 RBAC 적용. 공유 설정의 변경 범위는 추가 설계 필요 | Gateway와 HTTPRoute에 서로 다른 RBAC 적용 가능 |
| 고급 라우팅 표현 | 헤더 조건·가중치 분산 등은 컨트롤러별 기능 활용 | 표준 필드로 표현할 수 있으나 구현체 지원 확인 필요 |
| 초기 구성 | 기본적인 웹 라우팅 구성이 비교적 단순 | GatewayClass·Gateway·HTTPRoute의 관계의 연결 조건 설정 필요 |
| 버전 관리 | 컨트롤러와 Kubernetes 호환성 관리 | 컨트롤러·Kubernetes외에 Gateway API CRD 호환성 관리 추가 |
| 구현체 의존성 | 고급 기능이 annotation등 구현체별 설정에 의존 | 표준 설정을 활용할 수 있으나 구현체 전용 설정도 존재 |

`keepgo에 적용해보기`

- 기본 HTTP·HTTPS 라우팅 - 모두 충족 가능
- SSE 제공 - 모두 연결 안정성의 검증 필요
- Namespace별 RBAC - 기존 Namespace 설계에 양쪽 모두 유지 가능
- 공통 진입점 공유 - 공유 범위와 참여 조건을 어떻게 관리할지 비교
    - Ingress - 컨트롤러별 공유 기능 활용
    - Gateway API - 여러 Namespace의 Route 연결을 표준으로 정의
- 관리 책임 - 플랫폼 담당 범위와 서비스 담당 범위를 명시적으로 표현
    - Ingress - 구현체 설정을 기준으로 분리
    - Gateway API - 공통 진입점과 개별 통로를 별도 리소스로 분리
- 고급 라우팅 - 현재 필수 요구(서비스에 없음)가 아니므로 선택 근거에서 제외
- 초기 구성 - 추가 설정 부담을 고려
    - Ingress - 기본 웹 라우팅 구성이 비교적 단순
    - Gateway API - 리소스 관계와 연결 허용 조건 설정 추가

#### 결론 및 설계 방향

`선정 결과`

> KeepGo V3는 외부 라우팅 관리 방식으로 Gateway API를 선택합니다.

선정의 핵심 근거로는 팀과 서비스의 확대에 맞춰 공통 진입점과 서비스별 라우팅의 관리 책임을 구분하고, 여러 Namespace의 경로 추가와 연결 허용 범위를 일관된 구조로 관리하는 데 있습니다.

Ingress도 현재 통신 요구사항을 충족할 수 있으나, V3에서 채택한 운영 책임 구분을 별도 리소스로 표현하기 위해 Gateway API를 선택했습니다.
> 

GatewayClass - 구현체와 공통 구현 기준 관리

Gateway - 리스너·TLS 및 Route 연결 허용 범위 관리

HTTPRoute - 서비스 담당자가 담당 Namespace의 승인된 경로와 목적지 Service 관리

공통 변경 정책 - 경로 중복, 내부 API 노출, 각 서비스별 영향 검토

#### 컨트롤러 → 구현체 선정

`용어정리`

- **서비스 Mesh** : 서비스 간 통신을 애플리케이션이 직접 관리하는 대신 별도의 네트워크 계층에서 공통으로 관리하는 기술
- **Envoy** : 서비스 간 네트워크 요청을 대신 받아 전달하면서, 로드밸런싱·보안·트래픽 제어·관측성을 제공하는 고성능 프록시 서버 → 사이드카 패턴 고려
    - 도메인·경로에 따른 요청 전달
    - 여러 서버로 요청 분산
    - TLS 처리
    - 타임아웃·재시도·요청 제한
    - 접근 로그와 통신 지표 수집
- **Reverse Proxy** : 클라이언트의 요청을 서버 대신 받아서 적절한 내부 서버로 전달하고, 서버의 응답을 다시 클라이언트에게 반환하는 중간 서버
- **Kong Gateway** : 클라이언트의 API 요청을 받아 적절한 서버로 전달하면서 인증, 요청 제한, 로드밸런싱, 트래픽 관리 등을 수행하는 API Gateway 솔루션
- **Middleware(미들웨어)** : 클라이언트의 요청과 서버의 실제 처리 로직 사이에서 공통적인 기능을 수행하는 소프트웨어 또는 처리 계층

| 구현체 = 컨트롤러 | 설명 | 특징 |
| --- | --- | --- |
| AWS Load Balancer Controller | Gateway API 설정을 AWS 로드밸런서 구성으로 변환 | HTTP 라우팅은 ALB가 처리. AWS 연동이 중심이며, 지원 기능은 ALB의 제약에 영향을 받음 |
| Envoy Gateway | Gateway API로 Envoy 프록시를 관리 | 라우팅·타임아웃·재시도·요청 제한 등의 정책 제공. 컨트롤러와 프록시를 구분해 운영 |
| Treafik | k8s 설정 변화에 맞춰 동적으로 동작하는 리버스 프록시 | Ingress와 Gateway API 모두 지원. 라우팅과 미들웨어 기능을 활용하며 Traefix 프록시가 요청 처리 |
| NGINX Gateway Fabric | Gateway API로 NGINX 프록시를 구성 | Nginx 기반 라우팅·TLS·트래픽 정책 제공.  |
| Kong Ingress Controller | Gateway API 등의 설정을 Kong Gateway에 반영하는 컨트롤러 | 인증·요청 제한·플러그인 등 API 관리 기능과 연계. Kong Operator를 활용한 배포·관리 방식도 제공 |
| Istio | Envoy 기반 게이트웨이와 서비스 메시를 제공하는 솔루션 | 외부 진입점에 사용할 수 있고, 내부 통신의 mTLS·인가·관측으로 확장 가능. 외부 게이트웨이 사용만으로 전체 메시 적용이 필수인 것은 아님 |
| Kgateway | Gateway API를 기반으로 Envoy 프록시를 관리하는 애플리케이션 게이트웨이 | eBPF 네트워크 기능과 Envoy를 연계. Gateway 기능에 Cilium의 kube-proxy 대체 설정 등 선행 조건이 있어 기존 네트워크 구성과 함께 검토해야함. |

#### 결론 및 근거

`AWS Load Balancer Controller` 

1. 현재 필요 요구사항과 어울림
    
    > HTTPS·도메인·경로 라우팅이 중심이고, 별도 프록시를 도입해야 할 고급 처리 요구는 아직 없다고 생각합니다.
    > 
2. 실제 HTTP 처리를 AWS 관리형 ALB 운임
    
    > 컨트롤러는 직접 운영하되, 요청을 처리하는 프록시 Pod의 자원·확장·업그레이드까지 운영 범위에 추가하지 않아도 됩니다.
    > 
3. 앞서 정한 구조의 활용
    
    > Amazon VPC CNI의 Pod IP를 전달 대상으로 사용하면서, 공통 Gateway와 Namespace별 HTTPRoute의 관리 권한을 나누려는 목적도 유지할 수 있습니다.
    > 

```hcl
즉, 팀·서비스 성장에 따른 관리 구조는 Gateway API로 책임과 권한을 분리하고, 
요구사항에 맞게 트래픽 처리는 ALB에게 맡기는 구조로 판단하였고, 설계하였습니다.
```
