# 흐름: 알림 채널(SNS) → 서비스·데이터·큐 경보 → 배포 실패(자동 롤백) 이벤트 알림.
resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

# 메일 구독은 받은 메일에서 Confirm을 눌러야 활성화된다.
resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.alert_emails)

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.key
}

locals {
  alarms = merge(
    # 서비스: 메모리 85% 초과 (켜진 서비스만)
    { for key, service in local.enabled : "${key}-memory" => {
      namespace  = "AWS/ECS", metric = "MemoryUtilization", stat = "Average", threshold = 85, comparison = "GreaterThanThreshold"
      dimensions = { ClusterName = aws_ecs_cluster.main.name, ServiceName = aws_ecs_service.app[key].name }
    } },
    # ALB: 비정상 Task, 5xx 급증
    { for key in keys(local.target_groups) : "${key}-unhealthy" => {
      namespace  = "AWS/ApplicationELB", metric = "UnHealthyHostCount", stat = "Maximum", threshold = 0, comparison = "GreaterThanThreshold"
      dimensions = { LoadBalancer = aws_lb.api.arn_suffix, TargetGroup = aws_lb_target_group.app[key].arn_suffix }
    } },
    {
      alb-5xx = {
        namespace  = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", stat = "Sum", threshold = 10, comparison = "GreaterThanThreshold"
        dimensions = { LoadBalancer = aws_lb.api.arn_suffix }
      }
      rds-cpu = {
        namespace  = "AWS/RDS", metric = "CPUUtilization", stat = "Average", threshold = 80, comparison = "GreaterThanThreshold"
        dimensions = { DBInstanceIdentifier = aws_db_instance.main.identifier }
      }
      rds-storage = {
        namespace  = "AWS/RDS", metric = "FreeStorageSpace", stat = "Minimum", threshold = 2147483648, comparison = "LessThanThreshold"
        dimensions = { DBInstanceIdentifier = aws_db_instance.main.identifier }
      }
      redis-memory = {
        namespace  = "AWS/ElastiCache", metric = "DatabaseMemoryUsagePercentage", stat = "Average", threshold = 80, comparison = "GreaterThanThreshold"
        dimensions = { ReplicationGroupId = aws_elasticache_replication_group.main.id }
      }
    },
    # 큐: 5분 넘게 처리 안 된 메시지, DLQ 유입
    { for key in local.queues : "${key}-age" => {
      namespace  = "AWS/SQS", metric = "ApproximateAgeOfOldestMessage", stat = "Maximum", threshold = 300, comparison = "GreaterThanThreshold"
      dimensions = { QueueName = aws_sqs_queue.main[key].name }
    } },
    { for key in local.queues : "${key}-dlq" => {
      namespace  = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible", stat = "Maximum", threshold = 0, comparison = "GreaterThanThreshold"
      dimensions = { QueueName = aws_sqs_queue.dlq[key].name }
    } },
  )
}

resource "aws_cloudwatch_metric_alarm" "main" {
  for_each = local.alarms

  alarm_name          = "${local.name}-${each.key}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = each.value.stat
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  dimensions          = each.value.dimensions
  period              = 60
  evaluation_periods  = 3
  # 지표가 없을 때(Task 없음, 큐 비어 있음)는 정상으로 본다.
  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]
  ok_actions         = [aws_sns_topic.alerts.arn]
}

# 배포 실패(Circuit Breaker가 롤백함)를 바로 알린다. 경보 지표로는 잡히지 않는 이벤트다.
resource "aws_cloudwatch_event_rule" "deploy_failed" {
  name = "${local.name}-deploy-failed"
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Deployment State Change"]
    resources     = [{ prefix = "arn:aws:ecs:${local.region}:${var.aws_account_id}:service/${local.name}/" }]
    detail        = { eventName = ["SERVICE_DEPLOYMENT_FAILED"] }
  })
}

resource "aws_cloudwatch_event_target" "deploy_failed" {
  rule = aws_cloudwatch_event_rule.deploy_failed.name
  arn  = aws_sns_topic.alerts.arn
}

# CloudWatch 경보와 EventBridge가 이 토픽에 발행할 수 있게 허용한다.
resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = ["cloudwatch.amazonaws.com", "events.amazonaws.com"] }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = { StringEquals = { "aws:SourceAccount" = var.aws_account_id } }
    }]
  })
}