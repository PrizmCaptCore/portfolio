"""Why is fps low? Separate camera-side, network-side, and host-side causes.

1. Dump the camera nodes that govern frame rate and GigE bandwidth.
2. Measure raw grab fps with ZERO host processing (retrieve+release only).
   - raw fps ~= ResultingFrameRate  -> host loop was never the bottleneck
   - raw fps << ResultingFrameRate  -> network/host delivery problem
"""
from pypylon import pylon
import os
import time
import sys

IP = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CAMERA_IP", "192.168.0.2")
N = 300

tlf = pylon.TlFactory.GetInstance()
di = pylon.DeviceInfo()
di.SetDeviceClass("BaslerGigE")
di.SetIpAddress(IP)
cam = pylon.InstantCamera(tlf.CreateDevice(di))
cam.Open()

print("--- camera nodes ---")
for node in ["ExposureAuto", "ExposureTimeAbs", "GainAuto",
             "AcquisitionFrameRateEnable", "AcquisitionFrameRateAbs",
             "ResultingFrameRateAbs",
             "GevSCPSPacketSize", "GevSCPD", "GevSCFTD",
             "PixelFormat", "Width", "Height"]:
    try:
        print(f"  {node:28s} = {getattr(cam, node).GetValue()}")
    except Exception as e:
        print(f"  {node:28s} = <unavailable: {type(e).__name__}>")

print(f"\n--- raw grab fps (no processing, {N} frames) ---")
cam.MaxNumBuffer.Value = 32
cam.StartGrabbingMax(N + 5, pylon.GrabStrategy_OneByOne)
n = failed = 0
t0 = time.monotonic()
while cam.IsGrabbing() and n < N:
    grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
    if grab.GrabSucceeded():
        n += 1
    else:
        failed += 1
    grab.Release()
elapsed = time.monotonic() - t0
cam.StopGrabbing()
print(f"frames={n} failed={failed} elapsed={elapsed:.1f}s raw_fps={n / elapsed:.1f}")
cam.Close()
