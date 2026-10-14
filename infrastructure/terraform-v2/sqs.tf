# 구조 : 작업 큐 3개 -> 큐마다 DLQ -> TLS 아닌 요청 거부
locals {
  queues = toset(["sync", "analysis", "notification"])

}

# 5번 받고도 삭제되지 않은 메시지를 격리하기. 원인 파악을 위해 7일 보관
resource "aws_sqs_queue" "dlq" {
  for_each = local.queues

  name                      = "${local.name}-${each.key}-dlq"
  message_retention_seconds = 604800
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "main" {
  for_each = local.queues

  name                       = "${local.name}-${each.key}"
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = var.sqs_visibility_timeout
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = 5
  })
}

# DLQ에는 짝이 되는 원본 큐의 메시지만 들어올 수 있다.
resource "aws_sqs_queue_redrive_allow_policy" "main" {
  for_each = local.queues

  queue_url = aws_sqs_queue.dlq[each.key].url
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main[each.key].arn]
  })
}

resource "aws_sqs_queue_policy" "tls_only" {
  for_each = merge(
    { for key, queue in aws_sqs_queue.main : key => queue },
    { for key, queue in aws_sqs_queue.dlq : "${key}-dlq" => queue }

  )

  queue_url = each.value.url
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "sqs:*"
      Resource  = each.value.arn
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}