```hcl
A안은 주로 상태가 적게 변하는 리소스입니다.
네트워크, Node, AWS 리소스, 데이터 관리를 진행합니다.
업무 분담을 위해서 A, B로 나누어서 진행하기로 했습니다.
```

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

#### EKS 클러스터 생성

**① 기본 구성**

| 항목 | 실제 선택값 |
| --- | --- |
| AWS 계정 | `602601433533` |
| 리전 | 서울 `ap-northeast-2` |
| 구성 방식 | 사용자 지정 구성 / Standard EKS |
| EKS Auto Mode | **끔** |
| 클러스터 이름 | **`keepgo-dev3-eks`** |
| Kubernetes 버전 | **`1.37`** |
| Cluster IAM Role | `keepgo-dev3-eks-clusterRole` |
| 정책 업그레이드 | **표준 지원** |
| 스케일링 티어 | 상위 티어 사용 안 함 — 기본 `standard` |
| 컨트롤 플레인 구성 | 사용자 지정 없음 — 기본 설정 |
| ARC 영역 전환 | **비활성화** |
| 삭제 방지 | **끔** |

**② 접근·암호화**

| 항목 | 실제 선택값 |
| --- | --- |
| 부트스트랩 관리자 액세스 | **허용** |
| 초기 관리자 주체 | 해당 AWS 계정의 **root** |
| 초기 관리자 정책 | `AmazonEKSClusterAdminPolicy` — 클러스터 범위 |
| 클러스터 인증 모드 | **EKS API** |
| 자체 AWS KMS 키 사용 | **끔** — AWS 소유 키로 기본 암호화 |

초기 관리자 정책은 운영자 IAM Role·RBAC 연결과 검증을 마친 뒤 해제합니다.

**③ 네트워킹**

| 항목 | 실제 선택값 |
| --- | --- |
| VPC | `dev3-vpc` — `vpc-073c4aa25564d2725` |
| VPC CIDR | `10.47.0.0/16` |
| 추가 보안 그룹 | **선택하지 않음** |
| IP 주소 패밀리 | **IPv4** |
| 서비스 IP 주소 블록 구성 | **켬** |
| Service CIDR | **`10.96.0.0/16`** |
| Gateway API CRD 자동 관리 | 미구성 |
| 하이브리드 노드 원격 네트워크 | 미구성 |
| 엔드포인트 액세스 | **퍼블릭 및 프라이빗** |
| Public 접근 허용 CIDR | **`0.0.0.0/0` — 보완 필요** |
| 컨트롤 플레인 송신 | **AWS 관리형** |

| 선택한 서브넷 | ID | AZ | CIDR |
| --- | --- | --- | --- |
| `dev3-eks-private-a` | `subnet-06e87d59eae0e2be5` | `ap-northeast-2a` | `10.47.32.0/20` |
| `dev3-eks-private-c` | `subnet-0ccd4b4871d48eebb` | `ap-northeast-2c` | `10.47.48.0/20` |

VPC·서브넷을 재생성하면 ID는 달라지므로, 다음 구축에서는 동일 용도의 새 리소스를 선택합니다.

**④ 관측 설정**

| 항목 | 실제 구성 |
| --- | --- |
| 관리형 Prometheus 수집 | 미구성 — scraper 없음 |
| CloudWatch Observability Add-on | 미설치 |
| 컨테이너 네트워크 관측 Add-on | 미설치 |
| API 서버 로그 | **켬** |
| 감사 로그 | **켬** |
| Authenticator 로그 | **켬** |
| 컨트롤러 관리자 로그 | **끔** |
| 스케줄러 로그 | **끔** |

**⑤ 추가 기능 — 실제 선택한 7개**

| 추가 기능 | 버전 |
| --- | --- |
| Amazon VPC CNI | `v1.22.4-eksbuild.10` |
| CoreDNS | `v1.14.7-eksbuild.22` |
| kube-proxy | `v1.37.0-eksbuild.32` |
| EKS Pod Identity Agent | `v1.4.1-eksbuild.3` |
| Metrics Server | `v0.9.0-eksbuild.14` |
| Node Monitoring Agent | `v1.7.6-eksbuild.1` |
| External DNS | `v0.24.0-eksbuild.1` |

**⑥ 태그**

| 키 | 실제 값 |
| --- | --- |
| `Name` | `keepgo-dev3-eks` |

현재 클러스터에는 **Name 태그만 등록**되어 있습니다.

#### 운영자 접근 권한 - IAM + Kubernetes RBAC

> 5-2에서 결정한 대로 EKS Access Policy를 연결하지 않고, IAM Role과 Kubernetes RBAC를 조합합니다.
>

| Role 이름 | keepgo-dev3-platform-operator |
| --- | --- |
| 사용하는 주체  | 클라우드 담당팀 |
| 신뢰 대상 | 담당자의 IAM |
| AWS 권한 | 대상 EKS의 eks:DescribeCluster |

#### System 노드가 사용할 IAM Role 생성

!image.png

#### VPC CNI 전용 IAM Role 생성

!image.png

#### Pod Identity 연결 생성

!image.png

!image.png

#### Prefix Delegation 설정

!image.png

## 4. System Managed Node Group 생성

- System Managed Node Group은 클러스터 공통 컴포넌트를 실행하기 위한 EC2 노드 그룹입니다. EKS가 노드의 생성·클러스터 등록·업데이트를 관리하고, 사용자는 인스턴스 사양·노드 수·배치할 서브넷을 지정합니다.

`5-2, 5-3 설계구조 기반`

```yaml
Control Plane(EKS) - API 서버, etcd
Fargate - Karpenter 컨트롤러
System MNG - CoreDNS, Metrics Server, KEDA, LB Controller, ESO, ArgoCD
Karpenter 노드 - 앱 Pod, Worker Pod
```

### 4.1 System 노드

- System 노드는 2개 AZ에 최소 1대씩 배치합니다. 가용성과 초기 구축의 비용을 생각합니다
- AZ별 노드 수를 명확히 유지하기 위해 각 AZ에 Managed Node Group을 하나씩 구성합니다

| 항목 | 구성 명시 |
| --- | --- |
| 목적 | prod 시스템 노드 운영 구성의 사전 검증 및 dev 구축 |
| 노드그룹 | `keepgo-dev3-system-a`, `keepgo-dev3-system-c` |
| 배치 | AZ-a·AZ-c의 EKS Private 서브넷 |
| 기본 노드 수  | AZ별 1대, 총 2대 |
| 그룹별 크기 | Desired 1 / Minimum 1 / Maximum 2 |
| 용량 유형 | On-Demand |
| Node IAM Role  | keepgo-dev3-system-node-role |
| AMI → 도커 이미지 느낌 | EKS 최적화 Amazon Linux 2023 / x86_64 Standard |
| 노드 자동 복구 | 당연히 활성화 |
| 인스턴스 사양 | 시스템 Pod의 자원 요구량과 장애 시 필요 용량을 계산해 선정 |
| 배치 전략 | 시스템 노드 레이블과 컴포넌트별 AZ 분산 규칙 적용 |

#### 시스템 노드에서 실행할 공통 컴포넌트

