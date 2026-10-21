# 구조 : 서비스 사양 정의 -> 로그 그룹·내부 DNS -> Task Definition(실행 설계도) -> ECS Service(개수 유지·ALB 연결)
locals {
  # 호스트그룹(pool), 이미지 저장소, 포트, CPU, 메모리, Task 개수 범위
  # 백엔드는 Caffeine 캐시·로컬 업로드 때문에 Stateless화 전까지 Task 1개로 고정한다
  services = {
    backend = { pool = "backend", repository = "keepgo-backend", port = 8080, cpu = 512, memory = 1536, reservation = 1024, min = 1, max = 1, stop = 30, alb = true }
    ai-api  = { pool = "backend", repository = "keepgo-ai", port = 8000, cpu = 512, memory = 768, reservation = 512, min = 1, max = 4, stop = 30, alb = false }
    sse     = { pool = "sse", repository = "keepgo-backend", port = 8080, cpu = 512, memory = 1024, reservation = 512, min = 1, max = 4, stop = 120, alb = true }
    worker  = { pool = "worker", repository = "keepgo-backend", port = null, cpu = 1024, memory = 1536, reservation = 1024, min = 1, max = 4, stop = 120, alb = false }
  }

  # 실제로 띄울 서비스. 이미지 · Secret 값이 준비된 것만 var.enabled_services에 넣는다.
  enabled = { for key, service in local.services : key => service if contains(var.enabled_services, key) }
  # 백엔드 이미지로 뜨는 서비스(spring) jwt PEM 파일과 관리 포트(8081)가 필요하다.
  spring_services = toset(["backend", "sse", "worker"])

  web_origin = var.web_domain_name == "" ? "https://${aws_cloudfront_distribution.web.domain_name}" : "https://${var.web_domain_name}"
}

data "aws_ecr_repository" "app" {
  for_each = toset([for service in local.services : service.repository])
  name     = each.key
}

resource "aws_cloudwatch_log_group" "app" {
  for_each          = local.services
  name              = "/keepgo/v2/${each.key}"
  retention_in_days = var.log_retention_days
}

# 백엔드 -> AI API 호출용 내부 주소 : ai-api. keepgo-v2.internal
resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "keepgo-v2.internal"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "ai_api" {
  name = "ai-api"
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}

