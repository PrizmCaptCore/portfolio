# AWS Terraform Infrastructure as Code

Production-ready Terraform modules for multi-VPC AWS architecture with security-first design.

## Architecture Overview

This infrastructure implements a **dual-VPC architecture** with complete network isolation:
- **Isolated VPC**: Private workloads with SSH access only (from trusted IPs)
- **Service VPC**: Public-facing services with HTTP/HTTPS only (NO SSH)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Account (us-west-2)                         │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                          ISOLATED VPC (10.0.0.0/16)                   │  │
│  │                      Private Workloads & ML Training                  │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │  Private Subnets (10.0.0.0/20, 10.0.16.0/20, 10.0.32.0/20)      │ │  │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │ │  │
│  │  │  │   ML Agent  │  │   Training  │  │  Jupyter    │             │ │  │
│  │  │  │   Instance  │  │   Instance  │  │  Notebook   │             │ │  │
│  │  │  │             │  │             │  │             │             │ │  │
│  │  │  │ SSH: ✓      │  │ SSH: ✓      │  │ SSH: ✓      │             │ │  │
│  │  │  │ (Trusted IP)│  │ (Trusted IP)│  │ (Trusted IP)│             │ │  │
│  │  │  └─────────────┘  └─────────────┘  └─────────────┘             │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │  NAT Gateway (outbound only)                                     │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  │  Security Group: isolated-ssh-sg                                      │  │
│  │    Ingress: TCP 22 from 1.2.3.4/32 (Your IP)                         │  │
│  │    Egress: ALL                                                        │  │
│  └────────────────────────────────────┬───────────────────────────────────┘  │
│                                       │                                       │
│                          VPC Peering (Optional)                               │
│                                       │                                       │
│  ┌────────────────────────────────────▼───────────────────────────────────┐  │
│  │                          SERVICE VPC (10.1.0.0/16)                     │  │
│  │                       Public-Facing Services (NO SSH)                  │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │  Public Subnets (10.1.0.0/20, 10.1.16.0/20)                      │ │  │
│  │  │  ┌───────────────────────────────────────────────────────────┐   │ │  │
│  │  │  │         Application Load Balancer (ALB)                   │   │ │  │
│  │  │  │                                                            │   │ │  │
│  │  │  │  api.mlops.example.com  ──┐                              │   │ │  │
│  │  │  │  *.mlops.example.com      │  Route53 + ACM Certificate   │   │ │  │
│  │  │  │                            └─► HTTPS (443)                │   │ │  │
│  │  │  │                               HTTP (80) → 301 Redirect    │   │ │  │
│  │  │  └────────────────────────────────────────────────────────┘   │ │  │
│  │  │                                │                               │ │  │
│  │  └────────────────────────────────┼───────────────────────────────┘ │  │
│  │                                   │                                  │  │
│  │  ┌────────────────────────────────▼───────────────────────────────┐ │  │
│  │  │  Private Subnets (10.1.160.0/20, 10.1.176.0/20)               │ │  │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐    │ │  │
│  │  │  │  App Server  │  │  App Server  │  │   RDS Postgres   │    │ │  │
│  │  │  │              │  │              │  │   Multi-AZ       │    │ │  │
│  │  │  │  SSH: ✗      │  │  SSH: ✗      │  │                  │    │ │  │
│  │  │  │  HTTP: ✓     │  │  HTTP: ✓     │  │  Port: 5432      │    │ │  │
│  │  │  │  (from ALB)  │  │  (from ALB)  │  │  (from App only) │    │ │  │
│  │  │  └──────────────┘  └──────────────┘  └──────────────────┘    │ │  │
│  │  │                                                                │ │  │
│  │  │  ┌──────────────┐  ┌──────────────┐                          │ │  │
│  │  │  │  Redis       │  │  ElastiCache │                          │ │  │
│  │  │  │  Port: 6379  │  │  Memcached   │                          │ │  │
│  │  │  │  (from App)  │  │  Port: 11211 │                          │ │  │
│  │  │  └──────────────┘  └──────────────┘                          │ │  │
│  │  └────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │  │
│  │  │  NAT Gateways (Multi-AZ for high availability)                  │ │  │
│  │  └──────────────────────────────────────────────────────────────────┘ │  │
│  │                                                                        │  │
│  │  Security Groups:                                                      │  │
│  │    ├─ alb-sg: 80/443 from 0.0.0.0/0                                  │  │
│  │    ├─ app-server-sg: 80/443/8000 from ALB only (NO SSH)              │  │
│  │    ├─ rds-sg: 5432 from app-server-sg only                           │  │
│  │    └─ redis-sg: 6379 from app-server-sg only                         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  VPC Endpoints (Gateway)                                           │     │
│  │  ├─ S3 Endpoint (both VPCs)                                        │     │
│  │  └─ DynamoDB Endpoint (optional)                                   │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │  Route 53                                                          │     │
│  │  ├─ api.mlops.example.com → ALB                                    │     │
│  │  ├─ *.mlops.example.com → ALB (wildcard)                           │     │
│  │  └─ ACM Certificate Validation Records                             │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Security Design Principles

