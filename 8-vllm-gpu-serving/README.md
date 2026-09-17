# 비용 튜닝 GPU 서빙 플릿 (RunPod Serverless / Pod + vLLM / NeMo)

> AI 회의 인텔리전스 제품 **Relay**(제품명 가명화)의 추론 백엔드 전체 소스. 다섯 워커
> — 실시간 STT(CNN STT/NeMo), STT PoC(RealtimeSTT/vLLM Realtime), 요약·인텐트(Gemma 4), 임베딩(Qwen3), 번역(TranslateGemma) —
> 를 서빙한다. 설계의 핵심 질문은 "돌아가느냐"가 아니라 **"idle 일 때 얼마가 나가느냐"** 였고,
> 워크로드마다 duty cycle 이 극단적으로 달라 그 차이를 토폴로지에 직접 새겼다.

## 구성

```text
.
├── .github/workflows/build-push.yml   # path-filtered 매트릭스 빌드, 순차 빌드, HF 토큰은 BuildKit secret
├── runpod_inference/                  # Gemma 4 E2B-it · vLLM · Serverless always-on (handler.py) / Pod (server.py)
├── runpod_embedding/                  # Qwen3-Embedding-0.6B · vLLM · Serverless scale-to-zero
├── runpod_translate/                  # TranslateGemma-4B-it · vLLM · 출력 규율(중국어 누출·메타 코멘트 정리)
├── runpod_stt/                        # CNN STT 0.6B · NeMo · Pod · WS 스트리밍 + 마이크로배처
├── runpod_realtime_stt/                # Realtime STT 모델 · vLLM Realtime API 어댑터 · Network Volume 캐시
├── poc_gemma4_e2b/                    # 로컬 PoC: 토큰 단위 partial 스트리밍 (transformers, Intel Arc)
└── tools/reload-pods.ps1              # Pod 의 /admin/reload 호출 (zero-rebuild 재배포)
```

## 왜 이렇게 설계했나

- **지연을 체감하는 곳에만 과금.** 사용자가 실시간으로 기다리는 요약/인텐트만 Min Workers 1, 임베딩은 0.
  "always-on GPU 를 idle 99% 워크로드에 붙이지 않는다."
- **Zero-rebuild 배포.** NeMo STT 베이스 이미지가 ~80GB 라 GitHub 러너로 빌드가 안 된다. `entrypoint.sh` 가 컨테이너
  시작 시 `server.py` 만 git pull 해 덮어쓰고, `/admin/reload` 는 FastAPI 층만 SIGTERM 한다. vLLM 은 **서브프로세스**로
  띄워 두었기 때문에 재기동 시 `/v1/models` 로 살아 있음을 확인하고 모델 재로드(~60s)를 건너뛴다. pull 실패 시 baked 코드로 fallback.
- **가중치는 이미지에 굽되, 예외를 둔다.** 임베딩/추론/번역은 `snapshot_download` 로 빌드 시점에 굽고
  `HF_HUB_OFFLINE=1` 을 그 *뒤에* 켜서 gated repo 의 ETag HEAD 401 을 피한다 → scale-to-zero cold start 30s~1분.
  RealtimeSTT 은 굽으면 64GB 라 Network Volume(`/runpod-volume/hf-cache`)로 분리해 이미지 <10GB, 첫 Pod 만 다운로드 비용.
- **STT 마이크로배처.** 동시 세션이 NeMo encoder freeze/unfreeze 를 경쟁시키고, 단순 lock 은 처리량을 무너뜨린다.
  단일 워커 스레드가 `MAX_BATCH=16 / MAX_WAIT_MS=30` 으로 묶어 처리하고, final 은 무조건 큐잉·partial 은 backlog 16 초과 시 드랍.
  30s idle 후 CUDA 캐시 반환. 동시 150 세션 스트레스 검증(`runpod_stt/stress_test.py`).
- **계층 인증.** RunPod API Key 를 1차, 회전 가능한 내부 키(`RELAY_INTERNAL_KEY` + `_PREV` grace window)를 2차 방어선으로.
  STT WS 는 정적 키 또는 `uid:expiry:hmac` 토큰.