# 환경변수주입
locals {
  spring_env = {
    SPRING_JPA_HIBERNATE_DDL_AUTO                                 = "update"
    SPRING_FLYWAY_BASELINE_ON_MIGRATE                             = "true"
    SPRING_FLYWAY_BASELINE_VERSION                                = "1"
    DB_VENDOR                                                     = "mysql"
    DB_HOST                                                       = aws_db_instance.main.address
    DB_PORT                                                       = "3306"
    DB_NAME                                                       = "keepgo"
    DB_TIMEZONE                                                   = "Asia/Seoul"
    DB_DRIVER                                                     = "com.mysql.cj.jdbc.Driver"
    DB_DIALECT                                                    = "MySQL"
    AI_SERVER_API_ADDRESS                                         = "http://ai-api.${aws_service_discovery_private_dns_namespace.main.name}:8000"
    FRONTEND_SERVER_ADDRESS                                       = local.web_origin
    SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_GOOGLE_REDIRECTURI = "${local.web_origin}/login/oauth2/code/google"
    JAVA_TOOL_OPTIONS                                             = "-XX:MaxRAMPercentage=65.0"
    LOGGING_LEVEL_ROOT                                            = "INFO"
    SERVER_FORWARD_HEADERS_STRATEGY                               = "native"
    SPRING_SERVLET_MULTIPART_MAXFILESIZE                          = "10MB"
    SPRING_SERVLET_MULTIPART_MAXREQUESTSIZE                       = "10MB"
    KEEPGO_SECURITY_JWT_PUBLICKEY                                 = "file:/run/secrets/jwt_public_key.pem"
    KEEPGO_SECURITY_JWT_PRIVATEKEY                                = "file:/run/secrets/jwt_private_key.pem"
    SPRING_SQL_INIT_MODE                                          = "always"
    SPRING_SQL_INIT_CONTINUE_ON_ERROR                             = "true"
    # 아래는 SQS·Redis 코드가 들어오면 쓴다. 지금 넣어 둬도 앱이 읽지 않으면 영향 없다.
    REDIS_HOST = aws_elasticache_replication_group.main.primary_endpoint_address
    REDIS_PORT = "6379"
    # Spring Boot가 읽는 이름으로 설정. TLS가 없으면 접속 타임아웃
    SPRING_DATA_REDIS_SSL_ENABLED = "true"
    # 토큰 블랙리스트 RT 해시 채팅 요청 저장소와 추천 작업 상태를 Redis로 이전. 배포해도 로그인 유지
    EPHEMERAL_DATABASE = "redis"
    # 프로필 이미지는 S3에 저장한다. local은 컨테이너 디스크라 배포 때마다 사라짐
    FILE_STORAGE_PROVIDER      = "s3"
    FILE_STORAGE_S3_BUCKET     = aws_s3_bucket.uploads.bucket
    FILE_STORAGE_S3_REGION     = local.region
    SQS_SYNC_QUEUE_URL         = aws_sqs_queue.main["sync"].url
    SQS_ANALYSIS_QUEUE_URL     = aws_sqs_queue.main["analysis"].url
    SQS_NOTIFICATION_QUEUE_URL = aws_sqs_queue.main["notification"].url

  }

  service_env = {
    backend = merge(local.spring_env, { SPRING_PROFILES_ACTIVE = "prod" })
    sse     = merge(local.spring_env, { SPRING_PROFILES_ACTIVE = "sse" })
    worker  = merge(local.spring_env, { SPRING_PROFILES_ACTIVE = "worker" })
    ai-api = {
      LLM_PROVIDER           = "google"
      GOOGLE_MODEL           = "gemini-3.8-flash"
      EMBEDDING_PROVIDER     = "google"
      CHROMA_PATH            = "/app/chroma"
      LANGSMITH_TRACING      = "true"
      LANGSMITH_WORKSPACE_ID = "3839065b-21f0-4891-857e-e81695ab40e5"
      LANGSMITH_PROJECT      = "keepgo_local"
    }
  }

  # 컨테이너 안에서 실행하는 헬스체크. Spring 이미지에는 curl이 없어 V1과 같은 bash 방식을 쓴다.
  container_health = {
    spring = ["CMD", "bash", "-c", "timeout -k 1 2 bash -c 'exec 3<>/dev/tcp/127.0.0.1/8081 && printf \"GET /actuator/health HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n\" >&3 && grep -q \"\\\"status\\\":\\\"UP\\\"\" <&3' 2>/dev/null || exit 1"]
    ai-api = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]
  }
}

