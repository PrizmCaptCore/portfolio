"""Labeled meeting chunks -> chat-format SFT JSONL (train/val).

Input rows (data/labeled_meetings.jsonl), one per meeting:
    {"meeting_id": "...", "lang": "ko|en|mixed",
     "transcript": [{"t": 12.3, "speaker": "Me|Speaker", "text": "..."}, ...],
     "labels": [{"upto_t": 600.0,
                 "summary": "...",
                 "intents": [{"type": "action|decision|question|followup", "text": "...", "owner": "Me|Speaker|null"}]}]}

Each label is a checkpoint: "given the transcript up to upto_t, this is the expected output".
That mirrors the live product, which calls the model on the transcript-so-far, not on a finished meeting.

Output rows (data/sft/{train,val}.jsonl):
    {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", "<json>"}]}

Rules:
  * the assistant target is ALWAYS one JSON object matching SCHEMA; anything else is dropped, not fixed
  * the user turn is the transcript window ending at upto_t, trimmed from the front to --max-tokens
  * exact-duplicate (transcript window, target) pairs are dropped; near-duplicates across checkpoints of
    the same meeting are kept on purpose -- the model must learn that the summary grows monotonically
  * split is by meeting_id so no meeting leaks across train/val
"""
import argparse
import hashlib
import json
import os
import random

from transformers import AutoTokenizer

SYSTEM = (
    "You are a meeting assistant. Given the transcript so far, return ONE JSON object with keys "
    '"summary" (string, 3-6 sentences, same language as the meeting) and "intents" (list of '
    '{"type": "action|decision|question|followup", "text": string, "owner": "Me"|"Speaker"|null}). '
    "Keep English technical terms in Latin script. Output JSON only."
)

INTENT_TYPES = {"action", "decision", "question", "followup"}
OWNERS = {"Me", "Speaker", None}


def valid_target(label):
    """Schema gate. Returns the canonical JSON string or None."""
    if not isinstance(label.get("summary"), str) or not label["summary"].strip():
        return None
    intents = label.get("intents")
    if not isinstance(intents, list):
        return None
    clean = []
    for it in intents:
        if not isinstance(it, dict) or it.get("type") not in INTENT_TYPES:
            return None
        if not isinstance(it.get("text"), str) or not it["text"].strip():
            return None
        if it.get("owner") not in OWNERS:
            return None
        clean.append({"type": it["type"], "text": it["text"].strip(), "owner": it.get("owner")})
    return json.dumps({"summary": label["summary"].strip(), "intents": clean}, ensure_ascii=False)


def window_text(transcript, upto_t):
    lines = [f"[{seg['speaker']}] {seg['text'].strip()}" for seg in transcript if seg["t"] <= upto_t]
    return "\n".join(lines)


def trim_front(text, tok, max_tokens):
    """Drop whole lines from the front until the window fits. The end of the transcript is what the
    live product cares about; the head is what the summary already covers."""
    lines = text.split("\n")
    while lines and len(tok(("\n".join(lines)))["input_ids"]) > max_tokens:
        lines.pop(0)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--raw", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--base", default="google/gemma-4-E2B-it", help="tokenizer for length budgeting")
    p.add_argument("--max-tokens", type=int, default=3500, help="user-turn budget; leave room for the answer")
    p.add_argument("--val-frac", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    tok = AutoTokenizer.from_pretrained(args.base)
    os.makedirs(args.out, exist_ok=True)
    random.seed(args.seed)

    meetings = [json.loads(l) for l in open(args.raw, encoding="utf-8") if l.strip()]
    ids = sorted({m["meeting_id"] for m in meetings})
    random.shuffle(ids)
    val_ids = set(ids[: max(1, int(len(ids) * args.val_frac))])

    seen, rows = set(), {"train": [], "val": []}
    dropped_schema = dropped_dup = 0
    for m in meetings:
        for label in m["labels"]:
            target = valid_target(label)
            if target is None:
                dropped_schema += 1
                continue
            user = trim_front(window_text(m["transcript"], label["upto_t"]), tok, args.max_tokens)
            key = hashlib.sha1((user + "\x00" + target).encode("utf-8")).hexdigest()
            if key in seen:
                dropped_dup += 1
                continue
            seen.add(key)
            rows["val" if m["meeting_id"] in val_ids else "train"].append({
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": target},
                ]
            })

    for split, data in rows.items():
        with open(os.path.join(args.out, f"{split}.jsonl"), "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"train {len(rows['train'])}  val {len(rows['val'])}  "
          f"dropped: schema {dropped_schema}, duplicate {dropped_dup}")


if __name__ == "__main__":
    main()
