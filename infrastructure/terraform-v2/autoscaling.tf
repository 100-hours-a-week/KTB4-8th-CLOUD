# 구조 - 서비스별 Task 개수 범위 -> 부하 지표별 타겟 트래킹. EC2 대수는 Capacity Provider가 따라온다.
resource "aws_appautoscaling_target" "app" {
  for_each = local.enabled

  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.app[each.key].name}"
  min_capacity       = each.value.min
  max_capacity       = each.value.max
}

# Backend: Task당 분당 요청 수 + CPU. 둘 중 하나라도 넘으면 늘리고, 둘 다 내려가야 줄인다.
resource "aws_appautoscaling_policy" "backend_requests" {
  for_each = contains(keys(local.enabled), "backend") ? toset(["backend"]) : toset([])

  name               = "${local.name}-backend-requests"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = aws_appautoscaling_target.app["backend"].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 600
    scale_out_cooldown = 60
    scale_in_cooldown  = 300
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.api.arn_suffix}/${aws_lb_target_group.app["backend"].arn_suffix}"
    }
  }
}

resource "aws_appautoscaling_policy" "backend_cpu" {
  for_each = contains(keys(local.enabled), "backend") ? toset(["backend"]) : toset([])

  name               = "${local.name}-backend-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = aws_appautoscaling_target.app["backend"].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_out_cooldown = 60
    scale_in_cooldown  = 300
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# AI API·SSE: CPU로는 포화를 알 수 없다. 앱이 KeepGo/V2 네임스페이스로 60초마다 보내는 지표를 쓴다.
# 앱이 지표를 보내기 전까지 이 정책은 아무 동작도 하지 않는다.
resource "aws_appautoscaling_policy" "concurrency" {
  for_each = {
    for key, setting in {
      ai-api = { metric = "ActiveRequestsPerTask", target = 10 }
      sse    = { metric = "ActiveConnectionsPerTask", target = 1000 }
    } : key => setting if contains(keys(local.enabled), key)
  }

  name               = "${local.name}-${each.key}-concurrency"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = aws_appautoscaling_target.app[each.key].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = each.value.target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300
    customized_metric_specification {
      namespace   = "KeepGo/V2"
      metric_name = each.value.metric
      statistic   = "Average"
      dimensions {
        name  = "ClusterName"
        value = aws_ecs_cluster.main.name
      }
      dimensions {
        name  = "ServiceName"
        value = aws_ecs_service.app[each.key].name
      }
    }
  }
}

# Worker: (큐 3개의 대기 메시지 합) ÷ 실행 중 Task 수. 전체 길이가 아니라 Task당 적체량을 본다.
resource "aws_appautoscaling_policy" "worker_backlog" {
  for_each = contains(keys(local.enabled), "worker") ? toset(["worker"]) : toset([])

  name               = "${local.name}-worker-backlog"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = aws_appautoscaling_target.app["worker"].resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = 10
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    customized_metric_specification {
      dynamic "metrics" {
        for_each = { q1 = "sync", q2 = "analysis", q3 = "notification" }
        content {
          id          = metrics.key
          return_data = false
          metric_stat {
            stat = "Average"
            metric {
              namespace   = "AWS/SQS"
              metric_name = "ApproximateNumberOfMessagesVisible"
              dimensions {
                name  = "QueueName"
                value = aws_sqs_queue.main[metrics.value].name
              }
            }
          }
        }
      }

      metrics {
        id          = "tasks"
        return_data = false
        metric_stat {
          stat = "Average"
          metric {
            namespace   = "ECS/ContainerInsights"
            metric_name = "RunningTaskCount"
            dimensions {
              name  = "ClusterName"
              value = aws_ecs_cluster.main.name
            }
            dimensions {
              name  = "ServiceName"
              value = aws_ecs_service.app["worker"].name
            }
          }
        }
      }

      metrics {
        id          = "backlog"
        expression  = "IF(tasks > 0, (FILL(q1,0) + FILL(q2,0) + FILL(q3,0)) / tasks, 0)"
        label       = "Visible messages per running worker task"
        return_data = true
      }
    }
  }
}