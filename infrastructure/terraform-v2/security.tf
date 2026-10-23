# 보안그룹 정하기 
# 흐름은 역할별 SG 생성 -> 누가 어떤 SG를 쓰고 들어오는지 -> 나가는길

resource "aws_security_group" "main" {
  for_each = toset(["alb", "ecs-host", "backend", "ai-api", "sse", "worker", "rds", "redis"])

  name        = "${local.name}-${each.key}"
  description = "KeepGo V2 ${each.key}"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-${each.key}" }
}

locals {
  # 대상 SG ← 출발 SG : 포트
  sg_ingress = {
    backend-from-alb = { target = "backend", source = "alb", port = local.service_ports.backend }
    sse-from-alb     = { target = "sse", source = "alb", port = local.service_ports.sse }
    ai-from-backend  = { target = "ai-api", source = "backend", port = local.service_ports.ai-api }
    rds-from-backend = { target = "rds", source = "backend", port = 3306 }
    rds-from-worker  = { target = "rds", source = "worker", port = 3306 }
    redis-from-be    = { target = "redis", source = "backend", port = 6379 }
    redis-from-sse   = { target = "redis", source = "sse", port = 6379 }
    redis-from-wk    = { target = "redis", source = "worker", port = 6379 }
    # 디버깅용: SSM 포트 포워딩(호스ㅡㅌ 경유)으로 RedisInsigint 접속
    redis-from-host = { target = "redis", source = "ecs-host", port = 6379 }
    # 디버깅용: SSM 포트 포워딩(호스트 경유)으로 DB 도구 접속. 필요 없어지면 지운다.
    rds-from-host    = { target = "rds", source = "ecs-host", port = 3306 }
  }
}

resource "aws_vpc_security_group_ingress_rule" "from_sg" {
  for_each = local.sg_ingress

  security_group_id            = aws_security_group.main[each.value.target].id
  referenced_security_group_id = aws_security_group.main[each.value.source].id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
  description                  = each.key
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id = aws_security_group.main["alb"].id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "cloudfront only"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_targets" {
  for_each = toset(["backend", "sse"])

  security_group_id            = aws_security_group.main["alb"].id
  referenced_security_group_id = aws_security_group.main[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = local.service_ports[each.key]
  to_port                      = local.service_ports[each.key]
  description                  = "to ${each.key}"
}

# 앱과 ECS 호스트는 NAT를 통해 AWS API·외부 API로 나간다. RDS·Redis는 나가는 규칙이 없다.
resource "aws_vpc_security_group_egress_rule" "internet" {
  for_each = toset(["ecs-host", "backend", "ai-api", "sse", "worker"])

  security_group_id = aws_security_group.main[each.key].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "outbound via NAT"
}


# ALB 헬스체크가 백엔드와 SSE의 관리 포트(8081)로 들어온다.
# ALB 헬스체크가 Backend·SSE의 관리 포트(8081)로 들어온다.
resource "aws_vpc_security_group_ingress_rule" "alb_health" {
  for_each = toset(["backend", "sse"])

  security_group_id            = aws_security_group.main[each.key].id
  referenced_security_group_id = aws_security_group.main["alb"].id
  ip_protocol                  = "tcp"
  from_port                    = local.management_port
  to_port                      = local.management_port
  description                  = "alb health check"
}

resource "aws_vpc_security_group_egress_rule" "alb_health" {
  for_each = toset(["backend", "sse"])

  security_group_id            = aws_security_group.main["alb"].id
  referenced_security_group_id = aws_security_group.main[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = local.management_port
  to_port                      = local.management_port
  description                  = "health to ${each.key}"
}