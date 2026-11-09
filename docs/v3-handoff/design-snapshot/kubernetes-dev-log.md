> **위키 사본(스냅샷)** — 원본: [쿠버네티스-개발기록](https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/%EC%BF%A0%EB%B2%84%EB%84%A4%ED%8B%B0%EC%8A%A4-%EA%B0%9C%EB%B0%9C%EA%B8%B0%EB%A1%9D)  
> 기준: 위키 커밋 `addfeea`(2026-11-04), 복사 2026-11-09. **수정은 위키에서 하고, 바뀌면 이 사본을 다시 복사한다.**


#### 세부설정 정하면서 개발하기

## 1. Flux VS ArgoCD

| 구분 | Flux | ArgoCD |
| --- | --- | --- |
| 핵심 역할 | Git 내용을 클러스터에 자동 반영 | Git 내용을 클러스터에 자동 반영 |
| 관리 대상 | 클러스터 안의 리소스 | 클러스터 안의 리소스 |
| 화면 | 없음(CLI) | 웹 UI 기본 제공 |
| Helm 배포 | 실제 Helm으로 설치 | YAML로 펼쳐서 적용 |
| 잘 맞는 경우 | 가볍게 자동화 | 배포 상태를 화면으로 공유 |

Flux

- 화면 없이 CLI와 Git만으로 운영하는 가벼운 도구
- Helm 차트를 실제 Helm 릴리스로 설치해서 helm list와 롤백 기록이 남음
- 카나리 배포는 Flagger와 함께 쓰고, 보통 클러스터마다 하나씩 설치

Argo CD

- 웹 UI로 배포 상태와 Git과의 차이를 눈으로 확인하고 공유 가능
- Helm 차트를 YAML로 펼쳐서 적용하기 때문에 Helm 릴리스가 없음
- 카나리 배포는 Argo Rollouts와 함께 쓰고, 하나로 여러 클러스터를 중앙에서 관리

<aside>
🗣

두 도구 모두 Git을 기준으로 클러스터 상태를 지속적으로 동기화하는 GitOps 도구로 핵심 기능은 동일합니다. 

KeepGo는 다음 3가지 이유로 ArgoCD를 선택했습니다.

- kubectl을 사용하지 않는 풀스택·AI 팀원도 웹 화면에서 기능별 배포 버전과 성공 여부를 읽기 전용으로 확인할 수 있습니다.
- 단일 이미지를 기능별 Deployment로 운영하는데 각 기능과 플랫폼 에드온을 각각 Application으로 관리해 장애 위치를 화면에서 바로 구분할 수 있습니다.
- Git과 클러스터의 차이를 화면에서 확인한 뒤 적용·롤백할 수 있습니다.
    
    (설정을 단계적으로 보강하는 구축 방식에 유리하다고 생각했습니다.)
    
</aside>

## 2. Terraform으로 AWS 인프라 생성

Terraform + ArgoCD로 관리(동시에 관리 방지)

Terraform 장점

- V2가 이미 Terraform이라 기존 VPC, RDS, Redis 등의 data source를 그대로 읽어와서 VPC에 EKS 이식 가능합니다.
- 만들었다가 지우기를 반복할 수 있습니다. 예산 때문에 미리 구축이 어려운 만큼 매번 똑같이 실수없이 만들고 지우려면 테라폼밖에 생각이 나지 않았습니다.
- Karpeter 준비물이 모듈로 있습니다.
    - `terraform-aws-modules/eks`의 karpenter 서브모듈이 IAM, 중단 알림 큐, EventBridge 규칙을 한 번에 만들어 줍니다.

#### Terraform에 들어갈 리소스 정리(상태의 변경이 적은 것들)

- EKS 전용 서브넷
- EKS 클러스터, 접근 권한(access entry)
- EKS 관리형 에드온(VPC CNI, CoreDNS, kube-proxy, EBS CSI)
- Karpenter 중단 알림 SQS + EventBridge 규칙

#### 5-2에서 정하지 못한 점

- **VPC·AZ·서브넷** - 재사용할 실제 VPC · 서브넷, 사용할 AZ, 신규 EKS 서브넷 CIDR · 라우팅
- **Pod · Service IP** - IPv4·IPv6, Service CIDR, Node·Pod 서브넷 공유 여부, Prefix Delegation 설정
- **클러스너 접근 경로** - API Endpoint의 Public·Private 설정, 관리자 · 최초 설치 도구가 접근할 방법

### 2.1 VPC · AZ · 서브넷