| 컴포넌트 |  |
| --- | --- |
| CoreDNS | 클러스터 내부에서 Service 이름을 IP로 변환 |
| Metrics Server | 노드·Pod의 CPU와 메모리 사용량 제공. HPA와 kubectl top에서 사용 |
| KEDA | 큐 길이·처리량 등 이벤트 지표에 따라 Pod 수 조절 |
| AWS Load Balancer Controller | Gateway API 등의 설정을 읽고 ALB와 대상 그룹 구성·관리 |
| External Secrets Operator(ESO) | AWS Secrets Manager 등의 값을 Kubernetes Secret으로 동기화 |
| ArgoCD | Git에 선언한 배포 설정과 실제 클러스터 상태를 동기화 |
| ExternalDNS | 서비스 공개 주소에 맞춰 Route 53 등의 DNS 레코드 관리 |
| EBS CSI Controller | PVC 요청에 따라 EBS 볼륨 생성·연결 등을 조정 |
| Prometheus | 클러스터와 애플리케이션의 지표 수집·저장 |
| Grafana | 수집한 지표를 대시보드로 시각화 |

#### 일단 워커 노드에서 실행되는 컴포넌트

| 컴포넌트 |  |
| --- | --- |
| Amazon VPC CNI | Pod의 VPC IP 할당과 네트워크 연결 처리 |
| kube-proxy | Service의 가상 IP로 들어온 트래픽이 Pod에 전달되도록 규칙 관리 |
| EKS Pod Identity Agent | Pod가 사용할 IAM 임시 자격증명 전달 |
| EBS CSI Node | 노드에 연결된 EBS 볼륨을 Pod가 사용하도록 마운트 |
| Node Monitoring Agent | 노드의 상태 이상을 감지하고 보고 |
| 로그·지표 수집 Agent | 노드·컨테이너의 로그와 지표 수집 |

#### 노드 인스턴스 사양을 위한 자원 산정

→ 후에 실측 진행(카오스 엔지니어링)

|  | AZ-a | AZ-c |
| --- | --- | --- |
| 인스턴스 | t3.medium | t3.medium |
| 전체 CPU | 2,000m | 2,000m |
| 전체 메모리 | 4,096 MiB | 4,096 MiB |
| 계산용 시스템 예약 | 100m / 1,024 MiB | 100m / 1,024 MiB |
| Pod Requests 합계 | 1,350m / 2,758 MiB | 1,700m / 2,758 MiB |
| 남는 계산상 여유 | 550m / 314 MiB | 200m / 314 MiB |
- 예상 수치


    | 컴포넌트 | CPU | 메모리 |
    | --- | --- | --- |
    | CoreDNS | 100m | 70 MiB |
    | AWS Load Balancer Controller | 100m | 128 MiB |
    | EBS CSI Controller | 100m | 256 MiB |
    | Amazon VPC CNI | 100m | 128 MiB |
    | kube-proxy | 100m | 64 MiB |
    | Pod Identity Agent | 25m | 64 MiB |
    | EBS CSI Node | 50m | 128 MiB |
    | Node Monitoring Agent | 50m | 64 MiB |
    | 로그·지표 수집 Agent | 25m | 64 MiB |
    | **노드 한 대당 소계** | **650m** | **966 MiB** |
    
    | 컴포넌트의 Pod | CPU | 메모리 | 배치 예시 |
    | --- | --- | --- | --- |
    | Metrics Server | 100m | 128 MiB | AZ-c |
    | KEDA Operator | 100m | 128 MiB | AZ-a |
    | KEDA Metrics API Server | 50m | 64 MiB | AZ-a |
    | KEDA Webhook | 50m | 64 MiB | AZ-a |
    | ESO Controller | 100m | 128 MiB | AZ-c |
    | ESO Webhook | 25m | 32 MiB | AZ-c |
    | ESO Cert Controller | 25m | 32 MiB | AZ-c |
    | Argo CD Application Controller | 250m | 384 MiB | AZ-c |
    | Argo CD Repo Server | 100m | 256 MiB | AZ-a |
    | Argo CD Server | 50m | 128 MiB | AZ-c |
    | Argo CD 내부 Redis | 50m | 128 MiB | AZ-a |
    | Argo CD Dex | 100m | 128 MiB | AZ-c |
    | Argo CD ApplicationSet Controller | 100m | 128 MiB | AZ-c |
    | Argo CD Notifications Controller | 50m | 128 MiB | AZ-c |
    | ExternalDNS | 50m | 64 MiB | AZ-c |
    | Prometheus | 300m | 1,024 MiB | AZ-a |
    | Grafana | 100m | 256 MiB | AZ-c |
    | Prometheus Operator | 50m | 128 MiB | AZ-a |
    | kube-state-metrics | 50m | 128 MiB | AZ-c |
    | Alertmanager | 50m | 128 MiB | AZ-c |

> System 노드는 AZ별 t3.medium 1대씩, 총 2대로 구성합니다. 초기 예상 자원을 기준으로 구축한 뒤, 컴포넌트를 단계적으로 설치하며 실제 사용량을 측정합니다. 자원 부족이 확인되면 Requests·Limits 조정 또는 인스턴스 사양 상향을 진행합니다.
>

#### 노드 Label

> Node Label은 노드의 용도나 특성을 나타내는 Key: Value 형태의 정보입니다. Pod는 nodeSelector 또는 Node Affinity로 이 Label을 참조하여 실행할 노드를 선택합니다.
>

| 노드 그룹 | AZ | Key | Value |
| --- | --- | --- | --- |
| keepgo-dev3-system-a | ap-northeast-2a | workload | system |
| keepgo-dev3-system-c | ap-northeast-2c | workload | system |

`적용 근거`

- CoreDNS·ArgoCD·KEDA 등의 공통 컴포넌트가 System 노드를 선택하도록 합니다
- 개별 노드 이름 대신 용도를 참조하여, 노드가 교체돼도 동일한 배치 기준을 유지합니다
- 두 AZ에 동일한 Label을 적용하여, 특정 AZ에 고정하지 않고 System 노드 중에서 배치하도록 합니다

#### Taint·Toleration

> Taint는 노드에 적용하는 Pod 배치 제한 조건입니다. 해당 조건을 허용하는 Toleration이 없는 Pod는 그 노드에 새로 배치되지 않도록 설정할 수 있습니다.
>

| 노드 그룹 | key | Value | Effect |
| --- | --- | --- | --- |
| keepgo-dev3-system-a | workload | system | NoSchedule |
| keepgo-dev3-system-c | workload | system | NoSchedule |

`적용 근거`

- 일반 앱·분석 Worker가 System 노드의 CPU·메모리를 사용하는 것을 제한합니다.
- 시스템 컴포넌트에만 대응하는 Toleration을 부여하여 배치를 허용합니다.
- NoSchedule은 허용되지 않는 Pod의 신규 배치를 차단하며, 이미 실행 중인 Pod를 강제로 퇴거시키지는 않습니다.

```yaml
tolerations:
	- key: workload
		operator: Equal
		value: system
		effect: NoSchedule
```

→ Taint는 노드에, 이를 허용하는 Toleration은 Pod에 설정

| 이름 | 새로 들어오는 Pod | 이미 실행 중인 Pod |
| --- | --- | --- |
| NoSchedule | 일치하는 Toleration이 없으면 배치 차단 | 그대로 실행 |
| PreferNoSchedule | Toleration이 없으면 가급적 배치하지 않지만, 필요하면 배치 가능 | 그대로 실행 |
| NoExecute | Toleration이 없으면 배치 차단 | Toleration이 없으면 퇴거. 허용 시간을 지정해 지연 가능 |

