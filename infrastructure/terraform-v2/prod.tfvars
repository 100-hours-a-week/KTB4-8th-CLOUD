vpc_cidr           = "10.20.0.0/16"
enable_nat_gateway = true

api_domain_name     = "api.keepgo.kr"
api_certificate_arn = "arn:aws:acm:ap-northeast-2:602601433533:certificate/00806579-fd54-44fd-900b-b654ca6a9e35"

web_domain_name         = "dev.keepgo.kr"
web_extra_aliases       = []
web_certificate_arn     = "arn:aws:acm:us-east-1:602601433533:certificate/140a680c-67c2-43e9-ab86-e4b0a0be9d91"
web_alb_certificate_arn = "arn:aws:acm:ap-northeast-2:602601433533:certificate/6f7c6a41-0304-4bc8-919e-946e55072ca6"

enabled_services = ["backend", "ai-api", "frontend"]

image_tags = {
  backend  = "08a879a7dadac1cf7697a3a76749a69b424dd325"
  ai-api   = "25bbe478464c0acc336cb321b7415337de746756"
  frontend = "f567e87292921bfa3210c5d8ff1d86ddddba1b4c"
}