#!/usr/bin/env python3
"""
한국어 CTC ASR 학습 스크립트 (Parakeet 인코더 전이).

전략: 사전학습된 영어 encoder 를 한국어 CTC 모델에 이식한 뒤 2단계로 적응.
  - stage 1: encoder 고정(freeze), decoder + 새 tokenizer 만 학습 (높은 LR)
  - stage 2: 전체 unfreeze 후 낮은 LR 로 full fine-tuning

학습 순서:
  1) 데이터 준비   : scripts/prepare_data.py (Common Voice / FLEURS → NeMo manifest)
  2) 토크나이저    : scripts/train_tokenizer.py (한국어 SentencePiece BPE)
  3) 인코더 이식   : scripts/init_from_parakeet.py --freeze-encoder
  4) 학습          : 아래 train.py (--stage 1 → --stage 2)

* 포트폴리오용 발췌본입니다.
"""
import argparse
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--init-model", required=True,
                   help="초기화된 .nemo 파일 또는 이전 checkpoint .ckpt 경로")
    p.add_argument("--train-manifest", required=True, help="학습 manifest JSON 경로")
    p.add_argument("--val-manifest", required=True, help="검증 manifest JSON 경로")
    p.add_argument("--tokenizer-dir", default="tokenizer/", help="SentencePiece 토크나이저 디렉토리")
    p.add_argument("--config", default="configs/korean_ctc.yaml", help="NeMo 학습 config YAML")
    p.add_argument("--max-epochs", type=int, default=50)
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--devices", type=int, default=1, help="GPU 개수")
    p.add_argument("--stage", type=int, choices=[1, 2], default=2,
                   help="1=encoder 고정(decoder 만), 2=전체 fine-tuning")
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
        print("Stage 1: encoder 고정, decoder 만 학습")
        for param in model.encoder.parameters():
            param.requires_grad = False
        cfg.model.optim.lr = args.lr if args.lr != 5e-5 else 1e-4   # decoder 용으로 LR 상향
    else:
        print("Stage 2: 전체 fine-tuning")
        for param in model.parameters():
            param.requires_grad = True
        cfg.model.optim.lr = args.lr

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Trainable: {trainable:,} / {total:,} params")

    # data config
    model.cfg.train_ds.manifest_filepath = args.train_manifest
    model.cfg.train_ds.batch_size = args.batch_size
    model.cfg.validation_ds.manifest_filepath = args.val_manifest
    model.cfg.validation_ds.batch_size = args.batch_size
    model.setup_training_data(model.cfg.train_ds)
    model.setup_validation_data(model.cfg.validation_ds)
    return model


def main():
    args = parse_args()
    try:
        from nemo.utils import exp_manager
        from omegaconf import OmegaConf, open_dict
        import pytorch_lightning as pl
    except ImportError as e:
        print(f"ERROR: {e}\nconda activate nemo 후 실행하세요.")
        return

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

    model = setup_model(args, cfg)

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
    exp_manager.exp_manager(trainer, cfg.get("exp_manager", None))

    print(f"\n{'='*50}\nStage {args.stage} 학습 시작"
          f"\n  Train: {args.train_manifest}\n  Val:   {args.val_manifest}"
          f"\n  LR: {args.lr}, Epochs: {args.max_epochs}\n{'='*50}\n")
    trainer.fit(model)

    final_path = f"outputs/korean_ctc_stage{args.stage}_final.nemo"
    model.save_to(final_path)
    print(f"\n최종 모델 저장: {final_path}")


if __name__ == "__main__":
    main()
