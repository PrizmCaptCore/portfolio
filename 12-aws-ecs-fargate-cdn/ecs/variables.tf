variable "project_name" {
  type    = string
  default = "relay-platform"
}

variable "environment" {
  type    = string
  default = "dev"
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
  default = "dev-latest"
}

variable "acm_domain" {
  type    = string
  default = "dev.relay.example.com"
}

variable "spa_bucket_name" {
  type    = string
  default = "relay-platform-dev-spa"
}

variable "shared_alb_name" {
  type    = string
  default = "relay-platform-prod-alb"
}

variable "s3_bucket_names" {
  type    = list(string)
  default = ["relay-data"]
}

variable "github_repo" {
  description = "GitHub repository (org/repo)"
  type        = string
  default     = "relay-technologies/relay_web"
}

variable "rds_security_group_id" {
  description = "RDS security group ID (relaydb)"
  type        = string
  default     = "sg-0aaaa1111bbbb2222"
}

variable "elasticache_security_group_id" {
  description = "ElastiCache security group ID (celery-broker-prod, shared)"
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
