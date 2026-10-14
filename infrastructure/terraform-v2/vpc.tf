# 구조 VPC 분리 2AZ구성과 3계층 서브넷
# 흐름: VPC → 2 AZ × 3계층 서브넷 → IGW·NAT → 계층별 라우팅 → S3 Gateway Endpoint.
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = local.name }
}

# VPC 기본 SG는 같은 SG끼리 모든 통신을 허용한다. 규칙을 비워 실수로 쓰이지 않게 한다.
resource "aws_default_security_group" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name}-default-unused" }
}

locals {
  # 10.20.0.0/24, 10.20.1.0/24 = public / 10.20.10~11 = app / 10.20.20~21 = data
  tier_offsets = { public = 0, app = 10, data = 20 }

  subnets = merge([
    for tier, offset in local.tier_offsets : {
      for index, az in local.azs : "${tier}-${index}" => {
        tier = tier
        az   = az
        cidr = cidrsubnet(var.vpc_cidr, 8, offset + index)
      }
    }
  ]...)
}

resource "aws_subnet" "main" {
  for_each = local.subnets

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name}-${each.key}"
    Tier = each.value.tier
  }
}

locals {
  subnet_ids = {
    for tier in keys(local.tier_offsets) : tier => [
      for key, subnet in aws_subnet.main : subnet.id if local.subnets[key].tier == tier
    ]
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = local.name }
}

# 비용형 초기안: AZ-a에 NAT 1개. AZ-a 장애 시 두 AZ 모두 외부 API 호출이 끊긴다.
resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"

  tags = { Name = "${local.name}-nat" }
}

resource "aws_nat_gateway" "main" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.main["public-0"].id

  tags       = { Name = local.name }
  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "tier" {
  for_each = local.tier_offsets

  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name}-${each.key}" }
}

resource "aws_route_table_association" "main" {
  for_each = local.subnets

  subnet_id      = aws_subnet.main[each.key].id
  route_table_id = aws_route_table.tier[each.value.tier].id
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.tier["public"].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

# App 계층만 NAT로 나간다. Data 계층에는 인터넷 기본 경로가 없다.
resource "aws_route" "app_nat" {
  count = var.enable_nat_gateway ? 1 : 0

  route_table_id         = aws_route_table.tier["app"].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[0].id
}

# 무료. ECR 이미지 레이어(S3)와 S3 접근이 NAT를 거치지 않는다.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${local.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.tier["app"].id]

  tags = { Name = "${local.name}-s3" }
}