`라벨이랑 세트인가요? 같이 쓰는데요?`

<aside>
🗣

- Labe + nodeSelector만 사용 : 시스템 Pod를 시스템 노드로 보내지만, 일반 앱도 그 노드에 들어올 수 있음.
- Taint + Toleration만 사용 : 일반 앱의 진입은 막지만, 시스템 Pod가 다른 노드에 배치될 수도 있음.
- 둘다 사용 : 시스템 Pod의 목적지를 지정하면서, 일반 앱의 진입도 제한
</aside>

#### 루트디스크

> 루트디스크 먼저 정리
>

`루트 디스크(Root Disk)` - 서버의 운영체제(os)가 설치되어 있고, 서버가 부팅하고 동작하는 데 필요한 파일들이 저장되는 기본 디스크

- EKS Worker Node에서는 kubernetes 실행 데이터, 컨테이너 이미지, 로그, 임시 파일 등도 루트 디스크 사용

| 항목 | Root EBS | PVC용 EBS |
| --- | --- | --- |
| 주된 목적 | OS 및 노드 실행 | Pod 영구 데이터 저장 |
| 생성 시점 | EC2 생성 시  | PVC 요청에 따라 |
| 관리 방식 | EC2·Node Group | Kubernetes + EBS CSI |
| 생명주기  | EC2 설정에 의존 | PV Reclaim Policy 등에 의존 |

| 저장 내용 | 저장 위치 |
| --- | --- |
| Redis 컨테이너 이미지 |  노드 루트 디스크 |
| Redis가 보존할 데이터 | Redis용 PVC |
| Prometheus 컨테이너 이미지 | 노드 루트 디스크 |
| Prometheus가 보존할 시계열 데이터 | Prometheus용 PVC |

`결론`

> System 노드의 루트 디스크는 노드당 30GiB로 구성합니다. OS·컨테이너 이미지·임시 파일·로컬 로그를 저장하며, 애플리케이션의 영속 데이터는 별도 PVC로 분리합니다. 구축 후 디스크 사용량과 DiskPressure 발생 여부를 확인해 용량을 조정합니다.
>

#### 노드 접근 방식

| 점검 대상 | 접근 방식 |
| --- | --- |
| Pod 상태·이벤트·컨테이너 로그 | 운영자 IAM Role + Kubernetes RBAC로 kubectl 사용 |
| kubelet·containerd·노드 디스크·OS 로그 | SSM Session Manager로 해당 EC2에 접속 |

`선택 근거`

| 항목 | 적용 방향 |
| --- | --- |
| 노드 OS 접속 | SSM Session Manager |
| 노드 그룹의 SSH 원격 접속 | 비활성화 |
| SSH용 키 페어 | 미지정 |
| SSH용 22번 인바운드 | 추가하지 않음 |
| 노드 공인 IP | 할당하지 않음 |
| 별도 관리용 EC2 | 구성하지 않음 |
| 노드의 SSM 연결 경로 | 기존 NAT Gateway를 통한 HTTPS 통신 |

RBAC → 기존 설정은 유지하지만 SSM을 통한 OS 접속 권한은 IAM에서 관리

`구축 후 확인할것`

1. 노드의 SSM Agent 설치·실행 상태 확인
2. Systems Manager에서 두 노드가 관리 대상으로 표시되는지 확인
3. 운영자 Role로 각 노드의 세션 접속/종료 검증
4. kubelet으로 로그와 디스크 사용량 조회

#### 노드 업데이트 정책

```yaml
여기서 노드 업데이트란 새로운 AMI로 교체와 다음 버전 교체를 모두 뜻한다.
```

`Karpenter Drift`

<aside>
🗣

Karpenter Drift는 현재 실행 중인 EC2 Worker Node의 설정이 NodePool·EC2NodeClass에 선언된 최신 설정과 달라졌을 때, 이를 감지하고 새로운 설정의 노드로 교체하는 기능

</aside>

→ 결국 어떤 식으로 무중단을 보장하면서 노드라는 서버를 교체할건지?

`PDB`

<aside>
🗣

PDB는 노드 유지보수나 교체처럼 계획된 작업으로 Pod를 중단시킬 때, 최소한 몇 개의 Pod가 정상적으로 실행되어야 하는지 정하는 Kubernetes 리소스

</aside>

Voluntary Disruption - 계획된 중단

Involuntary Disruption - 예기치 못한 중단

minAvailable - 최소 몇 개가 살아 있어야 할까?

maxUnavailable - 최대 몇 개가 중단되어도 될까?

- kubectl drain : 일반적으로 Eviction API를 사용하므로 PDB를 준수
- kubectl delete pod : 직접 삭제하는 작업이므로 PDB의 축출 제한을 우회

`Kubetnetes Eviction API`

> Eviction API는 Kubetnetes API server에 특정 Pod를 축출(Evict)해 달라고 요청하는 API로, PDB와 종료 유예 시간등을 고려하여 Pod를 정상적으로 종료하도록 처리하는 기능
>

`topologySpreadConstraints`

> Kubernetes에서 새로운 Pod를 스케줄링할 때, 동일한 워크로드에 속하는 Pod들이 여러 노드 또는 가용영역(AZ)에 얼마나 균등하게 분산되어야 하는지를 정의하는 스케줄링 제약 조건
>

`초기 계획`

1. 복제본·분산 규칙·PDB 준비
2. 정상 배치와 서비스 동작 확인
3. AMI 변경
4. 교체 조건 확인 및 필요 시 대체 노드 준비
5. 기존 Pod 퇴거·재생성
6. 기존 노드 종료 및 서비스 검증

→ `하지만 시스템노드는 EKS Managed Node Group에 교체를 담당…!`

→ `후에 워커 노드에서 자세하게 세팅`

|  | Default | Minimal |
| --- | --- | --- |
| 순서 | 새 노드 생성 → 기존 노드 종료 | 기존 노드 종료 → 새 노드 생성 |
| 일시적인 노드 증가 | 발생 가능 | 교체를 위한 증설을 피함 |
| 교체 중 용량 | 새 용량을 먼저 확보 | 기존 용량이 먼저 감소 |
| 주로 고려하는 상황 | 일반적인 운영 노드 교체 | GPU 등 추가 용량·비용 제약이 큰 환경 |

무조건 Default가 강제됩니다.

→ 그룹마다 노드를 1대로 설정했기 때문에 Minimal로 해당 노드를 먼저 종료하면 그 그룹에 실행 가능한 노드가 없는 구간이 발생

`Rolling Update` - PDB를 준수하며 퇴거. 조건을 만족하지 못하면 실패 가능

> CoreDNS·LBC 등 시스템 Pod의 가용성을 보호하며 교체할 수 있습니다. 다만 AZ별 기본 노드가 1대이므로, 새 노드의 준비 상태·Pod 재배치 가능 용량·PDB 조건에 따라 업데이트가 지연되거나 중단될 수 있습니다.
>

`Force update` - PDB 문제로 퇴거하지 못해도 강제로 교체 진행

> PDB로 막힌 업데이트를 진행할 수 있지만, 시스템 Pod의 최소 가용 수를 보장하지 못할 수 있습니다. 당시 복제본과 배치 상태에 따라 DNS 응답이나 배포·확장 제어가 일시적으로 중단될 수 있습니다.
>

