# 흐름: Data 서브넷 그룹 → 개발용 작은 MySQL → 관리자 비밀번호는 RDS가 Secrets Manager에 직접 만든다.
# 개발 단계 전용 DB다. 운영 승격 때는 V1 DB 연결 방식(DB 시나리오)을 따로 정하고 이 DB는 지운다.
resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-rds"
  subnet_ids = local.subnet_ids.data

  tags = { Name = "${local.name}-rds" }
}

resource "aws_db_instance" "main" {
  identifier     = "${local.name}-dev-db"
  engine         = "mysql"
  engine_version = "8.4" # V1과 같은 메이저 버전. 마이너는 AWS 기본값

  instance_class        = "db.t4g.micro"
  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "keepgo"
  username = "keepgo_admin"
  # 비밀번호를 코드·state에 두지 않는다. RDS가 Secrets Manager에 username/password JSON으로 만든다.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.main["rds"].id]
  publicly_accessible    = false
  multi_az               = false

  # 개발 데이터는 버려도 되는 값이다. 하루치 백업만 두고, 지울 때 최종 스냅샷을 남기지 않는다.
  backup_retention_period    = 1
  skip_final_snapshot        = true
  deletion_protection        = false
  auto_minor_version_upgrade = true
  apply_immediately          = true

  tags = { Name = "${local.name}-dev-db", Purpose = "dev" }
}