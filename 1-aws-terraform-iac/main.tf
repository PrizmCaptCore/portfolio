terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Data sources
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Security Group for MLOps Agent
resource "aws_security_group" "mlops_agent" {
  name_prefix = "mlops-agent-"
  description = "Security group for MLOps Agent EC2 instance"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_cidr_blocks
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "mlops-agent-sg-${var.environment}"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM Role for EC2 instance
resource "aws_iam_role" "mlops_agent_role" {
  name = "mlops-agent-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "mlops-agent-role"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# IAM Policy for EC2 instance
resource "aws_iam_role_policy" "mlops_agent_policy" {
  name = "mlops-agent-policy"
  role = aws_iam_role.mlops_agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::mlops-artifacts-*",
          "arn:aws:s3:::mlops-artifacts-*/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeImages",
          "ec2:DescribeVolumes",
          "ec2:DescribeTags"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = "*"
      }
    ]
  })
}

# IAM Instance Profile
resource "aws_iam_instance_profile" "mlops_agent_profile" {
  name = "mlops-agent-profile-${var.environment}"
  role = aws_iam_role.mlops_agent_role.name
}

# SSH Key Pair
resource "aws_key_pair" "mlops_agent" {
  key_name   = "mlops-agent-key-${var.environment}"
  public_key = var.ssh_public_key

  tags = {
    Name        = "mlops-agent-key"
    Environment = var.environment
  }
}

# Random ID for unique naming
resource "random_id" "instance_id" {
  byte_length = 4
}

# User Data script
data "template_file" "userdata" {
  template = file("${path.module}/userdata.sh")

  vars = {
    agent_server_url = var.agent_server_url
    agent_access_key = var.agent_access_key
    agent_secret_key = var.agent_secret_key
    environment      = var.environment
  }
}

# EC2 Instance for MLOps Agent
resource "aws_instance" "mlops_agent" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  key_name      = aws_key_pair.mlops_agent.key_name

  vpc_security_group_ids = [aws_security_group.mlops_agent.id]
  iam_instance_profile   = aws_iam_instance_profile.mlops_agent_profile.name

  user_data = data.template_file.userdata.rendered

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.disk_size
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name        = "mlops-agent-${random_id.instance_id.hex}"
    Environment = var.environment
    Purpose     = "MLOps Agent"
    ManagedBy   = "Terraform"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Elastic IP for the instance
resource "aws_eip" "mlops_agent" {
  instance = aws_instance.mlops_agent.id
  domain   = "vpc"

  tags = {
    Name        = "mlops-agent-eip-${random_id.instance_id.hex}"
    Environment = var.environment
  }

  depends_on = [aws_instance.mlops_agent]
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "mlops_agent" {
  name              = "/aws/ec2/mlops-agent-${var.environment}"
  retention_in_days = 30

  tags = {
    Name        = "mlops-agent-logs"
    Environment = var.environment
  }
}
