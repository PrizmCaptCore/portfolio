# NHN cloud terraform

NHN 클라우드 gitops 배포용 코드 입니다.<br>
1차 업데이트는 skeleton 업데이트로, 실무에 적용하기 위한 OIDC 등등 셋업이 필요 합니다.<br>
nhn terraform은 배포할 ID,PW를 github secret으로 올리는 것을 기본으로 하기 때문에,<br>
실무 배포시 github action의 secret 입력 역시 필요합니다.

# GitHub Actions 배포 사용법

워크플로우: `.github/workflows/nhn-cloud-deploy.yml` (수동 실행, workflow_dispatch)

## 1. 사전 등록할 GitHub Secrets

등록 위치: repo Settings → **Environments → `NHN_CLOUD_SECRETS_ENV`** 의 Environment secrets.
워크플로우 job에 `environment: NHN_CLOUD_SECRETS_ENV`가 선언되어 있어야 이 secrets가 주입됩니다
(현재 워크플로우에 선언됨. environment 이름을 바꾸면 워크플로우도 같이 수정할 것).

| Secret 이름 | 내용 |
|---|---|
| `NHN_CLOUD_API_USER_ID` | 콘솔 **로그인 계정 ID** — 일반 회원은 이메일, IAM 멤버는 IAM 계정 ID (`OS_USERNAME`). 콘솔에 보이는 UUID가 아님! |
| `NHN_CLOUD_API_PASSWORD` | API 엔드포인트 설정에서 저장한 API 비밀번호. 로그인 비밀번호와 별개 (`OS_PASSWORD`) |
| `NHN_CLOUD_TENANT_ID` | NHN Cloud 프로젝트(테넌트) ID (`OS_TENANT_ID`) |
| `PRIVATE_REPO_TOKEN` | 배포 대상 private repo의 **read 전용** fine-grained PAT |
| `NHN_S3_ACCESS_KEY` | Object Storage S3 API 자격 증명 (콘솔에서 발급한 것만 유효) — 원격 tfstate용 |
| `NHN_S3_SECRET_KEY` | 위 액세스 키의 시크릿 키 |

`OS_AUTH_URL`, `OS_REGION_NAME`은 비밀값이 아니므로 워크플로우에 하드코딩되어 있습니다.

## 2. 배포 트리거 (기본: 제품 repo의 release 태그)

GitHub는 타 레포의 release 이벤트를 직접 구독할 수 없으므로,
**제품 repo → 배포 repo** 방향으로 dispatch 이벤트를 쏘는 구조입니다.

```
제품 repo: main 머지 → release TAG 발행
  └─ (제품 repo의 발신 워크플로우) repository_dispatch 전송
       └─ 이 레포의 NHN Cloud Deploy 실행 → terraform apply (자동 실배포)
```

세팅 방법:

1. `examples/product-repo-release-trigger.yml`을 배포할 제품 repo의
   `.github/workflows/`에 복사합니다.
2. 파일 안의 `DEPLOY_REPO`를 이 배포 레포의 실제 `owner/repo`로 수정합니다.
3. 제품 repo에 Secret `DEPLOY_TRIGGER_TOKEN`을 등록합니다.
   (이 배포 레포 대상, **Contents: Read and write** 권한의 fine-grained PAT —
   repository_dispatch 전송에 필요한 최소 권한입니다)
4. 제품 repo에서 main 기준으로 release를 발행하면 자동으로 배포됩니다.
   release의 태그가 그대로 배포 대상 ref가 됩니다.

release 태그로 들어온 배포는 plan을 거쳐 **자동으로 apply까지** 수행합니다.

## 3. 수동 실행 (디버깅/최초 검증용)

Actions 탭 → `NHN Cloud Deploy` → `Run workflow`에서 입력:

- `target_repo` : 배포할 내부 private repo (`owner/repo` 형식)
- `target_ref` : 배포할 브랜치/태그 (기본 `main`)
- `tf_action` : `plan`(검증만) 또는 `apply`(실제 배포)

