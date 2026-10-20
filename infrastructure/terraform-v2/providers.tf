#AWS프로바이저 및 이름 정의 계속 local.name으로 쓰던거
provider "aws" {
  region              = "ap-northeast-2"
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = "keepgo"
      Environment = "prod"
      Version     = "v2"
      ManagedBy   = "Terraform"
    }
  }

}

locals {
  name   = "keepgo-v2"
  region = "ap-northeast-2"
  azs    = ["ap-northeast-2a", "ap-northeast-2c"]

  service_ports = {
    backend = 8080
    ai-api  = 8000
    sse     = 8080
    # 헬스 지표용 = 관리 포트 8081
  }
  management_port = 8081
}