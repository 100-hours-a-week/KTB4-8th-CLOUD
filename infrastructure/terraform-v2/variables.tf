# 흐름 : 외부 입력 선언 -> 늦게 실패하는 인증서 규칙만 미리 검사 -> 네트워크 / ALB / CloudFront에 전달.
variable "aws_account_id" {
  type    = string
  default = "602601433533"

  validation {
    condition     = var.aws_account_id == "602601433533"
    error_message = "KeepGo 계정 602601433533만 지원합니다."
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"

  validation {
    condition     = can(cidrsubnet(var.vpc_cidr, 8, 21))
    error_message = "/16 이상의 IPv4 CIDR을 지정해주세요. 서브넷 6개를 /24로 나눕니다."
  }
}

# NAT는 만들자마자 시간당 과금됩니다. ECS를 올리기 전까지 flase로 둘 수 있습니다.
variable "enable_nat_gateway" {
  type    = bool
  default = true
  # true라고 NAT이 돌고 있는 것은 아님. 이 변수를 사용할때 별도 값이 없다면 ture로 판단한다는 뜻
}

# API 도메인(예 : api. keepgo.kr) ALB 인증서와 FE의 API 주소 CORS, OAuth 리다이렉트가 이 이름을 씁니다.
variable "api_domain_name" {
  type = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.api_domain_name))
    error_message = "api.keepgo.kr 양식의 소문자 도메인을 입력해주세요"
  }
}
# ALB 용 인증서입니다. 
variable "api_certificate_arn" {
  type = string

  validation {
    condition     = startswith(var.api_certificate_arn, "arn:aws:acm:ap-northeast-2:")
    error_message = "ALB 인증서는 서울(ap-northeast-2) ACM에서 발급해야 합니다."
  }
}

# 웹 도메인입니다. 값이 아무것도 없을 시 CloudFront 기본 도메인으로 접근이 가능합니다.
variable "web_domain_name" {
  type    = string
  default = ""
}

# CloudFonrt용 인증서는 반드시 us-east-1에서 발급해야 합니다..!
variable "web_certificate_arn" {
  type    = string
  default = ""

  validation {
    condition     = var.web_domain_name == "" || can(regex("^arn:aws:acm:us-east-1:602601433533:certificate/[a-f0-9-]+$", var.web_certificate_arn))
    error_message = "web_domain_name을 쓰려면 us-east-1 ACM 인증서 ARN이 필요합니다."
  }
}

variable "web_alb_certificate_arn" {
  type    = string
  default = ""

  validation {
    condition     = var.web_alb_certificate_arn == "" || startswith(var.web_alb_certificate_arn, "arn:aws:acm:ap-northeast-2:")
    error_message = "ALB용 웹 인증서는 서울 ACM에서 발급받아야 합니다."
  }
}

variable "health_check_paths" {
  type = map(string)
  default = {
    backend = "/actuator/health"
    sse     = "/actuator/health"
  }

  validation {
    condition     = alltrue([for service in ["backend", "sse"] : can(regex("^/", lookup(var.health_check_paths, service, "")))])
    error_message = "backend, sse의 헬스 체크 경로 필요"
  }
}

variable "privacy_policy_url" {
  type    = string
  default = "https://sites.google.com/view/keepgo-privacy-policy"
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "sqs_visibility_timeout" {
  type    = number
  default = 300
}

# 실제로 띄울 서비스. 이미지 태그와 Secret 값이 준비된 서비스만 넣는다. 예: ["backend", "ai-api"]
variable "enabled_services" {
  type    = list(string)
  default = []

  validation {
    condition     = alltrue([for service in var.enabled_services : contains(["backend", "ai-api", "sse", "worker", "frontend"], service)])
    error_message = "서비스 이름은 backend, ai-api, sse, worker, frontend 중에서 고르세요."
  }
}

# 첫 생성에 쓸 이미지 태그(커밋 SHA). 이후 배포는 CI가 하고 Terraform은 이 값을 다시 적용하지 않는다.
variable "image_tags" {
  type    = map(string)
  default = {}

  validation {
    condition     = alltrue([for service in var.enabled_services : can(regex("^[a-f0-9]{7,40}$", lookup(var.image_tags, service, "")))])
    error_message = "enabled_services의 각 서비스에 커밋 SHA 이미지 태그가 필요합니다."
  }
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# 경보를 받을 메일. 구독 확인 메일에서 Confirm을 눌러야 받는다.
variable "alert_emails" {
  type    = list(string)
  default = []
}

# V2에 배포할 수 있는 GitHub Job. 지금은 각 레포의 dev Environment만 허용한다.
variable "github_deploy_subjects" {
  type = list(string)
  default = [
    "repo:100-hours-a-week@167328634/KTB4-8th-BE@1344686243:environment:dev",
    "repo:100-hours-a-week@167328634/KTB4-8th-AI@1344686800:environment:dev",
    "repo:100-hours-a-week@167328634/KTB4-8th-FE@1344685464:environment:dev",
    "repo:100-hours-a-week@167328634/KTB4-8th-CLOUD@1344688950:environment:dev",
  ]
}

variable "web_extra_aliases" {
  description = "웹 도메인 외에 CloudFront가 함께 받을 이름(인증서에 모두 들어 있어야 함)"
  type        = list(string)
  default     = []
}