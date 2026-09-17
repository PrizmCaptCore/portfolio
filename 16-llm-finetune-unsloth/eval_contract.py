"""Contract eval for the merged model, run through vLLM's offline engine.

    python eval_contract.py --model runs/summary-merged --data data/sft/val.jsonl

Reports, in order of how much they mattered for shipping:
  1. json_valid        fraction of outputs that parse as JSON with no surrounding text
  2. schema_ok         ... and match the {"summary", "intents": [{type,text,owner}]} contract
  3. intent_type_acc   multiset match of intent types vs. the label (order-insensitive)
  4. latin_keep        English technical terms present in the transcript that survive in Latin script
                       in the summary (not transliterated to Hangul)
  5. summary_len_ok    3-6 sentences

Gates used for release: json_valid >= 0.99, schema_ok >= 0.98, latin_keep >= 0.95. Anything below
that went back to the data, not to the prompt.
"""
import argparse
import collections
import json
import re

from vllm import LLM, SamplingParams

INTENT_TYPES = {"action", "decision", "question", "followup"}
LATIN_TERM = re.compile(r"\b[A-Z][A-Za-z0-9]{1,}\b")  # AI, API, KPI, PR, GPU, Notion, ...
SENT_SPLIT = re.compile(r"[.!?。]\s+|[.!?。]$")


def parse(text):
    text = text.strip()
    if text.startswith("```"):
        return None  # fenced output counts as a contract violation
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def schema_ok(obj):
    if not isinstance(obj.get("summary"), str) or not isinstance(obj.get("intents"), list):
        return False
    for it in obj["intents"]:
        if not isinstance(it, dict) or it.get("type") not in INTENT_TYPES:
            return False
        if not isinstance(it.get("text"), str) or it.get("owner") not in ("Me", "Speaker", None):
            return False
    return True


def latin_keep(transcript, summary):
    terms = set(LATIN_TERM.findall(transcript))
    if not terms:
        return None
    kept = sum(1 for t in terms if t in summary)
    return kept / len(terms)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8") if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    llm = LLM(model=args.model, max_model_len=8192, gpu_memory_utilization=0.85)
    prompts = [llm.get_tokenizer().apply_chat_template(r["messages"][:2], tokenize=False, add_generation_prompt=True)
               for r in rows]
    outs = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=args.max_tokens))

    stats = collections.Counter()
    latin = []
    for r, o in zip(rows, outs):
        stats["n"] += 1
        text = o.outputs[0].text
        obj = parse(text)
        if obj is None:
            continue
        stats["json_valid"] += 1
        if not schema_ok(obj):
            continue
        stats["schema_ok"] += 1

        gold = json.loads(r["messages"][2]["content"])
        if collections.Counter(i["type"] for i in obj["intents"]) == collections.Counter(i["type"] for i in gold["intents"]):
            stats["intent_type_acc"] += 1
        n_sent = len([s for s in SENT_SPLIT.split(obj["summary"]) if s.strip()])
        if 3 <= n_sent <= 6:
            stats["summary_len_ok"] += 1
        lk = latin_keep(r["messages"][1]["content"], obj["summary"])
        if lk is not None:
            latin.append(lk)

    n = stats["n"]
    print(f"n={n}")
    for k in ("json_valid", "schema_ok", "intent_type_acc", "summary_len_ok"):
        print(f"{k:16s} {stats[k] / n:.3f}")
    print(f"{'latin_keep':16s} {sum(latin) / len(latin):.3f}  (over {len(latin)} windows with Latin terms)")


if __name__ == "__main__":
    main()
