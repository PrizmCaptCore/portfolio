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
# 기존 dev에서 생성한 리소스 참조

data "aws_vpc" "main" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
}

data "aws_subnet" "each" {
  for_each = toset(data.aws_subnets.default.ids)
  id       = each.value
}

locals {
  # AZ당 첫 번째 서브넷만 선택 (ALB 요구사항)
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

# 기존 ECS 클러스터 참조 (동일 클러스터 사용)
data "aws_ecs_cluster" "main" {
  cluster_name = "${var.project_name}-cluster"
}

locals {
  acm_certificate_arn = "arn:aws:acm:ap-northeast-2:123456789012:certificate/EXAMPLE0-0000-0000-0000-000000000000"
}

# 기존 OIDC provider 참조
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# ==================== CloudWatch Logs ====================

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}-${var.environment}"
  retention_in_days = 30

  tags = {
    Environment = var.environment
  }
}

# ==================== IAM: Task Execution Role ====================
# ECS 에이전트가 사용 (ECR pull, CloudWatch Logs, Secrets Manager)

resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-${var.environment}-ecs-execution"

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
  name = "${var.project_name}-${var.environment}-ecs-task"

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

# ==================== GitHub Actions OIDC (prod용 Role) ====================

resource "aws_iam_role" "github_actions" {
  name = "${var.project_name}-${var.environment}-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/main"
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
  name        = "${var.project_name}-${var.environment}-alb-sg"
  description = "ALB security group (${var.environment})"
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
    Name = "${var.project_name}-${var.environment}-alb-sg"
  }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-${var.environment}-ecs-tasks-sg"
  description = "ECS tasks security group (${var.environment})"
  vpc_id      = data.aws_vpc.main.id

  # ALB에서 오는 트래픽만 허용
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # 외부 접근 (RDS, ElastiCache, ECR, S3 등)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ecs-tasks-sg"
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

# ==================== ALB (prod 전용) ====================

module "alb" {
  source = "../ecs/modules/alb"

  # 리소스 이름 충돌 방지: relay-platform-prod-alb
  project_name        = "${var.project_name}-${var.environment}"
  environment         = var.environment
  vpc_id              = data.aws_vpc.main.id
  subnet_ids          = local.subnet_ids_unique_az
  security_group_id   = aws_security_group.alb.id
  acm_certificate_arn = local.acm_certificate_arn
}

# ==================== ECS Services ====================