### 1. **Network Isolation**
- **Isolated VPC**: For sensitive workloads (ML training, data processing)
  - SSH access from trusted IPs only
  - No public-facing services
  - Outbound internet via NAT Gateway

- **Service VPC**: For public-facing applications
  - **NO SSH ACCESS** to application servers
  - Only HTTP/HTTPS (80/443) exposed via ALB
  - Private subnets for all application infrastructure

### 2. **Defense in Depth**
```
Layer 1: Network (VPC isolation, subnet segregation)
Layer 2: Security Groups (port-level access control)
Layer 3: IAM (role-based access, no hardcoded credentials)
Layer 4: Application (authentication via Cognito)
Layer 5: Encryption (TLS, encrypted EBS volumes)
```

### 3. **Zero Trust Principles**
- No SSH access to production servers
- All access via bastion host in isolated VPC
- Service-to-service communication via security groups
- Encrypted data in transit and at rest

## File Structure

```
1-aws-terraform-iac/
├── README.md              # This file
├── main.tf               # EC2 instance configuration
├── vpc.tf                # Dual-VPC architecture
├── security_groups.tf    # Security group rules
├── alb.tf                # Application Load Balancer + Route53
├── variables.tf          # Input variables
├── userdata.sh           # EC2 initialization script
└── .gitignore            # Ignore sensitive files
```

## Components

### 1. VPC Configuration ([vpc.tf](vpc.tf))

**Isolated VPC:**
- 3 private subnets across AZs
- NAT Gateway for outbound traffic
- VPC endpoints for S3 (no internet needed)
- SSH access from trusted IPs only

**Service VPC:**
- 3 public subnets (for ALB)
- 3 private subnets (for app servers)
- Multi-AZ NAT Gateways for HA
- Internet Gateway for ALB

**VPC Peering** (optional):
- Allows cross-VPC communication
- Controlled via security groups

### 2. Security Groups ([security_groups.tf](security_groups.tf))

**Isolated VPC:**
- `isolated-ssh-sg`: SSH (22) from trusted CIDRs only
- `isolated-internal-sg`: Inter-VPC communication

**Service VPC:**
- `alb-sg`: HTTP/HTTPS from internet (0.0.0.0/0)
- `app-server-sg`: HTTP/HTTPS from ALB only (**NO SSH**)
- `rds-sg`: PostgreSQL (5432) from app servers only
- `redis-sg`: Redis (6379) from app servers only

### 3. Application Load Balancer ([alb.tf](alb.tf))

**Features:**
- Multi-AZ deployment
- HTTP → HTTPS redirect (301)
- SSL/TLS termination with ACM
- Path-based routing (`/api/*`, `/admin/*`)
- Cognito authentication for admin routes
- Access logs to S3
- Health checks for target groups

**Route53 Integration:**
- A records for ALB
- Wildcard subdomain support
- Automatic ACM certificate validation

### 4. EC2 Instances ([main.tf](main.tf))

**Features:**
- IAM instance profiles (no access keys)
- Encrypted EBS volumes
- CloudWatch logging
- User data for automated setup
- Spot instance support

## Usage

### Prerequisites

```bash
# Install Terraform
brew install terraform  # macOS
# or
wget https://releases.hashicorp.com/terraform/1.6.0/terraform_1.6.0_linux_amd64.zip

# Configure AWS credentials
aws configure
```

### Basic Deployment

