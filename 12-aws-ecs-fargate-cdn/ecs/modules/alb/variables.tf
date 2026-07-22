variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "acm_certificate_arn" {
  type = string
}

variable "health_check_path" {
  type    = string
  default = "/health-check/"
}
