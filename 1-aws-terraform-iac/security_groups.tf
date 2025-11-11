# Security Groups for Multi-VPC Architecture
# - Isolated VPC: SSH access only from trusted IPs
# - Service VPC: HTTP/HTTPS only, NO SSH

# ============================================================================
# Isolated VPC Security Groups
# ============================================================================

# Security group for isolated workloads (SSH access only)
resource "aws_security_group" "isolated_ssh" {
  name_description = "${var.project_name}-isolated-ssh-sg"
  description      = "Allow SSH access from trusted IPs only"
  vpc_id           = aws_vpc.isolated.id

  # Inbound SSH from trusted IPs only
  ingress {
    description = "SSH from trusted networks"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.trusted_ssh_cidrs
  }

  # Outbound - allow all for updates and package downloads
  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-isolated-ssh-sg"
    Environment = var.environment
    Purpose     = "ssh-access"
  }
}

# Security group for isolated internal communication
resource "aws_security_group" "isolated_internal" {
  name_description = "${var.project_name}-isolated-internal-sg"
  description      = "Allow internal communication within isolated VPC"
  vpc_id           = aws_vpc.isolated.id

  # Allow all traffic within VPC
  ingress {
    description = "Internal VPC communication"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.isolated_vpc_cidr]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-isolated-internal-sg"
    Environment = var.environment
  }
}

# ============================================================================
# Service VPC Security Groups
# ============================================================================

# Security group for Application Load Balancer
resource "aws_security_group" "alb" {
  name_description = "${var.project_name}-alb-sg"
  description      = "Security group for Application Load Balancer"
  vpc_id           = aws_vpc.service.id

  # HTTP from anywhere
  ingress {
    description = "HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS from anywhere
  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-alb-sg"
    Environment = var.environment
    Purpose     = "load-balancer"
  }
}

# Security group for application servers (NO SSH)
resource "aws_security_group" "app_server" {
  name_description = "${var.project_name}-app-server-sg"
  description      = "Security group for application servers - NO SSH ACCESS"
  vpc_id           = aws_vpc.service.id

  # HTTP from ALB only
  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # HTTPS from ALB only
  ingress {
    description     = "HTTPS from ALB"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # Custom application port from ALB
  ingress {
    description     = "Application port from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # NO SSH INGRESS RULE - Enforced at security group level

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-app-server-sg"
    Environment = var.environment
    Purpose     = "application-server"
    NoSSH       = "true"
  }
}

# Security group for RDS database
resource "aws_security_group" "rds" {
  name_description = "${var.project_name}-rds-sg"
  description      = "Security group for RDS database"
  vpc_id           = aws_vpc.service.id

  # PostgreSQL from application servers only
  ingress {
    description     = "PostgreSQL from app servers"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app_server.id]
  }

  # Optional: Allow from isolated VPC for maintenance
  dynamic "ingress" {
    for_each = var.enable_vpc_peering ? [1] : []
    content {
      description = "PostgreSQL from isolated VPC for maintenance"
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = [var.isolated_vpc_cidr]
    }
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-rds-sg"
    Environment = var.environment
    Purpose     = "database"
  }
}

# Security group for Redis/ElastiCache
resource "aws_security_group" "redis" {
  name_description = "${var.project_name}-redis-sg"
  description      = "Security group for Redis cluster"
  vpc_id           = aws_vpc.service.id

  # Redis from application servers only
  ingress {
    description     = "Redis from app servers"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app_server.id]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-redis-sg"
    Environment = var.environment
    Purpose     = "cache"
  }
}

# ============================================================================
# Cross-VPC Security Group (if peering enabled)
# ============================================================================

resource "aws_security_group" "cross_vpc_communication" {
  count            = var.enable_vpc_peering ? 1 : 0
  name_description = "${var.project_name}-cross-vpc-sg"
  description      = "Allow specific communication between VPCs"
  vpc_id           = aws_vpc.service.id

  # Allow specific ports from isolated VPC
  ingress {
    description = "Internal API from isolated VPC"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.isolated_vpc_cidr]
  }

  egress {
    description = "To isolated VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.isolated_vpc_cidr]
  }

  tags = {
    Name        = "${var.project_name}-cross-vpc-sg"
    Environment = var.environment
  }
}

# ============================================================================
# Outputs
# ============================================================================

output "isolated_ssh_sg_id" {
  description = "Security group ID for SSH access to isolated VPC"
  value       = aws_security_group.isolated_ssh.id
}

output "alb_sg_id" {
  description = "Security group ID for Application Load Balancer"
  value       = aws_security_group.alb.id
}

output "app_server_sg_id" {
  description = "Security group ID for application servers (NO SSH)"
  value       = aws_security_group.app_server.id
}

output "rds_sg_id" {
  description = "Security group ID for RDS database"
  value       = aws_security_group.rds.id
}
