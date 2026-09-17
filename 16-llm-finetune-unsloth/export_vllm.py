"""Merge the LoRA adapter into the base weights and write a plain HF directory vLLM can load.

    python export_vllm.py --base google/gemma-4-E2B-it --lora runs/summary-lora --out runs/summary-merged
    python export_vllm.py ... --push your-org/relay-summary-v3     # optional, private HF repo

We serve a merged 16-bit model rather than vLLM's LoRA path: no adapter hot-swap was needed, and the
serving image bakes weights at build time (see 8-vllm-gpu-serving/runpod_inference/Dockerfile), so a
single directory is the simplest artifact. unsloth's save_pretrained_merged does the dequant+merge
without materializing the 4-bit base twice.
"""
import argparse

from unsloth import FastLanguageModel


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="google/gemma-4-E2B-it")
    p.add_argument("--lora", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--push", default=None, help="HF repo id to push to (private)")
    p.add_argument("--max-seq", type=int, default=4096)
    args = p.parse_args()

    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.lora,          # adapter dir; unsloth resolves the base from adapter_config
        max_seq_length=args.max_seq,
        load_in_4bit=True,
        dtype=None,
    )
    # merged_16bit: dequantize base -> add LoRA delta -> bf16 safetensors + tokenizer + chat template
    model.save_pretrained_merged(args.out, tok, save_method="merged_16bit")
    print(f"merged model written to {args.out}")

    if args.push:
        model.push_to_hub_merged(args.push, tok, save_method="merged_16bit", private=True)
        print(f"pushed to {args.push}")


if __name__ == "__main__":
    main()
