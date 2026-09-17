"""Post-extraction step 1 of 2 (run 2026-09-07 on data_test/labeling_all*).

The YOLO pre-labels written by extract_label_frames.py carry no per-box score, only the frame's
max_conf in manifest.csv. To tell wheel-pocket ghosts from real potatoes we need the score of
each box, so this re-runs the same 1-class detector on the candidate frames and records every
box >= 0.30 with its confidence and aspect ratio. Candidates: frame max_conf < 0.70, or any
label box with aspect > 1.6 (the cup-carrier wheel pockets are ~2:1 wide).

    python wheel_ghost_redetect.py all_manifest.csv out.csv [start_index]

all_manifest.csv is the three lane manifests concatenated with a leading "lane" column
(labeling_all/cam0, ...). start_index resumes after a crash; unreadable images are listed in
out.csv.missing instead of aborting (a batch of images had been deleted by hand mid-run).
Paths are hardcoded for that run. Output feeds wheel_ghost_clean.py.
"""
import sys, os, csv, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cv2, torch
from detect_potato import Detector, DEF_CFG, DEF_DET

DT = os.environ.get("DATA_TEST_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data_test")); W, H = 1280, 1024

rows = list(csv.reader(open(sys.argv[1])))
start = int(sys.argv[3]) if len(sys.argv) > 3 else 0
cand = []
for lane, vid, fr, t, nb, mc in rows:
    name = f"{vid}_f{int(fr):05d}"; wide = False
    if float(mc) >= 0.70:
        for line in open(os.path.join(DT, lane, "labels", name + ".txt")):
            p = line.split()
            if float(p[3]) * W / (float(p[4]) * H) > 1.6:
                wide = True; break
    if float(mc) < 0.70 or wide:
        cand.append((lane, name, mc))
cand = cand[start:]
print("candidates", len(cand), flush=True)

det = Detector(DEF_CFG, DEF_DET, torch.device("cuda")); t0 = time.time(); missing = 0
with open(sys.argv[2], "w", newline="") as f, open(sys.argv[2] + ".missing", "w") as mf:
    w = csv.writer(f); w.writerow(["lane", "name", "old_max_conf", "x1", "y1", "x2", "y2", "conf", "aspect"])
    for k, (lane, name, mc) in enumerate(cand, 1):
        img = cv2.imread(os.path.join(DT, lane, "images", name + ".jpg"))
        if img is None:
            missing += 1; mf.write(f"{lane},{name}\n"); continue
        for x1, y1, x2, y2, s in det(img, 0.30):
            w.writerow([lane, name, mc, int(x1), int(y1), int(x2), int(y2), f"{s:.3f}", f"{(x2-x1)/max(y2-y1,1):.2f}"])
        if k % 2000 == 0:
            print(f"{k}/{len(cand)} {time.time()-t0:.0f}s missing={missing}", flush=True)
print(f"REDETECT_DONE {len(cand)} frames missing={missing} {time.time()-t0:.0f}s", flush=True)
