"""Extract labelling frames straight off the NAS, one video at a time. Peak disk: one video.

The bulk copy-then-process driver put 44 GB of source video on disk that nothing needs
once the frames are out. WSL cannot open a UNC path itself without a root mount, so
"read it from the share" means: copy one file (PowerShell, Windows credentials), extract
from the local copy, delete it, next. Same total time -- the copy is a few percent of the
inference -- and nothing accumulates.

If a video is already local (an earlier run left it there) and its size matches the NAS
copy, it is used as-is and still deleted afterwards, so a restart converges to the same
footprint rather than keeping whatever happened to be around.

    python extract_from_nas.py                    # all four lanes, 6 fps
    python extract_from_nas.py --cams cam2 cam3   # a subset
    python extract_from_nas.py --nas item_videos_2   # another NAS folder -> labeling_all_2/
    python extract_from_nas.py --keep             # leave the videos on disk

Restart-safe: each lane keeps a done.txt of finished videos and a rerun skips them.

Output is per lane, the same layout extract_label_frames.py writes:

    data_test/labeling_all/<cam>/{images,labels,classes.txt,manifest.csv}
"""
import os
import csv
import sys
import types
import argparse
import subprocess

import torch

from detect_item import Detector, DEF_CFG, DEF_DET, REPO
from extract_label_frames import extract

ROOT = os.path.dirname(REPO)
# 사이트별 경로는 환경변수로 받는다 (.env.example 참고).
#   NAS_ROOT        NAS 공유의 UNC 경로, 예: \\nas\share\videos
#   NAS_FOLDER      NAS_ROOT 아래 기본 폴더 이름 (촬영 회차)
#   WSL_UNC_PREFIX  Windows 쪽에서 본 이 WSL 배포판의 UNC 접두어, 예: \\wsl.localhost\Ubuntu
NAS_ROOT = os.environ.get("NAS_ROOT") or sys.exit("set NAS_ROOT (UNC path of the NAS share)")
DEFAULT_NAS = os.environ.get("NAS_FOLDER", "item_videos")
WSL = os.environ.get("WSL_UNC_PREFIX", r"\\wsl.localhost\Ubuntu") + ROOT.replace("/", "\\")
STAGE = os.path.join(ROOT, "data_test", "nas")
CAMS = ["cam0", "cam1", "cam2", "cam3"]


def ps(cmd):
    """Run a PowerShell command; Windows credentials are what reach the share."""
    r = subprocess.run(["powershell.exe", "-NoProfile", "-c", cmd],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"powershell failed: {r.stderr.strip()[:300]}")
    return r.stdout.replace("\r", "")


def nas_listing(nas, cam):
    """[(name, size), ...] for one lane, in recording order."""
    out = ps(f"Get-ChildItem '{nas}\\{cam}_*.mp4' | ForEach-Object {{ '{{0}}|{{1}}' -f $_.Name, $_.Length }}")
    rows = [ln.split("|") for ln in out.splitlines() if "|" in ln]
    return sorted((n, int(s)) for n, s in rows)


def fetch(nas, folder, cam, name, size):
    """Local path to the video, copying from the NAS unless a complete copy is present.
    Staged under <folder>/<cam>/ so two NAS folders running side by side never share a
    directory, even for lanes with the same name."""
    local = os.path.join(STAGE, folder, cam, name)
    if os.path.isfile(local) and os.path.getsize(local) == size:
        return local, False
    os.makedirs(os.path.dirname(local), exist_ok=True)
    ps(f"Copy-Item '{nas}\\{name}' '{WSL}\\data_test\\nas\\{folder}\\{cam}\\' -Force")
    if not (os.path.isfile(local) and os.path.getsize(local) == size):
        raise RuntimeError(f"copy incomplete: {name}")
    return local, True


