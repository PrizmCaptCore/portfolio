terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

# ==================== Data Sources ====================

data "aws_vpc" "main" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
}

# ALB는 AZ당 서브넷 1개만 허용 → 중복 제거
data "aws_subnet" "each" {
  for_each = toset(data.aws_subnets.default.ids)
  id       = each.value
}

locals {
  # AZ당 첫 번째 서브넷만 선택
  unique_az_subnets = values({
    for id, s in data.aws_subnet.each : s.availability_zone => s.id...
  })
  subnet_ids_unique_az = [for azs in local.unique_az_subnets : azs[0]]

  # VPC 엔드포인트는 ap-northeast-2d 미지원 → a,b,c만
  vpce_supported_azs = ["ap-northeast-2a", "ap-northeast-2b", "ap-northeast-2c"]
  vpce_subnet_ids = [
    for id, s in data.aws_subnet.each : s.id
    if contains(local.vpce_supported_azs, s.availability_zone)
    && contains(local.subnet_ids_unique_az, s.id)
  ]

}

data "aws_acm_certificate" "main" {
  domain   = var.acm_domain
  statuses = ["ISSUED"]
}

# ==================== CloudWatch Logs ====================

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 30

  tags = {
    Environment = var.environment
  }
}

# ==================== IAM: Task Execution Role ====================
# ECS 에이전트가 사용 (ECR pull, CloudWatch Logs, Secrets Manager)

resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "secrets-access"
  role = aws_iam_role.ecs_task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = [aws_secretsmanager_secret.app_env.arn]
    }]
  })
}

# ==================== IAM: Task Role ====================
# Django/Celery 앱이 실행 시 사용 (S3, SQS 접근)

resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "s3-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = flatten([
        for bucket in var.s3_bucket_names : [
          "arn:aws:s3:::${bucket}",
          "arn:aws:s3:::${bucket}/*"
        ]
      ])
    }]
  })
}

# ECS Exec 활성화용 (kubectl exec 대체)
resource "aws_iam_role_policy" "ecs_task_exec_command" {
  name = "ecs-exec"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel"
      ]
      Resource = "*"
    }]
  })
}

# ==================== GitHub Actions OIDC ====================

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["ffffffffffffffffffffffffffffffffffffffff"]

  tags = { Name = "github-actions-oidc" }
}

resource "aws_iam_role" "github_actions" {
  name = "${var.project_name}-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_actions_ecr" {
  name = "ecr-push"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "github_actions_ecs" {
  name = "ecs-deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices",
          "ecs:UpdateService",
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:DeregisterTaskDefinition",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
          "ecs:TagResource"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_s3" {
  name = "s3-collectstatic"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = flatten([
        for bucket in concat(var.s3_bucket_names, [var.spa_bucket_name]) : [
          "arn:aws:s3:::${bucket}",
          "arn:aws:s3:::${bucket}/*"
        ]
      ])
    }]
  })
}

resource "aws_iam_role_policy" "github_actions_cloudfront" {
  name = "cloudfront-invalidate"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["cloudfront:CreateInvalidation"]
      Resource = aws_cloudfront_distribution.spa.arn
    }]
  })
}

# ==================== Secrets Manager ====================

resource "aws_secretsmanager_secret" "app_env" {
  name = "${var.project_name}/${var.environment}/env"

  tags = {
    Environment = var.environment
  }
}

# ==================== Security Groups ====================

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb-sg"
  description = "ALB security group"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-alb-sg"
  }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-ecs-tasks-sg"
  description = "ECS tasks security group"
  vpc_id      = data.aws_vpc.main.id

  # ALB에서 오는 트래픽만 허용
  ingress {
    from_port = 8000
    to_port   = 8000
    protocol  = "tcp"
    security_groups = [
      aws_security_group.alb.id,
      "sg-0eeee5555ffff6666", # prod ALB SG (통합 ALB에서 dev로 트래픽 전달)
    ]
  }

  # 외부 접근 (RDS, ElastiCache, ECR, S3 등)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ecs-tasks-sg"
  }
}

# RDS에서 ECS 태스크 접근 허용
resource "aws_security_group_rule" "rds_from_ecs" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  security_group_id        = var.rds_security_group_id
}

# ElastiCache에서 ECS 태스크 접근 허용
resource "aws_security_group_rule" "redis_from_ecs" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  security_group_id        = var.elasticache_security_group_id
}


# ==================== Modules ====================

module "ecs_cluster" {
  source = "./modules/ecs_cluster"

  project_name = var.project_name
  environment  = var.environment
}