| 노드 교체 전략 | Default |
| --- | --- |
| Pod 퇴거 처리 | Rolling update |
| 최대 동시 사용 불가 | 그룹별 1대 |
| 그룹 간 진행 | system-a 검증 후 systme-c |
| 업데이트 실행 시점 | 운영자가 대상 버전 확인 후 실행 |
| 사전준비 | 복제본·AZ 분산·PDB·여유 용량 확인 |

`요약본 만들기`

| 노드 그룹 | keepgo-dev3-system-a, keepgo-dev3-system-c |
| --- | --- |
| 서브넷 | 각 AZ의 EKS Private 서브넷 하나씩 |
| 인스턴스 | 각각 t3.medium |
| 용량 유형 | On-Demand |
| 그룹별 노드 수 | Desired 1 / Minimum 1 / Maximum 2 |
| AMI | EKS 최적화 AL2023 / x86_64 Standard |
| Node IAM Role | keepgo-dev3-system-node-role |
| 루트 디스크 | 노드당 30 GiB |
| Label | workload=system |
| Taint | workload=system:NoSchedule |
| 노드 자동 복구 | 활성화 |
| OS 접속 | SSM Session Manager, SSH 비활성화 |
| 업데이트 | Default + Rolling update |
| 최대 동시 사용 불가 | 그룹별 1대 |
| 업데이트 순서 | system-a 검증 후 system-c |

## 5. GUI 구축

1. 기본 IAM 준비
  - EKS 클러스터 역할
  - 클라우드 운영자 역할
  - System 노드 역할
  - VPC CNI 역할
2. EKS 클러스터 생성
  - 운영자 Access Entry → Kubernetes RBAC 연결
  - Pod Identity Agent·CNI 역할 연결
3. System Managed Node Group 생성
4. Karpenter용 IAM 준비·설치
  - Fargate 실행 역할
  - Karpenter Controller 역할
  - Karpenter가 생성할 EC2 노드 역할
5. 공통 도구·앱 설치 시 전용 IAM 추가
  - LBC·EBS·CSI·시크릿·DNS·큐·관측

#### 5.1 기본 IAM 준비

!image.png

| 역할 이름 | 사용하는 주체·신뢰 대상 | 연결할 권한 | 연결할 위치 |
| --- | --- | --- | --- |
| `keepgo-dev3-eks-clusterRole` | EKS 서비스 — `eks.amazonaws.com` | `AmazonEKSClusterPolicy` | 클러스터 생성 화면 |
| `keepgo-dev3-platform-operator` | 클라우드 담당자의 IAM 주체 | 대상 클러스터의 `eks:DescribeCluster` | Access Entry와 RBAC |
| `keepgo-dev3-system-node-role` | System EC2 — `ec2.amazonaws.com` | `AmazonEKSWorkerNodePolicy` + `AmazonEC2ContainerRegistryPullOnly` + `AmazonSSMManagedInstanceCore` | System 노드그룹 2개에서 공통 사용 |
| `keepgo-dev3-vpc-cni-role` | Pod Identity — `pods.eks.amazonaws.com` | `AmazonEKS_CNI_Policy` | `kube-system/aws-node`에 Pod Identity 연결 |

#### 네트워크 세팅

!image.png

#### 5.2 EKS 클러스터 생성

!image.png

!image.png

!image.png

!image.png

!image.png

!image.png

#### 노드 그룹 설정

`AWS VPC CNI`

```yaml
{
  "env": {
    "ENABLE_PREFIX_DELEGATION": "true",
    "WARM_PREFIX_TARGET": "1"
  }
}
```

- `ENABLE_PREFIX_DELEGATION: “true”` - ENI에 개별 IP 대신 /28 Prefix를 할당하도록 활성화
- `WARM_PREFIX_TARGET: “1”` - Pod 확장에 대비해 사용하지 않는 Prefix 1개를 여유분으로 유지

#### CoreDNS - System 노드에 실행되도록 배치 설정하는 단계

```yaml
{
  "replicaCount": 2,
  "nodeSelector": {
    "workload": "system"
  },
  "tolerations": [
    {
      "key": "CriticalAddonsOnly",
      "operator": "Exists"
    },
    {
      "key": "node-role.kubernetes.io/control-plane",
      "effect": "NoSchedule"
    },
    {
      "key": "workload",
      "operator": "Equal",
      "value": "system",
      "effect": "NoSchedule"
    }
  ]
}
```

| replicaCount: 2 | CoreDNS Pod를 2개 실행 |
| --- | --- |
| nodeSelector | workload=system Label이 있는 노드에 배치 |
| 마지막 tolerations | System 노드의 workload=system:NoSchedule Taint를 허용 |
| 앞의 2개의 tolerations | 현재 애드온의 기본 설정을 보존 |

!image.png

!image.png

`EKS Pod Identity`

> Kubetnetes의 Pod가 AWS 서비스에 접근할 때, 해당 Pod에 필요한 IAM Role을 부여할 수 있도록 하는 AWS의 인증 기능
정확히는 Kubernetes ServiceAccount와 AWS IAM Role을 연결해 Pod가 AWS 권한을 사용할 수 있도록 해주는 기능
>

포드랑 파드가 같은 말이었음…

!image.png

`해석하기`

| 파드/포드(Pod) | 8개, 실행 중 100% | 실제 컨테이너를 실행하는 단위가 8개 있음 |
| --- | --- | --- |
| DaemonSets | 3개, 실행 중 100% | 대상 노드마다 Pod를 실행하도록 관리하는 리소스가 3개 있음 |
| 배포(Deployment) | 1개, 실행 중 100% | Pod 복제본과 배포 버전을 관리하는 리소스가 1개 있음 |
| ReplicaSet | 2개, 실행 중 100% | 지정된 Pod 개수를 유지하는 리소스가 2개 있음 |
| StatefulSet | 없음 | Redis처럼 고정된 이름·저장소가 필요한 워크로드는 아직 없음 |
| 작업(Job) | 없음 | 실행 후 완료되는 일회성 작업은 아직 없음 |

#### Karpenter Controller가 실행될 Fargate 환경 만들기

Fargate Profile 생성 - 어떤 Pod를 어느 서브넷의 Fargate에서 실행할지

!image.png

Karpenter를 Fargate에서 실행하므로 IRSA를 사용. EKS Pod Identity는 현재 Fargate Pod를 지원하지 않음.

!image.png

Karpenter가 생성할 EC2 노드용 IAM Role

!image.png

| `AmazonEKSWorkerNodePolicy` | 노드 운영에 필요한 AWS 조회 및 Pod Identity Agent 권한 |
| --- | --- |
| `AmazonEC2ContainerRegistryPullOnly` | ECR에서 컨테이너 이미지 다운로드 |
| `AmazonSSMManagedInstanceCore` | SSH 포트를 열지 않고 SSM으로 노드 관리 |

`Access Entry - IAM 역할을 사용하는 EC2가 이 EKS 클러스터에 노드로 참여할 수 있도록 등록`

!image.png

### 6. SQS + EventBridge

`이거 왜 사용하나요…?`

```yaml
Spot 회수와 EC2 유지보수 등의 이벤트를 Karpenter에 전달하기 위해 
EventBridge와 전용 SQS 큐로 중단 알림 경로를 구성합니다.
```

#### 사용 목적과 도입 근거

> Spot 인스턴스는 AWS의 가용 용량에 따라 중단될 수 있습니다. 노드가 사라진 뒤 복구를 시작하면 실행 중인 작업이 갑자기 끊기고, 대체 노드를 준비하는 시간도 추가됩니다.
>

