"""Day-scale naive-mode soak test, safe to leave unattended.

Scenario A: allocate per frame, drop immediately.
Scenario B (default): + 512-slot retained crop pool replaced irregularly
                      (realistic worst case, mimics tracker retention).

Features for unattended runs:
  - duration-based (--hours/--minutes), samples once a minute with wall-clock
    timestamps
  - survives camera/link drops: logs the error, reconnects, keeps counting
  - --unthrottle lifts GevSCPD + fps cap for the run and restores them at the
    end (re-applied automatically after every reconnect)
  - Ctrl-C prints the summary instead of dying silently

Usage:
  daily_soak.py [a|b] [--hours H] [--minutes M] [--unthrottle] [IP]
Example (24h, scenario B, full frame rate):
  nohup .venv/bin/python daily_soak.py b --hours 24 --unthrottle \
      $CAMERA_IP > soak_$(date +%Y%m%d_%H%M).log 2>&1 &
"""
from pypylon import pylon
from datetime import datetime
import os
import cv2
import time
import sys

argv = sys.argv[1:]
UNTHROTTLE = "--unthrottle" in argv
duration_s = 24 * 3600.0
if "--hours" in argv:
    duration_s = float(argv[argv.index("--hours") + 1]) * 3600.0
if "--minutes" in argv:
    duration_s = float(argv[argv.index("--minutes") + 1]) * 60.0
pos = [a for a in argv if not a.startswith("--")
       and a not in {argv[argv.index(f) + 1] for f in ("--hours", "--minutes") if f in argv}]
MODE = pos[0].lower() if pos and pos[0].lower() in ("a", "b") else "b"
IP = next((a for a in pos if a.count(".") == 3), os.environ.get("CAMERA_IP", "192.168.0.2"))

POOL = 512
MAX_CROPS = 8
H, W = 1024, 1280
SAMPLE_EVERY = 60.0


def rss_kb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1])
    return -1


def now():
    return datetime.now().isoformat(timespec="seconds")


def open_cam():
    tlf = pylon.TlFactory.GetInstance()
    di = pylon.DeviceInfo()
    di.SetDeviceClass("BaslerGigE")
    di.SetIpAddress(IP)
    cam = pylon.InstantCamera(tlf.CreateDevice(di))
    cam.Open()
    cam.MaxNumBuffer.Value = 32
    return cam


print(f"{now()} start mode={MODE} duration_s={duration_s:.0f} "
      f"unthrottle={UNTHROTTLE} camera={IP}", flush=True)
print(f"{'timestamp':>19} {'elap_s':>7} {'frames':>9} {'fps':>6} "
      f"{'failed':>6} {'reconn':>6} {'RSS_KB':>9} {'pool_MB':>8}", flush=True)

pool = [None] * POOL
converter = None
orig_throttle = None          # (GevSCPD, fps_cap_enable) captured on first connect
t0 = time.monotonic()
frames = failed = reconnects = 0
last_frames, last_t = 0, t0
next_sample = t0 + SAMPLE_EVERY
cam = None

try:
    while time.monotonic() - t0 < duration_s:
        try:
            cam = open_cam()
            if orig_throttle is None:
                orig_throttle = (cam.GevSCPD.GetValue(),
                                 cam.AcquisitionFrameRateEnable.GetValue())
                print(f"{now()} camera as-found: GevSCPD={orig_throttle[0]} "
                      f"fps_cap={orig_throttle[1]}", flush=True)
            if UNTHROTTLE:
                cam.GevSCPD.SetValue(0)
                cam.AcquisitionFrameRateEnable.SetValue(False)
            converter = pylon.ImageFormatConverter()
            converter.OutputPixelFormat = pylon.PixelType_BGR8packed
            cam.StartGrabbing(pylon.GrabStrategy_OneByOne)

            while time.monotonic() - t0 < duration_s:
                grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
                if not grab.GrabSucceeded():
                    failed += 1
                    grab.Release()
                    continue
                img = converter.Convert(grab)
                frame = img.GetArray()                        # per-frame copy
                i = frames
                for k in range(MAX_CROPS):
                    size = 60 + (i * 7 + k * 37) % 240
                    y = (i * 13 + k * 61) % (H - size)
                    x = (i * 29 + k * 97) % (W - size)
                    crop = frame[y:y + size, x:x + size].copy()
                    _ = cv2.resize(crop, (224, 224))
                    if MODE == "b":
                        idx = (i * 131 + k * 17 + (i * i) // 7) % POOL
                        pool[idx] = crop
                grab.Release()
                frames += 1

                t = time.monotonic()
                if t >= next_sample:
                    fps = (frames - last_frames) / (t - last_t)
                    pool_mb = sum(c.nbytes for c in pool if c is not None) / 1e6
                    print(f"{now():>19} {t - t0:>7.0f} {frames:>9} {fps:>6.1f} "
                          f"{failed:>6} {reconnects:>6} {rss_kb():>9} "
                          f"{pool_mb:>8.1f}", flush=True)
                    last_frames, last_t = frames, t
                    next_sample += SAMPLE_EVERY

            break                                             # duration reached
        except (pylon.RuntimeException, pylon.TimeoutException, OSError) as e:
            reconnects += 1
            print(f"{now()} DISCONNECT #{reconnects}: {type(e).__name__}: {e}",
                  flush=True)
            try:
                if cam is not None:
                    cam.Close()
            except Exception:
                pass
            cam = None
            time.sleep(5.0)
except KeyboardInterrupt:
    print(f"{now()} interrupted by user", flush=True)
finally:
    try:
        if UNTHROTTLE and orig_throttle is not None:
            if cam is None or not cam.IsOpen():
                cam = open_cam()
            if cam.IsGrabbing():
                cam.StopGrabbing()
            cam.GevSCPD.SetValue(orig_throttle[0])
            cam.AcquisitionFrameRateEnable.SetValue(orig_throttle[1])
            print(f"{now()} throttle restored: GevSCPD={orig_throttle[0]} "
                  f"fps_cap={orig_throttle[1]}", flush=True)
        if cam is not None and cam.IsOpen():
            cam.Close()
    except Exception as e:
        print(f"{now()} WARNING: restore/close failed ({e}) — GevSCPD is a "
              f"volatile register, a camera power cycle also resets it", flush=True)
    elapsed = time.monotonic() - t0
    print(f"{now()} done: mode={MODE} elapsed_s={elapsed:.0f} frames={frames} "
          f"avg_fps={frames / elapsed if elapsed else 0:.1f} failed={failed} "
          f"reconnects={reconnects} final_RSS_KB={rss_kb()}", flush=True)
