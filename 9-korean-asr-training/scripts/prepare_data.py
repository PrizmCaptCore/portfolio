#!/usr/bin/env python3
"""
Common Voice Korean / FLEURS Korean → NeMo manifest 변환.

NeMo manifest 포맷 (JSONL):
  {"audio_filepath": "/abs/path/to/file.wav", "duration": 3.5, "text": "안녕하세요"}

Usage:
    # Common Voice
    python scripts/prepare_data.py commonvoice \
        --data-dir data/downloads/cv-corpus-ko \
        --output-dir data/manifests/

    # FLEURS
    python scripts/prepare_data.py fleurs \
        --output-dir data/manifests/

    # 두 데이터셋 합치기
    python scripts/prepare_data.py merge \
        --manifests data/manifests/cv_train.json data/manifests/fleurs_train.json \
        --output data/manifests/combined_train.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ── 공통 유틸 ──────────────────────────────────────────────────────────────────

def get_audio_duration(path: str) -> float:
    """ffprobe로 오디오 길이(초) 반환."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        # ffprobe 없으면 soundfile 시도
        try:
            import soundfile as sf
            info = sf.info(path)
            return info.duration
        except Exception:
            return 0.0


def normalize_text(text: str) -> str:
    """한국어 텍스트 기본 정규화."""
    text = text.strip()
    # 괄호 안 내용 제거 (발음 표기 등)
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\[.*?\]", "", text)
    # 연속 공백 정리
    text = re.sub(r"\s+", " ", text).strip()
    return text


def write_manifest(entries: list[dict], output_path: str):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"  Saved {len(entries):,} entries -> {output_path}")


# ── Common Voice ───────────────────────────────────────────────────────────────

def prepare_commonvoice(data_dir: str, output_dir: str):
    """
    Common Voice Korean 데이터를 NeMo manifest로 변환.

    data_dir 구조:
        cv-corpus-ko/
            clips/          ← mp3 오디오 파일들
            train.tsv
            dev.tsv
            test.tsv

    HuggingFace에서 직접 다운로드하려면:
        pip install datasets
        python -c "
        from datasets import load_dataset
        ds = load_dataset('mozilla-foundation/common_voice_17_0', 'ko',
                          trust_remote_code=True)
        ds.save_to_disk('data/downloads/cv-ko')
        "
    저장된 HuggingFace 데이터셋을 쓸 경우 --hf-dataset 플래그를 사용하세요.
    """
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)

    for split in ["train", "dev", "test"]:
        tsv_path = data_dir / f"{split}.tsv"
        if not tsv_path.exists():
            print(f"  Skipping {split} (not found: {tsv_path})")
            continue

        clips_dir = data_dir / "clips"
        entries = []

        with open(tsv_path, encoding="utf-8") as f:
            header = f.readline().strip().split("\t")
            path_idx = header.index("path")
            sentence_idx = header.index("sentence")

            for line in f:
                cols = line.strip().split("\t")
                if len(cols) <= max(path_idx, sentence_idx):
                    continue

                filename = cols[path_idx]
                text = normalize_text(cols[sentence_idx])
                if not text:
                    continue

                # mp3 → wav 변환 경로 (변환 스크립트 따로 실행 필요)
                wav_path = clips_dir / filename.replace(".mp3", ".wav")
                if not wav_path.exists():
                    # mp3 그대로 써도 NeMo가 처리 가능
                    wav_path = clips_dir / filename
                    if not wav_path.exists():
                        continue

                duration = get_audio_duration(str(wav_path))
                if duration < 0.5 or duration > 20.0:  # 너무 짧거나 긴 것 제외
                    continue

                entries.append({
                    "audio_filepath": str(wav_path.absolute()),
                    "duration": round(duration, 3),
                    "text": text,
                })

        out_split = "val" if split == "dev" else split
        write_manifest(entries, str(output_dir / f"cv_{out_split}.json"))