# ALB는 prod에서 통합 관리 (relay-platform-prod-alb)
# dev web은 prod ALB의 dev 타겟 그룹에 연결
locals {
  dev_target_group_arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:targetgroup/relay-platform-dev-tg/EXAMPLE000000000"
}

# 공통 환경 변수
locals {
  common_env_vars = [
    { name = "DJANGO_SETTINGS_MODULE", value = "config.settings.prod" },
    { name = "USE_S3_STORAGE", value = "True" },
    { name = "AWS_REGION_NAME", value = var.aws_region },
    { name = "AWS_STORAGE_BUCKET_NAME", value = var.s3_bucket_names[0] },
    { name = "ALLOWED_HOSTS", value = "${var.acm_domain},*" },
    { name = "CSRF_TRUSTED_ORIGINS", value = "https://${var.acm_domain}" },
    { name = "REACT_FRONTEND_URL", value = "https://${var.acm_domain}" },
    { name = "SPA_FRONTEND_URL", value = "https://${var.acm_domain}" },
    { name = "SLACK_REDIRECT_URI", value = "https://${var.acm_domain}/api/v1/integrations/slack/callback/" },
    { name = "NOTION_REDIRECT_URI", value = "https://${var.acm_domain}/api/v1/integrations/notion/callback/" },
    { name = "GOOGLE_CALENDAR_REDIRECT_URI", value = "https://${var.acm_domain}/api/v1/integrations/google_calendar/callback/" },
    { name = "GMAIL_REDIRECT_URI", value = "https://${var.acm_domain}/api/v1/integrations/gmail/callback/" },
    { name = "OUTLOOK_CALENDAR_REDIRECT_URI", value = "https://${var.acm_domain}/api/v1/integrations/outlook_calendar/callback/" },
    { name = "OUTLOOK_MAIL_REDIRECT_URI", value = "https://${var.acm_domain}/api/v1/integrations/outlook_mail/callback/" },
    { name = "TEAMS_REDIRECT_URI", value = "https://${var.acm_domain}/api/v1/integrations/teams/callback/" },
    { name = "MICROSOFT_TENANT", value = "common" },
  ]

  secret_arn = aws_secretsmanager_secret.app_env.arn

  common_secrets = [
    { name = "SECRET_KEY", valueFrom = "${local.secret_arn}:SECRET_KEY::" },
    { name = "DATABASE_URL", valueFrom = "${local.secret_arn}:DATABASE_URL::" },
    { name = "REDIS_URL", valueFrom = "${local.secret_arn}:REDIS_URL::" },
    { name = "CELERY_BROKER_URL", valueFrom = "${local.secret_arn}:CELERY_BROKER_URL::" },
    { name = "CELERY_RESULT_BACKEND", valueFrom = "${local.secret_arn}:CELERY_RESULT_BACKEND::" },
    { name = "BREVO_API_KEY", valueFrom = "${local.secret_arn}:BREVO_API_KEY::" },
    { name = "DEFAULT_FROM_EMAIL", valueFrom = "${local.secret_arn}:DEFAULT_FROM_EMAIL::" },
    { name = "OPENAI_API_KEY", valueFrom = "${local.secret_arn}:OPENAI_API_KEY::" },
    { name = "OPENROUTER_API_KEY", valueFrom = "${local.secret_arn}:OPENROUTER_API_KEY::" },
    { name = "INTEGRATION_ENCRYPTION_KEY", valueFrom = "${local.secret_arn}:INTEGRATION_ENCRYPTION_KEY::" },
    { name = "SLACK_CLIENT_ID", valueFrom = "${local.secret_arn}:SLACK_CLIENT_ID::" },
    { name = "SLACK_CLIENT_SECRET", valueFrom = "${local.secret_arn}:SLACK_CLIENT_SECRET::" },
    { name = "SLACK_APP_ID", valueFrom = "${local.secret_arn}:SLACK_APP_ID::" },
    { name = "NOTION_CLIENT_ID", valueFrom = "${local.secret_arn}:NOTION_CLIENT_ID::" },
    { name = "NOTION_CLIENT_SECRET", valueFrom = "${local.secret_arn}:NOTION_CLIENT_SECRET::" },
    { name = "TOSS_PAYMENTS_CLIENT_KEY", valueFrom = "${local.secret_arn}:TOSS_PAYMENTS_CLIENT_KEY::" },
    { name = "TOSS_PAYMENTS_SECRET_KEY", valueFrom = "${local.secret_arn}:TOSS_PAYMENTS_SECRET_KEY::" },
    { name = "RELAY_INTERNAL_KEY", valueFrom = "${local.secret_arn}:RELAY_INTERNAL_KEY::" },
    { name = "MODAL_TRANSLATE_URL", valueFrom = "${local.secret_arn}:MODAL_TRANSLATE_URL::" },
    { name = "MODAL_STT_URL", valueFrom = "${local.secret_arn}:MODAL_STT_URL::" },
    { name = "MODAL_SUMMARY_URL", valueFrom = "${local.secret_arn}:MODAL_SUMMARY_URL::" },
    { name = "RUNPOD_TRANSLATE_ENDPOINT_ID", valueFrom = "${local.secret_arn}:RUNPOD_TRANSLATE_ENDPOINT_ID::" },
    { name = "RUNPOD_INFERENCE_ENDPOINT_ID", valueFrom = "${local.secret_arn}:RUNPOD_INFERENCE_ENDPOINT_ID::" },
    { name = "RUNPOD_EMBEDDING_ENDPOINT_ID", valueFrom = "${local.secret_arn}:RUNPOD_EMBEDDING_ENDPOINT_ID::" },
    { name = "RUNPOD_API_KEY", valueFrom = "${local.secret_arn}:RUNPOD_API_KEY::" },
    { name = "GOOGLE_CLIENT_ID", valueFrom = "${local.secret_arn}:GOOGLE_CLIENT_ID::" },
    { name = "GOOGLE_CLIENT_SECRET", valueFrom = "${local.secret_arn}:GOOGLE_CLIENT_SECRET::" },
    { name = "MICROSOFT_CLIENT_ID", valueFrom = "${local.secret_arn}:MICROSOFT_CLIENT_ID::" },
    { name = "MICROSOFT_CLIENT_SECRET", valueFrom = "${local.secret_arn}:MICROSOFT_CLIENT_SECRET::" },
  ]
}

