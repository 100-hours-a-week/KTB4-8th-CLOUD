# 구조 : 서비스마다 실행 Role(ECS가 쓰는 권한)과 Task Role(앱이 쓰는 권한)을 따로 만듬
locals {
  ecs_task_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = var.aws_account_id } }
    }]
  })

  # SSE랑 Worker는 백엔드 이미지와 백엔드 시크릿을 공유한다
  service_secret = { backend = "backend", ai-api = "ai-api", sse = "backend", worker = "backend" }
}

# 실행 Role - 이미지 쓰기, 로그 쓰기, 시크릿 주입
resource "aws_iam_role" "exec" {
  for_each           = local.services
  name               = "${local.name}-${each.key}-exec"
  assume_role_policy = local.ecs_task_trust
}

resource "aws_iam_role_policy" "exec" {
  for_each = local.services

  name = "runtime"
  role = aws_iam_role.exec[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
        Resource = data.aws_ecr_repository.app[each.value.repository].arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.app[each.key].arn}:*"
      },
      {
        Effect = "Allow"
        Action = "secretsmanager:GetSecretValue"
        Resource = concat(
          [data.aws_secretsmanager_secret.app[local.service_secret[each.key]].arn],
          contains(["backend", "worker"], each.key) ? [aws_db_instance.main.master_user_secret[0].secret_arn] : []
        )
      },
    ]
  })
}

# ---------- Task Role: 앱 코드가 AWS API를 부를 때 쓰는 권한 ----------
resource "aws_iam_role" "task" {
  for_each = local.services

  name               = "${local.name}-${each.key}-task"
  assume_role_policy = local.ecs_task_trust
}

resource "aws_iam_role_policy" "task" {
  for_each = local.services

  name = "app"
  role = aws_iam_role.task[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        # ECS Exec(aws ecs execute-command)로 컨테이너에 접속할 때 필요하다.
        {
          Effect   = "Allow"
          Action   = ["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
          Resource = "*"
        },
        {
          Effect    = "Allow"
          Action    = "cloudwatch:PutMetricData"
          Resource  = "*"
          Condition = { StringEquals = { "cloudwatch:namespace" = "KeepGo/V2" } }
        },
      ],
      # Backend는 큐에 넣기만, Worker는 꺼내고 지우기만 한다.
      each.key == "backend" ? [{
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
        Resource = [for queue in aws_sqs_queue.main : queue.arn]
      }] : [],
      each.key == "worker" ? [{
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"]
        Resource = [for queue in aws_sqs_queue.main : queue.arn]
      }] : [],
    )
  })
}