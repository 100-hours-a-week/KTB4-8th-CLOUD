# 흐름: ECS Cluster → 호스트 Role → 호스트 그룹 3개(Launch Template + ASG) → Capacity Provider.
resource "aws_ecs_cluster" "main" {
  name = local.name

  # Worker 확장 지표(RunningTaskCount)가 여기서 나온다. 지표 수만큼 CloudWatch 요금이 붙는다.
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_account_setting_default" "awsvpc_trunking" {
  name  = "awsvpcTrunking"
  value = "enabled"
}

locals {
  # 호스트당 Task 최대 2개(ENI 3개 - 호스트용 1개). max는 "서비스 최대 Task + 배포 중 추가분" 기준이다.
  pools = {
    backend = { instance_types = ["c7i.large"], min = 0, max = 6, on_demand_base = 0, spot = false }
    sse     = { instance_types = ["t3.medium"], min = 0, max = 4, on_demand_base = 0, spot = false }
    worker  = { instance_types = ["t3.medium", "t3a.medium"], min = 0, max = 5, on_demand_base = 1, spot = true }
    # 워커 1대까지는 온디맨드, 그 뒤부터는 Spot 적용
  }
}

# ---------- 호스트 Role ----------
# 호스트는 ECS 등록과 SSM 접속만 한다. 앱 권한은 Task Role(다음 계층)이 따로 가진다.
resource "aws_iam_role" "ecs_host" {
  name = "${local.name}-ecs-host"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_host" {
  for_each = toset([
    "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
  ])

  role       = aws_iam_role.ecs_host.name
  policy_arn = each.key
}

resource "aws_iam_instance_profile" "ecs_host" {
  name = "${local.name}-ecs-host"
  role = aws_iam_role.ecs_host.name
}

# ---------- 호스트 그룹 ----------
# AWS가 관리하는 최신 ECS 최적화 Amazon Linux 2023 AMI.
data "aws_ssm_parameter" "ecs_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

resource "aws_launch_template" "ecs" {
  for_each = local.pools

  name_prefix            = "${local.name}-${each.key}-"
  image_id               = nonsensitive(data.aws_ssm_parameter.ecs_ami.value)
  instance_type          = each.value.instance_types[0]
  vpc_security_group_ids = [aws_security_group.main["ecs-host"].id]

  iam_instance_profile { name = aws_iam_instance_profile.ecs_host.name }

  user_data = base64encode(templatefile("${path.module}/user-data.sh.tftpl", {
    cluster_name = aws_ecs_cluster.main.name
    pool_name    = each.key
  }))

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_type           = "gp3"
      volume_size           = 30
      encrypted             = true
      delete_on_termination = true
    }
  }

  # IMDSv2만 허용. hop 1이면 컨테이너에서 호스트 자격 증명을 꺼낼 수 없다.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # t3는 크레딧을 다 쓰면 느려진다(standard). unlimited는 초과분이 과금된다.
  dynamic "credit_specification" {
    for_each = startswith(each.value.instance_types[0], "t") ? [1] : []
    content { cpu_credits = "standard" }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${local.name}-${each.key}", Pool = each.key }
  }
}

resource "aws_autoscaling_group" "ecs" {
  for_each = local.pools

  name                = "${local.name}-${each.key}"
  vpc_zone_identifier = local.subnet_ids.app
  min_size            = each.value.min
  max_size            = each.value.max
  desired_capacity    = each.value.min

  health_check_type         = "EC2"
  health_check_grace_period = 300
  default_instance_warmup   = 300

  # Task가 있는 호스트를 ASG가 임의로 줄이지 못하게 한다. 축소는 Capacity Provider가 Task를 옮긴 뒤 한다.
  protect_from_scale_in = true

  # Worker만 Spot을 섞는다. 여러 타입을 허용해 Spot 회수 위험을 나눈다.
  capacity_rebalance = each.value.spot

  mixed_instances_policy {
    instances_distribution {
      on_demand_base_capacity                  = each.value.on_demand_base
      on_demand_percentage_above_base_capacity = each.value.spot ? 0 : 100
      spot_allocation_strategy                 = "price-capacity-optimized"
    }

    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.ecs[each.key].id
        version            = aws_launch_template.ecs[each.key].latest_version
      }

      dynamic "override" {
        for_each = each.value.instance_types
        content { instance_type = override.value }
      }
    }
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }

  # 대수는 Capacity Provider가 조절한다. Terraform이 되돌리지 않게 한다.
  lifecycle {
    ignore_changes = [desired_capacity]
  }

  depends_on = [aws_route.app_nat, aws_iam_role_policy_attachment.ecs_host]
}

resource "aws_ecs_capacity_provider" "pool" {
  for_each = local.pools

  name = "${local.name}-${each.key}"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.ecs[each.key].arn
    managed_termination_protection = "ENABLED"
    managed_draining               = "ENABLED"

    managed_scaling {
      status                    = "ENABLED"
      target_capacity           = 100
      minimum_scaling_step_size = 1
      maximum_scaling_step_size = 2
      instance_warmup_period    = 300
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = concat([for provider in aws_ecs_capacity_provider.pool : provider.name], ["FARGATE"])
}