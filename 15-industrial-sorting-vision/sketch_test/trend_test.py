"""Fixed-buffer mode only, 3000 frames, RSS + traced memory sampled every 300
frames to distinguish one-time settling from a linear leak."""
from pypylon import pylon
import os
import numpy as np
import cv2
import tracemalloc
import sys

IP = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CAMERA_IP", "192.168.0.2")
N_FRAMES = 3000
N_SLOTS = 8
MAX_CROPS = 8
H, W = 1024, 1280


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

frame_ring = np.empty((N_SLOTS, H, W, 3), dtype=np.uint8)
cls_batch = np.empty((MAX_CROPS, 224, 224, 3), dtype=np.uint8)
frame_ring[:] = 0
cls_batch[:] = 0
ring_ptr0, batch_ptr0 = ptr(frame_ring), ptr(cls_batch)

cam.StartGrabbingMax(N_FRAMES + 5, pylon.GrabStrategy_OneByOne)
tracemalloc.start()
i = 0
violations = 0
print(f"{'frame':>6} {'RSS_KB':>9} {'traced_KB':>10}")
while cam.IsGrabbing() and i < N_FRAMES:
    grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
    if not grab.GrabSucceeded():
        grab.Release()
        continue
    slot = i % N_SLOTS
    with grab.GetArrayZeroCopy() as raw:
        cv2.cvtColor(raw, cv2.COLOR_BayerBG2BGR, dst=frame_ring[slot])
    for k in range(MAX_CROPS):
        size = 60 + (i * 7 + k * 37) % 240
        y = (i * 13 + k * 61) % (H - size)
        x = (i * 29 + k * 97) % (W - size)
        view = frame_ring[slot][y:y + size, x:x + size]
        ret = cv2.resize(view, (224, 224), dst=cls_batch[k])
        if ptr(ret) != ptr(cls_batch[k]):
            violations += 1
    if ptr(frame_ring) != ring_ptr0 or ptr(cls_batch) != batch_ptr0:
        violations += 1
    grab.Release()
    i += 1
    if i % 300 == 0:
        print(f"{i:>6} {rss_kb():>9} {tracemalloc.get_traced_memory()[0] // 1024:>10}")

cam.StopGrabbing()
cam.Close()
print("in-place/pointer violations:", violations)
