# ==================== CloudFront + S3 SPA (dev) ====================
# dev.relay.example.com 진입점을 CloudFront로 통일:
#   - default behavior → S3 (SPA: frontend/dist)
#   - /api/*, /admin/*, /static/*, /media/*, /accounts/* → prod ALB (dev-tg)
# ALB 오리진 요청에 X-Origin-Verify 헤더 주입 → prod WAF에서 호스트 조건부 검증

# CloudFront/ACM (us-east-1) 용 provider
provider "aws" {
  alias   = "us_east_1"
  region  = "us-east-1"
  profile = var.aws_profile
}

# 공유 ALB는 prod state에서 관리되므로 data source로 조회
data "aws_lb" "shared" {
  name = var.shared_alb_name
}

# ==================== Shared Secret (CloudFront ↔ ALB) ====================

resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "origin_verify" {
  name = "${var.project_name}-${var.environment}/cloudfront-origin-verify"

  tags = {
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "origin_verify" {
  secret_id     = aws_secretsmanager_secret.origin_verify.id
  secret_string = random_password.origin_verify.result
}

# ==================== S3: SPA Origin ====================

resource "aws_s3_bucket" "spa" {
  bucket = var.spa_bucket_name

  tags = {
    Environment = var.environment
    Purpose     = "spa-hosting"
  }
}

resource "aws_s3_bucket_public_access_block" "spa" {
  bucket                  = aws_s3_bucket.spa.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "spa" {
  bucket = aws_s3_bucket.spa.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "spa" {
  bucket = aws_s3_bucket.spa.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "spa" {
  bucket = aws_s3_bucket.spa.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.spa.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.spa.arn
        }
      }
    }]
  })
}

# ==================== ACM (us-east-1) ====================

resource "aws_acm_certificate" "cloudfront" {
  provider          = aws.us_east_1
  domain_name       = var.acm_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# relay.example.com DNS는 external DNS registrar에서 관리됨 → ACM 검증용 CNAME을 external DNS registrar 콘솔에 수동 추가
# 검증 대기 리소스는 유지 (ACM ISSUED 될 때까지 apply가 대기; 그동안 CNAME 추가)
resource "aws_acm_certificate_validation" "cloudfront" {
  provider        = aws.us_east_1
  certificate_arn = aws_acm_certificate.cloudfront.arn
}

# ==================== CloudFront ====================

resource "aws_cloudfront_origin_access_control" "spa" {
  name                              = "${var.project_name}-${var.environment}-spa-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront 전용 WAF (CLOUDFRONT scope → us-east-1)
resource "aws_wafv2_web_acl" "cloudfront" {
  provider = aws.us_east_1
  name     = "${var.project_name}-${var.environment}-cf-waf"
  scope    = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSManagedRulesKnownBadInputs"
    priority = 0

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
      metric_name                = "cf-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "RateLimit"
    priority = 1

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
      metric_name                = "cf-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-${var.environment}-cf-waf"
    sampled_requests_enabled   = true
  }
}

# ==================== CloudFront Function: SPA router ====================
# Rewrites SPA deep-link paths (e.g., /meetings/abc123) to /index.html at the
# viewer-request stage, so S3 returns the SPA shell and client-side routing
# takes over. Static assets (anything with a file extension) pass through
# untouched; the root "/" is handled by default_root_object.
#
# With this in place we can drop the distribution-wide
# `custom_error_response(404 → /index.html 200)` mapping, which had the side
# effect of hijacking legitimate 404s on `/api/*` (ALB origin) responses and
# serving the SPA HTML to API clients — the Rust summary call would then get
# `200 OK + <!DOCTYPE html>` and fail parsing.
resource "aws_cloudfront_function" "spa_router" {
  name    = "${var.project_name}-${var.environment}-spa-router"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite SPA deep-links to /index.html; avoids the distribution-wide 404 custom_error_response hijacking /api/* responses."
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      // Static asset (anything with a file extension) — hand off to S3 as-is.
      if (/\.[a-zA-Z0-9]{1,6}$/.test(uri)) {
        return request;
      }
      // Root — default_root_object serves index.html.
      if (uri === '/' || uri === '') {
        return request;
      }
      // SPA route — rewrite so S3 returns index.html.
      request.uri = '/index.html';
      return request;
    }
  JS
}

resource "aws_cloudfront_distribution" "spa" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "${var.project_name}-${var.environment} SPA + API"
  aliases             = [var.acm_domain]
  price_class         = "PriceClass_200"
  web_acl_id          = aws_wafv2_web_acl.cloudfront.arn

  # ---- Origins ----
  origin {
    origin_id                = "s3-spa"
    domain_name              = aws_s3_bucket.spa.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.spa.id
  }

  origin {
    origin_id   = "alb-api"
    domain_name = data.aws_lb.shared.dns_name

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  # ---- Default: S3 SPA ----
  default_cache_behavior {
    target_origin_id       = "s3-spa"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # Managed: CachingOptimized
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_router.arn
    }
  }

  # ---- API-ish paths → ALB ----
  dynamic "ordered_cache_behavior" {
    for_each = toset([
      "/api/*",
      "/admin/*",
      "/static/*",
      "/media/*",
      "/accounts/*",
      "/health-check/*",
    ])

    content {
      path_pattern           = ordered_cache_behavior.value
      target_origin_id       = "alb-api"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods         = ["GET", "HEAD"]
      compress               = true

      # Managed: CachingDisabled
      cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
      # Managed: AllViewer (forward all headers/cookies/query)
      origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3"
    }
  }

  # SPA fallback moved to `aws_cloudfront_function.spa_router` (viewer-request
  # URI rewrite on the default behavior). Keeping distribution-wide
  # custom_error_response blocks would cause legitimate 404/403 responses from
  # `alb-api` to be replaced with the SPA HTML, which broke the Rust summary
  # client ("backend returned non-JSON response: <!DOCTYPE html>...").

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.cloudfront.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  tags = {
    Environment = var.environment
  }
}

# DNS (external DNS registrar)
# apply 후 `terraform output` 으로 CloudFront 도메인 확인 → external DNS registrar에서
#   dev  CNAME  <cloudfront_domain_name>
# 레코드로 수동 변경