## 4. 동작 방식

1. 러너가 배포 대상 repo를 checkout하여 repo 이름/토큰을 검증합니다 (빌드 스텝 추가 자리).
2. terraform이 인스턴스를 생성하며, `user_data`(cloud-init)로 부팅 시 인스턴스가
   입력받은 private repo를 `/opt/app`에 clone합니다.
3. [배포 계약] clone 직후 제품 repo의 `deploy/setup.sh`가 존재하면 실행합니다.
   설치/기동/학습/업로드 방법은 각 제품 repo가 이 스크립트에서 스스로 정의합니다
   (제품 repo 쪽 발신 워크플로우 예시는 `examples/` 참고).
   실행 로그는 인스턴스의 `/var/log/app-deploy.log`에 남습니다.
4. 동시 배포 방지를 위해 워크플로우에 `concurrency` 그룹이 걸려 있어,
   배포는 한 번에 하나씩만 실행됩니다.

## 5. 실무 적용 전 필수 체크

- **원격 tfstate**: (적용 완료) state는 NHN Object Storage 버킷에 저장됩니다. 버킷 이름은 코드에 두지 않고 GitHub Variable `TFSTATE_BUCKET`(CI) 또는 `backend.hcl`(로컬, `backend.hcl.example` 참고)로 주입합니다.
  덕분에 release를 반복해도 인스턴스가 중복 생성되지 않고(기존 리소스와 diff), destroy도 가능합니다.
  로컬에서 terraform을 돌리려면 S3 자격 증명을 환경변수로 주입하세요:
  `AWS_ACCESS_KEY_ID=<S3 액세스 키> AWS_SECRET_ACCESS_KEY=<S3 시크릿 키> terraform init -backend-config=backend.hcl && terraform plan` (전체 변수는 `src/env.example` 참고)
  단, S3 호환 backend라 잠금(lock)이 없으므로 CI 실행 중에 로컬 apply를 하지 마세요
  (CI 쪽 동시 실행은 워크플로우 concurrency 그룹이 막아줍니다).
- **토큰 노출 범위**: `deploy_token`은 user_data와 tfstate에 남습니다. 반드시 대상 repo
  read 권한만 가진 fine-grained PAT를 쓰고, 주기적으로 갱신하세요.
- **SSH 접속**: 필요 시 NHN 콘솔에 keypair를 등록하고 `TF_VAR_keypair_name`으로 이름을
  넘기면 됩니다 (기본값은 keypair 없음).

# 문법 확인

https://docs.nhncloud.com/ko/nhncloud/ko/terraform-guide/ <br>
테라폼 문법은 크게 다르지 않으나, nhn provider에 맞는 문법은 위 가이드에서 확인해주세요.<br>
```
OS_USERNAME: ${{ secrets.NHN_CLOUD_API_USER_ID }} 
```
식으로, __secret__ 키를 입력해주셔야 합니다. <br>
핵심은, **OS_\*** 로 매치하는 것으로, __NHN Cloud__ 는 AWS와 달리 OIDC가 없어 이와 같은 방법으로 인증키, 시크릿키를 입력해야 합니다.<br><br>
즉, __github action__ 의 __OS\_*__ 이 __github action__ 쪽에 써져야할 문법<br>
```${{ secret.NHN_CLOUD_API_USER_ID}} ```<br>
에서 __NHN_CLOUD_API_USER_ID__ 가 __github action secret__ 에 쓰여야할 문법 이런식으로 이해해주시면 됩니다.<br>
# gitignore 체크시 알아둬야할 점<br>
보통의 코드 실행 산출물은 모두 제거하는게 올바르지만,<br>
terraform의 lock.hcl 파일은 형상 관리를 위해 반드시 필요한 파일 입니다.<br>
이에 따라, gitignore에서는 반드시 이 파일들은 유지한 상태로 체크해야 합니다.<br>