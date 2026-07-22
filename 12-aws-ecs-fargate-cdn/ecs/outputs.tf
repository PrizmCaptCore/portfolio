output "cluster_name" {
  value = module.ecs_cluster.cluster_name
}

output "alb_dns_name" {
  value = "Managed by prod terraform (relay-platform-prod-alb)"
}

output "web_service_name" {
  value = module.web.service_name
}

output "worker_service_name" {
  value = module.worker.service_name
}

output "beat_service_name" {
  value = module.beat.service_name
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}

output "spa_bucket_name" {
  value = aws_s3_bucket.spa.bucket
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.spa.id
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.spa.domain_name
}

# external DNS registrar에 추가할 ACM 검증용 CNAME (apply 시작 후 출력됨)
output "acm_validation_records" {
  value = [
    for dvo in aws_acm_certificate.cloudfront.domain_validation_options : {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  ]
}

output "origin_verify_secret_name" {
  value = aws_secretsmanager_secret.origin_verify.name
}
