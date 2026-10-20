vpc_cidr           = "10.20.0.0/16"
enable_nat_gateway = true

api_domain_name     = "api.keepgo.kr"
api_certificate_arn = "arn:aws:acm:ap-northeast-2:602601433533:certificate/00806579-fd54-44fd-900b-b654ca6a9e35"

web_domain_name     = ""
web_certificate_arn = ""

enabled_services = ["backend", "ai-api"]
image_tags = {
  backend = "503a23686080485cae89c0cae152a33e3aac8528"
  ai-api  = "6e9c5cf7b2993238b613804fb1a6fdd7bf04657b"
}