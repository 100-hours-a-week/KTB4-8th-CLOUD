# 흐름: FE 사양 → 로그·보안 그룹 → Target Group·ALB 규칙(나머지 경로) → 실행·Task Role → Task Definition(Fargate) → Service → 자동 확장·경보
# FE(Next.js standalone)만 Fargate에서 실행한다. 작고 상태가 없는 서비스라 EC2 호스트의 ENI 자리를 쓰지 않는 쪽이 싸다.
# enabled_services에 "frontend"를 넣으면 켜진다. 끄면 페이지 요청은 ALB 기본 응답(404)을 받는다.
locals {
  frontend_enabled = contains(var.enabled_services, "frontend")

  frontend = {
    repository = "keepgo-web"
    port       = 3000
    cpu        = 256 # Fargate는 Task 단위로 정해진 조합만 쓸 수 있다: 0.25 vCPU
    memory     = 512 # 0.5 GB
    min        = 1
    max        = 4
  }
}

data "aws_ecr_repository" "frontend" {
  name = local.frontend.repository
}

# BFF(/bff/regions/subway-stations)가 쓰는 KAKAO_REST_API_KEY. V1 Secret을 조회만 한다.
data "aws_secretsmanager_secret" "frontend" {
  name = "Secret-v1-FE"
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/keepgo/v2/frontend"
  retention_in_days = var.log_retention_days
}

# ---------- 네트워크 ----------
resource "aws_security_group" "frontend" {
  name        = "${local.name}-frontend"
  description = "KeepGo V2 frontend"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-frontend" }
}

resource "aws_vpc_security_group_ingress_rule" "frontend_from_alb" {
  security_group_id            = aws_security_group.frontend.id
  referenced_security_group_id = aws_security_group.main["alb"].id
  ip_protocol                  = "tcp"
  from_port                    = local.frontend.port
  to_port                      = local.frontend.port
  description                  = "frontend-from-alb"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_frontend" {
  security_group_id            = aws_security_group.main["alb"].id
  referenced_security_group_id = aws_security_group.frontend.id
  ip_protocol                  = "tcp"
  from_port                    = local.frontend.port
  to_port                      = local.frontend.port
  description                  = "to frontend"
}

# 이미지 받기, Secret 조회, 로그 전송, BFF의 카카오 API 호출이 NAT로 나간다.
resource "aws_vpc_security_group_egress_rule" "frontend_internet" {
  security_group_id = aws_security_group.frontend.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "outbound via NAT"
}

resource "aws_lb_target_group" "frontend" {
  name                 = "${local.name}-frontend"
  vpc_id               = aws_vpc.main.id
  target_type          = "ip"
  protocol             = "HTTP"
  port                 = local.frontend.port
  deregistration_delay = 30

  # 페이지가 전부 빌드 때 만들어진 정적 페이지라 "/"가 가볍다. FE가 /healthz를 만들면 바꾼다.
  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

# SSE(10)·Backend(20) 규칙에 걸리지 않은 나머지 경로를 FE로 보낸다. FE를 끄면 규칙이 사라져 기존처럼 404가 난다.
resource "aws_lb_listener_rule" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  condition {
    path_pattern { values = ["/*"] }
  }
}

# ---------- Role ----------
resource "aws_iam_role" "frontend_exec" {
  name               = "${local.name}-frontend-exec"
  assume_role_policy = local.ecs_task_trust
}

resource "aws_iam_role_policy" "frontend_exec" {
  name = "runtime"
  role = aws_iam_role.frontend_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
        Resource = data.aws_ecr_repository.frontend.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.frontend.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = data.aws_secretsmanager_secret.frontend.arn
      },
    ]
  })
}

# FE 코드는 AWS API를 부르지 않는다. ECS Exec 접속 권한만 둔다.
resource "aws_iam_role" "frontend_task" {
  name               = "${local.name}-frontend-task"
  assume_role_policy = local.ecs_task_trust
}

resource "aws_iam_role_policy" "frontend_task" {
  name = "app"
  role = aws_iam_role.frontend_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
      Resource = "*"
    }]
  })
}

