# 흐름: 기존 GitHub OIDC 공급자 조회 → dev Environment에서만 쓰는 V2 배포 Role → ECS 갱신·웹 업로드 권한.
# 이미지 push는 기존 ECR push Role이 계속 담당한다. 이 Role은 "배포"만 한다.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_deploy" {
  name = "${local.name}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        # Job에 environment를 지정하면 sub가 "repo:<레포>:environment:<이름>" 형태가 된다.
        StringLike = { "token.actions.githubusercontent.com:sub" = var.github_deploy_subjects }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "deploy"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Task Definition 조회·등록은 특정 ARN으로 제한할 수 없다.
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:UpdateService", "ecs:DescribeServices"]
        Resource = "arn:aws:ecs:${local.region}:${var.aws_account_id}:service/${local.name}/*"
      },
      # 새 Task Definition에 기존 실행·Task Role을 그대로 넘긴다.
      {
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = concat([for role in aws_iam_role.exec : role.arn], [for role in aws_iam_role.task : role.arn])
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
      # FE 정적 파일 업로드와 캐시 무효화
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.web.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.web.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "cloudfront:CreateInvalidation"
        Resource = aws_cloudfront_distribution.web.arn
      },
    ]
  })
}


# CLOUD 레포 중앙 CD(deploy-v2-dev.yaml)의 보조 권한. 배포 상태 확인, Task Definition 태그 유지, 이미지 확인, 배포 기록 저장.
# 원본: KTB4-8th-CLOUD infrastructure/v2-cd/cloud-v2-dev-cd-policy.json (콘솔에서 먼저 만든 것을 import)
import {
  to = aws_iam_role_policy.cloud_v2_dev_cd
  id = "keepgo-v2-github-deploy:cloud-v2-dev-cd"
}

resource "aws_iam_role_policy" "cloud_v2_dev_cd" {
  name = "cloud-v2-dev-cd"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadDeploymentAndImageState"
        Effect   = "Allow"
        Action   = ["ecs:ListTasks", "elasticloadbalancing:DescribeTargetHealth"]
        Resource = "*"
      },
      {
        Sid      = "ReadV2Tasks"
        Effect   = "Allow"
        Action   = ["ecs:DescribeTasks"]
        Resource = "arn:aws:ecs:${local.region}:${var.aws_account_id}:task/${local.name}/*"
      },
      {
        Sid    = "PreserveTaskDefinitionTags"
        Effect = "Allow"
        Action = ["ecs:ListTagsForResource", "ecs:TagResource"]
        Resource = [
          "arn:aws:ecs:${local.region}:${var.aws_account_id}:task-definition/${local.name}-backend:*",
          "arn:aws:ecs:${local.region}:${var.aws_account_id}:task-definition/${local.name}-ai-api:*",
        ]
      },
      {
        Sid      = "VerifyPublishedImages"
        Effect   = "Allow"
        Action   = ["ecr:DescribeImages", "ecr:BatchGetImage"]
        Resource = [data.aws_ecr_repository.app["keepgo-backend"].arn, data.aws_ecr_repository.app["keepgo-ai"].arn]
      },
      {
        Sid    = "PersistV2DeploymentState"
        Effect = "Allow"
        Action = ["ssm:GetParameter", "ssm:PutParameter"]
        Resource = [
          "arn:aws:ssm:${local.region}:${var.aws_account_id}:parameter/keepgo/v2-dev/deployments/backend",
          "arn:aws:ssm:${local.region}:${var.aws_account_id}:parameter/keepgo/v2-dev/deployments/ai",
        ]
      },
    ]
  })
}