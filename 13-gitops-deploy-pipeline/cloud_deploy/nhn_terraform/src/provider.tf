# Define required providers
terraform {
  # tfstate 원격 저장소: NHN Object Storage(S3 호환) 버킷.
  # CI 러너는 매 실행마다 초기화되므로 원격 backend가 없으면 인스턴스가 중복 생성됩니다.
  #
  # 버킷 이름은 코드에 두지 않고 partial backend config 로 주입합니다.
  #   - GitHub Actions: terraform init -backend-config="bucket=${{ vars.TFSTATE_BUCKET }}"
  #   - 로컬:           cp backend.hcl.example backend.hcl 후 terraform init -backend-config=backend.hcl
  # 자격 증명은 환경변수로 주입: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  #   - GitHub Actions: secrets NHN_S3_ACCESS_KEY / NHN_S3_SECRET_KEY (워크플로우 env 참고)
  #   - 로컬: 콘솔에서 발급한 S3 API 자격 증명 사용 (README 참고)
  # 주의: S3 호환 스토리지라 잠금(lock)은 없음 — 동시 apply 방지는
  # 워크플로우의 concurrency 그룹이 담당하고, 로컬 apply는 CI와 겹치지 않게 할 것.
  backend "s3" {
    key    = "nhn/terraform.tfstate"
    region = "KR1" # SigV4 서명 리전 (NHN은 대문자 KR1)
    endpoints = {
      s3 = "https://kr1-api-object-storage.nhncloudservice.com"
    }
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    use_path_style              = true
    skip_s3_checksum            = true # S3 호환 스토리지는 AWS 체크섬 헤더 미지원인 경우가 많음
  }

  required_providers {
    nhncloud = {
      source  = "nhn-cloud/nhncloud"
      version = "1.0.9"
      # nhn cloud의 terraform provider는 현재는 1.0.9가 최신이나, 매번 체크하여 호환을 맞춰주셔야 합니다.
      # https://registry.terraform.io/providers/nhn-cloud/nhncloud/latest
    }
  }
}

# Configure the nhncloud Provider
# 설정값은 여기에 쓰지 않고 환경변수로 주입합니다. 이 provider는 OpenStack 기반이라
# OS_USERNAME, OS_TENANT_ID, OS_PASSWORD, OS_AUTH_URL, OS_REGION_NAME을 자동으로 읽습니다.
#   - 로컬:          set -a; source env/.env; set +a  후 terraform 실행
#   - GitHub Actions: Secrets를 워크플로우의 env: 블록으로 주입 (파일 생성 불필요)
provider "nhncloud" {}
