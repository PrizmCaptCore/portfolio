variable "project_name" {
  type    = string
  default = "relay-platform"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "aws_profile" {
  type    = string
  default = "default"
}

variable "ecr_repository_url" {
  type    = string
  default = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/relay-platform"
}

variable "image_tag" {
  type    = string
  default = "prod-latest"
}

variable "acm_domain" {
  type        = string
  default     = "relay.example.com"
  description = "Production ACM certificate domain (apex)"
}

variable "acm_domain_www" {
  type    = string
  default = "www.relay.example.com"
}

variable "spa_bucket_name" {
  type    = string
  default = "relay-platform-prod-spa"
}

variable "dev_environment" {
  type        = string
  default     = "dev"
  description = "Dev environment name (used to look up shared secret)"
}

variable "dev_acm_domain" {
  type        = string
  default     = "dev.relay.example.com"
  description = "Dev host value to match in WAF rule"
}

variable "s3_bucket_names" {
  type    = list(string)
  default = ["relay-data-prod"]
}

variable "github_repo" {
  description = "GitHub repository (org/repo)"
  type        = string
  default     = "relay-technologies/relay_web"
}

variable "rds_security_group_id" {
  description = "RDS security group ID (relay-prod-db)"
  type        = string
  default     = "sg-0aaaa7777bbbb8888"
}

variable "elasticache_security_group_id" {
  description = "ElastiCache security group ID (celery-broker-prod)"
  type        = string
  default     = "sg-0cccc3333dddd4444"
}

# Web
variable "web_cpu" {
  type    = number
  default = 256
}

variable "web_memory" {
  type    = number
  default = 512
}

variable "web_desired_count" {
  type    = number
  default = 1
}

# Worker
variable "worker_cpu" {
  type    = number
  default = 256
}

variable "worker_memory" {
  type    = number
  default = 512
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

# Beat
variable "beat_cpu" {
  type    = number
  default = 256
}

variable "beat_memory" {
  type    = number
  default = 512
}

variable "beat_desired_count" {
  type    = number
  default = 1
}