# ---------- Task Definition ----------
resource "aws_ecs_task_definition" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  family                   = "${local.name}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.frontend.cpu
  memory                   = local.frontend.memory
  execution_role_arn       = aws_iam_role.frontend_exec.arn
  task_role_arn            = aws_iam_role.frontend_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name            = "frontend"
    image           = local.deployed_image["frontend"]
    essential       = true
    stopTimeout     = 30
    linuxParameters = { initProcessEnabled = true }
    portMappings    = [{ containerPort = local.frontend.port, protocol = "tcp" }]

    environment = [
      { name = "NODE_ENV", value = "production" },
      { name = "PORT", value = tostring(local.frontend.port) },
      { name = "HOSTNAME", value = "0.0.0.0" },
    ]
    secrets = [{
      name      = "KAKAO_REST_API_KEY"
      valueFrom = "${data.aws_secretsmanager_secret.frontend.arn}:KAKAO_REST_API_KEY::"
    }]

    # node 이미지에는 curl이 없어서 node로 직접 요청한다.
    healthCheck = {
      command     = ["CMD", "node", "-e", "require('http').get('http://127.0.0.1:${local.frontend.port}/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-region        = local.region
        awslogs-group         = aws_cloudwatch_log_group.frontend.name
        awslogs-stream-prefix = "frontend"
        mode                  = "non-blocking"
        max-buffer-size       = "4m"
      }
    }
  }])
}

# ---------- Service ----------
resource "aws_ecs_service" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  name            = "${local.name}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend[0].arn
  desired_count   = local.frontend.min

  # EC2 호스트 그룹이 아니라 Fargate에서 실행한다. 배치 전략(spread/binpack)은 Fargate에서 쓸 수 없고 AWS가 AZ에 나눈다.
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }

  network_configuration {
    subnets          = local.subnet_ids.app
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = false
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = local.frontend.port
  }

  health_check_grace_period_seconds = 60
  enable_execute_command            = true
  propagate_tags                    = "SERVICE"
  enable_ecs_managed_tags           = true

  # 이미지는 CI가, Task 개수는 Auto Scaling이 바꾼다. Terraform이 되돌리지 않게 한다.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_lb_listener_rule.frontend,
    aws_iam_role_policy.frontend_exec,
    aws_iam_role_policy.frontend_task,
  ]
}

# ---------- 자동 확장 ----------
resource "aws_appautoscaling_target" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.frontend[0].name}"
  min_capacity       = local.frontend.min
  max_capacity       = local.frontend.max
}

# Task당 분당 요청 수 기준. 목표값은 부하 테스트로 Task 하나가 버티는 RPS를 잰 뒤 다시 정한다.
resource "aws_appautoscaling_policy" "frontend_requests" {
  count = local.frontend_enabled ? 1 : 0

  name               = "${local.name}-frontend-requests"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = aws_appautoscaling_target.frontend[0].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 1000
    scale_out_cooldown = 60
    scale_in_cooldown  = 300
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.api.arn_suffix}/${aws_lb_target_group.frontend.arn_suffix}"
    }
  }
}

# ---------- 경보 ----------
resource "aws_cloudwatch_metric_alarm" "frontend" {
  for_each = local.frontend_enabled ? {
    frontend-memory = {
      namespace  = "AWS/ECS", metric = "MemoryUtilization", stat = "Average", threshold = 85
      dimensions = { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.frontend[0].name }
    }
    frontend-unhealthy = {
      namespace  = "AWS/ApplicationELB", metric = "UnHealthyHostCount", stat = "Maximum", threshold = 0
      dimensions = { LoadBalancer = aws_lb.api.arn_suffix, TargetGroup = aws_lb_target_group.frontend.arn_suffix }
    }
  } : {}

  alarm_name          = "${local.name}-${each.key}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = each.value.stat
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanThreshold"
  dimensions          = each.value.dimensions
  period              = 60
  evaluation_periods  = 3
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}
