# 구조 파악하기 redis -> 단일 Redis(TLS 적용해야함 까먹지말기) -> 캐시 / 임시 / 상태 / SSE 
resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = local.subnet_ids.data
}

# 4단계 설계 문서에서 초기 redis는 cache.t4g.small
resource "aws_elasticache_replication_group" "main" {
  replication_group_id = local.name
  description          = "KeepGo V2 cache and PubSub"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = "cache.t4g.small"
  num_cache_clusters   = 1
  port                 = 6379
  parameter_group_name = "default.redis7"

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.main["redis"].id]

  automatic_failover_enabled = false
  multi_az_enabled           = false

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  transit_encryption_mode    = "required"

  snapshot_retention_limit   = 0
  maintenance_window         = "sun:18:00-sun:19:00"
  auto_minor_version_upgrade = true
  apply_immediately          = false
}