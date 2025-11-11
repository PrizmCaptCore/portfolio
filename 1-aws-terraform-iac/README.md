# AWS Terraform Infrastructure

Production-ready Terraform modules for deploying ML compute infrastructure on AWS.

## Overview

This module provisions a complete AWS environment for MLOps workloads:
- EC2 instances with auto-scaling capability
- IAM roles and policies following least-privilege principles
- Security groups with proper network isolation
- CloudWatch logging and monitoring
- Automated agent deployment via cloud-init

## Features

- **Cost Optimization**: Spot instance support with fallback to on-demand
- **Security**: IAM instance profiles, encrypted EBS volumes
- **Monitoring**: CloudWatch logs and metrics
- **Automation**: Full infrastructure as code with Terraform
- **Flexibility**: Parameterized for multiple environments

## Architecture

```
┌─────────────────────────────────────────┐
│           AWS Account                    │
│                                          │
│  ┌────────────────────────────────────┐ │
│  │          VPC                        │ │
│  │  ┌──────────────────────────────┐  │ │
│  │  │   Security Group              │  │ │
│  │  │   - SSH (22)                  │  │ │
│  │  │   - HTTP (80)                 │  │ │
│  │  │   - HTTPS (443)               │  │ │
│  │  └──────────────────────────────┘  │ │
│  │                                     │ │
│  │  ┌──────────────────────────────┐  │ │
│  │  │   EC2 Instance                │  │ │
│  │  │   - IAM Instance Profile      │  │ │
│  │  │   - Elastic IP                │  │ │
│  │  │   - User Data (cloud-init)    │  │ │
│  │  └──────────────────────────────┘  │ │
│  │                                     │ │
│  │  ┌──────────────────────────────┐  │ │
│  │  │   IAM Role                    │  │ │
│  │  │   - S3 access                 │  │ │
│  │  │   - CloudWatch logs           │  │ │
│  │  │   - EC2 describe              │  │ │
│  │  └──────────────────────────────┘  │ │
│  └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

## Usage

```hcl
module "mlops_agent" {
  source = "./modules/mlops-compute"

  aws_region      = "us-west-2"
  environment     = "production"
  instance_type   = "t3.xlarge"
  disk_size       = 100
  ssh_public_key  = file("~/.ssh/id_rsa.pub")

  # MLOps agent configuration
  agent_server_url = "https://mlops-server.example.com"
  agent_access_key = var.agent_access_key
  agent_secret_key = var.agent_secret_key
}
```

## Modules

### mlops-compute

Provisions EC2 compute instances for ML workloads with:
- Automatic OS patching via user data
- ML framework pre-installation
- Agent auto-registration
- S3 access for artifacts

### networking

Sets up VPC, subnets, and security groups with:
- Public/private subnet separation
- NAT gateway for private subnets
- Security group rules for ML services

### iam-roles

Creates IAM roles and policies for:
- EC2 instance profiles
- S3 bucket access
- CloudWatch logging
- EC2 management permissions

## Variables

| Name | Description | Type | Default |
|------|-------------|------|---------|
| aws_region | AWS region | string | us-west-2 |
| environment | Environment name | string | dev |
| instance_type | EC2 instance type | string | t3.medium |
| disk_size | Root EBS volume size (GB) | number | 50 |
| ssh_public_key | SSH public key | string | - |

## Outputs

| Name | Description |
|------|-------------|
| instance_id | EC2 instance ID |
| public_ip | Elastic IP address |
| instance_role_arn | IAM role ARN |
| security_group_id | Security group ID |

## Cost Optimization

- Uses Spot instances by default (60% cost savings)
- Implements auto-stop for idle instances
- Right-sized instance recommendations
- Encrypted EBS volumes at no extra cost

## Security Best Practices

- ✅ IAM roles instead of access keys
- ✅ Encrypted EBS volumes
- ✅ Security groups with minimal ports
- ✅ No hardcoded credentials
- ✅ CloudWatch logging enabled
- ✅ VPC isolation

## Requirements

- Terraform >= 1.0
- AWS Provider ~> 5.0
- Valid AWS credentials configured

## License

See main repository LICENSE file.
