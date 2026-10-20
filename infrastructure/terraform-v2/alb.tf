# 구조 파악 - Public ALB -> Backend/SSE Target Grou -> HTTP는 HTTPS로 전환 -> 경로별 각각 분배
# 흐름: Public ALB → Backend/SSE Target Group → HTTP는 HTTPS로 전환 → 경로별 전달, 나머지 404.
resource "aws_lb" "api" {
  name               = local.name
  internal           = false
  load_balancer_type = "application"
  subnets            = local.subnet_ids.public
  security_groups    = [aws_security_group.main["alb"].id]

  # SSE 연결 유지. 앱 Heartbeat는 이보다 짧아야 한다.
  idle_timeout               = 120
  drop_invalid_header_fields = true
  enable_deletion_protection = var.deletion_protection
}

locals {
  target_groups = {
    # Backend는 짧은 요청이라 연결 정리 30초, SSE는 장기 연결이라 300초.
    backend = { deregistration_delay = 30 }
    sse     = { deregistration_delay = 300 }
  }
}

resource "aws_lb_target_group" "app" {
  for_each = local.target_groups

  name                 = "${local.name}-${each.key}"
  vpc_id               = aws_vpc.main.id
  target_type          = "ip"
  protocol             = "HTTP"
  port                 = local.service_ports[each.key]
  deregistration_delay = each.value.deregistration_delay

  health_check {
    port                = tostring(local.management_port)
    path                = var.health_check_paths[each.key]
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 5
    unhealthy_threshold = 2
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.api_certificate_arn

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Not Found"
      status_code  = "404"
    }
  }
}

locals {
  # V1 nginx가 Backend로 보내던 경로와 같다. 규칙 하나에 경로 값은 최대 5개.
  listener_rules = {
    sse     = { priority = 10, paths = ["/events/*"] }
    backend = { priority = 20, paths = ["/api/*", "/oauth2/*", "/login/oauth2/*", "/public/*"] }
  }
}

resource "aws_lb_listener_rule" "app" {
  for_each = local.listener_rules

  listener_arn = aws_lb_listener.https.arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app[each.key].arn
  }

  condition {
    path_pattern { values = each.value.paths }
  }
}