| 도입 근거 | KeepGo 적용 의미 |
| --- | --- |
| Worker의 Spot 사용 | 인스턴스 회수에 대응할 경로 필요 |
| Karpenter의 기본 연동 지원 | 별도의 메시지 소비 프로그램을 개발하지 않고 중단 처리 기능 사용 |
| 이벤트 발생과 처리를 분리 | Karpenter가 큐를 조회하여 AWS 이벤트를 처리 |
| 서비스 메시징과 운영 경로 분리 | 영상 분석 메시징 변경과 독립적으로 노드 중단 알림 유지 |

`구성요소별 역할`

| 구성요소 | 역할 |
| --- | --- |
| AWS EC2·AWS Health | Spot 중단, 예정된 유지보수, 인스턴스 상태 변경 등의 이벤트 발생 |
| EventBridge | 규칙과 일치하는 이벤트를 찾아 SQS에 전달 |
| SQS | 전달된 이벤트 메시지를 보관하고 Controller의 조회에 응답 |
| Karpenter Controller | 이벤트를 자신이 관리하는 노드와 연결하고 필요한 중단 대응 수행 |
| Kubeternetes 컨트롤러·스케줄러 | 종료된 Pod의 대체 Pod 생성과 배치 처리 |
| 애플리케이션 Worker | 종료 신호 수집, 작업 정리·재처리·중복 처리 방지 |

```yaml
① AWS가 Spot 인스턴스 중단 경고 발생
   메시지에 인스턴스 ID·중단 동작 등이 포함
                    ↓
② EventBridge 규칙이 이벤트와 일치
                    ↓
③ 전용 SQS 큐로 이벤트 메시지 전달
                    ↓
④ Karpenter Controller가 SQS를 조회
   이벤트 유형과 대상 인스턴스 확인
                    ↓
⑤ Karpenter가 관리하는 해당 노드에 중단 대응 시작
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
기존 노드에 신규 배치 제한   대체 노드 프로비저닝
기존 Pod 퇴거·종료 진행     병렬로 시작
          │                    │
          └─────────┬──────────┘
                    ↓
⑥ Deployment 등의 컨트롤러가 대체 Pod 생성
   스케줄러가 가용 노드에 배치
                    ↓
⑦ 기존 노드 종료·정리
   AWS 회수 시점까지 처리하지 못한 작업은 재처리 필요
```

`→ Kafka를 개발할때 다시 한번 설계 생각해보기`

!image.png

→ 다음은 EventBridge 생성

`생성순서`

AWS 이벤트가 생성되면 EventBridge 규칙에 의해서 sqs:SendMessage 권한을 설정해야 Karpenter 알림 SQS가 시작

→ sqs:SendMessage 권한과 EventBridge 규칙 설정

`추가할 권한 목록`

!image.png

| 항목 | 의미 |
| --- | --- |
| events.amazonaws.com | EventBridge 서비스에 허용 |
| sqs:SendMessage | 메세지를 보내는 작업만 허용 |
| Resource | 이번 Karpenter 알림 큐에만 허용 |
| aws:SourceArn | 우리 계정·서울 리전에서 이름이 `keepgo-dev3-karpenter-`로 시작하는 규칙만 허용 |

!image.png

| 조건 | 의미 |
| --- | --- |
| source | EC2에서 발생한 이벤트 |
| detail-type | 그중 Spot 인스턴스 중단 경고만 선택 |

`AWS Health 알림 규칙`

!image.png

이벤트 패턴

- 이벤트 소스 : AWS 이벤트 또는 EventBridge 파트너 이벤트
- 생성 방버버 : 사용자 지정 패턴(JSON 편집기로)

`EC2 인스턴스 상태 변경 규칙`

!image.png

`리밸런스 권고 규칙`

!image.png

#### Controller용 IAM Role

!image.png

```yaml
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::602601433533:oidc-provider/oidc.eks.ap-northeast-2.amazonaws.com/id/9D77C55BB8BF2965833549FC9F54B682"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.ap-northeast-2.amazonaws.com/id/9D77C55BB8BF2965833549FC9F54B682:aud": "sts.amazonaws.com",
          "oidc.eks.ap-northeast-2.amazonaws.com/id/9D77C55BB8BF2965833549FC9F54B682:sub": "system:serviceaccount:karpenter:karpenter"
        }
      }
    }
  ]
}
```

| 설정 | 의미 |
| --- | --- |
| Federated | 우리 클러스터의 OIDC 공급자를 신뢰 |
| sts:AssumeRoleWithWebIdentity | ServiceAccount 토큰으로 임시 AWS 자격 증명 발급 |
| aud | AWS STS를 대상으로 발급한 토큰인지 확인 |
| sub | Karpneter 네임스페이스의 Karpenter 서비스계정만 허용 |
1. `eks-integration` - EKS 클러스터 정보 조회
2. `iam-integration` - 새 EC2 노드에 IAM Role 연결
3. `node-lifecycle` - EC2 노드 생성·종료·교체 관리
4. `interruption` - Spot 중단 및 유지보수 알림 수신
5. `resource-discovery` - 노드 생성에 필요한 AWS 리소스 조회

211.244.225.211/32

#### Helm 설정에 ServiceAccount, IAM Role 연결 지정

```yaml
# values.yaml
# KeepGo dev3 Karpenter Controller 설치 설정
replicas: 2

serviceAccount:
  create: true
  name: karpenter
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::602601433533:role/keepgo-dev3-karpenter-controller-role
    eks.amazonaws.com/sts-regional-endpoints: "true"

podLabels:
  eks.amazonaws.com/fargate-profile: keepgo-dev3-karpenter

nodeSelector:
  kubernetes.io/os: linux
  eks.amazonaws.com/compute-type: fargate

affinity: null
topologySpreadConstraints: []

controller:
  env:
    - name: AWS_REGION
      value: ap-northeast-2

    - name: AWS_DEFAULT_REGION
      value: ap-northeast-2

    - name: AWS_EC2_METADATA_DISABLED
      value: "true"

  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 512Mi

settings:
  clusterName: keepgo-dev3-eks

  clusterEndpoint: https://9D77C55BB8BF2965833549FC9F54B682.gr7.ap-northeast-2.eks.amazonaws.com

  eksControlPlane: true

  interruptionQueue: keepgo-dev3-karpenter-interruption

  enableZonalShift: false

serviceMonitor:
  enabled: false
```

`구성`

1. replicas - Controller Pod를 몇 개 실행할지?

   replicas: 2 → Karpenter Controller Pod가 2개를 실행

2. serviceAccount - Controller가 사용할 IAM Role 연결
3. podLabels와 nodeSelector - Fargate에서 실행

   이미 만들어둔 keepgo-dev3-karpenter 프로필 사용

4. affinity와 toplogySpreadConstraints - 차트위 기본 배치 규칙 해체
5. controller.env - AWS 리전과 인증 환경 지정
6. resources - Controller 컨테이너의 CPU·메모리
7. settings - 관리할 클러스터와 중단 알림 큐
8. serviceMonitor - Prometheus 연동용 리소스 생성 여부

!image.png

→ Helm으로 설치할 계정 연결하기

!image.png

미리 kubectl사용해보기

