# 멀티 타깃 배포 파이프라인 (NHN Cloud Terraform + 온프레미스 Nuitka 패키징)

> 농산물 선별기 제품군의 SW 배포를 한 레포에서 다루기 위해 설계한 배포 인프라.
> 같은 제품 코드가 **클라우드 인스턴스**(학습/업로드 워크로드)와 **현장 엣지 디바이스**(리눅스 .deb, 윈도우 .exe)
> 양쪽으로 나가야 했고, 제품 레포마다 설치 방법이 달랐다. 그래서 배포 레포는 "어떻게 설치하느냐"를 알지
> 않고, **제품 레포가 `deploy/setup.sh` 로 스스로 정의하는 계약**만 강제한다.

## 구성

```text
.
├── .github/workflows/nhn-cloud-deploy.yml      # 배포 워크플로우 (dispatch / 수동)
├── cloud_deploy/
│   ├── nhn_terraform/
│   │   ├── src/{provider,variables,instance}.tf # NHN Cloud(OpenStack 계열) 인스턴스 + cloud-init
│   │   ├── src/backend.hcl.example             # 원격 tfstate 버킷 (partial backend config)
│   │   ├── src/env.example                     # 로컬 실행용 환경변수 템플릿
│   │   └── examples/product-repo-release-trigger.yml  # 제품 레포에 두는 발신 워크플로우
│   └── aws_terraform/                          # AWS 쪽 skeleton (OIDC 전제, 미구현)
└── onpremise_deploy/
    ├── linux/src/{Dockerfile,build.sh}         # python -> Nuitka onefile -> .deb (BuildKit output)
    └── windows/src/{Dockerfile.windows,build.ps1}  # Windows 컨테이너 + MinGW-w64 Nuitka -> .exe
```

## 클라우드 배포 흐름

```
제품 repo: main 머지 -> release 태그 발행
  └─ (examples/product-repo-release-trigger.yml) repository_dispatch { repo, tag }
       └─ 이 레포의 NHN Cloud Deploy
            ├─ 대상 repo checkout (토큰/이름 조기 검증, 빌드 스텝 자리)
            ├─ terraform init -backend-config="bucket=${{ vars.TFSTATE_BUCKET }}"
            ├─ terraform plan -> (dispatch 는 자동) apply
            └─ 인스턴스 cloud-init:
                 git clone --depth 1 --branch <tag> https://x-access-token:<PAT>@github.com/<repo> /opt/app
                 remote 를 토큰 없는 URL 로 교체
                 [ -f /opt/app/deploy/setup.sh ] && bash /opt/app/deploy/setup.sh
```

### 설계 결정

- **GitHub 는 타 레포의 release 이벤트를 구독할 수 없다.** 그래서 제품 레포 -> 배포 레포 방향으로
  `repository_dispatch` 를 쏘는 구조. 제품 레포에는 배포 레포 대상 Contents R/W 권한만 가진 fine-grained PAT 하나만 둔다.
- **release 태그는 자동 apply, 수동 실행은 plan 기본.** 디버깅/최초 검증 경로와 실배포 경로를 같은 워크플로우에서 분리한다.
- **원격 tfstate 는 필수.** CI 러너는 매번 초기화되므로 로컬 state 로는 release 마다 인스턴스가 중복 생성된다.
  NHN Object Storage 의 S3 호환 API 를 backend 로 쓰되, 잠금(lock)이 없으므로 워크플로우 `concurrency` 그룹이 동시 apply 를 막는다.
- **버킷 이름·계정 식별자는 코드에 없다.** 버킷은 partial backend config(`vars.TFSTATE_BUCKET` / `backend.hcl`),
  인증은 OpenStack 호환 `OS_*` 환경변수와 S3 자격 증명 secrets, 인스턴스 형상은 `TF_VAR_*` 로 주입한다.
- **NHN 이미지는 이름이 바뀐다.** 이미지 이름 고정 대신 `name_regex` + `most_recent` 로 순정 Ubuntu 22.04 만 매치.
  서브넷은 `.id` 가 아니라 `vpc_id` 를 넣어야 하는 provider 특성이 있어 주석으로 고정했다.
- **토큰 노출 범위를 인정하고 좁힌다.** `deploy_token` 은 user_data 와 tfstate 에 남는다. 그래서 read-only PAT 만 허용하고,
  clone 직후 remote URL 에서 토큰을 제거하며, 로그는 `/dev/console` 로도 보내 SSH 없이 콘솔 출력 API 만으로 디버깅한다.
- **apt 락 대기.** 부팅 직후 unattended-upgrades 가 락을 잡고 있어 `DPkg::Lock::Timeout=300` 없이는 cloud-init 이 간헐적으로 실패한다.

## 온프레미스 패키징

리눅스: `python:3.14-slim` 에서 uv 로 의존성 설치 -> Nuitka `--standalone --onefile` -> `dpkg-deb` 로 `.deb` 조립 ->
`FROM scratch AS artifact` 스테이지에서 BuildKit `--output type=local` 로 산출물만 꺼낸다. 패키지 메타데이터(이름/버전/아키텍처/메인테이너)는
`env/.env` 를 `build.sh` 가 `--build-arg` 로 넘긴다.

윈도우: `python:3.14-windowsservercore-ltsc2022` Windows 컨테이너에서 `--mingw64` 로 MSVC 없이 빌드.
Windows 엔진은 BuildKit `--output` 을 지원하지 않으므로 `docker create` + `docker cp` 로 exe 를 꺼낸다. 호스트가 Windows Pro 이상이어야 한다.

## 사용

```bash
# 클라우드 (로컬 검증)
cd cloud_deploy/nhn_terraform/src
cp backend.hcl.example backend.hcl && cp env.example env/.env   # 값 채우기
set -a; source env/.env; set +a
terraform init -backend-config=backend.hcl && terraform plan

# 온프레미스 리눅스
cd onpremise_deploy/linux/src && cp env/.env.example env/.env && ./build.sh    # -> ./out/<PKG>_<VER>_<ARCH>.deb

# 온프레미스 윈도우 (PowerShell, Windows 컨테이너 모드)
cd onpremise_deploy\windows\src; Copy-Item env\.env.example env\.env; .\build.ps1   # -> .\out\<BIN>.exe
```

## 보안 검증 순서 (실상품 적용 전)

```
build -> SBOM scan (with VEX) -> SAST -> DAST -> deploy
```

최초 개발 단계에서는 제외했으나, ISO 27001 요구를 맞추려면 위 검증이 워크플로우의 checkout 과 apply 사이에 들어가야 한다.
리눅스 온프레미스는 솔루션 영역이라 code-sign 이 빠지고, 윈도우는 배포 루틴상 code-sign 스텝이 추가될 수 있다.
