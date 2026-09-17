"""LoRA SFT with unsloth + TRL. Single 24GB GPU, 4-bit base, completion-only loss.

    python train_sft.py --data data/sft --base google/gemma-4-E2B-it --out runs/summary-lora --epochs 2

Why the choices below:
  * load_in_4bit + LoRA on attention+MLP projections: fits a 2-4B model with seq 4096 on one consumer GPU
  * use_gradient_checkpointing="unsloth": offloads activations smartly; ~30% more throughput than "true"
  * completion-only: loss on the assistant turn only. The transcript is 10x longer than the answer and
    we do not want the model to learn to reproduce meetings
  * packing off: windows are long and variable; packing would let one meeting's tail bleed into another's head
  * lr 2e-4, cosine, warmup 3%: unsloth's recommended LoRA range; 2 epochs was the knee on val loss,
    a 3rd started to memorize summaries verbatim
"""
import argparse
import os

from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel
from unsloth.chat_templates import train_on_responses_only


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="dir with train.jsonl / val.jsonl from build_dataset.py")
    p.add_argument("--base", default="google/gemma-4-E2B-it")
    p.add_argument("--out", default="runs/summary-lora")
    p.add_argument("--max-seq", type=int, default=4096)
    p.add_argument("--epochs", type=float, default=2.0)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--r", type=int, default=16)
    p.add_argument("--batch", type=int, default=2)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--seed", type=int, default=3407)
    args = p.parse_args()

    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.base,
        max_seq_length=args.max_seq,
        load_in_4bit=True,
        dtype=None,  # auto: bf16 on Ampere+, fp16 otherwise
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.r,
        lora_alpha=args.r,  # alpha == r: keep the effective scale at 1
        lora_dropout=0.0,   # unsloth fast path requires 0
        bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    ds = load_dataset("json", data_files={
        "train": os.path.join(args.data, "train.jsonl"),
        "val": os.path.join(args.data, "val.jsonl"),
    })

    def to_text(batch):
        return {"text": [tok.apply_chat_template(m, tokenize=False, add_generation_prompt=False)
                         for m in batch["messages"]]}

    ds = ds.map(to_text, batched=True, remove_columns=["messages"])

    trainer = SFTTrainer(
        model=model,
        tokenizer=tok,
        train_dataset=ds["train"],
        eval_dataset=ds["val"],
        args=SFTConfig(
            output_dir=args.out,
            dataset_text_field="text",
            max_seq_length=args.max_seq,
            packing=False,
            per_device_train_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            warmup_ratio=0.03,
            weight_decay=0.01,
            optim="adamw_8bit",
            bf16=True,
            logging_steps=10,
            eval_strategy="steps",
            eval_steps=100,
            save_strategy="steps",
            save_steps=100,
            save_total_limit=3,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            seed=args.seed,
            report_to="tensorboard",
        ),
    )

    # Gemma chat template: loss only on the model turn. Marker strings are the template's role headers.
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<start_of_turn>user\n",
        response_part="<start_of_turn>model\n",
    )

    trainer.train()
    model.save_pretrained(args.out)   # LoRA adapter only; export_vllm.py merges it
    tok.save_pretrained(args.out)
    print(f"adapter saved to {args.out}")


if __name__ == "__main__":
    main()