```yaml
export AWS_PROFILE=keepgo-dice-eks
export KUBECONFIG=/Users/dice/.kube/keepgo-dev3.yaml

helm upgrade --install karpenter \
  oci://public.ecr.aws/karpenter/karpenter \
  --version 1.15.1 \
  --namespace karpenter \
  --create-namespace \
  --values "/Users/dice/Documents/ChatGPT/파이널 프로젝트/output/keepgo-v3/karpenter-dev3/values.yaml" \
  --wait \
  --timeout 10m
  # 헬름 설치
```

`구성점검`

```yaml
karpenter Namespace
├─ ServiceAccount: karpenter
│   └─ Controller IAM Role 연결
├─ Deployment: karpenter
│   └─ Controller Pod 2개 → Fargate 실행
└─ Service·RBAC 등

클러스터 공통
└─ Karpenter CRD·ClusterRole 등
```

#### EC2NodeClass

- Karpenter가 새로운 EC2 Worker Node를 생성할 때, AWS 인프라 설정을 어떻게 적용할지 정의하는 Kubernetes 사용자 정의 리소스(CRD)

| 구분 | 설정 대상 | 주요 내용 |
| --- | --- | --- |
| values.yaml | Karpenter Controller 자체 | Pod 복제본·CPU·메모리·ServiceAccount·Fargate 실행·SQS 연결 |
| EC2NodeClass | 생성할 EC2의 AWS 기본 구성 | AMI·서브넷·보안그룹·노드 IAM Role·루트 디스크 |
| NodePool | 어떤 조건의 노드를 언제 만들고 정리할지 | 인스턴스 종류·Spot/On-Demand·자원 상한·노드 라벨·회수 정책 |

```yaml
NodePool                         EC2NodeClass
인스턴스 조건·Spot·확장 한도       AMI·서브넷·보안 그룹·IAM·디스크
             └─────────┬─────────┘
                       ↓
             Karpenter가 EC2 생성
                       ↓
               노드 등록·Pod 실행
```

왜 Application과 Worker을 분리했나요?

| 항목 | Application | Worker |
| --- | --- | --- |
| 리소스 이름 | keepgo-dev3-application | keepgo-dev3-worker |
| 루트 디스크 | 30GiB | 50GiB |
| Workload 태그 | application | worker |
| AMI·서브넷·보안 그룹 ·노드 IAM Role | 동일 | 도일 |
1. AMI - 어떤 운영체제로 노드를 만들지

   > KeepGo V3는 Pod 요구사항에 따른 노드 프로비저닝과 Application·Worker별 확장 정책을 적용하기 위해 Karpenter를 선택했습니다. 또한 AMI 버전을 고정하고 신규 버전을 dev에서 검증한 뒤 반영하며, EC2 수준의 장애·Spot 중단 실험을 수행하기 위해 EKS Auto Mode 대신 Karpenter를 직접 운영합니다. 이에 따라 Controller·IAM·중단 알림 구성과 AMI 갱신 책임은 플랫폼 운영팀이 담당합니다.
>

   | 비교 | AL2023 + Karpenter | EKS Auto Mode |
       | --- | --- | --- |
   | 기반 OS | Amazon Linux 2023 | AWS가 관리하는 Bottlerocket 기반 OS |
   | 이미지 제공자 | AWS 공식 EKS 최적화 AMI | AWS이 Auto Mode용 관리형 AMI |
   | AMI 선택 | 운영팀이 AMI ID·릴리스 선택 | AWS가 선택 |
   | 버전 고정 | 특정 AMI ID로 고정 가능 | 사용자가 원하는 AMI ID로 고정하는 방식 미지원 |
   | 보안 패치 반영 | 운영팀이 새 AMI 검증·반영 | AWS가 관리 |
   | 호스트 OS 변경 | 필요하면 패키지·설정 변경 가능, 운영팀 책임 | 직접 접근, 소프트웨어 설치 제한 |
   | 노드 직접 진단 | 권한·네트워크를 구성하면 SSM 등으로 가능 | SSH·SSM 직접 접속 불가 |
   | 노드 수명 | 현재 30일 | 최대 21일 |
   | 주요 장점 | 이미지·OS·갱신 절차는 직접 제어 | OS 관리 부담 감소, 일관된 보안 구성 |
   | 운영 부담 | 패치 누락·호환성·교체 검증을 직접 관리 | AWS 관리 범위가 더 넓음 |

   > KeepGO V3는 AWS 공식 AL2023 기반 EKS 최적화 AMI를 사용합니다. Auto Mode의 AWS 관리형 Bottlerocket 이미지와 달리, 운영팀이 AMI 버전을 선택·고정하고 dev 검증 후 갱신하는 방식을 채택했습니다. 이를 통해 이미지 변경과 노드 교체 절차를 직접 관리하며, 보안 패치 확인과 호환성 검증 책임도 운영팀이 담당합니다.
>

   `그럼 Amazon Linux 2023(AL2023)의 특징에는 뭐가 있나요?`

  - nodeadm - 노드를 초기화하는 도구
  - IMDSv2 - EC2 메타데이트 접근 보안

    EC2 인스턴스가 자기 자신의 정보와 IAM Role의 임시 자격 증명을 조회할 수 있도록 하는 서비스

    - 세션 토큰을 먼저 발급받아 조회
  - cgroup v2 - 리눅스 자원 관리 기능

    Linux 커널이 프로세스 그룹의 CPU, 메모리, 디스크 I/O 등의 자원 사용량을 제한하고 관리하는 기능

    cgroup v2의 핵심은 CPU, 메모리 등의 자원을 하나의 통합된 계층 구조에서 더 일관되게 관리할 수 있다는 것입니다.


    | 핵심 기능 | Application | Worker | 적용 목적 |
    | --- | --- | --- | --- |
    | 리소스 이름 | keepgo-dev3-application | keepgo-dev3-worker | 각 NodePool이 참조할 노드 설정 구분 |
    | 배치 대상 | API·AI 등 애플리케이션 노드 | 영상 분석 Worker용 노드 | 워크로드별 AWS 설정 관리 |
    | 운영체제 계열 | AL2023 | AL2023 | Amazon Linux 2023 기반 실행 환경 통일 |
    | 사용 AMI | ami—028c | 동일 | EKS 1.37용 x86_64 최적화 AMI |
    | 노드 IAM Role | keepgo-dev3-karpenter-node-role | 동일 | EC2 노드의 EKS 연동·ECR 이미지 조회·SSM 사용 권한 제공 |
    | 서브넷 선택 | Karpenter.sh | 동일 |  |
    | 보안 그룹 | `sg-094cc466e3b468087` | 동일 | 기존 클러스터의 통신 규칙 적용 |
    | 공인 IP 할당 | 비활성화 | 비활성화 | 사설 IP 기반으로 운영하고 외부 요청에는 NAT 사용 |
    | 메타데이터 보안 | IMDSv2 필수 | 동일 | 토근 기반 메타데이터 접근과 일반 Pod의 접근 제한 |
    | IMDS IPv6 엔드포인트 | 비활성화 | 비활성화 |  |
    | 노드당 Pod 수 상한 | maxPods: 110 | maxPods: 110 | 시스템 Pod를 포함한 kubelet의 Pod 수 상한 설정 |
    | 루트 디스크 유형 | EBS gp3 | EBS gp3 | OS·컨테이너 이미지 로그 / 임시파일 저장 |
    | 루트 디스크 용량 | 30 | 50 | Worekr의 이미지·분석 임시 파일 고려 |
    | 디스크 암호화 | 활성화 | 활성화 | EBS 저장 데이터 암호화 |
    | 노드 종료 시 디스크 | 루트 EBS 함께 삭제 | 동일 | 종료된 노드의 루트 볼륨 잔존 방지 |
    | AWS 식별 태그 | Application용 이름·용도 태그 | Worker용 이름·태그 | AWS에서 노드의 환경·소속·용도 구분 |