```hcl
첫 EKS 클러스터는 신규 VPC에 dev 용으로 구축합니다. 
기존 V2 VPC에서는 ECS 부하테스트와 FIS 장애 실험을 마친 뒤,
같은 VPC에 별도의 Pord EKS 클러스터를 생성합니다.
```

https://github.com/100-hours-a-week/KTB4-8th-CLOUD/wiki/5%E2%80%904.-%EB%B0%B0%ED%8F%AC-%EC%9E%90%EB%8F%99%ED%99%94-%EB%B0%8F-%EC%A0%84%ED%99%98-%EC%A0%84%EB%9E%B5 

| 희망 시점 | 신규 VPC - dev | 기존 V2 VPC - prod |
| --- | --- | --- |
| 현재  | dev EKS 구축, 배포·노드 교체 검증 | 기존 ECS 구성으로 부하테스트·FIS 수행 |
| 운영 전환 준비 | dev에서 플랫폼 변경을 먼저 검증 | prod EKS를 추가하고 ECS와 병행하며 기존 RDS 연결 검증 |
| 전환 완료 후 | 장애 실험·업그레이드 사전 검증에 계속 사용 | prod EKS가 운영 요청을 처리하고, 복귀를 위해 정한 기간이 지나면 ECS 정리 |
- `VPC·기존 서브넷` - V2의 2개 AZ와 Public·Data 서브넷 구성을 활용합니다. EKS 노드·Pod에는 AZ별 정용 Private 서브넷을 추가해, Pod가 늘어도 기존 ECS 서비스 서브넷의 IP를 소모하지 않게 합니다.
- `RDS` - 기존 운영 데이터와 DB 주소를 유지합니다. 병행 기간에는 ECS와 EKS가 여는 DB 연결 수의 합계와 양쪽 앱 버전의 스키마 호환성을 검증합니다.
- `Terraform·배포 설정` - dev에서 검증한 EKS 모듈과 Helm 차트를 prod에도 사용하고 VPC ID, 서브넷, 권한, 용량은 환경별로 지정합니다.
- `Redis` - V2는 ElastiCache이고 V3 설계는 Redis StatefulSet과 EBS PVC입니다.

#### 서브넷 정하기

VPC에 전체 IP 주소 범위를 지정하고, 그 안에서 자원의 용도와 통신 경로에 따라 작은 주소 범위로 나눕니다. 

Public 서브넷 - ALB · NAT Gateway

EKS Private 서브넷 - 노드 · Pod

Data 서브넷 - RDS

#### CIDR : 10.47.0.0/16

| 항목 | 환경값 |
| --- | --- |
| 환경 | dev |
| 리전 | 서울 ap-northeast-2 |
| VPC CIDR | 10.47.0.0/16 |
| VPC 주소 범위 | 10.47.0.0 ~ 10.47.255.255 |
| 사용 AZ | ap-northeast-2a
ap-northeast-2c |
| 서브넷 구성 | Public 2개
EKS Private 2개
Data 2개 |

| 구분 | 명칭 | CIDR | IPv4 할당 개수 | 주요 배치 대상 |
| --- | --- | --- | --- | --- |
| Public | dev3-public-a | 10.47.0.0/24 | 251개 | ALB, NAT  |
|  | dev3-public-c | 10.47.1.0/24 | 251개 |  |
| EKS Private | dev3-eks-private-a | 10.47.32.0/20 | 4,091개 | 노드, Pod |
|  | dev3-eks-private-c | 10.47.48.0/20 | 4,091개 |  |
| Data | dev3-data-a | 10.47.20.0/24 | 251개 | RDS  |
|  | dev3-data-c | 10.47.21.0/24 | 251개 |  |

#### 라우트

- dev에서는 비용 우선적으로 NAT을 하나만 배치

| 리소스 | 이름  | 배치 |
| --- | --- | --- |
| Internet Gateway 1개 | dev3-igw | dev VPC에 연결 |
| NAT Gateway 1개 Zonal | dev3-nat-a | dev3-public-a에 배치 |
| Elastic IP | dev3-nat-eip-a | NAT Gateway에 연결 |

`Route Table 구성`

| Route Table | 연결할 서브넷 | 용도 |
| --- | --- | --- |
| dev3-public-rt | dev3-public-a, dev3-public-c | 공통 Public 경로 |
| dev3-eks-private-a-rt | dev3-eks-private-a | a영역 노드·파드용 경로 |
| dev3-eks-private-c-rt | dev3-eks-private-c | c영역 노드·파드용 경로 |
| dev3-data-rt | dev3-data-a, dev3-data-c | DB 내부 통신 |

