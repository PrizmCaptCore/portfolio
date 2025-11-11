output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.mlops_agent.id
}

output "instance_public_ip" {
  description = "Elastic IP address assigned to the instance"
  value       = aws_eip.mlops_agent.public_ip
}

output "instance_private_ip" {
  description = "Private IP address of the instance"
  value       = aws_instance.mlops_agent.private_ip
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.mlops_agent.id
}

output "iam_role_arn" {
  description = "IAM role ARN"
  value       = aws_iam_role.mlops_agent_role.arn
}

output "iam_role_name" {
  description = "IAM role name"
  value       = aws_iam_role.mlops_agent_role.name
}

output "instance_profile_arn" {
  description = "IAM instance profile ARN"
  value       = aws_iam_instance_profile.mlops_agent_profile.arn
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ~/.ssh/id_rsa ubuntu@${aws_eip.mlops_agent.public_ip}"
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.mlops_agent.name
}