#### NodePool

- NodePool은 Karpenter가 생성할 노드의 인스턴스 조건·배치 구분·확장 한도·수명·회수 정책을 정의합니다. 아래는 최근 수정한 YAML 기준이며, 두 NodePool의 주요 차이는 구입 방식·Taint·전체 용량 상한·회수 정책입니다.

| 핵심 기능 | Appication | Worekr | 적용 목적 |
| --- | --- | --- | --- |
| 리소스 이름 | keepgo-dev3—application | keepgo-dev3-worker | 워크로드별 노드 운영 정책 구분 |
| 운영 대상 | API·AI 등 애플리케이션 | 영상 분석 Worker | 사용자 요청 처리와 비동기 작업의 자원 경합 완화 |
| 참조 EC2NodeClass | keepgo-dev3-application | keepgo-dev3-worker | AMI·네트워크·IAM·디스크 설정 연결 |
| 노드 생성 방식 | Pod 요구에 따른 동적 생성 | 동일 | 필요한 용량에 맞춰 노드 생성·정리 |
| 노드 라벨 | workload=application | workload=worker | Pod가 실행할 노드 종류 선택 |
| Taint | 별도 설정 없음 | Noschedule | 해당 Taint를 허용하지 않은 Pod의 Worker 노드 배치 제한 |
| 운영체제·아키텍처 | linux, amd64 | 동일 | 선택한 x86_64 AMI와 실행 환경 일치 |
| 허용 AZ | 서울 AZ-a, AZ-c | 동일 | 두 AZ를 노드 생성 후보로 허용 |
| 구입 방식 | On-Demand만 허용 | Spot 우선 On-Demand 대체 허용 | Application은 실행 안정성, Worker은 비용 절감과 용량 확보 고려 |
| 허용 인스턴스 계열 | t, c, m, r | 동일 | 버스트·연산·범용·메모리 계열로 선택 후보 확대 |
| 세대 제한 | 별도 번호 제한 없음 | 동일 | 호환 조건을 충족하는 여러 세대 활용 |
| 가상화 조건 | Nitro 기반 | 동일 | 기존 Prefix Delegation 운영 전제 유지 |
| 노드별 CPU 후보 | 2, 4vCPU | 동일 | 초기 운영에서 선택할 개별 노드 크기 제한 |
| 노드별 최소 메모리 | 4 이상 | 동일 | 최소 t3.medium 수준의 최고 메모리 확보 |
| NodePool 전체 용량 상한 | CPU 16vCPU·메모리 64GiB | CPU 8 vCPU·메모리 32GiB | 워크로드별 확장 규모 제한 |
| 노드 수명 | 30일 | 동일 | 장기간 유지되는 노드를 주기적 교체 대상으로 관리 |
| 종료 처리 유예 상한 | 30분 | 5분 | 노드 종료 시 Pod 정리 대기 시간 설정 |
| 통합·회수 조건 | WhemEmpyt | WhenEmptyOrUnderutilized | Application은 보수적으로, Worker는 비용 절감 중심으로 정리 |
| 통합 판단 대기 시간 | 30분 | 5분 | Pod 추가·삭제 이후 통합 판단까지 대기 |
| 자발적 중단 예산 | 최대 1개 노드 | 최대 1개 노드 | 예산이 적용되는 노드 교체·통합의 동시 진행 수 제한 |

#### LBC

→ AWS Load Balancer Controller : Kubernetes에 작성한 외부 통신 설정을 읽고, AWS에 ALB·대상 그룹·리스너 등을 생성하거나 수정하는 프로그램

!image.png

`주요 역할`

| 권한 구분 | 대상 리소스 | 수행 가능한 작업 | 사용 목적 |
| --- | --- | --- | --- |
| AWS 환경 조회 | VPC·서브넷·AZ·보안 그룹·EC2·네트워크 인터페이스·라우팅 정보 등 | 조회 | 로드밸런서 배치 위치와 연결 대상 확인 |
| 로드밸런서 관리 | ALB·NLB | 생성·속성 변경·서브넷/보안 그룹 설정·삭제 | 선언한 외부 진입점 구성 반영 |
| 대상 그룹 관리 | Target Group | 생성·속성 변경·삭제·상태 조회 | 트래픽을 전달할 대상 그룹 관리 |
| 트래픽 대상 등록 | Target Group의 대상 | 등록·등록 해체 | Pod IP 등의 변경을 전달 대상에 반영 |
| 리스너·라우팅 규칙 관리 | Listener·Listener Rule | 생성·변경·우선 순위 조정·삭제 | 포트/도메인/경로별 요청 전달 설정 |
| HTTPS 인증서 연동 | ACM·IAM 서버 인증서·리스너 | 인증서 조회·리스너 인증서 추가/제거 | HTTPS 리스너 구성 |
| 보안 그룹 관리 | EC2 Security Group | 생성/삭제/인바운드 규칙 추가/제거 | ALB와 대상 사이에 필요한 통신 허용 |
| 태그 관리 | 로드밸런서·대상 그룹·리스너·보안 그룹 등 | 태그 추가·제거 | Controller 관리 리소스 식별 |
| 서비스 연결 역할 생성 | ELB용 Service-linked Role | ELB 서비스에 한정하여 생성 | AWS 로드밸런서 서비스 운영 준비 |

!image.png

#### CRD 설치 - Kubetnetes에 새로운 리소스 종류를 등록하는 정의서

Gateway API 표준 CRD

- GatewayClass - 처리할 컨트롤러 종류 지정
- Gateway - 요청을 받을 포트·프로토콜·Route 연결 범위 정의
- HTTPRoute - 도메인·경로별 목적지 Service 정의

LBC 전용 CRD

- LoadBalancerConfiguration - ALB의 공개 여부·서브넷 등 AWS 세부 설정
- TargetGroupConfiguration - 대상 그룹과 헬스 체크 등 설정
- ListenerRuleConfiguration - LBC에서 제공하는 리스너 규칙 세부 설정

!image.png

#### gatewayclass.yaml

```yaml
# 사용할 Kubernetes API 그룹과 버전
apiVersion: gateway.networking.k8s.io/v1

# Gateway를 처리할 컨트롤러 종류를 지정하는 리소스
kind: GatewayClass

metadata:
  # 우리가 정한 이름
  # 이후 Gateway의 gatewayClassName에 이 값을 작성
  name: keepgo-dev3-alb

spec:
  # AWS Load Balancer Controller의 ALB용 식별자
  # 이 값은 임의로 바꾸면 안 됨
  controllerName: gateway.k8s.aws/alb
```

Gateway를 어떤 컨트롤러가 어떤 방식으로 구현할지

`헷갈리는 개념 정리`

| GatewayClass | 누가 구현할까? | AWS LBC가 ALB로 구현 |
| --- | --- | --- |
| Gateway | 어디로 요청을 받을까? | HTTPS 443 포트 등 진입점 정의 |
| HTTPRoute | 받은 요청을 어디로 보낼까? | 경로에 따라 내부 Service 연결 |

