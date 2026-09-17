#!/usr/bin/env python3
"""
한국어 SentencePiece BPE 토크나이저 학습.

NeMo manifest 파일들에서 텍스트를 추출해 SentencePiece 모델을 학습합니다.
학습된 토크나이저는 NeMo CTC 모델에서 바로 사용할 수 있는 형식으로 저장됩니다.

Usage:
    python scripts/train_tokenizer.py \
        --manifests data/manifests/cv_train.json data/manifests/fleurs_train.json \
        --output-dir tokenizer/ \
        --vocab-size 4096
"""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


def extract_texts_from_manifests(manifest_paths: list[str]) -> list[str]:
    texts = []
    for path in manifest_paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                text = entry.get("text", "").strip()
                if text:
                    texts.append(text)
    print(f"Extracted {len(texts):,} utterances from {len(manifest_paths)} manifest(s)")
    return texts


def normalize_korean(text: str) -> str:
    """기본 정규화: 특수문자 제거, 소문자화, 공백 정리."""
    # 한국어, 영어, 숫자, 기본 구두점만 유지
    text = re.sub(r"[^\uAC00-\uD7A3a-zA-Z0-9\s\.,\?!']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def train_tokenizer(texts: list[str], output_dir: str, vocab_size: int):
    try:
        import sentencepiece as spm
    except ImportError:
        raise ImportError("Run: pip install sentencepiece")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 텍스트 파일로 저장
    text_file = output_dir / "corpus.txt"
    with open(text_file, "w", encoding="utf-8") as f:
        for text in texts:
            normalized = normalize_korean(text)
            if normalized:
                f.write(normalized + "\n")

    print(f"Corpus saved: {text_file} ({len(texts):,} lines)")

    # SentencePiece BPE 학습
    model_prefix = str(output_dir / "tokenizer")
    spm.SentencePieceTrainer.train(
        input=str(text_file),
        model_prefix=model_prefix,
        vocab_size=vocab_size,
        model_type="bpe",
        character_coverage=0.9999,   # 한국어 전체 커버
        pad_id=0,
        unk_id=1,
        bos_id=2,
        eos_id=3,
        pad_piece="<pad>",
        unk_piece="<unk>",
        bos_piece="<s>",
        eos_piece="</s>",
        user_defined_symbols=["▁"],  # word boundary
        byte_fallback=True,          # OOV 문자 처리
        split_digits=True,
        normalization_rule_name="nmt_nfkc",
    )

    print(f"Tokenizer trained -> {model_prefix}.model / {model_prefix}.vocab")

    # NeMo가 기대하는 디렉토리 구조로 복사
    # NeMo tokenizer dir에는 tokenizer.model 파일이 있어야 함
    import shutil
    shutil.copy(f"{model_prefix}.model", output_dir / "tokenizer.model")

    # vocab 크기 확인
    sp = spm.SentencePieceProcessor()
    sp.load(str(output_dir / "tokenizer.model"))
    print(f"Final vocab size: {sp.get_piece_size()}")

    # 샘플 테스트
    samples = ["안녕하세요", "회의를 시작하겠습니다", "오늘 날씨가 좋네요"]
    for s in samples:
        ids = sp.encode(s)
        decoded = sp.decode(ids)
        print(f"  '{s}' -> {ids} -> '{decoded}'")


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--manifests", nargs="+", required=True,
        help="NeMo manifest JSON 파일 경로들"
    )
    p.add_argument(
        "--output-dir", default="tokenizer/",
        help="토크나이저 저장 디렉토리 (default: tokenizer/)"
    )
    p.add_argument(
        "--vocab-size", type=int, default=4096,
        help="BPE vocab 크기 (default: 4096)"
    )
    args = p.parse_args()

    texts = extract_texts_from_manifests(args.manifests)
    if not texts:
        print("ERROR: manifest에서 텍스트를 추출하지 못했습니다.")
        return

    train_tokenizer(texts, args.output_dir, args.vocab_size)
    print(f"\nDone. 토크나이저: {args.output_dir}/tokenizer.model")


if __name__ == "__main__":
    main()
