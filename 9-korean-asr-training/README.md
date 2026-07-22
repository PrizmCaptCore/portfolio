# 한국어 ASR — Parakeet 인코더 전이 학습

> 회의 도메인 한국어 인식 품질이 기성 모델로는 부족해서, **직접 학습**했다.
> 처음부터 학습하는 대신 사전학습된 **영어 encoder 를 이식(transplant)** 해 음향 표현을
> 공짜로 얻고, 데이터 예산은 언어 계층(디코더 + 토크나이저)에 몰았다.

## 접근 (Encoder transfer, 2-stage)

```
nvidia/parakeet-unified-en-0.6b (사전학습 encoder)
        │  init_from_parakeet.py --freeze-encoder
        ▼
한국어 CTC 모델 (encoder = 이식, decoder = 신규, tokenizer = 한국어 BPE)
        │
        ├── STAGE 1 ── encoder 고정, decoder 만 학습 (LR 1e-4, ~15 epochs)
        │              음향 표현은 보존하고 한국어 출력 계층만 빠르게 정렬
        │
        └── STAGE 2 ── 전체 unfreeze, full fine-tuning (LR 5e-5, ~50 epochs)
                       encoder 까지 한국어에 미세 적응
```

## 왜 이렇게 설계했나 (Engineering decisions)

- **2단계 freeze/fine-tune 스케줄** — stage 1 에서 이식한 encoder 를 고정하고 decoder +
  새 토크나이저만 높은 LR 로 학습해 빠르게 정렬한 뒤, stage 2 에서 전체를 낮은 LR 로
  풀어 미세 적응. 초반부터 전체를 풀면 이식한 표현이 망가지는 걸 방지.
- **한국어 SentencePiece BPE 토크나이저** — 코퍼스 기반으로 학습, CTC head 에 맞춰 vocab
  크기(4096)를 의도적으로 설정.
- **상업적 사용 가능한 공개 코퍼스** — Common Voice / FLEURS(둘 다 CC-BY-4.0)를 단일 NeMo
  manifest 로 정규화, 이후 인도메인 회의 음성을 합쳐 넣을 경로까지 설계.
- **Loanword 보존을 명시적 eval 게이트로** — 한국어 발화 속 영어 용어(AI, API, KPI 등)가
  한글로 음차되지 않고 라틴 그대로 유지되는지를 별도 합격 기준으로 측정.

## 구조

```
korean-asr-training/
├── scripts/
│   ├── prepare_data.py        # Common Voice / FLEURS → NeMo manifest
│   ├── train_tokenizer.py     # 한국어 SentencePiece BPE
│   └── init_from_parakeet.py  # Parakeet encoder 이식 → 한국어 CTC 초기화
├── configs/korean_ctc.yaml    # NeMo 학습 config
└── train.py                   # 메인 학습 (stage 1 → stage 2)
```

- [`train.py`](./train.py) — 단계별 freeze 로직과 학습 루프 발췌본.

## 기술 스택

**Technologies**: NVIDIA NeMo, PyTorch Lightning, SentencePiece, CTC, transfer learning,
mixed precision (16-bit), HuggingFace Datasets
