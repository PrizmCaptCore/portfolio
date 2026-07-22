# 프로덕션 ECS + CloudFront 인프라 (AWS IaC)

> AI 회의 인텔리전스 제품 **Relay**(제품명 익명화)의 실제 프로덕션 인프라를 정의하는 Terraform.
> **단일 CloudFront 진입점** 뒤에 SPA(S3)와 API(ECS Fargate)를 함께 두고, dev/prod 를 같은
> 모듈로 찍어낸다. 설계의 실제 난제는 "ECS 를 띄우느냐"가 아니라 **"하나의 도메인 뒤에서
> SPA·API·정적파일·인증이 서로를 오염시키지 않게 경계를 어떻게 긋느냐"** 였다.

## 아키텍처

```
                        external DNS registrar (CNAME)
                                   │
                          CloudFront (+ WAFv2, us-east-1)
                          ├── default            → S3 (SPA / Vite dist, OAC)
                          └── /api|/admin|/static|/media|/accounts|/health-check
                                   │  (X-Origin-Verify 헤더 주입)
                                   ▼
                          ALB (HTTPS, ACM) ── prod에서 통합 관리
                                   │
                          ECS Fargate (Spot 기본)
                          ├── web     (Django ASGI, :8000)
                          ├── worker  (Celery)
                          └── beat    (Celery 스케줄러)
                                   │
                    RDS PostgreSQL · ElastiCache Redis   (SG 참조)
                    Secrets Manager (env valueFrom) · CloudWatch Logs

  배포: GitHub Actions ──(OIDC, 키 없음)──▶ ECR push · ECS update · S3 sync · CF invalidate
```

## 왜 이렇게 설계했나 (Engineering decisions)

- **CloudFront Function 으로 SPA 라우팅 — distribution-wide 404 리라이트를 버림.** 초기엔
  `custom_error_response(404 → /index.html 200)` 로 SPA 딥링크를 처리했는데, 이게 ALB 오리진의
  **정상 404/403 까지 SPA HTML 로 덮어써서** API 클라이언트(Rust 요약 호출)가
  `200 OK + <!DOCTYPE html>` 를 받고 파싱에 실패했다. viewer-request 단계의 URI rewrite
  (`aws_cloudfront_function.spa_router`)로 교체 — 확장자 있는 요청은 S3 로 통과, 나머지만
  `/index.html` 로 재작성해서 `/api/*` 응답을 건드리지 않는다.
- **오리진 우회 차단 (X-Origin-Verify).** CloudFront 가 ALB 오리진 요청에 공유 시크릿 헤더를
  주입하고(prod 는 `random_password` → Secrets Manager), WAF 가 호스트 조건과 함께 이 헤더를
  검증한다. ALB DNS 를 직접 때리는 트래픽을 걸러 CDN 을 실질적 단일 진입점으로 강제.
- **키 없는 배포 (GitHub OIDC).** 장기 액세스키 대신 federated role. ECR push / ECS deploy /
  S3 collectstatic / CloudFront invalidate 를 **각각 최소권한 정책**으로 분리하고, `iam:PassRole`
  은 task 역할 두 개로만 한정.
- **비용은 Spot, 워크로드는 3분할.** capacity provider 를 `FARGATE_SPOT` 기본으로 두고
  web(사용자 대기) / worker / beat 를 별도 서비스로. web 만 `RUN_PREDEPLOY=true` 로 마이그레이션·
  collectstatic 을 담당하고 worker/beat 는 스킵 — 배포 시 중복 실행 방지.
- **환경은 모듈로 찍고, ALB 는 prod 에서 통합.** dev(`ecs/`)는 자체 CloudFront 를 갖되 API 는
  **prod 통합 ALB 의 dev 타겟그룹**에 연결(ALB 중복 비용 제거), prod(`ecs-prod/`)가 ALB·WAF 를
  소유한다. 두 환경이 `../ecs/modules/*` 를 공유.
- **엣지 케이스를 코드에 박제.** VPC 엔드포인트가 `ap-northeast-2d` 를 미지원해서 AZ 를 a/b/c 로
  필터링하는 로직, ALB 의 "AZ 당 서브넷 1개" 제약을 위한 중복 제거 — 실운영에서 밟은 것들.

## 파일 구조

```
12-aws-ecs-fargate-cdn/
├── ecs/                      # dev 스택 (자체 CloudFront + prod ALB 공유)
│   ├── main.tf               # IAM(OIDC/task), SG, Secrets, web/worker/beat 모듈 호출
│   ├── cdn.tf                # CloudFront + S3(OAC) + WAF + SPA router function
│   ├── backend.tf            # S3 state + DynamoDB lock
│   ├── variables.tf / outputs.tf
│   └── modules/
│       ├── alb/              # ALB + HTTPS(리다이렉트) + 타겟그룹 + 헬스체크
│       ├── ecs_cluster/      # Fargate + Fargate Spot capacity provider
│       └── ecs_service/      # 태스크 정의 + 서비스 (web/worker/beat 공용)
└── ecs-prod/                 # prod 스택 (ALB·WAF 소유, ../ecs/modules 재사용)
    ├── main.tf / cdn.tf / backend.tf / variables.tf / outputs.tf
```

## 기술 스택

**Technologies**: Terraform (모듈화, S3 backend + DynamoDB state lock), AWS ECS Fargate /
Fargate Spot, CloudFront + CloudFront Functions, AWS WAFv2, ACM, S3 (OAC), Secrets Manager,
IAM (GitHub OIDC / 최소권한), RDS PostgreSQL · ElastiCache Redis (참조), GitHub Actions

> 본 Terraform 은 포트폴리오용으로 **sanitize** 되었습니다: AWS 계정 ID · 보안그룹 ID · ARN ·
> 도메인 · 버킷명 · CLI 프로파일 등 식별값을 예시값으로 치환했습니다. `terraform apply` 를
> 그대로 실행하기 위한 것이 아니라 아키텍처와 설계 의사결정을 보여주기 위한 문서입니다.
