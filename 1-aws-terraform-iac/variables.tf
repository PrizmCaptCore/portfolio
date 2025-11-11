variable "aws_region" {
  description = "AWS region where resources will be created"
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, production)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "instance_type" {
  description = "EC2 instance type for MLOps agent"
  type        = string
  default     = "t3.xlarge"

  validation {
    condition     = can(regex("^t3\\.|^m5\\.|^c5\\.|^r5\\.", var.instance_type))
    error_message = "Instance type must be from t3, m5, c5, or r5 families."
  }
}

variable "disk_size" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 100

  validation {
    condition     = var.disk_size >= 30 && var.disk_size <= 1000
    error_message = "Disk size must be between 30 and 1000 GB."
  }
}

variable "ssh_public_key" {
  description = "SSH public key for instance access"
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^ssh-rsa |^ssh-ed25519 |^ecdsa-sha2-", var.ssh_public_key))
    error_message = "Must be a valid SSH public key."
  }
}

variable "ssh_cidr_blocks" {
  description = "CIDR blocks allowed for SSH access"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "agent_server_url" {
  description = "MLOps agent server URL"
  type        = string
  default     = "https://mlops-server.example.com"

  validation {
    condition     = can(regex("^https://", var.agent_server_url))
    error_message = "Agent server URL must use HTTPS."
  }
}

variable "agent_access_key" {
  description = "MLOps agent access key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "agent_secret_key" {
  description = "MLOps agent secret key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tags" {
  description = "Additional tags to apply to resources"
  type        = map(string)
  default     = {}
}

# ============================================================================
# VPC Configuration Variables
# ============================================================================

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "mlops"
}

variable "isolated_vpc_cidr" {
  description = "CIDR block for isolated VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "service_vpc_cidr" {
  description = "CIDR block for service VPC"
  type        = string
  default     = "10.1.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-west-2a", "us-west-2b", "us-west-2c"]
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnets"
  type        = bool
  default     = true
}

variable "enable_vpc_peering" {
  description = "Enable VPC peering between isolated and service VPCs"
  type        = bool
  default     = false
}

variable "trusted_ssh_cidrs" {
  description = "CIDR blocks allowed for SSH access to isolated VPC"
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.trusted_ssh_cidrs) > 0
    error_message = "At least one trusted SSH CIDR must be specified for security."
  }
}

# ============================================================================
# ALB Configuration Variables
# ============================================================================

variable "enable_deletion_protection" {
  description = "Enable deletion protection for ALB"
  type        = bool
  default     = false
}

variable "domain_name" {
  description = "Domain name for Route53 and ACM certificate"
  type        = string
  default     = "example.com"
}

variable "subdomain_name" {
  description = "Subdomain for ALB (e.g., api.example.com)"
  type        = string
  default     = "api"
}

variable "cognito_user_pool_arn" {
  description = "Cognito User Pool ARN for admin authentication"
  type        = string
  default     = ""
}

variable "cognito_user_pool_client_id" {
  description = "Cognito User Pool Client ID"
  type        = string
  default     = ""
}

variable "cognito_user_pool_domain" {
  description = "Cognito User Pool Domain"
  type        = string
  default     = ""
}
