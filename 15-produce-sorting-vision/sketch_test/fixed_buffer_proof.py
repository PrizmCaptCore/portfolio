"""Empirical proof: fixed-buffer pipeline vs naive per-frame allocation.

Camera is BayerBG8. Fixed path: zero-copy access to pylon grab buffer ->
cv2.cvtColor debayer directly into preallocated ring slot -> crop views ->
cv2.resize into preallocated batch slots. Verifies pointers + measures churn.
"""
from pypylon import pylon
import os
import numpy as np
import cv2
import tracemalloc
import sys

IP = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CAMERA_IP", "192.168.0.2")
N_FRAMES = 600
WARMUP = 60
N_SLOTS = 8
MAX_CROPS = 8
H, W = 1024, 1280


def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024.0
    return -1.0


def ptr(a):
    return a.__array_interface__["data"][0]


def open_camera():
    tlf = pylon.TlFactory.GetInstance()
    di = pylon.DeviceInfo()
    di.SetDeviceClass("BaslerGigE")
    di.SetIpAddress(IP)
    cam = pylon.InstantCamera(tlf.CreateDevice(di))
    cam.Open()
    print("camera:", cam.GetDeviceInfo().GetModelName(),
          "pixfmt:", cam.PixelFormat.GetValue())
    return cam


def run_mode(cam, mode, converter):
    frame_ring = np.empty((N_SLOTS, H, W, 3), dtype=np.uint8)
    cls_batch = np.empty((MAX_CROPS, 224, 224, 3), dtype=np.uint8)
    ring_ptr0 = ptr(frame_ring)
    batch_ptr0 = ptr(cls_batch)

    cam.StartGrabbingMax(N_FRAMES + 5, pylon.GrabStrategy_OneByOne)
    i = 0
    rss_start = tr_start = None
    cvt_violations = resize_violations = ptr_violations = 0

    while cam.IsGrabbing() and i < N_FRAMES:
        grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
        if not grab.GrabSucceeded():
            grab.Release()
            continue

        if i == WARMUP:
            tracemalloc.start()
            tr_start = tracemalloc.get_traced_memory()[0]
            rss_start = rss_mb()

        if mode == "fixed":
            slot = i % N_SLOTS
            with grab.GetArrayZeroCopy() as raw:          # view of pylon pool buffer
                ret = cv2.cvtColor(raw, cv2.COLOR_BayerBG2BGR,
                                   dst=frame_ring[slot])
                if ptr(ret) != ptr(frame_ring[slot]):
                    cvt_violations += 1
            frame = frame_ring[slot]
        else:
            img = converter.Convert(grab)      # new PylonImage
            frame = img.GetArray()             # new ndarray copy every frame

        for k in range(MAX_CROPS):
            size = 60 + (i * 7 + k * 37) % 240
            y = (i * 13 + k * 61) % (H - size)
            x = (i * 29 + k * 97) % (W - size)
            if mode == "fixed":
                view = frame[y:y + size, x:x + size]      # view: no pixel copy
                ret = cv2.resize(view, (224, 224), dst=cls_batch[k],
                                 interpolation=cv2.INTER_LINEAR)
                if ptr(ret) != ptr(cls_batch[k]):
                    resize_violations += 1
            else:
                crop = frame[y:y + size, x:x + size].copy()   # variable-size alloc
                _ = cv2.resize(crop, (224, 224))               # another alloc

        if ptr(frame_ring) != ring_ptr0 or ptr(cls_batch) != batch_ptr0:
            ptr_violations += 1

        grab.Release()
        i += 1

    cam.StopGrabbing()
    tr_end, tr_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_end = rss_mb()

    print(f"\n[{mode}] frames={i} crops={i * MAX_CROPS}")
    print(f"  ring/batch data ptr stable    : {'YES' if ptr_violations == 0 else f'NO ({ptr_violations})'}")
    if mode == "fixed":
        print(f"  cvtColor wrote in place       : {'YES' if cvt_violations == 0 else f'NO ({cvt_violations})'}")
        print(f"  resize wrote in place         : {'YES' if resize_violations == 0 else f'NO ({resize_violations})'}")
    print(f"  python-traced net growth      : {(tr_end - tr_start) / 1024:.1f} KB over {i - WARMUP} frames")
    print(f"  python-traced churn peak      : {tr_peak / 1024 / 1024:.1f} MB")
    print(f"  RSS frame{WARMUP} -> end      : {rss_start:.1f} -> {rss_end:.1f} MB (delta {rss_end - rss_start:+.1f})")


def main():
    cam = open_camera()
    converter = pylon.ImageFormatConverter()
    converter.OutputPixelFormat = pylon.PixelType_BGR8packed

    cam.StartGrabbingMax(1)
    grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
    has_zc = hasattr(grab, "GetArrayZeroCopy")
    print("GetArrayZeroCopy available:", has_zc)
    grab.Release()
    cam.StopGrabbing()
    if not has_zc:
        print("zero-copy unavailable in this pypylon -> abort")
        sys.exit(1)

    run_mode(cam, "fixed", converter)
    run_mode(cam, "naive", converter)
    cam.Close()


if __name__ == "__main__":
    main()
