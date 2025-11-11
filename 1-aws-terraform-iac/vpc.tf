# VPC Configuration for Multi-Zone Architecture
# - Isolated VPC: Private application workloads (SSH access only)
# - Service VPC: Public-facing services (HTTP/HTTPS only)

# ============================================================================
# Isolated Application VPC
# ============================================================================

resource "aws_vpc" "isolated" {
  cidr_block           = var.isolated_vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "${var.project_name}-isolated-vpc"
    Environment = var.environment
    Purpose     = "isolated-workloads"
  }
}

# Private subnets for isolated workloads
resource "aws_subnet" "isolated_private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.isolated.id
  cidr_block        = cidrsubnet(var.isolated_vpc_cidr, 4, count.index)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name        = "${var.project_name}-isolated-private-${count.index + 1}"
    Environment = var.environment
    Type        = "private"
  }
}

# NAT Gateway for isolated VPC (for outbound traffic only)
resource "aws_eip" "isolated_nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-isolated-nat-eip"
  }
}

resource "aws_nat_gateway" "isolated" {
  count         = var.enable_nat_gateway ? 1 : 0
  allocation_id = aws_eip.isolated_nat[0].id
  subnet_id     = aws_subnet.isolated_private[0].id

  tags = {
    Name = "${var.project_name}-isolated-nat"
  }
}

# Route table for isolated private subnets
resource "aws_route_table" "isolated_private" {
  vpc_id = aws_vpc.isolated.id

  tags = {
    Name = "${var.project_name}-isolated-private-rtb"
  }
}

# Route to NAT Gateway for outbound traffic
resource "aws_route" "isolated_nat" {
  count                  = var.enable_nat_gateway ? 1 : 0
  route_table_id         = aws_route_table.isolated_private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.isolated[0].id
}

# Associate private subnets with route table
resource "aws_route_table_association" "isolated_private" {
  count          = length(aws_subnet.isolated_private)
  subnet_id      = aws_subnet.isolated_private[count.index].id
  route_table_id = aws_route_table.isolated_private.id
}

# ============================================================================
# Service VPC (Public-facing)
# ============================================================================

resource "aws_vpc" "service" {
  cidr_block           = var.service_vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "${var.project_name}-service-vpc"
    Environment = var.environment
    Purpose     = "public-services"
  }
}

# Public subnets for ALB
resource "aws_subnet" "service_public" {
  count                   = length(var.availability_zones)
  vpc_id                  = aws_vpc.service.id
  cidr_block              = cidrsubnet(var.service_vpc_cidr, 4, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name        = "${var.project_name}-service-public-${count.index + 1}"
    Environment = var.environment
    Type        = "public"
  }
}

# Private subnets for application servers
resource "aws_subnet" "service_private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.service.id
  cidr_block        = cidrsubnet(var.service_vpc_cidr, 4, count.index + 10)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name        = "${var.project_name}-service-private-${count.index + 1}"
    Environment = var.environment
    Type        = "private"
  }
}

# Internet Gateway for service VPC
resource "aws_internet_gateway" "service" {
  vpc_id = aws_vpc.service.id

  tags = {
    Name = "${var.project_name}-service-igw"
  }
}

# NAT Gateway for service VPC private subnets
resource "aws_eip" "service_nat" {
  count  = length(var.availability_zones)
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-service-nat-eip-${count.index + 1}"
  }
}

resource "aws_nat_gateway" "service" {
  count         = length(var.availability_zones)
  allocation_id = aws_eip.service_nat[count.index].id
  subnet_id     = aws_subnet.service_public[count.index].id

  tags = {
    Name = "${var.project_name}-service-nat-${count.index + 1}"
  }
}

# Route table for public subnets
resource "aws_route_table" "service_public" {
  vpc_id = aws_vpc.service.id

  tags = {
    Name = "${var.project_name}-service-public-rtb"
  }
}

# Route to Internet Gateway
resource "aws_route" "service_public_internet" {
  route_table_id         = aws_route_table.service_public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.service.id
}

# Associate public subnets with public route table
resource "aws_route_table_association" "service_public" {
  count          = length(aws_subnet.service_public)
  subnet_id      = aws_subnet.service_public[count.index].id
  route_table_id = aws_route_table.service_public.id
}

# Route tables for private subnets (one per AZ for NAT)
resource "aws_route_table" "service_private" {
  count  = length(var.availability_zones)
  vpc_id = aws_vpc.service.id

  tags = {
    Name = "${var.project_name}-service-private-rtb-${count.index + 1}"
  }
}

# Routes to NAT Gateways
resource "aws_route" "service_private_nat" {
  count                  = length(var.availability_zones)
  route_table_id         = aws_route_table.service_private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.service[count.index].id
}

# Associate private subnets with private route tables
resource "aws_route_table_association" "service_private" {
  count          = length(aws_subnet.service_private)
  subnet_id      = aws_subnet.service_private[count.index].id
  route_table_id = aws_route_table.service_private[count.index].id
}

# ============================================================================
# VPC Peering (Optional - for cross-VPC communication)
# ============================================================================

resource "aws_vpc_peering_connection" "isolated_to_service" {
  count       = var.enable_vpc_peering ? 1 : 0
  vpc_id      = aws_vpc.isolated.id
  peer_vpc_id = aws_vpc.service.id
  auto_accept = true

  tags = {
    Name = "${var.project_name}-isolated-to-service-peering"
  }
}

# Peering routes for isolated VPC
resource "aws_route" "isolated_to_service" {
  count                     = var.enable_vpc_peering ? 1 : 0
  route_table_id            = aws_route_table.isolated_private.id
  destination_cidr_block    = var.service_vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.isolated_to_service[0].id
}

# Peering routes for service VPC
resource "aws_route" "service_to_isolated" {
  count                     = var.enable_vpc_peering ? length(aws_route_table.service_private) : 0
  route_table_id            = aws_route_table.service_private[count.index].id
  destination_cidr_block    = var.isolated_vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.isolated_to_service[0].id
}

# ============================================================================
# VPC Endpoints (for AWS services without internet)
# ============================================================================

resource "aws_vpc_endpoint" "s3" {
  for_each = {
    isolated = aws_vpc.isolated.id
    service  = aws_vpc.service.id
  }

  vpc_id            = each.value
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  tags = {
    Name = "${var.project_name}-${each.key}-s3-endpoint"
  }
}

# Associate S3 endpoint with route tables
resource "aws_vpc_endpoint_route_table_association" "isolated_s3" {
  route_table_id  = aws_route_table.isolated_private.id
  vpc_endpoint_id = aws_vpc_endpoint.s3["isolated"].id
}

resource "aws_vpc_endpoint_route_table_association" "service_s3" {
  count           = length(aws_route_table.service_private)
  route_table_id  = aws_route_table.service_private[count.index].id
  vpc_endpoint_id = aws_vpc_endpoint.s3["service"].id
}

# ============================================================================
# Outputs
# ============================================================================

output "isolated_vpc_id" {
  description = "ID of isolated VPC"
  value       = aws_vpc.isolated.id
}

output "service_vpc_id" {
  description = "ID of service VPC"
  value       = aws_vpc.service.id
}

output "isolated_private_subnet_ids" {
  description = "IDs of isolated private subnets"
  value       = aws_subnet.isolated_private[*].id
}

output "service_public_subnet_ids" {
  description = "IDs of service public subnets"
  value       = aws_subnet.service_public[*].id
}

output "service_private_subnet_ids" {
  description = "IDs of service private subnets"
  value       = aws_subnet.service_private[*].id
}