#### VPC 기본 설정

→ DNS 사용 여부와 서브넷의 기본 동작을 정의하겠습니다.

| 설정 | 선택값 | 이유 |
| --- | --- | --- |
| IVp4 | 10.47.0.0/16 | dev 주소 공간 |
| DNS 해석 지원
`enable_dns_support` | true | AWS 제공 DNS로 RDS·ECR·외부 API 등의 이름 해석 |
| DNS 호스트명 지원
`enable_dns_hostnames` | true | EKS 및 Private DNS 사용 요건 충족 |
| DHCP의 DNS 서버 | AmazonProvidedDNS | AWS의 VPC Resolver 사용 |
| 인스턴스 전용 하드웨어 설정
`instance_tenancy` | default | 일반적인 EC2 실행 방식 사용 |
| 공인 IPv4 자동 할당
`map_public_ip_on_launch` | false | EC2가 의도치 않게 공인 IP를 받는 것을 방지 |
- **DNS 해석 지원** - AWS 제공 DNS에 이름을 물어보고 IP를 찾을 수 있도록 함
- **DNS 호스트명 지원** - EC2의 DNS 호스트명 부여와 AWS의 사설 DNS 기능 사용에 관여
- **DHCP의 DNS 설정** - EC2에 어느 DNS 서버를 사용할지 알려줌
    - **DHCP** - 기기가 사용할 네트워크 설정을 자동으로 전달하는 프로토콜

### 2.2 Pod · Service IP

```hcl
KeepGo V3의 EKS Pod·Service 주소 체계는 IPv4를 사용합니다. 
Amazon VPC CNI를 통해 일반적인 Pod에 VPC의 사설 IPv4 주소를 할당하고,
Service의 ClusterIP는 별도의 Service CIDR에서 할당합니다.
```

IPv4 선택 근거

- **충분한 주소 공간** - EKS Private 서브넷을 AZ별 /20으로 구성하면 AWS 예약 주소를 제외하고 각각 4,091개, 총 8,182개의 주소를 사용할 수 있습니다.
- **기존 환경과의 연결 단순화** - IPv4 기반의 V2 네트워크·RDS와 동일한 주소 체계를 사용하여, ECS와 EKS의 병행 운영 및 전환 과정에서 통신 경로와 접근 정책을 일관되게 관리합니다.
- **현재 요구사항에 맞는 선택** - 현재 설계 계산에서는 Pod의 IPv4 주소 부족이 확인되지 않았으므로, 초기 클러스터는 IPv4를 기준으로 구축하고 검증합니다.

`IPv4와 IPv6를 이중 스택으로 구성하면 더 좋은거 아닌가요?`

- IPv4 주소 부족 문제 완화
- 네트워크 호환성 향상
- 점진적인 IPv4 전환

이라는 장점을 가지고 있습니다. 하지만 그럼에도 현재 도입하지 않는 이유는 운영 및 관리 복잡도의 증가를 감수할 만큼의 필요성이 부족하기 때문입니다. 아직 IPv4의 의존도가 크고, 충분한 Pod IP를 확보할 수 있기 때문입니다.

→ KeepGo V3 IPv4 + Prefix Delegation 사용

| 구성 요소 | 선택사항 |
| --- | --- |
| IP Family | IPv4 |
| CNI  | Amazon VPC CNI |
| IP 할당 방식 | Prefix Delegation /28 |
| EC2 | Nitro 기반 |
| Node | EKS Managed Node Group |
| Warm Pool | `WARM_PREFIX_TARGET=1` |

```hcl
서브넷에 IP가 4000개가 있다면 Prefix를 사용해도 총 IP주소의 개수는 같습니다.
그럼에도 Prefix를 사용하는 이유는, ENI의 한계를 넘어서 Pod용 개별 IP수를 늘리고,
여유 warm pool을 확보해서 빠른 확장이 가능하도록 설계하였기 때문입니다.
```

#### Service

- Service - 변경되는 Pod IP 대신 안정적인 접근 경로를 제공하는 Kubernetes 리소스
- Service CIDR - Kubernetes Service의 가상 IP인 ClousterIP를 할당하는 주소 범위
- ClusterIP - 클러스터 내부에서 Service에 접근할 때 사용하는 가상 IP

`고려사항`

