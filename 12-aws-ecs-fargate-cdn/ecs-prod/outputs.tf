output "cluster_name" {
  value = data.aws_ecs_cluster.main.cluster_name
}

output "alb_dns_name" {
  value = module.alb.alb_dns_name
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

output "origin_verify_secret_name" {
  value = aws_secretsmanager_secret.origin_verify.name
}

output "acm_validation_records" {
  value = [
    for dvo in aws_acm_certificate.cloudfront.domain_validation_options : {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  ]
}
