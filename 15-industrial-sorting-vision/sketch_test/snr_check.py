"""Temporal SNR measurement, EMVA-1288 style.

Grabs a burst of frames per camera and computes per-pixel temporal noise -- scene
texture cancels out because each pixel is compared with itself over time. As
configured below this measures the PGI pipeline output (YUV422, luma plane only;
the chroma bytes hover at ~128 and would poison the stats), so it is PIPELINE
SNR, not bare sensor SNR -- NR is at 0 but PGI's 5x5 demosaicing still smooths
luma slightly. For bare sensor numbers set PixelFormat back to "BayerBG8".
Keep the scene as still as you can; the median-based stats shrug off small
motion but not a person walking through.

    python snr_check.py          # 16 frames per camera
    python snr_check.py 32       # more frames = steadier numbers

Reads back exposure/gain first: if GainRaw is high or an Auto function is on,
fix that before blaming the sensor. The table shows noise vs brightness -- shot
noise must RISE as sqrt(signal) while SNR still improves with brightness; a high
floor at low brightness means read noise/gain, not light physics.
"""
import sys
import time

import numpy as np
from pypylon import pylon

FRAMES = next((int(a) for a in sys.argv[1:] if a.isdigit()), 16)
BINS = [(0, 16), (16, 48), (48, 96), (96, 160), (160, 224), (224, 250)]


def measure(dev_info, n_frames):
    sn = dev_info.GetSerialNumber()
    cam = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateDevice(dev_info))
    cam.Open()
    cam.PixelFormat.SetValue("YUV422Packed")   # PGI path; stats use the Y plane
    cam.DemosaicingMode.SetValue("BaslerPGI")
    cam.NoiseReductionAbs.SetValue(0.0)
    cam.SharpnessEnhancementAbs.SetValue(1.0)
    cam.AcquisitionFrameRateAbs.SetValue(15.0)
    for auto in ("ExposureAuto", "GainAuto", "BalanceWhiteAuto"):
        getattr(cam, auto).SetValue("Off")     # leftover viewer auto locks exposure
    cam.GainRaw.SetValue(cam.GainRaw.GetMin())
    cam.ExposureTimeAbs.SetValue(5000.0)
    print(f"\n== SN {sn} @ {dev_info.GetIpAddress()} ==")
    for node in ("ExposureTimeAbs", "GainRaw", "BlackLevelRaw",
                 "ExposureAuto", "GainAuto", "BalanceWhiteAuto", "PixelFormat"):
        try:
            print(f"  {node:16s} = {getattr(cam, node).GetValue()}")
        except Exception:
            pass

    cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
    stack = []
    t0 = time.perf_counter()
    try:
        while len(stack) < n_frames and time.perf_counter() - t0 < 30:
            res = cam.RetrieveResult(2000, pylon.TimeoutHandling_Return)
            if res is None:
                continue
            if res.GrabSucceeded():
                arr = res.Array
                if arr.ndim == 3:              # YUV422 (H, W, 2): UYVY pairs,
                    arr = arr[:, :, 1]         # byte 1 of each pair is luma
                stack.append(arr.astype(np.float32))
            res.Release()
    finally:
        cam.StopGrabbing()
        cam.Close()
    if len(stack) < 4:
        print(f"  only {len(stack)} frames -- skipping")
        return

    cube = np.stack(stack)                      # (N, H, W)
    mu = cube.mean(axis=0)
    sigma = cube.std(axis=0, ddof=1)
    sat = float((mu >= 234).mean())            # video-range Y tops out near 235

    print(f"  frames={len(stack)}  saturated(>=234)={sat * 100:.2f}%")
    print(f"  {'brightness':>12s} {'pixels%':>8s} {'noise(DN)':>10s} {'SNR':>7s} {'SNR(dB)':>8s}")
    for lo, hi in BINS:
        m = (mu >= lo) & (mu < hi)
        if m.sum() < 1000:
            continue
        s = float(np.median(sigma[m]))          # median: robust to small motion
        b = float(np.median(mu[m]))
        snr = b / s if s > 0 else float("inf")
        print(f"  {f'{lo}-{hi}':>12s} {m.mean() * 100:7.1f}% {s:10.2f} "
              f"{snr:7.1f} {20 * np.log10(snr):7.1f}dB")


def main():
    devs = pylon.TlFactory.GetInstance().EnumerateDevices()
    if not devs:
        sys.exit("no cameras found")
    for d in devs:
        measure(d, FRAMES)


if __name__ == "__main__":
    main()