- 주소 중복 - 현재 VPC뿐 아니라 연결할 다른 VPC·VPN·사내망과도 겹치지 않아야 함
- EKS 허용 범위 - IPv4 사설 대역 안에서 /24 ~ /12 크기로 지정
- Service 개수 - Pod 수가 아니라 ClusterIP가 필요한 Service 개수를 고려
- 변경 가능 여부 - EKS에서는 클러스터 생성 후 Service CIDR 변경 불가

| 항목 | 설정 |
| --- | --- |
| Service CIDR | 10.96.0.0/16 |
| 주소 범위 | 10.96.0.0 ~ 10.96.255.255 |
| 적용 범위 | dev 클러스터 전체 
모든 Namespace가 공유 |
| 용도 | Service의 ClusterIP 할당 |

### 2.3 클러스터 접근 경로

> ClusterIP는 만들어진 서비스를 사용하기 위한 주소이고, EKS API Endpoint는 그 서비스를 포함한 Kubernetes 리소스를 만들고 관리하기 위한 접근 경로
> 

→ 관리자를 위한 설정(kubectl, eksctl)

- `kubectl` - Kubernetes 리소스 관리 - Pod, Deployment, Service
- `eksctl`- AWS EKS 클러스터 구축 및 관리 - EKS 클러스터, 노드 그룹
1. Endpoint 설정 : Kubernetes API를 Public·Private 중 어디에서 접근 가능하게 할지 결정하겠습니다.
    
    
    | 설정 | 외부 관리자 접근 | VPC 내부 노드 접근 |
    | --- | --- | --- |
    | Public만 활성화 | Public Endpoint | Public Endpoint |
    | Public + Private | Public Endpoint 또는
    연결된 사설 경로 | Private Endpoint |
    | Private만 활성화 | VPC 내부 또는 
    연결된 네트워크에서만 가능 | Private Endpoint |
- 관리 API의 Public 접근을 반드시 금지해야하나요?
    
    A. dev 구축 과정에서는 관리자 PC의 직접 접근이 필요합니다.
    
    → Public Endpoint 활성화
    
- 노드의 API 통신은 NAT 장애와 독립적으로 유지해야 하나요?
    
    A. NAT 장애가 발생해도 노드가 k8s API에 상태를 보고하고 명령을 받을 수 있어야 합니다.
    
    → Private Endpoint 활성화
    
- 관리자 PC에서 kubectl·Helm을 직접 실행해야 하나요?
    
    A. 초기 구축과 장애 확인을 위해 관리자가 로컬 PC에서 kubectl·Helm을 실행하고 싶습니다.
    
    → 관리자 PC에서 Public Endpoint로 접근
    
- Public Endpoint를 모든 IP에 개방해야 하나요?
    
    A. 관리 API는 일반 사용자가 아닌 지정된 관리자만 접근해야 합니다.
    
    → 관리자 출구 공인 IP만 허용
    
- 관리자의 접속 장소에 따라 공인 IP가 바뀔 수 있나요?
    
    A. 본가·교육장 등 접속 장소나 네트워크 변경으로 자주 바뀝니다.
    
    → IP 변경 시 Terraform의 허용 CIDR을 갱신
    

`결론`

> Piblic·Private Endpoint를 함께 활성화합니다. 노드는 Private Endpoint를 사용하고, 관리자는 허용된 공인 IP에서 Public Endpoint로 접근합니다. 

이를 통해 별도의 VPN·관리용 EC2 없이 초기 구축과 운영 확인을 진행합니다.
> 

#### 네트워크 테라폼 작성

```hcl
폴더 구성
dev3-Terraform/
-> settings.tf # Terrafrom·AWS Provider 버전, 계정, 리전, 공통 태그
-> network.tf # VPC, 서브넷, IGW, NAT Gateway, 라우팅
-> outputs.tf # VPC·서브넷·라우팅 테이블 ID와 NAT 공인 IP 출력
```

- V3에서는 각 리소스를 코드와 바로 대조할 수 있도록 `for_each`없이 리소스 선언을 하였습니다.

## 3. EKS 클러스터 및 기본 실행 환경 구축

### 3.1 EKS Cluster IAM Role 생성

> EKS가 클러스터 운영에 필요한 AWS 작업을 수행하도록 사용하는 IAM Role입니다. 사람이 kubectl로 접근할 때 사용하는 역할과 구분합니다.
> 

→ 5-2 RBAC를 기반으로 작성합니다

