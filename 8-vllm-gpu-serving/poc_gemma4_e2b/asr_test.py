import argparse
import threading
import time

import torch
from transformers import AutoModelForMultimodalLM, AutoProcessor, TextIteratorStreamer

MODEL_ID = "google/gemma-4-E2B-it"

ASR_KO = (
    "Transcribe the following speech segment in Korean into Korean text.\n"
    "Follow these specific instructions for formatting the answer:\n"
    "* Only output the transcription, with no newlines.\n"
    "* When transcribing numbers, write the digits."
)

AST_KO_TMPL = (
    "Transcribe the following speech segment in Korean, then translate it into {target}.\n"
    "When formatting the answer, first output the transcription in Korean, then one newline, "
    "then output the string '{target}: ', then the translation in {target}."
)


def build_messages(audio_path, task, target_lang):
    text = ASR_KO if task == "asr" else AST_KO_TMPL.format(target=target_lang)
    return [
        {
            "role": "user",
            "content": [
                {"type": "audio", "audio": audio_path},
                {"type": "text", "text": text},
            ],
        }
    ]


def pick_device():
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="Path to wav (<=30s, 16kHz mono)")
    ap.add_argument("--task", choices=["asr", "ast"], default="asr")
    ap.add_argument("--target-lang", default="English")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    args = ap.parse_args()

    device = pick_device()
    print(f"[env] device={device}", flush=True)
    if device == "xpu":
        print(f"[env] xpu_name={torch.xpu.get_device_name(0)}", flush=True)

    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForMultimodalLM.from_pretrained(
        MODEL_ID, dtype="auto", device_map=device
    )

    inputs = processor.apply_chat_template(
        build_messages(args.audio, args.task, args.target_lang),
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
        add_generation_prompt=True,
    ).to(model.device)

    streamer = TextIteratorStreamer(
        processor.tokenizer, skip_prompt=True, skip_special_tokens=False
    )
    gen_thread = threading.Thread(
        target=model.generate,
        kwargs=dict(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            streamer=streamer,
        ),
    )
    gen_thread.start()

    t0 = time.perf_counter()
    ttft = None
    n_tokens = 0
    for piece in streamer:
        if ttft is None:
            ttft = time.perf_counter() - t0
            print(f"\n[ttft] {ttft * 1000:.0f}ms", flush=True)
        n_tokens += 1
        print(piece, end="", flush=True)
    gen_thread.join()
    elapsed = time.perf_counter() - t0
    print(
        f"\n[stats] tokens={n_tokens} elapsed={elapsed:.2f}s tok_per_s={n_tokens / elapsed:.1f}"
    )


if __name__ == "__main__":
    main()
