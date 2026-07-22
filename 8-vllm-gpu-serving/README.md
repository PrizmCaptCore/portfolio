# 비용 튜닝 vLLM GPU 서빙 (Cost-tuned GPU Inference Fleet)

> AI 회의 인텔리전스 제품 **Relay**(제품명 익명화)의 추론 백엔드. 세 가지 서비스
> — 요약/인텐트, 임베딩, 번역 — 를 **vLLM** 으로 서빙한다. 설계의 핵심 질문은 "돌아가느냐"가
> 아니라 **"idle 일 때 얼마가 나가느냐"** 였다. 워크로드마다 duty cycle 이 극단적으로 달라서,
> 그 차이를 토폴로지에 직접 새겼다.

## 서비스별 토폴로지

| 서비스 | 특성 | Min workers | 이유 |
|--------|------|-------------|------|
| **요약 / 인텐트** | 회의 중 실시간, 사용자가 대기 | **1 (always-on)** | cold start 가 UX 직격탄 |
| **임베딩** | sparse batch 동기화, idle ~99% | **0 (scale-to-zero)** | idle 시 GPU 비용 0 |
| **번역** | 사용 빈도 의존 | **0–1** | duty cycle 로 결정 |

**비용 핵심**: 사용자가 *실시간으로 기다리는* 단 하나의 서비스에만 always-on GPU 를 붙이고,
나머지는 idle 시 GPU 를 반납한다.

## 왜 이렇게 설계했나 (Engineering decisions)

- **지연을 체감하는 곳에만 과금** — 실시간 대기가 있는 서비스만 always-on, 나머지는
  scale-to-zero. "always-on GPU 를 idle 99% 워크로드에 붙이지 않는다"는 원칙.
- **Zero-rebuild 배포** — STT 베이스 이미지가 ~80GB 라 변경마다 재빌드는 불가능. 컨테이너가
  시작 시 최신 핸들러 코드를 pull 해 in-place hot-reload 하고, pull 실패 시 이미지에 baked 된
  코드로 fallback 해서 서비스가 멈추지 않는다. 코드만 바뀐 경우 rebuild 0.
- **가중치를 이미지에 baking** — 임베딩/추론 이미지에 weights 를 구워, scale-to-zero cold
  start 를 분(minute) 이 아니라 수십 초 단위로 유지.
- **계층 인증** — 플랫폼 API Key 를 1차 게이트, 회전(rotating) 내부 키를 2차 방어선으로.
  무중단 키 회전을 위한 grace window 포함.
- **Matryoshka 임베딩 절단** — 같은 벡터를 클라이언트에서 앞 N차원만 잘라 정규화. 품질
  예산이 허용하면 온디바이스 인덱스 크기를 최대 4배(1024→256d) 축소.

## CI / 빌드

- 서비스 경로별 **path-filtered** GitHub Actions — 바뀐 서비스만 재빌드.
- vLLM 베이스 + baked weights 이미지가 커서 **순차 빌드**로 러너 디스크 한계 관리.
- 모델 다운로드 토큰은 **BuildKit secret** 으로 주입 — 이미지 레이어에 남지 않음.

## 기술 스택

**Technologies**: vLLM, Serverless GPU, Docker / BuildKit, GitHub Actions, CUDA,
Gemma / Qwen3-Embedding / Translate 계열 모델, OpenAI-compatible API

> 서빙 핸들러 소스는 비공개입니다. 본 문서는 아키텍처와 비용 설계 의사결정을 정리한 것입니다.
