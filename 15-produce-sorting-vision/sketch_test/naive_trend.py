"""How much does RSS actually grow without fixed buffers?

Scenario A: transient naive - allocate frame copy + variable crops every
frame, drop them immediately (refcount frees instantly).
Scenario B: retained naive - same, but a bounded pool of crops is held and
replaced irregularly (mimics tracker holding crops until track close).
Pool is bounded, so any RSS growth beyond the pool's live size is
allocator retention (fragmentation high-water), not a leak.
"""
from pypylon import pylon
import os
import cv2
import sys
import time

UNTHROTTLE = "--unthrottle" in sys.argv
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
IP = _args[0] if _args else os.environ.get("CAMERA_IP", "192.168.0.2")
N_FRAMES = 3000
MAX_CROPS = 8
POOL = 512          # bounded retained-crop pool (scenario B)
H, W = 1024, 1280


def rss_kb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1])
    return -1


def open_cam():
    tlf = pylon.TlFactory.GetInstance()
    di = pylon.DeviceInfo()
    di.SetDeviceClass("BaslerGigE")
    di.SetIpAddress(IP)
    cam = pylon.InstantCamera(tlf.CreateDevice(di))
    cam.Open()
    return cam


def run(cam, scenario):
    converter = pylon.ImageFormatConverter()
    converter.OutputPixelFormat = pylon.PixelType_BGR8packed
    pool = [None] * POOL
    live_kb = 0

    cam.MaxNumBuffer.Value = 32
    cam.StartGrabbingMax(N_FRAMES + 5, pylon.GrabStrategy_OneByOne)
    i = 0
    samples = []
    t0 = time.monotonic()
    while cam.IsGrabbing() and i < N_FRAMES:
        grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
        if not grab.GrabSucceeded():
            grab.Release()
            continue
        img = converter.Convert(grab)
        frame = img.GetArray()                       # ~3.9 MB alloc/frame
        for k in range(MAX_CROPS):
            size = 60 + (i * 7 + k * 37) % 240
            y = (i * 13 + k * 61) % (H - size)
            x = (i * 29 + k * 97) % (W - size)
            crop = frame[y:y + size, x:x + size].copy()   # variable alloc
            resized = cv2.resize(crop, (224, 224))          # 150 KB alloc
            if scenario == "B":
                idx = (i * 131 + k * 17 + (i * i) // 7) % POOL  # irregular slot
                pool[idx] = crop                              # hold variable-size
        grab.Release()
        i += 1
        if i % 300 == 0:
            if scenario == "B":
                live_kb = sum(c.nbytes for c in pool if c is not None) // 1024
            samples.append((i, rss_kb(), live_kb))
    elapsed = time.monotonic() - t0
    cam.StopGrabbing()

    print(f"\n--- scenario {scenario} (processed {i / elapsed:.1f} fps) ---")
    hdr = f"{'frame':>6} {'RSS_KB':>9}"
    if scenario == "B":
        hdr += f" {'pool_live_KB':>13} {'retention_KB':>13}"
    print(hdr)
    base = samples[0]
    for s in samples:
        line = f"{s[0]:>6} {s[1]:>9}"
        if scenario == "B":
            line += f" {s[2]:>13} {s[1] - base[1] - (s[2] - base[2]):>13}"
        print(line)
    print(f"RSS delta frame300->end: {samples[-1][1] - base[1]:+d} KB")


cam = open_cam()
orig = None
if UNTHROTTLE:
    orig = (cam.GevSCPD.GetValue(), cam.AcquisitionFrameRateEnable.GetValue())
    cam.GevSCPD.SetValue(0)
    cam.AcquisitionFrameRateEnable.SetValue(False)
    print("unthrottled: ResultingFrameRate =",
          round(cam.ResultingFrameRateAbs.GetValue(), 1))
try:
    run(cam, "A")
    run(cam, "B")
finally:
    if orig is not None:
        cam.GevSCPD.SetValue(orig[0])
        cam.AcquisitionFrameRateEnable.SetValue(orig[1])
        print("restored: GevSCPD =", orig[0], "fps-cap =", orig[1])
    cam.Close()