def prepare_commonvoice_hf(output_dir: str):
    """huggingface_hub으로 Common Voice 17 Korean raw 파일 직접 다운로드 후 변환.

    datasets 라이브러리의 loading script 지원 여부와 무관하게 동작.
    HuggingFace 로그인 + Mozilla 약관 동의 필요:
      huggingface-cli login
      (hf.co/datasets/mozilla-foundation/common_voice_17_0 에서 약관 동의)
    """
    try:
        import soundfile as sf
        import numpy as np
    except ImportError:
        print("ERROR: pip install soundfile numpy")
        sys.exit(1)

    try:
        from huggingface_hub import snapshot_download, list_repo_files, HfApi
    except ImportError:
        print("ERROR: pip install huggingface_hub")
        sys.exit(1)

    REPO_ID = "mozilla-foundation/common_voice_17_0"
    LANG = "ko"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir.parent / "cv_raw"
    audio_out_dir = output_dir.parent / "cv_audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 파일 목록 조회 (인증 + 약관 동의 체크) ──────────────────────────────
    print("Connecting to HuggingFace...")
    try:
        all_files = list(list_repo_files(REPO_ID, repo_type="dataset", token=True))
    except Exception as e:
        err = str(e)
        if any(k in err for k in ("401", "403", "gated", "access")):
            print("ERROR: HuggingFace 인증 실패 또는 Mozilla 약관 미동의.")
            print("  1. huggingface-cli login")
            print("  2. https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0")
            print("     에서 'Access repository' 클릭 후 약관 동의")
        else:
            print(f"ERROR: {e}")
        sys.exit(1)

    ko_tsvs  = sorted(f for f in all_files if f.endswith(".tsv") and f"/{LANG}/" in f)
    ko_tars  = sorted(f for f in all_files if f.endswith(".tar") and f"_{LANG}_" in f)

    if not ko_tsvs and not ko_tars:
        # 경로 패턴이 다를 수 있으므로 느슨하게 재시도
        ko_tsvs = sorted(f for f in all_files if f.endswith(".tsv") and LANG in f)
        ko_tars = sorted(f for f in all_files if f.endswith(".tar") and LANG in f)

    if not ko_tsvs:
        print("ERROR: 레포에서 한국어 TSV 파일을 찾을 수 없음.")
        print("발견된 파일 목록 (상위 30개):")
        for f in all_files[:30]:
            print(f"  {f}")
        sys.exit(1)

    print(f"TSV  파일: {ko_tsvs}")
    print(f"오디오 tar: {ko_tars[:3]}{'...' if len(ko_tars) > 3 else ''}")

    # ── 2. 한국어 파일만 다운로드 ─────────────────────────────────────────────
    patterns = [f"*/{LANG}/*.tsv", f"*{LANG}*.tar"]
    print(f"\n다운로드 중 (→ {work_dir}) ...")
    local_dir = snapshot_download(
        REPO_ID,
        repo_type="dataset",
        token=True,
        allow_patterns=patterns,
        local_dir=str(work_dir),
        local_dir_use_symlinks=False,
    )
    local_dir = Path(local_dir)

    # ── 3. TSV 파싱 + tar에서 오디오 추출 ────────────────────────────────────
    import tarfile, csv, io

    # split 이름 매핑 (CV 표준 split명 → 출력 split명)
    split_map = {
        "train":      "train",
        "dev":        "val",
        "validation": "val",
        "test":       "test",
        "other":      None,   # 스킵
        "invalidated": None,
    }

    # tar 파일 인덱스: mp3 파일명 → (tar_path, member)
    print("\ntar 파일 인덱싱 중...")
    tar_index: dict[str, tuple[Path, str]] = {}
    for tar_path in local_dir.rglob(f"*{LANG}*.tar"):
        with tarfile.open(tar_path, "r:*") as tf:
            for member in tf.getmembers():
                if member.isfile():
                    basename = Path(member.name).name
                    tar_index[basename] = (tar_path, member.name)
    print(f"인덱싱 완료: {len(tar_index):,}개 오디오 파일")

    # TSV → manifest
    for tsv_path in local_dir.rglob(f"*.tsv"):
        split_name = tsv_path.stem  # e.g. "train", "dev", "test"
        out_split = split_map.get(split_name)
        if out_split is None:
            continue

        print(f"\n{split_name} 처리 중...")
        entries = []

        with open(tsv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        for i, row in enumerate(rows):
            text = normalize_text(row.get("sentence", ""))
            if not text:
                continue

            mp3_name = Path(row.get("path", "")).name
            if mp3_name not in tar_index:
                continue

            tar_path, member_name = tar_index[mp3_name]
            wav_path = audio_out_dir / f"cv_{split_name}_{i:06d}.wav"

            try:
                with tarfile.open(tar_path, "r:*") as tf:
                    member_file = tf.extractfile(member_name)
                    if member_file is None:
                        continue
                    audio_bytes = member_file.read()

                import io
                wav_array, sr = sf.read(io.BytesIO(audio_bytes))
                wav_array = wav_array.astype(np.float32)
                if wav_array.ndim > 1:
                    wav_array = wav_array.mean(axis=1)

                if sr != 16000:
                    try:
                        import librosa
                        wav_array = librosa.resample(wav_array, orig_sr=sr, target_sr=16000)
                        sr = 16000
                    except ImportError:
                        pass

                duration = len(wav_array) / sr
                if duration < 0.5 or duration > 20.0:
                    continue

                sf.write(str(wav_path), wav_array, sr)
                entries.append({
                    "audio_filepath": str(wav_path.absolute()),
                    "duration": round(duration, 3),
                    "text": text,
                })

            except Exception as e:
                if i < 5:
                    print(f"  경고: {mp3_name} 처리 실패: {e}")
                continue

            if (i + 1) % 1000 == 0:
                print(f"  {i+1:,}/{len(rows):,} 처리 완료...")

        write_manifest(entries, str(output_dir / f"cv_{out_split}.json"))
        print(f"  → {len(entries):,}개 저장")


# ── FLEURS ─────────────────────────────────────────────────────────────────────

def prepare_fleurs(output_dir: str):
    """HuggingFace로 FLEURS Korean 다운로드 + 변환."""
    try:
        from datasets import load_dataset
        import soundfile as sf
        import numpy as np
    except ImportError:
        print("ERROR: pip install datasets soundfile")
        sys.exit(1)

    output_dir = Path(output_dir)
    audio_dir = output_dir.parent / "fleurs_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    print("Downloading FLEURS Korean from HuggingFace...")
    ds = load_dataset("google/fleurs", "ko_kr", trust_remote_code=True)

    split_map = {"train": "train", "validation": "val", "test": "test"}

    for hf_split, out_split in split_map.items():
        if hf_split not in ds:
            continue

        print(f"Processing {hf_split} ({len(ds[hf_split]):,} samples)...")
        entries = []

        for i, sample in enumerate(ds[hf_split]):
            text = normalize_text(sample.get("transcription", ""))
            if not text:
                continue

            audio = sample["audio"]
            wav_array = np.array(audio["array"], dtype=np.float32)
            sr = audio["sampling_rate"]

            if sr != 16000:
                try:
                    import librosa
                    wav_array = librosa.resample(wav_array, orig_sr=sr, target_sr=16000)
                    sr = 16000
                except ImportError:
                    pass

            wav_path = audio_dir / f"fleurs_{hf_split}_{i:06d}.wav"
            sf.write(str(wav_path), wav_array, sr)

            duration = len(wav_array) / sr
            if duration < 0.5 or duration > 20.0:
                wav_path.unlink(missing_ok=True)
                continue

            entries.append({
                "audio_filepath": str(wav_path.absolute()),
                "duration": round(duration, 3),
                "text": text,
            })

        write_manifest(entries, str(output_dir / f"fleurs_{out_split}.json"))


# ── Merge ──────────────────────────────────────────────────────────────────────

def merge_manifests(manifest_paths: list[str], output_path: str):
    """여러 manifest를 하나로 합침."""
    all_entries = []
    for path in manifest_paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    all_entries.append(json.loads(line))

    import random
    random.shuffle(all_entries)
    write_manifest(all_entries, output_path)
    print(f"Merged {len(manifest_paths)} manifests -> {len(all_entries):,} total entries")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    # commonvoice (로컬 tsv)
    cv = sub.add_parser("commonvoice", help="Common Voice TSV 디렉토리 변환")
    cv.add_argument("--data-dir", required=True)
    cv.add_argument("--output-dir", default="data/manifests/")

    # commonvoice-hf (HuggingFace 자동 다운로드)
    cvhf = sub.add_parser("commonvoice-hf", help="Common Voice HuggingFace 자동 다운로드")
    cvhf.add_argument("--output-dir", default="data/manifests/")

    # fleurs
    fl = sub.add_parser("fleurs", help="FLEURS HuggingFace 자동 다운로드")
    fl.add_argument("--output-dir", default="data/manifests/")

    # merge
    mg = sub.add_parser("merge", help="여러 manifest 합치기")
    mg.add_argument("--manifests", nargs="+", required=True)
    mg.add_argument("--output", required=True)

    args = p.parse_args()

    if args.cmd == "commonvoice":
        prepare_commonvoice(args.data_dir, args.output_dir)
    elif args.cmd == "commonvoice-hf":
        prepare_commonvoice_hf(args.output_dir)
    elif args.cmd == "fleurs":
        prepare_fleurs(args.output_dir)
    elif args.cmd == "merge":
        merge_manifests(args.manifests, args.output)


if __name__ == "__main__":
    main()