module "web" {
  source = "./modules/ecs_service"

  project_name       = var.project_name
  environment        = var.environment
  service_name       = "web"
  cluster_id         = module.ecs_cluster.cluster_id
  ecr_repository_url = var.ecr_repository_url
  image_tag          = var.image_tag
  cpu                = var.web_cpu
  memory             = var.web_memory
  desired_count      = var.web_desired_count
  container_port     = 8000
  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn
  subnet_ids         = local.vpce_subnet_ids
  security_group_ids = [aws_security_group.ecs_tasks.id]
  target_group_arn   = local.dev_target_group_arn
  log_group_name     = aws_cloudwatch_log_group.ecs.name
  environment_variables = concat(local.common_env_vars, [
    { name = "PROCESS_TYPE", value = "web" },
    { name = "RUN_PREDEPLOY", value = "true" },
  ])
  secrets = local.common_secrets

}

module "worker" {
  source = "./modules/ecs_service"

  project_name       = var.project_name
  environment        = var.environment
  service_name       = "worker"
  cluster_id         = module.ecs_cluster.cluster_id
  ecr_repository_url = var.ecr_repository_url
  image_tag          = var.image_tag
  cpu                = var.worker_cpu
  memory             = var.worker_memory
  desired_count      = var.worker_desired_count
  command            = ["celery", "-A", "config.celery:app", "worker", "--loglevel=info", "--hostname=worker@%h"]
  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn
  subnet_ids         = local.vpce_subnet_ids
  security_group_ids = [aws_security_group.ecs_tasks.id]
  log_group_name     = aws_cloudwatch_log_group.ecs.name
  environment_variables = concat(local.common_env_vars, [
    { name = "PROCESS_TYPE", value = "worker" },
    { name = "RUN_PREDEPLOY", value = "false" },
  ])
  secrets = local.common_secrets
}

module "beat" {
  source = "./modules/ecs_service"

  project_name       = var.project_name
  environment        = var.environment
  service_name       = "beat"
  cluster_id         = module.ecs_cluster.cluster_id
  ecr_repository_url = var.ecr_repository_url
  image_tag          = var.image_tag
  cpu                = var.beat_cpu
  memory             = var.beat_memory
  desired_count      = var.beat_desired_count
  command            = ["celery", "-A", "config.celery:app", "beat", "--loglevel=info", "--pidfile="]
  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn
  subnet_ids         = local.vpce_subnet_ids
  security_group_ids = [aws_security_group.ecs_tasks.id]
  log_group_name     = aws_cloudwatch_log_group.ecs.name
  environment_variables = concat(local.common_env_vars, [
    { name = "PROCESS_TYPE", value = "beat" },
    { name = "RUN_PREDEPLOY", value = "false" },
  ])
  secrets = local.common_secrets
}
