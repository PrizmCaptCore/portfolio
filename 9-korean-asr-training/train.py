#!/usr/bin/env python3
"""
한국어 CTC ASR 학습 스크립트.

학습 순서:
  1. 데이터 준비:
       python scripts/prepare_data.py commonvoice-hf --output-dir data/manifests/
       python scripts/prepare_data.py fleurs --output-dir data/manifests/
       python scripts/prepare_data.py merge \
           --manifests data/manifests/cv_train.json data/manifests/fleurs_train.json \
           --output data/manifests/combined_train.json

  2. 토크나이저 학습:
       python scripts/train_tokenizer.py \
           --manifests data/manifests/combined_train.json \
           --output-dir tokenizer/ --vocab-size 4096

  3. Parakeet 인코더 이식:
       python scripts/init_from_parakeet.py \
           --tokenizer-dir tokenizer/ \
           --output korean_ctc_init.nemo \
           --freeze-encoder       # 1단계: 인코더 고정

  4-A. 1단계 학습 (디코더만, 인코더 고정):
       python train.py \
           --init-model korean_ctc_init.nemo \
           --train-manifest data/manifests/combined_train.json \
           --val-manifest data/manifests/cv_val.json \
           --tokenizer-dir tokenizer/ \
           --max-epochs 15 --lr 1e-4 \
           --stage 1

  4-B. 2단계 학습 (전체 fine-tuning):
       python train.py \
           --init-model outputs/korean-ctc-parakeet-encoder/checkpoints/last.ckpt \
           --train-manifest data/manifests/combined_train.json \
           --val-manifest data/manifests/cv_val.json \
           --tokenizer-dir tokenizer/ \
           --max-epochs 50 --lr 5e-5 \
           --stage 2
"""

import argparse
import os
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--init-model", required=True,
                   help="초기화된 .nemo 파일 또는 이전 checkpoint .ckpt 경로")
    p.add_argument("--train-manifest", required=True,
                   help="학습 manifest JSON 경로")
    p.add_argument("--val-manifest", required=True,
                   help="검증 manifest JSON 경로")
    p.add_argument("--tokenizer-dir", default="tokenizer/",
                   help="SentencePiece 토크나이저 디렉토리")
    p.add_argument("--config", default="configs/korean_ctc.yaml",
                   help="NeMo 학습 config YAML")
    p.add_argument("--max-epochs", type=int, default=50)
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--devices", type=int, default=1,
                   help="GPU 개수")
    p.add_argument("--stage", type=int, choices=[1, 2], default=2,
                   help="1=인코더 고정(디코더만 학습), 2=전체 fine-tuning")
    p.add_argument("--resume", action="store_true",
                   help="outputs/ 에서 마지막 checkpoint 이어서 학습")
    return p.parse_args()


def setup_model(args, cfg):
    """모델 로드 및 단계별 freeze 설정."""
    import nemo.collections.asr as nemo_asr

    init_path = args.init_model

    if init_path.endswith(".nemo"):
        print(f"Loading from .nemo: {init_path}")
        model = nemo_asr.models.EncDecCTCModelBPE.restore_from(init_path)
    elif init_path.endswith(".ckpt"):
        print(f"Resuming from checkpoint: {init_path}")
        model = nemo_asr.models.EncDecCTCModelBPE.load_from_checkpoint(init_path)
    else:
        raise ValueError(f"Unsupported model format: {init_path}")

    # 단계별 freeze
    if args.stage == 1:
        print("Stage 1: 인코더 고정, 디코더만 학습")
        for param in model.encoder.parameters():
            param.requires_grad = False
        # learning rate를 디코더용으로 높게 설정
        cfg.model.optim.lr = args.lr if args.lr != 5e-5 else 1e-4
    else:
        print("Stage 2: 전체 fine-tuning")
        for param in model.parameters():
            param.requires_grad = True
        cfg.model.optim.lr = args.lr

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Trainable: {trainable:,} / {total:,} params")

    # data config 업데이트
    model.cfg.train_ds.manifest_filepath = args.train_manifest
    model.cfg.train_ds.batch_size = args.batch_size
    model.cfg.validation_ds.manifest_filepath = args.val_manifest
    model.cfg.validation_ds.batch_size = args.batch_size

    model.setup_training_data(model.cfg.train_ds)
    model.setup_validation_data(model.cfg.validation_ds)

    return model


def main():
    args = parse_args()

    # NeMo / PyTorch Lightning import
    try:
        import nemo.collections.asr as nemo_asr
        from nemo.core.config import hydra_runner
        from nemo.utils import exp_manager
        from omegaconf import OmegaConf, open_dict
        import pytorch_lightning as pl
    except ImportError as e:
        print(f"ERROR: {e}")
        print("conda activate nemo 후 실행하세요.")
        return

    # config 로드
    cfg = OmegaConf.load(args.config)

    with open_dict(cfg):
        cfg.model.init_from_nemo_model = args.init_model
        cfg.model.tokenizer.dir = str(Path(args.tokenizer_dir).absolute())
        cfg.model.train_ds.manifest_filepath = args.train_manifest
        cfg.model.train_ds.batch_size = args.batch_size
        cfg.model.validation_ds.manifest_filepath = args.val_manifest
        cfg.model.validation_ds.batch_size = args.batch_size
        cfg.model.optim.lr = args.lr
        cfg.trainer.max_epochs = args.max_epochs
        cfg.trainer.devices = args.devices
        cfg.exp_manager.name = f"korean-ctc-stage{args.stage}"

    # 모델 로드
    model = setup_model(args, cfg)

    # Trainer 설정
    trainer = pl.Trainer(
        devices=args.devices,
        accelerator="gpu",
        max_epochs=args.max_epochs,
        accumulate_grad_batches=cfg.trainer.get("accumulate_grad_batches", 2),
        gradient_clip_val=1.0,
        log_every_n_steps=50,
        precision="16-mixed",
        enable_checkpointing=True,
    )

    # Experiment Manager (체크포인트, 로깅)
    exp_manager.exp_manager(trainer, cfg.get("exp_manager", None))

    print(f"\n{'='*50}")
    print(f"Stage {args.stage} 학습 시작")
    print(f"  Train: {args.train_manifest}")
    print(f"  Val:   {args.val_manifest}")
    print(f"  LR: {args.lr}, Epochs: {args.max_epochs}")
    print(f"{'='*50}\n")

    trainer.fit(model)

    # 최종 모델 저장
    final_path = f"outputs/korean_ctc_stage{args.stage}_final.nemo"
    model.save_to(final_path)
    print(f"\n최종 모델 저장: {final_path}")


if __name__ == "__main__":
    main()
