# 프로덕션 웹 플랫폼 & 백엔드 (Web Platform & Backend)

> AI 회의 인텔리전스 제품 **Relay**(제품명 익명화)의 웹 계층. 계정·워크스페이스·회의 히스토리·
> B2B 프로비저닝·어드민을 담당한다. 동시에 **server-rendered 템플릿 → API + SPA** 로
> 마이그레이션 중이었는데, 이런 전환은 뭔가가 막지 않으면 조용히 되돌아간다(backslide).

## 아키텍처

```
                    CloudFront (CDN)
                    ├── /            → React SPA (Vite 빌드 아티팩트)
                    └── /api/v1/*    → ┐
                                       ▼
                              AWS ECS  (Django + DRF)
                              ├── web     (ASGI, WebSocket)
                              ├── worker  (Celery)
                              └── beat    (Celery 스케줄러)
                                       │
                              PostgreSQL 17  ·  Redis
```

## 왜 이렇게 설계했나 (Engineering decisions)

- **아키텍처 테스트 = fitness function** — 자동화 테스트가 레거시 템플릿 표면(surface)을
  **동결(freeze)** 하고 HTML 을 렌더링하는 새 제품 페이지 추가를 금지한다. 마이그레이션 중에도
  "API-only 경계"가 침식되지 않도록 강제.
- **CDN/컴퓨트 분리를 로컬에서 리허설** — 로컬 Docker 스택이 SPA 를 Django 와 별도로 서빙해서
  CloudFront + ECS 프로덕션 분리를 흉내낸다. SPA 동작을 *배포되는 방식 그대로* 테스트.
- **프로덕션과 같은 async** — Celery worker + beat 를 로컬에서도 eager 모드가 아닌 실제
  프로세스로 띄워, 태스크 동작이 ECS 와 일치.
- **B2B 일괄 프로비저닝 커맨드** — CSV 로 계정을 **멱등(idempotent)** 생성, dry-run · 팀 바인딩 ·
  재설정 링크 export 지원, 중복/잘못된 이메일은 안전하게 스킵.

## 기술 스택

**Technologies**: Django, Django REST Framework, Celery (+ beat), PostgreSQL, Redis,
React / Vite, TailwindCSS, Docker Compose, AWS ECS, CloudFront, Nginx (reverse proxy / WebSocket upgrade)

> 애플리케이션 소스는 비공개입니다. 본 문서는 아키텍처와 설계 의사결정을 정리한 것입니다.
