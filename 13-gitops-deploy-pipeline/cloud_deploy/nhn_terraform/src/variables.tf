# GitHub Actions에서 TF_VAR_* 환경변수로 주입되는 값들입니다.
# 예: TF_VAR_deploy_repo=your-org/some-product

variable "deploy_repo" {
  description = "배포할 내부 private repo (owner/repo 형식)"
  type        = string
}

variable "deploy_ref" {
  description = "배포할 브랜치 또는 태그"
  type        = string
  default     = "main"
}

variable "deploy_token" {
  description = "private repo를 읽을 수 있는 read-only 토큰 (fine-grained PAT 권장)"
  type        = string
  sensitive   = true
}

variable "keypair_name" {
  description = "SSH 접속용으로 NHN 콘솔에 미리 등록해둔 keypair 이름. SSH 접속이 불필요하면 null 유지."
  type        = string
  default     = null
}

# ---- 인스턴스 형상 (환경별로 TF_VAR_* 로 덮어쓴다) ----

variable "region" {
  description = "NHN Cloud 리전"
  type        = string
  default     = "KR1"
}

variable "instance_name" {
  description = "생성할 인스턴스 이름"
  type        = string
  default     = "app-instance-01"
}

variable "flavor_name" {
  description = "인스턴스 타입(flavor) 이름"
  type        = string
  default     = "m2.c1m2"
}

variable "subnet_name" {
  description = "인스턴스를 붙일 VPC 서브넷 이름 (콘솔 기준)"
  type        = string
  default     = "Default Network"
}

variable "root_volume_gb" {
  description = "루트 볼륨 크기 (GB)"
  type        = number
  default     = 20
}

variable "app_dir" {
  description = "인스턴스에서 제품 repo 를 clone 할 경로"
  type        = string
  default     = "/opt/app"
}
