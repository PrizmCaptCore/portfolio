# 한국어 ASR — Parakeet 인코더 전이 학습

> 회의 도메인 한국어 인식 품질이 기성 모델로는 부족해서, **직접 학습**했다.
> 처음부터 학습하는 대신 사전학습된 **영어 encoder 를 이식(transplant)** 해 음향 표현을
> 공짜로 얻고, 데이터 예산은 언어 계층(디코더 + 토크나이저)에 몰았다.

## 접근 (Encoder transfer, 2-stage)

```text
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

## 왜 이렇게 설계했나

- **인코더 이식은 `strict=True` 로 검증한다.** `init_from_parakeet.py` 가 Parakeet 체크포인트를 CPU 에 올려
  `encoder.state_dict()` 만 뽑고, 같은 형상의 24-layer Conformer(d_model 1024, 8 heads, `dw_striding` ×8,
  `rel_pos`, conv kernel 9, 128-mel) 를 새 `EncDecCTCModelBPE` 에 선언한 뒤 strict 로드한다. 키 하나라도
  어긋나면 조용히 랜덤 초기화되는 대신 즉시 실패한다.
- **2단계 freeze/fine-tune 스케줄.** stage 1 에서 이식한 encoder 를 고정하고 decoder + 새 토크나이저 head 만
  높은 LR 로 정렬한 뒤, stage 2 에서 전체를 낮은 LR 로 풀어 미세 적응. 초반부터 전체를 풀면 이식한 표현이 망가진다.
- **한국어 SentencePiece BPE(4096).** `character_coverage=0.9999`, `byte_fallback=True`, `split_digits=True`,
  `nmt_nfkc` 정규화, pad/unk/bos/eos 를 0~3 으로 고정. CTC head 크기와 맞물리는 값이라 config 와 함께 관리한다.
- **상업적 사용 가능한 공개 코퍼스만.** Common Voice 17.0 Korean(~800h) + FLEURS `ko_kr`(~10h), 둘 다 CC-BY-4.0.
  단일 NeMo JSONL manifest 로 정규화하고, 이후 인도메인 회의 음성을 `merge` 로 합쳐 넣을 경로까지 열어 뒀다.
- **Common Voice 는 gated 데이터셋이라 `datasets` loading script 에 기대지 않는다.** `huggingface_hub` 로
  tar 를 직접 받아 멤버를 인덱싱하며 스트리밍 추출하고, librosa 로 16kHz 리샘플, 0.5~20s 클립만 남긴다.
  인증 실패(401/403/gated)는 로그인·약관 동의 안내로 바로 바꿔 준다. 토큰 값은 코드에 없다(`token=True` 는 캐시된 로그인 사용).
- **길이 버킷팅.** [2,5,8,12,16,20]s 경계에 배치 [32,24,16,12,8,4] 를 매핑해 패딩 낭비를 줄이고,
  16-bit + `accumulate_grad_batches: 2` 로 단일 GPU 에서 유효 배치 32 를 맞춘다.
  AdamW(0.9, 0.98), wd 1e-3, CosineAnnealing warmup 2,000 step, SpecAugment(freq 2×27, time 10×5%).

## 구조

```text
korean-asr-training/
├── scripts/
│   ├── prepare_data.py        # Common Voice(HF hub 직접 다운로드) / FLEURS → NeMo manifest, merge
│   ├── train_tokenizer.py     # 한국어 SentencePiece BPE
│   └── init_from_parakeet.py  # Parakeet encoder 이식 → 한국어 CTC 초기화 (.nemo)
├── configs/korean_ctc.yaml    # NeMo config: preprocessor/encoder/decoder/spec-augment/optim/bucketing/exp_manager
└── train.py                   # stage 1 → stage 2, exp_manager(monitor val_wer, save_top_k 3, resume)
```

## 학습 순서

```bash
conda activate nemo
pip install sentencepiece soundfile librosa huggingface_hub datasets

# 1. 데이터 (Common Voice 는 huggingface-cli login + Mozilla 약관 동의 필요)
python scripts/prepare_data.py commonvoice-hf --output-dir data/manifests/
python scripts/prepare_data.py fleurs --output-dir data/manifests/
python scripts/prepare_data.py merge \
    --manifests data/manifests/cv_train.json data/manifests/fleurs_train.json \
    --output data/manifests/combined_train.json

# 2. 토크나이저
python scripts/train_tokenizer.py --manifests data/manifests/combined_train.json \
    --output-dir tokenizer/ --vocab-size 4096

# 3. 인코더 이식
python scripts/init_from_parakeet.py --tokenizer-dir tokenizer/ \
    --output korean_ctc_init.nemo --freeze-encoder

# 4-A. stage 1: decoder 만
python train.py --init-model korean_ctc_init.nemo \
    --train-manifest data/manifests/combined_train.json --val-manifest data/manifests/cv_val.json \
    --tokenizer-dir tokenizer/ --stage 1 --max-epochs 15 --lr 1e-4

# 4-B. stage 2: 전체 fine-tuning
python train.py --init-model outputs/korean-ctc-stage1/checkpoints/last.ckpt \
    --train-manifest data/manifests/combined_train.json --val-manifest data/manifests/cv_val.json \
    --tokenizer-dir tokenizer/ --stage 2 --max-epochs 50 --lr 5e-5
```

인도메인 데이터를 추가할 때는 같은 manifest 포맷으로 변환한 뒤 `prepare_data.py merge` 로 합친다.
데이터, 토크나이저, 체크포인트(`.nemo`, `.ckpt`)는 포함하지 않는다.

## 라이선스

- Common Voice Korean, FLEURS Korean: CC-BY-4.0
- nvidia/parakeet-unified-en-0.6b: CC-BY-4.0 (저작자 표시 필요)

**Technologies**: NVIDIA NeMo, PyTorch Lightning, SentencePiece, CTC, transfer learning, mixed precision, huggingface_hub