def prune_manifest(path, done):
    """Drop manifest rows for videos not in done.txt.

    A worker killed mid-video leaves that video's early frames in the manifest but not in
    done.txt; the rerun re-extracts it and would append them a second time. Keeping only
    rows for finished videos makes resume idempotent -- the images were overwritten under
    the same names anyway, this just keeps the index honest.
    """
    if not os.path.isfile(path):
        return 0
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    head, body = rows[0], rows[1:]
    kept = [r for r in body if r and r[0] + ".mp4" in done]
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(head); w.writerows(kept)
    return len(body) - len(kept)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nas", default=DEFAULT_NAS,
                   help="folder under NAS_ROOT (default NAS_FOLDER; suffixes _2, _3 map to labeling_all_2, _3)")
    p.add_argument("--out", default=None,
                   help="output root; default labeling_all plus the folder's suffix, "
                        "so item_videos_2 -> labeling_all_2")
    p.add_argument("--cams", nargs="+", default=CAMS)
    p.add_argument("--fps", type=float, default=6.0)
    p.add_argument("--det-thr", type=float, default=0.5)
    p.add_argument("--stride", type=int, default=1)
    p.add_argument("--keep", action="store_true", help="do not delete videos after extraction")
    p.add_argument("--limit", type=int, default=0, help="videos per lane (0 = all)")
    args = p.parse_args()
    xargs = types.SimpleNamespace(fps=args.fps, det_thr=args.det_thr, stride=args.stride)
    nas = NAS_ROOT + "\\" + args.nas
    suffix = args.nas[len(DEFAULT_NAS):] if args.nas.startswith(DEFAULT_NAS) else "_" + args.nas
    out_root = args.out or os.path.join(ROOT, "data_test", "labeling_all" + suffix)
    # Tag every log line with the folder so six workers writing one log stay readable.
    tag = f"[{suffix or 'main'}]"

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    det = Detector(DEF_CFG, DEF_DET, device)
    print(f"device {device}  weights {DEF_DET}", flush=True)

    grand = 0
    for cam in args.cams:
        files = nas_listing(nas, cam)
        if args.limit:
            files = files[:args.limit]
        out = os.path.join(out_root, cam)
        for d in ("images", "labels"):
            os.makedirs(os.path.join(out, d), exist_ok=True)
        with open(os.path.join(out, "classes.txt"), "w") as f:
            f.write("normal\nabnormal\n")
        # Resume support. A lane takes an hour or two and the process can die for
        # reasons that have nothing to do with the data (it already has, once). done.txt
        # lists every video fully processed; on restart those are skipped and the
        # manifest is appended to rather than rewritten. No done.txt means a fresh lane,
        # and the manifest starts over -- so a half-finished pass from before this
        # feature existed is redone cleanly instead of duplicated.
        done_path = os.path.join(out, "done.txt")
        done = set(open(done_path).read().split()) if os.path.isfile(done_path) else set()
        todo = [(n, s) for n, s in files if n not in done]
        print(f"CAM_START {tag} {cam} {len(files)} videos"
              + (f" ({len(done)} already done, {len(todo)} to go)" if done else ""), flush=True)

        kept = 0
        fresh = not done
        if not fresh:
            dropped = prune_manifest(os.path.join(out, "manifest.csv"), done)
            if dropped:
                print(f"RESUME {tag} {cam} dropped {dropped} manifest rows from an unfinished video",
                      flush=True)
        with open(os.path.join(out, "manifest.csv"), "w" if fresh else "a", newline="") as mf, \
             open(done_path, "a") as df:
            wr = csv.writer(mf)
            if fresh:
                wr.writerow(["video", "frame", "t_sec", "n_boxes", "max_conf"])
            for k, (name, size) in enumerate(todo, 1):
                try:
                    local, copied = fetch(nas, args.nas, cam, name, size)
                    n = extract(det, local, out, xargs, wr)
                    mf.flush()
                    kept += n
                    if not args.keep:
                        os.remove(local)
                    df.write(name + "\n"); df.flush()
                    print(f"FILE_DONE {tag} {cam} {k}/{len(todo)} {name} kept {n}"
                          f"{' (copied)' if copied else ' (was local)'}", flush=True)
                except Exception as e:
                    # One bad file must not stop the lane; the manifest already has
                    # everything before it and a re-run picks this one up again.
                    print(f"Error {tag} {cam} {name}: {type(e).__name__}: {e}", flush=True)
        grand += kept
        print(f"CAM_DONE {tag} {cam} {kept} frames", flush=True)
    print(f"ALL_DONE {tag} {grand} frames total", flush=True)


if __name__ == "__main__":
    main()