```hcl
# terraform.tfvars
project_name         = "mlops-prod"
environment          = "production"
aws_region           = "us-west-2"
availability_zones   = ["us-west-2a", "us-west-2b", "us-west-2c"]

# VPC Configuration
isolated_vpc_cidr    = "10.0.0.0/16"
service_vpc_cidr     = "10.1.0.0/16"
enable_vpc_peering   = false

# Security
trusted_ssh_cidrs    = ["1.2.3.4/32"]  # Your office IP

# ALB & Route53
domain_name          = "mlops.example.com"
subdomain_name       = "api"

# EC2
instance_type        = "t3.xlarge"
disk_size            = 100
ssh_public_key       = file("~/.ssh/id_rsa.pub")
```

```bash
# Initialize Terraform
terraform init

# Plan deployment
terraform plan -out=tfplan

# Apply changes
terraform apply tfplan

# Destroy (when done)
terraform destroy
```

### Advanced: Multi-Environment

```bash
# Development
terraform workspace new dev
terraform apply -var-file=environments/dev.tfvars

# Production
terraform workspace new prod
terraform apply -var-file=environments/prod.tfvars
```

## Security Best Practices

### ✅ Implemented

- [x] **No SSH to production servers** (service VPC)
- [x] **Encrypted EBS volumes** (AWS KMS)
- [x] **Security groups with least privilege**
- [x] **IAM roles instead of access keys**
- [x] **VPC isolation** (dual-VPC architecture)
- [x] **HTTPS only** (HTTP redirects to HTTPS)
- [x] **Multi-AZ deployment** for high availability
- [x] **CloudWatch logging** enabled
- [x] **Private subnets** for all backend services
- [x] **VPC endpoints** for AWS services (no internet)

### 🔒 Additional Recommendations

- Use AWS Secrets Manager for credentials
- Enable AWS GuardDuty for threat detection
- Implement AWS Config for compliance
- Use AWS Systems Manager Session Manager instead of SSH
- Enable VPC Flow Logs
- Implement AWS WAF on ALB

## Cost Optimization

| Resource | Monthly Cost (est.) | Notes |
|----------|---------------------|-------|
| NAT Gateway (3x) | ~$100 | Multi-AZ for HA |
| ALB | ~$20 | Plus data transfer |
| EC2 t3.xlarge | ~$120 | Or use Spot (60% savings) |
| EBS gp3 (100GB) | ~$8 | Per instance |
| Route53 | ~$1 | Plus query charges |
| **Total** | **~$250/month** | For basic setup |

**Savings Tips:**
- Use Spot instances for non-critical workloads
- Enable S3 VPC endpoints (free, saves NAT costs)
- Use single NAT Gateway in dev environments
- Right-size instances based on CloudWatch metrics

## Monitoring & Logging

### CloudWatch Dashboards

```hcl
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          metrics = [
            ["AWS/EC2", "CPUUtilization"],
            ["AWS/ApplicationELB", "TargetResponseTime"],
            ["AWS/RDS", "DatabaseConnections"]
          ]
        }
      }
    ]
  })
}
```

### Alerts

- EC2 CPU > 80%
- ALB 5xx errors > 10/min
- RDS connections > 90% of max
- NAT Gateway bandwidth throttling

## Outputs

After `terraform apply`, you'll get:

```
Outputs:

alb_dns_name = "mlops-alb-123456789.us-west-2.elb.amazonaws.com"
route53_record = "api.mlops.example.com"

isolated_vpc_id = "vpc-0abc123"
service_vpc_id = "vpc-0def456"

isolated_ssh_sg_id = "sg-0111"
app_server_sg_id = "sg-0222"
```

## Troubleshooting

### Cannot SSH to service VPC instances

**Expected behavior** - SSH is intentionally disabled. Use:
1. AWS Systems Manager Session Manager
2. Bastion host in isolated VPC with VPC peering

### ALB returns 503 errors

```bash
# Check target health
aws elbv2 describe-target-health \
  --target-group-arn <target-group-arn>

# Check security group rules
aws ec2 describe-security-groups \
  --group-ids <app-server-sg-id>
```

### High NAT Gateway costs

- Enable S3 VPC endpoint (free)
- Use VPC endpoints for other AWS services
- Consider using single NAT in dev environments

## Requirements

- Terraform >= 1.5.0
- AWS Provider ~> 5.0
- AWS account with appropriate permissions
- Route53 hosted zone (for custom domain)
- ACM certificate (auto-created)

## License

See main repository LICENSE file.

---

**Note**: All resources use tags for cost allocation and management. Adjust `project_name` and `environment` variables to match your naming conventions.
