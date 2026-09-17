"""Continuous video-capture soak test.

Free-running acquisition (no frame cap) for --seconds, processing every frame:
  fixed : zero-copy grab -> debayer into ring slot -> 8 variable crop views
          -> resize into fixed batch slots      (recommended design)
  naive : converter.Convert -> GetArray copy -> crop.copy() + resize allocs,
          512-slot retained pool replaced irregularly (worst realistic case)

Samples every 15 s: elapsed, frames, fps, failed grabs, RSS, traced heap.
"""
from pypylon import pylon
import os
import numpy as np
import cv2
import tracemalloc
import time
import sys

MODE = sys.argv[1]                     # fixed | naive
SECONDS = int(sys.argv[2])
IP = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("CAMERA_IP", "192.168.0.2")
N_SLOTS = 8
MAX_CROPS = 8
POOL = 512
H, W = 1024, 1280
SAMPLE_EVERY = 15.0


def rss_kb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1])
    return -1


def ptr(a):
    return a.__array_interface__["data"][0]


tlf = pylon.TlFactory.GetInstance()
di = pylon.DeviceInfo()
di.SetDeviceClass("BaslerGigE")
di.SetIpAddress(IP)
cam = pylon.InstantCamera(tlf.CreateDevice(di))
cam.Open()
cam.MaxNumBuffer.Value = 32

converter = pylon.ImageFormatConverter()
converter.OutputPixelFormat = pylon.PixelType_BGR8packed

frame_ring = np.empty((N_SLOTS, H, W, 3), dtype=np.uint8)
cls_batch = np.empty((MAX_CROPS, 224, 224, 3), dtype=np.uint8)
ring_ptr0, batch_ptr0 = ptr(frame_ring), ptr(cls_batch)
pool = [None] * POOL

print(f"### mode={MODE} seconds={SECONDS} camera={IP} "
      f"pixfmt={cam.PixelFormat.GetValue()}", flush=True)
print(f"{'t_s':>5} {'frames':>7} {'fps':>6} {'failed':>6} "
      f"{'RSS_KB':>9} {'traced_KB':>10}", flush=True)

cam.StartGrabbing(pylon.GrabStrategy_OneByOne)   # continuous, no frame cap
tracemalloc.start()
t0 = time.monotonic()
next_sample = t0 + SAMPLE_EVERY
frames = failed = violations = 0
last_frames, last_t = 0, t0

while True:
    now = time.monotonic()
    if now - t0 >= SECONDS:
        break
    grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
    if not grab.GrabSucceeded():
        failed += 1
        grab.Release()
        continue

    if MODE == "fixed":
        slot = frames % N_SLOTS
        with grab.GetArrayZeroCopy() as raw:
            ret = cv2.cvtColor(raw, cv2.COLOR_BayerBG2BGR, dst=frame_ring[slot])
            if ptr(ret) != ptr(frame_ring[slot]):
                violations += 1
        frame = frame_ring[slot]
    else:
        img = converter.Convert(grab)
        frame = img.GetArray()

    i = frames
    for k in range(MAX_CROPS):
        size = 60 + (i * 7 + k * 37) % 240
        y = (i * 13 + k * 61) % (H - size)
        x = (i * 29 + k * 97) % (W - size)
        if MODE == "fixed":
            view = frame[y:y + size, x:x + size]
            ret = cv2.resize(view, (224, 224), dst=cls_batch[k])
            if ptr(ret) != ptr(cls_batch[k]):
                violations += 1
        else:
            crop = frame[y:y + size, x:x + size].copy()
            _ = cv2.resize(crop, (224, 224))
            idx = (i * 131 + k * 17 + (i * i) // 7) % POOL
            pool[idx] = crop

    if ptr(frame_ring) != ring_ptr0 or ptr(cls_batch) != batch_ptr0:
        violations += 1
    grab.Release()
    frames += 1

    if now >= next_sample:
        fps = (frames - last_frames) / (now - last_t)
        print(f"{now - t0:>5.0f} {frames:>7} {fps:>6.1f} {failed:>6} "
              f"{rss_kb():>9} {tracemalloc.get_traced_memory()[0] // 1024:>10}",
              flush=True)
        last_frames, last_t = frames, now
        next_sample += SAMPLE_EVERY

cam.StopGrabbing()
cam.Close()
elapsed = time.monotonic() - t0
print(f"### done mode={MODE}: frames={frames} avg_fps={frames / elapsed:.1f} "
      f"failed={failed} violations={violations} final_RSS_KB={rss_kb()}",
      flush=True)