# ---------- Task Definition ----------
resource "aws_ecs_task_definition" "app" {
  for_each = local.enabled

  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.exec[each.key].arn
  task_role_arn            = aws_iam_role.task[each.key].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  # Spring 서비스만: JWT PEM을 담을 Task 전용 임시 볼륨
  dynamic "volume" {
    for_each = contains(local.spring_services, each.key) ? ["jwt"] : []
    content { name = volume.value }
  }

  container_definitions = jsonencode(concat(
    # 1) 초기화 컨테이너: Secret의 JWT 키를 PEM 파일로 쓰고 종료한다.
    contains(local.spring_services, each.key) ? [{
      name      = "jwt-files"
      image     = "public.ecr.aws/docker/library/busybox:1.37"
      essential = false
      memory    = 32
      command   = ["sh", "-c", "printf '%s' \"$JWT_PUBLIC_KEY\" > /run/secrets/jwt_public_key.pem && printf '%s' \"$JWT_PRIVATE_KEY\" > /run/secrets/jwt_private_key.pem && chmod 444 /run/secrets/*.pem"]
      secrets = [for key in local.jwt_secret_keys : {
        name      = key
        valueFrom = "${data.aws_secretsmanager_secret.app["backend"].arn}:${key}::"
      }]
      mountPoints = [{ sourceVolume = "jwt", containerPath = "/run/secrets", readOnly = false }]
      logConfiguration = {
        logDriver = "awslogs"
        options   = { awslogs-region = local.region, awslogs-group = aws_cloudwatch_log_group.app[each.key].name, awslogs-stream-prefix = "jwt-files" }
      }
    }] : [],

    # 2) 앱 컨테이너
    [{
      name              = each.key
      image             = "${data.aws_ecr_repository.app[each.value.repository].repository_url}:${var.image_tags[each.key]}"
      essential         = true
      cpu               = each.value.cpu
      memory            = each.value.memory
      memoryReservation = each.value.reservation
      stopTimeout       = each.value.stop
      linuxParameters   = { initProcessEnabled = true }
      command           = each.key == "ai-api" ? ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"] : null

      # 앱 포트 + 관리 포트(Spring 8081: 헬스·지표, AI 9464: 지표)
      portMappings = each.value.port == null ? [] : concat(
        [{ containerPort = each.value.port, protocol = "tcp" }],
        contains(local.spring_services, each.key) ? [{ containerPort = local.management_port, protocol = "tcp" }] : [{ containerPort = 9464, protocol = "tcp" }]
      )

      environment = [for name, value in local.service_env[each.key] : { name = name, value = value }]
      secrets = concat(
        [for key in local.secret_env_keys[local.service_secret[each.key]] : {
          name      = key
          valueFrom = "${data.aws_secretsmanager_secret.app[local.service_secret[each.key]].arn}:${key}::"
        }],
        # DB를 쓰는 서비스만(Backend·Worker): RDS 관리 Secret의 username/password
        contains(["backend", "worker"], each.key) ? [for env, field in local.db_secret_env : {
          name      = env
          valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:${field}::"
        }] : [],
        # ai api만 : v2 전용 Secret의 LangSmith 키
        each.key == "ai-api" ? [for key in local.v2_ai_secret_keys : {
          name      = key
          valueFrom = "${data.aws_secretsmanager_secret.v2_ai.arn}:${key}::"
        }] : []
      )

      healthCheck = {
        command     = contains(local.spring_services, each.key) ? local.container_health.spring : local.container_health.ai-api
        interval    = 30
        timeout     = 5
        retries     = 5
        startPeriod = contains(local.spring_services, each.key) ? 90 : 20
      }

      dependsOn   = contains(local.spring_services, each.key) ? [{ containerName = "jwt-files", condition = "SUCCESS" }] : null
      mountPoints = contains(local.spring_services, each.key) ? [{ sourceVolume = "jwt", containerPath = "/run/secrets", readOnly = true }] : []

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-region        = local.region
          awslogs-group         = aws_cloudwatch_log_group.app[each.key].name
          awslogs-stream-prefix = each.key
          mode                  = "non-blocking"
          max-buffer-size       = "4m"
        }
      }
    }]
  ))
}

# ---------- ECS Service ----------
resource "aws_ecs_service" "app" {
  for_each = local.enabled

  name            = "${local.name}-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app[each.key].arn
  desired_count   = each.value.min

  # 어느 호스트 그룹에 띄울지. launch_type과 같이 쓰지 않는다.
  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.pool[each.value.pool].name
    weight            = 1
    base              = 1
  }

  network_configuration {
    subnets          = local.subnet_ids.app
    security_groups  = [aws_security_group.main[each.key].id]
    assign_public_ip = false
  }

  # 롤링 배포: 새 Task를 먼저 띄우고(최대 200%), 실패하면 직전 정상 버전으로 자동 롤백
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # 배치: AZ에 고르게 나눈 뒤, 그 안에서는 메모리가 찬 호스트부터 채운다
  ordered_placement_strategy {
    type  = "spread"
    field = "attribute:ecs.availability-zone"
  }
  ordered_placement_strategy {
    type  = "binpack"
    field = "memory"
  }

  dynamic "load_balancer" {
    for_each = each.value.alb ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.app[each.key].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  dynamic "service_registries" {
    for_each = each.key == "ai-api" ? [1] : []
    content { registry_arn = aws_service_discovery_service.ai_api.arn }
  }

  health_check_grace_period_seconds = each.value.alb ? 180 : null
  enable_execute_command            = true
  propagate_tags                    = "SERVICE"
  enable_ecs_managed_tags           = true

  # 이미지는 CI가, Task 개수는 Auto Scaling이 바꾼다. Terraform이 되돌리지 않게 한다.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_lb_listener_rule.app,
    aws_iam_role_policy.exec,
    aws_iam_role_policy.task,
  ]
}