- **RealtimeSTT 양자화 선택.** Ampere(A5000)는 FP8 텐서코어가 없어 vLLM 의 FP8-Marlin 은 weight-only 다. INT4 W4A16-Marlin(bitsandbytes NF4)이
  실제로 GEMM 을 줄이므로 그쪽을 택했고, `max-model-len` 은 45000 → 8000(~10분 오디오)로 내려 L4 24GB 에서 KV 캐시 10GB 를 피했다.
  WebSocket 계약은 CNN STT 워커와 바이트 단위로 동일해 클라이언트 변경 0.
- **Matryoshka 임베딩 절단.** 1024-d 를 클라이언트에서 256-d 로 잘라 정규화하면 온디바이스 SQLite 인덱스가 1/4.

**Technologies**: vLLM, NVIDIA NeMo, RunPod Serverless / Pod, Docker BuildKit, GitHub Actions, CUDA, WebSocket, FastAPI, bitsandbytes

---

## 운영 가이드 (원본 README, 식별자 치환)

Modal → RunPod 마이그레이션. 서비스별 전략:

| 서비스 | 백엔드 | RunPod 방식 | Min Workers | 이유 |
|--------|------|------------|-------------|------|
| STT (CNN base) | NeMo | **Pod** | n/a | NeMo 베이스 ~80GB라 GitHub Actions 러너로 빌드 불가. Modal 유지 또는 로컬/RunPod native build |
| STT PoC (TF base) | **vLLM Realtime** | **Pod** | n/a | 한국어 라이브 전사 + loanword 보존 검증용. Slim CUDA 베이스 + Network Volume 캐시로 이미지 <10GB |
| Inference (Gemma 4 E2B-it) | **vLLM** | **Serverless** | **1 (always-on)** | 회의 진행 중 실시간 summary/intent 라 cold start 받으면 UX 망가짐 |
| Embedding (Qwen3-Embedding-0.6B) | **vLLM** (embed 아키텍처 자동 감지) | **Serverless** | **0 (scale-to-zero)** | Notion 동기화 같은 sparse batch 워크로드. idle 시 GPU 비용 0 |
| Translate (TranslateGemma 4B-it) | **vLLM** | **Serverless** | 0 또는 1 | 사용 빈도에 따라 결정 |

**BizOps**: Inference 만 항상 켜두고, Embedding 은 호출될 때만 GPU 점유 → idle 시간이 99% 인 워크로드에 always-on GPU 안 붙임.

GHA로 자동 빌드되는 이미지 (private, **GHCR**):

- `ghcr.io/your-org/relay-inference:latest`
- `ghcr.io/your-org/relay-embedding:latest`
- `ghcr.io/your-org/relay-translate:latest`

## 0. 이미지 빌드 (Inference / Embedding / Translate)

### 사전 준비: HF_TOKEN repo secret (최초 1회)

vLLM 베이스 이미지에 모델 weights를 빌드 시점에 굽기 때문에 HuggingFace 토큰이 필요합니다 (Gemma 계열은 gated, Qwen3-Embedding은 public이지만 일관성 위해 동일 경로 사용).

1. HF 계정에서 `google/gemma-4-E2B-it`, `google/translategemma-4b-it` 페이지 방문 → 라이선스 accept
2. https://huggingface.co/settings/tokens → **Read** 권한 토큰 발급
3. GitHub repo → **Settings** → **Secrets and variables** → **Actions** → `HF_TOKEN` 이름으로 등록

### GitHub Actions (권장)

- `runpod_inference/**`, `runpod_embedding/**`, `runpod_translate/**` 경로에 push 하면 해당 서비스만 자동 재빌드.
- Actions 탭 → **Build & Push** → **Run workflow** 로 수동 트리거 가능. `services` 입력으로 부분 재빌드.
- 세 서비스는 **순차 빌드** (max-parallel: 1). vLLM 베이스 + baked-in weights 이미지가 커서 러너 디스크 여유 확보를 위함.
- BuildKit cache export 는 비활성화 — vLLM 베이스 + weights 합산 시 디스크 한계 초과. 매 빌드 처음부터 빌드 (시간 +5~10분).
- Auth: GHCR push 는 `GITHUB_TOKEN` 자동 주입, HF weights 다운로드는 위 `HF_TOKEN` secret을 BuildKit secret으로 주입 (이미지 레이어에 토큰이 남지 않음).

### 로컬 빌드 (optional, x86_64 Linux에서)

