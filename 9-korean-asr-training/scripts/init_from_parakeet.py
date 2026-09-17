#!/usr/bin/env python3
"""
Parakeet-unified 인코더 가중치를 한국어 CTC 모델에 이식.

1. nvidia/parakeet-unified-en-0.6b 로드
2. 인코더(ConformerEncoder) 가중치 추출
3. 한국어 SentencePiece 토크나이저 + 동일 인코더 구조로 새 CTC 모델 생성
4. 인코더 가중치 이식 (디코더는 랜덤 초기화 유지)
5. 초기화된 모델을 .nemo 파일로 저장

Usage:
    python scripts/init_from_parakeet.py \
        --tokenizer-dir tokenizer/ \
        --output korean_ctc_init.nemo \
        [--freeze-encoder]   # 초기 학습 시 인코더 고정 옵션
"""

import argparse
import os
from pathlib import Path

import torch


def build_korean_ctc_config(tokenizer_dir: str, vocab_size: int):
    """Parakeet 인코더와 동일한 구조의 CTC 모델 config 생성."""
    from omegaconf import OmegaConf

    tokenizer_dir = str(Path(tokenizer_dir).absolute())

    cfg = OmegaConf.create({
        "sample_rate": 16000,
        "log_prediction": True,

        "preprocessor": {
            "_target_": "nemo.collections.asr.modules.AudioToMelSpectrogramPreprocessor",
            "sample_rate": 16000,
            "normalize": "per_feature",
            "window_size": 0.025,
            "window_stride": 0.01,
            "window": "hann",
            "features": 128,
            "n_fft": 512,
            "frame_splicing": 1,
            "dither": 1.0e-05,
            "pad_to": 0,
            "pad_value": 0.0,
        },

        "spec_augment": {
            "_target_": "nemo.collections.asr.modules.SpectrogramAugmentation",
            "freq_masks": 2,
            "time_masks": 10,
            "freq_width": 27,
            "time_width": 0.05,
        },

        # Parakeet-unified 인코더와 완전히 동일한 구조
        "encoder": {
            "_target_": "nemo.collections.asr.modules.ConformerEncoder",
            "feat_in": 128,
            "feat_out": -1,
            "n_layers": 24,
            "d_model": 1024,
            "subsampling": "dw_striding",
            "subsampling_factor": 8,
            "subsampling_conv_channels": 256,
            "causal_downsampling": False,
            "reduction": None,
            "reduction_position": None,
            "reduction_factor": 1,
            "ff_expansion_factor": 4,
            "self_attention_model": "rel_pos",
            "n_heads": 8,
            "att_context_size": [-1, -1],
            "xscaling": True,
            "untie_biases": True,
            "pos_emb_max_len": 5000,
            "conv_kernel_size": 9,
            "conv_norm_type": "batch_norm",
            "conv_context_size": None,
            "dropout": 0.1,
            "dropout_pre_encoder": 0.1,
            "dropout_emb": 0.0,
            "dropout_att": 0.1,
            "stochastic_depth_drop_prob": 0.0,
            "stochastic_depth_mode": "linear",
            "stochastic_depth_start_layer": 1,
        },

        # CTC 디코더: d_model → vocab_size 선형 변환
        "decoder": {
            "_target_": "nemo.collections.asr.modules.ConvASRDecoder",
            "feat_in": 1024,   # encoder d_model
            "num_classes": -1,  # 토크나이저 vocab 크기로 자동 설정
            "vocabulary": [],
        },

        "tokenizer": {
            "dir": tokenizer_dir,
            "type": "bpe",
        },

        "ctc_reduction": "mean_batch",
        "skip_nan_grad": False,

        "optim": {
            "name": "adamw",
            "lr": 1e-4,
            "betas": [0.9, 0.98],
            "weight_decay": 1e-3,
            "sched": {
                "name": "CosineAnnealing",
                "warmup_steps": 5000,
                "warmup_ratio": None,
                "min_lr": 1e-6,
            },
        },
    })

    return cfg


def load_parakeet_encoder_weights() -> dict:
    """Parakeet-unified 인코더 가중치만 추출."""
    import nemo.collections.asr as nemo_asr

    print("Loading nvidia/parakeet-unified-en-0.6b ...")
    parakeet = nemo_asr.models.ASRModel.from_pretrained(
        "nvidia/parakeet-unified-en-0.6b",
        map_location=torch.device("cpu"),
    )
    parakeet.eval()

    encoder_state = parakeet.encoder.state_dict()
    print(f"Encoder state dict: {len(encoder_state)} tensors")

    # 메모리 해제
    del parakeet
    torch.cuda.empty_cache()

    return encoder_state


def init_korean_model(tokenizer_dir: str, output_path: str, freeze_encoder: bool):
    import nemo.collections.asr as nemo_asr
    import sentencepiece as spm

    # 토크나이저 vocab 크기 확인
    sp = spm.SentencePieceProcessor()
    sp.load(str(Path(tokenizer_dir) / "tokenizer.model"))
    vocab_size = sp.get_piece_size()
    print(f"Korean tokenizer vocab size: {vocab_size}")

    # 인코더 가중치 로드
    encoder_weights = load_parakeet_encoder_weights()

    # 한국어 CTC 모델 config 생성
    cfg = build_korean_ctc_config(tokenizer_dir, vocab_size)

    # 새 CTC 모델 초기화
    print("Initializing Korean CTC model ...")
    korean_model = nemo_asr.models.EncDecCTCModelBPE(cfg=cfg)

    # 인코더 가중치 이식
    print("Transferring Parakeet encoder weights ...")
    missing, unexpected = korean_model.encoder.load_state_dict(
        encoder_weights, strict=True
    )
    if missing:
        print(f"  WARNING - Missing keys: {missing}")
    if unexpected:
        print(f"  WARNING - Unexpected keys: {unexpected}")
    print("  Encoder weights transferred successfully.")

    # 인코더 freeze 옵션
    if freeze_encoder:
        for param in korean_model.encoder.parameters():
            param.requires_grad = False
        frozen = sum(p.numel() for p in korean_model.encoder.parameters())
        print(f"  Encoder frozen ({frozen:,} params). Only decoder will be trained initially.")
    else:
        print("  Encoder will be fine-tuned together with decoder.")

    trainable = sum(p.numel() for p in korean_model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in korean_model.parameters())
    print(f"  Trainable params: {trainable:,} / {total:,}")

    # .nemo 파일로 저장
    output_path = str(Path(output_path).absolute())
    korean_model.save_to(output_path)
    print(f"\nSaved -> {output_path}")
    print("이제 train.py로 학습을 시작할 수 있습니다.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--tokenizer-dir", default="tokenizer/",
        help="train_tokenizer.py로 생성한 토크나이저 디렉토리"
    )
    p.add_argument(
        "--output", default="korean_ctc_init.nemo",
        help="초기화된 모델 저장 경로"
    )
    p.add_argument(
        "--freeze-encoder", action="store_true",
        help="학습 초기에 인코더를 고정 (디코더만 먼저 학습)"
    )
    args = p.parse_args()

    tokenizer_model = Path(args.tokenizer_dir) / "tokenizer.model"
    if not tokenizer_model.exists():
        print(f"ERROR: 토크나이저가 없습니다: {tokenizer_model}")
        print("먼저 scripts/train_tokenizer.py를 실행하세요.")
        return

    init_korean_model(args.tokenizer_dir, args.output, args.freeze_encoder)


if __name__ == "__main__":
    main()
