# 이 파일은 포트폴리오용으로 sanitize 되었습니다: 계정 ID / SG ID / ARN / 도메인 / 버킷명 / 프로파일 등 식별값을 예시값으로 치환.

terraform {
  backend "s3" {
    bucket         = "relay-tf-state"
    key            = "relay-platform/prod/terraform.tfstate"
    region         = "ap-northeast-2"
    encrypt        = true
    dynamodb_table = "relay-tf-lock"
    profile        = "default"
  }
}