```bash
echo "<github-pat>" | docker login ghcr.io -u <gh-username> --password-stdin

cd runpod_<service>
HF_TOKEN=<hf-token> docker buildx build --platform linux/amd64 \
  --secret id=hf_token,env=HF_TOKEN \
  -t ghcr.io/your-org/relay-<service>:latest \
  --push .
```

> Mac 에서 `buildx --platform linux/amd64` 빌드는 QEMU 에뮬레이션이라 매우 느립니다.

### STT 는 별도 처리

NeMo 베이스 이미지가 커서 GitHub-hosted 러너(최대 ~64GB)로는 빌드 불가. 선택지:

- **(a) Modal 유지** — STT는 기존 Modal 배포 그대로 두고, Inference/Embedding/Translate 만 RunPod 로 이전. 현재 권장 방향.
- **(b) RunPod Native Build** — RunPod Console → Templates → *Import from GitHub* 로 `runpod_stt/Dockerfile` 을 RunPod infra에서 빌드. GHCR push 불필요, 결과 이미지는 RunPod registry 에 저장됨.
- **(c) 로컬 빌드** — 디스크 200GB+ 머신에서 일회성으로 빌드 후 GHCR 에 push.
  ```bash
  cd runpod_stt
  docker buildx build --platform linux/amd64 \
    -t ghcr.io/your-org/relay-stt:latest \
    --push .
  ```

## 0-1. RunPod → GHCR pull 권한 설정 (최초 1회)

GHCR private 이미지를 RunPod 가 pull 하려면 PAT 필요:

1. https://github.com/settings/tokens/new (classic)
   - Scope: **`read:packages`** 만
   - Expire: 필요에 맞게
2. RunPod Console → **Settings** → **Container Registry Auth** → **Add Credentials**
   - Name: `ghcr-cred`
   - Registry: `ghcr.io`
   - Username: GitHub 사용자명
   - Password: 위 PAT