→ gateway-namespace.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: gateway-system
```

→ loadbalancer-configuration.yaml

```yaml
apiVersion: gateway.k8s.aws/v1
kind: LoadBalancerConfiguration

metadata:
  name: keepgo-dev3-alb-config
  namespace: gateway-system

spec:
  # 인터넷에서 접근할 수 있는 ALB
  scheme: internet-facing

  # ALB의 주소 체계
  ipAddressType: ipv4

  # ALB를 배치할 Public 서브넷 두 개
  loadBalancerSubnets:
    - identifier: subnet-061e173fafc26cbe2 # dev3-public-a
    - identifier: subnet-0fa8ff2876088e795 # dev3-public-c

  tags:
    Project: keepgo
    Environment: dev3
```

| scheme | 인터넷에서 접근 가능한 ALB로 구성 |
| --- | --- |
| ipAddressType | ALB에 IPv4 사용 |
| loadBalancerSubnets | AZ-a·AZ-c의 Public 서브넷 지정. 노드·Pod는 Private에 유지 |
| tags | 생성되는 AWS 리소스를 프로젝트·환경별로 식별 |

!image.png

#### Gateway YAML

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway

metadata:
  name: keepgo-dev3-gateway
  namespace: gateway-system

spec:
  # AWS LBC가 ALB로 구현하도록 지정
  gatewayClassName: keepgo-dev3-alb

  # 앞서 만든 ALB 설정 참조
  # Public 서브넷·IPv4·ACM 인증서 설정이 들어 있음
  infrastructure:
    parametersRef:
      group: gateway.k8s.aws
      kind: LoadBalancerConfiguration
      name: keepgo-dev3-alb-config

  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      hostname: dev3.keepgo.kr

      # 연결 가능한 Route 종류와 Namespace 제한
      allowedRoutes:
        kinds:
          - group: gateway.networking.k8s.io
            kind: HTTPRoute

        namespaces:
          from: Selector
          selector:
            matchExpressions:
              - key: kubernetes.io/metadata.name
                operator: In
                values:
                  - gateway-system
                  - account
                  - ingest
                  - content
                  - recommend
                  - frontend
```

```yaml
Gateway: keepgo-dev3-gateway
  │
  ├─ gatewayClassName
  │    └─ keepgo-dev3-alb → AWS LBC가 ALB로 구현
  │
  ├─ parametersRef
  │    └─ keepgo-dev3-alb-config
  │         └─ Public 서브넷·IPv4·ACM 인증서
  │
  └─ listeners
       └─ dev3.keepgo.kr / HTTPS 443
            └─ 허용된 Namespace의 HTTPRoute 연결
```

| 주요 설정 | 설명 |
| --- | --- |
| gatewayClassName | ALB용 GatewayClass를 지정 |
| infrastructure.parametersRef | Public 서브넷·IPv4·ACM 인증서가 포함된 ALB 설정 참조 |
| listeners | dev3.keepgo.kr의 HTTPS 443 진입점 정의 |
| allowedRoutes | 지정된 Namespace의 HTTPRoute만 연결 허용 |

!image.png

#### NetworkPolicy

`도입 목적`

> KeepGo V3는 여러 서비스가 하나의 Kubernetes 클러스터를 공유하므로, 서비스 실행에 필요한 통신만 허용하기 위해 NetworkPolicy를 적용합니다. Namespace와 Pod 라벨을 기준으로 접근 대상을 구분하고, 통신 방향과 포트별 허용 범위를 정의합니다.
>

`적용 목표`

| 목표 | 적용 방향 |
| --- | --- |
| 서비스 간 불필요한 접근 제한 | 호출 관계가 확인된 서비스 사이의 통신만 허용 |
| 내부 전용 서비스 보호 | ai-api등은 지정된 내부 호출 주체만 접근하도록 구성 |
| 필요한 외부 통신 유지 | 외부 API·AWS 서비스·RDS 등의 접근 요구사항 반영 |
| 기본 실행 기능 유지 | DNS 조회와 필요한 인증·모니터링 통신 포함 |
| Pod 교체·확장 대응 | 개별 Pod IP 대신 Namespace·Pod 라벨을 중심으로 정책 정의 |

1. VPC CNI 설정 변경

    ```yaml
    {
      "enableNetworkPolicy": "true",
      "env": {
        "ENABLE_PREFIX_DELEGATION": "true",
        "WARM_PREFIX_TARGET": "1",
        "NETWORK_POLICY_ENFORCING_MODE": "standard"
      }
    }
    ```

   | 설정 | 의미 |
       | --- | --- |
   | enableNetworkPolicy | NetworkPolicy를 실제로 집행하는 기능 활성화 |
   | Prefix 관련 값 | 기존 Pod IP 할당 설정 유지 |
   | standard | Pod 시작 시 허용 상태에서 출발하고, 정책이 준비되면 적용 |

`ai-api`

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy

metadata:
  name: allow-ai-api-from-approved-callers
  namespace: ai

spec:
  # 보호할 대상 Pod
  podSelector:
    matchLabels:
      app.kubernetes.io/name: ai-api

  # AI로 들어오는 통신을 제한
  policyTypes:
    - Ingress

  ingress:
    - from:
        # 영상 분석 Worker 허용
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingest
          podSelector:
            matchLabels:
              app.kubernetes.io/name: youtube-analysis-worker

        # 채팅·추천 API 허용
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: recommend
          podSelector:
            matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values:
                  - chat-api
                  - recommend-api

      # AI 컨테이너의 http라는 이름의 포트만 허용
      ports:
        - protocol: TCP
          port: http
```

| 접근 | AI 접근 |
| --- | --- |
| ingest의 youtube-analysis-worker | 허용 |
| recommend의 chat-api | 허용 |
| recommand의 recommand-api | 허용 |
| 그 외 일반 Pod | 허용 규칙 없음 |

→ ai-api는 영상 분석 Worker와 채팅·추천 API의 요청만 수신하도록 제한합니다. Namespace와 Pod라벨을 함께 확인하여 호출 대상을 구분하고, AI의 HTTP 포트만 허용합니다. 외부 AI 호출 등 송신 통신은 별도의 Egress 정책에서 정의합니다.

`ai-api 송신 정책`

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy

metadata:
  name: allow-ai-api-dns-and-external-https
  namespace: ai

spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: ai-api

  policyTypes:
    - Egress

  egress:
    # 1. CoreDNS로 도메인 조회 허용
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns

      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53

    # 2. 사설·링크로컬 대역을 제외한 목적지의 TCP 443 허용
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
              - 169.254.0.0/16

      ports:
        - protocol: TCP
          port: 443
```

| 구성 | 목적 |
| --- | --- |
| CoreDNS 허용 | 외부 AI 서비스의 도메인을 IP로 조회 |
| TCP 443 허용 | 외부 AI API에 HTTPS 요청 |
| 사설·링크로컬 대역 제외 | 해당 HTTPS 규칙으로 내부 자원까지 접근하는 것을 방지 |
| Egress | AI Pod가 새로 시작하는 송신 연결 제한 |

> AI 서비스의 송신 통신은 DNS 조회와 외부 AI 호출용 TCP 443을 우선 허용합니다. 사설·링크로컬 대역은 외부 호출 허용 규칙에서 제외하며, RDS·Redis 등 내부 자원 연결은 실제 사용 여부에 따라 별도 허용합니다.
>
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


내 IAM

dice-EKS