locals {
  common_env_vars = [
    { name = "DJANGO_SETTINGS_MODULE", value = "config.settings.prod" },
    { name = "USE_S3_STORAGE", value = "True" },
    { name = "AWS_REGION_NAME", value = var.aws_region },
    { name = "AWS_STORAGE_BUCKET_NAME", value = var.s3_bucket_names[0] },
    { name = "ALLOWED_HOSTS", value = "${var.acm_domain},${var.acm_domain_www},*" },
    { name = "CSRF_TRUSTED_ORIGINS", value = "https://${var.acm_domain},https://${var.acm_domain_www}" },
    { name = "REACT_FRONTEND_URL", value = "https://${var.acm_domain_www}" },
    { name = "SPA_FRONTEND_URL", value = "https://${var.acm_domain_www}" },
    { name = "SLACK_REDIRECT_URI", value = "https://${var.acm_domain_www}/api/v1/integrations/slack/callback/" },
    { name = "NOTION_REDIRECT_URI", value = "https://${var.acm_domain_www}/api/v1/integrations/notion/callback/" },
    { name = "GOOGLE_CALENDAR_REDIRECT_URI", value = "https://${var.acm_domain_www}/api/v1/integrations/google_calendar/callback/" },
    { name = "GMAIL_REDIRECT_URI", value = "https://${var.acm_domain_www}/api/v1/integrations/gmail/callback/" },
    { name = "OUTLOOK_CALENDAR_REDIRECT_URI", value = "https://${var.acm_domain_www}/api/v1/integrations/outlook_calendar/callback/" },
    { name = "OUTLOOK_MAIL_REDIRECT_URI", value = "https://${var.acm_domain_www}/api/v1/integrations/outlook_mail/callback/" },
    { name = "TEAMS_REDIRECT_URI", value = "https://${var.acm_domain_www}/api/v1/integrations/teams/callback/" },
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
  source = "../ecs/modules/ecs_service"

  project_name       = var.project_name
  environment        = var.environment
  service_name       = "web"
  cluster_id         = data.aws_ecs_cluster.main.id
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
  target_group_arn   = module.alb.target_group_arn
  log_group_name     = aws_cloudwatch_log_group.ecs.name
  environment_variables = concat(local.common_env_vars, [
    { name = "PROCESS_TYPE", value = "web" },
    { name = "RUN_PREDEPLOY", value = "true" },
  ])
  secrets = local.common_secrets

  depends_on = [module.alb]
}

module "worker" {
  source = "../ecs/modules/ecs_service"

  project_name       = var.project_name
  environment        = var.environment
  service_name       = "worker"
  cluster_id         = data.aws_ecs_cluster.main.id
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
  source = "../ecs/modules/ecs_service"

  project_name       = var.project_name
  environment        = var.environment
  service_name       = "beat"
  cluster_id         = data.aws_ecs_cluster.main.id
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

# ==================== WAF ====================

# dev CloudFront가 주입하는 X-Origin-Verify 헤더 검증용 시크릿 (ecs/ state에서 생성)
data "aws_secretsmanager_secret_version" "dev_origin_verify" {
  secret_id = "${var.project_name}-${var.dev_environment}/cloudfront-origin-verify"
}

resource "aws_wafv2_web_acl" "main" {
  name        = "${var.project_name}-${var.environment}-waf"
  scope       = "REGIONAL"
  description = "WAF for ${var.project_name} ALB"

  default_action {
    allow {}
  }

  # dev.relay.example.com 호스트로 온 요청 중 CloudFront 시크릿 헤더가 없으면 차단
  # → prod 트래픽은 Host 조건에 걸리지 않아 영향 없음
  rule {
    name     = "DevOriginVerify"
    priority = 5

    action {
      block {}
    }

    statement {
      and_statement {
        statement {
          byte_match_statement {
            search_string         = var.dev_acm_domain
            positional_constraint = "EXACTLY"
            field_to_match {
              single_header {
                name = "host"
              }
            }
            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
        statement {
          not_statement {
            statement {
              byte_match_statement {
                search_string         = data.aws_secretsmanager_secret_version.dev_origin_verify.secret_string
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header {
                    name = "x-origin-verify"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "DevOriginVerify"
      sampled_requests_enabled   = true
    }
  }

  # relay.example.com / www.relay.example.com 호스트로 온 요청 중 prod CloudFront 시크릿 헤더가 없으면 차단
  rule {
    name     = "ProdOriginVerify"
    priority = 6

    action {
      block {}
    }

    statement {
      and_statement {
        statement {
          or_statement {
            statement {
              byte_match_statement {
                search_string         = var.acm_domain
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header {
                    name = "host"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }
            statement {
              byte_match_statement {
                search_string         = var.acm_domain_www
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header {
                    name = "host"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }
          }
        }
        statement {
          not_statement {
            statement {
              byte_match_statement {
                search_string         = aws_secretsmanager_secret_version.origin_verify.secret_string
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header {
                    name = "x-origin-verify"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ProdOriginVerify"
      sampled_requests_enabled   = true
    }
  }

  # Host 헤더가 우리 도메인 화이트리스트에 없으면 차단.
  # 봇 스캐너가 ALB 의 public IP 를 직접 두드리는 트래픽 차단용 — 기존
  # OriginVerify 룰은 Host = 우리 도메인일 때만 평가하므로 IP 직접 스캔이
  # ECS 까지 도달했었음. WAF sample 분석 결과 이 IP 스캔이 트래픽의 ~80%.
  # ALB 의 target health check 는 WAF 를 거치지 않으므로 영향 없음.
  rule {
    name     = "BlockNonAllowlistHost"
    priority = 7

    action {
      block {}
    }

    statement {
      not_statement {
        statement {
          or_statement {
            statement {
              byte_match_statement {
                search_string         = var.acm_domain
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header {
                    name = "host"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }
            statement {
              byte_match_statement {
                search_string         = var.acm_domain_www
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header {
                    name = "host"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }
            statement {
              byte_match_statement {
                search_string         = var.dev_acm_domain
                positional_constraint = "EXACTLY"
                field_to_match {
                  single_header {
                    name = "host"
                  }
                }
                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "BlockNonAllowlistHost"
      sampled_requests_enabled   = true
    }
  }

  # 커스텀 룰: .php 확장자 요청 차단
  # Django 앱에서 .php URL은 정상 트래픽 없음 — PHPUnit RCE, Laravel/ThinkPHP 스캔 등 봇 트래픽 전부 해당
  rule {
    name     = "BlockPHPExtension"
    priority = 0

    action {
      block {}
    }

    statement {
      byte_match_statement {
        search_string         = ".php"
        positional_constraint = "CONTAINS"
        field_to_match {
          uri_path {}
        }
        text_transformation {
          priority = 0
          type     = "LOWERCASE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "BlockPHPExtension"
      sampled_requests_enabled   = true
    }
  }

  # AWS 관리형 룰: 알려진 악성 입력 패턴 차단 (ThinkPHP RCE, Log4Shell, SSRF 등)
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesKnownBadInputsRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # AWS 관리형 룰: 일반적인 웹 공격 방어 (SQLi, XSS 등)
  # 파일 업로드/다운로드/음성 경로는 바이너리 POST로 인한 오탐 방지를 위해 제외.
  # /api/v1/ai/ 는 SizeRestrictions_BODY 오탐 방지 — summary/translate 같은
  # LLM 요청은 transcript + system prompt + template 조합이 기본 8,192 byte
  # body 검사 한도를 자연스럽게 넘어가서 긴 회의는 전부 403으로 block 됨
  # (재현: payload > 8KB 에서 ALB WAF가 nginx-style 403 HTML 반환).
  # 제외 경로:
  # /presentation-coach/, /practice/api/, /admin/, /speech/,
  # /users/profile/, /conversation-log/practice/, /api/v1/ai/,
  # /api/v1/practice/sessions/ (오디오 업로드 multipart body),
  # /api/v1/presentation/ (슬라이드 업로드 + STT 오디오 + LLM payload),
  # /api/v1/speech/, /api/v1/ai-tutor/, /api/v1/trio-talk/,
  # /api/v1/conversations/ (오디오/LLM body 오탐 예방)
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        scope_down_statement {
          not_statement {
            statement {
              or_statement {
                statement {
                  byte_match_statement {
                    search_string         = "/presentation-coach/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/practice/api/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/admin/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/speech/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/users/profile/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/conversation-log/practice/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/ai/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/practice/sessions/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/presentation/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/speech/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/ai-tutor/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/trio-talk/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/conversations/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesCommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # AWS 관리형 룰: SQL Injection 방어
  # 제외 경로는 CommonRuleSet 과 동일 유지 — /api/v1/ai/ 도 자연어 LLM payload
  # 특성상 SQLi false-positive 여지 (단어 'select', 'union' 등)가 있어 제외.
  rule {
    name     = "AWSManagedRulesSQLiRuleSet"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"

        scope_down_statement {
          not_statement {
            statement {
              or_statement {
                statement {
                  byte_match_statement {
                    search_string         = "/presentation-coach/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/practice/api/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/admin/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/speech/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/users/profile/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/conversation-log/practice/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/ai/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/practice/sessions/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/presentation/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/speech/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/ai-tutor/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/trio-talk/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/api/v1/conversations/"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "LOWERCASE"
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesSQLiRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # Rate limiting: 5분간 동일 IP에서 2000건 초과 시 차단
  rule {
    name     = "RateLimitRule"
    priority = 4

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitRule"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-${var.environment}-waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = module.alb.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}