3. GHCR 패키지 페이지 (https://github.com/orgs/your-org/packages) 에서 각 패키지 → **Package settings** → **Manage Actions access** 에 `runpod_deploy` 연결 확인 (Actions 에서 첫 push 시 자동 연결되지만 간혹 수동 연결 필요).

Pod / Serverless Endpoint 생성 시 *Container Registry Credentials* 드롭다운에서 `ghcr-cred` 선택.

---

## 1. STT — RunPod Pod

> 현재 기본 방침은 **Modal 유지**. 아래는 RunPod 로 이전할 경우 참고용.

### Pod 생성

1. RunPod Console → **Deploy** → **GPU Pod**
2. Container Image: `ghcr.io/your-org/relay-stt:latest`
3. Container Registry Credentials: `ghcr-cred`
4. GPU: **L4** (또는 A4000)
5. Expose ports: `8765`
6. Environment Variables:
   ```
   RELAY_INTERNAL_KEY=<your-key>
   RELAY_INTERNAL_KEY_PREV=<prev-key>     # optional, rolling key grace
   GIT_PAT=<github-pat-with-repo-read>    # enables zero-rebuild code reload
   GIT_REF=main                            # optional, defaults to main
   ```
7. Deploy

### 환경변수 업데이트

```
RELAY_NEMO_STT_URL=wss://<pod-id>-8765.proxy.runpod.net/
```

> RunPod Pod proxy URL 형식: `<pod-id>-<port>.proxy.runpod.net`
> Pod 상세 페이지 → **Connect** → **HTTP Service** 에서 확인

### Zero-rebuild 코드 배포

NeMo 베이스가 ~80GB라 매번 빌드하면 시간이 너무 든다. `entrypoint.sh` 가
컨테이너 시작 시 `GIT_PAT` 으로 GitHub에서 `runpod_stt/server.py` 만
pull 해서 덮어쓴 다음 실행하므로, **코드만 바뀐 경우 이미지 rebuild 불필요**.

흐름:
1. `runpod_stt/server.py` 수정 후 `git push origin main`
2. 둘 중 하나:
   - **Pod 재시작** (RunPod Console → Restart) — `entrypoint.sh` 가 최신 코드 pull 후 기동
   - **In-place reload**: 모델 재로드 ~30s 후 새 코드로 다시 뜸
     ```bash
     curl -X POST -H "X-Internal-Key: <RELAY_INTERNAL_KEY>" \
       https://<pod-id>-8765.proxy.runpod.net/admin/reload
     ```
     `os.kill(SIGTERM)` 으로 uvicorn graceful shutdown → entrypoint 루프가 다시 pull → 재기동.

`GIT_PAT` 가 비어있거나 pull 실패 시 image 에 baked 된 `/app/server.py` 로 fallback — Pod 가 멈추지 않음.

Image 자체를 다시 빌드해야 하는 경우는 의존성 변경 (`Dockerfile` / NeMo / CNN STT 모델) 때뿐.

---

## 1-B. STT PoC (Realtime STT 모델) — RunPod Pod

> 한국어 라이브 전사 + loanword 보존 (영문 단어가 한글로 음차되지 않고 라틴 그대로 유지) 검증 목적. 기존 CNN STT Pod와 별도로 띄워 A/B 비교. 통과 시 기존 `runpod_stt` 대체 후보.

WebSocket 프로토콜은 `runpod_stt`와 **완전히 동일** (`f32 LE PCM 16kHz mono` ↔ `{"text", "is_partial"}` JSON). 내부는 vLLM Realtime API를 호출하는 어댑터 패턴.

### 아키텍처

```
client WS (port 8765, public)
    ↓  this process (server.py adapter)
    ↓     ├─ f32 PCM → base64 PCM16 변환
    ↓     ├─ transcription.delta / .done → {text, is_partial}
    ↓     └─ {cmd: reset} → 업스트림 WS 재오픈으로 인코더 cache flush
    ↓
vLLM Realtime API (localhost:8001/v1/realtime)
```

### Network Volume 사전 준비 (최초 1회)

이미지에서 RealtimeSTT weights (~9GB)를 분리해 Network Volume 에 캐시합니다 — 이미지 크기 <10GB 유지, 첫 Pod 만 download 비용 부담 (~60-90s), 이후 재시작/추가 Pod 는 캐시 hit.

1. RunPod Console → **Storage** → **New Network Volume**
   - Name: `realtime-stt-cache` (또는 임의)
   - Datacenter: Pod 띄울 리전과 동일 (예: `EU-RO-1`)
   - Size: **15GB** 권장 (현재 모델 ~9GB + 여유)
2. 비용: ~$0.07/GB/월 → 15GB ≈ $1.05/월

### 호스트 드라이버 요구사항 (필수 확인)

이미지가 vllm cu129 (CUDA 12.9) 빌드로 컴파일되어 있어서 **호스트 NVIDIA 드라이버가 575 이상 (CUDA 12.9 지원) 이어야 합니다**. RunPod 의 L4 호스트 풀은 driver 570~580 이 섞여 배정되니, 첫 부팅 후 `nvidia-smi` 한 번 찍어서 확인:

```bash
nvidia-smi | head -5
# 우측 상단 CUDA Version 이 12.9 이상이면 OK
# 12.8 이면 → 그 Pod 는 못 씀, stop + delete + 재생성으로 다른 호스트 배정 받기
```

호스트 부적합 시 vLLM 로그에 `RuntimeError: The NVIDIA driver on your system is too old (found version 12080)` 가 뜹니다. 이 경우 Pod 재생성 외에 다른 해결책 없음 (vllm cu128 빌드가 공식적으로 없어서).

### Pod 생성

1. RunPod Console → **Deploy** → **GPU Pod**
2. Container Image: `ghcr.io/your-org/relay-realtime-stt-stt:latest`
3. Container Registry Credentials: `ghcr-cred`
4. GPU: **L4 24GB** (PoC baseline, 기존 CNN STT Pod와 동일 GPU로 비교) — capacity 부족 시 **RTX 4090 24GB** 또는 **L40S 48GB**
5. **Network Volume**: 위에서 만든 `realtime-stt-cache` 선택, mount path `/runpod-volume` (RunPod 기본값)
6. Expose ports: `8765`
7. Environment Variables:
   ```
   RELAY_INTERNAL_KEY=<your-key>
   RELAY_INTERNAL_KEY_PREV=<prev-key>     # optional
   GIT_PAT=<github-pat-with-repo-read>    # zero-rebuild code reload
   GIT_REF=main                            # optional
   # HF_TOKEN=<hf-token>                   # optional — RealtimeSTT 은 Apache-2.0 / 비-gated 라 익명 다운로드 가능. 익명 rate-limit 회피용으로만 의미
   # PoC 튜닝 노브 (전부 optional):
   # VLLM_MAX_NUM_SEQS=16                  # 동시 처리 시퀀스 수, capacity 테스트 시 상향 검토
   # VLLM_MAX_MODEL_LEN=45000              # ~1시간 audio 분량 (RealtimeSTT 1토큰=80ms 기준)
   # VLLM_GPU_MEM_UTIL=0.90
   #
   # 주의: vLLM Realtime API (v0.21.0)는 session.update에서 {type, model}만
   # 검증함 — transcription_delay_ms / language / temperature 등 OpenAI 표준
   # 필드는 silently dropped. RealtimeSTT commit delay는 모델 컴파일 기본값으로
   # 고정. 추후 vLLM upstream이 session-level knob 추가하면 재도입 가능.
   ```
8. Deploy

> **첫 콜드 스타트**: weight download (~60-90s) + vLLM CUDA-graph compile (~60s) = 총 2-3분.
> **이후 재시작**: download 스킵, 컴파일만 ~60s. Volume 을 공유하는 추가 Pod 도 동일.
> Network Volume 을 안 붙이면 매 콜드 스타트마다 download 반복 (경고 로그 출력 후 in-container cache 로 fallback).

### 환경변수 (PoC 비교용)

기존 STT URL을 그대로 쓰면 Tauri 클라이언트 코드 변경 0:

```
RELAY_NEMO_STT_URL=wss://<realtime-stt-pod-id>-8765.proxy.runpod.net/
```

기존 CNN STT Pod와 토글하면서 PoC 측정 가능.

### PoC 측정 항목 (의사결정 게이트 순서)

1. **Loanword 보존도** — 한국어 발화 안의 영어 약어/단어 (AI, API, PR, KPI, GPU 등) 라틴 보존 비율. **합격: ≥95%**
2. **단일 세션 partial UX** — TTFT, partial 갱신 간격, partial rewrite 빈도, code-switching 보존도. **합격: TTFT <500ms, 90% 이상 monotonic**
3. **회의 도메인 WER** — 자체 한국어 회의 30분 샘플
4. **동시 세션 capacity** — 1 → 10 → 50 → 100 → 150 단계별 스트레스. CNN STT 150 동시 검증치 대비 어느 지점에서 깨지는지 (`stress_test.py` 재활용 가능)
5. **장시간 안정성** — 8h 연속 운영 메모리/품질 drift

게이트 1 실패 → 즉시 후보 제거. 게이트 4에서 깨지면 GPU 업그레이드 시나리오 (RTX 4090 / L40S) 비용 의사결정.

### Zero-rebuild 코드 배포

`runpod_stt` / `runpod_translate`와 동일 패턴. `runpod_realtime_stt/server.py`만 수정 + `git push origin main` 후:
- Pod 재시작, 또는
- `POST /admin/reload` (X-Internal-Key 헤더): FastAPI 어댑터만 ~2s 재기동, vLLM 서브프로세스는 살아있어 모델 재로드 없음

---

## 2. Inference (Chat) — RunPod Serverless, Always-On

회의 진행 중 실시간 summary / intent 추출용. cold start 가 UX 직격탄이라 **Min Workers: 1** 로 고정.

### Serverless Endpoint 생성

1. RunPod Console → **Serverless** → **New Endpoint**
2. Container Image: `ghcr.io/your-org/relay-inference:latest`
3. Container Registry Credentials: `ghcr-cred`
4. **Container Start Command**: `python3 handler.py`
5. GPU: **L4**
6. **Min Workers: 1** (always-on)
7. Max Workers: `2`
8. Environment Variables:
   ```
   RELAY_INTERNAL_KEY=<your-key>
   RELAY_INTERNAL_KEY_PREV=<prev-key>   # optional
   # 옵션: 기본값 변경 시
   # SUMMARY_MODEL=google/gemma-4-E2B-it
   # VLLM_MAX_MODEL_LEN=8192
   # VLLM_MAX_NUM_SEQS=16
   # VLLM_GPU_MEM_UTIL=0.85
   ```
9. Deploy

### API 호출 방식

```python
import httpx

resp = httpx.post(
    f"https://api.runpod.ai/v2/{INFERENCE_ENDPOINT_ID}/runsync",
    headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
    json={
        "input": {
            "_internal_key": RELAY_INTERNAL_KEY,
            "messages": [...],
            # model 생략 가능
        }
    },
    timeout=120,
)
result = resp.json()["output"]  # OpenAI-compatible chat completions response
```

---

## 3. Embedding — RunPod Serverless, Scale-to-Zero

Notion 동기화 같은 sparse batch 워크로드. **Min Workers: 0** 으로 idle 시 GPU 비용 0. 호출 시 cold start ~30s-1분 (이미지에 weights baked-in 덕분).

### Serverless Endpoint 생성

1. RunPod Console → **Serverless** → **New Endpoint**
2. Container Image: `ghcr.io/your-org/relay-embedding:latest`
3. Container Registry Credentials: `ghcr-cred`
4. **Container Start Command**: `python3 handler.py`
5. GPU: **L4** (Qwen3-0.6B 는 가벼워서 더 작은 GPU 도 가능 — 비용 우선이면 A4000 검토)
6. **Min Workers: 0** (scale-to-zero)
7. Max Workers: `3` (동기화 spike 흡수용)
8. Environment Variables:
   ```
   RELAY_INTERNAL_KEY=<your-key>
   RELAY_INTERNAL_KEY_PREV=<prev-key>   # optional
   # MODEL_NAME=Qwen/Qwen3-Embedding-0.6B
   # VLLM_MAX_MODEL_LEN=8192
   # VLLM_MAX_NUM_SEQS=32
   # VLLM_GPU_MEM_UTIL=0.85
   ```
9. Deploy

### API 호출 방식

```python
resp = httpx.post(
    f"https://api.runpod.ai/v2/{EMBEDDING_ENDPOINT_ID}/runsync",
    headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
    json={
        "input": {
            "_internal_key": RELAY_INTERNAL_KEY,
            "input": ["chunk 1 text", "chunk 2 text", "..."],
        }
    },
    timeout=120,  # cold start 시 첫 호출은 1-2분 가능 — 동기화는 background 권장
)
data = resp.json()["output"]["data"]
vectors = [d["embedding"] for d in data]   # 1024-d float arrays
```

### 차원 잘라쓰기 (Matryoshka)

Qwen3-Embedding-0.6B 는 dimension 잘라쓰기를 지원합니다. 사용자 PC sqlite 사이즈를 줄이고 싶으면 클라이언트에서 받은 1024-d 벡터의 앞 N차원만 쓰고 정규화:

```python
import numpy as np

def truncate_and_normalize(vec: list[float], dim: int = 256) -> list[float]:
    v = np.array(vec[:dim], dtype=np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()
```

256-d 로 자르면 디스크 사용량이 1024-d 의 1/4. 품질 vs 용량 트레이드오프 — 같은 임베딩으로 차원만 조정 가능.

---

## 4. Translate — RunPod Serverless

백엔드는 vLLM, 모델은 `google/translategemma-4b-it` (이미지에 baked-in). 사용 빈도에 따라 Min Workers 조정 (실시간 회의 번역이면 1, sparse 하면 0).

### Serverless Endpoint 생성

Inference 와 동일한 방법으로 생성 — Container Image 를 `ghcr.io/your-org/relay-translate:latest` 로 바꾸면 됨. Environment Variables 는 `MODEL_NAME` / `VLLM_*` 패턴.

### API 호출 방식

```python
resp = httpx.post(
    f"https://api.runpod.ai/v2/{TRANSLATE_ENDPOINT_ID}/runsync",
    headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
    json={
        "input": {
            "_internal_key": RELAY_INTERNAL_KEY,
            "text": "Hello world",
        }
    },
    timeout=60,
)
translation = resp.json()["output"]["translation"]
```

---

## Auth 차이점 요약

| | Modal | RunPod |
|---|---|---|
| STT | `?key=<hmac-or-static>` (WS query param) | 동일 — 변경 없음 |
| Inference (chat) | `X-Internal-Key` header | `_internal_key` in request body |
| Embedding | (신규) | `_internal_key` in request body |
| Translate | `X-Internal-Key` header | `_internal_key` in request body |
| 외부 인증 | Modal이 URL 기반으로 격리 | RunPod API Key (`Bearer`) |

RunPod API Key 가 1차 인증 역할을 하므로, `_internal_key` 는 2차 방어선.
앱 코드에서 inference/embedding/translate 클라이언트를 각자의 endpoint ID 로 호출.
