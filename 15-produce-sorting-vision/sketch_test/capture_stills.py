"""Grab stills from every connected camera.

Default mode is the dataset-collection sanity check: same grab (LatestImageOnly)
and debayer (BayerRG2BGR) as live_view and the future inference loop, so what
lands on disk is what the detector sees.

    python capture_stills.py                # 10 frames per camera
    python capture_stills.py 25             # 25 frames per camera
    python capture_stills.py 10 --every 5   # keep every 5th grabbed frame

--nice mode is the opposite: phone-style processed snapshots for human eyes --
reports, demos, "what does it actually look like". Each shot averages a BURST of
raw frames (noise / sqrt(12)), white-balances gray-world in the Bayer domain,
gently auto-levels, debayers with VNG, applies 2.2 gamma (sensor output is
linear -- THIS is most of why raw frames look dark next to a phone), then
median-cleans chroma and lightly sharpens luma. Subject must hold still for
~0.4 s per shot. NEVER feed --nice output to the model: multi-frame merge is
impossible on a moving belt and the tone pipeline breaks train/infer parity.

    python capture_stills.py 3 --nice       # 3 processed shots per camera

Frames go to captures/<timestamp>/<SN>_<n>.jpg (quality 95).
"""
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np
from pypylon import pylon

COUNT = next((int(a) for a in sys.argv[1:] if a.isdigit()), 10)
EVERY = int(sys.argv[sys.argv.index("--every") + 1]) if "--every" in sys.argv else 5
NICE = "--nice" in sys.argv
BURST = 12                   # frames averaged per --nice shot
QUALITY = 95


def open_camera(dev_info):
    cam = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateDevice(dev_info))
    cam.Open()
    cam.PixelFormat.SetValue("BayerBG8")   # live_view's PGI mode may have left YUV
    cam.AcquisitionFrameRateEnable.SetValue(True)
    cam.AcquisitionFrameRateAbs.SetValue(30.0)
    cam.GevSCPD.SetValue(2500)
    return cam


def nice_process(raw):
    """Phone-style development of an averaged raw Bayer frame (float32 HxW).

    Order matters: WB and leveling happen in the linear Bayer domain (before
    quantization, so the boosted weak channels keep their precision), gamma
    only after debayer, and denoise/sharpen on separated chroma/luma."""
    # Gray-world WB. BayerBG8 is BGGR: B at even/even, R at odd/odd.
    g = (raw[0::2, 1::2].mean() + raw[1::2, 0::2].mean()) / 2
    raw = raw.copy()
    raw[1::2, 1::2] *= min(4.0, g / max(raw[1::2, 1::2].mean(), 1e-6))
    raw[0::2, 0::2] *= min(4.0, g / max(raw[0::2, 0::2].mean(), 1e-6))
    # Gentle auto-level: near-highlights up to ~245, boost capped at 4x.
    raw *= min(4.0, 245.0 / max(float(np.percentile(raw, 99.5)), 1.0))
    bgr = cv2.cvtColor(np.clip(raw, 0, 255).astype(np.uint8),
                       cv2.COLOR_BayerRG2BGR_VNG)
    lut = (np.power(np.arange(256) / 255.0, 1 / 2.2) * 255).astype(np.uint8)
    ycc = cv2.cvtColor(lut[bgr], cv2.COLOR_BGR2YCrCb)
    y = ycc[:, :, 0].astype(np.float32)
    ycc[:, :, 1] = cv2.medianBlur(ycc[:, :, 1], 5)      # kill rainbow speckle
    ycc[:, :, 2] = cv2.medianBlur(ycc[:, :, 2], 5)
    ycc[:, :, 0] = np.clip(y + 0.6 * (y - cv2.GaussianBlur(y, (0, 0), 1.2)),
                           0, 255).astype(np.uint8)     # unsharp on luma only
    return cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)


def capture_nice(dev_info, out_dir, count):
    sn = dev_info.GetSerialNumber()
    cam = open_camera(dev_info)
    print(f"{sn}: exposure {cam.ExposureTimeAbs.GetValue() / 1000:.1f} ms, "
          f"{BURST}-frame bursts", flush=True)
    cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
    t0 = time.perf_counter()
    try:
        for shot in range(1, count + 1):
            frames = []
            while len(frames) < BURST and time.perf_counter() - t0 < count * 3 + 15:
                res = cam.RetrieveResult(2000, pylon.TimeoutHandling_Return)
                if res and res.GrabSucceeded():
                    frames.append(res.Array.astype(np.float32))
                if res:
                    res.Release()
            if len(frames) < BURST:
                print(f"{sn}: burst starved ({len(frames)}/{BURST}), stopping",
                      flush=True)
                break
            img = nice_process(np.mean(frames, axis=0))
            cv2.imwrite(os.path.join(out_dir, f"{sn}_nice_{shot:03d}.jpg"),
                        img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
            print(f"{sn}: nice shot {shot}/{count}", flush=True)
    finally:
        cam.StopGrabbing()
        cam.Close()


def capture(dev_info, out_dir, count, every):
    sn = dev_info.GetSerialNumber()
    cam = open_camera(dev_info)
    cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
    saved = grabbed = 0
    t0 = time.perf_counter()
    try:
        while saved < count and time.perf_counter() - t0 < count * every / 30.0 + 15:
            res = cam.RetrieveResult(2000, pylon.TimeoutHandling_Return)
            if res is None:
                print(f"{sn}: no frame within 2 s", flush=True)
                continue
            if not res.GrabSucceeded():
                res.Release()
                continue
            grabbed += 1
            if grabbed % every:
                res.Release()
                continue
            bgr = cv2.cvtColor(res.Array, cv2.COLOR_BayerRG2BGR)
            res.Release()
            saved += 1
            path = os.path.join(out_dir, f"{sn}_{saved:03d}.jpg")
            cv2.imwrite(path, bgr, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
    finally:
        cam.StopGrabbing()
        cam.Close()
    print(f"{sn}: saved {saved}/{count} ({grabbed} grabbed, "
          f"{time.perf_counter() - t0:.1f} s)", flush=True)
    return saved


def main():
    devs = pylon.TlFactory.GetInstance().EnumerateDevices()
    if not devs:
        sys.exit("no cameras found")
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "captures", datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    print(f"-> {out_dir}", flush=True)
    for d in devs:
        if NICE:
            capture_nice(d, out_dir, COUNT)
        else:
            capture(d, out_dir, COUNT, EVERY)


if __name__ == "__main__":
    main()
