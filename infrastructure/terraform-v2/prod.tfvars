vpc_cidr           = "10.20.0.0/16"
enable_nat_gateway = true

api_domain_name     = "api.keepgo.kr"
api_certificate_arn = "arn:aws:acm:ap-northeast-2:602601433533:certificate/00806579-fd54-44fd-900b-b654ca6a9e35"

web_domain_name         = "dev.keepgo.kr"
web_certificate_arn     = "arn:aws:acm:us-east-1:602601433533:certificate/140a680c-67c2-43e9-ab86-e4b0a0be9d91"
web_alb_certificate_arn = "arn:aws:acm:ap-northeast-2:602601433533:certificate/6f7c6a41-0304-4bc8-919e-946e55072ca6"

enabled_services = ["backend", "ai-api", "frontend"]
image_tags = {
  backend  = "5e26fbf223e636cd50509a2ad85138b742ad7865"
  ai-api   = "7c9e71ef8b2dbd718102cd7c0d1f8fd7a59d60c0"
  frontend = "f567e87292921bfa3210c5d8ff1d86ddddba1b4c"
}