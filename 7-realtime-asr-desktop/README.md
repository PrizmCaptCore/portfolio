# 실시간 회의 어시스턴트 데스크톱 클라이언트 (Tauri 2 + Rust + Next.js)

> AI 회의 인텔리전스 제품 **Relay**(제품명·조직명 가명화)의 데스크톱 앱 전체 소스. Rust 코어가 오디오 경로 전부를
> 소유하고, Next.js 웹뷰는 순수 뷰 계층이다. 마이크와 시스템 오디오를 **독립 스트림**으로 잡아 "나 / 상대" 를 나누고,
> DSP → VAD → 게이트웨이 STT(WebSocket f32 PCM) → partial/final 정합 → 번역·요약·로컬 RAG 까지 한 바이너리에서 돈다.
> 오픈소스 meetily(MIT)를 포크해 시작했고, 오디오 파이프라인·전사 워커·게이트웨이 인증·RAG·릴리스 체계를 새로 썼다.

## 구성

```text
frontend/
├── src-tauri/                       # Rust 코어 (Tauri 2.10)
│   ├── src/audio/
│   │   ├── capture/                 # cpal 마이크 + 시스템 루프백 (macOS: CoreAudio process tap via cidre)
│   │   ├── pipeline.rs              # 다운믹스 → HPF → RNNoise → EBU R128 정규화 → rubato 16kHz 리샘플 → 링버퍼 정렬 → RMS 게이트
│   │   ├── vad.rs                   # Silero VAD: 0.50/0.35 임계, 2s redemption, 300/400ms 패딩, 250ms 최소
│   │   ├── transcription/engine.rs  # 게이트웨이 warm-up(/health, /ready 폴링) → /ai/stt/session → wss + ?key=
│   │   ├── transcription/nemo_provider.rs   # f32 LE PCM 바이너리 업, {"text","is_partial"} 다운, {"cmd":"reset"}
│   │   ├── transcription/worker.rs  # 워커 풀, 길이 sanity 휴리스틱, LCP "stable prefix" partial/final 정합
│   │   ├── translation.rs, meeting_detector.rs, recording_commands.rs
│   ├── src/api/                     # 게이트웨이 클라이언트, JWT 는 매 폴링마다 auth.json 재독 (캐시 안 함)
│   ├── src/summary/                 # 요약 LLM 클라이언트: 게이트웨이 또는 OpenAI/Anthropic/Groq/OpenRouter 직접
│   ├── src/rag/, src/database/      # sqlx SQLite (11 migrations) + sqlite-vec 로컬 KNN
│   ├── migrations/, templates/      # 요약 프롬프트 템플릿(JSON)
│   └── tauri.conf.json              # CSP, opener 허용 도메인, updater(minisign) — 식별자는 placeholder
├── src/app, components, hooks, services, contexts   # Next.js 14 App Router, Radix/shadcn, BlockNote, xyflow
├── scripts/                         # 임베딩 모델(onnxruntime-web WASM) 다운로드·복사
Makefile                             # install / dev / dev-cloud / build / lint / check
```

## 왜 이렇게 설계했나

- **채널 기반 화자 라벨.** 마이크와 시스템 오디오를 별도 `cpal` 스트림으로 열고 청크마다 `DeviceType` 을 태깅한다.
  화자 분리(diarization) 모델 없이도 "Me / Speaker" 가 정확하다. macOS 는 화면 녹화 권한을 요구하는 CoreAudio 탭을 쓴다.
- **인식기 앞에서 버린다.** RNNoise 와 라우드니스 정규화 뒤에 RMS 게이트(`SILENCE_ENERGY_THRESHOLD = 0.0001`)를 두어
  무음을 STT 에 보내지 않는다. 무음이 들어가면 모델이 같은 문장을 환각으로 반복했다. Silero VAD 가 고정 프레임이 아니라 **발화 단위**로 자른다.
- **STT 엔드포인트는 클라이언트에 없다.** 게이트웨이에 JWT 로 `/ai/stt/session/` 을 요청해 단기 서명 세션을 받고,
  응답의 `https://` 를 `wss://` 로 바꿔 `?key=` 를 붙인다. GPU 워커 주소가 바뀌어도 클라이언트 릴리스가 필요 없다.
  게이트웨이는 먼저 `/health/` → `/ready/` 폴링으로 GPU 컨테이너가 뜰 때까지 기다린다.
- **partial 은 깜빡이지 않는다.** `worker.rs` 가 `sequence_id` 별 최근 N 개 토크나이즈의 **최장 공통 접두(LCP)** 만 커밋하고
  `committed_count` 를 단조 증가시킨다. 커밋된 머리는 고정, 꼬리만 흐리게 다시 그린다.
- **로컬 모델 fallback 을 의도적으로 막았다.** `transcription/engine.rs` 는 게이트웨이 STT 만 지원한다. 릴리스 빌드가 더 이상 싣지 않는
  로컬 모델로 조용히 떨어지면 사용자가 다른 품질을 보게 되기 때문이다. 온디바이스 CNN STT 는 별도 실험 브랜치로 남겼다.
- **RAG 는 전부 로컬.** 회의 요약과 Notion 청크의 임베딩을 `sqlite-vec` 가상 테이블에 넣고 KNN 한다. 임베딩 모델은
  웹뷰의 onnxruntime-web(WASM)에서 돌아 서버로 텍스트를 보내지 않는다.
- **번역·요약은 같은 인증 게이트웨이로.** 설정에서 OpenAI/Anthropic/Groq/OpenRouter 직접 호출도 고를 수 있다.
- **릴리스.** Tauri updater(minisign 서명). macOS 는 GitHub Actions 매트릭스 빌드, Windows 는 EV USB 토큰 때문에 로컬 서명.
  서명·업로드 스크립트와 키 정책은 조직 식별자를 포함해 제외했다.

## 이벤트 / 커맨드 경계

Rust → UI 는 Tauri 이벤트만: `transcript-update`, `translation-update`, `audio-levels`, `speech-detected`,
`transcription-progress`, `recording-saved`. UI → Rust 는 `#[tauri::command]` 핸들러(`api::commands`, `audio::recording_commands`,
`summary::commands`, `rag::commands`, `database::commands`).

## 빌드

```bash
make install            # pnpm + cargo
make dev                # Next dev(:3118) + tauri dev
make build              # 정적 export 후 tauri build
```

포함하지 않은 것: ffmpeg 사이드카 바이너리(150MB), 제품 아이콘·로고, 코드 서명/릴리스 스크립트, updater 공개키, `.env`.
게이트웨이 도메인·번들 식별자·조직명은 placeholder 로 치환했다.

**Technologies**: Rust, Tauri 2, cpal, Silero VAD, RNNoise (nnnoiseless), ebur128, rubato, tokio-tungstenite, sqlx + sqlite-vec,
Next.js 14, React 18, TypeScript, Tailwind, Radix, BlockNote, @huggingface/transformers (onnxruntime-web), PostHog
