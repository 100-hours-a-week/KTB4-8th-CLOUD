# 구조 파악 : 다음 계층(ECS, RDS, REdis)와 DNS 배포에 필요한 식별자 구분
output "vpc_id" { value = aws_vpc.main.id }
output "subnet_ids" { value = local.subnet_ids }
output "security_group_ids" {
  value = { for key, group in aws_security_group.main : key => group.id }
}
output "nat_public_ip" {
  value = try(aws_eip.nat[0].public_ip, null)
}

output "api" {
  value = {
    domain       = var.api_domain_name
    alb_arn      = aws_lb.api.arn
    listener_arn = aws_lb_listener.https.arn
    target_group = { for key, group in aws_lb_target_group.app : key => group.arn }
    alb_dns_name = aws_lb.api.dns_name
  }
}

output "web" {
  value = {
    bucket            = aws_s3_bucket.web.id
    distribution_id   = aws_cloudfront_distribution.web.id
    cloudfront_domain = aws_cloudfront_distribution.web.domain_name
    origin            = var.web_domain_name == "" ? "https://${aws_cloudfront_distribution.web.domain_name}" : "https://${var.web_domain_name}"
  }
}

output "redis" {
  value = {
    host = aws_elasticache_replication_group.main.primary_endpoint_address
    port = 6379
    tls  = true
  }
}

output "queues" {
  value = {
    urls = { for key, queue in aws_sqs_queue.main : key => queue.url }
    dlqs = { for key, queue in aws_sqs_queue.dlq : key => queue.url }
  }
}

output "ecs" {
  value = {
    cluster_name       = aws_ecs_cluster.main.name
    capacity_providers = { for key, provider in aws_ecs_capacity_provider.pool : key => provider.name }
  }
}

output "services" {
  value = {
    names        = { for key, service in aws_ecs_service.app : key => service.name }
    log_groups   = { for key, group in aws_cloudwatch_log_group.app : key => group.name }
    secret_names = { for key, secret in data.aws_secretsmanager_secret.app : key => secret.name }
    ai_api_url   = "http://ai-api.${aws_service_discovery_private_dns_namespace.main.name}:8000"
  }
}

output "cicd" {
  value = {
    deploy_role_arn = aws_iam_role.github_deploy.arn
    alerts_topic    = aws_sns_topic.alerts.arn
  }
}

output "database" {
  value = {
    host             = aws_db_instance.main.address
    port             = aws_db_instance.main.port
    name             = aws_db_instance.main.db_name
    admin_secret_arn = aws_db_instance.main.master_user_secret[0].secret_arn
  }
}