data "nhncloud_compute_flavor_v2" "app" {
  name = var.flavor_name                 # instance type 이름 (flavor)
}

data "nhncloud_images_image_v2" "ubuntu" {
  # NHN은 주기적으로 이미지를 교체(이름의 날짜 갱신)하므로 이름 고정 대신 정규식으로 조회.
  # 순정 Ubuntu 22.04 서버 이미지만 매치 (Deep Learning/NAT/Container/NVIDIA 변형 제외)
  name_regex  = "^Ubuntu Server 22\\.04\\.[0-9]+ LTS \\("
  most_recent = true
  visibility  = "public"
}

data "nhncloud_networking_vpcsubnet_v2" "app" {
  name = var.subnet_name                 # 기본 서브넷 이름
}
# 배포 환경에 추가 네트워크 서브넷이 걸려있을 수 있음. 정책에 맞춰 이름, id를 확인 후 변경 필요.

# resource "nhncloud_compute_keypair_v2" "main" {
#   name       = "terraform-keypair"
#   public_key = file("~/.ssh/id_rsa.pub") # 내 공개키 등록
# }
# SSH 접속이 필요하면 활성화 후 var.keypair_name 대신 이 리소스를 참조.
# 단, CI(GitHub Actions)에서는 러너에 개인키가 없으므로 콘솔에 등록된 keypair 이름을
# var.keypair_name으로 넘기는 방식을 권장.

resource "nhncloud_compute_instance_v2" "app" {
  name            = var.instance_name
  region          = var.region
  flavor_id       = data.nhncloud_compute_flavor_v2.app.id
  key_pair        = var.keypair_name
  security_groups = ["default"]

  network {
    # 주의: 서브넷 ID(.id)가 아니라 VPC(네트워크) ID를 넣어야 함.
    # 서브넷 ID를 넣으면 apply 시 "Could not find any matching network" 에러 발생.
    uuid = data.nhncloud_networking_vpcsubnet_v2.app.vpc_id
  }

  block_device {
    uuid                  = data.nhncloud_images_image_v2.ubuntu.id
    source_type           = "image"
    destination_type      = "volume"
    boot_index            = 0
    volume_size           = var.root_volume_gb
    delete_on_termination = true
  }

  # 부팅 시 1회 실행되는 cloud-init 스크립트.
  # GitHub Actions에서 입력받은 private repo를 인스턴스가 직접 clone합니다.
  # 주의: deploy_token이 user_data와 tfstate에 남으므로 read-only fine-grained PAT만 사용할 것.
  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    # 로그를 파일 + 시리얼 콘솔 양쪽에 남김. 콘솔로 보내면 SSH 없이
    # os-getConsoleOutput API(콘솔 출력 조회)만으로 원격 디버깅 가능.
    exec > >(tee /var/log/app-deploy.log > /dev/console) 2>&1
    trap 'echo "app-deploy: FAILED at line $LINENO"' ERR
    echo "app-deploy: start"
    export DEBIAN_FRONTEND=noninteractive
    # 부팅 직후 unattended-upgrades가 apt 락을 잡고 있을 수 있어 락 대기 옵션 필수
    apt-get -o DPkg::Lock::Timeout=300 update -y
    apt-get -o DPkg::Lock::Timeout=300 install -y git
    git clone --depth 1 --branch "${var.deploy_ref}" \
      "https://x-access-token:${var.deploy_token}@github.com/${var.deploy_repo}.git" "${var.app_dir}"
    # clone 이후 토큰이 남지 않도록 remote를 토큰 없는 URL로 교체
    git -C "${var.app_dir}" remote set-url origin "https://github.com/${var.deploy_repo}.git"
    # [배포 계약] 제품 repo가 deploy/setup.sh를 제공하면 실행합니다.
    # 설치/기동/학습/업로드 방법은 각 제품 repo가 스스로 정의하며, 이 레포는 관여하지 않습니다.
    if [ -f "${var.app_dir}/deploy/setup.sh" ]; then
      bash "${var.app_dir}/deploy/setup.sh"
    else
      echo "no deploy/setup.sh in repo; clone-only deploy"
    fi
    echo "app-deploy: DONE"
  EOT
}