| Role 이름 | Keepgo-dev3-eks-clusterRole |
| --- | --- |
| 신뢰할 서비스 | eks.amazonaws.com |
| 연결할 IAM 정책 | AmazonEKSClusterPolicy |
| 사용 시점 | EKS 클러스터 생성 시 Cluster IAM Role로 지정 |

`AmazonEKSClusterPolicy`

- EKS Contorl Plane이 클러스터 운영에 필요한 AWS 리소스 조회/관리 작업을 수행하도록 허용하는 AWS 관리형 IAM 정책

!image.png

#### 운영자 접근 권한 - IAM + Kubernetes RBAC

> 5-2에서 결정한 대로 EKS Access Policy를 연결하지 않고, IAM Role과 Kubernetes RBAC를 조합합니다.
> 

| Role 이름 | keepgo-dev3-platform-operator |
| --- | --- |
| 사용하는 주체  | 클라우드 담당팀 |
| 신뢰 대상 | 담당자의 IAM |
| AWS 권한 | 대상 EKS의 eks:DescribeCluster |

→ Deployment나 NodePool 등을 수정할 권한은 이후 RBAC에서 부여

- 추가공부
    
    #### 대답못한 질문
    
    1. KEDA는 Pod 제한이 가능한데 HPA는 그걸 못하는가?
        
        <aside>
        🗣
        
        HPA도 역시 min과 max레플리카를 통해 제한이 가능합니다. 하지만 제한 기준에 있어서 차이가 있습니다. HPA는 CPU, 메모리 기반이고 KEDA는 메시지, Kafka라면 Lag 등 이벤트 기반으로 작동합니다.
        
        </aside>
        
    2. etcd 컨센서스(Consensus)는 어떤 식으로 이루어지는가?
        
        `etcd의 역할`
        
        | Member | etcd 클러스터를 구성하는 서버 하나 |
        | --- | --- |
        | Leader | 쓰기 요청을 조정하고 다른 서버에 로그를 복제하는 대표 서버 |
        | Follower | Leader로부터 로그를 전달받아 저장하는 서버 |
        | Candidate | 새로운 Leader가 되기 위해 투표를 요청하는 서버 |
        
        `합의와 선거`
        
        | Consensus | 여러 서버가 동일한 데이터 상태에 합의하는 과정 |
        | --- | --- |
        | Raft | Leader 선출과 로그 복제를 통해 합의를 달성하는 알고리즘 |
        | Quorum | 합의를 진행하는 데 필요한 최소 과반수 |
        | Term | Leaser 선거의 시기를 구분하는 증가하는 번호 |
        | Hearbeat | Leader가 정상적으로 활동 중임을 알리는 주기적인 메시지 |
        | Election Timeout | Leader의 메시지를 기다리는 제한 시간 |
        
        `Raft의 합의 5단계`
        
        - Leader Election - 리더 선출
            
            Candidate는 새로운 Term을 시작하고 자신에게 우선 투표 후, 다른 서버에게 투표 요청을 전달
            
        - Proposal - 변경 요청 접수
            
            Leader가 데이터 변경 요청을 받아 로그 생성
            
        - Log Replication - 로그 복제
            
            Leader가 Follower들에게 변경 로그 전송
            
        - Quorum & Commit - 과반수 확인 및 확정
            
            과반수에 로그가 복제되면 커밋 조건 충족
            
        - Apply - 데이터 반영
            
            확정된 로그를 각 서버의 데이터 저장소에 적용
            
    
    #### 설정할때 필요한 것
    
    1. EKS, EKS-A, EKS-D
    
    `EKS - Elastic Kubernetes Service`
    
    AWS가 Control Plane을 관리하는 Kubernetes 서비스
    
    `EKS-A - EKS Anywhere` 
    
    온프레미스에서 Kubernetes를 쉽게 구축·관리하는 도구
    
    `EKS-D - EKS Distro`
    
    AWS가 검증하고 배포하는 Kubernetes 구성요소 묶음
    
    `왜 필요할까?`
    
    어떤 회사가 보안 정책 때문에 자체 데이터센터에서 Kubernetes를 운영해야한다.
    
    방법 1. EKS-D 활용
    
    AWS가 검증한 Kubernetes 구성요소를 사용하지만, 설치·업그레이드·운영 자동화는 직접 구성
    
    방법 2. EKS-A 활용
    
    EKS-D를 기반으로 Kubernetes 클러스터를 구축하면서 설치와 수명주기 관리 도구까지 사용할 수 있다. 다만 Control Plane을 포함한 클러스터 운영 책임은 사용자에게 있다.
    
    → GUI에만 있고 테라폼은 신경 X