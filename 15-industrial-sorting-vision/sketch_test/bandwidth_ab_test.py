"""A/B confirm: is GevSCPD (inter-packet delay) the fps bottleneck?

Temporarily sets GevSCPD=0 and disables the AcquisitionFrameRate cap,
measures raw grab fps, then RESTORES the original values.
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

orig = {
    "GevSCPD": cam.GevSCPD.GetValue(),
    "AcquisitionFrameRateEnable": cam.AcquisitionFrameRateEnable.GetValue(),
    "AcquisitionFrameRateAbs": cam.AcquisitionFrameRateAbs.GetValue(),
}
print("original:", orig)


def raw_fps(label):
    print(f"[{label}] ResultingFrameRateAbs =",
          round(cam.ResultingFrameRateAbs.GetValue(), 1))
    cam.MaxNumBuffer.Value = 64
    cam.StartGrabbingMax(N + 5, pylon.GrabStrategy_OneByOne)
    n = failed = 0
    t0 = time.monotonic()
    while cam.IsGrabbing() and n + failed < N:
        grab = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
        if grab.GrabSucceeded():
            n += 1
        else:
            failed += 1
        grab.Release()
    elapsed = time.monotonic() - t0
    cam.StopGrabbing()
    print(f"[{label}] ok={n} failed={failed} fps={n / elapsed:.1f}")


try:
    raw_fps("throttled (as found)")
    cam.GevSCPD.SetValue(0)
    cam.AcquisitionFrameRateEnable.SetValue(False)
    raw_fps("unthrottled (SCPD=0, no fps cap)")
finally:
    cam.GevSCPD.SetValue(orig["GevSCPD"])
    cam.AcquisitionFrameRateEnable.SetValue(orig["AcquisitionFrameRateEnable"])
    cam.AcquisitionFrameRateAbs.SetValue(orig["AcquisitionFrameRateAbs"])
    print("restored:", {k: getattr(cam, k).GetValue() for k in orig})
    cam.Close()
